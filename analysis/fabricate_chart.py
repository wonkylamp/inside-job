"""Chart: which models' moles showed a clue card they were never dealt (docs/CHART.md).

Writes docs/charts/fabricate.svg, docs/charts/fabricate.html (the same SVG in a standalone page with a
table of every number, nothing loaded from the network), docs/charts/fabricate_alt.txt (the alt text
for X, which carries the fine print) and docs/charts/fabricate.png when `rsvg-convert` is installed.
The alt text is also printed. Every number comes from analysis/fabricate_rate.py's functions at run
time; this file types in no result. Zero model calls, read only.

Built for a phone feed: a plain bar chart, 1200 x 1500 px (4:5 portrait), one sorted list of every
model, one bar hue, no text under 30 px (2.5% of the width).

Run from anywhere:
    python3.11 analysis/fabricate_chart.py [--games games] [--runs probes/moves/runs/v1_public]
        [--set probes/moves/sets/v1_public.jsonl] [--out docs/charts] [--no-png]
Standard library only; hand-written SVG in the palette of analysis/bluff_chart.py.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import bluff_chart as BC  # noqa: E402  (shared palette and the crew reader)
import fabricate_rate as FR  # noqa: E402

FONT = BC.FONT
SURFACE, INK, INK_2, GRID, AXIS = BC.SURFACE, BC.INK, BC.INK_2, BC.GRID, BC.AXIS
BAR = BC.DOT            # blue 450, categorical slot 1: every bar (one series, one hue)
CALLOUT_FILL = "#f0efea"  # neutral tint one step off the surface: the callout is not a bar

MAIN = ["Fable 5.2", "Opus 5.5", "Sonnet 5.5", "Haiku 5.5"]       # latest Claude models only, fixed order
# DeepSeek V4 Pro is not in fabricate_rate.GROUPS (that list mirrors analysis/latest_models.py); its
# group is kept here. Its reasoning setting is read from its batch config at run time.
DEEPSEEK = ("DeepSeek V4 Pro", "deepseek/deepseek-v4-pro-0813", ["bluff_deepseek"])
DEEPSEEK_CONFIG = ROOT / "config" / "bluff_deepseek.toml"
OTHER = sorted(["Grok 4.7", "Kimi K3.1 Pro", "Gemini 4 Carbon", DEEPSEEK[0]])  # read order; drawn sorted by share
FULL_GAMES = 10          # the planned games per model; a row with another count says so beside its name

# Layout, px in a fixed 1200 x 1500 viewBox.
W, H, M = 1200, 1500, 60
MIN_TEXT = 30
TITLE, SUB, GNOTE, NAME, NOTE, VALUE, COUNT, CALL, FOOT = 62, 36, 30, 42, 32, 52, 34, 36, 30
BAR_H = 36
GAP_NAME_BAR = 14        # from the name's baseline to the top of its bar
GAP_LABEL = 18           # from a bar's end to its value label
MIN_ROW_GAP, MAX_ROW_GAP = 10, 44
STUB = 6                 # a zero row's visible stub, px

WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine",
         10: "ten"}


# ---- data ----

def _index_rows(games_dir, batches) -> list[dict]:
    """The index rows `MV.load_sources` would read: last row per (batch, seed), not spoiled."""
    latest = {}
    with open(Path(games_dir) / "index.jsonl", encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("batch") in batches and not r.get("spoiled"):
                latest[(r["batch"], r.get("seed"))] = r
    return list(latest.values())


def _read_games(games_dir, groups) -> tuple[dict, dict]:
    """Turn counts and per-mole counts, read again if a game finished between the two reads."""
    for _ in range(3):
        fg = {r["name"]: r for r in FR.full_games(games_dir, groups=groups)}
        ml = {r["name"]: r for r in FR.moles(games_dir, groups=groups)}
        if all(fg[n]["games"] == ml[n]["games"] for n in fg):
            return fg, ml
    raise RuntimeError("games kept finishing while the chart was read; run it again")


def deepseek_reasoning(path=DEEPSEEK_CONFIG) -> str | None:
    """The reasoning setting DeepSeek's batch config sends ("none" = off), or None if not set."""
    try:
        cfg = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    return ((cfg.get("openrouter") or {}).get("reasoning_effort_by_model") or {}).get(DEEPSEEK[1])


