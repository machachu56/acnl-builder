# Finding the game's functions (hooks)

A script can only do what the game's own code lets it. The mod's plugin can **intercept** any function of the game
(see it run, read or change its arguments, skip it, change its result) and can **read and write the game's memory**,
but it cannot *call* a game function by itself. So every new action is "find the function, then hook it".
Builder gives you three tools for the finding. None of them needs anything but your own game dump.

## 1. The map of the game's classes: `python3 -m acnlb map`

The game was built with C++ type information, so the names of its classes survive. Builder reads them and, for each
class, the address of every *virtual method* (the functions you can hook):

```sh
python3 -m acnlb map --find Weather          # classes whose name contains "Weather"
python3 -m acnlb map BsWeatherRain           # its methods: address, size, how many places call it
python3 -m acnlb map --string face_tex       # strings in the game's code and the functions that use them
python3 -m acnlb map --callers 0x22a248      # who calls this function
python3 -m acnlb map --at 0x22a300           # which function an address is in, and whose method it is
```

The map says *where* things are. It cannot say what a function *does*; the name of a class and the strings it uses are the
clues. Everything in the table below is therefore a **candidate**.

## 2. The probe: watch the game do it

```sh
python3 -m acnlb probe --actors --class BsWeatherRain --class NpcTopsChangeModel --install
# start the game from a terminal and save what it prints:   ./acnl game.3ds 2>&1 | tee game.log
# make it rain / go to the house / change a villager's shirt…
python3 -m acnlb probe-report game.log
```

The probe is a tiny mod that logs, without changing anything:

* `--actors`: every actor the game creates, with its **profile number**, **the class it is** (`AcNpcNml` = a villager,
  `AcNpcSpShop` = a shopkeeper…) and the first words of the object. This is how you learn "Isabelle is profile N":
  go where she stands, and read the report.
* `--class NAME`: every call (the first 30 of each method) of every virtual method of the class, with the arguments
  and **the address of the caller**. The method that is called exactly when the thing happens, and its caller, are what to hook.
* `--hook 0xADDR`: the same for one function.

Reading a report: *what ran when I made it rain, and what did not run when it was sunny?* The caller addresses lead to the
code that decided; `map --at` and `map --callers` follow them.

## 3. Confirm with a script

Once you think you have the function, hook it from a script with `@on_call(address)`, `log(...)` its arguments,
and only then change them. See [SCRIPTING.md](SCRIPTING.md). If the address is not the start of a function, Builder says so.

## What the plugin hooks by itself

These were found for the Builder and are used by buildings, rooms and scripts:

| | address | used for |
|---|---|---|
| scene change | `0x5b4bd0` | going between rooms, `@on_leave`, `place_player` |
| the building behind a door | `0x5c9380` | `@on_enter` |
| actor creation | `FN_ACTOR_CREATE` in the plugin source | `@on_actor`, hiding furniture, the probe |
| collision block lookup | `FN_JMP_BLOCK` in the plugin source | the rooms' collision |

The game's clock is not a hook: the 3DS keeps the date and time in a shared memory page (`0x1FF81000`, milliseconds since 1900,
local time), which the plugin reads (`hour()`, `minute()`…).

## Measured so far (probe logs of the real game)

Actors the game creates (profile number = what `@on_actor` takes; these are built into Scripts as names):

| profile | class | where seen | name in scripts |
|---|---|---|---|
| 105 (0x69) | `AcPlayer` | town | `Player` |
| 454 (0x1c6) | `AcNpcSpSecretaryIn` | scene 38 (town hall) | `Isabelle` (confirmed: she was the one in the town hall during the probe run) |
| 492 (0x1ec) | `AcNpcSpShopTanukichi` | scene 65 (Nook's Homes, so also the Baisodrome) | `Tom Nook` |
| 419 / 500 | `AcNpcSpHonma` / `AcNpcSpTakumiRealEstate` | scene 65 | `Honma` / `Takumi` |
| 425, 468 | `AcNpcSpResetsan`, `AcNpcSpPerioNormal` | scenes 99, 0 | `Resetti`, `Pelly` |
| 283-286 | `BsWeatherRain`, `Snow`, `Sakura`, `Paper` | scenes 0 and 94 (outdoors) | `Rain`, `Snow`, `Sakura`, `Paper` |
| 402 | `AcNpcOut` | scene 94 | |

* Scene numbers: 0 and 94 outdoors, 38 town hall, 65 Nook's Homes (the scene the Baisodrome's interior replaces), 99 the Resetti/title area, 165 boot.
* All four weather effects exist as actors even when the sky is clear, so they are probably *always created and then switched on by the
  weather state*: hiding the Rain actor at creation (`@on_actor("Rain")` + `hide_actor()`) should remove rain, but making it rain needs the function that
  switches it on (not found yet). Probe `BsWeatherRain` on a rainy day (`ACNL_DAYS=n` in the environment shifts the date) and compare with a clear day: methods called
  only when it rains are the candidates.
* Ordinary villagers (`AcNpcNml`) are not created through the actor-creation function the probe watches; their methods run (`AcNpcNml.9`, `.12`, `.31`) but
  how they get created is not known yet.
* **Not yet seen:** the Baisodrome itself (the mod was not installed in that run), a villager changing a shirt (the save had no way to do it), rain or snow.

## What crashed

Real runs, recorded so nobody repeats them (the builder refuses these):

