"""Bluff mechanism (docs/PREREG_7A.md, criterion 7a): were the crew fooled by Fable 5.2's moles, or
did Fable 5.2's games just give the crew fewer rounds and less evidence?

For each mole model in `analysis/bluff_score.GROUPS` and for the paired-by-seed comparisons Fable 5.2
minus each other model, from the finished logs only (no model calls, no network, read-only):

1. Crew gap (mean 0-100 rating crew give moles minus mean they give other crew, at the vote turn,
   fallback turns left out): whole game and round 1, and by round.
2. Formula gap: the same readings with each rating replaced by 100 x `inside_job.probes.formulas`
   (`jobw50` from the rater's own view just before the round's votes; `public` beside it), and
   the residual = crew gap minus jobw50 gap.
3. Rank versions: chance a crew member rates a mole above an innocent (ties half).
4. Matching on (round, clean jobs so far, blown jobs so far, mole on this round's job).
5. A description table per mole model.
6. The pass marks P1, P2, P3 of PREREG_7A.md, computed from the numbers.

Run from anywhere:  env -u OPENROUTER_API_KEY python3.11 analysis/bluff_mechanism.py [--json FILE]

Definitions as implemented (literal readings of PREREG_7A.md; the alternatives are printed under
"Alternative readings"):

- A reading = one crew member's non-fallback vote turn in one round. Its rated players are the
  keys of `action.suspicion` that are players, alive at that round's `round_start`, not the rater.
- Gaps pool every rating in the scope (one round, or the whole game) the way bluff_score does:
  sum of ratings given to moles / their count minus the same for other crew.
- Rank: every (mole, innocent) pair within one reading counts once, pooled over the scope.
- Strata: clean and blown jobs "so far" are taken at the vote (the last `job_result` before the
  round's first vote turn, i.e. including this round's job). Mole on job: the round's `job_pick`
  team holds a mole.
- Paired tests use seeds present for every model (a seed missing for any model is left out of
  all paired tests and listed). Interval: bluff_score.boot over the paired differences. Sign-flip
  p: exact over all 2^n sign patterns (n <= 16), two-sided.
- Matching: per comparison, strata holding both models; difference of mean game-round crew gaps,
  weight n1 n2 / (n1 + n2), n = game-rounds. Interval: bootstrap resampling whole games within
  each model. A game-round "finds a match" when its stratum holds a game-round of the other model.

Random draws come from bluff_score.new_rng() in a fixed order: first the whole-game crew-gap
bootstrap per group in GROUPS order (the same draws, so the same intervals, as bluff_score), then
the other per-model bootstraps, the paired bootstraps, the matching bootstraps, and last the
alternative readings.
"""
from __future__ import annotations

import argparse
import collections
import itertools
import json
import math
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "analysis")):
    if p not in sys.path:
        sys.path.insert(0, p)

import bluff_score  # noqa: E402
from bluff_score import GROUPS, boot, new_rng  # noqa: E402
from inside_job.probes import formulas, vote_cutoff  # noqa: E402

EXPECTED_SEEDS = tuple(range(101, 111))
ROUNDS = (1, 2, 3, 4)
SCOPES = ("whole", "r1")
METRICS = (  # key, label
    ("crew", "crew gap"),
    ("f50", "jobw50 gap"),
    ("pub", "public gap"),
    ("resid", "residual (crew - jobw50)"),
    ("crew_rank", "crew rank"),
    ("f50_rank", "jobw50 rank"),
    ("pub_rank", "public rank"),
    ("rank_resid", "rank residual (crew - jobw50)"),
)
RANK_METRICS = {"crew_rank", "f50_rank", "pub_rank", "rank_resid"}
TOL = 1e-9
EXACT_SIGNFLIP_MAX = 16
MC_SIGNFLIP_N = 20000


def short(name):
    return name.replace(" moles", "")


# --------------------------------------------------------------------------- per-reading arithmetic

def pooled_gap(readings, key, moles):
    """Sum of values given to moles / count minus the same for other crew, over all readings."""
    ms = mn = cs = cn = 0
    for rd in readings:
        for n, v in rd[key].items():
            if n in moles:
                ms += v
                mn += 1
            else:
                cs += v
                cn += 1
    return ms / mn - cs / cn if mn and cn else None


def pair_score(a, b):
    """1 if a > b, 0.5 if tied (within TOL), else 0."""
    if abs(a - b) <= TOL:
        return 0.5
    return 1.0 if a > b else 0.0


def reading_pairs(rd, key, moles):
    """(sum of pair scores, pair count) for one reading: every (mole, innocent) it rated."""
    vals = rd[key]
    ms = [v for n, v in vals.items() if n in moles]
    cs = [v for n, v in vals.items() if n not in moles]
    return sum(pair_score(m, c) for m in ms for c in cs), len(ms) * len(cs)


def pooled_rank(readings, key, moles):
    """Chance a crew member rates a mole above an innocent, every within-reading pair once."""
    s = n = 0
    for rd in readings:
        a, b = reading_pairs(rd, key, moles)
        s += a
        n += b
    return s / n if n else None


