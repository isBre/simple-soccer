"""Python's copy of Godot's random generator (soccer/rng.py) against the real thing (tests/reference/rng_probe.gd, run in the
Godot reference checkout $SOCCER_REF, see tests/test_match.py).
Run: SOCCER_REF=... python3 tests/test_rng.py   (needs Godot; SOCCER_GODOT or the default path)"""
import base64, json, struct, sys
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))))
from soccer.rng import RandomNumberGenerator
from tests.godot_run import install_reference, run_scene


def main():
    ref = __import__("os").environ.get("SOCCER_REF")
    if not ref:
        sys.exit("set SOCCER_REF to a checkout of the Godot implementation (see tests/test_match.py)")
    install_reference(ref)
    g = json.loads(run_scene("res://tests/godot/rng_probe.tscn", "RNG ", project=ref))
    exact = 0
    worst_randfn = 0.0
    n_randfn = n_randfn_exact = 0
    for s, d in g.items():
        r = RandomNumberGenerator(int(s))
        assert r.get_state() == int(d["state0"]), ("state after seeding", s)
        ints, fl = [], []
        ints += [r.randi() for _ in range(40)]
        fl += [r.randf() for _ in range(40)]
        fl += [r.randfn(0.0, 1.0) for _ in range(40)]
        fl += [r.randfn(0.0, 0.55) for _ in range(40)]
        fl += [r.randf_range(-10.0, 10.0) for _ in range(40)]
        fl += [r.randf_range(0.0, 3.0) for _ in range(40)]
        ints += [r.randi_range(6, 28) for _ in range(40)]
        ints += [r.randi_range(-3, 1000003) for _ in range(40)]
        gf = struct.unpack("<%dd" % len(fl), base64.b64decode(d["floats"]))
        assert ints == d["ints"], ("integers", s)
        assert fl[:40] == list(gf[:40]), ("randf", s)
        assert fl[120:] == list(gf[120:]), ("randf_range", s)
        for a, b in zip(fl[40:120], gf[40:120]):
            n_randfn += 1
            n_randfn_exact += a == b
            worst_randfn = max(worst_randfn, abs(a - b) / max(abs(b), 1e-30))
        assert r.get_state() == int(d["state1"]), ("state at the end", s)
        exact += 1
    assert worst_randfn < 3e-7, worst_randfn
    print("rng: %d seeds; randi, randi_range, randf, randf_range, state exact; randfn %d / %d exact, worst relative diff %.1e"
          % (exact, n_randfn_exact, n_randfn, worst_randfn))


if __name__ == "__main__":
    main()
