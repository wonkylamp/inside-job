# Inside Job — what the benchmark claims

Draft 3, 2026-11-10. Not frozen: it freezes with a hash when `docs/ANALYSIS.md` is written (gate
G4). Scope: benchmark games only. A benchmark game is a *trial*: one model under test against one
fixed reference model, codenames on, the same deals for every model, each deal played once in the
mole seats and once in the crew seats. No trial has yet been played with real models.

## The skills and their metrics

Each metric is scored per decision, averaged per game, and compared between models on the same
deal, with a paired t interval over deals (whole-deal bootstrap shown beside it; `docs/GATES.md`).

| Skill | Who is scored | One decision | Score |
|---|---|---|---|
| **Read**: working out who the moles are | Test model in the crew seats, reading reference moles | One private suspicion reading | Brier score against the truth: mean over the players rated of (stated chance - 1 if mole, else 0) squared. Lower is better. Shown beside three fixed lines on the same readings: the base rate, the logic solver, the best scripted reasoner. |
| **Bluff**: blowing jobs without drawing the vote | Test model in the mole seats, judged by reference crew | One round with a test mole still in | *Getaway* = (1 if the job was blown, else 0) x (1 - share of crew votes on a mole that round); a blown job that ends the game scores 1. Higher is better. |

How Read is averaged within a game (all readings pooled, or rounds weighted equally) is fixed on
G1's data, which has one model and so no ranking to peek at. Win rate, votes on moles, lies and
fake cards are reported as descriptions and as checks, not as skills. Persuasion by crew is not
claimed: in a crew trial the listeners are copies of the model under test.

## What would prove a claim false

Either claim is withdrawn, not reworded, if gate G1, G2 or G3 fails for it (one model under two
names differs; scripts of known strength finish out of order; two halves disagree on the ranking).

- **Read** is false if a script that always reports the base rate, or one that copies the solver's
  public posterior, scores as well as the median real model; if better Read does not go with more
  crew votes on moles; or if the ranking changes when roles and actions are renamed in the prompts.
- **Bluff** is false if Getaway sits at its floor (mean under 0.10 for every model); if a script
  that always sabotages, never sabotages or never speaks scores as well as the median real model;
  or if, among scripted moles, the Getaway order differs from the win-rate order.

## Where the claims stand on the pilot (20 show games, cheap models; not trial data)

| Claim | Test | Result | Standing |
|---|---|---|---|
| Read | Script copying the public posterior vs the models | Script 0.165, models 0.171; difference +0.006 [-0.016, +0.028] in the script's favour | **Failing.** The cheap models do not read better than a formula. Open only for stronger models. |
| Read | Base-rate script vs the models | Base 0.212 [0.205, 0.219], models 0.171 [0.154, 0.186] | Passing |
| Bluff | Floor | Mean Getaway 0.082 [0.028, 0.138]; three of five models under 0.10 | **Failing at sabotage target 3.** |
| Bluff | Getaway order vs win-rate order, scripts | Target 3: 5 clear reversals in 78 pairs. Target 2: none | **Failing at target 3**, passing at 2 |
| Table read | Beat the constant base rate | Model error 0.038, constant 0.026; no model beats it | **Withdrawn** |

Intervals: whole-game bootstrap, 2,000 resamples. Script results: 1,000 bot games per cell.

## What the benchmark does not claim

- Nothing about a model's tendency to deceive the people it works for. Lying is the assigned task
  in a game every player has been told is a bluffing game.
- No ranking from show games, mixed tables or win rates alone. No comparison with human players.
- Nothing beyond the stated conditions: rules version, prompt wording, the one reference model,
  effort `low`, a 2,000-token thinking cap. Published work on similar games found rankings that
  reversed against another opponent and win rates that moved by tens of points when roles were
  renamed (`docs/SOURCES.md`, A10, A16).
- Nothing about the finale: in a trial both finalists are the same model.
- Nothing about a lone player among strangers: a test model plays beside copies of itself.
- Suspicion numbers are scored as written; no claim that they are the model's "real" belief.

## When entertainment and measurement conflict

Inside a benchmark game, measurement wins: one test model and the reference under codenames, not a
varied named cast; the dial setting with the widest spread between scripts of known strength, not
the closest race; every game counted, none dropped or rerun for being dull; thinking, effort, voice
and word caps identical for every model; the finale played as the owner decided but never ranked;
games from two rule versions never pooled. Show games may use other dials; they are labelled and
appear only under "series stats".

## Changes

- Draft 3: status table added from the full bot search; Bluff's order test fails at target 3.
- Draft 2: **Table read withdrawn** (failed its own test; a formula also beats its baseline without
  reading anyone). **Read no longer subtracts the solver**: the solver is not the best reasoner
  (weighting worlds by job results scores 0.144 against 0.154 on the pilot's 1,322 readings, and
  -0.029 better in bot games); subtracting it added noise (per-game spread 0.055 against 0.043);
  and in bot games a crew that shares less made the difference look better while winning 17 points
  less. **Intervals** are paired t (the percentile bootstrap called false differences 9.4% of the
  time at 10 deals). Read gains the renamed-roles test.
- Draft 1: first version, three skills, written before any analysis.
