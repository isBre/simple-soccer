"""The game's AI, in Python. Godot runs the physics, the match rules and the drawing; every decision a bot takes (rule-based
teams and neural-net teams alike) is made here. Godot talks to `brain/server.py` over a local TCP socket (`brain/protocol.py`).

Modules:
  vec.py       2-D vectors as Python complex numbers (fast, no dependencies)
  match.py     the match as the AI sees it: pitch, players, ball, ball history, score, kickoff (rebuilt from Godot's snapshots)
  rules.py     rule-based AI: TeamBrain (who chases, who keeps goal, marking, interceptions) and StyleBot (one player)
  nets.py      neural-net teams: observations, net loading, forward pass, sampling
  protocol.py  wire format between Godot (scripts/core/brain_link.gd) and the server
  server.py    the TCP server (one session per match)
"""
