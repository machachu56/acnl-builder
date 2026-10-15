"""Villagers: name, catchphrase and outfits of an existing villager (the plain skin is a texture edit, see textures).

{"id": "ant00", "name": {"en": "Cyrano", "fr": "..."}, "catchphrase": {"en": "ah-CHOO"},
 "outfits": [{"id": "work", "name": "Work clothes", "textures": {"b0": "outfit_ant00_work_b0.png"}}],
 "default_outfit": "work"}

A villager's clothes are painted on their body texture (b0), so an outfit is a replacement of that texture (and of
any other texture of the model you like). `default_outfit` is worn all the time. Every outfit is also staged as a
RomFS variant `outfit_<villager>_<outfit>` and listed in acnlb.cfg ([outfit]) so scripts can swap it in the game.
Personality dialogue is shared by every villager of a personality: edit it in the dialogue tab.
"""
import os

from .. import project, rom
from . import textures as texmod

NAME = "/Script/Str/STR_NNpc_name.umsbt"
HABIT = "/Script/Str/STR_NNpc_habit.umsbt"


def outfit_variant(vid, oid):
    return "outfit_%s_%s" % (vid, oid)


def model_path(v):
    return v.get("model") or "/Npc/Normal/Model/%s.bcres" % v["id"]


def _outfit_pixels(b, o, v):
    repl = {}
    for name, png in (o.get("textures") or {}).items():
        f = project.asset_path(b.proj["id"], png)
        if not os.path.isfile(f):
            raise ValueError("outfit %s of %s: missing image %s" % (o.get("id"), v["id"], png))
        repl[name] = texmod.load_png(f)
    return repl


def compile_outfits(b):
    unused = []
    for v in b.proj["villagers"]:
        model = model_path(v)
        plain = {e["name"]: e for e in b.proj["textures"] if e["file"] == model and not e.get("variant")}
        for o in v.get("outfits") or []:
            repl = _outfit_pixels(b, o, v)
            if not repl:
                continue
            if v.get("default_outfit") == o["id"]:
                b.put(model, texmod.replace_in(b.game(model), repl))
            base = {n: texmod.load_png(project.asset_path(b.proj["id"], e["png"])) for n, e in plain.items() if n not in repl}
            var = outfit_variant(v["id"], o["id"])
            b.put(model, texmod.replace_in(rom.read(model), {**base, **repl}), var)
            b.cfg.setdefault("outfits", []).append({"villager": v["id"], "id": o["id"], "model": model, "variant": var})
            if v.get("default_outfit") != o["id"]:
                unused.append("%s/%s" % (v["id"], o["id"]))
    if any("wear(" in (sc.get("code") or "") and sc.get("enabled", True) for sc in b.proj.get("scripts", [])):
        unused = []                                   # a script dresses them
    if unused:
        b.warn("outfits %s are in the mod but nothing wears them yet: only the default outfit shows until a script swaps one in" % ", ".join(unused))


def compile(b):
    compile_outfits(b)
    extra = []
    for v in b.proj["villagers"]:
        if any((v.get("name") or {}).values()):
            extra.append({"file": NAME, "label": v["id"], "text": v["name"]})
        if any((v.get("catchphrase") or {}).values()):
            extra.append({"file": HABIT, "label": v["id"], "text": v["catchphrase"]})
    b.proj["text"] = list(b.proj["text"]) + extra
