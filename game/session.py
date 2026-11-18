"""A live match in the browser: the match core plays it in real time (60 ticks/s) and every tick is sent to the page; the page
sends the keyboard back. One WebSocket per match (web/ws.py).

Page -> server (JSON):
  {"setup": {...}, "puzzle": seed?}        first message: the match (game/api.py setup)
  {"in": [dx, dy, kick]}                   the human's keys (direction normalised by the page), sent when they change
  {"switch": 1}                            TEAM control: hand control to the teammate nearest the ball
  {"pause": true|false}  {"speed": 1|2|4|8}  {"quit": 1}
Server -> page:
  {"k": "m", ...}   once: teams (kits, logos), players, pitch, statics
  {"k": "f", ...}   every tick while playing (see frame())
  {"k": "r", "result": {...}}   once, after the final whistle
  {"k": "e", "error": "..."}    the match could not start

Kickoff intro (as the Godot game): at every kickoff the match is held for INTRO_TICKS while the page zooms in."""
import math
import time

from game import api
from soccer.match import ENDED, PLAYING, Match

TICK = 1.0 / 60.0
INTRO_TICKS = 130


def meta(m):
    cfg, p = m.cfg, m.pitch
    raw = p.raw
    colors = raw.get("colors", {})
    kits = api.resolve_kits(*cfg.teams)
    teams = []
    for t in (0, 1):
        tm = cfg.teams[t]
        teams.append({"id": tm.id, "name": tm.name, "short": str(tm.raw.get("short", tm.name[:3].upper())), "kit": kits[t],
                      "pattern": str(tm.raw.get("kit", "solid")), "logo": tm.raw.get("logo", {}), "style": m.styles[t].name})
    return {"k": "m", "teams": teams, "control": cfg.control, "human_team": cfg.human_team, "duration": cfg.duration,
            "overtime": cfg.overtime, "ball_r": m.ball.radius,
            "players": [{"uid": q.uid, "team": q.team, "slot": q.slot, "role": q.role, "number": q.pdef.number, "name": q.pdef.name,
                         "r": q.radius} for t in (0, 1) for q in m.team_lists[t]],
            "pitch": {**{k: getattr(p, k) for k in ("half_w", "half_h", "goal_half", "net_depth", "out_x", "out_y", "center_r",
                                                    "box_depth", "box_half", "post_r")},
                      "stripes": int(raw.get("stripes", 0)), "pitch": str(colors.get("pitch", "718c5a")).lstrip("#"),
                      "outer": str(colors.get("outer", "5b7347")).lstrip("#"), "line": str(colors.get("line", "c7e6bd")).lstrip("#"),
                      "statics": [[s.pos.real, s.pos.imag, s.radius] for s in m.statics]},
            "warnings": list(getattr(m.ai, "warnings", []))}


def _uid(p):
    return p.uid if p is not None else -1


def frame(m, intro, events):
    pos, flags = [], []
    for t in (0, 1):
        for q in m.team_lists[t]:
            pos += [round(q.pos.real, 2), round(q.pos.imag, 2)]
            flags.append((1 if q.is_human else 0) | (2 if q.input_kick else 0) | (4 if q.kick_used else 0))
    return {"k": "f", "t": m.tick, "st": m.state, "sc": list(m.scores), "tl": m.time_left, "ot": bool(m.overtime), "otl": m.ot_left,
            "ko": bool(m.kickoff_active), "kt": m.kickoff_team, "gt": m.goal_team, "gs": _uid(m.goal_scorer), "gp": m.goal_pause,
            "gtm": m.goal_timer, "w": m.winner, "so": list(m.shootout) if len(m.shootout) == 2 else None, "cu": _uid(m.controlled),
            "in": intro, "b": [round(m.ball.pos.real, 2), round(m.ball.pos.imag, 2)], "p": pos, "h": flags, "ev": events}


def run(ws):
    """Plays one match on an accepted WebSocket until it closes."""
    first = None
    while first is None:
        msgs = ws.poll(30.0)
        if not msgs:
            return
        first = next((x for x in msgs if isinstance(x, dict) and "setup" in x), None)
    try:
        m = Match(api.config(first["setup"]))
        if first.get("puzzle") is not None:
            m.puzzle_layout(int(first["puzzle"]))
    except Exception as e:                                  # bad setup: tell the page
        ws.send({"k": "e", "error": "%s: %s" % (type(e).__name__, e)})
        ws.close()
        return
    ws.send(meta(m))
    human, switch, paused, speed = (0j, False), False, False, 1
    intro, intro_id, result_sent = 0, -1, False
    next_t = time.monotonic()
    ws.send(frame(m, intro, []))
    while True:
        msgs = ws.poll(next_t - time.monotonic())
        if msgs is None:
            return
        for x in msgs:
            if not isinstance(x, dict):
                continue
            if "in" in x:
                dx, dy, k = (list(x["in"]) + [0, 0, 0])[:3]
                d = complex(float(dx), float(dy))
                human = (d / abs(d) if abs(d) > 1e-9 else 0j, bool(k))
            if x.get("switch"):
                switch = True
            if "pause" in x:
                paused = bool(x["pause"])
            if "speed" in x and int(x["speed"]) in (1, 2, 4, 8):
                speed = int(x["speed"])
            if x.get("quit"):
                ws.close()
                return
        now = time.monotonic()
        if now < next_t:
            continue
        next_t += TICK
        if now - next_t > 0.25:                             # far behind (a busy machine): do not race to catch up
            next_t = now + TICK
        if paused or result_sent:
            continue
        events = []
        if m.state == PLAYING and m.kickoff_active and m.kickoff_start != intro_id:
            intro_id, intro = m.kickoff_start, INTRO_TICKS
        if intro > 0:
            intro -= 1
        else:
            if switch:
                m.switch_controlled()
                switch = False
            m.set_human_input(*human)
            n_ev = len(m.events)
            for _ in range(speed):
                if m.state == ENDED:
                    break
                m.step()
            events = m.events[n_ev:]
        ws.send(frame(m, intro, events))
        if m.state == ENDED and not result_sent:
            ws.send({"k": "r", "result": m.make_result()})
            result_sent = True
