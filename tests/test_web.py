"""Smoke test of the web app (web/app.py), no Godot needed: starts it on a free port and checks
  pages      the shell, styles and scripts are served; the Lab API answers (/api/v1/runs, /api/docs)
  catalog    leagues, teams, pitches, formations
  live       a match played over the WebSocket (/ws/match, at 8x speed) ends with the same result as the same setup simulated
             in one go (game/api.py play): the live path and the simulation are the same match
  input      the human's keys move the controlled player
  record     a match with "record" saves the human's play (game/recorder.py): the picked keeper is the one recorded, the keys become
             the right net moves, the observation can be rebuilt from the stored state (il/human_data.py), a match without it saves nothing
  tournament new -> simulate a round -> fixture -> record a result -> view, through /api/game/tournament

  python3 tests/test_web.py"""
import base64
import json
import os
import socket
import struct
import subprocess
import shutil
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from game import api   # noqa: E402


class WS:
    """A tiny WebSocket client (enough for the match protocol)."""

    def __init__(self, port):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall(("GET /ws/match HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                        "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (port, key)).encode())
        head = b""
        while b"\r\n\r\n" not in head:
            head += self.s.recv(1)
        assert b" 101 " in head.split(b"\r\n")[0], head
        self.buf = b""

    def send(self, obj):
        d, m = json.dumps(obj).encode(), os.urandom(4)
        hdr = bytes([0x81, 0x80 | len(d)]) if len(d) < 126 else bytes([0x81, 0xFE]) + struct.pack(">H", len(d))
        self.s.sendall(hdr + m + bytes(c ^ m[i % 4] for i, c in enumerate(d)))

    def recv(self):
        while True:
            b = self.buf
            if len(b) >= 2:
                n, i = b[1] & 0x7F, 2
                if n == 126:
                    n, i = struct.unpack(">H", b[2:4])[0], 4
                elif n == 127:
                    n, i = struct.unpack(">Q", b[2:10])[0], 10
                if len(b) >= i + n:
                    self.buf = b[i + n:]
                    return {"k": "closed"} if b[0] & 15 == 8 else json.loads(b[i:i + n])
            chunk = self.s.recv(65536)
            if not chunk:
                return {"k": "closed"}
            self.buf += chunk


def get(port, path):
    with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=60) as r:
        return r.status, r.read()


def post(port, path, body):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def check(name, ok, detail=""):
    print("%-11s %s  %s" % (name, "OK  " if ok else "FAIL", detail))
    return ok


