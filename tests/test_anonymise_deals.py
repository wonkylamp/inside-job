"""Anonymised mode, deals (seed streams) and benchmark trials."""

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from inside_job import __main__ as cli
from inside_job.config import CODENAMES, config_from_dict, display_name, load_raw, trial_config
from inside_job.log import read_log

from helpers import BENCH_TOML, events_of, make_config, raw_default, run_game

FAMILY = re.compile(r"haiku|sonnet|opus|fable|claude", re.IGNORECASE)


class Anonymised(unittest.TestCase):
    def test_no_model_names_in_any_prompt(self):
        cfg = make_config(anonymise=True)
        forbidden = {p.model for p in cfg.players} | {p.name for p in cfg.players} | \
                    {display_name(p.model) for p in cfg.players}
        for seed in range(15):
            game, llm = run_game(seed, cfg)
            self.assertTrue(llm.calls)
            for c in llm.calls:
                text = c["system"] + "\n" + c["prompt"] + "\n" + json.dumps(c["schema"])
                self.assertIsNone(FAMILY.search(text), FAMILY.search(text) and (c["phase"], FAMILY.search(text).group(0)))
                for f in forbidden:
                    self.assertNotIn(f, text)
            for c in llm.calls:
                if c["player"]:
                    self.assertIn("heist codename", c["system"])
            names = [p.name for p in game.players]
            self.assertEqual(len(set(names)), len(names))
            self.assertTrue(set(names) <= set(CODENAMES))
            start = game.log.events[0]
            self.assertTrue(start["anonymised"])
            for p in start["players"]:
                self.assertIn(p["name"], CODENAMES)
                self.assertTrue(p["model"].startswith("claude-"))
                self.assertEqual(p["model_name"], next(pc.name for pc in cfg.players if pc.model == p["model"]
                                                       and pc.name == p["model_name"]))

    def test_same_seed_same_codenames(self):
        cfg = make_config(anonymise=True)
        a, _ = run_game(21, cfg)
        b, _ = run_game(21, cfg)
        c, _ = run_game(22, cfg)
        self.assertEqual([p.name for p in a.players], [p.name for p in b.players])
        self.assertNotEqual([p.name for p in a.players], [p.name for p in c.players])

    def test_real_names_when_not_anonymised(self):
        game, _ = run_game(3, make_config(anonymise=False))
        start = game.log.events[0]
        self.assertFalse(start["anonymised"])
        for p in start["players"]:
            self.assertEqual(p["name"], p["model_name"])
        self.assertIsNone(start["trial"])


def round1_clues_by_seat(game):
    seat = {p.name: p.seat for p in game.players}
    out = {}
    for e in events_of(game.log.events, "clue"):
        if e["round"] == 1:
            c = e["clue"]
            out[seat[e["player"]]] = (c["kind"], tuple(seat[n] for n in c["players"]), c.get("k"))
    return out


class Deals(unittest.TestCase):
    def casts(self):
        base = raw_default()["players"]
        other = [{"model": m} for m in ("claude-opus-5-5", "claude-fable-5", "claude-sonnet-5", "claude-haiku-4-5",
                                       "claude-sonnet-4-6", "claude-haiku-5-5", "claude-opus-4-1")]
        same = [{"model": "claude-haiku-4-5"}] * 7
        return [base, other, same]

    def test_same_seed_same_deal_whatever_the_cast(self):
        for anonymise in (False, True):
            for seed in range(10):
                games = [run_game(seed, make_config(players=p, anonymise=anonymise))[0] for p in self.casts()]
                starts = [g.log.events[0] for g in games]
                self.assertEqual(len({tuple(s["mole_seats"]) for s in starts}), 1)
                self.assertEqual(len({next(p["seat"] for p in s["players"] if p["name"] == s["first_leader"])
                                      for s in starts}), 1)
                self.assertEqual(len({json.dumps(round1_clues_by_seat(g), sort_keys=True) for g in games}), 1)
                self.assertEqual(len({tuple(e["job_name"] for e in events_of(g.log.events, "job_pick"))[:1]
                                      for g in games}), 1)
                if anonymise:
                    self.assertEqual(len({tuple(p["name"] for p in s["players"]) for s in starts}), 1)
                    texts = [sorted(e["clue"]["text"] for e in events_of(g.log.events, "clue") if e["round"] == 1)
                             for g in games]
                    self.assertTrue(all(t == texts[0] for t in texts))
                for s in starts:
                    self.assertEqual(sorted(p["seat"] for p in s["players"] if p["role"] == "mole"), s["mole_seats"])

    def test_cast_shuffle_changes_seating_not_deal(self):
        a, _ = run_game(5, make_config())
        b, _ = run_game(6, make_config())
        self.assertNotEqual([p.model_name for p in a.players], [p.model_name for p in b.players])

    def test_fixed_roles_fill_mole_and_crew_seats_in_config_order(self):
        players = [{"model": "claude-opus-5-5", "role": "mole", "name": "M1"},
                   {"model": "claude-opus-5-5", "role": "mole", "name": "M2"}] + \
                  [{"model": "claude-haiku-4-5", "role": "crew", "name": f"C{i}"} for i in range(5)]
        for seed in range(10):
            game, _ = run_game(seed, make_config(players=players, anonymise=False))
            start = game.log.events[0]
            by_seat = sorted(start["players"], key=lambda p: p["seat"])
            moles = [p["name"] for p in by_seat if p["seat"] in start["mole_seats"]]
            crew = [p["name"] for p in by_seat if p["seat"] not in start["mole_seats"]]
            self.assertEqual(moles, ["M1", "M2"])
            self.assertEqual(crew, [f"C{i}" for i in range(5)])
            self.assertEqual(sorted(start["moles"]), ["M1", "M2"])


