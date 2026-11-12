"""Render the still images in docs/media from the replay viewer (no model calls).

    table_mixed_labs.png  games_frontier g-20261110-221335-s201 (batch frontier1, seed 201), the round 1 opening
    forge_moment.png      games g-20261111-125222-s109 (batch bluff_fable52, seed 109), seq 48: public line,
                          private note and the engine's verdict on one image
    vote_reveal.png       the same game, seq 65: the round 1 vote result and role reveal (Quill out, crew)

How: headless Chrome drives the unchanged viewer through `window.insideJob` (goto a beat, scene held on
its last frame with `scene_t=end`) and screenshots page regions at 2x. A small HTML page (written to the
scratch folder) then lays the crops out with plain factual captions, and Chrome renders it to PNG at
1600 px wide. Every word a model wrote is in a viewer crop; the captions are labels, not quotes.

    env -u OPENROUTER_API_KEY python3.11 -m inside_job view --out games --port 8771 --no-open
    env -u OPENROUTER_API_KEY python3.11 -m inside_job view --out games_frontier --port 8772 --no-open
    env -u OPENROUTER_API_KEY python3.11 analysis/media/stills.py --games-port 8771 --frontier-port 8772 --work <scratch>/stills
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cdp import Chrome  # noqa: E402
from forge_clip import GAME, INJECT, PRIVATE_QUOTE, PUBLIC_QUOTE, check_log  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FRONTIER = "g-20261110-221335-s201"
READY = "window.insideJob && insideJob.state.beats.length > 20 && insideJob.state.tl"
LABS = {"google/": "Google", "openai/": "OpenAI", "claude-": "Anthropic", "moonshotai/": "Moonshot AI",
        "x-ai/": "xAI", "deepseek/": "DeepSeek"}
# Display names for the legend (the plates in the viewer crop show the log's own model_name strings).
PRETTY = {"Gpt 6 Astra": "GPT-6 Astra", "Deepseek V4 Pro 0813": "DeepSeek V4 Pro"}

RECT_JS = """(sel => { const el = document.querySelector(sel); if (!el) return null; const r = el.getBoundingClientRect();
  return {x: r.left, y: r.top, width: r.width, height: r.height}; })(%s)"""

PAGE_CSS = """
:root { --cyan:#5fd8ff; --amber:#ffb22e; --mint:#43e4ad; --dim:#8db1d8; --line:#dcefff;
  --display:"Avenir Next Condensed","DIN Condensed","Arial Narrow","Helvetica Neue",sans-serif;
  --stamp:Impact,"Haettenschweiler","Arial Black","Avenir Next Condensed",sans-serif;
  --body:"Avenir Next","Helvetica Neue","Segoe UI",Roboto,Arial,sans-serif;
  --mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Monaco,Consolas,monospace; }
