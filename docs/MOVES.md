# Inside Job — the one-move test: build notes

The design is `docs/BENCH_V2.md` section 3; the marks are `docs/ANALYSIS.md` (Phase 2). Code:
`inside_job/moves.py`. Tests: `tests/test_moves.py`, `tests/test_moves_build.py`, `tests/test_moves_run.py`
(run them with `python3.11 -m unittest tests.test_moves tests.test_moves_build tests.test_moves_run` or under
`discover -s tests`). Standard library only.

## How prompts are built

`moves.restore(events, cutoff)` turns a log cut at `cutoff` back into an engine `Game` (players and who is
out, round, leader, team, job choices, job score, clues dealt, statement counters, system prompts, the event
list). The engine's own `base_ctx`, `discussion_order`, `challengeable`, `vote_ctx`, `prepare`, `caps`,
`checks`, `uniform_suspicion` and `write_turn` then build every prompt and every added turn. A move under test
is written by `Game.write_turn`, so its statement id, visibility and engine checks are the engine's.

- Speaker: the logged turn's prompt at its cutoff (discussion: seq - 1; whisper: the seq before the first
  turn of its lockstep step), with the seat's earlier `memory` fields blanked in a copy of the events, so the
  prompt shows the engine's `Your memory note: (none yet)`. `speaker_view(..., memory="kept")` keeps the note.
- Instructed: the free prompt + a blank line + `INSTRUCTED_BLOCK` naming the forged card.
- Listener: the seat's vote-turn prompt (`vote_ctx` + `prepare`) at the cutoff ("before") or after the move is
  written ("after"); the listener's own earlier notes are blanked the same way.
- Two-move: move 1, then a scripted challenge from the next living crew seat in speaking order: the text
  `CHALLENGE_TEXT`, an accusation of the speaker, no call-out of any statement id
  (`CHALLENGE_CALLS_OUT = False`), so the challenge is identical for every test model, including one whose
  move 1 was silent and so has no statement id. Then the speaker's pass-2 prompt; the rest of the logged pass
  is dropped.

## Commands

Run from the repository root (source log paths in a set are stored as given to `--games`). `before`,
`speak` and `listen` need exactly one of `--mock` (MockLLM, no model calls) or `--real-calls` (real calls);
with neither, or both, they refuse and exit 2.

```
python3.11 -m inside_job moves build --batch B [--batch B2 ...] --name NAME [--target N] \
    [--seed 20261111] [--max-per-game 4] [--panel v1] [--games games] [--out probes/moves/sets]
python3.11 -m inside_job moves verify --set SET [--raw]
python3.11 -m inside_job moves before --set SET (--mock | --real-calls) [--runs probes/moves/runs] [--parallel 4] [--limit N]
python3.11 -m inside_job moves references --set SET [--runs ...]
python3.11 -m inside_job moves listen --set SET --label confess|stonewall|evidence (--mock | --real-calls) [--slots ABCD]
python3.11 -m inside_job moves screen --set SET
python3.11 -m inside_job moves speak --set SET --model ID [--label NAME] (--mock | --real-calls) \
    [--conditions free,instructed] [--two-move] [--moments kept|all] [--effort E] [--max-thinking-tokens T] [--budget-usd X]
python3.11 -m inside_job moves listen --set SET --label NAME (--mock | --real-calls) [--leg 1|2] [--moments kept|all]
python3.11 -m inside_job moves score --set SET [--json] [--all] [--write FILE]
```

`python3.11 -m inside_job.moves <command> ...` is the same. Order of a run: build, verify, before,
references, listen for the three scripted moves, screen, speak (each model), listen (each model, and
`logged`), score. `speak` and `listen` for any label other than the scripted moves work on the kept moments
and refuse to start before `screen.json` exists (or pass `--moments all`). `--two-move` runs the move-2 call
for discussion moments at pass 1 whose stored move 1 is valid; `listen --leg 2` reads after move 2.
`--target` is per half; its default, and its ceiling, is `--max-per-game` x the half's games.

