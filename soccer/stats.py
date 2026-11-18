"""Per-player match counters (PlayerMatchStats) and the match totals (MatchStats). Grades come from rating.py."""
import math


def snapped(x: float, step: float) -> float:
    """Godot's snappedf: floor(x / step + 0.5) * step."""
    return math.floor(x / step + 0.5) * step


FIELDS_INT = ("touches", "passes_ok", "passes_failed", "passes_received", "progressive_passes", "key_passes", "shots",
              "shots_on_target", "goals", "assists", "own_goals", "big_chances", "big_scored", "tackles", "interceptions",
              "recoveries", "clearances", "blocks", "saves", "dribbles", "dispossessed", "conceded", "scored_for", "keeper_ticks")
FIELDS_FLOAT = ("pass_value", "xg", "xa", "save_xg", "conceded_xg", "carry_dist", "distance", "rating")


class PlayerMatchStats:
    __slots__ = FIELDS_INT + FIELDS_FLOAT

    def __init__(self):
        for k in FIELDS_INT:
            setattr(self, k, 0)
        for k in FIELDS_FLOAT:
            setattr(self, k, 0.0)
        self.rating = 6.0

    def passes(self):
        return self.passes_ok + self.passes_failed

    def pass_accuracy(self):
        n = self.passes()
        return 1.0 if n == 0 else self.passes_ok / n

    def defensive_actions(self):
        """tackles + interceptions + loose ball recoveries (one number for compact tables)"""
        return self.tackles + self.interceptions + self.recoveries

    def to_dict(self):
        return {"touches": self.touches, "passes_ok": self.passes_ok, "passes_failed": self.passes_failed,
                "passes_received": self.passes_received, "progressive_passes": self.progressive_passes,
                "key_passes": self.key_passes, "shots": self.shots, "shots_on_target": self.shots_on_target,
                "goals": self.goals, "assists": self.assists, "own_goals": self.own_goals,
                "xg": snapped(self.xg, 0.01), "xa": snapped(self.xa, 0.01), "big_chances": self.big_chances,
                "big_scored": self.big_scored, "tackles": self.tackles, "interceptions": self.interceptions,
                "recoveries": self.recoveries, "clearances": self.clearances, "blocks": self.blocks, "saves": self.saves,
                "save_xg": snapped(self.save_xg, 0.01), "conceded_xg": snapped(self.conceded_xg, 0.01),
                "dribbles": self.dribbles, "dispossessed": self.dispossessed, "conceded": self.conceded,
                "keeper_ticks": self.keeper_ticks, "distance": snapped(self.distance / 10.0, 0.1),
                "def_actions": self.defensive_actions(), "rating": self.rating}

    def state(self):
        return {k: getattr(self, k) for k in FIELDS_INT + FIELDS_FLOAT}

    def load(self, d):
        for k in FIELDS_INT:
            setattr(self, k, int(d[k]))
        for k in FIELDS_FLOAT:
            setattr(self, k, float(d[k]))


class MatchStats:
    def __init__(self):
        self.by_uid = {}
        self.possession_ticks = [0, 0]

    def get_player(self, uid):
        if uid not in self.by_uid:
            self.by_uid[uid] = PlayerMatchStats()
        return self.by_uid[uid]
