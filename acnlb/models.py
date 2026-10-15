"""Custom 3D models for interiors: Blender exports (glTF/GLB, OBJ + MTL, STL, PLY) -> a neutral triangle soup.

    load(name, fetch, up="y") -> Model
        name   file name of the main file (the extension picks the reader)
        fetch  fetch(basename) -> bytes | None, gives the other files a model refers to (.mtl, .bin, textures);
               fetch(name) itself must return the main file
        up     "y" (glTF and the Blender OBJ default) or "z" (STL/PLY and "Z up" exports)

The result is centred on x/z and stands on y = 0 (units are whatever the file used; the item's `scale` turns them
into room units: 32 per tile). The front of a model faces +z like the game's own, which is where Blender's -Y front
lands with its default exporter axes. No third-party packages: Pillow only, for textures.
"""
import base64
import io
import json
import math
import os
import struct

EXTENSIONS = (".glb", ".gltf", ".obj", ".stl", ".ply")
SUPPORT_EXTENSIONS = (".mtl", ".bin", ".png", ".jpg", ".jpeg")


class ModelError(ValueError):
    pass


class Material:
    def __init__(self, name, color=(1.0, 1.0, 1.0), image=None):
        self.name = name
        self.color = tuple(color)           # multiplies the texture (white = as painted)
        self.image = image                  # PIL.Image (RGBA) or None


class Model:
    def __init__(self):
        self.materials = []                 # [Material]
        self.groups = []                    # [(material index, [vertex dicts pos/normal/uv], [triangle indices])]
        self.notes = []

    @property
    def triangles(self):
        return sum(len(t) // 3 for _, _, t in self.groups)

    @property
    def vertices(self):
        return sum(len(v) for _, v, _ in self.groups)

    def bounds(self):
        pts = [v["pos"] for _, vs, _ in self.groups for v in vs]
        if not pts:
            raise ModelError("the model has no triangles")
        return (tuple(min(p[i] for p in pts) for i in range(3)), tuple(max(p[i] for p in pts) for i in range(3)))


# ------------------------------------------------------------------ small vector helpers

def _sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def _cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(a):
    n = math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])
    return (a[0] / n, a[1] / n, a[2] / n) if n > 1e-12 else (0.0, 1.0, 0.0)


def _face_normal(a, b, c):
    return _unit(_cross(_sub(b, a), _sub(c, a)))


class _Builder:
    """collects triangles per material, merging identical vertices"""

    def __init__(self):
        self.mats, self.groups = [], {}

    def material(self, m):
        self.mats.append(m)
        return len(self.mats) - 1

    def tri(self, mi, a, b, c):
        """a, b, c: (pos, normal | None, uv | None)"""
        g = self.groups.setdefault(mi, ({}, [], []))
        fn = None
        for p, n, uv in (a, b, c):
            if n is None:
                fn = fn or _face_normal(a[0], b[0], c[0])
                n = fn
            key = (p, n, uv)
            i = g[0].get(key)
            if i is None:
                i = g[0][key] = len(g[1])
                g[1].append({"pos": p, "normal": n, "uv": uv or (0.0, 0.0)})
            g[2].append(i)

    def model(self):
        m = Model()
        m.materials = self.mats
        for mi, (_, verts, tris) in sorted(self.groups.items()):
            if tris:
                m.groups.append((mi, verts, tris))
        return m


# ------------------------------------------------------------------ OBJ + MTL

def _images(fetch, name):
    from PIL import Image
    data = fetch(os.path.basename(name.replace("\\", "/")))
    if not data:
        return None
    try:
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None


