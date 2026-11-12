"""Watch a game live, or replay one (SPEC section 13).

`Renderer` turns log events into readable terminal text, one event at a time, in two views:

- audience: everything (cast and roles, clues, whispers, confessionals marked private, lies,
  real/fake clue cards, false job claims, top suspects, job choices, the score, votes, the
  finale and the token report). In an anonymised game every speaker reads `Codename (Model)`.
- table: exactly what the players collectively see, from `log.project(event, None)`: public
  events only, codenames only, no roles until revealed, no private text, tags, verdicts or
  suspicion. Vote turns are held back until the vote resolves.

`follow` tails a growing JSONL log and feeds each complete line to a callback, stopping after
`game_end`. Standard library only; ANSI colour only when asked for.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import textwrap
import time
from pathlib import Path

from .log import project, visible_to
from .results import conditions_line, token_report
from .transcript import fallback_tag, labeller, marks, top_suspect

STYLES = {"bold": "1", "dim": "2", "italic": "3", "red": "31", "green": "32", "yellow": "33",
          "blue": "34", "magenta": "35", "cyan": "36", "grey": "90", "rev": "7"}
TURN_PHASES_PRINTED = {"pick", "discuss", "vote", "whisper", "cut_pitch", "finale_pitch"}


def want_color(stream, no_color: bool) -> bool:
    if no_color or os.environ.get("NO_COLOR"):
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


class Renderer:
    def __init__(self, view: str = "audience", color: bool = False, width: int | None = None, out=None,
                 pace: float = 0.0, sleep=time.sleep):
        if view not in ("audience", "table"):
            raise ValueError("view must be audience or table")
        self.view = view
        self.color = color
        self.width = width or min(max(shutil.get_terminal_size((100, 24)).columns, 60), 120)
        self.out = out or sys.stdout
        self.pace = pace
        self.sleep = sleep
        self.events: list[dict] = []
        self.start: dict | None = None
        self.table: dict | None = None
        self.L = lambda n: n
        self.roles: dict[str, str] = {}
        self.held_votes: list[dict] = []
        self.whisper_open: tuple | None = None
        self.discuss_pass = None
        self.last_turn_at: float | None = None
        self.done = False
        self.quiet = False                      # catch-up mode: track state, print nothing

    # ---------------------------------------------------------------- styling
    def c(self, text: str, *styles: str) -> str:
        if not self.color or not styles:
            return text
        return "\033[" + ";".join(STYLES[s] for s in styles) + "m" + text + "\033[0m"

    def wrap(self, text: str, indent: str = "", first: str | None = None, style=()) -> list[str]:
        first = indent if first is None else first
        lines = textwrap.wrap(text, width=self.width, initial_indent=first, subsequent_indent=indent,
                              break_long_words=False, break_on_hyphens=False) or [first.rstrip()]
        return [self.c(x, *style) for x in lines]

    def name(self, n: str) -> str:
        return self.c(self.L(n), "bold") if self.view == "audience" else self.c(n, "bold")

    def role_tag(self, n: str) -> str:
        if self.view != "audience":
            return ""
        r = self.roles.get(n)
        return " " + (self.c("[MOLE]", "red", "bold") if r == "mole" else self.c("[crew]", "grey")) if r else ""

    def rule(self, title: str, char: str = "═") -> list[str]:
        t = f" {title} "
        side = max(3, (self.width - len(t)) // 2)
        return ["", self.c(char * side + t + char * max(3, self.width - side - len(t)), "bold", "yellow")]

    # ---------------------------------------------------------------- feeding
    def feed(self, ev: dict):
        """Render one event (as written to the log) and print it."""
        self.events.append(ev)
        lines = self.lines(ev)
        if not lines or self.quiet:
            return
        if self.pace and ev.get("type") == "turn":
            now = time.monotonic()
            if self.last_turn_at is not None:
                wait = self.pace - (now - self.last_turn_at)
                if wait > 0:
                    self.sleep(wait)
            self.last_turn_at = time.monotonic()
        self.out.write("\n".join(lines) + "\n")
        self.out.flush()

    def lines(self, ev: dict) -> list[str]:
        t = ev.get("type")
        if t == "game_start":
            self.start = ev
            if self.view == "audience":           # the table view never learns models or roles
                self.L = labeller(ev)
                self.roles = {p["name"]: p["role"] for p in ev["players"]}
        if t == "game_end":
            self.done = True
        if self.view == "table":
            if not visible_to(ev, None):
                return []
            ev = project(ev, None)
            if ev is None:
                return []
        fn = getattr(self, "r_" + t, None)
        return fn(ev) if fn else []

    # ---------------------------------------------------------------- events
    def r_game_start(self, e):
        out = self.rule("INSIDE JOB", "█")
        out.append(self.c(f"{e['game_id']} · rules v{e['rules_version']} · seed {e['seed']}"
                          + (" · codenames" if e.get("anonymised") else ""), "grey"))
        trial = e.get("trial")
        if trial:
            out.append(f"Benchmark {trial['kind']} trial: {trial['test_model']} plays the "
                       f"{'moles' if trial['kind'] == 'mole' else 'crew'}, {trial['reference_model']} the rest.")
        out.append(self.c(conditions_line([e]), "grey"))
        out.append("")
        out.append(self.c("THE CAST", "bold"))
        for p in sorted(e["players"], key=lambda p: p["seat"]):
            model = f"{p['model_name']:<14} {self.c(p['model'], 'grey')}"
            name = f"{p['name']:<10} " if e.get("anonymised") else ""
            out.append(f"  {p['seat'] + 1}. {self.c(name, 'bold')}{model} {self.role_tag(p['name'])}")
        out.append(f"First leader: {self.name(e['first_leader'])}.")
        return out

    def r_table(self, e):
        if self.view == "audience":
            return []
        out = self.rule("INSIDE JOB", "█")
        out.append(f"Seats, clockwise: {', '.join(e['seats'])}.")
        out.append(f"{e['num_moles']} moles among them. Pot {e['pot']}.")
        return out

    def score(self, clean, blown) -> str:
        g = (self.start or {}).get("config", {}).get("game", {}) if self.start else {}
        ct, st = g.get("clean_target", 3), g.get("sabotage_target", 3)
        return (f"SCORE  {self.c(f'clean {clean}/{ct}', 'green', 'bold')}  ·  "
                f"{self.c(f'blown {blown}/{st}', 'red', 'bold')}")

    def r_round_start(self, e):
        out = self.rule(f"ROUND {e['round']}")
        out.append(f"Leader {self.name(e['leader'])} · {len(e['alive'])} still in · "
                   + self.score(e.get("clean_jobs", 0), e["blown_jobs"]))
        out.append(self.c("Still in: " + ", ".join(e["alive"]), "grey"))
        self.discuss_pass = None
        return out

    def head(self, title: str) -> list[str]:
        return ["", self.c(f"── {title} ", "bold", "cyan") + self.c("─" * max(3, self.width - len(title) - 4), "cyan")]

    def r_clue_deal(self, e):
        out = self.head("CLUES")
        names = ", ".join(self.L(n) for n in e["recipients"]) or "nobody"
        out.append(self.c(f"Intel went to {e['k']}: {names}", "grey"))
        return out

    def r_clue(self, e):
        c = e["clue"]
        if c.get("kind") == "none":
            return [f"  {self.name(e['player'])}{self.role_tag(e['player'])} {self.c('no intel', 'grey')}"]
        return [f"  {self.name(e['player'])}{self.role_tag(e['player'])} ← "
                + self.c('"' + c["text"] + '"', "yellow", "bold")]

    def r_whisper_pairs(self, e):
        out = self.head("WHISPERS")
        pairs = "; ".join(f"{self.name(a)} ↔ {self.name(b)}" for a, b in e["pairs"]) or "none"
        out.append(f"Pairs: {pairs}")
        return out

    def r_job_pick(self, e):
        out = []
        out.append(f"{self.c('JOB', 'bold')} \"{e['job_name']}\" · team: "
                   + ", ".join(self.name(n) for n in e["team"]))
        return out

    def r_job_choices(self, e):
        bits = []
        for n, ch in e["choices"].items():
            bits.append(f"{self.L(n)} " + (self.c("SABOTAGE", "red", "bold") if ch == "sabotage" else "help"))
        return ["  choices: " + " · ".join(bits)]

    def r_job_result(self, e):
        s = e["sabotages"]
        verdict = (self.c(f"JOB BLOWN ({s} sabotage{'s' if s != 1 else ''})", "red", "bold", "rev") if e["blown"]
                   else self.c("JOB CLEAN", "green", "bold", "rev"))
        return ["", f"{verdict}   " + self.score(e.get("clean_jobs", 0), e["blown_jobs"])]

    def r_vote_result(self, e):
        out = []
        if self.held_votes:                       # table view: vote reasons revealed with the result
            out += self.head("VOTE")
        for t in self.held_votes:
            out += self.turn_lines(t)
        self.held_votes = []
        out += self.head("VOTE RESULT")
        by: dict[str, list[str]] = {}
        for voter, tgt in e["votes"].items():
            by.setdefault(tgt, []).append(voter)
        width = max(len(self.L(n)) for n in by) if by else 10
        for tgt, voters in sorted(by.items(), key=lambda kv: -len(kv[1])):
            bar = "█" * len(voters)
            out.append(f"  {self.c(self.L(tgt).ljust(width), 'bold')} {self.c(bar, 'magenta')} {len(voters)}"
                       f"  {self.c('(' + ', '.join(voters) + ')', 'grey')}")
        if e.get("tiebreak"):
            how = "the leader's vote" if e["tiebreak"] == "leader" else "random draw"
            out.append(f"  Tie between {', '.join(self.L(n) for n in e['tied'])}, broken by {how}.")
        role = e["role"]
        out.append(f"  {self.name(e['eliminated'])} is out, revealed as "
                   + (self.c("A MOLE", "red", "bold") if role == "mole" else self.c("CREW", "green", "bold")) + ".")
        return out

    def r_recap(self, e):
        out = self.head("RECAP")
        if e.get("text"):
            out += self.wrap(e["text"], "  ", style=("italic",))
        else:
            reason = e.get("fallback_reason")
            out.append(self.c("  (no recap" + (f": {reason}" if reason and self.view == "audience" else "") + ")", "grey"))
        return out

    def r_cut_result(self, e):
        out = self.head("THE CUT RESULT")
        out.append("  Tally: " + ", ".join(f"{self.L(k)} {v}" for k, v in e["tally"].items()))
        out.append(f"  Finalists: {' and '.join(self.name(f) for f in e['finalists'])}"
                   + (f" (tie broken by {e['tiebreak']})" if e.get("tiebreak") else ""))
        return out

    def r_finale_result(self, e):
        out = self.head("FINALE RESULT")
        for n in e["finalists"]:
            ch = e["choices"][n]
            out.append(f"  {self.name(n)} said {e['stated'][n]}, chose "
                       + (self.c("STEAL", "red", "bold") if ch == "steal" else self.c("SPLIT", "green", "bold"))
                       + f" → {e['payouts'][n]}")
        return out

    def r_game_end(self, e):
        out = self.rule(f"{e['winner'].upper()} WIN ({e['reason']}) after {e['rounds']} rounds", "█")
        out.append(self.score(e.get("clean_jobs", 0), e.get("blown_jobs", 0)))
        if self.view == "audience" and self.start:
            out.append("Moles: " + ", ".join(self.L(m) for m in self.start["moles"]))
        pay = ", ".join(f"{self.L(n)} {v}" for n, v in e["payouts"].items() if v) or "nobody"
        out.append(f"Payouts: {pay}")
        if self.view == "audience":
            out.append("")
            out += token_report(self.events).splitlines()
        return out

    # ---------------------------------------------------------------- turns
    def r_turn(self, e):
        tp = e.get("turn_phase")
        if self.view == "table" and tp == "vote":
            self.held_votes.append(e)
            return []
        return self.turn_lines(e)

    def private(self, text: str) -> list[str]:
        if not text or self.view != "audience":
            return []
        return self.wrap(text, "        ", "      ┆ private: ", style=("dim", "italic"))

    def extras(self, e) -> list[str]:
        """Marks, suspicion and fallback for the audience."""
        if self.view != "audience":
            return []
        out = []
        for kind, text, note in marks(e):
            if kind == "lie":
                out += self.wrap(f"LIE: {text}", "             ", "      ", ("red", "bold"))
            elif kind == "card_real":
                out.append("      " + self.c("CLUE CARD (real)", "green", "bold") + f" \"{text}\"")
            elif kind == "card_fake":
                out.append("      " + self.c("CLUE CARD (FAKE)", "red", "bold") + f" \"{text}\" "
                           + self.c(f"({note})", "grey"))
            elif kind == "job_false":
                out.append("      " + self.c("JOB CLAIM (FALSE)", "red", "bold") + f" {text}")
            else:
                out.append("      " + self.c(f"job claim (true): {text}", "grey"))
        ts = top_suspect(e)
        if ts:
            who, pct, kind = ts
            label = "thinks the table suspects" if kind == "table_read" else "top suspect"
            out.append("      " + self.c(f"{label}: {self.L(who)} {pct}%", "yellow"))
        return out

    def flag(self, e) -> str:
        if self.view != "audience":
            return ""
        fb = fallback_tag(e)
        bits = []
        if fb:
            bits.append(self.c(f"[{fb}]", "red", "bold"))
        elif e.get("blocked"):
            bits.append(self.c(f"[blocked x{e['blocked']}, then answered]", "red"))
        return (" " + " ".join(bits)) if bits else ""

    def say(self, who: str, text: str, tail: str = "", style=()) -> list[str]:
        body = f"\"{text}\"" if text else "(says nothing)"
        lead = f"  {who}{tail}: "
        # Wrap on the plain text, then put the coloured label back.
        plain_lead = f"  {who}{tail}: " if not self.color else None
        if plain_lead is not None:
            return self.wrap(body, "      ", plain_lead, style)
        return [lead + line.lstrip() if i == 0 else line
                for i, line in enumerate(self.wrap(body, "      ", " " * 6, style))]

    def turn_lines(self, e) -> list[str]:
        tp = e["turn_phase"]
        p = e["player"]
        act = e.get("action") or {}
        who = self.name(p) + self.role_tag(p)
        out: list[str] = []
        if tp == "clue":
            ww = act.get("whisper_with")
            ask = f"asks to whisper with {self.L(ww)}" if ww and ww != "none" else "no whisper request"
            out.append(f"  {who} {self.c(ask, 'grey')}{self.flag(e)}")
        elif tp == "whisper":
            if self.whisper_open != tuple(sorted((p, e.get("partner", "")))):
                self.whisper_open = tuple(sorted((p, e.get("partner", ""))))
                out.append("")
            out += self.say(f"{who} → {self.name(e['partner'])}", e.get("public", ""), self.flag(e), ("cyan",))
        elif tp == "pick":
            out.append("")
            out += self.say(f"{self.c('LEADER', 'bold')} {who}", e.get("public", ""), self.flag(e))
        elif tp == "job":
            ch = act.get("choice")
            out.append(f"  {who} chooses " + (self.c("SABOTAGE", "red", "bold") if ch == "sabotage" else "help")
                       + self.flag(e))
        elif tp == "discuss":
            if e.get("pass") != self.discuss_pass:
                self.discuss_pass = e.get("pass")
                out += self.head(f"DISCUSSION, pass {self.discuss_pass}")
            sid = e.get("statement_id")
            bits = []
            if act.get("accuse") and act["accuse"] != "none":
                bits.append(f"accuses {self.L(act['accuse'])}")
            if act.get("challenges"):
                bits.append("calls out " + ", ".join(act["challenges"]))
            jc = act.get("job_claim")
            if jc in ("helped", "sabotaged"):
                bits.append(f"says they {jc}")
            tail = (" " + self.c("(" + "; ".join(bits) + ")", "magenta")) if bits else ""
            prefix = self.c(f"[{sid}] ", "grey") if sid else ""
            out += self.say(prefix + who, e.get("public", ""), tail + self.flag(e))
            if self.view == "table":
                from .clues import card_as_clue
                for c in act.get("clue_cards") or []:
                    out.append("      claims clue: \"" + card_as_clue(c)["text"] + "\"")
        elif tp == "vote":
            if self.view == "audience" and not any(x.get("turn_phase") == "vote" and x["round"] == e["round"]
                                                    for x in self.events[:-1] if x.get("type") == "turn"):
                out += self.head("VOTE")
            out += self.say(f"{who} votes {self.c(self.L(act.get('vote', '?')), 'bold', 'magenta')}",
                            e.get("public", ""), self.flag(e))
        elif tp == "cut_pitch":
            if not any(x.get("turn_phase") == "cut_pitch" for x in self.events[:-1] if x.get("type") == "turn"):
                out += self.rule("THE CUT")
            out += self.say(who, e.get("public", ""), self.flag(e))
        elif tp == "cut_vote":
            out.append(f"  {who} sends {self.name(act.get('finalist', '?'))} through{self.flag(e)}")
        elif tp == "finale_pitch":
            if not any(x.get("turn_phase") == "finale_pitch" for x in self.events[:-1] if x.get("type") == "turn"):
                out += self.rule("FINALE: SPLIT OR STEAL")
            intent = act.get("stated_intent")
            tail = f" (says {intent})" if intent and intent != "unstated" else ""
            out += self.say(who, e.get("public", ""), self.c(tail, "magenta") + self.flag(e))
        elif tp == "finale_choice":
            ch = act.get("choice", "?")
            out.append(f"  {who} chooses " + (self.c("STEAL", "red", "bold") if ch == "steal"
                                               else self.c("SPLIT", "green", "bold")) + self.flag(e))
        if self.view == "table" and tp == "whisper":
            return []                              # never visible to the public anyway
        out += self.extras(e)
        out += self.private(e.get("confessional", ""))
        return out


# --------------------------------------------------------------------------- following a file

def follow(path, on_event, *, poll: float = 0.1, timeout: float | None = None, sleep=time.sleep,
           stop=lambda: False) -> int:
    """Tail a JSONL log, calling `on_event` once per complete line, until `game_end`.

    Partial lines (a write in progress) are kept until their newline arrives. Returns the number
    of events seen. `timeout` (seconds without a new line) stops a dead follow."""
    n = 0
    buf = ""
    idle = 0.0
    with open(path, encoding="utf-8") as f:
        while True:
            chunk = f.readline()
            if chunk:
                idle = 0.0
                buf += chunk
                if not buf.endswith("\n"):
                    continue
                line, buf = buf.strip(), ""
                if not line:
                    continue
                ev = json.loads(line)
                n += 1
                on_event(ev)
                if ev.get("type") == "game_end":
                    return n
                continue
            if stop():
                return n
            if timeout is not None and idle >= timeout:
                return n
            sleep(poll)
            idle += poll


def newest_log(out_dir, wait: bool = True, poll: float = 0.5, sleep=time.sleep) -> Path:
    d = Path(out_dir)
    while True:
        logs = ([p for p in d.glob("*.jsonl") if p.name != "index.jsonl" and not p.name.endswith(".raw.jsonl")]
                if d.exists() else [])                  # never a raw sidecar file (docs/RAWLOG.md)
        if logs:
            return max(logs, key=lambda p: p.stat().st_mtime)
        if not wait:
            raise FileNotFoundError(f"no game logs in {d}")
        sleep(poll)


def game_over(path) -> bool:
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 65536))
            tail = f.read().decode("utf-8", "replace").strip().splitlines()
        return bool(tail) and '"type": "game_end"' in tail[-1]
    except OSError:
        return False


def watch(path, renderer: Renderer, from_start: bool | None = None, poll: float = 0.1) -> int:
    """Print a log through `renderer`. A finished game is replayed from the start; a game in
    progress starts at the current point (after the cast and the current round's header) unless
    `from_start`."""
    if from_start is None:
        from_start = game_over(path)
    if not from_start:
        with open(path, encoding="utf-8") as f:
            complete = f.read().split("\n")[:-1]          # a partial last line is not an event yet
        existing = [json.loads(x) for x in complete if x.strip()]
        catch_up = len(existing)
        seen = {"n": 0}
        last_round_start = max((i for i, e in enumerate(existing) if e.get("type") == "round_start"), default=-1)

        def feed(ev):
            seen["n"] += 1
            i = seen["n"] - 1
            renderer.quiet = i < catch_up and ev.get("type") not in ("game_start", "table") and i != last_round_start
            renderer.feed(ev)
            renderer.quiet = False
        return follow(path, feed, poll=poll)
    return follow(path, renderer.feed, poll=poll)
