# Decision table summary: batch `pilot2`

6 finished games (only games with a `game_end`). Rows: reading 528, round 35, sabotage 14, vote 88.

**Intervals.** Every interval is a 95% percentile bootstrap that resamples whole games (2000 resamples, fixed seed 20261110); every statistic is a pooled mean over decisions in the resampled games. Each number is printed with n (decisions) and g (games) - in a table, the row's `n` and `games` columns apply to every cell that has no `(n=, g=)` of its own. Where fewer than 5 games contribute, the cell says `too few` instead of an interval.

**What the player could know.** All solver numbers use only events visible to that player (`log.visible_events`), up to a cutoff: for simultaneous phases (clue, job, vote, cut_vote, finale_choice) the seq just before the first turn of that phase in that round; for whisper steps (run in lockstep across pairs) the seq before the first turn of the step; for sequential phases (pick, discuss) seq-1.

These are show games (seven seats, five models, two seated twice). docs/CLAIMS.md says show games support none of its claims; the numbers below describe this batch only.

## a. Read (crew readings)

Brier = mean over rated players of (p - truth)^2. *model* = the stated suspicion, *solver* = the ideal reasoner from the reader's view at the cutoff, *base* = moles alive / players rated. `read_gap` = brier_model - brier_solver (the Read metric). *beats base* / *beats solver* = share of readings with a strictly lower Brier than that reference.

| all | n | games | brier_model | brier_solver | brier_base | read_gap | beats base | beats solver |
|---|---|---|---|---|---|---|---|---|
| all crew readings | 356 | 6 | 0.213 [0.185, 0.240] | 0.187 [0.179, 0.196] | 0.226 [0.221, 0.231] | 0.026 [0.006, 0.045] | 46% [35%, 55%] | 33% [20%, 44%] |

| round | n | games | brier_model | brier_solver | brier_base | read_gap | beats base | beats solver |
|---|---|---|---|---|---|---|---|---|
| 1 | 156 | 6 | 0.246 [0.226, 0.262] | 0.211 [0.202, 0.221] | 0.222 [0.222, 0.222] | 0.035 [0.019, 0.051] | 22% [13%, 32%] | 17% [9%, 28%] |
| 2 | 126 | 6 | 0.229 [0.196, 0.265] | 0.187 [0.171, 0.197] | 0.240 [0.240, 0.240] | 0.043 [0.005, 0.079] | 51% [33%, 67%] | 38% [23%, 56%] |
| 3 | 68 | 6 | 0.122 [0.065, 0.193] | 0.144 [0.132, 0.156] | 0.211 [0.191, 0.240] | -0.022 [-0.082, 0.053] | 87% [67%, 100%] | 60% [28%, 83%] |
| 4 | 6 | 1 | 0.072 (too few) | 0.083 (too few) | 0.222 (too few) | -0.011 (too few) | 100% (too few) | 50% (too few) |

| phase | n | games | brier_model | brier_solver | brier_base | read_gap | beats base | beats solver |
|---|---|---|---|---|---|---|---|---|
| clue | 77 | 6 | 0.201 [0.184, 0.218] | 0.190 [0.180, 0.199] | 0.226 [0.220, 0.232] | 0.012 [0.000, 0.026] | 44% [34%, 57%] | 22% [10%, 33%] |
| whisper | 96 | 6 | 0.198 [0.170, 0.223] | 0.193 [0.179, 0.203] | 0.224 [0.217, 0.232] | 0.005 [-0.019, 0.024] | 57% [46%, 71%] | 47% [36%, 61%] |
| discuss | 122 | 6 | 0.226 [0.188, 0.262] | 0.184 [0.174, 0.194] | 0.228 [0.222, 0.233] | 0.041 [0.014, 0.069] | 41% [22%, 56%] | 31% [15%, 44%] |
| vote | 61 | 6 | 0.228 [0.188, 0.268] | 0.182 [0.172, 0.193] | 0.228 [0.222, 0.233] | 0.045 [0.014, 0.079] | 41% [23%, 54%] | 31% [15%, 45%] |

