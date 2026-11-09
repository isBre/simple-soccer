extends Node
## Regression test: a screen starts a match with callbacks bound to itself (like QuickMatch / Tournament hub).

class Starter extends Control:
    var got := false
    func start(cfg: MatchConfig) -> void:
        App.play_match(cfg, _done, App.menu)
    func _done(res: Dictionary) -> void:
        got = true
        App.set_meta("flow_got", true)
        App.show_screen(ReportScreen.new().setup(res, App.menu))


func _ready() -> void:
    await get_tree().process_frame
    var st := Starter.new()
    App.show_screen(st)
    var cfg := Database.make_config("aurora", "borealis", "classic", 3, 6.0, 3)
    st.start(cfg)
    var waited := 0.0
    var state := -1
    while waited < 40.0:
        await get_tree().create_timer(0.5).timeout
        waited += 0.5
        var cur = App.current
        if cur != null and "sim" in cur:
            state = int(cur.sim.state)
            if cur.sim.state == MatchSim.State.ENDED:
                break
    await get_tree().create_timer(1.0).timeout
    var ev := InputEventKey.new()
    ev.keycode = KEY_ENTER
    ev.physical_keycode = KEY_ENTER
    ev.pressed = true
    Input.parse_input_event(ev)
    await get_tree().create_timer(1.0).timeout
    var got: bool = App.has_meta("flow_got")
    var ok := got and App.current is ReportScreen
    var f := FileAccess.open("res://experiments/flow_test.txt", FileAccess.WRITE)
    f.store_string("FLOW %s (got=%s state=%d waited=%.1f current=%s)\n" % ["OK" if ok else "FAIL", got, state, waited, App.current])
    f.close()
    get_tree().quit()
