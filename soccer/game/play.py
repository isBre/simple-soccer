"""A match as the game plays it: the core match (soccer.core.match) with every seat's brain and the people at the controls.

  new_match(cfg)   the core Match, ready to step (bots and nets seated; people too, if the config has any)
  new_game(cfg)    the same match with what the game also needs: the people (TEAM-mode Q switch, buttons), the warnings and the
                   kind of each team"""
from ..core.match import Match
from .humans import People, check_humans, config_humans
from .seating import bots
from .setup import MatchConfig, match_setup


class Game:
    """A match plus the game around it: `people` (soccer.game.humans.People), `warnings` (what could not be seated as asked) and
    `kinds` (what plays each team)."""

    def __init__(self, cfg: MatchConfig):
        self.cfg = cfg
        self.warnings, self.kinds = [], []
        humans = config_humans(cfg)
        check_humans(humans, cfg.team_size)
        self.people = None

        def seating(m):
            seats, self.kinds = bots(m, cfg, self.warnings)
            self.people = People(humans, seats)
            seats = dict(seats)
            for uid, person in self.people.seats(m).items():
                del seats[uid]                       # the people take their seats last, in their own order
                seats[uid] = person
            return seats

        self.match = Match(match_setup(cfg), seating)


def new_game(cfg: MatchConfig) -> Game:
    return Game(cfg)


def new_match(cfg: MatchConfig) -> Match:
    return Game(cfg).match
