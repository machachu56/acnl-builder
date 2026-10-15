"""The interpreter, in Python: runs the same bytecode as plugin/script_vm.h against a pretend game.

Used to (1) check a script can run (no division by zero, no runaway loops, no unreadable memory), (2) show what a
script does at every time of day, and (3) test the plugin's interpreter: both must give the same actions.
"""
import struct

from . import actions as A

BUDGET = 20000
NAMES = {n.id: n.name for n in A.NATIVES}


class VMError(Exception):
    pass


class Loaded:
    """a decoded program file (see compiler.Program.encode)"""

    def __init__(self, blob):
        if blob[:4] != b"ACS1":
            raise VMError("not a script program")
        o = 4
        n, = struct.unpack_from("<H", blob, o)
        o += 2
        self.strings = []
        for _ in range(n):
            ln = blob[o]
            self.strings.append(blob[o + 1:o + 1 + ln].decode("utf-8"))
            o += 1 + ln
        nv, nh = struct.unpack_from("<HH", blob, o)
        o += 4
        self.nvars = nv
        self.handlers = []
        for _ in range(nh):
            kind, s1, s2, num, nloc, ln = struct.unpack_from("<BHHIHH", blob, o)
            o += 13
            self.handlers.append(dict(kind=kind, s1=s1, s2=s2, num=num, nlocals=nloc, code=blob[o:o + ln]))
            o += ln


class World:
    """a pretend game: clock, place, memory, registers"""

    def __init__(self, hour=12, minute=0, weekday=0, day=1, month=1, year=2026, building=None, room=None, mem=None, regs=None, seed=1):
        self.hour, self.minute, self.weekday, self.day, self.month, self.year = hour, minute, weekday, day, month, year
        self.building, self.room = building, room
        self.mem = dict(mem or {})
        self.regs = list(regs or [0] * 16)
        self.vars = {}
        self.seed = seed
        self.trace = []
        self.skipped = False
        self.hidden = False
        self.became = None
        self.placed = None
        self.variants = {}

    def rand(self):
        self.seed = (self.seed * 1103515245 + 12345) & 0x7FFFFFFF
        return self.seed >> 8


