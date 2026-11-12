"""The raw sidecar log and the code stamp (docs/RAWLOG.md). Mock client only, no model calls."""

import asyncio
import contextlib
import copy
import gzip
import hashlib
import io
import json
import os
import random
import shutil
import tempfile
import unittest
from pathlib import Path

from inside_job import __main__ as cli
from inside_job import rawlog
from inside_job.batch import read_index
from inside_job.config import load_config
from inside_job.engine import Game
from inside_job.llm import ClaudeCLI, LLMReply, MockLLM, build_argv, parse_cli_output, random_valid, zero_usage
from inside_job.log import project, read_log, visible_events
from inside_job.prompts import NARRATOR_SYSTEM
from inside_job.rawlog import (FINGERPRINT_FILES, RawLog, code_fingerprint, raw_path_for, read_raw,
                               schema_sha256)

from helpers import ROOT, fixed_clock, make_config

PILOT_TOML = ROOT / "config" / "pilot.toml"
REJECT_MARK = "Your previous reply was rejected: "


def play(seed=1, cfg=None, policy=None, raw_dir=None, provenance=None, raw_cls=RawLog, game_id="g-test"):
    """One mock game; with `raw_dir` a raw log is written there (and closed by the engine)."""
    cfg = cfg or make_config()
    raw = raw_cls(Path(raw_dir) / f"{game_id}.jsonl") if raw_dir else None
    game = Game(cfg, MockLLM(seed, policy=policy), seed, game_id=game_id, clock=fixed_clock, raw=raw,
                provenance=provenance)
    game.run()
    return game


def records(game) -> list[dict]:
    return read_raw(game.raw.final_path)


def kinds(recs, kind):
    return [r for r in recs if r["kind"] == kind]


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


def norm(events, drop_stamp=True):
    out = []
    for e in copy.deepcopy(events):
        for k in ("ts", "game_id", "wall_s", "latency_s"):
            e.pop(k, None)
        if drop_stamp and e["type"] == "game_start":
            e.pop("code_hash", None)
            e.pop("code_files", None)
        out.append(e)
    return out


# --------------------------------------------------------------------------- 1. structure

