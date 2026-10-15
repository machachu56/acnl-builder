"""A brand-new action built from scratch: hook any function of the game.

@on_call(address) runs your code every time the game calls the function at that address, before the game's
own code. Inside you can read the game's registers (reg), change them (set_reg), read and write memory
(read32, write32 ...) and skip the original function (skip_call). This is how new actions such as "set the weather"
are written once the right address is known: find candidates with `python3 -m acnlb map` and confirm them with
the probe (docs/HOOKS.md).

This example only watches: it logs the first argument of the game's "which interior does this building lead to"
function every time it is called. Replace the address with the one you are investigating.
"""
from acnl import *


@on_call(0x5c9380)
def watch_building_lookups():
    log("building lookup, building id", reg(0))
