"""Trains a policy on the user's recorded play (imitation, "behaviour cloning") and saves it as a game model (the JSON format
of soccer/ai/nets.py), so the game plays it like any RL net: one shared policy, run once per player, all 5 players.

  model "linear"  no hidden layer: multinomial logistic regression on the 46 numbers (Machine Learning League)
  model "mlp"     46 -> hidden -> hidden -> 10, ReLU, the RL nets' shape (Deep Learning League)
Outputs: 9 move logits + 1 kick logit, as the RL nets. Loss: cross-entropy on the move + binary cross-entropy on the kick
(not re-weighted: the game samples the kick from this probability, so it must stay calibrated; weighting rare kicks
up made a first try kick 10-20 times more often than the user). Adam, weight decay, mirror augmentation (il/dataset.py), early stopping on held-out matches.

Evaluation before the final fit: the matches are split into --folds groups (whole matches only); each group is scored by a model
trained on the others. Reported per held-out match and pooled:
  move acc      share of decisions where the most likely move is the user's move
  top-2 acc     the user's move is among the 2 most likely
  nll           mean negative log-likelihood of the user's move (lower = better calibrated)
  kick F1       of "kick" vs the user's kick (threshold 0.5)
Baselines on the same rows: "always the most common move" and "always run at the ball".

  python3 il/train.py --model mlp --lag 3 --name dl_mlp_try1
  -> out_il/<name>.json (the game model) and out_il/<name>.metrics.json"""
import argparse
import json
import math
import os
import sys
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from il import dataset                       # noqa: E402

OUT = os.path.join(ROOT, "out_il")
UNIT = np.array([[0.0, 0.0]] + [[x / math.hypot(x, y), y / math.hypot(x, y)] for x, y in
                                 [(0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1)]])


def build(model, hidden):
    sizes = [dataset.N_OBS, 10] if model == "linear" else [dataset.N_OBS, hidden, hidden, 10]
    layers = []
    for i in range(len(sizes) - 1):
        layers.append(nn.Linear(sizes[i], sizes[i + 1]))
        if i < len(sizes) - 2:
            layers.append(nn.ReLU())
    return nn.Sequential(*layers), sizes


def to_game(net, sizes, meta):
    ws, bs = [], []
    for layer in net:
        if isinstance(layer, nn.Linear):
            ws.append(layer.weight.detach().numpy().astype(np.float32).reshape(-1).tolist())
            bs.append(layer.bias.detach().numpy().astype(np.float32).tolist())
    return {"sizes": sizes, "W": ws, "B": bs, "kick_bias": 0.0, "imitation": meta}


SELF_VEL = [2, 3]          # the controlled player's own speed: it gives away the key already held ("keep going" shortcut)


def hide_self_vel(net):
    """The first layer ignores the player's own speed (weights to 0), also when the game feeds it."""
    with torch.no_grad():
        net[0].weight[:, SELF_VEL] = 0.0


def fit(train, val, a, seed=0):
    """Trains on `train` (dict of arrays), early-stops on `val` (or a fixed number of epochs without it). Returns the net."""
    torch.manual_seed(seed)
    X, m, k = train["X"], train["move"], train["kick"]
    if a.hide_self_vel:
        X = X.copy()
        X[:, SELF_VEL] = 0.0
    if a.mirror:
        Xm, mm, km = dataset.mirror(X, m, k)
        X, m, k = np.concatenate([X, Xm]), np.concatenate([m, mm]), np.concatenate([k, km])
    net, sizes = build(a.model, a.hidden)
    opt = torch.optim.Adam(net.parameters(), lr=a.lr, weight_decay=a.wd)
    Xt, mt, kt = torch.from_numpy(X), torch.from_numpy(m), torch.from_numpy(k)
    best, best_state, bad = float("inf"), None, 0
    for ep in range(a.epochs):
        net.train()
        perm = torch.randperm(len(Xt))
        for i in range(0, len(perm), a.batch):
            idx = perm[i:i + a.batch]
            z = net(Xt[idx])
            loss = F.cross_entropy(z[:, :9], mt[idx]) + a.kick_w * F.binary_cross_entropy_with_logits(z[:, 9], kt[idx])
            opt.zero_grad()
            loss.backward()
            opt.step()
            if a.hide_self_vel:
                hide_self_vel(net)
        if val is not None:
            v = score(net, val)["nll"]
            if v < best - 1e-4:
                best, best_state, bad = v, {kk: vv.clone() for kk, vv in net.state_dict().items()}, 0
            else:
                bad += 1
                if bad >= a.patience:
                    break
    if best_state is not None:
        net.load_state_dict(best_state)
    net.epochs_run = ep + 1
    return net, sizes


