"""Who drives each player of a match: every slot is driven by its own player (data/players), alone. A rule-based player gets its
archetype's agent (soccer/ai/players: its own algorithm, settings and skill), a net player a NetBot. Nobody commands anybody:
players talk only through their calls (intents, docs/public_view.md).

MatchConfig.nets[t] overrides the line-up: one net drives every slot of that team (training, evaluation, the ladder). A net
that cannot play the match's size is replaced by the team's own players; a net player that cannot play it by a box-to-box
rule-based player of the same skill (see MatchAI.warnings)."""
from . import nets, players


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
    """Sets p.bot_ai for every player. Returns the kind of each team ({"kind": "net" | "rules" | "mixed"})."""
    kinds = []
    for t in (0, 1):
        lst = m.team_lists[t]
        override = _load(m.cfg.nets[t], len(lst), warnings, t) if m.cfg.nets[t] else None
        loaded = {}
        for p in lst:
            pd = p.pdef
            net = override
            if net is None and pd.kind == "net":
                if pd.model_path not in loaded:
                    loaded[pd.model_path] = _load({"model": pd.model_path}, len(lst), warnings, t)
                net = loaded[pd.model_path]
            if net is not None:
                p.bot_ai = nets.NetBot(net, m.cfg.net_temperature, p.ai_seed)
            elif pd.kind == "rules":
                p.bot_ai = players.make(pd, p.ai_seed)
            else:
                warnings.append("team %d: %s cannot play here; a box-to-box rule-based player instead" % (t, pd.name))
                p.bot_ai = players.ALGORITHMS["box_to_box"](None, pd.skill, p.ai_seed)
        ks = {"net" if isinstance(p.bot_ai, nets.NetBot) else "rules" for p in lst}
        kinds.append({"kind": ks.pop() if len(ks) == 1 else "mixed", **({"n_in": override.n_in} if override is not None else {})})
    return kinds
