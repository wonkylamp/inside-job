"""analysis/bluff_chart.py and the importable parts of analysis/bluff_score.py, on synthetic games.

Every fixture is written to a temp directory; nothing here reads games/.
"""

import json
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ANALYSIS = Path(__file__).resolve().parent.parent / "analysis"
if str(ANALYSIS) not in sys.path:
    sys.path.insert(0, str(ANALYSIS))

import bluff_chart  # noqa: E402
import bluff_score  # noqa: E402

SVG_NS = "http://www.w3.org/2000/svg"
MOLES = ("Ash", "Birch")
CREW = ("Cedar", "Dove", "Elm")


def log_events(mole_sus, crew_sus, *, winner="crew"):
    """A tiny 5-player game. Each crew member's vote turn gives every mole mole_sus and every other
    crew member crew_sus, so the gap is exactly mole_sus - crew_sus. Noise the score must ignore:
    a mole's vote-time suspicion, crew suspicion outside the vote, and a name that is not a player."""
    ev = [{"type": "game_start"}]
    ev += [{"type": "role", "player": p, "role": "mole"} for p in MOLES]
    ev += [{"type": "role", "player": p, "role": "crew"} for p in CREW]
    ev.append({"type": "round_start", "alive": list(MOLES + CREW)})
    for p in CREW:
        sus = {m: mole_sus for m in MOLES}
        sus.update({c: crew_sus for c in CREW if c != p})
        ev.append({"type": "turn", "player": p, "model": "m-crew", "turn_phase": "discuss", "public": "hi",
                   "action": {"suspicion": {m: 0 for m in MOLES}}})
        sus_noise = dict(sus, Nobody=99)
        ev.append({"type": "turn", "player": p, "model": "m-crew", "turn_phase": "vote",
                   "action": {"suspicion": sus_noise}})
    ev.append({"type": "turn", "player": "Ash", "model": "m-mole", "turn_phase": "vote",
               "action": {"suspicion": {c: 100 for c in CREW}}})
    ev.append({"type": "vote_result", "votes": {"Cedar": "Ash", "Dove": "Elm", "Elm": "Ash", "Ash": "Elm",
                                                "Birch": "Elm"}, "eliminated": "Elm", "role": "crew"})
    ev.append({"type": "game_end", "winner": winner, "survivors": ["Ash", "Birch", "Cedar", "Dove"]})
    return ev


def index_row(batch, seed, log, winner, effort="low"):
    players = [{"name": m, "model": "m-mole", "model_name": f"Mole Model {'AB'[i]}", "role": "mole"}
               for i, m in enumerate(MOLES)]
    players += [{"name": c, "model": f"m-{c}", "model_name": f"Crew {c}" + (" C" if c == "Elm" else ""),
                 "role": "crew"} for c in CREW]
    return {"game_id": f"{batch}-{seed}", "seed": seed, "batch": batch, "spoiled": False, "winner": winner,
            "log": log, "players": players, "conditions": {"effort": effort}}


# group name, batch, [(seed, mole suspicion, crew suspicion, winner)]
FIXTURE = [
    ("Alpha 1 moles", "alpha", [(1, 70, 30, "crew"), (2, 60, 40, "moles"), (3, 50, 50, "crew")]),
    ("Beta 2 moles", "beta", [(1, 20, 35, "moles"), (2, 30, 40, "moles"), (3, 45, 40, "crew")]),
]
GROUPS = [(name, [batch]) for name, batch, _ in FIXTURE]


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "games").mkdir()
        rows = []
        for _, batch, games in FIXTURE:
            for seed, ms, cs, winner in games:
                rel = f"games/{batch}-s{seed}.jsonl"
                (self.root / rel).write_text("".join(json.dumps(e) + "\n" for e in log_events(ms, cs, winner=winner)))
                rows.append(index_row(batch, seed, rel, winner))
        # A spoiled game that must be left out.
        rel = "games/alpha-spoiled.jsonl"
        (self.root / rel).write_text("".join(json.dumps(e) + "\n" for e in log_events(99, 0)))
        rows.append(dict(index_row("alpha", 4, rel, "moles"), spoiled=True))
        self.index = self.root / "games" / "index.jsonl"
        self.index.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def tearDown(self):
        self.tmp.cleanup()

    def data(self):
        return bluff_chart.chart_data(self.index, self.root, GROUPS)