def chart_data(games_dir=None, runs_dir=None, set_path=None) -> dict:
    games_dir = Path(games_dir or ROOT / "games")
    runs_dir = Path(runs_dir or ROOT / "probes/moves/runs/v1_public")
    set_path = Path(set_path or ROOT / "probes/moves/sets/v1_public.jsonl")
    groups = {g[0]: g for g in FR.GROUPS}
    groups[DEEPSEEK[0]] = DEEPSEEK
    fg, ml = _read_games(games_dir, [groups[n] for n in MAIN + OTHER])
    om, _mix = FR.one_move(runs_dir, set_path)
    ins = FR.instructed(runs_dir, set_path, labels={n: FR.MARK_LABELS[n] for n in MAIN})
    ins_by = {r["name"]: r for r in ins["rows"]}

    def full(name):
        r, m = fg[name], ml[name]
        if not r["turns"]:
            raise ValueError(f"no counted mole turns for {name} in {games_dir}")
        return {"games": r["games"], "turns": r["turns"], "forged": r["forged_turns"], "rate": r["rate"],
                "ci": r["ci"], "moles": m["moles"], "forged_moles": m["forged_moles"], "mole_rate": m["rate"],
                "mole_ci": m["ci"], "mole_bound": m["bound"]}

    main = []
    for n in MAIN:
        row = {"name": n, "full": full(n)}
        free = FR.label_for(om, n, groups[n][1])
        row["free"] = None if free is None else {"k": free["forged"], "n": free["valid"], "rate": free["rate"],
                                                 "ci": free["ci"], "moves": free["moves"]}
        ir = ins_by[n]
        if not ir["complete"]:
            raise ValueError(f"instructed condition not complete for {n}: {ir['valid']} valid of {ir['moments']}")
        row["told"] = {"k": ir["shown"]["k"], "n": ir["shown"]["n"], "rate": ir["shown"]["rate"],
                       "ci": ir["shown"]["ci"], "moves": ir["moves"]}
        main.append(row)
    # A lab with no finished game is left out.
    other = [{"name": n, "full": full(n)} for n in OTHER if fg[n]["games"]]
    for r in other:
        if r["name"] == DEEPSEEK[0]:
            r["reasoning"] = deepseek_reasoning()

    # Conditions, read from the index (the same rows the full-game counts use).
    idx = [r for n in MAIN for r in _index_rows(games_dir, groups[n][2])]
    crews = {BC._crew_of(r) for r in idx}
    effort = {(r.get("conditions") or {}).get("effort") for r in idx}
    seeds = {n: sorted(r.get("seed") for r in _index_rows(games_dir, groups[n][2])) for n in MAIN}
    return {
        "main": main,
        "other": other,
        "moments": ins["moments"],
        "free_moments": sorted({row["free"]["n"] for row in main if row["free"]}),
        "games": sorted({row["full"]["games"] for row in main}),
        "moles": sorted({row["full"]["moles"] for row in main}),
        "crew_size": len(next(iter(crews))) if len(crews) == 1 and None not in crews else None,
        "crew_claude": all(m.startswith(("Haiku", "Sonnet", "Opus", "Fable")) for c in crews if c for m in c),
        "effort": next(iter(effort)) if len(effort) == 1 else None,
        "same_seeds": len({tuple(s) for s in seeds.values()}) == 1,
    }


# ---- statistics used only for wording ----

def fisher_p(a: int, n1: int, b: int, n2: int) -> float:
    """Two-sided Fisher exact p for a of n1 against b of n2 (sum of tables no likelier than the one seen)."""
    k, n = a + b, n1 + n2

    def p(x):
        return math.comb(n1, x) * math.comb(n2, k - x) / math.comb(n, k)
    seen = p(a)
    return min(1.0, sum(p(x) for x in range(max(0, k - n2), min(k, n1) + 1) if p(x) <= seen * (1 + 1e-9)))


