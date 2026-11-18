"""The match server: Godot's UI (scripts/core/match_client.gd) runs every match here. Godot only draws and reads the
keyboard; the match itself (physics, rules, stats, grades, AI) is soccer.match.

  python3 soccer/server.py [--port 7330] [--idle-exit SECONDS] [--log FILE]

Godot starts it on demand (python3 with numpy, or $SOCCER_PYTHON). One session per connection; on Linux / macOS each runs in
its own forked process, so matches simulated in parallel (tournaments) use all cores. The server exits when one of its
source files changes (an updated checkout never answers with old code; Godot then starts the new one) and, with
--idle-exit, after that many seconds without a connection.

Wire format, little-endian; every message is a frame: u32 payload length, then the payload.
  1. Godot -> server, JSON: {"protocol": PROTOCOL, "mode": "live" | "run", "spec": {...}}  (spec: see config_from_spec)
     mode "run": the match is played to the end; reply {"ok": true, "result": {...}, "warnings": [...]}, then the
     connection closes (tournament matches, simulated in parallel).
     mode "live": reply {"ok": true, "players": [{uid, team, slot, role, id, radius}], "statics": [[x, y, r], ...],
     "ball_radius", "kinds": [{"kind": "rules" | "net", "n_in"}], "warnings": [...]}, then requests:
  2. 'S' u16 n, f32 human dir x, y, u8 human kick, u8 flags (1 = switch to the teammate nearest the ball):
     n ticks (0 = just the state). Reply: STATE, then per player PLAYER, then u32 n + JSON list of the goal events of
     these ticks.
  3. 'R': reply the result (JSON).   'Q': end the session."""
import argparse
import glob
import json
import os
import socket
import socketserver
import struct
import sys
import threading
import time
import traceback

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):   # the products are tiny: BLAS worker threads would
    os.environ.setdefault(_v, "1")                                          # only spin and starve the other matches

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from soccer.ai import nets                                               # noqa: E402
from soccer.data import Pitch, Style, Team                               # noqa: E402
from soccer.match import Match, MatchConfig                              # noqa: E402

PROTOCOL = 2
DEFAULT_PORT = 7330
STATE = struct.Struct("<iBBBfBfBBibbbiiffbbbb4f")
PLAYER = struct.Struct("<4fB")
STEP = struct.Struct("<Hff BB".replace(" ", ""))


def config_from_spec(s) -> MatchConfig:
    """A MatchConfig from the UI's spec: {"pitch": pitch dict, "teams": [team dict, team dict], "styles": [style dict or
    null, ...], "team_size", "duration", "score_limit", "allow_draw", "overtime", "match_seed", "control", "human_team",
    "auto_switch", "formations", "nets", "net_temperature"} (team / style dicts as in data/teams, data/styles)."""
    c = MatchConfig()
    c.pitch = Pitch(s["pitch"])
    c.teams = [Team(t) for t in s["teams"]]
    c.styles = [Style(x) if x else None for x in s.get("styles", [None, None])]
    for k in ("team_size", "score_limit", "match_seed", "control", "human_team"):
        if k in s:
            setattr(c, k, int(s[k]))
    for k in ("duration", "overtime", "net_temperature"):
        if k in s:
            setattr(c, k, float(s[k]))
    c.allow_draw = bool(s.get("allow_draw", True))
    c.auto_switch = bool(s.get("auto_switch", False))
    c.formations = list(s.get("formations", ["", ""]))
    c.nets = [n if n else None for n in s.get("nets", [None, None])]
    return c


def _uid(p):
    return p.uid if p is not None else -1


def state_bytes(m) -> bytes:
    sh = m.shootout if len(m.shootout) == 2 else [-1, -1]
    out = [STATE.pack(m.tick, m.state, min(m.scores[0], 255), min(m.scores[1], 255), m.time_left, int(m.overtime), m.ot_left,
                      int(m.kickoff_active), m.kickoff_team, m.kickoff_start, _uid(m.kickoff_taker), _uid(m.goal_scorer),
                      m.goal_team, m.goal_pause, m.goal_timer, m.goal_center.real, m.goal_center.imag, m.winner, sh[0], sh[1],
                      _uid(m.controlled), m.ball.pos.real, m.ball.pos.imag, m.ball.vel.real, m.ball.vel.imag)]
    for t in (0, 1):
        for p in m.team_lists[t]:
            out.append(PLAYER.pack(p.pos.real, p.pos.imag, p.vel.real, p.vel.imag,
                                   (1 if p.is_human else 0) | (2 if p.input_kick else 0) | (4 if p.kick_used else 0)))
    return b"".join(out)


def recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        c = sock.recv(n - len(buf))
        if not c:
            return None
        buf += c
    return bytes(buf)


