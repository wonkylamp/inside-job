"""analysis/finale_chart.py and analysis/media/finale_card.py, read only, no model calls.

The counting is tested on made-up logs (one game per outcome, a crew finale, a game with no finale, an
unfinished game, a spoiled and a re-run index row). Layout and wording are tested on the made-up data
and on the real logs. On the real logs the per-model steals from the counts must agree with
analysis/extra_stats.finale over the same batches, and every quote on the finale card must be an
exact substring of the logged text of its turn."""

import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
sys.path.insert(0, str(ROOT / "analysis" / "media"))

import extra_stats as ES  # noqa: E402
import finale_card as CARD  # noqa: E402
import finale_chart as FCH  # noqa: E402

GAMES = ROOT / "games"
SVG = "{http://www.w3.org/2000/svg}"
BANNED = ("honest", "trustworth", "liar", "cheat", "fooled", "betray", "best", "worst", "Haiku 4.5", "lied")


def _overlap(a, b):
    return a["x0"] < b["x1"] and b["x0"] < a["x1"] and a["y0"] < b["y1"] and b["y0"] < a["y1"]


def write_game(d: Path, gid: str, batch: str, seed: int, model: str, choices=None, crew_finale=False,
               finished=True):
    """A minimal log: game_start, roles, optionally a finale, game_end. Moles are A and B."""
    players = [{"name": n, "model": model if n in ("A", "B") else "claude-crew", "model_name": "M",
                "role": "mole" if n in ("A", "B") else "crew"} for n in ("A", "B", "C", "D")]
    ev = [{"seq": 0, "type": "game_start", "game_id": gid, "seed": seed, "batch": batch, "moles": ["A", "B"],
           "players": players, "config": {"game": {"pot": 100}}}]
    ev += [{"seq": 1 + i, "type": "role", "player": p["name"], "role": p["role"]} for i, p in enumerate(players)]
    if choices:
        fin = ["C", "D"] if crew_finale else ["A", "B"]
        ch = dict(zip(fin, choices))
        pay = {"split": 50, "steal": 100}
        ev.append({"seq": 9, "type": "finale_result", "finalists": fin, "choices": ch,
                   "stated": {p: "split" for p in fin},
                   "payouts": {p: (pay[c] if len(set(choices)) == 1 and c == "split" else
                                   (100 if c == "steal" and "split" in choices else 0)) for p, c in ch.items()}})
    if finished:
        ev.append({"seq": 10, "type": "game_end", "winner": "crew" if crew_finale else "moles"})
    log = d / f"{gid}.jsonl"
    log.write_text("".join(json.dumps(e) + "\n" for e in ev))
    return {"game_id": gid, "batch": batch, "seed": seed, "log": str(log), "players": players}


def fixture_dir(tmp: Path) -> Path:
    rows = [
        write_game(tmp, "g1", "bx", 1, "m/x", ["split", "split"]),
        write_game(tmp, "g2", "bx", 2, "m/x", ["split", "steal"]),
        write_game(tmp, "g3", "bx", 3, "m/x", ["steal", "steal"]),
        write_game(tmp, "g4", "bx", 4, "m/x", ["steal", "split"]),
        write_game(tmp, "g5", "bx", 5, "m/x", ["split", "split"], crew_finale=True),   # crew finale: not counted
        write_game(tmp, "g6", "bx", 6, "m/x"),                                         # no finale
        write_game(tmp, "g7", "bx", 7, "m/x", ["steal", "steal"], finished=False),      # unfinished: not counted
        write_game(tmp, "g8", "by", 1, "m/y", ["steal", "steal"]),
        write_game(tmp, "g9", "bz", 1, "m/z"),                                         # a model with no finale
    ]
    spoiled = dict(write_game(tmp, "g10", "by", 2, "m/y", ["split", "split"]), spoiled=True)
    old = write_game(tmp, "g11", "by", 3, "m/y", ["split", "split"])                   # re-run below: old row dropped
    rerun = write_game(tmp, "g12", "by", 3, "m/y", ["steal", "steal"])
    with open(tmp / "index.jsonl", "w") as f:
        for r in rows + [spoiled, old, rerun]:
            f.write(json.dumps(r) + "\n")
    return tmp


GROUPS = [("X", ["bx"]), ("Y", ["by"]), ("Z", ["bz"])]


