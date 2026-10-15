"""Remember things: greet differently the first time, and count visits.

get_var / set_var keep numbers while the game runs. Here: the first visit sets the player down at the
door facing north; later visits change nothing.
"""
from acnl import *


@on_enter("{{building}}")
def welcome():
    visits = get_var("visits")
    set_var("visits", visits + 1)
    if visits == 0:
        place_player(8, 12, "north")
        log("first visit")
    elif visits % 10 == 0:
        log("regular customer, visit", visits)
