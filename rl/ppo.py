"""PPO (shared policy over the 5 players of a team, keeper included) for simple-soccer 5v5 arena.

The net decides everything, with slot one-hot inputs so roles (keeper / defender / attacker) can emerge.
Actor layout = the game's MLP: [54, h, h, 10] (9 move logits + 1 kick logit, ReLU); exported as game JSON.

Curriculum (STAGES): empty goal with 5 players -> vs a rule-based keeper -> full matches against weak,
average, strong teams (training teams only; 4 teams are held out) -> all teams + self-play snapshots.

  /root/rl-venv/bin/python rl/ppo.py --stages s4_five_empty s5_vs_keeper s6_weak s7_average s8_strong s9_all_selfplay
"""
import argparse
import copy
import json
import os
import subprocess
import time

import numpy as np
import torch
import torch.nn as nn
from torch.distributions import Bernoulli, Categorical

from client import GODOT, ROOT, VecEnv

OUT = os.path.join(ROOT, "out_5v5")
OBS_DIM = 54
OUT_GOAL, OUT_OWN, OUT_TIMEOUT, OUT_CONCEDED, OUT_WIN, OUT_DRAW, OUT_LOSS = 1, 2, 3, 4, 5, 6, 7


def team_pools():
    """Training pools by tier from rl/teams_info.json (written by league_eval.tscn); held-out teams excluded."""
    info = json.load(open(os.path.join(ROOT, "rl", "teams_info.json")))
    pools = {}
    for t in info:
        if not t["held_out"]:
            pools.setdefault(t["tier"], []).append(t["id"])
    return pools


def build_stages():
    P = team_pools()
    weak, avg, strong, elite = (P.get(k, []) for k in ("weak", "average", "strong", "elite"))
    base = {"pitch": "arena", "size": 5, "own_team": "owls", "n_active": 5, "with_keeper": True}
    first_goal = {**base, "spread": 1.0, "ball_speed": 2.0, "max_steps": 750}
    match = {**base, "match_mode": True, "duration": 90.0, "max_steps": 3200}
    # name -> dict(cfg, metric, target, max_updates)
    return {
        "s4_five_empty": dict(cfg={**first_goal, "opp": "none"}, metric="goal", target=0.95, max_updates=400),
        "s5_vs_keeper": dict(cfg={**first_goal, "opp": "keeper"}, metric="goal", target=0.35, max_updates=400),
        "s6_weak": dict(cfg={**match, "opp": ",".join(weak)}, metric="pts", target=2.0, max_updates=1500),
        "s7_average": dict(cfg={**match, "opp": ",".join(weak + avg)}, metric="pts", target=1.8, max_updates=1500),
        "s8_strong": dict(cfg={**match, "opp": ",".join(weak + avg + strong)}, metric="pts", target=1.6, max_updates=1500),
        "s9_all": dict(cfg={**match, "opp": ",".join(weak + avg + strong + elite)},
                       metric="pts", target=99.0, max_updates=1500),
        "s9_all_selfplay": dict(cfg={**match, "opp": ",".join(weak + avg + strong + elite), "selfplay": 0.3},
                                metric="pts", target=99.0, max_updates=3000, selfplay=True),
    }


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
    """Load a checkpoint; if it has fewer input features (49 -> 54), pad the first layers with zeros."""
    sd = torch.load(path)
    for key in ("actor.0.weight", "critic.0.weight"):
        w = sd[key]
        if w.shape[1] < OBS_DIM:
            sd[key] = torch.cat([w, torch.zeros(w.shape[0], OBS_DIM - w.shape[1])], 1)
    agent.load_state_dict(sd)


def save_model(agent, name):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    with open(path, "w") as f:
        json.dump(agent.to_game_dict(), f)
    return path


def league_eval(model_path, games, log):
    """Independent evaluation through the game's own MLBot path (SimBatch, all cores)."""
    t0 = time.time()
    try:
        r = subprocess.run([GODOT, "--headless", "--path", ROOT, "res://rl/league_eval.tscn", "--",
                            "--model", "res://" + os.path.relpath(model_path, ROOT), "--games", str(games)],
                           capture_output=True, text=True, timeout=1800,
                           env={**os.environ, "GODOT_SILENCE_ROOT_WARNING": "1"})
        lines = [l for l in r.stdout.splitlines() if l.startswith("SUMMARY")]
        log("LEAGUE EVAL (%s, %.0fs)" % (os.path.basename(model_path), time.time() - t0))
        for l in lines:
            log("   " + l)
    except Exception as e:  # never kill training because of an evaluation problem
        log("league eval failed: %r" % (e,))


