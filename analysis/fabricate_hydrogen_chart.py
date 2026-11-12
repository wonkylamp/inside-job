"""Chart: docs/charts/fabricate.png with one more bar, Gemini 4 Hydrogen, added after the analysis.

Writes docs/charts/fabricate_hydrogen.svg, docs/charts/fabricate_hydrogen_alt.txt (the alt text for X,
at most 1,000 characters) and docs/charts/fabricate_hydrogen.png when `rsvg-convert` is installed. It
never writes docs/charts/fabricate.*: those stay the chart of the analysed set.

Everything but the drawing of one row and the footer is analysis/fabricate_chart.py, imported: its
data (`chart_data`), title, games line, callout, sort, text measure, Canvas, palette and size (1200 x
1500 px). The added bar is the same measure, read the same way: `fabricate_rate.moles` on the group
`HYDROGEN` (batch `bluff_hydrogen`), with the interval the fabricate chart's table gives (bootstrap
95% over whole games; 0 to the exact binomial 97.5% upper bound where no mole forged). As on fabricate.png, intervals are in the alt text, not drawn.

The added bar is drawn as an outline only and its name line says it was added after the analysis, with
the date its games were played (read from the game ids). The footer says the other bars come from the
games analysed (counted as analysis/extra_stats.py counts them: every real row of games/ and
games_frontier/ outside `extra_stats.AFTER_LAUNCH`). Zero model calls, read only.

    env -u OPENROUTER_API_KEY python3.11 analysis/fabricate_hydrogen_chart.py [--games games]
        [--frontier games_frontier] [--out docs/charts] [--no-png]
"""
from __future__ import annotations

