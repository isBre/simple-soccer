"""Fair information (docs/public_view.md): every player decides alone, from its team's public view only.

  imports     the brains (soccer/ai/: kit, skill, nets, obs, person and every archetype of players/) import from the core only
              what a player may know (core.public, core.act, core.vec) and nothing from the game layer
  names       they never name the engine's or another brain's inside (a seat's brain or label, the config, the people)
  alone       after a mixed match (rule-based and net players on both sides), nothing an agent holds leads to the match, a real
              player, a card, a view, or any other agent, teammates included (a net's weights are shared, they have no state)
  calls       teammates hear each other's calls (some own-team body carries one during the match); the opponents' calls are
              never in a team's view
  opponents   a team's view of the opponents is anonymous: no calls, no human flag; the generic skill for everyone but yourself
  obs         every net observation (soccer/ai/obs.py: slots76 and the ego layout at 1v1 / 3v3 / 5v5, team46, rank56 and the
              batched features_many at 5v5) built from a team's view equals the one built from the match: a net reads nothing
              the view does not have
  ghosts      with players taken off the pitch (training), views built before and after keep them in team_lists where the
              match parks them, leave them out of in_play / players, and still give the match's numbers for every observation

  python3 tests/test_view.py"""
import ast
import gc
import os
import sys
import types

import numpy as np
from soccer.core.match import Match, Player
from soccer.core.view import GENERIC_DELAY, View
from soccer.game import MatchConfig, make_config, new_match
from soccer.players import PlayerDef

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

AGENTS = sorted("soccer/ai/" + f for f in os.listdir(os.path.join(ROOT, "soccer", "ai")) if f.endswith(".py")) + \
    sorted("soccer/ai/players/" + f for f in os.listdir(os.path.join(ROOT, "soccer", "ai", "players")) if f.endswith(".py"))
ALLOWED = {"public", "act", "vec"}                             # what a brain may import from the core: what a player may know
LAYERS = {"core", "game"}                                       # a brain may import nothing else from these packages
FORBIDDEN = {"brain", "label", "cfg", "setup", "ai", "players_real", "humans", "people", "team_lists_real"}


def check(name, ok, detail=""):
    print("%-11s %s  %s" % (name, "OK  " if ok else "FAIL", detail))
    return ok


def _target(f, node):
    """The absolute dotted module an ImportFrom in file f names (relative imports resolved)."""
    if not node.level:
        return node.module or ""
    pkg = f[:-3].split("/")[:-node.level]
    return ".".join(pkg + ([node.module] if node.module else []))


def imports_ok():
    bad = []
    for f in AGENTS:
        for node in ast.walk(ast.parse(open(os.path.join(ROOT, f)).read())):
            if isinstance(node, ast.ImportFrom):
                mod = _target(f, node).split(".")
                names = [a.name for a in node.names]
                if mod[:2] == ["soccer", "core"] and len(mod) == 3 and mod[2] not in ALLOWED:
                    bad.append("%s: soccer.core.%s" % (f, mod[2]))
                elif mod == ["soccer", "core"]:
                    bad += ["%s: soccer.core.%s" % (f, n) for n in names if n not in ALLOWED]
                elif mod[:2] == ["soccer", "game"] or (mod == ["soccer"] and any(n in LAYERS for n in names)):
                    bad.append("%s: the game layer" % f)
                elif mod[:1] == ["soccer"] and len(mod) == 2 and mod[1] not in ("ai", "core", "game"):
                    bad.append("%s: soccer.%s" % (f, mod[1]))
            if isinstance(node, ast.Import) and any(a.name.startswith("soccer.core.") and a.name.split(".")[2] not in ALLOWED
                                                    or a.name.startswith("soccer.game") for a in node.names):
                bad.append("%s: import of the engine or the game" % f)
    return check("imports", not bad, "; ".join(bad) or "from the core only what a player may know, nothing from the game layer")


