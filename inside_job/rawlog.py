"""The raw sidecar log of a game, and the code fingerprint (docs/RAWLOG.md).

The game log keeps the cleaned, parsed turn. The raw file beside it, `<log stem>.raw.jsonl`
(gzipped to `<log stem>.raw.jsonl.gz` when the game ends), keeps what the game log does not: every
system prompt, turn prompt and reply schema, every call attempt's complete CLI stdout (rejected,
failed and over-long replies included; for an OpenRouter model, the HTTP response body) and
per-attempt usage, and which code played the game.

Nothing that builds prompts, the transcript, the live view, the report or the viewer reads it.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import zlib
from pathlib import Path

RAW_SUFFIX = ".raw.jsonl"
GZ_SUFFIX = ".gz"

# The files that decide how a game is played, relative to the project root.
FINGERPRINT_FILES = tuple(sorted((
    "RULES.md",
    "inside_job/__init__.py",
    "inside_job/clues.py",
    "inside_job/config.py",
    "inside_job/engine.py",
    "inside_job/llm.py",
    "inside_job/log.py",
    "inside_job/openrouter.py",       # the OpenRouter request (wire schema, reasoning, max tokens)
    "inside_job/prompts.py",
    "inside_job/schemas.py",
)))
PROJECT_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- hashing

def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def schema_json(schema: dict) -> str:
    """The compact, key-sorted JSON of a schema (what its sha256 is taken over)."""
    return json.dumps(schema, separators=(",", ":"), sort_keys=True)


def schema_sha256(schema: dict) -> str:
    return sha256_text(schema_json(schema))


# --------------------------------------------------------------------------- code fingerprint

_FINGERPRINT_CACHE: dict | None = None


def code_fingerprint(root: str | Path | None = None) -> dict:
    """`{"code_hash": sha256 hex, "code_files": {relative path: sha256 hex or "missing"}}`.

    `code_hash` is the sha256 of the lines `"<path> <sha256>\\n"` in sorted path order. With no
    `root` the project root is found from the package location and the result is cached for the
    process; an explicit `root` is always hashed afresh."""
    global _FINGERPRINT_CACHE
    if root is None and _FINGERPRINT_CACHE is not None:
        return {"code_hash": _FINGERPRINT_CACHE["code_hash"], "code_files": dict(_FINGERPRINT_CACHE["code_files"])}
    base = Path(root) if root is not None else PROJECT_ROOT
    files = {}
    for rel in FINGERPRINT_FILES:
        try:
            files[rel] = hashlib.sha256((base / rel).read_bytes()).hexdigest()
        except OSError:
            files[rel] = "missing"
    code_hash = hashlib.sha256("".join(f"{rel} {files[rel]}\n" for rel in FINGERPRINT_FILES)
                               .encode("utf-8")).hexdigest()
    out = {"code_hash": code_hash, "code_files": files}
    if root is None:
        _FINGERPRINT_CACHE = {"code_hash": code_hash, "code_files": dict(files)}
    return out


# --------------------------------------------------------------------------- paths

def raw_path_for(log_path: str | Path) -> Path:
    """`g-....jsonl` -> `g-....raw.jsonl` in the same folder (a raw path is returned unchanged)."""
    p = Path(log_path)
    name = p.name
    if name.endswith(RAW_SUFFIX + GZ_SUFFIX):
        return p.with_name(name[: -len(GZ_SUFFIX)])
    if name.endswith(RAW_SUFFIX):
        return p
    stem = name[: -len(".jsonl")] if name.endswith(".jsonl") else p.stem
    return p.with_name(stem + RAW_SUFFIX)


def is_raw_name(name: str) -> bool:
    return name.endswith(RAW_SUFFIX) or name.endswith(RAW_SUFFIX + GZ_SUFFIX)


# --------------------------------------------------------------------------- writer

class RawLog:
    """Append-only JSON-lines writer for one game's raw records.

    `path` is the game log path (or the raw path itself). The file is opened on the first write
    and flushed after every record, so a crashed game leaves a readable file. `write` raises
    OSError on failure; the engine catches it, warns once and stops writing for that game.
    `close()` gzips the file to `<stem>.raw.jsonl.gz` and removes the plain file."""

    def __init__(self, path: str | Path):
        self.path = raw_path_for(path)
        self.gz_path = self.path.with_name(self.path.name + GZ_SUFFIX)
        self._fh = None
        self._opened = False                  # this object created the plain file
        self.closed = False

    def write(self, record: dict) -> None:
        if self.closed:
            raise OSError("raw log is closed")
        if self._fh is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.path, "w", encoding="utf-8")
            self._opened = True
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._fh.flush()

    def close(self) -> None:
        """Gzip the plain file (only the one this object wrote) and remove it. Idempotent."""
        if self.closed:
            return
        self.closed = True
        if self._fh is not None:
            fh, self._fh = self._fh, None
            fh.close()
        if not self._opened or not self.path.exists():
            return
        tmp = self.gz_path.with_name(self.gz_path.name + ".tmp")
        try:
            with open(self.path, "rb") as src, open(tmp, "wb") as raw_dst, \
                    gzip.GzipFile(filename="", mode="wb", fileobj=raw_dst, mtime=0) as dst:
                shutil.copyfileobj(src, dst)
            os.replace(tmp, self.gz_path)
        except BaseException:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise                                 # the plain file is kept
        self.path.unlink()

    @property
    def final_path(self) -> Path | None:
        """The file this log left on disk: the gz once closed, else the plain file, else None."""
        if self.gz_path.exists() and self.closed:
            return self.gz_path
        if self._opened and self.path.exists():
            return self.path
        return None


# --------------------------------------------------------------------------- reader

def read_raw(path: str | Path) -> list[dict]:
    """The records of a raw file, plain or gzipped. A torn last line (a crash mid-write) is
    dropped; a truncated gzip stream yields the records before the cut. Given a game log path,
    reads its raw file (the gz if present, else the plain one)."""
    p = Path(path)
    if not is_raw_name(p.name):
        plain = raw_path_for(p)
        gz = plain.with_name(plain.name + GZ_SUFFIX)
        p = gz if gz.exists() else plain
    if p.name.endswith(GZ_SUFFIX):
        data = bytearray()
        try:
            with gzip.open(p, "rb") as f:
                while True:
                    chunk = f.read(1 << 16)
                    if not chunk:
                        break
                    data += chunk
        except (EOFError, zlib.error, gzip.BadGzipFile):
            pass                                  # keep what was readable
        text = bytes(data).decode("utf-8", "replace")
    else:
        text = Path(p).read_text(encoding="utf-8", errors="replace")
    lines = [ln for ln in text.split("\n") if ln.strip()]
    out = []
    for i, line in enumerate(lines):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            if i == len(lines) - 1:
                break                             # torn last line
            raise ValueError(f"{p}: line {i + 1} is not JSON")
        out.append(rec)
    return out
