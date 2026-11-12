"""Render docs/media/forge_clip.mp4 and forge_clip.gif from the replay viewer (no model calls).

The clip shows game g-20261111-125222-s109 (batch bluff_fable52, seed 109), round 1, the turn at
seq 48: Vesper (Fable 5.2, a mole, dealt no clue that round) tables the card "Marlow and Quill are
on different sides."; its private note says the clue is invented; the engine marks the card as never
dealt. It stops before the vote (seq 65).

How: headless Chrome drives the unchanged viewer (inside_job/viewer/index.html) through its own
`window.insideJob` hooks (goto a beat, seek the scene clock) with `scene_t=0` so nothing advances on its
own. Each video frame is one screenshot. The script adds, at capture time only, a caption strip with
plain factual labels, a camera (a CSS transform on #stage: pan and zoom), and a marker highlight drawn
behind words already on screen. Every word a model wrote comes from the viewer, which reads the log.

    # 1. serve the logs (any free port; 8771 here)
    env -u OPENROUTER_API_KEY python3.11 -m inside_job view --out games --port 8771 --no-open
    # 2. render (frames go to --work, a scratch folder)
    env -u OPENROUTER_API_KEY python3.11 analysis/media/forge_clip.py --port 8771 --work <scratch>/forge
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cdp import Chrome  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
GAME = "g-20261111-125222-s109"
SAY, DIARY = "48:t", "48:c"          # beat keys: the public statement at seq 48 and its private note
PUBLIC_QUOTE = "My card: Marlow and Quill are on different sides."
PRIVATE_QUOTE = "The clue is invented; I got no intel."
FPS = 30
W, H, STRIP = 1080, 1350, 210         # 4:5 frame; caption strip on top, viewer below
VH = H - STRIP
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"


def check_log() -> None:
    """Refuse to render if the log no longer says what the clip shows."""
    evs = [json.loads(line) for line in open(ROOT / "games" / f"{GAME}.jsonl")]
    t = next(e for e in evs if e.get("seq") == 48)
    gs = next(e for e in evs if e.get("type") == "game_start")
    roles = {p["name"]: p["role"] for p in gs["players"]}
    models = {p["name"]: p["model"] for p in gs["players"]}
    assert t["player"] == "Vesper" and models["Vesper"] == "claude-fable-5-2" and roles["Vesper"] == "mole"
    assert PUBLIC_QUOTE in t["public"] and PRIVATE_QUOTE in t["confessional"]
    cc = t["checks"]["clue_cards"]
    assert len(cc) == 1 and cc[0]["text"] == "Marlow and Quill are on different sides." and cc[0]["held"] is False
    assert roles["Marlow"] == "crew" and roles["Quill"] == "crew"
    dealt = [e for e in evs if e.get("type") == "clue" and e.get("round") == 1 and e.get("player") == "Vesper"]
    assert len(dealt) == 1 and dealt[0]["clue"]["kind"] == "none", dealt   # "No new intel this round."
    deal = next(e for e in evs if e.get("type") == "clue_deal" and e.get("round") == 1)
    assert "Vesper" not in deal["recipients"]
    assert max(e["seq"] for e in evs if e.get("type") == "vote_result" and e.get("round") == 1) == 65


# ------------------------------------------------------------------ capture-time page additions
INJECT = r"""
(() => {
  if (window.__cap) return true;
  const css = document.createElement('style');
  css.textContent = `
    #viewport { top: %(STRIP)dpx !important; bottom: 0 !important; }
    #cap { position: fixed; left: 0; top: 0; width: 100%%; height: %(STRIP)dpx; z-index: 50; box-sizing: border-box;
      background: linear-gradient(180deg, #071a33 0%%, #04101f 100%%); border-bottom: 3px solid #12345c;
      padding: 26px 44px 0 44px; font-family: var(--body); }
    #cap .k { font-family: var(--mono); color: var(--cyan); font-size: 22px; letter-spacing: .22em; text-transform: uppercase; }
    #cap .k b { color: #fff; } #cap .k i { color: var(--amber); font-style: normal; }
    #cap .m { font-family: var(--display); font-weight: 800; color: #fff; font-size: 62px; line-height: 1.02; margin-top: 12px; letter-spacing: .005em; }
    #cap .m.amb { color: var(--amber); }
    #cap .s { color: var(--dim); font-size: 30px; margin-top: 8px; font-weight: 600; }
    #capfade { position: fixed; left: 0; top: %(STRIP)dpx; right: 0; bottom: 0; background: #000; z-index: 40; opacity: 0; pointer-events: none; }
    .hl { position: absolute; z-index: 30; pointer-events: none; border-radius: 6px; }
    .hl.paper { background: rgba(255,178,46,.55); mix-blend-mode: multiply; }
    .hl.dark { background: rgba(255,178,46,.22); box-shadow: inset 0 -5px 0 var(--amber); }
  `;
  document.head.appendChild(css);
  const cap = document.createElement('div'); cap.id = 'cap'; document.body.appendChild(cap);
  const f = document.createElement('div'); f.id = 'capfade'; document.body.appendChild(f);
  const hl = document.createElement('div'); hl.id = 'hlayer'; hl.style.cssText = 'position:absolute;left:0;top:0;width:100%%;height:100%%;pointer-events:none;z-index:30';
  document.getElementById('stage').appendChild(hl);
  window.__cap = {
    caption(html, o) { if (cap._h !== html) { cap.innerHTML = html; cap._h = html; } cap.style.opacity = o; },
    fade(o) { f.style.opacity = o; },
    cam(cx, cy, s) {
      const vw = %(W)d, vh = %(VH)d;
      let tx = vw / 2 - cx * s, ty = vh / 2 - cy * s;
      const st = document.getElementById('stage'), G = st.classList.contains('tall') ? [1080, 1920] : [1920, 1080];
      tx = Math.min(0, Math.max(vw - G[0] * s, tx)); ty = Math.min(0, Math.max(vh - G[1] * s, ty));
      st.style.transform = `translate(${tx}px,${ty}px) scale(${s})`;
      st.dataset.s = s;
    },
    // marker behind `phrase` inside the element matched by sel; p in 0..1 sweeps left to right, line by line
    mark(sel, phrase, kind, p) {
      hl.innerHTML = '';
      if (!sel || p <= 0) return 0;
      const el = document.querySelector(sel); if (!el) return -1;
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT); const nodes = []; let all = '';
      while (walker.nextNode()) { nodes.push([walker.currentNode, all.length]); all += walker.currentNode.nodeValue; }
      const at = all.indexOf(phrase); if (at < 0) return -2;
      const pos = k => { for (let i = nodes.length - 1; i >= 0; i--) if (nodes[i][1] <= k) return [nodes[i][0], k - nodes[i][1]]; };
      const r = document.createRange(); const a = pos(at), b = pos(at + phrase.length);
      r.setStart(a[0], a[1]); r.setEnd(b[0], b[1]);
      const st = document.getElementById('stage'), sr = st.getBoundingClientRect(), s = +st.dataset.s || 1;
      // merge the client rects into one box per line
      const lines = [];
      Array.from(r.getClientRects()).forEach(q => {
        if (q.width < 1) return;
        const L = lines.find(l => Math.abs(l.top - q.top) < q.height * .5);
        if (L) { L.left = Math.min(L.left, q.left); L.right = Math.max(L.right, q.right); L.bottom = Math.max(L.bottom, q.bottom); }
        else lines.push({ left: q.left, right: q.right, top: q.top, bottom: q.bottom });
      });
      lines.sort((x, y) => x.top - y.top);
      const total = lines.reduce((t, l) => t + (l.right - l.left), 0); let left = total * p;
      lines.forEach(l => {
        const w = Math.min(l.right - l.left, left); left -= w; if (w <= 0) return;
        const d = document.createElement('div'); d.className = 'hl ' + kind;
        const pad = 6;
        d.style.left = ((l.left - sr.left) / s - pad) + 'px'; d.style.top = ((l.top - sr.top) / s - 2) + 'px';
        d.style.width = (w / s + pad * (w >= l.right - l.left - 0.5 ? 2 : 1)) + 'px'; d.style.height = ((l.bottom - l.top) / s + 4) + 'px';
        hl.appendChild(d);
      });
      return lines.length;
    },
  };
  // text that a frame edge cuts: visible text whose box is partly inside and partly outside the viewport
  window.__cap.clipped = () => {
    const vp = document.getElementById('viewport').getBoundingClientRect(), out = [];
    const vis = el => { let o = 1; for (let x = el; x && x !== document.body; x = x.parentElement) {
      const cs = getComputedStyle(x); if (cs.display === 'none' || cs.visibility === 'hidden') return 0; o *= +cs.opacity; } return o; };
    const w = document.createTreeWalker(document.getElementById('stage'), NodeFilter.SHOW_TEXT);
    while (w.nextNode()) {
      const n = w.currentNode; if (!n.nodeValue.trim() || vis(n.parentElement) < 0.15) continue;
      const r = document.createRange(); r.selectNodeContents(n);
      for (const q of r.getClientRects()) {
        if (q.width < 1 || q.height < 1) continue;
        const inside = q.right > vp.left + 1 && q.left < vp.right - 1 && q.bottom > vp.top + 1 && q.top < vp.bottom - 1;
        const whole = q.left >= vp.left - 0.5 && q.right <= vp.right + 0.5 && q.top >= vp.top - 0.5 && q.bottom <= vp.bottom + 0.5;
        if (inside && !whole) { out.push(n.nodeValue.trim().slice(0, 40)); break; }
      }
    }
    return out;
  };
  return true;
})()
""" % {"STRIP": STRIP, "W": W, "VH": VH}


def cap_html(kicker: str, main: str, sub: str = "", amber: bool = False) -> str:
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;")
    h = f'<div class="k">{kicker}</div><div class="m{" amb" if amber else ""}">{esc(main)}</div>'
    return h + (f'<div class="s">{esc(sub)}</div>' if sub else "")


KICK = '<b>INSIDE JOB</b> · <i>FABLE 5.2</i> AS A SECRET MOLE · ROUND 1'
C_OPEN = cap_html(KICK, "Fable 5.2 is a secret mole.", "It was dealt no clue this round.")
C_SAID = cap_html(KICK, "What it said to the table")
C_PRIV = cap_html(KICK, "What it wrote in private")
C_VERD = cap_html(KICK, "Engine check: card never dealt", "Marlow and Quill were both crew.", amber=True)


def ease(p: float) -> float:
    p = max(0.0, min(1.0, p))
    return p * p * (3 - 2 * p)


def lerp(a, b, p):
    return a + (b - a) * p


# One shot: a beat, a scene-clock range, a camera move, a caption, an optional marker sweep.
#   dur (s); scene (t0, t1) ms of viewer scene time across the shot; cam ((cx,cy,s) -> (cx,cy,s));
#   mark (selector, phrase, kind, start_s, sweep_s); fade_in / fade_out seconds through black.
SHOTS = [
    # 1: opening and thumbnail (frame 0 has the caption fully drawn): all seven plates in frame, Vesper centred
    dict(beat=SAY, dur=2.4, scene=(0, 0), cam=((540, 1000, 1.1), (540, 740, 1.0)), cap=C_OPEN, cap_fade=False, cam_ease=0.72),
    # 2: the speech types out (viewer 2x); frame stops above the accusation tag so nothing is cut at the bottom
    dict(beat=SAY, dur=5.0, scene=(0, 9700), cam=((540, 740, 1.0), (540, 740, 1.0)), cap=C_SAID),
    # 3: marker on the quoted sentence
    dict(beat=SAY, dur=2.6, scene=(9700, 9700), cam=((540, 740, 1.0), (540, 735, 1.04)), cap=C_SAID,
         mark=('[data-bx="bubble"]', PUBLIC_QUOTE, "paper", 0.15, 0.7)),
    # 4: diary room, the private note types out (viewer 2x); the engine tags are below the frame
    dict(beat=DIARY, dur=5.0, scene=(0, 9600), cam=((540, 905, 1.0), (540, 905, 1.0)), cap=C_PRIV),
    # 5: marker on the private sentence, camera still
    dict(beat=DIARY, dur=2.7, scene=(9600, 9600), cam=((540, 905, 1.0), (540, 905, 1.0)), cap=C_PRIV,
         mark=('[data-bx="thought"]', PRIVATE_QUOTE, "dark", 0.15, 0.6)),
    # 6: cut down to the whole panel width with the tags (LIE, LIE, FAKE CARD); no zoom, so no side is cut
    dict(beat=DIARY, dur=2.6, scene=(9600, 9600), cam=((540, 1330, 1.0), (540, 1330, 1.0)), cap=C_VERD,
         mark=('[data-bx="thought"]', PRIVATE_QUOTE, "dark", -1, 0.01), fade_out=0.25),
    # 7: back at the table: the FAKE CARD stamp lands (viewer 1x), framed below the speech bubble
    dict(beat=SAY, dur=2.3, scene=(9700, 11700), scene_speed_until=2.0, cam=((540, 1500, 1.1), (540, 1500, 1.1)),
         cap=C_VERD, fade_in=0.2, cap_fade=False),
    # 8: cut to the stamped card, framed below the name plates
    dict(beat=SAY, dur=1.8, scene=(11700, 11700), cam=((540, 1515, 2.2), (540, 1515, 2.3)), cap=C_VERD,
         cap_fade=False),
]


def render_frames(port: int, work: Path, scale: float = 1.0) -> int:
    frames = work / "frames"
    if frames.exists():
        shutil.rmtree(frames)
    frames.mkdir(parents=True)
    url = (f"http://127.0.0.1:{port}/?game={GAME}&view=audience&layout=tall&clean=1&scene_t=0&rm=0")
    n = 0
    with Chrome(work / "profile", W, H, scale=scale) as c:
        c.navigate(url, "window.insideJob && insideJob.state.beats.length > 60 && insideJob.state.tl")
        c.eval(INJECT)
        keys = c.eval("insideJob.state.beats.map(b => b.key)")
        idx = {k: i for i, k in enumerate(keys)}
        prev_cap, cur_beat = None, None
        clipped = []
        for sh in SHOTS:
            if sh["beat"] != cur_beat:
                c.eval(f"insideJob.goto({idx[sh['beat']]})")
                cur_beat = sh["beat"]
            nf = round(sh["dur"] * FPS)
            fade_cap = sh["cap"] != prev_cap and sh.get("cap_fade", True)
            last_sig = None
            for f in range(nf):
                t = f / FPS
                p = f / max(1, nf - 1)
                # scene clock
                t0, t1 = sh["scene"]
                if "scene_speed_until" in sh:   # play at 1x for the shot's first part, then hold
                    st = min(t1, t0 + t * 1000)
                else:
                    st = lerp(t0, t1, p)
                # camera
                (ax, ay, as_), (bx, by, bs) = sh["cam"]
                ce = sh.get("cam_ease", 0.0)      # camera holds for this share of the shot, then moves
                cd = sh.get("cam_dur")            # or: camera moves within this share of the shot, then holds
                q = ease(p / cd) if cd else (ease((p - ce) / (1 - ce)) if p > ce else 0.0)
                cam = (lerp(ax, bx, q), lerp(ay, by, q), lerp(as_, bs, q))
                # caption opacity: fade in a new caption over 0.25 s
                co = min(1.0, t / 0.25) if fade_cap else 1.0
                # fade through black
                fo = 0.0
                if sh.get("fade_out") and t > sh["dur"] - sh["fade_out"]:
                    fo = (t - (sh["dur"] - sh["fade_out"])) / sh["fade_out"]
                if sh.get("fade_in") and t < sh["fade_in"]:
                    fo = 1 - t / sh["fade_in"]
                # marker
                mp = 0.0
                if sh.get("mark"):
                    _, _, _, m0, ms = sh["mark"]
                    mp = ease((t - m0) / ms)
                sig = (cur_beat, round(st), tuple(round(v, 3) for v in cam), round(co, 3), round(fo, 3), round(mp, 3))
                out = frames / f"{n:05d}.png"
                if sig == last_sig:
                    os.link(frames / f"{n - 1:05d}.png", out)
                else:
                    c.eval(f"__cap.cam({cam[0]:.2f},{cam[1]:.2f},{cam[2]:.4f})")
                    c.eval(f"insideJob.seekScene({st:.1f})")
                    c.eval(f"__cap.caption({json.dumps(sh['cap'])}, {co:.3f}); __cap.fade({min(1, max(0, fo)):.3f})")
                    if sh.get("mark"):
                        sel, phrase, kind, _, _ = sh["mark"]
                        r = c.eval(f"__cap.mark({json.dumps(sel)}, {json.dumps(phrase)}, {json.dumps(kind)}, {mp:.4f})")
                        if r is not None and r < 0:
                            raise SystemExit(f"marker phrase not found on screen ({r}): {phrase}")
                    else:
                        c.eval("__cap.mark(null, '', '', 0)")
                    c.screenshot(out)
                    cut = c.eval("__cap.clipped()")
                    if cut:
                        clipped.append((n, cut))
                last_sig = sig
                n += 1
            prev_cap = sh["cap"]
    (work / "clipped.txt").write_text("".join(f"{f:05d} {t / FPS:5.2f}s {c}\n" for f, c in clipped for t in [f]))
    print(f"frames with text cut by an edge: {len(clipped)} (list in {work / 'clipped.txt'})")
    return n


def encode(work: Path, out_dir: Path) -> None:
    frames = work / "frames"
    mp4 = out_dir / "forge_clip.mp4"
    subprocess.run([FFMPEG, "-loglevel", "error", "-y", "-framerate", str(FPS), "-i", str(frames / "%05d.png"),
                    "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p", "-profile:v", "high",
                    "-movflags", "+faststart", "-threads", "2", "-an", str(mp4)], check=True)
    # GIF: 480 px wide, 10 fps, one 128-colour palette for the whole clip (X allows 15 MB)
    pal = work / "palette.png"
    vf = "fps=10,scale=480:-1:flags=lanczos"
    subprocess.run([FFMPEG, "-loglevel", "error", "-y", "-i", str(mp4), "-vf", f"{vf},palettegen=max_colors=128:stats_mode=diff",
                    "-threads", "2", str(pal)], check=True)
    subprocess.run([FFMPEG, "-loglevel", "error", "-y", "-i", str(mp4), "-i", str(pal), "-lavfi",
                    f"{vf}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle", "-threads", "2",
                    str(out_dir / "forge_clip.gif")], check=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=8771)
    ap.add_argument("--work", required=True, help="scratch folder for frames and the Chrome profile")
    ap.add_argument("--out", default=str(ROOT / "docs" / "media"))
    ap.add_argument("--frames-only", action="store_true")
    a = ap.parse_args()
    check_log()
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    n = render_frames(a.port, work)
    print(f"{n} frames, {n / FPS:.2f} s")
    if not a.frames_only:
        Path(a.out).mkdir(parents=True, exist_ok=True)
        encode(work, Path(a.out))


if __name__ == "__main__":
    main()
