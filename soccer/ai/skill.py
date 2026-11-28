"""A player's skill (0-100, data/players) as the rule-based AI's precision and reaction. It never changes the physics: every
body is the same, a bot is exactly as good as its player. The skill lives in the player's own bot: no other agent can read it
(soccer/core/view.py: others are judged by the generic skill)."""
import random

from ..core.public import quality
from ..core.vec import lerp, roundi


def attach_skill(bot, skill, seed):
    """A bot's own senses and precision from its player's skill (one number for what used to be five attributes), and its
    own random numbers."""
    q = quality(skill)
    bot.defend_q = q                                       # marking tightness, interceptions
    bot.vision = q                                         # how much of the play it reads
    bot.reaction_delay = roundi(lerp(14.0, 0.0, q))       # ticks of delayed ball perception
    bot.err_finish = lerp(0.24, 0.005, q)                 # radians (std dev) aim error when shooting
    bot.err_pass = lerp(0.20, 0.005, q)                   # radians (std dev) aim error when passing
    bot.pos_noise = lerp(70.0, 2.0, q)                    # px of positioning inaccuracy
    bot.think_ticks = roundi(lerp(18.0, 6.0, q))          # ticks between two decisions of the ball carrier
    bot.rng = random.Random(seed)
    return bot
