"""Isabelle's night shift: after hours she is not at work; she is at the Baisodrome instead.

Three things happen, each is a trigger:
  * at the town hall (and anywhere else the game creates her) she is not created between 22:00 and 06:00;
  * the Baisodrome's counter, where Tom Nook usually stands, shows her instead during those hours;
  * when the shift starts again she is back at work, in her work clothes.

"Isabelle" and "Tom Nook" are actors: give each a profile number in Scripts > Actors (the probe tells you which,
see docs/HOOKS.md). "work_clothes" is an outfit you made in the Villagers tab.
"""
from acnl import *

START = "06:00"
END = "22:00"


def after_hours():
    return time_between(END, START)


@on_actor("Isabelle")
def isabelle_is_not_at_work():
    if after_hours():
        hide_actor()
    else:
        wear("{{villager}}", "{{outfit}}")


@on_actor("Tom Nook")
def isabelle_covers_the_counter():
    if in_building("{{building}}") and after_hours():
        become("Isabelle")
