"""The complete state of a match as one vector of floats, in the layout tests/godot/record_match.gd writes for Godot's
MatchSim: load a Godot state into Python's soccer.match.Match, step, export, compare."""
from soccer.stats import FIELDS_FLOAT, FIELDS_INT

KINDS = ["", "touch", "pass", "shot", "clear"]
INTENTS = ["", "pass", "shoot", "clear", "long"]
HIST = 32

SCALARS = ["tick", "state", "score0", "score1", "time_left", "overtime", "ot_left", "goal_timer", "goal_scorer", "goal_pause",
           "goal_center_x", "goal_center_y", "goal_team", "winner", "kickoff_active", "kickoff_team", "kickoff_taker",
           "kickoff_dir_x", "kickoff_dir_y", "kickoff_go", "kickoff_start", "last_touch", "last_touch_tick", "last_touch_kicked",
           "last_touch_kind", "assist_cand", "assist_tick", "pending_shot_team", "pending_shot_tick", "pending_shot_player",
           "pending_shot_xg", "last_shot_xg", "last_shot_player", "carry_p", "carry_start_x", "carry_start_y", "carry_last_x",
           "carry_last_y", "carry_pressed", "kick_pos_x", "kick_pos_y", "kick_dir_x", "kick_dir_y", "kick_pressed",
           "team_touch_player0", "team_touch_player1", "team_touch_tick0", "team_touch_tick1", "hist_idx", "idle_ticks",
           "zone0", "zone1", "zone2", "zone3", "zone4", "possession0", "possession1", "controlled", "human_dir_x", "human_dir_y",
           "human_kick", "keeper0", "keeper1", "reset_count", "rng_lo", "rng_hi", "mom_uid", "n_events", "n_kickoff_waits",
           "shootout0", "shootout1", "ball_x", "ball_y", "ball_vx", "ball_vy"]
SCALARS += ["hist%d_%s" % (i, c) for i in range(HIST) for c in "xy"]
PLAYER = ["x", "y", "vx", "vy", "in_x", "in_y", "input_kick", "kick_used", "in_contact", "rec_tick", "is_human", "bot",
          "kick_intent"] + list(FIELDS_INT) + list(FIELDS_FLOAT)

# continuous quantities (compared with a tolerance: Godot keeps positions in 32-bit floats); everything else must be equal
FLOATS = {"time_left", "ot_left", "goal_center_x", "goal_center_y", "kickoff_dir_x", "kickoff_dir_y", "pending_shot_xg",
          "last_shot_xg", "carry_start_x", "carry_start_y", "carry_last_x", "carry_last_y", "kick_pos_x", "kick_pos_y",
          "kick_dir_x", "kick_dir_y", "human_dir_x", "human_dir_y", "ball_x", "ball_y", "ball_vx", "ball_vy"}
FLOATS |= {"hist%d_%s" % (i, c) for i in range(HIST) for c in "xy"}
PLAYER_FLOATS = {"x", "y", "vx", "vy", "in_x", "in_y"} | set(FIELDS_FLOAT)


def names(n_players):
    """Field names of the vector for a match with n_players players (team 0 then team 1, slot order)."""
    out = list(SCALARS)
    for i in range(n_players):
        out += ["p%d.%s" % (i, k) for k in PLAYER]
    return out


def is_float(name):
    return name.split(".")[-1] in PLAYER_FLOATS if "." in name else name in FLOATS


def _uid(p):
    return p.uid if p is not None else -1


def export_state(m):
    v = [m.tick, m.state, m.scores[0], m.scores[1], m.time_left, float(m.overtime), m.ot_left, m.goal_timer, _uid(m.goal_scorer),
         m.goal_pause, m.goal_center.real, m.goal_center.imag, m.goal_team, m.winner, float(m.kickoff_active), m.kickoff_team,
         _uid(m.kickoff_taker), m.kickoff_dir.real, m.kickoff_dir.imag, m.kickoff_go, m.kickoff_start, _uid(m.last_touch),
         m.last_touch_tick, float(m.last_touch_kicked), KINDS.index(m.last_touch_kind), _uid(m.assist_cand), m.assist_tick,
         m.pending_shot_team, m.pending_shot_tick, _uid(m.pending_shot_player), m.pending_shot_xg, m.last_shot_xg,
         _uid(m.last_shot_player), _uid(m.carry_p), m.carry_start.real, m.carry_start.imag, m.carry_last.real, m.carry_last.imag,
         float(m.carry_pressed), m.kick_pos.real, m.kick_pos.imag, m.kick_dir.real, m.kick_dir.imag, float(m.kick_pressed),
         _uid(m.team_touch_player[0]), _uid(m.team_touch_player[1]), m.team_touch_tick[0], m.team_touch_tick[1], m.hist_idx,
         m.idle_ticks] + list(m.zone_ticks) + [
        m.stats.possession_ticks[0], m.stats.possession_ticks[1], _uid(m.controlled), m.human_dir.real, m.human_dir.imag,
        float(m.human_kick), m.keeper_uid[0], m.keeper_uid[1], m.reset_count, m.rng.state & 0xffffffff, m.rng.state >> 32,
        m.mom_uid, len(m.events), len(m.kickoff_waits), m.shootout[0] if len(m.shootout) == 2 else -1,
        m.shootout[1] if len(m.shootout) == 2 else -1, m.ball.pos.real, m.ball.pos.imag, m.ball.vel.real, m.ball.vel.imag]
    for h in m.ball_hist:
        v += [h.real, h.imag]
    for t in (0, 1):
        for p in m.team_lists[t]:
            v += [p.pos.real, p.pos.imag, p.vel.real, p.vel.imag, p.input_dir.real, p.input_dir.imag, float(p.input_kick),
                  float(p.kick_used), float(p.in_contact), p.rec_tick, float(p.is_human), float(p.bot), INTENTS.index(p.kick_intent)]
            v += [getattr(p.ps, k) for k in FIELDS_INT] + [getattr(p.ps, k) for k in FIELDS_FLOAT]
    return [float(x) for x in v]


