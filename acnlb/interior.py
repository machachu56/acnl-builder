"""Interiors: a 16 x 16 tile room grid (32 units per tile) turned into the game's room model + collision grid.

The scene is plain JSON (see SCENE_DEFAULT). It replaces, while the player is inside the building, the room
model of Nook's Homes (/Bg/Indoor/Models/idr_realestate.bcres) and its collision block, which the runtime
plugin swaps in. Everything visible is one mesh on one 512 x 512 atlas; floors, walls and props reference
named *materials* that are painted procedurally (presets) or come from PNG assets drawn in the editor.

        x 0 1 2 3 4 5 6 7 8 9 A B C D E F
    y 0                                        rooms: any rectangles of floor; every tile that is not a floor
      ..                                       is a (low) partition wall. Doorways are floor tiles that join
      D                         D D            a room to the main room.
      E                         E E            D: the door (row 14), E: the exit (row 15)
"""
import math
import struct

from . import env, paintx, texfmt
from .paintx import Canvas, hex_rgb, rgba, shade

env.setup_path()
from modkit import cgfx, etc1, importer  # noqa: E402
from modkit.mesh import Atlas, Mesh, circle, heart  # noqa: E402
from modkit.paint import Packer, mix, paste, resize  # noqa: E402

ROOM = "/Bg/Indoor/Models/idr_realestate.bcres"
TILE = 32
GRID = 16
ATLAS_W = ATLAS_H = 512
FLOOR_PX = 16                       # atlas pixels per floor tile
SHAPE_OBJ_AFTER, SHAPE_OBJ2_AFTER, SHAPE_SHADOW_AFTER, SHAPE_OBJ_BEFORE = 0, 1, 2, 3
SHAPE_OBJ, SHAPE_SHADOW_BEFORE, SHAPE_SHADOW = 4, 5, 8
SHAPE_CARPET, SHAPE_WALL, SHAPE_WINDOW = 10, 11, 15

SCENE_DEFAULT = {
    "id": "interior", "title": "Interior", "wall_h": 112, "part_h": 40,
    "door": [[7, 14], [8, 14]], "exit": [[7, 15], [8, 15]], "main": "main",
    "materials": {}, "palettes": {}, "rooms": [], "items": [],
}


class SceneError(ValueError):
    pass


# =============================================================== material painters

def _gloss(c, level, rect=None):
    """alpha = the game's gloss/detail channel"""
    x0, y0, x1, y1 = rect or (0, 0, c.w, c.h)
    for y in range(y0, y1):
        for x in range(x0, x1):
            p = c.px[y][x]
            if p[3] > 0:
                lum = (p[0] * 3 + p[1] * 6 + p[2]) / 10
                p[3] = max(1, min(255, level + (lum - 160) * 0.2))


