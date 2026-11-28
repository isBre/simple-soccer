"""The Lab part of the web app (web/app.py serves it): the experiment pipeline's JSON API. The pages are web/lab/*.js.
Open http://<this machine>:8080/#/ from another computer; the Lab pages poll the API below every 10 s.
  /api/overview       this machine's state, the running experiment (progress, ETA), queue, every run with its latest evaluation, its Elo (lab/ladder.py)
                      and what it changes against its control; the imitation trainings (out_il/); machine health. Runs listed in
                      exp/hidden_runs.json carry "hidden" (the reason): the Runs table leaves them out unless "Show hidden" is ticked
  /api/run/<name>     one run: spec and settings, training curve, PPO health, reward terms, every evaluation, heatmaps
  /api/health         this machine's health log (temperature, thermal pressure, load, memory) of the last hours
  /api/live           server-sent events: the live demo match of this machine's current run (relayed from UDP 127.0.0.1:7310, sent by lab/live.py)
  /results.md         the tracker's table as text
  /api/v1/<command>   the agent interface (lab/lab.py, read-only): status, runs, run/<name>, evals, best, compare?a=&b=, ablation, events?since=,
                      queue, schema; query parameters = the CLI options (e.g. /api/v1/evals?run=minimal&kind=full). See AGENTS.md.
  /api/docs, /api/docs/<id>  the project's Markdown files (AGENTS.md, docs/*.md, exp/results.md, READMEs): the Docs page
  /api/dataset        the user's recorded play (data/human/, game/recorder.py) analysed for the Dataset page (il/analysis.py), plus
                      the nets' and the rule bots' behaviour numbers of the newest full evaluation as references
  /api/dataset/match/<id>  one recorded match, every decision, for the replay
  /api/ranking        the Elo ranking (lab/ladder.py ranking(): every team of every league, rating history, recent matches)
  /api/live/opponents GET the opponents the Live page can play (rule teams, RL Team 4/5, older checkpoints) and the chosen one
  /api/live/mode      POST {"mode": "match"|"puzzle"}: puzzle = random layout of all players and the ball, 60 s, over at the first goal
  /api/live/opponent  POST {"id": ...}: with the mode, the ONLY writes of this server: which opponent the live demo match plays next
                      (logs/live_opponent.json, read by lab/live.py); ids come from the list above, requests from another web site are refused
Standard library only and no internet needed (the charts are drawn in the browser as SVG). It reads exp/ and logs/; the one write is the opponent choice.
Two helpers run beside the server (web/app.py starts them):
  health_sampler()    a health line every 10 s (lab/health_log.py) while no other sampler writes logs/health.log
  follow_live()       the live demo match (lab/live.py) of this machine's current run while no one else (the runner's --viewer) plays it
There is NO login: use it on a trusted network only.

  python3 web/app.py [--port 8080]
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
from http.server import BaseHTTPRequestHandler
from urllib.parse import unquote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys  # noqa: E402
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from lab import lab  # noqa: E402  (lab/lab.py: the agent CLI; /api/v1 serves the same functions)
from lab import tracker  # noqa: E402
from lab import ladder  # noqa: E402
EXP = os.path.join(ROOT, "exp")
LOGS = os.path.join(ROOT, "logs")
STATIC = os.path.join(ROOT, "web")                 # the page shell, styles and scripts (Lab and Game)

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


_elo_cache = {}                                        # size -> (time, rows)


def elo_table(size=5, ttl=60):
    """The ratings of one team size on this machine by entry id (lab/ladder.py rows(): elo/), recomputed at most once a minute.
    A run is rated at the size it trains (a curriculum stage); a run's best net is rated where its weights are (each machine
    rates what it has: the ratings are local, docs/ratings.md)."""
    t, rows = _elo_cache.get(size, (0, {}))
    if time.time() - t > ttl:
        try:
            from lab import ladder
            rows = ladder.rows(size)
        except Exception:                              # no numpy, no database yet: the Runs page simply shows no Elo
            rows = {}
        _elo_cache[size] = (time.time(), rows)
    return rows


def elo_of(name, rows, st=None):
    """The ladder entry of a run: its best checkpoint (net:x_<run>_best), the net it imports (start:<stem>, old_<tag>), its team."""
    if name.startswith("team:"):
        ids = [k for k, r in rows.items() if r["kind"] == "team" and r["name"] == name[5:]]
    elif name.startswith("start:"):
        ids = ["net:" + name[6:]]
    else:
        ids = ["net:" + lab.tag_of(name, st) + "_best", "net:" + name]
    r = next((rows[i] for i in ids if i in rows), None)
    return {k: r.get(k) for k in ("id", "elo", "se", "lo", "hi", "rank", "games", "placed", "w", "d", "l", "gf", "ga", "agf", "aga", "agf_se", "aga_se", "stored")} if r else None


OPERATIONAL = ("ckpt_every", "fast_every", "elo_pairs", "fast_rules", "learn_threads", "envs_per_worker", "trainer_fg")   # how fast it trains, not what it learns


def settings(st, spec):
    """What a run trains with, flattened: {"start": ..., "<reward>": v, "<option>": v} (effective values: defaults included)."""
    rew, args = st.get("effective_rewards"), st.get("effective_args")
    if rew is None or args is None:                    # queued: as it would start now
        rew, args = tracker.effective(spec)
    rew = {**tracker.minimal_for(lab_time(st.get("started"))), **rew}   # older status files lack rewards added later
    args = {**tracker.defaults_for(lab_time(st.get("started"))), **args}
    out = {"start": ("start", spec.get("start"))}
    out.update({k: ("reward", v) for k, v in rew.items()})
    out.update({k: ("option", v) for k, v in args.items() if k not in OPERATIONAL})
    return out


def changes(st, spec):
    """What a run tests: [{k, v, was, kind}] against its control's settings, or against the defaults when it has no control.
    vs = the control's name, or None (then the run is judged against the net it starts from)."""
    mine = settings(st, spec)
    ctrl = spec.get("control")
    cst = tracker.run_status(ctrl) if ctrl else {}
    if ctrl and cst.get("spec"):
        ref = settings(cst, cst["spec"])
        skip = ()
    else:
        ctrl = None
        mn = tracker.minimal_for(lab_time(st.get("started")))
        ref = {**{k: ("reward", v) for k, v in mn.items()}, **{k: ("option", v) for k, v in tracker.defaults_for(lab_time(st.get("started"))).items()}}
        skip = ("start",)                              # the start net is the reference itself
    out = []
    for k, (kind, v) in mine.items():
        if k in skip or k == "updates":                # updates: the Update column
            continue
        was = ref.get(k, (kind, None))[1]
        if v != was and not (v in (0, None) and was in (0, None)):
            out.append({"k": k, "v": v, "was": was, "kind": kind})
    for k, (kind, was) in ref.items():                 # options the control set and this run leaves at the default
        if k not in mine and k not in skip and kind == "option" and k not in tracker.DEFAULTS:
            out.append({"k": k, "v": None, "was": was, "kind": kind})
    return out, ctrl


