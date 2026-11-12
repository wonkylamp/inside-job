# Inside Job — Detect: what is fixed before the numbers

Written 2026-11-11, 15:36 UTC, by the session that built Phase 6. Design: `docs/BENCH_V2.md`,
section 4, "Phase 6, Detect". Pass marks: `docs/ANALYSIS.md`, D1 to D3 (hashed earlier today; not
edited here, only applied). This file fixes everything those marks leave open. Its SHA-256 is in
`docs/DETECT_RULES.sha256`. It is not edited after that: a correction goes in the report, dated
and labelled "ruling after the numbers".

## What had been seen when this was written

- The code and its tests: the new dials, the blind formula, the reader and the score all exist
  and pass their tests on scripted-player games, mock-model games and made-up data.
- From scripted-player games on the new rules: only that games finish without errors, and how
  often clues go out at three settings of the new dial (a test of the dial).
- Not seen: the formula's error, or the share of games it solves, at any setting of the grid,
  on any seed, under the new rules or today's. No tuning run of any size has been made.
- Not seen: the reader fitted to, or any talk feature computed from, any finished real game.
  The reader has only been run on made-up rows and on four mock-model games whose text is random.
- Seen earlier, by others, and written in the brief for this work: under today's rules the
  formula finds the moles about as well as the models do.

## 1. The new rules ("v0.5, blind")

Today's rules with two dials, both off by default:

- `hide_roles = true`: when a player is voted out, nobody at the table is told whether they were
  a mole or crew, then or later. The engine still knows, logs it, and still ends the game the
  moment the last mole is out.
- `clue_round_pct`: each round, the chance in 100 that any clues go out at all. At 100 (today)
  clues go out every round. When they do go out, who gets one is drawn as today.

Everything else is as in the 30 Bluff games: the `[game]` table of `config/headroom.toml`
(7 players, 2 moles, crew win at 3 clean jobs or both moles out, moles win at 2 blown jobs,
weak clues, whispers on, two discussion passes).

What a player can still work out, and is told in the rules text: the game ends when the last
mole goes, so while it goes on at least one mole is still in. The formula uses that too, and
nothing else, about voted-out players.

## 2. The formula on the blind record

The existing job-weighted formula `jobw50` (`inside_job.probes.formulas`), from one crew member's
own view just before a round's votes, with no role of any voted-out player:

1. Take every pair of players that could be the two moles.
2. Drop a pair if it contains the viewer; if it breaks one of the viewer's own clues; if it breaks
   a clue card shown in discussion, or shown to the viewer in a whisper, by a player who is not in
   the pair (a card binds only if its speaker is crew); if a job had more sabotages than the pair
   has members on that team; or if both of its members have already been voted out (the game
   would be over).
3. If no pair is left (somebody on the crew side showed a false card), ignore the cards and the
   viewer's own clues and keep the pairs allowed by the jobs, the viewer and the last rule.
4. Weight each pair by the chance of the sabotage counts seen, if each mole on a team sabotages
   with chance one half.
5. A player's chance of being a mole is the weighted share of pairs that contain them.

This is `probes.formulas(record, cutoff, viewer, rated)["jobw50"]` on a record whose voted-out
roles are hidden. On a record that reveals roles the function returns what it always did.

**Error** of a set of chances: `inside_job.probes.brier`, the mean over the rated players of
(chance − truth)², truth 1 for a mole and 0 for crew, from the engine's record of the deal.
The rated players are the other players still in.

## 3. D1: scripted tuning

**Players.** The existing scripted bots, as the `bots` command runs them by default:
`BotLLM(crew="logician", crew_skill=0.7, moles="smart", mole_cards="decoy")`.
- Crew: holds every pair of players consistent with what it has seen and rates each player by
  the share of pairs containing them; shows its real clues as cards (two at most a turn, newest
  first), in discussion and to a whisper partner; asks to whisper with its least suspected
  player; accuses and votes for its top suspect; as leader picks itself and its least suspected
  players. On each choice of whisper partner, team, accusation and vote, with chance 0.3, it
  acts at random instead.
- Moles: on a job, only the mole in the lowest seat sabotages; they show one false card a round
  that fits a story in which two crew members are the moles; they accuse and vote for the
  public record's top suspect who is not a mole; as leader a mole picks itself and the least
  suspected players who are not its partner; it whispers with a random player who is not its
  partner and shows no card there.
- The code is the definition: `inside_job/bots.py`, unchanged in behaviour for games that reveal
  roles (a test pins that).
- On the blind rules the bots' reasoning is the same with step 2's last rule in place of revealed
  roles: a bot is handed no role of a voted-out player and uses only that a mole is still in.

**Seeds.** The 200 seeds 150001 to 150200, one game per seed per setting. Not used before.

