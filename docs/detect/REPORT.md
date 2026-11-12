# Detect (Bench v2, Phase 6): report of the build session

2026-11-11. No model was called. Nothing in the live repository was written.

Work folder: a scratch copy of the repository (not published).

Untouched copy it is diffed against: a second scratch copy (not published) (the live code as it stood at
15:14 UTC). Diff of code, tests, config and docs: `docs/detect/detect.diff` (3,358 lines,
16 files). Full write-up: `docs/detect/DETECT.md`.

## Verdicts

**D1, scripted tuning: NOT MET.** A setting does land in the band, but it is the wrong kind of
setting and it fails the second half of the mark.

- Walking the grid from most clues to fewest, the first setting with the formula's error between
  0.09 and 0.13 is the very first one, **G1: every player gets a clue every round, roles hidden**.
  Error 0.100 (200 scripted games, 872 crew voters, 95% interval 0.088 to 0.112). That is more
  clues than today, not fewer.
- At G1 the formula's two highest-rated players are the two moles in **51.2%** of cases (interval
  45.1% to 57.6%). The mark for "no longer solves it" is under 40%. Under today's rules, same
  seeds: 41.4% (35.7% to 47.6%), error 0.135 (0.122 to 0.149).
- No setting meets both halves. The nine settings with fewer clues are under 40% (35.0% down to
  10.0%) but their error is above the band (0.140 up to 0.220; knowing nothing scores 0.222).

**D2, does the talk carry signal: FAIL.** The fixed no-model reader beat the masked formula by
0.0058 on 830 crew vote turns in 75 finished games (formula 0.1539, reader 0.1481; 95% interval
−0.0005 to +0.0114). The mark is at least 0.01 with an interval that excludes zero. By the rule
written first, **Detect is not run on models.**

Neither mark, nor anything in `docs/DETECT_RULES.md`, was changed after the numbers.

## What the numbers say beyond pass and fail

Fixed in advance as "shown beside the mark":
- The reader's gain is all in **round 1**: +0.0148 (375 vote turns, interval +0.0062 to +0.0230).
  Round 1 has no revealed role to leak, so this is the talk. From round 2 on: −0.0015
  (455 turns, −0.0099 to +0.0061).
- Rescaling the formula without any talk does nothing (−0.0005), so the small gain is from the
  talk features.

Computed after the verdicts, deciding nothing (`analysis/detect_explore_after.py`):
- In scripted games the formula's error depends mostly on how long the game lasts. Under today's
  rules: last vote in round 1 (88 of 200 games) error 0.231, solved 2.5%; round 2 (62 games)
  0.097, 55%; round 3 (50 games) 0.015, 93%. Scripted moles win fast (crew win 19% of scripted
  games; in the 75 real games the crew won 80% and only 2 ended their voting in round 1). So
  the scripted "last vote" is not like a real one, and that is why today's rules already sit
  above the band with these bots.
- On the 75 real games, at the last vote, hiding the roles barely moves the formula: error 0.088
  (0.072 to 0.104) as played, 0.097 (0.081 to 0.114) masked; top two are the two moles in 59.6%
  and 57.5%. The formula's strength is in the clue cards and job results, not in the reveals.

## What was built (all tested, none run on a model)

1. **Rules v0.5 "blind"**, two dials, both off by default: `hide_roles` and `clue_round_pct`
   (chance in 100, each round, that any clues go out; needed because the existing dials cannot
   go below about one clue a round).
   With both off, play is byte-identical to the untouched copy: 99 seeded games (9 mock-model,
   90 scripted), 959 prompts, 15,798 log lines, and the existing formulas at 1,518 vote turns,
   all equal. Left out of the comparison: `wall_s`, and in the one stamped game `code_hash` and
   `code_files`. Leaks decided in writing: `docs/DETECT.md`, section 2.
2. **The blind formula**: `probes.formulas` on a record with hidden roles; uses only that a mole
   is still in. Existing functions unchanged on today's games (same 1,518 turns).
3. **`docs/DETECT_RULES.md`**, hashed (`b6826522…de19e`) before the first tuning run.
4. **D1 and D2 runners**, **D3 scoring** (`inside_job/detect.py`), and `config/detect_blind.toml`
   (marked not approved for model runs).

