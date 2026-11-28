"""People at the controls of a match: who plays which player, and the Q switch of TEAM control. Local multiplayer allows up to
`size` people per side; a side with two or more plays SINGLE only (check_humans). soccer.match.Match takes the switching
logic from HumanControl; the match itself only copies each human's buttons onto the player it controls, every tick."""
import math

NONE, SINGLE, TEAM = 0, 1, 2                  # MatchConfig.control: nobody, one player for the whole match, the whole team (Q)
SWITCH_WINDOW = 60      # ticks (1 s): a Q within this time of the previous one moves on to the next player of the same ranking


class Human:
    """One person at the controls: a side (`team`), a mode (SINGLE: one player for the whole match; TEAM: the whole team,
    switching with Q), the line-up slot asked for (SINGLE; -1 = auto), auto-switch (TEAM), the player controlled now, the
    buttons held, the Q ranking and every player this human has controlled (`played`, uids). A team with two or more humans
    plays SINGLE only, each human on a player of their own (check_humans)."""

    def __init__(self, team=0, mode=SINGLE, slot=-1, auto_switch=False):
        self.team, self.mode, self.slot, self.auto_switch = team, mode, slot, auto_switch
        self.controlled = None
        self.dir, self.kick = 0j, False
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


class HumanControl:
    """The human-control half of soccer.match.Match (a mixin: it reads and writes the match's own state). Match provides
    humans, team_lists, ball, tick, kickoff_dir and kickoff_taker, and answers two questions of the rules: over() and
    _human_kickoff_wait(h)."""

    def _pick_initial_controlled(self):
        """Every human's first player: SINGLE the slot asked for, else the most advanced formation spot still free; TEAM the
        player nearest the centre. Humans who asked for a slot choose first."""
        for h in sorted(self.humans, key=lambda h: h.slot < 0):
            lst = self.team_lists[h.team]
            free = [p for p in lst if p.human is None]
            if not free:
                continue
            if h.mode == SINGLE:
                if 0 <= h.slot < len(lst) and lst[h.slot].human is None:
                    best = lst[h.slot]
                else:
                    best = max(free, key=lambda p: (p.home.real, p.slot))
            else:
                best = min(free, key=lambda p: abs(p.pos))
            self.set_controlled(best, h)

    def human(self, h=0) -> Human:
        """A Human by number (0 = the first) or the Human itself."""
        return h if isinstance(h, Human) else self.humans[h]

    @property
    def controlled(self):
        """The first human's player (None without humans): the one-human view the recorder and older callers read."""
        return self.humans[0].controlled if self.humans else None

    def set_controlled(self, p, h=0):
        """Hands player `p` to human `h` (not one another human controls)."""
        h = self.human(h)
        if p is not None and p.human is not None and p.human is not h:
            return
        old = h.controlled
        if old is not None:
            old.is_human = False
            old.human = None
            old.input_dir = 0j
            old.input_kick = False
        h.controlled = p
        if p is not None:
            p.is_human = True
            p.intent, p.intent_tick = "none", self.tick      # a person calls nothing (yet)
            p.human = h
            if p.uid not in h.played:
                h.played.append(p.uid)

    def set_human_input(self, d: complex, kick: bool, h=0):
        if self.humans:
            h = self.human(h)
            h.dir = d
            h.kick = kick

    def switch_controlled(self, now=None, h=0):
        """TEAM control mode, the Q key of human `h`. The first press takes the teammate nearest to the ball; another press within
        SWITCH_WINDOW of the previous one takes the next player of the same ranking (made at the first press, so it does not
        reshuffle while the players move): 2nd nearest, 3rd, ..., then back to the player you started from.
        `now` is the caller's clock in ticks (the web session counts real frames, so the window also runs during the kickoff
        intro and at fast-forward speeds); default the match tick.
        While the human's team waits to take a kickoff, the new player becomes the taker (placed behind the ball, the old taker goes
        back to his kickoff spot). A kick held through the switch needs a fresh press on the new player."""
        if not self.humans:
            return
        h = self.human(h)
        if h.mode != TEAM:
            return
        now = self.tick if now is None else now
        own_kickoff = self._human_kickoff_wait(h)
        order, idx = self._switch_plan(h, now, own_kickoff)
        h.switch_order, h.switch_idx, h.switch_last = order, idx, now
        p = order[idx] if order else None
        if p is None or p is h.controlled:
            return
        old = h.controlled
        self.set_controlled(p, h)
        if h.kick:
            p.kick_used = True
        if own_kickoff:
            old.pos, p.pos = old.spawn, -self.kickoff_dir * (p.radius + self.ball.radius + 2.0)
            old.vel = p.vel = 0j
            self.kickoff_taker = p

    def next_switch(self, now=None, h=0):
        """The player a Q of human `h` at `now` would hand control to (None outside TEAM control or when it would change nothing):
        what the page marks with a dashed ring. Reads the same ranking as switch_controlled without changing it."""
        if not self.humans or self.over():
            return None
        h = self.human(h)
        if h.mode != TEAM:
            return None
        order, idx = self._switch_plan(h, self.tick if now is None else now, self._human_kickoff_wait(h))
        p = order[idx] if order else None
        return p if p is not h.controlled else None

    def in_switch_window(self, now, h=0) -> bool:
        """A Q of human `h` at `now` would continue the current ranking (2nd nearest, 3rd, ...) instead of starting a new one."""
        if not self.humans:
            return False
        h = self.human(h)
        idx, order = h.switch_idx, h.switch_order
        return now - h.switch_last <= SWITCH_WINDOW and 0 <= idx < len(order) and order[idx] is h.controlled

    def _switch_plan(self, h, now, own_kickoff):
        """(ranking, index of the player a Q at `now` takes): the current ranking moved one on inside SWITCH_WINDOW, else a
        new one (teammates nobody else controls, by distance to the ball, the controlled player at the end)."""
        lst = [p for p in self.team_lists[h.team] if p.human is None or p.human is h]
        order, idx = h.switch_order, h.switch_idx
        if not self.in_switch_window(now, h):
            others = sorted((p for p in lst if p is not h.controlled), key=lambda p: abs(p.pos - self.ball.pos))
            order = others + ([h.controlled] if h.controlled is not None else [])
            idx = -1
        if order:
            idx = (idx + 1) % len(order)
        return order, idx

    def _auto_switch(self, h):
        best, best_d = None, math.inf
        for p in self.team_lists[h.team]:
            if p.human is not None and p.human is not h:
                continue
            d = abs(p.pos - self.ball.pos)
            if d < best_d:
                best_d, best = d, p
        if best is not None and best is not h.controlled and h.controlled is not None \
                and abs(h.controlled.pos - self.ball.pos) > best_d + 40.0:
            self.set_controlled(best, h)
