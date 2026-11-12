"""v0.4 candidate rules as dials, phase A: engine and bots (docs/V04.md).

Every dial is off by default and must then change nothing: test 1 pins today's behaviour from a
fixture generated from the code before any v0.4 change (`tests/fixtures/v04_defaults/`)."""

from __future__ import annotations

import contextlib
import gzip
import io
import json
import random
import unittest
from pathlib import Path

from inside_job import __main__ as cli
from inside_job.bots import (BotLLM, cell_stats, format_row, game_summary, header_line, parse_sweep,
                             play_bot_game)
from inside_job.clues import clue_key, draw_recipients, generate_clue
from inside_job.config import ConfigError, GameConfig, config_from_dict, load_config, load_raw
from inside_job.engine import Game
from inside_job.llm import MockLLM
from inside_job.log import ENGINE_ONLY_TURN_FIELDS, project, visible_events, visible_to
from inside_job.solver import inputs_from_view

from helpers import (ROOT, NoPromptMock, Script, action_props, events_of, first_of, fixed_clock, job_choice,
                     make_config, pick_with_mole, pick_without_moles, raw_default, run_game, run_game_v04,
                     suspicion_for, turns, vote_with)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "v04_defaults"
PILOT = ROOT / "config" / "pilot.toml"
V04_TOML = ROOT / "config" / "v04_bots.toml"
DROP = ("ts", "game_id", "wall_s", "latency_s")
NEW_DIALS = {"mole_score_target": 4, "vote_nobody": True, "team_approval": True, "whisper_pairing": "random",
             "clue_turn": False, "endings": "stakes", "unique_clues": True}


def norm(x):
    if isinstance(x, dict):
        return {k: norm(v) for k, v in x.items() if k not in DROP}
    if isinstance(x, list):
        return [norm(v) for v in x]
    return x


def load_fixture(name):
    with gzip.open(FIXTURE / name, "rt", encoding="utf-8") as f:
        return json.load(f)


def raw_toml(name):
    return load_raw(ROOT / "config" / f"{name}.toml")


def v04_config(**game):
    """pilot.toml with the given [game] keys (the v0.4 config is pilot.toml plus dials)."""
    raw = raw_toml("pilot")
    raw["game"].update(game)
    return config_from_dict(raw)


def full_v04(**game):
    raw = load_raw(V04_TOML)
    raw["game"].update(game)
    return config_from_dict(raw)


def drop_new_config_keys(events, fixture_events):
    """Set aside the keys `game_start.config.game` gained after the fixture was made."""
    events = json.loads(json.dumps(events))
    known = set(fixture_events[0]["config"]["game"])
    for k in [k for k in events[0]["config"]["game"] if k not in known]:
        del events[0]["config"]["game"][k]
    return events


def add_dials(raw, **dials):
    raw = json.loads(json.dumps(raw))
    raw["game"].update(dials)
    return raw


# --------------------------------------------------------------------------- 1. defaults

class Defaults(unittest.TestCase):
    """With every v0.4 dial at its default the game plays exactly as before the change."""

    def assert_same_events(self, mine, fixture, what):
        mine = norm(drop_new_config_keys(mine, fixture))
        self.assertEqual(len(mine), len(fixture), what)
        for a, b in zip(mine, fixture):
            self.assertEqual(a, b, f"{what}: first difference at seq {b.get('seq')}")

    def test_mock_games_equal_fixture(self):
        for name, seeds in (("pilot", (1, 2, 3)), ("pilot2", (1, 2))):
            cfg = config_from_dict(raw_toml(name))
            self.assertEqual(cfg.game.v04_dials(), [])
            for s in seeds:
                g = Game(cfg, MockLLM(s), s, game_id="fixture", clock=lambda: "")
                g.run()
                self.assert_same_events(g.log.events, load_fixture(f"mock_{name}_s{s}.json.gz"), f"mock {name} s{s}")
                # A dial that is off adds no key to any event (outside game_start.config).
                for e in g.log.events:
                    for k in ("forced", "needed", "pairing", "crew_ejected", "mole_score"):
                        self.assertNotIn(k, e, e["type"])

    def test_bot_cell_equals_fixture(self):
        fx = load_fixture("bots_pilot_skill07.json.gz")
        cfg = config_from_dict(raw_toml("pilot"))
        for moles, want in fx.items():
            rows = []
            for s in range(1, len(want["rows"]) + 1):
                llm = BotLLM(cfg, s, crew="logician", crew_skill=0.7, moles=moles, mole_cards="decoy")
                g = Game(cfg, llm, s, game_id="fixture", clock=lambda: "")
                g.run()
                if str(s) in want["events"]:
                    self.assert_same_events(g.log.events, want["events"][str(s)], f"bots {moles} s{s}")
                rows.append(game_summary(g.log.events))
            for mine, old in zip(rows, want["rows"]):
                old_keys = {k: v for k, v in json.loads(json.dumps(mine)).items() if k in old}
                self.assertEqual(old_keys, old, (moles, old["seed"]))
            st = dict(cell_stats(rows), cell={}, games_per_s=0.0)
            self.assertEqual(format_row(st), want["row_line"], moles)
            self.assertEqual(format_row(st, False), want["row_line"])

    def test_default_dials(self):
        g = GameConfig()
        self.assertEqual(g.v04_dials(), [])
        self.assertEqual((g.mole_score_target, g.vote_nobody, g.forced_vote_after, g.team_approval,
                          g.whisper_pairing, g.clue_turn, g.endings, g.unique_clues),
                         (0, False, 2, False, "chosen", True, "classic", False))
        for name in ("default", "pilot", "pilot2", "bench"):
            raw = raw_toml(name)
            raw.setdefault("players", [{"model": f"m{i}"} for i in range(7)])
            self.assertEqual(config_from_dict(raw).game.v04_dials(), [], name)

    def test_header_unchanged_without_dials(self):
        self.assertEqual(header_line(), header_line(False))
        self.assertNotIn("ejected", header_line())
        self.assertIn("ejected", header_line(True))


