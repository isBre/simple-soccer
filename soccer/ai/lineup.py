"""Who drives each player of a match. Every slot is driven by its own player (data/players): a rule-based StyleBot (its own
style and skill) or a net. The rule-based players of a team share one TeamBrain (one plan per team: who chases, who marks
whom, who guards the goal); a brain only commands the players it owns (`p.brain is brain`) and takes its settings from them
(data.Style.blend: a team has no tactic). Nets need no brain. Every bot and brain decides from its team's public view only
(soccer/ai/view.py); its own skill is in the bot (soccer/ai/skill.py).

Opus (soccer/ai/opus.py) is parked: it planned on a clone of the whole match, which the public view does not allow, and comes
back once it plans from the view (docs/public_view.md).

MatchConfig.nets[t] overrides the line-up: one net drives every slot of that team (training, evaluation, the ladder). A net
that cannot play the match's size is replaced by the team's own players (see MatchAI.warnings)."""
from . import nets
from .rules import StyleBot, TeamBrain
from .skill import attach_skill


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
    """Sets p.bot_ai and p.brain for every player and m.brains (one main brain per team, the idle one for a team of nets) and
    m.team_brains (every brain of each team). Returns the kind of each team ({"kind": "net" | "rules" | "mixed"})."""
    from ..data import Style, database
    db = database()
    kinds, m.brains, m.team_brains = [], [], [[], []]
    for t in (0, 1):
        lst = m.team_lists[t]
        override = _load(m.cfg.nets[t], len(lst), warnings, t) if m.cfg.nets[t] else None
        loaded = {}
        members = []                                    # (player, its style) of the rule-based players
        for p in lst:
            pd = p.pdef
            net = override
            if net is None and pd.kind == "net":
                if pd.model_path not in loaded:
                    loaded[pd.model_path] = _load({"model": pd.model_path}, len(lst), warnings, t)
                net = loaded[pd.model_path]
            if net is not None:
                p.bot_ai, p.brain = nets.NetBot(net, m.cfg.net_temperature, p.ai_seed), None
                continue
            if pd.kind == "rules":
                style = db.style_of_player(pd)
            else:                                       # a net that cannot play this size, or a parked kind: balanced rules
                warnings.append("team %d: %s cannot play here; the balanced rule-based AI instead" % (t, pd.name))
                style = db.styles["balanced"]
            p.bot_ai = attach_skill(StyleBot(style), pd.skill, p.ai_seed)
            members.append((p, style))
        brains = []
        if members:                                     # one brain, with the settings of the players it commands
            b = TeamBrain(t, Style.blend(s for _, s in members))
            for p, _ in members:
                p.brain = b
            brains.append(b)
        main = brains[0] if brains else TeamBrain(t, db.styles["balanced"])   # a team of nets: an idle brain
        m.brains.append(main)
        for p in lst:
            if p.brain is None:
                p.brain = main
        ks = {"net" if isinstance(p.bot_ai, nets.NetBot) else "rules" for p in lst}
        kinds.append({"kind": ks.pop() if len(ks) == 1 else "mixed",
                      **({"n_in": override.n_in} if override is not None else {})})
        m.team_brains[t] = brains or [main]
    return kinds
