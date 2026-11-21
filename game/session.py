"""A live match in the browser: the match core plays it in real time (60 ticks/s) and every tick is sent to the page; the page
sends the keyboard back. One WebSocket per match (web/ws.py).

Page -> server (JSON):
  {"setup": {...}, "puzzle": seed?}        first message: the match (game/api.py setup; "record": true saves the human's play as a
                                           dataset file, game/recorder.py). With "puzzle": a random layout of every player and the
                                           ball (Match.puzzle_layout), a short "get ready" hold, and the round ends PUZZLE_GOAL_TICKS
                                           after the first goal (or at the final whistle); setup "player": "random" = the human
                                           controls a random player of their team (keeper included). The Puzzle page plays rounds of
                                           these back to back.
  {"in": [dx, dy, kick]}                   the human's keys (direction normalised by the page), sent when they change
  {"switch": 1}                            TEAM control: hand control to the teammate nearest the ball
  {"pause": true|false}  {"speed": 1|2|4|8}  {"quit": 1}
Server -> page:
  {"k": "m", ...}   once: teams (kits, logos), players, pitch, statics
  {"k": "f", ...}   every tick while playing (see frame())
  {"k": "r", "result": {...}}   once, after the final whistle
  {"k": "e", "error": "..."}    the match could not start

Kickoff intro (as the Godot game): at every kickoff the match is held for INTRO_TICKS while the page zooms in."""
import random
import time

from game import api, recorder
from soccer.match import ENDED, GOAL, PLAYING, SINGLE, Match

TICK = 1.0 / 60.0
INTRO_TICKS = 130
PUZZLE_READY = 75                 # ticks the puzzle's random layout is shown before play starts
PUZZLE_GOAL_TICKS = 100           # a puzzle round ends this long after the first goal (the banner is half shown)


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
    """Plays one match on an accepted WebSocket until it closes. A recorded match is saved when it ends, or when the page quits
    or disconnects (if long enough)."""
    rec = []
    try:
        _run(ws, rec)
    finally:
        if rec and not rec[0].saved:
            try:
                rec[0].save()
            except Exception as e:                          # never let a failed save break the game server
                print("recorder: could not save (%s: %s)" % (type(e).__name__, e), flush=True)


def _run(ws, rec):
    first = None
    while first is None:
        msgs = ws.poll(30.0)
        if not msgs:
            return
        first = next((x for x in msgs if isinstance(x, dict) and "setup" in x), None)
    try:
        m = Match(api.config(first["setup"]))
        puzzle = first.get("puzzle") is not None
        if puzzle:
            m.puzzle_layout(int(first["puzzle"]))
            if first["setup"].get("player") == "random" and m.cfg.control == SINGLE:
                m.set_controlled(random.Random(int(first["puzzle"])).choice(m.team_lists[m.cfg.human_team]))
    except Exception as e:                                  # bad setup: tell the page
        ws.send({"k": "e", "error": "%s: %s" % (type(e).__name__, e)})
        ws.close()
        return
    if recorder.wanted(first["setup"], m):
        rec.append(recorder.Recorder(m, {**first["setup"], "puzzle": first.get("puzzle")}, min_rows=30 if puzzle else recorder.MIN_ROWS))
    ws.send({**meta(m), "rec": bool(rec)})
    human, switch, paused, speed = (0j, False), False, False, 1
    intro, intro_id, result_sent = (PUZZLE_READY if puzzle else 0), -1, False
    goal_end = None
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
                if rec and rec[0].due():
                    rec[0].sample(*human, speed)
                m.step()
                if puzzle and goal_end is None and m.state == GOAL:
                    goal_end = m.tick + PUZZLE_GOAL_TICKS
            events = m.events[n_ev:]
        ws.send(frame(m, intro, events))
        if (m.state == ENDED or goal_end is not None and m.tick >= goal_end) and not result_sent:
            result = m.make_result()
            if puzzle:
                result["puzzle"] = {"end": "goal" if goal_end is not None else "time", "seconds": round(m.elapsed(), 2)}
            if rec:
                try:
                    rec[0].save(result)
                except Exception as e:
                    print("recorder: could not save (%s: %s)" % (type(e).__name__, e), flush=True)
            ws.send({"k": "r", "result": result})
            result_sent = True
