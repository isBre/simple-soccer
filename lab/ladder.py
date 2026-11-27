"""The Lab's view of the ratings (elo/, docs/ratings.md): the experiment ladder is this machine's 5v5 ratings. The ratings
themselves (who is rated, the model, the database in local/elo.db, the rounds) live in elo/; this module keeps what the Lab, the
runner and lab.py ask for:

  rows()           the 5v5 ratings by entry id (also under "net:<stem>" for a net that is a player's: jit8_best is Jasper Klein)
  ranking()        the Ranking page's table (lab/dashboard.py /api/ranking, lab.py ranking)
  estimate()       the estimated Elo of a checkpoint during training: it plays placed entries of the size it trains (default 5v5)
                   and only its own rating and goal strengths are fitted, everyone else's held fixed (not stored in the
                   ratings): one line in exp/elo_estimates.jsonl (with its size)
  estimates()      the stored estimates
  round            python3 lab/ladder.py round [--size 5] [--pairs 8] [--workers 3]: rounds of the ratings (elo.api.play_round)

Entries: player:<id> (every player, rule-based or net), team:<id> (teams; one player five times = that player's numbers),
net:<stem> (training checkpoints: models/*.json that is no player's net, the best checkpoint of every finished run).
Estimates before 2026-11-27 were made against the old team ladder (exp/ladder.jsonl, archived): another scale.

  python3 lab/ladder.py roster | round | ratings | estimate --model M --tag T --update U [--pairs 12] [--size 5]"""
import argparse
import hashlib
import json
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from elo import DURATION, MAX_TICKS, PLACEMENT, PROTOCOL as ELO_PROTOCOL, api as elo_api, model, play, roster as elo_roster  # noqa: E402

EXP = os.path.join(ROOT, "exp")
SIZE = 5                          # the experiments are 5v5 (the curriculum will add sizes)
PROTOCOL = "ladder/5v5/" + ELO_PROTOCOL
ESTIMATES = os.path.join(EXP, "elo_estimates.jsonl")
EST_PAIRS = 12                    # pairs per estimate (2 matches each): about ±140 Elo at 95%
__all__ = ["DURATION", "MAX_TICKS", "PLACEMENT", "rows", "ranking", "estimate", "estimates"]


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()[:10]


def rows(size=SIZE):
    """{entry id: table row} of the ratings (elo.api.table), with aliases: a uniform team's id and "net:<stem>" for players' nets."""
    out = {x["id"]: x for x in elo_api.table(size)}
    ros = elo_roster.get()
    for stem, eid in ros.by_model.items():
        if eid in out and "net:" + stem not in out:
            out["net:" + stem] = {**out[eid], "id": "net:" + stem, "via": eid}
    return out


def ranking(size=SIZE):
    """The Ranking page's table: elo.api.ranking with the Lab's protocol name ("off": local/refine_off, elo.api.rounds_off)."""
    r = elo_api.ranking(size)
    r["protocol"] = "ladder/%dv%d/%s" % (size, size, ELO_PROTOCOL)
    return r


def _summarise(recs, r):
    opp = [(x["b"], x["ga"], x["gb"]) for x in recs]
    rat, gm = r.rat, r.gm
    elo, se = model.rating_vs_fixed([rat[o]["elo"] for o, _, _ in opp], [1.0 if gf > ga else 0.5 if gf == ga else 0.0 for _, gf, ga in opp])
    att = model.strength_vs_fixed([gm["mu"] - gm["def"][o][0] for o, _, _ in opp], [gf for _, gf, _ in opp], +1)
    dfn = model.strength_vs_fixed([gm["mu"] + gm["att"][o][0] for o, _, _ in opp], [ga for _, _, ga in opp], -1)
    w = sum(1 for _, gf, ga in opp if gf > ga)
    d = sum(1 for _, gf, ga in opp if gf == ga)
    return {"elo": round(elo, 1), "se": round(se, 1), "lo": round(elo - 1.96 * se, 1), "hi": round(elo + 1.96 * se, 1),
            **{k: (round(v, 3) if v is not None else None) for k, v in model.adjusted_goals(gm, att, dfn).items()},
            "games": len(opp), "w": w, "d": d, "l": len(opp) - w - d,
            "raw_gf": round(sum(gf for _, gf, _ in opp) / len(opp), 3), "raw_ga": round(sum(ga for _, _, ga in opp) / len(opp), 3)}


def checkpoint_spec(model_path, eid, name):
    """A net checkpoint as an entry spec for elo.play (five copies of the net)."""
    full = model_path if os.path.isabs(model_path) else os.path.join(ROOT, model_path)
    rel = os.path.relpath(full, ROOT)
    return {"id": eid, "name": name, "sha": _sha(full), "lineup": [{"id": "ckpt:" + os.path.basename(rel)[:-5], "model": rel}] * 5}