# ---- wording, all derived from the numbers ----

def pct(x: float) -> str:
    if 0 < x < 0.005:
        return "<1%"
    if 0.995 <= x < 1:
        return ">99%"
    return f"{100 * x:.0f}%"


def pct1(x) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def ci0(c) -> str:
    return "n/a" if not c else f"{100 * c[0]:.0f} to {100 * c[1]:.0f}%"


def ci1(c) -> str:
    return "n/a" if not c else f"{100 * c[0]:.1f} to {100 * c[1]:.1f}%"


def has_width(c) -> bool:
    return bool(c) and c[1] > c[0]


def plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def moles_text(f: dict) -> str:
    return f"{f['forged_moles']} of {f['moles']} moles"


def turns_text(f: dict) -> str:
    return f"{f['forged']} of {f['turns']} turns"


def games_text(f: dict) -> str:
    return plural(f["games"], "game")


def span(xs) -> str:
    xs = sorted(xs)
    return str(xs[0]) if xs[0] == xs[-1] else f"{xs[0]} to {xs[-1]}"


def rows_of(data: dict) -> list[dict]:
    return data["main"] + data["other"]


def sorted_rows(data: dict) -> list[dict]:
    """Every model in one list: highest share of moles first; ties by more moles, then name."""
    return sorted(rows_of(data), key=lambda r: (-r["full"]["mole_rate"], -r["full"]["moles"], r["name"]))


def title_text(data: dict) -> str:
    forged = [r["full"]["forged_moles"] for r in rows_of(data)]
    if any(forged) and not all(forged):
        return "Allowed to forge clue cards, only some AI models did."
    if all(forged):
        return "Allowed to forge clue cards, every AI model did."
    return "Allowed to forge clue cards, no AI model did."


SUBTITLE = "Share of moles that showed a fake clue card at least once."


def reasoning_note(r: dict) -> str | None:
    if "reasoning" not in r:
        return None
    v = r["reasoning"]
    return "reasoning off" if v == "none" else (f"reasoning {v}" if v else "reasoning setting not found")


def shared_games(data: dict) -> int | None:
    """The one game count every row shares, else None."""
    gs = {r["full"]["games"] for r in rows_of(data)}
    return next(iter(gs)) if len(gs) == 1 else None


