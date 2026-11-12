# v0.4 candidate rules: scripted-bot results (phase A)

Facts only; no rule is recommended here (docs/V04.md, "Bot results"). Scripted bots only, no
model calls. Every cell plays seeds 1-300 (paired: the same deals in every cell) with
`--mole-cards decoy`; 84 commands, 128 cells, 38,400 games, **0 fallbacks** in every cell.
Run on 2026-11-10 from the code in this folder after the v0.4 build (`docs/V04.md`, Build notes).

Every command was run from the project root with `OUT` set to a scratch folder outside the
project (`--out` only adds the per-cell / per-game JSONL files the tables were built from; it
changes no game). The commands are given exactly as run, above each table.

**Columns.** crew win with a 95% Wilson interval; end reasons as % of games (`clean` =
jobs_clean, `out` = moles_out, `sab` = sabotage, `score` = mole_score); mean rounds; mean blown
jobs; mean crew members voted out; **nobody out** = share of votes that ejected nobody (`-` when
the vote has no `nobody` option); **team rejected** = share of team votes rejected (`-` without
`team_approval`); sabotage per chance (a mole on a job); share of games with no blown job; share
of games over by round 2; **FA hit** = share of Final Accusations that named a mole, with the
number of games that held one (`-` without `endings = "stakes"`).

## Read this before the numbers: what the bots do that real players would not

These are properties of the bots as written to the contract, measured, not tuned away.

- **The approval rule rejects almost every round-1 team.** A crew bot approves when its
  probability that the team holds a mole is below 0.45. With no evidence that probability is 0.6
  for a three-person team the bot is on and 0.8 for one it is not on, so at the default threshold
  round-1 teams were rejected in 299 of 300 games at skill 0.7 and 300 of 300 at skill 1.0
  (full v0.4, smart moles). By round: R1 299/300, R2 235/300, R3 193/294, R4 130/248, R5 39/99
  (skill 0.7). Crew leaders rejected their own team in 394 of 891 debates (skill 0.7) and 258 of
  823 (skill 1.0). So in these runs `team_approval` mostly acts as "the lead passes one seat and
  that leader's team goes", plus a statement round before the job. Forced teams held a mole 530
  of 896 times (skill 0.7). Mole `blend` bots reject on the same public arithmetic.
- **Moles never vote `nobody`; crew rarely do.** In unforced votes (full v0.4, smart) crew bots
  voted `nobody` 402 of 4,046 times (10%) at skill 0.7 and 316 of 3,982 (8%) at skill 1.0; mole
  bots 0 of 1,646 and 0 of 1,606. Votes are public, so "always votes to eject" is a tell that a
  real table could use. The logician bots read no behaviour, so the tell is never punished here:
  the moles' numbers under `vote_nobody` are probably flattering to the moles for that reason.
- **"Nobody out" is mostly split votes, not abstention.** With crew bots voting `nobody` only
  about one time in ten, the 42-70% nobody-out shares below come mainly from no player reaching a
  strict majority. A crew bot's belief in its top suspect starts at 1/3 (two moles among six
  others), so `eject_threshold` 0.3 makes crew always vote for someone, and 0.3 and 0.4 give
  nearly the same cells.
- **Endings do not change who wins for bots.** The bots' play before the end does not depend on
  `endings`; the pilot cells with `endings = "stakes"` are the same games as the baseline (same
  win rates), and full v0.4 minus endings matches full v0.4. Only the Final Accusation hit rate
  is new information.
- **`always` and `smart` moles play almost the same** under every rule set (they differ only when
  both moles are on one team). `never` moles were run in sections 1 and 2 only, as the contract
  lists.
- The logician crew uses clue cards, job results and reveals only (SPEC section 12). Real crews
  beat these bots by a wide margin under v0.3 (pilot 1: 95% crew wins against about 60% for
  skill-0.7 bots), so the levels below are not predictions for models; the differences between
  cells are what the bots can show.

Diagnostic figures in the bullets above come from a script outside the project that replays the
same games (`play_bot_game(load_config("config/v04_bots.toml"), seed, crew_skill=..., moles="smart")`,
seeds 1-300) and counts `team_vote`, `job_pick` and `vote_result` events. A second such count
(seeds 1-200, skill 0.7, smart): under `pilot.toml` 60% of executed jobs had a mole on the team
and 33% were mole-led; with `team_approval = true, discussion_passes = 1` added, 47% and 24%.

## 1. Baseline: `config/pilot.toml`

```
for skill in 0.5 0.7 1.0; do for moles in smart always never hold1; do
  python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/pilot.toml --crew-skill $skill --moles $moles --out "$OUT/base-$skill-$moles"
done; done
```

| crew skill, moles | crew win (95% CI) | end reasons (% of games) | rounds | blown | crew ejected | nobody out (% of votes) | team rejected (% of team votes) | sabotage / chance | 0 blown | over by R2 | FA hit (of games held) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| skill 0.5, smart | **42.0%** (37-48) | clean 8 out 34 sab 58 | 3.55 | 2.42 | 1.92 | - | - | 93% | 1% | 6% | - |
| skill 0.5, always | **45.0%** (39-51) | clean 7 out 38 sab 55 | 3.53 | 2.38 | 1.88 | - | - | 100% | 1% | 7% | - |
| skill 0.5, never | **100.0%** (99-100) | clean 98 out 2 | 2.98 | 0.00 | 1.73 | - | - | 0% | 100% | 2% | - |
| skill 0.5, hold1 | **55.7%** (50-61) | clean 24 out 32 sab 44 | 3.96 | 2.03 | 2.38 | - | - | 67% | 10% | 3% | - |
| skill 0.7, smart | **59.7%** (54-65) | clean 9 out 51 sab 40 | 3.47 | 2.15 | 1.73 | - | - | 95% | 1% | 8% | - |
| skill 0.7, always | **60.7%** (55-66) | clean 8 out 52 sab 39 | 3.45 | 2.14 | 1.69 | - | - | 100% | 1% | 9% | - |
| skill 0.7, never | **100.0%** (99-100) | clean 98 out 2 | 2.98 | 0.00 | 1.73 | - | - | 0% | 100% | 2% | - |
| skill 0.7, hold1 | **71.7%** (66-76) | clean 30 out 42 sab 28 | 3.88 | 1.75 | 2.18 | - | - | 66% | 10% | 3% | - |
| skill 1.0, smart | **82.3%** (78-86) | clean 20 out 62 sab 18 | 3.46 | 1.79 | 1.57 | - | - | 98% | 4% | 4% | - |
| skill 1.0, always | **82.7%** (78-87) | clean 20 out 63 sab 17 | 3.44 | 1.78 | 1.55 | - | - | 100% | 4% | 5% | - |
| skill 1.0, never | **100.0%** (99-100) | clean 98 out 2 | 2.98 | 0.00 | 1.69 | - | - | 0% | 100% | 2% | - |
| skill 1.0, hold1 | **90.0%** (86-93) | clean 47 out 43 sab 10 | 3.62 | 1.27 | 1.82 | - | - | 63% | 21% | 3% | - |

