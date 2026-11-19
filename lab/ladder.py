"""The Elo ranking: one rating for every team of every league (rule-based, RL, and later ML / DL), from matches between them.

Why: points against the rule bots saturate at 3, so they cannot rank good teams (docs/imitation_plan.md, Evaluation level 3).

Who is ranked (roster(), rebuilt every time from the files):
  rules:<team>   every handmade team of data/teams (its own squad)
  team:<team>    every team of data/teams with a net (`ml_model`: RL Team 1-5, later the ML / DL league teams), its own squad
  net:<stem>     every net in models/*.json (best checkpoint of each run, jit8, t48_u100, the distilled starts) and the best checkpoint
                 of every finished run still only in out_5v5/ckpt/ (x_<run>_best.json); played with RL Team 5's squad, as the Live page does
Each entry carries the sha1 of its file: when a file changes (a re-exported net, an edited team), its old results are no longer used.

How matches are chosen (choose_pairs()): a round picks pairs that tell the most: an entry with fewer than PLACEMENT games is placed
first (against opponents spread over the ranking), then pairs with close ratings, uncertain ratings and few games between them.
Each pair plays twice with the same seed, once from each side (the side and kickoff noise cancel). 5v5 on the arena, 90 s, draws
allowed. Results: exp/ladder.jsonl, one line per match (append only).

How ratings are computed (fit()): Bradley-Terry on all stored results at once (win 1, draw 0.5, loss 0), on the Elo scale
(400 points = 10:1 odds), with a weak prior (each rating ~ N(1500, 400)) so a team that never lost stays finite. The order of the
matches does not matter, and every rating gets a 95% interval from the curvature of the likelihood. A snapshot of the ratings after
each round goes to exp/ladder_ratings.jsonl (the history chart).

  python3 lab/ladder.py roster                         the entries and their files
  python3 lab/ladder.py round [--pairs 8] [--workers 3] one round (2 matches per pair), then the new ratings
  python3 lab/ladder.py ratings                        the ranking (JSON)
The runner (lab/exp_runner.py --loop) plays a round whenever the queue is empty (exp/ladder_off disables it)."""
import argparse
import glob
import hashlib
import json
import math
import multiprocessing as mp
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

EXP = os.path.join(ROOT, "exp")
RESULTS = os.path.join(EXP, "ladder.jsonl")
HISTORY = os.path.join(EXP, "ladder_ratings.jsonl")
OFF = os.path.join(EXP, "ladder_off")
NET_SQUAD = "rl_team_5"
PROTOCOL = "ladder/d90"
DURATION = 90.0
PLACEMENT = 6                    # games before an entry counts as placed
BASE, PRIOR_SD = 1500.0, 400.0
K = 400.0 / math.log(10.0)       # Elo points per unit of the logistic scale


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()[:10]


def _finished(run):
    try:
        st = json.load(open(os.path.join(EXP, "runs", run, "status.json")))
    except (OSError, ValueError):
        return False
    return st.get("state") not in ("running", "queued", None)


def roster():
    """Every entry that can be ranked now: {id, name, league, kind, team, model (path from ROOT or None), sha}."""
    from soccer.data import database
    db = database()
    out = []
    for t in sorted(db.teams.values(), key=lambda t: t.id):
        path = os.path.join(ROOT, "data", "teams", t.id + ".json")
        sha = _sha(path) if os.path.exists(path) else ""
        if t.ml_model:
            model = t.ml_model[6:] if t.ml_model.startswith("res://") else t.ml_model
            if os.path.exists(os.path.join(ROOT, model)):
                sha += _sha(os.path.join(ROOT, model))
            out.append({"id": "team:" + t.id, "name": t.name, "league": t.league, "kind": "team", "team": t.id, "model": model, "sha": sha})
        else:
            out.append({"id": "rules:" + t.id, "name": t.name, "league": t.league, "kind": "rules", "team": t.id, "model": None, "sha": sha})
    seen = set()
    nets = sorted(glob.glob(os.path.join(ROOT, "models", "*.json")))
    nets += [f for f in sorted(glob.glob(os.path.join(ROOT, "out_5v5", "ckpt", "x_*_best.json"))) if _finished(os.path.basename(f)[2:-10])]
    for f in nets:
        stem = os.path.basename(f)[:-5]
        if stem in seen:
            continue
        try:
            with open(f) as fh:
                head = json.load(fh)
            if "sizes" not in head:
                continue
        except (OSError, ValueError):
            continue
        seen.add(stem)
        label = ("run " + stem[2:-5] + " (best)") if stem.startswith("x_") and stem.endswith("_best") else stem
        out.append({"id": "net:" + stem, "name": label, "league": "rl", "kind": "net", "team": NET_SQUAD,
                    "model": os.path.relpath(f, ROOT), "sha": _sha(f), "inputs": head["sizes"][0], "width": head["sizes"][1]})
    return out