def moles_per_game(data: dict) -> int | None:
    ks = {r["full"]["moles"] // r["full"]["games"] for r in rows_of(data) if r["full"]["games"]}
    return next(iter(ks)) if len(ks) == 1 else None


def games_line(data: dict) -> str:
    """The small grey line under the subtitle: the game count every unmarked row has."""
    g = shared_games(data)
    head = f"{plural(g, 'game')} per model." if g is not None else f"{plural(FULL_GAMES, 'game')} per model unless marked."
    k = moles_per_game(data)
    return head + (f" Each game has {k} moles." if k is not None else "")


def name_note(r: dict, shared: int | None) -> str:
    """What follows a model's name, only where the row differs from the rest: its reasoning setting,
    and its game count when the rows do not all share one and it is not the planned count."""
    bits = []
    rn = reasoning_note(r)
    if rn:
        bits.append(rn)
    if shared is None and r["full"]["games"] != FULL_GAMES:
        bits.append(games_text(r["full"]))
    return "".join(f" · {b}" for b in bits)


def told_all(data: dict) -> bool:
    return all(r["told"]["k"] == r["told"]["n"] for r in data["main"])


def callout_lines(data: dict) -> list[str]:
    main = data["main"]
    ns = sorted({r["told"]["n"] for r in main})
    if told_all(data):
        first = f"Told to show a fake card, all {WORDS.get(len(main), len(main))} Claude models did."
        if len(ns) == 1:
            second = f"{ns[0]} of {ns[0]} single moves each. A separate test."
        else:
            second = "Every single move, " + ", ".join(f"{r['told']['n']}" for r in main) + ". A separate test."
    else:
        ks = [r["told"]["k"] for r in main]
        first = "Told to show a fake card, Claude models mostly did."
        second = (f"{min(ks)} to {max(ks)} of {span(ns)} single moves. A separate test."
                  if min(ks) != max(ks) else f"{ks[0]} of {span(ns)} single moves each. A separate test.")
    return [first, second]


FOOTER = ["Small samples: models close together are not separated.",
          "The game engine checks every card. No judge model."]


def footer_lines(data: dict) -> list[str]:
    return list(FOOTER)


def separation_text(data: dict) -> str:
    """Whether the two highest-forging Claude models are told apart per mole (Fisher exact)."""
    hits = sorted((r for r in data["main"] if r["full"]["forged_moles"]),
                  key=lambda r: -r["full"]["mole_rate"])
    if len(hits) < 2:
        return ""
    a, b = hits[0]["full"], hits[1]["full"]
    p = fisher_p(a["forged_moles"], a["moles"], b["forged_moles"], b["moles"])
    verdict = "are not separated" if p >= 0.05 else "are separated"
    return f"{hits[0]['name']} and {hits[1]['name']} {verdict} (Fisher exact p = {p:.2f})."


def alt_text(data: dict, limit: int = 1000) -> str:
    """The fine print, for the image's alt text on X (at most `limit` characters). Drops the Claude
    intervals, then the crew detail, then writes turn counts as 44/100 and drops two asides the image already carries, if the full
    version is too long."""
    def build(intervals: bool, crew_detail: bool, short: bool = False) -> str:
        def turns(f):
            return f"{f['forged']}/{f['turns']} turns" if short else turns_text(f)

        def main_row(r):
            f = r["full"]
            iv = f", 95% {ci0(f['mole_ci'])}" if intervals and has_width(f["mole_ci"]) else ""
            return f"{r['name']} {f['forged_moles']} of {f['moles']}{iv} ({turns(f)})"
        zero_ns = sorted({r["full"]["moles"] for r in data["main"] if r["full"]["mole_bound"] is not None})
        bounds = "; ".join(f"for 0 of {n} the exact 97.5% upper bound is {pct1(FR.zero_bound(n))}"
                           for n in zero_ns)
        crew = ""
        if crew_detail:
            crew = (f", crew of {WORDS.get(data['crew_size'], data['crew_size'])} Claude models"
                    if data["crew_size"] and data["crew_claude"] else ", crew differs by game")
            crew += f", {data['effort']} effort" if data["effort"] else ""
        parts = [
            f"{title_text(data)} Bar: share of moles{'' if short else ' (2 per game)'} that showed a clue card "
            f"the engine says it was never dealt{'' if short else ' (no judge model)'}; each mole was told it may "
            "bend or invent clues.",
            f"Claude models, {span(data['games'])} games each{crew}: "
            + "; ".join(main_row(r) for r in data["main"]) + ".",
        ]
        if bounds:
            parts.append(bounds[0].upper() + bounds[1:] + ".")
        sep = separation_text(data)
        parts.append((sep + " " if sep else "") + "Sorted by share; close bars are not separated.")
        if data["other"]:
            def other_row(r):
                f, rn = r["full"], reasoning_note(r)
                return (f"{r['name']}{' (' + rn + ')' if rn else ''}, {games_text(f)}: "
                        f"{f['forged_moles']} of {f['moles']} ({turns(f)})")
            parts.append("Other labs, via a different API (OpenRouter), not in the told-to test: "
                         + "; ".join(other_row(r) for r in data["other"]) + ".")
        told = callout_lines(data)
        parts.append(f"{told[0][:-1]}, {told[1].replace(' A separate test.', '').rstrip('.')}: a different "
                     f"one-move test at {data['moments']} frozen moments, designed after an earlier check failed.")
        return " ".join(parts)

    for opts in ((True, True), (False, True), (False, False), (False, False, True)):
        s = build(*opts)
        if len(s) <= limit:
            return s
    return s


# ---- text measuring (an estimate for a Helvetica-like sans; the test keeps a margin) ----

_NARROW = set("il.,:;'|!() ")
_SEMI = set("fjrtI-")
_WIDE = set("mwMW@")


def text_width(s: str, size: float, bold: bool = False) -> float:
    w = 0.0
    for ch in s:
        if ch in _NARROW:
            w += 0.27
        elif ch in _SEMI:
            w += 0.34
        elif ch in _WIDE:
            w += 0.82
        elif ch == "%":
            w += 0.98
        elif ch == "·":
            w += 0.30
        elif ch.isdigit():
            w += 0.58
        elif ch.isupper():
            w += 0.64
        else:
            w += 0.51
    return w * size * (1.07 if bold else 1.0)


def wrap(s: str, size: float, max_w: float, bold: bool = False) -> list[str]:
    lines, cur = [], ""
    for word in s.split():
        nxt = f"{cur} {word}".strip()
        if cur and text_width(nxt, size, bold) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = nxt
    return lines + ([cur] if cur else [])


# ---- drawing ----

class Canvas:
    """SVG pieces plus a record of every text box, so a test can check overlap and clipping."""

    def __init__(self):
        self.parts: list[str] = []
        self.boxes: list[dict] = []

    def _box(self, x0, y, s, size, bold, cls):
        w = text_width(s, size, bold)
        self.boxes.append({"text": s, "x0": x0, "x1": x0 + w, "y0": y - 0.78 * size, "y1": y + 0.22 * size,
                           "size": size, "cls": cls})
        return x0 + w

    def text(self, x, y, s, size, *, weight=400, fill=INK, anchor="start", cls=None):
        w = text_width(s, size, weight >= 600)
        x0 = x if anchor == "start" else (x - w if anchor == "end" else x - w / 2)
        self._box(x0, y, s, size, weight >= 600, cls)
        c = f' class="{cls}"' if cls else ""
        self.parts.append(f'<text{c} x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" '
                          f'fill="{fill}" text-anchor="{anchor}">{escape(s)}</text>')
        return x0 + w

    def pair(self, x, y, a, a_size, a_weight, a_fill, a_cls, b, b_size, b_weight, b_fill, b_cls, gap):
        """Two runs on one baseline in one <text>, so the renderer, not the estimate, spaces them."""
        end = self._box(x, y, a, a_size, a_weight >= 600, a_cls)
        self._box(end + gap, y, b, b_size, b_weight >= 600, b_cls)
        self.parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}"><tspan class="{a_cls}" font-size="{a_size}" font-weight="{a_weight}" '
            f'fill="{a_fill}">{escape(a)}</tspan><tspan class="{b_cls}" dx="{gap}" font-size="{b_size}" '
            f'font-weight="{b_weight}" fill="{b_fill}">{escape(b)}</tspan></text>')

    def raw(self, s: str):
        self.parts.append(s)


