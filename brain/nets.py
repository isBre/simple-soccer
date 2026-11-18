"""Neural-net teams: the observation a net sees, loading game-model JSON files, the forward pass and action sampling.

A game model is {"sizes": [n_in, h1, ..., 10], "W": [flat row-major weights per layer], "B": [biases], "kick_bias": k}: ReLU
hidden layers, linear output. Outputs 0..8 are move logits (DIRS, in the player's own frame: +x towards the opponent goal),
output 9 is the kick logit."""
import json
import math
import os
import socket
import struct
import threading

import numpy as np

TEAM_OBS = 46                     # role-free team observation (features_team)
DIRS = [0j, -1j, 1 - 1j, 1 + 0j, 1 + 1j, 1j, -1 + 1j, -1 + 0j, -1 - 1j]


# ---------------------------------------------------------------- observations

def _push(out, pos: complex, vel: complex, s: float, pd):
    out += (pos.real * s / pd.out_x, pos.imag / pd.out_y, vel.real * s / 5.0, vel.imag / 5.0)


def features_team(m, p):
    """Role-free observation (46 numbers, no player ID): the same picture for every player, from its own point of view (the
    pitch is mirrored so the team always attacks to the right). Me, my 4 teammates NEAREST FIRST, the 5 opponents NEAREST
    FIRST (position and speed each, scaled by the pitch and by 5), the ball (position and speed), kickoff on (0/1), goal
    celebration on (0/1). Sorting by distance instead of by slot keeps a player from knowing which "role" it has."""
    s = m.attack_dir(p.team)
    pd = m.pitch
    out = []
    _push(out, p.pos, p.vel, s, pd)
    key = lambda o: (abs(o.pos - p.pos) ** 2, o.uid)
    for group in ([o for o in m.team_lists[p.team] if o is not p], list(m.team_lists[1 - p.team])):
        group.sort(key=key)
        for o in group:
            _push(out, o.pos, o.vel, s, pd)
    _push(out, m.ball_pos, m.ball_vel, s, pd)
    out.append(1.0 if m.kickoff_active else 0.0)
    out.append(1.0 if m.state == 1 else 0.0)
    return out


def features(m, p, with_slot=False):
    """Older ego observation (49 numbers, 54 with the slot one-hot): me, ball, teammates and opponents in slot order, then the
    ball relative to me (fine scale, so the kick range is learnable) and the opponent goal relative to me."""
    s = m.attack_dir(p.team)
    pd = m.pitch
    out = []
    _push(out, p.pos, p.vel, s, pd)
    _push(out, m.ball_pos, m.ball_vel, s, pd)
    for o in m.team_lists[p.team]:
        if o is not p:
            _push(out, o.pos, o.vel, s, pd)
    for o in m.team_lists[1 - p.team]:
        _push(out, o.pos, o.vel, s, pd)
    rel = m.ball_pos - p.pos
    out.append(min(max(rel.real * s / 40.0, -6.0), 6.0))
    out.append(min(max(rel.imag / 40.0, -6.0), 6.0))
    out.append(min(abs(rel) / 40.0, 6.0))
    out.append((s * pd.half_w - p.pos.real) * s / 400.0)
    out.append((0.0 - p.pos.imag) / 400.0)
    if with_slot:                   # one-hot of the player's slot: lets roles (keeper / defender / attacker) emerge
        out += [1.0 if p.slot == k else 0.0 for k in range(5)]
    return out


def features_for(m, p, n_in):
    """The observation a net of this input size expects (46 = team observation; 49 / 54 = the older ego layouts)."""
    return features_team(m, p) if n_in == TEAM_OBS else features(m, p, n_in > 49)


def fits(n_in, team_size):
    return n_in in (8 * team_size + 9, 8 * team_size + 14, 8 * team_size + 6)


# ---------------------------------------------------------------- nets

class Net:
    """A game model loaded from JSON: batched forward pass with numpy."""

    def __init__(self, d):
        s = d["sizes"]
        self.W = [np.asarray(w, np.float32).reshape(s[i + 1], s[i]) for i, w in enumerate(d["W"])]
        self.B = [np.asarray(b, np.float32) for b in d["B"]]
        self.kick_bias = float(d.get("kick_bias", 0.0))
        self.n_in = int(s[0])

    def forward(self, x):
        """x: (n, n_in) -> (n, 10)."""
        h = np.asarray(x, np.float32)
        last = len(self.W) - 1
        for i, (w, b) in enumerate(zip(self.W, self.B)):
            h = h @ w.T + b
            if i < last:
                np.maximum(h, 0.0, out=h)
        return h


class RemoteNet:
    """A net served by tools/net_server.py (the experiment pipeline: newest / best checkpoint, the dashboard's live opponent).
    The server sends the input size on connect, then answers n_in float32 with 10 float32."""

    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", int(port)))
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.n_in = struct.unpack("<I", _recv(self.sock, 4))[0]
        self.kick_bias = 0.0

    def forward(self, x):
        out = []
        for row in np.asarray(x, np.float32):
            self.sock.sendall(row.tobytes())
            out.append(np.frombuffer(_recv(self.sock, 40), np.float32))
        return np.stack(out)


def _recv(sock, n):
    buf = b""
    while len(buf) < n:
        c = sock.recv(n - len(buf))
        if not c:
            raise ConnectionError("net server closed the connection")
        buf += c
    return buf


_cache = {}
_cache_lock = threading.Lock()


def load(spec):
    """spec: {"model": path} (a game-model JSON) or {"port": n} (a running tools/net_server.py). Model files are cached."""
    if "port" in spec:
        return RemoteNet(spec["port"])
    path = os.path.abspath(spec["model"])
    with _cache_lock:
        net = _cache.get(path)
        if net is None:
            with open(path) as f:
                net = Net(json.load(f))
            _cache[path] = net
    return net


# ---------------------------------------------------------------- the bot

class NetBot:
    """Plays one player from a net's output: samples the move from softmax(logits / T) and the kick from sigmoid(logit)
    (temperature 0 = the best move, kick when the logit is positive)."""

    def __init__(self, net, temperature=1.0):
        self.net = net
        self.temperature = temperature

    def act(self, m, p, out):
        """out: this player's 10 net outputs. Sets p.out_dir / p.out_kick."""
        best = 0
        for k in range(1, 9):
            if out[k] > out[best]:
                best = k
        t = self.temperature
        if t > 0.0:
            w = [math.exp((float(out[k]) - float(out[best])) / t) for k in range(9)]
            r = p.rng.random() * sum(w)
            for k in range(9):
                r -= w[k]
                if r <= 0.0:
                    best = k
                    break
        zk = min(max(float(out[9]) + self.net.kick_bias, -60.0), 60.0)
        kick = p.rng.random() < 1.0 / (1.0 + math.exp(-zk)) if t > 0.0 else zk > 0.0
        d = DIRS[best]
        d = complex(d.real * m.attack_dir(p.team), d.imag)
        l = abs(d)
        p.out_dir = d / l if l > 0.0 else 0j
        p.out_kick = kick
        p.out_intent = ""
