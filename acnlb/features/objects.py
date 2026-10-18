"""Outdoor objects: things placed in the town that the runtime draws itself (props), e.g. a drivable car.

project.json:
  objects [{"id": "car", "name": "My car", "kind": "vehicle",
            "model": {"car": "sports_car", "color": 0} | {"model_file": "<asset>", "front": -1, "seat": [x, y, z]},
            "start": {"near": "house" | "town_hall" | "station" | "tiles", "dx": 3, "dz": 0}, "yaw": 0,
            "scale": 1.0, "sound": "sporty" | "classic", "handling": {"max_speed": 330, "accel": 240, "turn": 2.4, "grip": 10}}]

  "appear": "item" | "parked", "give": {"pockets": false, "mail": true}, "letter": {"header": "To ,", "body": "...", "footer": "..."}

appear "item" (the default): the car is the furniture item of the same model (the game's sports car, compact car...):
dropped on the ground outside, the item becomes the car; holding Y next to the parked car turns it back into the item.
The first time the mod runs in a town the item is given: in the pockets and/or attached to a letter (only explained,
without the item, when the pockets already got it).
appear "parked": the car is simply parked in town from the start.
A car remembers where it was last parked; changing its start (or yaw) in the builder moves it back to the new start.

Each vehicle becomes veh_<id>/{car.apm, dust.apm, *.wav} in the mod and a [vehicle] section of acnlb.cfg; the plugin
(plugin/vehicles.h) does the rest. fgcol.bin (the collision radius of every field item, from your dump's
/Fg/Param/Fg.bin) lets vehicles bump into trees and rocks.
"""
import re
import struct
import zlib

from .. import project, rom, vehicle

ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,15}$")
STARTS = ("house", "town_hall", "station", "tiles")


# (a letter line holds about 27 characters, 6 lines show at once)
LETTER = {"header": "To ,", "body": "Your new car is here!\nDrop it on the ground\noutside, then press A\nbeside it to drive. Hold Y\nbeside it to put it away.\nDrive safely!",
          "footer": "Your car dealer"}
HEADER_CHARS, BODY_CHARS, FOOTER_CHARS = 32, 192, 32


def letter_bin(letter, has_item):
    """header, body, footer as the game keeps them in a letter (UTF-16 with room for a terminator), then where
    the receiver's name goes in the header: before a "," that follows a space ("To ," -> 3), 0 for nowhere"""
    lt = dict(LETTER, **(letter or {}))
    if not has_item:
        lt["body"] = lt["body"].replace("Your new car is here!", "It's in your pockets!")
    out = b""
    for key, n in (("header", HEADER_CHARS), ("body", BODY_CHARS), ("footer", FOOTER_CHARS)):
        t = lt[key].replace("\r", "")[:n]
        out += t.encode("utf-16le").ljust((n + 1) * 2, b"\0")
    h = lt["header"]
    pos = h.find(" ,")
    out += bytes([pos + 1 if 0 <= pos < 31 else 0])
    return out


def item_radii():
    """u16 collision radius per field item id (256): the first u16 of each 16-byte record of /Fg/Param/Fg.bin"""
    fg = rom.read("/Fg/Param/Fg.bin")
    out = [struct.unpack_from("<H", fg, i * 16)[0] if i * 16 + 2 <= len(fg) else 0 for i in range(256)]
    return struct.pack("<256H", *out)


def compile(b):
    objs = [o for o in b.proj.get("objects", []) if o.get("enabled", True)]
    if not objs:
        return
    vehicles = b.cfg.setdefault("vehicles", [])
    for o in objs:
        oid = o.get("id", "")
        if not ID_RE.match(oid):
            raise ValueError("object id %r: lowercase letters, digits, _ (16 at most, starting with a letter)" % oid)
        if o.get("kind", "vehicle") != "vehicle":
            b.warn("%s: only vehicles are supported so far" % oid)
            continue
        if len(vehicles) >= 4:
            b.warn("%s: at most 4 vehicles in a mod; this one is left out" % oid)
            continue
        spec = dict(o.get("model") or {"car": "sports_car"})
        spec["scale"] = o.get("scale", spec.get("scale", 1.0))
        spec["sound"] = o.get("sound", "sporty")
        appear = o.get("appear", "item")
        give = o.get("give") or {"pockets": False, "mail": True}
        model = vehicle.GAME_CARS.get(spec.get("car", "sports_car")) if not spec.get("model_file") else None
        item = model["item"] if model else 0
        if appear == "item" and not item:
            b.warn("%s: an imported model has no item of the game to make it appear: it is parked in town instead" % oid)
            appear = "parked"
        spec["appear"] = appear
        read = (lambda name: open(project.asset_path(b.proj["id"], name), "rb").read())
        built = vehicle.build(spec, read)
        d = "veh_%s/" % oid
        if appear == "item" and give.get("mail"):
            b.add(d + "letter.bin", letter_bin(o.get("letter"), not give.get("pockets")))
        b.add(d + "car.apm", built["apm"])
        b.add(d + "dust.apm", built["dust"])
        for name, data in built["sounds"].items():
            b.add(d + name, data)
        m = built["meta"]
        st = o.get("start") or {}
        near = st.get("near", "house")
        if near not in STARTS:
            near = "house"
        h = o.get("handling") or {}
        start = "%s, %s, %s" % (near, st.get("dx", 3), st.get("dz", 0))
        entry = {"id": oid, "dir": d, "length": m["length"], "width": m["width"], "height": m["height"], "front": m["front"],
                 "wheel_radius": m["wheel_radius"], "wheels": m["wheels"], "steer": m["steer"], "seat": m["seat"],
                 "head": m["head"], "tail": m["tail"], "brake": m["brake"], "beam": m["beam"], "beam_length": m["beam_length"],
                 "prompt": m["prompt"], "start": start, "yaw": o.get("yaw", 0),
                 "start_rev": zlib.crc32(("%s|%s" % (start, o.get("yaw", 0))).encode()) & 0x7FFFFFFF,
                 "max_speed": h.get("max_speed", 330), "accel": h.get("accel", 240), "turn": h.get("turn", 2.4), "grip": h.get("grip", 10)}
        if appear == "item":
            entry.update(item=item, give_pockets=int(bool(give.get("pockets"))), give_mail=int(bool(give.get("mail"))))
        vehicles.append(entry)
        b.note("vehicle %s: %d triangles, %d wheel(s), lights, %d sounds; %s" % (oid, built["triangles"], len(m["wheels"]), len(built["sounds"]),
               "parked in town" if appear != "item" else "appears from item %#x (%s)" % (item, ", ".join(k for k in ("pockets", "mail") if give.get(k)) or "not given")))
        if not m["wheels"]:
            b.warn("%s: no wheels found in the model (they will not turn)" % oid)
    if vehicles:
        b.add("fgcol.bin", item_radii())
