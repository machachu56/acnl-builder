"""Story: a game of your own on top of the town (the runtime plugin's story module, plugin/story.h).

project.json "story":
  {"enabled": true, "debug": false,
   "props": [{"id": "station_bar", "model": {"shape": "barrier"} | {"shape": "planks"} | {"shape": "sign", "text": "CONDAMNÉ"}
                                            | {"furniture": 0x2F20} | {"game": "/Strc/fobj/fobj_bench_plain/fobj_bench_plain.bcres"},
              "near": "station" | "town_hall" | "retail" | "bbs" | "pier" | "boat" | "reset" | "bridge" | "plaza" | "crossing" | "tile",
              "at": [dx, dz] (tiles from the building's tile, or the tile itself for "tile"), "yaw": 0 (degrees), "scale": 1.0,
              "solid": "auto" | [half x, half z] | false, "show": "freed_0" | "!freed_0" (a script value; none = always)}],
   "npcs": [{"id": "marie", "profile": 457, "code": "sza", "near": "station", "at": [dx, dz], "yaw": 0}],
   "models": [{"code": "hb0", "from": "/Npc/Normal/Model/cat00.bcres"}]   (a character model of the game under a new code)
   "quests": [{"title": "Premiers pas", "desc": "..."}], "hud_ready": "Retourne voir Marie"}

Props become story/<id>.apm (+ a [prop] section); the HUD font story/font.apm (an atlas) and story/font.bin (its glyphs).
A model of the game's town structures (/Strc/...) is drawn with its season00 textures (and its French sign texture): Main
Street's buildings cannot be real town buildings (their class is not loaded in the town), so they stand in the town as props.
Characters ([npc]) are actors of the game created by the plugin (profile, model code), kept on their spot.
Quests are shown once the script value "quest_on" is set: "quest" (an index of the list), "quest_ready" (done: go back to the
quest giver).
"""
import math
import os
import re
import struct

from PIL import Image, ImageDraw, ImageFont

from .. import propmesh, rom
from . import furniture as fmod

ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,22}$")
NEAR = ("station", "town_hall", "retail", "bbs", "pier", "boat", "reset", "bridge", "plaza", "crossing", "tile")
U = 28.0                     # one unit of the web game's world in the game's (32 per tile)
FONTS = ("/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
         "C:/Windows/Fonts/arialbd.ttf")
CHARSET = ("".join(chr(c) for c in range(32, 127)) + "àâäçéèêëîïôöùûüÿœæÀÂÄÇÉÈÊËÎÏÔÖÙÛÜŸŒÆ«»’…–—✿❤°€")
FONT_PX = 32


