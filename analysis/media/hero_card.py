"""Write docs/media/hero.svg, hero.png (1600 x 900, 16:9) and hero_alt.txt: the image that opens the thread.

An illustration of the premise, not a game: seven of the viewer's drawn characters at the viewer's
table, two of them marked as moles (amber glow, a mask, a MOLE chip), five as crew. No model names sit
on the seats and nothing on the image comes from one game.

Every number on the image is read from the logs at build time:
  - players and moles per game: the counted games' game_start config (cards.check_rules);
  - games and model calls: every real game in games/index.jsonl and games_frontier/index.jsonl, read
    and totalled the way analysis/extra_stats.py does (its index_rows; calls = tokens.calls);
  - the models that played the moles: extra_stats.GROUPS, in that order, each with at least one game.

The characters are drawn by the viewer's own code: the character section of inside_job/viewer/index.html
(from `const OL` up to the markup cache) is run once in node and its charSVG() markup is embedded as is.
No model calls, read only.

    env -u OPENROUTER_API_KEY python3.11 analysis/media/hero_card.py
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "media"
VIEWER = ROOT / "inside_job" / "viewer" / "index.html"
RSVG = shutil.which("rsvg-convert") or "/opt/homebrew/bin/rsvg-convert"
NODE = shutil.which("node") or "/opt/homebrew/bin/node"
for p in (ROOT / "analysis", ROOT / "analysis" / "media"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import cards  # noqa: E402  (check_rules: the counted games' settings)
import extra_stats  # noqa: E402  (index_rows, GROUPS: how games and calls are totalled)

COND = "Avenir Next Condensed, DIN Condensed, Arial Narrow, sans-serif"
BODY = "Avenir Next, Helvetica Neue, Arial, sans-serif"
MONO = "SF Mono, Menlo, monospace"
C = dict(bg="#061529", line="#dcefff", dim="#8db1d8", faint="#4f77a3", cyan="#5fd8ff", amber="#ffb22e",
         amber_deep="#e07a00", mint="#43e4ad", ink="#17122b")
W, H, M = 1600, 900, 64

# The illustration's seats, left to right: codename, expression, mole or not. Codenames are the
# viewer's cast; moles wear the smug face, crew look round the table.
SEATS = [("Marlow", "suspicious", False), ("Sable", "thinking", False), ("Fox", "smug", True),
         ("Duke", "suspicious", False), ("Lark", "nervous", False), ("Viper", "smug", True),
         ("Ghost", "suspicious", False)]


# ---- the logs ----

def facts(root: Path = ROOT) -> dict:
    """Every number on the image, from the logs."""
    rules = cards.check_rules()
    rows = (extra_stats.index_rows(root / "games" / "index.jsonl")
            + extra_stats.index_rows(root / "games_frontier" / "index.jsonl"))
    calls = sum((r.get("tokens") or {}).get("calls", 0) or 0 for r in rows)
    batches = {r.get("batch") for r in rows}
    models = [name for name, bs in extra_stats.GROUPS if batches & set(bs)]
    assert models == [name for name, _ in extra_stats.GROUPS], "a GROUPS model has no game"
    return {"players": rules["players"], "moles": rules["moles"], "games": len(rows), "calls": calls,
            "calls_floor": calls // 1000 * 1000, "models": models}


# ---- the viewer's characters ----

def viewer_js() -> str:
    src = VIEWER.read_text(encoding="utf-8")
    a, b = src.index("const OL = '#17122b';"), src.index("// Markup is built once per")
    return src[a:b]


def characters() -> list[dict]:
    """charSVG(name, expr) for each seat, plus the face geometry and pose the mask needs."""
    seats = [[n, e] for n, e, _m in SEATS]
    prog = viewer_js() + f"""
