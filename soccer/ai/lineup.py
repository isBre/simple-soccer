"""Who drives each player of a match. Every slot is driven by its own player (data/players): a rule-based StyleBot, an Opus
bot or a net. The rule-based players of a team share one TeamBrain and the Opus players one OpusBrain (one plan per team: who
chases, who marks whom, who guards the goal); a brain only commands the players it owns (`p.brain is brain`). Nets need no
brain.

MatchConfig.nets[t] overrides the line-up: one net drives every slot of that team (training, evaluation, the ladder). A net
that cannot play the match's size is replaced by the team's own players (see MatchAI.warnings)."""
from . import nets
from .opus import OpusBot, OpusBrain
from .rules import StyleBot, TeamBrain

_BRAIN = {"rules": TeamBrain, "opus": OpusBrain}
_BOT = {"rules": StyleBot, "opus": OpusBot}


def _load(spec, size, warnings, t):
    """A loaded net for this team size, or None (with a warning) when it cannot be loaded or does not fit."""
    try:
        net = nets.load(spec)
    except (OSError, ValueError, KeyError, ConnectionError) as e:
        warnings.append("team %d: cannot load net %s (%s); its own players instead" % (t, spec, e))
        return None
    if not nets.fits(net.n_in, size):
        warnings.append("team %d: a net with %d inputs does not fit %d players; its own players instead" % (t, net.n_in, size))
        return None
    return net


def build(m, warnings):
    """Sets p.bot_ai and p.brain for every player and m.brains (one main brain per team, the one other code asks for the
    team's plan, e.g. the opponents' keeper). Returns the kind of each team ({"kind": "net" | "rules" | "opus" | "mixed"})."""
    from ..data import database
    db = database()
    kinds, m.brains, m.team_brains = [], [], [[], []]
    for t in (0, 1):
        lst = m.team_lists[t]
        override = _load(m.cfg.nets[t], len(lst), warnings, t) if m.cfg.nets[t] else None
        loaded = {}
        brains = {}
        for p in lst:
            pd = p.pdef
            net = override
            if net is None and pd.kind == "net":
                if pd.model_path not in loaded:
                    loaded[pd.model_path] = _load({"model": pd.model_path}, len(lst), warnings, t)
                net = loaded[pd.model_path]
            if net is not None:
                p.bot_ai, p.brain = nets.NetBot(net, m.cfg.net_temperature), None
                continue
            kind = pd.kind if pd.kind in _BOT else "rules"     # a net player that cannot play: the balanced rule AI
            style = db.style_of_player(pd) if pd.kind in _BOT else db.styles["balanced"]
            if kind not in brains:
                brains[kind] = _BRAIN[kind](t, m.styles[t] if m.styles[t].brain == kind else style)
            p.bot_ai, p.brain = _BOT[kind](style), brains[kind]
        main = max(brains.values(), key=lambda b: (sum(1 for p in lst if p.brain is b), b.style is m.styles[t]), default=None)
        if main is None:
            main = TeamBrain(t, m.styles[t])          # a team of nets: an idle brain, so the opponents can still ask
        m.brains.append(main)
        for p in lst:
            if p.brain is None:
                p.brain = main
        ks = {("net" if isinstance(p.bot_ai, nets.NetBot) else "opus" if isinstance(p.bot_ai, OpusBot) else "rules") for p in lst}
        kinds.append({"kind": ks.pop() if len(ks) == 1 else "mixed",
                      **({"n_in": override.n_in} if override is not None else {})})
        m.team_brains[t] = list(brains.values()) or [main]
    return kinds
