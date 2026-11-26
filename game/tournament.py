"""Tournaments: fixtures, results, standings, player statistics. A port of the Godot game's Tournament
(scripts/tournament/tournament.gd); with Godot's random generator (soccer/rng.py) the same seed gives the same fixtures.

A tournament is plain JSON (the browser keeps it); the functions here take it, change it and return it:
  create(...)          a new tournament          view(t)            what the pages show (standings, round, top players)
  user_fixture(t)      the player's next match   setup_for(t, fix)  its match setup (game/api.py)
  record(t, fix, res)  stores a result and advances the rounds when they are complete"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from soccer.rng import RandomNumberGenerator        # noqa: E402

LEAGUE, KNOCKOUT, GROUPS = 0, 1, 2
FORMAT_NAMES = ["League (round robin)", "Knockout cup", "Groups + knockout"]


def _fx(home, away, stage, group):
    return {"home": home, "away": away, "stage": stage, "group": group, "played": False, "hg": 0, "ag": 0,
            "ot": False, "winner": "", "goals": []}


def _round_robin(ids):
    teams = list(ids)
    if len(teams) % 2 == 1:
        teams.append("")
    n = len(teams)
    out = []
    for r in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, b = teams[i], teams[n - 1 - i]
            if a and b:
                pairs.append([a, b] if (r + i) % 2 == 0 else [b, a])
        out.append(pairs)
        last = teams.pop()
        teams.insert(1, last)
    return out


def _ko_name(count):
    """Name of a knockout round of `count` matches. (The Godot game mapped 2 matches to "Final" and so called the real final
    "Round of 2"; fixed here.)"""
    return {1: "Final", 2: "Semi-finals", 4: "Quarter-finals"}.get(count, "Round of %d" % (count * 2))


def _ko_round(ids):
    fx = [_fx(ids[i], ids[i + 1], "ko", -1) for i in range(0, len(ids), 2)]
    return {"name": _ko_name(len(fx)), "stage": "ko", "fixtures": fx}


def create(fmt, ids, user, pitch, size, duration, seed):
    """Tournament.create: the teams are shuffled with the seed (Godot's generator), then the fixtures are drawn."""
    rng = RandomNumberGenerator()
    rng.seed = seed
    order = list(ids)
    for i in range(len(order) - 1, 0, -1):
        j = rng.randi() % (i + 1)
        order[i], order[j] = order[j], order[i]
    t = {"title": FORMAT_NAMES[fmt], "format": fmt, "team_ids": order, "user_team": user, "pitch_id": pitch, "team_size": size,
         "duration": float(duration), "t_seed": seed, "rounds": [], "round_index": 0, "groups": [], "player_stats": {},
         "champion": "", "finished": False}
    if fmt == LEAGUE:
        for n, rr in enumerate(_round_robin(order), 1):
            t["rounds"].append({"name": "Matchday %d" % n, "stage": "league", "fixtures": [_fx(a, b, "league", -1) for a, b in rr]})
    elif fmt == KNOCKOUT:
        t["rounds"].append(_ko_round(order))
    else:
        half = len(order) // 2
        t["groups"] = [order[:half], order[half:]]
        per_group = [_round_robin(g) for g in t["groups"]]
        for i in range(len(per_group[0])):
            fx = [_fx(a, b, "group", g) for g in (0, 1) for a, b in per_group[g][i]]
            t["rounds"].append({"name": "Group matchday %d" % (i + 1), "stage": "group", "fixtures": fx})
    return t


# ------------------------------------------------------------------ queries

def current_round(t):
    return t["rounds"][min(t["round_index"], len(t["rounds"]) - 1)]


def _mine(t, f):
    return f["home"] == t["user_team"] or f["away"] == t["user_team"]


def user_fixture(t):
    """Index of the player's unplayed match in the current round, or None."""
    for i, f in enumerate(current_round(t)["fixtures"]):
        if not f["played"] and _mine(t, f):
            return i
    return None


def pending_fixtures(t, include_user=True):
    return [i for i, f in enumerate(current_round(t)["fixtures"]) if not f["played"] and (include_user or not _mine(t, f))]


def user_eliminated(t):
    if t["format"] == LEAGUE or t["finished"] or current_round(t)["stage"] != "ko":
        return False
    return not any(_mine(t, f) for f in current_round(t)["fixtures"])


def setup_for(t, index):
    """The match setup of fixture `index` of the current round (Tournament.config_for: the same seed as the Godot game)."""
    f = current_round(t)["fixtures"][index]
    return {"home": f["home"], "away": f["away"], "pitch": t["pitch_id"], "size": t["team_size"], "duration": t["duration"],
            "seed": t["t_seed"] * 1000 + t["round_index"] * 37 + max(index, 0), "allow_draw": f["stage"] != "ko", "control": "none"}


def standings(t, group=-1):
    ids = t["team_ids"] if group < 0 else t["groups"][group]
    rows = {i: {"id": i, "p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "gd": 0, "pts": 0} for i in ids}
    for r in t["rounds"]:
        if r["stage"] == "ko":
            continue
        for f in r["fixtures"]:
            if not f["played"] or (group >= 0 and int(f["group"]) != group):
                continue
            _table_add(rows[f["home"]], int(f["hg"]), int(f["ag"]))
            _table_add(rows[f["away"]], int(f["ag"]), int(f["hg"]))
    return sorted(rows.values(), key=lambda a: (-a["pts"], -a["gd"], -a["gf"], a["id"]))


def _table_add(row, gf, ga):
    row["p"] += 1
    row["gf"] += gf
    row["ga"] += ga
    row["gd"] = row["gf"] - row["ga"]
    if gf > ga:
        row["w"] += 1
        row["pts"] += 3
    elif gf == ga:
        row["d"] += 1
        row["pts"] += 1
    else:
        row["l"] += 1


TOP_KINDS = ("goals", "assists", "shots")


def top_players(t, kind, n=8):
    """kind: goals / assists / shots. A row is one player of one team (copies of a player in a line-up count together)."""
    rows = list(t["player_stats"].values())
    return sorted(rows, key=lambda ps: (-float(ps.get(kind, 0)), int(ps["apps"]), ps["name"]))[:n]


def view(t):
    """Everything the tournament pages show, derived from the tournament."""
    r = current_round(t)
    out = {"round_name": r["name"], "round_index": t["round_index"], "user_fixture": user_fixture(t), "eliminated": user_eliminated(t),
           "pending": len(pending_fixtures(t)), "finished": t["finished"], "champion": t["champion"],
           "top": {k: top_players(t, k) for k in TOP_KINDS}}
    if t["format"] == LEAGUE:
        out["tables"] = [{"title": "", "rows": standings(t), "qualify": 0}]
    elif t["format"] == GROUPS:
        out["tables"] = [{"title": "Group %s" % "AB"[g], "rows": standings(t, g), "qualify": 2} for g in (0, 1)]
    else:
        out["tables"] = []
    return out


# ------------------------------------------------------------------ updates

def record(t, index, res):
    """Stores the result of fixture `index` of the current round (Tournament.record)."""
    f = current_round(t)["fixtures"][index]
    f["played"] = True
    f["hg"], f["ag"] = int(res["scores"][0]), int(res["scores"][1])
    f["ot"] = bool(res.get("overtime"))
    w = int(res["winner"])
    f["winner"] = "" if w == -1 else (f["home"] if w == 0 else f["away"])
    f["goals"] = [{"clock": e["clock"], "team": e["team"], "scorer": e["scorer_name"], "own": e["own"]} for e in res["events"]]
    _add_stats(t, res)
    advance_if_complete(t)
    return t


def _add_stats(t, res):
    """Goals, assists and shots per player and team; a player fielded several times by one team is one row (one appearance)."""
    seen = set()
    for p in res["players"]:
        team = res["teams"][int(p["team"])]
        key = team + "/" + p["id"]
        ps = t["player_stats"].setdefault(key, {"id": p["id"], "name": p["name"], "team": team, "apps": 0,
                                                "goals": 0, "assists": 0, "shots": 0})
        if key not in seen:
            ps["apps"] += 1
            seen.add(key)
        for k in ("goals", "assists", "shots"):
            ps[k] += int(p[k])


def advance_if_complete(t):
    if t["finished"]:
        return
    r = t["rounds"][t["round_index"]]
    if any(not f["played"] for f in r["fixtures"]):
        return
    if r["stage"] == "league":
        if t["round_index"] >= len(t["rounds"]) - 1:
            t["finished"] = True
            t["champion"] = standings(t)[0]["id"]
        else:
            t["round_index"] += 1
    elif r["stage"] == "group":
        if t["round_index"] + 1 < len(t["rounds"]):
            t["round_index"] += 1
        else:
            a, b = standings(t, 0), standings(t, 1)
            t["rounds"].append({"name": "Semi-finals", "stage": "ko", "fixtures": [
                _fx(a[0]["id"], b[1]["id"], "ko", -1), _fx(b[0]["id"], a[1]["id"], "ko", -1)]})
            t["round_index"] += 1
    else:
        winners = [f["winner"] for f in r["fixtures"]]
        if len(winners) == 1:
            t["finished"] = True
            t["champion"] = winners[0]
        else:
            t["rounds"].append(_ko_round(winners))
            t["round_index"] += 1
