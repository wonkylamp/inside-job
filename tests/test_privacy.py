"""Privacy: no player (or the narrator) is ever shown anything they must not see.

A planting policy puts a unique token in every confessional, memory note, claim and public /
whisper text (including the `public` of silent phases, which must be dropped). Every prompt the
mock model received is then scanned for tokens and each one is checked against who may see it.
Enum-valued private actions (whisper requests, suspicion, job choices, finalist and finale
choices) and the engine's `checks` cannot carry tokens, so they are checked structurally on the
projections that the view builder consumes.
"""

import random
import re
import unittest

from inside_job.llm import LLMReply, random_valid, zero_usage
from inside_job.log import (ENGINE_ONLY_EVENT_FIELDS, ENGINE_ONLY_TURN_FIELDS, PUBLIC_ACTION_KEYS, project,
                            visible_events, visible_to)
from inside_job.schemas import SILENT_PHASES, STATEMENT_PHASES, SUSPICION_PHASES

BLOCK_TEXT = ("API Error: Claude Sonnet 5.5's safeguards flagged this message "
              "(https://www.anthropic.com/legal/aup). This sometimes happens with safe, normal conversations")
# Engine-side v0.3 fields: never in any projection, the speaker's own included.
V03_FIELDS = {"blocked", "fallback_reason", "error_kinds", "error_kind", "rejections"}

from helpers import make_config, run_game

TOKEN = re.compile(r"tk\d{5}q")
ROUND = re.compile(r"THIS ROUND \(round (\d+)\)")
PARTNER = re.compile(r"YOUR TURN: whisper to (.+?), message")


class Planter:
    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.tokens: dict[str, dict] = {}
        self.n = 0
        self.call_index = 0
        self.suspicion: list[tuple[str, dict]] = []
        self.block_every = 0

    def tok(self, **info) -> str:
        self.n += 1
        t = f"tk{self.n:05d}q"
        self.tokens[t] = dict(info, call=self.call_index)
        return t

    def __call__(self, model, system, prompt, schema, phase, player):
        idx = self.call_index
        self.call_index += 1
        if self.block_every and idx % self.block_every == 3:
            # A blocked attempt (v0.3): recorded on the turn as engine-side fields only.
            return LLMReply(None, BLOCK_TEXT, model, zero_usage(), 0.0, "is_error: " + BLOCK_TEXT, "blocked")
        if phase == "recap":
            return {"recap": "Neutral recap."}
        d = random_valid(schema, self.rng)
        m = ROUND.search(prompt)
        rnd = int(m.group(1)) if m else None
        partner = None
        if phase == "whisper":
            partner = PARTNER.search(prompt).group(1)
        base = dict(owner=player, phase=phase, round=rnd, partner=partner)
        self.call_index = idx                       # tokens record the index of this call
        d["confessional"] = self.tok(field="confessional", **base) + " thinking hard"
        d["memory"] = self.tok(field="memory", **base)
        d["claims"] = [{"text": self.tok(field="claims", **base), "truthful": False}]
        d["public"] = self.tok(field="public", **base) + " says this"
        if "suspicion" in d["move"]:
            d["move"]["suspicion"] = {k: self.rng.randint(11, 99) for k in d["move"]["suspicion"]}
            self.suspicion.append((player, d["move"]["suspicion"]))
        self.call_index = idx + 1
        return d


