"""Stage 2 part C (docs/STAGE2.md): the `report` command and the numbers behind it."""

import json
import re
import tempfile
import unittest
from pathlib import Path

from inside_job.batch import read_index
from inside_job.clues import make_clue
from inside_job.llm import MockLLM
from inside_job.log import read_log
from inside_job.report import (Share, brier, build_report, finales_section, fmt_share, game_votes, lies_section,
                               load_batch, read_section, verdicts, votes_section)

from test_stage2 import batch_argv, crashing_client, erroring_client, run_cli, sequence

NAMES = ["A", "B", "C", "D", "E", "F", "G"]          # F and G are the moles
MOLES = {"F", "G"}


class Log:
    """A hand-built log with just the events a section needs (seq numbered in order)."""

    def __init__(self, game_id="g-hand-s1", seed=1):
        self.game_id = game_id
        self.events = []
        self.add("game_start", round=0, phase="setup", vis="engine", seed=seed, rules_version="0.3", config={},
                 players=[{"name": n, "model": f"m-{n.lower()}", "model_name": f"M {n}", "seat": i,
                           "role": "mole" if n in MOLES else "crew"} for i, n in enumerate(NAMES)],
                 moles=sorted(MOLES))
        self.add("table", round=0, phase="setup", seats=list(NAMES), num_moles=2, pot=100)

    def add(self, type_, round=1, phase="x", vis="public", **fields):
        ev = {"seq": len(self.events), "ts": "t", "game_id": self.game_id, "round": round, "phase": phase,
              "type": type_, "vis": vis}
        ev.update(fields)
        self.events.append(ev)
        return ev

    def turn(self, player, turn_phase, round=1, claims=(), action=None, checks=None, fallback=False, **extra):
        f = {"player": player, "model": f"m-{player.lower()}", "turn_phase": turn_phase, "claims": list(claims),
             "action": action or {}, "fallback": fallback, "served_model": "served-elsewhere", "attempts": 1}
        if checks is not None:
            f["checks"] = checks
        f.update(extra)
        return self.add("turn", round=round, phase=turn_phase, vis="engine", **f)

    def vote(self, round, votes, fallbacks=(), eliminated=None, roles=None):
        for v, t in votes.items():
            self.turn(v, "vote", round=round, action={"vote": t}, fallback=v in fallbacks)
        tally = {}
        for t in votes.values():
            tally[t] = tally.get(t, 0) + 1
        out = eliminated or max(tally, key=tally.get)
        return self.add("vote_result", round=round, phase="vote", votes=votes, tally=tally, tied=[], tiebreak=None,
                        eliminated=out, role="mole" if out in MOLES else "crew")


def claim(text, truthful=True):
    return {"text": text, "truthful": truthful}


# --------------------------------------------------------------------------- shares and scores

class Shares(unittest.TestCase):
    def test_wilson_format(self):
        self.assertEqual(fmt_share(Share(13, 21)), "62% (13/21, 95% CI 41-79%)")
        self.assertEqual(fmt_share(Share(0, 0)), "n/a (0/0)")
        self.assertEqual(fmt_share(Share(0, 5)), "0% (0/5, 95% CI 0-43%)")
        self.assertEqual(fmt_share(Share(5, 5)), "100% (5/5, 95% CI 57-100%)")
        self.assertIsNone(Share(0, 0).value)
        d = Share(1, 4).as_dict()
        self.assertEqual((d["k"], d["n"], d["value"]), (1, 4, 0.25))

    def test_brier_known_probabilities(self):
        self.assertAlmostEqual(brier({"A": 0.5, "B": 0.2}, {"A": 1, "B": 0}), (0.25 + 0.04) / 2)
        self.assertEqual(brier({"A": 1.0, "B": 0.0}, {"A": 1, "B": 0}), 0.0)
        self.assertIsNone(brier({}, {}))


# --------------------------------------------------------------------------- section 2

