"""Rules v0.3: scarce intel, suspicion on every talking turn, call controls, blocked calls, preflight."""

import asyncio
import contextlib
import io
import json
import random
import tempfile
import unittest
from pathlib import Path

from inside_job import RULES_VERSION
from inside_job import __main__ as cli
from inside_job.clues import draw_recipients, generate_clue
from inside_job.config import CODENAMES, ConfigError, config_from_dict, load_config, recipient_range
from inside_job.engine import JOB_NAMES, Game
from inside_job.llm import (ClaudeCLI, LLMReply, MockLLM, build_argv, build_env, parse_cli_output,
                            random_valid, zero_usage)
from inside_job.log import read_log
from inside_job.results import append_index, token_report
from inside_job.schemas import PHASES, SUSPICION_PHASES, turn_schema

from helpers import DEFAULT_TOML, ROOT, events_of, make_config, raw_default, run_game, turns
from test_client import FIXTURE, FakeProc, Recorder, SCHEMA

BLOCK = ("API Error: Claude Sonnet 5.5's safeguards flagged this message (https://www.anthropic.com/legal/aup). "
         "This sometimes happens with safe, normal conversations...")


def deals(game):
    return events_of(game.log.events, "clue_deal")


class ScarceIntel(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(RULES_VERSION, "0.3")
        g = load_config(DEFAULT_TOML).game
        self.assertEqual((g.clue_strength, g.clue_recipients, g.clue_recipients_spread), ("weak", 3, 1))
        for f in sorted((ROOT / "config").glob("*.toml")):
            self.assertIn("v0.3", f.read_text().splitlines()[0], f)

    def test_k_in_range_never_above_alive(self):
        rng = random.Random(3)
        for _ in range(3000):
            alive = [f"P{i}" for i in range(rng.randint(1, 9))]
            rec = rng.randint(1, 5)
            spread = rng.randint(0, rec)
            got = draw_recipients(rng, alive, rec, spread)
            self.assertTrue(max(0, rec - spread) <= len(got) or len(got) == len(alive))
            self.assertLessEqual(len(got), min(rec + spread, len(alive)))
            self.assertEqual(got, [a for a in alive if a in got])          # seat order, unique
        self.assertEqual(draw_recipients(random.Random(0), ["a", "b"], 0, 1), ["a", "b"])

    def test_k_in_games(self):
        seen = set()
        for seed in range(40):
            game, _ = run_game(seed, make_config())
            for d in deals(game):
                alive = next(e["alive"] for e in events_of(game.log.events, "round_start") if e["round"] == d["round"])
                lo, hi = recipient_range(game.cfg.game, len(alive))
                self.assertTrue(lo <= d["k"] <= hi, d)
                self.assertEqual(d["k"], len(d["recipients"]))
                self.assertTrue(set(d["recipients"]) <= set(alive))
                self.assertEqual(d["vis"], "engine")
                self.assertEqual(d["phase"], "clue")
                seen.add(d["k"])
                clues = {e["player"]: e["clue"] for e in events_of(game.log.events, "clue") if e["round"] == d["round"]}
                self.assertEqual(set(clues), set(alive))                    # one clue event each
                for n in alive:
                    if n not in d["recipients"]:
                        self.assertEqual(clues[n]["kind"], "none")
                        self.assertEqual(clues[n]["text"], "No new intel this round.")
        self.assertEqual(seen, {2, 3, 4})

    def test_same_round1_recipients_whatever_the_cast(self):
        casts = [raw_default()["players"],
                 [{"model": "claude-haiku-4-5"}] * 7,
                 [{"model": m} for m in ("claude-sonnet-4-5", "claude-opus-5-5", "claude-sonnet-5", "claude-haiku-4-5",
                                          "claude-sonnet-4-6", "claude-haiku-5-5", "claude-sonnet-5-5")]]
        for anonymise in (True, False):
            for seed in range(12):
                seen = set()
                for cast in casts:
                    game, _ = run_game(seed, make_config(players=cast, anonymise=anonymise))
                    seat = {p.name: p.seat for p in game.players}
                    d = next(x for x in deals(game) if x["round"] == 1)
                    seen.add(tuple(seat[n] for n in d["recipients"]))
                self.assertEqual(len(seen), 1, seed)

    def test_zero_recipients_reproduces_v02_dealing(self):
        cfg = make_config(clue_recipients=0, clue_strength="normal")
        for seed in range(10):
            game, _ = run_game(seed, cfg)
            # Replay the v0.2 deal stream by hand: setup draws, then every alive player in seat order.
            rng = random.Random(f"{seed}:deal")
            n = len(cfg.players)
            mole_seats = sorted(rng.sample(range(n), cfg.game.num_moles))
            rng.randrange(n)
            rng.sample(CODENAMES, n)
            rng.sample(JOB_NAMES, len(JOB_NAMES))
            names = [p.name for p in game.players]
            moles = [names[i] for i in mole_seats]
            want = [generate_clue(rng=rng, players=names, alive=names, moles=moles, num_moles=2, recipient=r,
                                  revealed={}, past_clues=[], strength="normal") for r in names]
            got = [e["clue"] for e in events_of(game.log.events, "clue") if e["round"] == 1]
            self.assertEqual(got, want)
            self.assertEqual(deals(game)[0]["recipients"], names)

    def test_rules_text_states_the_range_not_the_count(self):
        game, llm = run_game(2, make_config())
        sys_prompt = llm.calls[0]["system"]
        self.assertIn("between two and four of the players still in", sys_prompt)
        self.assertIn("Anyone may table a card, whether or not they were dealt a clue", sys_prompt)
        game, llm = run_game(2, make_config(clue_recipients=0))
        self.assertIn("Every player privately receives one clue", llm.calls[0]["system"])

    def test_validation(self):
        for game in ({"clue_recipients": -1}, {"clue_recipients": 2, "clue_recipients_spread": 3},
                     {"clue_recipients": 2, "clue_recipients_spread": -1}):
            raw = raw_default()
            raw["game"].update(game)
            with self.assertRaises(ConfigError, msg=game):
                config_from_dict(raw)
        raw = raw_default()
        raw["game"].update(clue_recipients=0, clue_recipients_spread=1)   # spread ignored when everyone
        config_from_dict(raw)


class SuspicionEveryTurn(unittest.TestCase):
    def test_schema_requires_it_in_four_phases(self):
        ctx = {"others": ["A", "B"], "alive": ["A", "B", "Me"], "whispers": True, "card_players": ["A", "B"],
               "challengeable": [], "on_team": False, "team_size": 2, "self": "Me", "moles_remaining": 2}
        for phase in SUSPICION_PHASES:
            act = turn_schema(phase, ctx)["properties"]["move"]
            self.assertIn("suspicion", act["required"], phase)
            self.assertEqual(sorted(act["properties"]["suspicion"]["required"]), ["A", "B"])
        self.assertEqual(set(SUSPICION_PHASES), {"clue", "whisper", "discuss", "vote"})

    def test_logged_with_kind_and_prompted(self):
        game, llm = run_game(3, make_config())
        roles = {p.name: p.role for p in game.players}
        for t in turns(game.log.events):
            if t["turn_phase"] in ("whisper", "discuss"):
                self.assertEqual(t["suspicion_kind"], "table_read" if roles[t["player"]] == "mole" else "belief")
                self.assertEqual(set(t["action"]["suspicion"]), set(game.others(t["player"], pool=next(
                    e["alive"] for e in events_of(game.log.events, "round_start") if e["round"] == t["round"]))))
        for c in llm.calls:
            if c["phase"] in ("whisper", "discuss"):
                self.assertIn("move.suspicion", c["prompt"])

    def test_confessional_has_no_schema_description(self):
        ctx = {"others": ["A", "B"], "alive": ["A", "B", "Me"], "whispers": True, "card_players": ["A", "B"],
               "challengeable": [], "on_team": True, "team_size": 2, "self": "Me", "moles_remaining": 2,
               "survivors": ["A", "Me"]}
        for phase in PHASES:
            conf = turn_schema(phase, ctx)["properties"]["confessional"]
            self.assertNotIn("description", conf, phase)
            self.assertEqual(conf, {"type": "string"})
        game, llm = run_game(1, make_config())
        for c in llm.calls:
            if c["player"]:
                self.assertNotIn("description", c["schema"]["properties"]["confessional"])


class CallControls(unittest.TestCase):
    def test_argv_effort(self):
        self.assertEqual(build_argv("m", "S", "P", SCHEMA)[:3], ["claude", "-p", "--model"])
        for level in ("low", "medium", "high", "xhigh", "max"):
            argv = build_argv("m", "S", "P", SCHEMA, effort=level)
            self.assertEqual(argv[:4], ["claude", "-p", "--effort", level])
            self.assertEqual(argv[4:], build_argv("m", "S", "P", SCHEMA)[2:])

    def test_env_thinking_cap(self):
        base = {"PATH": "/bin", "CLAUDECODE": "1", "MAX_THINKING_TOKENS": "99999"}
        self.assertEqual(build_env(base, 2000)["MAX_THINKING_TOKENS"], "2000")
        self.assertEqual(build_env(base, 0)["MAX_THINKING_TOKENS"], "0")
        env = build_env(base, -1)
        self.assertNotIn("MAX_THINKING_TOKENS", env)          # inherited value removed
        self.assertNotIn("CLAUDECODE", env)
        self.assertEqual(base["MAX_THINKING_TOKENS"], "99999")  # caller's dict untouched

    def test_client_applies_config(self):
        cfg = make_config()
        rec = Recorder(FakeProc(stdout=json.dumps(FIXTURE).encode()))
        cli_ = ClaudeCLI.from_config(cfg, exec_fn=rec)
        asyncio.run(cli_.call(model="claude-haiku-4-5", system="S", prompt="P", schema=SCHEMA))
        argv, kw = rec.calls[0]
        self.assertEqual(list(argv[:4]), ["claude", "-p", "--effort", "low"])
        self.assertEqual(kw["env"]["MAX_THINKING_TOKENS"], "2000")

    def test_config_validation(self):
        for lim in ({"max_thinking_tokens": -2}, {"effort": "huge"}, {"max_thinking_tokens": 1.5}):
            raw = raw_default()
            raw["limits"].update(lim)
            with self.assertRaises(ConfigError, msg=lim):
                config_from_dict(raw)
        for lim in ({"max_thinking_tokens": -1, "effort": ""}, {"max_thinking_tokens": 0, "effort": "max"}):
            raw = raw_default()
            raw["limits"].update(lim)
            config_from_dict(raw)

    def test_conditions_logged_and_reported(self):
        with tempfile.TemporaryDirectory() as d:
            game, _ = run_game(2, make_config(), log_path=Path(d) / "g.jsonl")
            end = game.log.events[-1]
            self.assertEqual(end["conditions"], {"max_thinking_tokens": 2000, "effort": "low"})
            self.assertEqual(game.log.events[0]["config"]["limits"]["effort"], "low")
            self.assertIn("thinking cap: 2000   effort: low", token_report(game.log.events).splitlines()[0])
            row = append_index(game.log.events, "g.jsonl", Path(d) / "index.jsonl")
            self.assertEqual(row["conditions"], {"max_thinking_tokens": 2000, "effort": "low"})


class ErrorKinds(unittest.TestCase):
    def test_classification(self):
        blocked = dict(FIXTURE, is_error=True, result=BLOCK)
        r = parse_cli_output(json.dumps(blocked), 1)
        self.assertEqual(r.error_kind, "blocked")
        self.assertIn("safeguards flagged", r.error)
        self.assertLessEqual(len(r.error), 320)
        r = parse_cli_output(json.dumps(dict(blocked, result=BLOCK.upper())), 0)
        self.assertEqual(r.error_kind, "blocked")                      # case-insensitive
        self.assertEqual(parse_cli_output(json.dumps(dict(FIXTURE, is_error=True, result="rate limit")), 0).error_kind,
                         "cli")
        self.assertEqual(parse_cli_output(json.dumps(FIXTURE), 2, "boom").error_kind, "cli")
        self.assertEqual(parse_cli_output("not json", 1, "crash").error_kind, "cli")
        self.assertEqual(parse_cli_output(json.dumps(dict(FIXTURE, structured_output=None, result="x")), 0).error_kind,
                         "cli")
        self.assertIsNone(parse_cli_output(json.dumps(FIXTURE), 0).error_kind)
        r = asyncio.run(ClaudeCLI(timeout_s=0.05, exec_fn=Recorder(FakeProc(hang=True))).call(
            model="m", system="S", prompt="P", schema=SCHEMA))
        self.assertEqual(r.error_kind, "timeout")


def blocking_policy(target_phase=None, times=99, models=None):
    """Mock policy that blocks matching calls `times` times per (player, prompt)."""
    seen = {}

    def policy(model, system, prompt, schema, phase, player):
        if (target_phase is None or phase == target_phase) and (models is None or model in models):
            k = (player, phase, prompt)
            seen[k] = seen.get(k, 0) + 1
            if seen[k] <= times:
                return LLMReply(None, BLOCK, model, zero_usage(), 0.0, "is_error: " + BLOCK, "blocked")
        return None
    return policy


class Blocked(unittest.TestCase):
    def test_blocked_twice_falls_back_with_two_identical_attempts(self):
        game, llm = run_game(4, make_config(), policy=blocking_policy("vote"))
        votes = turns(game.log.events, "vote")
        self.assertTrue(votes)
        for t in votes:
            self.assertTrue(t["fallback"])
            self.assertEqual(t["attempts"], 2)
            self.assertEqual(t["blocked"], 2)
            self.assertEqual(t["fallback_reason"], "blocked")
            self.assertEqual(t["error_kinds"], ["blocked", "blocked"])
        calls = [c for c in llm.calls if c["phase"] == "vote"]
        self.assertEqual(len(calls), 2 * len(votes))
        for c in calls:
            self.assertNotIn("rejected", c["prompt"])                 # no rejection text appended
        prompts = {}
        for c in calls:
            prompts.setdefault(c["player"], []).append(c["prompt"])
        for p, ps in prompts.items():
            for i in range(0, len(ps), 2):
                self.assertEqual(ps[i], ps[i + 1])                    # identical prompt

    def test_blocked_once_then_answers(self):
        game, llm = run_game(4, make_config(), policy=blocking_policy("discuss", times=1))
        for t in turns(game.log.events, "discuss"):
            self.assertFalse(t["fallback"])
            self.assertEqual((t["attempts"], t["blocked"]), (2, 1))
            self.assertIsNone(t["fallback_reason"])

    def test_block_does_not_use_up_retries(self):
        state = {}

        def policy(model, system, prompt, schema, phase, player):
            if phase != "clue":
                return None
            key = (player, prompt.split("Your previous")[0].rstrip())
            n = state[key] = state.get(key, 0) + 1
            if n == 1:
                return LLMReply(None, BLOCK, model, zero_usage(), 0.0, "is_error: " + BLOCK, "blocked")
            if n <= 3:
                return {"bad": 1}                       # uses both retries
            return None
        cfg = make_config()
        game, _ = run_game(3, cfg, policy=policy)
        for t in turns(game.log.events, "clue", 1):
            self.assertFalse(t["fallback"])
            self.assertEqual(cfg.limits.retries, 2)
            self.assertEqual(t["error_kinds"], ["blocked", "invalid", "invalid"])  # the block cost no retry
            self.assertEqual((t["blocked"], t["attempts"]), (1, 4))

    def test_invalid_fallback_reason(self):
        game, _ = run_game(2, make_config(), policy=lambda *a: None if a[4] != "discuss" else {"x": 1})
        for t in turns(game.log.events, "discuss"):
            self.assertEqual(t["fallback_reason"], "invalid")
            self.assertEqual(t["blocked"], 0)

    def test_counts_reach_report_game_end_index_and_transcript(self):
        from inside_job.transcript import render
        cfg = make_config()
        sonnet = "claude-sonnet-5-5"
        game, _ = run_game(5, cfg, policy=blocking_policy(models={sonnet}))
        ev = game.log.events
        end = ev[-1]
        mine = [t for t in turns(ev) if t["model"] == sonnet]
        self.assertTrue(mine)
        row = end["usage"]["by_model"][sonnet]
        self.assertEqual(row["blocked"], 2 * len(mine))
        self.assertEqual(row["fallbacks"], len(mine))
        self.assertEqual(end["blocked"], 2 * len(mine))
        for m, r in end["usage"]["by_model"].items():
            if m != sonnet:
                self.assertEqual((r["blocked"], r["fallbacks"]), (0, 0))
        rep = token_report(ev)
        self.assertIn("blocked", rep.splitlines()[2])
        self.assertIn("fallbacks", rep.splitlines()[2])
        line = next(x for x in rep.splitlines() if x.startswith(sonnet))
        self.assertIn(f" {2 * len(mine)} ", line)
        with tempfile.TemporaryDirectory() as d:
            idx = append_index(ev, "x", Path(d) / "i.jsonl")
        self.assertEqual(idx["by_model"][sonnet], {"calls": row["calls"], "blocked": 2 * len(mine),
                                                   "fallbacks": len(mine)})
        self.assertEqual(idx["blocked"], 2 * len(mine))
        md = render(ev)
        self.assertIn("[FALLBACK: blocked]", md)

    def test_narrator_block_gets_one_more_try(self):
        game, llm = run_game(3, make_config(), policy=blocking_policy("recap", times=1))
        for r in events_of(game.log.events, "recap"):
            self.assertEqual((r["attempts"], r["blocked"], r["error"]), (2, 1, None))
        game, _ = run_game(3, make_config(), policy=blocking_policy("recap"))
        for r in events_of(game.log.events, "recap"):
            self.assertEqual((r["attempts"], r["blocked"], r["fallback_reason"], r["text"]), (2, 2, "blocked", ""))
        end = game.log.events[-1]
        self.assertGreater(end["usage"]["by_model"]["claude-haiku-4-5"]["fallbacks"], 0)


class FakeClient:
    """A stand-in for ClaudeCLI that blocks some models (no model calls)."""

    def __init__(self, blocked=(), erroring=()):
        self.blocked, self.erroring = set(blocked), set(erroring)
        self.calls = []

    async def call(self, *, model, system, prompt, schema, phase=None, player=None, view=None):
        self.calls.append((model, system, prompt, schema))
        u = dict(zero_usage(), output=700, thinking=300)
        if model in self.blocked:
            return LLMReply(None, BLOCK, model, u, 1.5, "is_error: " + BLOCK, "blocked")
        if model in self.erroring:
            return LLMReply(None, "", None, zero_usage(), 0.1, "exit 1: boom", "cli")
        return LLMReply({"ok": True}, "{}", model, u, 2.0, None)


class Preflight(unittest.TestCase):
    def run_cli(self, argv, client):
        old = cli.make_client
        cli.make_client = lambda cfg: client
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = cli.main(argv)
        finally:
            cli.make_client = old
        return rc, out.getvalue(), err.getvalue()

    def test_preflight_names_blocked_model_and_run_refuses(self):
        client = FakeClient(blocked={"claude-fable-5"})
        rc, out, err = self.run_cli(["preflight", "--config", str(DEFAULT_TOML)], client)
        self.assertEqual(rc, 2)
        self.assertIn("claude-fable-5 is blocked", err)
        models = [m for m, *_ in client.calls]
        cfg = load_config(DEFAULT_TOML)
        want = set(p.model for p in cfg.players) | {cfg.narrator.model}
        self.assertEqual(set(models), want)
        self.assertEqual(models.count("claude-fable-5"), 4)            # 2 calls, each blocked: tried once more
        self.assertEqual(models.count("claude-haiku-5-5"), 2)
        # The calls are a genuine mole discussion turn and a vote turn, identical for every model.
        self.assertEqual(len({(s, p, json.dumps(sc)) for _, s, p, sc in client.calls}), 2)
        _, system, prompt, schema = next(c for c in client.calls if "YOUR TURN: discussion" in c[2])
        self.assertIn("You are a MOLE", system)
        self.assertIn("accuse", schema["properties"]["move"]["properties"])
        _, system, prompt, schema = next(c for c in client.calls if "YOUR TURN: the vote" in c[2])
        self.assertIn("vote", schema["properties"]["move"]["properties"])
        with tempfile.TemporaryDirectory() as d:
            client = FakeClient(blocked={"claude-fable-5"})
            rc, out, err = self.run_cli(["run", "--config", str(DEFAULT_TOML), "--seed", "1", "--out", d], client)
            self.assertEqual(rc, 2)
            self.assertIn("claude-fable-5", err)
            self.assertIn("refusing to start", err)
            self.assertEqual(list(Path(d).glob("*.jsonl")), [])

    def test_preflight_ok_and_erroring(self):
        rc, out, err = self.run_cli(["preflight", "--config", str(DEFAULT_TOML)], FakeClient())
        self.assertEqual(rc, 0)
        self.assertIn("claude-opus-5-5", err)
        self.assertIn("ok", err)
        client = FakeClient(erroring={"claude-opus-5"})
        rc, out, err = self.run_cli(["preflight", "--config", str(DEFAULT_TOML)], client)
        self.assertEqual(rc, 2)
        self.assertIn("claude-opus-5 is erroring", err)
        self.assertEqual([m for m, *_ in client.calls].count("claude-opus-5"), 4)

    def test_preflight_sends_discuss_and_vote_and_fails_on_vote_alone(self):
        class VoteFails:
            def __init__(self):
                self.calls = []

            async def call(self, *, model, system, prompt, schema, phase=None, player=None, view=None):
                self.calls.append((model, phase))
                if model == "claude-opus-5" and phase == "vote":
                    return LLMReply(None, "", None, zero_usage(), 0.1,
                                    "is_error: None (subtype error_max_structured_output_retries)", "cli")
                return LLMReply({"ok": True}, "{}", model, zero_usage(), 1.0, None)
        client = VoteFails()
        rc, out, err = self.run_cli(["preflight", "--config", str(DEFAULT_TOML)], client)
        self.assertEqual(rc, 2)
        cfg = load_config(DEFAULT_TOML)
        models = set(p.model for p in cfg.players) | {cfg.narrator.model}
        for m in models:
            want = 2 if m == "claude-opus-5" else 1                     # the failing vote call: tried once more
            self.assertEqual(client.calls.count((m, "discuss")), 1, m)
            self.assertEqual(client.calls.count((m, "vote")), want, m)
        self.assertIn("claude-opus-5 is erroring on both tries (vote call)", err)
        self.assertNotIn("claude-opus-5 is erroring on both tries (discuss call)", err)
        self.assertEqual(err.count("is erroring"), 1)
        self.assertIn("phase", err)                                     # the table has a phase column

    def test_mock_and_force_skip(self):
        with tempfile.TemporaryDirectory() as d:
            client = FakeClient(blocked={"claude-fable-5"})
            rc, *_ = self.run_cli(["run", "--config", str(DEFAULT_TOML), "--seed", "1", "--mock", "--out", d], client)
            self.assertEqual((rc, client.calls), (0, []))                 # --mock: no preflight
            rc, *_ = self.run_cli(["trial", "--kind", "mole", "--test", "claude-fable-5", "--reference",
                                   "claude-haiku-4-5", "--seed", "1", "--out", d,
                                   "--config", str(ROOT / "config" / "bench.toml")], client)
            self.assertEqual(rc, 2)


class WireMove(unittest.TestCase):
    """The nested object is `move` on the wire and `action` in the engine and the log."""
    CTX = {"others": ["A", "B"], "alive": ["A", "B", "Me"], "whispers": True, "card_players": ["A", "B"],
           "challengeable": [], "on_team": False, "team_size": 2, "self": "Me", "moles_remaining": 1}
    CAPS = {"confessional": 100, "public": 100, "memory": 100}

    def vote_reply(self, **move):
        return {"confessional": "c", "public": "p", "claims": [], "memory": "m",
                "move": dict({"vote": "A", "suspicion": {"A": 10, "B": 20}}, **move)}

    def test_wire_schema_has_move_and_no_action(self):
        from inside_job.schemas import WIRE_MOVE
        self.assertEqual(WIRE_MOVE, "move")
        for phase in PHASES:
            schema = turn_schema(phase, self.CTX)
            self.assertIn("move", schema["properties"], phase)
            self.assertIn("move", schema["required"], phase)
            self.assertNotIn("action", json.dumps(schema), phase)

    def test_wire_reply_stored_under_action(self):
        from inside_job.schemas import clean_reply
        out, err, _ = clean_reply("vote", self.vote_reply(), turn_schema("vote", self.CTX), self.CTX, self.CAPS)
        self.assertIsNone(err)
        self.assertEqual(out["action"], {"vote": "A", "suspicion": {"A": 10, "B": 20}})
        self.assertNotIn("move", out)
        game, llm = run_game(2, make_config())
        self.assertTrue(turns(game.log.events))
        for t in turns(game.log.events):
            self.assertIn("action", t)
            self.assertNotIn("move", t)
        # No prompt, system prompt or schema a model reads says `action`.
        for c in llm.calls:
            for text in (c["system"], c["prompt"], json.dumps(c["schema"])):
                self.assertNotIn("action", text.lower())

    def test_rejection_names_move(self):
        from inside_job.schemas import clean_reply
        _, err, _ = clean_reply("vote", self.vote_reply(vote="Me"), turn_schema("vote", self.CTX), self.CTX,
                                self.CAPS)
        self.assertIn("move.vote must be one of", err)
        # In a game the rejection, and the retry prompt that quotes it, use the wire name.
        def policy(model, system, prompt, schema, phase, player):
            if phase == "vote" and "rejected" not in prompt:
                d = random_valid(schema, random.Random(0))
                d["move"]["vote"] = "nobody"
                return d
            return None
        game, llm = run_game(3, make_config(), policy=policy)
        votes = turns(game.log.events, "vote")
        self.assertTrue(votes)
        for t in votes:
            self.assertEqual((t["attempts"], t["fallback"]), (2, False))
            self.assertIn("move.vote must be one of", t["rejections"][0])
            self.assertIn("vote", t["action"])
        retries = [c for c in llm.calls if c["phase"] == "vote" and "rejected" in c["prompt"]]
        self.assertTrue(retries)
        self.assertTrue(all("move.vote" in c["prompt"] and "action" not in c["prompt"] for c in retries))

    def test_reply_using_action_is_rejected_with_the_right_name(self):
        from inside_job.schemas import clean_reply
        r = self.vote_reply()
        r["action"] = r.pop("move")
        out, err, _ = clean_reply("vote", r, turn_schema("vote", self.CTX), self.CTX, self.CAPS)
        self.assertIsNone(out)
        self.assertIn("reply is missing 'move'", err)
        self.assertIn("object named 'move'", err)
        # The claude-sonnet-4-5 shape: the whole reply wrapped one level too deep.
        _, err, _ = clean_reply("vote", {"move": self.vote_reply()}, turn_schema("vote", self.CTX), self.CTX,
                                self.CAPS)
        self.assertIsNotNone(err)

    def test_cli_error_says_why(self):
        reason = ("Failed to provide valid structured output after 5 attempts: "
                  "data must NOT have additional properties " + "x" * 400)
        r = parse_cli_output(json.dumps({"is_error": True, "subtype": "error_max_structured_output_retries",
                                         "result": None, "errors": [reason, "second"]}), 0)
        self.assertEqual(r.error_kind, "cli")
        self.assertIsNone(r.data)
        self.assertIn("error_max_structured_output_retries", r.error)
        self.assertIn("Failed to provide valid structured output after 5 attempts", r.error)
        self.assertNotIn("second", r.error)
        self.assertLess(len(r.error), 400 + 100)                         # the reason is cut to 300 chars
        # Blocked detection still works, on the result text and on the errors text.
        r = parse_cli_output(json.dumps({"is_error": True, "result": BLOCK}), 0)
        self.assertEqual(r.error_kind, "blocked")
        r = parse_cli_output(json.dumps({"is_error": True, "subtype": "x", "result": None, "errors": [BLOCK]}), 0)
        self.assertEqual(r.error_kind, "blocked")


if __name__ == "__main__":
    unittest.main()
