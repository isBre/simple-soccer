#!/usr/bin/env python3
"""Generates the starter data (pitches, play styles) as JSON.
Re-run to regenerate; edit the JSON files directly to customise."""
import json, os, random

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
random.seed(2026)


def dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)
        f.write("\n")


# ------------------------------------------------------------------ pitches
pitches = {
    "classic": dict(id="classic", name="Classic", sizes=[1, 2, 3], half_w=370, half_h=170, goal_half=64,
                    net_depth=40, out_x=420, out_y=200, center_r=75, post_r=8, box_depth=0, box_half=0,
                    stripes=0, colors=dict(pitch="718c5a", outer="5b7347", line="c7e6bd")),
    "futsal": dict(id="futsal", name="Futsal", sizes=[1, 2], half_w=280, half_h=125, goal_half=55,
                   net_depth=35, out_x=325, out_y=160, center_r=60, post_r=7, box_depth=0, box_half=0,
                   stripes=0, colors=dict(pitch="4f7f9a", outer="3c6178", line="d4e8f2")),
    "big": dict(id="big", name="Big (5v5)", sizes=[4, 5], half_w=520, half_h=240, goal_half=90,
                net_depth=45, out_x=575, out_y=285, center_r=100, post_r=9, box_depth=130, box_half=150,
                stripes=10, colors=dict(pitch="5f8f4e", outer="466b3a", line="dcefd2")),
    "arena": dict(id="arena", name="Arena (5v5, large)", sizes=[4, 5], half_w=640, half_h=300, goal_half=115,
                  net_depth=55, out_x=700, out_y=355, center_r=120, post_r=10, box_depth=165, box_half=190,
                  stripes=12, colors=dict(pitch="58874a", outer="3f6034", line="e2f2d9")),
    "big_pillars": dict(id="big_pillars", name="Big with Pillars (5v5)", sizes=[4, 5], half_w=520, half_h=240,
                        goal_half=90, net_depth=45, out_x=575, out_y=285, center_r=100, post_r=9,
                        box_depth=130, box_half=150, stripes=10,
                        obstacles=[[0, -135, 18], [0, 135, 18], [-250, 0, 14], [250, 0, 14]],
                        colors=dict(pitch="6a7f55", outer="4d5e3e", line="dcefd2")),
}
for k, v in pitches.items():
    dump(os.path.join(ROOT, "pitches", k + ".json"), v)

