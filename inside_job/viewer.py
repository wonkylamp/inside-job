"""Browser viewer (SPEC section 16): a small read-only HTTP server, event decoration and export.

The page (`inside_job/viewer/index.html`, HTML + CSS + JS in one file) replays a finished game and
follows a game in progress from its JSONL log. This module only feeds it:

- `/api/games`: the games in `--out` (index rows plus logs with no index row), newest first.
- `/api/log/<game_id>?from=N&view=audience|table`: events from line N of the log, complete lines
  only, decorated for the audience or projected for the table.

Audience view: every event, with the values the Python helpers already compute added to each turn
(`_label`, `_role`, `_marks`, `_top_suspect`, `_fallback`, `_cards`), so the page never
re-implements rules logic. Table view: only `project(event, None)` of events `visible_to(event,
None)`, with vote turns held back until their `vote_result` (as `live.py` does), so the page never
receives anything a player at the table could not see.

`export_html` writes one self-contained file: the page with one game's decorated events embedded
as JSON; it works from `file://` with no network. Standard library only.

Portrait overrides (docs/STAGE4B.md): an image `inside_job/viewer/portraits/<codename>.png|webp|jpg|svg`
(lower case) replaces that character's drawing. `/api/portraits` lists them and `/portraits/<file>` serves
one; the file name is only ever matched against the codenames and extensions below, and the path read
is built from those constants, never from the request. An export embeds them as data: URIs.
Per-game overrides sit in `portraits/<game_id>/` (same file rules; a real directory, no symlink) and win
over the global image for that codename in that game only: `/api/portraits?game=<game_id>` lists one
game's set and `/portraits/<game_id>/<file>` serves a per-game file.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .clues import card_as_clue
from .config import CODENAMES
from .log import project, visible_to
from .transcript import fallback_tag, labeller, marks, top_suspect

GAME_ID = re.compile(r"^g-[0-9A-Za-z-]+$")
PAGE_PATH = Path(__file__).resolve().parent / "viewer" / "index.html"
DATA_TAG = '<script id="ij-data" type="application/json">null</script>'
VIEWS = ("audience", "table")
PORTRAIT_DIR = Path(__file__).resolve().parent / "viewer" / "portraits"
PORTRAIT_TYPES = {"png": "image/png", "webp": "image/webp", "jpg": "image/jpeg", "svg": "image/svg+xml"}
PORTRAIT_FILE = re.compile(r"^([a-z]+)\.(png|webp|jpg|svg)$")
PORTRAIT_MAX = 8 * 1024 * 1024
PAGE_CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
            "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'")

# Fields the page never shows. Dropped from the audience payload to keep it small (and because
# `rejections` / `error` can carry raw error text from the model client).
_AUDIENCE_DROP = ("usage", "served_model", "latency_s", "rejections", "error_kinds", "error", "error_kind",
                  "memory")


# --------------------------------------------------------------------------- reading logs

def read_complete(path: Path) -> list[dict]:
    """Every complete line of a log (a half-written last line is not an event yet)."""
    data = Path(path).read_bytes()
    out = []
    for raw in data.split(b"\n")[:-1]:
        raw = raw.strip()
        if not raw:
            continue
        try:
            ev = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(ev, dict):
            out.append(ev)
    return out


# --------------------------------------------------------------------------- decoration

def _card_texts(action: dict) -> list[str]:
    texts = []
    for c in (action or {}).get("clue_cards") or []:
        try:
            texts.append(card_as_clue(c)["text"])
        except (KeyError, TypeError, ValueError):
            texts.append("(unreadable card)")
    return texts


class _Audience:
    """Decorates events for the audience view; built from the log's `game_start`."""

    def __init__(self, events: list[dict]):
        start = next((e for e in events if e.get("type") == "game_start"), None)
        self.start = start
        self.label = labeller(start) if start else (lambda n: n)
        self.roles = {p["name"]: p.get("role") for p in (start or {}).get("players", []) if "name" in p}

    def event(self, e: dict) -> dict:
        d = {k: v for k, v in e.items() if k not in _AUDIENCE_DROP}
        t = e.get("type")
        if t == "game_start":
            cfg = e.get("config") or {}
            d["config"] = {"game": cfg.get("game", {})}       # rules only; models are in `players`
            d["_labels"] = {p["name"]: self.label(p["name"]) for p in e.get("players", []) if "name" in p}
        elif t == "turn":
            p = e.get("player")
            d["_label"] = self.label(p) if p else p
            d["_role"] = self.roles.get(p)
            try:
                d["_marks"] = [list(m) for m in marks(e)]
            except (KeyError, TypeError):
                d["_marks"] = []
            try:
                ts = top_suspect(e)
            except (TypeError, ValueError):
                ts = None
            d["_top_suspect"] = ({"name": ts[0], "pct": ts[1], "kind": ts[2], "label": self.label(ts[0])}
                                 if ts else None)
            d["_fallback"] = fallback_tag(e)
            d["_cards"] = _card_texts(e.get("action"))
        return d


