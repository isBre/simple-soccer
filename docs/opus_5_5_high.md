# Opus 5.5 High: how the team was built, and where it stands

Opus 5.5 High is a team for the **Rule Based League**: no neural net, no training, a hand-written team brain
([`soccer/ai/opus.py`](../soccer/ai/opus.py)). The brief: the strongest bot possible under one rule, **it must look like real
football**. The players cooperate to win; they don't all run after the ball.

This document explains how it works (with the maths), how it was built change by change, what the numbers say, and where it falls
short.

| | |
|---|---|
| ![Quick match setup](opus/screen_quickmatch.jpg) | ![Lab ranking, rule teams](opus/screen_ranking.jpg) |
| *Quick Match: Opus 5.5 High has Silver Arrows' players (rating 89), so the difference comes from the AI.* | *The Lab ranking filtered to the Rule Based League: Opus is the top rule team.* |

## In one minute

- **Plays as a team.** At any moment exactly one outfield player plays the ball; the other three have jobs (rest defence,
  striker, support / cover, marking). It has 3+ outfield players around the ball **~6 % of the time** (Silver Arrows 5 %, RL Team 5
  28 %) and plays **~18 passes a match at 80 %** (Silver Arrows ~10 at 59 %).
- **Thinks with physics.** In build-up it simulates ~50 kicks per decision (three aim samples each) and every player's exact
  reach, and picks the kick by who gets to the ball first and what that is worth.
- **Tuned against the nets, twice.** Its numbers were tuned with CMA-ES against 10 trained nets. The second run (section 9)
  added a territory term and an outlet player after measuring that the nets pinned it in its own third; on fresh seeds it added
  **+0.44 points and +0.47 goal difference per match against the nets** (z = 4.5 and 4.9) over the first tuned version.
- **Strength:**
  - **Against the whole field** (every other ladder entry, both sides, same seeds): **1.79 points per match, +0.61 goal
    difference** (v4 1.69 and +0.47; first tuned version ~1.2 and −0.1). Against the 25 trained nets and RL teams alone:
    1.54 points, +0.33 goal difference.
  - **Lab ranking (v5, section 11):** **1679 Elo (95 % 1613–1745) after 164 games**, 18th of 42, the top rule team by ~400
    points (Silver Arrows 1283), ahead of 8 of the 25 trained nets and RL teams. v4 (the first-time hit, section 10) was 1623; v5
    stops wasting the ball in the opponents' third, counter-presses there and skips shots the defenders will reach.
  - **Trained nets:** still ~200 Elo behind the best ones (jit8 ~1884, RL Team 5 ~1875).
  - **Against the rule teams:** 2.28 points per match in the ladder (42 won, 20 drawn, 2 lost), positive goal difference
    against every one of them.

