"""Teams (data/teams/*.json): an identity (name, colours, kit, logo) and a line-up of players (soccer/players.py). A team has
no tactic: every player plays the same in any team (the brain that coordinates a team's rule-based players takes its settings
from those players, data.Style.blend).

  lineup     five player ids in order of preference; a match of size N fields the first N who can play that size (the same
             player may appear several times: a team of five copies of one player is the usual case)

Every team takes the same kickoff spots for a size (data/formations.json "defaults"). Labels there (GK, DEF, MID, FWD) name a
spot's line for the rule-based AI; the match itself never reads them, and any player can stand on any spot."""
from .data import default_formation, formation_slots


class Team:
    def __init__(self, d):
        self.raw = d
        self.id = str(d.get("id", ""))
        self.name = str(d.get("name", self.id))
        self.short = str(d.get("short", self.name[:3].upper()))
        self.lineup_ids = [str(x) for x in d.get("lineup", [])]
        self.league = str(d.get("league", "rules"))
        # part of the RL evaluation league (rl/evaluate.py: the 16 original rule teams); teams added later set "rl_eval": false
        # so the RL protocol and every earlier evaluation stay comparable
        self.rl_eval = bool(d.get("rl_eval", False))
        self.players = []                     # PlayerDef per lineup entry (Database fills it)
        self.custom = False                   # built in the game (local/my_teams, this machine only)

    def eligible(self, size):
        """The players of the line-up who can play this size, in line-up order."""
        return [p for p in self.players if p.can_play(size)]

    def can_play(self, size):
        return bool(self.eligible(size))

    def lineup(self, size):
        """[(PlayerDef, line, fx, fy)] for a match of this size: the size's kickoff spots filled with the first eligible players
        of the line-up (repeated from the top if fewer than `size` can play)."""
        pool = self.eligible(size)
        if not pool:
            raise ValueError("team %s has nobody who can play %dv%d" % (self.id, size, size))
        spots = formation_slots(default_formation(size))
        return [(pool[i % len(pool)], line, float(fx), float(fy)) for i, (line, fx, fy) in enumerate(spots)]

    def kinds(self):
        return sorted({p.kind for p in self.players})

    @property
    def net_player(self):
        """The net player when every slot of the line-up is the same net, else None (such a team is "that net")."""
        ids = {p.id for p in self.players}
        if len(ids) == 1 and self.players and self.players[0].kind == "net":
            return self.players[0]
        return None

    @property
    def ml_model(self):
        """Model path of a team that is one net in every slot ("" otherwise): the ladder and the training tools treat such a
        team as that net."""
        p = self.net_player
        return p.model if p is not None else ""

    def strength(self):
        """Average skill of the line-up's first five (rule-based tiers in rl/evaluate.py)."""
        sk = [p.skill for p in self.players[:5]]
        return sum(sk) / len(sk) if sk else 0.0
