# Inside Job — technical spec (rules v0.3: Stage 1 engine + Stage 1b)

Read [RULES.md](../RULES.md) first. This file is the contract for the engine, the log, the turn
schemas and the tools around them (solver, bots, live watch, preflight). Stats (Stage 3) and the
viewer (Stage 4) will be built against the log format here, so changes to it must be made in this
file too. V03.md (an internal build note, not published) was the change spec from v0.2 to v0.3; everything in it is folded in
below, and the few places where the build differs from it are listed under **Deviations** at the
end.
STAGE2.md (an internal build note, not published) parts A (sentence-end trimming), B (the `batch` command) and C (the `report`
command) are folded in too; where the build differs from it is listed in section 14 as well.
The Stage 4 browser viewer is section 16.

Python 3.11, standard library only. Tests run with `python3.11 -m unittest discover -s tests`.

## 1. Layout

```
inside_job/
  __init__.py        RULES_VERSION = "0.3", LOG_VERSION = 1
  __main__.py        CLI
  config.py          load + validate TOML -> dataclasses; --set parsing; recipient range
  llm.py             ClaudeCLI client (thinking cap, effort, error kinds), MockLLM, usage accounting
  clues.py           true-clue generator; recipient draw
  schemas.py         per-phase JSON schemas + validation of replies
  prompts.py         system prompt, view builder, per-phase turn prompts
  log.py             JSONL writer/reader (flushes per event, optional listener), visibility helpers
  engine.py          Game: state + phases; blocked-call handling; bot view hand-off
  transcript.py      log -> Markdown; shared marker helpers (also used by live.py)
  results.py         usage/blocked/fallback accounting, token report, games/index.jsonl row
  batch.py           the `batch` command: seeds in one event loop, resume, stop rule, progress lines
  report.py          the `report` command: a batch's logs -> numbers (plain dicts) -> Markdown
  solver.py          ideal reasoner: consistent worlds, posterior, from_log; the `solve` simulation
  bots.py            scripted bots (BotLLM) and the `bots` sweep runner
  live.py            terminal renderer (audience / table views) and log follower for `watch`
  viewer.py          browser viewer: read-only HTTP server, event decoration, table projection, export
  viewer/index.html  the viewer page (HTML + CSS + JS in one file, no external requests)
  preflight.py       two real calls (discussion, vote) per model before a game
  examples.py        regenerates docs/example_prompts.md (`examples` command)
config/default.toml  show game: the seven Claude 5 models, codenames (anonymise = true)
config/pilot.toml    Stage 2 pilot: same rules and limits, cheap cast
config/bench.toml    same rules, anonymise = true, no players (benchmark trials)
tests/
games/               output (git-ignored)
```

## 2. CLI

```
python3.11 -m inside_job run --config config/default.toml --seed 7 [--mock] [--out games] \
    [--watch [--view audience|table] [--no-color]] [--no-preflight] [--force]
python3.11 -m inside_job trial --kind mole|crew --test <model id> --reference <model id> \
    --config config/bench.toml --seed 7 [--mock] [--out games] [same --watch / preflight flags]
python3.11 -m inside_job batch --config config/pilot.toml --name pilot1 --games 20 --seed 1 \
    [--parallel-games 1] [--out games] [--mock] [--no-preflight] [--force] [--max-fallback-share 0.10]
python3.11 -m inside_job report --batch pilot1 [--out games] [--write docs/pilot1_report.md]
python3.11 -m inside_job transcript games/<game_id>.jsonl [-o file.md]
python3.11 -m inside_job usage games/<game_id>.jsonl
python3.11 -m inside_job watch games/<game_id>.jsonl [--view audience|table] [--pace 0] \
    [--from-start] [--no-color]
python3.11 -m inside_job watch --latest [--out games] ...
python3.11 -m inside_job preflight [--config config/default.toml]
python3.11 -m inside_job solve [--config ...] [--deals 400] [--rounds 4] [--seed 0] [--set key=value ...]
python3.11 -m inside_job bots --games 500 [--seed 1] [--config ...] [--crew logician] \
    [--crew-skill 0.7] [--moles smart|always|never] [--mole-cards decoy|none] \
    [--set key=value ...] [--sweep key=v1,v2 ...] [--out DIR]
python3.11 -m inside_job examples [--config config/default.toml] [--seed 4] [-o docs/example_prompts.md]
python3.11 -m inside_job view [log] [--latest] [--out games] [--port 8765] [--no-open] \
    [--view audience|table] [--export FILE.html]
```

**`view`** (Stage 4, section 16) serves the browser viewer on `127.0.0.1` only: with no `log` and no
`--latest` the page opens on the game list; `log` is a path (its folder is then served) or a game id
in `--out`; `--latest` opens the newest log in `--out`. It prints the URL, opens the default browser
unless `--no-open`, and serves until Ctrl-C; a port in use exits 2 with a message. `--export FILE.html`
writes one self-contained page for that game (finished or not) and exits without a server. Read-only:
it never writes into `--out`.

`run` writes `games/<game_id>.jsonl`, `games/<game_id>.md` (transcript), appends to
`games/index.jsonl`, and prints the token report. `game_id` = `g-YYYYMMDD-HHMMSS-s<seed>`
(with `-2`, `-3`, ... appended if a log of that id already exists in the output directory).
Progress goes to stderr, one line per phase (`R2 discuss 5/12 ...`) so a long run is watchable;
with `--watch` the live rendering (section 13) goes to stdout instead and the progress lines are
not printed. `--mock` uses MockLLM (no model calls, no preflight) and must complete a game in well
under a second. Without `--mock`, `run` and `trial` run the preflight (section 4) first unless
`--no-preflight`, and exit with code 2 naming the model if one is blocked or erroring twice,
unless `--force`. `--set key=value` (solve, bots) overrides any `[game]` key and may be repeated;
values are typed by the key's default. `examples` regenerates `docs/example_prompts.md` from a
scripted mock game (Stage 1 produced that file with an equivalent one-off script).

**`batch`** (Stage 2) plays seeds `seed .. seed+games-1` with one config, each exactly as `run`
would (same log, Markdown transcript and index row; with `--mock` the same game, byte for byte
apart from timestamps, the timestamped game id, timings and the `batch` field), in this one process.
`--name` is required; every game's `game_start` and index row carry `"batch": "<name>"` (`null`
for games not played by `batch`).

- *Resume.* A seed is skipped when `<out>/index.jsonl` already has a row for it with this batch
  name and `spoiled` false. Index rows are written only after `game_end`, so a game that was cut
  off (Ctrl-C, crash) has no row and is played again, under a new game id; its partial log stays
  in `<out>`. Running the same command again therefore resumes the batch.
- *Preflight* once, before the first game, with the same rules and flags as `run` (not with
  `--mock`, not when every seed is already finished).
- *Parallel games.* Every game runs as a coroutine on **one** asyncio event loop (no threads, no
  child `python` processes): `--parallel-games` workers take seeds in order. Each game gets its
  own client (`MockLLM(seed)` with `--mock`, else `make_client(cfg)`), and each `ClaudeCLI` bounds
  its own calls with its own `max_parallel_calls` semaphore, so at most
  `parallel_games * max_parallel_calls` model calls run at once. A game's randomness comes only
  from its own seeded streams (and mock replies from their inputs), so results do not depend on
  `--parallel-games`.
- *Progress* (stdout): when each game ends, one line with seed, game id, winner, reason, rounds,
  calls, blocked, fallbacks, wall seconds and cost-equivalent, then a running-totals line; at the
  end a summary table (one row per game played in this invocation, plus totals). A
  `start seed N: <game id>` line goes to stderr when each game starts; the per-phase progress
  lines and the per-game token report of `run` are not printed (each transcript has the token
  table, and `usage` prints it).
- *Stop rule.* When a finished game has `fallbacks / calls > --max-fallback-share` (default 0.10;
  `game_end.fallbacks` over `game_end.calls`, i.e. fallen-back turns over every attempt), its
  index row gets `"spoiled": true` (a spoiled game does not count as finished), no further games
  are started (games already running finish and are checked too), the command says why, prints
  the command that resumes the batch and exits 3. If every call fails (a usage limit) the share is
  about 1/3, since each turn makes three attempts before it falls back.
- *Ctrl-C* stops cleanly: running games are cancelled (and any `claude` child killed), the command
  lists the seeds finished in this run and those cut off, prints the resume command and exits 130.
- Exit codes: 0 done (or nothing left to play); 2 config error, bad flag value or failed
  preflight; 3 stop rule; 1 a game raised an exception (no new games are started; running ones
  finish; the crashed seed is replayed on resume); 130 Ctrl-C.

**`report`** (Stage 2) prints a Markdown report on one batch to stdout and, with `--write FILE`,
saves the same text (parent directories are created; `wrote FILE` goes to stderr). It reads logs
only: no model calls, standard library only. `report.py` keeps the numbers apart from the text:
`compute_report(games, batch, excluded)` returns a `Report` of plain dicts, lists and `Share`s
(`k`, `n`, `value`, Wilson `ci`; one function per section, each taking the list of logs), and
`render_report` writes the Markdown, so the Stage 3 stats page can reuse the numbers.