def mean_reading_rank(readings, key, moles):
    """Alternative: the per-reading chance, averaged over readings (each reading counts once)."""
    xs = []
    for rd in readings:
        a, b = reading_pairs(rd, key, moles)
        if b:
            xs.append(a / b)
    return statistics.fmean(xs) if xs else None


def sub(a, b):
    return a - b if a is not None and b is not None else None


def scope_metrics(readings, moles):
    m = {
        "crew": pooled_gap(readings, "crew", moles),
        "f50": pooled_gap(readings, "f50", moles),
        "pub": pooled_gap(readings, "pub", moles),
        "crew_rank": pooled_rank(readings, "crew", moles),
        "f50_rank": pooled_rank(readings, "f50", moles),
        "pub_rank": pooled_rank(readings, "pub", moles),
    }
    m["resid"] = sub(m["crew"], m["f50"])
    m["rank_resid"] = sub(m["crew_rank"], m["f50_rank"])
    m["n_readings"] = len(readings)
    return m


# --------------------------------------------------------------------------- one game

def read_events(path):
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def compat_gap(events):
    """bluff_score's per-game gap, recomputed with its own inclusion rule (every non-mole vote turn,
    fallback or not; every rated name that is a player). Used only to check reproduction."""
    role = {e["player"]: e["role"] for e in events if e["type"] == "role"}
    moles = {p for p, x in role.items() if x == "mole"}
    sm = smn = sc = scn = 0
    for e in events:
        if e["type"] == "turn" and e["turn_phase"] == "vote" and e["player"] not in moles:
            for p, v in ((e.get("action") or {}).get("suspicion") or {}).items():
                if p in moles:
                    sm += v
                    smn += 1
                elif p in role:
                    sc += v
                    scn += 1
    return sm / smn - sc / scn if smn and scn else None


def score_game(events, *, with_formulas=True):
    """Per-round readings, metrics, strata and description facts for one finished game."""
    role = {e["player"]: e["role"] for e in events if e["type"] == "role"}
    moles = {p for p, x in role.items() if x == "mole"}
    end = next(e for e in events if e["type"] == "game_end")
    start = next((e for e in events if e["type"] == "game_start"), {})
    rs = {e["round"]: e for e in events if e["type"] == "round_start"}
    picks = collections.defaultdict(list)
    results = collections.defaultdict(list)
    for e in events:
        if e["type"] == "job_pick":
            picks[e["round"]].append(e)
        elif e["type"] == "job_result":
            results[e["round"]].append(e)
    issues = collections.Counter()
    vote_rounds = sorted({e["round"] for e in events if e["type"] == "turn" and e.get("turn_phase") == "vote"})
    rounds = {}
    for r in vote_rounds:
        alive = set(rs[r]["alive"]) if r in rs else None
        if alive is None:
            issues["vote round without round_start (alive taken as all players)"] += 1
            alive = set(role)
        cutoff = vote_cutoff(events, r)
        readings, seen = [], set()
        n_fb = 0
        for e in events:
            if not (e["type"] == "turn" and e.get("turn_phase") == "vote" and e["round"] == r):
                continue
            p = e["player"]
            if p in moles:
                continue
            if e.get("fallback"):
                n_fb += 1
                issues["crew fallback vote turn left out"] += 1
                continue
            sus = (e.get("action") or {}).get("suspicion")
            if not sus:
                issues["crew vote turn without suspicion left out"] += 1
                continue
            if p in seen:
                issues["second crew vote turn by one player in a round (kept)"] += 1
            seen.add(p)
            crew = {}
            for n, v in sus.items():
                if n not in role:
                    issues["rating of a name that is not a player dropped"] += 1
                elif n == p:
                    issues["self-rating dropped"] += 1
                elif n not in alive:
                    issues["rating of a dead player dropped"] += 1
                else:
                    crew[n] = v
            missing = alive - set(crew) - {p}
            if missing:
                issues["living player not rated (reading kept)"] += len(missing)
            rated = sorted(crew)
            rd = {"rater": p, "seq": e["seq"], "crew": crew}
            if with_formulas:
                f = formulas(events, cutoff, p, rated)
                rd["f50"] = {n: 100 * f["jobw50"][n] for n in rated}
                rd["pub"] = {n: 100 * f["public"][n] for n in rated}
            readings.append(rd)
        before = [j for j in events if j["type"] == "job_result" and j["seq"] <= cutoff]
        clean_v = before[-1]["clean_jobs"] if before else 0
        blown_v = before[-1]["blown_jobs"] if before else 0
        team = picks[r][-1]["team"] if picks.get(r) else None
        if team is None:
            issues["vote round without job_pick (mole on job = False)"] += 1
        if len(picks.get(r, [])) > 1:
            issues["round with more than one job_pick (last used)"] += 1
        mole_job = bool(team and moles & set(team))
        pre_clean = rs[r].get("clean_jobs", 0) if r in rs else 0
        pre_blown = rs[r].get("blown_jobs", 0) if r in rs else 0
        R = {"readings": readings, "n_fallback": n_fb, "cutoff": cutoff,
             "strata": (r, clean_v, blown_v, mole_job), "strata_pre": (r, pre_clean, pre_blown, mole_job)}
        if with_formulas:
            R["m"] = scope_metrics(readings, moles)
            R["alt_rank"] = mean_reading_rank(readings, "crew", moles)
        else:
            R["m"] = {"crew": pooled_gap(readings, "crew", moles), "n_readings": len(readings)}
        rounds[r] = R
    out = {"moles": sorted(moles), "rounds": rounds, "issues": issues,
           "rounds_played": end.get("rounds"), "winner": end.get("winner"), "reason": end.get("reason"),
           "game_id": start.get("game_id")}
    allr = [rd for r in sorted(rounds) for rd in rounds[r]["readings"]]
    if with_formulas:
        out["whole"] = scope_metrics(allr, moles)
        out["r1"] = rounds[1]["m"] if 1 in rounds else scope_metrics([], moles)
        out["alt"] = {
            "rank_whole": mean_reading_rank(allr, "crew", moles),
            "rank_r1": rounds[1]["alt_rank"] if 1 in rounds else None,
            "f50_rank_whole": mean_reading_rank(allr, "f50", moles),
            "f50_rank_r1": mean_reading_rank(rounds[1]["readings"], "f50", moles) if 1 in rounds else None,
        }
        rg = [rounds[r]["m"]["crew"] for r in sorted(rounds) if rounds[r]["m"]["crew"] is not None]
        rr = [rounds[r]["m"]["resid"] for r in sorted(rounds) if rounds[r]["m"]["resid"] is not None]
        out["alt"]["crew_whole_roundmean"] = statistics.fmean(rg) if rg else None
        out["alt"]["resid_whole_roundmean"] = statistics.fmean(rr) if rr else None
    else:
        out["whole"] = {"crew": pooled_gap(allr, "crew", moles)}
    rs1 = rs.get(1, {})
    p1 = picks.get(1)
    j1 = results.get(1)
    out["desc"] = {
        "job1_blown": bool(j1 and j1[-1].get("blown")),
        "job1_mole": bool(p1 and moles & set(p1[-1]["team"])),
        "mole_led_r1": rs1.get("leader") in moles,
        "readings": len(allr),
        "vote_rounds": len(rounds),
    }
    return out


