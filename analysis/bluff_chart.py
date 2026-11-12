"""Chart: "How suspicious did each model's moles look?" from the bluff confirmation games (docs/CHART.md).

Writes docs/charts/bluff_gap.svg and docs/charts/bluff_gap.html (the same SVG in a standalone page,
nothing loaded from the network). Every number comes from analysis/bluff_score.py's functions, with
the same seeded RNG in the same draw order, so the intervals match what that script prints.

Run from anywhere: python3.11 analysis/bluff_chart.py [--index games/index.jsonl] [--out docs/charts]
Standard library only; hand-written SVG.
"""
from __future__ import annotations

import argparse
import math
import os
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import bluff_score  # noqa: E402

# Canvas: 16:9, sized for a 1600x900 image on X.
W, H = 1600, 900
FONT = 'system-ui, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif'

# Fixed light palette (dataviz reference instance; one series hue, the row label carries identity).
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
DOT = "#2a78d6"        # blue 450: one game
BAND = "#86b6ef"       # blue 250: bootstrap 95% interval
MEAN = "#0d366b"       # blue 700: mean

# Layout (px in the 1600x900 viewBox).
LEFT = 80              # left margin: title, row labels, footnote
PLOT_X0, PLOT_X1 = 420, 1520
ROW_Y0, ROW_PITCH = 320, 130
DOT_R = 10
LANES = (0, 26, -26, 52)   # vertical offsets used to keep near-equal games from hiding each other


def display_name(group: str) -> str:
    """'Fable 5.2 moles' -> 'Fable 5.2'."""
    return re.sub(r"\s+moles$", "", group)


def fmt(x: float) -> str:
    """Signed one-decimal number with a typographic minus: +15.9, −3.6, 0.0."""
    s = f"{x:+.1f}"
    if s in ("+0.0", "-0.0"):
        return "0.0"
    return s.replace("-", "−")


def fmt_tick(v: int) -> str:
    return "0" if v == 0 else (f"+{v}" if v > 0 else f"−{-v}")


def _seed_text(seeds: list[int]) -> str:
    if seeds and seeds == list(range(seeds[0], seeds[-1] + 1)) and len(seeds) > 2:
        return f"{seeds[0]}–{seeds[-1]}"
    return ", ".join(str(s) for s in seeds)


def _crew_of(row: dict) -> tuple[str, ...] | None:
    players = row.get("players")
    if not players:
        return None
    return tuple(sorted(re.sub(r" [A-Z]$", "", p["model_name"]) for p in players if p.get("role") == "crew"))


def chart_data(index_path=None, root=None, groups=bluff_score.GROUPS) -> dict:
    """Everything the chart shows, computed with bluff_score's functions.

    The bootstrap runs over groups in the given order with a fresh seeded RNG, exactly as the script
    does, so the intervals are the printed ones. Rows are then sorted lowest mean first."""
    root = str(ROOT if root is None else root)
    index_path = os.path.join(root, "games", "index.jsonl") if index_path is None else str(index_path)
    idx = bluff_score.load_index(index_path)
    res = bluff_score.group_games(idx, groups, root)
    summ = bluff_score.summaries(res, bluff_score.new_rng(), groups)
    rows = []
    for name, _ in groups:
        if name not in summ:
            continue
        s = summ[name]
        rows.append({
            "group": name,
            "name": display_name(name),
            "n": s["n"],
            "wins": s["wins"],
            "mean": s["mean"],
            "lo": s["lo"],
            "hi": s["hi"],
            "games": [{"seed": x["row"]["seed"], "gap": x["gap"], "winner": x["row"]["winner"]}
                      for x in res[name] if x["gap"] is not None],
        })
    if not rows:
        raise ValueError(f"no scored games for any group in {index_path}")
    rows.sort(key=lambda r: r["mean"])

    all_games = [x for name, _ in groups for x in res.get(name, [])]
    crews = {_crew_of(x["row"]) for x in all_games}
    efforts = {(x["row"].get("conditions") or {}).get("effort") for x in all_games}
    seed_sets = {tuple(g["seed"] for g in r["games"]) for r in rows}
    ns = sorted({r["n"] for r in rows})
    return {
        "rows": rows,
        "crew": list(next(iter(crews))) if len(crews) == 1 and None not in crews else None,
        "effort": next(iter(efforts)) if len(efforts) == 1 and None not in efforts else None,
        "seeds": list(next(iter(seed_sets))) if len(seed_sets) == 1 else None,
        "n_text": str(ns[0]) if len(ns) == 1 else f"{ns[0]}–{ns[-1]}",
    }