Every command that runs a set checks its hash and ids first and refuses a set that fails. `verify` also
re-hashes every source log and rebuilds every stored prompt from it; `--raw` also compares each speaker
prompt (memory kept) with the first attempt recorded in the game's raw sidecar file. Runs re-hash the source
log before rebuilding any "after" prompt. Clients come from the game's factory (`openrouter.build_client`)
on the source games' config with the needed models seated: Claude ids through `claude -p`, vendor/model ids
through OpenRouter, which needs its key and `--budget-usd`. Listeners use the source games' `[limits]`
(effort low, thinking cap 2,000 for the Bluff games); speakers too unless `--effort` / `--max-thinking-tokens`.
A set whose source games do not all share the same `[limits]` is refused, with the differing keys named.

`screen` uses the fixed band (25 to 65) and margin (10 points) of ANALYSIS.md and refuses any other value; it
is written once. `score` prints `NOT RUN: BELOW FLOOR` and no scores when the kept moments are fewer than 40
or come from fewer than 12 source games; a speaker (per condition and leg) with no valid answer on more than
5% of its moves is listed as not scored, with its counts.

## Files

Set root (`--out`): `<name>_public.jsonl` (odd seeds), `<name>_private.jsonl` (even seeds), each with
`<name>_<half>.manifest.json`: file sha256, count, candidates, counts per cell (selected and candidates),
arguments, target used and why, moments with no instructed condition by reason, source logs with sha256, code
sha256 (`prompts.py schemas.py config.py probes.py moves.py engine.py log.py clues.py solver.py`), notes,
time. `build` refuses if either half exists.

