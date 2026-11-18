class_name MatchClient
extends RefCounted
## A match played by the Python match core (soccer/: physics, rules, stats, grades, AI) through soccer/server.py.
## Godot only draws it and sends the keyboard: this object mirrors what the screens need (positions, score, clock, goal
## and kickoff state, events) and has the calls they make (step, set_human_input, switch_controlled, make_result).
## The server is started on demand (interpreter: $SOCCER_PYTHON, else the first python3 that has numpy; port
## $SOCCER_PORT, default 7330; log in user://match_server.log).

enum State { PLAYING, GOAL, ENDED }

const PROTOCOL := 2
const DEFAULT_PORT := 7330
## Discrete moves of the RL nets, in the player's own frame (+x towards the opponent goal); also used by scripted inputs.
const DIRS: Array[Vector2] = [
    Vector2(0, 0), Vector2(0, -1), Vector2(1, -1), Vector2(1, 0), Vector2(1, 1),
    Vector2(0, 1), Vector2(-1, 1), Vector2(-1, 0), Vector2(-1, -1),
]

static var _mutex := Mutex.new()
static var _start_tick := -1000000
static var last_error := ""            # why the last connection failed, for the UI

var cfg: MatchConfig
var pitch: PitchDef
var ok := false
var error := ""
var kinds: Array = []                  # per team: {kind: "rules" | "net", n_in}
var warnings: Array = []
var ball := Disc.new()
var statics: Array[Disc] = []
var players: Array[SimPlayer] = []     # team 0 then team 1, slot order
var team_lists: Array = [[], []]
var by_uid: Dictionary = {}
var styles: Array[StyleDef] = []
var events: Array = []

var tick := 0
var state := State.PLAYING
var scores: Array[int] = [0, 0]
var time_left := 0.0
var overtime := false
var ot_left := 0.0
var kickoff_active := true
var kickoff_team := 0
var kickoff_start := 0
var kickoff_taker: SimPlayer = null
var goal_scorer: SimPlayer = null
var goal_team := -1
var goal_pause := 210
var goal_timer := 0
var goal_center := Vector2.ZERO
var winner := -1
var shootout: Array = []
var controlled: SimPlayer = null

var _peer: StreamPeerTCP = null
var _human_dir := Vector2.ZERO
var _human_kick := false
var _switch := false
var _in := StreamPeerBuffer.new()
var _out := StreamPeerBuffer.new()


## Opens a live match. puzzle_seed >= 0: every player and the ball start at random places (the Live page's puzzle).
func _init(config: MatchConfig, puzzle_seed: int = -1) -> void:
    cfg = config
    pitch = config.pitch
    time_left = config.duration
    for t in 2:
        styles.append(config.get_style(t))
    var spec := spec_of(config)
    if puzzle_seed >= 0:
        spec["puzzle_seed"] = puzzle_seed
    _peer = _connect()
    if _peer == null:
        error = "no match server on port %d (see %s)" % [port(), ProjectSettings.globalize_path("user://match_server.log")]
    else:
        var reply = _request({"protocol": PROTOCOL, "mode": "live", "spec": spec})
        if reply is Dictionary and bool(reply.get("ok", false)):
            _setup(reply)
            ok = true
            _exchange(0)
        else:
            error = str(reply.get("error", "no answer from the match server")) if reply is Dictionary else "no answer from the match server"
    if not ok:
        last_error = error
        push_error("MatchClient: " + error)


## Plays a whole match on the server and returns its result (blocking; tournaments run several on threads).
static func run(config: MatchConfig) -> Dictionary:
    var peer := _connect()
    if peer == null:
        last_error = "no match server on port %d" % port()
        push_error("MatchClient: " + last_error)
        return {}
    var body := JSON.stringify({"protocol": PROTOCOL, "mode": "run", "spec": spec_of(config)}).to_utf8_buffer()
    peer.put_u32(body.size())
    peer.put_data(body)
    var reply = JSON.parse_string(_read_frame(peer).get_string_from_utf8())
    if reply is Dictionary and bool(reply.get("ok", false)):
        return _ints(reply["result"])
    last_error = str(reply.get("error", "no answer")) if reply is Dictionary else "no answer from the match server"
    push_error("MatchClient: " + last_error)
    return {}


