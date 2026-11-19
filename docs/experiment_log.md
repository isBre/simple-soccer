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
- **w_wall 0.02 is in the default reward set** (user yes, 2026-11-18; earlier runs and the specs of `persist_*` keep 0 so their controls stay valid). Full reward register with evidence: `docs/rewards.md`.
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

## Network used (convention, 2026-11-18)
Every run states its network: `net` in `lab.py runs` / `run`, in `exp/results.md`, as a chip on the dashboard, and in every review here as
`inputs-hidden-hidden-outputs` (all runs so far: **46-128-128-10**, about 24k parameters; the old 54-number jit8 is 54-128-128-10).
The wider net (**46-256-256-10**) comes after the current queue: distil it from jit8 (`rl/distill.py --hidden 256 --out team46_w256`), then kickstart it
like `kickstart` / `kickstart_persist`; its reviews will name the net and compare against the 128-wide runs.

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

### Review 2026-11-17 12:20: `strong_opponents` (unanchored, jit8/RL4/RL5 opponents + PFSP, from t48_u100)
- Stopped as diverged at u194: fast 1.29 at u150 (z -0.4 vs start), h2h vs start 0.88; training points 1.88 -> 1.29. No full evaluation.
- Meaning: the third unanchored run (after `minimal`, `wall`) that declines; kickstarting is the only thing that kept the net stable. Strong opponents are not a cure without an anchor.
- Queue: cancelled `control_long` (1000 unanchored updates would be ~8 h on the same decline). Added `kickstart_strong`: from `x_kickstart_u600` (2.81), strong opponents + PFSP + decaying teacher KL (0.3 -> 0 at u400), lr 5e-5, 400 updates, judged against its start net. Still to come: `wall` on top of the anchored line; wider net.

### Note 2026-11-17 16:20: queue after `kickstart_strong`
`kickstart_strong` (u300 fast 2.62, paired +0.04 ± 0.27 vs its start) is flat so far; its full evaluation decides. Queued behind it, so the Pi never idles: `anchor_ctrl` (from kickstart u600, rule bots + self-play, KL 0.3 -> 0 over 300 updates) and `anchor_wall` (same plus w_wall 0.005, judged against `anchor_ctrl`). This re-tests the user-requested wall term on the stable anchored line; the earlier test on the unanchored line was lost to drift.

### Review 2026-11-17 18:20: `kickstart_strong` (from kickstart u600, strong opponents jit8/RL4/RL5 + PFSP 0.75, KL 0.3 -> 0 at u400, lr 5e-5, 400 updates)
- Full evaluation u400: **2.88 ± 0.09**, GD +2.25, conceded 0.06 vs its start net 2.81 (GD +2.12, conceded 0.16): +0.06 ± 0.14, paired z 0.4, p 0.66, MDE 0.40: **no difference**. Fast checks all within ±0.2 of the start (z <= 1.4).
- h2h: RL Team 4 0.81 (start 0.56), RL Team 5 0.44 (0.31), start net 1.88 (GD +0.69); still clearly behind RL4/RL5 (jit8: 1.67 / 2.17). Behaviour: 11.6 direction changes/s (start 12.9), idle 3%.
- Meaning: the anchored line is stable but 400 updates against the strong nets at lr 5e-5 did not move the h2h gap beyond noise; the h2h differences (+0.25, +0.13 on 16 games) are far below what the evaluation can resolve. Rule-bot league points are saturated, so only h2h can show progress.
- Next: `anchor_ctrl` -> `anchor_wall` (running / queued) re-test the wall term. After them the main lever for the RL4/RL5 gap is capacity or a better teacher signal: a wider net (distill.py --hidden 256 from jit8, then kickstart) is the next candidate; to be queued when the Pi frees up.

