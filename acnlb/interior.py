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

from . import env, models, paintx, texfmt
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
    # ways to other rooms of the same building: {"id", "tiles": [[x, y]...], "to": scene id, "arrive": [x, y], "face": 0|90|180|270}
    "links": [],
    # the entrance: which edge of the 16 x 16 plan the door is on ("south", "east", "west", "north") and where along it
    # (the first of the two door tiles); without "entrance" the "door" / "exit" tiles above are used as they are
}

ENTRANCES = ("south", "east", "west", "north")
YAW = {"south": 0, "east": 16384, "north": 32768, "west": 49152}        # the direction the player looks at
SIGN_MAX_W = 256                                                        # pixels; a sign is 1 (or 2) pixels per unit
SIGN_DEFAULTS = {"fg": "#ffeef4", "bg": "#784632", "outline": "#78143c", "frame": "#e6be5a"}


def entrance_layout(spec):
    """the entrance of a scene: {"door": tiles (the walkable doorway), "exit": tiles (leaving the room), "bounds":
    (x0, y0, x1, y1) of the playable area, "spawn": (x, z, yaw) where the player appears, or None for the game's own
    (south) arrival}. The door tiles lie in a strip along one edge, the exit tiles behind them, like the original
    room's south door in rows 14 and 15."""
    side = spec.get("entrance") or "south"
    if side not in ENTRANCES:
        raise SceneError("the entrance must be south, east, west or north (not %r)" % side)
    p = spec.get("entrance_at")
    if side == "south" and p is None:
        door, exit_ = spec.get("door") or [[7, 14], [8, 14]], spec.get("exit") or [[7, 15], [8, 15]]
        return {"side": side, "door": [tuple(t) for t in door], "exit": [tuple(t) for t in exit_], "bounds": (0, 0, GRID - 1, 13), "spawn": None}
    p = 7 if p is None else max(0, min(int(p), GRID - 2 if side in ("south", "north") else GRID - 4))   # the door is two tiles wide
    if side == "south":
        return {"side": side, "door": [(p, 14), (p + 1, 14)], "exit": [(p, 15), (p + 1, 15)], "bounds": (0, 0, GRID - 1, 13), "spawn": None}
    if side == "north":
        return {"side": side, "door": [(p, 1), (p + 1, 1)], "exit": [(p, 0), (p + 1, 0)], "bounds": (0, 2, GRID - 1, 13),
                "spawn": ((p + 1) * TILE, 1.5 * TILE, YAW["south"])}
    if side == "east":
        return {"side": side, "door": [(14, p), (14, p + 1)], "exit": [(15, p), (15, p + 1)], "bounds": (0, 0, 13, 13),
                "spawn": (14.5 * TILE, (p + 1) * TILE, YAW["west"])}
    return {"side": side, "door": [(1, p), (1, p + 1)], "exit": [(0, p), (0, p + 1)], "bounds": (2, 0, GRID - 1, 13),
            "spawn": (1.5 * TILE, (p + 1) * TILE, YAW["east"])}


def door_groups(tiles):
    """doorway tiles -> lists of tiles that touch each other (a sign goes over each group)"""
    left, out = {tuple(t) for t in tiles}, []
    while left:
        todo = [min(left)]
        grp = []
        left.discard(todo[0])
        while todo:
            x, y = todo.pop()
            grp.append((x, y))
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if n in left:
                    left.discard(n)
                    todo.append(n)
        out.append(sorted(grp))
    return sorted(out)


def sign_px(room, width):
    """atlas size of a sign `width` units wide (16 high): 1 pixel per unit like the original signs, or 2 ("high" detail,
    or "auto" when the text would get too small to read at 1)"""
    detail = room.get("label_detail") or "auto"
    k = 2 if detail == "high" else 1
    if detail == "auto":
        w = max(32, int(width))
        if paintx.fit_text(str(room.get("label", "")), w - 10, 16 - 8, room.get("label_font") or None, max_size=11, min_size=1)[1] < 7.5:
            k = 2
    return (min(SIGN_MAX_W, max(32, int(width) * k)), 16 * k)