## 2. Full v0.4: `config/v04_bots.toml`

```
for skill in 0.5 0.7 1.0; do for moles in smart always never hold1; do
  python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill $skill --moles $moles --out "$OUT/full-$skill-$moles"
done; done
```

| crew skill, moles | crew win (95% CI) | end reasons (% of games) | rounds | blown | crew ejected | nobody out (% of votes) | team rejected (% of team votes) | sabotage / chance | 0 blown | over by R2 | FA hit (of games held) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| skill 0.5, smart | **55.0%** (49-61) | clean 43 out 12 score 45 | 4.16 | 2.21 | 0.79 | 62% | 77% | 92% | 4% | 1% | 65% of 130 |
| skill 0.5, always | **58.3%** (53-64) | clean 46 out 12 score 42 | 4.18 | 2.17 | 0.76 | 62% | 76% | 100% | 4% | 1% | 66% of 138 |
| skill 0.5, never | **100.0%** (99-100) | clean 100 | 3.00 | 0.00 | 0.71 | 63% | 93% | 0% | 100% | 0% | 27% of 300 |
| skill 0.5, hold1 | **68.3%** (63-73) | clean 62 out 6 score 32 | 4.13 | 1.65 | 0.94 | 61% | 82% | 63% | 14% | 0% | 54% of 187 |
| skill 0.7, smart | **70.7%** (65-76) | clean 53 out 17 score 29 | 4.14 | 1.90 | 0.81 | 58% | 72% | 93% | 4% | 2% | 76% of 160 |
| skill 0.7, always | **70.7%** (65-76) | clean 53 out 18 score 29 | 4.13 | 1.88 | 0.79 | 58% | 71% | 100% | 4% | 2% | 75% of 159 |
| skill 0.7, never | **100.0%** (99-100) | clean 100 | 3.00 | 0.00 | 0.94 | 51% | 91% | 0% | 100% | 0% | 40% of 300 |
| skill 0.7, hold1 | **76.7%** (72-81) | clean 72 out 5 score 23 | 4.02 | 1.41 | 1.05 | 57% | 82% | 62% | 17% | 0% | 68% of 216 |
| skill 1.0, smart | **89.3%** (85-92) | clean 58 out 31 score 11 | 3.83 | 1.50 | 0.84 | 46% | 66% | 98% | 8% | 6% | 90% of 175 |
| skill 1.0, always | **89.3%** (85-92) | clean 58 out 31 score 11 | 3.82 | 1.49 | 0.83 | 46% | 66% | 100% | 8% | 6% | 90% of 174 |
| skill 1.0, never | **100.0%** (99-100) | clean 100 | 3.00 | 0.00 | 1.07 | 42% | 88% | 0% | 100% | 0% | 54% of 300 |
| skill 1.0, hold1 | **92.7%** (89-95) | clean 83 out 10 score 7 | 3.84 | 1.05 | 1.08 | 48% | 76% | 60% | 26% | 0% | 84% of 248 |

## 3. One dial at a time, and full v0.4 minus one dial

Dial groups: `score+nobody` = `mole_score_target = 4` + `vote_nobody = true` (with the default
`forced_vote_after = 2`); `approval` = `team_approval = true` + `discussion_passes = 1` (switched
off: `false` + `2`; see Build notes); `whispers` = `whisper_pairing = "random"` + `clue_turn = false`
+ `whisper_exchanges = 1`; `endings` = `endings = "stakes"`; `unique` = `unique_clues = true`. The
reference cells are in sections 1 (pilot.toml) and 2 (full v0.4).

### 3a. One dial on top of `pilot.toml`

#### one `score+nobody`

```
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/pilot.toml --crew-skill 0.7 --moles smart --set mole_score_target=4 --set vote_nobody=true --out "$OUT/one-score+nobody-0.7-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/pilot.toml --crew-skill 0.7 --moles hold1 --set mole_score_target=4 --set vote_nobody=true --out "$OUT/one-score+nobody-0.7-hold1"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/pilot.toml --crew-skill 1.0 --moles smart --set mole_score_target=4 --set vote_nobody=true --out "$OUT/one-score+nobody-1.0-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/pilot.toml --crew-skill 1.0 --moles hold1 --set mole_score_target=4 --set vote_nobody=true --out "$OUT/one-score+nobody-1.0-hold1"
```

| cell | crew win (95% CI) | end reasons (% of games) | rounds | blown | crew ejected | nobody out (% of votes) | team rejected (% of team votes) | sabotage / chance | 0 blown | over by R2 | FA hit (of games held) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| skill 0.7, smart | **40.7%** (35-46) | clean 24 out 16 score 59 | 3.99 | 2.44 | 0.90 | 55% | - | 95% | 0% | 2% | - |
| skill 0.7, hold1 | **58.0%** (52-63) | clean 48 out 10 score 42 | 4.12 | 1.85 | 1.00 | 57% | - | 66% | 9% | 0% | - |
| skill 1.0, smart | **60.3%** (55-66) | clean 33 out 27 score 40 | 3.88 | 2.04 | 1.01 | 44% | - | 98% | 3% | 3% | - |
| skill 1.0, hold1 | **75.7%** (71-80) | clean 59 out 17 score 24 | 3.95 | 1.50 | 1.05 | 47% | - | 66% | 16% | 0% | - |

#### one `approval`

```
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/pilot.toml --crew-skill 0.7 --moles smart --set team_approval=true --set discussion_passes=1 --out "$OUT/one-approval-0.7-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/pilot.toml --crew-skill 0.7 --moles hold1 --set team_approval=true --set discussion_passes=1 --out "$OUT/one-approval-0.7-hold1"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/pilot.toml --crew-skill 1.0 --moles smart --set team_approval=true --set discussion_passes=1 --out "$OUT/one-approval-1.0-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/pilot.toml --crew-skill 1.0 --moles hold1 --set team_approval=true --set discussion_passes=1 --out "$OUT/one-approval-1.0-hold1"
```

