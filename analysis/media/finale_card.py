"""Write docs/media/finale_card.svg and render it to a 1200 x 1500 PNG with rsvg-convert.

The finale of game g-20261111-234929-s107 (batch bluff_grok47, seed 107): both moles are Grok 4.7, the
moles won, and in the split-or-steal finale each said "split" out loud and chose steal; payouts 0 and 0.

Every quote is read from the game log at build time, picked by game id, player, turn phase, field and
a sentence selector (whole sentences only; separate runs of sentences are joined with an ellipsis, and
each run is an exact substring of the logged text). The facts on the card (models, roles, winner,
stated intents, choices, payouts, pot) are read from the same log and checked before anything is
written. No model calls, read only.

    env -u OPENROUTER_API_KEY python3.11 analysis/media/finale_card.py

analysis/media/finale_clip.py draws the clip's frames with `card_svg(ctx, step, fade)` from this file.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "media"
GAME = "g-20261111-234929-s107"
GAMES = ROOT / "games"
RSVG = shutil.which("rsvg-convert") or "/opt/homebrew/bin/rsvg-convert"
ELLIPSIS = " … "   # marks left-out sentences between two verbatim runs

# What the card quotes. `sentences` lists runs of whole sentences, 1-based, in log order; each run is
# shown verbatim and runs are joined by ELLIPSIS. Order here is the order on the card (and in the clip).
QUOTES = [
    {"key": "quill_said", "player": "Quill", "phase": "finale_pitch", "field": "public", "sentences": [[2, 3], [5]]},
    {"key": "quill_wrote", "player": "Quill", "phase": "finale_pitch", "field": "confessional", "sentences": [[3]]},
    {"key": "cipher_said", "player": "Cipher", "phase": "finale_pitch", "field": "public", "sentences": [[2, 3]]},
    {"key": "cipher_wrote", "player": "Cipher", "phase": "finale_pitch", "field": "confessional", "sentences": [[3]]},
]

COND = "Avenir Next Condensed, DIN Condensed, Arial Narrow, sans-serif"
BODY = "Avenir Next, Helvetica Neue, Arial, sans-serif"
MONO = "SF Mono, Menlo, monospace"
SERIF = "Georgia, Times New Roman, serif"
C = dict(bg="#061529", dim="#8db1d8", foot="#7f9fc6", cyan="#5fd8ff", amber="#ffb22e", paper="#f3ead6",
         ink="#2a2238", note="#080c18", noteline="#2a3346", mole="#ffb22e",
         Quill="#4f7dff", Cipher="#ff4fd8")   # the viewer's accent colours for the two players
W, H, M = 1200, 1500, 60


# ---- the log ----

def load(game: str = GAME, games_dir: Path = GAMES) -> list[dict]:
    with open(Path(games_dir) / f"{game}.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def sentences(text: str) -> list[str]:
    """Whole sentences, split after . ! or ? followed by white space (the text is not altered)."""
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def turn(events: list[dict], player: str, phase: str) -> dict:
    ts = [e for e in events if e.get("type") == "turn" and e.get("player") == player and e.get("turn_phase") == phase]
    if len(ts) != 1:
        raise ValueError(f"expected one {phase} turn for {player}, found {len(ts)}")
    return ts[0]


def pick(events: list[dict], spec: dict) -> dict:
    """The quote for one spec: its pieces (each an exact substring of the field), the text as shown,
    the full logged text and the turn's seq."""
    t = turn(events, spec["player"], spec["phase"])
    full = t[spec["field"]]
    sents = sentences(full)
    pieces = []
    for run in spec["sentences"]:
        piece = " ".join(sents[i - 1] for i in run)
        if piece not in full:
            raise ValueError(f"{spec['key']}: run {run} is not verbatim in the log")
        pieces.append(piece)
    return {"key": spec["key"], "player": spec["player"], "phase": spec["phase"], "field": spec["field"],
            "seq": t["seq"], "full": full, "pieces": pieces, "text": ELLIPSIS.join(pieces)}


