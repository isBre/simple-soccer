extends Node
## Behaviour statistics, RL Team vs rule-based opponents per decision: jitter, kick presses, clumping, keeper position.
##   godot --headless --path . res://rl/behaviour_stats.tscn [-- --model res://x.json | --remote PORT]
## --remote PORT: the measured net runs in tools/net_server.py (see league_eval.gd).
## Also prints one "SCOUT {json}" line for the scouting page: team shape in and out of possession by depth rank (who is really the
## deepest / most advanced player, whatever its slot), keeper presence, pressing, possession, territory and located events (shots
## for and against, completed passes between slots, recoveries), positions normalised to [-1, 1] in the RL team's attacking frame.
var results: Array = []
var model_net: MLP = null          # optional --model <res:// json>: measure this net instead of the team's shipped one
var remote_port := 0
var greedy := false          # --greedy: the net plays its best move instead of sampling
const GX := 14               # heatmap grid (the RL team always attacks to the right)
const GY := 8
var mutex := Mutex.new()

## Counts a position in a heatmap grid, in the team's attacking frame (x grows towards the opponent goal).
func _bin(grid: PackedFloat32Array, pos: Vector2, sim: MatchSim, team: int) -> void:
	var fx := clampf((pos.x * sim.attack_dir(team) / sim.pitch.half_w) * 0.5 + 0.5, 0.0, 0.9999)
	var fy := clampf((pos.y / sim.pitch.half_h) * 0.5 + 0.5, 0.0, 0.9999)
	grid[int(fy * GY) * GX + int(fx * GX)] += 1.0


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
	if greedy:
		c.ml_temperature = 0.0
	if remote_port > 0:
		c.ml_models[0] = RemoteMLP.new(remote_port)
		c.ml_keeper = true
	elif model_net != null:
		c.ml_models[0] = model_net
		c.ml_keeper = true
	var sim := MatchSim.new(c)
	sim.log_events = true
	var sc := {"role": [], "pos": {"in": [], "out": []}, "n_phase": {"in": 0, "out": 0}, "shape": {"in": [0.0, 0.0, 0.0, 0.0], "out": [0.0, 0.0, 0.0, 0.0]},
		"press": [0.0, 0.0, 0], "guarded": 0, "empty": 0, "deep_dist": 0.0, "n": 0, "tilt": 0, "own_half_ball": 0}
	for k in 5:
		sc["role"].append([0, 0, 0, 0, 0])
		sc["pos"]["in"].append([0.0, 0.0])
		sc["pos"]["out"].append([0.0, 0.0])
	var st := [{}, {}]
	for t in 2:
		st[t] = {"n": 0, "dir_change": 0, "kick_rise": 0, "kick_hold": 0, "idle": 0, "near_ball": 0.0, "spacing": 0.0, "gk_dist": 0.0, "gk_n": 0, "speed": 0.0, "turn180": 0, "near250": 0.0, "nn_dist": 0.0, "close_pairs": 0.0, "passes": 0.0, "passes_ok": 0.0, "key_passes": 0.0, "xa": 0.0, "shots": 0.0}
	var prev := {}
	var prev_kick := {}
	var heat: Array = []                 # RL team: one grid per slot, then the ball
	for k in 6:
		var grid := PackedFloat32Array()
		grid.resize(GX * GY)
		heat.append(grid)
	var roles := ["", "", "", "", ""]
	while sim.state != MatchSim.State.ENDED and sim.tick < 60 * 120:
		sim.step()
		if sim.tick % 2 != 0 or sim.kickoff_active or sim.state != MatchSim.State.PLAYING:
			continue
		for t in 2:
			var s: Dictionary = st[t]
			var team: Array = sim.team_lists[t]
			if t == 0:
				for p: SimPlayer in team:
					roles[p.slot] = p.role
					_bin(heat[p.slot], p.pos, sim, t)
				_bin(heat[5], sim.ball.pos, sim, t)
				_scout_tick(sc, sim, team)
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
	sc["events"] = sim.ev_log
	sc["possession"] = res["team_stats"][0]["possession"]
	for t in 2:
		st[t]["passes"] = res["team_stats"][t]["passes"]
		st[t]["passes_ok"] = res["team_stats"][t]["passes_ok"]
		st[t]["shots"] = res["team_stats"][t]["shots"]
	for pl: Dictionary in res["players"]:
		st[int(pl["team"])]["key_passes"] += float(pl.get("key_passes", 0))
		st[int(pl["team"])]["xa"] += float(pl.get("xa", 0.0))
	mutex.lock()
	results.append({"st": st, "score": sim.scores, "ticks": sim.tick, "heat": heat, "roles": roles, "scout": sc, "half": Vector2(sim.pitch.half_w, sim.pitch.half_h)})
	mutex.unlock()

