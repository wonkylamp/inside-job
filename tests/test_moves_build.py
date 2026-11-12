"""The one-move test (docs/MOVES.md): 4 flags and kinds on hand-made logs, 5 selection, halves,
manifests, overwrite refusal and verify. Temporary folders only; no model calls."""

import contextlib
import io
import json
import random
import tempfile
import unittest
from pathlib import Path

from inside_job import moves as M
from inside_job.__main__ import main

try:
    from test_moves import CONFIGS
except ImportError:                                     # run as `python3.11 -m unittest tests.test_moves_build`
    from tests.test_moves import CONFIGS

PLAYERS = [("A", "mole", "claude-x"), ("B", "mole", "claude-x"), ("C", "crew", "claude-y"),
           ("D", "crew", "claude-y"), ("E", "crew", "claude-y"), ("F", "crew", "claude-y"), ("G", "crew", "claude-y")]


class Log:
    """A hand-made log: only the events the flag and kind rules read."""

    def __init__(self, seed=7):
        self.ev = []
        self.add("game_start", 0, "setup", seed=seed, game_id="hand",
                 players=[{"name": n, "role": r, "model": mdl, "seat": i} for i, (n, r, mdl) in enumerate(PLAYERS)])

    def add(self, type, round, phase, **kw):
        e = {"seq": len(self.ev), "ts": "", "game_id": "hand", "round": round, "phase": phase, "type": type,
             "vis": "public"}
        e.update(kw)
        self.ev.append(e)
        return e

    def turn(self, tp, player, round, **kw):
        act = kw.pop("action", {})
        return self.add("turn", round, "discuss" if tp == "discuss" else tp, turn_phase=tp, player=player,
                        action=act, **kw)


def hand_log(whisper_card_b=False, pairs=(("A", "C"), ("B", "D"))):
    L = Log()
    L.add("round_start", 1, "clue", alive=[p[0] for p in PLAYERS], leader="G", clean_jobs=0, blown_jobs=0)
    L.add("whisper_pairs", 1, "whisper", pairs=[list(p) for p in pairs])
    for step in range(4):
        for a, b in pairs:
            sp, pt = (a, b) if step % 2 == 0 else (b, a)
            cards = [{"kind": "not_mole", "players": ["E"], "k": 0}] if whisper_card_b and sp == "B" and step == 0 else []
            L.turn("whisper", sp, 1, partner=pt, action={"clue_cards": cards})
    L.add("job_pick", 1, "pick", leader="G", team=["A", "C", "E"], job_name="x")
    L.add("job_result", 1, "job", team=["A", "C", "E"], sabotages=1, blown=True, clean_jobs=0, blown_jobs=1)
    L.turn("discuss", "C", 1, **{"pass": 1}, action={"accuse": "A", "clue_cards": [], "job_claim": "helped"})
    a1 = L.turn("discuss", "A", 1, **{"pass": 1}, action={"accuse": "none", "clue_cards": [], "job_claim": "helped"})
    b1 = L.turn("discuss", "B", 1, **{"pass": 1}, action={"accuse": "none", "clue_cards": [], "job_claim": "none"})
    fb = L.turn("discuss", "B", 1, **{"pass": 2}, fallback=True, action={"accuse": "none"})
    a2 = L.turn("discuss", "A", 1, **{"pass": 2}, action={"accuse": "none", "clue_cards": [], "job_claim": "none"})
    L.add("vote_result", 1, "vote", eliminated="B", role="mole", votes={})
    L.add("round_start", 2, "clue", alive=["A", "C", "D", "E", "F", "G"], leader="A", clean_jobs=0, blown_jobs=1)
    L.add("job_pick", 2, "pick", leader="A", team=["C", "D", "F"], job_name="y")
    L.add("job_result", 2, "job", team=["C", "D", "F"], sabotages=0, blown=False, clean_jobs=1, blown_jobs=1)
    a3 = L.turn("discuss", "A", 2, **{"pass": 1}, action={"accuse": "none", "clue_cards": [], "job_claim": "none"})
    return L.ev, {"a1": a1, "b1": b1, "fb": fb, "a2": a2, "a3": a3}


