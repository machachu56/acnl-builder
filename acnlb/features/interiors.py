"""Interiors: the rooms (pages) of each building's interior: a room model + collision grid per page.

A building's `interior` is its entrance page. A page may have `links` (see interior.SCENE_DEFAULT) to other
pages of the project: each becomes a RomFS variant `b_<building>_p<n>` the runtime plugin switches on when the
player goes through a link tile. Pages are numbered in the order they are found from the entrance.
"""
import os

from .. import env, interior, project, rom
from . import textures as texmod

YAW = interior.YAW                                                      # the direction the player looks on arrival


def asset_loader(proj):
    """asset name -> pixels of a PNG; `.bytes(name)` -> the raw file (3D models and what they refer to)"""
    cache = {}

    def load(name):
        if name not in cache:
            f = project.asset_path(proj["id"], name)
            if not os.path.isfile(f):
                raise interior.SceneError("missing image asset %s" % name)
            cache[name] = texmod.load_png(f)
        return cache[name]

    def raw(name):
        try:
            f = project.asset_path(proj["id"], name)
        except ValueError:
            return None
        if not os.path.isfile(f):
            return None
        with open(f, "rb") as fp:
            return fp.read()
    load.bytes = raw
    return load


def scene_by_id(proj, sid):
    for s in proj["interiors"]:
        if s["id"] == sid:
            return s
    raise ValueError("interior %r does not exist" % sid)


def page_variant(bld, k):
    return "b_%s_p%d" % (bld["id"], k)


def reachable(proj, entry_id):
    """[scene] of the entrance page and everything linked from it, in discovery order"""
    out, seen, todo = [], set(), [entry_id]
    while todo:
        sid = todo.pop(0)
        if sid in seen:
            continue
        seen.add(sid)
        sc = scene_by_id(proj, sid)
        out.append(sc)
        for k in sc.get("links") or []:
            if k.get("to"):
                todo.append(k["to"])
    return out


def check_links(pages, built):
    """every link leads to a floor tile of its destination that is neither blocked nor a link itself"""
    index = {s["id"]: i for i, s in enumerate(pages)}
    for sc, b in zip(pages, built):
        for k in sc.get("links") or []:
            if k.get("to") not in index:
                raise ValueError("interior %s: link %s leads to a room that does not exist" % (sc["id"], k.get("id")))
            dest = built[index[k["to"]]]
            a = tuple(k.get("arrive") or (-1, -1))
            if not dest.plan.floor(a) or a in dest.plan.solid or a in dest.plan.link:
                raise ValueError("interior %s: link %s arrives on tile %d,%d of %s, which is not free floor (or is a link tile)"
                                 % (sc["id"], k.get("id"), a[0], a[1], k["to"]))


def out_yaw(spec, plan, tile):
    """the way the player walks out through a link tile: away from the room's main area next to it (the game's door walk)"""
    main = spec.get("main") or "main"
    x, y = tile
    inside = lambda t: plan.owner.get(t) == main and t not in plan.link
    # (step out, name): the room's floor behind the tile, and no floor of it ahead
    sides = (((0, -1), "north"), ((0, 1), "south"), ((1, 0), "east"), ((-1, 0), "west"))
    for (dx, dy), away in sides:
        if inside((x - dx, y - dy)) and (plan.owner.get((x + dx, y + dy)) != main or (x + dx, y + dy) in plan.solid):
            return YAW[away]
    for (dx, dy), away in sides:
        if inside((x - dx, y - dy)):
            return YAW[away]
    return YAW["north"]


def compile(b):
    for bld in b.proj["buildings"]:
        if not bld.get("interior"):
            continue
        pages = reachable(b.proj, bld["interior"])
        if len(pages) > 8:
            raise ValueError("%s: at most 8 rooms per building (found %d)" % (bld["id"], len(pages)))
        built = []
        for spec in pages:
            try:
                built.append(interior.build_scene(spec, rom.read, asset_loader(b.proj)))
            except interior.SceneError as e:
                raise ValueError("interior %s: %s" % (spec["id"], e))
        check_links(pages, built)
        index = {s["id"]: i for i, s in enumerate(pages)}
        for spec in pages:                    # the player arrives from another room on a door tile, as through the real entrance
            for lk in spec.get("links") or []:
                built[index[lk["to"]]].plan.arrive.add(tuple(lk["arrive"]))
        cfg_pages = []
        for k, (spec, bt) in enumerate(zip(pages, built)):
            if k > 0:
                # only the entrance room has a way out to the town: in the other rooms the doorway of the plan is closed in the collision
                # (a door/exit next to a link tile kept the game from ever leaving by the link, seen in game), the links are the way out
                if not spec.get("links"):
                    raise ValueError("room %s has no link back: the player could not leave it (add a door to another room in Interiors)" % spec["id"])
                bt.plan.solid |= set(bt.plan.door) | set(bt.plan.exit)
                bt.plan.door, bt.plan.exit = [], []
            links, doors = [], []
            for lk in spec.get("links") or []:
                ax, ay = lk["arrive"]
                yaw = YAW.get(lk.get("face", "north"), 32768)
                door = (index[lk["to"]], ax, ay, yaw)
                if door not in doors:
                    doors.append(door)
                for (x, y) in lk.get("tiles", []):
                    links.append("%d, %d, %d, %d, %d, %d, %d" % (x, y, index[lk["to"]], ax, ay, yaw, out_yaw(spec, bt.plan, (x, y))))
                    # door n of the room (the game's exit types 0x4007 + n; 0 is the front door): the plugin adds it to the scene's door table
                    bt.plan.link_attr[(x, y)] = 0x4007 + doors.index(door) + 1
            if len(doors) > 5:
                raise ValueError("interior %s: at most 5 different ways out to other rooms (has %d)" % (spec["id"], len(doors)))
            if len(links) > 8:
                raise ValueError("interior %s: at most 8 link tiles per room (has %d)" % (spec["id"], len(links)))
            room, jmp = interior.room_files(rom.read(interior.ROOM), bt)
            var = page_variant(bld, k)
            b.put(interior.ROOM, room, var)
            name = "idr_%s_p%d.jmp" % (bld["id"], k)
            b.add(name, jmp)
            page = {"variant": var, "jmp": name, "links": links, "id": spec["id"]}
            if k == 0 and bt.plan.spawn:                  # an entrance that is not on the south edge: say where the player appears
                sx, sz, yaw = bt.plan.spawn
                page["entry"] = "%d, %d, %d" % (sx, sz, yaw)
            cfg_pages.append(page)
            b.note("room %s: %d vertices, %d triangles" % (spec["id"], len(bt.mesh.verts), len(bt.mesh.tris) // 3))
        quiet = None
        if len(pages) > 1:
            # arriving from another room is not walking in: the host does not greet again (the plugin switches this variant on then)
            from . import events as evmod
            host = evmod.FLOWS["Tanukichi"]
            quiet = "a_quiet_" + bld["id"]
            b.put(host["flow"], evmod.quiet_flow(rom.read(host["flow"]), host["first"]), quiet)
        for entry in b.cfg["buildings"]:
            if entry["id"] == bld["id"]:
                entry["pages"] = cfg_pages
                if quiet:
                    entry["quiet"] = quiet
