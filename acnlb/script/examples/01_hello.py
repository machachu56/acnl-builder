"""Hello: the smallest script. Writes a line in the game's log every time someone walks in.

Look for "script: someone came in" in the game's log (run the game from a terminal) to see it work.
"""
from acnl import *


@on_enter("{{building}}")
def someone_came_in():
    log("someone came in at hour", hour())
