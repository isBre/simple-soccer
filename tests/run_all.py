"""Runs every test (python3 tests/run_all.py [--update]); --update re-records the reference files of the regression tests
(tests/golden/) after an intended change of behaviour. test_web.py starts the web app on a free port (~30 s)."""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = ["test_rng.py", "test_match.py", "test_view.py", "test_env.py", "test_evaluate.py", "test_ladder.py", "test_tournament.py", "test_web.py"]


def main():
    update = [a for a in sys.argv[1:] if a == "--update"]
    failed = []
    for t in TESTS:
        t0 = time.time()
        print("== %s" % t, flush=True)
        args = update if t != "test_web.py" else []
        if subprocess.run([sys.executable, os.path.join(HERE, t)] + args).returncode != 0:
            failed.append(t)
        print("   (%.0f s)" % (time.time() - t0), flush=True)
    print("ALL PASS" if not failed else "FAILED: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
