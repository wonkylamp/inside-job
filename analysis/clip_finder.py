"""Clip finder: moments from finished Inside Job logs that work alone in under 40 seconds.

No model calls and no network: every clip is derived by rule from the game logs (the `.jsonl`
files listed in each folder's `index.jsonl`). Read-only on the game folders.

    python3.11 analysis/clip_finder.py [--games DIR ...] [--batch NAME ...] [--top N]
                                       [--out FILE.md] [--json FILE.json]

Default folders: `games_frontier`, then `games` (relative to the repo root). Without `--out` the
Markdown goes to stdout.

What is skipped
- index rows with `spoiled` true; logs with no `game_end` (unfinished); logs that cannot be found;
- mock games: every turn that carries a `usage` record reports zero output and zero thinking
  tokens (the engine's MockLLM; their text is canned word salad);
- any turn with `fallback` true (an engine default move, not the model speaking) is never quoted
  and never counts as evidence. A finale or vote whose deciding turn was a fallback does not fire.

Detectors (each a small pure function `detect_<kind>(game) -> [clip]`; `game` wraps one log):
- broken_promise: a finalist stated split (`finale_result.stated`, or the pitch's
  `action.stated_intent`) and chose steal while the other finalist split. Public line: their
  finale pitch. Diary: the confessional of their choice turn.
- mutual_steal: both finalists stole and nobody was paid. Speaker: the first finalist; the other
  finalist's pitch and choice diary are attached as context.
- believed_lie: a mole's public statement (pick, discuss or vote turn) carrying a claim the mole
  self-tagged `truthful: false`, in a round whose vote removed a crew member.
- right_accuser_out: a crew member who accused a real mole in discussion (`action.accuse`) or voted
  for one, and was voted out that round.
- sabotage_on_instruction: in a whisper between the two moles, one mole's message mentions
  sabotage ("sabotag..."), and the other mole sabotaged that round's job.
- invented_evidence: a mole tables a clue card (whisper or discussion) whose kind and players
  match no clue that mole was dealt in that round or earlier, the engine check says not held
  (when the check is logged), and the turn carries a self-tagged false claim.
- catch: a round whose vote removed a mole; the clip is the best-scoring crew discussion turn that
  accused that mole (crew vote speeches voting for the mole if nobody accused them).
- partner_turned: a mole accusing (`action.accuse`) or voting for their own partner.

Where a detector has several candidate lines for the same moment (the same kind, speaker and
round; for catch and sabotage_on_instruction the same round), only the best is kept: highest
score, then earliest in the log.

Quotes are verbatim: `public` is a turn's `public` field, `diary` a turn's `confessional`, never
trimmed or joined. Reading time = words in public + diary / 2.5 words per second (context lines
are reported separately as `reading_s_all` and do not count toward fits/long). A clip over 40 s is
flagged `long`, never cut.

SCORE_RULE (also printed at the top of the Markdown):
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inside_job.config import display_name  # noqa: E402

DEFAULT_DIRS = ("games_frontier", "games")
FRONTIER_FOLDER = "games_frontier"
VIEWER_PORTS = {"games_frontier": 8766}
DEFAULT_PORT = 8765
WORDS_PER_S = 2.5
CLIP_S = 40.0

KIND_WEIGHT = {
    "broken_promise": 12,
    "mutual_steal": 11,
    "invented_evidence": 9,
    "sabotage_on_instruction": 9,
    "believed_lie": 8,
    "right_accuser_out": 8,
    "partner_turned": 7,
    "catch": 6,
}
KIND_TITLE = {
    "broken_promise": "Broken promise in the finale",
    "mutual_steal": "Both steal, nobody paid",
    "believed_lie": "A lie the table believed",
    "right_accuser_out": "The right accuser voted out",
    "sabotage_on_instruction": "Sabotage on instruction",
    "invented_evidence": "Invented evidence",
    "catch": "The catch",
    "partner_turned": "Partner turned on",
}
BONUS_CONTRADICTS = 3
BONUS_FITS = 2
PENALTY_LONG = 3
BONUS_FRONTIER = 3
BONUS_ACCUSED_VICTIM = 2
BONUS_LOW_SUSPICION = 2
LOW_SUSPICION = 30.0

SCORE_RULE = f"""\
score = kind weight
  + {BONUS_CONTRADICTS} if the diary contradicts the public line (the quoted public turn carries a
      claim the speaker self-tagged false, or a finalist stated split and chose steal), and a
      diary line is present
  + {BONUS_FITS} if public + diary read in {CLIP_S:.0f} s or less (words / {WORDS_PER_S}), or
  - {PENALTY_LONG} if longer (the clip is flagged long; quotes are never cut)
  + {BONUS_FRONTIER} if the game is in the {FRONTIER_FOLDER} folder
  + {BONUS_ACCUSED_VICTIM} (believed_lie only) if the lying mole's accusation or vote in that statement named
      the crew member who went out
  + {BONUS_LOW_SUSPICION} (believed_lie only) if the crew's mean private suspicion of that mole at the vote
      was under {LOW_SUSPICION:.0f}%
