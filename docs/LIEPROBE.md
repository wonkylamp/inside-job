# Lie-spotting probe — zero-call check and verdict

2026-11-10. Step 3b of an internal run plan (not published). Everything here is measured from the pilot logs and the
400 probe answers already collected. No model was called. Scripts: `lies/liecheck.py`,
`lies/claimlevel.py`, `lies/tiebreak.py` in a scratch folder (not published).

## Verdict

1. **Do not build the simple lie probe** ("is this statement a lie?"). In these games it is Read
   under another name, and the formula does it as well as the players.
2. **Do not build the claim-level probe** ("which claim in this statement is false?") from the
   current logs. There are 75 usable statements, and a rule with no model already scores 0.66.
3. **One measure does look formula-proof: the tie-break score.** Take a mole and a crew player the
   formulas rate the same, and ask whether the reader rates the mole higher. The formula scores
   0.50 by construction. Top models score 0.58 to 0.66 on the 54 such pairs in the frozen set;
   the cheap players who made the original readings score 0.51 on the same pairs. This is a hint
   on a small sample, not a result.
   **Update, same day: the confirmation run did not pass, and a no-model rule on the voting record
   matches the model. See "Confirmation result" below.**

## 1. Why "is this a lie?" is Read in disguise

39 finished games, self-tagged claims.

| | Claims | False | Share |
|---|---|---|---|
| Moles | 1,184 | 272 | 23% |
| Crew | 4,174 | 38 | 0.9% |

Almost only moles lie. So a statement that holds a lie is, nearly always, a statement by a mole,
and spotting it is the same job as spotting the mole.

Area under the curve for "this discussion statement holds a tagged lie", scored by how suspicious
the crew listeners were of the speaker afterwards (0.5 = coin, 1.0 = perfect):

| Statements | Listeners (cheap models) | Job-weighted formula | Listeners minus formula |
|---|---|---|---|
| All (1,206) | 0.840 [0.802, 0.878] | 0.848 [0.796, 0.891] | 0.413 [0.323, 0.520] |
| Moles' only (332, 106 with a lie) | 0.657 [0.594, 0.715] | 0.663 [0.591, 0.718] | 0.464 [0.391, 0.544] |

The formula is as good a lie detector as the listeners. What the listeners add on top of the
formula carries no signal (0.41 and 0.46 are at or below a coin). Listeners' suspicion of a mole
rose by the same amount whether the statement held a lie (+0.042) or not (+0.050).

