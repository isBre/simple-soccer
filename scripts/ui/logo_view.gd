class_name LogoView
extends Control
## Control that shows a team logo.

var team: TeamDef


func _init(t: TeamDef = null, px: float = 48.0) -> void:
    team = t
    custom_minimum_size = Vector2(px, px)
    mouse_filter = Control.MOUSE_FILTER_IGNORE
    resized.connect(queue_redraw)


func set_team(t: TeamDef) -> void:
    team = t
    queue_redraw()


func _draw() -> void:
    if team == null:
        return
    LogoDraw.draw_logo(self, size / 2.0, minf(size.x, size.y) * 0.46, team.logo)
