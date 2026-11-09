extends Node
## Headless-style experiment runner. Edit res://experiments/config.json and run
## res://experiments/experiments.tscn. Results are printed and saved next to config.
##
## modes:
##   single - one match, prints a summary (debugging)
##   styles - every play style vs every other (same neutral squad) -> balance matrix
##   teams  - round robin between all teams (home + away)
##   sanity - many matches of random team pairs, aggregate stats for AI tuning
##   human  - a scripted human controls one team: teammate collisions, keeper assignment (results_human.txt)
##   keeper - shot-stopping test with tunable keeper depth variants (results_keeper.txt)

var batch := SimBatch.new()
var cfg: Dictionary = {}
var meta: Array = []
var t0 := 0


func _ready() -> void:
    var c = Database.read_json("res://experiments/config.json")
    cfg = c if c is Dictionary else {"mode": "single"}
    var mode: String = str(cfg.get("mode", "single"))
    var pitch_id: String = str(cfg.get("pitch", "classic"))
    var size: int = int(cfg.get("size", 3))
    var games: int = int(cfg.get("games", 4))
    var duration: float = float(cfg.get("duration", 180.0))
    var cfgs: Array = []

    match mode:
        "styles":
            var neutral := _neutral_team()
            var ids: Array = Database.styles.keys()
            ids.sort()
            for a: String in ids:
                for b: String in ids:
                    for g in games:
                        var c2 := _config(neutral, neutral, pitch_id, size, duration, 1000 + g)
                        c2.style_override = [Database.styles[a], Database.styles[b]]
                        cfgs.append(c2)
                        meta.append({"a": a, "b": b})
        "strength":
            # uniform-attribute squads (same style) at different levels: does the stronger team win?
            var levels := [90, 80, 70, 60, 50]
            for la: int in levels:
                for lb: int in levels:
                    if la == lb:
                        continue
                    for g in games:
                        var ta := _neutral_team(la)
                        var tb := _neutral_team(lb)
                        cfgs.append(_config(ta, tb, pitch_id, size, duration, 2000 + g))
                        meta.append({"a": ta.id, "b": tb.id, "la": la, "lb": lb})
        "versus":
            # the current bots against the frozen legacy bots: same team on both sides (mirror match),
            # sides swapped, so only the AI differs
            var ids5: Array = Database.teams.keys()
            ids5.sort()
            for a: String in ids5:
                for g in games:
                    for legacy_side in 2:
                        var cv := _config(Database.teams[a], Database.teams[a], pitch_id, size, duration, 3000 + g)
                        cv.legacy_bot = [legacy_side == 0, legacy_side == 1]
                        cfgs.append(cv)
                        meta.append({"a": a, "b": a, "legacy": legacy_side})
        "mlversus":
            # the neural-net policy (all outfield players) against the rule-based bots of the same team, sides
            # swapped. In the report "NEW" = the neural net, "legacy" = the rule-based bot. Use pitch classic, size 3.
            var ids6: Array = Database.teams.keys()
            ids6.sort()
            for a: String in ids6:
                for g in games:
                    for rule_side in 2:
                        var cm := _config(Database.teams[a], Database.teams[a], pitch_id, size, duration, 4000 + g)
                        cm.ml_models[1 - rule_side] = MLP.from_dict(Database.read_json("res://data/models/es_balanced_best.json"))
                        cfgs.append(cm)
                        meta.append({"a": a, "b": a, "legacy": rule_side})
        "teams":
            var ids2: Array = cfg.get("ids", Database.teams.keys())      # optional "ids": [...] limits the teams
            ids2.sort()
            for a: String in ids2:
                for b: String in ids2:
                    if a == b:
                        continue
                    for g in games:
                        cfgs.append(_config(Database.teams[a], Database.teams[b], pitch_id, size, duration, 500 + g))
                        meta.append({"a": a, "b": b})
        "sanity":
            var ids3: Array = Database.teams.keys()
            ids3.sort()
            var rng := RandomNumberGenerator.new()
            rng.seed = 7
            for g in games:
                var a: String = ids3[rng.randi() % ids3.size()]
                var b: String = ids3[rng.randi() % ids3.size()]
                if a == b:
                    b = ids3[(ids3.find(a) + 1) % ids3.size()]
                cfgs.append(_config(Database.teams[a], Database.teams[b], pitch_id, size, duration, 77 + g))
                meta.append({"a": a, "b": b})
        _:
            var ids4: Array = Database.teams.keys()
            ids4.sort()
            cfgs.append(_config(Database.teams[ids4[0]], Database.teams[ids4[1]], pitch_id, size, duration, 1))
            meta.append({"a": ids4[0], "b": ids4[1]})

    if mode == "keeper":
        set_process(false)
        _run_keeper(pitch_id, size)
        return
    if mode == "human":
        set_process(false)
        _run_human(pitch_id, size, games, duration)
        return
    print("[experiment] mode=%s pitch=%s size=%d matches=%d" % [mode, pitch_id, size, cfgs.size()])
    t0 = Time.get_ticks_msec()
    batch.start(cfgs)


