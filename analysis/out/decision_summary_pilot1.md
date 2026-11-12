# Decision table summary: batch `pilot1`

20 finished games (only games with a `game_end`). Rows: reading 1854, round 99, sabotage 36, vote 326.

**Intervals.** Every interval is a 95% percentile bootstrap that resamples whole games (2000 resamples, fixed seed 20261110); every statistic is a pooled mean over decisions in the resampled games. Each number is printed with n (decisions) and g (games) - in a table, the row's `n` and `games` columns apply to every cell that has no `(n=, g=)` of its own. Where fewer than 5 games contribute, the cell says `too few` instead of an interval.

**What the player could know.** All solver numbers use only events visible to that player (`log.visible_events`), up to a cutoff: for simultaneous phases (clue, job, vote, cut_vote, finale_choice) the seq just before the first turn of that phase in that round; for whisper steps (run in lockstep across pairs) the seq before the first turn of the step; for sequential phases (pick, discuss) seq-1.

These are show games (seven seats, five models, two seated twice). docs/CLAIMS.md says show games support none of its claims; the numbers below describe this batch only.

## a. Read (crew readings)

Brier = mean over rated players of (p - truth)^2. *model* = the stated suspicion, *solver* = the ideal reasoner from the reader's view at the cutoff, *base* = moles alive / players rated. `read_gap` = brier_model - brier_solver (the Read metric). *beats base* / *beats solver* = share of readings with a strictly lower Brier than that reference.

| all | n | games | brier_model | brier_solver | brier_base | read_gap | beats base | beats solver |
|---|---|---|---|---|---|---|---|---|
| all crew readings | 1322 | 20 | 0.171 [0.154, 0.186] | 0.154 [0.142, 0.165] | 0.212 [0.205, 0.219] | 0.018 [-0.005, 0.040] | 62% [56%, 68%] | 37% [26%, 49%] |

| round | n | games | brier_model | brier_solver | brier_base | read_gap | beats base | beats solver |
|---|---|---|---|---|---|---|---|---|
| 1 | 508 | 20 | 0.215 [0.196, 0.233] | 0.201 [0.193, 0.209] | 0.222 [0.222, 0.222] | 0.013 [-0.003, 0.029] | 44% [35%, 52%] | 33% [24%, 43%] |
| 2 | 492 | 20 | 0.159 [0.126, 0.193] | 0.155 [0.143, 0.169] | 0.205 [0.188, 0.222] | 0.004 [-0.027, 0.037] | 70% [58%, 81%] | 50% [34%, 64%] |
| 3 | 240 | 14 | 0.153 [0.121, 0.189] | 0.099 [0.074, 0.121] | 0.201 [0.188, 0.216] | 0.054 [0.018, 0.100] | 69% [55%, 80%] | 31% [15%, 47%] |
| 4 | 70 | 6 | 0.037 [0.023, 0.058] | 0.010 [0.000, 0.040] | 0.222 [0.222, 0.222] | 0.027 [-0.005, 0.055] | 99% [94%, 100%] | 6% [0%, 24%] |
| 5 | 12 | 2 | 0.003 (too few) | 0.000 (too few) | 0.250 (too few) | 0.003 (too few) | 100% (too few) | 0% (too few) |

| phase | n | games | brier_model | brier_solver | brier_base | read_gap | beats base | beats solver |
|---|---|---|---|---|---|---|---|---|
| clue | 261 | 20 | 0.184 [0.173, 0.194] | 0.166 [0.154, 0.179] | 0.211 [0.204, 0.218] | 0.018 [0.001, 0.035] | 47% [42%, 52%] | 25% [18%, 33%] |
| whisper | 356 | 20 | 0.170 [0.157, 0.181] | 0.157 [0.144, 0.171] | 0.212 [0.203, 0.220] | 0.013 [-0.007, 0.032] | 63% [56%, 72%] | 41% [29%, 54%] |
| discuss | 470 | 20 | 0.168 [0.145, 0.189] | 0.149 [0.137, 0.161] | 0.212 [0.205, 0.219] | 0.019 [-0.007, 0.045] | 66% [58%, 75%] | 40% [28%, 53%] |
| vote | 235 | 20 | 0.166 [0.136, 0.194] | 0.143 [0.131, 0.155] | 0.212 [0.205, 0.219] | 0.023 [-0.011, 0.057] | 66% [56%, 75%] | 38% [25%, 53%] |

| stage | n | games | brier_model | brier_solver | brier_base | read_gap | beats base | beats solver |
|---|---|---|---|---|---|---|---|---|
| clue | 261 | 20 | 0.184 [0.173, 0.194] | 0.166 [0.154, 0.179] | 0.211 [0.204, 0.218] | 0.018 [0.001, 0.035] | 47% [42%, 52%] | 25% [18%, 33%] |
| whisper1 | 178 | 20 | 0.169 [0.158, 0.179] | 0.158 [0.144, 0.172] | 0.212 [0.203, 0.220] | 0.011 [-0.008, 0.030] | 62% [53%, 70%] | 39% [26%, 52%] |
| whisper2 | 178 | 20 | 0.170 [0.156, 0.183] | 0.156 [0.143, 0.170] | 0.212 [0.203, 0.220] | 0.014 [-0.007, 0.034] | 65% [57%, 74%] | 43% [30%, 58%] |
| discuss1 | 235 | 20 | 0.171 [0.151, 0.188] | 0.155 [0.143, 0.167] | 0.212 [0.205, 0.219] | 0.016 [-0.006, 0.037] | 67% [59%, 75%] | 40% [29%, 52%] |
| discuss2 | 235 | 20 | 0.165 [0.138, 0.191] | 0.143 [0.131, 0.155] | 0.212 [0.205, 0.219] | 0.022 [-0.010, 0.054] | 65% [55%, 75%] | 40% [26%, 55%] |
| vote | 235 | 20 | 0.166 [0.136, 0.194] | 0.143 [0.131, 0.155] | 0.212 [0.205, 0.219] | 0.023 [-0.011, 0.057] | 66% [56%, 75%] | 38% [25%, 53%] |

