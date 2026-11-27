"""The AI of a match: every player decides alone. A rule-based player is an archetype with its own algorithm
(soccer/ai/players/, on the shared toolkit kit.py), a net player a NetBot (nets.py); lineup.py says who drives each slot. Every
agent decides from its team's public view (view.py, docs/public_view.md): the ball and anonymous bodies, their recent history,
the clock, the score, the kickoff and its teammates' calls, never the match engine or another agent's inside. Its answer is an
Act (agent.py): its buttons and its call. MatchAI is what soccer.match.Match calls on every AI tick: it refreshes the two views,
lets the due agents decide and hands each one's buttons and call back to the match."""
from . import nets
from .lineup import build
from .view import View


class MatchAI:
    """One agent per player (lineup.build). Anything that could not be set up as asked (a net that cannot be loaded or does not
    fit the size) is in `warnings`; `kinds` says what drives each team."""

    def __init__(self, m):
        self.warnings = []
        self.kinds = build(m, self.warnings)
        self.views = [View(m, 0), View(m, 1)]

    def decide(self, m, update):
        """One AI tick: the agents that are due decide (each player every AI_PERIOD ticks, staggered by slot). Everyone reads
        the views as they were at the start of the tick, so nobody hears a call made in the same tick."""
        views = [v.refresh(m) for v in self.views]
        by_net = {}
        for t in (0, 1):
            v = views[t]
            for p in m.team_lists[t]:
                if not p.bot or p.is_human or (m.tick + p.slot) % 2 != 0:
                    continue
                if isinstance(p.bot_ai, nets.NetBot):
                    by_net.setdefault(id(p.bot_ai.net), []).append(p)
                else:
                    self._apply(m, p, p.bot_ai.decide(v, v.bodies[p.uid]))
        for group in by_net.values():              # one forward pass per net for all its players of this tick (both teams)
            net = group[0].bot_ai.net
            group.sort(key=lambda p: p.team)
            feats = []
            for t in (0, 1):
                mine = [views[t].bodies[p.uid] for p in group if p.team == t]
                if mine:
                    feats += nets.features_group(views[t], mine, net.n_in)
            out = net.forward(feats)
            for p, o in zip(group, out):
                self._apply(m, p, p.bot_ai.act(views[p.team], views[p.team].bodies[p.uid], o))

    @staticmethod
    def _apply(m, p, act):
        p.input_dir, p.input_kick, p.kick_intent = act.dir, act.kick, act.kind
        m.set_intent(p, act.intent)