# --------------------------------------------------------------------------- 2. config

class Config(unittest.TestCase):
    def bad(self, **game):
        with self.assertRaises(ConfigError):
            make_config(**game)

    def test_each_dial_validated(self):
        self.bad(mole_score_target=-1)
        self.bad(mole_score_target=2.5)
        self.bad(vote_nobody="yes")
        self.bad(vote_nobody=True, forced_vote_after=-1)
        self.bad(forced_vote_after=1)                      # only with vote_nobody
        self.bad(team_approval=1)
        self.bad(whisper_pairing="mutual")
        self.bad(clue_turn="no")
        self.bad(endings="cut")
        self.bad(unique_clues=0)
        for ok in ({"mole_score_target": 3}, {"vote_nobody": True, "forced_vote_after": 0},
                   {"team_approval": True}, {"whisper_pairing": "random"}, {"endings": "stakes"},
                   {"unique_clues": True}, {"clue_turn": False, "whispers": False},
                   {"clue_turn": False, "whisper_pairing": "random"}):
            cfg = make_config(**ok)
            self.assertTrue(cfg.game.v04_dials(), ok)

    def test_clue_turn_off_needs_random_or_no_whispers(self):
        with self.assertRaises(ConfigError) as cm:
            make_config(clue_turn=False)
        self.assertIn("clue_turn", str(cm.exception))

    def test_nobody_reserved_with_vote_nobody(self):
        players = [{"model": f"m{i}"} for i in range(6)] + [{"model": "x", "name": "Nobody"}]
        make_config(players=players)                       # fine without the dial
        with self.assertRaises(ConfigError):
            make_config(players=players, vote_nobody=True)

    def test_v04_dials_lists_the_dials_away_from_default(self):
        self.assertEqual(make_config(team_approval=True, endings="stakes").game.v04_dials(),
                         ["team_approval", "endings"])
        cfg = full_v04()
        self.assertEqual(set(cfg.game.v04_dials()), set(NEW_DIALS))
        self.assertEqual((cfg.game.whisper_exchanges, cfg.game.discussion_passes), (1, 1))

    def test_bot_only_guard(self):
        cfg = make_config(team_approval=True, unique_clues=True)
        with self.assertRaises(ValueError) as cm:
            Game(cfg, MockLLM(1), 1)
        self.assertIn("team_approval", str(cm.exception))
        self.assertIn("unique_clues", str(cm.exception))
        Game(cfg, BotLLM(cfg, 1), 1)                       # the bots need no prompts
        Game(cfg, NoPromptMock(1), 1)
        Game(make_config(), MockLLM(1), 1)                 # no dial: no guard

    def test_run_refuses_v04_config(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(ValueError):
                cli.main(["run", "--mock", "--config", str(V04_TOML), "--seed", "1", "--out", d])


# --------------------------------------------------------------------------- 3. mole score

def by_round(fns: dict, default):
    """A Script phase function that dispatches on the game's current round."""
    def fn(s, player, schema, prompt):
        return fns.get(s.game.round, default)(s, player, schema, prompt)
    return fn


class MoleScore(unittest.TestCase):
    def test_ends_on_wrongly_ejected_crew(self):
        cfg = make_config(mole_score_target=2)
        script = Script(1, pick=pick_without_moles, job=job_choice("help"),
                        vote=vote_with(lambda s, p, o: first_of(s.crew_alive(), o)))
        game, _ = run_game_v04(3, cfg, script)
        end = game.result
        self.assertEqual((end["winner"], end["reason"]), ("moles", "mole_score"))
        self.assertEqual((end["crew_ejected"], end["mole_score"], end["blown_jobs"], end["rounds"]), (2, 2, 0, 2))
        rs = events_of(game.log.events, "round_start")
        self.assertEqual([(e["crew_ejected"], e["mole_score"]) for e in rs], [(0, 0), (1, 1)])
        self.assertEqual(game.log.events[-1]["type"], "game_end")
        self.assertEqual(events_of(game.log.events, "vote_result")[-1]["round"], 2)   # ended after the vote

    def test_ends_on_blown_job(self):
        cfg = make_config(mole_score_target=2, sabotage_target=1)       # sabotage_target is not used
        script = Script(2, pick=by_round({2: pick_with_mole}, pick_without_moles), job=job_choice("sabotage"),
                        vote=vote_with(lambda s, p, o: first_of(s.crew_alive(), o)))
        game, _ = run_game_v04(4, cfg, script)
        end = game.result
        self.assertEqual((end["winner"], end["reason"], end["rounds"]), ("moles", "mole_score", 2))
        self.assertEqual((end["crew_ejected"], end["blown_jobs"], end["mole_score"]), (1, 1, 2))
        self.assertEqual([e["type"] for e in game.log.events if e["round"] == 2
                          and e["phase"] not in ("cut", "finale", "end")][-1],
                         "job_result")
        self.assertFalse(turns(game.log.events, "discuss", 2))            # the game ended at the job

    def test_sabotage_target_unused_and_no_clock(self):
        # Three blown jobs (score 3 < 4), then three clean ones: six rounds, past the old clock
        # (players - 2 = 5), with nobody ever voted out.
        cfg = make_config(mole_score_target=4, vote_nobody=True, forced_vote_after=0)
        script = Script(3, pick=by_round({1: pick_with_mole, 2: pick_with_mole, 3: pick_with_mole},
                                         pick_without_moles),
                        job=job_choice("sabotage"), vote=vote_with(lambda s, p, o: "nobody"))
        game, _ = run_game_v04(5, cfg, script)
        end = game.result
        self.assertEqual((end["winner"], end["reason"], end["rounds"]), ("crew", "jobs_clean", 6))
        self.assertEqual((end["blown_jobs"], end["clean_jobs"], end["mole_score"]), (3, 3, 3))

    def test_clock_kept_when_max_rounds_set(self):
        cfg = make_config(mole_score_target=4, vote_nobody=True, forced_vote_after=0, max_rounds=2,
                          clean_target=5)
        script = Script(4, pick=pick_without_moles, vote=vote_with(lambda s, p, o: "nobody"))
        game, _ = run_game_v04(6, cfg, script)
        self.assertEqual((game.result["reason"], game.result["rounds"]), ("clock", 2))


# --------------------------------------------------------------------------- 4. nobody vote

def votes_by_round(plan: dict):
    """plan: round -> function(script, alive_seat_order) -> {voter: target}."""
    def fn(s, player, schema, prompt):
        votes = plan[s.game.round](s, s.alive())
        return {"vote": votes.get(player, "nobody"), "suspicion": suspicion_for(schema)}
    return fn


class NobodyVote(unittest.TestCase):
    def test_majority_boundaries_odd_and_even(self):
        def k_for_crew(k):
            def plan(s, alive):
                target = s.crew_alive()[-1]
                voters = [a for a in alive if a != target][:k]
                return {v: target for v in voters}
            return plan
        cfg = make_config(vote_nobody=True, forced_vote_after=0, clean_target=9, sabotage_target=5)
        script = Script(5, pick=pick_without_moles,
                        vote=votes_by_round({1: k_for_crew(4), 2: k_for_crew(3), 3: k_for_crew(4),
                                             4: k_for_crew(2), 5: k_for_crew(3)}))
        game, _ = run_game_v04(7, cfg, script)
        vr = events_of(game.log.events, "vote_result")
        # 7 alive: 4 needed, 4 votes eject.
        self.assertEqual((vr[0]["needed"], vr[0]["forced"], vr[0]["eliminated"] is not None), (4, False, True))
        self.assertEqual(vr[0]["role"], "crew")
        # 6 alive: 4 needed, 3 votes (half) eject nobody; then 4 do.
        self.assertEqual((vr[1]["needed"], vr[1]["eliminated"], vr[1]["role"], vr[1]["tied"], vr[1]["tiebreak"]),
                         (4, None, None, [], None))
        self.assertEqual(vr[1]["tally"]["nobody"], 3)
        self.assertEqual((vr[2]["needed"], vr[2]["eliminated"] is not None), (4, True))
        # 5 alive: 3 needed; 2 is not enough, 3 is.
        self.assertEqual((vr[3]["needed"], vr[3]["eliminated"]), (3, None))
        self.assertEqual((vr[4]["needed"], vr[4]["eliminated"] is not None), (3, True))
        self.assertEqual(sum(vr[1]["tally"].values()), 6)

    def test_forced_vote_and_streak_reset(self):
        seen = {}

        def vote(s, player, schema, prompt):
            enum = action_props(schema)["vote"]["enum"]
            seen.setdefault(s.game.round, set()).add("nobody" in enum)
            target = "nobody" if "nobody" in enum else first_of(s.crew_alive(), enum)
            return {"vote": target, "suspicion": suspicion_for(schema)}
        cfg = make_config(vote_nobody=True, forced_vote_after=2, clean_target=6, sabotage_target=6)
        game, _ = run_game_v04(8, cfg, Script(6, pick=pick_without_moles, vote=vote))
        vr = events_of(game.log.events, "vote_result")
        self.assertGreaterEqual(len(vr), 5)
        self.assertEqual([e["forced"] for e in vr[:6]], [False, False, True, False, False, True][:len(vr[:6])])
        self.assertEqual([e["eliminated"] is None for e in vr[:5]], [True, True, False, True, True])
        self.assertIsNone(vr[2]["needed"])
        self.assertEqual(seen[3], {False})                   # the forced vote offers no `nobody`
        self.assertEqual(seen[4], {True})                    # the streak reset after the ejection
        self.assertNotIn("nobody", vr[2]["tally"])

    def test_forced_never_with_zero(self):
        cfg = make_config(vote_nobody=True, forced_vote_after=0, clean_target=5, sabotage_target=5)
        game, _ = run_game_v04(9, cfg, Script(7, pick=pick_without_moles,
                                               vote=vote_with(lambda s, p, o: "nobody")))
        vr = events_of(game.log.events, "vote_result")
        self.assertTrue(all(e["eliminated"] is None and not e["forced"] for e in vr))

    def test_nobody_out_is_readable_by_bot_path(self):
        cfg = make_config(vote_nobody=True, forced_vote_after=0, clean_target=5, sabotage_target=5)
        game, _ = run_game_v04(9, cfg, Script(7, pick=pick_without_moles,
                                               vote=vote_with(lambda s, p, o: "nobody")))
        ev = game.log.events
        self.assertEqual(inputs_from_view(visible_events(ev, None), None)["revealed"], {})
        row = game_summary(ev)
        self.assertEqual((row["votes_nobody"], row["crew_ejected"]), (row["votes"], 0))
        self.assertEqual(game.vote_record(game.players[0].name), 0)

    def test_failed_vote_abstains(self):
        cfg = make_config(vote_nobody=True, forced_vote_after=0, clean_target=5, sabotage_target=5)
        bad = lambda s, p, schema, prompt: {"vote": "Mars", "suspicion": suspicion_for(schema)}
        game, _ = run_game_v04(10, cfg, Script(8, pick=pick_without_moles, vote=bad))
        for t in turns(game.log.events, "vote"):
            self.assertTrue(t["fallback"])
            self.assertEqual(t["action"]["vote"], "nobody")


# --------------------------------------------------------------------------- 5. team approval

def approve_by_round(plan: dict, default=True):
    """plan: round -> function(script, player) -> bool."""
    def fn(s, player, schema, prompt):
        props = action_props(schema)
        f = plan.get(s.game.round)
        return {"accuse": "none", "challenges": [], "clue_cards": [],
                "approve": f(s, player) if f else default, "suspicion": suspicion_for(schema)}
    return fn


class TeamApproval(unittest.TestCase):
    def cfg(self, **kw):
        return make_config(team_approval=True, discussion_passes=1, **kw)

    def test_approved_path(self):
        game, _ = run_game_v04(11, self.cfg(), Script(9, debate=approve_by_round({})))
        ev = game.log.events
        r1 = [e for e in ev if e["round"] == 1]
        self.assertEqual([e["forced"] for e in r1 if e["type"] == "job_pick"], [False])
        tv = [e for e in r1 if e["type"] == "team_vote"]
        self.assertEqual(len(tv), 1)
        self.assertTrue(tv[0]["approved"])
        self.assertEqual((tv[0]["approve"], tv[0]["reject"]), (7, 0))
        order = [t["player"] for t in turns(ev, "debate", 1)]
        self.assertEqual(list(tv[0]["approvals"]), order)
        self.assertEqual(order, game_order_after(ev, tv[0]["leader"]))
        # Round order: clue, whispers, pick, debate, team vote, job, discussion, vote.
        seq = [e["turn_phase"] if e["type"] == "turn" else e["type"] for e in r1]
        seq = [x for x in seq if x in ("clue", "whisper", "pick", "debate", "team_vote", "job_result", "discuss",
                                       "vote")]
        compact = [x for i, x in enumerate(seq) if i == 0 or seq[i - 1] != x]
        self.assertEqual(compact, ["clue", "whisper", "pick", "debate", "team_vote", "job_result", "discuss", "vote"])

    def test_rejected_path(self):
        cfg = self.cfg(clean_target=5, sabotage_target=5)
        game, _ = run_game_v04(12, cfg, Script(10, debate=approve_by_round({1: lambda s, p: False})))
        ev = game.log.events
        seats = game.seat_order()
        rs = events_of(ev, "round_start")
        first = rs[0]["leader"]
        picks = [e for e in ev if e["type"] == "job_pick" and e["round"] == 1]
        self.assertEqual([p["forced"] for p in picks], [False, True])
        self.assertEqual(picks[0]["leader"], first)
        second = seats[(seats.index(first) + 1) % len(seats)]
        self.assertEqual(picks[1]["leader"], second)
        self.assertEqual(len(turns(ev, "debate", 1)), 7)          # no second debate
        self.assertEqual(len(events_of([e for e in ev if e["round"] == 1], "team_vote")), 1)
        self.assertFalse(events_of(ev, "team_vote")[0]["approved"])
        jr = [e for e in ev if e["type"] == "job_result" and e["round"] == 1][0]
        self.assertEqual(jr["team"], picks[1]["team"])
        # Next round's leader is the seat after the new leader (skipping anyone voted out).
        out = events_of(ev, "vote_result")[0]["eliminated"]
        nxt = [s for s in seats[seats.index(second) + 1:] + seats[:seats.index(second) + 1] if s != out][0]
        self.assertEqual(rs[1]["leader"], nxt)
        # The forced leader leads the rest of the round: discussion ends with them.
        self.assertEqual([t["player"] for t in turns(ev, "discuss", 1)][-1], second)

    def test_strict_majority_and_tie_rejected(self):
        # Round 1, 7 alive: 4 approvals pass, 3 do not. Round 2, 6 alive: 3-3 is rejected.
        def k_yes(k):
            return lambda s, p: s.alive().index(p) < k
        cfg = self.cfg(clean_target=5, sabotage_target=5)
        script = Script(11, debate=approve_by_round({1: k_yes(4), 2: k_yes(3), 3: k_yes(3)}),
                        vote=by_round({1: vote_with(lambda s, p, o: first_of(s.crew_alive(), o))},
                                      vote_with(lambda s, p, o: first_of(s.crew_alive(), o))))
        game, _ = run_game_v04(13, cfg, script)
        tv = events_of(game.log.events, "team_vote")
        self.assertEqual([(e["round"], e["approve"], e["reject"], e["approved"]) for e in tv[:2]],
                         [(1, 4, 3, True), (2, 3, 3, False)])
        cfg7 = self.cfg(clean_target=5, sabotage_target=5)
        game, _ = run_game_v04(13, cfg7, Script(12, debate=approve_by_round({1: k_yes(3)})))
        self.assertFalse(events_of(game.log.events, "team_vote")[0]["approved"])

    def test_debate_statements_ids_challenges(self):
        def discuss(s, player, schema, prompt):
            ids = action_props(schema)["challenges"].get("items", {}).get("enum", [])
            deb = [i for i in ids if any(t["statement_id"] == i and t["turn_phase"] == "debate"
                                          for t in turns(s.game.log.events))]
            return {"accuse": "none", "challenges": deb[:1], "clue_cards": [],
                    "job_claim": "none", "suspicion": suspicion_for(schema)}

        def debate(s, player, schema, prompt):
            ids = action_props(schema)["challenges"].get("items", {}).get("enum", [])
            return {"accuse": "none", "challenges": ids[:1], "clue_cards": [], "approve": True,
                    "suspicion": suspicion_for(schema)}
        game, _ = run_game_v04(14, self.cfg(), Script(13, debate=debate, discuss=discuss))
        ev = game.log.events
        deb = turns(ev, "debate", 1)
        self.assertTrue(all(t["statement_id"] and t["statement_id"].startswith("R1-S") for t in deb))
        pick = turns(ev, "pick", 1)[0]
        self.assertEqual(deb[0]["action"]["challenges"], [pick["statement_id"]])
        self.assertEqual(deb[1]["action"]["challenges"], [pick["statement_id"]])
        for t in deb:
            self.assertEqual(t["suspicion_kind"], "table_read" if game.role_of(t["player"]) == "mole" else "belief")
            self.assertIn("checks", t)
            self.assertNotIn("job_claim", t["action"])
            self.assertFalse(t["fallback"])
        dis = turns(ev, "discuss", 1)
        deb_ids = {t["statement_id"] for t in deb}
        self.assertTrue(dis and all(t["action"]["challenges"] and t["action"]["challenges"][0] in deb_ids
                                    for t in dis))

    def test_debate_fallback(self):
        victim = {}

        def debate(s, player, schema, prompt):
            victim.setdefault("p", player)
            if player == victim["p"]:
                return {"accuse": "nobody-at-all"}
            return None
        game, _ = run_game_v04(15, self.cfg(), Script(14, debate=debate))
        t = [t for t in turns(game.log.events, "debate", 1) if t["player"] == victim["p"]][0]
        self.assertTrue(t["fallback"])
        self.assertEqual({k: t["action"][k] for k in ("accuse", "challenges", "clue_cards", "approve")},
                         {"accuse": "none", "challenges": [], "clue_cards": [], "approve": True})
        self.assertIsNone(t["statement_id"])
        self.assertEqual(events_of(game.log.events, "team_vote")[0]["approvals"][victim["p"]], True)


def game_order_after(events, leader):
    seats = next(e for e in events if e["type"] == "table")["seats"]
    alive = next(e for e in events if e["type"] == "round_start")["alive"]
    i = seats.index(leader)
    return [s for s in seats[i + 1:] + seats[:i + 1] if s in alive]


# --------------------------------------------------------------------------- 6. random whispers

class RandomWhispers(unittest.TestCase):
    def test_pairs_from_seed_only(self):
        cfg = make_config(whisper_pairing="random")
        a, _ = run_game_v04(21, cfg, mock_seed=1)
        b, _ = run_game_v04(21, cfg, mock_seed=2)
        pa = events_of(a.log.events, "whisper_pairs")
        pb = events_of(b.log.events, "whisper_pairs")
        self.assertEqual(pa[0]["pairs"], pb[0]["pairs"])
        # The pairs are exactly the whisper stream's shuffle of the alive players (seat order).
        pool = list(events_of(a.log.events, "round_start")[0]["alive"])
        random.Random("21:whispers").shuffle(pool)
        self.assertEqual(pa[0]["pairs"], [pool[0:2], pool[2:4], pool[4:6]])
        other = [events_of(run_game_v04(s, cfg)[0].log.events, "whisper_pairs")[0]["pairs"] for s in (22, 23)]
        self.assertTrue(any(p != pa[0]["pairs"] for p in other))

    def test_never_repeat_respect_cap_no_requests(self):
        for cap in (1, 2, 3):
            cfg = make_config(whisper_pairing="random", whisper_pairs_max=cap)
            for seed in range(4):
                game, _ = run_game_v04(seed, cfg)
                ev = game.log.events
                self.assertFalse(events_of(ev, "whisper_requests"))
                for wp in events_of(ev, "whisper_pairs"):
                    alive = [e for e in events_of(ev, "round_start") if e["round"] == wp["round"]][0]["alive"]
                    flat = [p for pair in wp["pairs"] for p in pair]
                    self.assertEqual(len(flat), len(set(flat)))
                    self.assertLessEqual(set(flat), set(alive))
                    self.assertEqual(len(wp["pairs"]), min(cap, len(alive) // 2))
                    self.assertEqual(wp["pairing"], "random")
                for t in turns(ev, "clue"):
                    self.assertNotIn("whisper_with", t["action"])
                for wp in events_of(ev, "whisper_pairs"):            # the first drawn speaks first
                    ws = [t for t in turns(ev, "whisper", wp["round"])]
                    for a, b in wp["pairs"]:
                        mine = [t["player"] for t in ws if {t["player"], t["partner"]} == {a, b}]
                        self.assertEqual(mine[0], a)

    def test_deal_unchanged(self):
        for seed in (1, 5, 9):
            chosen, _ = run_game(seed, make_config())
            rnd, _ = run_game_v04(seed, make_config(whisper_pairing="random", clue_turn=False,
                                                    whisper_exchanges=1, unique_clues=False))
            a, b = chosen.log.events, rnd.log.events
            for k in ("moles", "mole_seats", "first_leader", "players"):
                self.assertEqual(a[0][k], b[0][k], k)
            c1 = [(e["player"], e["clue"]) for e in a if e["type"] == "clue" and e["round"] == 1]
            c2 = [(e["player"], e["clue"]) for e in b if e["type"] == "clue" and e["round"] == 1]
            self.assertEqual(c1, c2)
            self.assertEqual(events_of(a, "clue_deal")[0]["recipients"], events_of(b, "clue_deal")[0]["recipients"])


# --------------------------------------------------------------------------- 7. no clue turn

class NoClueTurn(unittest.TestCase):
    def test_no_clue_calls_clues_still_dealt(self):
        cfg = make_config(clue_turn=False, whisper_pairing="random")
        game, llm = run_game_v04(31, cfg)
        ev = game.log.events
        self.assertFalse(turns(ev, "clue"))
        self.assertFalse([c for c in llm.calls if c["phase"] == "clue"])
        for rs in events_of(ev, "round_start"):
            got = sorted(e["player"] for e in ev if e["type"] == "clue" and e["round"] == rs["round"])
            self.assertEqual(got, sorted(rs["alive"]))
        self.assertTrue(events_of(ev, "clue_deal"))

    def test_clues_reach_the_view(self):
        cfg = make_config(clue_turn=False, whispers=False)
        seen = {}

        def audit(player, view):
            seen[player] = [e for e in view if e["type"] == "clue"]
        llm = BotLLM(cfg, 3, audit=audit)
        game = Game(cfg, llm, 3, game_id="b")
        game.run()
        for p, clues in seen.items():
            mine = [e["clue"] for e in game.log.events if e["type"] == "clue" and e["player"] == p]
            self.assertEqual([e["clue"] for e in clues], mine[:len(clues)])
            self.assertTrue(clues)
        self.assertFalse(events_of(game.log.events, "whisper_pairs"))


# --------------------------------------------------------------------------- 8. endings

class Endings(unittest.TestCase):
    def check_common(self, game):
        ev = game.log.events
        self.assertFalse(events_of(ev, "cut_result"))
        self.assertFalse(turns(ev, "cut_pitch") + turns(ev, "cut_vote"))
        end = game.result
        self.assertLessEqual(sum(end["payouts"].values()), game.cfg.game.pot)
        self.assertEqual(set(end["payouts"]), {p.name for p in game.players})
        return end

    def test_two_moles_win_split_steal(self):
        cfg = make_config(endings="stakes", sabotage_target=1)
        game, _ = run_game_v04(41, cfg, Script(20, pick=pick_with_mole, job=job_choice("sabotage")))
        end = self.check_common(game)
        self.assertEqual(end["winner"], "moles")
        fr = events_of(game.log.events, "finale_result")[0]
        self.assertEqual(sorted(fr["finalists"]), sorted(game.moles_alive()))
        self.assertEqual(len(game.moles_alive()), 2)

    def test_one_mole_wins_takes_pot(self):
        cfg = make_config(endings="stakes", sabotage_target=1)
        script = Script(21, pick=by_round({1: pick_without_moles}, pick_with_mole), job=job_choice("sabotage"),
                        vote=vote_with(lambda s, p, o: first_of(s.moles_alive(), o)))
        game, _ = run_game_v04(42, cfg, script)
        end = self.check_common(game)
        self.assertEqual(end["winner"], "moles")
        (m,) = game.moles_alive()
        self.assertEqual(end["payouts"][m], 100)
        self.assertFalse(events_of(game.log.events, "finale_result"))

    def test_moles_out_shares_pot(self):
        cfg = make_config(endings="stakes", clean_target=5)
        script = Script(22, pick=pick_without_moles, vote=vote_with(lambda s, p, o: first_of(s.moles_alive(), o)))
        game, _ = run_game_v04(43, cfg, script)
        end = self.check_common(game)
        self.assertEqual((end["winner"], end["reason"]), ("crew", "moles_out"))
        crew = [n for n in game.alive() if game.role_of(n) == "crew"]
        self.assertEqual(len(crew), 5)
        self.assertEqual({n: end["payouts"][n] for n in crew}, {n: 20 for n in crew})
        self.assertFalse(events_of(game.log.events, "final_accusation") + events_of(game.log.events, "finale_result"))

    def fa_game(self, seed, accuse_fn):
        cfg = make_config(endings="stakes")
        script = Script(23, pick=pick_without_moles, vote=vote_with(lambda s, p, o: first_of(s.crew_alive(), o)),
                        final_accuse=lambda s, p, schema, prompt: {"accuse": accuse_fn(s, p, action_props(schema)["accuse"]["enum"])})
        game, _ = run_game_v04(seed, cfg, script)
        end = self.check_common(game)
        self.assertEqual((end["winner"], end["reason"]), ("crew", "jobs_clean"))
        fa = events_of(game.log.events, "final_accusation")[0]
        fts = turns(game.log.events, "final_accuse")
        self.assertEqual(sorted(t["player"] for t in fts), sorted(game.alive()))
        self.assertTrue(all(t["phase"] == "finale" for t in fts))
        self.assertEqual(fa["votes"], {t["player"]: t["action"]["accuse"] for t in fts})
        self.assertEqual(fa["role"], game.role_of(fa["accused"]))
        self.assertEqual(fa["payouts"], {n: v for n, v in end["payouts"].items() if v})
        self.assertFalse(events_of(game.log.events, "finale_result"))
        return game, fa, end

    def test_final_accusation_hit(self):
        game, fa, end = self.fa_game(44, lambda s, p, o: first_of(s.moles_alive(), o))
        self.assertTrue(fa["hit"])
        crew = [n for n in game.alive() if game.role_of(n) == "crew"]
        self.assertEqual({n: end["payouts"][n] for n in crew}, {n: 100 // len(crew) for n in crew})
        self.assertEqual(end["winner"], "crew")

    def test_final_accusation_miss(self):
        game, fa, end = self.fa_game(45, lambda s, p, o: first_of(s.crew_alive(), o))
        self.assertFalse(fa["hit"])
        moles = game.moles_alive()
        self.assertEqual({n: end["payouts"][n] for n in moles}, {n: 100 // len(moles) for n in moles})
        self.assertEqual(end["winner"], "crew")                  # the team result stands

    def test_final_accusation_tie(self):
        def accuse(s, p, enum):
            L = s.alive()                        # five alive: a 2-2-1 split between L0 and L1
            return {L[0]: L[1], L[1]: L[0], L[2]: L[0], L[3]: L[1]}.get(p, L[2])
        accused = set()
        for seed in (46, 47, 48, 49):
            game, fa, end = self.fa_game(seed, accuse)
            L = game.alive()
            self.assertEqual(len(L), 5)
            self.assertEqual((fa["tied"], fa["tiebreak"]), (L[:2], "random"))
            self.assertIn(fa["accused"], L[:2])
            self.assertEqual(fa["hit"], game.role_of(fa["accused"]) == "mole")
            accused.add(fa["accused"] == L[0])
        self.assertEqual(accused, {True, False})             # the draw goes both ways

    def test_final_accuse_fallback(self):
        cfg = make_config(endings="stakes")
        script = Script(24, pick=pick_without_moles, vote=vote_with(lambda s, p, o: first_of(s.crew_alive(), o)),
                        final_accuse=lambda s, p, schema, prompt: {"accuse": "Mars"})
        game, _ = run_game_v04(47, cfg, script)
        for t in turns(game.log.events, "final_accuse"):
            self.assertTrue(t["fallback"])
            self.assertIn(t["action"]["accuse"], game.others(t["player"]))

    def test_payouts_never_exceed_pot_with_bots(self):
        cfg = full_v04()
        for seed in range(1, 41):
            ev = play_bot_game(cfg, seed)
            end = ev[-1]
            self.assertLessEqual(sum(end["payouts"].values()), 100)
            self.assertFalse(events_of(ev, "cut_result"))


# --------------------------------------------------------------------------- 9. privacy

PRIVATE_ACTION = {"debate": {"suspicion"}, "final_accuse": set(), "vote": {"suspicion"},
                  "discuss": {"suspicion"}, "pick": set()}


class Privacy(unittest.TestCase):
    def full_game(self, seed, bots=True):
        cfg = full_v04()
        if bots:
            llm = BotLLM(cfg, seed)
        else:
            llm = NoPromptMock(seed)
        game = Game(cfg, llm, seed, game_id="p", clock=fixed_clock)
        game.run()
        return game

    def check(self, game):
        ev = game.log.events
        names = [p.name for p in game.players]
        roles = {p.name: p.role for p in game.players}
        seen_types = set()
        for viewer in names + [None]:
            for e in ev:
                if not visible_to(e, viewer):
                    if e["type"] in ("team_vote", "final_accusation", "whisper_pairs", "vote_result", "job_pick"):
                        self.fail(f"public event hidden from {viewer}: {e['type']}")
                    continue
                p = project(e, viewer)
                if p is None:
                    continue
                self.assertNotIn(e["type"], ("game_start", "clue_deal", "job_choices", "whisper_requests"))
                if e["type"] != "turn":
                    if e["vis"] == "private":
                        self.assertEqual(e["player"], viewer)
                    continue
                if e["player"] == viewer:
                    for k in ENGINE_ONLY_TURN_FIELDS:
                        self.assertNotIn(k, p)
                    continue
                tp = e["turn_phase"]
                seen_types.add(tp)
                for k in ("confessional", "claims", "memory", "checks", "model", "suspicion_kind", "rejections"):
                    self.assertNotIn(k, p, (viewer, tp, k))
                self.assertNotIn("suspicion", p.get("action", {}), (viewer, tp))
                if tp == "debate":
                    self.assertEqual(set(p["action"]), {"accuse", "challenges", "clue_cards", "approve"})
                    self.assertEqual(p["public"], e["public"])
                elif tp == "final_accuse":
                    self.assertEqual(set(p["action"]), {"accuse"})
                    self.assertEqual(p["public"], e["public"])
                elif tp == "job":
                    self.assertEqual(roles[viewer], "mole")
                    self.assertIn(viewer, e["shared_with"])
                elif tp == "whisper":
                    self.assertEqual(e["partner"], viewer)
                    self.assertEqual(set(p["action"]), {"clue_cards"})
                else:
                    self.assertIn(tp, ("pick", "discuss", "vote", "finale_pitch"), tp)
                # No other player's confessional text appears anywhere in the projection.
                if e["confessional"]:
                    self.assertNotIn(e["confessional"], json.dumps(p))
        return seen_types

    def test_full_dials_bots(self):
        seen = set()
        for seed in range(1, 13):
            seen |= self.check(self.full_game(seed))
        self.assertIn("debate", seen)
        self.assertIn("final_accuse", seen)

    def test_full_dials_random_replies(self):
        seen = set()
        for seed in range(1, 9):
            seen |= self.check(self.full_game(seed, bots=False))
        self.assertIn("debate", seen)

    def test_bot_view_is_its_projection(self):
        cfg = full_v04()
        holder, n = {}, {"k": 0}

        def audit(player, view):
            events = holder["game"].log.events
            self.assertEqual(view, [p for p in (project(e, player) for e in events if visible_to(e, player))
                                    if p is not None])
            n["k"] += 1
        for seed in (2, 3):
            llm = BotLLM(cfg, seed, audit=audit)
            g = Game(cfg, llm, seed, game_id="b")
            holder["game"] = g
            g.run()
        self.assertGreater(n["k"], 50)

    def test_approve_and_accusations_public(self):
        game = self.full_game(3)
        pub = visible_events(game.log.events, None)
        deb = [e for e in pub if e["type"] == "turn" and e["turn_phase"] == "debate"]
        self.assertTrue(deb and all("approve" in e["action"] for e in deb))
        self.assertTrue(any(e["type"] == "team_vote" for e in pub))


# --------------------------------------------------------------------------- 10. unique clues

class UniqueClues(unittest.TestCase):
    def deal_rounds(self, unique, deals=50, rounds=4):
        players = list("ABCDEFG")
        dup_rounds = total = 0
        for d in range(deals):
            rng = random.Random(f"u:{d}")
            moles = rng.sample(players, 2)
            alive, revealed = list(players), {}
            held = {p: [] for p in players}
            for r in range(rounds):
                dealt = []
                for p in draw_recipients(rng, alive, 0, 0):        # everyone: the hardest case
                    c = generate_clue(rng=rng, players=players, alive=alive, moles=moles, num_moles=2,
                                      recipient=p, revealed=revealed, past_clues=held[p], strength="weak",
                                      avoid=dealt if unique else None)
                    held[p].append(c)
                    dealt.append(c)
                keys = [clue_key(c) for c in dealt if c["kind"] != "none"]
                dup_rounds += len(keys) != len(set(keys))
                total += 1
                out = rng.choice(alive)
                alive.remove(out)
                revealed[out] = "mole" if out in moles else "crew"
        return dup_rounds, total

    def test_200_rounds_no_duplicate(self):
        dups, total = self.deal_rounds(True)
        self.assertEqual(total, 200)
        self.assertEqual(dups, 0)
        dups_off, _ = self.deal_rounds(False)
        self.assertGreater(dups_off, 0)                      # the check is not vacuous

    def test_avoid_none_is_unchanged(self):
        kw = dict(players=list("ABCDEFG"), alive=list("ABCDEFG"), moles=["B", "E"], num_moles=2,
                  recipient="A", revealed={}, past_clues=[], strength="weak")
        a = generate_clue(rng=random.Random(5), **kw)
        b = generate_clue(rng=random.Random(5), avoid=None, **kw)
        c = generate_clue(rng=random.Random(5), avoid=[], **kw)
        self.assertEqual(a, b)
        self.assertEqual(a, c)
        d = generate_clue(rng=random.Random(5), avoid=[a], **kw)
        self.assertNotEqual(clue_key(d), clue_key(a))

    def test_engine_deals_unique(self):
        cfg = make_config(unique_clues=True, clue_recipients=0)
        for seed in range(6):
            game, _ = run_game_v04(seed, cfg)
            ev = game.log.events
            for r in {e["round"] for e in events_of(ev, "clue")}:
                keys = [clue_key(e["clue"]) for e in ev if e["type"] == "clue" and e["round"] == r
                        and e["clue"]["kind"] != "none"]
                self.assertEqual(len(keys), len(set(keys)), (seed, r))


# --------------------------------------------------------------------------- 11. bots

class V04Bots(unittest.TestCase):
    def test_300_games_no_fallbacks_each_mole_type(self):
        cfg = full_v04()
        for moles in ("smart", "always", "never", "hold1"):
            fb = 0
            for seed in range(1, 301):
                ev = play_bot_game(cfg, seed, crew_skill=0.7, moles=moles)
                fb += ev[-1]["fallbacks"]
                self.assertEqual(ev[-1]["type"], "game_end")
            self.assertEqual(fb, 0, moles)

    def test_hold1_never_sabotages_in_round_1(self):
        cfg = config_from_dict(raw_toml("pilot"))
        n = 0
        for seed in range(1, 41):
            ev = play_bot_game(cfg, seed, moles="hold1")
            for e in events_of(ev, "job_choices"):
                if e["round"] == 1:
                    self.assertNotIn("sabotage", e["choices"].values())
                else:
                    n += list(e["choices"].values()).count("sabotage")
        self.assertGreater(n, 0)

    def test_vote_thresholds(self):
        cfg = full_v04(forced_vote_after=0)

        def nobody_votes(eject):
            n = votes = 0
            for seed in range(1, 21):
                ev = play_bot_game(cfg, seed, crew_skill=1.0, eject_threshold=eject)
                crew = {p["name"] for p in ev[0]["players"] if p["role"] == "crew"}
                for e in events_of(ev, "vote_result"):
                    for voter, target in e["votes"].items():
                        if voter in crew:
                            votes += 1
                            n += target == "nobody"
                        else:
                            self.assertNotEqual(target, "nobody")   # moles always vote for an ejection
            return n, votes
        n, votes = nobody_votes(1.01)
        self.assertEqual(n, votes)                           # a belief is never above 1: always nobody
        n, votes = nobody_votes(0.0)
        self.assertEqual(n, 0)
        self.assertGreater(votes, 0)

    def test_debate_approval(self):
        cfg = full_v04()
        ev = play_bot_game(cfg, 4, crew_skill=1.0, approve_threshold=1.01)
        tv = events_of(ev, "team_vote")
        crew = {p["name"] for p in ev[0]["players"] if p["role"] == "crew"}
        self.assertTrue(all(all(v for n, v in e["approvals"].items() if n in crew) for e in tv))
        ev = play_bot_game(cfg, 4, crew_skill=1.0, mole_approve="team")
        moles = set(ev[0]["moles"])
        for e in events_of(ev, "team_vote"):
            for n, v in e["approvals"].items():
                if n in moles:
                    self.assertEqual(v, bool(set(e["team"]) & moles))

    def test_parse_sweep_bot_options(self):
        self.assertEqual(parse_sweep(["bot.eject_threshold=0.3,0.5", "mole_score_target=3,4"]),
                         [("bot.eject_threshold", [0.3, 0.5]), ("mole_score_target", [3, 4])])
        with self.assertRaises(ValueError):
            parse_sweep(["bot.skill=0.5"])

    def test_cli_options_and_v04_columns(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cli.main(["bots", "--games", "3", "--config", str(V04_TOML), "--moles", "hold1",
                           "--eject-threshold", "0.6", "--approve-threshold", "0.5", "--mole-approve", "team",
                           "--sweep", "bot.eject_threshold=0.4,0.7"])
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("ejected", text.splitlines()[0])
        self.assertEqual(len([l for l in text.splitlines() if l.startswith("bot.eject_threshold=")]), 2)
        self.assertIn("mole approve team", text)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["bots", "--games", "2", "--config", str(PILOT), "--sweep", "bot.approve_threshold=0.3,0.6"])
        self.assertNotIn("ejected", out.getvalue())          # no dial on: today's table

    def test_summary_fields(self):
        ev = play_bot_game(full_v04(), 5)
        row = game_summary(ev)
        for k in ("crew_ejected", "mole_score", "votes", "votes_nobody", "votes_forced", "team_votes",
                  "team_rejections", "fa_held", "fa_hit", "zero_blown", "over_by_r2"):
            self.assertIn(k, row)
        self.assertEqual(row["mole_score"], row["blown"] + row["crew_ejected"])
        self.assertEqual(row["team_votes"], len(events_of(ev, "team_vote")))
        st = cell_stats([row])
        self.assertIn("mole_score", st["reasons"])


if __name__ == "__main__":
    unittest.main()
