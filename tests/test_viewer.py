"""Browser viewer (SPEC section 16): the read-only server, event decoration, the table projection,
the export, and the page's pure playback core (`buildBeats`, run under node when it is installed).

Mock logs only, written to temporary folders; servers run on free ports on 127.0.0.1."""

import colorsys
import contextlib
import http.client
import io
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path

from inside_job import __main__ as cli
from inside_job import viewer
from inside_job.config import CODENAMES
from inside_job.log import read_log
from inside_job.schemas import STATEMENT_PHASES
from inside_job.transcript import labeller, marks

from helpers import DEFAULT_TOML, Script, job_choice, make_config, pick_with_mole, run_game, suspicion_for
from test_privacy import TOKEN, Planter
from test_transcript_cli import ending_games

FAMILY = re.compile(r"haiku|sonnet|opus|fable|claude", re.IGNORECASE)
CORE = re.compile(r'<script id="ij-core">(.*?)</script>', re.DOTALL)
PRIVATE_KEYS = ("confessional", "claims", "memory", "checks", "suspicion", "suspicion_kind", "whisper_with",
                "_marks", "_role", "_label", "_top_suspect", "_fallback", "model", "model_name", "usage",
                "served_model", "fallback_reason", "rejections", "error_kinds", "blocked", "partners", "shared_with",
                "recipients", "requests", "choices_private")


def lie_script():
    """Discussion turns that table a fake card and claim a job falsely (so marks are not empty)."""
    def discuss(s, player, schema, prompt):
        others = schema["properties"]["move"]["properties"]["accuse"]["enum"]
        cards = [{"kind": "not_mole", "players": [others[0]], "k": 0}]
        return {"accuse": others[0], "challenges": [], "clue_cards": cards,
                "job_claim": "helped" if player in s.game.team else "none", "suspicion": suspicion_for(schema)}
    return Script(2, discuss=discuss, job=job_choice("sabotage"), pick=pick_with_mole)


def write_log(path: Path, events, upto=None, partial: str = ""):
    lines = [json.dumps(e, ensure_ascii=False) for e in events[:upto]]
    path.write_text("".join(x + "\n" for x in lines) + partial, encoding="utf-8")


class ServerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.server, self.thread = viewer.start_in_thread(self.dir, 0)
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def request(self, path, method="GET"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request(method, path)
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, body

    def get_json(self, path):
        status, body = self.request(path)
        self.assertEqual(status, 200, (path, body[:200]))
        return json.loads(body)


# --------------------------------------------------------------------------- 1. game list

class GameList(ServerCase):
    def test_lists_finished_unfinished_and_old_logs(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["run", "--config", str(DEFAULT_TOML), "--seed", "3", "--mock", "--out",
                                       str(self.dir)]), 0)
        finished = next(p for p in self.dir.glob("g-*.jsonl"))
        # an unfinished log (no index row, a half-written last line) and an old-format finished one
        game, _ = run_game(4, make_config(anonymise=True))
        ev = game.log.events
        write_log(self.dir / "g-unfinished-s4.jsonl", [dict(e, game_id="g-unfinished-s4") for e in ev], upto=40,
                  partial='{"seq": 40, "half')
        old = []
        for e in run_game(5, make_config())[0].log.events:
            e = {k: v for k, v in e.items() if k not in ("batch", "truncated_fields")}
            old.append(dict(e, game_id="g-old-s5"))
        write_log(self.dir / "g-old-s5.jsonl", old)
        (self.dir / "notes.jsonl").write_text("{}\n")            # not a game log: never listed
        now = os.path.getmtime(finished)
        os.utime(self.dir / "g-old-s5.jsonl", (now + 1, now + 1))
        os.utime(self.dir / "g-unfinished-s4.jsonl", (now + 2, now + 2))

        games = self.get_json("/api/games")["games"]
        ids = [g["game_id"] for g in games]
        self.assertEqual(ids, ["g-unfinished-s4", "g-old-s5", finished.stem])      # newest first
        for g in games:
            for key in ("game_id", "seed", "batch", "finished", "winner", "reason", "rounds", "spoiled", "cast"):
                self.assertIn(key, g)
            self.assertEqual(len(g["cast"]), 7)
        unf, old_g, fin = games
        self.assertFalse(unf["finished"])
        self.assertIsNone(unf["winner"])
        self.assertEqual(unf["seed"], 4)
        self.assertTrue(old_g["finished"])
        self.assertIsNone(old_g["batch"])
        self.assertEqual(old_g["reason"], old[-1]["reason"])
        self.assertTrue(fin["finished"])
        self.assertFalse(fin["spoiled"])
        row = json.loads((self.dir / "index.jsonl").read_text().splitlines()[0])
        self.assertEqual((fin["winner"], fin["reason"], fin["rounds"], fin["seed"]),
                         (row["winner"], row["reason"], row["rounds"], 3))
        self.assertEqual(fin["cast"], [p["model_name"] for p in sorted(row["players"], key=lambda p: p["seat"])])


# --------------------------------------------------------------------------- 2. paging and live logs