| model | n | games | brier_model | brier_solver | brier_base | read_gap | beats base | beats solver |
|---|---|---|---|---|---|---|---|---|
| claude-haiku-4-5 | 441 | 20 | 0.168 [0.145, 0.189] | 0.149 [0.128, 0.167] | 0.213 [0.205, 0.221] | 0.019 [-0.013, 0.053] | 60% [51%, 67%] | 36% [23%, 49%] |
| claude-haiku-5-5 | 172 | 12 | 0.160 [0.142, 0.176] | 0.162 [0.143, 0.180] | 0.215 [0.205, 0.222] | -0.002 [-0.027, 0.022] | 67% [56%, 77%] | 42% [24%, 61%] |
| claude-sonnet-4-5 | 129 | 14 | 0.169 [0.133, 0.204] | 0.172 [0.159, 0.188] | 0.199 [0.193, 0.209] | -0.003 [-0.040, 0.032] | 64% [50%, 76%] | 51% [35%, 68%] |
| claude-sonnet-4-6 | 389 | 19 | 0.179 [0.159, 0.197] | 0.152 [0.139, 0.167] | 0.213 [0.204, 0.220] | 0.026 [0.002, 0.047] | 58% [51%, 66%] | 34% [21%, 49%] |
| claude-sonnet-5 | 191 | 14 | 0.176 [0.156, 0.195] | 0.147 [0.135, 0.162] | 0.214 [0.204, 0.223] | 0.029 [0.003, 0.051] | 66% [56%, 79%] | 32% [20%, 46%] |

Log scores (mean negative log likelihood, p clipped to [0.01, 0.99]):

| set | n | games | log_model | log_solver | log_base |
|---|---|---|---|---|---|
| all crew readings | 1322 | 20 | 0.509 [0.465, 0.546] | 0.451 [0.420, 0.482] | 0.614 [0.598, 0.628] |

Crew readings where model and solver Brier tie exactly: 3 of 1322. Solver inconsistent (fell back to reveals and jobs): 0. Readings whose rated set is not exactly the other living players: 0.

### a.1 Reconciliation with docs/pilot1_report.md (section 5)

Same selection as the report: each crew player's last non-fallback reading per round.

- Readings selected: 261 (report: 261); the same turns as `report.game_readings`: 261 of 261.
- Crew Brier: 0.1615 (report: 0.162); solver ('ideal') Brier at my cutoff: 0.1351; `game_readings` ideal (upto_seq = the turn's own seq): 0.1351 (report: 0.135).
- Selected readings whose solver Brier differs between the two cutoffs: 0; whose model Brier differs: 0.
- Phases of the selected readings: clue 5, vote 235, whisper 21.
- Over all 1854 readings (crew and mole), the solver posterior from the reader's view differs between upto_seq = own seq and my cutoff in 5 (discuss 5). `visible_to` makes every other player's vote turn (public part: reason and target) visible as soon as it is in the slice, so a cutoff at a vote turn's own seq 'sees' the earlier voters' votes, which the real prompt never did; the solver ignores vote turns (only cards, job results and reveals enter it), so this cannot move a solver number. `visible_to` also admits a partner mole's `job` turn (via `shared_with`) as soon as it is logged, so for the second mole on a team a seq-1 or own-seq cutoff would show the partner's choice, which the real prompt never did (see section h). A discuss turn's own seq adds the speaker's own tabled cards to their view; that is what the count above picks up.

## b. Calibration of crew readings

Unit: one stated probability (a reading of one player). Bins of stated suspicion; the last bin includes 100.

| stated | n | games | mean stated | observed mole share | mean solver posterior |
|---|---|---|---|---|---|
| 0-9 | 712 | 20 | 0.037 | 0.029 [0.001, 0.077] | 0.083 [0.057, 0.105] |
| 10-19 | 922 | 20 | 0.133 | 0.098 [0.060, 0.139] | 0.214 [0.196, 0.231] |
| 20-29 | 1353 | 20 | 0.229 | 0.222 [0.180, 0.266] | 0.279 [0.264, 0.294] |
| 30-39 | 1342 | 20 | 0.327 | 0.334 [0.306, 0.361] | 0.342 [0.330, 0.355] |
| 40-49 | 759 | 20 | 0.426 | 0.457 [0.412, 0.498] | 0.385 [0.367, 0.399] |
| 50-59 | 523 | 20 | 0.530 | 0.505 [0.443, 0.566] | 0.407 [0.386, 0.430] |
| 60-69 | 377 | 20 | 0.629 | 0.562 [0.490, 0.639] | 0.454 [0.420, 0.484] |
| 70-79 | 348 | 20 | 0.723 | 0.589 [0.513, 0.683] | 0.485 [0.450, 0.518] |
| 80-89 | 170 | 20 | 0.833 | 0.641 [0.519, 0.775] | 0.486 [0.431, 0.542] |
| 90-100 | 196 | 19 | 0.947 | 0.913 [0.849, 0.955] | 0.784 [0.651, 0.874] |

Hedging: mean stated suspicion grouped by the solver's posterior for the same player at the same moment (reader's view).

| solver band | n | games | mean stated | mean solver | observed mole share |
|---|---|---|---|---|---|
| solver >= 0.99 | 257 | 15 | 0.755 [0.682, 0.824] | 1.000 | 1.000 [1.000, 1.000] |
| solver <= 0.01 | 1008 | 20 | 0.141 [0.110, 0.175] | 0.000 | 0.000 [0.000, 0.000] |
| 0.01 < solver <= 1/3 | 3316 | 20 | 0.302 [0.288, 0.314] | 0.274 | 0.239 [0.212, 0.266] |
| 1/3 < solver <= 2/3 | 2031 | 20 | 0.457 [0.447, 0.468] | 0.463 | 0.516 [0.479, 0.552] |
| 2/3 < solver < 0.99 | 90 | 13 | 0.565 [0.489, 0.637] | 0.755 | 0.867 [0.682, 1.000] |