def _domain(rows) -> tuple[int, int]:
    vals = [0.0]
    for r in rows:
        vals += [g["gap"] for g in r["games"]]
        vals += [v for v in (r["lo"], r["hi"]) if not math.isnan(v)]
    lo = math.floor(min(vals) / 10) * 10
    hi = math.ceil(max(vals) / 10) * 10
    if hi == lo:
        hi = lo + 10
    return lo, hi


def _lanes(xs: list[float]) -> list[int]:
    """Vertical lane offset for each dot so that no two dots overlap (a minimal beeswarm)."""
    placed: list[tuple[float, int]] = []
    out = [0] * len(xs)
    for i in sorted(range(len(xs)), key=lambda i: xs[i]):
        for lane in LANES:
            if all(abs(xs[i] - px) >= 2 * DOT_R + 4 or pl != lane for px, pl in placed):
                break
        out[i] = lane
        placed.append((xs[i], lane))
    return out


def _text(x, y, s, size, *, weight=400, fill=INK, anchor="start", halo=False, extra=""):
    halo_attr = f' stroke="{SURFACE}" stroke-width="8" stroke-linejoin="round" paint-order="stroke"' if halo else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}"{halo_attr}{extra}>{escape(s)}</text>')


def footnote_lines(data: dict) -> list[str]:
    lines = ["Each dot is one game. Dark tick: mean of the games. Bar: bootstrap 95% interval over games."]
    crew = data["crew"]
    effort = f" Effort {data['effort']}." if data["effort"] else ""
    if crew:
        words = {3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}
        lines.append(f"Same {words.get(len(crew), str(len(crew)))}-model crew in every game: "
                     f"{', '.join(crew)}.{effort}")
    else:
        lines.append(f"Crew not the same in every game.{effort}")
    seeds = f"same seeds ({_seed_text(data['seeds'])})" if data["seeds"] else "seeds differ by model"
    lines.append(f"{data['n_text']} games per mole model, {seeds}. "
                 f"Read this as two groups, not a ranking. Not established at the first vote.")
    return lines


