class_name Tournament
extends RefCounted
## Tournament state: fixtures, results, standings, player stats. Pure data
## (serialisable to JSON); matches are played live or simulated by the UI.

enum Format { LEAGUE, KNOCKOUT, GROUPS }
const FORMAT_NAMES := ["League (round robin)", "Knockout cup", "Groups + knockout"]
const SAVE_PATH := "user://tournament.json"

var title := "Tournament"
var format := Format.LEAGUE
var team_ids: Array = []
var user_team := ""
var pitch_id := "classic"
var team_size := 3
var duration := 180.0
var t_seed := 1
var rounds: Array = []        # [{name, stage: league|group|ko, fixtures: [fixture]}]
var round_index := 0
var groups: Array = []        # GROUPS format: [[ids], [ids]]
var player_stats: Dictionary = {}
var champion := ""
var finished := false


static func create(fmt: int, ids: Array, user: String, pitch: String, size: int, dur: float,
        rseed: int) -> Tournament:
    var t := Tournament.new()
    t.format = fmt as Format
    t.user_team = user
    t.pitch_id = pitch
    t.team_size = size
    t.duration = dur
    t.t_seed = rseed
    t.title = FORMAT_NAMES[fmt]
    var order: Array = ids.duplicate()
    var rng := RandomNumberGenerator.new()
    rng.seed = rseed
    for i in range(order.size() - 1, 0, -1):
        var j := rng.randi() % (i + 1)
        var tmp = order[i]
        order[i] = order[j]
        order[j] = tmp
    t.team_ids = order
    match fmt:
        Format.LEAGUE:
            var n := 1
            for rr: Array in _round_robin(order):
                var fx: Array = []
                for pair: Array in rr:
                    fx.append(_fx(pair[0], pair[1], "league", -1))
                t.rounds.append({"name": "Matchday %d" % n, "stage": "league", "fixtures": fx})
                n += 1
        Format.KNOCKOUT:
            t.rounds.append(_ko_round(order))
        Format.GROUPS:
            var half := order.size() / 2
            t.groups = [order.slice(0, half), order.slice(half)]
            var per_group: Array = []
            for g in 2:
                per_group.append(_round_robin(t.groups[g]))
            var md: int = per_group[0].size()
            for i in md:
                var fx2: Array = []
                for g in 2:
                    for pair: Array in per_group[g][i]:
                        fx2.append(_fx(pair[0], pair[1], "group", g))
                t.rounds.append({"name": "Group matchday %d" % (i + 1), "stage": "group", "fixtures": fx2})
    return t


static func _fx(home: String, away: String, stage: String, group: int) -> Dictionary:
    return {"home": home, "away": away, "stage": stage, "group": group, "played": false, "hg": 0, "ag": 0,
        "pens": [], "winner": "", "mom": "", "goals": []}


static func _round_robin(ids: Array) -> Array:
    var teams: Array = ids.duplicate()
    if teams.size() % 2 == 1:
        teams.append("")
    var n := teams.size()
    var out: Array = []
    for r in n - 1:
        var pairs: Array = []
        for i in n / 2:
            var a: String = teams[i]
            var b: String = teams[n - 1 - i]
            if a != "" and b != "":
                pairs.append([a, b] if (r + i) % 2 == 0 else [b, a])
        out.append(pairs)
        var last = teams.pop_back()
        teams.insert(1, last)
    return out


static func _ko_name(count: int) -> String:
    match count:
        2: return "Final"
        4: return "Semi-finals"
        8: return "Quarter-finals"
    return "Round of %d" % (count * 2)


static func _ko_round(ids: Array) -> Dictionary:
    var fx: Array = []
    for i in range(0, ids.size(), 2):
        fx.append(_fx(ids[i], ids[i + 1], "ko", -1))
    return {"name": _ko_name(fx.size()), "stage": "ko", "fixtures": fx}


# ------------------------------------------------------------------ queries

func current_round() -> Dictionary:
    return rounds[mini(round_index, rounds.size() - 1)]


func round_name() -> String:
    return str(current_round()["name"])


func user_fixture() -> Dictionary:
    for f: Dictionary in current_round()["fixtures"]:
        if not f["played"] and (f["home"] == user_team or f["away"] == user_team):
            return f
    return {}


func pending_fixtures(include_user: bool) -> Array:
    var out: Array = []
    for f: Dictionary in current_round()["fixtures"]:
        if f["played"]:
            continue
        if not include_user and (f["home"] == user_team or f["away"] == user_team):
            continue
        out.append(f)
    return out


func user_eliminated() -> bool:
    if format == Format.LEAGUE or finished:
        return false
    if current_round()["stage"] != "ko":
        return false
    for f: Dictionary in current_round()["fixtures"]:
        if f["home"] == user_team or f["away"] == user_team:
            return false
    return true


func config_for(fix: Dictionary) -> MatchConfig:
    var idx: int = current_round()["fixtures"].find(fix)
    var c := Database.make_config(fix["home"], fix["away"], pitch_id, team_size, duration,
        t_seed * 1000 + round_index * 37 + maxi(idx, 0))
    c.allow_draw = fix["stage"] != "ko"
    return c