Kind weights: {", ".join(f"{k} {v}" for k, v in KIND_WEIGHT.items())}.
Order: score (high first), then game id, then round, then log position (seq). No randomness."""

__doc__ += "\n" + SCORE_RULE + "\n"

PUBLIC_PHASES = ("pick", "discuss", "vote")
SABOTAGE_WORD = re.compile(r"sabotag", re.IGNORECASE)


# --------------------------------------------------------------------------- one game

class Game:
    """One game's events plus the small indexes the detectors need."""

    def __init__(self, events: list[dict], batch: str = "", folder: str = "games"):
        self.events = events
        start = next((e for e in events if e.get("type") == "game_start"), {})
        self.game_id = start.get("game_id") or next((e.get("game_id") for e in events if e.get("game_id")), "")
        self.seed = start.get("seed")
        self.batch = batch or start.get("batch") or ""
        self.folder = folder
        self.role = {e["player"]: e["role"] for e in events if e.get("type") == "role"}
        self.model = {p["name"]: p["model"] for p in start.get("players") or [] if "name" in p and "model" in p}
        for e in events:
            if e.get("type") == "turn":
                self.model.setdefault(e["player"], e.get("model", ""))
        self.moles = {n for n, r in self.role.items() if r == "mole"}
        # Every quotable turn; fallback turns are the engine speaking, so they are dropped here.
        self.turns = [e for e in events if e.get("type") == "turn" and not e.get("fallback")]
        self.fallback_turns = [e for e in events if e.get("type") == "turn" and e.get("fallback")]
        self.vote_result = self._per_round("vote_result")
        self.job_choices = self._per_round("job_choices")
        self.job_result = self._per_round("job_result")
        self.whisper_pairs = self._per_round("whisper_pairs")
        self.finale = next((e for e in events if e.get("type") == "finale_result"), None)
        self.end = next((e for e in events if e.get("type") == "game_end"), None)
        table = next((e for e in events if e.get("type") == "table"), {})
        self.pot = table.get("pot", 100)
        self.dealt: dict[str, list[tuple[int, str, frozenset, str]]] = {}
        for e in events:
            if e.get("type") == "clue":
                c = e.get("clue") or {}
                if c.get("kind") and c.get("kind") != "none":
                    self.dealt.setdefault(e["player"], []).append(
                        (e.get("round", 0), c["kind"], frozenset(c.get("players") or []), c.get("text", "")))

    def _per_round(self, t: str) -> dict:
        return {e.get("round"): e for e in self.events if e.get("type") == t}

    def turns_in(self, rnd, phases=None, player=None) -> list[dict]:
        return [t for t in self.turns
                if t.get("round") == rnd
                and (phases is None or t.get("turn_phase") in phases)
                and (player is None or t.get("player") == player)]

    def is_fallback(self, player, rnd, phase) -> bool:
        return any(t.get("player") == player and t.get("round") == rnd and t.get("turn_phase") == phase
                   for t in self.fallback_turns)

    def partner(self, mole):
        others = [m for m in self.moles if m != mole]
        return others[0] if len(others) == 1 else None

    def label(self, player) -> str:
        """`Gpt 6 Astra (Ember, crew)`: display name from the model id, then codename and role."""
        return f"{display_name(self.model.get(player, '') or player)} ({player}, {self.role.get(player, '?')})"

    def vote_outcome(self, rnd) -> str:
        v = self.vote_result.get(rnd)
        if not v:
            j = self.job_result.get(rnd)
            if j and self.end:
                return (f"No vote: job {'blown' if j.get('blown') else 'clean'} "
                        f"({j.get('sabotages', 0)} sabotage), game over, {self.end.get('winner')} win "
                        f"({self.end.get('reason')})")
            return "No vote this round"
        s = f"{self.label(v.get('eliminated'))} voted out {self.tally(rnd)}"
        if v.get("tiebreak"):
            s += f" (tie broken: {v['tiebreak']})"
        return s

    def tally(self, rnd) -> str:
        """Vote counts high to low, joined by en dashes: `4–2–1`."""
        counts = sorted((n for n in ((self.vote_result.get(rnd) or {}).get("tally") or {}).values() if n), reverse=True)
        return "–".join(str(n) for n in counts)

    def mean_crew_suspicion(self, rnd, target):
        vals = [t["action"]["suspicion"][target] for t in self.turns_in(rnd, ("vote",))
                if self.role.get(t["player"]) == "crew"
                and isinstance((t.get("action") or {}).get("suspicion"), dict)
                and target in t["action"]["suspicion"]]
        return round(sum(vals) / len(vals), 1) if vals else None


