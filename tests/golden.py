"""Reference results for the regression tests (tests/golden/<name>.json).

Each test computes a JSON value from the current code and compares it with the stored one; `--update` stores the new value
instead. A difference means the code now behaves differently: fix it, or, if the change is intended, run the test with
--update and commit the new file together with the change.

The matches are chaotic: a last-bit difference in a float (another CPU, another libm or BLAS) grows into a different match.
The files record the machine they were made on; a FAIL on another machine can be that, not a bug (re-record there to check)."""
import json
import os
import platform

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden")


def rounded(v, nd=6):
    """The value with every float rounded to `nd` significant decimals (what the files store)."""
    if isinstance(v, float):
        return float("%.*g" % (nd, v)) if v == v else None
    if isinstance(v, dict):
        return {str(k): rounded(x, nd) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [rounded(x, nd) for x in v]
    if isinstance(v, complex):
        return [rounded(v.real, nd), rounded(v.imag, nd)]
    return v


def diff(a, b, path="", rel=1e-9):
    """Differences between two JSON values: (path, got, want)."""
    if isinstance(a, dict) and isinstance(b, dict):
        return [d for k in sorted(set(a) | set(b)) for d in diff(a.get(k), b.get(k), path + "." + str(k), rel)]
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [(path, "length %d" % len(a), "length %d" % len(b))]
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in diff(x, y, "%s[%d]" % (path, i), rel)]
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return [] if abs(a - b) <= rel * max(1.0, abs(b)) else [(path, a, b)]
    return [] if a == b else [(path, a, b)]


def check(name, got, update, label=None, show=6):
    """Compares `got` with tests/golden/<name>.json (or stores it with update). Prints one line; True if equal."""
    path = os.path.join(GOLDEN, name + ".json")
    got = json.loads(json.dumps(rounded(got)))
    label = label or name
    if update:
        os.makedirs(GOLDEN, exist_ok=True)
        with open(path, "w") as f:
            json.dump({"machine": "%s %s, Python %s" % (platform.system(), platform.machine(), platform.python_version()),
                       "data": got}, f, indent=None, separators=(",", ":"), sort_keys=True)
            f.write("\n")
        print("%-24s stored" % label)
        return True
    if not os.path.exists(path):
        print("%-24s FAIL  no reference file (run with --update)" % label)
        return False
    ref = json.load(open(path))
    bad = diff(got, ref["data"])
    print("%-24s %s%s" % (label, "OK" if not bad else "FAIL  %d differences" % len(bad),
                          "" if not bad else "".join("\n      %s: got %r, want %r" % d for d in bad[:show])))
    if bad and not ref.get("machine", "").startswith("%s %s" % (platform.system(), platform.machine())):
        print("      (recorded on %s: float noise from another machine can do this)" % ref.get("machine"))
    return not bad
