"""OpenRouter seats: the HTTPS client for other labs' models, the router, and the spend guard
(docs/OPENROUTER.md).

A model id with a "/" (`vendor/model`) is called through OpenRouter's chat/completions API with the
owner's key; an id without one is a Claude model and goes through `claude -p` exactly as before
(`llm.ClaudeCLI`, unchanged). A config whose cast and narrator are all Claude ids builds a plain
`ClaudeCLI`, as it always has.

The key is read from the environment variable `OPENROUTER_API_KEY` at call time and goes only
into the `Authorization` header. It is never printed, logged, put in an error text or written to a
file; response bodies are scrubbed of it before they are kept.

Standard library only: `urllib.request` run in a worker thread.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import hashlib
import inspect
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Callable

from .config import DEFAULT_OUTPUT_CEILING, is_openrouter_model
from .llm import ClaudeCLI, LLMReply, zero_usage

API_URL = "https://openrouter.ai/api/v1/chat/completions"
KEY_ENV = "OPENROUTER_API_KEY"
SCHEMA_NAME = "inside_job_reply"
HTTP_RETRIES = 2                      # extra tries after a 429 / 5xx / network error, inside one call
BACKOFF_S = (2.0, 8.0)
ERROR_CHARS = 300
# JSON-schema keywords sent on the wire. Everything else (today only `uniqueItems`) is dropped from
# the wire copy; the engine still validates every reply against the full schema.
WIRE_KEYWORDS = ("type", "properties", "required", "additionalProperties", "items", "enum", "description",
                 "minimum", "maximum", "minItems", "maxItems")
# `max_thinking_tokens = 0`: reasoning off, else the lowest effort the model accepts.
REASONING_OFF_CHAIN = ("none", "minimal", "low")
# native_finish_reason values (lower case) that mean the provider's safety layer stopped the reply.
BLOCK_FINISH = {"content_filter", "refusal", "safety", "prohibited_content", "blocklist", "spii",
                "recitation", "image_safety"}
_KEY_SHAPE = re.compile(r"sk-or-[A-Za-z0-9_-]{8,}")
# What the engine appends to a turn's prompt on a retry (engine.Game.ask). The text before it is the
# turn's own prompt, so a retry is matched to the length failure earlier in the same turn.
RETRY_MARK = "\n\nYour previous reply was rejected: "
TURN_MEMORY = 256                     # turns with a pending length failure remembered at once


class SpendStop(Exception):
    """No more paid requests: the budget is reached, spend cannot be tracked, or OpenRouter refused
    the key / account. Raised by the client instead of returning a reply, so the engine does not
    finish the game with fallback moves; `batch` and `run` stop the game and do not index it."""


# --------------------------------------------------------------------------- spend ledger

class SpendLedger:
    """Billed OpenRouter spend in this process, shared by every game (thread-safe).

    `check()` raises SpendStop once spend has reached the budget or the ledger was halted for
    another reason. A call already in flight when the budget is reached is still paid for, so spend
    can pass the budget by at most the cost of the calls in flight at that moment."""

    def __init__(self, budget_usd: float | None = None):
        self.budget_usd = budget_usd
        self.billed_usd = 0.0
        self.by_model: dict[str, float] = {}
        self.calls = 0
        self.stop_reason: str | None = None
        self._lock = threading.Lock()

    @property
    def stopped(self) -> bool:
        return self.stop_reason is not None

    def check(self) -> None:
        with self._lock:
            if self.stop_reason is None and self.budget_usd is None:
                self.stop_reason = "no OpenRouter budget is set ([openrouter] budget_usd or --budget-usd)"
            if self.stop_reason is not None:
                raise SpendStop(self.stop_reason)

    def add(self, model: str, cost: float) -> None:
        with self._lock:
            self.calls += 1
            self.billed_usd = round(self.billed_usd + cost, 8)
            self.by_model[model] = round(self.by_model.get(model, 0.0) + cost, 8)
            if (self.stop_reason is None and self.budget_usd is not None
                    and self.billed_usd >= self.budget_usd):
                self.stop_reason = (f"OpenRouter spend reached the budget: ${self.billed_usd:.4f} billed of "
                                    f"${self.budget_usd:.2f}; no more paid requests are sent")

    def halt(self, reason: str) -> None:
        with self._lock:
            if self.stop_reason is None:
                self.stop_reason = reason


_LEDGER: SpendLedger | None = None


def start_ledger(budget_usd: float | None) -> SpendLedger:
    """A fresh process-wide ledger (each `run`, `trial`, `batch` or `preflight` command starts one;
    the preflight's spend counts toward the same budget as the games that follow it)."""
    global _LEDGER
    _LEDGER = SpendLedger(budget_usd)
    return _LEDGER


def process_ledger(budget_usd: float | None = None) -> SpendLedger:
    global _LEDGER
    if _LEDGER is None:
        _LEDGER = SpendLedger(budget_usd)
    return _LEDGER


# --------------------------------------------------------------------------- request

def wire_schema(schema):
    """The schema as sent to OpenRouter: only `WIRE_KEYWORDS`, and every object closed
    (`additionalProperties: false`) with every property required, as strict modes want. The
    engine's own schemas already close every object, so in practice this only drops `uniqueItems`."""
    if isinstance(schema, list):
        return [wire_schema(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    out = {}
    for k in WIRE_KEYWORDS:
        if k not in schema:
            continue
        v = schema[k]
        if k == "properties":
            out[k] = {name: wire_schema(sub) for name, sub in v.items()}
        elif k == "items":
            out[k] = wire_schema(v)
        else:
            out[k] = v
    if out.get("type") == "object":
        props = out.setdefault("properties", {})
        out["additionalProperties"] = False
        out["required"] = list(props)
    return out


def reasoning_param(max_thinking_tokens: int, effort: str, off_level: str = "none") -> dict | None:
    """[limits] -> the `reasoning` object (OpenRouter takes an effort level or a token budget, not
    both). 0 turns reasoning off (`effort: off_level`). Otherwise a set `effort` is sent as the
    effort level: on the real preflight of 2026-11-10 a 2,000-token budget was not honoured by the
    effort-only models (Grok 4.7 reasoned for 10,001 tokens, DeepSeek V4 Pro used its whole output
    limit), and an effort level is the setting every lab's model accepts. With no effort set,
    > 0 sends `max_tokens`; -1 sends nothing."""
    if max_thinking_tokens == 0:
        return {"effort": off_level, "exclude": True}
    if effort:
        return {"effort": effort, "exclude": True}
    if max_thinking_tokens > 0:
        return {"max_tokens": int(max_thinking_tokens), "exclude": True}
    return None


def provider_param(providers: list | None = None) -> dict:
    """The `provider` object. Every request asks only for providers that support every parameter
    sent (structured output, reasoning); a model with an [openrouter.providers_by_model] entry is
    also sent only to those providers, tried in that order, with no fallback to any other."""
    if not providers:
        return {"require_parameters": True}
    return {"require_parameters": True, "only": list(providers), "order": list(providers),
            "allow_fallbacks": False}


def build_request(model: str, system: str, prompt: str, schema: dict, *, max_output_tokens: int,
                  max_thinking_tokens: int = -1, effort: str = "", off_level: str = "none",
                  reasoning_effort: str | None = None, providers: list | None = None) -> dict:
    """The request body. `reasoning_effort` (a model's [openrouter.reasoning_effort_by_model]
    entry, or the step of REASONING_OFF_CHAIN it has fallen back to) replaces the [limits] mapping;
    `providers` (its [openrouter.providers_by_model] entry) pins the providers. Left at None, the
    body is exactly the one built before these settings existed."""
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": SCHEMA_NAME, "strict": True, "schema": wire_schema(schema)}},
        "max_tokens": int(max_output_tokens),
        "provider": provider_param(providers),
    }
    if reasoning_effort is not None:
        r = {"effort": reasoning_effort, "exclude": True}
    else:
        r = reasoning_param(max_thinking_tokens, effort, off_level)
    if r is not None:
        body["reasoning"] = r
    return body


# --------------------------------------------------------------------------- response

def extract_json(text) -> dict | None:
    """The JSON object in a reply: the whole text, else inside a code fence, else the first
    object that parses starting at a `{`."""
    if not isinstance(text, str):
        return None
    s = text.strip()
    try:
        v = json.loads(s)
        if isinstance(v, dict):
            return v
    except ValueError:
        pass
    for m in re.finditer(r"```(?:json|JSON)?\s*\n?(.*?)```", s, re.S):
        try:
            v = json.loads(m.group(1).strip())
            if isinstance(v, dict):
                return v
        except ValueError:
            pass
    dec = json.JSONDecoder()
    for i, ch in enumerate(s):
        if ch == "{":
            try:
                v, _ = dec.raw_decode(s, i)
            except ValueError:
                continue
            if isinstance(v, dict):
                return v
    return None


def _int(v) -> int:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def parse_or_usage(u) -> tuple[dict, float | None]:
    """OpenRouter `usage` -> (the six usage keys, the reported cost or None).

    Same meaning as the CLI path: `input` uncached prompt tokens, `cache_read` cached ones,
    `cache_creation` cache writes, `output` completion tokens (reasoning included), `thinking`
    reasoning tokens. `cost_usd` is filled by the caller (reported or computed)."""
    usage = zero_usage()
    if not isinstance(u, dict):
        return usage, None
    pd = u.get("prompt_tokens_details") if isinstance(u.get("prompt_tokens_details"), dict) else {}
    cd = u.get("completion_tokens_details") if isinstance(u.get("completion_tokens_details"), dict) else {}
    prompt = _int(u.get("prompt_tokens"))
    cached = _int(pd.get("cached_tokens"))
    written = _int(pd.get("cache_write_tokens"))
    usage["input"] = max(0, prompt - cached - written)
    usage["cache_read"] = cached
    usage["cache_creation"] = written
    usage["output"] = _int(u.get("completion_tokens"))
    usage["thinking"] = _int(cd.get("reasoning_tokens"))
    cost = _num(u.get("cost"))
    if cost is not None and u.get("is_byok"):
        det = u.get("cost_details") if isinstance(u.get("cost_details"), dict) else {}
        up = _num(det.get("upstream_inference_cost"))
        if up is not None:
            cost += up                    # BYOK: OpenRouter's fee plus the provider's own bill
    return usage, cost


def price_cost(usage: dict, price: dict | None) -> float | None:
    """Cost from [openrouter.prices] (dollars per million tokens): every prompt token at the input
    price (cached ones too, so it errs high) and every completion token at the output price."""
    if not price:
        return None
    prompt = usage["input"] + usage["cache_read"] + usage["cache_creation"]
    return (prompt * price["input"] + usage["output"] * price["output"]) / 1e6


def _content_text(content) -> str | None:
    if isinstance(content, str):
        return content
    if isinstance(content, list):                 # some providers send content parts
        parts = [p.get("text") for p in content if isinstance(p, dict) and isinstance(p.get("text"), str)]
        return "".join(parts) if parts else None
    return None


def _is_moderation(err: dict) -> bool:
    meta = err.get("metadata") if isinstance(err.get("metadata"), dict) else {}
    if meta.get("reasons") or meta.get("flagged_input"):
        return True
    msg = str(err.get("message") or "").lower()
    return any(w in msg for w in ("moderation", "flagged", "content policy", "safety", "guardrail"))


# --------------------------------------------------------------------------- transport

def urllib_transport(url: str, headers: dict, body: bytes, timeout: float) -> tuple[int, bytes]:
    """POST with urllib (blocking; the client runs it in a worker thread). Returns (status, body)
    for every HTTP answer, error statuses included; raises TimeoutError on a timeout and OSError
    on a network failure. Nothing here prints or keeps the headers."""
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        try:
            data = e.read()
        except OSError:
            data = b""
        return e.code, data
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError) or "timed out" in str(e.reason):
            raise TimeoutError("request timed out") from None
        raise OSError(f"network error: {type(e.reason).__name__}") from None


# --------------------------------------------------------------------------- client

class OpenRouterClient:
    """Calls OpenRouter's chat/completions endpoint. Same `call` contract as `ClaudeCLI`.

    Concurrency is bounded by its own semaphore (per event loop), timeout from `call_timeout_s`.
    `transport(url, headers, body, timeout) -> (status, body bytes)` is injectable; tests never
    touch the network. Every reported (or computed) cost is added to the spend ledger.

    Output limit: a call asks for `max_output_tokens_by_model[model]` (else `max_output_tokens`).
    After a reply that is empty or cut off with finish_reason "length", the next attempt of the same
    turn (same model, player, phase, system and turn prompt) asks for twice the previous limit, up to
    `max_output_tokens_ceiling`; the engine's attempt count is unchanged. No other failure changes
    the limit. The limit used is the first of the call's transport notes (`stderr_tail`).

    Per-model settings: a model with a `reasoning_effort_by_model` entry is sent that effort whatever
    [limits] says (an entry "none" falls back along REASONING_OFF_CHAIN like `max_thinking_tokens = 0`);
    a model with a `providers_by_model` entry is sent only to those providers. For a model with an
    entry in either, the call's last transport note names the provider that served the reply, when
    the response says. Every other model's requests and notes are unchanged."""

    wants_view = False
    needs_prompt = True

    def __init__(self, *, ledger: SpendLedger, max_parallel_calls: int = 4, timeout_s: float = 240,
                 max_thinking_tokens: int = -1, effort: str = "", max_output_tokens: int = 6000,
                 prices: dict | None = None, transport: Callable | None = None, environ=None,
                 sleep: Callable | None = None, http_retries: int = HTTP_RETRIES, backoff=BACKOFF_S,
                 url: str = API_URL, max_output_tokens_by_model: dict | None = None,
                 max_output_tokens_ceiling: int = DEFAULT_OUTPUT_CEILING,
                 reasoning_effort_by_model: dict | None = None, providers_by_model: dict | None = None):
        self.ledger = ledger
        self.max_parallel_calls = max_parallel_calls
        self.timeout_s = timeout_s
        self.max_thinking_tokens = max_thinking_tokens
        self.effort = effort
        self.max_output_tokens = max_output_tokens
        self.max_output_tokens_by_model = dict(max_output_tokens_by_model or {})
        self.max_output_tokens_ceiling = max_output_tokens_ceiling
        self.reasoning_effort_by_model = dict(reasoning_effort_by_model or {})
        self.providers_by_model = {m: list(p) for m, p in (providers_by_model or {}).items()}
        self._length_fails: dict[str, int] = {}   # turn key -> length failures so far in that turn
        self.prices = dict(prices or {})
        self._transport = transport or urllib_transport
        self._environ = environ              # None: os.environ, read at call time
        self._sleep = sleep or asyncio.sleep
        self.http_retries = http_retries
        self.backoff = tuple(backoff)
        self.url = url
        self._off_level: dict[str, int] = {}     # model -> index into REASONING_OFF_CHAIN
        self._warned: set = set()
        self._sem: asyncio.Semaphore | None = None
        self._sem_loop = None
        # Its own threads, so a busy default executor can never eat into a call's timeout; twice the
        # semaphore so a timed-out request still finishing in its thread does not hold up the next.
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=2 * max(1, max_parallel_calls),
                                                           thread_name_prefix="openrouter")

    @classmethod
    def from_config(cls, cfg, *, ledger: SpendLedger, **kw) -> "OpenRouterClient":
        lim, orc = cfg.limits, cfg.openrouter
        return cls(ledger=ledger, max_parallel_calls=lim.max_parallel_calls, timeout_s=lim.call_timeout_s,
                   max_thinking_tokens=lim.max_thinking_tokens, effort=lim.effort,
                   max_output_tokens=orc.max_output_tokens, prices=orc.prices,
                   max_output_tokens_by_model=orc.max_output_tokens_by_model,
                   max_output_tokens_ceiling=orc.max_output_tokens_ceiling,
                   reasoning_effort_by_model=orc.reasoning_effort_by_model,
                   providers_by_model=orc.providers_by_model, **kw)

    # ------------------------------------------------------------------ per-model settings

    def has_entry(self, model: str) -> bool:
        """The model has a reasoning_effort_by_model or providers_by_model entry."""
        return model in self.reasoning_effort_by_model or model in self.providers_by_model

    def reasoning_off(self, model: str) -> bool:
        """This model's reasoning is switched off: by its entry ("none"), else globally
        ([limits] max_thinking_tokens = 0). Only then does a refusal move it along REASONING_OFF_CHAIN."""
        entry = self.reasoning_effort_by_model.get(model)
        if entry is not None:
            return entry == "none"
        return self.max_thinking_tokens == 0

    def _effort_for(self, model: str) -> str | None:
        """The `reasoning.effort` a model's entry sends (None: no entry, [limits] decides)."""
        entry = self.reasoning_effort_by_model.get(model)
        if entry == "none":
            return REASONING_OFF_CHAIN[self._off_level.get(model, 0)]
        return entry

    # ------------------------------------------------------------------ output limit

    def start_limit(self, model: str) -> int:
        """The limit of a turn's first attempt: the model's own, else `max_output_tokens`."""
        return int(self.max_output_tokens_by_model.get(model, self.max_output_tokens))

    def limit_for(self, model: str, length_failures: int) -> int:
        """Start limit doubled once per earlier length failure in the turn, never above the ceiling
        (and never below the start limit)."""
        start = self.start_limit(model)
        top = max(start, int(self.max_output_tokens_ceiling))
        return min(top, start * 2 ** max(0, length_failures))

    @staticmethod
    def turn_key(model: str, player, phase, system: str, prompt: str) -> str:
        i = prompt.find(RETRY_MARK)
        base = prompt if i < 0 else prompt[:i]
        h = hashlib.sha256()
        for part in (model, str(player), str(phase), system, base):
            h.update(part.encode("utf-8", "replace") + b"\0")
        return h.hexdigest()

    def _note_length_failure(self, key: str) -> None:
        """Count a length failure for the turn. Nothing else changes the count, so a reply the engine
        rejects for another reason keeps the raised limit for the turn's next attempt. A new turn has
        a new prompt, hence a new key; the oldest keys are forgotten past TURN_MEMORY."""
        n = self._length_fails.pop(key, 0) + 1
        self._length_fails[key] = n
        while len(self._length_fails) > TURN_MEMORY:
            self._length_fails.pop(next(iter(self._length_fails)))

    def _semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        if self._sem is None or self._sem_loop is not loop:
            self._sem = asyncio.Semaphore(self.max_parallel_calls)
            self._sem_loop = loop
        return self._sem

    def _key(self) -> str:
        env = os.environ if self._environ is None else self._environ
        return env.get(KEY_ENV, "") or ""

    @staticmethod
    def _scrub(text: str, key: str) -> str:
        if key and len(key) >= 8:
            text = text.replace(key, "[redacted]")
        return _KEY_SHAPE.sub("[redacted]", text)

    async def _send(self, headers: dict, body: bytes):
        res = self._transport(self.url, headers, body, self.timeout_s)
        if inspect.isawaitable(res):
            return await res
        return res

    async def _post(self, headers: dict, body: bytes):
        """Run the (blocking) transport in a thread, with the call timeout."""
        if inspect.iscoroutinefunction(self._transport):
            coro = self._send(headers, body)
        else:
            coro = asyncio.get_running_loop().run_in_executor(
                self._pool, functools.partial(self._transport, self.url, headers, body, self.timeout_s))
        return await asyncio.wait_for(coro, timeout=self.timeout_s)

    async def call(self, *, model: str, system: str, prompt: str, schema: dict,
                   phase: str | None = None, player: str | None = None, view=None) -> LLMReply:
        self.ledger.check()                              # SpendStop: nothing is sent
        key = self._key()
        if not key:
            return LLMReply(None, "", None, zero_usage(), 0.0, f"{KEY_ENV} is not set", "cli")
        tkey = self.turn_key(model, player, phase, system, prompt)
        fails = self._length_fails.get(tkey, 0)
        limit = self.limit_for(model, fails)
        async with self._semaphore():
            self.ledger.check()                          # the budget may have been reached while waiting
            t0 = time.monotonic()
            state = {"length": False}
            reply = await self._call(model, system, prompt, schema, key, limit, fails, state)
            reply.latency_s = round(time.monotonic() - t0, 3)
        if state["length"]:
            self._note_length_failure(tkey)
        if self.has_entry(model) and state.get("provider"):
            reply.stderr_tail += f", provider {state['provider']}"
        if reply.served_model and reply.served_model != model and (model, reply.served_model) not in self._warned:
            self._warned.add((model, reply.served_model))
            print(f"warning: requested {model} but served {reply.served_model}", file=sys.stderr)
        return reply

    async def _call(self, model, system, prompt, schema, key, limit, fails, state) -> LLMReply:
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                   "X-OpenRouter-Title": "Inside Job"}
        start = self.start_limit(model)
        notes: list[str] = [f"max_output_tokens {limit}" + (
            f" (raised from {start} after {fails} length failure{'s' if fails != 1 else ''} this turn)"
            if limit != start else "")]
        total = zero_usage()
        tries = 0
        while True:
            tries += 1
            state["provider"] = None                     # the provider of this try's response, if it says
            off = REASONING_OFF_CHAIN[self._off_level.get(model, 0)]
            body = build_request(model, system, prompt, schema, max_output_tokens=limit,
                                 max_thinking_tokens=self.max_thinking_tokens, effort=self.effort, off_level=off,
                                 reasoning_effort=self._effort_for(model),
                                 providers=self.providers_by_model.get(model))
            try:
                status, raw = await self._post(headers, json.dumps(body).encode("utf-8"))
            except (asyncio.TimeoutError, TimeoutError):
                notes.append("timeout")
                return self._reply(None, "", None, total, f"timeout after {self.timeout_s}s", "timeout", notes)
            except OSError as e:
                notes.append(f"network error ({type(e).__name__})")
                if tries <= self.http_retries:
                    await self._sleep(self.backoff[min(tries - 1, len(self.backoff) - 1)])
                    continue
                return self._reply(None, "", None, total, f"network error after {tries} tries", "cli", notes)

            text = self._scrub(raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw), key)
            notes.append(f"http {status}")
            try:
                obj = json.loads(text)
            except ValueError:
                obj = None
            obj = obj if isinstance(obj, dict) else {}
            if isinstance(obj.get("provider"), str) and obj["provider"].strip():
                state["provider"] = self._scrub(obj["provider"].strip()[:ERROR_CHARS], key)
            usage, cost = parse_or_usage(obj.get("usage"))
            served = obj.get("model") if isinstance(obj.get("model"), str) else None
            if cost is None and any(usage[k] for k in ("input", "output", "cache_read", "cache_creation")):
                cost = price_cost(usage, self.prices.get(model))
                if cost is None:
                    self.ledger.halt(f"cannot track spend for {model}: the response carries no cost and "
                                     f"[openrouter.prices] has no entry for it")
                    usage["cost_usd"] = 0.0
                    total = _add(total, usage)
                    return self._reply(None, text, served, total, f"cannot track spend for {model}: the response "
                                       "carries no cost and [openrouter.prices] has no entry for it", "cli", notes)
            if cost:
                self.ledger.add(model, cost)
            usage["cost_usd"] = round(cost or 0.0, 6)
            total = _add(total, usage)

            err = obj.get("error") if isinstance(obj.get("error"), dict) else None
            eff = status
            if status == 200 and err is not None and not obj.get("choices"):
                code = err.get("code")
                eff = code if isinstance(code, int) and not isinstance(code, bool) and code != 200 else 502
            if eff == 200 and obj:
                return self._parse_choice(obj, text, served, total, notes, model, limit, state)
            msg = self._scrub(str((err or {}).get("message") or "")[:ERROR_CHARS], key)
            if eff == 200:
                return self._reply(None, text, served, total, "response is not JSON", "cli", notes)
            if eff == 400 and self.reasoning_off(model) and re.search(r"reason|effort", msg, re.I):
                i = self._off_level.get(model, 0)
                if i + 1 < len(REASONING_OFF_CHAIN):         # the model cannot turn reasoning off
                    self._off_level[model] = i + 1
                    notes.append(f"reasoning effort {REASONING_OFF_CHAIN[i]} refused; trying "
                                 f"{REASONING_OFF_CHAIN[i + 1]}")
                    continue
            if eff == 408:
                return self._reply(None, text, served, total, f"HTTP 408 timeout: {msg}", "timeout", notes)
            if eff == 429 or eff >= 500:
                if tries <= self.http_retries:
                    await self._sleep(self.backoff[min(tries - 1, len(self.backoff) - 1)])
                    continue
                return self._reply(None, text, served, total, f"HTTP {eff} after {tries} tries: {msg}", "cli", notes)
            if eff == 403 and err is not None and _is_moderation(err):
                return self._reply(None, text, served, total, f"blocked by moderation (HTTP 403): {msg}",
                                   "blocked", notes)
            if eff in (401, 402, 403):
                what = {401: "OpenRouter refused the API key (HTTP 401): check the key in OPENROUTER_API_KEY",
                        402: f"OpenRouter account or key has insufficient credits (HTTP 402): {msg}",
                        403: f"OpenRouter refused the request (HTTP 403): {msg}"}[eff]
                self.ledger.halt(what)
                return self._reply(None, text, served, total, what, "cli", notes)
            return self._reply(None, text, served, total, f"HTTP {eff}: {msg}", "cli", notes)

    def _parse_choice(self, obj, text, served, usage, notes, model, limit, state) -> LLMReply:
        choices = obj.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            return self._reply(None, text, served, usage, "response has no choices", "cli", notes)
        ch = choices[0]
        msg = ch.get("message") if isinstance(ch.get("message"), dict) else {}
        fr = ch.get("finish_reason")
        nfr = str(ch.get("native_finish_reason") or "").lower()
        refusal = msg.get("refusal")
        if (isinstance(refusal, str) and refusal.strip()) or fr == "content_filter" or nfr in BLOCK_FINISH:
            why = (f"refusal: {refusal.strip()[:ERROR_CHARS]}" if isinstance(refusal, str) and refusal.strip()
                   else f"finish_reason {fr}" + (f" ({nfr})" if nfr else ""))
            return self._reply(None, text, served, usage, f"blocked by the model's safety filter: {why}",
                               "blocked", notes)
        if fr == "error":
            e = ch.get("error") if isinstance(ch.get("error"), dict) else {}
            if _is_moderation(e):
                return self._reply(None, text, served, usage, "blocked by moderation", "blocked", notes)
            return self._reply(None, text, served, usage,
                               f"provider error: {str(e.get('message') or '')[:ERROR_CHARS]}", "cli", notes)
        content = _content_text(msg.get("content"))
        data = extract_json(content)
        if data is None:
            state["length"] = fr == "length"             # empty or cut off at the limit: escalate next time
            why = "reply is not a JSON object"
            if fr == "length":
                why += f" (cut off at max_output_tokens {limit}: finish_reason length)"
            elif not content:
                why = "reply is empty" + (" (finish_reason length: reasoning used the whole max_output_tokens)"
                                          if fr == "length" else "")
            return self._reply(None, text, served, usage, why, "cli", notes, raw_text=content or "")
        return self._reply(data, text, served, usage, None, None, notes, raw_text=content)

    @staticmethod
    def _reply(data, body_text, served, usage, error, kind, notes, raw_text=None) -> LLMReply:
        return LLMReply(data=data, raw_text=raw_text if raw_text is not None else body_text, served_model=served,
                        usage=usage, latency_s=0.0, error=error, error_kind=kind, raw_stdout=body_text,
                        stderr_tail="openrouter: " + ", ".join(notes), returncode=None)


