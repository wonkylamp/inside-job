"""Per-phase reply schemas and validation (SPEC section 6).

The CLI is not trusted to enforce the schema: every reply is checked here against the same
schema (a JSON-schema subset) and the phase's semantic rules, then cleaned and truncated.
"""

from __future__ import annotations

import math
import re

PHASES = ("clue", "whisper", "pick", "job", "discuss", "vote",
          "cut_pitch", "cut_vote", "finale_pitch", "finale_choice")
# Phases where `public` must be "" (nothing is said aloud).
SILENT_PHASES = {"clue", "job", "cut_vote", "finale_choice"}
# Phases whose `public` text is a statement that gets an id.
STATEMENT_PHASES = {"pick", "discuss", "vote", "cut_pitch", "finale_pitch"}

# Phases whose action carries the private `suspicion` object (SPEC section 6).
SUSPICION_PHASES = ("clue", "whisper", "discuss", "vote")

# v0.4 turn phases (docs/V04.md), only reachable with a v0.4 dial on (and so only with the scripted
# bots or a prompt-free test client). Kept out of the tuples above, which describe v0.3 play.
V04_PHASES = ("debate", "final_accuse")
V04_STATEMENT_PHASES = {"debate", "final_accuse"}
V04_SUSPICION_PHASES = ("debate",)

# The nested per-phase object is called `move` on the wire (the schema and every prompt a model
# reads) and `action` everywhere else (engine, log, transcripts). claude-sonnet-4-5 wrapped its whole
# reply in an extra `action` object when the schema used that name; with `move` it does not.
# `clean_reply` validates the wire reply and stores the object under `action`.
WIRE_MOVE = "move"

NONE = "none"
JOB_CLAIMS = ("helped", "sabotaged", "none")


def _str(desc: str | None = None) -> dict:
    s = {"type": "string"}
    if desc:
        s["description"] = desc
    return s


def _enum(values: list[str], desc: str | None = None) -> dict:
    s = {"type": "string", "enum": list(values)}
    if desc:
        s["description"] = desc
    return s


def _obj(props: dict) -> dict:
    return {"type": "object", "additionalProperties": False,
            "required": list(props), "properties": props}


def suspicion_schema(others: list[str]) -> dict:
    """One required 0-100 integer per other alive player (SPEC section 6, Suspicion)."""
    s = _obj({n: {"type": "integer", "minimum": 0, "maximum": 100} for n in others})
    s["description"] = "private: percent for every other player still in, 0-100"
    return s


def clue_cards_schema(card_players: list[str]) -> dict:
    """0-2 formal clue claims in the clue grammar (SPEC section 6, Clue cards)."""
    from .clues import CARD_KINDS
    card = _obj({
        "kind": _enum(list(CARD_KINDS)),
        "players": {"type": "array", "items": _enum(card_players), "minItems": 1, "maxItems": 3,
                    "uniqueItems": True},
        "k": {"type": "integer", "minimum": 0, "maximum": 3,
              "description": "the k in exactly_k_of_three; 0 for other kinds"},
    })
    return {"type": "array", "items": card, "maxItems": 2,
            "description": "optional: clues you claim you were dealt, 0 to 2"}


def action_schema(phase: str, ctx: dict) -> dict:
    if phase == "clue":
        props = {}
        if ctx.get("whispers", True):
            props["whisper_with"] = _enum(list(ctx["others"]) + [NONE],
                                          "player you ask to whisper with this round, or none")
        props["suspicion"] = suspicion_schema(ctx["others"])
        return _obj(props)
    if phase == "whisper":
        return _obj({"clue_cards": clue_cards_schema(ctx["card_players"]),
                     "suspicion": suspicion_schema(ctx["others"])})
    if phase == "cut_pitch":
        return _obj({})
    if phase == "pick":
        n = ctx["team_size"]
        return _obj({"team": {"type": "array", "items": _enum(ctx["alive"]),
                              "minItems": n, "maxItems": n, "uniqueItems": True,
                              "description": f"exactly {n} different players; you may include yourself"}})
    if phase == "job":
        return _obj({"choice": _enum(["help", "sabotage"])})
    if phase == "discuss":
        ids = list(ctx["challengeable"])
        if ids:
            ch = {"type": "array", "items": _enum(ids), "uniqueItems": True,
                  "description": "ids of earlier statements this round you say are false"}
        else:
            ch = {"type": "array", "items": {"type": "string"}, "maxItems": 0,
                  "description": "no statements to challenge yet; must be empty"}
        return _obj({"accuse": _enum(list(ctx["others"]) + [NONE], "player you accuse, or none"),
                     "challenges": ch,
                     "clue_cards": clue_cards_schema(ctx["card_players"]),
                     "job_claim": _enum(list(JOB_CLAIMS) if ctx.get("on_team") else [NONE],
                                        "what you say you did on this round's job"),
                     "suspicion": suspicion_schema(ctx["others"])})
    if phase == "vote":
        # `vote_options` (v0.4 vote_nobody) adds "nobody"; absent, the options are the other players.
        return _obj({"vote": _enum(ctx.get("vote_options") or ctx["others"], "player you vote to throw out"),
                     "suspicion": suspicion_schema(ctx["others"])})
    if phase == "debate":
        ids = list(ctx["challengeable"])
        if ids:
            ch = {"type": "array", "items": _enum(ids), "uniqueItems": True,
                  "description": "ids of earlier statements this round you say are false"}
        else:
            ch = {"type": "array", "items": {"type": "string"}, "maxItems": 0,
                  "description": "no statements to challenge yet; must be empty"}
        return _obj({"accuse": _enum(list(ctx["others"]) + [NONE], "player you accuse, or none"),
                     "challenges": ch,
                     "clue_cards": clue_cards_schema(ctx["card_players"]),
                     "approve": {"type": "boolean", "description": "true to approve the proposed team"},
                     "suspicion": suspicion_schema(ctx["others"])})
    if phase == "final_accuse":
        return _obj({"accuse": _enum(ctx["others"], "player you name as a mole")})
    if phase == "cut_vote":
        return _obj({"finalist": _enum(ctx["others"], "survivor you send to the finale")})
    if phase == "finale_pitch":
        return _obj({"stated_intent": _enum(["split", "steal", "unstated"],
                                            "what you publicly say you will do")})
    if phase == "finale_choice":
        return _obj({"choice": _enum(["split", "steal"])})
    raise ValueError(f"unknown phase {phase}")


