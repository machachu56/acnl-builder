# Scripting guide

Scripts make the mod *react*: dress a villager differently at night, hide Isabelle after hours, send the player
to a certain spot when they walk in, or hook any function of the game to build a new action from scratch.

You write them in **Python syntax** in the **Scripts** tab. Python itself never runs them: Builder reads them,
**checks** them, runs them through a pretend day, and compiles them into a small program that the mod's plugin runs inside
the game. So a mistake is reported *in the editor, with its line*, not as a crash in the game.

```python
from acnl import *

@on_enter("baisodrome")                      # a trigger: when the player walks into the Baisodrome
def welcome():
    if time_between("22:00", "06:00"):       # it is night
        log("night visit")
```

## The shape of a script

* `from acnl import *` at the top (optional; it lets editors complete names. **Scripts > Reference > Download acnl.py**).
* Top-level constants: `START = "06:00"`, `LIMIT = 5`.
* **Trigger functions**: a function with one `@on_...` line above it and no parameters.
* **Helper functions**: a function *without* a decorator. Call it from a trigger. It can take values, and end with
  `return value`; Builder pastes it in where it is called (so a helper cannot call itself).
* Inside: `if / elif / else`, `for i in range(n)` (n a fixed number, at most 64), `x = ...`, `x += 1`,
  calls, numbers, `and / or / not`, `+ - * // %`, comparisons, `a if c else b`.
* Not available, on purpose: `while`, `try`, classes, `lambda`, imports, text values you can compute (a script must always
  finish and cannot surprise the game). The editor explains each one when you try it.

Text (`"like this"`) can only be given to a function that expects text. Everything else is whole numbers.

## Triggers: *when* a function runs

| trigger | runs when |
|---|---|
| `@on_enter("building")` | the player walks into the building. `@on_enter("building", room="spa")` also for each time they enter that room |
| `@on_leave("building")` | the player leaves it for the town |
| `@on_room("building", "room")` | the player passes into that room through a door between rooms |
| `@on_actor("Isabelle")` | the game is about to create that actor (villager, shopkeeper…) in a place that is loading |
| `@on_call(0x5c9380)` | the game calls the function at that address (advanced: build anything from this) |

Names are checked: a building, room, villager or outfit that does not exist is an error with a "did you mean…?".
Rooms are the rooms (interiors) linked from the building's entrance room, by their id.

