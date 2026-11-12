"""Clip finder (analysis/clip_finder.py): detectors on small synthetic logs, skips, score order,
verbatim quotes, and the known moments in the frontier logs when those are present."""

from __future__ import annotations

import contextlib
import io
import json
import random
import tempfile
import unittest
from pathlib import Path

from analysis import clip_finder as CF

ROOT = Path(__file__).resolve().parent.parent

# A, B moles; C, D, E crew.
CAST = {"A": ("openai/gpt-6-astra", "mole"), "B": ("x-ai/grok-4.7", "mole"),
        "C": ("claude-opus-5-5", "crew"), "D": ("claude-fable-5-2", "crew"),
        "E": ("moonshotai/kimi-k3.1-pro", "crew")}


class Log:
    """Builds a small event list with increasing seq numbers."""

    def __init__(self, game_id="g-test-s1", seed=1):
        self.events = []
        self.add("game_start", 0, game_id=game_id, seed=seed,
                 players=[{"name": n, "model": m, "role": r} for n, (m, r) in CAST.items()])
        self.add("table", 0, seats=list(CAST), num_moles=2, pot=100)
        for n, (_, r) in CAST.items():
            self.add("role", 0, player=n, role=r)

    def add(self, type_, rnd, **fields):
        e = {"seq": len(self.events), "round": rnd, "type": type_, "game_id": "g-test-s1"}
        e.update(fields)
        self.events.append(e)
        return e

    def turn(self, rnd, player, phase, public="", conf="", claims=None, action=None, fallback=False, checks=None,
             usage=None):
        e = self.add("turn", rnd, player=player, model=CAST[player][0], turn_phase=phase, public=public,
                     confessional=conf, claims=claims or [], action=action or {}, fallback=fallback)
        if checks is not None:
            e["checks"] = checks
        if usage is not None:
            e["usage"] = usage
        return e

    def vote(self, rnd, votes, eliminated):
        tally = {}
        for v in votes.values():
            tally[v] = tally.get(v, 0) + 1
        return self.add("vote_result", rnd, votes=votes, tally=tally, tied=[], tiebreak=None,
                        eliminated=eliminated, role=CAST[eliminated][1])

    def end(self, winner="crew"):
        return self.add("game_end", 9, winner=winner, reason="test")


def lie(text="I helped on the job"):
    return [{"text": text, "truthful": False}]


def kinds(clips):
    return [c["kind"] for c in clips]


def run_detector(det, log):
    return det(CF.Game(log.events, batch="t", folder="games"))


class TestFinale(unittest.TestCase):
    def finale(self, choices, stated, payouts, fallback_choice=False):
        log = Log()
        log.turn(3, "C", "finale_pitch", public="D, I'll split. Fifty each.", conf="I will steal.",
                 claims=lie("I will split"), action={"stated_intent": stated["C"]})
        log.turn(3, "D", "finale_pitch", public="Split with me, C.", conf="I split.",
                 action={"stated_intent": stated["D"]})
        log.turn(3, "C", "finale_choice", conf="My promise was a deliberate lie. Taking the 100.",
                 action={"choice": choices["C"]}, fallback=fallback_choice)
        log.turn(3, "D", "finale_choice", conf="Keeping my word.", action={"choice": choices["D"]})
        log.add("finale_result", 3, finalists=["C", "D"], choices=choices, stated=stated, payouts=payouts)
        return log

    def test_broken_promise_fires(self):
        log = self.finale({"C": "steal", "D": "split"}, {"C": "split", "D": "split"}, {"C": 100, "D": 0})
        clips = run_detector(CF.detect_broken_promise, log)
        self.assertEqual(len(clips), 1)
        c = clips[0]
        self.assertEqual(c["speaker"], "C")
        self.assertEqual(c["public"], "D, I'll split. Fifty each.")
        self.assertEqual(c["diary"], "My promise was a deliberate lie. Taking the 100.")
        self.assertEqual(c["diary_from"]["phase"], "finale_choice")
        self.assertIn("Opus 5.5 (C, crew) promises to split, then takes all 100", c["headline"])
        self.assertTrue(c["contradicts"])
        self.assertEqual(run_detector(CF.detect_mutual_steal, log), [])

    def test_honest_steal_is_not_a_broken_promise(self):
        log = self.finale({"C": "steal", "D": "split"}, {"C": "steal", "D": "split"}, {"C": 100, "D": 0})
        self.assertEqual(run_detector(CF.detect_broken_promise, log), [])

    def test_fallback_choice_does_not_fire(self):
        log = self.finale({"C": "steal", "D": "split"}, {"C": "split", "D": "split"}, {"C": 100, "D": 0},
                          fallback_choice=True)
        self.assertEqual(run_detector(CF.detect_broken_promise, log), [])

    def test_mutual_steal(self):
        log = self.finale({"C": "steal", "D": "steal"}, {"C": "split", "D": "split"}, {"C": 0, "D": 0})
        clips = run_detector(CF.detect_mutual_steal, log)
        self.assertEqual(kinds(clips), ["mutual_steal"])
        self.assertIn("both promise to split and both steal: nobody is paid", clips[0]["headline"])
        self.assertEqual([x["text"] for x in clips[0]["extra"]], ["Split with me, C.", "Keeping my word."])
        self.assertEqual(run_detector(CF.detect_broken_promise, log), [])   # the mirror replaces it
        log2 = self.finale({"C": "steal", "D": "split"}, {"C": "split", "D": "split"}, {"C": 100, "D": 0})
        self.assertEqual(run_detector(CF.detect_mutual_steal, log2), [])