| cell | crew win (95% CI) | end reasons (% of games) | rounds | blown | crew ejected | nobody out (% of votes) | team rejected (% of team votes) | sabotage / chance | 0 blown | over by R2 | FA hit (of games held) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| skill 0.7, smart | **85.0%** (81-89) | clean 26 out 59 sab 15 | 3.40 | 1.62 | 1.56 | - | 75% | 93% | 5% | 12% | - |
| skill 0.7, hold1 | **89.0%** (85-92) | clean 59 out 30 sab 11 | 3.71 | 1.20 | 2.00 | - | 80% | 57% | 21% | 4% | - |
| skill 1.0, smart | **99.0%** (97-100) | clean 30 out 69 sab 1 | 3.21 | 1.22 | 1.28 | - | 67% | 99% | 12% | 12% | - |
| skill 1.0, hold1 | **97.7%** (95-99) | clean 71 out 27 sab 2 | 3.51 | 0.80 | 1.73 | - | 74% | 51% | 31% | 3% | - |

#### one `whispers`

```
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/pilot.toml --crew-skill 0.7 --moles smart --set whisper_pairing=random --set clue_turn=false --set whisper_exchanges=1 --out "$OUT/one-whispers-0.7-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/pilot.toml --crew-skill 0.7 --moles hold1 --set whisper_pairing=random --set clue_turn=false --set whisper_exchanges=1 --out "$OUT/one-whispers-0.7-hold1"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/pilot.toml --crew-skill 1.0 --moles smart --set whisper_pairing=random --set clue_turn=false --set whisper_exchanges=1 --out "$OUT/one-whispers-1.0-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/pilot.toml --crew-skill 1.0 --moles hold1 --set whisper_pairing=random --set clue_turn=false --set whisper_exchanges=1 --out "$OUT/one-whispers-1.0-hold1"
```

| cell | crew win (95% CI) | end reasons (% of games) | rounds | blown | crew ejected | nobody out (% of votes) | team rejected (% of team votes) | sabotage / chance | 0 blown | over by R2 | FA hit (of games held) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| skill 0.7, smart | **62.3%** (57-68) | clean 12 out 50 sab 38 | 3.50 | 2.06 | 1.72 | - | - | 94% | 5% | 5% | - |
| skill 0.7, hold1 | **74.0%** (69-79) | clean 36 out 38 sab 26 | 3.78 | 1.60 | 2.03 | - | - | 65% | 15% | 4% | - |
| skill 1.0, smart | **83.3%** (79-87) | clean 19 out 64 sab 17 | 3.42 | 1.70 | 1.53 | - | - | 99% | 8% | 6% | - |
| skill 1.0, hold1 | **89.3%** (85-92) | clean 52 out 37 sab 11 | 3.65 | 1.21 | 1.87 | - | - | 63% | 24% | 3% | - |

#### one `endings`

```
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/pilot.toml --crew-skill 0.7 --moles smart --set endings=stakes --out "$OUT/one-endings-0.7-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/pilot.toml --crew-skill 0.7 --moles hold1 --set endings=stakes --out "$OUT/one-endings-0.7-hold1"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/pilot.toml --crew-skill 1.0 --moles smart --set endings=stakes --out "$OUT/one-endings-1.0-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/pilot.toml --crew-skill 1.0 --moles hold1 --set endings=stakes --out "$OUT/one-endings-1.0-hold1"
```

| cell | crew win (95% CI) | end reasons (% of games) | rounds | blown | crew ejected | nobody out (% of votes) | team rejected (% of team votes) | sabotage / chance | 0 blown | over by R2 | FA hit (of games held) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| skill 0.7, smart | **59.7%** (54-65) | clean 9 out 51 sab 40 | 3.47 | 2.15 | 1.73 | - | - | 95% | 1% | 8% | 85% of 27 |
| skill 0.7, hold1 | **71.7%** (66-76) | clean 30 out 42 sab 28 | 3.88 | 1.75 | 2.18 | - | - | 66% | 10% | 3% | 73% of 90 |
| skill 1.0, smart | **82.3%** (78-86) | clean 20 out 62 sab 18 | 3.46 | 1.79 | 1.57 | - | - | 98% | 4% | 4% | 80% of 60 |
| skill 1.0, hold1 | **90.0%** (86-93) | clean 47 out 43 sab 10 | 3.62 | 1.27 | 1.82 | - | - | 63% | 21% | 3% | 81% of 140 |

#### one `unique`

```
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/pilot.toml --crew-skill 0.7 --moles smart --set unique_clues=true --out "$OUT/one-unique-0.7-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/pilot.toml --crew-skill 0.7 --moles hold1 --set unique_clues=true --out "$OUT/one-unique-0.7-hold1"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/pilot.toml --crew-skill 1.0 --moles smart --set unique_clues=true --out "$OUT/one-unique-1.0-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/pilot.toml --crew-skill 1.0 --moles hold1 --set unique_clues=true --out "$OUT/one-unique-1.0-hold1"
```

| cell | crew win (95% CI) | end reasons (% of games) | rounds | blown | crew ejected | nobody out (% of votes) | team rejected (% of team votes) | sabotage / chance | 0 blown | over by R2 | FA hit (of games held) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| skill 0.7, smart | **62.0%** (56-67) | clean 17 out 45 sab 38 | 3.57 | 2.08 | 1.79 | - | - | 95% | 3% | 3% | - |
| skill 0.7, hold1 | **73.0%** (68-78) | clean 37 out 36 sab 27 | 3.84 | 1.64 | 2.12 | - | - | 64% | 14% | 3% | - |
| skill 1.0, smart | **82.0%** (77-86) | clean 20 out 62 sab 18 | 3.47 | 1.74 | 1.60 | - | - | 99% | 6% | 4% | - |
| skill 1.0, hold1 | **89.3%** (85-92) | clean 47 out 42 sab 11 | 3.61 | 1.24 | 1.85 | - | - | 62% | 23% | 4% | - |

### 3b. Full v0.4 minus one dial

#### minus `score+nobody`

```
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 0.7 --moles smart --set mole_score_target=0 --set vote_nobody=false --out "$OUT/minus-score+nobody-0.7-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 0.7 --moles hold1 --set mole_score_target=0 --set vote_nobody=false --out "$OUT/minus-score+nobody-0.7-hold1"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 1.0 --moles smart --set mole_score_target=0 --set vote_nobody=false --out "$OUT/minus-score+nobody-1.0-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 1.0 --moles hold1 --set mole_score_target=0 --set vote_nobody=false --out "$OUT/minus-score+nobody-1.0-hold1"
```

