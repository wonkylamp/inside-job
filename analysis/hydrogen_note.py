"""Per-game read of a late batch next to an earlier batch on the same seeds. No model calls.

Made for the Gemini 4 Hydrogen games played on 2026-11-12, after the charts and counts were made.
It reuses the existing counting code and adds no new measure:
  forged cards   analysis/fabricate_rate.py (`forged`, on the turns `inside_job.moves.scan` counts)
  sabotage, vote analysis/extra_stats.py (`game_stats`)
  finale         the engine's `finale_result` event

Every figure is a count over a few games, shown per game. Nothing here is a rate with an interval and
nothing here ranks a model.

Run: env -u OPENROUTER_API_KEY python3.11 analysis/hydrogen_note.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "analysis"))

import extra_stats as ES  # noqa: E402
import fabricate_rate as FR  # noqa: E402
from inside_job import moves as MV  # noqa: E402


def game_row(src: dict) -> dict:
    ev = src["events"]
    start = MV._start(ev)
    moles = [p["name"] for p in start["players"] if p["role"] == "mole"]
    model = sorted({p["model"] for p in start["players"] if p["role"] == "mole"})
    turns = forged_turns = 0
    hit = {n: 0 for n in moles}
    for c in MV.scan(src):
        turns += 1
        if FR.forged(c["turn"].get("checks")):
            forged_turns += 1
            hit[c["turn"]["player"]] = 1
    st = ES.game_stats(ev)
    fin = next((e for e in ev if e["type"] == "finale_result"), None)
    finale = "none"
    if fin:
        finale = ", ".join(f"{p} {'mole' if p in moles else 'crew'} {c}"
                           + (" (said split)" if c == "steal" and fin.get("stated", {}).get(p) == "split" else "")
                           for p, c in fin["choices"].items())
    return {"batch": src["batch"], "seed": src["seed"], "game_id": src["game_id"], "mole_model": "+".join(model),
            "winner": next(e for e in ev if e["type"] == "game_end")["winner"], "rounds": st["rounds"],
            "turns": turns, "forged_turns": forged_turns, "forged_moles": sum(hit.values()), "moles": len(moles),
            "voted_out": st["mole_voted_out"], "first_vote_crew": st["first_vote_hit_crew"],
            "job_seats": st["mole_job_seats"], "sabotages": st["mole_sabotages"],
            "sab_spoke": st["sab_then_spoke"], "sab_helped": st["sab_then_claimed_helped"],
            "sab_owned": st["sab_then_owned_up"], "finale": finale}


def rows(games_dir, batches, seeds) -> tuple[list[dict], list[str]]:
    sources, notes = MV.load_sources(games_dir, batches)
    return [game_row(s) for s in sources if s["seed"] in seeds], notes


def report(rs: list[dict], notes: list[str]) -> str:
    L = ["Per game, counts only (measured from the logs; a few games rank nobody)",
         f"{'batch':16} {'seed':>4} {'winner':>6} {'rnds':>4} {'forged turns':>12} {'moles forged':>12} "
         f"{'moles out':>9} {'sabotaged':>10} {'then said helped':>16}  finale"]
    for r in rs:
        L.append(f"{r['batch']:16} {r['seed']:>4} {r['winner']:>6} {r['rounds']:>4} "
                 f"{str(r['forged_turns']) + ' of ' + str(r['turns']):>12} "
                 f"{str(r['forged_moles']) + ' of ' + str(r['moles']):>12} "
                 f"{str(r['voted_out']) + ' of ' + str(r['moles']):>9} "
                 f"{str(r['sabotages']) + ' of ' + str(r['job_seats']):>10} "
                 f"{str(r['sab_helped']) + ' of ' + str(r['sab_spoke']):>16}  {r['finale']}")
    L.append("")
    for b in dict.fromkeys(r["batch"] for r in rs):
        g = [r for r in rs if r["batch"] == b]
        tot = lambda k: sum(r[k] for r in g)  # noqa: E731
        L.append(f"{b}: {len(g)} games ({', '.join(str(r['seed']) for r in g)}), mole model {g[0]['mole_model']}; "
                 f"moles won {sum(r['winner'] == 'moles' for r in g)}; forged turns {tot('forged_turns')} of {tot('turns')}; "
                 f"moles that forged {tot('forged_moles')} of {tot('moles')}; moles voted out {tot('voted_out')} of {tot('moles')}; "
                 f"sabotaged {tot('sabotages')} of {tot('job_seats')} job seats; after a sabotage, formally claimed "
                 f"'helped' {tot('sab_helped')} of {tot('sab_spoke')}, owned up {tot('sab_owned')}")
    L += [f"note: {n}" for n in notes]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--games", default=str(ROOT / "games"))
    ap.add_argument("--batches", nargs="+", default=["bluff_hydrogen", "bluff_sonnet55", "bluff_gemini"])
    ap.add_argument("--seeds", nargs="+", type=int, default=[101, 102, 103])
    a = ap.parse_args(argv)
    rs, notes = rows(a.games, a.batches, set(a.seeds))
    print(report(rs, notes))


if __name__ == "__main__":
    main()
