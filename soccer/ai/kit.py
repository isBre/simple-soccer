"""The toolkit every rule-based player builds on (soccer/ai/players/): the physics a player can predict (where the ball will be,
who gets there first), how to run (arrive, chase), how to strike the ball in a direction, how to read shooting and passing
lanes, and how to guard a goal. Pure functions of the public view (`v`, soccer/ai/view.py) and a body: no state, no agent.

The physics is public (soccer.match constants): a kick adds KICK_STRENGTH px/tick along player -> ball to the ball's velocity,
the ball keeps 0.99 of its speed every tick, a player accelerates at 0.1 px/tick^2 with damping 0.96 (top speed 2.4 px/tick)."""
import math

from ..match import KICK_RANGE, KICK_STRENGTH
from ..vec import INF, clamp, cross, dot, from_angle, lerp, normalized, rotated, angle

TOP = 2.4                               # a player's top speed, px/tick
TAU = 24.0                              # ticks: its acceleration time constant

# (t, (1 - 0.99^t) / 0.01) for t = 1, 3, ..., 159: how far the ball travels in t ticks per unit of speed
_Q = [(t, (1.0 - 0.99 ** t) / 0.01) for t in range(1, 161, 2)]
_Q160 = (1.0 - 0.99 ** 160) / 0.01
_QUICK = [(t, (1.0 - 0.99 ** t) / 0.01) for t in (2, 6, 12, 20, 30, 42, 56, 72, 90, 112, 136, 160)]
_ITAB = {}


# ---------------------------------------------------------------- the ball

def ball_at_t(v, bpos: complex, bvel: complex, q: float) -> complex:
    """Ball position after the time whose travel factor is q (walls ignored, clamped to the pitch)."""
    pd = v.pitch
    return complex(clamp(bpos.real + bvel.real * q, -pd.half_w + 12.0, pd.half_w - 12.0),
                   clamp(bpos.imag + bvel.imag * q, -pd.half_h + 12.0, pd.half_h - 12.0))


def ball_time(d: float) -> float:
    """Ticks a freshly kicked ball (~5 px/tick, damping 0.99) needs to cover d px (300 when it never gets there)."""
    r = 1.0 - d * 0.01 / 5.0
    if r <= 0.05:
        return 300.0
    return math.log(r) / math.log(0.99)


def _table(rd: float):
    tab = _ITAB.get(rd)
    if tab is None:
        tab = []
        for t, q in _Q:
            te = max(t - rd, 0.0)
            tab.append((t, q, TOP * te, 1.0 - math.exp(-te / TAU)))
        _ITAB[rd] = tab
    return tab


def intercept(v, b, bpos: complex, bvel: complex, delay: float):
    """Earliest point on the ball's path body b can get to, seeing the ball `delay` ticks late: (point, ticks); ticks = INF if
    none within 160 ticks."""
    touch = (b.radius + v.ball_r) * 0.6
    hw, hh = v.pitch.half_w - 12.0, v.pitch.half_h - 12.0
    bx, by, vx, vy = bpos.real, bpos.imag, bvel.real, bvel.imag
    px, py, pvx, pvy = b.pos.real, b.pos.imag, b.vel.real, b.vel.imag
    sqrt = math.sqrt
    for t, q, run, grow in _table(float(delay) + 2.0):
        x = bx + vx * q
        x = -hw if x < -hw else (hw if x > hw else x)
        y = by + vy * q
        y = -hh if y < -hh else (hh if y > hh else y)
        dx, dy = x - px, y - py
        dl = sqrt(dx * dx + dy * dy)
        along = (pvx * dx + pvy * dy) / (dl if dl > 1.0 else 1.0)
        if run + (along - TOP) * TAU * grow >= dl - touch:
            return complex(x, y), float(t)
    return ball_at_t(v, bpos, bvel, _Q160), INF


_QTAB = {}