## What the match core needs to set up this match (soccer/server.py config_from_spec).
static func spec_of(c: MatchConfig) -> Dictionary:
    return {"pitch": c.pitch.raw, "teams": [c.teams[0].to_dict(), c.teams[1].to_dict()],
        "styles": [c.get_style(0).to_dict(), c.get_style(1).to_dict()], "team_size": c.team_size, "duration": c.duration,
        "score_limit": c.score_limit, "allow_draw": c.allow_draw, "overtime": c.overtime, "match_seed": c.match_seed,
        "control": int(c.control), "human_team": c.human_team, "auto_switch": c.auto_switch, "formations": c.formations,
        "nets": c.nets, "net_temperature": c.net_temperature}


func _setup(reply: Dictionary) -> void:
    kinds = reply.get("kinds", [])
    warnings = reply.get("warnings", [])
    for w in warnings:
        push_warning("MatchClient: " + str(w))
    ball.radius = float(reply.get("ball_radius", 10.0))
    for s: Array in reply.get("statics", []):
        var d := Disc.new()
        d.pos = Vector2(s[0], s[1])
        d.radius = float(s[2])
        d.kind = Disc.KIND_STATIC
        statics.append(d)
    for pd: Dictionary in reply["players"]:
        var p := SimPlayer.new()
        p.team = int(pd["team"])
        p.slot = int(pd["slot"])
        p.uid = int(pd["uid"])
        p.role = str(pd["role"])
        p.radius = float(pd["radius"])
        for d: PlayerDef in cfg.teams[p.team].players:
            if d.id == str(pd["id"]):
                p.def = d
                break
        players.append(p)
        team_lists[p.team].append(p)
        by_uid[p.uid] = p


func set_human_input(dir: Vector2, kick: bool) -> void:
    _human_dir = dir
    _human_kick = kick


## TEAM control mode: hand control to the teammate nearest to the ball (applied at the next step).
func switch_controlled() -> void:
    _switch = true


func step(n: int = 1) -> void:
    if ok and state != State.ENDED:
        _exchange(n)


func run_to_end() -> void:
    while ok and state != State.ENDED:
        _exchange(600)


func elapsed() -> float:
    var t := cfg.duration - time_left
    if overtime:
        t += cfg.overtime - ot_left
    return t


func make_result() -> Dictionary:
    if not ok:
        return {}
    _peer.put_u32(1)
    _peer.put_u8(82)                   # 'R'
    var r = JSON.parse_string(_read_frame(_peer).get_string_from_utf8())
    return _ints(r) if r is Dictionary else {}


func _exchange(n: int) -> void:
    var o := _out
    o.clear()
    o.put_u32(13)                      # frame length: the 13 bytes below
    o.put_u8(83)                       # 'S'
    o.put_u16(n)
    o.put_float(_human_dir.x)
    o.put_float(_human_dir.y)
    o.put_u8(1 if _human_kick else 0)
    o.put_u8(1 if _switch else 0)
    _peer.put_data(o.data_array)       # one write per request
    _switch = false
    var data := _read_frame(_peer)
    if data.is_empty():
        ok = false
        error = "the match server closed the connection (see %s)" % ProjectSettings.globalize_path("user://match_server.log")
        last_error = error
        push_error("MatchClient: " + error)
        return
    var b := _in
    b.data_array = data
    tick = b.get_32()
    state = b.get_u8() as State
    scores[0] = b.get_u8()
    scores[1] = b.get_u8()
    time_left = b.get_float()
    overtime = b.get_u8() != 0
    ot_left = b.get_float()
    kickoff_active = b.get_u8() != 0
    kickoff_team = b.get_u8()
    kickoff_start = b.get_32()
    kickoff_taker = by_uid.get(b.get_8())
    goal_scorer = by_uid.get(b.get_8())
    goal_team = b.get_8()
    goal_pause = b.get_32()
    goal_timer = b.get_32()
    goal_center = Vector2(b.get_float(), b.get_float())
    winner = b.get_8()
    var s0 := b.get_8()
    var s1 := b.get_8()
    shootout = [s0, s1] if s0 >= 0 else []
    var cu := b.get_8()
    ball.pos = Vector2(b.get_float(), b.get_float())
    ball.vel = Vector2(b.get_float(), b.get_float())
    for p in players:
        p.pos = Vector2(b.get_float(), b.get_float())
        p.vel = Vector2(b.get_float(), b.get_float())
        var f := b.get_u8()
        p.is_human = (f & 1) != 0
        p.input_kick = (f & 2) != 0
        p.kick_used = (f & 4) != 0
    controlled = by_uid.get(cu)
    var n_ev := b.get_u32()
    if n_ev > 0:
        var ev = JSON.parse_string(b.get_utf8_string(n_ev))
        if ev is Array:
            events.append_array(_ints(ev))


