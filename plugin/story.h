/* Story: a game of your own on top of the town ([story], [prop], [quest], [talk] and [vars] sections of acnlb.cfg, written by the
   builder's story feature).

   Props: objects drawn in the town (a barrier in front of the station, cages, a bench...), placed next to one of the town's buildings
   (its tile in the save's building list) so they find their place in any town. Each is solid (the player is pushed out of its box) and
   can be shown only while a script value is set ("show = freed_0", "show = !freed_0").

   Remembered values: the scripts' get_var / set_var values are kept per town in the mod's storage (story_<town id>.bin, by name),
   so a story survives quitting the game. [vars] maps each name to the script's index.

   Conversations: a flow node of the mod's own (written by the events feature) runs a script: an event node with event STORY_EVENT,
   or a branch node with query STORY_BRANCH whose case is what the script answers (answer(n)). Their parameter is the talk point
   (the index of a [talk] name; the scripts' @on_talk("name") handlers run). The game's flow engine asks its receptor for both
   (script::IFlowRecept methods 4 and 3: 0x5d80e4 event(recept, ?, node), 0x5d8800 branch(recept, int *case, node); node + 4 -> the
   16-byte node: u32 parameter at +4, the event / query number at +0xA). The game's own numbers are below 0x100.

   HUD: once the value "quest_on" is set, the current quest (the value "quest" indexes the [quest] list; "quest_ready" set: done, go
   back to the quest giver) in a
   panel on the top screen, with the mod's font (story/font.apm: an atlas; story/font.bin: its glyphs). */
#pragma once
#include "field.h"
#include "pmath.h"

