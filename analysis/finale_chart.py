"""Chart: two moles of the same model won the game together. What did they do with the pot?

Writes docs/charts/finale.svg, docs/charts/finale_alt.txt (alt text for X, at most 1,000 characters)
and docs/charts/finale.png when `rsvg-convert` is installed. Every number is counted from the finished
game logs at run time; this file types in no result. Zero model calls, read only.

Unit: one finale between the two moles of a mole-benchmark game (in these batches both moles are the
same model). The moles reach the finale only when they win with both alive; each then chooses split
or steal in secret over the pot (both split: half each; one steals: all of it to the stealer; both
steal: nothing). Per model, finales are counted by outcome: both split, one stole, both stole.

Built for a phone feed like analysis/fabricate_chart.py: 1200 x 1500 px (4:5), the same fonts, ink
and footer style, no text under 30 px. One row per model in a fixed neutral order (Claude models, then
the other labs A to Z), never sorted by outcome. Bars are on a count scale (one finale = one unit), so
a model with fewer finales has a shorter bar. The three outcomes are one blue ramp, light to dark by
the number of players who stole, and every segment carries its count and outcome in words.

    env -u OPENROUTER_API_KEY python3.11 analysis/finale_chart.py [--games games] [--out docs/charts] [--no-png]
"""
from __future__ import annotations

import argparse
import collections
import json
import shutil
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import fabricate_chart as FC  # noqa: E402  (fonts, ink, text measure, Canvas, DeepSeek's reasoning setting)

# Fixed neutral order: the Claude models, then the other labs alphabetically. Never sorted by outcome.
GROUPS = [
    ("Fable 5.2", ["headroom1", "bluff_fable52"]),
    ("Opus 5.5", ["bluff_opus55"]),
    ("Sonnet 5.5", ["bluff_sonnet55"]),
    ("Haiku 5.5", ["bluff_haiku55"]),
    ("DeepSeek V4 Pro", ["bluff_deepseek"]),
    ("Gemini 4 Carbon", ["bluff_gemini"]),
    ("Grok 4.7", ["bluff_grok47"]),
    ("Kimi K3.1 Pro", ["bluff_kimi"]),
]
CLAUDE = {"Fable 5.2", "Opus 5.5", "Sonnet 5.5", "Haiku 5.5"}
DEEPSEEK = "DeepSeek V4 Pro"

OUTCOMES = ["both_split", "one_stole", "both_stole"]           # by the number of players who stole: 0, 1, 2
WORDS = {"both_split": "both split", "one_stole": "one stole", "both_stole": "both stole"}
# Ordinal blue ramp (dataviz palette, blue 250 / 450 / 650; validated with --ordinal on #fcfcfb).
FILL = {"both_split": "#86b6ef", "one_stole": "#2a78d6", "both_stole": "#104281"}
LABEL_INK = {"both_split": FC.INK, "one_stole": "#ffffff", "both_stole": "#ffffff"}

TITLE_LINES = ["Two moles of the same model won.", "What did they do with the pot?"]
FOOTER = ["Small counts. Not a planned test.",
          "Each finalist faced a copy of itself.",
          "In a one-shot finale, stealing never pays less than splitting."]

# Layout, px in a fixed 1200 x 1500 viewBox.
W, H, M = 1200, 1500, 60
TITLE, LEAD, LEG_NAME, LEG_PAY, NAME, NOTE, SEG_N, SEG_W, FOOT = 60, 34, 34, 30, 40, 30, 34, 30, 30
BAR_H = 80
SWATCH = 30
SEG_GAP = 2              # surface gap between touching segments
SEG_PAD = 14             # inner padding of a segment label


# ---- data ----

