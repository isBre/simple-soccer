"""Opus 5.5 High: a team AI for the Rule Based League that plays as a TEAM. Same senses and limits as every other bot
(perception delay, aim error, positioning noise and decision speed from the player's attributes; identical physics); what is
different is how it thinks:

- Fixed jobs, never a swarm. At any moment exactly one outfield player plays the ball (the one who gets there first). The
  others have a job: when we have the ball, one stays back as the rest defence and the rest take open support spots (pass
  lanes, space, spread over the pitch); when they have it, one covers goal-side behind the presser and the others mark the
  most dangerous receivers. The goalkeeper keeps goal and only leaves his line for balls he wins in his box.
- Every kick is simulated. The ball's path is exactly predictable (a kick adds 5 px/tick, damping 0.99/tick), and so is how
  fast every player can get to any point on it. The ball player scores every kick direction (passes, through balls, shots,
  clearances) by who reaches the ball first and what that is worth, including his own aim error, and compares the best kick
  with carrying the ball on.
- Defending goal-side: the presser approaches the ball from between it and our goal, so a touch or a kick sends it away.
- Finishing: in the opponents' half the carrier drives at goal and shoots like the handmade bots (StyleBot._decide_action with
  this team's style), which converted better than the simulated choice there; the Opus shape stays around him (the simulated
  kicks decide the build-up in our half). A shot from distance that the simulation says the defenders will reach is not taken.
- A ball at a player's feet is hit first time when the kick goes forwards (in the opponents' third only as a pass or a shot),
  and a ball lost high up is counter-pressed by a second player for two seconds.

Plugged in through the style (data/styles/opus_high.json: "brain": "opus"); see soccer/ai/__init__.py."""
import copy
import os
import math

import numpy as np

from ..match import KICK_RANGE, KICK_STRENGTH
from ..rating import shot_xg
from ..vec import INF, clamp, dot, from_angle, lerpf, normalized, rotated
from .rules import StyleBot, TeamBrain, _ball_time, _compensated_dir, intercept

DAMP = 0.99
TS = np.arange(1.0, 151.0, 2.0)                    # ticks after the kick at which the ball path is sampled
QS = (1.0 - DAMP ** TS) / (1.0 - DAMP)             # distance travelled per unit of initial speed
DECAY = DAMP ** TS
N_DIRS = 40                                        # kick directions scanned (9 degrees apart)
# Tuned with tools/tune_opus.py (CMA-ES against 10 trained nets: first run 2026-11-20, second run with the territory / outlet
# terms 2026-11-21; see docs/opus_5_5_high.md, sections 8 and 9).
# position value (pos_value): roughly the chance a possession at that point ends in a goal
VAL0, VALXG, VALPROG = 0.01, 0.405, 0.0615
HOLD_K = 0.316          # carrying the ball on is discounted: most dribbles in the final third end in a loss
WALL_PEN = 0.022        # carrying the ball into the touchline or a corner
RECV_SHOT = 1.5         # a free team-mate near goal is worth this share of his shot's xG
SHOT_READ = 41.6        # px of reach a defender (keeper included) loses reading where a shot goes
KICK_REL = 0.513        # take the kick on offer when it is worth this share of the plan (no waiting for the perfect angle)
PRESSED = 63.5          # px: an opponent this close to the ball = take any kick better than keeping it
FINAL_FROM = 0.149      # share of the half beyond halfway from which the carrier drives at goal and shoots (StyleBot)
BOX_FROM = 0.192        # from here on the most advanced supporter attacks the goal ...
BOX_DEPTH, BOX_Y = 80.5, 0.0    # ... this far from the goal line and from the middle (0 = in front of goal)
ATTACK_NEED_OWN = 29.1  # extra ticks of head start needed before switching to attack deep in our own half
REST_BACK = 319.0       # px the rest defender stays behind the ball
SUPPORT_MIN, SUPPORT_MAX = 94.1, 281.0   # px: support spots not closer to / further from the ball than this
SPACING = 118.0         # px: support spots push each other apart within this distance
COVER_FROM = 1.0        # a cover player drops goal-side when the ball is below this share of the half beyond halfway (1 = always)
COVER_DIST = 126.0      # px the cover stands behind the ball, towards our goal
COVER_OWN = 166.0       # ... and when the ball is in our own third
MARK_GAP_FAR, MARK_GAP_NEAR = 77.7, 31.1  # px a marker stays from a harmless / a dangerous receiver
GUARD_TRIGGER = 141.0   # px: a marker whose spot is this close to the ball near our goal guards the goal mouth instead
POKE_RADIUS = 500.0     # px from our goal within which the presser pokes the ball away when he cannot play it
OUTLET_FROM = -0.639    # ball below this share of the half (negative = our half): the most advanced free player stays up as an outlet (-1 = off)
OUTLET_X = -0.142       # where the outlet waits (share of the half, 0 = halfway line)
TERR = 0.135            # territory: a kick deep in our half that we may lose is worth this x depth x the ground it gains
FIRST_FWD = 0.2         # first time: a ball at an outfield player's feet is hit at once if it would go at least this forward (cos)
FIRST_UPTO = 1.0        # ... up to this share of the half beyond halfway (1 = the whole pitch; -1 = never)
# v5 (2026-11-23, measured against every ladder entry; docs section 11)
FIRST_CLEAR_UPTO = 0.33 # ... but beyond this share of the half only when it is a pass or a shot (2 = always)
CP_FROM = 0.0           # counter-press: ball lost beyond this share of the half (2 = off) ...
CP_TICKS = 120          # ... for this many ticks a second player presses the ball too
SHOT_VETO = 0.35        # finisher: a shot whose clean chance (simulated) is below this is not taken (0 = off) ...
SHOT_VETO_FROM = 150.0  # ... from further than this from goal
BOX2_FROM = 2.0         # deep attack: beyond this share of the half a second runner attacks the far post (2 = off; no gain measured)
BOX2_DEPTH = 60.0       # px from the goal line where the second runner waits
# v6: expected threat measured from play (Opus vs every ladder entry, 492 matches, 443k possession samples, 2026-11-24): the
# chance the team on the ball scores within 10 s, by a logistic model of the shot angle, progress, how many of their outfield
# players are goal-side of the ball and the nearest opponent. Replaces the hand formula in pos_value when XT = 1.
XT = 0
FP_MARGIN = 9.0         # final third: a simulated pass worth this much more than the finisher's dribble / shot is played (9 = off) ...
FP_OK = 0.6             # ... if it arrives with at least this chance ...
FP_FROM = 0.33          # ... beyond this share of the half
SECOND_FROM = 2.0       # attack beyond this share of the half against a deep block: one supporter waits for the second ball (2 = off) ...
SECOND_DEPTH = 210.0    # ... this far from their goal line, on the ball's side, ...
RO = 1                  # final third: the finisher's choice is checked by playing the candidates forward (rollouts; 0 = off) ...
RO_H = 75               # ... this many ticks, in a copy of the match where the opponents are a generic team (RO_STYLE) ...
RO_MARGIN = 0.03        # ... and another candidate replaces the finisher's choice when it scores this much better
RO_STYLE = "balanced"
RO_NEAR = 60.0          # ... only when the carrier is this close to the ball (about to play it)
RO_REPLAN = 0           # a new plan only this many ticks after the last one; in between its winner is kept (0 = every decision)
RO_POSTS = 1            # extra candidates: shots at the near and the far post ...
RO_THRU = (60.0, 120.0, 190.0)  # ... balls into the space this far ahead of each team-mate (through balls) ...
RO_DRIB = (-1.0, -0.5, 0.5, 1.0)  # ... and carrying the ball at these angles (radians) off the line to goal
SECOND_NB = 3           # ... when at least this many of their outfield players are goal-side of the ball
XT_W = (-4.3998, 2.9908, 5.8547, -3.2558, -3.5797, 2.4600, 0.0806, 0.2492, 0.8553, -2.4097, 1.5043, -1.3011)
SUPPORT_EVERY = 6                                  # ticks between two support-spot searches


