# Experiment results

Updated 2026-11-26 05:57. pts = league points per match (16 rule teams, both sides), gd = goal difference per match, mean ± standard error. Verdicts compare within one protocol (fast and full are never mixed), paired over identical matches when possible. `python3 lab/lab.py` gives the same data as JSON.

| run | net | state | update | protocol | pts ± se | gd | GA | vs RL4 | vs RL5 | dir chg/s | idle % | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| anchor_batch512 | 46-128-128-10 | done | 300 | full/g1/d90 | 3.0 ± 0.0 | 2.56 | 0.19 | 1.19 | 0.81 | 11.18 | 2.0 |  |
| anchor_batch512_s11 | 46-128-128-10 | done | 300 | full/g1/d90 | 2.81 ± 0.1 | 2.0 | 0.44 | 1.12 | 0.56 | 11.72 | 3.0 |  |
| anchor_batch512_s23 | 46-128-128-10 | done | 300 | full/g1/d90 | 2.88 ± 0.09 | 2.5 | 0.53 | 0.75 | 1.31 | 11.34 | 2.0 |  |
| anchor_bb_klconst | 46-128-128-10 | done | 600 | full/g1/d90 | 2.75 ± 0.12 | 2.34 | 0.06 | 1.38 | 1.44 | 10.72 | 2.0 |  |
| anchor_bb_klconst_s11 | 46-128-128-10 | done | 600 | full/g1/d90 | 2.88 ± 0.09 | 2.19 | 0.09 | 1.06 | 0.62 | 11.76 | 2.0 |  |
| anchor_bb_klconst_s23 | 46-128-128-10 | done | 600 | full/g1/d90 | 2.94 ± 0.06 | 2.59 | 0.06 | 1.0 | 1.31 | 10.88 | 2.0 |  |
| anchor_bigbatch | 46-128-128-10 | done | 300 | full/g1/d90 | 2.94 ± 0.06 | 2.62 | 0.16 | 1.62 | 1.25 | 12.37 | 4.0 |  |
| anchor_bigbatch_s11 | 46-128-128-10 | done | 300 | full/g1/d90 | 2.88 ± 0.09 | 2.06 | 0.47 | 1.31 | 0.81 | 11.56 | 3.0 |  |
| anchor_bigbatch_s23 | 46-128-128-10 | done | 300 | full/g1/d90 | 2.94 ± 0.06 | 3.0 | 0.41 | 0.62 | 0.81 | 10.96 | 2.0 |  |
| anchor_corner | - | cancelled | 200 | fast/g2/d60 | 2.75 ± 0.14 | 1.71 | 0.0 | - | - | - | - |  |
| anchor_corner2 | 46-128-128-10 | done | 300 | full/g1/d90 | 2.81 ± 0.1 | 2.16 | 0.28 | 1.12 | 1.25 | 11.78 | 3.0 | no difference (vs anchor_wall_strong) |
| anchor_corner2 | 46-128-128-10 | done | 300 | fast/g2/d60 | 2.75 ± 0.14 | 1.54 | 0.29 | - | - | - | - |  |
| anchor_corner_strong | 46-128-128-10 | done | 300 | full/g1/d90 | 2.69 ± 0.15 | 2.03 | 0.34 | 1.06 | 0.94 | 11.19 | 2.0 | no difference (vs anchor_wall_strong) |
| anchor_corner_strong | 46-128-128-10 | done | 300 | fast/g2/d60 | 2.67 ± 0.15 | 1.79 | 0.17 | - | - | - | - |  |
| anchor_ctrl | - | done | 300 | full/g1/d90 | 2.91 ± 0.09 | 2.28 | 0.16 | 0.94 | 0.69 | 11.75 | 3.0 | no difference (vs start:x_kickstart_u600) |
| anchor_ctrl | - | done | 300 | fast/g2/d60 | 2.58 ± 0.19 | 1.46 | 0.12 | - | - | - | - |  |
| anchor_klconst | 46-128-128-10 | done | 600 | full/g1/d90 | 2.78 ± 0.12 | 2.25 | 0.09 | 0.31 | 1.0 | 10.65 | 2.0 |  |
| anchor_klconst_s11 | 46-128-128-10 | done | 600 | full/g1/d90 | 2.94 ± 0.06 | 2.41 | 0.06 | 0.88 | 1.31 | 11.17 | 2.0 |  |
| anchor_klconst_s23 | 46-128-128-10 | done | 600 | full/g1/d90 | 2.84 ± 0.11 | 2.5 | 0.09 | 1.38 | 0.94 | 12.31 | 3.0 |  |
| anchor_klslow | 46-128-128-10 | done | 300 | full/g1/d90 | 2.94 ± 0.06 | 2.5 | 0.0 | 0.81 | 1.06 | 11.17 | 2.0 |  |
| anchor_long | 46-128-128-10 | done | 900 | full/g1/d90 | 2.09 ± 0.21 | 0.84 | 1.12 | 0.62 | 0.31 | 12.65 | 4.0 |  |
| anchor_marathon | 46-128-128-10 | done | 3000 | full/g1/d90 | 3.0 ± 0.0 | 2.62 | 0.09 | 0.88 | 0.38 | 12.87 | 4.0 |  |
| anchor_pfsp | 46-128-128-10 | done | 300 | full/g1/d90 | 2.78 ± 0.12 | 2.47 | 0.53 | 0.88 | 1.44 | 11.01 | 3.0 |  |
| anchor_wall | - | done | 300 | full/g1/d90 | 2.88 ± 0.09 | 2.34 | 0.28 | 1.38 | 0.06 | 11.61 | 2.0 | no difference (vs start:x_kickstart_u600) |
| anchor_wall | - | done | 300 | fast/g2/d60 | 2.62 ± 0.17 | 1.38 | 0.38 | - | - | - | - |  |
| anchor_wall_repro | 46-128-128-10 | done | 300 | full/g1/d90 | 2.72 ± 0.13 | 2.03 | 0.5 | 0.94 | 1.06 | 11.94 | 4.0 |  |
| anchor_wall_s11 | 46-128-128-10 | done | 300 | full/g1/d90 | 2.72 ± 0.13 | 2.12 | 0.41 | 0.56 | 1.19 | 11.02 | 3.0 |  |
| anchor_wall_s23 | 46-128-128-10 | done | 300 | full/g1/d90 | 2.81 ± 0.1 | 2.84 | 0.16 | 0.81 | 1.25 | 11.49 | 2.0 |  |
| anchor_wall_s31 | 46-128-128-10 | done | 300 | full/g1/d90 | 2.62 ± 0.16 | 2.0 | 0.44 | 0.44 | 0.38 | 11.4 | 2.0 |  |
| anchor_wall_strong | - | done | 300 | full/g1/d90 | 2.81 ± 0.1 | 2.06 | 0.41 | 1.25 | 0.69 | 10.83 | 2.0 | no difference (vs start:x_kickstart_u600) |
| anchor_wall_strong | - | done | 300 | fast/g2/d60 | 2.33 ± 0.22 | 1.04 | 0.25 | - | - | - | - |  |
| anchor_xga | 46-128-128-10 | done | 300 | full/g1/d90 | 2.78 ± 0.12 | 2.19 | 0.47 | 0.5 | 0.38 | 11.76 | 2.0 |  |
| b256_corner | 46-128-128-10 | done | 300 | full/g1/d90 | 2.94 ± 0.06 | 2.56 | 0.09 | 0.81 | 0.88 | 11.98 | 3.0 |  |
| b256_corner_s11 | 46-128-128-10 | done | 300 | full/g1/d90 | 2.84 ± 0.11 | 2.34 | 0.34 | 1.25 | 0.56 | 11.39 | 2.0 |  |
| b256_corner_s23 | 46-128-128-10 | done | 300 | full/g1/d90 | 2.53 ± 0.16 | 1.72 | 0.66 | 0.62 | 0.69 | 12.85 | 4.0 |  |
| b256_long | 46-128-128-10 | done | 600 | full/g1/d90 | 2.84 ± 0.11 | 2.38 | 0.66 | 0.31 | 0.62 | 11.58 | 4.0 |  |
| b256_long_s11 | 46-128-128-10 | done | 600 | full/g1/d90 | 2.72 ± 0.13 | 2.06 | 0.41 | 1.25 | 0.75 | 10.98 | 3.0 |  |
| b256_long_s23 | 46-128-128-10 | done | 600 | full/g1/d90 | 2.94 ± 0.06 | 2.84 | 0.31 | 1.0 | 0.25 | 10.53 | 2.0 |  |
| b256_lr1e4 | 46-128-128-10 | done | 300 | full/g1/d90 | 2.88 ± 0.09 | 2.47 | 0.16 | 1.19 | 0.56 | 11.25 | 3.0 |  |
| b256_lr1e4_s11 | 46-128-128-10 | done | 300 | full/g1/d90 | 2.81 ± 0.1 | 2.28 | 0.56 | 0.75 | 0.62 | 11.66 | 3.0 |  |
| b256_lr1e4_s23 | 46-128-128-10 | done | 300 | full/g1/d90 | 3.0 ± 0.0 | 2.84 | 0.25 | 1.06 | 1.31 | 10.49 | 3.0 |  |
| b256_tackle | 46-128-128-10 | done | 300 | full/g1/d90 | 2.56 ± 0.16 | 1.72 | 0.94 | 0.25 | 0.44 | 11.19 | 3.0 |  |
| b256_tackle_s11 | 46-128-128-10 | done | 300 | full/g1/d90 | 2.81 ± 0.1 | 2.31 | 0.66 | 0.88 | 0.44 | 11.57 | 3.0 |  |
| b256_tackle_s23 | 46-128-128-10 | done | 300 | full/g1/d90 | 2.94 ± 0.06 | 2.56 | 0.34 | 1.0 | 0.69 | 10.16 | 2.0 |  |
| b256_win | 46-128-128-10 | done | 300 | full/g1/d90 | 2.75 ± 0.12 | 2.41 | 0.44 | 0.56 | 0.88 | 11.06 | 3.0 |  |
| b256_win_s11 | 46-128-128-10 | done | 300 | full/g1/d90 | 2.94 ± 0.06 | 2.75 | 0.12 | 1.38 | 0.88 | 10.57 | 2.0 |  |
| b256_win_s23 | 46-128-128-10 | done | 300 | full/g1/d90 | 2.84 ± 0.11 | 1.78 | 0.47 | 1.19 | 0.75 | 10.64 | 4.0 |  |
| b256_xg | 46-128-128-10 | done | 300 | full/g1/d90 | 2.88 ± 0.09 | 2.75 | 0.41 | 1.31 | 0.62 | 10.98 | 2.0 |  |
| b256_xg_s11 | 46-128-128-10 | done | 300 | full/g1/d90 | 2.38 ± 0.18 | 1.47 | 0.91 | 0.31 | 0.62 | 11.02 | 3.0 |  |
| b256_xg_s23 | 46-128-128-10 | done | 300 | full/g1/d90 | 2.75 ± 0.12 | 2.53 | 0.44 | 0.69 | 1.0 | 10.92 | 3.0 |  |
| gen2 | 46-128-128-10 | done | 300 | full/g1/d90 | 2.5 ± 0.19 | 1.81 | 0.5 | 1.19 | 0.88 | 11.14 | 2.0 |  |
| gen2_s11 | 46-128-128-10 | done | 300 | full/g1/d90 | 2.94 ± 0.06 | 2.72 | 0.41 | 0.56 | 0.75 | 10.38 | 1.0 |  |
| gen2_s23 | 46-128-128-10 | done | 300 | full/g1/d90 | 2.94 ± 0.06 | 2.5 | 0.16 | 1.31 | 1.56 | 11.78 | 3.0 |  |
| kickstart | 46-128-128-10 | done | 600 | full/g1/d90 | 2.81 ± 0.1 | 2.12 | 0.16 | 0.56 | 0.31 | 12.87 | 3.0 | better (vs start:t48_u100) |
| kickstart | 46-128-128-10 | done | 600 | fast/g2/d60 | 2.58 ± 0.17 | 1.58 | 0.08 | - | - | - | - |  |
| kickstart_persist | - | done | 400 | full/g1/d90 | 2.94 ± 0.06 | 2.66 | 0.06 | 0.75 | 0.94 | 11.08 | 2.0 | no difference (vs start:x_kickstart_u600) |
| kickstart_persist | - | done | 400 | fast/g2/d60 | 2.83 ± 0.11 | 1.79 | 0.0 | - | - | - | - |  |
| kickstart_strong | - | done | 400 | full/g1/d90 | 2.88 ± 0.09 | 2.25 | 0.06 | 0.81 | 0.44 | 11.6 | 2.0 | no difference (vs start:x_kickstart_u600) |
| kickstart_strong | - | done | 400 | fast/g2/d60 | 2.5 ± 0.18 | 1.58 | 0.04 | - | - | - | - |  |
| minimal | 46-128-128-10 | diverged | 200 | fast/g2/d60 | 0.67 ± 0.17 | -0.54 | 0.88 | - | - | - | - |  |
| old_jit8 | - | imported | 200 | full/g1/d90 | 2.94 ± 0.06 | 2.94 | 0.03 | 1.67 | 2.17 | 8.16 | 2.0 |  |
| old_t46 | - | imported | 200 | full/g1/d90 | 1.16 ± 0.22 | -0.1 | 1.22 | 0.56 | 0.25 | 9.87 | 3.0 |  |
| old_t47 | - | imported | 400 | full/g1/d90 | 0.66 ± 0.17 | -0.87 | 2.09 | 0.25 | 0.12 | 13.26 | 26.0 |  |
| persist_long2 | 46-128-128-10 | done | 600 | full/g1/d90 | 2.94 ± 0.06 | 2.22 | 0.09 | 1.44 | 1.12 | 11.27 | 2.0 | no difference (vs kickstart_persist) |
| persist_long2 | 46-128-128-10 | done | 600 | fast/g2/d60 | 2.83 ± 0.11 | 1.62 | 0.04 | - | - | - | - |  |
| persist_lr | 46-128-128-10 | done | 400 | full/g1/d90 | 2.94 ± 0.06 | 2.25 | 0.09 | 0.81 | 1.25 | 11.08 | 2.0 | no difference (vs kickstart_persist) |
| persist_lr | 46-128-128-10 | done | 400 | fast/g2/d60 | 2.5 ± 0.18 | 1.21 | 0.08 | - | - | - | - |  |
| persist_mix | - | done | 400 | full/g1/d90 | 2.88 ± 0.09 | 2.19 | 0.19 | 0.88 | 0.62 | 11.43 | 2.0 | no difference (vs kickstart_persist) |
| persist_mix | - | done | 400 | fast/g2/d60 | 2.58 ± 0.17 | 1.54 | 0.04 | - | - | - | - |  |
| persist_wallcorner | 46-128-128-10 | done | 400 | full/g1/d90 | 2.88 ± 0.09 | 2.84 | 0.03 | 1.0 | 0.69 | 11.3 | 2.0 | no difference (vs kickstart_persist) |
| persist_wallcorner | 46-128-128-10 | done | 400 | fast/g2/d60 | 2.67 ± 0.15 | 1.62 | 0.08 | - | - | - | - |  |
| rank_anchor | 56-128-128-10 | done | 300 | full/g1/d90 | 2.78 ± 0.12 | 1.84 | 0.34 | 1.19 | 0.75 | 10.75 | 2.0 |  |
| rank_persist | 56-128-128-10 | done | 600 | full/g1/d90 | 2.84 ± 0.11 | 2.28 | 0.09 | 1.44 | 1.19 | 11.74 | 2.0 | no difference (vs persist_long2) |
| rank_persist | 56-128-128-10 | done | 600 | fast/g2/d60 | 3.0 ± 0.0 | 2.33 | 0.0 | - | - | - | - |  |
| start:t48_u100 | - | imported | 0 | full/g1/d90 | 2.25 ± 0.2 | 0.87 | 0.75 | 0.38 | 0.0 | 11.24 | 5.0 |  |
| start:t48_u100 | - | imported | 0 | fast/g2/d60 | 1.42 ± 0.24 | 0.25 | 0.58 | 0.62 | - | - | - |  |
| start:team46_w256 | - | imported | 0 | full/g1/d90 | 2.94 ± 0.06 | 2.31 | 0.16 | 0.19 | 0.69 | 9.93 | 2.0 |  |
| start:team46_w256 | - | imported | 0 | fast/g2/d60 | 2.83 ± 0.11 | 1.67 | 0.0 | 0.75 | - | - | - |  |
| start:x_kickstart_persist_u400 | - | imported | 0 | full/g1/d90 | 2.88 ± 0.09 | 2.66 | 0.0 | 1.31 | 0.75 | 11.34 | 2.0 |  |
| start:x_kickstart_persist_u400 | - | imported | 0 | fast/g2/d60 | 2.62 ± 0.17 | 1.75 | 0.04 | 1.5 | - | - | - |  |
| start:x_kickstart_u600 | - | imported | 0 | full/g1/d90 | 2.81 ± 0.1 | 2.12 | 0.16 | 0.56 | 0.31 | 12.87 | 3.0 |  |
| start:x_kickstart_u600 | - | imported | 0 | fast/g2/d60 | 2.58 ± 0.17 | 1.58 | 0.08 | 1.12 | - | - | - |  |
| start:x_rank_start | - | imported | 0 | full/g1/d90 | 2.81 ± 0.1 | 2.69 | 0.03 | 1.31 | 0.69 | 11.81 | 2.0 |  |
| start:x_rank_start | - | imported | 0 | fast/g2/d60 | 2.83 ± 0.11 | 1.71 | 0.04 | 1.5 | - | - | - |  |
| start:x_wide_kickstart_u600 | - | imported | 0 | full/g1/d90 | 2.69 ± 0.13 | 2.06 | 0.06 | 1.06 | 1.12 | 11.44 | 3.0 |  |
| start:x_wide_kickstart_u600 | - | imported | 0 | fast/g2/d60 | 2.38 ± 0.2 | 1.21 | 0.17 | 1.25 | - | - | - |  |
| strong_opponents | 46-128-128-10 | diverged | 150 | fast/g2/d60 | 1.29 ± 0.26 | 0.08 | 0.96 | - | - | - | - |  |
| wall | 46-128-128-10 | diverged | 150 | fast/g2/d60 | 0.96 ± 0.21 | -0.25 | 1.42 | - | - | - | - |  |
| wide_b256 | 46-256-256-10 | done | 300 | full/g1/d90 | 2.81 ± 0.1 | 2.16 | 0.69 | 1.5 | 1.0 | 11.07 | 3.0 |  |
| wide_b256_s11 | 46-256-256-10 | done | 300 | full/g1/d90 | 2.75 ± 0.12 | 2.44 | 0.22 | 0.94 | 1.31 | 12.21 | 3.0 |  |
| wide_b256_s23 | 46-256-256-10 | done | 300 | full/g1/d90 | 2.59 ± 0.15 | 2.0 | 0.66 | 0.94 | 0.62 | 11.09 | 2.0 |  |
| wide_kickstart | 46-256-256-10 | done | 600 | full/g1/d90 | 2.69 ± 0.13 | 2.06 | 0.06 | 1.06 | 1.12 | 11.44 | 3.0 | no difference (vs kickstart) |
| wide_kickstart | 46-256-256-10 | done | 600 | fast/g2/d60 | 2.38 ± 0.2 | 1.21 | 0.17 | - | - | - | - |  |
| wide_persist | 46-256-256-10 | done | 400 | full/g1/d90 | 2.94 ± 0.06 | 2.47 | 0.16 | 0.88 | 1.0 | 11.14 | 2.0 | no difference (vs kickstart_persist) |
| wide_persist | 46-256-256-10 | done | 400 | fast/g2/d60 | 2.83 ± 0.11 | 1.58 | 0.04 | - | - | - | - |  |
| wide_wallcorner | 46-256-256-10 | done | 400 | full/g1/d90 | 2.88 ± 0.09 | 2.75 | 0.22 | 1.12 | 0.69 | 10.86 | 2.0 | no difference (vs wide_persist) |
| wide_wallcorner | 46-256-256-10 | done | 400 | fast/g2/d60 | 2.79 ± 0.14 | 1.79 | 0.08 | - | - | - | - |  |

