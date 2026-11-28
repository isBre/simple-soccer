"""The match: a deterministic (seeded) Haxball-style simulation at a fixed 60 Hz: the rules, kickoffs, touches and stats, the
result. The bodies and their contacts are physics.py. Positions and velocities are complex numbers: x = .real, y = .imag.

Every player is a seat, and a brain plugged in from outside decides for it: a rule-based bot, a net, a person, or nothing (the
seat is driven with act(), e.g. by the RL trainer). The match owns the timing: it asks a person every tick and a bot every
AI_PERIOD ticks (staggered by slot), always with its team's public View, and applies the Act it returns. A brain is any object
with decide(view, me) -> Act; it may declare `person = True` (the rules involving people apply to it) and a shared `batch`
object, in which case batch.decide_batch(views, [(brain, me), ...]) decides all of that batch's due seats of the tick at once."""
import math

from . import rating
from .physics import KIND_BALL, KIND_PLAYER, KIND_STATIC, Disc, prepare_walls, resolve
from .public import (AI_PERIOD, BALL_DAMPING, ENDED, GOAL, HIST, INTENTS, KICK_RANGE, KICK_STRENGTH, PLAYER_ACCEL, PLAYER_DAMPING,
                     PLAYER_KICK_ACCEL, PLAYING, TICK)
from .rng import RandomNumberGenerator
from .stats import MatchStats, snapped
from .vec import clamp, dot, limit_length, normalized, roundi
from .view import View

GOAL_PAUSE = 210


# The engine's own from_angle / rotated (math.cos / math.sin): vec.py's versions (cmath.rect, used by the AI) differ from these in
# the last bit for ~0.2% of angles, and the kickoff direction, the celebration and the puzzle layout are built with these. Using
# one form everywhere changes the matches: it needs re-recorded tests/golden/ and an elo.ENGINE bump.
def from_angle(a: float) -> complex:
    return complex(math.cos(a), math.sin(a))


def rotated(z: complex, a: float) -> complex:
    return z * complex(math.cos(a), math.sin(a))


class Player(Disc):
    """A seat: a player disc, its line-up spot, the brain that decides for it (None: driven with Match.act) and what it does."""

    def __init__(self):
        super().__init__(radius=15.0, inv_mass=0.5, damping=PLAYER_DAMPING, b_coef=0.5, kind=KIND_PLAYER)
        self.team = 0
        self.slot = 0
        self.uid = 0                 # team * 16 + slot
        self.line = "MID"            # line of the kickoff spot (GK / DEF / MID / FWD), the same for every team; read only by the AI
        self.label = None            # who this is, for the result (any object with .id, .name, .kind: soccer.game puts the PlayerDef)
        self.brain = None            # what decides for this seat (None: driven with Match.act)
        self.is_human = False        # its brain is a person (public: the rules involving people use it)
        self.brain_seed = 0          # a random seed drawn by the match for this seat's brain
        self.ps = None
        self.home = 0j               # formation spot in the attack frame (-1 own goal line .. +1 opponent goal line)
        self.spawn = 0j              # kickoff position (world)
        self.input_dir = 0j          # length <= 1
        self.input_kick = False
        self.kick_used = False
        self.kick_intent = ""        # set by the bots: pass / shoot / clear / long (used for the stats)
        self.intent = "none"         # what this player calls to its teammates (INTENTS), and since which tick
        self.intent_tick = 0
        self.in_contact = False
        self.rec_tick = -999
        self.accel = PLAYER_ACCEL
        self.kick_accel = PLAYER_KICK_ACCEL


class MatchSetup:
    """What the core needs to set up a match: the pitch, the clock and the rules, the seed, and per team its slots
    [(label, line, fx, fy), ...] (a line-up: soccer.game builds it from a team) and an id for the result."""

    def __init__(self, pitch, slots, team_ids=("", ""), duration=180.0, score_limit=0, allow_draw=True, seed=1):
        self.pitch = pitch
        self.slots = [list(slots[0]), list(slots[1])]
        self.team_ids = list(team_ids)
        self.duration = duration
        self.score_limit = score_limit
        self.allow_draw = allow_draw              # False: a draw goes to golden-goal overtime (no time limit, no shootout)
        self.seed = seed


