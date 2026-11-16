# Experiment results

Updated 2026-11-16 22:20. pts = league points per match (all 16 rule teams, both sides), gd = goal difference per match, values are mean ± standard error. A difference smaller than about 2 standard errors is noise.

| run | state | update | kind | pts ± se | gd | GA | vs RL4 | vs RL5 | dir chg/s | idle % | spacing px | verdict vs start |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| minimal | running | 50 | fast | 1.79 ± 0.24 | 0.5 | 0.54 | - | - | - | - | - |  |
| old_jit8 | imported | 200 | full | 2.94 ± 0.06 | 2.94 | 0.03 | 1.67 | 2.17 | 8.16 | 2.0 | 494.0 |  |
| old_t46 | imported | 200 | full | 1.16 ± 0.22 | -0.1 | 1.22 | 0.56 | 0.25 | 9.87 | 3.0 | 456.0 |  |
| old_t47 | imported | 400 | full | 0.66 ± 0.17 | -0.87 | 2.09 | 0.25 | 0.12 | 13.26 | 26.0 | 250.0 |  |
| start:t48_u100 | imported | 0 | full | 2.25 ± 0.2 | 0.87 | 0.75 | 0.38 | 0.0 | 11.24 | 5.0 | 494.0 |  |
| start:t48_u100 | imported | 0 | fast | 1.42 ± 0.24 | 0.25 | 0.58 | 0.62 | - | - | - | - |  |

Runs: minimal (running), old_jit8 (imported), old_t46 (imported), old_t47 (imported), start:t48_u100 (imported)
