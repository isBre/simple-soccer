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


## Starts a match of the newest weights (the net server loads them when the match connects).
func _next() -> void:
    for old in match_area.get_children():
        old.queue_free()
    var best := data.best_checkpoint()
    var use_best := _best_ckpt and not best.is_empty()
    data.playing = str(best.checkpoint) if use_best else Data.newest_checkpoint(tag, start_weights).get_file().get_basename()
    var cfg := Database.make_config("rl_team_5", "rl_team_4", "arena", 5, 90.0, rng.randi())
    cfg.control = MatchConfig.ControlMode.NONE
    cfg.ml_models[0] = RemoteMLP.new(7303 if use_best else 7301)
    cfg.ml_models[1] = RemoteMLP.new(7302)
    cfg.ml_keeper = true
    if _best_move:
        cfg.ml_temperature = 0.0                                   # argmax instead of sampling (applies from the next match)
    var ms := MatchScreen.new().setup(cfg)
    ms.finished.connect(func(_result): _next.call_deferred())
    ms.quit_requested.connect(get_tree().quit)
    match_area.add_child(ms)
    ms.set_effects(false)                                          # no confetti: cheaper on the Pi
    ms.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)    # a screen added after the first match would stay 0x0
    _auto_continue(ms)


## No keyboard needed: after the final whistle, record the score and move on after a short pause.
func _auto_continue(ms: MatchScreen) -> void:
    while is_instance_valid(ms) and ms.sim.state != MatchSim.State.ENDED:
        await get_tree().create_timer(1.0).timeout
    if not is_instance_valid(ms):
        return
    data.record_result(ms.sim.scores[0], ms.sim.scores[1])
    await get_tree().create_timer(4.0).timeout
    if is_instance_valid(ms):
        ms.finished.emit(ms.sim.make_result())
