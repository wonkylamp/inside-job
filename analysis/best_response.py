"""Best-response search over scripted crew and mole policies, with the CLAIMS metrics.

    python3.11 -m analysis.best_response            # full run: games, checks, report
    python3.11 -m analysis.best_response --report   # rebuild the report from the saved rows

Bot games only, in memory: no model calls, nothing written under games/. Writes
analysis/out/best_response.md, best_response_cells.jsonl and best_response_rows.pkl.gz (per-game
rows, so the report can be rebuilt without replaying).

Bots show what the rules and the metric definitions allow; they are not how real models play.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import pickle
import sys
import time
from collections import Counter, defaultdict
from multiprocessing import Pool
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inside_job.bots import game_summary, play_bot_game, wilson          # noqa: E402
from inside_job.clues import card_as_clue                                # noqa: E402
from inside_job.config import config_from_dict, load_raw                 # noqa: E402
from inside_job.log import project, visible_to                           # noqa: E402
from inside_job.solver import from_log, player_worlds, posterior, table_posterior, table_worlds  # noqa: E402

from analysis.strategies import (CREW_DULL, CREW_POLICIES, MOLE_DULL, MOLE_POLICIES, crew_cond,  # noqa: E402
                                 play_policy_game, weighted_posterior)

OUT = ROOT / "analysis" / "out"
CONFIG = ROOT / "config" / "default.toml"
SEED0 = 100000
GAMES = 1000
SPREAD_GAMES = 1000          # logician skill cells
SPREAD_GAMES_MOLES = 500     # mole-policy cells at the extra settings
SPREAD_MOLES = ("smart+decoy", "always+decoy", "never+decoy", "late2", "closer", "mute")
SPREAD_SETTINGS = {"clean4": {"clean_target": 4}, "job2": {"job_size": 2},
                   "rec2": {"clue_recipients": 2}, "rec4": {"clue_recipients": 4}}
BOOT = 2000
BOOT_SEED = 20261110
CHUNK = 100

CREW_VARIANTS = ("logged", "exact", "base", "public", "shrink66", "shrink33", "push", "bayes50", "bayes90")
MOLE_VARIANTS = ("logged", "public", "base", "shrink66", "shrink33", "push", "truth", "crew_cond")


# --------------------------------------------------------------------------- per-game metrics

def _r(p: float) -> float:
    """As written in `suspicion`: a whole percent."""
    return int(round(100 * p)) / 100


def _brier(p: dict, truth: dict, names) -> float:
    return sum((p[n] - truth[n]) ** 2 for n in names) / len(names)


def analyse_game(events: list[dict], test_crew, full: bool = True) -> dict:
    """Win, Getaway, Read and Table read for one game, walking the log once.

    Read: every crew reading by a test-crew player (non-fallback), Brier of each report variant
    minus the Brier of the ideal reasoner (`player_worlds` posterior with the fallback) on the
    information that seat had strictly before the turn. Table read: every mole reading, squared
    error against the mean of the alive crew's latest stated suspicion (before the turn), minus the
    same for the public posterior. Getaway: per round that starts with a mole alive."""
    start, end = events[0], events[-1]
    table = next(e for e in events if e["type"] == "table")
    seats, nm = list(table["seats"]), table["num_moles"]
    moles = set(start["moles"])
    role = {p["name"]: p["role"] for p in start["players"]}
    truth = {n: 1.0 if n in moles else 0.0 for n in seats}
    test_crew = set(test_crew)
    own = {n: [] for n in seats}
    pair = {n: [] for n in seats}
    cards, jobs, revealed = [], [], {}
    alive = list(seats)
    latest = {}                                   # crew -> {x: p}
    cache = {}
    pcache = {}
    read = defaultdict(float)
    read_n = 0
    brier_ideal = 0.0
    tr = defaultdict(float)
    tr_n = 0
    rounds = {}                                   # round -> dict
    rnd = 0

    def public_post():
        k = (len(cards), len(jobs), len(revealed))
        if k not in pcache:
            w = table_worlds(seats, nm, revealed, cards, jobs)
            fb = table_worlds(seats, nm, revealed, [], jobs)
            pcache[k] = (posterior(w, seats, fb), w, fb)
        return pcache[k]

    def seat_post(p):
        k = (p, len(cards), len(pair[p]), len(own[p]), len(jobs), len(revealed))
        if k not in cache:
            w = player_worlds(seats, nm, revealed, cards, jobs, player=p, own_clues=own[p], pair_cards=pair[p])
            fb = [x for x in table_worlds(seats, nm, revealed, [], jobs) if p not in x]
            cache[k] = {"exact": posterior(w, seats, fb),
                        "bayes50": weighted_posterior(w, seats, jobs, 0.5, fb),
                        "bayes90": weighted_posterior(w, seats, jobs, 0.9, fb)}
        return cache[k]

    for e in events:
        t = e["type"]
        if t == "round_start":
            rnd = e["round"]
            alive = list(e["alive"])
            rounds[rnd] = {"mole_in": any(a in moles for a in alive), "blown": None, "share": None,
                           "on_team": False}
        elif t == "clue":
            own[e["player"]].append(e["clue"])
        elif t == "job_result":
            jobs.append((list(e["team"]), e["sabotages"]))
            rounds[e["round"]]["blown"] = bool(e["blown"])
            rounds[e["round"]]["on_team"] = any(t in moles for t in e["team"])
        elif t == "vote_result":
            revealed[e["eliminated"]] = e["role"]
            alive = [a for a in alive if a != e["eliminated"]]
            cv = [v for voter, v in e["votes"].items() if role[voter] == "crew"]
            rounds[e["round"]]["share"] = (sum(1 for v in cv if v in moles) / len(cv)) if cv else 0.0
        elif t == "turn":
            act = e.get("action") or {}
            sus = act.get("suspicion")
            p = e["player"]
            if sus and not e.get("fallback") and full:
                names = [n for n in sus if n in truth]
                out_m = sum(1 for r in revealed.values() if r == "mole")
                others = [a for a in alive if a != p]
                base = (nm - out_m) / len(others) if others else 0.0
                if e.get("suspicion_kind") == "belief" and p in test_crew and names:
                    sp = seat_post(p)
                    ex = sp["exact"]
                    pub = public_post()[0]
                    var = {"logged": {n: min(100, max(0, sus[n])) / 100 for n in names},
                           "exact": {n: _r(ex[n]) for n in names},
                           "base": {n: _r(base) for n in names},
                           "public": {n: _r(pub[n]) for n in names},
                           "shrink66": {n: _r(base + 0.66 * (ex[n] - base)) for n in names},
                           "shrink33": {n: _r(base + 0.33 * (ex[n] - base)) for n in names},
                           "push": {n: 1.0 if ex[n] >= 0.5 else 0.0 for n in names},
                           "bayes50": {n: _r(sp["bayes50"][n]) for n in names},
                           "bayes90": {n: _r(sp["bayes90"][n]) for n in names}}
                    b0 = _brier(ex, truth, names)
                    brier_ideal += b0
                    for v, pv in var.items():
                        read[v] += _brier(pv, truth, names) - b0
                    read_n += 1
                elif e.get("suspicion_kind") == "table_read" and names:
                    crew_alive = [a for a in alive if role[a] == "crew"]
                    tgt = {}
                    for x in names:
                        vals = [latest[c][x] for c in crew_alive if c != x and c in latest and x in latest[c]]
                        if vals:
                            tgt[x] = sum(vals) / len(vals)
                    if tgt:
                        pub = public_post()[0]
                        ck = ("cc", len(cards), len(jobs), len(revealed), tuple(crew_alive))
                        if ck not in pcache:
                            pcache[ck] = crew_cond(seats, nm, revealed, cards, jobs, crew_alive)
                        cc = pcache[ck]
                        xs = list(tgt)
                        var = {"logged": {n: min(100, max(0, sus[n])) / 100 for n in xs},
                               "public": {n: _r(pub[n]) for n in xs},
                               "base": {n: _r(base) for n in xs},
                               "shrink66": {n: _r(base + 0.66 * (pub[n] - base)) for n in xs},
                               "shrink33": {n: _r(base + 0.33 * (pub[n] - base)) for n in xs},
                               "push": {n: 1.0 if pub[n] >= 0.5 else 0.0 for n in xs},
                               "truth": {n: truth[n] for n in xs},
                               "crew_cond": {n: _r(cc[n]) for n in xs}}
                        e0 = sum((pub[n] - tgt[n]) ** 2 for n in xs) / len(xs)
                        for v, pv in var.items():
                            tr[v] += sum((pv[n] - tgt[n]) ** 2 for n in xs) / len(xs) - e0
                        tr_n += 1
                if role[p] == "crew":
                    latest[p] = {n: min(100, max(0, v)) / 100 for n, v in sus.items()}
            tp = e.get("turn_phase")
            if tp == "discuss":
                cards += [(p, card_as_clue(c)) for c in act.get("clue_cards") or []]
            elif tp == "whisper":
                pair[e["partner"]] += [(p, card_as_clue(c)) for c in act.get("clue_cards") or []]

    # Getaway
    scores = []
    for r, d in sorted(rounds.items()):
        if not d["mole_in"] or d["blown"] is None:
            continue
        if not d["blown"]:
            scores.append(0.0)
        elif d["share"] is None:                  # blown and the game ended on that job
            scores.append(1.0)
        else:
            scores.append(1.0 - d["share"])
    shares = [d["share"] for d in rounds.values() if d["share"] is not None]
    per_round = [(int(d["on_team"]), int(bool(d["blown"])), d["share"]) for r, d in sorted(rounds.items())
                 if d["mole_in"] and d["blown"] is not None]
    sab = opp = 0
    for e in events:
        if e["type"] == "job_choices":
            for n, c in e["choices"].items():
                if n in moles:
                    opp += 1
                    sab += c == "sabotage"
    return {"seed": start["seed"], "winner": end["winner"], "reason": end["reason"], "rounds": end["rounds"],
            "clean": end["clean_jobs"], "blown": end["blown_jobs"], "fallbacks": end["fallbacks"],
            "retries": sum(1 for e in events if e["type"] == "turn" and e.get("attempts", 1) > 1),
            "getaway": (sum(scores) / len(scores)) if scores else None,
            "read": {v: read[v] / read_n for v in CREW_VARIANTS} if read_n else None, "read_n": read_n,
            "brier_ideal": brier_ideal / read_n if read_n else None,
            "tr": {v: tr[v] / tr_n for v in MOLE_VARIANTS} if tr_n else None, "tr_n": tr_n,
            "crew_mole_votes": (sum(shares) / len(shares)) if shares else None,
            "sabotages": sab, "mole_opps": opp, "per_round": per_round}


# --------------------------------------------------------------------------- cells

def cfg_for(settings: dict):
    raw = load_raw(CONFIG)
    raw["game"].update(settings)
    return config_from_dict(raw)


_CFG = {}


def _init_worker():
    from analysis.strategies import install_memo
    install_memo()


def run_chunk(task):
    cell, lo, hi = task
    key = json.dumps(cell["settings"], sort_keys=True)
    if key not in _CFG:
        _CFG[key] = cfg_for(cell["settings"])
    cfg = _CFG[key]
    cs = CREW_POLICIES[cell["crew"]]
    ms = MOLE_POLICIES[cell["moles"]]
    dev = CREW_POLICIES[cell["deviator"]] if cell.get("deviator") else None
    rows = []
    for s in range(lo, hi):
        ev, test = play_policy_game(cfg, s, cs, ms, deviator=dev)
        rows.append(analyse_game(ev, test, full=cell.get("full", True)))
    return cell["id"], rows


def make_cells():
    cells = []
    for tgt in (3, 2):
        st = {"sabotage_target": tgt}
        for c in CREW_POLICIES:
            for m in MOLE_POLICIES:
                cells.append({"id": f"main|t{tgt}|{c}|{m}", "kind": "main", "settings": st, "crew": c, "moles": m,
                              "games": GAMES, "seed": SEED0,
                              "full": c == "logician_1.0" or m == "smart+decoy"})
        for c in CREW_POLICIES:
            if c == "logician_1.0" or tgt != 3:
                continue
            for m in ("smart+decoy",):
                cells.append({"id": f"dev|t{tgt}|{c}|{m}", "kind": "dev", "settings": st, "crew": "logician_1.0",
                              "deviator": c, "moles": m, "games": GAMES, "seed": SEED0})
    spread_settings = SPREAD_SETTINGS
    spread_moles = SPREAD_MOLES
    for name, st in spread_settings.items():
        for c in ("logician_1.0", "logician_0.7", "logician_0.4"):
            cells.append({"id": f"spread|{name}|{c}|smart+decoy", "kind": "spread", "settings": st, "crew": c,
                          "moles": "smart+decoy", "games": SPREAD_GAMES, "seed": SEED0, "setting": name})
        for m in spread_moles:
            if m == "smart+decoy":
                continue
            cells.append({"id": f"spread|{name}|logician_1.0|{m}", "kind": "spread", "settings": st,
                          "crew": "logician_1.0", "moles": m, "games": SPREAD_GAMES_MOLES, "seed": SEED0,
                          "setting": name, "full": False})
    return cells


def run_cells(cells, workers):
    tasks = []
    for c in cells:
        for lo in range(c["seed"], c["seed"] + c["games"], CHUNK):
            tasks.append((c, lo, min(lo + CHUNK, c["seed"] + c["games"])))
    # long cells first for better packing
    rows = defaultdict(list)
    t0 = time.monotonic()
    done = 0
    with Pool(workers, initializer=_init_worker) as pool:
        for cid, rs in pool.imap_unordered(run_chunk, tasks, chunksize=1):
            rows[cid] += rs
            done += 1
            if done % 200 == 0:
                el = time.monotonic() - t0
                print(f"  {done}/{len(tasks)} chunks, {el:.0f}s, eta {el / done * (len(tasks) - done):.0f}s",
                      flush=True)
    for cid in rows:
        rows[cid].sort(key=lambda r: r["seed"])
    return rows


# --------------------------------------------------------------------------- statistics

def boot_mean(x, B=BOOT, seed=BOOT_SEED):
    x = np.asarray([v for v in x if v is not None], dtype=float)
    if len(x) == 0:
        return None, (None, None)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), size=(B, len(x)))
    m = x[idx].mean(axis=1)
    return float(x.mean()), (float(np.quantile(m, 0.025)), float(np.quantile(m, 0.975)))


def boot_paired(a, b, B=BOOT, seed=BOOT_SEED):
    """Mean of a - b paired by seed (rows in the same seed order), percentile interval."""
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    d = np.asarray([x - y for x, y in pairs], dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(d), size=(B, len(d)))
    m = d[idx].mean(axis=1)
    return float(d.mean()), (float(np.quantile(m, 0.025)), float(np.quantile(m, 0.975)))


def spearman(x, y):
    def rank(v):
        v = np.asarray(v, dtype=float)
        order = v.argsort()
        r = np.empty(len(v))
        r[order] = np.arange(len(v))
        for val in np.unique(v):                          # average ranks for ties
            m = v == val
            r[m] = r[m].mean()
        return r
    rx, ry = rank(x), rank(y)
    return float(np.corrcoef(rx, ry)[0, 1])


def summarise(cell, rows):
    n = len(rows)
    crew = sum(1 for r in rows if r["winner"] == "crew")
    lo, hi = wilson(crew, n)
    reasons = Counter(r["reason"] for r in rows)
    ga, ga_ci = boot_mean([r["getaway"] for r in rows])
    read = {}
    for v in CREW_VARIANTS:
        m, ci = boot_mean([r["read"][v] if r["read"] else None for r in rows])
        read[v] = {"mean": m, "ci": ci}
    trd = {}
    for v in MOLE_VARIANTS:
        m, ci = boot_mean([r["tr"][v] if r["tr"] else None for r in rows])
        trd[v] = {"mean": m, "ci": ci}
    opp = sum(r["mole_opps"] for r in rows)
    return {"id": cell["id"], "kind": cell["kind"], "settings": cell["settings"], "crew": cell["crew"],
            "deviator": cell.get("deviator"), "moles": cell["moles"], "games": n,
            "seeds": [rows[0]["seed"], rows[-1]["seed"]],
            "crew_win": crew / n, "crew_win_ci": [lo, hi], "rounds": sum(r["rounds"] for r in rows) / n,
            "reasons": {k: v / n for k, v in sorted(reasons.items())},
            "getaway": ga, "getaway_ci": ga_ci,
            "read": read, "table_read": trd,
            "brier_ideal": boot_mean([r["brier_ideal"] for r in rows])[0],
            "crew_mole_votes": boot_mean([r["crew_mole_votes"] for r in rows])[0],
            "sabotage_rate": sum(r["sabotages"] for r in rows) / opp if opp else 0.0,
            "fallbacks": sum(r["fallbacks"] for r in rows), "retries": sum(r["retries"] for r in rows)}


# --------------------------------------------------------------------------- checks

def _strip(evs):
    return [{k: v for k, v in e.items() if k != "wall_s"} for e in evs]


class Audit:
    """The tests/test_bots.py audit: before every bot turn the view must be exactly the
    `visible_to` / `project` events for that player, with no engine-only events or fields."""

    def __init__(self):
        self.game = None
        self.n = 0
        self.errors = 0

    def __call__(self, player, view):
        events = self.game.log.events
        by_seq = {e["seq"]: e for e in events}
        allowed = [project(e, player) for e in events if visible_to(e, player)]
        ok = view == [a for a in allowed if a is not None]
        for v in view:
            o = by_seq[v["seq"]]
            ok = ok and visible_to(o, player) and o["type"] != "clue_deal" and "checks" not in v and "blocked" not in v
        self.n += 1
        self.errors += not ok


def run_checks(log):
    out = {}
    raw = load_raw(CONFIG)
    # 1. reproduce the shipped command on seeds 1000..1299
    rep = {}
    for tgt, want in ((3, 0.860), (2, 0.397)):
        r = json.loads(json.dumps(raw))
        r["game"]["sabotage_target"] = tgt
        cfg = config_from_dict(r)
        mine = [play_policy_game(cfg, s, CREW_POLICIES["logician_1.0"], MOLE_POLICIES["smart+decoy"])[0]
                for s in range(1000, 1300)]
        win = sum(1 for ev in mine if ev[-1]["winner"] == "crew") / 300
        same = 0
        for s, ev in zip(range(1000, 1300), mine):
            ref = play_bot_game(cfg, s, crew="logician", crew_skill=1.0, moles="smart", mole_cards="decoy")
            same += _strip(ref) == _strip(ev)
        rep[tgt] = {"crew_win": win, "expected": want, "identical_logs": same, "games": 300}
        log(f"  reproduce target {tgt}: crew win {100 * win:.1f}% (expected {100 * want:.1f}%), "
            f"{same}/300 logs identical to the shipped bots")
    out["reproduce"] = rep
    # 2. audit every new policy for 50 games
    cfg = config_from_dict(raw)
    aud = {}
    combos = [(c, "smart+decoy") for c in CREW_POLICIES] + [("logician_1.0", m) for m in MOLE_POLICIES]
    for c, m in combos:
        a = Audit()
        for s in range(SEED0, SEED0 + 50):
            play_policy_game(cfg, s, CREW_POLICIES[c], MOLE_POLICIES[m], audit=a)
        aud[f"{c} vs {m}"] = {"turns": a.n, "errors": a.errors}
    a = Audit()
    for s in range(SEED0, SEED0 + 50):
        play_policy_game(cfg, s, CREW_POLICIES["logician_1.0"], MOLE_POLICIES["smart+decoy"],
                         deviator=CREW_POLICIES["silent"], audit=a)
    aud["deviator silent"] = {"turns": a.n, "errors": a.errors}
    out["audit"] = aud
    log(f"  audit: {sum(v['turns'] for v in aud.values())} turns over {len(aud)} policy pairs x 50 games, "
        f"{sum(v['errors'] for v in aud.values())} view errors")
    # 3. determinism
    det = 0
    for c, m in (("bandwagon", "mimic"), ("random", "bus"), ("bayes_crew", "closer")):
        for s in (SEED0, SEED0 + 7):
            a1 = _strip(play_policy_game(cfg, s, CREW_POLICIES[c], MOLE_POLICIES[m])[0])
            a2 = _strip(play_policy_game(cfg, s, CREW_POLICIES[c], MOLE_POLICIES[m])[0])
            det += a1 == a2
    out["determinism"] = {"identical": det, "of": 6}
    log(f"  determinism: {det}/6 repeated games identical")
    # 4. metric plumbing: post-hoc solver == logician's logged suspicion; == from_log(seq-1)
    mism = checked = fl = 0
    for s in range(SEED0, SEED0 + 30):
        ev, test = play_policy_game(cfg, s, CREW_POLICIES["logician_1.0"], MOLE_POLICIES["smart+decoy"])
        row = analyse_game(ev, test)
        if row["read"] and abs(row["read"]["logged"] - row["read"]["exact"]) > 1e-12:
            mism += 1
        checked += 1
        for t in ev:
            if t["type"] == "turn" and t.get("suspicion_kind") == "belief":
                post = table_posterior(from_log(ev, upto_seq=t["seq"] - 1, viewpoint=t["player"]))
                if any(int(round(100 * post[n])) != v for n, v in t["action"]["suspicion"].items()):
                    fl += 1
    out["plumbing"] = {"games": checked, "logged_vs_posthoc_mismatch": mism, "from_log_mismatch_readings": fl}
    log(f"  plumbing: logged logician suspicion vs post-hoc solver, {mism}/{checked} games differ; "
        f"vs from_log(seq-1): {fl} readings differ")
    # 5. report variants written by the bots equal the post-hoc variants
    from analysis.strategies import crew as mkcrew, mole as mkmole
    vm = 0
    vn = 0
    for rep_name, post_name in (("base", "base"), ("exact", "exact"), ("public", "public"), ("shrink:0.66", "shrink66"),
                                ("push", "push"), ("bayes:0.9", "bayes90")):
        for s in range(SEED0, SEED0 + 10):
            ev, test = play_policy_game(cfg, s, mkcrew(report=rep_name), MOLE_POLICIES["smart+decoy"])
            row = analyse_game(ev, test)
            vn += 1
            if abs(row["read"]["logged"] - row["read"][post_name]) > 1e-9:
                vm += 1
    for rep_name, post_name in (("base", "base"), ("public", "public"), ("truth", "truth"),
                                ("crew_cond", "crew_cond"), ("shrink:0.33", "shrink33")):
        for s in range(SEED0, SEED0 + 10):
            ev, test = play_policy_game(cfg, s, CREW_POLICIES["logician_1.0"], mkmole(report=rep_name))
            row = analyse_game(ev, test)
            if row["tr"]:
                vn += 1
                if abs(row["tr"]["logged"] - row["tr"][post_name]) > 1e-9:
                    vm += 1
    out["report_variants"] = {"games": vn, "mismatch": vm}
    log(f"  report-variant bots vs post-hoc variants: {vm}/{vn} games differ")
    # 6. the speed memo used by the workers changes nothing
    pairs = [("logician_1.0", "smart+decoy"), ("bandwagon", "mimic"), ("random", "bus"), ("jobs_only", "closer"),
             ("dull_jobs", "leader_clean")]
    refs = {pr: [_strip(play_policy_game(cfg, s, CREW_POLICIES[pr[0]], MOLE_POLICIES[pr[1]])[0])
                 for s in range(SEED0, SEED0 + 40)] for pr in pairs}
    from analysis.strategies import install_memo
    install_memo()
    same = sum(_strip(play_policy_game(cfg, s, CREW_POLICIES[pr[0]], MOLE_POLICIES[pr[1]])[0]) == e
               for pr in pairs for s, e in zip(range(SEED0, SEED0 + 40), refs[pr]))
    out["memo"] = {"identical": same, "of": 40 * len(pairs)}
    log(f"  memoised solver: {same}/{40 * len(pairs)} games identical to unmemoised play")
    return out


def _checks_quiet():
    lines = []
    out = run_checks(lines.append)
    out["lines"] = lines
    return out


# --------------------------------------------------------------------------- report

def pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}"


def ci_s(ci, scale=100, fmt="{:.1f}"):
    if ci is None or ci[0] is None:
        return ""
    return f"({fmt.format(scale * ci[0])} to {fmt.format(scale * ci[1])})"


def num(x, fmt="{:+.4f}"):
    return "n/a" if x is None else fmt.format(x)


def build_report(cells, summ, rows, checks, wall, cmd):
    S = {c["id"]: summ[c["id"]] for c in cells}
    crews = list(CREW_POLICIES)
    moles = list(MOLE_POLICIES)
    L = []
    w = L.append

    def cell(kind, tgt, c, m):
        return S.get(f"{kind}|t{tgt}|{c}|{m}")

    def R(kind, tgt, c, m):
        return rows[f"{kind}|t{tgt}|{c}|{m}"]

    # ---------------- exploits (filled from the numbers below)
    findings = compute_findings(S, rows)

    w("# Inside Job: best-response search over scripted policies")
    w("")
    w(f"Generated by `{cmd}` in {wall / 60:.1f} min. Scripted bots only, played in memory; no model calls, "
      "nothing written to `games/`. Config `config/default.toml` (rules v0.3) with the dials named per table. "
      f"Every main cell plays the same {GAMES} seeds {SEED0}..{SEED0 + GAMES - 1} (the deal, seats and first "
      "leader are fixed by the seed; play then diverges). Intervals: crew win rate, 95% Wilson; every other "
      f"mean, 95% percentile bootstrap over games (seeds), {BOOT} resamples (numpy seed {BOOT_SEED}); "
      "differences between policies are paired by seed and bootstrapped the same way.")
    w("")
    w("**Bots are not models.** Every number here is what these scripts do under these rules. A script that "
      "scores well shows the rules or a metric *allow* that score without the skill; it does not show a model "
      "would find it, or that models play like the scripts. Where the reference side is a script, its tells "
      "(fixed accusation and voting rules, decoy logic) are part of what is being exploited.")
    w("")
    w("## Exploits found")
    w("")
    for f in findings["found"]:
        w(f"- {f}")
    w("")
    w("## Tried, not found")
    w("")
    for f in findings["not_found"]:
        w(f"- {f}")
    w("")
    w("## Checks")
    w("")
    if checks is None:
        checks = {"reproduce": {3: {"crew_win": 0, "expected": 0.86, "identical_logs": 0},
                                2: {"crew_win": 0, "expected": 0.397, "identical_logs": 0}},
                  "audit": {"none": {"turns": 0, "errors": 0}}, "determinism": {"identical": 0, "of": 0},
                  "plumbing": {"games": 0, "logged_vs_posthoc_mismatch": 0, "from_log_mismatch_readings": 0},
                  "report_variants": {"games": 0, "mismatch": 0}}
        w("- CHECKS SKIPPED (pilot run).")
    rp = checks["reproduce"]
    for t in (3, 2):
        w(f"- Reproduction, `logician 1.0` vs `smart`+decoy, sabotage_target {t}, seeds 1000..1299: crew win "
          f"{pct(rp[t]['crew_win'])}% (the shipped `bots` command gives {pct(rp[t]['expected'])}%); "
          f"{rp[t]['identical_logs']}/300 game logs identical event for event to `inside_job.bots.play_bot_game`.")
    nv = [s for s in summ.values() if s["moles"].startswith("never") and s["getaway"] is not None]
    w(f"- `never` moles: Getaway exactly 0 in every cell: {all(s['getaway'] == 0 for s in nv)} "
      f"({len(nv)} cells, max {max(s['getaway'] for s in nv):.3g}).")
    au = checks["audit"]
    w(f"- View audit (the `tests/test_bots.py` hook: before every turn the bot's view equals the "
      f"`visible_to`/`project` events for that player, no `clue_deal`, `checks` or `blocked`): "
      f"{sum(v['turns'] for v in au.values())} turns, {len(au)} policy pairs x 50 games, "
      f"{sum(v['errors'] for v in au.values())} errors.")
    w(f"- Determinism: {checks['determinism']['identical']}/{checks['determinism']['of']} repeated games "
      "identical; the whole run uses fixed seeds and a fixed bootstrap seed.")
    pl = checks["plumbing"]
    w(f"- Metric plumbing: the logician's logged suspicion equals the post-hoc solver posterior (Read of the "
      f"logged report minus Read of `exact` = 0) in {pl['games'] - pl['logged_vs_posthoc_mismatch']}/{pl['games']} "
      f"games, and equals `table_posterior(from_log(events, upto_seq=seq-1, viewpoint=player))` in every reading "
      f"({pl['from_log_mismatch_readings']} mismatches).")
    w(f"- Report-variant bots (that write the variant into `suspicion` themselves) match the post-hoc variant "
      f"in {checks['report_variants']['games'] - checks['report_variants']['mismatch']}/"
      f"{checks['report_variants']['games']} games.")
    if "memo" in checks:
        w(f"- Speed memo (workers memoise the pure `solver.table_worlds` in memory; no file changed): "
          f"{checks['memo']['identical']}/{checks['memo']['of']} games identical to unmemoised play.")
    fb = sum(s["fallbacks"] for s in summ.values())
    rt = sum(s["retries"] for s in summ.values())
    w(f"- Fallback turns over all cells: {fb}; retried turns: {rt}.")
    w("")

    # ---------------- policies
    w("## Policies")
    w("")
    w("Crew (applied to all five crew seats, as in a crew trial):")
    w("")
    desc_c = {
        "logician_1.0": "shipped logician: solver belief, tables every real clue, picks self + least suspected, accuses/votes the most suspected",
        "logician_0.7": "logician, 30% of decisions random", "logician_0.4": "logician, 60% of decisions random",
        "silent": "logician that never tables or whispers a card",
        "jobs_only": "belief from job results and reveals only (ignores own clues and every card); still tables its clues",
        "own_only": "belief from own clues, job results, reveals; ignores everyone's cards; still tables",
        "bandwagon": "logician, but accuses and votes whoever has the most public accusations this round (first accused on ties)",
        "random": "every decision random (logician skill 0)",
        "repeat_clean": "logician, but as leader re-picks the most recent clean team if all are still in",
        "no_blown": "logician, but as leader never picks anyone who was on a blown job (if enough others)",
        "blown_seat": "logician, but accuses and votes the alive player on most blown jobs (seat order on ties)",
        "dull_jobs": "no reasoning at all: no cards, picks self + seat order skipping blown-job members, votes blown-job members else first seat",
        "seat_vote": "logician, but everyone accuses and votes the first other alive player in seat order",
        "bayes_crew": "logician whose belief weights worlds by the job likelihood (q = 0.9)",
    }
    for c in crews:
        w(f"- `{c}`{' (dull)' if c in CREW_DULL else ''}: {desc_c[c]}.")
    w("")
    w("Moles (both seats):")
    w("")
    desc_m = {
        "smart+decoy": "shipped smart: lowest-seat mole on a team sabotages; one fake card a round",
        "smart+none": "smart, no cards", "always+decoy": "both sabotage whenever on a team; decoys",
        "always+none": "always, no cards", "never+decoy": "never sabotage; decoys", "never+none": "never, no cards",
        "late2": "help in round 1, smart from round 2", "late3": "help in rounds 1-2, smart from round 3",
        "closer": "sabotage only when a blown job wins now or a clean job would win it for the crew",
        "bus": "smart, but accuses and votes the partner once its public posterior is >= 0.5",
        "mute": "smart sabotage; no cards, no accusation, no job claim, empty statements",
        "mimic": "smart sabotage; tables only its own real clues that do not raise a mole's public posterior; picks, accuses and votes as a logician would from the public view (may hit the partner)",
        "leader_clean": "as leader picks three crew (job runs clean); sabotages like smart otherwise",
        "target_trusted": "smart, but accuses and votes the crew member the table trusts most",
    }
    for m in moles:
        w(f"- `{m}`{' (dull)' if m in MOLE_DULL else ''}: {desc_m[m]}.")
    w("")
    w("Report variants change no play; they are computed post hoc from each reading's information "
      "(checked above against bots that write them). Crew: `logged` (what the policy wrote), `exact` "
      "(ideal reasoner on the seat's view), `base` (moles left / others alive), `public` (solver on public "
      "information only), `shrink66`/`shrink33` (base + 0.66 or 0.33 x (exact - base)), `push` (1 if exact >= 0.5 "
      "else 0), `bayes50`/`bayes90` (solver worlds weighted by the likelihood of the job results with a mole on a "
      "team sabotaging independently with probability q). Moles: `logged`, `public` (the baseline itself), `base`, "
      "`shrink66`/`shrink33` (towards base from public), `push`, `truth` (1 for moles, 0 for crew), `crew_cond` "
      "(for each player, the mean over the alive crew c of the public posterior restricted to worlds without c: "
      "public information plus the mole's knowledge of who is crew). All written as whole percents.")
    w("")

    # ---------------- payoff matrices
    for tgt in (3, 2):
        w(f"## Payoff matrix, sabotage_target {tgt}: crew win % (95% Wilson), {GAMES} games per cell")
        w("")
        w("| crew \\ moles | " + " | ".join(f"`{m}`" for m in moles) + " | min |")
        w("|---|" + "---|" * (len(moles) + 1))
        for c in crews:
            vals = [cell("main", tgt, c, m) for m in moles]
            w(f"| `{c}` | " + " | ".join(f"{pct(v['crew_win'])} {ci_s(v['crew_win_ci'], fmt='{:.0f}')}" for v in vals)
              + f" | {pct(min(v['crew_win'] for v in vals if not v['moles'].startswith('never')))} |")
        w("| **max** | " + " | ".join(pct(max(cell("main", tgt, c, m)["crew_win"] for c in crews)) for m in moles)
          + " | |")
        w("")
        w("(`min` excludes the `never` columns, which no mole would pick.)")
        w("")
        w(f"Mean rounds and end reasons, sabotage_target {tgt} (crew `logician_1.0` row and mole `smart+decoy` column):")
        w("")
        w("| cell | rounds | jobs_clean | moles_out | sabotage | other | sabotage rate |")
        w("|---|---|---|---|---|---|---|")
        for c, m in [("logician_1.0", m) for m in moles] + [(c, "smart+decoy") for c in crews if c != "logician_1.0"]:
            v = cell("main", tgt, c, m)
            rs = v["reasons"]
            oth = max(0.0, 1 - rs.get("jobs_clean", 0) - rs.get("moles_out", 0) - rs.get("sabotage", 0))
            w(f"| `{c}` vs `{m}` | {v['rounds']:.2f} | {pct(rs.get('jobs_clean', 0))}% | {pct(rs.get('moles_out', 0))}% | "
              f"{pct(rs.get('sabotage', 0))}% | {pct(oth)}% | {pct(v['sabotage_rate'])}% |")
        w("")
        w("Every cell's rounds and end-reason mix are in `best_response_cells.jsonl`.")
        w("")

    # ---------------- best responses
    for tgt in (3, 2):
        w(f"## Best responses, sabotage_target {tgt}")
        w("")
        w("Crew best response to each mole policy (highest crew win); `ties` = every other crew policy whose Wilson "
          "interval overlaps the best one's; dull policies in **bold**.")
        w("")
        w("| moles | best crew | win % | ties (overlapping interval) |")
        w("|---|---|---|---|")
        for m in moles:
            vs = sorted(((cell("main", tgt, c, m), c) for c in crews), key=lambda t: -t[0]["crew_win"])
            best, bc = vs[0]
            ties = [c for v, c in vs[1:] if v["crew_win_ci"][1] >= best["crew_win_ci"][0]]
            fmtc = lambda c: f"**{c}**" if c in CREW_DULL else c
            w(f"| `{m}` | {fmtc(bc)} | {pct(best['crew_win'])} {ci_s(best['crew_win_ci'])} | "
              f"{', '.join(fmtc(c) for c in ties) or '-'} |")
        w("")
        w("Mole best response to each crew policy (lowest crew win):")
        w("")
        w("| crew | best moles | crew win % | ties (overlapping interval) |")
        w("|---|---|---|---|")
        for c in crews:
            vs = sorted(((cell("main", tgt, c, m), m) for m in moles), key=lambda t: t[0]["crew_win"])
            best, bm = vs[0]
            ties = [m for v, m in vs[1:] if v["crew_win_ci"][0] <= best["crew_win_ci"][1]]
            fmtm = lambda m: f"**{m}**" if m in MOLE_DULL else m
            w(f"| `{c}` | {fmtm(bm)} | {pct(best['crew_win'])} {ci_s(best['crew_win_ci'])} | "
              f"{', '.join(fmtm(m) for m in ties) or '-'} |")
        w("")
        mm = findings["maxmin"][tgt]
        w(f"Max-min (safest) crew policy: `{mm['crew'][0]}` (worst case {pct(mm['crew'][1])}% against "
          f"`{mm['crew'][2]}`); the ranking of crew policies by worst case: "
          + ", ".join(f"`{c}` {pct(v)}" for c, v, _ in mm["crew_rank"]) + ".")
        w("")
        w(f"Min-max (safest) mole policy: `{mm['moles'][0]}` (crew win at most {pct(mm['moles'][1])}%, by "
          f"`{mm['moles'][2]}`); ranking by worst case for the moles: "
          + ", ".join(f"`{m}` {pct(v)}" for m, v, _ in mm["mole_rank"]) + ".")
        w("")
        w("Dull policies as good as the reasoning ones: " + findings["dull_ok"][tgt])
        w("")

    # ---------------- information channels
    w("## What each information channel is worth")
    w("")
    w("Crew win-rate difference, paired by seed (same seeds in both cells), percentile bootstrap over seeds, "
      f"{BOOT} resamples. Percentage points; positive = the first policy wins more.")
    w("")
    comps = [("logician_1.0", "silent"), ("logician_1.0", "own_only"), ("logician_1.0", "jobs_only"),
             ("silent", "jobs_only"), ("bayes_crew", "logician_1.0")]
    for tgt in (3, 2):
        w(f"sabotage_target {tgt}:")
        w("")
        w("| moles | " + " | ".join(f"{a} - {b}" for a, b in comps) + " |")
        w("|---|" + "---|" * len(comps))
        for m in moles:
            parts = []
            for a, b in comps:
                ra, rb = R("main", tgt, a, m), R("main", tgt, b, m)
                d, ci = boot_paired([1.0 if r["winner"] == "crew" else 0.0 for r in ra],
                                    [1.0 if r["winner"] == "crew" else 0.0 for r in rb])
                parts.append(f"{100 * d:+.1f} {ci_s(ci)}")
            w(f"| `{m}` | " + " | ".join(parts) + " |")
        w("")
    w("Single deviator (one crew seat, the lowest-seat crew player, plays the policy; the other four play "
      "`logician_1.0`) against `smart`+decoy, sabotage_target 3: crew win, its difference from the all-logician "
      "cell paired by seed, and the deviator's own Read (`logged`, and the `bayes90` and `base` variants).")
    w("")
    w("| deviator | crew win % | diff vs all-logician (pp) | deviator Read logged | bayes90 | base |")
    w("|---|---|---|---|---|---|")
    rb = R("main", 3, "logician_1.0", "smart+decoy")
    for c in crews:
        if c == "logician_1.0":
            continue
        v = S[f"dev|t3|{c}|smart+decoy"]
        ra = rows[f"dev|t3|{c}|smart+decoy"]
        d, ci = boot_paired([1.0 if r["winner"] == "crew" else 0.0 for r in ra],
                            [1.0 if r["winner"] == "crew" else 0.0 for r in rb])
        w(f"| `{c}` | {pct(v['crew_win'])} {ci_s(v['crew_win_ci'])} | {100 * d:+.1f} {ci_s(ci)} | "
          + " | ".join(f"{num(v['read'][x]['mean'])} {ci_s(v['read'][x]['ci'], 1, '{:+.4f}')}"
                       for x in ("logged", "bayes90", "base")) + " |")
    w("")

    # ---------------- metric check
    w("## Metric check")
    w("")
    w("### (a) Getaway against the mole win-rate order")
    w("")
    for tgt in (3, 2):
        for c in ("logician_1.0", "logician_0.7"):
            g = findings["getaway_order"][(tgt, c)]
            w(f"Crew `{c}`, sabotage_target {tgt}: Spearman rho(Getaway, mole win rate) = {g['rho']:+.3f} over "
              f"{len(moles)} mole policies.")
            w("")
            w("| moles | mole win % | Getaway (95% bootstrap) | crew votes on moles |")
            w("|---|---|---|---|")
            for m, mw, ga, gci, cv in g["table"]:
                w(f"| `{m}`{' (dull)' if m in MOLE_DULL else ''} | {pct(mw)} | {num(ga, '{:.3f}')} "
                  f"{ci_s(gci, 1, '{:.3f}')} | {pct(cv)}% |")
            w("")
            w(f"Inversions (pairs where the higher-Getaway policy wins less, both gaps outside the other's "
              f"interval marked *): {len(g['inv'])} of {len(moles) * (len(moles) - 1) // 2} pairs. "
              + "; ".join(g["inv_text"]) + ".")
            w("")
    w("### (b) Read: report variants")
    w("")
    w("Read = Brier(report) - Brier(ideal reasoner on the seat's view), per reading, averaged per game, mean over "
      "games (95% bootstrap). Lower is better; negative = beats the solver.")
    w("")
    for tgt in (3,):
        w(f"Crew play `logician_1.0`, sabotage_target {tgt}, against every mole policy:")
        w("")
        w("| moles | " + " | ".join(CREW_VARIANTS[1:]) + " | ideal Brier |")
        w("|---|" + "---|" * len(CREW_VARIANTS))
        for m in moles:
            v = cell("main", tgt, "logician_1.0", m)
            w(f"| `{m}` | " + " | ".join(f"{num(v['read'][x]['mean'])}" for x in CREW_VARIANTS[1:])
              + f" | {num(v['brier_ideal'], '{:.4f}')} |")
        w("")
    v = cell("main", 3, "logician_1.0", "smart+decoy")
    w("Intervals for the reference cell (`logician_1.0` vs `smart`+decoy, target 3): "
      + "; ".join(f"{x} {num(v['read'][x]['mean'])} {ci_s(v['read'][x]['ci'], 1, '{:+.4f}')}" for x in CREW_VARIANTS[1:])
      + ".")
    w("")
    w("`bayes` against the solver by mole policy (crew play `logician_1.0`), Read with 95% bootstrap, both targets:")
    w("")
    w("| moles | t3 bayes50 | t3 bayes90 | t2 bayes50 | t2 bayes90 |")
    w("|---|---|---|---|---|")
    for m in moles:
        parts = []
        for tgt in (3, 2):
            v = cell("main", tgt, "logician_1.0", m)
            for x in ("bayes50", "bayes90"):
                parts.append(f"{num(v['read'][x]['mean'])} {ci_s(v['read'][x]['ci'], 1, '{:+.4f}')}")
        w(f"| `{m}` | " + " | ".join(parts) + " |")
    w("")
    w("Read of what each crew policy writes (`logged`) and of fixed report variants, under that policy's own play, "
      "against `smart`+decoy, target 3. Since Read subtracts the solver on the seat's own view, how the crew "
      "*plays* changes the baseline:")
    w("")
    w("| crew play | crew win % | logged | base | public | bayes90 | ideal Brier |")
    w("|---|---|---|---|---|---|---|")
    for c in crews:
        v = cell("main", 3, c, "smart+decoy")
        w(f"| `{c}` | {pct(v['crew_win'])} | " + " | ".join(
            f"{num(v['read'][x]['mean'])} {ci_s(v['read'][x]['ci'], 1, '{:+.4f}')}" for x in ("logged", "base", "public", "bayes90"))
          + f" | {num(v['brier_ideal'], '{:.4f}')} |")
    w("")
    w("### (c) Table read: report variants")
    w("")
    w("Table read = squared error against the alive crew's mean latest stated suspicion minus the same for the "
      "public solver posterior; lower is better. Crew `logician_1.0`, target 3.")
    w("")
    w("| moles | " + " | ".join(MOLE_VARIANTS) + " |")
    w("|---|" + "---|" * len(MOLE_VARIANTS))
    for m in moles:
        v = cell("main", 3, "logician_1.0", m)
        w(f"| `{m}` | " + " | ".join(num(v['table_read'][x]['mean']) for x in MOLE_VARIANTS) + " |")
    w("")
    v = cell("main", 3, "logician_1.0", "smart+decoy")
    w("Intervals for `smart`+decoy: " + "; ".join(
        f"{x} {num(v['table_read'][x]['mean'])} {ci_s(v['table_read'][x]['ci'], 1, '{:+.4f}')}" for x in MOLE_VARIANTS) + ".")
    w("")
    w("Against other crews (mole play `smart`+decoy, target 3), `crew_cond` and `base`:")
    w("")
    w("| crew | logged | base | crew_cond |")
    w("|---|---|---|---|")
    for c in crews:
        v = cell("main", 3, c, "smart+decoy")
        w(f"| `{c}` | " + " | ".join(f"{num(v['table_read'][x]['mean'])} {ci_s(v['table_read'][x]['ci'], 1, '{:+.4f}')}"
                                     for x in ("logged", "base", "crew_cond")) + " |")
    w("")
    w("### (d) Gaining on a metric by playing worse")
    w("")
    for f in findings["d"]:
        w(f"- {f}")
    w("")

    # ---------------- spread
    w("## Spread for choosing benchmark dials")
    w("")
    w(f"Crew `logician` skill 1.0 / 0.7 / 0.4 against `smart`+decoy; mole policies against `logician_1.0`. "
      f"{SPREAD_GAMES} games per cell (main-matrix cells for the two sabotage targets).")
    w("")
    w("| setting | L1.0 win % | L0.7 | L0.4 | 1.0 - 0.4 (pp) | Read L1.0 / L0.4 (logged) | Getaway: " +
      " / ".join(findings["spread_moles"]) + " | Getaway range | mole win % range |")
    w("|---|---|---|---|---|---|---|---|---|")
    for name, row in findings["spread"]:
        w("| " + " | ".join(row) + " |")
    w("")
    w(findings["spread_note"])
    w("")

    # ---------------- changes
    w("## Changes that would close each exploit (and what they do to the tables)")
    w("")
    for f in findings["fixes"]:
        w(f"- {f}")
    w("")
    w("## What bots cannot tell us")
    w("")
    for f in findings["cannot"]:
        w(f"- {f}")
    w("")
    w(f"Reproduce: `{cmd}` (this run took {wall / 60:.0f} min with 8 worker processes while the machine's load "
      "average was 100-200 from other jobs; unloaded, the same code measured about 230 games a second, which puts "
      f"the {sum(c['games'] for c in cells)} games at roughly 25-30 min). Per-game rows are saved to "
      "`analysis/out/best_response_rows.pkl.gz`; `python3.11 -m analysis.best_response --report` rebuilds this page "
      "and the cells file from them in a few minutes.")
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- findings

def compute_findings(S, rows):
    """Numbers behind the exploit lists, the best responses and the spread table."""
    crews, moles = list(CREW_POLICIES), list(MOLE_POLICIES)
    F = {"found": [], "not_found": [], "d": [], "fixes": [], "cannot": [], "maxmin": {}, "dull_ok": {},
         "getaway_order": {}, "spread": [], "spread_moles": list(SPREAD_MOLES), "spread_note": "", "alt": {}}
    win = lambda rs: [1.0 if r["winner"] == "crew" else 0.0 for r in rs]
    C = lambda t, c, m: S[f"main|t{t}|{c}|{m}"]
    RR = lambda t, c, m: rows[f"main|t{t}|{c}|{m}"]
    rd = lambda rs, v: [r["read"][v] if r["read"] else None for r in rs]
    trd = lambda rs, v: [r["tr"][v] if r["tr"] else None for r in rs]
    f4 = lambda x: f"{x:+.4f}"
    f3 = lambda x: f"{x:.3f}"
    cis = lambda ci, f=f4: f"({f(ci[0])} to {f(ci[1])})"
    pp = lambda d, ci: f"{100 * d:+.1f} pp ({100 * ci[0]:+.1f} to {100 * ci[1]:+.1f})"
    real_moles = [m for m in moles if not m.startswith("never")]

    # ---- max-min and dull best responses
    for t in (3, 2):
        crank = []
        for c in crews:
            worst = min(real_moles, key=lambda m: C(t, c, m)["crew_win"])
            crank.append((c, C(t, c, worst)["crew_win"], worst))
        crank.sort(key=lambda x: -x[1])
        mrank = []
        for m in moles:
            worst = max(crews, key=lambda c: C(t, c, m)["crew_win"])
            mrank.append((m, C(t, worst, m)["crew_win"], worst))
        mrank.sort(key=lambda x: x[1])
        F["maxmin"][t] = {"crew": crank[0], "crew_rank": crank, "moles": mrank[0], "mole_rank": mrank}
        dull_c, dull_m = defaultdict(list), defaultdict(list)
        for m in real_moles:
            vs = sorted(crews, key=lambda c: -C(t, c, m)["crew_win"])
            b = C(t, vs[0], m)
            for c in vs:
                if c in CREW_DULL and C(t, c, m)["crew_win_ci"][1] >= b["crew_win_ci"][0]:
                    dull_c[c].append(m)
        for c in crews:
            vs = sorted(moles, key=lambda m: C(t, c, m)["crew_win"])
            b = C(t, c, vs[0])
            for m in vs:
                if m in MOLE_DULL and C(t, c, m)["crew_win_ci"][0] <= b["crew_win_ci"][1]:
                    dull_m[m].append(c)
        txt = []
        txt.append("crew side: " + ("; ".join(f"`{c}` is best or tied-best (overlapping Wilson interval) against "
                                              f"{len(ms)} of {len(real_moles)} sabotaging mole policies ("
                                              + ", ".join(f"`{m}`" for m in ms) + ")"
                                              for c, ms in sorted(dull_c.items(), key=lambda kv: -len(kv[1])))
                                    or "no dull crew policy is best or tied-best against any sabotaging mole policy"))
        txt.append("mole side: " + ("; ".join(f"`{m}` is best or tied-best against {len(cs)} of {len(crews)} crew "
                                              "policies (" + ", ".join(f"`{c}`" for c in cs) + ")"
                                              for m, cs in sorted(dull_m.items(), key=lambda kv: -len(kv[1])))
                                    or "no dull mole policy is best or tied-best against any crew policy"))
        F["dull_ok"][t] = ". ".join(txt) + "."
        F[f"dull_c{t}"], F[f"dull_m{t}"] = dict(dull_c), dict(dull_m)

    # ---- Getaway order
    for t in (3, 2):
        for c in ("logician_1.0", "logician_0.7"):
            tab = []
            for m in moles:
                v = C(t, c, m)
                tab.append((m, 1 - v["crew_win"], v["getaway"], v["getaway_ci"], v["crew_mole_votes"],
                            v["crew_win_ci"]))
            tab.sort(key=lambda x: -x[2])
            rho = spearman([x[2] for x in tab], [x[1] for x in tab])
            inv, inv_text = [], []
            for i in range(len(tab)):
                for j in range(i + 1, len(tab)):
                    a, b = tab[i], tab[j]                      # a has the higher Getaway
                    if a[2] > b[2] and a[1] < b[1]:
                        sure = a[3][0] > b[3][1] and (1 - a[5][0]) < (1 - b[5][1])
                        inv.append((a[0], b[0], sure))
                        inv_text.append(f"`{a[0]}` (G {a[2]:.3f}, mole win {100 * a[1]:.0f}%) above `{b[0]}` "
                                        f"(G {b[2]:.3f}, {100 * b[1]:.0f}%){'*' if sure else ''}")
            F["getaway_order"][(t, c)] = {"rho": rho, "table": [(x[0], x[1], x[2], x[3], x[4]) for x in tab],
                                          "inv": inv, "inv_text": inv_text or ["none"]}

    # ---- alternative Getaway definitions (metric changes, computed from per-round data)
    def g_variants(rs, target):
        out = defaultdict(list)
        for r in rs:
            pr = r["per_round"]
            if not pr:
                continue
            sc = [(0.0 if not b else (1.0 if sh is None else 1 - sh)) for _, b, sh in pr]
            out["shipped"].append(sum(sc) / len(sc))
            opp = [x for (on, b, sh), x in zip(pr, sc) if on]
            out["per_opportunity"].append(sum(opp) / len(opp) if opp else 0.0)
            # ending blown job scored like the others would be if no mole was voted for: drop it
            ne = [x for (on, b, sh), x in zip(pr, sc) if not (b and sh is None)]
            out["no_end_bonus"].append(sum(ne) / len(ne) if ne else 0.0)
            out["total_over_target"].append(sum(sc) / target)
        return {k: float(np.mean(v)) for k, v in out.items()}
    for t in (3, 2):
        for c in ("logician_1.0", "logician_0.7"):
            gv = {m: g_variants(RR(t, c, m), t) for m in moles}
            mw = {m: 1 - C(t, c, m)["crew_win"] for m in moles}
            F["alt"][(t, c)] = {k: spearman([gv[m][k] for m in moles], [mw[m] for m in moles])
                                for k in ("shipped", "per_opportunity", "no_end_bonus", "total_over_target")}
            F["alt"][(t, c, "vals")] = gv

    # ---- exploits: Read
    ref = RR(3, "logician_1.0", "smart+decoy")
    refS = C(3, "logician_1.0", "smart+decoy")
    b90 = refS["read"]["bayes90"]
    b50 = refS["read"]["bayes50"]
    beats = [m for m in moles if C(3, "logician_1.0", m)["read"]["bayes90"]["ci"][1] < 0]
    loses = [m for m in moles if C(3, "logician_1.0", m)["read"]["bayes90"]["ci"][0] > 0]
    beats50 = [m for m in moles if C(3, "logician_1.0", m)["read"]["bayes50"]["ci"][1] < 0]
    loses50 = [m for m in moles if C(3, "logician_1.0", m)["read"]["bayes50"]["ci"][0] > 0]
    F["found"].append(
        f"**The ideal reasoner is not the best reasoner (Read).** A `bayes` reporter (solver worlds weighted by the "
        f"job-result likelihood) scores Read {f4(b90['mean'])} {cis(b90['ci'])} with q = 0.9 and {f4(b50['mean'])} "
        f"{cis(b50['ci'])} with q = 0.5 against `smart`+decoy (crew `logician_1.0`, target 3; ideal Brier "
        f"{refS['brier_ideal']:.4f}). The solver ignores clean jobs entirely, and a mole on a clean team is evidence "
        f"against that mole whenever moles usually sabotage. q = 0.9 beats the solver (interval below 0) against "
        f"{len(beats)} of {len(moles)} mole policies ({', '.join('`' + m + '`' for m in beats) or 'none'}) and loses "
        f"to it against {', '.join('`' + m + '`' for m in loses) or 'none'}; q = 0.5 beats it against {len(beats50)} "
        f"and loses against {', '.join('`' + m + '`' for m in loses50) or 'none'}. So Read below 0 does not need any "
        "behaviour reading: one line of arithmetic about clean jobs gets there.")
    base, pub = refS["read"]["base"], refS["read"]["public"]
    sh66, sh33, push = refS["read"]["shrink66"], refS["read"]["shrink33"], refS["read"]["push"]
    order_ok = sh66["mean"] < sh33["mean"] < base["mean"]
    F["d"].append(
        f"Read report ladder (reference cell): exact 0 by construction, shrink66 {f4(sh66['mean'])}, shrink33 "
        f"{f4(sh33['mean'])}, base rate {f4(base['mean'])} {cis(base['ci'])}, public copy {f4(pub['mean'])} "
        f"{cis(pub['ci'])}, push-to-0/100 {f4(push['mean'])}. The ladder is in the expected order"
        f"{'' if order_ok else ' NOT'}; the exact posterior tops it among the honest variants, and `bayes` beats it. "
        f"The CLAIMS falsifier is therefore concrete: a real model's median Read must be below the public-copy "
        f"script's {f4(pub['mean'])} and the base-rate script's {f4(base['mean'])} for Read to stand.")
    # Read gained by playing worse
    worse = []
    for c in ("silent", "jobs_only", "own_only", "random", "logician_0.4", "logician_0.7", "dull_jobs", "bandwagon",
              "repeat_clean", "no_blown", "blown_seat"):
        rc = RR(3, c, "smart+decoy")
        dw, dwci = boot_paired(win(rc), win(ref))
        res = {}
        for v in ("bayes90", "base", "logged"):
            res[v] = boot_paired(rd(rc, v), rd(ref, v))
        worse.append((c, dw, dwci, res))
    gains = [(c, dw, dwci, res) for c, dw, dwci, res in worse
             if dwci[1] < 0 and (res["bayes90"][1][1] < 0 or res["base"][1][1] < 0)]
    for c, dw, dwci, res in worse:
        F["d"].append(
            f"Crew team plays `{c}` instead of `logician_1.0` (vs `smart`+decoy, target 3, paired by seed): crew win "
            f"{pp(dw, dwci)}; Read of the same `bayes90` reporter {f4(res['bayes90'][0])} {cis(res['bayes90'][1])}, of "
            f"the base-rate script {f4(res['base'][0])} {cis(res['base'][1])}, of what the policy writes "
            f"{f4(res['logged'][0])} {cis(res['logged'][1])} (negative = Read improves).")
    if gains:
        g = sorted(gains, key=lambda x: x[3]["bayes90"][0])[0]
        parts = []
        for c, dw, dwci, res in gains:
            imp = [f"the `{lab}` reporter's Read by {f4(-res[v][0])} {cis((-res[v][1][1], -res[v][1][0]))}"
                   for v, lab in (("bayes90", "bayes90"), ("base", "base-rate")) if res[v][1][1] < 0]
            parts.append(f"`{c}` loses {100 * -dw:.1f} pp of crew win ({100 * -dwci[1]:.1f} to {100 * -dwci[0]:.1f}) "
                         "and improves " + " and ".join(imp))
        F["found"].append(
            "**Read improves when the crew plays worse.** Read subtracts the solver's Brier on what the seat saw, so a "
            "crew that shares less or plays worse lowers its own bar. With the reporter held fixed (paired by seed, "
            "vs `smart`+decoy, target 3): " + "; ".join(parts)
            + ". The cleanest case is `silent`: the whole crew withholding every card costs 17 pp of wins and makes the "
              "same reader look better on Read. A crew trial seats one model in all five crew seats, so this is "
              "available to the model under test.")
    else:
        F["not_found"].append("Read gained by playing worse at team level (silent, jobs_only, own_only, random, "
                              "low skill, dull scripts, with the reporter held fixed): no policy both lost win rate and "
                              "improved Read with intervals excluding 0.")
    # deviator
    dv = []
    for c in crews:
        if c == "logician_1.0":
            continue
        ra = rows[f"dev|t3|{c}|smart+decoy"]
        dv.append((c, boot_paired(win(ra), win(ref)), S[f"dev|t3|{c}|smart+decoy"]["read"]))
    F["d"].append("Single deviator: one seat changing its play moves the team's win rate by at most "
                  + f"{max(abs(100 * x[1][0]) for x in dv):.1f} pp; the deviator's own Read with an honest "
                  "solver report is 0 by construction whatever it does, because its baseline is its own view. "
                  "Withholding cards hurts the other four seats' baselines, not its own, so the Read exploit "
                  "above needs the whole team (which a crew trial is: one model plays all five).")
    # logged Read of dull reasoning policies
    lg = {c: C(3, c, "smart+decoy")["read"]["logged"] for c in crews}
    F["d"].append("What each policy writes, scored as Read (vs `smart`+decoy, target 3): "
                  + ", ".join(f"`{c}` {f4(lg[c]['mean'])}" for c in crews)
                  + ". Every solver-based policy scores 0 whatever its actions, so Read cannot separate the "
                    "logician skills (G2 needs a dial that changes the written number, not the play).")

    # ---- exploits: Getaway
    for t in (3, 2):
        g = F["getaway_order"][(t, "logician_1.0")]
        top = g["table"][0]
        dull_top = next(x for x in g["table"] if x[0] in MOLE_DULL)
        sm = next(x for x in g["table"] if x[0] == "smart+decoy")
        F["d"].append(
            f"Getaway, target {t}, crew `logician_1.0`: highest `{top[0]}` {f3(top[2])} {cis(top[3], f3)} (mole win "
            f"{100 * top[1]:.1f}%); highest dull `{dull_top[0]}` {f3(dull_top[2])} {cis(dull_top[3], f3)} (mole win "
            f"{100 * dull_top[1]:.1f}%); `smart`+decoy {f3(sm[2])} (mole win {100 * sm[1]:.1f}%). Spearman rho with "
            f"mole win rate {g['rho']:+.3f}; {len(g['inv'])} inverted pairs, {sum(1 for x in g['inv'] if x[2])} with "
            "both intervals separated.")
    g3 = F["getaway_order"][(3, "logician_1.0")]
    g2 = F["getaway_order"][(2, "logician_1.0")]
    sure = [x for x in g3["inv"] + g2["inv"] if x[2]]
    inv_txt = (f"Against crew `logician_1.0`, Spearman rho(Getaway, mole win rate) = {g3['rho']:+.3f} (target 3) and "
               f"{g2['rho']:+.3f} (target 2) over {len(moles)} mole scripts; {len(g3['inv'])} and {len(g2['inv'])} "
               f"inverted pairs of {len(moles) * (len(moles) - 1) // 2}, of which {len([x for x in g3['inv'] if x[2]])} "
               f"and {len([x for x in g2['inv'] if x[2]])} have both the Getaway and the win-rate intervals separated"
               + (": " + "; ".join(f"`{a}` over `{b}`" for a, b, s_ in (g3["inv"] + g2["inv"]) if s_) if sure else "")
               + ".")
    if sure:
        F["found"].append("**Getaway order differs from the win-rate order** (a stated CLAIMS falsifier for Bluff). "
                          + inv_txt)
    else:
        F["not_found"].append("A clear Getaway/win-rate inversion (both intervals separated). " + inv_txt
                              + " The order holds at the coarse level (never < late/closer < leader_clean < the "
                                "sabotaging scripts) but is not resolved among the sabotaging scripts.")
    cl = {t: (C(t, "logician_1.0", "closer"), C(t, "logician_1.0", "smart+decoy")) for t in (3, 2)}
    F["d"].append(
        "`closer` (sabotage only on a game-deciding job): " + "; ".join(
            f"target {t}: Getaway {f3(a['getaway'])} {cis(a['getaway_ci'], f3)} vs smart {f3(b['getaway'])}, mole win "
            f"{100 * (1 - a['crew_win']):.1f}% vs {100 * (1 - b['crew_win']):.1f}%" for t, (a, b) in cl.items())
        + ". The \"ending blown job scores 1\" rule pays the full point with no vote to dodge, but "
          "`closer` reaches a deciding job rarely, so it ")
    ok_cl = any(cl[t][0]["getaway"] >= cl[t][1]["getaway"] for t in (3, 2))
    F["d"][-1] += ("matches or beats smart on Getaway." if ok_cl else "stays below smart on Getaway.")
    mute = {t: (C(t, "logician_1.0", "mute"), C(t, "logician_1.0", "smart+decoy")) for t in (3, 2)}
    for t, (a, b) in mute.items():
        d, ci = boot_paired([r["getaway"] for r in RR(t, "logician_1.0", "mute")],
                            [r["getaway"] for r in RR(t, "logician_1.0", "smart+decoy")])
        dw, dwci = boot_paired(win(RR(t, "logician_1.0", "mute")), win(RR(t, "logician_1.0", "smart+decoy")))
        F[f"mute{t}"] = (d, ci, dw, dwci)
    m3 = F["mute3"]
    txt_mute = (f"`mute` moles (no cards, no accusations, empty statements) vs `smart`+decoy, crew `logician_1.0`: "
                f"Getaway {f4(m3[0])} {cis(m3[1])} (target 3), {f4(F['mute2'][0])} {cis(F['mute2'][1])} (target 2); "
                f"crew win {pp(m3[2], m3[3])} (target 3), {pp(F['mute2'][2], F['mute2'][3])} (target 2), paired by seed")
    mute_wins_same = all(F[f"mute{t}"][3][0] <= 0 <= F[f"mute{t}"][3][1] or F[f"mute{t}"][2] < 0 for t in (3, 2))
    if mute_wins_same:
        F["found"].append("**Playing without speaking costs a mole nothing in wins.** " + txt_mute
                          + ". The crew win-rate change is inside noise (or favours the moles), so the cards and "
                            "accusations of `smart` buy nothing against these crews. Getaway, however, "
                          + ("rates `mute` lower: the talk channel moves the metric without moving the result, which "
                             "is a second Getaway/win-rate disagreement." if m3[1][1] < 0 else "rates it the same."))
    else:
        F["not_found"].append("Silent moles matching talking ones on win rate: " + txt_mute + ".")
    for t in (3, 2):
        d, ci = boot_paired([r["getaway"] for r in RR(t, "logician_1.0", "smart+decoy")],
                            [r["getaway"] for r in RR(t, "logician_1.0", "smart+none")])
        dw, dwci = boot_paired(win(RR(t, "logician_1.0", "smart+decoy")), win(RR(t, "logician_1.0", "smart+none")))
        F[f"decoy{t}"] = (d, ci, dw, dwci)
    d3, d2 = F["decoy3"], F["decoy2"]
    txt = (f"Decoy cards vs no cards (`smart`+decoy minus `smart`+none, crew `logician_1.0`, paired by seed): Getaway "
           f"{f4(d3[0])} {cis(d3[1])} (target 3), {f4(d2[0])} {cis(d2[1])} (target 2); crew win {pp(d3[2], d3[3])} "
           f"(target 3), {pp(d2[2], d2[3])} (target 2)")
    if (d3[1][0] > 0 or d2[1][0] > 0) and d3[3][0] <= 0 <= d3[3][1]:
        F["found"].append("**Getaway pays for decoy cards that do not change the result.** " + txt + ". Decoys draw "
                          "crew votes off the moles in rounds the moles go on to lose anyway, so Getaway rises "
                          "while the mole win rate does not.")
    else:
        F["d"].append(txt + ".")
    aw = {t: (C(t, "logician_1.0", "always+decoy"), C(t, "logician_1.0", "smart+decoy")) for t in (3, 2)}
    F["d"].append("`always`+decoy vs `smart`+decoy (crew `logician_1.0`): " + "; ".join(
        f"target {t}: Getaway {f3(a['getaway'])} vs {f3(b['getaway'])}, mole win {100 * (1 - a['crew_win']):.1f}% vs "
        f"{100 * (1 - b['crew_win']):.1f}%" for t, (a, b) in aw.items()) + ".")

    # ---- Table read
    trS = refS["table_read"]
    cc = trS["crew_cond"]
    F["found"].append(
        f"**Table read can be beaten without reading anyone.** `crew_cond`, a mechanical formula (public posterior "
        f"restricted, for each crew member, to worlds without that member, then averaged), scores "
        f"{f4(cc['mean'])} {cis(cc['ci'])} against crew `logician_1.0` (`smart`+decoy, target 3), below the public-"
        f"posterior baseline's 0. Constant base rate scores {f4(trS['base']['mean'])} {cis(trS['base']['ci'])}; "
        f"`truth` {f4(trS['truth']['mean'])}; push {f4(trS['push']['mean'])}.")
    if trS["base"]["ci"][0] > 0:
        F["d"].append("Table read: the constant base-rate answer is worse than the public baseline, so the CLAIMS "
                      "falsifier (\"no model beats the constant answer\") is a low bar: copying the public posterior "
                      "already clears it.")
    jb = C(3, "jobs_only", "smart+decoy")["table_read"]["base"]
    F["d"].append(f"Table read depends on which crew is the reference: against a `jobs_only` crew (beliefs from job "
                  f"results only) the constant base rate beats the public-posterior baseline, {f4(jb['mean'])} "
                  f"{cis(jb['ci'])}, because that crew ignores the cards the baseline uses. A reference model that "
                  "under-uses cards makes every card-aware Table read look worse than a constant.")
    trd_dec = boot_paired(trd(RR(3, "logician_1.0", "smart+decoy"), "crew_cond"),
                          trd(RR(3, "logician_1.0", "smart+none"), "crew_cond"))
    F["d"].append(f"Table read moves with the mole's own play: the same `crew_cond` reporter scores "
                  f"{f4(trd_dec[0])} {cis(trd_dec[1])} lower (better) when the moles table decoys than when they "
                  "table nothing (paired by seed), because decoys pull the public baseline away from what the crew, "
                  "who hold real clues, believe.")
    if trd_dec[1][1] < 0:
        F["found"].append(f"**Table read rewards muddying the public record.** The same reporter gains "
                          f"{f4(-trd_dec[0])} {cis((-trd_dec[1][1], -trd_dec[1][0]))} when its side tables decoy "
                          "cards: the baseline (public posterior) gets worse, the reporter does not.")
    # ---- other wins
    for t in (3, 2):
        bc = C(t, "bayes_crew", "smart+decoy")
        lc = C(t, "logician_1.0", "smart+decoy")
        d, ci = boot_paired(win(RR(t, "bayes_crew", "smart+decoy")), win(RR(t, "logician_1.0", "smart+decoy")))
        F[f"bayes_play{t}"] = (d, ci)
    F["d"].append("Playing on the job likelihood (`bayes_crew`) instead of the solver, vs `smart`+decoy: crew win "
                  f"{pp(*F['bayes_play3'])} (target 3), {pp(*F['bayes_play2'])} (target 2).")
    # dull crew as good as reasoning
    for t in (3, 2):
        dc = F[f"dull_c{t}"]
        if dc:
            F["found"].append(f"**Dull crew scripts tie the best crew policy (target {t}).** " + "; ".join(
                f"`{c}` against {len(ms)} of {len(real_moles)} sabotaging mole policies" for c, ms in
                sorted(dc.items(), key=lambda kv: -len(kv[1]))) + " (Wilson intervals overlapping the best).")
        dm = F[f"dull_m{t}"]
        if dm:
            F["found"].append(f"**Dull mole scripts tie the best mole policy (target {t}).** " + "; ".join(
                f"`{m}` against {len(cs)} of {len(crews)} crew policies" for m, cs in
                sorted(dm.items(), key=lambda kv: -len(kv[1]))) + ".")
    # bandwagon / pile-on
    for t in (3, 2):
        d, ci = boot_paired(win(RR(t, "bandwagon", "smart+decoy")), win(RR(t, "logician_1.0", "smart+decoy")))
        F[f"band{t}"] = (d, ci)
    F["d"].append(f"Pile-on (`bandwagon`) vs `logician_1.0`, against `smart`+decoy: {pp(*F['band3'])} (target 3), "
                  f"{pp(*F['band2'])} (target 2).")

    # ---- spread
    def cellS(name, c, m):
        if name in ("sab3", "sab2"):
            return S[f"main|t{name[-1]}|{c}|{m}"], rows[f"main|t{name[-1]}|{c}|{m}"]
        return S[f"spread|{name}|{c}|{m}"], rows[f"spread|{name}|{c}|{m}"]
    labels = {"sab3": "sabotage_target 3 (default)", "sab2": "sabotage_target 2", "clean4": "clean_target 4",
              "job2": "job_size 2", "rec2": "clue_recipients 2", "rec4": "clue_recipients 4"}
    compressed = []
    for name in ("sab3", "sab2") + tuple(SPREAD_SETTINGS):
        L = {c: cellS(name, c, "smart+decoy") for c in ("logician_1.0", "logician_0.7", "logician_0.4")}
        n = min(len(L["logician_1.0"][1]), len(L["logician_0.4"][1]))
        d, ci = boot_paired(win(L["logician_1.0"][1][:n]), win(L["logician_0.4"][1][:n]))
        ga = {m: cellS(name, "logician_1.0", m)[0] for m in SPREAD_MOLES}
        sab_ga = [ga[m]["getaway"] for m in SPREAD_MOLES if not m.startswith("never")]
        sab_mw = [1 - ga[m]["crew_win"] for m in SPREAD_MOLES if not m.startswith("never")]
        cw = L["logician_1.0"][0]["crew_win"]
        flag = " (compressed)" if cw > 0.85 or cw < 0.15 else ""
        if flag:
            compressed.append(labels[name])
        F["spread"].append((name, [
            labels[name] + flag,
            f"{pct(cw)} {ci_s(L['logician_1.0'][0]['crew_win_ci'], fmt='{:.0f}')}",
            pct(L["logician_0.7"][0]["crew_win"]), pct(L["logician_0.4"][0]["crew_win"]),
            f"{100 * d:+.1f} ({100 * ci[0]:+.1f} to {100 * ci[1]:+.1f})",
            f"{num(L['logician_1.0'][0]['read']['logged']['mean'])} / {num(L['logician_0.4'][0]['read']['logged']['mean'])}",
            " / ".join(f"{ga[m]['getaway']:.3f}" for m in SPREAD_MOLES),
            f"{max(sab_ga) - min(sab_ga):.3f}", f"{100 * min(sab_mw):.0f}-{100 * max(sab_mw):.0f}"]))
    F["spread_note"] = (
        "Getaway columns are in the order of the header; `range` is over the sabotaging scripts (never excluded). "
        "Read of the logician is 0 at every skill and every setting, because the skill dial changes actions, not the "
        "written number. Settings where the reference crew (`logician_1.0` vs `smart`+decoy) wins over 85% or under "
        "15%: " + (", ".join(compressed) or "none") + ". Extra settings play "
        f"{SPREAD_GAMES} games per logician cell and {SPREAD_GAMES_MOLES} per mole cell on seeds from {SEED0}.")

    # ---- fixes
    rs_ = {c: C(3, c, "smart+decoy") for c in crews}
    absb = []
    for c in ("logician_1.0", "silent", "jobs_only", "random", "logician_0.4", "dull_jobs"):
        rc = RR(3, c, "smart+decoy")
        ab = [r["read"]["bayes90"] + r["brier_ideal"] if r["read"] else None for r in rc]
        absb.append((c, boot_mean(ab)))
    F["fixes"].append(
        "Read (team withholding / worse play lowers the bar): score the written number against the truth on the same "
        "deal with a baseline that does not depend on the test crew's own play, e.g. absolute Brier compared between "
        "models on the same deal (the trial design already pairs deals). Absolute Brier of the same `bayes90` reporter "
        "under each crew play (vs `smart`+decoy, target 3): "
        + ", ".join(f"`{c}` {m:.4f} ({ci[0]:.4f} to {ci[1]:.4f})" for c, (m, ci) in absb)
        + ". Under the absolute score, playing worse no longer pays if these rise as play gets worse. Cost: absolute "
          "Brier mixes reading skill with how much the table shares, which is a crew-trial property anyway.")
    F["fixes"].append(
        "Read (solver is not the ceiling): either call the zero point what it is (\"honest-card world counting, "
        "ignoring clean jobs\") or move the zero point to a job-likelihood reasoner. With `bayes90` as the zero "
        f"point the reference cell's exact report scores {f4(-b90['mean'])} and the base-rate script "
        f"{f4(base['mean'] - b90['mean'])}. q has to be fixed in advance; q = 0.9 is wrong against moles who rarely "
        "sabotage (see the `never` and `late` rows), so a likelihood baseline is itself a bet on mole behaviour.")
    alt3 = F["alt"][(3, "logician_1.0")]
    alt2 = F["alt"][(2, "logician_1.0")]
    F["fixes"].append(
        "Getaway (order vs win rate): Spearman rho with mole win rate for alternative definitions, computed from the "
        "same games (crew `logician_1.0`; target 3 / target 2): "
        + ", ".join(f"{k} {alt3[k]:+.2f} / {alt2[k]:+.2f}" for k in alt3)
        + ". `per_opportunity` averages only rounds with a mole on the team; `no_end_bonus` drops the game-ending "
          "blown job; `total_over_target` sums the round scores and divides by sabotage_target (so blowing more jobs "
          "counts, and never sabotaging is still 0).")
    F["fixes"].append(
        "Table read (mechanical formula beats the baseline): use `crew_cond` (or the mean of per-crew solver "
        "posteriors on public information) as the zero point instead of the plain public posterior. Then "
        f"`crew_cond` scores 0, the public copy {f4(-cc['mean'])}, and the base-rate script "
        f"{f4(trS['base']['mean'] - cc['mean'])}. The baseline still moves with the moles' own decoys; scoring "
        "against the crew's mean stated suspicion cannot avoid that, because the crew's beliefs are what is being "
        "read.")
    F["fixes"].append(
        "Balance dials: see the spread table. Only existing dials were run (sabotage_target, clean_target, job_size, "
        "clue_recipients); no engine change was made.")
    F["cannot"] = [
        "How real models play. The scripts' tells (smart moles never accuse or vote a partner, decoys follow a fixed "
        "world, logicians accuse the posterior maximum) are part of every exploit measured here; models have other "
        "tells and may read them.",
        "Whether a model would find any of these exploits. Bots show what the rules and metric definitions permit.",
        "Persuasion: no bot is moved by words, so talk is worth nothing to a bot crew (the `mute` result) and the "
        "accusation channel only matters through `bandwagon`.",
        "Read for behaviour reading: the only reader that beats the solver here uses job results; reading statements "
        "is not simulated.",
        "Mixed tables: every cell has one policy per side (or one crew deviator); show games and real trials seat "
        "copies of one model, which these cells mimic only in that respect.",
    ]
    if not any("Getaway" in x for x in F["not_found"]):
        pass
    chan = {}
    for t in (3,):
        for c in ("silent", "own_only", "jobs_only"):
            chan[c] = boot_paired(win(RR(t, "logician_1.0", "smart+decoy")), win(RR(t, c, "smart+decoy")))
    F["not_found"] += [
        "A crew that never shares cards or ignores clues winning as often as the logician: against `smart`+decoy "
        "(target 3) the logician beats `silent` by " + pp(*chan["silent"]) + ", `own_only` by " + pp(*chan["own_only"])
        + " and `jobs_only` by " + pp(*chan["jobs_only"]) + " (paired). Sharing and clues are worth a lot to a bot crew; "
        "see the channel table for every mole policy.",
        "A sabotage-only-on-the-deciding-job mole (`closer`) collecting Getaway 1 with no vote: it reaches a deciding "
        "job too rarely; see (d).",
        "A single deviating crew seat moving its own Read: with an honest solver report it is 0 whatever the seat does.",
    ]
    return F


# --------------------------------------------------------------------------- main

def main(argv=None):
    global GAMES, SPREAD_GAMES, SPREAD_GAMES_MOLES
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--report", action="store_true", help="rebuild the report from saved rows")
    ap.add_argument("--games", type=int, default=GAMES, help="games per main cell (pilot runs only)")
    ap.add_argument("--no-checks", action="store_true", help="skip the checks (pilot runs only)")
    args = ap.parse_args(argv)
    if args.games != GAMES:                      # pilot runs only
        GAMES, SPREAD_GAMES, SPREAD_GAMES_MOLES = args.games, args.games, max(1, args.games // 2)
    OUT.mkdir(parents=True, exist_ok=True)
    cmd = "python3.11 -m analysis.best_response"
    cells = make_cells()
    store = OUT / "best_response_rows.pkl.gz"
    if args.report:
        with gzip.open(store, "rb") as f:
            saved = pickle.load(f)
        rows, checks, wall = saved["rows"], saved["checks"], saved["wall"]
    else:
        t0 = time.monotonic()
        cpool = None
        if not args.no_checks:                    # checks run unmemoised in their own process, alongside
            cpool = Pool(1)
            cres = cpool.apply_async(_checks_quiet)
        print(f"cells: {len(cells)}, games: {sum(c['games'] for c in cells)}, workers {args.workers}", flush=True)
        rows = run_cells(cells, max(1, args.workers - (0 if args.no_checks else 1)))
        checks = None
        if cpool is not None:
            checks = cres.get()
            cpool.close()
            print("checks:\n" + "\n".join(checks["lines"]), flush=True)
        wall = time.monotonic() - t0
        with gzip.open(store, "wb") as f:
            pickle.dump({"rows": dict(rows), "checks": checks, "wall": wall}, f)
    summ = {c["id"]: summarise(c, rows[c["id"]]) for c in cells}
    with open(OUT / "best_response_cells.jsonl", "w", encoding="utf-8") as f:
        for c in cells:
            f.write(json.dumps(summ[c["id"]]) + "\n")
    text = build_report(cells, summ, rows, checks, wall, cmd)
    (OUT / "best_response.md").write_text(text, encoding="utf-8")
    print(f"wrote {OUT / 'best_response.md'} and best_response_cells.jsonl ({wall / 60:.1f} min)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