# ------------------------------------------------------------------- styles
S = lambda **kw: kw
styles = {
    "balanced": S(name="Balanced", description="Solid all-round play, no big weaknesses.",
                  line_height=.5, compactness=.5, width=1.0, press=.5, marking=.4, directness=.5,
                  shoot_range=0.58, pass_bias=.6, risk=.4, keeper_sweep=.3, forward_stay=.3, support_dist=150, fluidity=0.6, attack_commit=0.4),
    "tiki_taka": S(name="Tiki-Taka", description="Short passes, high possession, patient build-up.",
                   line_height=.65, compactness=.75, width=.9, press=.55, marking=.3, directness=0.25,
                   shoot_range=0.58, pass_bias=0.8, risk=0.35, keeper_sweep=.5, forward_stay=.2, support_dist=130, fluidity=0.7, attack_commit=0.5),
    "high_press": S(name="High Press", description="Wins the ball high up the pitch with several chasers.",
                    line_height=.6, compactness=.8, width=1.0, press=.9, marking=.6, directness=.45,
                    shoot_range=.6, pass_bias=.6, risk=.5, keeper_sweep=.45, forward_stay=.2, support_dist=140, fluidity=0.6, attack_commit=0.6),
    "park_the_bus": S(name="Park the Bus", description="Deep block, tight marking, lets the opponent come.",
                      line_height=.15, compactness=.6, width=.8, press=.2, marking=.7, directness=.6,
                      shoot_range=0.55, pass_bias=.4, risk=.2, keeper_sweep=.1, forward_stay=.2, support_dist=150, fluidity=0.1, attack_commit=0.1),
    "counter_attack": S(name="Counter-Attack", description="Sits back, then breaks fast with forwards held high.",
                        line_height=.3, compactness=.45, width=1.0, press=.3, marking=.5, directness=.7,
                        shoot_range=.65, pass_bias=.55, risk=.6, keeper_sweep=.25, forward_stay=.85, support_dist=180, fluidity=0.5, attack_commit=0.35),
    "long_ball": S(name="Long Ball", description="Direct, long passes and early shots.",
                   line_height=.5, compactness=.4, width=1.0, press=.4, marking=.3, directness=0.9,
                   shoot_range=0.62, pass_bias=.55, risk=0.6, keeper_sweep=.3, forward_stay=0.5, support_dist=220, fluidity=0.4, attack_commit=0.3),
    "wing_play": S(name="Wing Play", description="Stretches the pitch and attacks down the flanks.",
                   line_height=.5, compactness=.6, width=1.35, press=.45, marking=.3, directness=.55,
                   shoot_range=0.6, pass_bias=.7, risk=.45, keeper_sweep=.3, forward_stay=.4, support_dist=170, fluidity=0.6, attack_commit=0.55),
    "total_football": S(name="Total Football", description="Fluid roles: anyone keeps goal, anyone attacks. High line, constant pressing.",
                        line_height=.6, compactness=.7, width=1.1, press=.7, marking=.4, directness=.3,
                        shoot_range=.6, pass_bias=.8, risk=.5, keeper_sweep=.45, forward_stay=.2, support_dist=140,
                        fluidity=0.8, attack_commit=.6),
    "catenaccio": S(name="Catenaccio", description="Fixed keeper, deep disciplined block, man-marking and sudden long strikes.",
                    line_height=.1, compactness=.65, width=.8, press=.15, marking=.9, directness=.65,
                    shoot_range=.55, pass_bias=.35, risk=.15, keeper_sweep=.05, forward_stay=.35, support_dist=170,
                    fluidity=0.0, attack_commit=.1),
    "all_out_attack": S(name="All-Out Attack", description="Everyone pushes forward, high risk, shoots on sight.",
                        line_height=.85, compactness=.6, width=1.2, press=.85, marking=.3, directness=.75,
                        shoot_range=.75, pass_bias=.5, risk=.85, keeper_sweep=.6, forward_stay=.1, support_dist=200,
                        fluidity=.85, attack_commit=1.0),
    "gegenpress": S(name="Gegenpress", description="Wins the ball back within seconds of losing it with extra chasers, then strikes.",
                    line_height=.7, compactness=.85, width=1.0, press=.85, marking=.5, directness=.4,
                    shoot_range=.6, pass_bias=.65, risk=.55, keeper_sweep=.4, forward_stay=.2, support_dist=140,
                    fluidity=.6, attack_commit=.55, counter_press=1.0),
    "sharpshooters": S(name="Sharpshooters", description="Shoots from distance as soon as a lane opens up.",
                       line_height=.5, compactness=.5, width=1.0, press=.4, marking=.4, directness=.5,
                       shoot_range=.9, pass_bias=.45, risk=.55, keeper_sweep=.3, forward_stay=.5, support_dist=170,
                       fluidity=.5, attack_commit=.4, long_shot=1.0),
    "man_to_man": S(name="Man-to-Man", description="Every outfield player sticks to an opponent and denies the pass.",
                    line_height=.45, compactness=.5, width=1.0, press=.5, marking=1.0, directness=.5,
                    shoot_range=.55, pass_bias=.55, risk=.4, keeper_sweep=.3, forward_stay=.1, support_dist=150,
                    fluidity=.3, attack_commit=.3, intercept=.6),
    "zone_trap": S(name="Zone Trap", description="Compact deep block that reads the ball path, cuts out passes and breaks quickly.",
                   line_height=.35, compactness=.8, width=.9, press=.25, marking=.5, directness=.6,
                   shoot_range=.58, pass_bias=.5, risk=.45, keeper_sweep=.2, forward_stay=.6, support_dist=170,
                   fluidity=.3, attack_commit=.3, intercept=1.0),
    "dribblers": S(name="Dribblers", description="Carries the ball and takes opponents on instead of passing.",
                   line_height=.55, compactness=.5, width=1.0, press=.5, marking=.4, directness=.3,
                   shoot_range=.55, pass_bias=.45, risk=.5, keeper_sweep=.3, forward_stay=.4, support_dist=110,
                   fluidity=.5, attack_commit=.45),
    "switch_play": S(name="Switch Play", description="Wide and patient: moves the ball to the far side to find space.",
                     line_height=.55, compactness=.5, width=1.3, press=.45, marking=.35, directness=.5,
                     shoot_range=.58, pass_bias=.65, risk=.5, keeper_sweep=.3, forward_stay=.35, support_dist=170,
                     fluidity=.6, attack_commit=.55, switch_play=.5),
}
INTERCEPT = dict(balanced=.5, tiki_taka=.4, high_press=.5, park_the_bus=.7, counter_attack=.6, long_ball=.4,
                 wing_play=.4, total_football=.5, catenaccio=.8, all_out_attack=.2)
for k, v in styles.items():
    v.setdefault("intercept", INTERCEPT.get(k, .5))
    v.setdefault("counter_press", 0.0)
    v.setdefault("long_shot", 0.0)
    v.setdefault("switch_play", 0.3 if k == "wing_play" else 0.0)
    v["id"] = k
    dump(os.path.join(ROOT, "styles", k + ".json"), v)

# Teams and players are curated by hand since 2026-11-27 (data/teams: line-ups; data/players: rule-based, Opus and net
# players, see README "Players, teams and kickoff"); this script no longer writes them.
print("generated", len(pitches), "pitches,", len(styles), "styles (teams and players: edit data/teams and data/players)")
