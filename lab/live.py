"""The dashboard's live demo match (Live page): the newest checkpoint of the running experiment plays one match after another on
the match core, in real time, and every frame is streamed to lab/dashboard.py (UDP JSON to 127.0.0.1:7310), which relays it to
the browser. Started (and restarted if it stops) by lab/exp_runner.py --viewer while an experiment runs.
The stream is the Game's own (game/session.py meta / frame, with the same kickoff intro), so the Live page draws it with the Game's
renderer (web/game/render.js); this file adds only who plays (run, checkpoint, opponent, the rating ids of both sides).

  python3 lab/live.py --tag x_anchor_corner --start out_5v5/ckpt/t48_u100.json

Our team: RL Team 5's squad played by the newest out_5v5/ckpt/<tag>_u<N>.json (--start until the first checkpoint exists).
Opponent: logs/live_opponent.json (written by the dashboard's picker); "random" or missing = drawn for every match from the
handmade (rule-based) teams, RL Team 4/5, t48_u100, jit8 and the best checkpoint of every x_* run.
Mode: logs/live_mode.json "puzzle" = 60 s from a random layout of all players and the ball, over at the first goal; else a
90 s match. A change of opponent or mode ends the shown match at once."""
import argparse
import glob
import json
import os
import random
import re
import socket
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from game import session                               # noqa: E402
from soccer.data import database                       # noqa: E402
from soccer.match import ENDED, Match, make_config     # noqa: E402

LOGS = os.path.join(ROOT, "logs")
CKPT = os.path.join(ROOT, "out_5v5", "ckpt")
STREAM_PORT = 7310
FPS = 30                       # frames streamed per second; the match runs 60 ticks/s (2 ticks per frame)
OUR_TEAM = "rl_team_5"
NET_TEAM = "rl_team_4"         # squad used for a net opponent


def read_text(name):
    try:
        return open(os.path.join(LOGS, name)).read()
    except OSError:
        return ""


def newest_checkpoint(tag, fallback):
    best, path = -1, fallback
    for f in glob.glob(os.path.join(CKPT, tag + "_u*.json")):
        m = re.search(r"_u(\d+)\.json$", f)
        if m and int(m.group(1)) > best:
            best, path = int(m.group(1)), f
    return path


