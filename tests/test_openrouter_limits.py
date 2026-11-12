"""OpenRouter output limits (docs/OPENROUTER.md, "Output limit"): the per-model starting limit, the
escalation after an empty or cut-off `finish_reason: length` reply, the ceiling, and what is recorded.
No network and no `claude -p`: a fake HTTP transport and a fake `claude -p`, as in test_openrouter.py.
Everything here is checked against fakes only, never against a real model."""

from __future__ import annotations

import asyncio
import gzip
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from inside_job import openrouter as orm
from inside_job.config import DEFAULT_OUTPUT_CEILING, ConfigError, config_from_dict
from inside_job.engine import Game
from inside_job.llm import build_argv
from inside_job.log import read_log
from inside_job.openrouter import (RETRY_MARK, SpendLedger, SpendStop, build_client, build_request,
                                   wire_schema)

from test_openrouter import (GROK, SCHEMA, SENTINEL, Base, FakeExec, FakeHTTP, client, frontier_text,
                             mixed_raw, no_sleep, ok_body, run_cli)

DS = "deepseek/deepseek-v4-pro-0813"
TINY = {"type": "object", "properties": {"a": {"type": "string"}}}
# What the adapter sent before per-model limits existed, for one call (computed with the unchanged
# code of 2026-11-10: frontier settings, max_output_tokens 4500, effort low, thinking cap 2000).
GOLDEN = (b'{"model": "x-ai/grok-4.7", "messages": [{"role": "system", "content": "SYS"}, {"role": "user", '
          b'"content": "PROMPT"}], "response_format": {"type": "json_schema", "json_schema": {"name": '
          b'"inside_job_reply", "strict": true, "schema": {"type": "object", "properties": {"a": {"type": '
          b'"string"}}, "additionalProperties": false, "required": ["a"]}}}, "max_tokens": 4500, "provider": '
          b'{"require_parameters": true}, "reasoning": {"effort": "low", "exclude": true}}')


def length_body(model, content="", completion=None, cost=0.02):
    """A `finish_reason: length` reply: empty (reasoning used everything) or cut-off content."""
    b = ok_body(model, {}, cost=cost, completion=completion or 4500, reasoning=completion or 4500)
    b["choices"][0]["finish_reason"] = "length"
    b["choices"][0]["native_finish_reason"] = "length"
    b["choices"][0]["message"]["content"] = content
    return b


EMPTY = lambda m=DS, **kw: (200, length_body(m, **kw))
CUT = lambda m=DS, **kw: (200, length_body(m, content='{"move": {"team": ["Vi', **kw))


def stop_garbage(m=DS):
    b = ok_body(m, {})
    b["choices"][0]["message"]["content"] = "I would rather not say."
    return 200, b


def refusal(m=DS):
    b = ok_body(m, {})
    b["choices"][0]["message"] = {"role": "assistant", "content": None, "refusal": "no"}
    return 200, b


class RecordingHTTP(FakeHTTP):
    """FakeHTTP that keeps each request's exact bytes and lets `policy(req, n)` answer a request
    ((status, body), or None for FakeHTTP's own behaviour); `n` counts requests from 0."""

    def __init__(self, policy=None, **kw):
        super().__init__(**kw)
        self.policy = policy
        self.raw: list[bytes] = []

    def __call__(self, url, headers, body, timeout):
        req = json.loads(body.decode())
        with self.lock:
            n = len(self.raw)
            self.raw.append(body)
        step = self.policy(req, n) if self.policy else None
        if step is None:
            return super().__call__(url, headers, body, timeout)
        with self.lock:
            self.requests.append({"url": url, "headers": dict(headers), "body": req, "timeout": timeout,
                                  "billed_at_send": self.ledger_probe() if self.ledger_probe else None})
        status, resp = step
        return status, json.dumps(resp).encode()


def ask(c, prompt="PROMPT", model=DS, schema=SCHEMA, player="Ghost", phase="discuss", system="SYS"):
    return asyncio.run(c.call(model=model, system=system, prompt=prompt, schema=schema, phase=phase,
                              player=player))


