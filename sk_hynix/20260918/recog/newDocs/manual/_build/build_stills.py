#!/usr/bin/env python3
"""Step PNGs + vertical strip images (the board-proof fallback)."""
import os, sys, subprocess
sys.path.insert(0, "/home/claude/manual/work")
os.chdir("/home/claude/manual")
from PIL import Image, ImageDraw, ImageFont
from steps import UNITS, ORDER, STEP_CROP
from frames_lib import processed

BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
REG  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
f = lambda p, s: ImageFont.truetype(p, s)

INK    = (26, 26, 26)
GRAY   = (110, 116, 124)
ACCENT = (232, 89, 12)
LINE   = (226, 230, 235)
PANEL  = (247, 248, 250)

PAD    = 32
IMG_W  = 900          # column width
MAX_H  = 620          # screenshots never get taller than this


def wrap(draw, text, font, max_w):
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur); cur = ""; continue
        t = cur + ch
        if draw.textlength(t, font=font) > max_w and cur:
            lines.append(cur); cur = ch
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines


def fit(img):
    """Fit inside the column without upscaling a small crop into mush."""
    s = min(IMG_W / img.width, MAX_H / img.height, 1.3)
    return img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)


def step_block(draw_target, x, y, num, caption, shot, width, fnum, fcap):
    """Draw one numbered step (badge + caption + screenshot). Returns height."""
    d = ImageDraw.Draw(draw_target)
    r = 17
    cx, cy = x + r, y + r
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=ACCENT)
    tw = d.textlength(str(num), font=fnum)
    d.text((cx - tw / 2, cy - 13), str(num), fill="white", font=fnum)

    tx = x + 2 * r + 14
    lines = wrap(d, caption, fcap, width - (2 * r + 14))
    ty = y + 2
    for ln in lines:
        d.text((tx, ty), ln, fill=INK, font=fcap)
        ty += 30
    h = max(2 * r, ty - y) + 14

    ox = x + (width - shot.width) // 2
    d.rectangle([ox - 1, y + h - 1, ox + shot.width, y + h + shot.height], outline=LINE)
    draw_target.paste(shot, (ox, y + h))
    return h + shot.height + 2


def build_unit(unit):
    meta   = UNITS[unit]
    frames = processed(unit)
    crop   = STEP_CROP.get(unit)
    shots  = []
    for st in meta["steps"]:
        idx = st[0]
        c = st[2] if len(st) > 2 else crop
        img = frames[min(idx, len(frames) - 1)]
        if c:
            img = img.crop(c)
        shots.append(fit(img))

    fnum   = f(BOLD, 21)
    fcap   = f(REG, 22)
    ftitle = f(BOLD, 40)
    fintro = f(REG, 21)
    ffoot  = f(REG, 17)

    # ---- individual step PNGs -------------------------------------------
    os.makedirs("png", exist_ok=True)
    for i, (st, shot) in enumerate(zip(meta["steps"], shots), 1):
        cap = st[1]
        probe = Image.new("RGB", (10, 10)); d = ImageDraw.Draw(probe)
        lines = wrap(d, cap, fcap, IMG_W - 48)
        head  = max(34, len(lines) * 30) + 14
        canvas = Image.new("RGB", (IMG_W + 2 * PAD, head + shot.height + 2 * PAD + 2), "white")
        step_block(canvas, PAD, PAD, i, cap, shot, IMG_W, fnum, fcap)
        canvas.save(f"png/{unit}_{i}.png")

    # ---- vertical strip --------------------------------------------------
    probe = Image.new("RGB", (10, 10)); pd = ImageDraw.Draw(probe)
    W = IMG_W + 2 * PAD
    intro_lines = wrap(pd, meta["intro"], fintro, IMG_W)
    head_h = 30 + 52 + 10 + len(intro_lines) * 30 + 26

    blocks = []
    for i, (st, shot) in enumerate(zip(meta["steps"], shots), 1):
        cap = st[1]
        lines = wrap(pd, cap, fcap, IMG_W - 48)
        blocks.append(max(34, len(lines) * 30) + 14 + shot.height + 2)
    total = head_h + sum(b + 34 for b in blocks) + 60

    canvas = Image.new("RGB", (W, total), "white")
    d = ImageDraw.Draw(canvas)
    d.rectangle([0, 0, W, 8], fill=ACCENT)
    y = 30
    d.text((PAD, y), meta["title"], fill=INK, font=ftitle); y += 56
    for ln in intro_lines:
        d.text((PAD, y), ln, fill=GRAY, font=fintro); y += 30
    y += 26
    for i, (st, shot) in enumerate(zip(meta["steps"], shots), 1):
        cap = st[1]
        y += step_block(canvas, PAD, y, i, cap, shot, IMG_W, fnum, fcap) + 34
    d.line([PAD, total - 46, W - PAD, total - 46], fill=LINE)
    d.text((PAD, total - 34), "SK hynix AI 회의록 사용 안내", fill=GRAY, font=ffoot)
    os.makedirs("strip", exist_ok=True)
    canvas.save(f"strip/{unit}_steps.png")
    print(f"{unit:20s} steps={len(shots)}  strip={canvas.size}  "
          f"{os.path.getsize(f'strip/{unit}_steps.png')/1e6:.2f}MB")


if __name__ == "__main__":
    for u in ORDER:
        build_unit(u)