def recv_frame(sock):
    h = recv_exact(sock, 4)
    if h is None:
        return None
    n = struct.unpack("<I", h)[0]
    return recv_exact(sock, n) if n else b""


def send_frame(sock, payload: bytes):
    sock.sendall(struct.pack("<I", len(payload)) + payload)


def send_json(sock, d):
    send_frame(sock, json.dumps(d).encode())


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        sock = self.request
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        frame = recv_frame(sock)
        if frame is None:
            return
        try:
            req = json.loads(frame)
            if int(req.get("protocol", 0)) != PROTOCOL:
                raise ValueError("protocol %s, server speaks %d: restart the match server" % (req.get("protocol"), PROTOCOL))
            spec = req["spec"]
            m = Match(config_from_spec(spec))
            if spec.get("puzzle_seed") is not None:
                m.puzzle_layout(int(spec["puzzle_seed"]))
        except Exception as e:                       # report the problem to Godot instead of hanging up silently
            traceback.print_exc()
            send_json(sock, {"ok": False, "error": "%s: %s" % (type(e).__name__, e)})
            return
        if req.get("mode") == "run":
            m.run_to_end()
            send_json(sock, {"ok": True, "result": m.make_result(), "warnings": m.ai.warnings})
            return
        send_json(sock, {"ok": True, "protocol": PROTOCOL, "kinds": m.ai.kinds, "warnings": m.ai.warnings,
                         "ball_radius": m.ball.radius, "statics": [[s.pos.real, s.pos.imag, s.radius] for s in m.statics],
                         "players": [{"uid": p.uid, "team": p.team, "slot": p.slot, "role": p.role, "id": p.pdef.id,
                                      "radius": p.radius} for t in (0, 1) for p in m.team_lists[t]]})
        try:
            while True:
                buf = recv_frame(sock)
                if not buf or buf[0] == ord("Q"):
                    return
                if buf[0] == ord("S"):
                    n, hx, hy, kick, flags = STEP.unpack_from(buf, 1)
                    if flags & 1:
                        m.switch_controlled()
                    m.set_human_input(complex(hx, hy), bool(kick))
                    n_ev = len(m.events)
                    for _ in range(n):
                        m.step()
                    ev = json.dumps(m.events[n_ev:]).encode()
                    send_frame(sock, state_bytes(m) + struct.pack("<I", len(ev)) + ev)
                elif buf[0] == ord("R"):
                    send_json(sock, m.make_result())
        except (ConnectionError, OSError):
            return
        except Exception:
            traceback.print_exc()                    # a bug: log it; Godot sees the connection drop


_Base = socketserver.ForkingTCPServer if hasattr(os, "fork") else socketserver.ThreadingTCPServer


class Server(_Base):
    allow_reuse_address = True
    daemon_threads = True
    max_children = 512
    last_activity = time.time()

    def process_request(self, request, client_address):
        Server.last_activity = time.time()
        super().process_request(request, client_address)


def _sources_mtime():
    return max(os.path.getmtime(f) for f in glob.glob(os.path.join(ROOT, "soccer", "**", "*.py"), recursive=True))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=int(os.environ.get("SOCCER_PORT", DEFAULT_PORT)))
    ap.add_argument("--idle-exit", type=float, default=0.0, help="exit after this many seconds without a connection (0 = never)")
    ap.add_argument("--log", default="", help="append output to this file")
    a = ap.parse_args()
    if a.log:
        os.makedirs(os.path.dirname(os.path.abspath(a.log)), exist_ok=True)
        log = open(a.log, "a", buffering=1)
        # at the descriptor level too: the stdout / stderr inherited from Godot (maybe a pipe a script waits on) are released
        for fd in (1, 2):
            os.dup2(log.fileno(), fd)
        null = os.open(os.devnull, os.O_RDONLY)
        os.dup2(null, 0)
        sys.stdout = sys.stderr = log
    for f in glob.glob(os.path.join(ROOT, "data", "models", "*.json")):    # shared by every forked session
        try:
            nets.load({"model": f})
        except (OSError, ValueError, KeyError):
            pass
    from soccer.data import database
    database()                                                            # data/ loaded once, before forking
    srv = Server(("127.0.0.1", a.port), Handler)
    print("match server: listening on %d (pid %d)" % (a.port, os.getpid()), flush=True)
    born = _sources_mtime()

    def watch():
        while True:
            time.sleep(2.0)
            active = len(getattr(srv, "active_children", None) or ())
            if _sources_mtime() != born:
                print("match server: source changed, exiting", flush=True)
                break
            if a.idle_exit > 0 and active == 0 and time.time() - Server.last_activity > a.idle_exit:
                print("match server: idle, exiting", flush=True)
                break
        srv.shutdown()

    threading.Thread(target=watch, daemon=True).start()
    srv.serve_forever(poll_interval=0.5)
    srv.server_close()


if __name__ == "__main__":
    main()
