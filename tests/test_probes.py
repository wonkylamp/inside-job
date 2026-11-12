"""Read probes (docs/PROBES.md, tests 1-9): exact text, replay, cross-checks, privacy, freeze,
selection, run loop, scoring maths, CLI end to end. No model calls; temporary files only."""

import asyncio
import contextlib
import io
import json
import math
import random
import statistics
import tempfile
import unittest
from pathlib import Path

from inside_job import probes as P
from inside_job.__main__ import main
from inside_job.config import load_config
from inside_job.engine import Game
from inside_job.llm import ClaudeCLI, LLMReply, MockLLM, build_argv, random_valid, zero_usage

ROOT = Path(__file__).resolve().parent.parent
CONFIGS = (ROOT / "config" / "pilot.toml", ROOT / "config" / "pilot2.toml")
SEEDS = (1, 2, 3, 4)
RULE = "\n\nYour previous reply was rejected: {}. Reply again with valid JSON."

_GAMES: list = []


def mock_games() -> list:
    """(config stem, events, MockLLM) for seeds 1-4 under both pilot configs, played in memory once."""
    if not _GAMES:
        for path in CONFIGS:
            cfg = load_config(path)
            for seed in SEEDS:
                llm = MockLLM(seed)
                game = Game(cfg, llm, seed, game_id=f"mock-{path.stem}-s{seed}", clock=lambda: "")
                game.run()
                _GAMES.append((path.stem, game.log.events, llm))
    return _GAMES


def roles(events) -> dict:
    return {q["name"]: q["role"] for q in next(e for e in events if e["type"] == "game_start")["players"]}


def crew_votes(events) -> list:
    r = roles(events)
    return [t for t in events if t["type"] == "turn" and t.get("turn_phase") == "vote"
            and r[t["player"]] == "crew" and not t.get("fallback")]


def wire(turn) -> dict:
    """A logged turn as the reply that produced it (the move under `move`)."""
    return {"confessional": turn["confessional"], "public": turn["public"], "claims": turn["claims"],
            "memory": turn["memory"], "move": turn["action"]}


def all_crew_probes() -> list:
    return [P.make_probe(ev, t, b) for b, ev, _ in mock_games() for t in crew_votes(ev)]


class Seq:
    """A client that answers from a list of reply makers, then repeats the last; records prompts."""

    def __init__(self, *makers):
        self.makers = list(makers)
        self.prompts = []

    async def call(self, *, model, system, prompt, schema, phase=None, player=None, view=None):
        self.prompts.append(prompt)
        make = self.makers[min(len(self.prompts), len(self.makers)) - 1]
        out = make(schema)
        if isinstance(out, LLMReply):
            return out
        return LLMReply(out, json.dumps(out), model, zero_usage(), 0.0)


def valid(schema):
    return random_valid(schema, random.Random(7))


def invalid(schema):
    return {"bad": 1}


def blocked(schema):
    return LLMReply(None, "safeguards flagged this", None, zero_usage(), 0.0, "blocked: safeguards flagged",
                    "blocked")


class FakeProc:
    def __init__(self, stdout=b"", hang=False):
        self._out, self.hang, self.returncode = stdout, hang, 0

    async def communicate(self):
        if self.hang:
            await asyncio.sleep(30)
        return self._out, b""

    def kill(self):
        pass

    async def wait(self):
        return 0


class Recorder:
    def __init__(self, proc):
        self.proc, self.calls = proc, []

    async def __call__(self, *argv, **kw):
        self.calls.append((argv, kw))
        return self.proc


def quiet(fn, *a):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn(*a)


# --------------------------------------------------------------------------- 1, 2

class ExactText(unittest.TestCase):
    def test_probe_text_is_what_the_mock_received(self):
        n = 0
        for _, events, llm in mock_games():
            calls: dict = {}
            for c in llm.calls:
                if c["phase"] == "vote":
                    calls.setdefault(c["player"], []).append(c)
            seen: dict = {}
            for t in events:
                if t["type"] != "turn" or t.get("turn_phase") != "vote":
                    continue
                k = seen[t["player"]] = seen.get(t["player"], -1) + 1   # the player's k-th vote call
                if roles(events)[t["player"]] != "crew":
                    continue
                self.assertFalse(t.get("fallback"))
                c = calls[t["player"]][k]
                p = json.loads(P.probe_line(P.make_probe(events, t, "mock")))   # through the frozen form
                self.assertEqual(p["system"], c["system"])
                self.assertEqual(p["prompt"], c["prompt"])
                self.assertEqual(p["schema"], c["schema"])
                self.assertEqual(json.dumps(p["schema"], separators=(",", ":")),
                                 json.dumps(c["schema"], separators=(",", ":")))   # same bytes on the wire
                n += 1
        self.assertGreater(n, 50)