def retry(prompt="PROMPT", why="reply is empty"):
    """The prompt of the engine's next attempt (engine.Game.ask)."""
    return prompt + RETRY_MARK + why + ". Reply again with valid JSON."


def limits(http, model=DS):
    return [r["body"]["max_tokens"] for r in http.requests if r["body"]["model"] == model]


def today_bytes(req: dict, max_output_tokens: int) -> bytes:
    """The request the unchanged adapter builds for the same model, prompts and schema."""
    msgs = req["messages"]
    schema = req["response_format"]["json_schema"]["schema"]
    body = build_request(req["model"], msgs[0]["content"], msgs[1]["content"], schema,
                         max_output_tokens=max_output_tokens, max_thinking_tokens=2000, effort="low",
                         off_level="none")
    return json.dumps(body).encode("utf-8")


def frontier_cfg_text(budget="8.00", extra=""):
    """config/frontier_table.toml (unchanged on disk) with extra [openrouter] keys."""
    text = frontier_text(budget)
    anchor = next(ln for ln in text.splitlines() if ln.startswith("max_output_tokens"))
    return text.replace(anchor + "\n", anchor + "\n" + extra)


def raw_records(out: Path) -> list[dict]:
    recs = []
    for f in sorted(out.glob("*.raw.jsonl.gz")):
        with gzip.open(f, "rt") as fh:
            recs += [json.loads(x) for x in fh]
    return recs


# --------------------------------------------------------------------------- default unchanged

class DefaultUnchanged(Base):
    def test_default_request_is_byte_identical_to_golden(self):
        cfg = config_from_dict(mixed_raw())                    # frontier table: no new keys
        http = RecordingHTTP()
        c = build_client(cfg, exec_fn=FakeExec(), transport=http, ledger=SpendLedger(1.0),
                         environ={orm.KEY_ENV: SENTINEL})
        self.assertIsNone(ask(c, model=GROK, schema=TINY).error)
        self.assertEqual(http.raw, [GOLDEN])
        self.assertIsNone(ask(c, model=DS, schema=TINY).error)
        self.assertEqual(http.raw[1], GOLDEN.replace(b'"x-ai/grok-4.7"', b'"' + DS.encode() + b'"'))

    def test_whole_game_default_requests_unchanged_including_other_failures(self):
        """Every request of a whole mixed game, with invalid, 502 and refused replies mixed in, is
        byte for byte what the unchanged adapter builds at 4500."""
        def policy(req, n):
            if n % 7 == 3:
                return stop_garbage(req["model"])
            if n % 11 == 5:
                return 502, {"error": {"code": 502, "message": "down"}}
            if n % 13 == 6:
                return refusal(req["model"])
            return None
        cfg = config_from_dict(mixed_raw(budget=5.0))
        http = RecordingHTTP(policy=policy, seed=11)
        c = build_client(cfg, exec_fn=FakeExec(11), transport=http, ledger=SpendLedger(5.0),
                         environ={orm.KEY_ENV: SENTINEL}, sleep=no_sleep)
        end = Game(cfg, c, 11, game_id="g-test-default").run()
        self.assertEqual(end["type"], "game_end")
        self.assertGreater(len(http.raw), 60)
        self.assertEqual({r["body"]["max_tokens"] for r in http.requests}, {4500})
        for raw, r in zip(http.raw, http.requests):
            self.assertEqual(raw, today_bytes(r["body"], 4500))

    def test_ceiling_equal_to_the_limit_turns_escalation_off(self):
        http = RecordingHTTP(script=[EMPTY(), CUT()])
        c = client(http, max_output_tokens=4500, max_output_tokens_ceiling=4500)
        ask(c)
        ask(c, retry())
        ask(c, retry())
        self.assertEqual(limits(http), [4500, 4500, 4500])
        self.assertEqual([today_bytes(r["body"], 4500) for r in http.requests], http.raw)


# --------------------------------------------------------------------------- per-model limit

