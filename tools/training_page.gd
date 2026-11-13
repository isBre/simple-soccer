extends MarginContainer
## Full-window pages of the training viewer (kind = "training", "evaluation", "recap", "setup" or "insight"): text on the left, charts on the right.
## Built for a 1024x600 touch screen: large text, no scrolling. Refreshed by tools/watch_training.gd while visible.

const Data := preload("res://tools/training_data.gd")
const LineChart := preload("res://tools/line_chart.gd")
const Heatmap := preload("res://tools/heatmap.gd")

## Reward terms: key in the log, label, colour, team-wide (shared by all players) or personal.
const TERMS := [["goals", "goals scored / conceded", "6fd08c", true], ["shaping", "ball shaping", "6ab0ff", true], ["time", "time cost", "8a93a3", true],
        ["pass_prog", "progressive passes", "ffd54a", false], ["pass_fail", "failed passes", "ff6b6b", false], ["coop", "cooperation bonus", "c792ea", false],
        ["open", "standing open", "4dd0e1", false], ["space", "too close to teammate", "ff9e64", false], ["far", "too far from the ball", "ffcc80", false], ["kick", "kick far from ball", "f78fb3", false],
        ["keeper", "keeper far from goal", "b0bec5", false], ["jitter", "direction twitch", "ffffff", false],
        ["xg", "shot quality (xG)", "80cbc4", false], ["xga", "opponent chances (xGA)", "ef5350", true], ["result", "win / draw bonus", "aed581", true],
        ["tackle", "tackles, interceptions", "90caf9", false], ["goalside", "goal-side defending", "ce93d8", false],
        ["opp_half", "opponent in our half", "bcaaa4", true], ["compact", "team stretched", "fff59d", true]]
var _heatmaps: Array = []

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
    if kind == "insight":
        _build_insight(row)
        refresh()
        return
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
            _add_chart("CRITIC explained variance (green) · clip fraction (yellow)", data.ppo_history(), "upd", [["ev", Data.GOOD], ["clipfrac", Data.OK]], null)
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
                    label.add_theme_font_size_override("normal_font_size", 13)
                    label.add_theme_font_size_override("bold_font_size", 13)
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
        "insight":
            _insight()
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
    var per := data.seconds_per_update()
    t += "   [color=#%s][b]%s[/b][/color]\n" % [data.state_colour(), data.state_text()]
    t += "update [b]%d[/b]  ·  %.0f s/update  ·  %d decisions/s\n\n" % [l.upd, per, l.dec]
    t += Data.section("POINTS PER MATCH (3 = win, recent matches)", [["[color=#%s]●[/color] vs rule-based teams" % Data.GOOD, data.points_text("rules")],
            ["[color=#%s]●[/color] vs RL Team 5 (start weights)" % Data.OK, data.points_text("bench")], ["[color=#%s]●[/color] vs past snapshots" % Data.BLUE, data.points_text("league")]])
    t += Data.section("LEARNING", [["reward / step", Data.num_text(l.rew, "%.4f")], ["entropy", Data.num_text(l.ent)], ["opponent pool", str(l.pool)],
            ["simulate / learn time", "%.1f s / %.1f s" % [l.sim, l.learn]]])
    var rows := [["playing", "[b]%s[/b]" % (data.playing if data.playing != "" else "-")], ["newest", data.newest_name()]]
    var upd: int = l.upd
    rows.append(["next checkpoint", "update %d  (in ~%s)" % [upd + Data.CKPT_EVERY - upd % Data.CKPT_EVERY, Data.duration(data.eta_to(upd + Data.CKPT_EVERY - upd % Data.CKPT_EVERY))]])
    rows.append(["next evaluation", "update %d  (in ~%s)" % [upd + Data.EVAL_EVERY - upd % Data.EVAL_EVERY, Data.duration(data.eta_to(upd + Data.EVAL_EVERY - upd % Data.EVAL_EVERY))]])
    t += Data.section("CHECKPOINTS", rows)
    return t + _ppo_health()


