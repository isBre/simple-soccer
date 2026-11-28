"""A person at the controls as a brain: the buttons they hold now. The match asks a person every tick (`person = True`), and the
rules involving people apply to the seat it sits in (it takes its team's kickoff, it is never steered in a goal celebration).
Whoever reads the keyboard or the pad calls press(); soccer.game moves a person between seats in TEAM control."""
from ..core.act import Act


class Person:
    person = True

    def __init__(self):
        self.dir, self.kick = 0j, False

    def press(self, d: complex, kick: bool):
        self.dir, self.kick = d, kick

    def decide(self, view, me):
        return Act(self.dir, self.kick)