## c. Votes

Every non-fallback vote. *hit* = voted for a mole. *solver argmax hit* (crew only) = expected hit rate voting uniformly among the solver's most likely players. *base* = share of the voter's valid targets that are moles (random-vote hit rate; for a mole voter this counts their partner). *regret* = solver p(best) - solver p(target) (crew). *own top* = vote went to a player the voter rated highest in the same turn (ties count). *own accusation* = vote equals the voter's last accusation this round (only voters who accused). *most accused* = vote on a player with the most discussion accusations this round (ties count; only rounds with an accusation).

| round | role | n | games | hit | solver argmax hit | base | regret | own top | own accusation | most accused |
|---|---|---|---|---|---|---|---|---|---|---|
| all | all | 326 | 20 | 50% [43%, 58%] | 68% [60%, 74%] (n=235, g=20) | 28% [26%, 30%] | 0.078 [0.044, 0.120] (n=235, g=20) | 91% [87%, 94%] | 92% [89%, 95%] (n=308, g=20) | 69% [64%, 74%] |
| all | crew | 235 | 20 | 64% [55%, 73%] | 68% [60%, 74%] | 33% [30%, 35%] | 0.078 [0.044, 0.120] | 96% [93%, 98%] | 96% [94%, 98%] (n=225, g=20) | 73% [66%, 79%] |
| all | mole | 91 | 20 | 15% [10%, 22%] | - (n=0, g=0) | 16% [13%, 18%] | - (n=0, g=0) | 78% [68%, 87%] | 82% [73%, 89%] (n=83, g=20) | 59% [48%, 69%] |
| 1 | crew | 100 | 20 | 50% [32%, 68%] | 64% [49%, 77%] | 33% [33%, 33%] | 0.065 [0.033, 0.104] | 97% [94%, 100%] | 96% [91%, 99%] (n=90, g=20) | 63% [51%, 75%] |
| 1 | mole | 40 | 20 | 8% [0%, 15%] | - (n=0, g=0) | 17% [17%, 17%] | - (n=0, g=0) | 78% [60%, 92%] | 88% [77%, 97%] (n=34, g=20) | 70% [50%, 88%] |
| 2 | crew | 88 | 20 | 78% [62%, 92%] | 67% [56%, 80%] | 31% [27%, 35%] | 0.067 [0.027, 0.113] | 95% [91%, 99%] | 97% [93%, 100%] | 81% [69%, 91%] |
| 2 | mole | 32 | 20 | 31% [16%, 47%] | - (n=0, g=0) | 15% [11%, 18%] | - (n=0, g=0) | 78% [67%, 90%] | 77% [61%, 90%] (n=30, g=19) | 50% [34%, 65%] |
| 3 | crew | 37 | 10 | 57% [32%, 81%] | 71% [59%, 84%] | 31% [25%, 39%] | 0.162 [0.032, 0.323] | 95% [86%, 100%] | 97% [91%, 100%] | 78% [66%, 89%] |
| 3 | mole | 13 | 10 | 0% [0%, 0%] | - (n=0, g=0) | 12% [0%, 19%] | - (n=0, g=0) | 92% [77%, 100%] | 85% [69%, 100%] | 62% [30%, 87%] |
| 4 | crew | 10 | 4 | 100% (too few) | 100% (too few) | 47% (too few) | 0.000 (too few) | 90% (too few) | 90% (too few) | 80% (too few) |
| 4 | mole | 6 | 4 | 17% (too few) | - (n=0, g=0) | 22% (too few) | - (n=0, g=0) | 50% (too few) | 67% (too few) | 33% (too few) |

Check: 326 vote rows (expected 326 for pilot1); eliminations 54, of which a mole 32 (expected 32 of 54).
Crew votes with zero regret (on a solver-best player): 183 of 235; crew votes where the solver's best set is a single player: 85; own top suspicion tied: 3 of 326.

## d. Sabotage (job turns)

Only moles on the team are asked; crew help automatically. **The solver gives no ideal answer for this decision**: the columns below (the scripted `smart` rule, how much a blown job would move the public posterior on this mole, what happened next) are the closest available references, not a correct answer. *script* = sabotage unless the partner is also on the team and sits in a lower seat, then help. *exposure* = public posterior on this mole if this job came back blown with one sabotage, minus the public posterior before.

Job turns: 36 (fallback 0).

| decisions | n | games | sabotage rate | agrees with script | mean exposure |
|---|---|---|---|---|---|
| all | 36 | 15 | 56% [37%, 73%] | 61% [44%, 77%] | 0.105 [0.077, 0.139] |
| round 1 | 8 | 6 | 0% [0%, 0%] | 25% [0%, 43%] | 0.114 [0.114, 0.114] |
| round 2 | 19 | 14 | 63% [42%, 83%] | 58% [35%, 83%] | 0.111 [0.083, 0.134] |
| round 3 | 5 | 5 | 100% [100%, 100%] | 100% [100%, 100%] | 0.053 [0.000, 0.133] |
| round 4 | 4 | 3 | 75% (too few) | 100% (too few) | 0.125 (too few) |
| wins_now = true | 1 | 1 | 100% (too few) | 100% (too few) | 0.500 (too few) |
| wins_now = false | 35 | 15 | 54% [35%, 72%] | 60% [43%, 76%] | 0.094 [0.075, 0.114] |
| partner on team | 16 | 6 | 38% [12%, 67%] | 50% [21%, 83%] | 0.088 [0.048, 0.123] |
| partner not on team | 20 | 11 | 70% [50%, 89%] | 70% [50%, 89%] | 0.119 [0.074, 0.162] |
| clean job would win for crew | 3 | 2 | 67% (too few) | 100% (too few) | 0.000 (too few) |

