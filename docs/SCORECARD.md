# Inside Job — the road to 10/10

2026-11-10. Owner target: 10/10 as a benchmark and 10/10 as entertainment before the long run is
published. Starting point: the independent design review (an internal note, not published) gave benchmark 3/10 and
entertainment 5/10, on the sub-scores below.

**Who scores.** Never the lead and never the builder. A fresh reviewer with no history of the
project re-scores the same sub-scores from the raw logs and files: once after the probe check, once
before the long run. For entertainment, two or three people who have never seen the project also
watch one episode cold. The long run starts only when the fresh review has no sub-score under 8
and names nothing that would make a finding false.

**Status words.** *Measured* = checked on real data by the lead. *Built* = exists and is tested.
*Planned* = written down only.

## Benchmark (review: 3/10)

| Sub-score | Review | What 10 looks like, as evidence | What moves it | Status |
|---|---|---|---|---|
| Construct validity | 3 | The score is something arithmetic cannot do. At least one model beats the job-weighted formula on the frozen probes, its departures from the formula point at the truth (slope above 0), and probe scores predict results in full games. The "published record" line is gone from the prompt. Roles renamed: same ranking. | Probe check on top models; lie-spotting probe if Read fails; full mole trials for three models; renamed-roles run. | Cheap models fail it (measured). Fable 5.2 and Opus 5.5 tie the formula on 100 probes (measured): not passed. Plain lie-spotting is Read in disguise (measured). Tie-break score: failed its confirmation on 202 pairs and is matched by a no-model rule on the voting record (measured, `docs/LIEPROBE.md`). Read dropped as a headline. |
| Discriminative power | 2 | Models are spread wider than their intervals: at least three clearly separate groups among 15 models. Neither floor nor ceiling. | Probe states where the answer is open; top-model states added to the pool; headroom for moles. | Bluff on 30 games, 10 per mole model, same crew and seeds 101 to 110 (measured, `analysis/bluff_score.py`; `docs/HEADROOM.md`, "30-game update"): whole-game crew suspicion gap -0.1 [-7.3, +7.2] for Fable 5.2 moles against +15.8 [+7.8, +24.4] for Haiku 4.5 and +17.4 [+8.2, +26.0] for Opus 5.5; Fable lower on 9 of 10 seeds against each (permutation p = 0.015 and 0.014, uncorrected). This is description only: the Fable 5.2 result does not survive the pre-registered first-vote check (`docs/PREREG_7A.md`, `analysis/bluff_mechanism.py`: P1 no mark, ruled as fails in `docs/ROAD_TO_10.md` section 4; P2 fails; P3 direction only); mechanism not established. Two groups, not three: Opus 5.5 does not separate from Haiku 4.5 (-1.6, p = 0.80). |
| Reliability | 2 | ±0.012 per model (200 probes). One model under two names does not differ. Two halves of the set give the same order. | 200 probes per model; null and split-half gates. | Noise measured (0.095 per reading); gates planned |
| Control of confounds | 4 | Every model sees the same bytes. Effort and thinking cap fixed on evidence and reported. No model trimmed by word caps on more than 2% of probes. Seat, round and original player balanced in the set. | Frozen hashed set; effort sweep; cap check per model. | Being built |
| Ground truth | 8 | Truth comes from the engine, never from a judge model. Every score can be recomputed from published files. | Already strong; publish the set, replies and scoring code. | Built |
| Cost per unit of information | 3 | One call gives one scored decision. A new model can be added to the chart in an hour for about 200 calls. | Probes replace full games for ranking. | Being built |
| Resistance to saturation | 4 | The best model is still well short of perfect, and a held-back private half of the set detects leakage. Harder states can be added from stronger models' games without changing the method. | Private half; probe pool refreshed from top-model games. | Planned |

## Entertainment (review: 5/10)

| Sub-score | Review | What 10 looks like, as evidence | What moves it | Status |
|---|---|---|---|---|
| Tension | 3 | The viewer cannot call the winner before the last round in most games. Moles win a real share. No game ends in two rounds with no sabotage. | Top-model moles first; v0.4 dials if they still cannot win. | Crew won 19/20 and 17/20 with cheap moles; against the same cheap crew Fable 5.2 moles won 6 of 10, Haiku 4.5 moles 2 of 10, Opus 5.5 moles 2 of 10 (measured, `analysis/bluff_score.py`, seeds 101 to 110; all six Fable wins on seeds 101 to 107). Mixed-lab frontier table: moles won 3 of 4 (measured, `games_frontier/`) |
| Readable story | 7 | Someone who has never seen the rules follows an episode without help. | Rebuilt viewer: staged scenes, captions, pace tied to word count. | Being built |
| Memorable moments | 6 | Every episode has at least one clip that works alone in under 40 seconds: a lie with the diary beside it, a betrayal, a catch. | Top-model cast; clip finder over the logs (lies the table believed, partners turned on). | Clip finder built (`analysis/clip_finder.py`, the clip list itself is an internal note, not published): 295 clips found by rule in 60 games, 23 of them in the 4 frontier games; 211 fit in 40 seconds. Every quote checked against its log line (lead, 2026-11-11). Not shown: that a person finds them memorable; no cold viewer has watched one. |
| Variety | 4 | Ten episodes, no two with the same arc. Not always the leader sabotaging his own team. | Rule dials; cast mix; choose episodes from a larger batch by a stated rule. | Planned |
| Pacing | 4 | An episode runs 6 to 9 minutes with no dead stretch. Vote speeches that repeat the discussion are cut or shortened. | Viewer edit rules; shorter vote speeches in show rules. | Planned |
| Ending | 3 | Every episode ends on a reveal: the surviving mole is unmasked on screen, and the finale is not split/split nine times in ten. | Finale change (owner decision); end card with the unmasking. | End card with the unmasking and payouts built and checked on a real game (lead, 2026-11-10). Finale itself unchanged: both headroom mole pairs split. On the mixed-lab frontier table the three finales played were steal over split, both steal, steal over split (measured, 4 games). |
| Character and voice | 6 | Each model is recognisable by how it plays. Portraits, a distinct look, and public voices that differ. | Portraits in the rebuilt viewer; named top-model cast. | Being built |

## How the two fit together

The benchmark is the probes; the show is the full games. They share the engine, the logs and the
models, and each feeds the other: the show's games become new probe states, and the benchmark's
charts open each episode. Neither is bent to serve the other: probe conditions are fixed and
identical, show rules can be tuned for drama and are labelled as show games.

## What cannot be promised

- If no model beats the formula on Read, Read is dropped as a headline and the benchmark stands on
  a different skill. That is a result to report, not to hide.
- A 10 for reliability is bought with calls. The plan reaches ±0.012; tighter costs four times as
  much per halving.
- Whether a post spreads is not something a scorecard can settle.