def render_svg(data: dict) -> str:
    rows = data["rows"]
    d0, d1 = _domain(rows)

    def X(v: float) -> float:
        return PLOT_X0 + (v - d0) / (d1 - d0) * (PLOT_X1 - PLOT_X0)

    plot_top = ROW_Y0 - 62
    axis_y = ROW_Y0 + ROW_PITCH * (len(rows) - 1) + 70
    title = "How suspicious did each model's moles look?"
    subtitle = "Points more suspicion the crew put on the moles than on each other (0–100 scale)"
    desc = " ".join(
        f"{r['name']}: mean {fmt(r['mean'])}, 95% interval {fmt(r['lo'])} to {fmt(r['hi'])}, "
        f"moles won {r['wins']} of {r['n']}." for r in rows)

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
         f'role="img" aria-labelledby="chart-title chart-desc" font-family=\'{FONT}\'>',
         f'<title id="chart-title">{escape(title)}</title>',
         f'<desc id="chart-desc">{escape(subtitle + ". Lower: the crew suspected the moles less. " + desc)}</desc>',
         f'<rect x="0" y="0" width="{W}" height="{H}" fill="{SURFACE}"/>',
         _text(LEFT, 98, title, 64, weight=700),
         _text(LEFT, 150, subtitle, 30, fill=INK_2)]

    # Grid, axis, ticks.
    o.append('<g class="grid">')
    for v in range(d0, d1 + 1, 10):
        if v != 0:
            o.append(f'<line x1="{X(v):.1f}" y1="{plot_top}" x2="{X(v):.1f}" y2="{axis_y}" stroke="{GRID}" stroke-width="1"/>')
    o.append(f'<line x1="{PLOT_X0}" y1="{axis_y}" x2="{PLOT_X1}" y2="{axis_y}" stroke="{AXIS}" stroke-width="1"/>')
    for v in range(d0, d1 + 1, 10):
        o.append(_text(X(v), axis_y + 38, fmt_tick(v), 26, fill=INK_2, anchor="middle",
                       extra=' font-variant-numeric="tabular-nums"'))
    o.append(_text(PLOT_X0, axis_y + 80, "← less suspected", 26, weight=600, fill=INK))
    o.append(_text(PLOT_X1, axis_y + 80, "more suspected →", 26, weight=600, fill=INK, anchor="end"))
    o.append('</g>')

    # Reference line at 0, labelled above the plot.
    o.append(f'<line class="zero" x1="{X(0):.1f}" y1="{plot_top - 18}" x2="{X(0):.1f}" y2="{axis_y}" '
             f'stroke="{INK_2}" stroke-width="2"/>')
    o.append(_text(X(0), plot_top - 30, "0 = crew suspected the moles no more than each other", 26,
                   fill=INK_2, anchor="middle", halo=True))

    for i, r in enumerate(rows):
        y = ROW_Y0 + i * ROW_PITCH
        o.append(f'<g class="row" data-model="{escape(r["name"])}">')
        o.append(_text(LEFT, y + 2, r["name"], 44, weight=700))
        o.append(_text(LEFT, y + 40, f"moles won {r['wins']} of {r['n']}", 26, fill=INK_2,
                       extra=' class="wins"'))
        if not (math.isnan(r["lo"]) or math.isnan(r["hi"])):
            x0, x1 = X(r["lo"]), X(r["hi"])
            o.append(f'<rect class="interval" x="{x0:.1f}" y="{y - 6}" width="{max(x1 - x0, 0):.1f}" height="12" '
                     f'rx="6" fill="{BAND}"><title>{escape(r["name"])}: bootstrap 95% interval '
                     f'{escape(fmt(r["lo"]))} to {escape(fmt(r["hi"]))}</title></rect>')
        xs = [X(g["gap"]) for g in r["games"]]
        for g, x, lane in zip(r["games"], xs, _lanes(xs)):
            won = "moles won" if g["winner"] == "moles" else "crew won"
            o.append(f'<circle class="game" cx="{x:.1f}" cy="{y + lane}" r="{DOT_R}" fill="{DOT}" '
                     f'stroke="{SURFACE}" stroke-width="2.5"><title>{escape(r["name"])}, seed {g["seed"]}: '
                     f'gap {escape(fmt(g["gap"]))}, {won}</title></circle>')
        xm = X(r["mean"])
        o.append(f'<rect class="mean" x="{xm - 4:.1f}" y="{y - 30}" width="8" height="60" rx="3" fill="{MEAN}" '
                 f'stroke="{SURFACE}" stroke-width="2"><title>{escape(r["name"])}: mean '
                 f'{escape(fmt(r["mean"]))}</title></rect>')
        o.append(_text(xm, y - 50, f"mean {fmt(r['mean'])}", 30, weight=700, anchor="middle", halo=True))
        o.append('</g>')

    fy = axis_y + 140
    for j, line in enumerate(footnote_lines(data)):
        o.append(_text(LEFT, fy + j * 34, line, 23, fill=INK_2))
    o.append('</svg>')
    return "\n".join(o) + "\n"


def render_html(svg: str, data: dict) -> str:
    rows = "\n".join(
        f"<tr><th scope=\"row\">{escape(r['name'])}</th><td>{escape(fmt(r['mean']))}</td>"
        f"<td>{escape(fmt(r['lo']))} to {escape(fmt(r['hi']))}</td>"
        f"<td>{escape(', '.join(str(g['seed']) + ': ' + fmt(g['gap']) for g in r['games']))}</td>"
        f"<td>{r['wins']} of {r['n']}</td></tr>" for r in data["rows"])
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
</style>
</head>
<body>
<main>
{svg}<div class="wrap">
<table>
<caption style="text-align:left;font-weight:600;padding-bottom:8px">Crew suspicion gap, points (lower = less suspected)</caption>
<thead><tr><th scope="col">Mole model</th><th scope="col">Mean</th><th scope="col">Bootstrap 95%</th><th scope="col">Per game (seed: gap)</th><th scope="col">Moles won</th></tr></thead>
<tbody>
{rows}
</tbody>
</table>
</div>
</main>
</body>
</html>
"""


def write_chart(out_dir, index_path=None, root=None, groups=bluff_score.GROUPS) -> tuple[Path, Path]:
    data = chart_data(index_path, root, groups)
    svg = render_svg(data)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    svg_path, html_path = out / "bluff_gap.svg", out / "bluff_gap.html"
    svg_path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + svg, encoding="utf-8")
    html_path.write_text(render_html(svg, data), encoding="utf-8")
    return svg_path, html_path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--index", default=None, help="index file (default: <root>/games/index.jsonl)")
    ap.add_argument("--root", default=None, help="directory game log paths are relative to (default: project root)")
    ap.add_argument("--out", default=str(ROOT / "docs" / "charts"), help="output directory")
    a = ap.parse_args(argv)
    for p in write_chart(a.out, a.index, a.root):
        print(p)


if __name__ == "__main__":
    main()
