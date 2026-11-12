# Inside Job — prior work and sources

Status: compiled 2026-11-10. Read-only research notes. Nothing here changes the rules or the claims.

## How this file was made

- Every fact below was read in a document fetched on 2026-11-10. Nothing is from memory. Each fact
  gives the URL and a location. "p.N" is the page of the PDF file (counted from page breaks in the
  extracted text). For the journal papers, the printed page number is different; where that
  matters, it is noted.
- Quotes are kept to short fragments around the number, inside quotation marks. Tables are cited
  by table number and cell.
- "Our computation" marks a number we computed from released data or from the paper's own counts.
  It is not the authors' number.
- Downloaded copies and extracted text are under
  a scratch folder (not published),
  one sub-folder per source (written below as `sources/<folder>`). That folder is temporary
  scratch space and is not part of the project. Nothing in it was executed. Python was used only to
  count rows in data files.
- Heading 7 in each entry ("For Inside Job") is our reading, not the authors'.
- Section D at the end lists the findings that cut against `docs/CLAIMS.md`.

---

## Part A. LLM benchmarks with hidden roles or social deduction

### A1. AvalonBench (first titled "From Text to Tactic")

1. **Citation and what we have.** J. Light, M. Cai, S. Shen, Z. Hu, "AvalonBench: Evaluating LLMs
   Playing the Game of Avalon", arXiv 2310.05036 (v1 and v2 are titled "From Text to Tactic"; v3
   is dated 8 Nov 2023). The repository README gives the venue as the NeurIPS 2023 Foundation
   Models for Decision Making workshop.
   - Full text, all three versions (28 pages each): https://arxiv.org/pdf/2310.05036 →
     `sources/avalonbench`, `avalonbench_v1`, `avalonbench_v2`.
   - Code repository https://github.com/jonathanmli/Avalon-LLM: we read the README and opened two
     deal files (`sources/avalonllm_repo`).
2. **Game and set-up.**
   - Five-player Avalon: Merlin, two Servants, Minion, Assassin.
   - Models: GPT-3.5-turbo and Llama2-chat-7B.
   - One LLM replaces one rule-based "naive" bot, either as Assassin or as a Servant. There is also
     an all-GPT-3.5 self-play arena.
   - Game counts (p.8): "we ran 30 different games" for GPT-3.5 and "10 different games" for
     Llama2. For the bot baseline, "we ran 1000 games". Self-play is "60 games" (p.10).
   - Temperature 0.1 (p.8).
   - The deal files we opened put the LLM at index 0, with the quest leader also 0. `dev.json` holds
     a single deal.
3. **What was measured.**
   - Win rate.
   - Assassination accuracy.
   - "Deduction accuracy". The LLM is asked for a probability in [0, 1] that each player is Good
     (prompt, Table 20, p.20). The answer is thresholded at 0.5 and scored per game against the true
     side. No Brier score is computed.
   - The rule bot ("Naive Servant") enumerates every good/evil assignment that the mission results
     allow (Algorithms 1–2, p.7). It ignores talk and votes: "only the number of fails on each
     mission counts" (p.6). This is a constraint solver, like Inside Job's logic solver.
4. **Statistics.** None reported: no error bars, tests, seeds, repeats or rewording checks. The
   LLM's seat and the starting leader are fixed (from the deal files).
5. **Headline numbers.**
   - Good side (Table 3, p.8), win rate and deduction accuracy:
     - Servant bot: 38.2 and 71.8.
     - GPT-3.5 with discussion: 22.2 and 76.0.
     - GPT-3.5 without discussion: 11.1 and 60.7.
   - Abstract (p.1): ChatGPT as good "got a win rate of 22.2%", against 38.2% for the bot.
   - Self-play (p.10): "EVIL wins 83.3% of the games".
   - The authors' reading (p.10): LLMs "are able to deduce identities well based on discussion"
     but do not turn that into better decisions.
6. **Data and code.** The repository has no licence (the GitHub API reports none). It contains deal
   specifications only, such as `{"num_players":5,"quest_leader":0,"role_names":[...]}`. No game
   logs are released.
7. **For Inside Job.**
   - This is the nearest precedent for "stated belief versus a constraint solver". With discussion,
     the LLM's deduction accuracy (76.0) beat the solver bot's (71.8) while its win rate was lower.
     That is the same split CLAIMS.md expects between Read and winning.
   - With 30 games, a fixed seat, and no spread or proper scoring rule, it shows the gap Inside Job
     means to close.
   - Self-play balance was 83/17. Side balance needs tuning before any per-side metric is
     informative.

### A2. Avalon's Game of Thoughts (ReCon)

1. **Citation and what we have.** S. Wang et al., "Avalon's Game of Thoughts: Battle Against
   Deception through Recursive Contemplation", arXiv 2310.01320 v3 (24 Oct 2023), preprint.
   - Full text: https://arxiv.org/pdf/2310.01320 → `sources/recon`.
   - Repository https://github.com/Shenzhi-Wang/recon: README and run script only. The README
     names a later ACL 2024 Findings version, which we did not fetch.
2. **Game and set-up.**
   - Six-player Avalon: "1 Merlin, 1 Percival, 1 Morgana, 1 Assassin, and 2 Loyal Servants" (p.17).
   - Models: ChatGPT (GPT-3.5/GPT-4) and Claude-2 (p.11).
   - Opponents are a fixed method. When ReCon plays good, the evil side uses chain-of-thought (CoT)
     (p.6).
   - In the main runs ReCon drafts with GPT-3.5 and refines with GPT-4, while the CoT baseline is
     all GPT-3.5 (p.18).
   - The number of games per condition is not stated anywhere we could find.
3. **What was measured.**
   - Success rate per side.
   - GPT-4 pairwise preference judging of utterances on six dimensions, over "20 full Avalon games"
     (p.7).
   - Agents keep private first- and second-order beliefs, but these are not scored.
4. **Statistics.**
   - None reported. "Significantly" is used without a test.
   - Wording sensitivity is visible in Table 1 (p.9): adding human-like speech lowers success from
     83.3% to 70.0%.
5. **Headline numbers.**
   - CoT on both sides: "15.0% for the good side and 85.0% for the evil side" (p.11).
   - ReCon on both sides: "19.4% for the good side and 70.6%" for evil (p.11).
6. **Data and code.** Code only, with no licence. No logs are released.
7. **For Inside Job.**
   - A known pitfall: the test method used a stronger model than its baseline.
   - Game counts are missing, and a style change in the prompt moved success by 13 points. That
     supports the reworded-prompt check.

### A3. Werewolf Arena

1. **Citation and what we have.** S. Bailis, J. Friedhoff, F. Chen (Google Research), "Werewolf
   Arena: A Case Study in LLM Evaluation via Social Deduction", arXiv 2407.13943 v1 (18 Jul 2024).
   No venue is stated.
   - Full text: https://arxiv.org/pdf/2407.13943 → `sources/werewolfarena`.
   - Repository https://github.com/google/werewolf_arena (Apache-2.0): README, `runner.py` and
     `logging.py` read.
2. **Game and set-up.**
   - Eight players: 1 Seer, 1 Doctor, 2 Werewolves, 4 Villagers (p.2).
   - Models: Gemini 1.5 Pro, Gemini Pro and Flash, GPT-4, GPT-4o and GPT-3.5.
   - One model plays a whole side.
   - "Each pairing engaged in 10 games", 5 per side, plus "5 games of self-play" (p.5).
   - Speaking order is decided by bidding.
3. **What was measured.**
   - Villager win ratio per pairing.
   - Seer statistics such as reveal rate and backfire rate. Reveals were detected by an LLM (p.7).
   - "Synthetic votes" after each utterance, which do not affect play (p.5). These work as a belief
     probe.
   - Voting entropy.
   - A Monte Carlo baseline with no talk, in which Villagers "win a mere 1.2% of 100,000 simulated
     games" (p.1).
4. **Statistics.**
   - The authors say "the number of games limits statistical significance" (p.6) and that 10 games
     per pair "may not provide statistically robust results" (p.8).
   - One figure (Fig. 7, p.13) has standard-error bars.
   - Names are drawn randomly "from a pool of 17 names" (p.2), and the order of names in voting
     prompts is randomised (p.3).
   - The code assigns roles with an unseeded `random.shuffle`.
   - Self-play balance is used as a sanity check: 40–60% for all models except GPT-3.5 (p.5).
5. **Headline numbers.**
   - Fig. 5 (read from the image, p.5): Gemini 1.5 Pro villagers against GPT-4 wolves won 0.80. The
     reverse pairing won 0.40. Each cell is 5 games, so values move in steps of 0.2.
   - Table 1 (p.7), "Unmasked Wolf (%)" by model: 61.1, 26.7, 14.3, 75.0, 55.0, 38.5.
   - No spread is reported.
6. **Data and code.** Code only. The code writes JSON logs per game, but no logs are in the
   repository.
7. **For Inside Job.**
   - Name randomisation is a weaker form of codenames.
   - Fixed role sides per model pair, 5 games a cell, and no intervals: the authors themselves flag
     this as not robust.
   - The 1.2% no-talk baseline is the kind of null that the Bluff and Read floor tests formalise.

### A4. Exploring LLMs for Communication Games: Werewolf

1. **Citation and what we have.** Y. Xu et al. (Tsinghua), arXiv 2309.04658 v2 (11 May 2024). No
   venue is stated in the text.
   - Full text: https://arxiv.org/pdf/2309.04658 → `sources/xu_werewolf`.
   - Repository https://github.com/xuyuzhuang11/Werewolf (MIT): tree only.
2. **Game and set-up.**
   - Seven players: "two werewolves, two villagers, a witch, a guard, and a seer" (p.2).
   - All players are gpt-3.5-turbo-0301.
   - Roles are randomly assigned each game, and talking order is random (p.5).
   - Each experiment runs 50 games ("rounds" in the paper, p.6).
   - The werewolves are kept without the learning pools so that they stay constant, "serving as a
     reference" (p.5).
3. **What was measured.**
   - Villager win rate and game length (figures only).
   - Human-judged share of reasonable outputs.
   - Qualitative behaviours.
   - No beliefs are scored.
4. **Statistics.**
   - None reported.
   - The authors note that the fixed-reference assumption "may not hold true" (p.6): werewolf
     behaviour changed as the villagers learned. The conclusion asks for "an invariant baseline"
     (p.11).
   - Renaming roles (e.g. "werewolf" to "pretty girl") was checked qualitatively only (p.8).
5. **Headline numbers.** Win rates appear only in line plots (Fig. 3). There are no text values to
   quote.
