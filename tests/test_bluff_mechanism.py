"""analysis/bluff_mechanism.py on synthetic games written to a temp directory (never games/).

Every expected number below is worked by hand in the comment next to it.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ANALYSIS = Path(__file__).resolve().parent.parent / "analysis"
if str(ANALYSIS) not in sys.path:
    sys.path.insert(0, str(ANALYSIS))

import bluff_mechanism as bm  # noqa: E402
import bluff_score  # noqa: E402

PLAYERS = ["A", "B", "C", "D", "E"]
MOLES = ["A", "B"]


def build(rounds, *, players=PLAYERS, moles=MOLES, game_id="g-test", seed=1, winner="moles", reason="sabotage",
          end=True):
    """A log the engine could have written, cut down to what the analysis and the solver read.

    rounds: list of dicts with
      alive    (default: everyone not voted out so far)
      leader   (default: first alive)
      team, sabotages   the round's job (omit team for no job)
      clues    {player: clue dict}
      votes    {rater: suspicion dict}  (moles included if given)
      fallback set of raters whose vote turn is a fallback
      out      name voted out (optional)
    """
    ev = []

    def add(**kw):
        kw.setdefault("round", 0)
        kw.setdefault("phase", "setup")
        ev.append(dict(seq=len(ev), **kw))
    add(type="game_start", vis="engine", game_id=game_id, seed=seed, moles=list(moles))
    add(type="table", vis="public", seats=list(players), num_moles=len(moles), pot=100)
    for p in players:
        add(type="role", vis="private", player=p, role="mole" if p in moles else "crew",
            partners=[m for m in moles if m != p] if p in moles else [])
    alive = list(players)
    clean = blown = 0
    for i, R in enumerate(rounds, 1):
        alive = list(R.get("alive", alive))
        add(type="round_start", vis="public", round=i, phase="clue", leader=R.get("leader", alive[0]),
            alive=list(alive), clean_jobs=clean, blown_jobs=blown)
        for p, c in (R.get("clues") or {}).items():
            add(type="clue", vis="private", round=i, phase="clue", player=p, clue=c)
        if "team" in R:
            add(type="job_pick", vis="public", round=i, phase="pick", leader=R.get("leader", alive[0]),
                team=list(R["team"]))
            sab = R.get("sabotages", 0)
            clean += sab == 0
            blown += sab > 0
            add(type="job_result", vis="public", round=i, phase="job", team=list(R["team"]), sabotages=sab,
                blown=sab > 0, clean_jobs=clean, blown_jobs=blown)
        votes = {}
        for p, sus in (R.get("votes") or {}).items():
            tgt = max(sus, key=sus.get)
            votes[p] = tgt
            add(type="turn", vis="engine", round=i, phase="vote", turn_phase="vote", player=p, model="m",
                fallback=p in (R.get("fallback") or ()), public="", action={"vote": tgt, "suspicion": dict(sus)})
        if votes:
            out = R.get("out")
            add(type="vote_result", vis="public", round=i, phase="vote", votes=votes, tally={}, tied=[],
                tiebreak=None, eliminated=out, role=("mole" if out in moles else "crew") if out else None)
            if out:
                alive = [p for p in alive if p != out]
    if end:
        add(type="game_end", vis="public", round=len(rounds), phase="end", winner=winner, reason=reason,
            clean_jobs=clean, blown_jobs=blown, rounds=len(rounds), survivors=list(alive))
    return ev


def even(mole_v, crew_v, rater, alive=PLAYERS, moles=MOLES):
    """Rater gives every mole mole_v and every other living crew member crew_v."""
    return {p: (mole_v if p in moles else crew_v) for p in alive if p != rater}


# Round 1 of the hand-worked game: three crew readings.
R1_VOTES = {
    "C": {"A": 80, "B": 40, "D": 20, "E": 60},
    "D": {"A": 50, "B": 50, "C": 10, "E": 30},
    "E": {"A": 70, "B": 10, "C": 40, "D": 40},
    "A": {"B": 0, "C": 100, "D": 100, "E": 100},     # a mole's reading: never counted
}


class Root:
    """A temp project root with games/index.jsonl and the given logs."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "games").mkdir()
        self.rows = []

    def add(self, batch, seed, events, **row):
        gid = f"g-{batch}-s{seed}"
        rel = f"games/{gid}.jsonl"
        (self.root / rel).write_text("".join(json.dumps(e) + "\n" for e in events))
        self.rows.append(dict({"game_id": gid, "seed": seed, "batch": batch, "spoiled": False, "log": rel,
                               "winner": "moles", "reason": "sabotage", "rounds": 1}, **row))

    def write(self):
        (self.root / "games" / "index.jsonl").write_text("".join(json.dumps(r) + "\n" for r in self.rows))

    def close(self):
        self.tmp.cleanup()