def false_claims(turn) -> list[str]:
    return [c.get("text") or c.get("claim") or "" for c in turn.get("claims") or [] if c.get("truthful") is False]


def words(text) -> int:
    return len((text or "").split())


def reading_s(*texts) -> float:
    return round(sum(words(t) for t in texts) / WORDS_PER_S, 1)


def clip(game: Game, kind: str, rnd, speaker: str, headline: str, outcome: str, *,
         public_turn=None, diary_turn=None, contradicts=False, group=None, bonuses=None,
         extra=None, facts=None) -> dict:
    public = (public_turn or {}).get("public") or ""
    diary = (diary_turn or {}).get("confessional") or ""
    extra = extra or []
    secs = reading_s(public, diary)
    return {
        "game_id": game.game_id,
        "batch": game.batch,
        "seed": game.seed,
        "round": rnd,
        "kind": kind,
        "headline": headline,
        "speaker": speaker,
        "model": game.model.get(speaker, ""),
        "model_name": display_name(game.model.get(speaker, "") or speaker),
        "role": game.role.get(speaker, ""),
        "public": public,
        "public_from": _source(public_turn) if public else None,
        "diary": diary,
        "diary_from": _source(diary_turn) if diary else None,
        "extra": extra,
        "outcome": outcome,
        "reading_s": secs,
        "reading_s_all": round(secs + sum(words(x["text"]) for x in extra) / WORDS_PER_S, 1),
        "long": secs > CLIP_S,
        "contradicts": bool(contradicts and diary),
        "facts": facts or {},
        "_bonuses": bonuses or [],
        "_group": group or (kind, speaker, rnd),
        "_seq": (public_turn or diary_turn or {}).get("seq", 0),
    }


def _source(turn) -> dict:
    return {"seq": turn.get("seq"), "phase": turn.get("turn_phase"), "player": turn.get("player")}


def context(turn, field: str, label: str) -> dict | None:
    text = (turn or {}).get(field) or ""
    if not text:
        return None
    return {"player": turn["player"], "label": label, "field": field, "seq": turn.get("seq"),
            "phase": turn.get("turn_phase"), "text": text}


# --------------------------------------------------------------------------- detectors

def _finale_turn(game, player, phase):
    return next((t for t in game.turns if t.get("player") == player and t.get("turn_phase") == phase), None)


def _stated(game, player):
    stated = ((game.finale or {}).get("stated") or {}).get(player)
    if stated in (None, "", "unstated"):
        pitch = _finale_turn(game, player, "finale_pitch")
        stated = ((pitch or {}).get("action") or {}).get("stated_intent", stated)
    return stated


