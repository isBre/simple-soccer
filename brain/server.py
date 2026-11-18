"""The brain server: every AI decision of the game. Godot (scripts/core/brain_link.gd) opens one connection per match and
starts this server itself when nothing is listening (python3, or $SOCCER_PYTHON).

  python3 brain/server.py [--port 7330] [--idle-exit SECONDS] [--log FILE]

One session per connection; on Linux / macOS each session runs in its own forked process, so matches simulated in parallel
(tournaments, evaluations, training workers) use all cores. The server exits when its own source files change (so an updated
checkout never keeps answering with old logic; Godot then starts the new one) and, with --idle-exit, after that many seconds
without any connection."""
import argparse
import glob
import json
import os
import socket
import socketserver
import sys
import threading
import time
import traceback

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):   # the products are tiny: BLAS worker threads would
    os.environ.setdefault(_v, "1")                                          # only spin and starve the Godot simulation

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from brain import nets                                                   # noqa: E402
from brain.match import Match                                            # noqa: E402
from brain.protocol import (CMD_DECIDE, CMD_OBSERVE, CMD_QUIT, DECISION, FLAG_UPDATE, INTENT_CODE, KEEPERS, PROTOCOL,  # noqa: E402
                            read_snapshot, recv_frame, send_frame)
from brain.rules import StyleBot, TeamBrain                              # noqa: E402

DEFAULT_PORT = 7330


class Session:
    """The AI of one match: the two team brains and one bot per player."""

    def __init__(self, setup):
        m = self.m = Match(setup)
        m.brains = [TeamBrain(t, m.styles[t]) for t in (0, 1)]
        self.teams = []
        self.warnings = []
        temperature = float(setup.get("temperature", 1.0))
        for t in (0, 1):
            spec = (setup.get("nets") or [None, None])[t]
            net = None
            if spec:
                try:
                    net = nets.load(spec)
                    if not nets.fits(net.n_in, len(m.team_lists[t])):
                        self.warnings.append("team %d: a net with %d inputs does not fit %d players; rule-based instead"
                                             % (t, net.n_in, len(m.team_lists[t])))
                        net = None
                except (OSError, ValueError, KeyError, ConnectionError) as e:
                    self.warnings.append("team %d: cannot load net %s (%s); rule-based instead" % (t, spec, e))
                    net = None
            for p in m.team_lists[t]:      # a net drives the whole team, goalkeeper included
                p.bot = nets.NetBot(net, temperature) if net is not None else StyleBot(m.styles[t])
            self.teams.append({"kind": "net", "n_in": net.n_in} if net is not None else {"kind": "rules"})

    def decide(self, buf):
        m = self.m
        flags, deciders, _ = read_snapshot(m, buf)
        if flags & FLAG_UPDATE:
            for b in m.brains:
                b.update(m)
        by_net = {}
        for p in deciders:
            if isinstance(p.bot, nets.NetBot):
                by_net.setdefault(id(p.bot.net), []).append(p)
            else:
                p.bot.decide(m, p)
        for group in by_net.values():          # one forward pass per net for all its players of this tick
            net = group[0].bot.net
            out = net.forward([nets.features_for(m, p, net.n_in) for p in group])
            for p, o in zip(group, out):
                p.bot.act(m, p, o)
        reply = bytearray()
        for p in deciders:
            reply += DECISION.pack(p.out_dir.real, p.out_dir.imag, 1 if p.out_kick else 0, INTENT_CODE.get(p.out_intent, 0))
        k = [b.keeper.uid if b.keeper is not None else -1 for b in m.brains]
        reply += KEEPERS.pack(k[0], k[1])
        return bytes(reply)

    def observe(self, buf):
        import numpy as np
        m = self.m
        _, _, off = read_snapshot(m, buf)
        mode, n = buf[off], buf[off + 1]
        out = []
        for i in range(n):
            uid = int.from_bytes(buf[off + 2 + i:off + 3 + i], "little", signed=True)
            p = m.by_uid[uid]
            if mode & 1:
                out += nets.features_team(m, p)
            if mode & 2:
                out += nets.features(m, p, True)
        return np.asarray(out, np.float32).tobytes()


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        sock = self.request
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        frame = recv_frame(sock)
        if frame is None:
            return
        try:
            setup = json.loads(frame)
            if int(setup.get("protocol", 0)) != PROTOCOL:
                raise ValueError("protocol %s, server speaks %d: restart the brain server" % (setup.get("protocol"), PROTOCOL))
            session = Session(setup)
        except Exception as e:                       # report the problem to Godot instead of hanging up silently
            traceback.print_exc()
            send_frame(sock, json.dumps({"ok": False, "error": str(e)}).encode())
            return
        send_frame(sock, json.dumps({"ok": True, "protocol": PROTOCOL, "teams": session.teams,
                                     "warnings": session.warnings}).encode())
        try:
            while True:
                buf = recv_frame(sock)
                if buf is None or not buf or buf[0] == CMD_QUIT:
                    return
                if buf[0] == CMD_DECIDE:
                    send_frame(sock, session.decide(buf))
                elif buf[0] == CMD_OBSERVE:
                    send_frame(sock, session.observe(buf))
        except (ConnectionError, OSError):
            return
        except Exception:
            traceback.print_exc()                    # a bug in the AI: log it; Godot sees the connection drop


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
    return max(os.path.getmtime(f) for f in glob.glob(os.path.join(ROOT, "brain", "*.py")))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=int(os.environ.get("SOCCER_BRAIN_PORT", DEFAULT_PORT)))
    ap.add_argument("--idle-exit", type=float, default=0.0, help="exit after this many seconds without a connection (0 = never)")
    ap.add_argument("--log", default="", help="append output to this file")
    a = ap.parse_args()
    if a.log:
        os.makedirs(os.path.dirname(os.path.abspath(a.log)), exist_ok=True)
        sys.stdout = sys.stderr = open(a.log, "a", buffering=1)
    for f in glob.glob(os.path.join(ROOT, "data", "models", "*.json")):    # shared by every forked session
        try:
            nets.load({"model": f})
        except (OSError, ValueError, KeyError):
            pass
    srv = Server(("127.0.0.1", a.port), Handler)
    print("brain server: listening on %d (pid %d)" % (a.port, os.getpid()), flush=True)
    born = _sources_mtime()

    def watch():
        while True:
            time.sleep(2.0)
            active = len(getattr(srv, "active_children", None) or ())
            if _sources_mtime() != born:
                print("brain server: source changed, exiting", flush=True)
                break
            if a.idle_exit > 0 and active == 0 and time.time() - Server.last_activity > a.idle_exit:
                print("brain server: idle, exiting", flush=True)
                break
        srv.shutdown()

    threading.Thread(target=watch, daemon=True).start()
    srv.serve_forever(poll_interval=0.5)
    srv.server_close()


if __name__ == "__main__":
    main()
