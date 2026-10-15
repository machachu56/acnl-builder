"""Which game files were read, place by place: the log of a run with  ACNL_FSLOG=1  (and a probe mod, which marks the places).

    ACNL_FSLOG=1 ./acnl game.3ds 2>&1 | tee run.log
    python3 -m acnlb fslog-report run.log [--find sza]

The runtime logs `fsread <offset in the game image> <bytes>` for every RomFS read; this maps each offset to the file it is in and groups
the reads by the scene the probe saw loading. `--find` lists which scenes read files whose name contains the text. Comparing the
town hall with the Baisodrome shows what a character needs that the second place does not load.
"""
import bisect
import collections
import re

from . import env


def index():
    from . import rom
    rom._open()
    items = sorted((o, s, p) for p, (o, s) in rom._index.items())
    return [i[0] for i in items], items


def report(text, find=None):
    offs, items = index()
    scene, per = "?", collections.OrderedDict()
    for line in text.splitlines():
        m = re.search(r"probe: actor profile=\d+ arg=\w+ obj=\w+ vtable=\w+ scene=(\d+)/(\d+)", line)
        if m:
            scene = "%s/%s" % (m.group(1), m.group(2))
            continue
        m = re.search(r"fsread\s+(\w+) (\w+)", line)
        if not m:
            continue
        off = int(m.group(1), 16)
        if off == (1 << 64) - 1:
            continue
        i = bisect.bisect_right(offs, off) - 1
        if i >= 0 and items[i][0] <= off < items[i][0] + items[i][1]:
            per.setdefault(scene, collections.OrderedDict()).setdefault(items[i][2], 0)
            per[scene][items[i][2]] += 1
    out = []
    for sc, files in per.items():
        if find:
            hits = [f for f in files if find.lower() in f.lower()]
            if hits:
                out.append("scene %s: %s" % (sc, ", ".join(hits[:12])))
        else:
            npc = [f for f in files if f.startswith(("/Npc/", "/Script/Flow/", "/Script/Talk/"))]
            out.append("scene %s: %d files read; characters/conversations: %s" % (sc, len(files), ", ".join(f.rsplit("/", 1)[-1] for f in npc[:25]) or "-"))
    return "\n".join(out) or "no `fsread` lines: run the game with ACNL_FSLOG=1"