### Review 2026-11-17 22:20: `anchor_ctrl` (from kickstart u600, rule bots + self-play, KL 0.3 -> 0 at u300, lr 5e-5, 300 updates)
- Full evaluation u300: **2.91 ± 0.09**, GD +2.28, conceded 0.16 vs start (kickstart u600) 2.81 / +2.12 / 0.16: +0.09 ± 0.14, paired z 0.6, p 0.52: **no difference**. h2h: RL Team 4 0.94 (GD -0.44), RL Team 5 0.69 (-0.81), start net 1.38; 11.8 direction changes/s.
- Meaning: second flat anchored run in a row (with `kickstart_strong`): continuing at lr 5e-5 neither drifts nor improves; the rule-bot league is saturated and h2h differences (+0.4 / +0.4 points on 16 games) are inside the noise. It serves as the control for `anchor_wall` (compare with `lab.py compare anchor_wall anchor_ctrl --kind full`).
- Queue: `anchor_wall` running; added `kickstart_persist` (strong opponents with a persistent teacher pull, KL 0.2 decaying only to 0.12) as the cheap next probe of the RL4/RL5 gap. The wider net (distill.py --hidden 256 from jit8, then kickstart) needs a distillation run that would compete with training for the Pi's cores: do it once the queue is empty.

### Review 2026-11-18 04:30: `anchor_wall` (anchor_ctrl setup + w_wall 0.005, from kickstart u600, 300 updates)
- Full evaluation u300: **2.88 ± 0.09**, GD +2.34, conceded 0.28 (greedy 3.00) vs `anchor_ctrl` 2.91 / +2.28 / 0.16: difference -0.03 ± 0.13, paired z -0.2, p 0.81: **no difference** (MDE 0.37). Fast checks all within ±0.12 of the start.
- h2h: RL Team 4 1.38 (GD -0.38; ctrl 0.94), RL Team 5 0.06 (GD -1.81; ctrl 0.69), start net 1.81; the two h2h moves cancel and are noise on 16 games each. Behaviour: 11.6 direction changes/s, idle 2%, 31.9 passes, 15.6 shots (ctrl 7.1), key passes 8.25 (ctrl 2.9), xA 1.95 (ctrl 1.2): more attacking output.
- Wall time (scouting `at_wall_pct`, scout mode, same checkpoint): **17.9%** with the wall term vs **21.9%** for the control (start net t48_u100: 20.8%). Direction is as intended but small (-4 points) and from one scout run each: not shown to be significant.
- Meaning: 0.005 per decision is too weak to change wall behaviour much and costs nothing in league points. Reasonable next step for the user's request: a stronger weight (0.02) judged by `at_wall_pct`; queued after `kickstart_persist`.

### Review 2026-11-18 08:40: `kickstart_persist` (from kickstart u600, strong opponents + PFSP, KL 0.2 decaying to 0.12 at u400, lr 5e-5, 400 updates)
- Full evaluation u400: **2.94 ± 0.06**, GD +2.66, conceded 0.06 vs start (kickstart u600) 2.81 / +2.12 / 0.16: +0.13 ± 0.13, paired z 1.0, p 0.32; GD +0.53 (z 1.5): **no difference**.
- h2h: RL Team 4 0.75 (GD -0.44; start 0.56), RL Team 5 0.94 (-0.50; start 0.31), start net 1.94. Best of the 46-number runs against RL4/RL5 but still losing, and inside the noise (16 games each). Behaviour: 11.1 direction changes/s, 9.2 shots per match.
- Meaning: a persistent teacher pull plus strong opponents gives the best numbers so far (matches jit8 on the rule league) without drift, but no significant gain. Queued `kickstart_persist_long` (from its u400, 600 more updates, same setup) to see whether the small edge grows. Wider net (distill.py --hidden 256) after `anchor_wall_strong` finishes.

### Note 2026-11-18 10:50: speeding up convergence (agreed with the user)
Observation: the gains of every anchored run arrive in the first ~50 updates, then plateau; 2 of 3 workers play rule bots that are already beaten (~2.9 / 3). Queued behind `anchor_wall_strong`, each judged against `kickstart_persist` (same start, anchor, opponents, 400 updates):
- `persist_mix`: worker mix 1 rule + 2 strong/self-play (instead of 2 + 1).
- `persist_lr`: lr 1e-4 (instead of 5e-5) with the teacher anchor on.
- `kickstart_persist_long` moved last (a longer run of what we already have).
Not queued yet: supervised route (more DAgger rounds, `distill.py --hidden 256` from jit8, then kickstart). A distillation uses 3 workers and would fight a running training for the Pi's 4 cores: run it between experiments or on a faster machine. Also open: fast checks every 100 updates (about -4 s/update) and a screen-off switch, once the user decides.

