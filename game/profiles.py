"""How every team of the game plays: a scouting profile per team, the source of the one-line description on the team-select screen
(game/api.py describe()).

Each team plays PROFILE_MATCHES matches of 60 s, 5v5 on the arena, on the left side, against four mid-table rule teams (the same
opponents as the scout of rl/evaluate.py behaviour_stats); the scout recorder of rl/evaluate.py measures it (possession, territory,
pressing, passing, shots, keeper). The scalars go to data/team_profiles.json with the sha of the files they were measured on (a
re-exported net or an edited team marks its profile stale; the page still uses it until the profiles are rebuilt).

  python3 game/profiles.py [--workers 4] [--only aurora,net_jit8_best] [--matches 16]
Re-run it after adding teams or nets (a few seconds per team)."""
import argparse
import json
import multiprocessing as mp
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PATH = os.path.join(ROOT, "data", "team_profiles.json")
PROFILE_MATCHES = 16
OPPONENTS = ("owls", "cobalt", "tide", "dune")
SCALARS = ("possession_pct", "ball_own_half_pct", "field_tilt_pct", "goal_guarded_pct", "goal_empty_pct", "deepest_to_goal_px",
           "at_wall_pct", "ball_corner_ours_pct", "press_d1_px", "press_d2_px", "ppda", "passes_match", "pass_ok_pct",
           "progressive_match")


def _play(job):
    """Worker: one profiling match of team `tid` (side 0) -> the Behaviour record."""
    from game import api
    from rl.evaluate import Behaviour
    from soccer.match import ENDED, Match
    tid, opp, seed = job
    m = Match(api.config({"home": tid, "away": opp, "pitch": "arena", "size": 5, "duration": 60.0, "seed": seed, "control": "none"}))
    m.log_events = True
    b = Behaviour()
    while m.state != ENDED and m.tick < 60 * 120:
        m.step()
        b.tick(m)
    return b.finish(m, m.make_result())


def jobs_for(tid, n):
    opps = [o for o in OPPONENTS if o != tid] + (["aurora"] if tid in OPPONENTS else [])
    return [(tid, opps[i % len(opps)], 900 + i) for i in range(n)]


def summarise(records):
    from rl.evaluate import scout_summary
    s = scout_summary(records)
    n = max(len(records), 1)
    out = {k: s[k] for k in SCALARS}
    shots, against = s["shots"], s["shots_against"]
    out["shots_match"] = round(len(shots) / n, 2)
    out["xg_shot"] = round(sum(x[2] for x in shots) / len(shots), 3) if shots else 0.0
    out["shot_dist"] = round(sum(1.0 - x[0] for x in shots) / len(shots), 3) if shots else 0.0   # 0 = on the goal line, 2 = own goal line
    out["shots_against_match"] = round(len(against) / n, 2)
    out["gf_match"] = round(sum(r["score"][0] for r in records) / n, 2)
    out["ga_match"] = round(sum(r["score"][1] for r in records) / n, 2)
    out["line_out_px"] = s["shape"]["out"]["back_line_px"]
    out["matches"] = len(records)
    return out


def load():
    try:
        with open(PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def main():
    from game import api
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--only", default="", help="comma-separated team ids (default: every team of the game)")
    ap.add_argument("--matches", type=int, default=PROFILE_MATCHES)
    a = ap.parse_args()
    teams = api.teams()
    ids = [i for i in a.only.split(",") if i] or list(teams)
    for i in ids:
        if i not in teams:
            sys.exit("unknown team: " + i)
    jobs = [j for i in ids for j in jobs_for(i, a.matches)]
    t0 = time.time()
    with mp.get_context("spawn").Pool(max(1, a.workers)) as pool:
        recs = pool.map(_play, jobs, chunksize=1)
    prof = load()
    for k, i in enumerate(ids):
        prof[i] = {"sha": api.team_sha(teams[i]), "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   **summarise(recs[k * a.matches:(k + 1) * a.matches])}
    prof = {k: prof[k] for k in sorted(prof)}
    tmp = PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(prof, f, indent=1)
        f.write("\n")
    os.replace(tmp, PATH)
    print("%d teams, %d matches, %.0f s -> %s" % (len(ids), len(jobs), time.time() - t0, os.path.relpath(PATH, ROOT)))
    for i in ids:
        print("%-28s %s" % (i, api.describe(i)))


if __name__ == "__main__":
    main()
