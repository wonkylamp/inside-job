"""Variance decomposition of the pilot decision table, and a power simulation for the trial design.

    python3.11 analysis/variance_power.py                              # pilot1 + pilot2, full run
    python3.11 analysis/variance_power.py --refresh                    # first rebuild decisions_pilot2.*
    python3.11 analysis/variance_power.py --quick                      # fewer resamples (a smoke test)
    python3.11 analysis/variance_power.py --batches pilot1 pilot2 --games-dir games --out analysis/out

Reads `<out>/decisions_<batch>.jsonl` (built by analysis/decision_table.py) and, read-only, the game logs
(for the first leader of each game and the winner). The first batch is the main data set; every other
batch is paired with it by seed (Part A.3). Writes only `<out>/variance_power.md` and
`<out>/variance_power.json`. No model calls. Standard library plus numpy.

Part A  variance decomposition (nested method-of-moments ANOVA; permutation tests for model, seat
        and speaking position; deal-versus-table correlation; design effect).
Part B  power simulation for the trial design (paired per-deal differences, interval over deals).
Part C  what the pilot cannot support.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SEED = 20261110
ND = statistics.NormalDist()
Z975 = ND.inv_cdf(0.975)
Z80 = ND.inv_cdf(0.80)

# --------------------------------------------------------------------------- metrics

def _is_crew_belief(r):
    return r["row_type"] == "reading" and r.get("kind") == "belief" and r["role"] == "crew"


METRICS = {
    "read": {"label": "Read", "field": "read_gap", "role": "crew", "phase": True, "sel": _is_crew_belief,
             "unit": "crew reading", "desc": "`read_gap` = Brier(model) - Brier(solver), crew belief readings"},
    "brier": {"label": "Raw crew Brier", "field": "brier_model", "role": "crew", "phase": True, "sel": _is_crew_belief,
              "unit": "crew reading", "desc": "`brier_model`, crew belief readings"},
    "getaway": {"label": "Getaway", "field": "getaway", "role": "mole", "phase": False,
                "sel": lambda r: r["row_type"] == "round" and r["role"] == "mole",
                "unit": "mole round", "desc": "`getaway`, one row per mole per round alive"},
    "table_read": {"label": "Table read", "field": "table_read_gap", "role": "mole", "phase": True,
                   "sel": lambda r: (r["row_type"] == "reading" and r.get("kind") == "table_read"
                                     and r.get("table_read_gap") is not None),
                   "unit": "mole reading", "desc": "`table_read_gap`, mole readings with a crew target"},
    "vote_hit": {"label": "Crew vote hit", "field": "hit_mole", "role": "crew", "phase": False,
                 "sel": lambda r: r["row_type"] == "vote" and r["role"] == "crew",
                 "unit": "crew vote", "desc": "`hit_mole` (1 = voted for a mole), crew votes"},
}
EXPECTED_N = {"read": 1322, "brier": 1322, "getaway": 99, "table_read": 492, "vote_hit": 235}
ADDITIVE = ("read", "brier", "table_read", "vote_hit")       # simulated with the additive generator
N_GRID = (5, 10, 20, 30, 40, 60, 80, 120)
N_FINE = (3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 25, 30, 40, 50, 60, 70, 80, 100, 120, 150, 200, 250, 300, 400)
RHOS = (0.0, 0.25, 0.5, 0.75)
SCALES = (0.5, 1.0, 2.0)
AFFORD = 60          # deals per test model we call affordable (see the report)
STRETCH = 120


# --------------------------------------------------------------------------- small helpers

def t_quantile(p: float, df: int) -> float:
    """Student t quantile by the Cornish-Fisher expansion (Abramowitz & Stegun 26.7.5); error < 0.002
    for df >= 3 at p = 0.975 (checked in the self-test against tabled values)."""
    if df == 1:
        return math.tan(math.pi * (p - 0.5))
    if df == 2:
        return (2 * p - 1) / math.sqrt(2 * p * (1 - p))
    z = ND.inv_cdf(p)
    v = float(df)
    g1 = (z ** 3 + z) / 4
    g2 = (5 * z ** 5 + 16 * z ** 3 + 3 * z) / 96
    g3 = (3 * z ** 7 + 19 * z ** 5 + 17 * z ** 3 - 15 * z) / 384
    g4 = (79 * z ** 9 + 776 * z ** 7 + 1482 * z ** 5 - 1920 * z ** 3 - 945 * z) / 92160
    return z + g1 / v + g2 / v ** 2 + g3 / v ** 3 + g4 / v ** 4


def wilson(k: int, n: int, z: float = Z975):
    if n == 0:
        return None, None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def pct(a, axis=0):
    a = np.asarray(a, float)
    if a.size == 0:
        return None, None
    lo, hi = np.nanpercentile(a, [2.5, 97.5], axis=axis)
    return lo, hi


def f(x, d=3):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "-"
    return f"{x:.{d}f}"


def fci(v, lo, hi, d=3, pc=False):
    if v is None:
        return "-"
    if pc:
        return f"{100 * v:.0f}% [{100 * lo:.0f}%, {100 * hi:.0f}%]" if lo is not None else f"{100 * v:.0f}%"
    if lo is None:
        return f(v, d)
    return f"{f(v, d)} [{f(lo, d)}, {f(hi, d)}]"


def jsonable(o):
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, np.ndarray):
        return jsonable(o.tolist())
    if isinstance(o, (np.floating,)):
        o = float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, float) and not math.isfinite(o):
        return None
    return o


def onehot(lab, L):
    A = np.zeros((lab.size, L))
    A[np.arange(lab.size), lab] = 1.0
    return A


def boot_weights(n: int, B: int, rng) -> np.ndarray:
    """B x n matrix of resampling weights (counts / n); every row sums to 1."""
    idx = rng.integers(0, n, size=(B, n))
    flat = (idx + (np.arange(B) * n)[:, None]).ravel()
    return np.bincount(flat, minlength=B * n).reshape(B, n) / n


# --------------------------------------------------------------------------- data

def load_rows(out: Path, batch: str) -> list[dict]:
    p = out / f"decisions_{batch}.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.open()]


def game_facts(games_dir: Path, batch: str) -> dict:
    """game_id -> {seed, speak position of each player in round 1 (0 = first to speak, 6 = the
    first leader), winner, cast}. Read-only."""
    try:
        from inside_job.report import load_batch
        b = load_batch(games_dir, batch)
    except Exception as e:  # noqa: BLE001
        print(f"warning: could not read logs of {batch}: {e!r}", file=sys.stderr)
        return {}
    out = {}
    for ev in b.games:
        gs = ev[0]
        seat = {p["name"]: p["seat"] for p in gs["players"]}
        n = len(seat)
        rs1 = next(e for e in ev if e["type"] == "round_start" and e["round"] == 1)
        ls = seat[rs1["leader"]]
        order = [e["player"] for e in ev if e["type"] == "turn" and e.get("turn_phase") == "discuss"
                 and e["round"] == 1 and e.get("pass") == 1]
        spk = {p: (s - ls - 1) % n for p, s in seat.items()}
        ok = all(spk[p] == i for i, p in enumerate(order)) if len(order) == n else None
        end = next((e for e in ev if e["type"] == "game_end"), {})
        out[gs["game_id"]] = {"seed": gs["seed"], "spk": spk, "order_check": ok, "winner": end.get("winner"),
                              "cast": {p["name"]: (p["seat"], p["model"], p["role"]) for p in gs["players"]}}
    return out


class MData:
    """One metric's decisions in one batch, indexed for the nested analysis."""

    def __init__(self, rows: list[dict], key: str, facts: dict):
        spec = METRICS[key]
        self.key = key
        sel = [r for r in rows if spec["sel"](r) and r.get(spec["field"]) is not None]
        self.n_selected_all = sum(1 for r in rows if spec["sel"](r))
        self.rows = sel
        self.y = np.array([float(r[spec["field"]]) for r in sel])
        gids = list(dict.fromkeys(r["game_id"] for r in sel))
        self.game_ids = gids
        gpos = {g: i for i, g in enumerate(gids)}
        self.g = np.array([gpos[r["game_id"]] for r in sel])
        self.seed = {r["game_id"]: r["seed"] for r in sel}
        pkeys = list(dict.fromkeys((r["game_id"], r["player"]) for r in sel))
        ppos = {k: i for i, k in enumerate(pkeys)}
        self.p = np.array([ppos[(r["game_id"], r["player"])] for r in sel])
        self.pkeys = pkeys
        self.gp = np.array([gpos[k[0]] for k in pkeys])
        first = {}
        for r in sel:
            first.setdefault((r["game_id"], r["player"]), r)
        self.models = sorted({first[k]["model"] for k in pkeys})
        self.model_p = np.array([self.models.index(first[k]["model"]) for k in pkeys])
        self.seat_p = np.array([int(first[k]["seat"]) for k in pkeys])
        self.spk_p = np.array([facts.get(k[0], {}).get("spk", {}).get(k[1], -1) for k in pkeys])
        # local player index within game (for bootstrap relabelling)
        loc = {}
        cnt = Counter()
        for k in pkeys:
            loc[k] = cnt[k[0]]
            cnt[k[0]] += 1
        self.lp = np.array([loc[(r["game_id"], r["player"])] for r in sel])
        self.max_lp = max(cnt.values()) if cnt else 1
        self.rows_by_game = [np.flatnonzero(self.g == i) for i in range(len(gids))]
        self.round = np.array([int(r["round"]) for r in sel])
        self.phase = np.array([r.get("turn_phase") or "-" for r in sel])
        cols = [np.ones(len(sel))]
        for v in sorted(set(self.round))[1:]:
            cols.append((self.round == v).astype(float))
        if spec["phase"]:
            for v in sorted(set(self.phase))[1:]:
                cols.append((self.phase == v).astype(float))
        self.Xadj = np.column_stack(cols)                 # intercept + round + phase dummies
        self.N, self.G, self.P = len(sel), len(gids), len(pkeys)

    def game_means(self, round1=False):
        out = {}
        for i, gid in enumerate(self.game_ids):
            rr = self.rows_by_game[i]
            if round1:
                rr = rr[self.round[rr] == 1]
            out[self.seed[gid]] = float(self.y[rr].mean()) if rr.size else None
        return out


# =========================================================================== Part A.1

def nested_mom(y, g, p):
    """Nested (hierarchical) one-way ANOVA, method-of-moments estimates for unbalanced data:
    y = mu + a_game + b_player(game) + e. Expected mean squares with the unbalanced coefficients
    k1, k2, k3 (Searle, Casella & McCulloch 1992, sec. 3.6 / Sokal & Rohlf, nested ANOVA).
    Negative estimates: a negative player component is set to 0 and the game component re-solved
    without it; a negative game component is set to 0."""
    y = np.asarray(y, float)
    N = y.size
    n_p = np.bincount(p).astype(float)
    S_p = np.bincount(p, weights=y)
    kp = n_p > 0
    gp = np.zeros(n_p.size, int)
    gp[p] = g
    n_g = np.bincount(g).astype(float)
    S_g = np.bincount(g, weights=y)
    kg = n_g > 0
    a, b = int(kg.sum()), int(kp.sum())
    Tp = float((S_p[kp] ** 2 / n_p[kp]).sum())
    Tg = float((S_g[kg] ** 2 / n_g[kg]).sum())
    SSW = float((y * y).sum()) - Tp
    SSB = Tp - Tg
    SSA = Tg - float(y.sum()) ** 2 / N
    dfW, dfB, dfA = N - b, b - a, a - 1
    MSW = SSW / dfW if dfW > 0 else float("nan")
    MSB = SSB / dfB if dfB > 0 else float("nan")
    MSA = SSA / dfA if dfA > 0 else float("nan")
    s = float((n_p[kp] ** 2 / n_g[gp[kp]]).sum())
    k1 = (N - s) / dfB if dfB > 0 else float("nan")
    k2 = (s - float((n_p[kp] ** 2).sum()) / N) / dfA if dfA > 0 else float("nan")
    k3 = (N - float((n_g[kg] ** 2).sum()) / N) / dfA if dfA > 0 else float("nan")
    s2e = MSW
    s2p_raw = (MSB - MSW) / k1 if dfB > 0 else 0.0
    s2g_raw = (MSA - MSW - k2 * s2p_raw) / k3
    s2p = max(0.0, s2p_raw)
    s2g = (MSA - MSW - k2 * s2p) / k3
    s2g = max(0.0, s2g)
    tot = s2g + s2p + s2e
    # share of within-game decision pairs that come from the same player
    same = float((n_p[kp] * (n_p[kp] - 1)).sum())
    allp = float((n_g[kg] * (n_g[kg] - 1)).sum())
    pi = same / allp if allp > 0 else 0.0
    m = N / a
    rho_w = (s2g + pi * s2p) / tot if tot > 0 else 0.0
    deff = 1 + (m - 1) * rho_w
    return {"s2g": s2g, "s2p": s2p, "s2e": s2e, "s2g_raw": s2g_raw, "s2p_raw": s2p_raw, "total": tot,
            "share_g": s2g / tot if tot else 0, "share_p": s2p / tot if tot else 0, "share_e": s2e / tot if tot else 0,
            "icc_game": s2g / tot if tot else 0, "icc_player": (s2g + s2p) / tot if tot else 0,
            "N": N, "games": a, "players": b, "k1": k1, "k2": k2, "k3": k3,
            "MSA": MSA, "MSB": MSB, "MSW": MSW, "pi_same_player": pi, "m": m, "rho_within_game": rho_w,
            "deff": deff, "eff_per_game": m / deff, "eff_total": a * m / deff}


def residualize(y, X):
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return y - X @ beta


COMP_KEYS = ("s2g", "s2p", "s2e", "share_g", "share_p", "share_e", "icc_game", "icc_player",
             "deff", "eff_per_game", "eff_total")


