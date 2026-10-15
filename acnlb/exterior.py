"""Procedural town buildings: a parametric cottage (walls, roof, door, windows, sign, ornament) and its textures.

The geometry replaces the model of a town building the player does not normally have (see BASES); the
building keeps that base's collision data and door position. `style` is a plain dict (see DEFAULT);
anything missing takes the default, so a style can be as small as {"sign": {"text": "Café"}}.

    build(style)  -> Exterior with .body / .glow meshes and .paint_*() texture painters
"""
import copy
import math
import random

from . import env, paintx
from .paintx import Canvas, hex_rgb, rgba, shade

env.setup_path()
from modkit.mesh import Atlas, Mesh, circle, heart, norm  # noqa: E402

# game buildings a custom building can take over. body/glow: shape indices of the model; tex: the main texture
BASES = {
    "policeB": dict(slot=0x4D, model="sobj_policeB", label="Modern police station (verified)",
                    body_shape=1, glow_shape=0, body_tex="tex_sobj_policeB_out", mask_tex="cmn_sobj_policeB_out_mask",
                    glow_tex="cmn_sobj_policeB_in", glow_mask="cmn_sobj_policeB_in_mask", two_shape=True),
    "policeA": dict(slot=0x4C, model="sobj_policeA", label="Classic police station (verified)",
                    body_shape=0, glow_shape=None, body_tex="tex_sobj_police", mask_tex="cmn_sobj_police_mask",
                    two_shape=False),
}

DEFAULT = {
    "base": "policeB",
    "width": 40,            # half width of the walls (model units; ~32 = one tile)
    "depth": 64,            # front to back
    "eave": 38,             # wall height / roof edge
    "ridge": 80,            # roof peak
    "colors": {
        "wall": "#f6a8c4", "wall_low": "#d2608c", "roof": "#ee5c96", "roof_rim": "#fff8ec", "trim": "#fffcf4",
        "awning_a": "#ec407c", "awning_b": "#fff6f0", "gold": "#ffe88c", "door": "#2c0e22", "stone": "#bda8b4",
        "wood": "#96604a", "sign_bg": "#b0704e", "sign_fg": "#fff0f6", "sign_outline": "#96184a",
        "glass": "#ffc8d8", "curtain": "#b01446", "lamp": "#ffde96", "leaf": "#68ac54", "flower": "#d2144a",
        "pot": "#e48660", "ornament": "#f43c64",
    },
    "wall_pattern": "planks",        # planks | brick | stucco | stripes
    "roof": {"style": "barrel", "pattern": "panels", "motif": "heart"},      # barrel | gable | flat ; panels | tiles | shingles | plain
    "sign": {"text": "Baisodrome", "font": None, "size": 15},
    "ornament": "heart",             # heart | star | none (big shape on the front)
    "windows": "round",              # round | square | none
    "awning": True,
    "door": "beads",                 # beads | dark | wood
    "bushes": True,
    "lanterns": True,
    "overlay": None,                 # PNG (asset name) painted over the body texture, same size
}

PRESETS = {
    "love_hotel": {},
    "cozy_cottage": {
        "colors": {"wall": "#f2e3c4", "wall_low": "#8f6a4a", "roof": "#b5483a", "roof_rim": "#e8d8b8", "trim": "#fff6e0",
                   "awning_a": "#3f7f4f", "awning_b": "#f6efde", "gold": "#d9b45a", "door": "#3a2418", "stone": "#9a9186",
                   "wood": "#7a5236", "sign_bg": "#6e4a30", "sign_fg": "#fff1d0", "sign_outline": "#3a2418",
                   "glass": "#ffe9a8", "curtain": "#a63c2c", "lamp": "#ffd27a", "leaf": "#5d9a48", "flower": "#e0603a",
                   "pot": "#b8643c", "ornament": "#d9b45a"},
        "wall_pattern": "stucco", "roof": {"style": "gable", "pattern": "shingles", "motif": "none"},
        "sign": {"text": "Cottage", "font": None, "size": 16}, "ornament": "none", "windows": "square", "door": "wood",
    },
    "red_brick_shop": {
        "colors": {"wall": "#b9553f", "wall_low": "#5a4a46", "roof": "#3f4a5a", "roof_rim": "#d8d4cc", "trim": "#f2ede4",
                   "awning_a": "#2f5f9f", "awning_b": "#f6f2ea", "gold": "#e0c060", "door": "#2a2024", "stone": "#8a8484",
                   "wood": "#6a4a38", "sign_bg": "#2a3a52", "sign_fg": "#fff6e0", "sign_outline": "#101820",
                   "glass": "#cfe8ff", "curtain": "#2f5f9f", "lamp": "#ffe4a0", "leaf": "#5a9a50", "flower": "#e8c040",
                   "pot": "#9a5a3c", "ornament": "#e0c060"},
        "wall_pattern": "brick", "roof": {"style": "flat", "pattern": "plain", "motif": "none"},
        "sign": {"text": "Shop", "font": None, "size": 17}, "ornament": "star", "windows": "square", "door": "dark",
        "eave": 52, "ridge": 52,
    },
}


def merged(style):
    """style with every default filled in"""
    out = copy.deepcopy(DEFAULT)

    def upd(d, s):
        for k, v in (s or {}).items():
            if isinstance(v, dict) and isinstance(d.get(k), dict):
                upd(d[k], v)
            else:
                d[k] = v
    upd(out, style)
    return out