class TestCrewGap(unittest.TestCase):
    def test_round1_gap_hand_computed(self):
        ev = build([{"team": ["A", "C", "D"], "sabotages": 1, "votes": R1_VOTES}])
        g = bm.score_game(ev)
        # moles: 80+40 + 50+50 + 70+10 = 300 over 6 = 50; crew: 20+60 + 10+30 + 40+40 = 200 over 6.
        self.assertAlmostEqual(g["r1"]["crew"], 50 - 200 / 6)
        self.assertEqual(g["r1"]["n_readings"], 3)
        self.assertAlmostEqual(g["whole"]["crew"], 50 - 200 / 6)

    def test_whole_game_pools_like_bluff_score(self):
        # Round 2 after E is out: C gives moles 90, D 60 -> each reading rates 2 moles + 1 crew.
        ev = build([
            {"team": ["A", "C", "D"], "sabotages": 1, "votes": R1_VOTES, "out": "E"},
            {"team": ["B", "C"], "sabotages": 0,
             "votes": {"C": {"A": 90, "B": 90, "D": 30}, "D": {"A": 60, "B": 60, "C": 0}}},
        ])
        g = bm.score_game(ev)
        # round 2: moles 90,90,60,60 = 300/4 = 75; crew 30, 0 = 15 -> +60.
        self.assertAlmostEqual(g["rounds"][2]["m"]["crew"], 60.0)
        # whole: moles (300 + 300) / 10 = 60; crew (200 + 30) / 8 = 28.75.
        self.assertAlmostEqual(g["whole"]["crew"], 60 - 28.75)
        self.assertEqual(g["whole"]["crew"], bm.compat_gap(ev))

    def test_fallback_left_out(self):
        votes = dict(R1_VOTES, D=even(100, 0, "D"))
        ev = build([{"team": ["A", "C", "D"], "sabotages": 1, "votes": votes, "fallback": {"D"}}])
        g = bm.score_game(ev)
        # C and E only: moles 80+40+70+10 = 200/4 = 50; crew 20+60+40+40 = 160/4 = 40.
        self.assertAlmostEqual(g["r1"]["crew"], 10.0)
        self.assertEqual(g["r1"]["n_readings"], 2)
        self.assertEqual(g["issues"]["crew fallback vote turn left out"], 1)
        # bluff_score's own rule keeps the fallback turn: moles 300/6 = 50 with D's 100s -> (200+200)/6.
        self.assertAlmostEqual(bm.compat_gap(ev), 400 / 6 - 160 / 6)

    def test_dead_and_self_ratings_dropped(self):
        votes = dict(R1_VOTES)
        votes["C"] = dict(R1_VOTES["C"], C=99)
        ev = build([{"alive": ["A", "B", "C", "D"], "team": ["A", "C"], "sabotages": 1,
                     "votes": {"C": dict(votes["C"]), "D": {"A": 50, "B": 50, "C": 10}}}])
        g = bm.score_game(ev)
        # E is not alive: C's rating of E (60) and C's self-rating are dropped.
        # moles 80+40+50+50 = 220/4 = 55; crew C->D 20, D->C 10 = 15 -> +40.
        self.assertAlmostEqual(g["r1"]["crew"], 40.0)
        self.assertEqual(g["issues"]["rating of a dead player dropped"], 1)
        self.assertEqual(g["issues"]["self-rating dropped"], 1)


