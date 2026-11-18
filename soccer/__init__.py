"""The match core: everything a match is, without any UI. Godot (menus, tournaments, drawing, keyboard) sits on top and
plays its matches through server.py; training and evaluations (rl/) use it directly.

  data.py     pitches, styles, teams, formations and line-ups (the JSON files under data/)
  match.py    the match: physics at 60 ticks/s, kickoffs, touches, passes and shots, goals, overtime, shootouts, result
  stats.py    per-player counters          rating.py   grades (1-10) and xG
  rng.py      Godot's random number generator, bit for bit (kickoffs and shootouts draw exactly like the Godot version)
  vec.py      2-D vector helpers on complex numbers
  ai/         the AI: rules.py (team brain + rule bots), nets.py (net teams, observations)
  server.py   the TCP server Godot's MatchClient talks to

Quick use:
  from soccer.match import Match, make_config
  m = Match(make_config("aurora", "tide", "arena", 5, 90.0, seed=1)); m.run_to_end(); print(m.make_result()["scores"])"""
