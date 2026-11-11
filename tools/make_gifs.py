"""Stitches docs/screenshots/clip*/f*.png (from capture_screenshots.gd / capture_gifs.gd) into GIFs, shrinks the PNGs, deletes the clip dirs.
clip0 -> goal0.gif (legacy names), clip_<name> -> <name>.gif"""
import glob, os, shutil
from PIL import Image
D = os.path.join(os.path.dirname(__file__), "..", "docs", "screenshots")
for f in glob.glob(D + "/*.png"):
    im = Image.open(f).convert("RGB")
    im.resize((1280, round(im.height * 1280 / im.width)), Image.LANCZOS).save(f, optimize=True)
for d in sorted(glob.glob(D + "/clip*")):
    fr = [Image.open(x).convert("RGB") for x in sorted(glob.glob(d + "/f*.png"))]
    fr = [x.resize((640, round(x.height * 640 / x.width)), Image.LANCZOS) for x in fr]
    q = [x.quantize(128, dither=Image.Dither.NONE) for x in fr]
    base = os.path.basename(d)
    out = base.replace("clip_", "") if base.startswith("clip_") else base.replace("clip", "goal")
    q[0].save(os.path.join(D, out + ".gif"), save_all=True, append_images=q[1:], duration=50, loop=0, optimize=True)
    shutil.rmtree(d)
