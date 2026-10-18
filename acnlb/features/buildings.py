"""Custom town buildings, and changes to the game's own ones.

{"id": "baiso", "name": "Baisodrome", "slot": 77, "model": "sobj_baiso",
 "x": null, "y": null, "dx": 4, "dy": 7, "rect": null, "scene": 65, "interior": "<interior id>|null",
 "style": {...exterior style...}, "map_name": {"en": "..."}, "map_icon": {"shape": "heart", ...},
 "hide_furniture": true}

The building takes over the slot of a game building type (see exterior.BASES); its model, textures and
data files are looked up under /Strc/sobj/<model>/. Inside, the project's interior (if any) is switched on.

The game's own buildings (project "game_buildings", see gamebuildings.py):
{"slot": 78, "move": [x, y] | null, "remove": false, "interior": "<interior id>" | null, "map_name": {"en": "..."}}
Their look is repainted in Textures (category Buildings, /Strc/sobj/<model>).
"""
import re

from .. import env, exterior, gamebuildings, paintx, project, rom, texfmt, uipatch
from . import textures as texmod

env.setup_path()
from modkit import cgfx, etc1, msbt  # noqa: E402

MODEL_RE = re.compile(r"^sobj_[A-Za-z0-9]{1,7}$")       # no longer than the model name it replaces
SCENE_NOOKS = 0x41
# Spare IDs a building can be *added* under without replacing anything the player builds: the game's 20 signboard
# objects. The runtime plugin answers every lookup for such an ID as the base building would (see the plugin).
# (IDs >= 0xFC cannot be used: the game treats them as "no building".)
SPARE_SLOTS = tuple(range(0x6B, 0x7F))


def variant_of(bld):
    return "b_" + bld["id"]


def rename_strings(data, renames):
    """replace whole NUL-terminated strings in place (new names must not be longer)"""
    out = bytearray(data)
    for old, new in renames:
        o, n = old.encode() + b"\0", new.encode() + b"\0"
        assert len(n) <= len(o), (old, new)
        pos = 0
        while True:
            i = out.find(o, pos)
            if i < 0:
                break
            if i == 0 or not (chr(out[i - 1]).isalnum() or out[i - 1] == ord("_")):
                out[i:i + len(o)] = n.ljust(len(o), b"\0")
            pos = i + 1
    return bytes(out)


def stage_model(b, bld, ext, base):
    """sobj_<model>.bcres with the generated geometry, its data file and season textures"""
    src, name = base["model"], bld["model"]
    d = rom.read("/Strc/sobj/%s/%s.bcres" % (src, src))
    d = rename_strings(d, [(src, name)])
    geometry = {base["body_shape"]: (ext.body.verts, ext.body.tris)}
    if base["glow_shape"] is not None:
        geometry[base["glow_shape"]] = (ext.glow.verts, ext.glow.tris) if ext.glow else cgfx.EMPTY
    d = cgfx.set_geometry(d, geometry)
    b.put("/Strc/sobj/%s/%s.bcres" % (name, name), d)
    b.put("/Strc/data/%s.bin" % name, rom.read("/Strc/data/%s.bin" % src))

    overlay = None
    if ext.s.get("overlay"):
        f = project.asset_path(b.proj["id"], ext.s["overlay"])
        overlay = texmod.load_png(f)
    for season in ("season00", "season09"):
        p = "Textures/%s/%s.bcres" % (season, season)
        data = rom.read("/Strc/sobj/%s/%s" % (src, p))
        winter = season == "season09"
        new = {}
        tex = {t.name: t for t in cgfx.textures(data)}
        body = ext.paint_body(winter, overlay).rows()
        # ETC1 without the gloss alpha: half the size, to fit the building's memory budget
        bt = tex[base["body_tex"]]
        new[bt.name] = (len(body[0]), len(body), bt.mips, texfmt.encode_cached(body, 12, bt.mips), 12)
        mask = ext.paint_body_mask().rows()
        mt = tex[base["mask_tex"]]
        new[mt.name] = (len(mask[0]), len(mask), mt.mips, texfmt.encode_cached(mask, 12, mt.mips))
        if base["two_shape"]:
            for key, rows in (("glow_tex", ext.paint_glow().rows()), ("glow_mask", ext.paint_glow_mask().rows())):
                t = tex[base[key]]
                new[t.name] = (t.w, t.h, t.mips, texfmt.encode_cached(rows, t.fmt, t.mips))
        b.put("/Strc/sobj/%s/%s" % (name, p), cgfx.rebuild_textures(data, new))


SPARE_ICON_FRAMES = [15] + list(range(16, 4 * uipatch.ICON_ROWS))     # 15 is empty in the game's sheet, 16.. are added


