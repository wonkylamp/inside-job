"""OpenRouter seats (docs/OPENROUTER.md): the HTTPS client with a fake transport, routing by model id,
the spend guard and the key's safety. No network and no `claude -p`: Claude seats use a fake `exec_fn`,
OpenRouter seats a fake HTTP transport."""

from __future__ import annotations

import asyncio
import contextlib
import copy
import gzip
import io
import json
import os
import random
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import inside_job.__main__ as cli
from inside_job import openrouter as orm
from inside_job.config import ConfigError, config_from_dict, display_name, load_config, load_raw
from inside_job.engine import Game
from inside_job.llm import ClaudeCLI, build_argv, random_valid
from inside_job.log import read_log
from inside_job.openrouter import (OpenRouterClient, RoutedLLM, SpendLedger, SpendStop, build_client,
                                   build_request, extract_json, readiness_problems, wire_schema)
from inside_job.schemas import turn_schema

ROOT = Path(__file__).resolve().parent.parent
FRONTIER = ROOT / "config" / "frontier_table.toml"
PILOT = ROOT / "config" / "pilot.toml"
SENTINEL = "sk-or-v1-SENTINEL0123456789abcdef0123456789abcdef"   # a fake key; never a real one
GROK = "x-ai/grok-4.7"


# --------------------------------------------------------------------------- fakes

def unique_schema(schema):
    """The schema with `uniqueItems` back on every array of enum items (the wire copy drops it), so
    the fake model's random replies pass the engine's full check."""
    s = copy.deepcopy(schema)

    def walk(x):
        if isinstance(x, dict):
            if x.get("type") == "array" and isinstance(x.get("items"), dict) and "enum" in x["items"]:
                x["uniqueItems"] = True
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(s)
    return s


def ok_body(model, data, cost=0.001, prompt_tokens=1000, cached=0, completion=200, reasoning=50, served=None):
    return {"id": "gen-1", "object": "chat.completion", "model": served or model,
            "choices": [{"finish_reason": "stop", "native_finish_reason": "stop",
                         "message": {"role": "assistant", "content": json.dumps(data)}}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion,
                      "total_tokens": prompt_tokens + completion,
                      "prompt_tokens_details": {"cached_tokens": cached},
                      "completion_tokens_details": {"reasoning_tokens": reasoning},
                      **({"cost": cost} if cost is not None else {})}}


class FakeHTTP:
    """A fake transport. `script` is a list of (status, body) or callables taking the request
    body; once it runs out, every request gets a valid reply for its schema at `cost`."""

    def __init__(self, cost=0.001, script=(), seed=0, ledger_probe=None):
        self.cost = cost
        self.script = list(script)
        self.rng = random.Random(seed)
        self.requests: list[dict] = []
        self.lock = threading.Lock()
        self.ledger_probe = ledger_probe        # () -> billed_usd at send time, recorded per request

    def __call__(self, url, headers, body, timeout):
        req = json.loads(body.decode())
        with self.lock:
            self.requests.append({"url": url, "headers": dict(headers), "body": req, "timeout": timeout,
                                  "billed_at_send": self.ledger_probe() if self.ledger_probe else None})
            step = self.script.pop(0) if self.script else None
            if callable(step):
                step = step(req)
            if step is None:
                schema = req["response_format"]["json_schema"]["schema"]
                data = random_valid(unique_schema(schema), self.rng)
                step = (200, ok_body(req["model"], data, cost=self.cost))
        status, resp = step
        if isinstance(resp, BaseException):
            raise resp
        return status, (resp if isinstance(resp, bytes) else json.dumps(resp).encode())


class FakeProc:
    def __init__(self, stdout: bytes):
        self._out, self.returncode = stdout, 0

    async def communicate(self):
        return self._out, b""

    def kill(self):
        pass

    async def wait(self):
        return 0


class FakeExec:
    """A fake `claude -p`: a valid structured reply for the schema in argv, notional cost 0.01."""

    def __init__(self, seed=0):
        self.rng = random.Random(seed)
        self.argvs: list[list[str]] = []

    async def __call__(self, *argv, **kw):
        self.argvs.append(list(argv))
        model = argv[argv.index("--model") + 1]
        schema = json.loads(argv[argv.index("--json-schema") + 1])
        data = random_valid(schema, self.rng)
        out = {"is_error": False, "result": json.dumps(data), "structured_output": data,
               "modelUsage": {model: {"inputTokens": 900, "outputTokens": 150, "cacheReadInputTokens": 0,
                                      "cacheCreationInputTokens": 0, "thinkingTokens": 40, "costUSD": 0.01}}}
        return FakeProc(json.dumps(out).encode())