def quick_path(v, bpos: complex, bvel: complex):
    """The ball's path at the 12 times reach_times looks at: [(t, x, y)]."""
    hw, hh = v.pitch.half_w - 12.0, v.pitch.half_h - 12.0
    out = []
    for t, q in _QUICK:
        x = bpos.real + bvel.real * q
        y = bpos.imag + bvel.imag * q
        out.append((t, -hw if x < -hw else (hw if x > hw else x), -hh if y < -hh else (hh if y > hh else y)))
    return out


def reach_times(v, bodies, path, delay=None) -> dict:
    """{body: (ticks, point)}: a quick estimate of intercept() (12 points of the ball's path, quick_path, instead of 80), each
    body judged with its generic reaction delay unless `delay` is given (INF and the last point if it never gets there)."""
    sqrt = math.sqrt
    out = {}
    for b in bodies:
        rd = float(b.reaction_delay if delay is None else delay) + 2.0
        tab = _QTAB.get(rd)
        if tab is None:
            tab = _QTAB[rd] = [(TOP * max(t - rd, 0.0), TAU * (1.0 - math.exp(-max(t - rd, 0.0) / TAU))) for t, _ in _QUICK]
        touch = (b.radius + v.ball_r) * 0.6
        px, py, pvx, pvy = b.pos.real, b.pos.imag, b.vel.real, b.vel.imag
        r = (INF, complex(path[-1][1], path[-1][2]))
        for (t, x, y), (run, grow) in zip(path, tab):
            dx, dy = x - px, y - py
            dl = sqrt(dx * dx + dy * dy)
            if run + ((pvx * dx + pvy * dy) / (dl if dl > 1.0 else 1.0) - TOP) * grow >= dl - touch:
                r = (float(t), complex(x, y))
                break
        out[b] = r
    return out


# ---------------------------------------------------------------- running

def arrive(me, target: complex) -> complex:
    """Run to a point and stop there (brakes on the way in)."""
    cmd = ((target - me.pos) - me.vel * 20.0) / 30.0
    l = abs(cmd)
    return cmd / l if l > 1.0 else cmd


def chase(me, target: complex) -> complex:
    """Full speed at a point."""
    d = target - me.pos
    return normalized(d) if abs(d) > 1.0 else 0j


def rush(me, target: complex, slow_radius: float = 18.0) -> complex:
    """Full speed until close, then arrive (a goal guard needs speed, not precision)."""
    return chase(me, target) if abs(target - me.pos) > slow_radius * 2.5 else arrive(me, target)


def avoid(v, me, d: complex) -> complex:
    """Give the players people control some room instead of bumping into them."""
    for h in v.human_mates:
        if h is me:
            continue
        off = me.pos - h.pos
        dl = abs(off)
        if dl < 66.0:
            d = d + off / max(dl, 1.0) * (1.0 - dl / 66.0) * 1.8
    l = abs(d)
    return d / l if l > 1.0 else d


def on_pitch(v, p: complex, margin: float = 20.0) -> complex:
    pd = v.pitch
    return complex(clamp(p.real, -pd.half_w + margin, pd.half_w - margin), clamp(p.imag, -pd.half_h + margin, pd.half_h - margin))


# ---------------------------------------------------------------- striking the ball

def kick_dir(dd: complex, ball_vel: complex) -> complex:
    """A kick adds KICK_STRENGTH along (player -> ball) to the ball's current velocity: the kick normal that sends a moving ball
    in direction dd (without it a received pass or a rebound goes off by up to ~20 degrees)."""
    k = KICK_STRENGTH
    vd = dot(ball_vel, dd)
    disc = vd * vd - abs(ball_vel) ** 2 + k * k
    if disc <= 0.0:
        return dd
    s = vd + math.sqrt(disc)
    if s <= 0.5:
        return dd
    return normalized((dd * s - ball_vel) / k)