6. **Data and code.** Code only (MIT). No logs were found.
7. **For Inside Job.**
   - This is the clearest statement of a risk in the trial design. A "fixed" reference model is
     fixed in weights, not in behaviour, because it reacts to the test model.
   - The Bluff score is defined as the reference crew's reaction, so this is part of the
     construct. It should be said so in CLAIMS.md.

### A5. Learning to Discuss Strategically: One Night Ultimate Werewolf

1. **Citation and what we have.** X. Jin et al., arXiv 2405.19946 v2. Page 1 reads "38th
   Conference on Neural Information Processing Systems (NeurIPS 2024)".
   - Full text: https://arxiv.org/pdf/2405.19946 → `sources/onuw`.
   - Repository https://github.com/KylJin/Werewolf: tree only, no licence.
2. **Game and set-up.**
   - A three-player version for theory. The main experiments use five players with role swaps at
     night.
   - Models: GPT-4-1106 and Gemini-pro.
   - "We repeat the game 30 times" per evaluation (p.8).
   - Section 6.3 uses two predefined deals, where role assignment and night actions are fixed (p.9).
   - Section 6.4 always seats the test agent "as Player 3" (p.10), against fixed opponent agents.
3. **What was measured.**
   - Win rate and average votes received.
   - NashConv against a perfect Bayesian equilibrium in the three-player game: an equilibrium
     reference.
   - Beliefs are generated by the model but not scored.
4. **Statistics.** None reported: 30 games a cell, no spread. Fixed deals and a fixed seat are used
   on purpose.
5. **Headline numbers.** Table 1 (p.10), win rate and average votes against Gemini-based
   opponents:
   - ReAct: "0.40 1.23"
   - RL-instructed: "0.70 1.10"
6. **Data and code.** Code only. We did not establish whether logs are released.
7. **For Inside Job.**
   - Identical predefined deals across conditions are the same idea as "same deals for every
     model".
   - Fixing one seat, as here, is what Inside Job's seat rotation avoids.

### A6. Hoodwinked

1. **Citation and what we have.** A. O'Gara, "Hoodwinked: Deception and Cooperation in a Text-Based
   Game for Language Models", arXiv 2308.01404 v2 (Aug 2023).
   - Full text: https://arxiv.org/pdf/2308.01404 → `sources/hoodwinked`.
   - Repository https://github.com/aogara-ds/hoodwinked (MIT): we opened `results/0.csv` and one
     job file.
2. **Game and set-up.**
   - One killer among innocents in a house. A discussion and vote follow each murder.
   - Models: GPT-3 Ada, GPT-3 Curie, GPT-3.5, GPT-4.
   - One model plays the killer and another plays all innocents.
   - "Each matchup has a sample size of either 50 or 100 games" (p.4).
3. **What was measured.**
   - How often the killer is banished.
   - Vote accuracy of eyewitnesses against non-witnesses. Ground truth comes from the game (who saw
     the murder).
   - The number of pairwise comparisons won by the larger model.
4. **Statistics.** None reported. Results are given as counts such as "18 of 24 pairwise
   comparisons" (p.1).
5. **Headline numbers.** For GPT-3.5, the killer was banished in 32% of games without discussion and
   43% with it (p.3). Fig. 2 is a full killer-by-innocent matrix, image only.
6. **Data and code.** The paper says "Full data available" at the repository (p.4). The repository
   holds one game: `results/0.csv`, 4 rows, one row per player. Its columns include `killer`,
   `banished`, `vote_rate_for_killer`, `witness_vote_rate_for_killer` and `story` (the full
   transcript).
7. **For Inside Job.**
   - Using model size as a rough known-strength check (larger models should beat smaller) is an
     informal version of gate G2.
   - The data promised in the paper is not in the repository, which is a reason to publish logs
     with the release, not after.

### A7. Among Us: A Sandbox for Measuring and Detecting Agentic Deception

1. **Citation and what we have.** S. Golechha, A. Garriga-Alonso, arXiv 2504.04072 v3. Page 1
   footer: "39th Conference on Neural Information Processing Systems (NeurIPS 2025)".
   - Full text: https://arxiv.org/pdf/2504.04072 → `sources/amongus_sandbox`.
   - Code at https://github.com/7vik/AmongUs (CC0-1.0).
   - HuggingFace dataset `7vik/AmongUs`, 575 MB in total. We opened all five `summary.json` files,
     four experiment-detail files, and one agent log of about 68 MB.
2. **Game and set-up.**
   - Seven players: "5 crewmates and 2 impostors" (p.3). This is the same split as Inside Job.
   - Models get only the rules, with no examples.
   - Experiment A: "We run 400 games with 100 pairs of impostors and crewmates" (p.4). Each cell is
     one model as both impostors against another model as all crew (Llama-3.3-70b and Phi-4).
   - Experiment B: "2054 games with 7 players randomly initialized" from 18 models (p.6), so
     tables are mixed at random.
3. **What was measured.**
   - Per-game win or loss, turned into a "Deception Elo" for impostors and a "Detection Elo" for
     crew. "K = 32", starting at 1500 (p.5).
   - An LLM judge (GPT-4o-mini) scores each step 1–10 for lying, deception and so on. Those scores
     are the labels used to train linear probes on Phi-4 activations.
   - The authors call the judge scores "not very well-calibrated" (p.5).
   - Players state no beliefs, and there is no scripted player.
4. **Statistics.**
   - Elo intervals by "bootstrap resampling with replacement for 1000 iterations" (p.5), shown as
     95% and 90% CIs (Fig. 2).
   - No seeds, seat or role balancing, repeats or rewording checks.
   - Our computation from the 811-game summary: in 726 games the two impostors were different
     models, so each impostor's result is mixed with its partner's.
5. **Headline numbers.**
   - Abstract (p.1): RL-trained models are "much better at producing deception than detecting it".
   - Probes reach "AUROCs over 95%" (p.1).
   - Our computation from the released 400-game summaries, impostor wins out of 100:
     - Llama impostors against Llama crew: 43.
     - Phi impostors against Llama crew: 26.
     - Llama impostors against Phi crew: 54.
     - Phi impostors against Phi crew: 43.
6. **Data and code.**
   - Released files: 400 full-game agent logs (JSON lines, one record per step) and summary files.
   - The README speaks of "810 game summaries". The Elo file we opened has 811 games from 11 models,
     not the paper's 2054 games from 18 models, so Fig. 2 cannot be rebuilt from the release.
   - Example record: `game_index` "Game 27", step 1, identity "Impostor", model "microsoft/phi-4".
     The response has the fields "Condensed Memory", "Thinking Process" and "Action" (e.g. a SPEAK
     action).
7. **For Inside Job.**
   - Same table shape (5 against 2) and the same finding direction: deception is easier than
     detection. Bluff's floor test exists because the opposite could also happen.
   - The mixed-table design is exactly what CLAIMS.md rules out for rankings. Our count of
     mixed-partner impostor games (726 of 811) shows why.
   - Released data that does not match the paper's figures is a pitfall to avoid.

### A8. AmongAgents

1. **Citation and what we have.** Y. Chi, L. Mao, Z. Tang, arXiv 2407.16521 v2. The arXiv comment
   reads "Wordplay @ ACL 2024".
   - Full text: https://arxiv.org/pdf/2407.16521 → `sources/amongagents`.
   - Repository https://github.com/cyzus/among-agents (MIT): code only.
2. **Game and set-up.**
   - "four Crewmates and one Impostor" (p.8).
   - "20 runs per setup" (p.8).
   - Four set-ups: all-random, all-GPT-3.5, LLM crew against a random impostor, and random crew
     against an LLM impostor.
   - Personalities are assigned to agents.
3. **What was measured.** How each game ended (Table 1), and GPT-4 labels of speech categories.
   Random agents are the scripted baseline.
4. **Statistics.** None reported.
5. **Headline numbers.** Table 1 (p.8) gives the share of 20 runs ending each way. The authors
   report that "over 40% of Impostors' speeches" were labelled deception (p.8).
6. **Data and code.** Code only. No logs.
7. **For Inside Job.** Twenty games per setup and personality prompts. This is a description, not a
   measurement.

### A9. Bauer, Secret Hitler (master's thesis)

1. **Citation and what we have.** N. Bauer, "Evaluating Large Language Models in a Complex Hidden
   Role Game", arXiv 2605.22826 v1 (Apr 2026). The arXiv comment reads "Master's thesis,
   University of Göttingen".
   - Full text, 56 pages: https://arxiv.org/pdf/2605.22826 → `sources/sh_bauer`.
   - Repository https://github.com/ItsNiklas/secret-hitler-player: metadata only.
2. **Game and set-up.**
   - Five-player Secret Hitler: 3 liberals, 1 fascist, Hitler.
   - One LLM plays against four reputation-based agents (Table 3 caption, p.16).
   - "each model plays at least n ≥ 100 games" (p.16). Runs lasted 48 hours each, so the counts
     differ by model.
   - Baselines: random, rule-based and reputation-based agents. Human reference games come from
     secrethitler.io.
3. **What was measured.**
   - Win rate by role.
   - Role identification accuracy (RIA): each round the model privately names every player's role.
     These are categorical answers, not probabilities.
   - Deception retention, judged by an LLM annotator.
   - A game-state impact score.
   - Agreement with human experts on decisive final rounds.
4. **Statistics.**
   - Chi-square and z-tests for chat features and game length only.
   - No intervals on win rates.
   - Roles are random. There is no seat or seed control.
   - Prompt variation is left to future work (p.31).
5. **Headline numbers.**
   - Table 3 (p.16), Llama 3.3 70B by role, overall/liberal/fascist/Hitler: "46.0% 41.3% 33.3% 84.6%".
   - On human expert decisions, Llama 3.1 70B agrees in "only a 59.7%" of cases (p.1), against 86.7%
     for the rule agent (Table, p.19).
6. **Data and code.** Code exists. No LLM game logs were found.
7. **For Inside Job.**
   - Win rates by role run from 33% to 85% for one model. That is a large role effect.
   - It supports scoring within role, as Inside Job does with its separate crew and mole trials.

### A10. ParliamentBench (Secret Hitler)

1. **Citation and what we have.** N. Bauer, J. Kaesberg, A. Aizawa, J. Wahle, B. Gipp, T. Ruas, "Can
   Agents Deceive? Evaluating Reasoning and Deception in ParliamentBench using a Social Deduction
   Game", arXiv 2607.28146 v1 (30 Jul 2026). No venue is stated.
   - Full text, 34 pages: https://arxiv.org/pdf/2607.28146 → `sources/sh_parliamentbench`.
   - Repository https://github.com/ItsNiklas/ParliamentBench (CC BY-NC-SA 4.0): README and example
     config.