def display_model(name: str) -> str:
    """'Grok 4.7 A' -> 'Grok 4.7' (anonymised games add a seat letter to the model name)."""
    return re.sub(r" [A-Z]$", "", name)


def check(game: str = GAME, games_dir: Path = GAMES) -> dict:
    """Read and check everything the card states. Raises if the log does not say it."""
    ev = load(game, games_dir)
    start = next(e for e in ev if e["type"] == "game_start")
    end = next(e for e in ev if e["type"] == "game_end")
    fr = next(e for e in ev if e["type"] == "finale_result")
    players = {p["name"]: p for p in start["players"]}
    roles = {e["player"]: e["role"] for e in ev if e["type"] == "role"}
    a, b = fr["finalists"]
    assert end["winner"] == "moles", end["winner"]
    assert roles[a] == roles[b] == "mole" and sorted(start["moles"]) == sorted([a, b])
    assert players[a]["model"] == players[b]["model"], "the two moles are not the same model"
    models = {p: display_model(players[p]["model_name"]) for p in (a, b)}
    assert models[a] == models[b]
    pot = start["config"]["game"]["pot"]
    quotes = [pick(ev, q) for q in QUOTES]
    for q in quotes:
        assert q["player"] in (a, b)
    choices = {p: turn(ev, p, "finale_choice")["action"]["choice"] for p in (a, b)}
    assert choices == fr["choices"], (choices, fr["choices"])
    stated = {p: turn(ev, p, "finale_pitch")["action"]["stated_intent"] for p in (a, b)}
    assert stated == fr["stated"], (stated, fr["stated"])
    # This card tells one story; refuse to draw it over a log that says anything else.
    assert all(v == "split" for v in stated.values()), stated
    assert all(v == "steal" for v in choices.values()), choices
    assert all(v == 0 for v in fr["payouts"].values()), fr["payouts"]
    return {"game": game, "seed": start["seed"], "batch": start["batch"], "finalists": [a, b], "model": models[a],
            "model_id": players[a]["model"], "pot": pot, "choices": choices, "stated": stated,
            "payouts": fr["payouts"], "result_seq": fr["seq"],
            "choice_seq": {p: turn(ev, p, "finale_choice")["seq"] for p in (a, b)},
            "quotes": quotes}


# ---- text measuring (the system fonts when Pillow is present, else an estimate) ----

_FONTS = {"body600": ("/System/Library/Fonts/Avenir Next.ttc", 2),
          "serif_it": ("/System/Library/Fonts/Supplemental/Georgia Italic.ttf", 0),
          "cond800": ("/System/Library/Fonts/Avenir Next Condensed.ttc", 8)}
_FACTOR = {"body600": 0.56, "serif_it": 0.52, "cond800": 0.47}
_cache: dict = {}


def text_width(s: str, face: str, size: float) -> float:
    key = (face, size)
    if key not in _cache:
        try:
            from PIL import ImageFont
            path, idx = _FONTS[face]
            _cache[key] = ImageFont.truetype(path, int(size), index=idx)
        except Exception:
            _cache[key] = None
    f = _cache[key]
    if f is None:
        return len(s) * size * _FACTOR[face]
    return f.getlength(s) * size / int(size)


def wrap(s: str, face: str, size: float, max_w: float) -> list[str]:
    lines, cur = [], ""
    for word in s.split(" "):
        nxt = f"{cur} {word}" if cur else word
        if cur and text_width(nxt, face, size) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = nxt
    return lines + ([cur] if cur else [])


# ---- drawing ----

def defs() -> str:
    return f"""<defs>
  <radialGradient id="bg" cx="50%" cy="0%" r="110%"><stop offset="0" stop-color="#11335f"/><stop offset=".45" stop-color="{C['bg']}"/><stop offset="1" stop-color="#02070f"/></radialGradient>
  <pattern id="grid" width="60" height="60" patternUnits="userSpaceOnUse"><path d="M60 0H0V60" fill="none" stroke="#1a3d68" stroke-width="1" opacity=".35"/></pattern>
  <filter id="sh" x="-10%" y="-10%" width="120%" height="140%"><feDropShadow dx="0" dy="14" stdDeviation="16" flood-color="#000" flood-opacity=".55"/></filter>
  <radialGradient id="spot" cx="50%" cy="0%" r="70%"><stop offset="0" stop-color="#5fd8ff" stop-opacity=".16"/><stop offset="1" stop-color="#5fd8ff" stop-opacity="0"/></radialGradient>
</defs>"""