**Actors** are the people and objects the game creates. You never type their numbers: write the name
(`@on_actor("Isabelle")`, or the game's own class name like `"AcNpcSpSecretaryIn"`). The **Names to use** card in the Scripts tab
lists them and writes the one you click. New names come from probe logs (`python3 -m acnlb probe-report LOG --save`).
Functions of the game are named too: `@on_call("BsWeatherRain.17")` is method 17 of the class `BsWeatherRain`
(`python3 -m acnlb map BsWeatherRain` lists the methods); a raw address still works.

## Functions: *what* a script can ask and do

The complete, always-current list (with what each one is for and its status) is **Scripts > Reference**. In short:

**Ask**: `hour()`, `minute()`, `weekday()` (0 = Monday), `day()`, `month()`, `year()` · `time_between("22:00", "06:00")` (may cross
midnight) · `in_building("id")`, `in_room("building", "room")` · `chance(25)` (true 25 % of the time), `random(n)` ·
`get_var("name")` / `set_var("name", n)` remember numbers while the game runs.

**Do**:

| function | does | status |
|---|---|---|
| `log("text", number)` | writes a line in the game's log | ready |
| `wear("villager", "outfit")`, `wear_default("villager")` | dress a villager in an outfit you made (Villagers tab) | needs test |
| `hide_actor()` | (in `@on_actor`) the game does not create that actor | needs test |
| `become("Actor")` | (in `@on_actor`) create another actor in its place | needs test |
| `place_actor(tile_x, tile_y)` | (in `@on_actor`) move the new actor to a tile once the game created it; with `become()` this *adds* a character in a spare slot | needs test |
| `place_player(tile_x, tile_y, "north")` | (in `@on_enter`) where the player appears coming in | needs test |
| `variant_on("name")`, `variant_off("name")` | switch a RomFS variant of the mod | needs test |
| `read8/16/32(addr)`, `write8/16/32(addr, v)` | the game's memory | advanced |
| `reg(n)`, `set_reg(n, v)`, `skip_call()` | (in `@on_call`/`@on_actor`) the hooked function's arguments; skip it | advanced |

**Status** tells the truth about each one:
* *ready*: uses things known to work (the game's clock, the mod's own state, memory access).
* *needs test*: implemented and checked as far as it can be without the game (the compiler, the interpreter, the way it is
  wired to the game's hooks), but **nobody has yet watched the game do it**. Use the log, and tell what happens.
* *advanced*: you are working on the game's memory directly. It can crash the game; it is how new things are built.

## Make something new from scratch

`@on_call(address)` runs your code every time the game calls the function at `address`, *before* the game's own
code. Inside it you can read the arguments (`reg(0)`…`reg(3)`), change them (`set_reg`), read and write memory, and
skip the original (`skip_call()` after `set_reg(0, result)`).

```python
@on_call(0x5c9380)                 # "which interior does this building lead to?"
def log_door_lookups():
    log("building id", reg(0))     # watch first…
    # set_reg(0, 65)               # …then change the answer
```

An address must be the start of a function; Builder checks it against the game's code and refuses others.
[HOOKS.md](HOOKS.md) explains how to find the address of the thing you want (the weather, a face, a shirt).

## Events and scripts together

* **Events tab = what is said.** Pick any conversation of the game (the secretary's counter talk, Tom Nook's welcome, a birthday…) and
  either *say your own messages* or *rewrite the game's own lines* (its Yes/No questions and branches stay). Choose where it applies:
  **inside a building**, **everywhere**, or **only when a script switches it on**.
* **Scripts = when, and what else changes.** For a conversation whose scope is "only when a script switches it on", a script decides when:

```python
@on_enter("baisodrome")
def morning_or_night():
    if time_between("22:00", "06:00"):
        conversation_on("isabelle_night")     # her lines from the Events tab
    else:
        conversation_off("isabelle_night")    # back to the game's own lines
```
* The game decides *which* conversation starts and when (talking to someone, a visit…); events change what it says, scripts change
  which version is active. A conversation switches on the next time it starts.
* **Not possible yet:** brand-new questions with your own Yes/No branches (a conversation whose structure you design), a script
  trigger for "the player talked to X", showing text from a script. Rewriting an existing conversation keeps the game's questions.

## Example: Isabelle's night shift (for the Baisodrome)

The **Isabelle's night shift** example does this: after 22:00 Isabelle is not created at the town hall (she "left");
the Baisodrome's counter shows her instead of Tom Nook; at 06:00 she is back at work. It needs, once:
the profile numbers of Isabelle and Tom Nook (Scripts > Actors: use the probe) and an outfit for her
(Villagers > Special characters). It is in the Baisodrome project, switched off until those are filled in.

What this can and cannot do: the game creates its people when a place *loads*, so a script decides **who is there when
you arrive** and what they wear then. Nobody can be seen walking from the town hall to the Baisodrome, and nothing changes
while you stand in the same place. (A change *while you watch* needs a hook found for that particular thing.)

## How it is checked

When you type, Builder (1) reads the script as Python, (2) checks every name, argument, place and address,
(3) compiles it, and (4) **runs each trigger through a whole day** on a pretend game (every 30 minutes), which is the
"What it does" table: it shows what the function does at each time, and reports a runtime error (a division by zero,
a loop that would not end, reading memory that is not the game's) *before* you export. Export refuses to build if a script
has an error. The pretend game and the plugin's interpreter are two implementations of the same thing, and
`tests/test_script.py` checks that they do exactly the same for the same program.

## Limits

24 000 bytes of compiled scripts in total, 64 triggers, 32 local values per function, 20 000 steps per run, 64 remembered values,
256 distinct texts. They are checked while you type.
