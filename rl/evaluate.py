"""Evaluations of a net on the 5v5 arena, played by the match core (soccer/) in parallel processes. Line-by-line port of the
Godot scenes rl/league_eval.gd, rl/h2h_eval.gd and rl/behaviour_stats.gd, with the same printed lines (rl/eval_checkpoint.py
and the dashboard parse them); checked against them by tests/test_evaluate.py.

  python3 rl/evaluate.py league_eval --model res://out_5v5/x.json --games 4 [--duration 180] [--stride 2] [--greedy]
      The net drives ALL 5 players (keeper included) against each of the 16 rule-based teams, on both sides. Also writes
      rl/teams_info.json (id, strength, style, tier, held_out) for the trainer. Held-out teams (never trained against): sorted
      by strength, indices 1, 5, 9, 13 (one per tier).
  python3 rl/evaluate.py h2h_eval --a MODEL --b MODEL --name "RL Team 4" [--games 2] [--duration 90]
      Head to head of two nets (game-model JSON files), both sides. Prints
      H2H <name>: W x D y L z | pts/m | GF/GA | N matches   (a = the net being evaluated, results from its side)
  python3 rl/evaluate.py behaviour_stats [--model res://x.json] [--greedy]
      Behaviour per decision (jitter, kick presses, clumping, keeper position), heatmaps and one "SCOUT {json}" line for the
      scouting page (shape by depth rank in and out of possession, keeper presence, pressing, possession, territory, located
      events), positions normalised to [-1, 1] in the RL team's attacking frame."""
import json
import math
import multiprocessing as mp
import os
import sys
import time

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):   # before numpy: the nets' products are tiny, and BLAS
    os.environ.setdefault(_v, "1")                                         # thread pools in every worker starve the simulation

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from soccer.data import database                                      # noqa: E402
from soccer.match import ENDED, PLAYING, Match, MatchConfig           # noqa: E402
from soccer.stats import snapped                                      # noqa: E402

CORNER_ZONE = 150.0      # the ball counts as "in a corner" within this many px of both the goal line and the side line
GX, GY = 14, 8           # heatmap grid (the RL team always attacks to the right)


def res_abs(path):
    return os.path.join(ROOT, path[6:]) if path.startswith("res://") else os.path.abspath(path)


def gd_round(x):
    """Godot's roundf: halves away from zero."""
    return math.floor(x + 0.5) if x >= 0 else -math.floor(-x + 0.5)


def _f(fmt, x):
    """x as printed with fmt, back as a float: the JSON results carry exactly the printed numbers."""
    return float(fmt % x)


def result_line(d):
    """The machine-readable line of an evaluation part (rl/eval_checkpoint.py collects them into <out>.json)."""
    return "RESULT " + json.dumps(d, sort_keys=True)


def _pool():
    n = int(os.environ.get("SOCCER_PROCS", "0")) or os.cpu_count() or 2      # SOCCER_PROCS caps it (e.g. on a fanless laptop)
    return mp.get_context("fork" if hasattr(os, "fork") else "spawn").Pool(n)


def _play(cfg):
    m = Match(cfg)
    m.run_to_end()
    return m.make_result()


def play_all(cfgs):
    """Results of all matches, in order, played in parallel."""
    with _pool() as p:
        return p.map(_play, cfgs, chunksize=1)


def _cfg(teams, side_nets, seed, duration, temperature=1.0):
    db = database()
    c = MatchConfig()
    c.pitch = db.pitches["arena"]
    c.team_size = 5
    c.duration = duration
    c.match_seed = seed
    c.teams = [db.teams[t] for t in teams]
    c.nets = list(side_nets)
    c.net_temperature = temperature
    return c


# ------------------------------------------------------------------ league

