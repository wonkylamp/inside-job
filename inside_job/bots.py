"""Scripted bots: zero-token players for tuning the dials (SPEC section 12).

A bot acts only on the events its player may see. The engine hands it `view`, the player's
projected visible events (built through `log.visible_to` / `log.project`, exactly like a prompt);
a bot never reads prompt text (the engine does not even build it) and never sees engine events.
It also reads the reply schema, which lists the valid choices, and the game rules from the config
(what a real player reads in its system prompt).

Crew: `logician` (with `skill`: on each decision, with probability 1 - skill, act at random).
Moles: `always`, `never`, `smart`, `hold1` (see SPEC; `hold1` is `smart` that never sabotages in
round 1). All mole types share smart's non-job behaviour and differ only in when they sabotage.
`mole_cards`: `decoy` (one fake card a round, true in a world where crew members are the moles) or
`none`.

v0.4 dials (docs/V04.md): with `vote_nobody` crew vote their top suspect only when their belief in
it is at least `eject_threshold`, else `nobody`; in the `debate` (team_approval) crew approve when
their probability that the team holds a mole is below `approve_threshold`, moles approve as a
public-evidence logician would (`mole_approve = "blend"`) or exactly when a mole is on the team
(`"team"`); in the Final Accusation crew name their top suspect and moles the table's top
non-partner suspect.
"""

from __future__ import annotations

import json
import math
import random
import statistics
import time
from itertools import combinations, product
from pathlib import Path

from .clues import candidate_clues, card_as_clue, clue_is_true
from .config import CLUE_STRENGTHS, NOBODY, Config, config_from_dict, parse_set, parse_value
from .llm import LLMReply, zero_usage
from .log import visible_events
from .schemas import WIRE_MOVE
from .solver import inputs_from_view, player_worlds, posterior, table_worlds

CREW_TYPES = ("logician",)
MOLE_TYPES = ("always", "never", "smart", "hold1")
MOLE_CARDS = ("none", "decoy")
MOLE_APPROVE = ("blend", "team")
# v0.4 bot options (BotLLM keyword, default); `--sweep bot.<name>=...` sweeps them.
BOT_OPTIONS = {"eject_threshold": 0.5, "approve_threshold": 0.45}


def _key(clue: dict) -> tuple:
    return (clue["kind"], frozenset(clue.get("players", [])),
            clue.get("k") if clue["kind"] == "exactly_k_of_three" else None)


def _card(clue: dict) -> dict:
    return {"kind": clue["kind"], "players": list(clue["players"]), "k": clue.get("k", 0) or 0}


class _State:
    """What one player knows, accumulated from their (append-only) view."""

    def __init__(self, me: str):
        self.me = me
        self.n = 0
        self.seats: list[str] = []
        self.num_moles = 2
        self.role = "crew"
        self.partners: list[str] = []
        self.revealed: dict[str, str] = {}
        self.jobs: list[tuple] = []
        self.cards: list[tuple] = []          # public cards: (speaker, clue)
        self.pair_cards: list[tuple] = []
        self.own_clues: list[dict] = []
        self.round = 0
        self.alive: list[str] = []
        self.team: list[str] = []
        self.team_round = 0
        self.my_choice: dict[int, str] = {}   # round -> my job choice
        self.my_discuss_rounds: set[int] = set()

    def update(self, view: list[dict]):
        for e in view[self.n:]:
            t = e["type"]
            if t == "table":
                self.seats, self.num_moles = list(e["seats"]), e["num_moles"]
            elif t == "role":
                self.role, self.partners = e["role"], list(e.get("partners") or [])
            elif t == "round_start":
                self.round, self.alive = e["round"], list(e["alive"])
            elif t == "clue":
                self.own_clues.append(e["clue"])
            elif t == "job_pick":
                self.team, self.team_round = list(e["team"]), e["round"]
            elif t == "job_result":
                self.jobs.append((list(e["team"]), e["sabotages"]))
            elif t == "vote_result":
                if e.get("eliminated") is not None:      # v0.4 vote_nobody: nobody may go
                    self.revealed[e["eliminated"]] = e["role"]
                    self.alive = [a for a in self.alive if a != e["eliminated"]]
            elif t == "turn":
                tp, act = e.get("turn_phase"), e.get("action") or {}
                if tp in ("discuss", "debate"):          # debate: v0.4 team_approval, public too
                    self.cards += [(e["player"], card_as_clue(c)) for c in act.get("clue_cards") or []]
                    if tp == "discuss" and e["player"] == self.me:
                        self.my_discuss_rounds.add(e["round"])
                elif tp == "whisper" and e["player"] != self.me:
                    self.pair_cards += [(e["player"], card_as_clue(c)) for c in act.get("clue_cards") or []]
                elif tp == "job" and e["player"] == self.me:
                    self.my_choice[e["round"]] = act.get("choice")
        self.n = len(view)

    def real_clues(self) -> list[dict]:
        return [c for c in self.own_clues if c.get("kind") != "none"]