def last_update(tag):
    """Update number of the newest line of the training log (logs/<tag>.out), 0 before the first one."""
    try:
        with open(os.path.join(LOGS, tag + ".out"), "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 20000))
            found = re.findall(rb"upd (\d+) \|", f.read())
        return int(found[-1]) if found else 0
    except OSError:
        return 0


def opponent(rng):
    """{"team", "model" (None = rule-based), "label"} of the next match."""
    try:
        sel = json.loads(read_text("live_opponent.json"))
    except ValueError:
        sel = {}
    if not isinstance(sel, dict) or sel.get("kind", "random") == "random":
        pool = [{"kind": "rule", "team": t.id, "label": t.id.replace("_", " ").title()}
                for t in database().teams.values() if not t.ml_model]
        pool += [{"kind": "net", "model": "data/models/rl_5v5_arena_v4.json", "label": "RL Team 4"},
                 {"kind": "net", "model": "data/models/rl_5v5_arena_v5.json", "label": "RL Team 5"},
                 {"kind": "net", "model": "out_5v5/ckpt/t48_u100.json", "label": "Start net t48_u100"},
                 {"kind": "net", "model": "out_5v5/ckpt/jit8_best.json", "label": "jit8 (54-number)"}]
        for f in sorted(glob.glob(os.path.join(CKPT, "x_*_best.json"))):
            pool.append({"kind": "net", "model": os.path.relpath(f, ROOT), "label": "Run %s (best)" % os.path.basename(f)[2:-10]})
        pool = [p for p in pool if p["kind"] == "rule" or os.path.isfile(os.path.join(ROOT, p["model"]))]
        sel = rng.choice(pool)
    if sel.get("kind") == "rule" and sel.get("team") in database().teams:
        return {"team": sel["team"], "model": None, "label": sel.get("label", sel["team"])}
    model = sel.get("model") or "data/models/rl_5v5_arena_v4.json"
    if not os.path.isfile(os.path.join(ROOT, model)):
        model = "data/models/rl_5v5_arena_v4.json"
    return {"team": NET_TEAM, "model": model, "label": sel.get("label", "RL Team 4")}


def live_meta(m, tag, playing, opp, mode):
    """The Game's match meta plus who plays: our side is the run's newest checkpoint, the other side the opponent; `elo` = the rating
    entries the page looks the two sides up by (an id, else the net file)."""
    d = session.meta(m)
    run = tag[2:] if tag.startswith("x_") else tag
    d["teams"][0].update(name="%s · %s" % (run, playing.rsplit("_", 1)[-1]), short="RUN")
    if opp["model"]:
        d["teams"][1].update(name=opp["label"], short="NET")
    stem = lambda path: os.path.basename(path)[:-5] if path else ""
    d.update(id=m.cfg.match_seed, tag=tag, playing=playing, opponent=opp["label"], mode=mode, upd=last_update(tag),
             elo=[{"id": "net:" + playing, "model": ""},
                  {"id": "net:" + stem(opp["model"]) if opp["model"] else "team:" + opp["team"], "model": opp["model"] or ""}])
    return d


def play(tag, start, rng, sock):
    """One match (or puzzle), in real time. Returns when it is over and the result has been shown for a moment."""
    ckpt = newest_checkpoint(tag, start)
    opp = opponent(rng)
    mode = "puzzle" if "puzzle" in read_text("live_mode.json") else "match"
    choices = read_text("live_mode.json") + read_text("live_opponent.json")
    cfg = make_config(OUR_TEAM, opp["team"], "arena", 5, 60.0 if mode == "puzzle" else 90.0, rng.randrange(1 << 31))
    with open(ckpt) as f:
        cfg.nets[0] = {"dict": json.load(f)}           # loaded per match (not cached): a new checkpoint every few minutes
    if opp["model"]:
        cfg.nets[1] = {"model": os.path.join(ROOT, opp["model"])}
    m = Match(cfg)
    if mode == "puzzle":
        m.puzzle_layout(rng.randrange(1 << 31))
    head = json.dumps(live_meta(m, tag, os.path.basename(ckpt)[:-5], opp, mode)).encode()

    def send(d):
        try:
            sock.sendto(json.dumps(d).encode() if isinstance(d, dict) else d, ("127.0.0.1", STREAM_PORT))
        except OSError:
            pass                                       # nobody listening: nothing waits

    intro = session.KickoffIntro(session.PUZZLE_READY if mode == "puzzle" else 0)
    n, t_next, ended_at, goal_at = 0, time.monotonic(), None, None
    while True:
        n_ev = len(m.events)
        for _ in range(2):                             # 60 ticks/s, 30 frames/s
            if m.state != ENDED and not intro.hold(m):
                m.step()
        if n % FPS == 0:
            send(head)
            if read_text("live_mode.json") + read_text("live_opponent.json") != choices:
                return                                 # the dashboard picked another opponent or mode
        send({**session.frame(m, intro.left, m.events[n_ev:]), "id": m.cfg.match_seed})
        n += 1
        now = time.monotonic()
        if mode == "puzzle" and goal_at is None and sum(m.scores) > 0:
            goal_at = now
        if goal_at is not None and now - goal_at > 2.5:
            return                                     # puzzle solved: a moment of celebration, then the next one
        if m.state == ENDED:
            ended_at = ended_at or now
            if now - ended_at > (4.0 if mode == "match" else 2.0):
                return
        t_next += 1.0 / FPS
        time.sleep(max(0.0, t_next - time.monotonic()))
        if time.monotonic() - t_next > 1.0:            # far behind (the Pi was busy): do not race to catch up
            t_next = time.monotonic()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", required=True, help="run tag: plays the newest out_5v5/ckpt/<tag>_u<N>.json")
    ap.add_argument("--start", default="data/models/rl_5v5_arena_v5.json", help="model played before the first checkpoint")
    ap.add_argument("--matches", type=int, default=0, help="stop after this many matches (0 = never)")
    a = ap.parse_args()
    start = os.path.join(ROOT, a.start.replace("res://", ""))
    rng = random.Random()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    k = 0
    while a.matches <= 0 or k < a.matches:
        play(a.tag, start, rng, sock)
        k += 1


if __name__ == "__main__":
    main()
