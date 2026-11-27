"""What the game, the Lab and the command line ask of the ratings: the ratings of a size (cached until a result is added or a
file changes), ranking tables, the playing of a round, the setup (`init`) and the background refining (`refine`)."""
import os
import random
import threading
import time

from . import DURATION, ENGINE, LOCAL, PLACEMENT, PROTOCOL, SIZES, db, model, play, roster, schedule

_lock = threading.Lock()
_cache = {}                                         # (db path, size) -> (db version, roster, Ratings)


class Ratings:
    """The fit of one size: `rat` {entry id: rating dict}, `goals` {id: adjusted goals}, `gm` (the goals model), `groups` (the
    valid pairings) and `ros` (the roster it was fitted against)."""

    def __init__(self, ros, size, groups):
        self.ros, self.size, self.groups = ros, size, groups
        self.rat = model.fit(ros, size, groups)
        self.gm = model.goal_model(ros, size, groups)
        self.goals = model.goal_table(self.gm)
        self.matches = sum(g["n"] for g in groups)


def connection(path=None):
    return db.connect(path)


def ratings(size, conn=None, ros=None):
    """The Ratings of a size, recomputed only when a result was added or a file changed."""
    own = conn is None
    conn = conn or db.connect()
    try:
        ros = ros or roster.get()
        key = (conn.execute("PRAGMA database_list").fetchone()[2], size)
        ver = db.version(conn)
        with _lock:
            hit = _cache.get(key)
            if hit and hit[0] == ver and hit[1] is ros:
                return hit[2]
        r = Ratings(ros, size, model.valid_groups(ros, size, db.pairings(conn, size)))
        with _lock:
            _cache[key] = (ver, ros, r)
        return r
    finally:
        if own:
            conn.close()


def row(e, r, g):
    """One table row of an entry: identity, rating with its interval, record, opponent-adjusted goals."""
    gl = g or {}
    return {"id": e.id, "name": e.name, "entry": e.kind, "kind": e.sub if e.unit else "team", "sub": e.sub, "league": e.league,
            "model": e.model, "sizes": e.sizes(), "placed": r["placed"], "games": r["games"], "w": r["w"], "d": r["d"], "l": r["l"],
            "elo": r["elo"], "se": r["se"], "lo": r["lo"], "hi": r["hi"], "bonus": r["bonus"],
            "gf": r["gf"] / r["games"] if r["games"] else None, "ga": r["ga"] / r["games"] if r["games"] else None,
            "agf": gl.get("gf"), "aga": gl.get("ga"), "agf_se": gl.get("gf_se"), "aga_se": gl.get("ga_se")}


def table(size, conn=None):
    """Every rated entry of a size as rows sorted by Elo, with rank. A team that is one player five times is a row of its own
    (kind "team", `via` = the player's entry) with the player's numbers."""
    r = ratings(size, conn)
    ros = r.ros
    rows = [row(e, r.rat[i], r.goals.get(i)) for i, e in ros.at(size).items()]
    from soccer.data import database
    teams = database().teams
    for tid, eid in ros.alias.items():
        e = ros.entries[eid]
        if eid in r.rat and tid in teams:
            x = row(e, r.rat[eid], r.goals.get(eid))
            x.update({"id": "team:" + tid, "name": teams[tid].name, "entry": "team", "kind": "team", "league": teams[tid].league,
                      "via": eid, "sizes": [n for n in SIZES if teams[tid].can_play(n)]})
            rows.append(x)
    rows.sort(key=lambda x: (-x["elo"], x["id"]))
    for k, x in enumerate(rows):
        x["rank"] = k + 1
    return rows


def ranking(size=5, conn=None):
    """The table of the Ranking pages and of `lab.py ranking`: rows plus the history, the matches counted and the latest ones."""
    own = conn is None
    conn = conn or db.connect()
    try:
        r = ratings(size, conn)
        rows = table(size, conn)
        cnt = db.counts(conn).get(size, (0, 0))
        names = {x["id"]: x["name"] for x in rows}
        return {"protocol": PROTOCOL, "size": size, "matches": r.matches, "stale": cnt[0] + cnt[1] - r.matches, "entries": len(rows),
                "rows": rows, "history": db.history(conn, size), "off": os.path.exists(refine_off_path()), "last": db.last_time(conn, size),
                "recent": [{"t": m["t"], "a": m["a"], "b": m["b"], "ga": m["ga"], "gb": m["gb"]} for m in db.recent(conn, size)],
                "names": names}
    finally:
        if own:
            conn.close()


def elo_by_team(conn=None):
    """{team id: {size: {elo, se, games, placed}}} for the game: every team (aliases included) and every player id as "player:<id>"."""
    out = {}
    for size in SIZES:
        for x in table(size, conn):
            out.setdefault(x["id"], {})[size] = {"elo": x["elo"], "se": x["se"], "games": x["games"], "placed": x["placed"], "rank": x["rank"]}
    return out


def refine_off_path():
    return os.path.join(LOCAL, "refine_off")


# ---------------------------------------------------------------- playing


def _summary(conn, ros):
    out = {}
    for s in SIZES:
        r = ratings(s, conn, ros)
        ids = list(ros.at(s))
        out[s] = (len(ids), sum(1 for i in ids if r.rat[i]["games"] < PLACEMENT), sum(r.rat[i]["games"] for i in ids))
    return out