def results(path=RESULTS):
    out = []
    try:
        with open(path) as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def valid(res, ros):
    """The results that still count: both entries are in the roster with the same files."""
    sha = {e["id"]: e["sha"] for e in ros}
    return [r for r in res if r.get("protocol") == PROTOCOL and sha.get(r["a"]) == r.get("a_sha") and sha.get(r["b"]) == r.get("b_sha")]


def _score(r):
    return 1.0 if r["ga"] > r["gb"] else (0.5 if r["ga"] == r["gb"] else 0.0)


def fit(ros=None, res=None):
    """Ratings of every roster entry: {id: {elo, se, lo, hi, games, w, d, l, gf, ga, pts}} (MAP Bradley-Terry with a N(0, PRIOR_SD)
    prior, Newton's method; se from the inverse Hessian)."""
    import numpy as np
    ros = roster() if ros is None else ros
    res = valid(results() if res is None else res, ros)
    ids = [e["id"] for e in ros]
    ix = {k: i for i, k in enumerate(ids)}
    n = len(ids)
    a = np.array([ix[r["a"]] for r in res], dtype=int)
    b = np.array([ix[r["b"]] for r in res], dtype=int)
    s = np.array([_score(r) for r in res])
    tau = PRIOR_SD / K
    th = np.zeros(n)
    H = -np.eye(n) / tau ** 2
    for _ in range(50):
        p = 1.0 / (1.0 + np.exp(-(th[a] - th[b])))
        g = -th / tau ** 2
        np.add.at(g, a, s - p)
        np.add.at(g, b, p - s)
        w = p * (1 - p)
        H = -np.eye(n) / tau ** 2
        np.add.at(H, (a, a), -w)
        np.add.at(H, (b, b), -w)
        np.add.at(H, (a, b), w)
        np.add.at(H, (b, a), w)
        step = np.linalg.solve(H, g)
        th -= step
        if np.max(np.abs(step)) < 1e-9:
            break
    se = np.sqrt(np.maximum(np.diag(np.linalg.inv(-H)), 0.0))
    out = {}
    for k, i in ix.items():
        out[k] = {"elo": BASE + K * th[i], "se": K * se[i], "games": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0}
        out[k]["lo"], out[k]["hi"] = out[k]["elo"] - 1.96 * out[k]["se"], out[k]["elo"] + 1.96 * out[k]["se"]
    for r in res:
        for me, gf, ga in ((r["a"], r["ga"], r["gb"]), (r["b"], r["gb"], r["ga"])):
            o = out[me]
            o["games"] += 1
            o["gf"] += gf
            o["ga"] += ga
            o["w" if gf > ga else ("d" if gf == ga else "l")] += 1
    for o in out.values():
        o["pts"] = (3 * o["w"] + o["d"]) / o["games"] if o["games"] else None
    return out


def choose_pairs(ros, res, k, rng):
    """Up to k pairs for the next round (an entry plays in at most 2 of them)."""
    rat = fit(ros, res)
    games = {}
    for r in valid(res, ros):
        key = tuple(sorted((r["a"], r["b"])))
        games[key] = games.get(key, 0) + 1
    ids = [e["id"] for e in ros]
    order = sorted(ids, key=lambda i: rat[i]["elo"])
    load, pairs = {}, []

    def add(i, j):
        pairs.append((i, j))
        load[i] = load.get(i, 0) + 1
        load[j] = load.get(j, 0) + 1

    new = sorted([i for i in ids if rat[i]["games"] < PLACEMENT], key=lambda i: (rat[i]["games"], rng.random()))
    placed = [i for i in order if rat[i]["games"] >= PLACEMENT] or order
    for i in new:
        if len(pairs) >= k:
            break
        if load.get(i, 0) >= 2:
            continue
        cands = [j for j in placed if j != i and load.get(j, 0) < 2 and games.get(tuple(sorted((i, j))), 0) == 0] or \
                [j for j in placed if j != i and load.get(j, 0) < 2]
        if cands:                                   # spread over the ranking: a random quantile each time
            add(i, cands[min(len(cands) - 1, int(rng.random() * len(cands)))])
    scored = []
    for x in range(len(ids)):
        for y in range(x + 1, len(ids)):
            i, j = ids[x], ids[y]
            p = 1.0 / (1.0 + 10 ** ((rat[j]["elo"] - rat[i]["elo"]) / 400.0))
            info = p * (1 - p) * (rat[i]["se"] ** 2 + rat[j]["se"] ** 2) / (1 + games.get((min(i, j), max(i, j)), 0))
            scored.append((info * (0.9 + 0.2 * rng.random()), i, j))
    for _, i, j in sorted(scored, reverse=True):
        if len(pairs) >= k:
            break
        if load.get(i, 0) < 2 and load.get(j, 0) < 2 and (i, j) not in pairs and (j, i) not in pairs:
            add(i, j)
    return pairs


