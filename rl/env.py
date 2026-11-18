"""One RL episode source on top of the match core (soccer.match): the learner controls players of team 0 with ONE shared
policy (one observation per player, soccer/ai/nets.py). With `with_keeper` the goalkeeper slot is a normal learner player
too: no rule-based keeper, no fixed formation. The rule-based players (opponents, a kept keeper) are played by the match AI.
Line-by-line port of the Godot environment (rl/rl_env.gd), checked step by step against it (tests/test_env.py).

Config (configure()):
  n_active     number of learner-controlled players (1..5); the rest of team 0 is removed ("ghosts")
  with_keeper  true -> the keeper slot (slot 0) is one of the controlled players
  opp          "none"    empty goal: team 1 removed from the physics
               "keeper"  only team 1's rule-based keeper stays (outfield removed)
               "a,b,c"   a full rule-based team 1, drawn per episode from this pool of team ids
  match_mode   false -> first-goal episodes from random starts (curriculum stages)
               true  -> a real match: kickoffs, both teams complete, ends at the final whistle
  duration     match length in seconds (match_mode)
  selfplay     probability that team 1 is driven by `opp_net` (all 5 players incl. keeper) instead of rules
  own_team     id of the learner's team (only matters for a rule-based keeper / lineup)"""
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from soccer.ai import nets                                           # noqa: E402
from soccer.data import database                                     # noqa: E402
from soccer.match import ENDED, GOAL, HIST, PLAYING, Match, MatchConfig   # noqa: E402
from soccer.rng import RandomNumberGenerator                         # noqa: E402

REPEAT = 2                 # sim ticks per decision (same as the match's AI_PERIOD)
OUT_NONE, OUT_GOAL, OUT_OWN, OUT_TIMEOUT, OUT_CONCEDED, OUT_WIN, OUT_DRAW, OUT_LOSS = range(8)
OBS_LEGACY = 54            # ego observation with the slot one-hot (the first RL teams)
OBS_TEAM = 46              # role-free team observation (features_team)

DEFAULTS = dict(pitch="arena", size=5, n_active=5, with_keeper=True, opp="none", own_team="owls", max_steps=750, spread=1.0,
                ball_speed=0.0, match_mode=False, duration=90.0, selfplay=0.0, shaping=1.0, opp_external=False,
                w_pass_prog=0.0, w_pass_ok=0.0, w_pass_fail=0.0, w_key_pass=0.0, w_xa=0.0, pass_individual=False, w_recv=0.0,
                w_open=0.0, random_start=0.0, coop_cap=0.0, w_keeper=0.0, keeper_free=350.0, open_min=120.0, open_max=450.0,
                w_space=0.0, space_radius=140.0, w_kick=0.0, w_jitter=0.0, w_far=0.0, w_wall=0.0, w_corner=0.0, corner_zone=150.0,
                obs="legacy", w_xg=0.0, xg_cap=6.0, w_xga=0.0, w_win=0.0, w_draw=0.0, w_tackle=0.0, def_cap=2.0, w_goalside=0.0,
                goalside_lane=120.0, w_opp_half=0.0, w_compact=0.0, compact_len=700.0, compact_wid=450.0, far_radius=600.0)
LANE_CLEAR = 45.0
KICK_REACH = 40.0


def _seg_dist(p, a, b):
    ab = b - a
    l2 = ab.real * ab.real + ab.imag * ab.imag
    if l2 < 0.0001:
        return abs(p - a)
    t = ((p - a).real * ab.real + (p - a).imag * ab.imag) / l2
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return abs(p - (a + ab * t))