def _table_event(e: dict) -> dict | None:
    """What the public table sees of one event, or None."""
    if not visible_to(e, None):
        return None
    p = project(e, None)
    if p is None:
        return None
    p = dict(p)
    if p.get("type") == "turn":
        p["_cards"] = _card_texts(p.get("action"))
    return p


def rules_of(events: list[dict]) -> dict:
    """The job targets from `game_start` (players are told them; they carry nothing private)."""
    start = next((e for e in events if e.get("type") == "game_start"), None)
    g = ((start or {}).get("config") or {}).get("game") or {}
    return {k: g[k] for k in ("clean_target", "sabotage_target") if k in g}


def log_slice(events: list[dict], view: str, start: int = 0) -> dict:
    """Decorated events from line `start`: `{"events", "next", "done", "meta"}`.

    In table view, vote turns are held until their `vote_result`; if the result is not in the log
    yet, `next` points at the first held vote so the next request picks them up together."""
    if view not in VIEWS:
        raise ValueError("view must be audience or table")
    n = len(events)
    start = max(0, min(int(start), n))
    out: list[dict] = []
    nxt = n
    if view == "audience":
        dec = _Audience(events)
        out = [dec.event(e) for e in events[start:]]
    else:
        held: list[dict] = []
        held_from = None
        for i in range(start, n):
            p = _table_event(events[i])
            if p is None:
                continue
            if p.get("type") == "turn" and p.get("turn_phase") == "vote":
                if held_from is None:
                    held_from = i
                held.append(p)
                continue
            if p.get("type") == "vote_result":
                out.extend(held)
                held, held_from = [], None
            out.append(p)
        if held_from is not None:
            nxt = held_from
    end_at = next((i for i, e in enumerate(events) if e.get("type") == "game_end"), None)
    done = end_at is not None and end_at < nxt
    meta = {"view": view, "rules": rules_of(events)}
    if events and events[0].get("game_id"):
        meta["game_id"] = events[0]["game_id"]
    return {"events": out, "next": nxt, "done": done, "meta": meta}


# --------------------------------------------------------------------------- game list

def _row_info(row: dict) -> dict:
    players = sorted(row.get("players") or [], key=lambda p: p.get("seat", 0))
    return {"game_id": row.get("game_id"), "seed": row.get("seed"), "batch": row.get("batch"),
            "finished": True, "winner": row.get("winner"), "reason": row.get("reason"),
            "rounds": row.get("rounds"), "spoiled": bool(row.get("spoiled", False)),
            "cast": [p.get("model_name") or p.get("model") for p in players]}


def _log_info(path: Path) -> dict:
    events = read_complete(path)
    start = next((e for e in events if e.get("type") == "game_start"), {})
    end = next((e for e in events if e.get("type") == "game_end"), None)
    players = sorted(start.get("players") or [], key=lambda p: p.get("seat", 0))
    return {"game_id": path.stem, "seed": start.get("seed"), "batch": start.get("batch"),
            "finished": end is not None, "winner": (end or {}).get("winner"), "reason": (end or {}).get("reason"),
            "rounds": (end or {}).get("rounds", events[-1].get("round") if events else None),
            "spoiled": False, "cast": [p.get("model_name") or p.get("model") for p in players]}


