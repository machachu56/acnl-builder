"""Painting helpers on top of modkit.paint.Canvas: Pillow lettering (no ImageMagick), stars, patterns, colours."""
import glob
import math
import os

from . import env

env.setup_path()
from modkit.paint import Canvas as _Canvas, mix  # noqa: E402,F401

_FONT_GLOBS = [
    "/usr/share/fonts/**/LiberationSerif-Bold.ttf", "/usr/share/fonts/**/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/**/LiberationSans-Bold.ttf", "/usr/share/fonts/**/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/georgiab.ttf", "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
]
_font_cache = {}


def font_path(name=None):
    """a font file: `name` (a path or a family-ish substring) or the first bold serif/sans found"""
    if name and os.path.isfile(name):
        return name
    pats = ["/usr/share/fonts/**/*%s*" % name] if name else []
    for pat in pats + _FONT_GLOBS:
        hits = sorted(glob.glob(pat, recursive=True))
        hits = [h for h in hits if h.lower().endswith((".ttf", ".otf"))]
        if hits:
            return hits[0]
    return None


def list_fonts():
    out = {}
    for f in glob.glob("/usr/share/fonts/**/*.[to]tf", recursive=True) + glob.glob("C:/Windows/Fonts/*.ttf"):
        out[os.path.splitext(os.path.basename(f))[0]] = f
    return dict(sorted(out.items()))


def _font(size, name=None):
    from PIL import ImageFont
    key = (name, round(size * 4))
    if key not in _font_cache:
        p = font_path(name)
        try:
            _font_cache[key] = ImageFont.truetype(p, int(size * 4)) if p else ImageFont.load_default(int(size * 4))
        except OSError:
            _font_cache[key] = ImageFont.load_default(int(size * 4))
    return _font_cache[key]


class Canvas(_Canvas):
    def text(self, s, r, color, font=None, size=14, outline=None, outline_w=1.5):
        """lettering centred in rect r (drawn at 4x and reduced, so it is smooth)"""
        from PIL import Image, ImageDraw
        x0, y0, x1, y1 = r
        w, h = int(x1 - x0), int(y1 - y0)
        if w <= 0 or h <= 0 or not s:
            return
        f = _font(size, font if not (font or "").startswith("DejaVu-") else None)
        layers = []
        for stroke in ((outline_w if outline else 0), 0):
            im = Image.new("L", (w * 4, h * 4), 0)
            ImageDraw.Draw(im).text((w * 2, h * 2), s, fill=255, font=f, anchor="mm",
                                    stroke_width=int(stroke * 4), stroke_fill=255)
            layers.append(im.resize((w, h), Image.LANCZOS).load())
        for m, col in ((layers[0], outline), (layers[1], color)):
            if col is None:
                continue
            for y in range(h):
                for x in range(w):
                    a = m[x, y] / 255
                    if a:
                        self.blend(x0 + x, y0 + y, col, a)

    def star(self, cx, cy, size, color, points=5, inner=0.45):
        pts = []
        for i in range(points * 2):
            a = -math.pi / 2 + math.pi * i / points
            r = size / 2 * (1 if i % 2 == 0 else inner)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        self.polygon(pts, color)

    def paste_rows(self, rows, x0, y0):
        for j, row in enumerate(rows):
            for i, p in enumerate(row):
                if 0 <= x0 + i < self.w and 0 <= y0 + j < self.h:
                    a = p[3] / 255 if len(p) > 3 else 1
                    self.blend(x0 + i, y0 + j, tuple(p[:3]), a)

    @classmethod
    def from_rows(cls, rows):
        c = cls(len(rows[0]), len(rows))
        c.px = [[list(p) + ([255] if len(p) == 3 else []) for p in row] for row in rows]
        return c


# ---------------------------------------------------------------- colours

def hex_rgb(s, default=(128, 128, 128)):
    if isinstance(s, (list, tuple)):
        return tuple(int(v) for v in s[:3])
    try:
        s = s.lstrip("#")
        if len(s) == 3:
            s = "".join(ch * 2 for ch in s)
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except (ValueError, AttributeError, IndexError):
        return default


def shade(c, k):
    """k < 1 darkens, k > 1 lightens (towards white)"""
    c = hex_rgb(c)
    if k <= 1:
        return tuple(max(0, int(v * k)) for v in c)
    t = k - 1
    return tuple(min(255, int(v + (255 - v) * t)) for v in c)


def rgba(c, a=255):
    return tuple(hex_rgb(c)) + (a,)