class Match:
    def __init__(self, setup: MatchSetup, seating=None):
        """seating(match) -> {uid: brain}, called once the seats exist (their brain_seed drawn); seats it leaves out stay
        empty (driven with act())."""
        self.setup = setup
        self.pitch = setup.pitch
        self.rng = RandomNumberGenerator()
        self.rng.seed = setup.seed
        self.ball = None
        self.statics = []
        self.movers = []
        self.players = []
        self.team_lists = [[], []]
        self.by_uid = {}
        self.reset_count = 0
        self.bseg = []                      # walls for the ball: (a, b, bc)
        self.pseg = []                      # walls for the players
        self._wall_cache = {}               # id(segs) -> (segs, physics.prepare_walls(segs))
        self.scores = [0, 0]
        self.tick = 0
        self.time_left = setup.duration
        self.overtime = False               # golden goal: the first goal ends the match
        self.ot_time = 0.0                  # seconds of overtime played
        self.state = PLAYING
        self.goal_timer = 0
        self.goal_scorer = None
        self.goal_pause = GOAL_PAUSE
        self.goal_center = 0j
        self.goal_team = -1
        self.winner = -1
        self.kickoff_active = True
        self.kickoff_team = 0
        self.kickoff_taker = None
        self.kickoff_dir = 1 + 0j
        self.kickoff_go = 0
        self.kickoff_start = 0
        self.kickoff_waits = []
        self.zone_ticks = [0, 0, 0, 0, 0]
        self.idle_ticks = 0
        self.last_touch = None
        self.last_touch_tick = 0
        self.last_touch_kicked = False
        self.last_touch_kind = ""
        self.assist_cand = None
        self.assist_tick = 0
        self.pending_shot_team = -1
        self.pending_shot_tick = -999
        self.pending_shot_player = None
        self.pending_shot_xg = 0.0
        self.last_shot_xg = 0.0
        self.last_shot_player = None
        self.carry_p = None
        self.carry_start = 0j
        self.carry_last = 0j
        self.carry_pressed = False
        self.kick_pos = 0j
        self.kick_dir = 0j
        self.kick_pressed = False
        self.team_touch_player = [None, None]
        self.team_touch_tick = [-999, -999]
        self.ball_hist = [0j] * HIST
        self.pos_hist = [{} for _ in range(HIST)]   # every player's position in the last HIST ticks (public: soccer/core/view.py)
        self.hist_idx = 0
        self.stats = MatchStats()
        self.events = []
        self.log_events = False
        self.ev_log = []
        self.people = []                    # the person brains, in the order they were first seated (the kickoff rule uses it)
        self._seat_of = {}                  # id(person) -> uid of the seat it is in now
        self.tick_hooks = []                # f(match) called every tick after the goal celebration, before the kicks (seat policies)
        self._build_stadium()
        self._build_players()
        self._reset_positions()
        for uid, brain in (seating(self) if seating is not None else {}).items():
            self.seat(uid, brain)
        if self.people:
            self._setup_kickoff_taker()             # people seated at the start take part in the first kickoff
        self.views = [View(self, 0), View(self, 1)]

    # ------------------------------------------------------------ setup

    @staticmethod
    def attack_dir(team: int) -> float:
        return 1.0 if team == 0 else -1.0

    # what the AI reads (soccer/ai)
    @property
    def ball_pos(self):
        return self.ball.pos

    @property
    def ball_vel(self):
        return self.ball.vel

    @property
    def ball_r(self):
        return self.ball.radius

    @property
    def duration(self):
        return self.setup.duration

    def _static_disc(self, p, r):
        return Disc(p, r, 0.0, 1.0, 0.5, KIND_STATIC)

    def _add_seg(self, for_ball, for_player, a, b, bc):
        if for_ball:
            self.bseg.append((a, b, bc))
        if for_player:
            self.pseg.append((a, b, bc))

    def _build_stadium(self):
        self.ball = Disc(0j, 10.0, 1.0, BALL_DAMPING, 0.5, KIND_BALL)
        pd = self.pitch
        hw, hh, gh, nd = pd.half_w, pd.half_h, pd.goal_half, pd.net_depth
        for sx in (-1.0, 1.0):
            for sy in (-1.0, 1.0):
                self.statics.append(self._static_disc(complex(sx * hw, sy * gh), pd.post_r))
        for o in pd.obstacles:
            self.statics.append(self._static_disc(complex(o[0], o[1]), o[2]))
        self._add_seg(True, False, complex(-hw, -hh), complex(hw, -hh), 1.0)
        self._add_seg(True, False, complex(-hw, hh), complex(hw, hh), 1.0)
        for sx in (-1.0, 1.0):
            bx = sx * (hw + nd)
            self._add_seg(True, False, complex(sx * hw, -hh), complex(sx * hw, -gh), 1.0)
            self._add_seg(True, False, complex(sx * hw, gh), complex(sx * hw, hh), 1.0)
            self._add_seg(True, False, complex(sx * hw, -gh), complex(bx, -gh), 1.0)
            self._add_seg(True, False, complex(bx, -gh), complex(bx, gh), 1.0)
            self._add_seg(True, False, complex(bx, gh), complex(sx * hw, gh), 1.0)
        ox, oy = pd.out_x, pd.out_y
        self._add_seg(False, True, complex(-ox, -oy), complex(ox, -oy), 0.0)
        self._add_seg(False, True, complex(-ox, oy), complex(ox, oy), 0.0)
        self._add_seg(False, True, complex(-ox, -oy), complex(-ox, oy), 0.0)
        self._add_seg(False, True, complex(ox, -oy), complex(ox, oy), 0.0)
        for w in pd.walls:
            self._add_seg(w["ball"], w["player"], w["a"], w["b"], w["bc"])

    def _build_players(self):
        self.movers.append(self.ball)
        for t in (0, 1):
            ax = self.attack_dir(t)
            for i, (label, line, fx, fy) in enumerate(self.setup.slots[t]):
                p = Player()
                p.team = t
                p.slot = i
                p.uid = t * 16 + i
                p.label = label
                p.line = line
                p.home = complex(fx, fy)
                sp = complex(ax * fx * self.pitch.half_w, fy * self.pitch.half_h)
                minr = self.pitch.center_r + p.radius + 6.0
                if abs(sp) < minr:
                    sp = normalized(sp) * minr if abs(sp) > 0.01 else complex(-ax * minr, 0.0)
                p.spawn = sp
                p.ps = self.stats.get_player(p.uid)
                p.brain_seed = self.rng.randi()
                self.players.append(p)
                self.movers.append(p)
                self.team_lists[t].append(p)
                self.by_uid[p.uid] = p

    def _reset_positions(self):
        for p in self.players:
            p.pos = p.spawn
            p.vel = 0j
            p.input_dir = 0j
            p.input_kick = False
            p.kick_used = False
            p.in_contact = False
            p.intent, p.intent_tick = "none", self.tick
        self.ball.pos = 0j
        self.ball.vel = 0j
        self.kickoff_active = True
        self.kickoff_start = self.tick
        self.last_touch = None
        self.assist_cand = None
        self.pending_shot_team = -1
        self.carry_p = None
        self.ball_hist = [0j] * HIST
        self.pos_hist = [{} for _ in range(HIST)]
        self.reset_count += 1
        self._setup_kickoff_taker()

    def _setup_kickoff_taker(self):
        """Random taker (any player), placed right behind the ball so the kickoff is immediate. The kick direction is random
        inside a forward cone and the taker waits a few ticks, so bot-vs-bot kickoffs differ every time. A seat a person drives
        on the kickoff team always takes it (the first person seated, if several)."""
        self.kickoff_taker = None
        lst = self.team_lists[self.kickoff_team]
        if not lst:
            return
        for m in lst:
            m.pos = m.spawn
        ax = self.attack_dir(self.kickoff_team)
        forced = None
        for p in self.people_seats():                 # the first person of the kickoff team takes it
            if p.team == self.kickoff_team:
                forced = p
                break
        taker = forced if forced is not None else lst[self.rng.randi() % len(lst)]
        ang = 0.0 if forced is not None else clamp(self.rng.randfn(0.0, 0.55), -0.95, 0.95)
        self.kickoff_dir = rotated(complex(ax, 0.0), ang)
        taker.pos = -self.kickoff_dir * (taker.radius + self.ball.radius + 2.0)
        self.kickoff_taker = taker
        self.kickoff_go = self.tick + self.rng.randi_range(6, 28)

    # ------------------------------------------------------------ seats

    def seat(self, uid, brain):
        """Puts `brain` in seat `uid` (None: empty, driven with act()). A person leaving a seat leaves no buttons held; a person
        taking one calls nothing yet."""
        p = self.by_uid[uid]
        prev = p.brain
        if prev is brain:
            return
        if p.is_human:
            p.input_dir = 0j
            p.input_kick = False
            del self._seat_of[id(prev)]
        p.brain = brain
        p.is_human = bool(getattr(brain, "person", False))
        if p.is_human:
            if brain not in self.people:
                self.people.append(brain)
            self._seat_of[id(brain)] = uid
            p.intent, p.intent_tick = "none", self.tick

    def switch(self, person, uid, back):
        """A person moves to seat `uid` (TEAM control) and `back` takes the seat it leaves. A kick held through the switch needs a
        fresh press; during the person's own kickoff wait the new seat becomes the taker (the old one back to its kickoff spot)."""
        old = self.seat_of(person)
        p = self.by_uid[uid]
        own_kickoff = self.awaits_kickoff(old.uid)
        self.seat(old.uid, back)
        self.seat(uid, person)
        if getattr(person, "kick", False):
            p.kick_used = True
        if own_kickoff:
            old.pos, p.pos = old.spawn, -self.kickoff_dir * (p.radius + self.ball.radius + 2.0)
            old.vel = p.vel = 0j
            self.kickoff_taker = p

    def seat_of(self, person):
        """The seat a person is in now (None: not seated)."""
        uid = self._seat_of.get(id(person))
        return None if uid is None else self.by_uid[uid]

    def people_seats(self):
        """The seats people drive, in the order the people were first seated."""
        return [self.by_uid[self._seat_of[id(b)]] for b in self.people if id(b) in self._seat_of]

    def awaits_kickoff(self, uid) -> bool:
        """Seat `uid` is its team's kickoff taker and the kickoff is not taken yet."""
        p = self.by_uid[uid]
        return self.state == PLAYING and self.kickoff_active and self.kickoff_team == p.team and self.kickoff_taker is p

    def act(self, uid, a):
        """Applies Act `a` to an empty seat (one driven from outside, e.g. by the RL trainer)."""
        p = self.by_uid[uid]
        if p.brain is not None:
            raise ValueError("seat %d has a brain: it decides itself" % uid)
        self._apply(p, a)

    def _apply(self, p, a):
        p.input_dir, p.input_kick, p.kick_intent = a.dir, a.kick, a.kind
        intent = a.intent if a.intent in INTENTS else "none"
        if intent != p.intent:
            p.intent, p.intent_tick = intent, self.tick

    def _decide(self):
        """The bots that are due decide, each from its team's view as it was at the start of the tick (nobody hears a call made in
        the same tick); brains sharing a batch decide together after the others, in the order they first came up."""
        views = [v.refresh(self) for v in self.views]
        batches = {}
        for t in (0, 1):
            v = views[t]
            for p in self.team_lists[t]:
                b = p.brain
                if b is None or p.is_human or (self.tick + p.slot) % AI_PERIOD != 0:
                    continue
                key = getattr(b, "batch", None)
                if key is not None:
                    batches.setdefault(id(key), (key, []))[1].append(p)
                else:
                    self._apply(p, b.decide(v, v.bodies[p.uid]))
        for key, group in batches.values():
            group.sort(key=lambda p: p.team)
            acts = key.decide_batch(views, [(p.brain, views[p.team].bodies[p.uid]) for p in group])
            for p, a in zip(group, acts):
                self._apply(p, a)

    # ------------------------------------------------------------ simulation

    def ball_at(self, delay: int) -> complex:
        return self.ball_hist[(self.hist_idx - 1 - delay + HIST * 2) % HIST]

    def elapsed(self) -> float:
        t = self.setup.duration - self.time_left
        return t + self.ot_time

    def step(self):
        if self.state == ENDED:
            return
        self.tick += 1
        update = self.tick % AI_PERIOD == 0
        due = False
        for p in self.players:
            if p.is_human:                          # a person every tick: the buttons held now
                v = self.views[p.team]
                a = p.brain.decide(v, v.bodies[p.uid])
                p.input_dir = a.dir
                p.input_kick = a.kick
            elif p.brain is not None and (self.tick + p.slot) % AI_PERIOD == 0:
                due = True
        if update or due:
            self._decide()

        if self.state == GOAL:
            self._celebrate()
        for f in self.tick_hooks:
            f(self)

        for p in self.players:
            self._handle_kick(p)

        for p in self.players:
            a = p.kick_accel if p.input_kick else p.accel
            d = p.input_dir
            if d.real * d.real + d.imag * d.imag > 1.0:
                d = normalized(d)
            p.vel += d * a

        for m in self.movers:
            m.pos += m.vel

        movers = self.movers
        resolve(movers, self.statics, self._walls(self.bseg), self._walls(self.pseg))

        self._apply_kickoff_limits()

        lim = self.ball.radius + 15.0 + 0.6
        lim *= lim
        for p in self.players:
            dd = p.pos - self.ball.pos
            touching = dd.real * dd.real + dd.imag * dd.imag < lim
            if touching and not p.in_contact:
                self._register_touch(p, False)
            p.in_contact = touching
            p.ps.distance += abs(p.vel)

        for m in movers:
            m.vel *= m.damping

        bv = self.ball.vel
        if self.kickoff_active and bv.real * bv.real + bv.imag * bv.imag > 0.01:
            self.kickoff_active = False
            self.kickoff_waits.append(self.tick - self.kickoff_start)

        self.ball_hist[self.hist_idx] = self.ball.pos
        self.pos_hist[self.hist_idx] = {p.uid: p.pos for p in self.players}
        self.hist_idx = (self.hist_idx + 1) % HIST

        if self.state == PLAYING and not self.kickoff_active and self.last_touch is not None:
            self.stats.possession_ticks[self.last_touch.team] += 1
            self.zone_ticks[clamp(int((self.ball.pos.real / self.pitch.half_w + 1.0) * 2.5), 0, 4)] += 1
            bv = self.ball.vel
            if bv.real * bv.real + bv.imag * bv.imag < 0.04:
                self.idle_ticks += 1

        self._update_rules()

    def run_to_end(self, max_ticks=60 * 60 * 8):
        while self.state != ENDED and self.tick < max_ticks:
            self.step()
        if self.state != ENDED:
            self._end_match()

    def _handle_kick(self, p):
        if not p.input_kick:
            p.kick_used = False
            return
        if p.kick_used:
            return
        diff = self.ball.pos - p.pos
        dist = abs(diff)
        if dist - p.radius - self.ball.radius < KICK_RANGE:
            nrm = diff / max(dist, 0.0001)
            self.ball.vel += nrm * KICK_STRENGTH * self.ball.inv_mass
            p.kick_used = True
            self._register_touch(p, True)

    def _walls(self, segs):
        """segs prepared for physics.collide_walls (prepare_walls), cached; rebuilt if the list grew."""
        got = self._wall_cache.get(id(segs))
        if got is None or got[0] is not segs or len(got[1]) != len(segs):
            got = self._wall_cache[id(segs)] = (segs, prepare_walls(segs))
        return got[1]

    def _celebrate(self):
        """After a goal the scorer's bot teammates run to him and form a huddle around him; the other team stands still.
        Nobody kicks. A human-controlled player is never steered: he decides himself whether to join."""
        mates = []
        if self.goal_scorer is not None:
            mates = [m for m in self.team_lists[self.goal_team] if m is not self.goal_scorer and not m.is_human]
        for p in self.players:
            p.input_kick = False
            if not p.is_human:
                p.input_dir = 0j
        gs = self.goal_scorer
        if gs is None:
            return
        # a bot scorer runs a victory lap around the spot, his mates gather in a wider ring around it
        if not gs.is_human:
            age = float(self.goal_pause - self.goal_timer)
            dr = 1.0 if gs.uid % 2 == 0 else -1.0
            ang = dr * age * 0.03 + gs.uid
            tgt = self.goal_center + from_angle(ang) * 80.0
            gs.input_dir = limit_length(tgt - gs.pos, 1.0)
        pd = self.pitch
        for i, m in enumerate(mates):
            ang2 = math.tau * i / max(len(mates), 1) + gs.uid * 0.7
            spot = self.goal_center + from_angle(ang2) * (125.0 + 12.0 * (i % 2))
            spot = complex(clamp(spot.real, -pd.half_w + 40.0, pd.half_w - 40.0), clamp(spot.imag, -pd.half_h + 40.0, pd.half_h - 40.0))
            cmd = ((spot - m.pos) - m.vel * 20.0) / 30.0
            if abs(spot - m.pos) > 80.0:
                cmd = normalized(spot - m.pos)
            m.input_dir = limit_length(cmd, 1.0)

    def _apply_kickoff_limits(self):
        if not self.kickoff_active:
            return
        for p in self.players:
            r = p.radius
            wrong_side = p.pos.real > -r if p.team == 0 else p.pos.real < r
            if wrong_side:
                allow = self.pitch.center_r - r
                if p.team == self.kickoff_team and abs(p.pos.imag) < allow and abs(p.pos) > allow:
                    # the team that kicks off may use the whole centre circle (e.g. to play the ball back), but not leave
                    # it on the opponents' side
                    nrm = p.pos / max(abs(p.pos), 0.001)
                    p.pos = nrm * allow
                    vn = dot(p.vel, nrm)
                    if vn > 0.0:
                        p.vel -= nrm * vn
                elif p.team != self.kickoff_team or abs(p.pos.imag) >= allow:
                    if p.team == 0:
                        p.pos = complex(-r, p.pos.imag)
                        p.vel = complex(min(p.vel.real, 0.0), p.vel.imag)
                    else:
                        p.pos = complex(r, p.pos.imag)
                        p.vel = complex(max(p.vel.real, 0.0), p.vel.imag)
            if p.team != self.kickoff_team:
                dist = abs(p.pos)
                minr = self.pitch.center_r + r
                if dist < minr:
                    nrm = p.pos / max(dist, 0.001)
                    p.pos = nrm * minr
                    vn = dot(p.vel, nrm)
                    if vn < 0.0:
                        p.vel -= nrm * vn

    # ------------------------------------------------------------ touches & stats

    def _pressed(self, p) -> bool:
        """An opponent is close enough to bother this player."""
        for o in self.team_lists[1 - p.team]:
            d = o.pos - p.pos
            if d.real * d.real + d.imag * d.imag < 3844.0:    # 62 px
                return True
        return False

    def _end_carry(self):
        if self.carry_p is None:
            return
        fwd = (self.carry_last.real - self.carry_start.real) * self.attack_dir(self.carry_p.team)
        if fwd > 0.0:
            self.carry_p.ps.carry_dist += fwd
            if self.carry_pressed and fwd > self.pitch.half_w * 0.06:
                self.carry_p.ps.dribbles += 1
        self.carry_p = None

    def _register_touch(self, p, kicked):
        if self.state == GOAL:
            return
        tick = self.tick
        if self.last_touch is p and tick - self.last_touch_tick < 8:
            self.last_touch_tick = tick
            if not kicked:
                self.carry_last = self.ball.pos
                if not self.carry_pressed and self._pressed(p):
                    self.carry_pressed = True
            if kicked and not self.last_touch_kicked:
                self.last_touch_kicked = True
                self._classify_kick(p)
            return
        p.ps.touches += 1
        half_w = self.pitch.half_w
        lt = self.last_touch
        if lt is not None and lt is not p:
            ax_lt = self.attack_dir(lt.team)
            if lt.team == p.team:
                self._end_carry()
                if self.last_touch_kicked and self.last_touch_kind == "pass" and tick - self.last_touch_tick < 240:
                    lt.ps.passes_ok += 1
                    p.ps.passes_received += 1
                    self._log_ev("pass_ok", lt.team, lt.uid, self.kick_pos, self.ball.pos, float(p.uid))
                    gain = (self.ball.pos.real - self.kick_pos.real) * ax_lt
                    prog_thr = half_w * 0.2
                    if gain >= prog_thr:
                        lt.ps.progressive_passes += 1
                    lt.ps.pass_value += rating.pass_value(True, gain, False, self.kick_pressed,
                                                          self.kick_pos.real * ax_lt / half_w, prog_thr)
                self.assist_cand = lt
                self.assist_tick = tick
            else:
                was_dribbling = self.carry_p is lt and not self.last_touch_kicked and tick - self.last_touch_tick < 14
                if was_dribbling:
                    lt.ps.dispossessed += 1
                    self.carry_p = None
                else:
                    self._end_carry()
                if self.last_touch_kicked and self.last_touch_kind == "pass":
                    lt.ps.passes_failed += 1
                    self._log_ev("pass_fail", lt.team, lt.uid, self.kick_pos, self.ball.pos, float(p.uid))
                    lt.ps.pass_value += rating.pass_value(False, 0.0, self.kick_dir.real * ax_lt > 0.5, self.kick_pressed,
                                                          self.kick_pos.real * ax_lt / half_w, half_w * 0.2)
                if self.pending_shot_team == lt.team and tick - self.pending_shot_tick < 150:
                    p.ps.blocks += 1                 # a shot on target stopped (by anyone: there is no keeper)
                    self.pending_shot_team = -1
                elif was_dribbling:
                    p.ps.tackles += 1
                    p.rec_tick = tick
                    self._log_ev("tackle", p.team, p.uid, self.ball.pos, self.ball.pos, 0.0)
                elif self.last_touch_kicked and self.last_touch_kind in ("pass", "clear") \
                        and tick - self.last_touch_tick < 90 and tick - p.rec_tick >= 30:
                    p.ps.interceptions += 1
                    p.rec_tick = tick
                    self._log_ev("intercept", p.team, p.uid, self.ball.pos, self.ball.pos, 0.0)
                elif tick - self.last_touch_tick >= 12 and tick - p.rec_tick >= 60:
                    p.ps.recoveries += 1
                    p.rec_tick = tick
                    self._log_ev("recovery", p.team, p.uid, self.ball.pos, self.ball.pos, 0.0)
                self.assist_cand = None
        # a new possession by this player starts a carry (a kick ends it again straight away)
        if self.carry_p is p and self.last_touch is p and not kicked:
            self.carry_last = self.ball.pos      # same dribble, the ball just got away for a moment
        else:
            self._end_carry()
            if not kicked:
                self.carry_p = p
                self.carry_start = self.ball.pos
                self.carry_last = self.ball.pos
                self.carry_pressed = self._pressed(p)
        self.last_touch = p
        self.last_touch_tick = tick
        self.last_touch_kicked = kicked
        self.last_touch_kind = "touch"
        self.team_touch_player[p.team] = p
        self.team_touch_tick[p.team] = tick
        if kicked:
            self._classify_kick(p)

    def _log_ev(self, kind, team, uid, a, b, v):
        if not self.log_events:
            return
        ax = self.attack_dir(team)
        self.ev_log.append([kind, self.tick, team, uid, roundi(a.real * ax), roundi(a.imag), roundi(b.real * ax), roundi(b.imag),
                            snapped(v, 0.001)])

    def _classify_kick(self, p):
        ax = self.attack_dir(p.team)
        kind = "pass"
        v = self.ball.vel
        self._end_carry()
        self.kick_pos = self.ball.pos
        self.kick_dir = normalized(v)
        self.kick_pressed = self._pressed(p)
        pd = self.pitch
        gx = ax * pd.half_w
        if v.real * ax > 0.5:
            t = (gx - self.ball.pos.real) / v.real
            if t > 0.0:
                y_at = self.ball.pos.imag + v.imag * t
                dcross = abs(complex(gx - self.ball.pos.real, y_at - self.ball.pos.imag))
                if dcross < abs(v) * 55.0 and abs(y_at) < pd.goal_half + 45.0:
                    kind = "shot"
                    p.ps.shots += 1
                    xg = rating.shot_xg(self.ball.pos, gx, pd.goal_half)
                    p.ps.xg += xg
                    if xg >= 0.3:
                        p.ps.big_chances += 1
                    self.last_shot_xg = xg
                    self.last_shot_player = p
                    ac = self.assist_cand
                    if ac is not None and ac is not p and ac.team == p.team and self.tick - self.assist_tick < 240:
                        ac.ps.key_passes += 1
                        ac.ps.xa += xg
                    on = abs(y_at) < pd.goal_half - self.ball.radius
                    self._log_ev("shot_on" if on else "shot", p.team, p.uid, self.ball.pos, self.ball.pos, xg)
                    if on:
                        p.ps.shots_on_target += 1
                        self.pending_shot_team = p.team
                        self.pending_shot_tick = self.tick
                        self.pending_shot_player = p
                        self.pending_shot_xg = xg
        if kind == "pass" and p.kick_intent == "shoot":
            # the bot aimed at goal but the ball is not heading into the mouth (aim error): a wide shot, not a failed pass
            kind = "shot"
            p.ps.shots += 1
            xg_wide = rating.shot_xg(self.ball.pos, gx, pd.goal_half)
            p.ps.xg += xg_wide
            self._log_ev("shot", p.team, p.uid, self.ball.pos, self.ball.pos, xg_wide)
            if xg_wide >= 0.3:
                p.ps.big_chances += 1
        if kind == "pass" and p.kick_intent in ("clear", "long"):
            kind = "clear"
            if self.kick_pos.real * ax < -pd.half_w * 0.25:
                p.ps.clearances += 1
        self.last_touch_kind = kind

    # ------------------------------------------------------------ rules

    def _update_rules(self):
        if self.state == PLAYING:
            if abs(self.ball.pos.real) > self.pitch.half_w + self.ball.radius:      # the whole ball is over the line
                self._goal_scored(0 if self.ball.pos.real > 0.0 else 1)
            elif not self.kickoff_active:
                if not self.overtime:
                    self.time_left -= TICK
                    if self.time_left <= 0.0:
                        self.time_left = 0.0
                        if self.scores[0] != self.scores[1] or self.setup.allow_draw:
                            self._end_match()
                        else:
                            self.overtime = True          # golden goal: play on until someone scores
                else:
                    self.ot_time += TICK
        elif self.state == GOAL:
            self.goal_timer -= 1
            if self.goal_timer <= 0:
                limit_hit = self.setup.score_limit > 0 and (self.scores[0] >= self.setup.score_limit or self.scores[1] >= self.setup.score_limit)
                if limit_hit or self.overtime:
                    self._end_match()
                else:
                    self.state = PLAYING
                    self.kickoff_team = 1 - self.goal_team
                    self._reset_positions()

    def _goal_scored(self, team):
        self.scores[team] += 1
        self.goal_team = team
        self.state = GOAL
        self.goal_timer = GOAL_PAUSE
        scorer = self.last_touch
        tick = self.tick
        if scorer is not None and scorer.team != team:
            if self.pending_shot_player is not None and self.pending_shot_team == team and tick - self.pending_shot_tick < 200:
                scorer = self.pending_shot_player      # deflected / saved-into-net shot belongs to the shooter
            else:
                cand = self.team_touch_player[team]
                # a mere body-touch by the defender does not turn a dribbled-in ball into an own goal
                if cand is not None and not self.last_touch_kicked and tick - int(self.team_touch_tick[team]) < 180:
                    scorer = cand
        self.goal_scorer = scorer if (scorer is not None and scorer.team == team) else None
        pd = self.pitch
        if self.goal_scorer is not None:
            gp = self.goal_scorer.pos
            self.goal_center = complex(clamp(gp.real, -pd.half_w + 140.0, pd.half_w - 140.0),
                                       clamp(gp.imag, -pd.half_h + 110.0, pd.half_h - 110.0))
        # the pause lasts long enough for the scorer's teammates to run over to him (up to ~4.3 s)
        self.goal_pause = GOAL_PAUSE
        if self.goal_scorer is not None:
            far = 0.0
            for m in self.team_lists[team]:
                far = max(far, abs(m.pos - self.goal_scorer.pos))
            self.goal_pause = int(clamp(130 + int(far / 5.0), 150, 260))
        self.goal_timer = self.goal_pause
        lt = self.last_touch
        ev = {"type": "goal", "team": team, "clock": self.elapsed(), "scorer": -1, "scorer_name": "",
              "assist": -1, "assist_name": "", "own": False, "last_kind": self.last_touch_kind,
              "dt": tick - self.last_touch_tick,
              "ball_speed": abs(self.ball.vel)}
        if scorer is not None:
            ev["scorer"] = scorer.uid
            ev["scorer_name"] = scorer.label.name
            if scorer.team == team:
                scorer.ps.goals += 1
                ac = self.assist_cand
                if ac is not None and ac is not scorer and ac.team == team and tick - self.assist_tick < 420:
                    ev["assist"] = ac.uid
                    ev["assist_name"] = ac.label.name
                    ac.ps.assists += 1
            else:
                ev["own"] = True
                scorer.ps.own_goals += 1
        shot_goal = self.last_touch_kind == "shot" and self.last_shot_player is not None and self.last_shot_player.team == team
        if scorer is not None and scorer.team == team and shot_goal and self.last_shot_player is scorer and self.last_shot_xg >= 0.3:
            scorer.ps.big_scored += 1
        for p in self.team_lists[team]:
            p.ps.scored_for += 1
        for p in self.team_lists[1 - team]:
            p.ps.conceded += 1
        self.events.append(ev)
        self.pending_shot_team = -1

    def _end_match(self):
        if self.state == ENDED:
            return
        self.state = ENDED
        if self.scores[0] == self.scores[1]:
            self.winner = -1
        else:
            self.winner = 0 if self.scores[0] > self.scores[1] else 1

    # ------------------------------------------------------------ output

    def make_result(self) -> dict:
        plist = []
        for p in self.players:
            d = p.ps.to_dict()
            d.update({"uid": p.uid, "id": p.label.id, "name": p.label.name, "kind": p.label.kind, "team": p.team, "slot": p.slot})
            plist.append(d)
        tstats = []
        total_poss = self.stats.possession_ticks[0] + self.stats.possession_ticks[1]
        for t in (0, 1):
            ts = {"shots": 0, "shots_on_target": 0, "passes": 0, "passes_ok": 0, "recoveries": 0,
                  "blocks": 0, "touches": 0, "goals": self.scores[t], "xg": 0.0, "dribbles": 0}
            for p in self.team_lists[t]:
                ps = p.ps
                ts["shots"] += ps.shots
                ts["shots_on_target"] += ps.shots_on_target
                ts["passes"] += ps.passes()
                ts["passes_ok"] += ps.passes_ok
                ts["recoveries"] += ps.tackles + ps.interceptions
                ts["xg"] += ps.xg
                ts["dribbles"] += ps.dribbles
                ts["blocks"] += ps.blocks
                ts["touches"] += ps.touches
            ts["possession"] = 50.0 if total_poss == 0 else 100.0 * self.stats.possession_ticks[t] / total_poss
            tstats.append(ts)
        return {"teams": list(self.setup.team_ids), "scores": [self.scores[0], self.scores[1]],
                "winner": self.winner, "overtime": self.overtime, "overtime_s": round(self.ot_time, 1), "events": self.events,
                "players": plist, "team_stats": tstats, "duration": self.setup.duration,
                "ticks": self.tick, "kickoff_waits": list(self.kickoff_waits), "zones": list(self.zone_ticks),
                "idle": self.idle_ticks}

    def puzzle_layout(self, seed: int):
        """Puzzle (the Live page): every player and the ball at random places, play from the first tick.
        The layout is drawn from its own RandomNumberGenerator seeded with `seed`, so a seed always gives the same puzzle."""
        rng = RandomNumberGenerator(seed)
        self.kickoff_active = False
        self.kickoff_taker = None
        self.state = PLAYING
        hw, hh = self.pitch.half_w * 0.9, self.pitch.half_h * 0.9
        self.ball.pos = complex(rng.randf_range(-hw, hw), rng.randf_range(-hh, hh))
        a = rng.randf() * math.tau
        self.ball.vel = from_angle(a) * rng.randf_range(0.0, 3.0)
        placed = [self.ball.pos]
        for p in self.players:
            pos = 0j
            for _ in range(40):
                pos = complex(rng.randf_range(-hw, hw), rng.randf_range(-hh, hh))
                if all(abs(q - pos) >= 45.0 for q in placed):
                    break
            p.pos = pos
            p.vel = 0j
            placed.append(pos)
