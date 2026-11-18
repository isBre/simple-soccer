extends Node
## Plays tournaments of every format in the Godot game's Tournament (scripts/tournament/tournament.gd) with made-up results
## (the same formula as tests/test_tournament.py) and prints them, so the Python port (game/tournament.py) can be compared:
##   Godot --headless --path REF res://tests/godot/record_tournament.tscn
## Output: one line "TOURNAMENTS <json>": per case the final tournament (to_dict), the seed / allow_draw of every match setup
## (config_for) and the final standings.

const CASES := [
    [0, 5, 1], [0, 6, 12345], [0, 16, 777],
    [1, 4, 2], [1, 8, 99999], [1, 16, 31337],
    [2, 8, 4242], [2, 16, 5],
]


static func fake(t_seed: int, ri: int, idx: int, fix: Dictionary) -> Dictionary:
    var h := (t_seed * 31 + ri * 7 + idx * 13) % 11
    var hg := h % 3
    var ag := (h * 5 + idx) % 3
    var winner := -1
    if hg > ag:
        winner = 0
    elif ag > hg:
        winner = 1
    var shoot: Array = []
    if fix["stage"] == "ko" and winner == -1:
        shoot = [3, 2] if h % 2 == 0 else [2, 3]
        winner = 0 if h % 2 == 0 else 1
    var ev: Array = []
    for k in hg:
        ev.append({"clock": 30.0 * (k + 1), "team": 0, "scorer_name": "H%d" % k, "own": false})
    for k in ag:
        ev.append({"clock": 31.0 * (k + 1), "team": 1, "scorer_name": "A%d" % k, "own": k == 1})
    var rh := 6.0 + 0.5 * hg
    var ra := 6.25 + 0.5 * ag
    var pl := [
        {"uid": 0, "id": str(fix["home"]) + "_1", "name": "Home " + str(fix["home"]), "team": 0, "role": "MID", "goals": hg,
            "assists": 0, "saves": 1, "shots": hg + 2, "rating": rh},
        {"uid": 1, "id": str(fix["away"]) + "_1", "name": "Away " + str(fix["away"]), "team": 1, "role": "FWD", "goals": ag,
            "assists": 1 if ag > 0 else 0, "saves": 0, "shots": ag + 1, "rating": ra},
    ]
    return {"teams": [fix["home"], fix["away"]], "scores": [hg, ag], "shootout": shoot, "winner": winner, "events": ev,
        "players": pl, "mom": 0 if rh >= ra else 1}


func _ready() -> void:
    var ids: Array = []
    for t: TeamDef in Database.teams.values():
        if t.ml_model == "":
            ids.append(t.id)
    ids.sort()
    var out: Array = []
    for c: Array in CASES:
        var t := Tournament.create(c[0], ids.slice(0, c[1]), ids[0], "arena", 3, 60.0, c[2])
        var seeds: Array = []
        var guard := 0
        while not t.finished and guard < 200:
            guard += 1
            var ri := t.round_index
            var fixtures: Array = t.current_round()["fixtures"].duplicate()
            for idx in fixtures.size():
                var f: Dictionary = fixtures[idx]
                if f["played"]:
                    continue
                var cfg := t.config_for(f)
                seeds.append([cfg.match_seed, cfg.allow_draw])
                t.record(f, fake(t.t_seed, ri, idx, f))
        var st: Array = []
        if c[0] == 0:
            st = [t.standings()]
        elif c[0] == 2:
            st = [t.standings(0), t.standings(1)]
        out.append({"t": t.to_dict(), "seeds": seeds, "standings": st})
    print("TOURNAMENTS " + JSON.stringify(out))
    get_tree().quit()