# --------------------------------------------------------------------------- loading

def load_groups(root=ROOT, groups=GROUPS, *, with_formulas=True):
    """Finished, unspoiled games of each group (index row + log with game_end), sorted by seed.

    Returns (res, left_out): res {group: [game]}, left_out [(game_id, reason)]."""
    root = str(root)
    idx = bluff_score.load_index(os.path.join(root, "games", "index.jsonl"))
    res, left = {}, []
    for name, batches in groups:
        gs = []
        for r in sorted((r for r in idx if r.get("batch") in batches), key=lambda r: (r["seed"], r["game_id"])):
            if r.get("spoiled"):
                left.append((r["game_id"], "spoiled"))
                continue
            path = os.path.join(root, r["log"])
            if not os.path.exists(path):
                left.append((r["game_id"], "log file missing"))
                continue
            ev = read_events(path)
            if not any(e["type"] == "game_end" for e in ev):
                left.append((r["game_id"], "no game_end"))
                continue
            g = score_game(ev, with_formulas=with_formulas)
            g.update(group=name, batch=r["batch"], seed=r["seed"], game_id=r["game_id"], log=r["log"])
            # Reproduction check against bluff_score's own per-game gap.
            bs = bluff_score.game(r, root)["gap"]
            cg = compat_gap(ev)
            assert cg == bs, f"{r['game_id']}: compat gap {cg} != bluff_score gap {bs}"
            g["bluff_score_gap"] = bs
            g["same_as_bluff_score"] = g["whole"]["crew"] == bs
            if not g["same_as_bluff_score"]:
                g["issues"]["whole-game crew gap differs from bluff_score (fallback/dead/self ratings)"] += 1
            gs.append(g)
        res[name] = gs
    return res, left


# --------------------------------------------------------------------------- statistics

