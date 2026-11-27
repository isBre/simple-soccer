"""python3 -m elo <command>

  init [--quick | --full | --games N] [--minutes M]   the setup: play until every entry has enough games at every size
                                                       (quick: 30 games, ~10 min on a MacBook Air; full: 100 games, ~35 min; a Pi ~3x)
  round [--pairs 8] [--workers 3] [--size N] [--rounds R]   rounds of the most informative matches
  rank [--size 5] [--kind player|team|net]            the ranking of one size
  status                                               matches and entries per size, what is still unplaced
  roster                                               who is rated, their sizes and file versions
  refine                                               background refining (forever; local/refine_off pauses it)
  archive [--label L] [--yes]                          ONLY when the user asks: starts the ratings over (the database is moved aside)
"""
import argparse
import sys
import time

from . import SIZES, PLACEMENT, api, db, roster


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m elo", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init")
    p.add_argument("--quick", action="store_true", help="30 games per entry and size (the default; about 10 minutes on a MacBook Air)")
    p.add_argument("--full", action="store_true", help="100 games per entry and size (about 35 minutes)")
    p.add_argument("--games", type=int, default=0)
    p.add_argument("--minutes", type=float, default=None)
    p.add_argument("--pairs", type=int, default=8)
    p.add_argument("--workers", type=int, default=3)
    p = sub.add_parser("round")
    p.add_argument("--pairs", type=int, default=8)
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--size", type=int, default=None)
    p.add_argument("--rounds", type=int, default=1)
    p.add_argument("--seed", type=int, default=None)
    p = sub.add_parser("rank")
    p.add_argument("--size", type=int, default=5)
    p.add_argument("--kind", default="")
    p.add_argument("--top", type=int, default=0)
    sub.add_parser("status")
    sub.add_parser("roster")
    sub.add_parser("refine")
    p = sub.add_parser("archive")
    p.add_argument("--label", default="")
    p.add_argument("--yes", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "init":
        games = a.games or (100 if a.full else 30)
        r = api.init(games, a.pairs, a.workers, a.minutes, log=lambda s: print(s, flush=True))
        print("%s after %d s: %s" % ("done" if r["done"] else "stopped", r["seconds"], "every entry has %d games" % games if r["done"] else "run it again to go on"))
    elif a.cmd == "round":
        for k in range(a.rounds):
            r = api.play_round(a.pairs, a.workers, a.size, None if a.seed is None else a.seed + k)
            print("round %d: %s, %d matches in %.0f s" % (k + 1, "%dv%d" % (r["size"], r["size"]) if r["size"] else "nothing to play", r["matches"], r["seconds"]), flush=True)
    elif a.cmd == "rank":
        rows = [x for x in api.table(a.size) if not a.kind or x["entry"] == a.kind or x["kind"] == a.kind]
        for x in rows[:a.top or None]:
            print("%3d %-34s %-7s %6.0f ± %3.0f  %4d games   agf %s aga %s%s" % (
                x["rank"], x["name"], x["entry"], x["elo"], 1.96 * x["se"], x["games"],
                "%.2f" % x["agf"] if x["agf"] is not None else "-", "%.2f" % x["aga"] if x["aga"] is not None else "-", "" if x["placed"] else "  (provisional)"))
    elif a.cmd == "status":
        conn = db.connect()
        ros = roster.get()
        cnt = db.counts(conn)
        print("database %s (machine %s)" % (db.default_path(), conn.execute("SELECT value FROM meta WHERE key='machine'").fetchone()[0]))
        for s in SIZES:
            r = api.ratings(s, conn, ros)
            ids = list(ros.at(s))
            unplaced = sum(1 for i in ids if r.rat[i]["games"] < PLACEMENT)
            half = sorted(1.96 * r.rat[i]["se"] for i in ids)
            print("%dv%d: %5d matches counted (%d stale), %3d entries, %3d unplaced, median ±%.0f" % (
                s, s, r.matches, sum(cnt.get(s, (0, 0))) - r.matches, len(ids), unplaced, half[len(half) // 2] if half else 0))
    elif a.cmd == "roster":
        ros = roster.get()
        for i, e in sorted(ros.entries.items()):
            print("%-40s %-7s %-6s sizes %s sha %s%s" % (i, e.kind, e.sub, "".join(str(n) for n in e.sizes()), e.sha,
                                                         "  (also %s)" % ", ".join(e.aliases) if e.aliases else ""))
    elif a.cmd == "refine":
        api.refine(log=lambda s: print(time.strftime("%H:%M:%S"), s, flush=True))
    elif a.cmd == "archive":
        info = api.archive(a.label, dry_run=not a.yes)
        if not info["files"]:
            print("nothing to archive: no database here")
            return 1
        print(("moved" if a.yes else "would move") + ": %(from)s -> %(to)s (%(matches)d matches)" % info)
        if not a.yes:
            print("this starts the ratings over (every entry back to the prior, placement games first); add --yes to do it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
