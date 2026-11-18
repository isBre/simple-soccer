"""Self-play + league fine-tuning of the 5v5 RL net, with human-likeness rewards.

Two groups of env workers run side by side and feed ONE learner (shared policy over the 5 players of team 0):
  * rule group : team 1 = the rule-based teams (training pool only, 4 teams are held out)
  * self group : team 1 = the net itself, driven from Python (all 5 players, keeper included). Opponent slots:
                 slot 0 = the frozen shipped model (benchmark: the log shows how the learner scores against it),
                 other slots = past snapshots of the learner (resampled every few updates).
Extra reward terms (per player) push towards human-like play: completed progressive passes are paid, key passes
(a pass whose receiver shoots) and the xA of those shots are paid, failed passes cost, teammates should not bunch up ("storm"), and kick must only be pressed when the ball is in reach.

  /root/rl-venv/bin/python rl/selfplay.py --updates 1500
"""
import argparse
import copy
import json
import os
import subprocess
import sys
import time
from collections import deque

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.distributions import Bernoulli, Categorical

from client import ROOT, VecEnv
from ppo import Agent, OUT, OUT_DRAW, OUT_LOSS, OUT_WIN, load_padded, save_model, team_pools

CKPT = os.path.join(OUT, "ckpt")
OBS_DIMS = {"legacy": 54, "team": 46}            # observation layouts (see soccer/ai/nets.py features_team): ego with player slot / role-free team observation


N_TEAM, N_LEGACY = 46, 54                       # env obs "both" = the team observation followed by the legacy one


def load_net(path):
    """An Agent from a torch checkpoint (.pt) or a game-model JSON (sizes, W, B), whatever its input size and width."""
    if path.endswith(".json"):
        d = json.load(open(path))
        a = Agent(d["sizes"][0], d["sizes"][1])
        with torch.no_grad():
            for lin, w, b in zip([l for l in a.actor if isinstance(l, nn.Linear)], d["W"], d["B"]):
                lin.weight.copy_(torch.tensor(w, dtype=torch.float32).view(lin.weight.shape))
                lin.bias.copy_(torch.tensor(b, dtype=torch.float32))
        return a
    sd = torch.load(path)
    a = Agent(sd["actor.0.weight"].shape[1], sd["actor.0.weight"].shape[0])
    a.load_state_dict(sd)
    return a


def obs_cols(in_dim):
    """Columns of the 'both' observation a net with this input size reads."""
    return slice(0, N_TEAM) if in_dim == N_TEAM else slice(N_TEAM, N_TEAM + N_LEGACY)


def pts(o):
    return 3.0 if o == OUT_WIN else (1.0 if o == OUT_DRAW else 0.0)


def make_cfgs(args):
    P = team_pools()
    pool = ",".join(P["weak"] + P["average"] + P["strong"] + P["elite"])
    base = {"pitch": "arena", "size": 5, "own_team": "owls", "n_active": 5, "with_keeper": True,
            "match_mode": True, "duration": 90.0, "max_steps": 3200,
            "w_pass_prog": args.w_pass_prog, "w_pass_ok": args.w_pass_ok, "w_pass_fail": args.w_pass_fail,
            "pass_individual": bool(args.pass_individual), "w_recv": args.w_recv, "w_open": args.w_open, "w_key_pass": args.w_key_pass, "w_xa": args.w_xa, "w_space": args.w_space, "space_radius": args.space_radius, "w_kick": args.w_kick, "coop_cap": args.coop_cap, "random_start": args.random_start, "w_keeper": args.w_keeper, "w_jitter": args.w_jitter, "keeper_free": args.keeper_free,
            "obs": args.obs, "shaping": args.shaping, "w_far": args.w_far, "far_radius": args.far_radius, "w_wall": args.w_wall, "w_corner": args.w_corner,
            "w_xg": args.w_xg, "xg_cap": args.xg_cap, "w_xga": args.w_xga, "w_win": args.w_win, "w_draw": args.w_draw, "w_tackle": args.w_tackle, "def_cap": args.def_cap,
            "w_goalside": args.w_goalside, "goalside_lane": args.goalside_lane, "w_opp_half": args.w_opp_half, "w_compact": args.w_compact,
            "compact_len": args.compact_len, "compact_wid": args.compact_wid}
    return {**base, "opp": pool}, {**base, "opp": "owls", "opp_external": True}