class Replay(unittest.TestCase):
    def test_logged_reply_gives_logged_score_and_vote(self):
        logged = {}
        for _, events, _ in mock_games():
            for t in crew_votes(events):
                logged[(t["game_id"], t["seq"])] = wire(t)
        probes = all_crew_probes()
        by_prompt = {p["prompt"]: logged[(p["game_id"], p["seq"])] for p in probes}
        llm = MockLLM(0, policy=lambda model, system, prompt, schema, phase, player: by_prompt[prompt])
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "run.jsonl"
            asyncio.run(P.run_set(probes, llm, model="m", effort="", cap=-1, out=out, parallel=4))
            recs = P.read_run(out)
        self.assertEqual(len(recs), len(probes))
        for p in probes:
            r = recs[p["probe_id"]]
            self.assertTrue(r["ok"])
            self.assertEqual(r["attempts"], 1)
            row = P.probe_rows(p, r["suspicion"], r["vote"])
            self.assertAlmostEqual(row["model"], p["orig"]["brier"], delta=1e-12)
            self.assertEqual(r["vote"], p["orig"]["vote"])


# --------------------------------------------------------------------------- 3

class CrossCheck(unittest.TestCase):
    def setUp(self):
        try:
            import numpy  # noqa: F401
            from analysis import common, strategies
        except ImportError as e:
            self.skipTest(f"analysis needs numpy: {e}")
        self.common, self.strategies = common, strategies

    def test_against_analysis_on_mock_games(self):
        from inside_job.solver import player_worlds, table_worlds
        n = 0
        for _, events, _ in mock_games():
            g = self.common.GameData(events, "mock")
            for t in crew_votes(events):
                rb = P.rebuild_vote(events, t)
                self.assertEqual(rb["cutoff"], g.cutoff(t))
                self.assertEqual(rb["ctx"], self.common.rebuild_ctx(g, t))
                self.assertEqual((rb["system"], rb["prompt"], rb["schema"]), self.common.rebuild_prompt(g, t))
                p = P.make_probe(events, t, "mock")
                inp = g.solver_inputs(rb["cutoff"], t["player"])        # as the scratch `worlds_for`
                args = (inp["players"], inp["num_moles"], inp["revealed"])
                w = player_worlds(*args, inp["cards"], inp["jobs"], player=inp["player"],
                                  own_clues=inp["own_clues"], pair_cards=inp["pair_cards"])
                fb = [x for x in table_worlds(*args, [], inp["jobs"]) if inp["player"] not in x]
                wp = self.strategies.weighted_posterior(w, inp["players"], inp["jobs"], 0.5, fb)
                for name in p["rated"]:
                    self.assertAlmostEqual(p["formula"]["jobw50"][name], wp[name], delta=1e-12)
                n += 1
        self.assertGreater(n, 50)

    def test_pilot1_brier_matches_decision_table(self):
        index, table = ROOT / "games" / "index.jsonl", ROOT / "analysis" / "out" / "decisions_pilot1.jsonl"
        if not (index.exists() and table.exists()):
            self.skipTest("no pilot1 logs or decision table")
        from inside_job.report import load_batch
        rows = {}
        with open(table, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if r.get("kind") == "belief" and r.get("turn_phase") == "vote":
                    rows[(r["game_id"], r["seq"])] = r["brier_model"]
        done = set()
        for events in load_batch(ROOT / "games", "pilot1").games:
            for t in crew_votes(events):
                key = (t["game_id"], t["seq"])
                self.assertIn(key, rows)
                self.assertAlmostEqual(P.make_probe(events, t, "pilot1")["orig"]["brier"], rows[key], delta=1e-9)
                done.add(key)
        self.assertEqual(done, set(rows))
        self.assertGreater(len(done), 100)


# --------------------------------------------------------------------------- 4

class NothingPrivate(unittest.TestCase):
    def test_argv_holds_only_system_prompt_schema(self):
        probe = all_crew_probes()[0]
        leaky = dict(probe, truth={n: "LEAK-TRUTH" for n in probe["rated"]},
                     formula={k: {n: "LEAK-FORMULA" for n in probe["rated"]} for k in P.FORMULAS},
                     orig={"suspicion": {n: "LEAK-ORIG" for n in probe["rated"]}, "vote": "LEAK-VOTE",
                           "brier": "LEAK-BRIER"},
                     game_id="LEAK-GAME", orig_model="LEAK-MODEL", batch="LEAK-BATCH", strata={"x": "LEAK-STRATA"})
        out = {"is_error": False, "result": "", "structured_output": valid(probe["schema"]),
               "modelUsage": {"claude-x": {"inputTokens": 1, "outputTokens": 1}}}
        rec = Recorder(FakeProc(json.dumps(out).encode()))
        cli = ClaudeCLI(exec_fn=rec, effort="high", max_thinking_tokens=-1)
        r = asyncio.run(P.ask_probe(cli, leaky, "claude-x"))
        self.assertTrue(r["ok"])
        argv, kw = rec.calls[0]
        self.assertEqual(list(argv), build_argv("claude-x", probe["system"], probe["prompt"], probe["schema"],
                                                effort="high"))
        sent = "\n".join(argv) + json.dumps(kw["env"])
        self.assertNotIn("LEAK", sent)


# --------------------------------------------------------------------------- 5, 6, 9 (CLI on mock batches)

class CLI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.d = Path(cls.tmp.name)
        cls.games = cls.d / "games"
        code = quiet(main, ["batch", "--config", str(CONFIGS[0]), "--name", "mockb", "--games", "3", "--seed", "1",
                            "--mock", "--out", str(cls.games)])
        assert code == 0, code

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def build(self, out, n=12, seed=5):
        return quiet(main, ["probes", "build", "--games", str(self.games), "--batch", "mockb", "--n", str(n),
                            "--seed", str(seed), "--out", str(out)])

    def test_5_freeze(self):
        a, b = self.d / "f" / "a.jsonl", self.d / "f" / "b.jsonl"
        self.assertEqual(self.build(a), 0)
        self.assertEqual(self.build(b), 0)
        self.assertEqual(a.read_bytes(), b.read_bytes())
        self.assertEqual(quiet(main, ["probes", "verify", "--set", str(a)]), 0)
        # build will not overwrite
        before = a.read_bytes()
        self.assertEqual(self.build(a, n=3, seed=9), 2)
        self.assertEqual(a.read_bytes(), before)
        with self.assertRaises(FileExistsError):
            P.write_set([], a, {}, {})
        # one character of one prompt changed: verify, run and score all refuse
        bad = self.d / "f" / "bad.jsonl"
        lines = a.read_text(encoding="utf-8").splitlines()
        p = json.loads(lines[0])
        p["prompt"] = "X" + p["prompt"][1:]
        bad.write_text("\n".join([P.probe_line(p)] + lines[1:]) + "\n", encoding="utf-8")
        P.manifest_path(bad).write_text(P.manifest_path(a).read_text(encoding="utf-8"), encoding="utf-8")
        self.assertTrue(P.verify_set(bad))
        runs = self.d / "f" / "runs"
        self.assertEqual(quiet(main, ["probes", "verify", "--set", str(bad)]), 1)
        self.assertEqual(quiet(main, ["probes", "run", "--set", str(bad), "--model", "m", "--mock",
                                      "--runs", str(runs)]), 1)
        self.assertEqual(quiet(main, ["probes", "score", "--set", str(bad), "--runs", str(runs)]), 1)
        self.assertFalse(runs.exists())

    def test_9_run_mock_then_score(self):
        s = self.d / "e2e" / "read.jsonl"
        runs = self.d / "e2e" / "runs"
        self.assertEqual(self.build(s, n=8), 0)
        for model, effort in (("claude-a", ""), ("claude-a", "high"), ("claude-b", "high")):
            argv = ["probes", "run", "--set", str(s), "--model", model, "--mock", "--runs", str(runs)]
            self.assertEqual(quiet(main, argv + (["--effort", effort] if effort else [])), 0)
        f = runs / "read" / "claude-a__none__t-1.jsonl"
        recs = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(recs), 8)
        self.assertTrue(all(r["ok"] for r in recs))
        md = self.d / "e2e" / "score.md"
        self.assertEqual(quiet(main, ["probes", "score", "--set", str(s), "--runs", str(runs), "--write", str(md)]), 0)
        text = md.read_text(encoding="utf-8")
        self.assertIn(P.sha256_file(s), text.splitlines()[0])
        for head in ("## Runs", "## Brier", "## Model minus jobw50", "## Votes", "## Between runs"):
            self.assertIn(head, text)
        self.assertIn("| claude-a / high / t-1 | claude-a / none / t-1 |", text)   # effort against effort
        self.assertIn("| claude-a / high / t-1 | claude-b / high / t-1 |", text)   # model against model


