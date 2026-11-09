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