func _process(_delta: float) -> void:
    if batch.is_done():
        batch.finish()
        _report()
        set_process(false)
        get_tree().quit()


func _config(a: TeamDef, b: TeamDef, pitch_id: String, size: int, duration: float, seed_value: int) -> MatchConfig:
    var c := MatchConfig.new()
    c.pitch = Database.pitches[pitch_id]
    c.teams = [a, b]
    c.team_size = size
    c.duration = duration
    c.match_seed = seed_value
    c.resolve_kits()
    return c


func _neutral_team(level: int = 70) -> TeamDef:
    var t := TeamDef.new()
    t.id = "L%d" % level if str(cfg.get("mode", "")) == "strength" else "neutral"
    t.name = "Neutral"
    var layout := [["GK", 1], ["DEF", 4], ["DEF", 5], ["MID", 8], ["MID", 10], ["FWD", 9], ["FWD", 11]]
    for i in layout.size():
        var p := PlayerDef.new()
        p.id = "n%d" % i
        p.name = "N%d" % i
        p.pos = layout[i][0]
        p.number = layout[i][1]
        p.finishing = level
        p.passing = level
        p.defending = level
        p.positioning = level
        p.reaction = level
        t.players.append(p)
    t.style = Database.styles["balanced"]
    return t


func _report() -> void:
    var ms := Time.get_ticks_msec() - t0
    var mode: String = str(cfg.get("mode", "single"))
    var lines: PackedStringArray = []
    lines.append("== experiment %s: %d matches in %.1fs ==" % [mode, batch.results.size(), ms / 1000.0])

    # aggregate sanity numbers
    var goals := 0
    var shots := 0
    var sot := 0
    var passes := 0
    var passes_ok := 0
    var own := 0
    var recov := 0
    var poss_dev := 0.0
    var draws := 0
    var og_kinds: Dictionary = {}
    var og_dt := 0
    var og_speed := 0.0
    var saves := 0
    var ko_sum := 0
    var ko_n := 0
    var ko_first: Dictionary = {}
    var zones := [0, 0, 0, 0, 0]
    var idle := 0
    for r: Dictionary in batch.results:
        for zi in 5:
            zones[zi] += int(r["zones"][zi])
        idle += int(r["idle"])
        for w in r.get("kickoff_waits", []):
            ko_sum += int(w)
            ko_n += 1
        if not r.get("kickoff_waits", []).is_empty():
            ko_first[int(r["kickoff_waits"][0])] = true
        goals += int(r["scores"][0]) + int(r["scores"][1])
        if int(r["scores"][0]) == int(r["scores"][1]):
            draws += 1
        for ts: Dictionary in r["team_stats"]:
            shots += int(ts["shots"])
            sot += int(ts["shots_on_target"])
            passes += int(ts["passes"])
            passes_ok += int(ts["passes_ok"])
            recov += int(ts["recoveries"])
            saves += int(ts["saves"])
        poss_dev += absf(float(r["team_stats"][0]["possession"]) - 50.0)
        for e: Dictionary in r["events"]:
            if e["own"]:
                own += 1
                var key := "%s/%s" % [e["last_role"], e["last_kind"]]
                og_kinds[key] = int(og_kinds.get(key, 0)) + 1
                og_dt += int(e["dt"])
                og_speed += float(e["ball_speed"])
    var n := maxi(1, batch.results.size())
    lines.append("avg goals/match %.2f | shots %.1f | on target %.1f | passes %.1f (%.0f%% ok) | recoveries %.1f | own goals %.2f | draws %d/%d | |poss-50| %.1f" % [
        float(goals) / n, float(shots) / n, float(sot) / n, float(passes) / n,
        100.0 * passes_ok / maxf(1.0, passes), float(recov) / n, float(own) / n, draws, n, poss_dev / n])

    # --- grade distribution by role actually played
    var by_role: Dictionary = {}
    var xg_sum := 0.0
    var xg_goals := 0
    var all_r: Array = []
    for r: Dictionary in batch.results:
        for pl: Dictionary in r["players"]:
            var rk: String = str(pl["played"])
            if not by_role.has(rk):
                by_role[rk] = {"n": 0, "sum": 0.0, "sq": 0.0, "min": 99.0, "max": 0.0, "tkl": 0, "int": 0,
                    "rec": 0, "drb": 0, "disp": 0, "kp": 0, "prog": 0, "clr": 0, "g": 0, "a": 0, "sv": 0, "touch": 0}
            var b: Dictionary = by_role[rk]
            var g := float(pl["rating"])
            all_r.append(g)
            b["n"] += 1
            b["sum"] += g
            b["sq"] += g * g
            b["min"] = minf(b["min"], g)
            b["max"] = maxf(b["max"], g)
            b["tkl"] += int(pl["tackles"])
            b["int"] += int(pl["interceptions"])
            b["rec"] += int(pl["recoveries"])
            b["drb"] += int(pl["dribbles"])
            b["disp"] += int(pl["dispossessed"])
            b["kp"] += int(pl["key_passes"])
            b["prog"] += int(pl["progressive_passes"])
            b["clr"] += int(pl["clearances"])
            b["g"] += int(pl["goals"])
            b["a"] += int(pl["assists"])
            b["sv"] += int(pl["saves"])
            b["touch"] += int(pl["touches"])
            xg_sum += float(pl["xg"])
            xg_goals += int(pl["goals"])
    lines.append("grades by role played (per player-match): mean +-sd [min..max] | tkl int rec drb disp keyp prog clr g a sv touches")
    for rk: String in ["GK", "DEF", "MID", "FWD"]:
        if not by_role.has(rk):
            continue
        var b: Dictionary = by_role[rk]
        var m: float = float(b["sum"]) / float(b["n"])
        var sd: float = sqrt(maxf(0.0, float(b["sq"]) / float(b["n"]) - m * m))
        lines.append("  %s n=%d  %.2f +-%.2f [%.1f..%.1f] | %.2f %.2f %.2f %.2f %.2f %.2f %.2f %.2f %.2f %.2f %.2f %.1f" % [
            rk, b["n"], m, sd, b["min"], b["max"], float(b["tkl"]) / b["n"], float(b["int"]) / b["n"],
            float(b["rec"]) / b["n"], float(b["drb"]) / b["n"], float(b["disp"]) / b["n"], float(b["kp"]) / b["n"],
            float(b["prog"]) / b["n"], float(b["clr"]) / b["n"], float(b["g"]) / b["n"], float(b["a"]) / b["n"],
            float(b["sv"]) / b["n"], float(b["touch"]) / b["n"]])
    all_r.sort()
    if not all_r.is_empty():
        lines.append("  all: p10 %.1f  p50 %.1f  p90 %.1f | xG/match %.2f vs goals/match %.2f (own goals excluded)" % [
            all_r[int(all_r.size() * 0.1)], all_r[int(all_r.size() * 0.5)], all_r[int(all_r.size() * 0.9)],
            xg_sum / n, float(xg_goals) / n])

    var zsum := maxf(1.0, float(zones[0] + zones[1] + zones[2] + zones[3] + zones[4]))
    lines.append("ball zones (left->right fifths) %.0f/%.0f/%.0f/%.0f/%.0f %% | idle ball %.1f%% of play" % [
        100.0 * zones[0] / zsum, 100.0 * zones[1] / zsum, 100.0 * zones[2] / zsum, 100.0 * zones[3] / zsum,
        100.0 * zones[4] / zsum, 100.0 * idle / zsum])
    var real_goals := goals - own
    lines.append("keeper: saves/match %.1f | save rate %.0f%% (saves / (saves+goals)) | kickoff wait %.0f ticks avg | distinct first-kickoff waits %d/%d" % [
        float(saves) / n, 100.0 * saves / maxf(1.0, float(saves + real_goals)), float(ko_sum) / maxf(1.0, ko_n),
        ko_first.size(), n])
    if own > 0:
        lines.append("own goals by role/last-touch: %s | avg ticks since touch %.0f | avg ball speed %.1f" % [str(og_kinds), float(og_dt) / own, og_speed / own])
    if mode == "single":
        var r: Dictionary = batch.results[0]
        lines.append("%s %d - %d %s | MoM uid %d" % [r["teams"][0], r["scores"][0], r["scores"][1], r["teams"][1], r["mom"]])
        for e: Dictionary in r["events"]:
            lines.append("  %d' goal team %d by %s%s" % [int(e["clock"] / 60.0), e["team"], e["scorer_name"], " (OG)" if e["own"] else ""])
        for p: Dictionary in r["players"]:
            lines.append("  t%d %s %s rat %.1f g%d a%d sh%d/%d pass %d/%d rec %d sv %d dist %.0f" % [
                p["team"], str(p["role"]).rpad(3), str(p["name"]).rpad(18), p["rating"], p["goals"], p["assists"], p["shots_on_target"], p["shots"],
                p["passes_ok"], p["passes_ok"] + p["passes_failed"], p["recoveries"], p["saves"], p["distance"]])
    else:
        # standings per key (style id or team id)
        var tab: Dictionary = {}
        for i in batch.results.size():
            var r: Dictionary = batch.results[i]
            var m: Dictionary = meta[i]
            var ga: int = r["scores"][0]
            var gb: int = r["scores"][1]
            _acc(tab, m["a"], ga, gb)
            _acc(tab, m["b"], gb, ga)
        var keys: Array = tab.keys()
        keys.sort_custom(func(x: String, y: String) -> bool:
            return float(tab[x]["pts"]) / tab[x]["p"] > float(tab[y]["pts"]) / tab[y]["p"])
        lines.append("".rpad(18) + " P    W    D    L    GF/m  GA/m  pts/m")
        for k: String in keys:
            var t: Dictionary = tab[k]
            lines.append("%s %4d %4d %4d %4d %5.2f %5.2f %6.2f" % [k.rpad(18), t["p"], t["w"], t["d"], t["l"],
                float(t["gf"]) / t["p"], float(t["ga"]) / t["p"], float(t["pts"]) / t["p"]])
        if not mode.ends_with("versus"):
            # play-style profile per key: how a team actually plays
            var prof: Dictionary = {}
            for i in batch.results.size():
                var r2: Dictionary = batch.results[i]
                var m2: Dictionary = meta[i]
                for side in 2:
                    var pk: String = m2["a"] if side == 0 else m2["b"]
                    var ts2: Dictionary = r2["team_stats"][side]
                    if not prof.has(pk):
                        prof[pk] = {"n": 0, "poss": 0.0, "shots": 0, "sot": 0, "xg": 0.0, "passes": 0, "ok": 0, "drb": 0, "rec": 0}
                    var q: Dictionary = prof[pk]
                    q["n"] += 1
                    q["poss"] += float(ts2["possession"])
                    q["shots"] += int(ts2["shots"])
                    q["sot"] += int(ts2["shots_on_target"])
                    q["xg"] += float(ts2["xg"])
                    q["passes"] += int(ts2["passes"])
                    q["ok"] += int(ts2["passes_ok"])
                    q["drb"] += int(ts2["dribbles"])
                    q["rec"] += int(ts2["recoveries"])
            lines.append("play profile per match:      poss%  shots  on-tgt  xG    passes (ok%)  dribbles  tkl+int")
            for k: String in keys:
                var q: Dictionary = prof[k]
                var nq: float = float(q["n"])
                lines.append("%s %5.0f %6.1f %6.1f %5.2f %7.1f (%2.0f%%) %8.1f %8.1f" % [k.rpad(18), q["poss"] / nq,
                    q["shots"] / nq, q["sot"] / nq, q["xg"] / nq, q["passes"] / nq, 100.0 * q["ok"] / maxf(1.0, float(q["passes"])),
                    q["drb"] / nq, q["rec"] / nq])
    if mode.ends_with("versus"):
        var w := 0
        var d := 0
        var l := 0
        var gf_new := 0
        var ga_new := 0
        var per: Dictionary = {}
        var side_st := {"new": [0, 0, 0, 0, 0], "legacy": [0, 0, 0, 0, 0]}     # shots, on target, passes, passes ok, tackles+interceptions
        for i in batch.results.size():
            var r: Dictionary = batch.results[i]
            var m: Dictionary = meta[i]
            var ns: int = 1 - int(m["legacy"])
            for pair: Array in [["new", ns], ["legacy", 1 - ns]]:
                var ts: Dictionary = r["team_stats"][int(pair[1])]
                var a: Array = side_st[pair[0]]
                a[0] += int(ts["shots"])
                a[1] += int(ts["shots_on_target"])
                a[2] += int(ts["passes"])
                a[3] += int(ts["passes_ok"])
                a[4] += int(ts["recoveries"])
            var gn: int = r["scores"][ns]
            var go: int = r["scores"][1 - ns]
            gf_new += gn
            ga_new += go
            if not per.has(m["a"]):
                per[m["a"]] = [0, 0, 0, 0, 0]
            var e: Array = per[m["a"]]
            e[3] += gn
            e[4] += go
            if gn > go:
                w += 1
                e[0] += 1
            elif gn == go:
                d += 1
                e[1] += 1
            else:
                l += 1
                e[2] += 1
        var nn := maxi(1, w + d + l)
        lines.append(("NEURAL NET (as NEW) vs RULE-BASED bot (as legacy)" if mode == "mlversus" else "NEW bot vs LEGACY bot") + " (mirror teams): W %d  D %d  L %d  | win%% %.0f  pts/m %.2f | GF %.2f GA %.2f per match" % [
            w, d, l, 100.0 * w / nn, (3.0 * w + d) / nn, float(gf_new) / nn, float(ga_new) / nn])
        for who: String in ["new", "legacy"]:
            var a: Array = side_st[who]
            lines.append("  %-6s per match: shots %.1f | on target %.1f (%.0f%%) | passes %.1f (%.0f%% ok) | recoveries %.1f" % [
                who, float(a[0]) / nn, float(a[1]) / nn, 100.0 * a[1] / maxf(1.0, a[0]), float(a[2]) / nn,
                100.0 * a[3] / maxf(1.0, a[2]), float(a[4]) / nn])
        for k: String in per:
            var e: Array = per[k]
            lines.append("  %s  W%d D%d L%d  GF %d GA %d" % [str(k).rpad(10), e[0], e[1], e[2], e[3], e[4]])
    if mode == "strength":
        # stronger side's result by rating gap (pooled over home/away)
        var gaps: Dictionary = {}
        for i in batch.results.size():
            var r: Dictionary = batch.results[i]
            var m: Dictionary = meta[i]
            var strong_is_a: bool = int(m["la"]) > int(m["lb"])
            var gs: int = r["scores"][0] if strong_is_a else r["scores"][1]
            var gw: int = r["scores"][1] if strong_is_a else r["scores"][0]
            var gap: int = absi(int(m["la"]) - int(m["lb"]))
            if not gaps.has(gap):
                gaps[gap] = {"n": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0}
            var e: Dictionary = gaps[gap]
            e["n"] += 1
            e["gf"] += gs
            e["ga"] += gw
            if gs > gw:
                e["w"] += 1
            elif gs == gw:
                e["d"] += 1
            else:
                e["l"] += 1
        lines.append("stronger side by rating gap:  n   win%  draw%  loss%  GF/m  GA/m")
        var gk: Array = gaps.keys()
        gk.sort()
        for gap: int in gk:
            var e: Dictionary = gaps[gap]
            lines.append("  gap %2d  %4d  %5.0f  %5.0f  %5.0f  %5.2f %5.2f" % [gap, e["n"], 100.0 * e["w"] / e["n"],
                100.0 * e["d"] / e["n"], 100.0 * e["l"] / e["n"], float(e["gf"]) / e["n"], float(e["ga"]) / e["n"]])
    var text := "\n".join(lines)
    print(text)
    var f := FileAccess.open("res://experiments/results_%s.txt" % mode, FileAccess.WRITE)
    if f != null:
        f.store_string(text + "\n")


