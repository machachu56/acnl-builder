"""Custom 3D models, entrances, lift and signs. Pure Python except where the engine (recomp's modkit) is needed."""
import base64
import io
import json
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from acnlb import env, models  # noqa: E402

try:
    env.setup_path()
    from acnlb import interior  # noqa: E402
    HAVE_ENGINE = True
except SystemExit:
    HAVE_ENGINE = False

CUBE = [(-1, 0, -1), (1, 0, -1), (1, 0, 1), (-1, 0, 1), (-1, 2, -1), (1, 2, -1), (1, 2, 1), (-1, 2, 1)]
QUADS = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]       # counter-clockwise from outside


def png(color=(200, 30, 30, 255), size=(8, 8)):
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGBA", size, color).save(out, "PNG")
    return out.getvalue()


def obj_cube():
    lines = ["mtllib cube.mtl", "usemtl red"] + ["v %g %g %g" % p for p in CUBE]
    lines += ["vt 0 0", "vt 1 0", "vt 1 1", "vt 0 1"]
    lines += ["f " + " ".join("%d/%d" % (i + 1, k + 1) for k, i in enumerate(q)) for q in QUADS]
    return "\n".join(lines).encode()


def glb_cube(textured=True):
    pos = b"".join(struct.pack("<3f", *CUBE[i]) for q in QUADS for i in q)
    uv = b"".join(struct.pack("<2f", *t) for _ in QUADS for t in ((0, 0), (1, 0), (1, 1), (0, 1)))
    idx = b"".join(struct.pack("<3H", 4 * f, 4 * f + 1, 4 * f + 2) + struct.pack("<3H", 4 * f, 4 * f + 2, 4 * f + 3) for f in range(6))
    img = png()
    blob = pos + uv + idx + img
    doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}],
           "nodes": [{"mesh": 0, "translation": [5, 0, 0]}],
           "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "TEXCOORD_0": 1}, "indices": 2, "material": 0}]}],
           "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [1, 0.5, 0.5, 1], **({"baseColorTexture": {"index": 0}} if textured else {})}}],
           "textures": [{"source": 0}], "images": [{"bufferView": 3, "mimeType": "image/png"}],
           "buffers": [{"byteLength": len(blob)}],
           "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(pos)},
                           {"buffer": 0, "byteOffset": len(pos), "byteLength": len(uv)},
                           {"buffer": 0, "byteOffset": len(pos) + len(uv), "byteLength": len(idx)},
                           {"buffer": 0, "byteOffset": len(pos) + len(uv) + len(idx), "byteLength": len(img)}],
           "accessors": [{"bufferView": 0, "componentType": 5126, "count": 24, "type": "VEC3"},
                         {"bufferView": 1, "componentType": 5126, "count": 24, "type": "VEC2"},
                         {"bufferView": 2, "componentType": 5123, "count": 36, "type": "SCALAR"}]}
    j = json.dumps(doc).encode()
    j += b" " * (-len(j) % 4)
    b = blob + b"\0" * (-len(blob) % 4)
    return struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(j) + 8 + len(b)) + struct.pack("<I4s", len(j), b"JSON") + j + struct.pack("<I4s", len(b), b"BIN\0") + b


