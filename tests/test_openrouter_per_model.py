"""OpenRouter per-model reasoning and providers (docs/OPENROUTER.md, "Per-model reasoning and
providers"): [openrouter.reasoning_effort_by_model] and [openrouter.providers_by_model] reach the wire
for the named model only, the reasoning-off fallback for an entry "none", the provider note, the config
and a whole game. No network and no `claude -p`: fake transports only, as in test_openrouter.py.
Everything here is checked against fakes only, never against a real model."""

from __future__ import annotations

import json
import os
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from inside_job import openrouter as orm
from inside_job.config import ConfigError, OpenRouterConfig, config_from_dict, load_config
from inside_job.llm import random_valid
from inside_job.log import read_log
from inside_job.openrouter import REASONING_OFF_CHAIN, SpendLedger, build_client, build_request

from test_openrouter import (GROK, PILOT, SCHEMA, SENTINEL, Base, FakeExec, client, mixed_raw, no_sleep,
                             ok_body, run_cli, unique_schema)
from test_openrouter_limits import (DS, GOLDEN, TINY, RecordingHTTP, ask, frontier_cfg_text, raw_records,
                                    today_bytes)

PINNED = {"require_parameters": True, "only": ["together", "wafer"], "order": ["together", "wafer"],
          "allow_fallbacks": False}
PLAIN = {"require_parameters": True}
REFUSE = (400, {"error": {"code": 400, "message": "Reasoning is mandatory for this endpoint and cannot be disabled"}})


def served_by(provider, cost=0.001, seed=0):
    """A policy for RecordingHTTP: a valid reply for every request, with a top-level `provider`."""
    rng = random.Random(seed)

    def policy(req, n):
        data = random_valid(unique_schema(req["response_format"]["json_schema"]["schema"]), rng)
        body = ok_body(req["model"], data, cost=cost)
        if provider is not None:
            body["provider"] = provider
        return 200, body
    return policy


def gold_for(model: str) -> bytes:
    return GOLDEN.replace(b'"x-ai/grok-4.7"', json.dumps(model).encode())


def build(raw, http, ex=None):
    cfg = config_from_dict(raw)
    return cfg, build_client(cfg, exec_fn=ex or FakeExec(), transport=http, ledger=SpendLedger(1.0),
                             environ={orm.KEY_ENV: SENTINEL}, sleep=no_sleep)


# --------------------------------------------------------------------------- request body

class RequestBody(Base):
    def test_build_request_defaults_are_todays_body(self):
        for t, e in ((2000, "low"), (0, "low"), (2000, ""), (-1, "high"), (-1, "")):
            old = build_request(DS, "S", "P", TINY, max_output_tokens=4500, max_thinking_tokens=t, effort=e)
            new = build_request(DS, "S", "P", TINY, max_output_tokens=4500, max_thinking_tokens=t, effort=e,
                                reasoning_effort=None, providers=None)
            self.assertEqual(json.dumps(new), json.dumps(old))
        self.assertEqual(json.dumps(build_request(GROK, "SYS", "PROMPT", TINY, max_output_tokens=4500,
                                                  max_thinking_tokens=2000, effort="low")).encode(), GOLDEN)

    def test_build_request_with_both(self):
        b = build_request(DS, "S", "P", TINY, max_output_tokens=4500, max_thinking_tokens=2000, effort="low",
                          reasoning_effort="none", providers=["together", "wafer"])
        self.assertEqual(b["provider"], PINNED)
        self.assertEqual(b["reasoning"], {"effort": "none", "exclude": True})
        # An entry sends reasoning even where [limits] would send none.
        b = build_request(DS, "S", "P", TINY, max_output_tokens=4500, max_thinking_tokens=-1, effort="",
                          reasoning_effort="medium")
        self.assertEqual(b["reasoning"], {"effort": "medium", "exclude": True})
        self.assertEqual(b["provider"], PLAIN)


# --------------------------------------------------------------------------- reasoning entry

