# Agents: how to run and judge RL experiments here

This repository trains 5v5 soccer nets with PPO and runs experiments unattended, all on one machine (setup: `lab/SETUP.md`). If you
are an AI agent working on the experiments, start here. People: the same applies; the dashboard (the Lab area of the web app) is at
`http://localhost:8080`. The project is an installed package in `.venv/` (`python3 -m venv .venv && .venv/bin/pip install -e '.[train]'`):
run every command below with it active (`source .venv/bin/activate`) or with `.venv/bin/python` in place of `python3`.

## Read first
- `docs/rewards.md`: every reward term sorted into beneficial / unsure / not good, with the evidence (update it after each review).
- `docs/experiment_log.md`: history, **standing decisions** (do not violate them without asking the user), conclusions, reviews.
- `exp/schema.json`: what every metric means, its unit and direction, the evaluation protocols and the comparison rules.
- Players and teams: a player (`data/players`) is a brain with a name (a rule-based archetype with its own algorithm + skill, or a net) that decides alone, talking to teammates only through calls (`ball`, `open`, `run`, `cover`); a team (`data/teams`)
  is a line-up of 5 players (mixed allowed), with no tactic. No keeper role, golden-goal overtime, no shootouts (README "Players,
  teams and kickoff"). Opus 5.5 High was removed (it planned on a clone of the match; docs/opus_5_5_high.md).
- `docs/ratings.md`: **the ratings**: Elo per player and team, per size (1v1 to 5v5), in a local database (`local/elo.db`)
  (`python3 -m elo init` once after cloning; the web app refines in the background).
- `docs/lab_design.md`: the Lab's look (tokens, components, page layouts); read it before changing a Lab page.
- `docs/public_view.md`: **what a player may know**. Every agent (rule-based, net, anything new) decides from the same public view
  (`soccer/core/view.py`): anonymous bodies, their recent history, clock, score, kickoff, last touch, the pitch and the physics, plus
  anything it computes from that; never the match engine or another team's inside. A new observation or agent is a function of the
  view; `tests/test_view.py` enforces the rule.
- The match itself (physics, rules, stats, AI) is the Python core `soccer/`; training (`rl/env.py`) and evaluations
  (`rl/evaluate.py`) and the Live demo match (`lab/live.py`) run on it. The web app (`web/app.py`, port 8080) has two areas: Game (the
  playable game, back end `game/`) and Lab (this pipeline's dashboard). There is no Godot any more; `python3 tests/run_all.py` runs
  the regression tests (README "Tests"; re-record `tests/golden/` with `--update` only for an intended change of behaviour).

## Look (read-only, compact JSON)
```
python3 lab/lab.py status                  # machine + runner + running experiment (progress, ETA, stalled?) + last reboot
python3 lab/lab.py runs                    # every run: what it changed, state, stop reason, latest estimated Elo, cost
python3 lab/lab.py run NAME --tail 20      # one run in detail (evaluations, training / PPO / reward-term tail, config)
python3 lab/lab.py evals --kind full       # evaluation records (filters: --run, --kind, --protocol)
python3 lab/lab.py best                    # checkpoints ranked by the lower 95% bound of league points (one protocol)
python3 lab/lab.py compare A B             # paired difference A - B with se, z, p, MDE and a verdict (same protocol only)
python3 lab/lab.py ablation                # each finished run vs its reference, Holm-corrected over the batch
python3 lab/lab.py events --since 2026-11-16T20:00   # what happened (starts, resumes, stops, evaluations, reboots)
python3 lab/lab.py ranking [--size 5]      # this machine's ratings of one size (elo/, docs/ratings.md): Elo ± 95%, adjusted goals agf / aga
python3 -m elo status                      # matches and entries per size, what is still unplaced (python3 -m elo init after cloning)
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
`ladder archive` moves this machine's ratings database (`local/elo.db`) to `local/elo_archive/<date>[_<label>].db` (kept, no longer
counted); without `--yes` it only shows what would move. The user decides when the ratings are reset; never do it on your own.
A spec: `{"name": "xga", "start": "out_5v5/ckpt/t48_u100.pt", "updates": 300, "lr": 5e-5, "rewards": {"w_xga": 2.0},
"args": {"seed": 11}, "control": "minimal", "notes": "why"}`. `rewards` override the minimal set and `args` the training defaults
(`lab/tracker.py`: MINIMAL, DEFAULTS); any `rl/selfplay.py` option is allowed. Names are unique forever (a used name is refused).
`control` = the run this one is compared with (the dashboard's Experiment filter); without it, the start net.
**Curricula** (phase D, rl/README.md "Every team size, with calls"): a spec with `"stages": [{"size": 1, "opp": "none"}, {"size": 1},
..., {"size": 5}]` is queued as one run per stage (`<name>_1v0`, `<name>_1v1`, ...), each from the previous stage's best checkpoint
(`"start": "best:<run>"`; the first `"scratch"`), on the `slots` observation; `"plateau": K` stops a stage after K estimated Elos
without progress (after `min_updates`). A stage is rated and estimated at its own size.
The runner (`lab/exp_runner.py`, started by `lab/run.sh`) trains the queue one spec at a time; every 50 updates it pauses for an **estimated Elo**
(24 matches against mixed ladder entries, `elo_pairs`; the older rule-bot fast check only with `fast_rules: 1`); it stops early on
divergence / regression (two estimates in a row clearly below the start net's) / cancel, then
runs full evaluations (last checkpoint and the one with the highest estimated Elo: behaviour, scouting), keeps the better of the two by
estimated Elo as `x_<run>_best` and places it in the 5v5 ratings (`elo/`). There is no better / worse verdict.

## Judge correctly
1. **A run is judged by Elo, goals scored and goals conceded** (decided 2026-11-21): the 5v5 rating of its best checkpoint in this
   machine's ratings (`elo/`, `docs/ratings.md`) and its opponent-adjusted goals (`agf` / `aga`: per 90 s match against the average
   opponent). Points against the rule bots saturate near 3 and cannot rank good nets; there is no better / worse verdict. A new
   entry is placed after the run and its rating keeps settling as more rounds are played: read it again later before concluding.
2. The scale is pinned (the average rule-based player of a size is 1500) and the intervals are relative to it. Two ratings differ
   when their 95% intervals do not overlap. Raw goals per match are not comparable between entries: strong entries meet strong opponents.
3. Ratings are **per machine**: the database is local (`local/elo.db`, never pushed; a fresh clone starts empty). Compare runs
   rated in this database; a number from another database is close but not the same. Results stop counting when a file they depend on changes or `elo.ENGINE`
   moves on (bumped with every intended behaviour change, together with the golden tests).
4. The estimated Elo during training (`estimates`, about ±140) shows the trend of one run (is it improving, did it break?), not a
   ranking. Estimates before 2026-11-27 were made against the old team ladder: another scale.
5. The full evaluation (`full/g1/d90`, matches against the rule teams) is kept for behaviour and scouting. Its league points (and
   the older `fast/g2/d60` checks) are not used to judge runs; if you compare them, only within one protocol and paired (`compare`, `ablation`).
6. Training points (`train_pts_vs_rules`) are a trend signal from sampled play with random starts, not an evaluation.

## Health
- `lab.py status` shows `stalled` (no training output for 15 min outside an evaluation) and `last_reboot` (last health sample before it).
- `logs/health.log`: one line every 10 s (ISO time, boot id, battery temperature, thermal pressure, load, memory; `lab/health_log.py`).
- Processes, not services: `lab/run.sh` starts the runner (`logs/runner.out`), the health sampler and the thermal guard
  (`lab/thermal_guard.py`: pauses the run while the machine is too warm); `python3 web/app.py` serves the dashboard on port 8080.
  After a reboot or sleep nothing restarts by itself: run `lab/run.sh` again and the runner resumes the running experiment.

## Commit
Results, specs and the notebook are versioned: commit them with the repository owner's identity (the one of the existing commits)
and a `Co-Authored-By` line, then `git push`. The test hook (`.githooks/`, README "Tests") runs the tests before a push that changes
code; pushes of results, notes or docs only are not held up.

## Live demo match
The Live page plays the newest checkpoint of this machine's current run (started by the web app when the runner does not) against a **random opponent per match** (all handmade rule teams, RL Team 4/5, t48_u100, jit8 and the
best checkpoint of every `x_*` run). The Live page also has a **puzzle mode** (random layout of all players and the ball, 60 s, over at the first goal; `POST /api/live/mode`). The dropdown on the page pins one opponent (`POST /api/live/opponent`, same-origin only, the dashboard's only
write; state in `logs/live_opponent.json`). Agents do not need it.