class TestFormula(unittest.TestCase):
    """One crew reading (C), D and E on fallback. Job 1: team A, B, D, clean. No clues.

    C's own view: worlds are the pairs without C: AB AD AE BD BE DE. jobw50 weights each world by
    0.5^k, k = members on the clean team: AB .25, AD .25, AE .5, BD .25, BE .5, DE .5 (total 2.25).
    A = (.25+.25+.5)/2.25 = 4/9, B = 4/9, D = 4/9, E = 1.5/2.25 = 2/3.
    jobw50 gap = (400/9 + 400/9)/2 - (400/9 + 600/9)/2 = -100/9.
    public: all 10 pairs fit a clean job, unweighted -> 0.4 each -> gap 0.
    C's ratings A 50, B 20, D 50, E 10: crew gap 35 - 30 = +5; residual 5 + 100/9 = 145/9.
    Rank, C: (A,D) tie .5, (A,E) 1, (B,D) 0, (B,E) 1 -> 2.5/4 = .625.
    jobw50 rank: (A,D) tie .5, (A,E) 0, (B,D) tie .5, (B,E) 0 -> .25; public all ties -> .5.
    """

    def game(self):
        votes = {"C": {"A": 50, "B": 20, "D": 50, "E": 10}, "D": even(100, 0, "D"), "E": even(100, 0, "E")}
        return build([{"team": ["A", "B", "D"], "sabotages": 0, "votes": votes, "fallback": {"D", "E"}}])

    def test_formula_values(self):
        g = bm.score_game(self.game())
        rd = g["rounds"][1]["readings"]
        self.assertEqual([r["rater"] for r in rd], ["C"])
        f = rd[0]["f50"]
        for n, v in (("A", 400 / 9), ("B", 400 / 9), ("D", 400 / 9), ("E", 200 / 3)):
            self.assertAlmostEqual(f[n], v)
        for n in "ABDE":
            self.assertAlmostEqual(rd[0]["pub"][n], 40.0)

    def test_gaps_residual_rank(self):
        m = bm.score_game(self.game())["r1"]
        self.assertAlmostEqual(m["crew"], 5.0)
        self.assertAlmostEqual(m["f50"], -100 / 9)
        self.assertAlmostEqual(m["pub"], 0.0)
        self.assertAlmostEqual(m["resid"], 145 / 9)
        self.assertAlmostEqual(m["crew_rank"], 0.625)
        self.assertAlmostEqual(m["f50_rank"], 0.25)
        self.assertAlmostEqual(m["pub_rank"], 0.5)
        self.assertAlmostEqual(m["rank_resid"], 0.375)

    def test_formula_uses_view_before_votes(self):
        # A clue to C (at least one of A and E) removes BD from C's worlds. Worlds AB .25, AD .25,
        # AE .5, BE .5, DE .5 (total 2): A = 1/2, B = .75/2, D = .75/2, E = 1.5/2.
        # Round 2's blown job (team A, C) must not reach round 1's cutoff: if it did, BE and DE
        # would drop out and A would be 1.
        clue = {"kind": "at_least_one", "players": ["A", "E"], "text": "At least one of A and E is a mole."}
        ev = build([
            {"team": ["A", "B", "D"], "sabotages": 0, "clues": {"C": clue},
             "votes": {"C": {"A": 50, "B": 20, "D": 50, "E": 10}}},
            {"team": ["A", "C"], "sabotages": 1, "votes": {"C": {"A": 50, "B": 20, "D": 50, "E": 10}}},
        ])
        f = bm.score_game(ev)["rounds"][1]["readings"][0]["f50"]
        for n, v in (("A", 50.0), ("B", 37.5), ("D", 37.5), ("E", 75.0)):
            self.assertAlmostEqual(f[n], v)