def _nearest_dist(players, pt):
    return min((abs(o.pos - pt) for o in players), default=INF)


def _sig(x):
    return 1.0 / (1.0 + math.exp(-x)) if x > -60.0 else 0.0


class _Snap:
    """Positions and velocities of a group of players as numpy columns (for the vectorised reach model)."""

    def __init__(self, players, extra_delay=2.0):
        self.players = players
        self.px = np.array([p.pos.real for p in players])[:, None, None]
        self.py = np.array([p.pos.imag for p in players])[:, None, None]
        self.vx = np.array([p.vel.real for p in players])[:, None, None]
        self.vy = np.array([p.vel.imag for p in players])[:, None, None]
        self.rd = np.array([float(p.reaction_delay) + extra_delay for p in players])[:, None, None]


def _deficit(s, xs, ys, t, touch):
    """(players, paths, samples): how far each player is from touching the ball at each sample of each path when it gets
    there (px; <= 0 means he can be there). The player's motion is linear (v <- 0.96 (v + 0.1 u), then x <- x + v): his
    current velocity carries him on (free part) and after his reaction delay he can add up to the full-acceleration
    distance in any direction (forced part: top speed 2.5 px per tick of movement)."""
    coast = 25.0 * (1.0 - 0.96 ** t)[None, None, :]
    dx = xs[None] - (s.px + s.vx * coast)
    dy = ys[None] - (s.py + s.vy * coast)
    dist = np.sqrt(dx * dx + dy * dy)
    te = np.maximum(t[None, None, :] - s.rd, 0.0)
    reach = 2.5 * te - 60.0 * (1.0 - 0.96 ** te)
    return dist - touch - reach


def ball_paths(pd, br, p0, v0s):
    """Ball positions (paths, samples) for kicks of initial velocities v0s from p0, with the side walls and the goal-line
    walls (outside the mouth) bouncing it back at half speed. Returns xs, ys, speed."""
    vx = np.array([v.real for v in v0s])[:, None]
    vy = np.array([v.imag for v in v0s])[:, None]
    xs = p0.real + vx * QS[None, :]
    ys = p0.imag + vy * QS[None, :]
    ly = pd.half_h - br
    ys = np.where(ys > ly, ly - 0.5 * (ys - ly), ys)
    ys = np.where(ys < -ly, -ly - 0.5 * (ys + ly), ys)
    lx = pd.half_w - br
    side = np.abs(ys) > pd.goal_half - 4.0
    xs = np.where(side & (xs > lx), lx - 0.5 * (xs - lx), xs)
    xs = np.where(side & (xs < -lx), -lx - 0.5 * (xs + lx), xs)
    speed = np.sqrt(vx * vx + vy * vy) * DECAY[None, :]
    return xs, ys, speed


def itime(m, p, bpos, bvel):
    """rules.intercept's time, but finite for a ball nobody reaches within its horizon (then: time to its resting spot)."""
    pt, t = intercept(m, p, bpos, bvel)
    if t >= INF:
        t = 160.0 + abs(pt - p.pos) / 2.4
    return t


def pos_value(m, team, pt):
    """How promising it is for `team` to have the ball at pt (roughly: the chance this possession ends in a goal)."""
    pd = m.pitch
    ax = m.attack_dir(team)
    gx = ax * pd.half_w
    xg = shot_xg(pt, gx, pd.goal_half)
    prog = (pt.real * ax / pd.half_w + 1.0) * 0.5
    if XT:
        other = m.brains[1 - team]
        kp = getattr(other, "keeper", None)
        x = pt.real * ax
        nb, dopp = 0, INF
        for o in m.team_lists[1 - team]:
            d = abs(o.pos - pt)
            if d < dopp:
                dopp = d
            if o is not kp and o.pos.real * ax > x:
                nb += 1
        return xt_value(xg, prog, nb, dopp)
    return VAL0 + VALXG * xg + VALPROG * prog * prog


def _clone(m, opp):
    """A copy of the match for a rollout: shared static data is not copied, and team `opp` is played by a generic team
    (RO_STYLE) instead of its own brain / net (Opus does not read the opponents' minds)."""
    from ..data import database
    st = database().styles[RO_STYLE]
    memo = {id(m.cfg): m.cfg, id(m.ev_log): [], id(m.brains[opp]): None}
    for s_ in m.styles:
        memo[id(s_)] = s_
    for p in m.team_lists[opp]:
        memo[id(p.bot_ai)] = None
        memo[id(p.pdef)] = p.pdef
    for p in m.players:
        if hasattr(p, "pdef"):
            memo[id(p.pdef)] = p.pdef
    memo[id(st)] = st
    c = copy.deepcopy(m, memo)
    c._rollout = True
    c.log_events = False
    c.brains[opp] = TeamBrain(opp, st)
    for p in c.team_lists[opp]:
        p.bot_ai = StyleBot(st)
    c.brains[opp].update(c)
    return c


def _set_cand(c, b, cand, err):
    """Give the copy's carrier bot a candidate (kind, kick, aim, mate uid)."""
    kind, kick, aim, mate = cand
    b._kind, b._kick, b._aim = kind, kick, aim
    b._mate = c.by_uid[mate] if mate is not None else None
    b._err = err if kick else 0.0
    b._decided = c.tick


def _play_out(c, team, s0):
    """RO_H ticks of a rollout copy: +1 / -1 for a goal, else the value of the ball for whoever touched it last."""
    for _ in range(RO_H):
        c.step()
        if c.scores[team] > s0[team]:
            return 1.0
        if c.scores[1 - team] > s0[1 - team]:
            return -1.0
    lt = c.last_touch
    if lt is not None and lt.team == team:
        return pos_value(c, team, c.ball_pos)
    return -pos_value(c, 1 - team, c.ball_pos)


# Rollouts in worker processes (live play only: the web app calls use_pool). The answers are the same as in-process; the
# decision tick just takes ~1/n of the time, so a live match does not stall while the finisher thinks.
_POOL = None
_POOL_N = 0


def use_pool(n):
    """Run the finisher's rollouts on n worker processes (0 = in-process). The processes start on first use."""
    global _POOL, _POOL_N
    if _POOL is not None:
        _POOL.shutdown(wait=False, cancel_futures=True)
    _POOL, _POOL_N = None, max(0, int(n))


def _pool():
    global _POOL
    if _POOL is None and _POOL_N > 0:
        import concurrent.futures
        import multiprocessing
        _POOL = concurrent.futures.ProcessPoolExecutor(_POOL_N, mp_context=multiprocessing.get_context("spawn"),
                                                       initializer=_pool_init)
    return _POOL


def realtime():
    """A match played in real time (the web game) has an Opus team: put its rollouts on worker processes, so a decision
    tick does not stall the stream (~45 ms instead of ~150 ms at the worst), and start the workers now. The answers are the
    same either way. Workers: SOCCER_OPUS_WORKERS, else the CPU count minus 2, at most 6."""
    global _REALTIME
    if not _REALTIME:
        _REALTIME = True
        n = os.environ.get("SOCCER_OPUS_WORKERS")
        use_pool(int(n) if n is not None else min(6, max(0, (os.cpu_count() or 1) - 2)))
    pool = _pool()
    if pool is not None:
        for _ in range(_POOL_N):
            pool.submit(_noop)


_REALTIME = False


def _noop():
    return None


def _pool_init():
    try:
        os.nice(5)
    except OSError:
        pass


def _pool_job(blob, team, uid, s0, cands, err):
    """Score candidates on a pickled rollout copy: each one plays out on its own fresh load of it."""
    import pickle
    out = []
    for cand in cands:
        c = pickle.loads(blob)
        _set_cand(c, c.by_uid[uid].bot_ai, cand, err)
        out.append(_play_out(c, team, s0))
    return out