def strike(v, me, bp: complex, d: complex, kind: str, ball_vel: complex):
    """Get behind the ball at bp and kick it along unit direction d: (run direction, kick now). kind "dribble" pushes the ball
    with the body instead of kicking; "shoot" and "pass" line up precisely, "clear" and "long" roughly."""
    pd = v.pitch
    if kind != "dribble":
        d = kick_dir(d, ball_vel)
    rel = me.pos - bp
    along, lateral = dot(rel, d), cross(rel, d)
    reach = me.radius + v.ball_r
    tol = 7.0 if kind in ("shoot", "pass") else (13.0 if kind in ("clear", "long") else reach * 0.9)
    if along < 0.0 and abs(lateral) < tol:
        target = bp + d * 22.0
    elif along < 0.0:
        target = bp - d * (reach + 16.0)
    else:
        perp = complex(d.imag, -d.real) * (1.0 if lateral >= 0.0 else -1.0)
        target = bp + perp * (reach + 30.0) - d * (reach + 6.0)
    target = complex(clamp(target.real, -pd.out_x + 12.0, pd.out_x - 12.0), clamp(target.imag, -pd.out_y + 12.0, pd.out_y - 12.0))
    run = chase(me, target)
    kick = False
    if kind != "dribble":
        to_ball = v.ball.pos - me.pos
        dist = abs(to_ball)
        if dist - reach < KICK_RANGE and dot(normalized(to_ball), d) > (0.95 if kind in ("shoot", "pass") else 0.8):
            kick = True
    return run, kick


# ---------------------------------------------------------------- reading the play

def nearest(bodies, pos: complex):
    """(distance, body) of the body nearest pos ((INF, None) if none)."""
    best, bb = INF, None
    for b in bodies:
        d = abs(b.pos - pos)
        if d < best:
            best, bb = d, b
    return best, bb


def lane_clearance(opps, a: complex, b: complex) -> float:
    """Distance from the segment a-b to the nearest opponent."""
    best = INF
    ab = b - a
    l2 = max(abs(ab) ** 2, 0.001)
    for o in opps:
        t = clamp(dot(o.pos - a, ab) / l2, 0.0, 1.0)
        best = min(best, abs(o.pos - (a + ab * t)))
    return best


def pass_margin(opps, a: complex, b: complex) -> float:
    """Smallest (opponent arrival - ball arrival) in ticks over three points of the lane a-b; negative = cut out."""
    d = abs(b - a)
    best = INF
    for o in opps:
        for f in (0.35, 0.65, 1.0):
            pt = lerp(a, b, f)
            best = min(best, max(abs(o.pos - pt) - 25.0, 0.0) / 2.0 + float(o.reaction_delay) - ball_time(d * f))
    return best


def shot_target(v, opps, bp: complex, opp_goal: complex, ax: float, err: float):
    """The point of the goal mouth whose line from the ball stays furthest from every opponent, with a margin that covers an aim
    error of `err` radians: (target, clearance of its lane)."""
    gh = v.pitch.goal_half - 14.0
    gh = max(gh - min(gh * 0.85, 1.5 * err * abs(bp - opp_goal)), 12.0)
    gx = opp_goal.real + ax * 10.0
    best_t, best_c, best_lane = complex(gx, 0.0), -INF, 0.0
    for k in range(7):
        y = (k - 3.0) / 3.0 * gh
        t = complex(gx, y)
        lane = lane_clearance(opps, bp, t)
        c = lane + abs(y) / gh * 12.0                  # corners are harder to cover
        if c > best_c:
            best_c, best_t, best_lane = c, t, lane
    return best_t, best_lane


def open_heading(v, opps, bp: complex, toward: complex, look: float, spread: float = 0.38, sight: float = 1.0) -> complex:
    """The heading from bp (towards `toward`, up to 3 * spread radians off) whose path of length `look` stays clearest of
    the opponents (their position 10 ticks ahead), as a far point to aim at."""
    pd = v.pitch
    base = angle(toward - bp)
    best, best_s = toward, -INF
    for k in range(7):
        off = (k - 3.0) * spread
        dr = from_angle(base + off)
        clear = INF
        for o in opps:
            op = o.pos + o.vel * 10.0
            t = clamp(dot(op - bp, dr) / look, 0.0, 1.0)
            clear = min(clear, abs(op - (bp + dr * look * t)))
        s = math.cos(off) * 55.0 + min(clear, 90.0) * (0.3 + 0.9 * sight)
        if abs((bp + dr * look).imag) > pd.half_h - 25.0:
            s -= 40.0
        if s > best_s:
            best_s, best = s, bp + dr * 400.0
    return best


