class_name TeamDef
extends RefCounted
## A team: identity, colors, logo, kit, tactical style and roster.

var id := ""
var name := ""
var short := ""
var color_primary := Color("e56e56")
var color_secondary := Color.WHITE
var kit_pattern := "solid"       # solid / stripes / halves / hoops / band
var logo: Dictionary = {}
var style_id := "balanced"
var style: StyleDef = null       # resolved by Database
var formations: Dictionary = {}  # "5" -> formation name (optional)
var ml_model := ""               # optional res:// path of an MLP json: the whole team (keeper included) is driven by it
var players: Array[PlayerDef] = []


static func from_dict(d: Dictionary) -> TeamDef:
    var t := TeamDef.new()
    t.id = str(d.get("id", ""))
    t.name = str(d.get("name", t.id))
    t.short = str(d.get("short", t.name.substr(0, 3).to_upper()))
    var c: Dictionary = d.get("colors", {})
    t.color_primary = Color.html(str(c.get("primary", "e56e56")))
    t.color_secondary = Color.html(str(c.get("secondary", "ffffff")))
    t.kit_pattern = str(d.get("kit", "solid"))
    t.logo = d.get("logo", {})
    t.style_id = str(d.get("style", "balanced"))
    t.formations = d.get("formations", {})
    t.ml_model = str(d.get("ml_model", ""))
    for pd in d.get("players", []):
        t.players.append(PlayerDef.from_dict(pd))
    return t


func to_dict() -> Dictionary:
    var pl: Array = []
    for p in players:
        pl.append(p.to_dict())
    return {"id": id, "name": name, "short": short,
        "colors": {"primary": color_primary.to_html(false), "secondary": color_secondary.to_html(false)},
        "kit": kit_pattern, "logo": logo, "style": style_id, "formations": formations, "ml_model": ml_model, "players": pl}


## What the UI shows as the team's "style": a net-driven team has no rule-based style.
func style_label() -> String:
    return "Neural net (RL)" if ml_model != "" else style.name


func style_description() -> String:
    if ml_model != "":
        return "All players, goalkeeper included, are controlled by a neural net trained with reinforcement learning. It chooses its own formation and roles (5v5; other sizes fall back to the rule-based style)."
    return style.description


func formation_for(size: int) -> String:
    var f: String = str(formations.get(str(size), ""))
    if f != "" and Formations.size_of(f) == size:
        return f
    return Formations.default_for(size)


## Returns [{def: PlayerDef, role: String, fx: float, fy: float}] for the given team size.
func lineup(size: int, formation: String = "") -> Array:
    var fname := formation
    if fname == "" or Formations.size_of(fname) != size:
        fname = formation_for(size)
    var pool: Array[PlayerDef] = players.duplicate()
    pool.sort_custom(func(a: PlayerDef, b: PlayerDef) -> bool: return a.overall() > b.overall())
    var out: Array = []
    for s in Formations.slots(fname):
        var role: String = s[0]
        var pick: PlayerDef = null
        for p in pool:
            if p.pos == role:
                pick = p
                break
        if pick == null:
            # fall back to the best remaining non-keeper (or anyone)
            for p in pool:
                if p.pos != "GK" or role == "GK":
                    pick = p
                    break
        if pick == null and not pool.is_empty():
            pick = pool[0]
        if pick != null:
            pool.erase(pick)
            out.append({"def": pick, "role": role, "fx": float(s[1]), "fy": float(s[2])})
    return out


## 0..5 stars in half steps from the team rating (50 -> 0 stars, 89+ -> 5 stars).
func stars() -> float:
    return roundf(clampf((strength() - 50.0) / 39.0, 0.0, 1.0) * 10.0) / 2.0


func strength() -> float:
    if players.is_empty():
        return 0.0
    var best: Array = []
    for p in players:
        best.append(p.overall())
    best.sort()
    best.reverse()
    var n := mini(5, best.size())
    var s := 0.0
    for i in n:
        s += best[i]
    return s / n