class ReasoningEntry(Base):
    def test_effort_entry_reaches_the_wire_for_the_named_model_only(self):
        raw = mixed_raw()
        raw["openrouter"]["reasoning_effort_by_model"] = {DS: "none"}
        http = RecordingHTTP()
        cfg, c = build(raw, http)
        for m in cfg.openrouter_models():
            self.assertIsNone(ask(c, model=m, schema=TINY).error)
        got = {r["body"]["model"]: r["body"]["reasoning"] for r in http.requests}
        self.assertEqual(got, {m: {"effort": "none" if m == DS else "low", "exclude": True}
                               for m in cfg.openrouter_models()})
        for raw_b, r in zip(http.raw, http.requests):
            if r["body"]["model"] == DS:
                # Only the reasoning effort differs from today's body.
                self.assertEqual(raw_b, gold_for(DS).replace(b'"effort": "low"', b'"effort": "none"'))
            else:
                self.assertEqual(raw_b, gold_for(r["body"]["model"]))

    def test_entry_overrides_limits_for_that_model(self):
        for t, e in ((2000, "low"), (2000, ""), (0, "low"), (-1, "")):
            http = RecordingHTTP()
            c = client(http, max_thinking_tokens=t, effort=e, reasoning_effort_by_model={DS: "high"})
            ask(c, model=DS)
            ask(c, model=GROK)
            self.assertEqual(http.requests[0]["body"]["reasoning"], {"effort": "high", "exclude": True}, (t, e))
            want = orm.reasoning_param(t, e)
            if want is None:
                self.assertNotIn("reasoning", http.requests[1]["body"])
            else:
                self.assertEqual(http.requests[1]["body"]["reasoning"], want, (t, e))

    def test_none_entry_falls_back_along_the_chain_and_remembers(self):
        http = RecordingHTTP(script=[REFUSE, REFUSE])
        c = client(http, max_thinking_tokens=2000, effort="low", reasoning_effort_by_model={DS: "none"})
        r = ask(c)
        self.assertIsNone(r.error)
        self.assertEqual([q["body"]["reasoning"]["effort"] for q in http.requests], list(REASONING_OFF_CHAIN))
        self.assertIn("reasoning effort none refused; trying minimal", r.stderr_tail)
        self.assertIn("reasoning effort minimal refused; trying low", r.stderr_tail)
        ask(c, "NEXT TURN")
        self.assertEqual(http.requests[-1]["body"]["reasoning"]["effort"], "low")     # remembered per model
        ask(c, model=GROK)                                                          # other models untouched
        self.assertEqual(http.requests[-1]["body"]["reasoning"], {"effort": "low", "exclude": True})
        self.assertEqual(c._off_level, {DS: 2})

    def test_none_entry_chain_stops_at_the_end(self):
        http = RecordingHTTP(script=[REFUSE, REFUSE, REFUSE])
        c = client(http, reasoning_effort_by_model={DS: "none"})
        r = ask(c)
        self.assertEqual(r.error_kind, "cli")
        self.assertIn("HTTP 400", r.error)
        self.assertEqual(len(http.requests), 3)

    def test_other_entries_never_use_the_chain(self):
        for entry in ("minimal", "low", "medium", "high"):
            for t in (0, 2000):
                http = RecordingHTTP(script=[REFUSE])
                c = client(http, max_thinking_tokens=t, reasoning_effort_by_model={DS: entry})
                r = ask(c)
                self.assertEqual(r.error_kind, "cli", (entry, t))
                self.assertIn("HTTP 400", r.error)
                self.assertEqual(len(http.requests), 1, (entry, t))
                self.assertEqual(http.requests[0]["body"]["reasoning"]["effort"], entry)
                self.assertEqual(c._off_level, {})

    def test_global_off_still_falls_back_for_models_without_an_entry(self):
        http = RecordingHTTP(script=[REFUSE])
        c = client(http, max_thinking_tokens=0, reasoning_effort_by_model={DS: "high"})
        self.assertIsNone(ask(c, model=GROK).error)
        self.assertEqual([q["body"]["reasoning"]["effort"] for q in http.requests], ["none", "minimal"])

    def test_without_entry_400_does_not_fall_back_when_reasoning_is_on(self):
        http = RecordingHTTP(script=[REFUSE])
        c = client(http, reasoning_effort_by_model={GROK: "none"})
        r = ask(c, model=DS)
        self.assertIn("HTTP 400", r.error)
        self.assertEqual(len(http.requests), 1)


# --------------------------------------------------------------------------- providers entry