| cell | crew win (95% CI) | end reasons (% of games) | rounds | blown | crew ejected | nobody out (% of votes) | team rejected (% of team votes) | sabotage / chance | 0 blown | over by R2 | FA hit (of games held) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| skill 0.7, smart | **86.7%** (82-90) | clean 32 out 55 sab 13 | 3.43 | 1.54 | 1.60 | - | 76% | 94% | 6% | 11% | 74% of 95 |
| skill 0.7, hold1 | **88.3%** (84-91) | clean 60 out 28 sab 12 | 3.73 | 1.18 | 2.05 | - | 82% | 59% | 23% | 2% | 69% of 181 |
| skill 1.0, smart | **98.0%** (96-99) | clean 29 out 69 sab 2 | 3.14 | 1.21 | 1.25 | - | 69% | 99% | 9% | 16% | 84% of 88 |
| skill 1.0, hold1 | **96.7%** (94-98) | clean 69 out 28 sab 3 | 3.49 | 0.82 | 1.78 | - | 77% | 54% | 33% | 2% | 80% of 207 |

#### minus `approval`

```
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 0.7 --moles smart --set team_approval=false --set discussion_passes=2 --out "$OUT/minus-approval-0.7-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 0.7 --moles hold1 --set team_approval=false --set discussion_passes=2 --out "$OUT/minus-approval-0.7-hold1"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 1.0 --moles smart --set team_approval=false --set discussion_passes=2 --out "$OUT/minus-approval-1.0-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 1.0 --moles hold1 --set team_approval=false --set discussion_passes=2 --out "$OUT/minus-approval-1.0-hold1"
```

| cell | crew win (95% CI) | end reasons (% of games) | rounds | blown | crew ejected | nobody out (% of votes) | team rejected (% of team votes) | sabotage / chance | 0 blown | over by R2 | FA hit (of games held) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| skill 0.7, smart | **46.3%** (41-52) | clean 34 out 13 score 54 | 3.96 | 2.28 | 0.94 | 55% | - | 95% | 3% | 2% | 65% of 101 |
| skill 0.7, hold1 | **65.3%** (60-70) | clean 55 out 10 score 35 | 4.12 | 1.74 | 0.98 | 57% | - | 67% | 11% | 0% | 66% of 166 |
| skill 1.0, smart | **61.7%** (56-67) | clean 40 out 21 score 38 | 3.85 | 1.95 | 1.00 | 45% | - | 99% | 6% | 2% | 79% of 121 |
| skill 1.0, hold1 | **78.7%** (74-83) | clean 65 out 14 score 21 | 3.85 | 1.31 | 1.10 | 46% | - | 65% | 20% | 0% | 74% of 195 |

#### minus `whispers`

```
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 0.7 --moles smart --set whisper_pairing=chosen --set clue_turn=true --set whisper_exchanges=2 --out "$OUT/minus-whispers-0.7-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 0.7 --moles hold1 --set whisper_pairing=chosen --set clue_turn=true --set whisper_exchanges=2 --out "$OUT/minus-whispers-0.7-hold1"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 1.0 --moles smart --set whisper_pairing=chosen --set clue_turn=true --set whisper_exchanges=2 --out "$OUT/minus-whispers-1.0-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 1.0 --moles hold1 --set whisper_pairing=chosen --set clue_turn=true --set whisper_exchanges=2 --out "$OUT/minus-whispers-1.0-hold1"
```

| cell | crew win (95% CI) | end reasons (% of games) | rounds | blown | crew ejected | nobody out (% of votes) | team rejected (% of team votes) | sabotage / chance | 0 blown | over by R2 | FA hit (of games held) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| skill 0.7, smart | **72.3%** (67-77) | clean 49 out 23 score 28 | 4.09 | 1.94 | 0.75 | 57% | 74% | 94% | 4% | 2% | 78% of 147 |
| skill 0.7, hold1 | **82.3%** (78-86) | clean 76 out 6 score 18 | 4.04 | 1.37 | 0.98 | 57% | 82% | 60% | 17% | 0% | 70% of 228 |
| skill 1.0, smart | **91.7%** (88-94) | clean 60 out 32 score 8 | 3.85 | 1.45 | 0.85 | 44% | 68% | 97% | 9% | 6% | 89% of 179 |
| skill 1.0, hold1 | **89.7%** (86-93) | clean 79 out 10 score 10 | 3.78 | 1.05 | 1.13 | 46% | 77% | 60% | 24% | 1% | 84% of 238 |

#### minus `endings`

```
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 0.7 --moles smart --set endings=classic --out "$OUT/minus-endings-0.7-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 0.7 --moles hold1 --set endings=classic --out "$OUT/minus-endings-0.7-hold1"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 1.0 --moles smart --set endings=classic --out "$OUT/minus-endings-1.0-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 1.0 --moles hold1 --set endings=classic --out "$OUT/minus-endings-1.0-hold1"
```

| cell | crew win (95% CI) | end reasons (% of games) | rounds | blown | crew ejected | nobody out (% of votes) | team rejected (% of team votes) | sabotage / chance | 0 blown | over by R2 | FA hit (of games held) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| skill 0.7, smart | **70.7%** (65-76) | clean 53 out 17 score 29 | 4.14 | 1.90 | 0.81 | 58% | 72% | 93% | 4% | 2% | - |
| skill 0.7, hold1 | **76.7%** (72-81) | clean 72 out 5 score 23 | 4.02 | 1.41 | 1.05 | 57% | 82% | 62% | 17% | 0% | - |
| skill 1.0, smart | **89.3%** (85-92) | clean 58 out 31 score 11 | 3.83 | 1.50 | 0.84 | 46% | 66% | 98% | 8% | 6% | - |
| skill 1.0, hold1 | **92.7%** (89-95) | clean 83 out 10 score 7 | 3.84 | 1.05 | 1.08 | 48% | 76% | 60% | 26% | 0% | - |

#### minus `unique`

```
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 0.7 --moles smart --set unique_clues=false --out "$OUT/minus-unique-0.7-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 0.7 --moles hold1 --set unique_clues=false --out "$OUT/minus-unique-0.7-hold1"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 1.0 --moles smart --set unique_clues=false --out "$OUT/minus-unique-1.0-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 1.0 --moles hold1 --set unique_clues=false --out "$OUT/minus-unique-1.0-hold1"
```

