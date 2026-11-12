"""Render docs/media/finale_clip.mp4 and finale_clip.gif: the finale card, built up one line at a time.

Method: an animated version of docs/media/finale_card.png (no replay viewer). Every frame is the card
from analysis/media/finale_card.py drawn with `card_svg(ctx, step, fade)`, so the clip shows exactly the
card's words, read from the log and checked by `finale_card.check()` before any frame is drawn. Frames
are rendered with rsvg-convert at 1080 x 1350 (4:5) and joined with ffmpeg at 30 fps. No model calls,
no network, read only.

Shots (each new element fades in over FADE seconds, then holds). The clip opens on FIRST, not on the
card's empty "intro" step, so frame 0 (the still shown before the clip plays) already carries the
headline and the first promise:
  quill_said    the headline, the rules line, the two speakers and Quill's public line (finale pitch)
  quill_wrote   Quill's private note, same turn
  cipher_said   Cipher's public line (finale pitch)
  cipher_wrote  Cipher's private note, same turn
  result        "Both stole. Both got nothing." with the payouts

    env -u OPENROUTER_API_KEY python3.11 analysis/media/finale_clip.py --work <scratch folder>
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import finale_card as FCARD  # noqa: E402

FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
FPS = 30
W, H = 1080, 1350          # 4:5, the same frame as forge_clip.mp4
FADE = 0.35                # seconds for each new element to fade in
FIRST = "quill_said"       # the card step the clip opens on (the empty "intro" step is not shown)
HOLD = {"quill_said": 4.0, "quill_wrote": 3.2, "cipher_said": 3.4, "cipher_wrote": 3.2, "result": 3.8}


def timeline() -> list[tuple[int, float, int]]:
    """(step, opacity of that step's element, frames) in order. The opening step has no fade, so frame 0
    is a whole picture with the first quote on it (the thumbnail)."""
    out = []
    n_fade = round(FADE * FPS)
    start = FCARD.STEPS.index(FIRST)
    for i, name in enumerate(FCARD.STEPS):
        if i < start:
            continue
        if i > start:
            for k in range(1, n_fade + 1):
                out.append((i, k / (n_fade + 1), 1))
        out.append((i, 1.0, round(HOLD[name] * FPS)))
    return out


def render_frames(work: Path) -> int:
    ctx = FCARD.check()
    uniq, frames = work / "unique", work / "frames"
    for d in (uniq, frames):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
    n = 0
    for j, (step, fade, count) in enumerate(timeline()):
        svg, png = uniq / f"{j:03d}.svg", uniq / f"{j:03d}.png"
        FCARD.render(FCARD.card_svg(ctx, step, fade), svg, png, W, H)
        for _ in range(count):
            os.link(png, frames / f"{n:05d}.png")
            n += 1
    return n


def encode(work: Path, out_dir: Path) -> None:
    frames = work / "frames"
    mp4 = out_dir / "finale_clip.mp4"
    subprocess.run([FFMPEG, "-loglevel", "error", "-y", "-framerate", str(FPS), "-i", str(frames / "%05d.png"),
                    "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p", "-profile:v", "high",
                    "-movflags", "+faststart", "-threads", "2", "-an", str(mp4)], check=True)
    # GIF: 480 px wide, 10 fps, one 128-colour palette for the whole clip (as forge_clip.gif)
    pal = work / "palette.png"
    vf = "fps=10,scale=480:-1:flags=lanczos"
    subprocess.run([FFMPEG, "-loglevel", "error", "-y", "-i", str(mp4), "-vf", f"{vf},palettegen=max_colors=128:stats_mode=diff",
                    "-threads", "2", str(pal)], check=True)
    subprocess.run([FFMPEG, "-loglevel", "error", "-y", "-i", str(mp4), "-i", str(pal), "-lavfi",
                    f"{vf}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle", "-threads", "2",
                    str(out_dir / "finale_clip.gif")], check=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--work", required=True, help="scratch folder for the frames")
    ap.add_argument("--out", default=str(ROOT / "docs" / "media"))
    ap.add_argument("--frames-only", action="store_true")
    a = ap.parse_args()
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    n = render_frames(work)
    t = 0.0
    for step, fade, count in timeline():
        if fade == 1.0:
            print(f"  {t:5.2f} s  {FCARD.STEPS[step]}")
        t += count / FPS
    print(f"{n} frames, {n / FPS:.2f} s")
    if not a.frames_only:
        Path(a.out).mkdir(parents=True, exist_ok=True)
        encode(work, Path(a.out))


if __name__ == "__main__":
    main()
