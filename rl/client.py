"""A vector of RL environments (rl/env.py, on the Python match core) spread over several worker processes.
Interface: configure / step / terms / set_opponent / close (the same as when the workers were Godot processes)."""
import multiprocessing as mp
import os
import sys
import time
import traceback

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _worker(conn, log_path):
    """One worker process: several environments stepped in lock-step ."""
    for v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(v, "1")
    sys.path.insert(0, os.path.join(ROOT, "rl"))
    sys.path.insert(0, ROOT)
    try:
        from env import RLEnv
        envs, opp_net = [], None
        while True:
            cmd, payload = conn.recv()
            if cmd == "C":
                n_envs, seed0 = int(payload.get("envs", 8)), int(payload.get("seed", 1))
                envs = []
                for i in range(n_envs):
                    e = RLEnv()
                    e.configure(dict(payload, seed=seed0 * 1000003 + i * 7919))
                    e.opp_net = opp_net
                    e.reset()
                    envs.append(e)
                conn.send({"envs": n_envs, "agents": envs[0].n_agents(), "obs_dim": envs[0].obs_dim()})
            elif cmd == "S":
                acts = payload
                obs, rew = [], []
                done, outc, epr, gf, ga = (np.zeros(len(envs), t) for t in (np.uint8, np.uint8, np.float32, np.uint8, np.uint8))
                for i, e in enumerate(envs):
                    r, d, o, indiv = e.step(acts[i])
                    rew.append(np.asarray([r + x for x in indiv], np.float32))
                    done[i], outc[i], epr[i] = d, o, e.ep_return
                    gf[i], ga[i] = min(e.sim.scores[0], 255), min(e.sim.scores[1], 255)
                    if d:
                        e.reset()                      # a finished env starts its next episode at once
                    obs.append(np.asarray(e.observe(), np.float32))
                conn.send((np.stack(obs), np.stack(rew), done, outc, epr, gf, ga))
            elif cmd == "T":
                sums, steps = {}, 0
                for e in envs:
                    for k, v in e.term_sums.items():
                        sums[k] = sums.get(k, 0.0) + v
                    steps += e.term_steps
                    e.term_sums, e.term_steps = {}, 0
                conn.send({"terms": sums, "steps": steps})
            elif cmd == "W":
                opp_net = {"dict": payload} if payload and "W" in payload else None
                for e in envs:
                    e.opp_net = opp_net                # takes effect from the next episode
                conn.send({"ok": True})
            elif cmd == "Q":
                return
    except (EOFError, KeyboardInterrupt):
        return
    except Exception:
        with open(log_path, "a") as f:
            traceback.print_exc(file=f)
        raise


class Worker:
    def __init__(self, log_path):
        ctx = mp.get_context("spawn")                  # the trainer has torch loaded: never fork it
        self.conn, child = ctx.Pipe()
        self.proc = ctx.Process(target=_worker, args=(child, log_path), daemon=True)
        self.proc.start()

    def send(self, cmd, payload=None):
        self.conn.send((cmd, payload))

    def recv(self):
        if not self.conn.poll(3600):
            raise RuntimeError("worker gave no answer for an hour")
        return self.conn.recv()

    def close(self):
        try:
            self.send("Q")
        except Exception:
            pass
        self.proc.join(timeout=5)
        if self.proc.is_alive():
            self.proc.kill()


class VecEnv:
    """workers x envs_per_worker environments. Arrays are shaped [E_total, A, ...]."""

    def __init__(self, workers=14, envs_per_worker=8, base_port=7100, log_path="logs/rl_workers.log"):
        os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
        self.log_path = os.path.join(ROOT, log_path)
        self.workers = [Worker(self.log_path) for _ in range(workers)]
        self.epw = envs_per_worker
        self.E = workers * envs_per_worker
        self.A = self.D = None

    def configure(self, cfg, seed=1):
        for i, w in enumerate(self.workers):
            w.send("C", dict(cfg, envs=self.epw, seed=seed * 101 + i))
        for w in self.workers:
            info = w.recv()
        self.A, self.D = info["agents"], info["obs_dim"]
        return info

    def set_opponent(self, mlp_dict):
        """The self-play opponent (a game-model dict, or None to clear): used from the next episode on."""
        for w in self.workers:
            w.send("W", mlp_dict or None)
        for w in self.workers:
            w.recv()

    def terms(self):
        """Reward terms accumulated since the last call (what the reward is made of): ({term: summed per-agent mean}, env steps)."""
        for w in self.workers:
            w.send("T")
        sums, steps = {}, 0
        for w in self.workers:
            d = w.recv()
            steps += d["steps"]
            for k, v in d["terms"].items():
                sums[k] = sums.get(k, 0.0) + v
        return sums, steps

    def step_async(self, actions):
        """Send the actions (int8 [E, A, 2]) to all workers; collect with step_wait()."""
        acts = np.ascontiguousarray(actions, dtype=np.int8).reshape(self.E, self.A * 2)
        for i, w in enumerate(self.workers):
            w.send("S", acts[i * self.epw:(i + 1) * self.epw])

    def step(self, actions):
        """actions int8 [E, A, 2] -> obs [E,A,D], reward [E,A], done [E], outcome [E], ep_return [E], gf [E], ga [E]"""
        self.step_async(actions)
        return self.step_wait()

    def step_wait(self):
        parts = [w.recv() for w in self.workers]
        obs, rew, done, outc, epr, gf, ga = (np.concatenate([p[k] for p in parts]) for k in range(7))
        e, a, d = self.E, self.A, self.D
        return obs.reshape(e, a, d), rew.reshape(e, a), done.astype(bool), outc, epr, gf, ga

    def close(self):
        for w in self.workers:
            w.close()


if __name__ == "__main__":
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    env = VecEnv(workers=workers, envs_per_worker=8)
    print(env.configure({"pitch": "arena", "size": 5, "n_active": 5, "with_keeper": True, "opp": "aurora,cobalt", "match_mode": True,
                         "duration": 90.0, "obs": "team"}))
    rng = np.random.default_rng(0)
    t0 = time.time()
    n = 200
    for _ in range(n):
        act = np.stack([rng.integers(0, 9, (env.E, env.A)), rng.integers(0, 2, (env.E, env.A))], -1)
        obs, rew, done, outc, epr, gf, ga = env.step(act)
    dt = time.time() - t0
    print("obs", obs.shape, "steps/s (decisions, all envs): %.0f" % (n * env.E / dt), "ticks/s: %.0f" % (n * env.E * 2 / dt))
    env.close()
