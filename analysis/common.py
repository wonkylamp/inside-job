"""Shared helpers for reading finished Inside Job logs (no model calls, no writes to `games/`).

What is here, so later scripts can import it:

- `load_games(games_dir, batch)` -> [GameData]: the batch's finished games (via
  `inside_job.report.load_batch`, which keeps only games with a `game_end`), each wrapped with
  indexes (cast, roles, rounds, turns, per-turn information cutoffs).
- `GameData.cutoff(turn)`: the last seq the player could have seen when their prompt was built.
  Simultaneous phases (clue, job, vote, cut_vote, finale_choice) build every prompt before any
  reply is written, so the cutoff is the seq just before the FIRST turn of that phase in that round.
  Whisper steps run in lockstep across pairs (engine `phase_whispers`: step k of every pair is
  prepared in parallel), so the cutoff is the seq before the first turn of that step; this sees
  exactly the same events as seq-1 (other pairs' whisper turns are invisible to the speaker), it
  is just the faithful rule. Sequential phases (pick, discuss, cut_pitch, finale_pitch): seq-1.
- `GameData.posterior(cutoff, viewpoint)`: the solver posterior (cached), viewpoint "table" or a
  player name, through `solver.from_log` -> `visible_events`.
- Scores: `brier`, `log_score`; `argmax_set`.
- `Boot`: 95% percentile bootstrap that resamples whole games.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from inside_job.report import load_batch  # noqa: E402
from inside_job.solver import from_log, table_posterior  # noqa: E402

SIMULTANEOUS = ("clue", "job", "vote", "cut_vote", "finale_choice")
SEQUENTIAL = ("pick", "discuss", "cut_pitch", "finale_pitch")
SUSPICION_PHASES = ("clue", "whisper", "discuss", "vote")
CLIP = (0.01, 0.99)
NONE = "none"


# --------------------------------------------------------------------------- scores

def brier(probs: dict, truth: dict) -> float | None:
    """Mean over the rated players of (p - truth)^2."""
    if not probs:
        return None
    return sum((p - truth[n]) ** 2 for n, p in probs.items()) / len(probs)


def log_score(probs: dict, truth: dict) -> float | None:
    """Mean negative log likelihood, probabilities clipped to [0.01, 0.99]. Lower is better."""
    if not probs:
        return None
    tot = 0.0
    for n, p in probs.items():
        p = min(CLIP[1], max(CLIP[0], p))
        tot += -math.log(p) if truth[n] else -math.log(1 - p)
    return tot / len(probs)


def argmax_set(d: dict, keys=None, tol: float = 1e-9) -> list:
    keys = list(d) if keys is None else [k for k in keys if k in d]
    if not keys:
        return []
    top = max(d[k] for k in keys)
    return [k for k in keys if d[k] >= top - tol]


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


# --------------------------------------------------------------------------- one game

class GameData:
    """One finished game's events plus the indexes every row builder needs."""

    def __init__(self, events: list[dict], batch: str = ""):
        self.events = events
        self.batch = batch
        self.start = next(e for e in events if e["type"] == "game_start")
        self.end = next((e for e in events if e["type"] == "game_end"), None)
        self.game_id = self.start.get("game_id")
        self.seed = self.start.get("seed")
        self.config = self.start.get("config") or {}
        g = self.config.get("game", {})
        self.dials = {"sabotage_target": g.get("sabotage_target"), "clean_target": g.get("clean_target"),
                      "num_moles": g.get("num_moles"), "discussion_passes": g.get("discussion_passes"),
                      "whisper_exchanges": g.get("whisper_exchanges"),
                      "whisper_pairs_max": g.get("whisper_pairs_max")}
        self.cast = {p["name"]: p for p in self.start["players"]}
        self.role = {n: p["role"] for n, p in self.cast.items()}
        self.model = {n: p["model"] for n, p in self.cast.items()}
        self.seat = {n: p["seat"] for n, p in self.cast.items()}
        self.moles = {n for n, r in self.role.items() if r == "mole"}
        self.truth = {n: 1.0 if r == "mole" else 0.0 for n, r in self.role.items()}
        self.by_seq = {e["seq"]: e for e in events}
        self.turns = [e for e in events if e["type"] == "turn"]
        self.rounds = sorted({e["round"] for e in events if e["type"] == "round_start"})

        def per_round(t):
            return {e["round"]: e for e in events if e["type"] == t}
        self.round_start = per_round("round_start")
        self.job_pick = per_round("job_pick")
        self.job_result = per_round("job_result")
        self.job_choices = per_round("job_choices")
        self.vote_result = per_round("vote_result")
        self.whisper_pairs = per_round("whisper_pairs")
        self.whisper_requests = per_round("whisper_requests")
        self.clue_events = [e for e in events if e["type"] == "clue"]
        self._cut = self._cutoffs()
        self._post_cache: dict = {}

    # ---- basic facts
    def alive_at_round(self, r: int) -> list[str]:
        return list(self.round_start[r]["alive"])

    def moles_alive_at_round(self, r: int) -> int:
        return sum(1 for n in self.alive_at_round(r) if n in self.moles)

    def turns_in(self, r: int | None = None, *phases, fallback: bool | None = None) -> list[dict]:
        out = []
        for t in self.turns:
            if r is not None and t["round"] != r:
                continue
            if phases and t.get("turn_phase") not in phases:
                continue
            if fallback is not None and bool(t.get("fallback")) != fallback:
                continue
            out.append(t)
        return out

    def statement_speaker(self) -> dict:
        """statement_id -> speaker, for every turn that carries one."""
        return {t["statement_id"]: t["player"] for t in self.turns if t.get("statement_id")}

    # ---- cutoffs
    def _cutoffs(self) -> dict:
        cut = {}
        first: dict = {}
        for t in self.turns:
            tp = t.get("turn_phase")
            if tp in SIMULTANEOUS:
                key = (t["round"], tp)
                first.setdefault(key, t["seq"])
                cut[t["seq"]] = first[key] - 1
            elif tp in SEQUENTIAL:
                cut[t["seq"]] = t["seq"] - 1
        # Whisper lockstep: with P pairs, the round's whisper turns come in steps of P turns.
        for r in self.rounds:
            ws = self.turns_in(r, "whisper")
            if not ws:
                continue
            pairs = (self.whisper_pairs.get(r) or {}).get("pairs") or []
            P = len(pairs)
            if P == 0 or len(ws) % P:
                raise ValueError(f"{self.game_id} round {r}: {len(ws)} whisper turns, {P} pairs")
            for i, t in enumerate(ws):
                step = i // P
                step_first = ws[step * P]["seq"]
                speaker_should = [a if step % 2 == 0 else b for a, b in pairs][i % P]
                if t["player"] != speaker_should:
                    raise ValueError(f"{self.game_id} seq {t['seq']}: whisper speaker {t['player']} "
                                     f"!= expected {speaker_should}")
                cut[t["seq"]] = step_first - 1
        return cut

    def cutoff(self, turn: dict) -> int:
        return self._cut[turn["seq"]]

    # ---- solver
    def solver_inputs(self, cutoff: int, viewpoint: str = "table") -> dict:
        return from_log(self.events, upto_seq=cutoff, viewpoint=viewpoint)

    def posterior(self, cutoff: int, viewpoint: str = "table"):
        key = (cutoff, viewpoint)
        if key not in self._post_cache:
            self._post_cache[key] = table_posterior(self.solver_inputs(cutoff, viewpoint))
        return self._post_cache[key]