class Bot:
    def __init__(self, me: str, kind: str, rng: random.Random, cfg: Config, skill: float, mole_cards: str,
                 eject_threshold: float = 0.5, approve_threshold: float = 0.45, mole_approve: str = "blend"):
        self.me, self.kind, self.rng, self.cfg = me, kind, rng, cfg
        self.skill, self.mole_cards = skill, mole_cards
        self.eject_threshold, self.approve_threshold = eject_threshold, approve_threshold
        self.mole_approve = mole_approve
        self.s = _State(me)
        self.tabled: set = set()               # keys of clues this bot has tabled
        self.decoy_world: frozenset | None = None
        self.decoys: list[dict] = []           # fake clues tabled so far
        self.decoy_round = 0

    # ------------------------------------------------------------- beliefs
    def belief(self) -> dict:
        s = self.s
        if s.role == "crew":
            worlds = player_worlds(s.seats, s.num_moles, s.revealed, s.cards, s.jobs, player=self.me,
                                   own_clues=s.own_clues, pair_cards=s.pair_cards)
            fb = [w for w in table_worlds(s.seats, s.num_moles, s.revealed, [], s.jobs) if self.me not in w]
            return posterior(worlds, s.seats, fb)
        return self.table_read()

    def table_read(self) -> dict:
        s = self.s
        worlds = table_worlds(s.seats, s.num_moles, s.revealed, s.cards, s.jobs)
        return posterior(worlds, s.seats, table_worlds(s.seats, s.num_moles, s.revealed, [], s.jobs))

    def belief_worlds(self) -> list:
        """The worlds `belief` averages over (crew: own view; with the same fallback)."""
        s = self.s
        worlds = player_worlds(s.seats, s.num_moles, s.revealed, s.cards, s.jobs, player=self.me,
                               own_clues=s.own_clues, pair_cards=s.pair_cards)
        return worlds or [w for w in table_worlds(s.seats, s.num_moles, s.revealed, [], s.jobs) if self.me not in w]

    def public_worlds(self) -> list:
        """The worlds a logician holding only the table's public evidence averages over."""
        s = self.s
        return (table_worlds(s.seats, s.num_moles, s.revealed, s.cards, s.jobs)
                or table_worlds(s.seats, s.num_moles, s.revealed, [], s.jobs))

    @staticmethod
    def p_team_mole(team, worlds) -> float:
        """Share of the worlds in which at least one team member is a mole (over worlds, not
        from marginals)."""
        t = set(team)
        return sum(1 for w in worlds if w & t) / len(worlds) if worlds else 0.0

    def suspicion(self, schema: dict, probs: dict) -> dict:
        keys = schema["properties"][WIRE_MOVE]["properties"]["suspicion"]["properties"]
        return {k: int(round(100 * probs.get(k, 0.0))) for k in keys}

    def pick_max(self, names, probs) -> str:
        top = max(probs.get(n, 0.0) for n in names)
        return self.rng.choice([n for n in names if probs.get(n, 0.0) == top])

    def least(self, names, probs, n) -> list[str]:
        names = list(names)
        self.rng.shuffle(names)                     # seeded tie-break
        return sorted(names, key=lambda x: probs.get(x, 0.0))[:n]

    def random_act(self) -> bool:
        return self.s.role == "crew" and self.rng.random() >= self.skill

    @property
    def moles(self) -> set:
        return {self.me, *self.s.partners} if self.s.role == "mole" else set()

    # ------------------------------------------------------------- turns
    def turn(self, phase: str, schema: dict, view: list[dict]) -> dict:
        self.s.update(view)
        props = schema["properties"][WIRE_MOVE]["properties"]
        out = {"confessional": "", "public": "", "claims": [], "memory": "", "action": {}}
        fn = getattr(self, "do_" + phase)
        fn(out, props, schema)
        out["confessional"] = out["confessional"] or f"{self.kind} bot, {phase}."
        out["memory"] = f"R{self.s.round} {phase}"
        out[WIRE_MOVE] = out.pop("action")           # reply in the wire format, like a model
        return out

    def do_clue(self, out, props, schema):
        probs = self.belief()
        act = out["action"]
        if "whisper_with" in props:
            others = [o for o in props["whisper_with"]["enum"] if o != "none"]
            if self.s.role == "mole":
                pool = [o for o in others if o not in self.s.partners] or others
                act["whisper_with"] = self.rng.choice(pool)
            elif self.random_act():
                act["whisper_with"] = self.rng.choice(others)
            else:
                act["whisper_with"] = self.least(others, probs, 1)[0]
        act["suspicion"] = self.suspicion(schema, probs)

    def do_whisper(self, out, props, schema):
        cards = []
        if self.s.role == "crew":
            cards = [_card(c) for c in reversed(self.s.real_clues())][:2]
        out["public"] = "Here is what I have." if cards else "Nothing for you yet. Watch the team."
        out["claims"] = [{"text": f"my clue: {card_as_clue(c)['text']}", "truthful": True} for c in cards]
        out["action"] = {"clue_cards": cards, "suspicion": self.suspicion(schema, self.belief())}

    def do_pick(self, out, props, schema):
        n = props["team"]["minItems"]
        alive = list(props["team"]["items"]["enum"])
        others = [a for a in alive if a != self.me]
        if self.s.role == "mole":
            probs = self.table_read()
            pool = [o for o in others if o not in self.s.partners]
            team = [self.me] + self.least(pool, probs, n - 1)
            if len(team) < n:
                team += [o for o in others if o not in team][: n - len(team)]
        elif self.random_act():
            team = self.rng.sample(alive, n)
        else:
            team = [self.me] + self.least(others, self.belief(), n - 1)
        out["public"] = f"Team: {', '.join(team)}."
        out["action"] = {"team": team}

    def do_job(self, out, props, schema):
        s = self.s
        if self.kind == "never":
            choice = "help"
        elif self.kind == "always":
            choice = "sabotage"
        elif self.kind == "hold1" and s.round == 1:       # hold1: smart, but never in round 1
            choice = "help"
        else:                                              # smart: lowest-seat mole on the team only
            on = [m for m in s.seats if m in self.moles and m in s.team]
            choice = "sabotage" if on and on[0] == self.me else "help"
        out["action"] = {"choice": choice}

    def do_discuss(self, out, props, schema):
        s = self.s
        others = [o for o in props["accuse"]["enum"] if o != "none"]
        cards, claims, words = [], [], []
        if s.role == "crew":
            probs = self.belief()
            for c in reversed(s.real_clues()):
                if _key(c) not in self.tabled and len(cards) < 2:
                    cards.append(_card(c))
                    self.tabled.add(_key(c))
                    claims.append({"text": f"my clue: {c['text']}", "truthful": True})
            accuse = self.rng.choice(others) if self.random_act() else self.pick_max(others, probs)
            jc_enum = props["job_claim"]["enum"]
            job_claim = "helped" if "helped" in jc_enum else "none"
            if job_claim == "helped":
                claims.append({"text": "I helped on the job", "truthful": True})
        else:
            probs = self.table_read()
            pool = [o for o in others if o not in s.partners] or others
            accuse = self.pick_max(pool, probs)
            if self.mole_cards == "decoy" and self.decoy_round != s.round:
                fake = self.make_decoy(others)
                if fake:
                    self.decoy_round = s.round
                    self.decoys.append(fake)
                    cards.append(_card(fake))
                    claims.append({"text": f"my clue: {fake['text']}", "truthful": False})
            jc_enum = props["job_claim"]["enum"]
            job_claim = "helped" if "helped" in jc_enum else "none"
            if job_claim == "helped":
                claims.append({"text": "I helped on the job",
                               "truthful": s.my_choice.get(s.round) != "sabotage"})
        words.append("Cards on the table." if cards else "Nothing new from me.")
        if job_claim == "helped":
            words.append("I helped on that job.")
        words.append(f"I am watching {accuse}.")
        out["public"] = " ".join(words)
        out["claims"] = claims
        out["action"] = {"accuse": accuse, "challenges": [], "clue_cards": cards, "job_claim": job_claim,
                         "suspicion": self.suspicion(schema, probs)}

    def make_decoy(self, others: list[str]) -> dict | None:
        """A fake clue card that is true in a world where crew members are the moles: the same
        world every round while it stays possible, so the mole's own cards never contradict
        each other; preferring a world the public evidence still allows."""
        s = self.s
        crew_alive = [a for a in s.alive if a not in self.moles]
        out_moles = [n for n, r in s.revealed.items() if r == "mole"]
        need = s.num_moles - len(out_moles)
        if need < 0 or len(crew_alive) < need:
            return None
        cands = [frozenset(out_moles + list(c)) for c in combinations(crew_alive, need)]
        cands = [w for w in cands if all(clue_is_true(d, w) for d in self.decoys)]
        if not cands:
            return None
        public = set(table_worlds(s.seats, s.num_moles, s.revealed, s.cards, s.jobs))
        if self.decoy_world not in cands or (self.decoy_world not in public and any(w in public for w in cands)):
            good = [w for w in cands if w in public] or cands
            self.decoy_world = self.rng.choice(sorted(good, key=sorted))
        w2 = self.decoy_world
        alive_others = [o for o in s.alive if o != self.me and o in others]
        target = CLUE_STRENGTHS.get(self.cfg.game.clue_strength, 0.8)
        table = list(public) or list(table_worlds(s.seats, s.num_moles, s.revealed, [], s.jobs))
        real = self.moles | set(out_moles)
        tabled = {_key(d) for d in self.decoys}
        best, best_d = [], None
        for c in candidate_clues(alive_others, s.num_moles):
            if _key(c) in tabled or not clue_is_true(c, w2):
                continue
            surv = sum(1 for w in table if clue_is_true(c, w))
            if table and surv == len(table):
                continue                                  # tells the table nothing
            d = abs(surv / len(table) - target) if table else 0.0
            d += 0.0 if not clue_is_true(c, real) else 1.0  # prefer cards false in the real world
            if best_d is None or d < best_d - 1e-12:
                best, best_d = [c], d
            elif abs(d - best_d) <= 1e-12:
                best.append(c)
        return dict(self.rng.choice(best)) if best else None

    def do_vote(self, out, props, schema):
        s = self.s
        options = list(props["vote"]["enum"])
        others = [o for o in options if o != NOBODY]      # == options unless v0.4 vote_nobody
        if s.role == "mole":
            probs = self.table_read()
            pool = [o for o in others if o not in s.partners] or others
            target = self.pick_max(pool, probs)            # moles always vote for an ejection
        else:
            probs = self.belief()
            if self.random_act():
                target = self.rng.choice(options)
            else:
                target = self.pick_max(others, probs)
                if len(options) > len(others) and probs.get(target, 0.0) < self.eject_threshold:
                    target = NOBODY
        out["public"] = f"{target}."
        out["action"] = {"vote": target, "suspicion": self.suspicion(schema, probs)}

    def do_debate(self, out, props, schema):
        """v0.4 team_approval: cards and accusation as in discussion, plus approve / reject."""
        s = self.s
        others = [o for o in props["accuse"]["enum"] if o != "none"]
        team = list(s.team) if s.team_round == s.round else []
        cards, claims = [], []
        if s.role == "crew":
            probs = self.belief()
            for c in reversed(s.real_clues()):
                if _key(c) not in self.tabled and len(cards) < 2:
                    cards.append(_card(c))
                    self.tabled.add(_key(c))
                    claims.append({"text": f"my clue: {c['text']}", "truthful": True})
            accuse = self.rng.choice(others) if self.random_act() else self.pick_max(others, probs)
            if self.random_act():
                approve = self.rng.random() < 0.5
            else:
                approve = self.p_team_mole(team, self.belief_worlds()) < self.approve_threshold
        else:
            probs = self.table_read()
            pool = [o for o in others if o not in s.partners] or others
            accuse = self.pick_max(pool, probs)
            if self.mole_cards == "decoy" and self.decoy_round != s.round:
                fake = self.make_decoy(others)
                if fake:
                    self.decoy_round = s.round
                    self.decoys.append(fake)
                    cards.append(_card(fake))
                    claims.append({"text": f"my clue: {fake['text']}", "truthful": False})
            if self.mole_approve == "team":
                approve = bool(set(team) & self.moles)
            else:
                approve = self.p_team_mole(team, self.public_worlds()) < self.approve_threshold
        words = ["Cards on the table." if cards else "Nothing new from me.",
                 "I approve this team." if approve else "I reject this team.", f"I am watching {accuse}."]
        out["public"] = " ".join(words)
        out["claims"] = claims
        out["action"] = {"accuse": accuse, "challenges": [], "clue_cards": cards, "approve": approve,
                         "suspicion": self.suspicion(schema, probs)}

    def do_final_accuse(self, out, props, schema):
        """v0.4 Final Accusation: crew name their top suspect, moles the table's top non-partner."""
        s = self.s
        others = list(props["accuse"]["enum"])
        if s.role == "mole":
            probs = self.table_read()
            pool = [o for o in others if o not in s.partners] or others
            target = self.pick_max(pool, probs)
        else:
            target = self.rng.choice(others) if self.random_act() else self.pick_max(others, self.belief())
        out["public"] = f"I name {target}."
        out["action"] = {"accuse": target}

    def do_cut_pitch(self, out, props, schema):
        out["public"] = "Send me through. I split."
        out["claims"] = [{"text": "I will split", "truthful": True}]
        out["action"] = {}

    def do_cut_vote(self, out, props, schema):
        out["action"] = {"finalist": self.rng.choice(props["finalist"]["enum"])}

    def do_finale_pitch(self, out, props, schema):
        out["public"] = "I split. Split with me."
        out["claims"] = [{"text": "I will split", "truthful": True}]
        out["action"] = {"stated_intent": "split"}

    def do_finale_choice(self, out, props, schema):
        out["action"] = {"choice": "split"}