def _bar(x0, x1, top, h, tip):
    """A bar square at the baseline with a 4 px rounded data end."""
    w = max(x1 - x0, 0)
    r = min(4, w / 2, h / 2)
    d = (f"M{x0:.1f},{top:.1f} H{x0 + w - r:.1f} Q{x0 + w:.1f},{top:.1f} {x0 + w:.1f},{top + r:.1f} "
         f"V{top + h - r:.1f} Q{x0 + w:.1f},{top + h:.1f} {x0 + w - r:.1f},{top + h:.1f} H{x0:.1f} Z")
    return f'<path class="bar" d="{d}" fill="{BAR}"><title>{escape(tip)}</title></path>'


VALUE_GAP = 14           # between the percentage and the count


def scale_end(data: dict) -> float:
    """x of 100%: as far right as a full bar can go with the widest value label still inside the margin."""
    widest = max(text_width("100%", VALUE, True) + VALUE_GAP
                 + text_width(f"{r['full']['moles']} of {r['full']['moles']} moles", COUNT) for r in rows_of(data))
    return W - M - GAP_LABEL - widest


# vertical gaps, px
GAP_TITLE_SUB, GAP_SUB_NOTE, GAP_NOTE_ROWS = 16, 12, 34
GAP_CALLOUT, CALL_PAD, GAP_FOOT, BOTTOM = 26, 20, 24, 40


