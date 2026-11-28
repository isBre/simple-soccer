"""The match core: everything a match is, without any UI. The browser game (game/ + web/: menus, tournaments, drawing,
keyboard) sits on top; training, evaluations (rl/) and the Lab's live demo (lab/live.py) use it too.

  data.py     loads the JSON files under data/: pitches, kickoff spots, players, teams
  players.py  a player: a brain with a name (a rule-based archetype + skill, or a net) and the team sizes it can play
  teams.py    a team: identity and a line-up of players (mixed line-ups allowed); no tactic, no formation
  match.py    the match at 60 ticks/s: kickoffs, touches, passes and shots, goals, golden-goal overtime, result
              (no keeper role, no shootout: every player has the same body and the same rules)
  physics.py  discs and walls: the bodies, their constants and the contacts of one tick
  control.py  the people at the controls: who plays which player, the Q switch of TEAM control
  stats.py    per-player counters          rating.py   xG of a shot, value of a pass
  rng.py      Godot's random number generator, bit for bit (kickoffs draw exactly like the Godot version)
  vec.py      2-D vector helpers on complex numbers (engine and AI)
  ai/         the AI, every player alone: view.py (the public view), agent.py (an agent's answer: buttons and a call),
              lineup.py (who drives each slot), players/ (the rule-based archetypes), kit.py (their toolkit), skill.py
              (skill -> precision), nets.py (net players), obs.py (what a net sees)

Quick use:
  from soccer.match import Match, make_config
  m = Match(make_config("aurora", "tide", "arena", 5, 90.0, seed=1)); m.run_to_end(); print(m.make_result()["scores"])"""