def _parse_mtl(text, fetch, notes):
    mats, cur = {}, None
    for line in text.splitlines():
        p = line.split(None, 1)
        if len(p) < 2:
            continue
        key, rest = p[0].lower(), p[1].strip()
        if key == "newmtl":
            cur = mats[rest] = Material(rest)
        elif cur is None:
            continue
        elif key == "kd":
            try:
                cur.color = tuple(max(0.0, min(1.0, float(v))) for v in rest.split()[:3])
            except ValueError:
                pass
        elif key == "map_kd":
            ref = rest.split()[-1]            # options (-s, -o ...) come before the file name
            cur.image = _images(fetch, ref)
            if cur.image is None:
                notes.append("texture %s of material %s was not uploaded" % (ref, cur.name))
            else:
                cur.color = (1.0, 1.0, 1.0)
    return mats


def load_obj(data, fetch):
    b, notes = _Builder(), []
    V, VT, VN = [], [], []
    lib, cur = {}, None
    default = None

    def idx(s, n):
        i = int(s)
        return i - 1 if i > 0 else n + i

    for raw in data.decode("utf-8", "replace").splitlines():
        line = raw.strip()
        if not line or line[0] == "#":
            continue
        p = line.split()
        k = p[0]
        try:
            if k == "v":
                V.append((float(p[1]), float(p[2]), float(p[3])))
            elif k == "vt":
                VT.append((float(p[1]), float(p[2])))
            elif k == "vn":
                VN.append((float(p[1]), float(p[2]), float(p[3])))
            elif k == "mtllib":
                for f in line.split(None, 1)[1].split():
                    t = fetch(os.path.basename(f.replace("\\", "/")))
                    if t:
                        lib.update(_parse_mtl(t.decode("utf-8", "replace"), fetch, notes))
                    else:
                        notes.append("material library %s was not uploaded (colours are lost)" % f)
            elif k == "usemtl":
                name = line.split(None, 1)[1].strip()
                m = lib.get(name) or Material(name)
                cur = None
                for i, e in enumerate(b.mats):
                    if e is m:
                        cur = i
                if cur is None:
                    cur = b.material(m)
            elif k == "f":
                if cur is None:
                    if default is None:
                        default = b.material(Material("default", (0.8, 0.8, 0.8)))
                    cur = default
                corners = []
                for tok in p[1:]:
                    s = tok.split("/")
                    pos = V[idx(s[0], len(V))]
                    uv = VT[idx(s[1], len(VT))] if len(s) > 1 and s[1] else None
                    nr = VN[idx(s[2], len(VN))] if len(s) > 2 and s[2] else None
                    corners.append((pos, _unit(nr) if nr else None, uv))
                for i in range(1, len(corners) - 1):
                    b.tri(cur, corners[0], corners[i], corners[i + 1])
        except (ValueError, IndexError):
            raise ModelError("cannot read this line of the OBJ file: %s" % line[:60])
    m = b.model()
    m.notes = notes
    return m


# ------------------------------------------------------------------ glTF / GLB

_COMP = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def _mat_mul(a, b):
    """4x4 column-major matrices"""
    return [sum(a[k * 4 + r] * b[c * 4 + k] for k in range(4)) for c in range(4) for r in range(4)]


def _node_matrix(n):
    if "matrix" in n:
        return list(n["matrix"])
    t, r, s = n.get("translation", (0, 0, 0)), n.get("rotation", (0, 0, 0, 1)), n.get("scale", (1, 1, 1))
    x, y, z, w = r
    return [(1 - 2 * (y * y + z * z)) * s[0], (2 * (x * y + z * w)) * s[0], (2 * (x * z - y * w)) * s[0], 0,
            (2 * (x * y - z * w)) * s[1], (1 - 2 * (x * x + z * z)) * s[1], (2 * (y * z + x * w)) * s[1], 0,
            (2 * (x * z + y * w)) * s[2], (2 * (y * z - x * w)) * s[2], (1 - 2 * (x * x + y * y)) * s[2], 0,
            t[0], t[1], t[2], 1]


