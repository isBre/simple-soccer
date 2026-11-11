# RL training (Python PPO <-> headless Godot)

The AI controls **all 5 players of a team, keeper included**, with one shared policy and a slot one-hot
input (54 inputs), so roles and formation are learned, not scripted. The actor has the game's `MLP` layout
(`[54, h, h, 10]`: 9 move logits + 1 kick logit) and is exported as game model JSON; `MLBot` plays it as is.

- `rl_env.gd` / `rl_server.gd`: environment + TCP bridge (several envs per Godot process).
- `client.py`: vector env over N Godot workers. `ppo.py`: PPO + curriculum + model export.
- `league_eval.gd`: plays a model against all 16 teams on both sides (full matches, game code path) and
  writes `teams_info.json` (strengths, tiers, 4 held-out teams that are never trained against).
- `eval_model.gd`: quick check of an exported model on the first-goal scenarios.

Curriculum: empty goal -> rule-based keeper -> full 90 s matches vs weak / average / strong training teams.

```bash
python3 -m venv ~/rl-venv && ~/rl-venv/bin/pip install torch numpy --index-url https://download.pytorch.org/whl/cpu
# godot 4.6 at ~/godot/Godot_v4.6-stable_linux.x86_64 ; import once: godot --headless --path . --import
~/rl-venv/bin/python rl/ppo.py --stages s4_five_empty s5_vs_keeper s6_weak s7_average s8_strong
godot --headless --path . res://rl/league_eval.tscn -- --model res://out_5v5/rl_s8_strong_last.json --games 2
```

## Self-play and cooperation fine-tuning

`selfplay.py` continues from a trained `.pt` (`--start`). Team 0 (the learner) plays full 90 s matches against two groups of
Godot workers: rule-based teams, and a Python-controlled opponent (slot 0 = frozen start model, other slots = past snapshots of
the learner, resampled every 20 updates). Checkpoints: `out_5v5/ckpt/<tag>_u<N>.json/.pt`.

```bash
# cooperation fine-tune (anti-farming settings used for the coop3 run)
~/rl-venv/bin/python rl/selfplay.py --start out_5v5/ckpt/coop_u600.pt --tag coop3 --updates 1200 \
  --pass_individual 1 --w_recv 0.1 --w_open 0.003 --w_key_pass 0.15 --w_xa 1.5 --coop_cap 3 --w_keeper 0.006 --random_start 0.6 --eval_every 99999
godot --headless --path . res://rl/behaviour_stats.tscn -- --model res://out_5v5/ckpt/coop3_u600.json   # jitter, passes, key passes, spacing, keeper distance
godot --headless --path . res://rl/league_eval.tscn -- --model res://out_5v5/ckpt/coop3_u600.json --games 2
```

Reward terms (per agent, `rl_env.gd`): goals, ball/goal shaping, `--w_space` (spacing), `--w_kick` (kick discipline),
`--pass_individual` with `--w_recv` / `--w_key_pass` / `--w_xa` (pass credit goes to the passer and receiver),
`--w_open` (standing open for the ball carrier), `--coop_cap` (max cooperation reward per match) and `--w_keeper`
(keeper straying from its goal). `--random_start P` starts a fraction P of the episodes from a completely random layout
(all 10 players incl. keepers and the ball anywhere, play on immediately) instead of a kickoff, to generalise over situations. Without the cap and the keeper term the policy learned to farm key passes and
shots (40+ key passes and 50+ shots per match, keeper 770 px from its goal): always check `behaviour_stats`, not just the league.
Results: `results_league_final.txt`, `results_selfplay.txt`.