# the Setup tab: how a run was trained. Every option comes with the meaning the training script itself gives it (rl/selfplay_args.py)
FIXED_REWARDS = [("goals", "+10 for every goal scored, -10 for every goal conceded (the whole team; always on)"),
                 ("time", "-0.0005 per decision (always on)")]
REWARD_MODS = ("pass_individual", "coop_cap", "random_start", "xg_cap", "def_cap", "space_radius", "far_radius", "goalside_lane",
               "compact_len", "compact_wid", "keeper_free")
TRAINING_KEYS = ("start", "updates", "lr", "rollout", "minibatch", "epochs", "gamma", "lam", "ent", "hidden", "workers_rule",
                 "workers_self", "opp_models", "pfsp", "snapshot_every", "teacher", "kl_coef", "kl_decay", "fast_every", "elo_pairs", "seed")


def training_setup(cfg, st, row):
    """{obs, actions, rewards, reward_options, training}: the observation layout, the net's outputs, every reward weight (with the
    minimal set's value) and the main training settings of a run, from its config file (logs/<tag>_config.json) or, before that
    exists, its status."""
    mod = tracker.selfplay_args()
    acts = [a for a in mod.parser()._actions if a.option_strings and a.dest != "help"]
    helps, defaults = {a.dest: (a.help or "").replace("%%", "%") for a in acts}, {a.dest: a.default for a in acts}
    spec = st.get("spec") or {}
    top = {k: spec[k] for k in ("obs", "size") if k in spec}                       # a curriculum stage's spec names them itself
    if "opp" in spec:
        top["opp_mode"] = spec["opp"]
    v = {**defaults, **{k: val for k, (_, val) in settings(st, spec).items()}, **top, **cfg}
    minimal = tracker.minimal_for(lab_time(st.get("started")))
    item = lambda k: {"k": k, "v": v.get(k), "default": defaults.get(k), "help": helps.get(k, "")}
    reward = lambda k: {**item(k), "minimal": minimal.get(k, defaults.get(k))}
    net = [int(x) for x in str(row.get("net") or "").split("-") if x.isdigit()]
    by_inputs = {n: name for name, n in mod.OBS_DIMS.items()}
    obs = cfg.get("obs") or top.get("obs") or (by_inputs.get(net[0]) if net else None) or "team"
    outputs = net[-1] if net else 10
    from soccer.match import INTENTS
    return {"obs": {"name": obs, "inputs": net[0] if net else mod.OBS_DIMS.get(obs), "about": mod.OBS_DESC.get(obs, ""), "size": v.get("size", 5),
                    "opp_mode": v.get("opp_mode", "rules"), "hidden": net[1:-1]},
            "actions": {"outputs": outputs, "moves": 9, "kick": True, "calls": list(INTENTS) if outputs >= 15 else []},
            "rewards": [{"k": k, "v": None, "fixed": True, "help": h} for k, h in FIXED_REWARDS]
                       + [reward(k) for k in sorted(helps) if k.startswith("w_") or k == "shaping"],
            "reward_options": [reward(k) for k in REWARD_MODS if k in helps],
            "training": [item(k) for k in TRAINING_KEYS if k in v]}


