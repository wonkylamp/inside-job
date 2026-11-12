"""Render a game log as a Markdown transcript a person can read top to bottom (SPEC section 9)."""

from __future__ import annotations

from .results import conditions_line, usage_from_events


# ---------------------------------------------------------------------------- shared helpers
# Used by the Markdown transcript and by the live watcher (live.py), so both mark the same things.

def labeller(start: dict):
    """name -> speaker label. In an anonymised game the audience always sees the model behind a
    codename: `Vesper (Sonnet 5.5)`."""
    models = {p["name"]: p.get("model_name") or p.get("model") for p in start.get("players", [])}
    anon = start.get("anonymised", False)

    def label(name: str) -> str:
        if anon and name in models:
            return f"{name} ({models[name]})"
        return name
    return label


def marks(e: dict) -> list[tuple[str, str, str]]:
    """Engine verdicts and self-tags worth flagging on a turn, as (kind, text, note).

    kinds: lie (a claim the speaker tagged false), card_real, card_fake (note says whether the
    fake happens to be true), job_false, job_true."""
    out = [("lie", c["text"], "") for c in e.get("claims") or [] if not c.get("truthful", True)]
    checks = e.get("checks") or {}
    for c in checks.get("clue_cards") or []:
        if c["held"]:
            out.append(("card_real", c["text"], ""))
        else:
            out.append(("card_fake", c["text"], "true anyway" if c["true_in_world"] else "and false"))
    jc = checks.get("job_claim")
    if jc:
        if jc["lie"]:
            out.append(("job_false", f"said they {jc['claimed']}, actually {jc['actual']}", ""))
        else:
            out.append(("job_true", jc["claimed"], ""))
    return out


def top_suspect(e: dict) -> tuple[str, int, str] | None:
    """(name, percent, kind) of the highest suspicion on a turn, ties to the earlier seat in the dict."""
    s = (e.get("action") or {}).get("suspicion")
    if not s:
        return None
    name = max(s, key=lambda k: s[k])
    return name, s[name], e.get("suspicion_kind") or "belief"


def fallback_tag(e: dict) -> str | None:
    """`FALLBACK: blocked` etc. for a turn that fell back (reason from the engine)."""
    if not e.get("fallback"):
        return None
    return f"FALLBACK: {e.get('fallback_reason') or 'unknown'}"


def _q(text: str) -> str:
    return '"' + (text or "") + '"'


def _private(text: str) -> list[str]:
    if not text:
        return []
    return [f"> *private:* {text}"]


def _claims(e: dict) -> list[str]:
    out = []
    for kind, text, note in marks(e):
        if kind == "lie":
            out.append(f"  - **LIE:** {text}")
        elif kind == "card_real":
            out.append(f"  - **CLUE CARD (real):** \"{text}\"")
        elif kind == "card_fake":
            out.append(f"  - **CLUE CARD (FAKE):** \"{text}\" ({note})")
        elif kind == "job_false":
            out.append(f"  - **JOB CLAIM (FALSE):** {text}")
        else:
            out.append(f"  - job claim (true): {text}")
    return out


def _flags(e: dict) -> str:
    bits = []
    fb = fallback_tag(e)
    if fb:
        bits.append(f"[{fb}]")
    if e.get("blocked") and not e.get("fallback"):
        bits.append(f"{e['blocked']} blocked")
    if e.get("truncated_fields"):                    # Stage 2 logs name the trimmed fields
        bits.append("truncated: " + ", ".join(e["truncated_fields"]))
    elif e.get("truncated"):
        bits.append("truncated")
    if e.get("attempts", 1) > 1 and not e.get("fallback"):
        bits.append(f"{e['attempts']} attempts")
    return f" _({', '.join(bits)})_" if bits else ""


def _suspicion(e: dict) -> str:
    s = (e.get("action") or {}).get("suspicion")
    if not s:
        return ""
    kind = "table read" if e.get("suspicion_kind") == "table_read" else "belief"
    vals = ", ".join(f"{k} {v}" for k, v in sorted(s.items(), key=lambda kv: -kv[1]))
    return f"suspicion ({kind}): {vals}"