2. **Game and set-up.**
   - Five-player Secret Hitler.
   - "100 games per model" against Llama 3.3 70B agents (Table 1 caption, p.6). This is a fixed
     reference opponent, as in Inside Job's trials.
   - Roles are stratified 60/20/20 (p.27). The config uses a "balanced" role schedule with seed 42.
   - Sixteen models, about 1,600 games.
   - An anchor–opponent tournament of 450 games (p.27).
3. **What was measured.**
   - Win rate.
   - Role identification accuracy (RIA), asked privately each round.
   - Deception retention, from the opponents' private questioning.
   - A game-state impact score.
   - Vote accuracy in rule-defined critical states, which gives per-decision ground truth.
4. **Statistics.** These are the closest in this list to the checks Inside Job plans.
   - **Bootstrap.** Intervals and paired tests use "B = 10,000 resamples" (p.27). Table 10 (p.28)
     gives a 95% CI for every model and role.
   - **Power.** At n = 100 the design "cannot reliably resolve overall win-rate differences below
     roughly 14 percentage points" (p.27).
   - **Opponent dependence.** The win-rate order "fully reverses" against two other opponents,
     "(τ = −1.0)" (p.27). Mean τ is +0.55 for RIA against −0.33 for win rate.
   - **Wording check.** In a neutral-vocabulary rewrite (Hitler → Saboteur, and so on), GPT-OSS
     120B's Hitler win rate "falls from 95% to 40%" (p.8). Overall win rates were unchanged.
   - **Reasoning check.** Turning reasoning off left win rate unchanged but lowered RIA (p.27).
5. **Headline numbers.**
   - Table 10 (p.28), win rate with 95% CI: GPT-5.4 81 [73, 88]; Llama 3.3 70B 58 [49, 66].
   - Baselines: algorithmic 45 [36, 54], random 33 [24, 42].
   - Per-role intervals are wide; for example, Llama as fascist is 20 [5, 40].
   - Our comparison: Kimi K2.5 scores 76 in Table 1 and 67.0 in a separate cohort (Table 11). This
     is an informal repeat that the authors note "differ slightly".
6. **Data and code.** The README says "Recorded game runs are not included". Code and analysis
   JSON are released under CC BY-NC-SA 4.0.
7. **For Inside Job.**
   - Strong support for per-decision metrics over win rate: 100 games cannot separate models closer
     than about 14 points.
   - It also warns that a ranking against one reference opponent can reverse against another.
     CLAIMS.md already limits claims to "the reference model". This is evidence that the limit
     matters in practice.
   - Role vocabulary alone moved one role's win rate by 55 points. The reworded-prompt check
     should reword role names ("mole", "crew", "sabotage"), not only style.

### A11. Cicero (Diplomacy)

1. **Citation and what we have.** Meta Fundamental AI Research Diplomacy Team (FAIR) et al.,
   "Human-level play in the game of Diplomacy by combining language models with strategic
   reasoning", Science 378, 2022.
   - science.org returned HTTP 403. The full text came from an author-hosted copy whose footer says
     it was downloaded from science.org: https://noambrown.github.io (paper PDF) →
     `sources/cicero/paper.txt`.
   - The supplementary materials came from a gwern.net mirror. This is a secondary host; we did not
     check it against the publisher's copy. → `sources/cicero/supplement.txt`.
   - Repository https://github.com/facebookresearch/diplomacy_cicero (code MIT): we downloaded the
     40 released games.
2. **Game and set-up.**
   - Seven-player Diplomacy, with no hidden roles.
   - 40 anonymous league games against 82 humans.
   - Agent-against-agent tests (supplement p.58): "40 games with agent A playing each of the seven
     powers, for a total of 280 games". That is one test agent against six copies of a reference
     agent, with all seats rotated, which is the design of an Inside Job trial.
3. **What was measured.**
   - Sum-of-squares score per game.
   - Per message, message filters and a "lie score" used to choose training data (supplement).
   - "Cicero does not explicitly" predict deception (p.6).
4. **Statistics.**
   - Supplement tables give ± values. We did not find their definition.
   - A built-in null (Table S15, supplement p.75): the score expected from equal play is "1/7 ⇡
     14.3%". Cicero against six Cicero copies scores "14.3% ± 0.0%".
5. **Headline numbers.**
   - "Cicero's mean score was 25.8%", against 12.4% for its 82 opponents (p.7).
   - Table S15 (supplement p.75): Cicero against six imitation agents scores 32.0% ± 1.7%.
   - Pitfall noted by the authors (supplement p.58): performance against imitation agents seemed
     "almost perfectly correlated" with how many messages the agent sends.
6. **Data and code.**
   - 40 redacted games, 3.2 MB of JSON. Our count: 5,924 messages.
   - Fields: `phases` (with messages, orders, results and state), `scoring_system`, and others.
   - Example message: sender GERMANY, recipient ALL, "oh lord". There are no lie labels.
   - The human training data is "NOT available" (README).
7. **For Inside Job.**
   - Cicero tested one agent against six copies of another, rotating through all seven seats. That
     is the trial design here.
   - Its "self against copies equals 1/7" result is an exact null of the kind gate G1 uses.
   - The message-count correlation is a warning that verbosity can drive scores. Inside Job's equal
     word caps address this; it should be checked in the analysis.

### A12. WOLF: Werewolf-based Observations for LLM Deception and Falsehoods

1. **Citation and what we have.** M. Agarwal et al., arXiv 2512.09187 v1 (9 Dec 2025). The PDF
   footer reads "NeurIPS 2025"; MafiaScope's bibliography gives the MTI-LLM workshop. Code
   repository (Apache-2.0).
   - Full text, 11 pages: https://arxiv.org/pdf/2512.09187 → `sources/wolf`.
   - Code repository: README, KNOWN_ISSUES.md and config read.
2. **Game and set-up.**
   - Eight players: four Villagers, two Werewolves, Seer, Doctor (p.3).
   - Roles are "not randomized across runs" (Fig. 2, p.11).
   - 100 games.
   - The paper names no model. The repository's default is gpt-4o at temperature 0.7, so it is
     probably one model in every seat.
3. **What was measured.**
   - After each statement, the speaker privately labels it deceptive or not, and every observer
     gives a suspicion value in [0, 1].
   - "Peer judgments were evaluated against self-reports as ground truth" (p.7).
   - Scored per statement with Brier, ROC AUC and AUPRC.
   - There is no solver or scripted player.
4. **Statistics.**
   - "standard error of the mean (SEM); 95% confidence intervals use the normal approximation"
     (p.9).
   - No seat or role rotation, no nulls, no rewording.
   - The counts disagree within the paper: "7,320 statements" (p.1) against "324
     deception-analysis events" (p.6).
5. **Headline numbers.**
   - "Werewolves won 70% of games (70/100), Villagers won 10%" (p.6).
   - "The self-labeled deception base rate was 69.4%" (p.6).
   - "Brier scores (0.26–0.29)" (p.8).
   - Our computation: always answering the base rate 0.694 would score a Brier of 0.694 × 0.306 ≈
     0.21. The reported suspicion therefore did worse than a constant base-rate answer.
6. **Data and code.**
   - The paper says logs "are released" (p.9). The repository holds no run logs, only a test
     fixture.
   - KNOWN_ISSUES.md lists unfixed bugs, for example that `round_num` never increments. If this was
     the code that produced the paper's runs, the per-round trends are in doubt.
7. **For Inside Job.**
   - This is the closest prior use of Brier-scored suspicion, and on our arithmetic it fails the
     null test CLAIMS.md sets for Read (a base-rate script scoring as well as real models).
   - Inside Job's "minus the solver" and "base-rate script" checks are exactly what WOLF lacked.
     The lesson is that the Read floor test may well fail.
   - Using the speaker's self-label as ground truth is weaker than Inside Job's engine-known
     roles and clue cards.

### A13. MafiaScope

1. **Citation and what we have.** I. Karpov, Grigorenko, Ayuyev, "MafiaScope: Inspecting
   Multi-Agent Reasoning in Social Deduction Games" (the earlier title spoke of "belief probing"),
   arXiv 2607.10645 v3 (30 Oct 2026). A system demonstration; no venue is stated.
   - Full text: https://arxiv.org/pdf/2607.10645 → `sources/mafiascope`.
   - Repository https://github.com/karpovilia/mafiascope (MIT): we opened the config and one game.
2. **Game and set-up.**
   - "The demonstration uses seven-player games" (p.2). The repository config has 2 Mafia, 1 Doctor
     and 4 Villagers.
   - Mostly one model in every seat (deepseek-chat), with GPT-4o-mini and Qwen3 batches.
   - A corpus of "672 games" (p.1). The findings use a "30-game" DeepSeek batch (p.5).
3. **What was measured.**
   - After every public message, each living agent answers private probes on a copy of its
     context, so the answers never enter its acting history. The probes ask for:
     - each player's role, with a confidence from 0 to 100;
     - a suspicion ranking;
     - a "social map" of who it thinks suspects it.
   - Role reports are scored against true roles. Second-order predictions are scored against the
     other agents' own reports.
   - No Brier score, no solver.
4. **Statistics.**
   - **Game-level resampling.** "Intervals resample whole games 10,000 times" (p.9).
   - **Probe-effect null test.** "Mafia wins 84/120 games with probes and 89/120 without (Fisher's
     exact p = .565)", a difference of −4.2 points with a 95% CI of −15.3 to +7.1 (p.5).
   - **Probe repeatability.** Five repeat probes at nine saved states gave "42 disagreements across
     90 answer pairs (46.7%)" (p.5). The disagreement is concentrated in introductions and night
     actions; votes and discussion gave 0 disagreements (Table 5, p.8).
   - **Context-isolation audit.** It checked 113,794 messages for leaks and found none (p.5).
5. **Headline numbers** (p.5).
   - **Overconfidence.** At confidence 80–100, "mean stated confidence is 89.6%, but accuracy is
     61.4%".
   - **Self-perception.** Agents over-predict being suspected: "The ratio is 2.63 (95%
     game-bootstrap CI [2.15, 3.25])".
   - **Reports and votes.** The latest top suspect matches the vote "176 of 204" times (86.3%),
     against 23.5% for a uniform pick.
   - **Opening round.** In the first round, "91.6% of role guesses are Unknown".
   - **Authors' cautions.** Probe answers are "sensitive to wording and potentially unfaithful"
     (p.6). An API alias such as deepseek-chat does not identify a fixed checkpoint (p.8).
