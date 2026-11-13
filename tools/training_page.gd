extends MarginContainer
## Full-window pages of the training viewer (kind = "training", "evaluation", "recap" or "setup"): text on the left, charts on the right.
## Built for a 1024x600 touch screen: large text, no scrolling. Refreshed by tools/watch_training.gd while visible.

const Data := preload("res://tools/training_data.gd")
const LineChart := preload("res://tools/line_chart.gd")

var kind := ""
var data: Data
var _text: RichTextLabel
var _side: RichTextLabel          # evaluation and setup pages: second text column instead of charts
var _third: RichTextLabel         # setup page: third text column
var _charts: VBoxContainer
var _chart_nodes: Array = []


func setup(page_kind: String, training_data: Data) -> void:
    kind = page_kind
    data = training_data
    set_anchors_preset(Control.PRESET_FULL_RECT)
    add_theme_constant_override("margin_left", 16)
    add_theme_constant_override("margin_right", 16)
    add_theme_constant_override("margin_top", 10)
    add_theme_constant_override("margin_bottom", 10)
    var row := HBoxContainer.new()
    row.add_theme_constant_override("separation", 20)
    add_child(row)
    _text = RichTextLabel.new()
    _text.bbcode_enabled = true
    _text.scroll_active = false
    _text.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    _text.size_flags_stretch_ratio = 1.15
    _text.add_theme_font_size_override("normal_font_size", 15)
    _text.add_theme_font_size_override("bold_font_size", 15)
    row.add_child(_text)
    _charts = VBoxContainer.new()
    _charts.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    _charts.add_theme_constant_override("separation", 10)
    row.add_child(_charts)
    match kind:
        "training":
            _add_chart("POINTS PER MATCH  (green rule-based · yellow RL Team 5 · blue snapshots)", data.history, "upd", [["rules", Data.GOOD], ["bench", Data.OK], ["league", Data.BLUE]], Vector2(0, 3))
            _add_chart("REWARD / STEP", data.history, "upd", [["rew", Data.GOOD]], null)
            _add_chart("ENTROPY", data.history, "upd", [["ent", Data.OK]], null)
        "recap":
            _add_chart("LEAGUE POINTS / MATCH  (green all teams · yellow held-out teams)", [], "update", [["all", Data.GOOD], ["held", Data.OK]], Vector2(0, 3))
            _add_chart("POINTS vs RL TEAM 4 (green) · RL TEAM 5 (yellow)", [], "update", [["rl4", Data.GOOD], ["rl5", Data.OK]], Vector2(0, 3))
            _add_chart("DIRECTION CHANGES / s  (lower = less twitchy; rule bots about 2)", [], "update", [["dir", Data.BLUE]], null)
        _:                       # "evaluation" and "setup": a second text column instead of charts
            _charts.visible = false
            _side = RichTextLabel.new()
            _side.bbcode_enabled = true
            _side.scroll_active = false
            _side.size_flags_horizontal = Control.SIZE_EXPAND_FILL
            _side.add_theme_font_size_override("normal_font_size", 15)
            _side.add_theme_font_size_override("bold_font_size", 15)
            row.add_child(_side)
            if kind == "setup":
                _third = RichTextLabel.new()
                _third.bbcode_enabled = true
                _third.scroll_active = false
                _third.size_flags_horizontal = Control.SIZE_EXPAND_FILL
                row.add_child(_third)
                for label in [_text, _side, _third]:
                    label.add_theme_font_size_override("normal_font_size", 14)
                    label.add_theme_font_size_override("bold_font_size", 14)
                    label.size_flags_stretch_ratio = 1.0
                row.add_theme_constant_override("separation", 14)
    refresh()


func _add_chart(title: String, rows: Array, x_key: String, series: Array, fixed: Variant) -> void:
    var c := LineChart.new()
    c.title = title
    c.rows = rows
    c.x_key = x_key
    c.series = series
    c.fixed = fixed
    c.font_size = 12
    c.size_flags_vertical = Control.SIZE_EXPAND_FILL
    _charts.add_child(c)
    _chart_nodes.append(c)


func refresh() -> void:
    match kind:
        "training":
            _text.text = _training_text()
        "evaluation":
            _evaluation()
        "setup":
            _setup()
        "recap":
            var evs := data.evaluations()
            for c in _chart_nodes:
                c.rows = data.evaluation_rows(evs)
            _text.text = _recap_text(evs)
    for c in _chart_nodes:
        c.queue_redraw()