def list_games(out: Path) -> list[dict]:
    """Games in `out`, newest first: index rows (last row per game id wins) plus logs with no row."""
    out = Path(out)
    rows: dict[str, dict] = {}
    index = out / "index.jsonl"
    if index.is_file():
        for line in index.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("game_id"):
                rows[row["game_id"]] = row
    games = []
    for p in out.glob("g-*.jsonl") if out.is_dir() else []:
        if not GAME_ID.match(p.stem) or not p.is_file():
            continue
        try:
            info = _row_info(rows[p.stem]) if p.stem in rows else _log_info(p)
            info["mtime"] = p.stat().st_mtime
        except (OSError, ValueError):
            continue
        games.append(info)
    games.sort(key=lambda g: (g["mtime"], g["game_id"]), reverse=True)
    return games


def resolve_game(out: Path, game_id: str) -> Path | None:
    """The log of `game_id` directly inside `out`, or None. Nothing else is ever served."""
    if not isinstance(game_id, str) or not GAME_ID.match(game_id):
        return None
    base = Path(out).resolve()
    path = (base / f"{game_id}.jsonl").resolve()
    if path.parent != base or not path.is_file():
        return None
    return path


# --------------------------------------------------------------------------- portrait overrides

def portrait_file(folder: Path, name: str) -> tuple[Path, str] | None:
    """The override image for one codename (first of png, webp, jpg, svg), or None.

    `name` must be a codename; the path is built from it and a fixed extension only."""
    if name not in CODENAMES:
        return None
    for ext in PORTRAIT_TYPES:
        hit = _portrait_path(folder, f"{name.lower()}.{ext}")
        if hit:
            return hit, ext
    return None


def _portrait_path(folder: Path, filename: str) -> Path | None:
    """`folder/filename` if a regular file of exactly that name (case included) sits directly in the folder."""
    base = Path(folder).resolve()
    try:
        if filename not in os.listdir(base):           # exact name: case-insensitive file systems would match Fox.png
            return None
        p = base / filename
        if p.is_file() and not p.is_symlink() and p.resolve().parent == base and p.stat().st_size <= PORTRAIT_MAX:
            return p
    except OSError:
        pass
    return None


def portraits(folder: Path | None = None) -> dict[str, tuple[Path, str]]:
    """{codename: (path, ext)} for every codename with an override image in `folder`."""
    folder = PORTRAIT_DIR if folder is None else Path(folder)
    if not folder.is_dir():
        return {}
    out = {}
    for name in CODENAMES:
        hit = portrait_file(folder, name)
        if hit:
            out[name] = hit
    return out


def resolve_portrait(folder: Path, filename: str) -> tuple[Path, str] | None:
    """`/portraits/<filename>`: exactly `<codename in lower case>.<png|webp|jpg|svg>`, or None."""
    if not isinstance(filename, str):
        return None
    m = PORTRAIT_FILE.fullmatch(filename)
    if not m:
        return None
    canon = {c.lower(): c for c in CODENAMES}.get(m.group(1))
    if canon is None:
        return None
    p = _portrait_path(folder, f"{canon.lower()}.{m.group(2)}")
    return (p, m.group(2)) if p else None


def game_portrait_dir(folder: Path | None, game_id: str) -> Path | None:
    """`folder/<game_id>` for one game's own overrides, or None.

    `game_id` must match GAME_ID (so no `/`, `.` or `%`), and the folder must be a real directory of
    exactly that name (case included) directly inside `folder`: a symlink is refused."""
    if not isinstance(game_id, str) or not GAME_ID.fullmatch(game_id):
        return None
    base = (PORTRAIT_DIR if folder is None else Path(folder)).resolve()
    try:
        if game_id not in os.listdir(base):
            return None
        p = base / game_id
        if p.is_symlink() or not p.is_dir() or p.resolve().parent != base:
            return None
    except OSError:
        return None
    return p