def leopard(c, r, base, spot, ring, seed=3):
    import random
    rnd = random.Random(seed)
    c.rect(r, base)
    x0, y0, x1, y1 = r
    for _ in range(max(1, (x1 - x0) * (y1 - y0) // 40)):
        x, y = rnd.uniform(x0, x1), rnd.uniform(y0, y1)
        rad = rnd.uniform(1.6, 3.0)
        c.circle(x, y, rad + 1.2, ring)
        c.circle(x + rnd.uniform(-0.6, 0.6), y + rnd.uniform(-0.6, 0.6), rad * 0.55, spot)


def _col(m, key, default):
    return hex_rgb((m.get("colors") or {}).get(key, default))


# every floor preset paints one 32 x 32 tile; every wall preset a 32 x 64 wall tile (top row = top of the wall,
# the bottom 40/112 is the wainscot that partitions show); props paint their whole region
FLOOR_PRESETS = {
    "plain": dict(c1="#c8d0d8"),
    "hearts": dict(c1="#c83860", c2="#ec7498", c3="#961e42"),
    "marble": dict(c1="#f6f2f0", c2="#e2dcde", c3="#e6be5a"),
    "flagstone": dict(c1="#28222a", c2="#463e42"),
    "checker": dict(c1="#ff3ca0", c2="#5ac8ff", c3="#ffdc46", c4="#a050ff", c5="#1e1428"),
    "tiles": dict(c1="#78d2dc", c2="#e6fafc"),
    "leopard": dict(c1="#d6a050", c2="#3c2414", c3="#78461e"),
    "shag": dict(c1="#7832aa"),
    "planks": dict(c1="#b98a5a", c2="#8a6038"),
    "carpet": dict(c1="#a83038", c2="#d86468"),
}
WALL_PRESETS = {
    "plain": dict(c1="#e8e0d4", c2="#a0a0b0"),
    "stripes_hearts": dict(c1="#fac4d6", c2="#f4b2ca", c3="#ec6896", c4="#b23e68"),
    "panel": dict(c1="#fffaee", c2="#e6be5a", c3="#ffffff"),
    "brick": dict(c1="#6e1a22", c2="#281014"),
    "night": dict(c1="#1e1032", c2="#ff3cb4", c3="#3c1e5a"),
    "tiles": dict(c1="#c8f0f0", c2="#96d2d6", c3="#64bec8"),
    "leopard": dict(c1="#e0b060", c2="#3c2414", c3="#82501f"),
    "tufted": dict(c1="#6e28a0", c2="#8c40c4", c3="#ff78dc"),
    "wood": dict(c1="#a07848", c2="#6e4e2c"),
}


def paint_floor_tile(c, preset, m, r):
    x0, y0, x1, y1 = r
    g = lambda k: _col(m, k, FLOOR_PRESETS.get(preset, FLOOR_PRESETS["plain"]).get(k, "#808080"))
    A = lambda col: tuple(col) + (255,)
    if preset == "hearts":
        c.rect(r, A(g("c1")))
        c.noise(r, 9, seed=23, scale=1)
        c.heart(x0 + 16, y0 + 16, 12, A(g("c2")))
        c.rect((x0, y0, x1, y0 + 1), A(g("c3")), 0.4)
        c.rect((x0, y0, x0 + 1, y1), A(g("c3")), 0.4)
    elif preset == "marble":
        c.rect(r, A(g("c1")))
        c.noise(r, 8, seed=31, scale=3)
        for k in range(5):
            c.polygon([(x0 + 2 + k * 6, y0), (x0 + 4 + k * 6, y0), (x0 + 30 - k * 3, y1), (x0 + 28 - k * 3, y1)], A(g("c2")))
        c.edge_shade(r, 18, 1)
        c.circle(x0, y0, 3, A(g("c3")))
    elif preset == "flagstone":
        c.rect(r, A(g("c1")))
        for (a, b, cc, d) in ((1, 1, 15, 15), (17, 1, 31, 15), (1, 17, 31, 31)):
            c.rrect((x0 + a, y0 + b, x0 + cc, y0 + d), 2, A(g("c2")))
        c.noise(r, 12, seed=32, scale=2)
    elif preset == "checker":
        cols = [g("c1"), g("c2"), g("c3"), g("c4")]
        for j in range(2):
            for i in range(2):
                col = cols[(i + 2 * j) % 4]
                c.rect((x0 + i * 16, y0 + j * 16, x0 + i * 16 + 16, y0 + j * 16 + 16), A(col))
                c.rect((x0 + i * 16 + 3, y0 + j * 16 + 3, x0 + i * 16 + 13, y0 + j * 16 + 13), A(tuple(min(255, v + 70) for v in col)))
        for k in range(0, 32, 16):
            c.rect((x0 + k, y0, x0 + k + 1, y1), A(g("c5")))
            c.rect((x0, y0 + k, x1, y0 + k + 1), A(g("c5")))
    elif preset == "tiles":
        c.rect(r, A(g("c1")))
        for k in range(0, 32, 8):
            c.rect((x0 + k, y0, x0 + k + 1, y1), A(g("c2")))
            c.rect((x0, y0 + k, x1, y0 + k + 1), A(g("c2")))
        c.noise(r, 6, seed=33, scale=2)
    elif preset == "leopard":
        leopard(c, r, A(g("c1")), A(g("c2")), A(g("c3")), seed=34)
    elif preset == "shag":
        c.rect(r, A(g("c1")))
        c.noise(r, 22, seed=35, scale=1)
        c.noise(r, 10, seed=36, scale=3)
    elif preset == "planks":
        c.rect(r, A(g("c1")))
        for k in range(0, 32, 8):
            c.rect((x0, y0 + k, x1, y0 + k + 1), A(g("c2")), 0.8)
            for j in range(2):
                c.rect((x0 + (k * 7 + j * 17) % 28, y0 + k, x0 + (k * 7 + j * 17) % 28 + 1, y0 + k + 8), A(g("c2")), 0.5)
        c.noise(r, 8, seed=37, scale=2)
    elif preset == "carpet":
        c.rect(r, A(g("c1")))
        c.noise(r, 8, seed=38, scale=1)
        c.rect((x0 + 2, y0 + 2, x1 - 2, y0 + 3), A(g("c2")), 0.7)
        c.rect((x0 + 2, y1 - 3, x1 - 2, y1 - 2), A(g("c2")), 0.7)
    else:
        c.rect(r, A(g("c1")))
        c.noise(r, 5, seed=39, scale=2)


def paint_wall_tile(c, preset, m, r):
    x0, y0, x1, y1 = r
    h = y1 - y0
    low = y0 + int(h * (1 - 40 / 112))
    g = lambda k: _col(m, k, WALL_PRESETS.get(preset, WALL_PRESETS["plain"]).get(k, "#808080"))
    A = lambda col: tuple(col) + (255,)
    base = g("c1")
    if preset == "stripes_hearts":
        for x in range(x0, x1):
            c.rect((x, y0, x + 1, low), A(g("c1")) if (x - x0) // 4 % 2 == 0 else A(g("c2")))
        c.heart(x0 + 8, y0 + 12, 6, A(g("c3")))
        c.heart(x0 + 24, y0 + 28, 6, A(g("c3")))
        c.rect((x0, low - 2, x1, low), (255, 238, 228, 255))
        c.vgrad((x0, low, x1, y1), A(g("c4")), A(shade(g("c4"), 0.85)))
        c.rrect((x0 + 3, low + 4, x1 - 3, y1 - 4), 2, A(shade(g("c4"), 1.2)))
    elif preset == "panel":
        c.vgrad((x0, y0, x1, low), A(g("c1")), A(shade(g("c1"), 0.96)))
        c.circle(x0 + 16, y0 + 18, 7, A(shade(g("c1"), 0.92)))
        c.heart(x0 + 16, y0 + 18, 8, A(g("c3")))
        c.rect((x0, low - 2, x1, low), A(g("c2")))
        c.vgrad((x0, low, x1, y1), A(g("c3")), A(shade(g("c3"), 0.9)))
        c.rrect((x0 + 3, low + 4, x1 - 3, y1 - 4), 2, A(shade(g("c3"), 0.97)))
    elif preset == "brick":
        c.rect(r, A(shade(g("c1"), 0.5)))
        for row, y in enumerate(range(y0, y1, 6)):
            for x in range(x0 - (row % 2) * 8, x1, 16):
                c.rect((max(x0, x + 1), y + 1, min(x1, x + 15), min(y1, y + 5)), A(g("c1")))
        c.noise(r, 10, seed=41, scale=2)
    elif preset == "night":
        c.rect(r, A(g("c1")))
        for k in range(10):
            c.circle(x0 + (k * 13) % 32, y0 + (k * 23) % max(1, low - y0), 1, (255, 240, 255, 255))
        c.rect((x0, low - 3, x1, low), A(g("c2")))
        c.vgrad((x0, low, x1, y1), A(g("c3")), A(g("c1")))
    elif preset == "tiles":
        c.rect(r, A(g("c1")))
        for k in range(0, h, 8):
            c.rect((x0, y0 + k, x1, y0 + k + 1), A(g("c2")))
        for k in range(0, 32, 8):
            c.rect((x0 + k, y0, x0 + k + 1, y1), A(g("c2")))
        c.rect((x0, low, x1, y1), A(g("c3")), 0.6)
    elif preset == "leopard":
        leopard(c, (x0, y0, x1, low), A(g("c1")), A(g("c2")), A(g("c3")), seed=42)
        c.vgrad((x0, low, x1, y1), A(shade(g("c2"), 0.9)), A(shade(g("c2"), 0.55)))
        c.rect((x0, low, x1, low + 2), (230, 190, 90, 255))
    elif preset == "tufted":
        c.rect(r, A(g("c1")))
        for j in range(0, h, 10):
            for i in range(0, 32, 10):
                c.circle(x0 + i + 5 + (j // 10 % 2) * 5, y0 + j + 5, 3.5, A(g("c2")))
                c.circle(x0 + i + 5 + (j // 10 % 2) * 5, y0 + j + 5, 1, A(shade(g("c1"), 0.5)))
        c.rect((x0, low - 2, x1, low), A(g("c3")))
    elif preset == "wood":
        c.rect(r, A(base))
        for x in range(x0, x1, 8):
            c.rect((x, y0, x + 1, y1), A(g("c2")), 0.7)
        c.noise(r, 6, seed=43, scale=2)
        c.rect((x0, low - 2, x1, low), A(shade(base, 0.7)))
    else:   # plain: wallpaper over a wainscot
        c.vgrad((x0, y0, x1, low), A(base), A(shade(base, 0.95)))
        c.rect((x0, low - 2, x1, low), A(shade(base, 1.2)))
        c.vgrad((x0, low, x1, y1), A(g("c2")), A(shade(g("c2"), 0.85)))


def paint_prop(c, m, r):
    """a free-form material: gradient / wood / fabric / leopard / shag / tiles / text / solid"""
    x0, y0, x1, y1 = r
    preset = m.get("preset", "solid")
    g = lambda k, d: hex_rgb((m.get("colors") or {}).get(k, d))
    A = lambda col: tuple(col) + (255,)
    c1, c2, c3 = g("c1", "#c8c8d0"), g("c2", "#808090"), g("c3", "#ffffff")
    if preset == "gradient":
        c.vgrad(r, A(c1), A(c2))
    elif preset == "wood":
        c.vgrad(r, A(c1), A(c2))
        for y in range(y0 + 3, y1, 5):
            c.rect((x0, y, x1, y + 1), A(shade(c2, 0.7)), 0.5)
    elif preset == "fabric":
        c.vgrad(r, A(c1), A(c2))
        for k in range(y0 + 4, y1, 6):
            c.rect((x0, k, x1, k + 1), A(c2), 0.6)
    elif preset == "stripes":
        for k, x in enumerate(range(x0, x1, 4)):
            c.rect((x, y0, min(x1, x + 4), y1), A(c1 if k % 2 == 0 else c2))
    elif preset == "leopard":
        leopard(c, r, A(c1), A(c2), A(c3), seed=8)
    elif preset == "shag":
        c.rect(r, A(c1))
        c.noise(r, 22, seed=51, scale=1)
    elif preset == "tiles":
        c.rect(r, A(c1))
        for k in range(0, x1 - x0, 8):
            c.rect((x0 + k, y0, x0 + k + 1, y1), A(c2))
        for k in range(0, y1 - y0, 8):
            c.rect((x0, y0 + k, x1, y0 + k + 1), A(c2))
    elif preset == "hearts":
        c.rect(r, A(c1))
        for j in range(y0 + 8, y1, 16):
            for i in range(x0 + 8, x1, 16):
                c.heart(i, j, 10, A(c2))
    elif preset == "sign":
        c.rrect(r, 3, (230, 190, 90, 255))
        c.rrect((x0 + 1, y0 + 1, x1 - 1, y1 - 1), 2, A(c2))
        c.text(m.get("text", ""), (x0 + 2, y0 + 1, x1 - 2, y1 - 1), A(c1), size=m.get("size", 11), outline=A(c3), outline_w=1.2)
    elif preset == "text":
        c.rect(r, A(c2))
        c.text(m.get("text", ""), (x0 + 2, y0 + 1, x1 - 2, y1 - 1), A(c1), size=m.get("size", 11), outline=A(c3), outline_w=1.2)
    else:
        c.rect(r, A(c1))
    if m.get("noise"):
        c.noise(r, m["noise"], seed=5, scale=1)


# ---------------------------------------------------------------- bed palettes (the "love hotel" bed set)

BED_PARTS = {"frame": (64, 16), "sheet": (64, 32), "head": (48, 48), "stand": (32, 32), "pillow": (32, 16)}
BED_DEFAULT = dict(wood="#2c1e22", wood_dark="#140e10", accent="#be1028", accent_light="#fa465a", sheet="#281a1a", sheet_dark="#140a0e")


def paint_bed_part(c, part, pal, r):
    wood, dark, acc, light = (hex_rgb(pal[k]) + (255,) for k in ("wood", "wood_dark", "accent", "accent_light"))
    sheet = hex_rgb(pal["sheet"]) + (255,) if pal.get("sheet") else None
    sheet_d = hex_rgb(pal.get("sheet_dark") or pal["wood"]) + (255,)
    x0, y0, x1, y1 = r
    if part == "frame":
        c.vgrad(r, wood, dark)
        c.rect((x0, y0, x1, y0 + 2), light)
        for k in range(4):
            c.heart(x0 + 8 + k * 16, y0 + 9, 8, acc)
    elif part == "sheet":
        if sheet:
            c.vgrad(r, sheet, sheet_d)
            for k in range(4):
                c.rect((x0, y0 + 4 + k * 6, x1, y0 + 5 + k * 6), sheet_d, 0.6)
        else:
            leopard(c, r, (230, 180, 100, 255), (60, 36, 20, 255), (120, 70, 30, 255), seed=8)
        c.rect((x0, y1 - 8, x1, y1), acc)
        c.heart((x0 + x1) / 2, y1 - 4, 7, light)
    elif part == "head":
        c.rect(r, dark)
        c.heart((x0 + x1) / 2, (y0 + y1) / 2 + 2, 46, acc)
        c.heart((x0 + x1) / 2, (y0 + y1) / 2 + 2, 40, tuple(int(v * 0.85) for v in acc[:3]) + (255,))
        for j in range(4):
            for i in range(4):
                c.circle(x0 + 9 + i * 10 + (j % 2) * 4, y0 + 11 + j * 8, 1.3, dark)
        c.circle(x0 + 14, y0 + 14, 4, light)
    elif part == "stand":
        c.vgrad(r, wood, dark)
        c.rrect((x0 + 3, y0 + 3, x1 - 3, y0 + 14), 2, dark)
        c.rrect((x0 + 3, y0 + 17, x1 - 3, y1 - 3), 2, dark)
        c.heart((x0 + x1) / 2, y0 + 9, 7, acc)
        c.heart((x0 + x1) / 2, y0 + 23, 7, acc)
    elif part == "pillow":
        c.rrect(r, 4, light)
        c.heart((x0 + x1) / 2, (y0 + y1) / 2, 8, acc)


# =============================================================== the plan (tiles, collision)

class Plan:
    def __init__(self, spec):
        self.spec = spec
        self.owner = {}                # floor tile -> room id
        self.solid = set()
        self.doorway = {}              # tile -> room it leads to
        self.door = [tuple(t) for t in spec["door"]]
        self.exit = [tuple(t) for t in spec["exit"]]
        main = spec["main"]
        for r in spec["rooms"]:
            x0, y0, x1, y1 = r["rect"]
            for y in range(y0, y1 + 1):
                for x in range(x0, x1 + 1):
                    if not (0 <= x < GRID and 0 <= y < GRID):
                        raise SceneError("room %s leaves the 16 x 16 grid" % r["id"])
                    if (x, y) in self.owner:
                        raise SceneError("rooms %s and %s overlap at tile %d,%d" % (self.owner[(x, y)], r["id"], x, y))
                    self.owner[(x, y)] = r["id"]
        for r in spec["rooms"]:
            for t in r.get("doors", []):
                t = tuple(t)
                if t in self.owner and self.owner[t] != main:
                    raise SceneError("doorway %s of %s is inside room %s" % (t, r["id"], self.owner[t]))
                self.owner[t] = main
                self.doorway[t] = r["id"]
        for t in self.door:
            self.owner[t] = main

    def floor(self, t):
        return t in self.owner

    def wall(self, t):
        return not self.floor(t) and t not in self.exit

    def block(self, tiles):
        for t in tiles:
            t = tuple(t)
            if self.floor(t):
                self.solid.add(t)

    def problems(self):
        out = []
        free = {t for t in self.owner if t not in self.solid}
        for t in list(self.doorway) + self.door:
            if t not in free:
                out.append("a doorway or the entrance (tile %d,%d) is blocked by furniture" % t)
        if self.door and self.door[0] in free:
            seen, todo = {self.door[0]}, [self.door[0]]
            while todo:
                x, y = todo.pop()
                for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if n in free and n not in seen:
                        seen.add(n)
                        todo.append(n)
            for r in self.spec["rooms"]:
                tiles = [t for t, o in self.owner.items() if o == r["id"] and t in free]
                if tiles and not any(t in seen for t in tiles):
                    out.append("room %s cannot be reached from the entrance" % r["id"])
        return out

    def jmp(self):
        """the 0xA00-byte collision block: 16 x 16 tiles of 5 u16 (4 packed corner heights, attribute)"""
        out = bytearray()
        for y in range(GRID):
            for x in range(GRID):
                t = (x, y)
                if t in self.exit:
                    words = (0, 0, 0, 0, 0x4007)
                elif t in self.door:
                    words = (0, 0, 0, 0, 0x402B)
                elif not self.floor(t) or t in self.solid:
                    words = (0x6318, 0x6318, 0x6318, 0x6318, 0x400F)
                else:
                    near = any(not self.floor(n) or n in self.solid for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
                    words = (0, 0, 0, 0, 0x4012 if near else 0xC012)
                out += struct.pack("<5H", *words)
        return bytes(out)


# =============================================================== the builder

MODEL_CAP = 64


def color_texture_names(texs):
    return [t for t in texs if not any(k in t.lower() for k in ("mask", "_mr", "mr_", "lut", "_gl"))] or texs[:1]


class Builder:
    """paints the atlas and builds the mesh of a scene; `read` reads game files (models of `game` items)"""

    def __init__(self, spec, read, assets=None):
        s = dict(SCENE_DEFAULT)
        s.update(spec)
        s["materials"] = dict(s.get("materials") or {})
        self.spec = s
        self.read = read
        self.assets = assets or (lambda name: None)       # asset name -> rows
        self.plan = Plan(s)
        self.wall_h, self.part_h = float(s["wall_h"]), float(s["part_h"])
        self.notes = []
        self._models = {}
        self._collect()

    # ---- what the atlas must hold
    def mat(self, name):
        m = self.spec["materials"].get(name)
        if m is None:
            raise SceneError("unknown material %r" % name)
        return m

    def _collect(self):
        sizes = {}
        self.jobs = []                          # (region, painter callable(canvas, rect))
        S = self.spec
        for name, m in S["materials"].items():
            t = m.get("type", "prop")
            if t == "wall":
                sizes["m:" + name] = (32, 64)
            elif t == "floor":
                sizes["m:" + name] = (32, 32)
            else:
                sizes["m:" + name] = tuple(m.get("size") or (16, 16))
        for r in S["rooms"]:
            if r.get("floor"):
                x0, y0, x1, y1 = r["rect"]
                sizes["floor:" + r["id"]] = ((x1 - x0 + 1) * FLOOR_PX, (y1 - y0 + 1) * FLOOR_PX)
            if r.get("label"):
                sizes["sign:" + r["id"]] = (64, 16)
        sizes["trim"] = (16, 16)
        sizes["lip"] = (16, 16)
        sizes["_mirror"] = (16, 16)
        for pname in S["palettes"]:
            for part, size in BED_PARTS.items():
                sizes["bed:%s:%s" % (pname, part)] = size
        for it in S["items"]:
            if it["type"] in ("bed", "stand") and it.get("palette") not in S["palettes"]:
                raise SceneError("item %s uses the unknown palette %r" % (it.get("id", "?"), it.get("palette")))
            if it["type"] == "game":
                self._game_sizes(it, sizes)
        self.sizes = sizes
        self.pack = Packer(ATLAS_W, ATLAS_H)
        try:
            self.R = {}
            for name, (w, h) in sorted(sizes.items(), key=lambda kv: (-kv[1][1], -kv[1][0])):
                self.R[name] = self.pack.add(name, w, h)
        except ValueError as e:
            raise SceneError("the texture atlas is full (%s): use fewer or smaller materials/models" % e)

    def _model(self, path):
        if path not in self._models:
            d = self.read(path)
            tex = {t.name: etc1.decode(d[t.data_off:], t.w, t.h, t.fmt == 13) for t in cgfx.textures(d) if t.fmt in (12, 13)}
            self._models[path] = (d, tex)
        return self._models[path]

    def _game_sizes(self, it, sizes):
        d, tex = self._model(it["path"])
        cap = int(it.get("tex_cap", MODEL_CAP))
        for shp, mat, texs in cgfx.meshes(d):
            for tn in color_texture_names(texs)[:1]:
                if tn in tex:
                    h, w = len(tex[tn]), len(tex[tn][0])
                    c = cap // 4 if tn.startswith("fabric") else cap       # the cloth parts need less detail
                    while max(w, h) > c:
                        w, h = max(1, w // 2), max(1, h // 2)
                    sizes[self._game_region(it, tn)] = (w, h)

    @staticmethod
    def _game_region(it, tn):
        rc = it.get("recolor")
        return "g:%s:%s:%s" % (it["path"], tn, "" if not rc else "%s/%s/%s" % (rc.get("h", 0), rc.get("s", 1), rc.get("v", 1)))

    def _mat_rows(self, m):
        """pixels of an image material: a project PNG or a texture read from the player's own game dump"""
        if m.get("image"):
            return self.assets(m["image"])
        g = m.get("game_texture")
        if g:
            d = self.read(g["path"])
            for t in cgfx.textures(d):
                if t.name == g["name"]:
                    return texfmt.decode_texture(d, t)
            raise SceneError("%s has no texture %r" % (g["path"], g["name"]))
        return None

    # ---- painting
    def paint(self):
        c = Canvas(ATLAS_W, ATLAS_H, (255, 255, 255, 255))
        R = self.R
        c.vgrad(R["trim"], (255, 248, 240, 255), (232, 220, 214, 255))
        c.rect(R["lip"], (90, 40, 60, 255))
        c.vgrad(R["_mirror"], (220, 240, 255, 255), (150, 170, 200, 255))
        for name, m in self.spec["materials"].items():
            r = R["m:" + name]
            t = m.get("type", "prop")
            rows = self._mat_rows(m)
            if rows is not None:
                paste(c, rows, r)
            elif t == "floor":
                paint_floor_tile(c, m.get("preset", "plain"), m, r)
            elif t == "wall":
                paint_wall_tile(c, m.get("preset", "plain"), m, r)
            else:
                paint_prop(c, m, r)
        for r in self.spec["rooms"]:
            if r.get("floor"):
                m = self.mat(r["floor"])
                reg = R["floor:" + r["id"]]
                rows = self._mat_rows(m)
                tmp = Canvas(32, 32)
                if rows is not None:
                    paste(tmp, rows, (0, 0, 32, 32))
                else:
                    paint_floor_tile(tmp, m.get("preset", "plain"), m, (0, 0, 32, 32))
                tile = resize(tmp.rows(), FLOOR_PX, FLOOR_PX)
                x0, y0, x1, y1 = reg
                for y in range(y0, y1):
                    for x in range(x0, x1):
                        c.px[y][x] = list(tile[(y - y0) % FLOOR_PX][(x - x0) % FLOOR_PX])
            if r.get("label"):
                lc = r.get("label_colors") or {}
                paint_prop(c, dict(preset="sign", text=r["label"], size=11,
                                   colors={"c1": lc.get("fg", "#ffeef4"), "c2": lc.get("bg", "#784632"), "c3": lc.get("outline", "#78143c")}),
                           R["sign:" + r["id"]])
        for pname, pal0 in self.spec["palettes"].items():
            pal = dict(BED_DEFAULT)
            pal.update(pal0)
            for part in BED_PARTS:
                paint_bed_part(c, part, pal, R["bed:%s:%s" % (pname, part)])
        for it in self.spec["items"]:
            if it["type"] == "game":
                for region, rows in self._game_rows(it).items():
                    paste(c, rows, R[region])
        _gloss(c, 100)
        self.canvas = c
        return c

    def _game_rows(self, it):
        from modkit.paint import hsv, rgb, recolor
        d, tex = self._model(it["path"])
        out = {}
        for shp, mat, texs in cgfx.meshes(d):
            for tn in color_texture_names(texs)[:1]:
                if tn in tex:
                    rows = tex[tn]
                    rc = it.get("recolor")
                    if rc:
                        dh, ms, mv = rc.get("h", 0) / 360.0, rc.get("s", 1), rc.get("v", 1)

                        def fn(r, g, b, a, dh=dh, ms=ms, mv=mv):
                            h, s, v = hsv(r, g, b)
                            r2, g2, b2 = rgb(h + dh, s * ms, v * mv)
                            return (r2, g2, b2, a)
                        rows = recolor(rows, fn)
                    out[self._game_region(it, tn)] = rows
        return out

    # ---- mesh helpers
    def reg(self, mat):
        """atlas region of a material name or an internal region"""
        if mat in self.R:
            return mat
        if "m:" + mat in self.R:
            return "m:" + mat
        raise SceneError("unknown material %r" % mat)

    def cyl(self, cx, cz, r, y0, y1, side, top, n=12):
        m = self.mesh
        pts = circle(cx, cz, r, n)
        for i in range(n):
            (ax, az), (bx, bz) = pts[i], pts[(i + 1) % n]
            m.quad((bx, y0, bz), (ax, y0, az), (ax, y1, az), (bx, y1, bz), side,
                   st=((i / n, 0), ((i + 1) / n, 0), ((i + 1) / n, 1), (i / n, 1)))
        if top:
            m.poly([(x, y1, z) for x, z in pts[::-1]], [((x - cx + r) / (2 * r), (cz + r - z) / (2 * r)) for x, z in pts[::-1]], top)

    def flat(self, x0, z0, x1, z1, region, y=0.4):
        self.mesh.quad((x0, y, z1), (x1, y, z1), (x1, y, z0), (x0, y, z0), region, normal=(0, 1, 0))

    def wall_quad(self, a, b, h, region, t1=1.0):
        self.mesh.quad((a[0], 0, a[1]), (b[0], 0, b[1]), (b[0], h, b[1]), (a[0], h, a[1]), region, st=((0, 0), (1, 0), (1, t1), (0, t1)))

    def lamp(self, at, shade_region):
        x, z = at
        gold = self.reg_any("trim")
        self.cyl(x, z, 6, 0, 2, gold, gold, n=8)
        self.cyl(x, z, 1.5, 2, 30, gold, None, n=6)
        m, n = self.mesh, 10
        lo, hi = circle(x, z, 12, n), circle(x, z, 7, n)
        for i in range(n):
            a, b, c_, d = lo[i], lo[(i + 1) % n], hi[(i + 1) % n], hi[i]
            m.quad((b[0], 28, b[1]), (a[0], 28, a[1]), (d[0], 44, d[1]), (c_[0], 44, c_[1]), shade_region,
                   st=((i / n, 0), ((i + 1) / n, 0), ((i + 1) / n, 1), (i / n, 1)))
        m.poly([(px, 44, pz) for px, pz in hi[::-1]], [(0.5, 0.5)] * n, shade_region)

    def reg_any(self, name):
        return self.reg(name)

    # ---- the shell: floors, outer walls, partitions, lintels
    def shell(self):
        plan, m, T = self.plan, self.mesh, TILE
        WALL_H, PART_H = self.wall_h, self.part_h
        main = self.spec["main"]
        rooms = {r["id"]: r for r in self.spec["rooms"]}

        def wall_region(room_id):
            r = rooms.get(room_id)
            return "m:" + r["wall"] if r and r.get("wall") else "trim"

        for r in self.spec["rooms"]:
            if not r.get("floor"):
                continue
            x0, y0, x1, y1 = r["rect"]
            m.quad((x0 * T, 0, (y1 + 1) * T), ((x1 + 1) * T, 0, (y1 + 1) * T), ((x1 + 1) * T, 0, y0 * T), (x0 * T, 0, y0 * T),
                   "floor:" + r["id"], normal=(0, 1, 0))
        mainroom = rooms.get(main)
        door_floor = "m:" + mainroom["floor"] if mainroom and mainroom.get("floor") else "trim"
        for (x, y) in plan.doorway:
            m.quad((x * T, 0, (y + 1) * T), ((x + 1) * T, 0, (y + 1) * T), ((x + 1) * T, 0, y * T), (x * T, 0, y * T),
                   door_floor, normal=(0, 1, 0))
        for x in range(GRID):
            room = plan.owner.get((x, 0))
            if room:
                self.wall_quad(((x + 1) * T, 0), (x * T, 0), WALL_H, wall_region(room))
        for y in range(GRID - 2):
            for x, a, b in ((0, (0, y * T), (0, (y + 1) * T)), (GRID - 1, (GRID * T, (y + 1) * T), (GRID * T, y * T))):
                room = plan.owner.get((x, y))
                if room:
                    self.wall_quad(a, b, WALL_H, wall_region(room))
        tpart = PART_H / WALL_H
        for y in range(GRID - 2):
            for x in range(GRID):
                if not plan.wall((x, y)):
                    continue
                faces = []
                x0, x1, z0, z1 = x * T, (x + 1) * T, y * T, (y + 1) * T
                for (nx, ny), a, b in (((x, y + 1), (x0, z1), (x1, z1)), ((x, y - 1), (x1, z0), (x0, z0)),
                                       ((x - 1, y), (x0, z0), (x0, z1)), ((x + 1, y), (x1, z1), (x1, z0))):
                    room = plan.owner.get((nx, ny))
                    if room and (nx, ny) != (x, GRID - 2):
                        faces.append(room)
                        self.wall_quad(a, b, PART_H, wall_region(room), tpart)
                if faces:
                    m.quad((x0, PART_H, z1), (x1, PART_H, z1), (x1, PART_H, z0), (x0, PART_H, z0), "trim", normal=(0, 1, 0))
        for r in self.spec["rooms"]:
            doors = r.get("doors")
            if not doors or not r.get("label"):
                continue
            xs = [d[0] for d in doors]
            ys = [d[1] for d in doors]
            x0, x1, z0, z1 = min(xs) * T, (max(xs) + 1) * T, min(ys) * T, (max(ys) + 1) * T
            y0, y1 = PART_H, PART_H + 16
            sign = "sign:" + r["id"]
            if len(set(ys)) == 1:
                m.box(x0, x1, y0, y1, z0 + 10, z1 - 10, {"front": sign, "back": "trim", "top": "trim", "bottom": "trim", "left": "trim", "right": "trim"})
            else:
                side = "right" if x0 < GRID * T / 2 else "left"
                faces = {k: "trim" for k in ("front", "back", "top", "bottom", "left", "right")}
                m.box(x0 + 10, x1 - 10, y0, y1, z0, z1, {k: v for k, v in faces.items() if k != side})
                if side == "right":
                    m.quad((x1 - 10, y0, z1), (x1 - 10, y0, z0), (x1 - 10, y1, z0), (x1 - 10, y1, z1), sign)
                else:
                    m.quad((x0 + 10, y0, z0), (x0 + 10, y0, z1), (x0 + 10, y1, z1), (x0 + 10, y1, z0), sign)
        dxs = sorted(t[0] for t in plan.door)
        gap0, gap1 = (dxs[0] * T, (dxs[-1] + 1) * T) if dxs else (0, 0)
        for x0, x1 in ((0, gap0), (gap1, GRID * T)):
            if x1 > x0:
                m.quad((x0, -16, 448), (x1, -16, 448), (x1, 0, 448), (x0, 0, 448), "lip")

    # ---- items
    def _tiles_world(self, tile):
        return ((tile[0] + 0.5) * TILE, (tile[1] + 0.5) * TILE)

    def add_item(self, it):
        t, m = it["type"], self.mesh
        R = self.reg
        if t == "box":
            faces = {}
            for f in ("front", "back", "left", "right", "top", "bottom"):
                mat = (it.get("faces") or {}).get(f) or it.get("mat")
                if mat and not (f == "bottom" and not (it.get("faces") or {}).get("bottom")):
                    faces[f] = R(mat)
            m.box(it["x0"], it["x1"], it["y0"], it["y1"], it["z0"], it["z1"], faces)
        elif t == "cyl":
            self.cyl(it["cx"], it["cz"], it["r"], it["y0"], it["y1"], R(it["side"]) if it.get("side") else R(it["mat"]),
                     R(it["top"]) if it.get("top") else None, n=int(it.get("n", 12)))
        elif t == "flat":
            self.flat(it["x0"], it["z0"], it["x1"], it["z1"], R(it["mat"]), y=it.get("y", 0.4))
        elif t == "quad":
            st = it.get("st") or ((0, 0), (1, 0), (1, 1), (0, 1))
            m.quad(*[tuple(p) for p in it["pts"]], R(it["mat"]), st=st)
        elif t == "wallquad":
            for a, b in ((it["a"], it["b"]),) + (((it["b"], it["a"]),) if it.get("both") else ()):
                self.wall_quad(a, b, it["h"], R(it["mat"]), it.get("t1", 1.0))
        elif t == "lamp":
            self.lamp((it["x"], it["z"]), R(it["shade"]))
        elif t == "extrude":
            self.extrude(it)
        elif t == "bed":
            self.bed(it)
        elif t == "stand":
            self.stand(it)
        elif t == "game":
            self.game(it)
        else:
            raise SceneError("unknown item type %r" % t)
        if it.get("block"):
            self.plan.block(it["block"])

    def outline_pts(self, it):
        kind = it.get("shape", "heart")
        s = it.get("size", 60)
        if kind == "heart":
            return [(it["cx"] + x, it["cz"] - y) for x, y in heart(0, 0, s, n=24)]
        if kind == "circle":
            return circle(it["cx"], it["cz"], s / 2, 20)
        if kind == "oval":
            return [(it["cx"] + s / 2 * math.cos(a), it["cz"] + s / 4 * math.sin(a)) for a in (2 * math.pi * i / 16 for i in range(16))]
        raise SceneError("unknown shape %r" % kind)

    def extrude(self, it):
        """an upright tub/pool/pedestal on a heart/circle/oval outline: side wall + a top face"""
        m = self.mesh
        pts = self.outline_pts(it)
        y0, y1 = it.get("y0", 0), it["y1"]
        side, top = self.reg(it["side"]), self.reg(it["top"])
        cx, cz = it["cx"], it["cz"]
        sz = it.get("size", 60)
        for i in range(len(pts)):
            (ax, az), (bx, bz) = pts[i], pts[(i + 1) % len(pts)]
            m.quad((bx, y0, bz), (ax, y0, az), (ax, y1, az), (bx, y1, bz), side)
        top_pts = pts[::-1] if it.get("shape") != "heart" else pts
        m.poly([(x, it.get("top_y", y1), z) for x, z in top_pts],
               [((x - cx + sz / 2) / sz, (cz + sz / 2 - z) / sz) for x, z in top_pts], top, normal=(0, 1, 0))

    def bed(self, it):
        fr, sh, hd, pl = ("bed:%s:%s" % (it["palette"], p) for p in ("frame", "sheet", "head", "pillow"))
        part = Mesh(self.atlas)
        part.box(-28, 28, 0, 10, -26, 28, {"front": fr, "left": fr, "right": fr})
        part.box(-26, 26, 10, 17, -24, 26, {"front": sh, "left": sh, "right": sh, "top": sh})
        for x in (-22, 2):
            part.box(x, x + 20, 17, 21, -22, -12, {"front": pl, "top": pl, "left": pl, "right": pl})
        part.extrude(heart(0, 32, 58, n=20), -31, -25, hd, fr)
        rot = it.get("rot", 0)
        for v in part.verts:
            p = importer.rotate_y(v["pos"], rot)
            v["pos"] = (p[0] + it["x"], p[1], p[2] + it["z"])
            v["normal"] = importer.rotate_y(v["normal"], rot)
        self.mesh.merge(part)

    def stand(self, it):
        st, fr = "bed:%s:stand" % it["palette"], "bed:%s:frame" % it["palette"]
        x, z = it["x"], it["z"]
        self.mesh.box(x - 13, x + 13, 0, 24, z - 13, z + 13, {"front": st, "left": st, "right": st, "back": st, "top": fr})

    def game(self, it):
        d, tex = self._model(it["path"])
        for shp, mat, texs in cgfx.meshes(d):
            cols = color_texture_names(texs)
            tn = cols[0] if cols else None
            region = self._game_region(it, tn) if tn in tex else "_mirror"
            if texs and any(k in texs[0].lower() for k in ("mr", "gl")) and tn not in tex:
                region = "_mirror"
            if region not in self.atlas.regions:
                region = "_mirror"
            verts, tris = cgfx.read_geometry(d, shp)
            importer.add_model(self.mesh, verts, tris, region, at=(it["x"], it.get("y", 0), it["z"]), rot=it.get("rot", 0),
                               scale=it.get("scale", 1.0))

    # ---- all together
    def build(self):
        self.paint()
        self.atlas = Atlas(ATLAS_W, ATLAS_H, self.pack.regions)
        self.mesh = Mesh(self.atlas)
        self.shell()
        for it in self.spec["items"]:
            try:
                self.add_item(it)
            except SceneError:
                raise
            except KeyError as e:
                raise SceneError("item %s (%s): missing field %s" % (it.get("id", "?"), it["type"], e))
        problems = self.plan.problems()
        if problems:
            raise SceneError("; ".join(problems))
        self.mesh.weld()
        return self


def build_scene(spec, read, assets=None):
    return Builder(spec, read, assets).build()


# =============================================================== the room model file

def room_files(data, b):
    """(new idr_realestate.bcres bytes, collision block) from the original model and a built scene"""
    mesh = b.mesh
    geometry = {SHAPE_OBJ: (mesh.verts, mesh.tris)}
    for s in (SHAPE_OBJ_AFTER, SHAPE_OBJ2_AFTER, SHAPE_SHADOW_AFTER, SHAPE_OBJ_BEFORE, SHAPE_SHADOW_BEFORE,
              SHAPE_SHADOW, SHAPE_CARPET, SHAPE_WALL, SHAPE_WINDOW, 9, 13, 14):
        geometry[s] = cgfx.EMPTY
    geometry[(1, 0)] = cgfx.EMPTY
    textures = {"obj": (ATLAS_W, ATLAS_H, 1, texfmt.encode_cached(b.canvas.rows(), 12), 12)}
    for t in cgfx.textures(data):
        if t.name not in ("obj", "mat") and t.fmt in (12, 13):
            textures[t.name] = (8, 8, 1, etc1.encode([[(255, 255, 255, 255)] * 8] * 8, t.fmt == 13))
    return cgfx.rebuild(data, geometry, textures), b.plan.jmp()
