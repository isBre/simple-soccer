"""The match core: everything a match is, without any UI. The browser game (game/ + web/: menus, tournaments, drawing,
keyboard) sits on top; training, evaluations (rl/) and the Lab's live demo (lab/live.py) use it too.

  data.py     loads the JSON files under data/: pitches, styles, formations, players, teams
  players.py  a player: a brain with a name (rule-based style + skill, Opus, or a net) and the team sizes it can play
  teams.py    a team: identity and a line-up of players (mixed line-ups allowed); no tactic, no formation
  match.py    the match: physics at 60 ticks/s, kickoffs, touches, passes and shots, goals, golden-goal overtime, result
              (no keeper role, no shootout: every player has the same body and the same rules)
  stats.py    per-player counters          rating.py   xG of a shot, value of a pass
  rng.py      Godot's random number generator, bit for bit (kickoffs draw exactly like the Godot version)
  vec.py      2-D vector helpers on complex numbers
  ai/         the AI: lineup.py (who drives each slot), skill.py (skill -> precision), rules.py (team brain + rule bots),
              opus.py (the Opus planner), nets.py (net players, observations)

Quick use:
  from soccer.match import Match, make_config
  m = Match(make_config("aurora", "tide", "arena", 5, 90.0, seed=1)); m.run_to_end(); print(m.make_result()["scores"])"""