### Review 2026-11-18 12:50: `anchor_wall_strong` (anchor_ctrl setup + w_wall 0.02, net 46-128-128-10, from kickstart u600, 300 updates)
- Full evaluation u300: **2.81 ± 0.10**, GD +2.06, conceded 0.41 vs its start (kickstart u600) 2.81: difference 0.00 ± 0.13, paired z 0.0: **no difference**. Against `anchor_ctrl` (2.91 / +2.28 / 0.16): -0.09 ± 0.14, z -0.6, p 0.52: **no difference**. u200 (best fast check) was 2.88 ± 0.09, GD +2.62, conceded 0.06.
- Wall time (scouting `at_wall_pct`): **8.4%** vs 21.9% (anchor_ctrl) and 17.9% (w_wall 0.005); start net t48_u100 20.8%. Weight 0.02 more than halves the time players spend pressed against the wall, at no measurable cost in league points (one scout run per checkpoint; the effect is large enough not to need a test).
- h2h: u200 RL Team 4 1.38 (GD +0.12), RL Team 5 1.00 (-0.19), start net 2.38; u300 RL4 1.25 (-0.38), RL5 0.69 (-1.19), start net 2.50. The best h2h so far against RL4/RL5 at u200, partly lost at u300: inside the noise (16 games each). Behaviour: 10.8 direction changes/s (lowest of the anchored runs), 10.1 shots per match.
- Meaning: the user-requested wall penalty works at 0.02. Recommend keeping w_wall 0.02 in the minimal set from now on (a rule for the user to confirm; it is an addition to the reward set, so no change was made to the defaults). Queue unchanged: `persist_mix`, `persist_lr`, `kickstart_persist_long`.

