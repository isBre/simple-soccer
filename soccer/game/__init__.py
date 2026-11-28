"""The game around the core: a match between two teams with every seat's brain and the people at the controls.

  setup.py    MatchConfig / make_config (a match between two teams of data/teams) and the core MatchSetup it becomes
  seating.py  who sits in each seat: a rule-based player's archetype or a net player's NetBot
  humans.py   the people at the controls: who drives which seat, the Q switch and auto-switch of TEAM control
  play.py     new_match(cfg) / new_game(cfg): the match, ready to step"""
from .play import Game, new_game, new_match
from .setup import MatchConfig, make_config

__all__ = ["Game", "MatchConfig", "make_config", "new_game", "new_match"]
