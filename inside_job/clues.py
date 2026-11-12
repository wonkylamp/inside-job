"""True-clue generator (SPEC section 5).

A world is a frozenset of `num_moles` player names that could be the moles.
"""

from __future__ import annotations

import random
from itertools import combinations

from .config import CLUE_STRENGTHS

NONE_CLUE = {"kind": "none", "players": [], "text": "No new intel this round."}

_K_WORDS = {0: "None", 1: "Exactly one", 2: "Exactly two", 3: "All three"}


def _join(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def clue_text(kind: str, players: list[str], k: int | None = None) -> str:
    if kind == "at_least_one":
        return f"At least one of {_join(players)} is a mole."
    if kind == "at_least_one_of_three":
        return f"At least one of {_join(players)} is a mole."
    if kind == "exactly_k_of_three":
        if k == 0:
            return f"None of {_join(players)} is a mole."
        if k == 1:
            return f"Exactly one of {_join(players)} is a mole."
        return f"{_K_WORDS[k]} of {_join(players)} are moles."
    if kind == "same_side":
        return f"{players[0]} and {players[1]} are on the same side."
    if kind == "different_sides":
        return f"{players[0]} and {players[1]} are on different sides."
    if kind == "not_mole":
        return f"{players[0]} is not a mole."
    if kind == "none":
        return NONE_CLUE["text"]
    raise ValueError(f"unknown clue kind {kind}")


def make_clue(kind: str, players: list[str], k: int | None = None) -> dict:
    c = {"kind": kind, "players": list(players)}
    if k is not None:
        c["k"] = k
    c["text"] = clue_text(kind, players, k)
    return c


def clue_is_true(clue: dict, moles) -> bool:
    """Pure: is this clue true if `moles` is the set of moles?"""
    moles = set(moles)
    kind = clue["kind"]
    ps = clue.get("players", [])
    n_in = sum(1 for p in ps if p in moles)
    if kind in ("at_least_one", "at_least_one_of_three"):
        return n_in >= 1
    if kind == "exactly_k_of_three":
        return n_in == clue["k"]
    if kind == "same_side":
        return (ps[0] in moles) == (ps[1] in moles)
    if kind == "different_sides":
        return (ps[0] in moles) != (ps[1] in moles)
    if kind == "not_mole":
        return ps[0] not in moles
    if kind == "none":
        return True
    raise ValueError(f"unknown clue kind {kind}")


def all_worlds(players: list[str], num_moles: int) -> list[frozenset]:
    return [frozenset(c) for c in combinations(players, num_moles)]


def consistent_worlds(*, players: list[str], num_moles: int, recipient: str,
                      revealed: dict[str, str], past_clues: list[dict]) -> list[frozenset]:
    """Worlds compatible with what the recipient knows if they were crew.

    `revealed` maps eliminated player -> revealed role ("mole" | "crew"). "I am not a mole"
    is applied for every recipient, so a mole's clues look exactly like crew clues.
    """
    out = []
    for w in all_worlds(players, num_moles):
        if recipient in w:
            continue
        ok = True
        for name, role in revealed.items():
            if (role == "mole") != (name in w):
                ok = False
                break
        if not ok:
            continue
        if all(clue_is_true(c, w) for c in past_clues):
            out.append(w)
    return out


def candidate_clues(others: list[str], num_moles: int) -> list[dict]:
    """Every clue over the given players (alive, recipient excluded), in a fixed order."""
    cands = []
    for a in others:
        cands.append(make_clue("not_mole", [a]))
    for a, b in combinations(others, 2):
        cands.append(make_clue("at_least_one", [a, b]))
        cands.append(make_clue("same_side", [a, b]))
        cands.append(make_clue("different_sides", [a, b]))
    for trio in combinations(others, 3):
        cands.append(make_clue("at_least_one_of_three", list(trio)))
        for k in range(0, min(3, num_moles) + 1):
            cands.append(make_clue("exactly_k_of_three", list(trio), k))
    return cands


def generate_clue(*, rng: random.Random, players: list[str], alive: list[str], moles,
                  num_moles: int, recipient: str, revealed: dict[str, str],
                  past_clues: list[dict], strength: str = "normal", avoid=None) -> dict:
    """Pick one true clue for `recipient` whose survival ratio is closest to the target.

    `players` is every player in seat order (worlds range over all of them); candidates are
    over alive players other than the recipient, in seat order.

    `avoid` (v0.4 `unique_clues`): clues already dealt this round. Candidates equal to one of them
    (same kind, same set of players, same k) are dropped, unless that leaves no candidate, in
    which case the choice is made as if `avoid` were not given. `None` (the default) changes nothing.
    """
    target = CLUE_STRENGTHS[strength]
    worlds = consistent_worlds(players=players, num_moles=num_moles, recipient=recipient,
                               revealed=revealed, past_clues=past_clues)
    if len(worlds) < 2:
        return dict(NONE_CLUE)
    others = [p for p in alive if p != recipient]
    real = set(moles)
    total = len(worlds)
    usable = []
    for c in candidate_clues(others, num_moles):
        if not clue_is_true(c, real):
            continue
        surviving = sum(1 for w in worlds if clue_is_true(c, w))
        if surviving == total or surviving < 2:
            continue
        usable.append((c, abs(surviving / total - target)))
    if avoid:
        taken = {clue_key(a) for a in avoid if a.get("kind") != "none"}
        fresh = [(c, d) for c, d in usable if clue_key(c) not in taken]
        usable = fresh or usable
    best: list[dict] = []
    best_d = None
    for c, d in usable:
        if best_d is None or d < best_d - 1e-12:
            best, best_d = [c], d
        elif abs(d - best_d) <= 1e-12:
            best.append(c)
    if not best:
        return dict(NONE_CLUE)
    return dict(rng.choice(best))


def clue_key(clue: dict) -> tuple:
    """Identity of a clue for `unique_clues`: kind, set of players, and k where it matters."""
    return (clue.get("kind"), frozenset(clue.get("players", [])),
            clue.get("k") if clue.get("kind") == "exactly_k_of_three" else None)


def draw_recipients(rng: random.Random, alive: list[str], recipients: int, spread: int) -> list[str]:
    """Who is dealt a clue this round (SPEC section 5, "Recipients").

    `recipients = 0` means every alive player and uses no randomness (v0.2 dealing). Otherwise
    k is drawn uniformly from [recipients - spread, recipients + spread], clamped to [0, alive],
    then k alive players are sampled. Both draws use `rng` (the deal stream) and look only at
    the alive list in seat order, never at roles. Returned in seat order.
    """
    if recipients == 0:
        return list(alive)
    k = rng.randint(recipients - spread, recipients + spread)
    k = max(0, min(k, len(alive)))
    chosen = set(rng.sample(alive, k))
    return [a for a in alive if a in chosen]


# --------------------------------------------------------------------------- clue cards

CARD_ARITY = {"not_mole": 1, "at_least_one": 2, "same_side": 2, "different_sides": 2,
              "at_least_one_of_three": 3, "exactly_k_of_three": 3}
CARD_KINDS = tuple(CARD_ARITY)


def card_problem(card: dict, speaker: str, allowed: list[str]) -> str | None:
    """Why a clue card is malformed, or None if it is well-formed."""
    kind = card.get("kind")
    if kind not in CARD_ARITY:
        return f"clue card kind must be one of {list(CARD_KINDS)}"
    ps = card.get("players")
    if not isinstance(ps, list) or len(ps) != CARD_ARITY[kind] or len(set(ps)) != len(ps):
        return f"a {kind} clue card needs exactly {CARD_ARITY[kind]} different players"
    if speaker in ps:
        return "a clue card never names its own holder"
    if any(p not in allowed for p in ps):
        return "clue card players must be other players at the table"
    k = card.get("k")
    if isinstance(k, bool) or not isinstance(k, int) or not 0 <= k <= 3:
        return "clue card k must be a whole number from 0 to 3"
    return None


def card_as_clue(card: dict) -> dict:
    """The clue a (well-formed) card claims, in the standard wording."""
    k = card["k"] if card["kind"] == "exactly_k_of_three" else None
    return make_clue(card["kind"], list(card["players"]), k)


def card_held(card: dict, received: list[dict]) -> bool:
    """Was the speaker dealt this clue? Same kind, same set of players, same k if it matters."""
    for c in received:
        if c.get("kind") != card["kind"]:
            continue
        if set(c.get("players", [])) != set(card["players"]):
            continue
        if card["kind"] == "exactly_k_of_three" and c.get("k") != card["k"]:
            continue
        return True
    return False
