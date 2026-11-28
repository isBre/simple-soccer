"""The core on its own (soccer/core): a match plays with brains defined right here, and nothing from soccer.ai or soccer.game.

  plays     every seat holds a tiny brain (run to the ball, kick it): the match ends with a valid result
  cadence   a person is asked every tick; a bot every AI_PERIOD ticks, staggered by slot, always with a view of its own team
  batch     brains sharing a batch are asked once per tick, together, for all their seats that are due
  seats     a person leaving a seat leaves no buttons held; an empty seat is driven with act(), a seat with a brain is not
  alone     the core imports no brain and no game module

  python3 tests/test_core.py"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from soccer.core.act import Act                       # noqa: E402
from soccer.core.match import Match, MatchSetup        # noqa: E402
from soccer.core.pitch import Pitch                    # noqa: E402
from soccer.core.public import AI_PERIOD, ENDED        # noqa: E402


class Label:
    def __init__(self, i):
        self.id, self.name, self.kind = "p%d" % i, "Player %d" % i, "test"


def setup(size=3, seed=3, duration=20.0):
    spots = [("GK", -0.85, 0.0), ("DEF", -0.45, 0.4), ("FWD", -0.2, -0.3), ("MID", -0.3, 0.0), ("FWD", -0.1, 0.5)][:size]
    return MatchSetup(Pitch({}), [[(Label(t * 10 + i), line, fx, fy) for i, (line, fx, fy) in enumerate(spots)] for t in (0, 1)],
                      ["home", "away"], duration, seed=seed)


class Chaser:
    """Runs at the ball and holds kick when close; records when and with which view it was asked."""

    def __init__(self, log=None):
        self.log = log if log is not None else []

    def decide(self, view, me):
        self.log.append((view.tick, view.team, me.uid))
        d = view.ball_pos - me.pos
        return Act(d / abs(d) if abs(d) > 1e-9 else 0j, abs(d) < 30.0, "ball")


class Person:
    person = True

    def __init__(self):
        self.asked, self.dir, self.kick = [], 1 + 0j, True

    def decide(self, view, me):
        self.asked.append(me.uid)
        return Act(self.dir, self.kick)


class Batch:
    def __init__(self):
        self.calls = []

    def decide_batch(self, views, seats):
        self.calls.append((views[0].tick, [me.uid for _, me in seats]))
        return [Act(1j, False) for _ in seats]


class Batched:
    def __init__(self, batch):
        self.batch = batch

    def decide(self, view, me):
        raise AssertionError("a batched brain is asked through its batch")


def check(name, ok, detail):
    print("%-9s %s  %s" % (name, "OK  " if ok else "FAIL", detail))
    return ok


def plays():
    m = Match(setup(), lambda m: {p.uid: Chaser() for p in m.players})
    m.run_to_end()
    r = m.make_result()
    ok = m.state == ENDED and r["teams"] == ["home", "away"] and len(r["players"]) == 6 and r["players"][0]["name"] == "Player 0"
    return check("plays", ok, "%d ticks, %d-%d, %d touches" % (r["ticks"], r["scores"][0], r["scores"][1],
                                                              sum(t["touches"] for t in r["team_stats"])))


def cadence():
    log, person = [], Person()
    m = Match(setup(), lambda m: {**{p.uid: Chaser(log) for p in m.players}, m.team_lists[0][1].uid: person})
    for _ in range(40):
        m.step()
    bad = []
    if len(person.asked) != 40:
        bad.append("the person was asked %d times in 40 ticks" % len(person.asked))
    for tick, team, uid in log:
        p = m.by_uid[uid]
        if (tick + p.slot) % AI_PERIOD or team != p.team:
            bad.append("seat %d asked at tick %d with team %d's view" % (uid, tick, team))
    for p in m.players:
        if p.is_human:
            continue
        n = sum(1 for _, _, u in log if u == p.uid)
        if n != 40 // AI_PERIOD:
            bad.append("seat %d asked %d times in 40 ticks" % (p.uid, n))
    if m.people_seats() != [m.team_lists[0][1]]:
        bad.append("people_seats")
    return check("cadence", not bad, "; ".join(sorted(set(bad))[:3]) or "person every tick, bots every %d ticks by slot" % AI_PERIOD)


def batch():
    b = Batch()
    m = Match(setup(), lambda m: {p.uid: Batched(b) for p in m.players})
    for _ in range(10):
        m.step()
    due = lambda t: sorted(p.uid for p in m.players if (t + p.slot) % AI_PERIOD == 0)
    ok = len(b.calls) == 10 and all(sorted(uids) == due(t) for t, uids in b.calls) \
        and all(m.by_uid[u].input_dir == 1j for u in b.calls[-1][1])
    return check("batch", ok, "one call per tick for exactly the seats due (%s seats)" % "/".join(sorted({str(len(u)) for _, u in b.calls})))


def seats():
    person = Person()
    m = Match(setup(), lambda m: {p.uid: Chaser() for p in m.players if p.team == 1})
    me = m.team_lists[0][0]
    m.seat(me.uid, person)
    m.step()
    held = me.input_dir == 1 + 0j and me.input_kick
    m.seat(me.uid, None)
    released = me.input_dir == 0j and not me.input_kick and not me.is_human
    m.act(me.uid, Act(-1j, False, "open"))
    driven = me.input_dir == -1j and me.intent == "open"
    try:
        m.act(m.team_lists[1][0].uid, Act())
        refused = False
    except ValueError:
        refused = True
    return check("seats", held and released and driven and refused,
                 "buttons held %s, released %s, act() drives an empty seat %s, refused on a brain %s" % (held, released, driven, refused))


def alone():
    bad = []
    folder = os.path.join(ROOT, "soccer", "core")
    for f in sorted(os.listdir(folder)):
        if not f.endswith(".py"):
            continue
        for node in ast.walk(ast.parse(open(os.path.join(folder, f)).read())):
            if isinstance(node, ast.ImportFrom) and (node.level > 1 or (node.level == 0 and (node.module or "").startswith("soccer"))):
                bad.append("%s imports %s" % (f, "." * node.level + (node.module or "")))
            if isinstance(node, ast.Import) and any(a.name.startswith("soccer") or a.name == "numpy" for a in node.names):
                bad.append("%s imports %s" % (f, ", ".join(a.name for a in node.names)))
    return check("alone", not bad, "; ".join(bad) or "soccer/core imports only itself and the standard library")


def main():
    ok = plays() & cadence() & batch() & seats() & alone()
    print("TOTAL ->", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
