"""The game: state, phases, end checks and the finale (SPEC sections 4 and 6)."""

from __future__ import annotations

import asyncio
import random
import sys
import time
from dataclasses import dataclass, field

from . import LOG_VERSION, RULES_VERSION
from .clues import NONE_CLUE, card_as_clue, card_held, clue_is_true, draw_recipients, generate_clue
from .config import CODENAMES, NOBODY, Config
from .llm import LLM, add_usage, build_argv, zero_usage
from .log import GameLog, project, utc_now, visible_to
from .prompts import (NARRATOR_SYSTEM, narrator_prompt, player_system_prompt,
                      turn_prompt)
from .rawlog import RawLog, code_fingerprint, schema_sha256, sha256_text
from .schemas import (NONE, STATEMENT_PHASES, SUSPICION_PHASES, V04_STATEMENT_PHASES, V04_SUSPICION_PHASES,
                      clean_reply, hard_cap, narrator_schema, truncate_words, turn_schema)

JOB_NAMES = (
    "Loop the lobby cameras", "Swap the vault keycard", "Cut the rooftop alarm", "Bribe the night guard",
    "Copy the floor plans", "Drain the armoured van", "Crack the manager's safe", "Plant the fake badge",
    "Tap the security radio", "Steal the shift rota", "Jam the motion sensors", "Lift the master key",
    "Clone the elevator pass", "Disable the laser grid", "Forge the delivery papers",
    "Reroute the power line", "Spike the guard's coffee", "Pick the archive lock",
    "Hack the time lock", "Distract the doorman",
)

LOG_PHASE = {"clue": "clue", "whisper": "whisper", "pick": "pick", "job": "job", "discuss": "discuss",
             "vote": "vote", "cut_pitch": "cut", "cut_vote": "cut", "finale_pitch": "finale",
             "finale_choice": "finale", "debate": "debate", "final_accuse": "finale"}   # last two: v0.4
# Turn phases that belong to the end of the game (statement ids `F-S<n>`, progress label `F`).
FINALE_TURN_PHASES = ("cut_pitch", "cut_vote", "finale_pitch", "finale_choice", "final_accuse")


@dataclass
class Player:
    name: str
    model: str
    model_name: str
    seat: int
    role: str
    eliminated_round: int | None = None

    @property
    def alive(self) -> bool:
        return self.eliminated_round is None


@dataclass
class Pending:
    """A finished `ask`, not yet written to the log."""
    player: str
    phase: str
    data: dict | None
    truncated_fields: list[str]                             # fields trimmed to their word cap
    attempts: int
    usage: dict
    latency_s: float
    served_model: str | None
    rejections: list[str] = field(default_factory=list)
    error_kinds: list[str] = field(default_factory=list)   # one per failed attempt
    blocked: int = 0                                        # attempts refused by the model's filter
    fallback_reason: str | None = None                      # blocked | invalid | timeout | cli
    raw_attempts: list[int] = field(default_factory=list)   # raw-log attempt numbers (raw log only)


def make_game_id(seed: int, now=None) -> str:
    t = now or time.gmtime()
    return time.strftime("g-%Y%m%d-%H%M%S", t) + f"-s{seed}"