class Paging(ServerCase):
    def test_from_partial_lines_and_done(self):
        game, _ = run_game(6, make_config())
        ev = game.log.events
        path = self.dir / "g-live-s6.jsonl"
        n = len(ev)
        write_log(path, ev, upto=30, partial=json.dumps(ev[30])[:25])
        j = self.get_json("/api/log/g-live-s6?from=0&view=audience")
        self.assertEqual(len(j["events"]), 30)
        self.assertEqual(j["next"], 30)
        self.assertFalse(j["done"])
        self.assertEqual([e["seq"] for e in j["events"]], list(range(30)))
        j = self.get_json("/api/log/g-live-s6?from=30&view=audience")
        self.assertEqual(j["events"], [])                       # the half line waits
        write_log(path, ev, upto=31)                             # now it is complete
        j = self.get_json("/api/log/g-live-s6?from=30&view=audience")
        self.assertEqual([e["seq"] for e in j["events"]], [30])
        self.assertEqual(j["next"], 31)
        j = self.get_json("/api/log/g-live-s6?from=10&view=audience")
        self.assertEqual(j["events"][0]["seq"], 10)
        write_log(path, ev, upto=n - 1)                          # everything but game_end
        j = self.get_json("/api/log/g-live-s6?from=31&view=audience")
        self.assertEqual(j["next"], n - 1)
        self.assertFalse(j["done"])
        write_log(path, ev)
        j = self.get_json(f"/api/log/g-live-s6?from={n - 1}&view=audience")
        self.assertTrue(j["done"])
        self.assertEqual(j["events"][-1]["type"], "game_end")
        self.assertTrue(self.get_json(f"/api/log/g-live-s6?from={n}&view=audience")["done"])
        for view in ("audience", "table"):                       # paging in steps gives the same events
            whole = self.get_json(f"/api/log/g-live-s6?from=0&view={view}")["events"]
            got, at = [], 0
            for cut in list(range(5, n, 17)) + [n]:
                write_log(path, ev, upto=cut)
                j = self.get_json(f"/api/log/g-live-s6?from={at}&view={view}")
                got += j["events"]
                at = j["next"]
            self.assertEqual([e["seq"] for e in got], [e["seq"] for e in whole], view)

    def test_table_view_holds_votes_until_the_result(self):
        game, _ = run_game(7, make_config())
        ev = game.log.events
        first_vote = next(i for i, e in enumerate(ev) if e["type"] == "turn" and e["turn_phase"] == "vote")
        result = next(i for i, e in enumerate(ev) if e["type"] == "vote_result")
        path = self.dir / "g-votes-s7.jsonl"
        write_log(path, ev, upto=first_vote + 3)
        j = self.get_json("/api/log/g-votes-s7?from=0&view=table")
        self.assertEqual(j["next"], first_vote)
        self.assertFalse(any(e.get("turn_phase") == "vote" for e in j["events"]))
        write_log(path, ev, upto=result + 1)
        j2 = self.get_json(f"/api/log/g-votes-s7?from={j['next']}&view=table")
        kinds = [(e["type"], e.get("turn_phase")) for e in j2["events"]]
        self.assertEqual(kinds[-1], ("vote_result", None))
        self.assertEqual(sum(1 for k in kinds if k == ("turn", "vote")), result - first_vote)


# --------------------------------------------------------------------------- 3. audience decoration

class Audience(unittest.TestCase):
    def test_turns_carry_the_python_helpers_values(self):
        game, _ = run_game(2, make_config(clean_target=9, sabotage_target=9, anonymise=True), policy=lie_script())
        raw = game.log.events
        out = viewer.log_slice(raw, "audience", 0)
        self.assertTrue(out["done"])
        dec = out["events"]
        self.assertEqual(len(dec), len(raw))
        L = labeller(raw[0])
        roles = {p["name"]: p["role"] for p in raw[0]["players"]}
        kinds = set()
        for r, d in zip(raw, dec):
            self.assertEqual(r["seq"], d["seq"])
            if r["type"] != "turn":
                continue
            for key in ("_label", "_role", "_marks", "_top_suspect", "_fallback"):
                self.assertIn(key, d)
            self.assertEqual(d["_label"], L(r["player"]))
            self.assertEqual(d["_label"], f"{r['player']} ({next(p['model_name'] for p in raw[0]['players'] if p['name'] == r['player'])})")
            self.assertEqual(d["_role"], roles[r["player"]])
            self.assertEqual(d["_marks"], [list(m) for m in marks(r)])
            kinds |= {m[0] for m in d["_marks"]}
            s = (r.get("action") or {}).get("suspicion")
            if s:
                self.assertEqual(d["_top_suspect"]["pct"], max(s.values()))
            else:
                self.assertIsNone(d["_top_suspect"])
        self.assertTrue({"lie", "card_fake", "job_false"} <= kinds, kinds)
        self.assertIn("_labels", dec[0])
        self.assertEqual(set(dec[0]["config"]), {"game"})          # rules only


# --------------------------------------------------------------------------- 4 and 6. table privacy, export

def table_leaks(test, text: str, game, planter, anonymise: bool):
    """Test 4's check on a whole response (or exported page) body."""
    for t in TOKEN.findall(text):
        info = planter.tokens[t]
        test.assertEqual(info["field"], "public", info)
        test.assertIn(info["phase"], STATEMENT_PHASES, info)
    if anonymise:
        test.assertIsNone(FAMILY.search(text), FAMILY.search(text))
        for p in game.players:
            test.assertNotIn(p.model_name, text)


class TablePrivacy(ServerCase):
    def check_events(self, events, game):
        roles_revealed = set()
        for e in events:
            self.assertNotIn(e["type"], ("game_start", "role", "clue", "clue_deal", "job_choices", "whisper_requests"))
            self.assertNotEqual(e.get("vis"), "engine") if e["type"] != "turn" else None
            for k in PRIVATE_KEYS:
                self.assertNotIn(k, e, (k, e))
            if e["type"] == "turn":
                self.assertIn(e["turn_phase"], STATEMENT_PHASES, e)
                for k in ("choice", "finalist", "suspicion", "whisper_with"):
                    self.assertNotIn(k, e.get("action") or {}, e)
            if "role" in e:
                self.assertEqual(e["type"], "vote_result")
                roles_revealed.add(e["eliminated"])
            if e["type"] == "game_end":
                for k in ("usage", "blocked"):
                    self.assertNotIn(k, e)
        return roles_revealed

    def test_table_view_of_a_privacy_token_game(self):
        checked = 0
        for seed in range(3):
            for anonymise in (True, False):
                planter = Planter(seed)
                gid = f"g-priv-s{seed}{'a' if anonymise else 'n'}"
                game, _ = run_game(seed, make_config(anonymise=anonymise), policy=planter,
                                   log_path=self.dir / f"{gid}.jsonl", game_id=gid)
                status, body = self.request(f"/api/log/{gid}?from=0&view=table")
                self.assertEqual(status, 200)
                text = body.decode("utf-8")
                table_leaks(self, text, game, planter, anonymise)
                j = json.loads(text)
                self.check_events(j["events"], game)
                self.assertTrue(TOKEN.search(text))             # public statements do come through
                # no role is named before its reveal
                first = next(i for i, e in enumerate(j["events"]) if e["type"] == "vote_result")
                before = json.dumps(j["events"][:first])
                self.assertNotIn('"mole"', before)
                self.assertNotIn('"crew"', before)
                # nor in any partial response while the game is being written
                ev = game.log.events
                for cut in range(10, len(ev), 23):
                    write_log(self.dir / f"{gid}.jsonl", ev, upto=cut)
                    status, body = self.request(f"/api/log/{gid}?from=0&view=table")
                    table_leaks(self, body.decode("utf-8"), game, planter, anonymise)
                    self.check_events(json.loads(body)["events"], game)
                checked += 1
        self.assertEqual(checked, 6)


