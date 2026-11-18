"""Runs a Godot scene headless and returns the payload of its tagged output line (tests compare it with Python)."""
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GODOT = os.environ.get("SOCCER_GODOT") or ("/Applications/Godot.app/Contents/MacOS/Godot" if os.path.exists(
    "/Applications/Godot.app/Contents/MacOS/Godot") else os.path.expanduser("~/godot/Godot_v4.6-stable_linux.arm64"))


def run_scene(scene, tag, args=(), timeout=3600, project=None):
    """Runs `scene` (in `project`, default this checkout) and returns the text after `tag` on the first output line that
    starts with it."""
    import tempfile
    cmd = [GODOT, "--headless", "--path", project or ROOT, scene, "--"] + list(args)
    # output to a file, not a pipe: a server Godot starts inherits the pipe and would keep it open after Godot exits
    with tempfile.TemporaryFile("w+") as f:
        subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=timeout)
        f.seek(0)
        out = f.read()
    for line in out.splitlines():
        if line.startswith(tag):
            return line[len(tag):]
    raise RuntimeError("no %r line from %s:\n%s" % (tag, scene, out[-3000:]))


def install_reference(ref):
    """Copies the recorders (tests/reference/*.gd, *.tscn; they use the Godot match code, so they only run in a checkout of
    the Godot implementation) and the scenario lists into the reference checkout `ref`."""
    import shutil
    os.makedirs(os.path.join(ref, "tests", "godot"), exist_ok=True)
    for f in os.listdir(os.path.join(ROOT, "tests", "reference")):
        if f.endswith((".gd", ".tscn")):
            shutil.copy(os.path.join(ROOT, "tests", "reference", f), os.path.join(ref, "tests", "godot", f))
    for f in ("scenarios.json", "env_scenarios.json"):
        shutil.copy(os.path.join(ROOT, "tests", f), os.path.join(ref, "tests", f))
