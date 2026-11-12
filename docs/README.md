# Docs index

Every doc in this folder, with one line on what it is. Start with the top-level
[README.md](../README.md) and [RULES.md](../RULES.md).

## What was left out of the public copy, and why

This repository was published from a private working tree. Left out: the build plan, the stage
contracts for the pilot tooling and the viewer (their content was folded into `docs/SPEC.md`),
the X post drafts and their reviews, the clip lists (rebuilt by `analysis/clip_finder.py`), and a
pre-release audit. These are plans, build notes, drafts and reviews of drafts, written while the
work was going on. Two more working notes are also not in this copy while their status is
decided: an independent design review of the first pilot (`docs/DESIGN_REVIEW.md`, which holds
pilot-1 observations not restated elsewhere and the starting scores in `docs/SCORECARD.md`) and a
long-run plan (`docs/LONGRUN.md`, which defines the step gates that `docs/PROBES.md`,
`docs/probe_check_read_v1.md`, `docs/LIEPROBE.md` and `docs/HEADROOM.md` were judged against).
The numbers in the launch-thread draft are printed by `analysis/extra_stats.py` from the logs.
Also left out: two viewer avatars drawn after real people's profile pictures, the raw read-probe
runs (`probes/runs/`), the held-out half of the one-move test set (`probes/moves/sets/v1_private.jsonl`;
its manifest and hash are published), and a 16 MB pickle cache (`analysis/out/best_response_rows.pkl.gz`,
rebuilt by `python3.11 -m analysis.best_response`). Some docs and code comments still name a
left-out file (for example `PLAN.md`, `docs/STAGE2.md`, `docs/STAGE4.md`, `docs/STAGE4B.md`,
`docs/V03.md`, `docs/LONGRUN.md`, `docs/POSTS_DRAFT.md`, `docs/DESIGN_REVIEW.md`, `docs/CLIPS.md`).
Docs that are not hashed were edited so they no longer point at a left-out file (a few now say
"an internal note, not published"). The mentions are kept in the hashed files, because editing
them would break the hash, and in code, configs, tests and the exported replays, which are
published exactly as they were run (part of the code is under the code stamp in every game log).

Known consequences:

- The held-out half of the one-move set was cut from the even-seed games (seeds 102 to 110) of the
  published `bluff_*` and `headroom1` batches, and every one of those game logs is published here.
  The private half can therefore be rebuilt from public files; `docs/BENCH_V2.md` (decision 6)
  describes holding those logs back as the default, which this release did not do.
- The Read-probe results (`docs/PROBES.md`, `docs/probe_check_read_v1.md`, `docs/LIEPROBE.md`)
  cannot be re-scored from this repository, because their run files are not published.
- Some numbers in `docs/REVIEW_EVAL_FABRICATE.md` and `docs/CHART.md` came from a reviewer's
  scratch scripts (`evalreview/*.py`) that are not in this repository.
- In the public logs, the Claude Code CLI's per-call `session_id`, `uuid` and
  `credential_expires_at` were removed from the raw call logs (`*.raw.jsonl.gz`) and from the
  one-move run files, except in `probes/moves/runs/v1_public/before.jsonl` and
  `after__evidence.jsonl`, whose bytes are pinned by `screen.json`. Absolute paths in
  `games_frontier/index.jsonl` were made repo-relative. Nothing else in any log was changed.

## Using it

| Doc | What it is |
|---|---|
| [SETUP_PROMPT.md](SETUP_PROMPT.md) | A prompt to paste into a coding agent so it sets the repo up and plays a free mock game. |
| [OPENROUTER.md](OPENROUTER.md) | How other labs' models are seated through OpenRouter: the key, the spend guard, errors, measured costs. |
| [RAWLOG.md](RAWLOG.md) | The raw call log written beside each game, and the code stamp. |
| [SPEC.md](SPEC.md) | Technical spec of the engine, CLI, logs and viewer as built (rules v0.3). |
| [V04.md](V04.md) | The v0.4 candidate rules, built as dials that are off by default, and how they were checked. |
| [example_prompts.md](example_prompts.md) | Example prompts the players receive. |
| [media/MEDIA.md](media/MEDIA.md) | The images and clip in `docs/media/`, and the scripts that render them from the logs. |