| stage | n | games | brier_model | brier_solver | brier_base | read_gap | beats base | beats solver |
|---|---|---|---|---|---|---|---|---|
| clue | 77 | 6 | 0.201 [0.184, 0.218] | 0.190 [0.180, 0.199] | 0.226 [0.220, 0.232] | 0.012 [0.000, 0.026] | 44% [34%, 57%] | 22% [10%, 33%] |
| whisper1 | 48 | 6 | 0.199 [0.174, 0.221] | 0.193 [0.180, 0.203] | 0.224 [0.217, 0.232] | 0.005 [-0.014, 0.023] | 52% [44%, 65%] | 44% [39%, 49%] |
| whisper2 | 48 | 6 | 0.197 [0.163, 0.227] | 0.193 [0.179, 0.203] | 0.224 [0.217, 0.232] | 0.004 [-0.025, 0.030] | 62% [47%, 79%] | 50% [31%, 72%] |
| discuss1 | 61 | 6 | 0.223 [0.181, 0.260] | 0.186 [0.174, 0.196] | 0.228 [0.222, 0.233] | 0.036 [0.006, 0.066] | 39% [21%, 53%] | 30% [14%, 43%] |
| discuss2 | 61 | 6 | 0.229 [0.195, 0.266] | 0.182 [0.173, 0.193] | 0.228 [0.222, 0.233] | 0.047 [0.019, 0.075] | 43% [21%, 59%] | 33% [17%, 46%] |
| vote | 61 | 6 | 0.228 [0.188, 0.268] | 0.182 [0.172, 0.193] | 0.228 [0.222, 0.233] | 0.045 [0.014, 0.079] | 41% [23%, 54%] | 31% [15%, 45%] |

| model | n | games | brier_model | brier_solver | brier_base | read_gap | beats base | beats solver |
|---|---|---|---|---|---|---|---|---|
| claude-haiku-4-5 | 110 | 6 | 0.245 [0.213, 0.286] | 0.182 [0.166, 0.207] | 0.228 [0.222, 0.233] | 0.063 [0.032, 0.096] | 40% [19%, 54%] | 26% [13%, 39%] |
| claude-haiku-5-5 | 41 | 4 | 0.206 (too few) | 0.209 (too few) | 0.234 (too few) | -0.003 (too few) | 54% (too few) | 41% (too few) |
| claude-sonnet-4-5 | 38 | 3 | 0.193 (too few) | 0.185 (too few) | 0.224 (too few) | 0.008 (too few) | 45% (too few) | 42% (too few) |
| claude-sonnet-4-6 | 105 | 6 | 0.193 [0.165, 0.231] | 0.190 [0.176, 0.203] | 0.223 [0.218, 0.231] | 0.004 [-0.019, 0.040] | 46% [30%, 56%] | 36% [22%, 46%] |
| claude-sonnet-5 | 62 | 5 | 0.208 [0.199, 0.215] | 0.181 [0.156, 0.206] | 0.226 [0.219, 0.233] | 0.027 [0.009, 0.045] | 53% [47%, 67%] | 31% [24%, 39%] |

Log scores (mean negative log likelihood, p clipped to [0.01, 0.99]):

| set | n | games | log_model | log_solver | log_base |
|---|---|---|---|---|---|
| all crew readings | 356 | 6 | 0.614 [0.540, 0.684] | 0.544 [0.521, 0.569] | 0.645 [0.633, 0.655] |

Crew readings where model and solver Brier tie exactly: 1 of 356. Solver inconsistent (fell back to reveals and jobs): 0. Readings whose rated set is not exactly the other living players: 0.

### a.1 Reconciliation with docs/pilot1_report.md (section 5)

Same selection as the report: each crew player's last non-fallback reading per round.

