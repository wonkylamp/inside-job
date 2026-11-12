"""Read probes, version 1 (docs/PROBES.md): logged crew vote turns frozen as hashed prompt text,
replayed to a model one call each, and scored against the truth and the arithmetic formulas.

Standard library only; never imports `analysis` (the tests cross-check against it).

A probe line holds `system`, `prompt` and `schema` exactly as the seat received them, and
`probe_id` = first 16 hex of sha256 over `system + NUL + prompt + NUL + schema` (the schema as
compact JSON with sorted keys). Every key of a line is written sorted except inside `schema`,
whose key order is kept as the engine built it: `build_argv` sends the schema in that order, so
sorting it would change the bytes the model sees.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import random
import statistics
import sys
import time
from math import comb
from pathlib import Path

from .clues import card_as_clue, clue_is_true
from .config import config_from_dict
from .llm import ClaudeCLI, MockLLM, add_usage, zero_usage
from .log import utc_now, visible_to
from .prompts import player_system_prompt, turn_prompt
from .schemas import clean_reply, hard_cap, turn_schema
from .solver import from_log, player_worlds, posterior, table_posterior, table_worlds

KIND = "read_vote"
FORMULAS = ("simple", "jobw50", "jobw80", "public")
UNDECIDED = (0.2, 0.8)            # jobw50 range of an undecided rating (and of a candidate probe)
BOOT_N, BOOT_SEED = 2000, 20261110
HASHED_SOURCES = ("prompts.py", "schemas.py", "config.py", "probes.py")


# --------------------------------------------------------------------------- the state of a vote turn

def vote_cutoff(events: list[dict], rnd: int) -> int:
    """Votes are prepared together: the cutoff is the seq before the round's first vote turn."""
    return min(e["seq"] for e in events
               if e["type"] == "turn" and e.get("turn_phase") == "vote" and e["round"] == rnd) - 1


def rebuild_vote(events: list[dict], turn: dict) -> dict:
    """cutoff, ctx, caps, retries, system, prompt and schema of a logged vote turn, as `Game.ask`
    had them (ctx as `Game.base_ctx` plus `self`)."""
    start = next(e for e in events if e["type"] == "game_start")
    cfg = config_from_dict(start["config"])
    if cfg.game.vote_nobody:
        raise ValueError(f"{start['game_id']}: vote_nobody is on; read probes v1 do not support it")
    p, r = turn["player"], turn["round"]
    cutoff = vote_cutoff(events, r)
    upto = [e for e in events if e["seq"] <= cutoff]
    rs = next(e for e in upto if e["type"] == "round_start" and e["round"] == r)
    picks = [e for e in upto if e["type"] == "job_pick" and e["round"] == r]
    team = picks[-1]["team"] if picks else []
    role = {q["name"]: q["role"] for q in start["players"]}
    seats = [q["name"] for q in sorted(start["players"], key=lambda q: q["seat"])]
    alive = list(rs["alive"])
    moles_alive = [n for n in alive if role[n] == "mole"]
    ctx = {"others": [n for n in alive if n != p], "alive": alive, "role": role[p],
           "moles_remaining": len(moles_alive), "leader": rs["leader"], "whispers": cfg.game.whispers,
           "card_players": [n for n in seats if n != p], "on_team": p in team,
           "partners": [n for n in moles_alive if n != p] if role[p] == "mole" else [], "self": p}
    lim = cfg.limits
    caps = {"confessional": hard_cap(lim.confessional_words, lim.word_grace),
            "public": hard_cap(lim.public_words, lim.word_grace),
            "memory": hard_cap(lim.memory_words, lim.word_grace)}
    setup = [e for e in events if e["phase"] == "setup"]
    return {"cutoff": cutoff, "upto": upto, "ctx": ctx, "caps": caps, "retries": lim.retries,
            "system": player_system_prompt(setup, p, cfg), "prompt": turn_prompt(upto, p, cfg, "vote", ctx),
            "schema": turn_schema("vote", ctx), "start": start, "role": role}


# --------------------------------------------------------------------------- formulas

def job_likelihood(w: frozenset, jobs, q: float) -> float:
    """P(observed sabotage counts | moles = w) when each mole on a team sabotages with prob. q.
    (Copied from analysis/strategies.py.)"""
    lk = 1.0
    for team, sab in jobs:
        k = sum(1 for t in team if t in w)
        if sab > k:
            return 0.0
        lk *= comb(k, sab) * (q ** sab) * ((1 - q) ** (k - sab))
    return lk


