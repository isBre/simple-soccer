"""Rule-based AI: TeamBrain coordinates one team (who chases the ball, who is the carrier, who keeps goal, who marks whom,
who runs onto an opponent's pass), StyleBot plays one player from the team's style and the player's attributes.
Jobs of a StyleBot (given by the team brain each tick, never fixed): goal guard / chaser (plays the ball: shoot, pass, dribble, clear) / off-ball (shape, support, marking)."""
import math

from ..match import KICK_RANGE, KICK_STRENGTH
from ..vec import INF, clamp, cross, dot, from_angle, lerp, lerpf, normalized, rotated, sign, angle

# keeper depth tuning (see StyleBot._keeper)
KEEP_F = 0.3
KEEP_FS = 0.3
KEEP_CAP = 60.0
KEEP_CAPS = 160.0
KEEP_FAR = 600.0

# (1 - 0.99^t) / 0.01 for t = 1, 3, ..., 159: how far the ball travels in t ticks per unit of speed
_Q = [(t, (1.0 - 0.99 ** t) / 0.01) for t in range(1, 161, 2)]
_Q160 = (1.0 - 0.99 ** 160) / 0.01


def ball_at_t(m, bpos: complex, bvel: complex, q: float) -> complex:
    """Ball position after the time whose travel factor is q (walls ignored, clamped to the pitch)."""
    pd = m.pitch
    return complex(clamp(bpos.real + bvel.real * q, -pd.half_w + 12.0, pd.half_w - 12.0),
                   clamp(bpos.imag + bvel.imag * q, -pd.half_h + 12.0, pd.half_h - 12.0))


def _intercept_table(rd: float):
    """(t, q, 2.4 * te, 1 - exp(-te / 24)) for every t of _Q, te = max(t - rd, 0): te is a whole number (t is, and so is the
    reaction delay), so the values are exactly those computed in the loop. Cached per reaction delay."""
    tab = _ITAB.get(rd)
    if tab is None:
        tab = []
        for t, q in _Q:
            te = t - rd
            if te < 0.0:
                te = 0.0
            tab.append((t, q, 2.4 * te, 1.0 - math.exp(-te / 24.0)))
        _ITAB[rd] = tab
    return tab


_ITAB = {}


def intercept(m, p, bpos: complex, bvel: complex):
    """Earliest point on the ball's (predictable) path the player can get to: (point, ticks); ticks = INF if none within 160.
    A player accelerates at 0.1 with damping 0.96: top speed 2.4 px/tick, 24-tick time constant."""
    touch = (p.radius + m.ball_r) * 0.6
    hw, hh = m.pitch.half_w - 12.0, m.pitch.half_h - 12.0
    bx, by, vx, vy = bpos.real, bpos.imag, bvel.real, bvel.imag
    px, py, pvx, pvy = p.pos.real, p.pos.imag, p.vel.real, p.vel.imag
    sqrt = math.sqrt
    for t, q, run, grow in _intercept_table(float(p.reaction_delay) + 2.0):
        x = bx + vx * q
        x = -hw if x < -hw else (hw if x > hw else x)
        y = by + vy * q
        y = -hh if y < -hh else (hh if y > hh else y)
        dx, dy = x - px, y - py
        dl = sqrt(dx * dx + dy * dy)
        along = (pvx * dx + pvy * dy) / (dl if dl > 1.0 else 1.0)
        if run + (along - 2.4) * 24.0 * grow >= dl - touch:
            return complex(x, y), float(t)
    return ball_at_t(m, bpos, bvel, _Q160), INF


