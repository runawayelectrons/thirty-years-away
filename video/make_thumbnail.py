"""Compose the YouTube thumbnail: hero render + type, in the clean black/hot-pink trend style.

python video/make_thumbnail.py [--karaoke]   (needs video/out/thumb_hero.png from make_youtube_art.py -- thumbhero)
-> video/out/youtube_thumbnail.png (1280x720), or youtube_thumbnail_karaoke.png with a KARAOKE badge
"""
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
FONTS = HERE / "fonts"
W, H = 1280, 720
PINK = (255, 46, 136)
WHITE = (240, 240, 244)
LINE1, LINE2 = "FUSION IS ALWAYS", "30 YEARS AWAY"
LABEL = "CLAUDE OPUS 5.5  ×  SUNO"
KARAOKE = "--karaoke" in sys.argv

img = Image.open(OUT / "thumb_hero.png").convert("RGB").resize((W, H), Image.LANCZOS)
dust = ImageDraw.Draw(img)
rnd = random.Random(5)
for _ in range(90):  # faint specks, like dust on the lens
    x, y, g = rnd.randrange(W), rnd.randrange(H), rnd.randrange(25, 70)
    dust.point((x, y), fill=(g, g, g))


def fit(text, fontfile, max_w, start):
    size = start
    while size > 20:
        f = ImageFont.truetype(str(FONTS / fontfile), size)
        if f.getbbox(text)[2] <= max_w:
            return f
        size -= 2
    return f


def glow_text(base, xy, text, font, color, glow=14, glow_alpha=150):
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(xy, text, font=font, fill=color + (glow_alpha,), anchor="ms")
    base.alpha_composite(layer.filter(ImageFilter.GaussianBlur(glow)))
    ImageDraw.Draw(base).text(xy, text, font=font, fill=color + (255,), anchor="ms")


canvas = img.convert("RGBA")
f1 = fit(LINE1, "ArchivoBlack-Regular.ttf", 1130, 120)
f2 = fit(LINE2, "ArchivoBlack-Regular.ttf", 1180, 150)
glow_text(canvas, (W // 2, 560), LINE1, f1, WHITE, glow=10, glow_alpha=90)
glow_text(canvas, (W // 2, 690), LINE2, f2, PINK, glow=18, glow_alpha=170)

# top-left label, letter-spaced mono, with a short pink underline
d = ImageDraw.Draw(canvas)
mono = ImageFont.truetype(str(FONTS / "IBMPlexMono-Medium.ttf"), 26)
x = 48
for ch in LABEL:
    d.text((x, 44), ch, font=mono, fill=(225, 225, 230, 255))
    x += mono.getlength(ch) + 4
d.rectangle((48, 82, 96, 86), fill=PINK + (255,))

if KARAOKE:  # hot-pink badge top-right, same type as the headline
    badge = ImageFont.truetype(str(FONTS / "ArchivoBlack-Regular.ttf"), 44)
    tw = badge.getlength("KARAOKE")
    x1, y0 = W - 48, 34
    x0, y1 = x1 - tw - 48, y0 + 72
    glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).rounded_rectangle((x0, y0, x1, y1), 18, fill=PINK + (140,))
    canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(14)))
    d.rounded_rectangle((x0, y0, x1, y1), 18, fill=PINK + (255,))
    d.text(((x0 + x1) // 2, (y0 + y1) // 2 + 2), "KARAOKE", font=badge, fill=(16, 8, 14, 255), anchor="mm")

name = "youtube_thumbnail_karaoke.png" if KARAOKE else "youtube_thumbnail.png"
canvas.convert("RGB").save(OUT / name)
print("wrote", OUT / name)
