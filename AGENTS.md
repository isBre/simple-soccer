# Agents: how to run and judge RL experiments here

This repository trains 5v5 soccer nets with PPO on a Raspberry Pi 4 and runs experiments unattended. If you are an AI agent working
on the experiments, start here. People: the same applies; the dashboard is at `http://<pi-address>:8080`.

## Read first
- `docs/experiment_log.md`: history, **standing decisions** (do not violate them without asking the user), conclusions, reviews.
- `exp/schema.json`: what every metric means, its unit and direction, the evaluation protocols and the comparison rules.

## Look (read-only, compact JSON)
```
python3 rl/lab.py status                  # Pi + runner + running experiment (progress, ETA, stalled?) + last reboot
python3 rl/lab.py runs                    # every run: what it changed, state, stop reason, verdict, cost
python3 rl/lab.py run NAME --tail 20      # one run in detail (evaluations, training / PPO / reward-term tail, config)
python3 rl/lab.py evals --kind full       # evaluation records (filters: --run, --kind, --protocol)
python3 rl/lab.py best                    # checkpoints ranked by the lower 95% bound of league points (one protocol)
python3 rl/lab.py compare A B             # paired difference A - B with se, z, p, MDE and a verdict (same protocol only)
python3 rl/lab.py ablation                # each finished run vs its reference, Holm-corrected over the batch
python3 rl/lab.py events --since 2026-11-16T20:00   # what happened (starts, resumes, stops, evaluations, reboots)
```
Style / tactics: every full evaluation (and `python3 rl/eval_checkpoint.py --model M --out F --mode scout`, ~2 min) stores a `scout`
summary: possession, field tilt, PPDA, pressing distances, how often the goal is guarded or empty, shape by depth rank in and out of
possession, who plays where (role shares per slot), shots for / against with xG, passes, recoveries. `evals` rows carry the scalar part as
`style`; RL Team 4 and 5 are recorded as reference runs `team:RL Team 4` / `team:RL Team 5`.
The dashboard serves the same data at `GET /api/v1/<command>` (e.g. `/api/v1/compare?a=minimal&b=start:t48_u100&kind=full`).
Every response is `{"schema_version", "generated_at", "data"}`; errors are `{"error", "hint"}` with exit code 1 / HTTP 404.

## Act (local files only; every write is logged in exp/audit.jsonl)
```
python3 rl/lab.py queue list
python3 rl/lab.py queue validate spec.json       # checks name, start checkpoint, option names
python3 rl/lab.py queue add spec.json [--position 1]
python3 rl/lab.py queue move NAME --position 1
python3 rl/lab.py queue cancel NAME              # running: stops within 30 s ('cancelled'); queued: moved to exp/parked/
```
A spec: `{"name": "xga", "start": "out_5v5/ckpt/t48_u100.pt", "updates": 300, "lr": 5e-5, "rewards": {"w_xga": 2.0},
"args": {"seed": 11}, "control": "minimal", "notes": "why"}`. `rewards` override the minimal set and `args` the training defaults
(`rl/tracker.py`: MINIMAL, DEFAULTS); any `rl/selfplay.py` option is allowed. Names are unique forever (a used name is refused).
`control` = the run this one is judged against (same update, same protocol); without it the start net is the reference.
The runner (`rl/exp_runner.py`, service `soccer-exp`) trains the queue one spec at a time, fast-checks every 50 updates, stops early on
divergence / regression / cancel, then runs full evaluations (last checkpoint and the best fast check) and writes the verdict.

## Judge correctly
1. Only compare numbers of the same `protocol` (`full/g1/d90` vs `fast/g2/d60`; never across). `lab.py compare` refuses otherwise.
2. Prefer paired comparisons (the matches use fixed seeds); `paired: true` in the result means the noise of opponents / sides / kickoffs cancels.
3. A difference counts only if `|z| > 1.96`; for several arms against one reference use `ablation` (Holm). Look at `mde`: a full
   evaluation cannot see differences smaller than about 0.7 points.
4. League points saturate at 3 against the rule bots: rank strong nets by head to head (`h2h`) and goal difference.
5. Training points (`train_pts_vs_rules`) are a trend signal from sampled play with random starts, not an evaluation.

## Health
- `lab.py status` shows `stalled` (no training output for 15 min outside an evaluation) and `last_reboot` (last health sample before it).
- `logs/pi_health.log`: one line every 10 s (ISO time, boot id, throttling, temperature, load, memory). `journalctl -b -1` for the kernel side.
- Services: `soccer-exp` (runner), `soccer-dashboard` (port 8080), `soccer-health`, `soccer-oppnet` (net server 7304 for the Live opponent). The hardware watchdog reboots a frozen Pi.

## Commit
Results, specs and the notebook are versioned: `git -c user.name=<owner> -c user.email=<owner email> commit` (the Pi has no global
git identity; use the identity of the existing commits), with a `Co-Authored-By` line, then `git push`.

## Live demo match
The Live page plays the newest checkpoint against a **random opponent per match** (all handmade rule teams, RL Team 4/5, t48_u100, jit8 and the
best checkpoint of every `x_*` run). The Live page also has a **puzzle mode** (random layout of all players and the ball, 60 s, over at the first goal; `POST /api/live/mode`). The dropdown on the page pins one opponent (`POST /api/live/opponent`, same-origin only, the dashboard's only
write; state in `logs/live_opponent.json`). Agents do not need it.
