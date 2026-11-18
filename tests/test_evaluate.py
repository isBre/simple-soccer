"""The Python evaluations (rl/evaluate.py) against the Godot scenes they replace (rl/league_eval.gd, h2h_eval.gd,
behaviour_stats.gd), run in the reference checkout ($SOCCER_REF):

  league  Godot plays a short league; Python rebuilds the table and the SUMMARY lines from Godot's own per-match results
          (MATCH lines): every line must be identical. rl/teams_info.json must be byte-identical.
  h2h     same for the head-to-head line (two tools/net_server.py instances serve the nets).
  behaviour  Godot's behaviour_stats.gd prints its report; the same 8 matches are recorded tick by tick
          (tests/reference/record_behaviour.gd) and fed to Python's measurements: every printed line and the SCOUT JSON must
          agree (numbers to the printed precision).

  python3 tests/test_evaluate.py        ($SOCCER_REF, $SOCCER_REC as for tests/test_match.py)"""
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "rl"))
import evaluate as ev                                          # noqa: E402
from soccer.match import Match                                 # noqa: E402
from tests import state_codec as sc                            # noqa: E402
from tests.godot_run import GODOT, install_reference           # noqa: E402

REF = os.environ.get("SOCCER_REF", "")
REC = os.environ.get("SOCCER_REC") or os.path.join(tempfile.gettempdir(), "soccer_recordings")


def godot_lines(scene, args, timeout=3600):
    cmd = [GODOT, "--headless", "--path", REF, scene, "--"] + args
    with tempfile.TemporaryFile("w+") as f:          # a file, not a pipe: see tests/godot_run.py
        subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=timeout)
        f.seek(0)
        return f.read().splitlines()


def check_league():
    ok = True
    out = godot_lines("res://rl/league_eval.tscn", ["--model", "res://data/models/rl_5v5_arena_v5.json", "--games", "1",
                                                   "--duration", "20", "--stride", "2"])
    matches = []
    for l in out:
        m = re.match(r"MATCH (\S+) (\d+) (\d+) (\d+) (\d+)$", l)
        if m:
            matches.append((m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))))
    go_table = [l for l in out if re.match(r"^(team |SUMMARY|\S+\s+(weak|average|strong|elite)\s)", l)]
    ids, info = ev.league_teams()
    ids = [i for k, i in enumerate(ids) if k % 2 == 0]
    _, table = ev.league_report("res://data/models/rl_5v5_arena_v5.json", ids, info, matches, 0.0)
    py_table = [l for l in table if not l.startswith("LEAGUE")]
    if py_table != go_table:
        ok = False
        for a, b in zip(py_table, go_table):
            if a != b:
                print("   league line differs:\n     py %s\n     go %s" % (a, b))
    ref_info = open(os.path.join(REF, "rl", "teams_info.json")).read()
    py_info = ev._godot_json([info[i] for i in ev.league_teams()[0]])
    if ref_info != py_info:
        ok = False
        print("   teams_info.json differs")
    print("league     %s  %d matches, %d table / summary lines identical" % ("OK  " if ok else "FAIL", len(matches), len(go_table)))
    return ok


