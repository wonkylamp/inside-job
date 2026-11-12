"""Live watch: both views render every ending, the table view keeps secrets, following a growing
file prints every event once and stops at game_end, and the log writer flushes per event."""

import io
import json
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path

from inside_job.config import display_name
from inside_job.live import Renderer, follow, newest_log, watch
from inside_job.log import GameLog

from helpers import make_config, run_game
from test_privacy import TOKEN, Planter
from test_transcript_cli import ending_games

FAMILY = re.compile(r"haiku|sonnet|opus|fable|claude", re.IGNORECASE)


def render_all(events, view, color=False):
    out = io.StringIO()
    r = Renderer(view, color=color, width=100, out=out)
    for e in events:
        r.feed(e)
    return out.getvalue()


class Views(unittest.TestCase):
    def test_every_ending_both_views(self):
        for label, (cfg, script) in ending_games().items():
            game, _ = run_game(11, cfg, policy=script)
            ev = game.log.events
            types = {e["type"] for e in ev}
            for view in ("audience", "table"):
                for color in (False, True):
                    text = render_all(ev, view, color)
                    self.assertIn("WIN (", text, (label, view))
                    if not color:
                        self.assertNotIn("\033[", text)
                    else:
                        self.assertIn("\033[", text)
            aud = render_all(ev, "audience")
            for p in game.players:
                self.assertIn(p.name, aud)
            self.assertIn("SCORE", aud)
            self.assertIn("VOTE RESULT", aud) if "vote_result" in types else None
            self.assertIn("┆ private:", aud)
            self.assertIn("calls:", aud)                  # token report at the end
            self.assertIn("thinking cap:", aud)

    def test_audience_marks_and_labels(self):
        from helpers import Script, job_choice, pick_with_mole, suspicion_for

        def discuss(s, player, schema, prompt):
            others = schema["properties"]["move"]["properties"]["accuse"]["enum"]
            cards = [{"kind": "not_mole", "players": [others[0]], "k": 0}]
            return {"accuse": others[0], "challenges": [], "clue_cards": cards,
                    "job_claim": "helped" if player in s.game.team else "none", "suspicion": suspicion_for(schema)}
        s = Script(2, discuss=discuss, job=job_choice("sabotage"), pick=pick_with_mole)
        game, _ = run_game(2, make_config(clean_target=9, sabotage_target=9, anonymise=True), policy=s)
        aud = render_all(game.log.events, "audience")
        self.assertIn("CLUE CARD (FAKE)", aud)
        self.assertIn("JOB CLAIM (FALSE)", aud)
        self.assertIn("LIE:", aud)
        self.assertIn("top suspect:", aud)
        self.assertIn("thinks the table suspects:", aud)
        self.assertIn("[MOLE]", aud)
        self.assertIn("Intel went to", aud)
        for p in game.players:
            self.assertIn(f"{p.name} ({p.model_name})", aud)   # the audience sees the model

    def test_table_view_keeps_every_secret(self):
        for seed in range(4):
            for anonymise in (True, False):
                planter = Planter(seed)
                cfg = make_config(anonymise=anonymise)
                game, llm = run_game(seed, cfg, policy=planter)
                ev = game.log.events
                text = render_all(ev, "table")
                moles = set(ev[0]["moles"])
                for t in TOKEN.findall(text):
                    info = planter.tokens[t]
                    self.assertEqual(info["field"], "public", info)
                    self.assertNotIn(info["phase"], ("whisper", "clue", "job", "cut_vote", "finale_choice"))
                for word in ("private", "LIE", "CLUE CARD", "JOB CLAIM", "suspect", "[MOLE]", "[crew]",
                             "Intel went", "no intel", "SABOTAGE", "choices:", "FALLBACK", "thinking cap"):
                    self.assertNotIn(word, text, word)
                if anonymise:
                    self.assertIsNone(FAMILY.search(text), FAMILY.search(text))
                    for p in game.players:
                        self.assertNotIn(p.model_name, text)
                # Roles appear only for revealed players.
                revealed = {e["eliminated"] for e in ev if e["type"] == "vote_result"}
                for m in moles - revealed:
                    self.assertNotRegex(text, rf"{m}\W+is out, revealed")

    def test_table_view_holds_votes_until_result(self):
        game, _ = run_game(3, make_config())
        out = io.StringIO()
        r = Renderer("table", width=100, out=out)
        for e in game.log.events:
            before = out.getvalue()
            r.feed(e)
            if e["type"] == "turn" and e["turn_phase"] == "vote":
                self.assertEqual(out.getvalue(), before)
            if e["type"] == "vote_result":
                self.assertIn(" votes ", out.getvalue()[len(before):])

    def test_pace(self):
        game, _ = run_game(3, make_config())
        slept = []
        r = Renderer("audience", out=io.StringIO(), pace=2.0, sleep=slept.append)
        for e in game.log.events[:60]:
            r.feed(e)
        self.assertTrue(slept)
        self.assertTrue(all(0 < s <= 2.0 for s in slept))


