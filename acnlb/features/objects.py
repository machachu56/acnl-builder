"""Outdoor objects: things placed in the town that the runtime draws itself (props), e.g. a drivable car.

project.json:
  objects [{"id": "car", "name": "My car", "kind": "vehicle",
            "model": {"car": "sports_car", "color": 0} | {"model_file": "<asset>", "front": -1, "seat": [x, y, z]},
            "start": {"near": "house" | "town_hall" | "station" | "tiles", "dx": 3, "dz": 0}, "yaw": 0,
            "scale": 1.0, "sound": "sporty" | "classic", "handling": {"max_speed": 330, "accel": 240, "turn": 2.4, "grip": 10}}]

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
        read = (lambda name: open(project.asset_path(b.proj["id"], name), "rb").read())
        built = vehicle.build(spec, read)
        d = "veh_%s/" % oid
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
        vehicles.append(entry)
        b.note("vehicle %s: %d triangles, %d wheel(s), lights, %d sounds" % (oid, built["triangles"], len(m["wheels"]), len(built["sounds"])))
        if not m["wheels"]:
            b.warn("%s: no wheels found in the model (they will not turn)" % oid)
    if vehicles:
        b.add("fgcol.bin", item_radii())