## Godot's JSON parser reads every number as a float; the screens expect whole numbers (scores, uids, counters) as ints.
static func _ints(v: Variant) -> Variant:
    if v is float and v == floorf(v) and absf(v) < 1.0e15:
        return int(v)
    if v is Array:
        var a := []
        for x in v:
            a.append(_ints(x))
        return a
    if v is Dictionary:
        var d := {}
        for k in v:
            d[k] = _ints(v[k])
        return d
    return v


func _request(d: Dictionary) -> Variant:
    var body := JSON.stringify(d).to_utf8_buffer()
    _peer.put_u32(body.size())
    _peer.put_data(body)
    return JSON.parse_string(_read_frame(_peer).get_string_from_utf8())


static func _read_frame(peer: StreamPeerTCP) -> PackedByteArray:
    var n := peer.get_u32()
    if n == 0 or peer.get_status() != StreamPeerTCP.STATUS_CONNECTED:
        return PackedByteArray()
    var r: Array = peer.get_data(n)
    return r[1] if r[0] == OK else PackedByteArray()


# ------------------------------------------------------------------ the server process

static func port() -> int:
    var e := OS.get_environment("SOCCER_PORT")
    return int(e) if e.is_valid_int() else DEFAULT_PORT


static func _try_connect() -> StreamPeerTCP:
    var p := StreamPeerTCP.new()
    if p.connect_to_host("127.0.0.1", port()) != OK:
        return null
    var t0 := Time.get_ticks_msec()
    while Time.get_ticks_msec() - t0 < 2000:
        p.poll()
        match p.get_status():
            StreamPeerTCP.STATUS_CONNECTED:
                p.set_no_delay(true)
                return p
            StreamPeerTCP.STATUS_ERROR, StreamPeerTCP.STATUS_NONE:
                return null
        OS.delay_msec(2)
    return null


static func _connect() -> StreamPeerTCP:
    var p := _try_connect()
    if p != null:
        return p
    _mutex.lock()
    if Time.get_ticks_msec() - _start_tick > 15000:      # one start attempt at a time (matches are set up on several threads)
        _start_tick = Time.get_ticks_msec()
        _start_server()
    _mutex.unlock()
    var t0 := Time.get_ticks_msec()
    while Time.get_ticks_msec() - t0 < 15000:
        p = _try_connect()
        if p != null:
            return p
        OS.delay_msec(100)
    return null


## The interpreter for the server: $SOCCER_PYTHON, else the first candidate that can import numpy.
static func _python() -> String:
    var env := OS.get_environment("SOCCER_PYTHON")
    if env != "":
        return env
    var home := OS.get_environment("HOME")
    var cands: Array = [home + "/rl-venv/bin/python", "python3", "/usr/local/bin/python3",
        "/Library/Frameworks/Python.framework/Versions/Current/bin/python3", "/opt/homebrew/bin/python3", "/usr/bin/python3", "python"]
    for c: String in cands:
        if c.begins_with("/") and not FileAccess.file_exists(c):
            continue
        if OS.execute(c, ["-c", "import numpy"]) == 0:
            return c
    return "python3"


static func _start_server() -> void:
    var py := _python()
    var script := ProjectSettings.globalize_path("res://soccer/server.py")
    var log_file := ProjectSettings.globalize_path("user://match_server.log")
    var pid := OS.create_process(py, [script, "--port", str(port()), "--idle-exit", "600", "--log", log_file])
    print("MatchClient: started the match server (%s, pid %d)" % [py, pid])
