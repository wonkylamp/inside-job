"""The ideal reasoner: worlds logic on hand-built cases, from_log viewpoints, and the solve command."""

import contextlib
import io
import re
import unittest

from inside_job import __main__ as cli
from inside_job.clues import make_clue
from inside_job.log import visible_to
from inside_job.solver import from_log, player_worlds, posterior, table_posterior, table_worlds

from helpers import DEFAULT_TOML, make_config, run_game

P = ["A", "B", "C", "D", "E"]


def W(*names):
    return frozenset(names)


class Worlds(unittest.TestCase):
    def test_no_information(self):
        self.assertEqual(len(table_worlds(P, 2, {}, [], [])), 10)

    def test_mole_card_ignored_in_its_own_world(self):
        # A claims "B is not a mole". In worlds where A is a mole the card binds nothing.
        cards = [("A", make_clue("not_mole", ["B"]))]
        ws = set(table_worlds(P, 2, {}, cards, []))
        self.assertIn(W("A", "B"), ws)                  # A a mole: card free to be false
        self.assertNotIn(W("B", "C"), ws)               # A crew: card binds, B cannot be a mole
        self.assertIn(W("C", "D"), ws)
        self.assertEqual(len(ws), 7)                    # 10 minus {B,C},{B,D},{B,E}

    def test_blown_job_constraint(self):
        ws = table_worlds(P, 2, {}, [], [(["A", "B", "C"], 2)])
        self.assertEqual(set(ws), {W("A", "B"), W("A", "C"), W("B", "C")})
        ws = table_worlds(P, 2, {}, [], [(["A", "B", "C"], 0)])  # a clean job says nothing
        self.assertEqual(len(ws), 10)
        ws = table_worlds(P, 2, {}, [], [(["A", "B"], 1)])
        self.assertTrue(all(w & {"A", "B"} for w in ws))
        self.assertEqual(len(ws), 7)

    def test_reveal_constraint(self):
        ws = table_worlds(P, 2, {"A": "mole", "B": "crew"}, [], [])
        self.assertEqual(set(ws), {W("A", "C"), W("A", "D"), W("A", "E")})

    def test_player_worlds(self):
        own = [make_clue("same_side", ["B", "C"])]
        ws = player_worlds(P, 2, {}, [], [], player="A", own_clues=own)
        self.assertTrue(all("A" not in w for w in ws))
        self.assertEqual(set(ws), {W("B", "C"), W("D", "E")})
        # A whisper card from C, "D is not a mole": binds where C is crew ({D,E} goes), not in {B,C}.
        pair = [("C", make_clue("not_mole", ["D"]))]
        ws = player_worlds(P, 2, {}, [], [], player="A", own_clues=own, pair_cards=pair)
        self.assertEqual(set(ws), {W("B", "C")})

    def test_posterior_and_inconsistent_fallback(self):
        p = posterior([W("A", "B"), W("A", "C")], P)
        self.assertEqual((p["A"], p["B"], p["D"]), (1.0, 0.5, 0.0))
        self.assertTrue(p.consistent)
        self.assertEqual(p.worlds, 2)
        # Two crew-side cards that cannot both hold: no world fits, so fall back to reveals + jobs.
        cards = [("D", make_clue("not_mole", ["A"])), ("E", make_clue("exactly_k_of_three", ["A", "B", "C"], 2))]
        jobs = [(["A", "D"], 1)]                       # D is revealed crew, so A is a mole: D's card is false
        worlds = table_worlds(["A", "B", "C", "D", "E"], 2, {"D": "crew", "E": "crew"}, cards, jobs)
        self.assertEqual(worlds, [])
        p = table_posterior({"players": P, "num_moles": 2, "revealed": {"D": "crew", "E": "crew"}, "cards": cards,
                             "jobs": jobs, "player": None})
        self.assertFalse(p.consistent)
        self.assertEqual(p.worlds, 2)                   # {A,B},{A,C}
        self.assertEqual((p["A"], p["B"], p["D"]), (1.0, 0.5, 0.0))


class FromLog(unittest.TestCase):
    def test_viewpoints_use_only_visible_events(self):
        def discuss(s, player, schema, prompt):
            from helpers import action_props, suspicion_for
            clue = s.game.clues_received[player][-1]
            cards = [] if clue["kind"] == "none" else [{"kind": clue["kind"], "players": clue["players"],
                                                       "k": clue.get("k", 0)}]
            return {"accuse": "none", "challenges": [], "clue_cards": cards, "job_claim": "none",
                    "suspicion": suspicion_for(schema)}
        from helpers import Script
        game, _ = run_game(3, make_config(clue_recipients=0), policy=Script(1, discuss=discuss))
        ev = game.log.events
        moles = {p.name for p in game.players if p.role == "mole"}
        t = from_log(ev, viewpoint="table")
        self.assertIsNone(t["player"])
        self.assertEqual(t["own_clues"], [])
        self.assertTrue(t["cards"])
        # The true world is always consistent when only crew cards are honest... unless a mole
        # tabled a true clue; in any case the table never sees private clues.
        me = next(p.name for p in game.players if p.role == "crew")
        pv = from_log(ev, viewpoint=me)
        mine = [e["clue"] for e in ev if e["type"] == "clue" and e["player"] == me]
        self.assertEqual(pv["own_clues"], mine)
        self.assertIn(frozenset(moles), table_worlds(pv["players"], 2, pv["revealed"],
                                                     [c for c in pv["cards"] if c[0] not in moles], pv["jobs"]))
        # upto_seq cuts the log.
        first_vote = next(e["seq"] for e in ev if e["type"] == "vote_result")
        early = from_log(ev, upto_seq=first_vote - 1, viewpoint="table")
        self.assertEqual(early["revealed"], {})


class SolveCommand(unittest.TestCase):
    def solve(self, *sets, deals=200):
        argv = ["solve", "--config", str(DEFAULT_TOML), "--deals", str(deals), "--rounds", "3"]
        for s in sets:
            argv += ["--set", s]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(argv), 0)
        text = out.getvalue()
        row3 = next(line for line in text.splitlines() if re.match(r"\s+3\s", line))
        return text, float(re.findall(r"([\d.]+)%", row3)[0])

    def test_defaults_are_hard_and_v02_settings_easy(self):
        text, solved = self.solve()
        self.assertIn("clue_strength weak", text)
        self.assertLess(solved, 40.0)
        text, solved = self.solve("clue_recipients=0", "clue_strength=normal")
        self.assertIn("clues to everyone", text)
        self.assertGreater(solved, 80.0)


if __name__ == "__main__":
    unittest.main()