def stage_map(b, bld, base, fresh=False):
    """the name and icon on the town map (a new ID shares its alias' label and icon: see README)"""
    if fresh:
        if bld.get("share_map"):
            fresh = False                      # rename the alias type's label/icon (the real police station too)
        else:
            return stage_added_icon(b, bld)
    MAP_NAMES = "/Script/Str/STR_Map_name.umsbt"
    names = bld.get("map_name") or {}
    if any(names.values()) or bld.get("name"):
        names = dict(names)
        names.setdefault("en", bld.get("name", ""))
        parts = msbt.umsbt_split(b.game(MAP_NAMES))
        out = []
        for i, part in enumerate(parts):
            lang = msbt.LANGS[i] if i < len(msbt.LANGS) else None
            m = msbt.Msbt(part)
            m.set_text(base.get("map_label", 0), names.get(lang) or names["en"])
            out.append(m.build())
        b.put(MAP_NAMES, msbt.umsbt_join(out))
    ic = bld.get("map_icon")
    if ic and ic.get("image"):
        from modkit.paint import resize
        f = project.asset_path(b.proj["id"], ic["image"])
        rows = texmod.load_png(f)
        if (len(rows[0]), len(rows)) != (16, 16):
            rows = [[tuple(int(v) for v in p) for p in r] for r in resize(rows, 16, 16)]
        cells = {"tc_mpi_A_00": rows, "tc_mpi_A_01": uipatch.highlight_rows(rows)}
        b.put(uipatch.MAP, uipatch.patch_map(b.game(uipatch.MAP), cells))
    elif ic and ic.get("shape", "none") not in ("none", "image"):
        fill = paintx.rgba(ic.get("fill", "#f6548c"))
        outline = paintx.rgba(ic.get("outline", "#78143c"))
        cells = {"tc_mpi_A_00": uipatch.icon_rows(ic["shape"], fill, (255, 214, 230, 255), outline),
                 "tc_mpi_A_01": uipatch.icon_rows(ic["shape"], (255, 0, 255, 255), (255, 200, 255, 255), (255, 255, 255, 255))}
        b.put(uipatch.MAP, uipatch.patch_map(b.game(uipatch.MAP), cells))


def stage_added_icon(b, bld):
    """an added building gets its own cell of the map's icon sheet (the plugin points its map icon there)"""
    ic = bld.get("map_icon") or {}
    if not ic.get("image") and ic.get("shape", "none") in ("none", "image"):
        return None
    used = b.cfg.setdefault("icon_frames", [])
    if len(used) >= len(SPARE_ICON_FRAMES):
        b.warn("%s: the map's icon sheet has room for %d custom icon(s) of added buildings; this one keeps the base building's icon"
               % (bld["id"], len(SPARE_ICON_FRAMES)))
        return None
    frame = SPARE_ICON_FRAMES[len(used)]
    used.append(frame)
    if ic.get("image"):
        from modkit.paint import resize
        rows = texmod.load_png(project.asset_path(b.proj["id"], ic["image"]))
        if (len(rows[0]), len(rows)) != (16, 16):
            rows = [[tuple(int(v) for v in p) for p in r] for r in resize(rows, 16, 16)]
        cells = {"tc_mpi_A_00": rows, "tc_mpi_A_01": uipatch.highlight_rows(rows)}
    else:                                           # one of the built-in shapes
        fill, outline = paintx.rgba(ic.get("fill", "#f6548c")), paintx.rgba(ic.get("outline", "#78143c"))
        cells = {"tc_mpi_A_00": uipatch.icon_rows(ic["shape"], fill, (255, 214, 230, 255), outline),
                 "tc_mpi_A_01": uipatch.icon_rows(ic["shape"], (255, 0, 255, 255), (255, 200, 255, 255), (255, 255, 255, 255))}
    b.put(uipatch.MAP, uipatch.patch_map(uipatch.expand_icon_sheet(b.game(uipatch.MAP)), cells, at=uipatch.frame_cell(frame)))
    bld["_icon_frame"] = frame
    return frame


