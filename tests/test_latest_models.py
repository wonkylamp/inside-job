"""analysis/latest_models.py on synthetic games, plus one read-only check against the real logs.

Every fixture is written to a temp directory. Only TestRealGroups reads games/ (read-only), and it
skips when the index or any of its logs is missing.
"""

import io
import json
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
ANALYSIS = PROJECT / "analysis"
for _p in (str(PROJECT), str(ANALYSIS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import bluff_score  # noqa: E402
import latest_models as lm  # noqa: E402

SVG_NS = "http://www.w3.org/2000/svg"
MOLES = ("Ash", "Birch")
CREW = ("Cedar", "Dove", "Elm", "Fern", "Gale")
CREW_MODELS = (("claude-haiku-4-5", "Haiku 4.5"), ("claude-haiku-5-5", "Haiku 5.5"),
               ("claude-sonnet-4-5", "Sonnet 4.5"), ("claude-sonnet-4-6", "Sonnet 4.6"),
               ("claude-sonnet-5", "Sonnet 5"))
CLAUDE_STAMP = "0800d943" + "a" * 56
OUTSIDE_STAMP = "5eedf00d" + "b" * 56

# group name -> (batch, mole model id, mole model display name, offset added to the mole rating)
SPEC = {
    "Fable 5.2 moles": ("bluff_fable52", "claude-fable-5-2", "Fable 5.2", -8),
    "Opus 5.5 moles": ("bluff_opus55", "claude-opus-5-5", "Opus 5.5", 14),
    "Sonnet 5.5 moles": ("bluff_sonnet55", "claude-sonnet-5-5", "Sonnet 5.5", 6),
    "Haiku 5.5 moles": ("bluff_haiku55", "claude-haiku-5-5", "Haiku 5.5", 10),
    "Grok 4.7 moles": ("bluff_grok47", "x-ai/grok-4.7", "Grok 4.7", 2),
    "Kimi K3.1 Pro moles": ("bluff_kimi", "moonshotai/kimi-k3.1-pro", "Kimi K3.1 Pro", -2),
    "Gemini 4 Carbon moles": ("bluff_gemini", "google/gemini-4-carbon", "Gemini 4 Carbon", 22),
    "GPT-6.1 Sol moles": ("bluff_sol", "openai/gpt-6.1-sol", "GPT-6.1 Sol", -14),
    "Haiku 4.5 moles": ("bluff_haiku45", "claude-haiku-4-5", "Haiku 4.5", 16),
}


def mole_rating(group, seed):
    return 40 + SPEC[group][3] + (seed * 7) % 11


def players_for(group):
    _, mid, mname, _ = SPEC[group]
    ps = [{"name": m, "model": mid, "model_name": f"{mname} {'AB'[i]}", "role": "mole", "seat": i}
          for i, m in enumerate(MOLES)]
    for i, (c, (cid, cname)) in enumerate(zip(CREW, CREW_MODELS)):
        same = cid == mid
        ps.append({"name": c, "model": cid, "model_name": cname + (" C" if same else ""), "role": "crew",
                   "seat": i + 2})
    return ps


def log_events(group, seed, *, mole_turns=20, fallbacks=0, winner="crew", stamp=CLAUDE_STAMP):
    """A small 7-player game. Each crew vote turn rates every mole mole_rating and every other crew
    member 40, so the gap is mole_rating - 40. Mole seats take mole_turns turns, the first
    `fallbacks` of them fallbacks (after three failed attempts)."""
    ms = mole_rating(group, seed)
    ev = [{"type": "game_start", "seed": seed, "players": players_for(group), "code_hash": stamp}]
    ev += [{"type": "role", "player": p, "role": "mole"} for p in MOLES]
    ev += [{"type": "role", "player": p, "role": "crew"} for p in CREW]
    ev.append({"type": "round_start", "alive": list(MOLES + CREW)})
    for k in range(mole_turns):
        fb = k < fallbacks
        ev.append({"type": "turn", "player": MOLES[k % 2], "model": SPEC[group][1], "turn_phase": "discuss",
                   "public": "" if fb else "I was on a clean job.", "fallback": fb,
                   "fallback_reason": "cli" if fb else None, "attempts": 3 if fb else 1,
                   "error_kinds": ["cli", "cli", "cli"] if fb else [],
                   "claims": [] if fb else [{"truthful": k % 3 != 0}], "action": {}})
    for c in CREW:
        sus = {m: ms for m in MOLES}
        sus.update({o: 40 for o in CREW if o != c})
        ev.append({"type": "turn", "player": c, "model": "m", "turn_phase": "vote", "fallback": False,
                   "attempts": 1, "error_kinds": [], "action": {"suspicion": sus}})
    votes = {c: "Ash" if c in ("Cedar", "Dove") else "Elm" for c in CREW}
    votes.update({m: "Elm" for m in MOLES})
    ev.append({"type": "vote_result", "votes": votes, "eliminated": "Elm", "role": "crew"})
    ev.append({"type": "game_end", "winner": winner, "survivors": list(MOLES) + ["Cedar", "Dove"]})
    return ev


def index_row(group, seed, log, winner, stamp):
    batch, mid, _, _ = SPEC[group]
    row = {"game_id": f"g-{batch}-s{seed}", "seed": seed, "batch": batch, "spoiled": False, "winner": winner,
           "reason": "jobs_clean", "rounds": 3, "calls": 100, "log": log, "players": players_for(group),
           "conditions": {"max_thinking_tokens": 2000, "effort": "low"},
           "tokens": {"input": 1000, "output": 2000, "cache_read": 300, "cache_creation": 400, "thinking": 500,
                      "cost_usd": 1.25},
           "wall_s": 600.0, "code_hash": stamp}
    if "/" in mid:
        row["billed_usd"] = 0.3
    return row


def build(root, groups):
    """Logs and an index under root for groups = {group: (games, fallbacks per game)}; returns the
    index path. Seeds start at 101. One spoiled game (seed 199) is added for the first group."""
    (root / "games").mkdir(exist_ok=True)
    rows = []
    for group, (n, fbs) in groups.items():
        stamp = OUTSIDE_STAMP if "/" in SPEC[group][1] else CLAUDE_STAMP
        for seed in range(101, 101 + n):
            winner = "moles" if seed % 3 == 0 else "crew"
            rel = f"games/{SPEC[group][0]}-s{seed}.jsonl"
            ev = log_events(group, seed, fallbacks=fbs, winner=winner, stamp=stamp)
            (root / rel).write_text("".join(json.dumps(e) + "\n" for e in ev))
            rows.append(index_row(group, seed, rel, winner, stamp))
    first = next(iter(groups))
    rel = "games/spoiled.jsonl"
    (root / rel).write_text("".join(json.dumps(e) + "\n" for e in log_events(first, 199)))
    rows.append(dict(index_row(first, 199, rel, "moles", CLAUDE_STAMP), spoiled=True))
    index = root / "games" / "index.jsonl"
    index.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return index


class Fixture(unittest.TestCase):
    """Builds games for `self.groups` = {group: (number of games, fallbacks per game)}."""
    groups = {}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.index = build(self.root, self.groups)

    def rebuild(self, groups):
        self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.index = build(self.root, groups)

    def tearDown(self):
        self.tmp.cleanup()

    def out(self):
        return lm.analyse(self.index, self.root)

    def model(self, out, name):
        return next(m for m in out["models"] if m["name"] == name)


ALL_NINE = {g: (10 if SPEC[g][1].startswith("claude") else 5, 0) for g in SPEC}
THREE = {"Haiku 4.5 moles": (10, 0), "Opus 5.5 moles": (10, 0), "Fable 5.2 moles": (10, 0)}


class TestGroups(Fixture):
    groups = {"Fable 5.2 moles": (10, 0), "Opus 5.5 moles": (10, 0), "Grok 4.7 moles": (5, 0),
              "Kimi K3.1 Pro moles": (5, 0), "Haiku 4.5 moles": (10, 0)}

    def test_group_without_games_left_out(self):
        out = self.out()
        names = [m["name"] for m in out["models"]]
        self.assertEqual(names, ["Fable 5.2", "Opus 5.5", "Grok 4.7", "Kimi K3.1 Pro", "Haiku 4.5"])
        svg = lm.render_svg(out)
        text = lm.report(out) + lm.to_json(out) + svg + lm.render_html(svg, out)
        # Haiku 5.5 is a crew model, so only its mole group must be absent.
        for absent in ("Sonnet 5.5", "Haiku 5.5 moles", "bluff_haiku55", 'data-model="Haiku 5.5"', "Gemini", "Sol"):
            self.assertNotIn(absent, text, absent)
        self.assertNotRegex(lm.report(out), r"(?m)^  Haiku 5\.5 ")
        self.assertNotIn("199", lm.to_json(out))                                 # spoiled seed left out
        self.assertEqual(out["draw_order"], ["Haiku 4.5 moles", "Opus 5.5 moles", "Fable 5.2 moles",
                                             "Grok 4.7 moles", "Kimi K3.1 Pro moles"])

    def test_mixed_ten_and_five_game_groups(self):
        out = self.out()
        self.assertEqual(self.model(out, "Grok 4.7")["seeds"], [101, 102, 103, 104, 105])
        self.assertEqual(self.model(out, "Fable 5.2")["n"], 10)
        by_pair = {(p["a"], p["b"]): p for p in out["pairs"]}
        self.assertEqual(len(by_pair), 10)
        self.assertEqual(by_pair[("Fable 5.2", "Opus 5.5")]["n"], 10)
        self.assertEqual(by_pair[("Fable 5.2", "Grok 4.7")]["n"], 5)
        self.assertEqual(by_pair[("Grok 4.7", "Kimi K3.1 Pro")]["seeds"], [101, 102, 103, 104, 105])
        # Fable minus Opus: -22 on every seed, so 10 of 10 below zero and exact p = 2 / 2^10.
        p = by_pair[("Fable 5.2", "Opus 5.5")]
        self.assertAlmostEqual(p["mean"], -22.0)
        self.assertEqual(p["below"], 10)
        self.assertAlmostEqual(p["p"], 2 / 1024)
        self.assertAlmostEqual(by_pair[("Fable 5.2", "Grok 4.7")]["p"], 2 / 32)
        text = lm.report(out)
        self.assertIn("Pairs with Grok 4.7 (5-game model) have 5 seeds at most", text)
        self.assertIn("Holm correction over the 10 pairs", text)
        self.assertIn("fewer than 10 games", text)
        # Per-game table only for batches bluff_score does not print, billed dollars where present.
        self.assertEqual(out["new_batches"], ["Grok 4.7 moles", "Kimi K3.1 Pro moles"])
        self.assertIn("billed $0.30", text)
        self.assertNotIn("bluff_opus55   seed", text)
        self.assertAlmostEqual(self.model(out, "Grok 4.7")["billed_usd"], 1.5)
        self.assertIsNone(self.model(out, "Fable 5.2")["billed_usd"])
        # Chart: hollow dots for the 5-game rows, filled for the others, legend says why.
        tree = ET.fromstring(lm.render_svg(out))
        for g in tree.iter(f"{{{SVG_NS}}}g"):
            if g.get("data-model"):
                fills = {c.get("fill") for c in g.iter(f"{{{SVG_NS}}}circle")}
                short = g.get("data-model") in ("Grok 4.7", "Kimi K3.1 Pro")
                self.assertEqual("short" in g.get("class"), short)
                self.assertEqual(fills == {lm.SURFACE}, short, g.get("data-model"))
                self.assertEqual(len(list(g.iter(f"{{{SVG_NS}}}circle"))), 5 if short else 10)
        legend = " ".join(label for _, label in out["chart"]["legend"])
        self.assertIn("only 5 games", legend)
        self.assertIn("less sure", legend)

    def test_rows_sorted_reference_muted(self):
        out = self.out()
        means = {m["name"]: m["mean"] for m in out["models"]}
        rows = [lm.display_name(g) for g in out["chart"]["rows"]]
        self.assertEqual(rows, sorted(rows, key=lambda n: means[n]))
        tree = ET.fromstring(lm.render_svg(out))
        ref = [g for g in tree.iter(f"{{{SVG_NS}}}g") if "reference" in (g.get("class") or "")]
        self.assertEqual([g.get("data-model") for g in ref], ["Haiku 4.5"])
        self.assertEqual({c.get("fill") for c in ref[0].iter(f"{{{SVG_NS}}}circle")}, {lm.REF_DOT})
        self.assertIn("reference", [t.text for t in ref[0].iter(f"{{{SVG_NS}}}text")])
        wins = [t.text for t in tree.iter(f"{{{SVG_NS}}}text") if t.get("class") == "wins"]
        self.assertIn("moles won 3 of 10", wins)    # seeds 102, 105, 108 won by the moles
        self.assertIn("moles won 2 of 5", wins)     # seeds 102, 105

    def test_rerun_gives_identical_numbers(self):
        a, b = self.out(), self.out()
        self.assertEqual(lm.to_json(a), lm.to_json(b))
        self.assertEqual(lm.report(a), lm.report(b))
        self.assertEqual(lm.render_svg(a), lm.render_svg(b))

    def test_existing_groups_match_bluff_score(self):
        out = self.out()
        res = bluff_score.group_games(bluff_score.load_index(self.index), bluff_score.GROUPS, str(self.root))
        s = bluff_score.summaries(res, bluff_score.new_rng(), bluff_score.GROUPS)
        for name, _ in bluff_score.GROUPS:
            m = next(m for m in out["models"] if m["group"] == name)
            for k in ("n", "wins", "gaps", "mean", "lo", "hi"):
                self.assertEqual(m[k], s[name][k], (name, k))

    def test_json_option(self):
        path = self.root / "out.json"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(lm.main(["--index", str(self.index), "--root", str(self.root), "--json", str(path)]), 0)
        data = json.loads(path.read_text())
        self.assertEqual(len(data["models"]), 5)
        self.assertEqual(len(data["pairs"]), 10)
        self.assertIn("p_holm", data["pairs"][0])
        self.assertIn("fallback_share", data["models"][0])
        self.assertIn("games", data["models"][0])


class TestNoAnswer(Fixture):
    # 2 of 20 mole turns fall back in every Gemini game (10%); 1 of 20 in every Kimi game (5%, allowed).
    groups = {"Fable 5.2 moles": (10, 0), "Kimi K3.1 Pro moles": (5, 1), "Gemini 4 Carbon moles": (5, 2)}

    def test_above_five_percent_left_off(self):
        out = self.out()
        gem, kimi = self.model(out, "Gemini 4 Carbon"), self.model(out, "Kimi K3.1 Pro")
        self.assertEqual((gem["fallback_turns"], gem["mole_turns"]), (10, 100))
        self.assertAlmostEqual(gem["fallback_share"], 0.10)
        self.assertEqual(gem["fallback_reasons"], {"cli": 10})
        self.assertEqual(gem["failed_attempts"], 30)
        self.assertTrue(gem["left_off"])
        self.assertAlmostEqual(kimi["fallback_share"], 0.05)
        self.assertFalse(kimi["left_off"])
        self.assertNotIn("Gemini 4 Carbon moles", out["chart"]["rows"])
        self.assertIn("Kimi K3.1 Pro moles", out["chart"]["rows"])
        self.assertEqual([(p["a"], p["b"]) for p in out["pairs"]], [("Fable 5.2", "Kimi K3.1 Pro")])
        text = lm.report(out)
        self.assertRegex(text, r"Gemini 4 Carbon .*LEFT OFF THE CHART")
        self.assertRegex(text, r"Gemini 4 Carbon +100 +10 +10\.0%  cli 10 .* left off the chart")
        self.assertIn("Not compared (left off the chart): Gemini 4 Carbon.", text)
        svg = lm.render_svg(out)
        self.assertNotIn('data-model="Gemini 4 Carbon"', svg)
        self.assertIn("Left off the chart: Gemini 4 Carbon.", " ".join(out["chart"]["footnotes"]))
        # Fallback discuss turns carry no public text, so the lie tally ignores them.
        self.assertEqual(gem["stmts"], 5 * 18)


class TestHolm(unittest.TestCase):
    def test_hand_checked(self):
        # m = 4. Sorted: 0.01 x 4 = 0.04; 0.03 x 3 = 0.09; 0.04 x 2 = 0.08 -> max(0.09, 0.08) = 0.09;
        # 0.20 x 1 = 0.20. Back in input order:
        got = lm.holm([0.01, 0.04, 0.03, 0.20])
        for g, want in zip(got, [0.04, 0.09, 0.09, 0.20]):
            self.assertAlmostEqual(g, want)
        # Capped at 1, monotone, None left out of m.
        self.assertEqual(lm.holm([0.5, None, 0.6]), [1.0, None, 1.0])
        self.assertEqual(lm.holm([]), [])

    def test_applied_to_pairs(self):
        with tempfile.TemporaryDirectory() as d:
            out = lm.analyse(build(Path(d), THREE), d)
        ps = [p["p"] for p in out["pairs"]]
        self.assertEqual([p["p_holm"] for p in out["pairs"]], lm.holm(ps))


class TestChartFiles(Fixture):
    groups = THREE

    def test_refuses_to_overwrite_without_force(self):
        out_dir = self.root / "charts"
        svg, html = lm.write_chart(self.out(), out_dir)
        self.assertEqual(sorted(p.name for p in out_dir.iterdir()), ["latest_models.html", "latest_models.svg"])
        svg.write_text("keep me")
        with self.assertRaises(FileExistsError):
            lm.write_chart(self.out(), out_dir)
        self.assertEqual(svg.read_text(), "keep me")
        # One file present is enough to refuse.
        svg.unlink()
        with self.assertRaises(FileExistsError):
            lm.write_chart(self.out(), out_dir)
        self.assertFalse(svg.exists())
        # The command line refuses too, with exit status 2 and nothing written.
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = lm.main(["--index", str(self.index), "--root", str(self.root), "--chart", str(out_dir)])
        self.assertEqual(rc, 2)
        self.assertIn("--force", err.getvalue())
        self.assertFalse(svg.exists())
        with redirect_stdout(io.StringIO()):
            rc = lm.main(["--index", str(self.index), "--root", str(self.root), "--chart", str(out_dir), "--force"])
        self.assertEqual(rc, 0)
        self.assertTrue(svg.read_text().startswith("<?xml"))
        self.assertEqual(sorted(p.name for p in out_dir.iterdir()), ["latest_models.html", "latest_models.svg"])

    def test_never_writes_bluff_gap(self):
        out_dir = self.root / "charts"
        out_dir.mkdir()
        (out_dir / "bluff_gap.svg").write_text("old")
        (out_dir / "bluff_gap.html").write_text("old")
        lm.write_chart(self.out(), out_dir)
        self.assertEqual((out_dir / "bluff_gap.svg").read_text(), "old")
        self.assertEqual((out_dir / "bluff_gap.html").read_text(), "old")
        self.assertNotIn("bluff_gap", " ".join(lm.CHART_FILES))

    def test_files_well_formed_and_offline(self):
        svg_path, html_path = lm.write_chart(self.out(), self.root / "charts")
        root = ET.parse(svg_path).getroot()
        self.assertEqual(root.tag, f"{{{SVG_NS}}}svg")
        w, h = (int(v) for v in root.get("viewBox").split()[2:])
        self.assertEqual(w, 1600)
        self.assertGreaterEqual(h, 900)
        html = html_path.read_text()
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertEqual(html.count("<svg"), 1)
        for text in (svg_path.read_text(), html):
            urls = re.findall(r"(?:[a-z][a-z0-9+.-]*:)?//[^\s\"'<>)]+", text, re.I)
            self.assertEqual(set(urls), {SVG_NS}, urls)
            self.assertNotRegex(text, r"(?i)\b(src|href)\s*=|@import|url\(|<script|<link")


class TestFootnotes(Fixture):
    groups = THREE

    def notes(self):
        return " ".join(self.out()["chart"]["footnotes"])

    def test_without_haiku55_or_outside_lab(self):
        n = self.notes()
        self.assertIn("Each dot is one game.", n)
        self.assertIn("Same five-model crew in every game: Haiku 4.5, Haiku 5.5, Sonnet 4.5, Sonnet 4.6, "
                      "Sonnet 5. Effort low in every game.", n)
        # Names in chart order (lowest mean first).
        self.assertIn("Fable 5.2, Opus 5.5 and Haiku 4.5: 10 games each, seeds 101–110.", n)
        self.assertNotIn("Haiku 5.5 is also", n)
        self.assertNotIn("OpenRouter", n)
        self.assertTrue(n.endswith("No model has been played twice yet, so the size of a difference that means "
                                   "nothing is not measured. Not a ranking."))

    def test_with_haiku55_and_outside_lab(self):
        self.rebuild(dict(THREE, **{"Haiku 5.5 moles": (10, 0), "Grok 4.7 moles": (5, 0), "Kimi K3.1 Pro moles": (5, 0)}))
        n = self.notes()
        self.assertIn("Haiku 5.5 is also one of the five crew models, so three of seven seats are Haiku 5.5 "
                      "in its own games.", n)
        # Kimi's fake mean is below Grok's, so it comes first (chart order).
        self.assertIn("Kimi K3.1 Pro and Grok 4.7 were called through OpenRouter and sent reasoning effort "
                      "\"low\". They ran from code stamp 5eedf00d; the Claude rows ran from 0800d943.", n)
        self.assertIn("Kimi K3.1 Pro and Grok 4.7: 5 games each, seeds 101–105.", n)

    def test_crew_differs_is_said(self):
        rows = [json.loads(l) for l in self.index.read_text().splitlines()]
        log = self.root / rows[0]["log"]
        ev = [json.loads(l) for l in log.read_text().splitlines()]
        ev[0]["players"][2]["model_name"] = "Someone Else"
        log.write_text("".join(json.dumps(e) + "\n" for e in ev))
        n = self.notes()
        self.assertIn("Crew not the same in every game.", n)
        self.assertNotIn("Same five-model crew", n)

    def test_no_em_dash_in_prose(self):
        self.rebuild(ALL_NINE)
        out = self.out()
        prose = " ".join(out["chart"]["footnotes"] + [l for _, l in out["chart"]["legend"]]) + lm.report(out)
        self.assertNotIn("—", prose)


class TestLayout(Fixture):
    groups = ALL_NINE

    def check(self, out, rows):
        svg = lm.render_svg(out)
        self.assertEqual(len(out["chart"]["rows"]), rows)
        self.assertEqual(lm.layout_problems(svg), [])
        root = ET.fromstring(svg)
        w, h = (float(v) for v in root.get("viewBox").split()[2:])
        for c in root.iter(f"{{{SVG_NS}}}circle"):
            self.assertLessEqual(float(c.get("cy")) + 10, h)
        return svg

    def test_nine_rows(self):
        svg = self.check(self.out(), 9)
        self.assertEqual(svg.count('class="game"'), 4 * 10 + 4 * 5 + 10)

    def test_three_rows(self):
        self.rebuild(THREE)
        self.check(self.out(), 3)

    def test_checker_finds_overlap(self):
        svg = lm.render_svg(self.out())
        bad = svg.replace("</svg>", '<text x="80" y="98" font-size="64" font-weight="700">Clash</text>\n'
                                    '<text x="1590" y="400" font-size="26">Off the edge</text>\n</svg>')
        probs = lm.layout_problems(bad)
        self.assertTrue(any("overlap" in p and "Clash" in p for p in probs), probs)
        self.assertTrue(any("off canvas" in p and "Off the edge" in p for p in probs), probs)


class TestRealGroups(unittest.TestCase):
    """The three bluff_score groups in the real games/ folder (read-only). Skips without the logs."""

    def test_real_numbers_equal_bluff_score(self):
        index = PROJECT / "games" / "index.jsonl"
        if not index.exists():
            self.skipTest("no games/index.jsonl")
        idx = bluff_score.load_index(index)
        batches = {b for _, bs in bluff_score.GROUPS for b in bs}
        rows = [r for r in idx if r.get("batch") in batches and not r.get("spoiled")]
        if not rows or any(not (PROJECT / r["log"]).exists() for r in rows):
            self.skipTest("bluff logs missing")
        out = lm.analyse(index, PROJECT)
        res = bluff_score.group_games(idx, bluff_score.GROUPS, str(PROJECT))
        s = bluff_score.summaries(res, bluff_score.new_rng(), bluff_score.GROUPS)
        for name, _ in bluff_score.GROUPS:
            if name not in s:
                continue
            m = next(m for m in out["models"] if m["group"] == name)
            for k in ("n", "wins", "gaps", "mean", "lo", "hi"):
                self.assertEqual(m[k], s[name][k], (name, k))
            tot = s[name]["tot"]
            self.assertEqual((m["crew_on_mole"], m["crew_votes"]), (tot["crew_on_mole"], tot["crew_votes"]))
            self.assertEqual((m["elims_mole"], m["elims"]), (tot["elims_mole"], tot["elims"]))
            self.assertEqual((m["lies"], m["stmts"]), (tot["mole_stmts_lie"], tot["mole_stmts"]))
            # The index's own per-game fallback count is an upper bound on the mole seats' fallbacks.
            self.assertLessEqual(m["fallback_turns"], sum(x["row"].get("fallbacks", 0) for x in res[name]))


if __name__ == "__main__":
    unittest.main()
