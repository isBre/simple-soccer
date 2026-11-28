"""The "seat" test of an imitation model (il/train.py): the model plays ONE player of a rule-based team (the seat the user
played in when recording: the forward by default) and the team's AI plays the other four, exactly the situation of the data.
The same matches (same seeds, both sides) are played without the swap, so the difference is the model vs the AI forward.

  python3 il/seat_eval.py out_il/a.json [--team owls] [--role FWD] [--temperature 1 0] [--seeds 3]"""
import argparse
import multiprocessing as mp
import os

OPPONENTS = ["cobalt", "fern", "owls", "rose", "aurora", "tide"]


def play(job):
    team, opp, seed, side, model, temp, role = job
    from soccer.ai import nets
    from soccer.core.public import AI_PERIOD, ENDED
    from soccer.game import make_config, new_match
    c = make_config(team, opp, "arena", 5, 90.0, seed) if side == 0 else make_config(opp, team, "arena", 5, 90.0, seed)
    m = new_match(c)
    seat = None
    if model:
        seat = next(p for p in m.team_lists[side] if p.line == role)          # the player on that formation spot
        m.seat(seat.uid, nets.NetBot(nets.load({"model": model}), temp))
    chg = n = 0
    prev = None
    near = 0
    while m.state != ENDED and m.tick < 90 * 60 * 4:          # a kickoff the model never takes would stop the clock forever
        m.step()
        if seat is not None and m.tick % AI_PERIOD == 0 and m.state == 0:
            n += 1
            if prev is not None and abs(seat.input_dir - prev) > 0.3:
                chg += 1
            prev = seat.input_dir
            near += abs(seat.pos - m.ball.pos) < 40.0
    r = m.make_result()
    me = [p for p in r["players"] if p["team"] == side]
    seat_stats = next((p for p in me if seat is not None and p["uid"] == seat.uid), None)
    return {"stalled": m.state != ENDED, "gf": m.scores[side], "ga": m.scores[1 - side], "changes_s": 30.0 * chg / n if n else None,
            "on_ball_pct": 100.0 * near / n if n else None, "seat": seat_stats and {k: seat_stats.get(k) for k in ("goals", "shots", "touches", "rating")}}


def run(team, model, temp, role, seeds, workers):
    jobs = [(team, o, 5000 + 31 * s + i, side, model, temp, role) for i, o in enumerate(OPPONENTS) for s in range(seeds) for side in (0, 1)]
    with mp.get_context("spawn").Pool(workers) as pool:
        return pool.map(play, jobs)


def summary(out):
    g = len(out)
    pts = sum(3 if r["gf"] > r["ga"] else 1 if r["gf"] == r["ga"] else 0 for r in out) / g
    return pts, sum(r["gf"] - r["ga"] for r in out) / g, sum(r["gf"] for r in out) / g, sum(r["ga"] for r in out) / g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+")
    ap.add_argument("--team", default="owls")
    ap.add_argument("--role", default="FWD")
    ap.add_argument("--temperature", type=float, nargs="+", default=[1.0])
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args()
    base = run(a.team, None, 1.0, a.role, a.seeds, a.workers)
    pts, gd, gf, ga = summary(base)
    print("%-22s pts/game %.2f  GD %+.2f  (%.2f-%.2f)   [%s, all AI, %d games vs %s]" % ("AI %s (baseline)" % a.role, pts, gd, gf, ga, a.team, len(base), ", ".join(OPPONENTS)))
    for path in a.models:
        for t in a.temperature:
            out = run(a.team, os.path.abspath(path), t, a.role, a.seeds, a.workers)
            pts, gd, gf, ga = summary(out)
            d = [r["gf"] - r["ga"] - (b["gf"] - b["ga"]) for r, b in zip(out, base)]
            mean = sum(d) / len(d)
            se = (sum((x - mean) ** 2 for x in d) / (len(d) - 1) / len(d)) ** 0.5
            sg = [r["seat"] for r in out if r["seat"]]
            print("%-22s pts/game %.2f  GD %+.2f  (%.2f-%.2f)  paired GD diff %+.2f ± %.2f | seat: changes/s %.1f  on ball %.0f%%  goals %.2f  shots %.2f  touches %.0f  grade %.1f" % (
                os.path.basename(path)[:-5] + ("@T%g" % t if t != 1 else ""), pts, gd, gf, ga, mean, se,
                sum(r["changes_s"] for r in out if r["changes_s"] is not None) / max(1, sum(r["changes_s"] is not None for r in out)), sum(r["on_ball_pct"] for r in out) / len(out),
                sum(s["goals"] for s in sg) / len(sg), sum(s["shots"] for s in sg) / len(sg), sum(s["touches"] for s in sg) / len(sg),
                sum(s["rating"] for s in sg) / len(sg)) + ("  STALLED kickoffs: %d" % sum(r["stalled"] for r in out) if any(r["stalled"] for r in out) else ""), flush=True)


if __name__ == "__main__":
    main()