| cell | crew win (95% CI) | end reasons (% of games) | rounds | blown | crew ejected | nobody out (% of votes) | team rejected (% of team votes) | sabotage / chance | 0 blown | over by R2 | FA hit (of games held) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| skill 0.7, smart | **72.3%** (67-77) | clean 52 out 21 score 28 | 4.13 | 1.88 | 0.80 | 57% | 72% | 93% | 5% | 1% | 80% of 155 |
| skill 0.7, hold1 | **80.3%** (75-84) | clean 73 out 8 score 20 | 4.07 | 1.43 | 0.99 | 57% | 80% | 63% | 16% | 0% | 74% of 218 |
| skill 1.0, smart | **93.7%** (90-96) | clean 67 out 27 score 6 | 3.94 | 1.46 | 0.83 | 48% | 67% | 97% | 9% | 4% | 86% of 200 |
| skill 1.0, hold1 | **94.3%** (91-96) | clean 83 out 11 score 6 | 3.83 | 1.03 | 1.02 | 50% | 75% | 59% | 25% | 0% | 82% of 249 |

## 4. Sweeps on full v0.4

The default value of each swept dial reproduces the section 2 cell exactly (same seeds).

#### `--sweep mole_score_target=3,4,5`

```
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 0.7 --moles smart --sweep mole_score_target=3,4,5 --out "$OUT/sw-msc-0.7-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 0.7 --moles hold1 --sweep mole_score_target=3,4,5 --out "$OUT/sw-msc-0.7-hold1"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 1.0 --moles smart --sweep mole_score_target=3,4,5 --out "$OUT/sw-msc-1.0-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 1.0 --moles hold1 --sweep mole_score_target=3,4,5 --out "$OUT/sw-msc-1.0-hold1"
```

| cell | crew win (95% CI) | end reasons (% of games) | rounds | blown | crew ejected | nobody out (% of votes) | team rejected (% of team votes) | sabotage / chance | 0 blown | over by R2 | FA hit (of games held) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| skill 0.7, smart, mole_score_target=3 | **43.3%** (38-49) | clean 30 out 13 score 57 | 3.25 | 1.67 | 0.75 | 55% | 78% | 93% | 4% | 23% | 71% of 90 |
| skill 0.7, smart, mole_score_target=4 | **70.7%** (65-76) | clean 53 out 17 score 29 | 4.14 | 1.90 | 0.81 | 58% | 72% | 93% | 4% | 2% | 76% of 160 |
| skill 0.7, smart, mole_score_target=5 | **91.7%** (88-94) | clean 68 out 24 score 8 | 4.53 | 1.95 | 0.85 | 57% | 69% | 93% | 4% | 1% | 74% of 204 |
| skill 0.7, hold1, mole_score_target=3 | **50.7%** (45-56) | clean 47 out 4 score 49 | 3.45 | 1.26 | 0.96 | 55% | 86% | 60% | 17% | 5% | 63% of 140 |
| skill 0.7, hold1, mole_score_target=4 | **76.7%** (72-81) | clean 72 out 5 score 23 | 4.02 | 1.41 | 1.05 | 57% | 82% | 62% | 17% | 0% | 68% of 216 |
| skill 0.7, hold1, mole_score_target=5 | **91.7%** (88-94) | clean 84 out 8 score 8 | 4.28 | 1.47 | 1.07 | 56% | 80% | 63% | 17% | 0% | 68% of 251 |
| skill 1.0, smart, mole_score_target=3 | **57.7%** (52-63) | clean 32 out 26 score 42 | 3.09 | 1.43 | 0.81 | 43% | 74% | 98% | 8% | 24% | 84% of 95 |
| skill 1.0, smart, mole_score_target=4 | **89.3%** (85-92) | clean 58 out 31 score 11 | 3.83 | 1.50 | 0.84 | 46% | 66% | 98% | 8% | 6% | 90% of 175 |
| skill 1.0, smart, mole_score_target=5 | **99.7%** (98-100) | clean 63 out 37 score 0 | 3.98 | 1.51 | 0.84 | 46% | 64% | 98% | 8% | 6% | 90% of 189 |
| skill 1.0, hold1, mole_score_target=3 | **64.3%** (59-70) | clean 57 out 8 score 36 | 3.36 | 1.01 | 1.06 | 47% | 82% | 59% | 26% | 5% | 80% of 170 |
| skill 1.0, hold1, mole_score_target=4 | **92.7%** (89-95) | clean 83 out 10 score 7 | 3.84 | 1.05 | 1.08 | 48% | 76% | 60% | 26% | 0% | 84% of 248 |
| skill 1.0, hold1, mole_score_target=5 | **98.0%** (96-99) | clean 86 out 12 score 2 | 3.91 | 1.07 | 1.09 | 48% | 75% | 60% | 26% | 0% | 84% of 258 |

#### `--sweep bot.eject_threshold=0.3,0.4,0.5,0.6,0.7,0.8`

```
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 0.7 --moles smart --sweep bot.eject_threshold=0.3,0.4,0.5,0.6,0.7,0.8 --out "$OUT/sw-eject-0.7-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 0.7 --moles hold1 --sweep bot.eject_threshold=0.3,0.4,0.5,0.6,0.7,0.8 --out "$OUT/sw-eject-0.7-hold1"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 1.0 --moles smart --sweep bot.eject_threshold=0.3,0.4,0.5,0.6,0.7,0.8 --out "$OUT/sw-eject-1.0-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 1.0 --moles hold1 --sweep bot.eject_threshold=0.3,0.4,0.5,0.6,0.7,0.8 --out "$OUT/sw-eject-1.0-hold1"
```

