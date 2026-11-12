"""Whisper pairing, retries and fallbacks, usage accounting, suspicion, clue cards, The Cut."""

import random
import unittest

from inside_job.engine import Game
from inside_job.llm import LLMReply, MockLLM, random_valid, zero_usage
from inside_job.schemas import clean_reply, turn_schema

from helpers import (Script, action_props, events_of, job_choice, make_config, pick_with_mole,
                     pick_without_moles, run_game, turns, vote_moles, vote_with)

CAPS = {"confessional": 70, "public": 60, "memory": 60}


def fresh_game(cfg=None, seed=0):
    game = Game(cfg or make_config(), MockLLM(seed), seed, game_id="g")
    game.setup()
    return game


class WhisperPairing(unittest.TestCase):
    def test_mutual_requests_pair_first(self):
        game = fresh_game()
        a, b, c, d, e, f, g = game.seat_order()
        # c and d both want a; a and b want each other; e and f want each other.
        req = {a: b, b: a, c: a, d: a, e: f, f: e, g: "none"}
        for seed in range(20):
            game.rng = random.Random(seed)
            pairs = game.pair_whispers(req)
            self.assertEqual(pairs[:2], [[a, b], [e, f]])
            self.assertEqual(len(pairs), 2)                    # c and d asked for a, who is taken

    def test_one_whisper_per_player_and_cap(self):
        game = fresh_game()
        names = game.seat_order()
        rng = random.Random(1)
        for trial in range(300):
            req = {n: rng.choice([m for m in names if m != n] + ["none"]) for n in names}
            game.rng = random.Random(trial)
            pairs = game.pair_whispers(req)
            flat = [x for p in pairs for x in p]
            self.assertEqual(len(flat), len(set(flat)))
            self.assertLessEqual(len(pairs), 3)
            for initiator, target in pairs:
                # Every pair comes from a request (initiator asked for target).
                self.assertEqual(req[initiator], target)

    def test_pair_cap_respected(self):
        game = fresh_game(make_config(whisper_pairs_max=1))
        a, b, c, d, *_ = game.seat_order()
        pairs = game.pair_whispers({a: b, b: a, c: d, d: c})
        self.assertEqual(pairs, [[a, b]])

    def test_one_sided_request_cannot_be_refused(self):
        game = fresh_game()
        a, b, *_ = game.seat_order()
        self.assertEqual(game.pair_whispers({a: b, b: "none"}), [[a, b]])

    def test_whispers_off(self):
        cfg = make_config(whispers=False)
        game, llm = run_game(3, cfg)
        self.assertEqual(events_of(game.log.events, "whisper_pairs"), [])
        self.assertEqual(turns(game.log.events, "whisper"), [])
        for c in llm.calls:
            if c["phase"] == "clue":
                self.assertNotIn("whisper_with", action_props(c["schema"]))
                self.assertIn("suspicion", action_props(c["schema"]))
        self.assertIn("Whispers are switched off", llm.calls[0]["system"])