class TestGap(Fixture):
    def test_gap_hand_computed(self):
        row = index_row("alpha", 1, "games/alpha-s1.jsonl", "crew")
        g = bluff_score.game(row, str(self.root))
        # 3 crew x 2 moles at 70 and 3 crew x 2 other crew at 30; mole and non-vote suspicion ignored.
        self.assertAlmostEqual(g["gap"], 40.0)
        self.assertEqual((g["g"]["smn"], g["g"]["scn"]), (6, 6))
        self.assertEqual(g["moles"], ["Ash", "Birch"])
        self.assertEqual((g["g"]["crew_votes"], g["g"]["crew_on_mole"]), (3, 2))
        self.assertEqual(g["g"]["moles_alive"], 2)

    def test_uneven_suspicion(self):
        ev = log_events(0, 0)
        for e in ev:
            if e["type"] == "turn" and e["turn_phase"] == "vote" and e["player"] == "Cedar":
                e["action"]["suspicion"] = {"Ash": 90, "Birch": 60, "Dove": 10, "Elm": 20}
        (self.root / "games" / "uneven.jsonl").write_text("".join(json.dumps(e) + "\n" for e in ev))
        g = bluff_score.game({"log": "games/uneven.jsonl"}, str(self.root))
        # moles: 90, 60 (Cedar) + 0 x 4 (Dove, Elm) = 150 / 6; crew: 10, 20 + 0 x 4 = 30 / 6.
        self.assertAlmostEqual(g["gap"], 150 / 6 - 30 / 6)

    def test_summaries_and_draw_order(self):
        res = bluff_score.group_games(bluff_score.load_index(self.index), GROUPS, str(self.root))
        self.assertEqual([len(res[n]) for n, _ in GROUPS], [3, 3])  # spoiled game left out
        s = bluff_score.summaries(res, bluff_score.new_rng(), GROUPS)
        self.assertEqual(s["Alpha 1 moles"]["gaps"], [40.0, 20.0, 0.0])
        self.assertAlmostEqual(s["Alpha 1 moles"]["mean"], 20.0)
        self.assertEqual(s["Alpha 1 moles"]["wins"], 1)
        self.assertEqual(s["Beta 2 moles"]["wins"], 2)
        # The chart draws in the same order as the script, so its intervals are the script's.
        data = self.data()
        by = {r["group"]: r for r in data["rows"]}
        for name, _ in GROUPS:
            self.assertEqual((by[name]["lo"], by[name]["hi"]), (s[name]["lo"], s[name]["hi"]))
            self.assertLessEqual(s[name]["lo"], s[name]["mean"])
            self.assertLessEqual(s[name]["mean"], s[name]["hi"])


class TestChart(Fixture):
    def test_rows_best_liar_first(self):
        data = self.data()
        self.assertEqual([r["name"] for r in data["rows"]], ["Beta 2", "Alpha 1"])
        self.assertAlmostEqual(data["rows"][0]["mean"], (-15 - 10 + 5) / 3)
        self.assertEqual(data["crew"], ["Crew Cedar", "Crew Dove", "Crew Elm"])
        self.assertEqual(data["seeds"], [1, 2, 3])
        self.assertEqual(data["effort"], "low")

    def test_dots_and_wins_text(self):
        svg = bluff_chart.render_svg(self.data())
        tree = ET.fromstring(svg)
        rows = tree.findall(f".//{{{SVG_NS}}}g[@class='row']")
        self.assertEqual([r.get("data-model") for r in rows], ["Beta 2", "Alpha 1"])
        for r, wins in zip(rows, ("moles won 2 of 3", "moles won 1 of 3")):
            self.assertEqual(len(r.findall(f"{{{SVG_NS}}}circle[@class='game']")), 3)
            self.assertEqual(len(r.findall(f"{{{SVG_NS}}}rect[@class='mean']")), 1)
            self.assertEqual(len(r.findall(f"{{{SVG_NS}}}rect[@class='interval']")), 1)
            self.assertEqual(r.find(f"{{{SVG_NS}}}text[@class='wins']").text, wins)
        self.assertEqual(len(tree.findall(f".//{{{SVG_NS}}}circle")), 6)
        self.assertIn("mean +20.0", svg)
        self.assertIn("How suspicious did each model's moles look?", svg)
        self.assertIn("0 = crew suspected the moles no more than each other", svg)

    def test_files_well_formed_and_offline(self):
        out = self.root / "charts"
        svg_path, html_path = bluff_chart.write_chart(out, self.index, self.root, GROUPS)
        root = ET.parse(svg_path).getroot()
        self.assertEqual(root.tag, f"{{{SVG_NS}}}svg")
        self.assertEqual(root.get("viewBox"), "0 0 1600 900")
        html = html_path.read_text()
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertEqual(html.count("<svg"), 1)
        self.assertIn("moles won 2 of 3", html)
        for text in (svg_path.read_text(), html):
            urls = re.findall(r"(?:[a-z][a-z0-9+.-]*:)?//[^\s\"'<>)]+", text, re.I)
            self.assertEqual(set(urls), {SVG_NS}, urls)
            self.assertNotRegex(text, r"(?i)\b(src|href)\s*=|@import|url\(|<script|<link")

    def test_footnote_conditions_from_data(self):
        lines = bluff_chart.footnote_lines(self.data())
        joined = " ".join(lines)
        self.assertIn("Same three-model crew in every game: Crew Cedar, Crew Dove, Crew Elm. Effort low.", joined)
        self.assertIn("3 games per mole model, same seeds (1–3)", joined)
        self.assertIn("bootstrap 95% interval over games", joined)
        self.assertIn("two groups, not a ranking", joined)


if __name__ == "__main__":
    unittest.main()
