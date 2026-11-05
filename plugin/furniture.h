/* Furniture outside ([furniture] section of acnlb.cfg, written by the builder's Furniture tab).

   A piece of furniture dropped on the ground in the town shows as its own 3D model on its tile, instead of the leaf the
   game draws for any dropped furniture. The model is a prop (the runtime draws it into the game's 3D scene, bent onto the
   town's rolling log, as the vehicles are); the item itself stays in the town's item grid under it, so it is saved with the
   game and picked up as usual (the game's Y, facing it; or, with pickup = hold, holding Y beside it).

   The leaf: the game makes what the ground shows (trees, flowers, items) itself, a tile at a time, from the item grid, for
   the tiles that come into view (0x599478 walks them and calls 0x59cb10 for each; a bitmap of the map's 112 x 96 tiles at
   manager + 0x35C4 says which are done). For a tile holding furniture of the mod, the hook on 0x59cb10 answers as the game
   does for an empty tile: nothing made, the tile done. No leaf is made for it however often the area loads, and the item
   never leaves the grid.

   Dropped or picked up, a piece appears or goes in the game's own smoke puff and sound, as furniture placed indoors does
   (effect 0xD4, seen spawned by the game's furniture placing; SE_OBJ_FUR_CMN_APPEAR / _DISAPPEAR, named in
   /Sound/GardenSound.bcsar). A hook on the game's tile item setter (0x168890: drops and pick-ups go through it) has the grid
   looked at again the next frame.

   ftr/items.bin (from the builder): "FTR1", u16 first item, u16 count, then per item {u8 flags (1: it has a model,
   ftr/<item, 4 hex digits>.apm), u8 half width (x), u8 half depth (z), u8 height} in model units (32 a tile). Models face
   +z (south, the camera) unturned. Each object's quarter turn is kept in the mod's storage (ftr_rot.bin). */
#pragma once
#include "field.h"
#include "pmath.h"