def _add(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = out.get(k, 0) + v
    out["cost_usd"] = round(out["cost_usd"], 6)
    return out


# --------------------------------------------------------------------------- router

class RoutedLLM:
    """One `ClaudeCLI` and one `OpenRouterClient`; each call goes to one of them by model id.

    Once the spend ledger has stopped, every call (Claude ones too) raises SpendStop, so games in
    flight stop at their next call instead of playing on."""

    wants_view = False
    needs_prompt = True

    def __init__(self, cli: ClaudeCLI, openrouter: OpenRouterClient, ledger: SpendLedger):
        self.cli = cli
        self.openrouter = openrouter
        self.ledger = ledger

    # Read by the engine (raw header) and anything else that looked at a ClaudeCLI.
    @property
    def claude_bin(self) -> str:
        return self.cli.claude_bin

    @property
    def effort(self) -> str:
        return self.cli.effort

    @property
    def max_thinking_tokens(self) -> int:
        return self.cli.max_thinking_tokens

    @property
    def max_parallel_calls(self) -> int:
        return self.cli.max_parallel_calls

    @property
    def timeout_s(self) -> float:
        return self.cli.timeout_s

    def client_for(self, model: str):
        return self.openrouter if is_openrouter_model(model) else self.cli

    async def call(self, *, model: str, system: str, prompt: str, schema: dict,
                   phase: str | None = None, player: str | None = None, view=None) -> LLMReply:
        self.ledger.check()
        return await self.client_for(model).call(model=model, system=system, prompt=prompt, schema=schema,
                                                 phase=phase, player=player)


# --------------------------------------------------------------------------- building

def build_client(cfg, *, exec_fn: Callable | None = None, transport: Callable | None = None,
                 ledger: SpendLedger | None = None, environ=None, sleep: Callable | None = None):
    """A plain `ClaudeCLI.from_config(cfg)` when the cast and narrator are all Claude ids (exactly
    the client built before OpenRouter seats existed); a `RoutedLLM` otherwise."""
    cli_kw = {"exec_fn": exec_fn} if exec_fn is not None else {}
    if not cfg.openrouter_models():
        return ClaudeCLI.from_config(cfg, **cli_kw)
    ledger = ledger or process_ledger(cfg.openrouter.budget_usd)
    orc = OpenRouterClient.from_config(cfg, ledger=ledger, transport=transport, environ=environ, sleep=sleep)
    return RoutedLLM(ClaudeCLI.from_config(cfg, **cli_kw), orc, ledger)


def readiness_problems(cfg, environ=None) -> list[str]:
    """Why a real (non-mock) run with this config must not start; [] when it may. Never names the
    key's value."""
    models = cfg.openrouter_models()
    if not models:
        return []
    env = os.environ if environ is None else environ
    out = []
    if not env.get(KEY_ENV):
        out.append(f"{KEY_ENV} is not set: export it in your own shell to play the OpenRouter seats "
                   f"({', '.join(models)})")
    if cfg.openrouter.budget_usd is None:
        out.append(f"this cast includes OpenRouter models ({', '.join(models)}) and no spend budget is set: "
                   "add `[openrouter] budget_usd = <dollars>` to the config or pass --budget-usd")
    return out
