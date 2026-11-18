extends CanvasLayer
## Live viewer of a training run, for a touch screen without keyboard. A navigation bar switches between pages:
##   LIVE        matches of the newest checkpoint against RL Team 4 next to a compact training sidebar
##   TRAINING    the training numbers and charts          EVALUATION  the latest complete evaluation
##   RECAP       the whole run: progress between evaluations      INSIGHT  reward breakdown, heatmaps, sampling vs best move      SETUP  rewards, observations, actions, network, PPO settings
## The match pauses while another page is shown.
##   Godot --path . res://tools/watch_training.tscn -- --tag jit7 --start res://out_5v5/ckpt/jit6_u50.json [--page training]
## The scene is a CanvasLayer above the App autoload's own full-screen background.
## Needs the nets served by tools/net_server.py (ports 7301 = the run's newest checkpoint, 7302 = RL Team 4, 7303 = the run's best checkpoint):
## the GDScript MLP is too slow to play two net teams in real time on a Raspberry Pi.
## The match is also streamed (UDP to 127.0.0.1:7310, JSON) to tools/dashboard.py, which shows it live in the browser (#/live).

const Data := preload("res://tools/training_data.gd")
const Page := preload("res://tools/training_page.gd")
const PAGES := ["live", "training", "evaluation", "recap", "insight", "setup"]

var tag := "sp"
var start_weights := Data.FALLBACK        # played until the run saves its first checkpoint (= the net server's --model)
var start_page := "live"
var rng := RandomNumberGenerator.new()
var data := Data.new()
var _views: Dictionary = {}               # page name -> its Control
var _buttons: Dictionary = {}
var _status: Label
var _best_ckpt := false                  # BEST CKPT button: play the best checkpoint of the run (port 7303) instead of the newest (7301)
var _best_move := false                  # BEST MOVE button: the next matches play the net's best move instead of sampling
var _ms: MatchScreen = null              # the match being shown (streamed to the web dashboard)
var _udp := PacketPeerUDP.new()
var _frames := 0
const STREAM_PORT := 7310
const OPP_PORT := 7304                   # net server of the opponent picker (service soccer-oppnet)
var opp_label := "RL Team 4"
var _mode := "match"                      # "match" (90 s, kickoff) or "puzzle" (60 s from a random layout of all players and the ball, over at the first goal)
var _choice_snapshot := ""                # contents of the dashboard's choice files when the shown match started: a change ends the match early
@onready var nav_row: HBoxContainer = $Root/Nav/Row
@onready var pages: Control = $Root/Pages
@onready var banner: Label = $Root/Banner
@onready var sidebar = $Root/Pages/Live/Sidebar
@onready var match_area: Control = $Root/Pages/Live/MatchArea


func _ready() -> void:
    var a := OS.get_cmdline_user_args()
    for i in a.size() - 1:
        if a[i] == "--tag":
            tag = a[i + 1]
        if a[i] == "--page":
            start_page = a[i + 1]
        if a[i] == "--start":
            start_weights = a[i + 1]
    rng.randomize()
    get_viewport().msaa_2d = Viewport.MSAA_DISABLED
    Engine.max_fps = 30            # the physics keeps its 60 ticks/s; only drawing is halved
    data.setup(tag, start_weights)
    sidebar.start(data)
    _build_nav()
    _views["live"] = $Root/Pages/Live
    for kind in ["training", "evaluation", "recap", "insight", "setup"]:
        var page := Page.new()
        page.setup(kind, data)
        pages.add_child(page)
        page.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
        _views[kind] = page
    var timer := Timer.new()
    timer.wait_time = 2.0
    timer.autostart = true
    timer.timeout.connect(_refresh)
    add_child(timer)
    _show(start_page if start_page in PAGES else "live")
    _udp.connect_to_host("127.0.0.1", STREAM_PORT)
    _next()