def detect_broken_promise(game: Game) -> list[dict]:
    f = game.finale
    if not f or len(f.get("finalists") or []) != 2:
        return []
    a, b = f["finalists"]
    choices, pay = f.get("choices") or {}, f.get("payouts") or {}
    out = []
    for me, other in ((a, b), (b, a)):
        if choices.get(me) != "steal" or choices.get(other) != "split" or _stated(game, me) != "split":
            continue
        pitch, choice = _finale_turn(game, me, "finale_pitch"), _finale_turn(game, me, "finale_choice")
        if pitch is None or choice is None:   # missing or fallback: not the model's own move
            continue
        out.append(clip(
            game, "broken_promise", f.get("round"), me,
            f"{game.label(me)} promises to split, then takes all {pay.get(me, game.pot)} from {game.label(other)}",
            _payout_line(game), public_turn=pitch, diary_turn=choice, contradicts=True,
            facts={"stated": _stated(game, me), "choice": "steal", "other_choice": "split"}))
    return out


def detect_mutual_steal(game: Game) -> list[dict]:
    f = game.finale
    if not f or len(f.get("finalists") or []) != 2:
        return []
    a, b = f["finalists"]
    choices, pay = f.get("choices") or {}, f.get("payouts") or {}
    if choices.get(a) != "steal" or choices.get(b) != "steal" or any(pay.get(p, 0) for p in (a, b)):
        return []
    turns = {p: (_finale_turn(game, p, "finale_pitch"), _finale_turn(game, p, "finale_choice")) for p in (a, b)}
    if any(t is None for pair in turns.values() for t in pair):
        return []
    both_said_split = all(_stated(game, p) == "split" for p in (a, b))
    verb = "both promise to split and both steal" if both_said_split else "both steal"
    extra = [x for x in (context(turns[b][0], "public", "pitch"), context(turns[b][1], "confessional", "choice diary")) if x]
    return [clip(game, "mutual_steal", f.get("round"), a,
                 f"{game.label(a)} and {game.label(b)} {verb}: nobody is paid",
                 _payout_line(game), public_turn=turns[a][0], diary_turn=turns[a][1],
                 contradicts=_stated(game, a) == "split", extra=extra, group=("mutual_steal",),
                 facts={"stated": {p: _stated(game, p) for p in (a, b)}, "choices": {a: "steal", b: "steal"}})]


def _payout_line(game) -> str:
    f = game.finale or {}
    parts = [f"{game.label(p)} {f.get('choices', {}).get(p)} (said {_stated(game, p)}) gets {f.get('payouts', {}).get(p, 0)}"
             for p in f.get("finalists") or []]
    return "; ".join(parts)


def detect_believed_lie(game: Game) -> list[dict]:
    out = []
    for rnd, v in sorted(game.vote_result.items()):
        gone = v.get("eliminated")
        if game.role.get(gone) != "crew":
            continue
        susp_by_mole = {m: game.mean_crew_suspicion(rnd, m) for m in game.moles}
        for t in game.turns_in(rnd, PUBLIC_PHASES):
            m = t["player"]
            lies = false_claims(t)
            if m not in game.moles or not lies or not t.get("public"):
                continue
            act = t.get("action") or {}
            named = act.get("accuse") == gone or act.get("vote") == gone
            susp = susp_by_mole.get(m)
            bonuses = []
            if named:
                bonuses.append(("accusation named who went out", BONUS_ACCUSED_VICTIM))
            if susp is not None and susp < LOW_SUSPICION:
                bonuses.append((f"crew suspicion at the vote {susp}%", BONUS_LOW_SUSPICION))
            out.append(clip(
                game, "believed_lie", rnd, m,
                f"{game.label(m)} lies at the table and the vote removes {game.label(gone)} {game.tally(rnd)}",
                game.vote_outcome(rnd), public_turn=t, diary_turn=t, contradicts=True, bonuses=bonuses,
                facts={"false_claims": lies, "named_the_eliminated": named, "crew_suspicion_at_vote": susp,
                       "phase": t.get("turn_phase")}))
    return out