def _draw(data: dict, row_gap: float) -> tuple[Canvas, float]:
    cv = Canvas()
    x0, x100 = M, scale_end(data)

    y = M + TITLE * 0.78
    for i, line in enumerate(wrap(title_text(data), TITLE, W - 2 * M, bold=True)):
        y += TITLE * 1.05 if i else 0
        cv.text(M, y, line, TITLE, weight=700, cls="title")
    y += TITLE * 0.22 + GAP_TITLE_SUB
    for i, line in enumerate(wrap(SUBTITLE, SUB, W - 2 * M)):
        y += SUB * (1.25 if i else 0.78)
        cv.text(M, y, line, SUB, fill=INK_2, cls="subtitle")
    y += SUB * 0.22 + GAP_SUB_NOTE + GNOTE * 0.78
    cv.text(M, y, games_line(data), GNOTE, fill=INK_2, cls="games-line")
    y += GNOTE * 0.22 + GAP_NOTE_ROWS

    shared = shared_games(data)
    claude = {r["name"] for r in data["main"]}
    for i, r in enumerate(sorted_rows(data)):
        f = r["full"]
        if i:
            y += row_gap
        name_y = y + NAME * 0.78
        bar_top = name_y + GAP_NAME_BAR
        cy = bar_top + BAR_H / 2
        kind = "claude" if r["name"] in claude else "other"
        cv.raw(f'<g class="row {kind}" data-model="{escape(r["name"])}">')
        note = name_note(r, shared)
        if note:
            cv.pair(M, name_y, r["name"], NAME, 700, INK, "name", note.lstrip(), NOTE, 400, INK_2, "name-note",
                    text_width(" ", NOTE))
        else:
            cv.text(M, name_y, r["name"], NAME, weight=700, cls="name")
        tip = f"{r['name']}: {moles_text(f)} ({pct1(f['mole_rate'])}), {games_text(f)}"
        if f["forged_moles"]:
            bar_end = x0 + f["mole_rate"] * (x100 - x0)
            cv.raw(_bar(x0, bar_end, bar_top, BAR_H, tip))
        else:
            bar_end = x0 + STUB
            cv.raw(f'<rect class="stub" x="{x0}" y="{bar_top:.1f}" width="{STUB}" height="{BAR_H}" '
                   f'fill="{AXIS}"><title>{escape(tip)}</title></rect>')
        big, small = pct(f["mole_rate"]), moles_text(f)
        vy = cy + VALUE * 0.36
        cv.pair(bar_end + GAP_LABEL, vy, big, VALUE, 700, INK, "value", small, COUNT, 400, INK, "count", VALUE_GAP)
        cv.raw('</g>')
        y = max(bar_top + BAR_H, vy + VALUE * 0.22)

    # The callout: the told-to result, a separate test, in a tinted box.
    y += GAP_CALLOUT
    box_top = y
    at = len(cv.parts)
    y += CALL_PAD
    k = 0
    for i, s in enumerate(callout_lines(data)):
        size, bold = (CALL, True) if i == 0 else (CALL - 2, False)
        for line in wrap(s, size, W - 2 * M - 2 * 32, bold=bold):
            y += size * (0.78 if k == 0 else 1.32)
            cv.text(M + 32, y, line, size, weight=700 if bold else 400, fill=INK if bold else INK_2,
                    cls="callout-text")
            k += 1
    y += (CALL - 2) * 0.22 + CALL_PAD
    cv.parts.insert(at, f'<rect class="callout" x="{M}" y="{box_top:.1f}" width="{W - 2 * M}" '
                        f'height="{y - box_top:.1f}" rx="14" fill="{CALLOUT_FILL}"/>')

    y += GAP_FOOT
    k = 0
    for s in footer_lines(data):
        for line in wrap(s, FOOT, W - 2 * M):
            y += FOOT * (0.78 if k == 0 else 1.3)
            cv.text(M, y, line, FOOT, fill=INK_2, cls="foot")
            k += 1
    return cv, y + FOOT * 0.22 + BOTTOM