def turn_schema(phase: str, ctx: dict) -> dict:
    silent = phase in SILENT_PHASES
    claim = _obj({"text": _str(), "truthful": {"type": "boolean"}})
    claims = {"type": "array", "items": claim,
              "description": "private true/false tag for every factual claim in public"}
    if silent:
        claims["maxItems"] = 0
        public = _enum([""], "nothing is said aloud in this phase: empty string")
    else:
        public = _str("your words, seen by others" if phase != "whisper"
                      else "your whisper message, seen only by your partner")
    return _obj({
        # No description on `confessional` (V03.md section 8): that one schema string is what some
        # models' safety filters rejected; the system prompt already says what the field is.
        "confessional": _str(),
        "public": public,
        "claims": claims,
        "memory": _str("private note to your future self"),
        WIRE_MOVE: action_schema(phase, ctx),
    })


def narrator_schema() -> dict:
    return _obj({"recap": _str()})


# --------------------------------------------------------------------------- validation

def check(value, schema: dict, path: str = "reply") -> str | None:
    """Validate `value` against the JSON-schema subset we emit. Returns an error or None."""
    if "enum" in schema:
        if not isinstance(value, str) or value not in schema["enum"]:
            opts = ", ".join(repr(v) for v in schema["enum"][:12])
            return f"{path} must be one of [{opts}], got {value!r}"
        return None
    t = schema.get("type")
    if t == "object":
        if not isinstance(value, dict):
            return f"{path} must be an object"
        props = schema.get("properties", {})
        for k in schema.get("required", []):
            if k not in value:
                return f"{path} is missing '{k}'"
        if schema.get("additionalProperties") is False:
            extra = [k for k in value if k not in props]
            if extra:
                return f"{path} has unexpected keys {extra}"
        for k, sub in props.items():
            if k in value:
                err = check(value[k], sub, f"{path}.{k}")
                if err:
                    return err
        return None
    if t == "array":
        if not isinstance(value, list):
            return f"{path} must be an array"
        if "minItems" in schema and len(value) < schema["minItems"]:
            return f"{path} needs at least {schema['minItems']} items, got {len(value)}"
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            return f"{path} allows at most {schema['maxItems']} items, got {len(value)}"
        if schema.get("uniqueItems"):
            seen = []
            for v in value:
                if v in seen:
                    return f"{path} must not repeat {v!r}"
                seen.append(v)
        items = schema.get("items")
        if items:
            for i, v in enumerate(value):
                err = check(v, items, f"{path}[{i}]")
                if err:
                    return err
        return None
    if t == "string":
        if not isinstance(value, str):
            return f"{path} must be a string"
        return None
    if t == "boolean":
        if not isinstance(value, bool):
            return f"{path} must be true or false"
        return None
    if t == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return f"{path} must be a whole number"
        if "minimum" in schema and value < schema["minimum"]:
            return f"{path} must be at least {schema['minimum']}, got {value}"
        if "maximum" in schema and value > schema["maximum"]:
            return f"{path} must be at most {schema['maximum']}, got {value}"
        return None
    return None


ELLIPSIS = "…"
# A word that ends a sentence: `.`, `!` or `?`, optionally followed by closing quotes / brackets.
_SENTENCE_END = re.compile(r"[.!?][\"'”’)\]}»]*$")