def eval_blocking(model_path, tag, args, log, mode="full"):
    """Complete evaluation of a snapshot (rl/eval_checkpoint.py: league, behaviour, head to head, ...) while training is PAUSED:
    this call returns when it is done, the env workers just wait, so the evaluation gets the whole CPU (the viewer shows an
    "evaluation running" banner meanwhile). Result: logs/sp_eval/<tag>.txt"""
    suffix = "_fast" if mode == "fast" else ""
    out = os.path.join(ROOT, "logs", "sp_eval", tag + suffix + ".txt")
    cmd = [sys.executable, os.path.join(ROOT, "rl", "eval_checkpoint.py"), "--model", model_path, "--out", out, "--paused", "--mode", mode,
           "--games", str(args.eval_games), "--duration", str(args.eval_duration), "--h2h_games", str(args.eval_h2h_games)]
    if args.fast_ref:
        cmd += ["--ref", "start=" + args.fast_ref]                  # head to head against the net this run started from
    log("training paused: %s evaluation of %s (logs/sp_eval/%s%s.txt)" % (mode, tag, tag, suffix))
    t0 = time.time()
    subprocess.run(cmd, cwd=os.path.join(ROOT, "rl"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log("evaluation of %s finished in %.0f min, training continues" % (tag, (time.time() - t0) / 60.0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--updates", type=int, default=1500, help="final update number (absolute: with --start_update 200 and --updates 3000 it trains updates 201..3000)")
    ap.add_argument("--obs", choices=list(OBS_DIMS), default="team", help="observation layout: team = 46 numbers, no player ID (default); legacy = 54 numbers with the slot (the first RL teams)")
    ap.add_argument("--start_update", type=int, default=0, help="continue numbering from a restart: the checkpoint --start was saved at this update")
    ap.add_argument("--workers_rule", type=int, default=8)
    ap.add_argument("--workers_self", type=int, default=8)
    ap.add_argument("--envs_per_worker", type=int, default=10)
    ap.add_argument("--rollout", type=int, default=128)
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--minibatch", type=int, default=8192)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--gamma", type=float, default=0.997)
    ap.add_argument("--lam", type=float, default=0.95)
    ap.add_argument("--ent", type=float, default=0.003)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--start", default=os.path.join(OUT, "rl_agent_after_s9_all.pt"))
    ap.add_argument("--baseline", default="", help="frozen benchmark opponent (.pt); default = --start")
    ap.add_argument("--w_pass_prog", type=float, default=0.3)
    ap.add_argument("--w_pass_ok", type=float, default=0.05)
    ap.add_argument("--w_pass_fail", type=float, default=0.08)
    ap.add_argument("--pass_individual", type=int, default=0, help="1: pass rewards go to the passer / receiver, not the whole team")
    ap.add_argument("--w_recv", type=float, default=0.0)
    ap.add_argument("--w_open", type=float, default=0.0)
    ap.add_argument("--w_key_pass", type=float, default=0.0)
    ap.add_argument("--w_xa", type=float, default=0.0)
    ap.add_argument("--w_space", type=float, default=0.006)
    ap.add_argument("--space_radius", type=float, default=140.0)
    ap.add_argument("--w_kick", type=float, default=0.01)
    ap.add_argument("--random_start", type=float, default=0.0, help="fraction of episodes that start from a fully random layout instead of a kickoff")
    ap.add_argument("--coop_cap", type=float, default=0.0, help="max cooperation reward per episode (anti reward-farming)")
    ap.add_argument("--w_jitter", type=float, default=0.0)
    ap.add_argument("--w_keeper", type=float, default=0.0)
    ap.add_argument("--shaping", type=float, default=1.0, help="weight of the ball shaping (ball towards the goal, teammate towards the ball); 0 = off")
    ap.add_argument("--w_corner", type=float, default=0.0, help="penalty per decision while our team put the ball in a corner (last touch ours)")
    ap.add_argument("--w_wall", type=float, default=0.0, help="penalty per decision for a player pressed against the outer wall for 2+ decisions in a row")
    ap.add_argument("--w_far", type=float, default=0.0, help="penalty for an outfield player further than --far_radius px from the ball (the arena is 1280 x 600; full penalty at twice the radius)")
    ap.add_argument("--far_radius", type=float, default=600.0)
    ap.add_argument("--w_xg", type=float, default=0.0, help="reward per expected goal (xG) of the player's own shots (shot quality), at most --xg_cap per match")
    ap.add_argument("--xg_cap", type=float, default=6.0)
    ap.add_argument("--w_xga", type=float, default=0.0, help="team penalty per xG of the opponent's shots")
    ap.add_argument("--w_win", type=float, default=0.0, help="team bonus at the end of a won match")
    ap.add_argument("--w_draw", type=float, default=0.0, help="team bonus at the end of a drawn match")
    ap.add_argument("--w_tackle", type=float, default=0.0, help="reward per tackle or interception, at most --def_cap per match")
    ap.add_argument("--def_cap", type=float, default=2.0)
    ap.add_argument("--w_goalside", type=float, default=0.0, help="per decision: outfield player between the ball and its own goal while the opponent has the ball")
    ap.add_argument("--goalside_lane", type=float, default=120.0)
    ap.add_argument("--w_opp_half", type=float, default=0.0, help="team penalty per decision while the opponent has the ball in our half")
    ap.add_argument("--w_compact", type=float, default=0.0, help="team penalty per decision when the outfield players are stretched beyond --compact_len / --compact_wid px")
    ap.add_argument("--compact_len", type=float, default=700.0)
    ap.add_argument("--compact_wid", type=float, default=450.0)
    ap.add_argument("--keeper_free", type=float, default=350.0)
    ap.add_argument("--snapshot_every", type=int, default=40)
    ap.add_argument("--resample_every", type=int, default=20)
    ap.add_argument("--ckpt_every", type=int, default=100)
    ap.add_argument("--eval_every", type=int, default=100, help="complete evaluation of the checkpoint every N updates (multiple of --ckpt_every; 0 = never); training is paused meanwhile")
    ap.add_argument("--fast_every", type=int, default=0, help="FAST check (16 short matches + head to head vs --fast_ref) every N updates, training paused; 0 = never")
    ap.add_argument("--fast_ref", default="", help="game-model JSON of the net the run started from (the fast check plays it head to head)")
    ap.add_argument("--learn_threads", type=int, default=2, help="torch threads of the learning step (all 4 would fight the env workers for the CPU: the Pi froze)")
    ap.add_argument("--base_port", type=int, default=7100, help="first port of the rule-group workers (self-play group: +100)")
    ap.add_argument("--hidden", type=int, default=128, help="width of the two hidden layers (must match --start)")
    ap.add_argument("--teacher", default="", help="kickstarting: a checkpoint (.pt/.json, e.g. the 54-input jit8) whose moves the learner is pulled towards")
    ap.add_argument("--kl_coef", type=float, default=0.0, help="weight of KL(teacher || learner) in the loss at update 0, decaying linearly")
    ap.add_argument("--kl_decay", type=int, default=300, help="update at which the teacher term reaches 0")
    ap.add_argument("--opp_models", default="", help="comma-separated strong opponents for the self-play group (.pt or game-model .json, 46 or 54 inputs)")
    ap.add_argument("--pfsp", type=float, default=0.5, help="share of the self-play slots 1-3 given to --opp_models, each picked more often the more it wins (PFSP)")
    ap.add_argument("--eval_games", type=int, default=1, help="league games per team and side (1 = 32 matches)")
    ap.add_argument("--eval_duration", type=float, default=90.0, help="seconds per evaluation match")
    ap.add_argument("--eval_h2h_games", type=int, default=8, help="head-to-head games per side against each reference net")
    ap.add_argument("--log_every", type=int, default=5)
    ap.add_argument("--tag", default="sp")
    args = ap.parse_args()
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    obs_dim = OBS_DIMS[args.obs]
    strong = [(os.path.splitext(os.path.basename(p))[0], load_net(os.path.join(ROOT, p) if not os.path.isabs(p) else p).actor)
              for p in args.opp_models.split(",") if p]
    teacher = load_net(args.teacher if os.path.isabs(args.teacher) else os.path.join(ROOT, args.teacher)) if args.teacher else None
    both = teacher is not None or any(n[0].in_features == N_LEGACY for _, n in strong)
    assert not both or args.obs == "team", "a teacher / 54-input opponents need --obs team"
    env_obs = "both" if both else args.obs
    D_env = N_TEAM + N_LEGACY if both else obs_dim
    L = slice(0, obs_dim)                                           # the learner's columns of the environment observation
    for _, n in strong:
        for p in n.parameters():
            p.requires_grad_(False)
    if teacher is not None:
        for p in teacher.parameters():
            p.requires_grad_(False)
    config = {**vars(args), "obs_dim": obs_dim, "started": int(time.time())}
    with open(os.path.join(ROOT, "logs", args.tag + "_config.json"), "w") as f:        # read by the live viewer's SETUP page
        json.dump(config, f, indent=1)
    with open(os.path.join(ROOT, "logs", args.tag + "_config_history.jsonl"), "a") as f:   # every (re)start: what changed shows on the RECAP page
        f.write(json.dumps(config) + "\n")

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    os.makedirs(CKPT, exist_ok=True)
    logf = open(os.path.join(ROOT, "logs", "selfplay.log"), "a")

    def log(msg):
        line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    agent = Agent(obs_dim, args.hidden)
    load_padded(agent, args.start)
    opt = torch.optim.Adam(agent.parameters(), lr=args.lr)
    baseline = load_net(args.baseline or args.start)
    assert baseline.sizes[0] == obs_dim, "the frozen benchmark must read the learner's observation"
    for p in baseline.parameters():
        p.requires_grad_(False)
    pool = [copy.deepcopy(baseline.actor.state_dict())]           # opponent pool: baseline first, then snapshots
    warm = 30                                                      # lr warm-up (updates) for a fresh optimizer
    state_path = args.start[:-3] + ".train_state" if args.start.endswith(".pt") else ""
    if args.start_update > 0 and state_path and os.path.exists(state_path):     # faithful resume: same Adam moments and opponent pool
        saved = torch.load(state_path, weights_only=False)
        opt.load_state_dict(saved["opt"])
        pool = [pool[0]] + saved.get("pool", [])[1:]
        warm = 0
    NSLOT = 4
    snap_nets = [Agent(obs_dim, args.hidden).actor for _ in range(NSLOT)]     # learner snapshots (slots 1-3)
    for n in snap_nets:
        for p in n.parameters():
            p.requires_grad_(False)
    slot_net, slot_cols, slot_name = [baseline.actor] * NSLOT, [L] * NSLOT, ["bench"] * NSLOT
    strong_res = {name: deque(maxlen=60) for name, _ in strong}

    def pfsp_pick():
        w = np.array([(1.0 - (np.mean(strong_res[n]) / 3.0 if strong_res[n] else 0.5)) ** 2 + 0.05 for n, _ in strong])
        return strong[np.random.choice(len(strong), p=w / w.sum())]

    def assign_slots():
        slot_net[0], slot_cols[0], slot_name[0] = baseline.actor, L, "bench"      # slot 0 is always the frozen benchmark
        for k in range(1, NSLOT):
            if strong and np.random.rand() < args.pfsp:
                name, net = pfsp_pick()
                slot_net[k], slot_cols[k], slot_name[k] = net, obs_cols(net[0].in_features), "strong:" + name
            else:
                snap_nets[k].load_state_dict(pool[np.random.randint(len(pool))])
                slot_net[k], slot_cols[k], slot_name[k] = snap_nets[k], L, "league"

    assign_slots()

    cfg_rule, cfg_self = make_cfgs(args)
    cfg_rule["obs"] = cfg_self["obs"] = env_obs
    er = VecEnv(workers=args.workers_rule, envs_per_worker=args.envs_per_worker, base_port=args.base_port, log_path="logs/rl_workers_rule.log")
    es = VecEnv(workers=args.workers_self, envs_per_worker=args.envs_per_worker, base_port=args.base_port + 100, log_path="logs/rl_workers_self.log")
    try:
        er.configure(cfg_rule, seed=args.seed)
        es.configure(cfg_self, seed=args.seed + 1)
        Er, Es = er.E, es.E
        E, A, D, T = Er + Es, 5, D_env, args.rollout
        slot_of = np.arange(Es) * NSLOT // Es                      # envs of the self group -> opponent slot
        log("selfplay start | rule envs %d, self envs %d (opp slots %d, slot 0 = frozen benchmark) | lr %g | rewards pass %.2f/%.2f/-%.2f space %.3f kick %.3f" % (
            Er, Es, NSLOT, args.lr, args.w_pass_prog, args.w_pass_ok, args.w_pass_fail, args.w_space, args.w_kick))

        obs_r = torch.from_numpy(er.step(np.zeros((Er, 5, 2), np.int8))[0].copy())
        obs_s = torch.from_numpy(es.step(np.zeros((Es, 10, 2), np.int8))[0].copy())
        stats = {"rule": deque(maxlen=200), "bench": deque(maxlen=120), "league": deque(maxlen=200)}
        t_start = time.time()
        ent = torch.tensor(0.0)
        for upd in range(args.start_update + 1, args.updates + 1):
            for g in opt.param_groups:                     # warm-up: a fresh Adam must not shake a converged policy
                g["lr"] = args.lr * (min(1.0, (upd - args.start_update) / warm) if warm else 1.0)
            if upd % args.snapshot_every == 0:
                pool.append(copy.deepcopy(agent.actor.state_dict()))
                pool = [pool[0]] + pool[1:][-8:]
            if upd == args.start_update + 1 or upd % args.resample_every == 0:
                assign_slots()
            b_obs = torch.zeros(T, E, A, D)
            b_m = torch.zeros(T, E, A, dtype=torch.long)
            b_k = torch.zeros(T, E, A)
            b_lp = torch.zeros(T, E, A)
            b_rew = torch.zeros(T, E, A)
            b_done = torch.zeros(T, E)
            b_val = torch.zeros(T, E, A)
            t0 = time.time()
            torch.set_num_threads(1)                      # tiny batches: extra threads only steal CPU from the env workers
            for t in range(T):
                obs_L = torch.cat([obs_r, obs_s[:, :5]], 0)                    # [E, 5, D] learner observations
                with torch.no_grad():
                    mr_, kr_, lpr_ = agent.act(obs_r[..., L])
                    vr_ = agent.value(obs_r[..., L])
                er.step_async(np.stack([mr_.numpy(), kr_.long().numpy()], -1).astype(np.int8))   # rule workers simulate while we infer the self group
                with torch.no_grad():
                    ms_, ks_, lps_ = agent.act(obs_s[:, :5, L])
                    vs_ = agent.value(obs_s[:, :5, L])
                    om = torch.zeros(Es, 5, dtype=torch.long)
                    ok = torch.zeros(Es, 5)
                    for sl in range(NSLOT):
                        idx = np.nonzero(slot_of == sl)[0]
                        z = slot_net[sl](obs_s[idx, 5:][..., slot_cols[sl]])
                        dm = torch.distributions.Categorical(logits=z[..., :9])
                        om[idx] = dm.sample()
                        ok[idx] = torch.distributions.Bernoulli(logits=z[..., 9]).sample()
                m, k, lp, v = (torch.cat([x, y], 0) for x, y in ((mr_, ms_), (kr_, ks_), (lpr_, lps_), (vr_, vs_)))
                act_s = torch.zeros(Es, 10, 2, dtype=torch.long)
                act_s[:, :5, 0], act_s[:, :5, 1] = ms_, ks_.long()
                act_s[:, 5:, 0], act_s[:, 5:, 1] = om, ok.long()
                es.step_async(act_s.numpy().astype(np.int8))
                nr = er.step_wait()
                ns = es.step_wait()
                b_obs[t], b_m[t], b_k[t], b_lp[t], b_val[t] = obs_L, m, k, lp, v
                b_rew[t] = torch.from_numpy(np.concatenate([nr[1][:, :5], ns[1][:, :5]], 0).copy())
                dn = np.concatenate([nr[2], ns[2]])
                b_done[t] = torch.from_numpy(dn.astype(np.float32))
                for i in np.nonzero(nr[2])[0]:
                    stats["rule"].append(pts(int(nr[3][i])))
                for i in np.nonzero(ns[2])[0]:
                    p_ = pts(int(ns[3][i]))
                    who = slot_name[slot_of[i]]
                    if who.startswith("strong:"):
                        strong_res[who[7:]].append(p_)
                    else:
                        (stats["bench"] if who == "bench" else stats["league"]).append(p_)
                obs_r = torch.from_numpy(nr[0].copy())
                obs_s = torch.from_numpy(ns[0].copy())
            t_sim = time.time() - t0
            sums, n_steps = {}, 0
            for venv in (er, es):                               # what the reward was made of in this update (shown by the viewer's INSIGHT page)
                got, n = venv.terms()
                n_steps += n
                for k, v in got.items():
                    sums[k] = sums.get(k, 0.0) + v
            if n_steps:
                with open(os.path.join(ROOT, "logs", args.tag + "_terms.jsonl"), "a") as tf:
                    tf.write(json.dumps({"upd": upd, "terms": {k: v / n_steps for k, v in sums.items()}}) + "\n")

            with torch.no_grad():
                last_v = agent.value(torch.cat([obs_r, obs_s[:, :5]], 0)[..., L])
            adv = torch.zeros(T, E, A)
            gae = torch.zeros(E, A)
            for t in reversed(range(T)):
                nv = last_v if t == T - 1 else b_val[t + 1]
                nd = (1.0 - b_done[t]).unsqueeze(-1)
                delta = b_rew[t] + args.gamma * nv * nd - b_val[t]
                gae = delta + args.gamma * args.lam * nd * gae
                adv[t] = gae
            ret = adv + b_val
            f_obs = b_obs.reshape(-1, D)
            f_m, f_k, f_lp = b_m.reshape(-1), b_k.reshape(-1), b_lp.reshape(-1)
            f_adv, f_ret = adv.reshape(-1), ret.reshape(-1)
            f_adv = (f_adv - f_adv.mean()) / (f_adv.std() + 1e-8)
            n = f_obs.shape[0]
            t1 = time.time()
            torch.set_num_threads(args.learn_threads)
            f_val = b_val.reshape(-1)
            health = {"kl": [], "clipfrac": [], "vloss": [], "pg": [], "gradnorm": [], "ent_move": [], "ent_kick": [], "kl_teacher": []}
            kl_w = args.kl_coef * max(0.0, 1.0 - upd / max(args.kl_decay, 1)) if teacher is not None else 0.0
            ev = 1.0 - float((f_ret - f_val).var() / (f_ret.var() + 1e-8))      # explained variance of the critic (before this update)
            for _ in range(args.epochs):
                perm = torch.randperm(n)
                for s in range(0, n, args.minibatch):
                    idx = perm[s:s + args.minibatch]
                    x = f_obs[idx]
                    z = agent.actor(x[:, L])
                    dm, dk = Categorical(logits=z[:, :9]), Bernoulli(logits=z[:, 9])
                    lp = dm.log_prob(f_m[idx]) + dk.log_prob(f_k[idx])
                    ratio = torch.exp(lp - f_lp[idx])
                    pg = -torch.min(ratio * f_adv[idx], torch.clamp(ratio, 0.8, 1.2) * f_adv[idx]).mean()
                    vl = 0.5 * (agent.value(x[:, L]) - f_ret[idx]).pow(2).mean()
                    ent = dm.entropy().mean() + dk.entropy().mean()
                    loss = pg + 0.5 * vl - args.ent * ent
                    if teacher is not None:                         # kickstarting: stay close to the teacher's moves (weight decays to 0)
                        with torch.no_grad():
                            zt = teacher.actor(x[:, N_TEAM:N_TEAM + N_LEGACY])
                        klt = (F.softmax(zt[:, :9], -1) * (F.log_softmax(zt[:, :9], -1) - F.log_softmax(z[:, :9], -1))).sum(-1).mean()
                        pt, ps = torch.sigmoid(zt[:, 9]), torch.sigmoid(z[:, 9]).clamp(1e-6, 1 - 1e-6)
                        klt = klt + (pt * (torch.log(pt.clamp(1e-6)) - torch.log(ps)) + (1 - pt) * (torch.log((1 - pt).clamp(1e-6)) - torch.log(1 - ps))).mean()
                        health["kl_teacher"].append(float(klt))
                        if kl_w > 0:
                            loss = loss + kl_w * klt
                    opt.zero_grad()
                    loss.backward()
                    gn = nn.utils.clip_grad_norm_(agent.parameters(), 0.5)
                    opt.step()
                    health["kl"].append(float((f_lp[idx] - lp).mean()))                  # approx KL(old || new)
                    health["clipfrac"].append(float(((ratio - 1.0).abs() > 0.2).float().mean()))
                    health["vloss"].append(float(vl))
                    health["pg"].append(float(pg))
                    health["gradnorm"].append(float(gn))
                    health["ent_move"].append(float(dm.entropy().mean()))
                    health["ent_kick"].append(float(dk.entropy().mean()))
            t_learn = time.time() - t1
            with open(os.path.join(ROOT, "logs", args.tag + "_ppo.jsonl"), "a") as pf:      # PPO health, shown by the viewer's TRAINING page
                pf.write(json.dumps({"upd": upd, "ev": ev, "kl_w": kl_w, **{k: float(np.mean(v)) for k, v in health.items() if v}}) + "\n")

            if upd % args.log_every == 0 or upd == args.start_update + 1:
                f = lambda d: ("%.2f(%d)" % (np.mean(d), len(d))) if d else "-"
                log("sp upd %d | pts/m vs rules %s | vs frozen benchmark %s | vs league %s | rew/step %.4f | ent %.2f | pool %d | "
                    "%.0f dec/s sim %.1fs learn %.1fs | %.0fs" % (upd, f(stats["rule"]), f(stats["bench"]), f(stats["league"]),
                                                              b_rew.mean().item(), ent.item(), len(pool), 2 * T * Er / t_sim,
                                                              t_sim, t_learn, time.time() - t_start))
            if strong and upd % (args.log_every * 5) == 0:
                log("strong opponents (pts/match, last 60): " + ", ".join("%s %s" % (n, ("%.2f(%d)" % (np.mean(r), len(r))) if r else "-") for n, r in strong_res.items()))
            if upd % args.ckpt_every == 0:
                path = os.path.join(CKPT, "%s_u%d.json" % (args.tag, upd))
                with open(path, "w") as fh:
                    json.dump(agent.to_game_dict(), fh)
                torch.save(agent.state_dict(), os.path.join(CKPT, "%s_u%d.pt" % (args.tag, upd)))
                torch.save({"opt": opt.state_dict(), "pool": pool}, os.path.join(CKPT, "%s_u%d.train_state" % (args.tag, upd)))  # for a faithful resume
                if args.eval_every > 0 and upd % args.eval_every == 0:
                    eval_blocking(path, "%s_u%d" % (args.tag, upd), args, log)
                elif args.fast_every > 0 and upd % args.fast_every == 0:
                    eval_blocking(path, "%s_u%d" % (args.tag, upd), args, log, "fast")
        log("selfplay finished")
    finally:
        er.close()
        es.close()


if __name__ == "__main__":
    main()
