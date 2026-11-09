#!/usr/bin/env bash
# Train the neural-net bot for 5v5 on the Arena pitch on a many-core Linux box (Ubuntu 24.04, x86_64).
# Run from the project root (inside tmux or screen):   bash tools/train_5v5.sh
# Stages: 1 imitation  ->  2 DAgger  ->  3 evolution strategies. Results end up in ./out_5v5/ .
# Re-running skips finished stages, so it can be resumed after an interruption.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
GODOT_ZIP="Godot_v4.6-stable_linux.x86_64.zip"
GODOT_URL="https://github.com/godotengine/godot/releases/download/4.6-stable/${GODOT_ZIP}"
GODOT="$HOME/godot/Godot_v4.6-stable_linux.x86_64"
mkdir -p out_5v5 logs "$HOME/godot"
log() { echo "[$(date +%H:%M:%S)] $*"; }

if [ ! -x "$GODOT" ]; then
  log "installing packages + Godot 4.6"
  apt-get update -qq
  apt-get install -y -qq unzip wget ca-certificates libfontconfig1 libgl1 libxcursor1 libxinerama1 libxi6 libxrandr2 libx11-6 || true
  (cd "$HOME/godot" && wget -q "$GODOT_URL" && unzip -o -q "$GODOT_ZIP")
  chmod +x "$GODOT"
fi
"$GODOT" --version

log "importing project (builds the script class cache)"
"$GODOT" --headless --path "$ROOT" --import > logs/import.log 2>&1 || true

echo "cores: $(nproc)"

run_stage() {  # name  scene  done-marker
  local name="$1" scene="$2" marker="$3"
  if [ -f "out_5v5/$marker" ]; then log "stage $name already done, skipping"; return; fi
  log "stage $name starting"
  "$GODOT" --headless --path "$ROOT" "$scene" 2>&1 | tee "logs/$name.log" | grep --line-buffered -E "^\[|^iter|^gen|==|error|ERROR" || true
  log "stage $name finished"
}

# ---- 1) imitation
cat > experiments/ml_config.json <<'JSON'
{"imitate": "balanced", "pitch": "arena", "size": 5, "duration": 180, "collect_games": 2, "games": 2, "samples": 80000, "epochs": 8, "kick_weight": 8, "hidden": 32, "eval_only": false, "temperature": 1.0, "lr": 0.003}
JSON
run_stage imitation res://experiments/ml_runner.tscn imitate_5v5_arena.json
if [ ! -f out_5v5/imitate_5v5_arena.json ]; then
  cp data/models/imitate_balanced.json out_5v5/imitate_5v5_arena.json
  cp experiments/results_ml.txt out_5v5/results_ml.txt
fi

# ---- 2) DAgger (own fresh net, teacher = balanced rule-based bot)
cat > experiments/dagger_config.json <<'JSON'
{"imitate": "balanced", "pitch": "arena", "size": 5, "duration": 180, "iters": 5, "collect_games": 2, "keep": 0.4, "train_cap": 100000, "hidden": 64, "first_epochs": 8, "epochs": 4, "lr": 0.002, "kick_weight": 8, "eval_games": 1, "final_games": 2, "betas": [1.0, 0.5, 0.25, 0.0, 0.0, 0.0]}
JSON
run_stage dagger res://experiments/dagger_runner.tscn dagger_5v5_arena_best.json
if [ ! -f out_5v5/dagger_5v5_arena_best.json ]; then
  cp data/models/dagger_balanced_best.json out_5v5/dagger_5v5_arena_best.json
  cp experiments/results_dagger.txt out_5v5/results_dagger.txt
fi

# ---- 3) evolution strategies, starting from the DAgger model
cat > experiments/es_config.json <<'JSON'
{"teacher": "balanced", "pitch": "arena", "size": 5, "gens": 30, "pairs": 6, "sigma": 0.02, "alpha": 0.005, "opps_per_gen": 4, "eval_every": 4, "gen_duration": 90, "duration": 180, "final_games": 2, "start": "res://data/models/dagger_balanced_best.json"}
JSON
run_stage es res://experiments/es_runner.tscn es_5v5_arena_best.json
if [ ! -f out_5v5/es_5v5_arena_best.json ]; then
  cp data/models/es_balanced_best.json out_5v5/es_5v5_arena_best.json
  cp data/models/es_balanced_last.json out_5v5/es_5v5_arena_last.json
  cp experiments/results_es.txt out_5v5/results_es.txt
fi
log "ALL DONE. Copy ./out_5v5 back to your Mac."