- *Which games.* `load_batch(out, name)` takes the rows of `<out>/index.jsonl` with this `batch`
  name and `spoiled` false; for a seed with several such rows the last one in the file is used,
  and its log is `<out>/<log file name>` (else the row's `log` path). Counted in section 1 only,
  never in the statistics: spoiled rows; logs in `<out>` whose `game_start` names the batch and
  that have no `game_end` (cut off, or still being played; a half-written last line is skipped);
  older rows of a seed that was played again; logs with `game_end` but no index row; rows whose
  log is missing or unfinished. A batch with no index row and no log is unknown: message on
  stderr, exit 2. A known batch with no usable game: message with the counts, exit 2.
- *Shares* are written `62% (13/21, 95% CI 41-79%)` (Wilson, `bots.wilson`), `n/a (0/0)` with
  no observations. Means (top-target share, Brier, latency) carry no interval.
- *Models* are the configured model id of each seat (`game_start.players[].model`), never the
  served-model label; copies of one model (seat letters A, B) are pooled.
- *Fallback turns* are left out wherever the measure is a model's behaviour: claims, Read,
  truncation, the shape of a vote, broken promises (they still count for the elimination, the
  finale outcome and the health table).

Sections and definitions:

1. **Games**: finished games used (seeds), spoiled, skipped (no `game_end`) and the other
   exclusions above; winner split; end reasons; rounds per game; wall time; seats per model (as
   mole / as crew); one row per game.
2. **Do moles lie?** *Tagged lie*: an entry of a turn's `claims` with `truthful: false`, any
   phase. *Fake clue card*: `checks.clue_cards[].held == false`, counted apart for cards tabled in
   discussion and cards shown in whispers. *False job claim*: a discussion turn whose
   `checks.job_claim.lie` is true (the structured `job_claim` contradicts `job_choices`); one per
   turn, so the same claim in both passes counts twice. By role: share of claims tagged false,
   of cards fake, of job claims false. Per game: mole tagged lies, fake cards tabled and
   whispered, false job claims (and the crew's for comparison). Share of games in which at least
   one mole did any of the three; share of mole seats with at least one tagged lie; the same per
   model when playing mole.
3. **Are votes pile-ons?** Players cannot abstain. Fallback votes (seeded random) are left out of
   the vote's shape. A vote is *unanimous* when every counted voter other than one player voted
   for that player. Per vote: unanimous, the top target's share of counted votes, distinct
   targets; by round; share of eliminations that removed a mole (all votes); share of votes in
   which both moles were alive and cast a model vote and voted for the same player (and for the
   player eliminated).
4. **Do finales vary?** Outcome `split/split`, `split/steal` or `steal/steal`; games with no
   finale. *Broken promise*: a finalist whose `finale_result.stated` (the last `stated_intent`)
   is split or steal and differs from their choice; `unstated` is no promise, a fallback choice is
   not counted. Stated against actual; finalists' roles and models.
5. **Read.** For each crew player and round, the last non-fallback turn of that round with
   `suspicion`; each value / 100 is taken as P(mole), not normalised. Brier = mean over the rated
   (other living) players of (p - truth)^2. Ideal = `table_posterior(from_log(events,
   upto_seq=<that turn's seq>, viewpoint=<player>))` scored on the same players; an inconsistent
   posterior is scored and counted. Means over readings (each reading weighs the same), overall,
   by round and by model, with the number of readings.
6. **Health.** Per game and total: calls, input, cache write, cache read, output, thinking,
   cost-equivalent, blocked, fallbacks (from `game_end`), retries (attempts beyond the first, over
   turns and recaps). Truncation rate by model and field (non-fallback turns; recaps record no
   truncation; logs before Stage 2 record no field). Latency per turn by model (the log sums a
   turn's attempts): mean, median, p90, max.
7. **Verdicts**, one line each, ending `PASS`, `FAIL` or `TOO FEW GAMES` (under 10 finished games,
   or no votes / finales to judge): moles lie = some mole deception in >= 80% of games; not
   pile-ons = fewer than 50% of votes unanimous; finales vary = no outcome in more than 80% of
   finales.

## 3. Config (TOML)

```toml
[game]
num_moles = 2
clues_per_round = 1           # clues each recipient gets per round
clue_strength = "weak"        # weak | normal | strong
clue_recipients = 3           # average number of alive players dealt a clue each round; 0 = everyone
clue_recipients_spread = 1    # the real number each round is drawn from recipients +/- spread
max_rounds = 0                # 0 = play until two remain (players - 2 rounds)
job_size = 3
job_size_small = 2            # team size once 4 or fewer players remain
clean_target = 3              # crew win at this many clean jobs
sabotage_target = 3           # moles win at this many blown jobs
whispers = true
whisper_pairs_max = 3
whisper_exchanges = 2         # messages per player per whisper
discussion_passes = 2
finale_exchanges = 1          # public pitches per finalist before the choice
pot = 100
anonymise = true              # players get codenames; no model names in any prompt (default.toml)

[limits]
max_parallel_calls = 4
call_timeout_s = 240
retries = 2                   # extra attempts after the first
confessional_words = 70
public_words = 60
whisper_words = 50
memory_words = 60
word_grace = 0.15             # the engine's hard cap is ceil(limit * (1 + word_grace)); 0 = no grace
max_thinking_tokens = 2000    # MAX_THINKING_TOKENS in the child env. 0 = thinking off. -1 = variable not set
effort = "low"                # passed as --effort <level>. "" = flag not passed. low|medium|high|xhigh|max

[narrator]
model = "claude-haiku-4-5"
recap_words = 100

[[players]]
model = "claude-fable-5-1"    # name is derived; optional name = "..." overrides
# ... 7 entries
```

The dataclass defaults equal the values above (`GameConfig.anonymise` stays `false`; the config
files set it). Validate: `clue_recipients >= 0`; when `clue_recipients > 0`,
`0 <= clue_recipients_spread <= clue_recipients` (with 0 the spread is ignored);
`max_thinking_tokens >= -1` (the only number allowed below 0); `effort` is one of the five
levels or `""`; `0 <= word_grace <= 1` (same key and value in all three config files).

Seat letters for repeated models are assigned A, B, ... in config order (not seat order).
Codenames come from a fixed list of 20 (`config.CODENAMES`). `trial` seats 7 players
(`config.TRIAL_PLAYERS`, the table size in RULES.md), since `bench.toml` has no players.

Display names are derived from the id: `claude-opus-5-5` -> `Opus 5.5`, `claude-fable-5` ->
`Fable 5`, `claude-sonnet-4-6` -> `Sonnet 4.6`. If a model appears more than once, **every** copy
gets a seat letter: `Haiku 4.5 A`, `Haiku 4.5 B`. Names must be unique. Validate: at least 4
players, `1 <= num_moles < players/2`, `job_size <= players`.

Casts. `config/default.toml` (show game, `anonymise = true`): the seven Claude 5 models in this
config order: `claude-fable-5-1`, `claude-fable-5`, `claude-opus-5-5`, `claude-opus-5`,
`claude-sonnet-5-5`, `claude-sonnet-5`, `claude-haiku-5-5`. `config/pilot.toml` (Stage 2 pilot,
same `[game]`, `[limits]`, `[narrator]`): `claude-haiku-4-5`, `claude-haiku-5-5`,
`claude-sonnet-4-5`, `claude-sonnet-4-6`, `claude-sonnet-5`, `claude-haiku-4-5`,
`claude-sonnet-4-6` (repeats allowed; under codenames the seat letters appear only in the log's
`model_name` and the audience labels, never at the table). The narrator is `claude-haiku-4-5`.
Real-name play stays available with `anonymise = false`.

**Fixed roles.** A `[[players]]` entry may carry `role = "mole"` or `role = "crew"`. Either no
player has a role (roles are dealt) or all do, and the number of moles must equal `num_moles`.

**Benchmark trials.** `trial` builds the cast itself and ignores any `[[players]]` in the config:
`--kind mole` = `num_moles` seats of the test model with `role = "mole"` plus the rest as the
reference model with `role = "crew"`; `--kind crew` is the reverse. It forces `anonymise = true`.
`config/bench.toml` holds the same rules as `default.toml`, `anonymise = true`, and no players.
The log's `game_start` and the index row record `trial: {kind, test_model, reference_model}`
(`null` for a `run` game).

**Deals.** So that every model can be given the *same deal*, the seed feeds three independent
streams: `random.Random(f"{seed}:deal")`, `...:cast` and `...:play`.
- *deal* decides, by **seat index** and before any cast is looked at: which seats are moles, the
  first leader seat, the codename for each seat (drawn even when `anonymise = false`, so the
  stream is identical in both modes), the job names (the whole list is shuffled at setup; round
  r uses entry r), each round's clue **recipients** (section 5), and all clue generation.
- *cast* decides which player sits in which seat. With dealt roles it is a shuffle of the roster.
  With fixed roles, mole-role players fill the mole seats and crew-role players the crew seats,
  each in config order (no shuffle), so a trial is fully determined by seed and cast.
- *play* decides whisper pairing order, tie-breaks and fallbacks.
Two games with the same seed and config therefore have the same mole seats, leader order,
codenames, round-1 recipients and round-1 clues whatever models are seated. This is tested.

**Anonymised mode** (`anonymise = true`, used for benchmark runs so players cannot vote on a
model's reputation). Each player's in-game `name` is a heist codename drawn by seeded sample from
a fixed list of at least 16 short, distinct, single-word names (e.g. Ghost, Viper, Duke, Sparrow,
Onyx, Marlow, Quill, Sable, Wren, Fox, Cipher, Lark, Bishop, Juno, Rook, Ember). The codename is
used everywhere a name is used: prompts, schemas, events. No prompt to any player or to the
narrator may contain a model id or a derived model name, and the system prompt must not say which
model the player is. The log still records the truth: every `players` entry has `name` (in-game),
`model` (id) and `model_name` (derived display name, e.g. `Sonnet 4.6 A`), in both modes. When
`anonymise = false`, `name == model_name`. Show games are anonymised too (default.toml); **the
audience always sees the model**: in the transcript and the audience view of `watch` the cast list
maps codename to model and every speaker label reads `Codename (Model)`, e.g. `Vesper (Sonnet 5.5)`.
The table view of `watch` shows codenames only, as the players see them.

## 4. Model client (`llm.py`)

```python
@dataclass
class LLMReply:
    data: dict | None        # parsed structured output
    raw_text: str
    served_model: str | None # first key of modelUsage
    usage: dict              # input, output, cache_read, cache_creation, thinking, cost_usd
    latency_s: float
    error: str | None        # raw error text, at most ~300 characters of it
    error_kind: str | None   # blocked | timeout | cli (the engine adds invalid); None when ok

class LLM(Protocol):
    async def call(self, *, model: str, system: str, prompt: str, schema: dict,
                   phase: str | None = None, player: str | None = None, view=None) -> LLMReply: ...
```

`phase` and `player` are metadata only (the CLI client ignores them); they let `MockLLM` pass
them to its policy. The narrator calls with `phase="recap", player=None`. `view` is passed only to
a client with `wants_view = True` (the scripted bots, section 12): the player's projected visible
events. A client with `needs_prompt = False` lets the engine skip building prompt text (system and
turn prompt are then `""`). `ClaudeCLI` and `MockLLM` have neither flag, so real-model calls and
their prompts are exactly as without bots.

`ClaudeCLI.call` runs exactly this, with a list argv (no shell), `stdin=DEVNULL`, the environment
minus `CLAUDECODE`, and `cwd` set to an empty temp directory:

```
claude -p [--effort <level>] --model <id> --system-prompt <system> --tools "" --strict-mcp-config
  --setting-sources "" --no-session-persistence --output-format json
  --json-schema <schema json> <prompt>
```

**Call controls** (measured 2026-11-10: Haiku 4.5 uncapped took 92 s and 10,395 thinking tokens on
one turn). `ClaudeCLI.from_config(cfg)` takes `[limits] max_thinking_tokens` and `effort`, which
apply to every call, players and narrator alike. `build_argv` adds `--effort <level>` right after
`-p` unless `effort = ""`. `build_env` always removes `CLAUDECODE` and any inherited
`MAX_THINKING_TOKENS`, then sets `MAX_THINKING_TOKENS=<n>` unless the config says -1, so the parent
shell cannot change a game. Both are benchmark conditions: they are in the logged config, in
`game_end.conditions`, in the index row (`conditions`) and in the token report's first line.

- Use `asyncio.create_subprocess_exec`; each client's `asyncio.Semaphore(max_parallel_calls)`
  bounds its concurrency. `run` and `trial` use one client for the game (and the preflight);
  `batch` uses one per game, so its ceiling is `parallel_games * max_parallel_calls`. A call that
  is cancelled (Ctrl-C) kills its child process.
- Parse stdout as JSON. Prefer `structured_output`; else `json.loads(result)`; else error.
  `is_error: true` or a non-zero exit is an error. Kill the process on timeout.
- **Error kinds.** `parse_cli_output` classifies every failure: `blocked` when the result text
  (or stderr / raw output) contains `safeguards flagged`, case-insensitive (the CLI's text is
  `API Error: <model>'s safeguards flagged this message (...)`); `timeout` (set by the client);
  `cli` for a non-zero exit, unparsable output, a spawn failure or any other `is_error`. The engine
  adds `invalid` when a reply fails validation. An `is_error` reply's error text (which lands in
  the turn's `rejections`) is `is_error: <result> (subtype <subtype>): <first entry of errors, cut
  to 300 characters>`, so a failure such as `error_max_structured_output_retries` (where `result`
  is null) says why; the `safeguards flagged` check also runs over the `errors` entries.
- Usage: from `modelUsage[served]`: `inputTokens`, `outputTokens`, `cacheReadInputTokens`,
  `cacheCreationInputTokens`, `thinkingTokens`, `costUSD`. Sum across keys if several.
- If the served model differs from the requested one, record it and warn on stderr once.
- No API, no keys, no other provider. Do not add flags beyond those above.

`MockLLM(seed)` returns a random **valid** reply for any schema (walk the schema: enums, arrays
with min/max items and uniqueness, strings, booleans), so its replies are in the wire format (the
move under `move`, section 6), like a real model's; policies and the scripted bots reply in it too. It accepts an optional `policy` callable
`(model, system, prompt, schema, phase, player) -> dict | None` so tests can script behaviour. It
records every `(system, prompt)` it was given so tests can inspect prompts. Mock usage numbers
are zero.

The engine wraps calls in `ask(player, phase, ...)`:
1. call; validate the reply against the schema **and** the semantic rules in section 6;
2. on failure retry up to `retries` times, appending a line to the prompt:
   `Your previous reply was rejected: <reason>. Reply again with valid JSON.`;
3. **blocked attempts** (the model's safety filter refused the call) are different: a blocked
   attempt gets exactly **one** more attempt with the identical prompt (no rejection text, the
   model did nothing wrong), whatever `retries` says, and it does not use up a retry. A second
   block ends the turn with the fallback. Nothing is reworded and no other model is substituted;
4. if still failing, substitute the documented fallback for that phase and mark the turn
   `fallback: true` with `fallback_reason` = the last failure's kind (`blocked` | `invalid` |
   `timeout` | `cli`) (stats will exclude it). The game always finishes.
Every attempt's usage is counted, including failed and blocked ones.

**Preflight** (`preflight.py`, `python3.11 -m inside_job preflight [--config ...]`). Plays a mock
game in memory with the config's cast, takes two calls from it (system prompt, turn prompt,
schema): the first mole discussion call and the first vote call, and sends each once to each
distinct model in the cast and to the narrator model (in parallel, bounded by
`max_parallel_calls`). The vote call is there because a schema problem can show on one phase only
(claude-sonnet-4-5 failed its vote and clue turns, which the discussion call alone did not show;
section 6). A call that is
blocked or errors is tried once more, unchanged. It prints one row per model and phase: ok /
blocked / error, tries, latency, output and thinking tokens, and exits 2 naming every model and
call blocked or erroring on both tries; a model passes only if both its calls pass.
`run` and `trial` run it first (not with `--mock`; skipped with `--no-preflight`; `--force` starts
anyway). Tests swap `__main__.make_client` for a fake client.

## 5. Clues (`clues.py`)

A *world* is a set of `num_moles` players that could be the moles. For a recipient, the
**consistent worlds** are those compatible with: publicly revealed roles, the number of moles
still in, "I am not a mole" (applied for mole recipients too, so their clues look like crew clues),
and every clue that recipient has already received.

Candidate clues are over alive players other than the recipient:

| kind | text | args |
|---|---|---|
| `at_least_one` | "At least one of A and B is a mole." | 2 players |
| `at_least_one_of_three` | "At least one of A, B and C is a mole." | 3 players |
| `exactly_k_of_three` | "Exactly k of A, B and C are moles." | 3 players, k in 0..min(3, num_moles); worded "None of A, B and C is a mole." / "Exactly one of A, B and C is a mole." / "Exactly two of ... are moles." / "All three of ... are moles." |
| `same_side` | "A and B are on the same side." | 2 players |
| `different_sides` | "A and B are on different sides." | 2 players |
| `not_mole` | "A is not a mole." | 1 player |

**Recipients (v0.3: scarce intel).** Each round, before that round's clues are generated, the
engine draws who is dealt intel from the **deal** stream, looking only at the alive list in seat
order (blind to role): `k` uniformly from `[clue_recipients - spread, clue_recipients + spread]`,
clamped to `[0, alive]`, then `k` alive players by `random.sample` (`clues.draw_recipients`).
`clue_recipients = 0` means every alive player and uses no randomness (exactly v0.2 dealing).
Recipients get `clues_per_round` clues each, generated as below in seat order; every other alive
player gets one `none` clue ("No new intel this round."), so every alive player still has at least
one private `clue` event per round and a recipient whose generator found nothing looks exactly
like a non-recipient. Receipt is private: no prompt, public event or recap says who got a clue or
how many were dealt. The rules text gives only the range (`config.recipient_range`), e.g.
"between two and four of the players still in". The engine-only `clue_deal` event records the
truth. Any player may table a clue card whether or not they were dealt one.

Generation: enumerate candidates, keep those **true in the real world**, compute for each the
fraction of the recipient's consistent worlds that survive it. Discard candidates that remove
nothing (ratio 1.0) or that leave fewer than 2 worlds. Choose (seeded) the candidate whose ratio
is closest to the target for `clue_strength`: weak 0.8, normal 0.6, strong 0.4, breaking ties at
random. If no candidate qualifies the clue is `{"kind": "none", "text": "No new intel this round."}`.
Each clue is a dict `{kind, players, k?, text}`. `clue_is_true(clue, moles)` is a pure function and
is property-tested over many seeds.

## 6. Turns

Every reply has the same outer shape; `move` varies by phase.

```json
{
  "confessional": "private, to camera",
  "public": "public statement or whisper message; \"\" in private phases",
  "claims": [{"text": "claim made in `public`", "truthful": true}],
  "memory": "private note to self for the next turn",
  "move": { }
}
```

**Wire name `move`, log name `action`.** The nested object is called `move` in the schema sent to
the model and in every text the model reads (system prompt, turn prompts, rejection lines:
`move.vote`, `move.suspicion`, ...); the name is the one constant `schemas.WIRE_MOVE`. Inside the
engine, in the log, in transcripts and in everything that reads logs it is `action`, as before:
`clean_reply` validates the reply against the wire schema and stores the object under `action`, so
a turn event still has `action` and the log format is unchanged. Why: measured 2026-11-10,
claude-sonnet-4-5 answered vote and clue turns with its whole, correct reply wrapped in an extra
`action` object (`{"action": {"confessional": ..., "action": {...}}}`); the CLI rejected it five
times (`error_max_structured_output_retries`), 0 of 8 turns succeeded. With the object renamed to
`move` in the schema and prompts, 5 of 5 succeeded first time. A reply that puts the move under
another key is rejected with `reply is missing 'move': put this phase's choices in an object named
'move', ...`.

All five keys are required; `additionalProperties: false` everywhere. The `confessional` property
carries **no `description`** in the schema (`{"type": "string"}`): measured 2026-11-10, that one
schema description (`"private, to camera: your real thinking"`) was what the safety filter on
Fable 5.1, Fable 5, Opus 5 and Sonnet 5.5 rejected; the system prompt already says in plain words
what the confessional is. No other field or description changed. Name fields are JSON-schema
enums built per call from the currently valid targets, so most invalid actions are impossible.
**Limits (Stage 2).** Over-long text is trimmed, never rejected. The limit told to the model is
the configured one (`public_words` etc.); the **hard cap** the engine applies is
`ceil(limit * (1 + word_grace))` (`schemas.hard_cap`: 60 -> 69, 70 -> 81, 50 -> 58, recap 100 ->
115 at 0.15; `word_grace = 0` makes the limit itself the cap). Text at or under the hard cap is
never changed beyond stripping outer whitespace. Longer text keeps its first `hard cap` words
(re-joined with single spaces), cut back to the last sentence end among them (a word ending in
`.`, `!` or `?`, optionally followed by closing quotes or brackets: `" ' ” ’ ) ] } »`) **if** that
keeps at least half the hard cap; otherwise all `hard cap` words are kept and `…` is appended to
the last one. This applies to the confessional, public / whisper text, memory, every claim text
(public or whisper cap) and the narrator recap (`recap_words`). The turn records `truncated`
(any field trimmed) and `truncated_fields`, the trimmed fields in the order `confessional`,
`public`, `memory`, `claims` (`[]` when none, and on fallback turns).

| phase | who | order | `public` | `action` | semantic checks | fallback |
|---|---|---|---|---|---|---|
| `clue` | all alive | parallel | must be "" | `{"whisper_with": <other alive name> or "none", "suspicion": {...}}` (no `whisper_with` if whispers off) | — | none; uniform suspicion |
| `whisper` | pair members, alternating, initiator first | sequential per pair; pairs in parallel | the message (seen by partner only) | `{"clue_cards": [...], "suspicion": {...}}` | non-empty message; cards well-formed | "(says nothing)", no cards; uniform suspicion |
| `pick` | leader | — | announcement | `{"team": [names]}` exactly the team size (`job_size`, or `job_size_small` once 4 or fewer are alive, never more than alive), unique | unique, alive | leader + seeded random |
| `job` | moles on the team | parallel | "" | `{"choice": "help" \| "sabotage"}` | — | help |
| `discuss` | all alive | sequential, from left of leader, leader last, repeated `discussion_passes` times | statement | `{"accuse": <other alive name> or "none", "challenges": [statement ids from this round], "clue_cards": [...], "job_claim": "helped" \| "sabotaged" \| "none", "suspicion": {...}}` | ids exist, not own; cards well-formed; `job_claim` must be "none" unless the speaker was on this round's team | accuse none, no cards, no claim; uniform suspicion |
| `vote` | all alive | parallel | one-line reason, revealed with the vote | `{"vote": <other alive name>, "suspicion": {...}}` | — | seeded random vote; uniform suspicion |
| `cut_pitch` | surviving crew | sequential, seat order | pitch | `{}` | — | "(no pitch)" |
| `cut_vote` | surviving crew | parallel | "" | `{"finalist": <other survivor>}` | — | seeded random |
| `finale_pitch` | 2 finalists | sequential, alternating, `finale_exchanges` each | pitch | `{"stated_intent": "split" \| "steal" \| "unstated"}` | — | unstated |
| `finale_choice` | 2 finalists | parallel | "" | `{"choice": "split" \| "steal"}` | — | split, marked fallback |

**Suspicion** (in `clue`, `whisper`, `discuss` and `vote` actions, `schemas.SUSPICION_PHASES`:
a reading before and after every statement a player hears, at about 50 output tokens a turn and
no extra calls). `suspicion` is an object with one required integer property, 0 to 100, for **every other
alive player**: the percent chance the speaker gives that this player is a mole. It is never
shown to anyone. The engine does not require the numbers to sum to anything; it logs them raw
(stats normalise later). Crew are asked for their honest belief. Moles know the truth, so they
are asked a different question with the same field: how suspicious they think **the crew** find
each player right now (their read of the table). The `turn` event records which question was
asked as `suspicion_kind: "belief" | "table_read"`. Fallback: every value set to
`round(100 * moles_remaining / others_alive)`, turn marked `fallback`.

**Clue cards and job claims** (the claims the engine can check without trusting self-report).
`clue_cards` is an array of 0 to 2 objects `{"kind": ..., "players": [names], "k": int}` using the
clue kinds of section 5 (not `none`). `players` are other players, alive or out, never the
speaker; `k` is required by the schema and ignored except for `exactly_k_of_three`. Well-formed
means the right number of distinct players for the kind and `0 <= k <= 3`; a malformed card is a
rejection (retry). The engine renders each card with the standard clue wording and shows it next
to the statement, publicly in `discuss` and to the partner in `whisper`, as
`claims clue: "At least one of A and B is a mole."`. A card is a claim that the speaker was dealt
that clue. The engine records, on the `turn` event under `checks` (engine-only, never in any
prompt):

```json
"checks": {
  "clue_cards": [{"card": {...}, "text": "...", "held": true, "true_in_world": true}],
  "job_claim": {"claimed": "helped", "actual": "sabotage", "lie": true}
}
```

`held` = the speaker really received a clue with the same kind, the same set of players and (for
`exactly_k_of_three`) the same k. `true_in_world` = `clue_is_true(card, moles)`; a fabricated card
can happen to be true. `job_claim` is `null` when "none". The prompt tells players that cards are
optional, that the table cannot tell a real card from a fake one, and that the free-text `claims`
tags are still required for everything they say.

Statement ids: every non-empty public statement in `pick`, `discuss`, `vote`, `cut_pitch`,
`finale_pitch` gets `R<round>-S<n>` (n counts from 1 within the round; The Cut and the finale share
one `F-S<n>` sequence). Fallback placeholders ("(no pitch)") get no id. Ids are shown in prompts
next to each statement so `challenges` can reference them.

Schema details: in the silent phases (`clue`, `job`, `cut_vote`, `finale_choice`) `public` is
`{"enum": [""]}` and `claims` has `maxItems: 0`; a stray statement there is coerced to `""` /
`[]` rather than rejected. `job_claim`'s enum is just `["none"]` for a player who was not on the
team (the semantic check still applies). Duplicate `challenges` ids are silently de-duplicated.

### Phase mechanics

- **Seats and roles:** as "Deals" in section 3: mole seats and the first leader seat come from
  the deal stream, the seating from the cast stream. Leadership passes clockwise to the next
  alive player each round.
- **Whisper pairing:** collect requests. Mutual requests pair first (in seat order; the
  earlier seat is the initiator); then remaining requests in seeded random order pair if both
  players are still free (the target cannot refuse; the requester is the initiator). Stop at
  `whisper_pairs_max`. The public event lists the pairs only, initiator first. The pairs'
  conversations run in lockstep: step k of every pair is asked in parallel, then written in
  pair order.
- **Job:** crew on the team are recorded as `help` without a call. `sabotages` = number of
  sabotage choices; the job is blown if >= 1, otherwise clean. Running clean-job and blown-job
  counts are public and appear at the top of every prompt as the score.
- **Vote:** plurality. Tie: if the leader's vote is for one of the tied players, that player goes;
  otherwise seeded random among the tied. The eliminated player's role is revealed.
- **End checks, in this order after each job and each vote:** blown jobs >= `sabotage_target`
  -> moles win (`sabotage`); clean jobs >= `clean_target` -> crew win (`jobs_clean`); no moles
  alive -> crew win (`moles_out`); two players alive with a mole -> moles win (`final_two`);
  `max_rounds` reached with a mole alive -> moles win (`clock`). A job that reaches either target
  ends the game before that round's discussion. `final_two` and `clock` are backstops that the
  default 7-player settings never reach; keep and test them with other settings. `clock` is only
  checked after a vote (checking it after the last round's job would skip that round's
  discussion and vote).
- **Recap:** after each vote, one narrator call (plain schema `{"recap": string}`) summarises the
  round from **public events only**, neutrally, in `recap_words` (trimmed as under Limits). On
  failure the recap is "".
  The narrator gets a single attempt (no retries), except that a blocked attempt is tried once
  more, unchanged, as for players.
- **The Cut / finale:** as RULES.md. Finalists always come from the winning side's survivors:
  more than two -> The Cut (crew side; for moles with `num_moles > 2`, the same procedure);
  exactly two -> those two; exactly one -> takes the pot, no finale. Losing-side players never
  reach the finale even if still in. Payoffs: split/split = pot/2 each; split/steal = 0 / pot;
  steal/steal = 0 / 0; lone survivor = pot.

## 7. Prompts (`prompts.py`)

**System prompt** (identical for a player all game, so it can cache): who you are (display name
or codename),
that all players are AI models playing a consensual bluffing game in the spirit of Werewolf or
The Resistance where in-game deception is expected and is the point, the full rules (v0.3: the
intel range, "between two and four of the players still in ... nobody is told how many clues went
out or who got them", or "every player" when `clue_recipients = 0`; that anyone may table a card,
whether or not they were dealt a clue; suspicion at the clue, the vote and every whisper and
discussion turn), your role
(and for moles: your partner's name), the three incentives from RULES.md, the reply contract
(what each field is, that confessional / tags / memory are never shown to other players and must
be candid and accurate, tag *every* factual claim including claims about your own role, clue,
and actions), and style: short, vivid, in character as a member of a heist crew, no markdown,
never mention being an AI assistant or the JSON format in public statements. The word limits are
stated with each field, and the style paragraph ends (Stage 2): "Keep within the word limits:
text past a limit is cut back to its last complete sentence, so finish what you are saying inside
the limit." The grace is never stated.

**Turn prompt** = the player's view, then the phase instruction. The view is built **only** from
log events the player may see (section 8):

1. Table: the score first (`Clean jobs 1/3 - Blown jobs 2/3`), then seat order, who is alive,
   who is out and their revealed roles, the leader.
2. Earlier rounds, each as: engine fact digest (whisper pairs; leader, team, sabotage count;
   every vote and who went with what role) + the narrator recap.
3. Your private file: every clue you have received (with round), your whisper transcripts
   (earlier rounds trimmed to the last two messages), your job choices, your latest memory note.
4. This round so far in full: your clue, whisper pairs, your whisper, the pick, the job result,
   every public statement with its id and speaker, with any clue cards and job claim shown
   beside it. Clue cards from earlier rounds are kept in the fact digest (who claimed what), since
   they are what players reason from.
5. The phase instruction: what to do now, the word caps, the valid choices (and, in the four
   suspicion phases, what to rate). Fields of the nested object are named by their wire path
   (`move.vote`, `move.suspicion`, `move.clue_cards`, ...; section 6), and the system prompt's
   reply contract calls it `move`. No prompt text says `action`.

Moles additionally see their partner's job choices (they are a team) but **not** the partner's
confessionals, clues, memory, or whispers.

## 8. Log (`log.py`)

One JSON object per line. Common fields on every event:

```
seq      int, from 0, strictly increasing
ts       ISO-8601 UTC
game_id  str
round    int (0 before round 1; rounds count from 1; finale events keep the last round number)
phase    setup | clue | whisper | pick | job | discuss | vote | recap | cut | finale | end
type     see below
vis      "public" | "private" | "pair" | "engine"
```

`private` events carry `player` and are visible to that player only; `pair` events carry
`players: [a, b]`; `engine` events are ground truth that no player ever sees. The view builder
must go through one function, `visible_to(event, player) -> bool`, and tests assert privacy on it.

| type | vis | fields |
|---|---|---|
| `game_start` | engine | `rules_version`, `log_version`, `seed`, `config` (full), `anonymised` (bool), `trial` (`{kind, test_model, reference_model}` or null), `batch` (the `batch` name or null; absent in logs before Stage 2), `players: [{name, model, model_name, seat, role}]`, `moles: [names]`, `mole_seats`, `first_leader` |
| `table` | public | `seats: [names in seat order]`, `num_moles`, `pot` |
| `role` | private | `player`, `role`, `partners: [names]` |
| `round_start` | public | `leader`, `alive: [names]`, `clean_jobs`, `blown_jobs` |
| `clue_deal` | engine | `recipients: [names in seat order]`, `k` (phase `clue`; written after `round_start`, before the round's `clue` events) |
| `clue` | private | `player`, `clue: {kind, players, k?, text}` (`kind: "none"` for a player not dealt intel) |
| `turn` | see below | `player`, `model`, `turn_phase`, `confessional`, `public`, `claims`, `memory`, `action`, `checks` (discuss and whisper only), `suspicion_kind` (clue, whisper, discuss and vote), `statement_id` (or null), `truncated`, `truncated_fields` (Stage 2; absent in older logs), `fallback`, `attempts`, `served_model`, `usage`, `latency_s`, `rejections`, `error_kinds` (one per failed attempt), `blocked` (count of blocked attempts), `fallback_reason` (null unless `fallback`), `partner` (whisper only), `pass` (discuss only), `shared_with` (job only) |
| `whisper_pairs` | public | `pairs: [[a, b], ...]`, `requests: {name: target or "none"}` is **not** included here |
| `whisper_requests` | engine | `requests: {name: target or "none"}` |
| `job_pick` | public | `leader`, `team`, `job_name` (flavour, e.g. "Loop the lobby cameras") |
| `job_result` | public | `team`, `sabotages`, `blown`, `clean_jobs`, `blown_jobs` |
| `job_choices` | engine | `choices: {name: "help" \| "sabotage"}` |
| `vote_result` | public | `votes: {voter: target}`, `tally`, `tied: [names]`, `tiebreak: null \| "leader" \| "random"`, `eliminated`, `role` |
| `recap` | public | `text`, `model`, `usage`, `served_model`, `latency_s`, `error`, `error_kind`, `attempts`, `blocked`, `fallback_reason` (the error kind when `text` is "" because of a failure) — everything but `text` is stripped from every projection |
| `cut_result` | public | `votes`, `tally`, `finalists`, `tiebreak` |
| `finale_result` | public | `finalists`, `choices: {name: split \| steal}`, `stated: {name: split \| steal \| unstated}`, `payouts: {name: int}` |
| `game_end` | public | `winner: crew \| moles`, `reason: jobs_clean \| moles_out \| sabotage \| final_two \| clock`, `clean_jobs`, `blown_jobs`, `rounds`, `survivors`, `payouts` (all players, 0 default), `usage: {by_model: {...}, total: {...}}`, `calls`, `fallbacks` (turns), `blocked` (total blocked attempts), `conditions: {max_thinking_tokens, effort}`, `wall_s` — `usage` and `blocked` are stripped from projections |

A `turn` is written as **one** event with `vis: "engine"` holding everything, and its
player-visible parts are derived by `visible_to` / a `public_part(event)` helper rather than
duplicated: the `public` text, `statement_id`, and the public parts of `action` are public for
phases `pick`, `discuss`, `vote` (revealed together when the vote resolves), `cut_pitch`,
`finale_pitch`; visible to the pair for `whisper`; the speaker always sees their own whole turn.
Public parts of `action`: `team` (pick), `accuse`, `challenges`, `clue_cards` and `job_claim`
(discuss), `vote` (vote), `stated_intent` (finale_pitch); `clue_cards` in a whisper are visible to
the pair. Never public: `checks`, `confessional`, `claims`, `memory`, `suspicion`,
`whisper_with`, job `choice`, `finalist` until `cut_result`, finale `choice` until `finale_result`.

Engine-side fields (v0.3), never in any player's projection, **the speaker's own included**
(`log.ENGINE_ONLY_TURN_FIELDS`): `checks`, `blocked`, `fallback_reason`, `error_kinds`,
`rejections`. On public non-turn events `project` strips `log.ENGINE_ONLY_EVENT_FIELDS`
(`blocked`, `fallback_reason`, `error_kind`, `error_kinds`, `usage`, `attempts`, `served_model`,
`latency_s`, `model`, `error`), which affects `recap` and `game_end`. `clue_deal` is an engine
event and never visible. `GameLog` writes and flushes every event as it happens and can call a
`listener(event)` after each write (used by `run --watch`).

Turn fields added in Stage 1: `turn_phase` is the phase name from the section 6 table
(`clue` ... `finale_choice`; the event's `phase` is the coarser log phase, so `cut_pitch` and
`cut_vote` log as `cut`, `finale_pitch` and `finale_choice` as `finale`). `pass` is the discussion
pass (1-based). `rejections` lists the reason for every failed attempt, in order. `shared_with`
on a mole's `job` turn names the other moles, who may see that turn's `choice` (and nothing
else); this is how `visible_to` implements "moles see their partner's job choices" without
consulting the mole list. The `model` field of a turn is never part of its public projection,
and `checks` is stripped even from the speaker's own view. `truncated` and `truncated_fields`
are likewise never in another player's projection (only the speaker sees them, in their own turn;
no prompt renders them).

`game_end.usage.by_model` is keyed by **requested** model id; each entry has `calls` (every
attempt, failed and blocked ones included; narrator calls count under the narrator model), the six
usage keys, `blocked` (blocked attempts), `fallbacks` (turns that fell back, plus failed recaps for
the narrator model) and `served` (the served model ids seen). `total` has the same keys summed.

`games/index.jsonl` gets one row per finished game: `game_id`, `seed`, `rules_version`,
`anonymised`, `trial`, `batch` (name or null), `spoiled` (true only for a `batch` game that tripped
the stop rule; false otherwise; rows before Stage 2 have neither), `winner`, `reason`, `clean_jobs`, `blown_jobs`, `rounds`, `players` (name, model, model_name, role, seat,
eliminated_round or null, payout),
`finale` (`{finalists, choices, stated}` or null), calls, fallbacks, `blocked`, `by_model`
(`{model: {calls, blocked, fallbacks}}`), `conditions` (`{max_thinking_tokens, effort}`), `tokens`
(usage totals), `wall_s`, and `log` (the log path).

## 9. Transcript (`transcript.py`)

Markdown, readable top to bottom by a person:

- Header: game id, rules version, seed, cast table (seat, name, model, role; codename -> model
  in an anonymised game), result line, the call conditions. Every speaker label in an anonymised
  game is `Codename (Model)`.
- Per round, under Clues: who was dealt intel (`clue_deal`), then each player's clue.
- Per round: clues; whispers (who, then the messages); the pick and job result; discussion; the
  vote table and reveal; the recap.
- Each turn shows the public statement first, then the confessional as a blockquote marked
  private. A fallback turn is marked with its reason, e.g. `[FALLBACK: blocked]`; a turn that was
  blocked once and then answered shows `1 blocked`; a trimmed turn shows `truncated: public, memory`
(older logs: `truncated`). Claims tagged false are listed under the statement with a clear `LIE:` marker;
  challenges are shown as "calls out R2-S3". Clue cards are shown with the engine's verdict,
  `CLUE CARD (real)` or `CLUE CARD (FAKE)`, and a job claim that contradicts the truth as
  `JOB CLAIM (FALSE)`.
- The score (clean / blown) after every job. For a trial, the header names the kind, the test
  model and the reference model.
- The Cut and finale; final payouts.
- Token report table by model (with `Blocked` and `Fallbacks` columns), plus totals, calls,
  fallbacks, wall time. `transcript.marks`, `top_suspect`, `fallback_tag` and `labeller` are shared
  with the live renderer.

## 10. Tests (mock model, no real calls)

- Full mock games across 200 seeds finish, with a valid `game_end`, strictly increasing `seq`,
  and every line valid JSON.
- Scripted games reach each ending: `jobs_clean`, `moles_out` (with and without The Cut),
  `sabotage` (two surviving moles -> finale between them; one -> takes the pot), and the
  backstops `final_two` and `clock` under non-default settings; payoffs for all four split/steal
  combinations and the lone-survivor case. Moles that never sabotage lose by `jobs_clean`.
  Finalists are always on the winning side.
- Team size: `job_size` with 5 or more alive, `job_size_small` with 4 or fewer.
- **Clue cards:** a card matching a held clue (players in any order) is `held: true`; any other
  is `held: false` with `true_in_world` computed; malformed cards are rejected and retried;
  `job_claim` is checked against `job_choices`; `checks` never appears in any prompt; cards are
  public in `discuss` and pair-only in `whisper`.
- **Deals and trials:** the same seed with different casts gives identical `mole_seats`, first
  leader, codenames and round-1 clues; `trial --kind mole` seats the test model in exactly the mole
  seats and `--kind crew` in exactly the crew seats; trials are anonymised; `trial` is recorded
  in `game_start` and the index row.
- Vote tie-break: leader's vote, then random.
- Whisper pairing: mutual first, one whisper per player, pair cap, off when `whispers = false`.
- Clues: always true; never from an empty candidate set without the `none` fallback; recipient
  never named; consistent-world logic.
- **Privacy:** a policy plants a unique token in every confessional, memory note, claim, whisper
  message, clue request and private action; assert no token ever appears in a prompt given to a
  player who must not see it (whisper tokens appear only for the partner). Assert no crew prompt
  contains the mole list, and that the narrator prompt contains no private tokens. No prompt
  contains another player's `suspicion` numbers.
- **Anonymised mode:** with `anonymise = true`, no system or turn prompt (players or narrator)
  contains any model id, family name (Haiku, Sonnet, Opus, Fable) or derived model name; names are
  unique codenames; the log's `players` still carry `model` and `model_name`; same seed gives the
  same codenames.
- **Suspicion:** schema requires a 0-100 integer for every other alive player in `clue`,
  `whisper`, `discuss` and `vote`; crew get `belief`, moles get `table_read`; fallback is uniform
  and flagged. The `confessional` property has no `description` in any phase's schema.
- **Scarce intel (v0.3):** `k` always inside the range and never above alive; non-recipients get
  `none`; one clue event per alive player per round; the same seed gives the same round-1
  recipients whatever the cast (both modes); `clue_recipients = 0` reproduces v0.2 dealing (checked
  against a hand replay of the deal stream); the rules text states the range, not the count.
- **Privacy, v0.3 additions:** `clue_deal`, `blocked`, `fallback_reason`, `error_kinds`,
  `error_kind`, `rejections` are absent from every projection (speaker's own included; recaps and
  `game_end` stripped); a game with blocked calls planted passes the full token check and no prompt
  mentions a block; every line of every prompt that mentions intel names no other player (who got
  a clue never leaks), and no prompt states the number dealt.
- **Call controls:** argv for each effort level (`--effort` right after `-p`, nothing when ""); env
  for cap 2000, 0 and -1, an inherited `MAX_THINKING_TOKENS` overridden or removed; validation;
  conditions reach `game_end`, the index row and the token report.
- **Blocked calls:** classification of `blocked` (case-insensitive), `cli` and `timeout` from canned
  output; a blocked turn gets exactly two identical attempts with no rejection text, then falls
  back with reason `blocked`; a block does not use up a retry; counts reach the token report,
  `game_end` (per model and total), the index row and the transcript (`[FALLBACK: blocked]`); the
  narrator's block retry; preflight against a fake client that blocks (or errors on) one model
  exits 2 and names it, sends one identical genuine mole discussion call per distinct model plus the
  narrator, retries the failing one once; `run` refuses to start and writes no log; `--mock` skips it.
- **Solver, bots, live:** see sections 11 to 13.
- Retry and fallback: invalid reply -> retry with the rejection line -> fallback flagged.
- Client: argv construction, env has no `CLAUDECODE`, parsing of a recorded real reply
  (fixture below), timeout handling — with the subprocess stubbed.
- Transcript renders for every ending without error and contains every player name.
- **Stage 2** (`tests/test_stage2.py`): hard caps; trimming (under / at the cap unchanged, cut to the
  last sentence end, the half-cap rule, one long sentence gets `…`, closing quote or bracket after
  `.`/`!`/`?`, grace 0 is a hard limit); `clean_reply` and game turns report `truncated_fields`
  (recaps trimmed too) with the same visibility as `truncated`; old turns without the field still
  render; `word_grace` validation and the three config files; the system prompt sentence and no
  grace in it; `batch`: the name on `game_start` and the index row (`run` games null), resume skips
  finished seeds only for the same name, the stop rule (exit 3, spoiled row, resume command, running
  games finish, threshold), a crashed game's log has no `game_end` and is replayed, preflight once
  and never with `--mock`, `--parallel-games 1` and `3` give identical normalised logs and equal
  `run`'s, at most `parallel_games * max_parallel_calls` calls in flight (real `ClaudeCLI` clients over
  a fake subprocess), and Ctrl-C exits 130 with the resume command.
- **`report`** (`tests/test_report.py`): the share format and Wilson interval for known counts;
  Brier for known probabilities; on hand-built logs: a mole with one false claim (by configured
  model, served label ignored, fallback turns ignored), fake cards tabled and whispered and false
  job claims, a unanimous vote, a 2-2 split, a fallback vote left out, both moles' agreement, a
  finale with a broken promise (and `unstated`, a fallback choice, no finale), the last reading of
  a round against a hand-computed ideal, an inconsistent posterior scored and counted; verdict
  thresholds and TOO FEW GAMES. On mock batches: every section, `--write` equals stdout, unknown
  batch and only-spoiled batch exit 2, spoiled and cut-off games (with a half-written line)
  counted in section 1 only, the latest row of a replayed seed used, 10 games give PASS / FAIL.

Recorded real reply shape for the client fixture (trimmed):

```json
{"is_error": false, "result": "{\"public\":\"Hello\",\"vote\":\"A\"}",
 "structured_output": {"public": "Hello", "vote": "A"},
 "total_cost_usd": 0.002404,
 "usage": {"input_tokens": 1439, "output_tokens": 193},
 "modelUsage": {"claude-haiku-4-5": {"inputTokens": 1439, "outputTokens": 193,
   "cacheReadInputTokens": 0, "cacheCreationInputTokens": 0, "thinkingTokens": 115,
   "costUSD": 0.002404}}}
```

## 11. Ideal reasoner (`solver.py`)

Pure functions, no model calls; used by `solve`, the bots and (later) the stats page as the
ceiling for Read. A world is a frozenset of `num_moles` names.

- `table_worlds(players, num_moles, revealed, cards, jobs) -> [world]`: every mole set consistent
  with public information. `cards` are `(speaker, clue)` pairs, `jobs` are `(team, sabotages)`.
  A world is consistent when it matches the revealed roles, every card tabled by a player **not
  in the world** is true in it (a mole's cards bind nothing in the world where they are a mole),
  and every blown job with `s` sabotages has at least `s` members of the world on its team.
- `player_worlds(..., player=, own_clues=, pair_cards=)`: the same plus "I am not a mole", the
  player's own real clues (`none` ignored) and the cards shown to them in whispers (which bind like
  public cards).
- `posterior(worlds, players, fallback=None) -> Posterior`: a dict `{name: share of worlds
  containing name}` (uniform over worlds) with attributes `consistent` and `worlds`. If no world is
  consistent and `fallback` worlds (reveals and jobs only) are given, they are used and
  `consistent` is False. `table_posterior(inputs)` applies that fallback for either viewpoint.
- `from_log(events, upto_seq=None, viewpoint="table" | <name>)` builds the inputs from a log
  through `visible_events` only (cards from discussion statements; for a player also their own
  clues and partner whisper cards); `inputs_from_view` does the same from an already projected view.

The ideal reasoner is a ceiling, not a player: it assumes crew cards are honest and does no
reading of behaviour.

**`solve`** deals clues only (no play): per deal (`random.Random(f"{seed}:{deal}")`) it samples
the moles, then each round draws the recipients and deals clues with the engine's own functions,
measures the table (every crew clue pooled as an honest card; mole cards bind nothing) and one
crew member alone (own clues), then one random alive player leaves and their role is revealed. It
prints per round the mean number of consistent worlds and the share of deals solved (exactly one
world left) for both. Reproduces an earlier scratch script (`solve_sim.py`, not in the repo): at v0.2 settings (`--set
clue_recipients=0 --set clue_strength=normal`) 71.2% solved by round 2 and 92.8% by round 3; at
v0.3 defaults 2.0% and 20.2% (400 deals, seed 0). Tests: the default round-3 share is below 40%
and the v0.2 one above 80% (200 deals); worlds logic on hand-built cases (mole card ignored in its
own world, blown-job constraint, reveal constraint, whisper cards, inconsistent fallback); `from_log`
viewpoints and `upto_seq`.

## 12. Scripted bots (`bots.py`)

Zero-token players for tuning the dials. They show whether a setting is degenerate, not how real
models will play.

**Hand-off.** `BotLLM` sets `wants_view = True` and `needs_prompt = False`. The engine then
builds no prompt text at all (system prompts and turn prompts are `""`; the schema is built as
usual) and passes `view=` — the player's events through `visible_to` / `project`, exactly what a
prompt is built from, kept incrementally per player (`Game.view_for`). Bots read only that view and
the reply schema (valid choices); the game rules come from the config, as a real player's come from
its system prompt. They never see engine events, other players' private events or prompt text.
`ClaudeCLI` and `MockLLM` never receive a view, so real-model prompts are unchanged.

Crew (`--crew logician`): tables every real clue it holds (each once, up to two a turn, most
recent first) in discussion and shows its real clues to its whisper partner; suspicion =
`player_worlds` posterior x 100; whispers with its least suspected player; as leader picks
itself plus the least suspicious; accuses and votes for the most suspicious (seeded tie-break);
claims "helped" when on the job (true). `--crew-skill` (default 0.7): on each decision (whisper
partner, team, accusation, vote), with probability `1 - skill` it acts at random instead.
Suspicion is always its real posterior.

Moles (`--moles`): `always` sabotages whenever on a job; `never` never does; `smart` sabotages
when on a job, but if both moles are on the team only the lower seat does. All three share smart's
other behaviour: as leader picks itself plus the crew the table suspects least, never its partner;
accuses and votes for the table's leading crew suspect (`table_worlds` posterior), never its
partner; whispers with a random non-partner; `table_read` = `table_worlds` posterior; claims
"helped" when on the job (tagged false when it sabotaged). `--mole-cards decoy` (default): one fake
card a round in discussion, true in a world where crew members are the moles (plus any revealed
mole). The mole keeps the same decoy world while it stays consistent with its own earlier decoys,
preferring one the public evidence still allows, and picks the card (not already tabled, not
naming itself) whose share of surviving table worlds is closest to the `clue_strength` target,
preferring cards false in the real world. `none`: no cards. Cards are tagged false in `claims`.
Every bot reply is complete and valid (stock public lines); the finale is split/split.

**`bots` command.** Every cell of `--sweep` (cartesian product of the given values, after `--set`)
plays seeds `seed .. seed+games-1` (paired across cells), logs in memory, no transcript. One row
per cell: games, crew win rate with a 95% Wilson interval, end-reason mix, mean rounds, mean clean
and blown jobs, sabotage rate per mole-on-job, share of games where a mole was voted out by round 2,
the ideal reasoner's "solved by round 1..4" share on the cards actually tabled plus the public job
results and reveals (a game that ended earlier keeps its last state), and games per second. With
`--out DIR` it appends `bots-cells.jsonl` (one row per cell) and `bots-games.jsonl` (one per game);
without it nothing is written. Speed target 20+ games a second; measured about 55-63.

Tests: every mole type with decoy cards completes 50 games (and `none` 10) with no fallbacks and no
retries; an audit hook asserts before every bot turn that the view equals exactly the
`visible_to`/`project` events for that player (no `clue_deal`, `checks` or `blocked`); `never`
moles win under 15% (100 games); `always` sabotage rate 1.0 and `smart` never puts two sabotages
on one job; decoys are fake and tagged false, logician cards are real; identical seeds give
identical logs; Wilson interval; the CLI prints one row per sweep cell and writes nothing without
`--out`.

## 13. Watching a game (`live.py`)

`watch` follows a growing log (`follow`: complete lines only, a partial line waits for its
newline, each event printed once) and exits after `game_end`. `--latest` picks the newest
`*.jsonl` (not `index.jsonl`) in `--out`, waiting for one to appear. A finished game is replayed
from the start; a game in progress starts at the current point (the cast and the current round's
header are printed first) unless `--from-start`. `--pace N` puts at least N seconds between printed
turns. `run --watch` / `trial --watch` feed the same renderer from the log's listener and print to
stdout instead of the progress lines (the audience view ends with the token report, so it is not
printed twice). ANSI colour only when stdout is a terminal, `--no-color` is not given and
`NO_COLOR` is unset.

- **audience** (default): the cast with codename -> model and roles; each round's header with the
  leader and the score; who was dealt intel and every clue; whisper requests; whispers; every turn
  with its speaker as `Codename (Model) [MOLE]/[crew]`, statement ids, accusations, challenges and
  job claims; confessionals dimmed and marked `┆ private:`; `LIE:` for claims tagged false; `CLUE
  CARD (real)` / `CLUE CARD (FAKE)` (with "true anyway" / "and false"); `JOB CLAIM (FALSE)`; each
  speaker's top suspect with its percentage (moles: what they think the table suspects); job
  choices; `JOB CLEAN` / `JOB BLOWN` with the score; the vote table with bars and the reveal; the
  recap; The Cut, the finale, the result and payouts; the token report. Fallbacks are marked
  `[FALLBACK: <reason>]`.
- **table**: only `project(event, None)` of events `visible_to(event, None)`: codenames only (the
  renderer never learns models or roles from `game_start`), no confessionals, tags, verdicts,
  suspicion, intel receipt or job choices, roles only as revealed by votes. Vote turns are held
  back and printed with `vote_result`.

Rendering shares `labeller`, `marks`, `top_suspect` and `fallback_tag` with `transcript.py`.

Tests: both views, with and without colour, render every ending; the audience view shows the
marks, top suspects, intel receipt and `Codename (Model)` labels; the table view of a
privacy-token game contains only public statement tokens and none of the private markers, and no
model or family name in an anonymised game; vote turns are held back; pace; a watcher following a
file that another thread appends to (including lines written in two halves) prints every event
once in order and stops at `game_end`; `watch` replays a finished game identically; the log writer
flushes per event; `run --watch` and `watch --latest` from the CLI.

## 14. Deviations from V03.md and STAGE2.md

- **Spread when `clue_recipients = 0`.** V03 says validate `0 <= spread <= clue_recipients`, and
  also that 0 means everyone and ignores the spread. Applied literally, `--set clue_recipients=0`
  on the default config (spread 1) would be rejected, so the spread is only checked when
  `clue_recipients > 0`.
- **Turn field `error_kinds`.** V03 names `error_kind`. A turn can fail several times, so a turn
  records `error_kinds` (one per failed attempt, parallel to `rejections`); the `recap` event, a
  single call, records `error_kind`. Both are engine-side.
- **`rejections` is now engine-side too.** It can carry the blocked error text, and V03 says
  blocked details must never be in any projection, so it was added to `ENGINE_ONLY_TURN_FIELDS`
  (the speaker no longer sees it in its own projection; no prompt ever rendered it, and the retry
  line in the prompt is unchanged). Public non-turn events (`recap`, `game_end`) also lose their
  accounting fields (`usage`, `model`, `blocked`, ...) in projections; no prompt rendered those.
- **Per-model `fallbacks` include failed recaps** for the narrator model. `game_end.fallbacks` is
  unchanged (turn fallbacks only).
- **Mole bot types.** V03 lists leader, vote and table-read behaviour only under `smart`; `always`
  and `never` share it and differ only in the job choice, so the sabotage dial is isolated.
  Bots' `--crew-skill` randomness applies to choices (whisper partner, team, accusation, vote),
  not to suspicion. Logician also shows its real clues in whispers; moles show nothing in whispers.
- **Narrator blocks.** V03's one-identical-retry rule is stated for turns; it is applied to the
  narrator's single recap call as well (the narrator otherwise still gets no retries).
- **`examples` command.** No command existed for `docs/example_prompts.md` (Stage 1 used a one-off
  script); `python3.11 -m inside_job examples` regenerates it.

From STAGE2.md (parts A, B and C):

- **`…` placement.** STAGE2 says "append `…`"; it is attached to the last kept word with no space
  and any trailing comma is kept (`... vote Viper with,…` reads as cut). `truncate_words(text, cap)`
  keeps its name and now takes the hard cap; `schemas.hard_cap(limit, grace)` computes it.
- **Where the limits sentence sits.** The old style-paragraph sentence ("anything longer is cut off
  mid-sentence") was replaced in place rather than adding a new one beside the field limits; the
  limits themselves are stated with each field a few lines above.
- **`spoiled` on every row.** STAGE2 names only `"spoiled": true`; every new index row carries
  `spoiled` (false for `run` / `trial` games and unspoiled batch games), so readers need not
  treat a missing key specially for new rows.
- **Exit code 1 on a crash.** Not in STAGE2: if a game raises an exception (a bug, not a model
  failure; model failures fall back as usual) the batch starts no new games, lets running ones
  finish, reports it and exits 1. If both a crash and the stop rule happen, 1 wins.
- **Progress detail.** STAGE2 lists the per-game line and totals; in addition a `start seed N`
  line goes to stderr, and `run`'s per-phase progress lines and per-game token report are not
  printed by `batch` (with several games in parallel they would interleave).
- **Resume command.** Printed as the full command with every flag spelled out (`--parallel-games`,
  `--out` and `--max-fallback-share` always, `--mock` / `--no-preflight` / `--force` when given),
  rather than echoing the original argv; it resumes the same batch.
- **Cut-off and spoiled games stay on disk.** A replayed seed gets a new game id; the partial log
  of a cut-off game (no `game_end`, no index row) and the spoiled game's log, transcript and index
  row are kept. `watch --latest` may pick a partial log left by an interrupted batch.
- **Semaphore per client.** SPEC section 4 said one process-wide semaphore; it was always per
  `ClaudeCLI` instance (one per `run`). `batch` makes one client per game, which is what gives
  each game its own `max_parallel_calls`.
- **`report`: fake cards in whispers count.** STAGE2 says "fake clue cards tabled". Cards shown in
  whispers are reported in their own column and count toward "moles lie" too (a fake card shown
  to one player is the same lie); tabled (discussion) cards are also reported alone.
- **`report`: false job claims use the structured field.** The log records the claim as
  `action.job_claim` and the engine's verdict as `checks.job_claim.lie`, so no free-text claims
  are read for it. Each discussion turn counts, so a claim repeated in both passes counts twice;
  a crew player claiming "sabotaged" is a false job claim too (shown in the crew column).
- **`report`: fallback turns left out.** STAGE2 does not say; section 4 says stats exclude them.
  Fallback votes are left out of unanimity, top-target share, distinct targets and the mole
  agreement count (they still count for eliminations); fallback suspicion readings are skipped
  (the player's last real reading of the round is used); a fallback finale choice is not judged
  as a promise (the outcome still counts).
- **`report`: "skipped".** Read as logs of the batch with no `game_end` (cut off or still being
  played). Section 1 also lists older rows of a replayed seed, logs with `game_end` but no index
  row, and rows whose log cannot be read.
- **`report`: verdicts with nothing to judge.** With 10 or more games but no vote or no finale,
  the line says TOO FEW GAMES rather than a vacuous PASS.
- **`report`: Brier not normalised.** Suspicion values are used as given (/100) as each player's
  P(mole); each reading's Brier is a mean over its rated players and readings weigh equally.
- **`report`: latency per turn.** The log stores a turn's latency summed over its attempts, so
  latency is per turn, not per call. Narrator recaps are left out of truncation (the `recap`
  event records none) and of latency, but included in calls, tokens and retries.
- **`report`: extras.** Beyond STAGE2's list: share of cards fake and of job claims false by role,
  the crew's counts beside the moles', whether both moles' shared target was the one eliminated,
  the pooled top-target share, seats per model, and which phase each Read reading came from.

## 15. Changes after V03.md was first written (applied in this build)

- Section 9 revised: show games are anonymised (`default.toml anonymise = true`); the audience
  always sees `Codename (Model)`; the table view shows codenames only.
- `turn_schema`: `confessional` carries no `description` (section 6); unit-tested for every phase.
- The nested reply object is `move` on the wire (schema and prompts) and `action` in the engine
  and log, because claude-sonnet-4-5 wrapped its whole reply in an extra `action` object (section
  6); the preflight also sends a vote call (section 4); an `is_error` reply's error says its
  `subtype` and first `errors` entry (section 4).
- `config/default.toml` cast: the seven Claude 5 models (section 3); new `config/pilot.toml` with
  the cheap Stage 2 cast; the narrator stays Haiku 4.5.

## 16. Viewer (`viewer.py`, `viewer/index.html`)

Contract: STAGE4.md (an internal build note, not published). A page that shows a game as a heist blueprint, built only from the
JSONL log (section 8): a finished game is replayed, a game in progress is followed live. Nothing in
the engine, the log format, prompts or rules changed for it.

**Server** (`ThreadingHTTPServer` on `127.0.0.1`, GET only, everything else 405):

| Path | Returns |
|---|---|
| `/` | the page |
| `/api/games` | `{"games": [...]}`, newest first (log mtime): `game_id`, `seed`, `batch`, `finished`, `winner`, `reason`, `rounds`, `spoiled`, `cast` (model names in seat order), `mtime`; from `index.jsonl` (last row per id) plus `g-*.jsonl` logs with no row (read from the log; `finished` means it has `game_end`) |
| `/api/log/<game_id>?from=N&view=audience\|table` | `{"events", "next", "done", "meta"}`: events from complete line N (a half-written last line waits); `done` once `game_end` is at or before `next`; `meta.rules` = `clean_target`, `sabotage_target` from the config |

`game_id` must match `^g-[0-9A-Za-z-]+$` and resolve to a file directly inside `--out`; any other
path is 404 (no other file is served; `index.jsonl`, transcripts and encoded or absolute paths
included). Responses carry `Cache-Control: no-store`; the page also carries a Content-Security-Policy
that allows no request to any other host.

**Audience view** gets every event, with the transcript helpers' values added to each turn:
`_label` (`labeller`), `_role`, `_marks` (`marks`, as lists), `_top_suspect` (`top_suspect` as
`{name, pct, kind, label}`), `_fallback` (`fallback_tag`) and `_cards` (the text of each tabled or
whispered card, `clues.card_as_clue`). `game_start` keeps only `config.game` and gains `_labels`.
Fields the page never shows are dropped from the payload: `usage`, `served_model`, `latency_s`,
`rejections`, `error_kinds`, `error`, `error_kind`, `memory`.

**Table view** gets only `project(event, None)` of events with `visible_to(event, None)`, plus
`_cards` (card texts) on public turns; vote turns are held back and sent together just before their
`vote_result` (while the result is not written yet, `next` points at the first held vote, so the
next poll gets them all). No confessional, claim, check, suspicion, role (before its reveal), model
name, clue, whisper text or job choice ever reaches the page in this view.

**Export.** `export_html(log, view)` puts the decorated (or projected) events of one game into the
page's `<script id="ij-data" type="application/json">` slot. The JSON is escaped so it cannot close
the script element (`<`, `>`, `&` as `\u003c` ...) and so that no `://` appears in the file (`\/`),
so the file holds no `http://` or `https://` text even when a player typed a URL. It plays from
`file://` with no network; an unfinished game exports as it stands.

**Page.** One fixed design canvas scaled to the window and letterboxed: wide 1920x1080 and tall
1080x1920 (`?layout=wide|tall`, else the window's shape; a toggle button). Flat blueprint look (deep
blue, a fine grid, white and cyan lines, amber for moles, lies and blown jobs, mint for clean
results), system monospace fonts, the table, seats, connectors and arrows in inline SVG, all running
text in HTML boxes over it.

- Wide: header; the table with seven seats round it and the statement box on the table (a leader
  line to the speaker); on the right the confessional spotlight (audience) and a board (public
  record) or the whisper message under it. Table view: the board takes the whole right column.
- Tall: header; a compact table; a full-width statement box under it (which also holds whisper
  messages, reveal cards and, when nothing else is shown, the board); the confessional (audience)
  or the board (table view) at the bottom.
- Text fits: each box shrinks its font (binary search) to a floor; only if it still overflows does
  it scroll, through the beat's duration.
- Beats come from one pure function, `buildBeats(events, view, {rules, wps})`, in the page's
  `<script id="ij-core">` (no DOM; the tests run it under node): cast, round, intel (audience),
  silent turns (`think`, audience), whisper pairs, whispers (audience), statements (`say`), the pick,
  the job result, the vote (all arrows together), the elimination, the recap, The Cut and finale
  titles, the cut result, the finale result and the end card. Duration: the beat's words at 3.5 a
  second (public text, and in audience view the confessional and marks), at least 2.5 s; reveals 3 s.
  Unknown event types and malformed events get no beat and never break playback.
- Controls (hidden with `?clean=1`): play / pause (Space), previous / next beat (Left / Right), speed
  0.5x to 4x, a timeline with round markers (click or drag), round jump, LIVE, layout, view (reloads
  the log in that view, keeping the position), game list. `?autoplay=1` plays; `#R2-S3` opens on that
  statement; `?beat=N` opens on beat N.
- Live: while the log is not `done` the page polls `/api/log` every 2 s and appends beats; a game in
  progress opens at its newest beat and follows (plays) as beats arrive, showing "waiting for the next
  turn" at the end; a finished game opens at the first beat. The clock runs on a timer, not
  `requestAnimationFrame`, so it keeps time in a background tab.
- `prefers-reduced-motion`: no transitions or animations.
- `window.insideJob = {state, buildBeats, selfCheck, audit, load, goto, setLayout}`. `selfCheck()`
  returns `{events, beats, turns, turnsShown, problems}` (a turn with public text and no beat; a beat
  whose text overflowed at the smallest size when last shown). `audit(layout)` visits every beat in
  that layout and also lists boxes that overlap or leave the canvas.

Tests (`tests/test_viewer.py`): the game list (finished, unfinished, old-format logs, order, fields);
paging with `from`, half-written lines, `done`, and the held-back votes; audience decoration equal to
the helpers; the table view of privacy-token games (whole and partial logs) has public statement
tokens only, no private field or event, no role before its reveal and no model or family name;
bad ids, encoded and absolute paths and other files are 404, other methods 405, the bind address is
127.0.0.1, a taken port is a clear error; both exports are self-contained and the table export
passes the privacy check; the page has no external reference; with node, `buildBeats` over every
ending (and unfinished, old-format and odd logs) gives a beat to every public turn, in log order,
with positive durations.

Where the build differs from STAGE4.md:

- The `/api/log` response also carries `meta` (`view`, `game_id`, `rules`: the clean and sabotage
  targets from `config.game`), so the table view can draw the score pips; the targets are rules every
  player is told, nothing private.
- A `log` given as a path serves that file's folder (the server only ever serves files directly
  inside the folder it serves).
- A game in progress opens at its newest beat and plays, so it follows the game without a click.
- In the tall layout the statement box sits under the table at full width (a leader line runs to the
  speaker) rather than on the table, so 70-word statements stay large enough to read on a phone.
- The audience payload leaves out fields the page never shows (listed above). `HEAD` is 405 like the
  other non-GET methods. In table view the game list hides winners, reasons, rounds and casts.
- Extras: `?beat=N`; `?audit=1` (runs `audit` in both layouts and writes the result into a hidden
  `<pre id="ij-audit">`, for headless checks); `insideJob.audit(layout)`, `load(id, view)`, `goto`,
  `setLayout`.
