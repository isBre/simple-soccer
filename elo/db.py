"""The local database (SQLite, WAL mode: the web server, the training runner and the background rounds can write at once).

  results   one row per match: size, the two entries (ids and file versions), the side the first one played, goals, seed, engine
  history   a snapshot of the ratings of one size after a round (the Ranking page's chart), thinned as it ages
  meta      small facts (the machine's name, when the database was created)

Matches are never deleted: a result stops counting when a file it depends on changes (its sha no longer matches) or when ENGINE
moves on, and `archive` moves a whole database aside."""
import json
import os
import socket
import sqlite3
import time

from . import ENGINE, LOCAL

SCHEMA = """
CREATE TABLE IF NOT EXISTS results (
  id INTEGER PRIMARY KEY AUTOINCREMENT, t TEXT NOT NULL, size INTEGER NOT NULL, a TEXT NOT NULL, b TEXT NOT NULL,
  a_sha TEXT NOT NULL, b_sha TEXT NOT NULL, a_side INTEGER NOT NULL, ga INTEGER NOT NULL, gb INTEGER NOT NULL,
  seed INTEGER NOT NULL, engine INTEGER NOT NULL, machine TEXT, stalled INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS results_pair ON results(size, engine, a, b);
CREATE TABLE IF NOT EXISTS history (
  id INTEGER PRIMARY KEY AUTOINCREMENT, t TEXT NOT NULL, size INTEGER NOT NULL, matches INTEGER NOT NULL, elo TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS history_t ON history(size, t);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""
HISTORY_DENSE_H = 6               # hours of history kept after every round; older: the last snapshot of each hour
HISTORY_MAX = 600                 # snapshots per size before thinning


def default_path():
    return os.path.join(LOCAL, "elo.db")


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def machine():
    return socket.gethostname().split(".")[0]


def connect(path=None):
    path = path or default_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")
    conn.executescript(SCHEMA)
    conn.execute("INSERT OR IGNORE INTO meta VALUES ('created', ?)", (now(),))
    conn.execute("INSERT OR IGNORE INTO meta VALUES ('machine', ?)", (machine(),))
    conn.commit()
    return conn


def add_results(conn, rows):
    """rows: dicts with size, a, b, a_sha, b_sha, a_side, ga, gb, seed (and optionally stalled, t)."""
    conn.executemany(
        "INSERT INTO results (t, size, a, b, a_sha, b_sha, a_side, ga, gb, seed, engine, machine, stalled) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(r.get("t") or now(), r["size"], r["a"], r["b"], r["a_sha"], r["b_sha"], r["a_side"], r["ga"], r["gb"], r["seed"],
          r.get("engine", ENGINE), r.get("machine") or machine(), 1 if r.get("stalled") else 0) for r in rows])
    conn.commit()


def version(conn):
    """A number that changes whenever a result is added (the cache key of the ratings)."""
    return conn.execute("SELECT COALESCE(MAX(id), 0) FROM results").fetchone()[0]


def pairings(conn, size):
    """The results of one size of the current engine, summed per pairing (and per file version of the two entries): the model
    fits these, so a refit costs the same with a thousand games as with a million. [{a, b, a_sha, b_sha, n, score, w, d, ga, gb}]  (w / d: wins and draws of a)"""
    cur = conn.execute(
        "SELECT a, b, a_sha, b_sha, COUNT(*) AS n, SUM(CASE WHEN ga > gb THEN 1.0 WHEN ga = gb THEN 0.5 ELSE 0.0 END) AS score, "
        "SUM(ga > gb) AS w, SUM(ga = gb) AS d, SUM(ga) AS ga, SUM(gb) AS gb "
        "FROM results WHERE size = ? AND engine = ? GROUP BY a, b, a_sha, b_sha", (size, ENGINE))
    return [dict(r) for r in cur]


def counts(conn):
    """{size: (matches of this engine, matches of other engines)}"""
    out = {}
    for r in conn.execute("SELECT size, SUM(engine = ?) AS cur, SUM(engine != ?) AS old FROM results GROUP BY size", (ENGINE, ENGINE)):
        out[r["size"]] = (int(r["cur"] or 0), int(r["old"] or 0))
    return out


def recent(conn, size, n=30):
    return [dict(r) for r in conn.execute(
        "SELECT t, a, b, a_sha, b_sha, ga, gb FROM results WHERE size = ? AND engine = ? ORDER BY id DESC LIMIT ?", (size, ENGINE, n))][::-1]


def last_time(conn, size=None):
    q, args = "SELECT MAX(t) FROM results WHERE engine = ?", [ENGINE]
    if size:
        q, args = q + " AND size = ?", args + [size]
    return conn.execute(q, args).fetchone()[0]


def add_history(conn, size, matches, elo):
    conn.execute("INSERT INTO history (t, size, matches, elo) VALUES (?,?,?,?)", (now(), size, matches, json.dumps(elo)))
    n = conn.execute("SELECT COUNT(*) FROM history WHERE size = ?", (size,)).fetchone()[0]
    if n > HISTORY_MAX:
        thin_history(conn, size)
    conn.commit()


def thin_history(conn, size, at=None):
    """Keeps every snapshot of the last HISTORY_DENSE_H hours and, before that, the last one of each hour (nothing is lost:
    the ratings are refitted from all matches every time)."""
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime((at or time.time()) - HISTORY_DENSE_H * 3600))
    rows = conn.execute("SELECT id, t FROM history WHERE size = ? ORDER BY id", (size,)).fetchall()
    keep, last_of_hour = set(), {}
    for r in rows:
        if r["t"] >= cutoff:
            keep.add(r["id"])
        else:
            last_of_hour[r["t"][:13]] = r["id"]
    keep |= set(last_of_hour.values())
    conn.executemany("DELETE FROM history WHERE id = ?", [(r["id"],) for r in rows if r["id"] not in keep])


def history(conn, size, n=400):
    return [{"t": r["t"], "matches": r["matches"], "elo": json.loads(r["elo"])} for r in conn.execute(
        "SELECT t, matches, elo FROM history WHERE size = ? ORDER BY id DESC LIMIT ?", (size, n))][::-1]
