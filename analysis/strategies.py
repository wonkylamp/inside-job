"""Scripted crew and mole policies for the best-response search (analysis only, no model calls).

Every policy is a subclass of `inside_job.bots.Bot`: it acts only on the player's projected view
(`inside_job.log.visible_to` / `project`, handed over by the engine), the reply schema and the
config, exactly like the shipped bots. When a spec matches a shipped bot (logician; always /
never / smart moles with decoy or no cards) the shipped methods are called unchanged, so those
cells reproduce `python3.11 -m inside_job bots` seed for seed.

Specs are plain dicts so they pickle into worker processes.

Crew spec keys
  reason  solver | jobs_only | own_only | bayes      what the belief is built from
  q       sabotage probability for `bayes`
  share   True | False   table / whisper own real clues
  skill   probability of acting by the rule (else uniformly random), as the logician's skill
  target  logic | bandwagon | blown_seat | seat | blown_seat_dull   who to accuse and vote for
  pick    logic | repeat_clean | no_blown | no_blown_dull           team choice as leader
  report  own | exact | base | public | shrink:<k> | push | bayes:<q>   what is written in suspicion

Mole spec keys
  sab     always | never | smart | late | closer | leader_clean      when to sabotage (and pick)
  k       round from which `late` sabotages
  cards   decoy | none | true
  talk    smart | mute | mimic | bus | target_trusted
  thr     public posterior at which `bus` turns on the partner
  report  own | base | public | shrink:<k> | push | truth | crew_cond   table_read variant
"""

from __future__ import annotations

import random
from itertools import combinations

from inside_job.bots import Bot, BotLLM, _card, _key
from inside_job.clues import card_as_clue, clue_is_true
from inside_job.solver import player_worlds, posterior, table_worlds

# --------------------------------------------------------------------------- specs

CREW_DEFAULT = {"reason": "solver", "q": 0.9, "share": True, "skill": 1.0, "target": "logic",
                "pick": "logic", "report": "own"}
MOLE_DEFAULT = {"sab": "smart", "k": 3, "cards": "decoy", "talk": "smart", "thr": 0.5, "report": "own"}


def crew(**kw) -> dict:
    d = dict(CREW_DEFAULT)
    d.update(kw)
    return d


def mole(**kw) -> dict:
    d = dict(MOLE_DEFAULT)
    d.update(kw)
    return d


CREW_POLICIES = {
    "logician_1.0": crew(skill=1.0),
    "logician_0.7": crew(skill=0.7),
    "logician_0.4": crew(skill=0.4),
    "silent": crew(share=False),
    "jobs_only": crew(reason="jobs_only"),
    "own_only": crew(reason="own_only"),
    "bandwagon": crew(target="bandwagon"),
    "random": crew(skill=0.0),
    "repeat_clean": crew(pick="repeat_clean"),
    "no_blown": crew(pick="no_blown"),
    "blown_seat": crew(target="blown_seat"),
    "dull_jobs": crew(reason="jobs_only", pick="no_blown_dull", target="blown_seat_dull", share=False),
    "bayes_crew": crew(reason="bayes", q=0.9),
}
# Which crew policies are "dull" (no reasoning or no interaction) and which reason.
CREW_DULL = {"silent", "jobs_only", "own_only", "bandwagon", "random", "repeat_clean", "no_blown",
             "blown_seat", "dull_jobs", "logician_0.4"}
# Defined but left out of the matrix to keep the run near 20 minutes. `late3` plays identically to
# `closer` at clean_target 3 (helping in rounds 1-2 gives two clean jobs, which turns `closer` on in
# round 3), checked in the pilot: every number matched.
EXTRA_CREW = {"seat_vote": crew(target="seat")}
EXTRA_MOLES = {"late3": mole(sab="late", k=3)}

MOLE_POLICIES = {
    "smart+decoy": mole(sab="smart", cards="decoy"),
    "smart+none": mole(sab="smart", cards="none"),
    "always+decoy": mole(sab="always", cards="decoy"),
    "always+none": mole(sab="always", cards="none"),
    "never+decoy": mole(sab="never", cards="decoy"),
    "never+none": mole(sab="never", cards="none"),
    "late2": mole(sab="late", k=2),
    "closer": mole(sab="closer"),
    "bus": mole(talk="bus", thr=0.5),
    "mute": mole(talk="mute", cards="none"),
    "mimic": mole(talk="mimic", cards="true"),
    "leader_clean": mole(sab="leader_clean"),
    "target_trusted": mole(talk="target_trusted"),
}
MOLE_DULL = {"always+decoy", "always+none", "never+decoy", "never+none", "mute", "closer", "late2"}