class Loaders(unittest.TestCase):
    def check(self, m, tris=12):
        self.assertEqual(m.triangles, tris)
        (x0, y0, z0), (x1, y1, z1) = m.bounds()
        self.assertAlmostEqual(x0, -x1)                      # centred on x and z
        self.assertAlmostEqual(z0, -z1)
        self.assertAlmostEqual(y0, 0)                        # standing on the floor
        self.assertAlmostEqual(y1, 2)

    def test_obj_with_mtl_and_texture(self):
        files = {"cube.obj": obj_cube(), "cube.mtl": b"newmtl red\nKd 1 0 0\nmap_Kd tex.png\n", "tex.png": png()}
        m = models.load("cube.obj", files.get)
        self.check(m)
        self.assertIsNotNone(m.materials[0].image)

    def test_obj_missing_support_files_still_loads(self):
        m = models.load("cube.obj", {"cube.obj": obj_cube()}.get)
        self.check(m)
        self.assertIsNone(m.materials[0].image)

    def test_glb(self):
        m = models.load("cube.glb", {"cube.glb": glb_cube()}.get)
        self.check(m)                                        # the node's translation is gone after centring
        self.assertIsNotNone(m.materials[0].image)
        self.assertEqual(tuple(round(c, 2) for c in m.materials[0].color), (1.0, 0.5, 0.5))

    def test_gltf_with_embedded_buffers(self):
        glb = glb_cube()
        j_len = struct.unpack_from("<I", glb, 12)[0]
        doc = json.loads(glb[20:20 + j_len])
        n = struct.unpack_from("<I", glb, 20 + j_len)[0]
        blob = glb[28 + j_len:28 + j_len + n]
        doc["buffers"][0]["uri"] = "data:application/octet-stream;base64," + base64.b64encode(blob).decode()
        m = models.load("cube.gltf", {"cube.gltf": json.dumps(doc).encode()}.get)
        self.check(m)

    def test_stl_binary_and_ascii(self):
        tris = [[CUBE[a], CUBE[b], CUBE[c]] for q in QUADS for a, b, c in ((q[0], q[1], q[2]), (q[0], q[2], q[3]))]
        data = b"\0" * 80 + struct.pack("<I", 12) + b"".join(struct.pack("<12f", 0, 0, 0, *a, *b, *c) + b"\0\0" for a, b, c in tris)
        self.check(models.load("c.stl", {"c.stl": data}.get))
        txt = "solid x\n" + "".join("facet normal 0 0 0\nouter loop\n" + "".join("vertex %g %g %g\n" % p for p in t) + "endloop\nendfacet\n" for t in tris)
        self.check(models.load("c.stl", {"c.stl": txt.encode()}.get))

    def test_ply_ascii_z_up(self):
        faces = [q for q in QUADS]
        pts = [(x, -z, y) for x, y, z in CUBE]              # a Z-up export of the same cube
        txt = "ply\nformat ascii 1.0\nelement vertex 8\nproperty float x\nproperty float y\nproperty float z\nelement face 6\nproperty list uchar int vertex_indices\nend_header\n"
        txt += "".join("%g %g %g\n" % p for p in pts) + "".join("4 %d %d %d %d\n" % f for f in faces)
        self.check(models.load("c.ply", {"c.ply": txt.encode()}.get, up="z"))

    def test_bad_files(self):
        with self.assertRaises(models.ModelError):
            models.load("x.fbx", {"x.fbx": b"?"}.get)
        with self.assertRaises(models.ModelError):
            models.load("x.glb", {}.get)


class Config(unittest.TestCase):
    def test_entry_line_for_the_plugin(self):
        from acnlb.features.runtime import config_text

        class B:
            cfg = {"buildings": [{"id": "x", "pages": [{"variant": "v0", "jmp": "a.jmp", "links": [], "entry": "464, 256, 49152"}]}], "events": []}
        txt = config_text(B)
        self.assertIn("entry = 464, 256, 49152", txt)