def part_a1(md: MData, idx: np.ndarray):
    """Components before and after removing round and phase means, with game-bootstrap intervals."""
    res = {}
    yadj = residualize(md.y, md.Xadj)
    res["raw"] = nested_mom(md.y, md.g, md.p)
    res["adj"] = nested_mom(yadj, md.g, md.p)
    _, rcode = np.unique(md.g * 16 + md.round, return_inverse=True)
    res["round"] = nested_mom(md.y, md.g, rcode)          # middle level = round within game
    boots = {"raw": defaultdict(list), "adj": defaultdict(list), "round": defaultdict(list)}
    G = md.G
    for b in range(idx.shape[0]):
        sel = idx[b]
        rows = np.concatenate([md.rows_by_game[i] for i in sel])
        gnew = np.repeat(np.arange(G), [md.rows_by_game[i].size for i in sel])
        pnew = gnew * md.max_lp + md.lp[rows]
        _, pnew = np.unique(pnew, return_inverse=True)
        _, rnew = np.unique(gnew * 16 + md.round[rows], return_inverse=True)
        yr = md.y[rows]
        r1 = nested_mom(yr, gnew, pnew)
        r2 = nested_mom(residualize(yr, md.Xadj[rows]), gnew, pnew)
        r3 = nested_mom(yr, gnew, rnew)
        for k in COMP_KEYS:
            boots["raw"][k].append(r1[k])
            boots["adj"][k].append(r2[k])
            boots["round"][k].append(r3[k])
    for v in ("raw", "adj", "round"):
        res[v]["ci"] = {k: pct(np.array(boots[v][k])) for k in COMP_KEYS}
    res["boot_s2p_adj"] = np.array(boots["adj"]["s2p"])
    return res


def selftest_mom(md: MData, comps=(0.002, 0.001, 0.010), reps=1000, cov_reps=200, cov_boot=400, rng=None):
    """Recover planted components from simulated normal data with exactly the pilot's shape
    (games, players, decisions per player of metric `md`)."""
    rng = rng or np.random.default_rng(SEED + 1)
    s2g, s2p, s2e = comps
    est = []
    for _ in range(reps):
        y = (rng.normal(0, math.sqrt(s2g), md.G)[md.g] + rng.normal(0, math.sqrt(s2p), md.P)[md.p]
             + rng.normal(0, math.sqrt(s2e), md.N))
        r = nested_mom(y, md.g, md.p)
        est.append((r["s2g_raw"], r["s2p_raw"], r["s2e"], r["s2g"], r["s2p"]))
    est = np.array(est)
    out = {"planted": comps, "reps": reps, "shape": {"N": md.N, "games": md.G, "players": md.P}}
    names = ("s2g_raw", "s2p_raw", "s2e", "s2g_trunc", "s2p_trunc")
    truth = (s2g, s2p, s2e, s2g, s2p)
    out["est"] = {}
    ok = True
    for j, nm in enumerate(names):
        m, sd = float(est[:, j].mean()), float(est[:, j].std(ddof=1))
        se = sd / math.sqrt(reps)
        z = (m - truth[j]) / se if se > 0 else 0.0
        out["est"][nm] = {"mean": m, "sd": sd, "mc_se": se, "z": z, "truth": truth[j]}
        if nm in ("s2g_raw", "s2p_raw", "s2e") and abs(z) > 3:
            ok = False
    out["unbiased_pass"] = ok
    # coverage of the game-bootstrap percentile interval for the game component and the game ICC
    cover_g = cover_icc = 0
    icc_true = s2g / sum(comps)
    for _ in range(cov_reps):
        y = (rng.normal(0, math.sqrt(s2g), md.G)[md.g] + rng.normal(0, math.sqrt(s2p), md.P)[md.p]
             + rng.normal(0, math.sqrt(s2e), md.N))
        idx = rng.integers(0, md.G, size=(cov_boot, md.G))
        vg, vi = [], []
        for b in range(cov_boot):
            sel = idx[b]
            rows = np.concatenate([md.rows_by_game[i] for i in sel])
            gnew = np.repeat(np.arange(md.G), [md.rows_by_game[i].size for i in sel])
            pnew = gnew * md.max_lp + md.lp[rows]
            _, pnew = np.unique(pnew, return_inverse=True)
            r = nested_mom(y[rows], gnew, pnew)
            vg.append(r["s2g"])
            vi.append(r["icc_game"])
        lo, hi = np.percentile(vg, [2.5, 97.5])
        cover_g += lo <= s2g <= hi
        lo, hi = np.percentile(vi, [2.5, 97.5])
        cover_icc += lo <= icc_true <= hi
    out["boot_coverage"] = {"reps": cov_reps, "boot": cov_boot, "s2g": cover_g / cov_reps,
                            "icc_game": cover_icc / cov_reps}
    return out


# =========================================================================== Part A.2

class FE:
    """Decision-level linear model with game fixed effects + round/phase dummies, reduced to the
    player level: for a factor whose labels are constant within player, the extra sum of squares is
    h' (A'CA)^+ h with C = P'MP, h = A'P'My, M the residual projector of the base design."""

    def __init__(self, y, g, p, Xadj):
        G = int(g.max()) + 1
        Xg = np.zeros((y.size, G))
        Xg[np.arange(y.size), g] = 1.0
        X = np.column_stack([Xg, Xadj[:, 1:]])
        U, s, _ = np.linalg.svd(X, full_matrices=False)
        Q = U[:, s > s[0] * 1e-10]
        self.Q = Q
        b = int(p.max()) + 1
        self.n_p = np.bincount(p, minlength=b).astype(float)
        self.p = p
        self.QtP = np.stack([np.bincount(p, weights=Q[:, j], minlength=b) for j in range(Q.shape[1])])
        self.C = np.diag(self.n_p) - self.QtP.T @ self.QtP
        self.set_y(y)

    def set_y(self, y):
        Qty = self.Q.T @ y
        S_p = np.bincount(self.p, weights=y, minlength=self.n_p.size)
        self.v = S_p - self.QtP.T @ Qty
        self.yres2 = float(y @ y - Qty @ Qty)

    def stats(self, labs: np.ndarray, L: int):
        """labs: (K, b) integer labels -> (T = partial R^2, V = variance of the level effects)."""
        labs = np.atleast_2d(labs)
        K, b = labs.shape
        A = np.zeros((K, b, L))
        A[np.repeat(np.arange(K), b), np.tile(np.arange(b), K), labs.ravel()] = 1.0
        CA = np.matmul(self.C, A)
        Gm = np.matmul(A.transpose(0, 2, 1), CA)
        h = np.einsum("kbl,b->kl", A, self.v)
        beta = np.einsum("klm,km->kl", np.linalg.pinv(Gm, hermitian=True), h)
        SS = np.einsum("kl,kl->k", h, beta)
        present = A.sum(1) > 0
        V = np.array([np.var(beta[k][present[k]]) for k in range(K)])
        return SS / self.yres2, V, beta


def within_game_perms(gp: np.ndarray, K: int, rng) -> np.ndarray:
    """K x b index arrays, each a random permutation of players within their game."""
    b = gp.size
    fixed = np.lexsort((np.arange(b), gp))
    out = np.empty((K, b), int)
    for k in range(K):
        rnd = np.lexsort((rng.random(b), gp))
        perm = np.empty(b, int)
        perm[fixed] = rnd
        out[k] = perm
    return out


def part_a2(md: MData, idx: np.ndarray, n_perm: int, rng, s2p_boot: np.ndarray, s2p_hat: float,
            power_reps: int, null_reps: int, inner_perm: int):
    fe = FE(md.y, md.g, md.p, md.Xadj)
    factors = {"model": (md.model_p, len(md.models), md.models),
               "seat": (md.seat_p, 7, list(range(7))),
               "speak_position": (md.spk_p, 7, list(range(7)))}
    perms = within_game_perms(md.gp, n_perm, rng)
    out = {}
    live = {}
    for name, (lab, L, names) in factors.items():
        if (lab < 0).any():
            out[name] = {"error": "labels missing"}
            continue
        T_obs, V_obs, beta = fe.stats(lab[None, :], L)
        T_perm, V_perm, _ = fe.stats(lab[perms], L)
        pval = (1 + int((T_perm >= T_obs[0] - 1e-12).sum())) / (1 + n_perm)
        null_mean_V = float(V_perm.mean())
        comp = float(V_obs[0] - null_mean_V)
        effects = {str(names[i]): float(beta[0][i]) for i in range(L) if (lab == i).any()}
        out[name] = {"T_obs": float(T_obs[0]), "p": pval, "n_perm": n_perm, "levels": L,
                     "V_obs": float(V_obs[0]), "V_null_mean": null_mean_V, "component": comp,
                     "share_of_player": comp / s2p_hat if s2p_hat > 0 else None, "effects": effects}
        live[name] = (lab, L, null_mean_V, [], [])
    # bootstrap over games: recompute the fixed-effects fit on each resample (one fit, every factor)
    for b in range(idx.shape[0]):
        sel = idx[b]
        rows = np.concatenate([md.rows_by_game[i] for i in sel])
        gnew = np.repeat(np.arange(md.G), [md.rows_by_game[i].size for i in sel])
        pnew = gnew * md.max_lp + md.lp[rows]
        _, inv_first, pnew = np.unique(pnew, return_index=True, return_inverse=True)
        orig_p = md.p[rows][inv_first]
        feb = FE(md.y[rows], gnew, pnew, md.Xadj[rows])
        for name, (lab, L, nm, cb, sh) in live.items():
            _, Vb, _ = feb.stats(lab[orig_p][None, :], L)
            cb.append(Vb[0] - nm)
            sh.append((Vb[0] - nm) / s2p_boot[b] if s2p_boot[b] > 0 else np.nan)
    for name, (lab, L, nm, cb, sh) in live.items():
        out[name]["component_ci"] = pct(np.array(cb))
        out[name]["share_of_player_ci"] = pct(np.array(sh))
    # power of the model test with a planted effect, and its false-positive rate with none
    lab, L, names = factors["model"]
    raw_means = []
    for i in range(L):
        m = lab[md.p] == i
        if m.any():
            raw_means.append(md.y[m].mean())
    obs_range = float(max(raw_means) - min(raw_means)) if raw_means else 0.0
    inner = within_game_perms(md.gp, inner_perm, rng)
    pw = {"observed_range_of_model_means": obs_range, "inner_perm": inner_perm, "rows": []}
    y0 = md.y.copy()
    for mult, reps in ((0.0, null_reps), (0.5, power_reps), (1.0, power_reps), (2.0, power_reps),
                       (4.0, power_reps)):
        eff = np.linspace(-0.5, 0.5, L) * obs_range * mult
        rej = 0
        for _ in range(reps):
            lab0 = lab[within_game_perms(md.gp, 1, rng)[0]]
            y = y0 + eff[lab0[md.p]]
            fe.set_y(y)
            T0, _, _ = fe.stats(lab0[None, :], L)
            Tp, _, _ = fe.stats(lab0[inner], L)
            pv = (1 + int((Tp >= T0[0] - 1e-12).sum())) / (1 + inner_perm)
            rej += pv <= 0.05
        r = rej / reps
        pw["rows"].append({"multiple_of_observed_range": mult, "planted_range": float(obs_range * mult),
                           "reps": reps, "rejection_rate": r, "mc_se": math.sqrt(max(r * (1 - r), 1e-9) / reps)})
    fe.set_y(y0)
    out["model_power"] = pw
    return out


# =========================================================================== Part A.3