class Export(unittest.TestCase):
    def check_self_contained(self, html: str):
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)
        self.assertIsNone(re.search(r"<script[^>]*\bsrc\s*=", html, re.IGNORECASE))
        self.assertIsNone(re.search(r"<link[^>]*\bhref\s*=", html, re.IGNORECASE))
        self.assertIsNone(re.search(r"@import|url\(\s*['\"]?(?!data:|#)", html))

    def embedded(self, html: str) -> dict:
        m = re.search(r'<script id="ij-data" type="application/json">(.*?)</script>', html, re.DOTALL)
        self.assertIsNotNone(m)
        return json.loads(m.group(1))

    def test_export_both_views(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            planter = Planter(1)
            game, _ = run_game(1, make_config(anonymise=True), policy=planter, log_path=d / "g-exp-s1.jsonl",
                               game_id="g-exp-s1")
            # a URL in public text must not read as a reference in the export
            events = read_log(d / "g-exp-s1.jsonl")
            t = next(e for e in events if e["type"] == "turn" and e["turn_phase"] == "discuss")
            t["public"] += " see https://example.com/x </script><script>alert(1)</script>"
            write_log(d / "g-exp-s1.jsonl", events)
            for view in ("audience", "table"):
                out = d / f"exp-{view}.html"
                with contextlib.redirect_stdout(io.StringIO()):
                    rc = cli.main(["view", str(d / "g-exp-s1.jsonl"), "--export", str(out), "--view", view])
                self.assertEqual(rc, 0)
                html = out.read_text(encoding="utf-8")
                self.check_self_contained(html)
                self.assertEqual(html.count("</script>"), viewer.page_html().count("</script>"))
                data = self.embedded(html)
                self.assertEqual(data["view"], view)
                self.assertTrue(data["done"])
                self.assertEqual(data["events"], viewer.log_slice(read_log(d / "g-exp-s1.jsonl"), view, 0)["events"])
                self.assertIn("https://example.com/x", json.dumps(data["events"]))   # the text itself survives
                if view == "table":
                    table_leaks(self, html.replace("\\/", "/"), game, planter, True)
                    self.assertTrue(TOKEN.search(html))
                else:
                    self.assertIn("confessional", html)
            # --latest and a game id work too; unfinished logs export
            write_log(d / "g-half-s2.jsonl", [dict(e, game_id="g-half-s2") for e in events[:50]])
            os.utime(d / "g-half-s2.jsonl", (os.path.getmtime(d / "g-exp-s1.jsonl") + 5,) * 2)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["view", "--latest", "--out", str(d), "--export", str(d / "l.html")]), 0)
                self.assertEqual(cli.main(["view", "g-exp-s1", "--out", str(d), "--export", str(d / "i.html")]), 0)
            self.assertFalse(self.embedded((d / "l.html").read_text())["done"])
            self.assertEqual(self.embedded((d / "i.html").read_text())["game_id"], "g-exp-s1")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(["view", "g-nope-s1", "--out", str(d), "--export", str(d / "x.html")]), 2)
                self.assertEqual(cli.main(["view", "--out", str(d), "--export", str(d / "x.html")]), 2)


# --------------------------------------------------------------------------- 5. what is served

class Serving(ServerCase):
    def test_bad_ids_methods_and_binding(self):
        game, _ = run_game(3, make_config(), log_path=self.dir / "g-ok-s3.jsonl", game_id="g-ok-s3")
        (self.dir / "index.jsonl").write_text("{}\n")
        (self.dir / "g-ok-s3.md").write_text("transcript")
        self.assertEqual(self.request("/api/log/g-ok-s3")[0], 200)
        self.assertEqual(self.request("/")[0], 200)
        bad = ["/api/log/../x", "/api/log/..%2Fx", "/api/log/index", "/api/log/index.jsonl", "/api/log/g-ok-s3.jsonl",
               "/api/log//etc/passwd", "/api/log/%2Fetc%2Fpasswd", "/api/log/g-ok-s3%2F..%2Findex",
               "/api/log/g-ok-s3/../index", "/api/log/g-missing-s1", "/api/log/G-ok-s3", "/api/log/g-ok-s3%00",
               "/api/log/g-..", "/api/log/", "/index.jsonl", "/g-ok-s3.jsonl", "/g-ok-s3.md", "/games/g-ok-s3.jsonl",
               "/viewer/index.html", "/../inside_job/viewer.py", "/api/games/x"]
        for path in bad:
            status, body = self.request(path)
            self.assertEqual(status, 404, path)
            self.assertNotIn(b"seq", body)
        self.assertEqual(self.request("/api/log/g-ok-s3?view=nope")[0], 400)
        for method in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS"):
            self.assertEqual(self.request("/api/log/g-ok-s3", method)[0], 405, method)
            self.assertEqual(self.request("/", method)[0], 405, method)
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertIsNone(viewer.resolve_game(self.dir, "../g-ok-s3"))
        self.assertIsNone(viewer.resolve_game(self.dir, "g-ok-s3/../../x"))
        self.assertEqual(viewer.resolve_game(self.dir, "g-ok-s3"), (self.dir / "g-ok-s3.jsonl").resolve())

    def test_port_taken_is_a_clear_error(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = cli.main(["view", "--out", str(self.dir), "--port", str(self.port), "--no-open"])
        self.assertEqual(rc, 2)
        self.assertIn(f"127.0.0.1:{self.port}", err.getvalue())


# --------------------------------------------------------------------------- 7. the page itself

class Page(unittest.TestCase):
    def test_page_has_no_external_reference(self):
        html = viewer.page_html()
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)
        self.assertIsNone(re.search(r"//[A-Za-z0-9-]+\.[A-Za-z]{2,}/", html))      # protocol-relative URLs
        self.assertIsNone(re.search(r"\bsrc\s*=", html))
        self.assertIsNone(re.search(r"<link\b", html, re.IGNORECASE))
        self.assertIsNone(re.search(r"@import|url\(\s*['\"]?(?!data:|#)|@font-face", html))
        self.assertIn(viewer.DATA_TAG, html)
        self.assertIn("window.insideJob", html)
        self.assertIn("selfCheck", html)
        self.assertIsNotNone(CORE.search(html))


