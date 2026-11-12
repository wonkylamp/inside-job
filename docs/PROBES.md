# Inside Job — Read probes, version 1 (build contract)

2026-11-10. Approved: build the probe runner, then a 400-call top-model check
(steps 1 and 2 of an internal run plan, not published). This file is the contract for the build.

## What a probe is

One logged game state, replayed to one model in one call. Version 1 has one kind:

**Read probe.** A crew player's **vote turn** from a finished real game. The model under test
receives exactly the system prompt, turn prompt and reply schema that seat would receive at that
point, and answers the whole turn as in a game. Only two parts of the reply are scored: the
`suspicion` numbers and the `vote`.

The probe text is frozen in a file and hashed. Every model sees the same bytes. Later changes to
`prompts.py` cannot change a frozen probe.

## Rules for the build

- New files only: `inside_job/probes.py`, `tests/test_probes.py`. Allowed edits: `inside_job/__main__.py`
  (one `probes` subcommand and its dispatch, nothing else), `.gitignore` (add `probes/runs/`).
- Do not change any other file. In particular not `engine.py`, `log.py`, `prompts.py`, `schemas.py`,
  `config.py`, `solver.py`, anything under `analysis/`, `inside_job/viewer*`, `tests/test_viewer.py`.
  Other work is in progress on those.
- Python 3.11 standard library only. `inside_job/probes.py` must not import `analysis` (it needs numpy).
  Tests may import `analysis` to cross-check, and must skip cleanly if numpy or the data is missing.
- No real model calls. Use `MockLLM` or a stub `exec_fn`. Never write under `games/`.
- Temporary files go in the scratchpad folder given in the brief, never `/tmp`.

## Rebuilding the state (no `analysis` import)

For a vote turn `t` of player `p` in round `r`:

- cutoff = (seq of the first vote turn of round `r`) - 1; events = all with `seq <= cutoff`.
- ctx = what `Game.base_ctx` gives at that moment: `others` and `alive` from that round's
  `round_start["alive"]`, `role`, `moles_remaining` (moles in `alive`), `leader` from `round_start`,
  `whispers` from the logged config, `card_players` (all players in seat order except `p`),
  `on_team` from the round's `job_pick`, `partners` (`[]` for crew); then `self = p`.
- system = `prompts.player_system_prompt(setup events, p, cfg)`, prompt =
  `prompts.turn_prompt(events, p, cfg, "vote", ctx)`, schema = `schemas.turn_schema("vote", ctx)`,
  with `cfg = config.config_from_dict(logged config)`.
- Games with `vote_nobody` on are refused with a clear message (not in version 1).

`analysis/common.py` (`rebuild_ctx`, `rebuild_prompt`, `GameData._cutoffs`) does the same thing
independently. Read it, do not import it in the module; the tests compare the two.

## The frozen set

`python3.11 -m inside_job probes build --batch pilot1 --batch pilot2 --n 100 --seed 20261110 --out probes/sets/read_v1.jsonl`

- Candidates: vote turns of crew players, `fallback` false, in finished games of the named batches
  (`games/index.jsonl`, same loader the report uses), where at least one rated player has a
  job-weighted chance (q = 0.5) between 0.2 and 0.8.
- Selection: deterministic from the seed. At most one probe per (game, round) until every such
  cell has one; cells are taken evenly across games and rounds. If `--n` is larger than the number
  of cells, a second seat per cell is allowed and the build says how many.
- One JSON object per line, keys sorted, UTF-8:
  `probe_id` (first 16 hex of sha256 over system, prompt and the schema as compact sorted JSON),
  `kind` ("read_vote"), `batch`, `game_id`, `seed`, `round`, `seq`, `cutoff_seq`, `player`,
  `orig_model`, `system`, `prompt`, `schema`, `ctx`, `caps`, `retries`, `rated` (names),
  `truth` (name -> 0 or 1), `formula` (`simple`, `jobw50`, `jobw80`, `public`: name -> chance),
  `orig` (`suspicion`, `vote`, `brier`), `strata` (`n_alive`, `moles_alive`, `blown_jobs`,
  `clean_jobs`, `sabotage_target`, `false_card_visible`, `n_undecided`).
- Formulas, all from `inside_job.solver.from_log(events, cutoff, viewpoint)`:
  `simple` = `posterior(player_worlds(...), players, fallback)` from the player's viewpoint;
  `jobw50` / `jobw80` = the same worlds weighted by job likelihood (each mole on a team sabotages
  with chance q; copy the 15 lines from `analysis/strategies.py` `job_likelihood` and
  `weighted_posterior`, with the same fallback as the scratch script named in the brief);
  `public` = the table viewpoint. Chances are for the rated players only.
- A manifest `read_v1.manifest.json` beside it: sha256 of the set file, count, arguments, source
  batches with their game ids, sha256 of `prompts.py`, `schemas.py`, `config.py`, `probes.py`, and
  the time. `probes verify --set FILE` recomputes every `probe_id` and the file hash and exits 1 on
  any mismatch. `run` and `score` verify first and refuse a set that fails.
- `build` refuses to overwrite an existing set file.

## Running

`python3.11 -m inside_job probes run --set probes/sets/read_v1.jsonl --model claude-fable-5-2 --effort high --max-thinking-tokens -1 [--parallel 2] [--limit N] [--timeout 240] [--mock]`

