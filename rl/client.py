"""Python side of the Godot bridge: a vector of RL envs spread over several Godot processes."""
import json
import os
import socket
import struct
import subprocess
import time

import numpy as np

import platform
GODOT = os.path.expanduser("~/godot/Godot_v4.6-stable_linux.%s" % ("arm64" if platform.machine() == "aarch64" else "x86_64"))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Worker:
    def __init__(self, port, log):
        self.port = port
        self.proc = subprocess.Popen(
            [GODOT, "--headless", "--path", ROOT, "res://rl/rl_server.tscn", "--", "--port", str(port)],
            stdout=log, stderr=subprocess.STDOUT, env={**os.environ, "GODOT_SILENCE_ROOT_WARNING": "1"})
        self.sock = None
        for _ in range(200):
            if self.proc.poll() is not None:
                raise RuntimeError("godot worker died on start (port %d)" % port)
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=1.0)
                break
            except OSError:
                time.sleep(0.1)
        if self.sock is None:
            raise RuntimeError("cannot connect to worker on %d" % port)
        self.sock.settimeout(None)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def send(self, cmd, payload=b""):
        self.sock.sendall(cmd + struct.pack("<I", len(payload)) + payload)

    def recv(self):
        n = struct.unpack("<I", self._exact(4))[0]
        return self._exact(n)

    def _exact(self, n):
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise RuntimeError("worker closed connection")
            buf += chunk
        return bytes(buf)

    def close(self):
        try:
            self.send(b"Q")
        except Exception:
            pass
        try:
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


class VecEnv:
    """workers x envs_per_worker environments. Arrays are shaped [E_total, A, ...]."""

    def __init__(self, workers=14, envs_per_worker=8, base_port=7100, log_path="logs/rl_workers.log"):
        os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
        self.log = open(os.path.join(ROOT, log_path), "ab")
        self.workers = [Worker(base_port + i, self.log) for i in range(workers)]
        self.epw = envs_per_worker
        self.E = workers * envs_per_worker
        self.A = self.D = None

    def configure(self, cfg, seed=1):
        for i, w in enumerate(self.workers):
            c = dict(cfg, envs=self.epw, seed=seed * 101 + i)
            w.send(b"C", json.dumps(c).encode())
        for w in self.workers:
            info = json.loads(w.recv())
        self.A, self.D = info["agents"], info["obs_dim"]
        self._split = self.epw
        return info

    def set_opponent(self, mlp_dict):
        payload = json.dumps(mlp_dict or {}).encode()
        for w in self.workers:
            w.send(b"W", payload)
        for w in self.workers:
            w.recv()

    def terms(self):
        """Reward terms accumulated since the last call (what the reward is made of): ({term: summed per-agent mean}, env steps)."""
        for w in self.workers:
            w.send(b"T")
        sums, steps = {}, 0
        for w in self.workers:
            d = json.loads(w.recv())
            steps += d["steps"]
            for k, v in d["terms"].items():
                sums[k] = sums.get(k, 0.0) + v
        return sums, steps

    def step_async(self, actions):
        """Send the actions (int8 [E, A, 2]) to all workers; collect with step_wait()."""
        acts = np.ascontiguousarray(actions, dtype=np.int8).reshape(self.E, self.A * 2)
        for i, w in enumerate(self.workers):
            w.send(b"S", acts[i * self.epw:(i + 1) * self.epw].tobytes())

    def step(self, actions):
        """actions int8 [E, A, 2] -> obs [E,A,D], reward [E,A], done [E], outcome [E], ep_return [E], gf [E], ga [E]"""
        self.step_async(actions)
        return self.step_wait()

    def step_wait(self):
        obs, rew, done, outc, epr, gf, ga = [], [], [], [], [], [], []
        e, a, d = self.epw, self.A, self.D
        for w in self.workers:
            b = w.recv()
            o = e * a * d * 4
            obs.append(np.frombuffer(b, np.float32, e * a * d, 0).reshape(e, a, d))
            r0 = o + e * a * 4                    # after the per-agent rewards
            rew.append(np.frombuffer(b, np.float32, e * a, o).reshape(e, a))
            done.append(np.frombuffer(b, np.uint8, e, r0))
            outc.append(np.frombuffer(b, np.uint8, e, r0 + e))
            epr.append(np.frombuffer(b, np.float32, e, r0 + e * 2))
            gf.append(np.frombuffer(b, np.uint8, e, r0 + e * 6))
            ga.append(np.frombuffer(b, np.uint8, e, r0 + e * 7))
        return (np.concatenate(obs), np.concatenate(rew), np.concatenate(done).astype(bool),
                np.concatenate(outc), np.concatenate(epr), np.concatenate(gf), np.concatenate(ga))

    def close(self):
        for w in self.workers:
            w.close()


if __name__ == "__main__":
    import sys
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    env = VecEnv(workers=workers, envs_per_worker=8)
    print(env.configure({"pitch": "arena", "size": 5, "n_active": 5, "with_keeper": True, "opp": "none"}))
    rng = np.random.default_rng(0)
    t0 = time.time()
    n = 200
    goals = 0
    for _ in range(n):
        act = np.stack([rng.integers(0, 9, (env.E, env.A)), rng.integers(0, 2, (env.E, env.A))], -1)
        obs, rew, done, outc, epr, gf, ga = env.step(act)
        goals += int((outc[done] == 1).sum())
    dt = time.time() - t0
    print("obs", obs.shape, "rew", rew[:3], "steps/s (decisions, all envs): %.0f" % (n * env.E / dt),
          "ticks/s: %.0f" % (n * env.E * 2 / dt), "goals", goals)
    env.close()
