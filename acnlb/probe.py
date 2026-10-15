"""Probe mods: a tiny mod that logs what the game does, to find the function a script should hook.

    python3 -m acnlb probe --actors --class BsWeatherRain --class NpcTopsChangeModel   -> exports/probe.acmod
    ... play, with the game started from a terminal (its log goes to stdout), save the output ...
    python3 -m acnlb probe-report game.log

--actors          log every actor the game creates: its profile number, the class it is (AcNpcNml = a villager,
                  AcNpcSpShop = a shopkeeper ...) and the first words of the object (they hold ids)
--class NAME      log every call of every virtual method of the class (the first 30 of each), with the arguments and
                  the caller's address; --list shows which classes match a word
--hook 0xADDR     the same for one function of the game
"""
import collections
import os
import re
import struct

from . import build, env, gamemap

MOD_INI = "# probe mod made by ACNL Builder\nenabled = true\n"


def hooks_for(gm, class_names, addrs):
    shared = collections.Counter(m & ~1 for c in gm.classes.values() for m in set(c["methods"]))   # methods many classes share (the base-class plumbing) say nothing
    out = []
    for name in class_names:
        c = gm.classes.get(name)
        if not c:
            raise SystemExit("no class %r (try `python3 -m acnlb map --find %s`)" % (name, name[:6]))
        seen = set()
        for i, m in enumerate(c["methods"]):
            if m in seen or shared[m & ~1] > 3:
                continue
            seen.add(m)
            out.append((m, "%s.%d" % (name, i)))
    out += [(a, "fn_%x" % a) for a in addrs]
    return out[:400]


def build_probe(class_names=(), addrs=(), actors=False, out=None, spawns=False):
    gm = gamemap.load()
    hooks = hooks_for(gm, class_names, addrs)
    cfg = ["# probe", "", "[probe]", "actors = %d" % int(actors), "spawns = %d" % int(spawns)] + ["hook = 0x%x, %s" % h for h in hooks]
    files = {"mod.ini": MOD_INI.encode(), "acnlb.cfg": ("\n".join(cfg) + "\n").encode(), "probe.wasm": build.build_plugin(None)}
    out = out or os.path.join(env.EXPORTS, "probe.acmod")
    build.write_acmod(files, out)
    return out, len(hooks)


def seen_actors(text):
    """{class name: profile number} from a probe log"""
    gm = gamemap.load()
    vt = {v["vtable"]: n for n, v in gm.classes.items()}
    out = {}
    for m in re.finditer(r"probe: actor profile=(\d+) arg=\w+ obj=\w+ vtable=(\w+) scene=\d+/\d+(?: class=(\S*))?", text):
        name = gamemap.demangle(m.group(3)) if m.group(3) else vt.get(int(m.group(2), 16))
        if name:
            out[name] = int(m.group(1))
    return out


def save_actors(text):
    """merge the actors of a log into acnlb/script/actors.json; returns how many are new"""
    import json
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "script", "actors.json")
    data = json.load(open(path, encoding="utf-8"))
    new = {k: v for k, v in seen_actors(text).items() if k not in data["actors"]}
    data["actors"].update(new)
    json.dump(data, open(path, "w", encoding="utf-8"), indent=1, sort_keys=True)
    return len(new)


def report(text):
    """summarise a game log written with a probe mod"""
    gm = gamemap.load()
    vt = {v["vtable"]: n for n, v in gm.classes.items()}
    owner = {}
    for n, c in gm.classes.items():
        for i, m in enumerate(c["methods"]):
            owner.setdefault(m & ~1, "%s.%d" % (n, i))
    lines = [l.split("probe: ", 1)[1] for l in text.splitlines() if "probe: " in l]
    actors, calls = collections.OrderedDict(), collections.defaultdict(lambda: [0, collections.Counter(), []])
    words = {}
    names = {}
    last = None
    for l in lines:
        m = re.match(r"actor profile=(\d+) arg=(\w+) obj=(\w+) vtable=(\w+) scene=(\d+)/(\d+)(?: class=(\S*))?", l)
        if m:
            prof, vtab = int(m.group(1)), int(m.group(4), 16)
            if m.group(7):
                names[vtab] = gamemap.demangle(m.group(7))
            e = actors.setdefault((prof, vtab), [0, set()])
            e[0] += 1
            e[1].add(int(m.group(5)))
            last = (prof, vtab)
            continue
        m = re.match(r"actor-words (.*)", l)
        if m and last:
            words.setdefault(last, m.group(1))
            continue
        m = re.match(r"(\S+) r0=(\w+) r1=(\w+) r2=(\w+) r3=(\w+) from=(\w+)", l)
        if m:
            c = calls[m.group(1)]
            c[0] += 1
            c[1][int(m.group(6), 16)] += 1
            if len(c[2]) < 3:
                c[2].append(" ".join("r%d=%s" % (i, m.group(2 + i)) for i in range(4)))
    out = []
    if actors:
        out.append("ACTORS created (profile number -> class):")
        for (prof, v), (n, scenes) in sorted(actors.items()):
            out.append("  profile %-5d 0x%-4x  %-28s x%-3d scenes %s" % (prof, prof, names.get(v) or vt.get(v, "vtable 0x%x" % v), n, sorted(scenes)))
            if (prof, v) in words:
                w = [int(t, 16) for t in words[(prof, v)].split()]
                pos = struct.unpack("<3f", struct.pack("<3I", *w[5:8])) if len(w) >= 8 else None
                if pos and all(abs(c) < 5000 for c in pos):
                    out.append("      position (x, y, z): %.0f %.0f %.0f   (tile %d, %d)" % (pos[0], pos[1], pos[2], pos[0] // 32, pos[2] // 32))
                out.append("      first words: " + words[(prof, v)])
    if calls:
        out.append("")
        out.append("CALLS (the first 30 of each are logged):")
        for label, (n, frm, ex) in sorted(calls.items(), key=lambda x: -x[1][0]):
            out.append("  %-34s %4d call(s)   e.g. %s" % (label, n, ex[0] if ex else ""))
            for a, k in frm.most_common(2):
                out.append("        from 0x%x %s (x%d)" % (a, owner.get(a & ~1, ""), k))
    return "\n".join(out) or "no probe lines in the log (was the probe mod installed, and the game started from a terminal?)"