def import_state(m, v, events=None, kickoff_waits=None):
    """Loads a Godot state vector into the Python match (events / kickoff waits: the recorded lists, cut to the counts)."""
    d = dict(zip(names(len(m.team_lists[0]) + len(m.team_lists[1])), v))     # ghosts (RL training) included
    P = lambda k: m.by_uid.get(int(d[k]))
    i = lambda k: int(d[k])
    c = lambda k: complex(d[k + "_x"], d[k + "_y"])
    m.tick, m.state, m.scores = i("tick"), i("state"), [i("score0"), i("score1")]
    m.time_left, m.overtime, m.ot_left = d["time_left"], bool(d["overtime"]), d["ot_left"]
    m.goal_timer, m.goal_scorer, m.goal_pause = i("goal_timer"), P("goal_scorer"), i("goal_pause")
    m.goal_center, m.goal_team, m.winner = c("goal_center"), i("goal_team"), i("winner")
    m.kickoff_active, m.kickoff_team, m.kickoff_taker = bool(d["kickoff_active"]), i("kickoff_team"), P("kickoff_taker")
    m.kickoff_dir, m.kickoff_go, m.kickoff_start = c("kickoff_dir"), i("kickoff_go"), i("kickoff_start")
    m.last_touch, m.last_touch_tick, m.last_touch_kicked = P("last_touch"), i("last_touch_tick"), bool(d["last_touch_kicked"])
    m.last_touch_kind = KINDS[i("last_touch_kind")]
    m.assist_cand, m.assist_tick = P("assist_cand"), i("assist_tick")
    m.pending_shot_team, m.pending_shot_tick, m.pending_shot_player = i("pending_shot_team"), i("pending_shot_tick"), P("pending_shot_player")
    m.pending_shot_xg, m.last_shot_xg, m.last_shot_player = d["pending_shot_xg"], d["last_shot_xg"], P("last_shot_player")
    m.carry_p, m.carry_start, m.carry_last, m.carry_pressed = P("carry_p"), c("carry_start"), c("carry_last"), bool(d["carry_pressed"])
    m.kick_pos, m.kick_dir, m.kick_pressed = c("kick_pos"), c("kick_dir"), bool(d["kick_pressed"])
    m.team_touch_player = [P("team_touch_player0"), P("team_touch_player1")]
    m.team_touch_tick = [i("team_touch_tick0"), i("team_touch_tick1")]
    m.hist_idx, m.idle_ticks = i("hist_idx"), i("idle_ticks")
    m.zone_ticks = [i("zone%d" % k) for k in range(5)]
    m.stats.possession_ticks = [i("possession0"), i("possession1")]
    ctrl = P("controlled")
    m.controlled = ctrl
    m.human_dir, m.human_kick = c("human_dir"), bool(d["human_kick"])
    m.keeper_uid = [i("keeper0"), i("keeper1")]
    m.reset_count = i("reset_count")
    m.rng.state = (i("rng_hi") << 32) | i("rng_lo")
    m.mom_uid = i("mom_uid")
    if events is not None:
        m.events = [dict(e) for e in events[:i("n_events")]]
    if kickoff_waits is not None:
        m.kickoff_waits = [int(x) for x in kickoff_waits[:i("n_kickoff_waits")]]
    m.shootout = [i("shootout0"), i("shootout1")] if i("shootout0") >= 0 else []
    m.ball.pos, m.ball.vel = complex(d["ball_x"], d["ball_y"]), complex(d["ball_vx"], d["ball_vy"])
    m.ball_hist = [complex(d["hist%d_x" % k], d["hist%d_y" % k]) for k in range(HIST)]
    k = 0
    for t in (0, 1):
        for p in m.team_lists[t]:
            g = lambda f: d["p%d.%s" % (k, f)]
            p.pos, p.vel = complex(g("x"), g("y")), complex(g("vx"), g("vy"))
            p.input_dir, p.input_kick, p.kick_used = complex(g("in_x"), g("in_y")), bool(g("input_kick")), bool(g("kick_used"))
            p.in_contact, p.rec_tick, p.is_human, p.bot = bool(g("in_contact")), int(g("rec_tick")), bool(g("is_human")), bool(g("bot"))
            p.kick_intent = INTENTS[int(g("kick_intent"))]
            for f in FIELDS_INT:
                setattr(p.ps, f, int(g(f)))
            for f in FIELDS_FLOAT:
                setattr(p.ps, f, float(g(f)))
            k += 1


def player_inputs(v, n_players):
    """Per player (setup order): (input_dir, input_kick, kick_intent) from a state vector."""
    d = dict(zip(names(n_players), v))
    return [(complex(d["p%d.in_x" % k], d["p%d.in_y" % k]), bool(d["p%d.input_kick" % k]), INTENTS[int(d["p%d.kick_intent" % k])])
            for k in range(n_players)]
