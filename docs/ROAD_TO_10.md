# Inside Job — road to 10/10 for the benchmark

Written 2026-11-11 by the lead. Sections 1 to 3 were replaced at 14:30 the same day with the
30-game results: all three mole models have played seeds 101 to 110. The 25-game interim text is gone.

**From 14:55 the plan forward is `docs/BENCH_V2.md`** (the owner's Bench v2 brief), with its pass
marks in `docs/ANALYSIS.md` (hashed). Where this file's sections 5 to 7 differ from those two, they
win; the null-test mark (7b) and the probe marks (9b) are carried into ANALYSIS.md as N1, M1 to M5
and S3.

## 1. Verdict at 30 games

**The Fable 5.2 result does not survive the pre-registered first-vote check.** Over the whole game
the difference is measured. At the first vote it is not established, and the mark it gets there is
the one that section 4 ruled, before game 30 ended, counts as failing.

- **Measured, whole game (10 seeds each):** the crew's suspicion gap for Fable 5.2 moles is lower
  than for Haiku 4.5 moles by 15.9 points [-27.7, -6.3] and lower than for Opus 5.5 moles by 17.5
  [-28.2, -7.3], on 9 of 10 seeds each (sign-flip p = 0.004 both; `bluff_score.py`'s permutation
  test gives p = 0.015 and 0.014).
- **Measured, first vote (P1):** the difference is -4.0 [-10.6, +2.4], 6 of 10 seeds, against
  Haiku 4.5 and -0.8 [-5.4, +4.4], 7 of 10 seeds, against Opus 5.5. Both intervals include zero.
  Mark: **no mark**, which section 4 treats as **fails**.
- **Measured:** at the first vote nobody's moles are suspected. The crew rate the moles *below* the
  innocent players for all three models (-3.8, -6.9, -7.7).
- **Measured:** the difference opens at round 2. Crew gap in round 2: Fable 5.2 +5.7 (8 games),
  Haiku 4.5 +27.0, Opus 5.5 +27.9 (10 games each). In the same game state the difference is -21.0
  [-38.8, +1.8] against Haiku 4.5 and -14.1 [-26.7, -1.6] against Opus 5.5 (P3: direction only).
- **Measured:** Fable 5.2 moles won 6 of 10 games; Haiku 4.5 moles 2 of 10; Opus 5.5 moles 2 of 10.
  All six Fable 5.2 wins are on seeds 101 to 107. On seeds 108 to 110 the crew won all nine games,
  whoever the moles were.
- **Measured:** the whole-game difference shrank with the last three seeds, from about 21 points
  on 7 seeds to 16 to 17 on 10. On seeds 108 to 110 it is -6.0, -2.3, +1.0 against Haiku 4.5 and
  -26.7, -2.8, +1.5 against Opus 5.5.
- **Wording:** "left less evidence", not "fooled the crew". P2 fails (round 1 against Haiku 4.5:
  3 of 10 seeds below zero, mean +2.7).

What follows, under the rules written before the result:

- No Fable 5.2 Bluff post is drafted.
- The win counts and the by-round table may be reported as description, with the mechanism stated
  as not established.
- "Two groups, not a ranking" still describes the whole-game number: Fable 5.2 apart from Haiku 4.5
  and Opus 5.5, which cannot be told apart from each other (difference 1.6, 5 of 10 seeds, p = 0.80).
- Until the null test (section 6, step 10) no difference on this measure has a measured noise floor.

Three posts that do not depend on the Fable result were drafted (internal drafts, not published).

## 2. How to read this file

- **Measured** means a number taken from the logs by a named script. **Planned** means nothing has
  been run. Every table and list below is tagged one or the other.
- Scripts and file hashes (sha256) as run for this file, checked unchanged at 14:23 on 2026-11-11
  before the 30-game run:
  - `python3.11 analysis/bluff_mechanism.py` — `405f8d9e…6ebbd`. Every first-vote, formula and
    matching number. Tests: `tests/test_bluff_mechanism.py`.
  - `python3.11 analysis/bluff_score.py` — `75ece727…4bbcd`. Whole-game gap, wins, votes, calls
    and tokens per game.
  - `python3.11 -m inside_job probes score --set probes/sets/read_v1.jsonl` — the Read probe numbers
    in `docs/probe_check_read_v1.md`.
  - `python3.11 analysis/explore.py` — the behaviour counts in `docs/EXPLORE.md`. Its game list is
    fixed at 21 Bluff games (seeds 101 to 107); it was not rerun at 30.
  - `docs/PREREG_7A.md` — `a370b129…cf8840`, never edited.
- Intervals are 95%, by bootstrap over whole games, or over seeds when paired by seed.
- Games: every finished, unspoiled game in the three Bluff groups, 30 in all: Haiku 4.5, Opus 5.5
  and Fable 5.2 as moles on seeds 101 to 110. Paired tests use all 10 seeds.
- One crew (Haiku 4.5, Haiku 5.5, Sonnet 4.5, Sonnet 4.6, Sonnet 5), one effort level (low), pilot 2
  rules. All 30 games carry code stamp `0800d943`, none spoiled, no fallback turns, no blocked calls.
- The 30 games took 3,308 subscription calls (110 a game). The CLI's notional price for them is
  $145.44; nothing was billed.
- The lead reviewed the 7a script line by line against the pre-registration at 25 games and
  reproduced every per-game first-vote and whole-game crew gap with a separate script that shares no
  code with it. At 30 games the script's own check that its whole-game gap equals `bluff_score.py`'s
  passed for every game; the separate script was not rerun. The formula values come from
  `inside_job.probes.formulas`, which has its own tests.
- The benchmark is not scored here. `docs/SCORECARD.md` says a fresh reviewer does that.

## 3. Criterion 7a, measured (30 games)

### 3.1 Per mole model

Measured, `analysis/bluff_mechanism.py` (last five rows: `analysis/bluff_score.py`). Mean per game
[95%], 10 games each. Gaps are on the 0 to 100 suspicion scale.

| | Haiku 4.5 | Opus 5.5 | Fable 5.2 |
|---|---|---|---|
| Crew gap, whole game | +15.8 [+7.8, +24.4] | +17.4 [+8.2, +26.0] | -0.1 [-7.3, +7.2] |
| Crew gap, round 1 | -3.8 [-10.5, +2.5] | -6.9 [-12.0, -2.6] | -7.7 [-11.4, -3.6] |
| Formula gap, whole game | +30.5 [+23.1, +38.1] | +32.0 [+21.7, +42.3] | +20.7 [+13.1, +28.7] |
| Formula gap, round 1 | +11.2 [+5.4, +16.4] | -0.3 [-8.9, +8.6] | +4.6 [-3.7, +12.6] |
| Residual, whole game | -14.8 [-22.0, -9.0] | -14.6 [-23.9, -4.7] | -20.9 [-27.4, -14.3] |
| Residual, round 1 | -15.0 [-24.5, -6.6] | -6.7 [-16.5, +4.1] | -12.3 [-23.2, -1.1] |
| Chance a crew member rates a mole above an innocent, whole game | 60.7% | 59.2% | 48.3% |
| The same, round 1 | 45.4% | 42.8% | 43.4% |
| Rounds with a vote, per game | 2.50 | 2.90 | 2.20 |
| Job 1 blown | 0% | 20% | 30% |
| A mole on job 1 | 20% | 80% | 90% |
| Moles won | 2 of 10 | 2 of 10 | 6 of 10 |
| Crew votes landing on a mole | 51 of 108 (47%) | 66 of 122 (54%) | 34 of 96 (35%; chance is 36%) |
| Vote-outs that hit a mole | 10 of 25 | 13 of 29 | 4 of 22 |
| Mole statements with a self-tagged lie | 22 of 152 (14%) | 99 of 168 (59%) | 123 of 135 (91%) |

The formula is the job-weighted rule (`jobw50`) fed each crew member's own view of the record just
before the vote. The residual is crew gap minus formula gap. It is below zero for every model: the
cheap crew under-use the record whoever the moles are.

### 3.2 Paired by seed, Fable 5.2 minus each (10 seeds)

Measured, same script. Mean [95% over seeds], seeds below zero, sign-flip p.

| | minus Haiku 4.5 | minus Opus 5.5 |
|---|---|---|
| Crew gap, whole game | -15.9 [-27.7, -6.3], 9 of 10, p = 0.004 | -17.5 [-28.2, -7.3], 9 of 10, p = 0.004 |
| **Crew gap, round 1 (P1)** | **-4.0 [-10.6, +2.4], 6 of 10, p = 0.29** | **-0.8 [-5.4, +4.4], 7 of 10, p = 0.78** |
| Formula gap, whole game | -9.8 [-23.4, +2.1], 6 of 10 | -11.3 [-23.6, +1.8], 6 of 10 |
| Formula gap, round 1 | -6.6 [-14.0, -0.9], 7 of 10 | +4.9 [-3.5, +12.7], 3 of 10 |
| Residual, whole game (P2) | -6.1 [-13.9, +1.4], 7 of 10, p = 0.17 | -6.3 [-14.2, +1.9], 7 of 10, p = 0.17 |
| Residual, round 1 (P2) | +2.7 [-5.6, +10.3], 3 of 10, p = 0.55 | -5.6 [-15.4, +5.6], 7 of 10, p = 0.34 |
| Rank version, whole game | -12.4 [-20.8, -5.6], 9 of 10 | -10.9 [-20.3, -2.8], 6 of 10 |
| Rank version, round 1 | -2.0 [-9.2, +5.9], 5 of 10 | +0.6 [-5.5, +7.6], 5 of 10 |

Differences by seed (101 to 110), from the script's JSON output:

- Round 1 against Haiku 4.5: `+7.8 -22.4 +10.0 -7.2 -17.2 +4.5 -3.1 -8.4 +6.4 -9.9`
- Round 1 against Opus 5.5: `-2.0 -9.4 -3.9 -10.1 -1.1 +9.1 -8.9 +15.7 +5.2 -2.5`
- Whole game against Haiku 4.5: `-1.7 -5.4 -11.8 -59.0 -20.0 -31.9 -21.8 -6.0 -2.3 +1.0`
- Whole game against Opus 5.5: `-13.6 -4.0 -41.5 -39.8 -2.7 -4.5 -41.3 -26.7 -2.8 +1.5`

### 3.3 By round

Measured. Games with a crew vote that round, readings, then crew gap / formula gap / residual.

| | Round 1 | Round 2 | Round 3 |
|---|---|---|---|
| Haiku 4.5 | 10 games, 50: -3.8 / +11.2 / -15.0 | 10 games, 40: +27.0 / +44.2 / -17.2 | 5 games, 18: +64.3 / +76.3 / -12.0 |
| Opus 5.5 | 10 games, 50: -6.9 / -0.3 / -6.7 | 10 games, 40: +27.9 / +51.9 / -23.9 | 9 games, 32: +52.0 / +69.0 / -17.0 |
| Fable 5.2 | 10 games, 50: -7.7 / +4.6 / -12.3 | 8 games, 32: +5.7 / +33.9 / -28.2 | 4 games, 14: +43.5 / +69.8 / -26.3 |

Round 2 is where Fable 5.2 differs: the record points at its moles (formula gap 34 against 44 and
52) and the crew barely move (+5.7 against +27.0 and +27.9). Two of Fable 5.2's ten games ended
before a second vote. By round 3, in the four games that got there, the crew had caught up (+43.5).

### 3.4 Matching (P3)

Measured. Game-rounds grouped by round, clean jobs, blown jobs and whether a mole was on that
round's job, counted at the vote.

| | Weighted difference in crew gap | Fable 5.2 game-rounds matched |
|---|---|---|
| Fable 5.2 minus Haiku 4.5 | -21.0 [-38.8, +1.8] | 18 of 22 (82%) |
| Fable 5.2 minus Opus 5.5 | -14.1 [-26.7, -1.6] | 21 of 22 (95%) |

Largest shared group, "round 2, one clean, one blown, a mole on the job": Haiku 4.5 2 game-rounds at
+61.1, Opus 5.5 5 at +41.6, Fable 5.2 6 at +1.6.

### 3.5 Marks under `docs/PREREG_7A.md` (final for this set)

| Test | Mark at 30 games | Why |
|---|---|---|
| P1, first vote | **No mark**, treated as **fails** (section 4) | Both differences below zero, both intervals include zero, 6 of 10 seeds against Haiku 4.5 (the rule for "direction only" needs 70%; "fails" needs fewer than half) |
| P2, residual | **Fails** (whole game direction only, round 1 fails) | Round 1 against Haiku 4.5: mean +2.7, 3 of 10 seeds below zero |
| P3, matching | **Direction only** | Both below zero; the interval against Haiku 4.5 includes zero |

The marks are the same as at 25 games. The caution written then about the whole-game residual
sitting on zero no longer applies: at 30 games both intervals clearly include zero.

### 3.6 What limits the reading

- **The formula reads the cards on the table, and Fable 5.2 forges cards.** Measured in
  `docs/EXPLORE.md` (`analysis/explore.py`, on 21 Bluff games, 7 per mole model, not recounted at
  30): Fable 5.2 moles tabled clue cards they were never dealt on 45 of 112 whisper and discussion
  turns, Opus 5.5 on 19 of 138, Haiku 4.5 on 2 of 124. A forged card lowers the formula's suspicion
  as well as the crew's. So the residual cannot tell "planted false evidence" from "left less
  evidence", and a low formula gap for Fable 5.2 is partly its own doing.
- **Ten paired seeds.** Every interval here is wide.
- **The last three seeds went the crew's way for every model.** Nine crew wins of nine on seeds 108
  to 110. Whether that is the deals or chance, 10 seeds cannot say.
- **Eight pre-registered tests, uncorrected.** The pre-registration says six; with two comparisons
  and four questions (first vote, residual whole, residual round 1, matching) it is eight. The
  whole-game crew gap is the original finding, not one of the eight.
- **Null test (added 2026-11-11 17:11; measured, `analysis/null_test.py`).** Haiku 5.5 played twice
  as both moles on seeds 101–110: no difference found by the marks of `docs/ANALYSIS.md` N1 (run 1
  minus run 2 = −3.8 points [−16.9, +9.5], mole wins 4 and 4). The paired differences have SD 22.6
  points, so 10 seeds can show a difference between two models of about 16.1 points or more.
- **One crew, one effort level, one rule set.** Nothing here says the order holds elsewhere.
- **Thinking cap not held.** The 2,000-token cap is requested, not enforced (`docs/EXPLORE.md`:
  Haiku 4.5 went over on 322 of 1,817 turns). Crew seats are the same models in every group, so it
  does not favour one mole model, but it is not the stated condition.

## 4. Gaps in the pre-registration and how each is closed

`docs/PREREG_7A.md` is not edited. Its text says "about 12:45"; the file was saved at 12:27:01 on
2026-11-11, before the script first ran (script saved 12:33:36). These rulings were written on
2026-11-11 **after** the 25-game interim numbers were seen and before game 30 ended. Where a choice
existed, the stricter one was taken. The right-hand column was refilled at 30 games.

| Gap | Ruling | Effect at 30 games |
|---|---|---|
| P1 has no mark between "direction only" and "fails" (both below zero, half to 70% of seeds below zero) | For "What follows", no mark is treated as **fails**: the result does not survive the first-vote check | **Applies**: P1 has no mark |
| P2 covers four comparisons with one mark | Holds only if all four hold; fails if any fails. P2 governs wording only | Fails |
| "Six tests" | Eight (see 3.6) | None |
| Jobs "so far" in P3: before or after this round's job | At the vote, as written. The other reading is shown beside it | As written: direction only. Other reading: holds (-19.9 [-34.4, -4.2], -13.9 [-26.0, -1.7]) |
| Whole-game gap: pooled readings or mean of round gaps | Pooled, the same as `bluff_score.py`. Mean of rounds shown beside it | Pooled -15.9 and -17.5; mean of rounds -18.9 and -22.0, 9 of 10 both |
| Rank version: pooled or mean per reading | Pooled within reading | No change of sign either way |
| Paired seeds | Seeds every model has played | 10 seeds |
| Fallback vote turns | Left out, as written. None exist in these games | None |
| "Not informative" in P3 | Judged per comparison; resamples with no shared group dropped and counted (34 against Haiku 4.5, none against Opus 5.5) | None |
| A mark that sits on zero | Read as the weaker mark | Not needed: the whole-game residual intervals clearly include zero (direction only) |

What each 30-game outcome allows, as planned. The outcome is the last row:

| P1 at 30 games | P3 | What may be said |
|---|---|---|
| Holds | Not failing | The full result, at the first vote and over the game |
| Direction only | Not failing | "Measured over the whole game; at the first vote the direction is the same but not established" |
| **No mark, or fails (this is the result)** | Any | The result does not survive the first-vote check. Stated at the top. No Fable Bluff post. Win counts and the round-2 table may still be reported as description, with the mechanism stated as not established |

"The crew were fooled" needs P2 to hold. It does not; the wording stays "left less evidence".

## 5. Checklist: every criterion, 7a to 10c

Costs are planned, from measured rates: 110 calls and 21 minutes per Bluff game (3,308 calls over 30
games), two games at a time, so about 23 minutes per pair. Calls are subscription calls; nothing is
billed. As a guide to the load on the limit, the CLI's own notional price for the 30 games is $145
(Haiku 4.5 moles about $3.14 a game, Opus 5.5 $5.06, Fable 5.2 $6.35).

**Models on the chart (the owner's choice, 2026-11-11: the latest Claude models and the other labs' frontier models).** The plan was reworked the same day around that list:

- Claude: Fable 5.2 and Opus 5.5 (played), Sonnet 5.5 and Haiku 5.5 (not yet played as moles).
- Other labs: Grok 4.7, Kimi K3.1 Pro, Gemini 4 Carbon, GPT-6 Astra. DeepSeek V4 Pro only if fixed.
- Haiku 4.5 keeps its 10 games as a reference row. No more games are planned for it, and none for
  Fable 5.1, Fable 5, Opus 5 or Opus 4.8, which the first draft of this plan used to reach 8 models.
- The crew stays the same five cheap models in every game. Haiku 5.5 is one of them, so in its own
  mole games three of seven seats are Haiku 5.5; that is stated wherever its number is shown.

### Level 7

| | Status | Evidence | Cheapest test | Cost | Pass mark | What withdraws the claim |
|---|---|---|---|---|---|---|
| 7a Mechanism | **Tested: the result does not survive** | Section 3, 30 games | Done 2026-11-11 | 0 | `docs/PREREG_7A.md` with the rulings in section 4 | P1 has no mark at 30 games, so the Fable Bluff result is reported as not surviving the first-vote check. The whole-game difference stands as description |
| 7b Null test | **Not met** | None. Haiku 4.5 against Opus 5.5 (-1.6, 5 of 10 seeds, p = 0.80) is two models, not a null | Haiku 5.5 as moles twice under two batch names, seeds 101 to 110, from the baseline code so the stamp matches. The first run is also its chart entry, so the null costs 10 extra games | 20 games, about 2,160 calls, 3.8 h | Paired difference between the two Haiku 5.5 runs: interval includes zero **and** the mean is within half the Fable 5.2 minus Haiku 4.5 difference at 30 games, that is within 8.0 | A null difference as large as 15.9, or an interval that excludes zero: the measure's noise is not understood and the whole-game Fable difference is withdrawn until it is |
| 7c Docs and chart at current count | **Met 2026-11-11 14:55** (owner's brief for Bench v2, Phase 0) | `docs/CHART.md`, `docs/HEADROOM.md`, `docs/SCORECARD.md` and `docs/charts/bluff_gap.*` carry the 30-game numbers; the chart's title and axis no longer say "best liar" and its footnote says the difference is not established at the first vote | `python3.11 analysis/bluff_chart.py` at 30 games, then the three docs | 0 calls | Every number in the docs and the chart equals the script output at 30 games, game count beside it | Not a claim test. Overwrites `docs/charts/bluff_gap.svg`, `.html`, `.png` and edits three docs |

### Level 8

| | Status | Evidence | Cheapest test | Cost | Pass mark | What withdraws the claim |
|---|---|---|---|---|---|---|
| 8a Three separate groups over 8 models | **Not met** | 3 models, 2 groups (Fable 5.2; Haiku 4.5 with Opus 5.5) | Sonnet 5.5 and Haiku 5.5 as moles, 10 seeds each; the four other labs' models as moles (10a). Eight models: four Claude, four outside | Sonnet 5.5: 10 games, 1,080 calls, 1.9 h. Haiku 5.5: inside 7b. Outside labs: see 10a | Models sorted by mean gap; at least two cuts between neighbours where the paired difference excludes zero after Holm correction over the 7 neighbour tests. Models with fewer than 10 games are shown but not counted towards a group | This cannot be bought with more games of the same models. If no third group appears the claim stays "two groups, not a ranking" and the score for spread stays where it is |
| 8b Halves agree | **Not met** | None | Odd seeds against even seeds on the 8a games; new script | 0 calls after 8a | Same group order in both halves; Spearman 0.7 or more over 8 models | Halves disagree: no order is published, only pairwise results that hold in both halves. On 30 games (3 models) the check is too weak to count |
| 8c Second crew | **Not met** | None | Fable 5.2, Opus 5.5, Sonnet 5.5, Haiku 5.5 as moles against a different five-model crew, seeds 101 to 105 | 20 games, 2,160 calls, 3.8 h | Same order of the four as against the cheap crew; Fable 5.2 lower than Opus 5.5 on at least 4 of 5 seeds, paired mean below zero | Fable 5.2 not lower against the second crew: the result is "against this one cheap crew" and is said so in every post |

### Level 9

| | Status | Evidence | Cheapest test | Cost | Pass mark | What withdraws the claim |
|---|---|---|---|---|---|---|
| 9a Headroom against a harder crew | **Not met** | Against the cheap crew Fable 5.2 moles win 6 of 10 (6 of 7 on seeds 101 to 107, 0 of 3 after): not at the ceiling | Make 8c's second crew the latest models (Haiku 5.5, Sonnet 5, Sonnet 5.5, Opus 5.5, Fable 5.2), so one run answers both and shows whether the latest models can catch each other | Shared with 8c; heavier on the limit per call | Fable 5.2 still lowest; its win rate under 80%; its gap higher than against the cheap crew | Fable 5.2 wins 5 of 5: no headroom shown, a harder tier or v0.4 dials are needed before a long run |
| 9b Listener-panel Bluff probe | **Not met**, not built | Design note in an internal design review (not published) | Build with mock calls. Then: the tested model writes one mole statement in a frozen state, 3 listeners rate before and after: 7 calls a probe, 60 probes | Build 0 calls. 420 calls a model, 35 to 60 minutes. First check on the 4 Claude models 1,680 calls. An outside lab's model needs 60 paid calls (its own statements; listeners stay on the subscription): roughly $0.60 to $3.50 a model, estimated from seat costs, not measured | First check: the four Claude models in the same order as in full games, Fable 5.2 against Opus 5.5 paired by probe with an interval excluding zero. Full: Spearman 0.7 or more against full-game gap over 8 models | Probe order does not match game order: the probe is not published as a stand-in for games. The cheap-to-add claim is dropped, the game result stands |
| 9c Scripted moles of known strength | **Not met** | Bots exist for tests only | Three scripted mole policies, order of strength written down first (`docs/GATES.md` G2) | 20 games, about 1,660 calls, 3.8 h | Gaps land in the written order, neighbours apart by more than the 7b null difference | Order wrong: the gap is not measuring concealment and no Bluff ranking is published |
| 9d Second effort level, renamed roles | **Not met** | None | Fable 5.2, Opus 5.5, Haiku 5.5 as moles, 5 seeds, effort medium; the same with roles renamed (prompts built first, with mocks) | 30 games, 3,240 calls, 5.8 h | Same order of the three in each condition; Fable 5.2 lower on at least 4 of 5 seeds | Order flips with effort or with names: the result is tied to this prompt and said so; no general claim |
| 9e Analysis plan frozen and hashed | **Partly** | `docs/PREREG_7A.md` covers 7a only | Write `docs/ANALYSIS.md`: measures, tests, corrections, stopping rule, predictions; record its hash before the long run | 0 calls | File hash recorded in a commit before the first long-run game | Not a claim test. Without it, long-run results are labelled exploratory |
| 9f Public release | **Not met** | Logs, raw logs and scoring code exist locally; nothing is committed | Repo with logs, scoring code, one command that reprints every table, a page of what is not claimed (`docs/CLAIMS.md` has the list) | 0 calls. Owner decides repo, licence, which logs. Logs checked for secrets first | A fresh clone reprints every published number with one command | Not a claim test |

### Level 10

| | Status | Evidence | Cheapest test | Cost | Pass mark | What withdraws the claim |
|---|---|---|---|---|---|---|
| 10a Other labs on the same measure | **Not met** | 4 mixed-lab frontier games: a sample, not a measure. DeepSeek V4 Pro is **not fixed** (below) | Each lab's model as both moles against the same crew, seeds 101 to 105 | Paid, measured per seat: Grok 4.7 $0.30 a game, Kimi K3.1 Pro $0.41, Gemini 4 Carbon $0.52, GPT-6 Astra $1.74. 5 games each of the first three: about $6.20. Astra 5 games about $8.70 more. Plus about 77 subscription calls a game for the crew. Seat costs varied two to three times between games | Each model's gap with its interval on the same chart, game count shown; no order claimed under 10 games each | A lab's model returns no answer on more than 5% of calls: it is left off the chart, not scored with fallbacks |
| 10b Outsider rerun | **Not met** | None | After 9f: someone else plays 3 mole models on 5 seeds on their own subscription | About 1,620 calls of theirs | Same order of the three; Fable 5.2 lower on at least 4 of 5 seeds | Outsider gets a different order: the result is reported as not reproduced |
| 10c Private half | **Not met** | None | Hold back half the seeds, and half the probe states once 9b exists; publish hashes only | 0 calls to design | Public and private halves give the same order within their intervals | Scores on the public half drift above the private half: leakage is reported and the public half is retired |

**DeepSeek V4 Pro, measured.** One real test call of the higher output limit
was made: the first failed DeepSeek call of `g-20261110-230705-s204`, replayed at a limit of
8,000 tokens. No answer; all 8,000 tokens went to reasoning; 274 seconds; $0.025. One call is one
call, not a rate, but it shows the higher limit alone does not fix it. The setting not yet tried is
reasoning off for this model only (`docs/OPENROUTER.md`). Until that works DeepSeek is not seated as a mole.

## 6. One plan, cheapest first (planned)

"Sub calls" are subscription calls.

| # | Step | Criterion | Sub calls | Running total | Wall time | Needs |
|---|---|---|---|---|---|---|
| 1 | Finish the 30 games; rerun both scripts; replace sections 1 to 3 | 7a | already approved | 0 | **done 2026-11-11 14:30** | nothing |
| 2 | Regenerate the chart and bring three docs to 30 games | 7c | 0 | 0 | **done 2026-11-11 14:55** | nothing |
| 3 | Write and hash `docs/ANALYSIS.md` | 9e | 0 | 0 | **done 2026-11-11 14:55**, hash in `docs/ANALYSIS.sha256` | nothing |
| 4 | Build with mock calls: listener-panel probe, renamed-role prompts, three scripted mole policies, split-half script | 9b, 9d, 9c, 8b | 0 | 0 | subagent work | nothing |
| 5 | Design the private half | 10c | 0 | 0 | — | nothing |
| 6 | Sonnet 5.5 and Haiku 5.5 as moles, seeds 101 to 110 | 8a | 2,160 | 2,160 | 3.8 h | **approved and started 2026-11-11 14:18** |
| 7 | Show game: GPT-6 Astra and Grok 4.7 as the two moles at the frontier table, seed 205 | none (a show, ranks nobody) | about 60 | 2,220 | 0.5 h | **approved and started 2026-11-11 14:18**; paid seats about $1.50, cap $3.50 |
| 8 | Other labs as moles, 5 seeds each: Grok 4.7, Kimi K3.1 Pro, Gemini 4 Carbon | 10a, 8a | 1,160 | 3,380 | 3 h | **approved**; paid key about $6.15; one batch at a time, spend checked between |
| 9 | GPT-6 Astra as moles, 5 seeds | 10a, 8a | 390 | 3,770 | 1.5 h | about $8.70; not run |
| 10 | Null test: Haiku 5.5 as moles a second time, seeds 101 to 110 | 7b | 1,080 | 4,850 | 1.9 h | owner's yes |
| 11 | Probe, first check on the 4 Claude models | 9b | 1,680 | 6,530 | 3 h | owner's yes; step 4 |
| 12 | Latest-model second crew, 4 mole models, 5 seeds | 8c, 9a | 2,160 | 8,690 | 3.8 h | owner's yes |
| 13 | Scripted moles | 9c | 1,660 | 10,350 | 3.8 h | owner's yes; step 4 |
| 14 | Second effort level and renamed roles | 9d | 3,240 | 13,590 | 5.8 h | owner's yes; step 4 |
| 15 | Public release | 9f | 0 | 13,590 | — | owner's decisions |
| 16 | Outsider rerun | 10b | theirs | 13,590 | — | step 15 and a volunteer |

Steps 6 to 9 were reordered on 2026-11-11 at the owner's direction: the latest models are played
first and the null test follows. Until step 10 is done, no difference between two models on the
chart has a measured noise floor beside it, and every post says so.

Stop points: step 1 ended with P1 unmarked, so the Fable post is not written; the later steps are
still worth running as a benchmark of the measure. If step 10 fails, stop and find the
noise before anything else.

How the games in steps 6 to 9 are run. Subscription-only games (step 6) run from the saved baseline
code, stamp `0800d943`. Games with an outside lab's model (steps 7 to 9) cannot: the baseline has no
OpenRouter adapter. They run from the live code. Its `engine.py`, `prompts.py`, `schemas.py`,
`llm.py`, `clues.py`, `log.py` and `RULES.md` are byte-identical to the baseline (compared file by
file from the two logs' `code_files`); `config.py` differs and `openrouter.py` is new. Outside labs'
models are sent `reasoning.effort = low`, which they treat differently from each other, so their
thinking is not matched to the Claude seats'. Five games a model is half the Claude count.

## 7. Decisions open at the time of writing

1. **Null test (step 10):** Haiku 5.5 as moles a second time, about 1,080 subscription calls and
   1.9 hours. Recommended as soon as step 6 ends.
2. **Chart and docs (step 2):** decided by the owner's Bench v2 brief (Phase 0) and done
   2026-11-11 14:55.
3. **The first-vote ruling in section 4:** "no mark" counts as "fails". It was made after seeing the
   interim numbers and is the stricter reading. Game 30 has ended and it was applied (section 1).
   The owner can still overrule it; the less strict reading would be "direction only" wording, and
   that would have to be said in any post as a rule changed after the result.
4. **Benchmark games run from the saved baseline code** so every game carries the same stamp
   (`0800d943`). The live code has since gained the OpenRouter and viewer changes. Recommended: yes,
   and say so in the release notes.
5. **Thinking cap:** disclose it as "requested, not enforced", or change the engine before the long
   run. Recommended: disclose now; decide on enforcement in `docs/ANALYSIS.md`.
6. **DeepSeek V4 Pro:** the owner asked on 2026-11-11 whether it can be fixed. A per-model
   reasoning setting (`[openrouter.reasoning_effort_by_model]`) is built in a scratch copy and
   reviewed by the lead: 16 new tests, checked with fake transports only, every other model's request
   unchanged. It is not merged, so the code stamp of the paid mole games does not move. Whether it
   works needs one real call with reasoning switched off for that model, about $0.01 to $0.03:
   owner's yes. If DeepSeek's provider refuses "off", the setting steps down to "low", which is the
   setting that already fails.
7. **The internal clip list (not published):** the game `g-20261110-021122-s1` was served by Haiku 5.5 on 132 of 136 turns
   under top-model labels; the clip list names the wrong models for it. Fix or remove.
8. **The chosen-moles frontier game (GPT-6 Astra and Grok 4.7 as moles):** approved and started
   2026-11-11 (step 7). Sonnet 5.5 sits in the DeepSeek seat. **GPT-6 Astra's own five mole games
   (step 9)** need about $8.70 and were not run.
9. **Release (step 15):** repo, licence, and which logs go public.