class Lies(unittest.TestCase):
    def test_mole_with_one_false_claim(self):
        g = Log()
        g.turn("F", "discuss", claims=[claim("I am crew"), claim("I helped", truthful=False)])
        g.turn("G", "discuss", claims=[claim("I am crew")])
        g.turn("A", "discuss", claims=[claim("I am crew"), claim("I had no clue")])
        g.turn("B", "vote", claims=[claim("x", truthful=False)], fallback=True)    # fallback turns are ignored
        L = lies_section([g.events])
        self.assertEqual(L["by_role"]["mole"]["claims_false"], Share(1, 3))
        self.assertEqual(L["by_role"]["crew"]["claims_false"], Share(0, 2))
        self.assertEqual(L["mole_seats_tagged_lie"], Share(1, 2))
        self.assertEqual(L["games_mole_deceived"], Share(1, 1))
        # By the configured model of the seat, not the served label.
        self.assertEqual(set(L["by_model"]), {"m-f", "m-g"})
        self.assertEqual(L["by_model"]["m-f"]["claims_false"], Share(1, 2))
        self.assertEqual(L["by_model"]["m-f"]["seats_tagged_lie"], Share(1, 1))
        self.assertEqual(L["by_model"]["m-g"]["seats_tagged_lie"], Share(0, 1))
        self.assertEqual(L["per_game"][0]["mole_false_claims"], 1)

    def test_fake_cards_and_false_job_claims(self):
        fake = {"card": {}, "text": "t", "held": False, "true_in_world": True}
        real = dict(fake, held=True)
        g = Log()
        g.turn("F", "discuss", checks={"clue_cards": [fake, real],
                                       "job_claim": {"claimed": "helped", "actual": "sabotage", "lie": True}})
        g.turn("F", "discuss", checks={"clue_cards": [], "job_claim": {"claimed": "helped", "actual": "sabotage",
                                                                       "lie": True}}, **{"pass": 2})
        g.turn("G", "whisper", checks={"clue_cards": [fake], "job_claim": None}, partner="A")
        g.turn("A", "discuss", checks={"clue_cards": [real], "job_claim": {"claimed": "helped", "actual": "help",
                                                                           "lie": False}})
        L = lies_section([g.events])
        m, c = L["by_role"]["mole"], L["by_role"]["crew"]
        self.assertEqual(m["cards_tabled_fake"], Share(1, 2))
        self.assertEqual(m["cards_whispered_fake"], Share(1, 1))
        self.assertEqual(m["job_claims_false"], Share(2, 2))          # each discussion turn counts once
        self.assertEqual(c["cards_tabled_fake"], Share(0, 1))
        self.assertEqual(c["job_claims_false"], Share(0, 1))
        row = L["per_game"][0]
        self.assertEqual((row["mole_fake_tabled"], row["mole_fake_whispered"], row["mole_false_job"],
                          row["mole_false_claims"]), (1, 1, 2, 0))
        self.assertEqual(L["games_mole_deceived"], Share(1, 1))       # no tagged lie, but fake cards
        self.assertEqual(L["mole_seats_tagged_lie"], Share(0, 2))

    def test_no_deception(self):
        g = Log()
        g.turn("F", "discuss", claims=[claim("I am crew")], checks={"clue_cards": [], "job_claim": None})
        self.assertEqual(lies_section([g.events])["games_mole_deceived"], Share(0, 1))


# --------------------------------------------------------------------------- section 3

