"""Re-derive the processed frame list for each unit from the ORIGINAL sources,
so step indices match the source numbering (gifsicle merges frames, the raw
source does not)."""
import numpy as np
from PIL import Image, ImageSequence

SRC  = "/mnt/user-data/uploads/newDocs"
SRC2 = "/home/claude/manual/src2"

REC_A = list(range(0, 82)) + list(range(82, 162, 6)) + list(range(162, 184))
REC_B = list(range(172, 396))
REC_C = list(range(250, 396))

SOURCES = {
    "01_create-folder":  ("makeFolder/makeFolder.gif",        None),
    "01b_create-folder-full": ("makeFolder/makeFolder-full.gif", None),
    "02_folder-menu":    ("makeFolder/folderMenu.gif",        None),
    "03_rename-folder":  ("makeFolder/renameFolder.gif",      None),
    "04_delete-folder":  ("makeFolder/deleteFolder.gif",      None),
    "05_move-to-folder": ("makeFolder/moveToFolder.gif",      None),
    "06_record":         ("recording/recordMeeting.gif",      REC_A),
    "07_ai-template":    ("recording/recordMeeting.gif",      REC_B),
    "08_template-types": ("recording/recordMeeting.gif",      REC_C),
}

# --- second batch: shipped already trimmed, so no auto-crop -----------------
USAGE_A = list(range(0, 136))
USAGE_B = list(range(128, 224))
DICT_A  = list(range(0, 136))
DICT_B  = list(range(128, 271))

SOURCES2 = {
    "09_home-left":        ("09_home-left.gif",    None),
    "10_home-right":       ("10_home-right.gif",   None),
    "11_search":           ("11_search.gif",       None),
    "12_calendar":         ("12_calendar.gif",     None),
    "13_inbox":            ("13_inbox.gif",        None),
    "14_bookmark":         ("14_bookmark.gif",     None),
    "15_recycle":          ("15_recycle.gif",      None),
    "16a_usage-period":    ("16_usage.gif",        USAGE_A),
    "16b_usage-metrics":   ("16_usage.gif",        USAGE_B),
    "17a_dictionary-open": ("17_dictionary.gif",   DICT_A),
    "17b_dictionary-add":  ("17_dictionary.gif",   DICT_B),
    "18_lnb-menus":        ("18_lnb-menus.gif",    None),
}


def _bbox(frames, pad=10, thresh=10):
    acc = None
    for f in frames[:: max(1, len(frames) // 40)]:
        d = (255 - np.asarray(f, dtype=np.int16)).max(axis=2)
        acc = d if acc is None else np.maximum(acc, d)
    ys, xs = np.where(acc > thresh)
    if len(xs) == 0:
        return None
    return (int(max(0, xs.min() - pad)), int(max(0, ys.min() - pad)),
            int(min(frames[0].width,  xs.max() + 1 + pad)),
            int(min(frames[0].height, ys.max() + 1 + pad)))


def processed(unit, max_w=980):
    if unit in SOURCES2:
        src, keep = SOURCES2[unit]
        im = Image.open(f"{SRC2}/{src}")
        do_crop = False
    else:
        src, keep = SOURCES[unit]
        im = Image.open(f"{SRC}/{src}")
        do_crop = True
    frames = [f.convert("RGB").copy() for f in ImageSequence.Iterator(im)]
    if keep is not None:
        frames = [frames[i] for i in keep]
    if do_crop:
        bb = _bbox(frames)
        if bb:
            frames = [f.crop(bb) for f in frames]
    w, h = frames[0].size
    if w > max_w:
        frames = [f.resize((max_w, int(h * max_w / w)), Image.LANCZOS) for f in frames]
    return frames
