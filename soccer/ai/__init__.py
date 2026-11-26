"""The AI of a match: rule-based players (rules.py: TeamBrain + StyleBot), Opus players (opus.py) and neural nets (nets.py),
one per slot as the team's line-up says (lineup.py). MatchAI is what soccer.match.Match calls on every AI tick."""
from . import nets
from .lineup import build
from .skill import attach_skill


class MatchAI:
    """The team brains and one bot per player (lineup.build). Anything that could not be set up as asked (a net that cannot
    be loaded or does not fit the size) is in `warnings`; `kinds` says what drives each team."""

    def __init__(self, m):
        self.warnings = []
        self.resets = m.reset_count
        for p in m.players:
            attach_skill(p)
        self.kinds = build(m, self.warnings)

    def decide(self, m, update):
        """One AI tick: the team plans (every AI_PERIOD ticks), then the bots that are due set their inputs."""
        brains = m.team_brains[0] + m.team_brains[1]
        if m.reset_count != self.resets:           # a kickoff reset since the last tick: fresh team plans
            self.resets = m.reset_count
            for b in brains:
                b.reset()
        if update:
            for b in brains:
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
