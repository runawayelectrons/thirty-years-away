"""Channel logo: a confined plasma ring with one electron spiralling out (reads as a neon "Q").

python video/make_avatar_logo.py   -> video/out/youtube_avatar.png (800x800)
Drawn in 2D at 4x and downsampled, so lines stay crisp; glow is layered Gaussian blur.
"""
import math
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent / "out"
S = 4  # supersampling
W = 800 * S
PINK = (255, 46, 136)
CORE = (255, 205, 228)
WHITE = (255, 255, 255)

CX, CY, R = 366 * S, 366 * S, 205 * S  # ring a touch up-left, so the escaping electron balances it
RING_W, CORE_W = 15 * S, 4 * S


def background():
    """Near-black with a faint plum lift behind the ring."""
    bg = Image.new("RGB", (W, W), (7, 5, 9))
    glow = Image.new("L", (W, W), 0)
    ImageDraw.Draw(glow).ellipse((CX - R * 1.25, CY - R * 1.25, CX + R * 1.25, CY + R * 1.25), fill=255)
    glow = glow.filter(ImageFilter.GaussianBlur(120 * S))
    tint = Image.new("RGB", (W, W), (30, 10, 26))
    return Image.composite(tint, bg, glow)


STYLE = sys.argv[1] if len(sys.argv) > 1 else "spiral"  # "spiral" or "q"


def q_tail(n=60):
    """A straight Q-tail crossing the ring at the lower right; the electron leaves radially."""
    th = math.radians(42)
    return [(CX + R * (0.82 + 0.78 * i / n) * math.cos(th), CY + R * (0.82 + 0.78 * i / n) * math.sin(th), i / n)
            for i in range(n + 1)]


def spiral(n=200):
    """Leaves the ring at the lower right and spirals out diagonally, like the tail of a Q."""
    pts = []
    for i in range(n + 1):
        t = i / n
        th = math.radians(14 + 34 * t)
        r = R * (1 + 0.62 * t ** 1.35)
        pts.append((CX + r * math.cos(th), CY + r * math.sin(th), t))
    return pts


def stroke_layer(width_fn, color, pts):
    layer = Image.new("RGB", (W, W), (0, 0, 0))
    d = ImageDraw.Draw(layer)
    for (x0, y0, t0), (x1, y1, _) in zip(pts, pts[1:]):
        w = max(1, int(width_fn(t0)))
        d.line((x0, y0, x1, y1), fill=color, width=w)
        d.ellipse((x1 - w / 2, y1 - w / 2, x1 + w / 2, y1 + w / 2), fill=color)
    return layer


def ring_layer(width, color):
    layer = Image.new("RGB", (W, W), (0, 0, 0))
    ImageDraw.Draw(layer).ellipse((CX - R, CY - R, CX + R, CY + R), outline=color, width=width)
    return layer


def glow(layer, radii=(10, 34, 90), gains=(0.9, 0.55, 0.35)):
    out = Image.new("RGB", (W, W), (0, 0, 0))
    for rad, g in zip(radii, gains):
        blurred = layer.filter(ImageFilter.GaussianBlur(rad * S)).point(lambda v, g=g: int(min(255, v * g * 1.6)))
        out = ImageChops.add(out, blurred)
    return out


img = background()
pts = q_tail() if STYLE == "q" else spiral()
ex, ey, _ = pts[-1]

ring = ring_layer(RING_W, PINK)
tail = stroke_layer(lambda t: RING_W * (0.35 + 0.65 * t), PINK, pts)
shape = ImageChops.lighter(ring, tail)
img = ImageChops.add(img, glow(shape))
img = ImageChops.lighter(img, shape)
img = ImageChops.lighter(img, ring_layer(CORE_W, CORE))
img = ImageChops.lighter(img, stroke_layer(lambda t: CORE_W * (0.3 + 0.9 * t), CORE, pts))

# the electron: a small white-hot rounded square with a tight halo
e = Image.new("RGB", (W, W), (0, 0, 0))
h = 20 * S
ImageDraw.Draw(e).rounded_rectangle((ex - h, ey - h, ex + h, ey + h), radius=6 * S, fill=WHITE)
img = ImageChops.add(img, glow(e, radii=(8, 26, 70), gains=(1.0, 0.7, 0.4)))
img = ImageChops.lighter(img, e)

img = img.resize((800, 800), Image.LANCZOS)
name = "youtube_avatar_q.png" if STYLE == "q" else "youtube_avatar.png"
img.save(OUT / name)
print("wrote", OUT / name)