class Privacy(unittest.TestCase):
    def play(self, seed, block_every=0, **game):
        planter = Planter(seed)
        planter.block_every = block_every
        cfg = make_config(**game)
        g, llm = run_game(seed, cfg, policy=planter)
        return g, llm, planter

    def check_tokens(self, game, llm, planter):
        seen_whisper_partner = 0
        for i, call in enumerate(llm.calls):
            viewer = call["player"]
            text = call["system"] + "\n" + call["prompt"]
            m = ROUND.search(call["prompt"])
            call_round = int(m.group(1)) if m else None
            for t in TOKEN.findall(text):
                info = planter.tokens[t]
                where = f"token {t} {info} in call {i} ({call['phase']}, viewer {viewer})"
                self.assertLess(info["call"], i, "a token can only come from an earlier call: " + where)
                field, phase = info["field"], info["phase"]
                if field in ("confessional", "memory", "claims"):
                    self.assertEqual(viewer, info["owner"], "private field leaked: " + where)
                elif phase in SILENT_PHASES:
                    self.fail("public text of a silent phase leaked: " + where)
                elif phase == "whisper":
                    self.assertIn(viewer, (info["owner"], info["partner"]), "whisper leaked: " + where)
                    if viewer == info["partner"]:
                        seen_whisper_partner += 1
                else:
                    self.assertIn(phase, STATEMENT_PHASES, where)
                    if phase == "vote" and call["phase"] == "vote":
                        # Simultaneous: no vote reason is visible during the same vote.
                        self.assertNotEqual(call_round, info["round"], "vote seen before resolve: " + where)
        return seen_whisper_partner

    def check_discussion_visibility(self, llm, planter):
        """Each discuss speaker sees every earlier statement of the round, earlier passes included."""
        checked = 0
        for i, call in enumerate(llm.calls):
            if call["phase"] != "discuss":
                continue
            r = int(ROUND.search(call["prompt"]).group(1))
            for t, info in planter.tokens.items():
                if (info["phase"] == "discuss" and info["field"] == "public" and info["round"] == r
                        and info["call"] < i):
                    self.assertIn(t, call["prompt"])
                    checked += 1
        self.assertGreater(checked, 0)

    def check_projections(self, game):
        events = game.log.events
        roles = {p.name: p.role for p in game.players}
        moles = [n for n, r in roles.items() if r == "mole"]
        never = {"confessional", "claims", "memory", "checks", "usage", "rejections", "suspicion_kind",
                 "served_model", "attempts", "model", "latency_s", "truncated", "truncated_fields"}
        for viewer in list(roles) + [None]:
            for ev in visible_events(events, viewer):
                self.assertNotIn(ev["type"], ("game_start", "job_choices", "whisper_requests", "clue_deal"))
                self.assertNotIn("checks", ev)                         # not even for its speaker
                if ev["type"] != "turn":
                    self.assertFalse(set(ev) & set(ENGINE_ONLY_EVENT_FIELDS), (viewer, ev))
                    self.assertNotEqual(ev["type"], "clue_deal")
                    if ev["vis"] == "private":
                        self.assertEqual(ev["player"], viewer)
                    if ev["vis"] == "pair":
                        self.assertIn(viewer, ev["players"])
                    self.assertNotEqual(ev["vis"], "engine")
                    continue
                self.assertFalse(set(ev) & V03_FIELDS, (viewer, ev))     # not even its speaker
                if viewer is not None and ev["player"] == viewer:
                    continue                                           # own turn (minus checks)
                self.assertFalse(set(ev) & never, (viewer, ev))
                tp = ev["turn_phase"]
                keys = set(ev.get("action", {}))
                if tp in PUBLIC_ACTION_KEYS:
                    self.assertLessEqual(keys, set(PUBLIC_ACTION_KEYS[tp]), (viewer, ev))
                elif tp == "whisper":
                    self.assertIsNotNone(viewer)
                    self.assertEqual(viewer, next(e for e in events if e["seq"] == ev["seq"])["partner"])
                    self.assertLessEqual(keys, {"clue_cards"})
                elif tp == "job":
                    self.assertIn(viewer, moles)                       # partner mole only
                    self.assertIn(ev["player"], moles)
                    self.assertEqual(keys, {"choice"})
                    self.assertEqual(ev.get("public", ""), "")
                else:
                    self.fail(f"{viewer} sees someone else's {tp} turn: {ev}")
                self.assertNotIn("suspicion", keys)
                self.assertNotIn("whisper_with", keys)
                self.assertNotIn("finalist", keys)
                if tp != "job":
                    self.assertNotIn("choice", keys)
        # Engine-only events are never visible to anyone.
        for ev in events:
            if ev["vis"] == "engine" and ev["type"] != "turn":
                for viewer in list(roles) + [None]:
                    self.assertFalse(visible_to(ev, viewer))
                    self.assertIsNone(project(ev, viewer))

    def check_no_mole_list_for_crew(self, game, llm):
        roles = {p.name: p.role for p in game.players}
        moles = [n for n, r in roles.items() if r == "mole"]
        crew_calls = [c for c in llm.calls if c["player"] and roles[c["player"]] == "crew"]
        self.assertTrue(crew_calls)
        for c in crew_calls + [c for c in llm.calls if c["player"] is None]:
            text = c["system"] + c["prompt"]
            self.assertNotIn("You are a MOLE", text)
            self.assertNotIn("Role: mole", text)
            self.assertNotIn("Your partner", text)
            for m in moles:
                self.assertNotIn(f"partner {m}", text)
                self.assertNotIn(f"Your partner: {m}", text)
        mole_calls = [c for c in llm.calls if c["player"] and roles[c["player"]] == "mole"]
        self.assertTrue(any("You are a MOLE" in c["system"] for c in mole_calls))

    def check_suspicion_numbers(self, game, llm, planter):
        for owner, sus in planter.suspicion:
            pats = [f'"{n}": {v}' for n, v in sus.items()] + [f"{n}: {v}" for n, v in sus.items()] + \
                   [f"{n} {v}" for n, v in sus.items()]
            for c in llm.calls:
                if c["player"] == owner:
                    continue
                for p in pats:
                    self.assertNotIn(p, c["prompt"], (owner, p))

    def check_narrator(self, llm, planter):
        narr = [c for c in llm.calls if c["phase"] == "recap"]
        self.assertTrue(narr)
        for c in narr:
            for t in TOKEN.findall(c["system"] + c["prompt"]):
                info = planter.tokens[t]
                self.assertEqual(info["field"], "public")
                self.assertIn(info["phase"], STATEMENT_PHASES)

    def check_intel_receipt(self, game, llm):
        """Who was dealt a clue, and how many were dealt, never reaches anyone else (v0.3)."""
        names = [p.name for p in game.players]
        deals = [e for e in game.log.events if e["type"] == "clue_deal"]
        self.assertTrue(deals)
        for c in llm.calls:
            viewer = c["player"]
            for line in (c["system"] + "\n" + c["prompt"]).splitlines():
                low = line.lower()
                if "intel" in low or "clue" in low and ("got" in low or "dealt" in low or "receiv" in low):
                    if line.startswith(("Your clue:", "  R")) or "YOUR TURN" in line:
                        continue                              # the viewer's own clue lines
                    for n in names:
                        if n != viewer:
                            self.assertNotRegex(line, rf"\b{re.escape(n)}\b(?! is not a mole)",
                                                f"intel line names {n} for {viewer}: {line}")
            for d in deals:
                self.assertNotIn(f"recipients", c["prompt"])
                self.assertNotIn(f"{d['k']} clues", c["prompt"])
                self.assertNotIn(f"{d['k']} players got", c["prompt"])
        # Every alive player has a private clue event every round, recipient or not.
        for d in deals:
            got = [e["player"] for e in game.log.events if e["type"] == "clue" and e["round"] == d["round"]]
            alive = next(e["alive"] for e in game.log.events if e["type"] == "round_start" and e["round"] == d["round"])
            self.assertEqual(sorted(set(got)), sorted(alive))

    def check_new_turn_fields_logged(self, game):
        """The new fields exist in the log (so the projection checks above are not vacuous)."""
        ts = [e for e in game.log.events if e["type"] == "turn"]
        for t in ts:
            self.assertIn("blocked", t)
            self.assertIn("fallback_reason", t)
            self.assertIn("error_kinds", t)
            if t["turn_phase"] in SUSPICION_PHASES:
                self.assertIn("suspicion", t["action"])
                self.assertIn(t["suspicion_kind"], ("belief", "table_read"))

    def test_privacy_with_blocked_calls(self):
        for seed in range(4):
            game, llm, planter = self.play(seed, block_every=5, anonymise=False)
            self.assertTrue(any(e.get("blocked") for e in game.log.events if e["type"] in ("turn", "recap")))
            self.check_tokens(game, llm, planter)
            self.check_projections(game)
            self.check_new_turn_fields_logged(game)
            for c in llm.calls:
                self.assertNotIn("safeguards", c["prompt"])
                self.assertNotIn("blocked", c["prompt"])

    def test_privacy_across_seeds_and_modes(self):
        partner_views = 0
        for seed in range(12):
            for game_kw in ({"anonymise": False}, {"anonymise": True}, {"clean_target": 9, "sabotage_target": 9},
                            {"clue_recipients": 0, "anonymise": False}):
                game, llm, planter = self.play(seed, **game_kw)
                self.check_intel_receipt(game, llm)
                self.check_new_turn_fields_logged(game)
                partner_views += self.check_tokens(game, llm, planter)
                self.check_projections(game)
                self.check_no_mole_list_for_crew(game, llm)
                self.check_narrator(llm, planter)
                self.check_suspicion_numbers(game, llm, planter)
                self.check_discussion_visibility(llm, planter)
                for c in llm.calls:
                    self.assertNotIn('"held"', c["prompt"])
                    self.assertNotIn("true_in_world", c["prompt"])
                    self.assertNotIn("FAKE", c["prompt"])
        self.assertGreater(partner_views, 0)              # whispers do reach the partner

    def test_simultaneous_phases_build_all_prompts_first(self):
        """In parallel phases, no prompt is built after any reply of that phase is logged."""
        planter = Planter(1)
        game, llm = run_game(1, make_config(), policy=planter)
        for phase in ("clue", "vote", "cut_vote", "finale_choice"):
            groups = {}
            for i, c in enumerate(llm.calls):
                if c["phase"] == phase:
                    m = ROUND.search(c["prompt"])
                    groups.setdefault(m.group(1) if m else "F", []).append(c["prompt"])
            for prompts in groups.values():
                # The view part is identical apart from the per-player sections: no prompt in
                # the group contains another group member's tokens from this phase.
                for p in prompts:
                    for t in TOKEN.findall(p):
                        self.assertNotEqual(planter.tokens[t]["phase"], phase)


if __name__ == "__main__":
    unittest.main()