# ---------------------------------------------------------------- training

func _training_text() -> String:
    var l := data.last()
    var t := "[b][font_size=20]TRAINING  %s[/font_size][/b]" % data.tag
    if l.is_empty():
        return t + "\n\n[color=#%s]no training log yet (logs/%s.out)[/color]" % [Data.MUTED, data.tag]
    var running := data.is_running()
    var per := data.seconds_per_update()
    t += "   [color=#%s][b]%s[/b][/color]\n" % [Data.GOOD if running else Data.BAD, "RUNNING" if running else "STOPPED"]
    t += "update [b]%d[/b]  ·  %s elapsed  ·  %.0f s/update  ·  %d decisions/s\n\n" % [l.upd, Data.hms(l.elapsed), per, l.dec]
    t += Data.section("POINTS PER MATCH (3 = win, recent matches)", [["[color=#%s]●[/color] vs rule-based teams" % Data.GOOD, Data.points(l.rules)],
            ["[color=#%s]●[/color] vs RL Team 5 (start weights)" % Data.OK, Data.points(l.bench)], ["[color=#%s]●[/color] vs past snapshots" % Data.BLUE, Data.points(l.league)]])
    t += Data.section("LEARNING", [["reward / step", Data.num_text(l.rew, "%.4f")], ["entropy", Data.num_text(l.ent)], ["opponent pool", str(l.pool)],
            ["simulate / learn time", "%.1f s / %.1f s" % [l.sim, l.learn]]])
    var rows := [["playing", "[b]%s[/b]" % (data.playing if data.playing != "" else "-")], ["newest", data.newest_name()]]
    var upd: int = l.upd
    rows.append(["next checkpoint", "update %d  (in ~%s)" % [upd + Data.CKPT_EVERY - upd % Data.CKPT_EVERY, Data.duration(data.eta_to(upd + Data.CKPT_EVERY - upd % Data.CKPT_EVERY))]])
    rows.append(["next evaluation", "update %d  (in ~%s)" % [upd + Data.EVAL_EVERY - upd % Data.EVAL_EVERY, Data.duration(data.eta_to(upd + Data.EVAL_EVERY - upd % Data.EVAL_EVERY))]])
    t += Data.section("CHECKPOINTS", rows)
    return t + Data.section("MACHINE", data.system_rows())


# ---------------------------------------------------------------- evaluation

func _evaluation() -> void:
    var evs := data.evaluations()
    var head := "[b][font_size=20]EVALUATION  %s[/font_size][/b]\n" % data.tag
    if evs.is_empty():
        _text.text = head + "\n[color=#%s]No evaluation finished yet.\nThe training run starts one every %d updates, in the background at the lowest priority, and it takes a while.[/color]" % [Data.MUTED, Data.EVAL_EVERY]
        _side.text = ""
        return
    var e: Dictionary = evs[-1]
    var t := head + "[b]%s[/b]  ·  finished %s\n\n" % [e.name.trim_prefix(data.tag + "_"), Data.ago(e.age)]
    t += "[color=#%s]LEAGUE, per team  (the net vs each rule-based team, both sides)[/color]\n[table=5]" % Data.MUTED
    for team in e.teams:
        t += "[cell][color=#%s]%s%s   [/color][/cell][cell][color=#%s]%s   [/color][/cell][cell]%dW %dD %dL   [/cell][cell]%s   [/cell][cell][color=#%s]%.1f-%.1f[/color][/cell]" % [
                Data.MUTED, team.id, " *" if team.held else "", Data.MUTED, team.tier, team.w, team.d, team.l, Data.points(team.pts), Data.MUTED, team.gf, team.ga]
    _text.text = t + "[/table]\n[color=#%s]* held-out team (never trained against)[/color]" % Data.MUTED
    var L: Dictionary = e.league
    var s := "\n\n"
    if L.has("all"):
        s += Data.section("LEAGUE SUMMARY  (%d matches, points / match, goals for-against)" % L.all[3], [
                ["all teams", "%s  [color=#%s]%.2f-%.2f[/color]" % [Data.points(L.all[0]), Data.MUTED, L.all[1], L.all[2]]],
                ["trained against", Data.points(L.get("train", [NAN])[0])], ["held-out teams", Data.points(L.get("held", [NAN])[0])],
                ["weak  /  average", "%s   %s" % [Data.points(L.get("weak", [NAN])[0]), Data.points(L.get("average", [NAN])[0])]],
                ["strong  /  elite", "%s   %s" % [Data.points(L.get("strong", [NAN])[0]), Data.points(L.get("elite", [NAN])[0])]]])
    var rows := []
    for name in e.h2h:
        var h: Array = e.h2h[name]
        rows.append(["vs " + name, "%dW %dD %dL   %s   [color=#%s]%.1f-%.1f[/color]" % [h[0], h[1], h[2], Data.points(h[3]), Data.MUTED, h[4], h[5]]])
    if not rows.is_empty():
        s += Data.section("HEAD TO HEAD", rows)
    if not e.rl.is_empty():
        rows = []
        for row in [["direction changes / s", "dir", "%.1f"], ["kick presses / s", "kick", "%.2f"], ["keeper from its goal (px)", "keeper", "%.0f"],
                ["passes / match", "passes", "%.1f"], ["pass accuracy %", "acc", "%.0f"], ["key passes / match", "key", "%.2f"], ["shots / match", "shots", "%.1f"]]:
            if e.rl.has(row[1]):
                rows.append([row[0], "%s   [color=#%s]rule bots %s[/color]" % [row[2] % e.rl[row[1]], Data.MUTED, Data.num_text(e.rule.get(row[1], NAN), row[2])]])
        s += Data.section("BEHAVIOUR", rows)
    _side.text = s


