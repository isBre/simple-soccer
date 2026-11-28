# Plan: learning from the user's play (ML League, DL League)

Status: agreed plan, 2026-11-19. **Phase 1 (recorder), Phase 2 (Dataset page) and the Elo ranking (Evaluation 3) built**; the rest not yet. The user's decisions are at the end.

## The idea in one paragraph

Every team in the game is driven by one policy that decides for **one player** from that player's own 46-number observation
(`features_team`, `soccer/ai/obs.py`) and is run once per player. When the user plays, they control one player, so every decision
they make is one training example of exactly that form: (their player's observation, their direction, their kick). Recording those
gives a dataset. Models trained on it with supervised learning (imitation, "behaviour cloning") drive whole teams the same way the
RL nets do. Teams trained with classic machine learning go in a new **Machine Learning League**, teams trained with neural nets in a
new **Deep Learning League**, next to the Rule Based and Reinforcement Learning leagues.

| League | How the policy is trained | Example models |
|---|---|---|
| Rule Based | hand-written | the 16 handmade teams |
| Machine Learning | supervised, on the user's dataset, classic models | logistic regression, gradient-boosted trees, random forest, k-nearest neighbours |
| Deep Learning | supervised, on the user's dataset, neural nets | MLP of the RL net's shape (46 → h → h → 10), wider / frame-stacked variants |
| Reinforcement Learning | PPO from rewards (existing) | RL Team 1-5, the `x_*` runs |

## Phase 1: record the dataset (game side)

- Where: `game/session.py`, which already runs the match and receives the user's keys. A recorder samples **every 2 ticks** (the AI's
  decision rate, `REPEAT = 2`, 30 decisions/s) while a human-controlled player exists and the match is in play (no kickoff intro,
  pause or goal celebration).
- Per decision:
  - `obs`: `features_team(m, controlled)` (46 numbers), the model input;
  - `state`: the raw positions and velocities of all 10 players and the ball, score, clock, kickoff / celebration flags, the
    controlled player's uid and role. With this, any future observation (e.g. role-free extras, the 54-number one) can be recomputed
    without replaying;
  - `action`: the raw key direction (dx, dy), the nearest of the 9 net moves (`DIRS`, 0 = stand), kick held (0/1).
- Per match: date, home / away team, the user's side, control mode (single / team), duration, result, the user's player stats.
- Files: one compressed `.npz` per match in `data/human/` plus an `index.jsonl`. About 2,700 rows and under 1 MB per 90 s match.
- A "Record my play" switch on the match setup page (default on) and a small REC mark during the match.
- Done when: a played match produces a file, and a reader script can load it and replay the stored states.
- **Built (2026-11-19):** `game/recorder.py`, hooked into `game/session.py`; "Your player" (auto / GK / DEF / MID / FWD) and
  "Dataset" (record or not) on the Quick Match page and the tournament's Match Day; a REC mark in the match HUD; a picked keeper
  stays in goal at kickoffs (`MatchConfig.human_role`). Reader: `il/human_data.py` (`--check` rebuilds every observation from the
  raw state: identical to 1e-7). Checked by `tests/test_web.py` ("record"). Rows are only taken while the match is in play (no
  goal celebration, no pause, no kickoff intro), at x1 to x8 speed (the speed is stored per row).

## Phase 2: the Dataset page in the Lab

New route `#/dataset` in `web/lab/dataset.js`, API `/api/dataset` in `lab/dashboard.py` (read-only, like the rest).

- **Overview**: matches, minutes, decisions; by control mode and by opponent; the user's W/D/L and goals.
- **Actions**: the 9-move compass (how often each direction), kick rate, standing still %, **direction changes per second** next to
  the nets' (~11/s) and the rule bots' (~2/s).
- **Where**: heatmaps of the user's player, of the ball while they play, of their kicks (normalised so they always attack right).
- **Situations / coverage**: distance to the ball, on-ball vs off-ball time, attacking vs defending, by role of the controlled player.
  This shows which situations the dataset has hardly any examples of (expected gap: off-ball positioning, the keeper).
