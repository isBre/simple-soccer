# Reward register: what helps, what is unsure, what hurt

One place for every reward term (and the loss terms around them), with the evidence we have. Updated by the agent after each review;
the experiment log (`docs/experiment_log.md`) has the full story, `exp/results.md` the numbers. Standing rules: reward terms come back one at a time,
no hand-made positioning for defence or keeper (decided by the user, 2026-11-14 / 2026-11-16). Weights are per decision unless said otherwise.

## 1. Beneficial or in use (the minimal set, plus w_wall)
| Term | Weight | What it does | Evidence |
|---|---|---|---|
| goals | (match result) | scoring / conceding | basis of everything |
| passing: `w_pass_prog` 0.3, `w_pass_ok` 0.05, `w_pass_fail` 0.08, `pass_individual` 1, `w_recv` 0.1 | see left | progressive and completed passes rewarded, lost passes penalised, credit to the passer, small reward to the receiver | in every run since t48 (2.25 ± 0.20); kept within the minimal set, not isolated one by one |
| cooperation: `w_key_pass` 0.25, `w_xa` 2.5, `coop_cap` 8 per match | see left | key passes and expected assists, capped so it cannot be farmed | same as above; the cap stopped farming in RL Team 5 |
| `w_open` 0.003 | | stand open for a pass (distance and clear lane) while a teammate has the ball | in the minimal set, not isolated |
| `w_space` 0.006 (radius 140) | | penalty for crowding a teammate, **only while our team has the ball** | in the minimal set; the version that also applied while defending was removed |
| `w_kick` 0.01 | | penalty for kicking when the ball is out of reach | in the minimal set |
| `random_start` 0.6 | | 60% of episodes start from a random layout | in the minimal set |
| **`w_wall` 0.02** | **default since 2026-11-18** | penalty for a player pressed against the outer wall 2+ decisions in a row | `anchor_wall_strong`: wall time **8.4%** vs 21.9% (control), 17.9% at 0.005; league 2.81 vs 2.91 (z -0.6, no cost). Added to the defaults by the user's yes |

Not rewards but loss terms that proved essential:
- **Teacher KL (kickstarting)**, `kl_coef` 0.2-0.5 towards jit8: the only thing that stopped the 46-number net drifting down. Unanchored runs (`minimal`, `wall`, `strong_opponents`) all declined; anchored ones stayed at 2.8-2.9.
- **Learning rate 5e-5** with a 30-update warm-up (3e-4 and 1e-4 drifted without an anchor).

## 2. Unsure (never tested alone on a stable line, or tested only inside a mix)
Parked in `exp/parked/`; `xga` goes first when they come back. The test belongs on the anchored line (start `kickstart` u600, KL on), one term per run against `anchor_ctrl`-style controls.
| Term | Idea | What we know |
|---|---|---|
| `w_xga` | dense version of goals conceded (opponent xG) | only seen inside the full mix (t46/t47), which declined; the RL review picked it first to retest |
| `w_win`, `w_draw` | bonus at the end of the match | only inside the full mix |
| `w_tackle` (cap `def_cap`) | tackles and interceptions | only inside the full mix |
| `w_xg` (cap `xg_cap`) | quality of own shots | only inside the full mix |
| `w_opp_half` | opponent has the ball in our half | only inside the full mix |
| `w_far`, `w_keeper`, `shaping`, `w_jitter` | too far from the ball / keeper strays / dense ball shaping / direction-change penalty | `w_jitter` helped the old 54-number line (jit7/jit8: 11 -> 2 direction changes/s) but was not tested on the 46-number net |
| pass `w_open`, `w_recv` weights | exact values | tuned by hand, never swept |

## 3. Not good (evidence against) or excluded
| Term / setup | Evidence |
|---|---|
| the **full mix** (xG, xGA, win/draw, tackles, goal-side, opp-half, compact, far) on the 46-number net | t46: 1.19 / 1.16, t47: 1.88 -> 0.66 steady decline, conceded 1.2-2.1, idle 26%. The minimal set at the same net did far better (2.25) |
| **heavier goal-side 0.01 and compact 0.008** (t47 from u100) | u100 1.88 -> u200 1.19 right after the change; reverting did not recover it. Treat as harmful until retested alone |
| **hand-made defence / keeper positioning** (goal-line cover, keeper position) | excluded by the user's decision: the net should find its own solution (e.g. high pressing without a keeper) |
| **unanchored training** (any reward set) | `minimal` 1.79 -> 0.67, `wall` 1.58 -> 0.96, `strong_opponents` 1.88 -> 1.29 within 200 updates. A loss problem, not a reward term |
| **`w_wall` 0.005** | too weak: 17.9% vs 21.9% wall time, within noise |
| more training of what we have (`kickstart_strong`, `anchor_ctrl`) | flat: +0.06 and +0.09 pts, no difference; the rule league is saturated near 3 |