# ---------------------------------------------------------------- recap

func _recap_text(evs: Array) -> String:
    var t := "[b][font_size=20]RECAP  %s[/font_size][/b]\n\n" % data.tag
    var l := data.last()
    if not l.is_empty():
        t += Data.section("THE RUN", [["updates", "[b]%d[/b]  ·  %s of training" % [l.upd, Data.hms(l.elapsed)]],
                ["speed", "%.0f s/update  ·  %.0f updates/h" % [data.seconds_per_update(), 3600.0 / maxf(data.seconds_per_update(), 1.0)]],
                ["started from", data.fallback.get_file().get_basename()],
                ["status", "[color=#%s][b]%s[/b][/color]" % [Data.GOOD if data.is_running() else Data.BAD, "running" if data.is_running() else "stopped"]]])
    if evs.is_empty():
        return t + "[color=#%s]No evaluation finished yet: nothing to compare.[/color]" % Data.MUTED
    var rows := data.evaluation_rows(evs)
    var first: Dictionary = rows[0]
    var cur: Dictionary = rows[-1]
    var best: Dictionary = rows[0]
    for r in rows:
        if not is_nan(r.all) and (is_nan(best.all) or r.all > best.all):
            best = r
    t += Data.section("PROGRESS  (first evaluation -> latest)", [
            ["league pts / match", "%s -> %s" % [Data.num_text(first.all), Data.points(cur.all)]],
            ["vs RL Team 4", "%s -> %s" % [Data.num_text(first.rl4), Data.points(cur.rl4)]],
            ["vs RL Team 5", "%s -> %s" % [Data.num_text(first.rl5), Data.points(cur.rl5)]],
            ["direction changes / s", "%s -> [b]%s[/b]" % [Data.num_text(first.dir, "%.1f"), Data.num_text(cur.dir, "%.1f")]],
            ["key passes / match", "%s -> %s" % [Data.num_text(first.key, "%.2f"), Data.num_text(cur.key, "%.2f")]],
            ["keeper from its goal", "%s -> %s px" % [Data.num_text(first.keeper, "%.0f"), Data.num_text(cur.keeper, "%.0f")]]])
    t += Data.section("BEST CHECKPOINT (league points)", [["update %d" % best.update, "%s pts/match   ·   %d evaluations so far" % [Data.num_text(best.all), rows.size()]]])
    t += "[color=#%s]ALL EVALUATIONS  (league · held-out · RL4 · RL5 · jitter/s)[/color]\n[table=2]" % Data.MUTED
    for r in rows.slice(maxi(rows.size() - 8, 0)):
        t += "[cell][color=#%s]u%d   [/color][/cell][cell]%s %s %s %s  [color=#%s]%s[/color][/cell]" % [Data.MUTED, r.update, Data.points(r.all), Data.points(r.held), Data.points(r.rl4), Data.points(r.rl5), Data.MUTED, Data.num_text(r.dir, "%.1f")]
    t += "[/table]\n"
    var rec := ""
    for name in data.record:
        var w: Array = data.record[name]
        rec += "%s %dW %dD %dL   " % [name.trim_prefix(data.tag + "_"), w[0], w[1], w[2]]
    if rec != "":
        t += "\n[color=#%s]WATCHED IN THIS WINDOW[/color]\n%s" % [Data.MUTED, rec]
    return t


