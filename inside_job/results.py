"""Usage accounting from a log, the token report, and the games/index.jsonl summary row."""

from __future__ import annotations

import json
from pathlib import Path

from .config import is_openrouter_model
from .llm import USAGE_KEYS, add_usage, zero_usage


def billed_split(by_model: dict) -> tuple[float, float]:
    """(billed, notional) dollars from per-model usage. OpenRouter models (ids with a "/") are
    billed to the owner's key; Claude models report the CLI's list-price equivalent, which the
    subscription does not bill (docs/OPENROUTER.md)."""
    billed = notional = 0.0
    for m, r in (by_model or {}).items():
        c = (r or {}).get("cost_usd", 0.0) or 0.0
        if is_openrouter_model(m):
            billed += c
        else:
            notional += c
    return round(billed, 6), round(notional, 6)


def usage_from_events(events: list[dict]) -> tuple[dict, int]:
    """Sum usage per *requested* model over every attempt (turns and narrator recaps).

    Returns ({"by_model": {model: {calls, input, ..., blocked, fallbacks}}, "total": {...}}, calls).
    `blocked` counts attempts refused by the model's safety filter; `fallbacks` counts turns that
    fell back plus, for the narrator model, recaps that failed.
    """
    by_model: dict[str, dict] = {}

    def add(model: str, usage: dict, calls: int, served: str | None, blocked: int, fallback: bool):
        row = by_model.setdefault(model, dict(zero_usage(), calls=0, blocked=0, fallbacks=0, served=[]))
        merged = add_usage(row, usage or {})
        for k in USAGE_KEYS:
            row[k] = merged[k]
        row["calls"] += calls
        row["blocked"] += blocked or 0
        row["fallbacks"] += 1 if fallback else 0
        if served and served not in row["served"]:
            row["served"].append(served)

    for e in events:
        if e["type"] == "turn":
            add(e["model"], e.get("usage"), e.get("attempts", 1), e.get("served_model"), e.get("blocked", 0),
                bool(e.get("fallback")))
        elif e["type"] == "recap":
            add(e["model"], e.get("usage"), e.get("attempts", 1), e.get("served_model"), e.get("blocked", 0),
                bool(e.get("error")))
    total = dict(zero_usage(), calls=0, blocked=0, fallbacks=0)
    for row in by_model.values():
        merged = add_usage(total, row)
        for k in USAGE_KEYS:
            total[k] = merged[k]
        for k in ("calls", "blocked", "fallbacks"):
            total[k] += row[k]
    ordered = {k: by_model[k] for k in sorted(by_model)}
    return {"by_model": ordered, "total": total}, total["calls"]


def conditions(events: list[dict]) -> dict:
    """The call controls a game ran under (benchmark conditions), from its logged config."""
    start = next((e for e in events if e["type"] == "game_start"), None)
    lim = ((start or {}).get("config") or {}).get("limits") or {}
    return {"max_thinking_tokens": lim.get("max_thinking_tokens", -1), "effort": lim.get("effort", "")}


def openrouter_conditions(events: list[dict]) -> dict:
    """The OpenRouter output limits a game ran under, from its logged config ({} when the config has
    no [openrouter] table). A config logged before per-model limits existed gives {} and None: one
    limit for every model and no escalation."""
    start = next((e for e in events if e["type"] == "game_start"), None)
    orc = ((start or {}).get("config") or {}).get("openrouter")
    if not isinstance(orc, dict):
        return {}
    return {"max_output_tokens": orc.get("max_output_tokens"),
            "max_output_tokens_by_model": dict(orc.get("max_output_tokens_by_model") or {}),
            "max_output_tokens_ceiling": orc.get("max_output_tokens_ceiling")}


def conditions_line(events: list[dict]) -> str:
    c = conditions(events)
    t = c["max_thinking_tokens"]
    cap = "unset" if t == -1 else ("off" if t == 0 else str(t))
    return f"thinking cap: {cap}   effort: {c['effort'] or 'not passed'}"