def main():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    rec_dir = tempfile.mkdtemp(prefix="soccer_human_")
    srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "web", "app.py"), "--port", str(port), "--host", "127.0.0.1"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={**os.environ, "SOCCER_HUMAN_DIR": rec_dir})
    results = []
    try:
        for _ in range(100):
            try:
                get(port, "/")
                break
            except OSError:
                time.sleep(0.1)
        pages = [get(port, p) for p in ("/", "/style.css", "/game.css", "/draw.js", "/game.js", "/lab.js", "/api/docs")]
        runs = json.loads(get(port, "/api/v1/runs")[1])
        results.append(check("pages", all(c == 200 and len(b) > 100 for c, b in pages) and "data" in runs, "%d files, %d runs" % (len(pages), len(runs["data"]))))

        cat = json.loads(get(port, "/api/game/catalog")[1])
        results.append(check("catalog", len(cat["leagues"]) == 2 and len(cat["teams"]) >= 16 and cat["pitches"] and cat["formations"]["5"],
                             "%d teams, %d pitches" % (len(cat["teams"]), len(cat["pitches"]))))

        setup = {"home": "cobalt", "away": "rl_team_4", "pitch": "arena", "size": 5, "duration": 40.0, "seed": 21, "control": "none",
                 "allow_draw": False}
        ws = WS(port)
        ws.send({"setup": setup})
        meta = ws.recv()
        ws.send({"speed": 8})
        frames, t0 = 0, time.time()
        while True:
            m = ws.recv()
            if m["k"] == "f":
                frames += 1
            else:
                break
        live = m.get("result")
        sim = api.play(setup)
        results.append(check("live", meta["k"] == "m" and live is not None and live == json.loads(json.dumps(sim)),
                             "%d frames in %.1f s, score %s (%s) = simulated %s" % (frames, time.time() - t0, live and live["scores"],
                                                                                   "pens %s" % live["shootout"] if live and live["shootout"] else "no shootout", sim["scores"])))

        ws = WS(port)
        ws.send({"setup": {**setup, "control": "single", "human_team": 0, "duration": 30.0}})
        ws.recv()
        ws.send({"speed": 4})
        start = None
        moved = 0.0
        for _ in range(400):
            f = ws.recv()
            if f["k"] != "f":
                break
            if f["cu"] >= 0 and f["in"] == 0:
                i = next(k for k, h in enumerate(f["h"]) if h & 1)
                pos = (f["p"][2 * i], f["p"][2 * i + 1])
                if start is None:
                    start = pos
                    ws.send({"in": [0, 1, 0]})              # down
                moved = max(moved, pos[1] - start[1])
        ws.send({"quit": 1})
        results.append(check("input", moved > 40, "the controlled player moved %.0f px down" % moved))

        from il import human_data
        unrecorded = len(human_data.files(rec_dir))          # the matches above did not ask for recording
        ws = WS(port)
        ws.send({"setup": {**setup, "home": "rl_team_4", "away": "cobalt", "control": "single", "human_team": 1, "player": "GK",
                           "duration": 20.0, "record": True}})
        meta = ws.recv()
        ws.send({"speed": 8})
        ws.send({"in": [-1, 0, 0]})                          # team 1 attacks left: left is "forward" for the human
        while ws.recv()["k"] == "f":
            pass
        fs = human_data.files(rec_dir)
        ok = meta.get("rec") is True and unrecorded == 0 and len(fs) == 1
        detail = "%d files" % len(fs)
        if len(fs) == 1:
            d = human_data.load(fs[0])
            gk = next(p for p in d["meta"]["players"] if p["team"] == 1 and p["role"] == "GK")
            worst = max(float(abs(human_data.observation(d, i) - d["obs"][i]).max()) for i in range(0, len(d["tick"]), 7))
            fwd = float((d["move"] == 3).mean())
            ok = ok and d["meta"]["complete"] and set(d["ctrl"].tolist()) == {gk["uid"]} and d["obs"].shape[1] == 46 and fwd > 0.9 \
                and worst < 1e-5 and len(d["tick"]) > 400
            detail = "%d rows, keeper uid %d, forward moves %.0f%%, obs rebuilt within %.1g" % (len(d["tick"]), gk["uid"], 100 * fwd, worst)
        results.append(check("record", ok, detail))

        d = post(port, "/api/game/tournament", {"action": "new", "league": "rules", "user": "aurora", "count": 4, "format": 1,
                                                "pitch": "classic", "size": 3, "duration": 60})
        t = d["t"]
        fx = post(port, "/api/game/tournament", {"action": "fixture", "t": t})
        res = api.play(fx["setup"])
        d = post(port, "/api/game/tournament", {"action": "record", "t": t, "index": fx["index"], "result": res})
        d = post(port, "/api/game/tournament", {"action": "simulate", "t": d["t"]})
        rounds = d["t"]["rounds"]
        results.append(check("tournament", len(rounds) >= 2 or d["t"]["finished"],
                             "%s: %s" % (d["t"]["title"], ", ".join("%s %d-%d %s" % (f["home"], f["hg"], f["ag"], f["away"]) for f in rounds[0]["fixtures"]))))
    finally:
        srv.terminate()
        shutil.rmtree(rec_dir, ignore_errors=True)
    ok = all(results)
    print("TOTAL ->", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
