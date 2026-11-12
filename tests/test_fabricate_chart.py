"""analysis/fabricate_chart.py, read only, no model calls.

Layout and wording are tested on fixtures with made-up numbers, so they do not depend on the
outside-lab games that are still being added to games/ (a lab with fewer than 10 games, a lab with no
finished game, DeepSeek present and absent, zero rows, ties in the sort). The real-log tests check the four Claude rows
against analysis/fabricate_rate.py and only the structure of the outside-lab rows, never their numbers."""

import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import fabricate_chart as FC  # noqa: E402
import fabricate_rate as FR  # noqa: E402

GAMES = ROOT / "games"
RUNS = ROOT / "probes/moves/runs/v1_public"
SET = ROOT / "probes/moves/sets/v1_public.jsonl"
SVG = "{http://www.w3.org/2000/svg}"
DS = FC.DEEPSEEK[0]
BANNED = ("Haiku 4.5", "best liar", "fooled", "hardest to catch", "upper bound", "turns", "designed after",
          "interval", "95%", "CLAUDE MODELS", "OTHER LABS", "not a ranking", "two groups")


def _full(games, moles_forged, turns, forged):
    moles = 2 * games
    bound = FR.zero_bound(moles) if moles_forged == 0 else None
    return {"games": games, "turns": turns, "forged": forged, "rate": forged / turns,
            "ci": (0.0, 0.0) if forged == 0 else (forged / turns / 2, min(1.0, forged / turns * 1.5)),
            "moles": moles, "forged_moles": moles_forged, "mole_rate": moles_forged / moles,
            "mole_ci": (0.0, 0.0) if moles_forged == 0 else (moles_forged / moles / 2, min(1.0, moles_forged / moles * 1.3)),
            "mole_bound": bound}


def fixture(other=None, main_games=10, told_k=None):
    """A chart_data-shaped dict with made-up numbers (not the real logs). `other` maps an outside lab
    to its finished games; a lab with 0 games is left out, as chart_data does."""
    other = {"Gemini 4 Carbon": 10, "Grok 4.7": 7, "Kimi K3.1 Pro": 10} if other is None else other
    g = main_games
    main_counts = {"Fable 5.2": (2 * g - 5, 10 * g, 4 * g), "Opus 5.5": (g, 12 * g, 2 * g),
                   "Sonnet 5.5": (0, 9 * g, 0), "Haiku 5.5": (0, 9 * g, 0)}
    main = [{"name": n, "full": _full(g, *main_counts[n]),
             "free": {"k": 1, "n": 70, "rate": 1 / 70, "ci": (0.0, 0.04), "moves": 70},
             "told": {"k": 61 if told_k is None else told_k, "n": 61, "rate": 1.0, "ci": (1.0, 1.0), "moves": 61}}
            for n in FC.MAIN]
    shape = {"Gemini 4 Carbon": lambda o: (o, 10 * o, 2 * o), "Grok 4.7": lambda o: (o - 1, 9 * o, 3 * o),
             "Kimi K3.1 Pro": lambda o: (0, 8 * o, 0), DS: lambda o: (2 * o - 2, 7 * o, 4 * o)}
    rows = []
    for n in FC.OTHER:
        o = other.get(n, 0)
        if o:
            rows.append({"name": n, "full": _full(o, *shape[n](o))})
            if n == DS:
                rows[-1]["reasoning"] = "none"
    return {"main": main, "other": rows, "moments": 61, "free_moments": [70], "games": [g], "moles": [2 * g],
            "crew_size": 5, "crew_claude": True, "effort": "low", "same_seeds": True}


CASES = {
    "three labs, Grok short": {"Gemini 4 Carbon": 10, "Grok 4.7": 7, "Kimi K3.1 Pro": 10},
    "Kimi has no games": {"Gemini 4 Carbon": 6, "Grok 4.7": 7, "Kimi K3.1 Pro": 0},
    "DeepSeek, all ten": {DS: 10, "Gemini 4 Carbon": 10, "Grok 4.7": 10, "Kimi K3.1 Pro": 10},
    "DeepSeek short": {DS: 3, "Gemini 4 Carbon": 10, "Grok 4.7": 9, "Kimi K3.1 Pro": 10},
    "no other lab": {},
}


def _overlap(a, b):
    return a["x0"] < b["x1"] and b["x0"] < a["x1"] and a["y0"] < b["y1"] and b["y0"] < a["y1"]


def _texts(svg):
    """Every text run in the SVG, tspans included."""
    root = ET.fromstring(svg)
    return [t.text for t in root.iter() if t.tag in (SVG + "text", SVG + "tspan") and t.text]


