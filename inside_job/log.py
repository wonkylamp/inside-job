"""JSONL game log and the visibility rules (SPEC section 8).

Every prompt a player receives is built from `visible_events(events, player)`, which goes
through the single gate `visible_to(event, player)` and then strips each event down to what
that player may see. `player=None` is the public audience (used for the narrator).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

COMMON = ("seq", "ts", "game_id", "round", "phase", "type", "vis")

# Turn phases whose `public` text and statement id are public.
PUBLIC_TURN_PHASES = {"pick", "discuss", "vote", "cut_pitch", "finale_pitch",
                      "debate", "final_accuse"}           # the last two: v0.4 dials only (docs/V04.md)
# Public parts of `action`, by turn phase. Everything else in a turn is private.
PUBLIC_ACTION_KEYS = {
    "pick": ("team",),
    "discuss": ("accuse", "challenges", "clue_cards", "job_claim"),
    "vote": ("vote",),
    "cut_pitch": (),
    "finale_pitch": ("stated_intent",),
    "debate": ("accuse", "challenges", "clue_cards", "approve"),
    "final_accuse": ("accuse",),
}
# Fields of a turn that may be shown to other players (for the phases above).
# (`model` is deliberately absent: in anonymised games the model id must never reach a player.
# `truncated` and `truncated_fields` are absent too: only the speaker sees them, in their own turn.)
_TURN_PUBLIC_FIELDS = ("seq", "round", "phase", "type", "turn_phase", "player",
                       "public", "statement_id", "pass", "fallback")


# Fields of a turn that no player ever sees, not even its speaker. (`rejections` can carry a
# blocked call's error text, so it is engine-side too since v0.3.)
ENGINE_ONLY_TURN_FIELDS = ("checks", "blocked", "fallback_reason", "error_kinds", "rejections")
# Engine-side fields stripped from public non-turn events (`recap`, `game_end`) in every projection:
# call accounting and failure details are for the log and the audience, never for players.
ENGINE_ONLY_EVENT_FIELDS = ("blocked", "fallback_reason", "error_kind", "error_kinds", "usage", "attempts",
                            "served_model", "latency_s", "model", "error")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class GameLog:
    """Append-only event log, mirrored to a JSONL file when a path is given."""

    def __init__(self, game_id: str, path: str | Path | None = None, clock=utc_now, listener=None):
        self.game_id = game_id
        self.listener = listener          # called with each event right after it is written
        self.path = Path(path) if path else None
        self.clock = clock
        self.events: list[dict] = []
        self._fh = None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.path, "w", encoding="utf-8")

    def write(self, *, round: int, phase: str, type: str, vis: str, **fields) -> dict:
        assert vis in ("public", "private", "pair", "engine"), vis
        if vis == "private":
            assert "player" in fields, "private events carry `player`"
        if vis == "pair":
            assert "players" in fields, "pair events carry `players`"
        ev = {"seq": len(self.events), "ts": self.clock(), "game_id": self.game_id,
              "round": round, "phase": phase, "type": type, "vis": vis}
        ev.update(fields)
        self.events.append(ev)
        if self._fh:
            self._fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
            self._fh.flush()
        if self.listener:
            self.listener(ev)
        return ev

    def close(self):
        if self._fh:
            self._fh.close()
            self._fh = None


def read_log(path: str | Path) -> list[dict]:
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


# --------------------------------------------------------------------------- visibility

def visible_to(event: dict, player: str | None) -> bool:
    """May `player` (None = public audience) see any part of `event`? The single gate."""
    if event.get("type") == "turn":
        tp = event.get("turn_phase")
        if player is not None and event.get("player") == player:
            return True                      # the speaker always sees their own whole turn
        if tp in PUBLIC_TURN_PHASES:
            return True                      # its public part
        if tp == "whisper":
            return player is not None and event.get("partner") == player
        if tp == "job":
            return player is not None and player in (event.get("shared_with") or [])
        return False
    vis = event.get("vis")
    if vis == "public":
        return True
    if vis == "private":
        return player is not None and event.get("player") == player
    if vis == "pair":
        return player is not None and player in (event.get("players") or [])
    return False                             # engine: ground truth, never shown


def public_part(event: dict) -> dict:
    """The part of a turn anyone may see (for statement phases)."""
    tp = event.get("turn_phase")
    out = {k: event[k] for k in _TURN_PUBLIC_FIELDS if k in event}
    keys = PUBLIC_ACTION_KEYS.get(tp, ())
    out["action"] = {k: v for k, v in (event.get("action") or {}).items() if k in keys}
    if tp not in PUBLIC_TURN_PHASES:
        out["public"] = ""
        out["statement_id"] = None
    return out


def project(event: dict, player: str | None) -> dict | None:
    """What `player` sees of `event`, or None. Only call after (or via) `visible_to`."""
    if not visible_to(event, player):
        return None
    if event.get("type") != "turn":
        if any(k in event for k in ENGINE_ONLY_EVENT_FIELDS):
            return {k: v for k, v in event.items() if k not in ENGINE_ONLY_EVENT_FIELDS}
        return event
    if player is not None and event.get("player") == player:
        # The speaker sees their whole turn except the engine's verdicts on it.
        return {k: v for k, v in event.items() if k not in ENGINE_ONLY_TURN_FIELDS}
    tp = event.get("turn_phase")
    if tp in PUBLIC_TURN_PHASES:
        return public_part(event)
    if tp == "whisper":
        out = {k: event[k] for k in ("seq", "round", "phase", "type", "turn_phase", "player",
                                     "partner", "public", "fallback") if k in event}
        out["action"] = {"clue_cards": (event.get("action") or {}).get("clue_cards", [])}
        return out
    if tp == "job":
        return {"seq": event["seq"], "round": event["round"], "phase": event["phase"],
                "type": "turn", "turn_phase": "job", "player": event["player"],
                "action": {"choice": event["action"]["choice"]}}
    return None


def visible_events(events: list[dict], player: str | None) -> list[dict]:
    """The only source for building a player's (or the narrator's) view."""
    out = []
    for ev in events:
        if visible_to(ev, player):
            p = project(ev, player)
            if p is not None:
                out.append(p)
    return out
