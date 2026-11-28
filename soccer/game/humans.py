"""People at the controls of a match: who plays which player, and the Q switch of TEAM control. Each person is a Person brain
(soccer/ai/person.py) in a seat; People moves it between seats (soccer.core.match: seat / switch), so the match itself only asks
it for its buttons every tick. Local multiplayer allows up to `size` people per side; a side with two or more plays SINGLE only
(check_humans)."""
import math

from ..ai.person import Person
from ..core.public import ENDED

NONE, SINGLE, TEAM = 0, 1, 2                  # MatchConfig.control: nobody, one player for the whole match, the whole team (Q)
SWITCH_WINDOW = 60      # ticks (1 s): a Q within this time of the previous one moves on to the next player of the same ranking


class Human:
    """One person at the controls: a side (`team`), a mode (SINGLE: one player for the whole match; TEAM: the whole team,
    switching with Q), the line-up slot asked for (SINGLE; -1 = auto), auto-switch (TEAM), the player controlled now, the
    buttons held, the Q ranking and every player this human has controlled (`played`, uids). A team with two or more humans
    plays SINGLE only, each human on a player of their own (check_humans)."""

    def __init__(self, team=0, mode=SINGLE, slot=-1, auto_switch=False):
        self.team, self.mode, self.slot, self.auto_switch = team, mode, slot, auto_switch
        self.person = Person()              # the brain in the seat this human drives: the buttons held now
        self.controlled = None
        self.switch_order, self.switch_idx, self.switch_last = [], 0, -10 ** 9
        self.played = []


def config_humans(cfg) -> list:
    """The Humans of a MatchConfig: cfg.humans, else the one human of control / human_team / human_slot / auto_switch."""
    if cfg.humans:
        return [Human(int(h.get("team", 0)), int(h.get("mode", SINGLE)), int(h.get("slot", -1)), bool(h.get("auto_switch", False)))
                for h in cfg.humans]
    if cfg.control != NONE:
        return [Human(cfg.human_team, cfg.control, cfg.human_slot, cfg.auto_switch)]
    return []


def check_humans(humans, size):
    """The rules of local multiplayer (ValueError if broken): a side is 0 or 1, a mode SINGLE or TEAM; at most `size` humans per
    side; a side with two or more humans plays SINGLE only (each on one player for the whole match, nobody switches) and the
    slots asked for there are different."""
    for t in (0, 1):
        mine = [h for h in humans if h.team == t]
        if len(mine) > size:
            raise ValueError("%d people on one side of a %dv%d match" % (len(mine), size, size))
        if len(mine) >= 2 and any(h.mode != SINGLE for h in mine):
            raise ValueError("two or more people on one side control one player each: nobody can control the whole team")
        slots = [h.slot for h in mine if h.slot >= 0]
        if len(slots) != len(set(slots)):
            raise ValueError("two people on one side asked for the same player")
    for h in humans:
        if h.team not in (0, 1) or h.mode not in (SINGLE, TEAM) or h.slot >= size:
            raise ValueError("bad human: side %r, mode %r, slot %r" % (h.team, h.mode, h.slot))


