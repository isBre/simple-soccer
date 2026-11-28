"""Self-play + league training of the RL net at any team size (--size 1..5), with human-likeness rewards.

Two groups of env workers run side by side and feed ONE learner (shared policy over the N players of team 0):
  * rule group : team 1 = the rule-based teams (training pool only, 4 teams are held out); with --opp_mode none an empty
                 pitch instead (first-goal episodes from random starts: the 1v0 stage), and no self group
  * self group : team 1 = the net itself, driven from Python (all its players). Opponent slots:
                 slot 0 = the frozen shipped model (benchmark: the log shows how the learner scores against it),
                 other slots = past snapshots of the learner (resampled every few updates).
Extra reward terms (per player) push towards human-like play: completed progressive passes are paid, key passes
(a pass whose receiver shoots) and the xA of those shots are paid, failed passes cost, teammates should not bunch up ("storm"), and kick must only be pressed when the ball is in reach.
With --obs slots (76 numbers, every size) the net also makes a call to its teammates every decision (soccer.core.public.INTENTS, 5
logits after the kick); calls carry no reward: what they come to mean is up to training. --start scratch = a fresh net.

  python3 rl/selfplay.py --updates 1500
"""
import copy
import json
import os
import re
import subprocess
import sys
import time
from collections import deque

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from rl.client import VecEnv
from rl.agent import Agent, OUT, OUT_DRAW, OUT_GOAL, OUT_WIN, dists, load_padded, team_pools
from soccer.ai.obs import SLOTS_NAME
from rl.selfplay_args import OBS_DIMS, parser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

torch.distributions.Distribution.set_default_validate_args(False)    # argument checks only (no effect on any value): ~20% of the rollout inference


class TrainerQos:
    """macOS: lab/run.sh starts the runner with `taskpolicy -b` (background mode: efficiency cores only, low clock), the
    coolest way to run the long simulation. The trainer process itself only works in short bursts (the nets between two env
    steps, the learning step) and otherwise waits for the env workers, so with --trainer_fg 1 it leaves background mode once its
    workers are started (they inherit background mode and keep it): the bursts run about 4.5 times faster on the performance cores
    and the workers stop waiting for them. Evaluations go back to background mode (child processes inherit it). No-op elsewhere
    (Linux, or a trainer not started in background mode). Changes speed only, nothing that is computed."""
    PRIO_DARWIN_PROCESS, PRIO_DARWIN_BG = 4, 0x1000

    def __init__(self, enabled):
        self.libc = None
        if enabled and sys.platform == "darwin":
            import ctypes
            libc = ctypes.CDLL(None)
            if libc.getpriority(self.PRIO_DARWIN_PROCESS, 0) == 1:     # started in background mode
                self.libc = libc

    def fg(self):
        if self.libc is not None:
            self.libc.setpriority(self.PRIO_DARWIN_PROCESS, 0, 0)

    def bg(self):
        if self.libc is not None:
            self.libc.setpriority(self.PRIO_DARWIN_PROCESS, 0, self.PRIO_DARWIN_BG)


CKPT = os.path.join(OUT, "ckpt")


N_TEAM, N_LEGACY = 46, 54                       # env obs "both" = the team observation followed by the legacy one


def load_net(path):
    """An Agent from a torch checkpoint (.pt) or a game-model JSON (sizes, W, B), whatever its input size and width."""
    if path.endswith(".json"):
        d = json.load(open(path))
        a = Agent(d["sizes"][0], d["sizes"][1], d["sizes"][-1] >= 15, d.get("obs", ""))
        with torch.no_grad():
            for lin, w, b in zip([l for l in a.actor if isinstance(l, nn.Linear)], d["W"], d["B"]):
                lin.weight.copy_(torch.tensor(w, dtype=torch.float32).view(lin.weight.shape))
                lin.bias.copy_(torch.tensor(b, dtype=torch.float32))
        return a
    sd = torch.load(path)
    calls = sd["actor.4.weight"].shape[0] >= 15
    a = Agent(sd["actor.0.weight"].shape[1], sd["actor.0.weight"].shape[0], calls, SLOTS_NAME if calls else "")
    a.load_state_dict(sd)
    return a


def obs_cols(in_dim, first=N_TEAM):
    """Columns of the 'both' / 'both_rank' observation (first = 46 or 56 numbers, then the 54 legacy ones) a net with this
    input size reads: the team observation is the first 46 of the rank one."""
    return slice(first, first + N_LEGACY) if in_dim == N_LEGACY else slice(0, in_dim)