def _statement(e: dict, L=lambda n: n) -> list[str]:
    sid = e.get("statement_id")
    head = f"**[{sid}] {L(e['player'])}**" if sid else f"**{L(e['player'])}**"
    act = e.get("action") or {}
    extras = []
    if act.get("accuse") and act["accuse"] != "none":
        extras.append(f"accuses {act['accuse']}")
    if act.get("challenges"):
        extras.append("calls out " + ", ".join(act["challenges"]))
    if e.get("turn_phase") == "vote":
        extras.append(f"votes **{act.get('vote')}**")
    if e.get("turn_phase") == "finale_pitch":
        extras.append(f"stated intent: {act.get('stated_intent')}")
    ex = f" ({'; '.join(extras)})" if extras else ""
    text = _q(e["public"]) if e.get("public") else "_(says nothing)_"
    lines = [f"{head}{ex}: {text}{_flags(e)}"]
    lines += _claims(e)
    sus = _suspicion(e)
    if sus:
        lines.append(f"  - _{sus}_")
    lines += _private(e.get("confessional", ""))
    lines.append("")
    return lines


def render(events: list[dict]) -> str:
    start = next(e for e in events if e["type"] == "game_start")
    end = next((e for e in events if e["type"] == "game_end"), None)
    anon = start.get("anonymised", False)
    roles = {p["name"]: p["role"] for p in start["players"]}
    L = labeller(start)
    out = [f"# Inside Job — {start['game_id']}", ""]
    out.append(f"Rules v{start['rules_version']} · log v{start['log_version']} · seed {start['seed']}"
               + (" · anonymised (codenames)" if anon else ""))
    out.append("")
    trial = start.get("trial")
    if trial:
        out.append(f"**Benchmark trial: {trial['kind']} trial.** Test model `{trial['test_model']}` plays "
                   f"the {'moles' if trial['kind'] == 'mole' else 'crew'}; reference model "
                   f"`{trial['reference_model']}` plays the {'crew' if trial['kind'] == 'mole' else 'moles'}.")
        out.append("")
    if end:
        out.append(f"**Result: {end['winner']} win ({end['reason']}) after {end['rounds']} "
                   f"round{'s' if end['rounds'] != 1 else ''}.** Final score: clean "
                   f"{end.get('clean_jobs', 0)}, blown {end.get('blown_jobs', 0)}. "
                   f"Moles: {', '.join(start['moles'])}.")
    else:
        out.append("**Result: game did not finish.**")
    out.append("")
    out.append("## Cast")
    out.append("")
    if anon:
        out.append("Players sit under heist codenames; the audience sees the model behind each one.")
        out.append("")
        out += ["| Seat | Codename | Model | Model id | Role |", "|---|---|---|---|---|"]
        for p in start["players"]:
            out.append(f"| {p['seat'] + 1} | {p['name']} | {p['model_name']} | `{p['model']}` | {p['role']} |")
    else:
        out += ["| Seat | Name | Model | Role |", "|---|---|---|---|"]
        for p in start["players"]:
            out.append(f"| {p['seat'] + 1} | {p['name']} | `{p['model']}` | {p['role']} |")
    out.append(f"\nFirst leader: {L(start['first_leader'])}.")
    out.append(conditions_line(events).replace("   ", " · ").capitalize() + ".")
    out.append("")

    rounds = sorted({e["round"] for e in events if e["type"] == "round_start"})
    for r in rounds:
        ev = [e for e in events if e["round"] == r and e["phase"] not in ("cut", "finale", "end", "setup")]
        rs = next(e for e in ev if e["type"] == "round_start")
        out.append(f"## Round {r}")
        out.append("")
        out.append(f"Leader: **{L(rs['leader'])}**. Still in: {', '.join(rs['alive'])}. "
                   f"Score: clean {rs.get('clean_jobs', 0)}, blown {rs['blown_jobs']}.")
        out.append("")
        out.append("### Clues")
        out.append("")
        clue_turns = {e["player"]: e for e in ev if e["type"] == "turn" and e["turn_phase"] == "clue"}
        deal = next((e for e in ev if e["type"] == "clue_deal"), None)
        if deal is not None:
            out.append(f"_Intel dealt to {deal['k']} player{'s' if deal['k'] != 1 else ''}: "
                       f"{', '.join(L(n) for n in deal['recipients']) or 'nobody'}._")
            out.append("")
        for c in (e for e in ev if e["type"] == "clue"):
            p = c["player"]
            out.append(f"**{L(p)}** ({roles[p]}) — clue: {_q(c['clue']['text'])}")
            t = clue_turns.get(p)
            if t:
                ww = (t.get("action") or {}).get("whisper_with")
                if ww is not None:
                    out.append(f"  - asks to whisper with: {ww}{_flags(t)}")
                sus = _suspicion(t)
                if sus:
                    out.append(f"  - _{sus}_")
                out += _private(t.get("confessional", ""))
            out.append("")
        wp = next((e for e in ev if e["type"] == "whisper_pairs"), None)
        if wp is not None:
            out.append("### Whispers")
            out.append("")
            out.append("Pairs: " + ("; ".join(f"{L(a)} ↔ {L(b)}" for a, b in wp["pairs"]) or "none") + ".")
            out.append("")
            for a, b in wp["pairs"]:
                msgs = [e for e in ev if e["type"] == "turn" and e["turn_phase"] == "whisper"
                        and {e["player"], e.get("partner")} == {a, b}]
                if msgs:
                    out.append(f"**{L(a)} ↔ {L(b)}**")
                    out.append("")
                for m in msgs:
                    out.append(f"**{L(m['player'])} → {L(m['partner'])}:** {_q(m['public'])}{_flags(m)}")
                    out += _claims(m)
                    sus = _suspicion(m)
                    if sus:
                        out.append(f"  - _{sus}_")
                    out += _private(m.get("confessional", ""))
                    out.append("")
        out.append("### The job")
        out.append("")
        pick = next((e for e in ev if e["type"] == "job_pick"), None)
        pick_turn = next((e for e in ev if e["type"] == "turn" and e["turn_phase"] == "pick"), None)
        if pick:
            out.append(f"**{L(pick['leader'])}** picks {', '.join(pick['team'])} for _{pick['job_name']}_.")
            out.append("")
        if pick_turn:
            out += _statement(pick_turn, L)
        for j in (e for e in ev if e["type"] == "turn" and e["turn_phase"] == "job"):
            out.append(f"**{L(j['player'])}** (mole) chooses **{j['action']['choice']}**{_flags(j)}")
            out += _private(j.get("confessional", ""))
            out.append("")
        res = next((e for e in ev if e["type"] == "job_result"), None)
        if res:
            verdict = f"**BLOWN** ({res['sabotages']} sabotage{'s' if res['sabotages'] != 1 else ''})" \
                if res["blown"] else "clean"
            out.append(f"Result: {verdict}. **Score: clean {res.get('clean_jobs', 0)} - blown {res['blown_jobs']}.**")
            out.append("")
        talk = [e for e in ev if e["type"] == "turn" and e["turn_phase"] == "discuss"]
        if talk:
            out.append("### Discussion")
            out.append("")
            cur = None
            for e in talk:
                if e.get("pass") != cur:
                    cur = e.get("pass")
                    out.append(f"_Pass {cur}_")
                    out.append("")
                out += _statement(e, L)
        votes = [e for e in ev if e["type"] == "turn" and e["turn_phase"] == "vote"]
        vr = next((e for e in ev if e["type"] == "vote_result"), None)
        if votes or vr:
            out.append("### Vote")
            out.append("")
            for e in votes:
                out += _statement(e, L)
            if vr:
                out += ["| Player | Votes |", "|---|---|"]
                for n, c in sorted(vr["tally"].items(), key=lambda kv: -kv[1]):
                    out.append(f"| {L(n)} | {c} |")
                out.append("")
                tb = ""
                if vr["tiebreak"]:
                    tb = f" Tie between {', '.join(vr['tied'])}, broken by {vr['tiebreak']}."
                out.append(f"**{L(vr['eliminated'])} is out — revealed as {vr['role'].upper()}.**{tb}")
                out.append("")
        rec = next((e for e in ev if e["type"] == "recap"), None)
        if rec:
            out.append("### Recap")
            out.append("")
            out.append(f"> {rec['text']}" if rec.get("text") else
                       f"> _(no recap{': ' + rec['fallback_reason'] if rec.get('fallback_reason') else ''})_")
            out.append("")

    endev = [e for e in events if e["phase"] in ("cut", "finale")]
    if endev:
        cut = [e for e in endev if e["phase"] == "cut"]
        if cut:
            out.append("## The Cut")
            out.append("")
            for e in cut:
                if e["type"] == "turn" and e["turn_phase"] == "cut_pitch":
                    out += _statement(e, L)
                elif e["type"] == "turn" and e["turn_phase"] == "cut_vote":
                    out.append(f"**{L(e['player'])}** sends **{e['action']['finalist']}** through{_flags(e)}")
                    out += _private(e.get("confessional", ""))
                    out.append("")
                elif e["type"] == "cut_result":
                    tb = f" (tie broken by {e['tiebreak']})" if e.get("tiebreak") else ""
                    out.append(f"Tally: {', '.join(f'{k} {v}' for k, v in e['tally'].items())}. "
                               f"Finalists: **{' and '.join(e['finalists'])}**{tb}.")
                    out.append("")
        fin = [e for e in endev if e["phase"] == "finale"]
        if fin:
            out.append("## Finale: split or steal")
            out.append("")
            for e in fin:
                if e["type"] == "turn" and e["turn_phase"] == "finale_pitch":
                    out += _statement(e, L)
                elif e["type"] == "turn" and e["turn_phase"] == "finale_choice":
                    out.append(f"**{L(e['player'])}** chooses **{e['action']['choice'].upper()}**{_flags(e)}")
                    out += _private(e.get("confessional", ""))
                    out.append("")
                elif e["type"] == "finale_result":
                    out.append("Result: " + "; ".join(f"{L(n)} {e['choices'][n]} (said {e['stated'][n]}) -> {e['payouts'][n]}"
                                                      for n in e["finalists"]) + ".")
                    out.append("")

    if end:
        out.append("## Payouts")
        out.append("")
        out += ["| Player | Role | Payout |", "|---|---|---|"]
        for p in start["players"]:
            out.append(f"| {L(p['name'])} | {p['role']} | {end['payouts'].get(p['name'], 0)} |")
        out.append("")

    usage, calls = usage_from_events(events)
    out.append("## Token report")
    out.append("")
    out.append(conditions_line(events).replace("   ", " · ").capitalize() + ".")
    out.append("")
    out += ["| Model | Calls | Input | Output | Cache read | Cache write | Thinking | Blocked | Fallbacks | Cost (list USD) |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for m, u in list(usage["by_model"].items()) + [("**total**", usage["total"])]:
        out.append(f"| {m} | {u['calls']} | {u['input']} | {u['output']} | {u['cache_read']} | "
                   f"{u['cache_creation']} | {u['thinking']} | {u['blocked']} | {u['fallbacks']} | {u['cost_usd']:.4f} |")
    out.append("")
    fallbacks = sum(1 for e in events if e["type"] == "turn" and e.get("fallback"))
    wall = end.get("wall_s") if end else None
    out.append(f"Calls: {calls}. Fallbacks: {fallbacks}. Wall time: "
               f"{f'{wall:.1f}s' if wall is not None else 'n/a'}.")
    out.append("")
    return "\n".join(out)
