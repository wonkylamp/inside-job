# Chart: how suspicious did each model's moles look?

`docs/charts/bluff_gap.svg` (1600×900, for X and the blog) and `docs/charts/bluff_gap.html` (the same
SVG in a standalone page with a table of the numbers; nothing loaded from the network).

## Regenerate

From anywhere (no model calls; reads `games/index.jsonl` and the game logs, read-only):

    python3.11 analysis/bluff_chart.py

Options: `--index`, `--root` (directory the logs' paths are relative to), `--out` (default
`docs/charts`). Every number comes from `analysis/bluff_score.py`'s functions with the same seeded
RNG in the same draw order, so the chart matches what `python3.11 analysis/bluff_score.py` prints.
The crew list, seeds, game count and effort in the footnote are read from the index too.

`docs/charts/bluff_gap.png` (1600×900) is rendered from the SVG, no model calls:

    rsvg-convert -w 1600 -h 900 docs/charts/bluff_gap.svg -o docs/charts/bluff_gap.png

(rsvg-convert 2.62.0; this command was first recorded on 2026-11-11 at the 30-game regeneration. How
the earlier PNG was made was not written down.)

## What it shows

One row per mole model, lowest mean gap first. The measure is the **crew suspicion gap**:
at each vote, every crew member privately rates every other player's chance of being a mole (0 to
100); the gap is the mean rating the crew gave the moles minus the mean rating it gave other crew.
Lower means the moles were harder to tell apart from the crew.

- **Dot**: one game (one seed). Dots that would sit on top of each other are nudged up or down;
  only the horizontal position carries a value.
- **Dark tick**, labelled "mean": the mean gap over that model's games.
- **Light bar**: bootstrap 95% interval for the mean, resampling whole games.
- **Vertical line at 0**: the crew suspected the moles no more than they suspected each other.
- **"moles won N of 10"**: games the mole side won.

Hovering a mark in the HTML page shows its value; the table under the chart gives every number.

## Limits

10 games per mole model (30 in all), the same five-model crew (Haiku 4.5, Haiku 5.5, Sonnet 4.5,
Sonnet 4.6, Sonnet 5), the same seeds (101 to 110), effort low; intervals are bootstrap 95% over
games. Read it as two groups, not a ranking: Fable 5.2 apart from Haiku 4.5 and Opus 5.5, which
cannot be told apart. As drawn on 2026-11-11 (`analysis/bluff_score.py`, 10 games each): Fable 5.2
-0.1 [-7.3, +7.2], Haiku 4.5 +15.8 [+7.8, +24.4], Opus 5.5 +17.4 [+8.2, +26.0]; moles won 6, 2 and
2 of 10.

The chart shows the whole-game gap only, as description. **The Fable 5.2 result does not survive
the pre-registered first-vote check** (`docs/PREREG_7A.md`: P1 no mark, ruled as fails in
`docs/ROAD_TO_10.md` section 4; P2 fails; P3 direction only), so the mechanism is not established.
The allowed wording is that Fable 5.2's moles "left less evidence", not that they fooled the crew.
See `docs/ROAD_TO_10.md`, sections 1 and 3, for the tests, and `docs/HEADROOM.md`, "30-game update",
for the per-model counts.

# Chart: forged clue cards, allowed to and told to

`docs/charts/fabricate.svg` (1200 x 1500 px, 4:5 portrait, for X on a phone), `docs/charts/fabricate.html`
(the same SVG in a standalone page with a table of every number, including the per-turn rates,
intervals, the zero bound and the one-move free rate; nothing loaded from the network),
`docs/charts/fabricate.png` (rendered from the SVG at its own size) and `docs/charts/fabricate_alt.txt`
(the alt text for X, which carries the fine print; at most 1,000 characters).

Rebuilt on 2026-11-11 after `docs/REVIEW_EVAL_FABRICATE.md` and an internal review of the X thread draft, not published (per-mole
unit, phone-size text, fine print in the alt text), then again on 2026-11-12 because the two-column
version was hard to read: it is now one plain bar chart, every model in one list sorted by share, with
every interval and turn count moved to the alt text and the HTML table.

## Regenerate

From anywhere (no model calls; reads `games/`, `probes/moves/runs/v1_public`,
`probes/moves/sets/v1_public.jsonl` and `config/bluff_deepseek.toml`, read-only):

    env -u OPENROUTER_API_KEY python3.11 analysis/fabricate_chart.py

