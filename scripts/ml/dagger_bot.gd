class_name DaggerBot
extends BotController
## DAgger data collection: the teacher always labels the state, the student acts
## with probability (1 - beta). Records (features, teacher action).

var teacher: BotController
var student: MLBot
var rec: MLRecorder
var beta := 1.0
var rng: RandomNumberGenerator


func _init(t: BotController, s: MLBot, r: MLRecorder, b: float, g: RandomNumberGenerator) -> void:
    teacher = t
    student = s
    rec = r
    beta = b
    rng = g


func decide(sim: MatchSim, p: SimPlayer) -> void:
    var obs := MLBot.features(sim, p)
    teacher.decide(sim, p)
    var idx := RecordingBot.label(sim, p)
    var kick := p.input_kick
    if student != null and rng.randf() >= beta:
        student.decide(sim, p)
    rec.n_in = obs.size()
    rec.xs.append_array(obs)
    rec.ym.append(idx)
    rec.yk.append(1 if kick else 0)
