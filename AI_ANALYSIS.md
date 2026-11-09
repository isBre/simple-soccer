# Bot AI analysis (Nov 2026)

Measured with `experiments/ai_diag.tscn` (12 matches, new diagnostic) and the existing `versus` / `teams` / `strength` results.
Baseline `versus` (96 matches, classic 3v3): new vs legacy W60 D24 L12, 2.12 pts/m.

## What the numbers say
1. **63% of shots are not on target, and skill is not the reason.** Attribute-driven aim error alone would give ~85-99% on target.
   Diagnostic breakdown of 429 "shoot" kicks:
   - perfect aim from the bot's own contact estimate: 74% on target
   - perfect aim from the TRUE ball position/velocity: 86% (the predicted contact point is ~22 px from the real ball at kick time, because it is built from the delayed ball perception)
   - skill error only: 69%
   - actual: 53%. Mean kick misalignment is 10-16 degrees: the kick fires as soon as dot(player->ball, wanted dir) > 0.95 (18 degrees), and only 14% of kicks are within 4 degrees (those are 84% on target).
2. **Keepers dominate accurate shots.** In the gated-kick experiment on-target shots went 43% -> 65-68% but the save rate went 55% -> 85%: accuracy alone does not create goals.
3. **xG is inflated** (3.3-3.9 per match vs 1.8-2.3 goals): it ignores the keeper, so bots over-shoot from spots that look fine but are saved.
4. **The tactical layer is net-negative.** `styles` round robin: long_ball 1.70 pts/m, total_football 0.85, wing_play 1.05, high_press 1.15. Fancy positional styles lose to direct play.
5. **Team rating barely decides matches until the gap is >= 30**: strength experiment, gap 10-20 -> stronger side wins ~45%, draws ~28%.
6. **A learned policy already beats the rules**: ES fine-tuned MLP 2.68 pts/m vs the teacher 1.50 (GF 3.75 / GA 1.00), but only trained for balanced / classic / 3v3 and the eval samples are tiny.

## Experiment that did NOT work (kept for reference)
`experiments/alignment_gate.patch`: use the real ball position/velocity at close range, and only kick shots/passes when the real kick normal is within a tolerance of the wanted direction (relaxed while waiting).
Result (`results_versus_alignment_gate.txt`, 192 matches): on target 37% -> 68%, but passes per match halved (20.9 -> 10.0), new-vs-legacy win rate 62% -> 38%, pts/m 2.12 -> 1.52. Waiting for alignment loses the ball; strict gating on passes is the main culprit. Reverted.

## Next steps (ordered)
- Re-try only the "true ball position/velocity at close range" part (no kick gating), measure with `versus` games >= 6.
- Gate only shots, with a generous tolerance; leave passes alone.
- Shot selection against the keeper: shoot when the keeper is out of position / moving, not on any open lane.
- Evaluate the learned policy on 5v5 / other pitches / held-out styles; train with self-play.
`StyleBot.DIAG` is off by default; `experiments/ai_diag.tscn` turns it on.