class Selection(unittest.TestCase):
    def setUp(self):
        self.games = [(b, ev) for b, ev, _ in mock_games()]
        self.cands = P.candidates(self.games)

    def test_only_crew_nonfallback_votes(self):
        ev = [dict(e) for e in self.games[0][1]]
        target = crew_votes(ev)[0]
        target["fallback"] = True
        cands = P.candidates([("x", ev)])
        self.assertNotIn(target["seq"], {p["seq"] for p in cands})
        for p in self.cands:
            events = next(e for b, e in self.games if e[0]["game_id"] == p["game_id"])
            t = next(e for e in events if e["seq"] == p["seq"])
            self.assertEqual((t["type"], t["turn_phase"], roles(events)[t["player"]], bool(t.get("fallback"))),
                             ("turn", "vote", "crew", False))
            self.assertGreater(p["strata"]["n_undecided"], 0)

    def test_one_per_cell_before_any_second(self):
        cells = {(p["game_id"], p["round"]) for p in self.cands}
        doubles = sum(1 for c in cells if sum(1 for p in self.cands if (p["game_id"], p["round"]) == c) > 1)
        for n in (5, len(cells), len(cells) + 3, len(self.cands)):
            got, info = P.select(self.cands, n, 11)
            keys = [(p["game_id"], p["round"]) for p in got]
            first = keys[:len(cells)]
            self.assertEqual(len(set(first)), len(first))                 # distinct cells first
            if n >= len(cells):
                self.assertEqual(set(first), cells)                       # every cell before a second
            self.assertEqual(info["second_seats"], min(max(0, n - len(cells)), doubles))
            self.assertEqual(len({p["probe_id"] for p in got}), len(got))
            games = sorted({g for g, _ in cells})
            self.assertEqual(len({k[0] for k in keys[:len(games)]}), min(n, len(games)))   # round-robin
        self.assertEqual(P.select(self.cands, 9, 11), P.select(self.cands, 9, 11))


