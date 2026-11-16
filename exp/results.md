# Experiment results

Updated 2026-11-16 22:55. pts = league points per match (16 rule teams, both sides), gd = goal difference per match, mean ± standard error. Verdicts compare within one protocol (fast and full are never mixed), paired over identical matches when possible. `python3 rl/lab.py` gives the same data as JSON.

| run | state | update | protocol | pts ± se | gd | GA | vs RL4 | vs RL5 | dir chg/s | idle % | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| minimal | running | 50 | fast/g2/d60 | 1.79 ± 0.24 | 0.5 | 0.54 | - | - | - | - |  |
| old_jit8 | imported | 200 | full/g1/d90 | 2.94 ± 0.06 | 2.94 | 0.03 | 1.67 | 2.17 | 8.16 | 2.0 |  |
| old_t46 | imported | 200 | full/g1/d90 | 1.16 ± 0.22 | -0.1 | 1.22 | 0.56 | 0.25 | 9.87 | 3.0 |  |
| old_t47 | imported | 400 | full/g1/d90 | 0.66 ± 0.17 | -0.87 | 2.09 | 0.25 | 0.12 | 13.26 | 26.0 |  |
| start:t48_u100 | imported | 0 | full/g1/d90 | 2.25 ± 0.2 | 0.87 | 0.75 | 0.38 | 0.0 | 11.24 | 5.0 |  |
| start:t48_u100 | imported | 0 | fast/g2/d60 | 1.42 ± 0.24 | 0.25 | 0.58 | 0.62 | - | - | - |  |

Runs: minimal (running), old_jit8 (imported), old_t46 (imported), old_t47 (imported), start:t48_u100 (imported), team:RL Team 4 (imported), team:RL Team 5 (imported)