def names_ok():
    bad = []
    for f in AGENTS:
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
    m = new_match(cfg)
    for _ in range(600):
        m.step()
    cfg2 = make_config("iron_wall", "academy", "arena", 3, 30.0, 5)     # rule-based on both sides
    m2 = new_match(cfg2)
    for _ in range(600):
        m2.step()
    leaks = []
    for mm in (m, m2):
        agents = [p.brain for p in mm.players]
        for p in mm.players:
            others = {id(a) for a in agents if a is not p.brain}
            for o in reachable([p.brain], (Match, Player, MatchConfig, PlayerDef, View)):
                if isinstance(o, (Match, Player, MatchConfig, PlayerDef, View)) or (id(o) in others and not _shared_ok(o)):
                    leaks.append("%s %s reaches %s" % (mm.setup.team_ids[p.team], p.label.name, type(o).__name__))
        views = mm.views
        for t in (0, 1):
            for o in reachable([views[t]], (Match, Player, MatchConfig, PlayerDef)):
                if isinstance(o, (Match, Player, MatchConfig, PlayerDef)) or (isinstance(o, View) and o is not views[t]) or id(o) in map(id, agents):
                    leaks.append("view %d reaches %s" % (t, type(o).__name__))
    ok &= check("alone", not leaks, "; ".join(sorted(set(leaks))) or "no agent reaches the match, a view or another agent, teammates included")
    heard = {0: set(), 1: set()}
    m3 = new_match(make_config("arrows", "aurora", "arena", 5, 60.0, 6))
    for _ in range(2400):
        m3.step()
        for t in (0, 1):
            v = m3.views[t]
            heard[t] |= {b.intent for b in v.team_lists[t]}
            if any(b.intent != "none" for b in v.team_lists[1 - t]):
                heard[t].add("THEIRS")
    ok &= check("calls", all(len(h - {"none"}) >= 3 and "THEIRS" not in h for h in heard.values()),
                "team 0 heard %s, team 1 heard %s" % (sorted(heard[0]), sorted(heard[1])))
    bad = []
    for mm in (m, m2):
        for t in (0, 1):
            v = mm.views[t]
            for b in v.team_lists[1 - t]:
                if b.intent != "none" or b.is_human:
                    bad.append("team %d hears opponent %d" % (t, b.uid))
            if any(b.reaction_delay != GENERIC_DELAY for b in v.players):
                bad.append("a body carries a real skill")
            if v.kickoff_team != t and v.kickoff_go is not None:
                bad.append("team %d knows the other team's kickoff timer" % t)
    ok &= check("opponents", not bad, "; ".join(bad) or "anonymous, no calls, generic skill")
    from soccer.ai import obs
    layouts = {"slots76": lambda m, ps: [x for p in ps for x in obs.features_slots(m, p)],
               "team46": lambda m, ps: [x for p in ps for x in obs.features_team(m, p)],
               "rank56": lambda m, ps: [x for p in ps for x in obs.features_rank(m, p)],
               "ego": lambda m, ps: [x for p in ps for x in obs.features_ego(m, p)],
               "many": lambda m, ps: obs.features_many(m, ps, team=True, rank=True, legacy=True)}
    diff, n = {k: 0 for k in layouts}, {k: 0 for k in layouts}
    for size in (1, 3, 5):
        m4 = new_match(make_config("arrows", "aurora", "arena", size, 30.0, 8))
        for k in range(900):
            m4.step()
            if k % 97:
                continue
            for t in (0, 1):
                v = m4.views[t].refresh(m4)
                mine = m4.team_lists[t]
                for name, f in layouts.items():
                    if size < 5 and name not in ("slots76", "ego"):
                        continue                       # team46 / rank56 (and features_many with them) are 5v5 layouts
                    n[name] += len(mine)
                    diff[name] += f(v, [v.bodies[p.uid] for p in mine]) != f(m4, mine)
    ok &= check("obs", all(n.values()) and not any(diff.values()),
                ", ".join("%s %d (%d differ)" % (k, n[k], diff[k]) for k in layouts) + ": the view gives the match's numbers")
    ok &= ghosts_ok(layouts)
    print("TOTAL ->", "PASS" if ok else "FAIL")


def ghosts_ok(layouts):
    """Training takes players off the pitch (rl/env.py _ghost: out of m.players and the physics, still in the line-ups, parked
    below the pitch). A view built before (the AI's) and one built after (the trainer's) must both: keep every ghost in
    team_lists where the match has it, leave it out of in_play / players, and give the match's numbers for every
    observation (the slots one with the ghosts as empty slots, also through features_group)."""
    from soccer.ai import obs
    m = new_match(make_config("arrows", "aurora", "arena", 5, 30.0, 5))
    early = m.views
    ghosts = [p for p in m.team_lists[0] if p.line != "GK"][:2] + [p for p in m.team_lists[1] if p.line != "GK"][:3]
    for g in ghosts:
        m.seat(g.uid, None)
        m.movers.remove(g)
        m.players.remove(g)
        g.pos, g.vel = complex(0.0, m.pitch.out_y * 2.5), 0j
    late = [View(m, 0), View(m, 1)]
    gone = {g.uid for g in ghosts}
    bad, n = [], 0
    for k in range(600):
        m.step()
        if k % 60:
            continue
        on = {p.uid for p in m.players}
        for views in (early, late):
            for t in (0, 1):
                v = views[t].refresh(m)
                if {b.uid for b in v.players} != on or any(b.uid in gone for lst in v.in_play for b in lst):
                    bad.append("a ghost is in play in a view")
                if any(v.bodies[g.uid].pos != g.pos for g in ghosts):
                    bad.append("a ghost body is not where the match keeps it")
                mine = [p for p in m.team_lists[t] if p.uid not in gone]
                bodies = [v.bodies[p.uid] for p in mine]
                for name, f in layouts.items():
                    if name == "slots76":
                        got, want = [x for b in bodies for x in obs.features_slots(v, b, on)], \
                            [x for p in mine for x in obs.features_slots(m, p, on)]
                    else:
                        got, want = f(v, bodies), f(m, mine)
                    n += 1
                    if got != want:
                        bad.append("%s differs" % name)
                grouped = [x for o in obs.features_group(v, bodies, obs.SLOTS_OBS) for x in o]
                if grouped != [x for p in mine for x in obs.features_slots(m, p, on)]:
                    bad.append("features_group sees ghosts")
    return check("ghosts", not bad, "; ".join(sorted(set(bad))) or
                 "%d observations with %d ghosts, from views built before and after: in team_lists, not in play, the match's numbers" % (n, len(ghosts)))
    return 0 if ok else 1


def _shared_ok(o):
    """Objects both teams may hold: a net's weights (public, no state) are shared when both sides load the same net."""
    from soccer.ai.nets import Net
    return isinstance(o, Net)


if __name__ == "__main__":
    sys.exit(main())
