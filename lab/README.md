# Lab: experiment pipeline and dashboard

Runs the training experiments unattended on the Raspberry Pi and shows them on a web page. It drives the training scripts in
[`rl/`](../rl/README.md), which run on the match core (`soccer/`). No Godot is involved. Agents: start with [AGENTS.md](../AGENTS.md).

| File | What |
|---|---|
| `exp_runner.py` | the runner (service `soccer-exp`): queue -> train -> fast checks -> full evaluation -> verdict |
| `tracker.py` | the shared file formats in `exp/` (results, statuses, specs, defaults `MINIMAL` / `DEFAULTS`) |
| `lab.py` | the agent CLI (read-only views, queue edits); `/api/v1` of the dashboard serves the same |
| `dashboard.py` | the Lab's JSON API; the web app (`web/app.py`, service `soccer-dashboard`, port 8080) serves it, the pages are `web/lab.js` |
| `live.py` | the dashboard's live demo match (newest checkpoint vs a random or picked opponent, real time) |
| `pi_health_log.sh` | one health line every 10 s (service `soccer-health`) |
| `systemd/` | the services and the hardware-watchdog setting |

## Pipeline

Design and reasoning: [docs/experiment_pipeline.md](../docs/experiment_pipeline.md). An experiment is a small JSON file in `exp/queue/` (run in file-name order):
`{"name": "xga", "start": "out_5v5/ckpt/t48_u100.pt", "updates": 300, "lr": 5e-5, "rewards": {"w_xga": 2.0}, "notes": "..."}`. `rewards` overrides the minimal reward set
(goals, passing, cooperation, spacing while attacking, kick discipline; every other term 0); `args` may set any other `selfplay.py` option.
`lab/exp_runner.py --loop` (service `soccer-exp`, `lab/systemd/`) takes the next spec and:
1. evaluates the start net once (fast + full; cached per start file) = the baseline;
2. trains with `selfplay.py` (`--fast_every 50`: every 50 updates training pauses for a **fast check**, `eval_checkpoint.py --mode fast`: 24 short matches against every 3rd rule team plus head to head against the start net, a few minutes);
3. stops the run early as `diverged` (training points vs the rule bots under 70% of their starting value, after 60 updates) or `regressed` (two fast checks in a row worse than the baseline by more than 2 standard errors);
4. otherwise runs a **full evaluation** of the last checkpoint and compares it with the baseline (`tracker.compare`: league points and goal difference, verdict better / worse / no difference at 1.96 standard errors).
After a reboot (the Pi's hardware watchdog reboots a frozen Pi) the runner resumes the running experiment from its last checkpoint. `--viewer` (the service runs with it) plays the live demo match (`lab/live.py`, below) and opens the dashboard full screen on the Pi's 1024x600 touch screen (Chromium kiosk, `http://127.0.0.1:8080/?kiosk=1#/live`, own profile `~/.config/soccer-kiosk`). Both are started again if they close, so `kill`-ing the match reloads its code.
Everything is plain files: `exp/results.jsonl` (one record per evaluation, kind fast|full, league points / goal difference / head to head / behaviour, each with standard errors), `exp/results.md` (table, rewritten after every evaluation),
`exp/runs/<name>/status.json`, `exp/runner.log`; finished specs move to `exp/done/`, broken ones to `exp/failed/`. `EXP_MLFLOW=1` also mirrors every evaluation to MLflow (`pip install mlflow-skinny`, no server;
copy `exp/mlruns/` to another computer and run `mlflow ui` there).
The web app (`web/app.py`, service `soccer-dashboard`, port 8080, **no login: local network only**) shows the Lab next to the Game (switch in the bar); the Lab (`web/lab.js` on the API of `lab/dashboard.py`, read-only, dark by default) polls every 10 s:
**Now** (the running experiment with progress / ETA / last fast check, Pi vitals and the last reboot, league strength of every run with 95% intervals, the smoothed training curve, events, queue),
**Live** (the match the Pi plays, drawn in the browser from a stream of positions: `lab/live.py` sends JSON over local UDP 7310, the dashboard relays it as server-sent events), **Runs** (experiments, imported runs and the
queue in one sortable / filterable table with what each run changed, training sparklines on one scale, verdicts and cost; tick runs to compare), **Run** pages with tabs (Summary: evaluations with intervals and the
reference band; Training: PPO health small multiples, reward composition; Evaluation: tiers, head to head, forest plot vs the reference, paired; Behaviour: vs the rule bots, heatmaps; Config: what differs from the defaults),
**Dataset** (the user's recorded play from the Game, `data/human/`: moves, heatmaps, which situations are covered, a replay of every match; `il/analysis.py`), **Compare** (any number of runs against the first, same protocol only, paired forest plot, metric table, overlaid curves) and **Pi** (temperature, load, memory, clock on a time axis with reboot markers; an offline banner
appears on every page when the Pi stops answering). Run colours are hashed from the run name. On the Pi's 1024x600 touch screen the kiosk layout (`?kiosk=1`) uses a side rail and draws the live match at 15 fps.
Open `http://<pi-address>:8080` from any computer on the network.
Safety against the freezes seen on the Pi: the learning step uses 2 torch threads (`--learn_threads`), `rl/net_server.py` pins numpy/OpenBLAS to one thread (with the venv's OpenBLAS a net server spun 28 threads and starved the simulation: evaluations took 3x longer), and `lab/systemd/watchdog.conf` turns on the hardware watchdog (15 s).

## Live demo match (`lab/live.py`)

While an experiment runs, the runner keeps `lab/live.py --tag <run tag> --start <start net>` running: the newest checkpoint of the run
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
```

(The units moved from `tools/systemd/` to `lab/systemd/` and point at `lab/`; `soccer-oppnet`, the net server of the old Godot live
viewer, is gone: `lab/live.py` loads the opponent net itself. Godot is no longer needed on the Pi. `soccer-dashboard` now runs `web/app.py`
with the venv's Python: the Lab plus the Game.)

The runner and the web app use `~/rl-venv/bin/python` (torch 2.5.1, numpy; the web app's Game needs numpy, its Lab only the standard library).