def detect_right_accuser_out(game: Game) -> list[dict]:
    out = []
    for rnd, v in sorted(game.vote_result.items()):
        c = v.get("eliminated")
        if game.role.get(c) != "crew":
            continue
        mine = game.turns_in(rnd, ("discuss", "vote"), player=c)
        named = {(t.get("action") or {}).get("accuse") for t in mine if t["turn_phase"] == "discuss"} & game.moles
        for t in mine:
            act = t.get("action") or {}
            target = act.get("accuse") if t["turn_phase"] == "discuss" else act.get("vote")
            if target not in game.moles or not t.get("public"):
                continue
            how = "names" if target in named else "votes for"
            out.append(clip(
                game, "right_accuser_out", rnd, c,
                f"{game.label(c)} {how} {game.label(target)} and is voted out {game.tally(rnd)}",
                game.vote_outcome(rnd), public_turn=t, diary_turn=t, contradicts=bool(false_claims(t)),
                facts={"accused": target, "how": t["turn_phase"]}))
    return out


def detect_sabotage_on_instruction(game: Game) -> list[dict]:
    out = []
    for rnd, wp in sorted(game.whisper_pairs.items()):
        choices = (game.job_choices.get(rnd) or {}).get("choices") or {}
        for pair in wp.get("pairs") or []:
            if len(pair) != 2 or not all(p in game.moles for p in pair):
                continue
            for a, b in (pair, pair[::-1]):
                if choices.get(b) != "sabotage" or game.is_fallback(b, rnd, "job"):
                    continue
                job_turn = next(iter(game.turns_in(rnd, ("job",), player=b)), None)
                for t in game.turns_in(rnd, ("whisper",), player=a):
                    if not SABOTAGE_WORD.search(t.get("public") or ""):
                        continue
                    extra = [x for x in (context(job_turn, "confessional", "job diary"),) if x]
                    j = game.job_result.get(rnd) or {}
                    outcome = (f"{game.label(b)} sabotaged; job {'blown' if j.get('blown') else 'clean'} "
                               f"({j.get('sabotages', 0)} sabotage)")
                    if game.end and game.end.get("rounds") == rnd and rnd not in game.vote_result:
                        outcome += f"; game over, {game.end.get('winner')} win ({game.end.get('reason')})"
                    out.append(clip(
                        game, "sabotage_on_instruction", rnd, a,
                        f"{game.label(a)} whispers partner {game.label(b)} to sabotage, and {b} does",
                        outcome, public_turn=t, diary_turn=t, contradicts=bool(false_claims(t)),
                        extra=extra, group=("sabotage_on_instruction", rnd, a, b),
                        facts={"instructed": b}))
    return out


def detect_invented_evidence(game: Game) -> list[dict]:
    out = []
    for t in game.turns:
        m, rnd = t["player"], t.get("round")
        if m not in game.moles or t.get("turn_phase") not in ("whisper", "discuss") or not t.get("public"):
            continue
        lies = false_claims(t)
        if not lies:
            continue
        cards = (t.get("action") or {}).get("clue_cards") or []
        checks = ((t.get("checks") or {}).get("clue_cards")) or []
        dealt = {(k, ps) for (r, k, ps, _) in game.dealt.get(m, []) if r <= rnd}
        for i, card in enumerate(cards):
            key = (card.get("kind"), frozenset(card.get("players") or []))
            if key in dealt:
                continue
            chk = checks[i] if i < len(checks) and isinstance(checks[i], dict) else {}
            if chk.get("held") is True:
                continue
            text = chk.get("text") or f"{card.get('kind')}: {', '.join(card.get('players') or [])}"
            real = [txt for (r, _, _, txt) in game.dealt.get(m, []) if r == rnd]
            where = "at the table" if t["turn_phase"] == "discuss" else f"in a whisper to {_whisper_partner(game, m, rnd)}"
            out.append(clip(
                game, "invented_evidence", rnd, m,
                f"{game.label(m)} tables a clue never dealt {where}: “{text}”",
                game.vote_outcome(rnd), public_turn=t, diary_turn=t, contradicts=True,
                facts={"card": text, "dealt_this_round": real or ["none"], "false_claims": lies,
                       "true_in_world": chk.get("true_in_world"), "phase": t["turn_phase"]}))
    return out