class TeamBrain:
    def __init__(self, team: int, style):
        self.team = team
        self.style = style
        self.reset()

    def reset(self):
        self.has_possession = False
        self.opp_possession = False
        self.danger = False                # ball in our defensive third
        self.lost_tick = -999              # when we last lost possession (counter-press window)
        self._had_possession = False
        self.interceptor = None            # off-ball player sent to cut out an opponent's pass / shot
        self.intercept_pt = 0j
        self.urgency = 0.0                 # game management: > 0 chase the game (behind late), < 0 protect a lead
        self.chasers = []
        self.carrier = None
        self.pass_target = None
        self.pass_tick = -999
        self.marks = {}                    # slot -> opponent to mark
        self.keeper = None                 # whoever is guarding the goal right now (any player can)

    def _pick_keeper(self, m, mates, ax):
        """Who guards the goal: the rearmost non-chasing player. The player on the formation's goal spot (line "GK", a spot of
        the team's tactic, not a player's role) gets a head start that shrinks with style.fluidity (0 = the goal spot always
        guards, 1 = whoever is deepest); the current guard keeps the job unless someone else is clearly deeper (no flicker)."""
        if len(mates) <= 1:
            self.keeper = None
            return
        if self.keeper is not None and self.keeper.is_human:
            self.keeper = None             # the human decides for himself where to stand
        if self.keeper is None:
            for sp in mates:
                if sp.line == "GK" and not sp.is_human:
                    self.keeper = sp
            if self.keeper is None:
                for sp in mates:
                    if not sp.is_human:
                        self.keeper = sp
                        break
        own_x = -ax * m.pitch.half_w
        best, best_s = None, INF
        for sp in mates:
            if sp.is_human or (sp in self.chasers and sp is not self.keeper):
                continue
            s = (sp.pos.real - own_x) * ax
            if sp.line == "GK":
                s -= 260.0 * (1.0 - self.style.fluidity)
            elif sp.line == "FWD":
                s += 40.0
            if sp is self.keeper:
                s -= 50.0
            if s < best_s:
                best_s, best = s, sp
        if best is not None:
            self.keeper = best

    def update(self, m):
        st = self.style
        ball = m.ball_pos
        ax = m.attack_dir(self.team)
        team = m.team_lists[self.team]
        mates = [p for p in team if p.brain is self]          # the players this brain commands (a mixed team has several)
        opps = m.team_lists[1 - self.team]
        lt = m.last_touch
        hw = m.pitch.half_w
        self.has_possession = lt is not None and lt.team == self.team
        self.opp_possession = lt is not None and lt.team != self.team
        self.danger = ball.real * -ax > hw * 0.4
        if self._had_possession and not self.has_possession:
            self.lost_tick = m.tick
        self._had_possession = self.has_possession
        # game management: in the last ~45% of the match a team that is behind pushes up and shoots earlier, a team that is
        # ahead drops deeper and keeps the ball
        behind = m.scores[1 - self.team] - m.scores[self.team]
        elapsed_frac = 1.0 - m.time_left / max(m.duration, 1.0)
        self.urgency = clamp(behind * 0.5, -1.0, 1.0) * clamp((elapsed_frac - 0.55) / 0.35, 0.0, 1.0)

        if self.pass_target is not None and (m.tick - self.pass_tick > 90 or lt is self.pass_target or not self.has_possession):
            self.pass_target = None

        if self.keeper is None and len(mates) > 1:
            self._pick_keeper(m, mates, ax)
        prev = self.chasers
        self.chasers = []
        human_has_ball = False
        # a human-controlled player is not ours to command: when he is the one at the ball the bots leave it to him
        # (no second chaser running into him) and just support
        human = None
        for sp in team:
            if sp.is_human:
                human = sp
        if self.pass_target is not None and not self.pass_target.is_human:
            self.chasers.append(self.pass_target)
        else:
            scale = hw / 370.0
            n_max = 1
            if not self.has_possession:
                if st.press >= 0.25:
                    n_max += 1
                if st.press >= 0.8:
                    n_max += 1
            # attacking third: a second player follows the carrier for rebounds and tap-ins
            if self.has_possession and len(mates) >= 4 and ball.real * ax > hw * 0.3:
                n_max = max(n_max, 2)
            if not self.has_possession and len(mates) >= 4:
                # the ball is in our half: more defenders close in on the carrier (cover instead of a single lunge)
                depth = ball.real * -ax / hw
                if depth > 0.45:
                    n_max = max(n_max, 2)
                if depth > 0.7:
                    n_max = max(n_max, 3)
            if not self.has_possession and st.counter_press > 0.05 and len(mates) >= 3 \
                    and m.tick - self.lost_tick < int(150.0 * st.counter_press):
                n_max += 1       # gegenpress: win the ball back straight after losing it
            if self.urgency > 0.5 and not self.has_possession and len(mates) >= 4:
                n_max += 1       # chasing the game: press with one more player
            n_max = min(n_max, max(1, len(mates) - 1))
            if human is not None:
                hd = abs(human.pos - ball)
                bot_best = INF
                for sp in mates:
                    if not sp.is_human and sp is not self.keeper:
                        bot_best = min(bot_best, abs(sp.pos - ball))
                if hd < bot_best + 70.0 or hd < 90.0:
                    human_has_ball = True
                    n_max = 0 if self.has_possession else max(0, n_max - 1)
            press_radius = (70.0 + st.press * 230.0) * scale
            cand = []
            for sp in mates:
                if sp.is_human:
                    continue
                d = abs(sp.pos - ball)
                if sp is self.keeper and len(mates) > 1:
                    reach = (110.0 + st.keeper_sweep * 130.0) * scale
                    if not (self.danger and abs(ball.imag) < m.pitch.goal_half * 2.4 and d < reach):
                        continue
                    if (ball.real - sp.pos.real) * ax < 8.0:
                        continue      # ball is behind / level with the keeper: stay on the line
                    # only charge when he wins the race to the ball; against a dribbler who is closer he stays between
                    # ball and goal and narrows the angle instead
                    opp_d = INF
                    for o in opps:
                        opp_d = min(opp_d, abs(o.pos - ball))
                    if d > opp_d - 12.0:
                        continue
                if sp in prev:
                    d -= 25.0
                cand.append((d, sp))
            cand.sort(key=lambda c: c[0])
            for i in range(min(n_max, len(cand))):
                if i > 0 and cand[i][0] > press_radius:
                    break
                self.chasers.append(cand[i][1])
        self.carrier = self.chasers[0] if (self.has_possession and self.chasers) else None
        if self.has_possession and human_has_ball:
            self.carrier = human
        self._pick_keeper(m, mates, ax)
        self._assign_marks(m, mates, opps, ax)
        self._pick_interceptor(m, mates)

    def _pick_interceptor(self, m, mates):
        """After an opponent's kick, the off-ball player who can reach the ball's path first (and clearly before the
        chasers can) runs onto it. Eagerness comes from the style, ability from the player's defending."""
        self.interceptor = None
        st = self.style
        if st.intercept <= 0.05 or not self.opp_possession or abs(m.ball_vel) < 1.2:
            return
        chaser_t = INF
        for c in self.chasers:
            chaser_t = min(chaser_t, intercept(m, c, m.ball_pos, m.ball_vel)[1])
        best_t = INF
        for sp in mates:
            if sp.is_human or sp is self.keeper or sp in self.chasers:
                continue
            pt, t = intercept(m, sp, m.ball_pos, m.ball_vel)
            limit = (25.0 + 70.0 * st.intercept) * lerpf(0.6, 1.0, sp.defend_q)
            if t <= limit and t < best_t and t < chaser_t - 6.0:
                best_t = t
                self.interceptor = sp
                self.intercept_pt = pt

    def _assign_marks(self, m, mates, opps, ax):
        self.marks.clear()
        if self.has_possession:
            return
        free = []
        for sp in mates:
            if sp is self.keeper or sp in self.chasers or sp.is_human:
                continue
            if sp.line == "FWD" and self.style.forward_stay > 0.5:
                continue
            free.append(sp)
        if not free:
            return
        own_goal = complex(-ax * m.pitch.half_w, 0.0)
        other_keeper = m.brains[1 - self.team].keeper
        threats = []
        for op in opps:
            if op is other_keeper and len(opps) > 1:
                continue
            threats.append((abs(op.pos - own_goal), op))
        threats.sort(key=lambda th: th[0])
        for _, opp in threats:
            if not free:
                break
            best, bd = None, INF
            for fp in free:
                d = abs(fp.pos - opp.pos)
                if d < bd:
                    bd, best = d, fp
            self.marks[best.slot] = opp
            free.remove(best)


