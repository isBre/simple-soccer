"""Everything a player may know besides the view itself (docs/public_view.md): the clock, the physics, the calls, the move table
and the generic skill curve. Brains (soccer.ai) import constants from here and from nowhere else in the core."""

TICK = 1.0 / 60.0             # seconds per tick
AI_PERIOD = 2                 # a bot decides every AI_PERIOD ticks, staggered by slot (people decide every tick)
HIST = 32                     # ticks of recent history in the view
PLAYING, GOAL, ENDED = 0, 1, 2

# the physics of the bodies: anyone may simulate the ball and the players forward
KICK_STRENGTH = 5.0           # px/tick a kick adds along player -> ball
KICK_RANGE = 4.0              # px between the surfaces of player and ball within which a kick connects
BALL_DAMPING = 0.99           # the ball keeps this share of its speed every tick
PLAYER_DAMPING = 0.96
PLAYER_ACCEL = 0.1            # px/tick^2 with the stick held (top speed PLAYER_ACCEL * PLAYER_DAMPING / (1 - PLAYER_DAMPING) = 2.4)
PLAYER_KICK_ACCEL = 0.07      # while holding the kick button

# What a player can call to its teammates (the only way players talk; the opponents do not hear it)
INTENTS = ("none", "ball", "open", "run", "cover")
# the 9 discrete moves (index -> direction in the player's own frame, +x towards the opponent goal): nets and the trainer use them
DIRS = [0j, -1j, 1 - 1j, 1 + 0j, 1 + 1j, 1j, -1 + 1j, -1 + 0j, -1 - 1j]


def quality(skill: float) -> float:
    """The skill curve: a skill (0-100) as a 0..1 quality, 40 -> 0, 95 -> 1. Public because a player judges others by the
    generic skill (soccer.core.view GENERIC_*); a player's own skill stays in its own brain."""
    q = (skill - 40.0) / 55.0
    return 0.0 if q < 0.0 else (1.0 if q > 1.0 else q)