async def no_sleep(_s):
    return None


def client(http, ledger=None, **kw):
    kw.setdefault("max_thinking_tokens", 2000)
    kw.setdefault("effort", "low")
    return OpenRouterClient(ledger=ledger or SpendLedger(5.0), transport=http, environ={orm.KEY_ENV: SENTINEL},
                            sleep=kw.pop("sleep", no_sleep), **kw)


SCHEMA = turn_schema("pick", {"self": "Ghost", "team_size": 2, "alive": ["Ghost", "Viper", "Duke", "Wren"],
                              "others": ["Viper", "Duke", "Wren"]})


def call(c, model=GROK, schema=SCHEMA):
    return asyncio.run(c.call(model=model, system="SYS", prompt="PROMPT", schema=schema, phase="pick", player="Ghost"))


def frontier_text(budget: str | None = "8.00") -> str:
    text = FRONTIER.read_text()
    line = next(ln for ln in text.splitlines() if ln.startswith("budget_usd"))
    return text.replace(line + "\n", f"budget_usd = {budget}\n" if budget is not None else "")


def run_cli(argv, make):
    old = cli.make_client
    cli.make_client = make
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(argv)
    finally:
        cli.make_client = old
    return rc, out.getvalue(), err.getvalue()


def all_text(d: Path) -> str:
    parts = []
    for f in sorted(Path(d).rglob("*")):
        if f.is_file():
            data = f.read_bytes()
            if f.name.endswith(".gz"):
                data = gzip.decompress(data)
            parts.append(data.decode("utf-8", "replace"))
    return "\n".join(parts)


class Base(unittest.TestCase):
    def setUp(self):
        orm._LEDGER = None

    def tearDown(self):
        orm._LEDGER = None


# --------------------------------------------------------------------------- request

