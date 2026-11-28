"""Fair information (docs/public_view.md): every player decides alone, from its team's public view only.

  imports     the decision modules (soccer/ai/: agent, kit, view, skill, nets and every archetype of players/) import nothing
              from the match engine but its public constants (physics, frame numbers, the list of calls)
  names       they never name the engine's or another agent's inside (a player's bot or card, the config, the AI)
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
from soccer.match import Match, MatchConfig, Player, make_config
from soccer.players import PlayerDef
from soccer.ai.view import GENERIC_DELAY, View

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

AGENTS = ["soccer/ai/agent.py", "soccer/ai/kit.py", "soccer/ai/nets.py", "soccer/ai/obs.py", "soccer/ai/skill.py"] + \
    sorted("soccer/ai/players/" + f for f in os.listdir(os.path.join(ROOT, "soccer", "ai", "players")) if f.endswith(".py"))
DECIDE = AGENTS + ["soccer/ai/view.py"]
PUBLIC = {"KICK_RANGE", "KICK_STRENGTH", "BALL_DAMPING", "PLAYER_DAMPING", "PLAYER_ACCEL", "PLAYER_KICK_ACCEL", "AI_PERIOD", "DIRS", "GOAL", "HIST", "PLAYING", "ENDED", "TICK", "INTENTS"}
ENGINE = {"match", "physics", "control"}                       # the engine modules: only PUBLIC names may come from them
FORBIDDEN = {"bot_ai", "pdef", "cfg", "ai", "players_real", "humans", "team_lists_real"}


def check(name, ok, detail=""):
    print("%-11s %s  %s" % (name, "OK  " if ok else "FAIL", detail))
    return ok


def imports_ok():
    bad = []
    for f in DECIDE:
        for node in ast.walk(ast.parse(open(os.path.join(ROOT, f)).read())):
            if isinstance(node, ast.ImportFrom):
                mod = (node.module or "").split(".")[-1]
                if mod in ENGINE:                       # from ..match import X: only public constants
                    bad += ["%s: %s" % (f, a.name) for a in node.names if a.name not in PUBLIC]
                elif mod in ("", "soccer"):             # from .. import match / from soccer import physics: a whole engine module
                    bad += ["%s: import %s" % (f, a.name) for a in node.names if a.name in ENGINE]
            if isinstance(node, ast.Import) and any(a.name.split(".")[-1] in ENGINE for a in node.names):
                bad.append("%s: import of the engine" % f)
    return check("imports", not bad, "; ".join(bad) or "only public constants from the engine")


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
    m = Match(cfg)
    for _ in range(600):
        m.step()
    cfg2 = make_config("iron_wall", "academy", "arena", 3, 30.0, 5)     # rule-based on both sides
    m2 = Match(cfg2)
    for _ in range(600):
        m2.step()
    leaks = []
    for mm in (m, m2):
        agents = [p.bot_ai for p in mm.players]
        for p in mm.players:
            others = {id(a) for a in agents if a is not p.bot_ai}
            for o in reachable([p.bot_ai], (Match, Player, MatchConfig, PlayerDef, View)):
                if isinstance(o, (Match, Player, MatchConfig, PlayerDef, View)) or (id(o) in others and not _shared_ok(o)):
                    leaks.append("%s %s reaches %s" % (mm.cfg.teams[p.team].id, p.pdef.name, type(o).__name__))
        views = mm.ai.views
        for t in (0, 1):
            for o in reachable([views[t]], (Match, Player, MatchConfig, PlayerDef)):
                if isinstance(o, (Match, Player, MatchConfig, PlayerDef)) or (isinstance(o, View) and o is not views[t]) or id(o) in map(id, agents):
                    leaks.append("view %d reaches %s" % (t, type(o).__name__))
    ok &= check("alone", not leaks, "; ".join(sorted(set(leaks))) or "no agent reaches the match, a view or another agent, teammates included")
    heard = {0: set(), 1: set()}
    m3 = Match(make_config("arrows", "aurora", "arena", 5, 60.0, 6))
    for _ in range(2400):
        m3.step()
        for t in (0, 1):
            v = m3.ai.views[t]
            heard[t] |= {b.intent for b in v.team_lists[t]}
            if any(b.intent != "none" for b in v.team_lists[1 - t]):
                heard[t].add("THEIRS")
    ok &= check("calls", all(len(h - {"none"}) >= 3 and "THEIRS" not in h for h in heard.values()),
                "team 0 heard %s, team 1 heard %s" % (sorted(heard[0]), sorted(heard[1])))
    bad = []
    for mm in (m, m2):
        for t in (0, 1):
            v = mm.ai.views[t]
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
        m4 = Match(make_config("arrows", "aurora", "arena", size, 30.0, 8))
        for k in range(900):
            m4.step()
            if k % 97:
                continue
            for t in (0, 1):
                v = m4.ai.views[t].refresh(m4)
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
    m = Match(make_config("arrows", "aurora", "arena", 5, 30.0, 5))
    early = m.ai.views
    ghosts = [p for p in m.team_lists[0] if p.line != "GK"][:2] + [p for p in m.team_lists[1] if p.line != "GK"][:3]
    for g in ghosts:
        g.bot = False
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
