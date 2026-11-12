# OpenRouter seats

Other labs' models can sit at the table. They are called through OpenRouter's HTTPS API with
your own key. Claude models always run through `claude -p` on the subscription, unchanged.

Code: `inside_job/openrouter.py`. Example config: `config/frontier_table.toml`. Tests:
`tests/test_openrouter.py`, `tests/test_openrouter_limits.py` and
`tests/test_openrouter_per_model.py` (no network: a fake HTTP transport and a fake `claude -p`).

## Routing

- A model id with a `/` (`google/gemini-4-carbon`, `x-ai/grok-4.7`) is an OpenRouter model.
- An id without a `/` (`claude-opus-5-5`) is a Claude model, called through `claude -p`.
- An id that starts with `anthropic/` is rejected when the config is loaded. Claude models never
  run on the paid key.
- A config whose cast and narrator are all Claude ids builds the plain `ClaudeCLI` it always built.
  The argv, the environment and the logged config of such a game do not change.
- A mixed config builds a `RoutedLLM`: one `ClaudeCLI` and one `OpenRouterClient`, chosen per call
  by model id. Each one has its own `max_parallel_calls` limit, so a game can have up to twice that
  many calls in flight.
- Display names drop the vendor: `x-ai/grok-4.7` becomes `Grok 4.7`.

## Config

```toml
[openrouter]
budget_usd = 8.00             # required when any OpenRouter model is seated (or pass --budget-usd)
max_output_tokens = 4500      # per call, reasoning included; must be above [limits] max_thinking_tokens
max_output_tokens_ceiling = 16000   # optional: the most an escalated attempt asks for (see below)

[openrouter.max_output_tokens_by_model]   # optional: a model's own starting limit
"deepseek/deepseek-v4-pro-0813" = 8000

[openrouter.reasoning_effort_by_model]    # optional: a model's own reasoning effort (see below)
"deepseek/deepseek-v4-pro-0813" = "none"  # one of: none, minimal, low, medium, high

[openrouter.providers_by_model]           # optional: a model's own providers (see below)
"deepseek/deepseek-v4-pro-0813" = ["together"]   # OpenRouter provider slugs, tried in this order

[openrouter.prices."x-ai/grok-4.7"]   # optional, dollars per million tokens
input = 3.0
output = 15.0
```

### Output limit

- **Starting limit.** A call asks for `max_tokens` = the model's entry in
  `[openrouter.max_output_tokens_by_model]`, else `max_output_tokens`. Entries must be
  OpenRouter ids (`vendor/model`, not `anthropic/...`) with an integer >= 1. When `[limits]
  max_thinking_tokens` is above 0, each entry must be above it, as `max_output_tokens` must.
  Claude seats never see these settings.
- **Escalation.** When a reply is empty or cut off with `finish_reason: length` (no JSON object
  could be read), the next attempt of the same turn asks for twice the previous attempt's limit,
  never above `max_output_tokens_ceiling`. In other words, attempt *k* asks for
  `min(ceiling, start × 2^(length failures earlier in the turn))`. With the frontier settings and no
  per-model entry that is 4500, then 9000, then 16000.
- **What does not change.** No other failure (invalid JSON with another finish reason, a refusal,
  a timeout, a 4xx or 5xx, an engine rejection) raises the limit. It also does not lower one that an
  earlier length failure in the same turn raised. The client sends no extra request. The engine's
  attempts per turn (`[limits] retries` + 1, plus the one repeat after a block) are unchanged.
  The spend guard checks the budget before every attempt, escalated or not.
- **Same turn.** The client matches an attempt to the turn by model, player, phase, system prompt
  and the turn's prompt without the engine's retry line ("Your previous reply was rejected: ...").
  A new turn has a new prompt, so it starts again at the starting limit. The client remembers at
  most 256 turns with a pending length failure.
