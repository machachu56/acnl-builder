"""Scripts: the project's scripts, checked and compiled into acnlb.script for the runtime plugin (see docs/SCRIPTING.md).

{"id": "night_shift", "name": "Isabelle's night shift", "enabled": true, "code": "from acnl import *\\n..."}
All enabled scripts are checked together (one error stops the export: it is better fixed in the editor than in the game).
"""
from ..script import compiler, context

NEEDS_TEST = "uses %s(), which is implemented but whose effect in the game has not been seen yet"


ADD = "add"                # an extra character: the game's own stay
# special characters' model files (/Npc/Special/Model/<code>.bcres), seen in the game: a character added with @on_spawn takes the model
# the room loaded for the character it was spawned with, so the room gets that file replaced by the added character's own
MODEL_CODE = {"Isabelle": "sza", "Tom Nook": "rci"}
# characters the game itself creates anywhere with a model code of their own (the plugin spawns them the same way): no other character's
# model is touched, nobody is hidden for them, and any number can be added. name -> (profile class, model code)
# (AcNpcSpSecretaryOut, the class the game uses for that, crashed in Nook's Homes: its code is not loaded there. The class has to be one
# the place has loaded; Isabelle's counter class is.)
SPAWNABLE = {"Isabelle": ("Isabelle", "sza")}
# the conversation each added character runs when the player talks to them (Isabelle away from her counter: NPC_Secretary_Inside, whose
# line 029 is "talk to me over the counter"); a conversation chosen for them in the Characters card is written on this one
TALK_FLOW = {"Isabelle": "/Script/Flow/NPC_Secretary_Inside.msbf"}
SPARE = "spare"            # a spare slot: one of the furniture actors the game creates in the room (no character is replaced)
FTR_FIRST, FTR_LAST = 0xBB, 0xEB
HOST = "Tom Nook"                    # the character added characters are spawned together with, by default


def hide_body(proj, actor, room):
    """the body that takes `actor` out of a room: the game does not create them there (the rooms of a building are joined by doors of
    their own, which need nobody; the added characters are spawned at the moment the game would have created them, all the same)"""
    return "        hide_actor()\n"


def cast_source(proj):
    """Python for the "Characters" cards of the interiors. Each entry takes over a slot of the room:
    "Tom Nook" / "Honma" / "Takumi" (the three people the game creates; the person there is replaced or removed) or "spare"
    (one of the furniture actors the game creates: nobody is replaced, a character appears in its place).
    sc["cast"] = [{"replace": "Honma"|"spare", "with": "Isabelle", "room": "", "x": 8, "y": 7, "from": "22:00", "to": "06:00",
                   "away": true, "villager": "sza", "outfit": "night", "talk": "isabelle_hello"}]
    "talk" is a conversation of the Events tab: it is switched on while the player is where (and when) the character is, and
    off everywhere else (in the town hall she says her usual lines again)."""
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
                body += '        become("%s")\n' % c["with"] if c.get("with") else hide_body(proj, c.get("replace"), c.get("room"))
                if c.get("with") and c.get("x") is not None and c.get("y") is not None:
                    body += "        place_actor(%d, %d)\n" % (int(c["x"]), int(c["y"]))
                if c.get("replace") == ADD and c.get("with") in SPAWNABLE:
                    # an extra character with its own model: spawned when the game spawns the room's host, at its tile
                    cls = SPAWNABLE[c["with"]][0]
                    tile = ("%d, %d" % (int(c["x"]), int(c["y"]))) if c.get("x") is not None and c.get("y") is not None else "8, 8"
                    dress = '        wear("%s", "%s")\n' % (c["villager"], c["outfit"]) if c.get("villager") and c.get("outfit") else ""
                    out.append('@on_spawn("%s")\ndef add_%d():\n    if %s:\n%s        add_actor("%s", %s)\n' % (c.get("trigger") or HOST, n, here, dress, cls, tile))
                    if dress:
                        out.append('@on_actor("%s")\ndef add_%d_elsewhere():\n    if not in_building("%s"):\n        wear_default("%s")\n' % (cls, n, bid, c["villager"]))
                elif c.get("replace") == ADD and c.get("with") and not c.get("legacy_swap"):
                    raise ValueError("Characters: %s cannot be added yet: the game's way of creating them with their own model is known only for %s"
                                     % (c["with"], ", ".join(sorted(SPAWNABLE))))
                elif c.get("replace") == ADD:
                    # (older projects) an extra character spawned together with `trigger`, wearing the model the room loaded for it
                    trig = c.get("trigger") or "Tom Nook"
                    tile = ("%d, %d" % (int(c["x"]), int(c["y"]))) if c.get("x") is not None and c.get("y") is not None else "8, 8"
                    out.append('@on_spawn("%s")\ndef add_%d():\n    if %s:\n        add_actor("%s", %s)\n' % (trig, n, here, c["with"], tile))
                    # the character it is spawned with is not shown in that room: it would wear the added character's model
                    out.append('@on_actor("%s")\ndef add_%d_frees_its_model():\n    if %s:\n%s' % (trig, n, here, hide_body(proj, trig, c.get("room"))))
                elif c.get("replace") == SPARE:
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
            for c in entries:
                ev = next((e for e in proj.get("events", []) if e["id"] == c.get("talk")), None) if c.get("with") else None
                if not ev or ev.get("scope") != "script":
                    continue                    # a conversation for a building or for everywhere is on by itself
                n += 1
                when = ' and time_between("%s", "%s")' % (c["from"], c["to"]) if c.get("from") and c.get("to") else ""
                here = ('in_room("%s", "%s")' % (bid, c["room"]) if c.get("room") else 'in_building("%s")' % bid) + when
                body = '    if %s:\n        conversation_on("%s")\n    else:\n        conversation_off("%s")\n' % (here, ev["id"], ev["id"])
                out.append('@on_enter("%s")\ndef talk_%d():\n%s' % (bid, n, body))
                for r in context.rooms_of(proj, bld):
                    out.append('@on_room("%s", "%s")\ndef talk_%d_%s():\n%s' % (bid, r, n, r, body))
                out.append('@on_leave("%s")\ndef talk_%d_leave():\n    conversation_off("%s")\n' % (bid, n, ev["id"]))
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