def _i32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def run(prog, h, world, villagers=None):
    """execute handler `h` (a dict of Loaded.handlers); returns the world; raises VMError"""
    code, st, loc = h["code"], [], [0] * max(1, h["nlocals"])
    S = prog.strings
    pc, steps = 0, 0

    def pop():
        if not st:
            raise VMError("internal error: stack underflow")
        return st.pop()

    def rd(addr, n):
        if addr < 0x1000:
            raise VMError("read of address 0x%x (not game memory)" % (addr & 0xFFFFFFFF))
        return sum(world.mem.get(addr + i, 0) << (8 * i) for i in range(n))

    def wr(addr, n, v):
        if addr < 0x1000:
            raise VMError("write to address 0x%x (not game memory)" % (addr & 0xFFFFFFFF))
        for i in range(n):
            world.mem[addr + i] = (v >> (8 * i)) & 0xFF
        world.trace.append("write%d(0x%x, %d)" % (n * 8, addr & 0xFFFFFFFF, v))

    while True:
        steps += 1
        if steps > BUDGET:
            raise VMError("the script ran for too long (more than %d steps): is there a loop that never ends?" % BUDGET)
        if pc >= len(code):
            return world
        op = code[pc]
        pc += 1
        if op == 0x01:
            st.append(struct.unpack_from("<i", code, pc)[0]); pc += 4
        elif op == 0x02:
            st.append(loc[code[pc]]); pc += 1
        elif op == 0x03:
            loc[code[pc]] = pop(); pc += 1
        elif op == 0x06:
            b, a = pop(), pop()
            k = code[pc]; pc += 1
            if k in (3, 4) and b == 0:
                raise VMError("division by zero")
            st.append(_i32({0: lambda: a + b, 1: lambda: a - b, 2: lambda: a * b, 3: lambda: int(a // b) if b else 0,
                            4: lambda: a % b if b else 0, 5: lambda: int(a == b), 6: lambda: int(a != b), 7: lambda: int(a < b),
                            8: lambda: int(a <= b), 9: lambda: int(a > b), 10: lambda: int(a >= b), 11: lambda: a & b,
                            12: lambda: a | b, 13: lambda: a ^ b, 14: lambda: a << (b & 31), 15: lambda: a >> (b & 31)}[k]()))
        elif op == 0x07:
            st.append(int(not pop()))
        elif op == 0x08:
            st.append(_i32(-pop()))
        elif op == 0x09:
            pc = struct.unpack_from("<H", code, pc)[0]
        elif op == 0x0A:
            t = struct.unpack_from("<H", code, pc)[0]; pc += 2
            if not pop():
                pc = t
        elif op == 0x0F:
            t = struct.unpack_from("<H", code, pc)[0]; pc += 2
            if pop():
                pc = t
        elif op == 0x0C:
            pop()
        elif op == 0x0D:
            return world
        elif op == 0x0E:
            st.append(st[-1])
        elif op == 0x0B:
            nid, na = code[pc], code[pc + 1]
            pc += 2
            args = [pop() for _ in range(na)][::-1]
            r = native(prog, nid, args, world, S)
            if r is not None:
                st.append(_i32(r))
        else:
            raise VMError("bad instruction 0x%x" % op)


def native(prog, nid, a, w, S):
    nm = NAMES.get(nid)
    if nm is None:
        raise VMError("unknown built-in %d" % nid)
    if nm == "hour": return w.hour
    if nm == "minute": return w.minute
    if nm == "weekday": return w.weekday
    if nm == "day": return w.day
    if nm == "month": return w.month
    if nm == "year": return w.year
    if nm == "in_building": return int(w.building == S[a[0]])
    if nm == "in_room": return int(w.building == S[a[0]] and w.room == S[a[1]])
    if nm == "chance": return int(w.rand() % 100 < a[0])
    if nm == "random": return w.rand() % a[0] if a[0] > 0 else 0
    if nm == "get_var": return w.vars.get(a[0], 0)
    if nm == "set_var": w.vars[a[0]] = a[1]; return None
    if nm == "log":
        w.trace.append("log(%r%s)" % (S[a[0]], ", %d" % a[1] if a[1] else "")); return None
    if nm == "wear": w.trace.append("wear(%s, %s)" % (S[a[0]], S[a[1]])); return None
    if nm == "wear_default": w.trace.append("wear_default(%s)" % S[a[0]]); return None
    if nm == "variant_on": w.trace.append("variant_on(%s)" % S[a[0]]); return None
    if nm == "variant_off": w.trace.append("variant_off(%s)" % S[a[0]]); return None
    if nm == "hide_actor": w.hidden = True; w.trace.append("hide_actor()"); return None
    if nm == "become": w.became = a[0] & 0xFFFFFFFF; w.trace.append("become(0x%x)" % w.became); return None
    if nm == "place_player": w.placed = (a[0], a[1], a[2]); w.trace.append("place_player(%d, %d, %d)" % tuple(a)); return None
    if nm in ("read8", "read16", "read32"):
        n = int(nm[4:]) // 8
        return _rd(w, a[0], n)
    if nm in ("write8", "write16", "write32"):
        n = int(nm[5:]) // 8
        _wr(w, a[0], n, a[1]); return None
    if nm == "reg": return w.regs[a[0] & 15]
    if nm == "set_reg": w.regs[a[0] & 15] = a[1]; w.trace.append("set_reg(%d, %d)" % (a[0] & 15, a[1])); return None
    if nm == "skip_call": w.skipped = True; w.trace.append("skip_call()"); return None
    raise VMError("built-in %s is not implemented" % nm)


def _rd(w, addr, n):
    if addr < 0x1000:
        raise VMError("read of address 0x%x (not game memory)" % (addr & 0xFFFFFFFF))
    return sum(w.mem.get(addr + i, 0) << (8 * i) for i in range(n))


def _wr(w, addr, n, v):
    if addr < 0x1000:
        raise VMError("write to address 0x%x (not game memory)" % (addr & 0xFFFFFFFF))
    for i in range(n):
        w.mem[addr + i] = (v >> (8 * i)) & 0xFF
    w.trace.append("write%d(0x%x, %d)" % (n * 8, addr & 0xFFFFFFFF, v))
