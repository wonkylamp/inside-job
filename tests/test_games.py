"""Full mock games: they finish, the log is well-formed, the engine is deterministic."""

import json
import tempfile
import time
import unittest
from pathlib import Path

from inside_job.engine import Game
from inside_job.llm import MockLLM

from helpers import events_of, make_config, run_game, turns

WINNERS = {"jobs_clean": "crew", "moles_out": "crew", "sabotage": "moles", "final_two": "moles", "clock": "moles"}


def check_game(tc: unittest.TestCase, events: list[dict], cfg):
    tc.assertEqual([e["seq"] for e in events], list(range(len(events))))
    start = events[0]
    tc.assertEqual(start["type"], "game_start")
    end = events[-1]
    tc.assertEqual(end["type"], "game_end")
    tc.assertIn(end["reason"], WINNERS)
    tc.assertEqual(end["winner"], WINNERS[end["reason"]])
    names = [p["name"] for p in start["players"]]
    tc.assertEqual(set(end["payouts"]), set(names))
    tc.assertLessEqual(sum(end["payouts"].values()), cfg.game.pot)
    g = cfg.game
    if end["reason"] == "sabotage":
        tc.assertGreaterEqual(end["blown_jobs"], g.sabotage_target)
    if end["reason"] == "jobs_clean":
        tc.assertGreaterEqual(end["clean_jobs"], g.clean_target)
    roles = {p["name"]: p["role"] for p in start["players"]}
    side = "crew" if end["winner"] == "crew" else "mole"
    # Finalists, and anyone paid, come from the winning side.
    fin = events_of(events, "finale_result")
    for f in fin:
        tc.assertTrue(all(roles[n] == side for n in f["finalists"]), f)
    for n, v in end["payouts"].items():
        if v:
            tc.assertEqual(roles[n], side)
    # Team sizes follow the number alive.
    alive_at = {e["round"]: len(e["alive"]) for e in events_of(events, "round_start")}
    for p in events_of(events, "job_pick"):
        a = alive_at[p["round"]]
        want = min(g.job_size if a >= 5 else g.job_size_small, a)
        tc.assertEqual(len(p["team"]), want)
        tc.assertEqual(len(set(p["team"])), want)
    for wp in events_of(events, "whisper_pairs"):
        a = alive_at[wp["round"]]
        tc.assertLessEqual(len(wp["pairs"]), min(g.whisper_pairs_max, a // 2))
        flat = [x for pair in wp["pairs"] for x in pair]
        tc.assertEqual(len(flat), len(set(flat)))
    # Suspicion covers every other alive player.
    for t in turns(events):
        if t["turn_phase"] in ("clue", "vote"):
            a = set(next(e["alive"] for e in events_of(events, "round_start") if e["round"] == t["round"]))
            tc.assertEqual(set(t["action"]["suspicion"]), a - {t["player"]})
            tc.assertEqual(t["suspicion_kind"], "table_read" if roles[t["player"]] == "mole" else "belief")
    # A job that hits a target ends the game before that round's discussion.
    if end["reason"] in ("sabotage", "jobs_clean"):
        tc.assertEqual(turns(events, "discuss", end["rounds"]), [])
        tc.assertEqual(turns(events, "vote", end["rounds"]), [])


class FullGames(unittest.TestCase):
    def test_200_seeds_finish_with_valid_logs(self):
        cfg = make_config()
        reasons = set()
        with tempfile.TemporaryDirectory() as d:
            for seed in range(200):
                path = Path(d) / f"g{seed}.jsonl"
                game, _ = run_game(seed, cfg, log_path=path)
                with open(path) as f:
                    lines = f.read().splitlines()
                events = [json.loads(line) for line in lines]          # every line valid JSON
                self.assertEqual(events, json.loads(json.dumps(game.log.events)))
                check_game(self, events, cfg)
                self.assertEqual(events[-1]["fallbacks"], 0)
                reasons.add(events[-1]["reason"])
        self.assertTrue({"jobs_clean", "sabotage", "moles_out"} <= reasons, reasons)

    def test_anonymised_and_variant_settings_finish(self):
        variants = [
            make_config(anonymise=True),
            make_config(whispers=False),
            make_config(clean_target=9, sabotage_target=9),
            make_config(max_rounds=2, clean_target=9, sabotage_target=9),
            make_config(discussion_passes=1, finale_exchanges=2, clues_per_round=2, clue_strength="strong"),
            make_config(players=[{"model": "claude-haiku-4-5"}] * 5, num_moles=2),
            make_config(players=[{"model": "claude-haiku-4-5"}] * 9, num_moles=3, whisper_pairs_max=4),
        ]
        for i, cfg in enumerate(variants):
            for seed in range(25):
                game, _ = run_game(seed, cfg)
                check_game(self, game.log.events, cfg)

    def test_mock_game_is_fast(self):
        t0 = time.monotonic()
        run_game(7, make_config())
        self.assertLess(time.monotonic() - t0, 1.0)

    def test_same_seed_same_log_apart_from_timestamps(self):
        def strip(events):
            out = []
            for e in events:
                e = {k: v for k, v in e.items() if k not in ("ts", "game_id", "wall_s")}
                out.append(e)
            return out
        cfg = make_config()
        for seed in (3, 11):
            a = Game(cfg, MockLLM(seed), seed, game_id="g-a")
            a.run()
            time.sleep(0.002)
            b = Game(cfg, MockLLM(seed), seed, game_id="g-b")
            b.run()
            self.assertEqual(strip(a.log.events), strip(b.log.events))
        x, _ = run_game(1)
        y, _ = run_game(2)
        self.assertNotEqual(strip(x.log.events), strip(y.log.events))

    def test_round_start_and_job_result_carry_score(self):
        game, _ = run_game(5)
        for e in events_of(game.log.events, "round_start"):
            self.assertIn("clean_jobs", e)
            self.assertIn("blown_jobs", e)
        for e in events_of(game.log.events, "job_result"):
            self.assertEqual(e["blown"], e["sabotages"] >= 1)
            self.assertIn("clean_jobs", e)


class TeamSize(unittest.TestCase):
    def test_team_size_by_alive_count(self):
        cfg = make_config()
        game = Game(cfg, MockLLM(0), 0, game_id="g")
        game.setup()
        self.assertEqual(game.team_size(), 3)                  # 7 alive
        game.players[0].eliminated_round = 1
        game.players[1].eliminated_round = 1
        self.assertEqual(game.team_size(), 3)                  # 5 alive
        game.players[2].eliminated_round = 2
        self.assertEqual(game.team_size(), 2)                  # 4 alive
        game.players[3].eliminated_round = 3
        game.players[4].eliminated_round = 3
        self.assertEqual(game.team_size(), 2)                  # 2 alive

    def test_small_teams_in_long_games(self):
        cfg = make_config(clean_target=9, sabotage_target=9)
        seen_small = False
        for seed in range(10):
            game, _ = run_game(seed, cfg)
            alive_at = {e["round"]: len(e["alive"]) for e in events_of(game.log.events, "round_start")}
            for p in events_of(game.log.events, "job_pick"):
                if alive_at[p["round"]] <= 4:
                    self.assertEqual(len(p["team"]), 2)
                    seen_small = True
                else:
                    self.assertEqual(len(p["team"]), 3)
        self.assertTrue(seen_small)


if __name__ == "__main__":
    unittest.main()