- Uses `llm.ClaudeCLI` (so the exact approved `claude -p` call, `--effort` and `MAX_THINKING_TOKENS`
  handled by `build_argv` / `build_env`). Only `system`, `prompt` and `schema` of a probe are sent.
- Per probe the same loop as `Game.ask`: validate with `schemas.clean_reply` (the probe's `ctx`
  and `caps`); a blocked reply gets one identical retry; an invalid reply gets up to `retries`
  more tries with the same rejection line the engine adds. No fallback is invented: a probe that
  ends without a valid reply is recorded as failed.
- Output: `probes/runs/<set name>/<model>__<effort or none>__t<cap>.jsonl`, one line per probe,
  appended and flushed as each finishes: `probe_id`, `model`, `effort`, `max_thinking_tokens`,
  `served_model`, `ok`, `error_kind`, `attempts`, `rejections`, `suspicion`, `vote`, `data`
  (the cleaned reply), `raw` (raw text of every attempt), `usage`, `latency_s`, `ts`.
- Resume: probes already in the file with `ok` true are skipped. `--limit` takes the first N in
  set order, so a smoke run is a prefix of the full run.
- Ctrl-C leaves no child process and a valid file. At the end print calls, failures, tokens by
  kind (input, output, thinking, cache) and wall time.

## Scoring

`python3.11 -m inside_job probes score --set FILE [--runs DIR] [--write FILE.md]`

Per run file (model x effort x cap), on its valid probes:

- Brier of the reading (mean over rated players of (stated/100 - truth)^2; identical to
  `analysis/common.brier`), and the same for each formula and for the original player on the same
  probes.
- Model minus `jobw50`, paired per probe: mean, 95% interval by bootstrap over **games** (2,000
  resamples, fixed seed) and by paired t over game means.
- The same restricted to undecided ratings (jobw50 between 0.2 and 0.8), plus the slope
  `sum((s-f)(t-f)) / sum((s-f)^2)` over those ratings (s stated, f jobw50, t truth) with a
  bootstrap interval. Above 0 means the model's departures from the formula point at the truth.
- Share of votes that land on a mole, beside the same share for the original player and for
  "vote for the formula's top suspect" (ties split evenly).
- Valid count, failed count by kind, mean tokens (input, output, thinking), mean latency, and any
  probe served by a model other than the one asked.

Between runs, paired on the probes both answered: every pair of runs of the same model (effort
against effort), and every pair of models at the same effort and cap. Same statistics.

Markdown tables; numbers to three decimals; a line at the top with the set hash.

## Tests (`tests/test_probes.py`)

1. **Exact text.** Play mock games in memory (`MockLLM`, seeds 1 to 4, `config/pilot.toml` and
   `config/pilot2.toml`, as `analysis/common.mock_rebuild_check` does). For every crew vote turn the
   probe's system, prompt and schema equal what `MockLLM` recorded for that call. 100%, no skips.
2. **Replay gives the logged score.** A stub client that returns each probe's logged reply: the
   run scores equal `orig.brier` to 1e-12 and votes equal `orig.vote`.
3. **Cross-check** (skip if numpy missing): on the same mock games the module's cutoff, ctx and
   prompt equal `analysis.common.rebuild_prompt`; `jobw50` equals `analysis.strategies.weighted_posterior`.
   If `games/index.jsonl` and `analysis/out/decisions_pilot1.jsonl` exist: for every crew vote turn
   of pilot1, the module's Brier of the logged reading equals the table's `brier_model` (1e-9).
4. **Nothing private is sent.** The argv built for a probe contains only that probe's system,
   prompt and schema; no `truth`, `formula` or `orig` value can reach it (check with a stub `exec_fn`).
5. **Freeze.** Same arguments give a byte-identical set. Changing one character of a prompt makes
   `verify`, `run` and `score` fail. `build` will not overwrite.
6. **Selection.** One probe per (game, round) before any second; only crew, non-fallback, vote turns.
7. **Run loop.** Invalid then valid reply: 2 attempts, rejection line as the engine's. Blocked twice:
   failed, `error_kind` blocked. Timeout: failed. Resume skips finished probes. `--limit` is a prefix.
8. **Scoring maths.** Hand-made set of 6 probes in 3 games with known answers: Brier, paired
   difference, slope and vote share to 1e-12; the bootstrap is reproducible.
9. `python3.11 -m inside_job probes run --mock` end to end in a temporary folder, then `score`.

Run `python3.11 -m unittest tests.test_probes` often. Run the full suite once at the end in the
background (`python3.11 -m unittest discover -s tests`, 6 to 9 minutes). The viewer tests are being
changed by other work: report a viewer failure, do not fix it.

## Report back

- Files added or changed, with line counts.
- Test names and results, and the full-suite result.
- The output of `probes build` on the real logs (count of candidates, cells, probes by batch and
  round, how many have a false card on the table), **written to the scratchpad, not to
  `probes/sets/`**: the lead freezes the real set.
- Test 3's real-data result: how many pilot1 vote readings were compared and whether all matched.
- Anything in this contract that could not be done as written, and what was done instead.
- Anything found that makes a probe differ from what the seat saw in the game.