# --------------------------------------------------------------------------- 7

class RunLoop(unittest.TestCase):
    def setUp(self):
        self.probes = all_crew_probes()[:6]
        self.p = self.probes[0]

    def test_invalid_then_valid_like_the_engine(self):
        llm = Seq(invalid, valid)
        r = asyncio.run(P.ask_probe(llm, self.p, "m"))
        self.assertEqual((r["ok"], r["attempts"], len(r["rejections"])), (True, 2, 1))
        self.assertEqual(llm.prompts[1], self.p["prompt"] + RULE.format(r["rejections"][0]))
        # the engine, given the same two replies, adds the same line
        cfg = load_config(CONFIGS[0])
        eng = Seq(invalid, valid)
        game = Game(cfg, eng, 1, game_id="g", clock=lambda: "")
        game.setup()
        game.round = 1
        crew = next(q.name for q in game.players if q.role == "crew")
        ctx = game.base_ctx(crew)
        pend = asyncio.run(game.ask(crew, "vote", ctx, game.prepare(crew, "vote", ctx)))
        self.assertEqual(pend.attempts, 2)
        self.assertEqual(pend.rejections, r["rejections"])
        self.assertEqual(eng.prompts[1][len(eng.prompts[0]):], llm.prompts[1][len(llm.prompts[0]):])

    def test_blocked_twice_fails(self):
        llm = Seq(blocked)
        r = asyncio.run(P.ask_probe(llm, self.p, "m"))
        self.assertEqual((r["ok"], r["error_kind"], r["attempts"]), (False, "blocked", 2))
        self.assertEqual(llm.prompts, [self.p["prompt"]] * 2)                # identical retry
        self.assertIsNone(r["suspicion"])

    def test_timeout_fails(self):
        cli = ClaudeCLI(timeout_s=0.02, exec_fn=Recorder(FakeProc(hang=True)))
        r = asyncio.run(P.ask_probe(cli, self.p, "m"))
        self.assertEqual((r["ok"], r["error_kind"], r["attempts"]), (False, "timeout", self.p["retries"] + 1))

    def test_resume_and_limit(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "r.jsonl"
            st = asyncio.run(P.run_set(self.probes, Seq(valid), model="m", effort="", cap=-1, out=out, limit=2))
            self.assertEqual(set(P.read_run(out)), {p["probe_id"] for p in self.probes[:2]})   # a prefix
            self.assertEqual(st["probes"], 2)
            asyncio.run(P.run_set(self.probes, Seq(blocked), model="m", effort="", cap=-1, out=out, limit=4))
            recs = P.read_run(out)
            self.assertEqual([recs[p["probe_id"]]["ok"] for p in self.probes[:4]], [True, True, False, False])
            llm = Seq(valid)
            st = asyncio.run(P.run_set(self.probes, llm, model="m", effort="", cap=-1, out=out))
            self.assertEqual((st["skipped"], st["probes"]), (2, 4))               # failed ones are run again
            self.assertEqual(len(llm.prompts), 4)
            self.assertTrue(all(r["ok"] for r in P.read_run(out).values()))
            lines = out.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2 + 2 + 4)
            self.assertTrue(all(json.loads(x)["model"] == "m" for x in lines))