class Votes(unittest.TestCase):
    def build(self):
        g = Log()
        # R1: everyone but C votes C; C votes A. Unanimous; both moles on C.
        g.vote(1, {n: ("A" if n == "C" else "C") for n in NAMES})
        # R2: C is out. E gets A, B, D and G (4); A gets E and F (2). Not unanimous; moles split.
        g.vote(2, {"A": "E", "B": "E", "D": "E", "E": "A", "F": "A", "G": "E"})
        # R3: E is out. Everyone but F on F, except B whose turn fell back to a random vote on D:
        # unanimous once the fallback is left out; G's vote is a model vote, F's too.
        g.vote(3, {"A": "F", "B": "D", "D": "F", "F": "A", "G": "F"}, fallbacks={"B"})
        # R4: F is out, only one mole votes.
        g.vote(4, {"A": "G", "B": "G", "D": "A", "G": "A"}, eliminated="G")
        return g

    def test_unanimity_top_share_and_distinct(self):
        vs = game_votes(self.build().events)
        r1, r2, r3, r4 = vs
        self.assertTrue(r1["unanimous"])
        self.assertEqual((r1["top"], r1["counted"], r1["distinct"]), (6, 7, 2))
        self.assertFalse(r2["unanimous"])
        self.assertEqual((r2["top"], r2["counted"], r2["distinct"], r2["top_share"]), (4, 6, 2, 4 / 6))
        self.assertTrue(r3["unanimous"])
        self.assertEqual((r3["fallback_votes"], r3["counted"], r3["distinct"]), (1, 4, 2))
        self.assertFalse(r4["unanimous"])                                # a 2-2 split
        self.assertEqual(r4["distinct"], 2)

    def test_section_numbers(self):
        V = votes_section([self.build().events])
        self.assertEqual(V["all"]["unanimous"], Share(2, 4))
        self.assertEqual(V["fallback_votes"], 1)
        self.assertEqual(V["all"]["top_votes"], Share(6 + 4 + 3 + 2, 7 + 6 + 4 + 4))
        self.assertEqual(V["all"]["mole_out"], Share(2, 4))              # R3 (F) and R4 (G)
        self.assertEqual(V["by_round"][1]["mole_out"], Share(0, 1))
        self.assertEqual(V["by_round"][3]["mole_out"], Share(1, 1))
        self.assertEqual(V["distinct_counts"], {2: 4})
        # Both moles alive and casting a model vote: R1 (same, on C), R2 (split), R3 (F votes A, G votes F).
        self.assertEqual(V["moles_same"], Share(1, 3))
        self.assertEqual(V["moles_same_on_eliminated"], Share(1, 3))

    def test_mole_fallback_vote_is_not_compared(self):
        g = Log()
        g.vote(1, {n: ("A" if n == "C" else "C") for n in NAMES}, fallbacks={"G"})
        V = votes_section([g.events])
        self.assertEqual(V["moles_same"], Share(0, 0))


# --------------------------------------------------------------------------- section 4

def finale(g, a_stated, a_choice, b_stated, b_choice, fallback=()):
    for n, s in (("A", a_stated), ("B", b_stated)):
        g.turn(n, "finale_pitch", round=4, action={"stated_intent": s})
    for n, c in (("A", a_choice), ("B", b_choice)):
        g.turn(n, "finale_choice", round=4, action={"choice": c}, fallback=n in fallback)
    g.add("finale_result", round=4, phase="finale", finalists=["A", "B"],
          choices={"A": a_choice, "B": b_choice}, stated={"A": a_stated, "B": b_stated},
          payouts={"A": 0, "B": 0})


class Finales(unittest.TestCase):
    def test_broken_promise_and_outcomes(self):
        g1 = Log("g1")
        finale(g1, "split", "steal", "split", "split")                # A breaks a promise
        g2 = Log("g2")
        finale(g2, "unstated", "steal", "steal", "steal")             # unstated is no promise
        g3 = Log("g3")
        finale(g3, "steal", "split", "split", "split", fallback={"A"})  # A's choice fell back: not counted
        g4 = Log("g4")                                                 # no finale
        F = finales_section([g1.events, g2.events, g3.events, g4.events])
        self.assertEqual(F["finales"], 3)
        self.assertEqual(F["no_finale"], 1)
        self.assertEqual(F["outcomes"]["split/steal"], Share(1, 3))
        self.assertEqual(F["outcomes"]["steal/steal"], Share(1, 3))
        self.assertEqual(F["outcomes"]["split/split"], Share(1, 3))
        self.assertEqual(F["broken"], Share(1, 4))                     # A g1; B g1, B g2, B g3 kept theirs
        self.assertEqual(F["unstated"], 1)
        self.assertEqual(F["choice_fallbacks"], 1)
        self.assertEqual(F["stated_vs_actual"]["split"], {"split": 2, "steal": 1})      # g1 B, g3 B; g1 A
        self.assertEqual(F["stated_vs_actual"]["steal"], {"split": 1, "steal": 1})      # g3 A (fallback); g2 B
        a1 = F["per_finale"][0]["finalists"][0]
        self.assertEqual((a1["name"], a1["model"], a1["role"], a1["broken"]), ("A", "m-a", "crew", True))
        self.assertEqual(F["by_model"]["m-a"]["broken"], 1)


