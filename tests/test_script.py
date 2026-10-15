"""Scripts: compiler messages, the Python interpreter, and the plugin's interpreter (compiled natively) agreeing."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from acnlb import env  # noqa: E402

env_ok = True
try:
    env.setup_path()
except SystemExit:
    env_ok = False

from acnlb.script import Ctx, check, compile_source  # noqa: E402
from acnlb.script import vm  # noqa: E402

CTX = Ctx(buildings={"baisodrome": ["lobby", "spa"]}, villagers={"ant00": ["work", "night"]}, actors={"Isabelle": 0x1A0},
          is_function=lambda a: a in (0x5C9380, 0x22A248))

SAMPLE = '''
from acnl import *
LIMIT = 5

def is_night():
    return time_between("22:00", "06:00")

def greet():
    for i in range(LIMIT):
        log("hello", i)

@on_enter("baisodrome")
def a():
    x = 7
    y = -7
    log("div", x // 2 + y // 2)
    log("mod", y % 3)
    log("shift", (1 << 4) | (x ^ 2))
    if is_night() and chance(100):
        log("night")
    elif hour() < 12 or minute() == 30:
        greet()
    else:
        set_var("n", get_var("n") + 1)
        log("n", get_var("n"))
    z = 1 if x > 3 else 2
    log("ternary", z)
    place_player(8, 12, "east")

@on_actor("Isabelle")
def b():
    if time_between("08:00", "17:30"):
        wear("ant00", "work")
    else:
        hide_actor()
        become(0x77)
        place_actor(3, 4)

@on_call(0x5c9380)
def c():
    set_reg(1, reg(0) + 1)
    write32(0x1000, 123456)
    log("mem", read32(0x1000))
    write8(0x1004, 300)
    log("byte", read8(0x1004))
    skip_call()

@on_enter("baisodrome", room="spa")
def d():
    log("zero", 5 // (hour() - hour()))
'''


class Compile(unittest.TestCase):
    def test_sample_compiles(self):
        r = check(SAMPLE, CTX)
        errs = [d for d in r["diagnostics"] if d["severity"] == "error"]
        self.assertEqual([e["message"] for e in errs if "zero" not in e["message"] and "division" not in e["message"]], [])
        self.assertEqual([h["kind"] for h in r["handlers"]], ["enter", "actor", "call", "enter"])

    def test_dry_run_finds_runtime_errors(self):
        r = check(SAMPLE, CTX)
        self.assertTrue(any("division by zero" in d["message"] for d in r["diagnostics"]))
        self.assertFalse(r["ok"])

    def msgs(self, src):
        return [d["message"] + " | " + d["hint"] for d in check(src, CTX)["diagnostics"] if d["severity"] == "error"]

    def test_unknown_building_has_a_suggestion(self):
        m = self.msgs('@on_enter("baisodrom")\ndef f():\n    pass\n')
        self.assertIn("did you mean 'baisodrome'", m[0])

    def test_wrong_context(self):
        self.assertTrue(any("can only be used in @on_actor" in m for m in self.msgs('@on_enter("baisodrome")\ndef f():\n    hide_actor()\n')))

    def test_syntax_error_is_readable(self):
        self.assertTrue(any("not valid Python" in m for m in self.msgs("def f(:\n")))

    def test_unavailable_features_explained(self):
        for src, word in (("@on_enter(\"baisodrome\")\ndef f():\n    while True:\n        pass\n", "while"),
                          ("@on_enter(\"baisodrome\")\ndef f():\n    x = 1 / 2\n", "//"),
                          ("@on_enter(\"baisodrome\")\ndef f():\n    for i in range(500):\n        pass\n", "at most 64")):
            self.assertTrue(any(word in m for m in self.msgs(src)), src)

    def test_bad_function_address(self):
        self.assertTrue(any("not the start of a function" in m for m in self.msgs("@on_call(0x1234)\ndef f():\n    pass\n")))

    def test_unknown_outfit(self):
        self.assertTrue(any("outfit" in m and "nope" in m for m in self.msgs('@on_actor("Isabelle")\ndef f():\n    wear("ant00", "nope")\n')))

    def test_timeline(self):
        r = check('@on_actor("Isabelle")\ndef f():\n    if time_between("22:00", "06:00"):\n        hide_actor()\n', CTX)
        tl = r["handlers"][0]["timeline"]
        self.assertEqual([(s["start"], s["end"], bool(s["does"])) for s in tl], [("00:00", "06:00", True), ("06:00", "22:00", False), ("22:00", "00:00", True)])

    def test_runaway_loops_cannot_exist(self):
        r = check('@on_enter("baisodrome")\ndef f():\n    for i in range(64):\n        for j in range(64):\n            for k in range(64):\n                log("x")\n', CTX)
        self.assertFalse(r["ok"])                                # 262144 steps: over the budget


@unittest.skipUnless(shutil.which("g++") and env_ok, "g++ not available")
class NativeTwin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.exe = os.path.join(cls.dir, "vm_test")
        subprocess.check_call(["g++", "-std=c++17", "-O1", "-o", cls.exe, os.path.join(ROOT, "tests", "vm_native", "vm_test.cpp")])
        src = SAMPLE
        prog = compile_source(src, CTX)
        assert prog.ok, [str(d) for d in prog.diags]
        cls.blob = prog.encode()
        cls.file = os.path.join(cls.dir, "p.acs")
        open(cls.file, "wb").write(cls.blob)
        cls.loaded = vm.Loaded(cls.blob)

    def test_game_clock_fields(self):
        import datetime
        import random
        rnd = random.Random(5)
        epoch1900 = datetime.datetime(1900, 1, 1)
        for _ in range(400):
            t = epoch1900 + datetime.timedelta(seconds=rnd.randrange(0, 150 * 365 * 86400))
            ms = int((t - epoch1900).total_seconds()) * 1000 + rnd.randrange(1000)
            out = subprocess.run([self.exe, "clock", str(ms)], capture_output=True, text=True).stdout.split()
            self.assertEqual([int(v) for v in out], [t.year, t.month, t.day, t.weekday(), t.hour, t.minute], t)

    def python_trace(self, i, hour, minute, building, room):
        w = vm.World(hour=hour, minute=minute, building=building, room=room, weekday=2)
        try:
            vm.run(self.loaded, self.loaded.handlers[i], w)
            err = None
        except vm.VMError as e:
            err = str(e)
        return w.trace, err

    def test_same_actions_at_every_time(self):
        for i in range(len(self.loaded.handlers)):
            for hh in range(0, 24):
                for mm in (0, 30, 45):
                    out = subprocess.run([self.exe, self.file, str(i), str(hh), str(mm), "baisodrome", "spa"], capture_output=True, text=True).stdout.splitlines()
                    native_err = next((l for l in out if l.startswith("ERROR")), None)
                    native = [l for l in out if not l.startswith("ERROR")]
                    tr, err = self.python_trace(i, hh, mm, "baisodrome", "spa")
                    self.assertEqual(native, tr, (i, hh, mm))
                    self.assertEqual(bool(native_err), bool(err), (i, hh, mm))


@unittest.skipUnless(env_ok and os.path.isfile(env.ROM), "game dump not available")
class GameMapTests(unittest.TestCase):
    def test_rtti_map_finds_classes_and_methods(self):
        from acnlb import gamemap
        gm = gamemap.load()
        self.assertGreater(len(gm.classes), 2000)
        c = gm.classes["BsWeatherRain"]
        self.assertTrue(gm.is_code(c["methods"][0]))
        self.assertIn("AcNpc", gm.classes["AcNpcNml"]["bases"])

    def test_xref_finds_string_users(self):
        from acnlb import xref
        x = xref.load()
        hits = x.users_of_string("Player/face_tex/")
        self.assertTrue(hits and hits[0][2])

    def test_probe_report_names_classes(self):
        from acnlb import gamemap, probe
        gm = gamemap.load()
        v = gm.classes["AcNpcNml"]["vtable"]
        log = "probe: actor profile=123 arg=0000007b obj=00200000 vtable=%08x scene=1/1\nprobe: BsWeatherRain.3 r0=1 r1=2 r2=3 r3=4 from=00100010\n" % v
        out = probe.report(log)
        self.assertIn("AcNpcNml", out)
        self.assertIn("BsWeatherRain.3", out)


if __name__ == "__main__":
    unittest.main()
