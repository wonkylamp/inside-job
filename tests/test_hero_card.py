"""analysis/media/hero_card.py: the hero image that opens the thread. Read only, no model calls.

The script must run, write the same SVG bytes every time (and the files in docs/media must be the
current build), and every number on the image must equal the number counted here from the logs,
independently of the script. Also: no forbidden words, no model names on the seats, nothing under
28 px, no embedded images, PNG 1600 x 900 and under 1 MB, alt text under 1,000 characters.

Needs node (to run the viewer's character code) and rsvg-convert; skipped without them or the logs.
"""

import glob
import json
import re
import shutil
import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
sys.path.insert(0, str(ROOT / "analysis" / "media"))

import extra_stats as ES  # noqa: E402
import hero_card as HERO  # noqa: E402

SVG = "{http://www.w3.org/2000/svg}"
MEDIA = ROOT / "docs" / "media"
FORBIDDEN = ("honest", "trustworth", "fooled", "liar", "made to lie", "best", "worst", "rank", "cheat",
             "lied", "dollar", "usd", "$", "winner", "won")
HAVE_TOOLS = bool(shutil.which("node") or Path(HERO.NODE).exists()) and Path(HERO.RSVG).exists()
HAVE_LOGS = (ROOT / "games" / "index.jsonl").exists() and (ROOT / "games_frontier" / "index.jsonl").exists()


# Played after the launch counts were made (2026-11-12); published, but not part of the image's totals.
AFTER_LAUNCH = {"bluff_hydrogen"}


def count_from_logs() -> dict:
    """Games, calls, players and moles, counted here straight from the logs (not through the script)."""
    games = calls = 0
    for index in (ROOT / "games" / "index.jsonl", ROOT / "games_frontier" / "index.jsonl"):
        with open(index, encoding="utf-8") as fh:
            lines = fh.readlines()
        for line in lines:
            r = json.loads(line)
            log = Path(r["log"])
            if not log.exists():
                log = index.parent / log.name
            if r.get("mock") or not log.exists() or r.get("batch") in AFTER_LAUNCH:
                continue
            games += 1
            calls += (r.get("tokens") or {}).get("calls", 0) or 0
    shape = set()
    for f in glob.glob(str(ROOT / "games" / "*.jsonl")) + glob.glob(str(ROOT / "games_frontier" / "*.jsonl")):
        with open(f, encoding="utf-8") as fh:
            e = json.loads(fh.readline())
        b = e.get("batch") or ""
        if e.get("type") == "game_start" and (b.startswith("bluff") or b.startswith("frontier")):
            shape.add((len(e["players"]), e["config"]["game"]["num_moles"]))
    assert len(shape) == 1, shape
    (players, moles), = shape
    return {"games": games, "calls": calls, "players": players, "moles": moles}


def texts(svg: str) -> list[ET.Element]:
    return list(ET.fromstring(svg).iter(f"{SVG}text"))


def all_text(svg: str) -> str:
    return "\n".join("".join(t.itertext()) for t in texts(svg))