## Results, pass marks and audits

| Doc | What it is |
|---|---|
| [ANALYSIS.md](ANALYSIS.md) | Bench v2 measures, tests and pass marks, written and hashed before the runs (`ANALYSIS.sha256`). |
| [FABRICATE.md](FABRICATE.md) | The forged-clue-card one-move test and its pass mark, hashed before the run (`FABRICATE.sha256`). |
| [FABRICATE_INSTRUCTED.md](FABRICATE_INSTRUCTED.md) | The told-to condition of that test, hashed before the run (`FABRICATE_INSTRUCTED.sha256`). |
| [FABRICATE_RESULT.md](FABRICATE_RESULT.md) | Result of the forged-card one-move test. |
| [FABRICATE_INSTRUCTED_RESULT.md](FABRICATE_INSTRUCTED_RESULT.md) | Result of the told-to condition. |
| [FABRICATE_ERRATUM.md](FABRICATE_ERRATUM.md) | Erratum: a ruling made after the numbers, and a mock game that was cited as real behaviour. |
| [REVIEW_EVAL_FABRICATE.md](REVIEW_EVAL_FABRICATE.md) | An independent methods review of the forged-card claims. |
| [CHART.md](CHART.md) | The charts in `docs/charts/`: what they show, how they are built, their limits. |
| [CHECK_PHASE2.md](CHECK_PHASE2.md) | The Phase 2 check of the concealment one-move test: it failed, and the stop rule applied. |
| [BENCH_V2.md](BENCH_V2.md) | Bench v2 design, phases, stop rule and the decisions taken along the way. |
| [MOVES.md](MOVES.md) | Build notes of the one-move test tooling (`inside_job/moves.py`). |
| [BETRAY.md](BETRAY.md) | Bench v2 Phase 5 (Betray): design, rules fixed before any run, and the supply of frozen finale states. |
| [detect/DETECT.md](detect/DETECT.md) | Bench v2 Phase 6 (Detect): design, build, and its two failed zero-call checks. |
| [detect/DETECT_RULES.md](detect/DETECT_RULES.md) | Detect's rules, hashed before the numbers (`DETECT_RULES.sha256`; it names the path `docs/DETECT_RULES.md`, so run `shasum -c` with the file copied there or check the hash by hand). |
| [detect/REPORT.md](detect/REPORT.md) | Report of the Detect build session. |
| `detect/detect.diff` | The Detect code, tests and config as a diff; it was never merged into the engine. |
| [PREREG_7A.md](PREREG_7A.md) | Criterion 7a pass marks, written before the numbers. |
| [HEADROOM.md](HEADROOM.md) | Mole headroom test: Fable 5.2 as both moles. |
| [ROAD_TO_10.md](ROAD_TO_10.md) | Criteria for the benchmark, with each one's status, rulings and the plan at the time. |
| [SCORECARD.md](SCORECARD.md) | Benchmark and entertainment scorecard. |
| [CLAIMS.md](CLAIMS.md) | What the benchmark claims, and what it does not. |
| [GATES.md](GATES.md) | Gates G0 to G4: design, pass marks and cost estimates. |
| [EXPLORE.md](EXPLORE.md) | Behaviour counts from the finished games (`analysis/explore.py`), with data problems found. |
| [PROBES.md](PROBES.md) | Read probes, version 1: build contract and results. |
| [probe_check_read_v1.md](probe_check_read_v1.md) | The 400-call Read check: gate not passed. |
| [LIEPROBE.md](LIEPROBE.md) | Lie-spotting probe: zero-call check and verdict. |
| [pilot1_report.md](pilot1_report.md), [pilot2_report.md](pilot2_report.md) | Reports of the two pilot batches (older Claude models). |
| [v04_bot_results.md](v04_bot_results.md) | Scripted-bot results for the v0.4 candidate rules. |
| [SOURCES.md](SOURCES.md) | Prior work and sources. |