- **Reaction lag**: how many decisions later the user's moves best match the situation (from the Phase 3 fits); converted to ms.
  (Not built yet: it needs the Phase 3 models.)
- **Matches**: a table per recorded match, and a replay of any match from the stored states (the Lab already draws matches,
  `web/draw.js`) with the user's input drawn as an arrow.
- **You vs the leagues**: the user's results against every team they played, grouped by league (see Evaluation, level 4).
- **Built (2026-11-19):** `il/analysis.py` (cached until a file changes), `/api/dataset` and `/api/dataset/match/<id>` in
  `lab/dashboard.py`, the page `#/dataset` in `web/lab/dataset.js` (nav "Dataset", kiosk rail "Data"): KPIs, the moves as an octagon radar,
  direction changes and standing still against the newest full evaluation's net and rule bots (same definitions as
  `rl/evaluate.py`), heatmaps (player, ball, kicks), coverage by distance to the ball and by depth rank among the user's 5 (keeper
  included) with "thin" marks under a minute of examples, moves by situation, the match table and a replay (play / pause, speed,
  seek, the held direction as an arrow, red ring while kicking). Checked by `tests/test_web.py` ("dataset").

## Phase 3: the shared training base

New folder `il/` (imitation learning), used by both pipelines:

- `il/dataset.py`: loads `data/human/`, filters (control mode, date, opponent), **splits by match** (never by row: neighbouring rows
  are nearly identical, a row split would leak), applies the lag shift, and recomputes features from `state` when asked.
- `il/offline.py`: offline metrics on the held-out matches: move accuracy, top-2 accuracy, log loss, kick F1, each split by situation
  (on ball / off ball, attacking / defending). Reference baselines: "always run at the ball", and how often the rule bots and the best
  RL net would have made the user's move.
- Runtime: a team in a match is driven by a brain per seat (`p.brain`, soccer/core/match.py). DL models export to the existing net JSON format, so
  `NetBot` plays them with no new code. ML models need a small `ModelBot` in `soccer/ai/` (loads the saved model, batches the 5
  players per call like `NetBot`, samples or takes the most likely move).
- **No fixed roles, also here** (user, 2026-11-19): the model drives all 5 players, keeper slot included, like the RL nets. Roles must
  come from the context ("I am the last one back, so I stay back"), which is exactly what the user shows when they defend. So the
  dataset needs the user to play **deep and defensive situations too**, not only on the ball: in single mode the user can pick which
  player to control (any slot, keeper included); the Dataset page shows the coverage by depth rank so the gaps are visible.
- Per-player bots (`cfg.nets[t]` as a list of 5) are not needed for this; they stay a possible later tool for diagnosis.

## Phase 4: the ML and DL pipelines (in the existing runner)

Same queue, same runner (`lab/exp_runner.py`), same files, same dashboard. A spec gets a `kind`:

```json
{"name": "ml_hgb_lag3", "kind": "ml", "model": "hgb", "params": {"max_depth": 8},
 "data": {"control": "any", "lag": 3}, "control": "ml_logreg", "notes": "why"}
{"name": "dl_mlp256", "kind": "dl", "model": "mlp", "params": {"hidden": 256, "epochs": 40, "frames": 1},
 "data": {"control": "any", "lag": 3}, "notes": "why"}
```

The runner for `ml` / `dl`: build the dataset → train (`il/train_ml.py` with scikit-learn, `il/train_dl.py` with torch;
minutes) → offline metrics → game evaluations (below) → verdict against `control`. A finished run can be **promoted** to a team in its
league (`lab.py promote RUN --name "..."` writes `data/teams/<id>.json` with `"league": "ml"|"dl"` and the model under
`data/models/`). `game/api.py` gets the two new leagues. Runs, Run pages and Compare in the Lab show them like RL runs, with an
extra "Offline" tab.

First runs per league: ML: logistic regression (floor), gradient-boosted trees, random forest, kNN. DL: MLP in the RL net's shape
(also usable as a PPO start later), a wider MLP, an MLP with the last 3-4 observations stacked (gives it speed and direction of play).

## Evaluation (the open problem)

