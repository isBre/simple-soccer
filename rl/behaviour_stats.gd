extends Node
## Behaviour statistics, RL Team vs rule-based opponents per decision: jitter, kick presses, clumping, keeper position.
##   godot --headless --path . res://rl/behaviour_stats.tscn
var results: Array = []
var model_net: MLP = null          # optional --model <res:// json>: measure this net instead of the team's shipped one
var mutex := Mutex.new()

func _run(i: int) -> void:
	var rl: TeamDef = Database.teams["rl_team"]
	var opp: TeamDef = Database.teams[["owls", "cobalt", "tide", "dune"][i % 4]]
	var c := MatchConfig.new()
	c.pitch = Database.pitches["arena"]
	c.team_size = 5
	c.duration = 60.0
	c.match_seed = 900 + i
	c.teams = [rl, opp]
	c.resolve_kits()
	if model_net != null:
		c.ml_models[0] = model_net
		c.ml_keeper = true
	var sim := MatchSim.new(c)
	var st := [{}, {}]
	for t in 2:
		st[t] = {"n": 0, "dir_change": 0, "kick_rise": 0, "kick_hold": 0, "idle": 0, "near_ball": 0.0, "spacing": 0.0, "gk_dist": 0.0, "gk_n": 0, "speed": 0.0, "turn180": 0, "near250": 0.0, "nn_dist": 0.0, "close_pairs": 0.0, "passes": 0.0, "passes_ok": 0.0}
	var prev := {}
	var prev_kick := {}
	while sim.state != MatchSim.State.ENDED and sim.tick < 60 * 120:
		sim.step()
		if sim.tick % 2 != 0 or sim.kickoff_active or sim.state != MatchSim.State.PLAYING:
			continue
		for t in 2:
			var s: Dictionary = st[t]
			var team: Array = sim.team_lists[t]
			var near := 0
			for p: SimPlayer in team:
				s["n"] += 1
				var d := p.input_dir
				var pd: Vector2 = prev.get(p.uid, d)
				if d.distance_to(pd) > 0.3:
					s["dir_change"] += 1
				if d.length() > 0.1 and pd.length() > 0.1 and d.dot(pd) < -0.5:
					s["turn180"] += 1
				prev[p.uid] = d
				if d.length() < 0.1:
					s["idle"] += 1
				if p.input_kick:
					s["kick_hold"] += 1
					if not prev_kick.get(p.uid, false):
						s["kick_rise"] += 1
				prev_kick[p.uid] = p.input_kick
				s["speed"] += p.vel.length()
				if p.pos.distance_to(sim.ball.pos) < 120.0:
					near += 1
				if p.pos.distance_to(sim.ball.pos) < 250.0:
					s["near250"] += 1.0 / 5.0
			s["near_ball"] += near
			for a: SimPlayer in team:
				var nn := 1.0e9
				for b: SimPlayer in team:
					if a != b:
						var dd := a.pos.distance_to(b.pos)
						nn = minf(nn, dd)
						if dd < 110.0 and a.uid < b.uid:
							s["close_pairs"] += 1.0 / 5.0
				s["nn_dist"] += nn / 5.0
			var sp := 0.0
			var cnt := 0
			for a in team:
				for b in team:
					if a != b:
						sp += (a as SimPlayer).pos.distance_to((b as SimPlayer).pos)
						cnt += 1
			s["spacing"] += sp / maxf(1.0, cnt)
			var gk: SimPlayer = team[0]
			var own_goal := Vector2(-sim.pitch.half_w * sim.attack_dir(t), 0.0)
			s["gk_dist"] += gk.pos.distance_to(own_goal)
			s["gk_n"] += 1
	var res := sim.make_result()
	for t in 2:
		st[t]["passes"] = res["team_stats"][t]["passes"]
		st[t]["passes_ok"] = res["team_stats"][t]["passes_ok"]
	mutex.lock()
	results.append({"st": st, "score": sim.scores, "ticks": sim.tick})
	mutex.unlock()

func _ready() -> void:
	var a := OS.get_cmdline_user_args()
	for i in a.size():
		if a[i] == "--model" and i + 1 < a.size():
			model_net = MLP.from_dict(Database.read_json(a[i + 1]))
	var n := 8
	var tasks: Array[int] = []
	for i in n:
		tasks.append(WorkerThreadPool.add_task(_run.bind(i), true))
	for t in tasks:
		WorkerThreadPool.wait_for_task_completion(t)
	var agg := [{}, {}]
	for r in results:
		for t in 2:
			for k in r["st"][t]:
				agg[t][k] = agg[t].get(k, 0.0) + r["st"][t][k]
	for t in 2:
		var a: Dictionary = agg[t]
		var n_dec: float = a["n"]
		var per_sec := 30.0   # decisions per second per player (60 Hz / 2)
		print("%s: dir changes/s %.2f | 180-turns/s %.3f | kick presses/s %.2f | kick held %.0f%% | idle %.0f%% | speed %.2f px/tick | teammates spacing %.0f px | players within 120px of ball (team) %.2f | keeper dist from own goal %.0f px" % [
			["RL Team", "rule-based"][t], a["dir_change"] / n_dec * per_sec, a["turn180"] / n_dec * per_sec, a["kick_rise"] / n_dec * per_sec,
			100.0 * a["kick_hold"] / n_dec, 100.0 * a["idle"] / n_dec, a["speed"] / n_dec, a["spacing"] / (n_dec / 5.0), a["near_ball"] / (n_dec / 5.0), a["gk_dist"] / a["gk_n"]])
	for t in 2:
		var a: Dictionary = agg[t]
		var n_dec: float = a["n"] / 5.0     # team-decisions
		print("%s: players within 250px of ball %.2f | nearest-teammate dist %.0f px | pairs closer than 110px %.2f | passes/match %.1f (%.0f%% ok)" % [
			["RL Team", "rule-based"][t], a["near250"] / (a["n"] / 5.0) * 5.0 / 5.0 * 5.0 / 5.0, a["nn_dist"] / n_dec, a["close_pairs"] / n_dec, a["passes"] / results.size(), 100.0 * a["passes_ok"] / maxf(1.0, a["passes"])])
	var sc := ""
	for r in results:
		sc += str(r["score"]) + " "
	print("scores (RL first): ", sc)
	get_tree().quit()