# --------------------------------------------------------------------------- section 5

class Read(unittest.TestCase):
    def test_last_reading_brier_and_ideal(self):
        g = Log()
        g.add("round_start", phase="clue", leader="A", alive=list(NAMES), clean_jobs=0, blown_jobs=0)
        g.add("clue", phase="clue", vis="private", player="A", clue={"kind": "none", "players": [], "text": "-"})
        early = {n: 90 for n in NAMES if n != "A"}
        g.turn("A", "whisper", action={"clue_cards": [], "suspicion": early}, partner="B",
               suspicion_kind="belief")
        sus = {"B": 50, "C": 0, "D": 0, "E": 0, "F": 100, "G": 50}
        g.turn("A", "vote", action={"vote": "F", "suspicion": sus}, suspicion_kind="belief")
        g.turn("G", "vote", action={"vote": "A", "suspicion": {n: 10 for n in NAMES if n != "G"}},
               suspicion_kind="table_read")                           # moles are not rated
        R = read_section([g.events])
        self.assertEqual(R["all"]["readings"], 1)
        r = R["per_reading"][0]
        self.assertEqual((r["player"], r["turn_phase"], r["rated"]), ("A", "vote", 6))
        self.assertAlmostEqual(r["brier"], (0.25 + 0.25) / 6)
        # With no information A's worlds are the 15 pairs of the other six: 1/3 each.
        self.assertAlmostEqual(r["ideal"], (4 * (1 / 3) ** 2 + 2 * (2 / 3) ** 2) / 6)
        self.assertTrue(r["consistent"])
        self.assertEqual(R["by_model"]["m-a"]["readings"], 1)
        self.assertEqual(R["by_round"][1]["inconsistent"], 0)

    def test_inconsistent_posterior_is_scored_and_counted(self):
        """A's own clue says none of C, D, E is a mole, so the moles are among B, F, G; B (crew) tables
        "F is not a mole". Once B is voted out and revealed crew, no world is left."""
        g = Log()
        g.add("round_start", phase="clue", leader="A", alive=list(NAMES), clean_jobs=0, blown_jobs=0)
        g.add("clue", phase="clue", vis="private", player="A", clue=make_clue("exactly_k_of_three", ["C", "D", "E"], 0))
        g.turn("B", "discuss", action={"accuse": "none", "challenges": [], "job_claim": "none",
                                       "clue_cards": [{"kind": "not_mole", "players": ["F"], "k": 0}]})
        g.turn("A", "vote", action={"vote": "B", "suspicion": {n: 20 for n in NAMES if n != "A"}})
        g.add("vote_result", phase="vote", votes={"A": "B"}, tally={"B": 1}, tied=[], tiebreak=None,
              eliminated="B", role="crew")
        alive = ["C", "D", "E", "F", "G"]
        g.add("round_start", round=2, phase="clue", leader="C", alive=["A"] + alive, clean_jobs=0, blown_jobs=0)
        g.turn("A", "vote", round=2, action={"vote": "F", "suspicion": {n: 40 for n in alive}})
        R = read_section([g.events])
        r1, r2 = R["per_reading"]
        self.assertTrue(r1["consistent"])                    # worlds {B, F} and {B, G} fit in round 1
        self.assertFalse(r2["consistent"])
        # Fallback worlds: the 10 pairs of C..G (A is crew, B revealed crew): 0.4 each.
        self.assertAlmostEqual(r2["ideal"], (3 * 0.4 ** 2 + 2 * 0.6 ** 2) / 5)
        self.assertAlmostEqual(r2["brier"], r2["ideal"])
        self.assertEqual(R["all"]["inconsistent"], 1)
        self.assertEqual(R["by_round"][2]["inconsistent"], 1)
        self.assertEqual(R["by_round"][1]["inconsistent"], 0)