namespace st {

using namespace pm;

const uint32_t SCENE_STATE = 0x956320;              /* +2: current scene (0: the town) */
const uint32_t SAVE_PTR = 0x95af74;
const uint32_t TOWN_ID = 0xA0 + 0x55A6 + 0x14;      /* save + : the first player's town id (PersonalID + 0x14) */
const uint32_t FN_FLOW_EVENT = 0x5d80e4, FN_FLOW_BRANCH = 0x5d8800;
const uint32_t STORY_EVENT = 0x7D0, STORY_BRANCH = 0x7D1;
const float ROLL_RADIUS = 488.89f, TILE = 32.0f, PLAYER_R = 10.0f;
const int MAX_PROPS = 48, MAX_TALK = 64, MAX_VARS = 64, MAX_QUESTS = 16, MAX_GLYPHS = 160, MAX_NPCS = 12;
/* actors: actor *create_at(u16 profile, parent, info, float pos[3], stack: u16 angle[3]) (it keeps pos / angle at 0x94cfd8 for
   the new actor, then 0x528cd8(profile, parent, info, 2)); info = {u8 1, u8 0, .., char model code[4] at +4} gives a special
   character its model, as the game does for Isabelle meeting the player outdoors */
const uint32_t FN_CREATE_AT = 0x57aa34, FN_CREATE = 0x528cd8, PROFILE_NPC_OUT = 402;
const uint32_t CALL_NPC = 2000;

struct Prop {
    char id[24], mesh[48], near[16];
    int slot;                    /* near = slot: a building ID (an added building) */
    float dx, dz, yaw, scale;    /* offset from the building's tile, in tiles; yaw in degrees */
    float hx, hz;                /* solid box half extents (world units), 0: not solid */
    int show_var;                /* script value that shows it, -1: always */
    bool show_neg;
    char show[24];
    int mesh_id, inst;
    bool placed;
    float x, y, z;
};
Prop g_p[MAX_PROPS];
int g_np = 0;
char g_talk[MAX_TALK][24];
int g_ntalk = 0;
char g_var_name[MAX_VARS][24];
int g_nvars = 0;
struct Quest { char title[48]; char desc[128]; };
Quest g_q[MAX_QUESTS];
int g_nq = 0;
bool g_debug = false, g_on = false;
char g_font_path[40] = "story/font.apm", g_hud_ready[64] = "Retourne voir Marie";

/* characters the story puts in the town ([npc]) */
struct Npc {
    char id[24], near[16], code[4];
    uint32_t profile;
    int slot;
    float dx, dz, yaw;
    uint32_t actor, vtable;
    bool asked;
    float x, z;
};
Npc g_npc[MAX_NPCS];
int g_nnpc = 0;
uint32_t g_npc_parent = 0;       /* what the game gives as parent to the villagers it creates outdoors */
uint32_t g_npc_mem = 0;          /* guest memory: 0x40 per character (info, position, angle) */
int g_town_frames = 0;

void init_npc(Npc &n) {
    memset(&n, 0, sizeof n);
    n.slot = -1;
    copy_str(n.near, sizeof n.near, "town_hall");
}

/* the scripts' remembered values (acnlb_runtime.cpp's g_vars) */
int32_t *g_vars = nullptr;
bool g_dirty = false;
int g_town = -1;                 /* town id whose values are loaded */
uint32_t g_saved_us = 0;

void init_prop(Prop &p) {
    memset(&p, 0, sizeof p);
    p.slot = -1;
    p.scale = 1;
    p.show_var = -1;
    p.mesh_id = p.inst = -1;
    copy_str(p.near, sizeof p.near, "town_hall");
}

int var_index(const char *name) {
    for (int i = 0; i < g_nvars; i++) if (!strcmp(g_var_name[i], name)) return i;
    return -1;
}

void set_prop_key(Prop &p, const char *key, const char *val) {
    if (!strcmp(key, "id")) copy_str(p.id, sizeof p.id, val);
    else if (!strcmp(key, "mesh")) copy_str(p.mesh, sizeof p.mesh, val);
    else if (!strcmp(key, "near")) {
        if (!memcmp(val, "slot:", 5)) { p.slot = (int)acnl_strtol(val + 5, nullptr, 0); copy_str(p.near, sizeof p.near, "slot"); }
        else copy_str(p.near, sizeof p.near, val);
    }
    else if (!strcmp(key, "at")) {                       /* at = dx, dz (tiles) */
        char *e;
        p.dx = (float)acnl_strtol(val, &e, 0) / 16.0f;   /* sixteenths of a tile: no strtof in the plugin */
        while (*e == ',' || is_space(*e)) e++;
        p.dz = (float)acnl_strtol(e, nullptr, 0) / 16.0f;
    }
    else if (!strcmp(key, "yaw")) p.yaw = (float)acnl_strtol(val, nullptr, 0);
    else if (!strcmp(key, "scale")) p.scale = (float)acnl_strtol(val, nullptr, 0) / 100.0f;
    else if (!strcmp(key, "solid")) {                    /* solid = half x, half z (world units) */
        char *e;
        p.hx = (float)acnl_strtol(val, &e, 0);
        while (*e == ',' || is_space(*e)) e++;
        p.hz = (float)acnl_strtol(e, nullptr, 0);
    }
    else if (!strcmp(key, "show")) copy_str(p.show, sizeof p.show, val);
}

void set_npc_key(Npc &n, const char *key, const char *val) {
    if (!strcmp(key, "id")) copy_str(n.id, sizeof n.id, val);
    else if (!strcmp(key, "profile")) n.profile = (uint32_t)acnl_strtol(val, nullptr, 0);
    else if (!strcmp(key, "code")) { memset(n.code, 0, 4); for (int i = 0; i < 3 && val[i]; i++) n.code[i] = val[i]; }
    else if (!strcmp(key, "near")) {
        if (!memcmp(val, "slot:", 5)) { n.slot = (int)acnl_strtol(val + 5, nullptr, 0); copy_str(n.near, sizeof n.near, "slot"); }
        else copy_str(n.near, sizeof n.near, val);
    }
    else if (!strcmp(key, "at")) {
        char *e;
        n.dx = (float)acnl_strtol(val, &e, 0) / 16.0f;
        while (*e == ',' || is_space(*e)) e++;
        n.dz = (float)acnl_strtol(e, nullptr, 0) / 16.0f;
    }
    else if (!strcmp(key, "yaw")) n.yaw = (float)acnl_strtol(val, nullptr, 0);
}

void set_story_key(const char *key, const char *val) {
    if (!strcmp(key, "debug")) g_debug = acnl_strtol(val, nullptr, 0) != 0;
    else if (!strcmp(key, "font")) copy_str(g_font_path, sizeof g_font_path, val);
    else if (!strcmp(key, "hud_ready")) copy_str(g_hud_ready, sizeof g_hud_ready, val);
    g_on = true;
}
void set_talk_key(const char *key, const char *val) {
    if (!strcmp(key, "point") && g_ntalk < MAX_TALK) copy_str(g_talk[g_ntalk++], sizeof g_talk[0], val);
}
void set_vars_key(const char *key, const char *val) {
    int i = (int)acnl_strtol(val, nullptr, 0);
    if (i >= 0 && i < MAX_VARS) { copy_str(g_var_name[i], sizeof g_var_name[0], key); if (i >= g_nvars) g_nvars = i + 1; }
}
void set_quest_key(Quest &q, const char *key, const char *val) {
    if (!strcmp(key, "title")) copy_str(q.title, sizeof q.title, val);
    else if (!strcmp(key, "desc")) copy_str(q.desc, sizeof q.desc, val);
}

/* ------------------------------------------------------------------ remembered values, per town */

/* the town being played: its name and id (PersonalID of the first player: +0x14 town id, +0x16 town name, 9 x u16) hashed to 16
   bits (a town made by the scripted test input has id 0) */
int town_id() {
    uint32_t save = acnl_rd32(SAVE_PTR);
    if (save < 0x100000) return -1;
    uint8_t b[20];
    if (acnl_read(save + TOWN_ID, b, sizeof b) != 0) return -1;
    uint32_t h = 2166136261u;
    for (int i = 0; i < 20; i++) { h ^= b[i]; h *= 16777619u; }
    return (int)((h ^ (h >> 16)) & 0xFFFF);
}
void store_name(char *out, int town) {
    const char *hex = "0123456789abcdef";
    copy_str(out, 24, "story_0000.bin");
    for (int k = 0; k < 4; k++) out[6 + k] = hex[(town >> (12 - 4 * k)) & 15];
}
/* file: u32 count, then per value: u8 name length, name, i32 */
void vars_load(int town) {
    for (int i = 0; i < MAX_VARS; i++) g_vars[i] = 0;
    g_town = town;
    char name[24];
    store_name(name, town);
    static uint8_t buf[MAX_VARS * 32 + 4];
    int n = acnl_storage_read(name, buf, sizeof buf);
    if (n < 4) { acnl_log("story: town %04x: a new story", town); return; }
    uint32_t count;
    memcpy(&count, buf, 4);
    int o = 4, got = 0;
    for (uint32_t k = 0; k < count && o < n; k++) {
        int len = buf[o++];
        if (o + len + 4 > n || len > 23) break;
        char nm[24];
        memcpy(nm, buf + o, (size_t)len);
        nm[len] = 0;
        o += len;
        int32_t v;
        memcpy(&v, buf + o, 4);
        o += 4;
        int i = var_index(nm);
        if (i >= 0) { g_vars[i] = v; got++; }
    }
    acnl_log("story: town %04x: %d remembered value(s) loaded", town, got);
}
void vars_save() {
    if (g_town < 0) return;
    static uint8_t buf[MAX_VARS * 32 + 4];
    uint32_t count = 0;
    int o = 4;
    for (int i = 0; i < g_nvars; i++) {
        int len = (int)strlen(g_var_name[i]);
        if (!len) continue;
        buf[o++] = (uint8_t)len;
        memcpy(buf + o, g_var_name[i], (size_t)len);
        o += len;
        memcpy(buf + o, &g_vars[i], 4);
        o += 4;
        count++;
    }
    memcpy(buf, &count, 4);
    char name[24];
    store_name(name, g_town);
    acnl_storage_write(name, buf, (uint32_t)o);
    g_dirty = false;
}
/* before a script runs: the values of the town being played */
void vars_follow_town() {
    int t = town_id();
    if (t >= 0 && t != g_town) vars_load(t);
}
int32_t var_value(int i) { return i >= 0 && i < MAX_VARS && g_vars ? g_vars[i] : 0; }

/* ------------------------------------------------------------------ the font and the HUD */

struct Glyph { uint32_t cp; uint16_t x, y, w, h; int16_t ox, oy; uint16_t adv; };
Glyph g_gl[MAX_GLYPHS];
int g_ngl = 0, g_line = 12, g_font_mesh = -1, g_atlas_w = 1, g_atlas_h = 1;

void font_load() {
    char path[48];
    copy_str(path, sizeof path, g_font_path);
    int n = (int)strlen(path);
    if (n < 4) return;
    g_font_mesh = acnl_prop_mesh(path);
    memcpy(path + n - 4, ".bin", 5);
    static uint8_t buf[12 + MAX_GLYPHS * 20];
    int len = acnl_read_file(path, buf, sizeof buf);
    if (len < 12 || memcmp(buf, "FNT1", 4)) { acnl_log("story: no font (%s)", path); g_font_mesh = -1; return; }
    uint16_t cnt, line, aw, ah;
    memcpy(&cnt, buf + 4, 2); memcpy(&line, buf + 6, 2); memcpy(&aw, buf + 8, 2); memcpy(&ah, buf + 10, 2);
    g_line = line; g_atlas_w = aw ? aw : 1; g_atlas_h = ah ? ah : 1;
    for (int i = 0; i < cnt && i < MAX_GLYPHS && 12 + (i + 1) * 20 <= len; i++) memcpy(&g_gl[i], buf + 12 + i * 20, 20);
    g_ngl = cnt < MAX_GLYPHS ? cnt : MAX_GLYPHS;
}
const Glyph *glyph(uint32_t cp) {
    for (int i = 0; i < g_ngl; i++) if (g_gl[i].cp == cp) return &g_gl[i];
    return nullptr;
}
uint32_t utf8_next(const char *&s) {
    uint8_t c = (uint8_t)*s++;
    if (c < 0x80) return c;
    int n = c >= 0xF0 ? 3 : c >= 0xE0 ? 2 : 1;
    uint32_t cp = c & (0x3F >> n);
    for (int i = 0; i < n && *s; i++) cp = (cp << 6) | ((uint8_t)*s++ & 0x3F);
    return cp;
}
void ui_rect(int screen, float x, float y, float w, float h, const float rgba[4]) {
    const float r[4] = {x, y, w, h}, uv[4] = {0, 0, 1, 1};
    acnl_ui_quad(screen, r, -1, -1, uv, rgba);
}
float text_width(const char *s, float scale) {
    float w = 0;
    while (*s) { const Glyph *g = glyph(utf8_next(s)); if (g) w += g->adv * scale; }
    return w;
}
/* text from (x, y) (its top), wrapping at max_w, `px` pixels a line; returns the height used. draw = false only measures */
float ui_text(int screen, float x, float y, float max_w, const char *s, float px, const float rgba[4], bool draw = true) {
    if (g_font_mesh < 0 || g_line <= 0) return 0;
    float scale = px / g_line, cx = x, cy = y;
    while (*s) {
        /* the next word: does it fit on this line? */
        const char *w = s;
        float ww = 0;
        while (*w && *w != ' ') { const Glyph *g = glyph(utf8_next(w)); if (g) ww += g->adv * scale; }
        if (cx > x && cx + ww > x + max_w) { cx = x; cy += px; }
        while (*s && *s != ' ') {
            const Glyph *g = glyph(utf8_next(s));
            if (!g) continue;
            if (draw) {
                const float r[4] = {cx + g->ox * scale, cy + g->oy * scale, g->w * scale, g->h * scale};
                const float uv[4] = {(float)g->x / g_atlas_w, (float)g->y / g_atlas_h, (float)(g->x + g->w) / g_atlas_w, (float)(g->y + g->h) / g_atlas_h};
                acnl_ui_quad(screen, r, g_font_mesh, 0, uv, rgba);
            }
            cx += g->adv * scale;
        }
        if (*s == ' ') { const Glyph *g = glyph(' '); cx += (g ? g->adv : g_line / 4) * scale; s++; }
    }
    return cy - y + px;
}

int g_var_quest = -1, g_var_ready = -1, g_var_hud = -1;
void hud(bool town) {
    acnl_ui_begin();
    int qi = var_value(g_var_quest);
    bool show = town && g_nq && var_value(g_var_hud) != 0 && qi >= 0 && qi < g_nq;
    if (show) {
        const Quest &q = g_q[qi];
        bool ready = var_value(g_var_ready) != 0;
        static const float panel[4] = {0.99f, 0.96f, 0.86f, 0.85f}, edge[4] = {1, 1, 1, 0.9f};
        static const float ink[4] = {0.35f, 0.24f, 0.07f, 1}, green[4] = {0.15f, 0.55f, 0.13f, 1};
        const float x = 4, y = 4, w = 128, pad = 4, title_px = 10, desc_px = 8.5f;
        const char *title = ready ? "Quête terminée !" : q.title, *desc = ready ? g_hud_ready : q.desc;
        float h = pad + ui_text(0, 0, 0, w - 2 * pad, title, title_px, ink, false) + 1 + ui_text(0, 0, 0, w - 2 * pad, desc, desc_px, ink, false) + pad;
        ui_rect(0, x - 1, y - 1, w + 2, h + 2, edge);
        ui_rect(0, x, y, w, h, panel);
        float ty = y + pad;
        ty += ui_text(0, x + pad, ty, w - 2 * pad, title, title_px, ready ? green : ink) + 1;
        ui_text(0, x + pad, ty, w - 2 * pad, desc, desc_px, ready ? green : ink);
    }
    acnl_ui_end();
}

/* ------------------------------------------------------------------ props */

/* the building tile a prop (or a character) stands by, false if the town has none */
bool anchor_at(const char *near, int slot, int *tx, int *tz);
bool anchor(const Prop &p, int *tx, int *tz) { return anchor_at(p.near, p.slot, tx, tz); }
bool anchor_at(const char *near, int slot, int *tx, int *tz) {
    struct { const char *near; int slot; } p = {near, slot};
    if (!strcmp(p.near, "station")) return veh::building_tile(0x54, 0x57, tx, tz);
    if (!strcmp(p.near, "town_hall")) return veh::building_tile(0x50, 0x53, tx, tz);
    if (!strcmp(p.near, "retail")) return veh::building_tile(0x58, 0x58, tx, tz);
    if (!strcmp(p.near, "bbs")) return veh::building_tile(0x5B, 0x5B, tx, tz);
    if (!strcmp(p.near, "pier")) return veh::building_tile(0x5C, 0x5C, tx, tz) || veh::building_tile(0x68, 0x68, tx, tz);
    if (!strcmp(p.near, "boat")) return veh::building_tile(0x5D, 0x5D, tx, tz);
    if (!strcmp(p.near, "reset")) return veh::building_tile(0x4F, 0x4F, tx, tz);
    if (!strcmp(p.near, "bridge")) return veh::building_tile(0x90, 0xA7, tx, tz);
    if (!strcmp(p.near, "plaza")) return veh::building_tile(0x59, 0x59, tx, tz);
    if (!strcmp(p.near, "crossing")) return veh::building_tile(0x5A, 0x5A, tx, tz);
    if (!strcmp(p.near, "slot")) return veh::building_tile((uint16_t)p.slot, (uint16_t)p.slot, tx, tz);
    if (!strcmp(p.near, "tile")) { *tx = 0; *tz = 0; return true; }
    return false;
}

void place_props() {
    for (int i = 0; i < g_np; i++) {
        Prop &p = g_p[i];
        int tx, tz;
        p.placed = false;
        if (!anchor(p, &tx, &tz)) { if (g_debug) acnl_log("story: prop %s: no %s in this town", p.id, p.near); continue; }
        p.x = tx * TILE + TILE / 2 + p.dx * TILE;
        p.z = tz * TILE + TILE / 2 + p.dz * TILE;
        uint8_t kind;
        if (!field::ground(p.x, p.z, &p.y, &kind)) p.y = 0;
        p.placed = true;
        if (g_debug) acnl_log("story: prop %s by %s (%d, %d) at %.0f, %.0f, %.0f", p.id, p.near, tx, tz, p.x, p.y, p.z);
    }
}

bool prop_shown(const Prop &p) {
    if (!p.placed) return false;
    if (p.show_var < 0) return true;
    return (var_value(p.show_var) != 0) != p.show_neg;
}

void draw_props(bool town) {
    static const float zero[12] = {0};
    for (int i = 0; i < g_np; i++) {
        Prop &p = g_p[i];
        if (p.inst < 0) continue;
        if (!town || !prop_shown(p)) { acnl_prop_place(p.inst, zero, 0); continue; }
        float r[12], m[12];
        m_rot_y(p.yaw * PI / 180, r);
        for (int k = 0; k < 12; k++) if (k % 4 != 3) r[k] *= p.scale;
        m_translate(p.x, p.y, p.z, m);
        m_mul(m, r, m);
        acnl_prop_place(p.inst, m, 1);
    }
}

/* the player out of the solid boxes */
void push_player(uint32_t player) {
    float pp[3];
    if (acnl_read(player + 0x14, pp, 12) != 0) return;
    bool moved = false;
    for (int i = 0; i < g_np; i++) {
        const Prop &p = g_p[i];
        if (p.hx <= 0 || !prop_shown(p)) continue;
        float s, c;
        sincos(p.yaw * PI / 180, &s, &c);
        float dx = pp[0] - p.x, dz = pp[2] - p.z;
        float lx = c * dx - s * dz, lz = s * dx + c * dz;     /* into the prop's frame (turned by -yaw) */
        float ex = p.hx * p.scale + PLAYER_R, ez = p.hz * p.scale + PLAYER_R;
        if (absf(lx) >= ex || absf(lz) >= ez) continue;
        if (ex - absf(lx) < ez - absf(lz)) lx = lx < 0 ? -ex : ex; else lz = lz < 0 ? -ez : ez;
        pp[0] = p.x + c * lx + s * lz;
        pp[2] = p.z - s * lx + c * lz;
        moved = true;
    }
    if (moved) acnl_write(player + 0x14, pp, 12);
}

/* ------------------------------------------------------------------ characters */

/* the game creating an actor: who it gives as parent to its own characters (logged once per profile while debugging) */
uint8_t g_create_seen[640];
struct Created { uint32_t profile; } g_created_stack[8];
int g_created_n = 0;
int hook_create_pre(void *) {
    uint32_t prof = acnl_reg(0) & 0xFFFF, parent = acnl_reg(1), info = acnl_reg(2);
    if (g_created_n < 8) g_created_stack[g_created_n].profile = prof;
    g_created_n++;
    if (prof == PROFILE_NPC_OUT && parent >= 0x100000) g_npc_parent = parent;
    if (g_debug && prof >= 380 && prof < 640 && g_create_seen[prof] < 2) {
        g_create_seen[prof]++;
        uint32_t w[8] = {0};
        if (info >= 0x100000) acnl_read(info, w, sizeof w);
        acnl_log("story: create %u parent %08x info %08x [%08x %08x %08x %08x] kind %u from %08x", (unsigned)prof, (unsigned)parent, (unsigned)info,
                 (unsigned)w[0], (unsigned)w[1], (unsigned)w[2], (unsigned)w[3], (unsigned)acnl_reg(3), (unsigned)acnl_return_address());
    }
    return ACNL_CONTINUE;
}
void hook_create_post(void *) {
    if (g_created_n > 0) g_created_n--;
}

void spawn_npcs(uint32_t player) {
    if (!g_nnpc) return;
    uint32_t parent = g_npc_parent ? g_npc_parent : (g_town_frames > 240 ? player : 0);
    if (!parent) return;
    if (!g_npc_mem) g_npc_mem = acnl_alloc(0x40 * MAX_NPCS, 4);
    if (!g_npc_mem) return;
    for (int i = 0; i < g_nnpc; i++) {
        Npc &n = g_npc[i];
        if (n.asked) continue;
        n.asked = true;
        int tx, tz;
        if (!anchor_at(n.near, n.slot, &tx, &tz)) { acnl_log("story: npc %s: no %s in this town", n.id, n.near); continue; }
        n.x = tx * TILE + TILE / 2 + n.dx * TILE;
        n.z = tz * TILE + TILE / 2 + n.dz * TILE;
        float y = 0;
        uint8_t kind;
        if (!field::ground(n.x, n.z, &y, &kind)) y = 0;
        uint32_t m = g_npc_mem + (uint32_t)i * 0x40;
        uint8_t info[0x20] = {0};
        info[0] = 1;
        memcpy(info + 4, n.code, 4);
        float pos[4] = {n.x, y, n.z, 0};
        uint16_t ang[8] = {0, (uint16_t)(n.yaw * 65536.0f / 360.0f), 0, 0};
        acnl_write(m, info, sizeof info);
        acnl_write(m + 0x20, pos, 16);
        acnl_write(m + 0x30, ang, 16);
        const uint32_t args[5] = {n.profile, parent, n.code[0] ? m : 0, m + 0x20, m + 0x30};
        int rc = acnl_call(CALL_NPC + (uint32_t)i, FN_CREATE_AT, args, 5);
        acnl_log("story: npc %s: asking for actor %u (model %s) at %.0f, %.0f (parent %08x%s): %d", n.id, (unsigned)n.profile, n.code, n.x, n.z,
                 (unsigned)parent, g_npc_parent ? "" : ", the player", rc);
        return;                                          /* one per frame */
    }
}
void npc_created(uint32_t id, uint32_t actor) {
    int i = (int)(id - CALL_NPC);
    if (i < 0 || i >= g_nnpc) return;
    Npc &n = g_npc[i];
    n.actor = actor >= 0x100000 ? actor : 0;
    n.vtable = n.actor ? acnl_rd32(n.actor) : 0;
    acnl_log("story: npc %s: actor %08x (vtable %08x)", n.id, (unsigned)actor, (unsigned)n.vtable);
}
/* the story's character the player is talking to: the nearest one, where it really stands (as its index in the [npc] list). An
   empty conversation makes the class start another at once (seen in game: a loop), so the nearest one always answers;
   g_nnpc only when none exists. */
int speaker(uint32_t player) {
    float pp[3];
    if (player < 0x100000 || acnl_read(player + 0x14, pp, 12) != 0) return g_nnpc;
    int best = g_nnpc;
    float best_d = 1e30f;
    for (int i = 0; i < g_nnpc; i++) {
        const Npc &n = g_npc[i];
        float ap[3];
        if (!n.actor || acnl_read(n.actor + 0x14, ap, 12) != 0) continue;
        float dx = ap[0] - pp[0], dz = ap[2] - pp[2], d = dx * dx + dz * dz;
        if (d < best_d) { best_d = d; best = i; }
    }
    if (g_debug) acnl_log("story: the speaker is %s (%.0f away)", best < g_nnpc ? g_npc[best].id : "nobody", best < g_nnpc ? sqrtf(best_d) : 0.0f);
    return best;
}

/* characters stay where the story put them (the game would walk them to its own spots) */
void hold_npcs() {
    for (int i = 0; i < g_nnpc; i++) {
        Npc &n = g_npc[i];
        if (!n.actor) continue;
        if (acnl_rd32(n.actor) != n.vtable) { acnl_log("story: npc %s is gone", n.id); n.actor = 0; continue; }
        float pos[3];
        if (acnl_read(n.actor + 0x14, pos, 12) != 0) continue;
        float dx = pos[0] - n.x, dz = pos[2] - n.z;
        if (dx * dx + dz * dz > 4.0f) {
            acnl_write(n.actor + 0x14, &n.x, 4); acnl_write(n.actor + 0x1C, &n.z, 4);
            acnl_write(n.actor + 0x20, &n.x, 4); acnl_write(n.actor + 0x28, &n.z, 4);
        }
    }
}

/* debug: Select + L puts the player in front of the next story character, facing them (testing without walking) */
int g_warp_next = 0;
uint32_t g_prev_buttons = 0;
void debug_warp(uint32_t player) {
    acnl_pad pad;
    acnl_pad_read(&pad);
    const uint32_t combo = ACNL_BTN_SELECT | ACNL_BTN_L;
    bool now = (pad.buttons & combo) == combo, before = (g_prev_buttons & combo) == combo;
    g_prev_buttons = pad.buttons;
    if (!now || before || !g_nnpc) return;
    for (int k = 0; k < g_nnpc; k++) {
        Npc &n = g_npc[(g_warp_next + k) % g_nnpc];
        if (!n.actor) continue;
        g_warp_next = (g_warp_next + k + 1) % g_nnpc;
        float pos[3] = {n.x, 0, n.z + 26};
        uint8_t kind;
        if (!field::ground(pos[0], pos[2], &pos[1], &kind)) pos[1] = 0;
        acnl_write(player + 0x14, pos, 12);
        acnl_write(player + 0x20, pos, 12);
        acnl_wr16(player + 0x34, 0x8000);              /* facing north, towards the character */
        acnl_log("story: debug warp to %s", n.id);
        return;
    }
}

/* ------------------------------------------------------------------ setup, every frame */

void init(int32_t *vars) {
    g_vars = vars;
    for (int i = 0; i < g_np; i++) {
        Prop &p = g_p[i];
        if (p.show[0]) { p.show_neg = p.show[0] == '!'; p.show_var = var_index(p.show + (p.show_neg ? 1 : 0)); }
        p.mesh_id = acnl_prop_mesh(p.mesh);
        p.inst = p.mesh_id >= 0 ? acnl_prop_new(p.mesh_id) : -1;
        if (p.inst < 0) acnl_log("story: prop %s: no mesh %s", p.id, p.mesh);
    }
    g_var_quest = var_index("quest");
    g_var_ready = var_index("quest_ready");
    g_var_hud = var_index("quest_on");
    font_load();
    acnl_log("story: %d prop(s), %d talk point(s), %d remembered value name(s), %d quest(s)%s", g_np, g_ntalk, g_nvars, g_nq,
             g_font_mesh >= 0 ? ", HUD font" : "");
}

bool g_in_town = false;
void tick(uint32_t player) {
    if (!g_on) return;
    bool town = acnl_rd8(SCENE_STATE + 2) == 0 && player >= 0x100000 && field::refresh();
    if (!town) {
        if (g_in_town) for (int i = 0; i < g_nnpc; i++) { g_npc[i].asked = false; g_npc[i].actor = 0; }   /* left: created again next time */
        g_town_frames = 0;
    }
    if (town) {
        if (++g_town_frames > 90) spawn_npcs(player);
        hold_npcs();
        if (g_debug) debug_warp(player);
        vars_follow_town();
        uint32_t mtx = veh::player_render_matrix(player);
        if (mtx) acnl_world_roll(mtx, player + 0x14, ROLL_RADIUS);
        if (!g_in_town) place_props();
        push_player(player);
    }
    g_in_town = town;
    draw_props(town);
    hud(town);
    uint32_t now = acnl_time_us();
    if (g_dirty && now - g_saved_us > 1000000u) { g_saved_us = now; vars_save(); }
}

}  // namespace st