### Note 2026-11-18 13:10: ball in the corner (user idea)
New scouting numbers `ball_corner_pct` / `ball_corner_ours_pct` (ball within 150 px of both lines; and with our team's last touch). Measured on the anchored nets at u300: 22.9% / 13.4% (`anchor_ctrl`), 23.4% / 14.4% (`anchor_wall_strong`): the ball spends about twice the time in corners that their area would predict. New reward term `w_corner` (rl_env.gd, selfplay `--w_corner`, default off). Queued first as `anchor_corner` (w_corner 0.01 + w_wall 0.02, anchor setup of `anchor_wall_strong`, which is its control), ahead of `persist_lr`. Added at the user's request: standing decision "one term at a time" is respected (a single new term).

### Review 2026-11-18 18:20: `persist_mix` (kickstart_persist setup with worker mix 1 rule + 2 strong/self-play, net 46-128-128-10, from kickstart u600, 400 updates)
- Full evaluation u400: **2.88 ± 0.09**, GD +2.19, conceded 0.19 (greedy 2.88) vs control `kickstart_persist` u400 2.94 / +2.66 / 0.06: difference -0.06 ± 0.11, paired z -0.6, p 0.57; GD -0.47 (z -1.4): **no difference** (MDE 0.31). u200 (best fast check, 3.00 fast) was 3.00 on the full league, GD +2.31, conceded 0.03.
- h2h: u200 RL Team 4 0.81 (GD -0.62), RL Team 5 0.88 (-0.56), start net 2.44; u400 RL4 0.88 (-0.44), RL5 0.62 (-0.94), start net 1.94. Same level as the control (0.75 / 0.94): moving compute from rule bots to strong opponents did not improve the games against RL4/RL5. Fast checks wandered between 2.46 and 3.00 with no trend. Behaviour: 11.4 direction changes/s, 9.5 shots, 29.6 passes per match.
- Meaning: the worker mix is not what limits us. Every anchored 46-number run now ends at about 2.9 on the rule league and about 0.6–1.4 points against RL4/RL5, whatever the opponents, rewards or mix: the plateau looks like a capacity / observation limit rather than a training-schedule one. Queue kept: `anchor_corner` (running), `persist_lr`, `kickstart_persist_long`; the wider net (46-256-256-10 distilled from jit8, then kickstart) is the most promising next step once they finish.

### Note 2026-11-18 21:05: switch to the Python match core (user's restructure, c5d56ac)
- The Pi now runs the user's Python match core (`soccer/`, `rl/env.py`, `rl/evaluate.py`); Godot only draws (the live viewer). `anchor_corner` was cancelled at u234 for the switch (checkpoints kept, no full evaluation); the queue resumed with `persist_lr` at 20:58.
- Check: `persist_mix` u400 evaluated again on the new core (`logs/check/persist_mix_u400_python.txt`) vs its old Godot evaluation. Not match-for-match identical (even the greedy games differ: the old Godot core ran in 32-bit floats, the new one in 64-bit, and a tiny difference grows over a 90 s match), but the same within noise: league 2.81 ± 0.10 vs 2.88 ± 0.09, GD +2.53 vs +2.19, conceded 0.09 vs 0.19; greedy 2.88 vs 2.88; h2h RL Team 4 1.06 vs 0.88, RL Team 5 0.81 vs 0.62, start 2.06 vs 1.94; direction changes 11.48 vs 11.43/s, wall 22.1% vs 22.2%, ball in a corner 22.4% vs 22.5%.
- Consequence for judging: comparisons across the switch (a new run vs an old control) keep the same seeds but lose most of the pairing benefit, so they are less sensitive (larger se); they are still unbiased. For a close call, evaluate the control again on the new core (12 min).
- Speed: evaluation 738 s vs 1190 s (1.6x); training ~30 s per update vs ~40 s for the same worker mix (simulation 21.5 s vs ~30 s, learning step unchanged at ~8 s); rule-vs-rule matches 866 vs 477 ticks/s under load.

### Review 2026-11-19 00:35: `persist_lr` (kickstart_persist setup with lr 1e-4 instead of 5e-5, net 46-128-128-10, from kickstart u600, 400 updates; resumed at u175 after the code update; first run trained and evaluated on the Python core)
- Full evaluation u400: **2.94 ± 0.06**, GD +2.25, conceded 0.09 (greedy 3.00) vs control `kickstart_persist` u400 2.94 / +2.66 / 0.06: difference 0.00 ± 0.09, paired z 0.0; GD -0.41 (z -1.5): **no difference** (MDE 0.25). The control was evaluated on the old Godot core: the comparison is unbiased but less sensitive (see the note of 2026-11-18 21:05). u250 (best fast check, 2.92 fast): 2.78 ± 0.12, GD +2.16.
- h2h: u400 RL Team 4 0.81 (GD -0.62), RL Team 5 1.25 (-0.38), start net 2.44 (+0.94); u250 RL4 0.62, RL5 1.00. RL5 1.25 is the best value of a 46-number net so far, but on 16 games (se about 0.3) it is noise. Behaviour: 11.1 direction changes/s, 11.6 shots, 29.5 passes per match; wall 22.6% (w_wall pinned to 0 here), ball in a corner 24.3%.
- Meaning: doubling the learning rate is safe under the teacher anchor but does not lift the plateau either. Five setups (anchor, strong opponents, worker mix, lr, wall term) now end at the same place. Queue decision: `kickstart_persist_long` (600 more updates of the same setup) is cancelled before training (parked in exp/done as cancelled): a longer run of a setup that has plateaued for 400 updates is the least informative use of the Pi. Instead: distil the wider net now (`rl/distill.py --hidden 256 --out team46_w256 --rounds 4`, run by hand while the runner is idle, since it needs all 4 cores), then queue `wide_kickstart` (kickstart recipe of `kickstart` on the 46-256-256-10 net) and a re-run of the user's corner test `anchor_corner2` (the first one was cancelled at u234 for the code switch).
- 2026-11-19 01:40: distillation of the wide net done (`out_5v5/team46_w256`, 46-256-256-10, 4 DAgger rounds, 1 h on the Python core): move agreement with jit8 **87%** (the 128-wide net: 86%), kick 99%, value explained variance 0.93. Twice the width buys only one point of agreement: a first hint that the 46-vs-54 gap is more about what the observation contains than about net size; `wide_kickstart` will tell. Queued: `anchor_corner2` (running since 01:41), then `wide_kickstart`.

### Review 2026-11-19 04:20: `anchor_corner2` (anchor_wall_strong setup + w_corner 0.01, net 46-128-128-10, from kickstart u600, 300 updates, Python core)
- Full evaluation u300: **2.81 ± 0.10**, GD +2.16, conceded 0.28 (greedy 2.69) vs control `anchor_wall_strong` u300 2.81 / +2.06 / 0.41: difference 0.00 ± 0.16, paired z 0.0, GD +0.09: **no difference** (MDE 0.44; the control was evaluated on the old core). u150: 2.88 ± 0.09, GD +2.38, conceded 0.12.
- Corner (scout summary of the full evaluation): ball in a corner after our touch **12.0%** (u150 11.3%), any corner 20.2%, vs 14.4% / 23.4% for the control (scout run, old core) and 13.1% / 21.1% for the new wide start net. Direction as intended but about 2 points, which is the size of the scouting noise seen when the same checkpoint was evaluated on both cores (14.7% vs 12.7%): **not shown**. Wall time 10.4% (control 8.4%), so the wall term still works.
- h2h: u300 RL Team 4 1.12 (GD -0.25), RL Team 5 1.25 (-0.25), start net 2.25; u150 RL4 0.88, RL5 0.56. Inside the noise, but the first anchored run with both above 1.0. Behaviour: 11.8 direction changes/s, 5.9 shots (control 10.1), 27.4 passes, possession 47.9%.
- Meaning: w_corner 0.01 is too weak to see, at no cost in points: the same story as w_wall 0.005. Queued `anchor_corner_strong` (w_corner 0.04, control `anchor_wall_strong`) after `wide_kickstart`. The term stays "being tested" in docs/rewards.md.
- Also: the wide net straight out of distillation (`team46_w256`, no RL yet) scores 2.94 ± 0.06 on the full league (GD +2.31, conceded 0.16) but only 0.19 / 0.69 against RL Team 4 / 5: as strong as the best 128-wide nets against the rule bots before any RL, weak against the RL teams. `wide_kickstart` (running since 04:11, ~26 s/update, ETA ~08:30) is the test of whether RL on the wider net gets past the plateau.

### Review 2026-11-19 10:20: `wide_kickstart` (net 46-256-256-10 distilled from jit8, kickstart recipe: KL 0.5 to jit8 decaying to 0 by u600, lr 1e-4, 600 updates, Python core)
- Full evaluation u600: **2.69 ± 0.13**, GD +2.06, conceded 0.06 (greedy 3.00). vs control `kickstart` u600 (128-wide, same recipe, old core) 2.81 / +2.12 / 0.16: -0.12 ± 0.18, z -0.7: **no difference**. vs its own start (the distilled wide net, 2.94 / +2.31): -0.25 ± 0.12, paired z -2.1, p 0.035: **worse on the rule league** (fast checks drifted from 2.83 to 2.38 at u600). u100: 2.88 ± 0.09, GD +2.31.
- h2h, where it matters: u600 RL Team 4 **1.06** (GD -0.31), RL Team 5 **1.12** (-0.31), its start net 1.88 (+0.62); u100 RL4 0.69, RL5 1.12. Start (distilled, no RL): RL4 0.19, RL5 0.69. Control `kickstart` u600: RL4 0.56, RL5 0.31. Pooled over both RL teams (32 games each): 1.09 vs 0.44 for the 128-wide kickstart, a difference of about 0.65 ± 0.28 (unpaired, z about 2.3, one comparison, different cores): **suggestive, not yet established**. Behaviour: 40.6 passes per match (most of any run; control 24.8), 8.4 shots, 11.4 direction changes/s, wall 23.9% (w_wall pinned to 0), ours-in-corner 15.8%.
- Meaning: the wider net trades a little of its (saturated) rule-league score for clearly better games against the RL teams, and passes far more. That is the first sign of movement on the RL4/RL5 gap that is not just noise around 0.5–1.0, but it needs confirmation. Queued `wide_persist` (the kickstart_persist recipe, strong opponents + PFSP + persistent teacher pull, on the wide net, control `kickstart_persist`) after `anchor_corner_strong`: the 128-wide version of that recipe gave the best numbers so far, and its strong opponents are exactly RL4/RL5/jit8. A larger head-to-head evaluation (more than 8 games per side) would settle the h2h question; best run between experiments, since it needs the whole CPU.

### Review 2026-11-19 12:20: `anchor_corner_strong` (anchor_wall_strong setup + w_corner 0.04, net 46-128-128-10, from kickstart u600, 300 updates, Python core)
- Full evaluation u300: **2.69 ± 0.15**, GD +2.03, conceded 0.34 (greedy 2.88) vs control `anchor_wall_strong` u300 2.81 / +2.06 / 0.41: -0.12 ± 0.16, paired z -0.8: **no difference** (MDE 0.45). u50: 2.69 ± 0.13.
- Corner: ours-in-corner **10.0%**, any corner **16.9%** (control 14.4% / 23.4%; w_corner 0.01: 12.0% / 20.2%; u50 of this run, before the term had acted: 13.8% / 23.1%). A dose response over three weights and a drop of 4–6 points, twice the scouting noise: **the term works at 0.04**. Wall time 9.5% (w_wall 0.02 still on).
- Possible costs: possession 41.7% (other anchored runs 45–52%), 22.8 passes per match (control 29.5), 9.1 shots (10.1). League points no different. h2h: RL Team 4 1.06 (GD -0.69), RL Team 5 0.94 (-0.62), start net 1.62; inside the noise and similar to the control (1.25 / 0.69).
- Meaning: the user's corner idea is right: a 0.04 penalty cuts the time our team leaves the ball in a corner by about a third at no measurable cost in points, with a hint of less possession and fewer passes. Recommendation for the user: w_corner 0.04 can join the defaults like w_wall (not changed without their OK). Queue: `wide_persist` running (started 12:11); added `wide_wallcorner` (wide_persist + w_wall 0.02 + w_corner 0.04, control `wide_persist`): combining the two terms that each worked, on the net that looks best against RL4/RL5.

### Review 2026-11-19 16:20: `wide_persist` (kickstart_persist recipe on the wide net 46-256-256-10, from wide_kickstart u600, strong opponents + PFSP, KL 0.2 decaying slowly, lr 5e-5, 400 updates, Python core)
- Full evaluation u400: **2.94 ± 0.06**, GD +2.47, conceded 0.16 (greedy 3.00) vs control `kickstart_persist` u400 (128-wide, same recipe, old core) 2.94 / +2.66 / 0.06: 0.00 ± 0.09, z 0.0: **no difference**. vs its start (wide_kickstart u600, 2.69): +0.25 ± 0.15, z 1.7, p 0.09: no difference (it got the rule-league points back). u50: 3.00, GD +2.38.
- h2h: u400 RL Team 4 0.88 (GD -0.44), RL Team 5 1.00 (-0.25), start net 1.69; u50 0.88 / 0.25. Control `kickstart_persist`: 0.75 / 0.94. Its start (wide_kickstart u600): 1.06 / 1.12. Behaviour: 29.1 passes (the start had 40.6), 11.8 shots, possession 52.0%, wall 21.3% (w_wall pinned to 0), ours-in-corner 12.7%.
- Meaning: with the same recipe the wide net ends where the 128-wide net ended. The h2h edge of `wide_kickstart` was against a weak control (plain kickstart, 0.56 / 0.31); against the best 128-wide recipe there is no width effect. **Net size is not the limit.**
- What the evidence now says: the teacher jit8 (54 numbers, with the player slot) scores **1.67 / 2.17** against RL Team 4 / 5. Every 46-number net, whatever its width, recipe, opponents, rate or reward terms, ends at about 0.6–1.3. Distillation reaches 86–87% move agreement at both widths and no further. The missing 13% looks like information the role-free observation does not carry, and the teacher anchor keeps pulling the student towards moves it cannot represent. Changing the observation is a standing decision of the user's (46-number role-free observation): the question for the user is whether role-free derived features (for example each player's rank by distance to the ball or by depth, which do not fix a role) may be added.
- Queue: `wide_wallcorner` running (started 16:02, ETA ~19:00). Nothing added after it: a further plateaued recipe would not be informative. Next when the runner is idle: a larger head-to-head evaluation (more games per side) of the best checkpoints (`wide_persist` u400, `kickstart_persist` u400, `anchor_corner2` u300, `wide_kickstart` u600) to rank them with a smaller error than 16 games give.