class ProvidersEntry(Base):
    def test_provider_entry_reaches_the_wire_for_the_named_model_only(self):
        raw = mixed_raw()
        raw["openrouter"]["providers_by_model"] = {DS: ["together", "wafer"]}
        http = RecordingHTTP()
        cfg, c = build(raw, http)
        for m in cfg.openrouter_models():
            self.assertIsNone(ask(c, model=m, schema=TINY).error)
        got = {r["body"]["model"]: r["body"]["provider"] for r in http.requests}
        self.assertEqual(got, {m: PINNED if m == DS else PLAIN for m in cfg.openrouter_models()})
        for raw_b, r in zip(http.raw, http.requests):
            if r["body"]["model"] == DS:
                self.assertEqual(raw_b, gold_for(DS).replace(
                    b'"provider": {"require_parameters": true}',
                    b'"provider": {"require_parameters": true, "only": ["together", "wafer"], '
                    b'"order": ["together", "wafer"], "allow_fallbacks": false}'))
            else:
                self.assertEqual(raw_b, gold_for(r["body"]["model"]))

    def test_both_entries_together(self):
        http = RecordingHTTP()
        c = client(http, max_output_tokens=4500, reasoning_effort_by_model={DS: "none"},
                   providers_by_model={DS: ["together", "wafer"]})
        ask(c, schema=TINY)
        ask(c, model=GROK, schema=TINY)
        ds, grok = (r["body"] for r in http.requests)
        self.assertEqual((ds["provider"], ds["reasoning"]), (PINNED, {"effort": "none", "exclude": True}))
        self.assertEqual((grok["provider"], grok["reasoning"]), (PLAIN, {"effort": "low", "exclude": True}))
        self.assertEqual(http.raw[1], GOLDEN)
        # The chain keeps the providers on every try.
        http = RecordingHTTP(script=[REFUSE])
        c = client(http, reasoning_effort_by_model={DS: "none"}, providers_by_model={DS: ["together", "wafer"]})
        self.assertIsNone(ask(c).error)
        self.assertEqual([(q["body"]["provider"], q["body"]["reasoning"]["effort"]) for q in http.requests],
                         [(PINNED, "none"), (PINNED, "minimal")])


# --------------------------------------------------------------------------- provider note

class ProviderNote(Base):
    def test_note_only_for_a_model_with_an_entry(self):
        for kw in ({"reasoning_effort_by_model": {DS: "none"}}, {"providers_by_model": {DS: ["together"]}}):
            http = RecordingHTTP(policy=served_by("Together"))
            c = client(http, **kw)
            r = ask(c)
            self.assertEqual(r.stderr_tail, "openrouter: max_output_tokens 6000, http 200, provider Together", kw)
            r = ask(c, model=GROK)
            self.assertEqual(r.stderr_tail, "openrouter: max_output_tokens 6000, http 200", kw)

    def test_no_note_without_provider_in_the_response(self):
        http = RecordingHTTP(policy=served_by(None))
        c = client(http, providers_by_model={DS: ["together"]})
        self.assertEqual(ask(c).stderr_tail, "openrouter: max_output_tokens 6000, http 200")

    def test_one_note_per_call_naming_the_last_response(self):
        down = (502, {"error": {"code": 502, "message": "down"}, "provider": "Nebius"})
        ok = served_by("Wafer")

        def policy(req, n):
            return down if n == 0 else ok(req, n)
        http = RecordingHTTP(policy=policy)
        c = client(http, providers_by_model={DS: ["nebius", "wafer"]})
        r = ask(c)
        self.assertIsNone(r.error)
        self.assertEqual(r.stderr_tail, "openrouter: max_output_tokens 6000, http 502, http 200, provider Wafer")
        # A failed call names the provider of its failing response.
        http = RecordingHTTP(script=[(400, {"error": {"code": 400, "message": "bad"}, "provider": "Sail"})])
        c = client(http, providers_by_model={DS: ["sail"]})
        r = ask(c)
        self.assertEqual(r.stderr_tail, "openrouter: max_output_tokens 6000, http 400, provider Sail")

    def test_no_new_note_for_any_model_when_the_tables_are_empty(self):
        http = RecordingHTTP(policy=served_by("Together"))
        c = client(http)
        for m in (DS, GROK):
            self.assertEqual(ask(c, model=m).stderr_tail, "openrouter: max_output_tokens 6000, http 200")


