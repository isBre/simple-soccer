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

## Wall term (2026-11-16, requested by the user)
Players were seen pressed against the arena's outer wall. Measured with the new scouting number `at_wall_pct`: the start net (t48_u100)
spends **20.8%** of each player's time pressed against the wall. New term `w_wall` (rl_env.gd): a penalty per decision for a player at the
wall for 2+ decisions in a row. Queued first as experiment `wall` (0.005, minimal set, 300 updates, judged against the `minimal` control).

## Reviews
An automatic review runs every 2 hours while the agent's session is open: it checks the Pi and the runner, appends a review here for every
finished experiment and adjusts the queue.
<!-- the agent appends one entry per finished experiment: date, run, verdict with numbers, what it means, what was queued next -->

### Review 2026-11-17 02:20: `minimal` and `wall` (both stopped "diverged", no full evaluation)
- `minimal` (control, minimal set, lr 5e-5, seed 7): fast checks 1.79 (u50), 1.42 (u100), 1.12 (u150), 0.67 ± 0.17 (u200, z -2.6 vs start, GD -0.54, conceded 0.88). Training points 1.53 -> 1.07; stopped at u242 as diverged. h2h vs the start net 1.0 ± 0.31 at u200.
- `wall` (minimal + w_wall 0.005): fast 1.58, 1.50, 0.96 (u150, z -1.4); training points 2.05 -> 1.35; stopped at u194. Same decline as the control, so the wall term is neither shown to help nor to hurt; the wall metric was not measured because no full evaluation ran.
- Meaning: pure PPO with the minimal rewards degrades the 46-number start net even at lr 5e-5 (two independent runs, the same slope). The reward terms are not the cause of the decline; the learning signal itself (self-play plus rule bots, no anchor) drifts away from the distilled policy. Plain "more training" is therefore the wrong lever; an anchor is needed.
- Queue decision: cancelled `control_seed11` (a third degrading control adds little; moved to exp/parked). `kickstart` (KL to the jit8 teacher, decaying) now runs next, then `strong_opponents`, then `control_long`. The `wall` term should be re-tested on top of whatever anchor works (standing decision: one term at a time).

### Review 2026-11-17 10:20: `kickstart` (600 updates, lr 1e-4, KL to jit8 teacher 0.5 decaying to 0 at u600)
- Full evaluation u600: **2.81 ± 0.10**, goal difference +2.12, conceded 0.16 (greedy 2.88). Start net `t48_u100`: 2.25 ± 0.20, GD +0.87, conceded 0.75. Difference +0.56 ± 0.22, z 2.5, p 0.012, GD z 3.3: verdict **better** (unpaired vs the baseline). u50 (best fast check) 2.75 ± 0.12, so most of the gain came early and then held while the KL weight faded to zero (no drift once the anchor was gone, unlike `minimal`/`wall`).
- h2h: vs start net 1.81 (GD +0.88); vs RL Team 4 0.56 (GD -0.81), vs RL Team 5 0.31 (GD -1.56). Still clearly behind the old strong nets (jit8: 1.67 / 2.17 vs RL4 / RL5), so the 46-vs-54 gap against strong opponents is not closed; vs rule bots it nearly is (2.81 vs 2.94).
- Behaviour: 12.9 direction changes/s (still twitchy, rule bots ~2), idle 3%, 24.8 passes and 8.6 shots per match, key passes 3.75, xA 1.17 (start net had far fewer shots).
- Meaning: an anchor fixes the decline and lifts league points; rule-bot saturation limits what the league can show, so progress now has to be read from h2h and goal difference.
- Queue: `strong_opponents` (jit8 / RL4 / RL5 in self-play slots with PFSP) is running: it targets exactly the remaining weakness. `control_long` stays after it. Idea for later: `strong_opponents` started from `kickstart_u600`, then the `wall` term on top of the best line.