class People:
    """The humans of one match and the seat each one drives. `bots` are the seats' own brains: a seat a person leaves gets its
    bot back. TEAM-mode auto-switch runs as one of the match's tick hooks."""

    def __init__(self, humans, bots):
        self.humans = humans
        self.bots = bots
        self.m = None

    def seats(self, m):
        """Every human's first seat ({uid: Person}, in the humans' order: the first of a kickoff team takes the kickoff): SINGLE
        the slot asked for, else the most advanced formation spot still free; TEAM the player nearest the centre. Humans who
        asked for a slot choose first."""
        self.m = m
        taken = {}
        for h in sorted(self.humans, key=lambda h: h.slot < 0):
            lst = m.team_lists[h.team]
            free = [p for p in lst if p.uid not in taken]
            if not free:
                continue
            if h.mode == SINGLE:
                if 0 <= h.slot < len(lst) and lst[h.slot].uid not in taken:
                    best = lst[h.slot]
                else:
                    best = max(free, key=lambda p: (p.home.real, p.slot))
            else:
                best = min(free, key=lambda p: abs(p.pos))
            taken[best.uid] = h
        out = {}
        for h in self.humans:
            for uid, hh in taken.items():
                if hh is h:
                    out[uid] = h.person
                    h.controlled = m.by_uid[uid]
                    h.played.append(uid)
        if any(h.auto_switch and h.mode == TEAM for h in self.humans):
            m.tick_hooks.append(self._auto_switch_all)
        return out

    def human(self, h=0) -> Human:
        """A Human by number (0 = the first) or the Human itself."""
        return h if isinstance(h, Human) else self.humans[h]

    @property
    def controlled(self):
        """The first human's player (None without humans): the one-human view the recorder and older callers read."""
        return self.humans[0].controlled if self.humans else None

    def press(self, d: complex, kick: bool, h=0):
        """The buttons human `h` holds now (the match reads them on its next tick)."""
        if self.humans:
            self.human(h).person.press(d, kick)

    def set_controlled(self, p, h=0):
        """Hands player `p` to human `h` (not one another human drives); the seat it leaves gets its bot back."""
        h = self.human(h)
        if p is not None and p.is_human and p is not h.controlled:
            return
        m = self.m
        if h.controlled is not None:
            m.seat(h.controlled.uid, self.bots[h.controlled.uid])
        h.controlled = p
        if p is not None:
            m.seat(p.uid, h.person)
            if p.uid not in h.played:
                h.played.append(p.uid)

    def switch_controlled(self, now=None, h=0):
        """TEAM control mode, the Q key of human `h`. The first press takes the teammate nearest to the ball; another press within
        SWITCH_WINDOW of the previous one takes the next player of the same ranking (made at the first press, so it does not
        reshuffle while the players move): 2nd nearest, 3rd, ..., then back to the player you started from.
        `now` is the caller's clock in ticks (the web session counts real frames, so the window also runs during the kickoff
        intro and at fast-forward speeds); default the match tick. During the human's own kickoff wait the new player becomes
        the taker, and a kick held through the switch needs a fresh press (soccer.core.match: Match.switch)."""
        if not self.humans:
            return
        h = self.human(h)
        if h.mode != TEAM:
            return
        m = self.m
        now = m.tick if now is None else now
        order, idx = self._switch_plan(h, now, self._kickoff_wait(h))
        h.switch_order, h.switch_idx, h.switch_last = order, idx, now
        p = order[idx] if order else None
        if p is None or p is h.controlled:
            return
        if h.controlled is None:
            self.set_controlled(p, h)
            return
        m.switch(h.person, p.uid, self.bots[h.controlled.uid])
        h.controlled = p
        if p.uid not in h.played:
            h.played.append(p.uid)

    def next_switch(self, now=None, h=0):
        """The player a Q of human `h` at `now` would hand control to (None outside TEAM control or when it would change nothing):
        what the page marks with a dashed ring. Reads the same ranking as switch_controlled without changing it."""
        if not self.humans or self.m.state == ENDED:
            return None
        h = self.human(h)
        if h.mode != TEAM:
            return None
        order, idx = self._switch_plan(h, self.m.tick if now is None else now, self._kickoff_wait(h))
        p = order[idx] if order else None
        return p if p is not h.controlled else None

    def in_switch_window(self, now, h=0) -> bool:
        """A Q of human `h` at `now` would continue the current ranking (2nd nearest, 3rd, ...) instead of starting a new one."""
        if not self.humans:
            return False
        h = self.human(h)
        idx, order = h.switch_idx, h.switch_order
        return now - h.switch_last <= SWITCH_WINDOW and 0 <= idx < len(order) and order[idx] is h.controlled

    def _kickoff_wait(self, h) -> bool:
        return h.controlled is not None and self.m.awaits_kickoff(h.controlled.uid)

    def _switch_plan(self, h, now, own_kickoff):
        """(ranking, index of the player a Q at `now` takes): the current ranking moved one on inside SWITCH_WINDOW, else a
        new one (teammates nobody else drives, by distance to the ball, the controlled player at the end)."""
        m = self.m
        lst = [p for p in m.team_lists[h.team] if not p.is_human or p is h.controlled]
        order, idx = h.switch_order, h.switch_idx
        if not self.in_switch_window(now, h):
            others = sorted((p for p in lst if p is not h.controlled), key=lambda p: abs(p.pos - m.ball.pos))
            order = others + ([h.controlled] if h.controlled is not None else [])
            idx = -1
        if order:
            idx = (idx + 1) % len(order)
        return order, idx

    def _auto_switch_all(self, m):
        """Tick hook: every 20 ticks a TEAM-mode human with auto-switch moves to the teammate nearest the ball, when that one is
        clearly nearer (40 px) than the player driven now."""
        if m.tick % 20:
            return
        for h in self.humans:
            if h.auto_switch and h.mode == TEAM:
                self._auto_switch(h)

    def _auto_switch(self, h):
        m = self.m
        best, best_d = None, math.inf
        for p in m.team_lists[h.team]:
            if p.is_human and p is not h.controlled:
                continue
            d = abs(p.pos - m.ball.pos)
            if d < best_d:
                best_d, best = d, p
        if best is not None and best is not h.controlled and h.controlled is not None \
                and abs(h.controlled.pos - m.ball.pos) > best_d + 40.0:
            self.set_controlled(best, h)
