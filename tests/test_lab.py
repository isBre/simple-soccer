"""The Lab's experiment specs (lab/tracker.py), without training anything:
  curriculum   a curriculum spec becomes one spec per stage, in order: <name>_1v0, <name>_1v1, ..., the first from scratch, each
               next from the previous stage's best checkpoint, all on the slots observation, sizes and opponents as given
  validation   the stages of a curriculum are valid together (a stage may start from an earlier stage of the same batch); a
               size below 5 without the slots observation, an unknown opponent mode or a missing start are refused

  python3 tests/test_lab.py"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lab import tracker  # noqa: E402


def check(name, ok, detail=""):
    print("%-11s %s    %s" % (name, "OK" if ok else "FAIL", detail))
    return ok


def main():
    spec = {"name": "zz_test_cur", "updates": 300, "args": {"seed": 3, "elo_pairs": 8}, "plateau": 3, "notes": "test",
            "stages": [{"size": 1, "opp": "none", "updates": 150}, {"size": 1}, {"size": 2, "updates": 400, "args": {"lr": 5e-5}},
                       {"size": 5, "min_updates": 200}]}
    st = tracker.expand(spec)
    names = [s["name"] for s in st]
    ok = check("curriculum", names == ["zz_test_cur_1v0", "zz_test_cur_1v1", "zz_test_cur_2v2", "zz_test_cur_5v5"]
               and st[0]["start"] == "scratch" and st[1]["start"] == "best:zz_test_cur_1v0" and st[3]["start"] == "best:zz_test_cur_2v2"
               and all(s["obs"] == "slots" and s["curriculum"] == "zz_test_cur" for s in st)
               and [s["size"] for s in st] == [1, 1, 2, 5] and st[0]["opp"] == "none" and st[1]["opp"] == "rules"
               and st[2]["args"] == {"seed": 3, "elo_pairs": 8, "lr": 5e-5} and st[0]["updates"] == 150 and st[1]["updates"] == 300
               and tracker.start_model(st[0]) is None and tracker.start_model(st[2]) == "out_5v5/ckpt/x_zz_test_cur_1v1_best.pt"
               and tracker.expand({"name": "plain", "start": "x.pt"}) == [{"name": "plain", "start": "x.pt"}],
               " -> ".join(names))
    errs, earlier = [], []
    for s in st:
        errs += tracker.validate_spec(s, earlier)
        earlier.append(s["name"])
    bad = [tracker.validate_spec({"name": "zz_bad_a", "start": "scratch", "size": 3}),
           tracker.validate_spec({"name": "zz_bad_b", "start": "scratch", "obs": "slots", "size": 2, "opp": "keeper"}),
           tracker.validate_spec({"name": "zz_bad_c", "start": "best:zz_never_ran", "obs": "slots", "size": 2})]
    ok &= check("validation", not errs and all(bad), "stages valid together%s; refused: %s" % (
        " (" + "; ".join(errs) + ")" if errs else "", " | ".join(b[0] for b in bad if b)))
    print("TOTAL -> %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