def pts(o):
    return 3.0 if o == OUT_WIN else (1.0 if o == OUT_DRAW else 0.0)


def make_cfgs(args):
    P = team_pools()
    pool = ",".join(P["weak"] + P["average"] + P["strong"] + P["elite"])
    base = {"pitch": "arena", "size": args.size, "own_team": "owls", "n_active": args.size, "with_keeper": True,
            "match_mode": True, "duration": 90.0, "max_steps": 3200,
            "w_pass_prog": args.w_pass_prog, "w_pass_ok": args.w_pass_ok, "w_pass_fail": args.w_pass_fail,
            "pass_individual": bool(args.pass_individual), "w_recv": args.w_recv, "w_open": args.w_open, "w_key_pass": args.w_key_pass, "w_xa": args.w_xa, "w_space": args.w_space, "space_radius": args.space_radius, "w_kick": args.w_kick, "coop_cap": args.coop_cap, "random_start": args.random_start, "w_keeper": args.w_keeper, "w_jitter": args.w_jitter, "keeper_free": args.keeper_free,
            "obs": args.obs, "shaping": args.shaping, "w_far": args.w_far, "far_radius": args.far_radius, "w_wall": args.w_wall, "w_corner": args.w_corner,
            "w_xg": args.w_xg, "xg_cap": args.xg_cap, "w_xga": args.w_xga, "w_win": args.w_win, "w_draw": args.w_draw, "w_tackle": args.w_tackle, "def_cap": args.def_cap,
            "w_goalside": args.w_goalside, "goalside_lane": args.goalside_lane, "w_opp_half": args.w_opp_half, "w_compact": args.w_compact,
            "compact_len": args.compact_len, "compact_wid": args.compact_wid}
    if args.opp_mode == "none":                                    # the 1v0 stage: an empty pitch, first-goal episodes
        return {**base, "opp": "none", "match_mode": False, "max_steps": 750}, None
    return {**base, "opp": pool}, {**base, "opp": "owls", "opp_external": True}


