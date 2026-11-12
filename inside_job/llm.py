"""Model clients: the `claude -p` CLI client, a mock, and usage accounting.

Model calls go only through `claude -p` on the user's subscription. No API, no keys.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import sys
import tempfile
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

USAGE_KEYS = ("input", "output", "cache_read", "cache_creation", "thinking", "cost_usd")
_MODEL_USAGE_MAP = {
    "inputTokens": "input",
    "outputTokens": "output",
    "cacheReadInputTokens": "cache_read",
    "cacheCreationInputTokens": "cache_creation",
    "thinkingTokens": "thinking",
    "costUSD": "cost_usd",
}


def zero_usage() -> dict:
    return {k: (0.0 if k == "cost_usd" else 0) for k in USAGE_KEYS}


def add_usage(a: dict, b: dict) -> dict:
    out = zero_usage()
    for k in USAGE_KEYS:
        out[k] = (a or {}).get(k, 0) + (b or {}).get(k, 0)
    out["cost_usd"] = round(out["cost_usd"], 6)
    return out


@dataclass
class LLMReply:
    data: dict | None          # parsed structured output
    raw_text: str
    served_model: str | None   # the requested model if modelUsage lists it, else its biggest entry
    usage: dict = field(default_factory=zero_usage)
    latency_s: float = 0.0
    error: str | None = None
    error_kind: str | None = None   # blocked | timeout | cli (the engine adds invalid); None if ok
    # For the raw sidecar log only (docs/RAWLOG.md); never read by the engine, prompts or reports.
    raw_stdout: str = ""            # the CLI's complete stdout ("" on a timeout or spawn failure)
    stderr_tail: str = ""           # the last 2,000 characters of its stderr
    returncode: int | None = None   # the CLI's exit code (None if it never exited normally)


# Failure kinds (SPEC section 4). `invalid` is set by the engine when a reply fails validation.
ERROR_KINDS = ("blocked", "timeout", "cli", "invalid")
BLOCKED_MARK = "safeguards flagged"


def is_blocked_text(text: str | None) -> bool:
    return bool(text) and BLOCKED_MARK in text.lower()


class LLM(Protocol):
    """`view` is only passed to clients that set `wants_view = True` (the scripted bots): the
    player's projected visible events. `needs_prompt = False` tells the engine it may skip
    building prompt text. The CLI and mock clients never receive a view."""
    async def call(self, *, model: str, system: str, prompt: str, schema: dict,
                   phase: str | None = None, player: str | None = None, view=None) -> LLMReply: ...


# --------------------------------------------------------------------------- CLI client

def build_argv(model: str, system: str, prompt: str, schema: dict, claude_bin: str = "claude",
               effort: str = "") -> list[str]:
    """The exact `claude -p` invocation from SPEC section 4 (`--effort` right after `-p` if set)."""
    return [
        claude_bin, "-p",
        *(["--effort", effort] if effort else []),
        "--model", model,
        "--system-prompt", system,
        "--tools", "",
        "--strict-mcp-config",
        "--setting-sources", "",
        "--no-session-persistence",
        "--output-format", "json",
        "--json-schema", json.dumps(schema, separators=(",", ":")),
        prompt,
    ]


def build_env(base: dict | None = None, max_thinking_tokens: int = -1) -> dict:
    """The child environment: no CLAUDECODE, and MAX_THINKING_TOKENS exactly as configured.

    -1 removes any inherited MAX_THINKING_TOKENS, so the parent shell cannot change a game.
    """
    env = dict(os.environ if base is None else base)
    env.pop("CLAUDECODE", None)
    env.pop("MAX_THINKING_TOKENS", None)
    if max_thinking_tokens >= 0:
        env["MAX_THINKING_TOKENS"] = str(int(max_thinking_tokens))
    return env


def parse_usage(model_usage: dict | None) -> dict:
    usage = zero_usage()
    for _served, mu in (model_usage or {}).items():
        if not isinstance(mu, dict):
            continue
        for src, dst in _MODEL_USAGE_MAP.items():
            v = mu.get(src) or 0
            usage[dst] += v
    usage["cost_usd"] = round(usage["cost_usd"], 6)
    return usage


STDERR_TAIL_CHARS = 2000


def parse_cli_output(stdout: str, returncode: int, stderr: str = "", requested: str | None = None) -> LLMReply:
    """Turn the CLI's JSON stdout into an LLMReply (latency filled in by the caller).

    The reply also carries the complete stdout, the stderr tail and the exit code, for the raw
    sidecar log; the error text stays cut to about 300 characters as before."""
    reply = _parse_cli_output(stdout, returncode, stderr, requested)
    reply.raw_stdout = stdout or ""
    reply.stderr_tail = (stderr or "")[-STDERR_TAIL_CHARS:]
    reply.returncode = returncode
    return reply


def _parse_cli_output(stdout: str, returncode: int, stderr: str, requested: str | None) -> LLMReply:
    """The parsing behind `parse_cli_output`.

    `modelUsage` can hold more than one model: the CLI may make a small helper call of its own
    (seen: a `claude-haiku-5-5` entry listed first on every call). The served model is the
    requested one when it is among the keys; otherwise the key with the most output tokens."""
    raw = stdout or ""
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        err = f"exit {returncode}: stdout is not JSON"
        tail = (stderr or raw or "").strip()[-300:]
        if tail:
            err += f" ({tail})"
        kind = "blocked" if is_blocked_text(raw) or is_blocked_text(stderr) else "cli"
        return LLMReply(None, raw, None, zero_usage(), 0.0, err, kind)
    if not isinstance(obj, dict):
        return LLMReply(None, raw, None, zero_usage(), 0.0, f"exit {returncode}: unexpected JSON", "cli")

    model_usage = obj.get("modelUsage") or {}
    served = None
    if isinstance(model_usage, dict) and model_usage:
        if requested in model_usage:
            served = requested
        else:
            served = max(model_usage, key=lambda k: (model_usage[k] or {}).get("outputTokens", 0)
                         if isinstance(model_usage[k], dict) else 0)
    usage = parse_usage(model_usage if isinstance(model_usage, dict) else {})
    result_text = obj.get("result")
    raw_text = result_text if isinstance(result_text, str) else raw

    error = None
    kind = None
    data = None
    if obj.get("is_error"):
        # Say why: the subtype (e.g. error_max_structured_output_retries) and the first error.
        errors = obj.get("errors")
        errors = [str(e) for e in errors] if isinstance(errors, list) else ([str(errors)] if errors else [])
        error = f"is_error: {str(result_text)[:300]}"
        if obj.get("subtype"):
            error += f" (subtype {obj['subtype']})"
        if errors:
            error += f": {errors[0][:300]}"
        blocked = is_blocked_text(str(result_text)) or any(is_blocked_text(e) for e in errors)
        kind = "blocked" if blocked else "cli"
    elif returncode != 0:
        error = f"exit {returncode}: {(stderr or '').strip()[-300:]}"
        kind = "blocked" if is_blocked_text(stderr) else "cli"
    else:
        so = obj.get("structured_output")
        if isinstance(so, dict):
            data = so
        elif isinstance(result_text, str):
            try:
                parsed = json.loads(result_text)
                if isinstance(parsed, dict):
                    data = parsed
                else:
                    error = "result JSON is not an object"
            except (json.JSONDecodeError, ValueError):
                error = "no structured_output and result is not JSON"
        else:
            error = "no structured_output and no result"
        if error:
            kind = "cli"
    return LLMReply(data, raw_text, served, usage, 0.0, error, kind)


class ClaudeCLI:
    """Calls `claude -p` as a subprocess. Concurrency is bounded process-wide."""

    def __init__(self, max_parallel_calls: int = 4, timeout_s: float = 240, claude_bin: str = "claude",
                 exec_fn: Callable | None = None, max_thinking_tokens: int = -1, effort: str = ""):
        self.max_parallel_calls = max_parallel_calls
        self.max_thinking_tokens = max_thinking_tokens
        self.effort = effort
        self.timeout_s = timeout_s
        self.claude_bin = claude_bin
        self._exec = exec_fn or asyncio.create_subprocess_exec
        self._cwd = tempfile.mkdtemp(prefix="inside-job-call-")
        self._warned: set = set()
        self._sem: asyncio.Semaphore | None = None
        self._sem_loop = None

    def _semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        if self._sem is None or self._sem_loop is not loop:
            self._sem = asyncio.Semaphore(self.max_parallel_calls)
            self._sem_loop = loop
        return self._sem

    @classmethod
    def from_config(cls, cfg, **kw) -> "ClaudeCLI":
        lim = cfg.limits
        return cls(lim.max_parallel_calls, lim.call_timeout_s, max_thinking_tokens=lim.max_thinking_tokens,
                   effort=lim.effort, **kw)

    async def call(self, *, model: str, system: str, prompt: str, schema: dict,
                   phase: str | None = None, player: str | None = None, view=None) -> LLMReply:
        argv = build_argv(model, system, prompt, schema, self.claude_bin, self.effort)
        async with self._semaphore():
            t0 = time.monotonic()
            try:
                proc = await self._exec(
                    *argv,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=build_env(max_thinking_tokens=self.max_thinking_tokens),
                    cwd=self._cwd,
                )
            except (OSError, ValueError) as e:
                return LLMReply(None, "", None, zero_usage(), time.monotonic() - t0, f"spawn failed: {e}", "cli")
            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout=self.timeout_s)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=10)
                except (asyncio.TimeoutError, Exception):
                    pass
                return LLMReply(None, "", None, zero_usage(), time.monotonic() - t0,
                                f"timeout after {self.timeout_s}s", "timeout")
            except asyncio.CancelledError:              # Ctrl-C / batch stop: do not leave the child running
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                raise
            latency = time.monotonic() - t0
        reply = parse_cli_output(out.decode("utf-8", "replace"), proc.returncode,
                                 err.decode("utf-8", "replace"), requested=model)
        reply.latency_s = round(latency, 3)
        if reply.served_model and reply.served_model != model:
            key = (model, reply.served_model)
            if key not in self._warned:
                self._warned.add(key)
                print(f"warning: requested {model} but served {reply.served_model}", file=sys.stderr)
        return reply


# --------------------------------------------------------------------------- mock

_WORDS = ("vault", "alarm", "ledger", "lobby", "camera", "guard", "keycard", "van", "safe", "rooftop",
          "shadow", "signal", "alibi", "blueprint", "crowbar", "tunnel", "glove", "drill", "badge", "map")


def random_valid(schema: dict, rng: random.Random, _key: str = "") -> object:
    """A random value that satisfies the given (subset of) JSON schema."""
    if "enum" in schema:
        return rng.choice(schema["enum"])
    if "const" in schema:
        return schema["const"]
    t = schema.get("type")
    if t == "object":
        props = schema.get("properties", {})
        if set(props) == {"kind", "players", "k"} and "enum" in props["kind"]:
            return _random_card(props, rng)
        return {k: random_valid(v, rng, k) for k, v in props.items()}
    if t == "array":
        lo = schema.get("minItems", 0)
        hi = schema.get("maxItems", max(lo, 2))
        n = rng.randint(lo, max(lo, hi))
        items = schema.get("items", {"type": "string"})
        if schema.get("uniqueItems") and "enum" in items:
            pool = list(items["enum"])
            n = min(n, len(pool))
            return rng.sample(pool, n)
        out = []
        for _ in range(n):
            v = random_valid(items, rng, _key)
            if schema.get("uniqueItems") and v in out:
                continue
            out.append(v)
        return out
    if t == "string":
        if schema.get("maxLength") == 0:
            return ""
        n = rng.randint(3, 10)
        return " ".join(rng.choice(_WORDS) for _ in range(n))
    if t == "boolean":
        return rng.random() < 0.7
    if t == "integer":
        return rng.randint(schema.get("minimum", 0), schema.get("maximum", 10))
    if t == "number":
        return rng.uniform(schema.get("minimum", 0), schema.get("maximum", 1))
    return None


def _random_card(props: dict, rng: random.Random) -> dict:
    """A well-formed clue card (the right number of players for its kind)."""
    from .clues import CARD_ARITY
    pool = list(props["players"]["items"]["enum"])
    kinds = [k for k in props["kind"]["enum"] if CARD_ARITY.get(k, 99) <= len(pool)]
    kind = rng.choice(kinds)
    return {"kind": kind, "players": rng.sample(pool, CARD_ARITY[kind]), "k": rng.randint(0, 2)}


Policy = Callable[[str, str, str, dict, "str | None", "str | None"], "dict | None"]


class MockLLM:
    """Deterministic fake model. Replies are random but valid for the schema it is given, so they
    are in the wire format (the move under `move`), like a real model's.

    Each reply's randomness is derived from (seed, model, system, prompt), so the
    order in which concurrent calls complete never changes the replies.
    """

    def __init__(self, seed: int = 0, policy: Policy | None = None):
        self.seed = seed
        self.policy = policy
        self.calls: list[dict] = []

    def rng_for(self, model: str, system: str, prompt: str) -> random.Random:
        h = hashlib.sha256(f"{self.seed}\x00{model}\x00{system}\x00{prompt}".encode()).hexdigest()
        return random.Random(int(h[:16], 16))

    async def call(self, *, model: str, system: str, prompt: str, schema: dict,
                   phase: str | None = None, player: str | None = None, view=None) -> LLMReply:
        self.calls.append({"model": model, "system": system, "prompt": prompt, "schema": schema,
                           "phase": phase, "player": player})
        data = None
        if self.policy is not None:
            data = self.policy(model, system, prompt, schema, phase, player)
        if data is None:
            data = random_valid(schema, self.rng_for(model, system, prompt))
        if isinstance(data, LLMReply):
            return data
        text = json.dumps(data)
        return LLMReply(data=data, raw_text=text, served_model=model,
                        usage=zero_usage(), latency_s=0.0, error=None, raw_stdout=text)