def font(size):
    for f in FONTS:
        if os.path.isfile(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default(size)


def texture_apm(rows):
    """an .apm with one texture and no geometry (the plugin draws it on the screens)"""
    h, w = len(rows), len(rows[0])
    out = bytearray(b"APM1") + struct.pack("<5I", 0, 0, 0, 1, 0) + struct.pack("<4I", w, h, 0, 0)
    out += bytes(c for r in rows for px in r for c in px)
    return bytes(out)


def font_files():
    """(atlas .apm, glyphs .bin): every character of CHARSET, white on transparent"""
    f = font(FONT_PX)
    asc, desc = f.getmetrics()
    line = asc + desc + 4
    W, x, y, glyphs = 512, 1, 1, []
    cells = []
    for ch in CHARSET:
        box = f.getbbox(ch)
        w, h = max(1, box[2] - box[0]), max(1, box[3] - box[1])
        if x + w + 1 > W:
            x, y = 1, y + line
        cells.append((ch, x, y, w, h, box[0], box[1], int(round(f.getlength(ch)))))
        x += w + 2
    H = 1
    while H < y + line:
        H *= 2
    im = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    d = ImageDraw.Draw(im)
    for ch, gx, gy, w, h, ox, oy, adv in cells:
        if ch != " ":
            d.text((gx - ox, gy - oy), ch, font=f, fill=(255, 255, 255, 255))
        glyphs.append(struct.pack("<I4H2hH2x", ord(ch), gx, gy, w, h, ox, oy, adv))     # 20 bytes, as the plugin's struct
    rows = [[im.getpixel((i, j)) for i in range(W)] for j in range(H)]
    return texture_apm(rows), b"FNT1" + struct.pack("<4H", len(glyphs), line, W, H) + b"".join(glyphs)


# ---------------------------------------------------------------- shapes made here

def _tex(prop, rows):
    prop.textures.append((len(rows[0]), len(rows), rows, 1, 1))
    return len(prop.textures) - 1


def _rows(im):
    im = im.convert("RGBA")
    return [[im.getpixel((x, y)) for x in range(im.width)] for y in range(im.height)]


def box(prop, tex, center, size, rot_z=0.0, name="box"):
    """a box part: center, size (x, y, z), turned about z by rot_z (radians); each face shows the whole texture"""
    p = propmesh.Part(name, tex, 0)
    cx, cy, cz = center
    hx, hy, hz = (s / 2 for s in size)
    c, s = math.cos(rot_z), math.sin(rot_z)
    turn = lambda v: (v[0] * c - v[1] * s, v[0] * s + v[1] * c, v[2])
    faces = [((0, 0, 1), [(-1, 1, 1), (1, 1, 1), (1, -1, 1), (-1, -1, 1)]), ((0, 0, -1), [(1, 1, -1), (-1, 1, -1), (-1, -1, -1), (1, -1, -1)]),
             ((1, 0, 0), [(1, 1, 1), (1, 1, -1), (1, -1, -1), (1, -1, 1)]), ((-1, 0, 0), [(-1, 1, -1), (-1, 1, 1), (-1, -1, 1), (-1, -1, -1)]),
             ((0, 1, 0), [(-1, 1, -1), (1, 1, -1), (1, 1, 1), (-1, 1, 1)]), ((0, -1, 0), [(-1, -1, 1), (1, -1, 1), (1, -1, -1), (-1, -1, -1)])]
    for n, corners in faces:
        base = len(p.verts)
        for k, (ax, ay, az) in enumerate(corners):
            x, y, z = turn((ax * hx, ay * hy, az * hz))
            p.verts.append(((cx + x, cy + y, cz + z), turn(n), ((0, 1, 1, 0)[k], (0, 0, 1, 1)[k]), (255, 255, 255, 255)))
        p.tris += [base, base + 1, base + 2, base, base + 2, base + 3]
    prop.parts.append(p)


def stripes(w=64, h=16, a=(226, 59, 46), b=(255, 255, 255)):
    im = Image.new("RGB", (w, h), a)
    d = ImageDraw.Draw(im)
    for x in range(-h, w, 16):
        d.polygon([(x, h), (x + 8, h), (x + 8 + h, 0), (x + h, 0)], fill=b)
    return _rows(im)


def wood(w=64, h=16, base=(122, 74, 37)):
    im = Image.new("RGB", (w, h), base)
    d = ImageDraw.Draw(im)
    for y in range(2, h, 5):
        d.line([(0, y), (w, y + 1)], fill=tuple(int(c * 0.78) for c in base))
    return _rows(im)


def plain(rgb):
    return [[tuple(rgb) + (255,)] * 4 for _ in range(4)]


def sign_tex(text, bg=(226, 59, 46), fg=(255, 255, 255), w=128, h=48):
    im = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(im)
    size = h
    while size > 8:
        f = font(size)
        bb = d.textbbox((0, 0), text, font=f)
        if bb[2] - bb[0] <= w - 8 and bb[3] - bb[1] <= h - 8:
            break
        size -= 2
    d.text(((w - bb[2] - bb[0]) / 2, (h - bb[3] - bb[1]) / 2), text, font=f, fill=fg)
    return _rows(im)


def shape_prop(spec):
    kind = spec.get("shape")
    p = propmesh.Prop(kind)
    if kind == "barrier":           # a striped construction bar on two posts (the web game's makeBarrier)
        post, bar = _tex(p, plain((202, 162, 74))), _tex(p, stripes())
        for sx in (-1.3, 1.3):
            box(p, post, (sx * U, 0.65 * U, 0), (0.2 * U, 1.3 * U, 0.2 * U))
        box(p, bar, (0, 1.05 * U, 0), (3.0 * U, 0.34 * U, 0.16 * U))
    elif kind == "planks":          # two crossed planks over a door
        t = _tex(p, wood())
        for rot in (0.6, -0.6):
            box(p, t, (0, 1.1 * U, 0), (3.4 * U, 0.42 * U, 0.14 * U), rot)
    elif kind == "sign":            # a board with lettering (CONDAMNÉ...), standing at the height given
        t = _tex(p, sign_tex(spec.get("text", ""), tuple(spec.get("bg", (226, 59, 46))), tuple(spec.get("fg", (255, 255, 255)))))
        y = spec.get("height", 1.75) * U
        box(p, t, (0, y, 0), (1.5 * U, 0.55 * U, 0.08 * U))
        if spec.get("post"):
            box(p, _tex(p, wood()), (0, y / 2, -0.06 * U), (0.14 * U, y, 0.14 * U))
    else:
        raise ValueError("story prop: unknown shape %r" % kind)
    return p


def model_prop(spec):
    if spec.get("shape"):
        return shape_prop(spec)
    if spec.get("furniture") is not None:
        item = int(spec["furniture"])
        e = next((e for e in fmod.catalog() if e["id"] == item), None)
        if not e:
            raise ValueError("story prop: %#x is not a furniture item" % item)
        p = propmesh.from_game_model(fmod.model_path(e), pose=True)
    elif spec.get("game"):
        path = spec["game"]
        tex = []
        if path.startswith("/Strc/"):            # town structures: textures beside the model, the sign in the game's language too
            d = path.rsplit("/", 1)[0] + "/Textures/"
            tex = [d + f for f in ("season00.bcres", "season00_EU_FRA.bcres") if rom.exists(d + f)]
        p = propmesh.from_game_model(path, tex_file=tex)
    else:
        raise ValueError("story prop: the model needs a shape, a furniture item or a game model")
    p.ground()
    if spec.get("cage"):            # four copies of a panel (jail bars) around a square as wide as the panel
        lo, hi = p.bounds()
        w = hi[0] - lo[0]
        cage = propmesh.Prop(p.name + "_cage")
        cage.textures = p.textures
        for k in range(4):
            a = k * math.pi / 2
            c, s = math.cos(a), math.sin(a)
            for part in p.parts:
                q = propmesh.Part(part.name, part.tex, part.flags)
                for pos, n, uv, rgba in part.verts:
                    x, y, z = pos[0], pos[1], pos[2] + w / 2
                    q.verts.append(((x * c + z * s, y, -x * s + z * c), (n[0] * c + n[2] * s, n[1], -n[0] * s + n[2] * c), uv, rgba))
                q.tris = list(part.tris)
                cage.parts.append(q)
        p = cage
    return p


# ---------------------------------------------------------------- compile

def compile(b):
    sto = b.proj.get("story") or {}
    if not sto or not sto.get("enabled", True):
        return
    cfg = b.cfg["story"] = {"debug": int(bool(sto.get("debug"))), "font": "story/font.apm"}
    if sto.get("hud_ready"):
        cfg["hud_ready"] = sto["hud_ready"]
    props = b.cfg["story_props"] = []
    for sp in sto.get("props") or []:
        pid = sp.get("id", "")
        if not ID_RE.match(pid):
            raise ValueError("story prop %r: lowercase letters, digits, _ (23 at most)" % pid)
        near = sp.get("near", "town_hall")
        if near not in NEAR:
            raise ValueError("story prop %s: near %r is not one of %s or a story building" % (pid, near, ", ".join(NEAR)))
        prop = model_prop(sp.get("model") or {})
        lo, hi = prop.bounds()
        b.add("story/%s.apm" % pid, prop.apm())
        solid = sp.get("solid", "auto")
        if solid == "auto":
            solid = [max(abs(lo[0]), abs(hi[0])), max(abs(lo[2]), abs(hi[2]))]
        at = sp.get("at") or [0, 0]
        e = {"id": pid, "mesh": "story/%s.apm" % pid, "near": near, "at": "%d, %d" % (round(at[0] * 16), round(at[1] * 16)),
             "yaw": int(sp.get("yaw", 0)), "scale": int(round(float(sp.get("scale", 1.0)) * 100))}
        if solid:
            e["solid"] = "%d, %d" % (round(solid[0]), round(solid[1]))
        if sp.get("show"):
            e["show"] = sp["show"]
        props.append(e)
    for m in sto.get("models") or []:      # e.g. a villager's model as a special character's, so the story's class can wear it
        if not re.match(r"^[a-z0-9]{3}$", m.get("code", "")) or not rom.exists(m.get("from", "")):
            raise ValueError("story model %r: a 3-character code and a model file of the game" % m)
        b.put("/Npc/Special/Model/%s.bcres" % m["code"], rom.read(m["from"]))
    npcs = b.cfg["story_npcs"] = []
    for n in sto.get("npcs") or []:
        near = n.get("near", "town_hall")
        if near not in NEAR:
            raise ValueError("story character %s: near %r is not one of %s" % (n.get("id"), near, ", ".join(NEAR)))
        at = n.get("at") or [0, 0]
        npcs.append({"id": n["id"], "profile": int(n["profile"]), "code": n.get("code", ""), "near": near,
                     "at": "%d, %d" % (round(at[0] * 16), round(at[1] * 16)), "yaw": int(n.get("yaw", 0))})
    b.cfg["story_quests"] = [{"title": q.get("title", ""), "desc": q.get("desc", "")} for q in sto.get("quests") or []]
    atlas, glyphs = font_files()
    b.add("story/font.apm", atlas)
    b.add("story/font.bin", glyphs)
    b.note("story: %d prop(s), %d quest(s), %d talk point(s)" % (len(props), len(b.cfg["story_quests"]), len(b.cfg.get("talk_points", []))))


def config_lines(b):
    """the story's sections of acnlb.cfg"""
    if "story" not in b.cfg:
        return []
    out = ["", "[story]"] + ["%s = %s" % kv for kv in b.cfg["story"].items()]
    if b.cfg.get("script_vars"):
        out += ["", "[vars]"] + ["%s = %d" % (n, i) for i, n in enumerate(b.cfg["script_vars"])]
    if b.cfg.get("talk_points"):
        out += ["", "[talk]"] + ["point = %s" % n for n in b.cfg["talk_points"]]
    for p in b.cfg.get("story_props", []):
        out += ["", "[prop]"] + ["%s = %s" % kv for kv in p.items()]
    for q in b.cfg.get("story_quests", []):
        out += ["", "[quest]", "title = %s" % q["title"], "desc = %s" % q["desc"]]
    for n in b.cfg.get("story_npcs", []):
        out += ["", "[npc]"] + ["%s = %s" % kv for kv in n.items() if kv[1] != ""]
    if (b.proj.get("story") or {}).get("probe_actors"):
        out += ["", "[probe]", "actors = 1"]
    return out
