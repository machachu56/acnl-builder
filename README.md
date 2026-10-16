# ACNL Builder

A design suite for mods of the *Animal Crossing: New Leaf* recomp. You design in the browser; **Export** builds an
`.acmod` straight from your own game dump (nothing from the game is shipped unless you edited it).

```sh
./builder serve                # (= python3 -m acnlb serve) opens http://127.0.0.1:8765/
python3 -m acnlb export baisodrome --install      # headless: projects/baisodrome -> exports/baisodrome.acmod
python3 -m acnlb doctor         # checks the ROM, the recomp checkout and the WebAssembly toolchain
python3 -m unittest discover -s tests
python3 -m acnlb map --find Weather            # explore the game's classes / methods / strings (docs/HOOKS.md)
python3 -m acnlb probe --actors --install      # a mod that logs what the game does, to find what to hook
```

Needs Python 3.10+ with Pillow (`pip install -r requirements.txt`), the recomp checkout at `../recomp` (its `tools/modkit` does the CGFX / MSBT / ETC1
work), the decrypted dump at `../acnl.3ds` (or `ACNL_ROM`), and, **only for projects with buildings or events**,
`clang` + `wasm-ld` (lld) to compile the small runtime plugin once (an Android NDK's `wasm-ld` is found automatically).
Environment: `ACNL_RECOMP`, `ACNL_ROM`, `ACNL_BIN` (the game executable for "Install and play"), `CLANG`, `WASM_LD`.

## What you can design

| tab | what | how it ends up in the game |
|---|---|---|
| **Dialogue** | any line the game has: NPC talk, names, menus, mail (5 languages, live message-window preview with the 3 × 34 limits, control-code buttons) | edited `.umsbt` files; an edit can apply only *inside one of your buildings* |
| **Villagers** | rename a villager, new catch phrase, **outfits** (paint or import a PNG; special characters too) | `STR_NNpc_name` / `STR_NNpc_habit` |
| **Textures** | pixel editor + UV layout + 3D preview for any texture of any game model: villager skins, **clothes** (tops, bottoms, hats, shoes, socks… shown on the player model), furniture, buildings | the texture is re-encoded in its own format (ETC1/ETC1A4/RGBA4/… with mip maps) |
| **Buildings** | new town buildings: parametric exterior (3 presets, roof/walls/door/windows/ornament/sign, every colour), paint-over layer, name per language, map icon, position | a real building in the town (new and existing towns), its model/textures/data under `/Strc/sobj/<name>/` |
| **Interiors** | 16 × 16 plan editor + live 3D: rooms, doorways (with signs: your own text, colours, font), a door on any edge, doors that cross into other rooms (two-way), floors/walls from presets or hand-drawn, boxes/cylinders/rugs/tubs/beds/lamps, any game furniture, **your own 3D models** (glTF/GLB, OBJ+MTL, STL, PLY from Blender), items can be raised/lowered, collision | the room model of Nook's Homes replaced only while inside your building, with its collision grid |
| **Events** | your own conversations for any character of the game: messages, **questions with 2 to 6 answers** that each lead to their own messages (or end the talk), goodbye line; or the game's own lines rewritten | the conversation's flow gets new nodes (messages and answer branches), only inside that building or while a script / a character of the Interiors tab switches it on |
| **Scripts** | Python-syntax triggers (`@on_enter`, `@on_actor`, `@on_call(address)`…): clock, remembered values, dress villagers in outfits, hide/replace actors, place the player, hook any game function. Checked and run through a pretend day in the editor, compiled to a small program the plugin interprets ([docs/SCRIPTING.md](docs/SCRIPTING.md)) | `acnlb.script` + the runtime plugin |
| **Export** | builds, warns (text too long, …), installs, starts the game | `<project>.acmod` |

Projects live in `projects/<id>/` (`project.json` + `assets/*.png`), everything autosaves, and the JSON is meant to be
readable and diff-able. `projects/baisodrome` is the original Baisodrome mod converted by `tools/import_baisodrome.py`.

## Layout

```
acnlb/                 the engine (no UI): project model, feature compilers, exporter, local server
  features/            text · textures · villagers · events · buildings · interiors → a staged file tree
  exterior.py          parametric building generator      interior.py   room scene → mesh + collision
  texfmt.py            texture formats ⇄ RGBA             paintx.py     painting helpers (Pillow lettering…)
  build.py             stage → mod.ini + acnlb.cfg + plugin → .acmod
plugin/acnlb_runtime.cpp   the one WebAssembly plugin every mod ships; reads acnlb.cfg
web/                   the editor (vanilla JS modules, WebGL viewer, pixel editor)
tests/                 unit tests (need the dump)
```

## What the game lets us do (and what it doesn't — yet)

* **Buildings** take over the slot of a public-works building the town doesn't normally have. Exteriors exist for the
  modern and the classic police station (both verified in game); each slot needs its model's materials
  mapped, so more bases = more entries in `exterior.BASES`. Interiors are the room of Nook's Homes (the only interior
  whose room model and collision index are mapped so far); a building without an interior keeps its slot's original one (the police station).
* **Added vs replaced buildings.** Every building has a base (the police stations) it copies footprint, door and behaviour from. *Replace* takes that police station's slot (own map name and icon, the station is gone); *Add* uses a spare slot (one of the 20 signboard IDs) and the runtime plugin answers the game's ~22 per-building lookups as the base would, so nothing is replaced. IDs >= 0xFC cannot be used (the game clamps them to "no building"). Added buildings get their own **map icon**: the builder enlarges the map's icon sheet to 32 cells and the plugin points the building's icon at its cell; the name on the map list stays the base's. A new building steps aside if its default spot is taken.
* **Characters**: a "new" animal is an existing villager with a new name, catch phrase and skin. Their conversation lines
  belong to their *personality* (shared), not to the individual; truly new species/IDs need game-code patches.
* **Events** are conversations bound to your buildings; triggers by date/time, items, quests would need more of the
  game's scripting (flows) mapped; the original `recomp/mods/baisodrome` plugin keeps a function-call probe (`BAISO_PROBE`) useful for that.
* Atlas budget: an interior has one 512 × 512 texture; the Interiors tab shows how much is used.
* **Custom 3D models** are kept in the project (`assets/mdl_<name>__<file>`), measured on import and baked into the room mesh like any other
  furniture: textures go into the atlas (`Texture detail` caps their size), materials without a texture use their base colour. Export glTF 2.0 (`.glb`)
  from Blender for the least fuss; OBJ needs its `.mtl` and images selected together. Keep models small (a few thousand triangles; the Interiors tab warns).
  Animations, skinning, FBX and DAE are not supported.
* **The entrance** can be on any edge (Interiors → nothing selected, or the Areas tab). Rooms with a door that is not on the south edge also write an
  `entry = x, z, yaw` line so the runtime plugin puts the player in front of that door; that part is **not yet verified in game**.

## Copyright

The repository contains no game data. Textures that come from the game (the Lovely series carpet/wallpaper/lamp used
by the Baisodrome interior) are referenced by path (`game_texture` materials) and read from *your* dump at build time;
images the texture studio makes from game textures (`projects/*/assets/tex_*.png`) and exported `.acmod` files are
git-ignored. Keep it that way when sharing a project: only commit art you drew yourself.