## Is the optimiser healthy? Averages of the last 10 updates, coloured against usual PPO ranges.
func _ppo_health() -> String:
    var hist := data.ppo_history()
    if hist.is_empty():
        return "[color=#%s]PPO HEALTH: not logged for this run yet[/color]" % Data.MUTED
    var recent: Array = hist.slice(maxi(hist.size() - 10, 0))
    var avg := {}
    for k in ["ev", "kl", "clipfrac", "vloss", "gradnorm", "ent_move", "ent_kick"]:
        var sum := 0.0
        for r in recent:
            sum += float(r.get(k, 0.0))
        avg[k] = sum / recent.size()
    var ev_c: String = Data.GOOD if avg.ev > 0.5 else (Data.OK if avg.ev > 0.2 else Data.BAD)
    var kl_c: String = Data.GOOD if avg.kl < 0.03 else (Data.OK if avg.kl < 0.08 else Data.BAD)
    var cf_c: String = Data.GOOD if avg.clipfrac < 0.2 else (Data.OK if avg.clipfrac < 0.35 else Data.BAD)
    return Data.section("PPO HEALTH  (last %d updates)" % recent.size(), [
            ["critic explained variance", "[color=#%s][b]%.2f[/b][/color]  [color=#%s]higher is better[/color]" % [ev_c, avg.ev, Data.MUTED]],
            ["policy change (KL)", "[color=#%s][b]%.3f[/b][/color]  [color=#%s]about 0.01-0.03[/color]" % [kl_c, avg.kl, Data.MUTED]],
            ["updates clipped", "[color=#%s][b]%d%%[/b][/color]  [color=#%s]below 20%%[/color]" % [cf_c, roundi(avg.clipfrac * 100.0), Data.MUTED]],
            ["value loss / grad norm", "%.3f / %.2f" % [avg.vloss, avg.gradnorm]],
            ["entropy move / kick", "%.2f / %.2f" % [avg.ent_move, avg.ent_kick]]])


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
        s += Data.section("LEAGUE SUMMARY  (%d matches, points / match ± standard error)" % L.all[3], [
                ["all teams", "%s  [color=#%s]±%s  %.2f-%.2f[/color]" % [Data.points(L.all[0]), Data.MUTED, Data.num_text(L.all[4]), L.all[1], L.all[2]]],
                ["trained against", Data.points(L.get("train", [NAN])[0])], ["held-out teams", Data.points(L.get("held", [NAN])[0])],
                ["weak  /  average", "%s   %s" % [Data.points(L.get("weak", [NAN])[0]), Data.points(L.get("average", [NAN])[0])]],
                ["strong  /  elite", "%s   %s" % [Data.points(L.get("strong", [NAN])[0]), Data.points(L.get("elite", [NAN])[0])]]])
    var rows := []
    for name in e.h2h:
        var h: Array = e.h2h[name]
        rows.append(["vs " + name, "%dW %dD %dL   %s   [color=#%s]±%s[/color]" % [h[0], h[1], h[2], Data.points(h[3]), Data.MUTED, Data.num_text(h[6])]])
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
        t += Data.section("THE RUN", [["updates", "[b]%d[/b]  ·  %s of training" % [l.upd, Data.hms(data.total_elapsed())]],
                ["speed", "%.0f s/update  ·  %.0f updates/h" % [data.seconds_per_update(), 3600.0 / maxf(data.seconds_per_update(), 1.0)]],
                ["started from", data.fallback.get_file().get_basename()],
                ["status", "[color=#%s][b]%s[/b][/color]" % [data.state_colour(), data.state_text().to_lower()]]])
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
    var bc := data.best_checkpoint()
    if bc.is_empty():
        t += Data.section("BEST CHECKPOINT (league points)", [["update %d" % best.update, "%s pts/match   ·   %d evaluations so far" % [Data.num_text(best.all), rows.size()]]])
    else:
        t += Data.section("BEST CHECKPOINT (league points)", [[str(bc.checkpoint).trim_prefix(data.tag + "_"), "%s   ·   %d evaluations so far" % [Data.with_se(float(bc.pts), float(bc.get("se", NAN))), rows.size()]],
                ["file", "[color=#%s]%s_best.json[/color]" % [Data.MUTED, data.tag]]])
    t += "[color=#%s]ALL EVALUATIONS  (league ±error · RL4 · RL5 · jitter/s)   ▲ ▼ = beyond noise vs the previous[/color]\n[table=2]" % Data.MUTED
    var prev: Dictionary = {}
    for r in rows.slice(maxi(rows.size() - 8, 0)):
        var mark := ""
        if not prev.is_empty():
            var sg := Data.significance(r.all, r.all_se, prev.all, prev.all_se)
            mark = " [color=#%s]▲[/color]" % Data.GOOD if sg > 0 else (" [color=#%s]▼[/color]" % Data.BAD if sg < 0 else "")
        prev = r
        t += "[cell][color=#%s]u%d   [/color][/cell][cell]%s [color=#%s]±%s[/color]%s  %s %s  [color=#%s]%s[/color][/cell]" % [Data.MUTED, r.update, Data.points(r.all), Data.MUTED, Data.num_text(r.all_se), mark, Data.points(r.rl4), Data.points(r.rl5), Data.MUTED, Data.num_text(r.dir, "%.1f")]
    t += "[/table]\n"
    var changes := data.config_changes()
    if not changes.is_empty():
        t += "[color=#%s]REWARD CHANGES (at a restart)[/color]\n" % Data.MUTED
        for ch in changes:
            t += "u%d  %s\n" % [ch[0], ", ".join(ch[1])]
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
    t += Data.section("REWARD, shared by the 5 players", [
            ["goal scored / conceded", "[b]+10 / -10[/b]"], ["time cost", "-0.0005"],
            ["ball shaping", "[color=#%s]%s[/color]" % [Data.MUTED, "off" if float(c.get("shaping", 1.0)) == 0.0 else "on"]],
            ["opponent xG (chances)", "%s per xG" % _w(c, "w_xga", "-")], ["opponent has ball, our half", _w(c, "w_opp_half", "-")],
            ["team stretched", "%s  [color=#%s]%s x %s px[/color]" % [_w(c, "w_compact", "-"), Data.MUTED, _int(c, "compact_len"), _int(c, "compact_wid")]],
            ["win / draw bonus", "%s / %s" % [_w(c, "w_win", "+"), _w(c, "w_draw", "+")]]])
    t += Data.section("REWARD, personal: passing", [
            ["progressive pass", _w(c, "w_pass_prog", "+")], ["failed pass", _w(c, "w_pass_fail", "-")],
            ["other completed pass", _w(c, "w_pass_ok", "+")], ["pass received", _w(c, "w_recv", "+")],
            ["key pass", _w(c, "w_key_pass", "+")], ["expected assist", "%s x xA" % _w(c, "w_xa", "+")],
            ["cooperation cap / match", _w(c, "coop_cap", "")]])
    _text.text = t
    var d := "\n\n"
    d += Data.section("REWARD, personal: the rest", [
            ["shot quality", "%s per xG  [color=#%s]cap %s[/color]" % [_w(c, "w_xg", "+"), Data.MUTED, str(c.get("xg_cap", "?"))]],
            ["tackle / interception", "%s  [color=#%s]cap %s[/color]" % [_w(c, "w_tackle", "+"), Data.MUTED, str(c.get("def_cap", "?"))]],
            ["goal-side defending", _w(c, "w_goalside", "+")], ["standing open", _w(c, "w_open", "+")],
            ["teammate too close", _w(c, "w_space", "-")], ["too far from the ball", "%s  [color=#%s]> %s px[/color]" % [_w(c, "w_far", "-"), Data.MUTED, _int(c, "far_radius")]],
            ["kick away from ball", _w(c, "w_kick", "-")], ["keeper far from goal", _w(c, "w_keeper", "-")], ["direction twitch", _w(c, "w_jitter", "-")]])
    d += _observation_text(c)
    d += Data.section("ACTIONS", [["move", "9: 8 directions or still"], ["kick", "pressed or not"], ["decision", "every 2 ticks (30 / s)"], ["choice", "sampled, not argmax"]])
    _side.text = d
    var tr := "\n\n"
    var n_in := int(c.get("obs_dim", 54))
    tr += Data.section("NETWORK  (shared by all 5 players)", [["actor", "%d - 128 - 128 - 10" % n_in], ["critic", "%d - 128 - 128 - 1" % n_in]])
    tr += Data.section("TRAINING  (PPO)", [
            ["parallel matches", _matches(c)], ["steps / env / update", _int(c, "rollout")],
            ["epochs", _int(c, "epochs")], ["minibatch", _int(c, "minibatch")], ["learning rate", str(c.get("lr", "?"))],
            ["gamma / lambda", "%s / %s" % [c.get("gamma", "?"), c.get("lam", "?")]], ["entropy bonus", str(c.get("ent", "?"))],
            ["clip / grad clip", "0.2 / 0.5"]])
    tr += Data.section("EPISODES", [
            ["length", "90 s match, 5v5 arena"], ["random starts", "%s of episodes" % _percent(c.get("random_start", NAN))],
            ["started from", str(c.get("start", "?")).get_file()], ["opponents", "12 rule-based teams (4 held out), past snapshots, the start weights"]])
    _third.text = tr


