# The raw sidecar log and the code stamp

## What the raw file is for

The game log (`g-....jsonl`) keeps the cleaned, parsed turn: what the engine accepted, after
trimming, with the move stored under `action`. It does not keep the system prompt, the turn prompt,
the reply schema, the CLI's raw output, the text of rejected or failed replies, the text before
word-cap trimming, per-attempt usage, or which code played the game. The raw file keeps all of
that, so a result can be audited and any call can be replayed exactly.

Each game played by `run`, `trial` or `batch` (mock games included) writes `g-....raw.jsonl` beside
its log. It is flushed after every record, so a crashed game leaves a readable file. When the game
ends, or raises, the engine gzips it to `g-....raw.jsonl.gz` and removes the plain file. Pass
`--no-raw` to `run`, `trial` or `batch` to write no raw file. The scripted `bots` command, the
preflight, `examples` and games built in memory never write one.

If the raw file cannot be written (disk full, no permission), the game goes on: the engine prints
one warning to stderr and writes no more raw records for that game. The main log is never affected.

Nothing that builds prompts, the transcript, the live view, the report or the viewer reads the raw
file. `watch --latest` and `report` skip `*.raw.jsonl` files when they look through a folder.

## Records

One JSON object per line. Every record has `kind` and `game_id`.

- `header`, always the first record: `seed`, `rules_version`, `log_version`, `code_hash` and
  `code_files` (the code stamp, below), `conditions` (`max_thinking_tokens`, `effort`),
  `argv_template` (the exact `claude -p` argv with `<model>`, `<system>`, `<schema>` and `<prompt>`
  in place of the per-call values, from `llm.build_argv`), and `client` (the model client's class
  name, for example `ClaudeCLI` or `MockLLM`). A mock game still records the argv a real game
  would use.
- `system`, once per player in seat order and then once for the narrator: `player` (null for the
  narrator), `model`, `sha256` (of the text, UTF-8) and `text`.
- `schema`, once per distinct reply schema, written just before the first attempt that uses it:
  `sha256` and `schema` (the object). The hash is taken over
  `json.dumps(schema, separators=(",", ":"), sort_keys=True)`. Name fields are enums of the
  players who are valid targets at that moment, so a game has many distinct schemas.
- `attempt`, one per call attempt, players and narrator alike, in the order the replies come back:
  - `n`: running index from 0 within the game;
  - `round`; `phase` (the turn phase, such as `discuss` or `vote`, or `recap` for the narrator);
    `player` (null for the narrator); `model` (the requested model); `attempt` (1-based within the
    turn);
  - `system_sha256` and `schema_sha256`, which point at the `system` and `schema` records;
  - `prompt`: the full text actually sent on this attempt, including any
    `Your previous reply was rejected: <reason>. Reply again with valid JSON.` line;
  - `stdout`: the CLI's complete stdout, untruncated (for the mock client, the JSON text it
    returned); `stderr_tail`: the last 2,000 characters of stderr; `returncode`: the CLI's exit
    code. All three are empty or null after a timeout or a failed spawn, and `error` says why;
    for an OpenRouter model (docs/OPENROUTER.md), `stdout` is the HTTP response body (scrubbed of
    the key), `stderr_tail` the client's transport notes (`openrouter: http 429, http 200`) and
    `returncode` null;
  - `error`: the client's error text (the same text the main log keeps in `rejections`, cut to
    about 300 characters), or null; `error_kind`: `blocked`, `timeout`, `cli` or `invalid` (the
    reply arrived but failed validation; `error` is then null and `rejection` gives the reason), or
    null when the attempt was accepted;
  - `served_model`, `usage` (the six usage keys for this attempt alone), `latency_s`, `ts`;
  - `accepted`: true if this attempt's reply was used; `rejection`: the reason string when not
    accepted, else null; `trimmed_fields`: the fields the engine trimmed at the word cap when
    accepted (`confessional`, `public`, `memory`, `claims`, or `recap` for the narrator), else `[]`.
- `turn`, written when the engine writes a `turn` or `recap` event to the main log: `seq` (that
  event's `seq`), `attempts` (the `n` values of its attempts, in order) and `fallback` (true when
  the turn fell back, or the recap failed and its text is "").

## How it links to the main log

The `turn` record is the only link. Every `turn` and `recap` event in the main log has exactly one
`turn` record with the same `seq`, and the length of its `attempts` list equals the event's
`attempts` field. The main log's events gain no key from the raw file. The number of `attempt`
records equals the sum of `attempts` over the main log's `turn` and `recap` events. A turn's
accepted reply is its last attempt, unless the turn fell back. To replay a call, take its
`attempt` record, look up the `system` text and the `schema` by hash, and fill `argv_template`.

## How to read it

```python
from inside_job.rawlog import read_raw
records = read_raw("games/g-20261110-120000-s1.raw.jsonl.gz")
```

`read_raw` reads the plain or the gzipped form (given a game log path, it finds the raw file
beside it). It drops a torn last line, and for a gzip stream cut short it returns the records it
could read. From a shell: `gunzip -c g-....raw.jsonl.gz | head -1`.

`games/index.jsonl` rows now have `raw` (the gz file's path, or null with `--no-raw`) and
`code_hash`.

## The code stamp

`rawlog.code_fingerprint()` hashes the files that decide how a game is played: `RULES.md` and
`inside_job/__init__.py`, `clues.py`, `config.py`, `engine.py`, `llm.py`, `log.py`, `prompts.py`
and `schemas.py`, with paths relative to the project root. It returns
`{"code_hash": ..., "code_files": {path: sha256}}`, where `code_hash` is the SHA-256 of the lines
`"<path> <sha256>\n"` in sorted path order. A missing file is recorded as `"missing"`. The result
is cached for the process.

`run`, `trial` and `batch` stamp `code_hash` and `code_files` on the `game_start` event (mock games
too); the raw header carries the same values. `game_start` is an engine event, so no player ever
sees the stamp. Games built directly with `Game(...)` (the bots, tests, the preflight) are not
stamped, and their `game_start` is unchanged.

`python3.11 -m inside_job fingerprint` prints the current code hash and the per-file hashes.
`python3.11 -m inside_job fingerprint --check <game log>` says whether that log was played by this
code: exit 0 if the stamped hash equals the current one, 1 if it differs (it lists the files that
differ), 2 if the log has no stamp or cannot be read.

## Before publishing a raw file

The raw file holds every prompt and every reply in full, including confessionals, memories,
rejected replies and the text cut by trimming, plus whatever the CLI prints: session ids, request
ids, error messages and model ids. Check it before any raw file is published.

## Older logs

Logs made before this change have neither a raw file nor a code stamp; their index rows have no
`raw` or `code_hash` key.
