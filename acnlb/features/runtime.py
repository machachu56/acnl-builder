"""acnlb.cfg: what the runtime plugin (plugin/acnlb_runtime.cpp) reads."""


def config_text(b):
    out = ["# written by ACNL Builder -- do not edit by hand"]
    for bld in b.cfg["buildings"]:
        out.append("")
        out.append("[building]")
        for k, v in bld.items():
            if v is None or v == "":
                continue
            if isinstance(v, bool):
                v = int(v)
            if isinstance(v, (list, tuple)):
                v = ", ".join(str(x) for x in v)
            out.append("%s = %s" % (k, v))
    return "\n".join(out) + "\n"
