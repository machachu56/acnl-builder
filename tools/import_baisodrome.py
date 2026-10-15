#!/usr/bin/env python3
"""One-time conversion: the hand-coded Baisodrome mod (recomp/mods/baisodrome) -> an editable Builder project.

    python3 tools/import_baisodrome.py [project id]       (default: baisodrome)

The building becomes a `love_hotel` exterior, the interior becomes rooms + materials + items, the
hand-painted props become PNG assets (editable in the Builder's pixel editor), Tom Nook's lines become
text edits. After this the old scripts are no longer needed.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from acnlb import env, interior as I, project, rom, texfmt  # noqa: E402
from acnlb.features.textures import to_png  # noqa: E402

env.setup_path()
OLD = os.path.join(env.RECOMP, "mods", "baisodrome")
sys.path.insert(0, OLD)
import dialogue as old_dialogue  # noqa: E402
import interior as old_interior  # noqa: E402
from modkit import cgfx, etc1  # noqa: E402
from modkit.paint import Canvas, Packer, pack_all  # noqa: E402
from acnlb import paintx  # noqa: E402

Canvas.text = paintx.Canvas.text      # lettering with Pillow instead of a missing ImageMagick font

T = 32


def c_(tx, ty):
    return ((tx + 0.5) * T, (ty + 0.5) * T)


def e_(tx, ty):
    return ((tx + 1) * T, (ty + 1) * T)


def main():
    pid = sys.argv[1] if len(sys.argv) > 1 else "baisodrome"
    d = project.project_dir(pid)
    if os.path.exists(d):
        sys.exit("%s exists" % d)
    p = project.create(pid, "Baisodrome")
    assets = os.path.join(d, "assets")

    def save_png(name, rows):
        with open(os.path.join(assets, name), "wb") as f:
            f.write(to_png(rows))

    # ---- materials: floors / walls of the themes, the props as images
    rooms_theme = {"lobby": ("hearts", "stripes_hearts"), "nuptial": ("marble", "panel"), "donjon": ("flagstone", "brick"),
                   "disco": ("checker", "night"), "spa": ("tiles", "tiles"), "panther": ("leopard", "leopard"),
                   "vibro": ("shag", "tufted")}
    mats = {}
    for theme, (fl, wl) in rooms_theme.items():
        mats["floor_" + theme] = {"type": "floor", "preset": fl}
        mats["wall_" + theme] = {"type": "wall", "preset": wl}
    # Lovely series: the game's own carpet and wallpaper, read from the dump at build time (never stored)
    mats["lovely_floor"] = {"type": "floor", "game_texture": {"path": "/Item/Model/carpet_lovely.bcres", "name": "carpet_lovely"}}
    mats["lovely_wall"] = {"type": "wall", "game_texture": {"path": "/Item/Model/wall_lovely.bcres", "name": "wall_lovely"}}
    # props painted by the old code
    props = dict(old_interior.PROPS)
    for skip in ("trim",):
        props.pop(skip, None)
    pk = Packer(512, 512)
    R = pack_all(pk, props)
    canvas = Canvas(512, 512, (255, 255, 255, 255))
    old_interior.paint_props(canvas, dict(R, trim=R.get("trim", (0, 0, 16, 16))) if "trim" in R else _with_trim(R))
    rows = canvas.rows()
    for name, (x0, y0, x1, y1) in R.items():
        save_png("prop_%s.png" % name, [row[x0:x1] for row in rows[y0:y1]])
        mats[name] = {"type": "prop", "image": "prop_%s.png" % name, "size": [x1 - x0, y1 - y0]}
    mats["lov_lamp_f"] = {"type": "prop", "size": [32, 32], "game_texture": {"path": "/Item/Model/rmk_lov_lamp.bcres", "name": "fabric_00"}}

    pal = {}
    for theme, v in old_interior.BED_SETS.items():
        names = ("wood", "wood_dark", "accent", "accent_light", "sheet", "sheet_dark")
        pal[theme] = {k: ("#%02x%02x%02x" % tuple(c) if c else None) for k, c in zip(names, v)}

    # ---- rooms
    rooms = []
    for name, r in old_interior.ROOMS.items():
        theme = "lobby" if name == "lobby" else name
        room = {"id": name, "rect": list(r["rect"]), "floor": "lovely_floor" if name == "lovely" else "floor_" + theme,
                "wall": "lovely_wall" if name == "lovely" else "wall_" + theme}
        if r.get("doors"):
            room["doors"] = [list(t) for t in r["doors"]]
        if r.get("label"):
            room["label"] = r["label"]
        rooms.append(room)
    rooms[0]["id"] = "main"
    rooms[0]["name"] = "Lobby"

    items = []
    n = [0]

    def add(kind, block=None, **kw):
        n[0] += 1
        it = {"id": "i%d" % n[0], "type": kind}
        it.update(kw)
        if block:
            it["block"] = [list(t) for t in block]
        items.append(it)
        return it

    def box(x0, x1, y0, y1, z0, z1, mat, top=None, faces=None, **kw):
        f = dict(faces or {})
        if top:
            f["top"] = top
        return add("box", x0=x0, x1=x1, y0=y0, y1=y1, z0=z0, z1=z1, mat=mat, faces=f, **kw)

    def cyl(cx, cz, r, y0, y1, side, top, n=12, **kw):
        return add("cyl", cx=cx, cz=cz, r=r, y0=y0, y1=y1, side=side, top=top, n=n, **kw)

    def lovely(name, at, rot=0, block=None):
        return add("game", path="/Item/Model/rmk_lov_%s.bcres" % name, x=at[0], z=at[1], rot=rot, tex_cap=128, block=block)

    def lamp(at, shade, block=None):
        return add("lamp", x=at[0], z=at[1], shade=shade, block=block)

    def bed(at, theme, rot=0, block=None):
        return add("bed", x=at[0], z=at[1], rot=rot, palette=theme, block=block)

    def stand(at, theme, block=None):
        return add("stand", x=at[0], z=at[1], palette=theme, block=block)

    def flat(x0, z0, x1, z1, mat, y=0.4):
        return add("flat", x0=x0, z0=z0, x1=x1, z1=z1, mat=mat, y=y)

    def quad(pts, mat):
        return add("quad", pts=[list(p) for p in pts], mat=mat)

    # lobby
    counter = box(322, 350, 0, 26, 322, 382, "counter")
    counter["block"] = [[10, 10], [10, 11]]
    box(320, 352, 26, 29, 320, 384, "gold", top="counter_top")
    cyl(336, 336, 3.5, 29, 33, "bell", "bell", 8)
    cyl(340, 372, 4, 29, 40, "bottle", "gold", 6)
    add("extrude", shape="oval", cx=270, cz=272, size=104, y0=0, y1=6, side="gold", top="counter_top", block=[(7, 8), (8, 8)])
    for r, y0 in ((22, 6), (16, 16), (10, 26), (5, 36)):
        cyl(270, 272, r, y0, y0 + 10, "tub_rim", "glass", 10)
    cyl(270, 272, 1.5, 46, 54, "bottle", "gold", 6)
    lovely("chairL", (e_(5, 12)[0], 13.5 * T), 180, block=[(5, 13), (6, 13), (5, 12), (6, 12)])
    lovely("tableM", (6 * T, 12.5 * T))
    box(356, 380, 0, 56, 164, 186, "vending_side", faces={"front": "vending"}, block=[(11, 5)])
    quad([(196, 48, 161), (252, 48, 161), (252, 90, 161), (196, 90, 161)], "price")
    flat(214, 344, 302, 404, "rug_love")
    for t in ((6, 5), (9, 5)):
        lamp(c_(*t), "lov_lamp_f", block=[t])
    for x, z in ((214, 300), (300, 302), (236, 236), (300, 230), (322, 290), (190, 340)):
        flat(x, z, x + 6, z + 4, "petal", 0.5)
    # lovely
    lovely("bedW", e_(1, 0), block=[(1, 0), (2, 0), (1, 1), (2, 1)])
    lovely("tableS", c_(0, 0), block=[(0, 0)])
    lamp(c_(0, 0), "lov_lamp_f")
    lovely("dresser", c_(3, 0), block=[(3, 0)])
    lovely("chairS", c_(0, 2), 90, block=[(0, 2)])
    lovely("chairS", c_(0, 3), 90, block=[(0, 3)])
    # nuptial
    bed(e_(7, 0), "nuptial", 0, block=[(7, 0), (8, 0), (7, 1), (8, 1)])
    quad([(224, 64, 1), (288, 64, 1), (288, 80, 1), (224, 80, 1)], "married")
    for t in ((6, 0), (9, 0)):
        stand(c_(*t), "nuptial", block=[t])
        cyl(*c_(*t), 5, 24, 32, "gold", "glass", 8)
        cyl(*c_(*t), 1.5, 32, 40, "bottle", "gold", 6)
    for t in ((6, 3), (9, 3)):
        stand(c_(*t), "nuptial", block=[t])
        cyl(*c_(*t), 9, 24, 30, "bed:nuptial:sheet", "bed:nuptial:pillow", 10)
    for x, z in ((214, 80), (236, 96), (274, 90), (300, 70), (250, 110)):
        flat(x, z, x + 6, z + 4, "petal", 0.5)
    # donjon
    bed(e_(13, 0), "donjon", 0, block=[(13, 0), (14, 0), (13, 1), (14, 1)])
    quad([(420, 50, 1), (452, 50, 1), (452, 58, 1), (420, 58, 1)], "cuffs")
    quad([(358, 46, 1), (422, 46, 1), (422, 78, 1), (358, 78, 1)], "whips")
    x0, z0 = 11 * T + 2, 2
    for a, b in (((x0, z0 + 28), (x0 + 28, z0 + 28)), ((x0 + 28, z0 + 28), (x0 + 28, z0)), ((x0, z0), (x0, z0 + 28))):
        add("wallquad", a=list(a), b=list(b), h=44, mat="cage", both=True)
    add("flat", x0=x0, z0=z0, x1=x0 + 28, z1=z0 + 28, mat="black", y=44, block=[[11, 0]])
    box(482, 486, 0, 64, 66, 70, "black", block=[(15, 2), (15, 3)])
    box(482, 486, 0, 64, 122, 126, "black")
    box(482, 486, 60, 64, 66, 126, "black")
    for z in (84, 108):
        box(483, 485, 22, 60, z, z + 2, "black")
    box(474, 494, 18, 22, 82, 112, "leather")
    for t in ((12, 3), (15, 0)):
        cyl(*c_(*t), 3, 0, 14, "candle", "candle", 6)
    # disco
    cyl(48, 208, 2.2, 0, 112, "chrome", "chrome", 8, block=[[1, 6]])
    cyl(48, 208, 10, 0, 3, "chrome", "chrome", 12)
    cyl(48, 230, 9, 84, 102, "mirrorball", "mirrorball", 10)
    for t in ((0, 5), (2, 5)):
        box(c_(*t)[0] - 12, c_(*t)[0] + 12, 0, 40, 162, 186, "speaker", top="black", block=[t])
    bed(e_(0, 7), "disco", 90, block=[(0, 7), (1, 7), (0, 8), (1, 8)])
    quad([(4, 60, 168), (4, 60, 232), (4, 92, 232), (4, 92, 168)], "neon_love")
    # spa
    add("extrude", shape="heart", cx=64, cz=352, size=60, y0=0, y1=14, top_y=12, side="tub_side", top="water",
        block=[(0, 10), (1, 10), (0, 11), (1, 11)])
    quad([(60, 13, 350), (70, 13, 350), (70, 23, 350), (60, 23, 350)], "duck")
    box(c_(2, 10)[0] - 12, c_(2, 10)[0] + 12, 0, 26, 324, 348, "towels", block=[(2, 10)])
    lovely("tableM", (T, 13.5 * T), block=[(0, 13), (1, 13)])
    flat(4, 420, 60, 444, "towels", 17)
    # panther
    bed(e_(14, 5), "panther", 270, block=[(14, 5), (15, 5), (14, 6), (15, 6)])
    stand(c_(13, 5), "panther", block=[(13, 5)])
    lamp(c_(13, 5), "bed:panther:sheet")
    flat(420, 228, 504, 280, "fur")
    stand(c_(15, 8), "panther", block=[(15, 8)])
    # vibro
    bed(e_(14, 10), "vibro", 270, block=[(14, 10), (15, 10), (14, 11), (15, 11)])
    box(436, 452, 0, 22, 384, 396, "coinbox")
    quad([(448, 70, 321), (512, 70, 321), (512, 86, 321), (448, 86, 321)], "vibro_sign")
    stand(c_(15, 13), "vibro", block=[(15, 13)])
    for x, z in ((430, 420), (470, 404)):
        flat(x, z, x + 8, z + 8, "condom", 0.5)

    scene = {"id": "baiso_in", "title": "Baisodrome interior", "main": "main", "materials": mats, "palettes": pal,
             "rooms": rooms, "items": items}
    used = {m for it in items for k in ("mat", "side", "top", "shade") for m in [it.get(k)] if m}
    used |= {m for it in items for m in (it.get("faces") or {}).values()}
    used |= {r[k] for r in rooms for k in ("floor", "wall") if r.get(k)}
    for name in list(mats):
        if name not in used:
            mats.pop(name)
            f = os.path.join(assets, "prop_%s.png" % name)
            if os.path.exists(f):
                os.remove(f)
    p["interiors"].append(scene)

    # ---- the building
    p["buildings"].append({
        "id": "baisodrome", "name": "Baisodrome", "slot": 0x4D, "model": "sobj_baisod", "scene": 0x41, "dx": 4, "dy": 7,
        "interior": "baiso_in", "hide_furniture": True,
        "style": {"base": "policeB"}, "map_name": {"en": "Baisodrome"},
        "map_icon": {"shape": "heart", "fill": "#f6548c", "outline": "#78143c"},
    })
    # ---- Tom Nook presents the place every time the player walks in; his goodbye changes too
    p["events"].append({"id": "welcome", "type": "enter_talk", "building": "baisodrome", "npc": "Tanukichi",
                        "steps": [{"text": dict(old_dialogue.SPEECH)}],
                        "goodbye": {"en": old_dialogue.LINES["en"]["001"], "fr": old_dialogue.LINES["fr"]["001"]}})
    project.save(p)
    print("created", d)


def _with_trim(R):
    R = dict(R)
    R["trim"] = (0, 0, 16, 16)
    return R


if __name__ == "__main__":
    main()