class BotLLM:
    """An LLM client whose players are scripted bots. The engine sees `wants_view` and passes
    each call the player's projected view; `needs_prompt = False` lets it skip prompt text."""
    wants_view = True
    needs_prompt = False

    def __init__(self, cfg: Config, seed: int, crew: str = "logician", crew_skill: float = 0.7,
                 moles: str = "smart", mole_cards: str = "decoy", audit=None, eject_threshold: float = 0.5,
                 approve_threshold: float = 0.45, mole_approve: str = "blend"):
        if (crew not in CREW_TYPES or moles not in MOLE_TYPES or mole_cards not in MOLE_CARDS
                or mole_approve not in MOLE_APPROVE):
            raise ValueError("unknown bot type")
        self.cfg, self.seed = cfg, seed
        self.crew, self.skill, self.moles, self.mole_cards = crew, crew_skill, moles, mole_cards
        self.eject_threshold, self.approve_threshold = eject_threshold, approve_threshold
        self.mole_approve = mole_approve
        self.bots: dict[str, Bot] = {}
        self.audit = audit                    # test hook: audit(player, view) before every turn
        self.calls = 0

    def bot(self, player: str, view: list[dict]) -> Bot:
        b = self.bots.get(player)
        if b is None:
            role_ev = next((e for e in view if e["type"] == "role" and e.get("player") == player), None)
            role = role_ev["role"] if role_ev else "crew"
            kind = self.crew if role == "crew" else self.moles
            b = Bot(player, kind, random.Random(f"{self.seed}:bot:{player}"), self.cfg, self.skill,
                    self.mole_cards, eject_threshold=self.eject_threshold,
                    approve_threshold=self.approve_threshold, mole_approve=self.mole_approve)
            self.bots[player] = b
        return b

    async def call(self, *, model, system, prompt, schema, phase=None, player=None, view=None) -> LLMReply:
        self.calls += 1
        if phase == "recap" or player is None:
            data = {"recap": ""}
        else:
            view = view or []
            if self.audit:
                self.audit(player, view)
            data = self.bot(player, view).turn(phase, schema, view)
        return LLMReply(data=data, raw_text="", served_model=model, usage=zero_usage(), latency_s=0.0)


