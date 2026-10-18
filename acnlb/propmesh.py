"""Prop meshes (.apm): 3D objects the runtime draws into the game's scene (see recomp runtime/props.h).

A prop comes from a model of the game (any .bcres of your dump, e.g. a piece of furniture) or from an imported
3D file (glTF/GLB, OBJ, STL, PLY: modkit.importer). Each mesh of the model becomes a part with its own texture.

    from_game_model(path)        -> Prop
    from_import(files)           -> Prop
    Prop.apm()                   -> bytes of the .apm file
"""
import math
import struct

from . import env, rom, texfmt

env.setup_path()
from modkit import cgfx  # noqa: E402


# part flags (see the runtime's props.h)
ALPHA_TEST, ADDITIVE, BLENDED, BILLBOARD, UNLIT = 1, 1 << 1, 2 << 1, 1 << 3, 1 << 4


class Part:
    def __init__(self, name, tex, flags=0):
        self.name, self.tex, self.flags = name, tex, flags
        self.pivot = None
        self.verts = []            # (pos, normal, uv, rgba)
        self.tris = []             # vertex indices into self.verts


class Prop:
    def __init__(self, name):
        self.name = name
        self.parts = []
        self.textures = []         # (w, h, rows of RGBA, wrap_s, wrap_t)

    # -- geometry helpers
    def bounds(self):
        ps = [v[0] for p in self.parts for v in p.verts]
        if not ps:
            return (0, 0, 0), (0, 0, 0)
        return tuple(min(c[i] for c in ps) for i in range(3)), tuple(max(c[i] for c in ps) for i in range(3))

    def transform(self, fn):
        """apply fn(pos, normal) -> (pos, normal) to every vertex"""
        for p in self.parts:
            p.verts = [(*fn(v[0], v[1]), v[2], v[3]) for v in p.verts]

    def scale(self, s):
        self.transform(lambda pos, n: (tuple(c * s for c in pos), n))

    def rotate_y(self, deg):
        a = math.radians(deg)
        ca, sa = math.cos(a), math.sin(a)
        rot = lambda v: (v[0] * ca + v[2] * sa, v[1], -v[0] * sa + v[2] * ca)
        self.transform(lambda pos, n: (rot(pos), rot(n)))

    def ground(self):
        """put the lowest point on y = 0 and centre x/z"""
        lo, hi = self.bounds()
        cx, cz = (lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2
        self.transform(lambda pos, n: ((pos[0] - cx, pos[1] - lo[1], pos[2] - cz), n))

    def triangles(self):
        return sum(len(p.tris) // 3 for p in self.parts)

    def apm(self):
        verts, idx, parts = [], [], []
        for p in self.parts:
            base = len(verts)
            first = len(idx)
            verts += p.verts
            idx += [base + i for i in p.tris]
            lo = [min(v[0][k] for v in p.verts) if p.verts else 0 for k in range(3)]
            hi = [max(v[0][k] for v in p.verts) if p.verts else 0 for k in range(3)]
            pivot = list(p.pivot) if getattr(p, "pivot", None) else [(a + b) / 2 for a, b in zip(lo, hi)]
            parts.append((first, len(p.tris), p.tex, pivot, p.flags))
        out = bytearray(b"APM1")
        out += struct.pack("<5I", len(verts), len(idx), len(parts), len(self.textures), 0)
        for w, h, rows, ws, wt in self.textures:
            out += struct.pack("<4I", w, h, ws, wt)
        for first, count, tex, pivot, flags in parts:
            out += struct.pack("<IIi3fI", first, count, tex, *pivot, flags)
        for pos, n, uv, rgba in verts:
            out += struct.pack("<8f4B", *pos, *n, *uv, *(max(0, min(255, int(round(c)))) for c in rgba))
        out += struct.pack("<%dI" % len(idx), *idx)
        for w, h, rows, ws, wt in self.textures:
            out += bytes(c for r in rows for px in r for c in px)
        return bytes(out)


def _norm(n):
    l = math.sqrt(sum(c * c for c in n)) or 1.0
    return tuple(c / l for c in n)


def material_alpha_tests(data, model=0):
    """{material name: alpha reference (0-255) or None}: the alpha test of each material of a model, read from the GPU commands
    the material carries (register 0x104: enable bit 0, function bits 4-6 (6 = greater), reference bits 8-15)"""
    mdl = cgfx.models(data)[model]
    u32 = lambda a: struct.unpack_from("<I", data, a)[0]
    mats = cgfx.dict_entries(data, cgfx._rel(data, mdl + 0xC0)) if u32(mdl + 0xBC) else []
    out = {}
    for i, (name, mo) in enumerate(mats):
        end = mats[i + 1][1] if i + 1 < len(mats) else min(len(data) - 8, mo + 0x800)
        out[name] = None
        for k in range(mo, end - 4, 4):
            h = u32(k + 4)
            if (h & 0xFFFF) == 0x0104 and (h >> 16) & 0xF:
                v = u32(k)
                if v & 1:
                    out[name] = (v >> 8) & 0xFF
                break
    return out


def from_game_model(path, model=0, retexture=None, skip_meshes=()):
    """a model of the game's RomFS (e.g. "/Item/Model/rmk_car_spt.bcres") as a prop; retexture = {texture name: rows}
    replaces textures (remake colours...); meshes whose material name is in skip_meshes are left out"""
    data = rom.read(path)
    texs = {t.name: t for t in cgfx.textures(data)}
    prop = Prop(path.rsplit("/", 1)[-1].rsplit(".", 1)[0])
    tex_index = {}

    def texture(name):
        if name not in tex_index:
            rows = (retexture or {}).get(name)
            t = texs[name]
            if rows is None:
                rows = texfmt.decode_texture(data, t)
            rows = [[tuple(int(c) for c in px) for px in r] for r in rows]
            tex_index[name] = len(prop.textures)
            prop.textures.append((len(rows[0]), len(rows), rows, 1, 1))
        return tex_index[name]

    alpha = material_alpha_tests(data, model)
    for shape, material, tnames in cgfx.meshes(data, model):
        if material in skip_meshes:
            continue
        verts, tris = cgfx.read_geometry(data, shape, model)
        tname = next((t for t in tnames if t in texs), None)
        ref = alpha.get(material)
        part = Part(material, texture(tname) if tname else -1, 0 if ref is None else 1 | (ref << 8))
        for v in verts:
            pos = tuple(v["pos"][:3])
            n = _norm(v.get("normal", (0, 1, 0))[:3])
            uv = v.get("uv", (0, 0))
            col = v.get("color")
            rgba = tuple(c * 255 for c in col[:4]) if col else (255, 255, 255, 255)
            if len(rgba) == 3:
                rgba = rgba + (255,)
            part.verts.append((pos, n, (uv[0], 1.0 - uv[1]), rgba))     # PICA v goes up; texture rows go down
        part.tris = list(tris)
        prop.parts.append(part)
    return prop


# ---------------------------------------------------------------- vehicles: wheels, lights

def _components(part, tri_ids):
    """connected groups of the given triangles (sharing a vertex position)"""
    key = lambda v: tuple(round(c, 2) for c in part.verts[v][0])
    owner = {}
    parent = list(range(len(tri_ids)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for n, t in enumerate(tri_ids):
        for v in part.tris[t * 3:t * 3 + 3]:
            k = key(v)
            if k in owner:
                a, b = find(owner[k]), find(n)
                if a != b:
                    parent[a] = b
            else:
                owner[k] = n
    groups = {}
    for n, t in enumerate(tri_ids):
        groups.setdefault(find(n), []).append(t)
    return list(groups.values())


def find_wheels(prop, forward=-1):
    """wheels of a vehicle model (x = length, y = up, z = width): low, round, separate pieces on the outer sides.
    Returns [{part, tris, center (x, y, z), radius, front}] (front: on the half the car drives towards)"""
    lo, hi = prop.bounds()
    height, half_w = hi[1] - lo[1], max(abs(lo[2]), abs(hi[2]))
    wheels = []
    for pi, part in enumerate(prop.parts):
        cand = []
        for t in range(len(part.tris) // 3):
            ps = [part.verts[v][0] for v in part.tris[t * 3:t * 3 + 3]]
            if max(p[1] for p in ps) < lo[1] + height * 0.75 and min(abs(p[2]) for p in ps) > half_w * 0.5:
                cand.append(t)
        for g in _components(part, cand):
            ps = [part.verts[v][0] for t in g for v in part.tris[t * 3:t * 3 + 3]]
            xs, ys, zs = [p[0] for p in ps], [p[1] for p in ps], [p[2] for p in ps]
            sx, sy, sz = max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)
            if len(g) < 6 or sx < height * 0.25 or sy < height * 0.25 or abs(sx - sy) > 0.25 * max(sx, sy) or sz > half_w * 0.5:
                continue
            c = ((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2, (max(zs) + min(zs)) / 2)
            wheels.append({"part": pi, "tris": g, "center": c, "radius": max(sx, sy) / 2, "front": (c[0] < 0) == (forward < 0)})
    # a wheel is often several pieces (tyre, hub): one wheel per axle end
    merged = []
    for w in sorted(wheels, key=lambda w: -len(w["tris"])):
        for m in merged:
            if m["part"] == w["part"] and abs(m["center"][0] - w["center"][0]) < m["radius"] and abs(m["center"][1] - w["center"][1]) < m["radius"] \
                    and abs(m["center"][2] - w["center"][2]) < m["radius"] and (m["center"][2] < 0) == (w["center"][2] < 0):
                m["tris"] = m["tris"] + w["tris"]
                break
        else:
            merged.append(dict(w))
    return merged


def split_wheels(prop, forward=-1):
    """moves every wheel into a part of its own (named wheel_fl, wheel_fr, wheel_rl, wheel_rr; pivot = the wheel's centre)
    so the plugin can spin and steer it; returns the wheels found"""
    wheels = find_wheels(prop, forward)
    taken = {}
    for w in wheels:
        taken.setdefault(w["part"], set()).update(w["tris"])
    new_parts = []
    for w in wheels:
        src = prop.parts[w["part"]]
        side = "l" if (w["center"][2] < 0) == (forward < 0) else "r"
        p = Part("wheel_%s%s" % ("f" if w["front"] else "r", side), src.tex, src.flags)
        remap = {}
        for t in w["tris"]:
            for v in src.tris[t * 3:t * 3 + 3]:
                if v not in remap:
                    remap[v] = len(p.verts)
                    p.verts.append(src.verts[v])
                p.tris.append(remap[v])
        p.pivot = w["center"]
        new_parts.append(p)
    for pi, ts in taken.items():
        src = prop.parts[pi]
        src.tris = [v for t in range(len(src.tris) // 3) if t not in ts for v in src.tris[t * 3:t * 3 + 3]]
    prop.parts += new_parts
    return wheels
