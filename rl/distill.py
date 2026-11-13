"""Copies an old net into a net with a different observation (imitation, "distillation"), so a new run does not start from nothing.

The teacher (54-number ego observation with a player slot) plays full matches against the rule-based teams; the environment returns
BOTH observations of every state ("obs": "both"). The student (46-number role-free team observation) is trained to reproduce the
teacher's move distribution, kick probability and value estimate on those states. It is a warm start, not a perfect copy: the
teacher knew which player it controlled, the student has to tell from the situation. The agreement it reaches is printed.

After a first fit on the teacher's own states, DAgger rounds (--rounds): the STUDENT plays, the teacher labels the states the student
really reaches, they are added to the data and the student is trained further. This fixes the usual problem of plain imitation (a student
that drifts into states the teacher never visited and plays much worse than its agreement suggests).

  python3 rl/distill.py --teacher out_5v5/ckpt/jit8_best.pt --out team46_start --steps 700 --rounds 3
"""
import argparse
import os
import time

import numpy as np
import torch
import torch.nn.functional as F

from client import VecEnv
from ppo import Agent, load_padded, save_model, team_pools, OUT

N_TEAM, N_LEGACY = 46, 54


def new_env(args):
    P = team_pools()
    cfg = {"pitch": "arena", "size": 5, "own_team": "owls", "n_active": 5, "with_keeper": True, "match_mode": True, "duration": 90.0,
           "max_steps": 3200, "opp": ",".join(P["weak"] + P["average"] + P["strong"] + P["elite"]), "random_start": 0.6, "obs": "both"}
    env = VecEnv(workers=args.workers, envs_per_worker=args.envs_per_worker, base_port=7800, log_path="logs/rl_workers_distill.log")
    env.configure(cfg, seed=args.seed)
    return env


def sample(net_actor, x):
    z = net_actor(x)
    move = torch.distributions.Categorical(logits=z[..., :9]).sample()
    kick = torch.distributions.Bernoulli(logits=z[..., 9]).sample()
    return move, kick


def collect(env, teacher, student, student_share, steps):
    """Plays `steps` environment steps; a fraction `student_share` of the matches is played by the student, the rest by the teacher.
    Returns the student's observation, the teacher's logits and the teacher's value for every state reached."""
    E = env.E
    acts_student = torch.rand(E) < student_share
    obs = torch.from_numpy(env.step(np.zeros((E, 5, 2), np.int8))[0].copy())
    s_obs, t_logits, t_val = [], [], []
    t0 = time.time()
    for step in range(steps):
        t_in, s_in = obs[..., N_TEAM:], obs[..., :N_TEAM]
        with torch.no_grad():
            z = teacher.actor(t_in)
            v = teacher.value(t_in)
            tm, tk = sample(teacher.actor, t_in)
            if student is not None and acts_student.any():
                sm, sk = sample(student.actor, s_in)
                move = torch.where(acts_student[:, None], sm, tm)
                kick = torch.where(acts_student[:, None], sk, tk)
            else:
                move, kick = tm, tk
        s_obs.append(s_in.reshape(-1, N_TEAM))
        t_logits.append(z.reshape(-1, 10))
        t_val.append(v.reshape(-1))
        obs = torch.from_numpy(env.step(torch.stack([move, kick.long()], -1).numpy().astype(np.int8))[0].copy())
        if step % 200 == 0:
            print("  collected %d / %d steps (%.0fs)" % (step, steps, time.time() - t0), flush=True)
    return torch.cat(s_obs), torch.cat(t_logits), torch.cat(t_val)


def fit(student, opt, X, Z, V, epochs, label):
    n = X.shape[0]
    perm = torch.randperm(n)
    cut = int(n * 0.9)
    tr, va = perm[:cut], perm[cut:]

    def losses(idx):
        z = student.actor(X[idx])
        t = Z[idx]
        kl = F.kl_div(F.log_softmax(z[:, :9], -1), F.softmax(t[:, :9], -1), reduction="batchmean")
        kick = F.binary_cross_entropy_with_logits(z[:, 9], torch.sigmoid(t[:, 9]))
        val = F.mse_loss(student.value(X[idx]), V[idx])
        return kl, kick, val, z, t

    for ep in range(epochs):
        p = tr[torch.randperm(len(tr))]
        for s in range(0, len(p), 4096):
            idx = p[s:s + 4096]
            kl, kick, val, _, _ = losses(idx)
            loss = kl + kick + 0.5 * val
            opt.zero_grad()
            loss.backward()
            opt.step()
    with torch.no_grad():
        kl, kick, val, z, t = losses(va)
        agree = (z[:, :9].argmax(-1) == t[:, :9].argmax(-1)).float().mean().item()
        kick_acc = ((z[:, 9] > 0) == (t[:, 9] > 0)).float().mean().item()
        ev = 1.0 - float((student.value(X[va]) - V[va]).var() / (V[va].var() + 1e-8))
    print("%s | %d samples | validation: move agreement %.0f%%  KL %.3f | kick agreement %.0f%% | value explained variance %.2f" % (
        label, n, 100 * agree, kl.item(), 100 * kick_acc, ev), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teacher", required=True, help="teacher checkpoint (.pt, 54-number observation)")
    ap.add_argument("--out", default="team46_start", help="name of the student in out_5v5/ (.pt and game-model .json)")
    ap.add_argument("--steps", type=int, default=700, help="environment steps to collect per round (x envs x 5 players samples)")
    ap.add_argument("--rounds", type=int, default=3, help="DAgger rounds after the first fit")
    ap.add_argument("--student_share", type=float, default=0.8, help="share of the matches played by the student in a DAgger round")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--envs_per_worker", type=int, default=16)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()
    torch.manual_seed(args.seed)
    teacher = Agent(N_LEGACY)
    load_padded(teacher, args.teacher)
    student = Agent(N_TEAM)
    opt = torch.optim.Adam(student.parameters(), lr=args.lr)
    env = new_env(args)
    try:
        X, Z, V = collect(env, teacher, None, 0.0, args.steps)
        fit(student, opt, X, Z, V, args.epochs, "round 0 (teacher plays)")
        for r in range(1, args.rounds + 1):
            x, z, v = collect(env, teacher, student, args.student_share, args.steps)
            X, Z, V = torch.cat([X, x]), torch.cat([Z, z]), torch.cat([V, v])
            fit(student, opt, X, Z, V, args.epochs // 2, "round %d (student plays, teacher labels)" % r)
    finally:
        env.close()
    os.makedirs(OUT, exist_ok=True)
    torch.save(student.state_dict(), os.path.join(OUT, args.out + ".pt"))
    print("saved", save_model(student, args.out + ".json"), flush=True)


if __name__ == "__main__":
    main()