# --------------------------------------------------------------------------- shared maths

def job_likelihood(w: frozenset, jobs, q: float) -> float:
    """P(observed sabotage counts | moles = w) when each mole on a team sabotages with prob. q."""
    from math import comb
    lk = 1.0
    for team, sab in jobs:
        k = sum(1 for t in team if t in w)
        if sab > k:
            return 0.0
        lk *= comb(k, sab) * (q ** sab) * ((1 - q) ** (k - sab))
    return lk


def weighted_posterior(worlds, players, jobs, q: float, fallback=None) -> dict:
    """Like `solver.posterior`, but each consistent world weighted by the job likelihood."""
    use = list(worlds) or list(fallback or [])
    ws = [job_likelihood(w, jobs, q) for w in use]
    tot = sum(ws)
    if tot <= 0:
        return posterior(use, players)
    return {n: sum(wt for w, wt in zip(use, ws) if n in w) / tot for n in players}


def shrink(p: dict, base: float, k: float) -> dict:
    return {n: base + k * (v - base) for n, v in p.items()}


# --------------------------------------------------------------------------- extra view state

class _Extra:
    """Public facts the shipped `_State` does not keep: accusations, leaders, votes."""

    def __init__(self):
        self.n = 0
        self.accusations: dict[int, list[str]] = {}   # round -> accused names in order
        self.picks: dict[int, list[str]] = {}         # round -> team
        self.results: dict[int, int] = {}             # round -> sabotages

    def update(self, view):
        for e in view[self.n:]:
            t = e["type"]
            if t == "turn" and e.get("turn_phase") == "discuss":
                acc = (e.get("action") or {}).get("accuse")
                if acc and acc != "none":
                    self.accusations.setdefault(e["round"], []).append(acc)
            elif t == "job_pick":
                self.picks[e["round"]] = list(e["team"])
            elif t == "job_result":
                self.results[e["round"]] = e["sabotages"]
        self.n = len(view)


# --------------------------------------------------------------------------- the bot