def _ball_time(d: float) -> float:
    """Ticks a kicked ball needs to cover d px (kick speed ~5 px/tick, damping 0.99/tick)."""
    r = 1.0 - d * 0.01 / 5.0
    if r <= 0.05:
        return 300.0
    return math.log(r) / math.log(0.99)


def _compensated_dir(dd: complex, v: complex) -> complex:
    """A kick adds exactly KICK_STRENGTH along (player -> ball) to the ball's CURRENT velocity v. To send the ball in
    direction dd the kick normal n must satisfy v + K*n = s*dd: solve for s > 0, then n = (s*dd - v) / K. Without this,
    kicking a moving ball (received pass, rebound, dribble) sends it off by up to ~20 degrees."""
    k = KICK_STRENGTH
    vd = dot(v, dd)
    disc = vd * vd - abs(v) ** 2 + k * k
    if disc <= 0.0:
        return dd
    s = vd + math.sqrt(disc)
    if s <= 0.5:
        return dd
    return normalized((dd * s - v) / k)


def _nearest_opp_dist(m, team, pos):
    best = INF
    for o in m.team_lists[1 - team]:
        d = abs(o.pos - pos)
        if d < best:
            best = d
    return best


def _lane_clearance(m, team, a, b):
    """Distance from the segment a-b to the nearest opponent."""
    best = INF
    ab = b - a
    l2 = max(abs(ab) ** 2, 0.001)
    for o in m.team_lists[1 - team]:
        op = o.pos
        t = clamp(dot(op - a, ab) / l2, 0.0, 1.0)
        d = abs(op - (a + ab * t))
        if d < best:
            best = d
    return best


