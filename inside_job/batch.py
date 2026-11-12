"""`batch`: play many seeds in one process, with resume, parallel games and a stop rule (SPEC
section 2, "batch").

All games run as coroutines on **one** asyncio event loop (no threads, no child `python`
processes). A pool of `parallel_games` workers takes seeds in order; each game gets its own model
client, and a `ClaudeCLI` client bounds its own calls with its own `max_parallel_calls`
semaphore, so at most `parallel_games * max_parallel_calls` calls are in flight at once. Every
game's randomness comes from its own seeded streams (and `MockLLM` replies from their inputs), so
the result of a game does not depend on how many games run beside it.
"""

from __future__ import annotations

import asyncio
import json
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .engine import Game, make_game_id
from .rawlog import RawLog
from .results import append_index, billed_split
from .transcript import render


def new_game_id(out: Path, seed: int) -> str:
    """`g-YYYYMMDD-HHMMSS-s<seed>`, with `-2`, `-3`, ... if that log already exists in `out`."""
    base = make_game_id(seed)
    game_id, n = base, 1
    while (out / f"{game_id}.jsonl").exists():
        n += 1
        game_id = f"{base}-{n}"
    return game_id


def save_game(game: Game, out: Path, log_path: Path, spoiled: bool = False) -> tuple[Path, dict]:
    """Write the Markdown transcript and append the index row of a finished game."""
    events = game.log.events
    md_path = out / f"{game.game_id}.md"
    md_path.write_text(render(events), encoding="utf-8")
    raw = game.raw.final_path if game.raw is not None else None
    row = append_index(events, str(log_path), out / "index.jsonl", spoiled=spoiled, raw=raw)
    return md_path, row


