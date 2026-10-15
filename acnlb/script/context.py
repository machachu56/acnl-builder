"""What a script may refer to, taken from the project (buildings, rooms, villagers, outfits, actors) and the game (code map)."""
import functools

from . import compiler

# actors the game is known to create, by the profile number its actor factory takes (extended by `acnlb probe`
# and by the project's own "actors" table: {"Isabelle": 123})
KNOWN_ACTORS = {"Player": 0x69}


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
    actors = dict(KNOWN_ACTORS)
    actors.update({k: int(v) for k, v in (proj.get("actors") or {}).items()})
    return compiler.Ctx(
        buildings={b["id"]: rooms_of(proj, b) for b in proj.get("buildings", [])},
        villagers={v["id"]: [o["id"] for o in v.get("outfits") or []] for v in proj.get("villagers", [])},
        actors=actors, is_function=is_function)
