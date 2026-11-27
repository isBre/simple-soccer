"""Strength and way of playing of one team against the field: every other team of the Rule Based League (and optionally the RL
teams), both sides, several seeds, played by the match core in parallel. Also measures whether the team plays as a team
(spacing, players around the ball, passes, assisted goals) instead of swarming the ball.

  python3 tools/team_bench.py arrows [--seeds 4] [--duration 180] [--pitch arena] [--size 5] [--rl] [--vs arrows,aurora]
  Opponents in --vs can be team ids or trained nets: net:models/jit8_best.json (played in RL Team 5's shirts).
"""
import argparse
import multiprocessing as mp
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from soccer.data import database                    # noqa: E402
from soccer.match import ENDED, PLAYING, Match, make_config   # noqa: E402

NEAR = 120.0          # px: "around the ball"


def play(args):
    team, opp, side, seed, duration, pitch, size = args
    net = None
    opp_team = opp
    if opp.startswith("net:"):            # a trained net (data/models/*.json or models/*.json) in RL Team 5's shirts
        net = {"model": os.path.join(ROOT, opp[4:])}
        opp_team = "rl_team_5"
    a, b = (team, opp_team) if side == 0 else (opp_team, team)
    cfg = make_config(a, b, pitch, size, duration, seed)
    if net is not None:
        cfg.nets[1 - side] = net
    m = Match(cfg)
    t = side
    keeper = lambda: m.keeper_uid[t]
    samples = near_sum = swarm = spread_sum = 0
    near_opp = 0
    while m.state != ENDED and m.tick < 60 * 60 * 8:
        m.step()
        if m.state != PLAYING or m.kickoff_active or m.tick % 10:
            continue
        outs = [p for p in m.team_lists[t] if p.uid != keeper()]
        ball = m.ball_pos
        n = sum(1 for p in outs if abs(p.pos - ball) < NEAR)
        no = sum(1 for p in m.team_lists[1 - t] if p.uid != m.keeper_uid[1 - t] and abs(p.pos - ball) < NEAR)
        d, k = 0.0, 0
        for i in range(len(outs)):
            for j in range(i + 1, len(outs)):
                d += abs(outs[i].pos - outs[j].pos)
                k += 1
        samples += 1
        near_sum += n
        near_opp += no
        swarm += n >= 3
        spread_sum += d / max(k, 1)
    if m.state != ENDED:
        m._end_match()
    gf, ga = m.scores[t], m.scores[1 - t]
    ps = [m.stats.get_player(p.uid) for p in m.team_lists[t]]
    goals = sum(s.goals for s in ps)
    assists = sum(s.assists for s in ps)
    return {"opp": opp, "side": side, "seed": seed, "gf": gf, "ga": ga, "samples": samples, "near": near_sum, "near_opp": near_opp,
            "swarm": swarm, "spread": spread_sum, "passes_ok": sum(s.passes_ok for s in ps),
            "passes": sum(s.passes_ok + s.passes_failed for s in ps), "shots": sum(s.shots for s in ps), "xg": sum(s.xg for s in ps),
            "goals": goals, "assists": assists,
            "poss": m.stats.possession_ticks[t] / max(1, sum(m.stats.possession_ticks))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("team")
    ap.add_argument("--seeds", type=int, default=4)
    ap.add_argument("--seed0", type=int, default=1000)
    ap.add_argument("--duration", type=float, default=180.0)
    ap.add_argument("--pitch", default="arena")
    ap.add_argument("--size", type=int, default=5)
    ap.add_argument("--rl", action="store_true", help="also play the RL league teams")
    ap.add_argument("--vs", default="", help="comma-separated opponents instead of the whole league")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2, help="parallel matches (fewer = cooler laptop)")
    a = ap.parse_args()
    db = database()
    if a.vs:
        opps = a.vs.split(",")
    else:
        opps = sorted((t for t in db.teams.values() if t.league == "rules" and t.id != a.team), key=lambda t: -t.strength())
        opps = [t.id for t in opps]
        if a.rl:
            opps += [t.id for t in db.teams.values() if t.league == "rl" and t.id in ("rl_team_4", "rl_team_5")]
    jobs = [(a.team, o, side, a.seed0 + s * 7 + i * 101, a.duration, a.pitch, a.size)
            for i, o in enumerate(opps) for side in (0, 1) for s in range(a.seeds)]
    t0 = time.time()
    with mp.get_context("fork").Pool(a.workers) as pool:
        res = pool.map(play, jobs, chunksize=1)
    by = {}
    for r in res:
        by.setdefault(r["opp"], []).append(r)
    tot = {"w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "n": 0}
    print("%-12s %3s %3s %3s  %5s  %9s" % ("opponent", "W", "D", "L", "pts/m", "GF/GA"))
    for o in opps:
        rs = by[o]
        w = sum(r["gf"] > r["ga"] for r in rs)
        d = sum(r["gf"] == r["ga"] for r in rs)
        l = len(rs) - w - d
        gf, ga = sum(r["gf"] for r in rs), sum(r["ga"] for r in rs)
        print("%-12s %3d %3d %3d  %5.2f  %4.2f/%4.2f" % (o, w, d, l, (3 * w + d) / len(rs), gf / len(rs), ga / len(rs)))
        for k, v in (("w", w), ("d", d), ("l", l), ("gf", gf), ("ga", ga), ("n", len(rs))):
            tot[k] += v
    n = tot["n"]
    print("TOTAL        %3d %3d %3d  %5.2f  %4.2f/%4.2f   (%d matches, %.0f s)" % (
        tot["w"], tot["d"], tot["l"], (3 * tot["w"] + tot["d"]) / n, tot["gf"] / n, tot["ga"] / n, n, time.time() - t0))
    S = sum(r["samples"] for r in res)
    goals = sum(r["goals"] for r in res)
    print("STYLE  players<=%dpx of ball %.2f (opponents %.2f) | 3+ around ball %.1f%% | mean spacing %.0f px | passes/m %.1f "
          "(%.0f%% ok) | shots/m %.1f xG/m %.2f | assisted goals %.0f%% | possession %.0f%%" % (
              NEAR, sum(r["near"] for r in res) / S, sum(r["near_opp"] for r in res) / S, 100.0 * sum(r["swarm"] for r in res) / S,
              sum(r["spread"] for r in res) / S, sum(r["passes"] for r in res) / n,
              100.0 * sum(r["passes_ok"] for r in res) / max(1, sum(r["passes"] for r in res)),
              sum(r["shots"] for r in res) / n, sum(r["xg"] for r in res) / n,
              100.0 * sum(r["assists"] for r in res) / max(1, goals), 100.0 * sum(r["poss"] for r in res) / n))


if __name__ == "__main__":
    main()
