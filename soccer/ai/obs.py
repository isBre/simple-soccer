"""What a net player sees: its observation, a list of numbers computed from its team's public view (soccer/core/view.py,
docs/public_view.md) and nothing else. Every function takes the view as `m` and the player's own body as `p`. Training
(rl/env.py), the game recorder and every match build it from a View, so a net sees in play exactly what it saw in training
(tests/test_view.py also checks that the Match itself would give the same numbers).

Layouts (a net file says "obs": "slots76"; older files are recognised by their input size, features_for / LAYOUTS):
  slots76   every team size, with the teammates' calls (features_slots)
  team46    5v5, role-free: teammates and opponents nearest first (features_team)
  rank56    team46 + each player's rank by distance to the ball and by depth (features_rank)
  ego       8n + 14 numbers (54 at 5v5): slot order, the ball and the goal relative to me, my slot (features_ego; the oldest nets)"""
from ..core.public import INTENTS

TEAM_OBS = 46                     # role-free team observation (features_team)
RANK_OBS = 56                     # features_team + 10 rank numbers (features_rank)
SLOTS_OBS = 76                    # every size, with the teammates' calls (features_slots); the net file says "obs": "slots76"
SLOTS_NAME = "slots76"


# ---------------------------------------------------------------- observations

def _push(out, pos: complex, vel: complex, s: float, pd):
    out += (pos.real * s / pd.out_x, pos.imag / pd.out_y, vel.real * s / 5.0, vel.imag / 5.0)


def features_team(m, p):
    """Role-free observation (46 numbers, no player ID): the same picture for every player, from its own point of view (the
    pitch is mirrored so the team always attacks to the right). Me, my 4 teammates NEAREST FIRST, the 5 opponents NEAREST
    FIRST (position and speed each, scaled by the pitch and by 5), the ball (position and speed), kickoff on (0/1), goal
    celebration on (0/1). Sorting by distance instead of by slot keeps a player from knowing which "role" it has."""
    s = m.attack_dir(p.team)
    pd = m.pitch
    out = []
    _push(out, p.pos, p.vel, s, pd)
    key = lambda o: (abs(o.pos - p.pos) ** 2, o.uid)
    for group in ([o for o in m.team_lists[p.team] if o is not p], list(m.team_lists[1 - p.team])):
        group.sort(key=key)
        for o in group:
            _push(out, o.pos, o.vel, s, pd)
    _push(out, m.ball_pos, m.ball_vel, s, pd)
    out.append(1.0 if m.kickoff_active else 0.0)
    out.append(1.0 if m.state == 1 else 0.0)
    return out


def features_slots(m, p, present=None):
    """The observation of every team size (76 numbers, SLOTS_NAME), from the public view (or the match itself, in training).
    The pitch is mirrored so the team attacks to the right; positions are scaled by the pitch, speeds by 5.
      me                    position and speed                                                    4
      4 teammate slots      nearest first: position and speed, on the pitch (1), its call (5, INTENTS order)    4 x 10
      5 opponent slots      nearest first: position and speed, on the pitch (1)                    5 x 5
      ball                  position and speed                                                    4
      flags                 kickoff on, our kickoff, goal celebration                             3
    A slot nobody fills (a smaller size, a player removed in training) is zeros with "on the pitch" 0, so one net plays every
    size. `present`: the uids of the players on the pitch (training removes some); default all of m.players."""
    s = m.attack_dir(p.team)
    pd = m.pitch
    on = present if present is not None else {o.uid for o in m.players}
    out = []
    _push(out, p.pos, p.vel, s, pd)
    key = lambda o: (abs(o.pos - p.pos) ** 2, o.uid)
    mates = sorted((o for o in m.team_lists[p.team] if o is not p and o.uid in on), key=key)[:4]
    for o in mates:
        _push(out, o.pos, o.vel, s, pd)
        out.append(1.0)
        out += [1.0 if o.intent == c else 0.0 for c in INTENTS]
    out += [0.0] * (10 * (4 - len(mates)))
    opps = sorted((o for o in m.team_lists[1 - p.team] if o.uid in on), key=key)[:5]
    for o in opps:
        _push(out, o.pos, o.vel, s, pd)
        out.append(1.0)
    out += [0.0] * (5 * (5 - len(opps)))
    _push(out, m.ball_pos, m.ball_vel, s, pd)
    out.append(1.0 if m.kickoff_active else 0.0)
    out.append(1.0 if m.kickoff_active and m.kickoff_team == p.team else 0.0)
    out.append(1.0 if m.state == 1 else 0.0)
    return out


