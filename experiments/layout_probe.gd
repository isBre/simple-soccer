extends Node
## Prints where the Quick Match widgets end vertically (viewport is 1280x720).

func _walk(n: Node, out: Array) -> void:
    out.append(n)
    for c in n.get_children():
        _walk(c, out)


func _ready() -> void:
    var host := Control.new()
    host.set_anchors_preset(Control.PRESET_FULL_RECT)
    add_child(host)
    var screen := QuickMatchScreen.new()
    screen.set_anchors_preset(Control.PRESET_FULL_RECT)
    host.add_child(screen)
    for i in 4:
        await get_tree().process_frame
    var all: Array = []
    _walk(screen, all)
    var lines: PackedStringArray = []
    lines.append("viewport %s" % [get_viewport().get_visible_rect().size])
    for n in all:
        if n is Button and (n as Button).text.begins_with("Kick"):
            lines.append("Kick Off button bottom y = %.0f" % (n as Control).get_global_rect().end.y)
        if n is Label and (n as Label).text in ["Bot brain", "Play style override", "Formation"]:
            lines.append("%s label y = %.0f" % [(n as Label).text, (n as Control).get_global_rect().position.y])
    for n in all:
        if n is PanelContainer:
            lines.append("card %s  y %.0f..%.0f" % [n.get_child(0).get_child(0).get("text") if n.get_child(0).get_child_count() > 0 else "?", (n as Control).get_global_rect().position.y, (n as Control).get_global_rect().end.y])
    var f := FileAccess.open("res://experiments/results_layout.txt", FileAccess.WRITE)
    f.store_string("\n".join(lines) + "\n")
    f.close()
    print("\n".join(lines))
    get_tree().quit()
