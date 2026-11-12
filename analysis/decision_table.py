"""The decision table: one row per decision in a batch of finished Inside Job games.

    python3.11 analysis/decision_table.py --batch pilot1 --games-dir games --out analysis/out
    python3.11 analysis/decision_table.py --selftest

Writes <out>/decisions_<batch>.jsonl, <out>/decisions_<batch>.csv and
<out>/decision_summary_<batch>.md. Reads logs only: no model calls, nothing written to games/.

Row types (metric definitions: docs/CLAIMS.md):
  reading   every non-fallback turn with a suspicion reading (clue, whisper, discuss, vote)
  vote      every non-fallback vote turn
  sabotage  every job turn (only moles on the team are asked)
  round     one row per mole per round in which that mole was alive at the round start (Bluff unit)
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (NONE, SUSPICION_PHASES, Boot, GameData, argmax_set, brier, fmt_stat,  # noqa: E402
                    load_games, log_score, mean)
from inside_job.solver import from_log, table_posterior  # noqa: E402

STAGES = ("clue", "whisper1", "whisper2", "discuss1", "discuss2", "vote")


# =========================================================================== rows

def base_fields(g: GameData, row_type: str, player: str, rnd: int, seq: int | None) -> dict:
    return {"batch": g.batch, "game_id": g.game_id, "seed": g.seed, "round": rnd, "seq": seq,
            "row_type": row_type, "player": player, "seat": g.seat.get(player), "model": g.model.get(player),
            "role": g.role.get(player), "sabotage_target": g.dials["sabotage_target"],
            "clean_target": g.dials["clean_target"]}


def stated_probs(g: GameData, turn: dict) -> dict:
    sus = (turn.get("action") or {}).get("suspicion") or {}
    return {n: min(100, max(0, v)) / 100 for n, v in sus.items() if n in g.truth}


def crew_vote_share(g: GameData, r: int):
    """(share of the crew's non-fallback votes on any mole, crew votes, crew votes on moles);
    share is None when there was no vote (or no counted crew vote)."""
    vr = g.vote_result.get(r)
    if vr is None:
        return None, 0, 0
    fb = {t["player"] for t in g.turns_in(r, "vote") if t.get("fallback")}
    crew = {v: tg for v, tg in (vr.get("votes") or {}).items() if g.role.get(v) == "crew" and v not in fb}
    k = sum(1 for tg in crew.values() if tg in g.moles)
    return (k / len(crew) if crew else None), len(crew), k


def stage_of(g: GameData, t: dict) -> str:
    tp = t["turn_phase"]
    if tp == "whisper":
        mine = [w["seq"] for w in g.turns_in(t["round"], "whisper") if w["player"] == t["player"]]
        return f"whisper{mine.index(t['seq']) + 1}"
    if tp == "discuss":
        return f"discuss{t.get('pass', 1)}"
    return tp


def reading_rows(g: GameData) -> list[dict]:
    rows = []
    crew_reads = [(t["seq"], t["player"], stated_probs(g, t)) for t in g.turns
                  if t.get("turn_phase") in SUSPICION_PHASES and not t.get("fallback")
                  and g.role.get(t["player"]) == "crew" and (t.get("action") or {}).get("suspicion")]
    for t in g.turns:
        if t.get("turn_phase") not in SUSPICION_PHASES or t.get("fallback"):
            continue
        if not (t.get("action") or {}).get("suspicion"):
            continue
        p, r, c = t["player"], t["round"], g.cutoff(t)
        stated = stated_probs(g, t)
        alive = g.alive_at_round(r)
        ma = g.moles_alive_at_round(r)
        n_rated = len(stated)
        base = ma / n_rated if n_rated else None
        truth = {n: g.truth[n] for n in stated}
        inp = g.solver_inputs(c, p)
        post = g.posterior(c, p)
        pub = g.posterior(c, "table")
        solver = {n: post.get(n, 0.0) for n in stated}
        public = {n: pub.get(n, 0.0) for n in stated}
        basep = {n: base for n in stated}
        row = base_fields(g, "reading", p, r, t["seq"])
        row.update({
            "cutoff_seq": c, "turn_phase": t["turn_phase"], "pass": t.get("pass"), "stage": stage_of(g, t),
            "kind": t.get("suspicion_kind"), "n_rated": n_rated, "n_alive": len(alive), "moles_alive": ma,
            "rated_is_alive_others": sorted(stated) == sorted(n for n in alive if n != p),
            "base_rate": base, "stated": stated, "truth": truth, "solver": solver,
            "solver_consistent": post.consistent, "solver_worlds": post.worlds,
            "public": public, "public_consistent": pub.consistent, "public_worlds": pub.worlds,
            "own_real_clues": sum(1 for cl in inp["own_clues"] if cl.get("kind") != NONE),
            "public_cards_seen": len(inp["cards"]), "whisper_cards_seen": len(inp["pair_cards"]),
            "blown_jobs_seen": sum(1 for _, s in inp["jobs"] if s), "clean_jobs_seen": sum(1 for _, s in inp["jobs"] if not s),
            "players_revealed": len(inp["revealed"]),
            "stated_mean": mean(stated.values()),
            "brier_model": brier(stated, truth), "brier_solver": brier(solver, truth), "brier_base": brier(basep, truth),
            "log_model": log_score(stated, truth), "log_solver": log_score(solver, truth),
            "log_base": log_score(basep, truth),
            "brier_public": brier(public, truth),
        })
        row["read_gap"] = (row["brier_model"] - row["brier_solver"]) if row["kind"] == "belief" else None
        # Table read (moles): the crew's own latest stated suspicion, crew mean.
        target = target_n = None
        tr = {"tr_err_model": None, "tr_err_public": None, "tr_err_base": None, "table_read_gap": None,
              "tr_rated_with_target": None}
        if row["kind"] == "table_read":
            crew_in = [y for y in alive if g.role[y] == "crew"]
            latest = {}
            for s, y, probs in crew_reads:
                if s <= c and y in crew_in:
                    latest[y] = probs                      # in seq order: later overwrites earlier
            target, target_n = {}, {}
            for x in stated:
                vals = [latest[y][x] for y in crew_in if y != x and y in latest and x in latest[y]]
                target[x] = mean(vals) if vals else None
                target_n[x] = len(vals)
            have = [x for x in stated if target[x] is not None]
            if have:
                tr = {"tr_err_model": mean((stated[x] - target[x]) ** 2 for x in have),
                      "tr_err_public": mean((public[x] - target[x]) ** 2 for x in have),
                      "tr_err_base": mean((base - target[x]) ** 2 for x in have),
                      "tr_rated_with_target": len(have)}
                tr["table_read_gap"] = tr["tr_err_model"] - tr["tr_err_public"]
            else:
                tr["tr_rated_with_target"] = 0
        row["target"] = target
        row["target_n"] = target_n
        row.update(tr)
        rows.append(row)
    return rows


def vote_rows(g: GameData) -> list[dict]:
    rows = []
    for t in g.turns_in(None, "vote", fallback=False):
        p, r, c = t["player"], t["round"], g.cutoff(t)
        vr = g.vote_result[r]
        alive = g.alive_at_round(r)
        target = t["action"]["vote"]
        valid = [n for n in alive if n != p]
        sus = (t.get("action") or {}).get("suspicion") or {}
        own_top = argmax_set(sus, valid)
        talk = [d for d in g.turns_in(r, "discuss") if not d.get("fallback")]
        accs = [(d["seq"], d["player"], d["action"].get("accuse")) for d in talk
                if d["action"].get("accuse") not in (None, NONE)]
        mine = [a for s, who, a in accs if who == p]
        last_accuse = mine[-1] if mine else None
        cnt = Counter(a for _, _, a in accs)
        most = argmax_set(cnt) if cnt else []
        ma = g.moles_alive_at_round(r)
        moles_in_valid = sum(1 for n in valid if n in g.moles)
        row = base_fields(g, "vote", p, r, t["seq"])
        row.update({
            "cutoff_seq": c, "target": target, "target_role": g.role.get(target), "hit_mole": target in g.moles,
            "eliminated": vr.get("eliminated"), "eliminated_role": vr.get("role"),
            "with_plurality": target == vr.get("eliminated"), "tiebreak": vr.get("tiebreak"),
            "n_alive": len(alive), "moles_alive": ma, "base_rate": moles_in_valid / len(valid) if valid else None,
            "own_top": own_top, "own_top_tied": len(own_top) > 1, "vote_matches_own_top": target in own_top if own_top else None,
            "last_accuse": last_accuse, "vote_matches_accuse": (target == last_accuse) if last_accuse else None,
            "most_accused": most, "vote_on_most_accused": (target in most) if most else None,
            "first_accused": accs[0][2] if accs else None,
            "vote_on_first_accused": (target == accs[0][2]) if accs else None,
            "solver": None, "solver_best": None, "solver_p_target": None, "solver_p_best": None,
            "vote_regret": None, "solver_best_hits_mole": None, "solver_consistent": None,
        })
        if g.role[p] == "crew":
            post = g.posterior(c, p)
            sol = {n: post.get(n, 0.0) for n in valid}
            best = argmax_set(sol, valid)
            row.update({"solver": sol, "solver_best": best, "solver_p_target": sol.get(target),
                        "solver_p_best": sol[best[0]], "vote_regret": sol[best[0]] - sol.get(target, 0.0),
                        "solver_best_hits_mole": sum(1 for b in best if b in g.moles) / len(best),
                        "solver_best_n": len(best), "solver_consistent": post.consistent})
        rows.append(row)
    return rows


def sabotage_rows(g: GameData) -> list[dict]:
    rows = []
    for t in g.turns_in(None, "job"):
        p, r, c = t["player"], t["round"], g.cutoff(t)
        team = list(g.job_pick[r]["team"])
        partners = [m for m in g.moles if m != p]
        partner_on = [m for m in partners if m in team]
        rs = g.round_start[r]
        clean_b, blown_b = rs["clean_jobs"], rs["blown_jobs"]
        pub = g.posterior(c, "table")
        inp = copy.deepcopy(g.solver_inputs(c, "table"))
        inp["jobs"].append((team, 1))
        pub_if = table_posterior(inp)
        script = "help" if any(g.seat[m] < g.seat[p] for m in partner_on) else "sabotage"
        jr = g.job_result[r]
        share, ncv, _ = crew_vote_share(g, r)
        vr = g.vote_result.get(r)
        choice = t["action"]["choice"]
        row = base_fields(g, "sabotage", p, r, t["seq"])
        row.update({
            "cutoff_seq": c, "team": team, "team_size": len(team), "partner_on_team": bool(partner_on),
            "partner_alive": any(m in g.alive_at_round(r) for m in partners),
            "choice": choice, "sabotaged": choice == "sabotage", "fallback": bool(t.get("fallback")),
            "clean_before": clean_b, "blown_before": blown_b,
            "wins_now": blown_b + 1 >= g.dials["sabotage_target"],
            "clean_would_win_for_crew": clean_b + 1 >= g.dials["clean_target"],
            "public_p_self_before": pub.get(p), "public_p_self_if_blown": pub_if.get(p),
            "exposure": pub_if.get(p) - pub.get(p), "public_consistent_before": pub.consistent,
            "public_consistent_if_blown": pub_if.consistent,
            "script_answer": script, "matches_script": choice == script,
            "job_blown": jr["blown"], "sabotages": jr["sabotages"],
            "crew_vote_share_on_moles": share, "crew_votes": ncv,
            "mole_eliminated_this_round": (vr is not None and vr.get("role") == "mole"),
            "self_eliminated_this_round": (vr is not None and vr.get("eliminated") == p),
            "vote_happened": vr is not None,
        })
        rows.append(row)
    return rows


def round_rows(g: GameData) -> list[dict]:
    rows = []
    for r in g.rounds:
        alive = g.alive_at_round(r)
        team = list(g.job_pick[r]["team"])
        jr = g.job_result[r]
        choices = (g.job_choices.get(r) or {}).get("choices") or {}
        vr = g.vote_result.get(r)
        share, ncv, kcv = crew_vote_share(g, r)
        blown = bool(jr["blown"])
        game_ended_at_job = vr is None
        if game_ended_at_job and g.end and g.end["rounds"] != r:
            raise ValueError(f"{g.game_id} round {r}: no vote but the game did not end that round")
        if not blown:
            getaway = 0.0
        elif game_ended_at_job:
            getaway = 1.0
        else:
            getaway = (1.0 - share) if share is not None else None
        for m in [n for n in alive if n in g.moles]:
            row = base_fields(g, "round", m, r, None)
            row.update({
                "moles_alive": g.moles_alive_at_round(r), "n_alive": len(alive),
                "self_on_team": m in team, "any_mole_on_team": any(x in g.moles for x in team),
                "self_sabotaged": choices.get(m) == "sabotage", "blown": blown, "sabotages": jr["sabotages"],
                "game_ended_at_job": game_ended_at_job, "crew_votes": ncv, "crew_votes_on_moles": kcv,
                "share": share, "getaway": getaway,
                "eliminated": vr.get("eliminated") if vr else None, "eliminated_role": vr.get("role") if vr else None,
                "self_eliminated": bool(vr) and vr.get("eliminated") == m,
            })
            rows.append(row)
    return rows


def build_rows(games: list[GameData]) -> list[dict]:
    rows = []
    for g in games:
        rows += reading_rows(g) + vote_rows(g) + sabotage_rows(g) + round_rows(g)
    return rows


# =========================================================================== output files

def flat(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        if isinstance(v, dict):
            continue
        if isinstance(v, (list, tuple)):
            if all(not isinstance(x, (dict, list)) for x in v):
                out[k] = ";".join(str(x) for x in v)
            continue
        out[k] = v
    return out


def write_rows(rows: list[dict], out: Path, batch: str):
    with open(out / f"decisions_{batch}.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    flats = [flat(r) for r in rows]
    cols = list(dict.fromkeys(k for r in flats for k in r))
    with open(out / f"decisions_{batch}.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in flats:
            w.writerow(r)


# =========================================================================== summary helpers

class T:
    """Markdown table builder where each cell is a bootstrapped pooled mean."""

    def __init__(self, boot: Boot):
        self.boot = boot

    def s(self, rows, fn) -> dict:
        return self.boot.mean((r["game_id"], fn(r)) for r in rows)

    def cell(self, rows, fn, base_n=None, pct=False, digits=3) -> str:
        st = self.s(rows, fn)
        txt = fmt_stat(st, digits=digits, pct=pct)
        if base_n is None or st["n"] != base_n:
            txt += f" (n={st['n']}, g={st['games']})"
        return txt


def table(headers, body) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in body]
    return out


def ngames(rows) -> int:
    return len({r["game_id"] for r in rows})


def b2f(x):
    return None if x is None else float(bool(x))


def by(rows, key):
    d = defaultdict(list)
    for r in rows:
        d[key(r)].append(r)
    return dict(sorted(d.items(), key=lambda kv: (str(type(kv[0])), kv[0])))


# =========================================================================== summary sections

def sec_header(batch, games, rows, boot) -> list[str]:
    cnt = Counter(r["row_type"] for r in rows)
    return [f"# Decision table summary: batch `{batch}`", "",
            f"{len(games)} finished games (only games with a `game_end`). Rows: "
            + ", ".join(f"{k} {v}" for k, v in sorted(cnt.items())) + ".", "",
            "**Intervals.** Every interval is a 95% percentile bootstrap that resamples whole games "
            f"({boot.n} resamples, fixed seed 20261110); every statistic is a pooled mean over decisions in "
            "the resampled games. Each number is printed with n (decisions) and g (games) - in a table, "
            "the row's `n` and `games` columns apply to every cell that has no `(n=, g=)` of its own. "
            "Where fewer than 5 games contribute, the cell says `too few` instead of an interval.", "",
            "**What the player could know.** All solver numbers use only events visible to that player "
            "(`log.visible_events`), up to a cutoff: for simultaneous phases (clue, job, vote, cut_vote, "
            "finale_choice) the seq just before the first turn of that phase in that round; for whisper "
            "steps (run in lockstep across pairs) the seq before the first turn of the step; for "
            "sequential phases (pick, discuss) seq-1.", "",
            "These are show games (seven seats, five models, two seated twice). docs/CLAIMS.md says show "
            "games support none of its claims; the numbers below describe this batch only.", ""]


def sec_a(rows, games, boot) -> list[str]:
    T_ = T(boot)
    crew = [r for r in rows if r["row_type"] == "reading" and r["kind"] == "belief"]
    L = ["## a. Read (crew readings)", "",
         "Brier = mean over rated players of (p - truth)^2. *model* = the stated suspicion, *solver* = the "
         "ideal reasoner from the reader's view at the cutoff, *base* = moles alive / players rated. "
         "`read_gap` = brier_model - brier_solver (the Read metric). *beats base* / *beats solver* = share "
         "of readings with a strictly lower Brier than that reference.", ""]

    def block(title, groups):
        body = []
        for k, rs in groups:
            n = len(rs)
            body.append([k, n, ngames(rs), T_.cell(rs, lambda r: r["brier_model"], n),
                         T_.cell(rs, lambda r: r["brier_solver"], n), T_.cell(rs, lambda r: r["brier_base"], n),
                         T_.cell(rs, lambda r: r["read_gap"], n),
                         T_.cell(rs, lambda r: b2f(r["brier_model"] < r["brier_base"]), n, pct=True),
                         T_.cell(rs, lambda r: b2f(r["brier_model"] < r["brier_solver"]), n, pct=True)])
        return table([title, "n", "games", "brier_model", "brier_solver", "brier_base", "read_gap",
                      "beats base", "beats solver"], body) + [""]

    L += block("all", [("all crew readings", crew)])
    L += block("round", list(by(crew, lambda r: r["round"]).items()))
    L += block("phase", [(p, [r for r in crew if r["turn_phase"] == p]) for p in SUSPICION_PHASES])
    L += block("stage", [(s, [r for r in crew if r["stage"] == s]) for s in STAGES])
    L += block("model", list(by(crew, lambda r: r["model"]).items()))
    L += ["Log scores (mean negative log likelihood, p clipped to [0.01, 0.99]):", ""]
    L += table(["set", "n", "games", "log_model", "log_solver", "log_base"],
               [["all crew readings", len(crew), ngames(crew), T_.cell(crew, lambda r: r["log_model"], len(crew)),
                 T_.cell(crew, lambda r: r["log_solver"], len(crew)), T_.cell(crew, lambda r: r["log_base"], len(crew))]])
    ties = sum(1 for r in crew if abs(r["brier_model"] - r["brier_solver"]) < 1e-12)
    incons = sum(1 for r in crew if not r["solver_consistent"])
    L += ["", f"Crew readings where model and solver Brier tie exactly: {ties} of {len(crew)}. Solver "
          f"inconsistent (fell back to reveals and jobs): {incons}. Readings whose rated set is not exactly "
          f"the other living players: {sum(1 for r in crew if not r['rated_is_alive_others'])}.", ""]
    L += reconcile(rows, games)
    return L


def reconcile(rows, games) -> list[str]:
    """Reproduce docs/pilot1_report.md section 5 (each crew player's LAST reading per round)."""
    from inside_job.report import game_readings
    crew = [r for r in rows if r["row_type"] == "reading" and r["kind"] == "belief"]
    last = {}
    for r in crew:
        last[(r["game_id"], r["round"], r["player"])] = r      # rows are in seq order per game
    sel = list(last.values())
    rep = [x for g in games for x in game_readings(g.events)]
    rep_by = {(x["game_id"], x["seq"]): x for x in rep}
    same_sel = sum(1 for r in sel if (r["game_id"], r["seq"]) in rep_by)
    d_ideal = [r for r in sel if (r["game_id"], r["seq"]) in rep_by
               and abs(rep_by[(r["game_id"], r["seq"])]["ideal"] - r["brier_solver"]) > 1e-12]
    d_model = [r for r in sel if (r["game_id"], r["seq"]) in rep_by
               and abs(rep_by[(r["game_id"], r["seq"])]["brier"] - r["brier_model"]) > 1e-12]
    # Over ALL readings and votes: does upto_seq = own seq (report's choice) change the solver?
    gm = {g.game_id: g for g in games}
    diff_all, diff_by_phase = 0, Counter()
    checked = Counter()
    for r in rows:
        if r["row_type"] not in ("reading",):
            continue
        g = gm[r["game_id"]]
        a = g.posterior(r["seq"], r["player"])
        b = g.posterior(r["cutoff_seq"], r["player"])
        checked[r["turn_phase"]] += 1
        if any(abs(a.get(n, 0) - b.get(n, 0)) > 1e-12 for n in r["stated"]) or a.consistent != b.consistent:
            diff_all += 1
            diff_by_phase[r["turn_phase"]] += 1
    L = ["### a.1 Reconciliation with docs/pilot1_report.md (section 5)", "",
         "Same selection as the report: each crew player's last non-fallback reading per round.", "",
         f"- Readings selected: {len(sel)} (report: 261); the same turns as `report.game_readings`: "
         f"{same_sel} of {len(rep)}.",
         f"- Crew Brier: {mean(r['brier_model'] for r in sel):.4f} (report: 0.162); solver ('ideal') Brier at "
         f"my cutoff: {mean(r['brier_solver'] for r in sel):.4f}; `game_readings` ideal (upto_seq = the turn's "
         f"own seq): {mean(x['ideal'] for x in rep):.4f} (report: 0.135).",
         f"- Selected readings whose solver Brier differs between the two cutoffs: {len(d_ideal)}; whose model "
         f"Brier differs: {len(d_model)}.",
         f"- Phases of the selected readings: "
         + ", ".join(f"{k} {v}" for k, v in sorted(Counter(r['turn_phase'] for r in sel).items())) + ".",
         f"- Over all {sum(checked.values())} readings (crew and mole), the solver posterior from the reader's "
         f"view differs between upto_seq = own seq and my cutoff in {diff_all} "
         + ("(" + ", ".join(f"{k} {v}" for k, v in sorted(diff_by_phase.items())) + ")" if diff_all else "")
         + ". `visible_to` makes every other player's vote turn (public part: reason and target) visible "
         "as soon as it is in the slice, so a cutoff at a vote turn's own seq 'sees' the earlier voters' "
         "votes, which the real prompt never did; the solver ignores vote turns (only cards, job results "
         "and reveals enter it), so this cannot move a solver number. `visible_to` also admits a partner mole's `job` turn (via "
         "`shared_with`) as soon as it is logged, so for the second mole on a team a seq-1 or own-seq cutoff "
         "would show the partner's choice, which the real prompt never did (see section h). A discuss "
         "turn's own seq adds the speaker's own tabled cards to their view; that is what the count above "
         "picks up.", ""]
    return L


def sec_b(rows, boot) -> list[str]:
    T_ = T(boot)
    crew = [r for r in rows if r["row_type"] == "reading" and r["kind"] == "belief"]
    pairs = [{"game_id": r["game_id"], "p": p, "t": r["truth"][n], "s": r["solver"][n]}
             for r in crew for n, p in r["stated"].items()]
    L = ["## b. Calibration of crew readings", "",
         "Unit: one stated probability (a reading of one player). Bins of stated suspicion; the last bin "
         "includes 100.", ""]
    body = []
    for b in range(10):
        ps = [x for x in pairs if min(9, int(round(x["p"] * 100)) // 10) == b]
        lab = f"{10 * b}-{10 * b + 9}" if b < 9 else "90-100"
        if not ps:
            body.append([lab, 0, 0, "-", "-", "-"])
            continue
        body.append([lab, len(ps), ngames(ps), f"{mean(x['p'] for x in ps):.3f}",
                     T_.cell(ps, lambda x: x["t"], len(ps)), T_.cell(ps, lambda x: x["s"], len(ps))])
    L += table(["stated", "n", "games", "mean stated", "observed mole share", "mean solver posterior"], body)
    L += ["", "Hedging: mean stated suspicion grouped by the solver's posterior for the same player at the "
          "same moment (reader's view).", ""]
    bands = [("solver >= 0.99", lambda s: s >= 0.99), ("solver <= 0.01", lambda s: s <= 0.01),
             ("0.01 < solver <= 1/3", lambda s: 0.01 < s <= 1 / 3),
             ("1/3 < solver <= 2/3", lambda s: 1 / 3 < s <= 2 / 3),
             ("2/3 < solver < 0.99", lambda s: 2 / 3 < s < 0.99)]
    body = []
    for lab, f in bands:
        ps = [x for x in pairs if f(x["s"])]
        if not ps:
            body.append([lab, 0, 0, "-", "-", "-"])
            continue
        body.append([lab, len(ps), ngames(ps), T_.cell(ps, lambda x: x["p"], len(ps)),
                     f"{mean(x['s'] for x in ps):.3f}", T_.cell(ps, lambda x: x["t"], len(ps))])
    L += table(["solver band", "n", "games", "mean stated", "mean solver", "observed mole share"], body) + [""]
    return L


def sec_c(rows, boot) -> list[str]:
    T_ = T(boot)
    votes = [r for r in rows if r["row_type"] == "vote"]
    L = ["## c. Votes", "",
         "Every non-fallback vote. *hit* = voted for a mole. *solver argmax hit* (crew only) = expected hit "
         "rate voting uniformly among the solver's most likely players. *base* = share of the voter's valid "
         "targets that are moles (random-vote hit rate; for a mole voter this counts their partner). "
         "*regret* = solver p(best) - solver p(target) (crew). *own top* = vote went to a player the voter "
         "rated highest in the same turn (ties count). *own accusation* = vote equals the voter's last "
         "accusation this round (only voters who accused). *most accused* = vote on a player with the most "
         "discussion accusations this round (ties count; only rounds with an accusation).", ""]
    groups = [("all", "all", votes)]
    for role in ("crew", "mole"):
        groups.append(("all", role, [v for v in votes if v["role"] == role]))
    for rnd, rs in by(votes, lambda r: r["round"]).items():
        for role in ("crew", "mole"):
            groups.append((rnd, role, [v for v in rs if v["role"] == role]))
    body = []
    for rnd, role, rs in groups:
        if not rs:
            continue
        n = len(rs)
        body.append([rnd, role, n, ngames(rs), T_.cell(rs, lambda r: b2f(r["hit_mole"]), n, pct=True),
                     T_.cell(rs, lambda r: r["solver_best_hits_mole"], n, pct=True),
                     T_.cell(rs, lambda r: r["base_rate"], n, pct=True),
                     T_.cell(rs, lambda r: r["vote_regret"], n),
                     T_.cell(rs, lambda r: b2f(r["vote_matches_own_top"]), n, pct=True),
                     T_.cell(rs, lambda r: b2f(r["vote_matches_accuse"]), n, pct=True),
                     T_.cell(rs, lambda r: b2f(r["vote_on_most_accused"]), n, pct=True)])
    L += table(["round", "role", "n", "games", "hit", "solver argmax hit", "base", "regret", "own top",
                "own accusation", "most accused"], body)
    # checks
    elim = {}
    for v in votes:
        elim[(v["game_id"], v["round"])] = v["eliminated_role"]
    crew = [v for v in votes if v["role"] == "crew"]
    L += ["", f"Check: {len(votes)} vote rows (expected 326 for pilot1); eliminations {len(elim)}, of which a "
          f"mole {sum(1 for x in elim.values() if x == 'mole')} (expected 32 of 54).",
          f"Crew votes with zero regret (on a solver-best player): {sum(1 for v in crew if v['vote_regret'] is not None and v['vote_regret'] < 1e-12)} of {len(crew)}; "
          f"crew votes where the solver's best set is a single player: {sum(1 for v in crew if v.get('solver_best_n') == 1)}; "
          f"own top suspicion tied: {sum(1 for v in votes if v['own_top_tied'])} of {len(votes)}.", ""]
    return L


def sec_d(rows, boot) -> list[str]:
    T_ = T(boot)
    sab = [r for r in rows if r["row_type"] == "sabotage"]
    real = [r for r in sab if not r["fallback"]]
    L = ["## d. Sabotage (job turns)", "",
         "Only moles on the team are asked; crew help automatically. **The solver gives no ideal answer for "
         "this decision**: the columns below (the scripted `smart` rule, how much a blown job would move the "
         "public posterior on this mole, what happened next) are the closest available references, not a "
         "correct answer. *script* = sabotage unless the partner is also on the team and sits in a lower "
         "seat, then help. *exposure* = public posterior on this mole if this job came back blown with one "
         "sabotage, minus the public posterior before.", "",
         f"Job turns: {len(sab)} (fallback {len(sab) - len(real)}).", ""]
    groups = [("all", real)] + [(f"round {k}", v) for k, v in by(real, lambda r: r["round"]).items()]
    groups += [("wins_now = true", [r for r in real if r["wins_now"]]),
               ("wins_now = false", [r for r in real if not r["wins_now"]]),
               ("partner on team", [r for r in real if r["partner_on_team"]]),
               ("partner not on team", [r for r in real if not r["partner_on_team"]]),
               ("clean job would win for crew", [r for r in real if r["clean_would_win_for_crew"]])]
    body = []
    for lab, rs in groups:
        if not rs:
            body.append([lab, 0, 0, "-", "-", "-"])
            continue
        n = len(rs)
        body.append([lab, n, ngames(rs), T_.cell(rs, lambda r: b2f(r["sabotaged"]), n, pct=True),
                     T_.cell(rs, lambda r: b2f(r["matches_script"]), n, pct=True),
                     T_.cell(rs, lambda r: r["exposure"], n)])
    L += table(["decisions", "n", "games", "sabotage rate", "agrees with script", "mean exposure"], body)
    L += ["", "Exposure by choice:", ""]
    body = []
    for ch in ("sabotage", "help"):
        rs = [r for r in real if r["choice"] == ch]
        if rs:
            body.append([ch, len(rs), ngames(rs), T_.cell(rs, lambda r: r["exposure"], len(rs)),
                         T_.cell(rs, lambda r: r["public_p_self_before"], len(rs)),
                         T_.cell(rs, lambda r: b2f(r["self_eliminated_this_round"]), len(rs), pct=True)])
    L += table(["choice", "n", "games", "mean exposure", "public p(self) before", "self voted out this round"], body)
    L += ["", "Every job decision:", ""]
    body = []
    for r in sab:
        body.append([r["seed"], r["round"], r["player"], r["model"], r["team_size"], r["partner_on_team"],
                     r["choice"] + (" (fallback)" if r["fallback"] else ""), r["script_answer"], r["wins_now"],
                     f"{r['public_p_self_before']:.2f}", f"{r['exposure']:+.2f}",
                     f"{'blown' if r['job_blown'] else 'clean'} ({r['sabotages']})",
                     "-" if r["crew_vote_share_on_moles"] is None else f"{r['crew_vote_share_on_moles']:.2f}",
                     r["self_eliminated_this_round"]])
    L += table(["seed", "round", "mole", "model", "team", "partner on", "choice", "script", "wins now",
                "p(self)", "exposure", "job", "crew share on moles", "self out"], body) + [""]
    return L


def sec_e(rows, boot) -> list[str]:
    T_ = T(boot)
    rr = [r for r in rows if r["row_type"] == "round"]
    scored = [r for r in rr if r["getaway"] is not None]
    L = ["## e. Getaway (Bluff unit: one mole, one round)", "",
         "*getaway* = (1 if the job was blown, else 0) x (1 - share of the crew's non-fallback votes on any "
         "mole that round); a blown job that ends the game with no vote scores 1; a clean job scores 0. "
         f"Rows: {len(rr)}; scored {len(scored)}.", ""]
    groups = [("all", scored)] + [(f"round {k}", v) for k, v in by(scored, lambda r: r["round"]).items()]
    groups += [(f"`{k}`", v) for k, v in by(scored, lambda r: r["model"]).items()]
    groups += [("self on team", [r for r in scored if r["self_on_team"]]),
               ("self not on team", [r for r in scored if not r["self_on_team"]]),
               ("no mole on team", [r for r in scored if not r["any_mole_on_team"]])]
    body = []
    for lab, rs in groups:
        if not rs:
            continue
        n = len(rs)
        body.append([lab, n, ngames(rs), T_.cell(rs, lambda r: b2f(r["getaway"] == 0), n, pct=True),
                     T_.cell(rs, lambda r: b2f(r["getaway"] == 1), n, pct=True),
                     T_.cell(rs, lambda r: r["getaway"], n),
                     T_.cell(rs, lambda r: b2f(r["blown"]), n, pct=True)])
    L += table(["mole rounds", "n", "games", "getaway = 0", "getaway = 1", "mean getaway", "job blown"], body)
    L += ["", "Getaway values that are neither 0 nor 1: "
          + (", ".join(f"{v:.2f}" for v in sorted(r["getaway"] for r in scored if 0 < r["getaway"] < 1)) or "none")
          + ".", ""]
    return L


def sec_f(rows, boot) -> list[str]:
    T_ = T(boot)
    moles = [r for r in rows if r["row_type"] == "reading" and r["kind"] == "table_read"]
    sc = [r for r in moles if r["tr_err_model"] is not None]
    L = ["## f. Table read (mole readings)", "",
         "*target* for each rated player X = mean over crew still in (excluding X) of that crew member's "
         "latest non-fallback belief of X before this turn's cutoff. tr_err = mean over rated players with a "
         "target of (value - target)^2, for the mole's stated read (*model*), the solver's public posterior "
         "(*public*) and the constant base rate (*base* = moles alive / players rated, what a crew member "
         "with no information would say and the engine's fallback value). gap = tr_err_model - tr_err_public. "
         "A mole does not rate themselves, so how much the crew suspect the reader is never part of this score. "
         f"Mole readings: {len(moles)}; with a target: {len(sc)} (no crew reading exists before the first "
         "clue turn of the game, so round 1 clue readings have none).", ""]
    groups = [("all", sc)] + [(f"round {k}", v) for k, v in by(sc, lambda r: r["round"]).items()]
    groups += [(p, [r for r in sc if r["turn_phase"] == p]) for p in SUSPICION_PHASES]
    groups += [(f"`{k}`", v) for k, v in by(sc, lambda r: r["model"]).items()]
    body = []
    for lab, rs in groups:
        if not rs:
            continue
        n = len(rs)
        body.append([lab, n, ngames(rs), T_.cell(rs, lambda r: r["tr_err_model"], n),
                     T_.cell(rs, lambda r: r["tr_err_public"], n), T_.cell(rs, lambda r: r["tr_err_base"], n),
                     T_.cell(rs, lambda r: r["table_read_gap"], n),
                     T_.cell(rs, lambda r: b2f(r["tr_err_model"] < r["tr_err_base"]), n, pct=True)])
    L += table(["mole readings", "n", "games", "tr_err_model", "tr_err_public", "tr_err_base", "gap",
                "beats base"], body) + [""]
    return L


# ---------------------------------------------------------------------------- g. feature audit

def sec_g(rows, games, boot) -> list[str]:
    T_ = T(boot)
    L = ["## g. Feature audit", "", "Counts only; what the logs show.", ""]

    # whispers
    req, pairs_by_round = [], defaultdict(list)
    wcards = Counter()
    for g in games:
        for r in g.rounds:
            rq = (g.whisper_requests.get(r) or {}).get("requests") or {}
            for a, b in rq.items():
                req.append({"game_id": g.game_id, "role": g.role[a], "none": b == NONE,
                            "mutual": b != NONE and rq.get(b) == a, "to_partner": b in g.moles and a in g.moles and a != b})
            pairs_by_round[r].append(len((g.whisper_pairs.get(r) or {}).get("pairs") or []))
        for t in g.turns_in(None, "whisper", fallback=False):
            cs = (t.get("checks") or {}).get("clue_cards") or []
            wcards["turns"] += 1
            wcards["turns_with_cards"] += bool(cs)
            wcards["cards"] += len(cs)
    L += ["**Whisper requests.**", ""]
    body = []
    for role in ("crew", "mole"):
        rs = [x for x in req if x["role"] == role]
        body.append([role, len(rs), T_.cell(rs, lambda x: b2f(x["none"]), len(rs), pct=True),
                     T_.cell(rs, lambda x: b2f(x["mutual"]), len(rs), pct=True),
                     sum(x["to_partner"] for x in rs)])
    L += table(["requester", "requests", "'none'", "mutual", "mole asked partner"], body)
    L += ["", "Pairs formed per round: " + "; ".join(
        f"round {r}: mean {mean(v):.2f} over {len(v)} games ({dict(sorted(Counter(v).items()))})"
        for r, v in sorted(pairs_by_round.items())) + ".",
        f"Whisper turns (non-fallback): {wcards['turns']}; with a clue card: {wcards['turns_with_cards']}; "
        f"cards shown: {wcards['cards']}.", ""]

    # belief movement
    crew_r = [r for r in rows if r["row_type"] == "reading" and r["kind"] == "belief"]
    seqs = defaultdict(dict)
    for r in crew_r:
        seqs[(r["game_id"], r["round"], r["player"])][r["stage"]] = r
    trans = defaultdict(list)
    for key, st in seqs.items():
        have = [s for s in STAGES if s in st]
        for a, b in zip(have, have[1:]):
            ra, rb = st[a], st[b]
            common = [n for n in ra["stated"] if n in rb["stated"]]
            if not common:
                continue
            trans[f"{a} -> {b}"].append({
                "game_id": key[0],
                "abs": mean(abs(rb["stated"][n] - ra["stated"][n]) for n in common),
                "changed": any(rb["stated"][n] != ra["stated"][n] for n in common),
                "dbm": rb["brier_model"] - ra["brier_model"], "dbs": rb["brier_solver"] - ra["brier_solver"]})
    L += ["**Belief movement (crew).** Consecutive non-fallback readings of the same crew player in the "
          "same round, in the order clue, whisper 1, whisper 2, discuss pass 1, discuss pass 2, vote "
          "(a missing stage is skipped). *|change|* = mean absolute change in stated probability over the "
          "rated players; *dBrier* = later Brier minus earlier (negative = moved towards the truth); "
          "*dBrier solver* = the same for the solver over the same step (the information that arrived). "
          "Note the job result arrives between the whisper/clue readings and discuss pass 1.", ""]
    order = sorted(trans, key=lambda k: (STAGES.index(k.split(" -> ")[0]), STAGES.index(k.split(" -> ")[1])))
    body = []
    for k in order:
        rs = trans[k]
        n = len(rs)
        body.append([k, n, ngames(rs), T_.cell(rs, lambda x: x["abs"], n),
                     T_.cell(rs, lambda x: b2f(x["changed"]), n, pct=True),
                     T_.cell(rs, lambda x: x["dbm"], n), T_.cell(rs, lambda x: x["dbs"], n)])
    L += table(["step", "n", "games", "|change|", "any change", "dBrier model", "dBrier solver"], body) + [""]

    # second discussion pass
    flips, vote_p2 = [], []
    for g in games:
        votes = {(t["round"], t["player"]): t["action"]["vote"] for t in g.turns_in(None, "vote", fallback=False)}
        for r in g.rounds:
            d = g.turns_in(r, "discuss", fallback=False)
            p1 = {t["player"]: t["action"].get("accuse") for t in d if t.get("pass") == 1}
            p2 = {t["player"]: t["action"].get("accuse") for t in d if t.get("pass") == 2}
            for p in p1:
                if p in p2:
                    flips.append({"game_id": g.game_id, "changed": p1[p] != p2[p], "role": g.role[p],
                                  "none_both": p1[p] == NONE and p2[p] == NONE})
                    v = votes.get((r, p))
                    if v is not None:
                        vote_p2.append({"game_id": g.game_id, "p2_not_p1": v == p2[p] and v != p1[p],
                                        "p1_not_p2": v == p1[p] and v != p2[p], "both": v == p1[p] == p2[p]})
    L += ["**Second discussion pass.**", ""]
    body = [[role, len(rs), T_.cell(rs, lambda x: b2f(x["changed"]), len(rs), pct=True),
             T_.cell(rs, lambda x: b2f(x["none_both"]), len(rs), pct=True)]
            for role, rs in (("all", flips), ("crew", [x for x in flips if x["role"] == "crew"]),
                             ("mole", [x for x in flips if x["role"] == "mole"]))]
    L += table(["players (player-rounds with both passes)", "n", "accusation changes pass 1 -> 2",
                "'none' in both passes"], body)
    n = len(vote_p2)
    L += ["", f"Votes by players who spoke in both passes: {n}. Match the pass-2 accusation but not pass 1: "
          f"{T_.cell(vote_p2, lambda x: b2f(x['p2_not_p1']), n, pct=True)}; match pass 1 but not pass 2: "
          f"{T_.cell(vote_p2, lambda x: b2f(x['p1_not_p2']), n, pct=True)}; match both: "
          f"{T_.cell(vote_p2, lambda x: b2f(x['both']), n, pct=True)}.", ""]

    # challenges and accusations
    ch_turns, ch_ids, acc = [], [], []
    for g in games:
        spk = g.statement_speaker()
        sid_seq = {t["statement_id"]: t["seq"] for t in g.turns if t.get("statement_id")}
        for t in g.turns_in(None, "discuss", fallback=False):
            a = t["action"]
            ids = a.get("challenges") or []
            ch_turns.append({"game_id": g.game_id, "role": g.role[t["player"]], "uses": bool(ids)})
            pool = [s for s, q in sid_seq.items() if q < t["seq"] and s.startswith(f"R{t['round']}-")
                    and spk[s] != t["player"]]
            base = mean(1.0 if spk[s] in g.moles else 0.0 for s in pool) if pool else None
            for s in ids:
                ch_ids.append({"game_id": g.game_id, "role": g.role[t["player"]], "on_mole": spk.get(s) in g.moles,
                               "base": base})
            ac = a.get("accuse")
            alive = g.alive_at_round(t["round"])
            others = [n for n in alive if n != t["player"]]
            acc.append({"game_id": g.game_id, "role": g.role[t["player"]], "uses": ac not in (None, NONE),
                        "on_mole": (ac in g.moles) if ac not in (None, NONE) else None,
                        "base": (sum(1 for n in others if n in g.moles) / len(others)) if ac not in (None, NONE) else None,
                        "on_partner": (ac in g.moles) if g.role[t["player"]] == "mole" and ac not in (None, NONE) else None})
    L += ["**`challenges` and `accuse` (discussion turns, non-fallback).** *base* = share of the possible "
          "targets that were moles (for challenges: statements by others earlier this round; for accuse: "
          "the other living players).", ""]
    body = []
    for role in ("crew", "mole"):
        ct = [x for x in ch_turns if x["role"] == role]
        ci = [x for x in ch_ids if x["role"] == role]
        ac = [x for x in acc if x["role"] == role]
        aon = [x for x in ac if x["uses"]]
        body.append([role, len(ct), T_.cell(ct, lambda x: b2f(x["uses"]), len(ct), pct=True), len(ci),
                     T_.cell(ci, lambda x: b2f(x["on_mole"]), len(ci), pct=True) if ci else "-",
                     T_.cell(ci, lambda x: x["base"], len(ci), pct=True) if ci else "-",
                     T_.cell(ac, lambda x: b2f(x["uses"]), len(ac), pct=True),
                     T_.cell(aon, lambda x: b2f(x["on_mole"]), len(aon), pct=True) if aon else "-",
                     T_.cell(aon, lambda x: x["base"], len(aon), pct=True) if aon else "-"])
    L += table(["speaker", "discuss turns", "uses challenges", "challenge ids", "aimed at a mole's statement",
                "base", "accuses someone", "accusation on a mole", "base"], body) + [""]

    # clue cards
    cards = Counter()
    for g in games:
        for t in g.turns:
            if t.get("turn_phase") not in ("discuss", "whisper") or t.get("fallback"):
                continue
            where = "tabled" if t["turn_phase"] == "discuss" else "whispered"
            for c in (t.get("checks") or {}).get("clue_cards") or []:
                cards[(where, g.role[t["player"]], "real" if c["held"] else "fake",
                       "true" if c["true_in_world"] else "false")] += 1
    L += ["**Clue cards** (engine checks: real = the speaker holds that clue; true = true in the actual world).", ""]
    body = []
    for where in ("tabled", "whispered"):
        for role in ("crew", "mole"):
            k = {f"{h}/{tw}": cards[(where, role, h, tw)] for h in ("real", "fake") for tw in ("true", "false")}
            body.append([where, role, sum(k.values()), k["real/true"], k["real/false"], k["fake/true"], k["fake/false"]])
    L += table(["where", "role", "cards", "real, true", "real, false", "fake, true", "fake, false"], body) + [""]
    held = Counter()
    for g in games:
        for e in g.clue_events:
            held[(g.role[e["player"]], e["clue"]["kind"] != NONE)] += 1
    L += [f"Clues dealt (real, non-'none'): crew {held[('crew', True)]}, mole {held[('mole', True)]}; "
          f"'no intel': crew {held[('crew', False)]}, mole {held[('mole', False)]}.", ""]

    # job claims
    jc = Counter()
    for g in games:
        for t in g.turns_in(None, "discuss", fallback=False):
            claim = t["action"].get("job_claim")
            on_team = t["player"] in g.job_pick[t["round"]]["team"]
            actual = ((g.job_choices.get(t["round"]) or {}).get("choices") or {}).get(t["player"])
            jc[(g.role[t["player"]], on_team, claim, actual)] += 1
    L += ["**`job_claim`** (discussion turns; actual = the engine's job choice; crew always help).", ""]
    body = [[role, "yes" if on else "no", claim, actual or "-", n]
            for (role, on, claim, actual), n in sorted(jc.items(), key=lambda kv: tuple(str(x) for x in kv[0]))]
    L += table(["role", "on team", "claimed", "actual", "turns"], body) + [""]

    # The Cut
    cut_votes, cuts = [], []
    for g in games:
        cr = next((e for e in g.events if e["type"] == "cut_result"), None)
        if not cr:
            continue
        surv = list(cr["tally"])
        rec, rec_rev = {}, {}
        revealed = {vr["eliminated"] for vr in g.vote_result.values() if vr.get("role") == "mole"}
        for n in surv:
            rec[n] = sum(1 for vr in g.vote_result.values() if (vr.get("votes") or {}).get(n) in g.moles)
            rec_rev[n] = sum(1 for vr in g.vote_result.values() if (vr.get("votes") or {}).get(n) in revealed)
        fb = {t["player"] for t in g.turns_in(None, "cut_vote") if t.get("fallback")}
        for v, tg in cr["votes"].items():
            if v in fb:
                continue
            opts = [n for n in surv if n != v]
            top = max(rec[n] for n in opts)
            cut_votes.append({"game_id": g.game_id, "best": rec[tg] == top,
                              "base": sum(1 for n in opts if rec[n] == top) / len(opts),
                              "unique_best": sum(1 for n in opts if rec[n] == top) == 1})
        top2 = sorted(rec.values(), reverse=True)[:2]
        cuts.append({"game_id": g.game_id, "fin_top": sorted((rec[f] for f in cr["finalists"]), reverse=True) == top2,
                     "tiebreak": cr.get("tiebreak"), "differs": rec != rec_rev, "n": len(surv)})
    n = len(cut_votes)
    uniq = [x for x in cut_votes if x["unique_best"]]
    L += ["**The Cut.** Record = votes the player cast for a mole (as `engine.vote_record` counts it: the "
          "target's true role, whether or not revealed).", "",
          f"Cuts held: {len(cuts)} (survivors: {dict(sorted(Counter(c['n'] for c in cuts).items()))}). "
          f"Cut votes: {n}. On a candidate with the best record among the voter's options: "
          f"{T_.cell(cut_votes, lambda x: b2f(x['best']), n, pct=True)}; expected if random: "
          f"{T_.cell(cut_votes, lambda x: x['base'], n, pct=True)}. "
          f"Where exactly one option had the best record: {T_.cell(uniq, lambda x: b2f(x['best']), len(uniq), pct=True)}"
          + (f" vs random {T_.cell(uniq, lambda x: x['base'], len(uniq), pct=True)}" if uniq else "") + ".",
          f"Finalists are the two best records: {sum(c['fin_top'] for c in cuts)} of {len(cuts)}. Tiebreaks: "
          f"{dict(Counter(str(c['tiebreak']) for c in cuts))}. Cuts where counting only *revealed* moles "
          f"would change some record: {sum(c['differs'] for c in cuts)}.", ""]

    # finale
    fins = Counter()
    outs = Counter()
    for g in games:
        fr = next((e for e in g.events if e["type"] == "finale_result"), None)
        if not fr:
            continue
        for n in fr["finalists"]:
            fins[(fr["stated"].get(n), fr["choices"][n])] += 1
        outs["/".join(sorted(fr["choices"].values()))] += 1
    L += ["**Finale choices.** stated -> chosen: "
          + ", ".join(f"{a} -> {b}: {v}" for (a, b), v in sorted(fins.items()))
          + ". Outcomes: " + ", ".join(f"{k} {v}" for k, v in sorted(outs.items())) + ".", ""]

    # truncation and fallbacks
    tr = defaultdict(Counter)
    fbk = Counter()
    for g in games:
        for t in g.turns:
            if t.get("fallback"):
                fbk[(t["turn_phase"], t["model"], t.get("fallback_reason"))] += 1
                continue
            c = tr[t["model"]]
            c["turns"] += 1
            c["truncated"] += bool(t.get("truncated"))
            for f in t.get("truncated_fields") or []:
                c[f] += 1
    L += ["**Truncation** (non-fallback turns trimmed at the hard word cap).", ""]
    body = [[f"`{m}`", c["turns"], c["truncated"], c["confessional"], c["public"], c["memory"], c["claims"]]
            for m, c in sorted(tr.items())]
    L += table(["model", "turns", "truncated", "confessional", "public", "memory", "claims"], body)
    L += ["", "**Fallbacks** (turns that fell back to the documented default): "
          + (", ".join(f"{p} `{m}` ({why}): {n}" for (p, m, why), n in sorted(fbk.items())) or "none") + ".", ""]
    return L


# ---------------------------------------------------------------------------- h. raw material

def sec_h(games, rebuild_note: str) -> list[str]:
    multi = Counter()
    kinds = Counter()
    detail = []
    for g in games:
        for e in g.events:
            if e["type"] not in ("turn", "recap"):
                continue
            att = e.get("attempts") or 1
            if att <= 1:
                continue
            ks = e.get("error_kinds") if e["type"] == "turn" else [e.get("error_kind")]
            model = e.get("model")
            multi[(e["type"], e.get("turn_phase"), model)] += 1
            for k in ks or ["?"]:
                kinds[(k, model)] += 1
            detail.append((g.seed, e["seq"], e.get("turn_phase") or e["type"], model, att, ks,
                           [(r or "")[:90] for r in (e.get("rejections") or [])], e.get("fallback")))
    L = ["## h. Raw material: what a turn's log record keeps", "",
         "From `engine.ask` / `engine.write_turn`, `llm.py` and `log.py` (read, not run):", "",
         "Kept on every `turn` event: player, model (requested id), turn_phase, round, seq, ts, confessional, "
         "public, claims, memory, action (the parsed `move`), suspicion_kind, checks (discuss/whisper), "
         "statement_id, truncated, truncated_fields, fallback, fallback_reason, attempts, served_model, usage "
         "(summed over all attempts), latency_s (summed), rejections (one reason string per failed attempt), "
         "error_kinds (one per failed attempt), blocked (count), partner / pass / shared_with.", "",
         "Not kept anywhere in the log:", "",
         "- the system prompt (built once per player in `setup`, held in `Game.system_prompts`, never logged);",
         "- the turn prompt text (`prepare` builds it and passes it to the client; never logged);",
         "- the JSON schema sent with `--json-schema` (`turn_schema(phase, ctx)`; never logged);",
         "- `ctx` (others, order, challengeable ids, team, partner, index, pass ...), which the prompt and "
         "schema are built from;",
         "- the raw CLI stdout (`parse_cli_output` keeps `raw_text` on the `LLMReply`; the engine drops it);",
         "- the reply text of a failed attempt (rejected, invalid, blocked or timed out): only the reason "
         "string survives, and `llm.parse_cli_output` cuts CLI error text to 300 characters;",
         "- the text before word-cap trimming (`clean_reply` trims; only `truncated_fields` records that it "
         "happened, not what was cut);",
         "- thinking text (the CLI's JSON carries usage counts only; `usage.thinking` is a token count);",
         "- the retry prompt suffix (`\\n\\nYour previous reply was rejected: <reason>. Reply again with valid "
         "JSON.`): not logged, but reconstructible from `rejections` for invalid/cli failures; blocked "
         "retries reuse the identical prompt;",
         "- per-attempt usage, latency and served model (only sums / the last non-null served model);",
         "- the CLI's own internal structured-output retries (`error_max_structured_output_retries ... after "
         "5 attempts`): those five inner attempts are invisible, counted as one failed engine attempt.", "",
         "### Prompt rebuild", "", rebuild_note, "",
         "### Turns with more than one attempt", "",
         f"Turns/recaps with attempts > 1: {sum(multi.values())}. By error kind and model (one count per "
         "failed attempt): " + ", ".join(f"{k} `{m}`: {v}" for (k, m), v in sorted(kinds.items())) + ".", ""]
    L += table(["seed", "seq", "phase", "model", "attempts", "error_kinds", "rejections (first 90 chars)", "fallback"],
               [[a, b, c, d, e, f, "; ".join(x.replace("|", "/") for x in r), h] for a, b, c, d, e, f, r, h in detail])
    L += ["", "Recorded about each failed attempt: its reason string (`rejections[i]`) and kind "
          "(`error_kinds[i]`). Not recorded: the reply that failed, its usage, latency or served model "
          "separately, and the prompt it was answering.", ""]
    return L


def rebuild_note_for(games) -> str:
    from common import attempt_rebuild
    return attempt_rebuild(games)


# =========================================================================== self-test

def synthetic_log() -> list[dict]:
    """A hand-built 5-player game (moles D, E; sabotage_target 2) with known answers."""
    ev: list[dict] = []
    names = ["A", "B", "C", "D", "E"]
    moles = {"D", "E"}

    def w(**kw):
        kw = dict(seq=len(ev), ts="", game_id="synthetic", **kw)
        ev.append(kw)
        return kw

    def turn(r, tp, p, action, **extra):
        phase = {"cut_pitch": "cut"}.get(tp, tp)
        f = dict(round=r, phase=phase, type="turn", vis="engine", player=p, model=f"model-{p}", turn_phase=tp,
                 confessional="", public="", claims=[], memory="", action=action, statement_id=None,
                 truncated=False, truncated_fields=[], fallback=False, attempts=1, rejections=[], error_kinds=[],
                 blocked=0, fallback_reason=None, usage={}, latency_s=0.0, served_model=f"model-{p}")
        if "suspicion" in action:
            f["suspicion_kind"] = "table_read" if p in moles else "belief"
        f.update(extra)
        return w(**f)

    cfg = {"game": {"num_moles": 2, "clues_per_round": 1, "clue_strength": "weak", "clue_recipients": 1,
                    "clue_recipients_spread": 0, "max_rounds": 0, "job_size": 3, "job_size_small": 2,
                    "clean_target": 3, "sabotage_target": 2, "whispers": True, "whisper_pairs_max": 2,
                    "whisper_exchanges": 1, "discussion_passes": 1, "finale_exchanges": 1, "pot": 100,
                    "anonymise": False}}
    w(round=0, phase="setup", type="game_start", vis="engine", seed=99, config=cfg, batch="selftest",
      players=[{"name": n, "model": f"model-{n}", "model_name": n, "seat": i, "role": "mole" if n in moles else "crew"}
               for i, n in enumerate(names)], moles=["D", "E"], mole_seats=[3, 4], first_leader="A")
    w(round=0, phase="setup", type="table", vis="public", seats=names, num_moles=2, pot=100)
    for n in names:
        w(round=0, phase="setup", type="role", vis="private", player=n, role="mole" if n in moles else "crew",
          partners=[m for m in moles if m != n] if n in moles else [])
    # ---- round 1
    w(round=1, phase="clue", type="round_start", vis="public", leader="A", alive=names, clean_jobs=0, blown_jobs=0)
    w(round=1, phase="clue", type="clue_deal", vis="engine", recipients=["A"], k=1)
    for n in names:
        clue = ({"kind": "not_mole", "players": ["B"], "text": "B is not a mole."} if n == "A"
                else {"kind": "none", "players": [], "text": "No new intel this round."})
        w(round=1, phase="clue", type="clue", vis="private", player=n, clue=clue)

    def S(p, vals):
        return {o: v for o, v in zip([n for n in names if n != p], vals)}
    alive1 = names
    req = {"A": "B", "B": "A", "C": "none", "D": "none", "E": "none"}
    clue_s = {"A": [10, 40, 40, 40], "B": [30, 30, 50, 50], "C": [40, 40, 40, 40], "D": [30, 30, 30, 20],
              "E": [30, 30, 30, 20]}
    for n in alive1:
        turn(1, "clue", n, {"whisper_with": req[n], "suspicion": S(n, clue_s[n])})
    w(round=1, phase="whisper", type="whisper_requests", vis="engine", requests=req)
    w(round=1, phase="whisper", type="whisper_pairs", vis="public", pairs=[["A", "B"]])
    turn(1, "whisper", "A", {"clue_cards": [], "suspicion": S("A", [10, 40, 40, 40])}, partner="B", public="hi")
    turn(1, "whisper", "B", {"clue_cards": [], "suspicion": S("B", [20, 30, 50, 50])}, partner="A", public="hi")
    turn(1, "pick", "A", {"team": ["A", "D", "E"]}, public="team", statement_id="R1-S1")
    w(round=1, phase="pick", type="job_pick", vis="public", leader="A", team=["A", "D", "E"], job_name="x")
    turn(1, "job", "D", {"choice": "sabotage"}, shared_with=["E"])
    turn(1, "job", "E", {"choice": "help"}, shared_with=["D"])
    w(round=1, phase="job", type="job_choices", vis="engine", choices={"A": "help", "D": "sabotage", "E": "help"})
    w(round=1, phase="job", type="job_result", vis="public", team=["A", "D", "E"], sabotages=1, blown=True,
      clean_jobs=0, blown_jobs=1)
    disc = [("B", "D", [25, 20, 60, 50], []), ("C", "D", [45, 40, 60, 50], []), ("D", "A", [50, 30, 30, 30], []),
            ("E", "A", [50, 30, 30, 30], []),
            ("A", "D", [20, 40, 60, 50], [{"kind": "not_mole", "players": ["B"], "k": 0}])]
    for i, (p, acc, vals, cards) in enumerate(disc):
        turn(1, "discuss", p, {"accuse": acc, "challenges": [], "clue_cards": cards, "job_claim": "none",
                               "suspicion": S(p, vals)}, statement_id=f"R1-S{i + 2}", public="talk", **{"pass": 1})
    votes = {"A": "D", "B": "E", "C": "A", "D": "A", "E": "A"}
    vote_s = {"A": [90, 90, 90, 90], "B": [90, 90, 90, 90], "C": [90, 90, 90, 90], "D": [60, 30, 30, 30],
              "E": [60, 30, 30, 30]}
    for n in alive1:
        turn(1, "vote", n, {"vote": votes[n], "suspicion": S(n, vote_s[n])}, public="v")
    w(round=1, phase="vote", type="vote_result", vis="public", votes=votes, tally={"A": 3, "D": 1, "E": 1},
      tied=[], tiebreak=None, eliminated="A", role="crew")
    w(round=1, phase="recap", type="recap", vis="public", text="")
    # ---- round 2 (A out; team of 2; a blown job ends it at sabotage_target 2)
    alive2 = ["B", "C", "D", "E"]
    w(round=2, phase="clue", type="round_start", vis="public", leader="B", alive=alive2, clean_jobs=0, blown_jobs=1)
    w(round=2, phase="clue", type="clue_deal", vis="engine", recipients=[], k=0)
    for n in alive2:
        w(round=2, phase="clue", type="clue", vis="private", player=n,
          clue={"kind": "none", "players": [], "text": "No new intel this round."})
    for n in alive2:
        turn(2, "clue", n, {"whisper_with": "none", "suspicion": {o: 50 for o in alive2 if o != n}})
    w(round=2, phase="whisper", type="whisper_requests", vis="engine", requests={n: "none" for n in alive2})
    w(round=2, phase="whisper", type="whisper_pairs", vis="public", pairs=[])
    turn(2, "pick", "B", {"team": ["B", "D"]}, public="team", statement_id="R2-S1")
    w(round=2, phase="pick", type="job_pick", vis="public", leader="B", team=["B", "D"], job_name="y")
    turn(2, "job", "D", {"choice": "sabotage"}, shared_with=["E"])
    w(round=2, phase="job", type="job_choices", vis="engine", choices={"B": "help", "D": "sabotage"})
    w(round=2, phase="job", type="job_result", vis="public", team=["B", "D"], sabotages=1, blown=True,
      clean_jobs=0, blown_jobs=2)
    w(round=2, phase="end", type="game_end", vis="public", winner="moles", reason="sabotage", clean_jobs=0,
      blown_jobs=2, rounds=2, survivors=alive2, payouts={})
    return ev


def selftest():
    def close(a, b, tol=1e-9):
        return a is not None and b is not None and abs(a - b) <= tol

    g = GameData(synthetic_log(), "selftest")
    rows = build_rows([g])
    seq_of = {(t["round"], t["turn_phase"], t["player"]): t["seq"] for t in g.turns}
    R = {(r["row_type"], r["round"], r["player"], r.get("turn_phase")): r for r in rows}

    # cutoff rule
    first_clue = min(t["seq"] for t in g.turns_in(1, "clue"))
    first_vote = min(t["seq"] for t in g.turns_in(1, "vote"))
    for n in "ABCDE":
        assert R[("reading", 1, n, "clue")]["cutoff_seq"] == first_clue - 1, n
        assert R[("reading", 1, n, "vote")]["cutoff_seq"] == first_vote - 1, n
    assert R[("reading", 1, "B", "whisper")]["cutoff_seq"] == seq_of[(1, "whisper", "B")] - 1
    assert R[("reading", 1, "C", "discuss")]["cutoff_seq"] == seq_of[(1, "discuss", "C")] - 1
    jd, je = seq_of[(1, "job", "D")], seq_of[(1, "job", "E")]
    assert g.cutoff(next(t for t in g.turns if t["seq"] == je)) == jd - 1

    # solver at the cutoff: C before A's card (6 worlds) and at the vote (A's card: 4 worlds)
    assert R[("reading", 1, "C", "discuss")]["solver_worlds"] == 6
    vc = R[("vote", 1, "C", None)]
    assert vc["solver"] == {"A": 0.75, "B": 0.25, "D": 0.5, "E": 0.5}, vc["solver"]
    assert vc["solver_best"] == ["A"] and close(vc["vote_regret"], 0.0) and vc["solver_best_hits_mole"] == 0.0
    assert vc["most_accused"] == ["D"] and vc["first_accused"] == "D" and vc["last_accuse"] == "D"
    assert vc["vote_matches_accuse"] is False and vc["vote_on_most_accused"] is False
    assert R[("vote", 1, "A", None)]["hit_mole"] is True and R[("vote", 1, "A", None)]["with_plurality"] is False

    # table read target: crew readings strictly before the vote cutoff (discuss), not the crew votes (90s)
    er = R[("reading", 1, "E", "vote")]
    assert close(er["target"]["B"], (0.20 + 0.40) / 2), er["target"]          # A's and C's discuss reads of B
    assert close(er["target"]["A"], (0.25 + 0.45) / 2), er["target"]          # B's and C's discuss reads of A
    assert close(er["target"]["D"], (0.60 + 0.60 + 0.60) / 3)
    assert er["target_n"] == {"A": 2, "B": 2, "C": 2, "D": 3}
    exp = mean((er["stated"][x] - er["target"][x]) ** 2 for x in er["target"])
    assert close(er["tr_err_model"], exp)
    assert all(v is None for v in R[("reading", 1, "E", "clue")]["target"].values())
    r2 = R[("reading", 2, "E", "clue")]                                         # A out: crew B, C; their round-1 votes
    assert close(r2["target"]["D"], 0.90) and close(r2["target"]["B"], 0.90) and r2["target_n"]["B"] == 1

    # getaway: round 1 blown, crew votes A->D, B->E, C->A: share 2/3; round 2 blown, game ends at the job
    for m in "DE":
        assert close(R[("round", 1, m, None)]["getaway"], 1 / 3), R[("round", 1, m, None)]
        assert R[("round", 2, m, None)]["getaway"] == 1.0
    assert sum(1 for r in rows if r["row_type"] == "round") == 4

    # sabotage rows
    sd, se = R[("sabotage", 1, "D", None)], R[("sabotage", 1, "E", None)]
    assert sd["script_answer"] == "sabotage" and se["script_answer"] == "help"
    assert sd["partner_on_team"] and not sd["wins_now"] and R[("sabotage", 2, "D", None)]["wins_now"]
    assert close(sd["public_p_self_before"], 0.4) and close(sd["public_p_self_if_blown"], 4 / 9)
    assert close(sd["exposure"], 4 / 9 - 0.4)
    assert close(sd["crew_vote_share_on_moles"], 2 / 3) and not sd["mole_eliminated_this_round"]

    # scores
    ar = R[("reading", 1, "A", "clue")]
    assert close(ar["base_rate"], 0.5) and close(ar["brier_base"], 0.25)
    assert close(ar["brier_model"], ((0.1) ** 2 + 0.4 ** 2 + 0.6 ** 2 + 0.6 ** 2) / 4)
    assert close(ar["read_gap"], ar["brier_model"] - ar["brier_solver"])

    # bootstrap: constant values -> zero width; under 5 games -> too few
    b = Boot([f"g{i}" for i in range(6)], n=200)
    s = b.mean((f"g{i}", 0.5) for i in range(6))
    assert s["lo"] == s["hi"] == 0.5 and s["games"] == 6
    assert b.mean((f"g{i}", 1.0) for i in range(4))["lo"] is None

    # smoke: an in-memory bot game (no files) goes through every row builder
    from inside_job.bots import play_bot_game
    from inside_job.config import load_config
    from common import ROOT, mock_rebuild_check
    ev = play_bot_game(load_config(ROOT / "config" / "pilot.toml"), 5)
    bg = GameData(ev, "bots")
    brows = build_rows([bg])
    assert any(r["row_type"] == "reading" for r in brows) and any(r["row_type"] == "round" for r in brows)
    assert all(r["solver_consistent"] for r in brows if r["row_type"] == "reading" and r["kind"] == "belief")

    # the rebuild of prompts (and so the cutoff rule) is exact on a mock game
    mk = mock_rebuild_check(seeds=(3,))
    assert mk["prompt"] == mk["system"] == mk["schema"] == mk["turns"], mk
    print(f"selftest ok: synthetic game {len(rows)} rows; bot game {len(brows)} rows; "
          f"mock rebuild {mk['prompt']}/{mk['turns']} prompts exact")


# =========================================================================== main

def summarise(batch, games, rows) -> str:
    boot = Boot([g.game_id for g in games])
    L = sec_header(batch, games, rows, boot)
    L += sec_a(rows, games, boot)
    L += sec_b(rows, boot)
    L += sec_c(rows, boot)
    L += sec_d(rows, boot)
    L += sec_e(rows, boot)
    L += sec_f(rows, boot)
    L += sec_g(rows, games, boot)
    L += sec_h(games, rebuild_note_for(games))
    return "\n".join(L) + "\n"


def run(batch: str, games_dir: str, out: str):
    gd = Path(games_dir).resolve()
    od = Path(out).resolve()
    if od == gd or gd in od.parents:
        sys.exit("refusing to write inside the games directory")
    games, b = load_games(games_dir, batch)
    if not games:
        sys.exit(f"no finished games for batch {batch!r} in {games_dir}")
    od.mkdir(parents=True, exist_ok=True)
    rows = build_rows(games)
    write_rows(rows, od, batch)
    md = summarise(batch, games, rows)
    (od / f"decision_summary_{batch}.md").write_text(md, encoding="utf-8")
    ex = b.excluded
    print(f"{len(games)} games, {len(rows)} rows -> {od}")
    print("excluded:", {k: len(getattr(ex, k)) for k in ("spoiled", "unfinished", "replaced", "unindexed", "missing")})
    print(Counter(r["row_type"] for r in rows))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batch", default="pilot1")
    ap.add_argument("--games-dir", default="games")
    ap.add_argument("--out", default="analysis/out")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        selftest()
        return
    run(a.batch, a.games_dir, a.out)


if __name__ == "__main__":
    main()
