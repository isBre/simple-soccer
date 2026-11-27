"""The rule-based players: one archetype per file, each with its own algorithm on top of the shared base (base.py: senses,
kickoff, whose ball, guarding, striking) and toolkit (soccer/ai/kit.py). A player of data/players names its archetype
("algorithm"), its own settings and its skill; make() builds its agent.

  poacher      lives on the last defender's shoulder, shoots first        winger       runs down a touchline and crosses low
  playmaker    drops deep, through balls to runners                       target man   holds the ball up front, lays off, turns
  dribbler     carries the ball past defenders                            presser      presses the carrier or the next receiver
  ball winner  hunts the carrier, lays off at once                        box-to-box   late runs into the box, sprints back
  sweeper      the last man: guards the goal, sweeps, clears long         shadow       marks the most dangerous opponent goal-side"""
from .ball_winner import BallWinner
from .box_to_box import BoxToBox
from .dribbler import Dribbler
from .playmaker import Playmaker
from .poacher import Poacher
from .presser import Presser
from .shadow import Shadow
from .sweeper import Sweeper
from .target_man import TargetMan
from .winger import Winger

ALGORITHMS = {"poacher": Poacher, "playmaker": Playmaker, "dribbler": Dribbler, "ball_winner": BallWinner, "sweeper": Sweeper,
              "winger": Winger, "target_man": TargetMan, "presser": Presser, "box_to_box": BoxToBox, "shadow": Shadow}


def make(pdef, seed):
    """The agent of a rule-based player (data/players: "algorithm", "settings", "skill")."""
    return ALGORITHMS[pdef.algorithm](pdef.settings, pdef.skill, seed)


def describe():
    """[{id, name, description, settings: {key: label}}] of every archetype (the game's player pages)."""
    return [{"id": k, "name": c.NAME, "description": c.DESCRIPTION, "settings": {s: lbl for s, (_, lbl) in c.SETTINGS.items()}}
            for k, c in ALGORITHMS.items()]
