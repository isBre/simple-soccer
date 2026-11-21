"""The Lab full screen on the Pi's touch screen (1024x600, layout ?kiosk=1): Chromium in kiosk mode on the dashboard's Live page.

Runs as its own service (lab/systemd/soccer-kiosk.service, Restart=always), independent of the runner: it stays open between
experiments, whether the Pi trains or only shows (soccer-exp or soccer-exp-viewer). If a kiosk window is already open (one
started by hand or by an older runner) it waits until that one is closed; then this process becomes Chromium itself, so systemd
sees it close and starts it again.

  python3 lab/kiosk.py"""
import os
import subprocess
import time

PROFILE = os.path.expanduser("~/.config/soccer-kiosk")          # own Chromium profile: no keyring prompt, no restore bubble
URL = "http://127.0.0.1:8080/?kiosk=1#/live"


def running():
    return subprocess.run(["pgrep", "-f", "user-data-dir=" + PROFILE], stdout=subprocess.DEVNULL).returncode == 0


def main():
    while running():
        time.sleep(30)
    # native Wayland (the Pi's desktop is labwc): under X11 compatibility the touch screen arrives as a mouse and a finger drag
    # selects instead of scrolling
    env = {**os.environ, "WAYLAND_DISPLAY": "wayland-0", "XDG_RUNTIME_DIR": "/run/user/%d" % os.getuid(), "DISPLAY": ":0",
           "XAUTHORITY": os.path.expanduser("~/.Xauthority")}
    env.pop("DBUS_SESSION_BUS_ADDRESS", None)
    args = ["chromium", "--ozone-platform=wayland", "--kiosk", "--app=" + URL, "--user-data-dir=" + PROFILE, "--password-store=basic",
            "--no-first-run", "--noerrdialogs", "--disable-infobars", "--disable-session-crashed-bubble", "--disable-translate",
            "--disable-features=Translate,TranslateUI", "--overscroll-history-navigation=0", "--disable-pinch", "--touch-events=enabled",
            "--check-for-update-interval=31536000"]
    os.execvpe(args[0], args, env)


if __name__ == "__main__":
    main()