import argparse
import math
import shutil
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (str(ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import extra_stats as ES  # noqa: E402  (AFTER_LAUNCH and the analysed-set reader)
import fabricate_chart as FC  # noqa: E402  (data, wording, layout pieces, palette)
import fabricate_rate as FR  # noqa: E402  (the groups of the analysed bars)

NAME = "fabricate_hydrogen"
HYDROGEN = ("Gemini 4 Hydrogen", "google/gemini-4-hydrogen", ["bluff_hydrogen"])
AFTER_WORDS = "added after the analysis"
OUTLINE = 4              # px, the added bar's outline
MOLE_PROMPT = "Moles are told they may bend or invent clues; they are not told to on any turn."
MOLE_PROMPT_SHORT = "Moles are told they may bend or invent clues, never told to."   # the image's one-line form

# Vertical spacing, px. fabricate.png's values except where a ninth row and a third footer line need
# the room to stay inside 1500 px (fabricate_chart: 34, 26, 24, 40 and a 10 px least row gap).
GAP_NOTE_ROWS, GAP_CALLOUT, GAP_FOOT, BOTTOM = 26, 22, 20, 32
MIN_ROW_GAP = 4


# ---- data ----

def _full(fg: dict, ml: dict) -> dict:
    """The `full` dict fabricate_chart.chart_data builds, from the same two readers' rows."""
    return {"games": fg["games"], "turns": fg["turns"], "forged": fg["forged_turns"], "rate": fg["rate"],
            "ci": fg["ci"], "moles": ml["moles"], "forged_moles": ml["forged_moles"], "mole_rate": ml["rate"],
            "mole_ci": ml["ci"], "mole_bound": ml["bound"]}


def played_on(games_dir, batches) -> str:
    """The day(s) the batch's games were played, from their game ids (g-YYYYMMDD-...)."""
    days = sorted({r["game_id"].split("-")[1] for r in FC._index_rows(games_dir, batches)})
    if not days:
        raise ValueError(f"no games of {batches} in {games_dir}")
    iso = [f"{d[:4]}-{d[4:6]}-{d[6:8]}" for d in days]
    return iso[0] if len(iso) == 1 else f"{iso[0]} to {iso[-1]}"


def analysed_games(games_dir, frontier_dir) -> int:
    """The analysed set's game count, as analysis/extra_stats.py reads it (later batches left out)."""
    return sum(len(ES.index_rows(Path(d) / "index.jsonl")) for d in (games_dir, frontier_dir))


def chart_data(games_dir=None, runs_dir=None, set_path=None, frontier_dir=None) -> dict:
    games_dir = Path(games_dir or ROOT / "games")
    frontier_dir = Path(frontier_dir or ROOT / "games_frontier")
    if not set(HYDROGEN[2]) <= ES.AFTER_LAUNCH:
        raise ValueError(f"{HYDROGEN[2]} is not marked as played after the analysis in extra_stats.AFTER_LAUNCH")
    data = FC.chart_data(games_dir, runs_dir, set_path)
    if any(set(b) & ES.AFTER_LAUNCH for _n, _m, b in FR.GROUPS + [FC.DEEPSEEK]):
        raise ValueError("a bar of the analysed set reads a batch played after the analysis")
    fg, ml = FC._read_games(games_dir, [HYDROGEN])
    f, m = fg[HYDROGEN[0]], ml[HYDROGEN[0]]
    if not f["games"] or not f["turns"]:
        raise ValueError(f"no finished {HYDROGEN[0]} game in {games_dir}")
    row = {"name": HYDROGEN[0], "full": _full(f, m), "after": True, "played": played_on(games_dir, HYDROGEN[2])}
    data["other"] = data["other"] + [row]
    data["analysed"] = analysed_games(games_dir, frontier_dir)
    return data


def after_rows(data: dict) -> list[dict]:
    return [r for r in FC.rows_of(data) if r.get("after")]


def interval(f: dict):
    """The interval of a `full` dict: bootstrap 95% over games, or 0 to the exact 97.5% upper bound
    when no mole forged."""
    if f["forged_moles"] == 0 and f["mole_bound"] is not None:
        return (0.0, f["mole_bound"])
    return f["mole_ci"]


# ---- wording ----

def after_note(r: dict) -> str:
    return f"· {AFTER_WORDS}, {r['played']}"


def short_name(r: dict) -> str:
    """The added model's own word (Gemini 4 Hydrogen -> Hydrogen), so its footer line fits one line."""
    return r["name"].split()[-1]


def footer_lines(data: dict) -> list[str]:
    """Three lines, each one line at 30 px: fabricate.png's "Small samples" line, the line about the
    added batch, and the mole-prompt note with "No judge model". fabricate.png's "The game engine checks
    every card" is said in the alt text instead, so the frame stays 1200 x 1500."""
    after = after_rows(data)
    names = " and ".join(short_name(r) for r in after)
    games = sum(r["full"]["games"] for r in after)
    return [FC.FOOTER[0],
            f"Other bars: the {data['analysed']} games analysed. {names}'s {games} games were played later.",
            MOLE_PROMPT_SHORT + " No judge model."]


def alt_text(data: dict, limit: int = 1000) -> str:
    """The fine print for X: every drawn row with its count, share and (if it fits) its interval."""
    def build(intervals: bool, short: bool) -> str:
        def row(r):
            f = r["full"]
            bits = [FC.reasoning_note(r)] if FC.reasoning_note(r) else []
            if f["games"] != FC.FULL_GAMES:
                bits.append(FC.games_text(f))
            if r.get("after"):
                bits.append(f"{AFTER_WORDS}, {r['played']}")
            name = r["name"] + (f" ({', '.join(bits)})" if bits else "")
            share = f"{FC.ci0(interval(f))}" if intervals else FC.pct(f["mole_rate"])
            return f"{name} {f['forged_moles']} of {f['moles']} ({share})"
        after = after_rows(data)
        how = "" if short else " (bootstrap over games, exact bound if 0)"
        parts = [
            f"{FC.title_text(data)} Bar: share of moles that at least once showed a clue card "
            "the engine says it was never dealt; no judge model. " + MOLE_PROMPT,
            "Sorted by share, " + FC.games_line(data).split(".")[0].lower()
            + (f"; 95% interval in brackets{how}" if intervals else "") + ": "
            + "; ".join(row(r) for r in FC.sorted_rows(data)) + ".",
            f"Other bars: the {data['analysed']} games analysed. "
            + " and ".join(f"{short_name(r)}'s {FC.games_text(r['full'])}" for r in after)
            + " were played later. Small samples: close bars are not separated.",
            "Other labs: via OpenRouter, not in the told-to test.",
        ]
        told = FC.callout_lines(data)
        parts.append(f"{told[0][:-1]} ({told[1].replace(' A separate test.', '').rstrip('.')}, a separate test).")
        return " ".join(parts)

    for opts in ((True, False), (True, True), (False, True)):
        s = build(*opts)
        if len(s) <= limit:
            return s
    return s


# ---- drawing (fabricate_chart._draw with the added row outlined and the longer footer) ----

def _outline_bar(x0, x1, top, h, tip):
    """The added row's bar: the same shape as fabricate_chart._bar, outline only, drawn inside its box."""
    i = OUTLINE / 2
    w = max(x1 - x0 - 2 * i, 0)
    a, t, hh = x0 + i, top + i, h - 2 * i
    r = min(4, w / 2, hh / 2)
    d = (f"M{a:.1f},{t:.1f} H{a + w - r:.1f} Q{a + w:.1f},{t:.1f} {a + w:.1f},{t + r:.1f} "
         f"V{t + hh - r:.1f} Q{a + w:.1f},{t + hh:.1f} {a + w - r:.1f},{t + hh:.1f} H{a:.1f} Z")
    return (f'<path class="bar after" d="{d}" fill="{FC.SURFACE}" stroke="{FC.BAR}" stroke-width="{OUTLINE}">'
            f'<title>{escape(tip)}</title></path>')


def _draw(data: dict, row_gap: float) -> tuple[FC.Canvas, float]:
    cv = FC.Canvas()
    M, W = FC.M, FC.W
    x0, x100 = M, FC.scale_end(data)

    y = M + FC.TITLE * 0.78
    for i, line in enumerate(FC.wrap(FC.title_text(data), FC.TITLE, W - 2 * M, bold=True)):
        y += FC.TITLE * 1.05 if i else 0
        cv.text(M, y, line, FC.TITLE, weight=700, cls="title")
    y += FC.TITLE * 0.22 + FC.GAP_TITLE_SUB
    for i, line in enumerate(FC.wrap(FC.SUBTITLE, FC.SUB, W - 2 * M)):
        y += FC.SUB * (1.25 if i else 0.78)
        cv.text(M, y, line, FC.SUB, fill=FC.INK_2, cls="subtitle")
    y += FC.SUB * 0.22 + FC.GAP_SUB_NOTE + FC.GNOTE * 0.78
    cv.text(M, y, FC.games_line(data), FC.GNOTE, fill=FC.INK_2, cls="games-line")
    y += FC.GNOTE * 0.22 + GAP_NOTE_ROWS

    shared = FC.shared_games(data)
    claude = {r["name"] for r in data["main"]}
    for i, r in enumerate(FC.sorted_rows(data)):
        f = r["full"]
        if i:
            y += row_gap
        name_y = y + FC.NAME * 0.78
        bar_top = name_y + FC.GAP_NAME_BAR
        cy = bar_top + FC.BAR_H / 2
        kind = "after" if r.get("after") else ("claude" if r["name"] in claude else "other")
        cv.raw(f'<g class="row {kind}" data-model="{escape(r["name"])}">')
        note = FC.name_note(r, shared) + (f" {after_note(r)}" if r.get("after") else "")
        if note:
            cv.pair(M, name_y, r["name"], FC.NAME, 700, FC.INK, "name", note.lstrip(), FC.NOTE, 400, FC.INK_2,
                    "name-note", FC.text_width(" ", FC.NOTE))
        else:
            cv.text(M, name_y, r["name"], FC.NAME, weight=700, cls="name")
        tip = f"{r['name']}: {FC.moles_text(f)} ({FC.pct1(f['mole_rate'])}), {FC.games_text(f)}"
        if r.get("after"):
            tip += f", {AFTER_WORDS}"
        if f["forged_moles"]:
            bar_end = x0 + f["mole_rate"] * (x100 - x0)
            cv.raw(_outline_bar(x0, bar_end, bar_top, FC.BAR_H, tip) if r.get("after")
                   else FC._bar(x0, bar_end, bar_top, FC.BAR_H, tip))
        else:
            bar_end = x0 + FC.STUB
            cv.raw(f'<rect class="stub" x="{x0}" y="{bar_top:.1f}" width="{FC.STUB}" height="{FC.BAR_H}" '
                   f'fill="{FC.AXIS}"><title>{escape(tip)}</title></rect>')
        big, small = FC.pct(f["mole_rate"]), FC.moles_text(f)
        vy = cy + FC.VALUE * 0.36
        cv.pair(bar_end + FC.GAP_LABEL, vy, big, FC.VALUE, 700, FC.INK, "value", small, FC.COUNT, 400, FC.INK,
                "count", FC.VALUE_GAP)
        cv.raw('</g>')
        y = max(bar_top + FC.BAR_H, vy + FC.VALUE * 0.22)

    y += GAP_CALLOUT
    box_top = y
    at = len(cv.parts)
    y += FC.CALL_PAD
    k = 0
    for i, s in enumerate(FC.callout_lines(data)):
        size, bold = (FC.CALL, True) if i == 0 else (FC.CALL - 2, False)
        for line in FC.wrap(s, size, W - 2 * M - 2 * 32, bold=bold):
            y += size * (0.78 if k == 0 else 1.32)
            cv.text(M + 32, y, line, size, weight=700 if bold else 400, fill=FC.INK if bold else FC.INK_2,
                    cls="callout-text")
            k += 1
    y += (FC.CALL - 2) * 0.22 + FC.CALL_PAD
    cv.parts.insert(at, f'<rect class="callout" x="{M}" y="{box_top:.1f}" width="{W - 2 * M}" '
                        f'height="{y - box_top:.1f}" rx="14" fill="{FC.CALLOUT_FILL}"/>')

    y += GAP_FOOT
    k = 0
    for s in footer_lines(data):
        for line in FC.wrap(s, FC.FOOT, W - 2 * M):
            y += FC.FOOT * (0.78 if k == 0 else 1.3)
            cv.text(M, y, line, FC.FOOT, fill=FC.INK_2, cls="foot")
            k += 1
    return cv, y + FC.FOOT * 0.22 + BOTTOM


def layout(data: dict) -> tuple[FC.Canvas, int]:
    """fabricate_chart.layout with this file's _draw and spacing: fixed 1200 x 1500, spare space
    between the rows."""
    n_gaps = max(1, len(FC.rows_of(data)) - 1)
    _cv, used = _draw(data, MIN_ROW_GAP)
    gap = max(MIN_ROW_GAP, min(FC.MAX_ROW_GAP, MIN_ROW_GAP + (FC.H - used) / n_gaps))
    cv, used = _draw(data, gap)
    return cv, FC.H if used <= FC.H + 1 else int(math.ceil(used))


def render_svg(data: dict) -> str:
    cv, h = layout(data)
    title = FC.title_text(data)
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {FC.W} {h}" width="{FC.W}" height="{h}" '
         f'role="img" aria-labelledby="chart-title chart-desc" font-family=\'{FC.FONT}\'>',
         f'<title id="chart-title">{escape(title)}</title>',
         f'<desc id="chart-desc">{escape(alt_text(data))}</desc>',
         f'<rect x="0" y="0" width="{FC.W}" height="{h}" fill="{FC.SURFACE}"/>']
    o += cv.parts
    o.append('</svg>')
    return "\n".join(o) + "\n"


def table(data: dict) -> str:
    L = [f"{'model':42} {'games':>5} {'moles':>12} {'share':>6}  95% interval"]
    for r in FC.sorted_rows(data):
        f = r["full"]
        name = r["name"] + (f" ({FC.reasoning_note(r)})" if FC.reasoning_note(r) else "") \
            + (f" ({AFTER_WORDS})" if r.get("after") else "")
        L.append(f"{name:42} {f['games']:>5} {FC.moles_text(f)[:-6]:>12} {FC.pct(f['mole_rate']):>6}  "
                 f"{FC.ci0(interval(f))}" + ("  (0 forged: exact 97.5% bound)" if not f["forged_moles"] else ""))
    return "\n".join(L)


def write_chart(out_dir, data, png=True) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    svg_path, alt_path = out / f"{NAME}.svg", out / f"{NAME}_alt.txt"
    svg_path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + render_svg(data), encoding="utf-8")
    alt_path.write_text(alt_text(data) + "\n", encoding="utf-8")
    paths = [svg_path, alt_path]
    if png:
        tool = shutil.which("rsvg-convert")
        if tool is None:
            print("rsvg-convert not installed: no PNG written", file=sys.stderr)
        else:
            png_path = out / f"{NAME}.png"
            subprocess.run([tool, str(svg_path), "-o", str(png_path)], check=True)
            paths.append(png_path)
    return paths


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--games", default=str(ROOT / "games"))
    ap.add_argument("--frontier", default=str(ROOT / "games_frontier"))
    ap.add_argument("--runs", default=str(ROOT / "probes/moves/runs/v1_public"))
    ap.add_argument("--set", default=str(ROOT / "probes/moves/sets/v1_public.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "docs" / "charts"), help="output directory")
    ap.add_argument("--no-png", action="store_true", help="do not render the PNG")
    a = ap.parse_args(argv)
    data = chart_data(a.games, a.runs, a.set, a.frontier)
    for p in write_chart(a.out, data, png=not a.no_png):
        print(p)
    print("\n" + table(data))
    alt = alt_text(data)
    print(f"\nAlt text ({len(alt)} characters):\n{alt}")


if __name__ == "__main__":
    main()
