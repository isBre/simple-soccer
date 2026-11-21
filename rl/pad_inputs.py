"""Widen a checkpoint's input layer with zero weights, so a net trained on one observation starts on a longer one (e.g. the
46-number team observation -> the 56-number rank observation) and plays exactly as before until training uses the new inputs.

  python3 rl/pad_inputs.py models/x_kickstart_persist_best.pt out_5v5/ckpt/x_rank_start.pt --n_in 56

Writes the .pt (actor and critic padded) and its game-model .json next to it."""
import argparse
import json
import os
import sys

import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ppo import Agent, load_padded  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--n_in", type=int, required=True)
    a = ap.parse_args()
    sd = torch.load(a.src)
    agent = Agent(a.n_in, sd["actor.0.weight"].shape[0])
    load_padded(agent, a.src)
    os.makedirs(os.path.dirname(os.path.abspath(a.dst)), exist_ok=True)
    torch.save(agent.state_dict(), a.dst)
    with open(os.path.splitext(a.dst)[0] + ".json", "w") as f:
        json.dump(agent.to_game_dict(), f)
    print("wrote", a.dst, "inputs %d -> %d" % (sd["actor.0.weight"].shape[1], a.n_in))


if __name__ == "__main__":
    main()