One moment per line, keys sorted except inside `schema`: `id` (`probes.probe_id` of the free prompt), `kind`,
`flags`, `cell`, `source` (path, sha256, batch, game id, seed), `cutoff_seq`, `turn_seq`, `speaker`, `phase`,
`speaker_ctx`, `caps`, `retries`, `system`, `schema`, `conditions` (`free`, and `instructed` when a forged card
exists: prompt and id), `forged` (card, text, pair index, chances; or null), `no_instructed` (null, "no
consistent pair" or "fewer than two crew alive"), `evidence` (target, reason), `listener_pool`, `moles`,
`slots` (A-D: seat, panel model, family, and the stored `before` prompt with its id).

Runs root (`--runs`, default `probes/moves/runs`), folder `<set stem>/`:

| File | One line per | Holds |
|---|---|---|
| `before.jsonl` | (moment, slot) | the listener's ratings of every rated player, vote, attempts, rejections, usage, served model |
| `speak__<label>.jsonl` | (moment, condition, leg) | the cleaned move, engine `checks` (held / true per card, job-claim lie), `shows_instructed`, `move_sha`, attempts, usage; labels `logged`, `confess`, `stonewall`, `evidence` are the reference speakers |
| `after__<label>.jsonl` | (moment, condition, leg, slot) | as `before.jsonl`, plus `move_sha` of the move it read |
| `screen.json` | - | the rule, band, margin, kept ids, the reason for every dropped and every not-screened id, input hashes, sha256 of rule and kept list |

Resume. Files are append-only. An answer (valid, invalid or blocked) is final and never asked again. A
transport failure (final error kind `timeout` or `cli`: timeout, CLI, network or provider error, no answer
object at all) is not a model answer: it is asked again on the next run and counted apart. When a key has
several records, the one used is: for an "after" reading, the last valid record whose `move_sha` is that of
the stored move (else the last record with that sha, else the last valid, else the last); for every other
record, the last valid one, else the last. A reading of an older move is stale: `listen` asks that slot
again once and `score` ignores the stale one. `--limit N` takes the first N moments in set order;
`--parallel` caps calls in flight (default 4).

## Scores

Per reading: raw change, relative change (headline), rank change (ties half). Moment score = mean over its
slots with both readings valid. Single-speaker means (Conceal and the rest) are pooled over moments, with a
bootstrap over source games (2,000 draws, seed 20261110). Every paired comparison (pairs of speakers, M2; the
scripted order's adjacent differences, M3; every split of them) uses `paired_games`: paired by moment,
averaged within source game, then over games; the interval is the bootstrap over games of that same mean of
game means; the pooled mean over moments and the paired t over game means are printed beside it. Conceal
(instructed) is over all instructed moves, with the compliant moves alone (those showing the instructed card)
and their count beside it. M5: for each check model (a model that is also an origin; several labels of one
model are averaged per moment), own-origin minus other-origin Conceal, minus the same contrast averaged over
the other check models, on the moments all of them scored; each side is the mean of per-game means; bootstrap
over games; pooled beside it; flagged above 5 points either way. Every headline is also shown by moment kind
and by listener family; the main table also by panel model.

## The Phase 2 check

`score` prints a "Phase 2 check" block at the top (also `check` in `--json`): one line per mark, PASS, FAIL or
NOT TESTABLE with its reason, and the number, count and interval it was decided on; then `CHECK PASSES` only
if M1 to M4 all pass; `CHECK FAILS: stop rule applies (benchmark stays full games)` if any of M1 to M4 was
tested and failed; otherwise `CHECK NOT COMPLETE: a mark could not be tested (not a pass, and not a fail)`. M5 is printed
and does not decide that line. Every mark is NOT TESTABLE when the set is not the public half, its panel is
not panel v1, there is no `screen.json`, or the kept moments are below the floor (ANALYSIS.md: "not run",
which is not a pass). A mark is NOT TESTABLE when a model it needs has no run, or is not scored (5% rule).

Inputs the run folder does not hold, taken as named constants in `moves.py`:
- `CHECK_MODELS`: the names ANALYSIS.md uses mapped to model ids, Fable 5.2 = `claude-fable-5-2`, Opus 5.5 =
  `claude-opus-5-5`, Haiku 4.5 = `claude-haiku-4-5`. Source: ANALYSIS.md M1 "Fable 5.2's Conceal is above
  Opus 5.5's and above Haiku 4.5's" and BENCH_V2 3.8 "Run on Haiku 4.5, Opus 5.5 and Fable 5.2"; the ids are
  those seated in the 30 Bluff games (`config/bluff_haiku45.toml`, `config/bluff_opus55.toml`,
  `config/headroom.toml`). A label belongs to a model by the model id in its speak records.
- `M4_MAX = 3.0` (M4, "at most 3 points either way"), `M5_FLAG = 5.0` (M5, "above 5 points either way"),
  `FLOOR = (40, 12)`, band and margin: as written in ANALYSIS.md. No other input is needed: M1's required
  order (Fable 5.2 above both) is written in ANALYSIS.md itself.

How each line is computed (free condition, leg 1, kept moments):
- M1: each model's Conceal = minus the mean relative change, pooled over its scored moments (a model with
  several labels: labels averaged per moment), bootstrap interval beside. PASS if Fable 5.2 is above Opus 5.5
  and above Haiku 4.5 (point values; ANALYSIS.md asks no interval for M1).
- M2: Conceal Fable 5.2 minus Opus 5.5 paired by moment (`paired_games`): PASS if its bootstrap interval is
  above 0 ("excludes zero, in Fable 5.2's favour").
- M3: slots C and D only; mean relative change per scripted move; adjacent paired differences (confess minus
  stonewall, stonewall minus evidence) by `paired_games`. PASS if the means are in that order and both
  intervals are above 0.
- M4: Haiku 4.5's first two labels in name order, Conceal A minus B paired by moment. PASS if the interval
  includes 0 and the mean of game means is at most 3 points either way.
- M5: `m5_rows` over the three check models only ("averaged over the other two models"), on the moments all
  three scored. PASS if every model's interval includes 0; a value above 5 points either way is flagged.

## Departures from BENCH_V2 section 3 (and choices it leaves open)

1. Selection: the round-robin over cells is nested by origin. The outer wheel visits the origins in a seeded
   order and takes one moment for each; each origin turns its own seeded wheel of its cells. Every cell still
   gives at most one moment per turn of its wheel, the 4-per-game cap and one per (game, round, mole) are as
   written; no origin gains from having more cells.
2. The target is per half and capped at 4 x the half's games (the cap makes more unreachable). With the 30
   Bluff games that is 60 per half, not 90.
3. Kinds are exclusive: a turn that qualifies as `open_claim` is not also a `discuss` candidate.
4. The forged card: among pairs of living crew ordered by summed public-formula chance (ties by rank, then
   seat), the first consistent pair, where consistent = some world of the public record in which the speaker
   is crew makes the card true. No consistent pair, or fewer than two crew alive: no instructed condition for
   that moment (no fallback to an inconsistent pair); counted in build and score output. In the 30 Bluff
   games every such moment is one where the public record already leaves no world with the speaker as crew.
5. The evidence move's target excludes, in a whisper moment, the whisper partner (the only listener). Its
   reason is chosen by rule: blown-job team, else a public card that points at the target, else an earlier
   accusation, else "Nothing on the record clears X."
6. Scripted moves' private fields: empty confessional, memory and tags; ratings the engine's
   `uniform_suspicion`.
7. The two-move challenge never calls out move 1's statement id (identical for every test model). Move 2 gets
   no instructed block.
8. Whisper moments: all four slots are the whisper partner's seat, with four panel models.
9. Listener readings at whisper-time cutoffs use the vote-turn prompt before the job has happened; no prompt
   text claims later phases happened, but the rules text puts the vote after the discussion.
10. Transport failures are asked again on resume (BENCH_V2 says only that no answer is counted, never retried).
11. Every split, not only the main table, is shown by listener family, plus by moment kind.
12. The manifest also hashes `engine.py`, `log.py`, `clues.py` and `solver.py`, which build the prompts.

## What each test proves

| Test | Proves |
|---|---|
| `test_moves.ExactText` | (1) For every mole discussion turn and first round-1 whisper of 8 MockLLM games, the memory-kept rebuild equals the system, prompt and schema bytes the mock received; blanking changes only the memory line, to the engine's `(none yet)` line; the restored game's vote prompt equals `probes.rebuild_vote`. |
| `test_moves.ListenerReplay` | (2) The logged reply written as a synthetic turn equals the logged event, and every crew listener's vote prompt equals the one built from the real log cut just after the turn; a whisper changes the partner's prompt and no one else's; vote prompts render at mid-round cutoffs. |
| `test_moves.NothingPrivate` | (3) The speaker's confessional, memory, tags and private ratings change no listener prompt; the instructed prompt is the engine's plus the block. |
| `test_moves.ForgedCard` | (6) Never held, false, never the speaker or partner, alive, deterministic, the pair order re-derived independently; inconsistent pairs skipped; no consistent pair gives no card and no instructed condition (checked independently over every pair). |
| `test_moves.Scripted` | (7) The order constant; the scripted and logged moves validate in every kind; the evidence target is the formula's top suspect, never the whisper partner. |
| `test_moves.TwoMovePrompts` | (10) The move-2 prompt holds move 1, the challenge and move 1's note, pass 2; the challenge is the same after a silent move 1; listeners never see the note. |
| `test_moves_build.Flags` | (4) accused, on job, blown, job score, no_claim_yet, partner alive, round bucket, origin, open_claim and open_whisper rules, fallback turns excluded, whisper cutoffs, on hand-made logs. |
| `test_moves_build.SelectionRule`, `Freeze` | (5) Deterministic; origins level after every turn of the outer wheel, cells visited in turn within an origin, more cells give an origin nothing; at most 4 per game and one per (game, round, mole); target default and cap; halves by seed parity, no game in both; manifests; balanced panel rotation; refuses to overwrite; `verify` (with `--raw`) catches a changed set file, a re-hashed edited prompt and a changed source log. |
| `test_moves_run.RunLoop` | (8) "before" asked once and reused; resume; prefix limit; labels apart; parallel cap; invalid and blocked answers final; transport failures asked again and counted apart; OLD then NEW reading gives NEW and a second listen asks nothing; `--real-calls` required; mismatched `[limits]` refused; `ask_turn` matches `probes.ask_probe`; the client factory. |
| `test_moves_run.Maths` | (9) Raw, relative, rank change; the paired estimator (g1 two moments at -10, g2 one at +20: headline +5.0, pooled 0.0); pairs, M3 differences and M5 on per-game means; by kind and family; Fabricate; compliant Conceal; the floor; the 5% rule; the screen (all four before slots, A/B paired by slot, missing readings not screened). |
| `test_moves_run.EndToEnd` | (10, 11) The whole CLI with `--mock` in a temporary folder, two-move included; fixed screen; below-floor output; nothing written under `games/` or `probes/`. |