class Structure(unittest.TestCase):
    def test_records_link_to_the_main_log(self):
        with tempfile.TemporaryDirectory() as d:
            game = play(3, raw_dir=d, provenance=code_fingerprint())
            recs = records(game)
        self.assertEqual(recs[0]["kind"], "header")
        self.assertTrue(all(r["game_id"] == "g-test" for r in recs))
        h = recs[0]
        fp = code_fingerprint()
        self.assertEqual((h["seed"], h["rules_version"], h["code_hash"], h["code_files"], h["client"]),
                         (3, "0.3", fp["code_hash"], fp["code_files"], "MockLLM"))
        lim = game.cfg.limits
        self.assertEqual(h["conditions"], {"max_thinking_tokens": lim.max_thinking_tokens, "effort": lim.effort})
        self.assertEqual(h["argv_template"], build_argv("<model>", "<system>", "<prompt>", {}, effort=lim.effort)
                         [:-2] + ["<schema>", "<prompt>"])
        self.assertEqual(kinds(recs, "header"), [h])

        systems = kinds(recs, "system")
        self.assertEqual([s["player"] for s in systems], [p.name for p in game.players] + [None])
        for s in systems[:-1]:
            self.assertEqual(s["text"], game.system_prompts[s["player"]])
            self.assertEqual(s["model"], game.by_name[s["player"]].model)
        self.assertEqual((systems[-1]["text"], systems[-1]["model"]), (NARRATOR_SYSTEM, game.cfg.narrator.model))
        for s in systems:
            self.assertEqual(s["sha256"], hashlib.sha256(s["text"].encode()).hexdigest())

        schemas = {s["sha256"]: s["schema"] for s in kinds(recs, "schema")}
        self.assertEqual(len(schemas), len(kinds(recs, "schema")))          # once per distinct schema
        for sh, sc in schemas.items():
            self.assertEqual(sh, schema_sha256(sc))
        sys_shas = {s["sha256"] for s in systems}
        attempts = kinds(recs, "attempt")
        self.assertEqual([a["n"] for a in attempts], list(range(len(attempts))))
        for a in attempts:
            self.assertTrue(a["prompt"])
            self.assertTrue(a["stdout"])
            self.assertIn(a["system_sha256"], sys_shas)
            self.assertIn(a["schema_sha256"], schemas)
            self.assertLess(recs.index(next(s for s in kinds(recs, "schema") if s["sha256"] == a["schema_sha256"])),
                            recs.index(a))                                 # schema before first use

        ev = game.log.events
        turn_evs = [e for e in ev if e["type"] in ("turn", "recap")]
        self.assertEqual(len(attempts), sum(e["attempts"] for e in turn_evs))
        links = kinds(recs, "turn")
        by_seq = {}
        for t in links:
            self.assertNotIn(t["seq"], by_seq)
            by_seq[t["seq"]] = t
        self.assertEqual(set(by_seq), {e["seq"] for e in turn_evs})
        used = []
        for e in turn_evs:
            t = by_seq[e["seq"]]
            self.assertEqual(len(t["attempts"]), e["attempts"])
            self.assertEqual(t["fallback"], bool(e.get("fallback")) if e["type"] == "turn" else bool(e["error"]))
            for n in t["attempts"]:
                a = attempts[n]
                if e["type"] == "turn":
                    self.assertEqual((a["player"], a["phase"], a["round"]), (e["player"], e["turn_phase"], e["round"]))
                else:
                    self.assertEqual((a["player"], a["phase"]), (None, "recap"))
            self.assertEqual([attempts[n]["attempt"] for n in t["attempts"]], list(range(1, e["attempts"] + 1)))
            used += t["attempts"]
        self.assertEqual(sorted(used), list(range(len(attempts))))
        # The accepted reply of a turn is its last attempt (unless the turn fell back).
        for e in turn_evs:
            last = attempts[by_seq[e["seq"]]["attempts"][-1]]
            fell = e.get("fallback") if e["type"] == "turn" else bool(e["error"])
            self.assertEqual(last["accepted"], not fell)

    def test_prompts_are_what_the_mock_was_sent(self):
        with tempfile.TemporaryDirectory() as d:
            game = play(2, raw_dir=d)
            recs = records(game)
        sent = game.llm.calls
        attempts = kinds(recs, "attempt")
        self.assertEqual(sorted((c["prompt"], c["system"]) for c in sent),
                         sorted((a["prompt"], next(s["text"] for s in kinds(recs, "system")
                                                   if s["sha256"] == a["system_sha256"])) for a in attempts))
        schemas = {s["sha256"]: s["schema"] for s in kinds(recs, "schema")}
        self.assertEqual(sorted(schema_sha256(c["schema"]) for c in sent),
                         sorted(a["schema_sha256"] for a in attempts))
        for a in attempts:
            self.assertIn(a["schema_sha256"], schemas)
            self.assertEqual(a["stdout"], json.dumps(json.loads(a["stdout"])))   # the mock's JSON text


# --------------------------------------------------------------------------- 2-4. what the main log drops

def policy_of(fn):
    """A policy that applies `fn(prompt, schema, phase, player, data)` to a random valid reply."""
    rng = random.Random(7)

    def policy(model, system, prompt, schema, phase, player):
        if phase == "recap":
            return None
        return fn(prompt, schema, phase, player, random_valid(schema, rng))
    return policy


