"""Web dashboard of the experiment pipeline, for the local network: open http://<pi-address>:8080 from another computer.

The page (tools/dashboard/: index.html, app.js, style.css) is a small single-page app that polls the JSON API below every 10 s.
  /api/overview       Pi state, the running experiment (progress, ETA), queue, every run with its latest evaluation, Pi health
  /api/run/<name>     one run: spec and settings, training curve, PPO health, reward terms, every evaluation, heatmaps
  /api/health         Pi health log (throttling, temperature, load, memory) of the last hours
  /api/live           server-sent events: the match the Pi's viewer is showing (relayed from UDP 127.0.0.1:7310, see tools/watch_training.gd)
  /results.md         the tracker's table as text
  /api/v1/<command>   the agent interface (rl/lab.py, read-only): status, runs, run/<name>, evals, best, compare?a=&b=, ablation, events?since=,
                      queue, schema; query parameters = the CLI options (e.g. /api/v1/evals?run=minimal&kind=full). See AGENTS.md.
  /api/live/opponents GET the opponents the Live page can play (rule teams, RL Team 4/5, older checkpoints) and the chosen one
  /api/live/opponent  POST {"id": ...}: the ONLY write of this server: which opponent the Pi's demo match plays next (logs/live_opponent.json,
                      logs/live_opp_net.json); ids come from the list above, requests from another web site are refused
Standard library only and no internet needed (the charts are drawn in the browser as SVG). It reads exp/ and logs/; the one write is the opponent choice.
There is NO login: use it on a trusted network only.

  python3 tools/dashboard.py [--port 8080]                 (service soccer-dashboard, tools/systemd/)
"""
import argparse
import glob
import json
import mimetypes
import os
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "rl"))
import lab  # noqa: E402  (rl/lab.py: the agent CLI; /api/v1 serves the same functions)
import tracker  # noqa: E402
EXP = os.path.join(ROOT, "exp")
LOGS = os.path.join(ROOT, "logs")
STATIC = os.path.join(ROOT, "tools", "dashboard")

def rj(path, default=None):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default


def ns(**kw):
    import argparse
    return argparse.Namespace(**kw)


def heatmaps(path):
    out = []
    if path and os.path.exists(path):
        for line in open(path, errors="replace"):
            p = line.split()
            if len(p) > 5 and p[0] == "HEAT":
                out.append({"slot": p[1], "role": p[2], "w": int(p[3]), "h": int(p[4]), "v": [int(x) for x in p[5:]]})
    return out


def overview():
    """Everything the Now page needs, in one request (polled every 10 s)."""
    status = lab.cmd_status(None)
    runs = lab.cmd_runs(ns(state=None))
    for r in runs:
        tr = lab.training(lab.tag_of(r["name"]))
        r["spark"] = [[x["upd"], x["rules"]] for x in lab.thin(tr, 60) if x["rules"] is not None]
    since = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 86400))
    hl = lab.health(3)
    return {"status": status, "runs": runs, "queue": lab.cmd_queue(ns(action="list")), "events": lab.cmd_events(ns(since=since))[-40:][::-1],
            "health": lab.thin(hl, 120), "now": int(time.time())}


def run_detail(run):
    rows, names = lab.all_runs()
    if run not in names:
        raise lab.LabError("unknown run %r" % run)
    st = tracker.run_status(run)
    tag = lab.tag_of(run, st)
    evals = []
    for r in rows:
        if r["run"] == run:
            e = lab.eval_row(r)
            e.update({"league_all": r["league"], "greedy_all": r.get("greedy", {}), "h2h_full": r.get("h2h", {})})
            evals.append(e)
    last_full = next((r for r in reversed(rows) if r["run"] == run and r["kind"] == "full"), None)
    ref_name = (st.get("verdict") or {}).get("reference") or st.get("baseline_run")
    ref = [lab.eval_row(r) for r in rows if ref_name and r["run"] == ref_name]
    sc = next((r for r in reversed(rows) if r["run"] == run and r.get("scout")), None)
    ref_sc = next((r for r in reversed(rows) if r["run"] == "team:RL Team 4" and r.get("scout")), None)
    return {"run": run, "tag": tag, "row": lab.run_row(run, rows), "status": st,
            "scout": {**sc["scout"], "update": sc["update"], "kind": sc["kind"]} if sc else None,
            "scout_ref": {"name": "RL Team 4", **ref_sc["scout"]} if ref_sc and run != "team:RL Team 4" else None, "config": rj(os.path.join(LOGS, tag + "_config.json"), {}),
            "training": lab.thin(lab.training(tag), 500), "ppo": lab.thin(lab.latest_segment(lab.jl(os.path.join(LOGS, tag + "_ppo.jsonl"))), 400),
            "terms": lab.thin(lab.latest_segment([{"upd": t["upd"], **t["terms"]} for t in lab.jl(os.path.join(LOGS, tag + "_terms.jsonl"))]), 300),
            "evals": evals, "reference": {"name": ref_name, "evals": ref},
            "heat": heatmaps(os.path.join(ROOT, last_full["file"])) if last_full and last_full.get("file") else [],
            "minimal": tracker.MINIMAL, "defaults": tracker.DEFAULTS}


