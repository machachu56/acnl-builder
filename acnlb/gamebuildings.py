"""The game's own town buildings: what a mod may do with each (move, remove, rename on the map, give another interior),
and the ones standing in the player's town, read from the save.

Building IDs and model names are the game's table at 0x95a6e8 (const char *name[0xFC]); the interior scene per ID is at
0x88a5d8 (0xA5 = none), the footprint (s8 x0, y0, x1, y1 around the building's tile) at 0x88a7d4. The save keeps the town's
buildings at +0x4be80: u8 count at +4, then 56 entries of {u16 id, u8 x, u8 y} from +8 (0xFC = empty); the town grid is
112 x 96 tiles, the playable part from 16, 16.

Moving or removing writes the town's building list, which the game saves: removing the mod later does not put a building
back where it was. Public works projects can be rebuilt in game; the others cannot, so only projects can be removed.
"""
import functools
import os
import struct

from . import build

TOWN_BUILDINGS = 0x4be80
EMPTY = 0xFC
NAME_TABLE, SCENE_TABLE, RECT_TABLE = 0x95a6e8, 0x88a5d8, 0x88a7d4
NOOKS_SCENE = 65                         # project interiors take over this scene (as for added buildings)

# map_label: index of the name in /Script/Str/STR_Map_name (shared by every building of that type); interior: has a door
KINDS = {
    0x4C: dict(label="Police station (classic)", group="Services", map_label=0, move=True, interior=True),
    0x4D: dict(label="Police station (modern)", group="Services", map_label=0, move=True, interior=True),
    0x4E: dict(label="Café (The Roost)", group="Services", map_label=1, move=True, interior=True),
    0x4F: dict(label="Reset Center entrance", group="Services", move=True),
    0x50: dict(label="Town hall (style A)", group="Town hall & station", map_label=2, interior=True),
    0x51: dict(label="Town hall (style B)", group="Town hall & station", map_label=2, interior=True),
    0x52: dict(label="Town hall (style C)", group="Town hall & station", map_label=2, interior=True),
    0x53: dict(label="Town hall (style D)", group="Town hall & station", map_label=2, interior=True),
    0x54: dict(label="Train station (style A)", group="Town hall & station", map_label=3),
    0x55: dict(label="Train station (style B)", group="Town hall & station", map_label=3),
    0x56: dict(label="Train station (style C)", group="Town hall & station", map_label=3),
    0x57: dict(label="Train station (style D)", group="Town hall & station", map_label=3),
    0x58: dict(label="Re-Tail", group="Services", map_label=4, move=True, interior=True),
    0x5B: dict(label="Bulletin board", group="Services", move=True),
    0x5F: dict(label="Campsite tent", group="Services", map_label=33, move=True, interior=True),
}
# names as the game writes them (STR_Fobj_name), by model
PWP_NAMES = {
    "bench2x1": "Yellow bench", "bench_pla": "Blue bench", "bench_plain": "Wood bench", "bench_metal": "Metal bench",
    "bench_log": "Log bench", "bench_mdn": "Modern bench", "bench_wst": "Fairy-tale bench", "bench_jpn": "Zen bench",
    "flower_bed": "Flower bed", "drinking": "Drinking fountain", "screen": "Instrument shelter", "sandbox": "Sandbox",
    "trash": "Garbage can", "pipe_Y": "Pile of pipes", "well": "Water well", "fountain": "Fountain", "tire": "Tire toy",
    "grobejungle": "Climbing frame", "clock_park": "Park clock", "clock_mdn": "Modern clock", "clock_wst": "Fairy-tale clock",
    "clock_jpn": "Zen clock", "lamp": "Streetlight", "lamp_globe": "Round streetlight", "lamp_retro": "Street lamp",
    "lamp_mdn": "Modern streetlight", "lamp_wst": "Fairy-tale streetlight", "lamp_jpn": "Zen streetlight",
    "arch_balloon": "Balloon arch", "arch_flower": "Flower arch", "campsite": "Campsite", "picnic": "Picnic blanket",
    "hammock": "Hammock", "campfire": "Fire pit", "bed_outdoor": "Camping cot", "bed_garden": "Outdoor chair", "torch": "Torch",
    "karesansui": "Zen garden", "spa": "Hot spring", "geyser": "Geyser", "goddess": "Statue fountain", "monument": "Stone tablet",
    "pump": "Water pump", "wisteria": "Wisteria trellis", "bell_wst": "Bell", "bell_jpn": "Zen bell", "scarecrow": "Scarecrow",
    "rice": "Rack of rice", "fence": "Fence", "waiting": "Bus stop", "fireplug": "Fire hydrant", "trafic_light": "Traffic signal",
    "myd_sign": "Custom-design sign", "myd_signboard": "Face-cutout standee", "sign_A01": "Caution sign",
    "sign_B01": "Do-not-enter sign", "sign_C01": "Yield sign", "art_A": "Cube sculpture", "art_B": "Archway sculpture",
    "art_C": "Chair sculpture", "ilm_heart": "Illuminated heart", "ilm_arch": "Illuminated arch", "ilm_clock": "Illuminated clock",
    "ilm_tower": "Illuminated tree", "stadium_light": "Stadium light", "aurora": "Video screen", "excavator": "Drilling rig",
    "parabola": "Parabolic antenna", "solar": "Solar panel", "windturbine": "Wind turbine", "windmill": "Windmill",
    "lighthouse": "Lighthouse", "landmark": "Tower", "stonehenge": "Stonehenge", "totem": "Totem pole", "moai": "Moai statue",
    "pyramid": "Pyramid", "sphinx": "Sphinx", "topiary_A": "Round topiary", "topiary_B": "Square topiary",
    "topiary_C": "Tulip topiary", "clock_flower": "Flower clock", "barricade_L": "Barricade (left)", "barricade_R": "Barricade (right)",
}