func _build_nav() -> void:
    $Root/Nav.add_theme_stylebox_override("panel", _flat(Color(0.03, 0.04, 0.06), 6))
    banner.add_theme_stylebox_override("normal", _flat(Color("ffd54a"), 4))
    banner.add_theme_color_override("font_color", Color.BLACK)
    banner.add_theme_font_size_override("font_size", 16)
    for name in PAGES:
        var b := Button.new()
        b.text = name.to_upper()
        b.toggle_mode = true
        b.custom_minimum_size = Vector2(98, 46)              # big enough for a finger
        b.add_theme_font_size_override("font_size", 16)
        b.add_theme_stylebox_override("normal", _flat(Color(0.12, 0.14, 0.18), 4))
        b.add_theme_stylebox_override("hover", _flat(Color(0.17, 0.2, 0.26), 4))
        b.add_theme_stylebox_override("pressed", _flat(Color(0.18, 0.5, 0.35), 4))
        b.add_theme_stylebox_override("hover_pressed", _flat(Color(0.2, 0.55, 0.38), 4))
        b.focus_mode = Control.FOCUS_NONE
        b.pressed.connect(_show.bind(name))
        nav_row.add_child(b)
        _buttons[name] = b
    var spacer := Control.new()
    spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    nav_row.add_child(spacer)
    nav_row.add_child(_toggle("BEST CKPT", func(on: bool): _best_ckpt = on))
    var best := _toggle("BEST MOVE", func(on: bool): _best_move = on)
    nav_row.add_child(best)
    _status = Label.new()
    _status.add_theme_font_size_override("font_size", 13)
    nav_row.add_child(_status)


## A toggle button of the navigation bar (not a page): BEST MOVE, BEST CKPT.
func _toggle(label: String, on_toggled: Callable) -> Button:
    var b := Button.new()
    b.text = label
    b.toggle_mode = true
    b.custom_minimum_size = Vector2(94, 46)
    b.add_theme_font_size_override("font_size", 13)
    b.add_theme_stylebox_override("normal", _flat(Color(0.12, 0.14, 0.18), 4))
    b.add_theme_stylebox_override("pressed", _flat(Color(0.55, 0.42, 0.1), 4))
    b.add_theme_stylebox_override("hover", _flat(Color(0.17, 0.2, 0.26), 4))
    b.add_theme_stylebox_override("hover_pressed", _flat(Color(0.6, 0.46, 0.12), 4))
    b.focus_mode = Control.FOCUS_NONE
    b.toggled.connect(on_toggled)
    return b


static func _flat(color: Color, margin: float) -> StyleBoxFlat:
    var sb := StyleBoxFlat.new()
    sb.bg_color = color
    sb.set_content_margin_all(margin)
    sb.set_corner_radius_all(6)
    return sb


## Shows one page; the live match only runs while its page is visible.
func _show(name: String) -> void:
    for key in _views:
        _views[key].visible = key == name
    _views["live"].process_mode = Node.PROCESS_MODE_INHERIT if name == "live" else Node.PROCESS_MODE_DISABLED
    for key in _buttons:
        _buttons[key].button_pressed = key == name
    _refresh()


func _refresh() -> void:
    data.refresh()
    var l := data.last()
    _status.text = "%s  u%d  %s" % [tag, l.upd, data.state_text()] if not l.is_empty() else tag
    _status.add_theme_color_override("font_color", Color(data.state_colour()))
    var ev := data.eval_running()                      # banner on every page while an evaluation runs
    banner.visible = not ev.is_empty()
    if banner.visible:
        banner.text = "EVALUATION RUNNING  ·  %s  ·  started %s ago%s" % [ev.checkpoint, Data.duration(int(Time.get_unix_time_from_system()) - int(ev.started)), "  ·  training is paused" if ev.get("paused", false) else ""]
    for key in _views:
        if _views[key].visible and _views[key].has_method("refresh"):
            _views[key].refresh()
    if _views["live"].visible:
        sidebar.refresh()


