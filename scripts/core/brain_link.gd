class_name BrainLink
extends RefCounted
## Connection from one MatchSim to the Python brain server (brain/server.py), where every AI decision is made: rule-based
## teams and neural-net teams alike. Godot only runs the physics, the match rules and the drawing.
## Wire format: brain/protocol.py. One connection per match; started automatically when no server is listening.
##
## Environment: SOCCER_PYTHON (interpreter with numpy, default: the first python3 found), SOCCER_BRAIN_PORT (default 7330).

const PROTOCOL := 1
const DEFAULT_PORT := 7330
const HIST := 20                       # ball positions sent per snapshot, newest first (must match brain/match.py)
const INTENTS := ["", "pass", "shoot", "clear", "long"]
const CMD_DECIDE := 68                 # 'D'
const CMD_OBSERVE := 79                # 'O'
const OBS_TEAM := 1
const OBS_EGO := 2

static var _mutex := Mutex.new()
static var _start_tick := -1000000     # when we last started a server (ms)
static var last_error := ""            # why the last connection failed, for the UI

var peer: StreamPeerTCP = null
var ok := false
var error := ""
var teams: Array = []                  # per team: {kind: "rules" | "net", n_in}
var _order: Array = []                 # players in setup order (team 0 then team 1, slot order, ghosts included)
var _out := StreamPeerBuffer.new()
var _in := StreamPeerBuffer.new()


static func port() -> int:
    var e := OS.get_environment("SOCCER_BRAIN_PORT")
    return int(e) if e.is_valid_int() else DEFAULT_PORT


## Connects and sends the match setup. On failure `ok` is false and `error` says why (the bots then stand still).
static func open(sim: MatchSim) -> BrainLink:
    var b := BrainLink.new()
    b.peer = _connect()
    if b.peer == null:
        b.error = "no brain server on port %d (see %s)" % [port(), ProjectSettings.globalize_path("user://brain_server.log")]
    else:
        b._setup(sim)
    if not b.ok:
        last_error = b.error
        push_error("BrainLink: " + b.error)
    return b


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
    if Time.get_ticks_msec() - _start_tick > 15000:      # one start attempt at a time (matches are built on several threads)
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


## The interpreter for the brain server: $SOCCER_PYTHON, else the first candidate that can import numpy.
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
    var script := ProjectSettings.globalize_path("res://brain/server.py")
    var log_file := ProjectSettings.globalize_path("user://brain_server.log")
    var pid := OS.create_process(py, [script, "--port", str(port()), "--idle-exit", "600", "--log", log_file])
    print("BrainLink: started the brain server (%s, pid %d)" % [py, pid])


func _setup(sim: MatchSim) -> void:
    var pd := sim.pitch
    var players: Array = []
    _order = []
    for t in 2:
        for p: SimPlayer in sim.team_lists[t]:
            _order.append(p)
            var d := p.def
            players.append({"uid": p.uid, "team": p.team, "slot": p.slot, "role": p.role, "home": [p.home.x, p.home.y],
                "spawn": [p.spawn.x, p.spawn.y], "radius": p.radius, "seed": p.ai_seed,
                "attrs": {"finishing": d.finishing, "passing": d.passing, "defending": d.defending,
                    "positioning": d.positioning, "reaction": d.reaction}})
    var setup := {"protocol": PROTOCOL, "duration": sim.cfg.duration, "ball_radius": sim.ball.radius,
        "pitch": {"half_w": pd.half_w, "half_h": pd.half_h, "goal_half": pd.goal_half, "out_x": pd.out_x, "out_y": pd.out_y,
            "center_r": pd.center_r},
        "styles": [sim.styles[0].to_dict(), sim.styles[1].to_dict()], "nets": sim.cfg.nets,
        "temperature": sim.cfg.net_temperature, "players": players}
    var body := JSON.stringify(setup).to_utf8_buffer()
    peer.put_u32(body.size())
    peer.put_data(body)
    var reply = JSON.parse_string(_read_frame().get_string_from_utf8())
    if not (reply is Dictionary):
        error = "no answer from the brain server"
        return
    if not bool(reply.get("ok", false)):
        error = str(reply.get("error", "setup refused"))
        return
    teams = reply.get("teams", [])
    for w in reply.get("warnings", []):
        push_warning("BrainLink: " + str(w))
    ok = true