## What the net sees, as in the run's settings: "team" = the 46-number role-free observation, otherwise the older 54-number ego one.
static func _observation_text(c: Dictionary) -> String:
    if str(c.get("obs", "legacy")) == "team":
        return Data.section("OBSERVATION  (46 numbers, 30 / s)", [
                ["me: position + speed", "4"], ["4 teammates, nearest first", "4 x 4 = 16"], ["5 opponents, nearest first", "5 x 4 = 20"],
                ["ball: position + speed", "4"], ["kickoff on", "1  (0 / 1)"], ["goal celebration on", "1  (0 / 1)"]]) \
                + "[color=#%s]Everything is scaled (positions by the pitch, speeds by 5). The same net plays all 5 players with no player ID: roles come from the situation.[/color]\n\n" % Data.MUTED
    return Data.section("OBSERVATION  (%d numbers, 30 / s)" % int(c.get("obs_dim", 54)), [
            ["own position + speed", "4"], ["ball position + speed", "4"], ["4 teammates", "4 x 4 = 16"], ["5 opponents", "5 x 4 = 20"],
            ["ball relative to me", "3"], ["opp. goal relative to me", "2"], ["my slot (one-hot)", "5"]])


static func _int(c: Dictionary, key: String) -> String:
    return str(int(c[key])) if c.has(key) else "?"