* **`become("Isabelle")` outside the town hall.** `AcNpcSpSecretaryIn` was created in the Baisodrome (scene 65) and the game
  stopped with a memory fault at `0x6aa540` (a method of `NpcModel`, reading through a null model pointer). The class is built to
  run inside the town hall and needs data only that place sets up. Tom Nook, Honma and Takumi *did* work there, because that place
  is theirs. So a character can only be created where the game already prepares them; what can be swapped safely is
  the *look and lines* of the three that exist there (outfits, conversations), not the class.

## Classes worth probing for the things people ask for

Addresses are for the game version read by `python3 tools/gen_hooks_doc.py` (re-run it with your dump to refresh).
*What the name suggests* is a guess from the name only.

<!-- classes:start -->
| class | what the name suggests | vtable | slots | derived from |
|---|---|---|---|---|
| **Weather** | | | | |
| `BsWeatherRain` | rain effect | `0x8ecfa4` | 22 | `UtlBase::I4BaseE` |
| `BsWeatherSnow` | snow effect | `0x8ed004` | 22 | `UtlBase::I4BaseE` |
| `BsWeatherSakura` | cherry-blossom petals | `0x8ef648` | 22 | `UtlBase::I4BaseE` |
| `BsWeatherPaper` | paper/confetti | `0x8ee000` | 22 | `UtlBase::I4BaseE` |
| **Clothes** | | | | |
| `NpcTopsChangeModel` | a villager model whose shirt changes | `0x8f2814` | 20 | `NpcModel` |
| `AcNpcTopsChangeDemoDollSp` | the cut-scene doll of a villager changing their shirt | `0x8f5888` | 91 | `AcNpcTopsChangeDemoDollSpBas` |
| `NpcTopsBank` | the bank of shirt textures for villagers | `0x8eaa9c` | 8 | `ExchangeResBank::ILj8600E14B` |
| `ClothesList` | the player's clothes list | `0x8ea8dc` | 26 | `InstSelect::ILi8EE` |
| **Faces and emotions** | | | | |
| `HumanFaceAnimControl` | face animation of a human model | `0x8f3610` | 2 | `HumanModel::FaceCtrl` |
| `HumanResTextureAnimBank` | face texture animations | `0x8f5014` | 3 | `Bank::ILj3072ELj1ELb0E14Bank` |
| `PlayerFaceBank` | face textures of the player | `0x8ee474` | 3 | `Bank::ILj40543ELj1ELb1E14Ban` |
| `EmoticonAction` | a character playing an emoticon/emotion action | `0x8ee1b4` | 2 | - |
| `NpcHeadCtrl` | a villager's head/gaze control | `0x8eaa8c` | 2 | - |
| **Villagers and actors** | | | | |
| `AcNpc` | base of every villager/NPC actor | `0x8f661c` | 89 | `UtlBase::I9DemoActorE` |
| `AcNpcNml` | an ordinary villager | `0x8f7304` | 105 | `AcNpc` |
| `AcNpcSp` | a special character | `0x8f6ad8` | 89 | `AcNpc` |
| `AcNpcSpShop` | a shopkeeper | `0x8ea464` | 100 | `AcNpcSp` |
| `AcNpcSpResetsan` | Mr. Resetti | `0x8eecc0` | 89 | `AcNpcSp` |
| `AcNpcSpTourDesk` | the tour desk | `0x8eee2c` | 89 | `AcNpcSp` |
| `NpcModel` | a villager's 3D model | `0x8f7a9c` | 20 | `NpcModelBase` |
| `BsNpcMgr` | manager of all NPCs | `0x8f77e0` | 16 | `Base` |
| `NpcAction` | NPC actions | `0x8f851c` | 2 | - |
| `Actor` | base of all actors | `0x8f6788` | 17 | `Base` |
| `DemoActor` | actors in cut-scenes | `0x8f83b0` | 30 | `Actor` |
| **Events** | | | | |
| `BsEventMgr` | event manager | `0x8e9b3c` | 16 | `Base` |
| `EventBook` | the event calendar | `0x8f8430` | 8 | `AddressBook` |
| `EventSecretarySearchFunc` | looks for the secretary among the NPCs | `0x8f5640` | 1 | `BsNpcMgr::NpcForeachFunction` |
<!-- classes:end -->

Starting points, **all unconfirmed**:

* **Weather**: the four `BsWeather*` classes are the effects. The place that *chooses* the weather is what to find:
  probe `BsWeatherRain` and look at the callers of its first methods.
* **Changing clothes the way the game does it**: villagers have a shirt-change cut-scene
  (`AcNpcTopsChangeDemoDollSp`, `NpcTopsChangeModel`, the `NNPC_Q06_B_Cloth` flow). Probe them while a villager
  changes into a shirt you give them.
* **Faces and emotions**: `EmoticonAction`, `HumanFaceAnimControl`, `HumanResTextureAnimBank` (the string
  `Player/face_tex/%s%02d%s.bcres` is used by the function at `0x270cec`).
* **Isabelle**: `EventSecretarySearchFunc` searches the NPCs for the secretary; the `NPC_Secretary_*` flows are hers.

## Message flows: what the game already scripts

Villager and shop conversations are **message flows** (`/Script/Flow/*.msbf`): graphs of messages, branches and
*events* (a numbered call into the game's code, e.g. "give an item", "open a menu"). 426 flows, 76 distinct event numbers are
used by the game itself. Builder's *Events* tab rewrites the message nodes of a flow; the event numbers are a catalogue of what the
game's own scripts can already do, and which flows use each (a number used only in a clothes quest probably does
something with clothes). `python3 -m acnlb map` does not cover them yet.
