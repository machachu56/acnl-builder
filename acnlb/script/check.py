"""Check a script like the game would run it: compile, then dry-run every trigger through the day."""
from . import actions as A
from . import compiler, vm

DESC = {"enter": "when the player enters %s", "leave": "when the player leaves %s", "room": "when the player enters room %s of %s",
        "actor": "when the game creates actor %s", "call": "when the game calls 0x%x"}


def trigger_text(h, prog, names=None):
    s = prog.strings
    if h.kind == "enter":
        return DESC["enter"] % ("%s, room %s" % (s[h.s1], s[h.s2]) if h.s2 != 0xFFFF else s[h.s1])
    if h.kind == "leave":
        return DESC["leave"] % s[h.s1]
    if h.kind == "room":
        return DESC["room"] % (s[h.s2], s[h.s1])
    if h.kind == "actor":
        nm = (names or {}).get(h.num)
        return DESC["actor"] % ((nm or "0x%x" % h.num) if h.s2 == 0xFFFF else "0x%x to 0x%x" % (h.num, h.s2))
    return DESC["call"] % h.num


def timeline(prog_loaded, hdict, building, room, step=30):
    """[(from "HH:MM", to "HH:MM", [what happens])] over a day, merged"""
    slots = []
    for i in range(0, 24 * 60, step):
        w = vm.World(hour=i // 60, minute=i % 60, building=building, room=room, weekday=2)
        try:
            vm.run(prog_loaded, hdict, w)
            slots.append((i, tuple(w.trace), None))
        except vm.VMError as e:
            slots.append((i, (), str(e)))
    out = []
    for i, tr, er in slots:
        if out and out[-1][2] == tr and out[-1][3] == er:
            out[-1][1] = i + step
        else:
            out.append([i, i + step, tr, er])
    f = lambda m: "%02d:%02d" % ((m // 60) % 24, m % 60)
    return [dict(start=f(a), end=f(b), does=list(tr), error=er) for a, b, tr, er in out]


def check(source, ctx=None):
    """-> {"ok", "diagnostics": [...], "handlers": [{name, kind, trigger, line, timeline}], "bytes", "program": bytes|None}"""
    prog = compiler.compile_source(source, ctx)
    res = {"diagnostics": [], "handlers": [], "bytes": 0, "program": None}
    names = {}
    for k, v in sorted(((ctx.actor_names if ctx else {}) or {}).items(), reverse=True):
        names[v] = k                                     # friendly names win over class names
    for k, v in ((ctx.actor_names if ctx else {}) or {}).items():
        if k[:1].isupper() and not k.startswith(("Ac", "Bs", "Sc")):
            names[v] = k
    if prog.ok:
        blob = prog.encode()
        loaded = vm.Loaded(blob)
        res["bytes"] = len(blob)
        for h, hd in zip(prog.handlers, loaded.handlers):
            b = prog.strings[h.s1] if h.s1 != 0xFFFF else None
            r = prog.strings[h.s2] if h.s2 != 0xFFFF and h.kind in ("enter", "room") else None
            tl = timeline(loaded, hd, b, r)
            for seg in tl:
                if seg["error"]:
                    prog.diags.append(compiler.Diag(h.line, 0, "%s would fail at %s-%s: %s" % (h.name, seg["start"], seg["end"], seg["error"]), "", "error"))
                    break
            res["handlers"].append(dict(name=h.name, kind=h.kind, line=h.line, trigger=trigger_text(h, prog, names), timeline=tl))
        if len(blob) > 24000:
            prog.diags.append(compiler.Diag(1, 0, "the scripts are too big for the game (%d bytes, at most 24000)" % len(blob)))
        if prog.ok:
            res["program"] = blob
    for d in prog.diags:
        res["diagnostics"].append(d.to_json())
    # status notes: which built-ins used are not yet seen working in the game
    used = {n for n in _called(source)}
    for name in sorted(used):
        nat = A.BY_NAME.get(name)
        if nat and nat.status != "ready" and prog.ok:
            res["diagnostics"].append(compiler.Diag(0, 0, "%s() is %s" % (name, "advanced: it touches the game's memory directly" if nat.status == "advanced" else "not yet tested in the game: it should work but nobody has seen it run"), "", "info").to_json())
    res["ok"] = prog.ok and not any(d["severity"] == "error" for d in res["diagnostics"])
    return res


def _called(source):
    import ast
    try:
        return [n.func.id for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    except SyntaxError:
        return []