def lab_time(started):
    """A status time (epoch seconds, or ISO text in older files) as epoch seconds."""
    return started if isinstance(started, (int, float)) else (time.mktime(time.strptime(started[:19], "%Y-%m-%dT%H:%M:%S")) if started else None)


def imitation_runs(elo):
    """The imitation trainings on the recorded play (il/train.py -> out_il/<name>.metrics.json), as rows of the Runs table."""
    out = []
    for f in sorted(glob.glob(os.path.join(ROOT, "out_il", "*.metrics.json"))):
        m = rj(f, {})
        meta, pooled = m.get("meta") or {}, m.get("pooled") or {}
        name = meta.get("name") or os.path.basename(f)[:-13]
        model = "linear" if meta.get("model") == "linear" else "mlp %s" % meta.get("hidden", "")
        notes = "behaviour cloning on %d recorded matches (%s decisions)" % (len(meta.get("matches") or []), "{:,}".format(meta.get("rows") or 0))
        if pooled.get("move_acc") is not None:
            notes += " · held-out move accuracy %.0f%% (most common move %.0f%%)" % (100 * pooled["move_acc"], 100 * pooled.get("baseline_most_common_move", 0))
        ch = [{"k": "model", "v": model.strip(), "kind": "option"}, {"k": "lag", "v": meta.get("lag"), "kind": "option"}]
        if meta.get("hide_self_vel"):
            ch.append({"k": "hide_self_vel", "v": True, "kind": "option"})
        if meta.get("mirror") is False:
            ch.append({"k": "mirror", "v": False, "kind": "option"})
        out.append({"name": name, "type": "imitation", "state": "done", "notes": notes, "changes": ch, "vs": None, "start": None,
                    "update": meta.get("epochs"), "update_unit": "epochs", "finished": meta.get("trained"), "il": pooled or None,
                    "elo": elo_of(name, elo), "latest_full": None, "verdict": None})
    return out