## One sample of the RL team's shape (team 0, attacking frame, normalised): depth ranks, in / out of possession, pressing, keeper.
func _scout_tick(sc: Dictionary, sim: MatchSim, team: Array) -> void:
	var ax := sim.attack_dir(0)
	var hw := sim.pitch.half_w
	var hh := sim.pitch.half_h
	var q: Array = []
	for p: SimPlayer in team:
		q.append([Vector2(p.pos.x * ax / hw, p.pos.y / hh), p.slot])
	q.sort_custom(func(a, b): return a[0].x < b[0].x)          # rank 0 = the deepest player
	var lt := sim.last_touch
	var phase := ""
	if lt != null:
		phase = "in" if lt.team == 0 else "out"
	sc["n"] += 1
	var ball := Vector2(sim.ball.pos.x * ax / hw, sim.ball.pos.y / hh)
	if ball.x < 0.0:
		sc["own_half_ball"] += 1
	for r in q.size():
		sc["role"][q[r][1]][r] += 1
	if phase != "":
		sc["n_phase"][phase] += 1
		var lo := Vector2(9, 9)
		var hi := Vector2(-9, -9)
		for r in q.size():
			var v: Vector2 = q[r][0]
			sc["pos"][phase][r][0] += v.x
			sc["pos"][phase][r][1] += v.y
			lo = Vector2(minf(lo.x, v.x), minf(lo.y, v.y))
			hi = Vector2(maxf(hi.x, v.x), maxf(hi.y, v.y))
		var sh: Array = sc["shape"][phase]
		sh[0] += (hi.y - lo.y) * hh                            # width px
		sh[1] += (hi.x - lo.x) * hw                            # depth px
		sh[2] += (q[0][0].x + 1.0) * hw                        # last man: px from our goal line
		sh[3] += (q[1][0].x + 1.0) * hw                        # second deepest (back line) px from our goal line
		if phase == "in" and ball.x > 1.0 / 3.0:
			sc["tilt"] += 1
	if phase == "out":                                         # pressing: our two nearest players' distance to the ball
		var ds: Array = []
		for p: SimPlayer in team:
			ds.append(p.pos.distance_to(sim.ball.pos))
		ds.sort()
		sc["press"][0] += ds[0]
		sc["press"][1] += ds[1]
		sc["press"][2] += 1
	var own_goal := Vector2(-hw * ax, 0.0)
	var dmin := 1.0e9
	for p: SimPlayer in team:
		dmin = minf(dmin, p.pos.distance_to(own_goal))
	sc["deep_dist"] += dmin
	if dmin < 180.0:
		sc["guarded"] += 1
	if dmin > 300.0:
		sc["empty"] += 1


