"""The options of rl/selfplay.py, without torch: lab/tracker.py checks experiment specs against them (an `args` key of a spec must
be one of these)."""
import argparse
import os

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out_5v5")   # = rl/agent.py OUT

OBS_DIMS = {"legacy": 54, "team": 46, "rank": 56, "slots": 76}   # observation layouts (soccer/ai/obs.py): ego with player slot / role-free team / every size with calls
OBS_DESC = {                       # what each layout holds (soccer/ai/obs.py features_*); the Lab's Setup tab shows it
    "team": "Me (position, speed), my 4 teammates nearest first, the 5 opponents nearest first (position and speed each), the ball "
            "(position, speed), kickoff on, goal celebration on. No player ID: sorting by distance keeps a player from knowing a role. 5v5 only.",
    "rank": "The team layout plus, for me and my 4 teammates, the rank in our team by distance to the ball and by depth (no fixed role: "
            "ranks change with the situation). 5v5 only.",
    "slots": "Me; 4 teammate slots nearest first (position, speed, on the pitch, and the teammate's call: none / ball / open / run / cover); "
             "5 opponent slots nearest first (position, speed, on the pitch); the ball; kickoff on, our kickoff, goal celebration. "
             "An empty slot is zeros, so one net plays every size from 1v0 to 5v5.",
    "legacy": "Me, the ball, the 4 teammates and 5 opponents in slot order, the ball and the opponent goal relative to me, and a one-hot "
              "of my slot (the first RL teams). 5v5 only.",
}
# the blocks of each layout, in order (soccer/ai/nets.py features_*; tests/test_lab.py checks them against the real features):
# (block, count, numbers each, contents). "pos, speed" = 4 numbers: x, y, vx, vy
OBS_LAYOUT = {
    "slots": [("me", 1, 4, "position, speed"),
              ("teammates", 4, 10, "nearest first: position, speed, on the pitch (1), its call as 5 one-hot (none / ball / open / run / cover)"),
              ("opponents", 5, 5, "nearest first: position, speed, on the pitch (1)"),
              ("ball", 1, 4, "position, speed"),
              ("flags", 1, 3, "kickoff on, our kickoff, goal celebration (0 / 1 each)")],
    "team": [("me", 1, 4, "position, speed"),
             ("teammates", 4, 4, "nearest first: position, speed"),
             ("opponents", 5, 4, "nearest first: position, speed"),
             ("ball", 1, 4, "position, speed"),
             ("flags", 1, 2, "kickoff on, goal celebration (0 / 1 each)")],
    "rank": [("me", 1, 4, "position, speed"),
             ("teammates", 4, 4, "nearest first: position, speed"),
             ("opponents", 5, 4, "nearest first: position, speed"),
             ("ball", 1, 4, "position, speed"),
             ("flags", 1, 2, "kickoff on, goal celebration (0 / 1 each)"),
             ("ranks", 5, 2, "me, then the teammates nearest first: rank in our team by distance to the ball and by depth (÷ size − 1)")],
    "legacy": [("me", 1, 4, "position, speed"),
               ("ball", 1, 4, "position, speed"),
               ("teammates", 4, 4, "in slot order: position, speed"),
               ("opponents", 5, 4, "in slot order: position, speed"),
               ("ball from me", 1, 3, "dx, dy, distance (÷ 40, clipped at ±6: the kick range is learnable)"),
               ("goal from me", 1, 2, "dx, dy to the opponent goal (÷ 400)"),
               ("my slot", 1, 5, "one-hot of the player's slot 1–5")],
}
OBS_SCALE = "Mirrored so the team always attacks to the right (+x); positions ÷ the pitch half-size, speeds ÷ 5."