class Kept(unittest.TestCase):
    def test_rejected_text_is_kept(self):
        target = {}

        def fn(prompt, schema, phase, player, data):
            if phase == "discuss" and not target:
                target["player"] = player
            if phase == "discuss" and player == target["player"] and REJECT_MARK not in prompt \
                    and not target.get("done"):
                target["done"] = True
                bad = dict(data, confessional="MARKER rejected text " + "x " * 50)
                bad.pop("move")
                return bad
            return data
        with tempfile.TemporaryDirectory() as d:
            game = play(1, policy=policy_of(fn), raw_dir=d)
            recs = records(game)
        turn = next(e for e in game.log.events if e["type"] == "turn" and e["attempts"] == 2)
        self.assertEqual(turn["player"], target["player"])
        link = next(t for t in kinds(recs, "turn") if t["seq"] == turn["seq"])
        first, second = (kinds(recs, "attempt")[n] for n in link["attempts"])
        self.assertFalse(first["accepted"])
        self.assertEqual(first["error_kind"], "invalid")
        self.assertIsNone(first["error"])
        self.assertEqual(first["rejection"], turn["rejections"][0])
        self.assertIn("is missing 'move'", first["rejection"])
        self.assertIn("MARKER rejected text " + "x " * 50, json.loads(first["stdout"])["confessional"])
        self.assertTrue(second["accepted"])
        self.assertIsNone(second["rejection"])
        self.assertTrue(second["prompt"].endswith(f"\n\n{REJECT_MARK}{first['rejection']}. Reply again with valid JSON."))
        self.assertTrue(second["prompt"].startswith(first["prompt"]))
        self.assertNotIn(REJECT_MARK, first["prompt"])
        # Exactly what the mock was sent on the retry.
        self.assertIn(second["prompt"], [c["prompt"] for c in game.llm.calls])
        self.assertNotIn("MARKER", json.dumps(game.log.events))            # the main log never had it

    def test_pre_trim_text_is_kept(self):
        long_text = " ".join(f"word{i}" for i in range(300))

        def fn(prompt, schema, phase, player, data):
            if phase == "discuss":
                data["public"] = long_text
            return data
        with tempfile.TemporaryDirectory() as d:
            game = play(1, policy=policy_of(fn), raw_dir=d)
            recs = records(game)
        turn = next(e for e in game.log.events if e["type"] == "turn" and e["turn_phase"] == "discuss")
        self.assertTrue(turn["truncated"])
        self.assertIn("public", turn["truncated_fields"])
        self.assertLess(len(turn["public"]), len(long_text))
        link = next(t for t in kinds(recs, "turn") if t["seq"] == turn["seq"])
        a = kinds(recs, "attempt")[link["attempts"][-1]]
        self.assertTrue(a["accepted"])
        self.assertEqual(json.loads(a["stdout"])["public"], long_text)
        self.assertEqual(a["trimmed_fields"], turn["truncated_fields"])
        # Turns that were not trimmed say so.
        plain = next(e for e in game.log.events if e["type"] == "turn" and not e["truncated"])
        link = next(t for t in kinds(recs, "turn") if t["seq"] == plain["seq"])
        self.assertEqual(kinds(recs, "attempt")[link["attempts"][-1]]["trimmed_fields"], [])

    def test_failed_calls_and_fallbacks(self):
        victim = {}

        def policy(model, system, prompt, schema, phase, player):
            if phase == "vote" and "name" not in victim:
                victim["name"] = player
            if phase == "vote" and player == victim["name"]:
                return LLMReply(None, "", None, zero_usage(), 0.25, "exit 1: boom", "cli",
                                raw_stdout="partial output", stderr_tail="trace", returncode=1)
            if phase == "recap":
                return LLMReply(None, "", None, zero_usage(), 0.0, "exit 1: narrator down", "cli")
            return None
        with tempfile.TemporaryDirectory() as d:
            game = play(1, policy=policy, raw_dir=d)
            recs = records(game)
        attempts = kinds(recs, "attempt")
        turn = next(e for e in game.log.events if e["type"] == "turn" and e["turn_phase"] == "vote"
                    and e["player"] == victim["name"])
        self.assertTrue(turn["fallback"])
        self.assertEqual(turn["attempts"], game.cfg.limits.retries + 1)
        link = next(t for t in kinds(recs, "turn") if t["seq"] == turn["seq"])
        self.assertTrue(link["fallback"])
        for k, n in enumerate(link["attempts"], 1):
            a = attempts[n]
            self.assertEqual((a["accepted"], a["error"], a["error_kind"], a["rejection"], a["attempt"]),
                             (False, "exit 1: boom", "cli", "exit 1: boom", k))
            self.assertEqual((a["stdout"], a["stderr_tail"], a["returncode"], a["latency_s"]),
                             ("partial output", "trace", 1, 0.25))
            self.assertEqual(a["trimmed_fields"], [])
        self.assertTrue(attempts[link["attempts"][1]]["prompt"].endswith(
            f"{REJECT_MARK}exit 1: boom. Reply again with valid JSON."))
        recap = next(e for e in game.log.events if e["type"] == "recap")
        link = next(t for t in kinds(recs, "turn") if t["seq"] == recap["seq"])
        self.assertTrue(link["fallback"])
        a = attempts[link["attempts"][0]]
        self.assertEqual((a["accepted"], a["error"], a["phase"], a["player"]),
                         (False, "exit 1: narrator down", "recap", None))
        # Every non-fallback turn has fallback false.
        ok = next(e for e in game.log.events if e["type"] == "turn" and not e["fallback"])
        self.assertFalse(next(t for t in kinds(recs, "turn") if t["seq"] == ok["seq"])["fallback"])

    def test_blocked_attempts_are_recorded(self):
        block = "API Error: claude-x's safeguards flagged this message"

        def policy(model, system, prompt, schema, phase, player):
            if phase == "recap":
                return LLMReply(None, block, model, zero_usage(), 0.0, "is_error: " + block, "blocked")
            return None
        with tempfile.TemporaryDirectory() as d:
            game = play(1, policy=policy, raw_dir=d)
            recs = records(game)
        recap = next(e for e in game.log.events if e["type"] == "recap")
        self.assertEqual((recap["attempts"], recap["blocked"]), (2, 2))
        link = next(t for t in kinds(recs, "turn") if t["seq"] == recap["seq"])
        a1, a2 = (kinds(recs, "attempt")[n] for n in link["attempts"])
        self.assertEqual((a1["error_kind"], a2["error_kind"], a1["accepted"], a2["accepted"]),
                         ("blocked", "blocked", False, False))
        self.assertEqual(a1["prompt"], a2["prompt"])                         # unchanged on a block