# ---------------------------------------------------------------- guarding a goal

KEEP_F, KEEP_FS, KEEP_CAP, KEEP_CAPS, KEEP_FAR = 0.3, 0.3, 60.0, 160.0, 600.0


def guard(v, me, bpos: complex, bvel: complex, delay: float, sweep: float):
    """Guard our goal: (run direction, kick). A ball heading for the goal: run to the earliest point of its path still reachable
    in time. Otherwise stand on the line ball - goal centre, further out the closer the ball (narrowing the angle; `sweep` 0..1
    how far). Kick only a ball clearly in front, never towards our own goal."""
    ax = v.attack_dir(me.team)
    pd = v.pitch
    goal = complex(-ax * pd.half_w, 0.0)
    lim = pd.goal_half - 10.0
    if bvel.real * (-ax) > 0.8:
        bp, vel, path, on_target = bpos, bvel, [], False
        for _ in range(100):
            bp += vel
            vel *= 0.99
            path.append(bp)
            if (bp.real - (goal.real + ax * 10.0)) * (-ax) >= 0.0:
                on_target = abs(bp.imag) < pd.goal_half + 25.0
                break
            if abs(vel) < 0.3:
                break
        if on_target:
            tgt = path[-1]
            touch = me.radius + v.ball_r + 3.0
            for i, pt in enumerate(path):
                dv = pt - me.pos
                dl = abs(dv)
                te = max(i + 1.0 - delay - 2.0, 0.0)
                reach = TOP * te + (dot(me.vel, dv / max(dl, 1.0)) - TOP) * TAU * (1.0 - math.exp(-te / TAU))
                if reach * 0.92 >= dl - touch:
                    tgt = path[min(i + 8, len(path) - 1)]
                    break
            tgt = complex(tgt.real, clamp(tgt.imag, -(lim + 25.0), lim + 25.0))
            if (tgt.real - goal.real) * ax < 12.0:
                tgt = complex(goal.real + ax * 12.0, tgt.imag)
            run = chase(me, tgt) if abs(tgt - me.pos) > 14.0 else arrive(me, tgt)
            return run, _guard_kick(v, me, ax)
    to_ball = bpos - goal
    dist = max(abs(to_ball), 1.0)
    depth = min(dist * (KEEP_F + sweep * KEEP_FS), KEEP_CAP + sweep * KEEP_CAPS)
    depth *= clamp((KEEP_FAR - dist) / 220.0, 0.25, 1.0)
    depth = max(depth, 24.0)
    target = goal + to_ball / dist * depth
    target = complex(target.real, clamp(target.imag, -lim, lim))
    if (target.real - goal.real) * ax < 20.0:
        target = complex(goal.real + ax * 20.0, target.imag)
    return rush(me, target), _guard_kick(v, me, ax)


def _guard_kick(v, me, ax) -> bool:
    to_ball = v.ball.pos - me.pos
    dl = abs(to_ball)
    return dl - me.radius - v.ball_r < KICK_RANGE + 3.0 and to_ball.real * ax / max(dl, 1.0) > 0.3


def goal_side(v, team: int, threat: complex, ball: complex, tight: float) -> complex:
    """Where to stand to mark a threat: between it and our goal, a little towards the ball (tight 0..1: how close)."""
    ax = v.attack_dir(team)
    own_goal = complex(-ax * v.pitch.half_w, 0.0)
    return lerp(lerp(threat, own_goal, 0.35 - 0.2 * tight), ball, 0.2 * tight)


def aim_with_error(d: complex, err: float) -> complex:
    return rotated(normalized(d), err)