6. **Data and code.**
   - The repository has 1,073 log folders, about 623 MB. We opened game 36594b66.
   - `game.jsonl` has 32 events: setup with 7 players, roles and models, through to a game_over
     record.
   - `introspection.jsonl` has 577 probe records with these fields: game_id, round,
     public_msg_seq, player_name, role, probe_id, question, answer_raw, answer_parsed,
     answer_parse_ok, latency_ms, model.
7. **For Inside Job.**
   - This is the closest existing design: 7 players, 2 hidden, private suspicion every turn,
     whole-game resampling, and a check that asking does not change play.
   - Three findings bear on Inside Job:
     - Repeated probes disagreed nearly half the time in early phases.
     - Stated confidence was badly overconfident.
     - Agents over-estimated how much they were suspected by a factor of 2.6. That is the same
       quantity as Inside Job's "Table read".
   - Inside Job asks for suspicion inside the acting turn. MafiaScope asks on a copy. Inside Job
     therefore needs its own probe-effect check, and a test–retest check on suspicion readings.
     CLAIMS.md has neither.
   - Pin model snapshots, not aliases.

### A14. Auditing Belief-Conditioned LLM Agents in Hidden-Information Social Deduction Games

1. **Citation and what we have.** Gao, Yang, Zhao, Zhang, arXiv 2607.10814 (12 Jul 2026). No venue.
   - Full text: https://arxiv.org/pdf/2607.10814 → `sources/beliefaudit`.
   - Repository https://github.com/JJJayden-Yang/ai-werewolf: no licence.
2. **Game and set-up.**
   - Werewolf with "three werewolves, one seer, one witch, one hunter, and three villagers" (p.5).
   - One model in self-play: deepseek-chat, temperature 0.6, 1,080 games (p.15).
   - Arms share seeds: the no-belief and belief arms each have 200 games on seeds 7000–7199.
3. **What was measured.**
   - A rule-based belief state given to the agent. It is "rule-weighted heuristic rather than an
     exact Bayesian posterior" with "no optimality or calibration guarantee" (p.10).
   - Brier score of that belief.
   - Hit rates.
   - Consistency between the belief and the action taken.
4. **Statistics.**
   - A paired McNemar test over the 200 shared seeds (p.16).
   - Wald 95% intervals (Table 2, p.18).
   - No multiple-comparison correction (p.17).
   - A same-configuration replica (L1) run at different concurrency.
5. **Headline numbers.**
   - Good-side win rate: 0.205 without belief, 0.390 with belief, and 0.300 in the replica of the
     belief arm (Table 2, p.18).
   - "the average Brier score is 0.160" (p.17). The pooled figure includes werewolves, who know
     their teammates.
   - Action–belief consistency is "only about 0.21" (p.18).
6. **Data.** The corpus "is being prepared as an archived release" (p.27). Not obtained.
7. **For Inside Job.**
   - Shared seeds across arms are the same idea as identical deals.
   - The replica moved good-side win rate by 9 points with the same configuration. That is a direct
     estimate of run-to-run noise, of the kind gate G3 is meant to catch.
   - Low belief–action consistency is a caution for the Read claim's second falsifier (better Read
     should go with more votes on moles).

### A15. Do LLMs Trust the Accuser or the Accusation? Measuring Belief Shifts in Werewolf

1. **Citation and what we have.** Yang, Wu, Guei, Chen, Wu, arXiv 2609.12446 v1 (11 Sep 2026). The
   project page says EMNLP 2026.
   - Full text: https://arxiv.org/pdf/2609.12446 → `sources/accuser`.
   - Data: `messages.csv` from https://github.com/rlglab/werewolf-accusation-benchmark (no licence
     shown).
2. **Game and set-up.**
   - "200 seven-player Werewolf games" (p.2), played by a pool of open models.
   - Forty model configurations then act as offline observers on frozen game states.
3. **What was measured.**
   - The observer's prior belief about accuser and target on a −3 to +3 scale, and its shift after
     an accusation.
   - Accusations were labelled by Claude Opus 4.6, with human checks on a subset (p.6).
4. **Statistics.**
   - Spearman trends and 95% CIs.
   - The authors flag a possible anchoring effect from showing the prior (p.5).
5. **Headline numbers.** Wolf-versus-villager prior separation rises "from 0.80" in the smallest
   models to about 1.3 above 10B parameters (p.3).
6. **Data.** `messages.csv`, 1,224 rows. Each row has a game id, day, accuser (role, model), target
   (true role), the utterance, and the winner.
7. **For Inside Job.** Evaluating beliefs offline on frozen game states is a way to score Read on
   identical inputs across models. It is an alternative or complement to scoring beliefs live.

### A16. Deceive, Detect, and Disclose: LLMs Play Mini-Mafia

1. **Citation and what we have.** Costa, Vicente, arXiv 2509.23023 v3 (14 May 2026), preprint.
   - Full text: https://arxiv.org/pdf/2509.23023 → `sources/minimafia`.
   - Code at an anonymous link returned HTTP 401.
2. **Game and set-up.**
   - Four players (mafioso, detective, two villagers) and a single day phase.
   - Ten models across 140 mixed-model configurations. Each was "repeated with nijk = 100 games,
     producing 14,000 unique games overall" (p.5).
3. **What was measured.**
   - Win counts, fitted by a Bayesian model of the form logit p = v(m − d).
   - Configuration-level Brier score of that fit: "0.0073, a 76.6% reduction over the constant-0.5
     baseline" (p.7).
4. **Statistics.**
   - Posterior intervals.
   - A prompt ablation: rankings correlate "0.5 ± 0.2" between the default prompt and two others,
     so "capability rankings are prompt-conditioned" (p.19).
5. **Headline numbers** (p.2).
   - Name bias: "Bob outperforming Diana by 2.20 ± 0.68 percentage points".
   - Speaking-order effect: detectives gain "7.10 ± 0.77" points when speaking last.
6. **Data and code.** Not obtained (HTTP 401).
7. **For Inside Job.**
   - Measured name and seat effects of 2–7 points support codenames and seat rotation.
   - A prompt-ranking correlation of only about 0.5 is a warning that the reworded-prompt check
     could fail.

### A17. MINDGAMES (NeurIPS 2025 competition)

1. **Citation and what we have.** MINDGAMES Organizer & Participation Teams, arXiv 2605.29512 v1
   (28 May 2026).
   - Full text, 48 pages: https://arxiv.org/pdf/2605.29512 → `sources/mindgames`.
   - HuggingFace dataset `mindgameschallenge/MGC2025` (CC-BY-4.0). We read one row through the API
     (`sources/mindgames/hf/first.json`). The 187 MB Secret Mafia file was not downloaded.
2. **Game and set-up.**
   - Secret Mafia with six players (2 Mafia, Doctor, Detective, 2 Villagers).
   - "944 submitted agents" (p.1) matched live by TrueSkill.
   - An offline protocol, MG-Ref, plays each agent against a "frozen reference pool" (p.16).
3. **What was measured.**
   - TrueSkill and reward.
   - Error attribution: games the agent broke itself against games where an opponent broke.
4. **Statistics.**
   - MG-Ref for Secret Mafia (p.47): "96 | 4 dup × 6 seat × 4 rep | ±10%". That is 96 games:
     duplicated deals, all 6 seats, 4 repeats, with a Wald interval of about ±10 points.
   - Their validity rule (p.13): if the "error rate exceeds roughly 30%" and games end early, a
     ranking measures robustness to failure rather than skill.
5. **Headline numbers.**
   - Secret Mafia had a 50.3% game-level error rate (p.2, p.11).
   - "the mafia role consistently yields positive relative win rates" (p.16).
6. **Data.** Our one row has player_game_id, env_name "SecretMafia-v0", model_name, a map from seat
   to opponent model, rewards, timestamped observations, and the end reason.
7. **For Inside Job.**
   - MG-Ref is the same plan as Inside Job's trials (frozen reference, duplicate deals, rotation
     over every seat, repeats). With 96 games it reaches only ±10 points on win rate.
   - Parse failures and broken turns must be counted and reported per model. A 2,000-token thinking
     cap makes them more likely.

### A18. SocialGym

1. **Citation and what we have.** He, Zhou, Sap (CMU), arXiv 2608.09128 v2 (9 Nov 2026).
   - Full text, 31 pages: https://arxiv.org/pdf/2608.09128 → `sources/socialgym`.
   - Repository https://github.com/Keyu-He/Social_Gym_Spartan (MIT): we downloaded
     `data/social_gym_data.zip` (14.5 MB).
2. **Game and set-up.**
   - 22 games and 10 models, with "4,588 episodes" (p.5).
   - There is no self-play. In team games one model fills every seat of a team, and "seat order is
     shuffled per episode" (p.4).
   - Werewolves is six players: 2 werewolves and 4 on the village side (from the data).
3. **What was measured.**
   - Bradley–Terry ratings by side.
   - Vote accuracy compared with random voting.
   - A "Random play" row that measures the game's built-in asymmetry.
4. **Statistics.**
   - 95% bootstrap CIs.
   - **Split-half reliability** by game family (Table 13, p.28). For hidden-role games the
     correlation with the overall ranking is 0.96 and the split-half reliability is 0.94.
   - **Seat stability.** "Ratings fit on early and late seats agree at 0.93" (p.28).
   - **Deal halves.** Ratings fit on the earlier and later halves of the deals "agree at 0.88"
     (p.28).
   - **Replay noise.** In Survivor, the "winner changes in 73% of deals" even between two plays of
     the same deal (p.27).
5. **Headline numbers.** Removing discussion raises the Werewolf side's win rate "to 73%" (p.27).
6. **Data.**
   - `episode_summary.csv` has 17,410 rows (episode, game, player, model, side, score). 270
     Werewolves episodes.
   - The transcripts are 4,588 JSON files. Each turn has the agent, the model, the full prompt, a
     JSON action (e.g. "kill Laura") and token use.
7. **For Inside Job.**
   - This paper has both a split-half check and a seat-stability check, close to gates G3 and seat
     rotation. Its hidden-role figures (0.94, 0.93) are a level to compare against.
   - The 73% winner flip on replayed deals shows that identical deals do not remove game-level
     noise. Many deals are needed.

### A19. Multicultural Spyfall

1. **Citation and what we have.** Wibowo, Elsetohy, Cui, Aji, arXiv 2601.09017 v2 (3 Nov 2026).
   - Full text: https://arxiv.org/pdf/2601.09017 → `sources/spyfall`.
   - HuggingFace dataset `haryoaw/cultural-spyfall` (MIT): one row read.
2. **Game and set-up.**
   - Five players: one model plays the four non-spies, another plays the spy.
   - "9,000 matches" (p.5). Order is shuffled and each "game is played once" (p.4).
3. **What was measured.**
   - Bradley–Terry ratings, leakage and vote entropy.
   - A 0–1 confidence is asked at the vote but not scored.
