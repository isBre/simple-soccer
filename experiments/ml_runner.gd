extends Node
## Imitation-learning pipeline:
##  1. collect: StyleBot (style X) plays vs every style, its outfield decisions are recorded
##  2. train:   MLP learns observation -> (move, kick) (background thread)
##  3. eval:    MLP team vs every style, compared with the teacher style itself
## Config: res://experiments/ml_config.json   Output: results_ml.txt + data/models/imitate_<style>.json

var cfg: Dictionary = {}
var phase := "collect"
var batch := SimBatch.new()
var recorders: Array = []
var net: MLP = null
var thread: Thread = null
var meta: Array = []
var t0 := 0
var teacher := "balanced"
var pitch_id := "classic"
var size := 3
var duration := 180.0
var games := 2
var log_lines: PackedStringArray = []


func _ready() -> void:
    var c = Database.read_json("res://experiments/ml_config.json")
    cfg = c if c is Dictionary else {}
    teacher = str(cfg.get("imitate", "balanced"))
    pitch_id = str(cfg.get("pitch", "classic"))
    size = int(cfg.get("size", 3))
    duration = float(cfg.get("duration", 180.0))
    games = int(cfg.get("games", 2))
    t0 = Time.get_ticks_msec()
    if bool(cfg.get("eval_only", false)):
        net = MLP.from_dict(Database.read_json("res://data/models/imitate_%s.json" % teacher))
        _start_eval()
        return
    var ids: Array = Database.styles.keys()
    ids.sort()
    var cfgs: Array = []
    for g in int(cfg.get("collect_games", 2)):
        for opp: String in ids:
            var side := g % 2
            var m := _config(pitch_id, size, duration, 1000 + g * 31 + ids.find(opp))
            m.style_override = [null, null]
            m.style_override[side] = Database.styles[teacher]
            m.style_override[1 - side] = Database.styles[opp]
            var rec := MLRecorder.new()
            m.recorders[side] = rec
            recorders.append(rec)
            cfgs.append(m)
    print("[ml] collecting from %d matches (teacher=%s)" % [cfgs.size(), teacher])
    batch.start(cfgs)


func _process(_d: float) -> void:
    if phase == "collect" and batch.is_done():
        batch.finish()
        _start_training()
    elif phase == "train" and thread != null and not thread.is_alive():
        thread.wait_to_finish()
        _start_eval()
    elif phase == "eval" and batch.is_done():
        batch.finish()
        _report()
        set_process(false)
        get_tree().quit()


func _start_training() -> void:
    var X := PackedFloat32Array()
    var ym := PackedInt32Array()
    var yk := PackedInt32Array()
    var n_in := 0
    for r: MLRecorder in recorders:
        X.append_array(r.xs)
        ym.append_array(r.ym)
        yk.append_array(r.yk)
        n_in = maxi(n_in, r.n_in)
    var total := ym.size()
    var cap := int(cfg.get("samples", 60000))
    var rng := RandomNumberGenerator.new()
    rng.seed = 42
    if total > cap:   # random subsample
        var X2 := PackedFloat32Array()
        var y2 := PackedInt32Array()
        var k2 := PackedInt32Array()
        var keep := float(cap) / total
        for i in total:
            if rng.randf() < keep:
                X2.append_array(X.slice(i * n_in, (i + 1) * n_in))
                y2.append(ym[i])
                k2.append(yk[i])
        X = X2
        ym = y2
        yk = k2
    print("[ml] %d samples collected, training on %d (n_in=%d)" % [total, ym.size(), n_in])
    var hidden := int(cfg.get("hidden", 32))
    net = MLP.new(PackedInt32Array([n_in, hidden, hidden, 10]), rng)
    phase = "train"
    var epochs := int(cfg.get("epochs", 6))
    var lr := float(cfg.get("lr", 0.003))
    var kw := float(cfg.get("kick_weight", 20.0))
    thread = Thread.new()
    thread.start(_train.bind(X, ym, yk, epochs, lr, kw, rng))


func _train(X: PackedFloat32Array, ym: PackedInt32Array, yk: PackedInt32Array, epochs: int,
        lr: float, kw: float, rng: RandomNumberGenerator) -> void:
    net.fit(X, ym, yk, epochs, 64, lr, kw, rng)
    net.kick_bias = -0.5 * log(kw)


func _start_eval() -> void:
    if not bool(cfg.get("eval_only", false)):
        Database.write_json("res://data/models/imitate_%s.json" % teacher, net.to_dict())
    print("[ml] trained, model saved; evaluating")
    var ids: Array = Database.styles.keys()
    ids.sort()
    var cfgs: Array = []
    meta.clear()
    for opp: String in ids:
        for g in games:
            for side in 2:
                for kind in ["ml", "teacher"]:
                    var m := _config(pitch_id, size, duration, 5000 + g * 13 + ids.find(opp))
                    m.style_override = [null, null]
                    m.style_override[side] = Database.styles[teacher]
                    m.style_override[1 - side] = Database.styles[opp]
                    if kind == "ml":
                        m.ml_models[side] = net
                        m.ml_temperature = float(cfg.get("temperature", 1.0))
                    cfgs.append(m)
                    meta.append({"opp": opp, "side": side, "kind": kind})
    phase = "eval"
    batch = SimBatch.new()
    batch.start(cfgs)


func _report() -> void:
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
    var lines: PackedStringArray = []
    lines.append("== imitation learning (T=%.2f): teacher=%s, pitch=%s %dv%d, %.0fs, total %.0fs ==" % [float(cfg.get("temperature", 1.0)), teacher, pitch_id, size, size, duration, (Time.get_ticks_msec() - t0) / 1000.0])
    lines.append("opponent".rpad(16) + " teacher pts/m  GF/GA      |  ML pts/m  GF/GA")
    var ids: Array = Database.styles.keys()
    ids.sort()
    var tp := 0.0
    var mp := 0.0
    for opp: String in ids:
        var a: Dictionary = tab["teacher|" + opp]
        var b: Dictionary = tab["ml|" + opp]
        lines.append("%s %9.2f   %.2f/%.2f   |  %7.2f   %.2f/%.2f" % [opp.rpad(16),
            float(a["pts"]) / a["p"], float(a["gf"]) / a["p"], float(a["ga"]) / a["p"],
            float(b["pts"]) / b["p"], float(b["gf"]) / b["p"], float(b["ga"]) / b["p"]])
        tp += float(a["pts"]) / a["p"]
        mp += float(b["pts"]) / b["p"]
    lines.append("average".rpad(16) + " %9.2f %17s %7.2f" % [tp / ids.size(), "|", mp / ids.size()])
    var text := "\n".join(lines)
    print(text)
    var f := FileAccess.open("res://experiments/results_ml.txt", FileAccess.WRITE)
    if f != null:
        f.store_string(text + "\n")


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


func _config(pitch: String, team_size: int, dur: float, seed_value: int) -> MatchConfig:
    var neutral := _neutral_team()
    var c := MatchConfig.new()
    c.pitch = Database.pitches[pitch]
    c.teams = [neutral, neutral]
    c.team_size = team_size
    c.duration = dur
    c.match_seed = seed_value
    c.resolve_kits()
    return c
