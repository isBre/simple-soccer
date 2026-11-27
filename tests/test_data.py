"""The game data (soccer/data.py Database) on a temporary copy of data/:
  loads      the real data loads: every team's line-up names known players, every rule player's style exists
  broken     a file of data/ that is not valid JSON stops the loading with its name (a curated team never vanishes silently)
  my teams   a broken team built in the game (local/my_teams) is skipped, the others still load

  python3 tests/test_data.py"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from soccer.data import Database  # noqa: E402


def check(name, ok, detail=""):
    print("%-10s %s    %s" % (name, "OK" if ok else "FAIL", detail))
    return ok


def main():
    tmp = tempfile.mkdtemp(prefix="soccer_data_")
    mine = os.path.join(tmp, "my_teams")
    os.environ["SOCCER_MY_TEAMS"] = mine
    try:
        for d in ("pitches", "styles", "players", "teams"):
            shutil.copytree(os.path.join(ROOT, "data", d), os.path.join(tmp, "data", d))
        os.makedirs(mine)
        results = []
        db = Database(tmp)
        results.append(check("loads", len(db.teams) > 10 and len(db.players) > 10, "%d players, %d teams" % (len(db.players), len(db.teams))))

        bad = os.path.join(tmp, "data", "teams", "zz_broken.json")
        with open(bad, "w") as f:
            f.write('{"id": "zz_broken", "lineup": [')
        try:
            Database(tmp)
            msg = None
        except ValueError as e:
            msg = str(e)
        results.append(check("broken", msg is not None and "zz_broken.json" in msg, msg or "loaded anyway"))
        os.remove(bad)

        good = sorted(db.players)[0]
        with open(os.path.join(mine, "my_ok.json"), "w") as f:
            f.write('{"id": "my_ok", "name": "OK", "lineup": ["%s"]}' % good)
        with open(os.path.join(mine, "my_bad.json"), "w") as f:
            f.write("{not json")
        with open(os.path.join(mine, "my_gone.json"), "w") as f:
            f.write('{"id": "my_gone", "name": "Gone", "lineup": ["nobody_by_this_name"]}')
        db = Database(tmp)
        results.append(check("my teams", "my_ok" in db.teams and db.teams["my_ok"].custom and "my_gone" not in db.teams,
                             "built teams loaded: %s" % sorted(t for t in db.teams if t.startswith("my_"))))
        ok = all(results)
        print("TOTAL -> %s" % ("PASS" if ok else "FAIL"))
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