const SEATS = {json.dumps(seats)};
process.stdout.write(JSON.stringify(SEATS.map(([n, e]) => {{
  const R = castOf(n), G = geom(R), E = EXPR[e];
  return {{ name: n, svg: charSVG(n, e), eyeY: G.eyeY, sep: G.sep, accent: R.accent,
           tilt: E.tilt || 0, dy: E.dy || 0, lean: E.gest === 'point' ? 3 : 0 }};
}})));
"""
    out = subprocess.run([NODE, "-"], input=prog, capture_output=True, text=True, check=True)
    chars = json.loads(out.stdout)
    for i, ch in enumerate(chars):
        ch["svg"] = dedupe_attrs(ch["svg"].replace("@@", f"s{i}_"))
    return chars


_TAG = re.compile(r"<([a-zA-Z]+)((?:\s+[a-zA-Z:-]+=\"[^\"]*\")*)\s*(/?)>")
_ATTR = re.compile(r"\s+([a-zA-Z:-]+)=\"([^\"]*)\"")


def dedupe_attrs(markup: str) -> str:
    """The viewer's markup goes into the page through innerHTML, where a repeated attribute is ignored
    (the first one wins). XML refuses it, so keep the first of each, exactly as the browser draws it."""
    def fix(m):
        seen, attrs = set(), []
        for name, val in _ATTR.findall(m.group(2)):
            if name not in seen:
                seen.add(name)
                attrs.append(f' {name}="{val}"')
        return f"<{m.group(1)}{''.join(attrs)}{m.group(3)}>"
    return _TAG.sub(fix, markup)


# ---- drawing ----

def defs() -> str:
    return f"""<defs>
  <radialGradient id="rbg" cx="50%" cy="40%" r="85%"><stop offset="0" stop-color="#173f70"/><stop offset=".55" stop-color="#0b2346"/><stop offset="1" stop-color="#040c1a"/></radialGradient>
  <pattern id="grid" width="48" height="48" patternUnits="userSpaceOnUse"><path d="M48 0H0V48" fill="none" stroke="#78beff" stroke-opacity=".08" stroke-width="1"/></pattern>
  <radialGradient id="spot" cx="50%" cy="0%" r="70%"><stop offset="0" stop-color="#5fd8ff" stop-opacity=".16"/><stop offset="1" stop-color="#5fd8ff" stop-opacity="0"/></radialGradient>
  <linearGradient id="cone" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffe8b8" stop-opacity=".0"/><stop offset=".5" stop-color="#ffe8b8" stop-opacity=".10"/><stop offset="1" stop-color="#ffe8b8" stop-opacity="0"/></linearGradient>
  <radialGradient id="tw" cx="50%" cy="40%" r="70%"><stop offset="0" stop-color="#4a3326"/><stop offset="1" stop-color="#22160f"/></radialGradient>
  <radialGradient id="tpool" cx="50%" cy="45%" r="50%"><stop offset="0" stop-color="#ffe7b0" stop-opacity=".26"/><stop offset="1" stop-color="#ffe7b0" stop-opacity="0"/></radialGradient>
  <radialGradient id="moleglow" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="{C['amber']}" stop-opacity=".95"/><stop offset=".5" stop-color="{C['amber_deep']}" stop-opacity=".42"/><stop offset="1" stop-color="{C['amber_deep']}" stop-opacity="0"/></radialGradient>
  <linearGradient id="plate" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#162a49"/><stop offset="1" stop-color="#0b1a31"/></linearGradient>
  <linearGradient id="foot" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#030810" stop-opacity="0"/><stop offset=".42" stop-color="#030810" stop-opacity=".94"/><stop offset="1" stop-color="#02060c" stop-opacity="1"/></linearGradient>
  <radialGradient id="vig" cx="50%" cy="46%" r="75%"><stop offset=".6" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".6"/></radialGradient>
  <filter id="sh" x="-20%" y="-20%" width="140%" height="160%"><feDropShadow dx="0" dy="10" stdDeviation="10" flood-color="#000" flood-opacity=".6"/></filter>
</defs>
<style>.m{{display:none}} .m-rest{{display:inline}} .eyes-c{{display:none}}</style>"""


def logo(x: float, y: float, size: int) -> str:
    """The cards' INSIDE JOB wordmark (white INSIDE, amber JOB), centred on x, in the heavy face for the title."""
    return (f'<text x="{x:.0f}" y="{y:.0f}" text-anchor="middle" font-family="{BODY}" font-weight="900" font-size="{size}" '
            f'letter-spacing="{size * .03:.0f}" filter="url(#sh)"><tspan fill="#fff">INSIDE</tspan><tspan fill="{C["amber"]}" dx="{size * .2:.0f}">JOB</tspan></text>')