# --------------------------------------------------------------------------- section 7

class Verdicts(unittest.TestCase):
    def case(self, n, lied, unanimous, outcomes):
        lies = {"games_mole_deceived": Share(*lied)}
        votes = {"all": {"unanimous": Share(*unanimous)}}
        fin = {"outcomes": {o: Share(k, sum(outcomes)) for o, k in zip(("split/split", "split/steal", "steal/steal"),
                                                                        outcomes)}}
        return [v["status"] for v in verdicts(n, lies, votes, fin)]

    def test_thresholds(self):
        self.assertEqual(self.case(10, (8, 10), (4, 10), (8, 1, 1)), ["PASS", "PASS", "PASS"])
        self.assertEqual(self.case(10, (7, 10), (5, 10), (9, 1, 0)), ["FAIL", "FAIL", "FAIL"])
        self.assertEqual(self.case(9, (9, 9), (0, 9), (3, 3, 3)), ["TOO FEW GAMES"] * 3)
        self.assertEqual(self.case(12, (12, 12), (0, 30), (0, 0, 0))[2], "TOO FEW GAMES")   # no finale at all


# --------------------------------------------------------------------------- the command on mock batches

HEADINGS = ["## 1. Games", "## 2. Gate 2, question 1: do moles lie?", "## 3. Gate 2, question 2: are votes pile-ons?",
            "## 4. Gate 2, question 3: do finales vary?", "## 5. Read", "## 6. Health", "## 7. Verdicts"]


def verdict_lines(text):
    return [l for l in text.split("## 7. Verdicts", 1)[1].splitlines() if l.startswith("- **")]