def sign_regions(room):
    """[(region name, tiles, width in units, vertical?)] of the signs over a room's doorways"""
    out = []
    if not room.get("label") or not room.get("doors"):
        return out
    for k, grp in enumerate(door_groups(room["doors"])):
        xs, ys = [t[0] for t in grp], [t[1] for t in grp]
        vertical = len(set(ys)) > 1 and len(set(xs)) == 1
        width = ((max(ys) - min(ys) + 1) if vertical else (max(xs) - min(xs) + 1)) * TILE
        out.append(("sign:%s:%d" % (room["id"], k), grp, width, vertical))
    return out


class SceneError(ValueError):
    pass


def asset_fetch(main, files):
    """fetch(name) for models.load: the model's own file, or a file it refers to, which was uploaded next to it as
    <prefix>__<name> (prefix = the part of the main asset's name before "__"; odd characters of file names become "_")"""
    import re
    prefix = main.split("__", 1)[0] + "__" if "__" in main else ""

    def fetch(name):
        return files(name if name == main else prefix + re.sub(r"[^A-Za-z0-9._-]", "_", name))
    return fetch


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


def paint_sign(c, r, room):
    """the lettering over a doorway: its own colours, font and look (room["label_colors"], ["label_font"], ["label_style"]);
    the text is made to fit, never stretched"""
    x0, y0, x1, y1 = r
    k = (y1 - y0) // 16
    lc = dict(SIGN_DEFAULTS)
    lc.update({k: v for k, v in (room.get("label_colors") or {}).items() if k in SIGN_DEFAULTS or k == "outline"})
    style = room.get("label_style") or "plate"
    fg, bg, frame = rgba(lc["fg"]), rgba(lc["bg"]), rgba(lc["frame"])
    outline = rgba(lc["outline"]) if lc.get("outline") else None
    if style == "flat":
        c.rect(r, bg)
        inner = (x0 + 2 * k, y0 + 1 * k, x1 - 2 * k, y1 - 1 * k)
    elif style == "neon":
        c.rect(r, bg)
        c.rect((x0, y0, x1, y0 + k), frame)
        c.rect((x0, y1 - k, x1, y1), frame)
        inner = (x0 + 3 * k, y0 + 2 * k, x1 - 3 * k, y1 - 2 * k)
    else:                                                       # plate
        c.rrect(r, 3 * k, frame)
        c.rrect((x0 + k, y0 + k, x1 - k, y1 - k), 2 * k, bg)
        inner = (x0 + 3 * k, y0 + 2 * k, x1 - 3 * k, y1 - 2 * k)
    c.text(str(room.get("label", "")), inner, fg, font=room.get("label_font") or None, size=int((y1 - y0) * 0.7), fit=True,
           outline=outline, outline_w=(1.2 if style != "flat" else 0.8) * k)


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
        lay = entrance_layout(spec)
        self.side, self.bounds, self.spawn = lay["side"], lay["bounds"], lay["spawn"]
        self.door = lay["door"]
        self.exit = lay["exit"]
        main = spec["main"]
        for r in spec["rooms"]:
            x0, y0, x1, y1 = r["rect"]
            for y in range(y0, y1 + 1):
                for x in range(x0, x1 + 1):
                    if not (0 <= x < GRID and 0 <= y < GRID):
                        raise SceneError("room %s leaves the 16 x 16 grid" % r["id"])
                    if (x, y) in self.owner:
                        raise SceneError("rooms %s and %s overlap at tile %d,%d" % (self.owner[(x, y)], r["id"], x, y))
                    if self.side != "south" and (x, y) not in self.door and not (self.bounds[0] <= x <= self.bounds[2] and self.bounds[1] <= y <= self.bounds[3]):
                        raise SceneError("room %s reaches into the entrance strip (tile %d,%d): the %s door needs the two rows/columns along that edge free"
                                         % (r["id"], x, y, self.side))
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
        self.link = {}                 # tile -> link: walking onto it leaves for another room
        for k in spec.get("links") or []:
            for t in k.get("tiles", []):
                t = tuple(t)
                if t not in self.owner:
                    raise SceneError("link %s: tile %d,%d is not floor" % (k.get("id", "?"), t[0], t[1]))
                self.link[t] = k

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
        for t in list(self.link) + list(self.doorway) + self.door:
            if t not in free:
                out.append("a doorway or the entrance (tile %d,%d) is blocked by furniture" % t)
        if self.door and self.door[0] in free:
            seen, todo = {self.door[0]}, [self.door[0]]
            if not any(n in free and n not in self.door for t in self.door for n in ((t[0] + 1, t[1]), (t[0] - 1, t[1]), (t[0], t[1] + 1), (t[0], t[1] - 1))):
                out.append("the entrance door opens onto a wall: the main area must reach the tile in front of it (%s side)" % self.side)
            while todo:
                x, y = todo.pop()
                for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if n in free and n not in seen:
                        seen.add(n)
                        todo.append(n)
            for r in self.spec["rooms"]:
                tiles = [t for t, o in self.owner.items() if o == r["id"] and t in free]
                if tiles and not any(t in seen for t in tiles):
                    out.append("room %s cannot be reached from the entrance (furniture blocks the way in; its doorways are %s)"
                               % (r["id"], " ".join("%d,%d" % tuple(d) for d in r.get("doors") or []) or "missing"))
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
                elif t in self.link:                    # an exit tile: the plugin decides where it really leads
                    words = (0, 0, 0, 0, 0x4007)
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

    def __init__(self, spec, read, assets=None, files=None):
        s = dict(SCENE_DEFAULT)
        s.update(spec)
        s["materials"] = dict(s.get("materials") or {})
        self.spec = s
        self.read = read
        self.assets = assets or (lambda name: None)       # asset name -> rows
        self.files = files or getattr(assets, "bytes", None) or (lambda name: None)      # asset name -> bytes (3D models)
        self.plan = Plan(s)
        self.wall_h, self.part_h = float(s["wall_h"]), float(s["part_h"])
        self.notes = []
        self.warnings = []
        self._models = {}
        self._custom = {}
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
            for name, _, width, _ in sign_regions(r):
                sizes[name] = sign_px(r, width)
        sizes["trim"] = (16, 16)
        sizes["lip"] = (16, 16)
        sizes["_mirror"] = (16, 16)
        if S.get("links"):
            sizes["_link"] = (16, 16)
        for pname in S["palettes"]:
            for part, size in BED_PARTS.items():
                sizes["bed:%s:%s" % (pname, part)] = size
        for it in S["items"]:
            if it["type"] in ("bed", "stand") and it.get("palette") not in S["palettes"]:
                raise SceneError("item %s uses the unknown palette %r" % (it.get("id", "?"), it.get("palette")))
            if it["type"] == "game":
                self._game_sizes(it, sizes)
            elif it["type"] == "custom":
                self._custom_sizes(it, sizes)
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

    # ---- custom 3D models (Blender exports kept in the project's assets)
    def _custom_model(self, it):
        key = (it.get("asset"), it.get("up", "y"), bool(it.get("flip")))
        if key not in self._custom:
            if not key[0]:
                raise SceneError("item %s: no model chosen" % it.get("id", "?"))
            try:
                self._custom[key] = models.load(key[0], self._model_fetch(key[0]), key[1], key[2])
            except models.ModelError as e:
                raise SceneError("model %s: %s" % (key[0], e))
        return self._custom[key]

    def _model_fetch(self, main):
        return asset_fetch(main, self.files)

    @staticmethod
    def _custom_region(it, mi):
        return "c:%s:%d:%d" % (it["asset"], mi, int(it.get("tex_cap", MODEL_CAP)))

    def _custom_sizes(self, it, sizes):
        m = self._custom_model(it)
        cap = max(8, int(it.get("tex_cap", MODEL_CAP)))
        for mi, _, _ in m.groups:
            im = m.materials[mi].image
            if im is None:
                sizes["_white"] = (4, 4)
                continue
            w, h = im.size
            k = min(1.0, cap / max(w, h))
            sizes[self._custom_region(it, mi)] = (max(2, round(w * k)), max(2, round(h * k)))
        for note in m.notes:
            if note not in self.warnings:
                self.warnings.append("%s: %s" % (it["asset"].split("__")[-1], note))

    def _custom_rows(self, it, mi, size):
        from PIL import Image
        im = self._custom_model(it).materials[mi].image.resize(size, Image.LANCZOS)
        px = im.load()
        return [[px[x, y] for x in range(size[0])] for y in range(size[1])]

    def custom(self, it):
        m = self._custom_model(it)
        for mi, verts, tris in m.groups:
            mat = m.materials[mi]
            region = self._custom_region(it, mi) if mat.image is not None else "_white"
            importer.add_model(self.mesh, verts, tris, region, at=(it["x"], 0, it["z"]), rot=it.get("rot", 0),
                               scale=float(it.get("scale", 1.0)), color=tuple(mat.color) + (1.0,))

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
        if "_link" in R:                      # a doormat in front of the way to another room
            x0, y0, x1, y1 = R["_link"]
            c.rect(R["_link"], (150, 100, 40, 255))
            c.rrect((x0 + 1, y0 + 1, x1 - 1, y1 - 1), 3, (240, 200, 90, 255))
            c.rrect((x0 + 4, y0 + 4, x1 - 4, y1 - 4), 2, (255, 236, 160, 255))
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
            for name, _, _, _ in sign_regions(r):
                paint_sign(c, R[name], r)
        for pname, pal0 in self.spec["palettes"].items():
            pal = dict(BED_DEFAULT)
            pal.update(pal0)
            for part in BED_PARTS:
                paint_bed_part(c, part, pal, R["bed:%s:%s" % (pname, part)])
        if "_white" in R:
            c.rect(R["_white"], (255, 255, 255, 255))
        for it in self.spec["items"]:
            if it["type"] == "game":
                for region, rows in self._game_rows(it).items():
                    paste(c, rows, R[region])
            elif it["type"] == "custom":
                for mi, _, _ in self._custom_model(it).groups:
                    if self._custom_model(it).materials[mi].image is not None:
                        reg = self._custom_region(it, mi)
                        x0, y0, x1, y1 = R[reg]
                        paste(c, self._custom_rows(it, mi, (x1 - x0, y1 - y0)), R[reg])
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
        bx0, by0, bx1, by1 = plan.bounds
        door = set(plan.door)
        for x in range(bx0, bx1 + 1):                           # back wall
            room = plan.owner.get((x, by0))
            if room and (x, by0 - 1) not in door:
                self.wall_quad(((x + 1) * T, by0 * T), (x * T, by0 * T), WALL_H, wall_region(room))
        for y in range(by0, by1 + 1):                           # side walls
            for x, a, b, beyond in ((bx0, (bx0 * T, y * T), (bx0 * T, (y + 1) * T), (bx0 - 1, y)),
                                    (bx1, ((bx1 + 1) * T, (y + 1) * T), ((bx1 + 1) * T, y * T), (bx1 + 1, y))):
                room = plan.owner.get((x, y))
                if room and beyond not in door:
                    self.wall_quad(a, b, WALL_H, wall_region(room))
        tpart = PART_H / WALL_H
        for y in range(by0, by1 + 1):
            for x in range(bx0, bx1 + 1):
                if not plan.wall((x, y)):
                    continue
                faces = []
                x0, x1, z0, z1 = x * T, (x + 1) * T, y * T, (y + 1) * T
                for (nx, ny), a, b in (((x, y + 1), (x0, z1), (x1, z1)), ((x, y - 1), (x1, z0), (x0, z0)),
                                       ((x - 1, y), (x0, z0), (x0, z1)), ((x + 1, y), (x1, z1), (x1, z0))):
                    room = plan.owner.get((nx, ny))
                    if room and bx0 <= nx <= bx1 and by0 <= ny <= by1 and (nx, ny) not in door:
                        faces.append(room)
                        self.wall_quad(a, b, PART_H, wall_region(room), tpart)
                if faces:
                    m.quad((x0, PART_H, z1), (x1, PART_H, z1), (x1, PART_H, z0), (x0, PART_H, z0), "trim", normal=(0, 1, 0))
        for r in self.spec["rooms"]:                            # a lintel with a sign over each doorway
            for sign, grp, width, vertical in sign_regions(r):
                xs, ys = [t[0] for t in grp], [t[1] for t in grp]
                x0, x1, z0, z1 = min(xs) * T, (max(xs) + 1) * T, min(ys) * T, (max(ys) + 1) * T
                y0, y1 = PART_H, PART_H + 16
                if not vertical:
                    m.box(x0, x1, y0, y1, z0 + 10, z1 - 10, {"front": sign, "back": "trim", "top": "trim", "bottom": "trim", "left": "trim", "right": "trim"})
                else:
                    side = "right" if x0 < GRID * T / 2 else "left"
                    faces = {k: "trim" for k in ("front", "back", "top", "bottom", "left", "right")}
                    m.box(x0 + 10, x1 - 10, y0, y1, z0, z1, {k: v for k, v in faces.items() if k != side})
                    if side == "right":
                        m.quad((x1 - 10, y0, z1), (x1 - 10, y0, z0), (x1 - 10, y1, z0), (x1 - 10, y1, z1), sign)
                    else:
                        m.quad((x0 + 10, y0, z0), (x0 + 10, y0, z1), (x0 + 10, y1, z1), (x0 + 10, y1, z0), sign)
        for (x, y) in plan.link:                # doormats on the link tiles
            self.flat(x * T + 3, y * T + 3, (x + 1) * T - 3, (y + 1) * T - 3, "_link", y=0.7)
        if plan.side == "south":
            dxs = sorted(t[0] for t in plan.door)
            gap0, gap1 = (dxs[0] * T, (dxs[-1] + 1) * T) if dxs else (0, 0)
            for x0, x1 in ((0, gap0), (gap1, GRID * T)):
                if x1 > x0:
                    m.quad((x0, -16, 448), (x1, -16, 448), (x1, 0, 448), (x0, 0, 448), "lip")
        else:                                   # the front stays closed; a mat in the doorway on the side
            m.quad((0, -16, 448), (GRID * T, -16, 448), (GRID * T, 0, 448), (0, 0, 448), "lip")
            for (x, y) in plan.door:
                self.flat(x * T, y * T, (x + 1) * T, (y + 1) * T, "trim", y=0.0)

    # ---- items
    def _tiles_world(self, tile):
        return ((tile[0] + 0.5) * TILE, (tile[1] + 0.5) * TILE)

    def add_item(self, it):
        n0 = len(self.mesh.verts)
        self._add_item(it)
        lift = float(it.get("lift") or 0)
        if lift:                                # raised above (or sunk into) the floor
            for v in self.mesh.verts[n0:]:
                p = v["pos"]
                v["pos"] = (p[0], p[1] + lift, p[2])

    def _add_item(self, it):
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
        elif t == "custom":
            self.custom(it)
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
        problems = self.plan.problems() + self.budget()
        if problems:
            raise SceneError("; ".join(problems))
        self.mesh.weld()
        return self

    MAX_VERTS = 60000                               # the room is one mesh with 16-bit indices

    def budget(self):
        """errors about the size of the mesh (and warnings, in self.warnings, when it gets heavy)"""
        n, tris = len(self.mesh.verts), len(self.mesh.tris) // 3
        msg = "%d triangles" % tris
        self.warnings = [w for w in self.warnings if "triangles" not in w]
        if n > self.MAX_VERTS:
            return ["the room has too many vertices (%d, at most %d): simplify the custom models (Blender: Decimate modifier)" % (n, self.MAX_VERTS)]
        if tris > 20000:
            self.warnings.append("%s: heavy for a 3DS; expect slowdowns (Blender: Decimate the models)" % msg)
        return []


def build_scene(spec, read, assets=None, files=None):
    return Builder(spec, read, assets, files).build()


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