4. **Statistics.**
   - 1,000-resample bootstrap, e.g. "1136±11" (Table 1, p.4).
   - Ratings are not transitive across matchups (p.5).
5. **Headline numbers.** See Table 1. We took no further numbers.
6. **Data.** One row has game_id, entity, the non-spy model, the spy model, the winner and the
   conversation events.
7. **For Inside Job.** An example of collecting a confidence and never scoring it.

### A20. MafiaBench (website)

1. **Citation and what we have.** https://www.mafiabench.org/ (homepage HTML →
   `sources/mafiabench`). The repository https://github.com/nickslevine/mafiabench has no licence.
   The transcripts page needs JavaScript and was not read.
2. **Game and set-up.**
   - Eight players, two of them mafia, no special roles.
   - One model plays all mafia and another all town.
   - A Swiss tournament where pairs play 10 games, five on each side. 450 games in total.
   - Updated 7 April 2025.
3. **What was measured.** Elo, plus win rate as mafia and as town.
4. **Statistics.** None shown.
5. **Headline numbers.**
   - Top row: "openai/chatgpt-4o-latest 1740 81% 64%".
   - Overall mafia win rate 49.6%.
6. **Data.** Transcripts exist on a JavaScript page. Not read.
7. **For Inside Job.** Ten games a pairing with Elo and no intervals: the common public-leaderboard
   pattern Inside Job aims to improve on.

### A21. Kaggle Werewolf leaderboard and Game Arena

1. **Citation and what we have.**
   - The leaderboard page https://www.kaggle.com/benchmarks/kaggle/werewolf could not be read:
     WebFetch returned only the title, and curl got a JavaScript shell.
   - The methodology paper is "Game Arena: Strategic LLM Evaluation in Competitive Environments",
     Doerschuk-Tiberi et al., arXiv 2609.31473 v1 (25 Sep 2026). It introduces "Kaggle Game Arena"
     (p.1). Full text → `sources/gamearena`.
2. **Game and set-up.**
   - Werewolf with eight players: two Werewolves, Seer, Doctor and four Villagers (p.5).
   - Ten frontier models in a full round-robin.
   - The rules were changed for balance, and speaker and voter order "rotate each round to
     eliminate positional bias" (p.20).
3. **What was measured.**
   - A game-theoretic evaluation (GTE) that splits skill by role. The paper says raw win rates
     "conflate individual skill with role-assignment luck", and estimates the role contributions
     "across ∼31,000 games" (p.6).
4. **Statistics.**
   - Bootstrap CIs. GTE is reported to have "tighter confidence intervals" than Elo variants
     (p.21).
   - Balance table (p.20), from 500 self-play games per rule set: Villager win rate "0.734 ±
     0.039" under standard rules, down to 0.567 ± 0.043 after the changes.
5. **Headline numbers.** Leaderboard values not obtained.
6. **Data.** Trajectories are said to be hosted on Kaggle (p.14). Not downloaded.
7. **For Inside Job.**
   - Supports tuning balance dials on self-play before ranking, and modelling role separately from
     skill.
   - Shows how far standard Werewolf rules are from balanced with LLM players (73% for one side).

### A22. Bayesian Social Deduction with Graph-Informed Language Models (GRAIL)

1. **Citation and what we have.** Rahimirad et al., arXiv 2506.17788 v2. The abstract page says
   "Accepted to ACL 2026 main conference". Full text → `sources/bayes_social`.
2. **Game and set-up.**
   - Avalon with six players, 4 Good and 2 Evil, and no special roles.
   - "Each pairing was tested over 20 games" (p.5).
   - Agents: Random, ReCon, DeepSeek-R1, o4-mini and GRAIL.
   - A human study of 15 trials with three people each (p.8).
3. **What was measured.**
   - Win rate.
   - F1 of team votes, read as predictions of which teams contain Evil.
   - GRAIL keeps beliefs with a factor graph that enforces that "exactly two players are Evil"
     (p.3). The LLM only nudges the priors. The network is calibrated by temperature scaling.
   - Seat bias is removed by training on "all circular permutations of player orderings" (p.3).
4. **Statistics.**
   - Figure 2 has error bars, which "indicate SE" (p.6).
   - The human study reports p = 0.054 with a 95% credible interval (p.8).
5. **Headline numbers.**
   - GRAIL's good-side win rate averages 0.75 across opponents (Table 1, p.4).
   - In the human study, GRAIL won 67% against 27% for a reasoning agent (p.8).
6. **Data.** A HuggingFace dataset and code are linked from the project page. Not opened.
7. **For Inside Job.** An existing logic/probabilistic solver for a two-hidden-player game,
   producing per-player probabilities. It is a direct model for Inside Job's solver baseline.

### A23. Strategist (brief)

1. **Citation and what we have.** Light et al., arXiv 2408.10635 (ICLR 2025 per the repository).
   Full text → `sources/strategist`.
2. **Set-up.** "30 games" against humans (p.6).
3. **What was measured.** Win rate, against humans and in round-robins between strategies.
4. **Statistics.** Table 1 (p.7) reports a "Standard Error 0.089 0.061". The limitations section
   says "individual runs can have high variance", reduced by reusing "the same seed functions"
   (p.20).
5. **Headline numbers.** See Table 1 (p.7). We took no further numbers.
6. **Data and code.** Code in the jonathanmli/Avalon-LLM repository. Not opened for this paper.
7. **For Inside Job.** More evidence that single runs are noisy.

---

## Part B. Human hidden-role and deception datasets

### B1. It Takes Two to Lie: One to Lie, and One to Listen (Diplomacy)

1. **Citation and what we have.** D. Peskov, B. Cheng, A. Elgohary, J. Barrow, C.
   Danescu-Niculescu-Mizil, J. Boyd-Graber, ACL 2020.
   - Full text: https://aclanthology.org/2020.acl-main.353.pdf → `sources/ittakestwo`.
   - Data from https://github.com/DenisPeskoff/2020_acl_diplomacy (CC BY 4.0), linked from
     go.umd.edu/diplomacy_data: the train, validation and test JSONL files (3.2 MB), downloaded and
     opened.
2. **Game and set-up.**
   - Twelve human Diplomacy games. Players were paid at least $40, with a bonus for successful lies
     (p.4).
   - "Some players repeat between games" (p.6).
3. **What was measured.**
   - Every message carries two labels: the sender's own "ACTUAL LIE" label and the receiver's
     "SUSPECTED LIE" label.
   - The task metric is F1 on lies.
4. **Statistics.** None reported for results.
5. **Headline numbers.**
   - "Close to five percent of all messages" are lies (p.5).
   - "Humans spot 88.3% of lies", and humans "have a 22.5 Lie F1" (p.6).
   - Our computation from the data:
     - 17,289 messages in 252 dialogues; 887 lies (5.1%).
     - Of the 802 lies with a receiver annotation, 111 were caught (13.8%).
     - On the test games, receiver accuracy over all messages is 88.4%. So the paper's "88.3%"
       appears to be accuracy over all messages, not the share of lies caught.
6. **Data.**
   - One dialogue per line, with these fields: messages, sender_labels, receiver_labels, speakers,
     receivers, seasons, years, game_score, game_id.
   - Example: Italy to Germany, spring 1906. The sender label is false (a lie) and the receiver
     label is true (believed).
7. **For Inside Job.**
   - A human per-message baseline for lie detection: about 5% of messages are lies, and people
     caught about 14% of them.
   - Inside Job's true/false tags on claims are the same design as the sender labels. Clue cards
     add engine-checked truth, which this dataset lacks.

### B2. Werewolf Among Us

1. **Citation and what we have.** B. Lai et al., arXiv 2212.08279 v1 (Dec 2022). A revised version
   appeared in Findings of ACL 2023.
   - Both PDFs → `sources/werewolf_among_us`.
   - The original data site does not resolve. The GitHub README (SALT-NLP/PersuationGames) points
     to HuggingFace `bolinlai/Werewolf-Among-Us` (Apache-2.0 tag, about 9.9 GB, mostly video). We
     downloaded about 1 MB of vote and role files plus the README.
2. **Game and set-up.**
   - Humans playing One Night Ultimate Werewolf: "40 games" from Ego4D plus 8 Avalon games, and
     "151 clips" from YouTube (p.3).
   - Four to six players per game.
3. **What was measured.** Persuasion strategy per utterance, and voting outcome and roles per game.
   There are no per-utterance lie labels.
4. **Statistics.** "three random seeds", reported as mean ± std (p.6).
5. **Headline numbers.** Vote prediction "F1 of 32.7%" against 28.6% for random (p.9).
6. **Data.**
   - Each game record has playerNames, votingOutcome, startRoles, endRoles and a warning field.
   - Our counts: YouTube 151 games, all with votes; Ego4D 48 games, 35 with votes.
7. **For Inside Job.** A human source of "who voted for the werewolf", but with night role swaps and
   no lie labels.

### B3. Putting the Con in Context (Mafia)

1. **Citation and what we have.** S. Ibraheem, G. Zhou, J. DeNero, NAACL 2022, arXiv 2207.02253.
   Full text → `sources/con_in_context`.
2. **Game and set-up.**
   - "460 English-speaking participants" from Mechanical Turk (p.3).
   - "Forty-four of these Mafia games" were used, with 4–10 players and 1–2 mafia each.
3. **What was measured.** Text classifiers that rank players by probability of being mafia. "we
   ignore voting behavior" (p.4).
4. **Statistics.** None reported. Training on 39 games and evaluation on 5 (p.7).
5. **Headline numbers.** Table 2 (p.7): accuracy 0.74 for the best model against 0.62 for random.
   Mafia were "twice as likely to win" as bystanders (p.9).
6. **Data.** The paper says it releases records, but gives no link. No copy was found on the ACL
   Anthology, GitHub or HuggingFace. Not obtained.
7. **For Inside Job.** A human Mafia set with two hidden players, but too small and unreleased to
   compare against.

### B4. Long-Horizon Dialogue Understanding for Role Identification in Avalon

1. **Citation and what we have.** Stepputtis et al. (CMU), arXiv 2311.05720 v1. The repository says
   EMNLP 2023 Findings.
   - Full text → `sources/avalon_roleid`.
   - One game file from https://github.com/sstepput/Avalon-NLU (MIT), opened.
2. **Game and set-up.** "20 carefully collected and labeled games among human players" (p.1), six
   players each.
3. **What was measured.**
   - F1 of role identification by LLM observers, against human players' own stated beliefs.
   - Players' beliefs were recorded during play.
4. **Statistics.**
   - "Models are evaluated ten times on the six test games" (p.7), means only.
   - A seat effect: identifying good players is easier if Merlin is among the first three speakers,
     "(p-value 0.039)" (p.7).