static func _w(c: Dictionary, key: String, sign: String) -> String:
    if not c.has(key):
        return "?"
    return "[color=#%s]off[/color]" % Data.MUTED if float(c[key]) == 0.0 else "[b]%s%s[/b]" % [sign, str(c[key])]


static func _matches(c: Dictionary) -> String:
    if not c.has("workers_rule"):
        return "?"
    return "%d  (%d+%d workers x %d)" % [(int(c.workers_rule) + int(c.workers_self)) * int(c.envs_per_worker), int(c.workers_rule), int(c.workers_self), int(c.envs_per_worker)]


static func _percent(v: Variant) -> String:
    return "?" if is_nan(float(v)) else "%d%%" % roundi(float(v) * 100.0)


# ---------------------------------------------------------------- insight

func _build_insight(row: HBoxContainer) -> void:
    var left := VBoxContainer.new()
    left.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    left.add_theme_constant_override("separation", 6)
    row.add_child(left)
    _text = _label(left, 14)
    _text.custom_minimum_size = Vector2(0, 250)
    for chart in [["TEAM REWARD TERMS over the run (per decision, smoothed)", ["goals", "xga", "result", "opp_half", "compact", "shaping", "time"]],
            ["PERSONAL REWARD TERMS", ["xg", "tackle", "goalside", "pass_prog", "pass_fail", "coop", "open", "space", "far", "kick", "keeper", "jitter"]]]:
        var c := LineChart.new()
        c.title = chart[0]
        c.x_key = "upd"
        c.fixed = null
        c.font_size = 11
        c.size_flags_vertical = Control.SIZE_EXPAND_FILL
        var series := []
        for k in chart[1]:
            series.append([k, _term_colour(k)])
        c.series = series
        left.add_child(c)
        _chart_nodes.append(c)
        c.set_meta("keys", chart[1])
    var right := VBoxContainer.new()
    right.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    right.add_theme_constant_override("separation", 6)
    row.add_child(right)
    _side = _label(right, 14)
    var grid := GridContainer.new()
    grid.columns = 3
    grid.add_theme_constant_override("h_separation", 8)
    grid.add_theme_constant_override("v_separation", 6)
    right.add_child(grid)
    for k in 6:
        var h := Heatmap.new()
        h.custom_minimum_size = Vector2(150, 112)
        h.size_flags_horizontal = Control.SIZE_EXPAND_FILL
        grid.add_child(h)
        _heatmaps.append(h)
    _third = _label(right, 14)


func _label(parent: Control, font_size: int) -> RichTextLabel:
    var l := RichTextLabel.new()
    l.bbcode_enabled = true
    l.scroll_active = false
    l.fit_content = true
    l.add_theme_font_size_override("normal_font_size", font_size)
    l.add_theme_font_size_override("bold_font_size", font_size)
    parent.add_child(l)
    return l


static func _term_colour(key: String) -> String:
    for t in TERMS:
        if t[0] == key:
            return t[2]
    return "ffffff"