- Readings selected: 77 (report: 261); the same turns as `report.game_readings`: 77 of 77.
- Crew Brier: 0.2045 (report: 0.162); solver ('ideal') Brier at my cutoff: 0.1720; `game_readings` ideal (upto_seq = the turn's own seq): 0.1720 (report: 0.135).
- Selected readings whose solver Brier differs between the two cutoffs: 0; whose model Brier differs: 0.
- Phases of the selected readings: clue 5, vote 61, whisper 11.
- Over all 528 readings (crew and mole), the solver posterior from the reader's view differs between upto_seq = own seq and my cutoff in 1 (discuss 1). `visible_to` makes every other player's vote turn (public part: reason and target) visible as soon as it is in the slice, so a cutoff at a vote turn's own seq 'sees' the earlier voters' votes, which the real prompt never did; the solver ignores vote turns (only cards, job results and reveals enter it), so this cannot move a solver number. `visible_to` also admits a partner mole's `job` turn (via `shared_with`) as soon as it is logged, so for the second mole on a team a seq-1 or own-seq cutoff would show the partner's choice, which the real prompt never did (see section h). A discuss turn's own seq adds the speaker's own tabled cards to their view; that is what the count above picks up.

## b. Calibration of crew readings

Unit: one stated probability (a reading of one player). Bins of stated suspicion; the last bin includes 100.

| stated | n | games | mean stated | observed mole share | mean solver posterior |
|---|---|---|---|---|---|
| 0-9 | 60 | 5 | 0.036 | 0.083 [0.000, 0.520] | 0.206 [0.132, 0.419] |
| 10-19 | 243 | 6 | 0.136 | 0.144 [0.084, 0.218] | 0.260 [0.230, 0.293] |
| 20-29 | 426 | 6 | 0.231 | 0.298 [0.260, 0.332] | 0.306 [0.284, 0.327] |
| 30-39 | 387 | 6 | 0.327 | 0.377 [0.339, 0.416] | 0.354 [0.344, 0.365] |
| 40-49 | 240 | 6 | 0.426 | 0.429 [0.374, 0.496] | 0.400 [0.389, 0.413] |
| 50-59 | 159 | 6 | 0.526 | 0.409 [0.304, 0.517] | 0.403 [0.382, 0.431] |
| 60-69 | 135 | 6 | 0.628 | 0.511 [0.436, 0.618] | 0.438 [0.409, 0.475] |
| 70-79 | 123 | 6 | 0.721 | 0.512 [0.384, 0.631] | 0.501 [0.458, 0.545] |
| 80-89 | 44 | 6 | 0.830 | 0.591 [0.500, 0.750] | 0.506 [0.449, 0.551] |
| 90-100 | 39 | 4 | 0.951 | 0.795 (too few) | 0.618 (too few) |

Hedging: mean stated suspicion grouped by the solver's posterior for the same player at the same moment (reader's view).

| solver band | n | games | mean stated | mean solver | observed mole share |
|---|---|---|---|---|---|
| solver >= 0.99 | 36 | 4 | 0.709 (too few) | 1.000 | 1.000 (too few) |
| solver <= 0.01 | 114 | 6 | 0.205 [0.125, 0.348] | 0.000 | 0.000 [0.000, 0.000] |
| 0.01 < solver <= 1/3 | 984 | 6 | 0.312 [0.290, 0.332] | 0.290 | 0.272 [0.242, 0.301] |
| 1/3 < solver <= 2/3 | 689 | 6 | 0.466 [0.450, 0.478] | 0.470 | 0.483 [0.447, 0.535] |
| 2/3 < solver < 0.99 | 33 | 5 | 0.495 [0.354, 0.640] | 0.769 | 1.000 [1.000, 1.000] |

## c. Votes

Every non-fallback vote. *hit* = voted for a mole. *solver argmax hit* (crew only) = expected hit rate voting uniformly among the solver's most likely players. *base* = share of the voter's valid targets that are moles (random-vote hit rate; for a mole voter this counts their partner). *regret* = solver p(best) - solver p(target) (crew). *own top* = vote went to a player the voter rated highest in the same turn (ties count). *own accusation* = vote equals the voter's last accusation this round (only voters who accused). *most accused* = vote on a player with the most discussion accusations this round (ties count; only rounds with an accusation).

