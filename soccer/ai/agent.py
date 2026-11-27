"""What every agent (a rule-based player, a net, anything new) gives back each time it decides: its buttons and its call.

  agent.decide(view, me) -> Act      view: its team's public view (soccer/ai/view.py), me: its own body there

An agent decides alone: it never reads or writes another agent, teammates included. Its only way to talk is `intent`, one of
soccer.match.INTENTS, which its teammates (never the opponents) see on its body from the next tick (docs/public_view.md)."""


class Act:
    """dir: where to run (length <= 1), kick: hold the kick button, intent: the call to the teammates, kind: what a kick is meant
    as (pass / shoot / clear / long / "", only for the statistics)."""
    __slots__ = ("dir", "kick", "intent", "kind")

    def __init__(self, dir=0j, kick=False, intent="none", kind=""):
        self.dir, self.kick, self.intent, self.kind = dir, kick, intent, kind
