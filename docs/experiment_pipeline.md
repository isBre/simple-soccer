# Experiment pipeline (design and plan)

Goal: an autonomous loop on the Raspberry Pi where an experiment is a small file, a runner trains and evaluates it, results are
collected in one place that both people and the agent can read, and a web page on the local network shows everything.

## Constraints that shape the design
- Raspberry Pi 4, 4 cores, 3.8 GB RAM, SD card. One experiment at a time. Training uses 3 cores, so the rest has to stay light.
- The Pi froze twice (fan on, no ssh, no log). Training slowed 25-60x just before. So: fewer competing threads, a hardware watchdog,
  and a runner that picks up after a reboot by itself.
- The old evaluation is too noisy (+-0.2 points), too slow (hours) and has no resolution at the top (see "Evaluation").

## Pieces
| Piece | File | What it does |
|---|---|---|
| Safety | `rl/selfplay.py`, systemd watchdog | learning step uses 2 threads; a frozen Pi reboots itself in ~15 s |
| Evaluation | `rl/eval_checkpoint.py` (`--mode fast|full`, `--seed`) | paired seeds, ladder of fixed opponents, goal difference with error |
| Tracker | `rl/tracker.py`, `exp/` | one record per run and per evaluation, readable by humans, the agent and the web page |
| Runner | `rl/exp_runner.py` + systemd service | takes the next spec from `exp/queue/`, trains, evaluates, decides, repeats; resumes after reboot |
| Dashboard | `tools/dashboard.py` | read-only web page on port 8080, reachable from the local network (service `soccer-dashboard`) |
| Agent loop | scheduled wake-ups | the agent reads `exp/results.md`, writes the next spec, leaves a summary |

## Experiment spec (`exp/queue/<NN>_<name>.json`)
```json
{"name": "win_bonus", "start": "out_5v5/team46_start.pt", "updates": 300, "lr": 5e-5,
 "rewards": {"w_win": 3.0, "w_draw": 1.0}, "notes": "does the win/draw bonus help on top of the minimal set?"}
```
`rewards` overrides the minimal set (goals, passing, cooperation, spacing while attacking, kick). Everything else in a spec has a default.

## Evaluation
- **Fast check** (every 50 updates, minutes): 16 short matches, fixed seeds and starting positions, vs 2 rule bots of different strength
  and the previous best checkpoint. Used only to catch collapse and to stop early.
- **Full evaluation** (end of an experiment, or when the fast check improves a lot): same fixed seeds for every checkpoint
  (the league and head-to-head matches already use fixed seeds, so every checkpoint plays the same kickoffs; the net's own sampling is the remaining noise), all 16 rule teams, the ladder, behaviour numbers, sampled and best-move play.
- **Ladder** of fixed opponents: the 16 rule bots, RL Team 4 and 5, and the net the experiment started from (head to head). No Elo rating:
  with so few matches per opponent the head-to-head points and goal difference, with their standard errors, say the same.
- Every evaluation reports points per match AND goal difference per match, each with its standard error, and the smallest
  difference it could detect. The agent treats smaller differences as "no difference".

## Stopping rules (written to the run record)
- training points per match vs the rule bots falls below 70% of its value at the start of the run -> stop, status `diverged`;
- fast check worse than the start checkpoint by more than 2 standard errors twice in a row -> stop, status `regressed`;
- the update budget is reached -> full evaluation, status `done`.

## Tracker layout
```
exp/queue/    specs waiting
exp/runs/<name>/spec.json, status.json, train.jsonl (per-update metrics), evals.jsonl
exp/results.jsonl   one line per evaluation (run, update, kind, pts, se, gd, h2h, elo, behaviour)
exp/results.md      table for the agent and for humans, regenerated after every evaluation
```
An optional mirror to `mlflow-skinny` (no server, writes the standard `mlruns/` folder) is enabled with `--mlflow`; copy the folder
to another machine and run `mlflow ui` there to browse it. The full MLflow server is not installed on the Pi (memory).

## Dashboard
`python3 tools/dashboard.py` serves a self-refreshing page on `0.0.0.0:8080`: current run and queue, a table of finished runs
with verdicts, charts of strength over updates (inline SVG, no internet needed), the Pi health log. It is read-only and has no
login: use it on a trusted network only.

## Agent loop
Every ~hour the agent reads `exp/results.md`, compares the finished run with its baseline (using the standard errors), then
adds the next spec. The default plan is one reward term at a time on top of the minimal set: win/draw bonus, xG against,
goal-side positioning, compactness, too-far-from-ball, xG for, tackles. If the Pi is down, the agent notes it and waits.

## Build order
1. safety changes, 2. evaluation (fast/full, seeds, ladder), 3. tracker + runner + service, 4. dashboard, 5. first queue, 6. docs and tests.

## Status
Built and running as services (`tools/systemd/`). The live viewer is optional (`--viewer`): it costs ~900 MB and a core and the Pi froze while it ran, so unattended runs go without it.
