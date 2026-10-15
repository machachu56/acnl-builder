"""A map of the game's executable from its C++ run-time type information (RTTI): classes, their base classes and
virtual methods, found by reading the ExeFS `.code` of YOUR dump (nothing is shipped).

The game keeps the (mangled) names of its classes for `typeinfo`; a typeinfo points to its name and base class(es),
a vtable is [offset_to_top = 0, typeinfo, method pointers...]. That gives, for every polymorphic class, the entry
address of each virtual method: addresses a plugin can hook (acnl_hook) and `acnlb probe` can trace.

    gm = load()                          # cached on disk per dump
    gm.classes["BsWeatherRain"]          # {"vtable": 0x..., "bases": [...], "methods": [addr, ...]}
    gm.find("Weather")                   # class names containing the text

Names are as the compiler wrote them (some are in anonymous namespaces); what a method DOES is not in the file:
this map says where things are, the probe says when they run.
"""
import functools
import json
import os
import re
import struct

from . import env

TEXT_BASE = 0x100000


class GameMap:
    def __init__(self, code, text_addr, text_size, ro_addr, ro_size, data_addr, data_size):
        self.code = code
        self.segs = []                                   # (vaddr, file offset, size)
        off = 0
        for a, s in ((text_addr, text_size), (ro_addr, ro_size), (data_addr, data_size)):
            pages = (s + 0xFFF) & ~0xFFF
            self.segs.append((a, off, s))
            off += pages
        self.classes = {}

    # ---- addresses
    def off(self, va):
        for a, o, s in self.segs:
            if a <= va < a + s:
                return o + va - a
        return None

    def u32(self, va):
        o = self.off(va)
        return struct.unpack_from("<I", self.code, o)[0] if o is not None and o + 4 <= len(self.code) else None

    def cstr(self, va, limit=200):
        o = self.off(va)
        if o is None:
            return None
        e = self.code.find(b"\0", o, o + limit)
        return self.code[o:e].decode("latin1") if e > o else None

    def is_code(self, va):
        a, _, s = self.segs[0]
        return a <= (va & ~1) < a + s

    # ---- RTTI
    def scan(self):
        code = self.code
        ro, data = self.segs[1], self.segs[2]
        # 1. type name strings: "N10BsEventMgr6ReceptE", "10BsEventMgr" ...
        names = {}
        for m in re.finditer(rb"(?<=\0)(N?\d[A-Za-z0-9_]*E?)\0", code[ro[1]:ro[1] + ((ro[2] + 0xFFF) & ~0xFFF)]):
            names[ro[0] + m.start(1)] = m.group(1).decode()
        # 2. typeinfo objects: [vptr, name_ptr, ...]; find every word that equals a name address
        tinfo = {}                                       # typeinfo address -> (name, base typeinfo addresses)
        for seg in (ro, data):
            a, o, s = seg
            words = struct.unpack_from("<%dI" % (s // 4), code, o)
            for i in range(1, len(words) - 1):
                n = names.get(words[i])
                if n and (words[i - 1] != 0):
                    ta = a + (i - 1) * 4
                    bases = []
                    if i + 1 < len(words) and words[i + 1] in names.__class__() or False:
                        pass
                    tinfo[ta] = (n, words[i + 1:i + 2])
        # 3. vtables: [0, typeinfo, fn, fn...]
        vt = {}
        for seg in (ro, data):
            a, o, s = seg
            words = struct.unpack_from("<%dI" % (s // 4), code, o)
            for i in range(len(words) - 2):
                if words[i] == 0 and words[i + 1] in tinfo and self.is_code(words[i + 2]):
                    ti = words[i + 1]
                    fns = []
                    j = i + 2
                    while j < len(words) and self.is_code(words[j]) and len(fns) < 400:
                        fns.append(words[j])
                        j += 1
                    nm = tinfo[ti][0]
                    key = nm
                    if key not in vt or len(fns) > len(vt[key]["methods"]):
                        vt[key] = {"vtable": a + (i + 2) * 4, "typeinfo": ti, "methods": fns}
        for nm, v in vt.items():
            v["bases"] = self._bases(v["typeinfo"], tinfo)
        self.classes = {demangle(k): dict(v, mangled=k) for k, v in vt.items()}
        return self

    def _bases(self, ti, tinfo):
        """base class names of a typeinfo: [vptr, name, base_typeinfo] (single inheritance)"""
        out = []
        b = self.u32(ti + 8)
        if b in tinfo:
            out.append(demangle(tinfo[b][0]))
        return out

    def find(self, text):
        t = text.lower()
        return sorted(n for n in self.classes if t in n.lower())

    def to_json(self):
        return {"classes": {n: {"vtable": v["vtable"], "bases": v["bases"], "methods": v["methods"]} for n, v in self.classes.items()}}


def demangle(name):
    """'N10HumanModel8FaceCtrlE' -> 'HumanModel::FaceCtrl'; '12AcSimpleTalkI10SignReceptE' stays readable"""
    s = name
    if s.startswith("N") and s.endswith("E"):
        s = s[1:-1]
    parts, i = [], 0
    while i < len(s):
        m = re.match(r"(\d+)", s[i:])
        if not m:
            parts.append(s[i:])
            break
        n = int(m.group(1))
        i += len(m.group(1))
        parts.append(s[i:i + n])
        i += n
    return "::".join(p for p in parts if p) if parts else name


def _read_code():
    from . import rom
    env.setup_path()
    import ctr
    n = ctr.NCSD(env.rom_path())
    c = n.ncch(0)
    ex = c.exheader
    if ex.compressed:
        raise SystemExit("compressed ExeFS code is not supported (use a decrypted dump with an uncompressed .code)")
    return c.read_exefs(".code"), ex


@functools.lru_cache(maxsize=1)
def load():
    cache = os.path.join(env.CACHE, "gamemap.json")
    code, ex = _read_code()
    gm = GameMap(code, ex.text_addr, ex.text_size, ex.ro_addr, ex.ro_size, ex.data_addr, ex.data_size)
    gm.scan()
    return gm