def health_view(hours=12.0):
    hl = lab.health(hours)
    return {"rows": lab.thin(hl, 720), "reboots": lab.reboots(lab.health(72)), "hours": hours}


LIVE_SEL = os.path.join(ROOT, "logs", "live_opponent.json")
LIVE_NET = os.path.join(ROOT, "logs", "live_opp_net.json")
NET_LABELS = {"rl_5v5_arena_v4": "RL Team 4", "rl_5v5_arena_v5": "RL Team 5"}


def live_opponents():
    """Everything the demo match can play against: [{id, kind rule|net|random, label, group, team|model, ...}]."""
    out = [{"id": "random", "kind": "random", "label": "Random (all teams and earlier runs)", "group": "Automatic"}]
    try:
        info = json.load(open(os.path.join(ROOT, "rl", "teams_info.json")))
    except (OSError, ValueError):
        info = []
    for t in sorted(info, key=lambda t: t.get("strength", 0)):
        out.append({"id": "rule:" + t["id"], "kind": "rule", "team": t["id"], "label": t["id"].replace("_", " ").title(),
                    "group": "Handmade teams", "tier": t.get("tier"), "strength": t.get("strength"), "style": t.get("style")})
    for name, label in NET_LABELS.items():
        out.append({"id": "net:" + name, "kind": "net", "model": "data/models/%s.json" % name, "label": label, "group": "Earlier RL teams"})
    nets = [("out_5v5/ckpt/t48_u100.json", "Start net t48_u100"), ("out_5v5/ckpt/jit8_best.json", "jit8 (54-number, 2.94)")]
    for f in sorted(glob.glob(os.path.join(ROOT, "out_5v5", "ckpt", "x_*_best.json"))):
        run = os.path.basename(f)[2:-len("_best.json")]
        nets.append(("out_5v5/ckpt/" + os.path.basename(f), "Run %s (best)" % run))
    for rel, label in nets:
        if os.path.isfile(os.path.join(ROOT, rel)):
            out.append({"id": "net:" + rel, "kind": "net", "model": rel, "label": label, "group": "Previous runs"})
    return out


def live_selected():
    try:
        return json.load(open(LIVE_SEL)).get("id", "random")
    except (OSError, ValueError):
        return "random"


def live_select(opp_id):
    opp = next((o for o in live_opponents() if o["id"] == opp_id), None)
    if opp is None:
        return None
    sel = {"id": opp["id"], "kind": opp["kind"], "label": opp["label"], "team": opp.get("team", ""), "model": opp.get("model", "")}
    if opp["kind"] == "net":                                  # (random: the viewer draws a new one and writes logs/live_opp_net.json itself)
        json.dump({"model": opp["model"]}, open(LIVE_NET + ".tmp", "w"))
        os.replace(LIVE_NET + ".tmp", LIVE_NET)              # the net server reads it when the next match connects
    json.dump(sel, open(LIVE_SEL + ".tmp", "w"))
    os.replace(LIVE_SEL + ".tmp", LIVE_SEL)
    return sel


class Live:
    """Latest match state from the viewer (UDP JSON packets): 'meta' (pitch, kits, players) and 'frame' (positions)."""
    cond = threading.Condition()
    meta = None
    frame = None
    seq = 0
    meta_seq = 0
    received = 0.0

    @classmethod
    def listen(cls, port=7310):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", port))
        while True:
            data = sock.recv(65535)
            try:
                kind = json.loads(data).get("k")
            except ValueError:
                continue
            with cls.cond:
                if kind == "m":
                    cls.meta = data
                    cls.meta_seq += 1
                else:
                    cls.frame = data
                    cls.seq += 1
                cls.received = time.time()
                cls.cond.notify_all()


