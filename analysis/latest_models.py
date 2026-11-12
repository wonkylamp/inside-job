"""Bluff, latest models: the crew suspicion gap for every mole model played against the fixed crew.

Reads games/index.jsonl and the game logs (read-only; no model calls, no network) and prints, per
mole model: games, seeds, mole wins, mean gap with a bootstrap 95% interval, crew votes on a mole,
vote-outs that hit a mole, self-tagged lies, calls, billed dollars, code stamps, and the share of the
mole seats' turns that got no answer. Then paired-by-seed comparisons between every two models with
a Holm correction, and a per-game table for the batches analysis/bluff_score.py does not print.

Run from anywhere:
    python3.11 analysis/latest_models.py [--index FILE] [--root DIR] [--json FILE]
                                         [--chart [OUT_DIR]] [--force]

--chart writes latest_models.svg and latest_models.html (default directory docs/charts/latest). It
refuses to replace either file unless --force is given. It never writes bluff_gap.*.

Rules, as implemented:
- Games: bluff_score.group_games, so every game in the index for the group's batches that is not
  spoiled (a row is appended only when a game finishes). Groups with no such games are left out of
  every output. Gaps, wins and tallies come from bluff_score.game and bluff_score.summarise.
- No answer: a turn event (type "turn", written by inside_job/engine.py Game.write_turn) by a mole
  seat with "fallback": true. That is a turn where every attempt failed and the engine played the
  phase's default move; "fallback_reason" says why (blocked | invalid | timeout | cli, where cli
  covers an empty reply). A model whose mole seats fell back on more than 5% of their turns is
  flagged "left off the chart": it is printed with the flag, not drawn, and not compared. Failed
  attempts ("error_kinds", one per failed attempt, retried or not) are printed beside it.
- Pairs: every two models not left off, on the seeds both played: mean of the per-seed differences
  (first minus second, in group order), seeds below zero, and a two-sided sign-flip permutation p
  (bluff_mechanism.signflip_p, exact over all sign patterns up to 16 seeds). Holm correction over
  every pair printed. bluff_score.perm is not used here: it is an unpaired two-sample test.

Random draws: one fresh bluff_score.new_rng(), used only for the bootstrap (bluff_score.boot,
10,000 resamples) of each group with games, in DRAW_ORDER: first the groups of bluff_score.GROUPS
in that file's order (so their intervals equal what bluff_score.py prints), then the other groups in
LATEST_GROUPS order. Exact sign-flip p needs no draws; past 16 seeds it would draw from the same rng
after the bootstraps, in pair order. A rerun on the same index prints the same numbers.

Standard library only; hand-written SVG in the visual language of analysis/bluff_chart.py.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import re
import statistics
import sys
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import bluff_score  # noqa: E402
from bluff_chart import (  # noqa: E402
    AXIS, BAND, DOT, DOT_R, FONT, GRID, INK, INK_2, MEAN, SURFACE,
    _crew_of, _lanes, _seed_text, _text, display_name, fmt, fmt_tick,
)
from bluff_mechanism import signflip_p  # noqa: E402
from inside_job.config import is_openrouter_model  # noqa: E402
from inside_job.openrouter import reasoning_param  # noqa: E402

# The latest mole models, in report order. Haiku 4.5 is the reference row (an older model).
LATEST_GROUPS = [
    ("Fable 5.2 moles", ["headroom1", "bluff_fable52"]),
    ("Opus 5.5 moles", ["bluff_opus55"]),
    ("Sonnet 5.5 moles", ["bluff_sonnet55"]),
    ("Haiku 5.5 moles", ["bluff_haiku55"]),
    ("Grok 4.7 moles", ["bluff_grok47"]),
    ("Kimi K3.1 Pro moles", ["bluff_kimi"]),
    ("Gemini 4 Carbon moles", ["bluff_gemini"]),
    ("GPT-6.1 Sol moles", ["bluff_sol"]),
    ("Haiku 4.5 moles", ["bluff_haiku45"]),
]
REFERENCE = ("Haiku 4.5 moles",)
NULL_PAIR = ("Haiku 5.5", "bluff_haiku55", "bluff_haiku55_run2")   # one model, two runs, same seeds (N1)
NULL_T = 2.26              # docs/ANALYSIS.md N1: smallest difference n seeds could show = 2.26 x SD / sqrt(n)
FULL_GAMES = 10            # fewer games than this: hollow dots on the chart
NO_ANSWER_MAX = 0.05       # mole-seat fallback share above this: left off the chart
CHART_FILES = ("latest_models.svg", "latest_models.html")
DEFAULT_CHART_DIR = ROOT / "docs" / "charts" / "latest"
# The 30-game verdict (docs/ROAD_TO_10.md section 1) travels with the chart whenever its row is drawn.
VERDICT_GROUP = "Fable 5.2 moles"
VERDICT_NOTE = ("Whole-game averages. Fable 5.2's lower gap is not established at the first vote, "
                "so why it is lower is not shown.")


def draw_order(groups=LATEST_GROUPS):
    """bluff_score.GROUPS first (its order), then the rest of `groups` in their order."""
    by_name = dict(groups)
    first = []
    for name, batches in bluff_score.GROUPS:
        if name in by_name:
            if list(by_name[name]) != list(batches):
                raise ValueError(f"{name}: batches {by_name[name]} differ from bluff_score.GROUPS {batches}")
            first.append((name, by_name[name]))
    names = {n for n, _ in first}
    return first + [(n, b) for n, b in groups if n not in names]


DRAW_ORDER = draw_order()

WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine"}


def word(n: int) -> str:
    return WORDS.get(n, str(n))


def short_hash(h) -> str:
    return str(h)[:8] if h else "unstamped"


def nan_none(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else x


def plural(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def join_and(xs) -> str:
    xs = list(xs)
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def holm(ps):
    """Holm step-down adjusted p-values, in the input order. None stays None and is not counted."""
    idx = sorted((i for i, p in enumerate(ps) if p is not None), key=lambda i: ps[i])
    m = len(idx)
    out = [None] * len(ps)
    run = 0.0
    for k, i in enumerate(idx):
        run = max(run, min(1.0, (m - k) * ps[i]))
        out[i] = run
    return out


# --------------------------------------------------------------------------- reading the logs

def _strip_letter(model_name: str) -> str:
    return re.sub(r" [A-Z]$", "", model_name)


def seat_stats(x: dict, root: str) -> dict:
    """Mole-seat turn counts and the seating of one scored game (x from bluff_score.game)."""
    row = x["row"]
    with open(os.path.join(root, row["log"])) as f:
        ev = [json.loads(l) for l in f if l.strip()]
    start = next((e for e in ev if e["type"] == "game_start"), {})
    players = start.get("players") or row.get("players") or []
    moles = set(x["moles"])
    mole_models = sorted({p["model"] for p in players if p["name"] in moles})
    turns = [e for e in ev if e["type"] == "turn" and e.get("player") in moles]
    fb = [e for e in turns if e.get("fallback")]
    log_crew = tuple(sorted(_strip_letter(p["model_name"]) for p in players if p.get("role") == "crew")) or None
    return {
        "mole_models": mole_models,
        "turns": len(turns),
        "fallback_turns": len(fb),
        "fallback_reasons": dict(collections.Counter(e.get("fallback_reason") or "unrecorded" for e in fb)),
        "attempts": sum(e.get("attempts", 1) for e in turns),
        "failed_attempts": sum(len(e.get("error_kinds") or []) for e in turns),
        "failed_kinds": dict(collections.Counter(k for e in turns for k in e.get("error_kinds") or [])),
        "seats": len(players),
        "mole_seats": len(moles),
        "seats_of_mole_model": sum(p["model"] in mole_models for p in players),
        "crew_from_log": log_crew,
        "crew_from_index": _crew_of(row),
    }


def game_record(x: dict, st: dict) -> dict:
    r, t = x["row"], x["row"].get("tokens") or {}
    return {
        "batch": r.get("batch"), "seed": r["seed"], "game_id": r.get("game_id"), "winner": r["winner"],
        "reason": r.get("reason"), "rounds": r.get("rounds"), "gap": x["gap"],
        "crew_on_mole": x["g"]["crew_on_mole"], "crew_votes": x["g"]["crew_votes"],
        "calls": r.get("calls"), "mole_calls": st["attempts"],
        "tokens_in": t.get("input", 0) + t.get("cache_read", 0) + t.get("cache_creation", 0),
        "tokens_out": t.get("output", 0), "thinking": t.get("thinking", 0),
        "list_usd": t.get("cost_usd", 0.0), "billed_usd": r.get("billed_usd"),
        "wall_min": (r["wall_s"] / 60) if r.get("wall_s") is not None else None,
        "served_other": x["mis"], "mole_turns": st["turns"], "mole_fallbacks": st["fallback_turns"],
        "code_hash": r.get("code_hash"),
    }


def analyse(index_path=None, root=None, groups=LATEST_GROUPS, reference=REFERENCE) -> dict:
    """Every number the report, the JSON and the chart show."""
    root = str(ROOT if root is None else root)
    index_path = os.path.join(root, "games", "index.jsonl") if index_path is None else str(index_path)
    idx = bluff_score.load_index(index_path)
    res = bluff_score.group_games(idx, groups, root)
    order = draw_order(groups)
    rng = bluff_score.new_rng()
    summ = bluff_score.summaries(res, rng, order)          # the only draws before the pairs

    models = []
    for name, batches in groups:
        gs = res.get(name)
        if not gs:
            continue
        s = summ[name]
        tot = s["tot"]
        sts = [seat_stats(x, root) for x in gs]
        rows = [x["row"] for x in gs]
        billed = [r["billed_usd"] for r in rows if r.get("billed_usd") is not None]
        turns = sum(st["turns"] for st in sts)
        fbt = sum(st["fallback_turns"] for st in sts)
        att = sum(st["attempts"] for st in sts)
        fat = sum(st["failed_attempts"] for st in sts)
        share = fbt / turns if turns else 0.0
        mole_models = sorted({m for st in sts for m in st["mole_models"]})
        conds = [r.get("conditions") or {} for r in rows]
        models.append({
            "group": name, "name": display_name(name), "batches": list(batches),
            "reference": name in reference,
            "n": s["n"], "seeds": [r["seed"] for r in rows], "wins": s["wins"],
            "gaps": s["gaps"], "mean": s["mean"], "lo": s["lo"], "hi": s["hi"], "sd": s["sd"],
            "crew_on_mole": tot["crew_on_mole"], "crew_votes": tot["crew_votes"],
            "chance_pct": tot["exp_x1000"] / 10 / max(1, tot["crew_votes"]),
            "elims_mole": tot["elims_mole"], "elims": tot["elims"],
            "lies": tot["mole_stmts_lie"], "stmts": tot["mole_stmts"],
            "calls": sum(r.get("calls") or 0 for r in rows), "mole_calls": att,
            "billed_usd": round(sum(billed), 6) if billed else None, "billed_games": len(billed),
            "list_usd": round(sum((r.get("tokens") or {}).get("cost_usd", 0.0) for r in rows), 6),
            "code_hashes": sorted({r.get("code_hash") or "" for r in rows}),
            "mole_models": mole_models,
            "outside_lab": any(is_openrouter_model(m) for m in mole_models),
            "efforts": sorted({c.get("effort") or "" for c in conds}),
            "reasoning_sent": sorted({json.dumps(reasoning_param(c.get("max_thinking_tokens", -1), c.get("effort", "")),
                                                 sort_keys=True) for c in conds}),
            "mole_turns": turns, "fallback_turns": fbt, "fallback_share": share,
            "fallback_reasons": dict(sum((collections.Counter(st["fallback_reasons"]) for st in sts),
                                         collections.Counter())),
            "failed_attempts": fat, "failed_share": fat / att if att else 0.0,
            "failed_kinds": dict(sum((collections.Counter(st["failed_kinds"]) for st in sts), collections.Counter())),
            "left_off": share > NO_ANSWER_MAX,
            "seats_of_mole_model": sorted({st["seats_of_mole_model"] for st in sts}),
            "seats": sorted({st["seats"] for st in sts}),
            "mole_seats": sorted({st["mole_seats"] for st in sts}),
            "crews": sorted({c for st in sts for c in (st["crew_from_log"], st["crew_from_index"])},
                            key=lambda c: (c is None, c or ())),
            "games": [game_record(x, st) for x, st in zip(gs, sts)],
        })

    # Paired by seed, every two models not left off, in group order.
    compared = [m for m in models if not m["left_off"]]
    pairs = []
    for i in range(len(compared)):
        for j in range(i + 1, len(compared)):
            a, b = compared[i], compared[j]
            ga = {g["seed"]: g["gap"] for g in a["games"]}
            gb = {g["seed"]: g["gap"] for g in b["games"]}
            seeds = [s for s in sorted(set(ga) & set(gb)) if ga[s] is not None and gb[s] is not None]
            d = [ga[s] - gb[s] for s in seeds]
            pairs.append({"a": a["name"], "b": b["name"], "seeds": seeds, "n": len(d), "diffs": d,
                          "mean": statistics.fmean(d) if d else None, "below": sum(v < 0 for v in d),
                          "p": signflip_p(d, rng) if d else None})
    for p, h in zip(pairs, holm([p["p"] for p in pairs])):
        p["p_holm"] = h

    out = {"index": index_path, "rng_seed": bluff_score.RNG_SEED,
           "draw_order": [n for n, _ in order if res.get(n)],
           "rules": {"included": "in the index for the group's batches and not spoiled",
                     "no_answer": "mole-seat turn events with fallback true, over all mole-seat turns",
                     "no_answer_max": NO_ANSWER_MAX, "full_games": FULL_GAMES,
                     "pair_test": "two-sided sign-flip permutation on per-seed differences, Holm over the pairs"},
           "models": models, "pairs": pairs,
           "new_batches": [m["group"] for m in models if m["group"] not in dict(bluff_score.GROUPS)]}
    out["null"] = null_check(idx, root)
    out["chart"] = chart_data(out)
    return out


def null_check(idx, root, pair=NULL_PAIR):
    """One model played twice on the same seeds (docs/ANALYSIS.md N1). None until both batches have games.

    Uses no random draws, so it cannot move any other number. The full test is analysis/null_test.py."""
    res = bluff_score.group_games(idx, [("run 1", [pair[1]]), ("run 2", [pair[2]])], root)
    ga = {x["row"]["seed"]: x["gap"] for x in res.get("run 1") or [] if x["gap"] is not None}
    gb = {x["row"]["seed"]: x["gap"] for x in res.get("run 2") or [] if x["gap"] is not None}
    seeds = sorted(set(ga) & set(gb))
    if len(seeds) < 2:
        return None
    d = [ga[s] - gb[s] for s in seeds]
    sd = statistics.stdev(d)
    return {"model": pair[0], "batches": list(pair[1:]), "n": len(d), "mean": statistics.fmean(d), "sd": sd,
            "smallest": NULL_T * sd / math.sqrt(len(d))}


# --------------------------------------------------------------------------- chart

def _seat_note(m: dict, crew_size: int | None) -> str | None:
    """'Haiku 5.5 is also one of the five crew models, so three of seven seats are ...' (from data)."""
    seats_m, seats, moles = m["seats_of_mole_model"], m["seats"], m["mole_seats"]
    if len(seats_m) != 1 or len(seats) != 1 or len(moles) != 1 or seats_m[0] <= moles[0]:
        return None
    crew = f"one of the {word(crew_size)} crew models" if crew_size else "also seated as crew"
    return (f"{m['name']} is also {crew}, so {word(seats_m[0])} of {word(seats[0])} seats "
            f"are {m['name']} in its own games.")


def chart_data(out: dict) -> dict:
    """Rows drawn (left-off models out, lowest mean first), legend entries and footnotes."""
    drawn = [m for m in out["models"] if not m["left_off"]]
    drawn.sort(key=lambda m: (math.isnan(m["mean"]), m["mean"] if not math.isnan(m["mean"]) else 0.0))
    games = [g for m in drawn for g in m["games"]]
    crews = {c for m in drawn for c in m["crews"]}
    crew = list(next(iter(crews))) if len(crews) == 1 and None not in crews else None
    efforts = {e for m in drawn for e in m["efforts"]}

    lines = ["Each dot is one game. Dark tick: mean of the games. Bar: bootstrap 95% interval over games."]
    effort = (f" Effort {next(iter(efforts))} in every game." if len(efforts) == 1 and "" not in efforts
              else " Effort not the same in every game.")
    if crew:
        lines.append(f"Same {word(len(crew))}-model crew in every game: {', '.join(crew)}.{effort}")
    else:
        lines.append(f"Crew not the same in every game.{effort}")
    by_games = collections.OrderedDict()
    for m in drawn:
        by_games.setdefault((m["n"], tuple(m["seeds"])), []).append(m["name"])
    for (n, seeds), names in sorted(by_games.items(), key=lambda kv: (-kv[0][0], kv[0][1])):
        each = " each" if len(names) > 1 else ""
        lines.append(f"{join_and(names)}: {plural(n, 'game')}{each}, "
                     f"{'seeds' if len(seeds) > 1 else 'seed'} {_seed_text(list(seeds))}.")
    for m in drawn:
        note = _seat_note(m, len(crew) if crew else None)
        if note:
            lines.append(note)
    outside = [m for m in drawn if m["outside_lab"]]
    inside = [m for m in drawn if not m["outside_lab"]]
    if outside:
        sent = {json.dumps(json.loads(r), sort_keys=True) for m in outside for r in m["reasoning_sent"]}
        efforts_sent = {(json.loads(r) or {}).get("effort") for r in sent}
        sent_txt = (f"sent reasoning effort \"{next(iter(efforts_sent))}\""
                    if len(efforts_sent) == 1 and None not in efforts_sent else "not all sent the same reasoning setting")
        o_st = sorted({short_hash(h) for m in outside for h in m["code_hashes"]})
        i_st = sorted({short_hash(h) for m in inside for h in m["code_hashes"]})
        they = "It" if len(outside) == 1 else "They"
        stamp = f"{they} ran from code stamp{'' if len(o_st) == 1 else 's'} {join_and(o_st)}"
        if i_st and set(o_st) != set(i_st):
            stamp += f"; the Claude rows ran from {join_and(i_st)}."
        elif i_st:
            stamp += ", the same as the Claude rows."
        else:
            stamp += "."
        lines.append(f"{join_and([m['name'] for m in outside])} {'was' if len(outside) == 1 else 'were'} called "
                     f"through OpenRouter and {sent_txt}. {stamp}")
    left = [m for m in out["models"] if m["left_off"]]
    for m in left:
        lines.append(f"Left off the chart: {m['name']}. Its moles gave no answer on "
                     f"{m['fallback_turns']} of {m['mole_turns']} turns ({100 * m['fallback_share']:.1f}%), "
                     f"above the 5% pass mark.")
    if any(m["group"] == VERDICT_GROUP for m in drawn):
        lines.append(VERDICT_NOTE)
    nt = out.get("null")
    if nt:
        lines.append(f"{nt['model']} played twice on the same {nt['n']} seeds: the runs' mean gaps differ by "
                     f"{abs(nt['mean']):.1f} points, and single seeds by much more (SD {nt['sd']:.1f}). At that noise "
                     f"{nt['n']} seeds can show a difference of about {nt['smallest']:.0f} points or more. Not a ranking.")
    else:
        lines.append("No model has been played twice yet, so the size of a difference that means nothing "
                     "is not measured. Not a ranking.")

    short = [m for m in drawn if m["n"] < FULL_GAMES]
    legend = [("dot", f"One game ({FULL_GAMES} games per model)" if short else "One game")]
    if short:
        ns = sorted({m["n"] for m in short})
        legend.append(("hollow", f"One game of a model with only {join_and([str(n) for n in ns])} "
                                 f"{'game' if ns == [1] else 'games'}: "
                                 f"fewer games, so its mean is less sure"))
    if any(m["reference"] for m in drawn):
        refs = [m["name"] for m in drawn if m["reference"]]
        legend.append(("ref", f"{join_and(refs)}: an older model, kept for reference"))
    return {"rows": [m["group"] for m in drawn], "crew": crew, "footnotes": lines, "legend": legend,
            "left_off": [m["group"] for m in left]}


# Layout (px). Height grows with the number of rows and footnote lines; never less than 900.
W = 1600
LEFT, RIGHT = 80, 1520
PLOT_X0, PLOT_X1 = 500, 1250
ROW_Y0, ROW_PITCH = 320, 140   # 140: a dot in the fourth lane stays clear of the next row's mean label
NOTE_SIZE, NOTE_PITCH = 23, 34
REF_DOT, REF_BAND, REF_MEAN = "#9a988f", "#dcdbd4", "#6b6a64"


def text_width(s: str, size: float, weight: int = 400) -> float:
    """Estimated rendered width for the chart's sans-serif font. Calibrated on rsvg-convert's
    rendering (about 0.42 em a character for prose) with a margin for wider fonts such as Arial."""
    wide = sum(c.isupper() or c.isdigit() or c in "mwMW%" for c in s)
    return size * ((0.5 if weight < 600 else 0.54) * len(s) + 0.06 * wide)


def wrap(s: str, size: float, max_w: float) -> list[str]:
    out, cur = [], ""
    for w_ in s.split():
        t = f"{cur} {w_}".strip()
        if cur and text_width(t, size) > max_w:
            out.append(cur)
            cur = w_
        else:
            cur = t
    return out + ([cur] if cur else [])


def _domain(models) -> tuple[int, int]:
    vals = [0.0]
    for m in models:
        vals += [g["gap"] for g in m["games"] if g["gap"] is not None]
        vals += [v for v in (m["lo"], m["hi"]) if not math.isnan(v)]
    lo, hi = math.floor(min(vals) / 10) * 10, math.ceil(max(vals) / 10) * 10
    return lo, (hi if hi > lo else lo + 10)


def render_svg(out: dict) -> str:
    by = {m["group"]: m for m in out["models"]}
    rows = [by[g] for g in out["chart"]["rows"]]
    if not rows:
        raise ValueError("no model to draw")
    d0, d1 = _domain(rows)

    def X(v: float) -> float:
        return PLOT_X0 + (v - d0) / (d1 - d0) * (PLOT_X1 - PLOT_X0)

    plot_top = ROW_Y0 - 62
    axis_y = ROW_Y0 + ROW_PITCH * (len(rows) - 1) + 70
    legend_y = axis_y + 140
    notes = [l for line in out["chart"]["footnotes"] for l in wrap(line, NOTE_SIZE, RIGHT - LEFT)]
    legend = out["chart"]["legend"]
    # Legend items flow left to right and wrap.
    leg, x, y = [], LEFT, legend_y
    for kind, label in legend:
        w_ = 34 + text_width(label, 23)
        if x > LEFT and x + w_ > RIGHT:
            x, y = LEFT, y + 40
        leg.append((kind, label, x, y))
        x += w_ + 44
    notes_y = y + 56
    H = max(900, int(notes_y + NOTE_PITCH * (len(notes) - 1) + 40))

    title = "How suspicious did each model's moles look?"
    subtitle = "Points more suspicion the crew put on the moles than on each other (0–100 scale)"
    def ci_text(m):
        if math.isnan(m["lo"]) or math.isnan(m["hi"]):
            return "no interval (fewer than two games)"
        return f"95% interval {fmt(m['lo'])} to {fmt(m['hi'])}"

    desc = " ".join(f"{m['name']}{' (reference)' if m['reference'] else ''}: mean {fmt(m['mean'])}, "
                    f"{ci_text(m)}, moles won {m['wins']} of {m['n']}." for m in rows)
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
         f'role="img" aria-labelledby="chart-title chart-desc" font-family=\'{FONT}\'>',
         f'<title id="chart-title">{escape(title)}</title>',
         f'<desc id="chart-desc">{escape(subtitle + ". Lower: the crew suspected the moles less. " + desc)}</desc>',
         f'<rect x="0" y="0" width="{W}" height="{H}" fill="{SURFACE}"/>',
         _text(LEFT, 98, title, 64, weight=700),
         _text(LEFT, 150, subtitle, 30, fill=INK_2)]

    o.append('<g class="grid">')
    for v in range(d0, d1 + 1, 10):
        if v != 0:
            o.append(f'<line x1="{X(v):.1f}" y1="{plot_top}" x2="{X(v):.1f}" y2="{axis_y}" stroke="{GRID}" stroke-width="1"/>')
    o.append(f'<line x1="{PLOT_X0}" y1="{axis_y}" x2="{PLOT_X1}" y2="{axis_y}" stroke="{AXIS}" stroke-width="1"/>')
    for v in range(d0, d1 + 1, 10):
        o.append(_text(X(v), axis_y + 38, fmt_tick(v), 26, fill=INK_2, anchor="middle",
                       extra=' font-variant-numeric="tabular-nums"'))
    o.append(_text(PLOT_X0, axis_y + 80, "← less suspected", 26, weight=600))
    o.append(_text(PLOT_X1, axis_y + 80, "more suspected →", 26, weight=600, anchor="end"))
    o.append('</g>')

    o.append(f'<line class="zero" x1="{X(0):.1f}" y1="{plot_top - 18}" x2="{X(0):.1f}" y2="{axis_y}" '
             f'stroke="{INK_2}" stroke-width="2"/>')
    zl = "0 = crew suspected the moles no more than each other"
    zw = text_width(zl, 26) / 2
    o.append(_text(min(max(X(0), PLOT_X0 + zw - 80), PLOT_X1 - zw + 80), plot_top - 30, zl, 26,
                   fill=INK_2, anchor="middle", halo=True))

    for i, m in enumerate(rows):
        y = ROW_Y0 + i * ROW_PITCH
        ref, hollow = m["reference"], m["n"] < FULL_GAMES
        dot, band, mean = (REF_DOT, REF_BAND, REF_MEAN) if ref else (DOT, BAND, MEAN)
        cls = "row" + (" reference" if ref else "") + (" short" if hollow else "")
        o.append(f'<g class="{cls}" data-model="{escape(m["name"])}">')
        o.append(_text(LEFT, y + 6, m["name"], 40, weight=700, fill=INK_2 if ref else INK, extra=' class="name"'))
        sub = [t for t in ("reference" if ref else "", plural(m["n"], "game") if hollow else "") if t]
        if sub:
            o.append(_text(LEFT, y + 40, ", ".join(sub), 24, fill=INK_2, extra=' class="sub"'))
        o.append(_text(RIGHT, y + 9, f"moles won {m['wins']} of {m['n']}", 26, fill=INK_2, anchor="end",
                       extra=' class="wins"'))
        if not (math.isnan(m["lo"]) or math.isnan(m["hi"])):
            x0, x1 = X(m["lo"]), X(m["hi"])
            o.append(f'<rect class="interval" x="{x0:.1f}" y="{y - 6}" width="{max(x1 - x0, 0):.1f}" height="12" '
                     f'rx="6" fill="{band}"><title>{escape(m["name"])}: bootstrap 95% interval '
                     f'{escape(fmt(m["lo"]))} to {escape(fmt(m["hi"]))}</title></rect>')
        gs = [g for g in m["games"] if g["gap"] is not None]
        xs = [X(g["gap"]) for g in gs]
        for g, x, lane in zip(gs, xs, _lanes(xs)):
            won = "moles won" if g["winner"] == "moles" else "crew won"
            paint = (f'fill="{SURFACE}" stroke="{dot}" stroke-width="3.5"' if hollow
                     else f'fill="{dot}" stroke="{SURFACE}" stroke-width="2.5"')
            o.append(f'<circle class="game" cx="{x:.1f}" cy="{y + lane}" r="{DOT_R}" {paint}>'
                     f'<title>{escape(m["name"])}, seed {g["seed"]}: gap {escape(fmt(g["gap"]))}, {won}</title></circle>')
        if not math.isnan(m["mean"]):
            xm = X(m["mean"])
            o.append(f'<rect class="mean" x="{xm - 4:.1f}" y="{y - 30}" width="8" height="60" rx="3" fill="{mean}" '
                     f'stroke="{SURFACE}" stroke-width="2"><title>{escape(m["name"])}: mean '
                     f'{escape(fmt(m["mean"]))}</title></rect>')
            label = f"mean {fmt(m['mean'])}"
            half = text_width(label, 30, 700) / 2
            o.append(_text(min(max(xm, PLOT_X0 + half), PLOT_X1 - half), y - 50, label, 30, weight=700,
                           fill=INK_2 if ref else INK, anchor="middle", halo=True))
        o.append('</g>')

    o.append('<g class="legend">')
    for kind, label, x, y in leg:
        cx, cy = x + DOT_R + 2, y - 8
        if kind == "dot":
            o.append(f'<circle cx="{cx}" cy="{cy}" r="{DOT_R}" fill="{DOT}" stroke="{SURFACE}" stroke-width="2.5"/>')
        elif kind == "hollow":
            o.append(f'<circle cx="{cx}" cy="{cy}" r="{DOT_R}" fill="{SURFACE}" stroke="{DOT}" stroke-width="3.5"/>')
        else:
            o.append(f'<circle cx="{cx}" cy="{cy}" r="{DOT_R}" fill="{REF_DOT}" stroke="{SURFACE}" stroke-width="2.5"/>')
        o.append(_text(x + 34, y, label, 23, fill=INK))
    o.append('</g>')
    for j, line in enumerate(notes):
        o.append(_text(LEFT, notes_y + j * NOTE_PITCH, line, NOTE_SIZE, fill=INK_2, extra=' class="note"'))
    o.append('</svg>')
    return "\n".join(o) + "\n"


def layout_problems(svg: str) -> list[str]:
    """Estimated text boxes that overlap each other or leave the canvas (an estimate, not a renderer).
    Text with a halo may sit over marks; text may not sit over other text."""
    import xml.etree.ElementTree as ET
    ns = "{http://www.w3.org/2000/svg}"
    root = ET.fromstring(svg)
    W_, H_ = (float(v) for v in root.get("viewBox").split()[2:])
    boxes, probs = [], []
    for t in root.iter(f"{ns}text"):
        s, size = t.text or "", float(t.get("font-size"))
        w_ = text_width(s, size, int(t.get("font-weight", 400)))
        x, y = float(t.get("x")), float(t.get("y"))
        x0 = {"start": x, "middle": x - w_ / 2, "end": x - w_}[t.get("text-anchor", "start")]
        b = (x0, y - 0.78 * size, x0 + w_, y + 0.24 * size, s)
        if b[0] < 0 or b[2] > W_ or b[1] < 0 or b[3] > H_:
            probs.append(f"off canvas: {s!r} {tuple(round(v) for v in b[:4])}")
        boxes.append(b)
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                probs.append(f"overlap: {a[4]!r} and {b[4]!r}")
    plain = [b for b, t in zip(boxes, root.iter(f"{ns}text")) if t.get("stroke") is None]
    for c in root.iter(f"{ns}circle"):
        cx, cy, r = float(c.get("cx")), float(c.get("cy")), float(c.get("r"))
        if cx - r < 0 or cx + r > W_ or cy - r < 0 or cy + r > H_:
            probs.append(f"dot off canvas at {cx:.0f},{cy:.0f}")
        for b in plain:
            if b[0] < cx + r and cx - r < b[2] and b[1] < cy + r and cy - r < b[3]:
                probs.append(f"dot at {cx:.0f},{cy:.0f} under text {b[4]!r}")
    return probs


def render_html(svg: str, out: dict) -> str:
    def cell(x):
        return escape(fmt(x)) if x is not None and not math.isnan(x) else "n/a"

    order = out["chart"]["rows"] + [m["group"] for m in out["models"] if m["group"] not in out["chart"]["rows"]]
    by = {m["group"]: m for m in out["models"]}
    trs = []
    for g in order:
        m = by[g]
        status = ("left off the chart" if m["left_off"] else "reference" if m["reference"] else "")
        trs.append(
            f"<tr><th scope=\"row\">{escape(m['name'])}</th><td>{m['n']}</td><td>{escape(_seed_text(m['seeds']))}</td>"
            f"<td>{cell(m['mean'])}</td><td>{cell(m['lo'])} to {cell(m['hi'])}</td>"
            f"<td>{escape(', '.join(str(x['seed']) + ': ' + (fmt(x['gap']) if x['gap'] is not None else 'n/a') for x in m['games']))}</td>"
            f"<td>{m['wins']} of {m['n']}</td><td>{m['fallback_turns']} of {m['mole_turns']}</td>"
            f"<td>{escape(status)}</td></tr>")
    notes = "\n".join(f"<li>{escape(l)}</li>" for l in out["chart"]["footnotes"])
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>How suspicious did each model's moles look?</title>
<style>
  html, body {{ margin: 0; background: {SURFACE}; color: {INK}; color-scheme: light; }}
  body {{ font-family: {FONT}; padding: 16px; }}
  main {{ max-width: {W}px; margin: 0 auto; }}
  svg {{ display: block; width: 100%; height: auto; }}
  table {{ border-collapse: collapse; margin-top: 24px; font-size: 15px; font-variant-numeric: tabular-nums; }}
  th, td {{ text-align: left; padding: 6px 14px 6px 0; border-bottom: 1px solid {GRID}; vertical-align: top; }}
  thead th {{ color: {INK_2}; font-weight: 600; }}
  .wrap {{ overflow-x: auto; }}
  ul {{ color: {INK_2}; font-size: 15px; padding-left: 20px; }}
</style>
</head>
<body>
<main>
{svg}<div class="wrap">
<table>
<caption style="text-align:left;font-weight:600;padding-bottom:8px">Crew suspicion gap, points (lower = less suspected)</caption>
<thead><tr><th scope="col">Mole model</th><th scope="col">Games</th><th scope="col">Seeds</th><th scope="col">Mean</th><th scope="col">Bootstrap 95%</th><th scope="col">Per game (seed: gap)</th><th scope="col">Moles won</th><th scope="col">Mole turns with no answer</th><th scope="col">Note</th></tr></thead>
<tbody>
{chr(10).join(trs)}
</tbody>
</table>
</div>
<ul>
{notes}
</ul>
</main>
</body>
</html>
"""