class TestCounting(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.dir = fixture_dir(Path(self._t.name))

    def tearDown(self):
        self._t.cleanup()

    def test_outcome_of(self):
        self.assertEqual(FCH.outcome_of({"a": "split", "b": "split"}), "both_split")
        self.assertEqual(FCH.outcome_of({"a": "steal", "b": "split"}), "one_stole")
        self.assertEqual(FCH.outcome_of({"a": "split", "b": "steal"}), "one_stole")
        self.assertEqual(FCH.outcome_of({"a": "steal", "b": "steal"}), "both_stole")

    def test_counts_each_outcome_and_skips_the_rest(self):
        rows = {r["name"]: r for r in FCH.count_finales(self.dir, GROUPS)}
        x = rows["X"]
        self.assertEqual((x["both_split"], x["one_stole"], x["both_stole"], x["total"]), (1, 2, 1, 4))
        self.assertEqual(x["games"], 6)          # g7 is unfinished
        y = rows["Y"]                            # g8 and the re-run g12; spoiled g10 and replaced g11 dropped
        self.assertEqual((y["both_split"], y["one_stole"], y["both_stole"], y["total"]), (0, 0, 2, 2))
        self.assertEqual(rows["Z"]["total"], 0)

    def test_steals_by_model(self):
        data = FCH.count_finales(self.dir, GROUPS)
        self.assertEqual(FCH.steals_by_model(data), {"m/x": (8, 4), "m/y": (4, 4)})

    def test_drawing_on_fixture(self):
        data = {"rows": FCH.count_finales(self.dir, GROUPS), "pot": 100, "same_model": True}
        cv, h = FCH.layout(data)
        self.assertEqual(h, FCH.H)
        self.assertNotIn("Z", [b["text"] for b in cv.boxes if b["cls"] == "name"])   # no finale: not drawn
        self.assertIn("Z: no finale (1 game)", FCH.alt_text(data))
        for b in cv.boxes:
            self.assertGreaterEqual(b["size"], 30, b["text"])
        ET.fromstring(FCH.render_svg(data))


class TestRealChart(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = FCH.chart_data(GAMES)
        cls.rows = {r["name"]: r for r in cls.data["rows"]}

    def test_models_and_neutral_order(self):
        self.assertEqual([r["name"] for r in self.data["rows"]],
                         ["Fable 5.2", "Opus 5.5", "Sonnet 5.5", "Haiku 5.5", "DeepSeek V4 Pro", "Gemini 4 Carbon",
                          "Grok 4.7", "Kimi K3.1 Pro"])
        self.assertEqual({n: b for n, b in FCH.GROUPS}, {n: b for n, b in ES.GROUPS})

    def test_the_three_known_counts(self):
        r = self.rows
        self.assertEqual((r["Grok 4.7"]["both_stole"], r["Grok 4.7"]["total"]), (3, 3))
        self.assertEqual((r["Gemini 4 Carbon"]["both_stole"], r["Gemini 4 Carbon"]["total"]), (3, 3))
        self.assertEqual((r["Fable 5.2"]["both_split"], r["Fable 5.2"]["total"]), (6, 6))

    def test_every_finalist_faced_its_own_model(self):
        self.assertTrue(self.data["same_model"])
        self.assertEqual(self.data["pot"], 100)

    def test_steals_agree_with_extra_stats(self):
        batches = {b for _n, bs in FCH.GROUPS for b in bs}
        rows = [r for r in ES.index_rows(GAMES / "index.jsonl") if r.get("batch") in batches]
        by = ES.finale(rows)
        ours = FCH.steals_by_model(self.data["rows"])
        theirs = {m: (c["finals"], c["steals"]) for (m, role), c in by.items() if role == "mole"}
        self.assertEqual(ours, theirs)

    def test_layout_fits_with_no_overlap_and_large_text(self):
        cv, h = FCH.layout(self.data)
        self.assertEqual(h, FCH.H)
        for b in cv.boxes:
            self.assertGreaterEqual(b["size"], 30, b["text"])
            self.assertGreaterEqual(b["x0"], FCH.M - 1, b["text"])
            self.assertLessEqual(b["x1"], FCH.W - FCH.M + 1, b["text"])
        for i, a in enumerate(cv.boxes):
            for b in cv.boxes[i + 1:]:
                self.assertFalse(_overlap(a, b), (a["text"], b["text"]))

    def test_every_segment_is_labelled_in_words(self):
        cv, _h = FCH.layout(self.data)
        words = [b["text"] for b in cv.boxes if b["cls"] == "seg-word"]
        n_segs = sum(len(FCH.segments(r)) for r in FCH.drawn(self.data))
        self.assertEqual(len(words), n_segs)
        self.assertIn("6 of 6", [b["text"] for b in cv.boxes if b["cls"] == "seg-count"])

    def test_wording(self):
        svg = FCH.render_svg(self.data)
        alt = FCH.alt_text(self.data)
        for s in ("Small counts. Not a planned test.", "Each finalist faced a copy of itself."):
            self.assertIn(s, svg)
            self.assertIn(s, alt)
        for w in BANNED:
            self.assertNotIn(w.lower(), svg.lower(), w)
            self.assertNotIn(w.lower(), alt.lower(), w)
        self.assertLessEqual(len(alt), 1000)
        self.assertIn("DeepSeek V4 Pro (reasoning off): no finale", alt)
        self.assertNotIn("DeepSeek", "".join(b["text"] for b in FCH.layout(self.data)[0].boxes))

    def test_files_are_current(self):
        svg = (ROOT / "docs/charts/finale.svg").read_text()
        self.assertEqual(svg, '<?xml version="1.0" encoding="UTF-8"?>\n' + FCH.render_svg(self.data))
        self.assertEqual((ROOT / "docs/charts/finale_alt.txt").read_text().strip(), FCH.alt_text(self.data))


class TestFinaleCard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = CARD.check()
        cls.events = CARD.load()

    def test_facts(self):
        c = self.ctx
        self.assertEqual((c["seed"], c["batch"], c["model"], c["model_id"]), (107, "bluff_grok47", "Grok 4.7", "x-ai/grok-4.7"))
        self.assertEqual(c["finalists"], ["Quill", "Cipher"])
        self.assertEqual(c["stated"], {"Quill": "split", "Cipher": "split"})
        self.assertEqual(c["choices"], {"Quill": "steal", "Cipher": "steal"})
        self.assertEqual(c["payouts"], {"Quill": 0, "Cipher": 0})
        self.assertEqual(c["pot"], 100)

    def test_every_quote_on_the_card_is_verbatim(self):
        root = ET.fromstring((ROOT / "docs/media/finale_card.svg").read_text())
        quotes = [t for t in root.iter(f"{SVG}text") if t.get("class") == "quote"]
        self.assertEqual(len(quotes), len(CARD.QUOTES))
        spec = {q["key"]: q for q in CARD.QUOTES}
        for t in quotes:
            q = spec[t.get("data-key")]
            logged = CARD.turn(self.events, q["player"], q["phase"])[q["field"]]
            shown = " ".join(ts.text for ts in t.iter(f"{SVG}tspan"))
            pieces = shown.split(CARD.ELLIPSIS)
            for piece in pieces:
                self.assertIn(piece, logged, (q["key"], piece))
                # whole sentences only: each piece starts and ends on a sentence boundary
                self.assertTrue(piece[-1] in ".!?", piece)
                self.assertTrue(logged.startswith(piece) or (". " + piece) in logged or ("? " + piece) in logged
                                or ("! " + piece) in logged, piece)

    def test_quotes_and_seqs(self):
        q = {x["key"]: x for x in self.ctx["quotes"]}
        self.assertEqual(q["quill_said"]["text"], "I'm splitting. You should too. … I won't steal.")
        self.assertEqual(q["quill_wrote"]["text"],
                         "I'll promise a split so they trust me and split, then I'll steal for the full hundred.")
        self.assertEqual(q["cipher_said"]["text"],
                         "Fifty is the smart cut and I am splitting too. We finish this as partners, not as a coin flip to zero.")
        self.assertTrue(q["cipher_wrote"]["text"].endswith("I will promise split and take it when the choice opens."))
        self.assertEqual({k: v["seq"] for k, v in q.items()},
                         {"quill_said": 96, "quill_wrote": 96, "cipher_said": 97, "cipher_wrote": 97})

    def test_pick_refuses_a_sentence_that_is_not_there(self):
        with self.assertRaises(IndexError):
            CARD.pick(self.events, dict(CARD.QUOTES[0], sentences=[[40]]))

    def test_card_text_size_and_footer(self):
        svg = (ROOT / "docs/media/finale_card.svg").read_text()
        root = ET.fromstring(svg)
        sizes = [float(t.get("font-size")) for t in root.iter(f"{SVG}text") if t.get("font-size")]
        self.assertGreaterEqual(min(sizes), 30)
        self.assertIn("Inside Job · game seed 107 · quotes verbatim from the game log", svg)
        self.assertEqual(svg.count("Grok 4.7"), 3)          # the headline and both speakers
        self.assertIn("Both stole. Both got nothing.", svg)
        self.assertEqual(svg, CARD.card_svg(self.ctx))       # the file on disk is the current build
        for w in BANNED:
            self.assertNotIn(w.lower(), svg.lower(), w)

    def test_clip_frames_never_move_the_layout(self):
        import finale_clip as CLIP
        tl = CLIP.timeline()
        start = CARD.STEPS.index(CLIP.FIRST)
        self.assertEqual({s for s, _f, _n in tl}, set(range(start, len(CARD.STEPS))))
        self.assertEqual([s for s, _f, _n in tl], sorted(s for s, _f, _n in tl))   # steps only go forward
        total = sum(n for _s, _f, n in tl) / CLIP.FPS
        self.assertTrue(12 <= total <= 20, total)
        # frame 0 (the still shown before the clip plays) is a whole picture with the first promise on
        # it, not the empty card; every quote is on the final frame
        self.assertEqual(CLIP.FIRST, "quill_said")
        self.assertEqual(tl[0][:2], (start, 1.0))
        first, last = CARD.card_svg(self.ctx, *tl[0][:2]), CARD.card_svg(self.ctx, *tl[-1][:2])
        self.assertEqual(CARD.card_svg(self.ctx, 0, 1.0).count('class="quote"'), 0)
        self.assertEqual(first.count('class="quote"'), 1)
        self.assertNotIn("Both stole", first)                # the result is not given away on frame 0
        self.assertNotIn('class="cell wrote"', first)        # nor is either private note
        self.assertEqual(last.count('class="quote"'), 4)
        self.assertEqual(tl[-1][:2], (len(CARD.STEPS) - 1, 1.0))


if __name__ == "__main__":
    unittest.main()