namespace ftr {

using namespace pm;

const uint32_t SAVE_PTR = 0x95af74, TOWN_ITEMS = 0x534D8;
const uint32_t SCENE_STATE = 0x956320;         /* +2: current scene (0: the town) */
const uint32_t FN_MAKE_TILE = 0x59cb10;        /* bool make(manager, tile x, tile z, first try): what a tile's ground shows */
const uint32_t TILE_DONE = 0x35C4;             /* manager + : u32, then a bit per tile of the 112 x 96 map (set: done) */
const uint32_t CUR_PLAYER = 0xaae14c, POCKETS = 0x6BD0;
const uint32_t FN_TRAMPLE_SET = 0x168890, FN_TRAMPLE_SHOW = 0x59D6B4, ROOM_OUTDOORS = 0xA5;   /* see vehicles.h */
/* effect(id, float pos[3], u16 turn[3], float scale[3], 1, 0): the game's particle effects. Vapecord's USA WA 0x2075D4 (+0x28
   in this build, as its TRAMPLE1 there); the game passes the no-turn and scale-1 constants below */
const uint32_t FN_EFFECT = 0x2075FC, EFFECT_NO_TURN = 0x974BEE, EFFECT_SCALE_1 = 0xAE4664, EFFECT_PUFF = 0xD4;
/* play(sound id): Vapecord's PlaySound (its EUR WA 0x58CEE4, 0xAD8 lower here as its trample functions around there) */
const uint32_t FN_SOUND = 0x58C40C, SE_FUR_APPEAR = 0x1000950, SE_FUR_DISAPPEAR = 0x1000951;
const uint32_t EMPTY = 0x7FFE;
const float ROLL_RADIUS = 488.89f, TILE = 32.0f;
const int TOWN_SLOTS = 20 * 256, MAX_ITEMS = 1920, MAX_OBJS = 400, MAX_INST = 320;     /* (1,904 furniture items: 0x295C..0x30CB) */
const float VIEW_X = 14 * TILE, VIEW_Z = 10 * TILE;      /* drawn this far from the player */

struct Config { bool on, solid, face_player, hold_pickup, debug; char dir[40]; };
Config g_c = {false, true, true, false, false, "ftr/"};

struct Rec { uint8_t flags, hx, hz, h; };
struct Items { char magic[4]; uint16_t first, count; Rec rec[MAX_ITEMS]; };     /* items.bin as it is */
Items g_items;
uint16_t &g_first = g_items.first, &g_count = g_items.count;
Rec *const g_rec = g_items.rec;
int16_t g_mesh[MAX_ITEMS];                     /* the item's prop mesh: -2 not loaded yet, -1 none */

struct Obj {
    int16_t slot;                              /* town item slot (20 acres x 256 tiles) */
    uint16_t item;
    int16_t inst;                              /* its prop instance while in view, -1 */
    uint8_t rot;                               /* quarter turns about y: 0 faces south (+z), 1 east, 2 north, 3 west */
    bool seen;
    float y;                                   /* ground height */
};
Obj g_obj[MAX_OBJS];
int g_nobj = 0;
int16_t g_at[TOWN_SLOTS];                      /* object index on each slot, -1 */

struct Inst { int id; int16_t mesh; bool used; };
Inst g_inst[MAX_INST];
int g_ninst = 0;

struct Turn { uint16_t slot, item; uint8_t rot, pad[3]; };    /* a remembered quarter turn (kept when the item goes: the game
                                                                 may not be saved, and it comes back) */
const uint32_t TURN_MAGIC = 0x46545231u;
struct Turns { uint32_t magic, count; Turn t[MAX_OBJS]; };    /* ftr_rot.bin as it is */
Turns g_turns;
Turn *const g_turn = g_turns.t;
int g_nturn = 0;
bool g_turns_loaded = false;

uint32_t g_row[256];
bool g_in_town = false;
int g_scan_wait = 0, g_skips = 0, g_loads = 0;
uint32_t g_last_us = 0;
float g_hold = 0;
uint32_t g_item_buf = 0, g_fx_bufs = 0;
int g_fx_next = 0;

/* ------------------------------------------------------------------ config, items.bin */

void set_key(const char *key, const char *val) {
    long v = acnl_strtol(val, nullptr, 0);
    if (!strcmp(key, "enabled")) g_c.on = v != 0;
    else if (!strcmp(key, "dir")) copy_str(g_c.dir, sizeof g_c.dir, val);
    else if (!strcmp(key, "solid")) g_c.solid = v != 0;
    else if (!strcmp(key, "face")) g_c.face_player = strcmp(val, "south") != 0;
    else if (!strcmp(key, "pickup")) g_c.hold_pickup = !strcmp(val, "hold");
    else if (!strcmp(key, "debug")) g_c.debug = v != 0;
}

void file_path(const char *name, char *out, int cap) {
    int n = 0;
    for (const char *s = g_c.dir; *s && n < cap - 1; s++) out[n++] = *s;
    for (const char *s = name; *s && n < cap - 1; s++) out[n++] = *s;
    out[n] = 0;
}

const Rec *rec(uint32_t item) {
    uint32_t id = item & 0xFFFF;
    if (id < g_first || id >= (uint32_t)g_first + g_count) return nullptr;
    const Rec *r = &g_rec[id - g_first];
    return (r->flags & 1) ? r : nullptr;
}

/* furniture this mod draws: an item with a model, lying normally (not buried: flags of 0x8000 and up) */
bool ours(uint32_t item) { return (item >> 16) < 0x8000 && rec(item) != nullptr; }

bool car_blocked(const veh::Box &to, const veh::Box *from);

bool init() {
    char path[64];
    file_path("items.bin", path, sizeof path);
    int n = acnl_read_file(path, &g_items, sizeof g_items);
    if (n < 8 || memcmp(g_items.magic, "FTR1", 4)) { acnl_log("furniture: %s missing: off", path); g_c.on = false; return false; }
    if (n > (int)sizeof g_items) n = sizeof g_items;
    if (g_count > MAX_ITEMS) g_count = MAX_ITEMS;
    if (8 + g_count * 4 > n) g_count = (uint16_t)((n - 8) / 4);
    int models = 0;
    for (int i = 0; i < g_count; i++) {
        g_mesh[i] = -2;
        for (int k = 0; k < veh::g_nv; k++)             /* a car's item stays the car's (vehicles.h) */
            if (veh::g_v[k].c.item == (uint32_t)(g_first + i)) g_rec[i].flags = 0;
        models += g_rec[i].flags & 1;
    }
    for (int i = 0; i < TOWN_SLOTS; i++) g_at[i] = -1;
    veh::g_solid = car_blocked;                         /* the cars bump into it */
    acnl_log("furniture: %d item(s) with a model (%#x..%#x)%s%s%s", models, (unsigned)g_first, (unsigned)(g_first + g_count - 1),
             g_c.solid ? ", solid" : "", g_c.face_player ? ", facing the player" : ", facing south", g_c.hold_pickup ? ", hold Y to pick up" : "");
    return true;
}

/* ------------------------------------------------------------------ the town */

bool in_town() { return acnl_rd8(SCENE_STATE + 2) == 0; }

int tile_slot(int tx, int tz) {
    int ax = tx / 16 - 1, az = tz / 16 - 1;
    if (tx < 0 || tz < 0 || ax < 0 || az < 0 || ax > 4 || az > 3) return -1;
    return (az * 5 + ax) * 256 + (tz % 16) * 16 + tx % 16;
}
void slot_tile(int slot, int *tx, int *tz) { int acre = slot / 256, t = slot % 256; *tx = (acre % 5 + 1) * 16 + t % 16; *tz = (acre / 5 + 1) * 16 + t / 16; }

uint32_t player_render_matrix(uint32_t player) {
    if (player < 0x100000) return 0;
    uint32_t m = acnl_rd32(player + 0x230);
    if (m >= 0x100000) m = acnl_rd32(m + 0x220);
    if (m >= 0x100000) m = acnl_rd32(m + 0x30);
    return m >= 0x100000 ? m : 0;
}

/* the game makes a tile's ground: for our furniture, as for an empty tile (nothing; the tile is done, on the last try) */
int hook_make_tile_pre(void *) {
    uint32_t mgr = acnl_reg(0), tx = acnl_reg(1), tz = acnl_reg(2), first_try = acnl_reg(3);
    if (!g_c.on || tx >= 112 || tz >= 96 || !in_town()) return ACNL_CONTINUE;
    int slot = tile_slot((int)tx, (int)tz);
    uint32_t save = acnl_rd32(SAVE_PTR);
    if (slot < 0 || save < 0x100000) return ACNL_CONTINUE;
    uint32_t item = acnl_rd32(save + TOWN_ITEMS + (uint32_t)slot * 4);
    if (!ours(item)) return ACNL_CONTINUE;
    if (!first_try) {
        uint32_t bit = tx + tz * 112, w = mgr + TILE_DONE + 4 + (bit >> 5) * 4;
        acnl_wr32(w, acnl_rd32(w) | (1u << (bit & 31)));
    }
    if (g_c.debug && g_skips++ < 60) acnl_log("furniture: no leaf for %08x on tile %u, %u (try %u)", (unsigned)item, (unsigned)tx, (unsigned)tz, (unsigned)first_try);
    acnl_set_reg(0, 0);
    return ACNL_SKIP;
}

/* an item was just set on a tile (dropped, picked up...): the grid is looked at again next frame */
int hook_tile_set_pre(void *) {
    if (acnl_reg(3) == ROOM_OUTDOORS) g_scan_wait = 1;
    return ACNL_CONTINUE;
}

/* the game's smoke puff and sound of furniture placed (appear) or picked up, on a tile (they run right after the hook) */
void puff(int slot, float y, bool appear) {
    uint32_t sound = appear ? SE_FUR_APPEAR : SE_FUR_DISAPPEAR;
    acnl_call(0, FN_SOUND, &sound, 1);
    if (!g_fx_bufs) g_fx_bufs = acnl_alloc(8 * 12, 4);       /* (each queued call needs its own position until it runs) */
    if (!g_fx_bufs) return;
    int tx, tz;
    slot_tile(slot, &tx, &tz);
    uint32_t b = g_fx_bufs + (uint32_t)(g_fx_next++ & 7) * 12;
    float pos[3] = {tx * TILE + TILE / 2, y, tz * TILE + TILE / 2};
    acnl_write(b, pos, 12);
    uint32_t args[6] = {EFFECT_PUFF, b, EFFECT_NO_TURN, EFFECT_SCALE_1, 1, 0};
    acnl_call(0, FN_EFFECT, args, 6);
}

/* ------------------------------------------------------------------ remembered turns */

void load_turns() {
    g_turns_loaded = true;
    int n = acnl_storage_read("ftr_rot.bin", &g_turns, sizeof g_turns);
    if (n > (int)sizeof g_turns) n = sizeof g_turns;
    if (n < 8 || g_turns.magic != TURN_MAGIC) return;
    uint32_t count = g_turns.count;
    if (count > (uint32_t)MAX_OBJS) count = MAX_OBJS;
    if (8 + count * sizeof(Turn) > (uint32_t)n) count = (uint32_t)(n - 8) / sizeof(Turn);
    g_nturn = (int)count;
}

void save_turns() {
    g_turns.magic = TURN_MAGIC;
    g_turns.count = (uint32_t)g_nturn;
    acnl_storage_write("ftr_rot.bin", &g_turns, 8 + (uint32_t)g_nturn * sizeof(Turn));
}

int turn_of(int slot, uint16_t item) {
    for (int i = 0; i < g_nturn; i++) if (g_turn[i].slot == slot && g_turn[i].item == item) return g_turn[i].rot;
    return 0;
}

void remember_turn(int slot, uint16_t item, uint8_t rot) {
    int at = -1;
    for (int i = 0; i < g_nturn && at < 0; i++) if (g_turn[i].slot == slot) at = i;
    if (at < 0 && g_nturn < MAX_OBJS) at = g_nturn++;
    if (at < 0) {                                       /* full: forget one whose item is no longer there */
        for (int i = 0; i < g_nturn && at < 0; i++) {
            int o = g_at[g_turn[i].slot];
            if (o < 0 || g_obj[o].item != g_turn[i].item) at = i;
        }
        if (at < 0) return;
    }
    g_turn[at].slot = (uint16_t)slot;
    g_turn[at].item = item;
    g_turn[at].rot = rot;
    save_turns();
}

/* ------------------------------------------------------------------ models */

int mesh_of(uint16_t item) {
    int k = item - g_first;
    if (g_mesh[k] != -2) return g_mesh[k];
    if (g_loads <= 0) return -2;                        /* (a few a frame: the next frames load the rest) */
    g_loads--;
    char name[12], path[64];
    static const char hex[] = "0123456789abcdef";
    for (int i = 0; i < 4; i++) name[i] = hex[(item >> (12 - 4 * i)) & 15];
    memcpy(name + 4, ".apm", 5);
    file_path(name, path, sizeof path);
    g_mesh[k] = (int16_t)acnl_prop_mesh(path);
    if (g_mesh[k] < 0) { g_mesh[k] = -1; acnl_log("furniture: no model %s for item %#x", path, (unsigned)item); }
    return g_mesh[k];
}

int take_inst(int mesh) {
    for (int i = 0; i < g_ninst; i++)
        if (!g_inst[i].used && g_inst[i].mesh == mesh) { g_inst[i].used = true; return i; }
    if (g_ninst >= MAX_INST) return -1;
    int id = acnl_prop_new(mesh);
    if (id < 0) return -1;
    g_inst[g_ninst] = {id, (int16_t)mesh, true};
    return g_ninst++;
}

void give_inst(Obj &o) {
    static const float zero[12] = {0};
    if (o.inst < 0) return;
    g_inst[o.inst].used = false;
    acnl_prop_place(g_inst[o.inst].id, zero, 0);
    o.inst = -1;
}

void place(Obj &o) {
    int tx, tz;
    slot_tile(o.slot, &tx, &tz);
    float r[12], t[12], m[12];
    m_rot_y((float)o.rot * PI / 2, r);
    m_translate(tx * TILE + TILE / 2, o.y, tz * TILE + TILE / 2, t);
    m_mul(t, r, m);
    acnl_prop_place(g_inst[o.inst].id, m, 1);
}

/* the ground height under an object (kept: the ground stays), `fallback` while it cannot be known */
float ground_y(Obj &o, float fallback) {
    if (o.y > -1e8f) return o.y;
    int tx, tz;
    slot_tile(o.slot, &tx, &tz);
    uint8_t kind;
    float h;
    if (!field::ground(tx * TILE + TILE / 2, tz * TILE + TILE / 2, &h, &kind)) return fallback;
    return o.y = h;
}

/* ------------------------------------------------------------------ objects: what lies in the grid */

void remove_obj(int i) {
    give_inst(g_obj[i]);
    g_at[g_obj[i].slot] = -1;
    g_obj[i] = g_obj[--g_nobj];
    if (i < g_nobj) g_at[g_obj[i].slot] = (int16_t)i;
}

/* every furniture item in the town's grid has an object; `arrived`: the town was just entered (nothing was dropped, nothing
   picked up: no puff) */
void scan(uint32_t player, bool arrived) {
    uint32_t save = acnl_rd32(SAVE_PTR);
    if (save < 0x100000) return;
    if (!g_turns_loaded) load_turns();
    for (int i = 0; i < g_nobj; i++) g_obj[i].seen = false;
    for (int acre = 0; acre < 20; acre++) {
        if (acnl_read(save + TOWN_ITEMS + (uint32_t)acre * 1024, g_row, sizeof g_row) != 0) return;
        for (int t = 0; t < 256; t++) {
            uint32_t item = g_row[t];
            if (!ours(item)) continue;
            int slot = acre * 256 + t, i = g_at[slot];
            if (i >= 0 && g_obj[i].item == (item & 0xFFFF)) { g_obj[i].seen = true; continue; }
            if (i >= 0) remove_obj(i);                  /* another item on that tile now */
            if (g_nobj >= MAX_OBJS) continue;
            Obj &o = g_obj[g_nobj];
            memset(&o, 0, sizeof o);
            o.slot = (int16_t)slot;
            o.item = (uint16_t)(item & 0xFFFF);
            o.inst = -1;
            o.seen = true;
            o.y = -1e9f;
            if (arrived || !g_c.face_player || player < 0x100000) o.rot = g_c.face_player ? (uint8_t)turn_of(slot, o.item) : 0;
            else {                                      /* just dropped: turned to face the player */
                uint16_t yaw = acnl_rd16(player + 0x34);   /* 0 south, 0x4000 east */
                o.rot = (uint8_t)((((yaw + 0x2000) >> 14) + 2) & 3);
                remember_turn(slot, o.item, o.rot);
            }
            if (!arrived) puff(slot, ground_y(o, 0), true);
            g_at[slot] = (int16_t)g_nobj++;
            if (g_c.debug) {
                int tx, tz;
                slot_tile(slot, &tx, &tz);
                acnl_log("furniture: %08x on tile %d, %d (turn %d)%s", (unsigned)item, tx, tz, o.rot, arrived ? "" : ": just dropped");
            }
        }
    }
    for (int i = g_nobj - 1; i >= 0; i--) {
        Obj &o = g_obj[i];
        if (o.seen) continue;
        if (!arrived && o.inst >= 0) puff(o.slot, ground_y(o, 0), false);       /* picked up (in view) */
        remove_obj(i);
    }
}

/* ------------------------------------------------------------------ the player */

/* a piece of furniture is solid: the player is pushed out of its footprint (the item's size, turned with it) */
void push_out(const Obj &o, uint32_t player, float pp[3]) {
    const Rec *r = rec(o.item);
    if (!r) return;
    int tx, tz;
    slot_tile(o.slot, &tx, &tz);
    float cx = tx * TILE + TILE / 2, cz = tz * TILE + TILE / 2;
    float hx = (float)((o.rot & 1) ? r->hz : r->hx), hz = (float)((o.rot & 1) ? r->hx : r->hz);
    hx = clampf(hx, 6, 64) + 6;
    hz = clampf(hz, 6, 64) + 6;
    float lx = pp[0] - cx, lz = pp[2] - cz;
    if (absf(lx) >= hx || absf(lz) >= hz) return;
    if (hx - absf(lx) < hz - absf(lz)) pp[0] = cx + (lx < 0 ? -hx : hx);
    else pp[2] = cz + (lz < 0 ? -hz : hz);
    acnl_write(player + 0x14, pp, 12);
}

/* the current player's data (what 0x2fb894 returns), 0 when there is none */
uint32_t cur_player() {
    uint32_t save = acnl_rd32(SAVE_PTR), p = acnl_rd32(CUR_PLAYER);
    if (save < 0x100000 || p < save + 0xA0 || p >= save + 0xA0 + 4 * 0x9F10 || (p - save - 0xA0) % 0x9F10) return 0;
    return p;
}

/* pickup = hold: the item into the first free pocket, off the ground the game's way (the trample pair, as vehicles.h) */
bool pick_up(Obj &o) {
    uint32_t p = cur_player(), save = acnl_rd32(SAVE_PTR);
    if (!p || save < 0x100000) return false;
    uint32_t a = save + TOWN_ITEMS + (uint32_t)o.slot * 4, item = acnl_rd32(a);
    if ((item & 0xFFFF) != o.item) return false;
    int free_pocket = -1;
    for (int i = 0; i < 16 && free_pocket < 0; i++) if ((acnl_rd32(p + POCKETS + i * 4) & 0xFFFF) == EMPTY) free_pocket = i;
    if (free_pocket < 0) return false;
    acnl_wr32(p + POCKETS + (uint32_t)free_pocket * 4, item);
    int tx, tz;
    slot_tile(o.slot, &tx, &tz);
    if (!g_item_buf) g_item_buf = acnl_alloc(8, 4);
    if (g_item_buf) acnl_wr32(g_item_buf, EMPTY);
    uint32_t set[5] = {(uint32_t)tx, (uint32_t)tz, 0, ROOM_OUTDOORS, g_item_buf}, show[3] = {(uint32_t)tx, (uint32_t)tz, 1};
    if (!g_item_buf || acnl_call(0, FN_TRAMPLE_SET, set, 5) != 0) acnl_wr32(a, EMPTY);
    else acnl_call(0, FN_TRAMPLE_SHOW, show, 3);
    g_scan_wait = 1;                                    /* (it goes in a puff, as when the game picks it up) */
    acnl_log("furniture: %#x picked up from tile %d, %d", (unsigned)o.item, tx, tz);
    return true;
}

/* the buttons vehicles.h keeps from the game this frame (A and Y next to a parked car), so ours add to them */
uint32_t car_buttons(const float pp[3]) {
    if (veh::g_driver >= 0) return 0xFFFFFFFFu;
    for (int i = 0; i < veh::g_nv; i++) {
        const veh::Vehicle &v = veh::g_v[i];
        float dx = pp[0] - v.x, dz = pp[2] - v.z, reach = maxf(v.c.length, v.c.width) * 0.5f + 26;
        if (v.placed && dx * dx + dz * dz < reach * reach) return ACNL_BTN_A | ACNL_BTN_Y;
    }
    return 0;
}

/* ------------------------------------------------------------------ the cars (vehicles.h) */

/* is a car's footprint on a piece of furniture (its item's size, turned with it, and a margin)? The two rectangles are
   apart when they are apart along one of their sides: the world's x and z (the furniture's), then the footprint's own two
   (projections there scaled by the side's length, so no square root) */
bool box_on(const veh::Box &b, const Obj &o) {
    const Rec *r = rec(o.item);
    if (!r) return false;
    int tx, tz;
    slot_tile(o.slot, &tx, &tz);
    float hx = (float)((o.rot & 1) ? r->hz : r->hx), hz = (float)((o.rot & 1) ? r->hx : r->hz);
    hx = clampf(hx, 6, 64) + 3;
    hz = clampf(hz, 6, 64) + 3;
    float dx = tx * TILE + TILE / 2 - b.x, dz = tz * TILE + TILE / 2 - b.z;
    if (absf(dx) > absf(b.ax) + absf(b.bx) + hx || absf(dz) > absf(b.az) + absf(b.bz) + hz) return false;
    if (absf(dx * b.ax + dz * b.az) > b.ax * b.ax + b.az * b.az + hx * absf(b.ax) + hz * absf(b.az)) return false;
    if (absf(dx * b.bx + dz * b.bz) > b.bx * b.bx + b.bz * b.bz + hx * absf(b.bx) + hz * absf(b.bz)) return false;
    return true;
}

/* veh::g_solid: furniture is solid for a car as for the player; what the car already stands on (dropped beside it) is not,
   so it can drive off */
bool car_blocked(const veh::Box &to, const veh::Box *from) {
    if (!g_c.on || !g_c.solid) return false;
    for (int i = 0; i < g_nobj; i++)
        if (box_on(to, g_obj[i]) && !(from && box_on(*from, g_obj[i]))) return true;
    return false;
}

/* ------------------------------------------------------------------ every frame */

void hide_all() { for (int i = 0; i < g_nobj; i++) give_inst(g_obj[i]); }

void tick(uint32_t player) {
    if (!g_c.on) return;
    uint32_t now = acnl_time_us();
    float dt = clampf(g_last_us ? (float)(now - g_last_us) / 1e6f : 1.0f / 30, 0.001f, 0.1f);
    g_last_us = now;
    bool town = in_town() && player >= 0x100000 && field::refresh();
    uint32_t mtx = town ? player_render_matrix(player) : 0;
    if (!mtx) {
        if (g_in_town) hide_all();
        g_in_town = false;
        return;
    }
    acnl_world_roll(mtx, player + 0x14, ROLL_RADIUS);
    bool arrived = !g_in_town;
    g_in_town = true;
    if (arrived || --g_scan_wait <= 0) { scan(player, arrived); g_scan_wait = 10; }
    float pp[3] = {0, 0, 0};
    acnl_read(player + 0x14, pp, 12);
    acnl_pad pad;
    acnl_pad_read(&pad);
    g_loads = 4;
    bool driving = veh::g_driver >= 0;
    int nearest = -1;
    float nearest_d = 1e9f;
    for (int i = g_nobj - 1; i >= 0; i--) {
        Obj &o = g_obj[i];
        int tx, tz;
        slot_tile(o.slot, &tx, &tz);
        float dx = tx * TILE + TILE / 2 - pp[0], dz = tz * TILE + TILE / 2 - pp[2];
        if (absf(dx) > VIEW_X || absf(dz) > VIEW_Z) { give_inst(o); continue; }
        if (o.inst < 0) {
            int mesh = mesh_of(o.item);
            if (mesh < 0) continue;
            o.inst = (int16_t)take_inst(mesh);
            if (o.inst < 0) continue;
        }
        if (o.y < -1e8f) o.y = ground_y(o, pp[1]);
        place(o);
        if (!driving) {
            if (g_c.solid) push_out(o, player, pp);
            float d = dx * dx + dz * dz;
            if (d < nearest_d) { nearest_d = d; nearest = i; }
        }
    }
    if (!g_c.hold_pickup || driving) return;
    /* pickup = hold: hold Y next to it */
    const Rec *r = nearest >= 0 ? rec(g_obj[nearest].item) : nullptr;
    float reach = r ? maxf((float)r->hx, (float)r->hz) + 28 : 0;
    bool near = r && nearest_d < reach * reach;
    if (near && (pad.buttons & ACNL_BTN_Y)) {
        if (g_hold >= 0) g_hold += dt;
        if (g_hold >= 0.5f) g_hold = pick_up(g_obj[nearest]) ? 0 : -1;    /* -1: the pockets are full (until Y is let go) */
    } else g_hold = 0;
    if (near) acnl_pad_override(car_buttons(pp) | ACNL_BTN_Y, 0, 0);
}

}  // namespace ftr
