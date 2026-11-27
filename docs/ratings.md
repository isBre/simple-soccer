# Ratings: Elo for every player and team, per team size

Every player and every team has an Elo rating **per team size** (1v1 to 5v5), measured from matches played **on this machine**.
The results live in a local database (`local/elo.db`, git-ignored, never pushed); a fresh clone builds its ratings once and
keeps refining them in the background. The code is `elo/`; `tests/test_elo.py` checks the model.

## After cloning

```bash
python3 -m elo init
```

`init` plays until every entry has 30 games at every size it can play (about 10 minutes on a MacBook Air, about 3x that on a
Raspberry Pi 4); `--full` goes on to 100 games (about 35 minutes), `--minutes M` stops earlier and can be run again later. After
that the web app refines the ratings by itself whenever the machine is idle (see Background).

## What is rated

| Entry | Id | What it is |
|---|---|---|
| Player | `player:<id>` | every player of `data/players`, played as a team of five copies of itself, at every size it can play |
| Team | `team:<id>` | every team with at least two different players (curated, mixed, built in the game) |
| Checkpoint | `net:<stem>` | the Lab's training checkpoints: `models/*.json` that is no player's net, and the best checkpoint of every finished run (5v5) |

A team made of one player five times *is* that player's entry: it is listed under its own name with the player's numbers.
Nets that only understand 5v5 (every net so far) appear only in the 5v5 ratings.

## The model (`elo/model.py`)

- **Strength.** Every player (and checkpoint) has a strength per size. A team's strength is the **average strength of the players
  on the pitch** at that size (the first N of its line-up who can play it) **plus a small team bonus** (synergy). The chance that A
  beats B is a logistic of the difference (400 Elo points = 10:1 odds); a draw counts half.
- **Fit.** One fit per size over all results at once (the order of the matches does not matter): maximum a posteriori with
  Gaussian priors, a player's strength ~ N(0, 400 Elo) and a team bonus ~ N(0, 50 Elo), so a bonus stays near 0 unless the
  results clearly show it. Players and teams come out of the same fit.
- **Pinned scale.** At every size the **average rule-based player is 1500**. Adding entries does not move the scale, so numbers
  stay comparable over time on this machine.
- **Intervals.** "± N" is the 95% interval of a rating relative to that average (from the covariance of the fit). An entry with
  fewer than 6 games is **provisional**.
- **Goals.** A Poisson model of the goals (every entry has an attack and a defence strength) gives the goals scored and conceded
  per 90 s match against the average opponent (`agf`, `aga`), adjusted for who was met: a strong team that only meets strong
  teams scores fewer raw goals.
- **Cost.** The fit uses the results summed per pairing, so a refit costs the same with a thousand games as with a million.

Matches: arena, 90 s, draws allowed, every pair twice with the same seed, once from each side.

## Which matches are played (`elo/schedule.py`)

- **Placement first:** an entry with fewer than 6 games plays opponents spread over the ranking (a random quantile each time).
- **Then the most informative pairs:** close ratings, uncertain ratings, pairs that rarely met.
- **The size** that needs it most: the one with the most unplaced entries, else the one with the fewest games per entry.
- A team you build in the game gets its placement games from the next rounds.

## When results stop counting

- **A file changes:** every entry carries a hash of the files its play depends on (a player's file, its style or its net; a
  team's line-up and its players). A changed file makes the old results of every entry it takes part in stop counting (they
  stay in the database, marked stale on the Ranking page).
- **The game changes:** `elo.ENGINE` is bumped together with a re-recording of the golden tests (`tests/golden/`) for an
  intended change of behaviour; results of another engine stop counting.
- **Starting over** is a decision of the user: `python3 -m elo archive --yes` (or `python3 lab/lab.py ladder archive --yes`)
  moves the database to `local/elo_archive/<date>.db`.

## Background

The web app (`web/app.py`, unless `--no-helpers`) runs `elo.api.refine`: a round of 4 pairs on 2 niced workers whenever the load
average is low (no training run, no other heavy work), nothing while `local/refine_off` exists, one refiner per machine. The
training runner plays rounds when its queue is empty and places a finished run's best checkpoint at 5v5 right away (`lab/ladder.py`).

## Storage (`elo/db.py`)

SQLite in WAL mode (the web app, the runner and a terminal can write at once): `results` (one row per match: time, size, both
entries and their file hashes, the side, goals, seed, engine, machine), `history` (a snapshot of a size's ratings after every
round, thinned to one per hour after 6 hours), `meta`.

## Commands

```bash
python3 -m elo status
```

```bash
python3 -m elo rank --size 3
```

```bash
python3 -m elo round --pairs 8 --rounds 5
```

`roster` lists who is rated (sizes, file hashes, aliases), `refine` runs the background loop in a terminal. The game shows the
**Rankings** (`#/game/rankings/<size>`: players and teams) and every team's and player's Elo per size; the Lab's **Ranking** page
shows every entry of a size, the checkpoints included (`python3 lab/lab.py ranking --size 5`).

## Reading the numbers

- Two ratings differ when their 95% intervals do not overlap.
- Ratings are **this machine's**: another machine has its own database and its own numbers, close but not identical.
- The old team ladder (`exp/ladder.jsonl`, before players existed) is archived and not on this scale; so are the estimated Elo
  values of training runs before 2026-11-27 (`exp/elo_estimates.jsonl`).
