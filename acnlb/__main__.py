import argparse
import sys

from . import build, env, project


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
    elif a.cmd == "list":
        for p in project.list_projects():
            print("%-20s %s" % (p["id"], p["title"]))
    elif a.cmd == "doctor":
        for k, v in env.toolchain_status().items():
            print("%-8s %s" % (k, v or "MISSING"))
        sys.exit(0)


main()