![Live match: defending](opus/screen_defending.jpg)
*A live match in the browser, before tuning (Opus in orange defends the left goal). One player (#5) engages the man on the ball; the others hold
cover and marking positions and the keeper stays in goal: no swarm.*

---

## 1. The physics that decide everything

The match core is a deterministic Haxball-style simulation at 60 ticks per second (`soccer/match.py`). Three facts shape every
decision.

**The ball.** A kick adds exactly $K = 5$ px/tick to the ball's velocity along the line from the player's centre to the ball's
centre; the ball then loses 1 % of its speed per tick. After a kick with initial velocity $\mathbf v_0$ from $\mathbf b_0$:

$$\mathbf b(t) = \mathbf b_0 + \mathbf v_0\,\frac{1-0.99^{\,t}}{0.01},\qquad |\mathbf v(t)| = |\mathbf v_0|\,0.99^{\,t}$$

so a kick from rest travels at most 500 px, and a 200 px pass takes ~51 ticks. Side walls bounce it back at half speed.

**The players.** Each tick: $\mathbf v \leftarrow 0.96\,(\mathbf v + 0.1\,\mathbf u)$, $\mathbf x \leftarrow \mathbf x + \mathbf v$ with
$|\mathbf u| \le 1$. The system is linear, so a player's position is a *free* part (his current velocity carrying him on) plus a
*forced* part (what he can add by accelerating after his reaction delay $\tau$):

$$\mathbf x(t) = \mathbf x_0 + 25\,\mathbf v_0\,(1-0.96^{\,t}) + \mathbf u\,R(t-\tau),\qquad R(s) = 2.5\,s - 60\,(1-0.96^{\,s})$$

$R$ is how far a player starting from rest can get in $s$ ticks (top speed 2.5 px per tick of movement). The closed form matches
the integrator exactly:

![Ball and player distance over time](opus/physics.png)

The consequence: **a pass is only about twice as fast as a sprinting player**, so whether a pass arrives is a race that can be
computed.

**Kicking a moving ball.** The kick adds $K\mathbf n$ to the ball's current velocity $\mathbf v$. To send the ball along a
direction $\mathbf d$, solve $\mathbf v + K\mathbf n = s\,\mathbf d$ for the speed $s>0$:

$$s = (\mathbf v\cdot\mathbf d) + \sqrt{(\mathbf v\cdot\mathbf d)^2 - |\mathbf v|^2 + K^2},\qquad \mathbf n = \frac{s\,\mathbf d - \mathbf v}{K}$$

(`_compensated_dir`, shared with the handmade bots). A one-touch pass on a moving ball goes where it was meant to go.

---

## 2. The team brain: jobs, not a swarm

`OpusBrain.update` runs every 2 ticks and gives every player one job. Each bot then executes its job with its own senses and skill.
Perception delay, aim error, positioning noise and decision speed come from the player's attributes, exactly as for every other
team.

**Who plays the ball.** For each player the brain computes the earliest tick he can touch the ball on its predicted path
(`intercept`): $t_{us}$ for our best, $t_{them}$ for theirs. The phase:

$$\text{attack if } t_{us} + 4 + 21.8\,\delta < t_{them},\qquad \text{defend if } t_{them} + 4 < t_{us},\qquad \text{otherwise contest}$$

where $\delta \in [0,1]$ is how deep the ball is in our own half. Deep in our half the team only switches to attack when the
ball is clearly ours; a scramble near our goal keeps the defensive shape. Only the first player to the ball plays it (with a
small bonus for whoever already had the job, so it doesn't flicker).

| Job | When | What it does |
|---|---|---|
| **B** ball player | always one | attack: picks a kick or carries the ball (section 3); defend: presses from the goal side |
| **K** keeper | always | the nominal goalkeeper; shot-stopping from the handmade bots; plays the ball only in his own box when he is first |
| **R** rest defence | attack | the deepest free player stays ~370 px behind the ball against the counter |
| **X** striker | attack, beyond halfway | goes to the goal, ~60 px in front of the goal line |
| **S** support | attack | best open spot on a 55 px grid (below) |
| **C** cover | defend, ball not deep in their half | goal-side behind the presser, 140 px towards our goal |
| **M** marker | defend | goal-side of the most dangerous receivers, 44 to 73 px off them |
| **G** guard | defend, scramble near our goal | the far half of the goal mouth instead of joining the pile |

The support spot for each free player maximises

$$S(\mathbf p) = 1.6\,\tfrac{V(\mathbf p)}{0.35} + 0.22\,\min\!\big(\tfrac{d_{opp}}{130},1\big) + 0.22\,\min\!\big(\tfrac{\ell}{70},1\big) - \text{(too close / too far from the ball)} - \text{(near team-mates)} - 0.0006\,|\mathbf p - \mathbf x|$$

with $V$ the position value (section 3), $d_{opp}$ the distance to the nearest opponent, $\ell$ the clearance of the pass lane from
the ball (spots between 84 and 307 px from the ball); team-mates already placed push each other apart within 184 px. The numbers
in this document are the tuned values (section 8 lists the hand-set ones they replaced).

![The shapes in real moments](opus/shapes.png)
*Real moments from a match against Silver Arrows (tuned version), drawn from the simulation. Dashed lines go to where the brain sends each player.*

| | |
|---|---|
| ![Build-up](opus/screen_buildup.jpg) | ![Attack](opus/screen_attack.jpg) |
| *Before tuning. Build-up on the touchline: #8 on the ball, #5 and #9 offer passes, #4 stays back.* | *Attacking the box: #8 and #5 inside, #9 at the edge, #4 at halfway marking the counter.* |

---

## 3. Choosing a kick by simulating it

In build-up and midfield the ball player scores every option instead of following fixed rules.

**Candidates.** 40 directions (every 9°), a direct pass at each team-mate and 9 points across the goal mouth: about 50 kicks.
Each is simulated three times, at $-\sigma, 0, +\sigma$ of the player's aim error ($\sigma$ from his passing or finishing), and the
values are averaged with weights $\tfrac14,\tfrac12,\tfrac14$.

**Who gets there first.** For every player $i$ and every sample time $t$ of a path, the *deficit* is how far he still is from
touching the ball when it gets there:

$$D_i(t) = \Big|\,\mathbf b(t) - \big(\mathbf x_i + 25\,\mathbf v_i\,(1-0.96^{\,t})\big)\Big| - r - R\big(t - \tau_i\big)$$

with contact radius $r$ (15 px for a receiver, 24 px for an opponent: any touch deflects it) and $\tau_i$ = his reaction delay
+ 2 ticks. The first sample where $D_i \le 0$ is his arrival $k_i$. Lining up a kick that needs the kicker to turn costs
$28\,(1-\cos\theta)$ ticks, which delays our receivers and gives the opponents time. All of this is one vectorised numpy
computation: (players × paths × samples), about 50 × 3 × 75 × 9 numbers per decision.

**What it is worth.** With $k_m$ our first arrival and $k_o$ theirs (in samples of 2 ticks):

$$P_{\text{keep}} = \sigma\!\left(\frac{2(k_o-k_m) - 6}{5}\right),\qquad \text{value} = P_{\text{keep}}\,V_{\text{recv}} - (1-P_{\text{keep}})\,V_{\text{them}}(\text{catch point})$$

$V$ is the **position value**, an estimate of how likely possession at a point ends in a goal:

$$V(\mathbf p) = 0.01 + 0.327\,\mathrm{xG}(\mathbf p) + 0.0425\,\pi^2,\qquad \mathrm{xG}(\mathbf p) = \mathrm{clip}\!\left(0.75\,(\theta/1.8)^{1.6},\,0.01,\,0.8\right)$$

where $\theta$ is the angle the goal mouth subtends from $\mathbf p$ (the game's own xG, `soccer/rating.py`) and $\pi \in [0,1]$ is
progress up the pitch. The weights were first calibrated by hand to what attacks really yield (a few % per final-third entry;
an early version valued them about 5× too high and never shot), then tuned. A free team-mate near goal is worth the shot he gets:
$V_{\text{recv}} = \max\big(V\cdot(0.55 + 0.45\,\sigma(\cdot)),\; 1.35\,\mathrm{xG}\cdot\sigma(\tfrac{\text{space}-25}{12})\big)$.

**Shots.** A path that crosses the goal line before any team-mate touches it is a shot. Its margin $m$ is the opponents' smallest
deficit before the line, plus 38.6 px because defenders need a moment to read a shot's direction:

$$P_{\text{clean}} = \sigma\!\left(\frac{m + 38.6 - 2}{7}\right),\qquad \text{value} = 0.97\,P_{\text{clean}} + (1-P_{\text{clean}})\cdot\big(0.04 + 0.05\,n_{\text{box}}\big)$$

The last term is the rebound, worth more with team-mates near goal. A path that runs over **our own** goal line is never an option.

**Carrying the ball** is compared against the best kick: 16 headings, the value 70 px on, times the chance we are still first to
the ball there, discounted by 0.265 (most dribbles end in a loss) and penalised into the touchline or a corner.

**Kicking what is really on.** The plan is refreshed every few ticks, but the kick itself is decided at contact: the direction the
contact would give *right now* (contact normal plus the ball's velocity) is evaluated fresh. It is taken when it beats keeping the
ball and is close to the plan (or ≥ 43 % of it, or straight away when an opponent is within 62 px). Without this the player
circled the ball while the defenders closed in.

![One decision](opus/decision.png)
*One real decision: the ball player (B) simulated 53 kicks. Grey = an opponent gets there first; blue = we do (brighter = worth
more). He picks the through ball into the space ahead of the right-side supporter.*

**Is the simulation right?** Every kick logs its predicted success; after the fixes in section 6, passes rated over 95 % safe are
kept 90 % of the time (261 passes):

![Pass calibration](opus/pass_calibration.png)

Shots, after adding the reading delay (24 px at the time): predicted 0.5 to 0.8 → 44 % scored (9 shots), predicted over 0.8 →
60 % (5 shots), predicted 0.2 to 0.5 → 8 % (13 shots).

---

## 4. Defending

- **Pressing from the goal side.** The presser runs round the ball to the side of our goal before engaging, so a touch or a kick
  sends the ball away from our goal. He only kicks when the evaluated kick is worth it; a blind poke is allowed only within 312 px of
  our goal. Before this rule the presser poked ~27 times a match and gave the ball back 89 % of the time.
- **Cover and markers.** The cover stands between ball and goal; markers take the most dangerous receivers by
  $V_{\text{them}}(\text{position}) + 0.15\,(\text{closeness to the ball})$ and stand goal-side, leaning towards the ball to cut
  the pass.
- **No pile-ups.** The trained nets score mostly from scrambles on the goal line with 3 to 4 players around the ball. When a
  marker's man is already in such a scramble near our goal, the marker guards the far half of the goal mouth instead (the keeper
  takes the near post). That one change cut the goals conceded to RL Team 4/5 from ~4.7 to ~3.4 per match.

## 5. Finishing

In the opponents' half the ball player switches to the handmade bots' direct finishing (`StyleBot._decide_action`: drive at goal,
shoot at the open part of the mouth, long shots when the lane is open), with the Opus shape around him: striker, support, rest
defence. (By hand this started at 35 % of the opponents' half; the tuning moved it to the halfway line.) The simulated choice was better at keeping the ball but worse at
scoring: before the switch Opus reached the final third more often than Silver Arrows (28.7 vs 23.4 times a match) but shot from
close range far less:

![Attack endings before the finishing change](opus/attack_endings.png)

---

## 6. How it was built: every change, measured

Each change was tested with `tools/team_bench.py` (5v5 arena, 3-minute matches, both sides, fixed seeds) and kept only when it
helped. Problems were found by rendering the seconds before goals and failed passes frame by frame, and by logging every decision.

![Progress](opus/progress.png)

| Change | What was wrong | Effect |
|---|---|---|
| Kick now + no dithering | 572 pass decisions in a match, 38 kicks: the player kept circling the ball | passes started to happen |
| Own-goal paths blocked | a back-pass rolled into our own net: only the *opponents'* goal line was checked | conceded 2.36 → 1.71 per match |
| Loose-ball fix | a slow ball out of everyone's 160-tick horizon had nobody assigned | — |
| Keeper receives only in his box | 600 px back-passes to a keeper who (correctly) stays in goal | — |
| Contact radius 19 → 24 px, receiver meets the ball | passes rated 95 % safe were kept 62 % | 81 % completion |
| Exact kick direction | the line-up tolerance sent kicks up to 18° off the plan | 0.56 → 0.68 |
| No blind pokes | 27 pokes a match, 11 % kept | — |
| Turn cost when carrying | a carrier facing the wrong way dragged the ball backwards | 0.68 → 0.88 |
| Attack only with clear possession | scrambles in our box flipped the team to "attack" | 0.88 → 1.01 |
| Goal-mouth guard | 10-player pile-ups in our corner | conceded to RL 4.7 → 3.4 |
| Value recalibrated (÷5) | it never shot: holding the ball looked better than any shot | 1.26 (new benchmark) |
| Shot reading delay | the keeper was modelled as perfect | 1.39 |
| Planned vs taken shots | 599 shot plans, 59 shots taken | 1.45 |
| Direct finishing + far-post striker + long shots 0.5 | 0.6 goals a match | 1.60 → 1.70 → **1.79** |

Tried and dropped (measured worse): a fully simulated dribble (1.26 → 0.50), counter-pressing with a second player (1.77 → 1.55 to
1.70), a runner next to the carrier (1.77 → 1.67), and direct finishing from the halfway line (better against rule teams, 2.07,
but 0.77 → 0.19 against nets).

---

## 7. Results

**Plays as a team.** Over the whole Rule Based League (216 matches per team):

![Team play](opus/teamplay.png)

**Against the rule teams** (`tools/team_bench.py opus_high --rl`, 3-minute matches): positive record against all 16, 1.94 points
per match on average (1.88 before tuning), 0.33 goals conceded per match. Silver Arrows, with the same players, averages a similar
number of points against the other teams but concedes almost twice as many (0.58); head to head the two are close (Opus 4-5-3 in 12).

**Against the trained nets.** The real test, because league points against rule bots saturate:

| Opponents | Opus 5.5 High | Silver Arrows |
|---|---|---|
| RL Team 4 / 5, 3-minute matches (pts per match, conceded) | 0.17, 3.1 (before tuning 0.17, 3.4) | 0.13, 5.8 |
| t48_u100, kickstart, persist_lr, wide_persist, jit8, RL Team 5 (before tuning) | 0.77 pts, 2.4 conceded | 0.08 pts, 4.6 conceded |
| 10 nets of the tuning, 90 s matches, fresh seeds (360 matches) | 0.97 pts, −0.41 goal difference (defaults: 0.71, −0.87) | |

**The Lab ranking** (`lab/ladder.py`: everyone against everyone, 90-second matches, Bradley–Terry on the Elo scale with 95 %
intervals):

![Ladder](opus/ladder.png)

After the first tuning, Opus (v2) was **17th of 42 at 1664 ± 154** after 60 games (the team file got a new version, so the ranking re-rated it
from scratch; before tuning it was 22nd at 1471 ± 171). That is ~380 points above every handmade team, above RL Team 2 and RL Team 3
and six of the trained nets, level with the team46 nets, and still ~230 below the top (RL Team 5 1897, jit8 1879). Its record:
21 wins, 19 draws, 20 defeats, 35–34 in goals; 1-1-0 against RL Team 5, 0-1-1 against jit8, 2-0-0 against x_anchor_ctrl and
x_kickstart, 2-1-1 against RL Team 3, 0-0-2 against RL Team 4 and x_anchor_wall_strong. The one-off full round robin made before
tuning ([docs/elo_ranking.md](elo_ranking.md), 3-minute matches) put the old version at the same place as the ladder did then.

**It isn't the players.** Before tuning, giving Opus perfect attributes (99: no reaction delay, almost no aim error) only moved it
from 0.65 to 0.81 points per match against six nets (90-second matches). The gap to the nets is in the decisions, not in the
senses, which is why tuning the decisions paid off more than better players would.

---

## 8. Auto-tuning against the nets

The hand-built version plateaued at 1471 on the ladder, so the numbers were handed to an optimiser
([`tools/tune_opus.py`](../tools/tune_opus.py)). The structure stays fixed (jobs, one player on the ball, no swarm); 27 numbers are
tuned: the value weights, shot reading, the kick-now thresholds, where the finishing and the striker job start, the rest-defence,
cover, marking and guard distances, the support spacing, and four style values of the finisher (long shots, pass bias, risk, keeper
sweeping).

**Objective.** A parameter vector $\theta$ (scaled to $[0,1]^{27}$) is played against 10 nets around and above Opus (RL Team
2/4/5, jit8, the best `x_*` runs, t48_best, team46_w256), both sides, 90-second matches:

$$f(\theta) = \overline{\text{points}} + 0.5\,\overline{\text{goal difference}}$$

All candidates of a generation play the same seeds, so their differences are paired. The seeds change every generation so nothing
overfits them.

**CMA-ES.** Each generation samples $\lambda = 4 + \lfloor 3\ln 27\rfloor = 13$ candidates
$\theta_k = \mathbf m + \sigma\,\mathbf B\mathbf D\,\mathbf z_k$, $\mathbf z_k \sim \mathcal N(0, I)$, and moves the mean to the
weighted average of the best $\mu = 6$:

$$\mathbf m \leftarrow \sum_{i=1}^{\mu} w_i\,\theta_{i:\lambda},\qquad w_i \propto \ln(\mu + \tfrac12) - \ln i$$

The covariance $\mathbf C = \mathbf B\mathbf D^2\mathbf B^\top$ learns which parameters move together (rank-one update from the
evolution path, rank-$\mu$ update from the selected steps), and the step size $\sigma$ grows or shrinks with the length of its own
evolution path. Every 4 generations the mean is played on fixed validation seeds (160 matches); the best validated mean is the
result.

**The run.** 24 generations, 13 × 40 matches each, about 2.8 hours on 3 low-priority cores of a fanless laptop (~13,000 matches).
Every validated mean beat the defaults (0.18); the best, at generation 16, scored 0.69 (0.94 points, −0.50 goal difference):

![Tuning](opus/tuning.png)

**Checked on fresh seeds.** The best of six validations is optimistic by construction, so tuned and hand-set versions then played the
same new seeds (paired: same opponent, side and seed):

| Fresh seeds | Matches | Points per match (hand-set → tuned) | Goal difference per match | z (points / goal difference) |
|---|---|---|---|---|
| 10 nets, block 1 | 120 | 0.76 → 0.88 | −0.81 → −0.53 | 0.8 / 1.7 |
| 10 nets, block 2 | 240 | 0.69 → 1.02 | −0.90 → −0.35 | **3.2 / 4.9** |
| 6 rule teams | 48 | 1.63 → 1.77 | +0.27 → +0.56 | 0.7 / 1.6 |

Better in every block, clearly so on the larger one. On the Lab ladder the tuned version went from 1471 to 1664.

**What changed** (the largest moves):

| Parameter | Hand-set | Tuned | Reading |
|---|---|---|---|
| where direct finishing starts | 35 % into their half | the halfway line | attack the goal directly as soon as the ball crosses halfway |
| striker position | far post, 45 px off centre | centre, 61 px from the line | stand in front of goal for rebounds and cut-backs |
| shot reading delay | 24 px | 38.6 px | shoot more: defenders react later than the model assumed |
| long shots (style) | 0.5 | 0.71 | shoot from further out |
| carry discount | 0.5 | 0.265 | keep the ball less, pass or shoot sooner |
| receiver's shot value | 0.9 | 1.35 | value passes to a free man near goal more |
| head start needed to attack in our half | 12 ticks | 21.8 ticks | stay compact longer after winning the ball deep |
| cover depth / marking gap | 115 / 28–55 px | 140 / 44–73 px | defend a little deeper and looser, protect the space behind |
| rest defence | 330 px behind the ball | 373 px | keep the last man deeper |
| keeper sweeping (style) | 0.3 | 0.12 | the keeper stays on his line |

The direction is consistent: **more direct and more willing to shoot in attack, deeper and more patient in defence**. The team
play is intact: 3+ players around the ball 4.1 % of the time (3.2 % before, Silver Arrows 5.4 %), the same spacing, fewer passes
(23 instead of 33 a match) because the finishing now starts at halfway.

## 9. Second round: getting out of our own third

After the first tuning the nets still won most games, so before changing anything the losses were measured: 40 matches (90 s)
against the five strongest nets (jit8, x_anchor_wall_strong, RL Team 4, RL Team 5, x_persist_lr), with the ball's position
sampled every 10 ticks and every change of possession logged.

**Diagnosis.** The nets pinned Opus back. The ball was in Opus's own third **63 %** of the time and possession changed hands
**~57 times a match inside our own third**, each way: Opus won the ball and lost it straight back (53 % of those losses came
within 10 ticks of winning it, 86 % by the ball player). The goals against came out of these scrambles, from 80–200 px in front of
goal with 3–4 net players around the ball. The cause sat in the kick evaluation: a kick that the opponent wins was valued by what
the opponent can do *from the point where he gets it*, and losing it 400 px upfield scored almost the same as losing it at the
edge of our own box.

**Two additions** (both in [`soccer/ai/opus.py`](../soccer/ai/opus.py)):

- **Territory.** Every kick except shots gets a bonus for the ground it gains before anyone reaches it, weighted by how deep in our
  half the ball is. With the ball at $x_b$ (along our attacking direction), the first touch by anyone at $x_e$, and $h$ the half
  length:

  $$\text{depth} = \mathrm{clamp}\!\left(\tfrac12 - \tfrac{x_b}{h},\,0,\,1\right),\qquad
  \text{gain} = \mathrm{clamp}\!\left(\tfrac{x_e - x_b}{h},\,-1,\,1\right),\qquad
  V \leftarrow V + w_{\text{terr}}\cdot \text{depth}\cdot\text{gain}$$

  The term is zero from a quarter of the way into their half, and largest at our own goal line, where a clearance that loses the
  ball 300 px upfield is now clearly better than a short pass into a crowd.
- **Outlet.** When the ball is deep in our half and at least three outfield players are free of other jobs, the most advanced one
  stays up near halfway on the far side, so a clearance finds a team-mate and the next attack doesn't start from zero. The cover
  player also gets its own distance for balls in our own third.

A hand test showed the territory term cut goals against from 1.10 to 0.85 and own-third time from 63 % to 54 %, while the cover
and outlet variants were inside the noise. So rather than choose by hand, the four new numbers (territory weight, cover distance in
our own third, where the outlet starts and where it waits) joined the other 27 in a **second CMA-ES run**: 31 parameters,
$\lambda = 4 + \lfloor 3\ln 31\rfloor = 14$, 30 generations, started from the first run's result, $\sigma_0 = 0.12$, about 4.5 hours on
3 low-priority cores.

![Second tuning run](opus/tuning2.png)

**Checked on fresh seeds** against the version that was on `main` (paired: same opponent, side and seed; seeds no search ever
played):

| Fresh seeds | Matches | Points per match (v2 → v3) | Goal difference per match | z (points / goal difference) |
|---|---|---|---|---|
| 10 nets | 240 | 0.71 → **1.15** | −0.63 → **−0.16** | **4.5 / 4.9** |
| 6 rule teams | 48 | 1.71 → **2.15** | +0.48 → +0.73 | 2.0 / 1.5 |

**Against the five strongest nets** (the diagnosis matches, same seeds as before):

| | v2 | v3 |
|---|---|---|
| ball in our own third | 63 % | 58 % |
| possession lost in our own third (per match) | 57 | 47 |
| goals against per match | 1.10 | 0.90 |

**Still a team.** `team_bench --rl` (every rule team and RL Team 4/5, both sides, 3-minute matches), same seeds:

| | v2 | v3 |
|---|---|---|
| points per match | 1.78 | **2.10** |
| goals for / against | 1.06 / 0.69 | 1.36 / 0.47 |
| outfield players within 120 px of the ball | 1.20 | 1.21 (opponents 1.51) |
| 3+ outfield players around the ball | 4.1 % | 5.6 % (Silver Arrows 5.4 %) |
| mean spacing between outfield players | 282 px | 278 px |
| passes per match (completed) | 22.4 (80 %) | 18.5 (80 %) |
| goals with an assist | 17 % | 26 % |

**What moved** (the largest changes):

| Parameter | v2 | v3 | Reading |
|---|---|---|---|
| territory weight | (none) | 0.135 | clear the ball upfield when deep, don't play into the press |
| outlet | (none) | ball below −64 % of our half; waits at −14 % | one man stays up to receive the clearance |
| cover | ball below 75 % of their half; 140 px | always; 126 px (166 px in our third) | a cover man is always goal-side |
| poke radius | 312 px | 500 px | poke the ball away under pressure in most of our half |
| goal-mouth guard trigger | 103 px | 141 px | a marker guards the goal mouth earlier |
| support spacing | 184 px | 118 px | supporters stand a bit closer, more short options |
| where direct finishing starts | halfway | 15 % into their half | build a little longer before driving at goal |
| shot value weight | 0.327 | 0.405 | value chances more |
| keeper sweeping (style) | 0.12 | 0.44 | the keeper comes out for balls behind the defence |

The picture is a team that **gets the ball out of danger first and builds from there**, with a man always goal-side and one always
up.

**Against the whole field.** Because the second run only played the 10 strongest nets, v2 and v3 then played every other ladder
entry (41 teams and nets, both sides, 2 seeds, same seeds for both):

| Opponents | Matches | Points per match (v2 → v3) | Goal difference per match | z (points / goal difference) |
|---|---|---|---|---|
| all 41 | 164 | 1.18 → **1.53** | −0.12 → **+0.34** | **2.8 / 3.6** |
| 25 trained nets and RL teams | 100 | 0.87 → **1.33** | −0.41 → **+0.19** | **2.8 / 3.4** |
| 16 rule teams | 64 | 1.66 → 1.84 | +0.34 → +0.56 | 0.9 / 1.4 |

It lost a little against a few rule teams (Bulls, Arrows) and gained most against the mid-table nets (t48, team46, the `x_anchor`
and `x_wide` runs), which it now beats more often than not. On the Lab ladder the new file started from zero and stands at
**1613 ± 134 after 180 games**; the interval overlaps the first tuned version's 1664 ± 154, and the paired match-up above is the
sharper test of the two.

## 10. Third round: hitting the ball first time

**What the match logs showed.** After the second round Opus still lost the ball cheaply under the nets' press. The touch log
showed how: a player who reached a moving ball under pressure first stopped it with his body and then looked for the best kick.
The nets' runners were already on him in those few ticks. With a kick of +5 px/tick and KICK_RANGE 4 px, the ball that comes off a
body touch is slow and goes wherever the contact sends it. One that is kicked at once keeps its pace and goes where we choose.

**The change** (`OpusBot._first_time`). Every outfield player who is within kick range of the ball and not already kicking
checks one thing: where would the ball go if he kicked it now? With $\hat n$ the unit vector from the player to the ball and
$v_b$ the ball's velocity, the ball leaves along

$$\hat u = \frac{v_b + 5\,\hat n}{\lVert v_b + 5\,\hat n \rVert}.$$

If that direction goes forward, $\hat u_x \cdot a > \text{FIRST\_FWD}$ (with $a = \pm 1$ the attacking direction), he kicks.
The kick is labelled through the same `_evaluate` simulation as every other kick (pass to a team-mate, shot if the line reaches
the goal mouth, or a clearance), so passes and assists are still counted and the receiver still knows the ball is for him. The
keeper never does it, and `FIRST_UPTO` limits how far up the field it applies (1.0 = everywhere).

**Variants** (paired, the same fresh seeds; "base" = v3 without the hit):

| Variant | Opponents | Matches | Points | Goal difference | Δ points (z) |
|---|---|---|---|---|---|
| base (v3) | 10 tuning nets | 200 | 1.08 | −0.17 | |
| hit if forward > 0.2, whole field | 10 tuning nets | 200 | **1.59** | **+0.42** | **+0.51 (4.1)** |
| hit if forward > 0, whole field | 10 tuning nets | 200 | 1.55 | +0.26 | +0.47 (4.0) |
| hit if forward > 0, own third only | 10 tuning nets | 200 | 1.33 | +0.01 | +0.25 (2.2) |
| base (v3) | rule teams | 72 | 1.83 | +0.63 | |
| hit if forward > 0.2, whole field | rule teams | 72 | 1.99 | +0.74 | +0.15 (0.9) |

Against **every other ladder entry** (41 entries × 2 seeds × both sides = 164 matches): 1.48 → **1.73 points** per match (z 2.0),
goal difference +0.20 → **+0.49** (z 2.4). Against the 25 trained nets and RL teams: 1.26 → 1.68 points (z 2.4); against the rule
teams nothing changed (1.83 / 1.81). The style stays a team style: ~16 passes a match at 83 %, 3+ outfield players around the ball
~5 % of the time.

**Third tuning run.** CMA-ES started from these values (33 numbers now, with `FIRST_FWD` and `FIRST_UPTO`), 20 generations,
~3 h on 3 workers. Its best candidate tied the starting point on the validation matches (1.7625 vs 1.762), so the code keeps
the values above. The search is no longer finding gains of the size a full evaluation can see; the next gain has to come from a
new behaviour, as this one did, not from the numbers.

**team_bench** (16 rule teams + RL Team 4/5, both sides, 2 seeds): **2.26 points** per match (v3 2.10), 1.79 goals for, 0.39
against.

**Lab ranking.** v4 played every other ladder entry twice from each side (164 matches, 73 won, 55 drawn, 36 lost) and
is rated **1623 Elo (95 % 1558–1689)**, 20th of 42. That is the top rule team by ~340 (Silver Arrows 1284) and level with the
middle of the trained nets (RL Team 2 1613, team46_w256 1655). The best nets are still ~250 higher (jit8 1886, RL Team 5 1876).
The ladder on `main` gained thousands of matches since v3 was rated, so v3's 1613 is on a different scale; the paired whole-field
comparison above is the test of v4 against v3.

## 11. Fourth round: breaking down a deep defence (v5)

**Where the points went.** v4's ladder games split very unevenly: against the 25 nets and RL teams 1.35 points per match,
against the 16 handmade teams 2.17, but with **25 draws in 64 games** and under one goal per 90 s. jit8 wins 99 % of the same
games. Played against the 16 handmade teams (96 matches each, 90 s):

| Per 90 s | Opus v4 | jit8 |
|---|---|---|
| Win / draw | 53 % / 41 % | 99 % / 1 % |
| Goals | 0.96 | 3.26 |
| Ball time in their third | 48 s | 73 s |
| Shots from < 150 px / > 300 px | 2.7 / 3.9 | 9.8 / 0.0 |

The three tuning runs never saw this: their fitness used only the 10 nets. A fourth run with the handmade teams in the fitness
(weighted 16 / 41, as in the ladder field, 15 generations) also tied v4 (2.127 vs 2.110 on validation), so this was again a
missing behaviour, not missing numbers.

**How the attacks ended.** Tracing every Opus touch in the opponents' third and who touched the ball next (per 90 s): forward
first-time hits that nobody of ours reaches lost the ball 4.5 times (kept 1.4); dribbles lost it 4.7 times; shots were blocked
or saved 5.3 times for 0.2 goals. The first was v4's own change: built to get out of our third under the press, it also
knocked the ball into a packed defence up the pitch.

**Three changes, each confirmed on fresh seeds** (paired, every other ladder entry, both sides; points / goal difference per match):

| Change | What it does | Gain (z) |
|---|---|---|
| First-time hit up the pitch only as a pass or a shot (`FIRST_CLEAR_UPTO` 0.33) | from the start of their third a hit to nobody is not taken; the player plays the ball properly | +0.12 / +0.12 (2.3 / 2.4), 328 matches |
| Counter-press (`CP_FROM` 0, `CP_TICKS` 120) | ball lost in their half: for 2 s the nearest free player presses it too, the others keep their jobs | with the above, handmade teams +0.29 / +0.45 (3.5 / 4.8) |
| Shot veto (`SHOT_VETO` 0.35) | the finisher's shot from more than 150 px is simulated with Opus's kick model (`_evaluate`, defenders' reach after `SHOT_READ`); below a 35 % clean chance the carrier keeps the ball | +0.12 / +0.19 (2.0 / 3.1), nets +0.16 / +0.23 (2.1 / 3.1) |

The counter-press alone did nothing measurable (it only pays once the attack stops giving the ball straight back). Tried and
left out: a second runner at the far post, Opus's own kick choice in the final third instead of the finisher (−0.40 points,
z −4.2), no long shots, a shorter shooting range, more passing (all within noise). A pass of the finisher now also records its
kicker, so the receiver is told the ball is his (a bug; no measurable effect).

**v5 against v4** on new seeds (328 matches): all entries 1.69 → **1.79** points (z 1.5), goal difference +0.47 → **+0.61**
(z 2.1); handmade teams 1.93 → **2.18** (z 2.6), +0.70 → **+1.05** (z 3.5); nets unchanged (1.54 / +0.33).

**team_bench** (16 handmade teams + RL Team 4/5, 3 min, both sides, 2 seeds): **2.52 points** per match (v4 2.26), 2.48 goals
for, 0.35 against; 115 won, 18 drawn, 11 lost. Still a team: 3+ outfield players around the ball 6.4 % of the time, mean spacing
270 px, 17.9 passes per match at 80 %, 18 % of goals assisted.

**Lab ranking.** 164 games (83 won, 52 drawn, 29 lost; handmade teams 42-20-2, nets and RL teams 41-32-27): **1679 Elo (95 %
1613–1745)**, 18th of 42, +56 on v4 (1623) on the same ladder. The top handmade team by ~400, ahead of team46_w256 and the
kickstart run; the best nets are still ~200 higher (jit8 1884, RL Team 5 1875).

## 12. Fifth round: what did not work (no v6)

**Where the 200 Elo to jit8 is** (ladder games against the same opponents, per match):

| | Opus v5 | jit8 |
|---|---|---|
| Handmade teams: points / goals for / against | 2.28 / 1.36 / 0.09 | 2.98 / 2.91 / 0.05 |
| Nets and RL teams: points / goals for / against | 1.55 / 0.92 / 0.60 | 2.01 / 1.32 / 0.41 |

Most of the gap is goals against the handmade teams' deep defence. Defence is not the problem: Opus's opponent-adjusted goals
against (0.41) are close to jit8's (0.32).

**Diagnosis.** jit8 lives around the opponents' box. Against the handmade teams it gets the ball back in their third about 51
times per match, 69 % of them within half a second and 94 % before the ball leaves their third. Opus gets 21 such chances, wins
36 % back within half a second, and lets about a quarter escape their third. Against the nets both teams lose nearly every ball
they win in their own third within a moment. The difference is where the ball is won: Opus starts 59 possessions per match in
its own third and 15 in midfield; jit8 starts 28 and 40. Shot by shot against the handmade teams, Opus's first-time hits from
beyond 150 px are 8 of its 10.6 shots per match, score almost nothing and are mostly blocked.

**Tried, paired against every ladder entry (8–12 seeds, both sides), none kept** (points / goal difference per match against
v5, z values):

| Change | Result |
|---|---|
| First-time shot from beyond 150 px only with a simulated clean chance ≥ 0.2 / 0.35 / 0.5 | handmade teams −0.09 / −0.26 (z −1.2 / −2.6) and similar. Those hits keep the ball in their third even when blocked. |
| Markers of men near the ball stand in the passing lane, from a third up / from halfway | within noise (|z| ≤ 0.8) |
| Two counter-pressers instead of one; rest defender up to 25 % into their half | within noise; the direction flipped between seed sets |
| A supporter waits for the second ball at the edge of their box (210 px) | handmade teams +0.15 (z +2.2), nets −0.16 / −0.19 (z −2.6 / −3.1) on 12 fresh seeds |
| The same, only against a deep block (3+ outfield players behind the ball: 36 % of our attacks against the handmade teams, 11 % against the nets) | handmade teams +0.10 (z +1.5), nets ±0; all +0.04 (z +0.9): too small |
| The finisher's dribble or shot is replaced by a simulated pass worth more by a margin of 0.05 / 0.15 / 0.3 | −0.17 / −0.08 / −0.05 points, goal difference z −3.7 / −2.5 / −3.1. Worse against both groups. |

The last result confirms v5's own finding (Opus's kick choice in the final third, −0.40): the single-kick model rates a pass by
the spot where it arrives, but against a packed box the receiver loses the ball more often than the handmade finisher's
dribble or shot does. v5 stays the current version.

## 13. Limits and next steps

- **Scoring is still the weak point.** Before tuning: 1.07 goals per match in the full round robin against all 41 other teams; the
  tuning helped mostly by making it shoot earlier. The direct finishing borrowed from the handmade bots
  works. Replacing it with Opus's single-kick passes (cut-backs) was worse every time (section 12): a finishing model of its own
  has to value what the receiver can do next, not only the arrival spot.
- **The strongest nets are still ~250 Elo higher.** They win goal-line scrambles with numbers; Opus refuses to swarm by design.
  Closing the rest of the gap under the realism rule probably needs a planner that simulates whole sequences in the real match
  engine (a rollout of each candidate action for ~1 s with all ten players), not single kicks. A longer tuning run (more matches per
  candidate, more generations) is the cheaper next step.
- **Its interval on the ladder is still wide** (60 games); the runner narrows it once this branch is on `main` and the Pi plays more
  rounds.

## Reproduce

```bash
python3 tools/team_bench.py opus_high --rl                    # vs every rule team and RL Team 4/5
python3 tools/team_bench.py opus_high --vs net:models/jit8_best.json,net:data/models/rl_5v5_arena_v5.json
python3 lab/ladder.py round --pairs 10 --workers 4             # more ladder games (the Lab ranking)
python3 tools/tune_opus.py --gens 20 --seeds 2 --workers 3 --sigma 0.1 --out logs/tune3    # the third run (resumes); it starts
                                                               # from the values in the code, so a new run continues from v4
```

Watch it: `python3 web/app.py`, then Quick Match → Rule Based League → Opus 5.5 High, control "Watch".