def load_gltf(data, fetch):
    chunks = None
    if data[:4] == b"glTF":
        _, _, total = struct.unpack_from("<4sII", data, 0)
        off, chunks = 12, []
        while off + 8 <= min(total, len(data)):
            n, kind = struct.unpack_from("<I4s", data, off)
            chunks.append((kind, data[off + 8:off + 8 + n]))
            off += 8 + n
        doc = json.loads(chunks[0][1].decode("utf-8"))
        glb = next((c for k, c in chunks[1:] if k.startswith(b"BIN")), None)
    else:
        try:
            doc = json.loads(data.decode("utf-8"))
        except ValueError:
            raise ModelError("not a glTF file")
        glb = None
    notes = []

    def uri_bytes(uri):
        if uri.startswith("data:"):
            return base64.b64decode(uri.split(",", 1)[1])
        from urllib.parse import unquote
        return fetch(os.path.basename(unquote(uri)))

    buffers = []
    for i, bf in enumerate(doc.get("buffers", [])):
        blob = glb if "uri" not in bf else uri_bytes(bf["uri"])
        if blob is None:
            raise ModelError("the glTF refers to a file that was not uploaded (%s): select the .bin and the textures too, or export a single .glb" % bf.get("uri", "buffer %d" % i))
        buffers.append(blob)

    def view_bytes(vi):
        v = doc["bufferViews"][vi]
        o = v.get("byteOffset", 0)
        return buffers[v["buffer"]][o:o + v["byteLength"]], v.get("byteStride")

    def accessor(ai):
        a = doc["accessors"][ai]
        if "sparse" in a:
            raise ModelError("sparse glTF accessors are not supported: export again without shape keys")
        fmt, size = _COMP[a["componentType"]]
        nc = _NCOMP[a["type"]]
        n = a["count"]
        if "bufferView" not in a:
            return [tuple([0.0] * nc) if nc > 1 else 0 for _ in range(n)]
        raw, stride = view_bytes(a["bufferView"])
        stride = stride or size * nc
        off = a.get("byteOffset", 0)
        out = []
        norm = a.get("normalized")
        for i in range(n):
            vals = struct.unpack_from("<%d%s" % (nc, fmt), raw, off + i * stride)
            if norm and fmt != "f":
                lim = {"b": 127.0, "B": 255.0, "h": 32767.0, "H": 65535.0}[fmt]
                vals = tuple(max(-1.0, v / lim) for v in vals)
            out.append(vals if nc > 1 else vals[0])
        return out

    from PIL import Image
    images = {}

    def image(i):
        if i not in images:
            im = doc["images"][i]
            blob = None
            try:
                blob = view_bytes(im["bufferView"])[0] if "bufferView" in im else uri_bytes(im["uri"])
            except KeyError:
                pass
            try:
                images[i] = Image.open(io.BytesIO(blob)).convert("RGBA") if blob else None
            except Exception:
                images[i] = None
            if images[i] is None:
                notes.append("a texture could not be read (use PNG or JPEG)")
        return images[i]

    b = _Builder()
    mat_index = {}

    def material(mi):
        if mi not in mat_index:
            if mi is None:
                m = Material("default", (0.8, 0.8, 0.8))
            else:
                gm = doc["materials"][mi]
                pbr = gm.get("pbrMetallicRoughness", {})
                col = pbr.get("baseColorFactor", [1, 1, 1, 1])
                tex = pbr.get("baseColorTexture")
                im = None
                if tex is not None:
                    src = doc["textures"][tex["index"]].get("source")
                    im = image(src) if src is not None else None
                m = Material(gm.get("name", "material%d" % mi), col[:3], im)
            mat_index[mi] = b.material(m)
        return mat_index[mi]

    def visit(ni, parent):
        n = doc["nodes"][ni]
        mtx = _mat_mul(parent, _node_matrix(n))
        if "mesh" in n:
            for prim in doc["meshes"][n["mesh"]]["primitives"]:
                if prim.get("mode", 4) != 4:
                    notes.append("a non-triangle primitive was skipped")
                    continue
                at = prim["attributes"]
                P = accessor(at["POSITION"])
                N = accessor(at["NORMAL"]) if "NORMAL" in at else None
                UV = accessor(at["TEXCOORD_0"]) if "TEXCOORD_0" in at else None
                idx = accessor(prim["indices"]) if "indices" in prim else list(range(len(P)))
                mi = material(prim.get("material"))

                def xf(p):
                    return (mtx[0] * p[0] + mtx[4] * p[1] + mtx[8] * p[2] + mtx[12],
                            mtx[1] * p[0] + mtx[5] * p[1] + mtx[9] * p[2] + mtx[13],
                            mtx[2] * p[0] + mtx[6] * p[1] + mtx[10] * p[2] + mtx[14])

                def xn(v):
                    return _unit((mtx[0] * v[0] + mtx[4] * v[1] + mtx[8] * v[2],
                                  mtx[1] * v[0] + mtx[5] * v[1] + mtx[9] * v[2],
                                  mtx[2] * v[0] + mtx[6] * v[1] + mtx[10] * v[2]))
                flip = (mtx[0] * (mtx[5] * mtx[10] - mtx[6] * mtx[9]) - mtx[4] * (mtx[1] * mtx[10] - mtx[2] * mtx[9])
                        + mtx[8] * (mtx[1] * mtx[6] - mtx[2] * mtx[5])) < 0          # a mirrored node reverses the winding
                for t in range(0, len(idx) - 2, 3):
                    tri = []
                    for j in (idx[t], idx[t + 1], idx[t + 2]):
                        uv = UV[j] if UV else None
                        tri.append((xf(P[j]), xn(N[j]) if N else None, (uv[0], 1.0 - uv[1]) if uv else None))   # glTF v runs downwards
                    if flip:
                        tri[1], tri[2] = tri[2], tri[1]
                    b.tri(mi, *tri)
        for c in n.get("children", []):
            visit(c, mtx)

    ident = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    scene = doc.get("scenes", [{}])[doc.get("scene", 0)] if doc.get("scenes") else {}
    roots = scene.get("nodes")
    if roots is None:
        children = {c for n in doc.get("nodes", []) for c in n.get("children", [])}
        roots = [i for i in range(len(doc.get("nodes", []))) if i not in children]
    for r in roots:
        visit(r, ident)
    m = b.model()
    m.notes = notes
    return m