def src_of(ev):
    return {"path": "hand", "sha256": "-", "batch": "hand", "seed": 7, "game_id": "hand", "events": ev}


# --------------------------------------------------------------------------- 4

class Flags(unittest.TestCase):
    def setUp(self):
        self.ev, self.t = hand_log()
        self.cands = {c["turn"]["seq"]: c for c in M.scan(src_of(self.ev))}

    def flags(self, key):
        t = self.t[key]
        return M.moment_flags(self.ev, t, t["seq"] - 1)

    def test_accused_on_job_blown(self):
        f = self.flags("a1")
        self.assertTrue(f["accused"])                  # C accused A earlier this round
        self.assertTrue(f["on_job"])
        self.assertTrue(f["blown_this_round"])
        self.assertEqual((f["clean_jobs"], f["blown_jobs"]), (0, 1))
        self.assertTrue(f["no_claim_yet"])
        self.assertTrue(f["partner_alive"])
        self.assertEqual((f["round"], f["round_bucket"], f["pass"], f["origin"], f["seed"]), (1, "1", 1, "claude-x", 7))
        g = self.flags("b1")
        self.assertFalse(g["accused"])
        self.assertFalse(g["on_job"])
        self.assertTrue(g["blown_this_round"])

    def test_no_claim_yet_and_partner(self):
        self.assertFalse(self.flags("a2")["no_claim_yet"])   # A said "helped" in pass 1
        f = self.flags("a3")
        self.assertFalse(f["partner_alive"])                 # B voted out in round 1
        self.assertEqual(f["round_bucket"], "2")
        self.assertFalse(f["accused"])                       # accusations are per round
        self.assertFalse(f["on_job"])
        self.assertFalse(f["blown_this_round"])
        self.assertEqual((f["clean_jobs"], f["blown_jobs"]), (1, 1))

    def test_kinds(self):
        c = self.cands
        self.assertEqual(c[self.t["a1"]["seq"]]["kind"], "open_claim")
        self.assertEqual(c[self.t["b1"]["seq"]]["kind"], "open_claim")
        self.assertEqual(c[self.t["a2"]["seq"]]["kind"], "discuss")
        self.assertEqual(c[self.t["a3"]["seq"]]["kind"], "discuss")
        self.assertNotIn(self.t["fb"]["seq"], c)             # fallback turns are not moments
        ws = [x for x in c.values() if x["kind"] == "open_whisper"]
        self.assertEqual(sorted((x["turn"]["player"], x["turn"]["partner"]) for x in ws), [("A", "C"), ("B", "D")])
        for x in ws:                                         # the mole's first message only
            first = next(e for e in self.ev if e.get("turn_phase") == "whisper" and e["player"] == x["turn"]["player"])
            self.assertEqual(x["turn"]["seq"], first["seq"])
        # B opened pair B-D and speaks second within step 0: its cutoff is the step's first seq - 1
        b = next(x for x in ws if x["turn"]["player"] == "B")
        self.assertEqual(b["cutoff"], next(e["seq"] for e in self.ev if e.get("turn_phase") == "whisper") - 1)
        self.assertEqual(self.cands[self.t["a1"]["seq"]]["cell"], ["claude-x", "open_claim", "1", True, True, True])

    def test_earlier_whisper_card_rules_out_open_claim(self):
        ev, t = hand_log(whisper_card_b=True)
        c = {x["turn"]["seq"]: x for x in M.scan(src_of(ev))}
        self.assertEqual(c[t["b1"]["seq"]]["kind"], "discuss")
        self.assertFalse(c[t["b1"]["seq"]]["flags"]["no_claim_yet"])
        self.assertEqual(c[t["a1"]["seq"]]["kind"], "open_claim")

    def test_open_whisper_needs_a_crew_partner(self):
        ev, _ = hand_log(pairs=(("A", "B"), ("C", "D")))
        self.assertFalse([x for x in M.scan(src_of(ev)) if x["kind"] == "open_whisper"])
        ev, _ = hand_log(pairs=(("C", "A"), ("B", "D")))
        ws = {x["turn"]["player"]: x for x in M.scan(src_of(ev)) if x["kind"] == "open_whisper"}
        self.assertEqual(set(ws), {"A", "B"})
        a = ws["A"]                                          # A answers C: its first message is at step 1
        steps = [e for e in ev if e.get("turn_phase") == "whisper"]
        self.assertEqual(a["turn"]["seq"], steps[2]["seq"])
        self.assertEqual(a["cutoff"], steps[2]["seq"] - 1)


