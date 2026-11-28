# The public view: what a player may know

Every player of a match decides from the same information, whatever drives it: a rule-based bot, a neural net, or any agent
you write. This page is the specification; `soccer/ai/view.py` implements it and `tests/test_view.py` enforces it.

## The rule

A player may use **what a spectator in the stadium could know**, and **anything it computes from that**: inferring,
predicting, simulating forward, searching, remembering. It never sees the match engine or another agent's inside.

Players are **anonymous**: nobody knows who another player is, what kind of brain it has or how good it is. A player knows
its own skill and nothing else about anyone. No team, no tactic and no player can adapt to particular opponents or teammates.

Every player **decides alone**. There is no team brain: nobody commands anybody, and no agent reads or holds another agent,
teammates included. Players talk only through their **calls** (below).

## What is in the view

| Group | Field (`View`) | Meaning |
|---|---|---|
| Ball | `ball_pos`, `ball_vel`, `ball_r` | position (px, complex: x = `.real`, y = `.imag`), velocity (px per tick), radius |
| Players | `team_lists[team]`, `in_play[team]`, `players`, `bodies[uid]` | every player as a `Body` (`team_lists` the full line-ups; `in_play` and `players` only the bodies on the pitch: they differ only in training, which can take players off the pitch): `uid`, `team`, `slot` (line-up order), `radius`, `pos`, `vel`, `spawn` (kickoff position), `home` and `line` (kickoff spot and its line: GK / DEF / MID / FWD, the same layout for every team) |
| History | `ball_at(delay)`, `pos_at(uid, delay)` | the ball and every player `delay` ticks ago, for the last `HIST` = 32 ticks |
| Clock | `tick`, `time_left`, `duration`, `overtime` | the match clock (60 ticks per second), seconds left, match length, golden-goal overtime on |
| Score | `scores` | `[team 0, team 1]` |
| State | `state`, `celebrating()` | playing, or a goal being celebrated (`soccer.match.PLAYING`, `GOAL`) |
| Kickoff | `kickoff_active`, `kickoff_team`, `kickoff_taker` | a kickoff is on, whose it is, which body takes it |
| Touches | `last_touch`, `last_touch_tick` | the body that touched the ball last, and when (it could be inferred from the history) |
| Pitch | `pitch` | its size, goals, walls and obstacles (`soccer.data.Pitch`) |
| Physics | `soccer.match`: `KICK_STRENGTH`, `KICK_RANGE`, `BALL_DAMPING` (0.99), `PLAYER_DAMPING` (0.96), `PLAYER_ACCEL` (0.1), `PLAYER_KICK_ACCEL` (0.07), `AI_PERIOD` | the rules of motion are public: anyone may simulate the ball and the players forward from the view |
| Helpers | `attack_dir(team)`, `deepest(team)` | +1 / -1 (the direction a team attacks), the body nearest a team's own goal line (who seems to guard it) |

Direction: team 0 attacks towards +x, team 1 towards -x. Every Body is the same object for the whole match (updated in place
each tick), so an agent may remember bodies between ticks.

## What a team knows about itself: its calls

On its own bodies a team also sees:

- `intent`: what that teammate calls, one of `soccer.match.INTENTS`, and `intent_tick`, since when. A call is cheap talk:
  nobody has to obey it. Every agent makes one with each decision; it reaches the teammates on the next tick (everyone decides
  from the view as it was at the start of the tick).

| Call | Means | Typical use |
|---|---|---|
| `none` | nothing to say | the default; the nets of this generation; a player a person controls |
| `ball` | "mine": I'm going for the ball, or I have it | two teammates do not chase the same ball |
| `open` | "pass to me": I'm free, give it to my feet | the carrier looks for whoever calls |
| `run` | "I'm running": play it into the space ahead of me | through balls |
| `cover` | "I've got the back": I stay between the ball and our goal | the others push up; nobody else needs to guard |

- `is_human`: the player is controlled by a person (the bots leave the ball to them and do not run into them;
  `View.human_mates` lists them).

`View.kickoff_go` (the tick your kickoff taker kicks) is set only on the kicking team's view. The opponents' calls are never in
a team's view: on their bodies `intent` stays `"none"` and `is_human` `False`.

## The agent interface

An agent controls one player. Every tick it is due (every `AI_PERIOD` = 2 ticks, alternating by slot), the match calls it
with its team's view and its own body:

```python
from soccer.ai.agent import Act

class MyBot:
    def decide(self, view, me):
        """Returns an Act: dir (complex, length <= 1, world frame), kick (bool), intent (a call, soccer.match.INTENTS) and
        kind ("pass", "shoot", "clear", "long" or "": only labels the kick for the statistics)."""
        to_ball = view.ball_pos - me.pos
        near = abs(to_ball) < me.radius + view.ball_r + 4.0
        return Act(to_ball / max(abs(to_ball), 1.0), near, "ball", "shoot" if near else "")
```

The rule-based players (`soccer/ai/players/`) are archetypes, each with its own algorithm on the shared base (`base.py`:
senses, kickoff, whose ball, guarding, striking) and toolkit (`soccer/ai/kit.py`: ball prediction, interception, lanes,
shots, running, goal guarding). A player of `data/players` names its archetype (`algorithm`), its `settings` and its `skill`.

Nets use the same interface through `NetBot` (`soccer/ai/nets.py`): an observation built from the view
(`features_group(view, bodies, n_in)`), one forward pass for all the net's players of the tick, then `act(view, me, outputs)` returns its Act (the nets of this
generation call nothing).
The observations are functions of the view:

| Observation | Inputs | Contents |
|---|---|---|
| `team` | 46 | me, my 4 teammates nearest first, the 5 opponents nearest first (position and velocity, mirrored so the team attacks +x), the ball, kickoff on, goal celebration |
| `rank` | 56 | `team` + for me and my teammates the rank by distance to the ball and by depth |
| `legacy` | 54 / 49 | the first RL nets: an ego view with the player's slot |

A new agent can use all of the view or any part of it; a new observation is a new function of the view.

## How it is enforced

`tests/test_view.py` (part of `python3 tests/run_all.py`):

- the decision modules (`soccer/ai/`: `agent.py`, `kit.py`, `nets.py`, `obs.py`, `skill.py`, `view.py` and every archetype in
  `players/`) import nothing from the engine but its public constants, and never name the engine's or another agent's inside;
- after mixed matches, nothing an agent holds leads to the match, a real player, a card, a view, or any other agent, teammates
  included (a deliberate leak to a teammate or a view is caught);
- teammates hear each other's calls, never the opponents';
- a team's view of the opponents is anonymous, and nobody carries a real skill but the player's own agent.

## Removed: Opus

Opus 5.5 High ([docs/opus_5_5_high.md](opus_5_5_high.md)) planned by cloning the whole match and playing it forward: a copy of
the engine with hidden state (held buttons, the other agents' memory and random numbers). That is not allowed by this rule, so
it was removed (its code is in git history). A planner may come back if it starts from the public view (a simulation built from
the bodies and the ball, with the opponents played by a generic model).