# --------------------------------------------------------------------------- running and stats

def play_bot_game(cfg: Config, seed: int, **bot_kw) -> list[dict]:
    from .engine import Game
    llm = BotLLM(cfg, seed, **bot_kw)
    game = Game(cfg, llm, seed, game_id=f"bot-s{seed}", clock=lambda: "")
    game.run()
    return game.log.events


def game_summary(events: list[dict], rounds_checked: int = 4) -> dict:
    """Per-game figures for the sweep table (reads engine events: this is analysis, not play)."""
    start, end = events[0], events[-1]
    roles = {p["name"]: p["role"] for p in start["players"]}
    opp = sab = 0
    for e in events:
        if e["type"] == "job_choices":
            for n, c in e["choices"].items():
                if roles[n] == "mole":
                    opp += 1
                    sab += c == "sabotage"
    mole_out_r2 = any(e["type"] == "vote_result" and e["round"] <= 2 and e["role"] == "mole" for e in events)
    public = visible_events(events, None)
    worlds = {}
    for r in range(1, rounds_checked + 1):
        inp = inputs_from_view([e for e in public if e["round"] <= r and e["phase"] not in ("cut", "finale", "end")],
                               None)
        worlds[r] = len(table_worlds(inp["players"], inp["num_moles"], inp["revealed"], inp["cards"], inp["jobs"]))
    votes = [e for e in events if e["type"] == "vote_result"]
    team_votes = [e for e in events if e["type"] == "team_vote"]
    fa = next((e for e in events if e["type"] == "final_accusation"), None)
    crew_ejected = sum(1 for e in votes if e.get("role") == "crew")
    return {"seed": start["seed"], "winner": end["winner"], "reason": end["reason"], "rounds": end["rounds"],
            "clean": end["clean_jobs"], "blown": end["blown_jobs"], "mole_opps": opp, "sabotages": sab,
            "mole_out_r2": mole_out_r2, "fallbacks": end["fallbacks"],
            "solved": {r: worlds[r] == 1 for r in worlds}, "worlds": worlds,
            # v0.4 figures (meaningful under any rules; the counts are 0 where a dial is off)
            "crew_ejected": crew_ejected, "mole_score": end["blown_jobs"] + crew_ejected,
            "votes": len(votes), "votes_nobody": sum(1 for e in votes if e.get("eliminated") is None),
            "votes_forced": sum(1 for e in votes if e.get("forced")),
            "team_votes": len(team_votes), "team_rejections": sum(1 for e in team_votes if not e["approved"]),
            "fa_held": fa is not None, "fa_hit": bool(fa and fa["hit"]),
            "zero_blown": end["blown_jobs"] == 0, "over_by_r2": end["rounds"] <= 2}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