| cell | crew win (95% CI) | end reasons (% of games) | rounds | blown | crew ejected | nobody out (% of votes) | team rejected (% of team votes) | sabotage / chance | 0 blown | over by R2 | FA hit (of games held) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| skill 0.7, smart, bot.eject_threshold=0.3 | **69.3%** (64-74) | clean 52 out 17 score 31 | 4.10 | 1.89 | 0.86 | 56% | 73% | 94% | 3% | 2% | 78% of 157 |
| skill 0.7, smart, bot.eject_threshold=0.4 | **69.7%** (64-75) | clean 53 out 17 score 30 | 4.11 | 1.88 | 0.85 | 56% | 73% | 94% | 3% | 2% | 77% of 158 |
| skill 0.7, smart, bot.eject_threshold=0.5 | **70.7%** (65-76) | clean 53 out 17 score 29 | 4.14 | 1.90 | 0.81 | 58% | 72% | 93% | 4% | 2% | 76% of 160 |
| skill 0.7, smart, bot.eject_threshold=0.6 | **75.0%** (70-80) | clean 58 out 17 score 25 | 4.17 | 1.87 | 0.68 | 61% | 71% | 94% | 7% | 1% | 76% of 174 |
| skill 0.7, smart, bot.eject_threshold=0.7 | **78.7%** (74-83) | clean 58 out 21 score 21 | 4.22 | 1.90 | 0.53 | 65% | 70% | 94% | 8% | 0% | 75% of 174 |
| skill 0.7, smart, bot.eject_threshold=0.8 | **80.0%** (75-84) | clean 57 out 23 score 20 | 4.24 | 1.92 | 0.46 | 66% | 70% | 95% | 8% | 0% | 73% of 171 |
| skill 0.7, hold1, bot.eject_threshold=0.3 | **74.3%** (69-79) | clean 70 out 4 score 26 | 4.00 | 1.42 | 1.13 | 54% | 82% | 62% | 17% | 0% | 70% of 210 |
| skill 0.7, hold1, bot.eject_threshold=0.4 | **74.7%** (69-79) | clean 71 out 4 score 25 | 4.01 | 1.41 | 1.12 | 54% | 82% | 62% | 17% | 0% | 70% of 212 |
| skill 0.7, hold1, bot.eject_threshold=0.5 | **76.7%** (72-81) | clean 72 out 5 score 23 | 4.02 | 1.41 | 1.05 | 57% | 82% | 62% | 17% | 0% | 68% of 216 |
| skill 0.7, hold1, bot.eject_threshold=0.6 | **88.3%** (84-91) | clean 82 out 7 score 12 | 4.04 | 1.27 | 0.70 | 66% | 78% | 60% | 21% | 0% | 62% of 245 |
| skill 0.7, hold1, bot.eject_threshold=0.7 | **92.3%** (89-95) | clean 83 out 9 score 8 | 3.99 | 1.20 | 0.52 | 69% | 76% | 59% | 24% | 0% | 61% of 250 |
| skill 0.7, hold1, bot.eject_threshold=0.8 | **94.0%** (91-96) | clean 83 out 11 score 6 | 3.99 | 1.19 | 0.47 | 70% | 75% | 59% | 23% | 0% | 60% of 250 |
| skill 1.0, smart, bot.eject_threshold=0.3 | **89.0%** (85-92) | clean 57 out 32 score 11 | 3.74 | 1.45 | 0.88 | 42% | 66% | 98% | 8% | 9% | 88% of 170 |
| skill 1.0, smart, bot.eject_threshold=0.4 | **89.0%** (85-92) | clean 57 out 32 score 11 | 3.74 | 1.46 | 0.86 | 43% | 66% | 98% | 8% | 9% | 88% of 170 |
| skill 1.0, smart, bot.eject_threshold=0.5 | **89.3%** (85-92) | clean 58 out 31 score 11 | 3.83 | 1.50 | 0.84 | 46% | 66% | 98% | 8% | 6% | 90% of 175 |
| skill 1.0, smart, bot.eject_threshold=0.6 | **93.3%** (90-96) | clean 65 out 28 score 7 | 4.04 | 1.52 | 0.60 | 56% | 64% | 97% | 10% | 1% | 84% of 196 |
| skill 1.0, smart, bot.eject_threshold=0.7 | **95.7%** (93-97) | clean 61 out 35 score 4 | 4.06 | 1.56 | 0.35 | 62% | 62% | 97% | 13% | 0% | 79% of 182 |
| skill 1.0, smart, bot.eject_threshold=0.8 | **96.7%** (94-98) | clean 60 out 36 score 3 | 4.07 | 1.56 | 0.31 | 63% | 61% | 97% | 12% | 0% | 80% of 181 |
| skill 1.0, hold1, bot.eject_threshold=0.3 | **88.3%** (84-91) | clean 79 out 9 score 12 | 3.79 | 1.06 | 1.24 | 42% | 78% | 60% | 27% | 0% | 81% of 238 |
| skill 1.0, hold1, bot.eject_threshold=0.4 | **88.3%** (84-91) | clean 79 out 9 score 12 | 3.79 | 1.06 | 1.22 | 42% | 78% | 60% | 27% | 0% | 81% of 237 |
| skill 1.0, hold1, bot.eject_threshold=0.5 | **92.7%** (89-95) | clean 83 out 10 score 7 | 3.84 | 1.05 | 1.08 | 48% | 76% | 60% | 26% | 0% | 84% of 248 |
| skill 1.0, hold1, bot.eject_threshold=0.6 | **98.3%** (96-99) | clean 87 out 11 score 2 | 3.83 | 0.98 | 0.70 | 61% | 73% | 58% | 27% | 0% | 79% of 262 |
| skill 1.0, hold1, bot.eject_threshold=0.7 | **99.7%** (98-100) | clean 86 out 14 score 0 | 3.78 | 0.93 | 0.40 | 68% | 71% | 56% | 30% | 0% | 74% of 258 |
| skill 1.0, hold1, bot.eject_threshold=0.8 | **99.0%** (97-100) | clean 85 out 14 score 1 | 3.79 | 0.95 | 0.35 | 70% | 71% | 57% | 29% | 0% | 73% of 256 |

#### `--sweep bot.approve_threshold=0.3,0.45,0.6`

```
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 0.7 --moles smart --sweep bot.approve_threshold=0.3,0.45,0.6 --out "$OUT/sw-approve-0.7-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 0.7 --moles hold1 --sweep bot.approve_threshold=0.3,0.45,0.6 --out "$OUT/sw-approve-0.7-hold1"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 1.0 --moles smart --sweep bot.approve_threshold=0.3,0.45,0.6 --out "$OUT/sw-approve-1.0-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 1.0 --moles hold1 --sweep bot.approve_threshold=0.3,0.45,0.6 --out "$OUT/sw-approve-1.0-hold1"
```