class RetryAndFallback(unittest.TestCase):
    def test_invalid_then_valid_retries_with_rejection_line(self):
        seen = {"n": 0}

        def policy(model, system, prompt, schema, phase, player):
            if phase == "clue" and seen["n"] == 0:
                seen["n"] += 1
                return {"confessional": "x"}                     # missing fields
            return None
        game, llm = run_game(1, policy=policy)
        clue_calls = [c for c in llm.calls if c["phase"] == "clue"]
        retried = [c for c in clue_calls if "Your previous reply was rejected:" in c["prompt"]]
        self.assertEqual(len(retried), 1)
        self.assertTrue(retried[0]["prompt"].rstrip().endswith("Reply again with valid JSON."))
        self.assertIn("missing", retried[0]["prompt"])
        t = [e for e in turns(game.log.events, "clue", 1) if e["attempts"] == 2]
        self.assertEqual(len(t), 1)
        self.assertFalse(t[0]["fallback"])
        self.assertEqual(len(t[0]["rejections"]), 1)

    def test_always_invalid_falls_back_and_is_flagged(self):
        def policy(model, system, prompt, schema, phase, player):
            if phase == "discuss":
                return {"nonsense": True}
            return None
        cfg = make_config()
        game, llm = run_game(2, cfg, policy=policy)
        ds = turns(game.log.events, "discuss")
        self.assertTrue(ds)
        for t in ds:
            self.assertTrue(t["fallback"])
            self.assertEqual(t["attempts"], cfg.limits.retries + 1)
            self.assertEqual(len(t["rejections"]), cfg.limits.retries + 1)
            sus = t["action"].pop("suspicion")
            self.assertEqual(t["action"], {"accuse": "none", "challenges": [], "clue_cards": [], "job_claim": "none"})
            self.assertEqual(len(set(sus.values())), 1)               # uniform fallback (v0.3)
            self.assertIsNone(t["statement_id"])
        self.assertEqual(game.log.events[-1]["fallbacks"], len(ds))
        # The rejection line is appended to the original prompt, not stacked.
        retries = [c["prompt"] for c in llm.calls if c["phase"] == "discuss" and "rejected" in c["prompt"]]
        self.assertTrue(all(p.count("Your previous reply was rejected") == 1 for p in retries))

    def test_fallbacks_for_every_phase(self):
        def policy(model, system, prompt, schema, phase, player):
            return None if phase == "recap" else {"bad": 1}
        cfg = make_config()
        for seed in range(6):
            game, _ = run_game(seed, cfg, policy=policy)
            end = game.log.events[-1]
            self.assertEqual(end["type"], "game_end")
            ts = turns(game.log.events)
            self.assertTrue(all(t["fallback"] for t in ts))
            for t in ts:
                if t["turn_phase"] == "finale_choice":
                    self.assertEqual(t["action"]["choice"], "split")
                if t["turn_phase"] == "job":
                    self.assertEqual(t["action"]["choice"], "help")
                if t["turn_phase"] == "whisper":
                    self.assertEqual(t["public"], "(says nothing)")
                if t["turn_phase"] == "pick":
                    self.assertIn(t["player"], t["action"]["team"])
        # All-help fallbacks mean the crew win the race.
        self.assertEqual(end["reason"], "jobs_clean")

    def test_memory_carried_through_fallback(self):
        def policy(model, system, prompt, schema, phase, player):
            if phase == "vote":
                return {"bad": 1}
            if phase == "recap":
                return None
            d = random_valid(schema, random.Random(len(prompt)))
            d["memory"] = f"note-{phase}"
            return d
        game, _ = run_game(3, policy=policy)
        for t in turns(game.log.events, "vote"):
            self.assertEqual(t["memory"], "note-discuss")


class UsageAccounting(unittest.TestCase):
    def test_usage_sums_every_attempt_and_narrator(self):
        def usage(n):
            u = zero_usage()
            u.update(input=n, output=1, cache_read=2, cache_creation=3, thinking=4, cost_usd=0.001)
            return u
        count = {"n": 0}

        def policy(model, system, prompt, schema, phase, player):
            data = random_valid(schema, random.Random(len(prompt) + count["n"]))
            count["n"] += 1
            if phase == "clue" and "rejected" not in prompt:
                data = {"bad": 1}
            if phase == "recap":
                data = {"recap": "r"}
            served = "claude-other" if model == "claude-sonnet-5" else model
            return LLMReply(data=data, raw_text="", served_model=served, usage=usage(10), latency_s=0.5)
        game, llm = run_game(4, policy=policy)
        end = game.log.events[-1]
        self.assertEqual(end["calls"], len(llm.calls))
        self.assertEqual(end["usage"]["total"]["input"], 10 * len(llm.calls))
        self.assertAlmostEqual(end["usage"]["total"]["cost_usd"], 0.001 * len(llm.calls), places=6)
        clue = turns(game.log.events, "clue")[0]
        self.assertEqual(clue["attempts"], 2)
        self.assertEqual(clue["usage"]["input"], 20)
        self.assertEqual(clue["latency_s"], 1.0)
        # Per *requested* model, narrator included.
        per = {}
        for c in llm.calls:
            per[c["model"]] = per.get(c["model"], 0) + 1
        self.assertEqual({m: r["calls"] for m, r in end["usage"]["by_model"].items()}, per)
        self.assertIn("claude-other", end["usage"]["by_model"]["claude-sonnet-5"]["served"])
        recaps = events_of(game.log.events, "recap")
        self.assertTrue(recaps)
        self.assertEqual(recaps[0]["usage"]["input"], 10)