REASONS = ("jobs_clean", "moles_out", "sabotage", "final_two", "clock", "mole_score")


def cell_stats(rows: list[dict]) -> dict:
    n = len(rows)
    crew = sum(1 for r in rows if r["winner"] == "crew")
    lo, hi = wilson(crew, n)
    opp = sum(r["mole_opps"] for r in rows)
    votes, nobody = sum(r["votes"] for r in rows), sum(r["votes_nobody"] for r in rows)
    forced = sum(r["votes_forced"] for r in rows)
    tv, rej = sum(r["team_votes"] for r in rows), sum(r["team_rejections"] for r in rows)
    fa, hits = sum(1 for r in rows if r["fa_held"]), sum(1 for r in rows if r["fa_hit"])
    return {
        "games": n, "crew_win": crew / n if n else 0.0, "crew_win_ci": [lo, hi],
        "reasons": {k: sum(1 for r in rows if r["reason"] == k) / n for k in REASONS},
        "rounds": statistics.mean(r["rounds"] for r in rows), "clean": statistics.mean(r["clean"] for r in rows),
        "blown": statistics.mean(r["blown"] for r in rows),
        "sabotage_rate": (sum(r["sabotages"] for r in rows) / opp) if opp else 0.0,
        "mole_out_r2": sum(1 for r in rows if r["mole_out_r2"]) / n,
        "solved_by": {r: sum(1 for x in rows if x["solved"][r]) / n for r in rows[0]["solved"]} if rows else {},
        "fallbacks": sum(r["fallbacks"] for r in rows),
        # v0.4 (docs/V04.md)
        "crew_ejected": statistics.mean(r["crew_ejected"] for r in rows),
        "mole_score": statistics.mean(r["mole_score"] for r in rows),
        "votes": votes, "votes_nobody": nobody, "votes_forced": forced,
        "nobody_share": nobody / votes if votes else 0.0, "forced_share": forced / votes if votes else 0.0,
        "team_votes": tv, "team_rejections": rej, "reject_share": rej / tv if tv else 0.0,
        "fa_held": fa, "fa_hits": hits, "fa_hit_rate": hits / fa if fa else 0.0,
        "zero_blown": sum(1 for r in rows if r["zero_blown"]) / n,
        "over_by_r2": sum(1 for r in rows if r["over_by_r2"]) / n,
    }


