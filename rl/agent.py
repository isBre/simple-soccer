"""The net the RL teams train: one shared policy for the 5 players of a team (keeper included), and the helpers around it.
Actor layout = the game-model layout: [n_in, h, h, 10] (9 move logits + 1 kick logit, ReLU), exported as game JSON
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
    def __init__(self, obs_dim=OBS_DIM, hidden=128):
        super().__init__()
        self.sizes = [obs_dim, hidden, hidden, 10]
        self.actor = mlp(self.sizes)
        self.critic = mlp([obs_dim, hidden, hidden, 1])
        with torch.no_grad():
            self.actor[-1].weight.mul_(0.01)
            self.actor[-1].bias.zero_()
            self.actor[-1].bias[9] = -1.0

    def dist(self, obs):
        z = self.actor(obs)
        return Categorical(logits=z[..., :9]), Bernoulli(logits=z[..., 9])

    def act(self, obs):
        dm, dk = self.dist(obs)
        m, k = dm.sample(), dk.sample()
        return m, k, dm.log_prob(m) + dk.log_prob(k)

    def value(self, obs):
        return self.critic(obs).squeeze(-1)

    def to_game_dict(self):
        ws, bs = [], []
        for layer in self.actor:
            if isinstance(layer, nn.Linear):
                ws.append(layer.weight.detach().numpy().astype(np.float32).reshape(-1).tolist())
                bs.append(layer.bias.detach().numpy().astype(np.float32).tolist())
        return {"sizes": self.sizes, "W": ws, "B": bs, "kick_bias": 0.0}


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
