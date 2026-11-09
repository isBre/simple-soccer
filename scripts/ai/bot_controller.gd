class_name BotController
extends RefCounted
## Base class for AI. Subclass it and override decide() to plug in your own AI
## (rule-based, neural net, RL policy, network bridge...).
##
## decide() is called every 2nd physics tick per player (30 Hz) and must set:
##   p.input_dir  : Vector2, length <= 1 (movement)
##   p.input_kick : bool (kick button held)
## Use sim.get_observation(p) for a normalized state vector.

func decide(_sim: MatchSim, _p: SimPlayer) -> void:
    pass
