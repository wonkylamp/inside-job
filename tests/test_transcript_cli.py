"""Transcript for every ending, config parsing, and the CLI commands end to end."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from inside_job import __main__ as cli
from inside_job.config import ConfigError, config_from_dict, display_name
from inside_job.log import read_log
from inside_job.transcript import render

from helpers import (DEFAULT_TOML, Script, job_choice, suspicion_for, make_config, pick_with_mole, pick_without_moles,
                     raw_default, run_game, vote_crew, vote_moles, vote_with)


def ending_games():
    def r1_moles(s, p, o):
        return vote_moles(s, p, o) if s.game.round == 1 else vote_crew(s, p, o)
    big = dict(clean_target=9, sabotage_target=9)
    return {
        "jobs_clean": (make_config(), Script(1, job=job_choice("help"))),
        "moles_out": (make_config(), Script(1, job=job_choice("help"), pick=pick_without_moles,
                                            vote=vote_with(vote_moles))),
        "sabotage": (make_config(), Script(3, job=job_choice("sabotage"), pick=pick_with_mole,
                                           vote=vote_with(vote_crew))),
        "sabotage_lone": (make_config(), Script(4, job=job_choice("sabotage"), pick=pick_with_mole,
                                                vote=vote_with(r1_moles))),
        "final_two": (make_config(**big), Script(5, job=job_choice("help"), vote=vote_with(vote_crew))),
        "clock": (make_config(max_rounds=2, **big), Script(7, job=job_choice("help"), vote=vote_with(vote_crew))),
    }


class Transcript(unittest.TestCase):
    def test_renders_every_ending_with_every_name(self):
        for label, (cfg, script) in ending_games().items():
            game, _ = run_game(11, cfg, policy=script)
            end = game.log.events[-1]
            self.assertIn(end["reason"], label)
            md = render(game.log.events)
            for p in game.players:
                self.assertIn(p.name, md)
            self.assertIn("## Token report", md)
            self.assertIn(f"{end['winner']} win ({end['reason']})", md)
            self.assertIn("**Score: clean", md)
            if end["reason"] in ("moles_out",):
                self.assertIn("## The Cut", md)
            if label == "sabotage_lone":
                self.assertNotIn("## Finale", md)

    def test_marks_lies_cards_and_job_claims(self):
        def discuss(s, player, schema, prompt):
            others = schema["properties"]["move"]["properties"]["accuse"]["enum"]
            clue = s.game.clues_received[player][-1]
            cards = [{"kind": "not_mole", "players": [others[0]], "k": 0}]
            if clue["kind"] != "none":
                cards.append({"kind": clue["kind"], "players": clue["players"], "k": clue.get("k", 0)})
            return {"accuse": "none", "challenges": [], "clue_cards": cards,
                    "job_claim": "helped" if player in s.game.team else "none",
                    "suspicion": suspicion_for(schema)}
        s = Script(2, discuss=discuss, job=job_choice("sabotage"), pick=pick_with_mole)
        game, _ = run_game(2, make_config(clean_target=9, sabotage_target=9), policy=s)
        md = render(game.log.events)
        self.assertIn("CLUE CARD (real)", md)
        self.assertIn("CLUE CARD (FAKE)", md)
        self.assertIn("JOB CLAIM (FALSE)", md)
        self.assertIn("**LIE:**", md)
        self.assertIn("> *private:*", md)
        self.assertIn("suspicion (belief):", md)
        self.assertIn("suspicion (table read):", md)

    def test_anonymised_cast_table_shows_models(self):
        game, _ = run_game(3, make_config(anonymise=True))
        md = render(game.log.events)
        self.assertIn("| Seat | Codename | Model | Model id | Role |", md)
        for p in game.players:
            self.assertIn(f"| {p.name} | {p.model_name} | `{p.model}` |", md)


class Config(unittest.TestCase):
    def test_display_names(self):
        self.assertEqual(display_name("claude-opus-5-5"), "Opus 5.5")
        self.assertEqual(display_name("claude-fable-5"), "Fable 5")
        self.assertEqual(display_name("claude-sonnet-4-6"), "Sonnet 4.6")

    def test_duplicates_all_get_letters(self):
        # The v0.3 default cast has no repeats, so give it some.
        cfg = make_config(players=[{"model": "claude-haiku-4-5"}] * 2 + [{"model": m} for m in (
            "claude-haiku-5-5", "claude-sonnet-4-5", "claude-sonnet-4-6", "claude-sonnet-5", "claude-opus-5-5")])
        names = [p.name for p in cfg.players]
        self.assertIn("Haiku 4.5 A", names)
        self.assertIn("Haiku 4.5 B", names)
        self.assertNotIn("Haiku 4.5", names)
        self.assertEqual(len(set(names)), 7)

    def test_validation(self):
        bad = [
            {"players": raw_default()["players"][:3]},
            {"game": dict(raw_default()["game"], num_moles=4)},
            {"game": dict(raw_default()["game"], num_moles=0)},
            {"game": dict(raw_default()["game"], job_size=8)},
            {"game": dict(raw_default()["game"], job_size_small=4)},
            {"game": dict(raw_default()["game"], clue_strength="huge")},
            {"game": dict(raw_default()["game"], bogus=1)},
            # duplicate name: an explicit name equal to another seat's derived name
            {"players": raw_default()["players"][:6] + [{"model": "claude-x",
                                                        "name": display_name(raw_default()["players"][0]["model"])}]},
        ]
        for patch in bad:
            raw = dict(raw_default(), **patch)
            with self.assertRaises(ConfigError, msg=patch):
                config_from_dict(raw)


class CommandLine(unittest.TestCase):
    def test_run_transcript_usage(self):
        with tempfile.TemporaryDirectory() as d:
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()) as err:
                rc = cli.main(["run", "--config", str(DEFAULT_TOML), "--seed", "7", "--mock", "--out", d])
            self.assertEqual(rc, 0)
            self.assertIn("R1 discuss 1/14", err.getvalue())
            logs = list(Path(d).glob("g-*-s7.jsonl"))
            self.assertEqual(len(logs), 1)
            self.assertTrue(logs[0].with_suffix(".md").exists())
            rows = Path(d, "index.jsonl").read_text().splitlines()
            self.assertEqual(len(rows), 1)
            row = json.loads(rows[0])
            for k in ("game_id", "seed", "rules_version", "anonymised", "trial", "winner", "reason",
                      "clean_jobs", "blown_jobs", "rounds", "players", "finale", "calls", "fallbacks",
                      "tokens", "wall_s", "log"):
                self.assertIn(k, row)
            self.assertEqual(row["rules_version"], "0.3")
            self.assertIn("TOTAL", out.getvalue())
            md_path = Path(d, "t.md")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["transcript", str(logs[0]), "-o", str(md_path)]), 0)
            self.assertEqual(md_path.read_text(), render(read_log(logs[0])))
            u = io.StringIO()
            with contextlib.redirect_stdout(u):
                self.assertEqual(cli.main(["usage", str(logs[0])]), 0)
            self.assertIn("calls:", u.getvalue())


if __name__ == "__main__":
    unittest.main()
