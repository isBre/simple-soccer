"""The brains that play: every player decides alone, from its team's public view (soccer.core.view, docs/public_view.md),
and answers with an Act (soccer.core.act). A rule-based player is an archetype with its own algorithm (players/, on the shared
toolkit kit.py and its skill, skill.py), a net player a NetBot (nets.py, seeing what obs.py computes), a person a Person
(person.py). The match (soccer.core.match) asks them when they are due; soccer.game seats them."""