def _scores(m, p, cands, err):
    """Rollout score of each candidate (kind, kick, aim, mate): one copy of the match with the generic opponents, pickled
    once, then loaded fresh for every candidate; on the worker pool when there is one (same answers, less waiting)."""
    import pickle
    team = p.team
    blob = pickle.dumps(_clone(m, 1 - team), protocol=pickle.HIGHEST_PROTOCOL)
    plain = [c[:3] + ((c[3].uid if c[3] is not None else None),) for c in cands]
    s0 = list(m.scores)
    pool = _pool()
    if pool is None:
        return _pool_job(blob, team, p.uid, s0, plain, err)
    n = min(_POOL_N, len(plain))
    futs = [pool.submit(_pool_job, blob, team, p.uid, s0, plain[i::n], err) for i in range(n)]
    scores = [0.0] * len(plain)
    for i, f in enumerate(futs):
        for j, v in enumerate(f.result()):
            scores[i + j * n] = v
    return scores


def xt_value(xg, prog, nb, dopp):
    """The measured expected threat (XT_W): works on floats and on numpy arrays."""
    w = XT_W
    nbn = np.minimum(nb, 4) / 4.0
    free = (nb == 0) * 1.0
    pr = np.minimum(dopp, 120.0) / 120.0
    z = (w[0] + w[1] * xg + w[2] * prog + w[3] * prog * prog + w[4] * nbn + w[5] * nbn * prog + w[6] * free * prog
         + w[7] * pr + w[8] * pr * prog + w[9] * xg * nbn + w[10] * nbn * nbn + w[11] * nbn * prog * prog)
    return 1.0 / (1.0 + np.exp(-z))


