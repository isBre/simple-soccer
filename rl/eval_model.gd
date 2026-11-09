extends Node
## Independent check of an exported model: plays it through the game's own MLP/MLBot path.
## godot --headless --path . res://rl/eval_model.tscn -- --model out_5v5/x.json --n_active 4 --episodes 200 [--opp balanced]

func _ready() -> void:
	var a := OS.get_cmdline_user_args()
	var path := "res://out_5v5/rl_s3_four_empty_last.json"
	var n_active := 4
	var episodes := 200
	var opp := "none"
	for i in a.size():
		if a[i] == "--model": path = a[i + 1]
		if a[i] == "--n_active": n_active = int(a[i + 1])
		if a[i] == "--episodes": episodes = int(a[i + 1])
		if a[i] == "--opp": opp = a[i + 1]
	var net := MLP.from_dict(Database.read_json(path))
	var counts := {1: 0, 2: 0, 3: 0, 4: 0}
	var steps_goal := 0
	var rng := RandomNumberGenerator.new()
	rng.seed = 777
	for ep in episodes:
		var e := RLEnv.new()
		e.configure({"n_active": n_active, "opp": opp, "spread": 1.0, "ball_speed": 2.0, "seed": 9000 + ep})
		e.external_actions = true
		e.reset()
		var bots: Array = []
		for p in e.agents:
			bots.append(MLBot.new(net, rng))
		var res := [0.0, false, 0]
		while not res[1]:
			for i in e.agents.size():
				(bots[i] as MLBot).decide(e.sim, e.agents[i])
			res = e.step(PackedByteArray())
		counts[res[2]] = counts.get(res[2], 0) + 1
		if res[2] == 1:
			steps_goal += e.steps
	print("EVAL model=%s n_active=%d opp=%s episodes=%d | goals %d own %d timeout %d conceded %d | goal%% %.1f | mean decisions to goal %.0f (%.1fs)" % [
		path, n_active, opp, episodes, counts[1], counts[2], counts[3], counts[4], 100.0 * counts[1] / episodes,
		float(steps_goal) / maxf(1.0, counts[1]), float(steps_goal) / maxf(1.0, counts[1]) / 30.0])
	get_tree().quit()
