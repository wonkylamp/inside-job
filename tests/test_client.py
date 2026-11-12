"""The `claude -p` client with the subprocess stubbed: argv, env, parsing, timeout."""

import asyncio
import json
import os
import unittest

from inside_job.llm import ClaudeCLI, build_argv, build_env, parse_cli_output

FIXTURE = {"is_error": False, "result": "{\"public\":\"Hello\",\"vote\":\"A\"}",
           "structured_output": {"public": "Hello", "vote": "A"},
           "total_cost_usd": 0.002404,
           "usage": {"input_tokens": 1439, "output_tokens": 193},
           "modelUsage": {"claude-haiku-4-5": {"inputTokens": 1439, "outputTokens": 193,
                                               "cacheReadInputTokens": 0, "cacheCreationInputTokens": 0,
                                               "thinkingTokens": 115, "costUSD": 0.002404}}}


class FakeProc:
    def __init__(self, stdout=b"", stderr=b"", returncode=0, hang=False):
        self._out, self._err, self.returncode, self.hang = stdout, stderr, returncode, hang
        self.killed = False

    async def communicate(self):
        if self.hang:
            await asyncio.sleep(30)
        return self._out, self._err

    def kill(self):
        self.killed = True

    async def wait(self):
        return self.returncode


class Recorder:
    def __init__(self, proc):
        self.proc = proc
        self.calls = []

    async def __call__(self, *argv, **kwargs):
        self.calls.append((argv, kwargs))
        return self.proc


SCHEMA = {"type": "object", "properties": {"x": {"type": "string"}}}