# --------------------------------------------------------------------------- 5-6. nothing else changes

class NoChange(unittest.TestCase):
    def test_same_events_with_and_without(self):
        cfg = load_config(PILOT_TOML)
        for seed in (1, 2):
            plain = play(seed, cfg=cfg)
            with tempfile.TemporaryDirectory() as d:
                full = play(seed, cfg=cfg, raw_dir=d, provenance=code_fingerprint())
                raw_only = play(seed, cfg=cfg, raw_dir=Path(d) / "b")
            self.assertEqual(norm(plain.log.events, drop_stamp=False), norm(raw_only.log.events, drop_stamp=False))
            self.assertEqual(norm(plain.log.events), norm(full.log.events))
            self.assertNotIn("code_hash", plain.log.events[0])
            self.assertNotIn("code_hash", raw_only.log.events[0])
            start = full.log.events[0]
            self.assertEqual(start["code_hash"], code_fingerprint()["code_hash"])
            self.assertEqual(start["code_files"], code_fingerprint()["code_files"])
            # No turn or recap event gains a key.
            for a, b in zip(plain.log.events, full.log.events):
                if a["type"] != "game_start":
                    self.assertEqual(set(a), set(b), a["type"])
            # The same calls, in the same order with the same prompts.
            self.assertEqual([c["prompt"] for c in plain.llm.calls], [c["prompt"] for c in full.llm.calls])

    def test_players_never_see_the_stamp(self):
        plain = play(4)
        stamped = play(4, provenance=code_fingerprint())
        names = [p.name for p in plain.players]
        for e in stamped.log.events:
            for viewer in names + [None]:
                pr = project(e, viewer)
                self.assertNotIn("code_hash", json.dumps(pr), (e["type"], viewer))
        for viewer in names + [None]:
            a = visible_events(plain.log.events, viewer)
            b = visible_events(stamped.log.events, viewer)
            for x in a + b:
                x.pop("wall_s", None)
            self.assertEqual(a, b, viewer)
            self.assertNotIn("code_hash", json.dumps(b))
            self.assertNotIn("code_files", json.dumps(b))


# --------------------------------------------------------------------------- 7. files

