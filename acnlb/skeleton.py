"""Rest pose of a CGFX model: bone world matrices and per-vertex rigid skinning (for previews)."""
import struct

from . import env

env.setup_path()
from modkit import cgfx  # noqa: E402


def _rel(d, a):
    return a + struct.unpack_from("<I", d, a)[0]


def bones(d, model=0):
    """[(name, parent index, world matrix 3x4 as 12 floats)] in joint order, or [] without a skeleton"""
    mdl = cgfx.models(d)[model]
    if struct.unpack_from("<I", d, mdl + 0xE0)[0] == 0:
        return []
    try:
        sk = _rel(d, mdl + 0xE0)
        if d[sk + 4:sk + 8] != b"SOBJ":
            return []
        local = {}
        for name, o in cgfx.dict_entries(d, _rel(d, sk + 0x1C)):
            idx = struct.unpack_from("<I", d, o + 8)[0]
            parent = struct.unpack_from("<i", d, o + 0xC)[0]
            local[idx] = (name, parent, struct.unpack_from("<12f", d, o + 0x44))      # local matrix (3 x 4, row-major)
        world = {}

        def world_of(i):
            if i not in world:
                name, parent, m = local[i]
                world[i] = m if parent < 0 or parent not in local else _mul(world_of(parent), m)
            return world[i]
        return [(local[i][0], local[i][1], world_of(i)) for i in sorted(local)]
    except (struct.error, AssertionError, KeyError):
        return []


def _mul(a, b):
    """3 x 4 affine matrices (row-major): a * b"""
    out = []
    for r in range(3):
        for c in range(4):
            v = a[r * 4] * b[c] + a[r * 4 + 1] * b[4 + c] + a[r * 4 + 2] * b[8 + c]
            out.append(v + (a[r * 4 + 3] if c == 3 else 0.0))
    return tuple(out)


def bone_table(d, shape, model=0):
    """skeleton joint indices a shape's vertices refer to (first sub-mesh) and its skinning mode"""
    mdl = cgfx.models(d)[model]
    obj = _rel(d, _rel(d, mdl + 0xC8) + shape * 4)
    m = obj + 4
    if struct.unpack_from("<I", d, m + 0x28)[0] < 1:
        return [], 0
    sm = _rel(d, _rel(d, m + 0x2C))
    n = struct.unpack_from("<I", d, sm)[0]
    tbl = _rel(d, sm + 4)
    return list(struct.unpack_from("<%dI" % n, d, tbl)), struct.unpack_from("<I", d, sm + 8)[0]


def pose_vertices(d, shape, verts, model=0):
    """vertex dicts with positions/normals moved into model space by their bones (in place copy)"""
    bs = bones(d, model)
    table, mode = bone_table(d, shape, model)
    if not bs or not table:
        return verts
    out = []
    for v in verts:
        idx = int(round(v.get("attr7", (0,))[0])) if mode else 0
        bi = table[idx] if idx < len(table) else table[0]
        if bi >= len(bs):
            out.append(v)
            continue
        m = bs[bi][2]
        x, y, z = v["pos"][:3]
        nv = dict(v)
        nv["pos"] = (m[0] * x + m[1] * y + m[2] * z + m[3], m[4] * x + m[5] * y + m[6] * z + m[7], m[8] * x + m[9] * y + m[10] * z + m[11])
        if "normal" in v:
            nx, ny, nz = v["normal"][:3]
            nv["normal"] = (m[0] * nx + m[1] * ny + m[2] * nz, m[4] * nx + m[5] * ny + m[6] * nz, m[8] * nx + m[9] * ny + m[10] * nz)
        out.append(nv)
    return out
