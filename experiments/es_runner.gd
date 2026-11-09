extends Node
## Evolution-strategies fine-tuning (RL without gradients) of a pre-trained policy.
## Each generation: 2*pairs perturbed copies of the policy play the same set of matches
## (common random numbers); fitness = goal difference; rank-normalised update of the weights.
## Config: res://experiments/es_config.json   Output: results_es.txt, data/models/es_*.json

var cfg: Dictionary = {}
var phase := ""
var batch := SimBatch.new()
var net: MLP = null
var theta := PackedFloat32Array()
var eps_list: Array = []
var meta: Array = []
var gen := 0
var gens := 20
var pairs := 6
var sigma := 0.02
var alpha := 0.005
var opps_per_gen := 4
var eval_every := 4
var teacher := "balanced"
var pitch_id := "classic"
var size := 3
var gen_dur := 90.0
var duration := 180.0
var lines: PackedStringArray = []
var best := -1.0
var t0 := 0
var rng := RandomNumberGenerator.new()
var styles: Array = []


func _ready() -> void:
    var c = Database.read_json("res://experiments/es_config.json")
    cfg = c if c is Dictionary else {}
    teacher = str(cfg.get("teacher", "balanced"))
    pitch_id = str(cfg.get("pitch", "classic"))
    size = int(cfg.get("size", 3))
    gens = int(cfg.get("gens", 20))
    pairs = int(cfg.get("pairs", 6))
    sigma = float(cfg.get("sigma", 0.02))
    alpha = float(cfg.get("alpha", 0.005))
    opps_per_gen = int(cfg.get("opps_per_gen", 4))
    eval_every = int(cfg.get("eval_every", 4))
    gen_dur = float(cfg.get("gen_duration", 90.0))
    duration = float(cfg.get("duration", 180.0))
    rng.seed = 123
    styles = Database.styles.keys()
    styles.sort()
    net = MLP.from_dict(Database.read_json(str(cfg.get("start", "res://data/models/dagger_balanced_best.json"))))
    theta = net.get_params()
    t0 = Time.get_ticks_msec()
    lines.append("== ES fine-tuning: %d params, %d gens, pop %d, sigma %.3f alpha %.4f ==" % [theta.size(), gens, pairs * 2, sigma, alpha])
    _start_eval(["ml"], 1, 7000, "qeval")


func _log(t: String) -> void:
    print(t)
    lines.append(t)
    var f := FileAccess.open("res://experiments/results_es.txt", FileAccess.WRITE)
    if f != null:
        f.store_string("\n".join(lines) + "\n")


func _process(_d: float) -> void:
    if phase == "gen" and batch.is_done():
        batch.finish()
        _gen_done()
    elif phase == "qeval" and batch.is_done():
        batch.finish()
        _after_qeval()
    elif phase == "final" and batch.is_done():
        batch.finish()
        _final_report()
        set_process(false)
        get_tree().quit()


func _start_gen() -> void:
    eps_list.clear()
    var cfgs: Array = []
    meta.clear()
    var n := theta.size()
    for pi in pairs:
        var eps := PackedFloat32Array()
        eps.resize(n)
        for i in n:
            eps[i] = rng.randfn()
        eps_list.append(eps)
    for ci in pairs * 2:
        var eps: PackedFloat32Array = eps_list[ci / 2]
        var sgn := 1.0 if ci % 2 == 0 else -1.0
        var cand := net.clone()
        var th := theta.duplicate()
        for i in n:
            th[i] += sgn * sigma * eps[i]
        cand.set_params(th)
        for k in opps_per_gen:
            var opp: String = styles[(gen * opps_per_gen + k) % styles.size()]
            var side := (gen + k) % 2
            var m := _config(9000 + gen * 17 + k, gen_dur)
            m.style_override = [null, null]
            m.style_override[side] = Database.styles[teacher]
            m.style_override[1 - side] = Database.styles[opp]
            m.ml_models[side] = cand
            cfgs.append(m)
            meta.append({"cand": ci, "side": side})
    phase = "gen"
    batch = SimBatch.new()
    batch.start(cfgs)


func _gen_done() -> void:
    var npop := pairs * 2
    var fit := PackedFloat32Array()
    fit.resize(npop)
    for i in batch.results.size():
        var r: Dictionary = batch.results[i]
        var m: Dictionary = meta[i]
        fit[m["cand"]] += float(r["scores"][m["side"]]) - float(r["scores"][1 - int(m["side"])])
    # centered ranks in [-0.5, 0.5]
    var order: Array = range(npop)
    order.sort_custom(func(a: int, b: int) -> bool: return fit[a] < fit[b])
    var u := PackedFloat32Array()
    u.resize(npop)
    for rank in npop:
        u[order[rank]] = float(rank) / (npop - 1) - 0.5
    var n := theta.size()
    var grad := PackedFloat32Array()
    grad.resize(n)
    for pi in pairs:
        var eps: PackedFloat32Array = eps_list[pi]
        var w := u[pi * 2] - u[pi * 2 + 1]
        for i in n:
            grad[i] += w * eps[i]
    for i in n:
        theta[i] += alpha / (npop * sigma) * grad[i]
    net.set_params(theta)
    var mean_fit := 0.0
    for f in fit:
        mean_fit += f
    print("[es] gen %d done: mean GD %.2f best %.1f worst %.1f (%.0fs)" % [gen, mean_fit / npop, fit[order[npop - 1]], fit[order[0]], (Time.get_ticks_msec() - t0) / 1000.0])
    gen += 1
    if gen >= gens:
        _start_eval(["ml"], 1, 7000, "qeval")
    elif gen % eval_every == 0:
        _start_eval(["ml"], 1, 7000, "qeval")
    else:
        _start_gen()


