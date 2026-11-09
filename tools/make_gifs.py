"""Stitches docs/screenshots/clip*/f*.png (from capture_screenshots.gd) into goalN.gif, shrinks the PNGs, deletes the clip dirs."""
import glob, os, shutil
from PIL import Image
D = os.path.join(os.path.dirname(__file__), "..", "docs", "screenshots")
for f in glob.glob(D + "/*.png"):
    im = Image.open(f).convert("RGB")
    im.resize((1280, round(im.height * 1280 / im.width)), Image.LANCZOS).save(f, optimize=True)
for d in sorted(glob.glob(D + "/clip*")):
    fr = [Image.open(x).convert("RGB").resize((640, 402), Image.LANCZOS) for x in sorted(glob.glob(d + "/f*.png"))]
    q = [x.quantize(128, dither=Image.Dither.NONE) for x in fr]
    q[0].save(d.replace("clip", "goal") + ".gif", save_all=True, append_images=q[1:], duration=50, loop=0, optimize=True)
    shutil.rmtree(d)
