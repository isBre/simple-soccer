"""Adds the TAP hook tests/godot/record_env.gd needs to a reference checkout's match_sim.gd (test instrumentation only):
a static callable called right after the brain set the bots' inputs of a tick."""
import sys

path = sys.argv[1] + "/scripts/core/match_sim.gd"
s = open(path).read()
if "static var TAP" not in s:
    s = s.replace("const HIST := 32\n", "const HIST := 32\nstatic var TAP = null      # tests: called after the AI of each tick\n", 1)
    old = "        brain.decide(self, update)          # team plans every AI_PERIOD ticks, then the bots that are due\n"
    assert old in s, "unexpected match_sim.gd"
    s = s.replace(old, old + "        if TAP != null:\n            TAP.call(self)\n", 1)
    open(path, "w").write(s)
print("tap ok")