### Review 2026-11-19 20:10: `wide_wallcorner` (wide_persist + w_wall 0.02 + w_corner 0.04, net 46-256-256-10, 400 updates, Python core; the code was pulled afterwards, the run itself used commit ee02fb3)
- Full evaluation u400: **2.88 ± 0.09**, GD +2.75, conceded 0.22 (greedy 3.00) vs control `wide_persist` u400 2.94 / +2.47 / 0.16: -0.06 ± 0.09, paired z -0.7; GD +0.28 (z 0.7): **no difference** (MDE 0.25). u100: 2.94 ± 0.06.
- Style (scout of the full evaluation): wall time **18.0%** (wide_persist 21.3%, u100 of this run 21.8%), ours-in-corner **12.5%** (12.7%), any corner 20.4% (u100 24.3%). Both terms move in the right direction but far less than on the 128-wide net (wall 8.4%, corner 10.0%): the wide net, which leans on the teacher pull, reacts weakly to 0.02 / 0.04.
- h2h: u400 RL Team 4 1.12 (GD -0.19), RL Team 5 0.69 (-0.62), start net 2.12 (+0.81); u100 1.31 / 1.06. Control `wide_persist`: 0.88 / 1.00. Inside the noise (16 games, se about 0.3). Behaviour: 28.6 passes, 10.4 shots, possession 49.3%.
- Meaning: combining the two terms costs nothing and helps nothing measurable in points; no new evidence on the RL4/RL5 gap. Nothing queued after it. The plateau of 46-number nets (0.6-1.3 vs RL4/RL5) stays the open problem, with the observation question to the user pending.
- Next, started right after this review: a larger head-to-head evaluation (h2h 40 games per side) of the best checkpoints to rank them with a smaller error.