def rebuild_ctx(g: GameData, turn: dict) -> dict:
    """Best-effort reconstruction of the engine's `ctx` for a turn (engine.base_ctx plus the phase
    extras), from the log alone. `ctx` itself is never logged."""
    tp, p, r = turn["turn_phase"], turn["player"], turn["round"]
    gcfg = g.config.get("game", {})
    endgame = tp in ("cut_pitch", "cut_vote", "finale_pitch", "finale_choice")
    if endgame:
        alive = list(g.end["survivors"]) if g.end else []
    else:
        alive = g.alive_at_round(r)
    # Game.team: [] from round_start until the pick is written; then this round's team.
    pick = g.job_pick.get(r)
    team = list(pick["team"]) if pick and pick["seq"] < turn["seq"] else []
    moles_alive = [n for n in alive if n in g.moles]
    seats = sorted(g.seat, key=g.seat.get)
    ctx = {"others": [n for n in alive if n != p], "alive": alive, "role": g.role[p],
           "moles_remaining": len(moles_alive), "leader": g.round_start[r]["leader"],
           "whispers": gcfg.get("whispers", True), "card_players": [n for n in seats if n != p],
           "on_team": p in team, "partners": [n for n in moles_alive if n != p] if g.role[p] == "mole" else []}
    if tp == "whisper":
        ws = g.turns_in(r, "whisper")
        pairs = g.whisper_pairs[r]["pairs"]
        step = ws.index(turn) // len(pairs)
        ctx.update(partner=turn["partner"], index=step // 2 + 1, total=gcfg.get("whisper_exchanges"))
    elif tp == "pick":
        n = len(alive)
        ctx.update(team_size=min(gcfg["job_size"] if n >= 5 else gcfg["job_size_small"], n),
                   job_name=pick["job_name"])
    elif tp == "job":
        rs = g.round_start[r]
        ctx.update(team=team, job_name=pick["job_name"], blown_jobs=rs["blown_jobs"], clean_jobs=rs["clean_jobs"])
    elif tp == "discuss":
        order = [t["player"] for t in g.turns_in(r, "discuss") if t.get("pass") == 1]
        k = [t["seq"] for t in g.turns_in(r, "discuss")].index(turn["seq"]) + 1
        chal = [e["statement_id"] for e in g.events[:turn["seq"]]
                if e["type"] == "turn" and e["round"] == r and e.get("statement_id")
                and e["phase"] in ("pick", "discuss", "vote") and e["player"] != p]
        passes = gcfg.get("discussion_passes", 2)
        ctx.update(order=order, challengeable=chal, passes=passes, _n=f"{k}/{passes * len(order)} ")
        ctx["pass"] = turn.get("pass")
    elif tp in ("cut_pitch", "cut_vote"):
        side = "crew" if (g.end or {}).get("winner") == "crew" else "mole"
        surv = [n for n in alive if g.role[n] == side]
        ctx.update(survivors=surv, others=[n for n in surv if n != p])
    elif tp in ("finale_pitch", "finale_choice"):
        fr = next(e for e in g.events if e["type"] == "finale_result")
        opp = next(n for n in fr["finalists"] if n != p)
        ctx.update(opponent=opp)
        if tp == "finale_pitch":
            mine = [t["seq"] for t in g.turns_in(None, "finale_pitch") if t["player"] == p]
            ctx.update(index=mine.index(turn["seq"]) + 1, total=gcfg.get("finale_exchanges", 1))
    return dict(ctx, self=p)


def rebuild_prompt(g: GameData, turn: dict) -> tuple[str, str, dict]:
    """(system prompt, first-attempt turn prompt, schema) rebuilt with the CURRENT inside_job code
    from the log up to the turn's cutoff. Exact only if prompts.py / schemas.py / config.py are the
    versions that played the game, which the log cannot prove."""
    from inside_job.config import config_from_dict
    from inside_job.prompts import player_system_prompt, turn_prompt
    from inside_job.schemas import turn_schema
    cfg = config_from_dict(g.config)
    ctx = rebuild_ctx(g, turn)
    setup = [e for e in g.events if e["phase"] == "setup"]
    system = player_system_prompt(setup, turn["player"], cfg)
    upto = [e for e in g.events if e["seq"] <= g.cutoff(turn)]
    prompt = turn_prompt(upto, turn["player"], cfg, turn["turn_phase"], ctx)
    return system, prompt, turn_schema(turn["turn_phase"], ctx)


def mock_rebuild_check(seeds=(1, 2), config_path=None) -> dict:
    """Play mock games in memory (MockLLM: no model calls, no files) and check that `rebuild_prompt`
    reproduces every prompt, system prompt and schema the client actually received."""
    from inside_job.config import load_config
    from inside_job.engine import Game
    from inside_job.llm import MockLLM
    cfg = load_config(config_path or ROOT / "config" / "pilot.toml")
    from inside_job.config import config_from_dict
    from inside_job.prompts import turn_prompt
    out = {"turns": 0, "prompt": 0, "system": 0, "schema": 0, "naive": {}}
    for seed in seeds:
        llm = MockLLM(seed)
        game = Game(cfg, llm, seed, game_id=f"mock-s{seed}", clock=lambda: "")
        game.run()
        g = GameData(game.log.events, "mock")
        calls: dict = {}
        for c in llm.calls:
            if c["player"] is not None:
                calls.setdefault((c["player"], c["phase"]), []).append(c)
        for t in g.turns:
            s, p, sch = rebuild_prompt(g, t)
            cs = calls[(t["player"], t["turn_phase"])]
            out["turns"] += 1
            out["prompt"] += any(c["prompt"] == p for c in cs)
            out["system"] += any(c["system"] == s for c in cs)
            out["schema"] += any(c["schema"] == sch and c["prompt"] == p for c in cs)
            if g.cutoff(t) != t["seq"] - 1:
                # Naive cutoff (seq-1) for a turn that is not the first of its simultaneous phase / step:
                # does it give a prompt that was never sent?
                naive = turn_prompt([e for e in g.events if e["seq"] <= t["seq"] - 1], t["player"],
                                    config_from_dict(g.config), t["turn_phase"], rebuild_ctx(g, t))
                k = out["naive"].setdefault(t["turn_phase"], [0, 0])
                k[0] += not any(c["prompt"] == naive for c in cs)
                k[1] += 1
    return out


def attempt_rebuild(games: list[GameData]) -> str:
    """Rebuild every pilot turn's first-attempt prompt with the current code, and say what can and
    cannot be checked."""
    import json
    mock = mock_rebuild_check(seeds=(1, 2, 3, 4))
    n_ok, n_fail, err = 0, 0, ""
    per_model: dict = {}
    example = None
    for g in games:
        for t in g.turns:
            try:
                s, p, sch = rebuild_prompt(g, t)
            except Exception as e:  # noqa: BLE001
                n_fail += 1
                err = err or f"{g.game_id} seq {t['seq']}: {e!r}"
                continue
            n_ok += 1
            if example is None and t["turn_phase"] == "vote":
                example = (g, t, len(s), len(p), len(json.dumps(sch, separators=(",", ":"))))
            if (t.get("attempts") or 1) == 1:
                u = t.get("usage") or {}
                tok = u.get("input", 0) + u.get("cache_creation", 0) + u.get("cache_read", 0)
                chars = len(s) + len(p) + len(json.dumps(sch, separators=(",", ":")))
                per_model.setdefault(t["model"], []).append((chars, tok))
    lines = []
    if example:
        g, t, ls, lp, lsch = example
        lines.append(f"Rebuilt with `analysis/common.rebuild_prompt` (current `prompts.py`, the log up to the "
                     f"turn's cutoff, and a reconstructed `ctx`): every one of {n_ok} turns rebuilt without error"
                     + (f"; {n_fail} failed ({err})" if n_fail else "") + f". Example: seed {g.seed} seq {t['seq']} "
                     f"({t['player']}, vote): system prompt {ls} chars, turn prompt {lp} chars, schema {lsch} chars.")
    lines.append(f"Check of the method on {mock['turns']} turns of four in-memory mock games (`MockLLM` records the "
                 f"exact text it was sent): turn prompt identical {mock['prompt']}/{mock['turns']}, system prompt "
                 f"{mock['system']}/{mock['turns']}, schema {mock['schema']}/{mock['turns']}. With a naive cutoff of "
                 "seq-1 instead, for turns that are not the first of their simultaneous phase or whisper step, the "
                 "rebuilt prompt differs from the one sent in: "
                 + ", ".join(f"{ph} {a} of {b}" for ph, (a, b) in sorted(mock["naive"].items()))
                 + ". So the prompt text itself filters most same-phase turns; the first-turn cutoff still "
                 "matters for anything computed from `visible_events`, which does admit other players' public "
                 "vote turns and a partner's job turn as soon as they are logged.")
    corr = []
    for m, xs in sorted(per_model.items()):
        a = np.array(xs, float)
        r = float(np.corrcoef(a[:, 0], a[:, 1])[0, 1]) if len(a) > 2 else float("nan")
        ratio = a[:, 1] / a[:, 0]
        corr.append(f"`{m}` r={r:.3f}, tokens/char median {np.median(ratio):.2f}, "
                    f"share of turns above 1.2 tokens/char {100 * (ratio > 1.2).mean():.0f}%")
    lines.append("Is an exact rebuild of a pilot turn possible? Only if the code that played the batch is the "
                 "code on disk now. Nothing in the log records a code version or prompt hash (`log_version` is 1, "
                 "`rules_version` 0.3), the repository has no commits, so the only evidence is file times "
                 "(prompts.py, schemas.py, engine.py, config.py were last modified before the first pilot1 game "
                 "started, 03:21 UTC), which is suggestive, not proof. Nothing logged can verify the text: the "
                 "prompt, system prompt and schema are never written, and the only quantity that depends on them, "
                 "`usage`, sums every `modelUsage` entry of the CLI reply (including the CLI's own helper call), "
                 "so it is not a prompt length. Rebuilt length (system + prompt + schema, chars) against logged "
                 "input + cache tokens, single-attempt turns: " + "; ".join(corr) + ". A tokens/char ratio about "
                 "twice the usual on a minority of turns (mostly claude-sonnet-5) is consistent with extra calls "
                 "inside the CLI (for example its internal structured-output retries) that the log does not record; "
                 "the raw stdout that would show this is not kept.")
    return "\n\n".join(lines)


def load_games(games_dir: str | Path, batch: str) -> tuple[list[GameData], object]:
    """The batch's finished games (read only; nothing is written to `games_dir`)."""
    b = load_batch(games_dir, batch)
    return [GameData(ev, batch) for ev in b.games], b


# --------------------------------------------------------------------------- bootstrap

class Boot:
    """95% percentile bootstrap over whole games. One fixed resample matrix is shared by every
    statistic, so intervals are comparable. Statistics are pooled means over decisions (sum of
    values / number of decisions in the resampled games)."""

    def __init__(self, game_ids, n: int = 2000, seed: int = 20261110, min_games: int = 5):
        self.game_ids = list(dict.fromkeys(game_ids))
        self.pos = {g: i for i, g in enumerate(self.game_ids)}
        self.n = n
        self.min_games = min_games
        rng = np.random.default_rng(seed)
        G = len(self.game_ids)
        self.idx = rng.integers(0, G, size=(n, G)) if G else np.zeros((n, 0), dtype=int)

    def mean(self, pairs) -> dict:
        """`pairs` = iterable of (game_id, value); None values are skipped."""
        G = len(self.game_ids)
        S = np.zeros(G)
        N = np.zeros(G)
        for gid, v in pairs:
            if v is None:
                continue
            i = self.pos[gid]
            S[i] += float(v)
            N[i] += 1
        n = int(N.sum())
        games = int((N > 0).sum())
        out = {"value": (S.sum() / n) if n else None, "n": n, "games": games, "lo": None, "hi": None}
        if n and games >= self.min_games:
            num = S[self.idx].sum(axis=1)
            den = N[self.idx].sum(axis=1)
            with np.errstate(invalid="ignore", divide="ignore"):
                vals = np.where(den > 0, num / np.where(den > 0, den, 1), np.nan)
            vals = vals[~np.isnan(vals)]
            if len(vals):
                out["lo"], out["hi"] = float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))
        return out


def fmt_stat(s: dict, digits: int = 3, pct: bool = False) -> str:
    """`0.162 [0.140, 0.185]`, or `0.162 (too few)` under 5 games, or `-` with no data."""
    if s["value"] is None:
        return "-"

    def f(x):
        return f"{100 * x:.0f}%" if pct else f"{x:.{digits}f}"
    if s["lo"] is None:
        return f"{f(s['value'])} (too few)"
    return f"{f(s['value'])} [{f(s['lo'])}, {f(s['hi'])}]"
