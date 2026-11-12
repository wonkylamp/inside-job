"""Stage 2 (docs/STAGE2.md parts A and B): sentence-end trimming with a word grace, and `batch`."""

import asyncio
import contextlib
import copy
import io
import json
import os
import random
import signal
import tempfile
import threading
import tomllib
import unittest
from pathlib import Path

from inside_job import __main__ as cli
from inside_job.batch import finished_seeds, read_index
from inside_job.config import ConfigError, config_from_dict, load_config
from inside_job.llm import ClaudeCLI, LLMReply, MockLLM, random_valid, zero_usage
from inside_job.log import read_log, visible_events
from inside_job.prompts import player_system_prompt
from inside_job.schemas import ELLIPSIS, clean_reply, hard_cap, truncate_words, turn_schema
from inside_job.transcript import render

from helpers import DEFAULT_TOML, ROOT, events_of, make_config, raw_default, run_game, turns

PILOT_TOML = ROOT / "config" / "pilot.toml"


def words(n, start=0):
    return " ".join(f"w{i}" for i in range(start, start + n))


# --------------------------------------------------------------------------- Part A

class Trimming(unittest.TestCase):
    def test_hard_cap(self):
        self.assertEqual(hard_cap(60, 0.15), 69)
        self.assertEqual(hard_cap(70, 0.15), 81)
        self.assertEqual(hard_cap(50, 0.15), 58)
        self.assertEqual(hard_cap(100, 0.15), 115)
        self.assertEqual(hard_cap(60, 0), 60)
        self.assertEqual(hard_cap(60, 1), 120)
        self.assertEqual(hard_cap(20, 0.15), 23)          # 23.0 exactly: no float creep to 24

    def test_under_or_at_cap_unchanged(self):
        text = "  First line.\nSecond   line with spacing kept  "
        self.assertEqual(truncate_words(text, 10), (text.strip(), False))
        self.assertEqual(truncate_words(words(10), 10), (words(10), False))
        self.assertEqual(truncate_words("", 10), ("", False))

    def test_over_cap_cut_to_last_sentence_end(self):
        text = words(5) + " end. " + words(3, 10) + " again! " + words(10, 20)   # sentence ends at words 6 and 10
        out, t = truncate_words(text, 12)
        self.assertTrue(t)
        self.assertEqual(out, words(5) + " end. " + words(3, 10) + " again!")
        out, t = truncate_words("Is it Viper? " + words(20), 4)        # "?" counts; 3 words >= half of 4
        self.assertEqual((out, t), ("Is it Viper?", True))

    def test_one_long_sentence_gets_ellipsis(self):
        out, t = truncate_words("Vote Viper with me because " + words(30), 10)
        self.assertTrue(t)
        self.assertTrue(out.endswith(ELLIPSIS))
        self.assertEqual(len(out.split()), 10)
        self.assertEqual(out, "Vote Viper with me because w0 w1 w2 w3 w4" + ELLIPSIS)

    def test_sentence_end_must_keep_half_the_cap(self):
        # Sentence end at word 5 of a 10-word cap: 5 >= 5, kept.
        out, _ = truncate_words(words(4) + " stop. " + words(10), 10)
        self.assertEqual(out, words(4) + " stop.")
        # At word 4: too short, so all 10 words and the ellipsis.
        out, _ = truncate_words(words(3) + " stop. " + words(10), 10)
        self.assertEqual(out, words(3) + " stop. " + words(6) + ELLIPSIS)

    def test_closing_quote_or_bracket_after_full_stop(self):
        for end in ('go."', "go.'", "go.”", "go.)", "go!’", "go?)\""):
            out, t = truncate_words(f"He told me {end} " + words(20), 8)
            self.assertEqual((out, t), (f"He told me {end}", True), end)
        # A full stop inside a word, or an opening quote, is not a sentence end.
        out, _ = truncate_words("I saw e.g it " + words(20), 6)
        self.assertTrue(out.endswith(ELLIPSIS))

    def test_grace_zero_is_a_hard_limit(self):
        cap = hard_cap(60, 0)
        for n in (60, 61, 75, 200):
            out, t = truncate_words(words(n), cap)
            self.assertLessEqual(len(out.split()), 60)
            self.assertEqual(t, n > 60)
        out, t = truncate_words(words(30) + ". " + words(31), cap)       # 61 words, sentence end at 30
        self.assertEqual((out, t), (words(30) + ".", True))

    def test_truncated_fields_from_clean_reply(self):
        ctx = {"others": ["A", "B"], "alive": ["A", "B", "Me"], "self": "Me", "card_players": ["A", "B"],
               "challengeable": [], "on_team": False}
        schema = turn_schema("discuss", ctx)
        base = {"confessional": "short", "public": "short", "claims": [{"text": "x", "truthful": True}],
                "memory": "short",
                "move": {"accuse": "none", "challenges": [], "clue_cards": [], "job_claim": "none",
                           "suspicion": {"A": 10, "B": 20}}}
        caps = {"confessional": 10, "public": 10, "memory": 10}
        out, err, fields = clean_reply("discuss", base, schema, ctx, caps)
        self.assertEqual((err, fields), (None, []))
        long = dict(base, public=words(30), memory="Done. " + words(30),
                    claims=[{"text": words(11), "truthful": False}])
        out, err, fields = clean_reply("discuss", long, schema, ctx, caps)
        self.assertIsNone(err)
        self.assertEqual(fields, ["public", "memory", "claims"])
        self.assertEqual(out["public"], words(10) + ELLIPSIS)
        self.assertTrue(out["memory"].endswith(ELLIPSIS))                 # "Done." is under half the cap
        _, err, fields = clean_reply("discuss", dict(long, action={}), schema, ctx, caps)
        self.assertIsNotNone(err)
        self.assertEqual(fields, [])


