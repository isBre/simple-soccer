# The public view: what a player may know

Every player of a match decides from the same information, whatever drives it: a rule-based bot, a neural net, or any agent
you write. This page is the specification; `soccer/ai/view.py` implements it and `tests/test_view.py` enforces it.

## The rule

A player may use **what a spectator in the stadium could know**, and **anything it computes from that**: inferring,
predicting, simulating forward, searching, remembering. It never sees the match engine or another agent's inside.

Players are **anonymous**: nobody knows who another player is, what kind of brain it has or how good it is. A player knows
its own skill and nothing else about anyone. No team, no tactic and no player can adapt to particular opponents or teammates.

## What is in the view

| Group | Field (`View`) | Meaning |
|---|---|---|
| Ball | `ball_pos`, `ball_vel`, `ball_r` | position (px, complex: x = `.real`, y = `.imag`), velocity (px per tick), radius |
| Players | `team_lists[team]`, `players`, `bodies[uid]` | every player as a `Body`: `uid`, `team`, `slot` (line-up order), `radius`, `pos`, `vel`, `spawn` (kickoff position), `home` and `line` (kickoff spot and its line: GK / DEF / MID / FWD, the same layout for every team) |
| History | `ball_at(delay)`, `pos_at(uid, delay)` | the ball and every player `delay` ticks ago, for the last `HIST` = 32 ticks |
| Clock | `tick`, `time_left`, `duration`, `overtime` | the match clock (60 ticks per second), seconds left, match length, golden-goal overtime on |
| Score | `scores` | `[team 0, team 1]` |
| State | `state`, `celebrating()` | playing, or a goal being celebrated (`soccer.match.PLAYING`, `GOAL`) |
| Kickoff | `kickoff_active`, `kickoff_team`, `kickoff_taker` | a kickoff is on, whose it is, which body takes it |
| Touches | `last_touch`, `last_touch_tick` | the body that touched the ball last, and when (it could be inferred from the history) |
| Pitch | `pitch` | its size, goals, walls and obstacles (`soccer.data.Pitch`) |
| Physics | `soccer.match`: `KICK_STRENGTH`, `KICK_RANGE`, `AI_PERIOD`, damping 0.99 (ball) / 0.96 (players) | the rules of motion are public: anyone may simulate the ball and the players forward from the view |
| Helpers | `attack_dir(team)`, `deepest(team)` | +1 / -1 (the direction a team attacks), the body nearest a team's own goal line (who seems to guard it) |

Direction: team 0 attacks towards +x, team 1 towards -x. Every Body is the same object for the whole match (updated in place
each tick), so an agent may remember bodies between ticks.

## What a team knows about itself

A team talks to itself. On its own bodies the view also sets:

- `brain`: the team brain that commands the player (the rule-based players of a team share one plan: who chases, who marks
  whom, who guards the goal);
- `is_human`: the player is controlled by a person (the bots leave the ball to the human, and do not run into them);
- `input_dir`, `input_kick`, `kick_intent`: the team's own buttons (what the player is doing now).

`View.controlled` is the human player when it is on your team, else `None`. `View.kickoff_go` (the tick your kickoff taker
kicks) is set only on the kicking team's view.

## What is never in the view

- **Who a player is**: name, kind (rule-based or net), style, skill. Every `Body` carries the generic assumption about an
  unknown player (`reaction_delay` = `GENERIC_DELAY`, `defend_q` = `GENERIC_Q`, the values of skill 70), teammates included.
  Your own skill is in your own bot (`soccer/ai/skill.py`: perception delay, aim errors, position noise, decision speed).
- **The match engine**: no agent holds the `Match`, its `Player` objects, the configuration or the line-up cards.
- **Another team's inside**: its brain and plan (who it chose as goal guard, its marks), its bots' memory, its random numbers,
  the buttons it is about to press, the moment its kickoff taker will kick. On the opponents' bodies `brain` is `None`, the
  buttons are empty and `is_human` is `False`.

## The agent interface

An agent controls one player. Every tick it is due (every `AI_PERIOD` = 2 ticks, alternating by slot), the match calls it
with its team's view and its own body:

```python
class MyBot:
    def decide(self, view, me):
        """Sets me.input_dir (complex, length <= 1, world frame), me.input_kick (bool) and me.kick_intent
        ("pass", "shoot", "clear", "long" or "": only labels the kick for the statistics)."""
        to_ball = view.ball_pos - me.pos
        me.input_dir = to_ball / max(abs(to_ball), 1.0)
        me.input_kick = abs(to_ball) < me.radius + view.ball_r + 4.0
        me.kick_intent = "shoot" if me.input_kick else ""
```

A team plan is optional: an object with `reset()` (after every kickoff) and `update(view)` (every `AI_PERIOD` ticks, before
the players decide), set as `p.brain` on the players it commands (`soccer/ai/lineup.py` builds them). The rule-based players
use `TeamBrain` (`soccer/ai/rules.py`), whose settings come from the players it commands (`Style.blend`): a team has no
tactic of its own.

Nets use the same interface through `NetBot` (`soccer/ai/nets.py`): an observation built from the view
(`features_group(view, bodies, n_in)`), one forward pass for all the net's players of the tick, then `act(view, me, outputs)`.
The observations are functions of the view:

| Observation | Inputs | Contents |
|---|---|---|
| `team` | 46 | me, my 4 teammates nearest first, the 5 opponents nearest first (position and velocity, mirrored so the team attacks +x), the ball, kickoff on, goal celebration |
| `rank` | 56 | `team` + for me and my teammates the rank by distance to the ball and by depth |
| `legacy` | 54 / 49 | the first RL nets: an ego view with the player's slot |

A new agent can use all of the view or any part of it; a new observation is a new function of the view.

## How it is enforced

`tests/test_view.py` (part of `python3 tests/run_all.py`):

- the decision modules (`soccer/ai/rules.py`, `nets.py`, `view.py`, `skill.py`) import nothing from the engine but its public
  constants, and never name the engine's or another agent's inside;
- after mixed matches, nothing a team's agents hold (its view, brains, bots) leads to the match, a real player, a card, or
  the other team's view, brain or bot (deliberate leaks of each kind are caught);
- a team's view of the opponents is anonymous and empty inside, and nobody carries a real skill but the player's own bot.

## Parked: Opus

Opus 5.5 High (`soccer/ai/opus.py`, [docs/opus_5_5_high.md](opus_5_5_high.md)) planned by cloning the whole match and playing
it forward: a copy of the engine with hidden state (held buttons, the other agents' memory and random numbers). That is not
allowed by this rule, so Opus is parked: its code is kept, but no player or team uses it. It comes back once its planner starts
from the public view (a simulation built from the bodies and the ball, with the opponents played by a generic model).