@unittest.skipUnless(HAVE_TOOLS and HAVE_LOGS, "needs node, rsvg-convert and the game logs")
class TestHeroCard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._t = tempfile.TemporaryDirectory()
        cls.a, cls.b = Path(cls._t.name) / "a", Path(cls._t.name) / "b"
        cls.facts = HERO.build(cls.a, png=True)
        HERO.build(cls.b, png=False)
        cls.svg = (cls.a / "hero.svg").read_text(encoding="utf-8")
        cls.alt = (cls.a / "hero_alt.txt").read_text(encoding="utf-8")
        cls.logs = count_from_logs()

    @classmethod
    def tearDownClass(cls):
        cls._t.cleanup()

    def test_deterministic(self):
        self.assertEqual((self.a / "hero.svg").read_bytes(), (self.b / "hero.svg").read_bytes())
        self.assertEqual((self.a / "hero_alt.txt").read_bytes(), (self.b / "hero_alt.txt").read_bytes())

    def test_files_on_disk_are_the_current_build(self):
        self.assertEqual((MEDIA / "hero.svg").read_bytes(), (self.a / "hero.svg").read_bytes(),
                         "docs/media/hero.svg is stale: run analysis/media/hero_card.py")
        self.assertEqual((MEDIA / "hero_alt.txt").read_bytes(), (self.a / "hero_alt.txt").read_bytes())

    def test_png(self):
        for p in (self.a / "hero.png", MEDIA / "hero.png"):
            data = p.read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", data[16:24]), (1600, 900), p)
            self.assertLess(len(data), 1_000_000, p)

    def test_facts_match_the_logs(self):
        f, n = self.facts, self.logs
        self.assertEqual(f["games"], n["games"])
        self.assertEqual(f["calls"], n["calls"])
        self.assertEqual(f["calls_floor"], n["calls"] // 1000 * 1000)
        self.assertGreaterEqual(n["calls"], f["calls_floor"])
        self.assertEqual((f["players"], f["moles"]), (n["players"], n["moles"]))
        self.assertEqual(f["models"], [name for name, _ in ES.GROUPS])

    def test_every_number_on_the_image(self):
        f, n = self.facts, self.logs
        text = all_text(self.svg)
        for name in f["models"]:                     # model names carry version digits; they are checked below
            text = text.replace(name, " ")
        found = sorted(re.findall(r"\d[\d,]*\+?", text))
        expected = sorted([str(n["players"]), str(n["moles"]), str(n["games"]), f"{n['calls'] // 1000 * 1000:,}+"])
        self.assertEqual(found, expected)
        self.assertIn(f"{n['players']} AI players. {n['moles']} secret moles. Every private note logged.", text)
        self.assertIn(f"{n['games']} GAMES", text)
        self.assertIn(f"{n['calls'] // 1000 * 1000:,}+ MODEL CALLS", text)

    def test_model_names_in_groups_order_and_only_in_the_footer(self):
        footer = [t for t in texts(self.svg) if any(m in "".join(t.itertext()) for m in self.facts["models"])]
        self.assertEqual(len(footer), 1)
        line = "".join(footer[0].itertext())
        self.assertEqual(line, " · ".join(name for name, _ in ES.GROUPS))
        # the seats: codenames and roles only
        seat_words = {n.upper() for n, _e, _m in HERO.SEATS} | {"MOLE", "CREW"}
        root = ET.fromstring(self.svg)
        for g in root.iter(f"{SVG}g"):
            if g.get("class") == "seat":
                self.assertEqual(list(g.iter(f"{SVG}text")), [])
        plate_texts = [("".join(t.itertext())) for t in texts(self.svg)
                       if "".join(t.itertext()) in seat_words]
        self.assertEqual(len(plate_texts), 2 * len(HERO.SEATS))
        self.assertEqual(sum(1 for t in plate_texts if t == "MOLE"), self.logs["moles"])
        self.assertEqual(sum(1 for t in plate_texts if t == "CREW"), self.logs["players"] - self.logs["moles"])
        self.assertEqual(sum(1 for g in root.iter(f"{SVG}g") if g.get("class") == "seat"), self.logs["players"])

    def test_no_forbidden_words(self):
        for where, s in (("image", all_text(self.svg)), ("alt text", self.alt)):
            low = s.lower()
            for w in FORBIDDEN:
                if w.isalpha():
                    self.assertIsNone(re.search(rf"\b{re.escape(w)}", low), f"{w!r} in the {where}")
                else:
                    self.assertNotIn(w, low, f"{w!r} in the {where}")

    def test_text_size_and_no_images(self):
        root = ET.fromstring(self.svg)
        for el in list(root.iter(f"{SVG}text")) + list(root.iter(f"{SVG}tspan")):
            if el.get("font-size"):
                self.assertGreaterEqual(float(el.get("font-size")), 28, "".join(el.itertext()))
        self.assertEqual(list(root.iter(f"{SVG}image")), [])
        self.assertNotIn("art/avatars", self.svg)
        self.assertNotIn("portraits", self.svg)

    def test_alt_text(self):
        self.assertLess(len(self.alt), 1000)
        self.assertEqual(self.alt.strip(), HERO.alt_text(self.facts))
        self.assertIn(f"{self.logs['games']} games", self.alt)
        self.assertIn(", ".join(name for name, _ in ES.GROUPS), self.alt)


if __name__ == "__main__":
    unittest.main()
