"""The AI of a match: rule-based players (rules.py: TeamBrain + StyleBot) and neural nets (nets.py), one per slot as the
team's line-up says (lineup.py). Every bot and brain decides from its team's public view (view.py, docs/public_view.md): the
ball and anonymous bodies, their recent history, the clock, the score and the kickoff, never the match engine or the other
team's inside. MatchAI is what soccer.match.Match calls on every AI tick: it refreshes the two views, lets the brains plan and
the due bots decide, and hands only each team's buttons back to the match."""
from . import nets
from .lineup import build
from .view import View


class MatchAI:
    """The team brains and one bot per player (lineup.build). Anything that could not be set up as asked (a net that cannot
    be loaded or does not fit the size) is in `warnings`; `kinds` says what drives each team."""

    def __init__(self, m):
        self.warnings = []
        self.resets = m.reset_count
        self.kinds = build(m, self.warnings)
        self.views = [View(m, 0), View(m, 1)]

    def decide(self, m, update):
        """One AI tick: the team plans (every AI_PERIOD ticks), then the bots that are due set their inputs."""
        views = [v.refresh(m) for v in self.views]
        if m.reset_count != self.resets:           # a kickoff reset since the last tick: fresh team plans
            self.resets = m.reset_count
            for t in (0, 1):
                for b in m.team_brains[t]:
                    b.reset()
        if update:
            for t in (0, 1):
                for b in m.team_brains[t]:
                    b.update(views[t])
        by_net = {}
        for t in (0, 1):
            v = views[t]
            for p in m.team_lists[t]:
                if not p.bot or p.is_human or (m.tick + p.slot) % 2 != 0:
                    continue
                if isinstance(p.bot_ai, nets.NetBot):
                    by_net.setdefault(id(p.bot_ai.net), []).append(p)
                else:
                    body = v.bodies[p.uid]
                    p.bot_ai.decide(v, body)
                    p.input_dir, p.input_kick, p.kick_intent = body.input_dir, body.input_kick, body.kick_intent
        for group in by_net.values():              # one forward pass per net for all its players of this tick (both teams)
            net = group[0].bot_ai.net
            group.sort(key=lambda p: p.team)        # team 0 first, as the match lists them: the same batch as before
            feats = []
            for t in (0, 1):
                mine = [views[t].bodies[p.uid] for p in group if p.team == t]
                if mine:
                    feats += nets.features_group(views[t], mine, net.n_in)
            out = net.forward(feats)
            for p, o in zip(group, out):
                body = views[p.team].bodies[p.uid]
                p.bot_ai.act(views[p.team], body, o)
                p.input_dir, p.input_kick, p.kick_intent = body.input_dir, body.input_kick, body.kick_intent