class PerModelLimit(Base):
    def test_limit_reaches_the_wire_for_the_named_model_only(self):
        raw = mixed_raw()
        raw["openrouter"]["max_output_tokens_by_model"] = {DS: 8000}
        cfg = config_from_dict(raw)
        http, ex = RecordingHTTP(), FakeExec()
        c = build_client(cfg, exec_fn=ex, transport=http, ledger=SpendLedger(1.0), environ={orm.KEY_ENV: SENTINEL})
        for m in cfg.openrouter_models():
            self.assertIsNone(ask(c, model=m, schema=TINY).error)
        got = {r["body"]["model"]: r["body"]["max_tokens"] for r in http.requests}
        self.assertEqual(got, {m: (8000 if m == DS else 4500) for m in cfg.openrouter_models()})
        # The others' requests are the golden bytes for their model.
        for raw_b, r in zip(http.raw, http.requests):
            if r["body"]["model"] != DS:
                self.assertEqual(raw_b, GOLDEN.replace(b'"x-ai/grok-4.7"', json.dumps(r["body"]["model"]).encode()))
        # Claude seats go through `claude -p` exactly as before.
        self.assertIsNone(ask(c, model="claude-opus-5-5", schema=SCHEMA).error)
        self.assertEqual(ex.argvs, [build_argv("claude-opus-5-5", "SYS", "PROMPT", SCHEMA, effort="low")])
        self.assertEqual(len(http.requests), len(cfg.openrouter_models()))


# --------------------------------------------------------------------------- escalation

