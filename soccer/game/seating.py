"""Who sits in each seat: every slot is played by its own player (data/players), alone. A rule-based player gets its
archetype's brain (soccer/ai/players: its own algorithm, settings and skill), a net player a NetBot. Nobody commands anybody:
players talk only through their calls (intents, docs/public_view.md).

MatchConfig.nets[t] overrides the line-up: one net plays every slot of that team (training, evaluation, the ladder). A net
that cannot play the match's size is replaced by the team's own players; a net player that cannot play it by a box-to-box
rule-based player of the same skill (both reported in `warnings`)."""
from ..ai import nets, obs, players


def _load(spec, size, warnings, t):
    """A loaded net for this team size, or None (with a warning) when it cannot be loaded or does not fit."""
    try:
        net = nets.load(spec)
    except (OSError, ValueError, KeyError, ConnectionError) as e:
        warnings.append("team %d: cannot load net %s (%s); its own players instead" % (t, spec, e))
        return None
    if not obs.fits(net.n_in, size):
        warnings.append("team %d: a net with %d inputs does not fit %d players; its own players instead" % (t, net.n_in, size))
        return None
    return net


def bots(m, cfg, warnings):
    """The bot brain of every seat of match m ({uid: brain}, seeded with the seat's brain_seed) and the kind of each team
    ([{"kind": "net" | "rules" | "mixed", "n_in"?}, ...])."""
    seats, kinds = {}, []
    for t in (0, 1):
        lst = m.team_lists[t]
        override = _load(cfg.nets[t], len(lst), warnings, t) if cfg.nets[t] else None
        loaded = {}
        for p in lst:
            pd = p.label
            net = override
            if net is None and pd.kind == "net":
                if pd.model_path not in loaded:
                    loaded[pd.model_path] = _load({"model": pd.model_path}, len(lst), warnings, t)
                net = loaded[pd.model_path]
            if net is not None:
                seats[p.uid] = nets.NetBot(net, cfg.net_temperature, p.brain_seed)
            elif pd.kind == "rules":
                seats[p.uid] = players.make(pd, p.brain_seed)
            else:
                warnings.append("team %d: %s cannot play here; a box-to-box rule-based player instead" % (t, pd.name))
                seats[p.uid] = players.ALGORITHMS["box_to_box"](None, pd.skill, p.brain_seed)
        ks = {"net" if isinstance(seats[p.uid], nets.NetBot) else "rules" for p in lst}
        kinds.append({"kind": ks.pop() if len(ks) == 1 else "mixed", **({"n_in": override.n_in} if override is not None else {})})
    return seats, kinds