# --------------------------------------------------------------------------- config

class Config(Base):
    def test_defaults(self):
        self.assertEqual((OpenRouterConfig().reasoning_effort_by_model, OpenRouterConfig().providers_by_model),
                         ({}, {}))
        cfg = config_from_dict(mixed_raw())
        self.assertEqual((cfg.openrouter.reasoning_effort_by_model, cfg.openrouter.providers_by_model), ({}, {}))
        d = cfg.to_dict()["openrouter"]
        self.assertNotIn("reasoning_effort_by_model", d)
        self.assertNotIn("providers_by_model", d)
        self.assertEqual(list(d), ["budget_usd", "max_output_tokens", "max_output_tokens_by_model",
                                   "max_output_tokens_ceiling", "prices"])
        c = orm.OpenRouterClient.from_config(cfg, ledger=SpendLedger(1.0))
        self.assertEqual((c.reasoning_effort_by_model, c.providers_by_model), ({}, {}))

    def test_round_trip_through_load_and_to_dict(self):
        extra = (f'reasoning_effort_by_model = {{ "{DS}" = "none" }}\n'
                 f'providers_by_model = {{ "{DS}" = ["together", "wafer"] }}\n')
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.toml"
            p.write_text(frontier_cfg_text("8.00", extra))
            cfg = load_config(p)
        orc = cfg.openrouter
        self.assertEqual(orc.reasoning_effort_by_model, {DS: "none"})
        self.assertEqual(orc.providers_by_model, {DS: ["together", "wafer"]})
        d = cfg.to_dict()["openrouter"]
        self.assertEqual(d["reasoning_effort_by_model"], {DS: "none"})
        self.assertEqual(d["providers_by_model"], {DS: ["together", "wafer"]})
        self.assertEqual(config_from_dict(cfg.to_dict()).openrouter, orc)
        c = orm.OpenRouterClient.from_config(cfg, ledger=SpendLedger(1.0))
        self.assertEqual((c.reasoning_effort_by_model, c.providers_by_model),
                         ({DS: "none"}, {DS: ["together", "wafer"]}))
        # One set, the other empty: only the set one is logged.
        raw = mixed_raw()
        raw["openrouter"]["providers_by_model"] = {DS: ["together"]}
        d = config_from_dict(raw).to_dict()["openrouter"]
        self.assertEqual((d.get("providers_by_model"), "reasoning_effort_by_model" in d), ({DS: ["together"]}, False))
        # Empty tables are accepted and log nothing.
        raw = mixed_raw()
        raw["openrouter"].update(reasoning_effort_by_model={}, providers_by_model={})
        self.assertEqual(config_from_dict(raw).to_dict(), config_from_dict(mixed_raw()).to_dict())

    def test_every_effort_is_accepted(self):
        for e in ("none", "minimal", "low", "medium", "high"):
            raw = mixed_raw()
            raw["openrouter"]["reasoning_effort_by_model"] = {DS: e}
            self.assertEqual(config_from_dict(raw).openrouter.reasoning_effort_by_model, {DS: e})

    def test_validation_errors(self):
        R, P = "reasoning_effort_by_model", "providers_by_model"
        cases = [
            ({R: "none"}, r"\[openrouter.reasoning_effort_by_model\] must be a table"),
            ({R: ["none"]}, r"\[openrouter.reasoning_effort_by_model\] must be a table"),
            ({R: {"deepseek-v4": "none"}}, "not an OpenRouter id"),
            ({R: {"anthropic/claude-opus-5-5": "none"}}, "subscription"),
            ({R: {DS: "off"}}, r"must be one of \['none', 'minimal', 'low', 'medium', 'high'\]"),
            ({R: {DS: "xhigh"}}, "must be one of"),
            ({R: {DS: "None"}}, "must be one of"),
            ({R: {DS: ""}}, "must be one of"),
            ({R: {DS: 0}}, "must be one of"),
            ({R: {DS: False}}, "must be one of"),
            ({P: ["together"]}, r"\[openrouter.providers_by_model\] must be a table"),
            ({P: "together"}, r"\[openrouter.providers_by_model\] must be a table"),
            ({P: {"deepseek-v4": ["together"]}}, "not an OpenRouter id"),
            ({P: {"anthropic/claude-opus-5-5": ["together"]}}, "subscription"),
            ({P: {DS: []}}, "must be a non-empty list of provider slugs"),
            ({P: {DS: "together"}}, "must be a non-empty list of provider slugs"),
            ({P: {DS: [""]}}, "must be a non-empty list of provider slugs"),
            ({P: {DS: ["to gether"]}}, "must be a non-empty list of provider slugs"),
            ({P: {DS: [" together"]}}, "must be a non-empty list of provider slugs"),
            ({P: {DS: ["together", 3]}}, "must be a non-empty list of provider slugs"),
            ({P: {DS: [["together"]]}}, "must be a non-empty list of provider slugs"),
            ({P: {DS: ["together", "wafer", "together"]}}, "lists provider 'together' more than once"),
            ({"reasoning_effort": {DS: "none"}}, "unknown keys"),
            ({"providers": {DS: ["together"]}}, "unknown keys"),
        ]
        for bad, msg in cases:
            raw = mixed_raw()
            raw["openrouter"].update(bad)
            with self.assertRaisesRegex(ConfigError, msg, msg=repr(bad)):
                config_from_dict(raw)

    def test_claude_only_config_is_unaffected(self):
        cfg = load_config(PILOT)
        self.assertNotIn("openrouter", cfg.to_dict())
        self.assertEqual((cfg.openrouter.reasoning_effort_by_model, cfg.openrouter.providers_by_model), ({}, {}))
        got = build_client(cfg, exec_fn=FakeExec())
        self.assertNotIsInstance(got, orm.RoutedLLM)