def estimate(model_path, tag, update, pairs=EST_PAIRS, workers=3, seed=None, path=ESTIMATES, size=SIZE):
    """Estimated Elo of a checkpoint during training: it plays `pairs` placed entries of `size` (2 matches each, sides swapped) and only
    its own rating is fitted, everyone else's held at their current ratings (nothing is stored in the ratings). Opponents are mixed:
    the first half spread over the whole ranking (one random entry from each slice), the second half near the rating that first
    half gave (drawn with weight p(1-p): close games tell the most). Goals are adjusted with the ratings' goal model."""
    t0 = time.time()
    r = elo_api.ratings(size)
    ros = r.ros
    placed = sorted([i for i, v in r.rat.items() if v["games"] >= PLACEMENT], key=lambda i: r.rat[i]["elo"])
    if not placed:
        raise SystemExit("the %dv%d ratings have no placed entries yet: python3 -m elo init" % (size, size))
    me = checkpoint_spec(model_path, "est:%s_u%d" % (tag, update), "%s u%d" % (tag, update))
    rng = random.Random(seed if seed is not None else hash((tag, update)) & 0xFFFFFFFF)
    pairs = min(pairs, len(placed))
    n1 = max(1, pairs // 2)
    first = list(dict.fromkeys(placed[min(len(placed) - 1, int((k + rng.random()) * len(placed) / n1))] for k in range(n1)))
    recs = play.play([(me, ros.entries[o].spec(), size, rng.randrange(1, 1 << 31)) for o in first], workers)
    if pairs > len(first):
        mid = _summarise(recs, r)["elo"]
        left = [o for o in placed if o not in first]
        chosen = []
        while left and len(first) + len(chosen) < pairs:
            wts = [max(1e-6, (lambda p: p * (1 - p))(1.0 / (1.0 + 10 ** ((r.rat[o]["elo"] - mid) / 400.0)))) for o in left]
            x, acc = rng.random() * sum(wts), 0.0
            for o, wgt in zip(left, wts):
                acc += wgt
                if acc >= x:
                    break
            chosen.append(o)
            left.remove(o)
        recs += play.play([(me, ros.entries[o].spec(), size, rng.randrange(1, 1 << 31)) for o in chosen], workers)
    out = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "protocol": "estimate/ladder/%dv%d/%s" % (size, size, ELO_PROTOCOL), "tag": tag,
           "run": tag[2:] if tag.startswith("x_") else tag, "update": update, "size": size, "model": me["lineup"][0]["model"], "sha": me["sha"], **_summarise(recs, r),
           "seconds": round(time.time() - t0, 1), "ladder_matches": r.matches,
           "matches": [{"opp": x["b"], "opp_elo": round(r.rat[x["b"]]["elo"]), "gf": x["ga"], "ga": x["gb"], "side": x["a_side"], "seed": x["seed"]} for x in recs]}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(out) + "\n")
    return out


def estimates(path=ESTIMATES, run=None):
    """The stored estimates (one per checkpoint; a repeated one replaces the older line), optionally of one run, in update order."""
    by = {}
    try:
        with open(path) as f:
            for line in f:
                try:
                    x = json.loads(line)
                except ValueError:
                    continue
                if run is None or x.get("run") == run:
                    by[(x.get("run"), x.get("update"))] = x
    except OSError:
        pass
    return sorted(by.values(), key=lambda x: (x.get("run") or "", x.get("update") or 0))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("roster")
    p = sub.add_parser("round")
    p.add_argument("--pairs", type=int, default=8)
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--size", type=int, default=None, help="default: the size that needs it most")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--rounds", type=int, default=1)
    sub.add_parser("ratings")
    p = sub.add_parser("estimate", help="estimated Elo of one checkpoint (not added to the ratings)")
    p.add_argument("--model", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--update", type=int, required=True)
    p.add_argument("--pairs", type=int, default=EST_PAIRS)
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--out", default=ESTIMATES)
    p.add_argument("--size", type=int, default=SIZE, help="the team size it plays (the size the run trains)")
    a = ap.parse_args()
    if a.cmd == "roster":
        for i, e in sorted(elo_roster.get().entries.items()):
            print("%-40s %-7s sizes %s %s" % (i, e.kind, "".join(map(str, e.sizes())), e.model or ""))
    elif a.cmd == "round":
        for k in range(a.rounds):
            r = elo_api.play_round(a.pairs, a.workers, a.size, None if a.seed is None else a.seed + k)
            print("round %d: %s %d matches in %.0f s" % (k + 1, "%dv%d" % (r["size"], r["size"]) if r["size"] else "-", r["matches"], r["seconds"]), flush=True)
    elif a.cmd == "estimate":
        r = estimate(a.model, a.tag, a.update, a.pairs, a.workers, a.seed, os.path.abspath(a.out), a.size)
        print(json.dumps({k: v for k, v in r.items() if k != "matches"}))
    else:
        print(json.dumps(ranking(), indent=1, default=float))


if __name__ == "__main__":
    main()
