"""Smoke test of the web app (web/app.py): starts it on a free port and checks
  pages      the shell, styles and scripts are served; the Lab API answers (/api/v1/runs, /api/docs)
  catalog    leagues, players, teams (line-ups of known players), pitches, formations
  team select a mixed team fields the players who can play the size; a team of 5v5 nets is refused at 3v3
  live       a match played over the WebSocket (/ws/match, at 8x speed) ends with the same result as the same setup simulated
             in one go (game/api.py play): the live path and the simulation are the same match
  input      the human's keys move the controlled player
  dataset    the Lab's Dataset page API analyses that file (/api/dataset) and serves it for the replay (/api/dataset/match/<id>)
  record     a match with "record" saves the human's play (game/recorder.py): the picked slot is the one recorded, the keys become
             the right net moves, the observation can be rebuilt from the stored state (il/human_data.py), a match without it saves nothing
  ranking    after one round of 3v3 ratings (elo/, a temporary database): the Lab's ranking of a size (/api/ranking?size=3) and the
             game's Rankings page (/api/game/rankings) list players and teams, sorted, each rating inside its interval, and the
             teams in the catalog carry their Elo per size
  tournament new -> simulate a round -> fixture -> record a result -> view, through /api/game/tournament
  my team    a team built in the game (/api/game/team): saved in My Teams (a temporary folder here), plays 3v3 without its 5v5-only net
             and 5v5 with it, refused when a player is unknown, when it would edit a team of data/teams or from another origin; deleted

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
import urllib.error
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


def post_status(port, path, body, headers=None):
    """(HTTP status, JSON answer) of a POST, errors included."""
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _rated_first(rows):
    """The game's Rankings rows: rated entries first, sorted by Elo, then the unrated ones."""
    rated = [r for r in rows if r["games"]]
    return rows[:len(rated)] == rated and all(rated[i]["elo"] >= rated[i + 1]["elo"] for i in range(len(rated) - 1))


def ws_result(port, setup):
    """The result of a whole match played over the WebSocket at 8x speed."""
    ws = WS(port)
    ws.send({"setup": setup})
    ws.recv()
    ws.send({"speed": 8})
    while True:
        m = ws.recv()
        if m["k"] != "f":
            return m.get("result")


def check(name, ok, detail=""):
    print("%-11s %s  %s" % (name, "OK  " if ok else "FAIL", detail))
    return ok


