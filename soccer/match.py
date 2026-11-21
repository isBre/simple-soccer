"""The match: a deterministic (seeded) Haxball-style simulation at a fixed 60 Hz. Physics, match rules, touches, stats,
grades and the result. Started as a line-by-line port of the Godot game's MatchSim (matched it tick by tick before Godot was removed);
tests/test_match.py now guards it against stored matches. Positions and velocities are complex numbers: x = .real, y = .imag.

The AI is plugged in as `match.ai` (soccer.ai.MatchAI by default): it is asked once per AI tick to update the team plans
and set the inputs of the bots that are due, exactly when Godot's MatchSim asked its brain."""
import math
import os

from . import rating
from .data import ROOT, database
from .rng import RandomNumberGenerator
from .stats import MatchStats, snapped

TICK = 1.0 / 60.0
KICK_STRENGTH = 5.0
KICK_RANGE = 4.0
GOAL_PAUSE = 210
AI_PERIOD = 2
HIST = 32
PLAYING, GOAL, ENDED = 0, 1, 2
KIND_BALL, KIND_PLAYER, KIND_STATIC = 1, 2, 4
NONE, SINGLE, TEAM = 0, 1, 2                  # MatchConfig.ControlMode
# discrete actions of the RL trainer: move index -> direction in the player's own frame (+x towards the opponent goal)
DIRS = [0j, -1j, 1 - 1j, 1 + 0j, 1 + 1j, 1j, -1 + 1j, -1 + 0j, -1 - 1j]


def clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


def dot(a: complex, b: complex) -> float:
    return a.real * b.real + a.imag * b.imag


def normalized(z: complex) -> complex:
    l = abs(z)
    return z / l if l > 0.0 else 0j


def limit_length(z: complex, n: float = 1.0) -> complex:
    l = abs(z)
    return z / l * n if l > n else z


def from_angle(a: float) -> complex:
    return complex(math.cos(a), math.sin(a))


def rotated(z: complex, a: float) -> complex:
    return z * complex(math.cos(a), math.sin(a))


def res_path(path: str) -> str:
    """res://x -> <project>/x (model paths in team files are Godot paths)."""
    return os.path.join(ROOT, path[6:]) if path.startswith("res://") else path


class Disc:
    """A circle with Haxball-style physical properties."""
    __slots__ = ("pos", "vel", "radius", "inv_mass", "damping", "b_coef", "kind")

    def __init__(self, pos=0j, radius=10.0, inv_mass=1.0, damping=0.99, b_coef=0.5, kind=KIND_BALL):
        self.pos = pos
        self.vel = 0j
        self.radius = radius
        self.inv_mass = inv_mass
        self.damping = damping
        self.b_coef = b_coef
        self.kind = kind


class Player(Disc):
    """A player disc. The AI adds its own fields (soccer.ai) on top."""

    def __init__(self):
        super().__init__(radius=15.0, inv_mass=0.5, damping=0.96, b_coef=0.5, kind=KIND_PLAYER)
        self.team = 0
        self.slot = 0
        self.uid = 0                 # team * 16 + slot
        self.role = "MID"            # GK / DEF / MID / FWD
        self.pdef = None             # data.PlayerDef
        self.is_human = False
        self.bot = True              # decided by the AI; False = a human or an external controller (RL training)
        self.ai_seed = 0
        self.ps = None
        self.home = 0j               # formation spot in the attack frame (-1 own goal line .. +1 opponent goal line)
        self.spawn = 0j              # kickoff position (world)
        self.input_dir = 0j          # length <= 1
        self.input_kick = False
        self.kick_used = False
        self.kick_intent = ""        # set by the bots: pass / shoot / clear / long (used for the stats)
        self.in_contact = False
        self.rec_tick = -999
        self.accel = 0.1
        self.kick_accel = 0.07


class MatchConfig:
    """Everything needed to set up one match (MatchConfig in Godot)."""

    def __init__(self):
        self.pitch = None
        self.teams = [None, None]           # data.Team; [0] attacks right (left side), [1] attacks left
        self.styles = [None, None]          # data.Style per team (None = the team's own style)
        self.team_size = 3
        self.duration = 180.0
        self.score_limit = 0
        self.allow_draw = True
        self.overtime = 60.0
        self.match_seed = 1
        self.control = NONE
        self.human_team = 0
        self.auto_switch = False
        self.human_role = ""                # SINGLE control: GK / DEF / MID / FWD = control that role's first player ("" = auto)
        self.formations = ["", ""]
        self.nets = [None, None]            # {"model": path} | {"dict": model} | None (the team's ml_model, else rules)
        self.net_temperature = 1.0

    def get_style(self, t):
        return self.styles[t] if self.styles[t] is not None else database().style_of(self.teams[t])