class PolicyBot(Bot):
    def __init__(self, me, rng, cfg, cspec: dict, mspec: dict, role_hint: str):
        kind = "logician" if role_hint == "crew" else (mspec["sab"] if mspec["sab"] in ("always", "never", "smart")
                                                       else "smart")
        super().__init__(me, kind, rng, cfg, cspec["skill"], mspec["cards"] if mspec["cards"] in ("decoy", "none")
                         else "none")
        self.c, self.m = cspec, mspec
        self.x = _Extra()
        self._bkey = None
        self._bval = None
        self._tkey = None
        self._tval = None

    # ------------------------------------------------------------- state keys and beliefs
    def _skey(self):
        s = self.s
        return (len(s.cards), len(s.pair_cards), len(s.own_clues), len(s.jobs), len(s.revealed))

    def _fallback_worlds(self):
        s = self.s
        return [w for w in table_worlds(s.seats, s.num_moles, s.revealed, [], s.jobs) if self.me not in w]

    def belief(self) -> dict:
        s = self.s
        if s.role != "crew":
            return self.table_read()
        key = self._skey()
        if key == self._bkey:
            return self._bval
        mode = self.c["reason"]
        fb = self._fallback_worlds()
        if mode in ("solver", "bayes"):
            worlds = player_worlds(s.seats, s.num_moles, s.revealed, s.cards, s.jobs, player=self.me,
                                   own_clues=s.own_clues, pair_cards=s.pair_cards)
        elif mode == "own_only":
            worlds = player_worlds(s.seats, s.num_moles, s.revealed, [], s.jobs, player=self.me,
                                   own_clues=s.own_clues, pair_cards=[])
        elif mode == "jobs_only":
            worlds = fb
        else:
            raise ValueError(mode)
        if mode == "bayes":
            val = weighted_posterior(worlds, s.seats, s.jobs, self.c["q"], fb)
        else:
            val = posterior(worlds, s.seats, fb)
        self._bkey, self._bval = key, val
        return val

    def table_read(self) -> dict:
        key = self._skey()
        if key == self._tkey:
            return self._tval
        val = super().table_read()
        self._tkey, self._tval = key, val
        return val

    def exact(self) -> dict:
        """The ideal reasoner on this seat's view (for report variants)."""
        s = self.s
        worlds = player_worlds(s.seats, s.num_moles, s.revealed, s.cards, s.jobs, player=self.me,
                               own_clues=s.own_clues, pair_cards=s.pair_cards)
        return posterior(worlds, s.seats, self._fallback_worlds())

    def crewlike(self) -> dict:
        """A mole pretending to be crew: public worlds without itself (mimic)."""
        s = self.s
        worlds = [w for w in table_worlds(s.seats, s.num_moles, s.revealed, s.cards, s.jobs) if self.me not in w]
        return posterior(worlds, s.seats, self._fallback_worlds())

    def base_rate(self) -> float:
        s = self.s
        out = sum(1 for r in s.revealed.values() if r == "mole")
        others = [a for a in s.alive if a != self.me]
        return (s.num_moles - out) / len(others) if others else 0.0

    # ------------------------------------------------------------- reports
    def suspicion(self, schema, probs):
        rep = (self.c if self.s.role == "crew" else self.m)["report"]
        if rep == "own":
            return super().suspicion(schema, probs)
        s = self.s
        base = self.base_rate()
        if rep == "base":
            p = {n: base for n in s.seats}
        elif rep == "public":
            p = Bot.table_read(self)
        elif rep == "exact":
            p = self.exact()
        elif rep.startswith("shrink:"):
            src = self.exact() if s.role == "crew" else Bot.table_read(self)
            p = shrink(src, base, float(rep.split(":")[1]))
        elif rep == "push":
            src = self.exact() if s.role == "crew" else Bot.table_read(self)
            p = {n: 1.0 if v >= 0.5 else 0.0 for n, v in src.items()}
        elif rep.startswith("bayes:"):
            worlds = player_worlds(s.seats, s.num_moles, s.revealed, s.cards, s.jobs, player=self.me,
                                   own_clues=s.own_clues, pair_cards=s.pair_cards)
            p = weighted_posterior(worlds, s.seats, s.jobs, float(rep.split(":")[1]), self._fallback_worlds())
        elif rep == "truth":
            p = {n: 1.0 if n in self.moles else 0.0 for n in s.seats}
        elif rep == "crew_cond":
            p = crew_cond(s.seats, s.num_moles, s.revealed, s.cards, s.jobs,
                          [a for a in s.alive if a not in self.moles])
        else:
            raise ValueError(rep)
        return super().suspicion(schema, p)

    # ------------------------------------------------------------- turns
    def turn(self, phase, schema, view):
        self.x.update(view)
        return super().turn(phase, schema, view)

    def do_clue(self, out, props, schema):
        super().do_clue(out, props, schema)

    def do_whisper(self, out, props, schema):
        s = self.s
        if s.role == "crew":
            if self.c["share"]:
                return super().do_whisper(out, props, schema)
            out["public"] = "Nothing for you yet. Watch the team."
            out["action"] = {"clue_cards": [], "suspicion": self.suspicion(schema, self.belief())}
            return
        if self.m["talk"] == "mute":
            out["public"] = "..."
            out["action"] = {"clue_cards": [], "suspicion": self.suspicion(schema, self.table_read())}
            return
        if self.m["cards"] == "true":
            cards = [_card(c) for c in self.safe_true_clues()][:2]
            out["public"] = "Here is what I have." if cards else "Nothing for you yet. Watch the team."
            out["claims"] = [{"text": f"my clue: {card_as_clue(c)['text']}", "truthful": True} for c in cards]
            out["action"] = {"clue_cards": cards, "suspicion": self.suspicion(schema, self.table_read())}
            return
        return super().do_whisper(out, props, schema)

    # ------------------------------------------------------------- pick
    def do_pick(self, out, props, schema):
        s = self.s
        if s.role == "crew":
            if self.c["pick"] == "logic":                       # shipped rule on this bot's belief
                return super().do_pick(out, props, schema)
            n = props["team"]["minItems"]
            alive = list(props["team"]["items"]["enum"])
            others = [a for a in alive if a != self.me]
            if self.random_act():
                team = self.rng.sample(alive, n)
            else:
                team = self.crew_team(n, alive, others)
            out["public"] = f"Team: {', '.join(team)}."
            out["action"] = {"team": team}
            return
        sab = self.m["sab"]
        if sab == "leader_clean" or self.m["talk"] == "mimic":
            n = props["team"]["minItems"]
            alive = list(props["team"]["items"]["enum"])
            others = [a for a in alive if a != self.me]
            if sab == "leader_clean":
                pool = [o for o in others if o not in self.moles]
                team = self.least(pool, self.table_read(), n)
                if len(team) < n:
                    team += [o for o in alive if o not in team][: n - len(team)]
            else:
                team = [self.me] + self.least(others, self.crewlike(), n - 1)
            out["public"] = f"Team: {', '.join(team)}."
            out["action"] = {"team": team}
            return
        return super().do_pick(out, props, schema)

    def crew_team(self, n, alive, others):
        mode = self.c["pick"]
        probs = self.belief()
        blown = self.blown_members()
        if mode == "repeat_clean":
            for r in sorted(self.x.picks, reverse=True):
                if self.x.results.get(r) == 0:
                    t = self.x.picks[r]
                    if len(t) == n and all(p in alive for p in t):
                        return list(t)
                    break                                     # only the most recent clean team
            return [self.me] + self.least(others, probs, n - 1)
        if mode == "no_blown":
            pool = [o for o in others if o not in blown]
            team = [self.me] + self.least(pool, probs, n - 1)
            if len(team) < n:
                team += self.least([o for o in others if o not in team], probs, n - len(team))
            return team
        if mode == "no_blown_dull":                          # seat order, no beliefs
            pool = [o for o in others if o not in blown]
            team = [self.me] + pool[: n - 1]
            if len(team) < n:
                team += [o for o in others if o not in team][: n - len(team)]
            return team
        return [self.me] + self.least(others, probs, n - 1)

    def blown_members(self) -> list[str]:
        """Alive players who were on a blown job, ordered by number of blown jobs then seat."""
        s = self.s
        cnt = {}
        for team, sab in s.jobs:
            if sab:
                for t in team:
                    if t in s.alive and t not in s.revealed:
                        cnt[t] = cnt.get(t, 0) + 1
        return sorted(cnt, key=lambda t: (-cnt[t], s.seats.index(t)))

    # ------------------------------------------------------------- job
    def do_job(self, out, props, schema):
        s, m = self.s, self.m
        if m["sab"] in ("always", "never", "smart"):
            return super().do_job(out, props, schema)
        on = [x for x in s.seats if x in self.moles and x in s.team]
        lowest = bool(on) and on[0] == self.me
        if m["sab"] == "late":
            choice = "sabotage" if lowest and s.round >= m["k"] else "help"
        elif m["sab"] == "closer":
            blown = sum(1 for _, sab in s.jobs if sab)
            clean = sum(1 for _, sab in s.jobs if not sab)
            g = self.cfg.game
            urgent = blown + 1 >= g.sabotage_target or clean + 1 >= g.clean_target
            choice = "sabotage" if lowest and urgent else "help"
        elif m["sab"] == "leader_clean":
            choice = "sabotage" if lowest else "help"
        else:
            raise ValueError(m["sab"])
        out["action"] = {"choice": choice}

    # ------------------------------------------------------------- discussion and vote
    def crew_target(self, others, probs, phase) -> str:
        mode = self.c["target"]
        s = self.s
        if mode == "bandwagon":
            acc = [a for a in self.x.accusations.get(s.round, []) if a in others]
            if acc:
                cnt = {}
                for a in acc:
                    cnt[a] = cnt.get(a, 0) + 1
                top = max(cnt.values())
                return next(a for a in acc if cnt[a] == top)     # first accused among the tied
            return self.pick_max(others, probs)
        if mode in ("blown_seat", "blown_seat_dull"):
            bl = [b for b in self.blown_members() if b in others]
            if bl:
                return bl[0]
            if mode == "blown_seat_dull":
                return others[0]
            return self.pick_max(others, probs)
        if mode == "seat":
            return [o for o in s.seats if o in others][0]
        return self.pick_max(others, probs)

    def do_discuss(self, out, props, schema):
        s = self.s
        if s.role == "crew":
            if self.c["share"] and self.c["target"] == "logic":
                return super().do_discuss(out, props, schema)
            return self.crew_discuss(out, props, schema)
        if self.m["talk"] == "smart" and self.m["cards"] in ("decoy", "none"):
            return super().do_discuss(out, props, schema)
        return self.mole_discuss(out, props, schema)

    def crew_discuss(self, out, props, schema):
        s = self.s
        others = [o for o in props["accuse"]["enum"] if o != "none"]
        probs = self.belief()
        cards, claims, words = [], [], []
        if self.c["share"]:
            for c in reversed(s.real_clues()):
                if _key(c) not in self.tabled and len(cards) < 2:
                    cards.append(_card(c))
                    self.tabled.add(_key(c))
                    claims.append({"text": f"my clue: {c['text']}", "truthful": True})
        accuse = self.rng.choice(others) if self.random_act() else self.crew_target(others, probs, "discuss")
        job_claim = "helped" if "helped" in props["job_claim"]["enum"] else "none"
        if job_claim == "helped":
            claims.append({"text": "I helped on the job", "truthful": True})
            words.append("I helped on that job.")
        words.insert(0, "Cards on the table." if cards else "Nothing new from me.")
        words.append(f"I am watching {accuse}.")
        out["public"] = " ".join(words)
        out["claims"] = claims
        out["action"] = {"accuse": accuse, "challenges": [], "clue_cards": cards, "job_claim": job_claim,
                         "suspicion": self.suspicion(schema, probs)}

    def mole_target(self, others) -> str:
        s, m = self.s, self.m
        pool = [o for o in others if o not in s.partners] or others
        probs = self.table_read()
        if m["talk"] == "bus":
            live_partners = [p for p in s.partners if p in others]
            if live_partners and probs.get(live_partners[0], 0.0) >= m["thr"]:
                return live_partners[0]
        if m["talk"] == "target_trusted":
            return self.least(pool, probs, 1)[0]
        if m["talk"] == "mimic":
            return self.pick_max(others, self.crewlike())
        return self.pick_max(pool, probs)

    def safe_true_clues(self) -> list[dict]:
        """Real clues the mole holds that do not raise either mole's public posterior."""
        s = self.s
        before = Bot.table_read(self)
        out = []
        for c in reversed(s.real_clues()):
            if _key(c) in self.tabled:
                continue
            cards = s.cards + [(self.me, c)]
            worlds = table_worlds(s.seats, s.num_moles, s.revealed, cards, s.jobs)
            if not worlds:
                continue
            after = posterior(worlds, s.seats)
            if all(after[x] <= before.get(x, 0.0) + 1e-9 for x in self.moles):
                out.append(c)
        return out

    def mole_discuss(self, out, props, schema):
        s, m = self.s, self.m
        others = [o for o in props["accuse"]["enum"] if o != "none"]
        probs = self.table_read()
        cards, claims, words = [], [], []
        jc_enum = props["job_claim"]["enum"]
        if m["talk"] == "mute":
            out["public"] = ""
            out["claims"] = []
            out["action"] = {"accuse": "none", "challenges": [], "clue_cards": [], "job_claim": "none",
                             "suspicion": self.suspicion(schema, probs)}
            return
        accuse = self.mole_target(others)
        if m["cards"] == "decoy" and self.decoy_round != s.round:
            fake = self.make_decoy(others)
            if fake:
                self.decoy_round = s.round
                self.decoys.append(fake)
                cards.append(_card(fake))
                claims.append({"text": f"my clue: {fake['text']}", "truthful": False})
        elif m["cards"] == "true":
            for c in self.safe_true_clues()[:2]:
                cards.append(_card(c))
                self.tabled.add(_key(c))
                claims.append({"text": f"my clue: {c['text']}", "truthful": True})
        job_claim = "helped" if "helped" in jc_enum else "none"
        if job_claim == "helped":
            claims.append({"text": "I helped on the job", "truthful": s.my_choice.get(s.round) != "sabotage"})
        words.append("Cards on the table." if cards else "Nothing new from me.")
        if job_claim == "helped":
            words.append("I helped on that job.")
        words.append(f"I am watching {accuse}.")
        out["public"] = " ".join(words)
        out["claims"] = claims
        out["action"] = {"accuse": accuse, "challenges": [], "clue_cards": cards, "job_claim": job_claim,
                         "suspicion": self.suspicion(schema, probs)}

    def do_vote(self, out, props, schema):
        s = self.s
        others = list(props["vote"]["enum"])
        if s.role == "crew":
            if self.c["target"] == "logic":
                return super().do_vote(out, props, schema)
            probs = self.belief()
            target = self.rng.choice(others) if self.random_act() else self.crew_target(others, probs, "vote")
        else:
            if self.m["talk"] == "smart":
                return super().do_vote(out, props, schema)
            probs = self.table_read()
            target = self.mole_target(others)
        out["public"] = f"{target}."
        out["action"] = {"vote": target, "suspicion": self.suspicion(schema, probs)}


