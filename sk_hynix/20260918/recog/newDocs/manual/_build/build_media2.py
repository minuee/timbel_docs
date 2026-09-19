#!/usr/bin/env python3
"""Second batch: copy the ready-made GIFs across, slice 16/17, make light variants."""
import os, re, sys, shutil, subprocess
sys.path.insert(0, "/home/claude/manual/work")
os.chdir("/home/claude/manual")
from frames_lib import processed
from steps import STEP_CROP

GIF_CROP = {"17b_dictionary-add": (130, 10, 980, 400)}

COPY  = ["09_home-left", "10_home-right", "11_search", "12_calendar",
         "13_inbox", "14_bookmark", "15_recycle"]
SLICE = {"16a_usage-period": 100, "16b_usage-metrics": 100,
         "17a_dictionary-open": 100, "17b_dictionary-add": 100}
SRCNAME = {"09_home-left": "09_home-left.gif", "10_home-right": "10_home-right.gif",
           "11_search": "11_search.gif", "12_calendar": "12_calendar.gif",
           "13_inbox": "13_inbox.gif", "14_bookmark": "14_bookmark.gif",
           "15_recycle": "15_recycle.gif"}


def light(unit, dur):
    src = f"gif/{unit}.gif"
    info = subprocess.run(["gifsicle", "--info", src], capture_output=True, text=True).stdout
    nf = int(re.search(r"(\d+)\s+images", info).group(1))
    drop = [f"#{i}" for i in range(nf) if i % 3 == 2]
    subprocess.run(["gifsicle", "-O3", "--lossy=80", "--colors", "128",
                    "--resize-width", "760", "--delay", str(round(dur * 1.5 / 10)),
                    src, "--delete"] + drop + ["-o", f"gif-light/{unit}.gif"],
                   check=True, stderr=subprocess.DEVNULL)


mb = lambda p: os.path.getsize(p) / 1e6
for u in COPY:
    shutil.copy(f"src2/{SRCNAME[u]}", f"gif/{u}.gif")
    light(u, 100)
    print(f"{u:22s} copied      gif {mb(f'gif/{u}.gif'):.2f}MB  light {mb(f'gif-light/{u}.gif'):.2f}MB")

for u, dur in SLICE.items():
    frames = processed(u)
    if u in GIF_CROP:
        frames = [f.crop(GIF_CROP[u]) for f in frames]
    raw, out = f"work/_{u}.gif", f"gif/{u}.gif"
    frames[0].save(raw, save_all=True, append_images=frames[1:], duration=dur, loop=0, optimize=True)
    subprocess.run(["gifsicle", "-O3", "--lossy=40", "--colors", "160", raw, "-o", out],
                   check=True, stderr=subprocess.DEVNULL)
    os.remove(raw)
    light(u, dur)
    print(f"{u:22s} {frames[0].size[0]}x{frames[0].size[1]} {len(frames):3d}f  "
          f"gif {mb(out):.2f}MB  light {mb(f'gif-light/{u}.gif'):.2f}MB")