def make_config(team_a, team_b, pitch_id="arena", size=5, duration=180.0, seed=1, db=None) -> MatchConfig:
    """Database.make_config: a match between two teams of data/teams."""
    db = db or database()
    c = MatchConfig()
    c.pitch = db.pitches.get(pitch_id) or next(iter(db.pitches.values()))
    c.teams = [db.teams[team_a], db.teams[team_b]]
    c.team_size = size
    c.duration = duration
    c.match_seed = seed
    return c


class Match:
    def __init__(self, cfg: MatchConfig, ai=True):
        self.cfg = cfg
        self.pitch = cfg.pitch
        self.rng = RandomNumberGenerator()
        self.rng.seed = cfg.match_seed
        self.ball = None
        self.statics = []
        self.movers = []
        self.players = []
        self.team_lists = [[], []]
        self.by_uid = {}
        self.styles = []
        self.keeper_uid = [-1, -1]
        self.reset_count = 0
        self.bseg = []                      # walls for the ball: (a, b, bc)
        self.pseg = []                      # walls for the players
        self.scores = [0, 0]
        self.tick = 0
        self.time_left = cfg.duration
        self.overtime = False
        self.ot_left = 0.0
        self.state = PLAYING
        self.goal_timer = 0
        self.goal_scorer = None
        self.goal_pause = GOAL_PAUSE
        self.goal_center = 0j
        self.goal_team = -1
        self.winner = -1
        self.shootout = []
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
        self.hist_idx = 0
        self.stats = MatchStats()
        self.events = []
        self.log_events = False
        self.ev_log = []
        self.mom_uid = -1
        self.controlled = None
        self.human_dir = 0j
        self.human_kick = False
        self._build_stadium()
        self._build_players()
        self._reset_positions()
        if cfg.control != NONE:
            self._pick_initial_controlled()
            self._setup_kickoff_taker()
        self.ai = None
        if ai:
            from .ai import MatchAI
            self.ai = MatchAI(self)

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
        return self.cfg.duration

    def _static_disc(self, p, r):
        return Disc(p, r, 0.0, 1.0, 0.5, KIND_STATIC)

    def _add_seg(self, for_ball, for_player, a, b, bc):
        if for_ball:
            self.bseg.append((a, b, bc))
        if for_player:
            self.pseg.append((a, b, bc))

    def _build_stadium(self):
        self.ball = Disc(0j, 10.0, 1.0, 0.99, 0.5, KIND_BALL)
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
        cfg = self.cfg
        for t in (0, 1):
            self.styles.append(cfg.get_style(t))
        self.movers.append(self.ball)
        for t in (0, 1):
            team = cfg.teams[t]
            ax = self.attack_dir(t)
            if cfg.nets[t] is None and team.ml_model:
                # a team driven by a trained net (the AI falls back to the rule-based style when the net does not fit the size)
                cfg.nets[t] = {"model": res_path(team.ml_model)}
            for i, (pdef, role, fx, fy) in enumerate(team.lineup(cfg.team_size, cfg.formations[t])):
                p = Player()
                p.team = t
                p.slot = i
                p.uid = t * 16 + i
                p.pdef = pdef
                p.role = role
                p.home = complex(fx, fy)
                sp = complex(ax * fx * self.pitch.half_w, fy * self.pitch.half_h)
                minr = self.pitch.center_r + p.radius + 6.0
                if abs(sp) < minr:
                    sp = normalized(sp) * minr if abs(sp) > 0.01 else complex(-ax * minr, 0.0)
                p.spawn = sp
                p.ps = self.stats.get_player(p.uid)
                p.ai_seed = self.rng.randi()
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
        self.ball.pos = 0j
        self.ball.vel = 0j
        self.kickoff_active = True
        self.kickoff_start = self.tick
        self.last_touch = None
        self.assist_cand = None
        self.pending_shot_team = -1
        self.carry_p = None
        self.ball_hist = [0j] * HIST
        self.reset_count += 1
        self._setup_kickoff_taker()

    def _setup_kickoff_taker(self):
        """Random taker (never the nominal GK), placed right behind the ball so the kickoff is immediate. The kick
        direction is random inside a forward cone and the taker waits a few ticks, so bot-vs-bot kickoffs differ every
        time. A human-controlled player on the kickoff team always takes it himself."""
        self.kickoff_taker = None
        lst = self.team_lists[self.kickoff_team]
        if not lst:
            return
        for m in lst:
            m.pos = m.spawn
        ax = self.attack_dir(self.kickoff_team)
        cands = [sp for sp in lst if sp.role != "GK" or len(lst) == 1] or lst
        forced = None
        if self.cfg.control != NONE and self.kickoff_team == self.cfg.human_team \
                and self.controlled is not None and self.controlled.team == self.kickoff_team \
                and not (self.cfg.human_role == "GK" and self.controlled.role == "GK" and len(lst) > 1):
            forced = self.controlled                # (a keeper picked on the setup page stays in goal)
        taker = forced if forced is not None else cands[self.rng.randi() % len(cands)]
        ang = 0.0 if forced is not None else clamp(self.rng.randfn(0.0, 0.55), -0.95, 0.95)
        self.kickoff_dir = rotated(complex(ax, 0.0), ang)
        taker.pos = -self.kickoff_dir * (taker.radius + self.ball.radius + 2.0)
        self.kickoff_taker = taker
        self.kickoff_go = self.tick + self.rng.randi_range(6, 28)

    def _pick_initial_controlled(self):
        best = None
        lst = self.team_lists[self.cfg.human_team]
        if self.cfg.control == SINGLE and self.cfg.human_role:     # the page picked a role (keeper included): its first player
            best = next((p for p in lst if p.role == self.cfg.human_role), None)
            if best is not None:
                self.set_controlled(best)
                return
        for p in lst:
            if p.role == "GK" and len(lst) > 1:
                continue
            if self.cfg.control == SINGLE:
                if best is None or (p.role == "FWD" and best.role != "FWD") or (p.role == best.role and p.slot > best.slot):
                    best = p
            else:
                if best is None or abs(p.pos) < abs(best.pos):
                    best = p
        self.set_controlled(best)

    # ------------------------------------------------------------ human control

    def set_controlled(self, p):
        if self.controlled is not None:
            self.controlled.is_human = False
            self.controlled.input_dir = 0j
            self.controlled.input_kick = False
        self.controlled = p
        if p is not None:
            p.is_human = True

    def set_human_input(self, d: complex, kick: bool):
        self.human_dir = d
        self.human_kick = kick

    def switch_controlled(self):
        """TEAM control mode: hand control to the teammate nearest to the ball."""
        if self.cfg.control != TEAM:
            return
        best, best_d = None, math.inf
        for p in self.team_lists[self.cfg.human_team]:
            if p is self.controlled:
                continue
            d = abs(p.pos - self.ball.pos) ** 2
            if d < best_d:
                best_d, best = d, p
        if best is not None:
            self.set_controlled(best)

    # ------------------------------------------------------------ simulation

    def ball_at(self, delay: int) -> complex:
        return self.ball_hist[(self.hist_idx - 1 - delay + HIST * 2) % HIST]

    def elapsed(self) -> float:
        t = self.cfg.duration - self.time_left
        if self.overtime:
            t += self.cfg.overtime - self.ot_left
        return t

    def step(self):
        if self.state == ENDED:
            return
        self.tick += 1
        update = self.tick % AI_PERIOD == 0
        due = False
        for p in self.players:
            if p.is_human:
                p.input_dir = self.human_dir
                p.input_kick = self.human_kick
            elif p.bot and (self.tick + p.slot) % AI_PERIOD == 0:
                due = True
        if self.ai is not None and (update or due):
            self.ai.decide(self, update)          # team plans every AI_PERIOD ticks, then the bots that are due

        if self.state == GOAL:
            self._celebrate()
        if self.cfg.auto_switch and self.cfg.control == TEAM and self.tick % 20 == 0:
            self._auto_switch()

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
        n = len(movers)
        for i in range(n):
            a = movers[i]
            for j in range(i + 1, n):
                self._collide_discs(a, movers[j])
            for s in self.statics:
                self._collide_discs(a, s)
            self._collide_walls(a, self.bseg if a.kind == KIND_BALL else self.pseg)

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
            if self._is_keeper(p):
                p.ps.keeper_ticks += 1

        for m in movers:
            m.vel *= m.damping

        bv = self.ball.vel
        if self.kickoff_active and bv.real * bv.real + bv.imag * bv.imag > 0.01:
            self.kickoff_active = False
            self.kickoff_waits.append(self.tick - self.kickoff_start)

        self.ball_hist[self.hist_idx] = self.ball.pos
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

    def _auto_switch(self):
        best, best_d = None, math.inf
        for p in self.team_lists[self.cfg.human_team]:
            d = abs(p.pos - self.ball.pos)
            if d < best_d:
                best_d, best = d, p
        if best is not None and best is not self.controlled and self.controlled is not None \
                and abs(self.controlled.pos - self.ball.pos) > best_d + 40.0:
            self.set_controlled(best)

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

    @staticmethod
    def _collide_discs(a, b):
        diff = a.pos - b.pos
        rsum = a.radius + b.radius
        d2 = diff.real * diff.real + diff.imag * diff.imag
        if d2 >= rsum * rsum or d2 < 0.00000001:
            return
        mass_sum = a.inv_mass + b.inv_mass
        if mass_sum == 0.0:
            return
        dist = math.sqrt(d2)
        nrm = diff / dist
        share = a.inv_mass / mass_sum
        pen = rsum - dist
        a.pos += nrm * pen * share
        b.pos -= nrm * pen * (1.0 - share)
        rv = a.vel - b.vel
        rel = rv.real * nrm.real + rv.imag * nrm.imag
        if rel < 0.0:
            bc = a.b_coef * b.b_coef
            j = rel * (bc + 1.0) / mass_sum
            a.vel -= nrm * j * a.inv_mass
            b.vel += nrm * j * b.inv_mass

    @staticmethod
    def _collide_walls(d, segs):
        r = d.radius
        for a, b, c in segs:
            ab = b - a
            pa = d.pos - a
            t = (pa.real * ab.real + pa.imag * ab.imag) / (ab.real * ab.real + ab.imag * ab.imag)
            t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
            diff = d.pos - (a + ab * t)
            d2 = diff.real * diff.real + diff.imag * diff.imag
            if d2 >= r * r or d2 < 0.00000001:
                continue
            dist = math.sqrt(d2)
            nrm = diff / dist
            d.pos += nrm * (r - dist)
            v = d.vel
            vn = v.real * nrm.real + v.imag * nrm.imag
            if vn < 0.0:
                d.vel -= nrm * vn * (1.0 + d.b_coef * c)

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

    def _is_keeper(self, p) -> bool:
        k = self.keeper_uid[p.team]
        return k == p.uid if k >= 0 else p.role == "GK"

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
                    if self._is_keeper(p):
                        p.ps.saves += 1
                        p.ps.save_xg += self.pending_shot_xg
                    else:
                        p.ps.blocks += 1
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
        rnd = lambda x: math.floor(x + 0.5) if x >= 0 else -math.floor(-x + 0.5)       # Godot's roundf
        self.ev_log.append([kind, self.tick, team, uid, rnd(a.real * ax), rnd(a.imag), rnd(b.real * ax), rnd(b.imag),
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
                        if self.scores[0] != self.scores[1] or self.cfg.allow_draw:
                            self._end_match()
                        else:
                            self.overtime = True
                            self.ot_left = self.cfg.overtime
                else:
                    self.ot_left -= TICK
                    if self.ot_left <= 0.0:
                        self.ot_left = 0.0
                        self._run_shootout()
                        self._end_match()
        elif self.state == GOAL:
            self.goal_timer -= 1
            if self.goal_timer <= 0:
                limit_hit = self.cfg.score_limit > 0 and (self.scores[0] >= self.cfg.score_limit or self.scores[1] >= self.cfg.score_limit)
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
              "last_role": lt.role if lt is not None else "", "dt": tick - self.last_touch_tick,
              "ball_speed": abs(self.ball.vel)}
        if scorer is not None:
            ev["scorer"] = scorer.uid
            ev["scorer_name"] = scorer.pdef.name
            if scorer.team == team:
                scorer.ps.goals += 1
                ac = self.assist_cand
                if ac is not None and ac is not scorer and ac.team == team and tick - self.assist_tick < 420:
                    ev["assist"] = ac.uid
                    ev["assist_name"] = ac.pdef.name
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
            if self._is_keeper(p):
                p.ps.conceded_xg += self.last_shot_xg if shot_goal else 0.3
        self.events.append(ev)
        self.pending_shot_team = -1

    def _run_shootout(self):
        res = [0, 0]
        takers, keepers = [], []
        for t in (0, 1):
            lst = []
            gk = 60.0
            for p in self.team_lists[t]:
                if p.role == "GK":
                    gk = (p.pdef.positioning + p.pdef.reaction) / 2.0
                else:
                    lst.append(p)
            if not lst:
                lst = list(self.team_lists[t])
            lst.sort(key=lambda p: -p.pdef.finishing)   # ties keep their order (the chance only depends on finishing)
            takers.append(lst)
            keepers.append(gk)
        rd = 0
        while rd < 30:
            for t in (0, 1):
                tk = takers[t][rd % len(takers[t])]
                chance = clamp(0.72 + (tk.pdef.finishing - keepers[1 - t]) / 250.0, 0.5, 0.92)
                if self.rng.randf() < chance:
                    res[t] += 1
            rd += 1
            if rd >= 5 and res[0] != res[1]:
                break
        if res[0] == res[1]:
            res[self.rng.randi() % 2] += 1
        self.shootout = res

    def _end_match(self):
        if self.state == ENDED:
            return
        self.state = ENDED
        if self.shootout:
            self.winner = 0 if self.shootout[0] > self.shootout[1] else 1
        elif self.scores[0] == self.scores[1]:
            self.winner = -1
        else:
            self.winner = 0 if self.scores[0] > self.scores[1] else 1
        best_r = -1.0
        for p in self.players:
            won = self.winner == p.team
            lost = self.winner != -1 and self.winner != p.team
            p.ps.rating = rating.grade(self.played_role(p), p.ps, won, lost, self.scores[1 - p.team])
            score = p.ps.rating + (p.ps.goals + p.ps.assists) * 0.001
            if score > best_r:
                best_r = score
                self.mom_uid = p.uid

    def played_role(self, p) -> str:
        """The role a player actually filled: whoever spent most of the match in goal is the keeper, a nominal goalkeeper
        who was not is judged as a defender."""
        if p.ps.keeper_ticks * 2 > max(self.tick, 1):
            return "GK"
        return "DEF" if p.role == "GK" else p.role

    # ------------------------------------------------------------ output

    def make_result(self) -> dict:
        plist = []
        for p in self.players:
            d = p.ps.to_dict()
            d.update({"uid": p.uid, "id": p.pdef.id, "name": p.pdef.name, "team": p.team, "role": p.role,
                      "played": self.played_role(p), "number": p.pdef.number})
            plist.append(d)
        tstats = []
        total_poss = self.stats.possession_ticks[0] + self.stats.possession_ticks[1]
        for t in (0, 1):
            ts = {"shots": 0, "shots_on_target": 0, "passes": 0, "passes_ok": 0, "recoveries": 0,
                  "saves": 0, "touches": 0, "goals": self.scores[t], "xg": 0.0, "dribbles": 0}
            for p in self.team_lists[t]:
                ps = p.ps
                ts["shots"] += ps.shots
                ts["shots_on_target"] += ps.shots_on_target
                ts["passes"] += ps.passes()
                ts["passes_ok"] += ps.passes_ok
                ts["recoveries"] += ps.tackles + ps.interceptions
                ts["xg"] += ps.xg
                ts["dribbles"] += ps.dribbles
                ts["saves"] += ps.saves
                ts["touches"] += ps.touches
            ts["possession"] = 50.0 if total_poss == 0 else 100.0 * self.stats.possession_ticks[t] / total_poss
            tstats.append(ts)
        return {"teams": [self.cfg.teams[0].id, self.cfg.teams[1].id], "scores": [self.scores[0], self.scores[1]],
                "shootout": list(self.shootout), "winner": self.winner, "overtime": self.overtime, "events": self.events,
                "players": plist, "team_stats": tstats, "mom": self.mom_uid, "duration": self.cfg.duration,
                "ticks": self.tick, "kickoff_waits": list(self.kickoff_waits), "zones": list(self.zone_ticks),
                "idle": self.idle_ticks}

    def puzzle_layout(self, seed: int):
        """Puzzle (the Live page): every player, keepers too, and the ball at random places, play from the first tick.
        Same draws as the Live viewer's Godot code had (a RandomNumberGenerator seeded with `seed`)."""
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

    # ------------------------------------------------------------ RL interface

    def set_action(self, p, move_idx: int, kick: bool):
        """Discrete action of the trainer: move_idx 0..8 (DIRS, in the player's own frame) plus kick."""
        d = DIRS[move_idx]
        d = complex(d.real * self.attack_dir(p.team), d.imag)
        p.input_dir = normalized(d)
        p.input_kick = kick