def game_portraits(folder: Path | None, game_id: str) -> dict[str, tuple[Path, str]]:
    """{codename: (path, ext)} from one game's own folder only (empty if it has none)."""
    gd = game_portrait_dir(folder, game_id)
    return portraits(gd) if gd else {}


def portraits_for(folder: Path | None, game_id: str | None = None) -> dict[str, tuple[Path, str]]:
    """The overrides one game shows: its own image for a codename if it has one, else the global one."""
    out = portraits(folder)
    if game_id is not None:
        out.update(game_portraits(folder, game_id))
    return out


def portrait_urls(folder: Path | None, game_id: str | None = None) -> dict[str, str]:
    """{codename: URL} for `/api/portraits` (with `game_id`, that game's set, per-game images first)."""
    urls = {name: f"/portraits/{p.name}" for name, (p, _) in portraits(folder).items()}
    if game_id is not None:
        urls.update({name: f"/portraits/{game_id}/{p.name}" for name, (p, _) in game_portraits(folder, game_id).items()})
    return urls


def resolve_portrait_path(folder: Path, rest: str) -> tuple[Path, str] | None:
    """`/portraits/<rest>`: `<file>` (global) or `<game_id>/<file>` (one game's folder), or None."""
    if not isinstance(rest, str):
        return None
    parts = rest.split("/")
    if len(parts) == 1:
        return resolve_portrait(folder, parts[0])
    if len(parts) == 2:
        gd = game_portrait_dir(folder, parts[0])
        return resolve_portrait(gd, parts[1]) if gd else None
    return None


# --------------------------------------------------------------------------- page and export

def page_html() -> str:
    return PAGE_PATH.read_text(encoding="utf-8")


def embed_json(payload) -> str:
    """JSON safe inside a <script type="application/json"> element: no `<`, `>` or `&`, and no
    literal `://` (so no URL in the data reads as a reference)."""
    s = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    s = s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    s = s.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return s.replace("://", ":\\/\\/")


def export_html(log_path: Path, view: str = "audience", portrait_dir: Path | None = None) -> str:
    """The page with one game's decorated events embedded (works from file://, no network).
    Portrait overrides (this game's own folder first, then the global ones) are embedded as data: URIs."""
    events = read_complete(log_path)
    sl = log_slice(events, view, 0)
    game_id = sl["meta"].get("game_id") or Path(log_path).stem
    pics = {name: f"data:{PORTRAIT_TYPES[ext]};base64," + base64.b64encode(p.read_bytes()).decode("ascii")
            for name, (p, ext) in portraits_for(portrait_dir, game_id).items()}
    payload = {"game_id": game_id, "view": view,
               "events": sl["events"], "done": sl["done"], "meta": sl["meta"], "exported": True, "portraits": pics}
    html = page_html()
    if DATA_TAG not in html:
        raise RuntimeError("viewer page has no data slot")
    return html.replace(DATA_TAG, DATA_TAG.replace(">null<", ">" + embed_json(payload) + "<"), 1)


# --------------------------------------------------------------------------- server