### Note 2026-11-20 00:20: larger head-to-head evaluation of the four best checkpoints (80 games per reference, `logs/h2h_big/`, run while the runner was busy with the ladder; league part not used)
| checkpoint | vs RL Team 4 pts (se), GD | vs RL Team 5 pts (se), GD |
|---|---|---|
| `kickstart_persist` u400 (128-wide) | **1.09** (0.14), -0.26 | 0.90 (0.12), -0.35 |
| `wide_persist` u400 (256-wide) | 0.76 (0.11), -0.50 | **0.95** (0.13), -0.41 |
| `wide_kickstart` u600 (256-wide) | 0.93 (0.13), -0.56 | 0.85 (0.13), -0.69 |
| `anchor_corner2` u300 (128-wide) | 0.86 (0.13), -0.61 | 0.91 (0.14), -0.76 |
- All four sit at **0.76-1.09 points per game and goal difference -0.3 to -0.8** against RL Team 4 / 5; the spread between them (about 0.3) is about two standard errors at most, i.e. no checkpoint is clearly better. The earlier 16-game values (0.56-1.25) were noise around this band.
- `wide_kickstart`'s apparent edge over plain `kickstart` (1.06 / 1.12 on 16 games) shrinks to 0.93 / 0.85 on 80: that was noise. The best recipe stays `kickstart_persist` (best GD, -0.26 / -0.35), but not significantly.
- Meaning: the plateau is real and flat across width, recipe and reward terms; the teacher jit8 (54 numbers) reaches 1.67 / 2.17. Still waiting for the user's decision on role-free derived observation features, the only untested lever left under the standing decisions. `persist_wallcorner` finishes about 00:30.
