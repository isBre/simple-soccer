# Setup: one machine runs everything

One machine trains, runs the experiment queue, serves the dashboard (port 8080) with the live demo match, keeps the ratings
(`local/elo.db`) and commits the specs, results and notebook (`exp/`, `docs/`). Agents and people add, move and cancel specs on it with
`python3 lab/lab.py queue ...` (AGENTS.md).

## Once
```
git clone https://github.com/isBre/simple-soccer.git && cd simple-soccer     # needs git-lfs: brew install git-lfs && git lfs install
python3 -m venv .venv && .venv/bin/pip install -e '.[train]'                 # the project as an installed package
source .venv/bin/activate                                                    # every new terminal; the commands below assume it
sh .githooks/install.sh                                                      # the tests before a push that changes code
python3 -m elo init                                                          # the ratings database of this machine (docs/ratings.md)
```
Checkpoints (`out_5v5/`), logs (`logs/`) and the ratings database (`local/`) are not in git: a fresh clone starts without them.

## Every time
```
lab/run.sh                     # the runner (background QoS, no idle sleep), the health sampler and the thermal guard (.venv/bin/python)
python3 web/app.py             # the dashboard and the game: http://localhost:8080 (#/ = Lab, #/game = Game)
```
Stop the runner with `pkill -f lab/exp_runner.py`. Nothing restarts after a reboot or a sleep: start `lab/run.sh` again and the runner
resumes the running experiment from its last checkpoint. `lab/run.sh` runs the queue once and exits; `lab/exp_runner.py --loop` keeps
waiting for specs and plays Elo ladder rounds while the queue is empty (`touch local/refine_off` stops them and the web app's refining).
The training defaults (`workers_rule 2`, `envs_per_worker 16`, `learn_threads 2`) are small; a spec may set larger values in `args`
(they change speed, not what is learned).

## Speed and heat (fanless MacBook Air M4, measured 2026-11-21)
`lab/run.sh` runs everything in macOS background mode (`taskpolicy -b`): efficiency cores only. The same Python work costs about
3.6 times less energy there than on a performance core (1.0 J vs 3.6 J for one test loop), so the long simulation stays there.
- The match core, the rule AI and the observations do less work per step (same numbers bit for bit: a fingerprint of every
  observation, reward and position over 28,000 env steps and 24 full matches is unchanged): env workers about 25% faster, evaluations
  and ladder matches about 15%.
- `selfplay.py --trainer_fg 1` (default): the trainer process leaves background mode once its env workers are started. It only works
  in short bursts (the nets between two env steps, the learning step: 0.1 s instead of 0.6-1.0 s) and the workers no longer wait for
  it. Env workers and evaluations stay in background mode. `--trainer_fg 0` keeps the trainer there too (the coolest setting).
- `lab/thermal_guard.py` (started by `lab/run.sh`, `lab/run.sh MAX RESUME`, defaults 33 and 32 °C of battery temperature) pauses the
  runner and its workers above MAX and resumes them at RESUME.

16 updates of the rank_persist recipe, energy of the trainer and its workers (`proc_pid_rusage`; the whole machine draws about 15 W):

| | time | energy | power |
|---|---|---|---|
| before | 78 s | 44 J | 0.6 W |
| now, `--trainer_fg 0` | 51-60 s | 35-38 J | 0.6-0.7 W |
| now, `--trainer_fg 1` | 34-41 s | 47-50 J | 1.2-1.4 W |

The training is the same (same rewards and entropy at every update; the options change speed, not what is learned). Other jobs on the
efficiency cores (6 of them) slow the run down the most: check `ps -Ao pcpu,nice,command -r | head` before a long run.
