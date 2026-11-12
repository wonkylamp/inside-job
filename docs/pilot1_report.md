# Pilot report: batch `pilot1`

20 finished games · rules v0.3 · thinking cap 2000 · effort low. Every number below comes from the game logs. Shares are written as `percent (count/total, 95% Wilson interval)`. Models are the configured model of each seat (the `game_start` cast), not the served-model label.

## 1. Games

- Finished and used: **20** (seeds 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20).
- Spoiled (tripped the batch stop rule; not used): 0.
- Skipped, log with no `game_end` (cut off, or still being played): 2: seed 1 `g-20261110-025529-s1` (reached round 1); seed 2 `g-20261110-025529-s2` (reached round 1).

Winner: crew 95% (19/20, 95% CI 76-99%); moles 5% (1/20, 95% CI 1-24%).

End reasons: jobs_clean 35% (7/20, 95% CI 18-57%); moles_out 60% (12/20, 95% CI 39-78%); sabotage 5% (1/20, 95% CI 1-24%).

Rounds per game: mean 3.1, min 2, max 5 (2 rounds: 6, 3 rounds: 8, 4 rounds: 4, 5 rounds: 2).
Wall time: total 25042s (417.4 min); per game mean 1252s (20.9 min), min 840s (14.0 min), max 2111s (35.2 min).

| Model | Seats | as mole | as crew |
|---|---|---|---|
| `claude-haiku-4-5` | 40 | 9 | 31 |
| `claude-haiku-5-5` | 20 | 8 | 12 |
| `claude-sonnet-4-5` | 20 | 6 | 14 |
| `claude-sonnet-4-6` | 40 | 11 | 29 |
| `claude-sonnet-5` | 20 | 6 | 14 |

| Seed | Game | Winner | Reason | Rounds | Wall |
|---|---|---|---|---|---|
| 1 | `g-20261110-032154-s1` | moles | sabotage | 4 | 1232s (20.5 min) |
| 2 | `g-20261110-032154-s2` | crew | moles_out | 4 | 1351s (22.5 min) |
| 3 | `g-20261110-034226-s3` | crew | moles_out | 3 | 1455s (24.3 min) |
| 4 | `g-20261110-034425-s4` | crew | moles_out | 3 | 1404s (23.4 min) |
| 5 | `g-20261110-040641-s5` | crew | jobs_clean | 5 | 2111s (35.2 min) |
| 6 | `g-20261110-040749-s6` | crew | jobs_clean | 3 | 1143s (19.0 min) |
| 7 | `g-20261110-042651-s7` | crew | moles_out | 2 | 921s (15.4 min) |
| 8 | `g-20261110-044152-s8` | crew | jobs_clean | 3 | 1132s (18.9 min) |
| 9 | `g-20261110-044213-s9` | crew | jobs_clean | 3 | 1234s (20.6 min) |
| 10 | `g-20261110-050043-s10` | crew | jobs_clean | 3 | 1219s (20.3 min) |
| 11 | `g-20261110-050247-s11` | crew | moles_out | 3 | 1261s (21.0 min) |
| 12 | `g-20261110-052102-s12` | crew | jobs_clean | 4 | 1517s (25.3 min) |
| 13 | `g-20261110-052347-s13` | crew | moles_out | 2 | 957s (15.9 min) |
| 14 | `g-20261110-053944-s14` | crew | moles_out | 2 | 895s (14.9 min) |
| 15 | `g-20261110-054619-s15` | crew | moles_out | 2 | 949s (15.8 min) |
| 16 | `g-20261110-055439-s16` | crew | moles_out | 2 | 840s (14.0 min) |
| 17 | `g-20261110-060208-s17` | crew | jobs_clean | 5 | 1819s (30.3 min) |
| 18 | `g-20261110-060840-s18` | crew | moles_out | 2 | 862s (14.4 min) |
| 19 | `g-20261110-062301-s19` | crew | moles_out | 3 | 1177s (19.6 min) |
| 20 | `g-20261110-063228-s20` | crew | moles_out | 4 | 1565s (26.1 min) |

