extends Node
## TCP bridge for the Python trainer. One Godot process hosts several RLEnv instances and is
## stepped in lock-step. Run:  godot --headless --path . res://rl/rl_server.tscn -- --port 7000
##
## Frame (client -> server): u8 cmd, u32 len, payload.   Reply: u32 len, payload.
##   'C' configure : payload = JSON {envs, seed, ...env config}  -> JSON {envs, agents, obs_dim}
##   'S' step      : payload = int8[E*A*2] (move, kick)           -> f32 obs[E*A*D] | f32 reward[E*A] (shared team reward + individual terms)
##                                                                  | u8 done[E] | u8 outcome[E] | f32 ep_return[E] | u8 gf[E] | u8 ga[E]
##                   (a finished env is reset immediately; its obs is the first obs of the next episode)
##   'T' reward terms : (no payload) -> JSON {terms: {name: summed per-agent mean reward}, steps}; resets the sums
##   'W' set opponent net : payload = JSON MLP dict (or {} to clear)  -> JSON {ok}
##   'Q' quit

var server := TCPServer.new()
var conn: StreamPeerTCP = null
var envs: Array[RLEnv] = []
var cfg: Dictionary = {}
var opp_net: MLP = null


func _ready() -> void:
    var port := 7000
    var args := OS.get_cmdline_user_args()
    for i in args.size():
        if args[i] == "--port" and i + 1 < args.size():
            port = int(args[i + 1])
    var err := server.listen(port, "127.0.0.1")
    if err != OK:
        printerr("rl_server: cannot listen on %d (%d)" % [port, err])
        get_tree().quit(1)
        return
    print("rl_server: listening on ", port)
    while conn == null:
        if server.is_connection_available():
            conn = server.take_connection()
            conn.set_no_delay(true)
        else:
            OS.delay_msec(5)
    _loop()
    get_tree().quit()


func _read(n: int) -> PackedByteArray:
    if n == 0:
        return PackedByteArray()
    var r := conn.get_data(n)
    if r[0] != OK:
        return PackedByteArray()
    return r[1]


func _send(payload: PackedByteArray) -> void:
    conn.put_u32(payload.size())
    conn.put_data(payload)


func _loop() -> void:
    while true:
        conn.poll()
        if conn.get_status() != StreamPeerTCP.STATUS_CONNECTED:
            return
        if conn.get_available_bytes() < 5:
            OS.delay_usec(200)
            continue
        var cmd := conn.get_u8()
        var n := conn.get_u32()
        var payload := _read(n)
        match cmd:
            67: _configure(payload)          # 'C'
            83: _step(payload)               # 'S'
            87: _set_opp(payload)            # 'W'
            84: _terms()                     # 'T'
            81: return                       # 'Q'


func _configure(payload: PackedByteArray) -> void:
    cfg = JSON.parse_string(payload.get_string_from_utf8())
    var n_envs := int(cfg.get("envs", 8))
    var seed0 := int(cfg.get("seed", 1))
    envs.clear()
    for i in n_envs:
        var e := RLEnv.new()
        var c := cfg.duplicate()
        c["seed"] = seed0 * 1000003 + i * 7919
        e.configure(c)
        e.opp_net = opp_net
        e.reset()
        envs.append(e)
    var info := {"envs": n_envs, "agents": envs[0].n_agents(), "obs_dim": envs[0].obs_dim()}
    _send(JSON.stringify(info).to_utf8_buffer())


func _terms() -> void:
    var sums := {}
    var steps := 0
    for e in envs:
        for k in e.term_sums:
            sums[k] = float(sums.get(k, 0.0)) + float(e.term_sums[k])
        steps += e.term_steps
        e.term_sums = {}
        e.term_steps = 0
    _send(JSON.stringify({"terms": sums, "steps": steps}).to_utf8_buffer())


func _set_opp(payload: PackedByteArray) -> void:
    var d = JSON.parse_string(payload.get_string_from_utf8())
    opp_net = MLP.from_dict(d) if (d is Dictionary and d.has("W")) else null
    for e in envs:
        e.opp_net = opp_net            # takes effect from the next episode
    _send(JSON.stringify({"ok": true}).to_utf8_buffer())


func _step(payload: PackedByteArray) -> void:
    var n_envs := envs.size()
    var a := envs[0].n_agents()
    var per := a * 2
    var obs := PackedFloat32Array()
    var rew := PackedFloat32Array()
    var done := PackedByteArray()
    var outc := PackedByteArray()
    var epr := PackedFloat32Array()
    var gf := PackedByteArray()
    var ga := PackedByteArray()
    for i in n_envs:
        var e := envs[i]
        var res := e.step(payload.slice(i * per, (i + 1) * per))
        var indiv: PackedFloat32Array = res[3]
        for k in indiv.size():
            rew.append(float(res[0]) + indiv[k])
        done.append(1 if res[1] else 0)
        outc.append(int(res[2]))
        epr.append(e.ep_return)
        gf.append(mini(e.sim.scores[0], 255))
        ga.append(mini(e.sim.scores[1], 255))
        if res[1]:
            e.reset()
        obs.append_array(e.observe())
    var out := PackedByteArray()
    out.append_array(obs.to_byte_array())
    out.append_array(rew.to_byte_array())
    out.append_array(done)
    out.append_array(outc)
    out.append_array(epr.to_byte_array())
    out.append_array(gf)
    out.append_array(ga)
    _send(out)
