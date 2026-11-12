"""Scripted bots: complete valid games, see only their own view, deterministic, never-moles lose."""

import contextlib
import io
import unittest

from inside_job import __main__ as cli
from inside_job.bots import BotLLM, cell_stats, game_summary, play_bot_game, wilson
from inside_job.engine import Game
from inside_job.log import project, visible_to

from helpers import DEFAULT_TOML, make_config


def audited_game(test, cfg, seed, **kw):
    """Play a bot game asserting, before every bot turn, that each event the bot was handed is
    one `visible_to` allows that player, projected exactly as `project` gives it."""
    holder = {}
    checked = {"n": 0}

    def audit(player, view):
        events = holder["game"].log.events
        by_seq = {e["seq"]: e for e in events}
        allowed = [project(e, player) for e in events if visible_to(e, player)]
        test.assertEqual(view, [a for a in allowed if a is not None])
        for v in view:
            orig = by_seq[v["seq"]]
            test.assertTrue(visible_to(orig, player))
            test.assertNotEqual(orig["type"], "clue_deal")
            test.assertNotIn("checks", v)
            test.assertNotIn("blocked", v)
        checked["n"] += 1
    llm = BotLLM(cfg, seed, audit=audit, **kw)
    game = Game(cfg, llm, seed, game_id="b")
    holder["game"] = game
    game.run()
    test.assertGreater(checked["n"], 0)
    return game, llm


class Bots(unittest.TestCase):
    def test_every_type_completes_valid_games_without_fallbacks(self):
        cfg = make_config()
        for moles in ("always", "never", "smart"):
            for cards in ("decoy", "none"):
                for seed in range(50 if cards == "decoy" else 10):
                    events = play_bot_game(cfg, seed, moles=moles, mole_cards=cards)
                    end = events[-1]
                    self.assertEqual(end["type"], "game_end")
                    self.assertEqual(end["fallbacks"], 0, (moles, cards, seed))
                    for t in (e for e in events if e["type"] == "turn"):
                        self.assertEqual(t["attempts"], 1, t)

    def test_bots_see_only_their_view_and_no_prompts(self):
        cfg = make_config()
        for seed in range(4):
            game, llm = audited_game(self, cfg, seed)
            self.assertGreater(llm.calls, 50)
        # Real-model prompts are unaffected: the engine builds none for bots.
        self.assertEqual(game.system_prompts[game.players[0].name], "")

    def test_never_moles_lose(self):
        rows = [game_summary(play_bot_game(make_config(), s, moles="never")) for s in range(100)]
        st = cell_stats(rows)
        self.assertLess(1 - st["crew_win"], 0.15)
        self.assertEqual(st["sabotage_rate"], 0.0)

    def test_always_moles_always_sabotage_and_smart_never_double(self):
        rows = [game_summary(play_bot_game(make_config(), s, moles="always")) for s in range(30)]
        self.assertEqual(cell_stats(rows)["sabotage_rate"], 1.0)
        for s in range(30):
            ev = play_bot_game(make_config(), s, moles="smart")
            for e in ev:
                if e["type"] == "job_result":
                    self.assertLessEqual(e["sabotages"], 1)

    def test_decoy_cards_are_fake_and_tagged_false(self):
        n = 0
        for s in range(20):
            ev = play_bot_game(make_config(), s, moles="smart", mole_cards="decoy")
            moles = set(ev[0]["moles"])
            for t in ev:
                if t["type"] == "turn" and t["turn_phase"] == "discuss" and t["player"] in moles:
                    for c in t["checks"]["clue_cards"]:
                        n += 1
                        self.assertFalse(c["held"])
                        self.assertTrue(any(not cl["truthful"] and c["text"] in cl["text"] for cl in t["claims"]))
                if t["type"] == "turn" and t["turn_phase"] == "discuss" and t["player"] not in moles:
                    self.assertTrue(all(c["held"] for c in t["checks"]["clue_cards"]))   # logician: real only
        self.assertGreater(n, 0)

    def test_identical_seeds_identical_results(self):
        cfg = make_config()
        strip = lambda ev: [{k: v for k, v in e.items() if k not in ("wall_s",)} for e in ev]
        for s in (1, 7):
            self.assertEqual(strip(play_bot_game(cfg, s)), strip(play_bot_game(cfg, s)))
        self.assertNotEqual(strip(play_bot_game(cfg, 1)), strip(play_bot_game(cfg, 2)))

    def test_wilson(self):
        lo, hi = wilson(50, 100)
        self.assertAlmostEqual(lo, 0.4038, places=3)
        self.assertAlmostEqual(hi, 0.5962, places=3)
        self.assertEqual(wilson(0, 0), (0.0, 0.0))

    def test_cli_sweep_prints_one_row_per_cell_and_writes_nothing(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            cwd = os.getcwd()
            os.chdir(d)
            try:
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = cli.main(["bots", "--games", "6", "--config", str(DEFAULT_TOML),
                                   "--sweep", "clue_recipients=2,3", "--sweep", "clue_strength=weak,normal",
                                   "--set", "whisper_pairs_max=2"])
                self.assertEqual(rc, 0)
                self.assertEqual(os.listdir(d), [])
            finally:
                os.chdir(cwd)
        text = out.getvalue()
        rows = [l for l in text.splitlines() if l.startswith("clue_recipients=")]
        self.assertEqual(len(rows), 4)
        self.assertIn("games/s", text)
        with tempfile.TemporaryDirectory() as d:
            with contextlib.redirect_stdout(io.StringIO()):
                cli.main(["bots", "--games", "3", "--config", str(DEFAULT_TOML), "--out", d])
            self.assertEqual(sorted(os.listdir(d)), ["bots-cells.jsonl", "bots-games.jsonl"])


if __name__ == "__main__":
    unittest.main()
