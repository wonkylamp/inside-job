Set `read_v1.jsonl` sha256 `11de3e49673ab8433a754a7050291c31649f4b1d78a8f1774b59485d02187903`, 100 probes; 4 run(s) in `probes/runs/read_v1`.

## Runs

| run (model / effort / cap) | valid | games | failed | mean input | mean output | mean thinking | mean latency s | served by another model |
|---|---|---|---|---|---|---|---|---|
| claude-fable-5-2 / high / t-1 | 100 | 36 | 0 | 2.000 | 1468.200 | 805.060 | 16.614 | none |
| claude-fable-5-2 / low / t2000 | 100 | 36 | 0 | 2.000 | 767.730 | 176.320 | 9.753 | none |
| claude-opus-5-5 / high / t-1 | 100 | 36 | 0 | 2.000 | 1261.790 | 616.810 | 13.263 | none |
| claude-opus-5-5 / low / t2000 | 100 | 36 | 0 | 2.000 | 693.540 | 149.000 | 8.260 | none |

## Brier of the reading (valid probes; lower is better)

| run | model | original player | simple | jobw50 | jobw80 | public |
|---|---|---|---|---|---|---|
| claude-fable-5-2 / high / t-1 | 0.137 | 0.169 | 0.161 | 0.139 | 0.139 | 0.165 |
| claude-fable-5-2 / low / t2000 | 0.142 | 0.169 | 0.161 | 0.139 | 0.139 | 0.165 |
| claude-opus-5-5 / high / t-1 | 0.136 | 0.169 | 0.161 | 0.139 | 0.139 | 0.165 |
| claude-opus-5-5 / low / t2000 | 0.141 | 0.169 | 0.161 | 0.139 | 0.139 | 0.165 |

## Model minus jobw50 (paired per probe; bootstrap over games, 2,000 resamples; t over game means)

| run | probes | mean | boot 95% | t: game mean [95%] | probes (undecided) | mean undecided | boot 95% | t: game mean [95%] | undecided ratings | slope | slope boot 95% |
|---|---|---|---|---|---|---|---|---|---|---|---|
| claude-fable-5-2 / high / t-1 | 100 | -0.002 | [-0.015, 0.011] | -0.001 [-0.016, 0.013] | 100 | -0.014 | [-0.035, 0.007] | -0.014 [-0.037, 0.009] | 353 | 0.635 | [0.226, 1.015] |
| claude-fable-5-2 / low / t2000 | 100 | 0.004 | [-0.010, 0.017] | 0.004 [-0.011, 0.019] | 100 | -0.009 | [-0.032, 0.011] | -0.010 [-0.033, 0.013] | 353 | 0.525 | [0.083, 0.954] |
| claude-opus-5-5 / high / t-1 | 100 | -0.003 | [-0.018, 0.013] | -0.003 [-0.020, 0.014] | 100 | -0.019 | [-0.043, 0.002] | -0.020 [-0.046, 0.006] | 353 | 0.664 | [0.182, 1.136] |
| claude-opus-5-5 / low / t2000 | 100 | 0.002 | [-0.014, 0.019] | 0.002 [-0.016, 0.020] | 100 | -0.018 | [-0.041, 0.005] | -0.018 [-0.044, 0.007] | 353 | 0.611 | [0.201, 1.035] |

Undecided: ratings with jobw50 in [0.2, 0.8]; per probe the mean over its undecided ratings of (s - t)^2 - (f - t)^2. Slope = sum((s-f)(t-f)) / sum((s-f)^2) over those ratings; above 0 means the model's departures from the formula point at the truth.

## Votes on a mole (share of valid probes)

| run | model | original player | jobw50 top suspect (ties split) |
|---|---|---|---|
| claude-fable-5-2 / high / t-1 | 0.640 | 0.620 | 0.735 |
| claude-fable-5-2 / low / t2000 | 0.630 | 0.620 | 0.735 |
| claude-opus-5-5 / high / t-1 | 0.670 | 0.620 | 0.735 |
| claude-opus-5-5 / low / t2000 | 0.680 | 0.620 | 0.735 |