class Files(unittest.TestCase):
    def test_paths(self):
        self.assertEqual(raw_path_for("/x/g-1-s1.jsonl"), Path("/x/g-1-s1.raw.jsonl"))
        self.assertEqual(raw_path_for("/x/g-1-s1.raw.jsonl"), Path("/x/g-1-s1.raw.jsonl"))
        self.assertEqual(raw_path_for("/x/g-1-s1.raw.jsonl.gz"), Path("/x/g-1-s1.raw.jsonl"))
        r = RawLog("/x/g-1-s1.jsonl")
        self.assertEqual((r.path.name, r.gz_path.name), ("g-1-s1.raw.jsonl", "g-1-s1.raw.jsonl.gz"))

    def test_close_and_read(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "g-a.jsonl"
            r = RawLog(log)
            r.write({"kind": "header", "game_id": "a", "n": 1})
            r.write({"kind": "attempt", "game_id": "a", "stdout": "é" * 10})
            plain = Path(d) / "g-a.raw.jsonl"
            self.assertTrue(plain.exists())
            self.assertEqual(len(read_raw(plain)), 2)                       # readable while open
            self.assertEqual(r.final_path, plain)
            r.close()
            r.close()                                                       # idempotent
            self.assertEqual(sorted(os.listdir(d)), ["g-a.raw.jsonl.gz"])
            self.assertEqual(r.final_path, Path(d) / "g-a.raw.jsonl.gz")
            recs = read_raw(r.gz_path)
            self.assertEqual(recs[1]["stdout"], "é" * 10)
            self.assertEqual(read_raw(log), recs)                           # given the game log path
            with self.assertRaises(OSError):
                r.write({"kind": "late"})
            # A torn last line, plain and gzipped.
            body = "\n".join(json.dumps(x) for x in recs) + '\n{"kind": "attem'
            plain.write_text(body, encoding="utf-8")
            self.assertEqual(read_raw(plain), recs)
            torn_gz = Path(d) / "g-b.raw.jsonl.gz"
            with gzip.open(torn_gz, "wt", encoding="utf-8") as f:
                f.write(body)
            self.assertEqual(read_raw(torn_gz), recs)
            # A gzip stream cut short (a crash while compressing) keeps what it can.
            whole = gzip.compress(("\n".join(json.dumps({"i": i, "pad": "z" * 200}) for i in range(500)) + "\n").encode())
            cut = Path(d) / "g-c.raw.jsonl.gz"
            cut.write_bytes(whole[: len(whole) // 2])
            got = read_raw(cut)
            self.assertEqual([x["i"] for x in got], list(range(len(got))))
            # A bad line in the middle is not a torn line.
            plain.write_text('{"a": 1}\nnot json\n{"b": 2}\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                read_raw(plain)

    def test_close_without_writes_leaves_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            r = RawLog(Path(d) / "g-x.jsonl")
            r.close()
            self.assertEqual(os.listdir(d), [])
            self.assertIsNone(r.final_path)

    def test_close_only_removes_its_own_file(self):
        with tempfile.TemporaryDirectory() as d:
            other = Path(d) / "g-x.raw.jsonl"
            other.write_text('{"kind": "header"}\n')
            RawLog(Path(d) / "g-x.jsonl").close()                           # never wrote: leaves it
            self.assertTrue(other.exists())

    def test_game_closes_the_raw_log_when_it_raises(self):
        class Boom(RuntimeError):
            pass

        def policy(model, system, prompt, schema, phase, player):
            if phase == "vote":
                raise Boom("engine bug")
            return None
        with tempfile.TemporaryDirectory() as d:
            raw = RawLog(Path(d) / "g-c.jsonl")
            game = Game(make_config(), MockLLM(1, policy=policy), 1, game_id="g-c", clock=fixed_clock, raw=raw)
            with self.assertRaises(Boom):
                game.run()
            self.assertEqual(os.listdir(d), ["g-c.raw.jsonl.gz"])
            recs = read_raw(raw.gz_path)
            self.assertEqual(recs[0]["kind"], "header")
            self.assertTrue(kinds(recs, "attempt"))

    def test_write_failure_does_not_stop_the_game(self):
        class Flaky(RawLog):
            failed = 0

            def write(self, record):
                if record["kind"] == "attempt" and record["n"] == 20 and not Flaky.failed:
                    Flaky.failed += 1
                    raise OSError(28, "No space left on device")
                super().write(record)

        plain = play(1)
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stderr(err):
            game = play(1, raw_dir=d, raw_cls=Flaky)
            recs = records(game)
        self.assertEqual(Flaky.failed, 1)
        self.assertEqual(err.getvalue().count("warning: raw log"), 1)
        self.assertIn("No space left", err.getvalue())
        self.assertEqual(norm(plain.log.events), norm(game.log.events))       # the game went on, unchanged
        self.assertEqual(game.result["winner"], plain.result["winner"])
        attempts = kinds(recs, "attempt")
        self.assertEqual([a["n"] for a in attempts], list(range(20)))        # nothing after the failure
        self.assertFalse([t for t in kinds(recs, "turn") if any(n >= 20 for n in t["attempts"])])

    def test_read_only_folder_does_not_stop_the_game(self):
        if os.geteuid() == 0:
            self.skipTest("root ignores folder permissions")
        plain = play(2)
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as d:
            ro = Path(d) / "ro"
            ro.mkdir()
            os.chmod(ro, 0o500)
            try:
                with contextlib.redirect_stderr(err):
                    game = play(2, raw_dir=ro)
            finally:
                os.chmod(ro, 0o700)
            self.assertEqual(os.listdir(ro), [])
            self.assertIsNone(game.raw.final_path)
        self.assertEqual(err.getvalue().count("warning: raw log"), 1)
        self.assertEqual(norm(plain.log.events), norm(game.log.events))


# --------------------------------------------------------------------------- 8. code fingerprint

class Fingerprint(unittest.TestCase):
    def test_stable_and_well_formed(self):
        a, b = code_fingerprint(), code_fingerprint()
        self.assertEqual(a, b)
        self.assertEqual(list(a["code_files"]), sorted(FINGERPRINT_FILES))
        self.assertEqual(set(FINGERPRINT_FILES), {"RULES.md"} | {f"inside_job/{m}.py" for m in (
            "__init__", "engine", "prompts", "schemas", "clues", "config", "llm", "log", "openrouter")})
        lines = "".join(f"{p} {a['code_files'][p]}\n" for p in sorted(a["code_files"]))
        self.assertEqual(a["code_hash"], hashlib.sha256(lines.encode()).hexdigest())
        for p, h in a["code_files"].items():
            self.assertEqual(h, hashlib.sha256((ROOT / p).read_bytes()).hexdigest(), p)
        a["code_files"]["RULES.md"] = "tampered"                            # the cache is not shared
        self.assertNotEqual(code_fingerprint()["code_files"]["RULES.md"], "tampered")

    def test_changes_with_a_file(self):
        with tempfile.TemporaryDirectory() as d:
            for rel in FINGERPRINT_FILES:
                (Path(d) / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(ROOT / rel, Path(d) / rel)
            base = code_fingerprint(d)
            self.assertEqual(base, code_fingerprint())
            with open(Path(d) / "inside_job" / "prompts.py", "a") as f:
                f.write("\n# changed\n")
            changed = code_fingerprint(d)
            self.assertNotEqual(changed["code_hash"], base["code_hash"])
            self.assertEqual([p for p in base["code_files"] if base["code_files"][p] != changed["code_files"][p]],
                             ["inside_job/prompts.py"])
            os.remove(Path(d) / "RULES.md")
            gone = code_fingerprint(d)
            self.assertEqual(gone["code_files"]["RULES.md"], "missing")
            self.assertNotEqual(gone["code_hash"], changed["code_hash"])

    def test_fingerprint_command(self):
        rc, out, _ = run_cli(["fingerprint"])
        self.assertEqual(rc, 0)
        fp = code_fingerprint()
        self.assertIn(fp["code_hash"], out)
        for p, h in fp["code_files"].items():
            self.assertIn(f"{h}  {p}", out)
        with tempfile.TemporaryDirectory() as d:
            rc, *_ = run_cli(["run", "--config", str(PILOT_TOML), "--seed", "3", "--mock", "--out", d, "--no-raw"])
            self.assertEqual(rc, 0)
            log = read_index(Path(d) / "index.jsonl")[0]["log"]
            rc, out, _ = run_cli(["fingerprint", "--check", log])
            self.assertEqual(rc, 0, out)
            events = read_log(log)
            events[0]["code_hash"] = "0" * 64
            events[0]["code_files"]["inside_job/engine.py"] = "0" * 64
            other = Path(d) / "other.jsonl"
            other.write_text("".join(json.dumps(e) + "\n" for e in events))
            rc, out, _ = run_cli(["fingerprint", "--check", str(other)])
            self.assertEqual(rc, 1, out)
            self.assertIn("differs: inside_job/engine.py", out)
            unstamped = Path(d) / "old.jsonl"
            g = play(3)
            unstamped.write_text("".join(json.dumps(e) + "\n" for e in g.log.events))
            rc, out, _ = run_cli(["fingerprint", "--check", str(unstamped)])
            self.assertEqual(rc, 2, out)
            rc, *_ = run_cli(["fingerprint", "--check", str(Path(d) / "nope.jsonl")])
            self.assertEqual(rc, 2)


# --------------------------------------------------------------------------- 9. commands

class Commands(unittest.TestCase):
    def test_run_writes_the_raw_file_and_index_fields(self):
        with tempfile.TemporaryDirectory() as d:
            rc, out, err = run_cli(["run", "--config", str(PILOT_TOML), "--seed", "1", "--mock", "--out", d])
            self.assertEqual(rc, 0, err)
            row = read_index(Path(d) / "index.jsonl")[0]
            gz = Path(row["log"]).with_name(Path(row["log"]).stem + ".raw.jsonl.gz")
            self.assertEqual(row["raw"], str(gz))
            self.assertTrue(gz.exists())
            self.assertFalse(list(Path(d).glob("*.raw.jsonl")))
            self.assertEqual(row["code_hash"], code_fingerprint()["code_hash"])
            self.assertEqual(read_log(row["log"])[0]["code_hash"], row["code_hash"])
            recs = read_raw(gz)
            self.assertEqual((recs[0]["kind"], recs[0]["game_id"], recs[0]["code_hash"]),
                             ("header", row["game_id"], row["code_hash"]))
            self.assertIn(f"raw: {gz}", out)
            # --no-raw: no raw file, `raw` null, still stamped.
            rc, *_ = run_cli(["run", "--config", str(PILOT_TOML), "--seed", "2", "--mock", "--out", d, "--no-raw"])
            self.assertEqual(rc, 0)
            row = read_index(Path(d) / "index.jsonl")[1]
            self.assertIsNone(row["raw"])
            self.assertEqual(row["code_hash"], code_fingerprint()["code_hash"])
            self.assertEqual(len(list(Path(d).glob("*.raw.*"))), 1)

    def test_trial_writes_the_raw_file(self):
        with tempfile.TemporaryDirectory() as d:
            rc, out, err = run_cli(["trial", "--kind", "mole", "--test", "claude-a", "--reference", "claude-b",
                                    "--seed", "1", "--mock", "--out", d])
            self.assertEqual(rc, 0, err)
            row = read_index(Path(d) / "index.jsonl")[0]
            self.assertTrue(Path(row["raw"]).exists())
            self.assertEqual(row["code_hash"], code_fingerprint()["code_hash"])

    def test_batch_writes_one_raw_file_per_game(self):
        argv = ["batch", "--config", str(PILOT_TOML), "--name", "rb", "--games", "3", "--seed", "1",
                "--parallel-games", "2", "--mock"]
        with tempfile.TemporaryDirectory() as d:
            rc, out, err = run_cli(argv + ["--out", d])
            self.assertEqual(rc, 0, out + err)
            rows = read_index(Path(d) / "index.jsonl")
            self.assertEqual(len(rows), 3)
            self.assertEqual(len(list(Path(d).glob("*.raw.jsonl.gz"))), 3)
            self.assertFalse(list(Path(d).glob("*.raw.jsonl")))
            for r in rows:
                recs = read_raw(r["raw"])
                self.assertEqual(recs[0]["game_id"], r["game_id"])
                self.assertEqual(recs[0]["seed"], r["seed"])
                self.assertEqual(r["code_hash"], code_fingerprint()["code_hash"])
                events = read_log(r["log"])
                self.assertEqual(len(kinds(recs, "attempt")),
                                 sum(e["attempts"] for e in events if e["type"] in ("turn", "recap")))
            # The report still reads only the logs.
            rc, out, err = run_cli(["report", "--batch", "rb", "--out", d])
            self.assertEqual(rc, 0, err)
        with tempfile.TemporaryDirectory() as d:
            rc, *_ = run_cli(argv + ["--out", d, "--no-raw"])
            self.assertEqual(rc, 0)
            self.assertFalse(list(Path(d).glob("*.raw.*")))
            self.assertEqual([r["raw"] for r in read_index(Path(d) / "index.jsonl")], [None] * 3)

    def test_bots_never_write_raw_files(self):
        with tempfile.TemporaryDirectory() as d:
            rc, *_ = run_cli(["bots", "--config", str(PILOT_TOML), "--games", "3", "--out", d])
            self.assertEqual(rc, 0)
            self.assertFalse([p for p in os.listdir(d) if ".raw." in p])

    def test_newest_log_skips_raw_files(self):
        from inside_job.live import newest_log
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "g-1-s1.jsonl").write_text("{}\n")
            os.utime(Path(d) / "g-1-s1.jsonl", (1, 1))
            (Path(d) / "g-1-s1.raw.jsonl").write_text("{}\n")
            self.assertEqual(newest_log(d, wait=False).name, "g-1-s1.jsonl")


# --------------------------------------------------------------------------- the client's raw fields

class ClientFields(unittest.TestCase):
    def test_parse_cli_output_keeps_everything(self):
        long_err = "E" * 5000
        out = json.dumps({"is_error": True, "result": "x" * 1000, "subtype": "boom", "errors": [long_err]})
        r = parse_cli_output(out, 1, "s" * 3000 + "TAIL")
        self.assertEqual(r.raw_stdout, out)                                 # untruncated
        self.assertEqual(len(r.stderr_tail), 2000)
        self.assertTrue(r.stderr_tail.endswith("TAIL"))
        self.assertEqual(r.returncode, 1)
        self.assertLess(len(r.error), 700)                                  # the main log's cut is unchanged
        r = parse_cli_output("garbage", 2, "")
        self.assertEqual((r.raw_stdout, r.returncode, r.error_kind), ("garbage", 2, "cli"))

    def test_defaults_keep_old_constructors(self):
        r = LLMReply(None, "", None, zero_usage(), 0.0, "e", "cli")
        self.assertEqual((r.raw_stdout, r.stderr_tail, r.returncode), ("", "", None))

    def test_cli_call_fills_and_timeout_stays_empty(self):
        class Proc:
            def __init__(self, hang):
                self.hang, self.returncode = hang, 0

            async def communicate(self):
                if self.hang:
                    await asyncio.sleep(30)
                return b'{"is_error": false, "structured_output": {"a": 1}}', b"warn"

            def kill(self):
                pass

            async def wait(self):
                return 0

        def exec_for(hang):
            async def fake(*argv, **kw):
                return Proc(hang)
            return fake
        c = ClaudeCLI(timeout_s=5, exec_fn=exec_for(False))
        r = asyncio.run(c.call(model="m", system="s", prompt="p", schema={}))
        self.assertEqual((r.raw_stdout, r.stderr_tail, r.returncode, r.data),
                         ('{"is_error": false, "structured_output": {"a": 1}}', "warn", 0, {"a": 1}))
        c = ClaudeCLI(timeout_s=0.05, exec_fn=exec_for(True))
        r = asyncio.run(c.call(model="m", system="s", prompt="p", schema={}))
        self.assertEqual((r.raw_stdout, r.stderr_tail, r.returncode, r.error_kind), ("", "", None, "timeout"))
        self.assertIn("timeout", r.error)


if __name__ == "__main__":
    unittest.main()