@functools.lru_cache(maxsize=1)
def game_tables():
    """{id: {"model", "scene", "rect"}} from the game's tables (your dump)"""
    from . import gamemap
    gm = gamemap.load()
    out = {}
    for i in range(0xFC):
        p = gm.u32(NAME_TABLE + 4 * i)
        o = gm.off(RECT_TABLE + 4 * i)
        out[i] = {"model": gm.cstr(p) if p else None, "scene": gm.code[gm.off(SCENE_TABLE + i)],
                  "rect": [b - 256 if b >= 128 else b for b in gm.code[o:o + 4]]}
    return out


def kind(slot):
    """what can be done with the building of this ID (None: nothing)"""
    if slot in KINDS:
        return dict(KINDS[slot], slot=slot)
    if 0x90 <= slot <= 0xFB:                                    # public works projects
        model = game_tables()[slot]["model"] or ""
        key = model[len("fobj_"):]
        if key.startswith("bridge_"):                           # bridges belong to their river: nothing to do but repaint them
            return None
        label = PWP_NAMES.get(key) or key.replace("_", " ").capitalize()
        return dict(label=label, group="Public works projects", move=True, remove=True, slot=slot)
    return None


def kinds():
    """every editable building type, for the editor"""
    out = []
    for slot in list(KINDS) + list(range(0x90, 0xFC)):
        k = kind(slot)
        if k:
            t = game_tables()[slot]
            out.append(dict(k, model=t["model"], rect=t["rect"], has_door=t["scene"] != 0xA5 and t["scene"] != 165))
    return out


def town_buildings(path=None):
    """the buildings in the player's town: [{"slot", "x", "y"}], or None without a save"""
    path = path or build.save_path()
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        d = f.read()
    if len(d) < TOWN_BUILDINGS + 8 + 56 * 4:
        return None
    out = []
    for i in range(56):
        bid, x, y = struct.unpack_from("<HBB", d, TOWN_BUILDINGS + 8 + i * 4)
        if bid < EMPTY:
            out.append({"slot": bid, "x": x, "y": y})
    return out


def model_files(slot):
    """(model .bcres, [texture .bcres]) of a building ID, or None"""
    from . import rom
    model = game_tables()[slot]["model"]
    if not model:
        return None
    kind_dir = "/Strc/%s/" % model.split("_")[0]
    folder = kind_dir + model + "/"
    path = folder + model + ".bcres"
    if not rom.exists(path):                     # some come in stages (the town hall: sobj_officeA00, 01...): the first
        found = [p for p in rom.glob_prefix(kind_dir + model, ".bcres") if "/Textures/" not in p]
        if not found:
            return None
        path = sorted(found)[0]
        folder = path.rsplit("/", 1)[0] + "/"
    tex = [p for p in rom.glob_prefix(folder + "Textures/", ".bcres") if p.rsplit("/", 1)[-1] == "season00.bcres"]
    return path, tex