The rule bots are too weak to rank good teams (league points saturate at 3) and offline accuracy does not predict strength (the
distillation reached 86% agreement and still played much worse than its teacher). Proposal: five levels, each with one job.

1. **Offline** (seconds): accuracy / log loss on held-out matches. Only to pick settings **within** a league, never to rank teams.
2. **Floor** (the existing fast check vs the rule teams): only "it does not fall apart". Kept because it is cheap and paired.
3. **Strength: one Elo ranking for all four leagues** (user, 2026-11-19), updated from time to time.
   - Who is ranked: every team of every league (rule teams, RL Team 1-5, jit8, the best checkpoint of each run, ML and DL teams).
   - How it is updated: a **ladder job** in the runner plays rounds of matches when the queue is idle and a short block after every
     finished run. Each round picks pairs with close ratings and few games between them (the most informative matches), plays them on
     both sides with fixed seeds, and appends the results to `exp/ladder.jsonl`.
   - New team: placement matches against ~6 teams spread over the ranking, then it joins the normal rounds.
   - The rating is recomputed from **all** stored results each time (Bradley-Terry with draws, shown on the Elo scale), not updated
     match by match: the order of matches does not matter and every rating gets a 95% interval.
   - Where it shows: a **Ranking** page in the Lab (table by league and overall, rating history, interval bars) and the ratings in the
     game's team picker.
   - Optional fun: **"You"** in the ranking, from the user's recorded matches. Only indicative, because the user's teammates are the
     team's AI.
   - Points vs rule bots stay as the floor check (level 2). Whether the RL runs' verdicts switch to the ranking is decided once it runs.
   - **Built (2026-11-19):** `lab/ladder.py` (roster from the files, informative pairs, Bradley-Terry fit with a N(1500, 400) prior and
     95% intervals, results in `exp/ladder.jsonl`, snapshots in `exp/ladder_ratings.jsonl`; a changed file starts that entry over),
     rounds played by the runner whenever the queue is empty (`exp/ladder_off` stops it), `lab.py ranking`, `/api/ranking`, the Lab's
     **Ranking** page. Nets of the `models/` folder and finished runs' `out_5v5/ckpt/x_*_best.json` play with RL Team 5's squad.
     Seeded with about 1,900 matches. Not yet: "You" in the ranking, the ratings in the game's team picker.
4. **Likeness: "does it play like you"**, only for ML/DL: distance between the model's scouting numbers and the user's dataset (direction
   changes/s, kick rate, distance to the ball, heatmap overlap, passes and shots per minute). One score 0-100 plus the per-metric gaps.
5. **The user**: every recorded match already stores the opponent and the result, so the user's record against each team is free.
   Few games, but the most honest test, and the Dataset page shows it.

Expectation: pure imitation from a few dozen matches will most likely rank **below** the RL teams on the ladder (it copies a human
with a reaction lag, from limited data, with no keeper examples). The likely gain is style (fewer direction changes) and, later, a
hybrid: the user's dataset as an anchor during PPO (like the `kickstart` term), see decision 1.

## Order of work and checkpoints

1. Recorder + file format + reader + single-mode player pick (Phase 1). User plays ~5 matches: check the files.
2. Dataset page (Phase 2) on those matches. User plays more: aim ~20 matches (~55k decisions), both modes, deep situations included.
3. Elo ranking (Evaluation 3) first for the existing teams: useful on its own, and it gives the reference ratings before ML/DL exist.
4. Training base + offline metrics + `ModelBot` (Phase 3).
5. ML pipeline + ML League (Phase 4), first runs, placed in the ranking.
6. DL pipeline + DL League, first runs, placed in the ranking.
7. Likeness score; the user's record vs teams on the Dataset page.

## Decisions (user, 2026-11-19)

1. Hybrid (user data, then PPO): **not now**. Pure imitation first; decide after seeing how they play.
2. Keeper: **the model drives all 5, no fixed roles**; roles come from the context, the user will defend sometimes.
3. Dataset: **committed to git** (`data/human/`). Recordings land in `data/human/` and are committed with the usual results commits.
4. Evaluation: **an Elo ranking over all teams of all leagues**, updated from time to time by the runner.
