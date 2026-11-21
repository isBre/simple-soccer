#!/bin/bash
# Appends one line every 10 s: date and time (ISO), boot id (changes at every reboot), time, throttle flags (0x1 = undervoltage now, 0x10000 = undervoltage since boot), temperature,
# core voltage, CPU clock, load, free memory, swap, the live demo match (lab/live.py) and memory / disk pressure. After a crash the last lines show the state just before it. Synced to disk each time.
out=${1:-logs/health.log}
boot=$(cut -c1-8 /proc/sys/kernel/random/boot_id)
while true; do
  echo "$(date +%Y-%m-%dT%H:%M:%S) boot=$boot throttled=$(vcgencmd get_throttled | cut -d= -f2) temp=$(vcgencmd measure_temp | cut -d= -f2) volt=$(vcgencmd measure_volts core | cut -d= -f2) clock=$(( $(vcgencmd measure_clock arm | cut -d= -f2) / 1000000 ))MHz load=$(cut -d' ' -f1 /proc/loadavg) memfree=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)MB swapused=$(awk '/SwapTotal/ {t=$2} /SwapFree/ {f=$2} END {print int((t-f)/1024)}' /proc/meminfo)MB viewer=$(ps -o rss= -p "$(pgrep -f lab/live.py | head -1)" 2>/dev/null | tr -d ' ')KB mem_pressure=$(grep -o 'some avg10=[0-9.]*' /proc/pressure/memory 2>/dev/null | cut -d= -f2) io_pressure=$(grep -o 'some avg10=[0-9.]*' /proc/pressure/io 2>/dev/null | cut -d= -f2)" >> "$out"
  sync -f "$out"
  sleep 10
done
