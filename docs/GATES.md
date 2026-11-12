# Inside Job — gates G0 to G4: design, pass marks, cost

Status: draft 1, 2026-11-10. Written before any gate was run and before any trial had been
played with real models. Nothing here has been approved; no gate starts until its cost is approved.
Sources for every number: `analysis/out/decision_summary_pilot1.md`,
`analysis/out/variance_power.md`, `analysis/out/best_response.md`, `docs/SOURCES.md`.

## What a game costs (pilot 1, 20 show games, measured)

| Per game | Mean | Range |
|---|---|---|
| Calls (every attempt, narrator included) | 112 | 83 to 148 |
| of which the five crew seats / the two mole seats / narrator | 80 / 30 / 3 | |
| Game time | 21 min | 14 to 35 |
| Tokens: input / cache write / cache read / output (thinking inside output) | 427k / 665k / 109k / 153k (86k) | |
| List-price equivalent, cheap cast | $3.46 | $2.42 to $5.41 |

List price per call, from the logs: Haiku 4.5 $0.023 (20 s), Sonnet 4.6 $0.042 (11 s), Sonnet 5
$0.039 (14 s), Sonnet 4.5 $0.054 (30 s), Opus 5.5 $0.071, Opus 5 $0.083, Fable 5 and 5.1 $0.19.
The Haiku 5.5 figure in the logs ($0.0025) looks too low to trust. Subscription calls are not
billed per token; "dollars" below is the CLI's list-price estimate, given because it was asked for.

One **deal** for one test model is two games (once in the mole seats, once in the crew seats):
about 225 calls (110 by the test model, 110 by the reference, 5 by the narrator) and 42 minutes of
game time. Wall time is game time divided by the number of games run side by side (2 in the pilots).

All costs assume the reference model is **Sonnet 4.6** (proposed: fastest of the cheap cast, no
trimmed turns, no failed calls in pilot 1, mid price). With Haiku 4.5 as the reference, dollars
fall by about 45% and game time rises by about 80%.

## Rules that hold for every gate

- **Seeds.** Used so far with real models: 1 to 20, and 7. Real-model gates take seeds in order
  from a ledger (`docs/SEEDS.md`, to be created): G1 5001-5020, G2 5101-5120, G3 5201 onward, the
  large run 6001 onward. No seed is chosen by looking at its deal. Bot runs use 100000 upward.
- **Intervals.** Per-deal scores, compared between models on the same deal. The interval is a
  paired t interval over deals. Reason: simulated on the pilot's own distribution, the percentile
  bootstrap over deals calls a false difference 16.8%, 9.4%, 7.5% and 6.2% of the time at 5, 10, 20
  and 40 deals; the paired t stays at 4.8% to 5.6%. The whole-deal bootstrap is reported beside it.
- **Every game counts.** A game is void only if more than 10% of its turns fell back or a model was
  blocked; void games are replayed on the same seed and both logs are kept and listed. Fallback and
  retry rates are reported per model beside every score (a token cap that silently empties answers
  is a known way to fake a skill gap: `docs/SOURCES.md`, C1).
- **Stop rule.** A failed gate stops the sequence. The failure and what it means for the design
  are reported before anything else runs.

## G0. The rules must leave both sides something to measure (before G1)

Not one of the four named gates, but they are pointless without it. Pilot 1 (target 3): crew won
19 of 20; mean Getaway 0.082 [0.028, 0.138] (whole-game bootstrap, 99 mole-rounds, 20 games), 84%
of mole-rounds scored 0, and no mole sabotaged in round 1 (0 of 8).

Pass marks, on at least 20 real games of one rule set (cheap cast):
1. Crew win between 6 and 14 of 20 (30% to 70%).
2. Mean Getaway at least 0.15, and at least one blown job in 16 of 20 games.
3. Fewer than half of round-1 mole eliminations follow a public mole-to-mole whisper. (Pilot 1:
   8 of 8 did; with no such whisper, 0 of 5 round-1 votes removed a mole.)

Candidates, cheapest first: `sabotage_target = 2` (pilot 2, already running, no new cost; judged on
marks 1 to 3 when it ends); `whispers = false` (an existing dial; removes the tell and about a
quarter of the calls); the v0.4 dials another session is building (new features: each must show it
changes decisions before it stays). A further 20-game test of one more setting costs about 2,250
calls, 7 hours of game time, $70.

