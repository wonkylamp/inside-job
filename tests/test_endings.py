"""Scripted games reach every ending; payoffs; finalists from the winning side; tie-breaks."""

import unittest

from inside_job.engine import payoffs

from helpers import (Script, events_of, finale, job_choice, make_config, pick_with_mole, pick_without_moles,
                     run_game, suspicion_for, turns, vote_crew, vote_moles, vote_with)
from test_games import check_game


def roles_of(game):
    return {p.name: p.role for p in game.players}


class Endings(unittest.TestCase):
    def finish(self, game, cfg):
        check_game(self, game.log.events, cfg)
        return game.log.events[-1]

    def test_jobs_clean_when_moles_never_sabotage(self):
        cfg = make_config()
        for seed in range(5):
            # Votes go to crew so the race, not the vote, decides (v0.3 deals changed the random votes).
            s = Script(seed, job=job_choice("help"), pick=pick_with_mole, vote=vote_with(vote_crew))
            game, _ = run_game(seed, cfg, policy=s)
            end = self.finish(game, cfg)
            self.assertEqual((end["winner"], end["reason"]), ("crew", "jobs_clean"))
            self.assertEqual(end["clean_jobs"], 3)
            self.assertEqual(end["blown_jobs"], 0)
            self.assertEqual(end["rounds"], 3)
            # Moles still in get nothing; finalists are crew.
            roles = roles_of(game)
            for n in game.moles_alive():
                self.assertEqual(end["payouts"][n], 0)
            for c in events_of(game.log.events, "cut_result"):
                self.assertTrue(all(roles[f] == "crew" for f in c["finalists"]))
                self.assertTrue(all(roles[v] == "crew" for v in c["votes"]))

    def test_moles_out_with_the_cut(self):
        cfg = make_config()
        s = Script(1, job=job_choice("help"), pick=pick_without_moles, vote=vote_with(vote_moles))
        game, _ = run_game(1, cfg, policy=s)
        end = self.finish(game, cfg)
        self.assertEqual((end["winner"], end["reason"]), ("crew", "moles_out"))
        self.assertEqual(end["rounds"], 2)
        cut = events_of(game.log.events, "cut_result")
        self.assertEqual(len(cut), 1)
        self.assertEqual(len(turns(game.log.events, "cut_pitch")), 5)
        self.assertEqual(len(cut[0]["finalists"]), 2)
        self.assertEqual(len(events_of(game.log.events, "finale_result")), 1)

    def test_moles_out_without_the_cut(self):
        cfg = make_config(clean_target=9, sabotage_target=9)

        def vote(s, player, others):
            # Thin the crew to two first, then take out the moles.
            return vote_crew(s, player, others) if len(s.crew_alive()) > 2 else vote_moles(s, player, others)
        s = Script(2, job=job_choice("help"), vote=vote_with(vote))
        game, _ = run_game(2, cfg, policy=s)
        end = self.finish(game, cfg)
        self.assertEqual((end["winner"], end["reason"]), ("crew", "moles_out"))
        self.assertEqual(events_of(game.log.events, "cut_result"), [])
        fin = events_of(game.log.events, "finale_result")
        self.assertEqual(len(fin), 1)
        self.assertEqual(sorted(fin[0]["finalists"]), sorted(end["survivors"]))

    def test_sabotage_two_moles_go_to_finale(self):
        cfg = make_config()
        s = Script(3, job=job_choice("sabotage"), pick=pick_with_mole, vote=vote_with(vote_crew))
        game, _ = run_game(3, cfg, policy=s)
        end = self.finish(game, cfg)
        self.assertEqual((end["winner"], end["reason"]), ("moles", "sabotage"))
        self.assertEqual(end["rounds"], 3)
        fin = events_of(game.log.events, "finale_result")[0]
        self.assertEqual(sorted(fin["finalists"]), sorted(game.moles_alive()))
        self.assertEqual(turns(game.log.events, "discuss", 3), [])     # game ended before discussion

    def test_sabotage_lone_mole_takes_the_pot(self):
        cfg = make_config()

        def vote(s, player, others):
            return vote_moles(s, player, others) if s.game.round == 1 else vote_crew(s, player, others)
        s = Script(4, job=job_choice("sabotage"), pick=pick_with_mole, vote=vote_with(vote))
        game, _ = run_game(4, cfg, policy=s)
        end = self.finish(game, cfg)
        self.assertEqual((end["winner"], end["reason"]), ("moles", "sabotage"))
        moles = game.moles_alive()
        self.assertEqual(len(moles), 1)
        self.assertEqual(end["payouts"][moles[0]], cfg.game.pot)
        self.assertEqual(sum(end["payouts"].values()), cfg.game.pot)
        self.assertEqual(events_of(game.log.events, "finale_result"), [])

    def test_final_two_backstop(self):
        cfg = make_config(clean_target=9, sabotage_target=9)
        s = Script(5, job=job_choice("help"), vote=vote_with(vote_crew))
        game, _ = run_game(5, cfg, policy=s)
        end = self.finish(game, cfg)
        self.assertEqual((end["winner"], end["reason"]), ("moles", "final_two"))
        fin = events_of(game.log.events, "finale_result")[0]
        self.assertEqual(sorted(fin["finalists"]), sorted(game.moles_alive()))

    def test_final_two_with_one_crew_left_pays_only_the_mole(self):
        cfg = make_config(clean_target=9, sabotage_target=9)

        def vote(s, player, others):
            return vote_moles(s, player, others) if s.game.round == 1 else vote_crew(s, player, others)
        s = Script(6, job=job_choice("help"), vote=vote_with(vote))
        game, _ = run_game(6, cfg, policy=s)
        end = self.finish(game, cfg)
        self.assertEqual((end["winner"], end["reason"]), ("moles", "final_two"))
        self.assertEqual(len(end["survivors"]), 2)
        mole = game.moles_alive()[0]
        crew = [n for n in end["survivors"] if n != mole][0]
        self.assertEqual(end["payouts"][mole], cfg.game.pot)
        self.assertEqual(end["payouts"][crew], 0)
        self.assertEqual(events_of(game.log.events, "finale_result"), [])

    def test_clock_backstop(self):
        cfg = make_config(max_rounds=2, clean_target=9, sabotage_target=9)
        s = Script(7, job=job_choice("help"), vote=vote_with(vote_crew))
        game, _ = run_game(7, cfg, policy=s)
        end = self.finish(game, cfg)
        self.assertEqual((end["winner"], end["reason"]), ("moles", "clock"))
        self.assertEqual(end["rounds"], 2)
        self.assertEqual(len(turns(game.log.events, "vote", 2)), 6)    # the last round was played out

    def test_payoffs_all_four_combinations(self):
        cfg = make_config()
        cases = {("split", "split"): (50, 50), ("split", "steal"): (0, 100),
                 ("steal", "split"): (100, 0), ("steal", "steal"): (0, 0)}
        for (a, b), (pa, pb) in cases.items():
            s = Script(8, job=job_choice("sabotage"), pick=pick_with_mole, vote=vote_with(vote_crew),
                       finale_choice=finale(a, b))
            game, _ = run_game(8, cfg, policy=s)
            end = self.finish(game, cfg)
            fin = events_of(game.log.events, "finale_result")[0]
            first = turns(game.log.events, "finale_pitch")[0]["player"]
            second = [f for f in fin["finalists"] if f != first][0]
            self.assertEqual((fin["choices"][first], fin["choices"][second]), (a, b))
            self.assertEqual((fin["payouts"][first], fin["payouts"][second]), (pa, pb))
            self.assertEqual((end["payouts"][first], end["payouts"][second]), (pa, pb))
        self.assertEqual(payoffs("split", "split", 100), (50, 50))
        self.assertEqual(payoffs("steal", "steal", 100), (0, 0))