def write_chart(out: dict, out_dir, force: bool = False) -> tuple[Path, Path]:
    d = Path(out_dir)
    paths = [d / n for n in CHART_FILES]
    taken = [str(p) for p in paths if p.exists()]
    if taken and not force:
        raise FileExistsError(f"refusing to replace {', '.join(taken)} (pass --force to replace)")
    svg = render_svg(out)
    d.mkdir(parents=True, exist_ok=True)
    paths[0].write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + svg, encoding="utf-8")
    paths[1].write_text(render_html(svg, out), encoding="utf-8")
    return paths[0], paths[1]


# --------------------------------------------------------------------------- text and JSON

def pct(a, b) -> str:
    return bluff_score.pct(a, b)


def _f(x, spec="+.1f") -> str:
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else format(x, spec)


def report(out: dict) -> str:
    L = []
    models = out["models"]
    L.append("Bluff, latest models. Crew suspicion gap per game: the crew's mean 0-100 rating of the moles "
             "minus their mean rating of other crew, at vote turns. Lower = moles less suspected.")
    L.append(f"Index {out['index']}. Games: in the index, not spoiled (bluff_score.group_games). "
             f"Groups with no such games are left out.")
    if not models:
        L.append("No model has games yet.")
        return "\n".join(L) + "\n"
    namew = max(len(m["name"]) for m in models) + 2

    L.append("\n== Per mole model (interval: bootstrap 95% over games)")
    L.append(f"  {'model':{namew}}{'games':>5}  {'seeds':<9} {'moles won':<10} {'mean gap':>8}  {'95% interval':<16}  note")
    for m in models:
        notes = []
        if m["reference"]:
            notes.append("reference row")
        if m["n"] < FULL_GAMES:
            notes.append(f"fewer than {FULL_GAMES} games")
        if m["left_off"]:
            notes.append("LEFT OFF THE CHART (no answer above 5%)")
        won = f"{m['wins']} of {m['n']}"
        ci = f"[{_f(m['lo'])}, {_f(m['hi'])}]"
        L.append(f"  {m['name']:{namew}}{m['n']:>5}  {_seed_text(m['seeds']):<9} {won:<10} {_f(m['mean']):>8}  "
                 f"{ci:<16}  {'; '.join(notes)}".rstrip())

    L.append("\n== How the games went")
    L.append(f"  {'model':{namew}}{'crew votes on a mole':<26}{'vote-outs hit a mole':<22}{'self-tagged lies':<20}"
             f"{'calls':>6} {'mole':>6}  {'billed':<8} code stamp")
    for m in models:
        billed = (f"${m['billed_usd']:.2f}" + ("" if m["billed_games"] == m["n"] else f" ({m['billed_games']} games)")
                  if m["billed_usd"] is not None else "n/a")
        cv = f"{pct(m['crew_on_mole'], m['crew_votes'])} ch {m['chance_pct']:.0f}%"
        L.append(f"  {m['name']:{namew}}{cv:<26}{pct(m['elims_mole'], m['elims']):<22}{pct(m['lies'], m['stmts']):<20}"
                 f"{m['calls']:>6} {m['mole_calls']:>6}  {billed:<8} {', '.join(short_hash(h) for h in m['code_hashes'])}")
    L.append("  ch = chance rate for a random vote. calls = every call in the games; mole = attempts by the two mole "
             "seats. billed = OpenRouter money from the index's billed_usd (n/a: field not in these rows).")
    for m in models:
        L.append(f"  {m['name']}: mole model {', '.join(m['mole_models'])}; effort {', '.join(e or 'not passed' for e in m['efforts'])}"
                 + ("; OpenRouter reasoning sent " + ", ".join(m["reasoning_sent"]) if m["outside_lab"] else ""))

    L.append(f"\n== Mole-seat turns with no answer (turn events with fallback true). Pass mark: at most "
             f"{100 * NO_ANSWER_MAX:.0f}% of turns")
    L.append(f"  {'model':{namew}}{'turns':>6} {'no answer':>10} {'share':>7}  {'why':<22} {'failed attempts':>16}  status")
    for m in models:
        why = ", ".join(f"{k} {v}" for k, v in sorted(m["fallback_reasons"].items())) or "-"
        fa = f"{m['failed_attempts']}/{m['mole_calls']} ({100 * m['failed_share']:.1f}%)"
        status = "left off the chart" if m["left_off"] else "drawn"
        L.append(f"  {m['name']:{namew}}{m['mole_turns']:>6} {m['fallback_turns']:>10} {100 * m['fallback_share']:>6.1f}%  "
                 f"{why:<22} {fa:>16}  {status}")
        if not m["left_off"] and m["failed_share"] > NO_ANSWER_MAX:
            L.append(f"  note: {m['name']} failed on more than 5% of its attempts but fewer than 5% of its turns "
                     f"fell back (failed attempts by kind: {m['failed_kinds']}).")
    L.append("  Failed attempts are retried; a turn has no answer only when every attempt failed.")

    pairs = out["pairs"]
    L.append("\n== Paired by seed: first minus second on the per-game gap, seeds both played")
    left = [m["name"] for m in models if m["left_off"]]
    if left:
        L.append(f"  Not compared (left off the chart): {', '.join(left)}.")
    if not pairs:
        L.append("  No pairs.")
    else:
        pw = max(len(f"{p['a']} minus {p['b']}") for p in pairs) + 2
        L.append(f"  {'pair':{pw}}{'seeds':>5} {'mean diff':>10} {'below zero':>11} {'sign-flip p':>12} {'Holm p':>8}")
        for p in pairs:
            L.append(f"  {p['a'] + ' minus ' + p['b']:{pw}}{p['n']:>5} {_f(p['mean']):>10} "
                     f"{(str(p['below']) + ' of ' + str(p['n'])):>11} {_f(p['p'], '.4f'):>12} {_f(p['p_holm'], '.4f'):>8}")
        L.append(f"  Holm correction over the {sum(p['p'] is not None for p in pairs)} pairs above. "
                 "Sign-flip p is exact over every sign pattern (two-sided).")
        for m in models:
            if m["n"] < FULL_GAMES and not m["left_off"]:
                L.append(f"  Pairs with {m['name']} ({m['n']}-game model) have {m['n']} seed{'s' if m['n'] != 1 else ''} "
                         f"at most; with n seeds the smallest possible p is 2/2^n ({min(1.0, 2 / 2 ** m['n']):.4f} "
                         f"for {m['n']}).")

    new = [m for m in models if m["group"] in out["new_batches"]]
    L.append("\n== Per game, new batches (the others are printed by analysis/bluff_score.py)")
    if not new:
        L.append("  None yet.")
    for m in new:
        L.append(f"  {m['name']}:")
        for g in m["games"]:
            gap = _f(g["gap"])
            billed = f" billed ${g['billed_usd']:.2f}" if g["billed_usd"] is not None else ""
            wall = f"{g['wall_min']:.0f} min" if g["wall_min"] is not None else "n/a"
            L.append(f"   {g['batch']:14} seed {g['seed']}: {g['winner']:5} {g['reason'] or '':10} rounds {g['rounds']} "
                     f"gap {gap:>6} crew-on-mole {g['crew_on_mole']}/{g['crew_votes']} calls {g['calls']} "
                     f"(mole {g['mole_calls']}) in {g['tokens_in']:,} out {g['tokens_out']:,} (thinking {g['thinking']:,}) "
                     f"list ${g['list_usd']:.2f}{billed} {wall} served-other {g['served_other']} "
                     f"mole no-answer {g['mole_fallbacks']}/{g['mole_turns']}")

    L.append(f"\nRandom draws: bluff_score.new_rng() (seed {out['rng_seed']}), bootstrap per group in this order: "
             f"{', '.join(display_name(n) for n in out['draw_order'])}. The bluff_score.GROUPS groups come first, "
             "so their intervals equal bluff_score.py's. Exact sign-flip p uses no draws.")
    L.append("Chart rows: " + (", ".join(display_name(g) for g in out["chart"]["rows"]) or "none") + ".")
    return "\n".join(L) + "\n"