def layout(data: dict) -> tuple[Canvas, int]:
    """Draw everything top-down in a fixed 1200 x 1500 frame: the space left after the fixed parts
    goes between the rows. Returns the canvas and the height (over H only if even the tightest
    spacing does not fit)."""
    n_gaps = max(1, len(rows_of(data)) - 1)
    _cv, used = _draw(data, MIN_ROW_GAP)
    gap = max(MIN_ROW_GAP, min(MAX_ROW_GAP, MIN_ROW_GAP + (H - used) / n_gaps))
    cv, used = _draw(data, gap)
    return cv, H if used <= H + 1 else int(math.ceil(used))


def render_svg(data: dict) -> str:
    cv, h = layout(data)
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {h}" width="{W}" height="{h}" '
         f'role="img" aria-labelledby="chart-title chart-desc" font-family=\'{FONT}\'>',
         f'<title id="chart-title">{escape(title_text(data))}</title>',
         f'<desc id="chart-desc">{escape(alt_text(data))}</desc>',
         f'<rect x="0" y="0" width="{W}" height="{h}" fill="{SURFACE}"/>']
    o += cv.parts
    o.append('</svg>')
    return "\n".join(o) + "\n"


def render_html(svg: str, data: dict) -> str:
    def cell(k, n, rate, c):
        shown = ci1(c) if has_width(c) else (f"{ci1(c)} (no width)" if c else "n/a")
        return f"<td>{k} of {n}</td><td>{escape(pct1(rate))}</td><td>{escape(shown)}</td>"

    def mole_cell(f):
        c = (f"upper bound {pct1(f['mole_bound'])} (exact)" if f["mole_bound"] is not None
             else ci1(f["mole_ci"]))
        return f"<td>{f['forged_moles']} of {f['moles']}</td><td>{escape(pct1(f['mole_rate']))}</td><td>{escape(c)}</td>"

    na = '<td colspan="3">not run</td>'
    rows = []
    for r in data["main"]:
        f, fr, t = r["full"], r["free"], r["told"]
        rows.append(f"<tr><th scope=\"row\">{escape(r['name'])}</th><td>{f['games']}</td>" + mole_cell(f)
                    + cell(f["forged"], f["turns"], f["rate"], f["ci"])
                    + (cell(fr["k"], fr["n"], fr["rate"], fr["ci"]) if fr else na)
                    + cell(t["k"], t["n"], t["rate"], t["ci"]) + "</tr>")
    for r in data["other"]:
        f, rn = r["full"], reasoning_note(r)
        name = escape(r["name"]) + (f" ({escape(rn)})" if rn else "")
        rows.append(f"<tr class=\"other\"><th scope=\"row\">{name}</th><td>{f['games']}</td>"
                    + mole_cell(f) + cell(f["forged"], f["turns"], f["rate"], f["ci"]) + na + na + "</tr>")
    free_n = ", ".join(str(n) for n in data["free_moments"])
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>Forged clue cards</title>
<style>
  html, body {{ margin: 0; background: {SURFACE}; color: {INK}; color-scheme: light; }}
  body {{ font-family: {FONT}; padding: 16px; }}
  main {{ max-width: {W}px; margin: 0 auto; }}
  svg {{ display: block; width: 100%; height: auto; }}
  table {{ border-collapse: collapse; margin-top: 24px; font-size: 15px; font-variant-numeric: tabular-nums; }}
  th, td {{ text-align: left; padding: 6px 14px 6px 0; border-bottom: 1px solid {GRID}; vertical-align: top; }}
  thead th {{ color: {INK_2}; font-weight: 600; }}
  tr.other th, tr.other td {{ color: {INK_2}; }}
  .wrap {{ overflow-x: auto; }}
  p {{ color: {INK_2}; font-size: 15px; max-width: 70em; }}