def overview():
    """Everything the Now and Runs pages need, in one request (polled every 10 s)."""
    status = lab.cmd_status(None)
    runs = lab.cmd_runs(ns(state=None))
    elo = elo_table()
    hidden = (rj(os.path.join(EXP, "hidden_runs.json"), {}) or {}).get("runs", {})   # hidden in the Runs table, never deleted
    for r in runs:
        st = tracker.run_status(r["name"])
        if r["name"] in hidden:
            r["hidden"] = hidden[r["name"]]
        r["type"] = "rl"                               # RL Team 4 / 5 (the reference teams) were trained with RL too
        r["elo"] = elo_of(r["name"], elo if int(r.get("size") or 5) == 5 else elo_table(int(r["size"])), st)
        r["start_elo"] = start_elo(st, r["name"])
        if st.get("spec"):
            r["changes"], r["vs"] = changes(st, st["spec"])
    queue = lab.cmd_queue(ns(action="list"))
    for q in queue["queued"]:
        spec = next((rj(f) for f in lab.queue_files() if os.path.basename(f) == q["file"]), None) or {}
        q["changes"], q["vs"] = changes({}, spec)
    since = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 86400))
    hl = lab.health(3)
    return {"status": status, "runs": runs, "imitation": imitation_runs(elo), "queue": queue, "events": lab.cmd_events(ns(since=since))[-40:][::-1],
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
            "evals": evals, "reference": {"name": ref_name, "evals": ref}, "estimates": ladder.estimates(run=run),
            "start_elo": start_elo(st, run),
            "behaviour_refs": behaviour_refs(run, rows, names, k=10),
            "style_me": style_scalars(sc["scout"]) if sc else {},
            "heat": heatmaps(os.path.join(ROOT, last_full["file"])) if last_full and last_full.get("file") else [],
            "minimal": tracker.MINIMAL, "defaults": tracker.DEFAULTS, "setup": training_setup(rj(os.path.join(LOGS, tag + "_config.json"), {}), st, lab.run_row(run, rows))}