# ------------------------------------------------------------------ STL, PLY

def load_stl(data, fetch=None):
    b = _Builder()
    mi = b.material(Material("stl", (0.78, 0.78, 0.8)))
    tris = []
    if len(data) >= 84 and 84 + struct.unpack_from("<I", data, 80)[0] * 50 == len(data):
        n = struct.unpack_from("<I", data, 80)[0]
        for i in range(n):
            f = struct.unpack_from("<12f", data, 84 + i * 50)
            tris.append([tuple(f[3:6]), tuple(f[6:9]), tuple(f[9:12])])
    else:
        pts = []
        for line in data.decode("utf-8", "replace").splitlines():
            p = line.split()
            if p and p[0] == "vertex":
                pts.append((float(p[1]), float(p[2]), float(p[3])))
        tris = [pts[i:i + 3] for i in range(0, len(pts) - 2, 3)]
    if not tris:
        raise ModelError("the STL file has no triangles")
    for a, c, d in tris:
        b.tri(mi, (a, None, None), (c, None, None), (d, None, None))
    return b.model()


def load_ply(data, fetch=None):
    end = data.find(b"end_header")
    if end < 0:
        raise ModelError("not a PLY file")
    head = data[:end].decode("ascii", "replace").splitlines()
    body = data[data.find(b"\n", end) + 1:]
    fmt, elems = "ascii", []
    for line in head:
        p = line.split()
        if not p:
            continue
        if p[0] == "format":
            fmt = p[1]
        elif p[0] == "element":
            elems.append([p[1], int(p[2]), []])
        elif p[0] == "property" and elems:
            elems[-1][2].append(p[1:])
    types = {"char": "b", "int8": "b", "uchar": "B", "uint8": "B", "short": "h", "int16": "h", "ushort": "H", "uint16": "H",
             "int": "i", "int32": "i", "uint": "I", "uint32": "I", "float": "f", "float32": "f", "double": "d", "float64": "d"}
    verts, faces = [], []
    if fmt == "ascii":
        lines = body.decode("ascii", "replace").splitlines()
        li = 0
        for name, count, props in elems:
            for _ in range(count):
                vals = lines[li].split()
                li += 1
                if name == "vertex":
                    names = [p[-1] for p in props]
                    verts.append((float(vals[names.index("x")]), float(vals[names.index("y")]), float(vals[names.index("z")])))
                elif name == "face":
                    k = int(vals[0])
                    faces.append([int(v) for v in vals[1:1 + k]])
    else:
        e = "<" if "little" in fmt else ">"
        off = 0
        for name, count, props in elems:
            for _ in range(count):
                row = {}
                for p in props:
                    if p[0] == "list":
                        cf, ef, pname = types[p[1]], types[p[2]], p[3]
                        k = struct.unpack_from(e + cf, body, off)[0]
                        off += struct.calcsize(cf)
                        lst = struct.unpack_from(e + "%d%s" % (k, ef), body, off)
                        off += k * struct.calcsize(ef)
                        row[pname] = lst
                    else:
                        f = types[p[0]]
                        row[p[1]] = struct.unpack_from(e + f, body, off)[0]
                        off += struct.calcsize(f)
                if name == "vertex":
                    verts.append((float(row["x"]), float(row["y"]), float(row["z"])))
                elif name == "face":
                    faces.append(list(row.get("vertex_indices") or row.get("vertex_index") or ()))
    b = _Builder()
    mi = b.material(Material("ply", (0.78, 0.78, 0.8)))
    for f in faces:
        for i in range(1, len(f) - 1):
            b.tri(mi, (verts[f[0]], None, None), (verts[f[i]], None, None), (verts[f[i + 1]], None, None))
    return b.model()