| cell | crew win (95% CI) | end reasons (% of games) | rounds | blown | crew ejected | nobody out (% of votes) | team rejected (% of team votes) | sabotage / chance | 0 blown | over by R2 | FA hit (of games held) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| skill 0.7, smart, bot.approve_threshold=0.3 | **68.7%** (63-74) | clean 51 out 18 score 31 | 4.11 | 1.93 | 0.82 | 57% | 78% | 94% | 3% | 2% | 73% of 153 |
| skill 0.7, smart, bot.approve_threshold=0.45 | **70.7%** (65-76) | clean 53 out 17 score 29 | 4.14 | 1.90 | 0.81 | 58% | 72% | 93% | 4% | 2% | 76% of 160 |
| skill 0.7, smart, bot.approve_threshold=0.6 | **77.0%** (72-81) | clean 58 out 19 score 23 | 4.14 | 1.79 | 0.82 | 57% | 55% | 93% | 6% | 2% | 79% of 175 |
| skill 0.7, hold1, bot.approve_threshold=0.3 | **76.7%** (72-81) | clean 70 out 7 score 23 | 4.04 | 1.45 | 1.04 | 56% | 85% | 63% | 15% | 0% | 68% of 209 |
| skill 0.7, hold1, bot.approve_threshold=0.45 | **76.7%** (72-81) | clean 72 out 5 score 23 | 4.02 | 1.41 | 1.05 | 57% | 82% | 62% | 17% | 0% | 68% of 216 |
| skill 0.7, hold1, bot.approve_threshold=0.6 | **81.3%** (77-85) | clean 75 out 7 score 19 | 3.97 | 1.29 | 1.05 | 56% | 65% | 61% | 18% | 0% | 71% of 224 |
| skill 1.0, smart, bot.approve_threshold=0.3 | **87.7%** (83-91) | clean 55 out 32 score 12 | 3.82 | 1.52 | 0.84 | 45% | 72% | 98% | 8% | 5% | 89% of 166 |
| skill 1.0, smart, bot.approve_threshold=0.45 | **89.3%** (85-92) | clean 58 out 31 score 11 | 3.83 | 1.50 | 0.84 | 46% | 66% | 98% | 8% | 6% | 90% of 175 |
| skill 1.0, smart, bot.approve_threshold=0.6 | **90.3%** (86-93) | clean 60 out 30 score 10 | 3.84 | 1.48 | 0.87 | 47% | 48% | 97% | 11% | 7% | 89% of 180 |
| skill 1.0, hold1, bot.approve_threshold=0.3 | **92.0%** (88-95) | clean 80 out 12 score 8 | 3.83 | 1.09 | 1.07 | 47% | 80% | 61% | 25% | 0% | 82% of 240 |
| skill 1.0, hold1, bot.approve_threshold=0.45 | **92.7%** (89-95) | clean 83 out 10 score 7 | 3.84 | 1.05 | 1.08 | 48% | 76% | 60% | 26% | 0% | 84% of 248 |
| skill 1.0, hold1, bot.approve_threshold=0.6 | **92.7%** (89-95) | clean 81 out 11 score 7 | 3.80 | 1.03 | 1.10 | 47% | 57% | 59% | 27% | 0% | 84% of 244 |

#### `--sweep forced_vote_after=0,1,2`

```
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 0.7 --moles smart --sweep forced_vote_after=0,1,2 --out "$OUT/sw-forced-0.7-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 0.7 --moles hold1 --sweep forced_vote_after=0,1,2 --out "$OUT/sw-forced-0.7-hold1"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 1.0 --moles smart --sweep forced_vote_after=0,1,2 --out "$OUT/sw-forced-1.0-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 1.0 --moles hold1 --sweep forced_vote_after=0,1,2 --out "$OUT/sw-forced-1.0-hold1"
```

| cell | crew win (95% CI) | end reasons (% of games) | rounds | blown | crew ejected | nobody out (% of votes) | team rejected (% of team votes) | sabotage / chance | 0 blown | over by R2 | FA hit (of games held) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| skill 0.7, smart, forced_vote_after=0 | **76.3%** (71-81) | clean 66 out 10 score 24 | 4.36 | 1.94 | 0.68 | 70% | 72% | 93% | 4% | 2% | 72% of 199 |
| skill 0.7, smart, forced_vote_after=1 | **71.7%** (66-76) | clean 42 out 30 score 28 | 3.83 | 1.78 | 0.94 | 42% | 74% | 94% | 3% | 2% | 75% of 126 |
| skill 0.7, smart, forced_vote_after=2 | **70.7%** (65-76) | clean 53 out 17 score 29 | 4.14 | 1.90 | 0.81 | 58% | 72% | 93% | 4% | 2% | 76% of 160 |
| skill 0.7, hold1, forced_vote_after=0 | **79.3%** (74-84) | clean 76 out 3 score 21 | 4.12 | 1.46 | 0.93 | 65% | 82% | 63% | 17% | 0% | 67% of 229 |
| skill 0.7, hold1, forced_vote_after=1 | **74.7%** (69-79) | clean 63 out 12 score 25 | 3.79 | 1.31 | 1.24 | 41% | 82% | 61% | 17% | 0% | 69% of 188 |
| skill 0.7, hold1, forced_vote_after=2 | **76.7%** (72-81) | clean 72 out 5 score 23 | 4.02 | 1.41 | 1.05 | 57% | 82% | 62% | 17% | 0% | 68% of 216 |
| skill 1.0, smart, forced_vote_after=0 | **91.3%** (88-94) | clean 65 out 26 score 9 | 3.92 | 1.51 | 0.79 | 54% | 67% | 98% | 8% | 6% | 88% of 195 |
| skill 1.0, smart, forced_vote_after=1 | **91.3%** (88-94) | clean 47 out 44 score 9 | 3.60 | 1.43 | 0.88 | 32% | 67% | 98% | 8% | 6% | 86% of 142 |
| skill 1.0, smart, forced_vote_after=2 | **89.3%** (85-92) | clean 58 out 31 score 11 | 3.83 | 1.50 | 0.84 | 46% | 66% | 98% | 8% | 6% | 90% of 175 |
| skill 1.0, hold1, forced_vote_after=0 | **92.7%** (89-95) | clean 83 out 9 score 7 | 3.86 | 1.07 | 1.04 | 53% | 77% | 60% | 26% | 0% | 82% of 250 |
| skill 1.0, hold1, forced_vote_after=1 | **92.0%** (88-95) | clean 76 out 16 score 8 | 3.69 | 0.98 | 1.21 | 36% | 76% | 58% | 27% | 0% | 81% of 229 |
| skill 1.0, hold1, forced_vote_after=2 | **92.7%** (89-95) | clean 83 out 10 score 7 | 3.84 | 1.05 | 1.08 | 48% | 76% | 60% | 26% | 0% | 84% of 248 |

#### `--mole-approve team`

```
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 0.7 --moles smart --mole-approve team --out "$OUT/sw-mapp-0.7-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 0.7 --moles hold1 --mole-approve team --out "$OUT/sw-mapp-0.7-hold1"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 1.0 --moles smart --mole-approve team --out "$OUT/sw-mapp-1.0-smart"
python3.11 -m inside_job bots --games 300 --seed 1 --mole-cards decoy --config config/v04_bots.toml --crew-skill 1.0 --moles hold1 --mole-approve team --out "$OUT/sw-mapp-1.0-hold1"
```

