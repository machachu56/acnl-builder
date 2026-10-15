"""Scripts: the project's scripts, checked and compiled into acnlb.script for the runtime plugin (see docs/SCRIPTING.md).

{"id": "night_shift", "name": "Isabelle's night shift", "enabled": true, "code": "from acnl import *\\n..."}
All enabled scripts are checked together (one error stops the export: it is better fixed in the editor than in the game).
"""
from ..script import compiler, context

NEEDS_TEST = "uses %s(), which is implemented but whose effect in the game has not been seen yet"


def compile(b):
    scripts = [s for s in b.proj.get("scripts", []) if s.get("enabled", True) and (s.get("code") or "").strip()]
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
        for seg in timeline(loaded, hd, merged.strings[h.s1] if h.s1 != 0xFFFF else None, merged.strings[h.s2] if h.s2 != 0xFFFF else None):
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
