"""The AI of a match: rule-based teams (rules.py: TeamBrain + StyleBot) and neural-net teams (nets.py). MatchAI is what
soccer.match.Match calls on every AI tick."""
import random

from ..vec import clamp, lerpf, roundi
from . import nets
from .opus import OpusBot, OpusBrain
from .rules import StyleBot, TeamBrain


def quality(attr: float) -> float:
    """Maps an attribute (0-100) to a 0..1 quality: 40 -> 0, 95 -> 1."""
    return clamp((attr - 40.0) / 55.0, 0.0, 1.0)


def attach_attributes(p):
    """The AI-only effects of a player's attributes (they never change the physics): there are no difficulty levels, a bot
    is exactly as good as its player, for every team."""
    d = p.pdef
    q_rea, q_fin, q_pas, q_pos = quality(d.reaction), quality(d.finishing), quality(d.passing), quality(d.positioning)
    p.defend_q = quality(d.defending)                       # marking tightness, interceptions
    p.vision = (q_pas + q_pos + q_rea) / 3.0                # how much of the play he reads
    p.reaction_delay = roundi(lerpf(14.0, 0.0, q_rea))      # ticks of delayed ball perception
    p.err_finish = lerpf(0.24, 0.005, q_fin)                # radians (std dev) aim error when shooting
    p.err_pass = lerpf(0.20, 0.005, q_pas)                  # radians (std dev) aim error when passing
    p.pos_noise = lerpf(70.0, 2.0, q_pos)                   # px of positioning inaccuracy
    p.think_ticks = roundi(lerpf(18.0, 6.0, p.vision))      # ticks between two decisions of the ball carrier
    p.rng = random.Random(p.ai_seed)


class MatchAI:
    """The two team brains and one bot per player. A net (MatchConfig.nets) drives its whole team, keeper included; a net
    that does not fit the team size falls back to the team's rule-based style (see `warnings`)."""

    def __init__(self, m):
        self.warnings = []
        self.kinds = []
        self.resets = m.reset_count
        m.brains = [(OpusBrain if m.styles[t].brain == "opus" else TeamBrain)(t, m.styles[t]) for t in (0, 1)]
        for p in m.players:
            attach_attributes(p)
        for t in (0, 1):
            spec = m.cfg.nets[t]
            net = None
            if spec:
                try:
                    net = nets.load(spec)
                    if not nets.fits(net.n_in, len(m.team_lists[t])):
                        self.warnings.append("team %d: a net with %d inputs does not fit %d players; rule-based instead"
                                             % (t, net.n_in, len(m.team_lists[t])))
                        net = None
                except (OSError, ValueError, KeyError, ConnectionError) as e:
                    self.warnings.append("team %d: cannot load net %s (%s); rule-based instead" % (t, spec, e))
                    net = None
            for p in m.team_lists[t]:
                rule_bot = OpusBot if m.styles[t].brain == "opus" else StyleBot
                p.bot_ai = nets.NetBot(net, m.cfg.net_temperature) if net is not None else rule_bot(m.styles[t])
            self.kinds.append({"kind": "net", "n_in": net.n_in} if net is not None else {"kind": "rules"})

    def decide(self, m, update):
        """One AI tick: the team plans (every AI_PERIOD ticks), then the bots that are due set their inputs."""
        if m.reset_count != self.resets:           # a kickoff reset since the last tick: fresh team plans
            self.resets = m.reset_count
            for b in m.brains:
                b.reset()
        if update:
            for b in m.brains:
                b.update(m)
        by_net = {}
        for t in (0, 1):
            for p in m.team_lists[t]:
                if not p.bot or p.is_human or (m.tick + p.slot) % 2 != 0:
                    continue
                if isinstance(p.bot_ai, nets.NetBot):
                    by_net.setdefault(id(p.bot_ai.net), []).append(p)
                else:
                    p.bot_ai.decide(m, p)
        for group in by_net.values():              # one forward pass per net for all its players of this tick
            net = group[0].bot_ai.net
            out = net.forward(nets.features_group(m, group, net.n_in))
            for p, o in zip(group, out):
                p.bot_ai.act(m, p, o)
        m.keeper_uid = [b.keeper.uid if b.keeper is not None else -1 for b in m.brains]