What the bot search says about the dials (1,000 bot games per cell; bots are not models): at
target 3 the three crew skill levels are 50.5 points of win rate apart but scripted moles win only
7% to 17%; at target 2 scripted moles spread from 13% to 63% and Getaway from 0.04 to 0.50, but the
crew skill spread halves to 24.7 points. The two sides want different settings. Because mole trials
and crew trials are separate games, the benchmark may use target 2 for mole trials and target 3 for
crew trials; that is a choice for the owner, and it would be fixed before G1.

If no setting of the existing dials passes, that is the point at which switching the base game is
on the table.

## Work before G1 that costs no calls (apply after pilot 2 ends)

1. **Keep the raw material.** Per game, a second file `<game_id>.raw.jsonl.gz` beside the log: for
   every attempt of every call, the system prompt (once per player, then by hash), the full turn
   prompt including any retry suffix, the schema, the CLI's raw stdout, stderr tail and exit code,
   and per-attempt usage and latency. This keeps rejected and cut-off replies and the text before
   word-cap trimming, none of which the log keeps now. About 5 MB per game before compression.
   Touches `llm.py` (carry stdout on the reply) and `engine.py` (`ask` writes each attempt).
2. **Stamp the code.** `game_start` records a SHA-256 over the rules, prompt, schema, engine, clue
   and config files. Today nothing in a log says which code played it, so a rebuilt pilot prompt
   cannot be checked against what was sent.
3. **A seat router** so scripted players can sit at a table with real models (needed for G2). A
   wrapper client outside the game logic; model ids starting `script:` go to the bots.
4. **Free half of G1:** a test that the prompts for one seed are byte-identical when the same model
   is entered under two names.

## G1. Null test: one model under two names

**Design.** The reference model in all seven seats. Twenty deals, each played twice (entry "A" and
entry "B"): 40 games. With one model in every seat each game yields both Read and Getaway.

**Pass marks** (stated before the run):
1. For Read and for Getaway, the 97.5% paired t interval of A minus B contains 0 (two metrics,
   so 5% overall).
2. The interval is narrow enough to mean something: half-width at most 0.040 for Read. Expected
   from the pilot: about 0.033 if replays of a deal are unrelated, less if they are related. If it
   is wider, the gate is "not settled" and is extended once by 10 deals; it is not a pass.
3. Shuffling the A/B labels within deals 2,000 times, the observed difference is not in the outer
   5%.
4. The reference model is usable: crew win 12 to 28 of the 40 games and mean Getaway at least 0.15.

**What else the same 40 games give, at no extra cost:**
- The share of between-game variance that belongs to the deal (20 same-rule replays; pilot 1 has
  none). This sets the size of G3. With the 6 pilot1-pilot2 pairs so far it cannot be estimated
  (Read r = 0.51, interval -0.62 to 0.98, and the replay changes a rule).
- Test-retest of suspicion readings: the round-1 clue turn is the identical prompt in A and B
  (140 pairs). Prior work found repeated readings on a saved state disagreeing in 47% of pairs.
- The variance of a single-model table, which the show games cannot give.
- The exact averaging rule for Read (see `docs/CLAIMS.md`): chosen here by smallest paired
  spread, on data from one model, where there is no ranking to peek at.

**Cost.** 40 games: about 4,500 calls (3,300 to 5,900), 9.7 hours of game time (about 5 hours wall
at two games side by side), $190.

**If it fails.** Mark 1 or 3: the interval method or the pipeline is wrong, or the served model
drifts between runs; nothing downstream can be trusted until found. Mark 4: the reference or the
rules are wrong; back to G0.

## G2. Known skill: scripts of known strength at real tables

**Crew side (Read).** Five scripted crew (the logic player) against two real reference moles, 10
deals. Every reporting script is scored on the same 10 games, because what a script writes in its
private suspicion changes no play: the exact reasoner, the same shrunk halfway to the base rate,
the base rate, and a copy of the public posterior.
- Pass: mean Read in the order reasoner, shrunk, base rate (best to worst), each neighbouring pair
  separated by a 95% paired t interval. From the pilot's own readings these gaps are 0.017 and
  0.042 and need about 5 deals each for 80% power.
- "The ideal reasoner tops the read score" is tested here among scripts and again in G3 against
  models. The bots already show it is not the best reasoner (see CLAIMS, change 2), so this mark is
  judged on the corrected reasoner.
- Cost: 10 games, about 330 calls, 1 hour of game time, $14.

**Mole side (Bluff).** Two scripted moles against five real reference crew, 10 deals per script:
`never` (never sabotages), and `smart` (sabotages when on a job, one fake card a round).
- Pass: `never` scores Getaway 0 in every game and wins none; `smart` has mean Getaway above 0 with
  a 95% interval that excludes 0, and wins at least as often as `never`.