class CommandLine(unittest.TestCase):
    def test_run_watch_and_watch_command(self):
        import contextlib
        from inside_job import __main__ as cli
        from helpers import DEFAULT_TOML
        with tempfile.TemporaryDirectory() as d:
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = cli.main(["run", "--config", str(DEFAULT_TOML), "--seed", "3", "--mock", "--out", d,
                               "--watch", "--no-color"])
            self.assertEqual(rc, 0)
            self.assertIn("ROUND 1", out.getvalue())
            self.assertIn("THE CAST", out.getvalue())
            self.assertNotIn("R1 discuss", err.getvalue())          # no progress lines when watching
            self.assertEqual(out.getvalue().count("calls:"), 1)     # token report printed once
            for view in ("table", "audience"):
                o = io.StringIO()
                with contextlib.redirect_stdout(o):
                    self.assertEqual(cli.main(["watch", "--latest", "--out", d, "--view", view, "--no-color"]), 0)
                self.assertIn("WIN (", o.getvalue())
                self.assertNotIn("\033[", o.getvalue())
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rc = cli.main(["trial", "--kind", "mole", "--test", "claude-haiku-5-5", "--reference",
                               "claude-haiku-4-5", "--seed", "2", "--mock", "--out", d, "--watch", "--view", "table"])
            self.assertEqual(rc, 0)


class Following(unittest.TestCase):
    def test_follow_a_file_another_thread_appends_to(self):
        game, _ = run_game(5, make_config())
        lines = [json.dumps(e) for e in game.log.events]
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "g.jsonl"
            path.write_text("")

            def writer():
                with open(path, "a") as f:
                    for i, line in enumerate(lines):
                        if i % 7 == 3:                     # a line written in two halves
                            f.write(line[:10])
                            f.flush()
                            time.sleep(0.002)
                            f.write(line[10:] + "\n")
                        else:
                            f.write(line + "\n")
                        f.flush()
                        if i % 25 == 0:
                            time.sleep(0.01)
                    f.write(json.dumps({"type": "after_end"}) + "\n")
            th = threading.Thread(target=writer)
            th.start()
            got = []
            n = follow(path, got.append, poll=0.005, timeout=10)
            th.join()
            self.assertEqual(n, len(lines))
            self.assertEqual([e["seq"] for e in got], [e["seq"] for e in game.log.events])   # each once, in order
            self.assertEqual(got[-1]["type"], "game_end")

    def test_watch_replays_finished_game_and_latest(self):
        with tempfile.TemporaryDirectory() as d:
            game, _ = run_game(6, make_config(), log_path=Path(d) / "g-1.jsonl")
            self.assertEqual(newest_log(d, wait=False), Path(d) / "g-1.jsonl")
            out = io.StringIO()
            watch(Path(d) / "g-1.jsonl", Renderer("audience", out=out, width=100))
            self.assertEqual(out.getvalue(), render_all(game.log.events, "audience"))

    def test_log_writer_flushes_per_event(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "g.jsonl"
            log = GameLog("g", path, clock=lambda: "t")
            for i in range(5):
                log.write(round=0, phase="setup", type="x", vis="public", i=i)
                with open(path) as f:                     # another reader sees it at once
                    self.assertEqual(len(f.read().splitlines()), i + 1)
            log.close()


if __name__ == "__main__":
    unittest.main()
