"""Cross references in the game's code (ARM mode): who calls a function, who uses a string or a data word.

Built once per dump (a minute or so, cached): every `BL` (call) and every `LDR rX, [pc, #n]` literal that points at a
string or data address. With the RTTI map (gamemap) this is how hooks are found without symbols: a class' method uses
the string "Player/face_tex/%s%02d%s.bcres" -> it loads face textures; who calls it -> where the face is chosen.
"""
import bisect
import functools
import os
import pickle
import sys

from . import env, gamemap


class XRef:
    def __init__(self, gm):
        self.gm = gm
        self.calls = {}              # call site -> target
        self.callers = {}            # target -> [call sites]
        self.lits = {}               # instruction address -> literal value (pointing into rodata/data)
        self.users = {}              # value -> [instruction addresses]
        self.starts = []             # sorted function entries (vtable methods + call targets + push-lr prologues)

    def build(self):
        gm = self.gm
        env.setup_path()
        import armisa
        t0, _, tsize = gm.segs[0]
        data = gm.code[gm.segs[0][1]:gm.segs[0][1] + tsize]
        img = armisa.Image(t0, data)
        lo, hi = gm.segs[1][0], gm.segs[2][0] + gm.segs[2][2]
        starts = set()
        for c in gm.classes.values():
            starts.update(m & ~1 for m in c["methods"])
        for a in range(t0, t0 + tsize - 3, 4):
            w = int.from_bytes(data[a - t0:a - t0 + 4], "little")
            top = w >> 25
            if top == 0x75 or (w >> 24) & 0xF == 0xB:                         # cond B / BL
                if (w >> 24) & 0xF == 0xB and (w >> 28) != 0xF:
                    ins = armisa.decode_arm(w, a)
                    if getattr(ins, "link", False):
                        d = ins.dest
                        self.calls[a] = d
                        self.callers.setdefault(d, []).append(a)
                        starts.add(d & ~1)
            if (w & 0x0F7F0000) == 0x051F0000 or (w & 0x0E5F0000) == 0x041F0000:   # LDR rt, [pc, #+-imm]
                off = w & 0xFFF
                lit = a + 8 + (off if (w >> 23) & 1 else -off)
                if t0 <= lit < t0 + tsize:
                    v = int.from_bytes(data[lit - t0:lit - t0 + 4], "little")
                    if lo <= v < hi:
                        self.lits[a] = v
                        self.users.setdefault(v, []).append(a)
            if (w & 0xFFFF0000) == 0xE92D0000 and w & 0x4000:                    # push {..., lr}: a prologue
                starts.add(a)
        self.starts = sorted(starts)
        return self

    def function_of(self, addr):
        i = bisect.bisect_right(self.starts, addr & ~1) - 1
        return self.starts[i] if i >= 0 else None

    def users_of_string(self, text):
        """[(string address, string, [function entries that load its address])] for strings containing `text`"""
        gm, out = self.gm, []
        ro = gm.segs[1]
        blob = gm.code[ro[1]:ro[1] + ro[2]]
        needle = text.encode()
        i = blob.find(needle)
        while i >= 0:
            s = blob.rfind(b"\0", 0, i) + 1
            e = blob.find(b"\0", i)
            addr = ro[0] + s
            users = sorted({self.function_of(a) for a in self.users.get(addr, [])} - {None})
            out.append((addr, blob[s:e].decode("latin1"), users))
            i = blob.find(needle, e)
        return out

    def callers_of(self, func):
        return sorted({self.function_of(a) for a in self.callers.get(func, []) + self.callers.get(func | 1, [])} - {None})


@functools.lru_cache(maxsize=1)
def load():
    gm = gamemap.load()
    cache = os.path.join(env.CACHE, "xref.pickle")
    try:
        with open(cache, "rb") as f:
            x = pickle.load(f)
        x.gm = gm
        return x
    except Exception:
        pass
    x = XRef(gm).build()
    gm_, x.gm = x.gm, None
    try:
        os.makedirs(env.CACHE, exist_ok=True)
        with open(cache + ".tmp", "wb") as f:
            pickle.dump(x, f)
        os.replace(cache + ".tmp", cache)
    except OSError:
        pass
    x.gm = gm_
    return x