def _whisper_partner(game, player, rnd):
    for pair in (game.whisper_pairs.get(rnd) or {}).get("pairs") or []:
        if player in pair:
            return next((p for p in pair if p != player), "?")
    return "?"


def detect_catch(game: Game) -> list[dict]:
    out = []
    for rnd, v in sorted(game.vote_result.items()):
        m = v.get("eliminated")
        if m not in game.moles:
            continue
        cands = [t for t in game.turns_in(rnd, ("discuss",))
                 if game.role.get(t["player"]) == "crew" and (t.get("action") or {}).get("accuse") == m and t.get("public")]
        how = "calls out"
        if not cands:
            cands = [t for t in game.turns_in(rnd, ("vote",))
                     if game.role.get(t["player"]) == "crew" and (t.get("action") or {}).get("vote") == m and t.get("public")]
            how = "votes against"
        for t in cands:
            out.append(clip(
                game, "catch", rnd, t["player"],
                f"{game.label(t['player'])} {how} {game.label(m)}, and the table votes the mole out {game.tally(rnd)}",
                game.vote_outcome(rnd), public_turn=t, diary_turn=t, contradicts=bool(false_claims(t)),
                group=("catch", rnd), facts={"mole": m}))
    return out


def detect_partner_turned(game: Game) -> list[dict]:
    out = []
    for t in game.turns:
        m = t["player"]
        p = game.partner(m) if m in game.moles else None
        if not p or t.get("turn_phase") not in ("discuss", "vote") or not t.get("public"):
            continue
        act = t.get("action") or {}
        if t["turn_phase"] == "discuss" and act.get("accuse") == p:
            how = "accuses own partner"
        elif t["turn_phase"] == "vote" and act.get("vote") == p:
            how = "votes out own partner" if (game.vote_result.get(t["round"]) or {}).get("eliminated") == p \
                else "votes against own partner"
        else:
            continue
        out.append(clip(
            game, "partner_turned", t["round"], m, f"{game.label(m)} {how} {game.label(p)}",
            game.vote_outcome(t["round"]), public_turn=t, diary_turn=t, contradicts=bool(false_claims(t)),
            facts={"partner": p, "how": t["turn_phase"]}))
    return out


DETECTORS = (detect_broken_promise, detect_mutual_steal, detect_believed_lie, detect_right_accuser_out,
             detect_sabotage_on_instruction, detect_invented_evidence, detect_catch, detect_partner_turned)


# --------------------------------------------------------------------------- score, select, order

def score_clip(c: dict, frontier: bool) -> dict:
    parts = [(f"kind {c['kind']}", KIND_WEIGHT[c["kind"]])]
    if c["contradicts"]:
        parts.append(("diary contradicts public", BONUS_CONTRADICTS))
    parts.append(("fits 40 s", BONUS_FITS) if not c["long"] else ("long", -PENALTY_LONG))
    if frontier:
        parts.append(("frontier game", BONUS_FRONTIER))
    parts.extend(c.get("_bonuses") or [])
    c["score"] = sum(p for _, p in parts)
    c["score_parts"] = [[name, pts] for name, pts in parts]
    return c


def sort_key(c: dict):
    return (-c["score"], c["game_id"], c["round"] if c["round"] is not None else 0, c.get("_seq", 0), c["kind"])


def find_clips(events: list[dict], batch: str = "", folder: str = "games") -> list[dict]:
    """Every clip in one game, best first: scored, one per moment, viewer link set."""
    game = Game(events, batch=batch, folder=folder)
    frontier = Path(folder).name == FRONTIER_FOLDER
    port = VIEWER_PORTS.get(Path(folder).name, DEFAULT_PORT)
    best: dict = {}
    for det in DETECTORS:
        for c in det(game):
            score_clip(c, frontier)
            c["viewer"] = f"http://127.0.0.1:{port}/?game={game.game_id}"
            g = c["_group"]
            if g not in best or sort_key(c) < sort_key(best[g]):
                best[g] = c
    return sorted(best.values(), key=sort_key)