class TieBreak(unittest.TestCase):
    def tie_script(self, leader_in_tie: bool, seed=0):
        def vote(s, player, schema, prompt):
            game = s.game
            if game.round != 1:
                return None
            leader = game.seat_order()[game.leader_seat]
            non = [n for n in game.alive() if n != leader]
            x, y, z, w = non[0], non[1], non[2], non[3]
            plan = {non[0]: y, non[1]: z, non[2]: x, non[3]: x if not leader_in_tie else leader,
                    non[4]: y, non[5]: z, leader: x if leader_in_tie else w}
            return {"vote": plan[player], "suspicion": suspicion_for(schema)}
        return Script(seed, job=job_choice("help"), pick=pick_without_moles, vote=vote)

    def test_leader_breaks_tie(self):
        game, _ = run_game(9, policy=self.tie_script(True))
        vr = events_of(game.log.events, "vote_result")[0]
        leader = events_of(game.log.events, "round_start")[0]["leader"]
        self.assertEqual(sorted(vr["tally"].values(), reverse=True)[:3], [2, 2, 2])
        self.assertEqual(len(vr["tied"]), 3)
        self.assertEqual(vr["tiebreak"], "leader")
        self.assertEqual(vr["eliminated"], vr["votes"][leader])

    def test_random_tiebreak_when_leader_voted_elsewhere(self):
        outcomes = set()
        for seed in range(12):
            game, _ = run_game(seed, policy=self.tie_script(False, seed))
            vr = events_of(game.log.events, "vote_result")[0]
            leader = events_of(game.log.events, "round_start")[0]["leader"]
            self.assertEqual(vr["tiebreak"], "random")
            self.assertIn(vr["eliminated"], vr["tied"])
            self.assertNotIn(vr["votes"][leader], vr["tied"])
            outcomes.add(vr["tied"].index(vr["eliminated"]))
            again, _ = run_game(seed, policy=self.tie_script(False, seed))
            self.assertEqual(events_of(again.log.events, "vote_result")[0]["eliminated"], vr["eliminated"])
        self.assertGreater(len(outcomes), 1)

    def test_clear_winner_has_no_tiebreak(self):
        s = Script(0, job=job_choice("help"), vote=vote_with(vote_moles))
        game, _ = run_game(10, policy=s)
        vr = events_of(game.log.events, "vote_result")[0]
        self.assertIsNone(vr["tiebreak"])
        self.assertEqual(vr["tied"], [])


if __name__ == "__main__":
    unittest.main()