# ---------------------------------------------------------------- setup

## Rewards, observations, actions, network and training settings (the values come from the run's config file).
func _setup() -> void:
    var c := data.run_config()
    var t := "[b][font_size=20]SETUP  %s[/font_size][/b]\n" % data.tag
    if c.is_empty():
        t += "[color=#%s]run settings not found (logs/%s_config.json): weights shown as ?[/color]\n" % [Data.MUTED, data.tag]
    t += "\n"
    t += Data.section("REWARD, shared by the 5 players (every decision)", [
            ["goal scored / conceded", "[b]+10 / -10[/b]"], ["time", "-0.0005"],
            ["ball shaping", "[color=#%s]ball nearer the goal, teammate nearer the ball[/color]" % Data.MUTED]])
    t += Data.section("REWARD, personal", [
            ["progressive pass (passer)", _w(c, "w_pass_prog", "+")], ["failed pass (passer)", _w(c, "w_pass_fail", "-")],
            ["other completed pass", _w(c, "w_pass_ok", "+")], ["pass received", _w(c, "w_recv", "+")],
            ["key pass (receiver shoots)", _w(c, "w_key_pass", "+")], ["expected assist", "%s x xA" % _w(c, "w_xa", "+")],
            ["cooperation cap / match", _w(c, "coop_cap", "")], ["standing open", _w(c, "w_open", "+")],
            ["teammate too close", _w(c, "w_space", "-")], ["kick away from ball", _w(c, "w_kick", "-")],
            ["keeper far from goal", _w(c, "w_keeper", "-")], ["direction twitch", _w(c, "w_jitter", "-")]])
    _text.text = t
    var d := "\n\n"
    d += Data.section("OBSERVATION  (%d numbers, 30 / s)" % int(c.get("obs_dim", 54)), [
            ["own position + speed", "4"], ["ball position + speed", "4"], ["4 teammates", "4 x 4 = 16"], ["5 opponents", "5 x 4 = 20"],
            ["ball relative to me", "3"], ["opp. goal relative to me", "2"], ["my slot (one-hot)", "5"]])
    d += "[color=#%s]Seen from the own attacking side (mirrored); positions scaled by the pitch, speeds by 5.[/color]\n\n" % Data.MUTED
    d += Data.section("ACTIONS", [["move", "9: 8 directions or still"], ["kick", "pressed or not"], ["decision", "every 2 ticks (30 / s)"], ["choice", "sampled, not argmax"]])
    d += Data.section("NETWORK  (shared by all 5 players)", [["actor", "54 - 128 - 128 - 10"], ["critic", "54 - 128 - 128 - 1"]])
    _side.text = d
    var tr := "\n\n"
    tr += Data.section("TRAINING  (PPO)", [
            ["parallel matches", _matches(c)], ["steps / env / update", _int(c, "rollout")],
            ["epochs", _int(c, "epochs")], ["minibatch", _int(c, "minibatch")], ["learning rate", str(c.get("lr", "?"))],
            ["gamma / lambda", "%s / %s" % [c.get("gamma", "?"), c.get("lam", "?")]], ["entropy bonus", str(c.get("ent", "?"))],
            ["clip / grad clip", "0.2 / 0.5"]])
    tr += Data.section("EPISODES", [
            ["length", "90 s match, 5v5 arena"], ["random starts", "%s of episodes" % _percent(c.get("random_start", NAN))],
            ["started from", str(c.get("start", "?")).get_file()], ["opponents", "12 rule-based teams (4 held out), past snapshots, the start weights"]])
    _third.text = tr


static func _int(c: Dictionary, key: String) -> String:
    return str(int(c[key])) if c.has(key) else "?"


static func _w(c: Dictionary, key: String, sign: String) -> String:
    return "[b]%s%s[/b]" % [sign, str(c[key])] if c.has(key) else "?"


static func _matches(c: Dictionary) -> String:
    if not c.has("workers_rule"):
        return "?"
    return "%d  (%d+%d workers x %d)" % [(int(c.workers_rule) + int(c.workers_self)) * int(c.envs_per_worker), int(c.workers_rule), int(c.workers_self), int(c.envs_per_worker)]


static func _percent(v: Variant) -> String:
    return "?" if is_nan(float(v)) else "%d%%" % roundi(float(v) * 100.0)