@unittest.skipUnless(HAVE_ENGINE, "recomp checkout (modkit) not available")
class Engine(unittest.TestCase):
    def scene(self, **kw):
        s = {"id": "t", "main": "main", "materials": {"f": {"type": "floor", "preset": "plain"}, "w": {"type": "wall", "preset": "plain"}},
             "rooms": [{"id": "main", "rect": [3, 3, 10, 13], "floor": "f", "wall": "w"}], "items": []}
        s.update(kw)
        return s

    def build(self, spec, files=None):
        def read(path):
            raise AssertionError("no game files needed")
        f = files or {}
        loader = lambda n: None
        loader.bytes = f.get
        return interior.Builder(spec, read, loader).build()

    def test_entrances(self):
        for side, door, spawn_yaw, rect in (("south", (7, 14), None, [3, 3, 10, 13]), ("east", (14, 7), 49152, [3, 3, 13, 13]),
                                            ("west", (1, 7), 16384, [2, 3, 10, 13]), ("north", (7, 1), 0, [3, 2, 10, 13])):
            spec = self.scene(entrance=side, entrance_at=7)
            spec["rooms"][0]["rect"] = rect
            b = self.build(spec)
            self.assertIn(door, b.plan.door, side)
            self.assertEqual(None if b.plan.spawn is None else b.plan.spawn[2], spawn_yaw, side)
            self.assertEqual(len(b.plan.exit), 2)

    def test_door_must_open_onto_floor(self):
        spec = self.scene(entrance="east")                                  # the main room stops at x = 10: a wall in front of the door
        with self.assertRaises(interior.SceneError) as e:
            self.build(spec)
        self.assertIn("opens onto a wall", str(e.exception))

    def test_east_door_needs_a_free_strip(self):
        spec = self.scene(entrance="east")
        spec["rooms"][0]["rect"] = [3, 3, 14, 12]
        with self.assertRaises(interior.SceneError):
            self.build(spec)

    def test_south_default_is_unchanged(self):
        b = self.build(self.scene())
        self.assertEqual(b.plan.door, [(7, 14), (8, 14)])
        self.assertEqual(b.plan.exit, [(7, 15), (8, 15)])

    def test_lift_raises_an_item(self):
        item = {"id": "b", "type": "box", "x0": 64, "x1": 96, "z0": 64, "z1": 96, "y0": 0, "y1": 10, "mat": "f"}
        spec = self.scene(items=[item])
        spec["materials"]["f"] = {"type": "prop", "preset": "solid", "size": [8, 8]}
        lo = self.build(spec).mesh
        item["lift"] = 12
        hi = self.build(spec).mesh
        tops = lambda m: [v for v in m.verts if abs(v["pos"][1] - 22) < 1e-6]
        self.assertFalse(tops(lo))
        self.assertTrue(tops(hi))

    def test_signs_follow_the_doorways(self):
        spec = self.scene()
        spec["rooms"].append({"id": "r1", "rect": [5, 0, 10, 2], "floor": "f", "wall": "w", "doors": [[6, 3], [7, 3], [9, 3]],
                              "label": "A rather long sign for a small door", "label_style": "neon",
                              "label_colors": {"fg": "#00ff00", "bg": "#000000", "outline": "", "frame": "#ff00ff"}})
        b = self.build(spec)
        self.assertEqual(len(interior.sign_regions(spec["rooms"][1])), 2)     # 6-7 and 9
        self.assertIn("sign:r1:0", b.R)
        w0 = b.R["sign:r1:0"]
        self.assertEqual((w0[2] - w0[0]) / (w0[3] - w0[1]), 4.0)                # 64 x 16 units: never stretched
        w1 = b.R["sign:r1:1"]
        self.assertEqual((w1[2] - w1[0]) / (w1[3] - w1[1]), 2.0)                # a one-tile doorway gets a 2:1 sign

    def test_custom_model_in_a_room(self):
        files = {"mdl_cube__cube.glb": glb_cube()}
        item = {"id": "c1", "type": "custom", "asset": "mdl_cube__cube.glb", "x": 160, "z": 160, "scale": 8, "rot": 90, "lift": 4}
        b = self.build(self.scene(items=[item]), files)
        ys = [v["pos"][1] for v in b.mesh.verts]
        self.assertTrue(any(abs(y - (2 * 8 + 4)) < 1e-6 for y in ys))             # 2 units tall x 8, lifted by 4
        self.assertTrue(any(k.startswith("c:mdl_cube__cube.glb") for k in b.R))


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAVE_ENGINE and os.path.isfile(env.ROM), "game dump not available")
class Outfits(unittest.TestCase):
    def test_default_outfit_and_variant(self):
        import tempfile
        from acnlb import build, project
        from acnlb.features import textures as texmod
        with tempfile.TemporaryDirectory() as td:
            env.PROJECTS = td
            proj = project.blank("tst")
            os.makedirs(os.path.join(td, "tst", "assets"))
            open(os.path.join(td, "tst", "assets", "o.png"), "wb").write(png((255, 0, 0, 255), (64, 256)))
            proj["villagers"] = [{"id": "ant00", "name": {}, "catchphrase": {}, "default_outfit": "a",
                                  "outfits": [{"id": "a", "name": "A", "textures": {"b0": "o.png"}}, {"id": "b", "name": "B", "textures": {"b0": "o.png"}}]}]
            b = build.build(proj, only=["villagers"])
            self.assertIn("romfs/Npc/Normal/Model/ant00.bcres", b.files)
            self.assertIn("romfs.outfit_ant00_b/Npc/Normal/Model/ant00.bcres", b.files)
            self.assertEqual(len(b.cfg["outfits"]), 2)
            self.assertTrue(b.warnings)                                   # outfit b is worn by nothing yet