def eval_blocking(model_path, tag, args, log, mode="full", qos=None):
    """Evaluation of a snapshot while training is PAUSED: this call returns when it is done, the env workers just wait, so the
    evaluation gets the whole CPU (the viewer shows an "evaluation running" banner meanwhile).
      full: rl/eval_checkpoint.py (league, behaviour, scouting, head to head): logs/sp_eval/<tag>.txt
      fast: the check every --fast_every updates: the estimated Elo (--elo_pairs, lab/ladder.py estimate) and, with --fast_rules 1,
            the older fixed check against the rule bots (logs/sp_eval/<tag>_fast.txt)"""
    rules = mode == "full" or args.fast_rules
    elo = mode == "fast" and args.elo_pairs > 0
    if not rules and not elo:
        return
    suffix = "_fast" if mode == "fast" else ""
    out = os.path.join(ROOT, "logs", "sp_eval", tag + suffix + ".txt")
    cmd = [sys.executable, os.path.join(ROOT, "rl", "eval_checkpoint.py"), "--model", model_path, "--out", out, "--paused", "--mode", mode,
           "--games", str(args.eval_games), "--duration", str(args.eval_duration), "--h2h_games", str(args.eval_h2h_games)]
    if args.fast_ref:
        cmd += ["--ref", "start=" + args.fast_ref]                  # head to head against the net this run started from
    log("training paused: %s check of %s" % (mode, tag))
    t0 = time.time()
    if qos is not None:
        qos.bg()                                                    # the evaluation processes inherit background mode
    try:
        if rules:
            subprocess.run(cmd, cwd=os.path.join(ROOT, "rl"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if elo:
            elo_estimate(model_path, args, log)
    finally:
        if qos is not None:
            qos.fg()
    log("%s check of %s finished in %.1f min, training continues" % (mode, tag, (time.time() - t0) / 60.0))


def elo_estimate(model_path, args, log):
    """Estimated Elo of the snapshot (lab/ladder.py estimate: it plays placed ladder entries, its rating is fitted with theirs held
    fixed; exp/elo_estimates.jsonl). The "evaluation running" flag is set meanwhile (the runner does not count it as training time,
    the Lab shows "evaluating"). A failure only costs the estimate."""
    upd = int(re.search(r"_u(\d+)\.json$", model_path).group(1))
    flag = os.path.join(ROOT, "logs", "%s_eval_running.json" % args.tag)
    t0 = time.time()
    with open(flag, "w") as fh:
        json.dump({"pid": os.getpid(), "checkpoint": os.path.basename(model_path)[:-5], "started": int(t0), "paused": True, "what": "elo estimate"}, fh)
    try:
        p = subprocess.run([sys.executable, os.path.join(ROOT, "lab", "ladder.py"), "estimate", "--model", model_path, "--tag", args.tag,
                            "--update", str(upd), "--pairs", str(args.elo_pairs), "--workers", "3", "--size", str(args.size)], cwd=ROOT, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True)
    finally:
        if os.path.exists(flag):
            os.remove(flag)
    try:
        r = json.loads(p.stdout.strip().splitlines()[-1])
        log("estimated Elo of %s u%d: %.0f ± %.0f (GF %.2f, GA %.2f, %d games, %.0f s)" % (args.tag, upd, r["elo"], 1.96 * r["se"], r["gf"], r["ga"], r["games"], time.time() - t0))
    except (ValueError, IndexError, KeyError, TypeError):
        log("estimated Elo of %s u%d failed: %s" % (args.tag, upd, p.stdout.strip()[-300:]))


def main():
    ap = parser()
    args = ap.parse_args()
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    obs_dim = OBS_DIMS[args.obs]
    calls = args.obs == "slots"                                     # the slots observation: the net calls too
    assert 1 <= args.size <= 5 and (args.size == 5 or calls), "sizes below 5 need --obs slots"
    scratch = args.start in ("", "scratch")
    strong = [(os.path.splitext(os.path.basename(p))[0], load_net(os.path.join(ROOT, p) if not os.path.isabs(p) else p).actor)
              for p in args.opp_models.split(",") if p]
    teacher = load_net(args.teacher if os.path.isabs(args.teacher) else os.path.join(ROOT, args.teacher)) if args.teacher else None
    both = teacher is not None or any(n[0].in_features == N_LEGACY for _, n in strong)
    assert not both or args.obs in ("team", "rank"), "a teacher / 54-input opponents need --obs team or rank"
    env_obs = ("both" if args.obs == "team" else "both_rank") if both else args.obs
    D_env = obs_dim + N_LEGACY if both else obs_dim
    L = slice(0, obs_dim)                                           # the learner's columns of the environment observation
    for _, n in strong:
        for p in n.parameters():
            p.requires_grad_(False)
    T_cols = obs_cols(teacher.sizes[0], obs_dim) if teacher is not None else None    # the teacher's columns of the environment observation
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

    qos = TrainerQos(args.trainer_fg)
    agent = Agent(obs_dim, args.hidden, calls, SLOTS_NAME if calls else "")
    if not scratch:
        load_padded(agent, args.start)
    opt = torch.optim.Adam(agent.parameters(), lr=args.lr)
    baseline = load_net(args.baseline) if args.baseline else (copy.deepcopy(agent) if scratch else load_net(args.start))
    assert baseline.sizes[0] == obs_dim, "the frozen benchmark must read the learner's observation"
    for p in baseline.parameters():
        p.requires_grad_(False)
    pool = [copy.deepcopy(baseline.actor.state_dict())]           # opponent pool: baseline first, then snapshots
    warm = 30                                                      # lr warm-up (updates) for a fresh optimizer
    state_path = args.start[:-3] + ".train_state" if args.start.endswith(".pt") else ""
    if args.start_update > 0 and scratch:
        raise SystemExit("a resume needs --start (the checkpoint to continue from)")
    if args.start_update > 0 and state_path and os.path.exists(state_path):     # faithful resume: same Adam moments and opponent pool
        saved = torch.load(state_path, weights_only=False)
        opt.load_state_dict(saved["opt"])
        pool = [pool[0]] + saved.get("pool", [])[1:]
        warm = 0
    NSLOT = 4
    snap_nets = [Agent(obs_dim, args.hidden, calls).actor for _ in range(NSLOT)]     # learner snapshots (slots 1-3)
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
                slot_net[k], slot_cols[k], slot_name[k] = net, obs_cols(net[0].in_features, obs_dim), "strong:" + name
            else:
                snap_nets[k].load_state_dict(pool[np.random.randint(len(pool))])
                slot_net[k], slot_cols[k], slot_name[k] = snap_nets[k], L, "league"

    assign_slots()

    cfg_rule, cfg_self = make_cfgs(args)
    cfg_rule["obs"] = env_obs
    if cfg_self is not None:
        cfg_self["obs"] = env_obs
    er = VecEnv(workers=args.workers_rule, envs_per_worker=args.envs_per_worker, base_port=args.base_port, log_path="logs/rl_workers_rule.log")
    es = VecEnv(workers=args.workers_self, envs_per_worker=args.envs_per_worker, base_port=args.base_port + 100,
                log_path="logs/rl_workers_self.log") if cfg_self is not None and args.workers_self > 0 else None
    try:
        er.configure(cfg_rule, seed=args.seed)
        if es is not None:
            es.configure(cfg_self, seed=args.seed + 1)
        qos.fg()                                                    # the workers are started (in background mode): see TrainerQos
        Er, Es = er.E, (es.E if es is not None else 0)
        E, A, D, T = Er + Es, args.size, D_env, args.rollout
        W = 3 if calls else 2                                       # numbers per action: move, kick (, call)
        slot_of = np.arange(Es) * NSLOT // max(Es, 1)              # envs of the self group -> opponent slot
        log("selfplay start | rule envs %d, self envs %d (opp slots %d, slot 0 = frozen benchmark) | lr %g | rewards pass %.2f/%.2f/-%.2f space %.3f kick %.3f" % (
            Er, Es, NSLOT, args.lr, args.w_pass_prog, args.w_pass_ok, args.w_pass_fail, args.w_space, args.w_kick))

        obs_r = torch.from_numpy(er.step(np.zeros((Er, A, W), np.int8))[0].copy())
        obs_s = torch.from_numpy(es.step(np.zeros((Es, 2 * A, W), np.int8))[0].copy()) if es is not None else torch.zeros(0, 2 * A, D)
        stats = {"rule": deque(maxlen=200), "bench": deque(maxlen=120), "league": deque(maxlen=200), "goal": deque(maxlen=400)}
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
            b_c = torch.zeros(T, E, A, dtype=torch.long)
            b_lp = torch.zeros(T, E, A)
            b_rew = torch.zeros(T, E, A)
            b_done = torch.zeros(T, E)
            b_val = torch.zeros(T, E, A)
            t0 = time.time()
            torch.set_num_threads(1)                      # tiny batches: extra threads only steal CPU from the env workers
            for t in range(T):
                obs_L = torch.cat([obs_r, obs_s[:, :A]], 0)                    # [E, A, D] learner observations
                with torch.no_grad():
                    mr_, kr_, cr_, lpr_ = agent.act(obs_r[..., L])
                    vr_ = agent.value(obs_r[..., L])
                er.step_async(np.stack([mr_.numpy(), kr_.long().numpy(), cr_.numpy()][:W], -1).astype(np.int8))   # rule workers simulate while we infer the self group
                with torch.no_grad():
                    ms_, ks_, cs_, lps_ = agent.act(obs_s[:, :A, L])
                    vs_ = agent.value(obs_s[:, :A, L])
                    om = torch.zeros(Es, A, dtype=torch.long)
                    ok = torch.zeros(Es, A)
                    oc = torch.zeros(Es, A, dtype=torch.long)
                    for sl in range(NSLOT):
                        idx = np.nonzero(slot_of == sl)[0]
                        if len(idx) == 0:
                            continue
                        dm, dk, dc = dists(slot_net[sl](obs_s[idx, A:][..., slot_cols[sl]]))
                        om[idx] = dm.sample()
                        ok[idx] = dk.sample()
                        if dc is not None:
                            oc[idx] = dc.sample()
                m, k, c, lp, v = (torch.cat([x, y], 0) for x, y in ((mr_, ms_), (kr_, ks_), (cr_, cs_), (lpr_, lps_), (vr_, vs_)))
                if es is not None:
                    act_s = torch.zeros(Es, 2 * A, W, dtype=torch.long)
                    act_s[:, :A, 0], act_s[:, :A, 1] = ms_, ks_.long()
                    act_s[:, A:, 0], act_s[:, A:, 1] = om, ok.long()
                    if W == 3:
                        act_s[:, :A, 2], act_s[:, A:, 2] = cs_, oc
                    es.step_async(act_s.numpy().astype(np.int8))
                nr = er.step_wait()
                ns = es.step_wait() if es is not None else None
                b_obs[t], b_m[t], b_k[t], b_c[t], b_lp[t], b_val[t] = obs_L, m, k, c, lp, v
                b_rew[t] = torch.from_numpy(np.concatenate([nr[1][:, :A]] + ([ns[1][:, :A]] if ns else []), 0).copy())
                dn = np.concatenate([nr[2]] + ([ns[2]] if ns else []))
                b_done[t] = torch.from_numpy(dn.astype(np.float32))
                for i in np.nonzero(nr[2])[0]:
                    if args.opp_mode == "none":
                        stats["goal"].append(1.0 if int(nr[3][i]) == OUT_GOAL else 0.0)
                    else:
                        stats["rule"].append(pts(int(nr[3][i])))
                for i in (np.nonzero(ns[2])[0] if ns else []):
                    p_ = pts(int(ns[3][i]))
                    who = slot_name[slot_of[i]]
                    if who.startswith("strong:"):
                        strong_res[who[7:]].append(p_)
                    else:
                        (stats["bench"] if who == "bench" else stats["league"]).append(p_)
                obs_r = torch.from_numpy(nr[0].copy())
                if ns:
                    obs_s = torch.from_numpy(ns[0].copy())
            t_sim = time.time() - t0
            sums, n_steps = {}, 0
            for venv in [er] + ([es] if es is not None else []):                               # what the reward was made of in this update (shown by the viewer's INSIGHT page)
                got, n = venv.terms()
                n_steps += n
                for k, v in got.items():
                    sums[k] = sums.get(k, 0.0) + v
            if n_steps:
                with open(os.path.join(ROOT, "logs", args.tag + "_terms.jsonl"), "a") as tf:
                    tf.write(json.dumps({"upd": upd, "terms": {k: v / n_steps for k, v in sums.items()}}) + "\n")

            with torch.no_grad():
                last_v = agent.value(torch.cat([obs_r, obs_s[:, :A]], 0)[..., L])
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
            f_m, f_k, f_c, f_lp = b_m.reshape(-1), b_k.reshape(-1), b_c.reshape(-1), b_lp.reshape(-1)
            f_adv, f_ret = adv.reshape(-1), ret.reshape(-1)
            f_adv = (f_adv - f_adv.mean()) / (f_adv.std() + 1e-8)
            n = f_obs.shape[0]
            t1 = time.time()
            torch.set_num_threads(args.learn_threads)
            f_val = b_val.reshape(-1)
            health = {"kl": [], "clipfrac": [], "vloss": [], "pg": [], "gradnorm": [], "ent_move": [], "ent_kick": [], "ent_call": [], "kl_teacher": []}
            kl_w = args.kl_coef * max(0.0, 1.0 - upd / max(args.kl_decay, 1)) if teacher is not None else 0.0
            ev = 1.0 - float((f_ret - f_val).var() / (f_ret.var() + 1e-8))      # explained variance of the critic (before this update)
            for _ in range(args.epochs):
                perm = torch.randperm(n)
                for s in range(0, n, args.minibatch):
                    idx = perm[s:s + args.minibatch]
                    x = f_obs[idx]
                    z = agent.actor(x[:, L])
                    dm, dk, dc = dists(z)
                    lp = dm.log_prob(f_m[idx]) + dk.log_prob(f_k[idx]) + (dc.log_prob(f_c[idx]) if dc is not None else 0.0)
                    ratio = torch.exp(lp - f_lp[idx])
                    pg = -torch.min(ratio * f_adv[idx], torch.clamp(ratio, 0.8, 1.2) * f_adv[idx]).mean()
                    vl = 0.5 * (agent.value(x[:, L]) - f_ret[idx]).pow(2).mean()
                    ent = dm.entropy().mean() + dk.entropy().mean() + (dc.entropy().mean() if dc is not None else 0.0)
                    loss = pg + 0.5 * vl - args.ent * ent
                    if teacher is not None:                         # kickstarting: stay close to the teacher's moves (weight decays to 0)
                        with torch.no_grad():
                            zt = teacher.actor(x[:, T_cols])
                        klt = (F.softmax(zt[:, :9], -1) * (F.log_softmax(zt[:, :9], -1) - F.log_softmax(z[:, :9], -1))).sum(-1).mean()
                        pt, ps = torch.sigmoid(zt[:, 9]), torch.sigmoid(z[:, 9]).clamp(1e-6, 1 - 1e-6)
                        klt = klt + (pt * (torch.log(pt.clamp(1e-6)) - torch.log(ps)) + (1 - pt) * (torch.log((1 - pt).clamp(1e-6)) - torch.log(1 - ps))).mean()
                        health["kl_teacher"].append(float(klt.detach()))
                        if kl_w > 0:
                            loss = loss + kl_w * klt
                    opt.zero_grad()
                    loss.backward()
                    gn = nn.utils.clip_grad_norm_(agent.parameters(), 0.5)
                    opt.step()
                    health["kl"].append(float((f_lp[idx] - lp).mean().detach()))                  # approx KL(old || new)
                    health["clipfrac"].append(float(((ratio - 1.0).abs() > 0.2).float().mean().detach()))
                    health["vloss"].append(float(vl.detach()))
                    health["pg"].append(float(pg.detach()))
                    health["gradnorm"].append(float(gn))
                    health["ent_move"].append(float(dm.entropy().mean().detach()))
                    health["ent_kick"].append(float(dk.entropy().mean().detach()))
                    if dc is not None:
                        health["ent_call"].append(float(dc.entropy().mean().detach()))
            t_learn = time.time() - t1
            with open(os.path.join(ROOT, "logs", args.tag + "_ppo.jsonl"), "a") as pf:      # PPO health, shown by the viewer's TRAINING page
                pf.write(json.dumps({"upd": upd, "ev": ev, "kl_w": kl_w, **{k: float(np.mean(v)) for k, v in health.items() if v}}) + "\n")

            if upd % args.log_every == 0 or upd == args.start_update + 1:
                f = lambda d: ("%.2f(%d)" % (np.mean(d), len(d))) if d else "-"
                m2 = lambda d: float("%.2f" % np.mean(d)) if d else None
                dps, elapsed = 2 * T * Er / t_sim, time.time() - t_start
                log("sp upd %d %s | pts/m vs rules %s | goal rate %s | vs frozen benchmark %s | vs league %s | rew/step %.4f | ent %.2f | pool %d | "
                    "%.0f dec/s sim %.1fs learn %.1fs | %.0fs" % (upd, "%dv%d" % (A, 0 if args.opp_mode == "none" else A), f(stats["rule"]), f(stats["goal"]), f(stats["bench"]), f(stats["league"]),
                                                              b_rew.mean().item(), ent.item(), len(pool), dps,
                                                              t_sim, t_learn, elapsed))
                with open(os.path.join(ROOT, "logs", args.tag + "_train.jsonl"), "a") as tf:     # the same numbers for lab/tracker.py train_rows
                    tf.write(json.dumps({"clock": time.strftime("%H:%M:%S"), "upd": upd, "size": A, "rules": m2(stats["rule"]), "n_rules": len(stats["rule"]),
                                         "goal_rate": m2(stats["goal"]),
                                         "bench": m2(stats["bench"]), "league": m2(stats["league"]), "rew": float("%.4f" % b_rew.mean().item()),
                                         "ent": float("%.2f" % ent.item()), "dps": int("%.0f" % dps), "sim": float("%.1f" % t_sim),
                                         "learn": float("%.1f" % t_learn), "elapsed": int("%.0f" % elapsed)}) + "\n")
            if strong and upd % (args.log_every * 5) == 0:
                log("strong opponents (pts/match, last 60): " + ", ".join("%s %s" % (n, ("%.2f(%d)" % (np.mean(r), len(r))) if r else "-") for n, r in strong_res.items()))
            if upd % args.ckpt_every == 0:
                path = os.path.join(CKPT, "%s_u%d.json" % (args.tag, upd))
                with open(path, "w") as fh:
                    json.dump(agent.to_game_dict(), fh)
                torch.save(agent.state_dict(), os.path.join(CKPT, "%s_u%d.pt" % (args.tag, upd)))
                torch.save({"opt": opt.state_dict(), "pool": pool}, os.path.join(CKPT, "%s_u%d.train_state" % (args.tag, upd)))  # for a faithful resume
                if args.eval_every > 0 and upd % args.eval_every == 0:
                    eval_blocking(path, "%s_u%d" % (args.tag, upd), args, log, qos=qos)
                elif args.fast_every > 0 and upd % args.fast_every == 0:
                    eval_blocking(path, "%s_u%d" % (args.tag, upd), args, log, "fast", qos=qos)
        log("selfplay finished")
    finally:
        er.close()
        if es is not None:
            es.close()


if __name__ == "__main__":
    main()
