extends CanvasLayer
## Live viewer of a training run: matches of the newest checkpoint against RL Team 4 next to a training sidebar.
##   Godot --path . res://tools/watch_training.tscn -- --tag jit4 --start res://out_5v5/ckpt/jit3_u50.json
## The scene is a CanvasLayer above the App autoload's own full-screen background.
## Needs the nets served by tools/net_server.py (ports 7301 = the run's newest checkpoint, 7302 = RL Team 4):
## the GDScript MLP is too slow to play two net teams in real time on a Raspberry Pi.

const Sidebar := preload("res://tools/training_sidebar.gd")

var tag := "sp"
var start_weights := Sidebar.FALLBACK      # played until the run saves its first checkpoint (= the net server's --model)
var rng := RandomNumberGenerator.new()
@onready var sidebar: Sidebar = $Layout/Sidebar
@onready var match_area: Control = $Layout/MatchArea


func _ready() -> void:
    var a := OS.get_cmdline_user_args()
    for i in a.size() - 1:
        if a[i] == "--tag":
            tag = a[i + 1]
        if a[i] == "--start":
            start_weights = a[i + 1]
    rng.randomize()
    get_viewport().msaa_2d = Viewport.MSAA_DISABLED
    Engine.max_fps = 30            # the physics keeps its 60 ticks/s; only drawing is halved
    sidebar.start(tag, start_weights)
    _next()


## Starts a match of the newest weights (the net server loads them when the match connects).
func _next() -> void:
    for old in match_area.get_children():
        old.queue_free()
    sidebar.playing = Sidebar.newest_checkpoint(tag, start_weights).get_file().get_basename()
    var cfg := Database.make_config("rl_team_5", "rl_team_4", "arena", 5, 90.0, rng.randi())
    cfg.control = MatchConfig.ControlMode.NONE
    cfg.ml_models[0] = RemoteMLP.new(7301)
    cfg.ml_models[1] = RemoteMLP.new(7302)
    cfg.ml_keeper = true
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
    sidebar.record_result(ms.sim.scores[0], ms.sim.scores[1])
    await get_tree().create_timer(4.0).timeout
    if is_instance_valid(ms):
        ms.finished.emit(ms.sim.make_result())