def logo(x: int, y: int, size: int = 40) -> str:
    return (f'<text x="{x}" y="{y}" font-family="{COND}" font-weight="800" font-size="{size}" letter-spacing="{size * .26:.0f}">'
            f'<tspan fill="#fff">INSIDE</tspan><tspan fill="{C["amber"]}" dx="{size * .45:.0f}">JOB</tspan></text>')


# Quote styles: (face, svg attributes, size, line height, colour)
SAID = ("body600", f'font-family="{BODY}" font-weight="600"', 40, 52, C["ink"])
WROTE = ("serif_it", f'font-family="{SERIF}" font-style="italic"', 39, 51, C["paper"])
GUTTER = 30
COL_W = (W - 2 * M - GUTTER) / 2   # each cell
PAD = 26
STRIP = 14                         # the coloured strip on top of a private note
TEXT_W = COL_W - 2 * PAD - 6       # a few px of slack under the measured width
X_L, X_R = M, M + COL_W + GUTTER
TAIL = 26                          # speech-bubble tail, pointing up at the speaker's name
RESULT_H = 200
STEPS = ["intro", "quill_said", "quill_wrote", "cipher_said", "cipher_wrote", "result"]


def quote_lines(q: dict, style) -> list[str]:
    face, _attr, size, _lh, _fill = style
    # A no-break space keeps the ellipsis at the end of the run before it, never at a line start.
    text = q["text"].replace(ELLIPSIS, "\u00a0… ")
    greedy = wrap(text, face, size, TEXT_W)
    # Prefer a new line at each sentence end when that costs at most one extra line.
    runs = [r for r in re.split(r"(?<=[.!?…]) +", text) if r]   # sentence ends and the ellipsis (plain spaces only)
    by_sentence = [ln for run in runs for ln in wrap(run, face, size, TEXT_W)]
    lines = by_sentence if len(by_sentence) <= len(greedy) + 1 else greedy
    return [ln.replace("\u00a0", " ") for ln in lines]


def _text_h(n_lines: int, style) -> float:
    _f, _a, size, lh, _c = style
    return size * 0.74 + (n_lines - 1) * lh + size * 0.26


def _quote_text(q: dict, style, x: float, y_top: float) -> str:
    face, attr, size, lh, fill = style
    tsp = "".join(f'<tspan x="{x + PAD:.0f}" y="{y_top + size * 0.74 + i * lh:.0f}">{escape(line)}</tspan>'
                  for i, line in enumerate(quote_lines(q, style)))
    return f'<text class="quote" data-key="{q["key"]}" {attr} font-size="{size}" fill="{fill}" xml:space="preserve">{tsp}</text>'


def _said_cell(q, x, y, h, fade) -> str:
    return f"""<g class="cell said" opacity="{fade:.3f}">
  <g filter="url(#sh)"><rect x="{x:.0f}" y="{y:.0f}" width="{COL_W:.0f}" height="{h:.0f}" rx="24" fill="{C['paper']}" stroke="#0a0612" stroke-width="5"/>
  <path d="M{x + 40:.0f} {y + 3:.0f} L{x + 52:.0f} {y - TAIL:.0f} L{x + 84:.0f} {y + 3:.0f} Z" fill="{C['paper']}" stroke="#0a0612" stroke-width="5" stroke-linejoin="round"/>
  <rect x="{x + 36:.0f}" y="{y + 3:.0f}" width="52" height="10" fill="{C['paper']}"/></g>
  {_quote_text(q, SAID, x, y + PAD)}
</g>"""


