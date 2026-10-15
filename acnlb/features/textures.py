"""Texture replacements: {"file": "/Npc/Normal/Model/ant00.bcres", "name": "b0", "png": "name.png", "variant": null}"""
import io
import os

from .. import env, project, texfmt

env.setup_path()
from modkit import cgfx  # noqa: E402


def load_png(path):
    from PIL import Image
    im = Image.open(path).convert("RGBA")
    px = im.load()
    return [[px[x, y] for x in range(im.width)] for y in range(im.height)]


def to_png(rows):
    from PIL import Image
    h, w = len(rows), len(rows[0])
    im = Image.new("RGBA", (w, h))
    im.putdata([tuple(p) for r in rows for p in r])
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def replace_in(data, repl):
    """repl {texture name: rows} on a bcres -> new bytes"""
    by_name = {t.name: t for t in cgfx.textures(data)}
    new = {}
    for name, rows in repl.items():
        if name not in by_name:
            raise ValueError("no texture %r in the model (has: %s)" % (name, ", ".join(by_name)))
        new[name] = texfmt.replacement(rows, by_name[name])
    return cgfx.rebuild_textures(data, new)


def compile(b):
    groups = {}
    for e in b.proj["textures"]:
        groups.setdefault((e["file"], e.get("variant")), {})[e["name"]] = e
    for (path, variant), ents in groups.items():
        repl = {}
        for name, e in ents.items():
            f = project.asset_path(b.proj["id"], e["png"])
            if not os.path.isfile(f):
                raise ValueError("missing image %s for %s:%s" % (e["png"], path, name))
            repl[name] = load_png(f)
        b.put(path, replace_in(b.game(path, variant), repl), variant)