Commands (run in the work folder; each is zero calls, about 35 seconds):
- `python3.11 -m inside_job.detect d1 --config config/headroom.toml --out analysis/out/detect`
- `python3.11 -m inside_job.detect d2 --manifest docs/DETECT_D2_GAMES.json --games games --out analysis/out/detect`
- `python3.11 -m inside_job.detect score --games games --batch NAME` (new-rules games only)

## Tests

Full suite in the work folder: **498 tests, all pass, 4 skipped** (174 seconds), run as
`env -u OPENROUTER_API_KEY TMPDIR=<scratch> python3.11 -m unittest discover -s tests`.
The 4 skipped are existing tests that need data the copy does not have (two need the frontier
logs, one `games/index.jsonl`, one the pilot 1 logs). None of the 57 new tests is skipped
there. Once merged into the live folder, one new test will skip: the one that plays the same
games in an untouched copy of the code (it looks for a folder `orig` beside the code, or
`INSIDE_JOB_BASELINE`); the stored digest of the untouched copy's games still runs.

## Files

New: `inside_job/detect.py` (794 lines), `tests/test_v05.py` (23 tests), `tests/test_detect.py`
(34 tests), `tests/dump_default_play.py`, `tests/fixtures/v05_defaults/digest.json`,
`config/detect_blind.toml`, `docs/DETECT.md`, `docs/DETECT_RULES.md`, `docs/DETECT_RULES.sha256`,
`docs/DETECT_D2_GAMES.json`, `analysis/detect_explore_after.py`, `analysis/out/detect/` (5 files).

Changed (lines added / removed):
- In the code stamp: `inside_job/config.py` +22 −1, `engine.py` +35 −14, `log.py` +4 −0,
  `prompts.py` +85 −18, `RULES.md` +6 −0.
- Not in the stamp: `inside_job/solver.py` +27 −11, `probes.py` +10 −3, `bots.py` +15 −11.
- Not touched: `openrouter.py`, `llm.py`, `schemas.py`, `clues.py`, `__main__.py`, `moves.py`,
  viewer files.

For the merge: `config.py` changes are in three places only (two fields at the end of
`GameConfig` with `v05_dials()`, six lines at the top of `Config.to_dict`, six lines in
`validate` after the v0.4 checks). The code stamp of the merged code will differ from `0800d943`.

## Departures from docs/BENCH_V2.md

1. BENCH_V2 says "fewer clues are dealt". The grid also has three settings with more clues than
   today, and the walk stopped on the one with the most.
2. A new dial, `clue_round_pct`, was added (the brief allowed one).
3. A game with a v0.5 dial on logs `rules_version` "0.5"; a dial at its default is not written
   into the logged config (that is what keeps old log lines identical).
4. D2 has a control and three side analyses fixed in advance (rescaled formula; round 1 against
   later rounds; leave one seed out). They are stricter readings, and none changes the mark.
5. D2 used all 75 finished batch games, show games (pilot 1 and 2) and Bluff games alike,
   odd and even seeds alike. Only totals are reported.
6. The commands live under `python3.11 -m inside_job.detect`, not in the main command file,
   which other sessions are editing.
7. The reader, the score and their tests were written before `DETECT_RULES.md` (so the file
   could describe real code), and run on real data only after it was hashed. The blind config
   was written after D1 because it needs the density.

## Ruling after the numbers (2026-11-11, about 15:40 UTC)

D1 is read as needing both halves: a setting in the band, and under 40% solved at that setting.
The first setting in the band fails the 40% mark; the walk was not continued to look for
another, and no later setting is in the band anyway.

## What I am unsure of

- **Whether D1's measure suits scripted games at all.** It is taken at "the last vote of the
  game", and scripted moles end nearly half the games after one vote. A fixed round, or moles
  that hold back (the existing `hold1` bots), would test clue density more cleanly. That would be
  a new test with a new hashed file, not a rerun of this one.
- **D2 is a near miss in a specific shape**: clear gain in round 1, none later. The reader and
  its 12 features were fixed first and are deliberately simple; a failed simple reader does not
  show that models cannot read the talk.
- **Masked old games are not blind games.** The players of those 75 games saw the reveals.
- **The blind prompt wording** is mine and no model or person has read it in play.
- The heading of `DETECT_RULES.md` says 15:36 UTC; the file was hashed at 15:35:31 by this
  machine's clock, seconds before the D1 run started.
- Not updated for blind games: `analysis/common.py` (rebuilds prompt context by hand), and the
  viewer, transcript and report, which would still say "revealed as" to the audience. The saved
  baseline copy of the code cannot read a blind game's log.