def nan_to_none(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else x


def model_summary(values, rng):
    xs = [x for x in values if x is not None]
    lo, hi = boot(xs, rng)
    return {"n": len(xs), "mean": statistics.fmean(xs) if xs else None,
            "lo": nan_to_none(lo), "hi": nan_to_none(hi)}


def signflip_p(d, rng=None):
    """Two-sided sign-flip permutation p for the mean of paired differences d.

    Exact over all 2^n patterns when n <= 16; otherwise MC_SIGNFLIP_N random patterns from rng."""
    n = len(d)
    if n == 0:
        return None
    obs = abs(statistics.fmean(d))
    if n <= EXACT_SIGNFLIP_MAX:
        hit = 0
        for signs in itertools.product((1, -1), repeat=n):
            hit += abs(sum(s * x for s, x in zip(signs, d)) / n) >= obs - 1e-12
        return hit / 2 ** n
    hit = 0
    for _ in range(MC_SIGNFLIP_N):
        hit += abs(sum(x if rng.random() < 0.5 else -x for x in d) / n) >= obs - 1e-12
    return hit / MC_SIGNFLIP_N


def paired_summary(da, db, seeds, rng):
    """da, db: {seed: value}. Differences a - b over `seeds` where both are defined."""
    used = [s for s in seeds if da.get(s) is not None and db.get(s) is not None]
    d = [da[s] - db[s] for s in used]
    lo, hi = boot(d, rng)
    return {"n": len(d), "seeds": used, "diffs": d, "mean": statistics.fmean(d) if d else None,
            "lo": nan_to_none(lo), "hi": nan_to_none(hi), "below": sum(x < 0 for x in d),
            "p": signflip_p(d, rng),
            "undefined_seeds": [s for s in seeds if s not in used]}


def game_rounds(games, key):
    """[(stratum, crew gap)] for every game-round with a crew gap."""
    out = []
    for g in games:
        for r in sorted(g["rounds"]):
            R = g["rounds"][r]
            if R["m"]["crew"] is not None:
                out.append((R[key], R["m"]["crew"]))
    return out


def match(ga, gb, key="strata"):
    """Weighted difference (a minus b) of mean game-round crew gaps within strata holding both."""
    st = collections.defaultdict(lambda: ([], []))
    for i, games in enumerate((ga, gb)):
        for s, v in game_rounds(games, key):
            st[s][i].append(v)
    num = den = 0.0
    tot_a = tot_b = m_a = m_b = 0
    rows = []
    for s in sorted(st):
        a, b = st[s]
        tot_a += len(a)
        tot_b += len(b)
        if a and b:
            w = len(a) * len(b) / (len(a) + len(b))
            d = statistics.fmean(a) - statistics.fmean(b)
            num += w * d
            den += w
            m_a += len(a)
            m_b += len(b)
            rows.append({"stratum": s, "na": len(a), "nb": len(b), "w": w, "diff": d})
    return {"diff": num / den if den else None, "share_a": m_a / tot_a if tot_a else None,
            "share_b": m_b / tot_b if tot_b else None, "matched_a": m_a, "total_a": tot_a,
            "matched_b": m_b, "total_b": tot_b, "strata": rows}


def match_boot(ga, gb, rng, key="strata", n=10000):
    """Whole-game bootstrap of match(): each model's games resampled with replacement."""
    vals, empty = [], 0
    if len(ga) < 2 or len(gb) < 2:
        return None, None, 0
    for _ in range(n):
        x = match(rng.choices(ga, k=len(ga)), rng.choices(gb, k=len(gb)), key)["diff"]
        if x is None:
            empty += 1
        else:
            vals.append(x)
    if len(vals) < 2:
        return None, None, empty
    vals.sort()
    k = len(vals)
    return vals[int(0.025 * k)], vals[int(0.975 * k) - 1], empty


# --------------------------------------------------------------------------- pass marks

def excludes_zero(c):
    return c["lo"] is not None and c["hi"] is not None and (c["hi"] < 0 or c["lo"] > 0)


def mark_paired(comps):
    """P1/P2 rules of PREREG_7A.md over a list of paired comparisons (each: mean, lo, hi, below, n).

    Holds: every mean < 0 and every interval excludes zero. Direction only: every mean < 0 and at
    least 70% of seeds below zero in each, but some interval includes zero. Fails: some mean >= 0
    or fewer than half the seeds below zero in some comparison. The rules leave a gap (all means
    below zero, some interval includes zero, some comparison with 50-70% of seeds below) and can
    overlap (Holds and Fails both true); both are reported as such, not resolved."""
    if not comps or any(c["n"] == 0 or c["mean"] is None for c in comps):
        return "not informative (no paired seeds)"
    fails = any(c["mean"] >= 0 or c["below"] < c["n"] / 2 for c in comps)
    holds = all(c["mean"] < 0 and excludes_zero(c) for c in comps)
    direction = (all(c["mean"] < 0 and c["below"] >= 0.7 * c["n"] for c in comps)
                 and any(not excludes_zero(c) for c in comps))
    if holds and fails:
        return "Holds and Fails both met (rules overlap)"
    if holds:
        return "Holds"
    if fails:
        return "Fails"
    if direction:
        return "Direction only"
    return "No mark (between Direction only and Fails)"


def mark_match(comps):
    """P3: not informative if fewer than half of the focal model's game-rounds find a match in any
    comparison; else Holds / Direction only / Fails as in PREREG_7A.md."""
    if not comps or any(c["share_a"] is None or c["share_a"] < 0.5 for c in comps):
        return "not informative"
    if any(c["diff"] is None for c in comps):
        return "not informative"
    if any(c["diff"] >= 0 for c in comps):
        return "Fails"
    if all(excludes_zero(c) for c in comps):
        return "Holds"
    return "Direction only"


# --------------------------------------------------------------------------- the analysis

def analyse(root=ROOT, groups=GROUPS, rng=None, expected_seeds=EXPECTED_SEEDS, n_boot_match=10000):
    rng = rng or new_rng()
    res, left = load_groups(root, groups)
    names = [n for n, _ in groups]
    focal, others = names[-1], names[:-1]
    out = {"groups": names, "focal": focal, "others": others, "left_out": left, "games": res}

    # Seeds and the paired set.
    seeds = {n: [g["seed"] for g in res[n]] for n in names}
    dup = {n: sorted(s for s, c in collections.Counter(seeds[n]).items() if c > 1) for n in names}
    allseeds = sorted(set().union(*map(set, seeds.values()))) if names else []
    paired_seeds = [s for s in allseeds if all(s in seeds[n] for n in names) and not any(s in dup[n] for n in names)]
    out["seeds"] = seeds
    out["duplicate_seeds"] = dup
    out["paired_seeds"] = paired_seeds
    out["unpaired_seeds"] = {s: [short(n) for n in names if s not in seeds[n]] for s in allseeds if s not in paired_seeds}
    full = all(sorted(seeds[n]) == list(expected_seeds) for n in names)
    out["full"] = full
    out["n_games"] = sum(len(res[n]) for n in names)

    # 1-3. Per-model bootstraps. Whole-game crew gap first, in GROUPS order (= bluff_score's draws).
    per = {(m, sc, n): None for m, _ in METRICS for sc in SCOPES for n in names}
    for n in names:
        per[("crew", "whole", n)] = model_summary([g["whole"]["crew"] for g in res[n]], rng)
    for m, _ in METRICS:
        for sc in SCOPES:
            for n in names:
                if per[(m, sc, n)] is None:
                    per[(m, sc, n)] = model_summary([g[sc][m] for g in res[n]], rng)
    out["per_model"] = per

    # Paired by seed: focal minus each other.
    def by_seed(n, sc, m):
        return {g["seed"]: g[sc][m] for g in res[n] if g["seed"] in paired_seeds}
    paired = {}
    for m, _ in METRICS:
        for sc in SCOPES:
            for o in others:
                paired[(m, sc, o)] = paired_summary(by_seed(focal, sc, m), by_seed(o, sc, m), paired_seeds, rng)
    out["paired"] = paired

    # By round (no draws).
    byr = {}
    for n in names:
        for r in ROUNDS:
            Rs = [g["rounds"][r] for g in res[n] if r in g["rounds"]]
            def mean_of(k):
                xs = [R["m"][k] for R in Rs if R["m"][k] is not None]
                return statistics.fmean(xs) if xs else None
            byr[(n, r)] = {"games": len(Rs), "readings": sum(R["m"]["n_readings"] for R in Rs),
                           "crew": mean_of("crew"), "f50": mean_of("f50"), "resid": mean_of("resid"),
                           "crew_rank": mean_of("crew_rank")}
    out["by_round"] = byr

    # 4. Matching.
    mt = {}
    for o in others:
        m = match(res[focal], res[o], "strata")
        m["lo"], m["hi"], m["empty"] = match_boot(res[focal], res[o], rng, "strata", n_boot_match)
        mt[o] = m
    out["match"] = mt
    st = collections.defaultdict(lambda: {n: [] for n in names})
    for n in names:
        for s, v in game_rounds(res[n], "strata"):
            st[s][n].append(v)
    out["strata_table"] = dict(st)

    # 5. Description.
    desc = {}
    for n in names:
        gs = res[n]
        k = len(gs)
        vr = sum(g["desc"]["vote_rounds"] for g in gs)
        desc[n] = {
            "games": k,
            "rounds": statistics.fmean(g["rounds_played"] for g in gs) if gs else None,
            "vote_rounds": vr / k if k else None,
            "readings_per_vote_round": sum(g["desc"]["readings"] for g in gs) / vr if vr else None,
            "job1_blown": sum(g["desc"]["job1_blown"] for g in gs) / k if k else None,
            "job1_mole": sum(g["desc"]["job1_mole"] for g in gs) / k if k else None,
            "mole_led_r1": sum(g["desc"]["mole_led_r1"] for g in gs) / k if k else None,
            "ended": collections.Counter(f"{g['winner']}/{g['reason']}" for g in gs),
        }
    out["desc"] = desc

    # 6. Marks.
    p1c = [paired[("crew", "r1", o)] for o in others]
    p2w = [paired[("resid", "whole", o)] for o in others]
    p2r = [paired[("resid", "r1", o)] for o in others]
    out["marks"] = {
        "P1": mark_paired(p1c),
        "P2": mark_paired(p2w + p2r),
        "P2_whole": mark_paired(p2w),
        "P2_r1": mark_paired(p2r),
        "P3": mark_match([mt[o] for o in others]),
    }

    # Alternative readings (drawn last so the primary numbers do not move).
    alt = {}
    for o in others:
        m = match(res[focal], res[o], "strata_pre")
        m["lo"], m["hi"], m["empty"] = match_boot(res[focal], res[o], rng, "strata_pre", n_boot_match)
        alt[("match_pre", o)] = m
    alt["P3_pre"] = mark_match([alt[("match_pre", o)] for o in others])
    for key in ("rank_whole", "rank_r1", "f50_rank_whole", "f50_rank_r1", "crew_whole_roundmean",
                "resid_whole_roundmean"):
        for o in others:
            da = {g["seed"]: g["alt"][key] for g in res[focal] if g["seed"] in paired_seeds}
            db = {g["seed"]: g["alt"][key] for g in res[o] if g["seed"] in paired_seeds}
            alt[(key, o)] = paired_summary(da, db, paired_seeds, rng)
        for n in names:
            xs = [g["alt"][key] for g in res[n] if g["alt"][key] is not None]
            alt[(key, "mean", n)] = statistics.fmean(xs) if xs else None
    alt["P2_rm"] = mark_paired([alt[("resid_whole_roundmean", o)] for o in others] + p2r)
    # Pairwise seed intersections (instead of seeds present for every model).
    alt["pairwise_seeds"] = {o: sorted(set(seeds[focal]) & set(seeds[o])) for o in others}
    out["alt"] = alt

    issues = collections.Counter()
    for n in names:
        for g in res[n]:
            issues.update(g["issues"])
    out["issues"] = issues
    out["issue_games"] = {g["game_id"]: dict(g["issues"]) for n in names for g in res[n] if g["issues"]}
    return out


# --------------------------------------------------------------------------- printing

def f1(x, scale=1.0, fmt="{:+.1f}"):
    return "n/a" if x is None else fmt.format(x * scale)


def ci(lo, hi, scale=1.0, fmt="{:+.1f}"):
    return "[n/a]" if lo is None or hi is None else f"[{fmt.format(lo * scale)}, {fmt.format(hi * scale)}]"


def mfmt(m):
    """Rank metrics shown as chances x100 (50 = no separation), gaps on the 0-100 scale."""
    return "{:.1f}" if m in RANK_METRICS and not m.endswith("resid") else "{:+.1f}"


def scale_of(m):
    return 100.0 if m in RANK_METRICS else 1.0


def render(out):
    names, focal, others = out["groups"], out["focal"], out["others"]
    res = out["games"]
    L = []
    status = ("FULL SET: seeds 101-110 for all three models (the verdict set)" if out["full"]
              else f"INTERIM ({out['n_games']} games; the verdict is taken at 30 games, seeds 101-110 x 3)")
    mk = out["marks"]
    L.append(f"Bluff mechanism, docs/PREREG_7A.md. {status}")
    L.append(f"Marks: P1 {mk['P1']} | P2 {mk['P2']} (whole game {mk['P2_whole']}, round 1 {mk['P2_r1']}) | P3 {mk['P3']}")
    if not out["full"] and "Fails" in (mk["P1"], mk["P2"], mk["P3"]):
        L.append("INTERIM FAILURE: " + ", ".join(k for k in ("P1", "P2", "P3") if mk[k] == "Fails")
                 + " fails on the games so far (interim: decides nothing, stated per PREREG_7A.md).")

    L.append("")
    L.append("== Games used (index row, game_end, not spoiled)")
    for n in names:
        L.append(f"  {short(n)}: {len(res[n])} games, seeds {' '.join(str(s) for s in out['seeds'][n]) or '-'}")
    L.append(f"  paired seeds (present for every model): {' '.join(map(str, out['paired_seeds'])) or 'none'}")
    if out["unpaired_seeds"]:
        L.append("  left out of paired tests: " + "; ".join(f"seed {s} (missing for {', '.join(v) or 'duplicate'})"
                                                         for s, v in out["unpaired_seeds"].items()))
    for n, d in out["duplicate_seeds"].items():
        if d:
            L.append(f"  DUPLICATE seeds in {short(n)}: {d} (left out of paired tests)")
    if out["left_out"]:
        L.append("  index rows left out: " + "; ".join(f"{g} ({why})" for g, why in out["left_out"]))
    L.append(f"  {'model':10} {'seed':>4} {'game_id':24} {'rnds':>4} {'votes':>5} {'whole':>6} {'bluff_score':>11} "
             f"{'r1 crew':>7} {'r1 jw50':>7} {'r1 resid':>8} {'end':16}")
    for n in names:
        for g in res[n]:
            L.append(f"  {short(n):10} {g['seed']:>4} {g['game_id']:24} {g['rounds_played']:>4} "
                     f"{g['desc']['vote_rounds']:>5} {f1(g['whole']['crew']):>6} {f1(g['bluff_score_gap']):>11} "
                     f"{f1(g['r1']['crew']):>7} {f1(g['r1']['f50']):>7} {f1(g['r1']['resid']):>8} "
                     f"{g['winner']}/{g['reason']}")
    same = all(g["same_as_bluff_score"] for n in names for g in res[n])
    L.append(f"  whole-game crew gap equals bluff_score's per-game gap in every game: {'yes' if same else 'NO'} "
             "(bluff_score's own inclusion rule reproduced exactly, asserted)")

    L.append("")
    L.append("== 5. Description per mole model")
    L.append(f"  {'model':10} {'games':>5} {'rounds/game':>11} {'vote rnds/game':>14} {'readings/vote rnd':>17} "
             f"{'job1 blown':>10} {'mole on job1':>12} {'mole led r1':>11}  ended")
    for n in names:
        d = out["desc"][n]
        pc = lambda x: "n/a" if x is None else f"{100 * x:.0f}%"
        L.append(f"  {short(n):10} {d['games']:>5} {f1(d['rounds'], fmt='{:.2f}'):>11} {f1(d['vote_rounds'], fmt='{:.2f}'):>14} "
                 f"{f1(d['readings_per_vote_round'], fmt='{:.2f}'):>17} {pc(d['job1_blown']):>10} {pc(d['job1_mole']):>12} "
                 f"{pc(d['mole_led_r1']):>11}  " + ", ".join(f"{k} {v}" for k, v in sorted(d["ended"].items())))

    L.append("")
    L.append("== 1-3. Per mole model: mean per game, whole-game bootstrap 95% interval (n games)")
    L.append("   gaps on the 0-100 scale; rank = chance x100 a crew member rates a mole above an innocent (50 = none)")
    L.append(f"  {'metric':31} {'scope':5} " + " ".join(f"{short(n):>27}" for n in names))
    for m, lab in METRICS:
        for sc in SCOPES:
            cells = []
            for n in names:
                s = out["per_model"][(m, sc, n)]
                cells.append(f"{f1(s['mean'], scale_of(m), mfmt(m))} {ci(s['lo'], s['hi'], scale_of(m), mfmt(m))} ({s['n']})")
            L.append(f"  {lab:31} {sc:5} " + " ".join(f"{c:>27}" for c in cells))

    L.append("")
    L.append(f"== 1-3. Paired by seed, {short(focal)} minus each: mean [bootstrap 95% over seeds], seeds below zero, sign-flip p")
    L.append(f"  {'metric':31} {'scope':5} " + " ".join(f"{'minus ' + short(o):>38}" for o in others))
    for m, lab in METRICS:
        for sc in SCOPES:
            cells = []
            for o in others:
                p = out["paired"][(m, sc, o)]
                pv = "n/a" if p["p"] is None else f"{p['p']:.3f}"
                cells.append(f"{f1(p['mean'], scale_of(m))} {ci(p['lo'], p['hi'], scale_of(m))} {p['below']}/{p['n']} p={pv}")
            L.append(f"  {lab:31} {sc:5} " + " ".join(f"{c:>38}" for c in cells))

    L.append("")
    L.append("== 1. By round: games with a crew vote that round, readings, mean per game-round of crew gap / jobw50 gap / residual")
    L.append(f"  {'model':10} " + " ".join(f"{'round ' + str(r):>30}" for r in ROUNDS))
    for n in names:
        cells = []
        for r in ROUNDS:
            b = out["by_round"][(n, r)]
            cells.append(f"{b['games']}g {b['readings']}r {f1(b['crew'])} / {f1(b['f50'])} / {f1(b['resid'])}")
        L.append(f"  {short(n):10} " + " ".join(f"{c:>30}" for c in cells))

    L.append("")
    L.append("== 4. Matching: strata (round, clean jobs so far, blown jobs so far, mole on this round's job), at the vote")
    L.append(f"  {'stratum':27} " + " ".join(f"{short(n) + ' n, mean gap':>22}" for n in names))
    for s in sorted(out["strata_table"]):
        row = out["strata_table"][s]
        lab = f"r{s[0]} clean {s[1]} blown {s[2]} {'mole' if s[3] else 'no mole'}"
        L.append(f"  {lab:27} " + " ".join(
            f"{(str(len(row[n])) + ' ' + f1(statistics.fmean(row[n]) if row[n] else None)):>22}" for n in names))
    for o in others:
        mt = out["match"][o]
        L.append(f"  {short(focal)} minus {short(o)}: weighted diff {f1(mt['diff'])} {ci(mt['lo'], mt['hi'])} "
                 f"(bootstrap resamples with no shared stratum: {mt['empty']}); matched game-rounds "
                 f"{short(focal)} {mt['matched_a']}/{mt['total_a']} ({f1(mt['share_a'], 100, '{:.0f}')}%), "
                 f"{short(o)} {mt['matched_b']}/{mt['total_b']} ({f1(mt['share_b'], 100, '{:.0f}')}%)")

    L.append("")
    L.append("== 6. Pass marks (PREREG_7A.md), " + ("verdict set" if out["full"] else "INTERIM: decides nothing"))
    def pline(p):
        return f"{f1(p['mean'])} {ci(p['lo'], p['hi'])}, {p['below']}/{p['n']} seeds below zero"
    L.append(f"  P1 (crew gap, round 1): {mk['P1']}. " + "; ".join(
        f"minus {short(o)} {pline(out['paired'][('crew', 'r1', o)])}" for o in others))
    L.append(f"  P2 (residual, whole game and round 1, all four comparisons): {mk['P2']}.")
    for sc in SCOPES:
        L.append(f"     {sc}: {mk['P2_' + sc]}. " + "; ".join(
            f"minus {short(o)} {pline(out['paired'][('resid', sc, o)])}" for o in others))
    L.append(f"  P3 (matching): {mk['P3']}. " + "; ".join(
        f"minus {short(o)} {f1(out['match'][o]['diff'])} {ci(out['match'][o]['lo'], out['match'][o]['hi'])}, "
        f"{short(focal)} matched {f1(out['match'][o]['share_a'], 100, '{:.0f}')}%" for o in others))
    L.append("  Per PREREG_7A.md: " + consequence(mk))

    a = out["alt"]
    L.append("")
    L.append("== Alternative readings of ambiguous definitions (not the prereg's literal reading; for comparison)")
    L.append("  A. Strata with clean/blown jobs before this round's job (round_start): P3 would be " + a["P3_pre"] + ". " + "; ".join(
        f"minus {short(o)} {f1(a[('match_pre', o)]['diff'])} {ci(a[('match_pre', o)]['lo'], a[('match_pre', o)]['hi'])}, "
        f"{short(focal)} matched {f1(a[('match_pre', o)]['share_a'], 100, '{:.0f}')}%" for o in others))
    for key, lab, sc in (("rank_r1", "B. Crew rank as mean of per-reading chances, round 1", 100),
                         ("rank_whole", "   same, whole game", 100),
                         ("f50_rank_r1", "   jobw50 rank the same way, round 1", 100),
                         ("f50_rank_whole", "   jobw50 rank the same way, whole game", 100),
                         ("crew_whole_roundmean", "C. Whole-game crew gap as mean of round gaps", 1),
                         ("resid_whole_roundmean", "   whole-game residual as mean of round residuals", 1)):
        mf = "{:.1f}" if sc == 100 else "{:+.1f}"
        means = " ".join(f"{short(n)} {f1(a[(key, 'mean', n)], sc, mf)}" for n in names)
        L.append(f"  {lab}: {means}; " + "; ".join(
            f"minus {short(o)} {f1(a[(key, o)]['mean'], sc)} {ci(a[(key, o)]['lo'], a[(key, o)]['hi'], sc)} "
            f"{a[(key, o)]['below']}/{a[(key, o)]['n']}" for o in others))
    L.append(f"     P2 with C's whole-game residual: {a['P2_rm']}")
    L.append("  D. P2 marked per scope instead of over all four comparisons: whole game "
             f"{mk['P2_whole']}, round 1 {mk['P2_r1']}")
    L.append("  E. Paired seeds per comparison instead of present for every model: " + "; ".join(
        f"{short(focal)}/{short(o)} {len(a['pairwise_seeds'][o])} seeds" for o in others)
             + f" (used: {len(out['paired_seeds'])})")

    L.append("")
    L.append("== Log checks (handled by the stated rules)")
    if out["issues"]:
        for k, v in sorted(out["issues"].items()):
            L.append(f"  {k}: {v}")
        for gid, d in sorted(out["issue_games"].items()):
            L.append(f"    {gid}: {d}")
    else:
        L.append("  none: no fallback crew vote turns, no ratings of dead players, self or non-players, no unrated living players")
    return "\n".join(L)


def consequence(mk):
    p1, p2, p3 = mk["P1"], mk["P2"], mk["P3"]
    s = []
    if p1 == "Fails":
        s.append("P1 fails: the Fable 5.2 result does not survive (top of the report; no dependent post).")
    elif p1 in ("Holds", "Direction only") and p3 != "Fails":
        s.append(f"the result survives at strength '{p1}'.")
    else:
        s.append(f"P1 {p1}, P3 {p3}: not covered by a rule in 'What follows'.")
    if p2 == "Holds":
        s.append("'The crew were fooled' may be written.")
    elif p2 == "Direction only":
        s.append("'Fooled' only in hedged wording.")
    else:
        s.append("Wording is 'left less evidence', not 'fooled'.")
    return " ".join(s)


# --------------------------------------------------------------------------- JSON

def to_json(out):
    def key(k):
        return "|".join(map(str, k)) if isinstance(k, tuple) else str(k)

    def conv(x):
        if isinstance(x, dict):
            return {key(k): conv(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [conv(v) for v in x]
        if isinstance(x, set):
            return sorted(x)
        if isinstance(x, float) and math.isnan(x):
            return None
        return x
    return conv(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", help="also write every number to this JSON file")
    ap.add_argument("--root", default=str(ROOT), help="project root holding games/ (default: this repo)")
    args = ap.parse_args(argv)
    out = analyse(args.root)
    print(render(out))
    if args.json:
        with open(args.json, "w") as f:
            json.dump(to_json(out), f, indent=1, sort_keys=True)


if __name__ == "__main__":
    main()