def index_rows(games_dir, batches) -> list[dict]:
    """Last index row per (batch, seed) for the given batches; spoiled and mock rows left out; the
    log path resolved (an index path that does not exist is looked up next to the index)."""
    games_dir = Path(games_dir)
    latest = {}
    with open(games_dir / "index.jsonl", encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("batch") in batches and not r.get("spoiled") and not r.get("mock"):
                latest[(r["batch"], r.get("seed"))] = r
    out = []
    for r in latest.values():
        log = Path(r["log"])
        if not log.is_absolute():
            log = ROOT / log
        if not log.exists():
            log = games_dir / Path(r["log"]).name
        if log.exists():
            out.append(dict(r, _log=log))
    return sorted(out, key=lambda r: (r["batch"], r.get("seed")))


def read_events(path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def outcome_of(choices: dict) -> str:
    steals = sum(c == "steal" for c in choices.values())
    return OUTCOMES[steals]


def mole_finale(events: list[dict]) -> dict | None:
    """The finale of a finished game if both finalists were moles, else None (a crew finale, no
    finale, or an unfinished or mock game)."""
    start = next((e for e in events if e.get("type") == "game_start"), None)
    if start is None or start.get("mock") or not any(e.get("type") == "game_end" for e in events):
        return None
    role = {e["player"]: e["role"] for e in events if e.get("type") == "role"}
    model = {p["name"]: p["model"] for p in start.get("players", [])}
    fr = next((e for e in events if e.get("type") == "finale_result"), None)
    if fr is None or len(fr["choices"]) != 2 or not all(role.get(p) == "mole" for p in fr["choices"]):
        return None
    return {"game_id": start.get("game_id"), "seed": start.get("seed"), "seq": fr.get("seq"),
            "choices": dict(fr["choices"]), "stated": dict(fr.get("stated") or {}),
            "payouts": dict(fr.get("payouts") or {}), "models": sorted({model.get(p) for p in fr["choices"]}),
            "pot": (start.get("config") or {}).get("game", {}).get("pot"),
            "outcome": outcome_of(fr["choices"])}


def count_finales(games_dir=None, groups=GROUPS) -> list[dict]:
    """Per model, in the given order: games read, mole-vs-mole finales by outcome, and each finale."""
    games_dir = Path(games_dir or ROOT / "games")
    out = []
    for name, batches in groups:
        rows = index_rows(games_dir, batches)
        counts = collections.Counter()
        finales, games = [], 0
        for r in rows:
            ev = read_events(r["_log"])
            if not any(e.get("type") == "game_end" for e in ev):
                continue
            games += 1
            f = mole_finale(ev)
            if f:
                f["batch"] = r["batch"]
                counts[f["outcome"]] += 1
                finales.append(f)
        row = {"name": name, "batches": list(batches), "games": games, "finales": finales,
               "total": len(finales), **{o: counts[o] for o in OUTCOMES}}
        if name == DEEPSEEK:
            row["reasoning"] = FC.deepseek_reasoning()
        out.append(row)
    return out


def steals_by_model(data: list[dict]) -> dict:
    """{model id: (finalist seats, steals)} from the counts, for the cross-check with
    analysis/extra_stats.finale."""
    by = collections.defaultdict(lambda: [0, 0])
    for r in data:
        for f in r["finales"]:
            for p, c in f["choices"].items():
                m = f["models"][0] if len(f["models"]) == 1 else None
                by[m][0] += 1
                by[m][1] += c == "steal"
    return {k: tuple(v) for k, v in by.items()}


def chart_data(games_dir=None) -> dict:
    rows = count_finales(games_dir)
    pots = {f["pot"] for r in rows for f in r["finales"]}
    same = all(len(f["models"]) == 1 for r in rows for f in r["finales"])
    return {"rows": rows, "pot": next(iter(pots)) if len(pots) == 1 else None, "same_model": same}


def payoff_text(outcome: str, pot) -> str:
    """The legend line under each outcome, computed from the pot."""
    if pot is None:
        return ""
    half = pot // 2
    return {"both_split": f"{half} each", "one_stole": f"{pot} and 0", "both_stole": "0 each"}[outcome]


# ---- wording ----

def reasoning_note(r: dict) -> str | None:
    if "reasoning" not in r:
        return None
    v = r["reasoning"]
    return "reasoning off" if v == "none" else (f"reasoning {v}" if v else "reasoning setting not found")


def plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def drawn(data: dict) -> list[dict]:
    return [r for r in data["rows"] if r["total"]]


def segments(r: dict) -> list[tuple[str, int]]:
    return [(o, r[o]) for o in OUTCOMES if r[o]]


def seg_label(o: str, k: int, total: int) -> tuple[str, str]:
    return f"{k} of {total}", WORDS[o]


def footer_lines(data: dict) -> list[str]:
    lines = list(FOOTER)
    if not data["same_model"]:
        lines[1] = "Most finalists faced a copy of itself."   # never drawn on the current logs; the test asserts same_model
    return lines


def lead_text(data: dict) -> str:
    pot = data["pot"]
    return (f"Each chose in secret: split or steal a {pot}-point pot." if pot
            else "Each chose in secret: split or steal the pot.")


def row_alt(r: dict) -> str:
    rn = reasoning_note(r)
    head = f"{r['name']}{' (' + rn + ')' if rn else ''}"
    if not r["total"]:
        return f"{head}: no finale ({plural(r['games'], 'game')})"
    parts = [f"{k} {WORDS[o]}" for o, k in segments(r)]
    return f"{head}, {plural(r['total'], 'finale')} in {plural(r['games'], 'game')}: {', '.join(parts)}"


def alt_text(data: dict, limit: int = 1000) -> str:
    pot = data["pot"]
    pay = (f" Both split: {payoff_text('both_split', pot)}; one steals: {payoff_text('one_stole', pot)}; "
           f"both steal: {payoff_text('both_stole', pot)}." if pot else "")

    def build(long: bool) -> str:
        parts = [
            f"Chart. {' '.join(TITLE_LINES)} When the two moles win with both alive, each chooses split or "
            f"steal in secret{f' over a {pot}-point pot' if pot else ''}.{pay}",
            "Finales per model, both moles the same model: " + "; ".join(row_alt(r) for r in data["rows"]) + ".",
            "Rows: Claude models, then other labs A to Z; not a ranking.",
            " ".join(footer_lines(data)),
        ]
        if long:
            parts.append("Other labs played through OpenRouter; crew were Claude models. Counted from the game logs.")
        return " ".join(parts)
    s = build(True)
    return s if len(s) <= limit else build(False)


# ---- drawing ----

def unit_px(data: dict) -> float:
    """Width of one finale: the longest bar fills the width between the margins."""
    longest = max((r["total"] for r in drawn(data)), default=1)
    return (W - 2 * M) / longest


def label_fits(o: str, k: int, total: int, width: float) -> bool:
    a, b = seg_label(o, k, total)
    need = max(FC.text_width(a, SEG_N, True), FC.text_width(b, SEG_W)) + 2 * SEG_PAD
    return need <= width - SEG_GAP


def _seg_path(x0, x1, top, h, round_right, fill, tip, o):
    w = max(x1 - x0, 0)
    r = min(4, w / 2, h / 2) if round_right else 0
    d = (f"M{x0:.1f},{top:.1f} H{x1 - r:.1f} Q{x1:.1f},{top:.1f} {x1:.1f},{top + r:.1f} "
         f"V{top + h - r:.1f} Q{x1:.1f},{top + h:.1f} {x1 - r:.1f},{top + h:.1f} H{x0:.1f} Z")
    return f'<path class="seg {o}" d="{d}" fill="{fill}"><title>{escape(tip)}</title></path>'


GAP_TITLE_LEAD, GAP_LEAD_LEG, GAP_LEG_ROWS, GAP_NAME_BAR, GAP_FOOT, BOTTOM = 12, 24, 30, 6, 28, 26
MIN_ROW_GAP, MAX_ROW_GAP = 8, 40


def _draw(data: dict, row_gap: float) -> tuple[FC.Canvas, float]:
    cv = FC.Canvas()
    y = M + TITLE * 0.78
    for i, line in enumerate(TITLE_LINES):
        y += TITLE * 1.08 if i else 0
        cv.text(M, y, line, TITLE, weight=700, cls="title")
    y += TITLE * 0.22 + GAP_TITLE_LEAD + LEAD * 0.78
    cv.text(M, y, lead_text(data), LEAD, fill=FC.INK_2, cls="lead")
    y += LEAD * 0.22 + GAP_LEAD_LEG

    # Legend: three columns, swatch + outcome, payoff underneath.
    col = (W - 2 * M) / 3
    ly = y + LEG_NAME * 0.78
    for i, o in enumerate(OUTCOMES):
        x = M + i * col
        cv.raw(f'<rect class="swatch {o}" x="{x:.1f}" y="{ly - LEG_NAME * 0.78 + 2:.1f}" width="{SWATCH}" '
               f'height="{SWATCH}" rx="4" fill="{FILL[o]}"/>')
        cv.text(x + SWATCH + 12, ly, WORDS[o].capitalize(), LEG_NAME, weight=700, cls="legend")
        pay = payoff_text(o, data["pot"])
        if pay:
            cv.text(x + SWATCH + 12, ly + LEG_PAY * 1.25, pay, LEG_PAY, fill=FC.INK_2, cls="legend-pay")
    y = ly + LEG_PAY * 1.25 + LEG_PAY * 0.22 + GAP_LEG_ROWS

    u = unit_px(data)
    for i, r in enumerate(drawn(data)):
        if i:
            y += row_gap
        name_y = y + NAME * 0.78
        cv.raw(f'<g class="row" data-model="{escape(r["name"])}">')
        cv.pair(M, name_y, r["name"], NAME, 700, FC.INK, "name", "· " + plural(r["total"], "finale"), NOTE, 400,
                FC.INK_2, "name-note", FC.text_width(" ", NOTE))
        top = name_y + NAME * 0.22 + GAP_NAME_BAR
        x = M
        segs = segments(r)
        for j, (o, k) in enumerate(segs):
            x1 = x + k * u
            last = j == len(segs) - 1
            a, b = seg_label(o, k, r["total"])
            tip = f"{r['name']}: {a} finales {b}"
            cv.raw(_seg_path(x, x1 - (0 if last else SEG_GAP), top, BAR_H, last, FILL[o], tip, o))
            if label_fits(o, k, r["total"], x1 - x):
                ty = top + (BAR_H - (SEG_N * 0.78 + 6 + SEG_W)) / 2 + SEG_N * 0.78
                cv.text(x + SEG_PAD, ty, a, SEG_N, weight=700, fill=LABEL_INK[o], cls="seg-count")
                cv.text(x + SEG_PAD, ty + 6 + SEG_W * 1.0, b, SEG_W, fill=LABEL_INK[o], cls="seg-word")
            else:
                cv.text(x + (x1 - x) / 2, top + BAR_H / 2 + SEG_N * 0.36, str(k), SEG_N, weight=700,
                        fill=LABEL_INK[o], anchor="middle", cls="seg-count")
            x = x1
        cv.raw("</g>")
        y = top + BAR_H

    y += GAP_FOOT
    for k, line in enumerate(footer_lines(data)):
        y += FOOT * (0.78 if k == 0 else 1.25)
        cv.text(M, y, line, FOOT, fill=FC.INK_2, cls="foot")
    return cv, y + FOOT * 0.22 + BOTTOM


def layout(data: dict) -> tuple[FC.Canvas, int]:
    n_gaps = max(1, len(drawn(data)) - 1)
    _cv, used = _draw(data, MIN_ROW_GAP)
    gap = max(MIN_ROW_GAP, min(MAX_ROW_GAP, MIN_ROW_GAP + (H - used) / n_gaps))
    cv, used = _draw(data, gap)
    return cv, H if used <= H + 1 else int(used + 0.999)


def render_svg(data: dict) -> str:
    cv, h = layout(data)
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {h}" width="{W}" height="{h}" '
         f'role="img" aria-labelledby="chart-title chart-desc" font-family=\'{FC.FONT}\'>',
         f'<title id="chart-title">{escape(" ".join(TITLE_LINES))}</title>',
         f'<desc id="chart-desc">{escape(alt_text(data))}</desc>',
         f'<rect x="0" y="0" width="{W}" height="{h}" fill="{FC.SURFACE}"/>']
    o += cv.parts
    o.append("</svg>")
    return "\n".join(o) + "\n"


def write_chart(out_dir, games_dir=None, png=True, data=None) -> list[Path]:
    data = data or chart_data(games_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    svg_path, alt_path = out / "finale.svg", out / "finale_alt.txt"
    svg_path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + render_svg(data), encoding="utf-8")
    alt_path.write_text(alt_text(data) + "\n", encoding="utf-8")
    paths = [svg_path, alt_path]
    if png:
        tool = shutil.which("rsvg-convert")
        if tool is None:
            print("rsvg-convert not installed: no PNG written", file=sys.stderr)
        else:
            png_path = out / "finale.png"
            subprocess.run([tool, str(svg_path), "-o", str(png_path)], check=True)
            paths.append(png_path)
    return paths


def table(data: dict) -> str:
    lines = [f"{'model':<18} {'both split':>10} {'one stole':>10} {'both stole':>11} {'total':>6} {'games':>6}"]
    for r in data["rows"]:
        lines.append(f"{r['name']:<18} {r['both_split']:>10} {r['one_stole']:>10} {r['both_stole']:>11} "
                     f"{r['total']:>6} {r['games']:>6}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--games", default=str(ROOT / "games"))
    ap.add_argument("--out", default=str(ROOT / "docs" / "charts"), help="output directory")
    ap.add_argument("--no-png", action="store_true", help="do not render the PNG")
    a = ap.parse_args(argv)
    data = chart_data(a.games)
    for p in write_chart(a.out, png=not a.no_png, data=data):
        print(p)
    print("\n" + table(data))
    for r in data["rows"]:
        for f in r["finales"]:
            print(f"  {r['name']:<16} {f['game_id']} seq {f['seq']} {f['outcome']} {f['choices']}")
    alt = alt_text(data)
    print(f"\nAlt text ({len(alt)} characters):\n{alt}")


if __name__ == "__main__":
    main()