One thing does point the right way. When crew call out a statement, 48% of call-outs land on a
mole (moles make 28% of statements), and among call-outs on moles 57% land on a statement that
holds a lie (32% of moles' statements do). That is behaviour worth a clip finder. It is not yet a
score, because the formula was not asked to call out.

## 2. Why the claim-level probe is too thin

Public statements with claims, discussion and vote, 40 games: crew 1,178 (14 with any false
claim); moles 441, of which 299 all true, 67 all false, **75 mixed**. Only the 75 mixed ones can
ask "which claim is false" with the speaker held fixed. They hold 110 false-against-true pairs.

A rule that looks only at the kind of claim ("I helped" and claims about oneself are false more
often than clue content) picks the false claim in 0.664 [0.569, 0.765] of pairs, with no model and
no reading of the table. The truth label is also the speaker's own tag, not the engine's: the
engine-checked lies agree with the tags in most cases (4 job lies and 1 false card went untagged),
but for claims the engine cannot check there is no second source.

## 3. The tie-break score

Definition, fixed before any further run: within one probe, every pair of one mole and one crew
player whose chance of being a mole differs by at most 0.02 under all three formulas (simple,
job-weighted 0.5, job-weighted 0.8). Score 1 if the reader's suspicion of the mole is higher, 0.5
if equal, 0 if lower. Intervals by whole-game bootstrap.

On the frozen 100 probes (41 of them hold a tied pair; 54 pairs):

| Reader | Tied pairs | All mole-crew pairs (599) |
|---|---|---|
| Formula | 0.500 by construction | 0.821 [0.778, 0.864] |
| Original cheap players | 0.509 [0.364, 0.680] | 0.756 [0.698, 0.810] |
| Fable 5.2, high | 0.583 [0.442, 0.729] | 0.808 [0.764, 0.852] |
| Fable 5.2, low | 0.611 [0.465, 0.760] | 0.794 [0.748, 0.839] |
| Opus 5.5, high | 0.593 [0.451, 0.730] | 0.801 [0.754, 0.845] |
| Opus 5.5, low | 0.657 [0.536, 0.779] | 0.795 [0.751, 0.838] |

Paired on the same pairs, top model minus original player: +0.07 to +0.15; two of the four
intervals exclude zero (Fable low +0.102 [+0.000, +0.214], Opus low +0.148 [+0.024, +0.273]).
High effort is not better than low here; for Opus it is lower (-0.065 [-0.128, -0.011]).

Whole pool, every crew vote reading in pilots 1 and 2 by the cheap players (202 pairs in 159
readings): 0.552 [0.451, 0.668]. By round: round 1 0.481 [0.360, 0.614] (130 pairs), round 2
0.768 [0.561, 0.913] (56 pairs), round 3 0.375 (16 pairs). Round 1 has nothing to read, as
expected; the signal, if real, starts once there is a round of talk behind the vote.

**What this does and does not show.** It is the first measure on which the formula cannot tie the
models and on which top models sit above cheap ones. It is also four correlated runs on 54 pairs,
looked at after the main check failed; one interval of four clears 0.5. It has to be confirmed on
pairs not yet seen before it is called a finding.

## What it would take

- **Confirmation, about 120 calls.** The pool holds 159 readings with a tied pair; 41 are already
  answered. Running the other 118 on one top model at low effort gives 202 pairs. The paired
  interval against the cheap players shrinks from about ±0.12 to about ±0.06, enough to settle a
  true gap of 0.10. Pass: top model above 0.5 and above the cheap players, both intervals clear.
- **If it passes**, the benchmark's headline becomes "who reads the liar when the logic runs out",
  with the formula as a fixed 0.50 line. The pool then has to grow: about 5 tied pairs per game,
  so a 15-model ranking at ±0.05 needs roughly 1,000 pairs, or states from about 200 games. Games
  played for the show and for mole headroom feed this pool at no extra cost, and round-2-and-later
  states can be favoured since round 1 carries nothing.
- **If it fails**, Read in any form is dropped as a headline and the benchmark stands on Bluff
  (how well a model's moles survive a fixed panel of listeners), which needs the headroom test.

## Confirmation run — rule written before the run (2026-11-10)

Set `probes/sets/tie_v1.jsonl`, sha256 `88e9b9e9...acad`: the 118 crew vote readings in pilots 1
and 2 (40 games) that hold a tied pair and are not in `read_v1`. 148 pairs (round 1: 95, round 2:
42, round 3: 11), 32 games. Run: `claude-fable-5-2`, effort low, thinking cap 2,000, one call each.

- **Primary.** Fable 5.2 low on all 202 pairs (54 from `read_v1` + 148 new), whole-game bootstrap.
  Pass = the interval is above 0.50 **and** the paired difference from the original cheap players
  on the same pairs is above 0.
- **Reported beside it.** The 148 new pairs alone; rounds 2 and later alone; round 1 alone.
- **Known weakness, stated now.** This is more readers of the same games, not new games: 106 of
  the 118 readings are another crew seat at a table state `read_v1` already used. The game
  bootstrap accounts for that in the interval, but only new games can give an independent
  replication. Those come from the mole-headroom games.

## Confirmation result (measured 2026-11-10): not passed

118 calls, none failed, every call served by `claude-fable-5-2`. Output 90,322 tokens (thinking
20,621), cache creation 929,083; wall 10 minutes. Scripts `lies/score_tie.py`, `lies/rules_tie.py` (scratch folder, not published).

| Pairs | Count (games) | Fable 5.2 low | Original cheap players | Fable minus cheap |
|---|---|---|---|---|
| **Primary: all** | 202 (34) | 0.604 [0.500, 0.718] | 0.552 [0.451, 0.668] | +0.052 [-0.009, +0.117] |
| New only | 148 (32) | 0.601 [0.486, 0.712] | 0.568 [0.464, 0.678] | +0.034 [-0.030, +0.110] |
| Round 1 | 130 (28) | 0.508 [0.381, 0.647] | 0.481 [0.360, 0.614] | +0.027 [-0.038, +0.107] |
| Rounds 2+ | 72 (19) | 0.778 [0.603, 0.921] | 0.681 [0.485, 0.867] | +0.097 [+0.000, +0.211] |

**By the rule written before the run this fails.** The difference from the cheap players includes
zero, and the lower bound against 0.50 sits on 0.500.

**And the score is not formula-proof after all.** All of the signal is in rounds 2 and later, and
there a rule with no model does about as well. The rule uses only the public voting record, which
the three formulas ignore: a player who helped vote out a crew member is more suspect, one who
helped vote out a mole is less.

| Rounds 2+, 72 pairs | Score | Fable minus this |
|---|---|---|
| Fable 5.2 low | 0.778 [0.603, 0.921] | |
| Vote-record rule (no model) | 0.722 [0.585, 0.855] | +0.056 [-0.164, +0.246] |
| Accused by others this round (no model) | 0.674 [0.463, 0.877] | +0.104 [-0.006, +0.224] |
| Original cheap players | 0.681 [0.485, 0.867] | +0.097 [+0.000, +0.211] |

So the ties were ties only because the formulas leave out the votes. Add the votes and Fable 5.2
is again level with arithmetic.

**Conclusion.** Mole-reading in every form tried (Brier, lie-spotting, claim-level, tie-break) is
matched by arithmetic on the public record. Under these rules the game hands the table enough hard
evidence (clue cards, job results, the role shown at every vote-out) that reading the talk adds
nothing measurable. Read is dropped as a headline. The independent replication on new games is not
needed. What is left to test is the other side: how well a model's moles deceive (Bluff), and
whether the rules should hide more so that the truth has to be read from the talk.

## Limits

- Tags are self-reported by the speaking model.
- All states come from Haiku- and Sonnet-level games.
- The 0.02 tolerance and the three-formula rule were set before the numbers were seen, but the
  measure was chosen after the Brier check failed. Only unseen pairs can confirm it.
