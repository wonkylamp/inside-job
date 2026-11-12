# Inside Job — Detect (Bench v2, Phase 6): design, build and the two zero-call checks

Written 2026-11-11 by the session that built Phase 6. No model was called for anything in this
file. Each statement is **measured** (a number from a run, script named), **built** (code and
tests exist) or **planned** (not built or not run).

## Result first

**Both checks that had to pass before any model run failed. Detect is not ready to be run on
models.**

- **D1 (scripted tuning): not met.** Walking the grid from most clues to fewest, the first
  setting whose formula error lands in the band 0.09 to 0.13 is **G1: every player gets a clue
  every round, roles hidden**: error 0.100 (200 games, 95% interval 0.088 to 0.112). That is
  *more* clues than today, not fewer. And there the formula's two highest-rated players are the
  two moles in **51.2%** of cases (interval 45.1% to 57.6%); the mark for "no longer solves it"
  is under 40%. Under today's rules, same seeds, the figure is 41.4% (35.7% to 47.6%). No
  setting on the grid meets both halves of D1: the nine settings with fewer clues are under 40%
  (35.0% down to 10.0%) but their error is above the band (0.140 up to 0.220). (measured)
- **D2 (does the talk carry signal): fail.** The no-model reader beat the masked formula by
  **0.0058** (830 vote turns in 75 finished games; 95% interval −0.0005 to +0.0114). The mark
  is at least 0.01 with an interval that excludes zero. Neither holds. By the rule written first,
  Detect is not run on models and the talk signal was not shown. (measured)

What was learned on the way, which a new design can use (section 7): in round 1 the talk does
help (gain 0.015, interval 0.006 to 0.023); from round 2 on it does not; and on the 75 finished
games hiding the roles barely weakens the formula at the last vote (error 0.088 with roles,
0.097 without).

The marks (`docs/ANALYSIS.md`) and everything fixed before the numbers (`docs/DETECT_RULES.md`,
SHA-256 `b6826522ab6fbb8467b088ed9f613d366ecc60a566713297d49d4a7d540de19e`, hashed before the
first tuning run; exact times in section 9) were not changed after the numbers.

## 1. What Detect is meant to be

**Detect** = how much better a model's mole ratings are than a no-model formula's, on rules where
the formula cannot solve the game. Score: the formula's error minus the model's error on the same
vote turns, new-rules games only, with an interval over games (ANALYSIS.md, D3).

The problem it has to get round: under today's rules a formula over the public record (clue
cards and job results) finds the moles about as well as the models do, so there is nothing for a
model to add. The plan was a rules version that hides the role at vote-out and deals fewer clues,
then three steps in order: show with scripted players that the formula no longer solves it (D1),
show without any model that the talk carries signal a reader could use (D2), and only then test
models (D3).

## 2. The rules version: v0.5 "blind" (built)

Two dials in `[game]`, both off by default:

| Dial | Default | What it does |
|---|---|---|
| `hide_roles` | `false` | When a player is voted out, no player is told whether they were a mole or crew, then or later. |
| `clue_round_pct` | `100` | The chance in 100, each round, that any clues go out at all. 100 = every round, as today. Needed to deal fewer than "one or two players a round"; the existing dial `clue_recipients` cannot go below that because 0 there means "everyone". |

**With both dials off nothing changes.** Proof (measured, `tests/test_v05.py`, class `Defaults`):
99 seeded games were played in the untouched copy of the code and in the changed copy (9 with
the mock model, which records every prompt it is sent; 90 with the scripted bots, across
`default.toml`, `pilot2.toml` and `bluff_haiku45.toml`). All **959 prompts** (system prompt,
turn prompt and reply schema), all **15,798 log lines** and the existing formulas' values at all
**1,518 vote turns** are identical, byte for byte. Fields left out of the comparison: `wall_s`
(how long the game took) and, in the one game that asks for a code stamp, `code_hash` and
`code_files` (they differ whenever a source file does, which is their job). Time stamps and
game ids are not left out; the test fixes the clock and the id. The same digest is stored in
`tests/fixtures/v05_defaults/digest.json`, so the test still works once there is no untouched
copy beside the code.

