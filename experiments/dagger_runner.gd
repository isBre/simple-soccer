extends Node
## DAgger loop: iteration 0 = teacher demonstrations; iteration i: the student (mixed with the
## teacher by beta) plays, the teacher labels the visited states, data is aggregated, net retrained.
## After every iteration the student is evaluated vs every style (quick), final = full eval with teacher.
## Config: res://experiments/dagger_config.json   Output: results_dagger.txt, data/models/dagger_*.json

var cfg: Dictionary = {}
var phase := ""
var batch := SimBatch.new()
var recorders: Array = []
var net: MLP = null
var thread: Thread = null
var meta: Array = []
var iter := 0
var iters := 5
var teacher := "balanced"
var pitch_id := "classic"
var size := 3
var duration := 180.0
var X := PackedFloat32Array()
var YM := PackedInt32Array()
var YK := PackedInt32Array()
var n_in := 0
var lines: PackedStringArray = []
var best := -1.0
var t0 := 0
var rng := RandomNumberGenerator.new()
var styles: Array = []


func _ready() -> void:
    var c = Database.read_json("res://experiments/dagger_config.json")
    cfg = c if c is Dictionary else {}
    teacher = str(cfg.get("imitate", "balanced"))
    pitch_id = str(cfg.get("pitch", "classic"))
    size = int(cfg.get("size", 3))
    duration = float(cfg.get("duration", 180.0))
    iters = int(cfg.get("iters", 5))
    rng.seed = 42
    styles = Database.styles.keys()
    styles.sort()
    t0 = Time.get_ticks_msec()
    lines.append("== DAgger: teacher=%s %s %dv%d %.0fs ==" % [teacher, pitch_id, size, size, duration])
    _start_collect()


func _log(t: String) -> void:
    print(t)
    lines.append(t)
    var f := FileAccess.open("res://experiments/results_dagger.txt", FileAccess.WRITE)
    if f != null:
        f.store_string("\n".join(lines) + "\n")


func _process(_d: float) -> void:
    if phase == "collect" and batch.is_done():
        batch.finish()
        _aggregate()
        _start_train()
    elif phase == "train" and thread != null and not thread.is_alive():
        thread.wait_to_finish()
        _start_qeval()
    elif phase == "qeval" and batch.is_done():
        batch.finish()
        _after_qeval()
    elif phase == "final" and batch.is_done():
        batch.finish()
        _final_report()
        set_process(false)
        get_tree().quit()


func _start_collect() -> void:
    var betas: Array = cfg.get("betas", [1.0, 0.5, 0.25, 0.0, 0.0, 0.0, 0.0, 0.0])
    var beta: float = float(betas[mini(iter, betas.size() - 1)])
    var cfgs: Array = []
    recorders.clear()
    for g in int(cfg.get("collect_games", 2)):
        for opp: String in styles:
            var side := g % 2
            var m := _config(1000 + iter * 97 + g * 31 + styles.find(opp))
            m.style_override = [null, null]
            m.style_override[side] = Database.styles[teacher]
            m.style_override[1 - side] = Database.styles[opp]
            var rec := MLRecorder.new()
            m.dagger[side] = {"rec": rec, "net": net, "beta": beta, "temp": 1.0}
            recorders.append(rec)
            cfgs.append(m)
    print("[dagger] iter %d: collecting %d matches (beta=%.2f)" % [iter, cfgs.size(), beta])
    phase = "collect"
    batch = SimBatch.new()
    batch.start(cfgs)


func _aggregate() -> void:
    var keep := float(cfg.get("keep", 0.4))
    var added := 0
    for r: MLRecorder in recorders:
        n_in = maxi(n_in, r.n_in)
        for i in r.ym.size():
            if rng.randf() < keep:
                X.append_array(r.xs.slice(i * r.n_in, (i + 1) * r.n_in))
                YM.append(r.ym[i])
                YK.append(r.yk[i])
                added += 1
    recorders.clear()
    print("[dagger] iter %d: +%d samples, dataset %d" % [iter, added, YM.size()])


func _start_train() -> void:
    var total := YM.size()
    var cap := int(cfg.get("train_cap", 100000))
    var Xs := X
    var ys := YM
    var ks := YK
    if total > cap:
        Xs = PackedFloat32Array()
        ys = PackedInt32Array()
        ks = PackedInt32Array()
        var kp := float(cap) / total
        for i in total:
            if rng.randf() < kp:
                Xs.append_array(X.slice(i * n_in, (i + 1) * n_in))
                ys.append(YM[i])
                ks.append(YK[i])
    if net == null:
        var hidden := int(cfg.get("hidden", 64))
        net = MLP.new(PackedInt32Array([n_in, hidden, hidden, 10]), rng)
    var epochs := int(cfg.get("first_epochs", 8)) if iter == 0 else int(cfg.get("epochs", 4))
    print("[dagger] iter %d: training on %d samples, %d epochs" % [iter, ys.size(), epochs])
    phase = "train"
    thread = Thread.new()
    thread.start(_train.bind(Xs, ys, ks, epochs, float(cfg.get("lr", 0.002)), float(cfg.get("kick_weight", 8.0))))


func _train(Xs: PackedFloat32Array, ys: PackedInt32Array, ks: PackedInt32Array, epochs: int, lr: float, kw: float) -> void:
    net.fit(Xs, ys, ks, epochs, 64, lr, kw, rng)
    net.kick_bias = -0.5 * log(kw)


## Builds evaluation matches. kinds: "ml" (student), "teacher".
func _start_eval(kinds: Array, games: int, seed0: int, next_phase: String) -> void:
    var cfgs: Array = []
    meta.clear()
    for opp: String in styles:
        for g in games:
            for side in 2:
                for kind: String in kinds:
                    var m := _config(seed0 + g * 13 + styles.find(opp))
                    m.style_override = [null, null]
                    m.style_override[side] = Database.styles[teacher]
                    m.style_override[1 - side] = Database.styles[opp]
                    if kind == "ml":
                        m.ml_models[side] = net
                    cfgs.append(m)
                    meta.append({"opp": opp, "side": side, "kind": kind})
    phase = next_phase
    batch = SimBatch.new()
    batch.start(cfgs)


func _start_qeval() -> void:
    _start_eval(["ml"], int(cfg.get("eval_games", 1)), 7000, "qeval")


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
    _log("iter %d: student pts/m %.2f  GF %.2f  GA %.2f   (dataset %d, %.0fs elapsed)" % [
        iter, a[0], a[1], a[2], YM.size(), (Time.get_ticks_msec() - t0) / 1000.0])
    Database.write_json("res://data/models/dagger_%s_last.json" % teacher, net.to_dict())
    if a[0] > best:
        best = a[0]
        Database.write_json("res://data/models/dagger_%s_best.json" % teacher, net.to_dict())
    iter += 1
    if iter > iters:
        net = MLP.from_dict(Database.read_json("res://data/models/dagger_%s_best.json" % teacher))
        _start_eval(["ml", "teacher"], int(cfg.get("final_games", 2)), 5000, "final")
    else:
        _start_collect()


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


func _config(seed_value: int) -> MatchConfig:
    var neutral := _neutral_team()
    var c := MatchConfig.new()
    c.pitch = Database.pitches[pitch_id]
    c.teams = [neutral, neutral]
    c.team_size = size
    c.duration = duration
    c.match_seed = seed_value
    c.resolve_kits()
    return c