func _read_frame() -> PackedByteArray:
    var n := peer.get_u32()
    if n == 0:
        return PackedByteArray()
    var r: Array = peer.get_data(n)
    return r[1] if r[0] == OK else PackedByteArray()


## Writes the command byte and the match snapshot (brain/protocol.py SNAP_HEAD + players).
func _snapshot(sim: MatchSim, cmd: int, update_brains: bool, decide: bool) -> void:
    var o := _out
    o.clear()
    o.put_u32(0)                       # frame length, filled in by _send
    o.put_u8(cmd)
    o.put_32(sim.tick)
    o.put_u8(sim.state)
    o.put_u8((1 if sim.kickoff_active else 0) | (2 if update_brains else 0))
    o.put_8(sim.kickoff_taker.uid if sim.kickoff_taker != null else -1)
    o.put_32(sim.kickoff_go)
    o.put_u8(mini(sim.scores[0], 255))
    o.put_u8(mini(sim.scores[1], 255))
    o.put_float(sim.time_left)
    o.put_8(sim.last_touch.uid if sim.last_touch != null else -1)
    o.put_8(sim.controlled.uid if sim.controlled != null else -1)
    o.put_u16(sim.reset_count & 0xffff)
    o.put_float(sim.ball.pos.x)
    o.put_float(sim.ball.pos.y)
    o.put_float(sim.ball.vel.x)
    o.put_float(sim.ball.vel.y)
    for i in HIST:
        var h := sim.ball_at(i)
        o.put_float(h.x)
        o.put_float(h.y)
    for p: SimPlayer in _order:
        o.put_float(p.pos.x)
        o.put_float(p.pos.y)
        o.put_float(p.vel.x)
        o.put_float(p.vel.y)
        var due := decide and p.bot and not p.is_human and (sim.tick + p.slot) % MatchSim.AI_PERIOD == 0
        o.put_u8((1 if p.is_human else 0) | (2 if due else 0))


func _send() -> PackedByteArray:
    _out.seek(0)
    _out.put_u32(_out.get_size() - 4)
    peer.put_data(_out.data_array)
    return _read_frame()


## One AI tick: the brains update (every AI_PERIOD ticks) and the bots that are due this tick decide.
## Sets their input_dir / input_kick / kick_intent and the keeper of each team (sim.keeper_uid).
func decide(sim: MatchSim, update_brains: bool) -> void:
    if not ok:
        return
    _snapshot(sim, CMD_DECIDE, update_brains, true)
    var data := _send()
    if data.is_empty():
        ok = false
        error = "the brain server closed the connection (see %s)" % ProjectSettings.globalize_path("user://brain_server.log")
        last_error = error
        push_error("BrainLink: " + error)
        return
    _in.data_array = data
    for p: SimPlayer in _order:
        if p.bot and not p.is_human and (sim.tick + p.slot) % MatchSim.AI_PERIOD == 0:
            p.input_dir = Vector2(_in.get_float(), _in.get_float())
            p.input_kick = _in.get_u8() != 0
            p.kick_intent = INTENTS[mini(_in.get_u8(), INTENTS.size() - 1)]
    sim.keeper_uid[0] = _in.get_8()
    sim.keeper_uid[1] = _in.get_8()


## Observations of the given players (RL training): mode OBS_TEAM (46 numbers each), OBS_EGO (54) or both (team first).
func observe(sim: MatchSim, players: Array, mode: int) -> PackedFloat32Array:
    if not ok:
        return PackedFloat32Array()
    _snapshot(sim, CMD_OBSERVE, false, false)
    _out.put_u8(mode)
    _out.put_u8(players.size())
    for p: SimPlayer in players:
        _out.put_8(p.uid)
    return _send().to_float32_array()