Exposure by choice:

| choice | n | games | mean exposure | public p(self) before | self voted out this round |
|---|---|---|---|---|---|
| sabotage | 20 | 11 | 0.111 [0.073, 0.163] | 0.479 [0.381, 0.594] | 55% [32%, 81%] |
| help | 16 | 10 | 0.099 [0.063, 0.129] | 0.337 [0.262, 0.438] | 25% [7%, 42%] |

Every job decision:

| seed | round | mole | model | team | partner on | choice | script | wins now | p(self) | exposure | job | crew share on moles | self out |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | Viper | claude-haiku-5-5 | 3 | False | help | sabotage | False | 0.29 | +0.11 | clean (0) | 0.00 | False |
| 1 | 2 | Viper | claude-haiku-5-5 | 3 | False | sabotage | sabotage | False | 0.45 | +0.10 | blown (1) | 1.00 | True |
| 1 | 3 | Slate | claude-sonnet-5 | 3 | False | sabotage | sabotage | False | 0.20 | +0.13 | blown (1) | 0.25 | False |
| 1 | 4 | Slate | claude-sonnet-5 | 2 | False | sabotage | sabotage | True | 0.50 | +0.50 | blown (1) | - | False |
| 2 | 2 | Wren | claude-sonnet-4-6 | 3 | True | sabotage | sabotage | False | 0.38 | +0.12 | blown (2) | 1.00 | False |
| 2 | 2 | Rook | claude-haiku-4-5 | 3 | True | sabotage | help | False | 0.38 | +0.12 | blown (2) | 1.00 | True |
| 2 | 3 | Wren | claude-sonnet-4-6 | 3 | False | sabotage | sabotage | False | 0.50 | +0.00 | blown (1) | 0.25 | False |
| 3 | 2 | Juno | claude-sonnet-4-5 | 3 | False | sabotage | sabotage | False | 0.42 | +0.14 | blown (1) | 0.75 | True |
| 4 | 2 | Quill | claude-sonnet-4-5 | 3 | False | sabotage | sabotage | False | 0.42 | +0.08 | blown (1) | 1.00 | True |
| 4 | 3 | Slate | claude-sonnet-4-6 | 3 | False | sabotage | sabotage | False | 0.20 | +0.13 | blown (1) | 0.75 | True |
| 5 | 2 | Moth | claude-sonnet-4-5 | 3 | True | help | help | False | 0.30 | +0.08 | blown (1) | 0.75 | False |
| 5 | 2 | Vesper | claude-sonnet-4-6 | 3 | True | sabotage | sabotage | False | 0.50 | +0.12 | blown (1) | 0.75 | False |
| 5 | 4 | Vesper | claude-sonnet-4-6 | 2 | True | sabotage | sabotage | False | 1.00 | +0.00 | blown (1) | 1.00 | True |
| 5 | 4 | Moth | claude-sonnet-4-5 | 2 | True | help | help | False | 1.00 | +0.00 | blown (1) | 1.00 | False |
| 6 | 2 | Juno | claude-haiku-5-5 | 3 | True | help | sabotage | False | 0.50 | +0.00 | clean (0) | 1.00 | False |
| 6 | 2 | Slate | claude-haiku-4-5 | 3 | True | help | help | False | 0.30 | +0.00 | clean (0) | 1.00 | True |
| 9 | 1 | Onyx | claude-haiku-4-5 | 3 | False | help | sabotage | False | 0.29 | +0.11 | clean (0) | 1.00 | False |
| 9 | 2 | Onyx | claude-haiku-4-5 | 3 | False | help | sabotage | False | 0.17 | +0.17 | clean (0) | 0.00 | False |
| 11 | 2 | Cipher | claude-sonnet-4-6 | 3 | True | sabotage | help | False | 0.38 | +0.12 | blown (1) | 0.75 | True |
| 11 | 2 | Duke | claude-sonnet-4-6 | 3 | True | help | sabotage | False | 0.38 | +0.12 | blown (1) | 0.75 | False |
| 11 | 3 | Duke | claude-sonnet-4-6 | 3 | False | sabotage | sabotage | False | 0.50 | +0.00 | blown (1) | 1.00 | True |
| 12 | 1 | Onyx | claude-sonnet-4-5 | 3 | False | help | sabotage | False | 0.29 | +0.11 | clean (0) | 0.20 | False |
| 12 | 2 | Onyx | claude-sonnet-4-5 | 3 | False | sabotage | sabotage | False | 0.71 | +0.12 | blown (1) | 0.50 | False |
| 14 | 1 | Lark | claude-sonnet-5 | 3 | True | help | sabotage | False | 0.29 | +0.11 | clean (0) | 1.00 | True |
| 14 | 1 | Vesper | claude-sonnet-4-6 | 3 | True | help | help | False | 0.29 | +0.11 | clean (0) | 1.00 | False |
| 16 | 2 | Slate | claude-haiku-5-5 | 3 | False | help | sabotage | False | 0.17 | +0.17 | clean (0) | 1.00 | True |
| 17 | 2 | Onyx | claude-sonnet-4-5 | 3 | False | sabotage | sabotage | False | 0.42 | +0.14 | blown (1) | 0.25 | False |
| 17 | 3 | Onyx | claude-sonnet-4-5 | 3 | False | sabotage | sabotage | False | 0.67 | +0.00 | blown (1) | 0.33 | False |
| 18 | 2 | Cipher | claude-sonnet-4-6 | 3 | False | sabotage | sabotage | False | 0.17 | +0.17 | blown (1) | 1.00 | True |
| 19 | 1 | Duke | claude-sonnet-5 | 3 | True | help | sabotage | False | 0.29 | +0.11 | clean (0) | 0.20 | False |
| 19 | 1 | Bishop | claude-haiku-4-5 | 3 | True | help | help | False | 0.29 | +0.11 | clean (0) | 0.20 | False |
| 19 | 2 | Duke | claude-sonnet-5 | 3 | True | help | sabotage | False | 0.30 | +0.13 | blown (1) | 1.00 | True |
| 19 | 2 | Bishop | claude-haiku-4-5 | 3 | True | sabotage | help | False | 0.30 | +0.13 | blown (1) | 1.00 | False |
| 20 | 1 | Sparrow | claude-haiku-4-5 | 3 | False | help | sabotage | False | 0.29 | +0.11 | clean (0) | 0.20 | False |
| 20 | 2 | Sparrow | claude-haiku-4-5 | 3 | False | sabotage | sabotage | False | 0.50 | +0.07 | blown (1) | 1.00 | True |
| 20 | 4 | Quill | claude-haiku-5-5 | 2 | False | sabotage | sabotage | False | 1.00 | +0.00 | blown (1) | 1.00 | True |

