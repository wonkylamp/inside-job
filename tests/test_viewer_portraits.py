"""Per-game portrait overrides: `portraits/<game_id>/<codename>.<ext>` beats the global image for that
codename in that game only. Every image here is a tiny file written into a temp directory."""

import base64
import http.client
import json
import re
import tempfile
import unittest
from pathlib import Path

from inside_job import viewer

import test_viewer as tv            # module import only, so its test classes are not collected twice
from helpers import make_config, run_game

GAME = "g-pg-s2"                    # has its own folder
OTHER = "g-other-s9"                # has none

G_ROOK = b"\x89PNG\r\n\x1a\n global rook"
G_VESPER = b"\x89PNG\r\n\x1a\n global vesper"
P_ROOK = b'<svg xmlns="http:' + b'//www.w3.org/2000/svg" viewBox="0 0 10 10"><circle r="4"/></svg>'
P_LARK = b"\xff\xd8 per-game lark"
OUTSIDE = b"outside the folder"


def build(d: Path) -> Path:
    pd = d / "portraits"
    pd.mkdir()
    (pd / "rook.png").write_bytes(G_ROOK)                    # global Rook: overridden in GAME
    (pd / "vesper.png").write_bytes(G_VESPER)                # global Vesper: GAME falls back to it
    (d / "secret.png").write_bytes(OUTSIDE)

    g = pd / GAME
    g.mkdir()
    (g / "rook.svg").write_bytes(P_ROOK)                     # per-game svg beats global png
    (g / "lark.jpg").write_bytes(P_LARK)                     # per-game only
    (g / "wren.gif").write_bytes(b"GIF89a")                  # unlisted extension
    (g / "notes.png").write_bytes(b"not a codename")
    (g / "Moth.png").write_bytes(b"wrong case")
    (g / "README.md").write_text("readme")
    with open(g / "ember.png", "wb") as f:                   # oversize (sparse, so cheap)
        f.truncate(viewer.PORTRAIT_MAX + 1)
    (g / "sub").mkdir()
    (g / "sub" / "fox.png").write_bytes(b"nested")
    try:
        (g / "duke.png").symlink_to(d / "secret.png")        # a linked file is refused
    except OSError:
        pass

    elsewhere = d / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "rook.png").write_bytes(OUTSIDE)
    try:
        (pd / "g-link-s3").symlink_to(elsewhere, target_is_directory=True)   # a linked folder is refused
    except OSError:
        pass
    (pd / "g-Case-s4").mkdir()                               # only `g-Case-s4` exactly, never `g-case-s4`
    (pd / "g-Case-s4" / "rook.png").write_bytes(b"case folder")
    (pd / "g-file-s5").write_bytes(b"a file, not a folder")
    (pd / "stash").mkdir()                                   # a real folder whose name is not a game id
    (pd / "stash" / "rook.png").write_bytes(b"case folder")
    return pd


def data_uri(mime: str, raw: bytes) -> str:
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