def _pass_margin(m, team, a, b):
    """Smallest (opponent arrival time - ball arrival time) in ticks over a few points on the pass lane.
    Negative = an opponent gets there first."""
    d = abs(b - a)
    best = INF
    for op in m.team_lists[1 - team]:
        for f in (0.35, 0.65, 1.0):
            pt = lerp(a, b, f)
            t_ball = _ball_time(d * f)
            t_opp = max(abs(op.pos - pt) - 25.0, 0.0) / 2.0 + float(op.reaction_delay)
            best = min(best, t_opp - t_ball)
    return best


class StyleBot:
    """Rule-based bot driven by its player's style and skill (soccer/ai/skill.py), coordinated by its team brain."""

    def __init__(self, style):
        self.style = style
        self._kind = "dribble"
        self._aim = 0j
        self._kick = False
        self._mate = None
        self._decided = -999
        self._err = 0.0
        self._noise = 0j
        self._noise_tick = -999
        self._icp_t = 0.0                  # ticks until the chaser meets the ball
        self._bv_contact = 0j              # ball velocity expected at that moment

    def decide(self, m, p):
        p.input_kick = False
        p.kick_intent = ""
        p.input_dir = 0j
        brain = p.brain
        bpos = m.ball_at(p.reaction_delay)
        bold = m.ball_at(p.reaction_delay + 4)
        bvel = (bpos - bold) / 4.0
        is_chaser = p in brain.chasers

        if m.kickoff_active:
            if p is m.kickoff_taker:
                # taker stands right behind the ball: wait a random few ticks, then kick
                if m.tick >= m.kickoff_go:
                    p.input_kick = True
                    p.kick_intent = "pass"
            else:
                self._arrive(p, p.spawn)
            return
        if brain.keeper is p and not is_chaser and len(m.team_lists[p.team]) > 1:
            self._keeper(m, p, bpos, bvel)
        elif is_chaser:
            self._go_for_ball(m, p, brain, bpos, bvel)
        elif brain.interceptor is p:
            self._intercept_run(p, brain)
        else:
            self._off_ball(m, p, brain, bpos)
        self._avoid_human(m, p)

    def _intercept_run(self, p, brain):
        """Run onto the predicted path of an opponent's pass / shot (full speed, then settle on the spot)."""
        to = brain.intercept_pt - p.pos
        if abs(to) > 14.0:
            p.input_dir = normalized(to)
        else:
            self._arrive(p, brain.intercept_pt)

    @staticmethod
    def _avoid_human(m, p):
        """Bots give their human-controlled teammate some room instead of bumping into him."""
        h = m.controlled
        if h is None or h is p or h.team != p.team or not h.is_human:
            return
        off = p.pos - h.pos
        d = abs(off)
        if d >= 66.0:
            return
        push = off / max(d, 1.0) * (1.0 - d / 66.0) * 1.8
        z = p.input_dir + push
        l = abs(z)
        p.input_dir = z / l if l > 1.0 else z

    # ------------------------------------------------------------ ball play

    def _go_for_ball(self, m, p, brain, bpos, bvel):
        # exact meeting point with the (predictable) ball path instead of a rough lead
        bp, t = intercept(m, p, bpos, bvel)
        self._icp_t = min(t, 160.0)
        self._bv_contact = bvel * (0.99 ** self._icp_t)
        if m.tick - self._decided > p.think_ticks:
            self._decide_action(m, p, brain, bp)
            self._decided = m.tick
        self._play_ball(m, p, brain, bp)

    def _decide_action(self, m, p, brain, bp):
        st = self.style
        rng = p.rng
        ax = m.attack_dir(p.team)
        pd = m.pitch
        opp_goal = complex(ax * pd.half_w, 0.0)
        d_goal = abs(bp - opp_goal)
        pressure = _nearest_opp_dist(m, p.team, bp)
        in_front = bp.real * ax > -pd.half_w * 0.1
        self._mate = None
        self._err = 0.0

        # the ball's reach is fixed by the physics, so shot / pass distances must not grow with the pitch
        shoot_r = min(st.shoot_range * pd.half_w * 1.15, 330.0 * (1.0 + 0.4 * st.long_shot)) * (1.0 + 0.2 * max(brain.urgency, 0.0))
        if in_front and d_goal < shoot_r * (1.3 + 0.5 * st.long_shot):
            target, lane = self._shot_eval(m, p, bp, opp_goal, ax)
            # shoot inside the range unless the lane is blocked and there is time; a really open lane justifies a longer
            # shot; a ball about to be lost is shot anyway
            if (d_goal < shoot_r and (lane > 20.0 or pressure < 60.0 or d_goal < shoot_r * 0.45)) \
                    or lane > 45.0 - 15.0 * st.long_shot:
                self._kind = "shoot"
                self._kick = True
                self._aim = target
                self._err = rng.gauss(0.0, p.err_finish)
                return

        pass_chance = st.pass_bias
        if pressure < 55.0:
            pass_chance = min(1.0, pass_chance + 0.35)
        elif pressure > 130.0 * (pd.half_w / 370.0) * 0.6:
            pass_chance *= 0.55      # plenty of space: carry the ball forward instead of passing sideways
        best = self._best_pass(m, p, brain, bp, ax)
        if best is not None and pressure > 60.0:
            # a sideways / backward pass with nobody on him only gives the chance away: keep the ball and carry it
            # (possession-minded styles accept more sideways passes)
            gain = (best.pos.real - bp.real) * ax
            if gain < lerpf(40.0, -30.0, st.pass_bias) * min(pd.half_w / 370.0, 1.3):
                best = None
        if best is not None and rng.random() < pass_chance:
            self._kind = "pass"
            self._kick = True
            self._mate = best
            dist = abs(bp - best.pos)
            aim = best.pos + best.vel * min(_ball_time(dist), 40.0) * 0.8
            self._aim = complex(clamp(aim.real, -pd.half_w + 15.0, pd.half_w - 15.0),
                                clamp(aim.imag, -pd.half_h + 15.0, pd.half_h - 15.0))
            self._err = rng.gauss(0.0, p.err_pass)
            return

        if brain.danger and pressure < 80.0:
            self._kind = "clear"
            self._kick = True
            sy = 1.0 if bp.imag >= 0.0 else -1.0
            self._aim = complex(ax * pd.half_w * 0.4, sy * pd.half_h * 0.8)
            self._err = rng.gauss(0.0, p.err_pass)
            return

        if st.directness > 0.8 and not in_front and rng.random() < 0.4:
            self._kind = "long"
            self._kick = True
            self._aim = complex(opp_goal.real * 0.7, bp.imag * 0.5)
            self._err = rng.gauss(0.0, p.err_pass)
            return

        self._kind = "dribble"
        self._kick = False
        self._aim = self._dribble_aim(m, p, bp, opp_goal)

    def _shot_eval(self, m, p, bp, opp_goal, ax):
        """Best point in the goal mouth: the one whose line from the ball stays furthest from every opponent (keeper
        included). Returns (target, clearance). Players with poor vision sometimes pick at random."""
        # aim inside the goal mouth with a margin that covers this player's aim error at this distance
        gh = m.pitch.goal_half - 14.0
        margin = min(gh * 0.85, 1.5 * p.err_finish * abs(bp - opp_goal))
        gh = max(gh - margin, 12.0)
        gx = opp_goal.real + ax * 10.0
        best_t, best_c, best_lane = complex(gx, 0.0), -INF, 0.0
        for k in range(7):
            y = (k - 3.0) / 3.0 * gh
            t = complex(gx, y)
            lane = _lane_clearance(m, p.team, bp, t)
            c = lane + abs(y) / gh * 12.0       # corners are harder for the keeper
            if c > best_c:
                best_c, best_t, best_lane = c, t, lane
        if p.rng.random() > p.vision + 0.4:
            best_t = complex(gx, p.rng.uniform(-gh, gh))
            best_lane = _lane_clearance(m, p.team, bp, best_t)
        return best_t, best_lane

    @staticmethod
    def _dribble_aim(m, p, bp, opp_goal):
        """Carry the ball towards goal but steer around opponents (with a bit of look-ahead on their movement)."""
        pd = m.pitch
        look = 120.0 * min(pd.half_w / 370.0, 1.3)
        base_ang = angle(opp_goal - bp)
        best, best_s = opp_goal, -INF
        opps = m.team_lists[1 - p.team]
        for k in range(7):
            off = (k - 3.0) * 0.38
            dr = from_angle(base_ang + off)
            probe = bp + dr * look
            s = math.cos(off) * 55.0
            clear = INF
            for op in opps:
                opos = op.pos + op.vel * 10.0
                t = clamp(dot(opos - bp, dr) / look, 0.0, 1.0)
                clear = min(clear, abs(opos - (bp + dr * look * t)))
            s += min(clear, 90.0) * (0.3 + p.vision * 0.9)
            if abs(probe.imag) > pd.half_h - 25.0:
                s -= 40.0
            if s > best_s:
                best_s = s
                best = bp + dr * 400.0
        return best

    def _best_pass(self, m, p, brain, bp, ax):
        st = self.style
        scale = min(m.pitch.half_w / 370.0, 1.2)
        pref = lerpf(110.0, 300.0, st.directness) * scale
        max_d = min(lerpf(240.0, 520.0, st.directness) * scale, 450.0)
        best, best_s = None, -INF
        for mp in m.team_lists[p.team]:
            if mp is p:
                continue
            if mp is brain.keeper or mp.pos.real * ax < -m.pitch.half_w * 0.6:
                continue
            to = mp.pos - bp
            dist = abs(to)
            if dist < 60.0 or dist > max_d:
                continue
            tgt = mp.pos + mp.vel * min(_ball_time(dist), 40.0) * 0.8
            open_ = _lane_clearance(m, p.team, bp, tgt)
            if open_ < lerpf(16.0, 34.0, p.vision):
                continue
            # can an opponent get to the lane before the ball does?
            margin = _pass_margin(m, p.team, bp, tgt)
            if margin < lerpf(-45.0, -5.0, p.vision):
                continue
            rp = min(_nearest_opp_dist(m, p.team, mp.pos), 140.0)
            progress = to.real * ax
            s = progress * (0.25 + st.risk * 0.6) + min(open_, 100.0) * 0.5 + rp * 0.6 \
                - abs(dist - pref) * 0.35 + clamp(margin, -40.0, 40.0) * 0.6 \
                + st.switch_play * min(abs(mp.pos.imag - bp.imag), 220.0) * 0.3
            if s > best_s:
                best_s, best = s, mp
        return best

    def _play_ball(self, m, p, brain, bp):
        ax = m.attack_dir(p.team)
        pd = m.pitch
        d = self._aim - bp
        if abs(d) < 1.0:
            d = complex(ax, 0.0)
        d = rotated(normalized(d), self._err)
        if self._kind != "dribble":
            d = _compensated_dir(d, self._bv_contact)
        rel = p.pos - bp
        along = dot(rel, d)
        lateral = cross(rel, d)
        reach = p.radius + m.ball_r
        tol = reach * 0.9
        if self._kind in ("shoot", "pass"):
            tol = 7.0
        elif self._kind in ("clear", "long"):
            tol = 13.0
        if along < 0.0 and abs(lateral) < tol:
            target = bp + d * 22.0
        elif along < 0.0:
            target = bp - d * (reach + 16.0)
        else:
            sgn = 1.0 if lateral >= 0.0 else -1.0
            perp = complex(d.imag, -d.real) * sgn
            target = bp + perp * (reach + 30.0) - d * (reach + 6.0)
        target = complex(clamp(target.real, -pd.out_x + 12.0, pd.out_x - 12.0), clamp(target.imag, -pd.out_y + 12.0, pd.out_y - 12.0))
        self._chase(p, target)

        if self._kick:
            to_ball = m.ball_pos - p.pos
            dist = abs(to_ball)
            need = 0.95 if self._kind in ("shoot", "pass") else 0.8
            if dist - reach < KICK_RANGE and dot(normalized(to_ball), d) > need:
                p.input_kick = True
                p.kick_intent = self._kind
                if self._kind == "pass" and self._mate is not None:
                    brain.pass_target = self._mate
                    brain.pass_tick = m.tick

    # ------------------------------------------------------------ off-ball

    def _off_ball(self, m, p, brain, bpos):
        st = self.style
        ax = m.attack_dir(p.team)
        pd = m.pitch
        hw, hh = pd.half_w, pd.half_h
        bx = bpos.real * ax / hw
        role = p.line                         # the line of this player's formation spot (team tactic)
        fx = p.home.real
        if role == "GK":
            # the player on the goal spot plays as a defender while someone else guards the goal
            role = "DEF"
            fx = max(fx, -0.62)
        shift = {"MID": 0.45, "FWD": 0.5}.get(role, 0.3)
        fx += bx * shift * (0.4 + st.compactness)
        fx += (st.line_height - 0.5) * (0.15 if role == "FWD" else 0.3)
        if brain.has_possession:
            fx += {"FWD": 0.25, "MID": 0.15, "DEF": 0.05}.get(role, 0.0)
            # attack commitment: with the ball in the attacking half more players join the attack
            if bx > -0.15:
                fx += st.attack_commit * (0.32 if role == "DEF" else (0.2 if role == "MID" else 0.08))
        else:
            if role == "FWD":
                fx = max(fx, p.home.real + (st.forward_stay - 0.3) * 0.6)
            elif role == "DEF":
                fx -= 0.04
        fx += brain.urgency * (0.18 if role != "DEF" else 0.12)
        fx = clamp(fx, -0.9, 0.85)
        fy = p.home.imag * st.width + (bpos.imag / hh) * 0.2 * (0.5 + st.compactness)
        fy = clamp(fy, -0.85, 0.85)
        target = complex(ax * fx * hw, fy * hh)

        if brain.has_possession and (role != "DEF" or st.attack_commit > 0.6) and brain.carrier is not None:
            c = brain.carrier
            sd = st.support_dist * min(hw / 370.0, 1.3)
            base_x = c.pos.real + ax * sd
            off = 90.0 * (hh / 170.0)
            cands = [target, complex(base_x, target.imag),
                     complex(base_x, clamp(c.pos.imag + off, -hh * 0.8, hh * 0.8)),
                     complex(base_x, clamp(c.pos.imag - off, -hh * 0.8, hh * 0.8))]
            best, best_s = target, -INF
            for cp in cands:
                s = min(_nearest_opp_dist(m, p.team, cp), 120.0) - 0.15 * abs(cp - p.pos)
                if (cp.real - c.pos.real) * ax < -40.0:
                    s -= 60.0
                if p.home.imag != 0.0 and sign(cp.imag - c.pos.imag) == sign(p.home.imag):
                    s += 25.0
                if s > best_s:
                    best_s, best = s, cp
            target = lerp(target, best, 0.7)
        elif not brain.has_possession and role != "FWD" and bx < 0.2:
            own_goal2 = complex(-ax * hw, 0.0)
            scale = hw / 370.0
            cover_dist = lerpf(150.0, 80.0, st.line_height) * scale
            back = min(cover_dist, abs(bpos - own_goal2) - 45.0)
            cover = bpos + normalized(own_goal2 - bpos) * max(back, 0.0)
            cover += complex(0.0, p.home.imag * hh * 0.35)
            target = lerp(target, cover, 0.6 if role == "DEF" else 0.35)
            o2 = brain.marks.get(p.slot)
            if o2 is not None:
                spot = lerp(lerp(o2.pos, own_goal2, 0.3), bpos, 0.22 * p.defend_q)
                target = lerp(target, spot, st.marking * 0.5 * lerpf(0.6, 1.2, p.defend_q))
        elif not brain.has_possession and p.slot in brain.marks:
            o = brain.marks[p.slot]
            own_goal = complex(-ax * hw, 0.0)
            spot = lerp(lerp(o.pos, own_goal, 0.3), bpos, 0.22 * p.defend_q)
            target = lerp(target, spot, min(st.marking * lerpf(0.6, 1.2, p.defend_q), 1.0))

        if m.tick - self._noise_tick > 90:
            self._noise = complex(p.rng.gauss(0.0, 1.0), p.rng.gauss(0.0, 1.0)) * p.pos_noise * 0.5
            self._noise_tick = m.tick
        target += self._noise
        target = complex(clamp(target.real, -hw + 20.0, hw - 20.0), clamp(target.imag, -hh + 20.0, hh - 20.0))
        self._arrive(p, target)

    def _keeper(self, m, p, bpos, bvel):
        ax = m.attack_dir(p.team)
        pd = m.pitch
        goal = complex(-ax * pd.half_w, 0.0)
        lim = pd.goal_half - 10.0
        to_ball = bpos - goal
        dist = max(abs(to_ball), 1.0)
        sweep = self.style.keeper_sweep

        # 1) a shot / fast ball heading for the goal: simulate its path and run to the EARLIEST point of that path he can
        #    still reach in time (he accelerates slowly: ~2.4 px/tick top speed, 24-tick time constant)
        if bvel.real * (-ax) > 0.8:
            bp, v = bpos, bvel
            path = []
            on_target = False
            for _ in range(100):
                bp += v
                v *= 0.99
                path.append(bp)
                if (bp.real - (goal.real + ax * 10.0)) * (-ax) >= 0.0:
                    on_target = abs(bp.imag) < pd.goal_half + 25.0
                    break
                if abs(v) < 0.3:
                    break
            if on_target:
                tgt = path[-1]
                touch = p.radius + m.ball_r + 3.0
                for i, pt in enumerate(path):
                    t = float(i + 1)
                    dv = pt - p.pos
                    dl = abs(dv)
                    along = dot(p.vel, dv / max(dl, 1.0))
                    te = max(t - float(p.reaction_delay) - 2.0, 0.0)    # he sees the ball late and decides every 2nd tick
                    reach = 2.4 * te + (along - 2.4) * 24.0 * (1.0 - math.exp(-te / 24.0))
                    if reach * 0.92 >= dl - touch:
                        # aim a little further down the path: sitting in the ball's way guarantees the touch
                        tgt = path[min(i + 8, len(path) - 1)]
                        break
                tgt = complex(tgt.real, clamp(tgt.imag, -(lim + 25.0), lim + 25.0))
                if (tgt.real - goal.real) * ax < 12.0:
                    tgt = complex(goal.real + ax * 12.0, tgt.imag)
                to_t = tgt - p.pos
                if abs(to_t) > 14.0:
                    p.input_dir = normalized(to_t)      # full speed, no braking: he only has to get a touch
                else:
                    self._arrive(p, tgt)
                self._keeper_kick(m, p, ax)
                return

        # 2) otherwise stand on the line between the ball and the goal centre; the closer the ball, the further the keeper
        #    comes out to narrow the angle (he cannot cover the whole mouth in time: ~40 ticks to cross 60 px), until the
        #    shot cone at his depth is as wide as he can reach
        depth = min(dist * (KEEP_F + sweep * KEEP_FS), KEEP_CAP + sweep * KEEP_CAPS)
        depth *= clamp((KEEP_FAR - dist) / 220.0, 0.25, 1.0)    # ball far away: back to a safe depth
        depth = max(depth, 24.0)
        target = goal + to_ball / dist * depth
        target = complex(target.real, clamp(target.imag, -lim, lim))
        if (target.real - goal.real) * ax < 20.0:
            target = complex(goal.real + ax * 20.0, target.imag)
        self._chase_arrive(p, target, 18.0)
        self._keeper_kick(m, p, ax)

    @staticmethod
    def _keeper_kick(m, p, ax):
        # only kick when the ball is clearly in front of the keeper, so the kick can never push it towards his own goal
        to_ball = m.ball_pos - p.pos
        dl = abs(to_ball)
        if dl - p.radius - m.ball_r < KICK_RANGE + 3.0 and to_ball.real * ax / max(dl, 1.0) > 0.3:
            p.input_kick = True
            p.kick_intent = "clear"

    def _chase_arrive(self, p, target, slow_radius):
        """Full speed towards the target, braking only when close (a keeper needs speed, not precision)."""
        v = target - p.pos
        if abs(v) > slow_radius * 2.5:
            p.input_dir = normalized(v)
        else:
            self._arrive(p, target)

    @staticmethod
    def _chase(p, target):
        v = target - p.pos
        p.input_dir = normalized(v) if abs(v) > 1.0 else 0j

    @staticmethod
    def _arrive(p, target):
        cmd = ((target - p.pos) - p.vel * 20.0) / 30.0
        l = abs(cmd)
        p.input_dir = cmd / l if l > 1.0 else cmd

