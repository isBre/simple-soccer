"""A player's skill (0-100, data/players) as the rule-based AI's precision and reaction. It never changes the physics: every
body is the same, a bot is exactly as good as its player."""
import random

from ..vec import clamp, lerpf, roundi


def quality(skill: float) -> float:
    """Maps a skill (0-100) to a 0..1 quality: 40 -> 0, 95 -> 1."""
    return clamp((skill - 40.0) / 55.0, 0.0, 1.0)


def attach_skill(p):
    """The AI fields of one match player from its PlayerDef's skill (one number for what used to be five attributes)."""
    q = quality(p.pdef.skill)
    p.defend_q = q                                         # marking tightness, interceptions
    p.vision = q                                           # how much of the play it reads
    p.reaction_delay = roundi(lerpf(14.0, 0.0, q))         # ticks of delayed ball perception
    p.err_finish = lerpf(0.24, 0.005, q)                   # radians (std dev) aim error when shooting
    p.err_pass = lerpf(0.20, 0.005, q)                     # radians (std dev) aim error when passing
    p.pos_noise = lerpf(70.0, 2.0, q)                      # px of positioning inaccuracy
    p.think_ticks = roundi(lerpf(18.0, 6.0, q))            # ticks between two decisions of the ball carrier
    p.rng = random.Random(p.ai_seed)
