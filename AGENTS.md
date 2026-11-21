# Agents: how to run and judge RL experiments here

This repository trains 5v5 soccer nets with PPO on a Raspberry Pi 4 and runs experiments unattended. If you are an AI agent working
on the experiments, start here. People: the same applies; the dashboard (the Lab area of the web app) is at `http://<pi-address>:8080`.

## Read first
- `docs/rewards.md`: every reward term sorted into beneficial / unsure / not good, with the evidence (update it after each review).
- `docs/experiment_log.md`: history, **standing decisions** (do not violate them without asking the user), conclusions, reviews.
- `exp/schema.json`: what every metric means, its unit and direction, the evaluation protocols and the comparison rules.
- The match itself (physics, rules, stats, AI) is the Python core `soccer/`; training (`rl/env.py`) and evaluations
  (`rl/evaluate.py`) and the Live demo match (`lab/live.py`) run on it. The web app (`web/app.py`, port 8080) has two areas: Game (the
  playable game, back end `game/`) and Lab (this pipeline's dashboard). There is no Godot any more; `python3 tests/run_all.py` runs
  the regression tests (README "Tests"; re-record `tests/golden/` with `--update` only for an intended change of behaviour).

## Look (read-only, compact JSON)
```
python3 lab/lab.py status                  # Pi + runner + running experiment (progress, ETA, stalled?) + last reboot
python3 lab/lab.py runs                    # every run: what it changed, state, stop reason, latest estimated Elo, cost
python3 lab/lab.py run NAME --tail 20      # one run in detail (evaluations, training / PPO / reward-term tail, config)
python3 lab/lab.py evals --kind full       # evaluation records (filters: --run, --kind, --protocol)
python3 lab/lab.py best                    # checkpoints ranked by the lower 95% bound of league points (one protocol)
python3 lab/lab.py compare A B             # paired difference A - B with se, z, p, MDE and a verdict (same protocol only)
python3 lab/lab.py ablation                # each finished run vs its reference, Holm-corrected over the batch
python3 lab/lab.py events --since 2026-11-16T20:00   # what happened (starts, resumes, stops, evaluations, reboots)
python3 lab/lab.py ranking [--league rl]   # Elo ranking of every team of every league (lab/ladder.py): Elo ± 95%, adjusted goals agf / aga
python3 lab/lab.py estimates --run NAME    # estimated Elo, GF, GA of a run's checkpoints during training (u0 = the start net)
```
Style / tactics: every full evaluation (and `python3 rl/eval_checkpoint.py --model M --out F --mode scout`, ~2 min) stores a `scout`
summary: possession, field tilt, PPDA, pressing distances, how often the goal is guarded or empty, shape by depth rank in and out of
possession, who plays where (role shares per slot), shots for / against with xG, passes, recoveries. `evals` rows carry the scalar part as
`style`; RL Team 4 and 5 are recorded as reference runs `team:RL Team 4` / `team:RL Team 5`.
The dashboard serves the same data at `GET /api/v1/<command>` (e.g. `/api/v1/compare?a=minimal&b=start:t48_u100&kind=full`).
Every response is `{"schema_version", "generated_at", "data"}`; errors are `{"error", "hint"}` with exit code 1 / HTTP 404.

## Act (local files only; every write is logged in exp/audit.jsonl)
```
python3 lab/lab.py queue list
python3 lab/lab.py queue validate spec.json       # checks name, start checkpoint, option names
python3 lab/lab.py queue add spec.json [--position 1]
python3 lab/lab.py queue move NAME --position 1
python3 lab/lab.py queue cancel NAME              # running: stops within 30 s ('cancelled'); queued: moved to exp/parked/
python3 lab/lab.py ladder archive [--label L] [--yes]   # ONLY when the user asks: starts the Elo ranking over
```
`ladder archive` moves every stored ladder match and the rating history to `exp/ladder_archive/<date>[_<label>]/` (kept, no longer
counted); without `--yes` it only shows what would move. The user decides when the ranking is reset; never do it on your own.
A spec: `{"name": "xga", "start": "out_5v5/ckpt/t48_u100.pt", "updates": 300, "lr": 5e-5, "rewards": {"w_xga": 2.0},
"args": {"seed": 11}, "control": "minimal", "notes": "why"}`. `rewards` override the minimal set and `args` the training defaults
(`lab/tracker.py`: MINIMAL, DEFAULTS); any `rl/selfplay.py` option is allowed. Names are unique forever (a used name is refused).
`control` = the run this one is compared with (the dashboard's Experiment filter); without it, the start net.
The runner (`lab/exp_runner.py`, service `soccer-exp`) trains the queue one spec at a time; every 50 updates it pauses for an **estimated Elo**
(24 matches against mixed ladder entries, `elo_pairs`; the older rule-bot fast check only with `fast_rules: 1`); it stops early on
divergence / regression (two estimates in a row clearly below the start net's) / cancel, then
runs full evaluations (last checkpoint and the one with the highest estimated Elo: behaviour, scouting), keeps the better of the two by
estimated Elo as `x_<run>_best` and places it in the Elo ladder. There is no better / worse verdict.

## Judge correctly
1. **A run is judged by Elo, goals scored and goals conceded** (decided 2026-11-21): the ladder rating of its best checkpoint and its
   opponent-adjusted goals (`agf` / `aga`: per 90 s match against the average ladder team). Points against the rule bots saturate near 3
   and cannot rank good nets; there is no better / worse verdict. A new entry is placed after the run and its rating keeps settling as the
   ladder plays (while the queue is empty): read it again later before concluding.
2. Two Elo ratings differ when their 95% intervals do not overlap (the intervals are relative to the average rating, about ±25 after
   800 games). Raw goals per match are not comparable between entries: strong entries meet strong opponents.
3. The estimated Elo during training (`estimates`, about ±140) shows the trend of one run (is it improving, did it break?), not a ranking.
4. The full evaluation (`full/g1/d90`, matches against the rule teams) is kept for behaviour and scouting, which the Lab shows next to
   the strongest rated teams. Its league points (and the older `fast/g2/d60` checks) are not used to judge runs; if you compare them,
   only within one protocol and paired (`compare`, `ablation`).
5. Training points (`train_pts_vs_rules`) are a trend signal from sampled play with random starts, not an evaluation.

## Health
- `lab.py status` shows `stalled` (no training output for 15 min outside an evaluation) and `last_reboot` (last health sample before it).
- `logs/pi_health.log`: one line every 10 s (ISO time, boot id, throttling, temperature, load, memory). `journalctl -b -1` for the kernel side.
- Services: `soccer-exp` (runner), `soccer-dashboard` (port 8080), `soccer-health` (units in `lab/systemd/`; deploy steps in `lab/README.md`). The hardware watchdog reboots a frozen Pi.

## Commit
The test hook (`.githooks/`, README "Tests") is not installed on the Pi: pushes of results and notes from there are never held up.
Results, specs and the notebook are versioned: `git -c user.name=<owner> -c user.email=<owner email> commit` (the Pi has no global
git identity; use the identity of the existing commits), with a `Co-Authored-By` line, then `git push`.

## Live demo match
The Live page plays the newest checkpoint against a **random opponent per match** (all handmade rule teams, RL Team 4/5, t48_u100, jit8 and the
best checkpoint of every `x_*` run). The Live page also has a **puzzle mode** (random layout of all players and the ball, 60 s, over at the first goal; `POST /api/live/mode`). The dropdown on the page pins one opponent (`POST /api/live/opponent`, same-origin only, the dashboard's only
write; state in `logs/live_opponent.json`). Agents do not need it.