def public_record(c: dict) -> dict:
    return {k: v for k, v in c.items() if not k.startswith("_")}


# --------------------------------------------------------------------------- reading the folders

def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def is_mock(events: list[dict]) -> bool:
    usages = [e["usage"] for e in events if e.get("type") == "turn" and isinstance(e.get("usage"), dict)]
    return bool(usages) and all(not u.get("output") and not u.get("thinking") for u in usages)


def resolve_log(row: dict, folder: Path) -> Path | None:
    raw = row.get("log")
    cands = []
    if raw:
        p = Path(raw)
        cands += [p] if p.is_absolute() else [ROOT / p, folder.parent / p, folder / p.name]
    if row.get("game_id"):
        cands.append(folder / f"{row['game_id']}.jsonl")
    return next((c for c in cands if c.is_file()), None)


def load_folder(folder: Path, batches=None, skipped=None) -> list[tuple[str, str, list[dict]]]:
    """[(batch, folder, events)] for the folder's indexed games, after the skips."""
    skipped = skipped if skipped is not None else {}
    out = []
    index = folder / "index.jsonl"
    if not index.is_file():
        skipped.setdefault("no index", []).append(str(folder))
        return out
    for row in read_jsonl(index):
        gid = row.get("game_id", "?")
        if row.get("spoiled"):
            skipped.setdefault("spoiled", []).append(gid)
            continue
        path = resolve_log(row, folder)
        if path is None:
            skipped.setdefault("log not found", []).append(gid)
            continue
        events = read_jsonl(path)
        start = next((e for e in events if e.get("type") == "game_start"), {})
        batch = row.get("batch") or start.get("batch") or ""
        if batches and batch not in batches:
            continue
        if not any(e.get("type") == "game_end" for e in events):
            skipped.setdefault("unfinished", []).append(gid)
            continue
        if is_mock(events):
            skipped.setdefault("mock", []).append(gid)
            continue
        out.append((batch, str(folder), events))
    return out


# --------------------------------------------------------------------------- output

def _quote(label: str, text: str) -> list[str]:
    return [f"{label}", "", f"> {text}", ""]


def render_clip(c: dict, n: int, heading: str = "###") -> list[str]:
    secs = f"{c['reading_s']:.0f} s"
    if c["long"]:
        secs += f" (LONG: over {CLIP_S:.0f} s, not cut)"
    if c["extra"]:
        secs += f"; {c['reading_s_all']:.0f} s with context"
    lines = [f"{heading} {n}. {c['headline']}", "",
             f"- Kind: {KIND_TITLE[c['kind']]} (`{c['kind']}`), round {c['round']}, score {c['score']} "
             f"({', '.join(f'{name} {pts:+d}' for name, pts in c['score_parts'])})",
             f"- Speaker: {c['speaker']}, {c['model_name']} (`{c['model']}`), {c['role']}",
             f"- Outcome: {c['outcome']}",
             f"- Reading time: {secs}",
             f"- Viewer: {c['viewer']}"]
    facts = c.get("facts") or {}
    if facts.get("false_claims"):
        lines.append("- Self-tagged false: " + "; ".join(f"“{x}”" for x in facts["false_claims"]))
    if c["kind"] == "invented_evidence":
        lines.append("- Actually dealt that round: " + "; ".join(facts.get("dealt_this_round") or ["none"]))
    lines.append("")
    if c["public"]:
        src = c["public_from"]
        lines += _quote(f"**Public** ({src['player']}, round {c['round']} {src['phase']}, seq {src['seq']}):", c["public"])
    if c["diary"]:
        src = c["diary_from"]
        lines += _quote(f"**Diary** ({src['player']}, {src['phase']} turn, seq {src['seq']}):", c["diary"])
    for x in c["extra"]:
        lines += _quote(f"**Context: {x['player']} {x['label']}** ({x['phase']}, seq {x['seq']}):", x["text"])
    return lines


