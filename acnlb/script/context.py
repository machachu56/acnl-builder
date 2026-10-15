"""What a script may refer to, taken from the project (buildings, rooms, villagers, outfits, actors) and the game (code map)."""
import functools

from . import compiler

# actors the game is known to create, by the profile number its actor factory takes (for this version of the game;
# extend with `acnlb probe` and the project's own "actors" table)
KNOWN_ACTORS = {
    "Player": 0x69,
    # seen in a game log (probe, `AcPlayer` etc. by class name); the person behind each name is inferred from the class name, except Isabelle (confirmed)
    "Isabelle": 454,           # AcNpcSpSecretaryIn: Isabelle at the town hall counter (scene 38), confirmed in game
    "Tom Nook": 492,           # AcNpcSpShopTanukichi: behind the counter of Nook's Homes (scene 65, the Baisodrome's interior too)
    "Honma": 419,              # AcNpcSpHonma: also in Nook's Homes
    "Takumi": 500,             # AcNpcSpTakumiRealEstate: also in Nook's Homes
    "Resetti": 425,            # AcNpcSpResetsan
    "Pelly": 468,              # AcNpcSpPerioNormal
    "Rain": 283, "Snow": 284, "Sakura": 285, "Paper": 286,       # BsWeatherRain / Snow / Sakura / Paper: the weather effects
}


# actors that crashed the game when created in a place that is not theirs (seen in real runs): become() refuses them
UNSAFE_BECOME = {
    454: "AcNpcSpSecretaryIn (Isabelle at the town hall counter) crashes the game when it is created anywhere but the town hall "
         "(a null pointer in its model, seen when it was put in the Baisodrome)",
}


def _seen_actors():
    import json, os
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "actors.json"), encoding="utf-8") as f:
            return json.load(f)["actors"]
    except (OSError, ValueError, KeyError):
        return {}


def all_actors(proj=None):
    """every actor name a script can use: the game's class names seen in logs, the friendly names, and the project's own"""
    out = dict(_seen_actors())
    out.update(KNOWN_ACTORS)
    out.update({k: int(v) for k, v in ((proj or {}).get("actors") or {}).items()})
    return out


def resolve_method(text):
    """"BsWeatherRain.17" -> the address of that virtual method (None if unknown)"""
    try:
        from .. import gamemap
        gm = gamemap.load()
    except (SystemExit, Exception):
        return None, []
    cls, _, idx = text.rpartition(".")
    c = gm.classes.get(cls)
    if c and idx.isdigit() and int(idx) < len(c["methods"]):
        return c["methods"][int(idx)] & ~1, []
    if c:
        return None, "%s has %d methods, numbered 0 to %d" % (cls, len(c["methods"]), len(c["methods"]) - 1)
    return None, list(gm.classes)


def rooms_of(proj, bld):
    """scene ids of a building's rooms: its entrance room and everything linked from it"""
    if not bld.get("interior"):
        return []
    from ..features import interiors
    try:
        return [s["id"] for s in interiors.reachable(proj, bld["interior"])]
    except ValueError:
        return []


@functools.lru_cache(maxsize=1)
def _functions():
    """the set of function entry points of the game (None when the dump or the code map is not available)"""
    try:
        from .. import xref
        x = xref.load()
        return frozenset(x.starts) | frozenset(m & ~1 for c in x.gm.classes.values() for m in c["methods"])
    except (SystemExit, Exception):
        return None


def is_function(addr):
    f = _functions()
    return True if f is None else (addr & ~1) in f


def build_ctx(proj):
    actors = all_actors(proj)
    return compiler.Ctx(
        buildings={b["id"]: rooms_of(proj, b) for b in proj.get("buildings", [])},
        villagers={v["id"]: [o["id"] for o in v.get("outfits") or []] for v in proj.get("villagers", [])},
        actors=actors, is_function=is_function, resolve_method=resolve_method, unsafe_become=UNSAFE_BECOME,
        conversations=[e["id"] for e in proj.get("events", []) if e.get("scope") == "script"])