# ---------------------------------------------------------------- atlases (texture regions)

BODY_REGIONS = {
    "wall": (0, 0, 96, 56), "wall_low": (0, 56, 96, 72), "stone": (0, 72, 96, 88),
    "sign": (0, 88, 96, 112), "step": (0, 112, 48, 128), "gold": (48, 112, 96, 128),
    "roof": (96, 0, 192, 64), "roof_edge": (192, 0, 256, 8), "roof_under": (192, 8, 256, 16),
    "trim": (192, 16, 256, 24), "wood": (192, 24, 256, 40), "awning": (192, 40, 256, 64),
    "heart": (96, 64, 160, 128), "heart_side": (160, 64, 192, 72), "flower": (160, 72, 192, 96),
    "lamp": (160, 96, 192, 112), "dark": (160, 112, 192, 128),
    "rose": (192, 64, 256, 96), "pot": (192, 96, 256, 128),
}
GLOW_REGIONS = {"window": (0, 0, 32, 32), "curtain": (32, 0, 64, 64), "window_side": (0, 32, 32, 64)}
# when the base has no separate glow shape, the glowing parts live in the lower half of a 256 x 256 body atlas
BODY_REGIONS_1 = dict(BODY_REGIONS, window=(0, 128, 32, 160), window_side=(32, 128, 64, 160), curtain=(64, 128, 96, 192))