def weighted_posterior(worlds, players, jobs, q: float, fallback=None) -> dict:
    """Like `solver.posterior`, but each consistent world weighted by the job likelihood.
    (Copied from analysis/strategies.py.)"""
    use = list(worlds) or list(fallback or [])
    ws = [job_likelihood(w, jobs, q) for w in use]
    tot = sum(ws)
    if tot <= 0:
        return posterior(use, players)
    return {n: sum(wt for w, wt in zip(use, ws) if n in w) / tot for n in players}


def formulas(events: list[dict], cutoff: int, player: str, rated: list[str]) -> dict:
    """simple / jobw50 / jobw80 from the player's viewpoint and public from the table's, for the
    rated players. Fallback worlds (no world fits every card) as `solver.table_posterior`."""
    inp = from_log(events, cutoff, player)
    args = (inp["players"], inp["num_moles"], inp["revealed"])
    worlds = player_worlds(*args, inp["cards"], inp["jobs"], player=player, own_clues=inp["own_clues"],
                           pair_cards=inp["pair_cards"])
    fb = [w for w in table_worlds(*args, [], inp["jobs"]) if player not in w]
    out = {"simple": posterior(worlds, inp["players"], fb),
           "jobw50": weighted_posterior(worlds, inp["players"], inp["jobs"], 0.5, fb),
           "jobw80": weighted_posterior(worlds, inp["players"], inp["jobs"], 0.8, fb),
           "public": table_posterior(from_log(events, cutoff, "table"))}
    return {k: {n: v.get(n, 0.0) for n in rated} for k, v in out.items()}


# --------------------------------------------------------------------------- one probe

