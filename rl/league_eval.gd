extends Node
## League evaluation of an exported model on the 5v5 arena: the net drives ALL 5 players (keeper included)
## against each of the 16 rule-based teams, on both sides, full 180 s matches (SimBatch, all cores).
## Also writes rl/teams_info.json (id, strength, style, tier, held_out) for the trainer.
##   godot --headless --path . res://rl/league_eval.tscn -- --model res://out_5v5/x.json --games 4 [--duration 180]
## Held-out teams (never trained against): sorted by strength, indices 1, 5, 9, 13 (one per tier).

var batch := SimBatch.new()
var meta: Array = []
var ids: Array = []
var info: Dictionary = {}
var model_path := ""
var t0 := 0


func _ready() -> void:
	var a := OS.get_cmdline_user_args()
	var games := 4
	var duration := 180.0
	for i in a.size():
		if a[i] == "--model": model_path = a[i + 1]
		if a[i] == "--games": games = int(a[i + 1])
		if a[i] == "--duration": duration = float(a[i + 1])
	var teams: Array = Database.teams.values()
	teams.sort_custom(func(x: TeamDef, y: TeamDef) -> bool: return x.strength() < y.strength())
	var tiers := ["weak", "average", "strong", "elite"]
	var list: Array = []
	for i in teams.size():
		var t: TeamDef = teams[i]
		ids.append(t.id)
		info[t.id] = {"id": t.id, "strength": snappedf(t.strength(), 0.1), "style": t.style_id,
			"tier": tiers[mini(i / 4, 3)], "held_out": i % 4 == 1}
		list.append(info[t.id])
	Database.write_json("res://rl/teams_info.json", list)
	if model_path == "":
		get_tree().quit()
		return
	var net := MLP.from_dict(Database.read_json(model_path))
	var cfgs: Array = []
	var seed_i := 0
	for id: String in ids:
		for side in 2:
			for g in games:
				var c := MatchConfig.new()
				c.pitch = Database.pitches["arena"]
				c.team_size = 5
				c.duration = duration
				seed_i += 1
				c.match_seed = 50000 + seed_i
				c.teams = [Database.teams["owls"], Database.teams["owls"]]
				c.teams[1 - side] = Database.teams[id]
				c.resolve_kits()
				c.ml_models[side] = net
				c.ml_keeper = true
				cfgs.append(c)
				meta.append({"opp": id, "side": side})
	t0 = Time.get_ticks_msec()
	print("[league] %d matches vs %d teams, model %s" % [cfgs.size(), ids.size(), model_path])
	batch.start(cfgs)


func _process(_d: float) -> void:
	if model_path == "" or not batch.is_done():
		return
	batch.finish()
	var tab := {}
	for i in batch.results.size():
		var r: Dictionary = batch.results[i]
		var m: Dictionary = meta[i]
		var gf: int = r["scores"][m["side"]]
		var ga: int = r["scores"][1 - int(m["side"])]
		if not tab.has(m["opp"]):
			tab[m["opp"]] = {"p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0}
		var t: Dictionary = tab[m["opp"]]
		t["p"] += 1
		t["gf"] += gf
		t["ga"] += ga
		if gf > ga: t["w"] += 1
		elif gf == ga: t["d"] += 1
		else: t["l"] += 1
	var lines: PackedStringArray = []
	var agg := {}
	lines.append("LEAGUE model=%s  (%.0fs)" % [model_path, (Time.get_ticks_msec() - t0) / 1000.0])
	lines.append("team".rpad(11) + "tier".rpad(9) + "str".rpad(6) + "held".rpad(5) + "W  D  L   pts/m   GF/GA")
	for id: String in ids:
		var t: Dictionary = tab[id]
		var inf: Dictionary = info[id]
		var pts: float = 3.0 * t["w"] + t["d"]
		lines.append("%s%s%s%s%d  %d  %d   %.2f    %.2f/%.2f" % [id.rpad(11), str(inf["tier"]).rpad(9), str(inf["strength"]).rpad(6),
			("yes" if inf["held_out"] else "").rpad(5), t["w"], t["d"], t["l"], pts / t["p"], float(t["gf"]) / t["p"], float(t["ga"]) / t["p"]])
		for key in ["all", inf["tier"], "held" if inf["held_out"] else "train"]:
			if not agg.has(key): agg[key] = [0.0, 0, 0.0, 0.0]
			agg[key][0] += pts
			agg[key][1] += t["p"]
			agg[key][2] += t["gf"]
			agg[key][3] += t["ga"]
	for key in ["weak", "average", "strong", "elite", "train", "held", "all"]:
		var g: Array = agg[key]
		lines.append("SUMMARY %s: pts/m %.2f  GF %.2f GA %.2f  (%d matches)" % [key.rpad(8), g[0] / g[1], g[2] / g[1], g[3] / g[1], g[1]])
	var text := "\n".join(lines)
	print(text)
	var f := FileAccess.open("res://logs/league_last.txt", FileAccess.WRITE)
	if f != null:
		f.store_string(text + "\n")
	get_tree().quit()