## The opponent of the next match. Default and "random": drawn for every match from all handmade (rule-based) teams, RL Team 4/5 and the
## earlier runs' best checkpoints (out_5v5/ckpt/x_*_best.json, jit8, t48_u100). The dashboard's Live page can pin one opponent instead
## (logs/live_opponent.json, written by tools/dashboard.py). A net opponent is served by tools/net_server.py on OPP_PORT (service soccer-oppnet),
## which reads the model to play from logs/live_opp_net.json (written here before the match connects).
func _opponent() -> Dictionary:
    var sel: Dictionary = {}
    var f := FileAccess.open("res://logs/live_opponent.json", FileAccess.READ)
    if f != null:
        var parsed = JSON.parse_string(f.get_as_text())
        if parsed is Dictionary:
            sel = parsed
    var kind := str(sel.get("kind", "random"))
    if kind == "random":
        var pool: Array = []
        for t: TeamDef in Database.teams.values():
            if t.ml_model == "":
                pool.append({"kind": "rule", "team": t.id, "label": t.id.capitalize()})
        pool.append({"kind": "net", "model": "data/models/rl_5v5_arena_v4.json", "label": "RL Team 4"})
        pool.append({"kind": "net", "model": "data/models/rl_5v5_arena_v5.json", "label": "RL Team 5"})
        pool.append({"kind": "net", "model": "out_5v5/ckpt/t48_u100.json", "label": "Start net t48_u100"})
        pool.append({"kind": "net", "model": "out_5v5/ckpt/jit8_best.json", "label": "jit8 (54-number)"})
        for fn in DirAccess.get_files_at("res://out_5v5/ckpt"):
            if fn.begins_with("x_") and fn.ends_with("_best.json"):
                pool.append({"kind": "net", "model": "out_5v5/ckpt/" + fn, "label": "Run %s (best)" % fn.trim_prefix("x_").trim_suffix("_best.json")})
        sel = pool[rng.randi() % pool.size()]
        kind = sel.kind
    if kind == "rule" and Database.teams.has(str(sel.get("team", ""))):
        return {"team": str(sel.team), "net": false, "label": str(sel.get("label", sel.team))}
    var model := str(sel.get("model", "data/models/rl_5v5_arena_v4.json"))
    var nf := FileAccess.open("res://logs/live_opp_net.json", FileAccess.WRITE)
    if nf != null:
        nf.store_string(JSON.stringify({"model": model}))
        nf.close()
    return {"team": "rl_team_4", "net": true, "label": str(sel.get("label", "RL Team 4"))}


## Starts a match of the newest weights (the net server loads them when the match connects).
func _next() -> void:
    for old in match_area.get_children():
        old.queue_free()
    var best := data.best_checkpoint()
    var use_best := _best_ckpt and not best.is_empty()
    data.playing = str(best.checkpoint) if use_best else Data.newest_checkpoint(tag, start_weights).get_file().get_basename()
    var opp := _opponent()
    _mode = "puzzle" if _read_text("res://logs/live_mode.json").contains("puzzle") else "match"
    _choice_snapshot = _choices()
    var cfg := Database.make_config("rl_team_5", opp.team, "arena", 5, 60.0 if _mode == "puzzle" else 90.0, rng.randi())
    cfg.control = MatchConfig.ControlMode.NONE
    cfg.ml_models[0] = RemoteMLP.new(7303 if use_best else 7301)
    if opp.net:
        cfg.ml_models[1] = RemoteMLP.new(OPP_PORT)                 # the opponent net chosen on the dashboard (tools/net_server.py --select-file)
    opp_label = opp.label
    cfg.ml_keeper = true
    if _best_move:
        cfg.ml_temperature = 0.0                                   # argmax instead of sampling (applies from the next match)
    var ms := MatchScreen.new().setup(cfg)
    ms.finished.connect(func(_result): _next.call_deferred())
    ms.quit_requested.connect(get_tree().quit)
    match_area.add_child(ms)                                       # the sim is built when the screen enters the tree
    if _mode == "puzzle":
        _puzzle_layout(ms.sim)
    _ms = ms
    ms.set_effects(false)                                          # no confetti: cheaper on the Pi
    ms.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)    # a screen added after the first match would stay 0x0
    _auto_continue(ms)


## No keyboard needed: after the final whistle, record the score and move on after a short pause. Puzzle mode: the first goal ends the
## puzzle (after the celebration); a change of mode or opponent on the dashboard ends the shown match at once.
func _auto_continue(ms: MatchScreen) -> void:
    var celebrate := 0
    while is_instance_valid(ms) and ms.sim.state != MatchSim.State.ENDED:
        await get_tree().create_timer(0.5).timeout
        if not is_instance_valid(ms):
            return
        if _choices() != _choice_snapshot:
            ms.finished.emit(ms.sim.make_result())
            return
        if _mode == "puzzle" and (ms.sim.scores[0] + ms.sim.scores[1]) > 0:
            celebrate += 1
            if celebrate >= 5:                                     # ~2.5 s of celebration, then the next puzzle
                ms.finished.emit(ms.sim.make_result())
                return
    if not is_instance_valid(ms):
        return
    if _mode == "match":
        data.record_result(ms.sim.scores[0], ms.sim.scores[1])
    await get_tree().create_timer(4.0 if _mode == "match" else 2.0).timeout
    if is_instance_valid(ms):
        ms.finished.emit(ms.sim.make_result())


