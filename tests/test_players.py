"""The rule-based archetypes (soccer/ai/players/) play as they say: 10 short 5v5 matches between the Rule Based League teams
(fixed seeds), then one check per archetype on what defines it, and a sanity check of the matches themselves.

  matches      every match ends, goals per match in a football range, every archetype took part
  sweeper      the deepest player of its team most of the time, calling cover
  shadow       stays in our half
  winger       the widest player on average
  poacher      high up the pitch: higher than the box-to-box players
  target man   the highest on average
  playmaker    passes and hardly shoots
  dribbler     hardly passes: fewer passes than the playmakers
  ball winner  wins the ball more often than the shadows and calls "ball" a lot
  presser      near the ball more often than the box-to-box players
  box-to-box   calls both "open" and "run"

  python3 tests/test_players.py"""
import collections
import random
import sys

from soccer.data import database
from soccer.core.public import ENDED, PLAYING
from soccer.game import make_config, new_match

N, SECONDS = 10, 60.0


def measure():
    db = database()
    teams = sorted(t.id for t in db.teams.values() if t.league == "rules")
    rng = random.Random(12)
    acc = collections.defaultdict(collections.Counter)
    goals, ended = [], 0
    for _ in range(N):
        a, b = rng.sample(teams, 2)
        m = new_match(make_config(a, b, "arena", 5, SECONDS, rng.randrange(1, 1 << 30)))
        hw, hh = m.pitch.half_w, m.pitch.half_h
        while m.state != ENDED and m.tick < SECONDS * 60 * 4:
            m.step()
            if m.tick % 10 or m.state != PLAYING or m.kickoff_active:
                continue
            for t in (0, 1):
                ax = 1.0 if t == 0 else -1.0
                deep = min(m.team_lists[t], key=lambda p: p.pos.real * ax)
                for p in m.team_lists[t]:
                    c = acc[p.label.algorithm]
                    c["n"] += 1
                    c["x"] += p.pos.real * ax / hw
                    c["y"] += abs(p.pos.imag) / hh
                    c["deep"] += p is deep
                    c["near"] += abs(p.pos - m.ball.pos) < 60.0
                    c["i_" + p.intent] += 1
        ended += m.state == ENDED
        r = m.make_result()
        goals.append(sum(r["scores"]))
        for pl in r["players"]:
            c = acc[db.players[pl["id"]].algorithm]
            c["games"] += 1
            for k in ("shots", "passes_ok", "tackles", "interceptions", "goals"):
                c[k] += pl[k]
    out = {}
    for k, c in acc.items():
        n, g = max(c["n"], 1), max(c["games"], 1)
        out[k] = {"x": c["x"] / n, "y": c["y"] / n, "deep": c["deep"] / n, "near": c["near"] / n,
                  **{i: c["i_" + i] / n for i in ("ball", "open", "run", "cover", "none")},
                  "shots": c["shots"] / g, "passes": c["passes_ok"] / g, "wins": (c["tackles"] + c["interceptions"]) / g}
    return out, goals, ended


def main():
    a, goals, ended = measure()
    others = lambda key, me: [v[key] for k, v in a.items() if k != me]      # noqa: E731
    checks = [
        ("matches", ended == N and 0.4 <= sum(goals) / N * 90.0 / SECONDS <= 6.0 and len(a) == 10,
         "%d of %d ended, %.1f goals per 90 s, %d archetypes" % (ended, N, sum(goals) / N * 90.0 / SECONDS, len(a))),
        ("sweeper", a["sweeper"]["deep"] > 0.6 and a["sweeper"]["cover"] > 0.6, "deepest %.0f%%, calls cover %.0f%%" % (100 * a["sweeper"]["deep"], 100 * a["sweeper"]["cover"])),
        ("shadow", a["shadow"]["x"] < -0.2, "average depth %.2f" % a["shadow"]["x"]),
        ("winger", a["winger"]["y"] > max(others("y", "winger")), "width %.2f (next %.2f)" % (a["winger"]["y"], max(others("y", "winger")))),
        ("poacher", a["poacher"]["x"] > a["box_to_box"]["x"] + 0.2, "depth %.2f vs box-to-box %.2f" % (a["poacher"]["x"], a["box_to_box"]["x"])),
        ("target man", a["target_man"]["x"] >= max(others("x", "target_man")) - 0.05, "depth %.2f (next %.2f)" % (a["target_man"]["x"], max(others("x", "target_man")))),
        ("playmaker", a["playmaker"]["passes"] > 0.5 and a["playmaker"]["shots"] < 0.5, "%.1f passes, %.1f shots per match" % (a["playmaker"]["passes"], a["playmaker"]["shots"])),
        ("dribbler", a["dribbler"]["passes"] < a["playmaker"]["passes"], "%.1f passes vs playmaker %.1f" % (a["dribbler"]["passes"], a["playmaker"]["passes"])),
        ("ball winner", a["ball_winner"]["wins"] > a["shadow"]["wins"] and a["ball_winner"]["ball"] > 0.15,
         "%.1f balls won vs shadow %.1f, calls ball %.0f%%" % (a["ball_winner"]["wins"], a["shadow"]["wins"], 100 * a["ball_winner"]["ball"])),
        ("presser", a["presser"]["near"] > a["box_to_box"]["near"], "near the ball %.0f%% vs box-to-box %.0f%%" % (100 * a["presser"]["near"], 100 * a["box_to_box"]["near"])),
        ("box-to-box", a["box_to_box"]["open"] > 0.05 and a["box_to_box"]["run"] > 0.03, "calls open %.0f%%, run %.0f%%" % (100 * a["box_to_box"]["open"], 100 * a["box_to_box"]["run"])),
    ]
    ok = True
    for name, good, detail in checks:
        print("%-12s %s    %s" % (name, "OK" if good else "FAIL", detail))
        ok &= bool(good)
    print("TOTAL -> %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