class TestRoundDetectors(unittest.TestCase):
    def test_believed_lie(self):
        log = Log()
        log.turn(1, "A", "discuss", public="I helped. C blew it.", conf="I sabotaged; blaming C.",
                 claims=lie(), action={"accuse": "C"})
        log.turn(1, "D", "vote", public="Voting C.", action={"vote": "C", "suspicion": {"A": 10, "C": 60}})
        log.turn(1, "E", "vote", public="Voting C.", action={"vote": "C", "suspicion": {"A": 20, "C": 70}})
        log.vote(1, {"A": "C", "D": "C", "E": "C", "C": "A", "B": "C"}, "C")
        clips = run_detector(CF.detect_believed_lie, log)
        self.assertEqual(kinds(clips), ["believed_lie"])
        c = clips[0]
        self.assertTrue(c["facts"]["named_the_eliminated"])
        self.assertEqual(c["facts"]["crew_suspicion_at_vote"], 15.0)
        self.assertEqual({b[0] for b in c["_bonuses"]},
                         {"accusation named who went out", "crew suspicion at the vote 15.0%"})
        self.assertIn("4–1", c["headline"])

    def test_believed_lie_needs_crew_out_and_a_false_tag(self):
        log = Log()
        log.turn(1, "A", "discuss", public="I helped.", conf="I sabotaged.", claims=lie(), action={"accuse": "B"})
        log.vote(1, {"C": "B", "D": "B", "E": "B"}, "B")   # a mole went out: not believed
        self.assertEqual(run_detector(CF.detect_believed_lie, log), [])
        log = Log()
        log.turn(1, "A", "discuss", public="I helped.", conf="I helped.",
                 claims=[{"text": "I helped", "truthful": True}], action={"accuse": "C"})
        log.vote(1, {"A": "C", "D": "C", "E": "C"}, "C")
        self.assertEqual(run_detector(CF.detect_believed_lie, log), [])

    def test_fallback_turn_is_never_quoted(self):
        log = Log()
        log.turn(1, "A", "discuss", public="I helped. C blew it.", conf="", claims=lie(),
                 action={"accuse": "C"}, fallback=True)
        log.vote(1, {"A": "C", "D": "C", "E": "C"}, "C")
        self.assertEqual(run_detector(CF.detect_believed_lie, log), [])

    def test_right_accuser_out(self):
        log = Log()
        log.turn(1, "C", "discuss", public="A sabotaged. Vote A.", conf="A is the mole.", action={"accuse": "A"})
        log.vote(1, {"A": "C", "B": "C", "D": "C", "C": "A", "E": "A"}, "C")
        clips = run_detector(CF.detect_right_accuser_out, log)
        self.assertEqual(kinds(clips), ["right_accuser_out"])
        self.assertIn("names Gpt 6 Astra (A, mole) and is voted out 3–2", clips[0]["headline"])
        log = Log()
        log.turn(1, "C", "discuss", public="D sabotaged. Vote D.", conf="D?", action={"accuse": "D"})
        log.vote(1, {"A": "C", "B": "C", "D": "C", "C": "D", "E": "D"}, "C")
        self.assertEqual(run_detector(CF.detect_right_accuser_out, log), [])

    def sabotage_log(self, b_choice):
        log = Log()
        log.add("whisper_pairs", 2, pairs=[["A", "B"], ["C", "D"]])
        log.turn(2, "A", "whisper", public="Pick yourself, C and D, then sabotage.", conf="B should strike.")
        log.turn(2, "C", "whisper", public="Do not sabotage anything, D.", conf="Crew talk.")
        log.turn(2, "B", "job", conf="As agreed, I sabotage.", action={"choice": b_choice})
        log.add("job_choices", 2, choices={"B": b_choice, "C": "help", "D": "help"})
        log.add("job_result", 2, team=["B", "C", "D"], sabotages=int(b_choice == "sabotage"),
                blown=b_choice == "sabotage")
        return log

    def test_sabotage_on_instruction(self):
        clips = run_detector(CF.detect_sabotage_on_instruction, self.sabotage_log("sabotage"))
        self.assertEqual(kinds(clips), ["sabotage_on_instruction"])
        c = clips[0]
        self.assertEqual((c["speaker"], c["facts"]["instructed"]), ("A", "B"))
        self.assertEqual(c["extra"][0]["text"], "As agreed, I sabotage.")
        self.assertEqual(run_detector(CF.detect_sabotage_on_instruction, self.sabotage_log("help")), [])

    def invent_log(self, card_players, held):
        log = Log()
        log.add("clue", 2, player="A", clue={"kind": "at_least_one", "players": ["C", "E"],
                                             "text": "At least one of C and E is a mole."})
        log.turn(2, "A", "discuss", public="My clue: at least one of D and E is a mole.", conf="Inventing a clue.",
                 claims=lie("My clue says D or E"), action={"accuse": "D", "clue_cards": [
                     {"kind": "at_least_one", "players": card_players, "k": 0}]},
                 checks={"clue_cards": [{"text": f"At least one of {' and '.join(card_players)} is a mole.",
                                         "held": held, "true_in_world": False}]})
        log.vote(2, {"A": "D", "B": "D", "C": "D"}, "D")
        return log

    def test_invented_evidence(self):
        clips = run_detector(CF.detect_invented_evidence, self.invent_log(["D", "E"], False))
        self.assertEqual(kinds(clips), ["invented_evidence"])
        self.assertIn("tables a clue never dealt at the table", clips[0]["headline"])
        self.assertEqual(clips[0]["facts"]["dealt_this_round"], ["At least one of C and E is a mole."])
        # The card matches a clue the mole really holds: not invented.
        self.assertEqual(run_detector(CF.detect_invented_evidence, self.invent_log(["C", "E"], True)), [])

    def test_catch(self):
        log = Log()
        log.turn(2, "C", "discuss", public="A blew it. " + "Long reasoning. " * 60, conf="A is a mole.",
                 action={"accuse": "A"})
        log.turn(2, "D", "discuss", public="Vote A.", conf="A for sure.", action={"accuse": "A"})
        log.turn(2, "E", "discuss", public="Vote C.", conf="Hmm.", action={"accuse": "C"})
        log.vote(2, {"C": "A", "D": "A", "E": "A", "B": "C"}, "A")
        clips = CF.find_clips(log.events, "t", "games")
        catches = [c for c in clips if c["kind"] == "catch"]
        self.assertEqual(len(catches), 1)       # one per round: the best-scoring accusation
        self.assertEqual(catches[0]["speaker"], "D")
        log = Log()
        log.turn(2, "D", "discuss", public="Vote A.", conf="A.", action={"accuse": "A"})
        log.vote(2, {"C": "E", "D": "E", "A": "E"}, "E")
        self.assertEqual(run_detector(CF.detect_catch, log), [])

    def test_partner_turned(self):
        log = Log()
        log.turn(1, "A", "discuss", public="B is lying. Vote B.", conf="Bussing my partner to look clean.",
                 action={"accuse": "B"})
        log.vote(1, {"A": "B", "C": "B", "D": "B"}, "B")
        clips = run_detector(CF.detect_partner_turned, log)
        self.assertEqual(kinds(clips), ["partner_turned"])
        self.assertIn("accuses own partner Grok 4.7 (B, mole)", clips[0]["headline"])
        log = Log()
        log.turn(1, "A", "discuss", public="C is lying.", conf="Framing C.", action={"accuse": "C"})
        log.turn(1, "A", "vote", public="Voting C.", conf="C.", action={"vote": "C"})
        self.assertEqual(run_detector(CF.detect_partner_turned, log), [])