func _read_text(path: String) -> String:
    var f := FileAccess.open(path, FileAccess.READ)
    return f.get_as_text() if f != null else ""


func _choices() -> String:
    return _read_text("res://logs/live_mode.json") + _read_text("res://logs/live_opponent.json")


## Puzzle: every player (keepers too) and the ball at random places (as in training's random starts), play from the first tick.
func _puzzle_layout(sim: MatchSim) -> void:
    var pt := sim.pitch
    sim.kickoff_active = false
    sim.kickoff_taker = null
    sim.state = MatchSim.State.PLAYING
    var hw := pt.half_w * 0.9
    var hh := pt.half_h * 0.9
    sim.ball.pos = Vector2(rng.randf_range(-hw, hw), rng.randf_range(-hh, hh))
    sim.ball.vel = Vector2.from_angle(rng.randf() * TAU) * rng.randf_range(0.0, 3.0)
    var placed: Array[Vector2] = [sim.ball.pos]
    for p: SimPlayer in sim.players:
        var pos := Vector2.ZERO
        for _try in 40:
            pos = Vector2(rng.randf_range(-hw, hw), rng.randf_range(-hh, hh))
            var ok := true
            for q in placed:
                if q.distance_to(pos) < 45.0:
                    ok = false
                    break
            if ok:
                break
        p.pos = pos
        p.vel = Vector2.ZERO
        placed.append(pos)


## Streams the shown match to the web dashboard: a "meta" packet (pitch, kits, players) once a second and a frame with
## the positions every drawn frame (30/s). Small JSON over local UDP: nothing waits if the dashboard is not running.
func _process(_delta: float) -> void:
    if _ms == null or not is_instance_valid(_ms) or _ms.sim == null:
        return
    var sim: MatchSim = _ms.sim
    _frames += 1
    if _frames % 30 == 1:
        _udp.put_packet(JSON.stringify(_stream_meta(sim)).to_utf8_buffer())
    var pl: Array = []
    for p in sim.players:
        pl.append(snappedf(p.pos.x, 0.1))
        pl.append(snappedf(p.pos.y, 0.1))
    _udp.put_packet(JSON.stringify({"k": "f", "id": sim.cfg.match_seed, "t": sim.tick, "st": int(sim.state), "tl": snappedf(sim.time_left, 0.1),
        "sc": sim.scores, "b": [snappedf(sim.ball.pos.x, 0.1), snappedf(sim.ball.pos.y, 0.1)], "p": pl, "ko": sim.kickoff_active,
        "gt": sim.goal_team, "paused": not _views["live"].visible}).to_utf8_buffer())


func _stream_meta(sim: MatchSim) -> Dictionary:
    var pd := sim.pitch
    var teams: Array = []
    for t in 2:
        var td: TeamDef = sim.cfg.teams[t]
        teams.append({"name": td.name, "short": td.short, "primary": sim.cfg.kits[t][0].to_html(false), "secondary": sim.cfg.kits[t][1].to_html(false),
            "pattern": td.kit_pattern, "net": "remote" if sim.cfg.ml_models[t] != null else ""})
    var players: Array = []
    for p in sim.players:
        players.append({"team": p.team, "n": p.def.number, "r": p.radius, "role": p.role})
    var l := data.last()
    return {"k": "m", "id": sim.cfg.match_seed, "tag": tag, "playing": data.playing, "opponent": opp_label, "mode": _mode, "upd": l.get("upd", 0), "best_move": sim.cfg.ml_temperature == 0.0,
        "best_ckpt": _best_ckpt, "duration": sim.cfg.duration, "ball_r": sim.ball.radius, "teams": teams, "players": players,
        "pitch": {"half_w": pd.half_w, "half_h": pd.half_h, "goal_half": pd.goal_half, "net_depth": pd.net_depth, "out_x": pd.out_x, "out_y": pd.out_y,
            "center_r": pd.center_r, "box_depth": pd.box_depth, "box_half": pd.box_half, "stripes": pd.stripes, "post_r": pd.post_r,
            "pitch": pd.color_pitch.to_html(false), "outer": pd.color_outer.to_html(false), "line": pd.color_line.to_html(false)}}