- **Ceiling.** `max_output_tokens_ceiling` must be an integer at least as large as every starting
  limit. When it is not set it is `max(16000, every starting limit)`, so a starting limit is never
  lowered. A model whose starting limit is at or above the ceiling does not escalate. To turn
  escalation off, set the ceiling equal to `max_output_tokens` (and leave out per-model entries
  above it). Every request is then byte for byte what the client sent before this setting existed.
- **Without the new settings** every first attempt, and every attempt that does not follow a length
  failure in its turn, is byte for byte what the client sent before (a test checks this against a
  saved request and across a whole fake game with failures mixed in). Escalation is on by default:
  the attempt after a length failure differs only in `max_tokens`.
- **Recorded.** The limit used is the first of the call's transport notes, so it is in the raw
  log's `stderr_tail` for every OpenRouter attempt, for example
  `openrouter: max_output_tokens 9000 (raised from 4500 after 1 length failure this turn), http 200`.
  A cut-off reply's error text names the limit it was cut at. The logged config
  (`config.openrouter` on `game_start`) and the `conditions` of the game's `games/index.jsonl` row
  carry `max_output_tokens`, `max_output_tokens_by_model` and `max_output_tokens_ceiling`.
  An index row of a game logged before these settings existed shows `{}` and a null ceiling: one
  limit for every model and no escalation.
- **Cost.** OpenRouter bills the tokens a call uses, not the limit it asks for. A higher limit costs
  more only on calls that run to it. The worst case for one turn rises from 3 × 4500 = 13,500
  output tokens to 4500 + 9000 + 16000 = 29,500 at the defaults, or 8000 + 16000 + 16000 =
  40,000 with a DeepSeek entry of 8000. A call in flight when the budget is reached can now
  overshoot by up to the ceiling's worth of output tokens.

`[limits]` applies to OpenRouter calls as follows:

| Key | OpenRouter request |
|---|---|
| `call_timeout_s` | Timeout for each HTTP request |
| `max_parallel_calls` | The client's own semaphore |
| `max_thinking_tokens > 0` | `reasoning: {max_tokens: N, exclude: true}`, only when `effort` is empty |
| `max_thinking_tokens = 0` | `reasoning: {effort: "none"}`. If the model refuses that with HTTP 400 (its reasoning is mandatory), the client resends with `"minimal"`, then `"low"`, and remembers the level for that model. |
| `max_thinking_tokens = -1` | no `reasoning` field, unless `effort` is set |
| `effort` | When set (and `max_thinking_tokens` is not 0): `reasoning: {effort: <effort>, exclude: true}`. OpenRouter takes an effort level or a token budget, not both; the effort level wins because the real preflight of 2026-11-10 showed effort-only models ignoring a 2,000-token budget (Grok 4.7: 10,001 reasoning tokens on one vote; DeepSeek V4 Pro: the whole output limit). |

**Known problem, DeepSeek V4 Pro (measured, `frontier4`, 2026-11-10).** At effort "low" and
`max_output_tokens = 4500` it spent the whole limit on reasoning and returned no answer on 19 of
37 calls (`finish_reason: length`, empty content). Three more were cut off mid-answer. Three of its
18 turns used all three attempts and fell back to the default move. Across the four frontier games
it hit the limit on 30 of 73 calls (26 empty, 4 cut off). Its 43 answered calls used a median of
3,119 completion tokens (90th percentile 3,925, maximum 4,378), almost all of it reasoning. The
answer itself was never more than 469 tokens. The logs cannot show how many tokens the 30 failed
calls would have needed, only that it was more than 4,500.

The per-model limit and the escalation above were built for this. **A higher limit did not fix it
on the one real call tried (measured, lead, 2026-11-11).** The first failed DeepSeek call of
`g-20261110-230705-s204` (raw attempt 29: round 1, discuss; same system prompt, turn prompt and
schema, read from the raw log) was sent once more with a starting limit of 8000 and
`reasoning: {effort: "low"}`. It came back `finish_reason: length` with no answer: 8,000 of 8,000
output tokens were reasoning, it took 274 seconds, and $0.0250 was billed. Two things follow:

- On that turn DeepSeek V4 Pro reasons to whatever limit it is given; effort "low" does not bound it.
- At about 29 output tokens a second, 8,000 tokens take longer than the frontier table's
  `call_timeout_s = 240`. In a game that call would have been cut off as a timeout, and 16,000
  would take about nine minutes. A larger limit is not usable for this model.

One call is one call, not a rate. The setting not yet tried is reasoning switched off for this model
alone (`effort: "none"`, falling back to "minimal"); the client has no per-model reasoning setting
today. Until something is shown to work on real calls, do not seat DeepSeek V4 Pro as a mole, and
expect fallback moves from it as crew. No `[openrouter.max_output_tokens_by_model]` entry is
recommended for it.

**Two per-model settings built for it, not yet shown to work on real calls (2026-11-11, 23:28).**
`[openrouter.reasoning_effort_by_model]` and `[openrouter.providers_by_model]` (see "Per-model
reasoning and providers" below) were built for this problem, so the per-model reasoning setting
the paragraph above calls missing now exists. Both are checked only against fake transports. No
real call has been made with either, so neither is shown to help. Who served each call, measured,
lead's count from the four frontier games' raw logs (73 DeepSeek V4 Pro calls):

| Provider | Calls | Outcome |
|---|---|---|
| Together | 4 | answered 4 of 4, 0 reasoning tokens (median 379 completion tokens) |
| Wafer | 14 | answered 14 of 14 (median 3,476 reasoning tokens) |
| DigitalOcean | 17 | failed 10 of 17 |
| Sail Research | 23 | failed 10 of 23 |
| CoreWeave | 10 | failed 7 of 10 |
| Nebius | 3 | failed 2 of 3 |
| Baidu | 2 | failed 1 of 2 |

**Measured on real calls, 2026-11-11 23:31 to 23:33 (lead; paid test, $0.1955 billed, 42 calls).**
The 18 distinct DeepSeek V4 Pro turns that came back empty or cut off in the four frontier games were
sent again with the same system prompt, turn prompt, schema and 4,500 limit, no retry and no limit
escalation. Script: `ds_probe.py`, a scratch script not in the repo; one row per call was kept.

| Setting for this model | Calls | Answered with valid JSON | Served by | Reasoning tokens | Slowest call |
|---|---|---|---|---|---|
| `reasoning_effort_by_model = "none"`, no provider entry | 20 | 20 of 20 | Together 6, DigitalOcean 5, Wafer 4, Novita 3, Nebius 1, Sail Research 1 | 0 on every call | 31.9 s |
| `providers_by_model = ["together"]`, reasoning left at "low" | 20 | 20 of 20 | Together 20 | 0 on every call | 22.3 s |
| both | 2 | 2 of 2 | Together 2 | 0 | 3.2 s |

The first two rows are the 18 turns once each plus two of them a second time. Limits of this test:
these are single turns sent again, not a game; 20 calls with no failure puts the failure rate under
about 17% (exact 97.5% bound), not at zero; and the "none" row had only one call on Sail Research and
one on Nebius, none on CoreWeave or Baidu.

**Recommended setting for DeepSeek V4 Pro: `"deepseek/deepseek-v4-pro-0813" = "none"` under
`[openrouter.reasoning_effort_by_model]`,** with no provider entry, so the model does not depend on
one provider being up. `config/bluff_deepseek.toml` carries it. What it means for a comparison: this
model then plays with reasoning switched off, while the other outside-lab models are sent
`reasoning.effort = "low"`. Any DeepSeek result must say so.

**Shown in full games, 2026-11-12 (measured, `games/index.jsonl`, batch `bluff_deepseek`).** Five
full games with DeepSeek V4 Pro in both mole seats and this setting finished with 0 fallback moves
and 0 spoiled games (seeds 101 to 105, $0.57 billed). This replaces the advice above not to seat it
as a mole: seat it with reasoning off, and label every result so. `config/frontier_table.toml` does
not carry the setting.

`exclude: true` means the reasoning text is not returned. It is still billed and counted. This
matches the Claude path, which does not keep thinking text either.

A config with an `[openrouter]` table, or with an OpenRouter model, logs the table under
`config.openrouter` on `game_start`.

### Per-model reasoning and providers

Two optional tables change one model's requests and no other model's. Keys must be OpenRouter ids
(`vendor/model`, not `anthropic/...`). Claude seats never see these settings.

- **`[openrouter.reasoning_effort_by_model]`.** The value is one of `none`, `minimal`, `low`,
  `medium` or `high`. That model's requests carry `reasoning: {"effort": <value>, "exclude": true}`
  whatever `[limits] max_thinking_tokens` and `effort` say. With `"none"`, the reasoning-off
  fallback applies to that model as it does for `max_thinking_tokens = 0`: an HTTP 400 that mentions
  reasoning or effort moves it to `"minimal"`, then `"low"`, remembered for that model, with the
  note `reasoning effort none refused; trying minimal`. Any other value never falls back: a 400 is
  an ordinary 400. A model with an entry other than `"none"` does not take part in the
  `max_thinking_tokens = 0` fallback either.
- **`[openrouter.providers_by_model]`.** The value is a non-empty list of OpenRouter provider slugs
  (non-empty strings without spaces, no repeats). That model's requests carry
  `provider: {"require_parameters": true, "only": [...], "order": [...], "allow_fallbacks": false}`,
  with the list as given in both `only` and `order`. Every other model keeps
  `provider: {"require_parameters": true}`.
- **Provider note.** For a model with an entry in either table, each call's transport notes end with
  `provider <name>`, read from the top-level `provider` string of the call's last response when it
  has one (for example `openrouter: max_output_tokens 4500, http 200, provider Together`). No other
  model gets this note.
- **Logged.** Each table is in `config.openrouter` on `game_start` only when it is non-empty, so the
  logged config of every config without them is unchanged. The `conditions` of the
  `games/index.jsonl` row do not carry them.
- **Unchanged without them.** With both tables empty, every request body and every logged byte is
  what the client sent before these settings existed (the golden tests check this).

## The key

You run `export OPENROUTER_API_KEY=...` in your own shell. The client reads the variable at
call time and puts it only in the `Authorization: Bearer` header. It is never printed, logged,
written to the game log or the raw log, put in an error message, or stored in a config or test
file.

Response bodies are scrubbed before they are kept, in case a server echoes the key back. Both the
exact key and anything shaped like `sk-or-...` are replaced with `[redacted]`.
`tests/test_openrouter.py` plays a whole mixed game with a sentinel key, including one error body
that echoes it, and checks that the key appears in no output file and nowhere on stdout or stderr.

A real run (anything without `--mock`) with an OpenRouter model refuses to start in these cases:

- `OPENROUTER_API_KEY` is not set. The message says the variable is not set and never shows a value.
- No budget is set. The message asks for `[openrouter] budget_usd` or `--budget-usd`.

## Spend guard

- **Ledger.** One ledger per process, shared by every game in a batch. Each `run`, `trial`,
  `batch` or `preflight` command starts a fresh one. The preflight's calls count toward the same
  budget as the games after it.
- **Override.** `--budget-usd` on `run`, `trial`, `batch` and `preflight` overrides
  `[openrouter] budget_usd`. A resumed batch is a new process, so it starts with a full budget.
- **When spend reaches the budget**, the guard does all of the following:
  - No more paid requests are sent.
  - Every further call raises `SpendStop`, Claude calls included, so games in flight stop at their
    next call. The engine has no fallback for that exception, so a stopped game is never finished
    with fallback moves.
  - `batch` cancels the other games in flight and starts no new ones.
  - Stopped games are not written to `games/index.jsonl`, so they are replayed on resume. Their
    partial `.jsonl` logs stay on disk, like a crashed game's.
  - One `STOPPED: OpenRouter spend reached the budget: $X billed of $Y ...` line is printed. The
    exit code is 3.
- **Overshoot.** A call already in flight when the budget is reached is still paid for. Spend can
  pass the budget by about the cost of the calls in flight at that moment: up to
  `parallel_games × max_parallel_calls` calls.
- **Cost of each call.** The client uses `usage.cost` from the response. If the response has no
  cost, it uses `[openrouter.prices]`, with every prompt token at the input price (so the figure
  errs high). If there is neither, the call fails with "cannot track spend" and the guard stops the
  run. The preflight therefore fails for that model before any game starts.
- **HTTP 401, 402 or 403 (not moderation).** These mean a bad key, no credit or a forbidden
  request. The guard stops the run with a clear message that does not contain the key. There is no
  retry.

## Errors

| Response | `error_kind` | Notes |
|---|---|---|
| `message.refusal`, `finish_reason: content_filter`, a safety `native_finish_reason`, 403 with moderation metadata | `blocked` | The engine retries once, unchanged, as it does for the CLI. |
| Client timeout, HTTP 408 | `timeout` | |
| 429 or 5xx (also a 200 whose body is only an `error`) | `cli` | Two retries inside the client first, with 2 s and 8 s backoff. |
| 400, 404 and other errors | `cli` | |
| Reply not valid JSON | `cli` | The client first tries to recover the object from code fences or surrounding text. |
| Empty or cut-off reply with `finish_reason: length` | `cli` | The turn's next attempt asks for a larger limit (see "Output limit"). |

The engine's usual retry logic applies to every one of these.

## Schema on the wire

The engine's turn schemas already close every object (`additionalProperties: false`) and list
every property in `required`.

The wire copy (`wire_schema`) keeps only these keywords: `type`, `properties`, `required`,
`additionalProperties`, `items`, `enum`, `description`, `minimum`, `maximum`, `minItems` and
`maxItems`. It closes every object again. Today the only keyword it drops is `uniqueItems`, which
some strict modes reject.

The engine still validates every reply against the full schema, `uniqueItems` included. A
repeated item is rejected and the model is retried with the rejection line, as for any invalid
reply.

The request sends `response_format: {type: "json_schema", json_schema: {name: "inside_job_reply",
strict: true, schema}}` and `provider: {require_parameters: true}` (more for a model with a
`[openrouter.providers_by_model]` entry; see "Per-model reasoning and providers").

## Usage

Usage has the same meaning as on the Claude path:

| Usage key | From the OpenRouter response |
|---|---|
| `input` | `prompt_tokens − cached_tokens − cache_write_tokens` |
| `cache_read` | `prompt_tokens_details.cached_tokens` |
| `cache_creation` | `prompt_tokens_details.cache_write_tokens` |
| `output` | `completion_tokens` (reasoning included, as on the CLI path) |
| `thinking` | `completion_tokens_details.reasoning_tokens` |
| `cost_usd` | `usage.cost` |

For BYOK responses, `cost_usd` also includes `cost_details.upstream_inference_cost`.

`served_model` is the response's `model`. A mismatch is warned about once, as on the CLI path.

In the raw log, an OpenRouter attempt is recorded like this:

- `stdout`: the response body (scrubbed).
- `stderr_tail`: the client's transport notes: first the output limit used, then each HTTP
  status, for example `openrouter: max_output_tokens 4500, http 429, http 200`. For a model with a
  per-model reasoning or provider entry, the last note names the provider that served the reply.
- `returncode`: null.

## Reporting

- **Billed and notional.** OpenRouter dollars are real money. Claude `cost_usd` is the CLI's
  notional list price and is not billed.
- **Token report.** The per-game token report prints both totals for a mixed game. An all-Claude
  game prints the old line.
- **Batch lines.** The per-game line and the totals line add `(billed $x, notional $y)` when any
  money was billed.
- **Index row.** Each `games/index.jsonl` row has a new `billed_usd` field next to `tokens`.
  `tokens.cost_usd` stays the sum over all models, so existing readers see what they always saw.
  For a game whose config has an `[openrouter]` table, `conditions` also carries the output limits
  (see "Output limit"). An all-Claude game's row is unchanged.
- **`report` command.** Its health section still describes cost as the CLI's list price. It does
  not split billed from notional yet.

## Confirmed from OpenRouter's docs, and assumed

These were read on 2026-11-10 from the API reference, the structured outputs, reasoning tokens,
provider selection, usage accounting, errors and authentication pages.

Confirmed:

- **Endpoint and header.** `POST https://openrouter.ai/api/v1/chat/completions` with
  `Authorization: Bearer <key>`. `X-OpenRouter-Title` is an optional header.
- **Request fields.** `messages`, `max_tokens`, and
  `response_format: {type: "json_schema", json_schema: {name, strict, schema}}`.
- **Provider routing.** `provider.require_parameters: true` routes only to providers that support
  every parameter sent.
- **Reasoning.**
  - `reasoning.max_tokens` and `reasoning.effort` are one or the other, not both.
  - The effort levels are `max`, `xhigh`, `high`, `medium`, `low`, `minimal` and `none`.
  - `effort: "none"` is rejected by models whose reasoning is mandatory.
  - `exclude: true` hides the reasoning text.
  - For effort-only models, `max_tokens` is converted to an effort level.
  - Reasoning counts against `max_tokens` on most providers.
- **Usage.**
  - It is returned on every non-streaming response.
  - The `usage: {include: true}` request parameter is deprecated and has no effect, so it is not
    sent.
  - Field names: `prompt_tokens`, `completion_tokens`, `prompt_tokens_details.cached_tokens`,
    `prompt_tokens_details.cache_write_tokens`, `completion_tokens_details.reasoning_tokens`,
    `cost`, `is_byok`, `cost_details.upstream_inference_cost`.
- **Responses.**
  - Finish reasons are normalised to `stop`, `length`, `content_filter`, `tool_calls` and `error`.
    `native_finish_reason` carries the provider's own value.
- **Errors.**
  - The shape is `{error: {code, message, metadata}}`.
  - Status codes: 400, 401 (bad key), 402 (no credits), 403 (forbidden, guardrail or moderation),
    408, 429, 502 and 503.
  - Moderation metadata carries `reasons` and `flagged_input`.
  - A 200 can carry an `error` body, or an error inside a choice with `finish_reason: "error"`.

Assumed, to be checked by the first real preflight:

- **Cost units.** `usage.cost` is in US dollars. The docs say "credits".
- **Prompt tokens.** `prompt_tokens` includes the cached and cache-write tokens, as in OpenAI's
  usage format, so the client subtracts them.
- **Refusals.** `message.refusal` is passed through from OpenAI-style providers. The chat
  completions schema in the docs does not list it.
- **Safety finish values.** The `native_finish_reason` values treated as safety blocks (`SAFETY`,
  `refusal`, `prohibited_content` and similar) are a guess at the providers' spellings.
- **Wire schema.** Every provider for the five example models accepts the wire schema in strict
  mode, including the empty `move` object of `cut_pitch`, `enum: [""]` and `maxItems: 0`. If one
  does not, the preflight shows a 400 for that model.
- **Provider routing.** `require_parameters: true` together with `reasoning` and `response_format`
  leaves at least one provider for each model. Otherwise the preflight shows a 404 or 503.
- **Turning reasoning off.** The 400 message from a mandatory-reasoning model mentions "reasoning"
  or "effort". That is what triggers the `none` → `minimal` → `low` fallback.
- **Model ids.** The five ids in `config/frontier_table.toml` exist on OpenRouter under those exact
  names.
- **Timed-out calls.** A request that times out on the client side may still be billed by
  OpenRouter. The ledger cannot see that cost.

Check it with one real preflight before any game, with a small budget, for example:

```
export OPENROUTER_API_KEY=...        # in your own shell
python3.11 -m inside_job preflight --config config/frontier_table.toml --budget-usd 0.50
```

Then compare the billed total it reports with the OpenRouter activity page.