html,body { margin:0; background:#04101f; color:var(--line); font-family:var(--body); }
.page { width:1600px; box-sizing:border-box; background:radial-gradient(ellipse at 50% 0%, #0d2a50 0%, #061529 45%, #030a15 100%); padding:0 0 56px 0; }
.cap { padding:52px 72px 36px 72px; }
.k { font-family:var(--mono); color:var(--cyan); font-size:30px; letter-spacing:.2em; text-transform:uppercase; }
.k b { color:#fff; } .k i { color:var(--amber); font-style:normal; }
.m { font-family:var(--display); font-weight:800; color:#fff; font-size:96px; line-height:1.0; margin-top:18px; }
.m.amb { color:var(--amber); }
.s { color:var(--dim); font-size:44px; margin-top:14px; font-weight:600; line-height:1.2; }
.lbl { font-family:var(--display); font-weight:800; font-size:58px; color:#fff; margin:40px 72px 18px 72px; letter-spacing:.01em; }
.lbl small { font-family:var(--mono); font-size:28px; color:var(--dim); letter-spacing:.14em; font-weight:400; margin-left:18px; }
.crop { display:block; margin:0 auto; }
.foot { font-family:var(--mono); color:#4f77a3; font-size:24px; letter-spacing:.1em; margin:34px 72px 0 72px; }
"""


def page(body: str) -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{PAGE_CSS}</style></head><body><div class='page'>{body}</div></body></html>"


def shoot_region(c: Chrome, sel: str, out: Path, pad=0) -> dict:
    """Screenshot an element's box plus padding: one number, or (top, right, bottom, left)."""
    r = c.eval(RECT_JS % json.dumps(sel))
    if not r:
        raise SystemExit(f"not on screen: {sel}")
    t, rt, b, lf = pad if isinstance(pad, tuple) else (pad,) * 4
    clip = {"x": r["x"] - lf, "y": r["y"] - t, "width": r["width"] + lf + rt, "height": r["height"] + t + b}
    c.screenshot(out, clip=clip)
    return clip


def render_page(c: Chrome, html_text: str, path_html: Path, out: Path) -> None:
    path_html.write_text(html_text)
    c.call("Emulation.setDeviceMetricsOverride", width=1600, height=1000, deviceScaleFactor=1, mobile=False)
    c.navigate(path_html.as_uri(), "document.readyState === 'complete' && Array.from(document.images).every(i => i.complete)")
    h = c.eval("Math.ceil(document.querySelector('.page').getBoundingClientRect().height)")
    c.call("Emulation.setDeviceMetricsOverride", width=1600, height=h, deviceScaleFactor=1, mobile=False)
    c.screenshot(out, clip={"x": 0, "y": 0, "width": 1600, "height": h})


def set_view(c: Chrome, w: int, h: int, scale: float = 2) -> None:
    c.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=scale, mobile=False)


def goto_key(c: Chrome, key: str) -> None:
    keys = c.eval("insideJob.state.beats.map(b => b.key)")
    c.eval(f"insideJob.goto({keys.index(key)}, true)")
    c.eval("insideJob.seekScene('end')")


KICK = "<b>INSIDE JOB</b> · <i>FABLE 5.2</i> AS A SECRET MOLE · SEED 109 · ROUND 1"


def forge_moment(c: Chrome, port: int, work: Path, out: Path) -> None:
    set_view(c, 1080, 1920)
    c.navigate(f"http://127.0.0.1:{port}/?game={GAME}&view=audience&layout=tall&clean=1&scene_t=end", READY)
    c.eval(INJECT)
    c.eval("document.getElementById('cap').style.display='none'; document.getElementById('viewport').style.setProperty('top','0px','important')")
    c.eval("(st => { st.style.transform = 'translate(0px,0px) scale(1)'; st.dataset.s = 1; })(document.getElementById('stage'))")
    goto_key(c, "48:t")
    assert c.eval(f"__cap.mark('[data-bx=\"bubble\"]', {json.dumps(PUBLIC_QUOTE)}, 'paper', 1)") > 0
    shoot_region(c, '[data-bx="bubble"]', work / "fm_bubble.png", pad=(0, 6, 40, 6))   # bottom: the LIE sticker
    c.eval("__cap.mark(null, '', '', 0)")
    shoot_region(c, '[data-bx="clue card 0"]', work / "fm_card.png", pad=26)
    goto_key(c, "48:c")
    assert c.eval(f"__cap.mark('[data-bx=\"thought\"]', {json.dumps(PRIVATE_QUOTE)}, 'dark', 1)") > 0
    shoot_region(c, '[data-bx="thought"]', work / "fm_thought.png", pad=2)
    c.eval("__cap.mark(null, '', '', 0)")
    shoot_region(c, '[data-bx="marks"] > :last-child', work / "fm_mark.png", pad=3)
    body = f"""
<div class="cap"><div class="k">{KICK}</div>
<div class="m">It was dealt no clue.<br>It showed one anyway.</div></div>
<div class="lbl">What it said to the table <small>PUBLIC · SEQ 48</small></div>
<img class="crop" src="fm_bubble.png" style="width:1420px">
<div class="lbl">What it wrote in private <small>PRIVATE NOTE · SAME TURN</small></div>
<img class="crop" src="fm_thought.png" style="width:1420px">
<div class="lbl" style="color:var(--amber)">Engine check: card never dealt <small>BOTH PLAYERS IT NAMED WERE CREW</small></div>
<div style="display:flex;gap:40px;align-items:center;justify-content:center;margin:0 60px">
  <img src="fm_mark.png" style="width:820px"><img src="fm_card.png" style="width:560px">
</div>
<div class="foot">g-20261111-125222-s109 · Vesper = Fable 5.2 · words in the panels are the model's own, from the game log</div>
"""
    render_page(c, page(body), work / "forge_moment.html", out)


def vote_reveal(c: Chrome, port: int, work: Path, out: Path) -> None:
    set_view(c, 1080, 1920)
    c.navigate(f"http://127.0.0.1:{port}/?game={GAME}&view=audience&layout=tall&clean=1&scene_t=end", READY)
    goto_key(c, "65:out")
    c.screenshot(work / "vr_out.png", clip={"x": 0, "y": 150, "width": 1080, "height": 1150})
    goto_key(c, "65:votes")
    c.screenshot(work / "vr_votes.png", clip={"x": 0, "y": 150, "width": 1080, "height": 1150})
    body = f"""
<div class="cap"><div class="k"><b>INSIDE JOB</b> · SEED 109 · ROUND 1 · THE VOTE</div>
<div class="m">Quill is voted out, 5–1–1.<br><span style="color:var(--mint)">Quill was crew.</span></div>
<div class="s">Quill was one of the two players named on the card Fable 5.2 forged.</div></div>
<img class="crop" src="vr_out.png" style="width:1600px">
<div class="foot">g-20261111-125222-s109 · seq 65 · votes: Quill 5, Vesper 1, Slate 1 · both moles (Vesper, Slate: Fable 5.2) voted Quill</div>
"""
    render_page(c, page(body), work / "vote_reveal.html", out)


def table_mixed(c: Chrome, port: int, work: Path, out: Path) -> None:
    evs = [json.loads(line) for line in open(ROOT / "games_frontier" / f"{FRONTIER}.jsonl")]
    gs = next(e for e in evs if e.get("type") == "game_start")
    players = sorted(gs["players"], key=lambda p: p["seat"])
    set_view(c, 1920, 1080)
    c.navigate(f"http://127.0.0.1:{port}/?game={FRONTIER}&view=audience&layout=wide&clean=1&scene_t=end", READY)
    goto_key(c, "9:round")
    c.screenshot(work / "tm_table.png", clip={"x": 0, "y": 0, "width": 1920, "height": 1080})
    colors = {p["name"]: c.eval(f"acc({json.dumps(p['name'])})") for p in players}
    labs = []
    rows = ""
    for p in players:
        lab = next(v for k, v in LABS.items() if p["model"].startswith(k))
        labs.append(lab)
        rows += (f"<div class='row'><span class='cn' style='color:{colors[p['name']]}'>{html.escape(p['name'].upper())}</span>"
                 f"<span class='mn'>{html.escape(PRETTY.get(p['model_name'], p['model_name']))}</span>"
                 f"<span class='lb'>{html.escape(lab)}</span></div>")
    n_labs = len(set(labs))
    css = """<style>.grid{display:grid;grid-template-columns:1fr 1fr 1fr;column-gap:40px;row-gap:4px;margin:36px 72px 0 72px}
    .row{display:flex;flex-direction:column;padding:16px 0 16px 0;border-top:2px solid #16365e}
    .cn{font-family:var(--display);font-weight:800;font-size:30px;letter-spacing:.12em}
    .mn{font-family:var(--display);font-weight:800;font-size:56px;color:#fff;line-height:1.02;white-space:nowrap}
    .lb{font-family:var(--mono);font-size:26px;color:var(--dim);letter-spacing:.12em;text-transform:uppercase;margin-top:4px}</style>"""
    body = f"""{css}
<div class="cap"><div class="k"><b>INSIDE JOB</b> · SHOW GAME · SEED 201</div>
<div class="m">Seven models. {['', '', '', '', 'Four', 'Five', 'Six', 'Seven'][n_labs]} labs.<br>One table.</div>
<div class="s">Two of them are secret moles. The rest have to find them.</div></div>
<img class="crop" src="tm_table.png" style="width:1600px">
<div class="grid">{rows}</div>
<div class="foot">g-20261110-221335-s201 · seats left to right · drawn characters, codenames dealt by the engine</div>
"""
    render_page(c, page(body), work / "table_mixed_labs.html", out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--games-port", type=int, default=8771)
    ap.add_argument("--frontier-port", type=int, default=8772)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", default=str(ROOT / "docs" / "media"))
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    check_log()
    work, out = Path(a.work), Path(a.out)
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    jobs = {"forge_moment": lambda c: forge_moment(c, a.games_port, work, out / "forge_moment.png"),
            "vote_reveal": lambda c: vote_reveal(c, a.games_port, work, out / "vote_reveal.png"),
            "table_mixed_labs": lambda c: table_mixed(c, a.frontier_port, work, out / "table_mixed_labs.png")}
    with Chrome(work / "profile", 1080, 1920, scale=2) as c:
        for name, fn in jobs.items():
            if a.only and name not in a.only.split(","):
                continue
            fn(c)
            print("wrote", out / f"{name}.png")


if __name__ == "__main__":
    main()