def parser():
    ap = argparse.ArgumentParser(description="Self-play PPO training of the net teams (rl/selfplay.py), at any team size.")
    ap.add_argument("--updates", type=int, default=1500, help="final update number (absolute: with --start_update 200 and --updates 3000 it trains updates 201..3000)")
    ap.add_argument("--obs", choices=list(OBS_DIMS), default="team", help="observation layout: team = 46 numbers, no player ID (default, 5v5); slots = 76 numbers, every size, with the teammates' calls (the net calls too); legacy = 54 numbers with the slot (the first RL teams)")
    ap.add_argument("--size", type=int, default=5, help="players per side (1..5; below 5 needs --obs slots)")
    ap.add_argument("--opp_mode", choices=["rules", "none"], default="rules", help="rules: matches against the rule teams + self-play; none: an empty pitch (first-goal episodes from random starts: the 1v0 stage)")
    ap.add_argument("--start_update", type=int, default=0, help="continue numbering from a restart: the checkpoint --start was saved at this update")
    ap.add_argument("--workers_rule", type=int, default=8, help="worker processes playing against the rule teams")
    ap.add_argument("--workers_self", type=int, default=8, help="worker processes playing self-play (snapshots of itself and --opp_models)")
    ap.add_argument("--envs_per_worker", type=int, default=10, help="matches each worker plays at once")
    ap.add_argument("--rollout", type=int, default=128, help="decisions collected per match before each update (batch = matches x rollout x players)")
    ap.add_argument("--epochs", type=int, default=4, help="passes of PPO over each batch")
    ap.add_argument("--minibatch", type=int, default=8192, help="samples per gradient step")
    ap.add_argument("--lr", type=float, default=1e-4, help="learning rate of Adam (after a short warm-up)")
    ap.add_argument("--gamma", type=float, default=0.997, help="discount per decision (0.997: a reward 10 s ahead still counts about 40%%)")
    ap.add_argument("--lam", type=float, default=0.95, help="GAE lambda: bias / variance trade-off of the advantages")
    ap.add_argument("--ent", type=float, default=0.003, help="entropy bonus: keeps the moves random enough to explore")
    ap.add_argument("--seed", type=int, default=7, help="random seed of the training (matches, sampling, net init)")
    ap.add_argument("--start", default=os.path.join(OUT, "rl_agent_after_s9_all.pt"), help="checkpoint (.pt) to continue from; \"scratch\" = a fresh net")
    ap.add_argument("--baseline", default="", help="frozen benchmark opponent (.pt); default = --start")
    ap.add_argument("--w_pass_prog", type=float, default=0.3, help="reward per progressive pass (a completed pass that gains at least a fifth of the half-length towards the opponent goal)")
    ap.add_argument("--w_pass_ok", type=float, default=0.05, help="reward per completed pass that is not progressive (cooperation: capped by --coop_cap)")
    ap.add_argument("--w_pass_fail", type=float, default=0.08, help="penalty per failed pass")
    ap.add_argument("--pass_individual", type=int, default=0, help="1: pass rewards go to the passer / receiver, not the whole team")
    ap.add_argument("--w_recv", type=float, default=0.0, help="reward for receiving a pass (cooperation: capped by --coop_cap)")
    ap.add_argument("--w_open", type=float, default=0.0, help="reward per decision for a teammate of the ball carrier who is open for a pass (120-450 px away, no opponent in the lane)")
    ap.add_argument("--w_key_pass", type=float, default=0.0, help="reward per key pass: a pass the receiver shoots from (cooperation: capped by --coop_cap)")
    ap.add_argument("--w_xa", type=float, default=0.0, help="reward per expected assist: the xG of the shot a pass led to (cooperation: capped by --coop_cap)")
    ap.add_argument("--w_space", type=float, default=0.006, help="penalty per decision for crowding a teammate (closer than --space_radius px) while our team has the ball")
    ap.add_argument("--space_radius", type=float, default=140.0)
    ap.add_argument("--w_kick", type=float, default=0.01, help="penalty per decision for pressing kick out of reach of the ball (kick discipline)")
    ap.add_argument("--random_start", type=float, default=0.0, help="fraction of episodes that start from a fully random layout instead of a kickoff")
    ap.add_argument("--coop_cap", type=float, default=0.0, help="max cooperation reward per episode (anti reward-farming)")
    ap.add_argument("--w_jitter", type=float, default=0.0, help="penalty per sharp change of direction (twitching)")
    ap.add_argument("--w_keeper", type=float, default=0.0, help="penalty for the keeper-line player when further than --keeper_free px from its own goal")
    ap.add_argument("--shaping", type=float, default=1.0, help="weight of the ball shaping (ball towards the goal, teammate towards the ball); 0 = off")
    ap.add_argument("--w_corner", type=float, default=0.0, help="penalty per decision while our team put the ball in a corner (last touch ours)")
    ap.add_argument("--w_wall", type=float, default=0.0, help="penalty per decision for a player pressed against the outer wall for 2+ decisions in a row")
    ap.add_argument("--w_far", type=float, default=0.0, help="penalty for an outfield player further than --far_radius px from the ball (the arena is 1280 x 600; full penalty at twice the radius)")
    ap.add_argument("--far_radius", type=float, default=600.0)
    ap.add_argument("--w_xg", type=float, default=0.0, help="reward per expected goal (xG) of the player's own shots (shot quality), at most --xg_cap per match")
    ap.add_argument("--xg_cap", type=float, default=6.0)
    ap.add_argument("--w_xga", type=float, default=0.0, help="team penalty per xG of the opponent's shots")
    ap.add_argument("--w_win", type=float, default=0.0, help="team bonus at the end of a won match")
    ap.add_argument("--w_draw", type=float, default=0.0, help="team bonus at the end of a drawn match")
    ap.add_argument("--w_tackle", type=float, default=0.0, help="reward per tackle or interception, at most --def_cap per match")
    ap.add_argument("--def_cap", type=float, default=2.0)
    ap.add_argument("--w_goalside", type=float, default=0.0, help="per decision: outfield player between the ball and its own goal while the opponent has the ball")
    ap.add_argument("--goalside_lane", type=float, default=120.0)
    ap.add_argument("--w_opp_half", type=float, default=0.0, help="team penalty per decision while the opponent has the ball in our half")
    ap.add_argument("--w_compact", type=float, default=0.0, help="team penalty per decision when the outfield players are stretched beyond --compact_len / --compact_wid px")
    ap.add_argument("--compact_len", type=float, default=700.0)
    ap.add_argument("--compact_wid", type=float, default=450.0)
    ap.add_argument("--keeper_free", type=float, default=350.0)
    ap.add_argument("--snapshot_every", type=int, default=40, help="a snapshot of the learner joins the self-play opponent pool every N updates")
    ap.add_argument("--resample_every", type=int, default=20, help="the self-play opponents are drawn again every N updates")
    ap.add_argument("--ckpt_every", type=int, default=100, help="a checkpoint is saved every N updates")
    ap.add_argument("--eval_every", type=int, default=100, help="complete evaluation of the checkpoint every N updates (multiple of --ckpt_every; 0 = never); training is paused meanwhile")
    ap.add_argument("--fast_every", type=int, default=0, help="FAST check (16 short matches + head to head vs --fast_ref) every N updates, training paused; 0 = never")
    ap.add_argument("--fast_rules", type=int, default=1, help="1: the FAST check also plays the fixed matches against the rule bots (logs/sp_eval/<tag>_fast.txt); 0: only the estimated Elo")
    ap.add_argument("--elo_pairs", type=int, default=0, help="with each FAST check: estimated Elo from this many pairs of ladder matches (lab/ladder.py estimate, 2 matches per pair, training paused); 0 = none")
    ap.add_argument("--fast_ref", default="", help="game-model JSON of the net the run started from (the fast check plays it head to head)")
    ap.add_argument("--learn_threads", type=int, default=2, help="torch threads of the learning step (more would fight the env workers for the CPU)")
    ap.add_argument("--trainer_fg", type=int, default=1, help="macOS, runner in background mode (TrainerQos): 1 = the trainer process leaves it (about 1.5x faster, about 0.7 W more), 0 = it stays (coolest). Env workers and evaluations always keep it. Speed only")
    ap.add_argument("--base_port", type=int, default=7100, help="first port of the rule-group workers (self-play group: +100)")
    ap.add_argument("--hidden", type=int, default=128, help="width of the two hidden layers (must match --start)")
    ap.add_argument("--teacher", default="", help="kickstarting: a checkpoint (.pt/.json, e.g. the 54-input jit8) whose moves the learner is pulled towards")
    ap.add_argument("--kl_coef", type=float, default=0.0, help="weight of KL(teacher || learner) in the loss at update 0, decaying linearly")
    ap.add_argument("--kl_decay", type=int, default=300, help="update at which the teacher term reaches 0")
    ap.add_argument("--opp_models", default="", help="comma-separated strong opponents for the self-play group (.pt or game-model .json, 46 or 54 inputs)")
    ap.add_argument("--pfsp", type=float, default=0.5, help="share of the self-play slots 1-3 given to --opp_models, each picked more often the more it wins (PFSP)")
    ap.add_argument("--eval_games", type=int, default=1, help="league games per team and side (1 = 32 matches)")
    ap.add_argument("--eval_duration", type=float, default=90.0, help="seconds per evaluation match")
    ap.add_argument("--eval_h2h_games", type=int, default=8, help="head-to-head games per side against each reference net")
    ap.add_argument("--log_every", type=int, default=5)
    ap.add_argument("--tag", default="sp")
    return ap
