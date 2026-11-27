# Lab: experiment pipeline and dashboard

Runs the training experiments unattended on the Raspberry Pi and shows them on a web page. It drives the training scripts in
[`rl/`](../rl/README.md), which run on the match core (`soccer/`). No Godot is involved. Agents: start with [AGENTS.md](../AGENTS.md).

| File | What |
|---|---|
| `exp_runner.py` | the runner (service `soccer-exp`): queue -> train -> estimated Elo every 50 updates -> full evaluation -> best checkpoint into the Elo ladder |
| `tracker.py` | the shared file formats in `exp/` (results, statuses, specs, defaults `MINIMAL` / `DEFAULTS`) |
| `lab.py` | the agent CLI (read-only views, queue edits); `/api/v1` of the dashboard serves the same |
| `dashboard.py` | the Lab's JSON API; the web app (`web/app.py`, service `soccer-dashboard`, port 8080) serves it, the pages are `web/lab/*.js` |
| `live.py` | the dashboard's live demo match (newest checkpoint vs a random or picked opponent, real time) |
| `mac_sync.py`, [`MAC.md`](MAC.md) | training on a Mac while the Pi only shows it: the sync script (Mac -> Pi results and checkpoints, Pi -> Mac queue and cancels) and `exp_runner.py --viewer-only` (service `soccer-exp-viewer`) |
| `pi_health_log.sh` | one health line every 10 s (service `soccer-health`) |
| `systemd/` | the services and the hardware-watchdog setting |

## Pipeline