# --------------------------------------------------------------------------- 5 (selection, pure)

def fake_cands(n_games=6, seed=0):
    rng = random.Random(seed)
    out = []
    for g in range(n_games):
        for k in range(14):
            rnd = 1 + k // 5
            kind = rng.choice(["discuss", "discuss", "open_claim", "open_whisper"])
            flags = {"game_id": f"g{g}", "round": rnd, "seed": 100 + g, "origin": f"m{g % 3}",
                     "round_bucket": str(min(rnd, 3)) if rnd < 3 else "3+", "blown_this_round": rng.random() < .4,
                     "on_job": rng.random() < .4, "accused": rng.random() < .3}
            out.append({"turn": {"seq": 10 * k, "player": f"P{k}"}, "flags": flags, "kind": kind,
                        "cell": M.cell_of(kind, flags)})
    return out


class SelectionRule(unittest.TestCase):
    def test_deterministic_and_capped(self):
        c = fake_cands()
        a = M.select(c, 20, 5)
        b = M.select(list(reversed(c)), 20, 5)
        key = lambda x: (x["flags"]["game_id"], x["turn"]["seq"])   # noqa: E731
        self.assertEqual([key(x) for x in a], [key(x) for x in b])
        self.assertNotEqual([key(x) for x in a], [key(x) for x in M.select(c, 20, 6)])
        self.assertEqual(len(a), 20)
        per = {}
        for x in a:
            per[x["flags"]["game_id"]] = per.get(x["flags"]["game_id"], 0) + 1
        self.assertLessEqual(max(per.values()), 4)
        grm = [(x["flags"]["game_id"], x["flags"]["round"], x["turn"]["player"]) for x in a]
        self.assertEqual(len(grm), len(set(grm)))

    def test_round_robin_by_origin_then_cells(self):
        c = fake_cands(n_games=40, seed=3)
        sizes: dict = {}
        for x in c:
            o = x["flags"]["origin"]
            sizes.setdefault(o, {})
            sizes[o][M.cell_key(x["cell"])] = sizes[o].get(M.cell_key(x["cell"]), 0) + 1
        a = M.select(c, 60, 1, max_per_game=99)
        # the outer wheel is over origins: after every full turn the origins are level
        org = [x["flags"]["origin"] for x in a]
        for i in range(0, 60, 3):
            self.assertEqual(sorted(org[i:i + 3]), sorted(sizes))
        # within an origin, its cells are visited in turn: its first n_cells picks are distinct cells
        for o, cells in sizes.items():
            picks = [M.cell_key(x["cell"]) for x in a if x["flags"]["origin"] == o]
            first = picks[:len(cells)]
            self.assertEqual(len(first), len(set(first)))
        # an origin with more cells gains nothing: give one origin twice the cells, still level
        c2 = [dict(x, cell=x["cell"][:1] + [x["cell"][1] + "-x"] + x["cell"][2:]) if x["flags"]["origin"] == "m0"
              and x["turn"]["seq"] % 20 == 0 else x for x in c]
        b = M.select(c2, 60, 1, max_per_game=99)
        counts = {o: sum(1 for x in b if x["flags"]["origin"] == o) for o in sizes}
        self.assertEqual(set(counts.values()), {20})


    def test_runs_out_cleanly(self):
        c = fake_cands(n_games=2)
        a = M.select(c, 1000, 1)
        self.assertEqual(len(a), 8)                     # 2 games x at most 4


