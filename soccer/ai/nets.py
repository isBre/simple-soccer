"""Neural-net players: loading game-model JSON files, the forward pass and action sampling. What a net sees (its observation,
a function of the public view) is soccer/ai/obs.py.

A game model is {"sizes": [n_in, h1, ..., 10], "W": [flat row-major weights per layer], "B": [biases], "kick_bias": k}: ReLU
hidden layers, linear output. Outputs 0..8 are move logits (DIRS, in the player's own frame: +x towards the opponent goal),
output 9 is the kick logit."""
import json
import math
import os
import random
import threading

import numpy as np

from ..match import DIRS, INTENTS
from .agent import Act
from .obs import SLOTS_NAME, SLOTS_OBS

CALL_OUT = 15                     # outputs of a net that calls: 9 moves, 1 kick, 5 calls (INTENTS order)


# ---------------------------------------------------------------- nets

class Net:
    """A game model loaded from JSON: batched forward pass with numpy."""

    def __init__(self, d):
        s = d["sizes"]
        self.W = [np.asarray(w, np.float32).reshape(s[i + 1], s[i]) for i, w in enumerate(d["W"])]
        self.B = [np.asarray(b, np.float32) for b in d["B"]]
        self.kick_bias = float(d.get("kick_bias", 0.0))
        self.n_in = int(s[0])
        self.n_out = int(s[-1])                 # 10: moves and kick; CALL_OUT (15): and a call
        self.obs = str(d.get("obs", ""))        # the observation it was trained on ("slots76"; older files leave it out)
        if self.n_in == SLOTS_OBS and self.obs not in ("", SLOTS_NAME):
            raise ValueError("a 76-input net with observation %r" % self.obs)

    def forward(self, x):
        """x: (n, n_in) -> (n, n_out)."""
        h = np.asarray(x, np.float32)
        last = len(self.W) - 1
        for i, (w, b) in enumerate(zip(self.W, self.B)):
            h = h @ w.T + b
            if i < last:
                np.maximum(h, 0.0, out=h)
        return h


_cache = {}
_cache_lock = threading.Lock()


def load(spec):
    """spec: {"model": path} (a game-model JSON) or {"dict": game model} (in memory, e.g. a self-play snapshot).
    Model files are cached."""
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
    """Plays one player from a net's output: samples the move from softmax(logits / T), the kick from sigmoid(logit) and, for a
    net that calls (CALL_OUT outputs), the call from softmax(call logits / T) (temperature 0 = the best move and call, kick when
    the logit is positive)."""

    def __init__(self, net, temperature=1.0, seed=0):
        self.net = net
        self.temperature = temperature
        self.rng = random.Random(seed)          # its own random numbers (lineup.build seeds it from the match)

    def act(self, m, p, out):
        """out: this player's net outputs -> its Act (a net with 10 outputs calls nothing)."""
        best = 0
        for k in range(1, 9):
            if out[k] > out[best]:
                best = k
        t = self.temperature
        if t > 0.0:
            w = [math.exp((float(out[k]) - float(out[best])) / t) for k in range(9)]
            r = self.rng.random() * sum(w)
            for k in range(9):
                r -= w[k]
                if r <= 0.0:
                    best = k
                    break
        zk = min(max(float(out[9]) + self.net.kick_bias, -60.0), 60.0)
        kick = self.rng.random() < 1.0 / (1.0 + math.exp(-zk)) if t > 0.0 else zk > 0.0
        d = DIRS[best]
        d = complex(d.real * m.attack_dir(p.team), d.imag)
        l = abs(d)
        call = "none"
        if len(out) >= CALL_OUT:
            c = max(range(5), key=lambda k: out[10 + k])
            if t > 0.0:
                w = [math.exp((float(out[10 + k]) - float(out[10 + c])) / t) for k in range(5)]
                r = self.rng.random() * sum(w)
                for k in range(5):
                    r -= w[k]
                    if r <= 0.0:
                        c = k
                        break
            call = INTENTS[c]
        return Act(d / l if l > 0.0 else 0j, kick, call, "")