class Request(Base):
    def test_body_shape(self):
        http = FakeHTTP()
        r = call(client(http))
        self.assertIsNone(r.error)
        self.assertEqual(len(http.requests), 1)
        req = http.requests[0]
        self.assertEqual(req["url"], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(req["headers"]["Authorization"], f"Bearer {SENTINEL}")
        self.assertEqual(req["headers"]["Content-Type"], "application/json")
        b = req["body"]
        self.assertEqual(b["model"], GROK)
        self.assertEqual(b["messages"], [{"role": "system", "content": "SYS"}, {"role": "user", "content": "PROMPT"}])
        rf = b["response_format"]
        self.assertEqual(rf["type"], "json_schema")
        self.assertEqual(rf["json_schema"]["name"], "inside_job_reply")
        self.assertIs(rf["json_schema"]["strict"], True)
        self.assertEqual(rf["json_schema"]["schema"], wire_schema(SCHEMA))
        self.assertEqual(b["max_tokens"], 6000)
        self.assertEqual(b["provider"], {"require_parameters": True})
        self.assertEqual(b["reasoning"], {"effort": "low", "exclude": True})
        self.assertEqual(req["timeout"], 240)

    def test_wire_schema_drops_unique_items_and_closes_objects(self):
        w = wire_schema(SCHEMA)
        self.assertNotIn("uniqueItems", json.dumps(w))
        self.assertIn("uniqueItems", json.dumps(SCHEMA))            # the engine's copy keeps it
        team = w["properties"]["move"]["properties"]["team"]
        self.assertEqual((team["minItems"], team["maxItems"]), (2, 2))

        def objects(x):
            if isinstance(x, dict):
                if x.get("type") == "object":
                    yield x
                for v in x.values():
                    yield from objects(v)
        for o in objects(w):
            self.assertIs(o["additionalProperties"], False)
            self.assertEqual(o["required"], list(o["properties"]))
        loose = {"type": "object", "properties": {"a": {"type": "string", "maxLength": 5}}, "uniqueItems": True}
        self.assertEqual(wire_schema(loose), {"type": "object", "properties": {"a": {"type": "string"}},
                                              "additionalProperties": False, "required": ["a"]})

    def test_reasoning_mapping(self):
        kw = dict(max_output_tokens=6000)
        self.assertEqual(build_request("a/b", "s", "p", {}, max_thinking_tokens=2000, effort="low", **kw)["reasoning"],
                         {"effort": "low", "exclude": True})                    # a set effort wins over the budget
        self.assertEqual(build_request("a/b", "s", "p", {}, max_thinking_tokens=2000, effort="", **kw)["reasoning"],
                         {"max_tokens": 2000, "exclude": True})
        self.assertEqual(build_request("a/b", "s", "p", {}, max_thinking_tokens=0, effort="low", **kw)["reasoning"],
                         {"effort": "none", "exclude": True})
        self.assertEqual(build_request("a/b", "s", "p", {}, max_thinking_tokens=-1, effort="high", **kw)["reasoning"],
                         {"effort": "high", "exclude": True})
        self.assertNotIn("reasoning", build_request("a/b", "s", "p", {}, max_thinking_tokens=-1, effort="", **kw))

    def test_reasoning_off_falls_back_when_the_model_cannot_turn_it_off(self):
        refuse = (400, {"error": {"code": 400, "message": "Reasoning is mandatory for this endpoint and cannot be disabled"}})
        http = FakeHTTP(script=[refuse])
        c = client(http, max_thinking_tokens=0)
        self.assertIsNone(call(c).error)
        self.assertEqual([r["body"]["reasoning"]["effort"] for r in http.requests], ["none", "minimal"])
        call(c)
        self.assertEqual(http.requests[-1]["body"]["reasoning"]["effort"], "minimal")   # remembered per model


# --------------------------------------------------------------------------- response

class Response(Base):
    def test_usage_cost_and_served_model(self):
        data = {"x": 1}
        body = ok_body(GROK, data, cost=0.0123, prompt_tokens=1000, cached=200, completion=300, reasoning=120,
                       served="x-ai/grok-4.7-20261001")
        body["usage"]["prompt_tokens_details"]["cache_write_tokens"] = 50
        http = FakeHTTP(script=[(200, body)])
        led = SpendLedger(5.0)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            r = call(client(http, led))
        self.assertEqual(r.data, data)
        self.assertEqual(r.usage, {"input": 750, "cache_read": 200, "cache_creation": 50, "output": 300,
                                   "thinking": 120, "cost_usd": 0.0123})
        self.assertEqual(r.served_model, "x-ai/grok-4.7-20261001")
        self.assertIn("requested x-ai/grok-4.7 but served x-ai/grok-4.7-20261001", err.getvalue())
        self.assertEqual(json.loads(r.raw_stdout), body)
        self.assertIsNone(r.error_kind)
        self.assertAlmostEqual(led.billed_usd, 0.0123)
        self.assertEqual(led.by_model, {GROK: 0.0123})

    def test_cost_from_config_prices_when_the_response_has_none(self):
        http = FakeHTTP(script=[(200, ok_body(GROK, {"x": 1}, cost=None, prompt_tokens=1000, completion=200))])
        led = SpendLedger(5.0)
        r = call(client(http, led, prices={GROK: {"input": 2.0, "output": 10.0}}))
        self.assertIsNone(r.error)
        self.assertAlmostEqual(r.usage["cost_usd"], (1000 * 2.0 + 200 * 10.0) / 1e6)
        self.assertAlmostEqual(led.billed_usd, 0.004)

    def test_no_cost_and_no_price_cannot_track_spend(self):
        http = FakeHTTP(script=[(200, ok_body(GROK, {"x": 1}, cost=None))])
        led = SpendLedger(5.0)
        c = client(http, led)
        r = call(c)
        self.assertEqual(r.error_kind, "cli")
        self.assertIn("cannot track spend", r.error)
        with self.assertRaises(SpendStop):
            call(c)
        self.assertEqual(len(http.requests), 1)

    def test_json_extraction(self):
        self.assertEqual(extract_json('{"a": 1}'), {"a": 1})
        self.assertEqual(extract_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(extract_json('Here is my move:\n{"a": {"b": [1, 2]}} hope that helps'), {"a": {"b": [1, 2]}})
        self.assertEqual(extract_json('think {not json} then {"a": 2}'), {"a": 2})
        self.assertIsNone(extract_json("no json here"))
        self.assertIsNone(extract_json("[1, 2]"))
        self.assertIsNone(extract_json(None))

    def test_fenced_reply_is_accepted_and_garbage_is_a_cli_error(self):
        fenced = ok_body(GROK, {})
        fenced["choices"][0]["message"]["content"] = 'Sure.\n```json\n{"move": 1}\n```'
        self.assertEqual(call(client(FakeHTTP(script=[(200, fenced)]))).data, {"move": 1})
        bad = ok_body(GROK, {})
        bad["choices"][0]["message"]["content"] = "I would rather not say."
        r = call(client(FakeHTTP(script=[(200, bad)])))
        self.assertIsNone(r.data)
        self.assertEqual(r.error_kind, "cli")
        cut = copy.deepcopy(bad)
        cut["choices"][0]["finish_reason"] = "length"
        self.assertIn("max_output_tokens", call(client(FakeHTTP(script=[(200, cut)]))).error)

    def test_blocked(self):
        refusal = ok_body(GROK, {})
        refusal["choices"][0]["message"] = {"role": "assistant", "content": None, "refusal": "I can't help with deception."}
        filt = ok_body(GROK, {})
        filt["choices"][0]["finish_reason"] = "content_filter"
        native = ok_body(GROK, {})
        native["choices"][0]["native_finish_reason"] = "SAFETY"
        moderation = (403, {"error": {"code": 403, "message": "Input was flagged",
                                      "metadata": {"reasons": ["deception"], "flagged_input": "...",
                                                   "provider_name": "x"}}})
        for step in ((200, refusal), (200, filt), (200, native), moderation):
            led = SpendLedger(5.0)
            r = call(client(FakeHTTP(script=[step]), led))
            self.assertEqual(r.error_kind, "blocked", step)
            self.assertIsNone(led.stop_reason)                 # a block does not stop the run

    def test_timeout(self):
        r = call(client(FakeHTTP(script=[(0, TimeoutError("slow"))])))
        self.assertEqual(r.error_kind, "timeout")

        def slow(url, headers, body, timeout):
            import time
            time.sleep(0.5)
            return 200, b"{}"
        c = OpenRouterClient(ledger=SpendLedger(5.0), transport=slow, environ={orm.KEY_ENV: SENTINEL}, timeout_s=0.05)
        self.assertEqual(call(c).error_kind, "timeout")
        r = call(client(FakeHTTP(script=[(408, {"error": {"code": 408, "message": "timed out"}})])))
        self.assertEqual(r.error_kind, "timeout")

    def test_429_then_ok_and_5xx_exhausted(self):
        sleeps = []

        async def rec(s):
            sleeps.append(s)
        http = FakeHTTP(script=[(429, {"error": {"code": 429, "message": "rate limited"}})])
        r = call(client(http, sleep=rec))
        self.assertIsNone(r.error)
        self.assertEqual(len(http.requests), 2)
        self.assertEqual(sleeps, [2.0])
        self.assertIn("http 429", r.stderr_tail)
        down = (502, {"error": {"code": 502, "message": "provider down"}})
        http = FakeHTTP(script=[down, down, down, down])
        r = call(client(http))
        self.assertEqual(len(http.requests), 3)                 # one try plus two retries
        self.assertEqual(r.error_kind, "cli")
        self.assertIn("HTTP 502 after 3 tries", r.error)
        # A provider failure inside a 200 body counts by its own code.
        http = FakeHTTP(script=[(200, {"error": {"code": 502, "message": "upstream"}})])
        self.assertIsNone(call(client(http)).error)
        self.assertEqual(len(http.requests), 2)

    def test_401_and_402_stop_without_retry_and_never_show_the_key(self):
        for status in (401, 402):
            echo = (status, {"error": {"code": status, "message": f"bad key {SENTINEL} / credits"}})
            http = FakeHTTP(script=[echo])
            led = SpendLedger(5.0)
            c = client(http, led)
            r = call(c)
            self.assertEqual(r.error_kind, "cli")
            self.assertEqual(len(http.requests), 1)
            self.assertIn(f"HTTP {status}", r.error)
            for text in (r.error, r.raw_stdout, r.raw_text, r.stderr_tail, led.stop_reason):
                self.assertNotIn(SENTINEL, text)
            with self.assertRaises(SpendStop) as cm:
                call(c)
            self.assertNotIn(SENTINEL, str(cm.exception))
            self.assertEqual(len(http.requests), 1)

    def test_missing_key_at_call_time(self):
        http = FakeHTTP()
        c = OpenRouterClient(ledger=SpendLedger(5.0), transport=http, environ={})
        r = call(c)
        self.assertEqual(r.error, "OPENROUTER_API_KEY is not set")
        self.assertEqual(http.requests, [])

    def test_no_budget_sends_nothing(self):
        http = FakeHTTP()
        with self.assertRaises(SpendStop):
            call(client(http, SpendLedger(None)))
        self.assertEqual(http.requests, [])


# --------------------------------------------------------------------------- routing and config

def mixed_raw(budget=1.0):
    raw = load_raw(FRONTIER)
    if budget is None:
        raw["openrouter"].pop("budget_usd")
    else:
        raw["openrouter"]["budget_usd"] = budget
    return raw


class Routing(Base):
    def test_claude_only_config_builds_the_same_plain_client(self):
        cfg = load_config(PILOT)
        self.assertEqual(cfg.openrouter_models(), [])
        got = cli.make_client(cfg)
        want = ClaudeCLI.from_config(cfg)
        self.assertIs(type(got), ClaudeCLI)
        strip = lambda c: {k: v for k, v in vars(c).items() if k not in ("_cwd", "_exec")}
        self.assertEqual(strip(got), strip(want))
        self.assertIs(got._exec, asyncio.create_subprocess_exec)
        self.assertNotIn("openrouter", cfg.to_dict())                       # the logged config is unchanged
        self.assertEqual(readiness_problems(cfg, environ={}), [])
        schema = {"type": "object", "properties": {"x": {"type": "string"}}}
        self.assertEqual(build_argv("claude-haiku-4-5", "SYS", "PROMPT", schema, effort="low"), [
            "claude", "-p", "--effort", "low", "--model", "claude-haiku-4-5", "--system-prompt", "SYS",
            "--tools", "", "--strict-mcp-config", "--setting-sources", "", "--no-session-persistence",
            "--output-format", "json", "--json-schema", json.dumps(schema, separators=(",", ":")), "PROMPT"])

    def test_routed_client_dispatches_by_id(self):
        cfg = config_from_dict(mixed_raw())
        http, ex = FakeHTTP(), FakeExec()
        c = build_client(cfg, exec_fn=ex, transport=http, ledger=SpendLedger(1.0), environ={orm.KEY_ENV: SENTINEL})
        self.assertIsInstance(c, RoutedLLM)
        self.assertEqual((c.claude_bin, c.effort, c.max_thinking_tokens), ("claude", "low", 2000))
        r1 = call(c, model="claude-opus-5-5")
        r2 = call(c, model="google/gemini-4-carbon")
        self.assertIsNone(r1.error)
        self.assertIsNone(r2.error)
        self.assertEqual([a[a.index("--model") + 1] for a in ex.argvs], ["claude-opus-5-5"])
        self.assertEqual([r["body"]["model"] for r in http.requests], ["google/gemini-4-carbon"])
        self.assertEqual(ex.argvs[0], build_argv("claude-opus-5-5", "SYS", "PROMPT", SCHEMA, effort="low"))

    def test_config_rules(self):
        cfg = config_from_dict(mixed_raw())
        self.assertEqual(len(cfg.openrouter_models()), 5)
        self.assertEqual(cfg.narrator.model, "claude-haiku-4-5")
        self.assertTrue(all(p.role is None for p in cfg.players))
        self.assertEqual(cfg.openrouter.budget_usd, 1.0)
        self.assertEqual(cfg.to_dict()["openrouter"]["max_output_tokens"], 4500)
        self.assertEqual(config_from_dict(cfg.to_dict()).openrouter, cfg.openrouter)   # probes rebuild it
        self.assertEqual(display_name("x-ai/grok-4.7"), "Grok 4.7")
        self.assertEqual(display_name("claude-opus-5-5"), "Opus 5.5")
        raw = mixed_raw()
        raw["players"][2]["model"] = "anthropic/claude-sonnet-9"
        with self.assertRaisesRegex(ConfigError, "subscription"):
            config_from_dict(raw)
        raw = mixed_raw()
        raw["narrator"]["model"] = "anthropic/claude-haiku-4-5"
        with self.assertRaises(ConfigError):
            config_from_dict(raw)
        for bad in ({"budget_usd": 0}, {"budget_usd": "8"}, {"max_output_tokens": 2000}, {"oops": 1},
                    {"prices": {"claude-opus-5-5": {"input": 1, "output": 2}}}, {"prices": {GROK: {"input": 1}}}):
            raw = mixed_raw()
            raw["openrouter"].update(bad)
            with self.assertRaises(ConfigError, msg=repr(bad)):
                config_from_dict(raw)

    def test_readiness(self):
        cfg = config_from_dict(mixed_raw(budget=None))
        probs = readiness_problems(cfg, environ={})
        self.assertEqual(len(probs), 2)
        self.assertTrue(any("OPENROUTER_API_KEY is not set" in p for p in probs))
        self.assertTrue(any("budget" in p for p in probs))
        self.assertEqual(readiness_problems(config_from_dict(mixed_raw()), environ={orm.KEY_ENV: SENTINEL}), [])


# --------------------------------------------------------------------------- whole games

class Games(Base):
    def maker(self, http, ex):
        return lambda cfg: build_client(cfg, exec_fn=ex, transport=http, sleep=no_sleep)

    def write_cfg(self, d, budget="8.00"):
        p = Path(d) / "mixed.toml"
        p.write_text(frontier_text(budget))
        return p

    def test_mixed_game_ends_normally_with_billed_spend(self):
        http, ex = FakeHTTP(cost=0.002, seed=1), FakeExec(seed=1)
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {orm.KEY_ENV: SENTINEL}):
            cfgp = self.write_cfg(d)
            out = Path(d) / "games"
            rc, so, se = run_cli(["run", "--config", str(cfgp), "--seed", "3", "--out", str(out)],
                                 self.maker(http, ex))
            self.assertEqual(rc, 0, se)
            self.assertIn("preflight", se)
            rows = [json.loads(x) for x in (out / "index.jsonl").read_text().splitlines()]
            self.assertEqual(len(rows), 1)
            row = rows[0]
            log = read_log(row["log"])
            end = log[-1]
            self.assertEqual(end["type"], "game_end")
            or_calls = sum(r["calls"] for m, r in end["usage"]["by_model"].items() if "/" in m)
            self.assertGreater(or_calls, 0)
            self.assertAlmostEqual(row["billed_usd"], round(0.002 * or_calls, 6))
            self.assertAlmostEqual(row["tokens"]["cost_usd"], row["billed_usd"] + 0.01 * (end["calls"] - or_calls), 4)
            self.assertIn("billed (OpenRouter models, real money)", so)
            # The preflight's paid calls count toward the same budget as the game's.
            self.assertAlmostEqual(orm._LEDGER.billed_usd, 0.002 * len(http.requests))
            self.assertGreater(len(http.requests), or_calls)
            self.assertEqual(log[0]["config"]["openrouter"]["budget_usd"], 8.0)
            self.assertTrue(any(a[a.index("--model") + 1] == "claude-haiku-4-5" for a in ex.argvs))   # narrator

    def test_budget_stops_a_game_without_indexing_or_fallbacks(self):
        http, ex = FakeHTTP(cost=0.004, seed=2), FakeExec(seed=2)
        http.ledger_probe = lambda: orm._LEDGER.billed_usd
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {orm.KEY_ENV: SENTINEL}):
            cfgp = self.write_cfg(d)
            out = Path(d) / "games"
            rc, so, se = run_cli(["run", "--config", str(cfgp), "--seed", "3", "--out", str(out), "--no-preflight",
                                  "--budget-usd", "0.05"], self.maker(http, ex))
            self.assertEqual(rc, 3, se)
            self.assertIn("STOPPED: OpenRouter spend reached the budget", so)
            self.assertFalse((out / "index.jsonl").exists())
            logs = list(out.glob("g-*.jsonl"))
            self.assertEqual(len(logs), 1)
            events = read_log(logs[0])
            self.assertFalse(any(e["type"] == "game_end" for e in events))
            self.assertFalse(any(e["type"] == "turn" and e.get("fallback") for e in events))
            self.assertGreaterEqual(orm._LEDGER.billed_usd, 0.05)
            # Every paid request went out while spend was still under the budget.
            self.assertTrue(all(r["billed_at_send"] < 0.05 for r in http.requests))

    def test_budget_stops_a_parallel_batch(self):
        http, ex = FakeHTTP(cost=0.004, seed=3), FakeExec(seed=3)
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {orm.KEY_ENV: SENTINEL}):
            cfgp = self.write_cfg(d, budget="0.12")
            out = Path(d) / "games"
            rc, so, se = run_cli(["batch", "--config", str(cfgp), "--name", "b", "--games", "4", "--seed", "1",
                                  "--parallel-games", "2", "--out", str(out), "--no-preflight"], self.maker(http, ex))
            self.assertEqual(rc, 3, so + se)
            self.assertIn("STOPPED: OpenRouter spend reached the budget", so)
            self.assertIn("cut off by the spend guard", so)
            rows = (out / "index.jsonl").read_text().splitlines() if (out / "index.jsonl").exists() else []
            self.assertEqual(rows, [])
            # Both games in flight shared one ledger: total spend is just over the budget, not twice it.
            self.assertLess(orm._LEDGER.billed_usd, 0.12 + 0.004 * 8)

    def test_refusals(self):
        http, ex = FakeHTTP(), FakeExec()
        with tempfile.TemporaryDirectory() as d:
            nobudget = Path(d) / "nb.toml"
            nobudget.write_text(frontier_text(None))
            with mock.patch.dict(os.environ, {orm.KEY_ENV: SENTINEL}):
                for argv in (["run", "--config", str(nobudget), "--seed", "1", "--out", d],
                             ["batch", "--config", str(nobudget), "--name", "x", "--games", "1", "--seed", "1",
                              "--out", d],
                             ["preflight", "--config", str(nobudget)]):
                    rc, so, se = run_cli(argv, self.maker(http, ex))
                    self.assertEqual(rc, 2, argv)
                    self.assertIn("no spend budget is set", se)
            env = {k: v for k, v in os.environ.items() if k != orm.KEY_ENV}
            with mock.patch.dict(os.environ, env, clear=True):
                rc, so, se = run_cli(["run", "--config", str(self.write_cfg(d)), "--seed", "1", "--out", d],
                                     self.maker(http, ex))
                self.assertEqual(rc, 2)
                self.assertIn("OPENROUTER_API_KEY is not set", se)
                # --mock needs neither a key nor a budget, and makes no calls.
                rc, so, se = run_cli(["run", "--config", str(nobudget), "--seed", "1", "--out", d, "--mock"],
                                     self.maker(http, ex))
                self.assertEqual(rc, 0, se)
            self.assertEqual(http.requests, [])
            self.assertEqual(ex.argvs, [])

    def test_key_never_reaches_output(self):
        """A mixed game with the sentinel key, one server error body that echoes the key and the raw
        log on: the key is in the Authorization header and nowhere else."""
        echo = (500, {"error": {"code": 500, "message": f"internal error for key {SENTINEL}"}})
        http, ex = FakeHTTP(cost=0.001, seed=5, script=[None] * 12 + [echo]), FakeExec(seed=5)
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {orm.KEY_ENV: SENTINEL}):
            cfgp = self.write_cfg(d)
            out = Path(d) / "games"
            rc, so, se = run_cli(["run", "--config", str(cfgp), "--seed", "4", "--out", str(out)],
                                 self.maker(http, ex))
            self.assertEqual(rc, 0, se)
            self.assertTrue(list(out.glob("*.raw.jsonl.gz")))
            self.assertTrue(all(r["headers"]["Authorization"] == f"Bearer {SENTINEL}" for r in http.requests))
            text = all_text(out) + so + se + all_text(Path(d))
            self.assertNotIn(SENTINEL, text)
            self.assertNotIn(SENTINEL[len("sk-or-v1-"):], text)
            self.assertIn("http 500", all_text(out))                 # the echoing reply is in the raw log, scrubbed

    def test_direct_game_with_routed_client(self):
        cfg = config_from_dict(mixed_raw(budget=5.0))
        led = SpendLedger(5.0)
        c = build_client(cfg, exec_fn=FakeExec(7), transport=FakeHTTP(cost=0.001, seed=7), ledger=led,
                         environ={orm.KEY_ENV: SENTINEL})
        game = Game(cfg, c, 7, game_id="g-test-or")
        end = game.run()
        self.assertEqual(end["type"], "game_end")
        self.assertEqual(end["fallbacks"], 0)
        billed = sum(r["cost_usd"] for m, r in end["usage"]["by_model"].items() if "/" in m)
        self.assertAlmostEqual(billed, led.billed_usd, 6)


if __name__ == "__main__":
    unittest.main()
