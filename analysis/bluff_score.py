"""Bluff confirmation: one fixed cheap crew, the mole model varied (docs/HEADROOM.md).

Groups are batches in games/index.jsonl. For each group: per-game crew suspicion gap (mean suspicion
the crew gives the moles minus mean suspicion it gives other crew, at vote time), crew votes that
landed on a mole, mole wins, and token use. Intervals are a bootstrap over whole games. Groups are
compared by a permutation test on the per-game gap and, where seeds match, by paired differences.

Run from the project root: python3.11 analysis/bluff_score.py

Importable: load_index, group_games, summarise, summaries and comparisons give the numbers the
script prints (analysis/bluff_chart.py uses them). All random draws come from one seeded RNG in a
fixed order: the bootstrap for each group in GROUPS order, then the permutation tests. Pass a fresh
new_rng() and call in that order to reproduce the printed intervals and p-values.
"""
import collections
import json
import os
import random
import statistics

GROUPS = [
    ("Haiku 4.5 moles", ["bluff_haiku45"]),
    ("Opus 5.5 moles", ["bluff_opus55"]),
    ("Fable 5.2 moles", ["headroom1", "bluff_fable52"]),
]
RNG_SEED = 20261110


def new_rng():
    return random.Random(RNG_SEED)


def load_index(path="games/index.jsonl"):
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def game(r, root=""):
    """Score one game. r is its index row; r["log"] is resolved against root (default: cwd)."""
    with open(os.path.join(root, r["log"])) as f:
        ev = [json.loads(l) for l in f if l.strip()]
    role = {e["player"]: e["role"] for e in ev if e["type"] == "role"}
    moles = {p for p, x in role.items() if x == "mole"}
    g = collections.Counter()
    alive = set(role)
    mis = 0
    for e in ev:
        t = e["type"]
        if t == "round_start":
            alive = set(e["alive"])
        elif t == "job_pick":
            g["jobs"] += 1
            g["jobs_with_mole"] += bool(moles & set(e["team"]))
        elif t == "job_choices":
            for p, c in e["choices"].items():
                if p in moles:
                    g["mole_job_seats"] += 1
                    g["mole_sabotage"] += c == "sabotage"
        elif t == "vote_result":
            for v, tgt in e["votes"].items():
                if v in moles:
                    g["mole_votes"] += 1
                    g["mole_on_partner"] += tgt in moles
                else:
                    g["crew_votes"] += 1
                    g["crew_on_mole"] += tgt in moles
                    g["exp_x1000"] += round(1000 * len(moles & alive) / (len(alive) - 1))
            if e.get("eliminated"):
                g["elims"] += 1
                g["elims_mole"] += e["role"] == "mole"
                alive.discard(e["eliminated"])
        elif t == "turn":
            sm = e.get("served_model")
            if sm and not str(sm).startswith(e["model"]):
                mis += 1
            is_mole = e["player"] in moles
            if is_mole and e["turn_phase"] in ("discuss", "vote", "pick") and e.get("public"):
                g["mole_stmts"] += 1
                g["mole_stmts_lie"] += any(c.get("truthful") is False for c in e.get("claims") or [])
            if e["turn_phase"] == "vote" and not is_mole:
                for p, v in ((e.get("action") or {}).get("suspicion") or {}).items():
                    if p in moles:
                        g["sm"] += v; g["smn"] += 1
                    elif p in role:
                        g["sc"] += v; g["scn"] += 1
    end = next(e for e in ev if e["type"] == "game_end")
    g["moles_alive"] = len(moles & set(end["survivors"]))
    gap = g["sm"] / g["smn"] - g["sc"] / g["scn"] if g["smn"] and g["scn"] else None
    return {"row": r, "g": g, "gap": gap, "mis": mis, "moles": sorted(moles)}


def boot(xs, rng, n=10000):
    if len(xs) < 2:
        return (float("nan"), float("nan"))
    ms = sorted(statistics.fmean(rng.choices(xs, k=len(xs))) for _ in range(n))
    return ms[int(0.025 * n)], ms[int(0.975 * n) - 1]


def perm(a, b, rng, n=20000):
    obs = statistics.fmean(a) - statistics.fmean(b)
    pool = a + b
    hit = 0
    for _ in range(n):
        rng.shuffle(pool)
        d = statistics.fmean(pool[:len(a)]) - statistics.fmean(pool[len(a):])
        hit += abs(d) >= abs(obs) - 1e-12
    return obs, hit / n


def pct(a, b):
    return f"{a}/{b} ({100 * a / b:.0f}%)" if b else "0/0"


def group_games(idx, groups=GROUPS, root=""):
    """{group name: [scored game, ...] sorted by seed}, spoiled games left out. No random draws."""
    res = {}
    for name, batches in groups:
        rows = [r for r in idx if r.get("batch") in batches and not r.get("spoiled")]
        res[name] = [game(r, root) for r in sorted(rows, key=lambda r: r["seed"])]
    return res