## e. Getaway (Bluff unit: one mole, one round)

*getaway* = (1 if the job was blown, else 0) x (1 - share of the crew's non-fallback votes on any mole that round); a blown job that ends the game with no vote scores 1; a clean job scores 0. Rows: 99; scored 99.

| mole rounds | n | games | getaway = 0 | getaway = 1 | mean getaway | job blown |
|---|---|---|---|---|---|---|
| all | 99 | 20 | 84% [76%, 93%] | 1% [0%, 3%] | 0.082 [0.028, 0.138] | 31% [20%, 41%] |
| round 1 | 40 | 20 | 100% [100%, 100%] | 0% [0%, 0%] | 0.000 [0.000, 0.000] | 0% [0%, 0%] |
| round 2 | 32 | 20 | 69% [47%, 93%] | 0% [0%, 0%] | 0.125 [0.031, 0.229] | 66% [44%, 85%] |
| round 3 | 17 | 14 | 71% [44%, 94%] | 0% [0%, 0%] | 0.181 [0.016, 0.368] | 35% [10%, 62%] |
| round 4 | 8 | 6 | 88% [50%, 100%] | 12% [0%, 50%] | 0.125 [0.000, 0.500] | 50% [0%, 100%] |
| round 5 | 2 | 2 | 100% (too few) | 0% (too few) | 0.000 (too few) | 0% (too few) |
| `claude-haiku-4-5` | 19 | 9 | 100% [100%, 100%] | 0% [0%, 0%] | 0.000 [0.000, 0.000] | 16% [0%, 31%] |
| `claude-haiku-5-5` | 20 | 8 | 95% [85%, 100%] | 0% [0%, 0%] | 0.025 [0.000, 0.077] | 20% [0%, 38%] |
| `claude-sonnet-4-5` | 21 | 6 | 76% [63%, 92%] | 0% [0%, 0%] | 0.115 [0.025, 0.217] | 33% [19%, 45%] |
| `claude-sonnet-4-6` | 26 | 10 | 77% [69%, 89%] | 0% [0%, 0%] | 0.077 [0.031, 0.115] | 42% [25%, 53%] |
| `claude-sonnet-5` | 13 | 6 | 69% [54%, 100%] | 8% [0%, 20%] | 0.244 [0.000, 0.373] | 46% [0%, 64%] |
| self on team | 36 | 15 | 67% [50%, 83%] | 3% [0%, 9%] | 0.164 [0.064, 0.273] | 67% [46%, 84%] |
| self not on team | 63 | 20 | 94% [87%, 100%] | 0% [0%, 0%] | 0.034 [0.000, 0.073] | 11% [4%, 18%] |
| no mole on team | 52 | 19 | 100% [100%, 100%] | 0% [0%, 0%] | 0.000 [0.000, 0.000] | 0% [0%, 0%] |

Getaway values that are neither 0 nor 1: 0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 0.50, 0.50, 0.67, 0.67, 0.75, 0.75, 0.75, 0.75.

## f. Table read (mole readings)

*target* for each rated player X = mean over crew still in (excluding X) of that crew member's latest non-fallback belief of X before this turn's cutoff. tr_err = mean over rated players with a target of (value - target)^2, for the mole's stated read (*model*), the solver's public posterior (*public*) and the constant base rate (*base* = moles alive / players rated, what a crew member with no information would say and the engine's fallback value). gap = tr_err_model - tr_err_public. A mole does not rate themselves, so how much the crew suspect the reader is never part of this score. Mole readings: 532; with a target: 492 (no crew reading exists before the first clue turn of the game, so round 1 clue readings have none).

| mole readings | n | games | tr_err_model | tr_err_public | tr_err_base | gap | beats base |
|---|---|---|---|---|---|---|---|
| all | 492 | 20 | 0.038 [0.032, 0.044] | 0.032 [0.019, 0.048] | 0.026 [0.018, 0.035] | 0.006 [-0.006, 0.016] | 29% [23%, 34%] |
| round 1 | 196 | 20 | 0.025 [0.022, 0.029] | 0.011 [0.009, 0.014] | 0.011 [0.009, 0.014] | 0.014 [0.010, 0.018] | 17% [12%, 22%] |
| round 2 | 180 | 20 | 0.036 [0.029, 0.043] | 0.030 [0.024, 0.037] | 0.023 [0.018, 0.027] | 0.005 [-0.005, 0.015] | 37% [27%, 47%] |
| round 3 | 80 | 14 | 0.043 [0.035, 0.049] | 0.059 [0.029, 0.089] | 0.030 [0.022, 0.038] | -0.016 [-0.047, 0.010] | 31% [22%, 43%] |
| round 4 | 34 | 6 | 0.114 [0.049, 0.145] | 0.102 [0.011, 0.183] | 0.116 [0.055, 0.172] | 0.012 [-0.047, 0.082] | 50% [21%, 91%] |
| round 5 | 2 | 2 | 0.026 (too few) | 0.022 (too few) | 0.148 (too few) | 0.003 (too few) | 100% (too few) |
| clue | 59 | 20 | 0.038 [0.026, 0.050] | 0.050 [0.024, 0.077] | 0.039 [0.022, 0.056] | -0.012 [-0.031, 0.008] | 46% [33%, 60%] |
| whisper | 160 | 20 | 0.035 [0.029, 0.042] | 0.025 [0.011, 0.045] | 0.012 [0.008, 0.016] | 0.010 [-0.004, 0.020] | 9% [3%, 15%] |
| discuss | 182 | 20 | 0.041 [0.033, 0.048] | 0.031 [0.021, 0.041] | 0.028 [0.019, 0.036] | 0.010 [0.002, 0.018] | 31% [24%, 38%] |
| vote | 91 | 20 | 0.038 [0.031, 0.047] | 0.037 [0.026, 0.051] | 0.041 [0.031, 0.051] | 0.001 [-0.015, 0.016] | 49% [39%, 58%] |
| `claude-haiku-4-5` | 100 | 9 | 0.040 [0.030, 0.051] | 0.018 [0.013, 0.023] | 0.017 [0.012, 0.021] | 0.021 [0.013, 0.031] | 21% [11%, 32%] |
| `claude-haiku-5-5` | 102 | 8 | 0.041 [0.032, 0.050] | 0.023 [0.015, 0.033] | 0.024 [0.015, 0.032] | 0.018 [0.003, 0.031] | 25% [13%, 36%] |
| `claude-sonnet-4-5` | 94 | 6 | 0.037 [0.023, 0.046] | 0.059 [0.019, 0.101] | 0.036 [0.017, 0.058] | -0.023 [-0.057, 0.005] | 38% [26%, 49%] |
| `claude-sonnet-4-6` | 131 | 10 | 0.036 [0.024, 0.051] | 0.033 [0.015, 0.053] | 0.026 [0.015, 0.036] | 0.003 [-0.004, 0.011] | 34% [26%, 39%] |
| `claude-sonnet-5` | 65 | 6 | 0.038 [0.025, 0.051] | 0.027 [0.010, 0.039] | 0.031 [0.008, 0.048] | 0.010 [0.005, 0.017] | 25% [0%, 37%] |

## g. Feature audit

Counts only; what the logs show.

**Whisper requests.**

| requester | requests | 'none' | mutual | mole asked partner |
|---|---|---|---|---|
| crew | 261 | 7% [4%, 9%] | 23% [16%, 31%] | 0 |
| mole | 99 | 6% [2%, 11%] | 38% [29%, 48%] | 41 |

Pairs formed per round: round 1: mean 2.30 over 20 games ({1: 1, 2: 12, 3: 7}); round 2: mean 2.40 over 20 games ({2: 12, 3: 8}); round 3: mean 1.79 over 14 games ({1: 3, 2: 11}); round 4: mean 1.33 over 6 games ({1: 4, 2: 2}); round 5: mean 1.00 over 2 games ({1: 2}).
Whisper turns (non-fallback): 516; with a clue card: 181; cards shown: 188.

**Belief movement (crew).** Consecutive non-fallback readings of the same crew player in the same round, in the order clue, whisper 1, whisper 2, discuss pass 1, discuss pass 2, vote (a missing stage is skipped). *|change|* = mean absolute change in stated probability over the rated players; *dBrier* = later Brier minus earlier (negative = moved towards the truth); *dBrier solver* = the same for the solver over the same step (the information that arrived). Note the job result arrives between the whisper/clue readings and discuss pass 1.

| step | n | games | |change| | any change | dBrier model | dBrier solver |
|---|---|---|---|---|---|---|
| clue -> whisper1 | 178 | 20 | 0.055 [0.049, 0.062] | 89% [82%, 94%] | -0.007 [-0.013, -0.001] | -0.001 [-0.003, -0.000] |
| clue -> discuss1 | 78 | 20 | 0.105 [0.092, 0.123] | 100% [100%, 100%] | -0.014 [-0.029, 0.003] | -0.018 [-0.026, -0.011] |
| whisper1 -> whisper2 | 178 | 20 | 0.070 [0.063, 0.077] | 96% [93%, 99%] | 0.001 [-0.006, 0.007] | -0.002 [-0.004, -0.000] |
| whisper2 -> discuss1 | 157 | 20 | 0.112 [0.101, 0.123] | 98% [96%, 100%] | -0.016 [-0.032, 0.001] | -0.021 [-0.029, -0.014] |
| discuss1 -> discuss2 | 235 | 20 | 0.101 [0.092, 0.109] | 98% [96%, 100%] | -0.006 [-0.021, 0.009] | -0.012 [-0.018, -0.007] |
| discuss2 -> vote | 235 | 20 | 0.063 [0.057, 0.069] | 97% [94%, 99%] | 0.001 [-0.004, 0.006] | 0.000 [0.000, 0.000] |

**Second discussion pass.**

| players (player-rounds with both passes) | n | accusation changes pass 1 -> 2 | 'none' in both passes |
|---|---|---|---|
| all | 326 | 43% [38%, 47%] | 6% [3%, 9%] |
| crew | 235 | 39% [32%, 46%] | 4% [2%, 8%] |
| mole | 91 | 52% [41%, 63%] | 9% [3%, 16%] |

Votes by players who spoke in both passes: 326. Match the pass-2 accusation but not pass 1: 39% [33%, 45%]; match pass 1 but not pass 2: 3% [1%, 5%]; match both: 48% [41%, 54%].

**`challenges` and `accuse` (discussion turns, non-fallback).** *base* = share of the possible targets that were moles (for challenges: statements by others earlier this round; for accuse: the other living players).

| speaker | discuss turns | uses challenges | challenge ids | aimed at a mole's statement | base | accuses someone | accusation on a mole | base |
|---|---|---|---|---|---|---|---|---|
| crew | 470 | 44% [37%, 52%] | 243 | 55% [46%, 65%] | 35% [30%, 39%] | 83% [78%, 87%] | 64% [57%, 72%] | 33% [30%, 35%] |
| mole | 182 | 37% [25%, 48%] | 80 | 16% [7%, 29%] | 16% [11%, 20%] | 77% [69%, 84%] | 9% [4%, 16%] | 16% [13%, 18%] |

**Clue cards** (engine checks: real = the speaker holds that clue; true = true in the actual world).

| where | role | cards | real, true | real, false | fake, true | fake, false |
|---|---|---|---|---|---|---|
| tabled | crew | 174 | 173 | 0 | 1 | 0 |
| tabled | mole | 52 | 47 | 0 | 0 | 5 |
| whispered | crew | 148 | 148 | 0 | 0 | 0 |
| whispered | mole | 40 | 37 | 0 | 0 | 3 |

Clues dealt (real, non-'none'): crew 129, mole 48; 'no intel': crew 132, mole 51.

**`job_claim`** (discussion turns; actual = the engine's job choice; crew always help).

| role | on team | claimed | actual | turns |
|---|---|---|---|---|
| crew | no | none | - | 224 |
| crew | yes | helped | help | 207 |
| crew | yes | none | help | 39 |
| mole | no | none | - | 112 |
| mole | yes | helped | help | 29 |
| mole | yes | helped | sabotage | 28 |
| mole | yes | none | help | 3 |
| mole | yes | none | sabotage | 10 |

**The Cut.** Record = votes the player cast for a mole (as `engine.vote_record` counts it: the target's true role, whether or not revealed).

Cuts held: 17 (survivors: {3: 3, 4: 8, 5: 6}). Cut votes: 71. On a candidate with the best record among the voter's options: 80% [64%, 93%]; expected if random: 81% [69%, 90%]. Where exactly one option had the best record: 25% [0%, 57%] vs random 39% [33%, 46%].
Finalists are the two best records: 13 of 17. Tiebreaks: {'None': 11, 'record': 1, 'random': 5}. Cuts where counting only *revealed* moles would change some record: 4.

**Finale choices.** stated -> chosen: split -> split: 36, split -> steal: 2. Outcomes: split/split 17, split/steal 2.

**Truncation** (non-fallback turns trimmed at the hard word cap).

| model | turns | truncated | confessional | public | memory | claims |
|---|---|---|---|---|---|---|
| `claude-haiku-4-5` | 643 | 82 | 45 | 25 | 15 | 0 |
| `claude-haiku-5-5` | 326 | 5 | 1 | 2 | 2 | 0 |
| `claude-sonnet-4-5` | 268 | 10 | 4 | 5 | 2 | 0 |
| `claude-sonnet-4-6` | 625 | 0 | 0 | 0 | 0 | 0 |
| `claude-sonnet-5` | 308 | 1 | 0 | 0 | 1 | 0 |

**Fallbacks** (turns that fell back to the documented default): none.

## h. Raw material: what a turn's log record keeps

From `engine.ask` / `engine.write_turn`, `llm.py` and `log.py` (read, not run):

Kept on every `turn` event: player, model (requested id), turn_phase, round, seq, ts, confessional, public, claims, memory, action (the parsed `move`), suspicion_kind, checks (discuss/whisper), statement_id, truncated, truncated_fields, fallback, fallback_reason, attempts, served_model, usage (summed over all attempts), latency_s (summed), rejections (one reason string per failed attempt), error_kinds (one per failed attempt), blocked (count), partner / pass / shared_with.

Not kept anywhere in the log:

- the system prompt (built once per player in `setup`, held in `Game.system_prompts`, never logged);
- the turn prompt text (`prepare` builds it and passes it to the client; never logged);
- the JSON schema sent with `--json-schema` (`turn_schema(phase, ctx)`; never logged);
- `ctx` (others, order, challengeable ids, team, partner, index, pass ...), which the prompt and schema are built from;
- the raw CLI stdout (`parse_cli_output` keeps `raw_text` on the `LLMReply`; the engine drops it);
- the reply text of a failed attempt (rejected, invalid, blocked or timed out): only the reason string survives, and `llm.parse_cli_output` cuts CLI error text to 300 characters;
- the text before word-cap trimming (`clean_reply` trims; only `truncated_fields` records that it happened, not what was cut);
- thinking text (the CLI's JSON carries usage counts only; `usage.thinking` is a token count);
- the retry prompt suffix (`\n\nYour previous reply was rejected: <reason>. Reply again with valid JSON.`): not logged, but reconstructible from `rejections` for invalid/cli failures; blocked retries reuse the identical prompt;
- per-attempt usage, latency and served model (only sums / the last non-null served model);
- the CLI's own internal structured-output retries (`error_max_structured_output_retries ... after 5 attempts`): those five inner attempts are invisible, counted as one failed engine attempt.

### Prompt rebuild

Rebuilt with `analysis/common.rebuild_prompt` (current `prompts.py`, the log up to the turn's cutoff, and a reconstructed `ctx`): every one of 2170 turns rebuilt without error. Example: seed 1 seq 54 (Ghost, vote): system prompt 9374 chars, turn prompt 6785 chars, schema 1307 chars.

Check of the method on 503 turns of four in-memory mock games (`MockLLM` records the exact text it was sent): turn prompt identical 503/503, system prompt 503/503, schema 503/503. With a naive cutoff of seq-1 instead, for turns that are not the first of their simultaneous phase or whisper step, the rebuilt prompt differs from the one sent in: clue 0 of 73, cut_vote 0 of 4, finale_choice 0 of 4, job 1 of 1, vote 0 of 62, whisper 0 of 68. So the prompt text itself filters most same-phase turns; the first-turn cutoff still matters for anything computed from `visible_events`, which does admit other players' public vote turns and a partner's job turn as soon as they are logged.

Is an exact rebuild of a pilot turn possible? Only if the code that played the batch is the code on disk now. Nothing in the log records a code version or prompt hash (`log_version` is 1, `rules_version` 0.3), the repository has no commits, so the only evidence is file times (prompts.py, schemas.py, engine.py, config.py were last modified before the first pilot1 game started, 03:21 UTC), which is suggestive, not proof. Nothing logged can verify the text: the prompt, system prompt and schema are never written, and the only quantity that depends on them, `usage`, sums every `modelUsage` entry of the CLI reply (including the CLI's own helper call), so it is not a prompt length. Rebuilt length (system + prompt + schema, chars) against logged input + cache tokens, single-attempt turns: `claude-haiku-4-5` r=0.859, tokens/char median 0.57, share of turns above 1.2 tokens/char 0%; `claude-haiku-5-5` r=0.786, tokens/char median 0.64, share of turns above 1.2 tokens/char 0%; `claude-sonnet-4-5` r=0.935, tokens/char median 0.57, share of turns above 1.2 tokens/char 0%; `claude-sonnet-4-6` r=0.994, tokens/char median 0.56, share of turns above 1.2 tokens/char 0%; `claude-sonnet-5` r=0.457, tokens/char median 0.65, share of turns above 1.2 tokens/char 11%. A tokens/char ratio about twice the usual on a minority of turns (mostly claude-sonnet-5) is consistent with extra calls inside the CLI (for example its internal structured-output retries) that the log does not record; the raw stdout that would show this is not kept.

### Turns with more than one attempt

Turns/recaps with attempts > 1: 23. By error kind and model (one count per failed attempt): cli `claude-haiku-4-5`: 1, cli `claude-sonnet-5`: 8, invalid `claude-haiku-4-5`: 10, invalid `claude-haiku-5-5`: 4.

| seed | seq | phase | model | attempts | error_kinds | rejections (first 90 chars) | fallback |
|---|---|---|---|---|---|---|---|
| 1 | 132 | whisper | claude-sonnet-5 | 2 | ['cli'] | is_error: None (subtype error_max_structured_output_retries): Failed to provide valid stru | False |
| 2 | 132 | whisper | claude-sonnet-5 | 2 | ['cli'] | is_error: None (subtype error_max_structured_output_retries): Failed to provide valid stru | False |
| 2 | 153 | vote | claude-sonnet-5 | 2 | ['cli'] | is_error: None (subtype error_max_structured_output_retries): Failed to provide valid stru | False |
| 3 | 146 | discuss | claude-haiku-4-5 | 2 | ['invalid'] | a at_least_one clue card needs exactly 2 different players | False |
| 4 | 46 | discuss | claude-haiku-4-5 | 2 | ['invalid'] | a at_least_one clue card needs exactly 2 different players | False |
| 4 | 143 | discuss | claude-haiku-4-5 | 2 | ['invalid'] | a at_least_one clue card needs exactly 2 different players | False |
| 5 | 137 | whisper | claude-sonnet-5 | 2 | ['cli'] | is_error: None (subtype error_max_structured_output_retries): Failed to provide valid stru | False |
| 5 | 181 | discuss | claude-haiku-4-5 | 2 | ['invalid'] | a at_least_one_of_three clue card needs exactly 3 different players | False |
| 7 | 56 | vote | claude-sonnet-5 | 2 | ['cli'] | is_error: None (subtype error_max_structured_output_retries): Failed to provide valid stru | False |
| 7 | 85 | whisper | claude-haiku-4-5 | 2 | ['invalid'] | a at_least_one clue card needs exactly 2 different players | False |
| 10 | 85 | whisper | claude-haiku-5-5 | 2 | ['invalid'] | your whisper message (public) must not be empty | False |
| 11 | 80 | whisper | claude-haiku-4-5 | 2 | ['invalid'] | a at_least_one clue card needs exactly 2 different players | False |
| 11 | 94 | discuss | claude-haiku-4-5 | 2 | ['invalid'] | a at_least_one clue card needs exactly 2 different players | False |
| 11 | 126 | whisper | claude-haiku-4-5 | 2 | ['invalid'] | a at_least_one clue card needs exactly 2 different players | False |
| 11 | 140 | discuss | claude-haiku-4-5 | 2 | ['invalid'] | a at_least_one clue card needs exactly 2 different players | False |
| 13 | 95 | discuss | claude-sonnet-5 | 2 | ['cli'] | is_error: None (subtype error_max_structured_output_retries): Failed to provide valid stru | False |
| 16 | 81 | whisper | claude-haiku-5-5 | 2 | ['invalid'] | a at_least_one clue card needs exactly 2 different players | False |
| 16 | 85 | whisper | claude-haiku-5-5 | 2 | ['invalid'] | a at_least_one clue card needs exactly 2 different players | False |
| 17 | 92 | discuss | claude-haiku-4-5 | 2 | ['cli'] | is_error: None (subtype error_max_structured_output_retries): Failed to provide valid stru | False |
| 19 | 28 | whisper | claude-haiku-5-5 | 2 | ['invalid'] | a at_least_one clue card needs exactly 2 different players | False |
| 20 | 116 | vote | claude-sonnet-5 | 2 | ['cli'] | is_error: None (subtype error_max_structured_output_retries): Failed to provide valid stru | False |
| 20 | 142 | discuss | claude-sonnet-5 | 2 | ['cli'] | is_error: None (subtype error_max_structured_output_retries): Failed to provide valid stru | False |
| 20 | 144 | discuss | claude-haiku-4-5 | 2 | ['invalid'] | a at_least_one clue card needs exactly 2 different players | False |

Recorded about each failed attempt: its reason string (`rejections[i]`) and kind (`error_kinds[i]`). Not recorded: the reply that failed, its usage, latency or served model separately, and the prompt it was answering.