class Escalation(Base):
    def test_empty_length_reply_doubles_the_next_attempt(self):
        http = RecordingHTTP(script=[EMPTY()])
        c = client(http, max_output_tokens=4500)
        r = ask(c)
        self.assertEqual(r.error_kind, "cli")
        self.assertIn("finish_reason length", r.error)
        self.assertEqual(len(http.requests), 1)                  # no hidden extra request
        self.assertIsNone(ask(c, retry()).error)
        self.assertEqual(limits(http), [4500, 9000])
        # Only max_tokens differs from the request the unchanged adapter would have repeated.
        self.assertEqual(http.raw[1], today_bytes(http.requests[1]["body"], 4500).replace(
            b'"max_tokens": 4500', b'"max_tokens": 9000'))

    def test_cut_off_reply_doubles_the_next_attempt(self):
        http = RecordingHTTP(script=[CUT()])
        c = client(http, max_output_tokens=4500)
        r = ask(c)
        self.assertIn("cut off at max_output_tokens 4500", r.error)
        self.assertIsNone(ask(c, retry(why=r.error)).error)
        self.assertEqual(limits(http), [4500, 9000])

    def test_per_model_start_and_ceiling(self):
        http = RecordingHTTP(script=[EMPTY(), EMPTY(), EMPTY(), EMPTY()])
        c = client(http, max_output_tokens=4500, max_output_tokens_by_model={DS: 8000},
                   max_output_tokens_ceiling=12000)
        for p in ("PROMPT", retry(), retry(), retry()):
            ask(c, p)
        self.assertEqual(limits(http), [8000, 12000, 12000, 12000])
        r = ask(c, retry())
        self.assertIn("max_output_tokens 12000 (raised from 8000 after 4 length failures this turn)", r.stderr_tail)

    def test_default_ceiling(self):
        http = RecordingHTTP(script=[EMPTY(), EMPTY(), EMPTY()])
        c = client(http, max_output_tokens=4500)
        self.assertEqual(c.max_output_tokens_ceiling, DEFAULT_OUTPUT_CEILING)
        for p in ("PROMPT", retry(), retry()):
            ask(c, p)
        self.assertEqual(limits(http), [4500, 9000, 16000])

    def test_start_above_the_ceiling_is_never_lowered(self):
        http = RecordingHTTP(script=[EMPTY()])
        c = client(http, max_output_tokens=4500, max_output_tokens_by_model={DS: 20000},
                   max_output_tokens_ceiling=16000)
        ask(c)
        ask(c, retry())
        self.assertEqual(limits(http), [20000, 20000])

    def test_other_failures_do_not_escalate(self):
        down = (502, {"error": {"code": 502, "message": "down"}})
        for step in (stop_garbage(), refusal(), down, (400, {"error": {"code": 400, "message": "bad"}}),
                     (0, TimeoutError("slow")), (408, {"error": {"code": 408, "message": "slow"}})):
            http = RecordingHTTP(script=[step, step, step])
            c = client(http, max_output_tokens=4500)
            r = ask(c)
            self.assertIsNotNone(r.error, step)
            ask(c, retry(why=r.error))
            self.assertEqual(set(limits(http)), {4500}, step)

    def test_other_failure_keeps_the_raised_limit_for_the_turn(self):
        http = RecordingHTTP(script=[EMPTY(), stop_garbage()])
        c = client(http, max_output_tokens=4500)
        ask(c)
        ask(c, retry())
        ask(c, retry(why="reply is not a JSON object"))
        self.assertEqual(limits(http), [4500, 9000, 9000])

    def test_a_new_turn_starts_again_at_the_start_limit(self):
        http = RecordingHTTP(script=[EMPTY(), EMPTY()])
        c = client(http, max_output_tokens=4500)
        ask(c)                                                    # turn 1 fails at 4500
        ask(c, "NEXT TURN PROMPT")                                # a new prompt is a new turn
        ask(c, retry("NEXT TURN PROMPT"))
        ask(c, "PROMPT", player="Viper")                          # same prompt, other player
        ask(c, "PROMPT", phase="vote")                            # same prompt, other phase
        ask(c, "PROMPT", model=GROK)                              # same prompt, other model
        self.assertEqual([r["body"]["max_tokens"] for r in http.requests],
                         [4500, 4500, 9000, 4500, 4500, 4500])

    def test_spend_guard_still_stops(self):
        led = SpendLedger(0.03)
        http = RecordingHTTP(script=[EMPTY(cost=0.02), EMPTY(cost=0.02)])
        c = client(http, led, max_output_tokens=4500)
        ask(c)
        ask(c, retry())
        self.assertTrue(led.stopped)
        with self.assertRaises(SpendStop):
            ask(c, retry())
        self.assertEqual(limits(http), [4500, 9000])             # nothing sent after the stop

    def test_limit_used_is_in_the_notes(self):
        http = RecordingHTTP(script=[EMPTY()])
        c = client(http, max_output_tokens=4500)
        r1 = ask(c)
        r2 = ask(c, retry())
        r3 = ask(c, model=GROK)
        self.assertTrue(r1.stderr_tail.startswith("openrouter: max_output_tokens 4500, http 200"), r1.stderr_tail)
        self.assertTrue(r2.stderr_tail.startswith(
            "openrouter: max_output_tokens 9000 (raised from 4500 after 1 length failure this turn), http 200"),
            r2.stderr_tail)
        self.assertEqual(r3.stderr_tail, "openrouter: max_output_tokens 4500, http 200")

    def test_turn_memory_is_bounded(self):
        http = RecordingHTTP(script=[EMPTY(cost=0.0)] * (orm.TURN_MEMORY + 5))
        c = client(http, max_output_tokens=4500)
        for i in range(orm.TURN_MEMORY + 5):
            ask(c, f"PROMPT {i}")
        self.assertEqual(len(c._length_fails), orm.TURN_MEMORY)


# --------------------------------------------------------------------------- whole games

