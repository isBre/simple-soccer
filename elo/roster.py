"""Who is rated. Three kinds of entry, each with an id that never changes while its files stay the same:

  player:<id>   a player of data/players, as a team of five copies of itself (so every player has its own rating, also those
                that only appear in mixed teams). A team whose line-up is one player five times IS that entry (an alias)
  team:<id>     a team with at least two different players (curated, mixed or built in the game): its rating is the average of
                the players on the pitch plus a small team bonus (elo/model.py)
  net:<stem>    a training checkpoint (models/*.json that is no player's net, and the best checkpoint of every finished run of
                out_5v5/ckpt/): a net, 5v5 only, for the Lab's experiments

Every entry knows the sizes it can play, who takes the pitch at each size (`compose`, weights that sum to 1 over the units) and
the version of the files its results depend on (`sha`): when a player's file, its style or its net changes, the results of
every entry it takes part in stop counting. A *unit* is an entry that has a strength of its own (a player or a checkpoint)."""
import glob
import hashlib
import json
import os
import threading
from collections import Counter

from soccer import data as sd
from soccer.players import PlayerDef
from soccer.teams import Team

from . import ROOT, SIZES

_lock = threading.Lock()
_cache = {"sig": None, "roster": None}


def _sha(*paths):
    h = hashlib.sha1()
    for p in paths:
        try:
            with open(p, "rb") as f:
                h.update(f.read())
        except OSError:
            h.update(b"?")
    return h.hexdigest()[:10]


def _label(stem):
    """x_kickstart_persist_best -> 'run kickstart_persist (best)'; t48_u100 -> 't48_u100'."""
    return "run %s (best)" % stem[2:-5] if stem.startswith("x_") and stem.endswith("_best") else stem


def _finished(run):
    try:
        st = json.load(open(os.path.join(ROOT, "exp", "runs", run, "status.json")))
    except (OSError, ValueError):
        return False
    return st.get("state") not in ("running", "queued", None)


class Entry:
    """One rated thing. `units` are the entries (itself for a unit) whose strengths make its rating; `bonus` is True for a team
    that has a bonus parameter of its own."""

    def __init__(self, eid, kind, name, league, team, sha, sub, model=None):
        self.id, self.kind, self.name, self.league, self.team, self.sha = eid, kind, name, league, team, sha
        self.sub = sub                      # "rules" | "net" | "mixed" (what drives it)
        self.model = model                  # a net's model path from the project root
        self.unit = kind != "team"
        self.bonus = kind == "team"
        self.players = []                   # PlayerDef of the line-up (a unit: itself five times)
        self.aliases = []                   # ids of uniform teams that are this entry

    def sizes(self):
        return [n for n in SIZES if self.team.can_play(n)]

    def compose(self, size):
        """{unit id: weight} of who takes the pitch at this size (the weights sum to 1), {} if it cannot play this size."""
        if not self.team.can_play(size):
            return {}
        if self.unit:
            return {self.id: 1.0}
        c = Counter("player:" + p.id for p, _, _, _ in self.team.lineup(size))
        return {u: k / size for u, k in c.items()}

    def spec(self):
        """What a worker process needs to field this entry (a plain dict): the line-up as player descriptors."""
        def desc(p):
            return {"id": p.id, "model": p.model} if p.kind == "net" and p.id.startswith("ckpt:") else {"id": p.id}
        return {"id": self.id, "name": self.name, "sha": self.sha, "lineup": [desc(p) for p in self.players]}


class Roster:
    def __init__(self, entries, aliases):
        self.entries = entries              # {id: Entry}
        self.alias = aliases                # {team id: entry id} uniform teams
        self.by_model = {}
        for e in entries.values():
            if e.model:
                self.by_model[os.path.splitext(os.path.basename(e.model))[0]] = e.id

    def at(self, size):
        """The entries that can play this size."""
        return {i: e for i, e in self.entries.items() if size in e.sizes()}