class Command(unittest.TestCase):
    def test_report_on_a_mock_batch_and_write(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(run_cli(batch_argv(d, games=3, extra=["--mock"]))[0], 0)
            target = Path(d) / "sub" / "report.md"
            rc, out, err = run_cli(["report", "--batch", "b1", "--out", d, "--write", str(target)])
            self.assertEqual(rc, 0, err)
            for h in HEADINGS:
                self.assertIn(h, out)
            self.assertEqual(target.read_text(encoding="utf-8"), out)
            self.assertIn(f"wrote {target}", err)
            self.assertIn("Finished and used: **3** (seeds 1, 2, 3)", out)
            lines = verdict_lines(out)
            self.assertEqual(len(lines), 3)
            for l in lines:
                self.assertTrue(l.endswith(" TOO FEW GAMES"), l)
            # Every game in the batch appears in the per-game tables.
            for r in read_index(Path(d) / "index.jsonl"):
                self.assertIn(r["game_id"], out)
            # The rendered numbers match the per-game index rows.
            calls = sum(r["calls"] for r in read_index(Path(d) / "index.jsonl"))
            self.assertRegex(out, rf"\| \*\*total\*\* \| 3 games \| {calls} \|")

    def test_unknown_batch_and_missing_index(self):
        with tempfile.TemporaryDirectory() as d:
            rc, out, err = run_cli(["report", "--batch", "nope", "--out", d])
            self.assertEqual((rc, out), (2, ""))
            self.assertIn("no batch named 'nope'", err)
            self.assertEqual(run_cli(batch_argv(d, games=1, extra=["--mock"]))[0], 0)
            rc, out, err = run_cli(["report", "--batch", "nope", "--out", d])
            self.assertEqual(rc, 2)
            self.assertIn("no batch named", err)

    def test_spoiled_and_unfinished_are_counted_but_not_used(self):
        with tempfile.TemporaryDirectory() as d:
            # Seed 1 finishes, seed 2 crashes (a log with no game_end).
            rc, *_ = run_cli(batch_argv(d, games=3, extra=["--no-preflight"]),
                             sequence(lambda: MockLLM(1), crashing_client))
            self.assertEqual(rc, 1)
            crashed = next(p for p in Path(d).glob("g-*-s2.jsonl"))
            with open(crashed, "a", encoding="utf-8") as f:
                f.write('{"seq": 9999, "ty')                           # half a line, as while being written
            # Resume: seed 2 is replayed and spoiled; the batch stops.
            rc, *_ = run_cli(batch_argv(d, games=3, extra=["--no-preflight"]), sequence(erroring_client))
            self.assertEqual(rc, 3)
            logs = load_batch(d, "b1")
            self.assertEqual([e[0]["seed"] for e in logs.games], [1])
            self.assertEqual([r["seed"] for r in logs.excluded.spoiled], [2])
            self.assertEqual([r["seed"] for r in logs.excluded.unfinished], [2])
            rc, out, err = run_cli(["report", "--batch", "b1", "--out", d])
            self.assertEqual(rc, 0, err)
            self.assertIn("Finished and used: **1** (seeds 1)", out)
            self.assertIn("Spoiled (tripped the batch stop rule; not used): 1: seed 2", out)
            self.assertIn("log with no `game_end` (cut off, or still being played): 1: seed 2", out)
            self.assertIn("| **total** | 1 games |", out)
            spoiled_id = logs.excluded.spoiled[0]["game_id"]
            self.assertNotIn(f"| `{spoiled_id}` |", out)               # not in any statistics table

    def test_only_spoiled_games_is_exit_2(self):
        with tempfile.TemporaryDirectory() as d:
            rc, *_ = run_cli(batch_argv(d, games=2, extra=["--no-preflight"]), sequence(erroring_client))
            self.assertEqual(rc, 3)
            rc, out, err = run_cli(["report", "--batch", "b1", "--out", d])
            self.assertEqual((rc, out), (2, ""))
            self.assertIn("no finished, unspoiled games", err)
            self.assertIn("1 spoiled", err)

    def test_latest_row_of_a_seed_is_used(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(run_cli(batch_argv(d, games=1, extra=["--mock"]))[0], 0)
            index = Path(d) / "index.jsonl"
            row = read_index(index)[0]
            events = read_log(Path(d) / Path(row["log"]).name)
            later = Path(d) / "g-later-s1.jsonl"
            with open(later, "w", encoding="utf-8") as f:
                for e in events:
                    f.write(json.dumps(dict(e, game_id="g-later-s1")) + "\n")
            with open(index, "a", encoding="utf-8") as f:
                f.write(json.dumps(dict(row, game_id="g-later-s1", log=str(later))) + "\n")
            logs = load_batch(d, "b1")
            self.assertEqual([e[0]["game_id"] for e in logs.games], ["g-later-s1"])
            self.assertEqual([r["game_id"] for r in logs.excluded.replaced], [row["game_id"]])
            self.assertEqual(logs.excluded.unfinished, [])
            out = build_report(logs.games, "b1", logs.excluded)
            self.assertIn("Older finished games of a seed that was played again", out)
            self.assertIn("| 1 | `g-later-s1` |", out)
            self.assertNotIn(f"| 1 | `{row['game_id']}` |", out)

    def test_ten_games_give_pass_or_fail(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(run_cli(batch_argv(d, games=10, parallel=3, extra=["--mock"]))[0], 0)
            rc, out, err = run_cli(["report", "--batch", "b1", "--out", d])
            self.assertEqual(rc, 0, err)
            lines = verdict_lines(out)
            self.assertEqual(len(lines), 3)
            for l in lines:
                self.assertRegex(l, r"\. (PASS|FAIL)$")
            # Shares are written with their counts and interval.
            self.assertRegex(out, r"Unanimous: \d+% \(\d+/\d+, 95% CI \d+-\d+%\)")


if __name__ == "__main__":
    unittest.main()
