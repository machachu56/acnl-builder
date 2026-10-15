"""Scripts: the project's scripts, checked and compiled into acnlb.script for the runtime plugin (see docs/SCRIPTING.md).

{"id": "night_shift", "name": "Isabelle's night shift", "enabled": true, "code": "from acnl import *\\n..."}
All enabled scripts are checked together (one error stops the export: it is better fixed in the editor than in the game).
"""
from ..script import compiler, context

NEEDS_TEST = "uses %s(), which is implemented but whose effect in the game has not been seen yet"


SPARE = "spare"            # a spare slot: one of the furniture actors the game creates in the room (no character is replaced)
FTR_FIRST, FTR_LAST = 0xBB, 0xEB


def cast_source(proj):
    """Python for the "Characters" cards of the interiors. Each entry takes over a slot of the room:
    "Tom Nook" / "Honma" / "Takumi" (the three people the game creates; the person there is replaced or removed) or "spare"
    (one of the furniture actors the game creates: nobody is replaced, a character appears in its place).
    sc["cast"] = [{"replace": "Honma"|"spare", "with": "Isabelle", "room": "", "x": 8, "y": 7, "from": "22:00", "to": "06:00",
                   "away": true, "villager": "sza", "outfit": "night"}]"""
    from ..script import context
    out, n = [], 0
    for sc in proj.get("interiors", []):
        entries = sc.get("cast") or []
        for bld in [x for x in proj.get("buildings", []) if x.get("interior") == sc["id"]]:
            bid, spares = bld["id"], []
            for c in entries:
                n += 1
                when = ' and time_between("%s", "%s")' % (c["from"], c["to"]) if c.get("from") and c.get("to") else ""
                here = ('in_room("%s", "%s")' % (bid, c["room"]) if c.get("room") else 'in_building("%s")' % bid) + when
                body = ""
                if c.get("with") and c.get("villager") and c.get("outfit"):
                    body += '        wear("%s", "%s")\n' % (c["villager"], c["outfit"])
                body += '        become("%s")\n' % c["with"] if c.get("with") else "        hide_actor()\n"
                if c.get("with") and c.get("x") is not None and c.get("y") is not None:
                    body += "        place_actor(%d, %d)\n" % (int(c["x"]), int(c["y"]))
                if c.get("replace") == SPARE:
                    spares.append((here, body))
                else:
                    out.append('@on_actor("%s")\ndef cast_%d():\n    if %s:\n%s' % (c["replace"], n, here, body))
                if c.get("with") and (c.get("away") or (c.get("villager") and c.get("outfit"))):
                    lines = ""
                    if c.get("villager") and c.get("outfit"):
                        lines += '    if not in_building("%s"):\n        wear_default("%s")\n' % (bid, c["villager"])      # elsewhere she keeps her usual clothes
                    if c.get("away"):
                        lines += '    if not in_building("%s")%s:\n        hide_actor()\n' % (bid, when)
                    out.append('@on_actor("%s")\ndef cast_%d_elsewhere():\n%s' % (c["with"], n, lines))
            if spares:
                var = "spare_" + bid
                lines = '    n = get_var("%s")\n    set_var("%s", n + 1)\n' % (var, var)
                for k, (here, body) in enumerate(spares):
                    lines += "    %s n == %d and %s:\n%s" % ("if" if k == 0 else "elif", k, here, body.replace("        ", "        ", 1))
                out.append("@on_actor(0x%x, last=0x%x)\ndef spare_slots_%s():\n%s" % (FTR_FIRST, FTR_LAST, bid, lines))
                out.append('@on_enter("%s")\ndef reset_spare_slots_%s():\n    set_var("%s", 0)\n' % (bid, bid, var))
                from ..script import context as ctxmod
                for r in ctxmod.rooms_of(proj, bld):
                    out.append('@on_room("%s", "%s")\ndef reset_spare_slots_%s_%s():\n    set_var("%s", 0)\n' % (bid, r, bid, r, var))
    return "from acnl import *\n\n" + "\n".join(out) if out else ""


def compile(b):
    scripts = [s for s in b.proj.get("scripts", []) if s.get("enabled", True) and (s.get("code") or "").strip()]
    generated = cast_source(b.proj)
    if generated:
        scripts.append({"id": "characters", "name": "Characters (Interiors tab)", "code": generated})
    if not scripts:
        return
    ctx = context.build_ctx(b.proj)
    # one program from every script: handlers are concatenated, strings and variables shared
    merged = compiler.Program()
    errors = []
    for s in scripts:
        comp = compiler.Compiler(ctx)
        comp.prog = merged
        n0 = len(merged.diags)
        comp.compile(s["code"])
        for d in merged.diags[n0:]:
            if d.severity == "error":
                errors.append("script %s, %s" % (s.get("name") or s["id"], d))
    if errors:
        raise ValueError("scripts have errors:\n" + "\n".join(errors))
    blob = merged.encode()
    if len(blob) > 24000:
        raise ValueError("the scripts are too big for the game (%d bytes, at most 24000)" % len(blob))
    from ..script import vm
    loaded = vm.Loaded(blob)
    for h, hd in zip(merged.handlers, loaded.handlers):
        from ..script.check import timeline
        for seg in timeline(loaded, hd, merged.strings[h.s1] if h.s1 != 0xFFFF else None, merged.strings[h.s2] if h.s2 != 0xFFFF and h.kind in ("enter", "room") else None):
            if seg["error"]:
                raise ValueError("script handler %s would fail at %s-%s: %s" % (h.name, seg["start"], seg["end"], seg["error"]))
    b.add("acnlb.script", blob)
    b.cfg["scripts"] = len(merged.handlers)
    b.note("scripts: %d trigger(s), %d bytes" % (len(merged.handlers), len(blob)))
    import ast
    from ..script import actions as A
    used = set()
    for s in scripts:
        used |= {n.func.id for n in ast.walk(ast.parse(s["code"])) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    for name in sorted(used):
        nat = A.BY_NAME.get(name)
        if nat and nat.status == "needs-test":
            b.warn("scripts: " + NEEDS_TEST % name)
