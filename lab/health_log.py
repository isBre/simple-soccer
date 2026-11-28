"""Health sampler of this machine (macOS).

Appends one line every 10 s to logs/health.log (key=value pairs), read by lab/lab.py health() and the dashboard. The web app
(web/app.py) runs sample(only_if_quiet=True): it writes only while no other sampler does (lab/run.sh starts this script).
The fixed keys describe the machine (name, chip, cores, total memory, boot id); each sample has the readings macOS gives without
admin rights: load, free memory, battery temperature (the only temperature sensor readable without sudo; on a fanless MacBook it follows the chassis),
thermal pressure (0 nominal, 1 moderate, 2 heavy, 3 trapping, 4 sleeping: macOS slows the CPU from 1 up), power source and charge.

  nohup nice -n 10 python3 lab/health_log.py > /dev/null 2>&1 &
"""
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sh(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def machine_mac():
    hw = sh("system_profiler", "SPHardwareDataType")
    get = lambda k: (re.search(k + r":\s*(.+)", hw) or [None, ""])[1].strip()
    boot = re.search(r"sec = (\d+)", sh("sysctl", "-n", "kern.boottime"))
    return {"machine": get("Model Name") or "This machine", "chip": get("Chip"), "cores": os.cpu_count(),
            "memtotal": "%dMB" % (int(sh("sysctl", "-n", "hw.memsize") or 0) // 2 ** 20), "boot": "%08x" % (int(boot[1]) & 0xffffffff) if boot else "-"}


def sample_mac():
    bat = sh("ioreg", "-rn", "AppleSmartBattery")
    val = lambda k: (re.search(r'"%s" = (\w+)' % k, bat) or [None, None])[1]
    free = re.search(r"free percentage: (\d+)", sh("memory_pressure", "-Q"))
    total = int(sh("sysctl", "-n", "hw.memsize") or 0) // 2 ** 20
    tp = re.search(r"(\d+)\s*$", sh("notifyutil", "-g", "com.apple.system.thermalpressurelevel"))
    d = {"load": "%.2f" % os.getloadavg()[0], "memfree": "%dMB" % (total * int(free[1]) // 100) if free else "-",
         "thermal": tp[1] if tp else "-", "power": "AC" if val("ExternalConnected") == "Yes" else "battery"}
    if val("Temperature"):
        d["temp"] = "%.1f'C" % (int(val("Temperature")) / 100.0)
        d["temp_src"] = "battery"
    if val("CurrentCapacity"):
        d["battery"] = val("CurrentCapacity")
    return d


HEALTH_LOG = os.path.join(ROOT, "logs", "health.log")
EVERY = 10                     # seconds between samples
QUIET = 25                     # only_if_quiet: write when the log has not changed for this long (no other sampler is running)


def sample(out=HEALTH_LOG, only_if_quiet=False):
    """Appends one line every EVERY s, forever. only_if_quiet: skips while another sampler keeps the log fresh."""
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if sys.platform != "darwin":                                    # macOS only (ioreg, sysctl, memory_pressure)
        return
    info = machine_mac()
    fixed = " ".join("%s=%s" % (k, str(v).replace(" ", "_")) for k, v in info.items() if v not in (None, ""))
    mine = None                                                     # mtime of the log after our own last line
    while True:
        try:
            mt = os.path.getmtime(out)
            quiet = mt == mine or time.time() - mt > QUIET              # unchanged since our line, or nobody wrote for a while
        except OSError:
            quiet = True
        if quiet or not only_if_quiet:
            d = sample_mac()
            line = "%s %s %s" % (time.strftime("%Y-%m-%dT%H:%M:%S"), fixed, " ".join("%s=%s" % kv for kv in d.items()))
            with open(out, "a") as f:
                f.write(line + "\n")
            mine = os.path.getmtime(out)
        time.sleep(EVERY)


def main():
    sample(sys.argv[1] if len(sys.argv) > 1 else HEALTH_LOG)


if __name__ == "__main__":
    main()
