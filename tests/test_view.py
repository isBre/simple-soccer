"""Fair information (docs/public_view.md): every agent decides from its team's public view only.

  imports     the decision modules (soccer/ai/rules.py, nets.py, view.py, skill.py) import nothing from the match engine but its
              public constants (physics and frame numbers)
  names       they never name the engine's or another agent's inside (the match's brains, a player's bot or card, the config)
  reach       after a mixed match (rule-based and net players on both sides), nothing a team's agents hold (its view, brains,
              bots) leads to the match, a real player, a card, or the other team's view, brain or bot
  opponents   a team's view of the opponents is anonymous and empty inside: no brain, no buttons, no human flag; the generic
              skill for everyone but yourself

  python3 tests/test_view.py"""
import ast
import gc
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np                                                   # noqa: E402
from soccer.match import Match, MatchConfig, Player, make_config   # noqa: E402
from soccer.players import PlayerDef                                # noqa: E402
from soccer.ai.view import GENERIC_DELAY, View                     # noqa: E402

DECIDE = ["soccer/ai/rules.py", "soccer/ai/nets.py", "soccer/ai/view.py", "soccer/ai/skill.py"]
PUBLIC = {"KICK_RANGE", "KICK_STRENGTH", "AI_PERIOD", "DIRS", "GOAL", "HIST", "PLAYING", "ENDED", "TICK"}
FORBIDDEN = {"brains", "team_brains", "bot_ai", "pdef", "cfg", "ai", "players_real", "_rollout"}


def check(name, ok, detail=""):
    print("%-11s %s  %s" % (name, "OK  " if ok else "FAIL", detail))
    return ok


def imports_ok():
    bad = []
    for f in DECIDE:
        for node in ast.walk(ast.parse(open(os.path.join(ROOT, f)).read())):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("match"):
                bad += ["%s: %s" % (f, a.name) for a in node.names if a.name not in PUBLIC]
            if isinstance(node, ast.Import) and any(a.name.endswith("soccer.match") for a in node.names):
                bad.append("%s: import soccer.match" % f)
    return check("imports", not bad, "; ".join(bad) or "only public constants from the engine")


def names_ok():
    bad = []
    for f in ("soccer/ai/rules.py", "soccer/ai/nets.py"):
        for node in ast.walk(ast.parse(open(os.path.join(ROOT, f)).read())):
            if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN:
                bad.append("%s:%d .%s" % (f, node.lineno, node.attr))
    return check("names", not bad, "; ".join(bad) or "no engine or agent inside named")


def reachable(roots, stop):
    """Every object reachable from `roots` (modules, classes, functions and numpy arrays are not followed)."""
    seen, todo, out = set(), list(roots), []
    while todo:
        o = todo.pop()
        if id(o) in seen or isinstance(o, (types.ModuleType, type, types.FunctionType, types.BuiltinFunctionType, np.ndarray,
                                           str, bytes, int, float, complex, bool)) or o is None:
            continue
        seen.add(id(o))
        out.append(o)
        if isinstance(o, stop):
            continue
        todo.extend(gc.get_referents(o))
    return out


def main():
    ok = imports_ok() & names_ok()
    cfg = make_config("all_stars", "net_lab", "arena", 5, 30.0, 4)      # rule + net players vs nets (and a mixed team)
    m = Match(cfg)
    for _ in range(600):
        m.step()
    cfg2 = make_config("iron_wall", "academy", "arena", 3, 30.0, 5)     # rule-based on both sides
    m2 = Match(cfg2)
    for _ in range(600):
        m2.step()
    leaks = []
    for mm in (m, m2):
        views = mm.ai.views
        for t in (0, 1):
            mine = [views[t]] + mm.team_brains[t] + [p.bot_ai for p in mm.team_lists[t]]
            theirs = {id(x) for x in [views[1 - t]] + mm.team_brains[1 - t] + [p.bot_ai for p in mm.team_lists[1 - t]]}
            for o in reachable(mine, (Match, Player, MatchConfig, PlayerDef, View)):
                if isinstance(o, (Match, Player, MatchConfig, PlayerDef)) or (isinstance(o, View) and o is not views[t]) \
                        or (id(o) in theirs and not _shared_ok(o)):
                    leaks.append("%s team %d reaches %s" % (mm.cfg.teams[t].id, t, type(o).__name__))
    ok &= check("reach", not leaks, "; ".join(sorted(set(leaks))) or "no team's agents reach the match, a real player or the other team")
    bad = []
    for mm in (m, m2):
        for t in (0, 1):
            v = mm.ai.views[t]
            for b in v.team_lists[1 - t]:
                if b.brain is not None or b.input_dir != 0j or b.input_kick or b.kick_intent or b.is_human:
                    bad.append("team %d sees inside opponent %d" % (t, b.uid))
            if any(b.reaction_delay != GENERIC_DELAY for b in v.players):
                bad.append("a body carries a real skill")
            if v.kickoff_team != t and v.kickoff_go is not None:
                bad.append("team %d knows the other team's kickoff timer" % t)
    ok &= check("opponents", not bad, "; ".join(bad) or "anonymous, nothing inside, generic skill")
    print("TOTAL ->", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def _shared_ok(o):
    """Objects both teams may hold: a net's weights (public, no state) are shared when both sides load the same net."""
    from soccer.ai.nets import Net
    return isinstance(o, Net)


if __name__ == "__main__":
    sys.exit(main())