def compile(b):
    blds = b.proj["buildings"]
    used_slots = {}
    for bld in blds:
        if not re.match(r"^[a-z][a-z0-9_]{1,15}$", bld["id"]):
            raise ValueError("building id %r: lowercase letters, digits, _" % bld["id"])
        style = bld.get("style") or {}
        ext = exterior.build(style)
        base = ext.base
        slot = int(bld.get("slot", base["slot"]))
        fresh = slot != base["slot"]
        if fresh and slot not in SPARE_SLOTS:
            raise ValueError("%s: slot %#x is neither the base building's own nor a spare slot (%#x..%#x)" % (bld["id"], slot, SPARE_SLOTS[0], SPARE_SLOTS[-1]))
        if slot in used_slots:
            raise ValueError("%s and %s both want slot %#x" % (bld["id"], used_slots[slot], slot))
        used_slots[slot] = bld["id"]
        model = bld.get("model") or ("sobj_" + bld["id"][:7])
        if not MODEL_RE.match(model):
            raise ValueError("%s: model name %r must look like sobj_xxxxx" % (bld["id"], model))
        bld["model"] = model
        stage_model(b, bld, ext, base)
        stage_map(b, bld, base, fresh)
        scene = bld.get("scene")
        if bld.get("interior") and scene is None:
            scene = SCENE_NOOKS                      # the custom room replaces the one of Nook's Homes
        if not bld.get("interior") and bld.get("scene") is None:
            b.warn("%s has no interior of its own: inside it is still the %s (officer included). Give it one in Buildings > Inside." % (bld["id"], base["label"].split(" (")[0].lower()))
        entry = {"id": bld["id"], "slot": slot, "model": model, "scene": int(scene) if scene is not None else None,
                 "room": int(bld.get("room", 48)), "x": bld.get("x"), "y": bld.get("y"),
                 "dx": bld.get("dx", 4), "dy": bld.get("dy", 7), "hide_furniture": bool(bld.get("hide_furniture", bool(bld.get("interior"))))}
        if fresh:
            entry["alias"] = base["slot"]               # shares the table rows of this building
            if bld.get("_icon_frame") is not None:
                entry["icon_frame"] = bld["_icon_frame"]
        if bld.get("rect"):
            entry["rect"] = bld["rect"]
        if any(t.get("variant") == bld["id"] for t in b.proj["text"]) or any(e.get("building") == bld["id"] for e in b.proj["events"]):
            entry["variant"] = variant_of(bld)
        for k in ("x", "y", "scene"):
            if entry[k] is None:
                del entry[k]
        b.cfg["buildings"].append(entry)
    compile_game(b)


def game_id(slot):
    return "game_%02x" % slot


def game_edits(proj):
    """the project's changes to the game's buildings that do something, as {id, slot, kind, ...}"""
    out = []
    for g in proj.get("game_buildings") or []:
        slot = int(g.get("slot", -1))
        k = gamebuildings.kind(slot)
        if not k:
            raise ValueError("building ID %#x cannot be changed by a mod" % slot)
        e = dict(g, id=game_id(slot), slot=slot, kind=k)
        if not k.get("interior"):
            e["interior"] = None
        if not k.get("remove"):
            e["remove"] = False
        if not k.get("move"):
            e["move"] = None
        if k.get("map_label") is None:
            e["map_name"] = {}
        if e.get("remove") or e.get("move") or e.get("interior") or any((e.get("map_name") or {}).values()):
            out.append(e)
    return out


def compile_game(b):
    """the game's own buildings: moved, removed, renamed on the map, another interior (plugin [building] with game = 1)"""
    seen = set()
    for e in game_edits(b.proj):
        slot, k = e["slot"], e["kind"]
        if slot in seen:
            raise ValueError("%s is changed twice" % k["label"])
        seen.add(slot)
        entry = {"id": e["id"], "slot": slot, "game": 1}
        if e.get("remove"):
            entry["remove"] = 1
        elif e.get("move"):
            x, y = (int(v) for v in e["move"])
            if not (16 <= x < 96 and 16 <= y < 80):
                raise ValueError("%s: tile %d, %d is outside the playable town (16..95, 16..79)" % (k["label"], x, y))
            entry["x"], entry["y"] = x, y
        if e.get("interior"):
            entry.update(scene=gamebuildings.NOOKS_SCENE, room=48, hide_furniture=1)
        names = {l: v for l, v in (e.get("map_name") or {}).items() if v}
        if names:
            MAP_NAMES = "/Script/Str/STR_Map_name.umsbt"
            parts = msbt.umsbt_split(b.game(MAP_NAMES))
            out = []
            for i, part in enumerate(parts):
                lang = msbt.LANGS[i] if i < len(msbt.LANGS) else None
                m = msbt.Msbt(part)
                text = names.get(lang) or names.get("en")
                if text:
                    m.set_text(k["map_label"], text)
                out.append(m.build())
            b.put(MAP_NAMES, msbt.umsbt_join(out))
        b.cfg["buildings"].append(entry)
        what = ["removed" if e.get("remove") else "moved to %d, %d" % tuple(e["move"]) if e.get("move") else None,
                "interior %s" % e["interior"] if e.get("interior") else None, "renamed" if names else None]
        b.note("%s: %s" % (k["label"], ", ".join(w for w in what if w)))
        if e.get("remove") or e.get("move"):
            b.warn("%s is %s in the town's save: removing the mod does not undo it" % (k["label"], "removed" if e.get("remove") else "moved"))