def score(net, d):
    net.eval()
    with torch.no_grad():
        z = net(torch.from_numpy(d["X"]))
    lp = F.log_softmax(z[:, :9], 1).numpy()
    m = d["move"]
    top = np.argsort(-lp, 1)
    pk = 1 / (1 + np.exp(-z[:, 9].numpy()))
    pred_k, k = pk > 0.5, d["kick"] > 0.5
    tp = float((pred_k & k).sum())
    f1 = 2 * tp / max(1.0, float(pred_k.sum() + k.sum()))
    return {"rows": int(len(m)), "move_acc": float((top[:, 0] == m).mean()), "top2_acc": float(((top[:, 0] == m) | (top[:, 1] == m)).mean()),
            "nll": float(-lp[np.arange(len(m)), m].mean()), "kick_f1": f1, "kick_rate_pred": float(pk.mean()), "kick_rate_true": float(k.mean())}


def baselines(d):
    m = d["move"]
    X = d["X"]
    common = np.bincount(m, minlength=9).argmax()
    ball = X[:, 40:42] - X[:, 0:2]                          # ball minus me (normalised by the pitch; close enough for a direction)
    ball = ball / np.maximum(np.linalg.norm(ball, axis=1, keepdims=True), 1e-9)
    chase = np.argmax(ball @ UNIT[1:].T, 1) + 1
    return {"most_common_move": float((m == common).mean()), "run_at_ball": float((m == chase).mean())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=["linear", "mlp"], default="mlp")
    ap.add_argument("--hidden", type=int, default=128)
    ap.add_argument("--lag", type=int, default=3, help="decisions between the picture and the key (30 per second)")
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--patience", type=int, default=6)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--wd", type=float, default=1e-4)
    ap.add_argument("--kick_w", type=float, default=1.0)
    ap.add_argument("--no_mirror", dest="mirror", action="store_false")
    ap.add_argument("--control", default=None, help="only matches of this control mode (single / team)")
    ap.add_argument("--hide_self_vel", action="store_true", help="the model does not see its own player's speed")
    ap.add_argument("--folds", type=int, default=5, help="held-out evaluation: this many groups of whole matches")
    ap.add_argument("--name", required=True)
    a = ap.parse_args()
    t0 = time.time()
    d = dataset.load(lag=a.lag, control=a.control)
    n_m = len(d["names"])
    print("%d matches, %d rows, lag %d (%.0f ms)" % (n_m, len(d["move"]), a.lag, a.lag * 1000 / 30), flush=True)
    folds, epochs = [], []
    if n_m >= 2:
        k = min(a.folds, n_m)                           # groups of whole matches (shuffled, fixed seed)
        order = np.random.RandomState(0).permutation(n_m)
        for i in range(k):
            held = order[i::k]
            name = d["names"][held[0]] if len(held) == 1 else "%d matches (fold %d/%d)" % (len(held), i + 1, k)
            sel = np.isin(d["match"], held)
            tr, va = dataset.subset(d, ~sel), dataset.subset(d, sel)
            net, _ = fit(tr, va, a)
            s = {"held_out": name, **score(net, va), **{"baseline_" + k: v for k, v in baselines(va).items()}, "epochs": net.epochs_run}
            folds.append(s)
            epochs.append(net.epochs_run)
            print("  held out %s: move acc %.3f  top-2 %.3f  nll %.3f  kick F1 %.2f | most common %.3f, run at ball %.3f  (%d epochs)" % (
                name, s["move_acc"], s["top2_acc"], s["nll"], s["kick_f1"], s["baseline_most_common_move"], s["baseline_run_at_ball"], s["epochs"]), flush=True)
    # final model on every match, for as many epochs as the held-out runs needed
    a_final = argparse.Namespace(**vars(a))
    a_final.epochs = int(np.median(epochs)) if epochs else a.epochs
    net, sizes = fit(d, None, a_final)
    pooled = None
    if folds:
        w = np.array([f["rows"] for f in folds], float)
        pooled = {k: float(np.average([f[k] for f in folds], weights=w)) for k in folds[0] if isinstance(folds[0][k], float)}
    meta = {"name": a.name, "model": a.model, "hide_self_vel": a.hide_self_vel, "hidden": a.hidden if a.model == "mlp" else 0, "lag": a.lag, "mirror": a.mirror,
            "matches": d["names"], "rows": int(len(d["move"])), "epochs": a_final.epochs, "trained": time.strftime("%Y-%m-%dT%H:%M:%S")}
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, a.name + ".json"), "w") as f:
        json.dump(to_game(net, sizes, meta), f)
    with open(os.path.join(OUT, a.name + ".metrics.json"), "w") as f:
        json.dump({"meta": meta, "folds": folds, "pooled": pooled, "train": score(net, d)}, f, indent=1)
    if pooled:
        print("pooled held-out: move acc %.3f  top-2 %.3f  nll %.3f  kick F1 %.2f | baselines: most common %.3f, run at ball %.3f" % (
            pooled["move_acc"], pooled["top2_acc"], pooled["nll"], pooled["kick_f1"], pooled["baseline_most_common_move"], pooled["baseline_run_at_ball"]))
    print("saved out_il/%s.json (%d epochs, %.0f s)" % (a.name, a_final.epochs, time.time() - t0))


if __name__ == "__main__":
    main()