class TestRank(unittest.TestCase):
    def test_pooled_pairs_with_ties(self):
        moles = {"A", "B"}
        r1 = {"crew": {"A": 50, "B": 30, "D": 50, "E": 10}}     # .5 + 1 + 0 + 1 = 2.5 of 4
        r2 = {"crew": {"A": 70, "D": 70}}                         # one tie: .5 of 1
        self.assertAlmostEqual(bm.pooled_rank([r1, r2], "crew", moles), 3.0 / 5)
        # Alternative: mean of per-reading chances (.625 + .5) / 2.
        self.assertAlmostEqual(bm.mean_reading_rank([r1, r2], "crew", moles), 0.5625)
        self.assertIsNone(bm.pooled_rank([{"crew": {"D": 5}}], "crew", moles))

    def test_float_ties(self):
        self.assertEqual(bm.pair_score(4 / 9 * 100, 400 / 9), 0.5)
        self.assertEqual(bm.pair_score(0.3, 0.1 + 0.2), 0.5)


class TestStrata(unittest.TestCase):
    def test_strata_assignment(self):
        ev = build([
            {"team": ["A", "C", "D"], "sabotages": 1, "votes": R1_VOTES, "out": "E"},
            {"team": ["C", "D"], "sabotages": 0, "votes": {"C": {"A": 1, "B": 2, "D": 3}}},
            {"team": ["B", "C"], "sabotages": 0, "votes": {"C": {"A": 1, "B": 2, "D": 3}}},
        ])
        g = bm.score_game(ev)
        # At the vote (this round's job counted): r1 blown 1; r2 clean 1 blown 1; r3 clean 2 blown 1.
        self.assertEqual(g["rounds"][1]["strata"], (1, 0, 1, True))
        self.assertEqual(g["rounds"][2]["strata"], (2, 1, 1, False))
        self.assertEqual(g["rounds"][3]["strata"], (3, 2, 1, True))
        # Alternative: counts at round_start (before this round's job).
        self.assertEqual(g["rounds"][1]["strata_pre"], (1, 0, 0, True))
        self.assertEqual(g["rounds"][2]["strata_pre"], (2, 0, 1, False))
        self.assertEqual(g["rounds"][3]["strata_pre"], (3, 1, 1, True))
        self.assertEqual(g["desc"], {"job1_blown": True, "job1_mole": True, "mole_led_r1": True,
                                     "readings": 5, "vote_rounds": 3})


def fake(gaps):
    """A scored game for match(): {round: (stratum, crew gap)}."""
    return {"rounds": {r: {"strata": s, "m": {"crew": v}} for r, (s, v) in gaps.items()}}


class TestMatching(unittest.TestCase):
    def test_weights_hand_computed(self):
        X, Y, Z, W = (1, 0, 1, True), (1, 1, 0, False), (2, 1, 1, True), (2, 2, 0, False)
        a = [fake({1: (X, 10), 2: (Z, 5)}), fake({1: (X, 20)}), fake({1: (Y, -10)})]
        b = [fake({1: (X, 0), 2: (W, 7)}), fake({1: (Y, 10)}), fake({1: (Y, 30)}), fake({1: (Y, 20)})]
        m = bm.match(a, b)
        # X: a 10, 20 (n 2), b 0 (n 1): w = 2/3, diff 15. Y: a -10 (1), b 10, 30, 20 (3): w = 3/4,
        # diff -30. Z only a, W only b: unmatched. (2/3*15 + 3/4*-30) / (2/3 + 3/4) = -12.5 / (17/12).
        self.assertAlmostEqual(m["diff"], -150 / 17)
        self.assertEqual((m["matched_a"], m["total_a"]), (3, 4))
        self.assertEqual((m["matched_b"], m["total_b"]), (4, 5))
        self.assertEqual([(r["na"], r["nb"]) for r in m["strata"]], [(2, 1), (1, 3)])
        self.assertAlmostEqual(m["strata"][0]["w"], 2 / 3)
        self.assertAlmostEqual(m["strata"][1]["w"], 3 / 4)

    def test_no_shared_stratum(self):
        m = bm.match([fake({1: ((1, 0, 0, True), 1)})], [fake({1: ((1, 0, 0, False), 1)})])
        self.assertIsNone(m["diff"])
        self.assertEqual(m["share_a"], 0)


