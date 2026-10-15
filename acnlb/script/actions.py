"""The scripting vocabulary: every function a script may call, in one table.

This table is the single source of truth: the compiler checks calls against it, the plugin's interpreter implements
the `id`s, the documentation (docs/SCRIPTING.md and the in-app reference) and the `acnl` stub module are generated
from it. To add a built-in, add a row here, implement the id in plugin/script_vm.h and in vm.py.

status
  ready          works with mechanisms the runtime/plugin are known to have (reading the clock, memory, switching variants)
  needs-test     implemented, but what the GAME does with it has not been seen yet (marked in the docs and the editor)
  advanced       raw access to the game's memory/registers: powerful, can crash the game
types of parameters
  int        any number expression          bool   a condition
  str        a text literal                 building / room / villager / outfit / actor   a name that must exist
  time       "HH:MM"                        addr   address of a function of the game (checked against the code map)
where
  handler kinds a call is allowed in: enter, leave, room, actor, call, any
"""
from collections import namedtuple

Native = namedtuple("Native", "id name params returns status where doc example")


def N(id, name, params, returns, status, where, doc, example=""):
    return Native(id, name, tuple(params), returns, status, where, doc, example)


ANY = ("any",)
NATIVES = [
    # ---- the clock (the game's own, from the shared page)
    N(0, "hour", [], "int", "ready", ANY, "The hour of the game's clock, 0-23.", "if hour() >= 22: ..."),
    N(1, "minute", [], "int", "ready", ANY, "The minute of the game's clock, 0-59."),
    N(2, "weekday", [], "int", "ready", ANY, "Day of the week: 0 = Monday ... 6 = Sunday."),
    N(3, "day", [], "int", "ready", ANY, "Day of the month, 1-31."),
    N(4, "month", [], "int", "ready", ANY, "Month, 1-12."),
    N(5, "year", [], "int", "ready", ANY, "The year, e.g. 2026."),
    # time_between(a, b) is expanded by the compiler (no id)
    # ---- where the player is
    N(6, "in_building", [("building", "building")], "bool", "ready", ANY, "True while the player is inside this building (any of its rooms).", 'if in_building("baisodrome"): ...'),
    N(7, "in_room", [("building", "building"), ("room", "room")], "bool", "ready", ANY, "True while the player is in this room of the building.", 'if in_room("baisodrome", "spa"): ...'),
    # ---- numbers
    N(8, "chance", [("percent", "int")], "bool", "ready", ANY, "True `percent` times out of 100 (a new roll each call).", "if chance(25): ..."),
    N(9, "random", [("n", "int")], "int", "ready", ANY, "A random whole number from 0 to n-1."),
    # ---- remembered values (kept while the game runs)
    N(10, "get_var", [("name", "str")], "int", "ready", ANY, "A remembered value (0 until it is set). Use it to keep a story state: visits, flags.", 'visits = get_var("visits")'),
    N(11, "set_var", [("name", "str"), ("value", "int")], None, "ready", ANY, "Remember a value.", 'set_var("visits", get_var("visits") + 1)'),
    N(12, "log", [("message", "str"), ("value", "int?")], None, "ready", ANY, "Write a line (and an optional number) in the game's log: the easiest way to see that a script runs.", 'log("welcome played", hour())'),
    # ---- characters and clothes
    N(13, "wear", [("villager", "villager"), ("outfit", "outfit")], None, "needs-test", ("enter", "leave", "room", "actor"),
      "Dress a villager in one of the outfits you made for them (Villagers tab). The new clothes show the next time the game loads that villager's model, e.g. when you walk into a place they are in.",
      'wear("ant00", "work_clothes")'),
    N(14, "wear_default", [("villager", "villager")], None, "needs-test", ("enter", "leave", "room", "actor", "spawn"), "Back to the villager's normal clothes (the default outfit, or the game's).", 'wear_default("ant00")'),
    N(15, "variant_on", [("name", "str")], None, "needs-test", ANY, "Switch on a RomFS variant of your mod by name (advanced: outfits and buildings have their own).", ""),
    N(16, "variant_off", [("name", "str")], None, "needs-test", ANY, "Switch a RomFS variant off.", ""),
    N(30, "conversation_on", [("conversation", "conversation")], None, "needs-test", ANY, "Switch on a conversation you wrote in the Events tab whose scope is “only when a script turns it on”: from now on the game's character says your lines. Takes effect the next time that conversation starts.", 'conversation_on("isabelle_hello")'),
    N(31, "conversation_off", [("conversation", "conversation")], None, "needs-test", ANY, "Switch that conversation off again (the game's own lines return).", 'conversation_off("isabelle_hello")'),
    # ---- actors (the people and objects the game creates when a place loads)
    N(17, "hide_actor", [], None, "needs-test", ("actor",), "In an @on_actor handler: the game does not create this actor at all (the same hook as “No exhibits”). The villager is simply not there.", "@on_actor(\"Isabelle\")\ndef not_at_work():\n    if time_between(\"22:00\", \"06:00\"):\n        hide_actor()"),
    N(18, "become", [("actor", "actor")], None, "needs-test", ("actor",), "In an @on_actor handler: create another actor in this one's place (e.g. Isabelle where Tom Nook would stand).", 'become("Isabelle")'),
    N(19, "place_player", [("tile_x", "int"), ("tile_y", "int"), ("facing", "str")], None, "needs-test", ("enter",), "In an @on_enter handler: where the player appears when coming in (tile 0-15 of the room's plan) and which way they face: north, south, east or west.", 'place_player(8, 12, "north")'),
    N(29, "place_actor", [("tile_x", "int"), ("tile_y", "int")], None, "needs-test", ("actor",), "In an @on_actor handler: put the actor on this tile (0-15 of the room's plan) once the game has created it. Together with become() this adds a character where the game creates a spare one.", "become(\"Isabelle\")\nplace_actor(8, 6)"),
    N(32, "add_actor", [("actor", "actor"), ("tile_x", "int"), ("tile_y", "int")], None, "needs-test", ("spawn",), "In an @on_spawn handler: when the game spawns the actor you named, spawn this other actor as well (the first one is not replaced), standing on this tile (0-15 of the room's plan). Needs the Builder's runtime (call_again).", 'add_actor("Isabelle", 8, 6)'),
    # ---- raw access: build new actions from scratch
    N(20, "read8", [("address", "int")], "int", "advanced", ANY, "Read a byte of the game's memory."),
    N(21, "read16", [("address", "int")], "int", "advanced", ANY, "Read 16 bits of the game's memory."),
    N(22, "read32", [("address", "int")], "int", "advanced", ANY, "Read 32 bits of the game's memory."),
    N(23, "write8", [("address", "int"), ("value", "int")], None, "advanced", ANY, "Write a byte into the game's memory."),
    N(24, "write16", [("address", "int"), ("value", "int")], None, "advanced", ANY, "Write 16 bits into the game's memory."),
    N(25, "write32", [("address", "int"), ("value", "int")], None, "advanced", ANY, "Write 32 bits into the game's memory.", "write32(0x956320, 0)"),
    N(26, "reg", [("n", "int")], "int", "advanced", ("call", "actor"), "In a hook: the value of the game's register r<n> (r0-r3 are the arguments of the function; r13 the stack pointer).", "who = reg(0)"),
    N(27, "set_reg", [("n", "int"), ("value", "int")], None, "advanced", ("call", "actor"), "In a hook: change a register (e.g. the first argument) before the game's function runs.", "set_reg(0, 5)"),
    N(28, "skip_call", [], None, "advanced", ("call", "actor"), "In a hook: do not run the game's function; it returns whatever r0 holds (set it with set_reg(0, ...)).", "set_reg(0, 0)\nskip_call()"),
]
BY_NAME = {n.name: n for n in NATIVES}
BY_ID = {n.id: n for n in NATIVES}

