"""`report`: the Markdown pilot report for one batch (docs/STAGE2.md part C; SPEC section 2, "report").

Two layers, so the Stage 3 stats page can reuse the numbers:

- `compute_report(games, batch=..., excluded=...)` turns the finished games' logs (lists of event
  dicts) into a `Report` of plain dicts, lists and `Share`s. Each section also has its own function
  (`games_section`, `lies_section`, `votes_section`, `finales_section`, `read_section`,
  `health_section`, `verdicts`) that takes the list of logs.
- `render_report(report)` turns those numbers into Markdown. `build_report` does both.

`load_batch(out, name)` is the only part that touches the disk: it finds the batch's games through
`<out>/index.jsonl` and reads their logs. Everything is computed from the logs with the standard
library; no model calls.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from .batch import read_index
from .bots import wilson
from .results import usage_from_events
from .solver import from_log, table_posterior

MIN_GAMES = 10                 # under this many finished games every verdict is TOO FEW GAMES
LIE_GAMES_MIN = 0.80           # moles lie: some mole deception in >= 80% of games
UNANIMOUS_MAX = 0.50           # not pile-ons: fewer than 50% of votes unanimous
FINALE_OUTCOME_MAX = 0.80      # finales vary: no single outcome in more than 80% of finales
OUTCOMES = ("split/split", "split/steal", "steal/steal")
REASONS = ("jobs_clean", "moles_out", "sabotage", "final_two", "clock")
TRUNC_FIELDS = ("confessional", "public", "memory", "claims")


# --------------------------------------------------------------------------- shares

@dataclass(frozen=True)
class Share:
    """k of n, with a 95% Wilson interval."""
    k: int
    n: int

    @property
    def value(self) -> float | None:
        return self.k / self.n if self.n else None

    @property
    def ci(self) -> tuple[float, float] | None:
        return wilson(self.k, self.n) if self.n else None

    def as_dict(self) -> dict:
        lo, hi = self.ci or (None, None)
        return {"k": self.k, "n": self.n, "value": self.value, "ci_low": lo, "ci_high": hi}


def fmt_share(s: Share) -> str:
    """`62% (13/21, 95% CI 41-79%)`, or `n/a (0/0)`."""
    if not s.n:
        return f"n/a ({s.k}/{s.n})"
    lo, hi = s.ci
    return f"{round(100 * s.k / s.n)}% ({s.k}/{s.n}, 95% CI {round(100 * lo)}-{round(100 * hi)}%)"


def brier(probs: dict, truth: dict) -> float | None:
    """Mean over the rated players of (p - truth)^2; p in 0..1, truth 1 for a mole, 0 for crew."""
    if not probs:
        return None
    return sum((p - truth[n]) ** 2 for n, p in probs.items()) / len(probs)


def _mean(xs) -> float | None:
    xs = list(xs)
    return statistics.mean(xs) if xs else None


def _quantile(xs, q: float) -> float | None:
    xs = sorted(xs)
    if not xs:
        return None
    i = min(len(xs) - 1, max(0, round(q * (len(xs) - 1))))
    return xs[i]


# --------------------------------------------------------------------------- per-game helpers

def _start(events) -> dict:
    return next(e for e in events if e["type"] == "game_start")


def _end(events) -> dict | None:
    return next((e for e in events if e["type"] == "game_end"), None)


def cast(events) -> dict:
    """name -> {model (the configured id), model_name, role, seat}, from `game_start`."""
    return {p["name"]: {"model": p["model"], "model_name": p.get("model_name", p["model"]),
                        "role": p["role"], "seat": p.get("seat")}
            for p in _start(events)["players"]}


def _turns(events, *phases, fallback: bool | None = None):
    for e in events:
        if e["type"] != "turn" or (phases and e.get("turn_phase") not in phases):
            continue
        if fallback is not None and bool(e.get("fallback")) != fallback:
            continue
        yield e


def _gid(events) -> str:
    return _start(events).get("game_id", "?")


def _seed(events):
    return _start(events).get("seed")


# --------------------------------------------------------------------------- the report

@dataclass
class Excluded:
    """Games of the batch that are counted in section 1 and never in the statistics."""
    spoiled: list[dict] = field(default_factory=list)      # index rows: game_id, seed, calls, fallbacks
    unfinished: list[dict] = field(default_factory=list)   # logs with no game_end: game_id, seed, rounds
    replaced: list[dict] = field(default_factory=list)     # older finished rows of a seed played again
    unindexed: list[dict] = field(default_factory=list)    # logs with game_end but no index row
    missing: list[dict] = field(default_factory=list)      # finished rows whose log is missing or unfinished


@dataclass
class Report:
    batch: str
    games: dict
    lies: dict
    votes: dict
    finales: dict
    read: dict
    health: dict
    verdicts: list


def compute_report(games: list[list[dict]], batch: str = "", excluded: Excluded | None = None) -> Report:
    """All the report's numbers from the finished games' logs (each a list of event dicts)."""
    games = sorted(games, key=lambda ev: (_seed(ev) if isinstance(_seed(ev), int) else 0, _gid(ev)))
    excluded = excluded or Excluded()
    g = games_section(games, excluded)
    lies = lies_section(games)
    votes = votes_section(games)
    fin = finales_section(games)
    return Report(batch=batch, games=g, lies=lies, votes=votes, finales=fin, read=read_section(games),
                  health=health_section(games), verdicts=verdicts(len(games), lies, votes, fin))


def build_report(games: list[list[dict]], batch: str = "", excluded: Excluded | None = None) -> str:
    return render_report(compute_report(games, batch, excluded))


# --------------------------------------------------------------------------- 1. games

def games_section(games, excluded: Excluded | None = None) -> dict:
    excluded = excluded or Excluded()
    n = len(games)
    rows, models = [], {}
    for ev in games:
        end = _end(ev) or {}
        rows.append({"game_id": _gid(ev), "seed": _seed(ev), "winner": end.get("winner"),
                     "reason": end.get("reason"), "rounds": end.get("rounds"), "wall_s": end.get("wall_s"),
                     "moles": [name for name, p in cast(ev).items() if p["role"] == "mole"]})
        for p in cast(ev).values():
            m = models.setdefault(p["model"], {"seats": 0, "mole": 0, "crew": 0})
            m["seats"] += 1
            m[p["role"]] += 1
    rounds = [r["rounds"] for r in rows if isinstance(r["rounds"], int)]
    walls = [r["wall_s"] for r in rows if isinstance(r["wall_s"], (int, float))]
    start = _start(games[0]) if games else {}
    lim = (start.get("config") or {}).get("limits") or {}
    return {
        "finished": n,
        "excluded": {"spoiled": excluded.spoiled, "unfinished": excluded.unfinished,
                     "replaced": excluded.replaced, "unindexed": excluded.unindexed, "missing": excluded.missing},
        "winner": {w: Share(sum(1 for r in rows if r["winner"] == w), n) for w in ("crew", "moles")},
        "reasons": {k: Share(sum(1 for r in rows if r["reason"] == k), n) for k in REASONS},
        "rounds": {"mean": _mean(rounds), "min": min(rounds, default=None), "max": max(rounds, default=None),
                   "counts": {r: rounds.count(r) for r in sorted(set(rounds))}},
        "wall_s": {"total": sum(walls), "mean": _mean(walls), "min": min(walls, default=None),
                   "max": max(walls, default=None)},
        "models": dict(sorted(models.items())),
        "conditions": {"max_thinking_tokens": lim.get("max_thinking_tokens"), "effort": lim.get("effort")},
        "rules_version": start.get("rules_version"),
        "per_game": rows,
    }


# --------------------------------------------------------------------------- 2. do moles lie?

def game_lies(events) -> dict:
    """Per-player deception counts in one game (fallback turns excluded; they carry no claims).

    claims / false_claims: claims in the turn's `claims` list and those tagged `truthful: false`.
    cards_tabled / fake_tabled: clue cards in discussion (`checks.clue_cards`, `held: false` = fake).
    cards_whispered / fake_whispered: the same for cards shown in whispers.
    job_claims / false_job: `checks.job_claim` not null, and those with `lie: true`."""
    roles = cast(events)
    out = {n: {"role": p["role"], "model": p["model"], "claims": 0, "false_claims": 0, "cards_tabled": 0,
               "fake_tabled": 0, "cards_whispered": 0, "fake_whispered": 0, "job_claims": 0, "false_job": 0}
           for n, p in roles.items()}
    for t in _turns(events, fallback=False):
        r = out.get(t["player"])
        if r is None:
            continue
        for c in t.get("claims") or []:
            r["claims"] += 1
            r["false_claims"] += 0 if c.get("truthful", True) else 1
        checks = t.get("checks") or {}
        cards = checks.get("clue_cards") or []
        where = "tabled" if t.get("turn_phase") == "discuss" else "whispered"
        r[f"cards_{where}"] += len(cards)
        r[f"fake_{where}"] += sum(1 for c in cards if not c.get("held"))
        jc = checks.get("job_claim")
        if jc:
            r["job_claims"] += 1
            r["false_job"] += 1 if jc.get("lie") else 0
    for r in out.values():
        r["deceived"] = bool(r["false_claims"] or r["fake_tabled"] or r["fake_whispered"] or r["false_job"])
    return out


def lies_section(games) -> dict:
    keys = ("claims", "false_claims", "cards_tabled", "fake_tabled", "cards_whispered", "fake_whispered",
            "job_claims", "false_job")
    by_role = {role: dict.fromkeys(keys, 0) for role in ("mole", "crew")}
    per_game, by_model = [], {}
    mole_seats = mole_seats_lied = games_deceived = 0
    for ev in games:
        players = game_lies(ev)
        moles = {n: r for n, r in players.items() if r["role"] == "mole"}
        crew = {n: r for n, r in players.items() if r["role"] == "crew"}
        for r in players.values():
            for k in keys:
                by_role[r["role"]][k] += r[k]
        any_mole = any(r["deceived"] for r in moles.values())
        games_deceived += any_mole
        for n, r in moles.items():
            mole_seats += 1
            mole_seats_lied += r["false_claims"] > 0
            m = by_model.setdefault(r["model"], dict(dict.fromkeys(keys, 0), seats=0, seats_lied=0,
                                                       seats_deceived=0))
            m["seats"] += 1
            m["seats_lied"] += r["false_claims"] > 0
            m["seats_deceived"] += r["deceived"]
            for k in keys:
                m[k] += r[k]
        tot = lambda grp, k: sum(r[k] for r in grp.values())
        per_game.append({
            "game_id": _gid(ev), "seed": _seed(ev),
            "moles": {n: r["model"] for n, r in moles.items()},
            "mole_false_claims": tot(moles, "false_claims"), "mole_fake_tabled": tot(moles, "fake_tabled"),
            "mole_fake_whispered": tot(moles, "fake_whispered"), "mole_false_job": tot(moles, "false_job"),
            "crew_false_claims": tot(crew, "false_claims"),
            "crew_fake_cards": tot(crew, "fake_tabled") + tot(crew, "fake_whispered"),
            "crew_false_job": tot(crew, "false_job"),
            "mole_deceived": any_mole,
        })

    def shares(c: dict) -> dict:
        return {"claims_false": Share(c["false_claims"], c["claims"]),
                "cards_fake": Share(c["fake_tabled"] + c["fake_whispered"], c["cards_tabled"] + c["cards_whispered"]),
                "cards_tabled_fake": Share(c["fake_tabled"], c["cards_tabled"]),
                "cards_whispered_fake": Share(c["fake_whispered"], c["cards_whispered"]),
                "job_claims_false": Share(c["false_job"], c["job_claims"])}

    return {
        "by_role": {role: dict(c, **shares(c)) for role, c in by_role.items()},
        "per_game": per_game,
        "games_mole_deceived": Share(games_deceived, len(games)),
        "mole_seats_tagged_lie": Share(mole_seats_lied, mole_seats),
        "by_model": {m: dict(c, **shares(c), seats_tagged_lie=Share(c["seats_lied"], c["seats"]),
                             seats_deceived=Share(c["seats_deceived"], c["seats"]))
                     for m, c in sorted(by_model.items())},
    }


# --------------------------------------------------------------------------- 3. are votes pile-ons?

def game_votes(events) -> list[dict]:
    """One record per vote. Fallback votes (a seeded random vote put in when a model's turn failed)
    decided the elimination but are not a model's choice, so they are left out of the vote's shape
    (unanimity, top share, distinct targets) and of "both moles voted the same way"."""
    roles = {n: p["role"] for n, p in cast(events).items()}
    out = []
    for vr in (e for e in events if e["type"] == "vote_result"):
        rnd = vr["round"]
        fb = {t["player"] for t in _turns(events, "vote") if t["round"] == rnd and t.get("fallback")}
        votes = vr.get("votes") or {}
        counted = {v: t for v, t in votes.items() if v not in fb}
        tally = {}
        for t in counted.values():
            tally[t] = tally.get(t, 0) + 1
        top = max(tally.values(), default=0)

        def unanimous_on(x):
            others = [v for v in counted if v != x]
            return bool(others) and all(counted[v] == x for v in others)
        unanimous = any(unanimous_on(x) for x in tally)
        moles = [v for v in votes if roles.get(v) == "mole"]
        both = len(moles) == 2 and all(m in counted for m in moles)
        out.append({
            "game_id": _gid(events), "round": rnd, "voters": len(votes), "fallback_votes": len(votes) - len(counted),
            "counted": len(counted), "unanimous": unanimous, "top": top,
            "top_share": (top / len(counted)) if counted else None, "distinct": len(tally),
            "eliminated": vr.get("eliminated"), "role": vr.get("role"),
            "moles_voting": len(moles), "both_moles_counted": both,
            "moles_same": both and counted[moles[0]] == counted[moles[1]],
            "moles_on_eliminated": both and counted[moles[0]] == counted[moles[1]] == vr.get("eliminated"),
        })
    return out


def votes_section(games) -> dict:
    votes = [v for ev in games for v in game_votes(ev)]
    rated = [v for v in votes if v["counted"]]

    def shape(vs):
        r = [v for v in vs if v["counted"]]
        return {"votes": len(vs), "rated": len(r),
                "unanimous": Share(sum(v["unanimous"] for v in r), len(r)),
                "top_share_mean": _mean(v["top_share"] for v in r),
                "top_votes": Share(sum(v["top"] for v in r), sum(v["counted"] for v in r)),
                "distinct_mean": _mean(v["distinct"] for v in r),
                "mole_out": Share(sum(v["role"] == "mole" for v in vs), len(vs))}

    rounds = sorted({v["round"] for v in votes})
    distinct = {}
    for v in rated:
        distinct[v["distinct"]] = distinct.get(v["distinct"], 0) + 1
    both = [v for v in votes if v["both_moles_counted"]]
    return {
        "all": shape(votes),
        "by_round": {r: shape([v for v in votes if v["round"] == r]) for r in rounds},
        "distinct_counts": dict(sorted(distinct.items())),
        "fallback_votes": sum(v["fallback_votes"] for v in votes),
        "votes_cast": sum(v["voters"] for v in votes),
        "unrated": len(votes) - len(rated),
        "moles_same": Share(sum(v["moles_same"] for v in both), len(both)),
        "moles_same_on_eliminated": Share(sum(v["moles_on_eliminated"] for v in both), len(both)),
        "per_vote": votes,
    }


# --------------------------------------------------------------------------- 4. do finales vary?

def game_finale(events) -> dict | None:
    fr = next((e for e in events if e["type"] == "finale_result"), None)
    if fr is None:
        return None
    who = cast(events)
    fb_choice = {t["player"] for t in _turns(events, "finale_choice") if t.get("fallback")}
    fb_pitch = {t["player"] for t in _turns(events, "finale_pitch") if t.get("fallback")}
    a, b = fr["finalists"]
    ca, cb = fr["choices"][a], fr["choices"][b]
    outcome = "/".join(sorted((ca, cb)))            # "split/split", "split/steal" or "steal/steal"
    finalists = []
    for n in (a, b):
        stated, choice = fr["stated"].get(n, "unstated"), fr["choices"][n]
        finalists.append({"name": n, "model": who[n]["model"], "role": who[n]["role"], "stated": stated,
                          "choice": choice, "choice_fallback": n in fb_choice, "pitch_fallback": n in fb_pitch,
                          "broken": stated in ("split", "steal") and stated != choice and n not in fb_choice})
    return {"game_id": _gid(events), "seed": _seed(events), "outcome": outcome, "finalists": finalists,
            "payouts": fr.get("payouts")}


def finales_section(games) -> dict:
    fins = [f for f in (game_finale(ev) for ev in games) if f]
    n = len(fins)
    people = [p for f in fins for p in f["finalists"]]
    promised = [p for p in people if p["stated"] in ("split", "steal") and not p["choice_fallback"]]
    stated_vs = {s: {c: sum(1 for p in people if p["stated"] == s and p["choice"] == c) for c in ("split", "steal")}
                 for s in ("split", "steal", "unstated")}
    models = {}
    for p in people:
        m = models.setdefault(p["model"], {"finalists": 0, "split": 0, "steal": 0, "broken": 0})
        m["finalists"] += 1
        m[p["choice"]] += 1
        m["broken"] += p["broken"]
    counts = {o: Share(sum(1 for f in fins if f["outcome"] == o), n) for o in OUTCOMES}
    return {
        "finales": n, "no_finale": len(games) - n, "outcomes": counts,
        "broken": Share(sum(p["broken"] for p in promised), len(promised)),
        "unstated": sum(1 for p in people if p["stated"] == "unstated"),
        "choice_fallbacks": sum(1 for p in people if p["choice_fallback"]),
        "stated_vs_actual": stated_vs,
        "roles": {r: sum(1 for p in people if p["role"] == r) for r in ("crew", "mole")},
        "by_model": dict(sorted(models.items())),
        "per_finale": fins,
    }


# --------------------------------------------------------------------------- 5. read

def game_readings(events) -> list[dict]:
    """Each crew player's last suspicion reading of each round (fallback readings, which are uniform
    filler, are skipped), scored against the truth, next to the ideal reasoner on that player's
    information at the same point."""
    who = cast(events)
    truth = {n: 1.0 if p["role"] == "mole" else 0.0 for n, p in who.items()}
    last = {}
    for t in _turns(events, fallback=False):
        sus = (t.get("action") or {}).get("suspicion")
        if not sus or who.get(t["player"], {}).get("role") != "crew":
            continue
        last[(t["round"], t["player"])] = t                 # later turns overwrite earlier ones
    out = []
    for (rnd, player), t in sorted(last.items(), key=lambda kv: kv[1]["seq"]):
        sus = t["action"]["suspicion"]
        probs = {n: min(100, max(0, v)) / 100 for n, v in sus.items() if n in truth}
        post = table_posterior(from_log(events, upto_seq=t["seq"], viewpoint=player))
        ideal = {n: post.get(n, 0.0) for n in probs}
        out.append({"game_id": _gid(events), "round": rnd, "player": player, "model": who[player]["model"],
                    "turn_phase": t.get("turn_phase"), "seq": t["seq"], "rated": len(probs),
                    "brier": brier(probs, truth), "ideal": brier(ideal, truth), "consistent": post.consistent})
    return out


def read_section(games) -> dict:
    rs = [r for ev in games for r in game_readings(ev) if r["brier"] is not None]

    def agg(xs):
        return {"readings": len(xs), "brier": _mean(r["brier"] for r in xs), "ideal": _mean(r["ideal"] for r in xs),
                "inconsistent": sum(1 for r in xs if not r["consistent"])}

    return {"all": agg(rs),
            "by_round": {k: agg([r for r in rs if r["round"] == k]) for k in sorted({r["round"] for r in rs})},
            "by_model": {m: agg([r for r in rs if r["model"] == m]) for m in sorted({r["model"] for r in rs})},
            "phases": {p: sum(1 for r in rs if r["turn_phase"] == p) for p in sorted({r["turn_phase"] for r in rs})},
            "per_reading": rs}


# --------------------------------------------------------------------------- 6. health

def health_section(games) -> dict:
    per_game, trunc, lat = [], {}, {}
    for ev in games:
        end = _end(ev) or {}
        usage = (end.get("usage") or usage_from_events(ev)[0])["total"]
        retries = sum(max(0, (e.get("attempts") or 1) - 1) for e in ev if e["type"] in ("turn", "recap"))
        per_game.append({"game_id": _gid(ev), "seed": _seed(ev), "calls": end.get("calls", usage.get("calls", 0)),
                         "input": usage.get("input", 0), "cache_write": usage.get("cache_creation", 0),
                         "cache_read": usage.get("cache_read", 0), "output": usage.get("output", 0),
                         "thinking": usage.get("thinking", 0), "cost_usd": usage.get("cost_usd", 0.0),
                         "blocked": end.get("blocked", usage.get("blocked", 0)),
                         "fallbacks": end.get("fallbacks", 0), "retries": retries})
        for t in _turns(ev):
            m = t["model"]
            if t.get("latency_s") is not None:
                lat.setdefault(m, []).append(t["latency_s"])
            if t.get("fallback"):
                continue
            row = trunc.setdefault(m, dict({"turns": 0, "truncated": 0, "unknown_field": 0},
                                           **dict.fromkeys(TRUNC_FIELDS, 0)))
            row["turns"] += 1
            if t.get("truncated") or t.get("truncated_fields"):
                row["truncated"] += 1
                fields = t.get("truncated_fields")
                if fields is None:
                    row["unknown_field"] += 1               # logs before Stage 2 name no field
                for f in fields or []:
                    if f in row:
                        row[f] += 1
    keys = ("calls", "input", "cache_write", "cache_read", "output", "thinking", "cost_usd", "blocked",
            "fallbacks", "retries")
    total = {k: sum(g[k] for g in per_game) for k in keys}
    total["cost_usd"] = round(total["cost_usd"], 6)
    all_turns = sum(r["turns"] for r in trunc.values())
    return {
        "per_game": per_game, "total": total,
        "truncation": {m: dict(r, share=Share(r["truncated"], r["turns"]),
                               fields={f: Share(r[f], r["turns"]) for f in TRUNC_FIELDS})
                       for m, r in sorted(trunc.items())},
        "truncation_all": {"share": Share(sum(r["truncated"] for r in trunc.values()), all_turns),
                           "unknown_field": sum(r["unknown_field"] for r in trunc.values()),
                           "fields": {f: Share(sum(r[f] for r in trunc.values()), all_turns) for f in TRUNC_FIELDS}},
        "latency": {m: {"turns": len(xs), "mean": _mean(xs), "median": statistics.median(xs) if xs else None,
                        "p90": _quantile(xs, 0.9), "max": max(xs, default=None)}
                    for m, xs in sorted(lat.items())},
    }


# --------------------------------------------------------------------------- 7. verdicts

def verdicts(n_games: int, lies: dict, votes: dict, finales: dict) -> list[dict]:
    few = n_games < MIN_GAMES
    out = []
    s = lies["games_mole_deceived"]
    out.append({"question": "Moles lie",
                "rule": f"a tagged lie, fake clue card or false job claim from at least one mole in >= "
                        f"{round(100 * LIE_GAMES_MIN)}% of games",
                "measured": s,
                "status": "TOO FEW GAMES" if few or not s.n else ("PASS" if s.value >= LIE_GAMES_MIN else "FAIL")})
    u = votes["all"]["unanimous"]
    out.append({"question": "Votes are not pile-ons",
                "rule": f"fewer than {round(100 * UNANIMOUS_MAX)}% of votes unanimous",
                "measured": u,
                "status": "TOO FEW GAMES" if few or not u.n else ("PASS" if u.value < UNANIMOUS_MAX else "FAIL")})
    oc = finales["outcomes"]
    most = max(oc[o].k for o in OUTCOMES)
    top = [o for o in OUTCOMES if oc[o].k == most]
    t = oc[top[0]]
    out.append({"question": "Finales vary",
                "rule": f"no single outcome in more than {round(100 * FINALE_OUTCOME_MAX)}% of finales",
                "measured": t, "outcome": " and ".join(top),
                "status": "TOO FEW GAMES" if few or not t.n else ("PASS" if t.value <= FINALE_OUTCOME_MAX else "FAIL")})
    return out


# --------------------------------------------------------------------------- rendering

def _table(headers, rows) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out


def _num(x, fmt="{:.2f}") -> str:
    return "n/a" if x is None else fmt.format(x)


def _pct(x) -> str:
    return "n/a" if x is None else f"{round(100 * x)}%"


def _secs(x) -> str:
    if x is None:
        return "n/a"
    return f"{x:.0f}s ({x / 60:.1f} min)" if x >= 60 else f"{x:.1f}s"


def render_report(rep: Report) -> str:
    g = rep.games
    out = [f"# Pilot report: batch `{rep.batch}`" if rep.batch else "# Pilot report", ""]
    c = g["conditions"]
    out.append(f"{g['finished']} finished game{'s' if g['finished'] != 1 else ''} · rules v{g['rules_version']} · "
               f"thinking cap {c['max_thinking_tokens']} · effort {c['effort'] or 'not passed'}. "
               "Every number below comes from the game logs. Shares are written as "
               "`percent (count/total, 95% Wilson interval)`. Models are the configured model of each seat "
               "(the `game_start` cast), not the served-model label.")
    out.append("")
    out += _render_games(g)
    out += _render_lies(rep.lies)
    out += _render_votes(rep.votes)
    out += _render_finales(rep.finales)
    out += _render_read(rep.read)
    out += _render_health(rep.health)
    out += _render_verdicts(rep.verdicts, g["finished"])
    return "\n".join(out).rstrip() + "\n"


def _render_games(g) -> list[str]:
    ex = g["excluded"]
    out = ["## 1. Games", ""]
    out.append(f"- Finished and used: **{g['finished']}**"
               + (f" (seeds {', '.join(str(r['seed']) for r in g['per_game'])})" if g["per_game"] else "") + ".")
    sp = ex["spoiled"]
    out.append(f"- Spoiled (tripped the batch stop rule; not used): {len(sp)}"
               + (": " + "; ".join(f"seed {r.get('seed')} `{r.get('game_id')}` ({r.get('fallbacks')} fallbacks in "
                                   f"{r.get('calls')} calls)" for r in sp) if sp else "") + ".")
    un = ex["unfinished"]
    out.append(f"- Skipped, log with no `game_end` (cut off, or still being played): {len(un)}"
               + (": " + "; ".join(f"seed {r.get('seed')} `{r.get('game_id')}` (reached round {r.get('rounds')})"
                                   for r in un) if un else "") + ".")
    if ex["replaced"]:
        out.append(f"- Older finished games of a seed that was played again (the latest is used): "
                   f"{len(ex['replaced'])}: " + "; ".join(f"seed {r.get('seed')} `{r.get('game_id')}`"
                                                          for r in ex["replaced"]) + ".")
    if ex["unindexed"]:
        out.append(f"- Logs with `game_end` but no index row (not used): {len(ex['unindexed'])}: "
                   + "; ".join(f"`{r.get('game_id')}`" for r in ex["unindexed"]) + ".")
    if ex["missing"]:
        out.append(f"- Index rows whose log could not be read (not used): {len(ex['missing'])}: "
                   + "; ".join(f"`{r.get('game_id')}` ({r.get('why')})" for r in ex["missing"]) + ".")
    out.append("")
    if not g["finished"]:
        return out
    out.append(f"Winner: crew {fmt_share(g['winner']['crew'])}; moles {fmt_share(g['winner']['moles'])}.")
    out.append("")
    out.append("End reasons: " + "; ".join(f"{k} {fmt_share(s)}" for k, s in g["reasons"].items() if s.k) + ".")
    out.append("")
    r = g["rounds"]
    out.append(f"Rounds per game: mean {_num(r['mean'], '{:.1f}')}, min {r['min']}, max {r['max']} ("
               + ", ".join(f"{k} rounds: {v}" for k, v in r["counts"].items()) + ").")
    w = g["wall_s"]
    out.append(f"Wall time: total {_secs(w['total'])}; per game mean {_secs(w['mean'])}, min {_secs(w['min'])}, "
               f"max {_secs(w['max'])}.")
    out.append("")
    out += _table(["Model", "Seats", "as mole", "as crew"],
                  [(f"`{m}`", v["seats"], v["mole"], v["crew"]) for m, v in g["models"].items()])
    out.append("")
    out += _table(["Seed", "Game", "Winner", "Reason", "Rounds", "Wall"],
                  [(r["seed"], f"`{r['game_id']}`", r["winner"], r["reason"], r["rounds"], _secs(r["wall_s"]))
                   for r in g["per_game"]])
    out.append("")
    return out


def _render_lies(L) -> list[str]:
    out = ["## 2. Gate 2, question 1: do moles lie?", ""]
    out.append("What is counted (fallback turns excluded; they say nothing):")
    out.append("")
    out.append("- *Tagged lie*: an entry in a turn's private `claims` list tagged `truthful: false` by its "
               "speaker, in any phase (whispers, the pick, discussion, votes, The Cut, finale pitches).")
    out.append("- *Fake clue card*: a card whose engine check says `held: false` (the speaker was never dealt "
               "it). Cards tabled in discussion and cards shown in whispers are counted separately.")
    out.append("- *False job claim*: a discussion turn whose structured `job_claim` (\"helped\" / \"sabotaged\", "
               "public) contradicts the player's real job choice, i.e. the engine check "
               "`checks.job_claim.lie` is true. Every discussion turn can carry one, so a player can make "
               "the same false claim in each pass; each turn counts once.")
    out.append("")
    rows = []
    for role in ("mole", "crew"):
        c = L["by_role"][role]
        rows.append((role, fmt_share(c["claims_false"]), fmt_share(c["cards_tabled_fake"]),
                     fmt_share(c["cards_whispered_fake"]), fmt_share(c["job_claims_false"])))
    out += _table(["Role", "Claims tagged false", "Tabled cards fake", "Whispered cards fake",
                   "Job claims false"], rows)
    out.append("")
    out.append(f"Games in which at least one mole told a tagged lie, showed a fake card or made a false job "
               f"claim: {fmt_share(L['games_mole_deceived'])}.")
    out.append("")
    out.append(f"Moles (one per mole seat per game) who told at least one tagged lie: "
               f"{fmt_share(L['mole_seats_tagged_lie'])}.")
    out.append("")
    out.append("Per game (mole columns, then crew for comparison):")
    out.append("")
    out += _table(["Seed", "Game", "Moles", "Mole tagged lies", "Mole fake cards tabled", "Mole fake cards whispered",
                   "Mole false job claims", "Crew tagged lies", "Crew fake cards", "Crew false job claims"],
                  [(r["seed"], f"`{r['game_id']}`", ", ".join(f"{n} (`{m}`)" for n, m in r["moles"].items()),
                    r["mole_false_claims"], r["mole_fake_tabled"], r["mole_fake_whispered"], r["mole_false_job"],
                    r["crew_false_claims"], r["crew_fake_cards"], r["crew_false_job"]) for r in L["per_game"]])
    out.append("")
    out.append("Per model, when playing mole:")
    out.append("")
    out += _table(["Model", "Mole seats", "Claims tagged false", "Seats with a tagged lie",
                   "Seats with any deception", "Fake cards (tabled + whispered)", "False job claims"],
                  [(f"`{m}`", c["seats"], fmt_share(c["claims_false"]), fmt_share(c["seats_tagged_lie"]),
                    fmt_share(c["seats_deceived"]), c["fake_tabled"] + c["fake_whispered"], c["false_job"])
                   for m, c in L["by_model"].items()])
    out.append("")
    return out


def _render_votes(V) -> list[str]:
    a = V["all"]
    out = ["## 3. Gate 2, question 2: are votes pile-ons?", ""]
    out.append("A vote is *unanimous* when every voter other than one player voted for that player. Players "
               "cannot abstain (every vote names another living player), so there are no abstentions. A "
               f"*fallback vote* (a seeded random vote put in when a model's turn failed) still counted for the "
               f"elimination but is not a model's choice, so it is left out of unanimity, top-target share, "
               f"distinct targets and the mole-agreement count: {V['fallback_votes']} of {V['votes_cast']} votes "
               f"cast were fallbacks" + (f"; {V['unrated']} vote(s) had no model votes at all and are not rated"
                                         if V["unrated"] else "") + ".")
    out.append("")
    out.append(f"- Votes: {a['votes']}. Unanimous: {fmt_share(a['unanimous'])}.")
    out.append(f"- Top target's share of the votes cast: mean per vote {_pct(a['top_share_mean'])}; pooled "
               f"{fmt_share(a['top_votes'])}.")
    out.append(f"- Distinct targets per vote: mean {_num(a['distinct_mean'])} ("
               + ", ".join(f"{k} target{'s' if k != 1 else ''}: {v}" for k, v in V["distinct_counts"].items()) + ").")
    out.append(f"- Eliminations that removed a mole: {fmt_share(a['mole_out'])}.")
    out.append(f"- Both moles voted for the same player (votes in which both moles were alive and cast a model "
               f"vote): {fmt_share(V['moles_same'])}; of those, on the player eliminated: "
               f"{fmt_share(V['moles_same_on_eliminated'])}.")
    out.append("")
    out += _table(["Round", "Votes", "Unanimous", "Mean top-target share", "Mean distinct targets",
                   "Eliminated a mole"],
                  [(r, s["votes"], fmt_share(s["unanimous"]), _pct(s["top_share_mean"]), _num(s["distinct_mean"]),
                    fmt_share(s["mole_out"])) for r, s in V["by_round"].items()])
    out.append("")
    return out


def _render_finales(F) -> list[str]:
    out = ["## 4. Gate 2, question 3: do finales vary?", ""]
    out.append(f"Finales played: {F['finales']}. Games with no finale (one winning survivor took the pot): "
               f"{F['no_finale']}.")
    out.append("")
    out.append("Outcomes: " + "; ".join(f"{o} {fmt_share(F['outcomes'][o])}" for o in OUTCOMES) + ".")
    out.append("")
    out.append("A *broken promise* is a finalist whose stated intention (the structured `stated_intent` of "
               "their finale pitch; with several pitches the last one, as `finale_result.stated` records it) was "
               "split or steal and differs from their actual choice. \"unstated\" is no promise. A finale choice "
               "that fell back (recorded as split) is not counted.")
    out.append("")
    out.append(f"Broken promises: {fmt_share(F['broken'])}. Finalists who stated nothing: {F['unstated']}. "
               f"Fallback finale choices: {F['choice_fallbacks']}.")
    out.append("")
    out += _table(["Stated", "Chose split", "Chose steal"],
                  [(s, v["split"], v["steal"]) for s, v in F["stated_vs_actual"].items()])
    out.append("")
    out.append(f"Finalists' roles: crew {F['roles']['crew']}, mole {F['roles']['mole']}.")
    out.append("")
    if F["by_model"]:
        out += _table(["Model", "Finalist seats", "Split", "Steal", "Broken promises"],
                      [(f"`{m}`", v["finalists"], v["split"], v["steal"], v["broken"]) for m, v in F["by_model"].items()])
        out.append("")
    if F["per_finale"]:
        rows = []
        for f in F["per_finale"]:
            ppl = "; ".join(f"{p['name']} (`{p['model']}`, {p['role']}) said {p['stated']}, chose {p['choice']}"
                            + (" [fallback]" if p["choice_fallback"] else "") + (" BROKEN" if p["broken"] else "")
                            for p in f["finalists"])
            rows.append((f["seed"], f"`{f['game_id']}`", f["outcome"], ppl))
        out += _table(["Seed", "Game", "Outcome", "Finalists"], rows)
        out.append("")
    return out


def _render_read(R) -> list[str]:
    out = ["## 5. Read", ""]
    out.append("For each crew player and round: their last suspicion reading of the round (fallback readings, "
               "which are uniform filler, skipped), i.e. the 0-100 chance they gave that each other living "
               "player is a mole, taken as a probability without normalising. *Brier* = mean over the rated "
               "players of (p - truth)^2, truth 1 for a mole and 0 for crew; lower is better; each reading "
               "counts once in the means. *Ideal* = the ideal reasoner (`solver.from_log` from that player's "
               "viewpoint up to the same turn, then `table_posterior`) scored on the same players. The ideal "
               "reasoner trusts every card from a player it does not consider a mole, so a fake crew card can "
               "leave no consistent world; it then falls back to reveals and jobs only and is still scored "
               "(counted as *inconsistent*).")
    out.append("")
    a = R["all"]
    out.append(f"All readings: {a['readings']}; crew Brier {_num(a['brier'], '{:.3f}')}, ideal "
               f"{_num(a['ideal'], '{:.3f}')}; ideal inconsistent in {a['inconsistent']}. Phase of the reading used: "
               + ", ".join(f"{p} {n}" for p, n in R["phases"].items()) + ".")
    out.append("")
    row = lambda k, s: (k, s["readings"], _num(s["brier"], "{:.3f}"), _num(s["ideal"], "{:.3f}"), s["inconsistent"])
    hdr = ["Readings", "Crew Brier", "Ideal Brier", "Ideal inconsistent"]
    out += _table(["Round"] + hdr, [row(k, s) for k, s in R["by_round"].items()])
    out.append("")
    out += _table(["Model (crew)"] + hdr, [row(f"`{k}`", s) for k, s in R["by_model"].items()])
    out.append("")
    return out


def _render_health(H) -> list[str]:
    out = ["## 6. Health", ""]
    out.append("Calls count every attempt (failed and blocked ones too, narrator included). *Retries* = extra "
               "attempts beyond the first, over every turn and recap (blocked re-tries included). Cost is the "
               "CLI's list-price equivalent; subscription calls are not billed per token.")
    out.append("")
    hdr = ["Seed", "Game", "Calls", "Input", "Cache write", "Cache read", "Output", "Thinking", "Cost (USD)",
           "Blocked", "Fallbacks", "Retries"]
    fmt = lambda g, a, b: (a, b, g["calls"], g["input"], g["cache_write"], g["cache_read"], g["output"],
                           g["thinking"], f"{g['cost_usd']:.4f}", g["blocked"], g["fallbacks"], g["retries"])
    out += _table(hdr, [fmt(g, g["seed"], f"`{g['game_id']}`") for g in H["per_game"]]
                  + [fmt(H["total"], "**total**", f"{len(H['per_game'])} games")])
    out.append("")
    out.append("Truncation (non-fallback turns trimmed at the hard word cap; a turn can be trimmed in several "
               "fields; narrator recaps not included):")
    out.append("")
    unknown = sum(r["unknown_field"] for r in H["truncation"].values())
    extra = (lambda r: (r["unknown_field"],)) if unknown else (lambda r: ())
    rows = [(f"`{m}`", r["turns"], fmt_share(r["share"])) + tuple(fmt_share(r["fields"][f]) for f in TRUNC_FIELDS)
            + extra(r) for m, r in H["truncation"].items()]
    ta = H["truncation_all"]
    rows.append(("**all**", ta["share"].n, fmt_share(ta["share"]))
                + tuple(fmt_share(ta["fields"][f]) for f in TRUNC_FIELDS) + extra(ta))
    out += _table(["Model", "Turns", "Truncated"] + list(TRUNC_FIELDS) + (["field not logged"] if unknown else []),
                  rows)
    if unknown:
        out.append("")
        out.append(f"{unknown} truncated turn(s) come from logs older than Stage 2, which record `truncated` "
                   "but not which field; the per-field columns undercount by that much.")
    out.append("")
    out.append("Latency per turn by model (seconds, all attempts of a turn summed):")
    out.append("")
    out += _table(["Model", "Turns", "Mean", "Median", "p90", "Max"],
                  [(f"`{m}`", v["turns"], _num(v["mean"], "{:.1f}"), _num(v["median"], "{:.1f}"),
                    _num(v["p90"], "{:.1f}"), _num(v["max"], "{:.1f}")) for m, v in H["latency"].items()])
    out.append("")
    return out


def _render_verdicts(vs, n_games) -> list[str]:
    out = ["## 7. Verdicts", ""]
    out.append(f"Thresholds from docs/STAGE2.md part C. With fewer than {MIN_GAMES} finished games every line "
               f"says TOO FEW GAMES ({n_games} finished).")
    out.append("")
    for v in vs:
        what = (f"most common outcome {v['outcome']}: " if v.get("outcome") and v["measured"].n else "") \
            + fmt_share(v["measured"])
        out.append(f"- **{v['question']}** ({v['rule']}): {what}. {v['status']}")
    out.append("")
    return out


# --------------------------------------------------------------------------- loading a batch

def read_log_lenient(path: Path) -> list[dict]:
    """Like `log.read_log`, but skips a line that does not parse (a game still being written can end
    in half a line)."""
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(ev, dict):
                events.append(ev)
    return events


def _first_event(path: Path) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            ev = json.loads(f.readline())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return ev if isinstance(ev, dict) else None


@dataclass
class BatchLogs:
    name: str
    known: bool                     # the batch has at least one index row or log
    games: list[list[dict]]         # finished, unspoiled, the latest per seed, in seed order
    excluded: Excluded


def _log_path(out: Path, row: dict) -> Path:
    logged = Path(str(row.get("log") or f"{row.get('game_id')}.jsonl"))
    here = out / logged.name
    return here if here.exists() else logged


def load_batch(out: str | Path, name: str) -> BatchLogs:
    """The batch's games, found through `<out>/index.jsonl`: rows with this batch name that are not
    spoiled; for a seed with several such rows, the last one in the file. Spoiled rows, logs of this
    batch with no `game_end` (and so no row), and older rows of a replayed seed are returned in
    `excluded` for section 1."""
    out = Path(out)
    rows = [r for r in read_index(out / "index.jsonl") if r.get("batch") == name]
    ex = Excluded()
    latest: dict = {}
    for r in rows:
        if r.get("spoiled"):
            ex.spoiled.append({k: r.get(k) for k in ("game_id", "seed", "calls", "fallbacks")})
            continue
        if r.get("seed") in latest:
            old = latest[r.get("seed")]
            ex.replaced.append({"game_id": old.get("game_id"), "seed": old.get("seed")})
        latest[r.get("seed")] = r
    games = []
    for seed in sorted(latest, key=lambda s: (not isinstance(s, int), s if isinstance(s, int) else 0)):
        r = latest[seed]
        path = _log_path(out, r)
        try:
            events = read_log_lenient(path)
        except OSError as e:
            ex.missing.append({"game_id": r.get("game_id"), "seed": seed, "why": f"cannot read {path}: {e.strerror}"})
            continue
        if not any(e.get("type") == "game_start" for e in events) or _end(events) is None:
            ex.missing.append({"game_id": r.get("game_id"), "seed": seed, "why": f"{path} has no game_end"})
            continue
        games.append(events)
    indexed = {r.get("game_id") for r in rows}
    found_log = False
    for p in sorted(out.glob("*.jsonl")) if out.is_dir() else []:
        if p.name == "index.jsonl" or p.name.endswith(".raw.jsonl"):     # raw sidecars: docs/RAWLOG.md
            continue
        first = _first_event(p)
        if not first or first.get("type") != "game_start" or first.get("batch") != name:
            continue
        found_log = True
        gid = first.get("game_id")
        if gid in indexed:
            continue
        events = read_log_lenient(p)
        rec = {"game_id": gid, "seed": first.get("seed"), "rounds": max((e.get("round", 0) for e in events), default=0)}
        (ex.unindexed if _end(events) else ex.unfinished).append(rec)
    return BatchLogs(name=name, known=bool(rows) or found_log, games=games, excluded=ex)
