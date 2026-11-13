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
# godot 4.6 at ~/godot/Godot_v4.6-stable_linux.x86_64 (or ..._linux.arm64 on a Raspberry Pi; client.py picks by machine type)
# import once: godot --headless --path . --import
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

`--w_jitter W` penalises a move direction that turns by more than ~60 degrees between two decisions (anti-twitch: the earlier teams changed direction ~11 times per second, the rule bots ~2). It is unproven: check `behaviour_stats` (direction changes per second) on a checkpoint before relying on it.

## Running on a Raspberry Pi 4 (4 cores, 3.7 GB)

Tested setup, `jit` runs of Nov 2026:
- Godot 4.6 `linux.arm64` build; Python venv with **torch 2.5.1** (`pip install torch==2.5.1 "numpy<2"`). The newest torch wheel (2.15) crashed with "illegal instruction" in the multi-threaded backward pass on this CPU.
- The `.pt` checkpoints are not in git (`*.pt` is ignored). To start from a shipped model, convert its JSON (`data/models/*.json`: actor weights only, so the critic starts fresh and the first updates are noisy) into a `.pt` through `ppo.Agent` and `load_state_dict`.
- Used for the `jit*` runs: `--workers_rule 3 --workers_self 1 --envs_per_worker 16 --minibatch 4096`. The limit is CPU, not memory (about 1.5 GB used): the Python loop steps all envs in turn and the PPO step uses all cores. Rollouts use one torch thread (tiny batches; more threads only steal CPU from the Godot workers), the learning step uses all of them.
- Run training at low priority (`nice -n 15`) when watching it live (below), so the viewer keeps its frame rate.

```bash
nice -n 15 ~/rl-venv/bin/python rl/selfplay.py --start out_5v5/ckpt/jit3_u50.pt --baseline out_5v5/rl_v5_start.pt --tag jit6 \
  --workers_rule 3 --workers_self 1 --envs_per_worker 16 --minibatch 4096 --ckpt_every 25 --log_every 2 \
  --pass_individual 1 --w_recv 0.1 --w_open 0.003 --w_key_pass 0.25 --w_xa 2.5 --coop_cap 8 --w_keeper 0.006 --random_start 0.6 --w_jitter 0.004 \
  > logs/jit6.out 2>&1 &
```

## Evaluation inside the run (`rl/eval_checkpoint.py`)

`selfplay.py --eval_every 100` (default; a multiple of `--ckpt_every`, 0 = never) starts a **complete evaluation of every Nth checkpoint** in the background, at the lowest priority, one at a time
(a new one is skipped while the previous still runs). It writes `logs/sp_eval/<tag>_u<N>.txt` (only once it is complete; last line `DONE <seconds>`):
1. **League**: all 16 rule-based teams, both sides (`league_eval.gd`): pts/match and goals per team, per tier, trained-against vs held-out teams. `--eval_games` (default 1 = 32 matches), `--eval_duration` (default 90 s per match; the shipped league numbers used 180 s).
2. **Behaviour** (`behaviour_stats.gd`): direction changes/s (the anti-twitch metric), kick presses, spacing, keeper distance, passes and pass accuracy, key passes, shots, next to the same numbers for the rule bots.
3. **Head to head** (`h2h_eval.gd`) against RL Team 4 and RL Team 5 (the previous shipped nets), both sides, `--eval_h2h_games` games per side.

All three run the nets in numpy servers (`--remote PORT` in the Godot scripts, `tools/net_server.py`, `RemoteMLP`): the GDScript MLP is too slow on a Raspberry Pi to evaluate a checkpoint in reasonable time.
Cost on a Pi 4 next to training: about 25-30 minutes of background CPU per evaluation with the defaults (a quick test with 20 s matches took 6 minutes). Run it by hand on any checkpoint:
`python3 rl/eval_checkpoint.py --model out_5v5/ckpt/x.json --out logs/sp_eval/x.txt [--games 1] [--duration 90] [--h2h_games 3]`.
`selfplay.py` also writes `logs/<tag>_config.json` (all its settings) at start, which the viewer's SETUP page reads.

## Watching training live (`tools/watch_training.tscn`, touch screen, no keyboard)

A window (needs a display) with a navigation bar of big touch buttons (nothing needs a keyboard):
- **LIVE**: endless matches of the newest checkpoint against RL Team 4 next to a compact sidebar (status, points per match, checkpoints, machine load, a chart). The match is paused while another page is shown.
- **TRAINING**: update, speed, points per match (vs rule-based teams / the start weights / past snapshots), reward, entropy, pool, sim/learn time, checkpoints (playing, newest, next checkpoint and next evaluation with estimated time), CPU load, temperature, memory, FPS, and charts of points, reward and entropy over the run.
- **EVALUATION**: the latest complete evaluation: every team (held-out marked), league summary by tier, head to head, behaviour vs the rule bots.
- **RECAP**: the whole run: updates, time, speed, first -> latest evaluation (league points, vs RL Team 4 / 5, direction changes, key passes, keeper distance), the best checkpoint, all evaluations, and charts across evaluations.
- **SETUP**: the rewards with their weights, the observation (54 numbers), actions, network, PPO settings, episodes and opponents (read from the run's config file).

Code: `training_data.gd` (parsing of the log, checkpoints and evaluations, machine info; no UI), `training_page.gd` (full pages), `training_sidebar.gd` (compact panel), `line_chart.gd`, `watch_training.gd/.tscn` (navigation and the match). The numbers come from `logs/<tag>.out` and `logs/sp_eval/`, so it works while training runs in another process.
`CKPT_EVERY` / `EVAL_EVERY` in `training_data.gd` must match the run's `--ckpt_every` / `--eval_every` (only used for "next checkpoint / evaluation" estimates).

Why a Python server: playing two net teams with the game's GDScript `MLP` ran at about 4 FPS on a Pi (about 300 forward passes per second of 25k multiply-adds each).
`tools/net_server.py` runs the nets in numpy; `scripts/ml/remote_mlp.gd` (`RemoteMLP`, an `MLP` whose `forward` asks the server) plugs into `MatchConfig.ml_models`.
The server loads the newest `<tag>_u*.json` each time a match connects, so every match uses the latest weights (before the first checkpoint it plays `--model`).

```bash
python3 tools/net_server.py --port 7301 --tag jit7 --model out_5v5/ckpt/jit6_u75.json &      # newest checkpoint of the run
python3 tools/net_server.py --port 7302 --model data/models/rl_5v5_arena_v4.json &            # the opponent (RL Team 4)
godot --path . res://tools/watch_training.tscn -- --tag jit7 --start res://out_5v5/ckpt/jit6_u75.json [--page training]   # --start = the server's --model
```

Frame rate: capped at 30 FPS (physics keeps 60 ticks/s) and without goal confetti (`MatchScreen.set_effects(false)`; the normal game is unchanged).
`MatchView` draws the static pitch once in a layer behind the players and paints the background without overdraw: that, not the nets, was the cost left on the Pi GPU (about 36 -> 60 FPS).
`tools/bench_sim.tscn` is a headless benchmark (ticks/s with rule bots and with remote nets, observation and net latency) to see where time goes before optimising.
A match screen added after the first one must be sized explicitly (`set_anchors_and_offsets_preset`), otherwise it stays 0x0.