To keep the log lines identical, a v0.5 dial at its default is **not written** into the logged
config. A game with a dial on logs it, and logs `rules_version` "0.5" in place of "0.3".

### What a blind game shows and hides

- The log keeps the truth: `vote_result` still carries `role`, plus the flag `role_hidden`.
  The one gate every player's view passes through (`log.project`) leaves `role` out when the flag
  is set, for players, the narrator and the public projection alike. The scripted bots get their
  view through the same gate.
- The win check uses the truth, as before.
- Prompts: the rules text, the vote instruction, the table ("[out R1, role hidden]"), the vote
  lines ("Their role was not revealed."), the suspicion instruction and the narrator's
  instructions all have blind wording. No model has read these prompts yet; the wording is this
  session's and has not been reviewed.
- Tests (`tests/test_v05.py`, class `HiddenRoles`): no prompt in six mock games contains a
  voted-out role or a count of moles left; swapping every logged role and rebuilding gives the
  same vote prompts and narrator prompts character for character (and the same swap does change
  them under today's rules, so the test can fail); in 75 blind bot games no vote result handed
  to a bot carried a role (more than 1,000 checked).

### What else could leak a role, and what was decided

| Possible leak | Decision |
|---|---|
| **The game goes on after a vote.** The crew win the moment both moles are out, so a game that continues has a mole still in. | Kept; it is part of the game. Players are told so in the rules text, and the formula uses it (a pair of players who have both been voted out cannot be the two moles). Nothing else about voted-out players is used. |
| **The count "Moles still in: 1 of 2"** in the table and in the suspicion instruction. | Removed. Players read "not revealed (at least one, or the game would be over)" and "at least one, at most two". The context handed to the prompt builder carries no count (it is `None`, so a prompt that tried to use it would crash, not leak). |
| **The crew win by voting out the second mole.** The game ending tells everyone the last player out was a mole. | Unavoidable and harmless: the game is over; no rating is taken after it. |
| **The finale and The Cut.** Finalists come from the winning side, so the survivors' sides show. | Left as it is: this is after the game is decided. Voted-out roles stay hidden even there. The Cut's tie-break (record of votes against moles) is still computed by the engine from the truth. |
| **Clues.** A clue is fitted to what its reader already knows; today that includes revealed roles. | In a blind game clues are fitted with no revealed role. Clues are still always true and still mention only players still in. A true clue can of course imply something about who is left; that is legitimate intel. |
| **The fallback rating** (used when a model gives no valid answer) was "moles left / players left". | In a blind game it is 2 moles among 6 others = 33, whatever has happened. |
| **The narrator's recap**, which players read. | The narrator is shown the same role-free record and is told not to state or guess a role. |
| **The v0.4 moles' score** (blown jobs + crew voted out) is public. | The config refuses `hide_roles` together with `mole_score_target`. |
| **The v0.4 Final Accusation** names the accused player's role. | It is written after the last turn of the game; nobody acts on it. Not used in the Detect config. |
| **Audience tools** (viewer, transcript, report) read the log. | Unchanged: the audience may see roles. Their wording ("revealed as") is not adapted to blind games (follow-up). |

## 3. The formula on the blind record (built)

`probes.formulas(record, cutoff, viewer, rated)["jobw50"]` on a record with hidden roles: every
pair of players that could be the two moles given the viewer's own clues, the clue cards shown
(a card binds only if its speaker is crew), the job results and "at least one mole is still
in"; pairs weighted by how well they explain the sabotage counts; a player's chance is the
weighted share of pairs containing them. No role is read. Full definition:
`docs/DETECT_RULES.md`, section 2.

- The existing functions return what they always did on games that reveal roles (measured: the
  1,518 vote turns above; and the new argument `hidden_out` defaults to "nothing hidden").
- The blind formula equals a second version written out again by hand in the tests, on 250+
  vote turns, to 12 decimal places; and swapping the hidden roles in the log never changes it.

**Masking a finished game** (`detect.mask_blind`): each `vote_result` gets the flag
`role_hidden`, the flag a blind game writes; everything then passes through the same gate.

## 4. D1: scripted tuning (measured)

Script: `python3.11 -m inside_job.detect d1 --config config/headroom.toml --out analysis/out/detect`
(36 seconds, zero calls). Output: `analysis/out/detect/detect_d1.md` and `.json`.
200 scripted-player games per setting, seeds 150001 to 150200, the default bots (crew `logician`
skill 0.7, moles `smart`, one decoy card a round). Error = the blind formula's `probes.brier`
at the last vote of each game, mean over the crew voters, then over games. A crew member who
knows nothing scores 0.222. Intervals: bootstrap over games, 2,000 draws, seed 20261110.

| Setting | Who gets a clue, how often | Formula's error | 95% interval | In the band 0.09–0.13 | Formula's top two are the two moles | 95% interval |
|---|---|---|---|---|---|---|
| today's rules | 2 to 4 players, every round, roles **revealed** | 0.135 | 0.122 to 0.149 | (not on the grid) | 41.4% | 35.7 to 47.6% |
| G1 | everyone, every round | **0.100** | 0.088 to 0.112 | **yes** | **51.2%** | 45.1 to 57.6% |
| G2 | 4 to 6 players, every round | 0.140 | 0.127 to 0.152 | no | 35.0% | 29.6 to 41.3% |
| G3 | 3 to 5 players, every round | 0.144 | 0.131 to 0.155 | no | 35.2% | 29.6 to 41.3% |
| G4 | 2 to 4 players, every round (today's density) | 0.166 | 0.155 to 0.178 | no | 28.5% | 23.1 to 34.1% |
| G5 | 2 to 4 players, 83 rounds in 100 | 0.180 | 0.169 to 0.191 | no | 22.9% | 17.9 to 28.1% |
| G6 | 2 to 4 players, 67 rounds in 100 | 0.186 | 0.175 to 0.196 | no | 21.5% | 16.7 to 26.7% |
| G7 | 2 to 4 players, 50 rounds in 100 | 0.195 | 0.186 to 0.205 | no | 18.6% | 14.0 to 23.4% |
| G8 | 2 to 4 players, 33 rounds in 100 | 0.206 | 0.197 to 0.215 | no | 15.1% | 10.8 to 19.6% |
| G9 | 2 to 4 players, 17 rounds in 100 | 0.214 | 0.206 to 0.222 | no | 11.5% | 7.5 to 15.8% |
| G10 | no clues | 0.220 | 0.213 to 0.227 | no | 10.0% | 6.5 to 13.8% |

All grid settings have roles hidden. "Top two are the two moles" is the share of crew voters at
the last vote for whom both moles rate strictly above the other four players, averaged over
games (fixed in DETECT_RULES.md). Other ways of counting, at G1 and under today's rules: for
every crew voter of the game 45.0% and 32.5%; for at least one 67.0% and 58.0%; from the public
record alone 23.0% and 21.0%.

**Verdict.** The walk stops at G1. G1 is in the band, and fails the 40% mark. D1 is not met.

**Why it came out this way** (measured, same games; script `analysis/detect_explore_after.py`,
output `analysis/out/detect/detect_explore_after.json`; computed after the verdict and deciding
nothing):

- In scripted games the formula's error is set mostly by **how long the game lasts**. Under
  today's rules, when the last vote is in round 1 (88 of 200 games) the error is 0.231 and the
  formula solves 2.5%; in round 2 (62 games) 0.097 and 55%; in round 3 (50 games) 0.015 and
  93%. The same pattern holds at every setting: a game that reaches round 3 is solved in 78% to
  97% of cases, even with no clues at all.
- The scripted moles win fast: the crew win 19% of scripted games under today's rules. In the
  75 finished real games the crew won 80%, and the last vote was in round 1 in 2 games of 75.
  So "the last vote" means something different in scripted games and in real ones.
- That is why today's rules already sit *above* the band with these bots (0.135), and why the
  walk had to go to more clues, not fewer, to land in it.

## 5. D2: does the talk carry signal (measured)

Script: `python3.11 -m inside_job.detect d2 --manifest docs/DETECT_D2_GAMES.json --games games --out analysis/out/detect`
(33 seconds, zero calls). Output: `analysis/out/detect/detect_d2.md` and `.json`.

The 75 finished games fixed by `games/index.jsonl` as it stood at 15:17:39 UTC (list and file
hashes in `docs/DETECT_D2_GAMES.json`), record masked. 830 crew vote turns that were not
fallbacks, 4,369 ratings. The reader is a logistic regression on the masked formula's log-odds
plus 12 talk features listed before fitting (who accused whom, votes in earlier rounds,
call-outs, cards shown, job claims, length of statements, name mentions, who whispered), fitted
leaving each game out in turn. Gain = first error − second error; above zero means the second is
better. Intervals: bootstrap over games, 2,000 draws, seed 20261110.

| Comparison | Vote turns | Games | First error | Second error | Gain | 95% interval |
|---|---|---|---|---|---|---|
| **The mark: masked formula, then the reader** | 830 | 75 | 0.1539 | 0.1481 | **+0.0058** | **−0.0005 to +0.0114** |
| Control: a rescaled formula with no talk, then the reader | 830 | 75 | 0.1544 | 0.1481 | +0.0063 | +0.0001 to +0.0120 |
| Masked formula, then the rescaled formula | 830 | 75 | 0.1539 | 0.1544 | −0.0005 | −0.0009 to −0.0001 |
| Round 1 only: masked formula, then the reader | 375 | 75 | 0.2030 | 0.1882 | +0.0148 | +0.0062 to +0.0230 |
| Round 1 only: rescaled formula, then the reader | 375 | 75 | 0.2036 | 0.1882 | +0.0154 | +0.0069 to +0.0237 |
| Rounds 2 and later: masked formula, then the reader | 455 | 73 | 0.1134 | 0.1150 | −0.0015 | −0.0099 to +0.0061 |
| Rounds 2 and later: rescaled formula, then the reader | 455 | 73 | 0.1138 | 0.1150 | −0.0012 | −0.0097 to +0.0064 |
| Leaving out a whole seed at a time, interval over 30 seeds | 830 | 75 | 0.1539 | 0.1489 | +0.0050 | −0.0017 to +0.0114 |

**Verdict: fail.** The gain is 0.0058, below the 0.01 mark, and its interval includes zero.

Reading the rest (all of it fixed in advance as "shown beside the mark"):

- Rescaling the formula does not help (−0.0005), so the reader's small gain is from the talk
  features, not from recalibration. The control's interval only just clears zero by the
  bootstrap and includes zero by the t interval (−0.0003 to +0.0119): weak.
- The gain is all in **round 1**: +0.015, interval clear of zero. Round 1 has nothing to mask,
  so this cannot be revealed roles leaking into the talk. There the formula knows little (error
  0.203, near the know-nothing 0.222) and the talk adds something.
- From **round 2 on** the reader adds nothing (−0.0015). The feared leak, which would have
  inflated later rounds, is not what the numbers show.
- In the reader fitted on all games (for reading only): a player who whispered that round is
  rated more likely a mole (+0.47 per standard deviation), one who showed cards less likely
  (−0.35), one whose statements were called out less likely (−0.20). Accusations by others add
  almost nothing (+0.02) beyond the formula.

## 6. D3: the score and the config (built, not run)

- `detect.detect_score(games)`: per model, mean of (formula's error − model's error) over its
  crew vote turns, bootstrap interval over games, paired t beside it; "beats the formula" only
  if the interval is above zero. It refuses a game that revealed roles (a masked old game too),
  refuses to pool games played under different `[game]` tables, counts fallback turns and does
  not score a model above 5% of them. Command: `python3.11 -m inside_job.detect score --batch NAME`.
- Tested on made-up readings with known answers (`tests/test_detect.py`, class `Score`): a
  perfect reader beats the formula, a reader that copies the formula is not separated, a reader
  that is always wrong is worse; each row equals a hand calculation.
- `config/detect_blind.toml`: the blind rules at the density the walk gave (G1), the Bluff
  games' cast. Its header says it is **not approved for model runs**. It plays with the mock
  model and the bots (tested).

## 7. What a new design could use (measured; decides nothing)

All from `python3.11 analysis/detect_explore_after.py . games` (output
`analysis/out/detect/detect_explore_after.json`), computed after the verdicts.

- On the 75 finished real games, at the last vote: the formula's error is **0.088** (interval
  0.072 to 0.104) with roles as played and **0.097** (0.081 to 0.114) with roles masked; its top
  two are the two moles in **59.6%** and **57.5%** of cases. So hiding roles alone hardly
  weakens the formula; its strength is in the clue cards and the job results. (These games were
  played with roles revealed; a game played blind may differ.)
- The scripted bots are a poor stand-in for game length (section 4). A tuning target defined at
  "the last vote" mixes clue density with how fast the scripted moles win. A target at a fixed
  round, or bots whose moles hold back as real ones do (the existing `hold1` type), would
  measure density more cleanly. Either is a new test and needs its own hashed file.
- The talk helps where the formula is weak (round 1) and not where it is strong. A Detect score
  taken at round-1 votes, or on rules that keep the formula weak for longer, is where a model
  would have room. That is a hypothesis from this data, not a result.

## 8. What Detect does not show

Nothing has been measured on any model. If it is ever run:

- It would compare a model's private ratings with one formula. Beating that formula is not
  "detecting deception" in general; a better formula could close the gap.
- It would say nothing about whether a model's votes or statements make use of what it detects.
- Old games are never compared with new-rules games. D2 used old games with roles masked, and
  that record is not the record a blind game would produce.
- A failed D2 does not show that models cannot read the talk. It shows that this fixed, simple
  reader, on these 75 games, did not beat the formula by the margin written first.

## 9. Order of work, and rulings after the numbers

- 15:14 UTC: code copied. 15:17:39: `games/index.jsonl` copied (78 rows) to fix the D2 games.
- Dials, blind formula, D1 runner, reader and score were written and tested on scripted, mock
  and made-up data. No formula error on any tuning seed and no feature of any real game was
  looked at.
- 15:35:23: `docs/DETECT_RULES.md` first hashed. Seconds later, before any run, the "Written"
  time in its heading was corrected from 15:40 to 15:36 and the file hashed again at 15:35:31
  (the machine's clock; the heading is half a minute ahead of it). That second hash is the one
  in `docs/DETECT_RULES.sha256`. `inside_job/detect.py` has not changed since then
  (SHA-256 `8d2fe05e1eb3c0b16a64a24ddea4cc5b819b17b479c021778d83ce5d882b1ae3`).
- 15:35:31 to 15:36:07: the D1 run. 15:36:38 to 15:37:11: the D2 run. Then section 7.

**Rulings after the numbers** (2026-11-11, about 15:40 UTC):

1. *D1 when the first setting in the band fails the 40% mark.* ANALYSIS.md says the density is
   the first setting in the band, and that "no longer solves it" means under 40% at the last
   vote. Read here as: both must hold for D1 to be met; they do not; the walk is not continued
   past G1 to look for another setting, and no setting further down is in the band anyway.
2. *No other ruling was needed.* Nothing in DETECT_RULES.md was reinterpreted, and no feature,
   setting, seed or game was added, dropped or changed.

## 10. Files

New: `inside_job/detect.py`, `tests/test_v05.py`, `tests/test_detect.py`,
`tests/dump_default_play.py`, `tests/fixtures/v05_defaults/digest.json`,
`config/detect_blind.toml`, `docs/DETECT.md`, `docs/DETECT_RULES.md`, `docs/DETECT_RULES.sha256`,
`docs/DETECT_D2_GAMES.json`, `analysis/detect_explore_after.py`, `analysis/out/detect/` (D1, D2
and the exploratory figures).

Changed: `inside_job/config.py` (the two dials, their validation, not logged at default),
`inside_job/engine.py` (hide roles, thin the clue deal, rules version 0.5 when a dial is on),
`inside_job/log.py` (the gate leaves the role out), `inside_job/prompts.py` (blind wording),
`inside_job/solver.py`, `inside_job/probes.py`, `inside_job/bots.py` (voted-out players with a
hidden role), `RULES.md` (the two dials).

Of these, `RULES.md`, `config.py`, `engine.py`, `log.py` and `prompts.py` are in the code stamp,
so the stamp of this code differs from the baseline's `0800d943`; play with the dials off is
identical all the same (section 2).

Not changed, and worth knowing: `analysis/common.py` rebuilds prompt context by hand and has no
blind branch; the viewer, transcript and report still say "revealed" for a blind game; the
baseline copy of the code cannot read a blind game's log (it does not know the two new keys).