class Game:
    def __init__(self, cfg: Config, llm: LLM, seed: int, *, game_id: str | None = None,
                 log_path=None, clock=utc_now, progress=None, trial: dict | None = None, on_event=None,
                 batch: str | None = None, raw: RawLog | None = None, provenance: dict | None = None):
        self.cfg = cfg
        self.llm = llm
        self.seed = seed
        # Three independent streams (SPEC "Deals"): the deal is fixed by seed and seat index
        # whatever models are seated; the cast seats players; play covers everything else.
        self.deal = random.Random(f"{seed}:deal")
        self.cast = random.Random(f"{seed}:cast")
        self.rng = random.Random(f"{seed}:play")
        self.trial = trial
        self.batch = batch                  # name of the `batch` run that plays this game, or None
        self.game_id = game_id or make_game_id(seed)
        self.log = GameLog(self.game_id, log_path, clock, listener=on_event)
        self.progress = progress or (lambda msg: None)
        self.round = 0
        self.blown_jobs = 0
        self.clean_jobs = 0
        self.team: list[str] = []
        self.job_choices: dict[str, str] = {}
        self.players: list[Player] = []
        self.leader_seat = 0
        self.stmt_n: dict = {}
        self.clues_received: dict[str, list[dict]] = {}
        self.memory: dict[str, str] = {}
        self.system_prompts: dict[str, str] = {}
        self.result: dict | None = None
        self.job_names: list[str] = []
        # Scripted bots get the player's projected events instead of prompt text (SPEC "Bots").
        self.wants_view = bool(getattr(llm, "wants_view", False))
        self.needs_prompt = bool(getattr(llm, "needs_prompt", True))
        self._views: dict[str, tuple[list, int]] = {}
        # v0.4 dials (docs/V04.md): bot-only until their prompts are written.
        dials = cfg.game.v04_dials()
        if dials and self.needs_prompt:
            raise ValueError(f"v0.4 dials {', '.join(dials)} are on, but the prompts for these rules are not "
                             "written yet: they can only be played by a client that needs no prompt text "
                             "(the scripted bots, `bots` command)")
        self.crew_ejected = 0               # crew members voted out (mole_score_target)
        self.empty_votes = 0                # votes in a row with nobody out (vote_nobody)
        # Random whisper pairs (whisper_pairing = "random") have their own stream, so the deal and
        # play streams draw exactly what they draw with chosen pairs. Creating it draws nothing.
        self.whisper_rng = random.Random(f"{seed}:whispers")
        # Provenance (`code_fingerprint()`): stamped on game_start when given. The raw sidecar log
        # (docs/RAWLOG.md): when None, nothing below is done and no event changes.
        self.provenance = provenance
        self.raw = raw
        self._raw_on = raw is not None
        self._raw_warned = False
        self._raw_n = 0                     # next attempt number
        self._raw_schemas: set[str] = set()
        self._raw_sha: dict[str, str] = {}  # system text -> sha256

    # ------------------------------------------------------------------ helpers

    @property
    def by_name(self) -> dict[str, Player]:
        return {p.name: p for p in self.players}

    def seat_order(self) -> list[str]:
        return [p.name for p in self.players]

    def alive(self) -> list[str]:
        return [p.name for p in self.players if p.alive]

    def moles_alive(self) -> list[str]:
        return [p.name for p in self.players if p.alive and p.role == "mole"]

    def role_of(self, name: str) -> str:
        return self.by_name[name].role

    def others(self, name: str, pool=None) -> list[str]:
        return [n for n in (pool if pool is not None else self.alive()) if n != name]

    def write(self, *, phase: str, type: str, vis: str, round: int | None = None, **fields) -> dict:
        return self.log.write(round=self.round if round is None else round, phase=phase, type=type,
                              vis=vis, **fields)

    def mole_score(self) -> int:
        """v0.4 `mole_score_target`: blown jobs plus crew members voted out."""
        return self.blown_jobs + self.crew_ejected

    def score_fields(self) -> dict:
        """`crew_ejected` and `mole_score` for `round_start` / `game_end`, only with the dial on."""
        if self.cfg.game.mole_score_target > 0:
            return {"crew_ejected": self.crew_ejected, "mole_score": self.mole_score()}
        return {}

    def next_leader_seat(self) -> int:
        """The next alive seat clockwise from the current leader."""
        n = len(self.players)
        for i in range(1, n + 1):
            s = (self.leader_seat + i) % n
            if self.players[s].alive:
                return s
        return self.leader_seat

    def next_statement_id(self, finale: bool = False) -> str:
        key = "F" if finale else self.round
        self.stmt_n[key] = self.stmt_n.get(key, 0) + 1
        return f"F-S{self.stmt_n[key]}" if finale else f"R{self.round}-S{self.stmt_n[key]}"

    def caps(self, phase: str) -> dict:
        """Hard word caps for a turn: the limit the model is told plus the grace (SPEC section 6)."""
        lim = self.cfg.limits
        g = lim.word_grace
        return {"confessional": hard_cap(lim.confessional_words, g),
                "public": hard_cap(lim.whisper_words if phase == "whisper" else lim.public_words, g),
                "memory": hard_cap(lim.memory_words, g)}

    def challengeable(self, speaker: str) -> list[str]:
        """Statement ids from this round by other players, in order."""
        ids = []
        for e in self.log.events:
            if (e["type"] == "turn" and e["round"] == self.round and e.get("statement_id")
                    and e["phase"] in ("pick", "debate", "discuss", "vote") and e["player"] != speaker):
                ids.append(e["statement_id"])
        return ids

    # ------------------------------------------------------------------ model calls

    def view_for(self, player: str) -> list[dict]:
        """The player's projected visible events so far (only for clients with `wants_view`).

        Goes through `visible_to` / `project`, like the prompt builder; kept incrementally."""
        seen, cursor = self._views.get(player, ([], 0))
        events = self.log.events
        for ev in events[cursor:]:
            if visible_to(ev, player):
                pr = project(ev, player)
                if pr is not None:
                    seen.append(pr)
        self._views[player] = (seen, len(events))
        return list(seen)

    def prepare(self, player: str, phase: str, ctx: dict) -> tuple[str, str, dict, list | None]:
        """Build (system, prompt, schema, view) now, from the log as it stands."""
        ctx = dict(ctx, self=player)
        schema = turn_schema(phase, ctx)
        if self.needs_prompt:
            system = self.system_prompts[player]
            prompt = turn_prompt(self.log.events, player, self.cfg, phase, ctx)
        else:
            system = prompt = ""
        view = self.view_for(player) if self.wants_view else None
        return system, prompt, schema, view

    async def call_llm(self, *, view=None, **kw):
        if view is not None:
            return await self.llm.call(view=view, **kw)
        return await self.llm.call(**kw)

    async def ask(self, player: str, phase: str, ctx: dict, prepared=None) -> Pending:
        """One turn (SPEC section 4): validate, retry with the rejection line, fall back.

        A blocked attempt (the model's safety filter refused it) gets exactly one more attempt with
        the identical prompt, whatever `retries` says, and does not use up a retry; a second block
        ends the turn with the fallback. Nothing is reworded or substituted on a block."""
        ctx = dict(ctx, self=player)
        system, prompt, schema, view = prepared or self.prepare(player, phase, ctx)
        model = self.by_name[player].model
        usage = zero_usage()
        latency = 0.0
        served = None
        rejections: list[str] = []
        kinds: list[str] = []
        attempt_prompt = prompt
        attempts = blocked = fails = 0
        raw_ns: list[int] = []
        while True:
            attempts += 1
            reply = await self.call_llm(model=model, system=system, prompt=attempt_prompt, schema=schema,
                                        phase=phase, player=player, view=view)
            usage = add_usage(usage, reply.usage)
            latency += reply.latency_s or 0.0
            served = reply.served_model or served
            if reply.error:
                reason, kind = reply.error, reply.error_kind or "cli"
            else:
                cleaned, reason, trimmed = clean_reply(phase, reply.data, schema, ctx, self.caps(phase))
                if cleaned is not None:
                    if self._raw_on:
                        raw_ns.append(self.raw_attempt(phase, player, model, attempts, system, schema,
                                                       attempt_prompt, reply, None, None, trimmed))
                    return Pending(player, phase, cleaned, trimmed, attempts, usage, round(latency, 3),
                                   served, rejections, kinds, blocked, raw_attempts=raw_ns)
                kind = "invalid"
            rejections.append(reason)
            kinds.append(kind)
            if self._raw_on:
                raw_ns.append(self.raw_attempt(phase, player, model, attempts, system, schema, attempt_prompt,
                                               reply, reason, kind, []))
            if kind == "blocked":
                blocked += 1
                if blocked >= 2:
                    break
                continue                                   # identical prompt, no rejection line
            fails += 1
            if fails > self.cfg.limits.retries:
                break
            attempt_prompt = (prompt + f"\n\nYour previous reply was rejected: {reason}. "
                              "Reply again with valid JSON.")
        return Pending(player, phase, None, [], attempts, usage, round(latency, 3), served, rejections,
                       kinds, blocked, kinds[-1], raw_attempts=raw_ns)

    async def ask_parallel(self, jobs: list[tuple[str, str, dict]]) -> list[Pending]:
        """Simultaneous phase: every prompt is built before any reply is written."""
        prepared = [self.prepare(p, ph, ctx) for p, ph, ctx in jobs]
        return list(await asyncio.gather(*[self.ask(p, ph, ctx, prep)
                                           for (p, ph, ctx), prep in zip(jobs, prepared)]))

    def uniform_suspicion(self, player: str) -> dict:
        others = self.others(player)
        mr = len(self.moles_alive())
        val = round(100 * mr / len(others)) if others else 0
        return {o: val for o in others}

    def fallback(self, pend: Pending, ctx: dict) -> dict:
        """The documented fallback for a phase. Called in seat order so rng use is deterministic."""
        p, ph = pend.player, pend.phase
        public, action = "", {}
        if ph == "clue":
            if self.cfg.game.whispers and self.cfg.game.whisper_pairing == "chosen":
                action["whisper_with"] = NONE
            action["suspicion"] = self.uniform_suspicion(p)
        elif ph == "whisper":
            public = "(says nothing)"
            action = {"clue_cards": [], "suspicion": self.uniform_suspicion(p)}
        elif ph == "pick":
            n = ctx["team_size"]
            action["team"] = [p] + self.rng.sample(self.others(p), n - 1)
        elif ph == "job":
            action["choice"] = "help"
        elif ph == "discuss":
            action = {"accuse": NONE, "challenges": [], "clue_cards": [], "job_claim": "none",
                      "suspicion": self.uniform_suspicion(p)}
        elif ph == "vote":
            if ctx.get("vote_options"):                    # v0.4 vote_nobody: a failed vote abstains
                action = {"vote": NOBODY, "suspicion": self.uniform_suspicion(p)}
            else:
                action = {"vote": self.rng.choice(self.others(p)), "suspicion": self.uniform_suspicion(p)}
        elif ph == "debate":
            action = {"accuse": NONE, "challenges": [], "clue_cards": [], "approve": True,
                      "suspicion": self.uniform_suspicion(p)}
        elif ph == "final_accuse":
            action = {"accuse": self.rng.choice(self.others(p))}
        elif ph == "cut_pitch":
            public = "(no pitch)"
        elif ph == "cut_vote":
            action["finalist"] = self.rng.choice(ctx["others"])
        elif ph == "finale_pitch":
            action["stated_intent"] = "unstated"
        elif ph == "finale_choice":
            action["choice"] = "split"
        return {"confessional": "", "public": public, "claims": [], "memory": self.memory.get(p, ""),
                "action": action}

    def write_turn(self, pend: Pending, ctx: dict | None = None, **extra) -> dict:
        ctx = ctx or {}
        fb = pend.data is None
        data = self.fallback(pend, ctx) if fb else pend.data
        ph = pend.phase
        sid = None
        if (ph in STATEMENT_PHASES or ph in V04_STATEMENT_PHASES) and data["public"].strip() and not fb:
            sid = self.next_statement_id(finale=ph in ("cut_pitch", "finale_pitch", "final_accuse"))
        fields = {
            "player": pend.player, "model": self.by_name[pend.player].model, "turn_phase": ph,
            "confessional": data["confessional"], "public": data["public"], "claims": data["claims"],
            "memory": data["memory"], "action": data["action"],
        }
        if ph in SUSPICION_PHASES or ph in V04_SUSPICION_PHASES:
            fields["suspicion_kind"] = "table_read" if self.role_of(pend.player) == "mole" else "belief"
        if ph in ("discuss", "whisper", "debate"):
            fields["checks"] = self.checks(pend.player, data["action"])
        fields.update({"statement_id": sid, "truncated": bool(pend.truncated_fields),
                       "truncated_fields": list(pend.truncated_fields), "fallback": fb,
                       "attempts": pend.attempts, "served_model": pend.served_model, "usage": pend.usage,
                       "latency_s": pend.latency_s, "rejections": pend.rejections,
                       "error_kinds": pend.error_kinds, "blocked": pend.blocked,
                       "fallback_reason": pend.fallback_reason if fb else None})
        fields.update(extra)
        self.memory[pend.player] = data["memory"]
        ev = self.write(phase=LOG_PHASE[ph], type="turn", vis="engine", **fields)
        if self._raw_on:
            self.raw_write("turn", seq=ev["seq"], attempts=list(pend.raw_attempts), fallback=fb)
        label = f"R{self.round}" if ph not in FINALE_TURN_PHASES else "F"
        note = f" FALLBACK ({pend.fallback_reason})" if fb else (f" retry x{pend.attempts - 1}" if pend.attempts > 1 else "")
        self.progress(f"{label} {ph} {ctx.get('_n', '')}{pend.player}{note}".strip())
        return ev

    def checks(self, player: str, action: dict) -> dict:
        """Engine-only verdicts on a turn's clue cards and job claim (never shown to players)."""
        moles = [p.name for p in self.players if p.role == "mole"]
        cards = []
        for card in action.get("clue_cards") or []:
            clue = card_as_clue(card)
            cards.append({"card": card, "text": clue["text"],
                          "held": card_held(card, self.clues_received.get(player, [])),
                          "true_in_world": clue_is_true(clue, moles)})
        out = {"clue_cards": cards}
        claim = action.get("job_claim")
        if claim is not None:
            if claim == "none":
                out["job_claim"] = None
            else:
                actual = self.job_choices.get(player)
                out["job_claim"] = {"claimed": claim, "actual": actual,
                                    "lie": actual is None or (claim == "helped") != (actual == "help")}
        return out

    def team_size(self) -> int:
        g = self.cfg.game
        n = len(self.alive())
        return min(g.job_size if n >= 5 else g.job_size_small, n)

    def base_ctx(self, player: str) -> dict:
        return {"others": self.others(player), "alive": self.alive(), "role": self.role_of(player),
                "moles_remaining": len(self.moles_alive()), "leader": self.seat_order()[self.leader_seat],
                "whispers": self.cfg.game.whispers,
                "card_players": [p.name for p in self.players if p.name != player],
                "on_team": player in self.team,
                "partners": [n for n in self.moles_alive() if n != player] if self.role_of(player) == "mole" else []}

    # ------------------------------------------------------------------ setup

    def setup(self):
        cfg, g = self.cfg, self.cfg.game
        n = len(cfg.players)
        # The deal, by seat index, before any cast is looked at.
        mole_seats = sorted(self.deal.sample(range(n), g.num_moles))
        self.leader_seat = self.deal.randrange(n)
        codenames = self.deal.sample(CODENAMES, n)
        self.job_names = self.deal.sample(JOB_NAMES, len(JOB_NAMES))
        # The cast: who sits where.
        if all(p.role for p in cfg.players):
            moles_cfg = [p for p in cfg.players if p.role == "mole"]
            crew_cfg = [p for p in cfg.players if p.role == "crew"]
            seated = [moles_cfg.pop(0) if i in mole_seats else crew_cfg.pop(0) for i in range(n)]
        else:
            seated = list(cfg.players)
            self.cast.shuffle(seated)
        self.players = [Player(name=codenames[i] if g.anonymise else pc.name, model=pc.model,
                               model_name=pc.name, seat=i, role="mole" if i in mole_seats else "crew")
                        for i, pc in enumerate(seated)]
        self.write(phase="setup", type="game_start", vis="engine", round=0,
                   rules_version=RULES_VERSION, log_version=LOG_VERSION, seed=self.seed,
                   config=cfg.to_dict(), anonymised=g.anonymise, trial=self.trial, batch=self.batch,
                   players=[{"name": p.name, "model": p.model, "model_name": p.model_name, "seat": p.seat,
                             "role": p.role} for p in self.players],
                   moles=[p.name for p in self.players if p.role == "mole"], mole_seats=mole_seats,
                   first_leader=self.players[self.leader_seat].name,
                   **({"code_hash": self.provenance["code_hash"], "code_files": self.provenance["code_files"]}
                      if self.provenance else {}))
        self.write(phase="setup", type="table", vis="public", round=0, seats=self.seat_order(),
                   num_moles=g.num_moles, pot=g.pot)
        mole_names = [p.name for p in self.players if p.role == "mole"]
        for p in self.players:
            partners = [m for m in mole_names if m != p.name] if p.role == "mole" else []
            self.write(phase="setup", type="role", vis="private", round=0, player=p.name, role=p.role,
                       partners=partners)
        # The system prompt is fixed for the whole game (so it can be cached).
        for p in self.players:
            self.system_prompts[p.name] = (player_system_prompt(self.log.events, p.name, cfg)
                                           if self.needs_prompt else "")
        self.clues_received = {p.name: [] for p in self.players}
        if self._raw_on:
            self.raw_setup()

    # ------------------------------------------------------------------ phases

    async def phase_clue(self):
        g = self.cfg.game
        revealed = {p.name: p.role for p in self.players if not p.alive}
        moles = [p.name for p in self.players if p.role == "mole"]
        # Who gets intel: deal stream, before this round's clues, blind to role (SPEC section 5).
        recipients = draw_recipients(self.deal, self.alive(), g.clue_recipients, g.clue_recipients_spread)
        self.write(phase="clue", type="clue_deal", vis="engine", recipients=recipients, k=len(recipients))
        dealt: list[dict] = []                           # this round's clues (unique_clues)
        for name in self.alive():
            if name not in recipients:
                clue = dict(NONE_CLUE)
                self.clues_received[name].append(clue)
                self.write(phase="clue", type="clue", vis="private", player=name, clue=clue)
                continue
            for _ in range(g.clues_per_round):
                clue = generate_clue(rng=self.deal, players=self.seat_order(), alive=self.alive(), moles=moles,
                                     num_moles=g.num_moles, recipient=name, revealed=revealed,
                                     past_clues=self.clues_received[name], strength=g.clue_strength,
                                     avoid=dealt if g.unique_clues else None)
                dealt.append(clue)
                self.clues_received[name].append(clue)
                self.write(phase="clue", type="clue", vis="private", player=name, clue=clue)
        if not g.clue_turn:                              # v0.4: clues dealt, no clue-phase call
            return {}
        alive = self.alive()
        pend = await self.ask_parallel([(n, "clue", self.clue_ctx(n)) for n in alive])
        requests = {}
        for i, p in enumerate(pend):
            ev = self.write_turn(p, self.clue_ctx(p.player), )
            requests[p.player] = ev["action"].get("whisper_with", NONE)
        return requests

    def clue_ctx(self, player: str) -> dict:
        ctx = self.base_ctx(player)
        if self.cfg.game.whisper_pairing == "random":    # v0.4: no whisper request to make
            ctx["whispers"] = False
        return ctx

    def random_whisper_pairs(self) -> list[list[str]]:
        """v0.4 `whisper_pairing = "random"`: shuffle the alive players (seat order) with the
        whisper stream, pair them off, keep the first min(whisper_pairs_max, alive // 2) pairs.
        The first drawn of a pair speaks first."""
        pool = self.alive()
        self.whisper_rng.shuffle(pool)
        k = min(self.cfg.game.whisper_pairs_max, len(pool) // 2)
        return [[pool[2 * i], pool[2 * i + 1]] for i in range(k)]

    def pair_whispers(self, requests: dict) -> list[list[str]]:
        g = self.cfg.game
        if not g.whispers:
            return []
        order = [n for n in self.seat_order() if n in requests]
        free = set(order)
        pairs: list[list[str]] = []
        cap = g.whisper_pairs_max
        for a in order:                                 # mutual requests first, seat order
            b = requests.get(a, NONE)
            if len(pairs) >= cap:
                break
            if b != NONE and requests.get(b) == a and a in free and b in free:
                pairs.append([a, b])
                free -= {a, b}
        rest = [a for a in order if requests.get(a, NONE) != NONE and a in free]
        self.rng.shuffle(rest)
        for a in rest:
            if len(pairs) >= cap:
                break
            b = requests[a]
            if a in free and b in free:
                pairs.append([a, b])                    # initiator first
                free -= {a, b}
        return pairs

    async def phase_whispers(self, requests: dict):
        if not self.cfg.game.whispers:
            return
        if self.cfg.game.whisper_pairing == "random":
            pairs = self.random_whisper_pairs()
            self.write(phase="whisper", type="whisper_pairs", vis="public", pairs=pairs, pairing="random")
        else:
            pairs = self.pair_whispers(requests)
            self.write(phase="whisper", type="whisper_requests", vis="engine", requests=requests)
            self.write(phase="whisper", type="whisper_pairs", vis="public", pairs=pairs)
        ex = self.cfg.game.whisper_exchanges
        # Lockstep: step k of every pair runs in parallel; pairs cannot see each other's messages.
        for step in range(2 * ex):
            jobs = []
            for a, b in pairs:
                speaker, partner = (a, b) if step % 2 == 0 else (b, a)
                ctx = dict(self.base_ctx(speaker), partner=partner, index=step // 2 + 1, total=ex)
                jobs.append((speaker, "whisper", ctx))
            if not jobs:
                break
            results = await self.ask_parallel(jobs)
            for (speaker, _, ctx), pend in zip(jobs, results):
                self.write_turn(pend, ctx, partner=ctx["partner"])

    async def phase_pick(self, forced: bool = False) -> list[str]:
        leader = self.seat_order()[self.leader_seat]
        n = self.team_size()
        job_name = self.job_names[(self.round - 1) % len(self.job_names)]
        ctx = dict(self.base_ctx(leader), team_size=n, job_name=job_name)
        pend = await self.ask(leader, "pick", ctx)
        ev = self.write_turn(pend, ctx)
        team = list(ev["action"]["team"])
        self.team = team
        extra = {"forced": forced} if self.cfg.game.team_approval else {}
        self.write(phase="pick", type="job_pick", vis="public", leader=leader, team=team, job_name=job_name,
                   **extra)
        return team, job_name

    async def phase_debate(self, team: list[str]) -> bool:
        """v0.4 `team_approval`: one statement each, in discussion order, with approve / reject.
        Returns whether the team goes ahead (a strict majority of the alive players approve)."""
        leader = self.seat_order()[self.leader_seat]
        order = self.discussion_order()
        approvals: dict[str, bool] = {}
        for k, name in enumerate(order, 1):
            ctx = dict(self.base_ctx(name), order=order, team=team, challengeable=self.challengeable(name),
                       _n=f"{k}/{len(order)} ")
            pend = await self.ask(name, "debate", ctx)
            ev = self.write_turn(pend, ctx)
            approvals[name] = bool(ev["action"]["approve"])
        yes = sum(1 for v in approvals.values() if v)
        approved = yes > len(self.alive()) / 2
        self.write(phase="debate", type="team_vote", vis="public", leader=leader, team=team, approvals=approvals,
                   approve=yes, reject=len(approvals) - yes, approved=approved)
        self.progress(f"R{self.round} team vote: {yes}/{len(approvals)} approve, "
                      f"{'approved' if approved else 'REJECTED'}")
        return approved

    async def phase_job(self, team: list[str], job_name: str):
        moles_on = [n for n in team if self.role_of(n) == "mole"]
        choices = {n: "help" for n in team}
        if moles_on:
            jobs = [(n, "job", dict(self.base_ctx(n), team=team, job_name=job_name, blown_jobs=self.blown_jobs,
                                     clean_jobs=self.clean_jobs))
                    for n in moles_on]
            results = await self.ask_parallel(jobs)
            all_moles = [p.name for p in self.players if p.role == "mole"]
            for (n, _, ctx), pend in zip(jobs, results):
                ev = self.write_turn(pend, ctx, shared_with=[m for m in all_moles if m != n])
                choices[n] = ev["action"]["choice"]
        sab = sum(1 for c in choices.values() if c == "sabotage")
        blown = sab >= 1
        if blown:
            self.blown_jobs += 1
        else:
            self.clean_jobs += 1
        self.job_choices = choices
        self.write(phase="job", type="job_choices", vis="engine", choices=choices)
        self.write(phase="job", type="job_result", vis="public", team=team, sabotages=sab, blown=blown,
                   clean_jobs=self.clean_jobs, blown_jobs=self.blown_jobs)
        self.progress(f"R{self.round} job: {'BLOWN' if blown else 'clean'} - score clean "
                      f"{self.clean_jobs}/{self.cfg.game.clean_target}, blown "
                      f"{self.blown_jobs}/{self.cfg.game.sabotage_target}")

    def discussion_order(self) -> list[str]:
        seats = self.seat_order()
        n = len(seats)
        order = []
        for i in range(1, n + 1):
            name = seats[(self.leader_seat + i) % n]
            if self.by_name[name].alive:
                order.append(name)
        return order                                  # left of the leader first, leader last

    async def phase_discuss(self):
        order = self.discussion_order()
        passes = self.cfg.game.discussion_passes
        total = passes * len(order)
        k = 0
        for ps in range(1, passes + 1):
            for name in order:
                k += 1
                ctx = dict(self.base_ctx(name), order=order, challengeable=self.challengeable(name),
                           passes=passes, _n=f"{k}/{total} ")
                ctx["pass"] = ps
                pend = await self.ask(name, "discuss", ctx)
                self.write_turn(pend, ctx, **{"pass": ps})

    def vote_is_forced(self) -> bool:
        """v0.4 `vote_nobody`: after `forced_vote_after` votes in a row with nobody out, the next
        vote has no `nobody` option and uses the plurality rule (0 = never forced)."""
        g = self.cfg.game
        return g.forced_vote_after > 0 and self.empty_votes >= g.forced_vote_after

    def vote_ctx(self, player: str, nobody_ok: bool) -> dict:
        ctx = self.base_ctx(player)
        if nobody_ok:
            ctx["vote_options"] = self.others(player) + [NOBODY]
        return ctx

    async def phase_vote(self):
        g = self.cfg.game
        alive = self.alive()
        leader = self.seat_order()[self.leader_seat]
        forced = g.vote_nobody and self.vote_is_forced()
        nobody_ok = g.vote_nobody and not forced
        jobs = [(n, "vote", self.vote_ctx(n, nobody_ok)) for n in alive]
        results = await self.ask_parallel(jobs)
        votes = {}
        for (n, _, ctx), pend in zip(jobs, results):
            ev = self.write_turn(pend, ctx)
            votes[n] = ev["action"]["vote"]
        tally = {}
        for t in votes.values():
            tally[t] = tally.get(t, 0) + 1
        if nobody_ok:
            self.resolve_nobody_vote(votes, tally, len(alive))
            return
        top = max(tally.values())
        tied = [n for n in self.seat_order() if tally.get(n) == top]
        tiebreak = None
        if len(tied) == 1:
            out = tied[0]
            tied_list = []
        else:
            tied_list = tied
            if votes.get(leader) in tied:
                out, tiebreak = votes[leader], "leader"
            else:
                out, tiebreak = self.rng.choice(tied), "random"
        self.by_name[out].eliminated_round = self.round
        tally_sorted = {n: tally[n] for n in self.seat_order() if n in tally}
        extra = {"forced": True, "needed": None} if g.vote_nobody else {}
        self.after_ejection(out)
        self.write(phase="vote", type="vote_result", vis="public", votes=votes, tally=tally_sorted,
                   tied=tied_list, tiebreak=tiebreak, eliminated=out, role=self.role_of(out), **extra)
        self.progress(f"R{self.round} vote: {out} out ({self.role_of(out)})")

    def after_ejection(self, out: str | None):
        if out is None:
            self.empty_votes += 1
            return
        self.empty_votes = 0
        if self.role_of(out) == "crew":
            self.crew_ejected += 1

    def resolve_nobody_vote(self, votes: dict, tally: dict, voters: int):
        """v0.4 `vote_nobody`: a player goes only with a strict majority of the alive voters;
        otherwise nobody goes. No tie-break, no random draw."""
        needed = voters // 2 + 1
        tally_sorted = {n: tally[n] for n in self.seat_order() if n in tally}
        if NOBODY in tally:
            tally_sorted[NOBODY] = tally[NOBODY]
        top = [n for n in self.seat_order() if tally.get(n, 0) >= needed]
        out = top[0] if top else None
        if out is not None:
            self.by_name[out].eliminated_round = self.round
        self.after_ejection(out)
        self.write(phase="vote", type="vote_result", vis="public", votes=votes, tally=tally_sorted, tied=[],
                   tiebreak=None, eliminated=out, role=self.role_of(out) if out else None, forced=False,
                   needed=needed)
        self.progress(f"R{self.round} vote: " + (f"{out} out ({self.role_of(out)})" if out
                                                 else f"nobody out (needed {needed})"))

    async def phase_recap(self):
        """One narrator call (no retries), except that a blocked call is tried once more, unchanged."""
        nar = self.cfg.narrator
        prompt = narrator_prompt(self.log.events, self.round, self.cfg) if self.needs_prompt else ""
        system = NARRATOR_SYSTEM if self.needs_prompt else ""
        usage, latency, served, attempts, blocked = zero_usage(), 0.0, None, 0, 0
        replies = []                                       # raw log only
        while True:
            attempts += 1
            reply = await self.llm.call(model=nar.model, system=system, prompt=prompt,
                                        schema=narrator_schema(), phase="recap", player=None)
            if self._raw_on:
                replies.append(reply)
            usage = add_usage(usage, reply.usage)
            latency += reply.latency_s or 0.0
            served = reply.served_model or served
            if reply.error and (reply.error_kind == "blocked"):
                blocked += 1
                if blocked < 2:
                    continue
            break
        text, error = "", reply.error
        kind = (reply.error_kind or "cli") if error else None
        trimmed = False
        if not error:
            d = reply.data
            if isinstance(d, dict) and isinstance(d.get("recap"), str):
                text, trimmed = truncate_words(d["recap"], hard_cap(nar.recap_words, self.cfg.limits.word_grace))
            else:
                error, kind = "recap missing", "invalid"
        ev = self.write(phase="recap", type="recap", vis="public", text=text, model=nar.model, usage=usage,
                        served_model=served, latency_s=round(latency, 3), error=error, error_kind=kind,
                        attempts=attempts, blocked=blocked, fallback_reason=kind)
        if self._raw_on:
            ns = []
            for i, r in enumerate(replies):
                if i < len(replies) - 1:                   # a blocked attempt that was tried again
                    ns.append(self.raw_attempt("recap", None, nar.model, i + 1, system, narrator_schema(), prompt,
                                               r, r.error, r.error_kind or "cli", []))
                else:
                    ns.append(self.raw_attempt("recap", None, nar.model, i + 1, system, narrator_schema(), prompt,
                                               r, error, kind, ["recap"] if trimmed else []))
            self.raw_write("turn", seq=ev["seq"], attempts=ns, fallback=error is not None)

    # ------------------------------------------------------------------ raw sidecar log

    def raw_warn(self, what: str, e: OSError):
        if not self._raw_warned:
            self._raw_warned = True
            print(f"warning: raw log {self.raw.path}: {what} failed ({e}); no more raw records for game "
                  f"{self.game_id} (the game goes on)", file=sys.stderr)

    def raw_write(self, kind: str, **fields):
        """Write one raw record. A failing write (disk full, permission) stops the raw log for this
        game with one warning; it never stops the game."""
        if not self._raw_on:
            return
        try:
            self.raw.write({"kind": kind, "game_id": self.game_id, **fields})
        except OSError as e:
            self._raw_on = False
            self.raw_warn("write", e)

    def raw_close(self):
        try:
            self.raw.close()
        except OSError as e:
            self.raw_warn("close", e)

    def sha_of(self, text: str) -> str:
        h = self._raw_sha.get(text)
        if h is None:
            h = self._raw_sha[text] = sha256_text(text)
        return h

    def raw_setup(self):
        """The header and one `system` record per player and for the narrator."""
        lim = self.cfg.limits
        fp = self.provenance or code_fingerprint()
        argv = build_argv("<model>", "<system>", "<prompt>", {}, getattr(self.llm, "claude_bin", "claude"),
                          getattr(self.llm, "effort", lim.effort))
        argv[argv.index("--json-schema") + 1] = "<schema>"
        self.raw_write("header", seed=self.seed, rules_version=RULES_VERSION, log_version=LOG_VERSION,
                       code_hash=fp["code_hash"], code_files=fp["code_files"],
                       conditions={"max_thinking_tokens": lim.max_thinking_tokens, "effort": lim.effort},
                       argv_template=argv, client=type(self.llm).__name__)
        for p in self.players:
            text = self.system_prompts[p.name]
            self.raw_write("system", player=p.name, model=p.model, sha256=self.sha_of(text), text=text)
        text = NARRATOR_SYSTEM if self.needs_prompt else ""
        self.raw_write("system", player=None, model=self.cfg.narrator.model, sha256=self.sha_of(text), text=text)

    def raw_attempt(self, phase: str, player: str | None, model: str, attempt: int, system: str, schema: dict,
                    prompt: str, reply, rejection: str | None, error_kind: str | None,
                    trimmed: list[str]) -> int:
        """Record one call attempt (and its schema, the first time it is seen); returns its number.
        `rejection` None means the attempt's reply was used."""
        n = self._raw_n
        self._raw_n += 1
        sh = schema_sha256(schema)
        if sh not in self._raw_schemas:
            self._raw_schemas.add(sh)
            self.raw_write("schema", sha256=sh, schema=schema)
        self.raw_write("attempt", n=n, round=self.round, phase=phase, player=player, model=model, attempt=attempt,
                       system_sha256=self.sha_of(system), schema_sha256=sh, prompt=prompt,
                       stdout=getattr(reply, "raw_stdout", "") or "",
                       stderr_tail=getattr(reply, "stderr_tail", "") or "",
                       returncode=getattr(reply, "returncode", None), error=reply.error, error_kind=error_kind,
                       served_model=reply.served_model, usage=reply.usage, latency_s=reply.latency_s,
                       ts=self.log.clock(), accepted=rejection is None, rejection=rejection,
                       trimmed_fields=list(trimmed) if rejection is None else [])
        return n

    # ------------------------------------------------------------------ end

    def end_check(self, after: str) -> tuple[str, str] | None:
        """Order from SPEC section 6. The clock only runs out once a round's vote is done."""
        g = self.cfg.game
        if g.mole_score_target > 0:
            # v0.4: the moles' score replaces the sabotage target; max_rounds = 0 means no clock.
            if self.mole_score() >= g.mole_score_target:
                return "moles", "mole_score"
        elif self.blown_jobs >= g.sabotage_target:
            return "moles", "sabotage"
        if self.clean_jobs >= g.clean_target:
            return "crew", "jobs_clean"
        moles = self.moles_alive()
        if not moles:
            return "crew", "moles_out"
        if len(self.alive()) <= 2:
            return "moles", "final_two"
        if g.mole_score_target > 0 and g.max_rounds == 0:
            return None
        if after == "vote" and self.round >= self.cfg.rounds_limit:
            return "moles", "clock"
        return None

    def vote_record(self, name: str) -> int:
        """Votes this player cast against players revealed as moles."""
        n = 0
        for e in self.log.events:
            if e["type"] == "vote_result":
                tgt = e["votes"].get(name)
                if tgt and tgt in self.by_name and self.role_of(tgt) == "mole":   # not "nobody" (v0.4)
                    n += 1
        return n

    async def run_cut(self, survivors: list[str]) -> list[str]:
        for name in survivors:
            ctx = dict(self.base_ctx(name), survivors=survivors, others=self.others(name, survivors))
            pend = await self.ask(name, "cut_pitch", ctx)
            self.write_turn(pend, ctx)
        jobs = [(n, "cut_vote", dict(self.base_ctx(n), survivors=survivors, others=self.others(n, survivors)))
                for n in survivors]
        results = await self.ask_parallel(jobs)
        votes = {}
        for (n, _, ctx), pend in zip(jobs, results):
            ev = self.write_turn(pend, ctx)
            votes[n] = ev["action"]["finalist"]
        tally = {n: 0 for n in survivors}
        for t in votes.values():
            tally[t] += 1
        finalists: list[str] = []
        tiebreak = None
        for v in sorted(set(tally.values()), reverse=True):
            group = [n for n in survivors if tally[n] == v]
            need = 2 - len(finalists)
            if need <= 0:
                break
            if len(group) <= need:
                finalists += group
                continue
            # Boundary tie: best record of votes against moles, then random.
            recs = {n: self.vote_record(n) for n in group}
            ranked = sorted(group, key=lambda n: -recs[n])
            cutoff = recs[ranked[need - 1]]
            sure = [n for n in ranked if recs[n] > cutoff]
            maybe = [n for n in ranked if recs[n] == cutoff]
            finalists += sure
            rest = need - len(sure)
            if len(maybe) == rest:
                finalists += maybe
                tiebreak = "record"
            else:
                finalists += self.rng.sample(maybe, rest)
                tiebreak = "random"
        finalists = [n for n in survivors if n in finalists]
        self.write(phase="cut", type="cut_result", vis="public", votes=votes, tally=tally,
                   finalists=finalists, tiebreak=tiebreak)
        return finalists

    async def run_finale(self, finalists: list[str]) -> dict:
        g = self.cfg.game
        a, b = finalists
        stated = {a: "unstated", b: "unstated"}
        for i in range(g.finale_exchanges):
            for me, opp in ((a, b), (b, a)):
                ctx = dict(self.base_ctx(me), opponent=opp, index=i + 1, total=g.finale_exchanges)
                pend = await self.ask(me, "finale_pitch", ctx)
                ev = self.write_turn(pend, ctx)
                stated[me] = ev["action"]["stated_intent"]
        jobs = [(n, "finale_choice", dict(self.base_ctx(n), opponent=o)) for n, o in ((a, b), (b, a))]
        results = await self.ask_parallel(jobs)
        choices = {}
        for (n, _, ctx), pend in zip(jobs, results):
            ev = self.write_turn(pend, ctx)
            choices[n] = ev["action"]["choice"]
        pay = payoffs(choices[a], choices[b], g.pot)
        payouts = {a: pay[0], b: pay[1]}
        self.write(phase="finale", type="finale_result", vis="public", finalists=[a, b], choices=choices,
                   stated=stated, payouts=payouts)
        return payouts

    async def endgame(self, winner: str, reason: str) -> dict:
        """Finalists always come from the winning side's survivors."""
        if self.cfg.game.endings == "stakes":
            return await self.endgame_stakes(winner, reason)
        side = "crew" if winner == "crew" else "mole"
        winners = [n for n in self.alive() if self.role_of(n) == side]
        payouts = {p.name: 0 for p in self.players}
        if len(winners) > 2:
            finalists = await self.run_cut(winners)
        else:
            finalists = winners
        if len(finalists) == 2:
            payouts.update(await self.run_finale(finalists))
        elif len(finalists) == 1:
            payouts[finalists[0]] = self.cfg.game.pot      # lone winning survivor takes the pot
        return payouts

    def share(self, names: list[str]) -> dict:
        """The pot shared equally (`pot // k` each; any remainder is not paid out)."""
        return {n: self.cfg.game.pot // len(names) for n in names} if names else {}

    async def endgame_stakes(self, winner: str, reason: str) -> dict:
        """v0.4 `endings = "stakes"`: no Cut, no crew split / steal (docs/V04.md)."""
        payouts = {p.name: 0 for p in self.players}
        moles = self.moles_alive()
        if winner == "moles":
            if len(moles) == 2:
                payouts.update(await self.run_finale(moles))
            elif len(moles) == 1:
                payouts[moles[0]] = self.cfg.game.pot
            else:
                payouts.update(self.share(moles))         # more than two moles (num_moles > 2)
        elif reason == "jobs_clean" and moles:
            payouts.update(await self.run_final_accusation())
        else:
            payouts.update(self.share([n for n in self.alive() if self.role_of(n) == "crew"]))
        return payouts

    async def run_final_accusation(self) -> dict:
        """Every alive player names one other alive player at once; plurality, random tie-break.
        Hit (a mole): the alive crew share the pot; miss: the alive moles share it."""
        alive = self.alive()
        jobs = [(n, "final_accuse", self.base_ctx(n)) for n in alive]
        results = await self.ask_parallel(jobs)
        votes = {}
        for (n, _, ctx), pend in zip(jobs, results):
            ev = self.write_turn(pend, ctx)
            votes[n] = ev["action"]["accuse"]
        tally = {}
        for t in votes.values():
            tally[t] = tally.get(t, 0) + 1
        top = max(tally.values())
        tied = [n for n in self.seat_order() if tally.get(n) == top]
        if len(tied) == 1:
            accused, tied_list, tiebreak = tied[0], [], None
        else:
            accused, tied_list, tiebreak = self.rng.choice(tied), tied, "random"
        role = self.role_of(accused)
        hit = role == "mole"
        side = "crew" if hit else "mole"
        payouts = self.share([n for n in alive if self.role_of(n) == side])
        self.write(phase="finale", type="final_accusation", vis="public", votes=votes,
                   tally={n: tally[n] for n in self.seat_order() if n in tally}, tied=tied_list,
                   tiebreak=tiebreak, accused=accused, role=role, hit=hit, payouts=payouts)
        self.progress(f"final accusation: {accused} ({role}) - {'hit' if hit else 'miss'}")
        return payouts

    # ------------------------------------------------------------------ main loop

    async def play(self) -> dict:
        if self.raw is None:
            return await self._play()
        try:
            return await self._play()
        finally:
            self.raw_close()                            # gzip it whether the game ended or raised

    async def _play(self) -> dict:
        t0 = time.monotonic()
        self.setup()
        n = len(self.players)
        outcome = None
        while outcome is None:
            self.round += 1
            if self.round > 1:
                for i in range(1, n + 1):
                    s = (self.leader_seat + i) % n
                    if self.players[s].alive:
                        self.leader_seat = s
                        break
            leader = self.seat_order()[self.leader_seat]
            self.team, self.job_choices = [], {}
            self.write(phase="clue", type="round_start", vis="public", leader=leader, alive=self.alive(),
                       clean_jobs=self.clean_jobs, blown_jobs=self.blown_jobs, **self.score_fields())
            self.progress(f"R{self.round} start: leader {leader}, {len(self.alive())} alive")
            requests = await self.phase_clue()
            await self.phase_whispers(requests)
            team, job_name = await self.phase_pick()
            if self.cfg.game.team_approval and not await self.phase_debate(team):
                # Rejected: the lead passes to the next alive seat and stays there; that leader's
                # team is forced (no second debate).
                self.leader_seat = self.next_leader_seat()
                team, job_name = await self.phase_pick(forced=True)
            await self.phase_job(team, job_name)
            outcome = self.end_check("job")
            if outcome:
                break
            await self.phase_discuss()
            await self.phase_vote()
            await self.phase_recap()
            outcome = self.end_check("vote")
        winner, reason = outcome
        self.progress(f"game over: {winner} win ({reason})")
        payouts = await self.endgame(winner, reason)
        from .results import usage_from_events
        usage, calls = usage_from_events(self.log.events)
        fallbacks = sum(1 for e in self.log.events if e["type"] == "turn" and e.get("fallback"))
        lim = self.cfg.limits
        ev = self.write(phase="end", type="game_end", vis="public", winner=winner, reason=reason,
                        clean_jobs=self.clean_jobs, blown_jobs=self.blown_jobs, **self.score_fields(),
                        rounds=self.round,
                        survivors=self.alive(), payouts=payouts, usage=usage, calls=calls, fallbacks=fallbacks,
                        blocked=usage["total"]["blocked"],
                        conditions={"max_thinking_tokens": lim.max_thinking_tokens, "effort": lim.effort},
                        wall_s=round(time.monotonic() - t0, 3))
        self.result = ev
        self.log.close()
        return ev

    def run(self) -> dict:
        return asyncio.run(self.play())


def payoffs(a: str, b: str, pot: int) -> tuple[int, int]:
    if a == "split" and b == "split":
        return pot // 2, pot // 2
    if a == "steal" and b == "split":
        return pot, 0
    if a == "split" and b == "steal":
        return 0, pot
    return 0, 0