func _acc(tab: Dictionary, key: String, gf: int, ga: int) -> void:
    if not tab.has(key):
        tab[key] = {"p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "pts": 0}
    var t: Dictionary = tab[key]
    t["p"] += 1
    t["gf"] += gf
    t["ga"] += ga
    if gf > ga:
        t["w"] += 1
        t["pts"] += 3
    elif gf == ga:
        t["d"] += 1
        t["pts"] += 1
    else:
        t["l"] += 1


## mode "human": a scripted player controls one team (auto switch, like TEAM control) and chases the ball.
## Measures how often his bot teammates crash into him, who the AI picks as keeper, and the goals.
func _run_human(pitch_id: String, size: int, games: int, duration: float) -> void:
    var ids: Array = Database.teams.keys()
    ids.sort()
    var contact := 0
    var crowd := 0
    var human_keeper := 0
    var ticks := 0
    var goals_for := 0
    var goals_against := 0
    var shots_against := 0
    var saves := 0
    for g in games:
        var a: String = ids[g % ids.size()]
        var b: String = ids[(g + 3) % ids.size()]
        var c := _config(Database.teams[a], Database.teams[b], pitch_id, size, duration, 900 + g)
        c.control = MatchConfig.ControlMode.TEAM
        c.auto_switch = true
        c.human_team = 0
        var sim := MatchSim.new(c)
        var guard := 0
        while sim.state != MatchSim.State.ENDED and guard < 60 * 60 * 6:
            guard += 1
            _drive_human(sim)
            sim.step()
            var h := sim.controlled
            if h != null and sim.state == MatchSim.State.PLAYING and not sim.kickoff_active:
                ticks += 1
                var near := false
                for m: SimPlayer in sim.team_lists[0]:
                    if m != h and m.pos.distance_to(h.pos) < 34.0:
                        near = true
                if near:
                    contact += 1
                var bots_chasing := 0
                for m: SimPlayer in sim.brains[0].chasers:
                    if m != h:
                        bots_chasing += 1
                if h.pos.distance_to(sim.ball.pos) < 70.0 and bots_chasing > 0:
                    crowd += 1
                if sim.brains[0].keeper == h:
                    human_keeper += 1
        var r := sim.make_result()
        goals_for += int(r["scores"][0])
        goals_against += int(r["scores"][1])
        shots_against += int(r["team_stats"][1]["shots_on_target"])
        saves += int(r["team_stats"][1]["saves"]) if false else int(r["team_stats"][0]["saves"])
    var lines: PackedStringArray = []
    lines.append("== human-control experiment: %d matches, %d active ticks ==" % [games, ticks])
    lines.append("teammate within 34px of the human: %.1f%% of ticks" % (100.0 * contact / maxf(1.0, ticks)))
    lines.append("a bot chaser while the human is on the ball: %.1f%% of ticks" % (100.0 * crowd / maxf(1.0, ticks)))
    lines.append("human assigned as keeper: %.1f%% of ticks" % (100.0 * human_keeper / maxf(1.0, ticks)))
    lines.append("goals for/against per match: %.2f / %.2f | opp shots on target %.1f | own saves %.1f" % [
        float(goals_for) / games, float(goals_against) / games, float(shots_against) / games, float(saves) / games])
    var text := "\n".join(lines)
    print(text)
    var f := FileAccess.open("res://experiments/results_human.txt", FileAccess.WRITE)
    if f != null:
        f.store_string(text + "\n")
    get_tree().quit()


func _drive_human(sim: MatchSim) -> void:
    var h := sim.controlled
    if h == null:
        return
    var ax := sim.attack_dir(0)
    var goal := Vector2(ax * sim.pitch.half_w, 0.0)
    var to_ball := sim.ball.pos - h.pos
    var d := to_ball.length()
    var behind := sim.ball.pos - (goal - sim.ball.pos).normalized() * 28.0
    var dir := (behind - h.pos).normalized() if d > 60.0 else to_ball.normalized()
    var kick := d < 36.0 and (goal - sim.ball.pos).length() < 360.0 and (sim.ball.pos.x - h.pos.x) * ax > 0.0
    sim.set_human_input(dir, kick)


## mode "keeper": shot-stopping test. A shot is fired at the goal of team 1 from a random spot at a random
## aimed point inside the goal mouth; everybody except the goalkeeper is parked out of the way.
func _run_keeper(pitch_id: String, size: int) -> void:
    var trials: int = int(cfg.get("trials", 120))
    var variants: Array = cfg.get("variants", [[0.22, 0.3, 50.0, 140.0, 600.0]])
    var out_lines: PackedStringArray = []
    for v: Array in variants:
        StyleBot.KEEP_F = float(v[0])
        StyleBot.KEEP_FS = float(v[1])
        StyleBot.KEEP_CAP = float(v[2])
        StyleBot.KEEP_CAPS = float(v[3])
        StyleBot.KEEP_FAR = float(v[4])
        out_lines.append(_keeper_trial(pitch_id, size, trials, str(v)))
    out_lines.append_array(debug_lines)
    var text := "\n".join(out_lines)
    print(text)
    var f := FileAccess.open("res://experiments/results_keeper.txt", FileAccess.WRITE)
    if f != null:
        f.store_string(text + "\n")
    get_tree().quit()


var debug_lines: PackedStringArray = []


func _keeper_trial(pitch_id: String, size: int, trials: int, label: String) -> String:
    var ids: Array = Database.teams.keys()
    ids.sort()
    var rng := RandomNumberGenerator.new()
    rng.seed = 4242
    var res := {}
    for speed: float in [5.0, 6.5]:
        for bucket in 3:
            res["%.1f/%d" % [speed, bucket]] = {"n": 0, "goal": 0, "save": 0, "miss": 0}
    for i in trials:
        var a: String = ids[i % ids.size()]
        var b: String = ids[(i + 3) % ids.size()]
        var c := _config(Database.teams[a], Database.teams[b], pitch_id, size, 60.0, 3000 + i)
        var sim := MatchSim.new(c)
        sim.kickoff_active = false
        sim.kickoff_taker = null
        var gx := sim.attack_dir(0) * sim.pitch.half_w
        var speed: float = [5.0, 6.5][i % 2]
        var bucket := (i / 2) % 3
        var dist: float = [rng.randf_range(110.0, 200.0), rng.randf_range(200.0, 300.0), rng.randf_range(300.0, 420.0)][bucket]
        var sy := rng.randf_range(-sim.pitch.half_h * 0.7, sim.pitch.half_h * 0.7)
        var ty := rng.randf_range(-(sim.pitch.goal_half - 14.0), sim.pitch.goal_half - 14.0)
        var from := Vector2(gx - sim.attack_dir(0) * dist, sy)
        sim.ball.pos = from
        sim.ball.vel = (Vector2(gx, ty) - from).normalized() * speed
        var shooter: SimPlayer = sim.team_lists[0][1]
        sim.last_touch = shooter
        sim.last_touch_tick = sim.tick
        sim.last_touch_kicked = true
        sim.last_touch_kind = "shot"
        var park := func() -> void:
            for t in 2:
                for p: SimPlayer in sim.team_lists[t]:
                    if t == 1 and p == sim.brains[1].keeper:
                        continue
                    if t == 1 and sim.brains[1].keeper == null and p.role == "GK":
                        continue
                    p.pos = Vector2(-sim.attack_dir(0) * sim.pitch.half_w * 0.5, -sim.pitch.half_h * 0.85 + float(p.slot) * 12.0)
                    p.vel = Vector2.ZERO
            # the shooter stands just behind the ball, so the keeper is NOT closer to it
            shooter.pos = from - Vector2(sim.attack_dir(0), 0.0) * 28.0
            shooter.vel = Vector2.ZERO
        # the keeper gets 70 ticks to react to the ball standing there (a dribbler lining up the shot)
        var vel0 := sim.ball.vel
        for k in 70:
            sim.ball.pos = from
            sim.ball.vel = Vector2.ZERO
            park.call()
            sim.step()
        sim.ball.pos = from
        sim.ball.vel = vel0
        sim.last_touch = shooter
        sim.last_touch_kicked = true
        sim.last_touch_kind = "shot"
        var kp: SimPlayer = sim.brains[1].keeper
        var k_at := kp.pos if kp != null else Vector2.ZERO
        var k_v := kp.vel if kp != null else Vector2.ZERO
        var s0: int = sim.scores[0]
        var outcome := "miss"
        var mind := 9999.0
        var kend := Vector2.ZERO
        for k in 200:
            park.call()
            sim.step()
            var kk: SimPlayer = sim.brains[1].keeper
            if kk != null:
                mind = minf(mind, kk.pos.distance_to(sim.ball.pos))
                kend = kk.pos
            if sim.scores[0] > s0:
                outcome = "goal"
                break
            if sim.last_touch != null and sim.last_touch.team == 1:
                outcome = "save"
                break
            if sim.ball.vel.length() < 0.3:
                break
        if outcome == "goal" and dist > 300.0 and debug_lines.size() < 14:
            debug_lines.append("GOAL sp%.1f d%.0f from(%.0f,%.0f) aim y%.0f | keeper at (%.0f,%.0f) v(%.1f,%.1f) goalx %.0f | keeper=%s mind %.0f kend (%.0f,%.0f)" % [
                speed, dist, from.x, from.y, ty, k_at.x, k_at.y, k_v.x, k_v.y, gx, str(kp.role if kp != null else "none"), mind, kend.x, kend.y])
        res["%.1f/%d" % [speed, bucket]][outcome if outcome != "goal" else "goal"] += 1
        res["%.1f/%d" % [speed, bucket]]["n"] += 1
    var tg := 0
    var tn := 0
    var parts: PackedStringArray = []
    for k: String in res.keys():
        var r: Dictionary = res[k]
        tg += int(r["goal"])
        tn += int(r["n"])
        parts.append("%s:%.0f%%" % [k, 100.0 * r["goal"] / maxf(1.0, r["n"])])
    return "%s goal rate %.0f%% | %s" % [label, 100.0 * tg / maxf(1.0, tn), " ".join(parts)]