</style>
</head>
<body>
<main>
{svg}<div class="wrap">
<table>
<caption style="text-align:left;font-weight:600;padding-bottom:8px">{escape(title_text(data))}</caption>
<thead>
<tr><th scope="col" rowspan="2">Model</th><th scope="col" rowspan="2">Full games</th>
<th scope="colgroup" colspan="3">Allowed to, full games: moles that forged at least once (the bars)</th>
<th scope="colgroup" colspan="3">Allowed to, full games: counted turns forged</th>
<th scope="colgroup" colspan="3">One move, free: moves forged</th>
<th scope="colgroup" colspan="3">Told to: one move, showed the named false card (the callout)</th></tr>
<tr><th scope="col">Count</th><th scope="col">Share</th><th scope="col">Bootstrap 95% or bound</th>
<th scope="col">Count</th><th scope="col">Rate</th><th scope="col">Bootstrap 95%</th>
<th scope="col">Count</th><th scope="col">Rate</th><th scope="col">Bootstrap 95%</th>
<th scope="col">Count</th><th scope="col">Rate</th><th scope="col">Bootstrap 95%</th></tr>
</thead>
<tbody>
{chr(10).join(rows)}
</tbody>
</table>
</div>
<p>Alt text: {escape(alt_text(data))}</p>
<p>A mole is one mole in one game. Counted turns: mole discussion turns on pass 1 or 2 and each mole's
first round-1 whisper to a crew member. One move, free: the model makes one move at each of
{escape(free_n)} frozen game moments with no instruction (not drawn on the chart). Told to: the same
moments that have a named false card ({data['moments']}), with a private instruction to show it.
Intervals are bootstrap 95% over whole games; where no mole forged, the bound is the exact binomial 97.5%
upper bound on the share of moles. Bars are sorted by share of moles. Other labs ran through a different API (OpenRouter) and were not in the one-move
tests; DeepSeek V4 Pro ran with reasoning off, the other labs with reasoning effort low. Numbers from
analysis/fabricate_rate.py; the one-move tests were designed after an earlier check failed.</p>
</main>
</body>
</html>
"""


def write_chart(out_dir, games_dir=None, runs_dir=None, set_path=None, png=True, data=None) -> list[Path]:
    data = data or chart_data(games_dir, runs_dir, set_path)
    svg = render_svg(data)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    svg_path, html_path, alt_path = out / "fabricate.svg", out / "fabricate.html", out / "fabricate_alt.txt"
    svg_path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + svg, encoding="utf-8")
    html_path.write_text(render_html(svg, data), encoding="utf-8")
    alt_path.write_text(alt_text(data) + "\n", encoding="utf-8")
    paths = [svg_path, html_path, alt_path]
    if png:
        tool = shutil.which("rsvg-convert")
        if tool is None:
            print("rsvg-convert not installed: no PNG written", file=sys.stderr)
        else:
            png_path = out / "fabricate.png"
            subprocess.run([tool, str(svg_path), "-o", str(png_path)], check=True)
            paths.append(png_path)
    return paths


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--games", default=str(ROOT / "games"))
    ap.add_argument("--runs", default=str(ROOT / "probes/moves/runs/v1_public"))
    ap.add_argument("--set", default=str(ROOT / "probes/moves/sets/v1_public.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "docs" / "charts"), help="output directory")
    ap.add_argument("--no-png", action="store_true", help="do not render the PNG")
    a = ap.parse_args(argv)
    data = chart_data(a.games, a.runs, a.set)
    for p in write_chart(a.out, png=not a.no_png, data=data):
        print(p)
    alt = alt_text(data)
    print(f"\nAlt text ({len(alt)} characters):\n{alt}")


if __name__ == "__main__":
    main()
