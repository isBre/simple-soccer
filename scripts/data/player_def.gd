class_name PlayerDef
extends RefCounted
## Static description of a player. Attributes (0-100) only influence AI
## decisions (reaction, aim error, positioning) - never the physics.

var id := ""
var name := ""
var number := 1
var pos := "MID"        # GK / DEF / MID / FWD
var finishing := 60
var passing := 60
var defending := 60
var positioning := 60
var reaction := 60


static func from_dict(d: Dictionary) -> PlayerDef:
    var p := PlayerDef.new()
    p.id = str(d.get("id", ""))
    p.name = str(d.get("name", "Player"))
    p.number = int(d.get("number", 1))
    p.pos = str(d.get("pos", "MID"))
    var a: Dictionary = d.get("attrs", {})
    p.finishing = int(a.get("finishing", 60))
    p.passing = int(a.get("passing", 60))
    p.defending = int(a.get("defending", 60))
    p.positioning = int(a.get("positioning", 60))
    p.reaction = int(a.get("reaction", 60))
    return p


func to_dict() -> Dictionary:
    return {"id": id, "name": name, "number": number, "pos": pos,
        "attrs": {"finishing": finishing, "passing": passing, "defending": defending,
            "positioning": positioning, "reaction": reaction}}


func overall() -> int:
    var v := 0.0
    match pos:
        "GK":
            v = positioning * 0.35 + reaction * 0.4 + defending * 0.25
        "DEF":
            v = defending * 0.4 + positioning * 0.25 + passing * 0.2 + reaction * 0.15
        "MID":
            v = passing * 0.35 + positioning * 0.2 + defending * 0.15 + reaction * 0.15 + finishing * 0.15
        _:
            v = finishing * 0.4 + reaction * 0.2 + passing * 0.2 + positioning * 0.2
    return roundi(v)
