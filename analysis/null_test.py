"""Null test N1 (docs/ANALYSIS.md, "Phase 1 — null test"): one model played twice as both moles.

Prints the per-seed crew gap of each run, the paired difference (run 1 minus run 2), the four N1
checks and the verdict. Reads the game logs only; makes no model calls.

    python3.11 analysis/null_test.py [--a bluff_haiku55] [--b bluff_haiku55_run2]

Gap per game: `analysis/bluff_score.py` (through `analysis/latest_models.py`, which also drops
spoiled games and counts mole fallback turns). Interval: bootstrap 95% over seeds (`bluff_score.boot`).
p: exact two-sided sign-flip (`bluff_mechanism.signflip_p`).
"""
from __future__ import annotations

import argparse
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bluff_score  # noqa: E402
import latest_models  # noqa: E402
from bluff_mechanism import signflip_p  # noqa: E402

MAX_MEAN_DIFF = 8.0     # points, either way (ANALYSIS.md N1)
MAX_WIN_DIFF = 5        # mole wins of 10: this many or more is a difference
P_MARK = 0.05
T_9 = 2.26              # ANALYSIS.md N1: smallest difference 10 seeds could show = 2.26 x SD / sqrt(10)


def run(a: str, b: str, index=None, root=None) -> dict:
    groups = [("run 1", [a]), ("run 2", [b])]
    out = latest_models.analyse(index, root, groups=groups, reference=())
    ms = {m["group"]: m for m in out["models"]}
    for g, _ in groups:
        if g not in ms:
            raise SystemExit(f"no games found for {g}")
    m1, m2 = ms["run 1"], ms["run 2"]
    g1 = {g["seed"]: g for g in m1["games"]}
    g2 = {g["seed"]: g for g in m2["games"]}
    seeds = [s for s in sorted(set(g1) & set(g2)) if g1[s]["gap"] is not None and g2[s]["gap"] is not None]
    d = [g1[s]["gap"] - g2[s]["gap"] for s in seeds]
    rng = bluff_score.new_rng()
    lo, hi = bluff_score.boot(d, rng)
    mean = statistics.fmean(d)
    sd = statistics.stdev(d)
    p = signflip_p(d, bluff_score.new_rng())
    w1 = sum(g["winner"] == "moles" for g in m1["games"])
    w2 = sum(g["winner"] == "moles" for g in m2["games"])
    checks = {
        "interval excludes zero": lo > 0 or hi < 0,
        f"sign-flip p below {P_MARK}": p < P_MARK,
        f"mean difference above {MAX_MEAN_DIFF} points": abs(mean) > MAX_MEAN_DIFF,
        f"mole wins differ by {MAX_WIN_DIFF} or more": abs(w1 - w2) >= MAX_WIN_DIFF,
    }
    return {"a": a, "b": b, "seeds": seeds, "g1": g1, "g2": g2, "d": d, "mean": mean, "ci": (lo, hi), "sd": sd,
            "p": p, "wins": (w1, w2), "n_games": (len(m1["games"]), len(m2["games"])), "checks": checks,
            "differ": any(checks.values()), "mdd": T_9 * sd / math.sqrt(len(d)), "m1": m1, "m2": m2}


def report(r: dict) -> str:
    L = [f"Null test N1: {r['a']} (run 1) against {r['b']} (run 2), paired by seed",
         f"games: {r['n_games'][0]} and {r['n_games'][1]}; seeds paired: {len(r['seeds'])}", "",
         "seed   run 1 gap  run 2 gap   run 1 - run 2   winners"]
    for s, dv in zip(r["seeds"], r["d"]):
        a, b = r["g1"][s], r["g2"][s]
        L.append(f"{s:>4}   {a['gap']:>+8.1f}   {b['gap']:>+8.1f}   {dv:>+8.1f}        {a['winner']} / {b['winner']}")
    L += ["",
          f"mean paired difference: {r['mean']:+.1f} points, bootstrap 95% over seeds [{r['ci'][0]:+.1f}, {r['ci'][1]:+.1f}]",
          f"sign-flip p (exact, two-sided): {r['p']:.4f}",
          f"SD of the paired differences: {r['sd']:.1f} points",
          f"mole wins: {r['wins'][0]} of {r['n_games'][0]} and {r['wins'][1]} of {r['n_games'][1]}", "",
          "N1 checks (any one true means the runs differ):"]
    L += [f"  {'YES' if v else 'no '}  {k}" for k, v in r["checks"].items()]
    L += ["", "VERDICT: THE RUNS DIFFER: stop and find the noise first" if r["differ"] else
          "VERDICT: no difference found between two runs of one model",
          f"smallest difference between two models that {len(r['d'])} seeds could show at this noise: "
          f"{r['mdd']:.1f} points (2.26 x SD / sqrt(n))",
          "This bounds the noise; it does not prove the runs are the same."]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--a", default="bluff_haiku55")
    ap.add_argument("--b", default="bluff_haiku55_run2")
    ap.add_argument("--index", default=None)
    ap.add_argument("--root", default=None)
    args = ap.parse_args(argv)
    print(report(run(args.a, args.b, args.index, args.root)))


if __name__ == "__main__":
    main()