## Between runs (A minus B, on the probes both answered)

| A | B | probes | Brier A | Brier B | mean A-B | boot 95% | t: game mean [95%] | undecided A-B | boot 95% | t: game mean [95%] | slope A | slope B | votes on mole A | votes on mole B |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| claude-fable-5-2 / high / t-1 | claude-fable-5-2 / low / t2000 | 100 | 0.137 | 0.142 | -0.005 | [-0.014, 0.003] | -0.005 [-0.014, 0.004] | -0.005 | [-0.020, 0.010] | -0.004 [-0.019, 0.010] | 0.635 | 0.525 | 0.640 | 0.630 |
| claude-fable-5-2 / high / t-1 | claude-opus-5-5 / high / t-1 | 100 | 0.137 | 0.136 | 0.001 | [-0.005, 0.007] | 0.002 [-0.006, 0.009] | 0.005 | [-0.005, 0.016] | 0.006 [-0.007, 0.018] | 0.635 | 0.664 | 0.640 | 0.670 |
| claude-fable-5-2 / low / t2000 | claude-opus-5-5 / low / t2000 | 100 | 0.142 | 0.141 | 0.002 | [-0.007, 0.009] | 0.002 [-0.005, 0.010] | 0.008 | [-0.002, 0.019] | 0.008 [-0.002, 0.019] | 0.525 | 0.611 | 0.630 | 0.680 |
| claude-opus-5-5 / high / t-1 | claude-opus-5-5 / low / t2000 | 100 | 0.136 | 0.141 | -0.005 | [-0.011, 0.001] | -0.005 [-0.011, 0.001] | -0.002 | [-0.009, 0.007] | -0.002 [-0.010, 0.006] | 0.664 | 0.611 | 0.670 | 0.680 |


## Lead's reading of the check (2026-11-10)

400 calls, none failed, every call served by the model asked. Extra breakdowns below are computed
from the same run files (bootstrap over games, 2,000 resamples).

| run | model minus original player | decided ratings, model minus jobw50 | own top suspect is a mole | 50/50 blend with jobw50, minus jobw50 |
|---|---|---|---|---|
| claude-fable-5-2 / high | -0.032 [-0.051, -0.014] | +0.013 [+0.002, +0.024] | 0.680 | -0.006 [-0.013, +0.001] |
| claude-fable-5-2 / low | -0.027 [-0.044, -0.011] | +0.018 [+0.008, +0.027] | 0.683 | -0.003 [-0.011, +0.003] |
| claude-opus-5-5 / high | -0.033 [-0.049, -0.017] | +0.015 [+0.003, +0.027] | 0.710 | -0.006 [-0.014, +0.002] |
| claude-opus-5-5 / low | -0.028 [-0.041, -0.016] | +0.025 [+0.012, +0.040] | 0.690 | -0.006 [-0.014, +0.003] |

- **Gate (step 2 of an internal run plan, not published): not passed.** No run beats the job-weighted formula by more than
  its interval, on all ratings or on undecided ratings. Step 3b applies.
- Both top models read better than the cheap players who sat in those seats (about 0.03).
- Their departures from the formula point at the truth (slope 0.5 to 0.7, intervals above 0), but
  the gain is cancelled by hedging on ratings the logic has already settled.
- Their votes land on a mole less often (0.63 to 0.68) than voting for the formula's top suspect (0.735).
- High effort against low: -0.005 for both models, intervals include 0, for 4 to 5 times the
  thinking tokens. Effort and thinking cap were changed together, so they are not separated.
- Fable 5.2 against Opus 5.5: +0.001 [-0.005, +0.007] at high effort. No difference.
- Tokens, all four runs: output 419,126 (thinking 174,719 of it), cache creation 1,782,322, cache
  read 1,556,870, input 800.
- Limits: 100 probes from 36 games; every state comes from a game played by Haiku- and Sonnet-level
  models; the probed model inherits the original player's memory note.