func _start_eval(kinds: Array, games: int, seed0: int, next_phase: String) -> void:
    var cfgs: Array = []
    meta.clear()
    for opp: String in styles:
        for g in games:
            for side in 2:
                for kind: String in kinds:
                    var m := _config(seed0 + g * 13 + styles.find(opp), duration)
                    m.style_override = [null, null]
                    m.style_override[side] = Database.styles[teacher]
                    m.style_override[1 - side] = Database.styles[opp]
                    if kind == "ml":
                        m.ml_models[side] = net.clone()
                    cfgs.append(m)
                    meta.append({"opp": opp, "side": side, "kind": kind})
    phase = next_phase
    batch = SimBatch.new()
    batch.start(cfgs)


func _summ() -> Dictionary:
    var tab: Dictionary = {}
    for i in batch.results.size():
        var r: Dictionary = batch.results[i]
        var m: Dictionary = meta[i]
        var gf: int = r["scores"][m["side"]]
        var ga: int = r["scores"][1 - int(m["side"])]
        var key := "%s|%s" % [m["kind"], m["opp"]]
        if not tab.has(key):
            tab[key] = {"p": 0, "pts": 0, "gf": 0, "ga": 0}
        var t: Dictionary = tab[key]
        t["p"] += 1
        t["gf"] += gf
        t["ga"] += ga
        t["pts"] += 3 if gf > ga else (1 if gf == ga else 0)
    return tab


func _avg(tab: Dictionary, kind: String) -> Array:
    var pts := 0.0
    var gf := 0.0
    var ga := 0.0
    for opp: String in styles:
        var t: Dictionary = tab["%s|%s" % [kind, opp]]
        pts += float(t["pts"]) / t["p"]
        gf += float(t["gf"]) / t["p"]
        ga += float(t["ga"]) / t["p"]
    var n := float(styles.size())
    return [pts / n, gf / n, ga / n]


func _after_qeval() -> void:
    var a := _avg(_summ(), "ml")
    _log("gen %d: policy pts/m %.2f  GF %.2f  GA %.2f   (%.0fs elapsed)" % [gen, a[0], a[1], a[2], (Time.get_ticks_msec() - t0) / 1000.0])
    Database.write_json("res://data/models/es_%s_last.json" % teacher, net.to_dict())
    if a[0] > best:
        best = a[0]
        Database.write_json("res://data/models/es_%s_best.json" % teacher, net.to_dict())
    if gen >= gens:
        net = MLP.from_dict(Database.read_json("res://data/models/es_%s_best.json" % teacher))
        _start_eval(["ml", "teacher"], int(cfg.get("final_games", 2)), 5000, "final")
    else:
        _start_gen()


func _final_report() -> void:
    var tab := _summ()
    _log("-- final (best model) vs teacher --")
    _log("opponent".rpad(16) + " teacher pts/m  GF/GA      |  ML pts/m  GF/GA")
    for opp: String in styles:
        var a: Dictionary = tab["teacher|" + opp]
        var b: Dictionary = tab["ml|" + opp]
        _log("%s %9.2f   %.2f/%.2f   |  %7.2f   %.2f/%.2f" % [opp.rpad(16),
            float(a["pts"]) / a["p"], float(a["gf"]) / a["p"], float(a["ga"]) / a["p"],
            float(b["pts"]) / b["p"], float(b["gf"]) / b["p"], float(b["ga"]) / b["p"]])
    var ta := _avg(tab, "teacher")
    var ma := _avg(tab, "ml")
    _log("average".rpad(16) + " %9.2f %17s %7.2f   (ML GF %.2f GA %.2f)" % [ta[0], "|", ma[0], ma[1], ma[2]])
    _log("total %.0fs" % ((Time.get_ticks_msec() - t0) / 1000.0))


func _neutral_team() -> TeamDef:
    var t := TeamDef.new()
    t.id = "neutral"
    t.name = "Neutral"
    var layout := [["GK", 1], ["DEF", 4], ["DEF", 5], ["MID", 8], ["MID", 10], ["FWD", 9], ["FWD", 11]]
    for i in layout.size():
        var p := PlayerDef.new()
        p.id = "n%d" % i
        p.name = "N%d" % i
        p.pos = layout[i][0]
        p.number = layout[i][1]
        p.finishing = 70
        p.passing = 70
        p.defending = 70
        p.positioning = 70
        p.reaction = 70
        t.players.append(p)
    t.style = Database.styles["balanced"]
    return t


func _config(seed_value: int, dur: float) -> MatchConfig:
    var neutral := _neutral_team()
    var c := MatchConfig.new()
    c.pitch = Database.pitches[pitch_id]
    c.teams = [neutral, neutral]
    c.team_size = size
    c.duration = dur
    c.match_seed = seed_value
    c.resolve_kits()
    return c