class Trials(unittest.TestCase):
    def test_trial_config_seats_test_model(self):
        raw = load_raw(BENCH_TOML)
        for kind in ("mole", "crew"):
            cfg = trial_config(raw, kind, "claude-sonnet-5", "claude-haiku-4-5")
            self.assertTrue(cfg.game.anonymise)
            self.assertEqual(len(cfg.players), 7)
            for seed in range(8):
                trial = {"kind": kind, "test_model": "claude-sonnet-5", "reference_model": "claude-haiku-4-5"}
                game, llm = run_game(seed, cfg, trial=trial)
                start = game.log.events[0]
                self.assertEqual(start["trial"], trial)
                self.assertTrue(start["anonymised"])
                test_seats = sorted(p["seat"] for p in start["players"] if p["model"] == "claude-sonnet-5")
                crew_seats = sorted(set(range(7)) - set(start["mole_seats"]))
                self.assertEqual(test_seats, start["mole_seats"] if kind == "mole" else crew_seats)
                for c in llm.calls:
                    self.assertIsNone(FAMILY.search(c["system"] + c["prompt"]))

    def test_trial_cli_records_trial_in_log_and_index(self):
        with tempfile.TemporaryDirectory() as d:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rc = cli.main(["trial", "--kind", "crew", "--test", "claude-sonnet-5", "--reference",
                               "claude-haiku-4-5", "--config", str(BENCH_TOML), "--seed", "4", "--mock", "--out", d])
            self.assertEqual(rc, 0)
            rows = [json.loads(line) for line in Path(d, "index.jsonl").read_text().splitlines()]
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["trial"], {"kind": "crew", "test_model": "claude-sonnet-5",
                                            "reference_model": "claude-haiku-4-5"})
            self.assertTrue(row["anonymised"])
            self.assertEqual(sum(1 for p in row["players"] if p["model"] == "claude-sonnet-5"), 5)
            for p in row["players"]:
                self.assertEqual(p["role"] == "crew", p["model"] == "claude-sonnet-5")
                self.assertIn("model_name", p)
            events = read_log(row["log"])
            self.assertEqual(events[0]["trial"]["kind"], "crew")
            md = Path(row["log"]).with_suffix(".md").read_text()
            self.assertIn("Benchmark trial: crew trial", md)

    def test_fixed_role_validation(self):
        raw = raw_default()
        raw["players"] = [dict(p, role="crew") for p in raw["players"]]
        with self.assertRaises(ValueError):
            config_from_dict(raw)                       # 0 moles != num_moles
        raw["players"][0]["role"] = "mole"
        with self.assertRaises(ValueError):
            config_from_dict(raw)                       # 1 mole != 2
        raw["players"][1]["role"] = "mole"
        config_from_dict(raw)
        del raw["players"][2]["role"]
        with self.assertRaises(ValueError):
            config_from_dict(raw)                       # all or none


if __name__ == "__main__":
    unittest.main()