| round | role | n | games | hit | solver argmax hit | base | regret | own top | own accusation | most accused |
|---|---|---|---|---|---|---|---|---|---|---|
| all | all | 88 | 6 | 35% [20%, 47%] | 65% [57%, 72%] (n=61, g=6) | 31% [29%, 32%] | 0.117 [0.065, 0.171] (n=61, g=6) | 86% [82%, 90%] | 85% [79%, 90%] (n=80, g=6) | 67% [59%, 77%] |
| all | crew | 61 | 6 | 48% [28%, 63%] | 65% [57%, 72%] | 36% [34%, 38%] | 0.117 [0.065, 0.171] | 95% [88%, 100%] | 86% [80%, 93%] (n=58, g=6) | 64% [49%, 78%] |
| all | mole | 27 | 6 | 7% [0%, 17%] | - (n=0, g=0) | 18% [16%, 20%] | - (n=0, g=0) | 67% [52%, 79%] | 82% [65%, 96%] (n=22, g=6) | 74% [56%, 90%] |
| 1 | crew | 30 | 6 | 20% [3%, 40%] | 46% [28%, 62%] | 33% [33%, 33%] | 0.085 [0.020, 0.163] | 97% [90%, 100%] | 85% [71%, 97%] (n=27, g=6) | 70% [47%, 90%] |
| 1 | mole | 12 | 6 | 0% [0%, 0%] | - (n=0, g=0) | 17% [17%, 17%] | - (n=0, g=0) | 83% [67%, 100%] | 89% [67%, 100%] (n=9, g=5) | 92% [75%, 100%] |
| 2 | crew | 24 | 6 | 71% [46%, 92%] | 88% [77%, 96%] | 40% [40%, 40%] | 0.102 [0.042, 0.160] | 96% [88%, 100%] | 83% [67%, 96%] | 54% [25%, 79%] |
| 2 | mole | 12 | 6 | 17% [0%, 33%] | - (n=0, g=0) | 20% [20%, 20%] | - (n=0, g=0) | 50% [25%, 75%] | 80% [60%, 100%] (n=10, g=6) | 58% [33%, 83%] |
| 3 | crew | 7 | 2 | 86% (too few) | 67% (too few) | 36% (too few) | 0.310 (too few) | 86% (too few) | 100% (too few) | 71% (too few) |
| 3 | mole | 3 | 2 | 0% (too few) | - (n=0, g=0) | 17% (too few) | - (n=0, g=0) | 67% (too few) | 67% (too few) | 67% (too few) |

Check: 88 vote rows (expected 326 for pilot1); eliminations 14, of which a mole 4 (expected 32 of 54).
Crew votes with zero regret (on a solver-best player): 38 of 61; crew votes where the solver's best set is a single player: 22; own top suspicion tied: 1 of 88.

## d. Sabotage (job turns)

Only moles on the team are asked; crew help automatically. **The solver gives no ideal answer for this decision**: the columns below (the scripted `smart` rule, how much a blown job would move the public posterior on this mole, what happened next) are the closest available references, not a correct answer. *script* = sabotage unless the partner is also on the team and sits in a lower seat, then help. *exposure* = public posterior on this mole if this job came back blown with one sabotage, minus the public posterior before.

Job turns: 14 (fallback 0).

| decisions | n | games | sabotage rate | agrees with script | mean exposure |
|---|---|---|---|---|---|
| all | 14 | 4 | 50% (too few) | 29% (too few) | 0.109 (too few) |
| round 1 | 2 | 2 | 0% (too few) | 0% (too few) | 0.114 (too few) |
| round 2 | 7 | 4 | 57% (too few) | 43% (too few) | 0.091 (too few) |
| round 3 | 3 | 2 | 67% (too few) | 33% (too few) | 0.222 (too few) |
| round 4 | 2 | 1 | 50% (too few) | 0% (too few) | 0.000 (too few) |
| wins_now = true | 5 | 3 | 60% (too few) | 20% (too few) | 0.133 (too few) |
| wins_now = false | 9 | 4 | 44% (too few) | 33% (too few) | 0.096 (too few) |
| partner on team | 10 | 4 | 50% (too few) | 20% (too few) | 0.055 (too few) |
| partner not on team | 4 | 3 | 50% (too few) | 50% (too few) | 0.245 (too few) |
| clean job would win for crew | 2 | 1 | 50% (too few) | 0% (too few) | 0.000 (too few) |

Exposure by choice:

| choice | n | games | mean exposure | public p(self) before | self voted out this round |
|---|---|---|---|---|---|
| sabotage | 7 | 4 | 0.146 (too few) | 0.501 (too few) | 29% (too few) |
| help | 7 | 4 | 0.073 (too few) | 0.382 (too few) | 0% (too few) |

Every job decision:

