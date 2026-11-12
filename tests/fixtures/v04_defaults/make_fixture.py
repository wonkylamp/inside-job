"""Regenerate the v0.4 defaults fixture. ONLY meaningful when run on the pre-v0.4 code (the code as
it was before the v0.4 dials were added): the fixture pins today's behaviour so `tests/test_v04.py`
can prove that every v0.4 dial at its default changes nothing.

    python3.11 tests/fixtures/v04_defaults/make_fixture.py

Normalisation (also applied by the test): the keys `ts`, `game_id`, `wall_s`, `latency_s` are
dropped at every depth; `game_start.config` is compared on the keys the fixture holds.
"""

from __future__ import annotations

import gzip
import json
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
sys.path.insert(0, str(ROOT))

from inside_job.bots import BotLLM, cell_stats, format_row, game_summary  # noqa: E402
from inside_job.config import config_from_dict  # noqa: E402
from inside_job.engine import Game  # noqa: E402
from inside_job.llm import MockLLM  # noqa: E402

DROP = ("ts", "game_id", "wall_s", "latency_s")
MOCK = {"pilot": [1, 2, 3], "pilot2": [1, 2]}
BOT_SEEDS = list(range(1, 13))
BOT_CELL_GAMES = 30
BOT_TYPES = ("smart", "always", "never")


def norm(x):
    if isinstance(x, dict):
        return {k: norm(v) for k, v in x.items() if k not in DROP}
    if isinstance(x, list):
        return [norm(v) for v in x]
    return x


def raw(name):
    with open(ROOT / "config" / f"{name}.toml", "rb") as f:
        return tomllib.load(f)


def mock_events(name, seed):
    cfg = config_from_dict(raw(name))
    g = Game(cfg, MockLLM(seed), seed, game_id="fixture", clock=lambda: "")
    g.run()
    return norm(g.log.events)


def bot_events(cfg, seed, moles):
    llm = BotLLM(cfg, seed, crew="logician", crew_skill=0.7, moles=moles, mole_cards="decoy")
    g = Game(cfg, llm, seed, game_id="fixture", clock=lambda: "")
    g.run()
    return g.log.events


def main():
    for name, seeds in MOCK.items():
        for s in seeds:
            with gzip.open(HERE / f"mock_{name}_s{s}.json.gz", "wt", encoding="utf-8") as f:
                json.dump(mock_events(name, s), f)
    cfg = config_from_dict(raw("pilot"))
    bots = {}
    for moles in BOT_TYPES:
        evs = {s: norm(bot_events(cfg, s, moles)) for s in BOT_SEEDS}
        rows = [game_summary(bot_events(cfg, s, moles)) for s in range(1, BOT_CELL_GAMES + 1)]
        st = dict(cell_stats(rows), cell={}, games_per_s=0.0)
        bots[moles] = {"events": evs, "rows": rows, "row_line": format_row(st)}
    with gzip.open(HERE / "bots_pilot_skill07.json.gz", "wt", encoding="utf-8") as f:
        json.dump(bots, f)
    print("wrote", sorted(p.name for p in HERE.glob("*.gz")))


if __name__ == "__main__":
    main()