class TestScoreAndOutput(unittest.TestCase):
    def full_log(self, game_id="g-test-s1", folder_name="games"):
        log = Log(game_id=game_id)
        log.events[0]["game_id"] = game_id
        for e in log.events:
            e["game_id"] = game_id
        log.turn(1, "A", "discuss", public="I helped. C blew it.", conf="I sabotaged; blaming C.",
                 claims=lie(), action={"accuse": "C"})
        log.turn(1, "C", "discuss", public="A sabotaged. Vote A.", conf="A is the mole.", action={"accuse": "A"})
        log.turn(1, "B", "discuss", public="Long. " * 150, conf="I lie a lot.", claims=lie("x"),
                 action={"accuse": "C"})
        log.vote(1, {"A": "C", "B": "C", "D": "C", "C": "A", "E": "A"}, "C")
        log.end()
        return log

    def test_order_is_deterministic(self):
        clips = CF.find_clips(self.full_log().events, "t", "games")
        again = CF.find_clips(self.full_log().events, "t", "games")
        self.assertEqual([CF.public_record(c) for c in clips], [CF.public_record(c) for c in again])
        self.assertEqual([c["score"] for c in clips], sorted((c["score"] for c in clips), reverse=True))
        long_one = next(c for c in clips if c["speaker"] == "B")
        self.assertTrue(long_one["long"])
        self.assertEqual(long_one["public"], "Long. " * 150)          # flagged, never cut
        recs = [{"score": 5, "game_id": g, "round": r, "_seq": s, "kind": "catch"}
                for g in ("g-b", "g-a") for r in (2, 1) for s in (9, 3)]
        want = sorted(recs, key=lambda c: (c["game_id"], c["round"], c["_seq"]))
        for seed in range(5):
            shuffled = recs[:]
            random.Random(seed).shuffle(shuffled)
            self.assertEqual(sorted(shuffled, key=CF.sort_key), want)

    def test_score_rule(self):
        c = {"kind": "broken_promise", "contradicts": True, "long": False, "_bonuses": []}
        self.assertEqual(CF.score_clip(dict(c), frontier=True)["score"],
                         CF.KIND_WEIGHT["broken_promise"] + CF.BONUS_CONTRADICTS + CF.BONUS_FITS + CF.BONUS_FRONTIER)
        c.update(contradicts=False, long=True)
        self.assertEqual(CF.score_clip(dict(c), frontier=False)["score"],
                         CF.KIND_WEIGHT["broken_promise"] - CF.PENALTY_LONG)

    def write_folder(self, root: Path, name: str, rows_logs):
        folder = root / name
        folder.mkdir()
        with open(folder / "index.jsonl", "w") as idx:
            for row, events in rows_logs:
                path = folder / f"{row['game_id']}.jsonl"
                path.write_text("".join(json.dumps(e) + "\n" for e in events))
                idx.write(json.dumps(dict(row, log=str(path))) + "\n")
        return folder

    def test_skips_spoiled_mock_and_unfinished(self):
        good = self.full_log("g-good")
        spoiled = self.full_log("g-spoiled")
        unfinished = self.full_log("g-open")
        unfinished.events.pop()      # no game_end
        mock = self.full_log("g-mock")
        for e in mock.events:
            if e["type"] == "turn":
                e["usage"] = {"output": 0, "thinking": 0}
        with tempfile.TemporaryDirectory() as td:
            folder = self.write_folder(Path(td), "games", [
                ({"game_id": "g-good", "batch": "b1"}, good.events),
                ({"game_id": "g-spoiled", "batch": "b1", "spoiled": True}, spoiled.events),
                ({"game_id": "g-open", "batch": "b1"}, unfinished.events),
                ({"game_id": "g-mock", "batch": "b1"}, mock.events)])
            skipped = {}
            loaded = CF.load_folder(folder, None, skipped)
            self.assertEqual([CF.Game(ev).game_id for _, _, ev in loaded], ["g-good"])
            self.assertEqual(skipped, {"spoiled": ["g-spoiled"], "unfinished": ["g-open"], "mock": ["g-mock"]})
            self.assertEqual(CF.load_folder(folder, {"other"}, {}), [])

    def test_quotes_in_output_are_verbatim(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            f1 = self.write_folder(root, "games_frontier", [({"game_id": "g-front", "batch": "fr"},
                                                             self.full_log("g-front").events)])
            f2 = self.write_folder(root, "games", [({"game_id": "g-other", "batch": "p"},
                                                    self.full_log("g-other").events)])
            md_path, js_path = root / "out" / "clips.md", root / "out" / "clips.json"
            with contextlib.redirect_stderr(io.StringIO()):
                rc = CF.main(["--games", str(f1), "--games", str(f2), "--top", "3",
                              "--out", str(md_path), "--json", str(js_path)])
            self.assertEqual(rc, 0)
            md, recs = md_path.read_text(), json.loads(js_path.read_text())
            self.assertTrue(recs)
            logs = {p.stem: p.read_text() for p in root.glob("*/g-*.jsonl")}
            for c in recs:
                events = [json.loads(line) for line in logs[c["game_id"]].splitlines()]
                for field, src in (("public", "public_from"), ("diary", "diary_from")):
                    if not c[field]:
                        continue
                    ev = next(e for e in events if e["seq"] == c[src]["seq"])
                    self.assertEqual(c[field], ev["public" if field == "public" else "confessional"])
                    self.assertIn(json.dumps(c[field])[1:-1], logs[c["game_id"]])
                    self.assertIn(f"> {c[field]}\n", md)
                port = "8766" if c["game_id"] == "g-front" else "8765"
                self.assertEqual(c["viewer"], f"http://127.0.0.1:{port}/?game={c['game_id']}")
                self.assertEqual(c["reading_s"], round((len(c["public"].split()) + len(c["diary"].split())) / 2.5, 1))
            self.assertIn("## Top 3 across all games", md)


FRONTIER = ROOT / "games_frontier" / "index.jsonl"


@unittest.skipUnless(FRONTIER.is_file(), "frontier logs not present")
class TestKnownFrontierMoments(unittest.TestCase):
    """The moments the lead named, on the real logs (read-only)."""

    @classmethod
    def setUpClass(cls):
        cls.clips = {}
        for batch, folder, events in CF.load_folder(FRONTIER.parent, None, {}):
            g = CF.Game(events)
            cls.clips[g.game_id[-4:]] = CF.find_clips(events, batch, folder)

    def has(self, game, kind, rnd=None, speaker=None, diary_part=None):
        for c in self.clips[game]:
            if c["kind"] == kind and (rnd is None or c["round"] == rnd) and (speaker is None or c["speaker"] == speaker) \
                    and (diary_part is None or diary_part in c["diary"]):
                return c
        self.fail(f"{game}: no {kind} round {rnd} by {speaker}")

    def test_s204(self):
        c = self.has("s204", "broken_promise", 3, "Ember", "My reassurance was a deliberate lie.")
        self.assertIn("takes all 100 from Opus 5.5 (Cipher, crew)", c["headline"])
        c = self.has("s204", "right_accuser_out", 1, "Slate")
        self.assertIn("names Fable 5.2 (Quill, mole) and is voted out 4–2–1", c["headline"])
        self.has("s204", "invented_evidence", 2, "Sable")
        self.has("s204", "catch", 2)
        self.has("s204", "catch", 3)

    def test_s202_and_s203(self):
        self.has("s202", "broken_promise", 2, "Cipher")
        c = self.has("s203", "sabotage_on_instruction", 3, "Ghost")
        self.assertEqual(c["public"].split(".")[0], "Pick yourself, Rook and Cipher, then sabotage")
        self.has("s203", "mutual_steal", 3)


if __name__ == "__main__":
    unittest.main()