5. **Headline numbers.**
   - Human baseline in Table 2 (p.7).
   - "Seven of the 20 games were won by the good players" (p.6).
6. **Data.** Twenty JSON games, about 1.1 MB. Each holds users and roles, messages, `beliefs`
   (player, about_player, belief, quest, turn) and persuasion labels.
7. **For Inside Job.** Evidence of a speaking-order effect in human play. It is also the only
   released source of human in-game stated beliefs that we found.

---

## Part C. Critique of game-based LLM evaluation

### C1. Auditing Game-Theoretic Measures of Strategic Reasoning in LLMs

1. **Citation and what we have.** Pechon-Elkins, Chun, arXiv 2603.10029 (25 Feb 2026). Full text →
   `sources/gtaudit`. The Zenodo data (10.5281/zenodo.21943627) was not opened.
2. **Scope.** Not a social-deduction paper. It audits game benchmarks in general.
3. **Findings.**
   - A token limit made "some models to return empty answers that parsers silently replaced" with
     fixed actions (p.1).
   - Wins over models that were silently playing defaults "inflated survivors' RSR ratings by
     43–176 points" (p.10).
   - A Hoeffding bound of "n ≥ 356 games per pairing" to detect a 50-point Elo difference (p.7).
   - Prompt framing raised one model's bluff rate "from 0.08 to 0.65–0.67" (p.1).
   - The paper calls for a "powered, preregistered" framing study (p.11).
4. **For Inside Job.**
   - Inside Job's 2,000-token thinking cap at effort "low" is exactly the condition this paper
     found producing empty answers.
   - Every fallback action needs to be logged, counted per model, and excluded from scores or
     reported beside them.

### C2. Other papers that report reliability problems (cross-references)

- ParliamentBench (A10): power of about 14 points at 100 games, opponent reversal, and a role-name
  effect.
- Mini-Mafia (A16): name and order effects, and a prompt-ranking correlation of 0.5.
- MINDGAMES (A17): error-confounded rankings.
- SocialGym (A18): a 73% winner flip on replays.
- MafiaScope (A13): 46.7% disagreement between repeat probes.
- Werewolf Arena (A3): the authors call 10 games per pair not robust.
- Xu et al. (A4): the reference side drifted.
- We found no paper whose main subject is a critique of social-deduction benchmarks in particular.

---

## Part D. Human split or steal

All Golden Balls papers use the same broadcast run (2007–2009), so their samples overlap and are
not independent. The finale payoffs match Inside Job's pot of 100 in proportion: half each if both
split, all to a lone stealer, nothing if both steal.

### D1. van den Assem, van Dolder and Thaler, "Split or Steal?" (2012)

1. **Citation and what we have.** M. J. van den Assem, D. van Dolder, R. H. Thaler, "Split or Steal?
   Cooperative Behavior When the Stakes Are Large", Management Science 58(1):2–20, 2012.
   - Full published PDF: https://repub.eur.nl/pub/31292/SplitorSteal_2012.pdf →
     `sources/vdassem2012`. The journal page is the PDF page plus 1.
2. **Game and set-up.**
   - Golden Balls finale. The paper calls it a "weak" prisoner's dilemma, because stealing is only
     weakly dominant (p.2).
   - 574 finalists in 287 episodes, aired June 2007 to December 2009 (p.4).
   - Mean jackpot £13,416, median £4,300, range £2.85 to £100,150 (Table 1, p.5).
   - There is a short free talk before the choice.
3. **What was measured.**
   - Probit of the split decision, one row per contestant.
   - Errors clustered by episode.
   - No beliefs were elicited. Expectation-based conditional cooperation is tested through the
     opponent's promise and traits.
4. **Statistics.** N = 574, 287 clusters, in every model.
5. **Headline numbers.**
   - **Overall:** "52.8% of the contestants decide to split" (p.5).
   - **Outcomes:** both split 31%, one each 44%, both steal 25% (p.5).
   - **Stakes:** up to £500, "people on average cooperate 73.4%". The rate "drops to approximately
     45%" and is flat above £1,500 (p.9).
   - **"Big peanuts" (p.11):** in early episodes, doubling the maximum possible jackpot raises
     cooperation "by more than 12 percentage points". The effect fades over the run.
   - **Reciprocity:** if the opponent voted against you earlier, cooperation "plummets by
     approximately 21 percentage points" (p.13). Only 28 contestants were in that position.
   - **Own promise:** about 53% made an explicit promise to split (p.13). Promisers are "about 31
     percentage points more likely" to split (p.14).
   - **Opponent's promise:** no increase in splitting, and even a marginal decrease (p.14).
   - **Earlier lies:** 41% lied in round 1 (p.15), and the opponent's past lies do not affect
     cooperation (p.15).
   - **Gender and age:** young men cooperate less, and this reverses with age (p.7).
6. **Released data.** No data statement in the paper. The INFORMS supplement page returned HTTP
   403. Searches of Harvard Dataverse and Zenodo found nothing. Not obtained.
7. **For Inside Job.**
   - A human split rate of about 53% (N = 574) is the obvious comparison for the finale. CLAIMS.md
     says the finale is not a claimed skill.
   - Players' promises predict their own choice but not their opponent's. That is a testable
     pattern for the public pitches before the finale.

### D2. Burton-Chellew and West (2012)

1. **Citation and what we have.** M. N. Burton-Chellew, S. A. West, "Correlates of Cooperation in a
   One-Shot High-Stakes Televised Prisoners' Dilemma", PLoS ONE 7(4): e33344, 2012.
   - Full PDF from journals.plos.org → `sources/burtonchellew2012`.
   - The PMC copy showed a reCAPTCHA, which was not attempted.
2. **Game and set-up.**
   - 143 episodes and 286 contestants, from series 1–3 (aired March 2007 to May 2008), after
     exclusions (p.3).
   - Mean stake £14,094, range £3 to £93,250 (p.4).
3. **What was measured.**
   - A logistic GLM per decision with errors clustered by episode.
   - Stated intentions taken from pre-show interviews.
4. **Statistics.** N = 286 in 143 clusters. Wald χ² tests.
5. **Headline numbers.**
   - "Fifty percent of the 286 contestants chose 'split'" (p.4).
   - Outcomes: "39 episodes of split:split, 39 of steal:steal, and 65 of split:steal". This is what
     independent choices would give (p = 0.554).
   - Contestants were more likely to steal when stakes were larger (Wald χ² = 5.98, p = 0.014).
   - **Stated intentions:** 148 of 252 interviewed stated a plan, and "Seventy percent ... (104 of
     148) were true to their stated intentions" (p.4).
   - **Promises:** promisers split more (χ² = 21.10, p < 0.001). The effect on the opponent was
     "marginally non-significant" (p = 0.060).
   - **Laughter:** contestants who started laughter split more (p = 0.002).
   - **Lies:** overall no effect. Contestants who inflated their cash balls (N = 30) received less
     cooperation (p = 0.037).
6. **Released data.** No supporting-information files and no data statement. Not obtained.
7. **For Inside Job.**
   - The 70% match between stated plan and action is a human figure to compare against Inside
     Job's confessional-versus-choice consistency.
   - The pair outcomes look independent, which matches the "split/split as chance" null.

### D3. Turmunkh, van den Assem and van Dolder, "Malleable Lies" (2019)

1. **Citation and what we have.** U. Turmunkh, M. J. van den Assem, D. van Dolder, "Malleable Lies:
   Communication and Cooperation in a High Stakes TV Game Show", Management Science
   65(10):4795–4812, 2019.
   - Publisher version from https://research.vu.nl (VU portal PDF) → `sources/turmunkh2019`.
2. **Game and set-up.**
   - "The data set used for this study covers 284 episodes", with 568 contestants.
   - Mean jackpot £13,510, median £4,325.
3. **What was measured.**
   - Each contestant's statements were coded on two axes: explicit or implicit, and unconditional
     or conditional. The three authors coded them independently.
   - Logit average marginal effects, with errors clustered by episode.
4. **Statistics.** N = 568, 284 clusters, in every model.
5. **Headline numbers.**
   - "Approximately half (52%) cooperate" (p.7, journal p.4799).
   - **Split rate by type of statement made** (p.7–8):

     | Statement made | Split rate |
     |---|---|
     | Explicit unconditional | 67% |
     | Implicit unconditional | 58% |
     | Explicit conditional | 59% |
     | Both implicit and conditional | 49% |
     | None of the four types | 31% |

   - **Who made which statements** (Table 1, p.8): 37.9% made at least one explicit unconditional
     statement, and 16.9% made no statement of any type.
   - Opponents' statements had no effect on a contestant's own choice (Table 5, p.14).