# triggers: decorator name -> (kind, parameter specs)
TRIGGERS = {
    "on_enter": ("enter", [("building", "building")], [("room", "room")],
                 "Runs when the player walks into the building (and again for each room they enter if you give `room`)."),
    "on_leave": ("leave", [("building", "building")], [],
                 "Runs when the player leaves the building to the town."),
    "on_room": ("room", [("building", "building"), ("room", "room")], [],
                "Runs when the player passes into this room of the building (through a door between rooms)."),
    "on_actor": ("actor", [("actor", "actor")], [("last", "actor")],
                 "Runs each time the game is about to create this actor (a villager, a shop assistant...) in a place you are loading. This is where villagers can be hidden or swapped. With last=N it covers every profile from the first number to N (e.g. all the furniture actors)."),
    "on_spawn": ("spawn", [("actor", "actor")], [],
                 "Runs when the game spawns this actor (a villager, a shop assistant...), before it does. Use add_actor() inside to spawn ANOTHER actor at the same moment: the new one is in addition to the game's, not instead of it."),
    "on_call": ("call", [("address", "addr")], [],
                "Advanced: runs every time the game calls the function at this address, before it does. Build any new action from this."),
}
KIND_CODE = {"enter": 1, "leave": 2, "actor": 3, "call": 4, "room": 5, "spawn": 6}
