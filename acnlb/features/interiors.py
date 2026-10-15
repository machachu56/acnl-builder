"""Interiors: the room model + collision grid of each building's interior (RomFS variant of that building)."""
import os

from .. import env, interior, project, rom
from . import textures as texmod


def asset_loader(proj):
    cache = {}

    def load(name):
        if name not in cache:
            f = project.asset_path(proj["id"], name)
            if not os.path.isfile(f):
                raise interior.SceneError("missing image asset %s" % name)
            cache[name] = texmod.load_png(f)
        return cache[name]
    return load


def scene_by_id(proj, sid):
    for s in proj["interiors"]:
        if s["id"] == sid:
            return s
    raise ValueError("interior %r does not exist" % sid)


def compile(b):
    from .buildings import variant_of
    for bld in b.proj["buildings"]:
        if not bld.get("interior"):
            continue
        spec = scene_by_id(b.proj, bld["interior"])
        try:
            built = interior.build_scene(spec, rom.read, asset_loader(b.proj))
        except interior.SceneError as e:
            raise ValueError("interior %s: %s" % (spec["id"], e))
        room, jmp = interior.room_files(rom.read(interior.ROOM), built)
        b.put(interior.ROOM, room, variant_of(bld))
        b.add("idr_%s.jmp" % bld["id"], jmp)
        b.note("interior %s: %d vertices, %d triangles" % (spec["id"], len(built.mesh.verts), len(built.mesh.tris) // 3))