| cell | crew win (95% CI) | end reasons (% of games) | rounds | blown | crew ejected | nobody out (% of votes) | team rejected (% of team votes) | sabotage / chance | 0 blown | over by R2 | FA hit (of games held) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| skill 0.7, smart | **57.0%** (51-62) | clean 39 out 18 score 43 | 4.03 | 2.18 | 0.84 | 55% | 69% | 94% | 2% | 2% | 78% of 116 |
| skill 0.7, hold1 | **69.3%** (64-74) | clean 61 out 8 score 31 | 4.10 | 1.64 | 1.04 | 56% | 73% | 64% | 11% | 0% | 73% of 184 |
| skill 1.0, smart | **88.7%** (85-92) | clean 57 out 32 score 11 | 3.84 | 1.55 | 0.85 | 46% | 66% | 98% | 7% | 6% | 91% of 171 |
| skill 1.0, hold1 | **91.0%** (87-94) | clean 79 out 12 score 9 | 3.85 | 1.12 | 1.09 | 48% | 75% | 61% | 23% | 0% | 85% of 238 |

## 5. What the numbers say

Facts only. "Skill" is crew skill; "smart", "hold1" etc. are the mole bots.

**Cells with crew wins between 35% and 65%.**
- Baseline (`pilot.toml`): skill 0.5 smart 42.0%, always 45.0%, hold1 55.7%; skill 0.7 smart
  59.7%, always 60.7%. None at skill 1.0.
- Full v0.4: skill 0.5 smart 55.0%, always 58.3%. None at skill 0.7 (smart 70.7%, hold1 76.7%)
  or 1.0 (smart 89.3%, hold1 92.7%).
- One dial on pilot.toml: `score+nobody` at skill 0.7 smart 40.7%, hold1 58.0%, skill 1.0 smart
  60.3%; `whispers` skill 0.7 smart 62.3%; `unique` skill 0.7 smart 62.0%; `endings` skill 0.7
  smart 59.7% (the baseline games).
- Full v0.4 minus one dial: minus `approval` at skill 0.7 smart 46.3% and skill 1.0 smart 61.7%.
- Sweeps: `mole_score_target = 3` in all four cells (skill 0.7 smart 43.3%, hold1 50.7%; skill
  1.0 smart 57.7%, hold1 64.3%); `--mole-approve team` at skill 0.7 smart 57.0%. No
  `eject_threshold`, `approve_threshold` or `forced_vote_after` value puts any of the four cells
  in the band (lowest: 68.7%).

**Never-sabotage moles.** They won 0 of 300 games in every cell they played (baseline and full
v0.4, skills 0.5 / 0.7 / 1.0): nowhere near 35%. Under full v0.4 they ended 100% on clean jobs,
and the Final Accusation found one of them in 27% / 40% / 54% of games (skill 0.5 / 0.7 / 1.0).

**Where crews stop ejecting (nobody-out share above 60%).** Full v0.4 at skill 0.5 (61-63% in
all four mole types); `bot.eject_threshold` 0.6 and above at skill 0.7 (smart 61-66%, hold1
66-70%) and 0.7 and above at skill 1.0 (smart 62-63%; hold1 61% at 0.6, 68-70% at 0.7-0.8);
`forced_vote_after = 0` at skill 0.7 (smart 70%, hold1 65%). At the defaults the share is 42-58%
at skills 0.7 and 1.0, and `forced_vote_after = 1` lowers it to 32-42%. As noted above, most of
it is split votes.

**Crew skill 0.7 -> 1.0, with and without `team_approval`** (crew win, percentage points):

| rule set | team_approval | smart | hold1 |
|---|---|---|---|
| pilot.toml (baseline) | off | 59.7 -> 82.3 (+22.6) | 71.7 -> 90.0 (+18.3) |
| pilot.toml + `score+nobody` | off | 40.7 -> 60.3 (+19.6) | 58.0 -> 75.7 (+17.7) |
| full v0.4 minus `approval` | off | 46.3 -> 61.7 (+15.4) | 65.3 -> 78.7 (+13.4) |
| pilot.toml + `approval` | on | 85.0 -> 99.0 (+14.0) | 89.0 -> 97.7 (+8.7) |
| full v0.4 | on | 70.7 -> 89.3 (+18.6) | 76.7 -> 92.7 (+16.0) |

With these bots, switching `team_approval` on did not make the skill gain larger: within full
v0.4 it is +18.6 / +16.0 with approval and +15.4 / +13.4 without; on top of pilot.toml it is
+14.0 / +8.7 with approval (near the 100% ceiling) against +22.6 / +18.3 without.

**Other things that stand out.**
- `team_approval` is the dial that moves crew wins most: on pilot.toml it raises them from
  59.7% to 85.0% (skill 0.7, smart) and from 82.3% to 99.0% (skill 1.0, smart); removing it from
  full v0.4 lowers them from 70.7% to 46.3% and from 89.3% to 61.7%. Read this with the first
  caveat: in these runs most teams are rejected and the next seat's team goes.
- `score+nobody` alone moves crew wins the other way (pilot.toml skill 0.7 smart 59.7% -> 40.7%;
  skill 1.0 smart 82.3% -> 60.3%). Crew members voted out per game fall from about 1.6-2.2 to
  0.9-1.05, but each now counts toward the moles' score.
- `mole_score_target` is steep: at skill 0.7 smart, 3 / 4 / 5 give 43.3% / 70.7% / 91.7% crew
  wins; at skill 1.0 smart 57.7% / 89.3% / 99.7%. At target 3, 23-24% of games with smart moles
  are over by round 2 (5% with hold1); at 4 and 5, 0-6%.
- Under full v0.4 the team vote is rejected 66-93% of the time at the default threshold; at
  `approve_threshold = 0.6` still 48-65%.
- Games over by round 2: baseline 2-9%; full v0.4 0-6%. Games with no blown job: baseline 1-21%
  (smart / always / hold1), full v0.4 4-26%; with `never` moles 100% by construction.
- `whispers` and `unique` each move crew wins by at most about 3 points on pilot.toml (inside the
  intervals). Removed from full v0.4 they move crew wins by -3.0 to +5.6 points: full v0.4 is
  70.7 / 76.7 / 89.3 / 92.7 (skill 0.7 smart, hold1; skill 1.0 smart, hold1), minus `whispers`
  72.3 / 82.3 / 91.7 / 89.7, minus `unique` 72.3 / 80.3 / 93.7 / 94.3.
- Final Accusation (full v0.4): held in 130-248 of 300 games against sabotaging moles, hit rate
  54-90%, rising with crew skill (smart: 65% / 76% / 90% at skill 0.5 / 0.7 / 1.0).
- Mean rounds with sabotaging moles: baseline 3.44-3.96, full v0.4 3.82-4.18.