def _wrote_cell(q, x, y, h, fade, accent) -> str:
    return f"""<g class="cell wrote" opacity="{fade:.3f}">
  <g filter="url(#sh)"><rect x="{x:.0f}" y="{y:.0f}" width="{COL_W:.0f}" height="{h:.0f}" rx="18" fill="{C['note']}" stroke="{C['noteline']}" stroke-width="3"/></g>
  <path d="M{x + 18:.0f} {y:.0f} H{x + COL_W - 18:.0f} A18 18 0 0 1 {x + COL_W:.0f} {y + 18:.0f} V{y + STRIP + 4:.0f} H{x:.0f} V{y + 18:.0f} A18 18 0 0 1 {x + 18:.0f} {y:.0f} Z" fill="{accent}"/>
  {_quote_text(q, WROTE, x, y + STRIP + PAD)}
</g>"""


def _placeholder(x, y, h) -> str:
    return (f'<rect class="placeholder" x="{x:.0f}" y="{y:.0f}" width="{COL_W:.0f}" height="{h:.0f}" rx="20" '
            f'fill="none" stroke="#2c4f7c" stroke-width="3" stroke-dasharray="10 10" opacity=".7"/>')


def layout(ctx: dict) -> dict:
    """Vertical positions, shared by the card and every clip frame so nothing moves between steps.
    Rows and the result box share the space between the column heads and the footer evenly."""
    q = {x["key"]: x for x in ctx["quotes"]}
    rows = []
    for p in ctx["finalists"]:
        k = p.lower()
        said, wrote = q[f"{k}_said"], q[f"{k}_wrote"]
        h = max(2 * PAD + _text_h(len(quote_lines(said, SAID)), SAID),
                STRIP + 2 * PAD + _text_h(len(quote_lines(wrote, WROTE)), WROTE))
        rows.append((p, h))
    top, bottom = 372, H - 96                  # under the column heads; above the footer
    label_h = 44 + TAIL + 10                  # name line, then the bubble tail
    used = sum(label_h + h for _p, h in rows) + RESULT_H
    gap = (bottom - top - used) / (len(rows) + 1)
    if gap < 20:
        raise ValueError(f"card does not fit: {gap:.0f} px between blocks")
    pos, y = {}, top + gap
    for p, h in rows:
        pos[p] = {"label_y": y + 34, "cell_y": y + label_h, "h": h}
        y += label_h + h + gap
    pos["result_y"] = y
    pos["gap"] = gap
    return pos