# ------------------------------------------------------------------ entry point

def _orient(model, up, flip=False):
    """up axis -> y up, then centre on x/z and put the lowest point on y = 0"""
    def rot(v):
        return (v[0], v[2], -v[1]) if up == "z" else v
    for _, verts, tris in model.groups:
        for v in verts:
            v["pos"] = rot(v["pos"])
            v["normal"] = rot(v["normal"])
        if flip:
            for i in range(0, len(tris) - 2, 3):
                tris[i + 1], tris[i + 2] = tris[i + 2], tris[i + 1]
            for v in verts:
                v["normal"] = tuple(-c for c in v["normal"])
    (x0, y0, z0), (x1, y1, z1) = model.bounds()
    cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
    for _, verts, _ in model.groups:
        for v in verts:
            p = v["pos"]
            v["pos"] = (p[0] - cx, p[1] - y0, p[2] - cz)
    return model


def load(name, fetch, up="y", flip=False):
    data = fetch(name)
    if data is None:
        raise ModelError("the model file %s is missing" % name)
    ext = os.path.splitext(name)[1].lower()
    if ext in (".glb", ".gltf"):
        m = load_gltf(data, fetch)
    elif ext == ".obj":
        m = load_obj(data, fetch)
    elif ext == ".stl":
        m = load_stl(data)
    elif ext == ".ply":
        m = load_ply(data)
    else:
        raise ModelError("unsupported model format %s (use glTF/GLB, OBJ, STL or PLY)" % ext)
    if not m.groups:
        raise ModelError("the model has no triangles")
    return _orient(m, "z" if up == "z" else "y", flip)
