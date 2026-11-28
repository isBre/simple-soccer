"""The random generator (soccer/core/rng.py, a copy of Godot's PCG32) against its stored outputs (tests/golden/rng.json).
Every match seed, kickoff and random start comes from it, so its outputs must never change.

  python3 tests/test_rng.py [--update]"""
import sys

from soccer.core.rng import RandomNumberGenerator
import golden

SEEDS = [0, 1, 42, 12345, 987654321, (1 << 40) + 7]


def outputs():
    out = {}
    for s in SEEDS:
        r = RandomNumberGenerator(s)
        d = {"state0": r.get_state()}
        d["randi"] = [r.randi() for _ in range(40)]
        d["randf"] = [r.randf() for _ in range(40)]
        d["randfn"] = [r.randfn(0.0, 1.0) for _ in range(20)] + [r.randfn(0.0, 0.55) for _ in range(20)]
        d["randf_range"] = [r.randf_range(-10.0, 10.0) for _ in range(20)] + [r.randf_range(0.0, 3.0) for _ in range(20)]
        d["randi_range"] = [r.randi_range(6, 28) for _ in range(20)] + [r.randi_range(-3, 1000003) for _ in range(20)]
        d["state1"] = r.get_state()
        out[str(s)] = d
    return out


def main():
    ok = golden.check("rng", outputs(), "--update" in sys.argv, "rng (%d seeds)" % len(SEEDS))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