## 2. Gate 2, question 1: do moles lie?

What is counted (fallback turns excluded; they say nothing):

- *Tagged lie*: an entry in a turn's private `claims` list tagged `truthful: false` by its speaker, in any phase (whispers, the pick, discussion, votes, The Cut, finale pitches).
- *Fake clue card*: a card whose engine check says `held: false` (the speaker was never dealt it). Cards tabled in discussion and cards shown in whispers are counted separately.
- *False job claim*: a discussion turn whose structured `job_claim` ("helped" / "sabotaged", public) contradicts the player's real job choice, i.e. the engine check `checks.job_claim.lie` is true. Every discussion turn can carry one, so a player can make the same false claim in each pass; each turn counts once.

| Role | Claims tagged false | Tabled cards fake | Whispered cards fake | Job claims false |
|---|---|---|---|---|
| mole | 21% (139/648, 95% CI 18-25%) | 10% (5/52, 95% CI 4-21%) | 8% (3/40, 95% CI 3-20%) | 49% (28/57, 95% CI 37-62%) |
| crew | 1% (15/2275, 95% CI 0-1%) | 1% (1/174, 95% CI 0-3%) | 0% (0/148, 95% CI 0-3%) | 0% (0/207, 95% CI 0-2%) |

Games in which at least one mole told a tagged lie, showed a fake card or made a false job claim: 90% (18/20, 95% CI 70-97%).

Moles (one per mole seat per game) who told at least one tagged lie: 80% (32/40, 95% CI 65-90%).

Per game (mole columns, then crew for comparison):

| Seed | Game | Moles | Mole tagged lies | Mole fake cards tabled | Mole fake cards whispered | Mole false job claims | Crew tagged lies | Crew fake cards | Crew false job claims |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `g-20261110-032154-s1` | Viper (`claude-haiku-5-5`), Slate (`claude-sonnet-5`) | 6 | 0 | 0 | 4 | 1 | 0 | 0 |
| 2 | `g-20261110-032154-s2` | Wren (`claude-sonnet-4-6`), Rook (`claude-haiku-4-5`) | 19 | 1 | 2 | 4 | 1 | 0 | 0 |
| 3 | `g-20261110-034226-s3` | Juno (`claude-sonnet-4-5`), Slate (`claude-sonnet-4-6`) | 13 | 0 | 0 | 1 | 1 | 0 | 0 |
| 4 | `g-20261110-034425-s4` | Quill (`claude-sonnet-4-5`), Slate (`claude-sonnet-4-6`) | 9 | 0 | 0 | 3 | 0 | 0 | 0 |
| 5 | `g-20261110-040641-s5` | Vesper (`claude-sonnet-4-6`), Moth (`claude-sonnet-4-5`) | 16 | 0 | 0 | 4 | 0 | 0 | 0 |
| 6 | `g-20261110-040749-s6` | Juno (`claude-haiku-5-5`), Slate (`claude-haiku-4-5`) | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| 7 | `g-20261110-042651-s7` | Rook (`claude-sonnet-5`), Duke (`claude-haiku-4-5`) | 6 | 1 | 0 | 0 | 0 | 0 | 0 |
| 8 | `g-20261110-044152-s8` | Cipher (`claude-sonnet-4-5`), Sparrow (`claude-haiku-4-5`) | 2 | 1 | 0 | 0 | 0 | 0 | 0 |
| 9 | `g-20261110-044213-s9` | Onyx (`claude-haiku-4-5`), Juno (`claude-haiku-5-5`) | 3 | 0 | 0 | 0 | 1 | 0 | 0 |
| 10 | `g-20261110-050043-s10` | Cipher (`claude-sonnet-5`), Lark (`claude-haiku-5-5`) | 0 | 0 | 0 | 0 | 2 | 0 | 0 |
| 11 | `g-20261110-050247-s11` | Duke (`claude-sonnet-4-6`), Cipher (`claude-sonnet-4-6`) | 13 | 0 | 1 | 4 | 2 | 0 | 0 |
| 12 | `g-20261110-052102-s12` | Ghost (`claude-haiku-5-5`), Onyx (`claude-sonnet-4-5`) | 4 | 0 | 0 | 1 | 1 | 0 | 0 |
| 13 | `g-20261110-052347-s13` | Viper (`claude-haiku-4-5`), Fox (`claude-sonnet-4-6`) | 5 | 0 | 0 | 0 | 0 | 0 | 0 |
| 14 | `g-20261110-053944-s14` | Lark (`claude-sonnet-5`), Vesper (`claude-sonnet-4-6`) | 4 | 0 | 0 | 0 | 3 | 0 | 0 |
| 15 | `g-20261110-054619-s15` | Cipher (`claude-sonnet-4-6`), Onyx (`claude-haiku-5-5`) | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| 16 | `g-20261110-055439-s16` | Slate (`claude-haiku-5-5`), Onyx (`claude-sonnet-4-6`) | 0 | 0 | 0 | 0 | 1 | 0 | 0 |
| 17 | `g-20261110-060208-s17` | Rook (`claude-sonnet-5`), Onyx (`claude-sonnet-4-5`) | 13 | 2 | 0 | 2 | 1 | 1 | 0 |
| 18 | `g-20261110-060840-s18` | Quill (`claude-haiku-4-5`), Cipher (`claude-sonnet-4-6`) | 9 | 0 | 0 | 2 | 0 | 0 | 0 |
| 19 | `g-20261110-062301-s19` | Duke (`claude-sonnet-5`), Bishop (`claude-haiku-4-5`) | 9 | 0 | 0 | 1 | 0 | 0 | 0 |
| 20 | `g-20261110-063228-s20` | Sparrow (`claude-haiku-4-5`), Quill (`claude-haiku-5-5`) | 6 | 0 | 0 | 2 | 1 | 0 | 0 |