def league_teams():
    """The rule-based teams sorted by strength, with tier and held-out flag (rl/teams_info.json)."""
    db = database()
    teams = [t for t in db.teams.values() if t.rl_eval]
    teams.sort(key=lambda t: t.strength())
    tiers = ["weak", "average", "strong", "elite"]
    ids, info = [], {}
    for i, t in enumerate(teams):
        ids.append(t.id)
        info[t.id] = {"id": t.id, "strength": snapped(t.strength(), 0.1), "style": t.style_id, "tier": tiers[min(i // 4, 3)],
                      "held_out": i % 4 == 1}
    return ids, info


def league_report(model_label, ids, info, matches, seconds, summary=None):
    """The LEAGUE table and SUMMARY lines from the matches [(opp, side, seed, gf, ga)] (league_eval.gd's output). A `summary`
    dict is filled with the SUMMARY numbers by group (all, tiers, train / held): pts, se, gf, ga, n, gd, gd_se."""
    lines = ["MATCH %s %d %d %d %d" % m for m in matches]
    tab = {}
    for opp, side, seed, gf, ga in matches:
        t = tab.setdefault(opp, {"p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "gd2": 0})
        t["p"] += 1
        t["gd2"] += (gf - ga) * (gf - ga)
        t["gf"] += gf
        t["ga"] += ga
        if gf > ga:
            t["w"] += 1
        elif gf == ga:
            t["d"] += 1
        else:
            t["l"] += 1
    out = ["LEAGUE model=%s  (%.0fs)" % (model_label, seconds),
           "team".ljust(11) + "tier".ljust(9) + "str".ljust(6) + "held".ljust(5) + "W  D  L   pts/m   GF/GA"]
    agg = {}
    for tid in ids:
        t, inf = tab[tid], info[tid]
        pts = 3.0 * t["w"] + t["d"]
        out.append("%s%s%s%s%d  %d  %d   %.2f    %.2f/%.2f" % (tid.ljust(11), str(inf["tier"]).ljust(9), _gd_str(inf["strength"]).ljust(6),
                   ("yes" if inf["held_out"] else "").ljust(5), t["w"], t["d"], t["l"], pts / t["p"], t["gf"] / t["p"], t["ga"] / t["p"]))
        for key in ("all", inf["tier"], "held" if inf["held_out"] else "train"):
            g = agg.setdefault(key, [0.0, 0, 0.0, 0.0, 0.0, 0.0])
            g[0] += pts
            g[1] += t["p"]
            g[2] += t["gf"]
            g[3] += t["ga"]
            g[4] += 9.0 * t["w"] + t["d"]          # sum of squared match points (3 / 1 / 0): for the standard error
            g[5] += t["gd2"]
    for key in ("weak", "average", "strong", "elite", "train", "held", "all"):
        if key not in agg:                         # e.g. --stride 2 leaves no held-out team
            continue
        g = agg[key]
        mean = g[0] / g[1]
        se = math.sqrt(max(g[4] / g[1] - mean * mean, 0.0) / g[1])
        gd = (g[2] - g[3]) / g[1]
        gd_se = math.sqrt(max(g[5] / g[1] - gd * gd, 0.0) / g[1])
        out.append("SUMMARY %s: pts/m %.2f  GF %.2f GA %.2f  (%d matches) se %.2f gd %.2f gdse %.2f" % (
            key.ljust(8), mean, g[2] / g[1], g[3] / g[1], g[1], se, gd, gd_se))
        if summary is not None:
            summary[key] = {"pts": _f("%.2f", mean), "se": _f("%.2f", se), "gf": _f("%.2f", g[2] / g[1]), "ga": _f("%.2f", g[3] / g[1]),
                            "n": int(g[1]), "gd": _f("%.2f", gd), "gd_se": _f("%.2f", gd_se)}
    return lines, out


def _gd_str(x):
    """str() of a Godot float: 61.8 -> "61.8", 84.0 -> "84.0"."""
    return gd_float(float(x))


def league_eval(a):
    ids, info = league_teams()
    with open(os.path.join(ROOT, "rl", "teams_info.json"), "w") as f:
        f.write(_godot_json([info[i] for i in ids]))
    if a.stride > 1:
        ids = [i for k, i in enumerate(ids) if k % a.stride == 0]
    if not a.model:
        return
    spec = {"model": res_abs(a.model)}
    cfgs, meta = [], []
    seed_i = 0
    for tid in ids:
        for side in (0, 1):
            for g in range(a.games):
                seed_i += 1
                teams = ["owls", "owls"]
                teams[1 - side] = tid
                nets = [None, None]
                nets[side] = spec
                cfgs.append(_cfg(teams, nets, 50000 + seed_i, a.duration, 0.0 if a.greedy else 1.0))
                meta.append((tid, side, 50000 + seed_i))
    t0 = time.time()
    print("[league] %d matches vs %d teams, model %s" % (len(cfgs), len(ids), a.model), flush=True)
    results = play_all(cfgs)
    matches = [(opp, side, seed, r["scores"][side], r["scores"][1 - side]) for (opp, side, seed), r in zip(meta, results)]
    summary = {}
    lines, table = league_report(a.model, ids, info, matches, time.time() - t0, summary)
    print("\n".join(lines))
    text = "\n".join(table)
    print(text)
    print(result_line({"part": "league", "summary": summary, "matches": [list(m) for m in matches]}))
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    with open(os.path.join(ROOT, "logs", "league_last.txt"), "w") as f:
        f.write(text + "\n")


def gd_float(x):
    """A float as Godot writes it in text and JSON: 15 significant digits, integral values with ".0"."""
    t = "%.15g" % x
    if not any(c in t for c in ".eEn"):      # no decimal point, exponent, inf or nan
        t += ".0"
    return t


def gd_json(v, indent=None, level=0):
    """JSON.stringify(v, indent) of Godot: sorted keys, Godot's float format; compact without indent."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return gd_float(v)
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, dict):
        items = [(json.dumps(str(k)), gd_json(v[k], indent, level + 1)) for k in sorted(v, key=str)]
        if indent is None:
            return "{" + ",".join("%s:%s" % kv for kv in items) + "}"
        if not items:
            return "{}"
        pad, pad1 = indent * level, indent * (level + 1)
        return "{\n" + ",\n".join("%s%s: %s" % (pad1, k, x) for k, x in items) + "\n" + pad + "}"
    if isinstance(v, (list, tuple)):
        items = [gd_json(x, indent, level + 1) for x in v]
        if indent is None:
            return "[" + ",".join(items) + "]"
        if not items:
            return "[]"
        pad, pad1 = indent * level, indent * (level + 1)
        return "[\n" + ",\n".join(pad1 + x for x in items) + "\n" + pad + "]"
    raise TypeError(type(v))


def _godot_json(v):
    """Database.write_json's format (JSON.stringify with a two-space indent and sorted keys), so the file stays identical."""
    return gd_json(v, "  ")


# ------------------------------------------------------------------ head to head

def h2h_report(name, matches, summary=None):
    """matches [(side, seed, gf, ga)] -> the MATCH lines and the H2H line (h2h_eval.gd's output). A `summary` dict is filled
    with the H2H numbers: pts, se, gf, ga, n, w, d, l, gd, gd_se."""
    lines = []
    w = d = l = gf = ga = 0
    gd2 = 0.0
    for side, seed, f, g in matches:
        gf += f
        ga += g
        lines.append("MATCH h2h:%s %d %d %d %d" % (name.replace(" ", "_"), side, seed, f, g))
        gd2 += float((f - g) * (f - g))
        if f > g:
            w += 1
        elif f == g:
            d += 1
        else:
            l += 1
    n = len(matches)
    mean = (3.0 * w + d) / n
    se = math.sqrt(max((9.0 * w + d) / n - mean * mean, 0.0) / n)
    gd = (gf - ga) / n
    gd_se = math.sqrt(max(gd2 / n - gd * gd, 0.0) / n)
    lines.append("H2H %s: W %d D %d L %d | pts/m %.2f | GF/GA %.2f/%.2f | %d matches | se %.2f | gd %.2f gdse %.2f" % (
        name, w, d, l, mean, gf / n, ga / n, n, se, gd, gd_se))
    if summary is not None:
        summary.update({"pts": _f("%.2f", mean), "se": _f("%.2f", se), "gf": _f("%.2f", gf / n), "ga": _f("%.2f", ga / n), "n": n,
                        "w": w, "d": d, "l": l, "gd": _f("%.2f", gd), "gd_se": _f("%.2f", gd_se)})
    return lines


def h2h_eval(a):
    if not a.a or not a.b:
        return
    cfgs, meta = [], []
    for side in (0, 1):                            # side = the side the evaluated net plays
        for g in range(a.games):
            teams = ["owls", "rl_team_4"] if side == 0 else ["rl_team_4", "owls"]
            nets = [None, None]
            nets[side] = {"model": res_abs(a.a)}
            nets[1 - side] = {"model": res_abs(a.b)}
            seed = 70000 + side * 1000 + g
            cfgs.append(_cfg(teams, nets, seed, a.duration))
            meta.append((side, seed))
    results = play_all(cfgs)
    matches = [(s, sd, r["scores"][s], r["scores"][1 - s]) for (s, sd), r in zip(meta, results)]
    summary = {}
    print("\n".join(h2h_report(a.name, matches, summary)))
    print(result_line({"part": "h2h", "name": a.name, "summary": summary, "matches": [list(m) for m in matches]}))


# ------------------------------------------------------------------ behaviour and scouting

def _bin(grid, pos, m, team):
    """Counts a position in a heatmap grid, in the team's attacking frame (x grows towards the opponent goal)."""
    fx = min(max((pos.real * m.attack_dir(team) / m.pitch.half_w) * 0.5 + 0.5, 0.0), 0.9999)
    fy = min(max((pos.imag / m.pitch.half_h) * 0.5 + 0.5, 0.0), 0.9999)
    grid[int(fy * GY) * GX + int(fx * GX)] += 1.0


class Behaviour:
    """The per-decision measurements of one match (behaviour_stats.gd _run), fed tick by tick."""

    def __init__(self):
        self.sc = {"role": [[0] * 5 for _ in range(5)], "pos": {"in": [[0.0, 0.0] for _ in range(5)], "out": [[0.0, 0.0] for _ in range(5)]},
                   "n_phase": {"in": 0, "out": 0}, "shape": {"in": [0.0] * 4, "out": [0.0] * 4}, "press": [0.0, 0.0, 0],
                   "guarded": 0, "empty": 0, "deep_dist": 0.0, "n": 0, "tilt": 0, "own_half_ball": 0, "wall": 0.0, "corner": 0,
                   "corner_own": 0}
        self.st = [{k: 0 for k in ("n", "dir_change", "kick_rise", "kick_hold", "idle", "gk_n", "turn180")} for _ in range(2)]
        for s in self.st:
            s.update({k: 0.0 for k in ("near_ball", "spacing", "gk_dist", "speed", "near250", "nn_dist", "close_pairs", "passes",
                                        "passes_ok", "key_passes", "xa", "shots")})
        self.prev, self.prev_kick = {}, {}
        self.heat = [[0.0] * (GX * GY) for _ in range(6)]       # RL team: one grid per slot, then the ball
        self.roles = [""] * 5

    def tick(self, m):
        if m.tick % 2 != 0 or m.kickoff_active or m.state != PLAYING:
            return
        for t in (0, 1):
            s = self.st[t]
            team = m.team_lists[t]
            if t == 0:
                for p in team:
                    self.roles[p.slot] = p.line          # the formation spot of the slot (rule teams)
                    _bin(self.heat[p.slot], p.pos, m, t)
                _bin(self.heat[5], m.ball.pos, m, t)
                self._scout_tick(m, team)
            near = 0
            for p in team:
                s["n"] += 1
                d = p.input_dir
                pd = self.prev.get(p.uid, d)
                if abs(d - pd) > 0.3:
                    s["dir_change"] += 1
                if abs(d) > 0.1 and abs(pd) > 0.1 and d.real * pd.real + d.imag * pd.imag < -0.5:
                    s["turn180"] += 1
                self.prev[p.uid] = d
                if abs(d) < 0.1:
                    s["idle"] += 1
                if p.input_kick:
                    s["kick_hold"] += 1
                    if not self.prev_kick.get(p.uid, False):
                        s["kick_rise"] += 1
                self.prev_kick[p.uid] = p.input_kick
                s["speed"] += abs(p.vel)
                if abs(p.pos - m.ball.pos) < 120.0:
                    near += 1
                if abs(p.pos - m.ball.pos) < 250.0:
                    s["near250"] += 1.0 / 5.0
            s["near_ball"] += near
            for a in team:
                nn = 1.0e9
                for b in team:
                    if a is not b:
                        dd = abs(a.pos - b.pos)
                        nn = min(nn, dd)
                        if dd < 110.0 and a.uid < b.uid:
                            s["close_pairs"] += 1.0 / 5.0
                s["nn_dist"] += nn / 5.0
            sp, cnt = 0.0, 0
            for a in team:
                for b in team:
                    if a is not b:
                        sp += abs(a.pos - b.pos)
                        cnt += 1
            s["spacing"] += sp / max(1.0, cnt)
            gk = team[0]
            own_goal = complex(-m.pitch.half_w * m.attack_dir(t), 0.0)
            s["gk_dist"] += abs(gk.pos - own_goal)
            s["gk_n"] += 1

    def _scout_tick(self, m, team):
        """One sample of the RL team's shape (team 0, attacking frame, normalised): depth ranks, in / out of possession,
        pressing, keeper."""
        sc = self.sc
        ax = m.attack_dir(0)
        hw, hh = m.pitch.half_w, m.pitch.half_h
        q = [(complex(p.pos.real * ax / hw, p.pos.imag / hh), p.slot) for p in team]
        q.sort(key=lambda e: e[0].real)                               # rank 0 = the deepest player
        lt = m.last_touch
        phase = ("in" if lt.team == 0 else "out") if lt is not None else ""
        sc["n"] += 1
        for p in team:                                                # share of player time pressed against the outer wall
            if abs(p.pos.real) >= m.pitch.out_x - p.radius - 3.0 or abs(p.pos.imag) >= m.pitch.out_y - p.radius - 3.0:
                sc["wall"] += 1.0 / 5.0
        if abs(m.ball.pos.real) > hw - CORNER_ZONE and abs(m.ball.pos.imag) > hh - CORNER_ZONE:   # the ball in a corner
            sc["corner"] += 1
            if lt is not None and lt.team == 0:
                sc["corner_own"] += 1                                 # ... and our team put it there (last touch)
        ball = complex(m.ball.pos.real * ax / hw, m.ball.pos.imag / hh)
        if ball.real < 0.0:
            sc["own_half_ball"] += 1
        for r, (_, slot) in enumerate(q):
            sc["role"][slot][r] += 1
        if phase:
            sc["n_phase"][phase] += 1
            lo_x = lo_y = 9.0
            hi_x = hi_y = -9.0
            for r, (v, _) in enumerate(q):
                sc["pos"][phase][r][0] += v.real
                sc["pos"][phase][r][1] += v.imag
                lo_x, lo_y, hi_x, hi_y = min(lo_x, v.real), min(lo_y, v.imag), max(hi_x, v.real), max(hi_y, v.imag)
            sh = sc["shape"][phase]
            sh[0] += (hi_y - lo_y) * hh                               # width px
            sh[1] += (hi_x - lo_x) * hw                               # depth px
            sh[2] += (q[0][0].real + 1.0) * hw                        # last man: px from our goal line
            sh[3] += (q[1][0].real + 1.0) * hw                        # second deepest (back line) px from our goal line
            if phase == "in" and ball.real > 1.0 / 3.0:
                sc["tilt"] += 1
        if phase == "out":                                            # pressing: our two nearest players' distance to the ball
            ds = sorted(abs(p.pos - m.ball.pos) for p in team)
            sc["press"][0] += ds[0]
            sc["press"][1] += ds[1]
            sc["press"][2] += 1
        own_goal = complex(-hw * ax, 0.0)
        dmin = min([1.0e9] + [abs(p.pos - own_goal) for p in team])
        sc["deep_dist"] += dmin
        if dmin < 180.0:
            sc["guarded"] += 1
        if dmin > 300.0:
            sc["empty"] += 1

    def finish(self, m, res):
        self.sc["events"] = list(m.ev_log)
        self.sc["possession"] = res["team_stats"][0]["possession"]
        for t in (0, 1):
            self.st[t]["passes"] = res["team_stats"][t]["passes"]
            self.st[t]["passes_ok"] = res["team_stats"][t]["passes_ok"]
            self.st[t]["shots"] = res["team_stats"][t]["shots"]
        for pl in res["players"]:
            self.st[int(pl["team"])]["key_passes"] += float(pl.get("key_passes", 0))
            self.st[int(pl["team"])]["xa"] += float(pl.get("xa", 0.0))
        return {"st": self.st, "score": [m.scores[0], m.scores[1]], "ticks": m.tick, "heat": self.heat, "roles": self.roles,
                "scout": self.sc, "half": (m.pitch.half_w, m.pitch.half_h)}


def behaviour_cfg(i, model_spec, greedy):
    db = database()
    c = MatchConfig()
    c.pitch = db.pitches["arena"]
    c.team_size = 5
    c.duration = 60.0
    c.match_seed = 900 + i
    c.teams = [db.teams["rl_team"], db.teams[["owls", "cobalt", "tide", "dune"][i % 4]]]
    if greedy:
        c.net_temperature = 0.0
    if model_spec is not None:
        c.nets[0] = model_spec
    return c


def _behaviour_match(args):
    i, model_spec, greedy = args
    m = Match(behaviour_cfg(i, model_spec, greedy))
    m.log_events = True
    b = Behaviour()
    while m.state != ENDED and m.tick < 60 * 120:
        m.step()
        b.tick(m)
    return b.finish(m, m.make_result())


def scout_summary(results):
    """Merges the scouting samples and located events of every match into the SCOUT line."""
    hw, hh = 640.0, 300.0
    if results and "half" in results[0]:
        hw, hh = results[0]["half"]
    role = [[0] * 5 for _ in range(5)]
    pos = {"in": [[0.0, 0.0] for _ in range(5)], "out": [[0.0, 0.0] for _ in range(5)]}
    nph = {"in": 0, "out": 0}
    shape = {"in": [0.0] * 4, "out": [0.0] * 4}
    tot = {"n": 0, "guarded": 0, "empty": 0, "deep_dist": 0.0, "tilt": 0, "own_half_ball": 0, "possession": 0.0, "wall": 0.0, "corner": 0,
           "corner_own": 0}
    press = [0.0, 0.0, 0]
    shots, shots_against, recov, pass_len = [], [], [], []
    edges = {}
    prog = n_pass = n_ok = opp_build = def_high = 0
    for r in results:
        sc = r["scout"]
        for k in range(5):
            for j in range(5):
                role[k][j] += sc["role"][k][j]
            for ph in ("in", "out"):
                pos[ph][k][0] += sc["pos"][ph][k][0]
                pos[ph][k][1] += sc["pos"][ph][k][1]
        for ph in ("in", "out"):
            nph[ph] += sc["n_phase"][ph]
            for j in range(4):
                shape[ph][j] += sc["shape"][ph][j]
        for key in ("n", "guarded", "empty", "deep_dist", "tilt", "own_half_ball", "wall", "corner", "corner_own"):
            tot[key] += sc[key]
        for j in range(3):
            press[j] += sc["press"][j]
        tot["possession"] += sc["possession"] / float(len(results))
        for e in sc["events"]:
            kind = e[0]
            x, y = e[4] / hw, e[5] / hh
            if int(e[2]) == 0:
                if kind.startswith("shot"):
                    shots.append([snapped(x, 0.01), snapped(y, 0.01), e[8], 1 if kind == "shot_on" else 0])
                elif kind in ("pass_ok", "pass_fail"):
                    n_pass += 1
                    if kind == "pass_ok":
                        n_ok += 1
                        key = "%d-%d" % (int(e[3]) % 16, int(e[8]) % 16)
                        edges[key] = edges.get(key, 0) + 1
                        pass_len.append(gd_round(math.hypot(e[6] - e[4], e[7] - e[5])))
                        if e[6] - e[4] >= hw * 0.2:
                            prog += 1
                else:
                    recov.append([snapped(x, 0.01), snapped(y, 0.01), kind[:1]])
                    if kind != "recovery" and x > -0.2:
                        def_high += 1
            else:
                if kind.startswith("shot"):                   # opponent frame: mirror into ours
                    shots_against.append([snapped(-x, 0.01), snapped(-y, 0.01), e[8], 1 if kind == "shot_on" else 0])
                elif kind in ("pass_ok", "pass_fail") and x < 0.2:
                    opp_build += 1
    avg = {"in": [], "out": []}
    shape_out = {}
    for ph in ("in", "out"):
        n = max(nph[ph], 1)
        for k in range(5):
            avg[ph].append([snapped(pos[ph][k][0] / n, 0.01), snapped(pos[ph][k][1] / n, 0.01)])
        shape_out[ph] = {"width_px": gd_round(shape[ph][0] / n), "depth_px": gd_round(shape[ph][1] / n),
                         "last_man_px": gd_round(shape[ph][2] / n), "back_line_px": gd_round(shape[ph][3] / n)}
    role_share = []
    for k in range(5):
        s = sum(role[k])
        role_share.append([snapped(100.0 * role[k][j] / max(s, 1), 0.1) for j in range(5)])
    edge_list = [[int(k.split("-")[0]), int(k.split("-")[1]), v] for k, v in edges.items()]
    n_t = max(tot["n"], 1)
    nm = max(len(results), 1)
    return {"matches": len(results), "possession_pct": snapped(tot["possession"], 0.1),
            "ball_own_half_pct": snapped(100.0 * tot["own_half_ball"] / n_t, 0.1),
            "field_tilt_pct": snapped(100.0 * tot["tilt"] / max(nph["in"], 1), 0.1),
            "goal_guarded_pct": snapped(100.0 * tot["guarded"] / n_t, 0.1), "goal_empty_pct": snapped(100.0 * tot["empty"] / n_t, 0.1),
            "deepest_to_goal_px": gd_round(tot["deep_dist"] / n_t), "at_wall_pct": snapped(100.0 * tot["wall"] / n_t, 0.1),
            "ball_corner_pct": snapped(100.0 * tot["corner"] / n_t, 0.1),
            "ball_corner_ours_pct": snapped(100.0 * tot["corner_own"] / n_t, 0.1),
            "press_d1_px": gd_round(press[0] / max(press[2], 1)), "press_d2_px": gd_round(press[1] / max(press[2], 1)),
            "ppda": snapped(opp_build / max(def_high, 1), 0.01), "passes_match": snapped(n_pass / nm, 0.1),
            "pass_ok_pct": snapped(100.0 * n_ok / max(n_pass, 1), 0.1), "progressive_match": snapped(prog / nm, 0.1),
            "shape": shape_out, "avg_pos": avg, "role_share": role_share, "edges": edge_list, "pass_len": pass_len,
            "shots": shots, "shots_against": shots_against, "recoveries": recov}


def behaviour_report(results, summary=None):
    """The printed lines of behaviour_stats.gd from the per-match measurements. A `summary` dict is filled with the printed
    numbers: {"rl": {...}, "rule": {...}} (dir_changes_s, idle_pct, spacing_px, keeper_dist_px, passes_match, shots_match,
    key_passes_match, xa_match) and "scout" (the SCOUT JSON)."""
    out = []
    agg = [{}, {}]
    for r in results:
        for t in (0, 1):
            for k, v in r["st"][t].items():
                agg[t][k] = agg[t].get(k, 0.0) + v
    for t in (0, 1):
        a = agg[t]
        n_dec = a["n"]
        per_sec = 30.0                      # decisions per second per player (60 Hz / 2)
        out.append("%s: dir changes/s %.2f | 180-turns/s %.3f | kick presses/s %.2f | kick held %.0f%% | idle %.0f%% | speed %.2f px/tick | teammates spacing %.0f px | players within 120px of ball (team) %.2f | keeper dist from own goal %.0f px" % (
            ["RL Team", "rule-based"][t], a["dir_change"] / n_dec * per_sec, a["turn180"] / n_dec * per_sec, a["kick_rise"] / n_dec * per_sec,
            100.0 * a["kick_hold"] / n_dec, 100.0 * a["idle"] / n_dec, a["speed"] / n_dec, a["spacing"] / (n_dec / 5.0), a["near_ball"] / (n_dec / 5.0),
            a["gk_dist"] / a["gk_n"]))
        if summary is not None:
            summary.setdefault(["rl", "rule"][t], {}).update({
                "dir_changes_s": _f("%.2f", a["dir_change"] / n_dec * per_sec), "idle_pct": _f("%.0f", 100.0 * a["idle"] / n_dec),
                "spacing_px": _f("%.0f", a["spacing"] / (n_dec / 5.0)), "keeper_dist_px": _f("%.0f", a["gk_dist"] / a["gk_n"])})
    for t in (0, 1):
        a = agg[t]
        n_dec = a["n"] / 5.0               # team-decisions
        out.append("%s: players within 250px of ball %.2f | nearest-teammate dist %.0f px | pairs closer than 110px %.2f | passes/match %.1f (%.0f%% ok) | shots/match %.1f | key passes/match %.2f | xA/match %.2f" % (
            ["RL Team", "rule-based"][t], a["near250"] / (a["n"] / 5.0) * 5.0 / 5.0 * 5.0 / 5.0, a["nn_dist"] / n_dec, a["close_pairs"] / n_dec,
            a["passes"] / len(results), 100.0 * a["passes_ok"] / max(1.0, a["passes"]), a["shots"] / len(results), a["key_passes"] / len(results),
            a["xa"] / len(results)))
        if summary is not None:
            summary.setdefault(["rl", "rule"][t], {}).update({
                "passes_match": _f("%.1f", a["passes"] / len(results)), "shots_match": _f("%.1f", a["shots"] / len(results)),
                "key_passes_match": _f("%.2f", a["key_passes"] / len(results)), "xa_match": _f("%.2f", a["xa"] / len(results))})
    # heatmaps (RL team): "HEAT <slot|ball> <role> <w> <h> v..." with v in per mille of that player's time, row by row from the top
    for k in range(6):
        cells = [0.0] * (GX * GY)
        total = 0.0
        for r in results:
            for c in range(GX * GY):
                cells[c] += r["heat"][k][c]
                total += r["heat"][k][c]
        vals = [str(int(cells[c] / max(total, 1.0) * 1000.0)) for c in range(GX * GY)]
        out.append("HEAT %s %s %d %d %s" % ("ball" if k == 5 else str(k), "-" if k == 5 else str(results[0]["roles"][k]), GX, GY, " ".join(vals)))
    out.append("scores (RL first): " + "".join("[%d, %d] " % tuple(r["score"]) for r in results))
    scout = _godot_compact(scout_summary(results))
    out.append("SCOUT " + scout)
    if summary is not None:
        summary["scout"] = json.loads(scout)
    return out


def _godot_compact(v):
    """JSON.stringify's format: no spaces, sorted keys, Godot's float format."""
    return gd_json(v)


def behaviour_stats(a):
    spec = {"model": res_abs(a.model)} if a.model else None
    with _pool() as p:
        results = p.map(_behaviour_match, [(i, spec, a.greedy) for i in range(8)], chunksize=1)
    summary = {}
    print("\n".join(behaviour_report(results, summary)))
    print(result_line({"part": "behaviour", **summary}))


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["league_eval", "h2h_eval", "behaviour_stats"])
    ap.add_argument("--model", default="")
    ap.add_argument("--games", type=int, default=0)
    ap.add_argument("--duration", type=float, default=0.0)
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--greedy", action="store_true")
    ap.add_argument("--a", default="", help="h2h: model of the net being evaluated")
    ap.add_argument("--b", default="", help="h2h: model of the opponent net")
    ap.add_argument("--name", default="opponent")
    a = ap.parse_args(argv)
    if a.what == "league_eval":
        a.games, a.duration = a.games or 4, a.duration or 180.0
        league_eval(a)
    elif a.what == "h2h_eval":
        a.games, a.duration = a.games or 2, a.duration or 90.0
        h2h_eval(a)
    else:
        behaviour_stats(a)


if __name__ == "__main__":
    main()
