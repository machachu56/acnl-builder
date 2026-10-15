import argparse
import os
import sys

from . import build, env, project


def _map(a):
    import bisect
    from . import gamemap, xref
    gm = gamemap.load()
    if a.find:
        for n in gm.find(a.find):
            c = gm.classes[n]
            print("%-40s vtable 0x%x  %2d slots  %s" % (n, c["vtable"], len(c["methods"]), ("< " + ", ".join(c["bases"])) if c["bases"] else ""))
    elif a.name:
        c = gm.classes.get(a.name)
        if not c:
            raise SystemExit("no class %r: try --find" % a.name)
        x = xref.load()
        print("%s  vtable 0x%x  bases %s" % (a.name, c["vtable"], c["bases"] or "-"))
        for i, m in enumerate(c["methods"]):
            f = m & ~1
            k = bisect.bisect_right(x.starts, f)
            size = (x.starts[k] - f) if k < len(x.starts) else 0
            print("  #%-3d 0x%08x%s  ~%4d bytes  %2d caller(s)" % (i, f, " (thumb)" if m & 1 else "", size, len(x.callers_of(f))))
    elif a.string:
        x = xref.load()
        for addr, s, users in x.users_of_string(a.string)[:40]:
            print("0x%x  %r" % (addr, s))
            for u in users[:8]:
                owner = [n for n, c in gm.classes.items() if u in [m & ~1 for m in c["methods"]]]
                print("     used by function 0x%x %s" % (u, ("(method of " + ", ".join(owner[:3]) + ")") if owner else ""))
    elif a.callers:
        x = xref.load()
        t = int(a.callers, 0)
        for f in x.callers_of(t & ~1):
            print("0x%x" % f)
    elif a.at:
        x = xref.load()
        v = int(a.at, 0)
        f = x.function_of(v)
        print("function starts at 0x%x" % f)
        for n, c in gm.classes.items():
            for i, m in enumerate(c["methods"]):
                if m & ~1 == f:
                    print("  %s::#%d (vtable 0x%x)" % (n, i, c["vtable"]))
    else:
        print("classes: %d, e.g. python3 -m acnlb map --find Weather" % len(gm.classes))


def main():
    ap = argparse.ArgumentParser(prog="acnlb", description="ACNL Builder: design mods for the ACNL recomp")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="start the editor in your browser")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true")
    e = sub.add_parser("export", help="build a project into exports/<id>.acmod")
    e.add_argument("project")
    e.add_argument("--install", action="store_true", help="also copy it into the game's mods folder")
    e.add_argument("-o", "--out")
    m = sub.add_parser("map", help="explore the game's code: classes, virtual methods, strings, callers (needs your dump)")
    m.add_argument("name", nargs="?", help="a class name: lists its virtual methods")
    m.add_argument("--find", help="classes whose name contains this")
    m.add_argument("--string", help="strings containing this, and the functions that use them")
    m.add_argument("--callers", help="functions that call this address")
    m.add_argument("--at", help="the function an address belongs to, and the classes it is a method of")
    p = sub.add_parser("probe", help="make a tiny mod that logs what the game does (docs/HOOKS.md)")
    p.add_argument("--class", dest="classes", action="append", default=[], help="log calls of this class' virtual methods")
    p.add_argument("--hook", action="append", default=[], help="log calls of the function at this address")
    p.add_argument("--actors", action="store_true", help="log every actor the game creates")
    p.add_argument("--install", action="store_true")
    r = sub.add_parser("probe-report", help="summarise a game log written with the probe mod")
    r.add_argument("log")
    r.add_argument("--save", action="store_true", help="add the actors of this log to the names scripts can use")
    f = sub.add_parser("fslog-report", help="which game files were read in each place (run the game with ACNL_FSLOG=1)")
    f.add_argument("log")
    f.add_argument("--find", help="only the places that read a file whose name contains this")
    sub.add_parser("list", help="list projects")
    sub.add_parser("doctor", help="check the toolchain")
    a = ap.parse_args()
    if a.cmd == "serve":
        from .server import serve
        serve(a.port, not a.no_browser)
    elif a.cmd == "export":
        rep = build.export(a.project, a.out, a.install)
        for line in rep["log"]:
            print(" ", line)
        print("%s: %d files, %d KiB" % (rep["path"], rep["files"], rep["bytes"] >> 10))
        if rep.get("installed"):
            print("installed:", rep["installed"])
    elif a.cmd == "map":
        _map(a)
    elif a.cmd == "probe":
        from . import probe
        out, n = probe.build_probe(a.classes, [int(x, 0) for x in a.hook], a.actors)
        print("%s: %d function(s) hooked%s" % (out, n, ", actors logged" if a.actors else ""))
        if a.install:
            import shutil
            os.makedirs(build.install_dir(), exist_ok=True)
            shutil.copy(out, os.path.join(build.install_dir(), "probe.acmod"))
            print("installed in", build.install_dir())
        print("Start the game from a terminal, play, save its output, then: python3 -m acnlb probe-report <log>")
    elif a.cmd == "probe-report":
        from . import probe
        text = open(a.log, encoding="utf-8", errors="replace").read()
        print(probe.report(text))
        if a.save:
            print("\n%d new actor name(s) saved: scripts can use them (@on_actor(\"ClassName\"))" % probe.save_actors(text))
    elif a.cmd == "fslog-report":
        from . import fslog
        print(fslog.report(open(a.log, encoding="utf-8", errors="replace").read(), a.find))
    elif a.cmd == "list":
        for p in project.list_projects():
            print("%-20s %s" % (p["id"], p["title"]))
    elif a.cmd == "doctor":
        for k, v in env.toolchain_status().items():
            print("%-8s %s" % (k, v or "MISSING"))
        sys.exit(0)


main()