**Grid**, listed from most clues to fewest. Every setting has `hide_roles = true`, weak clues and
one clue per recipient. "Clues a round" is the average number dealt at a full table.

| Setting | Who gets a clue | Rounds in which clues go out | Clues a round | Dials |
|---|---|---|---|---|
| G1 | everyone | every round | 7 | `clue_recipients = 0` |
| G2 | 4 to 6 players | every round | 5 | `clue_recipients = 5`, spread 1 |
| G3 | 3 to 5 players | every round | 4 | `clue_recipients = 4`, spread 1 |
| G4 | 2 to 4 players (today) | every round | 3 | `clue_recipients = 3`, spread 1 |
| G5 | 2 to 4 players | 83 in 100 | 2.5 | G4 with `clue_round_pct = 83` |
| G6 | 2 to 4 players | 67 in 100 | 2 | G4 with `clue_round_pct = 67` |
| G7 | 2 to 4 players | 50 in 100 | 1.5 | G4 with `clue_round_pct = 50` |
| G8 | 2 to 4 players | 33 in 100 | 1 | G4 with `clue_round_pct = 33` |
| G9 | 2 to 4 players | 17 in 100 | 0.5 | G4 with `clue_round_pct = 17` |
| G10 | nobody | never | 0 | G4 with `clue_round_pct = 0` |

**Measure.** For each game, at its last vote (the last round in which a vote was held), for each
crew member who voted: the error of the blind `jobw50` from that crew member's view, rating the
other players still in. The game's error is the mean over those crew members. A setting's error
is the mean over its 200 games. A 95% interval is shown beside it (bootstrap over games, 2,000
draws, seed 20261110); the band is tested on the mean, as ANALYSIS.md words it.

**Rule.** Walk G1, G2, ... in order. The first setting whose error lies between 0.09 and 0.13
(both ends included) is the density. Every setting is played and shown, so the whole curve can
be seen; the choice is the walk's and nothing else. If no setting lands in the band, D1 has
failed: that goes at the top of the report and the work stops there.

**"No longer solves it".** For each crew voter at the last vote, the formula's chances for all
six other players, in the game or out, are taken; the formula has "solved" the game for that
voter if both moles rate strictly above each of the four others (a tie is not a solve). A game's
figure is the share of its crew voters for whom it is solved; a setting's figure is the mean
over its 200 games. Mark: under 40% at the chosen density. The same figure is computed on the
same seeds under today's rules (roles revealed, G4's clues, today's formula) and shown beside
it. Also shown, deciding nothing: the share of games solved for every crew voter, for at least
one, and from the public view with no private clue.

## 4. D2: the games and the masking

**Games.** The finished games in `games/index.jsonl` as it stood at 2026-11-11 15:17:39 UTC
(78 rows; SHA-256 of the file `f2cb20f10d90f7c009b80fa78bd529383a3e5c1d4f746734d39f531a8585159d`):
every row with a batch name among `pilot1`, `pilot2`, `headroom1`, `bluff_haiku45`,
`bluff_opus55`, `bluff_fable52`, `bluff_sonnet55`, rules 0.3, not spoiled, the last row where a
batch played a seed twice. That is **75 games**: pilot1 20 (seeds 1 to 20), pilot2 20 (1 to 20),
headroom1 3 (101 to 103), bluff_haiku45 10 (101 to 110), bluff_opus55 10 (101 to 110),
bluff_fable52 7 (104 to 110), bluff_sonnet55 5 (101 to 105). The three rows without a batch
name (two under rules 0.2, one test game) are left out. Games that finish later are not added.
The list, with the SHA-256 of each log, is `docs/DETECT_D2_GAMES.json` (SHA-256
`49161337424e21af19f0293732d38aba9ee09fd5ae401ae7dfc1725db083250f`).

**Masking.** Each `vote_result` in a game's log gets the flag `role_hidden`, the flag a blind
game writes. Everything the formula or the reader takes from the log passes through the same
gate that builds a player's view (`log.visible_events`), which then leaves the role out.
Nothing else in the log is changed.

**What masking cannot undo**, stated now: these games were played with roles revealed. From
round 2 on, the players knew who had been shown to be a mole or crew, and what they then said,
whom they accused and how they voted may carry that knowledge. A reader that learns from that
talk could be recovering the reveals, not reading the talk. Round 1 has no such problem: nobody
has been voted out, so there is nothing to mask and nothing to leak. So the round-1 result is
shown beside the main one (section 6).

**Turns.** Every vote turn of a crew member that was not a fallback turn. For each, the rated
players are the other players still in. One row per (vote turn, rated player).

## 5. D2: the reader and its features