class Games(Base):
    def run_game(self, d, http, extra="", budget="8.00", more=()):
        cfgp = Path(d) / "mixed.toml"
        cfgp.write_text(frontier_cfg_text(budget, extra))
        out = Path(d) / "games"
        ex = FakeExec(seed=4)
        rc, so, se = run_cli(["run", "--config", str(cfgp), "--seed", "4", "--out", str(out), "--no-preflight",
                              *more], lambda cfg: build_client(cfg, exec_fn=ex, transport=http, sleep=no_sleep))
        return rc, so, se, out

    def test_engine_escalates_through_its_own_retries_and_attempts_do_not_grow(self):
        """DeepSeek always runs out at the limit: each of its turns makes exactly retries + 1 = 3
        calls, at 4500, 9000 and 16000 (the default ceiling), then falls back."""
        http = RecordingHTTP(policy=lambda req, n: EMPTY(cost=0.001) if req["model"] == DS else None,
                             cost=0.001, seed=4)
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {orm.KEY_ENV: SENTINEL}):
            rc, so, se, out = self.run_game(d, http)
            self.assertEqual(rc, 0, se)
            log = read_log(next(out.glob("g-*.jsonl")))
            ds_turns = [e for e in log if e["type"] == "turn" and e.get("model") == DS]
            self.assertTrue(ds_turns)
            self.assertTrue(all(e["attempts"] == 3 and e["fallback"] for e in ds_turns))
            self.assertEqual(limits(http), [4500, 9000, 16000] * len(ds_turns))
            others = [r["body"]["max_tokens"] for r in http.requests if r["body"]["model"] != DS]
            self.assertEqual(set(others), {4500})
            # The limit used is in each raw attempt record.
            tails = [a["stderr_tail"] for a in raw_records(out) if a["kind"] == "attempt" and a["model"] == DS]
            self.assertEqual(len(tails), 3 * len(ds_turns))
            self.assertEqual([t.split(",")[0].split(" (")[0] for t in tails],
                             ["openrouter: max_output_tokens 4500", "openrouter: max_output_tokens 9000",
                              "openrouter: max_output_tokens 16000"] * len(ds_turns))

    def test_per_model_limit_and_ceiling_in_a_game_and_in_its_conditions(self):
        """DeepSeek starts at 8000 and needs more than that: one escalation to the 12000 ceiling
        answers every turn, so no DeepSeek fallback. The limits are in the logged config and the
        index row's conditions."""
        def policy(req, n):
            if req["model"] == DS and req["max_tokens"] < 12000:
                return EMPTY(cost=0.001)
            return None
        http = RecordingHTTP(policy=policy, cost=0.001, seed=4)
        extra = (f'max_output_tokens_ceiling = 12000\n'
                 f'max_output_tokens_by_model = {{ "{DS}" = 8000 }}\n')
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {orm.KEY_ENV: SENTINEL}):
            rc, so, se, out = self.run_game(d, http, extra)
            self.assertEqual(rc, 0, se)
            log = read_log(next(out.glob("g-*.jsonl")))
            ds_turns = [e for e in log if e["type"] == "turn" and e.get("model") == DS]
            self.assertTrue(ds_turns)
            self.assertTrue(all(e["attempts"] == 2 and not e["fallback"] for e in ds_turns))
            self.assertEqual(limits(http), [8000, 12000] * len(ds_turns))
            want = {"max_output_tokens": 4500, "max_output_tokens_by_model": {DS: 8000},
                    "max_output_tokens_ceiling": 12000}
            orc = log[0]["config"]["openrouter"]
            self.assertEqual({k: orc[k] for k in want}, want)
            row = json.loads((out / "index.jsonl").read_text().splitlines()[0])
            self.assertEqual(row["conditions"], {"max_thinking_tokens": 2000, "effort": "low", **want})

    def test_budget_still_stops_a_game_with_escalation(self):
        http = RecordingHTTP(policy=lambda req, n: EMPTY(cost=0.01) if req["model"] == DS else None,
                             cost=0.004, seed=4)
        http.ledger_probe = lambda: orm._LEDGER.billed_usd
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {orm.KEY_ENV: SENTINEL}):
            rc, so, se, out = self.run_game(d, http, more=("--budget-usd", "0.08"))
            self.assertEqual(rc, 3, se)
            self.assertIn("STOPPED: OpenRouter spend reached the budget", so)
            self.assertFalse((out / "index.jsonl").exists())
            self.assertTrue(all(r["billed_at_send"] < 0.08 for r in http.requests))
            self.assertIn(9000, limits(http))                     # escalation happened before the stop


# --------------------------------------------------------------------------- config