def ranks(m, p):
    """10 role-free derived numbers (user OK, 2026-11-21): for me and my 4 teammates in the order of features_team (nearest
    first), the player's rank in our team by distance to the ball (0 = nearest) and by depth (0 = deepest, nearest our own
    goal), each divided by (team size - 1). They fix no role: a rank changes with the situation, and two players swap ranks as
    they move. The same information is in the 46 positions, but a small net cannot sort 5 points easily."""
    s = m.attack_dir(p.team)
    team = m.team_lists[p.team]
    n = max(len(team) - 1, 1)
    key = lambda o: (abs(o.pos - p.pos) ** 2, o.uid)
    order = [p] + sorted([o for o in team if o is not p], key=key)
    by_ball = {o.uid: i for i, o in enumerate(sorted(team, key=lambda o: (abs(o.pos - m.ball_pos) ** 2, o.uid)))}
    by_depth = {o.uid: i for i, o in enumerate(sorted(team, key=lambda o: (o.pos.real * s, o.uid)))}
    out = []
    for o in order:
        out += (by_ball[o.uid] / n, by_depth[o.uid] / n)
    return out


def features_rank(m, p):
    """features_team followed by ranks (56 numbers for 5 players)."""
    return features_team(m, p) + ranks(m, p)


def features_ego(m, p):
    """Older ego observation (8n + 14 numbers: 54 at 5v5): me, ball, teammates and opponents in slot order, then the ball
    relative to me (fine scale, so the kick range is learnable), the opponent goal relative to me and the one-hot of my slot."""
    s = m.attack_dir(p.team)
    pd = m.pitch
    out = []
    _push(out, p.pos, p.vel, s, pd)
    _push(out, m.ball_pos, m.ball_vel, s, pd)
    for o in m.team_lists[p.team]:
        if o is not p:
            _push(out, o.pos, o.vel, s, pd)
    for o in m.team_lists[1 - p.team]:
        _push(out, o.pos, o.vel, s, pd)
    rel = m.ball_pos - p.pos
    out.append(min(max(rel.real * s / 40.0, -6.0), 6.0))
    out.append(min(max(rel.imag / 40.0, -6.0), 6.0))
    out.append(min(abs(rel) / 40.0, 6.0))
    out.append((s * pd.half_w - p.pos.real) * s / 400.0)
    out.append((0.0 - p.pos.imag) / 400.0)
    out += [1.0 if p.slot == k else 0.0 for k in range(5)]      # one-hot of the player's slot: lets roles emerge
    return out


def features_for(m, p, n_in):
    """The observation a net of this input size expects (LAYOUTS; any other size: the ego layout of its team size)."""
    return LAYOUTS.get(n_in, features_ego)(m, p)


