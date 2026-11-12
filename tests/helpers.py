"""Shared test helpers: configs, scripted mock policies and game runners."""

from __future__ import annotations

import copy
import random
import tomllib
from pathlib import Path

from inside_job.config import config_from_dict
from inside_job.engine import Game
from inside_job.llm import MockLLM, random_valid

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TOML = ROOT / "config" / "default.toml"
BENCH_TOML = ROOT / "config" / "bench.toml"


def raw_default() -> dict:
    with open(DEFAULT_TOML, "rb") as f:
        return tomllib.load(f)


def make_config(players=None, **game_overrides):
    raw = copy.deepcopy(raw_default())
    raw["game"].update(game_overrides)
    if players is not None:
        raw["players"] = players
    return config_from_dict(raw)


def fixed_clock():
    return "2026-01-01T00:00:00.000Z"


def run_game(seed=1, cfg=None, policy=None, log_path=None, mock_seed=None, game_id=None, trial=None):
    cfg = cfg or make_config()
    llm = MockLLM(seed if mock_seed is None else mock_seed, policy=policy)
    game = Game(cfg, llm, seed, game_id=game_id or f"g-test-s{seed}", log_path=log_path, clock=fixed_clock,
                trial=trial)
    if hasattr(policy, "bind"):
        policy.bind(game)
    game.run()
    return game, llm


class Script:
    """A mock policy whose actions are chosen by per-phase functions with access to the game.

    Each function gets (script, player, schema, prompt) and returns an `action` dict or None
    (None = random valid action). Text fields are random but valid.
    """

    def __init__(self, seed=0, **fns):
        self.rng = random.Random(seed)
        self.fns = fns
        self.game: Game | None = None

    def bind(self, game: Game):
        self.game = game

    def roles(self) -> dict:
        return {p.name: p.role for p in self.game.players}

    def alive(self) -> list[str]:
        return self.game.alive()

    def moles_alive(self) -> list[str]:
        return self.game.moles_alive()

    def crew_alive(self) -> list[str]:
        return [n for n in self.alive() if self.roles()[n] == "crew"]

    def __call__(self, model, system, prompt, schema, phase, player):
        if phase == "recap":
            return {"recap": "Things happened."}
        data = random_valid(schema, self.rng)
        fn = self.fns.get(phase)
        if fn:
            act = fn(self, player, schema, prompt)
            if act is not None:
                data["move"] = act
        return data


def action_props(schema):
    return schema["properties"]["move"]["properties"]


def suspicion_for(schema, value=50):
    return {k: value for k in action_props(schema)["suspicion"]["properties"]}


def first_of(names, pool):
    for n in names:
        if n in pool:
            return n
    return pool[0]


def vote_with(target_fn):
    def fn(s: Script, player, schema, prompt):
        others = action_props(schema)["vote"]["enum"]
        return {"vote": target_fn(s, player, others), "suspicion": suspicion_for(schema)}
    return fn


def vote_moles(s, player, others):
    return first_of(s.moles_alive(), others)


def vote_crew(s, player, others):
    return first_of(s.crew_alive(), others)


def job_choice(choice):
    return lambda s, player, schema, prompt: {"choice": choice}


def _team_spec(schema):
    t = action_props(schema)["team"]
    return t["minItems"], t["items"]["enum"]


def pick_with_mole(s: Script, player, schema, prompt):
    n, alive = _team_spec(schema)
    mole = [m for m in s.moles_alive() if m in alive][:1]
    return {"team": mole + [a for a in alive if a not in mole][: n - len(mole)]}


def pick_without_moles(s: Script, player, schema, prompt):
    n, alive = _team_spec(schema)
    crew = [a for a in alive if a in s.crew_alive()][:n]
    return {"team": crew + [a for a in alive if a not in crew][: n - len(crew)]}


def finale(choice_first, choice_second):
    """The finalist who pitched first chooses `choice_first`."""
    def fn(s, player, schema, prompt):
        order = []
        for e in s.game.log.events:
            if e["type"] == "turn" and e["turn_phase"] == "finale_pitch" and e["player"] not in order:
                order.append(e["player"])
        return {"choice": choice_first if order and player == order[0] else choice_second}
    return fn


def events_of(events, type_):
    return [e for e in events if e["type"] == type_]


def turns(events, turn_phase=None, round_=None):
    return [e for e in events if e["type"] == "turn" and (turn_phase is None or e["turn_phase"] == turn_phase)
            and (round_ is None or e["round"] == round_)]


# --------------------------------------------------------------------------- v0.4 (docs/V04.md)

class NoPromptMock(MockLLM):
    """A MockLLM that needs no prompt text, for games with v0.4 dials on (the engine refuses
    those with a prompt-needing client). With no prompt to seed from, each reply's randomness is
    seeded from the mock seed, the model and a call counter, so replies still vary."""
    needs_prompt = False

    def rng_for(self, model: str, system: str, prompt: str) -> random.Random:
        self._n = getattr(self, "_n", 0) + 1
        return super().rng_for(model, system, f"{prompt}\x00call {self._n}")


def run_game_v04(seed=1, cfg=None, policy=None, mock_seed=None, game_id=None):
    """`run_game` with a `NoPromptMock` (v0.4 dials allowed)."""
    cfg = cfg or make_config()
    llm = NoPromptMock(seed if mock_seed is None else mock_seed, policy=policy)
    game = Game(cfg, llm, seed, game_id=game_id or f"g-test-s{seed}", clock=fixed_clock)
    if hasattr(policy, "bind"):
        policy.bind(game)
    game.run()
    return game, llm
