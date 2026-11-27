"""The game's HTTP API (served by web/app.py under /api/game/):
  GET  /api/game/catalog          leagues, players, teams (logos, kits, line-ups, ratings), pitches, builder options
  POST /api/game/tournament       {"action": ..., "t": tournament?, ...} -> {"t": tournament, "view": {...}} (game/tournament.py)
       new       {"league" ("all" = every league, mixed), "user", "count", "format", "pitch", "size", "duration"}: a new tournament (random opponents and seed)
       view      the derived view of a stored tournament
       simulate  plays every unplayed match of the current round (all cores), then records them
       fixture   -> {"setup", "index"}: the player's next match, to play live (/ws/match)
       record    {"index", "result"}: stores the result of the player's live match
  GET  /api/game/rankings?size=N  the Rankings page of one size (elo/: this machine's ratings): players and teams
  POST /api/game/team             {"action": "save", "team": {...}} -> {"team": team_info} | {"action": "delete", "id"}: the teams built in
                                  the game (local/my_teams, this machine only; the teams of data/teams can only be copied)
The browser keeps the tournament (localStorage); the server keeps nothing but the built teams."""
import random

from game import api, tournament as tn


class BadRequest(Exception):
    pass


def _pow2(n):
    return n >= 4 and n & (n - 1) == 0


def new_tournament(b):
    size = int(b.get("size", 3))
    teams = [t for t in api.team_list() if (b.get("league") == api.ALL_LEAGUES or t.league == b.get("league"))   # "all": every league
             and t.can_play(size)]                       # teams of 5v5-only nets sit out the smaller sizes
    ids = [t.id for t in teams]
    user = b.get("user")
    if user not in ids or len(ids) < 2:
        raise BadRequest("pick a team of the league that can play %dv%d" % (size, size))
    count = max(2, min(len(ids), int(b.get("count", len(ids)))))
    fmt = int(b.get("format", tn.LEAGUE))
    if fmt not in (tn.LEAGUE, tn.KNOCKOUT, tn.GROUPS) or (fmt != tn.LEAGUE and not _pow2(count)):
        fmt = tn.LEAGUE                                  # knockout and groups need 4, 8 or 16 teams
    others = [i for i in ids if i != user]
    random.shuffle(others)                               # random opponents when fewer than all teams play
    t = tn.create(fmt, [user] + others[:count - 1], user, str(b.get("pitch", "arena")), size,
                  float(b.get("duration", 180.0)), random.randrange(100000))
    t["title"] = "%s - %s" % (api.league_name(b["league"]), t["title"])
    return t


def tournament(b):
    action = b.get("action")
    if action == "new":
        t = new_tournament(b)
        return {"t": t, "view": tn.view(t)}
    t = b.get("t")
    if not isinstance(t, dict) or not t.get("rounds"):
        raise BadRequest("no tournament")
    if action == "simulate":
        idx = tn.pending_fixtures(t)
        results = api.simulate([tn.setup_for(t, i) for i in idx])
        for i, res in zip(idx, results):                 # the last one completes the round, which then advances
            tn.record(t, i, res)
    elif action == "fixture":
        i = tn.user_fixture(t)
        if i is None:
            raise BadRequest("no match to play")
        setup = tn.setup_for(t, i)
        f = tn.current_round(t)["fixtures"][i]
        setup["human_team"] = 0 if f["home"] == t["user_team"] else 1
        return {"setup": setup, "index": i}
    elif action == "record":
        i, res = b.get("index"), b.get("result")
        if i is None or not isinstance(res, dict) or tn.current_round(t)["fixtures"][int(i)]["played"]:
            raise BadRequest("nothing to record")
        tn.record(t, int(i), res)
    elif action != "view":
        raise BadRequest("unknown action %r" % action)
    return {"t": t, "view": tn.view(t)}


def handle(method, path, body, query=None):
    """(status, JSON-able answer) for /api/game/<...>."""
    try:
        if method == "GET" and path == "/api/game/catalog":
            return 200, api.catalog()
        if method == "GET" and path.startswith("/api/game/rankings"):
            size = int((query or {}).get("size", 5))
            if size not in (1, 2, 3, 4, 5):
                raise BadRequest("size must be 1 to 5")
            return 200, api.rankings(size)
        if method == "POST" and path == "/api/game/tournament":
            return 200, tournament(body or {})
        if method == "POST" and path == "/api/game/team":
            b = body or {}
            if b.get("action") == "save":
                return 200, {"team": api.save_team(b.get("team") or {})}
            if b.get("action") == "delete":
                api.delete_team(b.get("id"))
                return 200, {"deleted": b.get("id")}
            raise BadRequest("unknown action %r" % b.get("action"))
        return 404, {"error": "unknown: %s %s" % (method, path)}
    except (BadRequest, api.Invalid) as e:
        return 400, {"error": str(e)}
    except (KeyError, IndexError, TypeError, ValueError) as e:
        return 400, {"error": "%s: %s" % (type(e).__name__, e)}