def style_scalars(sc):
    """The numbers of a scouting summary the Behaviour tab compares: its scalar fields, plus per match xG for / against, xG per shot
    and ball recoveries (from the stored shot and recovery lists)."""
    if not sc:
        return {}
    out = {k: v for k, v in sc.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    m = max(sc.get("matches") or 0, 1)
    shots, against = sc.get("shots") or [], sc.get("shots_against") or []
    out["xg_match"] = round(sum(x[2] for x in shots) / m, 3)
    out["xga_match"] = round(sum(x[2] for x in against) / m, 3)
    out["xg_per_shot"] = round(sum(x[2] for x in shots) / len(shots), 3) if shots else None
    out["recoveries_match"] = round(len(sc.get("recoveries") or []) / m, 2)
    return out


def behaviour_refs(run, rows, names, k=6):
    """The strongest teams with measured behaviour, to compare a run's behaviour with: every run / reference team / imported net
    whose ladder entry is placed (RL Team 4 and 5, jit8, the best checkpoint of each run), its newest record with behaviour (a full
    evaluation, else a scouting one), the k highest rated. [{name, elo, update, kind, protocol, behaviour}]"""
    table, out = elo_table(), []
    for n in names:
        if n == run:
            continue
        rec = next((r for r in reversed(rows) if r["run"] == n and r.get("behaviour") and r["kind"] == "full"), None) or \
            next((r for r in reversed(rows) if r["run"] == n and r.get("behaviour")), None)
        e = elo_of(n, table, tracker.run_status(n)) if rec else None
        if e and e.get("placed"):
            sc = next((r for r in reversed(rows) if r["run"] == n and r.get("scout")), None)
            out.append({"name": n, "elo": e["elo"], "update": rec["update"], "kind": rec["kind"], "protocol": rec.get("protocol"), "behaviour": rec["behaviour"],
                        "style": style_scalars(sc["scout"]) if sc else {}})
    out.sort(key=lambda r: -r["elo"])
    return out[:k]


def start_elo(st, run=None):
    """The Elo of the net a run started from: its ladder entry (models/<stem>.json, a run's best checkpoint), else the run's
    estimate at update 0 (the runner estimates the start net before training; "estimate": True). None if neither exists."""
    start = ((st.get("spec") or {}).get("start") or "")
    if not start:
        return None
    stem = os.path.basename(start).rsplit(".", 1)[0]
    r = elo_table().get("net:" + stem)
    if r and r.get("games"):
        return {"name": stem, **{k: r.get(k) for k in ("elo", "se", "lo", "hi", "agf", "aga", "games", "placed")}}
    e0 = next((e for e in ladder.estimates(run=run) if e.get("update") == 0), None) if run else None
    if e0:
        return {"name": stem, "elo": e0["elo"], "se": e0["se"], "lo": e0["lo"], "hi": e0["hi"], "agf": e0.get("gf"), "aga": e0.get("ga"),
                "games": e0["games"], "placed": False, "estimate": True}
    return None


def health_view(hours=12.0):
    hl = lab.health(hours)
    return {"rows": lab.thin(hl, 720), "reboots": lab.reboots(lab.health(72)), "hours": hours}


DOC_FILES = [("Experiments", "AGENTS.md"), ("Experiments", "docs/experiment_log.md"), ("Experiments", "docs/rewards.md"), ("Experiments", "docs/experiment_pipeline.md"),
             ("Experiments", "exp/results.md"), ("Experiments", "lab/README.md"),
             ("Project", "README.md"), ("Project", "rl/README.md"), ("Project", "docs/design.md"), ("Project", "docs/lab_design.md"),
             ("Teams", "docs/opus_5_5_high.md"), ("Teams", "docs/elo_ranking.md"), ("Teams", "docs/ratings.md"), ("Teams", "docs/public_view.md")]


def doc_list():
    """The Markdown files the Docs page shows (a fixed list: nothing else is ever served): [{id, path, title, group, size, updated}]."""
    out = []
    for group, rel in DOC_FILES:
        full = os.path.join(ROOT, rel)
        if not os.path.isfile(full):
            continue
        text = open(full, encoding="utf-8", errors="replace").read(4000)
        m = re.search(r"^#\s+(.+)$", text, re.M)
        out.append({"id": rel.replace("/", "__"), "path": rel, "title": m.group(1).strip() if m else rel, "group": group,
                    "size": os.path.getsize(full), "updated": os.path.getmtime(full)})
    return out


LIVE_SEL = os.path.join(ROOT, "logs", "live_opponent.json")
LIVE_MODE = os.path.join(ROOT, "logs", "live_mode.json")
NET_LABELS = {"rl_5v5_arena_v4": "RL Team 4", "rl_5v5_arena_v5": "RL Team 5"}


def dataset_view():
    """The Dataset page: the analysis of data/human/ and, as references, the behaviour of the newest full evaluation (the net
    and the rule bots it played, same definitions)."""
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from il import analysis
    out = dict(analysis.summary())
    ref = None
    try:
        for line in open(os.path.join(EXP, "results.jsonl")):
            r = json.loads(line)
            if r.get("kind") == "full" and r.get("behaviour"):
                ref = r
    except (OSError, ValueError):
        pass
    out["reference"] = None if ref is None else {"run": ref.get("run"), "update": ref.get("update"), "net": ref.get("behaviour"),
                                                 "rules": ref.get("behaviour_rule")}
    return out


def live_opponents():
    """Everything the demo match can play against: [{id, kind rule|net|random, label, group, team|model, ...}]."""
    out = [{"id": "random", "kind": "random", "label": "Random (all teams and earlier runs)", "group": "Automatic"}]
    try:
        info = json.load(open(os.path.join(ROOT, "rl", "teams_info.json")))
    except (OSError, ValueError):
        info = []
    for t in sorted(info, key=lambda t: t.get("strength", 0)):
        out.append({"id": "rule:" + t["id"], "kind": "rule", "team": t["id"], "label": t["id"].replace("_", " ").title(),
                    "group": "Handmade teams", "tier": t.get("tier"), "strength": t.get("strength"), "plays": t.get("plays")})
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


def live_mode():
    try:
        return "puzzle" if json.load(open(LIVE_MODE)).get("mode") == "puzzle" else "match"
    except (OSError, ValueError):
        return "match"


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
    bound = False                 # this server receives the stream (another one on this machine may hold the port)

    @classmethod
    def listen(cls, port=7310):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            print("live demo: port %d is taken (another web app on this machine shows it)" % port, flush=True)
            return
        cls.bound = True
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


def health_sampler():
    """Health line every 10 s while no other sampler (lab/health_log.py started by lab/run.sh) keeps logs/health.log fresh."""
    from lab import health_log
    try:
        health_log.sample(only_if_quiet=True)
    except Exception as e:                                       # never takes the server down
        print("health sampler stopped: %r" % e, flush=True)


def follow_live(every=10):
    """The live demo match (lab/live.py) of this machine's current run: the running experiment, else the most recently updated one
    (lab/exp_runner.py viewer_target). Only while no other lab/live.py runs (the runner's --viewer owns it while it trains: started
    and paused by it and by lab/thermal_guard.py); this one steps back as soon as another appears. Only the server that receives the
    stream (Live.bound) plays it."""
    import subprocess
    from lab import exp_runner
    own, cur = None, None
    while True:
        time.sleep(every)
        if not Live.bound:
            continue
        if own is not None and own.poll() is not None:          # ours ended (crashed or was stopped): start it again below
            own = cur = None
        try:
            pids = subprocess.run(["pgrep", "-f", "lab/live.py"], capture_output=True, text=True).stdout.split()
        except OSError:
            continue
        others = [p for p in pids if own is None or int(p) != own.pid]
        tag, model = exp_runner.viewer_target()
        if tag and not (os.path.exists(os.path.join(ROOT, model)) or glob.glob(os.path.join(ROOT, "out_5v5", "ckpt", tag + "_u*.json"))):
            tag = None                                           # its nets are not on this machine (an imported run)
        if own is not None and (others or tag != cur):
            own.terminate()
            try:
                own.wait(10)
            except subprocess.TimeoutExpired:
                own.kill()
            own = cur = None
        if own is None and not others and tag:
            own, cur = exp_runner.viewer_window(tag, model), tag
            print("live demo: follows %s (pid %d)" % (tag, own.pid), flush=True)


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
            if path == "/api/docs":
                return self.send(json.dumps({"docs": doc_list()}).encode(), "application/json")
            if path.startswith("/api/docs/"):
                doc = next((d for d in doc_list() if d["id"] == path[len("/api/docs/"):]), None)
                if doc is None:
                    return self.send(json.dumps({"error": "unknown document"}).encode(), "application/json", 404)
                return self.send(open(os.path.join(ROOT, doc["path"]), "rb").read(), "text/markdown; charset=utf-8")
            if path == "/api/docfile":                              # images of the documents: only pictures under docs/ and icon.svg
                from urllib.parse import parse_qsl
                rel = dict(parse_qsl(self.path.split("?", 1)[1] if "?" in self.path else "")).get("path", "")
                full = os.path.realpath(os.path.join(ROOT, rel))
                ctype = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml"}.get(os.path.splitext(full)[1].lower())
                if not ctype or not (full.startswith(os.path.join(ROOT, "docs") + os.sep) or full == os.path.join(ROOT, "icon.svg")) or not os.path.isfile(full):
                    return self.send(b"not found", "text/plain", 404)
                return self.send(open(full, "rb").read(), ctype)
            if path == "/api/ranking":
                from lab import ladder
                from urllib.parse import parse_qsl
                q = dict(parse_qsl(self.path.split("?", 1)[1])) if "?" in self.path else {}
                size = int(q.get("size", 5)) if str(q.get("size", 5)).isdigit() and 1 <= int(q.get("size", 5)) <= 5 else 5
                return self.send(json.dumps(ladder.ranking(size), default=float).encode(), "application/json")
            if path == "/api/dataset":
                return self.send(json.dumps(dataset_view(), default=float).encode(), "application/json")
            if path.startswith("/api/dataset/match/"):
                from il import analysis
                try:
                    return self.send(json.dumps(analysis.match_frames(path[len("/api/dataset/match/"):])).encode(), "application/json")
                except KeyError:
                    return self.send(json.dumps({"error": "unknown match"}).encode(), "application/json", 404)
            if path == "/api/live/opponents":
                return self.send(json.dumps({"opponents": live_opponents(), "selected": live_selected(), "mode": live_mode()}).encode(), "application/json")
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
        if path == "/api/live/mode":
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 4096)) or b"{}")
            except ValueError:
                body = {}
            mode = "puzzle" if body.get("mode") == "puzzle" else "match"
            if origin and origin.split("://")[-1] != host:
                return self.send(json.dumps({"error": "not allowed"}).encode(), "application/json", 403)
            json.dump({"mode": mode}, open(LIVE_MODE + ".tmp", "w"))
            os.replace(LIVE_MODE + ".tmp", LIVE_MODE)
            return self.send(json.dumps({"mode": mode}).encode(), "application/json")
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
        """/api/v1/<command>[/<positional>...]?option=value -> lab/lab.py <command> ... (read-only commands only)."""
        from urllib.parse import parse_qsl
        parts = [p for p in path[len("/api/v1"):].split("/") if p]
        if not parts:
            body = {"commands": ["status", "runs", "run/<name>", "evals", "best", "compare?a=&b=", "ablation", "events?since=", "queue", "schema", "ranking?league="],
                    "docs": "AGENTS.md, exp/schema.json", "cli": "python3 lab/lab.py -h"}
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
            body, code = {"error": "bad parameters", "hint": "same options as: python3 lab/lab.py %s -h" % cmd}, 400
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