class _Frame:
    """What every observation of one tick shares, computed once: each player's 4 scaled numbers from both teams' points of
    view, the squared distance of every pair, and each team's ranks by distance to the ball and by depth. features_many builds
    from it exactly the lists features_team / features_rank / features_ego return (same values, same order)."""

    def __init__(self, m):
        pd = m.pitch
        ox, oy = pd.out_x, pd.out_y
        self.m = m
        self.teams = m.team_lists
        players = [o for t in self.teams for o in t]
        self.push = {}                                 # (uid, s) -> 4 numbers
        for o in players + [m.ball]:
            pos, vel = o.pos, o.vel
            y, vy = pos.imag / oy, vel.imag / 5.0
            key = id(o) if o is m.ball else o.uid
            self.push[key, 1.0] = (pos.real * 1.0 / ox, y, vel.real * 1.0 / 5.0, vy)
            self.push[key, -1.0] = (pos.real * -1.0 / ox, y, vel.real * -1.0 / 5.0, vy)
        self.ball_key = id(m.ball)
        self.d2 = {}                                   # (uid_a, uid_b) -> abs(a.pos - b.pos) ** 2 (symmetric)
        for i, a in enumerate(players):
            for b in players[i + 1:]:
                d = abs(a.pos - b.pos) ** 2
                self.d2[a.uid, b.uid] = self.d2[b.uid, a.uid] = d
        self.flags = (1.0 if m.kickoff_active else 0.0, 1.0 if m.state == 1 else 0.0)
        self._ranks = {}

    def team_ranks(self, team):
        r = self._ranks.get(team)
        if r is None:
            m, lst = self.m, self.teams[team]
            s = m.attack_dir(team)
            bp = m.ball_pos
            by_ball = {o.uid: i for i, o in enumerate(sorted(lst, key=lambda o: (abs(o.pos - bp) ** 2, o.uid)))}
            by_depth = {o.uid: i for i, o in enumerate(sorted(lst, key=lambda o: (o.pos.real * s, o.uid)))}
            r = self._ranks[team] = (by_ball, by_depth, max(len(lst) - 1, 1))
        return r


def features_many(m, players, team=True, rank=False, legacy=False, frame=None):
    """The observations of several players of the same tick, concatenated: per player features_team (team), then ranks (rank,
    after the team observation), then the legacy ego features with the slot one-hot (legacy). Identical to calling those."""
    f = frame or _Frame(m)
    push, d2 = f.push, f.d2
    out = []
    for p in players:
        s = m.attack_dir(p.team)
        if team:
            uid = p.uid
            out += push[uid, s]
            mates = [o for o in f.teams[p.team] if o is not p]
            mates.sort(key=lambda o: (d2[uid, o.uid], o.uid))
            for o in mates:
                out += push[o.uid, s]
            opps = list(f.teams[1 - p.team])
            opps.sort(key=lambda o: (d2[uid, o.uid], o.uid))
            for o in opps:
                out += push[o.uid, s]
            out += push[f.ball_key, s]
            out += f.flags
            if rank:
                by_ball, by_depth, n = f.team_ranks(p.team)
                out += (by_ball[uid] / n, by_depth[uid] / n)
                for o in mates:
                    out += (by_ball[o.uid] / n, by_depth[o.uid] / n)
        if legacy:
            out += push[p.uid, s]
            out += push[f.ball_key, s]
            for o in f.teams[p.team]:
                if o is not p:
                    out += push[o.uid, s]
            for o in f.teams[1 - p.team]:
                out += push[o.uid, s]
            pd = m.pitch
            rel = m.ball_pos - p.pos
            out.append(min(max(rel.real * s / 40.0, -6.0), 6.0))
            out.append(min(max(rel.imag / 40.0, -6.0), 6.0))
            out.append(min(abs(rel) / 40.0, 6.0))
            out.append((s * pd.half_w - p.pos.real) * s / 400.0)
            out.append((0.0 - p.pos.imag) / 400.0)
            out += [1.0 if p.slot == k else 0.0 for k in range(5)]
    return out


def features_group(m, players, n_in):
    """features_for for several players of the same tick: one list per player."""
    if n_in == SLOTS_OBS:
        on = {o.uid for o in m.players}
        return [features_slots(m, p, on) for p in players]
    if n_in in (TEAM_OBS, RANK_OBS):
        f = _Frame(m)
        return [features_many(m, [p], True, n_in == RANK_OBS, False, f) for p in players]
    return [features_ego(m, p) for p in players]


def fits(n_in, team_size):
    """A net can play this team size: the slots observation (76) and the ego layout (8n+14) at any size; the team (46) and
    rank (56) observations exist only for 5v5 (features_for picks them by input size, so a 46-input net is never read as the
    ego layout of 4v4)."""
    if n_in == SLOTS_OBS:
        return 1 <= team_size <= 5
    if n_in in (TEAM_OBS, RANK_OBS):
        return team_size == 5
    return n_in == 8 * team_size + 14


# the layouts a net's input size selects (features_for; any other size is the ego layout of its team size)
LAYOUTS = {SLOTS_OBS: features_slots, TEAM_OBS: features_team, RANK_OBS: features_rank}