class OpusBrain:
    """Team plan for Opus 5.5 High. Exposes the fields other code reads from a team brain (keeper, chasers, carrier,
    has_possession, ...)."""

    def __init__(self, team, style):
        self.team = team
        self.style = style
        self.reset()

    def reset(self):
        self.has_possession = False
        self.opp_possession = False
        self.danger = False
        self.urgency = 0.0
        self.phase = "contest"            # attack / defend / contest
        self.primary = None               # the one player who plays the ball
        self.chasers = []
        self.carrier = None
        self.interceptor = None
        self.intercept_pt = 0j
        self.pass_target = None
        self.pass_tick = -999
        self.pass_kicker = None
        self.marks = {}
        self.keeper = None
        self.targets = {}                 # uid -> off-ball target
        self.jobs = {}                    # uid -> job name (for debugging / scouting)
        self.rest = None
        self.cover = None
        self.striker = None
        self._support_tick = -999
        self._support = {}
        self.t_us = INF
        self.t_them = INF
        self.opp_primary = None
        self.lost_tick = -999
        self.lost_x = 0.0
        self._second = None

    # ------------------------------------------------------------ team plan

    def update(self, m):
        ball, bvel = m.ball_pos, m.ball_vel
        ax = m.attack_dir(self.team)
        pd = m.pitch
        hw = pd.half_w
        mates = m.team_lists[self.team]
        opps = m.team_lists[1 - self.team]
        lt = m.last_touch
        if self.has_possession and lt is not None and lt.team != self.team:
            self.lost_tick = m.tick                   # just lost the ball: where (for the counter-press)
            self.lost_x = ball.real * ax
        self.has_possession = lt is not None and lt.team == self.team
        self.opp_possession = lt is not None and lt.team != self.team
        self.danger = ball.real * -ax > hw * 0.4
        behind = m.scores[1 - self.team] - m.scores[self.team]
        elapsed_frac = 1.0 - m.time_left / max(m.duration, 1.0)
        self.urgency = clamp(behind * 0.5, -1.0, 1.0) * clamp((elapsed_frac - 0.55) / 0.35, 0.0, 1.0)

        # the goalkeeper: the nominal GK (a fixed keeper, as in real football); any bot if there is none
        if self.keeper is None or self.keeper.is_human:
            self.keeper = None
            if len(mates) > 1:
                for sp in mates:
                    if sp.role == "GK" and not sp.is_human:
                        self.keeper = sp
                if self.keeper is None:
                    for sp in mates:
                        if not sp.is_human:
                            self.keeper = sp
        keeper = self.keeper

        # pass in flight: the receiver plays it, unless an opponent clearly gets there first
        if self.pass_target is not None and (m.tick - self.pass_tick > 120 or (lt is not None and lt is not self.pass_kicker)
                                             or self.pass_target.is_human):
            self.pass_target = None

        # who gets to the ball first (true ball state; each player's own perception delay is in intercept())
        t_us, best_us = INF, None
        times = {}
        in_box = ball.real * -ax > hw - pd.box_depth - 20.0 and abs(ball.imag) < pd.box_half + 20.0
        for sp in mates:
            if sp.is_human:
                continue
            t = itime(m, sp, ball, bvel)
            times[sp.uid] = t
            if sp is keeper and not in_box:
                continue
            tt = t - (6.0 if sp is self.primary else 0.0)
            if tt < t_us:
                t_us, best_us = tt, sp
        t_them, best_them = INF, None
        for o in opps:
            t = itime(m, o, ball, bvel)
            if t < t_them:
                t_them, best_them = t, o
        self.t_us, self.t_them, self.opp_primary = t_us, t_them, best_them

        human = None
        for sp in mates:
            if sp.is_human:
                human = sp
        if self.pass_target is not None:
            primary = self.pass_target
            phase = "attack"
        else:
            primary = best_us
            if human is not None and abs(human.pos - ball) < (abs(best_us.pos - ball) + 60.0 if best_us is not None else INF):
                primary = None             # the human is at the ball: leave it to him
            # in our own half the team only switches to attack when the ball is really ours (a clear head start), so a
            # scramble near our goal keeps the defensive shape
            depth = clamp(ball.real * -ax / hw, 0.0, 1.0)
            need = 4.0 + ATTACK_NEED_OWN * depth
            if t_us + need < t_them:
                phase = "attack"
            elif t_them + 4.0 < t_us:
                phase = "defend"
            else:
                phase = "attack" if (self.has_possession and depth < 0.2) else "contest"
        # the keeper only plays the ball in his box when he is the first of all to it
        if primary is keeper and keeper is not None and not (in_box and times.get(keeper.uid, INF) + 2.0 < t_them):
            primary = None
            t2, b2 = INF, None
            for sp in mates:
                if sp is keeper or sp.is_human:
                    continue
                if times[sp.uid] < t2:
                    t2, b2 = times[sp.uid], sp
            primary = b2
        self.primary = primary
        self.phase = phase
        self.chasers = [primary] if primary is not None else []
        self.carrier = primary if phase == "attack" else None
        if human is not None and phase != "defend" and primary is None:
            self.carrier = human
        self.interceptor = None

        # off-ball jobs
        self.targets.clear()
        self.jobs = {}
        self.marks.clear()
        free = [sp for sp in mates if sp is not keeper and sp is not primary and not sp.is_human]
        if phase == "attack":
            self._plan_attack(m, free, ax, ball)
        else:
            self._plan_defend(m, free, ax, ball, best_them)

    def _plan_attack(self, m, free, ax, ball):
        pd = m.pitch
        hw, hh = pd.half_w, pd.half_h
        bx = ball.real * ax
        carrier = self.carrier or self.primary
        # rest defence: the deepest free player stays behind the ball against the counter
        self.rest = None
        if len(free) >= 2:
            rest = min(free, key=lambda sp: (sp.pos.real * ax + (0.0 if sp is self.rest else 30.0) - (60.0 if sp.role == "DEF" else 0.0)))
            self.rest = rest
            rx = clamp(bx - REST_BACK, -hw * 0.78, hw * 0.05)
            ry = clamp(ball.imag * 0.35, -hh * 0.4, hh * 0.4)
            self.targets[rest.uid] = complex(ax * rx, ry)
            self.jobs[rest.uid] = "rest"
            free = [sp for sp in free if sp is not rest]
        if not free:
            return
        self.striker = None
        if bx > hw * BOX_FROM and len(free) >= 2:
            # attacking: the most advanced supporter attacks the goal (rebounds, balls across the box)
            st_ = max(free, key=lambda sp: sp.pos.real * ax + (40.0 if sp is self.striker else 0.0))
            self.striker = st_
            sy = -1.0 if ball.imag > 0.0 else 1.0
            self.targets[st_.uid] = complex(ax * (hw - BOX_DEPTH), sy * BOX_Y)
            self.jobs[st_.uid] = "box"
            free = [sp for sp in free if sp is not st_]
            if bx > hw * BOX2_FROM and free:
                # deep in their third: a second runner attacks the far post (balls across the box, rebounds)
                r2 = max(free, key=lambda sp: sp.pos.real * ax + (40.0 if self.jobs.get(sp.uid) == "box2" else 0.0))
                self.targets[r2.uid] = complex(ax * (hw - BOX2_DEPTH), sy * pd.goal_half * 1.3)
                self.jobs[r2.uid] = "box2"
                free = [sp for sp in free if sp is not r2]
        if bx > hw * SECOND_FROM and free and self._n_behind(m, ax, bx) >= SECOND_NB:
            # second ball against a deep block: blocked shots and clearances come out to the edge of the box
            spt = complex(ax * (hw - SECOND_DEPTH), clamp(ball.imag * 0.5, -hh * 0.4, hh * 0.4))
            sb = min(free, key=lambda sp: abs(sp.pos - spt) - (40.0 if sp is self._second else 0.0))
            self._second = sb
            self.targets[sb.uid] = spt
            self.jobs[sb.uid] = "second"
            free = [sp for sp in free if sp is not sb]
        if m.tick - self._support_tick >= SUPPORT_EVERY or any(sp.uid not in self._support for sp in free):
            self._support_tick = m.tick
            self._support = self._support_spots(m, free, ax, ball, carrier)
        for sp in free:
            self.targets[sp.uid] = self._support.get(sp.uid, sp.pos)
            self.jobs[sp.uid] = "support"

    def _n_behind(self, m, ax, bx):
        """How many of their outfield players are goal-side of the ball (how deep they defend)."""
        kp = getattr(m.brains[1 - self.team], "keeper", None)
        return sum(1 for o in m.team_lists[1 - self.team] if o is not kp and o.pos.real * ax > bx)

    def _support_spots(self, m, free, ax, ball, carrier):
        """Open spots for the supporting players: valuable, reachable by a pass, away from opponents and from each other."""
        pd = m.pitch
        hw, hh = pd.half_w, pd.half_h
        opps = m.team_lists[1 - self.team]
        bx = ball.real * ax
        xs = np.arange(-hw * 0.55, hw * 0.93, 55.0)
        ys = np.arange(-hh * 0.85, hh * 0.86, 55.0)
        gx, gy = np.meshgrid(xs, ys)
        gx = gx.ravel()
        gy = gy.ravel()
        keep = (gx > bx - 260.0) & (gx < bx + 480.0)
        gx, gy = gx[keep], gy[keep]
        wx = gx * ax                                        # world x
        # value of having the ball there
        gxw = ax * hw
        dxg = np.maximum(np.abs(gxw - wx), 1.0)
        ang = np.abs(np.arctan2(pd.goal_half - gy, dxg) - np.arctan2(-pd.goal_half - gy, dxg))
        xg = np.clip((ang / 1.8) ** 1.6 * 0.75, 0.01, 0.8)
        prog = (gx / hw + 1.0) * 0.5
        # space: distance to the nearest opponent, and how open the lane from the ball is
        ox = np.array([o.pos.real for o in opps])[:, None]
        oy = np.array([o.pos.imag for o in opps])[:, None]
        d_opp = np.sqrt((ox - wx[None]) ** 2 + (oy - gy[None]) ** 2).min(axis=0)
        if XT:
            other = m.brains[1 - self.team]
            kp = getattr(other, "keeper", None)
            oxo = np.array([o.pos.real * ax for o in opps if o is not kp])[:, None]
            nb = (oxo > gx[None]).sum(axis=0) if len(oxo) else np.zeros_like(gx)
            val = xt_value(xg, prog, nb, d_opp) / 0.35
        else:
            val = (VAL0 + VALXG * xg + VALPROG * prog * prog) / 0.35
        lx, ly = wx - ball.real, gy - ball.imag
        l2 = np.maximum(lx * lx + ly * ly, 1.0)
        tt = np.clip(((ox - ball.real) * lx[None] + (oy - ball.imag) * ly[None]) / l2[None], 0.0, 1.0)
        lane = np.sqrt((ox - (ball.real + lx[None] * tt)) ** 2 + (oy - (ball.imag + ly[None] * tt)) ** 2).min(axis=0)
        dball = np.sqrt(l2)
        score = val * 1.6 + np.minimum(d_opp, 130.0) / 130.0 * 0.22 + np.minimum(lane, 70.0) / 70.0 * 0.22
        score -= np.where(dball < SUPPORT_MIN, (SUPPORT_MIN - dball) / SUPPORT_MIN * 0.4, 0.0)            # not on top of the carrier
        score -= np.where(dball > SUPPORT_MAX, (dball - SUPPORT_MAX) / 200.0 * 0.4, 0.0)            # but within passing range
        score -= np.where(np.abs(gy) > hh - 40.0, 0.08, 0.0)
        taken = [ball]
        for r_ in (self.rest, self.striker):
            if r_ is not None:
                taken.append(self.targets.get(r_.uid, r_.pos))
        out = {}
        # the most advanced role picks first; each spot pushes the others away (spread, no clumping)
        order = sorted(free, key=lambda sp: -sp.pos.real * ax)
        for sp in order:
            s = score.copy()
            for tk in taken:
                d = np.sqrt((wx - tk.real) ** 2 + (gy - tk.imag) ** 2)
                s -= np.where(d < SPACING, (SPACING - d) / SPACING * 0.6, 0.0)
            dme = np.sqrt((wx - sp.pos.real) ** 2 + (gy - sp.pos.imag) ** 2)
            s -= dme * 0.0006
            prev = self._support.get(sp.uid)
            if prev is not None:
                s -= np.where(np.sqrt((wx - prev.real) ** 2 + (gy - prev.imag) ** 2) < 40.0, -0.05, 0.0)
            i = int(np.argmax(s))
            pt = complex(wx[i], gy[i])
            out[sp.uid] = pt
            taken.append(pt)
        return out

    def _plan_defend(self, m, free, ax, ball, opp_ball):
        pd = m.pitch
        hw, hh = pd.half_w, pd.half_h
        own_goal = complex(-ax * hw, 0.0)
        opps = m.team_lists[1 - self.team]
        other_keeper = m.brains[1 - self.team].keeper if m.brains[1 - self.team] is not None else None
        bx = ball.real * ax
        self.cover = None
        if (free and bx > hw * CP_FROM and self.lost_x > hw * CP_FROM and m.tick - self.lost_tick < CP_TICKS
                and self.primary is not None):
            # counter-press: just lost the ball high up, the nearest free player presses it too for a moment (the ball
            # is won back before they can play out); the others keep their jobs
            p2 = min(free, key=lambda sp: abs(sp.pos - ball) - (30.0 if self.jobs.get(sp.uid) == "press2" else 0.0))
            self.targets[p2.uid] = ball
            self.jobs[p2.uid] = "press2"
            free = [sp for sp in free if sp is not p2]
        if OUTLET_FROM > -1.0 and bx < hw * OUTLET_FROM and len(free) >= 3:
            # outlet: deep in our half the most advanced free player stays up on the far side, so a clearance finds someone
            out = max(free, key=lambda sp: sp.pos.real * ax + (40.0 if self.jobs.get(sp.uid) == "outlet" else 0.0))
            sy = -1.0 if ball.imag > 0.0 else 1.0
            self.targets[out.uid] = complex(ax * hw * OUTLET_X, sy * hh * 0.45)
            self.jobs[out.uid] = "outlet"
            free = [sp for sp in free if sp is not out]
        # cover: goal-side behind the presser, between the ball and our goal
        if free and bx < hw * COVER_FROM:
            to_goal = own_goal - ball
            dg = abs(to_goal)
            cdist = COVER_DIST if bx > -hw / 3.0 else COVER_OWN     # in our own third the cover stays close: the second ball
            cpt = ball + to_goal / max(dg, 1.0) * min(cdist, dg * 0.45)
            cover = min(free, key=lambda sp: abs(sp.pos - cpt) - (40.0 if sp is self.cover else 0.0))
            self.cover = cover
            self.targets[cover.uid] = cpt
            self.jobs[cover.uid] = "cover"
            free = [sp for sp in free if sp is not cover]
        if not free:
            return
        # markers: the most dangerous receivers (not the man on the ball, not their keeper)
        threats = []
        for o in opps:
            if o is opp_ball or (o is other_keeper and len(opps) > 1):
                continue
            dang = pos_value(m, 1 - self.team, o.pos) + 0.15 * clamp(1.0 - abs(o.pos - ball) / 500.0, 0.0, 1.0)
            threats.append((dang, o))
        threats.sort(key=lambda th: -th[0])
        guard = []
        for dang, o in threats:
            if not free:
                break
            # stand goal-side of him, a bit towards the ball (to cut the pass), closer the more dangerous he is
            to_goal = normalized(own_goal - o.pos)
            to_ball = normalized(ball - o.pos)
            gap = lerpf(MARK_GAP_FAR, MARK_GAP_NEAR, clamp(dang / 0.35, 0.0, 1.0))
            spot = o.pos + normalized(to_goal * 1.0 + to_ball * 0.6) * gap
            best = min(free, key=lambda sp: abs(sp.pos - spot) - (30.0 if self.marks.get(sp.slot) is o else 0.0))
            free.remove(best)
            if abs(spot - ball) < GUARD_TRIGGER and abs(ball - own_goal) < 330.0:
                # his man is already in the scramble at the ball: do not pile in. Guard the far half of the goal mouth
                # (the keeper takes the near post), or hold the edge of the box for the clearance
                if not guard:
                    sy = -1.0 if ball.imag > 0.0 else 1.0
                    self.targets[best.uid] = complex(own_goal.real + ax * 26.0, sy * pd.goal_half * 0.4)
                    self.jobs[best.uid] = "guard"
                    guard.append(best)
                else:
                    self.targets[best.uid] = complex(own_goal.real + ax * 190.0, clamp(ball.imag * 0.4, -hh * 0.5, hh * 0.5))
                    self.jobs[best.uid] = "zone"
                continue
            self.marks[best.slot] = o
            self.targets[best.uid] = spot
            self.jobs[best.uid] = "mark"
        for sp in free:                           # nobody left to mark: hold a compact zone between ball and goal
            fx = clamp(bx - 200.0, -hw * 0.8, hw * 0.3)
            self.targets[sp.uid] = complex(ax * fx, clamp(ball.imag * 0.5 + sp.home.imag * hh * 0.5, -hh * 0.8, hh * 0.8))
            self.jobs[sp.uid] = "zone"