| seed | round | mole | model | team | partner on | choice | script | wins now | p(self) | exposure | job | crew share on moles | self out |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 1 | Rook | claude-haiku-4-5 | 3 | False | help | sabotage | False | 0.29 | +0.11 | clean (0) | 0.00 | False |
| 2 | 2 | Wren | claude-sonnet-4-6 | 3 | True | help | sabotage | False | 0.33 | +0.10 | blown (1) | 0.25 | False |
| 2 | 2 | Rook | claude-haiku-4-5 | 3 | True | sabotage | help | False | 0.33 | +0.10 | blown (1) | 0.25 | False |
| 2 | 3 | Wren | claude-sonnet-4-6 | 3 | True | help | sabotage | True | 0.67 | +0.00 | blown (1) | - | False |
| 2 | 3 | Rook | claude-haiku-4-5 | 3 | True | sabotage | help | True | 0.67 | +0.00 | blown (1) | - | False |
| 3 | 2 | Slate | claude-sonnet-4-6 | 3 | False | sabotage | sabotage | False | 0.42 | +0.08 | blown (1) | 0.50 | False |
| 3 | 4 | Slate | claude-sonnet-4-6 | 2 | True | sabotage | help | True | 1.00 | +0.00 | blown (1) | - | False |
| 3 | 4 | Juno | claude-sonnet-4-5 | 2 | True | help | sabotage | True | 0.33 | +0.00 | blown (1) | - | False |
| 5 | 1 | Moth | claude-sonnet-4-5 | 3 | False | help | sabotage | False | 0.29 | +0.11 | clean (0) | 0.40 | False |
| 5 | 2 | Moth | claude-sonnet-4-5 | 3 | True | help | help | False | 0.27 | +0.06 | blown (1) | 1.00 | False |
| 5 | 2 | Vesper | claude-sonnet-4-6 | 3 | True | sabotage | sabotage | False | 0.45 | +0.10 | blown (1) | 1.00 | True |
| 5 | 3 | Moth | claude-sonnet-4-5 | 3 | False | sabotage | sabotage | True | 0.33 | +0.67 | blown (1) | - | False |
| 6 | 2 | Juno | claude-haiku-5-5 | 3 | True | help | sabotage | False | 0.50 | +0.12 | blown (1) | 1.00 | False |
| 6 | 2 | Slate | claude-haiku-4-5 | 3 | True | sabotage | help | False | 0.30 | +0.08 | blown (1) | 1.00 | True |

## e. Getaway (Bluff unit: one mole, one round)

