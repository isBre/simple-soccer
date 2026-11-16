# Experiment log (lab notebook)

What was tried, what came out, and what we concluded. Numbers are league points per match against the 16 rule-based teams
(3 = always win), mean ± standard error, unless stated. Full evaluations use 90 s matches (32 matches); fast checks use 60 s matches
against every 3rd team (24 matches) and are only comparable with other fast checks. Raw results: `exp/results.jsonl`, table: `exp/results.md`,
dashboard: `http://<pi-address>:8080`. Newest entries at the bottom; the agent appends a review after every finished experiment.

## Standing decisions (read first)
- **No fixed roles.** One net drives all 5 players; the observation has no player slot or ID, so roles must come from the situation (decided 2026-11-14).
- **Observation `team` (46 numbers):** me, my 4 teammates nearest first, the 5 opponents nearest first, the ball (positions and velocities,
  normalised), a kickoff flag and a goal-celebration flag. No goal positions, no "ball relative to me", no score, no time.
- **Reward terms come back one at a time** on top of the minimal set, each as its own experiment judged by a full evaluation (2026-11-16).
  Minimal set: goals, passing (progressive / ok / failed, individual credit, receive, key pass, xA), cooperation (capped at 8/match),
  "open for a pass", spacing **only while our team has the ball**, kick discipline. Off: shaping, twitching, keeper-far, too-far-from-ball,
  xG for/against, win/draw bonus, tackles, goal-side, opponent-in-our-half, compactness.
- **No hand-made positioning terms for defence or the keeper** (goal-line cover, keeper position): the user wants the net to find its own
  solution, e.g. high pressing without a keeper (2026-11-16).
- **Learning rate 5e-5** with a 30-update warm-up after every (re)start. 3e-4 and 1e-4 runs drifted away from the warm start.
- **Raspberry Pi 4 (4 cores, 3.8 GB).** Training on 3 workers (2 rule + 1 self-play), learning step on 2 threads, net servers on 1 BLAS thread.
  The live viewer runs on the Pi's touch screen (no keyboard) next to training.

## History before the pipeline
| Run | What | Result |
|---|---|---|
| RL Team 1-5 | 54-number observation with player slot (`legacy`). Team 3: self-play u500; Team 4: cooperation fine-tune (key passes, xA, open); Team 5: anti-farming coop + keeper-home + 60% random starts | Team 3 2.97, Team 4 3.00, all near the 3.0 ceiling of the rule league |
| jit7 / jit8 | anti-twitch work on the 54-number net (jitter penalty, then lr 3e-4) | `jit8_u200`: **2.94 ± 0.06**, conceded 0.03, beats RL Team 4 (1.67 pts h2h) and RL Team 5 (2.17) |
| distillation | 54 -> 46 numbers: imitation of jit8 by a fresh 46-input net, then 4 DAgger rounds (`rl/distill.py`, `out_5v5/team46_start`) | move agreement 86%, kick 99%; short 30 s check 2.19 ± 0.17. Plain imitation without DAgger: 0.88 |
| t46 | 46 numbers from team46_start, **full reward mix** (xG, xGA, win/draw, tackles, goal-side, opp-half, compact, far), lr 3e-4 | u100 1.19 ± 0.23, u200 1.16; conceded 1.22. Pi froze at u254 |
| t47 | same mix, lr 1e-4; from u100 heavier goal-side 0.01 / compact 0.008 | u100 1.88 ± 0.23 -> u200 1.19 (heavier terms) -> reverted -> u200 1.53, u400 **0.66**, idle 26%. Steady decline. Pi froze at u492 |
| t48 | 46 numbers from team46_start, **minimal reward set**, lr 5e-5 | u100 **2.25 ± 0.20**, conceded 0.75; best move 2.69, conceded 0.19. h2h RL4 0.38, RL5 0.00 |

### Conclusions so far
1. The full reward mix made the 46-number net steadily worse (t46, t47); the minimal set at a small learning rate kept and improved it (t48).
   Which of the new terms hurts is not known yet: that is what the queue measures.
2. **The 46-number line is still far below the old 54-number jit8** (2.25 vs 2.94, and it loses clearly to RL Team 4/5 head to head).
   Closing this gap is the main open problem. Candidates: more DAgger rounds / longer distillation, a larger net, or features the role-free
   observation lost (the net cannot tell its own role, so it may need more training to learn situational roles).
3. Sampling noise matters a lot: best-move play concedes far less (t48: 0.19 vs 0.75) and twitches like the rule bots (2.2 direction changes/s vs 11).
4. Two identical evaluations can differ by about 2 standard errors only by chance; read verdicts with that in mind. Experiment `minimal`
   (control) measures the pipeline's own noise floor.

### The Pi freezes (2026-11-14 and 2026-11-16)
The Pi became unreachable with the fan still running (frozen, not a power cut), no kernel message. Before both freezes training slowed
25-60x (a learning step took 622 s instead of 11). Found and fixed: the venv's numpy (OpenBLAS) started 28 busy threads per net server and
starved the simulation; the learning step used 4 torch threads next to the Godot workers. Now: BLAS 1 thread, learn 2 threads, hardware
watchdog (reboot after 15 s frozen), the runner resumes after a reboot, `logs/pi_health.log` records the state every 10 s.
Not proven that this was the cause: if it freezes again, read the last lines of the health log first.

## Experiment queue (2026-11-16)
All from `t48_u100`, 300 updates, lr 5e-5, minimal set plus one term: 01 minimal (control), 02 win_draw, 03 xga, 04 goalside, 05 compact,
06 far, 07 xg, 08 tackle. Baseline `start:t48_u100`: full 2.25 ± 0.20, fast 1.42 ± 0.24.

## Changes on 2026-11-16 (evening)
Four reviews of the pipeline (RL, scouting, UI, agent interface) led to: per-match evaluation records and paired comparisons within one
protocol, provenance (git commit, checkpoint hash), faithful resumes (optimizer + opponent pool saved, frozen benchmark pinned to the
start net), the agent CLI `rl/lab.py` + `/api/v1` + `AGENTS.md`, a redesigned dashboard with a scouting tab, and a new queue:
- The RL review judged the one-term-at-a-time reward queue underpowered (300 updates at lr 5e-5 barely move the policy; a full evaluation
  only detects differences of about 0.7 points). The reward arms are parked in `exp/parked/` (xga first when they come back).
- New queue: `minimal` (running) -> `control_seed11` (noise floor) -> `kickstart` (KL to the jit8 teacher, decaying, lr 1e-4) ->
  `strong_opponents` (jit8 / RL4 / RL5 in the self-play slots, PFSP) -> `control_long` (1000 updates).
- Still to try: a wider net (256) distilled from jit8 (`distill.py --hidden 256`), then kickstarted.

## Reviews
An automatic review runs every 2 hours while the agent's session is open: it checks the Pi and the runner, appends a review here for every
finished experiment and adjusts the queue.
<!-- the agent appends one entry per finished experiment: date, run, verdict with numbers, what it means, what was queued next -->