A logistic regression that gives, for each row, the chance that the rated player is a mole.
Inputs, all computed from the voter's own view of the masked record up to just before the
round's votes (so each is something that player could see at the table). "Viewer" is the voter,
"target" the rated player, "this round" the round of the vote.

| Name | What it is |
|---|---|
| `lo` | Log-odds of the masked formula's chance for the target, the chance first held between 0.02 and 0.98. |
| `acc_now` | Share of the other players still in (not viewer, not target) who formally accused the target in a discussion statement this round. |
| `acc_before` | Number of (player, earlier round) pairs in which a player other than the viewer formally accused the target in discussion, divided by the number of earlier rounds; 0 in round 1. |
| `votes_before` | Number of votes cast against the target in earlier rounds by players other than the viewer, divided by the number of earlier rounds; 0 in round 1. |
| `challenged_now` | Number of times a player other than the viewer called out one of the target's statements of this round as false. |
| `accuses_viewer` | 1 if the target formally accused the viewer in discussion this round. |
| `target_f` | The masked formula's chance, from the viewer's view, for the player the target last formally accused this round; 0 if that player is the viewer; one third (2 moles among 6 others) if the target accused nobody. |
| `cards_now` | Number of clue cards the target put on the table in discussion this round. |
| `claim_helped` | 1 if the target was on this round's job and formally claimed to have helped. |
| `claim_silent` | 1 if the target was on this round's job and made no formal claim about it. |
| `words_now` | Words in the target's discussion statements this round, divided by 100. |
| `mentions_now` | Share of this round's discussion statements by players other than viewer and target that contain the target's name as a whole word. |
| `whispered` | 1 if the target was in a whisper pair this round (who whispered with whom is public). |

No feature reads the meaning of a statement, a confessional, a private tag, a suspicion number,
a memory note, or anything the engine alone knows.

**Fit.** Each feature is standardised with the mean and standard deviation of the training rows
(a feature that is constant there is dropped). Ridge penalty 1.0 on the standardised
coefficients, none on the intercept. Newton's method, at most 50 steps, each halved until the
penalised loss does not rise, stopping when no coefficient moves by more than 1e-8. Python
standard library only (`inside_job.detect.fit_logistic`).

**Test.** Leave one game out: for each of the 75 games, fit on the rows of the other 74 and
give chances for its rows. Per vote turn, the reader's error and the masked formula's error
are each `probes.brier` over that turn's rated players (the formula's chance is used as it is,
not clipped). **Gain** = formula's error − reader's error, mean over vote turns. Interval:
percentile bootstrap over games, 2,000 draws, seed 20261110 (`probes.bootstrap`), with the
paired t over game means beside it.

**Pass (ANALYSIS.md, D2):** gain at least 0.01 and the bootstrap interval above zero.
Otherwise fail, and Detect is not run on models.

## 6. D2: shown beside the mark, fixed now

None of these changes the pass or fail above. They are listed so that none can be added,
dropped or chosen after the numbers.

1. **Control: what the talk adds.** The same regression with `lo` alone (a formula that has
   merely been rescaled). Gain of the full reader over this one, same test, same interval. If
   the mark is passed but this interval includes zero, the report says at the top that the mark
   is met on paper and the talk signal was **not** shown: the reader won by rescaling the
   formula, not by reading the talk.
2. **Round 1 only**, and **rounds 2 and later only**: the same held-out chances, the gain over
   the formula and over the control on those vote turns. If the gain is there in later rounds
   and not in round 1, the report says the result may come from revealed roles leaking into
   the talk (section 4).
3. **Leave one seed out.** Games on the same seed share a deal (the same players are the
   moles). The test is repeated leaving out all games of a seed at once, with the bootstrap over
   seeds (30 of them).
4. The reader fitted once on all 75 games, coefficients printed, for reading only.

## 7. D3: the score (no model run is part of this work)

For new-rules games only (logged `hide_roles` true): for every crew vote turn that was not a
fallback, formula's error − the player's error, both `probes.brier` on the same rated players,
the player's chances being the suspicion numbers the engine logged divided by 100. **Detect**
for a model is the mean over its vote turns; interval by bootstrap over games (2,000 draws,
seed 20261110), paired t over game means beside it. "Beats the formula" only if the interval is
above zero. A model with no valid answer on more than 5% of its vote turns is not scored. The
scoring code refuses a game that revealed roles and refuses to pool games played under different
`[game]` tables.

## 8. Not done after the numbers

No change to the band, the 40% mark, the 0.01 margin, the grid, the seeds, the bot policy, the
game list, the masking, the feature list, the penalty or the test. If something here turns out
to be ambiguous or wrong, the report says so under "ruling after the numbers" and shows the
result both ways where that is possible.