def parse_sweep(specs: list[str]) -> list[tuple[str, list]]:
    """`key=v1,v2`: a [game] key, or `bot.<option>` for a v0.4 bot threshold (BOT_OPTIONS)."""
    out = []
    for spec in specs or []:
        if "=" not in spec:
            raise ValueError(f"--sweep needs key=v1,v2 (got {spec!r})")
        k, vs = spec.split("=", 1)
        k = k.strip()
        if k.startswith("bot."):
            if k[4:] not in BOT_OPTIONS:
                raise ValueError(f"--sweep: unknown bot option {k!r} (known: "
                                 f"{', '.join('bot.' + o for o in BOT_OPTIONS)})")
            try:
                vals = [float(v) for v in vs.split(",") if v.strip()]
            except ValueError:
                raise ValueError(f"--sweep {k} needs numbers") from None
        else:
            vals = [parse_value(k, v.strip()) for v in vs.split(",") if v.strip()]
        out.append((k, vals))
    return out


def run_sweep(raw: dict, *, games: int, seed: int, sets: list[str], sweeps: list[str], bot_kw: dict,
              out_dir: str | None = None, echo=print) -> list[dict]:
    """One cell per combination of sweep values; every cell plays the same seeds (paired)."""
    base = parse_set(raw, sets)
    axes = parse_sweep(sweeps)
    cells = [dict(zip([k for k, _ in axes], combo)) for combo in product(*[v for _, v in axes])] or [{}]
    results = []
    out = Path(out_dir) if out_dir else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    plan = []
    for cell in cells:
        r = json.loads(json.dumps(base))
        r["game"].update({k: v for k, v in cell.items() if not k.startswith("bot.")})
        kw = dict(bot_kw, **{k[4:]: v for k, v in cell.items() if k.startswith("bot.")})
        plan.append((cell, config_from_dict(r), kw))
    # The v0.4 columns are printed only when some cell has a v0.4 dial on.
    v04 = any(cfg.game.v04_dials() for _, cfg, _ in plan)
    echo(header_line(v04))
    for cell, cfg, kw in plan:
        t0 = time.monotonic()
        rows = [game_summary(play_bot_game(cfg, s, **kw)) for s in range(seed, seed + games)]
        wall = time.monotonic() - t0
        st = dict(cell_stats(rows), cell=cell, wall_s=round(wall, 3), games_per_s=round(games / wall, 1) if wall else None)
        results.append(st)
        echo(format_row(st, v04))
        if out:
            with open(out / "bots-cells.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(dict(st, bots=kw, seed=seed, set=sets)) + "\n")
            with open(out / "bots-games.jsonl", "a", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(dict(row, cell=cell)) + "\n")
    return results


def header_line(v04: bool = False) -> str:
    if v04:
        return (f"{'cell':<28} {'games':>5}  {'crew win (95% CI)':<21} {'end reasons':<44} {'rounds':>6} "
                f"{'clean':>5} {'blown':>5} {'sab/opp':>7} {'mole out<=R2':>12}  {'solved by R1/R2/R3/R4':<22} "
                f"{V04_HEADER}   g/s")
    return (f"{'cell':<28} {'games':>5}  {'crew win (95% CI)':<21} {'end reasons':<44} {'rounds':>6} "
            f"{'clean':>5} {'blown':>5} {'sab/opp':>7} {'mole out<=R2':>12}  solved by R1/R2/R3/R4   g/s")


# v0.4 columns: crew ejected and mole score (means per game); votes with nobody out and forced votes
# (share of votes); team votes rejected (share of team votes); Final Accusation held (share of games)
# and hit (share of those held); games with no blown job; games over by round 2.
V04_HEADER = (f"{'ejected':>7} {'m.score':>7} {'nobody':>6} {'forced':>6} {'reject':>6} {'FA held':>7} "
              f"{'FA hit':>6} {'0 blown':>7} {'<=R2':>5}")


def format_v04(st: dict) -> str:
    return (f"{st['crew_ejected']:>7.2f} {st['mole_score']:>7.2f} {100 * st['nobody_share']:>5.1f}% "
            f"{100 * st['forced_share']:>5.1f}% {100 * st['reject_share']:>5.1f}% {100 * st['fa_held'] / st['games']:>6.1f}% "
            f"{100 * st['fa_hit_rate']:>5.1f}% {100 * st['zero_blown']:>6.1f}% {100 * st['over_by_r2']:>4.1f}%")


def format_row(st: dict, v04: bool = False) -> str:
    cell = ", ".join(f"{k}={v}" for k, v in st["cell"].items()) or "(defaults)"
    lo, hi = st["crew_win_ci"]
    win = f"{100 * st['crew_win']:5.1f}% ({100 * lo:4.1f}-{100 * hi:4.1f})"
    reasons = " ".join(f"{k} {100 * v:.0f}%" for k, v in st["reasons"].items() if v)
    solved = "/".join(f"{100 * v:.0f}%" for v in st["solved_by"].values())
    fb = f"  FALLBACKS {st['fallbacks']}" if st["fallbacks"] else ""
    extra = f" {format_v04(st)}" if v04 else ""
    return (f"{cell:<28} {st['games']:>5}  {win:<21} {reasons:<44} {st['rounds']:>6.2f} {st['clean']:>5.2f} "
            f"{st['blown']:>5.2f} {100 * st['sabotage_rate']:>6.1f}% {100 * st['mole_out_r2']:>11.1f}%  "
            f"{solved:<22}{extra} {st['games_per_s'] or 0:>5.1f}{fb}")