def hard_cap(limit: int, grace: float) -> int:
    """The word cap the engine applies: `ceil(limit * (1 + grace))` (SPEC section 6, Limits).

    Rounded to 9 places first so float noise (60 * 1.15 = 68.99999999999999) cannot move it."""
    return max(1, math.ceil(round(limit * (1 + grace), 9)))


def truncate_words(text: str, cap: int) -> tuple[str, bool]:
    """Trim `text` to at most `cap` words (`cap` is the hard cap, grace already applied).

    Text at or under the cap is only stripped. Longer text keeps its first `cap` words, cut back
    to the last sentence end among them if that keeps at least half the cap; otherwise the `cap`
    words are kept and `…` is appended so a reader can see the cut. Returns (text, trimmed)."""
    words = text.split()
    if len(words) <= cap:
        return text.strip(), False
    kept = words[:cap]
    for i in range(len(kept) - 1, -1, -1):
        if _SENTENCE_END.search(kept[i]):
            if i + 1 >= cap / 2:
                return " ".join(kept[:i + 1]), True
            break
    return " ".join(kept) + ELLIPSIS, True


TRIMMABLE_FIELDS = ("confessional", "public", "memory", "claims")


def clean_reply(phase: str, data, schema: dict, ctx: dict, caps: dict) -> tuple[dict | None, str | None, list]:
    """Validate and normalise a reply.

    `data` is in the wire format (the move under `WIRE_MOVE`) and is checked against the wire
    schema; the cleaned reply has the move under `action`, as the engine and the log expect.
    Returns (cleaned, error, truncated_fields). `caps` has the confessional/public/memory hard word
    caps (claims use the public cap); `truncated_fields` lists the fields that were trimmed, in
    `TRIMMABLE_FIELDS` order, `[]` when none (and on an error).
    """
    if not isinstance(data, dict):
        return None, "reply must be a JSON object", []
    data = dict(data)
    # Nothing is said aloud in silent phases: coerce rather than reject a stray statement.
    if phase in SILENT_PHASES:
        if isinstance(data.get("public"), str):
            data["public"] = ""
        if isinstance(data.get("claims"), list):
            data["claims"] = []
    mv = WIRE_MOVE
    # A reply that put the move under another key (such as the log's name for it) is told the
    # wire name, which is the only name the model knows.
    if mv not in data:
        stray = [k for k, v in data.items() if isinstance(v, dict) and k not in schema.get("properties", {})]
        if stray:
            return None, (f"reply is missing '{mv}': put this phase's choices in an object named "
                          f"'{mv}', not {stray[0]!r}"), []
    # A whole number written as 70.0 is still a whole number.
    if isinstance(data.get(mv), dict) and isinstance(data[mv].get("suspicion"), dict):
        sus = {k: (int(v) if isinstance(v, float) and v.is_integer() else v)
               for k, v in data[mv]["suspicion"].items()}
        data[mv] = dict(data[mv], suspicion=sus)
    if phase in ("discuss", "debate") and isinstance(data.get(mv), dict):
        ch = data[mv].get("challenges")
        if isinstance(ch, list):
            deduped = []
            for c in ch:
                if c not in deduped:
                    deduped.append(c)
            data[mv] = dict(data[mv], challenges=deduped)
    err = check(data, schema)
    if err:
        return None, err, []
    # Semantic rules beyond the schema.
    act = data[mv]
    if phase == "whisper" and not data["public"].strip():
        return None, "your whisper message (public) must not be empty", []
    if phase == "pick":
        team = act["team"]
        if len(set(team)) != len(team) or len(team) != ctx["team_size"]:
            return None, f"team must be exactly {ctx['team_size']} different players", []
        if any(t not in ctx["alive"] for t in team):
            return None, "team may only contain players still in the game", []
    if phase in ("discuss", "debate"):
        for c in act["challenges"]:
            if c not in ctx["challengeable"]:
                return None, f"challenge {c!r} is not an earlier statement by another player this round", []
    if phase == "discuss":
        if act["job_claim"] != "none" and not ctx.get("on_team"):
            return None, "job_claim must be \"none\": you were not on this round's job", []
    if phase in ("discuss", "whisper", "debate"):
        from .clues import card_problem
        for card in act["clue_cards"]:
            err = card_problem(card, ctx["self"], ctx["card_players"])
            if err:
                return None, err, []

    trimmed = set()
    out = {}
    for key, cap in (("confessional", caps["confessional"]), ("public", caps["public"]),
                     ("memory", caps["memory"])):
        out[key], t = truncate_words(data[key], cap)
        if t:
            trimmed.add(key)
    claims = []
    for c in data["claims"]:
        text, t = truncate_words(c["text"], caps["public"])
        if t:
            trimmed.add("claims")
        if text:
            claims.append({"text": text, "truthful": c["truthful"]})
    out["claims"] = claims
    out["action"] = dict(act)              # wire `move` -> log `action`
    return out, None, [f for f in TRIMMABLE_FIELDS if f in trimmed]
