class_name RecordingBot
extends BotController
## Wraps another bot and records what it does as a discrete (move, kick) label.

var inner: BotController
var rec: MLRecorder


func _init(b: BotController, r: MLRecorder) -> void:
    inner = b
    rec = r


## Quantizes the player's current input into one of the 9 discrete move classes.
static func label(sim: MatchSim, p: SimPlayer) -> int:
    var d := p.input_dir
    d.x *= sim.attack_dir(p.team)
    var idx := 0
    if d.length() > 0.2:
        var bd := -2.0
        d = d.normalized()
        for k in range(1, 9):
            var dot := d.dot((MatchSim.DIRS[k] as Vector2).normalized())
            if dot > bd:
                bd = dot
                idx = k
    return idx


func decide(sim: MatchSim, p: SimPlayer) -> void:
    var obs := MLBot.features(sim, p)
    inner.decide(sim, p)
    var idx := label(sim, p)
    rec.n_in = obs.size()
    rec.xs.append_array(obs)
    rec.ym.append(idx)
    rec.yk.append(1 if p.input_kick else 0)