class Suspicion(unittest.TestCase):
    def schema(self, phase, others):
        ctx = {"others": others, "alive": others + ["Me"], "whispers": True, "moles_remaining": 2,
               "self": "Me"}
        return turn_schema(phase, ctx), ctx

    def test_schema_requires_every_other_alive_player(self):
        others = ["A", "B", "C"]
        for phase in ("clue", "vote"):
            schema, _ = self.schema(phase, others)
            sus = action_props(schema)["suspicion"]
            self.assertEqual(sorted(sus["required"]), others)
            self.assertFalse(sus["additionalProperties"])
            for v in sus["properties"].values():
                self.assertEqual(v, {"type": "integer", "minimum": 0, "maximum": 100})

    def test_validation(self):
        others = ["A", "B", "C"]
        schema, ctx = self.schema("vote", others)

        def reply(sus):
            return {"confessional": "", "public": "r", "claims": [], "memory": "",
                    "move": {"vote": "A", "suspicion": sus}}
        ok, err, _ = clean_reply("vote", reply({"A": 10, "B": 0, "C": 100}), schema, ctx, CAPS)
        self.assertIsNone(err)
        ok, err, _ = clean_reply("vote", reply({"A": 10.0, "B": 0, "C": 100}), schema, ctx, CAPS)
        self.assertIsNone(err)
        self.assertEqual(ok["action"]["suspicion"]["A"], 10)
        for bad in ({"A": 10, "B": 0}, {"A": 101, "B": 0, "C": 1}, {"A": -1, "B": 0, "C": 1},
                    {"A": "50", "B": 0, "C": 1}, {"A": True, "B": 0, "C": 1}, {"A": 5.5, "B": 0, "C": 1},
                    {"A": 1, "B": 0, "C": 1, "Me": 4}):
            _, err, _ = clean_reply("vote", reply(bad), schema, ctx, CAPS)
            self.assertIsNotNone(err, bad)

    def test_kind_by_role_and_uniform_fallback(self):
        def policy(model, system, prompt, schema, phase, player):
            if phase == "clue":
                d = random_valid(schema, random.Random(1))
                d["move"]["suspicion"] = {}
                return d
            return None
        game, _ = run_game(5, policy=policy)
        roles = {p.name: p.role for p in game.players}
        for t in turns(game.log.events, "clue"):
            self.assertTrue(t["fallback"])
            others = len(t["action"]["suspicion"])
            rs = next(e for e in events_of(game.log.events, "round_start") if e["round"] == t["round"])
            moles_in = sum(1 for n in rs["alive"] if roles[n] == "mole")
            self.assertEqual(set(t["action"]["suspicion"].values()), {round(100 * moles_in / others)})
            self.assertEqual(t["suspicion_kind"], "table_read" if roles[t["player"]] == "mole" else "belief")
        for t in turns(game.log.events, "vote"):
            self.assertFalse(t["fallback"])
            self.assertEqual(t["suspicion_kind"], "table_read" if roles[t["player"]] == "mole" else "belief")

    def test_prompts_ask_different_questions(self):
        game, llm = run_game(6)
        roles = {p.name: p.role for p in game.players}
        for c in llm.calls:
            if c["phase"] in ("clue", "vote"):
                if roles[c["player"]] == "mole":
                    self.assertIn("how suspicious you think the crew find", c["prompt"])
                else:
                    self.assertIn("your honest percent chance", c["prompt"])