# --------------------------------------------------------------------------- whole game

class Game(Base):
    def test_whole_game_sends_the_settings_on_that_models_calls_only(self):
        extra = (f'reasoning_effort_by_model = {{ "{DS}" = "none" }}\n'
                 f'providers_by_model = {{ "{DS}" = ["together", "wafer"] }}\n')
        http = RecordingHTTP(policy=served_by("Together", seed=4), seed=4)
        ex = FakeExec(seed=4)
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {orm.KEY_ENV: SENTINEL}):
            cfgp = Path(d) / "mixed.toml"
            cfgp.write_text(frontier_cfg_text("8.00", extra))
            out = Path(d) / "games"
            rc, so, se = run_cli(["run", "--config", str(cfgp), "--seed", "4", "--out", str(out), "--no-preflight"],
                                 lambda cfg: build_client(cfg, exec_fn=ex, transport=http, sleep=no_sleep))
            self.assertEqual(rc, 0, se)
            log = read_log(next(out.glob("g-*.jsonl")))
            orc = log[0]["config"]["openrouter"]
            self.assertEqual(orc["reasoning_effort_by_model"], {DS: "none"})
            self.assertEqual(orc["providers_by_model"], {DS: ["together", "wafer"]})
            ds = [r for r in http.requests if r["body"]["model"] == DS]
            others = [r for r in http.requests if r["body"]["model"] != DS]
            self.assertTrue(ds)
            self.assertGreater(len({r["body"]["model"] for r in others}), 2)
            for r in ds:
                self.assertEqual(r["body"]["provider"], PINNED)
                self.assertEqual(r["body"]["reasoning"], {"effort": "none", "exclude": True})
            for raw_b, r in zip(http.raw, http.requests):
                if r["body"]["model"] != DS:
                    self.assertEqual(r["body"]["provider"], PLAIN)
                    self.assertEqual(r["body"]["reasoning"], {"effort": "low", "exclude": True})
                    self.assertEqual(raw_b, today_bytes(r["body"], 4500))
            # The provider note is in DeepSeek's raw attempt records and in nobody else's.
            atts = [a for a in raw_records(out) if a["kind"] == "attempt" and "/" in a["model"]]
            self.assertTrue(atts)
            for a in atts:
                if a["model"] == DS:
                    self.assertTrue(a["stderr_tail"].endswith(", provider Together"), a["stderr_tail"])
                else:
                    self.assertNotIn("provider", a["stderr_tail"])
            # Claude seats still went through `claude -p`, never through OpenRouter.
            self.assertTrue(ex.argvs)
            self.assertFalse(any(r["body"]["model"].startswith("claude") for r in http.requests))


if __name__ == "__main__":
    unittest.main()
