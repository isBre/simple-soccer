# Training on the Mac, showing it on the Pi

The Mac trains (`lab/exp_runner.py --loop`, no `--viewer`); the Pi keeps the dashboard (`http://10.0.0.75:8080`), the live demo match and the
kiosk, and plays the Mac's newest checkpoints. Agents and people still add, move and cancel specs on the Pi (`python3 lab/lab.py queue ...`);
`lab/mac_sync.py` carries everything both ways every minute. Specs, results and the notebook are committed **from the Pi** (the Mac's `exp/`
is a working copy: do not commit it there).

## Mac, once
```
git clone https://github.com/isBre/simple-soccer.git && cd simple-soccer     # needs git-lfs: brew install git-lfs && git lfs install
python3 -m venv ~/rl-venv && ~/rl-venv/bin/pip install numpy torch
# checkpoints and logs the specs start from (checkpoints only, not the big *.train_state files; ~100 MB)
mkdir -p out_5v5 logs && rsync -a --exclude='*.train_state' isbre@10.0.0.75:simple-soccer/out_5v5/ out_5v5/
rsync -a isbre@10.0.0.75:simple-soccer/exp/ exp/          # the Pi's exp/ is the newest (results, runs, ladder)
rsync -a --include='x_*.out' --include='sp_eval/***' --exclude='*' isbre@10.0.0.75:simple-soccer/logs/ logs/
```
Key login to the Pi must work (`ssh isbre@10.0.0.75` without a password; `ssh-copy-id isbre@10.0.0.75`).

## Mac, every time (two terminals)
```
caffeinate -i ~/rl-venv/bin/python lab/exp_runner.py --loop          # the runner; caffeinate keeps the Mac awake
python3 lab/mac_sync.py --pi isbre@10.0.0.75                         # the sync, every 60 s
```
The Pi's Elo ladder rounds then run on the Mac too (`touch exp/ladder_off` there to stop them). The training defaults (`workers_rule 2`,
`envs_per_worker 16`, `learn_threads 2`) were chosen for the Pi's 4 cores; on a Mac with more cores a spec may set larger values in `args`
(they change speed, not what is learned).

## Speed and heat (fanless MacBook Air M4, measured 2026-11-21)
`lab/mac_run.sh` runs everything in macOS background mode (`taskpolicy -b`): efficiency cores only. The same Python work costs about
3.6 times less energy there than on a performance core (1.0 J vs 3.6 J for one test loop), so the long simulation stays there.
- The match core, the rule AI and the observations do less work per step (same numbers bit for bit: a fingerprint of every
  observation, reward and position over 28,000 env steps and 24 full matches is unchanged): env workers about 25% faster, evaluations
  and ladder matches about 15%.
- `selfplay.py --trainer_fg 1` (default): the trainer process leaves background mode once its env workers are started. It only works
  in short bursts (the nets between two env steps, the learning step: 0.1 s instead of 0.6-1.0 s) and the workers no longer wait for
  it. Env workers and evaluations stay in background mode. `--trainer_fg 0` keeps the trainer there too (the coolest setting).

16 updates of the rank_persist recipe, energy of the trainer and its workers (`proc_pid_rusage`; the whole Mac draws about 15 W):

| | time | energy | power |
|---|---|---|---|
| before | 78 s | 44 J | 0.6 W |
| now, `--trainer_fg 0` | 51-60 s | 35-38 J | 0.6-0.7 W |
| now, `--trainer_fg 1` | 34-41 s | 47-50 J | 1.2-1.4 W |

The training is the same (same rewards and entropy at every update; the options change speed, not what is learned). Other jobs on the
efficiency cores (6 of them) slow the run down the most: check `ps -Ao pcpu,nice,command -r | head` before a long run.

## Pi, once (then the Pi no longer trains)
```
sudo cp lab/systemd/soccer-exp-viewer.service /etc/systemd/system/ && sudo systemctl daemon-reload
sudo systemctl disable --now soccer-exp && sudo systemctl enable --now soccer-exp-viewer
```
`soccer-exp-viewer` runs `exp_runner.py --viewer-only`: only the live demo (the screen shows it through `soccer-kiosk`), following the experiment that is current in the
synced `exp/runs/*/status.json`. The Lab pages show the Mac's results; the "Pi" page and the vitals still show the Pi itself.
Back to training on the Pi: `sudo systemctl disable --now soccer-exp-viewer && sudo systemctl enable --now soccer-exp`.
