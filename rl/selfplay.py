"""Self-play + league fine-tuning of the 5v5 RL net, with human-likeness rewards.

Two groups of Godot workers run side by side and feed ONE learner (shared policy over the 5 players of team 0):
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
import time
from collections import deque

import numpy as np
import torch
import torch.nn as nn

from client import GODOT, ROOT, VecEnv
from ppo import Agent, OBS_DIM, OUT, OUT_DRAW, OUT_LOSS, OUT_WIN, load_padded, save_model, team_pools

CKPT = os.path.join(OUT, "ckpt")


def pts(o):
    return 3.0 if o == OUT_WIN else (1.0 if o == OUT_DRAW else 0.0)


def make_cfgs(args):
    P = team_pools()
    pool = ",".join(P["weak"] + P["average"] + P["strong"] + P["elite"])
    base = {"pitch": "arena", "size": 5, "own_team": "owls", "n_active": 5, "with_keeper": True,
            "match_mode": True, "duration": 90.0, "max_steps": 3200,
            "w_pass_prog": args.w_pass_prog, "w_pass_ok": args.w_pass_ok, "w_pass_fail": args.w_pass_fail,
            "pass_individual": bool(args.pass_individual), "w_recv": args.w_recv, "w_open": args.w_open, "w_key_pass": args.w_key_pass, "w_xa": args.w_xa, "w_space": args.w_space, "space_radius": args.space_radius, "w_kick": args.w_kick, "coop_cap": args.coop_cap, "random_start": args.random_start, "w_keeper": args.w_keeper, "w_jitter": args.w_jitter, "keeper_free": args.keeper_free}
    return {**base, "opp": pool}, {**base, "opp": "owls", "opp_external": True}


def eval_async(model_path, tag, games, log):
    """League evaluation + behaviour statistics of a snapshot, in the background (does not pause training)."""
    os.makedirs(os.path.join(ROOT, "logs", "sp_eval"), exist_ok=True)
    out = os.path.join(ROOT, "logs", "sp_eval", tag + ".txt")
    rel = "res://" + os.path.relpath(model_path, ROOT)
    cmd = ("nice -n 5 %s --headless --path %s res://rl/league_eval.tscn -- --model %s --games %d 2>&1 | grep -E 'SUMMARY' > %s; "
           "nice -n 5 %s --headless --path %s res://rl/behaviour_stats.tscn -- --model %s 2>&1 | grep -E 'RL Team|rule-based' >> %s") % (
        GODOT, ROOT, rel, games, out, GODOT, ROOT, rel, out)
    subprocess.Popen(["bash", "-c", cmd], env={**os.environ, "GODOT_SILENCE_ROOT_WARNING": "1"})
    log("background eval started for %s -> logs/sp_eval/%s.txt" % (tag, tag))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--updates", type=int, default=1500)
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
    ap.add_argument("--keeper_free", type=float, default=350.0)
    ap.add_argument("--snapshot_every", type=int, default=40)
    ap.add_argument("--resample_every", type=int, default=20)
    ap.add_argument("--ckpt_every", type=int, default=100)
    ap.add_argument("--eval_every", type=int, default=250)
    ap.add_argument("--eval_games", type=int, default=2)
    ap.add_argument("--log_every", type=int, default=5)
    ap.add_argument("--tag", default="sp")
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    os.makedirs(CKPT, exist_ok=True)
    logf = open(os.path.join(ROOT, "logs", "selfplay.log"), "a")

    def log(msg):
        line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    agent = Agent()
    load_padded(agent, args.start)
    opt = torch.optim.Adam(agent.parameters(), lr=args.lr)
    baseline = Agent()
    load_padded(baseline, args.baseline or args.start)
    for p in baseline.parameters():
        p.requires_grad_(False)
    pool = [copy.deepcopy(baseline.actor.state_dict())]           # opponent pool: baseline first, then snapshots
    NSLOT = 4
    opp_nets = [Agent().actor for _ in range(NSLOT)]
    for n in opp_nets:
        for p in n.parameters():
            p.requires_grad_(False)

    def assign_slots():
        opp_nets[0].load_state_dict(pool[0])                      # slot 0 is always the frozen benchmark
        for k in range(1, NSLOT):
            opp_nets[k].load_state_dict(pool[np.random.randint(len(pool))])

    assign_slots()

    cfg_rule, cfg_self = make_cfgs(args)
    er = VecEnv(workers=args.workers_rule, envs_per_worker=args.envs_per_worker, base_port=7100, log_path="logs/rl_workers_rule.log")
    es = VecEnv(workers=args.workers_self, envs_per_worker=args.envs_per_worker, base_port=7200, log_path="logs/rl_workers_self.log")
    try:
        er.configure(cfg_rule, seed=args.seed)
        es.configure(cfg_self, seed=args.seed + 1)
        Er, Es = er.E, es.E
        E, A, D, T = Er + Es, 5, OBS_DIM, args.rollout
        slot_of = np.arange(Es) * NSLOT // Es                      # envs of the self group -> opponent slot
        log("selfplay start | rule envs %d, self envs %d (opp slots %d, slot 0 = frozen benchmark) | lr %g | rewards pass %.2f/%.2f/-%.2f space %.3f kick %.3f" % (
            Er, Es, NSLOT, args.lr, args.w_pass_prog, args.w_pass_ok, args.w_pass_fail, args.w_space, args.w_kick))

        obs_r = torch.from_numpy(er.step(np.zeros((Er, 5, 2), np.int8))[0].copy())
        obs_s = torch.from_numpy(es.step(np.zeros((Es, 10, 2), np.int8))[0].copy())
        stats = {"rule": deque(maxlen=200), "bench": deque(maxlen=120), "league": deque(maxlen=200)}
        t_start = time.time()
        ent = torch.tensor(0.0)
        for upd in range(1, args.updates + 1):
            for g in opt.param_groups:                     # warm-up: a fresh Adam must not shake a converged policy
                g["lr"] = args.lr * min(1.0, upd / 30.0)
            if upd % args.snapshot_every == 0:
                pool.append(copy.deepcopy(agent.actor.state_dict()))
                pool = [pool[0]] + pool[1:][-8:]
            if upd == 1 or upd % args.resample_every == 0:
                assign_slots()
            b_obs = torch.zeros(T, E, A, D)
            b_m = torch.zeros(T, E, A, dtype=torch.long)
            b_k = torch.zeros(T, E, A)
            b_lp = torch.zeros(T, E, A)
            b_rew = torch.zeros(T, E, A)
            b_done = torch.zeros(T, E)
            b_val = torch.zeros(T, E, A)
            t0 = time.time()
            torch.set_num_threads(1)                      # tiny batches: extra threads only steal CPU from the Godot workers
            for t in range(T):
                obs_L = torch.cat([obs_r, obs_s[:, :5]], 0)                    # [E, 5, D] learner observations
                with torch.no_grad():
                    mr_, kr_, lpr_ = agent.act(obs_r)
                    vr_ = agent.value(obs_r)
                er.step_async(np.stack([mr_.numpy(), kr_.long().numpy()], -1).astype(np.int8))   # rule workers simulate while we infer the self group
                with torch.no_grad():
                    ms_, ks_, lps_ = agent.act(obs_s[:, :5])
                    vs_ = agent.value(obs_s[:, :5])
                    om = torch.zeros(Es, 5, dtype=torch.long)
                    ok = torch.zeros(Es, 5)
                    for sl in range(NSLOT):
                        idx = np.nonzero(slot_of == sl)[0]
                        z = opp_nets[sl](obs_s[idx, 5:])
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
                    (stats["bench"] if slot_of[i] == 0 else stats["league"]).append(p_)
                obs_r = torch.from_numpy(nr[0].copy())
                obs_s = torch.from_numpy(ns[0].copy())
            t_sim = time.time() - t0

            with torch.no_grad():
                last_v = agent.value(torch.cat([obs_r, obs_s[:, :5]], 0))
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
            torch.set_num_threads(os.cpu_count())
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

            if upd % args.log_every == 0 or upd == 1:
                f = lambda d: ("%.2f(%d)" % (np.mean(d), len(d))) if d else "-"
                log("sp upd %d | pts/m vs rules %s | vs frozen benchmark %s | vs league %s | rew/step %.4f | ent %.2f | pool %d | "
                    "%.0f dec/s sim %.1fs learn %.1fs | %.0fs" % (upd, f(stats["rule"]), f(stats["bench"]), f(stats["league"]),
                                                              b_rew.mean().item(), ent.item(), len(pool), 2 * T * Er / t_sim,
                                                              t_sim, t_learn, time.time() - t_start))
            if upd % args.ckpt_every == 0:
                path = os.path.join(CKPT, "%s_u%d.json" % (args.tag, upd))
                with open(path, "w") as fh:
                    json.dump(agent.to_game_dict(), fh)
                torch.save(agent.state_dict(), os.path.join(CKPT, "%s_u%d.pt" % (args.tag, upd)))
                if upd % args.eval_every == 0:
                    eval_async(path, "%s_u%d" % (args.tag, upd), args.eval_games, log)
        log("selfplay finished")
    finally:
        er.close()
        es.close()


if __name__ == "__main__":
    main()
