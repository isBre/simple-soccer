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
RANK_OBS = 56                     # features_team + 10 rank numbers (features_rank)
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


def ranks(m, p):
    """10 role-free derived numbers (user OK, 2026-11-21): for me and my 4 teammates in the order of features_team (nearest
    first), the player's rank in our team by distance to the ball (0 = nearest) and by depth (0 = deepest, nearest our own
    goal), each divided by (team size - 1). They fix no role: a rank changes with the situation, and two players swap ranks as
    they move. The same information is in the 46 positions, but a small net cannot sort 5 points easily."""
    s = m.attack_dir(p.team)
    team = m.team_lists[p.team]
    n = max(len(team) - 1, 1)
    key = lambda o: (abs(o.pos - p.pos) ** 2, o.uid)
    order = [p] + sorted([o for o in team if o is not p], key=key)
    by_ball = {o.uid: i for i, o in enumerate(sorted(team, key=lambda o: (abs(o.pos - m.ball_pos) ** 2, o.uid)))}
    by_depth = {o.uid: i for i, o in enumerate(sorted(team, key=lambda o: (o.pos.real * s, o.uid)))}
    out = []
    for o in order:
        out += (by_ball[o.uid] / n, by_depth[o.uid] / n)
    return out


def features_rank(m, p):
    """features_team followed by ranks (56 numbers for 5 players)."""
    return features_team(m, p) + ranks(m, p)


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
    """The observation a net of this input size expects (46 = team observation, 56 = team + ranks; 49 / 54 = the older ego layouts)."""
    if n_in == TEAM_OBS:
        return features_team(m, p)
    if n_in == RANK_OBS:
        return features_rank(m, p)
    return features(m, p, n_in > 49)


class _Frame:
    """What every observation of one tick shares, computed once: each player's 4 scaled numbers from both teams' points of
    view, the squared distance of every pair, and each team's ranks by distance to the ball and by depth. features_many builds
    from it exactly the lists features_team / features_rank / features return (same values, same order)."""

    def __init__(self, m):
        pd = m.pitch
        ox, oy = pd.out_x, pd.out_y
        self.m = m
        self.teams = m.team_lists
        players = [o for t in self.teams for o in t]
        self.push = {}                                 # (uid, s) -> 4 numbers
        for o in players + [m.ball]:
            pos, vel = o.pos, o.vel
            y, vy = pos.imag / oy, vel.imag / 5.0
            key = id(o) if o is m.ball else o.uid
            self.push[key, 1.0] = (pos.real * 1.0 / ox, y, vel.real * 1.0 / 5.0, vy)
            self.push[key, -1.0] = (pos.real * -1.0 / ox, y, vel.real * -1.0 / 5.0, vy)
        self.ball_key = id(m.ball)
        self.d2 = {}                                   # (uid_a, uid_b) -> abs(a.pos - b.pos) ** 2 (symmetric)
        for i, a in enumerate(players):
            for b in players[i + 1:]:
                d = abs(a.pos - b.pos) ** 2
                self.d2[a.uid, b.uid] = self.d2[b.uid, a.uid] = d
        self.flags = (1.0 if m.kickoff_active else 0.0, 1.0 if m.state == 1 else 0.0)
        self._ranks = {}

    def team_ranks(self, team):
        r = self._ranks.get(team)
        if r is None:
            m, lst = self.m, self.teams[team]
            s = m.attack_dir(team)
            bp = m.ball_pos
            by_ball = {o.uid: i for i, o in enumerate(sorted(lst, key=lambda o: (abs(o.pos - bp) ** 2, o.uid)))}
            by_depth = {o.uid: i for i, o in enumerate(sorted(lst, key=lambda o: (o.pos.real * s, o.uid)))}
            r = self._ranks[team] = (by_ball, by_depth, max(len(lst) - 1, 1))
        return r


def features_many(m, players, team=True, rank=False, legacy=False, frame=None):
    """The observations of several players of the same tick, concatenated: per player features_team (team), then ranks (rank,
    after the team observation), then the legacy ego features with the slot one-hot (legacy). Identical to calling those."""
    f = frame or _Frame(m)
    push, d2 = f.push, f.d2
    out = []
    for p in players:
        s = m.attack_dir(p.team)
        if team:
            uid = p.uid
            out += push[uid, s]
            mates = [o for o in f.teams[p.team] if o is not p]
            mates.sort(key=lambda o: (d2[uid, o.uid], o.uid))
            for o in mates:
                out += push[o.uid, s]
            opps = list(f.teams[1 - p.team])
            opps.sort(key=lambda o: (d2[uid, o.uid], o.uid))
            for o in opps:
                out += push[o.uid, s]
            out += push[f.ball_key, s]
            out += f.flags
            if rank:
                by_ball, by_depth, n = f.team_ranks(p.team)
                out += (by_ball[uid] / n, by_depth[uid] / n)
                for o in mates:
                    out += (by_ball[o.uid] / n, by_depth[o.uid] / n)
        if legacy:
            out += push[p.uid, s]
            out += push[f.ball_key, s]
            for o in f.teams[p.team]:
                if o is not p:
                    out += push[o.uid, s]
            for o in f.teams[1 - p.team]:
                out += push[o.uid, s]
            pd = m.pitch
            rel = m.ball_pos - p.pos
            out.append(min(max(rel.real * s / 40.0, -6.0), 6.0))
            out.append(min(max(rel.imag / 40.0, -6.0), 6.0))
            out.append(min(abs(rel) / 40.0, 6.0))
            out.append((s * pd.half_w - p.pos.real) * s / 400.0)
            out.append((0.0 - p.pos.imag) / 400.0)
            out += [1.0 if p.slot == k else 0.0 for k in range(5)]
    return out


def features_group(m, players, n_in):
    """features_for for several players of the same tick: one list per player."""
    if n_in in (TEAM_OBS, RANK_OBS):
        f = _Frame(m)
        return [features_many(m, [p], True, n_in == RANK_OBS, False, f) for p in players]
    return [features(m, p, n_in > 49) for p in players]


def fits(n_in, team_size):
    return n_in in (8 * team_size + 9, 8 * team_size + 14, 8 * team_size + 6, 10 * team_size + 6)


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
    """A net served by rl/net_server.py (the experiment pipeline: newest / best checkpoint, the dashboard's live opponent).
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
    """spec: {"model": path} (a game-model JSON), {"dict": game model} (in memory, e.g. a self-play snapshot) or
    {"port": n} (a running rl/net_server.py). Model files are cached."""
    if "port" in spec:
        return RemoteNet(spec["port"])
    if "dict" in spec:
        return Net(spec["dict"])
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
        """out: this player's 10 net outputs. Sets p.input_dir / p.input_kick."""
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
        p.input_dir = d / l if l > 0.0 else 0j
        p.input_kick = kick
        p.kick_intent = ""