def corr(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    if x.size < 3 or x.std() == 0 or y.std() == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def part_a3(main: dict, other: dict, B: int, rng):
    """main/other: seed -> value. Pearson r across seeds present in both, with a bootstrap over seeds."""
    seeds = sorted(s for s in main if s in other and main[s] is not None and other[s] is not None)
    x = np.array([main[s] for s in seeds])
    y = np.array([other[s] for s in seeds])
    r = corr(x, y)
    out = {"pairs": len(seeds), "seeds": seeds, "r": r, "lo": None, "hi": None,
           "values": [[s, main[s], other[s]] for s in seeds]}
    if r is not None and len(seeds) >= 5:
        bs = []
        for _ in range(B):
            i = rng.integers(0, len(seeds), len(seeds))
            c = corr(x[i], y[i])
            if c is not None:
                bs.append(c)
        if bs:
            out["lo"], out["hi"] = (float(v) for v in np.percentile(bs, [2.5, 97.5]))
            out["boot_valid"] = len(bs)
    return out


# =========================================================================== Part B machinery

def intervals(D: np.ndarray, W: np.ndarray, methods=("pct", "t", "bca", "stud")) -> dict:
    """95% intervals for the mean of each column of D (N x R). W: B x N resampling weights."""
    N, R = D.shape
    th = D.mean(0)
    out = {}
    sd = D.std(0, ddof=1)
    se = sd / math.sqrt(N)
    if "t" in methods:
        tq = t_quantile(0.975, N - 1)
        out["t"] = (th - tq * se, th + tq * se)
    need_boot = any(m in methods for m in ("pct", "bca", "stud"))
    if not need_boot:
        return out
    BM = W @ D
    if "pct" in methods:
        lo, hi = np.quantile(BM, [0.025, 0.975], axis=0)
        out["pct"] = (lo, hi)
    if "bca" in methods:
        B = BM.shape[0]
        less = (BM < th - 1e-14).mean(0) + 0.5 * (np.abs(BM - th) <= 1e-14).mean(0)
        less = np.clip(less, 1 / (2 * B), 1 - 1 / (2 * B))
        z0 = np.array([ND.inv_cdf(float(v)) for v in less])
        jk = (D.sum(0)[None, :] - D) / (N - 1)
        d = jk.mean(0)[None, :] - jk
        num = (d ** 3).sum(0)
        den = 6 * ((d ** 2).sum(0)) ** 1.5
        a = np.where(den > 0, num / np.where(den > 0, den, 1), 0.0)
        S = np.sort(BM, axis=0)
        res = []
        for zq in (-Z975, Z975):
            arg = z0 + (z0 + zq) / (1 - a * (z0 + zq))
            al = np.array([ND.cdf(float(v)) for v in arg])
            k = np.clip(np.floor(al * (B - 1)).astype(int), 0, B - 1)
            res.append(S[k, np.arange(R)])
        out["bca"] = (res[0], res[1])
    if "stud" in methods:
        BM2 = W @ (D * D)
        var = np.clip(BM2 - BM ** 2, 0, None)
        seb = np.sqrt(var / (N - 1))
        diff = BM - th[None, :]
        tstar = np.where(seb > 1e-14, diff / np.where(seb > 1e-14, seb, 1),
                         np.where(np.abs(diff) <= 1e-14, 0.0, np.sign(diff) * 1e12))
        qlo, qhi = np.quantile(tstar, [0.025, 0.975], axis=0)
        lo = np.where(se > 0, th - qhi * se, th)
        hi = np.where(se > 0, th - qlo * se, th)
        out["stud"] = (lo, hi)
    return out


def run_intervals(D: np.ndarray, B: int, rng, methods=("pct", "t", "bca", "stud"), chunk: int = 250) -> dict:
    """`intervals` with a fresh resampling matrix for every chunk of simulated studies, so that the
    bootstrap's own noise is not shared by all of them."""
    N, R = D.shape
    parts = []
    for s in range(0, R, chunk):
        W = boot_weights(N, B, rng) if any(m != "t" for m in methods) else None
        parts.append(intervals(D[:, s:s + chunk], W, methods))
    return {m: (np.concatenate([p[m][0] for p in parts]), np.concatenate([p[m][1] for p in parts]))
            for m in parts[0]}


def excludes0(iv):
    lo, hi = iv
    return (lo > 1e-12) | (hi < -1e-12)


class AddGen:
    """Additive generator: per-deal score = mu_model + sqrt(rho)*a_deal + sqrt(1-rho)*b_play, with a
    and b drawn independently from the pilot's per-game means, centred and scaled (variance x c).
    The paired difference of two models on one deal is delta + u * (z1 - z2), u = sd * sqrt((1-rho)c),
    z drawn from the standardised empirical distribution: rho and c only rescale delta."""

    def __init__(self, gm: np.ndarray):
        self.x = np.asarray(gm, float)
        self.sd = float(self.x.std(ddof=1))
        d = self.x - self.x.mean()
        self.z = d / math.sqrt((d ** 2).mean())

    def unit(self, rho, c):
        return self.sd * math.sqrt((1 - rho) * c)

    def D0(self, N, R, rng):
        return self.z[rng.integers(0, self.z.size, (N, R))] - self.z[rng.integers(0, self.z.size, (N, R))]


class GetawayGen:
    """Two-part (zero-inflated) generator for per-game Getaway means, fitted to the pilot: a game
    has any getaway with probability p, and then a positive value s*Y (capped at 1), Y drawn from the
    pilot's positive per-game means. Rescaling to a new mean mu: p and s both grow by sqrt(mu/mu0)
    (p capped at 0.95, s takes the rest). Variance scale c: with the mean held, p is moved (and s
    re-solved) until the variance is c times that default. Two models on one deal share latent
    normals (a Gaussian copula) whose correlation is calibrated so that the per-deal scores of two
    identical models correlate rho."""

    P_CAP = 0.95

    def __init__(self, gm: np.ndarray):
        x = np.asarray(gm, float)
        self.mu0 = float(x.mean())
        self.p0 = float((x > 0).mean())
        self.Y = np.sort(x[x > 0])
        self.k = self.Y.size
        self.thr = np.array([ND.inv_cdf(i / self.k) for i in range(1, self.k)])
        self._cal = {}
        self._prm = {}

    def _mv(self, p, s):
        v = np.minimum(1.0, s * self.Y)
        m1 = float(v.mean())
        return p * m1, p * float((v * v).mean()) - (p * m1) ** 2

    def _s_for(self, p, mu):
        lo, hi = 0.0, 1.0 / self.Y.min() + 1.0
        if self._mv(p, hi)[0] < mu:
            return hi
        for _ in range(60):
            mid = (lo + hi) / 2
            if self._mv(p, mid)[0] < mu:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    def params(self, mu, c=1.0):
        key = (round(mu, 9), c)
        if key not in self._prm:
            self._prm[key] = self._params(mu, c)
        return self._prm[key]

    def _params(self, mu, c):
        p_def = min(self.P_CAP, self.p0 * math.sqrt(mu / self.mu0))
        v_def = self._mv(p_def, self._s_for(p_def, mu))[1]
        target = c * v_def

        def var_at(p):
            return self._mv(p, self._s_for(p, mu))[1]
        lo, hi = mu * 1.0001, self.P_CAP
        if target >= var_at(lo):
            p = lo
        elif target <= var_at(hi):
            p = hi
        else:
            for _ in range(60):
                mid = (lo + hi) / 2
                if var_at(mid) > target:
                    lo = mid
                else:
                    hi = mid
            p = (lo + hi) / 2
        s = self._s_for(p, mu)
        m, v = self._mv(p, s)
        return {"p": p, "s": s, "mean": m, "var": v, "var_target": target, "var_default": v_def}

    def draw(self, prm, zo, zv):
        occ = zo < ND.inv_cdf(min(prm["p"], 1 - 1e-12))
        val = np.minimum(1.0, prm["s"] * self.Y[np.searchsorted(self.thr, zv)])
        return occ * val

    def latent_rho(self, mu, c, rho):
        key = (round(mu, 6), c, rho)
        if rho <= 0:
            return 0.0
        if key in self._cal:
            return self._cal[key]
        prm = self.params(mu, c)
        rng = np.random.default_rng(SEED + 7)
        n = 200_000
        U, V = rng.standard_normal(n), rng.standard_normal(n)
        E = rng.standard_normal((4, n))

        def achieved(rl):
            a, b = math.sqrt(rl), math.sqrt(1 - rl)
            xa = self.draw(prm, a * U + b * E[0], a * V + b * E[1])
            xb = self.draw(prm, a * U + b * E[2], a * V + b * E[3])
            return float(np.corrcoef(xa, xb)[0, 1])
        lo, hi = 0.0, 1.0
        if achieved(1.0) < rho:
            self._cal[key] = 1.0
            return 1.0
        for _ in range(30):
            mid = (lo + hi) / 2
            if achieved(mid) < rho:
                lo = mid
            else:
                hi = mid
        self._cal[key] = (lo + hi) / 2
        return self._cal[key]

    def scores(self, mus, c, rho_lat, N, R, rng):
        """(K, N, R) per-deal scores for K models with means `mus`, sharing deal latents."""
        a, b = math.sqrt(rho_lat), math.sqrt(1 - rho_lat)
        U = rng.standard_normal((N, R))
        V = rng.standard_normal((N, R))
        out = []
        for mu in mus:
            prm = self.params(mu, c)
            zo = a * U + b * rng.standard_normal((N, R))
            zv = a * V + b * rng.standard_normal((N, R))
            out.append(self.draw(prm, zo, zv))
        return np.stack(out)


# =========================================================================== Part B

def part_b_additive(gens: dict, R: int, B: int, rng):
    """Power curves for the additive metrics as a function of the standardised difference
    s = delta / u. For every N: the percentile bootstrap interval and the paired t interval."""
    sgrid = np.round(np.arange(0, 8.0001, 0.01), 4)
    out = {}
    for key, gen in gens.items():
        out[key] = {}
        for N in N_FINE:
            D0 = gen.D0(N, R, rng)
            iv = run_intervals(D0, B, rng, methods=("pct", "t"))
            row = {}
            for m in ("pct", "t"):
                lo, hi = iv[m]
                pw = np.array([float(((lo + s > 1e-12) | (hi + s < -1e-12)).mean()) for s in sgrid])
                row[m] = pw
                row[m + "_halfwidth_per_unit"] = float(((hi - lo) / 2).mean())
            row["var_D0"] = float(D0.var())
            out[key][N] = row
    return sgrid, out


def power_at(sgrid, curve, s):
    s = abs(s)
    if s >= sgrid[-1]:
        return float(curve[-1])
    return float(np.interp(s, sgrid, curve))


def s80(sgrid, curve):
    i = np.flatnonzero(curve >= 0.8)
    if not i.size:
        return None
    j = i[0]
    if j == 0:
        return float(sgrid[0])
    return float(np.interp(0.8, [curve[j - 1], curve[j]], [sgrid[j - 1], sgrid[j]]))


def n80_from(powers: dict, Ns):
    """Smallest N (linear interpolation between grid points) with power >= 0.8."""
    prev = None
    for N in Ns:
        p = powers[N]
        if p >= 0.8:
            if prev is None:
                return float(N)
            N0, p0 = prev
            return float(N0 + (0.8 - p0) / (p - p0) * (N - N0)) if p > p0 else float(N)
        prev = (N, p)
    return None


def part_b_getaway(gen: GetawayGen, mus, deltas, R, B, rng):
    out = {"params": {}, "cells": [], "latent_rho": {}}
    for mu in mus:
        for c in SCALES:
            out["params"][f"{mu}|{c}"] = gen.params(mu, c)
            for rho in RHOS:
                out["latent_rho"][f"{mu}|{c}|{rho}"] = gen.latent_rho(mu, c, rho)
    for mu in mus:
        for c in SCALES:
            for rho in RHOS:
                rl = gen.latent_rho(mu, c, rho)
                for N in N_GRID:
                    for d in deltas:
                        X = gen.scores([mu, mu + d], c, rl, N, R, rng)
                        D = X[1] - X[0]
                        # the percentile bootstrap only at c = 1 (cost); the t interval everywhere
                        ms = ("pct", "t") if c == 1.0 else ("t",)
                        iv = run_intervals(D, B, rng, methods=ms)
                        cell = {"mu": mu, "c": c, "rho": rho, "N": N, "delta": d,
                                "t": float(excludes0(iv["t"]).mean()), "var_D": float(D.var()),
                                "half_t": float(((iv["t"][1] - iv["t"][0]) / 2).mean())}
                        if "pct" in iv:
                            cell["pct"] = float(excludes0(iv["pct"]).mean())
                            cell["half_pct"] = float(((iv["pct"][1] - iv["pct"][0]) / 2).mean())
                        out["cells"].append(cell)
    return out


def part_b3(gens: dict, gaw: GetawayGen, R: int, B: int, rng, getaway_cases):
    """False-positive rate of four interval methods under the null (two identical models)."""
    out = {}
    for key, gen in gens.items():
        out[key] = {}
        for N in (5, 10, 20, 40):
            D = gen.D0(N, R, rng)
            iv = run_intervals(D, B, rng)
            out[key][N] = {m: {"fpr": float(excludes0(v).mean()), "half_per_unit": float(((v[1] - v[0]) / 2).mean())}
                           for m, v in iv.items()}
    for mu, rho in getaway_cases:
        k = f"getaway mu={mu} rho={rho}"
        out[k] = {}
        rl = gaw.latent_rho(mu, 1.0, rho)
        for N in (5, 10, 20, 40):
            X = gaw.scores([mu, mu], 1.0, rl, N, R, rng)
            D = X[1] - X[0]
            iv = run_intervals(D, B, rng)
            out[k][N] = {m: {"fpr": float(excludes0(v).mean()), "half_raw": float(((v[1] - v[0]) / 2).mean())}
                         for m, v in iv.items()}
            out[k][N]["all_zero_share"] = float((np.abs(D).sum(0) == 0).mean())
    return out


def part_b4_additive(gens: dict, R: int, rng, Ks=(3, 4, 5)):
    """Repeatability: K models spaced s (standard units) apart, N deals split into two halves."""
    sgrid = (0.0, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0)
    out = {}
    for key, gen in gens.items():
        out[key] = {}
        for K in Ks:
            for N in N_GRID:
                n1 = N // 2
                n2 = N - n1
                # per-model play noise e (K, N, R); deal effects cancel in comparisons within a half
                Z = gen.z[rng.integers(0, gen.z.size, (K, N, R))]
                res = {}
                for s in sgrid:
                    X = Z + (np.arange(K) * s)[:, None, None]
                    same, norev = _repeat_stats(X, n1, n2)
                    res[s] = {"same_ranking": same, "no_sig_reversal": norev}
                out[key][f"{K}|{N}"] = res
    return sgrid, out


def _repeat_stats(X, n1, n2):
    """X: (K, N, R). Share of R where both halves give the same strict ranking; share where no pair
    has paired-t intervals excluding 0 with opposite signs in the two halves."""
    K = X.shape[0]
    h1, h2 = X[:, :n1], X[:, n1:n1 + n2]
    m1, m2 = h1.mean(1), h2.mean(1)                      # (K, R)
    same = np.ones(X.shape[2], bool)
    rev = np.zeros(X.shape[2], bool)
    for i in range(K):
        for j in range(i + 1, K):
            d1 = m1[i] - m1[j]
            d2 = m2[i] - m2[j]
            same &= (np.sign(d1) == np.sign(d2)) & (d1 != 0) & (d2 != 0)
            sig = []
            for h, n in ((h1, n1), (h2, n2)):
                dd = h[i] - h[j]
                mm = dd.mean(0)
                if n >= 2:
                    se = dd.std(0, ddof=1) / math.sqrt(n)
                    tq = t_quantile(0.975, n - 1)
                    sig.append(np.where(mm - tq * se > 1e-12, 1, np.where(mm + tq * se < -1e-12, -1, 0)))
                else:
                    sig.append(np.zeros_like(mm, dtype=int))
            rev |= (sig[0] * sig[1]) < 0
    return float(same.mean()), float((~rev).mean())


def part_b4_getaway(gen: GetawayGen, mus, deltas, R, rng, Ks=(3, 4, 5)):
    out = []
    for mu in mus:
        for rho in RHOS:
            rl = gen.latent_rho(mu, 1.0, rho)
            for K in Ks:
                for N in N_GRID:
                    for d in deltas:
                        X = gen.scores([mu + k * d for k in range(K)], 1.0, rl, N, R, rng)
                        same, norev = _repeat_stats(X, N // 2, N - N // 2)
                        out.append({"mu": mu, "rho": rho, "K": K, "N": N, "delta": d,
                                    "same_ranking": same, "no_sig_reversal": norev})
    return out


def shrunk_gap(r):
    base = r["base_rate"]
    sol, tru = r["solver"], r["truth"]
    vals = [(base + 0.5 * (sol[n] - base) - tru[n]) ** 2 for n in sol]
    return sum(vals) / len(vals) - r["brier_solver"]


def part_b5(md: MData, idx, R, B, rng):
    rows = md.rows
    gap_exact = np.zeros(md.N)
    gap_shr = np.array([shrunk_gap(r) for r in rows])
    gap_base = np.array([r["brier_base"] - r["brier_solver"] for r in rows])
    gap_public = np.array([r["brier_public"] - r["brier_solver"] for r in rows])
    gap_model = md.y
    scripts = {"exact solver": gap_exact, "shrunk half-way to base": gap_shr, "base rate": gap_base,
               "public solver posterior (copies the table's view)": gap_public,
               "models (pilot1, as played)": gap_model}
    out = {"scripts": {}, "pairs": {}}

    def pooled_boot(v):
        S = np.bincount(md.g, weights=v, minlength=md.G)
        n = np.bincount(md.g, minlength=md.G).astype(float)
        cnt = np.stack([np.bincount(row, minlength=md.G) for row in idx])
        bs = (cnt @ S) / (cnt @ n)
        return float(S.sum() / n.sum()), pct(bs)

    for k, v in scripts.items():
        val, (lo, hi) = pooled_boot(v)
        out["scripts"][k] = {"mean": val, "lo": lo, "hi": hi}
    pairs = {"shrunk - exact": gap_shr - gap_exact, "base - exact": gap_base - gap_exact,
             "base - shrunk": gap_base - gap_shr, "public - exact": gap_public - gap_exact,
             "models - public": gap_model - gap_public}
    for k, v in pairs.items():
        val, (lo, hi) = pooled_boot(v)
        gm = np.array([v[r].mean() for r in md.rows_by_game])
        powers = {}
        for N in (2, 3, 4, 5, 6, 8, 10, 15, 20, 30, 40, 60, 80, 120):
            D = gm[rng.integers(0, gm.size, (N, R))]
            iv = run_intervals(D, B, rng, methods=("pct", "t"))
            powers[N] = {"pct": float(excludes0(iv["pct"]).mean()), "t": float(excludes0(iv["t"]).mean())}
        Ns = sorted(powers)
        out["pairs"][k] = {"mean": val, "lo": lo, "hi": hi, "per_game_sd": float(gm.std(ddof=1)),
                           "per_game_mean": float(gm.mean()), "games_below_0": int((gm < 0).sum()),
                           "power": powers,
                           "N80_pct": n80_from({n: powers[n]["pct"] for n in Ns}, Ns),
                           "N80_t": n80_from({n: powers[n]["t"] for n in Ns}, Ns)}
    return out


# =========================================================================== Part C

def pairwise_models(md: MData, idx, perms):
    L = len(md.models)
    S_p = np.bincount(md.p, weights=md.y, minlength=md.P)
    n_p = np.bincount(md.p, minlength=md.P).astype(float)
    A = onehot(md.model_p, L)
    means = (S_p @ A) / (n_p @ A)
    cnt = np.stack([np.bincount(row, minlength=md.G) for row in idx])     # B x G game counts
    wp = cnt[:, md.gp]                                                      # B x b
    bm = ((wp * S_p) @ A) / np.where((wp * n_p) @ A > 0, (wp * n_p) @ A, np.nan)
    labs = md.model_p[perms]
    Ap = np.zeros((labs.shape[0], md.P, L))
    Ap[np.repeat(np.arange(labs.shape[0]), md.P), np.tile(np.arange(md.P), labs.shape[0]), labs.ravel()] = 1
    pm = np.einsum("b,kbl->kl", S_p, Ap) / np.einsum("b,kbl->kl", n_p, Ap)
    out = {"models": md.models, "means": {}, "pairs": []}
    for i, m in enumerate(md.models):
        lo, hi = pct(bm[:, i])
        out["means"][m] = {"mean": float(means[i]), "lo": lo, "hi": hi, "n": int(n_p[md.model_p == i].sum()),
                           "games": int(len({md.gp[k] for k in np.flatnonzero(md.model_p == i)}))}
    for i in range(L):
        for j in range(i + 1, L):
            d = means[i] - means[j]
            lo, hi = pct(bm[:, i] - bm[:, j])
            pd = pm[:, i] - pm[:, j]
            pv = (1 + int((np.abs(pd) >= abs(d) - 1e-12).sum())) / (1 + pd.size)
            out["pairs"].append({"a": md.models[i], "b": md.models[j], "diff": float(d), "lo": lo, "hi": hi,
                                 "p_perm": pv, "excludes0": bool(lo > 0 or hi < 0)})
    return out


def unanimity(rows, idx_games, gids):
    votes = defaultdict(list)
    for r in rows:
        if r["row_type"] == "vote":
            votes[(r["game_id"], r["round"])].append(r["target"])
    per = []
    for (gid, rnd), ts in votes.items():
        top = Counter(ts).most_common(1)[0][1]
        per.append((gid, 1.0 if top == len(ts) - 1 else 0.0))
    gpos = {g: i for i, g in enumerate(gids)}
    S = np.zeros(len(gids))
    n = np.zeros(len(gids))
    for gid, v in per:
        S[gpos[gid]] += v
        n[gpos[gid]] += 1
    cnt = np.stack([np.bincount(row, minlength=len(gids)) for row in idx_games])
    bs = (cnt @ S) / (cnt @ n)
    k, N = int(S.sum()), int(n.sum())
    return {"unanimous": k, "votes": N, "share": k / N if N else None, "boot": pct(bs), "wilson": wilson(k, N)}


# =========================================================================== main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batches", nargs="+", default=["pilot1", "pilot2"])
    ap.add_argument("--games-dir", default=str(ROOT / "games"))
    ap.add_argument("--out", default=str(ROOT / "analysis" / "out"))
    ap.add_argument("--refresh", action="store_true",
                    help="rebuild decisions_<batch> for every batch after the first (runs decision_table.py)")
    ap.add_argument("--quick", action="store_true", help="few resamples, for a smoke test")
    args = ap.parse_args()
    t0 = time.time()
    out = Path(args.out)
    gdir = Path(args.games_dir)
    q = args.quick
    BOOT = 200 if q else 2000
    NPERM = 200 if q else 2000
    POW_REPS, NULL_REPS, INNER = (40, 100, 99) if q else (300, 1000, 199)
    R_ADD, B_ADD = (500, 300) if q else (4000, 1000)
    R_COV, B_COV = (500, 300) if q else (4000, 2000)
    R_GET, B_GET = (300, 200) if q else (1000, 1000)
    R_REP = 300 if q else 2000
    R_GREP = 200 if q else 1000
    SELF_REPS, COV_REPS, COV_BOOT = (200, 30, 100) if q else (1000, 200, 400)

    if args.refresh:
        for b in args.batches[1:]:
            cmd = [sys.executable, str(HERE / "decision_table.py"), "--batch", b, "--games-dir", str(gdir),
                   "--out", str(out)]
            print("running:", " ".join(cmd))
            subprocess.run(cmd, check=True)

    batches = args.batches
    main_b = batches[0]
    rows_by_batch = {b: load_rows(out, b) for b in batches}
    facts = {b: game_facts(gdir, b) for b in batches}
    rows = rows_by_batch[main_b]
    if not rows:
        sys.exit(f"no rows for {main_b} in {out}")
    R = {"batches": batches, "main": main_b, "settings": {"boot": BOOT, "perm": NPERM, "seed": SEED, "quick": q}}
    checks = []

    md = {k: MData(rows, k, facts[main_b]) for k in METRICS}
    for k in METRICS:
        checks.append({"check": f"rows for {k}", "value": md[k].N, "expected": EXPECTED_N[k],
                       "pass": md[k].N == EXPECTED_N[k]})
    oc = [v["order_check"] for v in facts[main_b].values()]
    checks.append({"check": "round-1 discussion order = seats clockwise from the first leader's left",
                   "value": f"{sum(1 for v in oc if v)} of {len(oc)} games", "pass": all(oc)})
    print(f"[{time.time() - t0:.0f}s] loaded {main_b}: " + ", ".join(f"{k} {md[k].N}" for k in METRICS))

    # one resample matrix of games shared by every statistic of the main batch
    G = md["read"].G
    gid_all = md["read"].game_ids
    for k in METRICS:
        if md[k].game_ids != gid_all and set(md[k].game_ids) != set(gid_all):
            print(f"note: {k} covers {md[k].G} games")
    rng_boot = np.random.default_rng(SEED)
    idx = rng_boot.integers(0, G, size=(BOOT, G))

    # ---------------- self-tests
    rng = np.random.default_rng(SEED + 11)
    st = {}
    st["t_quantile"] = {df: (t_quantile(0.975, df), ref) for df, ref in
                        ((2, 4.3027), (3, 3.1824), (4, 2.7764), (9, 2.2622), (19, 2.0930), (39, 2.0227), (59, 2.0010))}
    tq_ok = all(abs(a - b) < 0.01 for df, (a, b) in st["t_quantile"].items() if df >= 3)
    checks.append({"check": "t quantile (Cornish-Fisher) within 0.01 of tables, df >= 3",
                   "value": "; ".join(f"df {df}: {a:.4f} vs {b:.4f}" for df, (a, b) in st["t_quantile"].items()),
                   "pass": tq_ok})
    a1_raw = nested_mom(md["read"].y, md["read"].g, md["read"].p)
    planted = (max(a1_raw["s2g"], 1e-4), max(a1_raw["s2p"], 5e-5), a1_raw["s2e"])
    st["mom_read_shape"] = selftest_mom(md["read"], comps=planted, reps=SELF_REPS, cov_reps=COV_REPS,
                                        cov_boot=COV_BOOT, rng=rng)
    st["mom_getaway_shape"] = selftest_mom(md["getaway"], comps=(0.004, 0.002, 0.04), reps=SELF_REPS,
                                           cov_reps=COV_REPS, cov_boot=COV_BOOT, rng=rng)
    for nm in ("mom_read_shape", "mom_getaway_shape"):
        e = st[nm]["est"]
        checks.append({"check": f"variance estimator recovers planted components ({nm.split('_', 1)[1]})",
                       "value": "; ".join(f"{k} mean {v['mean']:.5f} vs {v['truth']:.5f} (z {v['z']:+.1f})"
                                          for k, v in e.items() if k in ("s2g_raw", "s2p_raw", "s2e")),
                       "pass": st[nm]["unbiased_pass"]})
    R["selftest"] = st
    print(f"[{time.time() - t0:.0f}s] self-tests done")

    # ---------------- Part A.1 + A.4
    A1 = {}
    for k in METRICS:
        A1[k] = part_a1(md[k], idx)
    print(f"[{time.time() - t0:.0f}s] A.1 done")

    # ---------------- Part A.2
    A2 = {}
    rng_p = np.random.default_rng(SEED + 2)
    for k in METRICS:
        A2[k] = part_a2(md[k], idx, NPERM, rng_p, A1[k]["boot_s2p_adj"], A1[k]["adj"]["s2p"],
                        POW_REPS, NULL_REPS, INNER)
        nr = A2[k]["model_power"]["rows"][0]
        checks.append({"check": f"permutation test (model) rejection rate with no model effect: {k}",
                       "value": f"{100 * nr['rejection_rate']:.1f}% (MC s.e. {100 * nr['mc_se']:.1f}%, "
                                f"{nr['reps']} null data sets)",
                       "pass": abs(nr["rejection_rate"] - 0.05) <= max(0.02, 3 * nr["mc_se"]) or nr["rejection_rate"] < 0.05})
        print(f"[{time.time() - t0:.0f}s] A.2 {k} done")

    # ---------------- Part A.3
    A3 = {}
    rng_s = np.random.default_rng(SEED + 3)
    seat_check = {}
    for ob in batches[1:]:
        orows = rows_by_batch[ob]
        A3[ob] = {}
        same_cast = []
        for gid, fa in facts[ob].items():
            m = next((v for v in facts[main_b].values() if v["seed"] == fa["seed"]), None)
            if m is not None and any(r["game_id"] == gid for r in orows):
                same_cast.append((fa["seed"], m["cast"] == fa["cast"]))
        seat_check[ob] = same_cast
        omd = {k: MData(orows, k, facts[ob]) for k in METRICS} if orows else {}
        for k in METRICS:
            if not orows or omd[k].N == 0:
                A3[ob][k] = {"all": {"pairs": 0}, "round1": {"pairs": 0}}
                continue
            A3[ob][k] = {"all": part_a3(md[k].game_means(), omd[k].game_means(), BOOT, rng_s),
                         "round1": part_a3(md[k].game_means(True), omd[k].game_means(True), BOOT, rng_s),
                         "games_other": omd[k].G}
        A3[ob]["games"] = len({r["game_id"] for r in orows})
        A3[ob]["same_cast"] = same_cast
        if same_cast:
            checks.append({"check": f"{ob} games have the same seating, models and roles as {main_b} on the same seed",
                           "value": f"{sum(1 for _, v in same_cast if v)} of {len(same_cast)}",
                           "pass": all(v for _, v in same_cast)})
    print(f"[{time.time() - t0:.0f}s] A.3 done")

    # ---------------- Part B
    gm = {k: np.array([v for v in md[k].game_means().values()]) for k in METRICS}
    sd_game = {}
    for k in METRICS:
        S = np.bincount(md[k].g, weights=md[k].y, minlength=G)
        n = np.bincount(md[k].g, minlength=G).astype(float)
        bs = []
        for row in idx:
            x = S[row] / n[row]
            bs.append(x.std(ddof=1))
        sd_game[k] = {"sd": float(gm[k].std(ddof=1)), "ci": pct(np.array(bs)), "mean": float(gm[k].mean()),
                      "games": int(gm[k].size)}
    gens = {k: AddGen(gm[k]) for k in ADDITIVE}
    gaw = GetawayGen(gm["getaway"])
    rng_b = np.random.default_rng(SEED + 4)
    sgrid, PB = part_b_additive(gens, R_ADD, B_ADD, rng_b)
    print(f"[{time.time() - t0:.0f}s] B additive power done")
    g_mus = (round(gaw.mu0, 4), 0.2, 0.4)
    g_deltas = (0.0, 0.02, 0.04, 0.06, 0.08, 0.10, 0.15, 0.20)
    PG = part_b_getaway(gaw, g_mus, g_deltas, R_GET, B_GET, rng_b)
    print(f"[{time.time() - t0:.0f}s] B getaway power done")
    cov_cases = ((round(gaw.mu0, 4), 0.0), (round(gaw.mu0, 4), 0.5), (0.2, 0.0), (0.2, 0.5))
    PB3 = part_b3(gens, gaw, R_COV, B_COV, rng_b, cov_cases)
    print(f"[{time.time() - t0:.0f}s] B.3 coverage done")
    s4grid, PB4 = part_b4_additive(gens, R_REP, rng_b)
    PB4G = part_b4_getaway(gaw, (round(gaw.mu0, 4), 0.2), (0.04, 0.08, 0.15, 0.2), R_GREP, rng_b)
    print(f"[{time.time() - t0:.0f}s] B.4 done")
    PB5 = part_b5(md["read"], idx, R_ADD, B_ADD, rng_b)
    print(f"[{time.time() - t0:.0f}s] B.5 done")

    # check: power at delta = 0 equals the false-positive rate
    for k in ADDITIVE:
        for N in (5, 10, 20, 40):
            p0 = float(PB[k][N]["pct"][0])
            fp = PB3[k][N]["pct"]["fpr"]
            se = math.sqrt(fp * (1 - fp) / R_COV + p0 * (1 - p0) / R_ADD)
            checks.append({"check": f"power at delta 0 = false-positive rate ({k}, N {N}, percentile)",
                           "value": f"{100 * p0:.1f}% vs {100 * fp:.1f}%", "pass": abs(p0 - fp) <= 3 * se + 1e-9})
    for c in PG["cells"]:
        if c["delta"] == 0 and c["c"] == 1.0 and c["rho"] in (0.0, 0.5) and c["N"] in (5, 10, 20, 40) \
                and c["mu"] in (round(gaw.mu0, 4), 0.2):
            fp = PB3[f"getaway mu={c['mu']} rho={c['rho']}"][c["N"]]["pct"]["fpr"]
            se = math.sqrt(max(fp * (1 - fp), 1e-4) / R_COV + max(c["pct"] * (1 - c["pct"]), 1e-4) / R_GET)
            checks.append({"check": f"power at delta 0 = false-positive rate (getaway mu {c['mu']}, rho {c['rho']}, N {c['N']})",
                           "value": f"{100 * c['pct']:.1f}% vs {100 * fp:.1f}%", "pass": abs(c["pct"] - fp) <= 3 * se})

    # ---------------- Part C
    perms_c = {k: within_game_perms(md[k].gp, NPERM, np.random.default_rng(SEED + 5)) for k in METRICS}
    PC = {k: pairwise_models(md[k], idx, perms_c[k]) for k in ("read", "getaway", "table_read", "vote_hit")}
    win = Counter(v["winner"] for v in facts[main_b].values())
    crew_w = win.get("crew", 0)
    n_games = sum(win.values())
    PCx = {"crew_wins": crew_w, "games": n_games, "wilson": wilson(crew_w, n_games),
           "unanimity": unanimity(rows, idx, gid_all)}

    R.update({"checks": checks, "A1": {k: {v: A1[k][v] for v in ("raw", "adj", "round")} for k in METRICS}, "A2": A2,
              "A3": A3, "sd_game": sd_game,
              "B_additive": {k: {N: {"pct_power": PB[k][N]["pct"][::10], "t_power": PB[k][N]["t"][::10],
                                     "pct_halfwidth_per_unit": PB[k][N]["pct_halfwidth_per_unit"],
                                     "t_halfwidth_per_unit": PB[k][N]["t_halfwidth_per_unit"]}
                                 for N in N_FINE} for k in ADDITIVE},
              "B_additive_sgrid_step10": sgrid[::10], "B_getaway": PG, "B3": PB3,
              "B4_additive": {k: {kk: {str(s): v for s, v in vv.items()} for kk, vv in d.items()} for k, d in PB4.items()},
              "B4_getaway": PB4G, "B5": PB5, "C": PC, "C_extra": PCx,
              "getaway_generator": {"mu0": gaw.mu0, "p0": gaw.p0, "Y": gaw.Y}})

    md_text, summary = render(R, md, A1, A2, A3, sd_game, gens, gaw, sgrid, PB, PG, PB3, s4grid, PB4, PB4G, PB5,
                              PC, PCx, st, checks, rows_by_batch, facts, args, t0)
    R["summary"] = summary
    (out / "variance_power.md").write_text(md_text)
    (out / "variance_power.json").write_text(json.dumps(jsonable(R), indent=1))
    print(f"[{time.time() - t0:.0f}s] wrote {out / 'variance_power.md'} and {out / 'variance_power.json'}")
    bad = [c for c in checks if not c["pass"]]
    print(f"checks: {len(checks) - len(bad)} of {len(checks)} pass" + ("" if not bad else ": FAILED " +
                                                                      "; ".join(c["check"] for c in bad)))
    print("rerun: python3.11 analysis/variance_power.py --refresh")


# =========================================================================== report

YARD = {}


def render(R, md, A1, A2, A3, sd_game, gens, gaw, sgrid, PB, PG, PB3, s4grid, PB4, PB4G, PB5, PC, PCx, st,
           checks, rows_by_batch, facts, args, t0):
    L = []
    w = L.append
    main_b = R["main"]
    G = md["read"].G
    BOOT = R["settings"]["boot"]
    summary = {}
    rows = rows_by_batch[main_b]

    # interval method: the one whose null false-positive rate stays in 4% to 6% most often (B.3)
    outside = {m: [(k, N, v[m]["fpr"]) for k, d in PB3.items() for N, v in d.items()
                   if not (0.04 <= v[m]["fpr"] <= 0.06)] for m in ("pct", "t", "bca", "stud")}
    add_out = {m: [b for b in bad if b[0] in ADDITIVE] for m, bad in outside.items()}
    rec = min(("t", "stud", "bca", "pct"), key=lambda m: (len(add_out[m]), len(outside[m])))
    pm = rec if rec in ("pct", "t") else "t"          # power curves exist for pct and t
    PMN = {"pct": "percentile bootstrap", "t": "paired t", "bca": "BCa", "stud": "studentized"}

    # yardsticks
    read_rows = md["read"].rows
    base_minus_solver = float(np.mean([r["brier_base"] for r in read_rows]) - np.mean([r["brier_solver"] for r in read_rows]))
    mm_read = [v["mean"] for v in PC["read"]["means"].values()]
    tr_rows = md["table_read"].rows
    tr_model_minus_base = float(np.mean([r["tr_err_model"] for r in tr_rows]) - np.mean([r["tr_err_base"] for r in tr_rows]))
    mm_tr = [v["mean"] for v in PC["table_read"]["means"].values()]
    vote_rows = md["vote_hit"].rows
    v_solver = float(np.mean([r["solver_best_hits_mole"] for r in vote_rows if r.get("solver_best_hits_mole") is not None]))
    v_base = float(np.mean([r["base_rate"] for r in vote_rows]))
    mm_vote = [v["mean"] for v in PC["vote_hit"]["means"].values()]
    yard = {
        "read": [("base-solver Brier distance", base_minus_solver), ("range of model means", max(mm_read) - min(mm_read))],
        "brier": [("base-solver Brier distance", base_minus_solver)],
        "table_read": [("model-minus-base error", abs(tr_model_minus_base)), ("range of model means", max(mm_tr) - min(mm_tr))],
        "vote_hit": [("solver-argmax minus random hit rate", v_solver - v_base), ("range of model means", max(mm_vote) - min(mm_vote))],
    }
    deltas = {
        "read": sorted({round(x, 4) for x in (0.005, 0.01, 0.02, 0.03, 0.04)} |
                       {round(base_minus_solver * fr, 4) for fr in (0.1, 0.25, 0.5, 1.0)} |
                       {round(max(mm_read) - min(mm_read), 4)}),
        "brier": sorted({round(base_minus_solver * fr, 4) for fr in (0.1, 0.25, 0.5, 1.0)} | {0.01, 0.02, 0.04}),
        "table_read": sorted({0.0025, 0.005, 0.01, 0.02, round(abs(tr_model_minus_base), 4),
                              round(max(mm_tr) - min(mm_tr), 4)}),
        "vote_hit": sorted({0.025, 0.05, 0.1, 0.15, 0.2, 0.3, round(v_solver - v_base, 3)}),
    }
    YARD.update(yard)
    R["yardsticks"] = yard
    R["delta_grid"] = deltas

    w("# Variance decomposition and power for Inside Job")
    w("")
    w(f"Generated by `python3.11 analysis/variance_power.py{' --quick' if R['settings']['quick'] else ''}` "
      f"(batches {', '.join(R['batches'])}; {time.time() - t0:.0f} s). Numbers for reuse: "
      "`analysis/out/variance_power.json`.")
    w("")
    w("## What the data are, and what they cannot be")
    w("")
    ob = R["batches"][1:]
    w(f"- `{main_b}`: {G} show games (seeds {min(md['read'].seed.values())} to {max(md['read'].seed.values())}). "
      "Seven seats, five cheap models, two of them seated twice, moles dealt at random. One game per deal, "
      "so inside this batch the deal and the particular playing of it (the *table*) cannot be separated: "
      "\"between games\" below means deal plus table.")
    for b in ob:
        n = A3.get(b, {}).get("games", 0)
        w(f"- `{b}`: {n} finished game(s) so far, on the same seeds, seating, models and moles as `{main_b}`, with one "
          "rule changed (`sabotage_target` 2 instead of 3). It is the only replay of a deal that exists, and it is "
          "confounded with the rule change.")
    w("- The benchmark is not a show game. It is a *trial*: one test model in all five crew seats (crew trial) or "
      "both mole seats (mole trial) against one fixed reference model, on the same deals for every model. **No "
      "trial has ever been played with real models.** Everything in Part B is an extrapolation from show games, "
      "made under stated assumptions, with a sensitivity range.")
    w(f"- Every interval marked *game bootstrap* is a 95% percentile interval from {BOOT} resamples of whole "
      f"games (seed {SEED}; one resample matrix shared by every statistic of `{main_b}`).")
    w("")
    w("Terms used throughout:")
    w("")
    w("- *decision*: one row of the decision table (one reading, one vote, one mole-round).")
    w("- *player*: one seat in one game (a codename; one model).")
    w("- *variance component*: the part of the variance of a single decision's value that comes from one level "
      "(game, player within game, decision within player). *share* = component / sum of the three.")
    w("- *ICC (game)*: share of the game component = the correlation between two decisions from the same game "
      "but different players. *ICC (player)*: (game + player) / total = the correlation between two decisions of "
      "the same player.")
    w("- *per-game mean*: the mean of a metric over every decision of that metric in one game (for crew metrics "
      "that is all five crew seats, which is what a crew trial would score for the test model).")
    w("- *rho*: the share of the variance of per-game means that belongs to the deal, i.e. the correlation "
      "between the per-game means of two playings of the same deal. *c*: a multiplier on the per-game variance "
      "(trial noise relative to show-game noise).")
    w("")

    ins = len(L)

    # ------------------------------------------------------------------ checks
    w("## Checks")
    w("")
    w("| check | result | pass |")
    w("|---|---|---|")
    for c in checks:
        w(f"| {c['check']} | {c['value']}" + (f" (expected {c['expected']})" if "expected" in c else "") +
          f" | {'yes' if c['pass'] else 'NO'} |")
    w("")
    for nm, lab in (("mom_read_shape", "Read"), ("mom_getaway_shape", "Getaway")):
        s = st[nm]
        bc = s["boot_coverage"]
        w(f"Self-test of the variance estimator, {lab} shape ({s['shape']['N']} decisions, {s['shape']['games']} "
          f"games, {s['shape']['players']} players, the pilot's exact layout): normal data with planted components "
          f"game {s['planted'][0]:.5f}, player {s['planted'][1]:.5f}, decision {s['planted'][2]:.5f}; {s['reps']} "
          "data sets. Mean estimate (sd across data sets): " +
          "; ".join(f"{k} {v['mean']:.5f} ({v['sd']:.5f})" for k, v in s["est"].items()) +
          f". The untruncated estimates are unbiased; truncating at zero biases them up. Coverage of the "
          f"game-bootstrap percentile interval ({bc['reps']} data sets x {bc['boot']} resamples): game component "
          f"{100 * bc['s2g']:.0f}%, game ICC {100 * bc['icc_game']:.0f}% (nominal 95%). With {G} games the "
          "bootstrap intervals for variance components are approximate and tend to be too narrow.")
        w("")

    # ------------------------------------------------------------------ Part A.1
    w("## Part A. Variance decomposition")
    w("")
    w("### A.1 Nested components")
    w("")
    w("Estimator: nested (hierarchical) one-way ANOVA, method-of-moments estimates for unbalanced data (expected "
      "mean squares with the unbalanced coefficients k1, k2, k3; Searle, Casella and McCulloch 1992, nested "
      "classifications). Model: value = mean + game + player(game) + decision. A negative player estimate is set "
      "to 0 and the game component re-solved without it; a negative game estimate is set to 0. *Raw*: the values "
      "as they are. *Adjusted*: after removing round and phase means (least-squares residuals on round dummies and, "
      "for readings, phase dummies clue / whisper / discuss / vote; refitted inside every bootstrap resample). "
      "Removing round means also removes part of the between-game variance, because long games contribute more "
      "late-round decisions.")
    w("")
    w("| metric | version | decisions | games | players | game var | player var | decision var | game share | player share | decision share | ICC game | ICC player |")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    summary["A1"] = {}
    for k in METRICS:
        for v in ("raw", "adj"):
            a = A1[k][v]
            ci = a["ci"]

            def c3(key, d=5, pc=False):
                return fci(a[key], ci[key][0], ci[key][1], d, pc)
            w(f"| {METRICS[k]['label']} | {v} | {a['N']} | {a['games']} | {a['players']} | {c3('s2g')} | {c3('s2p')} | "
              f"{c3('s2e')} | {c3('share_g', pc=True)} | {c3('share_p', pc=True)} | {c3('share_e', pc=True)} | "
              f"{c3('icc_game', 3)} | {c3('icc_player', 3)} |")
            summary["A1"][f"{k}|{v}"] = {kk: a[kk] for kk in ("share_g", "share_p", "share_e", "icc_game", "icc_player")}
    w("")
    w("Untruncated estimates (to show where a component is at its floor): " + "; ".join(
        f"{METRICS[k]['label']} game {A1[k]['raw']['s2g_raw']:.5f}, player {A1[k]['raw']['s2p_raw']:.5f}"
        for k in METRICS) + ".")
    w("")
    gw = md["getaway"]
    same_rounds = defaultdict(list)
    for r in gw.rows:
        same_rounds[(r["game_id"], r["round"])].append(r["getaway"])
    both = [v for v in same_rounds.values() if len(v) == 2]
    w(f"Getaway is a round-level quantity: in all {sum(1 for v in both if v[0] == v[1])} of {len(both)} mole-rounds "
      "with both moles alive, the two moles have the same Getaway (a blown job and the crew vote share are "
      "shared). The two moles of a game differ only in rounds after one is voted out. So Getaway has almost no "
      "between-player variance by construction, and nothing inside a game can tell two mole models apart.")
    w("")
    w("The same estimator with the round, not the player, as the middle level (game / round within game / "
      "decision; raw values). For crew votes and Getaway the round is the natural cluster: everyone votes on the "
      "same evidence, and a job is blown or not for both moles. A strongly negative untruncated player component "
      "(Getaway, crew vote hit above) is the sign that decisions of one player in different rounds are less alike "
      "than decisions of different players in the same round.")
    w("")
    w("| metric | game var | round var | decision var | game share | round share | decision share |")
    w("|---|---|---|---|---|---|---|")
    for k in METRICS:
        a = A1[k]["round"]
        ci = a["ci"]
        w(f"| {METRICS[k]['label']} | {fci(a['s2g'], *ci['s2g'], d=5)} | {fci(a['s2p'], *ci['s2p'], d=5)} | "
          f"{fci(a['s2e'], *ci['s2e'], d=5)} | {fci(a['share_g'], *ci['share_g'], pc=True)} | "
          f"{fci(a['share_p'], *ci['share_p'], pc=True)} | {fci(a['share_e'], *ci['share_e'], pc=True)} |")
    w("")

    # ------------------------------------------------------------------ Part A.2
    w("### A.2 Does the model (or seat, or speaking position) explain the between-player variance?")
    w("")
    w("Statistic: the extra share of residual variance explained by the factor's levels in a decision-level "
      "least-squares fit that already has game fixed effects plus round and phase dummies (partial R-squared). "
      f"Permutation test: the factor's labels are shuffled among the seats of the same role within each game "
      f"({R['settings']['perm']} permutations; a seat's decisions move together, game effects stay fixed); p = (1 + "
      "number of permuted statistics >= observed) / (1 + permutations). *Component*: the variance of the "
      "fitted level effects minus its mean under the permutations (so 0 means \"no more spread than chance\"), "
      "with a game-bootstrap interval (the fit is redone on each resample; the permutation mean is held at its "
      "full-data value, an approximation). *Share of player variance* = component / adjusted player variance "
      "from A.1. Speaking position = place in the round-1 discussion order (0 = first to speak, left of the first "
      "leader; 6 = the first leader).")
    w("")
    w("| metric | factor | levels | partial R2 | p (permutation) | component | share of player variance |")
    w("|---|---|---|---|---|---|---|")
    summary["A2"] = {}
    for k in METRICS:
        for fac in ("model", "seat", "speak_position"):
            a = A2[k][fac]
            if "error" in a:
                continue
            sh = a["share_of_player"]
            w(f"| {METRICS[k]['label']} | {fac} | {a['levels']} | {a['T_obs']:.4f} | {a['p']:.3f} | "
              f"{fci(a['component'], *a['component_ci'], d=5)} | "
              f"{fci(sh, *a['share_of_player_ci'], d=2) if sh is not None else '- (player variance 0)'} |")
            summary["A2"][f"{k}|{fac}"] = {"p": a["p"], "component": a["component"]}
    w("")
    w("Fitted model effects (decision-level, centred, after game, round and phase effects):")
    w("")
    for k in METRICS:
        e = A2[k]["model"]["effects"]
        w(f"- {METRICS[k]['label']}: " + ", ".join(f"`{m}` {v:+.4f}" for m, v in e.items()))
    w("")
    w("Power of the model test. A known model effect is planted in data whose real model labels have first been "
      "shuffled within games (so any real model effect is destroyed): the five models get effects evenly spaced "
      "over a range equal to a multiple of the range of raw per-model means seen in the pilot. Rejection rate "
      f"at p <= 0.05 (inner permutation test with {A2['read']['model_power']['inner_perm']} permutations). The "
      "first column (planted 0) is the test's false-positive rate.")
    w("")
    mults = [r["multiple_of_observed_range"] for r in A2["read"]["model_power"]["rows"]]
    w("| metric | observed range of model means | " + " | ".join(f"planted {m:g} x range" for m in mults) + " |")
    w("|---|---|" + "---|" * len(mults))
    for k in METRICS:
        pw = A2[k]["model_power"]
        w(f"| {METRICS[k]['label']} | {pw['observed_range_of_model_means']:.4f} | " +
          " | ".join(f"{100 * r['rejection_rate']:.0f}% (n={r['reps']})" for r in pw["rows"]) + " |")
    w("")
    mole_counts = Counter(md["getaway"].models[i] for i in md["getaway"].model_p)
    w("Mole seats per model in the pilot: " + ", ".join(f"`{m}` {n}" for m, n in sorted(mole_counts.items())) +
      ". Within a game the test compares only the two moles with each other, and a game whose two moles are "
      "the same model contributes nothing.")
    w("")
    n_solo = sum(1 for v in same_rounds.values() if len(v) == 1)
    w(f"Caveat for Getaway. The planted effect above is added to each mole's own rows, which real Getaway cannot "
      f"show: both moles share one value whenever both are alive, so a better mole model would lift both. The "
      f"only within-game contrast in the real data is the {n_solo} mole-rounds in which one mole played alone "
      "after the other was voted out; the observed model and seat p values for Getaway rest on those rounds "
      "(they reward the mole who survived longer, not the one who bluffed better on a shared job). The planted "
      "power for Getaway is therefore an upper bound that does not apply; the real power to tell mole models "
      f"apart inside show games is close to nil. Across the 15 tests in the table, about "
      f"{15 * 0.05:.2f} p values under 0.05 are expected by chance alone.")
    w("")

    # ------------------------------------------------------------------ Part A.3
    w("### A.3 Deal versus table: the only replay")
    w("")
    w(f"Pairs = seeds with a finished game in both `{main_b}` and the replay batch. Statistic: Pearson correlation "
      "across seeds of the per-game mean (all rounds, and round 1 only, where the rule change matters least). "
      "Interval: 95% percentile bootstrap over seeds (2,000 resamples), only with 5 or more pairs; a correlation "
      "needs at least 3 pairs and some variation in both.")
    w("")
    summary["A3"] = {}
    for b in ob:
        if b not in A3:
            continue
        w(f"Replay batch `{b}`: {A3[b].get('games', 0)} finished game(s). Same seating, models and moles: " +
          (", ".join(f"seed {s} {'yes' if v else 'NO'}" for s, v in A3[b].get('same_cast', [])) or "-") + ".")
        w("")
        w("| metric | scope | pairs | r | 95% interval | per-seed values (seed: main, replay) |")
        w("|---|---|---|---|---|---|")
        for k in METRICS:
            for sc in ("all", "round1"):
                a = A3[b][k][sc]
                vals = "; ".join(f"{s}: {x:.3f}, {y:.3f}" for s, x, y in a.get("values", []))
                ivs = "-" if a.get("lo") is None else "[{:.2f}, {:.2f}]".format(a["lo"], a["hi"])
                w(f"| {METRICS[k]['label']} | {sc} | {a['pairs']} | {f(a.get('r'))} | {ivs} | {vals or '-'} |")
                summary["A3"][f"{b}|{k}|{sc}"] = {"pairs": a["pairs"], "r": a.get("r"), "lo": a.get("lo"), "hi": a.get("hi")}
        w("")
    w("How weak this is: even with all 20 pairs, a correlation of 0.5 would carry a 95% interval of roughly "
      f"[{math.tanh(math.atanh(0.5) - Z975 / math.sqrt(17)):.2f}, {math.tanh(math.atanh(0.5) + Z975 / math.sqrt(17)):.2f}] "
      "(Fisher z, normal data), and the replay changes a rule, so any difference between the two playings mixes "
      "table noise with the rule's effect: the correlation is a lower bound on the deal share for the "
      "unchanged-rule case only if the rule change acts like extra noise. Part B therefore runs rho = 0, 0.25, "
      "0.5 and 0.75 instead of relying on it.")
    w("")

    # ------------------------------------------------------------------ Part A.4
    w("### A.4 Design effect: what a game is worth")
    w("")
    w("*m* = decisions per game (mean). *rho_w* = average correlation between two different decisions of the same "
      "game = (game component + pi x player component) / total, where pi is the share of within-game decision "
      "pairs that come from the same player. *Design effect* = 1 + (m - 1) x rho_w. *Effective decisions per game* = "
      "m / design effect; *effective total* = games x that. Raw components (round and phase not removed), because "
      "the per-game mean includes them. Interval: game bootstrap.")
    w("")
    w("| metric | decisions | games | m | pi | rho_w | design effect | effective per game | effective total |")
    w("|---|---|---|---|---|---|---|---|---|")
    summary["A4"] = {}
    for k in METRICS:
        a = A1[k]["raw"]
        ci = a["ci"]
        w(f"| {METRICS[k]['label']} | {a['N']} | {a['games']} | {a['m']:.1f} | {a['pi_same_player']:.2f} | "
          f"{a['rho_within_game']:.3f} | {fci(a['deff'], *ci['deff'], d=1)} | {fci(a['eff_per_game'], *ci['eff_per_game'], d=1)} | "
          f"{fci(a['eff_total'], *ci['eff_total'], d=0)} |")
        summary["A4"][k] = {"N": a["N"], "eff_total": a["eff_total"], "deff": a["deff"]}
    w("")
    w("These effective counts describe the precision of an overall pilot mean. For comparing models they are an "
      "upper bound: the comparison runs on per-game (per-deal) means, so the unit is the game, and 20 games are "
      "20 observations.")
    w("")

    # ------------------------------------------------------------------ Part B
    w("## Part B. Power simulation for the trial design")
    w("")
    w("**Set-up.** N deals. Each test model plays every deal twice against the reference model: once in the crew "
      "seats (gives Read) and once in the mole seats (gives Getaway and Table read). Two models are compared by the "
      "mean over deals of the paired difference of their per-deal scores (a per-deal score = the metric's mean over "
      "that game's decisions for the test model's seats). The interval is a 95% interval from resampling deals; a "
      "difference is *detected* when it excludes 0.")
    w("")
    w("**Generator.** Built from the pilot's 20 per-game means (empirical distribution, not a normal). For Read, "
      "raw Brier, Table read and crew vote hit: per-deal score = model mean + sqrt(rho) x a(deal) + sqrt(1 - rho) x "
      "b(play) with a and b drawn independently from the pilot's centred per-game means, scaled so the per-game "
      "variance is c times the pilot's. The deal part is shared by two models on one deal and cancels in the "
      "paired difference, so the difference is delta + u x (z1 - z2) with u = sd(per-game mean) x sqrt((1 - rho) x "
      "c). Under this generator rho and c act only through u: every result depends on delta / u. Getaway is mostly "
      f"zeros ({100 * (1 - gaw.p0):.0f}% of pilot games have per-game Getaway 0), so it gets its own two-part "
      "generator (below).")
    w("")
    w("Per-game standard deviation in the pilot (sd of the 20 per-game means; game-bootstrap interval):")
    w("")
    w("| metric | mean of per-game means | sd of per-game means | games |")
    w("|---|---|---|---|")
    for k in METRICS:
        s = sd_game[k]
        w(f"| {METRICS[k]['label']} | {s['mean']:.4f} | {fci(s['sd'], *s['ci'], d=4)} | {s['games']} |")
    w("")
    w("Standard unit u = sd x sqrt((1 - rho) x c) for each assumption:")
    w("")
    w("| metric | " + " | ".join(f"rho {r:g}, c {c:g}" for r in RHOS for c in SCALES) + " |")
    w("|---|" + "---|" * (len(RHOS) * len(SCALES)))
    for k in ADDITIVE:
        w(f"| {METRICS[k]['label']} | " + " | ".join(f"{gens[k].unit(r, c):.4f}" for r in RHOS for c in SCALES) + " |")
    w("")
    w("Yardsticks (pilot1, pooled over decisions): " + "; ".join(
        f"{METRICS[k]['label']}: " + ", ".join(f"{n} {v:.4f}" for n, v in yard[k]) for k in yard) +
      f". Getaway: pilot mean {gaw.mu0:.3f}; easier rules might give 0.2 or 0.4.")
    w("")

    # B.2 power tables, additive
    w("### B.1-B.2 Power, smallest detectable difference, deals needed")
    w("")
    w("Power tables are for rho = 0 and c = 1 (no deal cancellation, show-game noise). For any other assumption, "
      "read the row for delta' = delta / sqrt((1 - rho) x c): for example at rho = 0.5, c = 1 a true delta has the "
      "power shown here for delta / 0.71. Percentile bootstrap over deals (1,000 resamples, "
      f"{'4,000' if not R['settings']['quick'] else 'few'} simulated studies per N); in brackets the paired t "
      "interval.")
    w("")
    summary["B_N80"] = {}
    for k in ADDITIVE:
        gen = gens[k]
        u0 = gen.unit(0.0, 1.0)
        w(f"**{METRICS[k]['label']}** (per-game sd {gen.sd:.4f}). Power at rho 0, c 1:")
        w("")
        w("| delta | " + " | ".join(f"/ {n}" for n, _ in yard[k]) + " | " + " | ".join(f"N={N}" for N in N_GRID) + " |")
        w("|---|" + "---|" * len(yard[k]) + "---|" * len(N_GRID))
        for d in [0.0] + deltas[k]:
            cells = []
            for N in N_GRID:
                cells.append(f"{100 * power_at(sgrid, PB[k][N]['pct'], d / u0):.0f}% "
                             f"({100 * power_at(sgrid, PB[k][N]['t'], d / u0):.0f}%)")
            w(f"| {d:.4f} | " + " | ".join(f"{d / v:.2f}" for _, v in yard[k]) + " | " + " | ".join(cells) + " |")
        w("")
        w(f"Smallest difference detectable with 80% power ({PMN[pm]} interval; percentile bootstrap in brackets), "
          "by N and assumption:")
        w("")
        w("| N | " + " | ".join(f"rho {r:g} c {c:g}" for r in RHOS for c in SCALES) + " |")
        w("|---|" + "---|" * (len(RHOS) * len(SCALES)))
        summary.setdefault("B_d80", {})[k] = {}
        for N in N_GRID:
            s = s80(sgrid, PB[k][N][pm])
            sp = s80(sgrid, PB[k][N]["pct"])
            cells = []
            for r in RHOS:
                for c in SCALES:
                    u = gen.unit(r, c)
                    cells.append((f(s * u, 4) if s is not None else ">") + f" ({f(sp * u, 4) if sp is not None else '>'})")
                    summary["B_d80"][k][f"{N}|{r}|{c}"] = s * u if s is not None else None
            w(f"| {N} | " + " | ".join(cells) + " |")
        w("")
        w(f"Deals needed for 80% power ({PMN[pm]} interval; percentile bootstrap in brackets; smallest N on the grid "
          f"{', '.join(map(str, N_FINE))}, interpolated; '>400' = not reached). At very small N the percentile "
          "figure is flattered by its excess false positives (B.3):")
        w("")
        w("| delta | " + " | ".join(f"rho {r:g} c {c:g}" for r in RHOS for c in SCALES) + " |")
        w("|---|" + "---|" * (len(RHOS) * len(SCALES)))
        summary["B_N80"][k] = {}
        for d in deltas[k]:
            cells = []
            for r in RHOS:
                for c in SCALES:
                    u = gen.unit(r, c)
                    n80 = n80_from({N: power_at(sgrid, PB[k][N][pm], d / u) for N in N_FINE}, N_FINE)
                    n80p = n80_from({N: power_at(sgrid, PB[k][N]["pct"], d / u) for N in N_FINE}, N_FINE)
                    cells.append((f"{n80:.0f}" if n80 is not None else ">400") +
                                 f" ({f'{n80p:.0f}' if n80p is not None else '>400'})")
                    summary["B_N80"][k][f"{d}|{r}|{c}"] = n80
            w(f"| {d:.4f} | " + " | ".join(cells) + " |")
        w("")

    # Getaway
    w("**Getaway.** Two-part generator fitted to the pilot's per-game means: a game has any Getaway with "
      f"probability p (pilot {gaw.p0:.2f}) and then a positive per-game mean s x Y, capped at 1, with Y drawn from the "
      f"pilot's {gaw.Y.size} positive per-game means (mean {gaw.Y.mean():.3f}). To move the mean to mu, p and s both "
      "grow by sqrt(mu / pilot mean) (p capped at 0.95, s takes the rest); the variance multiplier c is applied by "
      "moving p with the mean held (s re-solved): smaller p and larger s = rarer, bigger getaways. Two models on "
      "one deal share latent normals (Gaussian copula), calibrated so that two identical models' per-deal scores "
      "correlate rho. Model B sits at mu, model A at mu + delta. Simulated studies per cell: "
      f"{R['settings'].get('get_R', 1000 if not R['settings']['quick'] else 300)}.")
    w("")
    w("| mu | c | p | s | mean | sd per game | sd asked for |")
    w("|---|---|---|---|---|---|---|")
    for key, prm in PG["params"].items():
        mu, c = key.split("|")
        w(f"| {mu} | {c} | {prm['p']:.3f} | {prm['s']:.2f} | {prm['mean']:.3f} | {math.sqrt(prm['var']):.3f} | "
          f"{math.sqrt(prm['var_target']):.3f} |")
    w("")
    w("Where *sd per game* is below *sd asked for*, the request could not be met with p capped at 0.95 (a game "
      "with no getaway at all stays possible); the achieved value is what was simulated. "
      f"Note the pilot mean here ({gaw.mu0:.3f}) is the mean of per-game means (every game weighted equally); "
      f"pooled over mole-rounds it is {md['getaway'].y.mean():.3f}.")
    w("")
    cells = PG["cells"]
    gm_list = sorted({c["mu"] for c in cells})
    gd_list = sorted({c["delta"] for c in cells})
    summary["B_N80"]["getaway"] = {}
    for mu in gm_list:
        w(f"Getaway, mu = {mu}: power (percentile; paired t in brackets) at c = 1, rho = 0 | rho = 0.5:")
        w("")
        w("| delta | delta / mu | " + " | ".join(f"N={N}" for N in N_GRID) + " |")
        w("|---|---|" + "---|" * len(N_GRID))
        for d in gd_list:
            row = []
            for N in N_GRID:
                a = next(c for c in cells if c["mu"] == mu and c["c"] == 1.0 and c["rho"] == 0.0 and c["N"] == N and c["delta"] == d)
                b = next(c for c in cells if c["mu"] == mu and c["c"] == 1.0 and c["rho"] == 0.5 and c["N"] == N and c["delta"] == d)
                row.append(f"{100 * a['pct']:.0f}% ({100 * a['t']:.0f}%) / {100 * b['pct']:.0f}%")
            w(f"| {d:.2f} | {d / mu:.2f} | " + " | ".join(row) + " |")
        w("")
        w(f"Getaway, mu = {mu}: deals for 80% power (paired t interval, which is conservative for Getaway, B.3; "
          f"interpolated on N = {', '.join(map(str, N_GRID))}; beyond 120 the normal approximation "
          "7.85 x var(D) / delta^2 using the simulated var(D), marked ~):")
        w("")
        w("| delta | " + " | ".join(f"rho {r:g} c {c:g}" for r in RHOS for c in SCALES) + " |")
        w("|---|" + "---|" * (len(RHOS) * len(SCALES)))
        for d in gd_list:
            if d == 0:
                continue
            row = []
            for r in RHOS:
                for c in SCALES:
                    sub = {x["N"]: x for x in cells if x["mu"] == mu and x["c"] == c and x["rho"] == r and x["delta"] == d}
                    n80 = n80_from({N: sub[N]["t"] for N in N_GRID}, N_GRID)
                    if n80 is None:
                        vd = sub[N_GRID[-1]]["var_D"]
                        approx = (Z975 + Z80) ** 2 * vd / d ** 2
                        row.append(f"~{approx:.0f}")
                        summary["B_N80"]["getaway"][f"{mu}|{d}|{r}|{c}"] = approx
                    else:
                        row.append(f"{n80:.0f}")
                        summary["B_N80"]["getaway"][f"{mu}|{d}|{r}|{c}"] = n80
            w(f"| {d:.2f} | " + " | ".join(row) + " |")
        w("")

    # B.3
    w("### B.3 Does the interval method hold its error rate at small N?")
    w("")
    w("Null: two identical models (delta = 0). Share of simulated studies whose 95% interval excludes 0 (the "
      f"false-positive rate; nominal 5%; Monte Carlo s.e. about {100 * math.sqrt(0.05 * 0.95 / (4000 if not R['settings']['quick'] else 500)):.1f} "
      "points). Methods: *pct* = percentile bootstrap over deals; *t* = paired t interval; *BCa* = bias-corrected "
      "and accelerated bootstrap (jackknife acceleration); *stud* = studentized (bootstrap-t) interval. "
      f"{2000 if not R['settings']['quick'] else 300} bootstrap resamples. For the additive metrics the result does "
      "not depend on rho or c (all four methods are scale-equivariant).")
    w("")
    w("| metric | N | pct | t | BCa | stud |")
    w("|---|---|---|---|---|---|")
    for k, d in PB3.items():
        lab = METRICS[k]["label"] if k in METRICS else k
        for N, v in d.items():
            extra = f" (all-zero studies {100 * v['all_zero_share']:.0f}%)" if "all_zero_share" in v else ""
            w(f"| {lab}{extra} | {N} | " + " | ".join(f"{100 * v[m]['fpr']:.1f}%" for m in ("pct", "t", "bca", "stud")) + " |")
    w("")
    ok = outside
    w("Cells outside 4% to 6%, by method: " + "; ".join(
        f"{m}: {len(b)} of {sum(len(d) for d in PB3.values())}" + (" (" + ", ".join(f"{k} N {N} {100 * x:.1f}%" for k, N, x in b[:8]) + (" ..." if len(b) > 8 else "") + ")" if b else "")
        for m, b in ok.items()) + ".")
    w("")
    summary["B3_recommended"] = rec
    summary["B3_cells_outside"] = {m: len(b) for m, b in ok.items()}
    R["B3_recommended"] = rec
    w(f"Recommended method (fewest cells outside 4% to 6% on the continuous metrics, then overall): **{rec}** "
      f"({PMN[rec]}). The percentile bootstrap, the method named in docs/CLAIMS.md, rejects a true null far more "
      "often than 5% at 5 to 20 deals, because a resample of a few deals underestimates the spread; BCa is no "
      "better. No method holds 4% to 6% for Getaway near its floor: there the t interval is conservative "
      "(rejects too rarely) and the bootstrap ones too liberal.")
    w("")
    w("Null-test gate (G1: one model entered under two names on the same N deals): expected 95% half-width of the "
      f"recommended interval ({rec}), in the metric's own units, by assumption. Under the additive generator "
      "half-width = (half-width per unit) x u.")
    w("")
    w("| metric | N | " + " | ".join(f"rho {r:g} c {c:g}" for r in RHOS for c in SCALES) + " |")
    w("|---|---|" + "---|" * (len(RHOS) * len(SCALES)))
    summary["B3_halfwidth"] = {}
    for k in ADDITIVE:
        for N in (5, 10, 20, 40):
            hpu = PB3[k][N][rec]["half_per_unit"]
            w(f"| {METRICS[k]['label']} | {N} | " + " | ".join(f"{hpu * gens[k].unit(r, c):.4f}" for r in RHOS for c in SCALES) + " |")
            summary["B3_halfwidth"][f"{k}|{N}"] = {f"{r}|{c}": hpu * gens[k].unit(r, c) for r in RHOS for c in SCALES}
    w("")
    w("Getaway (c = 1), half-width of the recommended interval in Getaway units: " + "; ".join(
        f"{key.replace('getaway ', '')}: " + ", ".join(f"N {N} {v[rec]['half_raw']:.4f}" for N, v in d.items())
        for key, d in PB3.items() if key not in METRICS) + ".")
    w("")

    # B.4
    w("### B.4 Repeatability gate (G3)")
    w("")
    w("K models whose true scores are spaced delta apart; N deals split into two halves by seed (N/2 each); every "
      "model plays every deal. *Same ranking*: the two halves give the same strict order of all K model means. "
      "*No significant reversal*: no pair of models has paired t intervals that exclude 0 with opposite signs in "
      "the two halves (a weaker gate: a reversal must be significant in both halves to count). Rho = 0, c = 1 "
      "(other assumptions: rescale delta as in B.2). "
      f"{2000 if not R['settings']['quick'] else 300} simulated studies per cell.")
    w("")
    for k in ("read", "table_read", "brier", "vote_hit"):
        u0 = gens[k].unit(0, 1)
        dl = list(deltas[k])
        for K in (3, 4, 5):
            w(f"{METRICS[k]['label']}, K = {K}: same ranking / no significant reversal")
            w("")
            w("| N | " + " | ".join(f"delta {d:.4f}" for d in dl) + " |")
            w("|---|" + "---|" * len(dl))
            for N in N_GRID:
                res = PB4[k][f"{K}|{N}"]
                ss = sorted(res)
                cells = []
                for d in dl:
                    s = d / u0
                    same = float(np.interp(s, ss, [res[x]["same_ranking"] for x in ss]))
                    nr = float(np.interp(s, ss, [res[x]["no_sig_reversal"] for x in ss]))
                    cells.append(f"{100 * same:.0f}% / {100 * nr:.0f}%")
                w(f"| {N} | " + " | ".join(cells) + " |")
            w("")
        if k == "table_read":
            w("Raw crew Brier and crew vote hit tables are in the JSON (`B4_additive`); they follow the same rule.")
            w("")
            break
    w("Getaway (c = 1): same ranking / no significant reversal")
    w("")
    for mu in sorted({x["mu"] for x in PB4G}):
        for rho in (0.0, 0.5):
            for K in (3, 5):
                dl = sorted({x["delta"] for x in PB4G})
                w(f"mu = {mu}, rho = {rho}, K = {K}:")
                w("")
                w("| N | " + " | ".join(f"delta {d:.2f}" for d in dl) + " |")
                w("|---|" + "---|" * len(dl))
                for N in N_GRID:
                    cells = []
                    for d in dl:
                        x = next(x for x in PB4G if x["mu"] == mu and x["rho"] == rho and x["K"] == K and x["N"] == N and x["delta"] == d)
                        cells.append(f"{100 * x['same_ranking']:.0f}% / {100 * x['no_sig_reversal']:.0f}%")
                    w(f"| {N} | " + " | ".join(cells) + " |")
                w("")

    # B.5
    w("### B.5 Known-skill gate (G2), crew side")
    w("")
    w("Scripts scored on the pilot's own crew readings (what each script would have written at the same moment, "
      "same rated players): *exact solver* reports the solver posterior (Read gap 0 by definition); *shrunk* "
      "reports base + 0.5 x (solver - base); *base rate* reports moles alive / players rated; *public solver "
      "posterior* reports the solver's posterior from public information only (the script docs/CLAIMS.md names "
      "in Read's falsification test). Pooled mean Read gap "
      f"over {md['read'].N} readings in {G} games, game-bootstrap interval. Caveat: in a trial the scripts would play "
      "their own games (their votes change who is eliminated), so the readings would not be these; the per-game "
      "spread here comes from model-played games.")
    w("")
    w("| script | mean Read gap |")
    w("|---|---|")
    for k, v in PB5["scripts"].items():
        w(f"| {k} | {fci(v['mean'], v['lo'], v['hi'], 4)} |")
    w("")
    w("Paired differences (per-deal score of the first minus the second), and deals needed to separate them "
      "with 80% power (resampling the 20 per-game differences as the population; paired t interval, percentile "
      "bootstrap in brackets; the percentile figure at 2 to 5 deals is inflated by false positives). The pair "
      "*models - public* is not a script pair: it is the pilot's own models against the public-posterior script on "
      "the same readings, the comparison in Read's falsification test:")
    w("")
    Ns5 = sorted(next(iter(PB5["pairs"].values()))["power"])
    w("| pair | mean difference | per-game sd | games with difference < 0 | " + " | ".join(f"N={n}" for n in Ns5) + " | N for 80% |")
    w("|---|---|---|---|" + "---|" * len(Ns5) + "---|")
    for k, v in PB5["pairs"].items():
        w(f"| {k} | {fci(v['mean'], v['lo'], v['hi'], 4)} | {v['per_game_sd']:.4f} | {v['games_below_0']} of {G} | " +
          " | ".join(f"{100 * v['power'][n]['t']:.0f}% ({100 * v['power'][n]['pct']:.0f}%)" for n in Ns5) +
          f" | {f(v['N80_t'], 1) if v['N80_t'] else '>120'} ({f(v['N80_pct'], 1) if v['N80_pct'] else '>120'}) |")
    w("")

    # ------------------------------------------------------------------ Part C
    w("## Part C. What 20 show games cannot support")
    w("")
    rd = PC["read"]
    w(f"**Pairwise model differences in Read** (pooled mean read_gap per model, raw; game-bootstrap interval of the "
      f"difference; two-sided permutation p from shuffling crew labels within games, {R['settings']['perm']} "
      f"permutations; overall model test p = {A2['read']['model']['p']:.3f} from A.2):")
    w("")
    w("| model | decisions | games | mean read_gap |")
    w("|---|---|---|---|")
    for m, v in rd["means"].items():
        w(f"| `{m}` | {v['n']} | {v['games']} | {fci(v['mean'], v['lo'], v['hi'], 4)} |")
    w("")
    w("| A | B | A - B | p (permutation) |")
    w("|---|---|---|---|")
    for pr in rd["pairs"]:
        w(f"| `{pr['a']}` | `{pr['b']}` | {fci(pr['diff'], pr['lo'], pr['hi'], 4)} | {pr['p_perm']:.3f} |")
    w("")
    for k in ("getaway", "table_read", "vote_hit"):
        pc = PC[k]
        nx = sum(1 for p in pc["pairs"] if p["excludes0"])
        minp = min(p["p_perm"] for p in pc["pairs"])
        w(f"- **{METRICS[k]['label']} by model**: " + ", ".join(
            f"`{m}` {fci(v['mean'], v['lo'], v['hi'], 3)} (n {v['n']}, {v['games']} games)" for m, v in pc["means"].items()) +
          f". Pairs whose bootstrap interval excludes 0: {nx} of {len(pc['pairs'])}; smallest pairwise permutation "
          f"p {minp:.3f}; overall model test p {A2[k]['model']['p']:.3f}.")
    w("")
    lo, hi = PCx["wilson"]
    w(f"- **Crew win rate**: {PCx['crew_wins']} of {PCx['games']} games, Wilson 95% interval "
      f"{100 * lo:.0f}% to {100 * hi:.0f}%. The pilot shows the crew side is strong; it cannot say whether the true "
      "rate is 76% or 99%.")
    u = PCx["unanimity"]
    w(f"- **Unanimous votes** (the \"pile-on\" verdict, threshold < 50%): {u['unanimous']} of {u['votes']} "
      f"votes ({100 * u['share']:.0f}%), Wilson {100 * u['wilson'][0]:.0f}% to {100 * u['wilson'][1]:.0f}%, game "
      f"bootstrap {100 * u['boot'][0]:.0f}% to {100 * u['boot'][1]:.0f}%. The FAIL in docs/pilot1_report.md sits "
      "exactly on the threshold; the data cannot tell pass from fail.")
    w("- **The other two verdicts**: moles lie 18 of 20 (Wilson 70% to 97%, threshold 80%) and finales "
      "split/split 17 of 19 (Wilson 69% to 97%, threshold 80%): both intervals contain their threshold, so PASS and "
      "FAIL there are not established either (counts from docs/pilot1_report.md).")
    w("- **Per-model Read intervals that exclude 0** in the decision summary (`claude-sonnet-4-6`, "
      "`claude-sonnet-5`): each is one of five models checked, the intervals ignore that a model's seats sit in "
      "particular games, and the model test (A.2) is the right test for \"models differ\".")
    w("- **Round-by-round Read** (round 3 gap 0.054 from 14 games, round 4 from 6): later rounds exist only in "
      "longer games, so round means mix round effects with which games lasted.")
    w("- **Per-model lie rates and finale behaviour** in docs/pilot1_report.md use Wilson intervals over claims "
      "or seats as if independent; claims cluster within seats and games (A.4 shows how much clustering costs for "
      "the decision metrics), so those intervals are too narrow. This is a judgement, not computed here: the "
      "decision table has no claim rows.")
    w("- **The rule change** (pilot2): with the replay so far it is impossible to separate the rule's effect from "
      "replay noise.")
    w("")

    # ------------------------------------------------------------------ summary (inserted near the top)
    def n80a(k, d, r, c, m=pm):
        u = gens[k].unit(r, c)
        return n80_from({N: power_at(sgrid, PB[k][N][m], d / u) for N in N_FINE}, N_FINE)

    def nfmt(x):
        return ">400" if x is None else f"{x:.0f}"

    def span(k, d):
        vals = [n80a(k, d, r, c) for r in RHOS for c in SCALES]
        lo_ = min((v for v in vals if v is not None), default=None)
        hi_ = None if any(v is None for v in vals) else max(vals)
        return f"{nfmt(lo_)} to {nfmt(hi_)} (rho 0, c 1: {nfmt(n80a(k, d, 0.0, 1.0))})"

    S = []
    s = S.append
    s("## Summary")
    s("")
    s("### What the data show")
    s("")
    a, ci = A1["read"]["raw"], A1["read"]["raw"]["ci"]
    s(f"- **Read: most of the variance is between single readings, about a third between games.** Raw shares "
      f"(game bootstrap, {G} games, "
      f"{a['N']} readings): game {100 * a['share_g']:.0f}% [{100 * ci['share_g'][0]:.0f}%, {100 * ci['share_g'][1]:.0f}%], "
      f"player within game {100 * a['share_p']:.0f}% [{100 * ci['share_p'][0]:.0f}%, {100 * ci['share_p'][1]:.0f}%], "
      f"decision {100 * a['share_e']:.0f}%. The {a['N']} readings are worth about {a['eff_total']:.0f} "
      f"[{ci['eff_total'][0]:.0f}, {ci['eff_total'][1]:.0f}] independent ones (design effect {a['deff']:.0f}).")
    for k in ("getaway", "table_read", "vote_hit"):
        a, ci = A1[k]["raw"], A1[k]["raw"]["ci"]
        s(f"- {METRICS[k]['label']}: game share {100 * a['share_g']:.0f}% [{100 * ci['share_g'][0]:.0f}%, "
          f"{100 * ci['share_g'][1]:.0f}%], player share {100 * a['share_p']:.0f}%; {a['N']} decisions worth about "
          f"{a['eff_total']:.0f} independent ones.")
    s(f"- **Which model sat in a seat explains none of the between-player variance that can be detected** "
      f"(permutation p: Read {A2['read']['model']['p']:.2f}, raw Brier {A2['brier']['model']['p']:.2f}, Table read "
      f"{A2['table_read']['model']['p']:.2f}, crew vote hit {A2['vote_hit']['model']['p']:.2f}). The test had about "
      f"{100 * A2['read']['model_power']['rows'][2]['rejection_rate']:.0f}% power for Read model effects as large as "
      "the spread of model means the pilot shows, so this is weak evidence against such effects, not proof of none. "
      f"Getaway's p = {A2['getaway']['model']['p']:.3f} (and seat p = {A2['getaway']['seat']['p']:.3f}) comes from "
      "the few rounds a mole played alone and is one of 15 tests.")
    for b in ob:
        if b not in A3:
            continue
        parts = []
        for k in ("read", "brier", "table_read", "getaway"):
            a = A3[b][k]["all"]
            iv = "" if a.get("lo") is None else " [{:.2f}, {:.2f}]".format(a["lo"], a["hi"])
            parts.append(f"{METRICS[k]['label']} r = {f(a.get('r'), 2)}{iv}")
        s(f"- **Deal versus table: not measurable yet.** The replay (`{b}`) has {A3[b]['read']['all']['pairs']} "
          "finished pair(s) of seeds: " + "; ".join(parts) + " (all rounds; bootstrap over seeds, none under 5 "
          "pairs). With so few pairs the intervals span most of [-1, 1], and the replay changes a rule, so these "
          "numbers do not fix rho.")
    fp = {N: PB3["read"][N]["pct"]["fpr"] for N in (5, 10, 20, 40)}
    ft = {N: PB3["read"][N]["t"]["fpr"] for N in (5, 10, 20, 40)}
    s(f"- **The percentile bootstrap over deals is too liberal at small N.** False-positive rate for Read at N = 5, "
      f"10, 20, 40: {', '.join(f'{100 * v:.1f}%' for v in fp.values())} (paired t: "
      f"{', '.join(f'{100 * v:.1f}%' for v in ft.values())}). Recommended: **{PMN[rec]}**.")
    yd = yard["read"][0][1]
    s(f"- **Deals for 80% power, Read** ({PMN[pm]} interval; range over the 12 assumptions rho 0 to 0.75, c 0.5 "
      f"to 2): delta = {0.25 * yd:.4f} (a quarter of the base-to-solver distance): {span('read', round(0.25 * yd, 4))}; "
      f"delta = {0.5 * yd:.4f} (half): {span('read', round(0.5 * yd, 4))}; delta = {yd:.4f} (all of it): "
      f"{span('read', round(yd, 4))}; delta = {yard['read'][1][1]:.4f} (the pilot's spread of model means): "
      f"{span('read', round(yard['read'][1][1], 4))}.")
    ytr = yard["table_read"][0][1]
    s(f"- **Table read**: delta = {ytr:.4f} (the pilot's model-minus-base error): {span('table_read', round(ytr, 4))}; "
      f"delta = {yard['table_read'][1][1]:.4f} (spread of model means): {span('table_read', round(yard['table_read'][1][1], 4))}.")
    gN = summary["B_N80"]["getaway"]

    def gspan(mu, d):
        vals = [gN.get(f"{mu}|{d}|{r}|{c}") for r in RHOS for c in SCALES]
        vals = [v for v in vals if v is not None]
        c0 = gN.get(f"{mu}|{d}|0.0|1.0")
        return f"{min(vals):.0f} to {max(vals):.0f} (rho 0, c 1: {c0:.0f})" if vals else "-"
    mu0 = gm_list[0]
    s(f"- **Getaway** (paired t; beyond 120 deals by normal approximation): at the pilot's mean {mu0}, delta 0.04: "
      f"{gspan(mu0, 0.04)}, delta 0.08: {gspan(mu0, 0.08)}; at mean 0.2, delta 0.04: {gspan(0.2, 0.04)}, delta 0.1: "
      f"{gspan(0.2, 0.1)}; at mean 0.4, delta 0.1: {gspan(0.4, 0.1)}. Under the rescaling rule the per-game "
      "spread grows with the mean, so a fixed raw delta gets harder as rules get easier for moles; relative to the "
      "mean it gets easier.")
    v5 = PB5["pairs"]
    s(f"- **Known-skill gate (G2) is cheap on the crew side**: shrunk minus exact solver "
      f"{v5['shrunk - exact']['mean']:.4f} (positive in {G - v5['shrunk - exact']['games_below_0']} of {G} games), "
      f"80% power at about {f(v5['shrunk - exact']['N80_t'], 0)} deals; base minus shrunk at about "
      f"{f(v5['base - shrunk']['N80_t'], 0)}. The public-posterior script scores "
      f"{PB5['scripts']['public solver posterior (copies the table' + chr(39) + 's view)']['mean']:.4f}, the pilot's "
      f"models {PB5['scripts']['models (pilot1, as played)']['mean']:.4f} (models minus public "
      f"{v5['models - public']['mean']:+.4f} [{v5['models - public']['lo']:+.4f}, {v5['models - public']['hi']:+.4f}]).")
    rep = PB4["read"]["3|60"]
    ss = sorted(rep)
    u0 = gens["read"].unit(0, 1)
    p_same = float(np.interp(0.5 * yd / u0, ss, [rep[x]["same_ranking"] for x in ss]))
    s(f"- **Repeatability gate (G3)**: three models spaced {0.5 * yd:.4f} apart in Read (half the base-to-solver "
      f"distance), 60 deals split 30/30, rho 0, c 1: both halves give the same full ranking in {100 * p_same:.0f}% of "
      "studies. The weaker gate (no significant reversal) passes almost always, even with no true differences.")
    s("")
    s(f"*Affordable* here means at most {AFFORD} deals per test model (about {AFFORD * 110:,} calls and {AFFORD * 40 / 60:.0f} "
      f"hours of game time for its two games per deal); {STRETCH} deals ({STRETCH * 110:,} calls, {STRETCH * 40 / 60:.0f} hours) is a "
      "stretch. Under that budget:")
    s("")
    unaff = []
    for k in ADDITIVE:
        for d in deltas[k]:
            best = n80a(k, d, 0.75, 0.5)
            cen = n80a(k, d, 0.0, 1.0)
            if best is None or best > AFFORD:
                unaff.append(f"{METRICS[k]['label']} delta {d:.4f} (needs {nfmt(best)} even at rho 0.75, c 0.5)")
            elif cen is None or cen > AFFORD:
                unaff.append(f"{METRICS[k]['label']} delta {d:.4f} (affordable only if rho is high or c low; "
                             f"rho 0, c 1 needs {nfmt(cen)})")
    for mu in gm_list:
        for d in gd_list:
            if d == 0:
                continue
            best = gN.get(f"{mu}|{d}|0.75|0.5")
            cen = gN.get(f"{mu}|{d}|0.0|1.0")
            if best is not None and best > AFFORD:
                unaff.append(f"Getaway mean {mu} delta {d:.2f} (needs about {best:.0f} even at rho 0.75, c 0.5)")
            elif cen is not None and cen > AFFORD:
                unaff.append(f"Getaway mean {mu} delta {d:.2f} (affordable only if rho is high or c low; rho 0, c 1 "
                             f"needs about {cen:.0f})")
    for x in unaff:
        s(f"- {x}")
    s("")
    s("### What I believe but the data do not show")
    s("")
    s("- The deal share rho is probably small for Read and larger for raw Brier: Read subtracts the solver's Brier, "
      "which already absorbs how informative the deal's clues were, so what remains is mostly how this table "
      "played. If so, the paired same-deal design buys little for Read and the rho = 0 to 0.25 columns are the "
      "realistic ones. Only finished same-rule replays can test this.")
    s("- A crew trial puts five copies of one model in the crew seats. Their readings will share blind spots, which "
      "raises the per-game variance (c above 1) rather than lowering it. I would plan with c = 1 to 2.")
    s("- Getaway at the pilot's rules sits near its floor (mean about 0.06 to 0.08) and can only be powered for "
      "large differences; CLAIMS.md's own floor test (mean under 0.10 for every model) would very likely fail. The "
      "rules need to make moles stronger before Bluff can be ranked.")
    s("- The percentile interval named in docs/CLAIMS.md should be replaced by the paired t interval (or the "
      "minimum N raised to about 40), before the analysis plan is frozen.")
    s("")
    L[ins:ins] = S
    return "\n".join(L) + "\n", summary


if __name__ == "__main__":
    main()