def card_svg(ctx: dict, step: int = len(STEPS) - 1, fade: float = 1.0) -> str:
    """The card with everything up to STEPS[step] shown; the element of `step` drawn at opacity `fade`."""
    def op(i):
        return 0.0 if i > step else (fade if i == step else 1.0)

    a, b = ctx["finalists"]
    q = {x["key"]: x for x in ctx["quotes"]}
    pos = layout(ctx)
    pot, model = ctx["pot"], ctx["model"]
    pay = payoffs(pot)
    parts = [f"""{logo(M, 104)}
<text x="{W - M}" y="102" text-anchor="end" font-family="{MONO}" font-size="30" letter-spacing="4" fill="{C['cyan']}">SEED {ctx['seed']} · FINALE</text>
<text x="{M}" y="194" font-family="{COND}" font-weight="800" font-size="64" fill="#fff">Two {escape(model)} moles won the game.</text>
<text x="{M}" y="250" font-family="{BODY}" font-weight="600" font-size="36" fill="{C['dim']}">Then each chose in secret: split or steal {pot} points.</text>
<text x="{M}" y="296" font-family="{BODY}" font-weight="600" font-size="31" fill="{C['dim']}">Both split: {pay['split']} each. One steals: all {pay['steal']}. Both steal: {pay['both']}.</text>
<text x="{X_L}" y="370" font-family="{MONO}" font-size="30" letter-spacing="3" fill="{C['cyan']}">SAID OUT LOUD</text>
<text x="{X_R:.0f}" y="370" font-family="{MONO}" font-size="30" letter-spacing="3" fill="{C['cyan']}">WROTE IN PRIVATE</text>"""]
    for p in (a, b):
        k = p.lower()
        pp = pos[p]
        y, h = pp["cell_y"], pp["h"]
        i_said, i_wrote = STEPS.index(f"{k}_said"), STEPS.index(f"{k}_wrote")
        name_w = text_width(p.upper(), "cond800", 46) + 2 * len(p)
        parts.append(f"""<g class="speaker" data-player="{p}">
<text x="{M}" y="{pp['label_y']:.0f}" font-family="{COND}" font-weight="800" font-size="46" letter-spacing="2" fill="{C[p]}">{p.upper()}</text>
<text x="{M + name_w + 20:.0f}" y="{pp['label_y'] - 2:.0f}" font-family="{MONO}" font-size="30" fill="#e6eefa">{escape(model)} <tspan fill="{C['mole']}" font-weight="700" letter-spacing="2">· MOLE</tspan></text>
</g>""")
        parts.append(_said_cell(q[f"{k}_said"], X_L, y, h, op(i_said)) if op(i_said) else _placeholder(X_L, y, h))
        parts.append(_wrote_cell(q[f"{k}_wrote"], X_R, y, h, op(i_wrote), C[p]) if op(i_wrote)
                     else _placeholder(X_R, y, h))

    ry = pos["result_y"]
    o = op(STEPS.index("result"))
    paid = " and ".join(str(ctx["payouts"][p]) for p in (a, b))
    if o:
        parts.append(f"""<g class="result" opacity="{o:.3f}">
<rect x="{M}" y="{ry:.0f}" width="{W - 2 * M}" height="{RESULT_H}" rx="18" fill="#241503" stroke="{C['amber']}" stroke-width="4"/>
<text x="{M + 40}" y="{ry + 84:.0f}" font-family="{COND}" font-weight="800" font-size="70" fill="{C['amber']}">Both stole. Both got nothing.</text>
<text x="{M + 40}" y="{ry + 140:.0f}" font-family="{BODY}" font-weight="600" font-size="36" fill="#fff">{a} and {b} each chose steal.</text>
<text x="{M + 40}" y="{ry + 178:.0f}" font-family="{BODY}" font-weight="500" font-size="31" fill="#ffe2b0">Payout: {paid} of the {pot}-point pot.</text>
</g>""")
    parts.append(f'<text x="{M}" y="{H - 40}" font-family="{BODY}" font-weight="500" font-size="30" fill="{C["foot"]}">'
                 f'Inside Job · game seed {ctx["seed"]} · quotes verbatim from the game log</text>')
    inner = "\n".join(parts)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
{defs()}
<rect width="{W}" height="{H}" fill="url(#bg)"/>
<rect width="{W}" height="{H}" fill="url(#grid)"/>
<rect width="{W}" height="700" fill="url(#spot)"/>
{inner}
</svg>
"""


def payoffs(pot: int) -> dict:
    """The finale's payoffs, from the engine's own function."""
    import sys
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from inside_job.engine import payoffs as pay
    return {"split": pay("split", "split", pot)[0], "steal": pay("steal", "split", pot)[0],
            "both": pay("steal", "steal", pot)[0]}


def render(svg: str, svg_path: Path, png_path: Path, width: int = W, height: int = H) -> None:
    svg_path.write_text(svg, encoding="utf-8")
    subprocess.run([RSVG, "-w", str(width), "-h", str(height), "-o", str(png_path), str(svg_path)], check=True)


def main() -> None:
    ctx = check()
    OUT.mkdir(parents=True, exist_ok=True)
    render(card_svg(ctx), OUT / "finale_card.svg", OUT / "finale_card.png")
    print("wrote", OUT / "finale_card.svg", OUT / "finale_card.png")
    for q in ctx["quotes"]:
        print(f"  {q['key']:<13} seq {q['seq']} {q['phase']}.{q['field']}: {q['text']}")


if __name__ == "__main__":
    main()