def main():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    rec_dir = tempfile.mkdtemp(prefix="soccer_human_")
    my_dir = tempfile.mkdtemp(prefix="soccer_my_teams_")
    os.environ["SOCCER_MY_TEAMS"] = my_dir                  # the teams built in the game: a temporary folder, here and in the server
    local_dir = tempfile.mkdtemp(prefix="soccer_local_")
    os.environ["SOCCER_LOCAL"] = local_dir                  # the ratings database: a temporary one
    srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "web", "app.py"), "--port", str(port), "--host", "127.0.0.1", "--no-helpers"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={**os.environ, "SOCCER_HUMAN_DIR": rec_dir})
    results = []
    try:
        for _ in range(100):
            try:
                get(port, "/")
                break
            except OSError:
                time.sleep(0.1)
        pages = [get(port, p) for p in ("/", "/style.css", "/game.css", "/draw.js", "/game.js", "/game/core.js", "/game/render.js", "/lab/core.js", "/lab/app.js", "/api/docs")]
        runs = json.loads(get(port, "/api/v1/runs")[1])
        results.append(check("pages", all(c == 200 and len(b) > 100 for c, b in pages) and "data" in runs, "%d files, %d runs" % (len(pages), len(runs["data"]))))

        cat = json.loads(get(port, "/api/game/catalog")[1])
        players = {p["id"]: p for p in cat["players"]}
        results.append(check("catalog", len(cat["leagues"]) == 4 and len(cat["teams"]) >= 16 and cat["pitches"]
                             and len(players) >= 30 and all(i in players for t in cat["teams"] for i in t["lineup"]),
                             "%d teams, %d players, %d pitches" % (len(cat["teams"]), len(players), len(cat["pitches"]))))
        # teams are line-ups of players: a mixed team plays every size its players can, a team of 5v5 nets only 5v5
        rated = [t for t in cat["teams"] if t["elo"] is not None]
        described = [p for p in players.values() if p["description"]]
        mixed = api.play({"home": "all_stars", "away": "high_flyers", "pitch": "arena", "size": 3, "duration": 20.0, "seed": 5, "control": "none"})
        names = {p["name"] for p in mixed["players"] if p["team"] == 0}
        try:
            api.config({"home": "rl_team_5", "away": "cobalt", "size": 3})
            refused = False
        except ValueError:
            refused = True
        nets_only = [t for t in cat["teams"] if t["net"]]
        results.append(check("team select", refused and names == {"Lars Holm", "Viktor Lund", "Mateo Alonso"} and all(t["sizes"] == [5] for t in nets_only)
                             and len(described) == len(players) and all("plays" in t and "elo" in t for t in cat["teams"]),
                             "%d players described, %d teams rated, 3v3 all_stars fields %s" % (len(described), len(rated), ", ".join(sorted(names)))))

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
                                                                                   "golden goal" if live and live["overtime"] else "no overtime", sim["scores"])))

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
        ws.send({"setup": {**setup, "home": "rl_team_4", "away": "cobalt", "control": "single", "human_team": 1, "player": "0",
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
            gk = next(p for p in d["meta"]["players"] if p["team"] == 1 and p["slot"] == 0)
            worst = max(float(abs(human_data.observation(d, i) - d["obs"][i]).max()) for i in range(0, len(d["tick"]), 7))
            fwd = float((d["move"] == 3).mean())
            ok = ok and d["meta"]["complete"] and set(d["ctrl"].tolist()) == {gk["uid"]} and d["obs"].shape[1] == 46 and fwd > 0.9 \
                and worst < 1e-5 and len(d["tick"]) > 400
            detail = "%d rows, slot-0 uid %d, forward moves %.0f%%, obs rebuilt within %.1g" % (len(d["tick"]), gk["uid"], 100 * fwd, worst)
        results.append(check("record", ok, detail))

        ds = json.loads(get(port, "/api/dataset")[1])
        mid = ds["matches"][0]["id"] if ds.get("matches") else ""
        rp = json.loads(get(port, "/api/dataset/match/" + mid)[1]) if mid else {}
        ok = ds.get("files") == 1 and ds["matches"][0].get("outcome") in ("W", "D", "L") and abs(sum(ds["moves"]) - 100) < 1e-6 \
            and sum(r["rows"] for r in ds["ranks"]) == ds["rows"] and ds["heat"]["player"]["n"] == ds["rows"] \
            and len(rp.get("p", [])) == ds["rows"] and len(rp["p"][0]) == 20
        results.append(check("dataset", ok, "%d rows, forward moves %.0f%%, replay %d frames" % (
            ds.get("rows", 0), ds["moves"][3] if ds.get("moves") else 0, len(rp.get("p", [])))))

        subprocess.run([sys.executable, "-m", "elo", "round", "--size", "3", "--pairs", "6", "--workers", "2"], cwd=ROOT,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        rk = json.loads(get(port, "/api/ranking?size=3")[1])
        rows = rk.get("rows", [])
        kinds = {r["kind"] for r in rows}
        gr = json.loads(get(port, "/api/game/rankings?size=3")[1])
        cat3 = json.loads(get(port, "/api/game/catalog")[1])
        rated = [t for t in cat3["teams"] if t["ratings"].get("3", {}).get("games")]
        ok = rk.get("size") == 3 and rk.get("matches") == 12 and len(rows) >= 21 and {"rules", "team"} <= kinds \
            and all(r["lo"] <= r["elo"] <= r["hi"] for r in rows) and [r["rank"] for r in rows] == list(range(1, len(rows) + 1)) \
            and all(rows[i]["elo"] >= rows[i + 1]["elo"] for i in range(len(rows) - 1)) \
            and len(gr["players"]) >= 20 and gr["teams"] and _rated_first(gr["players"]) and _rated_first(gr["teams"]) \
            and rated and os.path.exists(os.path.join(local_dir, "elo.db"))
        results.append(check("ranking", ok, "3v3: %d entries (%s), %d matches, game page %d players / %d teams, %d teams rated in the catalog" % (
            len(rows), ", ".join(sorted(kinds)), rk.get("matches", 0), len(gr["players"]), len(gr["teams"]), len(rated))))

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
        # a mixed tournament: "all" draws its teams from every league
        d = post(port, "/api/game/tournament", {"action": "new", "league": "all", "user": "aurora", "count": len(cat["teams"]), "format": 0,
                                                "pitch": "arena", "size": 5, "duration": 60})
        ids = {x for r in d["t"]["rounds"] for f in r["fixtures"] for x in (f["home"], f["away"]) if x}
        leagues = {next(c["league"] for c in cat["teams"] if c["id"] == i) for i in ids}
        results.append(check("mixed cup", len(ids) == len(cat["teams"]) and leagues == {lg["id"] for lg in cat["leagues"] if lg["count"]},
                             "%s: %d teams from %s" % (d["t"]["title"], len(ids), ", ".join(sorted(leagues)))))

        # a team built in the game: a net first (it sits out 3v3), then rule-based and Opus players
        team = {"name": "Test Builders", "colors": {"primary": "ff8800", "secondary": "202020"}, "kit": "band",
                "logo": {"shape": "hex", "pattern": "halves", "symbol": "star", "c3": "ffffff"}, "style": "high_press",
                "lineup": ["finn_dahl", "lars_holm", "felix_wagner", "marco_bellini", "nikolai_orlov"]}
        code, saved = post_status(port, "/api/game/team", {"action": "save", "team": team})
        tid = saved.get("team", {}).get("id", "")
        cat2 = json.loads(get(port, "/api/game/catalog")[1])
        mine = next((t for t in cat2["teams"] if t["id"] == tid), None)
        base = {"away": "cobalt", "pitch": "arena", "duration": 15.0, "seed": 9, "control": "none", "allow_draw": True}
        r3 = ws_result(port, {**base, "home": tid, "size": 3})
        r5 = ws_result(port, {**base, "home": tid, "size": 5})
        on3 = [p["name"] for p in (r3 or {}).get("players", []) if p["team"] == 0]
        on5 = [p["name"] for p in (r5 or {}).get("players", []) if p["team"] == 0]
        bad_player = post_status(port, "/api/game/team", {"action": "save", "team": {**team, "lineup": ["nobody"] * 5}})[0]
        edit_curated = post_status(port, "/api/game/team", {"action": "save", "team": {**team, "id": "aurora"}})[0]
        foreign = post_status(port, "/api/game/team", {"action": "save", "team": team}, {"Origin": "http://evil.example"})[0]
        files = os.listdir(my_dir)
        gone = post_status(port, "/api/game/team", {"action": "delete", "id": tid})[0] == 200 and not os.listdir(my_dir) \
            and tid not in {t["id"] for t in json.loads(get(port, "/api/game/catalog")[1])["teams"]}
        results.append(check("my team", code == 200 and mine is not None and mine["league"] == "mine" and mine["sizes"] == [1, 2, 3, 4, 5]
                             and on3 == ["Lars Holm", "Felix Wagner", "Marco Bellini"] and on5[0] == "Finn Dahl" and bad_player == 400
                             and edit_curated == 400 and foreign == 403 and files == [tid + ".json"] and gone,
                             "%s saved, 3v3 fields %s, refused %d/%d/%d, deleted" % (tid, ", ".join(on3), bad_player, edit_curated, foreign)))
    finally:
        srv.terminate()
        shutil.rmtree(rec_dir, ignore_errors=True)
        shutil.rmtree(my_dir, ignore_errors=True)
        shutil.rmtree(local_dir, ignore_errors=True)
    ok = all(results)
    print("TOTAL ->", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