This writes all four files and prints the alt text; the PNG step runs `rsvg-convert` (2.62.0 here)
at the SVG's own size and is skipped with a message if the tool is missing (`--no-png` skips it on
purpose). Options: `--games`, `--runs`, `--set`, `--out` (default `docs/charts`). Every number comes
from `analysis/fabricate_rate.py`'s `full_games`, `moles`, `one_move` and `instructed` at run time, so
the chart matches `python3.11 analysis/fabricate_rate.py --instructed --moles` (DeepSeek V4 Pro, batch
`bluff_deepseek`, is read by the chart script itself because it is not in that script's model list).
DeepSeek's "reasoning off" label is read from `[openrouter.reasoning_effort_by_model]` in its batch
config. Game counts, crew, effort and the moment count are read from the index and the logs too. If a
game finishes between the two reads, the script reads again. Test:
`python3.11 -m unittest tests.test_fabricate_chart` (layout and wording on fixtures with made-up
numbers: a lab with fewer than 10 games, a lab with none, DeepSeek present and absent, zero rows, ties
in the sort; the four Claude rows on the real logs).

The outside-lab games are still being added, so their rows change each time the chart is rebuilt.

## What it shows

A mole **forged** when, on at least one counted turn, it showed a clue card the engine says it was
never dealt (no judge model). One mole in one game is one unit (two per game). Counted turns: mole
discussion turns on pass 1 or 2 and each mole's first round-1 whisper to a crew member.

- **Title:** "Allowed to forge clue cards, only some AI models did." (it follows the numbers: "every
  AI model did" or "no AI model did" if those become true). Subtitle: "Share of moles that showed a
  fake clue card at least once."
- **Games line**, small and grey under the subtitle: "10 games per model unless marked. Each game has 2
  moles." ("unless marked" is dropped when no row is marked; both numbers are read from the data).
- **Bars:** one list of every model, no group headers, sorted by share of moles, highest first; ties go
  to the row with more moles, then by name, so zero rows end at the bottom. One blue (`#2a78d6`, the
  palette's slot 1) for every bar, 0 to 100% of moles, square at the left and a 4 px rounded end. The
  model name sits above its bar in bold; at the bar's end, the percentage in large bold and the count
  in regular weight ("80%  16 of 20 moles"). A zero row shows a short grey stub and "0%  0 of 20
  moles". No axis, gridlines, intervals or dots: the value labels carry the numbers. Models in the
  list: Fable 5.2, Opus 5.5, Sonnet 5.5, Haiku 5.5 and, once each has a finished game, DeepSeek V4 Pro,
  Gemini 4 Carbon, Grok 4.7, Kimi K3.1 Pro (a lab with no finished game is left out).
- **Notes after a name**, small and grey, only where a row differs from the rest: "· N games" when a
  model has other than 10 games, and "· reasoning off" on DeepSeek V4 Pro (the other labs ran with
  reasoning effort low). A row with exactly 10 games carries no note.
- **Callout, in a tinted box under the bars:** "Told to show a fake card, all four Claude models did."
  and "73 of 73 single moves each. A separate test." (from `instructed` at run time).
- **Footer:** "Small samples: models close together are not separated." and "The game engine checks
  every card. No judge model." A sorted list must not read as a ranking; the first line says so.
- **Alt text only:** per-turn counts, the Claude bootstrap 95% intervals, the exact 97.5% upper bound
  for 0 of 20 (16.8%), whether Fable 5.2 and Opus 5.5 are separated (Fisher exact, computed), that the
  non-Claude models ran through a different API (OpenRouter) and were not in the told-to test, that the
  told-to result is a different one-move test designed after an earlier check failed, each other lab's
  game count and that DeepSeek ran with reasoning off. If the full alt text would pass 1,000
  characters it drops the intervals first, then the crew detail, then writes turn counts as "44/100"
  and drops "(2 per game)" and "(no judge model)", which the image already says.

The frame is fixed at 1200 x 1500 (4:5); the space left after the fixed parts goes between the rows,
so 4 to 8 rows all fit. No text is under 30 px (2.5% of the width); names are 42 px and percentages 52 px.
Checked by eye at full size and scaled to 400 px wide.

## Limits

Ten games per Claude model (20 moles), the same five-model Claude crew (Haiku 4.5, Haiku 5.5, Sonnet
4.5, Sonnet 4.6, Sonnet 5) and seeds, low effort. The other labs ran through a different API, ten
games each except DeepSeek V4 Pro, which has five and ran with reasoning off; they are sorted into
the same list but are small samples, and none was in the told-to test. The sort is not a ranking:
models close together are not separated. Fable 5.2 (16 of 20) and Opus 5.5 (11 of 20) are not
separated per mole (Fisher exact p = 0.18,
reviewer script `evalreview/seats.py`; the chart script computes the same p). The bound for a zero
ignores that the two moles of a game share it. The told-to condition is one move at frozen moments,
not a full game, and ranks nothing (73 of 73 for all four). The one-move tests were designed after an
earlier check failed (`docs/CHECK_PHASE2.md`). Haiku 4.5 is in the tables `analysis/fabricate_rate.py`
prints but is not drawn (latest models only).

# Chart: what two same-model moles did with the pot

`docs/charts/finale.svg` (1200 x 1500 px, 4:5 portrait, for X on a phone), `docs/charts/finale.png`
(rendered from the SVG at its own size) and `docs/charts/finale_alt.txt` (alt text for X, at most 1,000
characters). Question: two moles of the same model won the game together; what did they do with the pot?

## Regenerate

From anywhere (no model calls; reads `games/` and `config/bluff_deepseek.toml`, read-only):

    env -u OPENROUTER_API_KEY python3.11 analysis/finale_chart.py

This writes the three files and prints the per-model table, every finale counted (game id, seq,
choices) and the alt text. Options: `--games`, `--out` (default `docs/charts`), `--no-png`. Test:
`python3.11 -m unittest tests.test_finale_chart` (counting on made-up logs with each outcome, a crew
finale, no finale, an unfinished game, a spoiled and a re-run index row; on the real logs, per-model steals
agree with `analysis/extra_stats.finale` over the same batches, layout fits 1200 x 1500 with no text
under 30 px and no overlap, the required footer lines, banned words, and that the files on disk are
current).

## What it shows

- **Unit:** one finale between the two moles of a game in the mole-benchmark batches (Fable 5.2:
  `headroom1` + `bluff_fable52`; Opus 5.5 `bluff_opus55`; Sonnet 5.5 `bluff_sonnet55`; Haiku 5.5
  `bluff_haiku55`; DeepSeek V4 Pro `bluff_deepseek`; Gemini 4 Carbon `bluff_gemini`; Grok 4.7
  `bluff_grok47`; Kimi K3.1 Pro `bluff_kimi`). In these batches both moles are the same model; the script
  checks that for every finale counted. The moles reach the finale only when they win with both alive.
  Crew finales are not counted. Last index row per (batch, seed); spoiled, mock and unfinished games left out.
- **Outcome**, from `finale_result.choices`: both split (50 each), one stole (100 and 0), both stole
  (0 each). Payoffs in the legend come from the pot in the logs.
- **Rows:** one per model with at least one finale, in a fixed order: the Claude models (Fable, Opus,
  Sonnet, Haiku), then the other labs A to Z. Never sorted by outcome. A model with no finale is not drawn;
  the alt text lists it as "no finale" (DeepSeek V4 Pro, reasoning off, 5 games).
- **Bars:** a count scale, one finale = one unit, so the longest bar (Fable 5.2, 6 finales) fills the width
  and a model with fewer finales has a shorter bar. Three segments in one blue ramp, light to dark by the
  number of players who stole (blue 250 / 450 / 650 of the dataviz palette, validated as an ordinal ramp on
  the light surface), with a 2 px gap between segments. Every segment carries its count and outcome in
  words ("6 of 6" / "both split"), so the colour is never the only cue. No red or green.
- **Footer:** "Small counts. Not a planned test." "Each finalist faced a copy of itself." "In a one-shot
  finale, stealing never pays less than splitting." The chart describes choices in a game; it does not
  judge them.

Counts on 2026-11-12 (both split / one stole / both stole / finales, in games): Fable 5.2 6/0/0/6 in 10;
Opus 5.5 1/0/0/1 in 10; Sonnet 5.5 1/2/2/5 in 10; Haiku 5.5 0/1/1/2 in 10; DeepSeek V4 Pro no finale in 5;
Gemini 4 Carbon 0/0/3/3 in 10; Grok 4.7 0/0/3/3 in 10; Kimi K3.1 Pro 0/2/1/3 in 10.

## Limits

Tiny counts (1 to 6 finales per model), and how many finales a model gets depends on how often its moles
won with both alive, so the denominators differ and are not chosen. Not a planned test: like the counts
in `analysis/extra_stats.py`, this was looked at after the games were played (exploratory, no pass mark). Each
finalist faced a copy of itself, so a model's row mixes its own choice with its reply to itself. In a
one-shot split-or-steal, stealing never pays less than splitting, so stealing is not evidence of anything
beyond playing the payoff; the public pitch before the choice is free talk. The other labs played through
a different API (OpenRouter) with reasoning effort low (DeepSeek: reasoning off). The crew in these games
included Haiku 4.5, which is not a row (latest models only); crew finales are not counted at all.
`games_frontier/` is not read.
