#!/usr/bin/env python3
"""Generates the pitches (data/pitches) as JSON.
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

# Teams and players are curated by hand since 2026-11-27 (data/teams: line-ups; data/players: rule-based archetypes and net
# players, see README "Players, teams and kickoff"); this script only writes the pitches.
print("generated", len(pitches), "pitches (teams and players: edit data/teams and data/players)")
