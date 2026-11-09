extends Node
## Autoload: screen navigation + shared state.

var root: Control
var current: Control
var tournament: Tournament = null


func _ready() -> void:
    var layer := CanvasLayer.new()
    add_child(layer)
    var bg := ColorRect.new()
    bg.color = UIKit.BG
    bg.set_anchors_preset(Control.PRESET_FULL_RECT)
    layer.add_child(bg)
    root = Control.new()
    root.set_anchors_preset(Control.PRESET_FULL_RECT)
    root.theme = UIKit.make_theme()
    layer.add_child(root)


func show_screen(s: Control) -> void:
    if current != null:
        current.queue_free()
    current = s
    s.set_anchors_preset(Control.PRESET_FULL_RECT)
    root.add_child(s)


func menu() -> void:
    show_screen(MainMenuScreen.new())


## Runs a live match, then calls on_done(result) (Enter after full time) or on_quit().
## The screen that started the match stays alive (hidden) until then, because the callbacks
## are usually bound to it.
func play_match(cfg: MatchConfig, on_done: Callable, on_quit: Callable) -> void:
    var parked: Control = current
    if parked != null:
        parked.visible = false
        parked.process_mode = Node.PROCESS_MODE_DISABLED
        current = null
    var ms := MatchScreen.new().setup(cfg)
    ms.finished.connect(_match_over.bind(on_done, parked))
    ms.quit_requested.connect(_match_quit.bind(on_quit, parked))
    show_screen(ms)


func _match_over(result: Dictionary, on_done: Callable, parked: Control) -> void:
    on_done.call(result)
    _release(parked)


func _match_quit(on_quit: Callable, parked: Control) -> void:
    on_quit.call()
    _release(parked)


func _release(s: Control) -> void:
    if is_instance_valid(s) and s != current:
        s.queue_free()
