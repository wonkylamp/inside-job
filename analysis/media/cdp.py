"""A very small Chrome DevTools Protocol client (standard library only) for media capture.

It starts headless Chrome with a throwaway profile, opens one page, and lets a script evaluate
JavaScript and take PNG screenshots. Everything stays on 127.0.0.1: the page under capture is a
local `inside_job view` server or a local file, and the DevTools socket is on loopback.

    with Chrome(profile_dir, width=1080, height=1920) as c:
        c.navigate("http://127.0.0.1:8771/?game=...")
        c.eval("1 + 1")
        c.screenshot("out.png")
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import time
import urllib.request
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


class _WS:
    """Client side of RFC 6455, just enough for DevTools (text frames, masking, fragments)."""

    def __init__(self, url: str):
        assert url.startswith("ws://127.0.0.1:") or url.startswith("ws://localhost:"), url
        rest = url[len("ws://"):]
        hostport, path = rest.split("/", 1)
        host, port = hostport.split(":")
        self.sock = socket.create_connection((host, int(port)), timeout=60)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("websocket handshake failed")
            head += chunk
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError(head.decode(errors="replace"))
        self.buf = bytearray(head.split(b"\r\n\r\n", 1)[1])

    def _read(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(1 << 20)
            if not chunk:
                raise ConnectionError("websocket closed")
            self.buf += chunk
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out

    def send(self, text: str) -> None:
        data = text.encode()
        mask = os.urandom(4)
        n = len(data)
        if n < 126:
            hdr = struct.pack("!BB", 0x81, 0x80 | n)
        elif n < 65536:
            hdr = struct.pack("!BBH", 0x81, 0x80 | 126, n)
        else:
            hdr = struct.pack("!BBQ", 0x81, 0x80 | 127, n)
        masked = (int.from_bytes(data, 'big') ^ int.from_bytes((mask * (n // 4 + 1))[:n], 'big')).to_bytes(n, 'big') if n else b''
        self.sock.sendall(hdr + mask + masked)

    def recv(self) -> str:
        parts = []
        while True:
            b1, b2 = self._read(2)
            fin, op = b1 & 0x80, b1 & 0x0F
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._read(8))[0]
            payload = self._read(n)
            if op == 0x8:
                raise ConnectionError("websocket closed by peer")
            if op in (0x9, 0xA):
                continue
            parts.append(payload)
            if fin:
                return b"".join(parts).decode()


class Chrome:
    def __init__(self, profile_dir: str | Path, width: int = 1080, height: int = 1920, scale: float = 1.0,
                 port: int = 9341):
        self.profile = Path(profile_dir)
        self.width, self.height, self.scale, self.port = width, height, scale, port
        self.proc = None
        self.ws = None
        self.n = 0

    def __enter__(self):
        if self.profile.exists():
            shutil.rmtree(self.profile)
        self.profile.mkdir(parents=True)
        self.proc = subprocess.Popen(
            [CHROME, "--headless=new", f"--user-data-dir={self.profile}", f"--remote-debugging-port={self.port}",
             "--remote-debugging-address=127.0.0.1", "--no-first-run", "--no-default-browser-check",
             "--disable-gpu", "--hide-scrollbars", "--mute-audio", "--disable-background-networking",
             "--disable-component-update", "--disable-sync", "--metrics-recording-only",
             f"--window-size={self.width},{self.height}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        url = f"http://127.0.0.1:{self.port}/json"
        for _ in range(100):
            try:
                with urllib.request.urlopen(url, timeout=2) as r:
                    targets = json.load(r)
                pages = [t for t in targets if t.get("type") == "page"]
                if pages:
                    self.ws = _WS(pages[0]["webSocketDebuggerUrl"])
                    break
            except OSError:
                pass
            time.sleep(0.1)
        if not self.ws:
            raise RuntimeError("Chrome did not start")
        self.call("Page.enable")
        self.call("Runtime.enable")
        self.call("Emulation.setDeviceMetricsOverride", width=self.width, height=self.height,
                  deviceScaleFactor=self.scale, mobile=False)
        return self

    def __exit__(self, *exc):
        try:
            self.call("Browser.close")
        except Exception:
            pass
        if self.proc:
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)

    def call(self, method: str, **params):
        self.n += 1
        my = self.n
        self.ws.send(json.dumps({"id": my, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == my:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def navigate(self, url: str, wait_js: str | None = None, timeout: float = 30.0):
        assert url.startswith("http://127.0.0.1:") or url.startswith("file://"), url
        self.call("Page.navigate", url=url)
        if wait_js:
            self.wait_for(wait_js, timeout)

    def eval(self, js: str):
        r = self.call("Runtime.evaluate", expression=js, returnByValue=True, awaitPromise=True)
        if r.get("exceptionDetails"):
            raise RuntimeError(f"JS error: {r['exceptionDetails']}")
        return r.get("result", {}).get("value")

    def wait_for(self, js: str, timeout: float = 30.0):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if self.eval(js):
                    return
            except RuntimeError:
                pass
            time.sleep(0.1)
        raise TimeoutError(js)

    def screenshot(self, path: str | Path, clip: dict | None = None):
        params = {"format": "png", "captureBeyondViewport": False}
        if clip:
            params["clip"] = dict(clip, scale=1)
        r = self.call("Page.captureScreenshot", **params)
        Path(path).write_bytes(base64.b64decode(r["data"]))