# --------------------------------------------------------------------------- 5 (freeze, on mock batches)

def quiet(fn, *a):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn(*a)


class Freeze(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.d = Path(cls.tmp.name)
        cls.games = cls.d / "games"
        for cfg, name in zip(CONFIGS, ("mh", "mo")):
            code = quiet(main, ["batch", "--config", str(cfg), "--name", name, "--games", "4", "--seed", "9001",
                                "--mock", "--out", str(cls.games)])
            assert code == 0, code

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def build(self, out, name="t", target=6, seed=11):
        return quiet(main, ["moves", "build", "--games", str(self.games), "--batch", "mh", "--batch", "mo",
                            "--target", str(target), "--seed", str(seed), "--name", name, "--out", str(out)])

    def test_halves_manifest_and_determinism(self):
        a, b = self.d / "fa", self.d / "fb"
        self.assertEqual(self.build(a), 0)
        self.assertEqual(self.build(b), 0)
        for h in M.HALVES:
            fa, fb = a / f"t_{h}.jsonl", b / f"t_{h}.jsonl"
            self.assertEqual(fa.read_bytes(), fb.read_bytes())
            man = json.loads(M.manifest_path(fa).read_text())
            self.assertEqual(man["sha256"], M.PR.sha256_file(fa))
            ms = M.load_set(fa)
            self.assertEqual(man["count"], len(ms))
            self.assertEqual(sum(man["cells_selected"].values()), len(ms))
            self.assertEqual(set(man["code_sha256"]), set(M.HASHED_SOURCES))
            for n in ("prompts.py", "schemas.py", "config.py", "probes.py", "moves.py"):
                self.assertIn(n, man["code_sha256"])
            for m in ms:
                self.assertEqual(m["flags"]["seed"] % 2, 1 if h == "public" else 0)
                src = man["sources"][m["source"]["path"]]
                self.assertEqual(src["sha256"], m["source"]["sha256"])
                self.assertEqual(M.sha256_bytes(Path(m["source"]["path"]).read_bytes()), src["sha256"])
                self.assertEqual([s["slot"] for s in m["slots"]], list(M.SLOTS))
                self.assertEqual(len({s["panel_model"] for s in m["slots"]}), 4)
            pm = {}
            for m in ms:
                for s in m["slots"]:
                    pm[s["panel_model"]] = pm.get(s["panel_model"], 0) + 1
            self.assertLessEqual(max(pm.values()) - min(pm.values()), 1)
            self.assertEqual(set(pm), set(M.PANEL_V1))
        pub = {m["source"]["game_id"] for m in M.load_set(a / "t_public.jsonl")}
        priv = {m["source"]["game_id"] for m in M.load_set(a / "t_private.jsonl")}
        self.assertFalse(pub & priv)
        self.assertTrue(pub and priv)

    def test_target_default_and_cap(self):
        for name, extra in (("dflt", []), ("big", ["--target", "999"])):
            out = self.d / f"ft-{name}"
            self.assertEqual(quiet(main, ["moves", "build", "--games", str(self.games), "--batch", "mh", "--batch",
                                          "mo", "--name", "t", "--out", str(out)] + extra), 0)
            for h in M.HALVES:
                man = json.loads(M.manifest_path(out / f"t_{h}.jsonl").read_text())
                n_games = len(man["sources"])
                self.assertEqual(man["target_used"], 4 * n_games)
                self.assertIn("4 per game", man["target_note"])
                self.assertLessEqual(man["count"], 4 * n_games)
                ms = M.load_set(out / f"t_{h}.jsonl")
                org = {}
                for m in ms:
                    org[m["flags"]["origin"]] = org.get(m["flags"]["origin"], 0) + 1
                self.assertLessEqual(max(org.values()) - min(org.values()), 4)
                self.assertEqual(man["no_instructed"][M.NO_PAIR_CONSISTENT] + man["no_instructed"][M.NO_PAIR_CREW],
                                 sum(1 for m in ms if not m["forged"]))

    def test_refuses_overwrite(self):
        out = self.d / "fo"
        self.assertEqual(self.build(out), 0)
        before = (out / "t_public.jsonl").read_bytes()
        self.assertEqual(self.build(out, target=2), 2)
        self.assertEqual((out / "t_public.jsonl").read_bytes(), before)
        with self.assertRaises(FileExistsError):
            M.build_sets([], name="t", out_root=out, target=1)
        # one half present is enough to refuse both
        (out / "t_private.jsonl").unlink()
        M.manifest_path(out / "t_private.jsonl").unlink()
        self.assertEqual(self.build(out), 2)
        self.assertFalse((out / "t_private.jsonl").exists())

    def test_verify_catches_changes(self):
        import shutil
        games2 = self.d / "games2"
        shutil.copytree(self.games, games2)
        out = self.d / "fv"
        self.assertEqual(quiet(main, ["moves", "build", "--games", str(games2), "--batch", "mh", "--batch", "mo",
                                      "--target", "5", "--name", "v", "--out", str(out)]), 0)
        s = out / "v_public.jsonl"
        notes: list = []
        self.assertEqual(M.verify_set(s, raw=True, notes=notes), [])
        self.assertEqual(notes, [])                     # every mock game has its raw sidecar; all compared
        self.assertEqual(quiet(main, ["moves", "verify", "--set", str(s), "--raw"]), 0)
        # a changed set file (one character of one prompt, manifest copied over)
        bad = out / "bad_public.jsonl"
        lines = s.read_text(encoding="utf-8").splitlines()
        m = json.loads(lines[0])
        m["conditions"]["free"]["prompt"] = "X" + m["conditions"]["free"]["prompt"][1:]
        bad.write_text("\n".join([M.moment_line(m)] + lines[1:]) + "\n", encoding="utf-8")
        M.manifest_path(bad).write_text(M.manifest_path(s).read_text(encoding="utf-8"), encoding="utf-8")
        self.assertTrue(M.verify_set(bad))
        self.assertEqual(quiet(main, ["moves", "verify", "--set", str(bad)]), 1)
        self.assertEqual(quiet(main, ["moves", "before", "--set", str(bad), "--mock", "--runs", str(self.d / "r")]), 1)
        self.assertFalse((self.d / "r").exists())
        # a set file edited consistently (ids and manifest recomputed) still fails the rebuild
        m2 = json.loads(lines[0])
        m2["conditions"]["free"]["prompt"] += " "
        m2["conditions"]["free"]["id"] = m2["id"] = M.PR.probe_id(m2["system"], m2["conditions"]["free"]["prompt"],
                                                                  m2["schema"])
        bad2 = out / "bad2_public.jsonl"
        bad2.write_text("\n".join([M.moment_line(m2)] + lines[1:]) + "\n", encoding="utf-8")
        man = json.loads(M.manifest_path(s).read_text())
        man["sha256"] = M.PR.sha256_file(bad2)
        M.manifest_path(bad2).write_text(json.dumps(man))
        self.assertEqual(M.quick_verify(bad2), [])
        self.assertTrue(any("does not rebuild" in b for b in M.verify_set(bad2)))
        # a changed source log
        M._EVENTS_CACHE.clear()
        src = Path(m["source"]["path"])
        src.write_bytes(src.read_bytes() + b"\n")
        probs = M.verify_set(s)
        self.assertTrue(any("has changed" in p for p in probs), probs)
        self.assertEqual(quiet(main, ["moves", "verify", "--set", str(s)]), 1)


if __name__ == "__main__":
    unittest.main()