def mask(ch: dict) -> str:
    """A domino mask over the eyes, in the character's own head frame (same pose as charSVG's head)."""
    cx, y, s = 100, ch["eyeY"], ch["sep"]
    L, R = cx - s - 19, cx + s + 19
    outer = (f"M{L} {y - 5}Q{L + 3} {y - 17} {cx - s} {y - 15}Q{cx} {y - 13} {cx + s} {y - 15}"
             f"Q{R - 3} {y - 17} {R} {y - 5}Q{R - 4} {y + 13} {cx + s} {y + 12}Q{cx + 7} {y + 11} {cx} {y + 4}"
             f"Q{cx - 7} {y + 11} {cx - s} {y + 12}Q{L + 4} {y + 13} {L} {y - 5}Z")
    holes = "".join(f"M{cx + d * s - 10.5} {y}a10.5 6.8 0 1 0 21 0a10.5 6.8 0 1 0 -21 0Z" for d in (-1, 1))
    tf = f'translate({ch["lean"]} {ch["dy"]}) rotate({ch["tilt"]} 100 170)'
    return (f'<g transform="{tf}"><path d="{outer}{holes}" fill="#0b0710" fill-rule="evenodd" stroke="{C["amber"]}" '
            f'stroke-width="2.6" stroke-linejoin="round"/>'
            f'<path d="M{L + 6} {y - 8}Q{cx - s} {y - 12} {cx - 8} {y - 9}" fill="none" stroke="#fff" stroke-opacity=".28" stroke-width="2.2" stroke-linecap="round"/></g>')


# Table geometry (the viewer's table shot, scaled to 1600 wide)
TCX, TY, TRX, TRY = W / 2, 762, 900, 215
SEAT_RX = 640


def edge_y(x: float) -> float:
    return TY - TRY * max(0.0, 1 - ((x - TCX) / TRX) ** 2) ** 0.5


def seat_boxes() -> list[dict]:
    n = len(SEATS)
    out = []
    for i in range(n):
        u = -0.93 + 1.86 * i / (n - 1)
        depth = (1 - u * u) ** 0.5
        x = TCX + SEAT_RX * u
        pw = 290 * (1 - 0.17 * depth)
        bottom = edge_y(x) + 18
        out.append({"x": x, "pw": pw, "h": pw * 1.1, "top": bottom - pw * 1.1, "bottom": bottom, "depth": depth,
                    "flip": u < -0.05})
    return out


def seat_svg(ch: dict, box: dict, mole: bool) -> str:
    k = box["pw"] / 200
    x0, y0 = box["x"] - box["pw"] / 2, box["top"]
    body = ch["svg"] + (mask(ch) if mole else "")
    if box["flip"]:
        body = f'<g transform="translate(200 0) scale(-1 1)">{body}</g>'
    glow = ""
    if mole:
        r = box["pw"] * 0.78
        glow = (f'<ellipse cx="{box["x"]:.1f}" cy="{y0 + box["h"] * .44:.1f}" rx="{r:.1f}" ry="{r * 1.02:.1f}" fill="url(#moleglow)"/>')
    return (f'{glow}<g class="seat" data-name="{ch["name"]}" data-role="{"mole" if mole else "crew"}" '
            f'transform="translate({x0:.1f} {y0:.1f}) scale({k:.4f})">{body}</g>')


def plate_svg(name: str, accent: str, box: dict, mole: bool) -> str:
    pw, ph = 182, 102
    x, y = box["x"] - pw / 2, box["bottom"] - 34
    chip_w = 104
    chip = C["amber"] if mole else C["mint"]
    chip_ink = "#2a1600" if mole else "#022a1d"
    label = "MOLE" if mole else "CREW"
    return f"""<g class="plate" filter="url(#sh)">
  <rect x="{x:.1f}" y="{y:.1f}" width="{pw}" height="{ph}" rx="7" fill="url(#plate)" stroke="#04070e" stroke-width="3"/>
  <rect x="{x:.1f}" y="{y:.1f}" width="{pw}" height="6" rx="3" fill="{accent}"/>
</g>
<text x="{box['x']:.1f}" y="{y + 44:.1f}" text-anchor="middle" font-family="{COND}" font-weight="800" font-size="36" letter-spacing="2" fill="{accent}">{escape(name.upper())}</text>
<rect x="{box['x'] - chip_w / 2:.1f}" y="{y + 56:.1f}" width="{chip_w}" height="36" rx="5" fill="{chip}"/>
<text x="{box['x']:.1f}" y="{y + 84:.1f}" text-anchor="middle" font-family="{MONO}" font-weight="800" font-size="28" letter-spacing="2" fill="{chip_ink}">{label}</text>"""