def play_round(pairs=8, workers=3, size=None, seed=None, conn=None, min_games=0):
    """One round: placement and the most informative pairs of one size (chosen if not given), two matches each. min_games: an entry
    below it counts as unplaced when the size is chosen. Returns {size, matches, seconds, pairs}."""
    own = conn is None
    conn = conn or db.connect()
    try:
        t0 = time.time()
        rng = random.Random(seed)
        ros = roster.get()
        if size is None:
            summ = _summary(conn, ros)
            if min_games:
                summ = {s: (n, sum(1 for i in ros.at(s) if ratings(s, conn, ros).rat[i]["games"] < min_games), g) for s, (n, _, g) in summ.items()}
            size = schedule.pick_size(SIZES, summ)
            if size is None:
                return {"size": None, "matches": 0, "seconds": 0.0, "pairs": []}
        r = ratings(size, conn, ros)
        ids = list(ros.at(size))
        rat = r.rat
        if min_games:
            rat = {i: {**v, "games": min(v["games"], PLACEMENT - 1) if v["games"] < min_games else v["games"]} for i, v in rat.items()}
        ps = schedule.choose_pairs(ids, rat, schedule.pair_games(r.groups), pairs, rng)
        jobs = [(ros.entries[a].spec(), ros.entries[b].spec(), size, rng.randrange(1, 1 << 31)) for a, b in ps]
        recs = play.play(jobs, workers)
        db.add_results(conn, recs)
        snap = ratings(size, conn, ros)
        db.add_history(conn, size, snap.matches, {i: round(v["elo"], 1) for i, v in snap.rat.items() if v["games"]})
        return {"size": size, "matches": len(recs), "seconds": round(time.time() - t0, 1), "pairs": ps}
    finally:
        if own:
            conn.close()


def init(games=30, pairs=8, workers=3, minutes=None, log=print, conn=None):
    """The setup: rounds until every entry has `games` games at every size it can play (or the time is up). `quick` is 30 games
    per entry, `full` 100."""
    own = conn is None
    conn = conn or db.connect()
    t0 = time.time()
    try:
        while True:
            ros = roster.get()
            low = {s: [i for i in ros.at(s) if ratings(s, conn, ros).rat[i]["games"] < games] for s in SIZES if len(ros.at(s)) >= 2}
            todo = {s: v for s, v in low.items() if v}
            if not todo or (minutes and time.time() - t0 > minutes * 60):
                break
            r = play_round(pairs, workers, conn=conn, min_games=games)
            if r["size"] is None:
                break
            log("%dv%d: %d matches in %.0f s   (still below %d games: %s)" % (r["size"], r["size"], r["matches"], r["seconds"], games,
                                                                          ", ".join("%dv%d %d" % (s, s, len(v)) for s, v in sorted(todo.items()))))
        return {"seconds": round(time.time() - t0), "done": not todo}
    finally:
        if own:
            conn.close()


def refine(pairs=4, workers=2, max_load=None, log=None):
    """Background refining, forever: a small round whenever the machine is idle (the load average is low: no training run, no
    other heavy work), nothing while `local/refine_off` exists. A match someone is playing in the game is one process: it does
    not stop this, the workers are niced."""
    import fcntl
    os.makedirs(LOCAL, exist_ok=True)
    lock = open(os.path.join(LOCAL, "refine.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)        # one refiner per machine (two web servers, a terminal)
    except OSError:
        if log:
            log("refine: another process is already refining the ratings here")
        return
    cores = os.cpu_count() or 2
    max_load = max_load if max_load is not None else max(1.0, cores * 0.4)
    conn = db.connect()
    while True:
        try:
            if os.path.exists(refine_off_path()) or os.getloadavg()[0] > max_load:
                time.sleep(60)
                continue
            r = play_round(pairs, workers, conn=conn)
            if log:
                log("refine %dv%d: %d matches in %.0f s" % (r["size"] or 0, r["size"] or 0, r["matches"], r["seconds"]))
            time.sleep(5 if r["size"] else 600)
        except Exception as e:                       # a bad round must not end the refining
            if log:
                log("refine: %r" % (e,))
            time.sleep(120)


def archive(label="", dry_run=False):
    """Starts the ratings over (only when the user decides): moves local/elo.db to local/elo_archive/<date>[_label].db."""
    src = db.default_path()
    if not os.path.exists(src):
        return {"files": 0}
    name = time.strftime("%Y-%m-%d") + ("_" + "".join(c if c.isalnum() or c in "-_" else "_" for c in label) if label else "")
    conn = db.connect(src)
    counts = db.counts(conn)
    conn.close()
    dest = os.path.join(LOCAL, "elo_archive", name + ".db")
    k = 2
    while os.path.exists(dest):
        dest = os.path.join(LOCAL, "elo_archive", "%s_%d.db" % (name, k))
        k += 1
    info = {"files": 1, "from": src, "to": dest, "matches": sum(c[0] + c[1] for c in counts.values()), "label": label}
    if not dry_run:
        import shutil
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        c = db.connect(src)
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        c.close()
        shutil.move(src, dest)
        for ext in ("-wal", "-shm"):
            if os.path.exists(src + ext):
                os.remove(src + ext)
        with _lock:
            _cache.clear()
    return info
