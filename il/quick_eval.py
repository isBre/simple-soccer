"""Quick check of trained imitation models (il/train.py) in real matches: each model plays a fixed set of opponents spread over
the 5v5 ratings (2 seeds x both sides each, arena 90 s, five copies of the net, as the ratings' checkpoints), and gets a
provisional Elo against them, their ratings held fixed (elo/model.py rating_vs_fixed). Nothing is written to the ratings. Also the behaviour of the model's players (same definitions as rl/evaluate.py and il/analysis.py):
direction changes per second, idle %, kick presses per minute, shots, passes.

  python3 il/quick_eval.py out_il/a.json out_il/b.json [--seeds 2] [--workers 9]"""
import argparse
import json
import multiprocessing as mp
import os
import time

from lab import ladder

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OPPONENTS = ["player:daan_de_vries", "player:sam_taylor", "player:felix_wagner", "net:t46_best", "player:elias_berg", "net:t48_u100",
             "player:hugo_lindqvist", "net:team46_start", "net:x_anchor_wall_best", "player:leo_schneider"]


def play(job):
    me, opp, seed, my_side = job
    temp = me.get("temperature", 1.0)
    from elo.play import _team
    from soccer.data import database
    from soccer.core.public import AI_PERIOD, ENDED
    from soccer.game import MatchConfig, new_match
    from soccer.players import PlayerDef
    from soccer.teams import Team
    db = database()
    home, away = (me, opp) if my_side == 0 else (opp, me)
    c = MatchConfig()
    c.pitch = db.pitches["arena"]
    c.teams = [_team(home, db, PlayerDef, Team), _team(away, db, PlayerDef, Team)]
    c.team_size = 5
    c.duration = ladder.DURATION
    c.match_seed = seed
    m = new_match(c)
    for p in m.team_lists[my_side]:             # the model's own temperature (0 = always the most likely move); the opponent keeps 1
        if hasattr(p.brain, "temperature"):
            p.brain.temperature = temp
    st = {"n": 0, "chg": 0, "idle": 0, "rise": 0}
    prev, prevk = {}, {}
    while m.state != ENDED and m.tick < ladder.MAX_TICKS:
        m.step()
        if m.tick % AI_PERIOD == 0 and m.state == 0:
            for p in m.team_lists[my_side]:
                d = p.input_dir
                st["n"] += 1
                if abs(d - prev.get(p.uid, d)) > 0.3:
                    st["chg"] += 1
                if abs(d) < 0.1:
                    st["idle"] += 1
                if p.input_kick and not prevk.get(p.uid, False):
                    st["rise"] += 1
                prev[p.uid], prevk[p.uid] = d, p.input_kick
    res = m.make_result()
    ts = res["team_stats"][my_side]
    return {"opp": opp["id"], "seed": seed, "side": my_side, "gf": m.scores[my_side], "ga": m.scores[1 - my_side],
            "shots": ts["shots"], "passes": ts["passes"], "possession": ts["possession"], **st}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+")
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--temperature", type=float, nargs="+", default=[1.0], help="one evaluation per value (0 = greedy)")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args()
    from elo import api as elo_api, model
    r5 = elo_api.ratings(5)
    by = {i: e.spec() for i, e in r5.ros.entries.items()}
    report = {}
    for path, temp in [(p, t) for p in a.models for t in a.temperature]:
        stem = os.path.basename(path)[:-5] + ("" if temp == 1.0 else "@T%g" % temp)
        me = {**ladder.checkpoint_spec(os.path.abspath(path), "try:" + stem, stem), "temperature": temp}
        jobs = [(me, by[o], 1000 + 7919 * s + i, side) for i, o in enumerate(OPPONENTS) if o in by for s in range(a.seeds) for side in (0, 1)]
        t0 = time.time()
        with mp.get_context("spawn").Pool(a.workers) as pool:
            out = pool.map(play, jobs)
        elo, se = model.rating_vs_fixed([r5.rat[r["opp"]]["elo"] for r in out],
                                        [1.0 if r["gf"] > r["ga"] else 0.5 if r["gf"] == r["ga"] else 0.0 for r in out])
        rat = {"elo": elo, "lo": elo - 1.96 * se, "hi": elo + 1.96 * se, "w": sum(r["gf"] > r["ga"] for r in out),
               "d": sum(r["gf"] == r["ga"] for r in out), "l": sum(r["gf"] < r["ga"] for r in out),
               "gf": sum(r["gf"] for r in out), "ga": sum(r["ga"] for r in out)}
        n = sum(r["n"] for r in out)
        per_opp = {}
        for r in out:
            o = per_opp.setdefault(r["opp"], [0, 0, 0, 0, 0])
            o[0 if r["gf"] > r["ga"] else 1 if r["gf"] == r["ga"] else 2] += 1
            o[3] += r["gf"]
            o[4] += r["ga"]
        games = len(out)
        rep = {"elo": rat["elo"], "lo": rat["lo"], "hi": rat["hi"], "games": games, "w": rat["w"], "d": rat["d"], "l": rat["l"],
               "gf": rat["gf"], "ga": rat["ga"], "dir_changes_s": 30.0 * sum(r["chg"] for r in out) / n,
               "idle_pct": 100.0 * sum(r["idle"] for r in out) / n, "kick_presses_min": 1800.0 * sum(r["rise"] for r in out) / n,
               "shots_match": sum(r["shots"] for r in out) / games, "passes_match": sum(r["passes"] for r in out) / games,
               "possession": sum(r["possession"] for r in out) / games, "per_opponent": per_opp, "seconds": time.time() - t0}
        report[stem] = rep
        print("%-20s Elo %4.0f [%4.0f-%4.0f]  W-D-L %d-%d-%d  goals %d-%d | changes/s %.1f  idle %.0f%%  kicks/min %.1f  shots %.1f  passes %.1f  poss %.0f%%  (%.0f s)" % (
            stem, rep["elo"], rep["lo"], rep["hi"], rep["w"], rep["d"], rep["l"], rep["gf"], rep["ga"], rep["dir_changes_s"], rep["idle_pct"],
            rep["kick_presses_min"], rep["shots_match"], rep["passes_match"], rep["possession"], rep["seconds"]), flush=True)
        for o in OPPONENTS:
            if o in per_opp:
                w, dd, l, gf, ga = per_opp[o]
                print("     vs %-24s %4.0f  %d-%d-%d  %d-%d" % (o, base[o]["elo"], w, dd, l, gf, ga))
    os.makedirs(os.path.join(ROOT, "out_il"), exist_ok=True)
    with open(os.path.join(ROOT, "out_il", "quick_eval.json"), "w") as f:
        json.dump(report, f, indent=1)


if __name__ == "__main__":
    main()
