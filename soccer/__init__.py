"""The game in three layers, each importing only the ones above it in this list:

  core/   the game itself and nothing that plays it: the rules and physics of a match at 60 ticks/s (match.py, physics.py), what
          a player may see (view.py, public.py) and answer (act.py), seeded random numbers, stats, the value of shots and passes.
          Every player is a seat; whatever decides for it is a brain plugged in from outside.
  ai/     the brains: rule-based archetypes (players/, on kit.py and skill.py), net players (nets.py, seeing obs.py), a person
          at the controls (person.py). Each decides alone from its team's public view (docs/public_view.md).
  game/   a match between two teams: the config (setup.py), who sits in each seat (seating.py), the people at the controls and
          TEAM-mode switching (humans.py), new_match / new_game (play.py).

  data.py, players.py, teams.py   the JSON files under data/: pitches, kickoff spots, players, teams

Quick use:
  from soccer.game import make_config, new_match
  m = new_match(make_config("aurora", "tide", "arena", 5, 90.0, seed=1)); m.run_to_end(); print(m.make_result()["scores"])"""
