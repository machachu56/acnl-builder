"""Furniture outside: furniture dropped on the ground in the town shows as its own 3D model instead of the game's leaf.

project.json:
  furniture {"enabled": true, "which": "all" | "list", "list": [item ids], "exclude": [item ids],
             "solid": true, "face": "player" | "south", "pickup": "game" | "hold"}

which "all": every furniture item of the game (1,904, gyroids too) but those in exclude; "list": only those in list.
solid: the player walks around it. face "player": a dropped piece turns to face the player who dropped it; "south": all
face the camera. pickup "game": the game's own Y (the item stays in the town's grid under the model); "hold": hold Y beside it.

Each item becomes ftr/<item id, 4 hex digits>.apm (its model from /Item/Model/<name>.bcres, posed), ftr/items.bin says
which items have one and their size, and a [furniture] section of acnlb.cfg turns it on; the plugin (plugin/furniture.h)
does the rest. Converted models are cached in .cache/ftr-<converter hash>/ (the first export of all of them takes ~30 s).

Item ID = 0x2000 + its index in /Item/Param/Item.bin (= its index in STR_Item_name). The game's model name of an item is in
the table at 0x871680 of the executable (one const char * per item from 0x234C: wallpaper, carpets, clothes, furniture).
"""
import functools
import hashlib
import json
import os
import re
import struct

from .. import env, gamemap, propmesh

FIRST, LAST = 0x295C, 0x30CB                    # furniture: the gyroids (0x295C...) to the instruction manual
MODEL_TABLE, MODEL_TABLE_FIRST = 0x871680, 0x234C
CONVERT = 1                                     # bump when converted() changes what it makes


@functools.lru_cache(maxsize=1)
def catalog():
    """[{"id", "name", "model"}] of every furniture item, by ID"""
    from .text import read_table
    code, ex = gamemap._read_code()
    base = ex.text_addr

    def cstr(a):
        o = a - base
        return code[o:code.index(b"\0", o)].decode("ascii", "replace")
    names = read_table("/Script/Str/STR_Item_name.umsbt").get("en", [])
    out = []
    for item in range(FIRST, LAST + 1):
        ptr = struct.unpack_from("<I", code, MODEL_TABLE - base + (item - MODEL_TABLE_FIRST) * 4)[0]
        k = item - 0x2000
        name = re.sub(r"\{[^}]*\}", "", names[k][2]).strip() if k < len(names) else ""
        out.append({"id": item, "name": name or "item %#x" % item, "model": cstr(ptr)})
    return out


def model_path(entry):
    return "/Item/Model/%s.bcres" % entry["model"]


def _cache_dir():
    h = hashlib.sha1()
    for mod in ("propmesh.py", "skeleton.py", "texfmt.py"):
        h.update(open(os.path.join(env.ROOT, "acnlb", mod), "rb").read())
    h.update(b"%d" % CONVERT)
    return os.path.join(env.CACHE, "ftr-" + h.hexdigest()[:12])


def prop(entry):
    return propmesh.from_game_model(model_path(entry), pose=True)


def converted(entry, cache=None):
    """(.apm bytes, (half width, half depth, height)) of an item's model, from the cache when it is there"""
    cache = cache or _cache_dir()
    path = os.path.join(cache, entry["model"])
    try:
        with open(path + ".apm", "rb") as f:
            apm = f.read()
        with open(path + ".json") as f:
            size = tuple(json.load(f))
        return apm, size
    except (OSError, ValueError):
        pass
    p = prop(entry)
    lo, hi = p.bounds()
    size = (max(abs(lo[0]), abs(hi[0])), max(abs(lo[2]), abs(hi[2])), max(hi[1], 0.0))
    apm = p.apm()
    os.makedirs(cache, exist_ok=True)
    for ext, data in ((".apm", apm), (".json", json.dumps(size).encode())):
        with open(path + ext + ".tmp", "wb") as f:
            f.write(data)
        os.replace(path + ext + ".tmp", path + ext)
    return apm, size


def chosen(f):
    """the item IDs the project turns into models"""
    ids = [e["id"] for e in catalog()]
    if f.get("which") == "list":
        want = set(f.get("list") or [])
        return [i for i in ids if i in want]
    out = set(f.get("exclude") or [])
    return [i for i in ids if i not in out]


def compile(b):
    f = b.proj.get("furniture") or {}
    if not f.get("enabled"):
        return
    cars = {v.get("item") for v in b.cfg.get("vehicles", []) if v.get("item")}
    by_id = {e["id"]: e for e in catalog()}
    cache = _cache_dir()
    recs = [(0, 0, 0, 0)] * (LAST - FIRST + 1)
    n = failed = total = 0
    for item in chosen(f):
        if item in cars:                         # the car feature makes that one a car
            continue
        try:
            apm, (hx, hz, h) = converted(by_id[item], cache)
        except Exception as e:                   # one broken model must not stop the export
            failed += 1
            b.warn("furniture %#x (%s): its model could not be converted: %s" % (item, by_id[item]["name"], e))
            continue
        b.add("ftr/%04x.apm" % item, apm)
        total += len(apm)
        clamp = lambda v: max(1, min(255, int(v + 0.999)))
        recs[item - FIRST] = (1, clamp(hx), clamp(hz), clamp(h))
        n += 1
    if not n:
        b.warn("furniture outside is on, but no item is chosen")
        return
    b.add("ftr/items.bin", b"FTR1" + struct.pack("<HH", FIRST, len(recs)) + b"".join(bytes(r) for r in recs))
    b.cfg["furniture"] = {"enabled": 1, "dir": "ftr/", "solid": int(f.get("solid", True)), "face": f.get("face", "player"),
                          "pickup": f.get("pickup", "game")}
    b.note("furniture outside: %d item(s) with their model (%.1f MB before packing)%s" % (n, total / 2 ** 20,
           ", %d left out (no model)" % failed if failed else ""))


def preview(item):
    """an item's model for the 3D preview: viewer parts (texture PNG each), its size and footprint"""
    from .textures import to_png
    import base64
    e = next((x for x in catalog() if x["id"] == item), None)
    if not e:
        raise KeyError("not a furniture item: %#x" % item)
    p = prop(e)
    pngs, parts = {}, []
    for part in p.parts:
        if not part.tris:
            continue
        if part.tex not in pngs:
            rows = p.textures[part.tex][2] if 0 <= part.tex < len(p.textures) else [[(255, 255, 255, 255)]]
            pngs[part.tex] = base64.b64encode(to_png(rows)).decode()
        parts.append({"name": part.name, "positions": [c for v in part.verts for c in v[0]], "normals": [c for v in part.verts for c in v[1]],
                      "uvs": [c for v in part.verts for c in v[2]], "colors": [c / 255 for v in part.verts for c in v[3][:3]],
                      "indices": part.tris, "atlas": pngs[part.tex], "alpha": bool(part.flags & 1)})
    lo, hi = p.bounds()
    return {"parts": parts, "size": [round(hi[i] - lo[i], 1) for i in range(3)], "triangles": p.triangles(), "model": e["model"], "name": e["name"]}