def crew_cond(seats, num_moles, revealed, cards, jobs, crew_alive) -> dict:
    """The mole's model of the crew's mean belief: for each player x, the mean over alive crew c
    (c != x) of the public posterior restricted to worlds without c (each crew member knows it is
    not a mole). Uses public information only plus the mole's knowledge of who is crew."""
    worlds = table_worlds(seats, num_moles, revealed, cards, jobs)
    fb = table_worlds(seats, num_moles, revealed, [], jobs)
    out = {}
    per_c = {}
    for c in crew_alive:
        w = [x for x in worlds if c not in x]
        per_c[c] = posterior(w, seats, [x for x in fb if c not in x])
    for x in seats:
        vals = [per_c[c][x] for c in crew_alive if c != x]
        out[x] = sum(vals) / len(vals) if vals else 0.0
    return out


# --------------------------------------------------------------------------- speed

def install_memo():
    """Memoise `solver.table_worlds` (a pure function) in this process only, by rebinding the
    name in the modules that call it. No file is changed; results are identical (checked by
    `best_response.run_checks`)."""
    import inside_job.bots as _b
    import inside_job.solver as _s
    import sys as _sys
    if getattr(_s.table_worlds, "_memo", False):
        return
    orig = _s.table_worlds
    cache = {}

    def tw(players, num_moles, revealed, cards, jobs):
        key = (tuple(players), num_moles, tuple(sorted(revealed.items())),
               tuple((s, c["kind"], tuple(c.get("players", ())), c.get("k")) for s, c in cards),
               tuple((tuple(t), n) for t, n in jobs))
        r = cache.get(key)
        if r is None:
            if len(cache) > 200000:
                cache.clear()
            r = orig(players, num_moles, revealed, cards, jobs)
            cache[key] = r
        return list(r)
    tw._memo = True
    _s.table_worlds = tw
    _b.table_worlds = tw
    for name in ("analysis.strategies", "analysis.best_response", "__main__", "__mp_main__"):
        mod = _sys.modules.get(name)
        if mod is not None and getattr(mod, "table_worlds", None) is orig:
            mod.table_worlds = tw