func _insight() -> void:
    var hist := data.terms_history()
    for c in _chart_nodes:
        c.rows = data.smoothed_terms(c.get_meta("keys"))
    # --- reward breakdown (average of the last 10 updates)
    var t := "[b][font_size=20]INSIGHT  %s[/font_size][/b]\n" % data.tag
    if hist.is_empty():
        t += "\n[color=#%s]No reward log yet (logs/%s_terms.jsonl).\nTraining writes it every update; runs started before this page existed don't have it.[/color]" % [Data.MUTED, data.tag]
    else:
        var avg := {}
        var total := 0.0
        var recent: Array = hist.slice(maxi(hist.size() - 10, 0))
        for term in TERMS:
            var sum := 0.0
            for row in recent:
                sum += float(row.get(term[0], 0.0))
            avg[term[0]] = sum / recent.size()
            total += absf(avg[term[0]])
        t += "[color=#%s]WHAT THE REWARD IS MADE OF  (per 1000 decisions · share of total · last %d updates)[/color]\n[table=6]" % [Data.MUTED, recent.size()]
        var warn := ""
        var shown := 0
        for term in TERMS:
            var v: float = avg[term[0]]
            if v == 0.0:                          # switched off in this run
                continue
            var share: float = absf(v) / maxf(total, 1e-9) * 100.0
            t += "[cell][color=#%s]■ %s  [/color][/cell][cell][color=#%s]%+.1f[/color]  [/cell][cell][color=#%s]%d%%    [/color][/cell]" % [
                    term[2], term[1], Data.GOOD if v > 0.0 else Data.BAD, v * 1000.0, Data.MUTED, roundi(share)]
            shown += 1
            if term[0] == "coop" and share > 35.0:
                warn = "cooperation bonus is %d%% of the reward: check for farming (key passes, shots, keeper far from goal)" % roundi(share)
        if shown % 2 == 1:                        # keep the two-column table rectangular
            t += "[cell] [/cell][cell] [/cell][cell] [/cell]"
        t += "[/table]"
        if warn != "":
            t += "\n[color=#%s]%s[/color]" % [Data.OK, warn]
    _text.text = t
    # --- heatmaps and sampling vs best move, from the latest evaluation
    var evs := data.evaluations()
    if evs.is_empty():
        _side.text = "\n[color=#%s]WHERE THE PLAYERS ARE\nneeds a finished evaluation (every %d updates)[/color]" % [Data.MUTED, Data.EVAL_EVERY]
        _third.text = ""
        for h in _heatmaps:
            h.values = PackedFloat32Array()
            h.queue_redraw()
        return
    var e: Dictionary = evs[-1]
    _side.text = "\n[color=#%s]WHERE THE PLAYERS ARE  (%s, attacking to the right)[/color]" % [Data.MUTED, e.name.trim_prefix(data.tag + "_")]
    var names := ["0", "1", "2", "3", "4", "ball"]
    for k in 6:
        var h: Heatmap = _heatmaps[k]
        var hm: Dictionary = e.heat.get(names[k], {})
        h.title = "ball" if k == 5 else "%s  (slot %d)" % [hm.get("role", "?"), k]
        h.values = hm.get("v", PackedFloat32Array())
        h.grid_w = hm.get("w", 14)
        h.grid_h = hm.get("h", 8)
        h.queue_redraw()
    _third.text = _sampling_text(e)


## The same net sampling its moves (as in training) vs always playing its best move.
func _sampling_text(e: Dictionary) -> String:
    var g: Dictionary = e.greedy
    if g.teams.is_empty():
        return "\n[color=#%s]SAMPLING vs BEST MOVE: not in this evaluation[/color]" % Data.MUTED
    var ids := []
    var gpts := 0.0
    for team in g.teams:
        ids.append(team.id)
        gpts += team.pts
    gpts /= g.teams.size()
    var spts := 0.0
    var n := 0
    for team in e.teams:
        if team.id in ids:
            spts += team.pts
            n += 1
    spts /= maxf(n, 1)
    var rows := [["league points (%d teams)" % ids.size(), "%s  /  %s" % [Data.points(spts), Data.points(gpts)]]]
    for row in [["direction changes / s", "dir", "%.1f"], ["kick presses / s", "kick", "%.2f"], ["keeper from goal (px)", "keeper", "%.0f"], ["key passes / match", "key", "%.2f"]]:
        if e.rl.has(row[1]) and g.rl.has(row[1]):
            rows.append([row[0], "%s  /  %s" % [row[2] % e.rl[row[1]], row[2] % g.rl[row[1]]]])
    return "\n" + Data.section("SAMPLING  /  BEST MOVE  (the same net)", rows)