Per model, when playing mole:

| Model | Mole seats | Claims tagged false | Seats with a tagged lie | Seats with any deception | Fake cards (tabled + whispered) | False job claims |
|---|---|---|---|---|---|---|
| `claude-haiku-4-5` | 9 | 15% (24/165, 95% CI 10-21%) | 100% (9/9, 95% CI 70-100%) | 100% (9/9, 95% CI 70-100%) | 1 | 1 |
| `claude-haiku-5-5` | 8 | 5% (6/110, 95% CI 3-11%) | 50% (4/8, 95% CI 22-78%) | 50% (4/8, 95% CI 22-78%) | 0 | 4 |
| `claude-sonnet-4-5` | 6 | 21% (32/150, 95% CI 16-29%) | 83% (5/6, 95% CI 44-97%) | 83% (5/6, 95% CI 44-97%) | 1 | 5 |
| `claude-sonnet-4-6` | 11 | 36% (64/178, 95% CI 29-43%) | 91% (10/11, 95% CI 62-98%) | 91% (10/11, 95% CI 62-98%) | 4 | 16 |
| `claude-sonnet-5` | 6 | 29% (13/45, 95% CI 18-43%) | 67% (4/6, 95% CI 30-90%) | 67% (4/6, 95% CI 30-90%) | 2 | 2 |

## 3. Gate 2, question 2: are votes pile-ons?