## Merges the scouting samples and located events of every match into the SCOUT line.
func _scout_summary() -> Dictionary:
	var hw := 640.0
	var hh := 300.0
	if not results.is_empty() and results[0].has("half"):
		hw = results[0]["half"].x
		hh = results[0]["half"].y
	var role := []
	var pos := {"in": [], "out": []}
	var nph := {"in": 0, "out": 0}
	var shape := {"in": [0.0, 0.0, 0.0, 0.0], "out": [0.0, 0.0, 0.0, 0.0]}
	var tot := {"n": 0, "guarded": 0, "empty": 0, "deep_dist": 0.0, "tilt": 0, "own_half_ball": 0, "possession": 0.0}
	var press := [0.0, 0.0, 0]
	for k in 5:
		role.append([0, 0, 0, 0, 0])
		pos["in"].append([0.0, 0.0])
		pos["out"].append([0.0, 0.0])
	var shots := []
	var shots_against := []
	var recov := []
	var edges := {}
	var pass_len := []
	var prog := 0
	var n_pass := 0
	var n_ok := 0
	var opp_build := 0                                         # opponent passes in their own 60% of the pitch (PPDA numerator)
	var def_high := 0                                          # our tackles / interceptions in that zone (PPDA denominator)
	for r in results:
		var sc: Dictionary = r["scout"]
		for k in 5:
			for j in 5:
				role[k][j] += sc["role"][k][j]
			for ph in ["in", "out"]:
				pos[ph][k][0] += sc["pos"][ph][k][0]
				pos[ph][k][1] += sc["pos"][ph][k][1]
		for ph in ["in", "out"]:
			nph[ph] += sc["n_phase"][ph]
			for j in 4:
				shape[ph][j] += sc["shape"][ph][j]
		for key in ["n", "guarded", "empty", "deep_dist", "tilt", "own_half_ball"]:
			tot[key] += sc[key]
		for j in 3:
			press[j] += sc["press"][j]
		tot["possession"] += sc["possession"] / float(results.size())
		for e: Array in sc["events"]:
			var kind: String = e[0]
			var x: float = e[4] / hw
			var y: float = e[5] / hh
			if int(e[2]) == 0:
				if kind.begins_with("shot"):
					shots.append([snappedf(x, 0.01), snappedf(y, 0.01), e[8], 1 if kind == "shot_on" else 0])
				elif kind == "pass_ok" or kind == "pass_fail":
					n_pass += 1
					if kind == "pass_ok":
						n_ok += 1
						var key := "%d-%d" % [int(e[3]) % 16, int(e[8]) % 16]
						edges[key] = edges.get(key, 0) + 1
						pass_len.append(roundf(Vector2(e[6] - e[4], e[7] - e[5]).length()))
						if e[6] - e[4] >= hw * 0.2:
							prog += 1
				else:
					recov.append([snappedf(x, 0.01), snappedf(y, 0.01), kind.substr(0, 1)])
					if kind != "recovery" and x > -0.2:
						def_high += 1
			else:
				if kind.begins_with("shot"):                       # opponent frame: mirror into ours
					shots_against.append([snappedf(-x, 0.01), snappedf(-y, 0.01), e[8], 1 if kind == "shot_on" else 0])
				elif (kind == "pass_ok" or kind == "pass_fail") and x < 0.2:
					opp_build += 1
	var avg := {"in": [], "out": []}
	var shape_out := {}
	for ph in ["in", "out"]:
		var n := maxf(nph[ph], 1)
		for k in 5:
			avg[ph].append([snappedf(pos[ph][k][0] / n, 0.01), snappedf(pos[ph][k][1] / n, 0.01)])
		shape_out[ph] = {"width_px": roundf(shape[ph][0] / n), "depth_px": roundf(shape[ph][1] / n),
			"last_man_px": roundf(shape[ph][2] / n), "back_line_px": roundf(shape[ph][3] / n)}
	var role_share := []
	for k in 5:
		var s := 0
		for j in 5:
			s += role[k][j]
		var row := []
		for j in 5:
			row.append(snappedf(100.0 * role[k][j] / maxf(s, 1), 0.1))
		role_share.append(row)
	var edge_list := []
	for key in edges:
		var parts: PackedStringArray = key.split("-")
		edge_list.append([int(parts[0]), int(parts[1]), edges[key]])
	var n_t := maxf(tot["n"], 1)
	var nm := maxf(results.size(), 1)
	return {"matches": results.size(), "possession_pct": snappedf(tot["possession"], 0.1), "ball_own_half_pct": snappedf(100.0 * tot["own_half_ball"] / n_t, 0.1),
		"field_tilt_pct": snappedf(100.0 * tot["tilt"] / maxf(nph["in"], 1), 0.1), "goal_guarded_pct": snappedf(100.0 * tot["guarded"] / n_t, 0.1),
		"goal_empty_pct": snappedf(100.0 * tot["empty"] / n_t, 0.1), "deepest_to_goal_px": roundf(tot["deep_dist"] / n_t),
		"press_d1_px": roundf(press[0] / maxf(press[2], 1)), "press_d2_px": roundf(press[1] / maxf(press[2], 1)),
		"ppda": snappedf(opp_build / maxf(def_high, 1), 0.01), "passes_match": snappedf(n_pass / nm, 0.1),
		"pass_ok_pct": snappedf(100.0 * n_ok / maxf(n_pass, 1), 0.1), "progressive_match": snappedf(prog / nm, 0.1),
		"shape": shape_out, "avg_pos": avg, "role_share": role_share, "edges": edge_list, "pass_len": pass_len,
		"shots": shots, "shots_against": shots_against, "recoveries": recov}


func _ready() -> void:
	var cli := OS.get_cmdline_user_args()
	for i in cli.size():
		if cli[i] == "--model" and i + 1 < cli.size():
			model_net = MLP.from_dict(Database.read_json(cli[i + 1]))
		if cli[i] == "--greedy":
			greedy = true
		if cli[i] == "--remote" and i + 1 < cli.size():
			remote_port = int(cli[i + 1])
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
		print("%s: players within 250px of ball %.2f | nearest-teammate dist %.0f px | pairs closer than 110px %.2f | passes/match %.1f (%.0f%% ok) | shots/match %.1f | key passes/match %.2f | xA/match %.2f" % [
			["RL Team", "rule-based"][t], a["near250"] / (a["n"] / 5.0) * 5.0 / 5.0 * 5.0 / 5.0, a["nn_dist"] / n_dec, a["close_pairs"] / n_dec, a["passes"] / results.size(), 100.0 * a["passes_ok"] / maxf(1.0, a["passes"]), a["shots"] / results.size(), a["key_passes"] / results.size(), a["xa"] / results.size()])
	# heatmaps (RL team): "HEAT <slot|ball> <role> <w> <h> v..." with v in per mille of that player's time, row by row from the top
	for k in 6:
		var total := 0.0
		var cells := PackedFloat32Array()
		cells.resize(GX * GY)
		for r in results:
			for c in GX * GY:
				cells[c] += r["heat"][k][c]
				total += r["heat"][k][c]
		var vals := PackedStringArray()
		for c in GX * GY:
			vals.append(str(int(cells[c] / maxf(total, 1.0) * 1000.0)))
		print("HEAT %s %s %d %d %s" % ["ball" if k == 5 else str(k), "-" if k == 5 else str(results[0]["roles"][k]), GX, GY, " ".join(vals)])
	var sc := ""
	for r in results:
		sc += str(r["score"]) + " "
	print("scores (RL first): ", sc)
	print("SCOUT " + JSON.stringify(_scout_summary()))
	get_tree().quit()
