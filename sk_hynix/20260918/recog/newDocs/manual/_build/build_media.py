#!/usr/bin/env python3
"""Build the delivery GIFs (full + light) and MP4s from the source recordings."""
import os, re, sys, subprocess
sys.path.insert(0, "/home/claude/manual/work")
os.chdir("/home/claude/manual")
from PIL import Image
from steps import ORDER
from frames_lib import processed

for d in ("gif", "gif-light", "mp4"):
    os.makedirs(d, exist_ok=True)

GIF_CROP = {"07_ai-template": (160, 0, 875, 522),
            "08_template-types": (330, 28, 875, 358)}
DURATION = {u: (100 if u.startswith(("06", "07", "08")) else 75) for u in ORDER}
DURATION["01b_create-folder-full"] = 75

UNITS = ORDER + ["01b_create-folder-full"]


def build(unit):
    frames = processed(unit)
    if unit in GIF_CROP:
        frames = [f.crop(GIF_CROP[unit]) for f in frames]
    dur = DURATION[unit]

    raw, out = f"work/_{unit}.gif", f"gif/{unit}.gif"
    frames[0].save(raw, save_all=True, append_images=frames[1:],
                   duration=dur, loop=0, optimize=True)
    subprocess.run(["gifsicle", "-O3", "--lossy=40", "--colors", "160", raw, "-o", out],
                   check=True, stderr=subprocess.DEVNULL)
    os.remove(raw)

    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", out,
                    "-movflags", "+faststart", "-pix_fmt", "yuv420p",
                    "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                    "-c:v", "libx264", "-crf", "20", f"mp4/{unit}.mp4"], check=True)

    # lightweight variant: 760px wide, every 3rd frame dropped, timing preserved
    info = subprocess.run(["gifsicle", "--info", out], capture_output=True, text=True).stdout
    nf = int(re.search(r"(\d+)\s+images", info).group(1))
    drop = [f"#{i}" for i in range(nf) if i % 3 == 2]
    subprocess.run(["gifsicle", "-O3", "--lossy=80", "--colors", "128",
                    "--resize-width", "760", "--delay", str(round(dur * 1.5 / 10)),
                    out, "--delete"] + drop + ["-o", f"gif-light/{unit}.gif"],
                   check=True, stderr=subprocess.DEVNULL)

    mb = lambda p: os.path.getsize(p) / 1e6
    print(f"{unit:24s} {frames[0].size[0]}x{frames[0].size[1]}  {len(frames):3d}f  "
          f"{len(frames)*dur/1000:5.1f}s   gif {mb(out):.2f}MB   "
          f"light {mb(f'gif-light/{unit}.gif'):.2f}MB   mp4 {mb(f'mp4/{unit}.mp4'):.2f}MB")


if __name__ == "__main__":
    for u in UNITS:
        build(u)