class OpusBot(StyleBot):
    """One Opus player: the brain gives the job, the bot executes it with the player's own senses and skill."""

    def __init__(self, style):
        super().__init__(style)
        self._recv = None
        self._table = None                 # last decision: (directions, values, kinds, receivers, hold value)
        self._choice = None                # direction chosen at the last decision
        self._pred = None                  # (kind, predicted success, value) of the last kick (calibration)

    def decide(self, m, p):
        p.input_kick = False
        p.kick_intent = ""
        p.input_dir = 0j
        brain = m.brains[p.team]
        bpos = m.ball_at(p.reaction_delay)
        bold = m.ball_at(p.reaction_delay + 4)
        bvel = (bpos - bold) / 4.0
        if m.kickoff_active:
            if p is m.kickoff_taker:
                if m.tick >= m.kickoff_go:
                    p.input_kick = True
                    p.kick_intent = "pass"
            else:
                self._arrive(p, p.spawn)
            return
        if p is brain.primary:
            if p is brain.keeper or brain.phase != "defend" or brain.pass_target is p:
                self._go_for_ball(m, p, brain, bpos, bvel)
            else:
                self._press(m, p, brain, bpos, bvel)
        elif p is brain.keeper and len(m.team_lists[p.team]) > 1:
            self._keeper(m, p, bpos, bvel)
        elif brain.jobs.get(p.uid) == "press2":
            self._press(m, p, brain, bpos, bvel)
        else:
            self._move_off_ball(m, p, brain)
        if not p.input_kick and p is not brain.keeper:
            self._first_time(m, p)
        self._avoid_human(m, p)

    def _first_time(self, m, p):
        """A ball at an outfield player's feet is hit first time whenever the kick it gives right now goes forwards, instead
        of being bumped on with the body or circled for a better angle. Against a press a body touch almost always hands
        the ball straight back (measured: of ~55 balls won in our own third per match, ~43 were lost again within half a
        second, mostly without a kick). Applies to every outfield player, not only the ball player: the ball often lands
        on a marker or the cover in a scramble."""
        ax = m.attack_dir(p.team)
        if m.ball_pos.real * ax > m.pitch.half_w * FIRST_UPTO:
            return
        to = m.ball_pos - p.pos
        d = abs(to)
        if d - p.radius - m.ball_r >= KICK_RANGE:
            return
        n = to / max(d, 1e-6)
        u = normalized(m.ball_vel + n * KICK_STRENGTH)
        if u.real * ax < FIRST_FWD:
            return
        # what the hit is (pass / shot / clearance) comes from the same simulation as every other kick; a pass tells the
        # receiver to meet the ball
        pd = m.pitch
        shot = 0
        if u.real * ax > 0.05:
            ty = m.ball_pos.imag + u.imag * (ax * pd.half_w - m.ball_pos.real) / u.real
            shot = 1 if abs(ty) < pd.goal_half - m.ball_r else 0
        _, kind_of, recv_of, _ = self._evaluate(m, p, m.ball_pos, m.ball_vel, 0.0, n, [u], [shot])
        if kind_of[0] == "clear" and m.ball_pos.real * ax > m.pitch.half_w * FIRST_CLEAR_UPTO:
            return                             # up the pitch a hit to nobody only gives the ball back: play it properly
        p.input_kick = True
        p.kick_intent = kind_of[0]
        if kind_of[0] == "pass" and recv_of[0] is not None:
            brain = m.brains[p.team]
            brain.pass_target = recv_of[0]
            brain.pass_kicker = p
            brain.pass_tick = m.tick

    # ------------------------------------------------------------ off the ball

    def _move_off_ball(self, m, p, brain):
        target = brain.targets.get(p.uid, p.pos)
        if m.tick - self._noise_tick > 90:
            self._noise = complex(p.rng.gauss(0.0, 1.0), p.rng.gauss(0.0, 1.0)) * p.pos_noise * 0.5
            self._noise_tick = m.tick
        target += self._noise
        pd = m.pitch
        target = complex(clamp(target.real, -pd.half_w + 18.0, pd.half_w - 18.0), clamp(target.imag, -pd.half_h + 18.0, pd.half_h - 18.0))
        job = brain.jobs.get(p.uid, "")
        if job in ("cover", "mark", "guard") and abs(target - p.pos) > 60.0:
            self._chase(p, target)             # defensive jobs: get there fast
        else:
            self._arrive(p, target)

    # ------------------------------------------------------------ pressing

    def _press(self, m, p, brain, bpos, bvel):
        """Opponent on the ball: close him down from the goal side, so every touch sends the ball away from our goal;
        poke it away when in reach and the poke does not point at our own goal."""
        ax = m.attack_dir(p.team)
        pd = m.pitch
        own_goal = complex(-ax * pd.half_w, 0.0)
        bp, t = intercept(m, p, bpos, bvel)
        gs = normalized(own_goal - bp)
        rel = p.pos - bp
        reach = p.radius + m.ball_r
        if dot(rel, gs) < reach * 0.5 and abs(rel) > reach + 4.0:
            # not goal-side yet: run round the ball to the goal side (never through it towards our goal)
            side = 1.0 if (rel.real * gs.imag - rel.imag * gs.real) < 0.0 else -1.0
            perp = complex(-gs.imag, gs.real) * side
            target = bp + gs * (reach + 12.0) + perp * (reach + 10.0) * clamp(1.0 - dot(normalized(rel), gs), 0.0, 1.0)
        else:
            target = bp - normalized(rel) * 6.0 if abs(rel) > 1.0 else bp
        self._chase(p, target)
        to_ball = m.ball_pos - p.pos
        dist = abs(to_ball)
        if dist - reach < KICK_RANGE:
            n = normalized(to_ball)
            if dot(n, normalized(own_goal - m.ball_pos)) < 0.2:
                # in reach and it would go away from our goal: decide on a real ball play if there is time, else poke
                self._go_for_ball(m, p, brain, bpos, bvel)
                # a blind poke usually just gives the ball back: only near our own goal, to get it away from danger
                if not p.input_kick and abs(m.ball_pos - own_goal) < POKE_RADIUS:
                    p.input_kick = True
                    p.kick_intent = "clear"
                    self._pred = ("poke", 0.0, 0.0)

    # ------------------------------------------------------------ on the ball

    def _go_for_ball(self, m, p, brain, bpos, bvel):
        if bpos.real * m.attack_dir(p.team) > m.pitch.half_w * FINAL_FROM and p is not brain.keeper:
            # final third: drive at goal and shoot inside the style's range (the direct finishing of the rule bots,
            # StyleBot._decide_action), with the Opus team shape around the carrier
            brain.chasers = [p]
            StyleBot._go_for_ball(self, m, p, brain, bpos, bvel)
            if p.input_kick and p.kick_intent == "pass":
                brain.pass_kicker = p          # the pass stays live until someone else touches the ball
            return
        bp, t = intercept(m, p, bpos, bvel)
        self._icp_t = min(t, 160.0)
        self._bv_contact = bvel * (0.99 ** self._icp_t)
        if m.tick - self._decided > p.think_ticks:
            self._decide(m, p, brain, bp)
            self._decided = m.tick
        if self._icp_t > 10.0 and abs(bvel) > 1.0:
            # a moving ball still some way off: first get onto its path and meet it (lining up comes later)
            to = bp - p.pos
            if abs(to) > 14.0:
                p.input_dir = normalized(to)
            else:
                self._arrive(p, bp)
        else:
            # line up behind the ball for the planned kick; the kick itself is always decided by _kick_now on the exact
            # direction the contact would give (the line-up tolerance alone could send it ~18 degrees off)
            planned = self._kick
            self._kick = False
            self._play_ball(m, p, brain, bp)
            self._kick = planned
        if not p.input_kick:
            self._kick_now(m, p)
        if p.input_kick and self._kind == "pass" and self._recv is not None:
            brain.pass_target = self._recv
            brain.pass_kicker = p
            brain.pass_tick = m.tick

    def _decide_action(self, m, p, brain, bp):
        """The finisher's choice (StyleBot), with one check of our own: a shot from distance that the simulation says the
        defenders will reach (clean chance below SHOT_VETO) is not taken; the carrier keeps the ball and goes on."""
        StyleBot._decide_action(self, m, p, brain, bp)
        self._veto(m, p, bp)
        if FP_MARGIN < 9.0 and self._kind in ("dribble", "shoot"):
            self._final_pass(m, p, brain, bp)
        if RO and not getattr(m, "_rollout", False) and abs(p.pos - bp) < RO_NEAR:
            self._rollout_choice(m, p, brain, bp)

    # ------------------------------------------------------------ rollouts

    def _rollout_choice(self, m, p, brain, bp):
        """Play each candidate (the finisher's choice, a shot, a dribble at goal, a pass to each team-mate in range) RO_H
        ticks forward in a copy of the match. In the copy our team plays as Opus and the opponents as a generic team (we do
        not know how they think, only where they are); the outcome is a goal (+1 / -1) or the value of the ball for whoever
        has it at the end. Another candidate replaces the finisher's choice only when it does clearly better."""
        lp = getattr(self, "_last_plan", None)
        if RO_REPLAN and lp is not None and m.tick - lp[0] <= RO_REPLAN:
            if lp[1] is not None:                   # the plan's winner holds: no new rollouts yet
                kind, kick, aim, uid = lp[1]
                self._kind, self._kick, self._aim = kind, kick, aim
                self._mate = m.by_uid.get(uid) if uid is not None else None
                self._err = p.rng.gauss(0.0, p.err_finish if kind == "shoot" else p.err_pass) if kick else 0.0
            return
        cands = self._ro_cands(m, p, brain, bp)
        if len(cands) < 2:
            return
        err = self._err
        scores = _scores(m, p, cands, err)
        best = max(range(len(cands)), key=lambda i: scores[i])
        self._last_plan = (m.tick, None)
        if best != 0 and scores[best] > scores[0] + RO_MARGIN:
            kind, kick, aim, mate = cands[best]
            self._kind, self._kick, self._aim, self._mate = kind, kick, aim, mate
            self._err = p.rng.gauss(0.0, p.err_finish if kind == "shoot" else p.err_pass) if kick else 0.0
            self._last_plan = (m.tick, (kind, kick, aim, mate.uid if mate is not None else None))

    def _ro_cands(self, m, p, brain, bp):
        """The candidates: this bot's current choice first, then shots, dribbles, passes to feet and into space."""
        ax = m.attack_dir(p.team)
        pd = m.pitch
        goal = complex(ax * pd.half_w, 0.0)
        cands = [(self._kind, self._kick, self._aim, self._mate)]
        if self._kind != "shoot" and abs(bp - goal) < 420.0:
            cands.append(("shoot", True, self._shot_eval(m, p, bp, goal, ax)[0], None))
        if self._kind != "dribble":
            cands.append(("dribble", False, self._dribble_aim(m, p, bp, goal), None))
        if RO_POSTS and abs(bp - goal) < 420.0:
            gh = pd.goal_half - 14.0
            gh = max(gh - min(gh * 0.85, 1.5 * p.err_finish * abs(bp - goal)), 12.0)
            for y in (-gh, gh):
                cands.append(("shoot", True, complex(goal.real + ax * 10.0, y), None))
        for off in RO_DRIB:
            dr = rotated(normalized(goal - bp), off)
            q2 = bp + dr * 120.0
            if abs(q2.imag) < pd.half_h - 25.0:
                cands.append(("dribble", False, bp + dr * 400.0, None))
        for q in m.team_lists[p.team]:
            if q is p or q is brain.keeper:
                continue
            dist = abs(bp - q.pos)
            if q is not self._mate and 40.0 < dist < 380.0:
                aim = q.pos + q.vel * min(_ball_time(dist), 40.0) * 0.8
                aim = complex(clamp(aim.real, -pd.half_w + 15.0, pd.half_w - 15.0), clamp(aim.imag, -pd.half_h + 15.0, pd.half_h - 15.0))
                cands.append(("pass", True, aim, q))
            for lead in RO_THRU:
                aim = q.pos + complex(ax * lead, 0.0)
                if abs(aim.real) > pd.half_w - 20.0 or (aim.real - bp.real) * ax < 20.0:
                    continue
                if 40.0 < abs(aim - bp) < 420.0:
                    cands.append(("pass", True, aim, q))
        return cands

    def _final_pass(self, m, p, brain, bp):
        """The finisher dribbles or shoots; when the simulation finds a pass that is clearly worth more (a team-mate free
        in a better spot: the cut-back, the ball across the box), play the pass instead."""
        ax = m.attack_dir(p.team)
        pd = m.pitch
        if bp.real * ax < pd.half_w * FP_FROM:
            return
        keeper = brain.keeper
        approach = normalized(bp - p.pos) if abs(bp - p.pos) > 1.0 else complex(ax, 0.0)
        dirs = [from_angle(2.0 * math.pi * k / N_DIRS) for k in range(N_DIRS)]
        for q in m.team_lists[p.team]:
            if q is not p and q is not keeper and abs(q.pos - bp) > 40.0:
                dirs.append(normalized(q.pos + q.vel * 12.0 - bp))
        vals3, kind_of, recv_of, ok3 = self._evaluate(m, p, bp, self._bv_contact, self._icp_t, approach, dirs, [0] * len(dirs))
        best_i, best_v = -1, -INF
        for i in range(len(dirs)):
            if kind_of[i] == "pass" and recv_of[i] is not None and recv_of[i] is not keeper and float(ok3[i]) >= FP_OK \
                    and float(vals3[i]) > best_v:
                best_i, best_v = i, float(vals3[i])
        if best_i < 0:
            return
        if self._kind == "shoot":
            cur = float(self._evaluate(m, p, bp, self._bv_contact, self._icp_t, approach, [normalized(self._aim - bp)], [1])[0][0])
        else:
            cur = self._carry_value(m, p, bp, ax)[0]
        if best_v > cur + FP_MARGIN:
            d = dirs[best_i]
            self._kind = "pass"
            self._kick = True
            self._mate = recv_of[best_i]
            self._aim = bp + d * 400.0
            self._err = p.rng.gauss(0.0, p.err_pass)

    def _veto(self, m, p, bp):
        if self._kind != "shoot" or SHOT_VETO <= 0.0:
            return
        ax = m.attack_dir(p.team)
        goal = complex(ax * m.pitch.half_w, 0.0)
        if abs(bp - goal) < SHOT_VETO_FROM or _nearest_dist(m.team_lists[1 - p.team], bp) < 40.0:
            return                             # close in, or about to lose it anyway: shoot
        approach = normalized(bp - p.pos) if abs(bp - p.pos) > 1.0 else complex(ax, 0.0)
        d = normalized(self._aim - bp)
        _, _, _, ok3 = self._evaluate(m, p, bp, self._bv_contact, self._icp_t, approach, [d], [1])
        if float(ok3[0]) < SHOT_VETO:
            self._kind = "dribble"
            self._kick = False
            self._err = 0.0
            self._aim = self._dribble_aim(m, p, bp, goal)

    def _evaluate(self, m, p, bp, vc, t0, approach, dirs, kinds):
        """Value of kicking the ball (at bp, moving at vc when the kick lands, t0 ticks from now) in each direction: the
        ball path is simulated for three aim samples (-1, 0, +1 standard deviation of this player's aim error), and for each
        path it is decided who touches the ball first and what that is worth. Returns (values, kinds, receivers, ok)."""
        team = p.team
        ax = m.attack_dir(team)
        pd = m.pitch
        br = m.ball_r
        mates = [q for q in m.team_lists[team] if q is not p]
        opps = m.team_lists[1 - team]
        err = max(p.err_pass, 0.02)
        errs = max(p.err_finish, 0.02)
        v0s = []
        for i, d in enumerate(dirs):
            e = errs if kinds[i] == 1 else err
            for s in (-1.0, 0.0, 1.0):
                n = _compensated_dir(rotated(d, s * e), vc)
                v0s.append(vc + n * KICK_STRENGTH)
        xs, ys, _ = ball_paths(pd, br, bp, v0s)
        # time the kicker needs to line up behind the ball for each direction
        tk = np.repeat(np.array([28.0 * (1.0 - dot(approach, d)) for d in dirs]), 3)[:, None]
        tt = TS + min(t0, 40.0) * 0.7 + 2.0
        far = np.full((1,) + xs.shape, 1e9)
        dm = _deficit(_Snap(mates), xs, ys, tt, 15.0) if mates else far      # (mates, paths, T)
        do = _deficit(_Snap(opps), xs, ys, tt, 24.0) if opps else far        # (opps, paths, T)
        if not mates:
            mates = [p]
        keeper = m.brains[team].keeper
        for k, q in enumerate(mates):
            if q is keeper and keeper is not p:
                # the keeper only receives inside his own box (he does not leave his goal for a back-pass)
                box = (xs * -ax > pd.half_w - pd.box_depth) & (np.abs(ys) < pd.box_half)
                dm[k] = np.where(box, dm[k], 1e9)
        dm = dm + 2.4 * tk[None]                              # lining up costs the kicker's side time ...
        do = do - 1.2 * tk[None]                              # ... and gives the opponents time to close in
        T = TS.shape[0]
        reach_m = dm <= 0.0
        km = np.where(reach_m.any(axis=2), reach_m.argmax(axis=2), T)    # first sample a mate can be there
        reach_o = do <= 0.0
        ko = np.where(reach_o.any(axis=2), reach_o.argmax(axis=2), T)
        km_best = km.min(axis=0)
        who_m = km.argmin(axis=0)
        ko_best = ko.min(axis=0)
        n_paths = xs.shape[0]
        cross = (xs * ax > pd.half_w + br) & (np.abs(ys) < pd.goal_half - 2.0)
        kc = np.where(cross.any(axis=1), cross.argmax(axis=1), T)
        # a path that runs over our OWN goal line in or near the mouth is never an option
        own = ((xs * -ax > pd.half_w - br - 4.0) & (np.abs(ys) < pd.goal_half + 30.0)).any(axis=1)
        goal = complex(ax * pd.half_w, 0.0)
        # rebound chances: our players (not the kicker) close to their goal
        n_box = sum(1 for q in mates if q is not keeper and abs(q.pos - goal) < 220.0)
        rebound = 0.04 + 0.05 * min(n_box, 2)
        vals = np.zeros(n_paths)
        oks = np.zeros(n_paths)
        for j in range(n_paths):
            i = j // 3
            if own[j]:
                vals[j] = -1.0
                continue
            if kc[j] < T and kc[j] <= km_best[j] + 1:
                # a shot: the defenders (keeper included) need a few ticks to read where it goes (SHOT_READ px less
                # reach). A touch near the goal is a save that often leaves a rebound for our players in the box.
                marg = float(do[:, j, :kc[j] + 1].min()) + SHOT_READ
                clean = _sig((marg - 2.0) / 7.0)
                o = ko_best[j]
                if o < kc[j] and abs(complex(xs[j, o], ys[j, o]) - goal) > 140.0:
                    # blocked well before the goal: it is a lost ball out there
                    fail = -pos_value(m, 1 - team, complex(xs[j, o], ys[j, o]))
                else:
                    fail = rebound
                oks[j] = clean
                vals[j] = clean * 0.97 + (1.0 - clean) * fail
                continue
            if kinds[i] == 1:
                vals[j] = -0.02
                continue
            a, o = km_best[j], ko_best[j]
            if a >= T and o >= T:
                e = complex(xs[j, -1], ys[j, -1])             # nobody reaches it before it stops: a loose ball there
                vals[j] = 0.3 * pos_value(m, team, e) - 0.3 * pos_value(m, 1 - team, e)
                continue
            if a < o:
                q = mates[who_m[j]]
                c = complex(xs[j, a], ys[j, a])
                space = float(do[:, j, a].min())              # how far the nearest opponent still is at the reception
                v = pos_value(m, team, c) * (0.55 + 0.45 * _sig((space - 25.0) / 25.0))
                # a free team-mate near goal: the pass is worth the shot it sets up (a cut-back, a ball across the box)
                v = max(v, RECV_SHOT * shot_xg(c, goal.real, pd.goal_half) * _sig((space - 25.0) / 12.0))
                ok = _sig(((o - a) * 2.0 - 6.0) / 5.0)
                if q is keeper:
                    v *= 0.6
                oks[j] = ok
                vals[j] = ok * v - (1.0 - ok) * pos_value(m, 1 - team, c)
            else:
                vals[j] = -pos_value(m, 1 - team, complex(xs[j, o], ys[j, o]))
        if TERR > 0.0:
            # territory: deep in our half, getting the ball away from our goal is worth something in itself, even if it is lost
            # out there (against a high press the alternative is losing it at the edge of our box)
            depth = clamp(0.5 - bp.real * ax / pd.half_w, 0.0, 1.0)
            if depth > 0.0:
                first = np.minimum(np.minimum(km_best, ko_best), T - 1)
                xe = xs[np.arange(n_paths), first] * ax
                gain = np.clip((xe - bp.real * ax) / pd.half_w, -1.0, 1.0)
                vals = np.where(own | (kc < T), vals, vals + TERR * depth * gain)
        w = np.array([0.25, 0.5, 0.25])
        vals3 = vals.reshape(-1, 3) @ w
        ok3 = oks.reshape(-1, 3) @ w
        kind_of, recv_of = [], []
        for i in range(len(dirs)):
            j = i * 3 + 1
            is_shot = kinds[i] == 1 or kc[j] < T
            kind_of.append("shoot" if is_shot else ("pass" if km_best[j] < ko_best[j] else "clear"))
            recv_of.append(mates[who_m[j]] if km_best[j] < ko_best[j] else None)
        return vals3, kind_of, recv_of, ok3

    def _decide(self, m, p, brain, bp):
        """Score every kick (direction x who gets there first x what it is worth) and carrying the ball; pick the best."""
        team = p.team
        ax = m.attack_dir(team)
        pd = m.pitch
        br = m.ball_r
        approach = normalized(bp - p.pos) if abs(bp - p.pos) > 1.0 else complex(ax, 0.0)
        self._recv = None
        # candidate directions: a fan of directions, straight at each team-mate, and at points of the goal mouth
        dirs, kinds = [], []
        for k in range(N_DIRS):
            dirs.append(from_angle(2.0 * math.pi * k / N_DIRS))
            kinds.append(0)
        for q in m.team_lists[team]:
            if q is not p and abs(q.pos - bp) > 40.0:
                dirs.append(normalized(q.pos + q.vel * 12.0 - bp))
                kinds.append(0)
        gx = ax * (pd.half_w + 20.0)
        gh = pd.goal_half - br - 6.0
        for k in range(9):
            dirs.append(normalized(complex(gx, (k - 4.0) / 4.0 * gh) - bp))
            kinds.append(1)
        vals3, kind_of, recv_of, ok3 = self._evaluate(m, p, bp, self._bv_contact, self._icp_t, approach, dirs, kinds)
        best_i = int(np.argmax(vals3))
        best_v = float(vals3[best_i])
        # keep the previous plan unless something is clearly better (no dithering around the ball)
        if self._choice is not None:
            for i, d in enumerate(dirs):
                if dot(d, self._choice) > 0.995 and vals3[i] > best_v - 0.03:
                    best_i, best_v = i, float(vals3[i])
                    break
        hold_v, hold_aim = self._carry_value(m, p, bp, ax)
        self._table = (best_v, hold_v, m.tick)
        bias = 0.004 if kinds[best_i] == 0 else 0.0           # a team that passes: prefer the pass when it is as good
        if best_v + bias > hold_v:
            d = dirs[best_i]
            self._choice = d
            self._kind = kind_of[best_i]
            self._kick = True
            self._aim = bp + d * 400.0
            self._err = p.rng.gauss(0.0, p.err_finish if self._kind == "shoot" else p.err_pass)
            if self._kind == "pass":
                self._recv = recv_of[best_i]
            return
        self._choice = None
        self._kind = "dribble"
        self._kick = False
        self._aim = hold_aim
        self._err = 0.0

    def _kick_now(self, m, p):
        """In reach of the ball: the direction a kick would send it RIGHT NOW (from the contact normal and the ball's own
        speed), evaluated fresh. Take it when it is about as good as the plan and better than keeping the ball: a one-touch
        pass or shot instead of circling the ball while the opponents close in."""
        tb = self._table
        if tb is None or m.tick - tb[2] > 30:
            return
        to_ball = m.ball_pos - p.pos
        dist = abs(to_ball)
        if dist - p.radius - m.ball_r >= KICK_RANGE:
            return
        n = normalized(to_ball)
        u = normalized(m.ball_vel + n * KICK_STRENGTH)
        ax = m.attack_dir(p.team)
        pd = m.pitch
        # does it head into the goal mouth?
        shot = 0
        if u.real * ax > 0.05:
            ty = m.ball_pos.imag + u.imag * (ax * pd.half_w - m.ball_pos.real) / u.real
            shot = 1 if abs(ty) < pd.goal_half - m.ball_r else 0
        # the kick goes exactly along the contact normal plus the ball's velocity: evaluate without aim compensation
        vals3, kind_of, recv_of, ok3 = self._evaluate(m, p, m.ball_pos, m.ball_vel, 0.0, n, [u], [shot])
        v = float(vals3[0])
        best_v, hold_v, _ = tb
        # waiting for the perfect angle lets the defenders close in: take a kick that is clearly better than keeping the
        # ball when it is close to the plan, or straight away when an opponent is already at the ball
        pressed = _nearest_dist(m.team_lists[1 - p.team], m.ball_pos) < PRESSED
        if v > hold_v + 0.01 and (v >= best_v - 0.04 or v >= KICK_REL * best_v or pressed):
            p.input_kick = True
            self._kind = kind_of[0]
            p.kick_intent = self._kind
            self._recv = recv_of[0] if self._kind == "pass" else None
            self._pred = (self._kind, float(ok3[0]), v)
            self._choice = None

    def _carry_value(self, m, p, bp, ax):
        """Value of keeping the ball and carrying it: for headings all round, the value of the spot 70 px on, times the
        chance we are still first to the ball there. Turning the ball costs time (the carrier has to get round it first),
        so a carrier facing the wrong way shields it sideways or backwards instead of dragging it round. Running the ball
        into the touchline or a corner is a dead end."""
        team = p.team
        pd = m.pitch
        opps = m.team_lists[1 - team]
        goal = complex(ax * pd.half_w, 0.0)
        approach = normalized(bp - p.pos) if abs(bp - p.pos) > 1.0 else complex(ax, 0.0)
        base = math.atan2((goal - bp).imag, (goal - bp).real)
        best_v, best_aim = -INF, goal
        for k in range(16):
            off = (k - 8) * (math.pi / 8.0)
            dr = from_angle(base + off)
            q = bp + dr * 70.0
            if abs(q.imag) > pd.half_h - 22.0 or abs(q.real) > pd.half_w - 18.0:
                continue
            turn = 28.0 * (1.0 - dot(approach, dr))
            t_me = abs(q - p.pos) / 2.1 + 4.0 + turn
            t_op = INF
            for o in opps:
                oq = o.pos + o.vel * 6.0
                t_op = min(t_op, max(abs(q - oq) - 20.0, 0.0) / 2.4 + o.reaction_delay * 0.5)
            keep = _sig((t_op - t_me - 4.0) / 6.0)
            v = HOLD_K * keep * pos_value(m, team, q) - (1.0 - keep) * pos_value(m, 1 - team, q) * 0.8
            if abs(q.imag) > pd.half_h - 60.0 and dot(dr, complex(0.0, 1.0 if q.imag > 0 else -1.0)) > 0.3:
                v -= WALL_PEN
            if abs(q.real) > pd.half_w - 90.0 and abs(q.imag) > pd.goal_half:
                v -= WALL_PEN
            if v > best_v:
                best_v, best_aim = v, bp + dr * 400.0
        return best_v, best_aim