def long_policy(public_words=100, recap_words=200):
    """Discussion statements and recaps far over their caps, in full sentences of 7 words."""
    sentence = "This is one full sentence here."               # 7 words with the counter word
    def text(n):
        out = []
        while len(out) < n:
            out += (f"S{len(out)} " + sentence).split()
        return " ".join(out[:n])

    rng = random.Random(3)

    def policy(model, system, prompt, schema, phase, player):
        if phase == "recap":
            return {"recap": text(recap_words)}
        d = random_valid(schema, rng)
        if phase == "discuss":
            d["public"] = text(public_words)
        return d
    return policy


class TruncatedFields(unittest.TestCase):
    def test_turns_carry_truncated_fields(self):
        cfg = make_config()
        game, _ = run_game(2, cfg, policy=long_policy())
        ev = game.log.events
        cap = hard_cap(cfg.limits.public_words, cfg.limits.word_grace)
        for t in turns(ev):
            self.assertIn("truncated_fields", t)
            self.assertEqual(t["truncated"], bool(t["truncated_fields"]))
            if t["turn_phase"] == "discuss" and not t["fallback"]:
                self.assertEqual(t["truncated_fields"], ["public"])
                n = len(t["public"].split())
                self.assertLessEqual(n, cap)
                self.assertGreater(n, cfg.limits.public_words - 7)   # the grace keeps most of the text
                self.assertTrue(t["public"].endswith("here."), t["public"])
            elif t["turn_phase"] != "discuss":
                self.assertEqual(t["truncated_fields"], [])
        rcap = hard_cap(cfg.narrator.recap_words, cfg.limits.word_grace)
        for r in events_of(ev, "recap"):
            self.assertLessEqual(len(r["text"].split()), rcap)
            self.assertTrue(r["text"].endswith("here."))
        md = render(ev)
        self.assertIn("truncated: public", md)

    def test_visibility_same_as_truncated(self):
        game, _ = run_game(2, make_config(), policy=long_policy())
        ev = game.log.events
        for viewer in [p.name for p in game.players] + [None]:
            for e in visible_events(ev, viewer):
                if e["type"] != "turn":
                    continue
                own = viewer is not None and e["player"] == viewer
                self.assertEqual("truncated_fields" in e, own, (viewer, e.get("turn_phase")))
                self.assertEqual("truncated" in e, own)

    def test_old_turns_without_the_field_still_render(self):
        game, _ = run_game(2, make_config(), policy=long_policy())
        old = copy.deepcopy(game.log.events)
        for e in old:
            e.pop("truncated_fields", None)
            if e["type"] == "game_start":
                e.pop("batch", None)
        md = render(old)
        self.assertIn("_(truncated)_", md)