def read_index(index_path: Path) -> list[dict]:
    rows = []
    if not index_path.exists():
        return rows
    with open(index_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue                                # a torn line is not a finished game
            if isinstance(row, dict):
                rows.append(row)
    return rows


def finished_seeds(index_path: Path, name: str) -> set[int]:
    """Seeds with a finished, unspoiled game of this batch in the index.

    An index row is only written after `game_end`, so a game cut off mid-way never counts."""
    return {r["seed"] for r in read_index(index_path)
            if r.get("batch") == name and not r.get("spoiled") and isinstance(r.get("seed"), int)}


def fallback_share(end: dict) -> float:
    calls = end.get("calls") or 0
    return (end.get("fallbacks") or 0) / calls if calls else 0.0


@dataclass
class GameSummary:
    seed: int
    game_id: str
    winner: str
    reason: str
    rounds: int
    calls: int
    blocked: int
    fallbacks: int
    wall_s: float
    cost_usd: float
    spoiled: bool
    log: str
    billed_usd: float = 0.0        # OpenRouter models: real money (docs/OPENROUTER.md)
    notional_usd: float = 0.0      # Claude models: the CLI's list-price equivalent, not billed

    @classmethod
    def from_end(cls, seed: int, game_id: str, end: dict, spoiled: bool, log: str) -> "GameSummary":
        billed, notional = billed_split(end["usage"]["by_model"])
        return cls(seed, game_id, end["winner"], end["reason"], end["rounds"], end["calls"],
                   end.get("blocked", 0), end["fallbacks"], end["wall_s"],
                   end["usage"]["total"].get("cost_usd", 0.0), spoiled, log, billed, notional)


@dataclass
class BatchState:
    """What the batch has done so far (readable after an interrupt)."""
    pending: list[int]
    done: list[GameSummary] = field(default_factory=list)
    running: dict[int, str] = field(default_factory=dict)      # seed -> game id
    stop_reason: str | None = None
    errors: list[tuple[int, str]] = field(default_factory=list)
    cut: list[int] = field(default_factory=list)                # seeds stopped mid-game by the spend guard
    spend_stopped: bool = False

    @property
    def stopped(self) -> bool:
        return self.stop_reason is not None


async def run_batch(cfg, *, name: str, state: BatchState, parallel: int, out: Path,
                    client_for: Callable[[int], object], max_share: float,
                    on_start: Callable[[int, str], None] = lambda s, g: None,
                    on_end: Callable[[GameSummary, BatchState], None] = lambda g, s: None,
                    raw: bool = False, provenance: dict | None = None,
                    spend_stop: Callable[[], str | None] = lambda: None) -> BatchState:
    """Play `state.pending` seeds, at most `parallel` at once, on the running event loop.

    `raw` writes each game's raw sidecar file beside its log; `provenance` (`code_fingerprint()`)
    is stamped on every game_start (docs/RAWLOG.md).

    The OpenRouter spend guard (docs/OPENROUTER.md): a game whose client raises `SpendStop` is cut
    off where it stands, is not indexed (it is replayed on resume) and stops the batch; the other
    games in flight are cancelled. `spend_stop()` returning a reason also stops the batch before
    the next game starts."""
    from .openrouter import SpendStop
    out.mkdir(parents=True, exist_ok=True)
    tasks: dict[int, asyncio.Task] = {}

    def stop_for_spend(reason: str):
        state.spend_stopped = True
        if not state.stopped:
            state.stop_reason = reason
        for t in list(tasks.values()):
            if not t.done():
                t.cancel()

    def cut_off(seed: int, game: Game):
        game.log.close()
        state.running.pop(seed, None)
        state.cut.append(seed)

    async def worker():
        while state.pending and not state.stopped:
            reason = spend_stop()
            if reason:
                stop_for_spend(reason)
                break
            seed = state.pending.pop(0)
            game_id = new_game_id(out, seed)
            log_path = out / f"{game_id}.jsonl"
            # The log file is created here, before the next await, so ids cannot collide.
            game = Game(cfg, client_for(seed), seed, game_id=game_id, log_path=log_path, batch=name,
                        raw=RawLog(log_path) if raw else None, provenance=provenance)
            state.running[seed] = game_id
            on_start(seed, game_id)
            task = asyncio.ensure_future(game.play())
            tasks[seed] = task
            try:
                end = await task
            except SpendStop as e:
                cut_off(seed, game)
                stop_for_spend(str(e))
                continue
            except asyncio.CancelledError:
                cur = asyncio.current_task()
                if state.spend_stopped and not (cur is not None and cur.cancelling()):
                    cut_off(seed, game)                 # cancelled by the spend guard, not by Ctrl-C
                    continue
                raise
            except Exception as e:                      # a bug, not a model failure: stop the batch
                game.log.close()
                state.running.pop(seed, None)
                state.errors.append((seed, f"{type(e).__name__}: {e}"))
                if not state.stopped:
                    state.stop_reason = f"game {game_id} (seed {seed}) crashed: {type(e).__name__}: {e}"
                continue
            state.running.pop(seed, None)
            share = fallback_share(end)
            spoiled = share > max_share
            save_game(game, out, log_path, spoiled=spoiled)
            summary = GameSummary.from_end(seed, game_id, end, spoiled, str(log_path))
            state.done.append(summary)
            if spoiled and not state.stopped:
                state.stop_reason = (f"game {game_id} (seed {seed}) had {end['fallbacks']} fallbacks in "
                                     f"{end['calls']} calls ({share:.1%}, above the "
                                     f"{max_share:.1%} limit); it is marked spoiled and will be "
                                     "replayed on resume")
            on_end(summary, state)

    n = max(1, min(parallel, len(state.pending)))
    await asyncio.gather(*[worker() for _ in range(n)])
    return state


# --------------------------------------------------------------------------- reporting

def game_line(g: GameSummary, k: int, total: int) -> str:
    return (f"[{k}/{total}] seed {g.seed}  {g.game_id}  {g.winner} win ({g.reason})  {g.rounds} rounds  "
            f"calls {g.calls}  blocked {g.blocked}  fallbacks {g.fallbacks}  wall {g.wall_s:.1f}s  "
            f"cost ${g.cost_usd:.4f}" + _split(g.billed_usd, g.notional_usd) + ("  SPOILED" if g.spoiled else ""))


def _split(billed: float, notional: float) -> str:
    """` (billed $x, notional $y)` when any OpenRouter money was spent, else nothing (lines for
    all-Claude batches are unchanged)."""
    return f" (billed ${billed:.4f}, notional ${notional:.4f})" if billed else ""


def totals_line(done: list[GameSummary]) -> str:
    calls = sum(g.calls for g in done)
    fb = sum(g.fallbacks for g in done)
    crew = sum(1 for g in done if g.winner == "crew")
    spoiled = sum(1 for g in done if g.spoiled)
    return (f"  totals: {len(done)} games ({spoiled} spoiled)  crew {crew} / moles {len(done) - crew}  "
            f"calls {calls}  blocked {sum(g.blocked for g in done)}  fallbacks {fb}"
            f" ({(fb / calls if calls else 0):.1%})  game wall {sum(g.wall_s for g in done):.1f}s  "
            f"cost ${sum(g.cost_usd for g in done):.4f}"
            + _split(sum(g.billed_usd for g in done), sum(g.notional_usd for g in done)))


def summary_table(done: list[GameSummary]) -> str:
    hdr = ("seed", "game_id", "winner", "reason", "rounds", "calls", "blocked", "fallbacks", "wall_s",
           "cost_usd", "spoiled")
    rows = [(g.seed, g.game_id, g.winner, g.reason, g.rounds, g.calls, g.blocked, g.fallbacks,
             f"{g.wall_s:.1f}", f"{g.cost_usd:.4f}", "yes" if g.spoiled else "")
            for g in sorted(done, key=lambda g: g.seed)]
    calls = sum(g.calls for g in done)
    rows.append(("TOTAL", f"{len(done)} games", "", "", sum(g.rounds for g in done), calls,
                 sum(g.blocked for g in done), sum(g.fallbacks for g in done),
                 f"{sum(g.wall_s for g in done):.1f}", f"{sum(g.cost_usd for g in done):.4f}",
                 str(sum(1 for g in done if g.spoiled) or "")))
    widths = [max(len(str(x)) for x in col) for col in zip(hdr, *rows)]
    fmt = lambda row: "  ".join(str(v).ljust(w) if i <= 3 else str(v).rjust(w)
                                for i, (v, w) in enumerate(zip(row, widths))).rstrip()
    return "\n".join([fmt(hdr), fmt(["-" * w for w in widths])] + [fmt(r) for r in rows])


def resume_command(args) -> str:
    """The command that resumes this batch: the same command (finished seeds are skipped)."""
    argv = ["python3.11", "-m", "inside_job", "batch", "--config", args.config, "--name", args.name,
            "--games", str(args.games), "--seed", str(args.seed),
            "--parallel-games", str(args.parallel_games), "--out", args.out,
            "--max-fallback-share", f"{args.max_fallback_share:g}"]
    if getattr(args, "budget_usd", None) is not None:
        argv += ["--budget-usd", f"{args.budget_usd:g}"]
    for flag, on in (("--mock", args.mock), ("--no-preflight", args.no_preflight), ("--force", args.force),
                     ("--no-raw", getattr(args, "no_raw", False))):
        if on:
            argv.append(flag)
    return shlex.join(argv)
