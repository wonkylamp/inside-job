"""Clue generator: always true, never names the recipient, consistent-world logic, fallback."""

import random
import unittest

from inside_job.clues import (NONE_CLUE, candidate_clues, clue_is_true, consistent_worlds, generate_clue,
                              make_clue)
from inside_job.config import CLUE_STRENGTHS

from helpers import events_of, make_config, run_game

P = ["A", "B", "C", "D", "E", "F", "G"]


class ClueTruth(unittest.TestCase):
    def test_clue_is_true_each_kind(self):
        moles = {"A", "B"}
        cases = [
            (make_clue("at_least_one", ["A", "C"]), True), (make_clue("at_least_one", ["C", "D"]), False),
            (make_clue("at_least_one_of_three", ["C", "D", "B"]), True),
            (make_clue("at_least_one_of_three", ["C", "D", "E"]), False),
            (make_clue("exactly_k_of_three", ["A", "B", "C"], 2), True),
            (make_clue("exactly_k_of_three", ["A", "B", "C"], 1), False),
            (make_clue("exactly_k_of_three", ["C", "D", "E"], 0), True),
            (make_clue("same_side", ["A", "B"]), True), (make_clue("same_side", ["C", "D"]), True),
            (make_clue("same_side", ["A", "C"]), False),
            (make_clue("different_sides", ["A", "C"]), True), (make_clue("different_sides", ["A", "B"]), False),
            (make_clue("not_mole", ["C"]), True), (make_clue("not_mole", ["A"]), False),
        ]
        for clue, want in cases:
            self.assertEqual(clue_is_true(clue, moles), want, clue)

    def test_texts(self):
        self.assertEqual(make_clue("at_least_one", ["A", "B"])["text"], "At least one of A and B is a mole.")
        self.assertEqual(make_clue("exactly_k_of_three", ["A", "B", "C"], 2)["text"],
                         "Exactly two of A, B and C are moles.")
        self.assertEqual(make_clue("same_side", ["C", "D"])["text"], "C and D are on the same side.")
        self.assertEqual(make_clue("not_mole", ["E"])["text"], "E is not a mole.")


class ConsistentWorlds(unittest.TestCase):
    def test_excludes_recipient_and_respects_reveals_and_past_clues(self):
        w = consistent_worlds(players=P, num_moles=2, recipient="A", revealed={}, past_clues=[])
        self.assertEqual(len(w), 15)                      # C(6, 2)
        self.assertTrue(all("A" not in x for x in w))
        w = consistent_worlds(players=P, num_moles=2, recipient="A", revealed={"B": "mole", "C": "crew"},
                              past_clues=[])
        self.assertTrue(all("B" in x and "C" not in x for x in w))
        self.assertEqual(len(w), 4)                       # B plus one of D, E, F, G
        w = consistent_worlds(players=P, num_moles=2, recipient="A", revealed={"B": "mole", "C": "crew"},
                              past_clues=[make_clue("not_mole", ["D"])])
        self.assertEqual(len(w), 3)

    def test_mole_recipient_treated_as_crew(self):
        # A is really a mole, but A's consistent worlds never contain A.
        w = consistent_worlds(players=P, num_moles=2, recipient="A", revealed={}, past_clues=[])
        self.assertNotIn(frozenset({"A", "B"}), w)


class Generation(unittest.TestCase):
    def random_state(self, rng):
        n = rng.randint(4, 9)
        players = [f"P{i}" for i in range(n)]
        num_moles = rng.randint(1, (n - 1) // 2)
        moles = set(rng.sample(players, num_moles))
        out = rng.sample(players, rng.randint(0, max(0, n - 3)))
        # Keep at least one mole alive.
        out = [o for o in out if not (o in moles and len(moles - set(out)) <= 1)] if moles - set(out) else out[:0]
        alive = [p for p in players if p not in out]
        revealed = {o: ("mole" if o in moles else "crew") for o in out}
        return players, alive, moles, num_moles, revealed

    def test_property_true_alive_never_recipient(self):
        rng = random.Random(1234)
        nones = 0
        for trial in range(1500):
            players, alive, moles, k, revealed = self.random_state(rng)
            rec = rng.choice(alive)
            past = []
            for r in range(rng.randint(1, 4)):
                clue = generate_clue(rng=rng, players=players, alive=alive, moles=moles, num_moles=k,
                                     recipient=rec, revealed=revealed, past_clues=past,
                                     strength=rng.choice(list(CLUE_STRENGTHS)))
                self.assertTrue(clue_is_true(clue, moles), clue)
                self.assertNotIn(rec, clue["players"])
                self.assertTrue(set(clue["players"]) <= set(alive))
                if clue["kind"] == "none":
                    nones += 1
                    self.assertEqual(clue["text"], NONE_CLUE["text"])
                else:
                    worlds = consistent_worlds(players=players, num_moles=k, recipient=rec,
                                               revealed=revealed, past_clues=past)
                    surv = [w for w in worlds if clue_is_true(clue, w)]
                    self.assertGreaterEqual(len(surv), 2)
                    self.assertLess(len(surv), len(worlds))
                past.append(clue)
        self.assertGreater(nones, 0)

    def test_closest_ratio_chosen(self):
        rng = random.Random(5)
        for trial in range(200):
            moles = set(rng.sample(P, 2))
            rec = rng.choice(P)
            strength = rng.choice(list(CLUE_STRENGTHS))
            clue = generate_clue(rng=rng, players=P, alive=P, moles=moles, num_moles=2, recipient=rec,
                                 revealed={}, past_clues=[], strength=strength)
            worlds = consistent_worlds(players=P, num_moles=2, recipient=rec, revealed={}, past_clues=[])
            target = CLUE_STRENGTHS[strength]

            def dist(c):
                s = sum(1 for w in worlds if clue_is_true(c, w))
                return abs(s / len(worlds) - target)
            qualifying = [c for c in candidate_clues([p for p in P if p != rec], 2)
                          if clue_is_true(c, moles) and 2 <= sum(1 for w in worlds if clue_is_true(c, w)) < len(worlds)]
            self.assertAlmostEqual(dist(clue), min(dist(c) for c in qualifying))

    def test_none_when_no_candidate_qualifies(self):
        # Three alive, one mole left, recipient crew: only two worlds remain; any true clue
        # that removes a world leaves one, so nothing qualifies.
        players = ["A", "B", "C", "D", "E"]
        revealed = {"D": "mole", "E": "crew"}
        clue = generate_clue(rng=random.Random(0), players=players, alive=["A", "B", "C"], moles={"D", "B"},
                             num_moles=2, recipient="A", revealed=revealed, past_clues=[])
        self.assertEqual(clue["kind"], "none")
        # Fewer than two consistent worlds: none, without looking at candidates.
        clue = generate_clue(rng=random.Random(0), players=players, alive=["A", "B", "C"], moles={"D", "B"},
                             num_moles=2, recipient="A", revealed=revealed,
                             past_clues=[make_clue("not_mole", ["C"])])
        self.assertEqual(clue["kind"], "none")

    def test_clues_in_games_are_true_and_private(self):
        for seed in range(30):
            game, _ = run_game(seed, make_config())
            moles = {p.name for p in game.players if p.role == "mole"}
            for e in events_of(game.log.events, "clue"):
                self.assertEqual(e["vis"], "private")
                self.assertTrue(clue_is_true(e["clue"], moles))
                self.assertNotIn(e["player"], e["clue"]["players"])


if __name__ == "__main__":
    unittest.main()