class Config(Base):
    def test_defaults_and_round_trip(self):
        cfg = config_from_dict(mixed_raw())
        orc = cfg.openrouter
        self.assertEqual((orc.max_output_tokens, orc.max_output_tokens_by_model, orc.max_output_tokens_ceiling),
                         (4500, {}, 16000))
        d = cfg.to_dict()["openrouter"]
        self.assertEqual((d["max_output_tokens_by_model"], d["max_output_tokens_ceiling"]), ({}, 16000))
        raw = mixed_raw()
        raw["openrouter"].update(max_output_tokens_by_model={DS: 8000}, max_output_tokens_ceiling=12000)
        cfg = config_from_dict(raw)
        self.assertEqual(cfg.openrouter.output_limit(DS), 8000)
        self.assertEqual(cfg.openrouter.output_limit(GROK), 4500)
        self.assertEqual(config_from_dict(cfg.to_dict()).openrouter, cfg.openrouter)
        # Without a ceiling, a starting limit above the default raises it (no escalation, never lowered).
        raw = mixed_raw()
        raw["openrouter"]["max_output_tokens_by_model"] = {DS: 24000}
        cfg = config_from_dict(raw)
        self.assertEqual(cfg.openrouter.max_output_tokens_ceiling, 24000)
        self.assertEqual(config_from_dict(cfg.to_dict()).openrouter, cfg.openrouter)
        c = orm.OpenRouterClient.from_config(cfg, ledger=SpendLedger(1.0))
        self.assertEqual((c.start_limit(DS), c.start_limit(GROK), c.limit_for(DS, 2), c.limit_for(GROK, 1)),
                         (24000, 4500, 24000, 9000))

    def test_validation_errors(self):
        cases = [
            ({"max_output_tokens_by_model": 8000}, "must be a table"),
            ({"max_output_tokens_by_model": {"deepseek-v4": 8000}}, "not an OpenRouter id"),
            ({"max_output_tokens_by_model": {"anthropic/claude-opus-5-5": 8000}}, "subscription"),
            ({"max_output_tokens_by_model": {DS: 0}}, "integer >= 1"),
            ({"max_output_tokens_by_model": {DS: 8000.0}}, "integer >= 1"),
            ({"max_output_tokens_by_model": {DS: True}}, "integer >= 1"),
            ({"max_output_tokens_by_model": {DS: "8000"}}, "integer >= 1"),
            ({"max_output_tokens_ceiling": 0}, "max_output_tokens_ceiling must be an integer"),
            ({"max_output_tokens_ceiling": 9000.5}, "max_output_tokens_ceiling must be an integer"),
            ({"max_output_tokens_ceiling": False}, "max_output_tokens_ceiling must be an integer"),
            ({"max_output_tokens_ceiling": 4000}, r"\(4000\) must be at least every starting limit: "
                                                  r"max_output_tokens is 4500"),
            ({"max_output_tokens_ceiling": 6000, "max_output_tokens_by_model": {DS: 8000}},
             f"max_output_tokens_by_model \"{DS}\" is 8000"),
            ({"max_output_tokens_by_model": {DS: 2000}}, r"must be above \[limits\] max_thinking_tokens \(2000\)"),
            ({"max_output_token_ceiling": 9000}, "unknown keys"),
        ]
        for bad, msg in cases:
            raw = mixed_raw()
            raw["openrouter"].update(bad)
            with self.assertRaisesRegex(ConfigError, msg, msg=repr(bad)):
                config_from_dict(raw)
        # The thinking check only applies with a positive thinking cap, as for max_output_tokens.
        raw = mixed_raw()
        raw["openrouter"]["max_output_tokens_by_model"] = {DS: 1500}
        raw["limits"]["max_thinking_tokens"] = -1
        self.assertEqual(config_from_dict(raw).openrouter.output_limit(DS), 1500)

    def test_claude_only_config_is_unaffected(self):
        from test_openrouter import PILOT
        from inside_job.config import load_config
        cfg = load_config(PILOT)
        self.assertNotIn("openrouter", cfg.to_dict())
        from inside_job.results import openrouter_conditions
        self.assertEqual(openrouter_conditions([{"type": "game_start", "config": cfg.to_dict()}]), {})


if __name__ == "__main__":
    unittest.main()
