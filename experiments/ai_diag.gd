extends Node
## Diagnostic: why do shots miss? Runs a few matches single-threaded with StyleBot.DIAG on.

func _ready() -> void:
    StyleBot.DIAG = true
    StyleBot.diag = {}
    var ids: Array = Database.teams.keys()
    ids.sort()
    var shots := 0
    var sot := 0
    var goals := 0
    var n := 0
    var setups := [["classic", 3], ["arena", 5]]
    for s in setups:
        for g in 6:
            var a: String = ids[(g * 3) % ids.size()]
            var b: String = ids[(g * 5 + 1) % ids.size()]
            if a == b:
                b = ids[(g + 2) % ids.size()]
            var cfg := Database.make_config(a, b, s[0], s[1], 180.0, 900 + g)
            var sim := MatchSim.new(cfg)
            sim.run_to_end()
            n += 1
            goals += sim.scores[0] + sim.scores[1]
            for p in sim.players:
                shots += p.ps.shots
                sot += p.ps.shots_on_target
    var d: Dictionary = StyleBot.diag
    var k := maxf(float(d.get("shoot_kicks", 0.0)), 1.0)
    var lines: PackedStringArray = []
    lines.append("== ai_diag: %d matches, goals %d, stat shots %d (on target %d = %.0f%%) ==" % [n, goals, shots, sot, 100.0 * sot / maxf(shots, 1)])
    lines.append("shoot decisions %d, shoot kicks %d" % [int(d.get("shoot_decisions", 0)), int(k)])
    lines.append("on target, perfect aim, bot's velocity estimate: %.0f%%" % (100.0 * float(d.get("on_target_perfect", 0)) / k))
    lines.append("on target, perfect aim, TRUE ball velocity      : %.0f%%" % (100.0 * float(d.get("on_target_true_comp", 0)) / k))
    lines.append("mean |estimated - true| ball velocity at kick   : %.2f px/tick" % (float(d.get("vel_est_err_sum", 0)) / k))
    lines.append("on target, perfect aim from TRUE ball pos+vel      : %.0f%%" % (100.0 * float(d.get("on_target_true_origin", 0)) / k))
    lines.append("mean |predicted contact point - real ball pos| at kick: %.1f px" % (float(d.get("origin_err_sum", 0)) / k))
    lines.append("mean misalignment vs TRUE desired direction deg: %.1f" % (float(d.get("align_true_deg_sum", 0)) / k))
    var ka := maxf(float(d.get("aligned4", 0.0)), 1.0)
    lines.append("kicks within 4 deg of true desired dir: %d (%.0f%%), on target %.0f%%" % [int(d.get("aligned4", 0)), 100.0 * ka / k, 100.0 * float(d.get("aligned4_ot", 0)) / ka])
    lines.append("on target, skill error only  : %.0f%%" % (100.0 * float(d.get("on_target_skill_only", 0)) / k))
    lines.append("on target, ACTUAL            : %.0f%%" % (100.0 * float(d.get("on_target_actual", 0)) / k))
    lines.append("mean kick misalignment deg   : %.1f" % (float(d.get("align_deg_sum", 0)) / k))
    lines.append("mean skill error deg         : %.1f" % (float(d.get("skill_err_deg_sum", 0)) / k))
    lines.append("mean velocity-compensation shift deg: %.1f" % (float(d.get("comp_shift_deg_sum", 0)) / k))
    lines.append("mean ball speed at kick      : %.2f" % (float(d.get("vel_at_kick_sum", 0)) / k))
    for b in ["near", "mid", "far"]:
        var kb := maxf(float(d.get("kicks_" + b, 0.0)), 1.0)
        lines.append("  %s: %d kicks, %.0f%% on target" % [b, int(d.get("kicks_" + b, 0)), 100.0 * float(d.get("ot_" + b, 0)) / kb])
    var km := maxf(float(d.get("kicks_ball_moving", 0.0)), 1.0)
    lines.append("  ball already moving (>1.5): %d kicks, %.0f%% on target" % [int(d.get("kicks_ball_moving", 0)), 100.0 * float(d.get("ot_ball_moving", 0)) / km])
    var f := FileAccess.open("res://experiments/results_diag_after.txt", FileAccess.WRITE)
    f.store_string("\n".join(lines) + "\n")
    f.close()
    print("\n".join(lines))
    get_tree().quit()
