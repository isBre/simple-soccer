"""A match between two teams of data/teams, as the game asks for it (MatchConfig: teams, size, clock, people at the controls,
nets that replace a line-up), and the core's MatchSetup it turns into."""
from ..core.match import MatchSetup
from ..data import database
from .humans import NONE


class MatchConfig:
    """Everything needed to set up one match."""

    def __init__(self):
        self.pitch = None
        self.teams = [None, None]           # teams.Team; [0] attacks right (left side), [1] attacks left
        self.team_size = 3
        self.duration = 180.0
        self.score_limit = 0
        self.allow_draw = True              # False: a draw goes to golden-goal overtime (no time limit, no shootout)
        self.match_seed = 1
        self.control = NONE
        self.human_team = 0
        self.auto_switch = False
        self.human_slot = -1                # SINGLE control: the line-up slot the human plays (-1 = auto: the most advanced spot)
        self.humans = []                    # local multiplayer: [{"team", "mode", "slot", "auto_switch"}], one per person; when empty,
                                            # control / human_team / human_slot / auto_switch describe the one human (or nobody)
        self.nets = [None, None]            # {"model": path} | {"dict": model} | None: one net for the whole team instead of its line-up
        self.net_temperature = 1.0


def make_config(team_a, team_b, pitch_id="arena", size=5, duration=180.0, seed=1, db=None) -> MatchConfig:
    """A match between two teams of data/teams."""
    db = db or database()
    c = MatchConfig()
    c.pitch = db.pitches.get(pitch_id) or next(iter(db.pitches.values()))
    c.teams = [db.teams[team_a], db.teams[team_b]]
    c.team_size = size
    c.duration = duration
    c.match_seed = seed
    return c


def match_setup(cfg: MatchConfig) -> MatchSetup:
    """The core's view of a config: the pitch, each team's line-up (its players as the slot labels), the clock and the rules."""
    return MatchSetup(cfg.pitch, [cfg.teams[t].lineup(cfg.team_size) for t in (0, 1)], [cfg.teams[0].id, cfg.teams[1].id],
                      cfg.duration, cfg.score_limit, cfg.allow_draw, cfg.match_seed)