Runs: anchor_batch512 (done), anchor_batch512_s11 (done), anchor_batch512_s23 (done), anchor_bb_klconst (done), anchor_bb_klconst_s11 (done), anchor_bb_klconst_s23 (done), anchor_bigbatch (done), anchor_bigbatch_s11 (done), anchor_bigbatch_s23 (done), anchor_corner (cancelled), anchor_corner2 (done), anchor_corner_strong (done), anchor_ctrl (done), anchor_klconst (done), anchor_klconst_s11 (done), anchor_klconst_s23 (done), anchor_klslow (done), anchor_long (done), anchor_marathon (done), anchor_pfsp (done), anchor_wall (done), anchor_wall_repro (done), anchor_wall_s11 (done), anchor_wall_s23 (done), anchor_wall_s31 (done), anchor_wall_strong (done), anchor_xga (done), b256_corner (done), b256_corner_s11 (done), b256_corner_s23 (done), b256_long (done), b256_long_s11 (done), b256_long_s23 (done), b256_lr1e4 (done), b256_lr1e4_s11 (done), b256_lr1e4_s23 (done), b256_tackle (done), b256_tackle_s11 (done), b256_tackle_s23 (done), b256_win (done), b256_win_s11 (done), b256_win_s23 (done), b256_xg (done), b256_xg_s11 (done), b256_xg_s23 (done), control_long (cancelled), control_seed11 (cancelled), gen2 (done), gen2_s11 (done), gen2_s23 (done), kickstart (done), kickstart_persist (done), kickstart_persist_long (cancelled), kickstart_strong (done), minimal (diverged), old_jit8 (imported), old_t46 (imported), old_t47 (imported), persist_long2 (done), persist_lr (done), persist_mix (done), persist_wallcorner (done), rank_anchor (done), rank_persist (done), start:t48_u100 (imported), start:team46_w256 (imported), start:x_kickstart_persist_u400 (imported), start:x_kickstart_u600 (imported), start:x_rank_start (imported), start:x_wide_kickstart_u600 (imported), strong_opponents (diverged), team:RL Team 4 (imported), team:RL Team 5 (imported), wall (diverged), wide_b256 (done), wide_b256_s11 (done), wide_b256_s23 (done), wide_kickstart (done), wide_persist (done), wide_wallcorner (done)