class RLEnv:
    def __init__(self):
        for k, v in DEFAULTS.items():
            setattr(self, k, v)
        self.opp_pool = []
        self.own_keeper = True
        self.opp_net = None              # net spec of the self-play opponent ({"model": path} or {"dict": game model}), None = none
        self.external_actions = False
        self.rng = RandomNumberGenerator()
        self.sim = None
        self.agents = []
        self.opp_agents = []
        self.steps = 0
        self.ep_return = 0.0
        self.prev_pot = 0.0
        self.prev_scores = [0, 0]
        self.prev_playing = True
        self.episode_id = 0
        self.used_selfplay = False
        self.coop_used = self.xg_used = self.def_used = 0.0
        self.prev_ps, self.prev_def, self.prev_dir, self.wall_streak = {}, {}, {}, {}
        self.prev_pass = [0, 0, 0, 0, 0.0]
        self.prev_opp_xg = 0.0
        self.term_sums = {}
        self.term_steps = 0

    # names in the config dict are the attribute names, except "pitch" / "size" / "obs" (kept as is)
    def configure(self, c):
        for k, v in DEFAULTS.items():
            if k in c:
                cur = getattr(self, k)
                setattr(self, k, type(v)(c[k]) if not isinstance(v, bool) else bool(c[k]))
        self.opp = str(c.get("opp", self.opp))
        self.opp_pool = [x for x in self.opp.split(",") if x] if self.opp not in ("none", "keeper") else []
        self.own_keeper = bool(c.get("own_keeper", self.opp != "none"))
        if "seed" in c:
            self.rng.seed = int(c["seed"])

    def obs_dim(self):
        """Observation layout (config "obs"): "legacy" = 54 numbers with slot, "team" = the 46-number role-free one,
        "both" = team then legacy (100 numbers; only for distilling an old net into a new one, rl/distill.py)."""
        return {"legacy": OBS_LEGACY, "team": OBS_TEAM, "both": OBS_TEAM + OBS_LEGACY}[self.obs]

    def n_agents(self):
        """Learner agents first, then (self-play) the opponent team's players."""
        return self.n_active + (self.size if self.opp_external else 0)

    def reset(self):
        self.coop_used = self.xg_used = self.def_used = 0.0
        db = database()
        cfg = MatchConfig()
        cfg.pitch = db.pitches[self.pitch]
        cfg.team_size = self.size
        cfg.duration = self.duration if self.match_mode else 600.0
        cfg.match_seed = self.rng.randi()
        opp_id = self.own_team
        if self.opp_pool:
            opp_id = self.opp_pool[self.rng.randi() % len(self.opp_pool)]
        cfg.teams = [db.teams[self.own_team], db.teams[opp_id]]
        self.used_selfplay = self.opp_net is not None and self.rng.randf() < self.selfplay
        if self.used_selfplay:
            cfg.nets[1] = self.opp_net
        sim = self.sim = Match(cfg)
        self.episode_id += 1
        self.steps = 0
        self.ep_return = 0.0
        # learner team: controlled players, the rest are ghosts (or the rule-based keeper)
        self.agents = []
        ghosts = []
        ordered = []
        for p in sim.team_lists[0]:
            if p.role == "GK":
                ordered.insert(0, p)
            else:
                ordered.append(p)
        for p in ordered:
            is_gk = p.role == "GK"
            if len(self.agents) < self.n_active and (self.with_keeper or not is_gk):
                self.agents.append(p)
                p.bot = False
            elif is_gk and self.own_keeper and not self.with_keeper:
                pass                                    # stays a rule-based keeper
            else:
                ghosts.append(p)
        self.opp_agents = []
        if self.opp_external:
            ordered1 = []
            for p in sim.team_lists[1]:
                if p.role == "GK":
                    ordered1.insert(0, p)
                else:
                    ordered1.append(p)
            for p in ordered1:
                self.opp_agents.append(p)
                p.bot = False
        if self.opp == "none":
            ghosts += list(sim.team_lists[1])
        elif self.opp == "keeper":
            ghosts += [p for p in sim.team_lists[1] if p.role != "GK"]
        for g in ghosts:
            self._ghost(g)
        if self.match_mode:
            sim.kickoff_team = self.rng.randi() % 2
            sim._reset_positions()
            if self.random_start > 0.0 and self.rng.randf() < self.random_start:
                self._random_layout()
        else:
            self._random_start()
        self.prev_pot = self._potential()
        self.prev_scores = [0, 0]
        self.prev_playing = True
        self.prev_pass = self._pass_totals()
        self.prev_ps = {}
        self.prev_dir = {}
        self.wall_streak = {}
        self.prev_def = {}
        self.prev_opp_xg = self._team_xg(1)
        for a in self.agents:
            self.prev_ps[a.uid] = self._ps_vec(a)
            self.prev_def[a.uid] = self._def_vec(a)

    def _ghost(self, g):
        """Removes a player from the physics and the rule logic but keeps it in team_lists (observations)."""
        g.bot = False
        if g in self.sim.movers:
            self.sim.movers.remove(g)
        if g in self.sim.players:
            self.sim.players.remove(g)
        g.pos = complex(0.0, self.sim.pitch.out_y * 2.5)
        g.vel = 0j

    def _random_layout(self):
        """Match-mode variant: every player (both teams, keepers too) and the ball anywhere on the pitch, play starts at once."""
        sim, rng = self.sim, self.rng
        sim.kickoff_active = False
        sim.kickoff_taker = None
        sim.state = PLAYING
        hw, hh = sim.pitch.half_w * 0.92, sim.pitch.half_h * 0.92
        sim.ball.pos = complex(rng.randf_range(-hw, hw), rng.randf_range(-hh, hh))
        a = rng.randf() * math.tau
        sim.ball.vel = complex(math.cos(a), math.sin(a)) * rng.randf_range(0.0, 3.0)
        placed = [sim.ball.pos]
        for p in sim.players:
            pos = 0j
            for _ in range(40):
                pos = complex(rng.randf_range(-hw, hw), rng.randf_range(-hh, hh))
                if all(abs(q - pos) >= 45.0 for q in placed):
                    break
            p.pos = pos
            p.vel = 0j
            placed.append(pos)

    def _random_start(self):
        sim, rng = self.sim, self.rng
        sim.kickoff_active = False
        sim.kickoff_taker = None
        sim.state = PLAYING
        hw, hh = sim.pitch.half_w, sim.pitch.half_h
        bx = rng.randf_range(-hw * 0.6, hw * (0.15 + 0.45 * self.spread))
        if self.spread < 0.2:
            bx = rng.randf_range(0.0, hw * 0.35)
        sim.ball.pos = complex(bx, rng.randf_range(-hh * 0.8, hh * 0.8))
        sp = rng.randf_range(0.0, self.ball_speed)
        a = rng.randf() * math.tau
        sim.ball.vel = complex(math.cos(a), math.sin(a)) * sp
        placed = [sim.ball.pos]
        for p in list(sim.players):
            if p.team == 1 and p.role == "GK":
                p.pos = p.spawn                       # an opposing keeper starts on its line
                p.vel = 0j
                placed.append(p.pos)
                continue
            pos = 0j
            for _ in range(40):
                pos = complex(rng.randf_range(-hw * 0.9, hw * 0.5), rng.randf_range(-hh * 0.9, hh * 0.9))
                if p.team == 1:
                    pos = complex(-pos.real, pos.imag)
                if all(abs(q - pos) >= 45.0 for q in placed):
                    break
            p.pos = pos
            p.vel = 0j
            p.input_dir = 0j
            p.input_kick = False
            p.in_contact = False
            placed.append(pos)
        sim.last_touch = None
        sim.assist_cand = None
        sim.pending_shot_team = -1
        sim.ball_hist = [sim.ball.pos] * HIST

    def _potential(self):
        """Shaping potential: ball close to the opponent goal, nearest agent close to the ball."""
        hw = self.sim.pitch.half_w
        d_goal = abs(self.sim.ball.pos - complex(hw, 0.0))
        near = 1.0e9
        for a in self.agents:
            near = min(near, abs(a.pos - self.sim.ball.pos))
        return self.shaping * (-4.0 * d_goal / hw - 4.0 * min(near, hw) / hw)

    def _pass_totals(self):
        prog = ok = fail = kp = 0
        xa = 0.0
        for p in self.sim.team_lists[0]:
            prog += p.ps.progressive_passes
            ok += p.ps.passes_ok
            fail += p.ps.passes_failed
            kp += p.ps.key_passes
            xa += p.ps.xa
        return [prog, ok, fail, kp, xa]

    @staticmethod
    def _ps_vec(p):
        return [p.ps.passes_ok, p.ps.passes_failed, p.ps.progressive_passes, p.ps.key_passes, p.ps.xa, p.ps.passes_received]

    @staticmethod
    def _def_vec(a):
        return [a.ps.tackles + a.ps.interceptions, a.ps.xg]

    def _team_xg(self, team):
        return sum(p.ps.xg for p in self.sim.team_lists[team])

    def _opp_has_ball(self):
        return self.sim.last_touch is not None and self.sim.last_touch.team == 1

    def _we_have_ball(self):
        return self.sim.last_touch is not None and self.sim.last_touch.team == 0

    def _stretch(self):
        """0..1: how far the 4 outfield players are stretched beyond compact_len (along the pitch) and compact_wid (across)."""
        lo_x = lo_y = 1.0e9
        hi_x = hi_y = -1.0e9
        n = 0
        for a in self.agents:
            if a.role == "GK":
                continue
            qx, qy = a.pos.real * self.sim.attack_dir(0), a.pos.imag
            lo_x, lo_y, hi_x, hi_y = min(lo_x, qx), min(lo_y, qy), max(hi_x, qx), max(hi_y, qy)
            n += 1
        if n < 2:
            return 0.0
        c = lambda x: 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)
        return 0.5 * (c((hi_x - lo_x - self.compact_len) / self.compact_len) + c((hi_y - lo_y - self.compact_wid) / self.compact_wid))

    def _acc(self, term, value):
        """Adds `value` (already a per-agent mean) to a reward term's running total (what the reward is made of)."""
        if value != 0.0:
            self.term_sums[term] = self.term_sums.get(term, 0.0) + value

    def _individual(self):
        """Individual reward terms, one per learner agent: kick discipline, spacing, pass credit (passer / receiver) and
        "standing open" for the ball carrier."""
        sim = self.sim
        out = [0.0] * (len(self.agents) + len(self.opp_agents))
        credit = self.match_mode and self.pass_individual
        if self.w_kick == 0.0 and self.w_space == 0.0 and not credit and self.w_open == 0.0 and self.w_keeper == 0.0 \
                and self.w_jitter == 0.0 and self.w_far == 0.0 and self.w_xg == 0.0 and self.w_tackle == 0.0 \
                and self.w_goalside == 0.0 and self.w_wall == 0.0 and self.w_corner == 0.0:
            return out
        bp = sim.ball.pos
        pd = sim.pitch
        ball_in_corner = abs(bp.real) > pd.half_w - self.corner_zone and abs(bp.imag) > pd.half_h - self.corner_zone
        n_learn = float(len(self.agents))
        # the carrier: the learner agent that last touched the ball and is next to it
        carrier = None
        lt = sim.last_touch
        if self.w_open > 0.0 and lt is not None and lt.team == 0 and lt in self.agents and abs(lt.pos - bp) < 45.0:
            carrier = lt
        for i, a in enumerate(self.agents):
            da = abs(a.pos - bp)
            r = 0.0
            if self.w_kick > 0.0 and a.input_kick and da > KICK_REACH:
                r -= self.w_kick
                self._acc("kick", -self.w_kick / n_learn)
            if self.w_jitter > 0.0:
                dnow = a.input_dir
                if abs(dnow) > 0.1:
                    dprev = self.prev_dir.get(a.uid, dnow)
                    u, w = dprev / abs(dprev) if abs(dprev) > 0 else 0j, dnow / abs(dnow)
                    if u.real * w.real + u.imag * w.imag < 0.5:
                        r -= self.w_jitter
                        self._acc("jitter", -self.w_jitter / n_learn)
                    self.prev_dir[a.uid] = dnow
            if self.w_space > 0.0 and da > 70.0 and self._we_have_ball():   # spreading out is for attacking
                for j, b in enumerate(self.agents):
                    if j != i:
                        d = abs(a.pos - b.pos)
                        if d < self.space_radius and abs(b.pos - bp) > 70.0:
                            r -= self.w_space * (1.0 - d / self.space_radius)
                            self._acc("space", -self.w_space * (1.0 - d / self.space_radius) / n_learn)
            if self.w_far > 0.0 and a.role != "GK" and da > self.far_radius:   # an outfield player far away from the play
                pen = self.w_far * min((da - self.far_radius) / self.far_radius, 1.0)
                r -= pen
                self._acc("far", -pen / n_learn)
            if self.w_wall > 0.0:                                     # pressed against the outer wall (the edge of the arena)
                at_wall = abs(a.pos.real) >= pd.out_x - a.radius - 3.0 or abs(a.pos.imag) >= pd.out_y - a.radius - 3.0
                streak = self.wall_streak.get(a.uid, 0) + 1 if at_wall else 0
                self.wall_streak[a.uid] = streak
                if streak >= 2:
                    r -= self.w_wall
                    self._acc("wall", -self.w_wall / n_learn)
            if self.w_corner > 0.0 and ball_in_corner and lt is not None and lt.team == 0:
                r -= self.w_corner                                    # our team pushed the ball into a corner
                self._acc("corner", -self.w_corner / n_learn)
            if self.w_xg > 0.0 or self.w_tackle > 0.0:
                cd = self._def_vec(a)
                pdv = self.prev_def.get(a.uid, cd)
                if self.w_xg > 0.0:                                   # shot quality: a clear chance pays, a hopeful long shot hardly
                    gain_xg = min(self.w_xg * (cd[1] - pdv[1]), max(self.xg_cap - self.xg_used, 0.0))
                    self.xg_used += gain_xg
                    r += gain_xg
                    self._acc("xg", gain_xg / n_learn)
                if self.w_tackle > 0.0:
                    gain_t = min(self.w_tackle * float(cd[0] - pdv[0]), max(self.def_cap - self.def_used, 0.0))
                    self.def_used += gain_t
                    r += gain_t
                    self._acc("tackle", gain_t / n_learn)
                self.prev_def[a.uid] = cd
            if self.w_goalside > 0.0 and a.role != "GK" and self._opp_has_ball():
                own_goal = complex(-pd.half_w * sim.attack_dir(0), 0.0)
                if abs(a.pos - own_goal) < abs(bp - own_goal) and _seg_dist(a.pos, bp, own_goal) < self.goalside_lane:
                    r += self.w_goalside
                    self._acc("goalside", self.w_goalside / n_learn)
            if credit:
                cur = self._ps_vec(a)
                prev = self.prev_ps.get(a.uid, cur)
                d_ok, d_fail, d_prog, d_kp = cur[0] - prev[0], cur[1] - prev[1], cur[2] - prev[2], cur[3] - prev[3]
                d_xa, d_recv = cur[4] - prev[4], cur[5] - prev[5]
                r += self.w_pass_prog * d_prog - self.w_pass_fail * d_fail
                self._acc("pass_prog", self.w_pass_prog * d_prog / n_learn)
                self._acc("pass_fail", -self.w_pass_fail * d_fail / n_learn)
                coop = self.w_pass_ok * max(d_ok - d_prog, 0) + self.w_key_pass * d_kp + self.w_xa * d_xa + self.w_recv * d_recv
                if self.coop_cap > 0.0 and coop > 0.0:
                    coop = min(coop, max(self.coop_cap - self.coop_used, 0.0))
                    self.coop_used += coop
                r += coop
                self._acc("coop", coop / n_learn)
                self.prev_ps[a.uid] = cur
            if self.w_keeper > 0.0 and a.role == "GK":
                dg = abs(a.pos - complex(-pd.half_w, 0.0))
                if dg > self.keeper_free:
                    r -= self.w_keeper * min((dg - self.keeper_free) / self.keeper_free, 1.0)
                    self._acc("keeper", -self.w_keeper * min((dg - self.keeper_free) / self.keeper_free, 1.0) / n_learn)
            if carrier is not None and a is not carrier:
                dc = abs(a.pos - carrier.pos)
                if self.open_min <= dc <= self.open_max:
                    if all(_seg_dist(o.pos, carrier.pos, a.pos) >= LANE_CLEAR for o in sim.team_lists[1]):
                        r += self.w_open
                        self._acc("open", self.w_open / n_learn)
            out[i] = r
        return out

    def observe(self):
        """The observations of all agents (learners, then the self-play opponents), concatenated."""
        out = []
        for a in self.agents + self.opp_agents:
            if self.obs != "legacy":
                out += nets.features_team(self.sim, a)
            if self.obs != "team":
                out += nets.features(self.sim, a, True)
        return out

    def step(self, actions):
        """actions: move idx (0..8) and kick (0/1) per agent, flat [m0, k0, m1, k1, ...].
        Returns (reward, done, outcome, individual rewards). Does NOT auto-reset."""
        sim = self.sim
        all_agents = self.agents + self.opp_agents
        if not self.external_actions:
            for i, a in enumerate(all_agents):
                sim.set_action(a, min(max(int(actions[i * 2]), 0), 8), int(actions[i * 2 + 1]) != 0)
                a.kick_intent = ""
        for _ in range(REPEAT):
            sim.step()
            if not self.match_mode and sim.state != PLAYING:
                break
            if sim.state == ENDED:
                break
        self.steps += 1
        r = -0.0005
        self.term_steps += 1
        self._acc("time", -0.0005)
        done = False
        outcome = OUT_NONE
        playing = sim.state == PLAYING
        pot = self._potential()
        if playing and self.prev_playing:
            r += pot - self.prev_pot                       # no shaping across goals / kickoffs (the ball teleports)
            self._acc("shaping", pot - self.prev_pot)
        self.prev_pot = pot
        self.prev_playing = playing
        if self.match_mode:
            goal_r = 10.0 * (sim.scores[0] - self.prev_scores[0]) - 10.0 * (sim.scores[1] - self.prev_scores[1])
            r += goal_r
            self._acc("goals", goal_r)
            if self.w_xga > 0.0:                           # chances the opponent created, scored or not
                oxg = self._team_xg(1)
                r -= self.w_xga * (oxg - self.prev_opp_xg)
                self._acc("xga", -self.w_xga * (oxg - self.prev_opp_xg))
                self.prev_opp_xg = oxg
            if playing:
                if self.w_opp_half > 0.0 and self._opp_has_ball() and sim.ball.pos.real * sim.attack_dir(0) < 0.0:
                    r -= self.w_opp_half
                    self._acc("opp_half", -self.w_opp_half)
                if self.w_compact > 0.0:
                    stretch = self._stretch()
                    r -= self.w_compact * stretch
                    self._acc("compact", -self.w_compact * stretch)
            self.prev_scores = [sim.scores[0], sim.scores[1]]
            if sim.state == ENDED or self.steps >= self.max_steps:
                done = True
                outcome = OUT_WIN if sim.scores[0] > sim.scores[1] else (OUT_LOSS if sim.scores[0] < sim.scores[1] else OUT_DRAW)
                bonus = self.w_win if outcome == OUT_WIN else (self.w_draw if outcome == OUT_DRAW else 0.0)
                r += bonus
                self._acc("result", bonus)
        else:
            if sim.scores[0] > 0:
                r += 10.0
                done = True
                outcome = OUT_GOAL
            elif sim.scores[1] > 0:
                r -= 10.0
                done = True
                outcome = OUT_OWN if self.opp == "none" else OUT_CONCEDED
            elif self.steps >= self.max_steps:
                done = True
                outcome = OUT_TIMEOUT
        if self.match_mode and not self.pass_individual and (self.w_pass_prog != 0.0 or self.w_pass_ok != 0.0
                                                             or self.w_pass_fail != 0.0 or self.w_key_pass != 0.0 or self.w_xa != 0.0):
            pt = self._pass_totals()
            d_prog, d_ok, d_fail = pt[0] - self.prev_pass[0], pt[1] - self.prev_pass[1], pt[2] - self.prev_pass[2]
            # progressive passes are a subset of the completed ones: pay the bonus rate for those, the base rate for the rest
            pr = self.w_pass_prog * d_prog + self.w_pass_ok * max(d_ok - d_prog, 0) - self.w_pass_fail * d_fail
            pr2 = self.w_key_pass * (pt[3] - self.prev_pass[3]) + self.w_xa * (pt[4] - self.prev_pass[4])
            r += pr
            r += pr2
            self._acc("pass_team", pr + pr2)
            self.prev_pass = pt
        self.ep_return += r
        return r, done, outcome, self._individual()