def run_stage(name, S, agent, opt, env, args, log):
    cfg, metric, target, max_updates = S["cfg"], S["metric"], S["target"], S["max_updates"]
    env.configure(cfg, seed=args.seed)
    E, A, D = env.E, env.A, env.D
    T = args.rollout
    match = bool(cfg.get("match_mode"))
    log("== stage %s | envs %d agents/env %d | %s" % (name, E, A, json.dumps(cfg)[:300]))
    obs = torch.from_numpy(env.step(np.zeros((E, A, 2), np.int8))[0].copy())
    recent = []                                  # (outcome, gf, ga) of finished episodes
    snapshots = []
    t_start = time.time()
    best = -1e9
    ent = torch.tensor(0.0)
    for upd in range(1, max_updates + 1):
        if S.get("selfplay") and (upd == 1 or upd % args.snapshot_every == 0):
            snapshots.append(copy.deepcopy(agent.to_game_dict()))
            snapshots = snapshots[-8:]
            env.set_opponent(snapshots[np.random.randint(len(snapshots))])
        elif S.get("selfplay") and upd % 10 == 0:
            env.set_opponent(snapshots[np.random.randint(len(snapshots))])
        b_obs = torch.zeros(T, E, A, D)
        b_m = torch.zeros(T, E, A, dtype=torch.long)
        b_k = torch.zeros(T, E, A)
        b_lp = torch.zeros(T, E, A)
        b_rew = torch.zeros(T, E)
        b_done = torch.zeros(T, E)
        b_val = torch.zeros(T, E, A)
        t0 = time.time()
        torch.set_num_threads(4)                   # rollouts: leave the cores to the simulators
        for t in range(T):
            with torch.no_grad():
                m, k, lp = agent.act(obs)
                v = agent.value(obs)
            actions = torch.stack([m, k.long()], -1).numpy().astype(np.int8)
            nobs, rew, done, outc, epr, gf, ga = env.step(actions)
            b_obs[t], b_m[t], b_k[t], b_lp[t], b_val[t] = obs, m, k, lp, v
            b_rew[t] = torch.from_numpy(rew.copy())
            b_done[t] = torch.from_numpy(done.astype(np.float32))
            for i in np.nonzero(done)[0]:
                recent.append((int(outc[i]), int(gf[i]), int(ga[i])))
            obs = torch.from_numpy(nobs.copy())
        t_sim = time.time() - t0
        recent = recent[-300:]

        with torch.no_grad():
            last_v = agent.value(obs)
        adv = torch.zeros(T, E, A)
        gae = torch.zeros(E, A)
        for t in reversed(range(T)):
            nv = last_v if t == T - 1 else b_val[t + 1]
            nd = (1.0 - b_done[t]).unsqueeze(-1)
            delta = b_rew[t].unsqueeze(-1) + args.gamma * nv * nd - b_val[t]
            gae = delta + args.gamma * args.lam * nd * gae
            adv[t] = gae
        ret = adv + b_val

        f_obs = b_obs.reshape(-1, D)
        f_m, f_k, f_lp = b_m.reshape(-1), b_k.reshape(-1), b_lp.reshape(-1)
        f_adv, f_ret = adv.reshape(-1), ret.reshape(-1)
        f_adv = (f_adv - f_adv.mean()) / (f_adv.std() + 1e-8)
        n = f_obs.shape[0]
        t1 = time.time()
        torch.set_num_threads(16)                  # learning: the simulators are idle
        for _ in range(args.epochs):
            perm = torch.randperm(n)
            for s in range(0, n, args.minibatch):
                idx = perm[s:s + args.minibatch]
                dm, dk = agent.dist(f_obs[idx])
                lp = dm.log_prob(f_m[idx]) + dk.log_prob(f_k[idx])
                ratio = torch.exp(lp - f_lp[idx])
                pg = -torch.min(ratio * f_adv[idx], torch.clamp(ratio, 0.8, 1.2) * f_adv[idx]).mean()
                vl = 0.5 * (agent.value(f_obs[idx]) - f_ret[idx]).pow(2).mean()
                ent = dm.entropy().mean() + dk.entropy().mean()
                loss = pg + 0.5 * vl - args.ent * ent
                opt.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(agent.parameters(), 0.5)
                opt.step()
        t_learn = time.time() - t1

        if match:
            pts = np.mean([3.0 if o == OUT_WIN else (1.0 if o == OUT_DRAW else 0.0) for o, _, _ in recent]) if recent else 0.0
            val = pts
            extra = "pts/m %.2f GF %.2f GA %.2f (last %d eps)" % (
                pts, np.mean([g for _, g, _ in recent]) if recent else 0, np.mean([g for _, _, g in recent]) if recent else 0, len(recent))
        else:
            val = np.mean([o == OUT_GOAL for o, _, _ in recent]) if recent else 0.0
            extra = "goal %.0f%% conceded %.0f%% timeout %.0f%% (last %d eps)" % (
                100 * val, 100 * np.mean([o == OUT_CONCEDED for o, _, _ in recent]) if recent else 0,
                100 * np.mean([o == OUT_TIMEOUT for o, _, _ in recent]) if recent else 0, len(recent))
        if upd % args.log_every == 0 or upd == 1:
            log("%s upd %d | %s | rew/step %.4f | ent %.2f | %.0f dec/s sim %.1fs learn %.1fs | %.0fs" % (
                name, upd, extra, b_rew.mean().item(), ent.item(), T * E / t_sim, t_sim, t_learn, time.time() - t_start))
        enough = len(recent) >= (100 if match else 200)
        warm = upd * T >= 1.5 * cfg["max_steps"]
        if enough and warm and val > best:
            best = val
            save_model(agent, "rl_%s_best.json" % name)
        if upd % 25 == 0:
            save_model(agent, "rl_%s_last.json" % name)
            torch.save(agent.state_dict(), os.path.join(OUT, "rl_agent_%s_last.pt" % name))
        if match and upd % args.eval_every == 0:
            league_eval(save_model(agent, "rl_%s_last.json" % name), args.eval_games, log)
        if enough and warm and val >= target:
            log("== stage %s PASSED: %.3f >= %.2f after %d updates" % (name, val, target, upd))
            break
    else:
        log("== stage %s reached its update cap without hitting %.2f (best %.3f); continuing anyway" % (name, target, best))
    path = save_model(agent, "rl_%s_last.json" % name)
    torch.save(agent.state_dict(), os.path.join(OUT, "rl_agent_after_%s.pt" % name))
    if match:
        league_eval(path, args.eval_games, log)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stages", nargs="+", default=["s4_five_empty", "s5_vs_keeper", "s6_weak", "s7_average", "s8_strong"])
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--envs_per_worker", type=int, default=10)
    ap.add_argument("--rollout", type=int, default=128)
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--minibatch", type=int, default=8192)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--gamma", type=float, default=0.997)
    ap.add_argument("--lam", type=float, default=0.95)
    ap.add_argument("--ent", type=float, default=0.003)
    ap.add_argument("--hidden", type=int, default=128)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--log_every", type=int, default=5)
    ap.add_argument("--snapshot_every", type=int, default=60)
    ap.add_argument("--eval_every", type=int, default=250)
    ap.add_argument("--eval_games", type=int, default=1)
    ap.add_argument("--resume", default=os.path.join(OUT, "rl_agent_after_s3_four_empty.pt"))
    args = ap.parse_args()
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    torch.set_num_threads(16)                     # the simulators are idle while the learner trains
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    logf = open(os.path.join(ROOT, "logs", "ppo.log"), "a")

    def log(msg):
        line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    agent = Agent(hidden=args.hidden)
    if args.resume and os.path.exists(args.resume):
        load_padded(agent, args.resume)
        log("warm start from %s" % args.resume)
    opt = torch.optim.Adam(agent.parameters(), lr=args.lr)
    stages = build_stages()
    env = VecEnv(workers=args.workers, envs_per_worker=args.envs_per_worker)
    try:
        for st in args.stages:
            run_stage(st, stages[st], agent, opt, env, args, log)
    finally:
        env.close()


if __name__ == "__main__":
    main()