def hero_svg(f: dict, chars: list[dict]) -> str:
    boxes = seat_boxes()
    moles_drawn = sum(1 for _n, _e, m in SEATS if m)
    assert len(SEATS) == f["players"] and moles_drawn == f["moles"], (len(SEATS), moles_drawn, f)
    parts = []
    # back to front: the far (middle) seats first, so nearer shoulders overlap them as in the viewer
    order = sorted(range(len(SEATS)), key=lambda i: -boxes[i]["depth"])
    for i in order:
        parts.append(seat_svg(chars[i], boxes[i], SEATS[i][2]))
    seats = "\n".join(parts)
    plates = "\n".join(plate_svg(SEATS[i][0], chars[i]["accent"], boxes[i], SEATS[i][2]) for i in range(len(SEATS)))
    calls = f"{f['calls_floor']:,}+"
    names = f'<tspan fill="{C["faint"]}"> · </tspan>'.join(f'<tspan>{escape(n)}</tspan>' for n in f["models"])
    sub = (f'<tspan>{f["players"]} AI players. </tspan><tspan fill="{C["amber"]}">{f["moles"]} secret moles.</tspan>'
           f'<tspan> Every private note logged.</tspan>')
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
{defs()}
<rect width="{W}" height="{H}" fill="url(#rbg)"/>
<rect width="{W}" height="{TY - TRY + 40}" fill="url(#grid)"/>
<rect width="{W}" height="520" fill="url(#spot)"/>
<polygon points="{W / 2 - 90},250 {W / 2 + 90},250 {W / 2 + 820},{H} {W / 2 - 820},{H}" fill="url(#cone)"/>
{logo(W / 2, 172, 150)}
<text x="{W / 2}" y="252" text-anchor="middle" font-family="{BODY}" font-weight="700" font-size="46" fill="{C['line']}" xml:space="preserve">{sub}</text>
{seats}
<ellipse cx="{TCX}" cy="{TY + 30}" rx="{TRX}" ry="{TRY}" fill="#120b07" stroke="#05030a" stroke-width="5"/>
<ellipse cx="{TCX}" cy="{TY}" rx="{TRX}" ry="{TRY}" fill="url(#tw)" stroke="#05030a" stroke-width="5"/>
<ellipse cx="{TCX}" cy="{TY - 30}" rx="{TRX * .8}" ry="{TRY * .9}" fill="url(#tpool)"/>
<path d="M{TCX - TRX} {TY}A{TRX} {TRY} 0 0 1 {TCX + TRX} {TY}" fill="none" stroke="#ffe7b0" stroke-opacity=".2" stroke-width="3"/>
{plates}
<rect y="{H - 250}" width="{W}" height="250" fill="url(#foot)"/>
<rect width="{W}" height="{H}" fill="url(#vig)"/>
<text x="{W / 2}" y="{H - 124}" text-anchor="middle" font-family="{COND}" font-weight="900" font-size="52" letter-spacing="2" fill="#fff" xml:space="preserve"><tspan>{f['games']} GAMES</tspan><tspan fill="{C['faint']}">  ·  </tspan><tspan>{calls} MODEL CALLS</tspan></text>
<text x="{W / 2}" y="{H - 78}" text-anchor="middle" font-family="{MONO}" font-weight="700" font-size="28" letter-spacing="5" fill="{C['amber']}">BENCHMARKED AS MOLES</text>
<text x="{W / 2}" y="{H - 30}" text-anchor="middle" font-family="{COND}" font-weight="600" font-size="34" letter-spacing=".5" fill="{C['line']}" xml:space="preserve">{names}</text>
</svg>
"""


def alt_text(f: dict) -> str:
    return (f"Inside Job: {f['players']} AI players. {f['moles']} secret moles. Every private note logged. "
            f"An illustration of the premise, not a real game: {f['players']} drawn characters with heist codenames "
            f"sit at a wooden table. {f['moles']} of them wear masks and glow amber, with MOLE on their name plates; "
            f"the other {f['players'] - f['moles']} are marked CREW. Footer: {f['games']} games, "
            f"{f['calls_floor']:,}+ model calls. Benchmarked as moles: {', '.join(f['models'])}.")


def build(out_dir: Path = OUT, png: bool = True) -> dict:
    f = facts()
    svg = hero_svg(f, characters())
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "hero.svg").write_text(svg, encoding="utf-8")
    alt = alt_text(f)
    assert len(alt) < 1000, len(alt)
    (out_dir / "hero_alt.txt").write_text(alt + "\n", encoding="utf-8")
    if png:
        subprocess.run([RSVG, "-w", str(W), "-h", str(H), "-o", str(out_dir / "hero.png"), str(out_dir / "hero.svg")],
                       check=True)
    return f


def main() -> None:
    f = build()
    print("wrote", OUT / "hero.svg", OUT / "hero.png", OUT / "hero_alt.txt")
    print(f"  games {f['games']}, calls {f['calls']} (shown {f['calls_floor']:,}+), "
          f"players {f['players']}, moles {f['moles']}; moles played by {', '.join(f['models'])}")


if __name__ == "__main__":
    main()