*getaway* = (1 if the job was blown, else 0) x (1 - share of the crew's non-fallback votes on any mole that round); a blown job that ends the game with no vote scores 1; a clean job scores 0. Rows: 35; scored 35.

| mole rounds | n | games | getaway = 0 | getaway = 1 | mean getaway | job blown |
|---|---|---|---|---|---|---|
| all | 35 | 6 | 74% [53%, 97%] | 14% [3%, 25%] | 0.214 [0.030, 0.392] | 37% [12%, 56%] |
| round 1 | 12 | 6 | 100% [100%, 100%] | 0% [0%, 0%] | 0.000 [0.000, 0.000] | 0% [0%, 0%] |
| round 2 | 12 | 6 | 67% [33%, 100%] | 0% [0%, 0%] | 0.208 [0.000, 0.458] | 67% [33%, 100%] |
| round 3 | 9 | 6 | 67% [25%, 100%] | 33% [0%, 75%] | 0.333 [0.000, 0.750] | 33% [0%, 75%] |
| round 4 | 2 | 1 | 0% (too few) | 100% (too few) | 1.000 (too few) | 100% (too few) |
| `claude-haiku-4-5` | 5 | 2 | 60% (too few) | 20% (too few) | 0.350 (too few) | 60% (too few) |
| `claude-haiku-5-5` | 5 | 2 | 100% (too few) | 0% (too few) | 0.000 (too few) | 20% (too few) |
| `claude-sonnet-4-5` | 10 | 3 | 70% (too few) | 20% (too few) | 0.250 (too few) | 40% (too few) |
| `claude-sonnet-4-6` | 12 | 4 | 67% (too few) | 17% (too few) | 0.271 (too few) | 42% (too few) |
| `claude-sonnet-5` | 3 | 1 | 100% (too few) | 0% (too few) | 0.000 (too few) | 0% (too few) |
| self on team | 14 | 4 | 43% (too few) | 36% (too few) | 0.500 (too few) | 86% (too few) |
| self not on team | 21 | 6 | 95% [87%, 100%] | 0% [0%, 0%] | 0.024 [0.000, 0.065] | 5% [0%, 13%] |
| no mole on team | 18 | 4 | 100% (too few) | 0% (too few) | 0.000 (too few) | 0% (too few) |

Getaway values that are neither 0 nor 1: 0.50, 0.50, 0.75, 0.75.

## f. Table read (mole readings)

*target* for each rated player X = mean over crew still in (excluding X) of that crew member's latest non-fallback belief of X before this turn's cutoff. tr_err = mean over rated players with a target of (value - target)^2, for the mole's stated read (*model*), the solver's public posterior (*public*) and the constant base rate (*base* = moles alive / players rated, what a crew member with no information would say and the engine's fallback value). gap = tr_err_model - tr_err_public. A mole does not rate themselves, so how much the crew suspect the reader is never part of this score. Mole readings: 172; with a target: 160 (no crew reading exists before the first clue turn of the game, so round 1 clue readings have none).

| mole readings | n | games | tr_err_model | tr_err_public | tr_err_base | gap | beats base |
|---|---|---|---|---|---|---|---|
| all | 160 | 6 | 0.029 [0.023, 0.033] | 0.031 [0.014, 0.049] | 0.026 [0.016, 0.037] | -0.002 [-0.020, 0.013] | 41% [32%, 47%] |
| round 1 | 56 | 6 | 0.024 [0.019, 0.030] | 0.011 [0.006, 0.016] | 0.009 [0.008, 0.010] | 0.013 [0.008, 0.018] | 20% [12%, 29%] |
| round 2 | 66 | 6 | 0.027 [0.020, 0.034] | 0.023 [0.015, 0.032] | 0.024 [0.019, 0.029] | 0.004 [-0.006, 0.011] | 45% [38%, 53%] |
| round 3 | 32 | 6 | 0.038 [0.023, 0.054] | 0.067 [0.020, 0.115] | 0.044 [0.018, 0.062] | -0.029 [-0.081, 0.024] | 56% [27%, 83%] |
| round 4 | 6 | 1 | 0.044 (too few) | 0.107 (too few) | 0.115 (too few) | -0.063 (too few) | 100% (too few) |
| clue | 23 | 6 | 0.019 [0.015, 0.022] | 0.041 [0.022, 0.056] | 0.048 [0.028, 0.066] | -0.022 [-0.037, -0.004] | 70% [52%, 84%] |
| whisper | 56 | 6 | 0.032 [0.024, 0.040] | 0.021 [0.008, 0.035] | 0.022 [0.008, 0.037] | 0.011 [0.002, 0.020] | 34% [19%, 47%] |
| discuss | 54 | 6 | 0.030 [0.020, 0.040] | 0.030 [0.015, 0.048] | 0.019 [0.014, 0.024] | 0.000 [-0.021, 0.021] | 26% [16%, 38%] |
| vote | 27 | 6 | 0.028 [0.020, 0.036] | 0.044 [0.020, 0.070] | 0.028 [0.021, 0.036] | -0.016 [-0.044, 0.009] | 59% [52%, 67%] |
| `claude-haiku-4-5` | 23 | 2 | 0.025 (too few) | 0.022 (too few) | 0.030 (too few) | 0.003 (too few) | 57% (too few) |
| `claude-haiku-5-5` | 28 | 2 | 0.032 (too few) | 0.017 (too few) | 0.018 (too few) | 0.016 (too few) | 32% (too few) |
| `claude-sonnet-4-5` | 42 | 3 | 0.029 (too few) | 0.045 (too few) | 0.030 (too few) | -0.016 (too few) | 50% (too few) |
| `claude-sonnet-4-6` | 53 | 4 | 0.031 (too few) | 0.034 (too few) | 0.028 (too few) | -0.004 (too few) | 32% (too few) |
| `claude-sonnet-5` | 14 | 1 | 0.020 (too few) | 0.014 (too few) | 0.015 (too few) | 0.006 (too few) | 36% (too few) |

## g. Feature audit

Counts only; what the logs show.

**Whisper requests.**

| requester | requests | 'none' | mutual | mole asked partner |
|---|---|---|---|---|
| crew | 77 | 6% [3%, 10%] | 21% [8%, 32%] | 0 |
| mole | 35 | 9% [3%, 14%] | 40% [21%, 65%] | 15 |

Pairs formed per round: round 1: mean 2.33 over 6 games ({2: 4, 3: 2}); round 2: mean 2.00 over 6 games ({1: 1, 2: 4, 3: 1}); round 3: mean 1.67 over 6 games ({1: 2, 2: 4}); round 4: mean 2.00 over 1 games ({2: 1}).
Whisper turns (non-fallback): 152; with a clue card: 43; cards shown: 43.

**Belief movement (crew).** Consecutive non-fallback readings of the same crew player in the same round, in the order clue, whisper 1, whisper 2, discuss pass 1, discuss pass 2, vote (a missing stage is skipped). *|change|* = mean absolute change in stated probability over the rated players; *dBrier* = later Brier minus earlier (negative = moved towards the truth); *dBrier solver* = the same for the solver over the same step (the information that arrived). Note the job result arrives between the whisper/clue readings and discuss pass 1.

| step | n | games | |change| | any change | dBrier model | dBrier solver |
|---|---|---|---|---|---|---|
| clue -> whisper1 | 48 | 6 | 0.060 [0.050, 0.068] | 83% [74%, 92%] | -0.006 [-0.015, 0.001] | 0.001 [0.000, 0.001] |
| clue -> discuss1 | 24 | 6 | 0.103 [0.084, 0.115] | 100% [100%, 100%] | 0.027 [-0.006, 0.063] | -0.010 [-0.027, 0.004] |
| whisper1 -> whisper2 | 48 | 6 | 0.075 [0.065, 0.085] | 98% [94%, 100%] | -0.001 [-0.016, 0.016] | -0.000 [-0.001, 0.001] |
| whisper2 -> discuss1 | 37 | 6 | 0.093 [0.072, 0.108] | 100% [100%, 100%] | -0.010 [-0.027, 0.011] | -0.024 [-0.038, -0.008] |
| discuss1 -> discuss2 | 61 | 6 | 0.112 [0.098, 0.128] | 98% [95%, 100%] | 0.007 [-0.008, 0.020] | -0.004 [-0.008, 0.001] |
| discuss2 -> vote | 61 | 6 | 0.080 [0.067, 0.090] | 93% [87%, 98%] | -0.001 [-0.013, 0.013] | -0.000 [-0.001, 0.000] |

**Second discussion pass.**

| players (player-rounds with both passes) | n | accusation changes pass 1 -> 2 | 'none' in both passes |
|---|---|---|---|
| all | 88 | 52% [41%, 61%] | 9% [2%, 18%] |
| crew | 61 | 52% [43%, 63%] | 5% [0%, 12%] |
| mole | 27 | 52% [29%, 69%] | 19% [7%, 33%] |

Votes by players who spoke in both passes: 88. Match the pass-2 accusation but not pass 1: 42% [31%, 53%]; match pass 1 but not pass 2: 1% [0%, 4%]; match both: 35% [31%, 42%].

**`challenges` and `accuse` (discussion turns, non-fallback).** *base* = share of the possible targets that were moles (for challenges: statements by others earlier this round; for accuse: the other living players).

| speaker | discuss turns | uses challenges | challenge ids | aimed at a mole's statement | base | accuses someone | accusation on a mole | base |
|---|---|---|---|---|---|---|---|---|
| crew | 122 | 39% [28%, 49%] | 68 | 34% [27%, 45%] | 39% [35%, 43%] | 80% [72%, 85%] | 49% [32%, 62%] | 37% [34%, 39%] |
| mole | 54 | 30% [15%, 44%] | 19 | 5% [0%, 14%] | 19% [17%, 23%] | 63% [54%, 73%] | 6% [0%, 20%] | 19% [15%, 21%] |

**Clue cards** (engine checks: real = the speaker holds that clue; true = true in the actual world).

| where | role | cards | real, true | real, false | fake, true | fake, false |
|---|---|---|---|---|---|---|
| tabled | crew | 30 | 30 | 0 | 0 | 0 |
| tabled | mole | 16 | 14 | 0 | 0 | 2 |
| whispered | crew | 27 | 25 | 0 | 2 | 0 |
| whispered | mole | 16 | 13 | 0 | 1 | 2 |

Clues dealt (real, non-'none'): crew 34, mole 18; 'no intel': crew 43, mole 17.

**`job_claim`** (discussion turns; actual = the engine's job choice; crew always help).

| role | on team | claimed | actual | turns |
|---|---|---|---|---|
| crew | no | none | - | 56 |
| crew | yes | helped | help | 49 |
| crew | yes | none | help | 17 |
| mole | no | none | - | 36 |
| mole | yes | helped | help | 7 |
| mole | yes | helped | sabotage | 4 |
| mole | yes | none | help | 3 |
| mole | yes | none | sabotage | 3 |
| mole | yes | sabotaged | sabotage | 1 |

**The Cut.** Record = votes the player cast for a mole (as `engine.vote_record` counts it: the target's true role, whether or not revealed).

Cuts held: 3 (survivors: {3: 1, 4: 2}). Cut votes: 11. On a candidate with the best record among the voter's options: 100% (too few); expected if random: 91% (too few). Where exactly one option had the best record: 100% (too few) vs random 50% (too few).
Finalists are the two best records: 3 of 3. Tiebreaks: {'random': 1, 'None': 2}. Cuts where counting only *revealed* moles would change some record: 1.

**Finale choices.** stated -> chosen: split -> split: 5, split -> steal: 4, steal -> steal: 1. Outcomes: split/split 2, split/steal 1, steal/steal 2.

**Truncation** (non-fallback turns trimmed at the hard word cap).

| model | turns | truncated | confessional | public | memory | claims |
|---|---|---|---|---|---|---|
| `claude-haiku-4-5` | 150 | 14 | 8 | 5 | 1 | 0 |
| `claude-haiku-5-5` | 79 | 0 | 0 | 0 | 0 | 0 |
| `claude-sonnet-4-5` | 99 | 2 | 1 | 1 | 0 | 0 |
| `claude-sonnet-4-6` | 193 | 1 | 0 | 1 | 0 | 0 |
| `claude-sonnet-5` | 82 | 0 | 0 | 0 | 0 | 0 |

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

Rebuilt with `analysis/common.rebuild_prompt` (current `prompts.py`, the log up to the turn's cutoff, and a reconstructed `ctx`): every one of 603 turns rebuilt without error. Example: seed 1 seq 57 (Ghost, vote): system prompt 9370 chars, turn prompt 8260 chars, schema 1307 chars.

Check of the method on 503 turns of four in-memory mock games (`MockLLM` records the exact text it was sent): turn prompt identical 503/503, system prompt 503/503, schema 503/503. With a naive cutoff of seq-1 instead, for turns that are not the first of their simultaneous phase or whisper step, the rebuilt prompt differs from the one sent in: clue 0 of 73, cut_vote 0 of 4, finale_choice 0 of 4, job 1 of 1, vote 0 of 62, whisper 0 of 68. So the prompt text itself filters most same-phase turns; the first-turn cutoff still matters for anything computed from `visible_events`, which does admit other players' public vote turns and a partner's job turn as soon as they are logged.

Is an exact rebuild of a pilot turn possible? Only if the code that played the batch is the code on disk now. Nothing in the log records a code version or prompt hash (`log_version` is 1, `rules_version` 0.3), the repository has no commits, so the only evidence is file times (prompts.py, schemas.py, engine.py, config.py were last modified before the first pilot1 game started, 03:21 UTC), which is suggestive, not proof. Nothing logged can verify the text: the prompt, system prompt and schema are never written, and the only quantity that depends on them, `usage`, sums every `modelUsage` entry of the CLI reply (including the CLI's own helper call), so it is not a prompt length. Rebuilt length (system + prompt + schema, chars) against logged input + cache tokens, single-attempt turns: `claude-haiku-4-5` r=0.847, tokens/char median 0.56, share of turns above 1.2 tokens/char 0%; `claude-haiku-5-5` r=0.819, tokens/char median 0.63, share of turns above 1.2 tokens/char 0%; `claude-sonnet-4-5` r=0.993, tokens/char median 0.56, share of turns above 1.2 tokens/char 0%; `claude-sonnet-4-6` r=0.993, tokens/char median 0.56, share of turns above 1.2 tokens/char 0%; `claude-sonnet-5` r=0.427, tokens/char median 0.64, share of turns above 1.2 tokens/char 7%. A tokens/char ratio about twice the usual on a minority of turns (mostly claude-sonnet-5) is consistent with extra calls inside the CLI (for example its internal structured-output retries) that the log does not record; the raw stdout that would show this is not kept.

### Turns with more than one attempt

Turns/recaps with attempts > 1: 3. By error kind and model (one count per failed attempt): cli `claude-haiku-4-5`: 1, cli `claude-sonnet-5`: 1, invalid `claude-haiku-4-5`: 1.

| seed | seq | phase | model | attempts | error_kinds | rejections (first 90 chars) | fallback |
|---|---|---|---|---|---|---|---|
| 2 | 28 | whisper | claude-haiku-4-5 | 2 | ['invalid'] | a at_least_one clue card needs exactly 2 different players | False |
| 2 | 40 | discuss | claude-haiku-4-5 | 2 | ['cli'] | is_error: None (subtype error_max_structured_output_retries): Failed to provide valid stru | False |
| 3 | 91 | discuss | claude-sonnet-5 | 2 | ['cli'] | is_error: None (subtype error_max_structured_output_retries): Failed to provide valid stru | False |

Recorded about each failed attempt: its reason string (`rejections[i]`) and kind (`error_kinds[i]`). Not recorded: the reply that failed, its usage, latency or served model separately, and the prompt it was answering.

