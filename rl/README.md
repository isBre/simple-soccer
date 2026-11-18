# RL training (Python PPO on the match core)

Training and evaluation of the net teams. Everything runs on the Python match core (`soccer/`), no Godot. The experiment
pipeline that runs these scripts unattended on the Pi (queue, runner, dashboard) is in [`lab/`](../lab/README.md).

The AI controls **all 5 players of a team, keeper included**, with one shared policy, so roles and formation are learned, not scripted.
The actor has the game-model layout (`[n_in, h, h, 10]`: 9 move logits + 1 kick logit) and is exported as game model JSON; the match core (`soccer/ai/nets.py`) plays it as is.
Two observation layouts exist (`selfplay.py --obs`, `env.py` config `obs`, chosen by the net's input size in `soccer/ai/nets.py` `features_for`):
- **`team` (46 numbers, default for new runs, no player ID):** me (position and speed), my 4 teammates nearest first, the 5 opponents nearest first, the ball (position and speed),
  kickoff on (0/1), goal celebration on (0/1). Positions are scaled by the pitch, speeds by 5, the pitch is mirrored so the team attacks to the right. Sorting by distance instead of by
  slot keeps a player from knowing a "role": it acts on the situation (see `features_team` in `soccer/ai/nets.py`).
- **`legacy` (54 numbers):** me first, ball, the 4 teammates and 5 opponents in slot order, ball and opponent goal relative to me, and a one-hot of the player's slot. The first RL teams (RL Team 1-5) use it.

- `env.py`: the environment (episodes, random starts, every reward term) on the match core (`soccer/`); no Godot.
  An exact copy of the earlier Godot environment (`tests/test_env.py`).
- `client.py`: vector env over N worker processes (several envs each). `ppo.py`: PPO + curriculum + model export.
- `evaluate.py league_eval`: plays a model against all 16 teams on both sides (full matches, all cores) and
  writes `teams_info.json` (strengths, tiers, 4 held-out teams that are never trained against).

Curriculum: empty goal -> rule-based keeper -> full 90 s matches vs weak / average / strong training teams.

```bash
python3 -m venv ~/rl-venv && ~/rl-venv/bin/pip install torch numpy --index-url https://download.pytorch.org/whl/cpu
~/rl-venv/bin/python rl/ppo.py --stages s4_five_empty s5_vs_keeper s6_weak s7_average s8_strong
~/rl-venv/bin/python rl/evaluate.py league_eval --model res://out_5v5/rl_s8_strong_last.json --games 2
```

## New observation, warm start by imitation (`rl/distill.py`)

A net with another observation cannot continue from an old checkpoint, so `distill.py` copies the old net into the new layout: the teacher plays (observation `both` from `env.py`
gives both layouts of every state), the student learns its move distribution, kick probability and value estimate, then **DAgger rounds** let the student play and the teacher label the states
the student really reaches (plain imitation alone gave a student that agreed 85% with the teacher but scored 0.9 instead of 2.9 league points per match).
`python3 rl/distill.py --teacher out_5v5/ckpt/jit8_best.pt --out team46_start --rounds 4` writes `out_5v5/team46_start.pt/.json`; start the run with `selfplay.py --obs team --start out_5v5/team46_start.pt`.
The net server announces the net's input size when the match core connects, so nets of both layouts can play side by side (evaluation against RL Team 4 / 5 works unchanged).

## Self-play and cooperation fine-tuning

`selfplay.py` continues from a trained `.pt` (`--start`). Team 0 (the learner) plays full 90 s matches against two groups of
env workers: rule-based teams, and a Python-controlled opponent (slot 0 = frozen start model, other slots = past snapshots of
the learner, resampled every 20 updates). Checkpoints: `out_5v5/ckpt/<tag>_u<N>.json/.pt`.

```bash
# cooperation fine-tune (anti-farming settings used for the coop3 run)
~/rl-venv/bin/python rl/selfplay.py --start out_5v5/ckpt/coop_u600.pt --tag coop3 --updates 1200 \
  --pass_individual 1 --w_recv 0.1 --w_open 0.003 --w_key_pass 0.15 --w_xa 1.5 --coop_cap 3 --w_keeper 0.006 --random_start 0.6 --eval_every 99999
~/rl-venv/bin/python rl/evaluate.py behaviour_stats --model res://out_5v5/ckpt/coop3_u600.json   # jitter, passes, key passes, spacing, keeper distance
~/rl-venv/bin/python rl/evaluate.py league_eval --model res://out_5v5/ckpt/coop3_u600.json --games 2
```

Reward terms (per agent, `env.py`): goals, ball/goal shaping, `--w_space` (spacing, only while our team has the ball), `--w_kick` (kick discipline),
`--pass_individual` with `--w_recv` / `--w_key_pass` / `--w_xa` (pass credit goes to the passer and receiver),
`--w_open` (standing open for the ball carrier), `--coop_cap` (max cooperation reward per match) and `--w_keeper`
(keeper straying from its goal). `--random_start P` starts a fraction P of the episodes from a completely random layout
(all 10 players incl. keepers and the ball anywhere, play on immediately) instead of a kickoff, to generalise over situations. Without the cap and the keeper term the policy learned to farm key passes and
shots (40+ key passes and 50+ shots per match, keeper 770 px from its goal): always check `behaviour_stats`, not just the league.
Results of the first teams: `docs/history/results_league_final.txt`, `docs/history/results_selfplay.txt`.

`--w_jitter W` penalises a move direction that turns by more than ~60 degrees between two decisions (anti-twitch: the earlier teams changed direction ~11 times per second, the rule bots ~2). It is unproven: check `behaviour_stats` (direction changes per second) on a checkpoint before relying on it.

## Running on a Raspberry Pi 4 (4 cores, 3.7 GB)

Tested setup, `jit` runs of Nov 2026:
- Python venv with **torch 2.5.1** (`pip install torch==2.5.1 "numpy<2"`). The newest torch wheel (2.15) crashed with "illegal instruction" in the multi-threaded backward pass on this CPU.
- The `.pt` checkpoints are not in git (`*.pt` is ignored). To start from a shipped model, convert its JSON (`data/models/*.json`: actor weights only, so the critic starts fresh and the first updates are noisy) into a `.pt` through `ppo.Agent` and `load_state_dict`.
- Used for the `jit*` runs: `--workers_rule 3 --workers_self 1 --envs_per_worker 16 --minibatch 4096`. The limit is CPU, not memory (about 1.5 GB used): the Python loop steps all envs in turn and the PPO step uses all cores. Rollouts use one torch thread (tiny batches; more threads only steal CPU from the env workers), the learning step uses all of them.
- Run training at low priority (`nice -n 15`) next to the live demo match (`lab/live.py`), so the demo keeps real time.

```bash
nice -n 15 ~/rl-venv/bin/python rl/selfplay.py --start out_5v5/ckpt/jit3_u50.pt --baseline out_5v5/rl_v5_start.pt --tag jit6 \
  --workers_rule 3 --workers_self 1 --envs_per_worker 16 --minibatch 4096 --ckpt_every 25 --log_every 2 \
  --pass_individual 1 --w_recv 0.1 --w_open 0.003 --w_key_pass 0.25 --w_xa 2.5 --coop_cap 8 --w_keeper 0.006 --random_start 0.6 --w_jitter 0.004 \
  > logs/jit6.out 2>&1 &
```

## Evaluation inside the run (`rl/eval_checkpoint.py`)

`selfplay.py --eval_every 100` (default; a multiple of `--ckpt_every`, 0 = never) runs a **complete evaluation of every Nth checkpoint** and **pauses training meanwhile**
(the env workers just wait), so the evaluation gets the whole CPU; the dashboard shows that an evaluation is running. Run in the background at the lowest priority
next to training it was starved on a Pi 4: the same evaluation took hours instead of about half an hour. It writes `logs/sp_eval/<tag>_u<N>.txt` (only once it is complete; last line `DONE <seconds>`):
1. **League**: all 16 rule-based teams, both sides (`evaluate.py league_eval`): pts/match and goals per team, per tier, trained-against vs held-out teams. `--eval_games` (default 1 = 32 matches), `--eval_duration` (default 90 s per match; the shipped league numbers used 180 s).
2. **Behaviour** (`evaluate.py behaviour_stats`): direction changes/s (the anti-twitch metric), kick presses, spacing, keeper distance, passes and pass accuracy, key passes, shots, next to the same numbers for the rule bots.
3. **Head to head** (`evaluate.py h2h_eval`) against RL Team 4 and RL Team 5 (the previous shipped nets), both sides, `--eval_h2h_games` games per side (default 8: the rule-bot league saturates at about 3.0 points, so these two are what tells checkpoints apart; 6 matches gave a standard error of about 0.5).
4. **Sampling vs best move**: the same net playing its best move (`net_temperature` 0, `--greedy` in `evaluate.py`) instead of sampling, on every 2nd team (`--stride 2`, written with a `greedy ` prefix) plus the behaviour numbers. In the first test the net made about 2.4 direction changes/s when playing its best move against about 14 when sampling (rule bots about 2.2): the twitching comes from sampling, not from what the net has learned (short 10 s matches, to be confirmed on real evaluations).
5. **Heatmaps**: where each player slot and the ball spend their time (`HEAT` lines from `behaviour_stats`, team attacking to the right).
6. **Scouting** (`SCOUT` line from `behaviour_stats`, JSON): team shape in and out of possession by depth rank (who is really the deepest / most advanced player: with no
   fixed roles the slot means nothing), how often the goal is guarded or empty, pressing distance and PPDA, possession, field tilt, and located events (shots for and against
   with xG, completed passes between slots, tackles / interceptions / loose balls). The events come from `Match.log_events` (soccer/match.py) (off in games and training; on only here).
   `eval_checkpoint.py --mode scout` runs just this part (about 2 minutes) for any net, e.g. RL Team 4/5 as references. The dashboard shows it on a run's Scouting tab.
Every league and head-to-head number carries its standard error (`se`, and `gd` / `gdse` for the goal difference per match; points per match are 3 / 1 / 0, so 32 matches give about +-0.2): a difference smaller than about two standard errors is noise,
the dashboard marks changes beyond noise between evaluations. The matches use fixed seeds, so every checkpoint plays the same kickoffs.
After each evaluation `eval_checkpoint.py` keeps the **best checkpoint** by league points (`out_5v5/ckpt/<tag>_best.json/.pt`, `logs/<tag>_best.json`).
`python3 rl/export_team.py --tag jit8 --number 6` turns it (or `--checkpoint jit8_u300`) into a playable "RL Team 6" (`data/models/rl_5v5_arena_v6.json`, `data/teams/rl_team_6.json`).
An evaluation that hangs is killed after 3 hours (`TIMEOUT` line) so it cannot block later evaluations.

All three serve the nets from numpy servers (`--remote PORT` in `evaluate.py`, `rl/net_server.py`); the match core builds the observations and asks them for the outputs.
Cost on a Pi 4 with the CPU free: about 25-30 minutes with the defaults (a quick test with 20 s matches took 6 minutes). Run it by hand on any checkpoint:
`python3 rl/eval_checkpoint.py --model out_5v5/ckpt/x.json --out logs/sp_eval/x.txt [--games 1] [--duration 90] [--h2h_games 3]`.
Numbering across restarts: `--start_update N --updates TOTAL` continues a run (checkpoint names, logs and charts keep counting; append to the log with `>>`).
`selfplay.py` also writes `logs/<tag>_ppo.jsonl` (PPO health per update: critic explained variance, approx. KL, clip fraction, value loss, gradient norm, entropy of the move and kick heads;
shown on the dashboard's Training tab) and `logs/<tag>_config.json` (all its settings) at start, which the dashboard's Config tab reads, and `logs/<tag>_terms.jsonl` (one line per update:
what the reward was made of, per reward term, mean per agent-decision). The terms are accumulated in `env.py` (`_acc`) and read from the workers with the `T` command (`VecEnv.terms()`).

## Net server (`rl/net_server.py`)

`eval_checkpoint.py` serves the nets it evaluates from small numpy servers; the match core connects to one for a team whose
`MatchConfig.nets` entry is `{"port": n}` (`--remote PORT` in `evaluate.py`). `--tag TAG` serves the newest `<tag>_u*.json` each time a
match connects; `--best-file` the run's best checkpoint. The server pins numpy/OpenBLAS to one thread (the venv's OpenBLAS otherwise
spun 28 threads and starved the simulation).

## Speed

`python3 tools/bench.py` measures the match core: sim ticks/s of rule-vs-rule matches and training-environment steps/s.
