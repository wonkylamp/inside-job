"""Preflight (SPEC section 4, "Preflight"): before a real game, send two real calls, a mole
discussion turn and a vote turn, to every distinct model in the cast and to the narrator model, so
a model whose safety filter blocks game turns, or that errors (for example on one phase's schema),
stops the run before tokens are spent. A model passes only if both calls pass.

OpenRouter models (ids with a "/") are checked the same way through the routed client; their cost
counts toward the run's spend budget, and a model whose spend cannot be tracked fails here
(docs/OPENROUTER.md).

The calls are taken from a mock game played in memory with the same config (same cast, same
codenames), so they are genuine turns: system prompt, turn prompt and schema. Nothing is reworded.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .engine import Game
from .llm import MockLLM

PREFLIGHT_PHASES = ("discuss", "vote")


@dataclass
class ModelCheck:
    model: str
    status: str            # ok | blocked | error
    attempts: int
    latency_s: float
    output: int
    thinking: int
    detail: str = ""
    phase: str = "discuss"


def sample_calls(cfg, seed: int = 1) -> dict:
    """A mole discussion call and a vote call (system, prompt, schema) from one mock game with
    this config, as {phase: call}."""
    for s in range(seed, seed + 50):
        mock = MockLLM(s)
        game = Game(cfg, mock, s, game_id="preflight")
        game.run()
        moles = {p.name for p in game.players if p.role == "mole"}
        discuss = next((c for c in mock.calls if c["phase"] == "discuss" and c["player"] in moles), None)
        vote = next((c for c in mock.calls if c["phase"] == "vote"), None)
        if discuss and vote:
            return {"discuss": discuss, "vote": vote}
    raise RuntimeError("no mole discussion turn and vote turn in 50 mock games")


async def _check(client, model: str, call: dict, phase: str = "discuss") -> ModelCheck:
    attempts, latency, out, think = 0, 0.0, 0, 0
    status, detail = "error", ""
    from .openrouter import SpendStop
    for _ in range(2):                    # a blocked or erroring model is tried once more, unchanged
        attempts += 1
        try:
            reply = await client.call(model=model, system=call["system"], prompt=call["prompt"],
                                      schema=call["schema"], phase=phase, player=None)
        except SpendStop as e:            # budget reached, spend untrackable or key refused: no call made
            status, detail = "error", f"not sent: {e}"
            break
        latency += reply.latency_s or 0.0
        out += reply.usage.get("output", 0)
        think += reply.usage.get("thinking", 0)
        if not reply.error:
            status, detail = "ok", ""
            break
        status = "blocked" if reply.error_kind == "blocked" else "error"
        detail = reply.error or ""
    return ModelCheck(model, status, attempts, round(latency, 2), out, think, detail[:200], phase)


def run_preflight(cfg, client) -> list[ModelCheck]:
    """One check per (model, phase), in model order then phase order."""
    calls = sample_calls(cfg)
    models = list(dict.fromkeys([p.model for p in cfg.players] + [cfg.narrator.model]))

    async def all_checks():
        return await asyncio.gather(*[_check(client, m, calls[ph], ph)
                                      for m in models for ph in PREFLIGHT_PHASES])
    return list(asyncio.run(all_checks()))


def format_checks(checks: list[ModelCheck]) -> str:
    lines = [f"{'model':<22} {'phase':<8} {'status':<8} {'tries':>5} {'latency_s':>9} {'output':>7} {'thinking':>8}"]
    for c in checks:
        lines.append(f"{c.model:<22} {c.phase:<8} {c.status:<8} {c.attempts:>5} {c.latency_s:>9.1f} {c.output:>7} "
                     f"{c.thinking:>8}" + (f"  {c.detail}" if c.detail else ""))
    return "\n".join(lines)


def failures(checks: list[ModelCheck]) -> list[ModelCheck]:
    """The failed checks; a model fails if any of its checks is here."""
    return [c for c in checks if c.status != "ok"]