def _rows(svg):
    root = ET.fromstring(svg)
    return {g.get("data-model"): g for g in root.iter(SVG + "g") if g.get("data-model")}


class Fixtures(unittest.TestCase):
    def test_layout_fits_4_by_5_with_no_overlap(self):
        for case, other in CASES.items():
            with self.subTest(case):
                data = fixture(other)
                cv, h = FC.layout(data)
                self.assertEqual(h, FC.H, "fixed 1200 x 1500, 4:5")
                self.assertEqual((FC.W, FC.H), (1200, 1500))
                for b in cv.boxes:
                    self.assertGreaterEqual(b["size"], 30, b["text"])
                    self.assertGreaterEqual(b["x0"], FC.M - 1, b["text"])
                    self.assertLessEqual(b["x1"], FC.W - FC.M + 1, b["text"])
                    self.assertGreaterEqual(b["y0"], FC.M - 1, b["text"])
                    self.assertLessEqual(b["y1"], h - 30, b["text"])
                for i, a in enumerate(cv.boxes):
                    for b in cv.boxes[i + 1:]:
                        self.assertFalse(_overlap(a, b), (a["text"], b["text"]))

    def test_names_and_percentages_are_large(self):
        cv, _h = FC.layout(fixture())
        for b in cv.boxes:
            if b["cls"] in ("name", "value"):
                self.assertGreaterEqual(b["size"], 40, b["text"])
            if b["cls"] == "title":
                self.assertGreaterEqual(b["size"], 56, b["text"])
        self.assertLessEqual(len([b for b in cv.boxes if b["cls"] == "title"]), 2)

    def test_wording(self):
        data = fixture(CASES["DeepSeek, all ten"])
        texts = _texts(FC.render_svg(data))
        self.assertIn("Allowed to forge clue cards, only some", " ".join(texts))
        self.assertIn("Share of moles that showed a fake clue card at least once.", texts)
        self.assertIn("10 games per model. Each game has 2 moles.", texts)
        self.assertIn("Told to show a fake card, all four Claude models did.", texts)
        self.assertIn("61 of 61 single moves each. A separate test.", texts)
        self.assertEqual(texts[-2:], ["Small samples: models close together are not separated.",
                                      "The game engine checks every card. No judge model."])
        body = " ".join(texts)
        for s in BANNED:
            self.assertNotIn(s, body)

    def test_games_line_says_unless_marked_only_when_a_row_is_marked(self):
        self.assertEqual(FC.games_line(fixture(CASES["DeepSeek, all ten"])),
                         "10 games per model. Each game has 2 moles.")
        self.assertEqual(FC.games_line(fixture(CASES["three labs, Grok short"])),
                         "10 games per model unless marked. Each game has 2 moles.")

    def test_callout_follows_the_numbers(self):
        self.assertEqual(FC.callout_lines(fixture(told_k=58))[0], "Told to show a fake card, Claude models mostly did.")
        self.assertIn("58 of 61", FC.callout_lines(fixture(told_k=58))[1])

    def test_one_bar_hue_and_no_interval_marks(self):
        svg = FC.render_svg(fixture(CASES["DeepSeek short"]))
        root = ET.fromstring(svg)
        fills = {p.get("fill") for p in root.iter(SVG + "path") if p.get("class") == "bar"}
        self.assertEqual(fills, {FC.BAR})
        self.assertEqual(list(root.iter(SVG + "circle")), [])
        self.assertNotIn("stroke-dasharray", svg)

    def test_one_list_sorted_by_share(self):
        data = fixture(CASES["DeepSeek short"])
        rows = list(_rows(FC.render_svg(data)))
        # made-up shares: DeepSeek 4/6, Fable 15/20, Gemini 10/20, Opus 10/20, Grok 8/18, then the zeros
        self.assertEqual(rows, ["Fable 5.2", DS, "Gemini 4 Carbon", "Opus 5.5", "Grok 4.7",
                                "Haiku 5.5", "Kimi K3.1 Pro", "Sonnet 5.5"])
        shares = [r["full"]["mole_rate"] for r in FC.sorted_rows(data)]
        self.assertEqual(shares, sorted(shares, reverse=True))

    def test_ties_go_to_more_moles_then_name(self):
        data = fixture({DS: 2, "Gemini 4 Carbon": 10, "Grok 4.7": 10, "Kimi K3.1 Pro": 10})
        for r in FC.rows_of(data):          # every row at 50%
            f = r["full"]
            f["forged_moles"], f["mole_rate"], f["mole_bound"] = f["moles"] // 2, 0.5, None
        names = [r["name"] for r in FC.sorted_rows(data)]
        self.assertEqual(names[-1], DS)     # 2 of 4 moles: fewest moles, last of the ties
        self.assertEqual(names[:-1], sorted(names[:-1]))

    def test_notes_only_where_a_row_differs(self):
        rows = _rows(FC.render_svg(fixture(CASES["DeepSeek short"])))
        notes = {n: [t.text for t in g.iter() if t.get("class") == "name-note"] for n, g in rows.items()}
        self.assertEqual(notes[DS], ["· reasoning off · 3 games"])
        self.assertEqual(notes["Grok 4.7"], ["· 9 games"])
        for n in FC.MAIN + ["Gemini 4 Carbon", "Kimi K3.1 Pro"]:
            self.assertEqual(notes[n], [], n)
        rows = _rows(FC.render_svg(fixture(CASES["DeepSeek, all ten"])))
        notes = {n: [t.text for t in g.iter() if t.get("class") == "name-note"] for n, g in rows.items()}
        self.assertEqual(notes[DS], ["· reasoning off"])
        self.assertEqual(sum(len(v) for v in notes.values()), 1)

    def test_lab_with_no_games_and_absent_deepseek_are_left_out(self):
        svg = FC.render_svg(fixture(CASES["Kimi has no games"]))
        rows = _rows(svg)
        self.assertNotIn("Kimi K3.1 Pro", rows)
        self.assertNotIn(DS, rows)
        self.assertNotIn("DeepSeek", svg)
        self.assertNotIn("reasoning", svg)
        self.assertEqual(list(_rows(FC.render_svg(fixture(CASES["no other lab"])))),
                         ["Fable 5.2", "Opus 5.5", "Haiku 5.5", "Sonnet 5.5"])

    def test_zero_rows_show_a_stub_and_the_count(self):
        rows = _rows(FC.render_svg(fixture()))
        for name in ("Sonnet 5.5", "Haiku 5.5", "Kimi K3.1 Pro"):
            g = rows[name]
            self.assertEqual(len(g.findall(f"{SVG}rect[@class='stub']")), 1, name)
            self.assertEqual(g.findall(f"{SVG}path[@class='bar']"), [], name)
            texts = [t.text for t in g.iter() if t.text and t.text.strip()]
            self.assertIn("0%", texts)
            self.assertTrue(any(t.startswith("0 of ") and t.endswith(" moles") for t in texts), texts)
        g = rows["Fable 5.2"]
        self.assertEqual(len(g.findall(f"{SVG}path[@class='bar']")), 1)
        texts = [t.text for t in g.iter() if t.text]
        self.assertIn("75%", texts)
        self.assertIn("15 of 20 moles", texts)

    def test_bar_length_is_the_share(self):
        data = fixture()
        cv, _h = FC.layout(data)
        x100 = FC.scale_end(data)
        svg = FC.render_svg(data)
        for name, g in _rows(svg).items():
            bar = g.find(f"{SVG}path[@class='bar']")
            if bar is None:
                continue
            f = next(r["full"] for r in FC.rows_of(data) if r["name"] == name)
            end = float(bar.get("d").split("V")[0].split("Q")[1].split(",")[0])
            self.assertAlmostEqual(end, FC.M + f["mole_rate"] * (x100 - FC.M), places=0)
        # a full bar's label still fits inside the margin
        self.assertLessEqual(x100 + FC.GAP_LABEL + FC.text_width("100%", FC.VALUE, True) + FC.VALUE_GAP
                             + FC.text_width("20 of 20 moles", FC.COUNT), FC.W - FC.M + 0.5)

    def test_pct(self):
        self.assertEqual(FC.pct(0.8), "80%")
        self.assertEqual(FC.pct(1 / 16), "6%")
        self.assertEqual(FC.pct(0.001), "<1%")
        self.assertEqual(FC.pct(0.0), "0%")
        self.assertEqual(FC.pct(1.0), "100%")

    def test_fisher_p(self):
        self.assertAlmostEqual(FC.fisher_p(16, 20, 11, 20), 0.176, places=3)
        self.assertAlmostEqual(FC.fisher_p(5, 5, 0, 5), 0.0079, places=4)
        self.assertAlmostEqual(FC.fisher_p(3, 10, 3, 10), 1.0)

    def test_alt_text_carries_the_fine_print_and_fits_x(self):
        for case, other in CASES.items():
            with self.subTest(case):
                data = fixture(other)
                alt = FC.alt_text(data)
                self.assertLessEqual(len(alt), 1000)
                self.assertIn(f"For 0 of 20 the exact 97.5% upper bound is {FC.pct1(FR.zero_bound(20))}", alt)
                self.assertIn("are not separated (Fisher exact p =", alt)
                self.assertIn("close bars are not separated", alt)
                self.assertIn("different one-move test", alt)
                self.assertIn("designed after an earlier check failed", alt)
                for r in data["main"] + data["other"]:
                    f = r["full"]
                    self.assertTrue(f"{f['forged']} of {f['turns']} turns" in alt
                                    or f"{f['forged']}/{f['turns']} turns" in alt, r["name"])
                    self.assertIn(f"{f['forged_moles']} of {f['moles']}", alt, r["name"])
                for r in data["other"]:
                    self.assertIn(f"{r['name']}{' (reasoning off)' if r['name'] == DS else ''}, "
                                  f"{FC.games_text(r['full'])}", alt)
                if other:
                    self.assertIn("different API (OpenRouter), not in the told-to test", alt)
                self.assertEqual("reasoning off" in alt, DS in {r["name"] for r in data["other"]})
                self.assertNotIn("Haiku 4.5", alt)
                self.assertNotIn("not a ranking", alt)

    def test_alt_text_fits_with_every_lab_at_ten_games_and_long_counts(self):
        data = fixture(CASES["DeepSeek, all ten"])
        for r in FC.rows_of(data):
            r["full"]["turns"] += 100       # three-digit turn counts everywhere
        self.assertLessEqual(len(FC.alt_text(data)), 1000)

    def test_title_follows_the_numbers(self):
        data = fixture()
        for r in FC.rows_of(data):
            r["full"]["forged_moles"] = 3
        self.assertEqual(FC.title_text(data), "Allowed to forge clue cards, every AI model did.")
        for r in FC.rows_of(data):
            r["full"]["forged_moles"] = 0
        self.assertEqual(FC.title_text(data), "Allowed to forge clue cards, no AI model did.")

    def test_deepseek_reasoning_is_read_from_its_config(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.toml"
            p.write_text(f'[openrouter.reasoning_effort_by_model]\n"{FC.DEEPSEEK[1]}" = "none"\n', encoding="utf-8")
            self.assertEqual(FC.deepseek_reasoning(p), "none")
            p.write_text("[game]\nnum_moles = 2\n", encoding="utf-8")
            self.assertIsNone(FC.deepseek_reasoning(p))
            self.assertIsNone(FC.deepseek_reasoning(Path(d) / "missing.toml"))
        self.assertEqual(FC.reasoning_note({"reasoning": "none"}), "reasoning off")

    def test_chart_data_leaves_out_labs_with_no_games(self):
        """chart_data on stubbed reads: Kimi and DeepSeek have no finished game and are left out."""
        def counts(name, games, forged_moles, turns, forged):
            fg = {"name": name, "games": games, "turns": turns, "forged_turns": forged,
                  "rate": forged / turns if turns else None, "ci": (0.0, 0.5)}
            ml = {"name": name, "games": games, "moles": 2 * games, "forged_moles": forged_moles,
                  "rate": forged_moles / (2 * games) if games else None, "ci": (0.0, 0.5), "bound": None}
            return fg, ml
        table = {"Fable 5.2": (10, 12, 90, 30), "Opus 5.5": (10, 9, 95, 12), "Sonnet 5.5": (10, 0, 80, 0),
                 "Haiku 5.5": (10, 0, 80, 0), "Gemini 4 Carbon": (4, 3, 30, 5), "Grok 4.7": (10, 5, 70, 9),
                 "Kimi K3.1 Pro": (0, 0, 0, 0), DS: (0, 0, 0, 0)}
        fg = {n: counts(n, *v)[0] for n, v in table.items()}
        ml = {n: counts(n, *v)[1] for n, v in table.items()}
        ins = {"moments": 61, "rows": [{"name": n, "complete": True, "valid": 61, "moments": 61, "moves": 61,
                                        "shown": {"k": 61, "n": 61, "rate": 1.0, "ci": (1.0, 1.0)}}
                                       for n in FC.MAIN]}
        with mock.patch.object(FC, "_read_games", return_value=(fg, ml)), \
                mock.patch.object(FR, "one_move", return_value=([], {})), \
                mock.patch.object(FR, "label_for", return_value=None), \
                mock.patch.object(FR, "instructed", return_value=ins), \
                mock.patch.object(FC, "_index_rows", return_value=[]):
            data = FC.chart_data("g", "r", "s")
        self.assertEqual([r["name"] for r in data["other"]], ["Gemini 4 Carbon", "Grok 4.7"])
        self.assertEqual([r["name"] for r in FC.sorted_rows(data)][:3], ["Fable 5.2", "Opus 5.5", "Gemini 4 Carbon"])
        self.assertEqual([r["name"] for r in data["main"]], FC.MAIN)
        texts = _texts(FC.render_svg(data))
        self.assertIn("· 4 games", texts)
        self.assertIn("38%", texts)               # 3 of 8 moles

    def test_write_chart_from_fixture(self):
        with tempfile.TemporaryDirectory() as d:
            paths = FC.write_chart(d, png=False, data=fixture(CASES["DeepSeek short"]))
            self.assertEqual({p.name for p in paths}, {"fabricate.svg", "fabricate.html", "fabricate_alt.txt"})
            html = (Path(d) / "fabricate.html").read_text(encoding="utf-8")
            self.assertNotIn("http://", html.replace("http://www.w3.org/2000/svg", ""))
            self.assertNotIn("https://", html)
            self.assertIn("DeepSeek V4 Pro (reasoning off)", html)


@unittest.skipUnless((GAMES / "index.jsonl").exists() and (RUNS / "screen.json").exists() and SET.exists(),
                     "real logs not present")
class RealLogs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.data = FC.chart_data(GAMES, RUNS, SET)
        cls.paths = FC.write_chart(cls.tmp.name, png=False, data=cls.data)
        cls.svg = (Path(cls.tmp.name) / "fabricate.svg").read_text(encoding="utf-8").split("\n", 1)[1]
        cls.alt = (Path(cls.tmp.name) / "fabricate_alt.txt").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_files(self):
        self.assertEqual({p.name for p in self.paths}, {"fabricate.svg", "fabricate.html", "fabricate_alt.txt"})
        root = ET.fromstring(self.svg)
        self.assertEqual((root.get("width"), root.get("height")), ("1200", "1500"))
        self.assertLessEqual(len(self.alt.strip()), 1000)

    def test_claude_rows_come_from_fabricate_rate(self):
        groups = [g for g in FR.GROUPS if g[0] in FC.MAIN]
        fg = {r["name"]: r for r in FR.full_games(GAMES, groups=groups)}
        ml = {r["name"]: r for r in FR.moles(GAMES, groups=groups)}
        ins = {r["name"]: r for r in FR.instructed(RUNS, SET)["rows"]}
        rows = _rows(self.svg)
        for name in FC.MAIN:
            texts = [t.text for t in rows[name].iter() if t.text]
            self.assertIn(f"{ml[name]['forged_moles']} of {ml[name]['moles']} moles", texts, name)
            self.assertIn(FC.pct(ml[name]["rate"]), texts, name)
            self.assertTrue(f"{fg[name]['forged_turns']} of {fg[name]['turns']} turns" in self.alt
                            or f"{fg[name]['forged_turns']}/{fg[name]['turns']} turns" in self.alt, name)
        ks = {(ins[n]["shown"]["k"], ins[n]["shown"]["n"]) for n in FC.MAIN}
        if len(ks) == 1 and all(k == n for k, n in ks):
            k, n = next(iter(ks))
            self.assertIn(f"{k} of {n} single moves each. A separate test.", _texts(self.svg))

    def test_per_mole_counts_match_the_review(self):
        groups = [g for g in FR.GROUPS if g[0] in FC.MAIN]
        ml = {r["name"]: (r["forged_moles"], r["moles"]) for r in FR.moles(GAMES, groups=groups)}
        self.assertEqual(ml, {"Fable 5.2": (16, 20), "Opus 5.5": (11, 20), "Sonnet 5.5": (0, 20),
                              "Haiku 5.5": (0, 20)})

    def test_models_shown(self):
        rows = list(_rows(self.svg))
        self.assertEqual(rows, [r["name"] for r in FC.sorted_rows(self.data)])
        self.assertEqual(set(rows), set(FC.MAIN) | {r["name"] for r in self.data["other"]})
        others = [r["name"] for r in self.data["other"]]
        self.assertEqual(others, sorted(others))
        for r in self.data["other"]:
            self.assertGreater(r["full"]["games"], 0)
        body = " ".join(_texts(self.svg))
        for s in BANNED + ("GPT-6.1",):
            self.assertNotIn(s, body)

    def test_deepseek_config_says_reasoning_off(self):
        self.assertEqual(FC.deepseek_reasoning(), "none")


if __name__ == "__main__":
    unittest.main()