class ClueCards(unittest.TestCase):
    def card_script(self, make_card, job="help", claim="none", only_round=1):
        """Every discuss turn plays the card make_card(script, player) and the given job claim."""
        def discuss(s, player, schema, prompt):
            act = random_valid(schema["properties"]["move"], random.Random(0))
            act["challenges"] = []
            card = make_card(s, player)
            act["clue_cards"] = [card] if card else []
            act["job_claim"] = claim if player in s.game.team else "none"
            return act
        return Script(0, discuss=discuss, job=job_choice(job), pick=pick_with_mole)

    def test_held_card_players_in_any_order(self):
        def real(s, player):
            clue = s.game.clues_received[player][-1]
            if clue["kind"] == "none":
                return None
            return {"kind": clue["kind"], "players": list(reversed(clue["players"])), "k": clue.get("k", 0)}
        game, _ = run_game(1, policy=self.card_script(real))
        n = 0
        for t in turns(game.log.events, "discuss"):
            for c in t["checks"]["clue_cards"]:
                self.assertTrue(c["held"])
                self.assertTrue(c["true_in_world"])               # dealt clues are always true
                n += 1
        self.assertGreater(n, 0)

    def test_fabricated_card(self):
        def fake(s, player):
            others = [p for p in s.game.seat_order() if p != player]
            target = others[0]
            return {"kind": "not_mole", "players": [target], "k": 0}
        game, _ = run_game(2, policy=self.card_script(fake))
        moles = {p.name for p in game.players if p.role == "mole"}
        n = 0
        for t in turns(game.log.events, "discuss"):
            for c in t["checks"]["clue_cards"]:
                tgt = c["card"]["players"][0]
                held = any(cl["kind"] == "not_mole" and cl["players"] == [tgt]
                           for cl in game.clues_received[t["player"]])
                self.assertEqual(c["held"], held)
                self.assertEqual(c["true_in_world"], tgt not in moles)
                self.assertEqual(c["text"], f"{tgt} is not a mole.")
                n += 1
        self.assertGreater(n, 0)
        self.assertTrue(any(not c["held"] for t in turns(game.log.events, "discuss")
                            for c in t["checks"]["clue_cards"]))

    def test_exactly_k_must_match_k(self):
        game = fresh_game()
        p = game.seat_order()[0]
        a, b, c = game.seat_order()[1:4]
        game.clues_received[p] = [{"kind": "exactly_k_of_three", "players": [a, b, c], "k": 1, "text": "x"}]
        same = game.checks(p, {"clue_cards": [{"kind": "exactly_k_of_three", "players": [c, a, b], "k": 1}]})
        other = game.checks(p, {"clue_cards": [{"kind": "exactly_k_of_three", "players": [c, a, b], "k": 2}]})
        kind = game.checks(p, {"clue_cards": [{"kind": "at_least_one_of_three", "players": [a, b, c], "k": 1}]})
        self.assertTrue(same["clue_cards"][0]["held"])
        self.assertFalse(other["clue_cards"][0]["held"])
        self.assertFalse(kind["clue_cards"][0]["held"])

    def test_malformed_cards_rejected_and_retried(self):
        game = fresh_game()
        me = game.seat_order()[0]
        ctx = dict(game.base_ctx(me), self=me, challengeable=[], on_team=False)
        schema = turn_schema("discuss", ctx)
        others = game.others(me)
        base = {"confessional": "", "public": "hi", "claims": [], "memory": "",
                "move": {"accuse": "none", "challenges": [], "job_claim": "none",
                           "suspicion": {o: 30 for o in others}}}
        bad_cards = [
            {"kind": "same_side", "players": [others[0]], "k": 0},                 # wrong arity
            {"kind": "not_mole", "players": [others[0], others[1]], "k": 0},
            {"kind": "at_least_one", "players": [others[0], others[0]], "k": 0},   # repeated
            {"kind": "exactly_k_of_three", "players": others[:3], "k": 4},         # k out of range
            {"kind": "not_mole", "players": [me], "k": 0},                         # names self
            {"kind": "none", "players": [others[0]], "k": 0},
        ]
        for card in bad_cards:
            r = dict(base, move=dict(base["move"], clue_cards=[card]))
            _, err, _ = clean_reply("discuss", r, schema, ctx, CAPS)
            self.assertIsNotNone(err, card)
        too_many = [{"kind": "not_mole", "players": [o], "k": 0} for o in others[:3]]
        _, err, _ = clean_reply("discuss", dict(base, move=dict(base["move"], clue_cards=too_many)),
                                schema, ctx, CAPS)
        self.assertIsNotNone(err)
        good = dict(base, move=dict(base["move"], clue_cards=[{"kind": "not_mole", "players": [others[0]], "k": 0}]))
        _, err, _ = clean_reply("discuss", good, schema, ctx, CAPS)
        self.assertIsNone(err)

        # In a game: a malformed card is retried, and the retry is accepted.
        state = {"bad": 0}

        def policy(model, system, prompt, schema, phase, player):
            if phase == "discuss" and "rejected" not in prompt:
                d = random_valid(schema, random.Random(len(prompt)))
                enum = action_props(schema)["clue_cards"]["items"]["properties"]["players"]["items"]["enum"]
                d["move"]["clue_cards"] = [{"kind": "same_side", "players": [enum[0]], "k": 0}]
                state["bad"] += 1
                return d
            return None
        game, llm = run_game(3, policy=policy)
        ds = turns(game.log.events, "discuss")
        self.assertTrue(ds)
        for t in ds:
            self.assertEqual(t["attempts"], 2)
            self.assertFalse(t["fallback"])
            self.assertIn("same_side clue card needs exactly 2", t["rejections"][0])

    def test_job_claim_checked_against_choices(self):
        game, _ = run_game(4, policy=self.card_script(lambda s, p: None, job="sabotage", claim="helped"))
        jc_events = events_of(game.log.events, "job_choices")
        n = 0
        for t in turns(game.log.events, "discuss"):
            choices = next(e for e in jc_events if e["round"] == t["round"])["choices"]
            jc = t["checks"]["job_claim"]
            if t["player"] in choices:
                self.assertEqual(jc["claimed"], "helped")
                self.assertEqual(jc["actual"], choices[t["player"]])
                self.assertEqual(jc["lie"], choices[t["player"]] == "sabotage")
                n += 1
            else:
                self.assertIsNone(jc)
        self.assertGreater(n, 0)
        self.assertTrue(any(t["checks"]["job_claim"] and t["checks"]["job_claim"]["lie"]
                            for t in turns(game.log.events, "discuss")))

    def test_job_claim_only_for_team_members(self):
        game = fresh_game()
        me = game.seat_order()[0]
        for on_team, enum in ((False, ["none"]), (True, ["helped", "sabotaged", "none"])):
            ctx = dict(game.base_ctx(me), self=me, challengeable=[], on_team=on_team)
            schema = turn_schema("discuss", ctx)
            self.assertEqual(action_props(schema)["job_claim"]["enum"], enum)
        ctx = dict(game.base_ctx(me), self=me, challengeable=[], on_team=False)
        schema = turn_schema("discuss", dict(ctx, on_team=True))  # a lax schema, strict context
        r = {"confessional": "", "public": "hi", "claims": [], "memory": "",
             "move": {"accuse": "none", "challenges": [], "clue_cards": [], "job_claim": "helped",
                        "suspicion": {o: 30 for o in ctx["others"]}}}
        _, err, _ = clean_reply("discuss", r, schema, ctx, CAPS)
        self.assertIn("not on this round's job", err)

    def test_cards_rendered_publicly_in_discuss(self):
        def real(s, player):
            clue = s.game.clues_received[player][-1]
            return None if clue["kind"] == "none" else {"kind": clue["kind"], "players": clue["players"],
                                                         "k": clue.get("k", 0)}
        game, llm = run_game(5, policy=self.card_script(real))
        first = next(t for t in turns(game.log.events, "discuss") if t["checks"]["clue_cards"])
        text = first["checks"]["clue_cards"][0]["text"]
        later = [c for c in llm.calls[llm.calls.index(next(c for c in llm.calls if c["phase"] == "vote")):]
                 if c["phase"] == "vote" and c["player"] != first["player"]]
        checked = 0
        for c in later:
            if f'(round {first["round"]})' in c["prompt"]:
                self.assertIn(f'claims clue: "{text}"', c["prompt"])
                checked += 1
        self.assertGreater(checked, 0)
        # ...and kept in the earlier-rounds digest afterwards.
        nxt = [c for c in llm.calls if c["phase"] == "clue" and f'(round {first["round"] + 1})' in c["prompt"]]
        for c in nxt:
            self.assertIn(f'{first["player"]} claims clue: "{text}"', c["prompt"].replace(" (you)", ""))


