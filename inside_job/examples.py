"""Regenerate docs/example_prompts.md (`python3.11 -m inside_job examples`).

Plays a mock game whose players speak a few scripted English lines, so the prompts read like a
real game, and writes out the system prompt, one turn prompt and its schema exactly as a real
model would receive them. (Stage 1 produced the file with an equivalent one-off script; this is
that script made into a command.)
"""

from __future__ import annotations

import json
import random

from . import RULES_VERSION
from .config import load_config
from .engine import Game
from .llm import MockLLM, random_valid
from .prompts import NARRATOR_SYSTEM
from .schemas import WIRE_MOVE

DISCUSS = [
    "That job was {res} with {a} on it. My clue says at least one of {a} and {b} is a mole. Explain yourselves.",
    "{a} is fishing. I'd look hard at whoever picked that team, and {b} has been very quiet.",
    "I'm not buying {a}'s story. Their whisper partner went silent the moment the team was named.",
    "Slow down. Nobody has put a clue card down yet. Mine points away from {a}; I want to hear from {b}.",
    "{a}, you pushed for that team and now you're pushing on {b}. Pick a lane.",
]
WHISPER = [
    "Between us: my clue points away from you. What did you get?",
    "I trust you more than {a}. Want to vote together on {a} if the job goes bad?",
    "Fine, deal. But if you put a card down against me I'm done with you.",
]


class Scripted:
    """Mock policy: random valid moves (wire format), scripted English text."""

    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.game = None

    def __call__(self, model, system, prompt, schema, phase, player):
        if phase == "recap":
            return {"recap": "The leader picked a team, the job result came in, and the table argued about "
                             "who had been on it before a split vote sent one player out."}
        d = random_valid(schema, self.rng)
        g = self.game
        others = [n for n in g.alive() if n != player]
        a, b = self.rng.sample(others, 2) if len(others) >= 2 else (others[0], others[0])
        res = "blown" if any(e["type"] == "job_result" and e["round"] == g.round and e["blown"]
                             for e in g.log.events) else "clean"
        d["confessional"] = f"I think {a} is the likelier mole; {b} I can't read yet."
        d["memory"] = f"R{g.round}: suspect {a}. Watch {b}. Told nobody my clue."
        d["claims"] = []
        if phase == "discuss":
            d["public"] = self.rng.choice(DISCUSS).format(a=a, b=b, res=res)
            d["claims"] = [{"text": "my clue mentions " + a, "truthful": True}]
            d[WIRE_MOVE]["challenges"] = d[WIRE_MOVE]["challenges"][:1]
            d[WIRE_MOVE]["clue_cards"] = d[WIRE_MOVE]["clue_cards"][:1]
        elif phase == "whisper":
            d["public"] = self.rng.choice(WHISPER).format(a=a)
            d[WIRE_MOVE]["clue_cards"] = []
        elif phase == "pick":
            d["public"] = f"I'm taking {', '.join(n for n in d[WIRE_MOVE]['team'] if n != player)}. Clean hands, eyes on both."
        elif phase == "vote":
            d["public"] = f"{d[WIRE_MOVE]['vote']} has dodged every question about that job."
        elif phase in ("cut_pitch", "finale_pitch"):
            d["public"] = "I kept every promise I made at this table. Split with me."
        return d


def build(config_path: str, seed: int = 4, anonymise: bool | None = None):
    cfg = load_config(config_path)
    if anonymise is not None:
        cfg.game.anonymise = anonymise
    pol = Scripted(seed)
    mock = MockLLM(seed, policy=pol)
    game = Game(cfg, mock, seed, game_id="g-example")
    pol.game = game
    game.run()
    return game, mock


def render_examples(config_path: str = "config/default.toml", seed: int = 4) -> str:
    g, m = build(config_path, seed)
    roles = {p.name: p.role for p in g.players}
    models = {p.name: p.model_name for p in g.players}
    moles_r3 = [c for c in m.calls if c["phase"] == "discuss" and "(round 3)" in c["prompt"]
                and roles[c["player"]] == "mole"]
    c = (moles_r3 or [c for c in m.calls if c["phase"] == "discuss" and roles[c["player"]] == "mole"])[0]
    rnd = c["prompt"].split("THIS ROUND (round ")[1].split(")")[0]
    crew_sys = next(x["system"] for x in m.calls if x["player"] and roles[x["player"]] == "crew")
    crew_role = crew_sys[crew_sys.index("Your role"):crew_sys.index("How to play well")].strip()
    other_mode = not g.cfg.game.anonymise
    g2, m2 = build(config_path, seed, anonymise=other_mode)
    other_sys = next(x["system"] for x in m2.calls if x["player"])
    other_intro = other_sys.split("\n\n")[0]
    w = next((x for x in m.calls if x["phase"] == "whisper"), None)
    schema = json.dumps(c["schema"], indent=1)
    mode = "codenames" if g.cfg.game.anonymise else "real names"
    label = (lambda n: f"{n} ({models[n]})") if g.cfg.game.anonymise else (lambda n: n)
    who = label(c["player"])
    out = f"""# Example prompts (rules v{RULES_VERSION})

Generated by `python3.11 -m inside_job examples` from a `--mock` game (seed {seed},
`{config_path}`, {mode}). The mock players speak a few scripted English lines chosen at random
so the view reads like a game; their content (and the clue cards and job claims the mock plays)
is not meant to be coherent. Everything around it, the system prompt, the view layout, the phase
instruction and the schema, is exactly what a real model receives.

## 1. System prompt ({who}, a mole)

Identical for this player on every call of the game (so the CLI can cache it).

```text
{c['system']}
```

For comparison, the role section a crew player gets instead:

```text
{crew_role}
```

And the first paragraph with `anonymise = {'true' if other_mode else 'false'}`:

```text
{other_intro}
```

## 2. Turn prompt: round {rnd} discussion, {who} speaking (mole)

```text
{c['prompt']}
```

The `--json-schema` sent with this turn:

```json
{schema}
```
"""
    if w:
        out += f"""
## 3. Phase instruction for a whisper turn ({label(w['player'])})

The view above it has the same layout; only the instruction differs.

```text
{w['prompt'][w['prompt'].index('YOUR TURN'):]}
```
"""
    out += f"""
## {4 if w else 3}. Narrator system prompt

```text
{NARRATOR_SYSTEM}
```
"""
    return out