def probe_id(system: str, prompt: str, schema: dict) -> str:
    sch = json.dumps(schema, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256("\x00".join((system, prompt, sch)).encode("utf-8")).hexdigest()[:16]


def stated(rated: list[str], suspicion: dict) -> dict:
    """The reading as the analysis takes it: 0-100 clamped, divided by 100."""
    return {n: min(100, max(0, suspicion[n])) / 100 for n in rated}


def brier(probs: dict, truth: dict) -> float:
    """Mean over the rated players of (p - truth)^2 (as analysis/common.brier)."""
    return sum((p - truth[n]) ** 2 for n, p in probs.items()) / len(probs)


def undecided(f50: dict) -> list[str]:
    return [n for n, v in f50.items() if UNDECIDED[0] <= v <= UNDECIDED[1]]


def false_card_visible(upto: list[dict], player: str, moles) -> bool:
    """Has a false clue card been shown where `player` can see it? Cards are shown in discuss and
    debate turns (public) and in whisper turns (speaker and partner); `visible_to` decides. A
    card's truth is the engine's `checks.clue_cards[i].true_in_world` verdict, computed from the
    real moles if a turn has no checks."""
    for e in upto:
        if e["type"] != "turn" or e.get("turn_phase") not in ("discuss", "debate", "whisper"):
            continue
        if not visible_to(e, player):
            continue
        checks = (e.get("checks") or {}).get("clue_cards") or []
        for i, card in enumerate((e.get("action") or {}).get("clue_cards") or []):
            ok = checks[i]["true_in_world"] if i < len(checks) else clue_is_true(card_as_clue(card), moles)
            if not ok:
                return True
    return False


def make_probe(events: list[dict], turn: dict, batch: str) -> dict:
    rb = rebuild_vote(events, turn)
    start, role, ctx, upto = rb["start"], rb["role"], rb["ctx"], rb["upto"]
    sus = turn["action"]["suspicion"]
    rated = [n for n in ctx["others"] if n in sus]         # the logged keys, in seat order
    if sorted(rated) != sorted(n for n in sus if n in role):
        raise ValueError(f"{start['game_id']} seq {turn['seq']}: rated {sorted(sus)} != others {ctx['others']}")
    truth = {n: int(role[n] == "mole") for n in rated}
    f = formulas(events, rb["cutoff"], turn["player"], rated)
    jr = [e for e in upto if e["type"] == "job_result"]
    g = start["config"]["game"]
    return {
        "probe_id": probe_id(rb["system"], rb["prompt"], rb["schema"]), "kind": KIND, "batch": batch,
        "game_id": start["game_id"], "seed": start.get("seed"), "round": turn["round"], "seq": turn["seq"],
        "cutoff_seq": rb["cutoff"], "player": turn["player"], "orig_model": turn.get("model"),
        "system": rb["system"], "prompt": rb["prompt"], "schema": rb["schema"], "ctx": ctx,
        "caps": rb["caps"], "retries": rb["retries"], "rated": rated, "truth": truth, "formula": f,
        "orig": {"suspicion": sus, "vote": turn["action"]["vote"], "brier": brier(stated(rated, sus), truth)},
        "strata": {"n_alive": len(ctx["alive"]), "moles_alive": ctx["moles_remaining"],
                   "blown_jobs": jr[-1]["blown_jobs"] if jr else 0, "clean_jobs": jr[-1]["clean_jobs"] if jr else 0,
                   "sabotage_target": g.get("sabotage_target"),
                   "false_card_visible": false_card_visible(upto, turn["player"], set(start["moles"])),
                   "n_undecided": len(undecided(f["jobw50"]))},
    }


# --------------------------------------------------------------------------- building the set

def candidates(games: list[tuple[str, list[dict]]]) -> list[dict]:
    """Probes for crew, non-fallback vote turns with at least one undecided rating (jobw50)."""
    out = []
    for batch, events in games:
        start = next(e for e in events if e["type"] == "game_start")
        role = {q["name"]: q["role"] for q in start["players"]}
        for t in events:
            if (t["type"] == "turn" and t.get("turn_phase") == "vote" and role.get(t["player"]) == "crew"
                    and not t.get("fallback")):
                p = make_probe(events, t, batch)
                if p["strata"]["n_undecided"]:
                    out.append(p)
    return out


def select(cands: list[dict], n: int, seed: int) -> tuple[list[dict], dict]:
    """Deterministic from `seed`. Cells are (game, round). Cells are ordered round-robin over the
    games (shuffled); each game in turn gives its cell whose round has been taken least so far
    (ties broken at random). The first `n` cells give one seat each (drawn at random within the
    cell); if `n` is larger than the number of cells, second seats follow in the same cell order."""
    rng = random.Random(seed)
    cells: dict = {}
    for p in sorted(cands, key=lambda p: (p["game_id"], p["seq"])):
        cells.setdefault((p["game_id"], p["round"]), []).append(p)
    for key in sorted(cells):
        rng.shuffle(cells[key])
    games = sorted({g for g, _ in cells})
    rng.shuffle(games)
    tie = {key: rng.random() for key in sorted(cells)}
    left = {g: sorted(r for gg, r in cells if gg == g) for g in games}
    used: dict = {}
    order = []
    while any(left.values()):
        for g in games:
            if left[g]:
                r = min(left[g], key=lambda r: (used.get(r, 0), tie[(g, r)]))
                left[g].remove(r)
                used[r] = used.get(r, 0) + 1
                order.append((g, r))
    first = [cells[k][0] for k in order[:n]]
    second = [cells[k][1] for k in order if len(cells[k]) > 1][:max(0, n - len(order))]
    return first + second, {"candidates": len(cands), "cells": len(order), "second_seats": len(second)}


def _sorted(obj):
    if isinstance(obj, dict):
        return {k: _sorted(obj[k]) for k in sorted(obj)}
    if isinstance(obj, list):
        return [_sorted(v) for v in obj]
    return obj


def probe_line(p: dict) -> str:
    return json.dumps({k: (p[k] if k == "schema" else _sorted(p[k])) for k in sorted(p)}, ensure_ascii=False)


def sha256_file(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def manifest_path(set_path) -> Path:
    set_path = Path(set_path)
    return set_path.with_name(set_path.stem + ".manifest.json")


def write_set(probes: list[dict], out, arguments: dict, sources: dict) -> dict:
    """Write the set and its manifest. Refuses to overwrite an existing set file."""
    out = Path(out)
    if out.exists():
        raise FileExistsError(f"{out} exists; a frozen set is never overwritten")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "x", encoding="utf-8", newline="\n") as f:
        for p in probes:
            f.write(probe_line(p) + "\n")
    here = Path(__file__).resolve().parent
    man = {"set": out.name, "sha256": sha256_file(out), "count": len(probes), "arguments": arguments,
           "sources": sources, "code_sha256": {n: sha256_file(here / n) for n in HASHED_SOURCES},
           "time": utc_now()}
    manifest_path(out).write_text(json.dumps(man, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return man


def load_set(path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def verify_set(path) -> list[str]:
    """Problems with a set file (empty list = fine): every probe_id recomputed, ids unique, file
    hash and count as in the manifest."""
    path = Path(path)
    if not path.exists():
        return [f"{path} not found"]
    mp = manifest_path(path)
    if not mp.exists():
        return [f"manifest {mp} not found"]
    man = json.loads(mp.read_text(encoding="utf-8"))
    bad = []
    probes = load_set(path)
    for i, p in enumerate(probes, 1):
        if probe_id(p["system"], p["prompt"], p["schema"]) != p["probe_id"]:
            bad.append(f"line {i}: probe_id {p['probe_id']} does not match its text")
    if len({p["probe_id"] for p in probes}) != len(probes):
        bad.append("probe ids are not unique")
    if sha256_file(path) != man.get("sha256"):
        bad.append(f"file sha256 differs from the manifest ({man.get('sha256')})")
    if len(probes) != man.get("count"):
        bad.append(f"{len(probes)} probes, manifest says {man.get('count')}")
    return bad


def build_summary(probes: list[dict], info: dict, n: int) -> str:
    lines = [f"candidates {info['candidates']} (crew, non-fallback vote turns with an undecided rating), "
             f"cells (game, round) {info['cells']}, probes {len(probes)} of {n} asked"
             + (f", {info['second_seats']} of them a second seat in a cell" if info["second_seats"] else "")]
    by = {}
    for p in probes:
        by.setdefault(p["batch"], {}).setdefault(p["round"], 0)
        by[p["batch"]][p["round"]] += 1
    for b in sorted(by):
        lines.append(f"  {b}: {sum(by[b].values())} probes; by round "
                     + ", ".join(f"R{r} {k}" for r, k in sorted(by[b].items())))
    fc = sum(1 for p in probes if p["strata"]["false_card_visible"])
    lines.append(f"  false card visible to the seat: {fc} of {len(probes)}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- running

async def ask_probe(llm, probe: dict, model: str) -> dict:
    """One probe, with the same validate / retry / blocked loop as `Game.ask`, and no fallback."""
    system, prompt, schema = probe["system"], probe["prompt"], probe["schema"]
    usage, latency, served = zero_usage(), 0.0, None
    rejections, kinds, raws = [], [], []
    attempt_prompt = prompt
    attempts = blocked = fails = 0
    while True:
        attempts += 1
        reply = await llm.call(model=model, system=system, prompt=attempt_prompt, schema=schema,
                               phase="vote", player=probe["player"])
        usage = add_usage(usage, reply.usage)
        latency += reply.latency_s or 0.0
        served = reply.served_model or served
        raws.append(reply.raw_text)
        if reply.error:
            reason, kind = reply.error, reply.error_kind or "cli"
        else:
            cleaned, reason, _ = clean_reply("vote", reply.data, schema, probe["ctx"], probe["caps"])
            if cleaned is not None:
                act = cleaned["action"]
                return _record(probe, True, None, attempts, rejections, act["suspicion"], act["vote"], cleaned,
                               raws, usage, latency, served)
            kind = "invalid"
        rejections.append(reason)
        kinds.append(kind)
        if kind == "blocked":
            blocked += 1
            if blocked >= 2:
                break
            continue                                   # identical prompt, no rejection line
        fails += 1
        if fails > probe["retries"]:
            break
        attempt_prompt = (prompt + f"\n\nYour previous reply was rejected: {reason}. "
                          "Reply again with valid JSON.")
    return _record(probe, False, kinds[-1], attempts, rejections, None, None, None, raws, usage, latency, served)


def _record(probe, ok, kind, attempts, rejections, sus, vote, data, raws, usage, latency, served) -> dict:
    return {"probe_id": probe["probe_id"], "served_model": served, "ok": ok, "error_kind": kind,
            "attempts": attempts, "rejections": rejections, "suspicion": sus, "vote": vote, "data": data,
            "raw": raws, "usage": usage, "latency_s": round(latency, 3)}


def run_path(runs_dir, set_path, model: str, effort: str, cap: int) -> Path:
    return Path(runs_dir) / Path(set_path).stem / f"{model}__{effort or 'none'}__t{cap}.jsonl"


def read_run(path) -> dict:
    """probe_id -> its record: the ok one if any, else the last."""
    recs: dict = {}
    if Path(path).exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    if not (recs.get(r["probe_id"]) or {}).get("ok"):
                        recs[r["probe_id"]] = r
    return recs


async def run_set(probes: list[dict], llm, *, model: str, effort: str, cap: int, out: Path,
                  parallel: int = 2, limit: int | None = None, stats: dict | None = None) -> dict:
    """Run the first `limit` probes (all if None) that have no ok record in `out`; append each
    record as it finishes. `stats` is updated in place (so an interrupted run can still report)."""
    stats = stats if stats is not None else {}
    stats.update(probes=0, calls=0, failed=0, skipped=0, usage=zero_usage())
    done = {i for i, r in read_run(out).items() if r.get("ok")}
    todo = [p for p in probes[:limit] if p["probe_id"] not in done]
    stats["skipped"] = len(probes[:limit]) - len(todo)
    out.parent.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(max(1, parallel))
    with open(out, "a", encoding="utf-8", newline="\n") as fh:
        async def one(p):
            async with sem:
                rec = await ask_probe(llm, p, model)
            rec.update(model=model, effort=effort, max_thinking_tokens=cap, ts=utc_now())
            fh.write(json.dumps(rec, sort_keys=True, ensure_ascii=False) + "\n")
            fh.flush()
            stats["probes"] += 1
            stats["calls"] += rec["attempts"]
            stats["failed"] += not rec["ok"]
            stats["usage"] = add_usage(stats["usage"], rec["usage"])
        await asyncio.gather(*[one(p) for p in todo])
    return stats


def run_summary(stats: dict, wall: float) -> str:
    u = stats["usage"]
    return (f"{stats['probes']} probes run ({stats['skipped']} already done), {stats['calls']} calls, "
            f"{stats['failed']} failed; tokens: input {u['input']}, output {u['output']}, thinking {u['thinking']}, "
            f"cache {u['cache_read'] + u['cache_creation']} (read {u['cache_read']}, creation "
            f"{u['cache_creation']}); wall {wall:.1f}s")


# --------------------------------------------------------------------------- scoring

_T975 = {1: 12.7062, 2: 4.3027, 3: 3.1824, 4: 2.7764, 5: 2.5706, 6: 2.4469, 7: 2.3646, 8: 2.3060,
         9: 2.2622, 10: 2.2281, 11: 2.2010, 12: 2.1788, 13: 2.1604, 14: 2.1448, 15: 2.1314, 16: 2.1199,
         17: 2.1098, 18: 2.1009, 19: 2.0930, 20: 2.0860, 21: 2.0796, 22: 2.0739, 23: 2.0687, 24: 2.0639,
         25: 2.0595, 26: 2.0555, 27: 2.0518, 28: 2.0484, 29: 2.0452, 30: 2.0423, 40: 2.0211, 60: 2.0003,
         120: 1.9799, math.inf: 1.9600}


def t975(df: int) -> float:
    """97.5% quantile of Student's t; table values, linear in 1/df between them."""
    if df in _T975:
        return _T975[df]
    keys = sorted(_T975)
    hi = next(k for k in keys if k > df)
    lo = keys[keys.index(hi) - 1]
    x, xl, xh = 1 / df, 1 / lo, (0.0 if hi == math.inf else 1 / hi)
    return _T975[hi] + (_T975[lo] - _T975[hi]) * (x - xh) / (xl - xh)


def _pct(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolation percentile (numpy's default)."""
    pos = (len(sorted_vals) - 1) * q
    lo = math.floor(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def bootstrap(rows: list[tuple], stat, n: int = BOOT_N, seed: int = BOOT_SEED):
    """95% percentile interval of `stat(items)` over `n` resamples of whole games, or None with
    fewer than two games. `rows` = [(game_id, item)]. Same seed and games -> same resamples."""
    by_game: dict = {}
    for g, x in rows:
        by_game.setdefault(g, []).append(x)
    games = sorted(by_game)
    if len(games) < 2:
        return None
    rng = random.Random(seed)
    vals = []
    for _ in range(n):
        items = []
        for _g in games:
            items += by_game[games[rng.randrange(len(games))]]
        v = stat(items)
        if v is not None:
            vals.append(v)
    vals.sort()
    return (_pct(vals, 0.025), _pct(vals, 0.975)) if vals else None


def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


def _slope(pairs):
    den = sum(b for _, b in pairs)
    return sum(a for a, _ in pairs) / den if den > 0 else None


def paired(rows: list[tuple]) -> dict:
    """rows = [(game_id, difference)]: pooled mean, bootstrap interval over games, and the paired
    t interval over per-game means (centre = mean of the game means)."""
    out = {"n": len(rows), "games": len({g for g, _ in rows}), "mean": _mean(d for _, d in rows),
           "boot": bootstrap(rows, _mean), "t": None}
    gm: dict = {}
    for g, d in rows:
        gm.setdefault(g, []).append(d)
    means = [sum(v) / len(v) for v in gm.values()]
    if len(means) >= 2:
        c = sum(means) / len(means)
        half = t975(len(means) - 1) * statistics.stdev(means) / math.sqrt(len(means))
        out["t"] = (c, c - half, c + half)
    return out


def slope_stat(rows: list[tuple]) -> dict:
    """rows = [(game_id, (s - f) * (t - f), (s - f) ** 2)] over undecided ratings."""
    pairs = [(g, (a, b)) for g, a, b in rows]
    return {"n": len(rows), "slope": _slope([x for _, x in pairs]), "boot": bootstrap(pairs, _slope)}


def top_share(f: dict, truth: dict, tol: float = 1e-9) -> float:
    """Mole share of the formula's top suspects (ties split evenly)."""
    top = max(f.values())
    tied = [n for n, v in f.items() if v >= top - tol]
    return sum(truth[n] for n in tied) / len(tied)


def probe_rows(probe: dict, sus: dict, vote: str) -> dict:
    """Everything the scores need from one answered probe."""
    t, f50 = probe["truth"], probe["formula"]["jobw50"]
    s = stated(probe["rated"], sus)
    und = undecided({n: f50[n] for n in probe["rated"]})
    row = {"g": probe["game_id"], "model": brier(s, t), "orig": probe["orig"]["brier"],
           "vote": t.get(vote, 0), "vote_orig": t.get(probe["orig"]["vote"], 0), "vote_top": top_share(f50, t),
           "und": [(s[n] - t[n]) ** 2 - (f50[n] - t[n]) ** 2 for n in und],
           "slope": [((s[n] - f50[n]) * (t[n] - f50[n]), (s[n] - f50[n]) ** 2) for n in und]}
    row.update({k: brier(probe["formula"][k], t) for k in FORMULAS})
    return row


def score_run(probes: list[dict], recs: dict) -> dict:
    """Scores for one run (records by probe_id) on its valid probes, in set order."""
    rows = [probe_rows(p, recs[p["probe_id"]]["suspicion"], recs[p["probe_id"]]["vote"])
            for p in probes if (recs.get(p["probe_id"]) or {}).get("ok")]
    done = [recs[p["probe_id"]] for p in probes if p["probe_id"] in recs]
    failed: dict = {}
    for r in done:
        if not r["ok"]:
            failed[r["error_kind"]] = failed.get(r["error_kind"], 0) + 1
    out = {"valid": len(rows), "failed": failed, "games": len({r["g"] for r in rows})}
    for k in ("model", "orig", *FORMULAS, "vote", "vote_orig", "vote_top"):
        out[k] = _mean(r[k] for r in rows)
    out["diff"] = paired([(r["g"], r["model"] - r["jobw50"]) for r in rows])
    out["diff_und"] = paired([(r["g"], sum(r["und"]) / len(r["und"])) for r in rows if r["und"]])
    out["slope"] = slope_stat([(r["g"], a, b) for r in rows for a, b in r["slope"]])
    for k in ("input", "output", "thinking"):
        out[f"tok_{k}"] = _mean(r["usage"].get(k, 0) for r in done)
    out["latency"] = _mean(r["latency_s"] for r in done)
    out["served_other"] = sorted(r["probe_id"] for r in done if r.get("served_model")
                                 and r["served_model"] != r.get("model"))
    return out


def score_pair(probes: list[dict], a: dict, b: dict) -> dict:
    """Run A against run B on the probes both answered."""
    both = [p for p in probes if (a.get(p["probe_id"]) or {}).get("ok") and (b.get(p["probe_id"]) or {}).get("ok")]
    ra = [probe_rows(p, a[p["probe_id"]]["suspicion"], a[p["probe_id"]]["vote"]) for p in both]
    rb = [probe_rows(p, b[p["probe_id"]]["suspicion"], b[p["probe_id"]]["vote"]) for p in both]
    out = {"n": len(both), "games": len({p["game_id"] for p in both})}
    for tag, rows in (("a", ra), ("b", rb)):
        out[f"brier_{tag}"] = _mean(r["model"] for r in rows)
        out[f"vote_{tag}"] = _mean(r["vote"] for r in rows)
        out[f"slope_{tag}"] = slope_stat([(r["g"], x, y) for r in rows for x, y in r["slope"]])
    out["diff"] = paired([(x["g"], x["model"] - y["model"]) for x, y in zip(ra, rb)])
    out["diff_und"] = paired([(x["g"], (sum(x["und"]) - sum(y["und"])) / len(x["und"]))
                              for x, y in zip(ra, rb) if x["und"]])
    return out


def _f(x) -> str:
    return "-" if x is None else f"{x:.3f}"


def _ci(s: dict) -> tuple[str, str, str]:
    boot = f"[{_f(s['boot'][0])}, {_f(s['boot'][1])}]" if s["boot"] else "-"
    t = f"{_f(s['t'][0])} [{_f(s['t'][1])}, {_f(s['t'][2])}]" if s["t"] else "-"
    return _f(s["mean"]), boot, t


def _table(head: list[str], body: list[list]) -> list[str]:
    return ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + \
           ["| " + " | ".join(str(c) for c in row) + " |" for row in body] + [""]


def run_key(path: Path) -> tuple[str, str, str]:
    model, effort, cap = path.stem.split("__")
    return model, effort, cap


def score_report(set_path, runs_dir) -> str:
    set_path = Path(set_path)
    probes = load_set(set_path)
    files = sorted((Path(runs_dir) / set_path.stem).glob("*.jsonl"))
    runs = {run_key(f): read_run(f) for f in files}
    scores = {k: score_run(probes, r) for k, r in runs.items()}
    name = lambda k: f"{k[0]} / {k[1]} / {k[2]}"   # noqa: E731
    L = [f"Set `{set_path.name}` sha256 `{sha256_file(set_path)}`, {len(probes)} probes; "
         f"{len(runs)} run(s) in `{Path(runs_dir) / set_path.stem}`.", ""]
    if not runs:
        return "\n".join(L + ["No runs yet.", ""])
    L += ["## Runs", ""] + _table(
        ["run (model / effort / cap)", "valid", "games", "failed", "mean input", "mean output", "mean thinking",
         "mean latency s", "served by another model"],
        [[name(k), s["valid"], s["games"], ", ".join(f"{e} {c}" for e, c in sorted(s["failed"].items())) or "0",
          _f(s["tok_input"]), _f(s["tok_output"]), _f(s["tok_thinking"]), _f(s["latency"]),
          ", ".join(s["served_other"]) or "none"] for k, s in scores.items()])
    L += ["## Brier of the reading (valid probes; lower is better)", ""] + _table(
        ["run", "model", "original player", *FORMULAS],
        [[name(k), _f(s["model"]), _f(s["orig"]), *[_f(s[f]) for f in FORMULAS]] for k, s in scores.items()])
    L += ["## Model minus jobw50 (paired per probe; bootstrap over games, 2,000 resamples; t over game means)", ""]
    body = []
    for k, s in scores.items():
        sl = s["slope"]
        body.append([name(k), s["diff"]["n"], *_ci(s["diff"]), s["diff_und"]["n"], *_ci(s["diff_und"]),
                     sl["n"], _f(sl["slope"]), f"[{_f(sl['boot'][0])}, {_f(sl['boot'][1])}]" if sl["boot"] else "-"])
    L += _table(["run", "probes", "mean", "boot 95%", "t: game mean [95%]", "probes (undecided)", "mean undecided",
                 "boot 95%", "t: game mean [95%]", "undecided ratings", "slope", "slope boot 95%"], body)
    L += ["Undecided: ratings with jobw50 in [0.2, 0.8]; per probe the mean over its undecided ratings of "
          "(s - t)^2 - (f - t)^2. Slope = sum((s-f)(t-f)) / sum((s-f)^2) over those ratings; above 0 means "
          "the model's departures from the formula point at the truth.", ""]
    L += ["## Votes on a mole (share of valid probes)", ""] + _table(
        ["run", "model", "original player", "jobw50 top suspect (ties split)"],
        [[name(k), _f(s["vote"]), _f(s["vote_orig"]), _f(s["vote_top"])] for k, s in scores.items()])
    keys = list(runs)
    pairs = [(a, b) for i, a in enumerate(keys) for b in keys[i + 1:]
             if a[0] == b[0] or (a[1], a[2]) == (b[1], b[2])]
    if pairs:
        body = []
        for a, b in pairs:
            s = score_pair(probes, runs[a], runs[b])
            body.append([name(a), name(b), s["n"], _f(s["brier_a"]), _f(s["brier_b"]), *_ci(s["diff"]),
                         *_ci(s["diff_und"]), _f(s["slope_a"]["slope"]), _f(s["slope_b"]["slope"]),
                         _f(s["vote_a"]), _f(s["vote_b"])])
        L += ["## Between runs (A minus B, on the probes both answered)", ""] + _table(
            ["A", "B", "probes", "Brier A", "Brier B", "mean A-B", "boot 95%", "t: game mean [95%]",
             "undecided A-B", "boot 95%", "t: game mean [95%]", "slope A", "slope B", "votes on mole A",
             "votes on mole B"], body)
    return "\n".join(L)


# --------------------------------------------------------------------------- commands

def _refuse(set_path) -> int:
    bad = verify_set(set_path)
    for b in bad:
        print(f"verify: {b}", file=sys.stderr)
    return 1 if bad else 0


def cmd_build(args) -> int:
    from .report import load_batch
    out = Path(args.out)
    if out.exists():
        print(f"build: {out} exists; a frozen set is never overwritten", file=sys.stderr)
        return 2
    games, sources = [], {}
    for b in args.batch:
        logs = load_batch(args.games, b)
        if not logs.known:
            print(f"build: no batch named {b!r} in {Path(args.games) / 'index.jsonl'}", file=sys.stderr)
            return 2
        games += [(b, ev) for ev in logs.games]
        sources[b] = [next(e for e in ev if e["type"] == "game_start")["game_id"] for ev in logs.games]
    try:
        cands = candidates(games)
    except ValueError as e:
        print(f"build: {e}", file=sys.stderr)
        return 2
    chosen, info = select(cands, args.n, args.seed)
    man = write_set(chosen, out, {"batch": list(args.batch), "n": args.n, "seed": args.seed,
                                  "games": str(args.games), "out": str(out)}, sources)
    print(build_summary(chosen, info, args.n))
    print(f"wrote {out} ({man['count']} probes, sha256 {man['sha256']}) and {manifest_path(out)}")
    return 0


def cmd_verify(args) -> int:
    code = _refuse(args.set)
    if not code:
        print(f"verify: {args.set} ok ({len(load_set(args.set))} probes)")
    return code


def cmd_run(args) -> int:
    if _refuse(args.set):
        print("run: refusing a set that fails verify", file=sys.stderr)
        return 1
    probes = load_set(args.set)
    if args.mock:
        llm = MockLLM(0)
    else:
        llm = ClaudeCLI(max_parallel_calls=args.parallel, timeout_s=args.timeout,
                        max_thinking_tokens=args.max_thinking_tokens, effort=args.effort)
    out = run_path(args.runs, args.set, args.model, args.effort, args.max_thinking_tokens)
    print(f"run: {args.model}, effort {args.effort or 'none'}, thinking cap {args.max_thinking_tokens}"
          f"{', mock model' if args.mock else ''}; writing {out}", file=sys.stderr, flush=True)
    stats: dict = {}
    t0 = time.monotonic()
    try:
        asyncio.run(run_set(probes, llm, model=args.model, effort=args.effort, cap=args.max_thinking_tokens,
                            out=out, parallel=args.parallel, limit=args.limit, stats=stats))
    except KeyboardInterrupt:
        print(f"\ninterrupted. {run_summary(stats, time.monotonic() - t0)}")
        return 130
    print(run_summary(stats, time.monotonic() - t0))
    return 0


def cmd_score(args) -> int:
    if _refuse(args.set):
        print("score: refusing a set that fails verify", file=sys.stderr)
        return 1
    text = score_report(args.set, args.runs)
    sys.stdout.write(text + "\n")
    if args.write:
        Path(args.write).parent.mkdir(parents=True, exist_ok=True)
        Path(args.write).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.write}", file=sys.stderr)
    return 0


COMMANDS = {"build": cmd_build, "verify": cmd_verify, "run": cmd_run, "score": cmd_score}
