# Setup prompt for a coding agent

Paste everything inside the box below into Claude Code (or another coding agent) started in the
root of a fresh clone of this repo. It checks your machine, runs the tests and one free mock game,
opens the replay viewer, and explains how to add an OpenRouter key yourself. It makes no model
calls and spends nothing.

---

```text
Set up this repository (Inside Job, a hidden-role game that AI models play) so I can run it
locally. Work in the repo root. Read README.md first.

Hard rules for this whole task:
- Never ask me for an API key, and never type, paste, store, echo, log or print one. Do not create
  .env files or any file that could hold a key. Do not open my shell profile files (~/.zshrc,
  ~/.bashrc, ~/.zshenv, ~/.profile and the like) and do not run env, printenv, set or export with
  no arguments. If you need to know whether a key is set, use only the check in step 6, which prints
  "set" or "not set".
- Make no model calls. Every game command you run must have --mock. Do not run `claude -p`. Do not
  run preflight, or run, trial or batch without --mock, or any probes or moves command that calls a
  model. A real game uses my Claude subscription and, with other labs' models, my OpenRouter money:
  start one only after you have told me what it will cost (number of games, roughly how many model
  calls, which of them go to OpenRouter, and the --budget-usd you would set) and I have said yes.
- Always pass --out with a folder outside the repo, such as /tmp/inside-job/games. Never write into
  games/ or games_frontier/: they hold the published logs.
- Do not install anything, commit, push, or change files in the repo without asking me.

Steps:

1. Python. Run `python3.11 --version`. It must print 3.11.x. If python3.11 is missing, stop and
   tell me how I could install it on this system; do not install it yourself. The engine uses the
   standard library only, so there is nothing else to install.

2. Claude Code CLI. Run `claude --version` to check it is installed. Then run
   `claude auth status --text` and tell me only its "Login method" line, nothing else from that
   output (it also shows my email and organization). Real games call Claude models through
   `claude -p` on that login: a Claude subscription login uses my plan's usage limit; an API key
   login is billed per token. Also run
   sh -c 'if [ -n "$ANTHROPIC_API_KEY" ]; then echo "ANTHROPIC_API_KEY is set"; else echo "ANTHROPIC_API_KEY is not set"; fi'
   and, if it is set, tell me the CLI may use that key for game calls and bill it.

3. Tests. Run
   env -u OPENROUTER_API_KEY python3.11 -m unittest discover -s tests
   It takes about 3 minutes, needs no network or key, and should end with "OK" (about 540 tests).
   Report the last lines. If anything fails, show me the failure; do not change code to fix it.

4. One free mock game (scripted bots, no model calls, under a second):
   python3.11 -m inside_job run --config config/default.toml --seed 1 --mock --out /tmp/inside-job/games
   Tell me the result line and the files it wrote.

5. The replay viewer. Start it in the background:
   python3.11 -m inside_job view --latest --out /tmp/inside-job/games
   It serves http://127.0.0.1:8765 and opens my browser; if that port is busy, add --port 8780.
   Tell me the URL and how to stop it (Ctrl-C, or stop the background process). Also show me how
   to open the published games: python3.11 -m inside_job view --out games
   If you cannot keep a server running, write a single-file replay instead:
   python3.11 -m inside_job view --latest --out /tmp/inside-job/games --export /tmp/inside-job/replay.html

6. OpenRouter (other labs' models). Check whether the key is already in my environment, without
   showing it:
   sh -c 'if [ -n "$OPENROUTER_API_KEY" ]; then echo "OPENROUTER_API_KEY is set"; else echo "OPENROUTER_API_KEY is not set"; fi'
   Then explain, without doing it for me:
   - I set the key myself by adding `export OPENROUTER_API_KEY=...` to my own shell profile and
     opening a new terminal, or for one command only by putting `OPENROUTER_API_KEY=...` in front
     of it (that saves it in my shell history). The code reads only that environment variable; it
     does not read .env files. The key must never go in a file inside the repo.
   - A real game with an OpenRouter seat will not start without the key and a spend budget
     ([openrouter] budget_usd in the config, or --budget-usd on the command). Show me the mock
     version of such a game, and run it:
     python3.11 -m inside_job run --config config/bluff_kimi.toml --seed 101 --mock --budget-usd 0.50 --out /tmp/inside-job/games
   - What real games cost is in README.md ("What it cost here") and docs/OPENROUTER.md.

7. Finish with a short summary: what passed, what failed or is missing, where the mock game and
   viewer are, and the exact command for a small real game (README.md, "Play a real game with your
   Claude subscription"), with its expected cost. Do not run it.
```