# --------------------------------------------------------------------------- 8. buildBeats under node

HARNESS = r"""
const fs = require("fs");
const core = require(process.argv[2]);
const cases = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const out = cases.map(c => {
  const beats = core.buildBeats(c.events, c.view, { rules: c.rules });
  return beats.map(b => ({ i: b.i, dur: b.dur, kind: b.kind, key: b.key, turn: !!(b.ev && b.ev.type === "turn") }));
});
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class Beats(unittest.TestCase):
    def test_build_beats_for_every_ending_and_odd_logs(self):
        cases, labels = [], []
        for label, (cfg, script) in ending_games().items():
            game, _ = run_game(11, cfg, policy=script)
            ev = game.log.events
            odd = [{"seq": 9999, "type": "mystery", "round": 1, "phase": "clue", "vis": "public"},
                   {"type": "turn", "turn_phase": "new_phase", "player": "X", "public": "hello there"},
                   "not an event", None, {"type": "vote_result"}]
            variants = {"full": ev,
                        "unfinished": ev[: len(ev) * 2 // 3],
                        "old": [{k: v for k, v in e.items() if k not in ("batch", "truncated_fields")} for e in ev],
                        "unknown": ev}
            for vname, events in variants.items():
                for view in ("audience", "table"):
                    decorated = viewer.log_slice(events, view, 0)["events"]
                    if vname == "unknown":                     # the page must survive oddities
                        decorated = decorated[:12] + odd + decorated[12:]
                    cases.append({"events": decorated, "view": view, "rules": viewer.rules_of(events)})
                    labels.append((label, vname, view))
        with tempfile.TemporaryDirectory() as d:
            m = CORE.search(viewer.page_html())
            core = Path(d) / "core.js"
            core.write_text(m.group(1), encoding="utf-8")
            harness = Path(d) / "harness.js"
            harness.write_text(HARNESS, encoding="utf-8")
            data = Path(d) / "cases.json"
            data.write_text(json.dumps(cases), encoding="utf-8")
            r = subprocess.run(["node", str(harness), str(core), str(data)], capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            results = json.loads(r.stdout)
        self.assertEqual(len(results), len(cases))
        for label, case, beats in zip(labels, cases, results):
            events = case["events"]
            self.assertTrue(beats, label)
            idx = [b["i"] for b in beats]
            self.assertEqual(idx, sorted(idx), label)                       # log order
            self.assertTrue(all(b["dur"] > 0 for b in beats), label)
            self.assertEqual(len({b["key"] for b in beats}), len(beats), label)
            with_beat = {b["i"] for b in beats if b["turn"]}
            for i, e in enumerate(events):
                if isinstance(e, dict) and e.get("type") == "turn" and (e.get("public") or "").strip():
                    self.assertIn(i, with_beat, (label, e.get("turn_phase"), e.get("seq")))
            if label[1] == "full":
                kinds = [b["kind"] for b in beats]
                self.assertEqual(kinds[-1], "end", label)
                self.assertIn("cast", kinds)
                if any(e.get("type") == "vote_result" for e in events):
                    self.assertIn("votes", kinds)
                    self.assertIn("out", kinds)
                if label[2] == "audience":
                    self.assertTrue(all(b["turn"] for b in beats if b["kind"] in ("say", "think", "whisper")))
                    n_turns = sum(1 for e in events if e.get("type") == "turn")
                    self.assertEqual(len(with_beat), n_turns, label)        # every turn has a beat


# --------------------------------------------------------------------------- Stage 4B: portraits, art, privacy, pace

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24          # bytes are served as they are; no decoding happens
SVG = b'<svg xmlns="http:' + b'//www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>'


def portrait_folder(d: Path) -> Path:
    pd = d / "portraits"
    pd.mkdir()
    (pd / "rook.png").write_bytes(PNG)
    (pd / "vesper.svg").write_bytes(SVG)
    (pd / "vesper.jpg").write_bytes(b"\xff\xd8 not first")    # png > webp > jpg > svg: jpg wins over svg
    (pd / "ghost.gif").write_bytes(b"GIF89a")                 # not an allowed type
    (pd / "notes.png").write_bytes(PNG)                       # not a codename
    (pd / "Fox.png").write_bytes(PNG)                         # not lower case
    (pd / "README.md").write_text("readme")
    secret = d / "secret.png"
    secret.write_bytes(b"outside")
    try:
        (pd / "duke.png").symlink_to(secret)                  # a link out of the folder is refused
    except OSError:
        pass
    return pd


class Portraits(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.pd = portrait_folder(self.dir)
        self.server, self.thread = viewer.start_in_thread(self.dir, 0, portrait_dir=self.pd)
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def request(self, path, method="GET"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request(method, path)
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, body, r.getheader("Content-Type")

    def test_serving_and_refusals(self):
        status, body, _ = self.request("/api/portraits")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["portraits"], {"Rook": "/portraits/rook.png", "Vesper": "/portraits/vesper.jpg"})
        status, body, ctype = self.request("/portraits/rook.png")
        self.assertEqual((status, body, ctype), (200, PNG, "image/png"))
        self.assertEqual(self.request("/portraits/vesper.svg")[2], "image/svg+xml")
        bad = ["/portraits/ROOK.png", "/portraits/Rook.png", "/portraits/rook.PNG", "/portraits/rook.gif", "/portraits/ghost.gif",
               "/portraits/notes.png", "/portraits/README.md", "/portraits/readme.md", "/portraits/fox.png", "/portraits/Fox.png",
               "/portraits/duke.png", "/portraits/rook", "/portraits/", "/portraits/rook.png.bak", "/portraits/rook.png%00",
               "/portraits/../viewer.py", "/portraits/..%2Fviewer.py", "/portraits/%2e%2e/secret.png", "/portraits/..%2Fsecret.png",
               "/portraits/rook.png/", "/portraits//etc/passwd", "/portraits/nobody.png", "/portraits/secret.png", "/portrait/rook.png"]
        for path in bad:
            status, body, _ = self.request(path)
            self.assertEqual(status, 404, path)
            self.assertNotIn(b"outside", body)
        self.assertEqual(self.request("/portraits/rook.png", "POST")[0], 405)
        self.assertIsNone(viewer.resolve_portrait(self.pd, "../rook.png"))
        self.assertIsNone(viewer.resolve_portrait(self.pd, "rook.png/.."))
        self.assertIsNone(viewer.portrait_file(self.pd, "../secret"))
        self.assertEqual(viewer.portraits(self.dir / "missing"), {})

    def test_export_embeds_portraits(self):
        game, _ = run_game(2, make_config(anonymise=True), log_path=self.dir / "g-pt-s2.jsonl", game_id="g-pt-s2")
        for view in ("audience", "table"):
            html = viewer.export_html(self.dir / "g-pt-s2.jsonl", view, portrait_dir=self.pd)
            Export.check_self_contained(self, html)
            data = Export.embedded(self, html)
            self.assertEqual(set(data["portraits"]), {"Rook", "Vesper"})
            self.assertTrue(data["portraits"]["Rook"].startswith("data:image/png;base64,"))
            self.assertTrue(data["portraits"]["Vesper"].startswith("data:image/jpeg;base64,"))
        html = viewer.export_html(self.dir / "g-pt-s2.jsonl", "audience", portrait_dir=self.dir / "none")
        self.assertEqual(Export.embedded(self, html)["portraits"], {})


class Art(unittest.TestCase):
    def test_no_filter_on_characters_and_csp(self):
        html = viewer.page_html()
        # the outline and rim light are drawn geometry: no SVG filter, CSS filter or backdrop-filter anywhere
        self.assertIsNone(re.search(r"<filter\b|\bfilter\s*=|(?<![-\w])filter\s*:|backdrop-filter|filter=\"url", html), "filter in the page")
        self.assertNotIn("mix-blend-mode", html)
        csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]*)"', html).group(1)
        self.assertEqual(csp, viewer.PAGE_CSP)
        self.assertIn("img-src 'self' data:", csp)
        self.assertNotIn("http", csp)

    def test_every_codename_has_a_character(self):
        html = viewer.page_html()
        block = re.search(r"const CAST = \{(.*?)\n\};", html, re.DOTALL).group(1)
        names = re.findall(r"^  (\w+):\s+\{ accent: '(#[0-9a-f]{6})'", block, re.MULTILINE)
        self.assertEqual([n for n, _ in names], list(CODENAMES))
        accents = [a for _, a in names]
        self.assertEqual(len(set(accents)), len(accents))
        def hsv(h):
            return colorsys.rgb_to_hsv(*(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)))
        for n, a in names:                                   # amber (moles, lies) and mint (clean) belong to nobody
            hue, sat, _ = hsv(a)
            for reserved in ("#ffb22e", "#43e4ad"):
                d = abs(hue - hsv(reserved)[0]) * 360
                if sat > .35:
                    self.assertGreaterEqual(min(d, 360 - d), 16, (n, a, reserved))


BEATS_HARNESS = r"""
const fs = require("fs");
const core = require(process.argv[2]);
const cases = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
process.stdout.write(JSON.stringify(cases.map(c => core.buildBeats(c.events, c.view, { rules: c.rules }))));
"""


def run_core(cases):
    with tempfile.TemporaryDirectory() as d:
        core = Path(d) / "core.js"
        core.write_text(CORE.search(viewer.page_html()).group(1), encoding="utf-8")
        (Path(d) / "h.js").write_text(BEATS_HARNESS, encoding="utf-8")
        (Path(d) / "c.json").write_text(json.dumps(cases), encoding="utf-8")
        r = subprocess.run(["node", str(Path(d) / "h.js"), str(core), str(Path(d) / "c.json")], capture_output=True, text=True, timeout=120)
        if r.returncode:
            raise AssertionError(r.stderr)
        return json.loads(r.stdout)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class Staging(unittest.TestCase):
    def test_table_view_beats_carry_no_private_field(self):
        """Every scene is built from a beat; in table view no beat holds anything private."""
        cases, games = [], []
        for seed in range(2):
            planter = Planter(seed)
            game, _ = run_game(seed, make_config(anonymise=True), policy=planter)
            ev = game.log.events
            cases.append({"events": viewer.log_slice(ev, "table", 0)["events"], "view": "table", "rules": viewer.rules_of(ev)})
            games.append((game, planter))
        for (game, planter), beats in zip(games, run_core(cases)):
            self.assertTrue(beats)
            kinds = {b["kind"] for b in beats}
            self.assertFalse(kinds & {"diary", "think", "whisper", "intel"}, kinds)
            text = json.dumps(beats)
            table_leaks(self, text, game, planter, True)
            for b in beats:
                self.assertEqual(b["w"]["moles"], [])
                self.assertEqual(b["w"]["intel"], {})
                self.assertIsNone(b["w"]["choices"])
                if b["kind"] != "finale":                    # split / steal is revealed at the table
                    self.assertIsNone(b["data"].get("choices"))
                for part in (b.get("ev") or {}, b["data"]):
                    for k in PRIVATE_KEYS:
                        self.assertNotIn(k, part, (k, b["kind"]))
                for o in b["w"]["outs"]:                    # roles appear only once revealed by a vote
                    self.assertLessEqual(o["round"], b["round"])

    def test_beat_duration_follows_reading_pace(self):
        cases = []
        for label, (cfg, script) in ending_games().items():
            game, _ = run_game(11, cfg, policy=script)
            ev = game.log.events
            for view in ("audience", "table"):
                cases.append({"events": viewer.log_slice(ev, view, 0)["events"], "view": view, "rules": viewer.rules_of(ev)})
        text_kinds = {"say", "diary", "think", "whisper", "recap", "intel", "cast", "end", "note"}
        n = 0
        for beats in run_core(cases):
            for b in beats:
                if b["kind"] in text_kinds:
                    self.assertGreater(b["words"], 0, b["kind"])
                if b["words"]:
                    self.assertGreaterEqual(b["dur"] + 1e-6, b["words"] / 3.3 + 1, (b["kind"], b["words"], b["dur"]))
                    n += 1
                if b["kind"] in ("say", "whisper", "diary", "think"):
                    e = b["ev"]
                    shown = (e.get("confessional") if b["kind"] in ("diary", "think") else e.get("public")) or ""
                    self.assertGreaterEqual(b["words"], len(shown.split()))
        self.assertGreater(n, 50)


# --------------------------------------------------------------------------- the table scene (discussion, vote, vote-out)

def table_state(events):
    """Who accuses whom and who has voted for whom after each event, rebuilt in Python from the
    public fields of the turns: [(accusing, ballots)] by event index. Both reset at a round start."""
    acc, bal, out = {}, {}, []
    for e in events:
        if isinstance(e, dict):
            if e.get("type") == "round_start":
                acc, bal = {}, {}
            elif e.get("type") == "turn" and e.get("player"):
                act = e.get("action") or {}
                if e.get("turn_phase") in ("discuss", "debate") and act.get("accuse") not in (None, "", "none"):
                    acc[e["player"]] = act["accuse"]
                if e.get("turn_phase") == "vote" and act.get("vote"):
                    bal[e["player"]] = act["vote"]
        out.append((dict(acc), dict(bal)))
    return out


SCENE_HARNESS = r"""
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const turns = /const TABLE_TURNS = (\{[^}]*\});/.exec(html)[1];
const fn = /\nfunction sceneFor\(b\) \{[\s\S]*?\n\}\n/.exec(html)[0];
const make = new Function("CLASSIC", "const TABLE_TURNS = " + turns + ";" + fn + "; return sceneFor;");
const beats = JSON.parse(process.argv[3]);
process.stdout.write(JSON.stringify([false, true].map(c => beats.map(b => make(c)(b).join(":")))));
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TableScene(unittest.TestCase):
    def games(self):
        yield "lies", run_game(2, make_config(clean_target=9, sabotage_target=9, anonymise=True), policy=lie_script())[0]
        for label, (cfg, script) in ending_games().items():
            yield label, run_game(11, cfg, policy=script)[0]

    def test_beats_carry_the_accusations_and_ballots_of_the_round(self):
        cases, labels = [], []
        for label, game in self.games():
            for view in ("audience", "table"):
                ev = viewer.log_slice(game.log.events, view, 0)["events"]
                cases.append({"events": ev, "view": view, "rules": viewer.rules_of(game.log.events)})
                labels.append((label, view))
        accusations = ballots = moved = 0
        for (label, view), case, beats in zip(labels, cases, run_core(cases)):
            events, state = case["events"], table_state(case["events"])
            seats = set(beats[0]["w"]["seats"])
            for b in beats:
                acc, bal = state[b["i"]]
                e = events[b["i"]]
                if b["kind"] == "title":                    # added before its event is applied
                    continue
                self.assertEqual(b["w"]["accusing"], acc, (label, view, b["key"]))
                self.assertEqual(b["w"]["ballots"], bal, (label, view, b["key"]))
                self.assertLessEqual(set(acc) | set(acc.values()) | set(bal) | set(bal.values()), seats, label)
                if b["kind"] == "round":
                    self.assertEqual((acc, bal), ({}, {}), label)
                if b["kind"] == "say" and e.get("turn_phase") in ("discuss", "debate"):
                    target = (e.get("action") or {}).get("accuse")
                    if target and target != "none":
                        before = state[b["i"] - 1][0].get(e["player"])
                        self.assertEqual(b["data"].get("accusePrev"), before, (label, view, b["key"]))
                        accusations += 1
                        moved += before not in (None, target)
                    else:
                        self.assertNotIn("accusePrev", b["data"])
                if b["kind"] in ("votes", "out"):           # the count shows exactly the ballots that were cast
                    self.assertEqual(b["data"]["votes"], e.get("votes") or {})
                    self.assertEqual(bal, {k: v for k, v in (e.get("votes") or {}).items() if k in bal})
                    ballots += len(bal)
        self.assertGreater(accusations, 20)
        self.assertGreater(ballots, 20)

    def test_both_views_stage_the_same_table(self):
        game = run_game(2, make_config(clean_target=9, sabotage_target=9, anonymise=True), policy=lie_script())[0]
        raw = game.log.events
        cases = [{"events": viewer.log_slice(raw, v, 0)["events"], "view": v, "rules": viewer.rules_of(raw)}
                 for v in ("audience", "table")]
        aud, tab = run_core(cases)
        by_key = {b["key"]: b for b in aud if b["kind"] in ("say", "votes", "out")}
        n = 0
        for b in tab:
            if b["kind"] in ("say", "votes", "out"):
                a = by_key[b["key"]]
                self.assertEqual((b["w"]["accusing"], b["w"]["ballots"], b["data"]),
                                 (a["w"]["accusing"], a["w"]["ballots"], a["data"]), b["key"])
                n += 1
        self.assertGreater(n, 20)

    def test_table_view_shows_no_ballot_before_the_result(self):
        game = run_game(7, make_config())[0]
        ev = game.log.events
        first_vote = next(i for i, e in enumerate(ev) if e["type"] == "turn" and e["turn_phase"] == "vote")
        result = next(i for i, e in enumerate(ev) if e["type"] == "vote_result")
        self.assertGreater(result - first_vote, 2)
        cut = ev[:result]                                   # every ballot cast, the result not yet logged
        cases = [{"events": viewer.log_slice(cut, v, 0)["events"], "view": v, "rules": viewer.rules_of(ev)}
                 for v in ("table", "audience")]
        tab, aud = run_core(cases)
        self.assertTrue(all(b["w"]["ballots"] == {} for b in tab))
        self.assertFalse(any(b["kind"] in ("votes", "out") for b in tab))
        self.assertEqual(len(aud[-1]["w"]["ballots"]), result - first_vote)   # the audience has watched them come in

    def test_discussion_and_vote_are_staged_at_the_table(self):
        beats = [{"kind": "say", "ev": {"turn_phase": tp}, "data": {}} for tp in
                 ("discuss", "vote", "debate", "final_accuse", "pick", "cut_pitch", "finale_pitch")]
        beats += [{"kind": k, "ev": None, "data": {}} for k in ("votes", "out", "cut", "round", "diary")]
        beats += [{"kind": "diary", "ev": {"turn_phase": "discuss"}, "data": {"atTable": True}},
                  {"kind": "think", "ev": {"turn_phase": "clue"}, "data": {"atTable": True}},
                  {"kind": "think", "ev": {"turn_phase": "job"}, "data": {}}]
        with tempfile.TemporaryDirectory() as d:
            h = Path(d) / "h.js"
            h.write_text(SCENE_HARNESS, encoding="utf-8")
            r = subprocess.run(["node", str(h), str(viewer.PAGE_PATH), json.dumps(beats)], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        table, classic = json.loads(r.stdout)
        self.assertEqual(table, ["council:say"] * 4 + ["speaker", "speaker", "finale:pitch", "council:votes", "council:out",
                                                      "vote:cut", "table:round", "diary", "council:think", "council:think",
                                                      "diary"])
        self.assertEqual(classic, ["speaker"] * 6 + ["finale:pitch", "vote:votes", "vote:out", "vote:cut", "table:round", "diary",
                                                     "diary", "diary", "diary"])
        html = viewer.page_html()
        self.assertIn("SCENES.council = ", html)
        self.assertIn("function emptyChair(", html)
        # the scene asks for a model or a role only through the audience-only helpers
        scene = html[html.index("function councilStage("):html.index("/* ---------------------------------------------------------------- FINALE")]
        calls = list(re.finditer(r"(?:modelOf|roleOf)\(", scene))
        self.assertGreaterEqual(len(calls), 5)
        for m in calls:                                     # `aud ? modelOf(..)`, `aud && roleOf(..)`, `aud ? roleChip(roleOf(..`
            self.assertRegex(scene[max(0, m.start() - 24):m.start()], r"\baud (\?|&&) (roleChip\()?$", scene[m.start() - 60:m.end() + 20])


# --------------------------------------------------------------------------- thoughts at the table, private-suspicion meters

OPTS_HARNESS = r"""
const fs = require("fs");
const core = require(process.argv[2]);
const job = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
process.stdout.write(JSON.stringify({
  beats: job.cases.map(c => core.buildBeats(c.events, c.view, Object.assign({ rules: c.rules }, c.opts || {}))),
  excerpts: job.texts.map(t => core.thoughtExcerpt(t)),
  limit: core.THOUGHT_WORDS,
}));
"""

LONG_THOUGHT = ("Fox pushed the vote early, which is odd for someone with no intel. I helped on the job and said so. "
                "If the card Duke tabled is real then one of three is a mole; if it is invented, Duke is. "
                "I will press Duke first and watch who defends him, then decide.")


def run_core_opts(cases, texts=()):
    with tempfile.TemporaryDirectory() as d:
        core = Path(d) / "core.js"
        core.write_text(CORE.search(viewer.page_html()).group(1), encoding="utf-8")
        (Path(d) / "h.js").write_text(OPTS_HARNESS, encoding="utf-8")
        (Path(d) / "c.json").write_text(json.dumps({"cases": cases, "texts": list(texts)}), encoding="utf-8")
        r = subprocess.run(["node", str(Path(d) / "h.js"), str(core), str(Path(d) / "c.json")], capture_output=True, text=True, timeout=120)
        if r.returncode:
            raise AssertionError(r.stderr)
        return json.loads(r.stdout)


def belief_state(events):
    """Each player's latest private suspicion numbers after each event, rebuilt in Python: [{player: {kind, s}}]."""
    cur, out = {}, []
    for e in events:
        if isinstance(e, dict) and e.get("type") == "turn" and e.get("player"):
            s = (e.get("action") or {}).get("suspicion")
            if isinstance(s, dict) and s:
                cur[e["player"]] = {"kind": e.get("suspicion_kind") or "belief", "s": s}
        out.append(dict(cur))
    return out


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class ThoughtsAndMeters(unittest.TestCase):
    def game_events(self):
        """A mock game with lies, where every other thought is long enough to be shortened."""
        game = run_game(2, make_config(clean_target=9, sabotage_target=9, anonymise=True), policy=lie_script())[0]
        raw = [dict(e) for e in game.log.events]
        k = 0
        for e in raw:
            if e["type"] == "turn":
                k += 1
                if k % 2:
                    e["confessional"] = LONG_THOUGHT
        return raw

    def test_the_opening_of_a_thought_is_a_word_for_word_prefix(self):
        texts = ["", "Short and whole.", LONG_THOUGHT, "Opus 5.5 said no. " * 12, " ".join(["word"] * 80),
                 "One very long opening sentence " + " ".join(["and more"] * 30) + ". Then a second one.",
                 'She said "no." Then left! Why? ' + " ".join(["because"] * 40) + "."]
        res = run_core_opts([], texts)
        limit = res["limit"]
        for text, ex in zip(texts, res["excerpts"]):
            self.assertTrue(text.strip().startswith(ex["text"]), (text[:40], ex))
            self.assertEqual(ex["cut"], len(ex["text"].split()) < len(text.split()))
            self.assertLessEqual(len(ex["text"].split()), limit + 8)
            if len(text.split()) <= limit:
                self.assertEqual((ex["text"], ex["cut"]), (text.strip(), False))
            else:
                self.assertTrue(ex["cut"] and ex["text"], ex)
        self.assertEqual(res["excerpts"][2]["text"], "Fox pushed the vote early, which is odd for someone with no intel. "
                                                     "I helped on the job and said so.")
        self.assertEqual(len(res["excerpts"][4]["text"].split()), limit)          # no sentence end: cut at the limit

    def test_short_thoughts_play_at_the_table_and_lies_keep_the_diary_room(self):
        raw = self.game_events()
        aud = viewer.log_slice(raw, "audience", 0)["events"]
        rules = viewer.rules_of(raw)
        # a whisper that carries a lie (the mock game has none): its thought must stay whole
        lying_whisper = next(e for e in aud if e["type"] == "turn" and e["turn_phase"] == "whisper"
                             and e["confessional"] == LONG_THOUGHT)
        lying_whisper["_marks"] = [["lie", "made up for the test"]]
        full, short, tab = run_core_opts([{"events": aud, "view": "audience", "rules": rules},
                                          {"events": aud, "view": "audience", "rules": rules, "opts": {"thoughts": "short"}},
                                          {"events": viewer.log_slice(raw, "table", 0)["events"], "view": "table", "rules": rules,
                                           "opts": {"thoughts": "short"}}])["beats"]
        self.assertEqual([b["key"] for b in full], [b["key"] for b in short])      # same beats, same order
        self.assertFalse(any("thought" in b["data"] or "atTable" in b["data"] for b in full))    # the default is unchanged
        lie_kinds = {"lie", "card_fake", "job_false"}
        table_turns = ("discuss", "vote", "debate", "final_accuse")
        seen = {"table": 0, "intel": 0, "whisper": 0, "lie": 0, "cut": 0, "other": 0}
        for f, b in zip(full, short):
            e = b["ev"] or {}
            tp = e.get("turn_phase")
            d = b["data"]
            if b["kind"] == "diary" and tp in table_turns:
                where = "table"                             # after a statement: at the speaker's seat
            elif b["kind"] == "think" and tp == "clue":
                where = "intel"                             # the intel phase: at the player's seat
            elif b["kind"] == "diary" and tp == "whisper":
                where = "whisper"                           # after a whisper: short, in the diary room
            else:
                self.assertNotIn("atTable", d, b["key"])
                self.assertNotIn("thought", d, b["key"])
                self.assertEqual(b["dur"], f["dur"], b["key"])
                seen["other"] += b["kind"] in ("diary", "think")
                continue
            conf = e["confessional"].strip()
            if lie_kinds & {m[0] for m in e["_marks"]}:
                self.assertNotIn("atTable", d, b["key"])    # a lie keeps its full cut-away
                self.assertNotIn("thought", d, b["key"])
                self.assertEqual(b["dur"], f["dur"])
                seen["lie"] += 1
                continue
            seen[where] += 1
            self.assertEqual(bool(d.get("atTable")), where != "whisper", b["key"])
            self.assertTrue(conf.startswith(d["thought"]) and d["thought"], d)
            self.assertEqual(d["thoughtCut"], d["thought"] != conf)
            self.assertGreaterEqual(b["words"], len(d["thought"].split()))
            self.assertGreaterEqual(b["dur"] + 1e-6, b["words"] / 3.3 + 1)
            self.assertLessEqual(b["dur"], f["dur"] + 0.6)
            if d["thoughtCut"]:
                self.assertLess(b["dur"], f["dur"])
                seen["cut"] += 1
        self.assertGreater(seen["table"], 10)
        self.assertGreater(seen["intel"], 5)
        self.assertGreater(seen["whisper"], 5)
        self.assertGreater(seen["lie"], 4)
        self.assertGreater(seen["cut"], 15)
        self.assertGreater(seen["other"], 0)                # the job, the pick and the like keep their full thoughts
        self.assertEqual(next(b for b in short if b["kind"] == "diary" and b["ev"]["seq"] == lying_whisper["seq"])["data"]
                         .get("thought"), None)
        self.assertLess(sum(b["dur"] for b in short), sum(b["dur"] for b in full))
        # the table view has no thoughts and no private numbers: the server sends none, and the page would not
        # use them even if it were handed the audience's events
        leaked = run_core_opts([{"events": aud, "view": "table", "rules": rules, "opts": {"thoughts": "short"}}])["beats"][0]
        for b in tab + leaked:
            self.assertNotIn(b["kind"], ("diary", "think"))
            for k in ("atTable", "thought", "thoughtCut", "beliefPrev"):
                self.assertNotIn(k, b["data"], (k, b["key"]))
            self.assertEqual(b["w"]["beliefs"], {})

    def test_beats_carry_each_players_latest_private_numbers(self):
        raw = self.game_events()
        aud = viewer.log_slice(raw, "audience", 0)["events"]
        state = belief_state(aud)
        beats = run_core_opts([{"events": aud, "view": "audience", "rules": viewer.rules_of(raw), "opts": {"thoughts": "short"}}])["beats"][0]
        kinds = set()
        moved = 0
        for b in beats:
            e = aud[b["i"]]
            mine = isinstance(e, dict) and e.get("type") == "turn" and (e.get("action") or {}).get("suspicion")
            if b["kind"] == "title":
                continue
            if b["kind"] == "say":                          # the table before the speaker's new numbers
                self.assertEqual(b["w"]["beliefs"], state[b["i"] - 1], b["key"])
                self.assertNotIn("beliefPrev", b["data"])
            else:
                self.assertEqual(b["w"]["beliefs"], state[b["i"]], b["key"])
                if mine and b["kind"] in ("diary", "think"):
                    self.assertEqual(b["data"]["beliefPrev"], state[b["i"] - 1].get(e["player"]), b["key"])
                    moved += b["data"]["beliefPrev"] not in (None, state[b["i"]][e["player"]])
            kinds |= {v["kind"] for v in b["w"]["beliefs"].values()}
        self.assertEqual(kinds, {"belief", "table_read"})   # crew give a belief, moles a read of the table
        self.assertGreater(moved, 10)
        roles = {p["name"]: p["role"] for p in raw[0]["players"]}
        last = beats[-1]["w"]["beliefs"]
        self.assertTrue(last)
        for name, v in last.items():
            self.assertEqual(v["kind"], "table_read" if roles[name] == "mole" else "belief")

    def test_the_meter_averages_crew_beliefs_only(self):
        html = viewer.page_html()
        fn = re.search(r"\nfunction crewSuspicion\(beliefs, out\) \{.*?\n\}\n", html, re.DOTALL).group(0)
        beliefs = {"A": {"kind": "belief", "s": {"B": 20, "C": 80, "M": 60}},
                   "B": {"kind": "belief", "s": {"A": 10, "C": 40, "M": 90}},
                   "C": {"kind": "belief", "s": {"A": 30, "B": 0, "M": 100}},        # C is voted out below
                   "M": {"kind": "table_read", "s": {"A": 99, "B": 99, "C": 99}}}    # a mole's guess: never counted
        js = ("const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));" + fn +
              "process.stdout.write(JSON.stringify([crewSuspicion(B, {}), crewSuspicion(B, {C: 'crew'}), crewSuspicion({}, {})]));")
        r = subprocess.run(["node", "-e", "const B = " + json.dumps(beliefs) + ";" + js], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        everyone, without_c, empty = json.loads(r.stdout)
        self.assertEqual(everyone, {"B": 10, "C": 60, "M": 250 / 3, "A": 20})
        self.assertEqual(without_c, {"B": 20, "C": 60, "M": 75, "A": 10})
        self.assertEqual(empty, {})
        # the bars exist only where the scene was given beliefs, and the scene asks for them in the audience view only
        self.assertIn("const meters = aud && METERS && Object.keys(w.beliefs || {}).length > 0;", html)


if __name__ == "__main__":
    unittest.main()