class WordGraceConfig(unittest.TestCase):
    def test_default_and_files(self):
        self.assertEqual(make_config().limits.word_grace, 0.15)
        for name in ("default.toml", "pilot.toml", "bench.toml"):
            with open(ROOT / "config" / name, "rb") as f:
                self.assertEqual(tomllib.load(f)["limits"]["word_grace"], 0.15, name)

    def test_validation(self):
        for ok in (0, 0.0, 0.5, 1, 1.0):
            raw = raw_default()
            raw["limits"]["word_grace"] = ok
            self.assertEqual(config_from_dict(raw).limits.word_grace, ok)
        for bad in (-0.1, 1.01, 2, "0.15", True):
            raw = raw_default()
            raw["limits"]["word_grace"] = bad
            with self.assertRaises(ConfigError, msg=repr(bad)):
                config_from_dict(raw)

    def test_system_prompt_says_what_happens_without_the_grace(self):
        game, _ = run_game(1, make_config())
        system = game.system_prompts[game.players[0].name]
        self.assertIn("text past a limit is cut back to its last complete sentence, so finish what you are "
                      "saying inside the limit", system)
        self.assertNotIn("mid-sentence", system)
        for leak in ("15%", "0.15", "grace", " 69 ", " 81 ", " 58 "):
            self.assertNotIn(leak, system)
        self.assertIn("at most 60 words", system)                       # the told limit is unchanged


# --------------------------------------------------------------------------- Part B

def run_cli(argv, client_factory=None):
    old = cli.make_client
    if client_factory is not None:
        cli.make_client = client_factory
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(argv)
    finally:
        cli.make_client = old
    return rc, out.getvalue(), err.getvalue()


def erroring_client():
    """Every call fails (as when a usage limit is hit): every turn falls back after its retries."""
    return MockLLM(0, policy=lambda *a: LLMReply(None, "", None, zero_usage(), 0.0, "exit 1: usage limit", "cli"))


class Slow(MockLLM):
    """A mock that takes a moment per call, so other games' events interleave with it."""

    async def call(self, **kw):
        await asyncio.sleep(0.002)
        return await super().call(**kw)


class Crash(RuntimeError):
    pass


def crashing_client():
    def policy(*a):
        raise Crash("engine bug")
    return MockLLM(0, policy=policy)


def sequence(*makers):
    """A make_client stand-in: the n-th game gets makers[n] (the last one repeats)."""
    n = [0]

    def make(cfg):
        m = makers[min(n[0], len(makers) - 1)]
        n[0] += 1
        return m()
    return make


def batch_argv(d, name="b1", games=4, seed=1, parallel=1, extra=()):
    return ["batch", "--config", str(PILOT_TOML), "--name", name, "--games", str(games), "--seed", str(seed),
            "--parallel-games", str(parallel), "--out", d, *extra]


def normalised(path: Path) -> list[str]:
    """Log lines without timestamps, the timestamped game id, and timings."""
    out = []
    for e in read_log(path):
        for k in ("ts", "game_id", "wall_s", "latency_s"):
            e.pop(k, None)
        out.append(json.dumps(e, sort_keys=True))
    return out


def log_for(d: str, seed: int) -> Path:
    logs = sorted(Path(d).glob(f"g-*-s{seed}.jsonl"))
    assert len(logs) == 1, logs
    return logs[0]