def _net_server(port, model):
    p = subprocess.Popen([sys.executable, os.path.join(REF, "tools", "net_server.py"), "--port", str(port), "--model",
                          os.path.join(REF, model)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return p
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("net server did not start")


def check_h2h():
    servers = [_net_server(7391, "data/models/rl_5v5_arena_v5.json"), _net_server(7392, "data/models/rl_5v5_arena_v4.json")]
    try:
        out = godot_lines("res://rl/h2h_eval.tscn", ["--a", "7391", "--b", "7392", "--name", "RL Team 4", "--games", "3", "--duration", "20"])
    finally:
        for s in servers:
            s.kill()
    matches = []
    for l in out:
        m = re.match(r"MATCH h2h:\S+ (\d+) (\d+) (\d+) (\d+)$", l)
        if m:
            matches.append(tuple(int(m.group(k)) for k in range(1, 5)))
    go = [l for l in out if l.startswith(("H2H", "MATCH "))]
    py = ev.h2h_report("RL Team 4", matches)
    ok = py == go and len(matches) == 6
    print("h2h        %s  %d matches, %d lines identical" % ("OK  " if ok else "FAIL", len(matches), len(go) if ok else 0))
    if not ok:
        print("   py", py[-1], "\n   go", go[-1] if go else None)
    return ok


def _numbers(line):
    """(value, unit of the last printed digit) of every number in a printed line."""
    out = []
    for x in re.findall(r"-?\d+(?:\.\d+)?", line):
        dec = len(x.split(".")[1]) if "." in x else 0
        out.append((float(x), 10.0 ** -dec))
    return out


def check_behaviour():
    rec = os.path.join(REC, "behaviour")
    os.makedirs(rec, exist_ok=True)
    out = godot_lines("res://rl/behaviour_stats.tscn", [])
    godot_lines("res://tests/godot/record_behaviour.tscn", [rec])
    results = []
    for i in range(8):
        cfg = ev.behaviour_cfg(i, None, False)
        m = Match(cfg, ai=False)
        names = sc.names(10)
        n = len(names)
        raw = open(os.path.join(rec, "behaviour_%d.bin" % i), "rb").read()
        meta = json.load(open(os.path.join(rec, "behaviour_%d.json" % i)))
        b = ev.Behaviour()
        for k in range(len(raw) // (8 * n)):
            sc.import_state(m, struct.unpack_from("<%dd" % n, raw, k * 8 * n))
            b.tick(m)
        m.ev_log = meta["ev_log"]
        results.append(b.finish(m, meta["result"]))
    py = ev.behaviour_report(results)
    go = [l for l in out if re.match(r"^(RL Team|rule-based|scores|HEAT|SCOUT)", l)]
    ok = len(py) == len(go)
    n_lines = 0
    for a, b in zip(py, go):
        if a.startswith("scores"):                 # Godot appends the matches in the order its threads finish them
            if sorted(re.findall(r"\[\d+, \d+\]", a)) != sorted(re.findall(r"\[\d+, \d+\]", b)):
                ok = False
                print("   scores differ:\n     py %s\n     go %s" % (a, b))
        elif a.startswith("SCOUT"):
            ja, jb = json.loads(a[6:]), json.loads(b[6:])
            for k in ("shots", "shots_against", "recoveries", "pass_len", "edges"):     # match order: not part of the result
                ja[k], jb[k] = sorted(ja[k], key=json.dumps), sorted(jb[k], key=json.dumps)
            bad = _json_diff(ja, jb)
            if bad:
                ok = False
                print("   SCOUT differs:", bad[:6])
        elif a.startswith("HEAT"):
            na, nb = a.split(), b.split()
            off = sum(1 for x, y in zip(na[5:], nb[5:]) if abs(int(x) - int(y)) > 1)
            if na[:5] != nb[:5] or off:
                ok = False
                print("   HEAT differs (%d cells beyond +-1 per mille):\n     py %s\n     go %s" % (off, a[:100], b[:100]))
        elif a != b:
            na, nb = _numbers(a), _numbers(b)
            # Godot measures distances in 32-bit floats: a printed number may differ by one unit in its last digit
            if len(na) != len(nb) or any(abs(x - y) > u * 1.0001 for (x, u), (y, _) in zip(na, nb)):
                ok = False
                print("   line differs:\n     py %s\n     go %s" % (a, b))
        n_lines += 1
    print("behaviour  %s  8 matches, %d lines compared" % ("OK  " if ok else "FAIL", n_lines))
    return ok


def _json_diff(a, b, path=""):
    out = []
    if isinstance(b, dict):
        for k in set(a) | set(b):
            out += _json_diff(a.get(k), b.get(k), path + "." + k)
    elif isinstance(b, list):
        if not isinstance(a, list) or len(a) != len(b):
            return [(path, "len", len(a) if isinstance(a, list) else a, len(b))]
        for i, (x, y) in enumerate(zip(a, b)):
            out += _json_diff(x, y, "%s[%d]" % (path, i))
    elif isinstance(b, (int, float)) and isinstance(a, (int, float)):
        if abs(a - b) > 1e-6 and abs(a - b) > 0.0101 * max(abs(b) * 0.001, 1.0):   # one unit of the 0.01 rounding at most
            out.append((path, a, b))
    elif a != b:
        out.append((path, a, b))
    return out


def main():
    if not REF:
        sys.exit("set SOCCER_REF to a checkout of the Godot implementation")
    install_reference(REF)
    results = [check_league(), check_h2h(), check_behaviour()]
    print("TOTAL ->", "PASS" if all(results) else "FAIL")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
