# Experiment results

Updated 2026-11-18 22:36. pts = league points per match (16 rule teams, both sides), gd = goal difference per match, mean ± standard error. Verdicts compare within one protocol (fast and full are never mixed), paired over identical matches when possible. `python3 rl/lab.py` gives the same data as JSON.

| run | net | state | update | protocol | pts ± se | gd | GA | vs RL4 | vs RL5 | dir chg/s | idle % | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| anchor_corner | 46-128-128-10 | cancelled | 200 | fast/g2/d60 | 2.75 ± 0.14 | 1.71 | 0.0 | - | - | - | - |  |
| anchor_ctrl | 46-128-128-10 | done | 300 | full/g1/d90 | 2.91 ± 0.09 | 2.28 | 0.16 | 0.94 | 0.69 | 11.75 | 3.0 | no difference (vs start:x_kickstart_u600) |
| anchor_ctrl | 46-128-128-10 | done | 300 | fast/g2/d60 | 2.58 ± 0.19 | 1.46 | 0.12 | - | - | - | - |  |
| anchor_wall | 46-128-128-10 | done | 300 | full/g1/d90 | 2.88 ± 0.09 | 2.34 | 0.28 | 1.38 | 0.06 | 11.61 | 2.0 | no difference (vs start:x_kickstart_u600) |
| anchor_wall | 46-128-128-10 | done | 300 | fast/g2/d60 | 2.62 ± 0.17 | 1.38 | 0.38 | - | - | - | - |  |
| anchor_wall_strong | 46-128-128-10 | done | 300 | full/g1/d90 | 2.81 ± 0.1 | 2.06 | 0.41 | 1.25 | 0.69 | 10.83 | 2.0 | no difference (vs start:x_kickstart_u600) |
| anchor_wall_strong | 46-128-128-10 | done | 300 | fast/g2/d60 | 2.33 ± 0.22 | 1.04 | 0.25 | - | - | - | - |  |
| kickstart | 46-128-128-10 | done | 600 | full/g1/d90 | 2.81 ± 0.1 | 2.12 | 0.16 | 0.56 | 0.31 | 12.87 | 3.0 | better (vs start:t48_u100) |
| kickstart | 46-128-128-10 | done | 600 | fast/g2/d60 | 2.58 ± 0.17 | 1.58 | 0.08 | - | - | - | - |  |
| kickstart_persist | 46-128-128-10 | done | 400 | full/g1/d90 | 2.94 ± 0.06 | 2.66 | 0.06 | 0.75 | 0.94 | 11.08 | 2.0 | no difference (vs start:x_kickstart_u600) |
| kickstart_persist | 46-128-128-10 | done | 400 | fast/g2/d60 | 2.83 ± 0.11 | 1.79 | 0.0 | - | - | - | - |  |
| kickstart_strong | 46-128-128-10 | done | 400 | full/g1/d90 | 2.88 ± 0.09 | 2.25 | 0.06 | 0.81 | 0.44 | 11.6 | 2.0 | no difference (vs start:x_kickstart_u600) |
| kickstart_strong | 46-128-128-10 | done | 400 | fast/g2/d60 | 2.5 ± 0.18 | 1.58 | 0.04 | - | - | - | - |  |
| minimal | 46-128-128-10 | diverged | 200 | fast/g2/d60 | 0.67 ± 0.17 | -0.54 | 0.88 | - | - | - | - |  |
| old_jit8 | - | imported | 200 | full/g1/d90 | 2.94 ± 0.06 | 2.94 | 0.03 | 1.67 | 2.17 | 8.16 | 2.0 |  |
| old_t46 | - | imported | 200 | full/g1/d90 | 1.16 ± 0.22 | -0.1 | 1.22 | 0.56 | 0.25 | 9.87 | 3.0 |  |
| old_t47 | - | imported | 400 | full/g1/d90 | 0.66 ± 0.17 | -0.87 | 2.09 | 0.25 | 0.12 | 13.26 | 26.0 |  |
| persist_lr | 46-128-128-10 | running | 150 | fast/g2/d60 | 2.67 ± 0.15 | 1.83 | 0.04 | - | - | - | - |  |
| persist_mix | 46-128-128-10 | done | 400 | full/g1/d90 | 2.88 ± 0.09 | 2.19 | 0.19 | 0.88 | 0.62 | 11.43 | 2.0 | no difference (vs kickstart_persist) |
| persist_mix | 46-128-128-10 | done | 400 | fast/g2/d60 | 2.58 ± 0.17 | 1.54 | 0.04 | - | - | - | - |  |
| start:t48_u100 | - | imported | 0 | full/g1/d90 | 2.25 ± 0.2 | 0.87 | 0.75 | 0.38 | 0.0 | 11.24 | 5.0 |  |
| start:t48_u100 | - | imported | 0 | fast/g2/d60 | 1.42 ± 0.24 | 0.25 | 0.58 | 0.62 | - | - | - |  |
| start:x_kickstart_u600 | - | imported | 0 | full/g1/d90 | 2.81 ± 0.1 | 2.12 | 0.16 | 0.56 | 0.31 | 12.87 | 3.0 |  |
| start:x_kickstart_u600 | - | imported | 0 | fast/g2/d60 | 2.58 ± 0.17 | 1.58 | 0.08 | 1.12 | - | - | - |  |
| strong_opponents | 46-128-128-10 | diverged | 150 | fast/g2/d60 | 1.29 ± 0.26 | 0.08 | 0.96 | - | - | - | - |  |
| wall | 46-128-128-10 | diverged | 150 | fast/g2/d60 | 0.96 ± 0.21 | -0.25 | 1.42 | - | - | - | - |  |

Runs: anchor_corner (cancelled), anchor_ctrl (done), anchor_wall (done), anchor_wall_strong (done), control_long (cancelled), control_seed11 (cancelled), kickstart (done), kickstart_persist (done), kickstart_strong (done), minimal (diverged), old_jit8 (imported), old_t46 (imported), old_t47 (imported), persist_lr (running), persist_mix (done), start:t48_u100 (imported), start:x_kickstart_u600 (imported), strong_opponents (diverged), team:RL Team 4 (imported), team:RL Team 5 (imported), wall (diverged)