class Handler(BaseHTTPRequestHandler):
    def send(self, body, ctype, code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = unquote(self.path.split("?")[0])
        try:
            if path == "/api/overview":
                return self.send(json.dumps(overview(), default=str).encode(), "application/json")
            if path.startswith("/api/run/"):
                try:
                    return self.send(json.dumps(run_detail(path[len("/api/run/"):]), default=str).encode(), "application/json")
                except lab.LabError as e:
                    return self.send(json.dumps({"error": e.error}).encode(), "application/json", 404)
            if path.startswith("/api/v1/") or path == "/api/v1":
                return self.api_v1(path, self.path.split("?", 1)[1] if "?" in self.path else "")
            if path == "/api/live":
                return self.live()
            if path == "/api/live/opponents":
                return self.send(json.dumps({"opponents": live_opponents(), "selected": live_selected()}).encode(), "application/json")
            if path == "/api/health":
                from urllib.parse import parse_qsl
                q = dict(parse_qsl(self.path.split("?", 1)[1])) if "?" in self.path else {}
                return self.send(json.dumps(health_view(float(q.get("hours", 12)))).encode(), "application/json")
            if path == "/results.md":
                return self.send(open(os.path.join(EXP, "results.md"), "rb").read(), "text/plain; charset=utf-8")
            name = "index.html" if path in ("/", "") else path.lstrip("/")
            full = os.path.realpath(os.path.join(STATIC, name))
            if not full.startswith(os.path.realpath(STATIC) + os.sep) or not os.path.isfile(full):
                return self.send(b"not found", "text/plain", 404)
            return self.send(open(full, "rb").read(), (mimetypes.guess_type(full)[0] or "application/octet-stream") + "; charset=utf-8")
        except Exception as e:                                 # a half-written log must not kill the server
            return self.send(json.dumps({"error": repr(e)}).encode(), "application/json", 500)

    def do_POST(self):
        """The only write: choose the live opponent. Same-origin only (a page on another site cannot trigger it)."""
        path = unquote(self.path.split("?")[0])
        host, origin = self.headers.get("Host", ""), self.headers.get("Origin", "")
        if path != "/api/live/opponent" or (origin and origin.split("://")[-1] != host):
            return self.send(json.dumps({"error": "not allowed"}).encode(), "application/json", 403)
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 4096)) or b"{}")
            sel = live_select(str(body.get("id", "")))
        except (ValueError, OSError):
            sel = None
        if sel is None:
            return self.send(json.dumps({"error": "unknown opponent"}).encode(), "application/json", 400)
        return self.send(json.dumps({"selected": sel["id"], "label": sel["label"]}).encode(), "application/json")

    def api_v1(self, path, qs):
        """/api/v1/<command>[/<positional>...]?option=value -> rl/lab.py <command> ... (read-only commands only)."""
        from urllib.parse import parse_qsl
        parts = [p for p in path[len("/api/v1"):].split("/") if p]
        if not parts:
            body = {"commands": ["status", "runs", "run/<name>", "evals", "best", "compare?a=&b=", "ablation", "events?since=", "queue", "schema"],
                    "docs": "AGENTS.md, exp/schema.json", "cli": "python3 rl/lab.py -h"}
            return self.send(json.dumps(lab.envelope(body)).encode(), "application/json")
        cmd, pos = parts[0], parts[1:]
        q = dict(parse_qsl(qs))
        if cmd not in lab.COMMANDS or cmd == "queue" and q.get("action", "list") != "list":
            return self.send(json.dumps({"error": "unknown or not allowed: %s" % cmd, "hint": "GET /api/v1 lists the commands (read-only)"}).encode(), "application/json", 404)
        argv = [cmd] + ([q.pop("a", ""), q.pop("b", "")] if cmd == "compare" else ["list"] if cmd == "queue" else pos)
        q.pop("action", None)
        for k, v in q.items():
            argv += ["--" + k, v]
        try:
            a = lab.parser().parse_args(argv)
            body, code = lab.envelope(lab.COMMANDS[cmd](a)), 200
        except SystemExit:
            body, code = {"error": "bad parameters", "hint": "same options as: python3 rl/lab.py %s -h" % cmd}, 400
        except lab.LabError as e:
            body, code = {"error": e.error, "hint": e.hint}, 404
        return self.send(json.dumps(body, default=str).encode(), "application/json", code)

    def live(self):
        """Server-sent events: the latest meta (when it changes) and every frame, at most 30 per second."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        seen, seen_meta, last_beat = -1, -1, time.time()
        try:
            while True:
                with Live.cond:
                    Live.cond.wait_for(lambda: Live.seq != seen or Live.meta_seq != seen_meta, timeout=2.0)
                    meta, frame, mseq, fseq, rec = Live.meta, Live.frame, Live.meta_seq, Live.seq, Live.received
                out = b""
                if meta is not None and mseq != seen_meta:
                    out += b"event: meta\ndata: " + meta + b"\n\n"
                    seen_meta = mseq
                if frame is not None and fseq != seen:
                    out += b"data: " + frame + b"\n\n"
                    seen = fseq
                if not out and time.time() - last_beat > 2.0:
                    out = b"event: idle\ndata: %d\n\n" % int(time.time() - rec if rec else -1)       # also tells the page how old the last frame is
                if out:
                    self.wfile.write(out)
                    self.wfile.flush()
                    last_beat = time.time()
                time.sleep(1 / 30)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    a = ap.parse_args()
    threading.Thread(target=Live.listen, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", a.port), Handler)
    server.daemon_threads = True
    server.serve_forever()