def to_json(out: dict) -> str:
    def clean(x):
        if isinstance(x, float):
            return nan_none(x)
        if isinstance(x, dict):
            return {str(k): clean(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [clean(v) for v in x]
        return x
    return json.dumps(clean(out), indent=1, ensure_ascii=False) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--index", default=None, help="index file (default: <root>/games/index.jsonl)")
    ap.add_argument("--root", default=None, help="directory the logs' paths are relative to (default: project root)")
    ap.add_argument("--json", metavar="FILE", default=None, help="also write every number as JSON")
    ap.add_argument("--chart", metavar="OUT_DIR", nargs="?", const=str(DEFAULT_CHART_DIR), default=None,
                    help=f"write {' and '.join(CHART_FILES)} (default directory {DEFAULT_CHART_DIR})")
    ap.add_argument("--force", action="store_true", help="let --chart replace existing chart files")
    a = ap.parse_args(argv)
    out = analyse(a.index, a.root)
    sys.stdout.write(report(out))
    if a.json:
        Path(a.json).write_text(to_json(out), encoding="utf-8")
        print(f"wrote {a.json}")
    if a.chart:
        try:
            paths = write_chart(out, a.chart, a.force)
        except FileExistsError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        for p in paths:
            print(f"wrote {p}")
        for prob in layout_problems(render_svg(out)):
            print(f"layout warning: {prob}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