# --------------------------------------------------------------------------- 8

def hand_probe(pid, game, s, f50, truth, vote, orig_vote, orig_s):
    """Two or three rated players; every formula equal to `f50` except `public` (all 0.5)."""
    rated = list(truth)
    f = {k: dict(zip(rated, f50)) for k in ("simple", "jobw50", "jobw80")}
    f["public"] = {n: 0.5 for n in rated}
    orig_sus = dict(zip(rated, orig_s))
    p = {"probe_id": pid, "game_id": game, "rated": rated, "truth": truth, "formula": f,
         "orig": {"suspicion": orig_sus, "vote": orig_vote,
                  "brier": sum((orig_sus[n] / 100 - truth[n]) ** 2 for n in rated) / len(rated)}}
    rec = {"probe_id": pid, "model": "m", "ok": True, "suspicion": dict(zip(rated, s)), "vote": vote,
           "usage": zero_usage(), "latency_s": 1.0, "served_model": "m", "error_kind": None}
    return p, rec


class Scoring(unittest.TestCase):
    def setUp(self):
        T = {"A": 1, "B": 0}
        T3 = {"A": 1, "B": 0, "C": 0}
        made = [hand_probe("p1", "g1", (80, 20), (0.5, 0.5), T, "A", "B", (50, 50)),
                hand_probe("p2", "g1", (40, 60), (0.9, 0.1), T, "B", "A", (100, 0)),
                hand_probe("p3", "g2", (60, 30, 30), (0.6, 0.3, 0.1), T3, "A", "A", (60, 30, 30)),
                hand_probe("p4", "g2", (100, 0), (0.5, 0.5), T, "A", "A", (90, 10)),
                hand_probe("p5", "g3", (50, 50), (0.3, 0.7), T, "B", "B", (0, 100)),
                hand_probe("p6", "g3", (20, 10, 70), (0.25, 0.25, 0.5), T3, "C", "A", (34, 33, 33))]
        self.probes = [p for p, _ in made]
        self.recs = {r["probe_id"]: r for _, r in made}

    def test_known_answers(self):
        s = P.score_run(self.probes, self.recs)
        # Brier of the model's reading, per probe, by hand
        bm = [(0.2 ** 2 + 0.2 ** 2) / 2, (0.6 ** 2 + 0.6 ** 2) / 2, (0.4 ** 2 + 0.3 ** 2 + 0.3 ** 2) / 3, 0.0,
              (0.5 ** 2 + 0.5 ** 2) / 2, (0.8 ** 2 + 0.1 ** 2 + 0.7 ** 2) / 3]
        bf = [(0.25 + 0.25) / 2, (0.01 + 0.01) / 2, (0.16 + 0.09 + 0.01) / 3, (0.25 + 0.25) / 2,
              (0.49 + 0.49) / 2, (0.5625 + 0.0625 + 0.25) / 3]
        self.assertEqual(s["valid"], 6)
        self.assertAlmostEqual(s["model"], sum(bm) / 6, delta=1e-12)
        self.assertAlmostEqual(s["jobw50"], sum(bf) / 6, delta=1e-12)
        self.assertAlmostEqual(s["public"], 0.25, delta=1e-12)
        d = [a - b for a, b in zip(bm, bf)]
        self.assertAlmostEqual(s["diff"]["mean"], sum(d) / 6, delta=1e-12)
        gm = [(d[0] + d[1]) / 2, (d[2] + d[3]) / 2, (d[4] + d[5]) / 2]
        c, lo, hi = s["diff"]["t"]
        half = 4.3027 * statistics.stdev(gm) / math.sqrt(3)
        self.assertAlmostEqual(c, sum(gm) / 3, delta=1e-12)
        self.assertAlmostEqual(hi - lo, 2 * half, delta=1e-12)
        # undecided ratings (jobw50 in [0.2, 0.8]): p1 A,B; p3 A,B; p4 A,B; p5 A,B; p6 A,B,C; p2 none
        und = [((0.2 ** 2 - 0.25) + (0.2 ** 2 - 0.25)) / 2, ((0.16 - 0.16) + (0.09 - 0.09)) / 2,
               ((0.0 - 0.25) + (0.0 - 0.25)) / 2, ((0.25 - 0.49) + (0.25 - 0.49)) / 2,
               ((0.64 - 0.5625) + (0.01 - 0.0625) + (0.49 - 0.25)) / 3]
        self.assertEqual(s["diff_und"]["n"], 5)
        self.assertAlmostEqual(s["diff_und"]["mean"], sum(und) / 5, delta=1e-12)
        # slope: sum((s-f)(t-f)) / sum((s-f)^2) over those ratings
        terms = [(0.3, 0.5), (-0.3, -0.5), (0.0, 0.4), (0.0, -0.3), (0.5, 0.5), (-0.5, -0.5), (0.2, 0.7),
                 (-0.2, -0.7), (-0.05, 0.75), (-0.15, -0.25), (0.2, -0.5)]
        num = sum(a * b for a, b in terms)
        den = sum(a * a for a, _ in terms)
        self.assertAlmostEqual(s["slope"]["slope"], num / den, delta=1e-12)
        self.assertEqual(s["slope"]["n"], 11)
        # votes on a mole: model A,B,A,A,B,C -> 3/6; original B,A,A,A,B,A -> 4/6; formula top
        self.assertAlmostEqual(s["vote"], 3 / 6, delta=1e-12)
        self.assertAlmostEqual(s["vote_orig"], 4 / 6, delta=1e-12)
        self.assertAlmostEqual(s["vote_top"], (0.5 + 1 + 1 + 0.5 + 0 + 0) / 6, delta=1e-12)
        orig = [0.25, 0.0, (0.16 + 0.09 + 0.09) / 3, (0.01 + 0.01) / 2, 1.0, (0.66 ** 2 + 0.33 ** 2 + 0.33 ** 2) / 3]
        self.assertAlmostEqual(s["orig"], sum(orig) / 6, delta=1e-12)

    def test_bootstrap_is_reproducible(self):
        a = P.score_run(self.probes, self.recs)
        b = P.score_run(self.probes, self.recs)
        self.assertEqual((a["diff"]["boot"], a["diff_und"]["boot"], a["slope"]["boot"]),
                         (b["diff"]["boot"], b["diff_und"]["boot"], b["slope"]["boot"]))
        lo, hi = a["diff"]["boot"]
        self.assertLessEqual(lo, a["diff"]["mean"])
        self.assertLessEqual(a["diff"]["mean"], hi)
        same = P.paired([("g1", 0.1), ("g2", 0.1), ("g2", 0.1), ("g3", 0.1)])     # resampling cannot move it
        self.assertAlmostEqual(same["boot"][0], 0.1, delta=1e-12)
        self.assertAlmostEqual(same["boot"][1], 0.1, delta=1e-12)
        ten = [(f"g{i}", float(i * i)) for i in range(10)]                     # the seed is what fixes it
        self.assertEqual(P.bootstrap(ten, P._mean, seed=1), P.bootstrap(ten, P._mean, seed=1))
        self.assertNotEqual(P.bootstrap(ten, P._mean, seed=1), P.bootstrap(ten, P._mean, seed=2))

    def test_t_quantile(self):
        self.assertEqual(P.t975(10), 2.2281)
        self.assertTrue(2.0211 > P.t975(50) > 2.0003)
        self.assertTrue(1.9799 > P.t975(500) > 1.96)


if __name__ == "__main__":
    unittest.main()