def token_report(events: list[dict]) -> str:
    """Plain-text token report (by requested model, then totals)."""
    end = next((e for e in events if e["type"] == "game_end"), None)
    usage, calls = usage_from_events(events)
    fallbacks = sum(1 for e in events if e["type"] == "turn" and e.get("fallback"))
    hdr = ("model", "calls", "input", "output", "cache_read", "cache_write", "thinking", "blocked",
           "fallbacks", "cost_usd")
    rows = []
    for m, r in usage["by_model"].items():
        rows.append((m, r["calls"], r["input"], r["output"], r["cache_read"], r["cache_creation"],
                     r["thinking"], r["blocked"], r["fallbacks"], f"{r['cost_usd']:.4f}"))
    t = usage["total"]
    rows.append(("TOTAL", t["calls"], t["input"], t["output"], t["cache_read"], t["cache_creation"],
                 t["thinking"], t["blocked"], t["fallbacks"], f"{t['cost_usd']:.4f}"))
    widths = [max(len(str(x)) for x in col) for col in zip(hdr, *rows)]
    fmt = lambda row: "  ".join(str(v).ljust(w) if i == 0 else str(v).rjust(w)
                                for i, (v, w) in enumerate(zip(row, widths)))
    lines = [conditions_line(events), "", fmt(hdr), fmt(["-" * w for w in widths])] + [fmt(r) for r in rows]
    served_notes = [f"{m} served as {', '.join(r['served'])}" for m, r in usage["by_model"].items()
                    if r["served"] and r["served"] != [m]]
    lines.append("")
    wall = end.get("wall_s") if end else None
    lines.append(f"calls: {calls}   fallbacks: {fallbacks}   wall time: "
                 f"{f'{wall:.1f}s' if wall is not None else 'n/a (game did not finish)'}")
    if any(is_openrouter_model(m) for m in usage["by_model"]):
        billed, notional = billed_split(usage["by_model"])
        lines.append(f"billed (OpenRouter models, real money): ${billed:.4f}   notional (Claude models, "
                     f"the CLI's list-price equivalent, not billed): ${notional:.4f}")
    else:
        lines.append("cost_usd is the CLI's list-price equivalent; subscription calls are not billed per token.")
    for n in served_notes:
        lines.append("note: " + n)
    return "\n".join(lines)


def index_row(events: list[dict], log_path: str, spoiled: bool = False, raw: str | None = None) -> dict:
    """One games/index.jsonl row. `batch` is the `batch` run's name (null for other games);
    `spoiled` marks a game that tripped the batch stop rule (it does not count as finished);
    `raw` is the game's raw sidecar file (docs/RAWLOG.md) or null; `code_hash` is the code stamp
    on game_start (null for unstamped games)."""
    start = next(e for e in events if e["type"] == "game_start")
    end = next(e for e in events if e["type"] == "game_end")
    elim = {e["eliminated"]: e["round"] for e in events if e["type"] == "vote_result"}
    fin = next((e for e in events if e["type"] == "finale_result"), None)
    players = []
    for p in start["players"]:
        players.append({"name": p["name"], "model": p["model"], "model_name": p["model_name"],
                        "role": p["role"], "seat": p["seat"], "eliminated_round": elim.get(p["name"]),
                        "payout": end["payouts"].get(p["name"], 0)})
    return {
        "game_id": start["game_id"], "seed": start["seed"], "rules_version": start["rules_version"],
        "anonymised": start.get("anonymised", False), "trial": start.get("trial"),
        "batch": start.get("batch"), "spoiled": bool(spoiled),
        "winner": end["winner"], "reason": end["reason"],
        "clean_jobs": end.get("clean_jobs", 0), "blown_jobs": end.get("blown_jobs", 0), "rounds": end["rounds"],
        "players": players,
        "finale": ({"finalists": fin["finalists"], "choices": fin["choices"], "stated": fin["stated"]}
                   if fin else None),
        "calls": end["calls"], "fallbacks": end["fallbacks"],
        "blocked": end["usage"]["total"].get("blocked", 0),
        "by_model": {m: {"calls": r["calls"], "blocked": r.get("blocked", 0), "fallbacks": r.get("fallbacks", 0)}
                     for m, r in end["usage"]["by_model"].items()},
        # Games with an [openrouter] table add its output limits (all-Claude rows are unchanged).
        "conditions": {**(end.get("conditions") or conditions(events)), **openrouter_conditions(events)},
        "tokens": end["usage"]["total"],
        # Real money: the cost of the OpenRouter models (ids with "/"); `tokens.cost_usd` stays the sum
        # of every model's cost, Claude's notional list price included (docs/OPENROUTER.md).
        "billed_usd": billed_split(end["usage"]["by_model"])[0],
        "wall_s": end["wall_s"], "log": str(log_path),
        "raw": str(raw) if raw else None, "code_hash": start.get("code_hash"),
    }


def append_index(events: list[dict], log_path: str, index_path: str | Path, spoiled: bool = False,
                 raw: str | None = None) -> dict:
    row = index_row(events, log_path, spoiled, raw)
    p = Path(index_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row