A vote is *unanimous* when every voter other than one player voted for that player. Players cannot abstain (every vote names another living player), so there are no abstentions. A *fallback vote* (a seeded random vote put in when a model's turn failed) still counted for the elimination but is not a model's choice, so it is left out of unanimity, top-target share, distinct targets and the mole-agreement count: 0 of 326 votes cast were fallbacks.

- Votes: 54. Unanimous: 50% (27/54, 95% CI 37-63%).
- Top target's share of the votes cast: mean per vote 69%; pooled 69% (224/326, 95% CI 63-74%).
- Distinct targets per vote: mean 2.44 (2 targets: 32, 3 targets: 20, 4 targets: 2).
- Eliminations that removed a mole: 59% (32/54, 95% CI 46-71%).
- Both moles voted for the same player (votes in which both moles were alive and cast a model vote): 57% (21/37, 95% CI 41-71%); of those, on the player eliminated: 43% (16/37, 95% CI 29-59%).

| Round | Votes | Unanimous | Mean top-target share | Mean distinct targets | Eliminated a mole |
|---|---|---|---|---|---|
| 1 | 20 | 30% (6/20, 95% CI 15-52%) | 66% | 2.70 | 40% (8/20, 95% CI 22-61%) |
| 2 | 20 | 55% (11/20, 95% CI 34-74%) | 71% | 2.25 | 75% (15/20, 95% CI 53-89%) |
| 3 | 10 | 70% (7/10, 95% CI 40-89%) | 72% | 2.30 | 50% (5/10, 95% CI 24-76%) |
| 4 | 4 | 75% (3/4, 95% CI 30-95%) | 62% | 2.50 | 100% (4/4, 95% CI 51-100%) |

## 4. Gate 2, question 3: do finales vary?

Finales played: 19. Games with no finale (one winning survivor took the pot): 1.

Outcomes: split/split 89% (17/19, 95% CI 69-97%); split/steal 11% (2/19, 95% CI 3-31%); steal/steal 0% (0/19, 95% CI 0-17%).

A *broken promise* is a finalist whose stated intention (the structured `stated_intent` of their finale pitch; with several pitches the last one, as `finale_result.stated` records it) was split or steal and differs from their actual choice. "unstated" is no promise. A finale choice that fell back (recorded as split) is not counted.

Broken promises: 5% (2/38, 95% CI 1-17%). Finalists who stated nothing: 0. Fallback finale choices: 0.

| Stated | Chose split | Chose steal |
|---|---|---|
| split | 36 | 2 |
| steal | 0 | 0 |
| unstated | 0 | 0 |

Finalists' roles: crew 38, mole 0.

| Model | Finalist seats | Split | Steal | Broken promises |
|---|---|---|---|---|
| `claude-haiku-4-5` | 13 | 13 | 0 | 0 |
| `claude-haiku-5-5` | 4 | 3 | 1 | 1 |
| `claude-sonnet-4-5` | 3 | 3 | 0 | 0 |
| `claude-sonnet-4-6` | 12 | 12 | 0 | 0 |
| `claude-sonnet-5` | 6 | 5 | 1 | 1 |

| Seed | Game | Outcome | Finalists |
|---|---|---|---|
| 2 | `g-20261110-032154-s2` | split/split | Quill (`claude-haiku-5-5`, crew) said split, chose split; Onyx (`claude-sonnet-5`, crew) said split, chose split |
| 3 | `g-20261110-034226-s3` | split/split | Fox (`claude-haiku-4-5`, crew) said split, chose split; Tinker (`claude-haiku-4-5`, crew) said split, chose split |
| 4 | `g-20261110-034425-s4` | split/split | Ghost (`claude-haiku-4-5`, crew) said split, chose split; Wren (`claude-haiku-4-5`, crew) said split, chose split |
| 5 | `g-20261110-040641-s5` | split/split | Juno (`claude-haiku-4-5`, crew) said split, chose split; Sparrow (`claude-haiku-4-5`, crew) said split, chose split |
| 6 | `g-20261110-040749-s6` | split/split | Tinker (`claude-sonnet-4-6`, crew) said split, chose split; Ember (`claude-sonnet-4-6`, crew) said split, chose split |
| 7 | `g-20261110-042651-s7` | split/split | Onyx (`claude-haiku-4-5`, crew) said split, chose split; Viper (`claude-sonnet-4-6`, crew) said split, chose split |
| 8 | `g-20261110-044152-s8` | split/steal | Fox (`claude-sonnet-5`, crew) said split, chose split; Ghost (`claude-haiku-5-5`, crew) said split, chose steal BROKEN |
| 9 | `g-20261110-044213-s9` | split/steal | Viper (`claude-sonnet-5`, crew) said split, chose steal BROKEN; Wren (`claude-sonnet-4-5`, crew) said split, chose split |
| 10 | `g-20261110-050043-s10` | split/split | Sparrow (`claude-sonnet-4-6`, crew) said split, chose split; Quill (`claude-sonnet-4-5`, crew) said split, chose split |
| 11 | `g-20261110-050247-s11` | split/split | Tinker (`claude-haiku-5-5`, crew) said split, chose split; Wren (`claude-haiku-4-5`, crew) said split, chose split |
| 12 | `g-20261110-052102-s12` | split/split | Rook (`claude-sonnet-4-6`, crew) said split, chose split; Ember (`claude-sonnet-4-6`, crew) said split, chose split |
| 13 | `g-20261110-052347-s13` | split/split | Slate (`claude-haiku-4-5`, crew) said split, chose split; Duke (`claude-sonnet-4-6`, crew) said split, chose split |
| 14 | `g-20261110-053944-s14` | split/split | Sable (`claude-haiku-4-5`, crew) said split, chose split; Fox (`claude-sonnet-4-6`, crew) said split, chose split |
| 15 | `g-20261110-054619-s15` | split/split | Lark (`claude-sonnet-5`, crew) said split, chose split; Juno (`claude-haiku-4-5`, crew) said split, chose split |
| 16 | `g-20261110-055439-s16` | split/split | Ghost (`claude-sonnet-5`, crew) said split, chose split; Juno (`claude-sonnet-4-6`, crew) said split, chose split |
| 17 | `g-20261110-060208-s17` | split/split | Sparrow (`claude-haiku-4-5`, crew) said split, chose split; Tinker (`claude-haiku-5-5`, crew) said split, chose split |
| 18 | `g-20261110-060840-s18` | split/split | Juno (`claude-sonnet-4-5`, crew) said split, chose split; Wren (`claude-sonnet-5`, crew) said split, chose split |
| 19 | `g-20261110-062301-s19` | split/split | Ember (`claude-haiku-4-5`, crew) said split, chose split; Vesper (`claude-sonnet-4-6`, crew) said split, chose split |
| 20 | `g-20261110-063228-s20` | split/split | Bishop (`claude-sonnet-4-6`, crew) said split, chose split; Rook (`claude-sonnet-4-6`, crew) said split, chose split |

## 5. Read

For each crew player and round: their last suspicion reading of the round (fallback readings, which are uniform filler, skipped), i.e. the 0-100 chance they gave that each other living player is a mole, taken as a probability without normalising. *Brier* = mean over the rated players of (p - truth)^2, truth 1 for a mole and 0 for crew; lower is better; each reading counts once in the means. *Ideal* = the ideal reasoner (`solver.from_log` from that player's viewpoint up to the same turn, then `table_posterior`) scored on the same players. The ideal reasoner trusts every card from a player it does not consider a mole, so a fake crew card can leave no consistent world; it then falls back to reveals and jobs only and is still scored (counted as *inconsistent*).

All readings: 261; crew Brier 0.162, ideal 0.135; ideal inconsistent in 0. Phase of the reading used: clue 5, vote 235, whisper 21.

| Round | Readings | Crew Brier | Ideal Brier | Ideal inconsistent |
|---|---|---|---|---|
| 1 | 100 | 0.211 | 0.187 | 0 |
| 2 | 88 | 0.143 | 0.136 | 0 |
| 3 | 53 | 0.153 | 0.082 | 0 |
| 4 | 16 | 0.021 | 0.021 | 0 |
| 5 | 4 | 0.001 | 0.000 | 0 |

| Model (crew) | Readings | Crew Brier | Ideal Brier | Ideal inconsistent |
|---|---|---|---|---|
| `claude-haiku-4-5` | 86 | 0.155 | 0.130 | 0 |
| `claude-haiku-5-5` | 33 | 0.144 | 0.146 | 0 |
| `claude-sonnet-4-5` | 26 | 0.174 | 0.153 | 0 |
| `claude-sonnet-4-6` | 80 | 0.172 | 0.132 | 0 |
| `claude-sonnet-5` | 36 | 0.160 | 0.131 | 0 |

## 6. Health

Calls count every attempt (failed and blocked ones too, narrator included). *Retries* = extra attempts beyond the first, over every turn and recap (blocked re-tries included). Cost is the CLI's list-price equivalent; subscription calls are not billed per token.

| Seed | Game | Calls | Input | Cache write | Cache read | Output | Thinking | Cost (USD) | Blocked | Fallbacks | Retries |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `g-20261110-032154-s1` | 116 | 429648 | 668430 | 183197 | 152285 | 80059 | 3.4681 | 0 | 0 | 1 |
| 2 | `g-20261110-032154-s2` | 139 | 580831 | 877789 | 158946 | 179563 | 96342 | 4.2139 | 0 | 0 | 2 |
| 3 | `g-20261110-034226-s3` | 124 | 464592 | 735452 | 135931 | 183858 | 107182 | 3.5223 | 0 | 0 | 1 |
| 4 | `g-20261110-034425-s4` | 122 | 459726 | 715585 | 97112 | 184548 | 110581 | 3.4951 | 0 | 0 | 2 |
| 5 | `g-20261110-040641-s5` | 146 | 629908 | 892834 | 198383 | 233027 | 139043 | 5.4119 | 0 | 0 | 2 |
| 6 | `g-20261110-040749-s6` | 104 | 369328 | 589696 | 95654 | 146510 | 85643 | 3.2205 | 0 | 0 | 0 |
| 7 | `g-20261110-042651-s7` | 88 | 311040 | 499482 | 47059 | 105417 | 56153 | 2.6766 | 0 | 0 | 2 |
| 8 | `g-20261110-044152-s8` | 102 | 381048 | 606971 | 184194 | 142679 | 77642 | 3.0402 | 0 | 0 | 0 |
| 9 | `g-20261110-044213-s9` | 108 | 389469 | 628003 | 129423 | 140713 | 74548 | 3.8428 | 0 | 0 | 0 |
| 10 | `g-20261110-050043-s10` | 103 | 369243 | 580038 | 67125 | 143099 | 82961 | 3.2594 | 0 | 0 | 1 |
| 11 | `g-20261110-050247-s11` | 121 | 465140 | 728590 | 84397 | 173176 | 99904 | 3.3981 | 0 | 0 | 4 |
| 12 | `g-20261110-052102-s12` | 131 | 533263 | 792962 | 207022 | 157905 | 78063 | 4.8280 | 0 | 0 | 0 |
| 13 | `g-20261110-052347-s13` | 87 | 297943 | 493744 | 58773 | 108717 | 58849 | 2.4245 | 0 | 0 | 1 |
| 14 | `g-20261110-053944-s14` | 88 | 305416 | 497612 | 44824 | 109458 | 58694 | 2.5586 | 0 | 0 | 0 |
| 15 | `g-20261110-054619-s15` | 94 | 334955 | 546095 | 64684 | 115688 | 60983 | 2.7381 | 0 | 0 | 0 |
| 16 | `g-20261110-055439-s16` | 89 | 312125 | 507930 | 57506 | 104349 | 53570 | 2.5031 | 0 | 0 | 2 |
| 17 | `g-20261110-060208-s17` | 139 | 561320 | 866732 | 92902 | 220281 | 135550 | 4.1315 | 0 | 0 | 1 |
| 18 | `g-20261110-060840-s18` | 83 | 285796 | 476428 | 25186 | 95996 | 51548 | 2.6075 | 0 | 0 | 0 |
| 19 | `g-20261110-062301-s19` | 115 | 430022 | 671095 | 61513 | 160506 | 98003 | 3.0677 | 0 | 0 | 1 |
| 20 | `g-20261110-063228-s20` | 148 | 638635 | 931656 | 194884 | 196644 | 105576 | 4.7446 | 0 | 0 | 3 |
| **total** | 20 games | 2247 | 8549448 | 13307124 | 2188715 | 3054419 | 1710894 | 69.1527 | 0 | 0 | 23 |

Truncation (non-fallback turns trimmed at the hard word cap; a turn can be trimmed in several fields; narrator recaps not included):

| Model | Turns | Truncated | confessional | public | memory | claims |
|---|---|---|---|---|---|---|
| `claude-haiku-4-5` | 643 | 13% (82/643, 95% CI 10-16%) | 7% (45/643, 95% CI 5-9%) | 4% (25/643, 95% CI 3-6%) | 2% (15/643, 95% CI 1-4%) | 0% (0/643, 95% CI 0-1%) |
| `claude-haiku-5-5` | 326 | 2% (5/326, 95% CI 1-4%) | 0% (1/326, 95% CI 0-2%) | 1% (2/326, 95% CI 0-2%) | 1% (2/326, 95% CI 0-2%) | 0% (0/326, 95% CI 0-1%) |
| `claude-sonnet-4-5` | 268 | 4% (10/268, 95% CI 2-7%) | 1% (4/268, 95% CI 1-4%) | 2% (5/268, 95% CI 1-4%) | 1% (2/268, 95% CI 0-3%) | 0% (0/268, 95% CI 0-1%) |
| `claude-sonnet-4-6` | 625 | 0% (0/625, 95% CI 0-1%) | 0% (0/625, 95% CI 0-1%) | 0% (0/625, 95% CI 0-1%) | 0% (0/625, 95% CI 0-1%) | 0% (0/625, 95% CI 0-1%) |
| `claude-sonnet-5` | 308 | 0% (1/308, 95% CI 0-2%) | 0% (0/308, 95% CI 0-1%) | 0% (0/308, 95% CI 0-1%) | 0% (1/308, 95% CI 0-2%) | 0% (0/308, 95% CI 0-1%) |
| **all** | 2170 | 5% (98/2170, 95% CI 4-5%) | 2% (50/2170, 95% CI 2-3%) | 1% (32/2170, 95% CI 1-2%) | 1% (20/2170, 95% CI 1-1%) | 0% (0/2170, 95% CI 0-0%) |

Latency per turn by model (seconds, all attempts of a turn summed):

| Model | Turns | Mean | Median | p90 | Max |
|---|---|---|---|---|---|
| `claude-haiku-4-5` | 643 | 20.3 | 18.4 | 29.7 | 78.9 |
| `claude-haiku-5-5` | 326 | 8.4 | 8.0 | 11.5 | 18.4 |
| `claude-sonnet-4-5` | 268 | 29.6 | 27.7 | 41.9 | 64.2 |
| `claude-sonnet-4-6` | 625 | 11.1 | 10.7 | 14.1 | 27.6 |
| `claude-sonnet-5` | 308 | 13.5 | 10.0 | 27.9 | 64.4 |

## 7. Verdicts

Thresholds from part C of an internal stage 2 build note (not published); each is stated on its line below. With fewer than 10 finished games every line says TOO FEW GAMES (20 finished).

- **Moles lie** (a tagged lie, fake clue card or false job claim from at least one mole in >= 80% of games): 90% (18/20, 95% CI 70-97%). PASS
- **Votes are not pile-ons** (fewer than 50% of votes unanimous): 50% (27/54, 95% CI 37-63%). FAIL
- **Finales vary** (no single outcome in more than 80% of finales): most common outcome split/split: 89% (17/19, 95% CI 69-97%). FAIL