def render_markdown(per_game: list[tuple[dict, list[dict]]], top: int, folders, skipped: dict) -> str:
    allc = sorted((c for _, cs in per_game for c in cs), key=sort_key)
    n_games = len(per_game)
    out = ["# Clips", "",
           f"Found by rule by `analysis/clip_finder.py` (no model calls) in {n_games} games from "
           f"{', '.join(f'`{Path(f).name}`' for f in folders)}: {len(allc)} clips. Quotes are verbatim from the "
           "logs (`public` and `confessional` fields); fallback turns are never quoted. Reading time is the "
           f"public line plus the diary line at {WORDS_PER_S} words a second.", ""]
    if skipped:
        out.append("Skipped: " + "; ".join(f"{k} {len(v)} ({', '.join(v)})" for k, v in sorted(skipped.items())) + ".")
        out.append("")
    out += ["## Score rule", "", "```", SCORE_RULE, "```", ""]
    out += ["## Counts", "", "| Folder | " + " | ".join(f"`{k}`" for k in KIND_WEIGHT) + " | All |",
            "|---|" + "---:|" * (len(KIND_WEIGHT) + 1)]
    for f in folders:
        cs = [c for g, gc in per_game if g["folder"] == str(f) for c in gc]
        out.append(f"| `{Path(f).name}` | " + " | ".join(str(sum(c["kind"] == k for c in cs)) for k in KIND_WEIGHT)
                   + f" | {len(cs)} |")
    out += ["", f"## Top {top} across all games", ""]
    for i, c in enumerate(allc[:top], 1):
        out.append(f"{i}. **{c['headline']}** — `{c['game_id']}` round {c['round']}, "
                   f"`{c['kind']}`, score {c['score']}, {c['reading_s']:.0f} s{' LONG' if c['long'] else ''}. "
                   f"[viewer]({c['viewer']})")
    out.append("")
    out += ["## By game", ""]
    for g, cs in per_game:
        if not cs:
            continue
        out += [f"## `{g['game_id']}` ({g['batch'] or 'no batch'}, seed {g['seed']}, {Path(g['folder']).name})", "",
                f"Viewer: {cs[0]['viewer']}", ""]
        for i, c in enumerate(cs, 1):
            out += render_clip(c, i)
    empty = [g["game_id"] for g, cs in per_game if not cs]
    if empty:
        out += ["## Games with no clips", "", ", ".join(f"`{x}`" for x in empty), ""]
    return "\n".join(out).rstrip() + "\n"


def run(folders, batches=None):
    skipped: dict = {}
    per_game = []
    for f in folders:
        for batch, folder, events in load_folder(Path(f), batches, skipped):
            cs = find_clips(events, batch=batch, folder=folder)
            g = Game(events, batch, folder)
            per_game.append(({"game_id": g.game_id, "batch": g.batch, "seed": g.seed, "folder": folder}, cs))
    return per_game, skipped


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="List clip-worthy moments in finished Inside Job logs.")
    ap.add_argument("--games", action="append", metavar="DIR",
                    help="game folder with an index.jsonl (repeatable; default: games_frontier and games)")
    ap.add_argument("--batch", action="append", metavar="NAME", help="only these batches (repeatable)")
    ap.add_argument("--top", type=int, default=10, help="length of the cross-game list (default 10)")
    ap.add_argument("--out", metavar="FILE.md", help="write the Markdown here (default: stdout)")
    ap.add_argument("--json", metavar="FILE.json", help="also write the clip records as JSON")
    args = ap.parse_args(argv)
    folders = [Path(d) for d in args.games] if args.games else [ROOT / d for d in DEFAULT_DIRS]
    per_game, skipped = run(folders, set(args.batch) if args.batch else None)
    md = render_markdown(per_game, args.top, folders, skipped)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(md, encoding="utf-8")
    else:
        sys.stdout.write(md)
    if args.json:
        recs = sorted((c for _, cs in per_game for c in cs), key=sort_key)
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps([public_record(c) for c in recs], indent=1, ensure_ascii=False) + "\n",
                                   encoding="utf-8")
    n = sum(len(cs) for _, cs in per_game)
    print(f"clip_finder: {len(per_game)} games, {n} clips; skipped "
          + (", ".join(f"{k} {len(v)}" for k, v in sorted(skipped.items())) or "none"), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
