"""acnlb.cfg: what the runtime plugin (plugin/acnlb_runtime.cpp) reads.

[building] sections hold keys; a building's rooms follow as [page] sections (variant, jmp, entry = x, z, yaw, link = x, y, to, ax, ay, yaw).
"""


def _val(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v)
    return v


def config_text(b):
    out = ["# written by ACNL Builder -- do not edit by hand"]
    for bld in b.cfg["buildings"]:
        out += ["", "[building]"]
        for k, v in bld.items():
            if v is None or v == "" or k == "pages":
                continue
            out.append("%s = %s" % (k, _val(v)))
        for pg in bld.get("pages", []):
            out += ["", "[page]", "variant = %s" % pg["variant"], "jmp = %s" % pg["jmp"]]
            if pg.get("id"):
                out.append("id = %s" % pg["id"])
            if pg.get("entry"):
                out.append("entry = %s" % pg["entry"])
            out += ["link = %s" % l for l in pg.get("links", [])]
    for v in b.cfg.get("vehicles", []):
        out += ["", "[vehicle]"]
        for k, val in v.items():
            out.append("%s = %s" % (k, _val(val)))
    if b.cfg.get("characters"):
        out += ["", "[characters]"] + ["%s = %d, %s" % (k, prof, v) for k, prof, v in b.cfg["characters"]]
    import os
    tr = [t for t in (os.environ.get("ACNLB_TRACE") or "").split(",") if t.strip()]
    if tr:
        out += ["", "[trace]"] + ["hook = %s" % t.replace(":", ", ") for t in tr]
    for o in b.cfg.get("outfits", []):
        out += ["", "[outfit]", "villager = %s" % o["villager"], "id = %s" % o["id"], "model = %s" % o["model"], "variant = %s" % o["variant"]]
    return "\n".join(out) + "\n"