class Client(unittest.TestCase):
    def test_argv_is_exactly_the_spec(self):
        argv = build_argv("claude-haiku-4-5", "SYS", "PROMPT", SCHEMA)
        self.assertEqual(argv, [
            "claude", "-p", "--model", "claude-haiku-4-5", "--system-prompt", "SYS", "--tools", "",
            "--strict-mcp-config", "--setting-sources", "", "--no-session-persistence",
            "--output-format", "json", "--json-schema", json.dumps(SCHEMA, separators=(",", ":")), "PROMPT"])

    def test_env_has_no_claudecode(self):
        env = build_env({"CLAUDECODE": "1", "PATH": "/bin", "HOME": "/h"})
        self.assertNotIn("CLAUDECODE", env)
        self.assertEqual(env["PATH"], "/bin")

    def test_parse_recorded_reply(self):
        r = parse_cli_output(json.dumps(FIXTURE), 0)
        self.assertIsNone(r.error)
        self.assertEqual(r.data, {"public": "Hello", "vote": "A"})
        self.assertEqual(r.served_model, "claude-haiku-4-5")
        self.assertEqual(r.usage, {"input": 1439, "output": 193, "cache_read": 0, "cache_creation": 0,
                                   "thinking": 115, "cost_usd": 0.002404})

    def test_parse_fallbacks_and_errors(self):
        no_so = dict(FIXTURE)
        del no_so["structured_output"]
        self.assertEqual(parse_cli_output(json.dumps(no_so), 0).data, {"public": "Hello", "vote": "A"})
        bad = dict(no_so, result="not json")
        r = parse_cli_output(json.dumps(bad), 0)
        self.assertIsNone(r.data)
        self.assertIsNotNone(r.error)
        err = dict(FIXTURE, is_error=True, result="rate limited")
        r = parse_cli_output(json.dumps(err), 0)
        self.assertIsNone(r.data)
        self.assertIn("rate limited", r.error)
        self.assertEqual(r.usage["input"], 1439)          # usage still counted on errors
        r = parse_cli_output(json.dumps(FIXTURE), 1, "boom")
        self.assertIsNotNone(r.error)
        r = parse_cli_output("garbage", 2, "crashed")
        self.assertIn("crashed", r.error)
        two = dict(FIXTURE, modelUsage={"a": {"inputTokens": 1, "costUSD": 0.5},
                                        "b": {"inputTokens": 2, "outputTokens": 3, "costUSD": 0.25}})
        r = parse_cli_output(json.dumps(two), 0)
        self.assertEqual((r.served_model, r.usage["input"], r.usage["output"], r.usage["cost_usd"]),
                         ("b", 3, 3, 0.75))   # no requested model given: the entry with most output

    def test_call_with_stubbed_subprocess(self):
        rec = Recorder(FakeProc(stdout=json.dumps(FIXTURE).encode()))
        cli = ClaudeCLI(max_parallel_calls=2, timeout_s=5, exec_fn=rec)
        old = os.environ.get("CLAUDECODE")
        os.environ["CLAUDECODE"] = "1"
        try:
            reply = asyncio.run(cli.call(model="claude-haiku-4-5", system="S", prompt="P", schema=SCHEMA))
        finally:
            if old is None:
                os.environ.pop("CLAUDECODE", None)
            else:
                os.environ["CLAUDECODE"] = old
        self.assertIsNone(reply.error)
        self.assertEqual(reply.data["public"], "Hello")
        argv, kw = rec.calls[0]
        self.assertEqual(list(argv), build_argv("claude-haiku-4-5", "S", "P", SCHEMA))
        self.assertEqual(kw["stdin"], asyncio.subprocess.DEVNULL)
        self.assertNotIn("CLAUDECODE", kw["env"])
        self.assertTrue(os.path.isdir(kw["cwd"]))
        self.assertEqual(os.listdir(kw["cwd"]), [])

    def test_served_model_mismatch_recorded(self):
        fx = dict(FIXTURE, modelUsage={"claude-haiku-4-5-2025": FIXTURE["modelUsage"]["claude-haiku-4-5"]})
        cli = ClaudeCLI(exec_fn=Recorder(FakeProc(stdout=json.dumps(fx).encode())))
        import contextlib, io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            r1 = asyncio.run(cli.call(model="claude-haiku-4-5", system="S", prompt="P", schema=SCHEMA))
            asyncio.run(cli.call(model="claude-haiku-4-5", system="S", prompt="P", schema=SCHEMA))
        self.assertEqual(r1.served_model, "claude-haiku-4-5-2025")
        self.assertEqual(err.getvalue().count("warning"), 1)   # warned once

    def test_timeout_kills_process(self):
        proc = FakeProc(hang=True)
        cli = ClaudeCLI(timeout_s=0.05, exec_fn=Recorder(proc))
        reply = asyncio.run(cli.call(model="m", system="S", prompt="P", schema=SCHEMA))
        self.assertIsNone(reply.data)
        self.assertIn("timeout", reply.error)
        self.assertTrue(proc.killed)

    def test_concurrency_is_bounded(self):
        state = {"now": 0, "max": 0}

        class SlowProc(FakeProc):
            async def communicate(self):
                state["now"] += 1
                state["max"] = max(state["max"], state["now"])
                await asyncio.sleep(0.01)
                state["now"] -= 1
                return json.dumps(FIXTURE).encode(), b""

        async def spawn(*a, **k):
            return SlowProc()
        cli = ClaudeCLI(max_parallel_calls=3, exec_fn=spawn)

        async def many():
            return await asyncio.gather(*[cli.call(model="claude-haiku-4-5", system="S", prompt="P", schema=SCHEMA)
                                          for _ in range(10)])
        replies = asyncio.run(many())
        self.assertEqual(len(replies), 10)
        self.assertEqual(state["max"], 3)


class ServedModel(unittest.TestCase):
    """modelUsage may list a CLI helper model before the one that answered."""

    def _out(self, usage):
        return json.dumps({"is_error": False, "structured_output": {"a": 1}, "result": "", "modelUsage": usage})

    def test_requested_model_wins_over_first_key(self):
        usage = {"claude-haiku-5-5": {"outputTokens": 20}, "claude-opus-5": {"outputTokens": 400}}
        r = parse_cli_output(self._out(usage), 0, "", requested="claude-opus-5")
        self.assertEqual(r.served_model, "claude-opus-5")
        self.assertEqual(r.usage["output"], 420)

    def test_other_model_is_reported_when_requested_is_absent(self):
        usage = {"claude-haiku-5-5": {"outputTokens": 20}, "claude-sonnet-5": {"outputTokens": 400}}
        r = parse_cli_output(self._out(usage), 0, "", requested="claude-opus-5")
        self.assertEqual(r.served_model, "claude-sonnet-5")


if __name__ == "__main__":
    unittest.main()
