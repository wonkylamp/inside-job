"""The ideal reasoner (SPEC section 11): which mole sets are consistent with what is known.

Pure functions, no model calls. Used by the `solve` balance command, the scripted bots and,
later, the stats page as the ceiling for Read.

A *world* is a frozenset of `num_moles` player names. The reasoner is a ceiling, not a player:
it assumes crew cards are honest (a card binds every world in which its speaker is crew) and
does no reading of behaviour.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field
from itertools import combinations

from .clues import card_as_clue, clue_is_true, draw_recipients, generate_clue
from .log import visible_events

# A card is (speaker, clue dict); a job is (team, sabotages).
Card = tuple
Job = tuple


def _base_ok(w: frozenset, revealed: dict, jobs) -> bool:
    for name, role in revealed.items():
        if (role == "mole") != (name in w):
            return False
    for team, sab in jobs:
        if sab and sum(1 for t in team if t in w) < sab:
            return False
    return True


def table_worlds(players, num_moles: int, revealed: dict, cards, jobs) -> list[frozenset]:
    """Every mole set consistent with public information.

    `revealed`: eliminated name -> "mole" | "crew". `cards`: [(speaker, clue)] tabled in public.
    `jobs`: [(team, sabotages)]. A card binds only the worlds in which its speaker is not a mole
    (a mole's cards bind nothing in the world where they are a mole); a blown job with s
    sabotages needs at least s members of the world on its team.
    """
    out = []
    for c in combinations(players, num_moles):
        w = frozenset(c)
        if not _base_ok(w, revealed, jobs):
            continue
        if all(spk in w or clue_is_true(clue, w) for spk, clue in cards):
            out.append(w)
    return out


def player_worlds(players, num_moles: int, revealed: dict, cards, jobs, *, player: str,
                  own_clues=(), pair_cards=()) -> list[frozenset]:
    """`table_worlds` plus what one player privately knows: "I am not a mole", their own real
    clues, and the cards they were shown in whispers (which bind like public cards)."""
    own = [c for c in own_clues if c.get("kind") != "none"]
    out = []
    for w in table_worlds(players, num_moles, revealed, list(cards) + list(pair_cards), jobs):
        if player in w:
            continue
        if all(clue_is_true(c, w) for c in own):
            out.append(w)
    return out


class Posterior(dict):
    """{name: probability of being a mole}, plus `consistent` (False when no world fitted every
    card and the fallback worlds were used) and `worlds` (how many worlds it averages over)."""
    consistent: bool = True
    worlds: int = 0


def posterior(worlds, players, fallback=None) -> Posterior:
    """Share of the consistent worlds containing each player (uniform over worlds).

    If `worlds` is empty (somebody on the crew side tabled a false card) and `fallback` worlds
    are given (those consistent with reveals and jobs only), they are used and `consistent` is
    False. With no worlds at all every probability is 0.
    """
    p = Posterior()
    use = list(worlds)
    p.consistent = bool(use)
    if not use and fallback is not None:
        use = list(fallback)
    p.worlds = len(use)
    for name in players:
        p[name] = (sum(1 for w in use if name in w) / len(use)) if use else 0.0
    return p


def table_posterior(inp: dict) -> Posterior:
    """Posterior for the inputs from `from_log` (table or player viewpoint), with the fallback."""
    args = (inp["players"], inp["num_moles"], inp["revealed"])
    if inp.get("player"):
        worlds = player_worlds(*args, inp["cards"], inp["jobs"], player=inp["player"],
                               own_clues=inp["own_clues"], pair_cards=inp["pair_cards"])
        fb = [w for w in table_worlds(*args, [], inp["jobs"]) if inp["player"] not in w]
    else:
        worlds = table_worlds(*args, inp["cards"], inp["jobs"])
        fb = table_worlds(*args, [], inp["jobs"])
    return posterior(worlds, inp["players"], fb)


def inputs_from_view(view: list[dict], player: str | None) -> dict:
    """Solver inputs from already-projected visible events (a player's or the public's).

    Cards: every clue card shown in a discussion statement (public), or in a v0.4 `debate`
    statement. For a player: their own clues, and cards shown to them in whispers (by the
    partner). A `vote_result` with nobody out (v0.4 `vote_nobody`: `eliminated` null) reveals nothing."""
    table = next((e for e in view if e["type"] == "table"), None)
    players = list(table["seats"]) if table else []
    num_moles = table["num_moles"] if table else 2
    revealed, cards, jobs, own, pair = {}, [], [], [], []
    for e in view:
        t = e["type"]
        if t == "vote_result" and e.get("eliminated"):
            revealed[e["eliminated"]] = e["role"]
        elif t == "job_result":
            jobs.append((list(e["team"]), e["sabotages"]))
        elif t == "clue" and player is not None and e.get("player") == player:
            own.append(e["clue"])
        elif t == "turn":
            tp = e.get("turn_phase")
            act = e.get("action") or {}
            if tp in ("discuss", "debate"):            # debate: v0.4 team_approval, also public
                cards += [(e["player"], card_as_clue(c)) for c in act.get("clue_cards") or []]
            elif tp == "whisper" and player is not None and e.get("player") != player:
                pair += [(e["player"], card_as_clue(c)) for c in act.get("clue_cards") or []]
    return {"players": players, "num_moles": num_moles, "revealed": revealed, "cards": cards, "jobs": jobs,
            "player": player, "own_clues": own, "pair_cards": pair}


def from_log(events: list[dict], upto_seq: int | None = None, viewpoint: str = "table") -> dict:
    """Solver inputs from a game log, using only events `viewpoint` may see ("table" = the
    public; or a player name), up to and including `upto_seq`."""
    evs = [e for e in events if upto_seq is None or e["seq"] <= upto_seq]
    player = None if viewpoint == "table" else viewpoint
    return inputs_from_view(visible_events(evs, player), player)


# --------------------------------------------------------------------------- the solve command

@dataclass
class SolveResult:
    rounds: int
    deals: int
    table_worlds: dict = field(default_factory=dict)   # round -> [worlds per deal]
    solo_worlds: dict = field(default_factory=dict)


def simulate_deals(cfg, deals: int = 400, rounds: int = 4, seed: int = 0) -> SolveResult:
    """Deal clues only, with the engine's recipient draw and generator (no play): each round the
    recipients are drawn, clues dealt, then the table (every crew clue pooled as an honest card)
    and one crew member alone (own clues only) are solved; then one random player leaves and
    their role is revealed. Reproduces the lead's `solve_sim.py` measurement."""
    g = cfg.game
    players = [chr(ord("A") + i) if len(cfg.players) <= 26 else f"P{i + 1}" for i in range(len(cfg.players))]
    res = SolveResult(rounds, deals, {r: [] for r in range(1, rounds + 1)}, {r: [] for r in range(1, rounds + 1)})
    for d in range(deals):
        rng = random.Random(f"{seed}:{d}")
        moles = frozenset(rng.sample(players, g.num_moles))
        alive, revealed = list(players), {}
        held = {p: [] for p in players}
        for r in range(1, rounds + 1):
            if len(alive) < 3:
                break
            for p in draw_recipients(rng, alive, g.clue_recipients, g.clue_recipients_spread):
                for _ in range(g.clues_per_round):
                    held[p].append(generate_clue(rng=rng, players=players, alive=alive, moles=moles,
                                                 num_moles=g.num_moles, recipient=p, revealed=revealed,
                                                 past_clues=held[p], strength=g.clue_strength))
            crew_cards = [(p, c) for p in players if p not in moles for c in held[p] if c["kind"] != "none"]
            res.table_worlds[r].append(len(table_worlds(players, g.num_moles, revealed, crew_cards, [])))
            crew_alive = [p for p in alive if p not in moles]
            if crew_alive:
                me = crew_alive[0]
                res.solo_worlds[r].append(len(player_worlds(players, g.num_moles, revealed, [], [], player=me,
                                                            own_clues=held[me])))
            out = rng.choice(alive)
            alive.remove(out)
            revealed[out] = "mole" if out in moles else "crew"
    return res


def solved_share(worlds: list[int]) -> float:
    return sum(1 for w in worlds if w == 1) / len(worlds) if worlds else 0.0


def format_solve(res: SolveResult, cfg) -> str:
    g = cfg.game
    rec = ("everyone" if g.clue_recipients == 0 else
           f"{g.clue_recipients} +/- {g.clue_recipients_spread} players")
    lines = [f"solve: {res.deals} deals, {len(cfg.players)} players, {g.num_moles} moles, clue_strength "
             f"{g.clue_strength}, clues to {rec}, {g.clues_per_round} per recipient; one random player "
             "leaves each round",
             "",
             f"{'round':>5}  {'table worlds':>12}  {'table solved':>12}  {'solo worlds':>11}  {'solo solved':>11}  deals"]
    for r in range(1, res.rounds + 1):
        tw, sw = res.table_worlds[r], res.solo_worlds[r]
        if not tw:
            continue
        lines.append(f"{r:>5}  {statistics.mean(tw):>12.2f}  {100 * solved_share(tw):>11.1f}%  "
                     f"{statistics.mean(sw) if sw else 0:>11.2f}  {100 * solved_share(sw):>10.1f}%  {len(tw)}")
    lines.append("")
    lines.append("table = every crew clue tabled honestly and pooled (mole cards bind nothing); "
                 "solo = one crew member's own clues. solved = exactly one consistent world left.")
    return "\n".join(lines)