class TheCut(unittest.TestCase):
    def test_cut_ties_broken_by_record_then_random(self):
        cfg = make_config()
        tiebreaks = set()
        for seed in range(30):
            def cut_vote(s, player, schema, prompt):
                # A vote ring: everyone votes for the next survivor, so all tie on one vote.
                surv = action_props(schema)["finalist"]["enum"] + [player]
                order = [n for n in s.game.seat_order() if n in surv]
                return {"finalist": order[(order.index(player) + 1) % len(order)]}
            s = Script(seed, job=job_choice("help"), pick=pick_without_moles,
                       vote=vote_with(lambda sc, p, o: vote_moles(sc, p, o) if sc.game.round > 1 or seed % 2
                                      else sc.rng.choice(o)),
                       cut_vote=cut_vote)
            game, _ = run_game(seed, cfg, policy=s)
            cut = events_of(game.log.events, "cut_result")
            if not cut:
                continue
            cut = cut[0]
            self.assertEqual(set(cut["tally"].values()), {1})
            self.assertIn(cut["tiebreak"], ("record", "random"))
            # Finalists have the best record of votes against moles.
            roles = {p.name: p.role for p in game.players}
            rec = {n: sum(1 for v in events_of(game.log.events, "vote_result")
                          if roles.get(v["votes"].get(n)) == "mole") for n in cut["tally"]}
            worst_finalist = min(rec[f] for f in cut["finalists"])
            best_other = max([rec[n] for n in cut["tally"] if n not in cut["finalists"]], default=-1)
            self.assertGreaterEqual(worst_finalist, best_other)
            tiebreaks.add(cut["tiebreak"])
        self.assertTrue(tiebreaks)


if __name__ == "__main__":
    unittest.main()