class Handler(BaseHTTPRequestHandler):
    server_version = "InsideJobViewer/1"
    out_dir: Path = Path("games")
    portrait_dir: Path = PORTRAIT_DIR
    quiet = True

    def log_message(self, fmt, *args):
        if not self.quiet:
            super().log_message(fmt, *args)

    def _send(self, status, body: bytes, ctype: str):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if ctype.startswith("text/html"):
            self.send_header("Content-Security-Policy", PAGE_CSP)
        elif ctype.startswith("image/"):
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=HTTPStatus.OK):
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _not_found(self):
        self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_GET(self):
        parts = urlsplit(self.path)
        path = parts.path
        if path in ("/", "/index.html"):
            self._send(HTTPStatus.OK, page_html().encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/portraits":
            games = parse_qs(parts.query).get("game")
            if games is None:
                self._json({"portraits": portrait_urls(self.portrait_dir)})
            elif len(games) == 1 and GAME_ID.fullmatch(games[0]):
                self._json({"portraits": portrait_urls(self.portrait_dir, games[0])})
            else:
                self._not_found()
            return
        if path.startswith("/portraits/"):
            hit = resolve_portrait_path(self.portrait_dir, path[len("/portraits/"):])
            if hit is None:
                self._not_found()
                return
            try:
                body = hit[0].read_bytes()
            except OSError:
                self._not_found()
                return
            self._send(HTTPStatus.OK, body, PORTRAIT_TYPES[hit[1]])
            return
        if path == "/api/games":
            self._json({"games": list_games(self.out_dir)})
            return
        if path.startswith("/api/log/"):
            game_id = path[len("/api/log/"):]
            log = resolve_game(self.out_dir, game_id)
            if log is None:
                self._not_found()
                return
            q = parse_qs(parts.query)
            view = (q.get("view") or ["audience"])[0]
            try:
                start = int((q.get("from") or ["0"])[0])
            except ValueError:
                start = 0
            if view not in VIEWS:
                self._json({"error": "view must be audience or table"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                events = read_complete(log)
            except OSError:
                self._not_found()
                return
            self._json(log_slice(events, view, start))
            return
        self._not_found()

    def _method_not_allowed(self):
        body = json.dumps({"error": "read-only: GET only"}).encode("utf-8")
        self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
        self.send_header("Allow", "GET")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = do_TRACE = do_CONNECT = _method_not_allowed


def make_server(out_dir, port: int = 8765, quiet: bool = True, portrait_dir=None) -> ThreadingHTTPServer:
    """A server on 127.0.0.1 only. Raises OSError if the port is taken."""
    handler = type("BoundHandler", (Handler,), {"out_dir": Path(out_dir), "quiet": quiet,
                                                "portrait_dir": Path(portrait_dir) if portrait_dir else PORTRAIT_DIR})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    return server


def start_in_thread(out_dir, port: int = 0, portrait_dir=None) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """For tests: a server on a free port, serving in a background thread."""
    server = make_server(out_dir, port, portrait_dir=portrait_dir)
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    return server, th


# --------------------------------------------------------------------------- command

def newest_game(out: Path) -> Path | None:
    logs = [p for p in Path(out).glob("g-*.jsonl") if GAME_ID.match(p.stem)] if Path(out).is_dir() else []
    return max(logs, key=lambda p: p.stat().st_mtime) if logs else None


def run_view(args) -> int:
    """The `view` command (SPEC section 16)."""
    out = Path(args.out)
    game_id = None
    if args.log:
        p = Path(args.log)
        if p.suffix == ".jsonl" or p.is_file() or "/" in args.log:
            if not p.is_file():
                print(f"view: {p} not found", file=sys.stderr)
                return 2
            out, game_id = p.parent, p.stem          # serve the folder the log is in
        else:
            game_id = args.log
        if not GAME_ID.match(game_id) or resolve_game(out, game_id) is None:
            print(f"view: no game log {game_id!r} in {out}", file=sys.stderr)
            return 2
    elif args.latest:
        p = newest_game(out)
        if p is None:
            print(f"view: no game logs in {out}", file=sys.stderr)
            return 2
        game_id = p.stem

    if args.export:
        if game_id is None:
            print("view: --export needs a log (path or game id) or --latest", file=sys.stderr)
            return 2
        html = export_html(resolve_game(out, game_id), args.view)
        dest = Path(args.export)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(html, encoding="utf-8")
        print(f"wrote {dest} ({args.view} view of {game_id}, {len(html) // 1024} KB)")
        return 0

    try:
        server = make_server(out, args.port)
    except OSError as e:
        print(f"view: cannot listen on 127.0.0.1:{args.port} ({e.strerror or e}). Is another viewer running? "
              f"Try --port {args.port + 1}.", file=sys.stderr)
        return 2
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    query = []
    if game_id:
        query.append(f"game={game_id}")
    if args.view != "audience":
        query.append(f"view={args.view}")
    if query:
        url += "?" + "&".join(query)
    print(f"Inside Job viewer: {url}\nserving {out.resolve()} (read-only). Ctrl-C to stop.", flush=True)
    if not args.no_open:
        try:
            webbrowser.open(url)
        except webbrowser.Error:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        server.server_close()
    return 0
