"""Tests that need the game dump (skipped without it):  python3 -m unittest discover -s tests"""
import io
import json
import os
import struct
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from acnlb import env  # noqa: E402

HAVE_ROM = os.path.isfile(env.ROM) and os.path.isdir(env.RECOMP)


class TextTests(unittest.TestCase):
    def test_check_limits(self):
        env.setup_path()
        from acnlb.features import text
        self.assertEqual(text.check("{3.1:}Hello {5.0:}!\nShort"), [])
        self.assertTrue(text.check("a\nb\nc\nd"))                       # 4 lines in a box
        self.assertEqual(text.check("a\nb\nc{0.4:}d\ne\nf"), [])          # a new box resets the count
        self.assertTrue(text.check("x" * 40))
        self.assertEqual(text.plain_len("{5.0:}"), 8)


@unittest.skipUnless(HAVE_ROM, "game dump not available")
class GameTests(unittest.TestCase):
    def test_texture_roundtrip_sizes(self):
        from acnlb import rom, texfmt
        from modkit import cgfx
        for path in ("/Npc/Normal/Model/ant00.bcres", "/Item/Model/tops_aloha_blu.bcres", "/Item/Model/rmk_lov_bedW.bcres"):
            d = rom.read(path)
            for t in cgfx.textures(d):
                if not texfmt.supported(t.fmt):
                    continue
                rows = texfmt.decode_texture(d, t)
                rep = texfmt.replacement(rows, t)
                self.assertEqual(len(rep[3]), t.size, (path, t))

    def test_texture_replacement_applies(self):
        from acnlb import rom
        from acnlb.features import textures
        from modkit import cgfx
        d = rom.read("/Npc/Normal/Model/ant00.bcres")
        t = [x for x in cgfx.textures(d) if x.name == "b0"][0]
        rows = [[(255, 0, 0, 255)] * t.w for _ in range(t.h)]
        new = textures.replace_in(d, {"b0": rows})
        from acnlb import texfmt
        t2 = [x for x in cgfx.textures(new) if x.name == "b0"][0]
        px = texfmt.decode_texture(new, t2)[10][10]
        self.assertGreater(px[0], 200)
        self.assertLess(px[1], 60)

    def test_text_edit(self):
        from acnlb import rom
        from acnlb.features import text
        from modkit import msbt
        d = rom.read("/Script/Talk/NPC_Tanukichi.umsbt")
        out = text.apply(d, [{"label": "001", "text": {"en": "Hi!", "fr": "Salut !"}}])
        parts = msbt.umsbt_split(out)
        self.assertEqual(msbt.Msbt(parts[0]).text(msbt.Msbt(parts[0]).index("001")), "Hi!")
        self.assertEqual(msbt.Msbt(parts[2]).text(msbt.Msbt(parts[2]).index("001")), "Salut !")
        self.assertEqual(msbt.Msbt(parts[1]).text(msbt.Msbt(parts[1]).index("001")), "Hi!")       # es -> English

    def test_exteriors_build(self):
        from acnlb import exterior
        for name, preset in exterior.PRESETS.items():
            e = exterior.build(preset)
            self.assertGreater(len(e.body.tris), 100, name)
            c = e.paint_body()
            self.assertEqual(c.w, 256)
        e = exterior.build({"base": "policeA"})
        self.assertIsNone(e.glow)
        self.assertEqual(e.paint_body().h, 256)

    def test_baisodrome_interior(self):
        from acnlb import interior, project, rom
        from acnlb.features.interiors import asset_loader
        p = project.load("baisodrome")
        b = interior.build_scene(p["interiors"][0], rom.read, asset_loader(p))
        self.assertGreater(len(b.mesh.tris), 3000)
        self.assertEqual(len(b.plan.jmp()), 0xA00)
        self.assertEqual(b.plan.problems(), [])

    def test_interior_rejects_blocked_door(self):
        from acnlb import interior, rom
        spec = {"materials": {"f": {"type": "floor"}, "w": {"type": "wall"}, "p": {"type": "prop", "size": [16, 16]}},
                "rooms": [{"id": "main", "rect": [3, 4, 12, 13], "floor": "f", "wall": "w"}],
                "items": [{"id": "x", "type": "box", "x0": 224, "x1": 288, "y0": 0, "y1": 10, "z0": 448, "z1": 480, "mat": "p", "block": [[7, 14], [8, 14]]}]}
        with self.assertRaises(interior.SceneError):
            interior.build_scene(spec, rom.read)

    def test_events_nodes(self):
        from acnlb.features import events
        nodes = events.message_nodes("Tanukichi")
        self.assertEqual(nodes[0], (4, "002"))
        self.assertEqual(len({l for _, l in nodes}), len(nodes))

    def test_flow_rebuild_and_answers(self):
        from acnlb import rom
        from acnlb.features import events
        flow, talk = "/Script/Flow/NPC_Tanukichi_In.msbf", "/Script/Talk/NPC_Tanukichi.umsbt"
        data = rom.read(flow)
        self.assertEqual(events.FlowFile(data).build(), data)            # untouched, byte for byte
        f = events.FlowFile(data)
        n0, names0 = len(f.nodes), struct.unpack_from("<H", f.nodes[5], 4)[0]
        steps = [{"id": "q", "text": {"en": "Tour?"}, "choices": [{"text": {"en": "Yes!"}, "next": "y"}, {"text": {"en": "No."}, "next": "end"}]},
                 {"id": "y", "text": {"en": "Follow me!"}}]
        extra = []
        events.build_sequence(f, "t", steps, events.text_slots(flow, talk, 4, "001"), extra, talk, None)
        g = events.FlowFile(f.build())
        self.assertEqual(len(g.nodes), n0 + 3)                          # two messages and the branch on the answer
        self.assertEqual(struct.unpack_from("<H", g.nodes[0], 8)[0], n0)
        br = g.nodes[struct.unpack_from("<H", g.nodes[n0], 8)[0]]
        self.assertEqual((br[0], br[1]) + struct.unpack_from("<HH", br, 10), (2, 6, 3, 2))
        self.assertEqual(g.table[-2:], [n0 + 1, 0xFFFF])
        self.assertEqual(struct.unpack_from("<H", g.nodes[5], 4)[0], names0 + 3 * 16 + 2 * 2)      # flow names moved along
        self.assertEqual(g.names, f.names)
        self.assertEqual(extra[0]["text"]["en"], "Tour?{15.5:00000000}\nYes!\nNo.")

    def test_flow_money_steps(self):
        from acnlb import rom
        from acnlb.features import events
        flow, talk = "/Script/Flow/NPC_Secretary_Inside.msbf", "/Script/Talk/NPC_Secretary.umsbt"
        f = events.FlowFile(rom.read(flow))
        n0 = len(f.nodes)
        steps = [{"id": "k", "has_bells": 300, "else": "poor"}, {"id": "c", "charge": 300}, {"id": "ok", "text": {"en": "Thanks!"}, "next": "end"},
                 {"id": "poor", "text": {"en": "You're short."}}]
        extra = []
        events.build_sequence(f, "t", steps, events.text_slots(flow, talk), extra, talk, None)
        g = events.FlowFile(f.build())
        br, ch = g.nodes[n0], g.nodes[n0 + 1]
        self.assertEqual((br[0], br[1]) + struct.unpack_from("<HHH", br, 10)[:2] + (struct.unpack_from("<H", br, 4)[0],), (2, 0, 34, 2, 300))
        t0 = struct.unpack_from("<H", br, 14)[0]
        self.assertEqual(g.table[t0:t0 + 2], [n0 + 1, n0 + 3])                      # enough: charge; not enough: "You're short."
        self.assertEqual((ch[0], ch[1]) + (struct.unpack_from("<H", ch, 10)[0], struct.unpack_from("<H", ch, 4)[0], struct.unpack_from("<H", ch, 8)[0]),
                         (3, 0, 1, 300, n0 + 2))
        self.assertEqual(len(extra), 2)

    def test_export_small_project(self):
        from acnlb import build, project
        old = env.PROJECTS, env.EXPORTS
        with tempfile.TemporaryDirectory() as td:
            env.PROJECTS = os.path.join(td, "p")
            env.EXPORTS = os.path.join(td, "e")
            try:
                p = project.create("tiny", "Tiny")
                p["text"].append({"file": "/Script/Talk/NPC_Tanukichi.umsbt", "label": "001", "text": {"en": "Hello"}})
                p["villagers"].append({"id": "ant00", "name": {"en": "Cyranette"}})
                project.save(p)
                rep = build.export("tiny")
                with zipfile.ZipFile(rep["path"]) as z:
                    names = z.namelist()
                self.assertIn("romfs/Script/Talk/NPC_Tanukichi.umsbt", names)
                self.assertIn("romfs/Script/Str/STR_NNpc_name.umsbt", names)
                self.assertFalse(any(n.endswith(".wasm") for n in names))      # no plugin needed
            finally:
                env.PROJECTS, env.EXPORTS = old
                build.env.EXPORTS = old[1]

    def test_empty_project_refuses(self):
        from acnlb import build, project
        old = env.PROJECTS
        with tempfile.TemporaryDirectory() as td:
            env.PROJECTS = td
            try:
                project.create("empty")
                with self.assertRaises(build.BuildError):
                    build.export("empty")
            finally:
                env.PROJECTS = old


if __name__ == "__main__":
    unittest.main()
