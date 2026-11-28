"""The vector helpers (soccer/vec.py) and the physics numbers the AI writes out (soccer/ai/kit.py) against the engine's.

  roundi      halves away from zero, like Godot's roundi (Python's round() rounds halves to even), and returns an int
  vectors     normalized, limit_length, dot, cross, rotated on plain cases
  angles      vec.from_angle (cmath.rect, the AI's) and match.from_angle (cos / sin, the engine's) agree to 1e-15
              (they are not bit-identical: soccer/match.py says why both exist)
  physics     kit.TOP, kit.TAU and kit._BALL_LOSS agree with soccer.match's BALL_DAMPING / PLAYER_DAMPING / PLAYER_ACCEL

  python3 tests/test_vec.py"""
import math
import random
import sys

from soccer import match, vec
from soccer.ai import kit


def check(name, ok, detail):
    print("%-9s %s  %s" % (name, "OK  " if ok else "FAIL", detail))
    return ok


def main():
    cases = {0.5: 1, 1.5: 2, 2.5: 3, -0.5: -1, -1.5: -2, -2.5: -3, 0.49: 0, -0.49: 0, 0.0: 0, 7.0: 7}
    bad = ["roundi(%r) = %r" % (x, vec.roundi(x)) for x, want in cases.items()
           if vec.roundi(x) != want or not isinstance(vec.roundi(x), int)]
    ok = check("roundi", not bad, "; ".join(bad) or "%d cases" % len(cases))

    bad = []
    if vec.normalized(0j) != 0j or abs(vec.normalized(3 + 4j) - (0.6 + 0.8j)) > 1e-15:
        bad.append("normalized")
    if vec.limit_length(3 + 4j, 10.0) != 3 + 4j or abs(abs(vec.limit_length(3 + 4j, 1.0)) - 1.0) > 1e-15:
        bad.append("limit_length")
    if vec.dot(1 + 2j, 3 + 4j) != 11.0 or vec.cross(1 + 0j, 1j) != 1.0 or vec.cross(1j, 1 + 0j) != -1.0:
        bad.append("dot / cross")
    if abs(vec.rotated(1 + 0j, math.pi / 2) - 1j) > 1e-15 or vec.clamp(5.0, 0.0, 1.0) != 1.0 or vec.lerp(2.0, 4.0, 0.25) != 2.5:
        bad.append("rotated / clamp / lerp")
    ok &= check("vectors", not bad, "; ".join(bad) or "normalized, limit_length, dot, cross, rotated, clamp, lerp")

    rng = random.Random(1)
    worst = max(abs(vec.from_angle(a) - match.from_angle(a)) for a in (rng.uniform(-7.0, 7.0) for _ in range(20000)))
    ok &= check("angles", worst < 1e-15, "largest difference %.1e over 20000 angles" % worst)

    d, acc = match.PLAYER_DAMPING, match.PLAYER_ACCEL
    errs = {"TOP": kit.TOP - acc * d / (1.0 - d), "TAU": kit.TAU - d / (1.0 - d), "_BALL_LOSS": kit._BALL_LOSS - (1.0 - match.BALL_DAMPING)}
    bad = ["%s off by %.1e" % (k, e) for k, e in errs.items() if abs(e) > 1e-9]
    ok &= check("physics", not bad, "; ".join(bad) or "kit's TOP, TAU and ball loss match the engine")
    print("TOTAL ->", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