class Batch(unittest.TestCase):
    def test_batch_name_on_game_start_and_index_and_run_is_null(self):
        with tempfile.TemporaryDirectory() as d:
            rc, out, err = run_cli(batch_argv(d, games=2, extra=["--mock"]))
            self.assertEqual(rc, 0, out + err)
            rows = read_index(Path(d) / "index.jsonl")
            self.assertEqual([(r["seed"], r["batch"], r["spoiled"]) for r in rows], [(1, "b1", False), (2, "b1", False)])
            for r in rows:
                start = read_log(r["log"])[0]
                self.assertEqual(start["batch"], "b1")
                self.assertTrue(Path(r["log"]).with_suffix(".md").exists())
            self.assertIn("seed 1", out)
            self.assertIn("totals:", out)
            self.assertIn("cost_usd", out)                                   # the summary table
            rc, *_ = run_cli(["run", "--config", str(PILOT_TOML), "--seed", "9", "--mock", "--out", d])
            self.assertEqual(rc, 0)
            row = read_index(Path(d) / "index.jsonl")[-1]
            self.assertEqual((row["seed"], row["batch"], row["spoiled"]), (9, None, False))
            self.assertIsNone(read_log(row["log"])[0]["batch"])

    def test_resume_skips_finished_seeds(self):
        with tempfile.TemporaryDirectory() as d:
            rc, out, _ = run_cli(batch_argv(d, games=2, parallel=2, extra=["--mock"]))
            self.assertEqual(rc, 0)
            rc, out, _ = run_cli(batch_argv(d, games=3, parallel=2, extra=["--mock"]))
            self.assertEqual(rc, 0)
            self.assertIn("skipping 2 seed(s) already finished in this batch: 1, 2", out)
            rows = read_index(Path(d) / "index.jsonl")
            # Rows are appended as games finish, so with 2 in parallel the order is not the seed order.
            self.assertEqual(sorted(r["seed"] for r in rows), [1, 2, 3])
            rc, out, _ = run_cli(batch_argv(d, games=3, extra=["--mock"]))
            self.assertEqual(rc, 0)
            self.assertIn("nothing to play", out)
            self.assertEqual(len(read_index(Path(d) / "index.jsonl")), 3)
            # Another batch name in the same index does not count.
            rc, out, _ = run_cli(batch_argv(d, name="other", games=1, extra=["--mock"]))
            self.assertEqual(len(read_index(Path(d) / "index.jsonl")), 4)

    def test_stop_rule_spoils_stops_and_resumes(self):
        with tempfile.TemporaryDirectory() as d:
            make = sequence(lambda: MockLLM(1), erroring_client, lambda: MockLLM(3))
            rc, out, err = run_cli(batch_argv(d, games=4, extra=["--no-preflight"]), make)
            self.assertEqual(rc, 3, out + err)
            self.assertIn("STOPPED", out)
            self.assertIn("spoiled", out)
            self.assertIn("not started: 3, 4", out)
            resume = ("python3.11 -m inside_job batch --config " + str(PILOT_TOML) + " --name b1 --games 4 "
                      "--seed 1 --parallel-games 1 --out " + d + " --max-fallback-share 0.1 --no-preflight")
            self.assertIn(resume, out)
            rows = read_index(Path(d) / "index.jsonl")
            self.assertEqual([(r["seed"], r["spoiled"]) for r in rows], [(1, False), (2, True)])
            spoiled_end = read_log(rows[1]["log"])[-1]
            self.assertGreater(spoiled_end["fallbacks"] / spoiled_end["calls"], 0.10)
            self.assertEqual(finished_seeds(Path(d) / "index.jsonl", "b1"), {1})
            # Resume: the spoiled seed is replayed, the finished one skipped.
            rc, out, err = run_cli(batch_argv(d, games=4, extra=["--no-preflight"]), lambda cfg: MockLLM(5))
            self.assertEqual(rc, 0, out + err)
            self.assertIn("skipping 1 seed(s) already finished in this batch: 1", out)
            rows = read_index(Path(d) / "index.jsonl")
            self.assertEqual([(r["seed"], r["spoiled"]) for r in rows],
                             [(1, False), (2, True), (2, False), (3, False), (4, False)])
            self.assertEqual(finished_seeds(Path(d) / "index.jsonl", "b1"), {1, 2, 3, 4})

    def test_stop_rule_lets_running_games_finish(self):
        with tempfile.TemporaryDirectory() as d:
            make = sequence(erroring_client, lambda: Slow(2))
            rc, out, _ = run_cli(batch_argv(d, games=5, parallel=2, extra=["--no-preflight"]), make)
            self.assertEqual(rc, 3)
            rows = read_index(Path(d) / "index.jsonl")
            self.assertEqual(sorted((r["seed"], r["spoiled"]) for r in rows), [(1, True), (2, False)])
            self.assertIn("not started: 3, 4, 5", out)

    def test_threshold_is_respected(self):
        with tempfile.TemporaryDirectory() as d:
            rc, out, _ = run_cli(batch_argv(d, games=2, extra=["--no-preflight", "--max-fallback-share", "1"]),
                                 lambda cfg: erroring_client())
            self.assertEqual(rc, 0)
            self.assertEqual([r["spoiled"] for r in read_index(Path(d) / "index.jsonl")], [False, False])

    def test_unfinished_game_is_replayed(self):
        with tempfile.TemporaryDirectory() as d:
            make = sequence(lambda: MockLLM(1), crashing_client, lambda: MockLLM(3))
            rc, out, err = run_cli(batch_argv(d, games=3, extra=["--no-preflight"]), make)
            self.assertEqual(rc, 1, out + err)
            self.assertIn("crashed", out)
            cut = read_log(log_for(d, 2))
            self.assertFalse(any(e["type"] == "game_end" for e in cut))     # a log with no game_end
            self.assertEqual([r["seed"] for r in read_index(Path(d) / "index.jsonl")], [1])
            rc, out, _ = run_cli(batch_argv(d, games=3, extra=["--no-preflight"]), lambda cfg: MockLLM(4))
            self.assertEqual(rc, 0)
            self.assertEqual([r["seed"] for r in read_index(Path(d) / "index.jsonl")], [1, 2, 3])

    def test_preflight_once_and_never_with_mock(self):
        from test_v03 import FakeClient
        with tempfile.TemporaryDirectory() as d:
            client = FakeClient(blocked={"claude-sonnet-5"})
            rc, out, err = run_cli(batch_argv(d, games=2), lambda cfg: client)
            self.assertEqual(rc, 2)
            self.assertIn("claude-sonnet-5 is blocked", err)
            self.assertFalse(list(Path(d).glob("*.jsonl")))
            n = len(client.calls)
            rc, *_ = run_cli(batch_argv(d, games=2, extra=["--mock"]), lambda cfg: client)
            self.assertEqual(rc, 0)
            self.assertEqual(len(client.calls), n)                           # --mock: no preflight
            # Preflight passes, then games are played with per-game clients: preflight calls happen once.
            calls = []
            good = FakeClient()

            def make(cfg):
                calls.append(1)
                return good if len(calls) == 1 else MockLLM(len(calls))
            rc, out, err = run_cli(batch_argv(d, name="pf", games=2), make)
            self.assertEqual(rc, 0, err)
            self.assertEqual(err.count("preflight: one real"), 1)
            self.assertEqual(len(calls), 3)                                  # preflight + one per game

    def test_parallel_games_are_deterministic_and_equal_to_run(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d3, \
                tempfile.TemporaryDirectory() as dr:
            self.assertEqual(run_cli(batch_argv(d1, games=4, parallel=1, extra=["--mock"]))[0], 0)
            self.assertEqual(run_cli(batch_argv(d3, games=4, parallel=3, extra=["--mock"]))[0], 0)
            for seed in range(1, 5):
                a, b = normalised(log_for(d1, seed)), normalised(log_for(d3, seed))
                self.assertEqual(a, b, f"seed {seed}")
                # Exactly the game `run` plays, apart from the batch name.
                self.assertEqual(run_cli(["run", "--config", str(PILOT_TOML), "--seed", str(seed), "--mock",
                                          "--out", dr])[0], 0)
                r = normalised(log_for(dr, seed))
                a0 = json.loads(a[0])
                self.assertEqual(a0.pop("batch"), "b1")
                r0 = json.loads(r[0])
                self.assertIsNone(r0.pop("batch"))
                self.assertEqual((a0, a[1:]), (r0, r[1:]))

    def test_call_ceiling_is_parallel_games_times_max_parallel_calls(self):
        """Real ClaudeCLI clients (one per game) with a fake subprocess that counts calls in flight."""
        flight = {"now": 0, "peak": 0}

        class Proc:
            returncode = 0

            def __init__(self, argv):
                self.argv = argv

            async def communicate(self):
                flight["now"] += 1
                flight["peak"] = max(flight["peak"], flight["now"])
                await asyncio.sleep(0.002)
                flight["now"] -= 1
                argv = self.argv
                schema = json.loads(argv[argv.index("--json-schema") + 1])
                model = argv[argv.index("--model") + 1]
                data = random_valid(schema, random.Random(argv[-1]))
                return json.dumps({"is_error": False, "result": json.dumps(data), "structured_output": data,
                                   "modelUsage": {model: {"inputTokens": 10, "outputTokens": 5}}}).encode(), b""

        async def fake_exec(*argv, **kw):
            return Proc(argv)

        cfg = load_config(PILOT_TOML)
        m = cfg.limits.max_parallel_calls
        with tempfile.TemporaryDirectory() as d:
            rc, out, err = run_cli(batch_argv(d, games=2, parallel=2, extra=["--no-preflight"]),
                                   lambda c: ClaudeCLI.from_config(c, exec_fn=fake_exec))
            self.assertEqual(rc, 0, out + err)
            self.assertLessEqual(flight["peak"], 2 * m)
            self.assertGreater(flight["peak"], m)                         # the two games really overlapped
            self.assertEqual(len(read_index(Path(d) / "index.jsonl")), 2)

    def test_ctrl_c_stops_cleanly(self):
        if threading.current_thread() is not threading.main_thread():
            self.skipTest("SIGINT handling needs the main thread")
        with tempfile.TemporaryDirectory() as d:
            timer = threading.Timer(0.5, os.kill, (os.getpid(), signal.SIGINT))
            timer.start()
            try:
                rc, out, err = run_cli(batch_argv(d, games=50, extra=["--no-preflight"]), lambda cfg: Slow(1))
            finally:
                timer.cancel()
            self.assertEqual(rc, 130, out + err)
            self.assertIn("interrupted", out)
            self.assertIn("resume with:", out)
            self.assertIn("cut off (will be replayed)", out)
            finished = {r["seed"] for r in read_index(Path(d) / "index.jsonl")}
            self.assertLess(len(finished), 50)


if __name__ == "__main__":
    unittest.main()
