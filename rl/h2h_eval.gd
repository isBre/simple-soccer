extends Node
## Head to head of two nets on the 5v5 arena, full matches, both sides (SimBatch, all cores). Both nets run in
## tools/net_server.py (ports), so this is cheap on a Raspberry Pi.
##   godot --headless --path . res://rl/h2h_eval.tscn -- --a PORT --b PORT --name "RL Team 4" [--games 2] [--duration 90]
## Prints one line:  H2H <name>: W x D y L z | pts/m | GF/GA | N matches    (a = the net being evaluated, results from its side)

var batch := SimBatch.new()
var meta: Array = []
var opp_name := "opponent"


func _ready() -> void:
	var port_a := 0
	var port_b := 0
	var games := 2
	var duration := 90.0
	var a := OS.get_cmdline_user_args()
	for i in a.size() - 1:
		if a[i] == "--a": port_a = int(a[i + 1])
		if a[i] == "--b": port_b = int(a[i + 1])
		if a[i] == "--name": opp_name = a[i + 1]
		if a[i] == "--games": games = int(a[i + 1])
		if a[i] == "--duration": duration = float(a[i + 1])
	if port_a == 0 or port_b == 0:
		get_tree().quit()
		return
	var cfgs: Array = []
	for side in 2:                                   # side = the side the evaluated net plays
		for g in games:
			var c := MatchConfig.new()
			c.pitch = Database.pitches["arena"]
			c.team_size = 5
			c.duration = duration
			c.match_seed = 70000 + side * 1000 + g
			c.teams = [Database.teams["owls"], Database.teams["rl_team_4"]]
			if side == 1:
				c.teams = [Database.teams["rl_team_4"], Database.teams["owls"]]
			c.resolve_kits()
			c.ml_models[side] = RemoteMLP.new(port_a)
			c.ml_models[1 - side] = RemoteMLP.new(port_b)
			c.ml_keeper = true
			cfgs.append(c)
			meta.append(side)
	batch.start(cfgs)


func _process(_d: float) -> void:
	if meta.is_empty() or not batch.is_done():
		return
	batch.finish()
	var w := 0
	var d := 0
	var l := 0
	var gf := 0
	var ga := 0
	for i in batch.results.size():
		var side: int = meta[i]
		var sc: Array = batch.results[i]["scores"]
		gf += sc[side]
		ga += sc[1 - side]
		if sc[side] > sc[1 - side]: w += 1
		elif sc[side] == sc[1 - side]: d += 1
		else: l += 1
	var n := batch.results.size()
	var mean := (3.0 * w + d) / n
	var se := sqrt(maxf((9.0 * w + d) / n - mean * mean, 0.0) / n)
	print("H2H %s: W %d D %d L %d | pts/m %.2f | GF/GA %.2f/%.2f | %d matches | se %.2f" % [opp_name, w, d, l, mean, float(gf) / n, float(ga) / n, n, se])
	get_tree().quit()