Design and reasoning: [docs/experiment_pipeline.md](../docs/experiment_pipeline.md). An experiment is a small JSON file in `exp/queue/` (run in file-name order):
`{"name": "xga", "start": "out_5v5/ckpt/t48_u100.pt", "updates": 300, "lr": 5e-5, "rewards": {"w_xga": 2.0}, "notes": "..."}`. `rewards` overrides the minimal reward set
(goals, passing, cooperation, spacing while attacking, kick discipline; every other term 0); `args` may set any other `selfplay.py` option.
`lab/exp_runner.py --loop` (service `soccer-exp`, `lab/systemd/`) takes the next spec and:
1. estimates the start net's Elo (update 0 of the run; with `fast_rules: 1` also its fixed rule-bot checks, cached per start file);
2. trains with `selfplay.py` (`--fast_every 50`: every 50 updates training pauses for a check, the **estimated Elo** below; with `fast_rules: 1` also the older fast check against the rule bots, `eval_checkpoint.py --mode fast`);
3. stops the run early as `diverged` (training points vs the rule bots under 70% of their starting value, after 60 updates) or `regressed` (two estimated Elos in a row below the start net's by more than 2 standard errors of the difference);
4. otherwise runs a **full evaluation** (behaviour, scouting) of the last checkpoint and of the one with the highest estimated Elo, keeps the better of the two by estimated Elo as the run's best checkpoint (`x_<run>_best`) and plays ladder rounds until it is placed. There is no verdict: a run is judged by its Elo and its goals scored / conceded (`lab/ladder.py`).
Every `fast_every` updates (and once for the start net, update 0) the checkpoint gets an **estimated Elo** (this is the whole check; the older fixed matches against the rule bots only with `fast_rules: 1`, and `regressed` = two estimates in a row more than 2 standard errors below the start net's) (`lab/ladder.py estimate`, option `elo_pairs`, default 12 pairs = 24 matches, seconds on the Mac): it plays placed ladder entries, half spread over the ranking and half near its level, and only its own rating and goal strengths are fitted. Stored in `exp/elo_estimates.jsonl`, not in the ladder.
After a reboot (the Pi's hardware watchdog reboots a frozen Pi) the runner resumes the running experiment from its last checkpoint. `--viewer` (the service runs with it) plays the live demo match (`lab/live.py`, below), started again if it closes, so `kill`-ing the match reloads its code. The Pi's 1024x600 touch screen shows the dashboard full screen through its own service, `soccer-kiosk` (`lab/kiosk.py`: Chromium kiosk on `http://127.0.0.1:8080/?kiosk=1#/live`, own profile `~/.config/soccer-kiosk`, restarted by systemd if it closes), whether the Pi trains or only shows.
Every evaluation writes `logs/sp_eval/<name>.txt` (readable text) and `<name>.json` (the same numbers as one record, built by `rl/eval_checkpoint.py` from the `RESULT` lines of `rl/evaluate.py`; `tracker.add_result` stores it as is, and parses the text only for files from before the JSON). Training progress: `logs/<tag>_train.jsonl` (one line per logged update, `tracker.train_rows`; older runs: the progress lines of `logs/<tag>.out`).
Everything is plain files: `exp/results.jsonl` (one record per evaluation, kind fast|full, league points / goal difference / head to head / behaviour, each with standard errors), `exp/results.md` (table, rewritten after every evaluation),
`exp/runs/<name>/status.json`, `exp/runner.log`; finished specs move to `exp/done/`, broken ones to `exp/failed/`. `EXP_MLFLOW=1` also mirrors every evaluation to MLflow (`pip install mlflow-skinny`, no server;
copy `exp/mlruns/` to another computer and run `mlflow ui` there).
The web app (`web/app.py`, service `soccer-dashboard`, port 8080, **no login: local network only**) shows the Lab next to the Game (switch in the bar); the Lab (`web/lab/*.js` on the API of `lab/dashboard.py`, read-only, dark by default) polls every 10 s:
**Now** (the running experiment with progress / ETA and its estimated Elo, goals scored and conceded, or when idle the last finished run with its Elo, the change against its start net, goals and cost; the next specs in the queue; machine vitals and the last reboot; the top 8 of the Elo ranking with the current run's checkpoint marked; the smoothed training curve of the running or last run; the events of the last 24 h as readable lines with fast checks grouped),
**Live** (the match this machine plays, drawn in the browser from a stream of positions: `lab/live.py` sends JSON over local UDP 7310, the dashboard relays it as server-sent events), **Runs** (experiments, imitation trainings, imported runs and the
queue in one table ranked by Elo (estimated while a run trains), with goals scored / conceded against the average ladder team, what each run changes against its control, cost; filters by state,
type, net, changed setting and experiment; runs listed in `exp/hidden_runs.json` (failed, empty, leftover) are hidden unless "Show hidden" is ticked; tick runs to compare), **Run** pages with tabs (Summary: Elo, estimated Elo, change against the
start net, goals scored / conceded, the estimates over updates; Training: PPO health small multiples, reward composition; Evaluation: estimated Elo and goals of every checkpoint, the ladder row, the matches of each estimate, and folded away the fixed rule-bot tests (tiers, head to head, forest plot vs the reference); Behaviour: vs the rule bots, heatmaps; Config: what differs from the defaults),
**Ranking** (this machine's ratings of one team size, `elo/` and [docs/ratings.md](../docs/ratings.md): every player, team and training checkpoint, size pills 1v1 to 5v5; the runner plays a round whenever the queue is empty and the web app refines while the machine is idle, `touch exp/ladder_off` / `touch local/refine_off` stop them; table with 95% intervals, rating history, latest matches; `python3 lab/lab.py ladder archive --yes` starts the ratings over when you decide, keeping the old database in `local/elo_archive/`), **Dataset** (the user's recorded play from the Game, `data/human/`: moves, heatmaps, which situations are covered, a replay of every match; `il/analysis.py`), **Compare** (any number of runs against the first, same protocol only, paired forest plot, metric table, overlaid curves) and **Pi** (temperature, load, memory, clock on a time axis with reboot markers; an offline banner
appears on every page when the Pi stops answering). Run colours are hashed from the run name. On the Pi's 1024x600 touch screen the kiosk layout (`?kiosk=1`) uses a side rail and draws the live match at 15 fps.
Open `http://<pi-address>:8080` from any computer on the network.
Safety against the freezes seen on the Pi: the learning step uses 2 torch threads (`--learn_threads`), `rl/evaluate.py` pins numpy/OpenBLAS to one thread in every evaluation process (with the venv's OpenBLAS the old net servers spun 28 threads and starved the simulation: evaluations took 3x longer), and `lab/systemd/watchdog.conf` turns on the hardware watchdog (15 s).

## Live demo match (`lab/live.py`)

The web app keeps `lab/live.py --tag <run tag> --start <start net>` running for this machine's current run (the running experiment, else the most
recently updated one), on the Pi or the Mac alike; while the runner plays it itself (`--viewer`) the web app steps back: the newest checkpoint of the run
(RL Team 5's squad) plays one 90 s match after another in real time on the match core and streams every frame (30/s, JSON over UDP
127.0.0.1:7310) to the dashboard, which relays it to the browser. The opponent is drawn for every match from all handmade teams,
RL Team 4/5, t48_u100, jit8 and the best checkpoint of every `x_*` run, unless the Live page pins one (`logs/live_opponent.json`).
Puzzle mode (`logs/live_mode.json`): 60 s from a random layout of all players and the ball, over at the first goal. A new pick on the
page ends the shown match at once.

## Deploy on the Pi

Between experiments (nothing in `exp/running/`, or right after a run finished), from `~/simple-soccer`:

```bash
git pull
sudo systemctl disable --now soccer-oppnet; sudo rm -f /etc/systemd/system/soccer-oppnet.service
sudo rm -f /etc/systemd/system/soccer-{exp,dashboard,health}.service && sudo cp lab/systemd/soccer-*.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl restart soccer-exp soccer-dashboard soccer-health
sudo systemctl enable --now soccer-kiosk          # once: the kiosk is its own service since 2026-11-21 (the runner no longer opens it)
```
`git lfs version` must work on the Pi (`sudo apt install git-lfs && git lfs install` once): the nets in `models/` and the recordings
in `data/human/` are Git LFS files, and without it they arrive as small pointer files.

(The units moved from `tools/systemd/` to `lab/systemd/` and point at `lab/`; `soccer-oppnet`, the net server of the old Godot live
viewer, is gone: `lab/live.py` loads the opponent net itself. Godot is no longer needed on the Pi. `soccer-dashboard` now runs `web/app.py`
with the venv's Python: the Lab plus the Game.)

The runner and the web app use `~/rl-venv/bin/python` (torch 2.5.1, numpy; the web app's Game needs numpy, its Lab only the standard library).