def _setup(e, side_cfg, side):
    side_cfg.nets[side] = {"model": os.path.join(ROOT, e["model"])} if e["model"] else None


def play_pair(job):
    """Worker: both legs of one pair (same seed, sides swapped). Returns two result records."""
    ea, eb, seed = job
    from soccer.match import Match, make_config
    out = []
    for home, away in ((ea, eb), (eb, ea)):
        c = make_config(home["team"], away["team"], "arena", 5, DURATION, seed)
        _setup(home, c, 0)
        _setup(away, c, 1)
        m = Match(c)
        m.run_to_end()
        g = {home["id"]: m.scores[0], away["id"]: m.scores[1]}
        out.append({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "protocol": PROTOCOL, "seed": seed, "a": ea["id"], "b": eb["id"],
                    "a_sha": ea["sha"], "b_sha": eb["sha"], "a_side": 0 if home is ea else 1, "ga": g[ea["id"]], "gb": g[eb["id"]]})
    return out


def _nice():
    try:
        os.nice(10)                        # a ladder round never starves training on the Pi
    except OSError:
        pass


def play_round(pairs_n=8, workers=3, path=RESULTS, seed=None):
    ros = roster()
    rng = random.Random(seed)
    pairs = choose_pairs(ros, results(path), pairs_n, rng)
    by = {e["id"]: e for e in ros}
    jobs = [(by[i], by[j], rng.randrange(1, 1 << 31)) for i, j in pairs]
    t0 = time.time()
    if workers > 1 and len(jobs) > 1:
        with mp.get_context("spawn").Pool(min(workers, len(jobs)), initializer=_nice) as pool:
            recs = [r for pair in pool.map(play_pair, jobs) for r in pair]
    else:
        _nice()
        recs = [r for j in jobs for r in play_pair(j)]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    rat = fit(ros, results(path))
    if path == RESULTS:
        with open(HISTORY, "a") as f:
            f.write(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "matches": len(valid(results(path), ros)),
                                "elo": {k: round(v["elo"], 1) for k, v in rat.items() if v["games"]}}) + "\n")
    return {"matches": len(recs), "seconds": round(time.time() - t0, 1), "pairs": pairs, "ratings": rat}


def ranking(path=RESULTS):
    """The table of the Ranking page and of `lab.py ranking`: entries sorted by rating, with their league and record."""
    ros = roster()
    res = results(path)
    rat = fit(ros, res)
    rows = []
    for e in ros:
        r = rat[e["id"]]
        rows.append({**{k: e[k] for k in ("id", "name", "league", "kind", "model") if k in e},
                     **{k: (round(v, 1) if isinstance(v, float) else v) for k, v in r.items()}, "placed": r["games"] >= PLACEMENT})
    rows.sort(key=lambda x: -x["elo"])
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    hist = []
    try:
        with open(HISTORY) as f:
            hist = [json.loads(l) for l in f if l.strip()]
    except (OSError, ValueError):
        pass
    v = valid(res, ros)
    return {"protocol": PROTOCOL, "matches": len(v), "stale": len(res) - len(v), "entries": len(rows), "rows": rows,
            "history": hist[-400:], "off": os.path.exists(OFF), "last": v[-1]["t"] if v else None,
            "recent": v[-30:]}


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("roster")
    p = sub.add_parser("round")
    p.add_argument("--pairs", type=int, default=8)
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--rounds", type=int, default=1)
    p.add_argument("--out", default=RESULTS, help="results file (default exp/ladder.jsonl; another file = a test, no history)")
    sub.add_parser("ratings")
    a = ap.parse_args()
    if a.cmd == "roster":
        for e in roster():
            print("%-34s %-6s %-6s %s" % (e["id"], e["league"], e["kind"], e["model"] or ""))
    elif a.cmd == "round":
        for k in range(a.rounds):
            r = play_round(a.pairs, a.workers, path=os.path.abspath(a.out), seed=None if a.seed is None else a.seed + k)
            print("round %d: %d matches in %.0f s" % (k + 1, r["matches"], r["seconds"]), flush=True)
        rk = ranking(os.path.abspath(a.out))
        for row in rk["rows"]:
            print("%3d %-34s %6.0f ± %3.0f  %3d games" % (row["rank"], row["id"], row["elo"], 1.96 * row["se"], row["games"]))
    else:
        print(json.dumps(ranking(), indent=1))


if __name__ == "__main__":
    main()