# --------------------------------------------------------------------------- the client

class PolicyLLM(BotLLM):
    """`BotLLM` with policy bots. `deviator`: a crew spec for the lowest-seat crew player only
    (the others play `crew_spec`). Seat assignment is done by the harness from the game it runs;
    the bots themselves still see only their own view."""

    def __init__(self, cfg, seed, crew_spec: dict, mole_spec: dict, deviator: dict | None = None, audit=None):
        self.cfg, self.seed = cfg, seed
        self.crew_spec, self.mole_spec, self.deviator = crew_spec, mole_spec, deviator
        self.bots = {}
        self.audit = audit
        self.calls = 0
        self.game = None
        self.deviator_name = None

    def bot(self, player, view):
        b = self.bots.get(player)
        if b is None:
            role_ev = next((e for e in view if e["type"] == "role" and e.get("player") == player), None)
            role = role_ev["role"] if role_ev else "crew"
            cs = self.crew_spec
            if role == "crew" and self.deviator is not None and player == self.deviator_name:
                cs = self.deviator
            b = PolicyBot(player, random.Random(f"{self.seed}:bot:{player}"), self.cfg, cs, self.mole_spec, role)
            self.bots[player] = b
        return b


def play_policy_game(cfg, seed, crew_spec, mole_spec, deviator=None, audit=None):
    """One in-memory game (no log file). Returns (events, test_crew): the crew players scored as
    the policy under test (all crew, or the deviator alone)."""
    from inside_job.engine import Game
    llm = PolicyLLM(cfg, seed, crew_spec, mole_spec, deviator=deviator, audit=audit)
    game = Game(cfg, llm, seed, game_id=f"bot-s{seed}", clock=lambda: "")
    llm.game = game
    orig_setup = game.setup

    def setup():
        orig_setup()
        crew_seats = [p.name for p in game.players if p.role == "crew"]
        llm.deviator_name = crew_seats[0] if deviator is not None else None
    game.setup = setup
    if audit is not None:
        audit.game = game
    game.run()
    ev = game.log.events
    crew_names = [p["name"] for p in ev[0]["players"] if p["role"] == "crew"]
    test = [llm.deviator_name] if deviator is not None else crew_names
    return ev, test