def _signature():
    sig = []
    for pat in ("data/players/*.json", "data/teams/*.json", "data/styles/*.json", "models/*.json", "data/models/*.json",
                "out_5v5/ckpt/x_*_best.json", "exp/runs/*/status.json"):
        for f in sorted(glob.glob(os.path.join(ROOT, pat))):
            st = os.stat(f)
            sig.append((f, st.st_mtime_ns, st.st_size))
    for f in sorted(glob.glob(os.path.join(sd.my_teams_dir(), "*.json"))):
        st = os.stat(f)
        sig.append((f, st.st_mtime_ns, st.st_size))
    return tuple(sig)


def get(force=False):
    """The roster, rebuilt when a file it depends on changed (a cheap stat sweep decides: hashing every net takes a while)."""
    with _lock:
        sig = _signature()
        if force or _cache["sig"] != sig:
            if _cache["sig"] is not None:
                sd.reload()                 # the game data changed on disk: read it again
            _cache["roster"], _cache["sig"] = _build(), sig
        return _cache["roster"]


def _solo_team(eid, name, players):
    t = Team({"id": eid, "name": name, "lineup": [p.id for p in players]})
    t.players = list(players)
    return t


def _build():
    db = sd.database()
    entries, aliases, units_sha = {}, {}, {}
    owned = set()
    for p in sorted(db.players.values(), key=lambda p: p.id):
        if p.hidden:
            continue
        eid = "player:" + p.id
        files = [os.path.join(ROOT, "data", "players", p.id + ".json")]
        files += [p.model_path] if p.kind == "net" else [os.path.join(ROOT, "data", "styles", p.style_id + ".json")]
        if p.kind == "net":
            owned.add(os.path.normpath(p.model))
        e = Entry(eid, "player", p.name, "rl" if p.kind == "net" else "rules", None, _sha(*files), p.kind, p.model or None)
        e.players = [p] * 5
        e.team = _solo_team(eid, p.name, e.players)
        entries[eid] = e
        units_sha[eid] = e.sha
    # training checkpoints: nets that are no player's net
    nets = sorted(glob.glob(os.path.join(ROOT, "models", "*.json")))
    nets += [f for f in sorted(glob.glob(os.path.join(ROOT, "out_5v5", "ckpt", "x_*_best.json"))) if _finished(os.path.basename(f)[2:-10])]
    seen = set()
    for f in nets:
        stem = os.path.basename(f)[:-5]
        rel = os.path.relpath(f, ROOT)
        if stem in seen or os.path.normpath(rel) in owned:
            continue
        try:
            with open(f) as fh:
                if "sizes" not in json.load(fh):
                    continue
        except (OSError, ValueError):
            continue
        seen.add(stem)
        eid = "net:" + stem
        pd = PlayerDef({"id": "ckpt:" + stem, "name": _label(stem), "kind": "net", "model": rel}, ROOT)
        e = Entry(eid, "net", _label(stem), "rl", None, _sha(f), "net", rel)
        e.players = [pd] * 5
        e.team = _solo_team(eid, e.name, e.players)
        entries[eid] = e
        units_sha[eid] = e.sha
    for t in sorted(db.teams.values(), key=lambda t: t.id):
        ids = [p.id for p in t.players]
        if not all("player:" + i in entries for i in ids):
            continue                                                    # a player that is not rated (hidden): the team is not either
        if len(set(ids)) == 1:                                          # five copies of one player: that player's entry
            solo = entries["player:" + ids[0]]
            solo.aliases.append(t.id)
            aliases[t.id] = solo.id
            continue
        eid = "team:" + t.id
        kinds = {p.kind for p in t.players}
        e = Entry(eid, "team", t.name, t.league, t, _sha_of(units_sha["player:" + i] for i in ids), "mixed" if len(kinds) > 1 else kinds.pop())
        e.players = list(t.players)
        entries[eid] = e
    return Roster(entries, aliases)


def _sha_of(parts):
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:10]
