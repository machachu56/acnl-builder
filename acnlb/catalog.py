"""Browsing the game's data for the editors: text files, villagers, models, textures."""
import base64
import functools
import io
import re

from . import env, rom, skeleton, texfmt
from .features import text as textmod

env.setup_path()
from modkit import cgfx, msbt  # noqa: E402

# friendly names of NPC talk files (their file names are Japanese romaji)
NPC_ALIASES = {
    "Tanukichi": "Tom Nook", "Tunekichi": "Crazy Redd", "Kappei": "Kapp'n", "Totakeke": "K.K. Slider", "Rover": "Rover",
    "Master": "Brewster", "Jonny": "Gulliver", "Cafe": "The Roost", "CafeOrder": "The Roost (orders)", "Reset": "Mr. Resetti",
    "Recycle": "Re-Tail", "PoliceA": "Police station", "PoliceB": "Police station", "Station": "Train station",
    "Fireworks": "Fireworks show", "Prologue": "Intro", "Event": "Events", "Snowman": "Snowmen",
}
SPECIES = {
    "ant": "Anteater", "bea": "Bear", "brd": "Bird", "bul": "Bull", "cat": "Cat", "cbr": "Cub", "chn": "Chicken",
    "cow": "Cow", "crd": "Alligator", "der": "Deer", "dog": "Dog", "duk": "Duck", "elp": "Elephant", "flg": "Frog",
    "goa": "Goat", "gor": "Gorilla", "ham": "Hamster", "hip": "Hippo", "hrs": "Horse", "kal": "Koala", "kgr": "Kangaroo",
    "lon": "Lion", "mus": "Mouse", "mnk": "Monkey", "oct": "Octopus", "ost": "Ostrich", "pbr": "Polar bear",
    "pgn": "Penguin", "pig": "Pig", "rbt": "Rabbit", "rhn": "Rhino", "shp": "Sheep", "squ": "Squirrel", "tig": "Tiger",
    "wol": "Wolf",
}


@functools.lru_cache(maxsize=1)
def text_files():
    """[{path, group, name}] of every text file"""
    out = []
    for p in sorted(rom.listing()):
        if not p.endswith((".umsbt", ".msbt")) or not p.startswith("/Script/"):
            continue
        group = p.split("/")[2]
        base = p.rsplit("/", 1)[1].rsplit(".", 1)[0]
        name = base
        m = re.match(r"NPC_([A-Za-z0-9]+)", base)
        if m and m.group(1) in NPC_ALIASES:
            name += "  (%s)" % NPC_ALIASES[m.group(1)]
        out.append({"path": p, "group": group, "name": name})
    return out


def read_text(path):
    """{lang: [{label, text}]} (messages with a label only)"""
    t = textmod.read_table(path)
    return {lang: [{"label": l, "text": s} for l, k, s in rows if l] for lang, rows in t.items()}


def search_text(q, limit=60):
    """messages whose English text contains q (case-insensitive)"""
    q = q.lower()
    out = []
    for f in text_files():
        if not f["path"].endswith(".umsbt"):
            continue
        d = rom.read(f["path"])
        parts = msbt.umsbt_split(d)
        if not parts:
            continue
        m = msbt.Msbt(parts[0])
        by = {v: k for k, v in m.labels.items()}
        for i in range(len(m.raw)):
            s = m.text(i)
            if q in textmod.CODE.sub("", s).lower() and by.get(i):
                out.append({"path": f["path"], "label": by[i], "text": s[:160]})
                if len(out) >= limit:
                    return out
    return out


# ---------------------------------------------------------------- villagers

@functools.lru_cache(maxsize=1)
def villagers():
    names = textmod.read_table("/Script/Str/STR_NNpc_name.umsbt")
    habit = textmod.read_table("/Script/Str/STR_NNpc_habit.umsbt")
    by_habit = {l: s for l, k, s in habit["en"]}
    out = []
    for label, idx, name in names["en"]:
        if not label or not name:
            continue
        model = "/Npc/Normal/Model/%s.bcres" % label
        if not rom.exists(model):
            continue
        sp = re.match(r"[a-z]+", label).group(0)
        out.append({"id": label, "name": name, "species": SPECIES.get(sp, sp), "catchphrase": by_habit.get(label, ""),
                    "model": model})
    return out


# ---------------------------------------------------------------- models and textures

def list_models(prefix, q="", limit=300):
    q = q.lower()
    out = []
    for p in rom.glob_prefix(prefix, ".bcres"):
        if q in p.lower():
            out.append(p)
            if len(out) >= limit:
                break
    return out


def model_textures(path):
    d = rom.read(path)
    return [{"name": t.name, "w": t.w, "h": t.h, "fmt": cgfx.FORMATS.get(t.fmt, t.fmt), "mips": t.mips,
             "supported": texfmt.supported(t.fmt)} for t in cgfx.textures(d)]


def texture_rows(path, name, data=None):
    d = data or rom.read(path)
    for t in cgfx.textures(d):
        if t.name == name:
            return texfmt.decode_texture(d, t)
    raise KeyError(name)


def mesh_json(path, model=0):
    """a game model as JSON for the browser viewer: parts [{positions, normals, uvs, indices, texture}] + textures PNG"""
    from .features.textures import to_png
    d = rom.read(path)
    tex = {t.name: t for t in cgfx.textures(d)}
    parts = []
    for shp, mat, texs in cgfx.meshes(d, model):
        try:
            verts, tris = cgfx.read_geometry(d, shp, model)
            verts = skeleton.pose_vertices(d, shp, verts, model)
        except Exception:
            continue
        cols = [t for t in texs if t in tex and texfmt.supported(tex[t].fmt)
                and not any(k in t.lower() for k in ("mask", "lut"))]
        parts.append({
            "positions": [c for v in verts for c in v["pos"][:3]],
            "normals": [c for v in verts for c in (v.get("normal") or (0, 1, 0))[:3]],
            "uvs": [c for v in verts for c in (v.get("uv") or (0, 0))[:2]],
            "indices": tris, "texture": cols[0] if cols else None, "material": mat})
    textures = {}
    for part in parts:
        n = part["texture"]
        if n and n not in textures:
            rows = texfmt.decode_texture(d, tex[n])
            textures[n] = base64.b64encode(to_png(rows)).decode()
    return {"parts": parts, "textures": textures}


# clothing items hold only a texture; this is how they look on the player's body models
WORN_ON = [
    ("tops_", [("Short sleeves", "/Player/tops_mdl/shtN.bcres"), ("Long sleeves", "/Player/tops_mdl/shtL.bcres"),
               ("Hooded", "/Player/tops_mdl/shtH.bcres"), ("Dress", "/Player/tops_mdl/onpN.bcres"), ("Long dress", "/Player/tops_mdl/onpL.bcres")]),
    ("btms_", [("Pants", "/Player/btms_mdl/pntH.bcres"), ("Short pants", "/Player/btms_mdl/pntL.bcres"), ("Skirt", "/Player/btms_mdl/skt.bcres")]),
    ("botH_", [("Boots", "/Player/shoe_mdl/botH.bcres")]), ("botL_", [("Shoes", "/Player/shoe_mdl/botL.bcres")]),
    ("sock_", [("Legs", "/Player/legs_mdl/Common.bcres")]),
]


def preview_models(path):
    """[(label, model path)] to show an item texture on, or [] when the item brings its own model"""
    name = path.rsplit("/", 1)[-1]
    if not path.startswith("/Item/Model/"):
        return []
    for prefix, models in WORN_ON:
        if name.startswith(prefix):
            return [[l, p] for l, p in models if rom.exists(p)]
    return []