6. **Released data.** The paper says data are supplemental material at the DOI
   (https://doi.org/10.1287/mnsc.2018.3159). INFORMS returned HTTP 403. The HAL record has no file;
   SSRN and CORE returned 403. Not obtained.
7. **For Inside Job.** A coding scheme for finale pitches that could be applied to model pitches:
   explicit promise, hedged promise, conditional promise, or empty talk. The human split rates by
   type give a reference.

### D4. Darai and Grätz (University of Zurich working papers)

1. **Citation and what we have.** Curl to ZORA and EconStor hit a bot check; the PDFs came via
   WebFetch from EconStor.
   - (a) D. Darai, S. Grätz, "Golden Balls: A Prisoner's Dilemma Experiment", SOI working paper
     1006 (2010), 52 pages → `sources/darai/goldenballs2010`.
   - (b) "Facing a Dilemma: Cooperative Behavior and Beauty", UZH Econ working paper 82 (revised
     2012) → `sources/darai/attraction2012`.
   - (c) A 2011 conference version of (a) → `sources/darai/vfs2011`.
2. **Game and set-up.**
   - (a): 222 episodes, final-round N = 444, jackpot £3 to £100,150.
   - (b): 211 episodes, 422 finalists.
3. **What was measured.**
   - Probits with errors clustered by episode.
   - (a) also uses private pre-show intended strategies and an "expected jackpot" variable.
4. **Statistics.** (a) Table 3: N = 441 in 222 clusters.
5. **Headline numbers, (a).**
   - "We observe an average cooperation rate of 54.5%".
   - Mutual cooperation 33.3%, and split/steal 42.3%.
   - Cooperation falls "from 73.6% for jackpots below £500 to roughly 50%" above £500.
   - A handshake alone lowers splitting. A promise combined with a handshake raises it (Table 3).
   - (b) reports a 54% split rate.
6. **Released data.** None. The data came from Endemol UK (paper (a)).
7. **For Inside Job.** Confirms the pattern: about 54% split, and much more cooperation for small
   jackpots.

### D5. Oberholzer-Gee, Waldfogel and White, Friend or Foe? (working paper, 2003)

1. **Citation and what we have.** F. Oberholzer-Gee, J. Waldfogel, M. White, "Social Learning and
   Coordination in High-Stakes Games: Evidence from Friend or Foe", NBER WP 9805 (2003).
   - Full text: https://www.nber.org/system/files/working_papers/w9805/w9805.pdf → `sources/ogw2010`.
   - The published version (Review of Economics and Statistics 92(1), 2010) was not obtained (MIT
     Press returned 403).
2. **Game and set-up.**
   - Friend or Foe? (US, Game Show Network): "315 games" and "630" contestants (p.3).
   - Stakes $200 to $16,400.
   - Season 1 was taped before the show aired; season 2 after.
   - Partners answer trivia together before the choice.
3. **What was measured.** Probits with errors clustered on the pair. No beliefs.
4. **Statistics.** Season 1: 240 contestants. Season 2: 390 contestants (Table 2a, p.36).
5. **Headline numbers.**
   - Table 2a (p.36), foe rate: "54.8%" overall (N = 630), 49.2% in season 1 and 58.2% in season 2.
   - So the friend rate is 45.2% overall (our arithmetic).
   - Pairs (Table 4, p.39): foe–foe 31.7%, friend–friend 22.2%, one each 46.0%.
   - "Stakes are not significant in any of the equations" (p.25).
   - The introduction gives a figure for "friend" that contradicts Table 2a. We use the table.
6. **Released data.** None in the paper.
7. **For Inside Job.** Cooperation fell once players could watch earlier episodes. Repeated
   exposure changes behaviour, which matters if models have seen Golden Balls clips or analyses in
   training.

### D6. List, Friend or Foe? (working paper, 2006)

1. **Citation and what we have.** J. A. List, "Friend or Foe? A Natural Experiment of the Prisoner's
   Dilemma", NBER WP 12097 (2006).
   - Full text: https://nber.org/system/files/working_papers/w12097/w12097.pdf → `sources/list2006`.
   - The published Review of Economics and Statistics 88(3) version was not obtained.
2. **Game and set-up.** Season 1 only: 234 players in 117 games (p.8). Stakes $200 to $16,400.
   Partners chose each other.
3. **What was measured.** An ordered probit on team outcome. Clustering is not reported.
4. **Statistics.** N = 234.
5. **Headline numbers.**
   - "50 percent of subjects chose to cooperate" (p.9).
   - "Result 1: Stakes do not have an important effect on play" (p.13).
   - Table 1 (p.23) splits cooperation by gender and age.
6. **Released data.** None.
7. **For Inside Job.** Stakes do not matter in this range. Inside Job's pot is fixed at 100, so
   stakes are not a factor anyway.

### D7. Kalist, Friend or Foe dataset (Journal of Statistics Education)

1. **Citation and what we have.** D. E. Kalist, Journal of Statistics Education dataset,
   https://jse.amstat.org/v12n3/datasets.kalist.html.
   - The documentation, data file and codebook were downloaded and opened (`sources/kalist`).
   - No licence is stated. The page says the text may be shared but not republished without
     consent.
2. **Game and set-up.**
   - 76 episodes (28 from season 1, 48 from season 2), taped from August 2002 to March 2003
     (documentation §2).
   - 227 games and 454 contestants.
3. **What was measured.** Kalist's own analysis uses a linear probability model and a probit on foe
   (Table 3, N = 454).
4. **Statistics.** No clustering.
5. **Headline numbers (our computation from the data file).**
   - Friend share is 207 of 454 (45.6%): 88 of 166 (53.0%) in season 1 and 119 of 288 (41.3%) in
     season 2.
   - Pairs: friend–friend 52 of 227 (22.9%), one each 103 (45.4%), foe–foe 72 (31.7%).
6. **Released data.**
   - Tab-separated text, 227 rows plus a header, one row per game with both players.
   - Columns: male, white, age, foe, round2, round3, season2, cash, male1, white1, age1, foe1, win,
     win1.
7. **For Inside Job.** The only human split-or-steal data we could actually open. It is small and
   from the US show, but usable as a reference distribution.

### D8. Later work

- **Serra-Garcia and Gneezy, "Improving Human Deception Detection Using Algorithmic Feedback",
  CESifo WP 10518** (August 2024 version) → `sources/later/cesifo10518`.
  - Sample: "430 contestants across 217 episodes" (p.15) of Golden Balls.
  - Contestants "elect steal 46% of the time" (p.6), so 54% split.
  - Human observers "correctly guess the decisions of contestants 53.5% of the time" (p.26). A
    machine-learning model reached "AUC of 0.71" (p.26).
  - Its experiments were pre-registered on aspredicted.org (p.19). No data release is mentioned.
- **Brams and Mor, MPRA paper 97604 (2019)** → `sources/later/brams_mor`. A game-theoretic analysis
  of one episode. It has no new data, and its outcome shares are cited from D1 (secondary).
- **Checked and set aside:**
  - Schniter and Shields, Evolutionary Human Sciences 2024 (`sources/later/ehs2024`): a lab
    prisoner's dilemma, not the TV show.
  - Dobson and Goddard, Review of Economic Analysis 2018 (`sources/later/twohalves2018`): football
    data.
- **Found but not readable:** two later journal papers named in searches, in Decision Support
  Systems (2023, doi 10.1016/j.dss.2023.113997) and the Journal of Behavioral and Experimental
  Economics (2026, doi 10.1016/j.socec.2026.102570). We found no open copy. Their content is not
  used here.

---

## (a) Comparison table: LLM benchmarks

Column meanings:

- **Per-decision metric:** something scored per vote, utterance or belief report, not only per
  game.
- **Null test:** a check where the right answer is known to be "no effect" or a fixed value. Examples
  are self against copies, asking against not asking, and a random baseline used as a floor.
- **Known-skill check:** scripted or baseline players whose order is known, compared in the
  results.
- **Repeatability:** the same configuration run again, or split-half agreement.

"Partly" means something close but weaker. The source of each cell is in that benchmark's entry
above.

| Benchmark | Games per condition | Opponent design | Per-decision metric | Error bars | Null test | Known-skill check | Repeatability | Pre-registration | Logs released |
|---|---|---|---|---|---|---|---|---|---|
| AvalonBench (A1) | 30 (GPT-3.5), 10 (Llama2), 60 self-play | Fixed rule bots; LLM in a fixed seat | Partly (per-game deduction accuracy from stated probabilities) | No | No | Partly (rule bot as reference, 1000 games) | No | No | No (deal files only) |
| ReCon (A2) | Not stated | Fixed CoT opponent side | Yes (judged utterances) | No | No | No | No | No | No |
| Werewolf Arena (A3) | 10 per pair (5 per side), 5 self-play | One model per side, round-robin | Partly (synthetic votes, Seer statistics) | One figure only | Partly (1.2% random-play baseline) | No | No | No | No |
| Xu et al. Werewolf (A4) | 50 | All GPT-3.5, werewolves held fixed | No | No | No | No | No | No | No |
| ONUW (A5) | 30 | Fixed opponent agents, fixed deals and seat | Partly (votes received) | No | No | Partly (equilibrium in 3-player game) | No | No | Not established |
| Hoodwinked (A6) | 50 or 100 | One model as killer, another as all innocents | Yes (witness vote accuracy) | No | No | Partly (larger models expected stronger) | No | No | Claimed; 1 game in repository |
| Among Us sandbox (A7) | 100 per cell (400); 2054 mixed | One model per side (400); random mixed tables (2054) | Yes (judge scores per step) | Yes (bootstrap) | No | No | No | No | Yes (400 logs; summaries do not match paper) |
| AmongAgents (A8) | 20 | All GPT-3.5, or LLM against random agents | Partly (speech labels) | No | Partly (all-random games) | No | No | No | No |
| Bauer Secret Hitler (A9) | ≥100 (varies) | One LLM against 4 reputation agents | Yes (RIA per round) | No (tests on side metrics only) | No | Partly (random, rule, reputation; agreement with experts) | No | No | No |
| ParliamentBench (A10) | 100 (60/20/20 by role) | Fixed reference model (Llama 3.3 70B) | Yes (RIA; vote accuracy in critical states) | Yes (bootstrap, B = 10,000) | Partly (neutral rewrite; reasoning off) | Partly (random 33 < algorithmic 45) | Partly (second cohort) | No | No |
| Cicero (A11) | 280 bot games (40 × 7 seats); 40 human games | One agent against 6 copies, all seats rotated | Partly (message filters) | Yes (±, undefined) | Yes (self against copies = 1/7) | Partly (imitation agents) | No | No | Yes (40 human-league games) |
| WOLF (A12) | 100 | Probably one model in all seats | Yes (Brier per statement) | Yes (SEM, normal CI) | No | No | No | No | Claimed; not in repository |
| MafiaScope (A13) | 30-game case study; 120 per arm | One model in all seats | Yes (probes after every message) | Yes (game bootstrap, Wilson) | Yes (probe against no probe) | No | Yes (repeat probes) | No | Yes (1,073 log folders) |
| Belief audit (A14) | 200 per arm, shared seeds | Self-play, one model | Yes (belief Brier, hit rates) | Yes (Wald, McNemar) | Yes (no-belief arm) | No | Yes (replica arm) | No | Not yet |
| Accuser (A15) | 200 games, observers offline | Pool of models; frozen states | Yes (per accusation) | Yes (CIs) | No | No | No | No | Partly (messages.csv) |
| Mini-Mafia (A16) | 100 per configuration (140 configurations) | Mixed-model tables | No (per game) | Yes (posterior) | No | No | Partly (prompt ablation) | No | No (link 401) |
| MINDGAMES (A17) | MG-Ref 96 (4 dup × 6 seats × 4 reps) | Frozen reference pool, all seats | No | Yes (Wald ±10%) | No | No | Partly (4 repeats in protocol) | No | Yes (parquet) |
| SocialGym (A18) | 270 Werewolves episodes (4,588 total) | One model per team, seat order shuffled | Yes (vote accuracy) | Yes (bootstrap) | Yes (random play row) | No | Yes (split-half 0.94; seat halves 0.93) | No | Yes (transcripts) |
| Spyfall (A19) | 9,000 total, each game once | One model as all non-spies, another as spy | No | Yes (bootstrap) | No | No | No | No | Yes |
| MafiaBench (A20) | 10 per pairing | One model per side, Swiss | No | No | No | No | No | No | JavaScript page, not read |
| Game Arena Werewolf (A21) | ~31,000 games in all; 500 per balance setting | Round-robin, order rotated | No (per game) | Yes (bootstrap) | No | No | No | No | Said to be on Kaggle; not checked |
| GRAIL (A22) | 20 per pairing | Pairings and mixed teams | Yes (vote F1 per round) | Yes (SE) | Partly (random agent) | Partly (random agent at 0) | Partly (20 resampled subsets) | No | Linked; not opened |

No LLM benchmark we read reports pre-registration. The only pre-registrations found were in the
human Golden Balls experiments (D8) and as a recommendation in C1.

## (b) Human split or steal: side by side

The Golden Balls rows overlap: they draw on the same 2007–2009 broadcasts.

| Source | Show | Share who split / play friend | Sample | Pair outcomes (both split / one / both steal) | Location |
|---|---|---|---|---|---|
| van den Assem et al. 2012 (D1) | Golden Balls | 52.8% | 574 contestants, 287 episodes | 31% / 44% / 25% | p.5 |
| Same, jackpot ≤ £500 | Golden Balls | 73.4% | subset (size in Fig. 2 only) | — | p.9 |
| Burton-Chellew & West 2012 (D2) | Golden Balls | 50% | 286 contestants, 143 episodes | 39 / 65 / 39 episodes | p.4 |
| Turmunkh et al. 2019 (D3) | Golden Balls | 52% | 568 contestants, 284 episodes | — | p.7 |
| Same, after an explicit unconditional promise | Golden Balls | 67% | 215 contestants made one (Table 1) | — | p.7 |
| Same, no statement of any type | Golden Balls | 31% | 96 contestants (Table 1) | — | p.8 |
| Darai & Grätz 2010 (D4a) | Golden Balls | 54.5% | 444 contestants, 222 episodes | 33.3% / 42.3% / 24.3% | text; Table 11 |
| Same, jackpot < £500 | Golden Balls | 73.6% | subset | — | text |
| Darai & Grätz 2012 (D4b) | Golden Balls | 54% | 422 contestants, 211 episodes | 32% / — / 25% | p.9 |
| Serra-Garcia & Gneezy 2024 (D8) | Golden Balls | 54% (46% steal) | 430 contestants, 217 episodes | — | p.6, p.15 |
| Oberholzer-Gee et al. 2003 (D5) | Friend or Foe? | 45.2% (season 1: 50.8%; season 2: 41.8%) | 630 contestants, 315 games | 22.2% / 46.0% / 31.7% | Tables 2a, 4 |
| List 2006 (D6) | Friend or Foe? (season 1) | 50% | 234 players, 117 games | — | p.9 |
| Kalist data (D7, our computation) | Friend or Foe? | 45.6% (season 1: 53.0%; season 2: 41.3%) | 454 contestants, 227 games | 22.9% / 45.4% / 31.7% | data file |

What predicts splitting, across sources:

- **Own promise.** A contestant's own explicit promise is the strongest predictor of their own split:
  +31 points in D1, and 67% against 31% in D3.
- **Opponent's statements.** The opponent's promise or statements do not raise splitting (D1, D2,
  D3).
- **Stakes.** Small jackpots raise splitting. Above a few hundred pounds the rate is flat at about
  45–50% (D1, D4). In Friend or Foe? stakes did not matter (D5, D6).
- **Prior hostility.** An earlier vote against you by the opponent lowers splitting by about 21
  points (D1).
- **Age.** Older contestants split more (D1, D2).
- **Independence.** Pair outcomes are consistent with the two players choosing independently (D2).

## (c) Could not obtain

- **Data for van den Assem et al. 2012 (D1).** The paper has no data statement. The INFORMS
  supplement page returned HTTP 403. Harvard Dataverse and Zenodo searches found nothing.
- **Data for Turmunkh et al. 2019 (D3).** The paper says the data are at
  https://doi.org/10.1287/mnsc.2018.3159. INFORMS returned 403 to both curl and WebFetch. HAL has
  no file; SSRN and CORE returned 403.
- **Data for Burton-Chellew & West (D2).** The article has no supporting-information files. The PMC
  copy showed a reCAPTCHA, which we did not attempt; the PLoS PDF was used instead.
- **Data for Darai & Grätz (D4).** None released. ZORA and EconStor bot checks blocked curl; the
  PDFs came via WebFetch.
- **Published versions of Oberholzer-Gee et al. (2010) and List (2006).** MIT Press returned 403.
  The NBER working papers were used, and the published numbers may differ.
- **Two later Friend or Foe / Golden Balls journal papers** (Decision Support Systems 2023; Journal
  of Behavioral and Experimental Economics 2026). No open copy found.
- **Cicero paper from the publisher.** science.org returned 403. An author-hosted copy was used,
  and the supplement came from a third-party mirror. The model weights were not downloaded.
- **"Putting the Con in Context" dataset (B3).** No link in the paper, the ACL Anthology, GitHub or
  HuggingFace.
- **Werewolf Among Us (B2).** The original site does not resolve and the Wayback Machine blocked
  requests. The HuggingFace mirror was used; the videos (about 9.9 GB) were not downloaded.
- **Kaggle Werewolf leaderboard values (A21).** The page is JavaScript-only (tried WebFetch and
  curl).
- **MafiaBench transcripts (A20).** JavaScript-only page.
- **Mini-Mafia code (A16).** The anonymous repository returned HTTP 401.
- **WOLF logs (A12).** Claimed in the paper; not in the repository.
- **Belief-audit corpus (A14).** Not yet released.
- **Hoodwinked full results (A6).** Claimed; the repository holds one game.
- **Werewolf Arena logs (A3).** None in the repository.
- **AvalonBench and ReCon logs (A1, A2).** None released.
- **ParliamentBench and Bauer game logs (A9, A10).** The README says runs are not included.
- **Not fully opened.** Among Us (A7): only one of the four large agent logs. MINDGAMES (A17): the
  187 MB Secret Mafia file, read through one API row only. Game Arena trajectories (A21). GRAIL
  data (A22). The ONUW and Xu et al. repositories (A4, A5), tree only. The ReCon ACL 2024 version
  (A2).
- **Figure-only numbers.** Werewolf Arena Fig. 5, ReCon Fig. 4, ONUW Fig. 5 and Hoodwinked Fig. 2
  have no text layer. Where we give these numbers, they were read from rendered page images.

## (d) Findings that argue against Inside Job's current design or claims

1. **The Read floor test may fail.**
   - WOLF (A12) is the only prior Brier-scored suspicion we found. Its 0.26–0.29 is worse than the
     ≈0.21 a constant base-rate answer would score (our arithmetic).
   - MafiaScope (A13) found stated confidence of 89.6% with 61.4% accuracy.
   - CLAIMS.md already makes "a base-rate script scores as well as the median model" a falsifier
     for Read. The prior evidence says that outcome is likely, not remote.
2. **Suspicion readings are noisy and possibly reactive, and CLAIMS.md has no check for either.**
   - MafiaScope's repeated probes on the same state disagreed in 46.7% of pairs (A13).
   - MafiaScope asks on a copy of the context. Inside Job asks inside the acting turn, so asking may
     change play.
   - A test–retest check on suspicion readings and an asked-against-not-asked check are missing
     from the gates.
3. **One fixed reference model can decide the ranking.**
   - ParliamentBench's win-rate order "fully reverses" against two other opponents (A10).
   - Xu et al. found the "fixed" reference side changed behaviour in response to the other side
     (A4).
   - CLAIMS.md scopes claims to the reference model. Bluff and Table read are both defined by the
     reference crew's reactions, so a second reference model should be run before any claim is
     described as a model trait.
4. **Wording effects can be very large, especially role names.**
   - ParliamentBench: one role's win rate went from 95% to 40% after renaming roles (A10).
   - Mini-Mafia: rankings correlate only about 0.5 across prompts (A16).
   - gtaudit: one model's bluff rate went from 0.08 to 0.65 with framing (C1).
   - The reworded-prompt check should change role and action names ("mole", "sabotage", "crew"),
     and CLAIMS.md should expect it might fail.
5. **The thinking cap and parse fallbacks can create fake skill differences.**
   - gtaudit (C1) found token caps producing empty answers that parsers silently replaced, which
     inflated survivors' ratings by 43–176 points.
   - MINDGAMES (A17) found rankings confounded when error rates are high.
   - CLAIMS.md fixes a 2,000-token thinking cap and effort "low" but does not mention parse
     failures. Fallback rates should be reported per model and per metric, with a threshold that
     voids a trial.
6. **Many deals are needed, even with identical deals.**
   - ParliamentBench could not resolve win-rate differences under about 14 points at 100 games
     (A10).
   - MINDGAMES' 96-game seat-rotated protocol gives about ±10 points (A17).
   - SocialGym saw the winner change in 73% of replays of the same Survivor deal (A18).
   - The belief-audit replica moved win rate by 9 points (A14).
   - Per-decision metrics help, but CLAIMS.md does not yet state how many deals a trial needs or
     what interval width it targets.
7. **Stated beliefs may not drive actions.** The belief-audit paper found action–belief consistency
   of about 0.21 (A14). MafiaScope found 86.3% agreement between the top suspect and the vote
   (A13). The evidence is mixed. Read's second falsifier ("better Read goes with more crew votes on
   moles") will decide it for Inside Job and should be computed per decision as well as per deal.
8. **"Table read" has a known bias to calibrate against.** MafiaScope's agents over-predicted being
   suspected by a factor of 2.63 (A13). Inside Job's Table read compares mole estimates with the
   crew's stated suspicion. A model with this bias would score badly for a reason unrelated to
   reading the table. A calibration-only baseline, such as a constant scaled estimate, should be
   added to the "constant answer" null.
9. **Side balance.**
   - Werewolves won 70% in WOLF (A12).
   - Evil won 83% in AvalonBench self-play (A1).
   - Villagers won 73% under standard Game Arena rules (A21).
   - Mafia won 70% in the MafiaScope probe test (A13).
   - LLM games are often lopsided. CLAIMS.md's choice of the dial setting with the widest spread
     between scripts (G2), even if one side wins more, is consistent with this, but a floor on
     Getaway is likely to bind (Among Us found deception easier than detection, A7).
10. **Human split rates are not comparable without care.** CLAIMS.md makes no human claim, and
    this list supports keeping it that way.
    - Human rates sit near 50–55% (Golden Balls) and 45–50% (Friend or Foe?), but the shows differ
      from Inside Job:
      - Real money is at stake.
      - The finalists are strangers rather than one model playing both.
      - In Golden Balls, the earlier rounds include voting each other out, which lowered
        cooperation by about 21 points where it happened (D1).
    - In mole finales the two finalists are teammates, which no human dataset covers.