def pc(mean, lo, hi, below, n):
    return {"mean": mean, "lo": lo, "hi": hi, "below": below, "n": n}


class TestMarks(unittest.TestCase):
    def test_p1_p2_rules(self):
        self.assertEqual(bm.mark_paired([pc(-5, -9, -1, 6, 10), pc(-4, -8, -0.5, 5, 10)]), "Holds")
        self.assertEqual(bm.mark_paired([pc(-5, -9, -1, 7, 10), pc(-4, -8, 1, 7, 10)]), "Direction only")
        self.assertEqual(bm.mark_paired([pc(-5, -9, -1, 9, 10), pc(0.0, -3, 3, 5, 10)]), "Fails")
        self.assertEqual(bm.mark_paired([pc(-5, -9, 2, 9, 10), pc(-1, -3, 3, 4, 10)]), "Fails")
        # Below zero, an interval includes zero, 60% of seeds below: no rule covers it.
        self.assertEqual(bm.mark_paired([pc(-5, -9, 2, 6, 10), pc(-4, -8, 1, 8, 10)]),
                         "No mark (between Direction only and Fails)")
        # Both intervals exclude zero but fewer than half the seeds are below: rules overlap.
        self.assertEqual(bm.mark_paired([pc(-5, -9, -1, 4, 10), pc(-4, -8, -1, 8, 10)]),
                         "Holds and Fails both met (rules overlap)")
        self.assertEqual(bm.mark_paired([pc(None, None, None, 0, 0), pc(-4, -8, -1, 8, 10)]),
                         "not informative (no paired seeds)")
        # An interval that cannot be computed (one seed) counts as including zero.
        self.assertEqual(bm.mark_paired([pc(-5, None, None, 1, 1), pc(-4, -8, -1, 8, 10)]), "Direction only")

    def test_p3_rules(self):
        def mc(d, lo, hi, share):
            return {"diff": d, "lo": lo, "hi": hi, "share_a": share}
        self.assertEqual(bm.mark_match([mc(-5, -9, -1, 0.8), mc(-3, -6, -0.1, 0.5)]), "Holds")
        self.assertEqual(bm.mark_match([mc(-5, -9, -1, 0.8), mc(-3, -6, 0.1, 0.9)]), "Direction only")
        self.assertEqual(bm.mark_match([mc(-5, -9, -1, 0.8), mc(0.0, -6, 6, 0.9)]), "Fails")
        self.assertEqual(bm.mark_match([mc(-5, -9, -1, 0.8), mc(-3, -6, -1, 0.49)]), "not informative")
        self.assertEqual(bm.mark_match([mc(5, 1, 9, 0.2), mc(-3, -6, -1, 0.9)]), "not informative")


class TestStats(unittest.TestCase):
    def test_signflip_exact(self):
        # [1, 2, 3]: only all-plus and all-minus reach |mean| 2 -> 2/8.
        self.assertAlmostEqual(bm.signflip_p([1, 2, 3]), 0.25)
        self.assertAlmostEqual(bm.signflip_p([1, -1]), 1.0)
        self.assertAlmostEqual(bm.signflip_p([-4] * 7), 2 / 128)

    def test_paired_summary(self):
        p = bm.paired_summary({1: 5, 2: -1, 3: 0, 4: None}, {1: 7, 2: 1, 3: 0, 4: 2}, [1, 2, 3, 4],
                              bluff_score.new_rng())
        self.assertEqual(p["seeds"], [1, 2, 3])
        self.assertEqual(p["diffs"], [-2, -2, 0])
        self.assertAlmostEqual(p["mean"], -4 / 3)
        self.assertEqual(p["below"], 2)
        self.assertEqual(p["undefined_seeds"], [4])
        self.assertAlmostEqual(p["p"], 2 / 8 + 2 / 8)    # |mean| >= 4/3 when both -2s share a sign