def stage_added_models(b):
    """for every added character: the room where it is added loads the added character's model in place of the model of the character it is
    spawned with (with the outfit chosen for it), in that room's variant only"""
    from . import interiors as intfeat, textures as texmod
    from .. import project, rom
    for sc in b.proj.get("interiors", []):
        for c in sc.get("cast") or []:
            if c.get("replace") != ADD or not c.get("with") or c["with"] in SPAWNABLE:
                continue
            trig = c.get("trigger") or "Tom Nook"
            src, dst = MODEL_CODE.get(c["with"]), MODEL_CODE.get(trig)
            if not src or not dst:
                raise ValueError("Characters: adding %s next to %s is not possible yet: the model file of %s is not known"
                                 % (c["with"], trig, c["with"] if not src else trig))
            data = rom.read("/Npc/Special/Model/%s.bcres" % src)
            if c.get("villager") and c.get("outfit"):
                v = next((x for x in b.proj["villagers"] if x["id"] == c["villager"]), None)
                o = next((x for x in (v or {}).get("outfits") or [] if x["id"] == c["outfit"]), None)
                if o:
                    data = texmod.replace_in(data, {n: texmod.load_png(project.asset_path(b.proj["id"], png)) for n, png in o["textures"].items()})
            for bld in [x for x in b.proj["buildings"] if x.get("interior") == sc["id"]]:
                rooms = [s["id"] for s in intfeat.reachable(b.proj, bld["interior"])]
                if c.get("room"):
                    if c["room"] not in rooms:
                        continue
                    variant = intfeat.page_variant(bld, rooms.index(c["room"]))
                else:
                    variant = "b_" + bld["id"]
                b.put("/Npc/Special/Model/%s.bcres" % dst, data, variant)
                b.note("characters: %s added in %s (%s), %s's model swapped for theirs there" % (c["with"], c.get("room") or bld["id"], variant, trig))


def characters_cfg(proj):
    """[characters] of acnlb.cfg: the model code of each spawnable character added, and the conversation it talks with"""
    from . import events as evmod
    out, seen = [], set()
    for sc in proj.get("interiors", []):
        for c in sc.get("cast") or []:
            if c.get("replace") != ADD or c.get("with") not in SPAWNABLE:
                continue
            cls, code = SPAWNABLE[c["with"]]
            prof = context.all_actors(proj)[cls]
            if ("spawn", prof) not in seen:
                seen.add(("spawn", prof))
                out.append(("spawn", prof, code))
            ev = next((e for e in proj.get("events", []) if e["id"] == c.get("talk")), None)
            if ev and ("talk", prof) not in seen:
                flow = evmod.normalise(ev)[0]
                seen.add(("talk", prof))
                out.append(("talk", prof, flow.rsplit("/", 1)[-1][:-5]))
    return out


def check_talk(b):
    """a conversation given to an added character must be written on the conversation that character runs"""
    for sc in b.proj.get("interiors", []):
        for c in sc.get("cast") or []:
            ev = next((e for e in b.proj.get("events", []) if e["id"] == c.get("talk")), None)
            want = TALK_FLOW.get(c.get("with")) if c.get("replace") == ADD else None
            if ev and want and ev.get("flow") != want:
                b.warn("Characters: %s talks with %s, but the conversation %s is written on %s: it will not play (choose it again in the "
                       "Characters card, or pick %s for it in Events)" % (c["with"], want.rsplit("/", 1)[-1][:-5], ev["id"],
                                                                         (ev.get("flow") or "?").rsplit("/", 1)[-1][:-5], want.rsplit("/", 1)[-1][:-5]))


def compile(b):
    stage_added_models(b)
    check_talk(b)
    b.cfg["characters"] = characters_cfg(b.proj)
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
