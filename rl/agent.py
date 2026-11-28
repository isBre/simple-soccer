"""The net the RL teams train: one shared policy for all the players of a team, and the helpers around it.
Actor layout = the game-model layout: [n_in, h, h, 10] (9 move logits + 1 kick logit, ReLU), or [n_in, h, h, 15] for a net that
calls (+ 5 call logits, soccer.core.public.INTENTS order; the slots observation), exported as game JSON with its observation's name
(soccer/ai/nets.py plays it). Used by rl/selfplay.py (training) and rl/distill.py (copying a net into a new observation)."""
import json
import os

import numpy as np
import torch
import torch.nn as nn
from torch.distributions import Bernoulli, Categorical

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out_5v5")
OBS_DIM = 54
OUT_GOAL, OUT_OWN, OUT_TIMEOUT, OUT_CONCEDED, OUT_WIN, OUT_DRAW, OUT_LOSS = 1, 2, 3, 4, 5, 6, 7   # episode outcomes (rl/env.py)


def team_pools():
    """Training pools by tier from rl/teams_info.json (written by rl/evaluate.py league_eval); held-out teams excluded."""
    info = json.load(open(os.path.join(ROOT, "rl", "teams_info.json")))
    pools = {}
    for t in info:
        if not t["held_out"]:
            pools.setdefault(t["tier"], []).append(t["id"])
    return pools


def mlp(sizes):
    layers = []
    for i in range(len(sizes) - 1):
        layers.append(nn.Linear(sizes[i], sizes[i + 1]))
        if i < len(sizes) - 2:
            layers.append(nn.ReLU())
    return nn.Sequential(*layers)


class Agent(nn.Module):
    def __init__(self, obs_dim=OBS_DIM, hidden=128, calls=False, obs_name=""):
        super().__init__()
        self.calls, self.obs_name = calls, obs_name
        self.sizes = [obs_dim, hidden, hidden, 15 if calls else 10]
        self.actor = mlp(self.sizes)
        self.critic = mlp([obs_dim, hidden, hidden, 1])
        with torch.no_grad():
            self.actor[-1].weight.mul_(0.01)
            self.actor[-1].bias.zero_()
            self.actor[-1].bias[9] = -1.0

    def dist(self, obs):
        """(move, kick, call) distributions; call is None for a net that does not call."""
        return dists(self.actor(obs))

    def act(self, obs):
        """(move, kick, call, log-probability); call is zeros (the "none" call) for a net that does not call."""
        dm, dk, dc = self.dist(obs)
        m, k = dm.sample(), dk.sample()
        lp = dm.log_prob(m) + dk.log_prob(k)
        if dc is None:
            return m, k, torch.zeros_like(m), lp
        c = dc.sample()
        return m, k, c, lp + dc.log_prob(c)

    def value(self, obs):
        return self.critic(obs).squeeze(-1)

    def to_game_dict(self):
        ws, bs = [], []
        for layer in self.actor:
            if isinstance(layer, nn.Linear):
                ws.append(layer.weight.detach().numpy().astype(np.float32).reshape(-1).tolist())
                bs.append(layer.bias.detach().numpy().astype(np.float32).tolist())
        d = {"sizes": self.sizes, "W": ws, "B": bs, "kick_bias": 0.0}
        if self.obs_name:
            d["obs"] = self.obs_name
        return d


def dists(z):
    """The distributions of an actor's output z: move (9 logits), kick (1), call (5, when z has 15 columns; else None)."""
    return Categorical(logits=z[..., :9]), Bernoulli(logits=z[..., 9]), (Categorical(logits=z[..., 10:15]) if z.shape[-1] >= 15 else None)


def load_padded(agent, path):
    """Load a checkpoint; if it has fewer input features than the agent (49 -> 54), pad the first layers with zeros."""
    sd = torch.load(path)
    obs_dim = agent.sizes[0]
    for key in ("actor.0.weight", "critic.0.weight"):
        w = sd[key]
        if w.shape[1] < obs_dim:
            sd[key] = torch.cat([w, torch.zeros(w.shape[0], obs_dim - w.shape[1])], 1)
    agent.load_state_dict(sd)


def save_model(agent, name):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    with open(path, "w") as f:
        json.dump(agent.to_game_dict(), f)
    return path