class PerGamePortraits(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.pd = build(self.dir)
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

    def listing(self, query=""):
        status, body, _ = self.request("/api/portraits" + query)
        self.assertEqual(status, 200, query)
        return json.loads(body)["portraits"]

    # ------------------------------------------------------------------ precedence

    def test_precedence_per_game_then_global_then_drawn(self):
        got = {n: (p.parent.name, p.name) for n, (p, _) in viewer.portraits_for(self.pd, GAME).items()}
        self.assertEqual(got, {"Rook": (GAME, "rook.svg"),              # per-game wins, whatever the format
                               "Lark": (GAME, "lark.jpg"),              # per-game only
                               "Vesper": ("portraits", "vesper.png")})  # no per-game image: global
        self.assertNotIn("Wren", got)                                   # neither: drawn portrait
        self.assertEqual(set(viewer.game_portraits(self.pd, GAME)), {"Rook", "Lark"})

    def test_other_games_are_unaffected(self):
        global_set = viewer.portraits(self.pd)
        self.assertEqual(set(global_set), {"Rook", "Vesper"})
        for gid in (OTHER, "g-link-s3", "g-case-s4", "g-file-s5"):
            self.assertEqual(viewer.portraits_for(self.pd, gid), global_set, gid)
        self.assertEqual(viewer.portraits_for(self.pd, None), global_set)

    # ------------------------------------------------------------------ listing and serving

    def test_listing(self):
        glob = {"Rook": "/portraits/rook.png", "Vesper": "/portraits/vesper.png"}
        self.assertEqual(self.listing(), glob)                          # unchanged without ?game
        self.assertEqual(self.listing(f"?game={GAME}"),
                         {"Rook": f"/portraits/{GAME}/rook.svg", "Lark": f"/portraits/{GAME}/lark.jpg",
                          "Vesper": "/portraits/vesper.png"})
        for gid in (OTHER, "g-link-s3", "g-case-s4", "g-file-s5"):
            self.assertEqual(self.listing(f"?game={gid}"), glob, gid)
        self.assertEqual(self.listing("?game="), glob)                  # a blank value is no game
        self.assertEqual(self.listing("?game=g-Case-s4"),
                         {"Rook": "/portraits/g-Case-s4/rook.png", "Vesper": "/portraits/vesper.png"})

    def test_bad_game_ids_in_listing(self):
        bad = ["?game=..", "?game=../portraits", "?game=g-..", "?game=G-pg-s2", "?game=g-pg-s2/..", "?game=g-pg-s2%2F..",
               "?game=g-pg-s2%2Fsub", "?game=%2e%2e", "?game=g-pg-s2%00", "?game=g-pg-s2%0A", "?game=g-pg.s2",
               "?game=pg-s2", "?game=stash", "?game=g-", f"?game={GAME}&game={OTHER}", "?game=g-pg-s2%20"]
        for q in bad:
            status, body, _ = self.request("/api/portraits" + q)
            self.assertEqual(status, 404, q)
            self.assertNotIn(b"portraits/", body, q)

    def test_serving(self):
        self.assertEqual(self.request(f"/portraits/{GAME}/rook.svg"), (200, P_ROOK, "image/svg+xml"))
        self.assertEqual(self.request(f"/portraits/{GAME}/lark.jpg"), (200, P_LARK, "image/jpeg"))
        self.assertEqual(self.request("/portraits/rook.png"), (200, G_ROOK, "image/png"))      # global still served
        self.assertEqual(self.request("/portraits/g-Case-s4/rook.png")[0], 200)
        self.assertEqual(self.request(f"/portraits/{GAME}/rook.svg", "POST")[0], 405)

    def test_serving_refusals(self):
        bad = [
            # names: wrong case, not a codename, unlisted type, oversize, symlink, README, nested, missing
            f"/portraits/{GAME}/Moth.png", f"/portraits/{GAME}/moth.png", f"/portraits/{GAME}/ROOK.svg",
            f"/portraits/{GAME}/Rook.svg", f"/portraits/{GAME}/rook.SVG", f"/portraits/{GAME}/notes.png",
            f"/portraits/{GAME}/wren.gif", f"/portraits/{GAME}/ember.png", f"/portraits/{GAME}/duke.png",
            f"/portraits/{GAME}/README.md", f"/portraits/{GAME}/readme.md", f"/portraits/{GAME}/sub/fox.png",
            f"/portraits/{GAME}/sub", f"/portraits/{GAME}/rook.png", f"/portraits/{GAME}/vesper.png",
            f"/portraits/{GAME}/rook.svg/", f"/portraits/{GAME}/rook.svg.bak", f"/portraits/{GAME}/rook.svg%00",
            f"/portraits/{GAME}/", f"/portraits/{GAME}", f"/portraits/{GAME}//rook.svg", f"/portraits//{GAME}/rook.svg",
            "/portraits/rook.svg", "/portraits/lark.jpg",               # per-game files are not global
            # folders: missing, linked, wrong case, a file, bad ids
            f"/portraits/{OTHER}/rook.png", "/portraits/g-link-s3/rook.png", "/portraits/g-case-s4/rook.png",
            "/portraits/G-Case-s4/rook.png", "/portraits/g-file-s5/rook.png", "/portraits/G-pg-s2/rook.svg",
            "/portraits/g-pg.s2/rook.svg", "/portraits/stash/rook.png", "/portraits/portraits/rook.png", "/portraits/elsewhere/rook.png",
            # traversal and encoded slashes
            f"/portraits/{GAME}/../rook.png", f"/portraits/{GAME}/..%2Frook.png", f"/portraits/{GAME}/..%2frook.png",
            f"/portraits/{GAME}%2Frook.svg", f"/portraits/{GAME}%2frook.svg", f"/portraits/..%2F{GAME}/rook.svg",
            f"/portraits/../portraits/{GAME}/rook.svg", "/portraits/%2e%2e/secret.png", "/portraits/../secret.png",
            f"/portraits/{GAME}/%2e%2e/%2e%2e/secret.png", f"/portraits/{GAME}/../../secret.png",
            "/portraits/g-pg-s2%2F..%2F..%2Fsecret.png", f"/portraits/{GAME}/%2e%2e%2fvesper.png",
            "/portraits/..%5Csecret.png", f"/portraits/{GAME}\\rook.svg", "/portraits/g-link-s3%2Frook.png",
        ]
        for path in bad:
            status, body, _ = self.request(path)
            self.assertEqual(status, 404, path)
            self.assertNotIn(OUTSIDE, body, path)
            self.assertNotIn(b"case folder", body, path)

    def test_helpers_refuse_bad_input(self):
        for gid in ("..", "../g-pg-s2", "g-pg-s2/..", "g-pg-s2/", "g-..", "G-pg-s2", "g-case-s4", "g-link-s3",
                    "g-file-s5", "stash", "g-pg-s2\n", "", None, 7, "/" + str(self.pd / GAME)):
            self.assertIsNone(viewer.game_portrait_dir(self.pd, gid), gid)
            self.assertEqual(viewer.game_portraits(self.pd, gid), {}, gid)
        self.assertEqual(viewer.game_portrait_dir(self.pd, GAME), self.pd.resolve() / GAME)
        for rest in (f"{GAME}/../rook.png", f"../{GAME}/rook.svg", f"{GAME}/sub/fox.png", f"{GAME}/duke.png",
                     f"{GAME}/rook.svg\n", None):
            self.assertIsNone(viewer.resolve_portrait_path(self.pd, rest), rest)
        self.assertEqual(viewer.resolve_portrait_path(self.pd, f"{GAME}/rook.svg"),
                         (self.pd.resolve() / GAME / "rook.svg", "svg"))
        self.assertEqual(viewer.game_portraits(self.dir / "missing", GAME), {})

    # ------------------------------------------------------------------ export

    def test_export_embeds_the_right_set_for_each_game(self):
        for gid, seed in ((GAME, 2), (OTHER, 9)):
            run_game(seed, make_config(anonymise=True), log_path=self.dir / f"{gid}.jsonl", game_id=gid)
        for view in ("audience", "table"):
            html = viewer.export_html(self.dir / f"{GAME}.jsonl", view, portrait_dir=self.pd)
            tv.Export.check_self_contained(self, html)
            data = tv.Export.embedded(self, html)
            self.assertEqual(data["game_id"], GAME)
            self.assertEqual(data["portraits"], {"Rook": data_uri("image/svg+xml", P_ROOK),
                                                 "Lark": data_uri("image/jpeg", P_LARK),
                                                 "Vesper": data_uri("image/png", G_VESPER)})
            other = tv.Export.embedded(self, viewer.export_html(self.dir / f"{OTHER}.jsonl", view, portrait_dir=self.pd))
            self.assertEqual(other["portraits"], {"Rook": data_uri("image/png", G_ROOK),
                                                  "Vesper": data_uri("image/png", G_VESPER)})
            # presentation only: the game's events (names, models, roles) are the same with or without overrides
            bare = tv.Export.embedded(self, viewer.export_html(self.dir / f"{GAME}.jsonl", view, portrait_dir=self.dir / "none"))
            self.assertEqual(bare["portraits"], {})
            self.assertEqual({k: v for k, v in data.items() if k != "portraits"},
                             {k: v for k, v in bare.items() if k != "portraits"})
            self.assertNotIn(OUTSIDE.decode(), html)

    def test_log_is_not_touched(self):
        log = self.dir / f"{GAME}.jsonl"
        run_game(2, make_config(), log_path=log, game_id=GAME)
        before = log.read_bytes()
        self.request(f"/api/log/{GAME}")
        self.request(f"/api/portraits?game={GAME}")
        self.request(f"/portraits/{GAME}/rook.svg")
        viewer.export_html(log, "audience", portrait_dir=self.pd)
        self.assertEqual(log.read_bytes(), before)


class PagePortraitSwitching(unittest.TestCase):
    """The page asks for each game's own set and empties the previous one before showing the next game."""

    def test_page_loads_each_games_set(self):
        html = viewer.page_html()
        self.assertIn("'/api/portraits' + q", html)
        self.assertIn("'?game=' + encodeURIComponent(id)", html)
        load = re.search(r"function loadGame\(id, view, opts\) \{(.*?)\n  \}\n", html, re.DOTALL).group(1)
        self.assertIn("setPortraits({})", load)                 # cleared when the game changes
        self.assertIn("loadPortraits(id)", load)                # fetched with the log, for this id
        self.assertLess(load.index("setPortraits(pics)"), load.index("buildBeats"))
        setp = re.search(r"function setPortraits\(pics\) \{(.*?)\n  \}", html, re.DOTALL).group(1)
        self.assertIn("delete PORTRAITS[k]", setp)               # replaced, never merged


if __name__ == "__main__":
    unittest.main()