def summarise(gs, rng):
    """Totals, per-game gaps, mean, bootstrap 95% interval and mole wins for one non-empty group.

    Draws from rng only for the bootstrap (none when fewer than two games have a gap)."""
    tot = collections.Counter()
    for x in gs:
        tot.update(x["g"])
    gaps = [x["gap"] for x in gs if x["gap"] is not None]
    lo, hi = boot(gaps, rng)
    return {
        "n": len(gs),
        "wins": sum(x["row"]["winner"] == "moles" for x in gs),
        "gaps": gaps,
        "mean": statistics.fmean(gaps) if gaps else float("nan"),
        "lo": lo,
        "hi": hi,
        "sd": statistics.stdev(gaps) if len(gaps) > 1 else float("nan"),
        "tot": tot,
    }


def summaries(res, rng, groups=GROUPS):
    """summarise() for every group with games, in GROUPS order (the order the script draws in)."""
    return {name: summarise(res[name], rng) for name, _ in groups if res.get(name)}


def comparisons(res, rng, groups=GROUPS):
    """Permutation test and paired-by-seed differences on the per-game gap for each pair of groups."""
    out = []
    names = [n for n, _ in groups if res.get(n)]
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a = [x["gap"] for x in res[names[i]] if x["gap"] is not None]
            b = [x["gap"] for x in res[names[j]] if x["gap"] is not None]
            if len(a) > 1 and len(b) > 1:
                d, p = perm(a, b, rng)
                sa = {x["row"]["seed"]: x["gap"] for x in res[names[i]]}
                sb = {x["row"]["seed"]: x["gap"] for x in res[names[j]]}
                paired = [sa[s] - sb[s] for s in sorted(set(sa) & set(sb)) if sa[s] is not None and sb[s] is not None]
                out.append({"a": names[i], "b": names[j], "diff": d, "p": p, "paired": paired})
    return out


def main():
    rng = new_rng()
    idx = load_index()
    res = group_games(idx)
    for name, _ in GROUPS:
        gs = res[name]
        if not gs:
            print(f"\n== {name}: no games yet")
            continue
        s = summarise(gs, rng)
        tot, gaps, lo, hi, wins = s["tot"], s["gaps"], s["lo"], s["hi"], s["wins"]
        print(f"\n== {name}: {len(gs)} games, moles won {wins}")
        print(f"  crew suspicion gap per game: mean {statistics.fmean(gaps):+.1f}  95% [{lo:+.1f}, {hi:+.1f}]"
              f"  sd {statistics.stdev(gaps) if len(gaps) > 1 else float('nan'):.1f}")
        print(f"  pooled suspicion: of moles {tot['sm'] / max(1, tot['smn']):.1f}, of crew {tot['sc'] / max(1, tot['scn']):.1f}")
        print(f"  crew votes on a mole        {pct(tot['crew_on_mole'], tot['crew_votes'])}  chance {tot['exp_x1000'] / 10 / max(1, tot['crew_votes']):.0f}%")
        print(f"  eliminations hitting a mole {pct(tot['elims_mole'], tot['elims'])}")
        print(f"  jobs with a mole on team    {pct(tot['jobs_with_mole'], tot['jobs'])}")
        print(f"  mole on a job sabotaged     {pct(tot['mole_sabotage'], tot['mole_job_seats'])}")
        print(f"  mole votes at own partner   {pct(tot['mole_on_partner'], tot['mole_votes'])}")
        print(f"  mole statements with a self-tagged lie {pct(tot['mole_stmts_lie'], tot['mole_stmts'])}")
        print(f"  moles alive at end, per game {tot['moles_alive'] / len(gs):.2f}")
        for x in gs:
            r, t = x["row"], x["row"]["tokens"]
            gap = f"{x['gap']:+.1f}" if x["gap"] is not None else "n/a"
            print(f"   {r['batch']:14} seed {r['seed']}: {r['winner']:5} {r['reason']:10} rounds {r['rounds']} gap {gap:>6} "
                  f"crew-on-mole {x['g']['crew_on_mole']}/{x['g']['crew_votes']} calls {r['calls']} "
                  f"in {t['input'] + t['cache_read'] + t['cache_creation']:,} out {t['output']:,} (thinking {t['thinking']:,}) "
                  f"${t['cost_usd']:.2f} {r['wall_s'] / 60:.0f} min  served-other {x['mis']}")
        print(f"  totals: calls {sum(x['row']['calls'] for x in gs)}, notional ${sum(x['row']['tokens']['cost_usd'] for x in gs):.2f}")

    print("\n== Comparisons on the per-game suspicion gap (two-sided permutation test)")
    for c in comparisons(res, rng):
        d, p, paired = c["diff"], c["p"], c["paired"]
        pm = f"paired by seed ({len(paired)}): mean {statistics.fmean(paired):+.1f}, {sum(d > 0 for d in paired)} of {len(paired)} positive" if paired else ""
        print(f"  {c['a']} minus {c['b']}: {d:+.1f}  p = {p:.4f}   {pm}")


if __name__ == "__main__":
    main()
