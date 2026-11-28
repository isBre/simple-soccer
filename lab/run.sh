#!/bin/bash
# Runs the experiment queue on this machine (a fanless MacBook Air) and keeps it cool:
#   - the health sampler (lab/health_log.py: battery temperature, thermal pressure, load) if it is not running yet,
#   - the runner on the efficiency cores (background QoS), nice 10, evaluations on 3 processes, no idle sleep while it runs,
#     no ladder loop afterwards (it exits when the queue is empty),
#   - the thermal guard (lab/thermal_guard.py): pauses everything above MAX °C, resumes at RESUME °C.
#
#   lab/run.sh [MAX] [RESUME]               defaults 33 32 (battery temperature, °C; the battery idles at about 30.6 on AC)
#
# Stop: pkill -f lab/exp_runner.py   (the guard resumes any paused process and exits on its own)
set -e
cd "$(dirname "$0")/.."
MAX=${1:-33}
RESUME=${2:-32}
mkdir -p logs
if pgrep -f lab/exp_runner.py >/dev/null; then echo "a runner is already running"; exit 1; fi
pgrep -f lab/health_log.py >/dev/null || nohup nice -n 10 python3 lab/health_log.py >/dev/null 2>&1 &
SOCCER_PROCS=3 nohup caffeinate -i taskpolicy -b nice -n 10 python3 lab/exp_runner.py --viewer >> logs/runner.out 2>&1 &
sleep 3
nohup nice -n 5 python3 lab/thermal_guard.py --max "$MAX" --resume "$RESUME" >> logs/thermal_guard.out 2>&1 &
echo "runner started (thermal guard: pause above $MAX °C, resume at $RESUME °C)"