class TestEndToEnd(unittest.TestCase):
    """Two groups (focal last), seeds 1-3, one seed missing, a spoiled game, an unfinished game."""

    GROUPS = [("Other moles", ["other"]), ("Focal moles", ["focal"])]

    def setUp(self):
        self.r = Root()
        for seed, (mv, cv) in {1: (60, 30), 2: (50, 40), 3: (70, 20)}.items():
            votes = {p: even(mv, cv, p) for p in "CDE"}
            self.r.add("other", seed, build([{"team": ["A", "C"], "sabotages": 1, "votes": votes}], seed=seed))
        for seed, (mv, cv) in {1: (30, 40), 2: (20, 40)}.items():
            votes = {p: even(mv, cv, p) for p in "CDE"}
            self.r.add("focal", seed, build([{"team": ["A", "C"], "sabotages": 1, "votes": votes}], seed=seed))
        self.r.add("focal", 4, build([{"team": ["A", "C"], "sabotages": 1, "votes": {"C": even(99, 0, "C")}}]),
                   spoiled=True)
        self.r.add("focal", 5, build([{"team": ["A", "C"], "sabotages": 1, "votes": {"C": even(99, 0, "C")}}],
                                     end=False))
        self.r.write()

    def tearDown(self):
        self.r.close()

    def test_analyse(self):
        out = bm.analyse(self.r.root, self.GROUPS, expected_seeds=(1, 2, 3), n_boot_match=200)
        self.assertEqual(out["seeds"], {"Other moles": [1, 2, 3], "Focal moles": [1, 2]})
        self.assertEqual(out["paired_seeds"], [1, 2])
        self.assertEqual(out["unpaired_seeds"], {3: ["Focal"]})
        self.assertFalse(out["full"])
        self.assertEqual(sorted(why for _, why in out["left_out"]), ["no game_end", "spoiled"])
        # Round-1 gaps: other +30, +10, +50; focal -10, -20. Paired seeds 1, 2: -40, -30.
        p = out["paired"][("crew", "r1", "Other moles")]
        self.assertEqual(p["diffs"], [-40, -30])
        self.assertEqual(p["below"], 2)
        self.assertAlmostEqual(out["per_model"][("crew", "r1", "Other moles")]["mean"], 30.0)
        # Every game-round sits in the same stratum (1, 0, 1, True): weights 2*3/5; diff -15 - 30.
        self.assertAlmostEqual(out["match"]["Other moles"]["diff"], -45.0)
        self.assertEqual(out["match"]["Other moles"]["share_a"], 1.0)
        for g in out["games"]["Focal moles"] + out["games"]["Other moles"]:
            self.assertTrue(g["same_as_bluff_score"])
        text = bm.render(out)
        self.assertIn("INTERIM", text)
        self.assertIn("left out of paired tests: seed 3 (missing for Focal)", text)
        json.dumps(bm.to_json(out))

    def test_fallback_game_flagged_against_bluff_score(self):
        votes = dict(R1_VOTES, D=even(100, 0, "D"))
        self.r.add("other", 9, build([{"team": ["A", "C", "D"], "sabotages": 1, "votes": votes,
                                       "fallback": {"D"}}]))
        self.r.write()
        res, _ = bm.load_groups(self.r.root, self.GROUPS)
        g = next(x for x in res["Other moles"] if x["seed"] == 9)
        self.assertFalse(g["same_as_bluff_score"])
        self.assertAlmostEqual(g["bluff_score_gap"], 400 / 6 - 160 / 6)
        self.assertAlmostEqual(g["whole"]["crew"], 10.0)

    def test_deterministic(self):
        a = bm.render(bm.analyse(self.r.root, self.GROUPS, expected_seeds=(1, 2, 3), n_boot_match=200))
        b = bm.render(bm.analyse(self.r.root, self.GROUPS, expected_seeds=(1, 2, 3), n_boot_match=200))
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