class Exterior:
    def __init__(self, style):
        self.s = merged(style)
        self.base = BASES[self.s["base"]]
        self.two = self.base["two_shape"]
        self.col = {k: hex_rgb(v) for k, v in self.s["colors"].items()}
        if self.two:
            self.body_atlas, self.glow_atlas = Atlas(256, 128, BODY_REGIONS), Atlas(64, 64, GLOW_REGIONS)
        else:
            self.body_atlas, self.glow_atlas = Atlas(256, 256, BODY_REGIONS_1), None
        self.W = float(self.s["width"])
        self.F = 10.0
        self.B = self.F - float(self.s["depth"])
        self.C = 6.0
        self.PLINTH = 4.0
        self.LOW = self.PLINTH + 12
        self.EAVE = float(self.s["eave"])
        self.RIDGE = max(float(self.s["ridge"]), self.EAVE)
        self.TH = 6.0
        self.OV, self.OV_F, self.OV_B = 8.0, 4.0, 5.0
        self.EX = self.W + self.OV
        self.DOOR_W, self.DOOR_H = 11.0, 30.0
        self.roof_style = self.s["roof"]["style"]
        if self.roof_style == "flat":
            self.RIDGE = self.EAVE
        self.body, self.glow = None, None

    @property
    def regions(self):
        return self.body_atlas.regions

    # -- roof profile
    def roof_top(self, x):
        u = min(1.0, abs(x) / self.EX)
        if self.roof_style == "gable":
            return self.EAVE + (self.RIDGE - self.EAVE) * (1 - u)
        if self.roof_style == "flat":
            return self.EAVE + 2
        return self.EAVE + (self.RIDGE - self.EAVE) * (1 - u * u) ** 0.55

    def roof_bottom(self, x):
        return self.roof_top(x) - self.TH

    def roof_normal(self, x):
        if self.roof_style == "flat":
            return (0, 1, 0)
        d = 0.01
        if self.roof_style == "gable":
            slope = (self.roof_top(x + d) - self.roof_top(x - d)) / (2 * d)
            return norm((-slope, 1, 0))
        slope = (self.roof_top(x + d) - self.roof_top(x - d)) / (2 * d)
        return norm((-slope, 1, 0))

    # ------------------------------------------------------------ textures
    def _planks(self, c, r, width, base, dark, light, seed=0):
        x0, y0, x1, y1 = r
        for k, x in enumerate(range(x0, x1, width)):
            tone = ((k * 5 + seed) % 3 - 1) * 6
            top = tuple(min(255, v + tone + 8) for v in base) + (255,)
            bot = tuple(max(0, v + tone - 10) for v in base) + (255,)
            c.vgrad((x, y0, min(x1, x + width), y1), top, bot)
            c.rect((x + 1, y0, x + 3, y1), light + (255,), 0.55)
            c.rect((x + width - 1, y0, x + width, y1), dark + (255,), 0.9)
            for j in range(2):
                yy = y0 + (k * 17 + j * 23 + seed) % max(1, y1 - y0 - 4)
                c.rect((x + 4, yy, x + width - 3, yy + 1), dark + (255,), 0.18)

    def _bricks(self, c, r, base, dark, light, seed=0):
        x0, y0, x1, y1 = r
        c.rect(r, dark + (255,))
        rnd = random.Random(seed)
        for row, y in enumerate(range(y0, y1, 6)):
            for x in range(x0 - (row % 2) * 6, x1, 12):
                t = rnd.uniform(-14, 14)
                col = tuple(max(0, min(255, v + t)) for v in base) + (255,)
                c.rect((max(x0, x + 1), y + 1, min(x1, x + 11), min(y1, y + 5)), col)
                c.rect((max(x0, x + 1), y + 1, min(x1, x + 11), y + 2), light + (255,), 0.25)

    def _stucco(self, c, r, base, dark, light, seed=0):
        c.vgrad(r, base + (255,), tuple(max(0, v - 14) for v in base) + (255,))
        c.noise(r, 9, seed=seed + 3, scale=2)
        c.noise(r, 5, seed=seed + 4, scale=1)

    def _stripes(self, c, r, base, dark, light, seed=0):
        x0, y0, x1, y1 = r
        for k, x in enumerate(range(x0, x1, 8)):
            col = base if k % 2 == 0 else light
            c.vgrad((x, y0, min(x1, x + 8), y1), col + (255,), tuple(max(0, v - 18) for v in col) + (255,))

    def _wall(self, c, r, base, dark, light, seed=0):
        pat = self.s["wall_pattern"]
        {"planks": lambda: self._planks(c, r, 12, base, dark, light, seed),
         "brick": lambda: self._bricks(c, r, base, dark, light, seed),
         "stucco": lambda: self._stucco(c, r, base, dark, light, seed),
         "stripes": lambda: self._stripes(c, r, base, dark, light, seed)}.get(pat, lambda: self._planks(c, r, 12, base, dark, light, seed))()

    def _motif(self, c, x, y, size, color, kind=None):
        kind = kind or self.s["roof"]["motif"]
        if kind == "heart":
            c.heart(x, y, size, color)
        elif kind == "star":
            c.star(x, y, size * 1.2, color)

    def _paint_roof(self, c, r):
        x0, y0, x1, y1 = r
        base = self.col["roof"]
        pat = self.s["roof"]["pattern"]
        top, bot = shade(base, 1.05), shade(base, 0.78)
        light = shade(base, 1.35)
        if pat == "panels":
            ph = 8
            for k, y in enumerate(range(y0, y1, ph)):
                c.vgrad((x0, y, x1, y + ph), top + (255,), bot + (255,))
                c.rect((x0, y + 1, x1, y + 3), light + (255,), 0.55)
                c.rect((x0, y + ph - 1, x1, y + ph), shade(base, 0.45) + (255,))
                if self.s["roof"]["motif"] != "none":
                    for j in range(4):
                        hx = x0 + 8 + ((j * 23 + k * 11) % (x1 - x0 - 16))
                        self._motif(c, hx, y + 4.5, 4, shade(base, 1.6) + (255,))
        elif pat in ("tiles", "shingles"):
            c.rect(r, shade(base, 0.7) + (255,))
            step = 6 if pat == "shingles" else 8
            rnd = random.Random(7)
            for row, y in enumerate(range(y0, y1, step)):
                for x in range(x0 - (row % 2) * step, x1, step * 2 if pat == "tiles" else 10):
                    t = rnd.uniform(0.9, 1.1)
                    col = tuple(min(255, int(v * t)) for v in base) + (255,)
                    if pat == "tiles":
                        c.rrect((x, y, x + step * 2, y + step + 3), 3, shade(base, 0.6) + (255,))
                        c.rrect((x + 1, y, x + step * 2 - 1, y + step + 1), 3, col)
                    else:
                        c.rect((x + 1, y, x + 9, y + step), col)
                        c.rect((x + 1, y + step - 1, x + 9, y + step), shade(base, 0.55) + (255,))
        else:
            c.vgrad(r, top + (255,), bot + (255,))
            c.noise(r, 5, seed=11, scale=3)
        for y in range(y0, y1):          # the middle of a barrel/gable roof catches more light
            for x in range(x0, x1):
                s = (x - x0) / (x1 - x0 - 1)
                k = 0.86 + 0.18 * math.cos((s - 0.5) * math.pi)
                p = c.px[y][x]
                for i in range(3):
                    p[i] = min(255, p[i] * k)

    def paint_body(self, winter=False, overlay=None):
        two = self.two
        c = Canvas(256, 128 if two else 256, (255, 255, 255, 255))
        r, col = self.regions, self.col
        wall, wall_low = col["wall"], col["wall_low"]
        self._wall(c, r["wall"], wall, shade(wall, 0.68), shade(wall, 1.35))
        x0, y0, x1, y1 = r["wall_low"]
        self._planks(c, r["wall_low"], 8, wall_low, shade(wall_low, 0.7), shade(wall_low, 1.35), seed=2)
        c.rect((x0, y0, x1, y0 + 3), rgba(col["trim"]))
        c.rect((x0, y0 + 3, x1, y0 + 4), shade(wall_low, 0.8) + (255,))
        c.rect((x0, y1 - 2, x1, y1), shade(wall_low, 0.55) + (255,), 0.6)
        x0, y0, x1, y1 = r["stone"]                                    # plinth stones
        st = col["stone"]
        c.rect(r["stone"], shade(st, 0.62) + (255,))
        for row, y in enumerate(range(y0, y1, 8)):
            for k, x in enumerate(range(x0 - (row % 2) * 8, x1, 16)):
                t = ((k * 7 + row * 13) % 4) * 0.05 + 0.92
                tone = tuple(min(255, int(v * t)) for v in st)
                c.rrect((x + 1, y + 1, x + 15, y + 7.5), 3, shade(tone, 0.8) + (255,))
                c.rrect((x + 1.5, y + 1, x + 14, y + 6), 2.5, tone + (255,))
                c.rect((x + 4, y + 2, x + 9, y + 3), (255, 250, 255, 255), 0.35)
        x0, y0, x1, y1 = r["sign"]                                     # sign board
        sg = self.s["sign"]
        c.rect(r["sign"], shade(col["sign_bg"], 0.55) + (255,))
        c.rrect((x0 + 2, y0 + 2, x1 - 2, y1 - 2), 4, shade(col["sign_bg"], 0.9) + (255,))
        c.vgrad((x0 + 4, y0 + 4, x1 - 4, y1 - 4), shade(col["sign_bg"], 1.08) + (255,), shade(col["sign_bg"], 0.92) + (255,))
        c.text(sg.get("text", ""), (x0 + 5, y0 + 4, x1 - 5, y1 - 4), rgba(col["sign_fg"]), font=sg.get("font"),
               size=sg.get("size", 15), outline=rgba(col["sign_outline"]), outline_w=1.8)
        for x in (x0 + 5, x1 - 6):
            c.circle(x, (y0 + y1) / 2, 1.5, rgba(col["gold"]))
        c.vgrad(r["step"], shade(col["stone"], 1.25) + (255,), shade(col["stone"], 0.95) + (255,))
        c.edge_shade(r["step"], 30, 2)
        x0, y0, x1, y1 = r["gold"]
        c.vgrad(r["gold"], shade(col["gold"], 1.1) + (255,), shade(col["gold"], 0.75) + (255,))
        c.rect((x0, y0 + 2, x1, y0 + 4), shade(col["gold"], 1.5) + (255,), 0.7)
        self._paint_roof(c, r["roof"])
        c.vgrad(r["roof_edge"], rgba(col["roof_rim"]), shade(col["roof_rim"], 0.87) + (255,))
        c.vgrad(r["roof_under"], shade(col["roof"], 0.5) + (255,), shade(col["roof"], 0.35) + (255,))
        c.vgrad(r["trim"], rgba(col["trim"]), shade(col["trim"], 0.9) + (255,))
        x0, y0, x1, y1 = r["wood"]
        c.vgrad(r["wood"], shade(col["wood"], 1.1) + (255,), shade(col["wood"], 0.8) + (255,))
        for y in range(y0 + 3, y1, 5):
            c.rect((x0, y, x1, y + 1), shade(col["wood"], 0.6) + (255,), 0.5)
        x0, y0, x1, y1 = r["awning"]                                    # awning stripes
        for k, x in enumerate(range(x0, x1, 8)):
            cc = col["awning_a"] if k % 2 == 0 else col["awning_b"]
            c.vgrad((x, y0, x + 8, y1), cc + (255,), shade(cc, 0.86) + (255,))
            c.rect((x, y0, x + 1, y1), (255, 255, 255, 255), 0.25)
        # big ornament
        x0, y0, x1, y1 = r["heart"]
        orn = col["ornament"]
        c.rect(r["heart"], shade(orn, 0.7) + (255,))
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2 + 1
        kind = self.s["ornament"] if self.s["ornament"] != "none" else "heart"
        if kind == "star":
            c.star(cx, cy, 62, shade(orn, 0.8) + (255,))
            c.star(cx, cy - 1, 54, orn + (255,))
            c.star(cx - 2, cy - 3, 36, shade(orn, 1.3) + (255,))
        else:
            c.heart(cx, cy, 58, shade(orn, 0.85) + (255,))
            c.heart(cx, cy - 1, 50, orn + (255,))
            c.heart(cx - 3, cy - 4, 34, shade(orn, 1.35) + (255,))
            c.circle(x0 + 19, y0 + 20, 5.5, shade(orn, 1.75) + (255,))
            c.circle(x0 + 26, y0 + 15, 2.5, shade(orn, 1.95) + (255,))
        c.vgrad(r["heart_side"], shade(orn, 0.8) + (255,), shade(orn, 0.55) + (255,))
        x0, y0, x1, y1 = r["flower"]                                    # window box
        c.vgrad((x0, y0 + 12, x1, y1), shade(col["wood"], 1.15) + (255,), shade(col["wood"], 0.85) + (255,))
        c.rect((x0, y0 + 12, x1, y0 + 14), shade(col["wood"], 1.4) + (255,))
        c.vgrad((x0, y0, x1, y0 + 12), shade(col["leaf"], 1.05) + (255,), shade(col["leaf"], 0.7) + (255,))
        for k in range(8):
            cc = [col["flower"], (255, 236, 130), (255, 255, 255), shade(col["flower"], 0.8)][k % 4]
            c.circle(x0 + 2 + k * 4, y0 + 4 + (k % 3) * 2.5, 2.2, tuple(cc) + (255,))
        x0, y0, x1, y1 = r["rose"]                                      # bush
        c.vgrad(r["rose"], shade(col["leaf"], 1.0) + (255,), shade(col["leaf"], 0.6) + (255,))
        for k in range(40):
            lx, ly = x0 + (k * 29) % 64, y0 + (k * 13) % 32
            c.circle(lx, ly, 2.4, shade(col["leaf"], 1.2 if k % 2 else 0.75) + (255,))
        for k in range(12):
            rx, ry = x0 + 5 + (k * 37) % 56, y0 + 4 + (k * 11) % 24
            c.circle(rx, ry, 3, col["flower"] + (255,))
            c.circle(rx - 0.6, ry - 0.6, 1.8, shade(col["flower"], 1.4) + (255,))
        x0, y0, x1, y1 = r["pot"]
        c.vgrad(r["pot"], shade(col["pot"], 1.1) + (255,), shade(col["pot"], 0.72) + (255,))
        c.rect((x0, y0, x1, y0 + 6), shade(col["pot"], 1.2) + (255,))
        c.rect((x0, y0 + 6, x1, y0 + 7), shade(col["pot"], 0.6) + (255,))
        c.heart((x0 + x1) / 2, (y0 + y1) / 2 + 4, 14, (255, 236, 236, 255))
        x0, y0, x1, y1 = r["lamp"]
        c.rect(r["lamp"], (70, 50, 60, 255))
        c.rrect((x0 + 4, y0 + 3, x1 - 4, y1 - 3), 2, rgba(col["lamp"]))
        c.heart((x0 + x1) / 2, (y0 + y1) / 2, 10, shade(col["ornament"], 1.2) + (255,))
        c.vgrad(r["dark"], shade(col["door"], 1.1) + (255,), shade(col["door"], 0.6) + (255,))

        if not two:                                                    # glowing parts, in the same atlas
            self._paint_glow_regions(c, r)
        if winter:
            x0, y0, x1, y1 = r["roof"]
            for y in range(y0, y1):
                for x in range(x0, x1):
                    k = 0.8 + 0.1 * math.sin(x * 0.5 + y * 0.3)
                    c.blend(x, y, (246, 248, 255, 255), k)
            c.noise(r["roof"], 5, seed=13, scale=3)
            for name in ("step", "roof_edge"):
                c.rect(r[name], (240, 244, 252, 255), 0.7)
            for name in ("flower", "rose"):
                x0, y0, x1, y1 = r[name]
                c.rect((x0, y0, x1, y0 + 8), (244, 246, 255, 255), 0.85)
        if overlay:
            c.paste_rows(overlay, 0, 0)
        for y in range(c.h):                                           # alpha: gloss / detail, low like the game's
            for x in range(c.w):
                p = c.px[y][x]
                lum = (p[0] * 3 + p[1] * 6 + p[2]) / 10
                p[3] = 50 + lum * 0.25
        return c

    def _paint_glow_regions(self, c, r):
        col = self.col
        for name in ("window", "window_side"):
            x0, y0, x1, y1 = r[name]
            c.vgrad(r[name], shade(col["glass"], 1.1) + (255,), shade(col["glass"], 0.85) + (255,))
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            if self.s["windows"] == "round" or True:
                c.heart(cx, cy + 1, 13, col["curtain"] + (255,)) if self.s["ornament"] == "heart" else \
                    c.star(cx, cy, 14, col["curtain"] + (255,)) if self.s["ornament"] == "star" else None
            cur = col["curtain"]
            c.polygon([(x0, y0), (x0 + 12, y0), (x0 + 6, y0 + 14), (x0 + 3, y1), (x0, y1)], cur + (255,))
            c.polygon([(x1, y0), (x1 - 12, y0), (x1 - 6, y0 + 14), (x1 - 3, y1), (x1, y1)], cur + (255,))
            c.rect((x0, y0, x1, y0 + 3), shade(cur, 0.8) + (255,))
        x0, y0, x1, y1 = r["curtain"]
        door = self.s["door"]
        if door == "wood":
            c.vgrad(r["curtain"], shade(col["wood"], 1.0) + (255,), shade(col["wood"], 0.7) + (255,))
            for x in range(x0 + 4, x1, 8):
                c.rect((x, y0, x + 1, y1), shade(col["wood"], 0.5) + (255,), 0.7)
            c.circle(x1 - 6, (y0 + y1) / 2, 2, rgba(col["gold"]))
        else:
            c.vgrad(r["curtain"], shade(col["door"], 1.2) + (255,), shade(col["door"], 0.7) + (255,))
            if door == "beads":
                c.heart((x0 + x1) / 2, y0 + 22, 14, shade(col["curtain"], 0.75) + (255,))
                for k, x in enumerate(range(x0 + 2, x1, 4)):
                    for j, y in enumerate(range(y0 + 2 + (k % 2) * 2, y1 - 4, 4)):
                        cc = [shade(col["curtain"], 1.2), shade(col["curtain"], 0.85), shade(col["curtain"], 1.0)][(j + k) % 3]
                        c.circle(x + 0.5, y, 1.1, tuple(cc) + (255,))

    def paint_body_mask(self):
        """night emission of the body texture (half resolution)"""
        two = self.two
        c = Canvas(256, 128 if two else 256, (0, 0, 0, 255))
        r = self.regions
        if self.s["lanterns"]:
            c.rect(r["lamp"], (255, 255, 255, 255))
        x0, y0, x1, y1 = r["heart"]
        if self.s["ornament"] != "none":
            if self.s["ornament"] == "star":
                c.star((x0 + x1) / 2, (y0 + y1) / 2 + 1, 56, (230, 230, 230, 255))
            else:
                c.heart((x0 + x1) / 2, (y0 + y1) / 2 + 1, 54, (230, 230, 230, 255))
        c.rect(r["sign"], (110, 110, 110, 255))
        c.rect(r["gold"], (80, 80, 80, 255))
        if not two:
            for name in ("window", "window_side"):
                c.rect(r[name], (150, 150, 150, 255))
            c.rect(r["curtain"], (110, 110, 110, 255))
        return c.downscale(2)

    def paint_glow(self):
        """the glowing parts' own texture (64 x 64): windows and doorway"""
        c = Canvas(64, 64, (0, 0, 0, 255))
        self._paint_glow_regions(c, GLOW_REGIONS)
        for y in range(c.h):
            for x in range(c.w):
                c.px[y][x][3] = 255
        return c

    def paint_glow_mask(self):
        c = Canvas(64, 64, (96, 96, 96, 255))
        c.rect(GLOW_REGIONS["curtain"], (150, 150, 150, 255))
        return c

    # ------------------------------------------------------------ geometry
    def ao(self, p):
        k = 0.74 + 0.26 * min(1.0, max(0.0, (p[1] - self.PLINTH) / 20))
        if p[1] > self.roof_bottom(p[0]) - 6 and self.B - 1 < p[2] < self.F + 1:
            k *= 0.86
        return k

    def footprint(self):
        W, F, B, C = self.W, self.F, self.B, self.C
        return [(-W + C, F), (W - C, F), (W, F - C), (W, B + C), (W - C, B), (-W + C, B), (-W, B + C), (-W, F - C)]

    @staticmethod
    def smooth_quad(m, pts, normals, st, region, shade_fn=None):
        idx = []
        for p, n, (s, t) in zip(pts, normals, st):
            k = shade_fn(p) if shade_fn else 1
            idx.append(m._vert(p, n, m.atlas.uv(region, s, t), (k, k, k, 1)))
        m.tris += [idx[0], idx[1], idx[2], idx[0], idx[2], idx[3]]

    def dome(self, m, cx, cy, cz, rx, ry, region, n=8, rings=4):
        def p(i, j):
            a = 2 * math.pi * i / n
            e = (math.pi / 2) * j / rings
            return (cx + rx * math.cos(e) * math.cos(a), cy + ry * math.sin(e), cz + rx * math.cos(e) * math.sin(a))
        for j in range(rings):
            for i in range(n):
                q = [p(i + 1, j), p(i, j), p(i, j + 1), p(i + 1, j + 1)]
                ns = [norm(((v[0] - cx) / rx, (v[1] - cy) / ry, (v[2] - cz) / rx)) for v in q]
                self.smooth_quad(m, q, ns, [((i + 1) / n, j / rings), (i / n, j / rings), (i / n, (j + 1) / rings),
                                            ((i + 1) / n, (j + 1) / rings)], region)

    def cylinder(self, m, cx, cz, r, y0, y1, region, n=8, top=None, shade_fn=None):
        pts = circle(cx, cz, r, n, math.pi / n)
        for i in range(n):
            (ax, az), (bx, bz) = pts[i], pts[(i + 1) % n]
            na, nb = norm((ax - cx, 0, az - cz)), norm((bx - cx, 0, bz - cz))
            self.smooth_quad(m, [(bx, y0, bz), (ax, y0, az), (ax, y1, az), (bx, y1, bz)], [nb, na, na, nb],
                             [(i / n, 0), ((i + 1) / n, 0), ((i + 1) / n, 1), (i / n, 1)], region, shade_fn)
        if top:
            m.poly([(x, y1, z) for x, z in pts[::-1]], [(0.5, 0.5)] * n, top, normal=(0, 1, 0))

    @staticmethod
    def star_outline(cx, cy, size, points=5, inner=0.45):
        pts = []
        for i in range(points * 2):
            a = math.pi / 2 - math.pi * i / points          # clockwise from the top...
            r = size / 2 * (1 if i % 2 == 0 else inner)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        return pts[::-1]                                     # ...reversed: counter-clockwise

    def build(self):
        s = self.s
        two = self.two
        body = Mesh(self.body_atlas)
        glow = Mesh(self.glow_atlas) if two else body
        m = body
        W, F, B, C, PLINTH, LOW = self.W, self.F, self.B, self.C, self.PLINTH, self.LOW
        DOOR_W, DOOR_H, RIDGE, EAVE = self.DOOR_W, self.DOOR_H, self.RIDGE, self.EAVE
        roof_top, roof_bottom, ao = self.roof_top, self.roof_bottom, self.ao
        rng = max(1.0, self.RIDGE - LOW)

        m.box(-W - 3, W + 3, 0, PLINTH, B - 3, F + 3,
              {"front": "stone", "back": "stone", "left": "stone", "right": "stone", "top": "step"})
        m.box(-DOOR_W - 7, DOOR_W + 7, 0, 3, F + 3, F + 12, {"front": "step", "left": "step", "right": "step", "top": "step"})

        fp = self.footprint()
        span = 2 * W
        top_h = max(1.0, max(roof_bottom(-W), roof_bottom(0)) - LOW)

        def wall_strip(a, b, y0, top_a, top_b, reg, s_of):
            sa, sb = s_of(a), s_of(b)
            h = (LOW - PLINTH) if reg == "wall_low" else top_h
            m.quad((a[0], y0, a[1]), (b[0], y0, b[1]), (b[0], top_b, b[1]), (a[0], top_a, a[1]), reg, shade=ao,
                   st=((sa, 0), (sb, 0), (sb, (top_b - y0) / h), (sa, (top_a - y0) / h)))

        for i in range(len(fp)):
            a, b = fp[i], fp[(i + 1) % len(fp)]
            frontback = abs(a[1] - b[1]) < 1e-6
            if frontback:
                s_of = (lambda p: (p[0] + W) / span) if a[1] > 0 else (lambda p: (W - p[0]) / span)
            else:
                s_of = (lambda p: (p[1] - B) / (F - B)) if a[0] > 0 else (lambda p: (F - p[1]) / (F - B))
            cuts = [0.0, 1.0]
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            if frontback:
                cuts += [k / math.ceil(L / 14) for k in range(1, math.ceil(L / 14))]
                if (a[0] < 0 < b[0]) or (b[0] < 0 < a[0]):
                    cuts.append((0 - a[0]) / (b[0] - a[0]))
            if i == 0:
                cuts += [(x - a[0]) / (b[0] - a[0]) for x in (-DOOR_W, DOOR_W)]
            cuts = sorted(set(round(t, 6) for t in cuts))
            for t0, t1 in zip(cuts, cuts[1:]):
                p = (a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0)
                q = (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)
                door = i == 0 and -DOOR_W - 1e-6 <= p[0] and q[0] <= DOOR_W + 1e-6
                if door:
                    y_lo = PLINTH + DOOR_H
                    if roof_bottom(p[0]) > y_lo and roof_bottom(q[0]) > y_lo:
                        m.quad((p[0], y_lo, p[1]), (q[0], y_lo, q[1]), (q[0], roof_bottom(q[0]), q[1]),
                               (p[0], roof_bottom(p[0]), p[1]), "wall", shade=ao,
                               st=((s_of(p), (y_lo - LOW) / top_h), (s_of(q), (y_lo - LOW) / top_h),
                                   (s_of(q), (roof_bottom(q[0]) - LOW) / top_h), (s_of(p), (roof_bottom(p[0]) - LOW) / top_h)))
                    continue
                wall_strip(p, q, PLINTH, LOW, LOW, "wall_low", s_of)
                wall_strip(p, q, LOW, max(LOW + 0.1, roof_bottom(p[0])), max(LOW + 0.1, roof_bottom(q[0])), "wall", s_of)

        for x, z in ((-W + C / 2, F - C / 2), (W - C / 2, F - C / 2)):
            self.cylinder(m, x, z, 3.6, PLINTH, roof_bottom(x) + 1, "trim", n=5, shade_fn=ao)

        # doorway
        D = 6
        dy0, dy1 = PLINTH, PLINTH + DOOR_H
        m.quad((-DOOR_W, dy0, F - D), (-DOOR_W, dy0, F), (-DOOR_W, dy1, F), (-DOOR_W, dy1, F - D), "dark")
        m.quad((DOOR_W, dy0, F), (DOOR_W, dy0, F - D), (DOOR_W, dy1, F - D), (DOOR_W, dy1, F), "dark")
        m.quad((-DOOR_W, dy1, F), (DOOR_W, dy1, F), (DOOR_W, dy1, F - D), (-DOOR_W, dy1, F - D), "dark")
        glow.quad((-DOOR_W, dy0, F - D), (DOOR_W, dy0, F - D), (DOOR_W, dy1, F - D), (-DOOR_W, dy1, F - D), "curtain")
        m.box(-DOOR_W - 3.5, -DOOR_W, PLINTH, dy1 + 3.5, F, F + 2.5, {"front": "gold", "left": "gold", "right": "gold"})
        m.box(DOOR_W, DOOR_W + 3.5, PLINTH, dy1 + 3.5, F, F + 2.5, {"front": "gold", "left": "gold", "right": "gold"})
        m.box(-DOOR_W - 3.5, DOOR_W + 3.5, dy1, dy1 + 3.5, F, F + 2.5, {"front": "gold", "top": "gold", "bottom": "gold"})

        if s["awning"]:
            ax0, ax1 = -DOOR_W - 8, DOOR_W + 8
            top, low, depth = dy1 + 12, dy1 + 4, 14
            m.quad((ax0, low, F + depth), (ax1, low, F + depth), (ax1, top, F), (ax0, top, F), "awning")
            m.quad((ax0, low - 5, F + depth), (ax1, low - 5, F + depth), (ax1, low, F + depth), (ax0, low, F + depth), "awning",
                   st=((0, 0), (1, 0), (1, 0.3), (0, 0.3)))
            m.quad((ax1, low - 5, F + depth), (ax0, low - 5, F + depth), (ax0, top - 1, F), (ax1, top - 1, F), "roof_under")
            for x, sgn in ((ax0, -1), (ax1, 1)):
                pts = [(x, low - 5, F + depth), (x, low, F + depth), (x, top, F), (x, top - 1, F)]
                st = [(0, 0), (0, 0.3), (1, 1), (1, 0.9)]
                if sgn < 0:
                    pts, st = pts[::-1], st[::-1]
                m.poly(pts, st, "awning")
            cyl_z = F + depth
            for k in range(4):
                a0, a1 = 2 * math.pi * k / 4, 2 * math.pi * (k + 1) / 4
                p = [(ax0, low - 5 + 1.6 * math.sin(a), cyl_z + 1.6 * math.cos(a)) for a in (a0, a1)]
                q = [(ax1, y, z) for _, y, z in p]
                self.smooth_quad(m, [p[0], q[0], q[1], p[1]],
                                 [(0, math.sin(a0), math.cos(a0)), (0, math.sin(a0), math.cos(a0)),
                                  (0, math.sin(a1), math.cos(a1)), (0, math.sin(a1), math.cos(a1))],
                                 [(0, 0), (1, 0), (1, 1), (0, 1)], "trim")

        # windows
        kind = s["windows"]

        def front(x, y, d):
            return (x, y, F + d)

        def window(cx, cy, place):
            if kind == "square":
                n, ro, ri, st0 = 4, 12.0, 8.4, math.pi / 4
            else:
                n, ro, ri, st0 = 8, 10.0, 7.0, math.pi / 8
            outer, inner = circle(0, 0, ro, n, st0), circle(0, 0, ri, n, st0)
            for i in range(n):
                j = (i + 1) % n
                m.quad(place(outer[i][0] + cx, outer[i][1] + cy, 1.6), place(outer[j][0] + cx, outer[j][1] + cy, 1.6),
                       place(inner[j][0] + cx, inner[j][1] + cy, 1.6), place(inner[i][0] + cx, inner[i][1] + cy, 1.6),
                       "trim", st=((i / n, 0), (j / n, 0), (j / n, 1), (i / n, 1)))
            pane = [place(x + cx, y + cy, 0.2) for x, y in inner]
            glow.poly(pane, [((x + ri) / (2 * ri), (y + ri) / (2 * ri)) for x, y in inner], "window")
            sx0, sx1 = cx - ro, cx + ro
            corners = [place(sx0, cy - ro - 2, 0), place(sx1, cy - ro - 2, 0), place(sx1, cy - ro - 2, 5), place(sx0, cy - ro - 2, 5)]
            lows = [place(sx0, cy - ro - 7, 0), place(sx1, cy - ro - 7, 0), place(sx1, cy - ro - 7, 5), place(sx0, cy - ro - 7, 5)]
            m.quad(lows[3], lows[2], corners[2], corners[3], "flower", st=((0, 0), (1, 0), (1, 0.45), (0, 0.45)))
            m.quad(corners[3], corners[2], corners[1], corners[0], "flower", st=((0, 0.55), (1, 0.55), (1, 1), (0, 1)))
            m.quad(lows[0], lows[3], corners[3], corners[0], "wood")
            m.quad(lows[2], lows[1], corners[1], corners[2], "wood")

        if kind != "none":
            wx = W * 0.675
            for x in (-wx, wx):
                window(x, 30, front)

        if s["lanterns"]:
            for x in (-DOOR_W - 9, DOOR_W + 5.5):
                m.box(x, x + 3.5, 24, 33, F, F + 3.5, {"front": "lamp", "left": "lamp", "right": "lamp", "top": "dark", "bottom": "dark"})
        if s["bushes"]:
            for x in (-DOOR_W - 16, DOOR_W + 16):
                m.box(x - 5, x + 5, 0, 7, F + 4, F + 14, {"front": "pot", "left": "pot", "right": "pot", "top": "dark"})
                self.dome(m, x, 6.5, F + 9, 7.5, 9, "rose", n=6, rings=2)

        # roof
        EX, OV_F, OV_B = self.EX, self.OV_F, self.OV_B
        zf, zb = F + OV_F, B - OV_B
        n = {"barrel": 8, "gable": 2, "flat": 1}[self.roof_style]
        xs = [-EX + 2 * EX * k / n for k in range(n + 1)]
        for k in range(n):
            x0, x1 = xs[k], xs[k + 1]
            if self.roof_style == "gable":
                nn = norm((-(roof_top(x1) - roof_top(x0)) / (x1 - x0), 1, 0))
                n0 = n1 = nn
            else:
                n0, n1 = self.roof_normal(x0), self.roof_normal(x1)
            s0, s1 = k / n, (k + 1) / n
            self.smooth_quad(m, [(x0, roof_top(x0), zf), (x1, roof_top(x1), zf), (x1, roof_top(x1), zb), (x0, roof_top(x0), zb)],
                             [n0, n1, n1, n0], [(s0, 1), (s1, 1), (s1, 0), (s0, 0)], "roof")
            m.quad((x0, roof_bottom(x0), zb), (x1, roof_bottom(x1), zb), (x1, roof_bottom(x1), zf), (x0, roof_bottom(x0), zf), "roof_under")
            q = [(x0, roof_bottom(x0), zf), (x1, roof_bottom(x1), zf), (x1, roof_top(x1) + 0.6, zf), (x0, roof_top(x0) + 0.6, zf)]
            m.quad(*q, "roof_edge", st=((s0, 0), (s1, 0), (s1, 1), (s0, 1)))
        for x, sgn in ((-EX, -1), (EX, 1)):
            q = [(x, roof_bottom(x), zf), (x, roof_bottom(x), zb), (x, roof_top(x) + 0.6, zb), (x, roof_top(x) + 0.6, zf)]
            if sgn < 0:
                q = [q[1], q[0], q[3], q[2]]
            m.quad(*q, "roof_edge")

        # sign and the front ornament
        sy = dy1 + 13
        m.box(-25, 25, sy, sy + 12, F, F + 3.5,
              {"front": "sign", "top": "wood", "bottom": "wood", "left": "wood", "right": "wood"})
        orn = s["ornament"]
        if orn != "none":
            hy = roof_top(0) - 1 if self.roof_style != "gable" else roof_top(0) + 2
            if orn == "star":
                rim = self.star_outline(0, hy + 6, 44)
                inner = self.star_outline(0, hy + 6.5, 36)
            else:
                rim = heart(0, hy, 36, n=14)
                inner = heart(0, hy + 0.5, 29, n=14)
            cy = sum(p[1] for p in rim) / len(rim)
            for i in range(len(rim)):
                (ax, ay), (bx, by) = rim[i], rim[(i + 1) % len(rim)]
                m.poly([(0, cy, zf + 2.5), (ax, ay, zf + 2.5), (bx, by, zf + 2.5)], [(0.5, 0.5)] * 3, "gold", normal=(0, 0, 1))
            m.extrude(inner, zf + 2.5, zf + 6.5, "heart", "heart_side")
        self.body, self.glow = body, (glow if two else None)
        body.weld()
        if two:
            glow.weld()
        return self


def build(style):
    return Exterior(style).build()