func standings(group: int = -1) -> Array:
    var rows: Dictionary = {}
    var ids: Array = team_ids if group < 0 else groups[group]
    for id: String in ids:
        rows[id] = {"id": id, "p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "gd": 0, "pts": 0}
    for r: Dictionary in rounds:
        if r["stage"] == "ko":
            continue
        for f: Dictionary in r["fixtures"]:
            if not f["played"]:
                continue
            if group >= 0 and int(f["group"]) != group:
                continue
            _table_add(rows[f["home"]], int(f["hg"]), int(f["ag"]))
            _table_add(rows[f["away"]], int(f["ag"]), int(f["hg"]))
    var list: Array = rows.values()
    list.sort_custom(func(a: Dictionary, b: Dictionary) -> bool:
        if a["pts"] != b["pts"]:
            return a["pts"] > b["pts"]
        if a["gd"] != b["gd"]:
            return a["gd"] > b["gd"]
        if a["gf"] != b["gf"]:
            return a["gf"] > b["gf"]
        return str(a["id"]) < str(b["id"]))
    return list


func _table_add(row: Dictionary, gf: int, ga: int) -> void:
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


## kind: goals / assists / rating / motm / saves
func top_players(kind: String, n: int = 8) -> Array:
    var list: Array = []
    for ps: Dictionary in player_stats.values():
        if kind == "rating" and int(ps["apps"]) < 1:
            continue
        list.append(ps)
    list.sort_custom(func(a: Dictionary, b: Dictionary) -> bool:
        var va := _stat_value(a, kind)
        var vb := _stat_value(b, kind)
        if va != vb:
            return va > vb
        return float(a["rating_sum"]) / maxf(1.0, a["apps"]) > float(b["rating_sum"]) / maxf(1.0, b["apps"]))
    return list.slice(0, n)


func _stat_value(ps: Dictionary, kind: String) -> float:
    match kind:
        "rating":
            return float(ps["rating_sum"]) / maxf(1.0, float(ps["apps"]))
        _:
            return float(ps.get(kind, 0))


# ------------------------------------------------------------------ updates

func record(fix: Dictionary, res: Dictionary) -> void:
    fix["played"] = true
    fix["hg"] = int(res["scores"][0])
    fix["ag"] = int(res["scores"][1])
    fix["pens"] = res["shootout"]
    var w: int = res["winner"]
    fix["winner"] = "" if w == -1 else (fix["home"] if w == 0 else fix["away"])
    var goals: Array = []
    for e: Dictionary in res["events"]:
        goals.append({"clock": e["clock"], "team": e["team"], "scorer": e["scorer_name"], "own": e["own"]})
    fix["goals"] = goals
    for p: Dictionary in res["players"]:
        if int(p["uid"]) == int(res["mom"]):
            fix["mom"] = "%s (%.1f)" % [p["name"], p["rating"]]
    _add_stats(res)
    advance_if_complete()


func _add_stats(res: Dictionary) -> void:
    for p: Dictionary in res["players"]:
        var id: String = p["id"]
        if not player_stats.has(id):
            player_stats[id] = {"id": id, "name": p["name"], "team": res["teams"][int(p["team"])],
                "pos": p["role"], "apps": 0, "goals": 0, "assists": 0, "rating_sum": 0.0, "motm": 0,
                "saves": 0, "shots": 0}
        var ps: Dictionary = player_stats[id]
        ps["apps"] += 1
        ps["goals"] += int(p["goals"])
        ps["assists"] += int(p["assists"])
        ps["saves"] += int(p["saves"])
        ps["shots"] += int(p["shots"])
        ps["rating_sum"] += float(p["rating"])
        if int(p["uid"]) == int(res["mom"]):
            ps["motm"] += 1


func advance_if_complete() -> void:
    if finished:
        return
    var r: Dictionary = rounds[round_index]
    for f: Dictionary in r["fixtures"]:
        if not f["played"]:
            return
    match r["stage"]:
        "league":
            if round_index >= rounds.size() - 1:
                finished = true
                champion = standings()[0]["id"]
            else:
                round_index += 1
        "group":
            if round_index + 1 < rounds.size():
                round_index += 1
            else:
                var a := standings(0)
                var b := standings(1)
                rounds.append({"name": "Semi-finals", "stage": "ko", "fixtures": [
                    _fx(a[0]["id"], b[1]["id"], "ko", -1), _fx(b[0]["id"], a[1]["id"], "ko", -1)]})
                round_index += 1
        "ko":
            var winners: Array = []
            for f: Dictionary in r["fixtures"]:
                winners.append(f["winner"])
            if winners.size() == 1:
                finished = true
                champion = winners[0]
            else:
                rounds.append(_ko_round(winners))
                round_index += 1


# ------------------------------------------------------------- persistence

func to_dict() -> Dictionary:
    return {"title": title, "format": int(format), "team_ids": team_ids, "user_team": user_team,
        "pitch_id": pitch_id, "team_size": team_size, "duration": duration, "t_seed": t_seed,
        "rounds": rounds, "round_index": round_index, "groups": groups, "player_stats": player_stats,
        "champion": champion, "finished": finished}


static func from_dict(d: Dictionary) -> Tournament:
    var t := Tournament.new()
    t.title = str(d.get("title", ""))
    t.format = int(d.get("format", 0)) as Format
    t.team_ids = d.get("team_ids", [])
    t.user_team = str(d.get("user_team", ""))
    t.pitch_id = str(d.get("pitch_id", "classic"))
    t.team_size = int(d.get("team_size", 3))
    t.duration = float(d.get("duration", 180.0))
    t.t_seed = int(d.get("t_seed", 1))
    t.rounds = d.get("rounds", [])
    t.round_index = int(d.get("round_index", 0))
    t.groups = d.get("groups", [])
    t.player_stats = d.get("player_stats", {})
    t.champion = str(d.get("champion", ""))
    t.finished = bool(d.get("finished", false))
    return t


func save() -> void:
    Database.write_json(SAVE_PATH, to_dict())


static func load_saved() -> Tournament:
    var d = Database.read_json(SAVE_PATH)
    if d is Dictionary:
        return from_dict(d)
    return null


static func has_save() -> bool:
    return FileAccess.file_exists(SAVE_PATH)