- At 10 deals a difference in Getaway under about 0.14 cannot be seen, so this is a coarse check
  that the scale has a bottom and something above it, not a fine ladder.
- Cost: 20 games, about 1,660 calls, 4.8 hours of game time, $70.

**Total G2:** 30 games, about 2,000 calls, 6 hours of game time (3 hours wall), $85.

**If it fails.** Crew side: Read does not order players of known strength; the metric is replaced
or the claim withdrawn. Mole side with `smart` at 0: real crews catch even a competent script every
time, the Bluff scale has no room, and the rules go back to G0.

## G4. Pre-registration (before G3; costs no calls)

`docs/ANALYSIS.md` holds: the two metric definitions as code references; the models and the
reference; the seed list; the interval method; the exclusion rule; every comparison that will be
reported; and written predictions with numbers. It ends with a SHA-256 over itself, `RULES.md`,
`docs/CLAIMS.md`, the prompt, schema, engine and clue modules and the bench config.

Pass marks: the hash is recorded in the file, in the shared notes and in a message to the owner
before the first G3 game (a commit or tag if the owner allows one); every G3 game's stamped hash
equals it; every seed is unused in the ledger; the predictions file is older than the first game.
A check script prints pass or fail per game.

## G3. Repeatability: two halves, different seeds, same ranking

**Design.** Three entries: the reference model against itself, plus two test models. Forty deals in
two halves of 20, fixed in advance by seed. Each test model plays each deal twice (mole seats, crew
seats). The reference entry reuses G1's "A" games for half one and plays 20 more.

**Pass marks**, for each metric:
1. The order of the three entries is the same in both halves.
2. No pair has a difference that is separated from 0 in the full 40 deals and of opposite sign in
   one half.
3. At least one pair is separated in the full 40 deals. Without this, mark 1 can pass by luck one
   time in six, and "no model can be told from another" is a fail for usefulness.

**What to expect, honestly.** From the pilot, with replays of a deal unrelated and trial noise equal
to show-game noise: three models 0.029 apart in Read (half the distance between the base rate and
the solver) give the same ranking in both halves 92% of the time at 60 deals; at 40 deals less. The
five cheap models in pilot 1 spanned 0.032 in Read in total and could not be told apart
(permutation p = 0.82). So G3 is likely to fail on mark 3 unless the two test models are far apart.
Choosing them far apart (for example Haiku 4.5 and one top model) is the right test of the
instrument. G1's replay data will resize this gate before it is costed finally.

**Cost at 40 deals, two test models:** 180 games, about 20,200 calls, about 55 hours of game time
(27 hours wall at two side by side). List price: reference side $465; Haiku 4.5 as a test model
$100; Sonnet 5 $170; Opus 5.5 $310; Fable 5.1 $835. With Haiku 4.5 and Opus 5.5: about $880.

**If it fails.** The ranking is not a property of the models at this size. Either the size goes up
(the power table says by how much), or the claim is dropped for that metric.

## A cheaper route for Read, not adopted without the owner's say

The independent review proposes replaying logged game states to each model as single calls. For
Read this is the same-deal pairing taken to its limit: every model reads the identical state, so
deal and table variance cancel. Rough size: 200 states per model give about plus or minus 0.015 on
Read for 200 calls, against about 60 deals (13,500 calls) by full trials. G1 and G3 for Read would
then cost hundreds of calls, not thousands.

What it costs: a runner (about a day), and it is new apparatus, so by the owner's rule something
goes: crew trials (Read would no longer need them). What is not known: a replayed state carries the
original player's memory note and earlier statements, so the reader inherits another model's
notes; and the score describes reading, not playing. It would need its own check that replayed
Read and in-game Read rank models the same way. Bluff cannot be measured this way without a panel
of listeners and still needs mole trials.

## Order and totals

| Step | Games | Calls | Game time | List price | Needs approval |
|---|---|---|---|---|---|
| G0 (pilot 2) | 20 | running | running | running | already given |
| No-call work | 0 | 0 | 0 | 0 | no |
| G1 | 40 | 4,500 | 9.7 h | $190 | yes |
| G2 | 30 | 2,000 | 6 h | $85 | yes |
| G4 | 0 | 0 | 0 | 0 | no |
| G3 | 180 | 20,200 | 55 h | about $880 | yes, after G1 resizes it |

G5 to G7 (outside readers, audience, reproduction) are not designed here.
