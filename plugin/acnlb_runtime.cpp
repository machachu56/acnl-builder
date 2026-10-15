/* ACNL Builder runtime: the one WebAssembly plugin every Builder mod ships.

   It is generic: everything that differs between mods is read from acnlb.cfg, written by the Builder
   when it exports. The plugin knows the game's addresses (Welcome amiibo, main executable) and does
   the parts RomFS replacement cannot:

   [building] sections -- custom town buildings.
     The game has no free building ID (0x00-0xFB are all taken, 0xFC = empty), so a building takes over
     the slot of a type the town does not normally have (the public works projects, 0x4C..0x80). For that
     ID the name used to find the model/textures/data is redirected (to /Strc/sobj/<model>/...), the
     interior scene is set, the building is added to the town's building list right before the game
     instantiates it (so it is there from day one in a new town and appears in existing towns), and
     entering through its door switches on the RomFS variant "romfs.<variant>" with the interior, its
     text and the room's collision grid. Any other door switches it off again.

   Virtual buildings (config "alias = <base ID>"): instead of editing the game's per-building tables, the plugin
     hooks the ~20 small lookup functions (each `cmp id, #0xFC` + a table read) and, for the building's ID,
     answers as the alias building would (same footprint, door, scene...), except for the model name (and, when
     configured, the footprint and scene), which are the mod's own. The ID can be any spare one, so the
     building the alias stands for (e.g. the police station) is left alone. IDs >= 0xFC do not work: the game
     keeps a building's ID in one byte and treats 0xFC and above as "no building" in many places (tested).

   The interior scene is shared with the building that normally owns it (Nook's Homes on Main Street);
   its exit leads to the building listed for the scene, so that entry is pointed at whichever door the
   player came in by. */
#include "acnl_mod.h"

namespace {

/* game addresses */
const uint32_t BLD_NAME_TABLE = 0x95a6e8;    /* const char *name[0xFC] (.data) */
const uint32_t BLD_SCENE_TABLE = 0x88a5d8;   /* u8 interior scene per ID, 0xA5 = none */
const uint32_t BLD_RECT_TABLE = 0x88a7d4;    /* s8 x0, y0, x1, y1 footprint per ID */
const uint32_t SCENE_BLD_TABLE = 0x888428;   /* u8 building ID per interior scene: where its exit leads */
const uint32_t FN_BUILDING_SCENE = 0x5c9380; /* u8 scene(u8 building): looked up when walking through a door */
const uint32_t SAVE_PTR = 0x95af74;          /* -> garden_plus.dat image in memory */
const uint32_t TOWN_BUILDINGS = 0x4be80;     /* building block within the save */
const uint32_t FN_PLACE_TOWN_BUILDINGS = 0x242470;
const uint32_t FN_JMP_BLOCK = 0x1c1ff4;      /* u16 *block(obj, index): collision grid of an acre or a room */
const uint32_t JMP_INDOOR_BASE = 0x109;      /* indoor rooms follow the 0x109 outdoor blocks */
const uint32_t JMP_SIZE = 0xA00;
const uint32_t FN_ACTOR_CREATE = 0x51fd74;   /* actor *create(u16 profile) */
const uint32_t PROFILE_FTR_FIRST = 0xbb;     /* AcFtr .. AcFtrGossipStone: furniture actors */
const uint32_t PROFILE_FTR_LAST = 0xeb;
const int MAX_BUILDINGS = 56;
const uint16_t EMPTY = 0xFC;
const int MAX_MODS = 8;
const int TILE = 32;

/* the game's per-building lookups: function entry, register holding the building ID.
   Each is `cmp id, #0xFC` followed by a table read (or a default), see recomp notes */
struct IdFn { uint32_t addr; int reg; };
const IdFn ID_FNS[] = {
    {0x5c87ac, 0}, {0x5c87f8, 0}, {0x5c8900, 0}, {0x5c922c, 0}, {0x5c92a4, 0}, {0x5c92bc, 0}, {0x5c92d4, 0}, {0x5c92ec, 0},
    {0x5c9304, 3}, {0x5c93b0, 1}, {0x5c93f0, 0}, {0x5c9408, 0}, {0x5c9444, 1}, {0x5c94d0, 0}, {0x5c950c, 0}, {0x5c9548, 0},
    {0x5c9588, 0}, {0x5c95c4, 0}, {0x5c95dc, 0}, {0x5c9618, 0},
};
const uint32_t FN_BLD_NAME = 0x5c8794;       /* const char *name(u8 id) */
const uint32_t FN_BLD_RECT_SIZE = 0x5c87ac;  /* u16 (width | height << 8) of the footprint */
const uint32_t FN_BLD_RECT_PTR = 0x5c928c;   /* s8 *rect(u8 id): x0, y0, x1, y1 */
/* the town map: one call per building (id in r1) picks the icon widget by a switch on the ID, then
   sets its "kind" (r1 of the widget call); kind - base[widget type] is the cell of the icon sheet */
const uint32_t FN_MAP_ICON_FOR = 0x221f60;   /* widget *icon_for(map, u8 id) */
const uint32_t FN_MAP_ICON_KIND = 0x60ce78;  /* void set_kind(widget, kind) */
const uint32_t MAP_KIND_BASE = 0x9523e0;     /* u8 base kind per widget type (0, 15, 22) */

/* a building's interior can have several rooms ("pages"): each its own room model (a RomFS variant) and
   collision grid. Link tiles of a page are exit tiles; when the game starts leaving the building and the
   player stands on one, the plugin turns the scene change into an arrival in the linked room. */
const int MAX_PAGES = 8, MAX_LINKS = 8;
const uint32_t PROFILE_PLAYER = 0x69;        /* the player's actor; its position is at +0x14 */
const int SCENE_ARRIVE_INDOOR = 0x2f;        /* first stack argument of a scene change that arrives through a door */
struct Link { int x, y, to, ax, ay, yaw; };
struct Page {
    char variant[40];             /* RomFS variant with this room's model */
    char jmp_file[48];            /* its collision grid file */
    uint32_t jmp;                 /* guest copy of the grid */
    Link links[MAX_LINKS];
    int nlinks;
};
struct Building {
    char id[32];
    char model[16];               /* name the game looks the model up by */
    char variant[32];             /* RomFS variant with the building's text, on inside any of its rooms */
    Page pages[MAX_PAGES];
    int npages;
    int slot;
    int alias;                    /* virtual buildings: the building whose table rows this one shares */
    int icon_frame;               /* town-map icon: cell of the icon sheet, or -1 for the alias' own */
    uint32_t name_ptr, rect_ptr;
    int scene;                    /* interior scene, or -1 to keep the slot's own */
    int room;                     /* indoor model index of the scene (Nook's Homes = 48) */
    int x, y;                     /* absolute position on the town grid, or -1 */
    int dx, dy;                   /* offset from the town hall when x/y are unset */
    bool set_rect;
    int rect[4];
    bool hide_furniture;
};

/* the plugin has no static constructors (no libc start-up), so every struct is plain data, zeroed, and set up here */
void init_building(Building &b) {
    memset(&b, 0, sizeof b);
    b.slot = b.alias = b.icon_frame = b.scene = -1;
    b.room = 48;
    b.x = b.y = -1;
    b.dx = 4;
    b.dy = 7;
}

Building g_b[MAX_MODS];
int g_nb;
int g_cur = -1;                   /* building whose door the player used, or -1 */
int g_page = 0;                   /* the room of that building the player is in */
bool g_trace = false, g_debug_enter = false;
uint8_t g_scene_owner[0xA5];      /* the building ID each scene normally leads out to */

void select_page(Building &b, int page);

bool is_space(char c) { return c == ' ' || c == '\t' || c == '\r'; }

void copy_str(char *dst, uint32_t cap, const char *src) {
    uint32_t n = strlen(src);
    if (n >= cap) n = cap - 1;
    memcpy(dst, src, n);
    dst[n] = 0;
}

void set_key(Building &b, const char *key, const char *val) {
    long v = acnl_strtol(val, nullptr, 0);
    if (!strcmp(key, "id")) copy_str(b.id, sizeof b.id, val);
    else if (!strcmp(key, "model")) copy_str(b.model, sizeof b.model, val);
    else if (!strcmp(key, "variant")) copy_str(b.variant, sizeof b.variant, val);
    else if (!strcmp(key, "slot")) b.slot = (int)v;
    else if (!strcmp(key, "alias")) b.alias = (int)v;
    else if (!strcmp(key, "icon_frame")) b.icon_frame = (int)v;
    else if (!strcmp(key, "scene")) b.scene = (int)v;
    else if (!strcmp(key, "room")) b.room = (int)v;
    else if (!strcmp(key, "x")) b.x = (int)v;
    else if (!strcmp(key, "y")) b.y = (int)v;
    else if (!strcmp(key, "dx")) b.dx = (int)v;
    else if (!strcmp(key, "dy")) b.dy = (int)v;
    else if (!strcmp(key, "hide_furniture")) b.hide_furniture = v != 0;
    else if (!strcmp(key, "rect")) {
        const char *p = val;
        int k = 0;
        for (; k < 4; k++) {
            char *e;
            b.rect[k] = (int)acnl_strtol(p, &e, 0);
            if (e == p) break;
            p = e;
            while (is_space(*p)) p++;
            if (*p == ',') p++;
        }
        b.set_rect = k == 4;
    }
}

void set_page_key(Page &p, const char *key, const char *val) {
    if (!strcmp(key, "variant")) copy_str(p.variant, sizeof p.variant, val);
    else if (!strcmp(key, "jmp")) copy_str(p.jmp_file, sizeof p.jmp_file, val);
    else if (!strcmp(key, "link") && p.nlinks < MAX_LINKS) {      /* link = x, y, to page, arrival x, y, yaw */
        int v[6] = {0, 0, 0, 0, 0, 0};
        const char *q = val;
        for (int k = 0; k < 6; k++) {
            char *e;
            v[k] = (int)acnl_strtol(q, &e, 0);
            if (e == q) break;
            q = e;
            while (is_space(*q)) q++;
            if (*q == ',') q++;
        }
        p.links[p.nlinks++] = {v[0], v[1], v[2], v[3], v[4], v[5]};
    }
}

/* acnlb.cfg: "[building]" starts a section, "key = value" lines, '#' comments */
void load_config() {
    static char text[8192];
    int n = acnl_read_file("acnlb.cfg", text, sizeof text - 1);
    if (n <= 0) return;
    if (n > (int)sizeof text - 1) n = sizeof text - 1;
    text[n] = 0;
    Building *cur = nullptr;
    Page *page = nullptr;
    for (char *line = text; *line;) {
        char *end = line;
        while (*end && *end != '\n') end++;
        char *next = *end ? end + 1 : end;
        *end = 0;
        for (char *h = line; *h; h++) if (*h == '#') { *h = 0; break; }
        while (is_space(*line)) line++;
        if (*line == '[') {
            page = nullptr;
            if (!memcmp(line, "[building]", 10)) { cur = g_nb < MAX_MODS ? &g_b[g_nb++] : nullptr; if (cur) init_building(*cur); }
            else if (!memcmp(line, "[page]", 6) && cur && cur->npages < MAX_PAGES) page = &cur->pages[cur->npages++];
        } else if (cur) {
            char *eq = line;
            while (*eq && *eq != '=') eq++;
            if (*eq == '=') {
                *eq = 0;
                char *ke = eq;
                while (ke > line && is_space(ke[-1])) *--ke = 0;
                char *val = eq + 1;
                while (is_space(*val)) val++;
                char *ve = val + strlen(val);
                while (ve > val && is_space(ve[-1])) *--ve = 0;
                if (page) set_page_key(*page, line, val); else set_key(*cur, line, val);
            }
        }
        line = next;
    }
}

int find_building(uint32_t slot) {
    for (int i = 0; i < g_nb; i++) if (g_b[i].slot == (int)slot) return i;
    return -1;
}

/* footprint (s8 x0, y0, x1, y1 around the position) of a building ID, as the game or this mod defines it */
bool footprint(uint32_t id, int r[4]) {
    int i = find_building(id);
    if (i >= 0 && g_b[i].set_rect) { for (int k = 0; k < 4; k++) r[k] = g_b[i].rect[k]; return true; }
    if (i >= 0 && g_b[i].alias >= 0) id = (uint32_t)g_b[i].alias;
    if (id >= 0xFC) return false;
    for (int k = 0; k < 4; k++) r[k] = (int8_t)acnl_rd8(BLD_RECT_TABLE + id * 4 + k);
    return true;
}

/* does a building `id` at (x, y) overlap (or touch) one of the town's buildings? */
bool crowded(uint32_t blk, uint32_t id, int x, int y) {
    int a[4];
    if (!footprint(id, a)) { if (g_trace) acnl_log("builder: no footprint for id %#x", id); return false; }
    for (int i = 0; i < MAX_BUILDINGS; i++) {
        uint32_t e = blk + 8 + i * 4;
        uint16_t oid = acnl_rd16(e);
        int b[4];
        if (oid == EMPTY || !footprint(oid, b)) continue;
        int ox = acnl_rd8(e + 2), oy = acnl_rd8(e + 3);
        if (x + a[2] + 1 >= ox + b[0] && x + a[0] - 1 <= ox + b[2] && y + a[3] + 1 >= oy + b[1] && y + a[1] - 1 <= oy + b[3]) {
            if (g_trace) acnl_log("builder: (%d,%d) overlaps %#x at %d,%d", x, y, oid, ox, oy);
            return true;
        }
    }
    return false;
}

/* make sure the town's building list contains every building of the mod */
void ensure_buildings() {
    uint32_t save = acnl_rd32(SAVE_PTR);
    if (!save) return;
    uint32_t blk = save + TOWN_BUILDINGS;
    /* entries with an ID above 0xFB (other than "empty") are no buildings: clear such leftovers (an earlier build of
       this plugin could write 0xFF) so they neither pile up nor block the spot */
    for (int i = 0; i < MAX_BUILDINGS; i++) {
        uint32_t e = blk + 8 + i * 4;
        uint16_t id = acnl_rd16(e);
        if (id != EMPTY && id > 0xFB) {
            acnl_wr16(e, EMPTY);
            acnl_wr8(blk + 4, (uint8_t)(acnl_rd8(blk + 4) - 1));
            acnl_log("builder: cleared a leftover entry (%#x at %d, %d)", id, acnl_rd8(e + 2), acnl_rd8(e + 3));
        }
    }
    if (g_trace) {
        acnl_log("builder: town buildings (count %d):", acnl_rd8(blk + 4));
        for (int i = 0; i < MAX_BUILDINGS; i++) {
            uint32_t e = blk + 8 + i * 4;
            if (acnl_rd16(e) != EMPTY) acnl_log("   #%d id %#x at %d, %d", i, acnl_rd16(e), acnl_rd8(e + 2), acnl_rd8(e + 3));
        }
    }
    for (int k = 0; k < g_nb; k++) {
        Building &b = g_b[k];
        if (g_trace) acnl_log("builder: ensure %s: slot %d alias %d x %d y %d dx %d dy %d npages %d", b.id, b.slot, b.alias, b.x, b.y, b.dx, b.dy, b.npages);
        int free_slot = -1;
        bool have = false;
        for (int i = 0; i < MAX_BUILDINGS; i++) {
            uint16_t id = acnl_rd16(blk + 8 + i * 4);
            if (id == b.slot) { have = true; break; }
            if (id == EMPTY && free_slot < 0) free_slot = i;
        }
        if (have) continue;
        if (free_slot < 0) { acnl_log("builder: no free building slot in this town for %s", b.id); continue; }
        int x = b.x, y = b.y;
        if (x < 0 || y < 0) {       /* relative to the town hall */
            for (int i = 0; i < MAX_BUILDINGS; i++) {
                uint32_t e = blk + 8 + i * 4;
                uint16_t id = acnl_rd16(e);
                if (id >= 0x50 && id <= 0x53) { x = acnl_rd8(e + 2) + b.dx; y = acnl_rd8(e + 3) + b.dy; }
            }
            if (x < 0) { x = 0x4C + b.dx - 4; y = 0x20 + b.dy - 7; }
        }
        if (b.x < 0 || b.y < 0) {   /* no fixed position: step aside, outwards, until nothing is in the way */
            int bx = x, by = y;
            for (int ring = 0; ring <= 14 && crowded(blk, (uint32_t)b.slot, x, y); ring++)
                for (int dyy = -ring; dyy <= ring; dyy++)
                    for (int dxx = -ring; dxx <= ring; dxx++) {
                        if ((dxx > -ring && dxx < ring && dyy > -ring && dyy < ring) || bx + dxx < 0 || by + dyy < 0 || bx + dxx > 0x6F || by + dyy > 0x5F) continue;
                        if (!crowded(blk, (uint32_t)b.slot, bx + dxx, by + dyy)) { x = bx + dxx; y = by + dyy; ring = 99; dyy = ring; break; }
                    }
            if (x != bx || y != by) acnl_log("builder: %s moved from (%02x, %02x) to (%02x, %02x), the spot was taken", b.id, bx, by, x, y);
        }
        uint8_t e[4] = {(uint8_t)b.slot, 0, (uint8_t)x, (uint8_t)y};
        acnl_write(blk + 8 + free_slot * 4, e, 4);
        acnl_wr8(blk + 4, (uint8_t)(acnl_rd8(blk + 4) + 1));
        acnl_log("builder: %s built at (%02x, %02x), slot %d", b.id, x, y, free_slot);
    }
}

/* a pre/post pair keeps what it needs from the call on a small stack: the same function can run nested */
const int DEPTH = 8;
struct Saved { uint32_t v[DEPTH]; int n; };
void push(Saved &s, uint32_t v) { if (s.n < DEPTH) s.v[s.n] = v; s.n++; }
uint32_t pop(Saved &s) { if (s.n <= 0) return 0; s.n--; return s.n < DEPTH ? s.v[s.n] : 0; }

/* the room's collision grid: the building's own while inside it */
Saved s_jmp;
int hook_jmp_block_pre(void *) { push(s_jmp, acnl_reg(1)); return ACNL_CONTINUE; }
void hook_jmp_block_post(void *) {
    uint32_t index = pop(s_jmp);
    if (g_cur >= 0 && g_page < g_b[g_cur].npages && g_b[g_cur].pages[g_page].jmp && index == JMP_INDOOR_BASE + (uint32_t)g_b[g_cur].room && acnl_reg(0))
        acnl_set_reg(0, g_b[g_cur].pages[g_page].jmp);
}

/* the player's actor, remembered when the game creates it: its position tells which link tile it stands on */
uint32_t g_player = 0;
Saved s_prof;
int hook_actor_track_pre(void *) { push(s_prof, acnl_reg(0) & 0xFFFF); return ACNL_CONTINUE; }
void hook_actor_track_post(void *) {
    uint32_t prof = pop(s_prof), a = acnl_reg(0);
    if (prof == PROFILE_PLAYER && a >= 0x100000) g_player = a;
}

/* furniture actors (Tom Nook's exhibits...): a building with its own furnished room creates none */
int hook_actor_create_pre(void *) {
    uint32_t profile = acnl_reg(0) & 0xFFFF;
    if (g_cur >= 0 && g_b[g_cur].hide_furniture && profile >= PROFILE_FTR_FIRST && profile <= PROFILE_FTR_LAST) {
        acnl_set_reg(0, 0);
        return ACNL_SKIP;
    }
    return ACNL_CONTINUE;
}

/* ---- new IDs: answer the game's per-building lookups ---- */
Building *new_id_building(uint32_t id) {
    int i = find_building(id);
    return i >= 0 && g_b[i].alias >= 0 ? &g_b[i] : nullptr;
}

/* look up as the alias building would */
int hook_alias_pre(void *user) {
    int reg = (int)(intptr_t)user;
    Building *b = new_id_building(acnl_reg(reg));
    if (b && b->alias >= 0) acnl_set_reg(reg, (uint32_t)b->alias);
    return ACNL_CONTINUE;
}

int hook_name_pre(void *) {
    Building *b = new_id_building(acnl_reg(0));
    if (!b || !b->name_ptr) return ACNL_CONTINUE;
    acnl_set_reg(0, b->name_ptr);
    return ACNL_SKIP;
}

int hook_rect_ptr_pre(void *) {
    Building *b = new_id_building(acnl_reg(0));
    if (!b) return ACNL_CONTINUE;
    if (b->set_rect && b->rect_ptr) { acnl_set_reg(0, b->rect_ptr); return ACNL_SKIP; }
    if (b->alias >= 0) acnl_set_reg(0, (uint32_t)b->alias);
    return ACNL_CONTINUE;
}

int hook_rect_size_pre(void *) {
    Building *b = new_id_building(acnl_reg(0));
    if (!b) return ACNL_CONTINUE;
    if (b->set_rect) {
        uint32_t w = (uint32_t)(b->rect[2] - b->rect[0] + 1) & 0xFF, h = (uint32_t)(b->rect[3] - b->rect[1] + 1) & 0xFF;
        acnl_set_reg(0, w | (h << 8));
        return ACNL_SKIP;
    }
    if (b->alias >= 0) acnl_set_reg(0, (uint32_t)b->alias);
    return ACNL_CONTINUE;
}

/* ---- town map ---- */
Saved s_map;
Building *g_map_b = nullptr;     /* the added building the map is drawing an icon for */
int hook_map_icon_for_pre(void *) {
    uint32_t id = acnl_reg(1);
    push(s_map, (uint32_t)(uintptr_t)g_map_b);
    g_map_b = new_id_building(id);
    if (g_map_b) acnl_set_reg(1, (uint32_t)g_map_b->alias);       /* drawn like the alias building (police station...) */
    return ACNL_CONTINUE;
}
void hook_map_icon_for_post(void *) { g_map_b = (Building *)(uintptr_t)pop(s_map); }
int hook_map_icon_kind_pre(void *) {
    if (g_map_b && g_map_b->icon_frame >= 0) {
        uint32_t type = acnl_rd8(acnl_reg(0) + 0x26a);              /* widget type: where its kind numbering starts */
        if (type < 3) acnl_set_reg(1, (uint32_t)g_map_b->icon_frame + acnl_rd8(MAP_KIND_BASE + type));
    }
    return ACNL_CONTINUE;
}

/* scene changes: leaving a room by a link tile goes to another room of the same building instead of outdoors.
   BUILDER_TRACE=1 logs every scene change (arguments: scene, position, angles, stack kind). */
const uint32_t FN_GOTO_SCENE = 0x5b4bd0;   /* bool goto(obj, u8 scene, float pos[3], u16 angle[3], f32, stack: kind, ?) */
const uint32_t SCENE_STATE = 0x956320;     /* +2 current scene, +3 next */
int hook_goto_pre(void *) {
    uint32_t cur = acnl_rd8(SCENE_STATE + 2), want = acnl_reg(1) & 0xFF, sp = acnl_reg(13);
    if (g_debug_enter && g_nb && g_b[0].scene >= 0 && cur == 0 && want != 0 && want != (uint32_t)g_b[0].scene) {
        /* BUILDER_DEBUG_ENTER=1: the first door the player uses leads into the first building (for testing) */
        float np[3] = {256.0f, 32.0f, 464.0f};
        uint16_t na[3] = {0, 32768, 0};
        acnl_write(acnl_reg(2), np, 12);
        acnl_write(acnl_reg(3), na, 6);
        acnl_set_reg(1, (uint32_t)g_b[0].scene);
        g_cur = 0;
        for (int k = 0; k < g_b[0].npages; k++) acnl_set_romfs_variant(g_b[0].pages[k].variant, k == 0);
        if (g_b[0].variant[0]) acnl_set_romfs_variant(g_b[0].variant, 1);
        g_page = 0;
        want = acnl_reg(1) & 0xFF;
    }
    if (g_cur >= 0 && g_page < g_b[g_cur].npages && cur == (uint32_t)g_b[g_cur].scene && want == 0 && g_player) {
        Building &b = g_b[g_cur];
        Page &pg = b.pages[g_page];
        float pos[3];
        if (acnl_read(g_player + 0x14, pos, 12) == 0) {
            int tx = (int)(pos[0] / TILE), ty = (int)(pos[2] / TILE);
            for (int l = 0; l < pg.nlinks; l++) {
                const Link &k = pg.links[l];
                if (k.x != tx || k.y != ty || k.to < 0 || k.to >= b.npages) continue;
                float np[3] = {k.ax * TILE + TILE / 2.0f, 32.0f, k.ay * TILE + TILE / 2.0f};
                uint16_t na[3] = {0, (uint16_t)k.yaw, 0};
                acnl_write(acnl_reg(2), np, 12);
                acnl_write(acnl_reg(3), na, 6);
                acnl_wr32(sp, SCENE_ARRIVE_INDOOR);
                acnl_wr32(sp + 4, 0);
                acnl_set_reg(1, (uint32_t)b.scene);
                select_page(b, k.to);
                acnl_log("builder: %s: room %d -> room %d (tile %d,%d)", b.id, (int)(&pg - b.pages), k.to, tx, ty);
                break;
            }
        }
    }
    if (g_trace) {
        float pos[3] = {0, 0, 0};
        uint16_t ang[3] = {0, 0, 0};
        acnl_read(acnl_reg(2), pos, 12);
        acnl_read(acnl_reg(3), ang, 6);
        acnl_log("goto: scene %u -> %u pos %.2f %.2f %.2f ang %u %u %u stack %x %x", cur, acnl_reg(1) & 0xFF, pos[0], pos[1], pos[2],
                 ang[0], ang[1], ang[2], acnl_rd32(sp), acnl_rd32(sp + 4));
    }
    return ACNL_CONTINUE;
}

Saved s_building;
int hook_building_scene_pre(void *) {
    uint32_t id = acnl_reg(0);
    push(s_building, id);
    Building *b = new_id_building(id);
    if (b && b->alias >= 0) acnl_set_reg(0, (uint32_t)b->alias);
    return ACNL_CONTINUE;
}
void hook_building_scene_post(void *) {
    uint32_t bld = pop(s_building);
    g_cur = find_building(bld);
    if (Building *nb = new_id_building(bld))
        if (nb->scene >= 0) acnl_set_reg(0, (uint32_t)nb->scene);
    for (int i = 0; i < g_nb; i++) {
        if (g_b[i].variant[0]) acnl_set_romfs_variant(g_b[i].variant, i == g_cur);
        for (int k = 0; k < g_b[i].npages; k++) acnl_set_romfs_variant(g_b[i].pages[k].variant, i == g_cur && k == 0);
    }
    g_page = 0;
    uint32_t scene = acnl_reg(0);
    if (scene >= 0xA5) return;
    /* the scene's exit leads to the building listed for it: the one whose door the player used, else the original */
    if (g_cur >= 0) acnl_wr8(SCENE_BLD_TABLE + scene, (uint8_t)g_b[g_cur].slot);
    else if (g_scene_owner[scene] != 0xFC) acnl_wr8(SCENE_BLD_TABLE + scene, g_scene_owner[scene]);
}

int hook_place_town_buildings_pre(void *) {
    ensure_buildings();
    return ACNL_CONTINUE;
}

bool load_jmp(Building &b, Page &pg) {
    if (!pg.jmp_file[0]) return false;
    pg.jmp = acnl_alloc(JMP_SIZE, 4);
    static uint8_t buf[JMP_SIZE];
    if (pg.jmp && acnl_read_file(pg.jmp_file, buf, JMP_SIZE) == (int)JMP_SIZE && acnl_write(pg.jmp, buf, JMP_SIZE) == 0) return true;
    pg.jmp = 0;
    acnl_log("builder: %s missing: %s keeps the original walls", pg.jmp_file, b.id);
    return false;
}

/* switch on the room (page) of a building: its room model variant */
void select_page(Building &b, int page) {
    g_page = page;
    for (int k = 0; k < b.npages; k++) acnl_set_romfs_variant(b.pages[k].variant, k == page);
}


}  // namespace

extern "C" int acnl_mod_init(void) {
    for (int i = 0; i < 0xA5; i++) g_scene_owner[i] = acnl_rd8(SCENE_BLD_TABLE + i);     /* who each interior leads out to */
    load_config();
    bool any_jmp = false, any_hide = false, any_new = false, any_links = false;
    for (int i = 0; i < g_nb; i++) {
        Building &b = g_b[i];
        bool fresh = b.alias >= 0;                 /* virtual: answered by hooks */
        if (b.slot < 0x4C || b.slot > 0xFB || (fresh && b.alias > 0xFB)) {
            acnl_log("builder: %s: slot %#x / alias %#x is not a building ID", b.id, b.slot, b.alias);
            return -1;
        }
        for (int j = 0; j < i; j++) if (g_b[j].slot == b.slot) { acnl_log("builder: slot %#x used twice", b.slot); return -1; }
        /* name: points the model/texture/data lookups at our RomFS files */
        uint32_t s = acnl_alloc(strlen(b.model) + 1, 4);
        acnl_write(s, b.model, strlen(b.model) + 1);
        if (b.set_rect && fresh) {
            b.rect_ptr = acnl_alloc(4, 4);
            for (int k = 0; k < 4; k++) acnl_wr8(b.rect_ptr + k, (uint8_t)(int8_t)b.rect[k]);
        }
        if (fresh) { b.name_ptr = s; any_new = true; }
        else {
            acnl_wr32(BLD_NAME_TABLE + b.slot * 4, s);
            if (b.scene >= 0) acnl_wr8(BLD_SCENE_TABLE + b.slot, (uint8_t)b.scene);
            if (b.set_rect)
                for (int k = 0; k < 4; k++) acnl_wr8(BLD_RECT_TABLE + b.slot * 4 + k, (uint8_t)(int8_t)b.rect[k]);
        }
        for (int k = 0; k < b.npages; k++) if (load_jmp(b, b.pages[k])) any_jmp = true;
        for (int k = 0; k < b.npages; k++) for (int l = 0; l < b.pages[k].nlinks; l++) any_links = true;
        if (b.hide_furniture) any_hide = true;
        acnl_log("builder: building %s: ID %#x, model %s, interior scene %d", b.id, b.slot, b.model, b.scene);
    }
    if (g_nb) {
        if (acnl_hook(FN_PLACE_TOWN_BUILDINGS, hook_place_town_buildings_pre, nullptr, nullptr) != 0) return -1;
        if (acnl_hook(FN_BUILDING_SCENE, hook_building_scene_pre, hook_building_scene_post, nullptr) != 0) return -1;
    }
    if (any_new) {
        for (const IdFn &f : ID_FNS) {
            int rc = 0;
            if (f.addr == FN_BLD_RECT_SIZE) rc = acnl_hook(f.addr, hook_rect_size_pre, nullptr, nullptr);
            else rc = acnl_hook(f.addr, hook_alias_pre, nullptr, (void *)(intptr_t)f.reg);
            if (rc != 0) { acnl_log("builder: cannot hook %#x", f.addr); return -1; }
        }
        if (acnl_hook(FN_MAP_ICON_FOR, hook_map_icon_for_pre, hook_map_icon_for_post, nullptr) != 0) return -1;
        if (acnl_hook(FN_MAP_ICON_KIND, hook_map_icon_kind_pre, nullptr, nullptr) != 0) return -1;
        if (acnl_hook(FN_BLD_NAME, hook_name_pre, nullptr, nullptr) != 0) return -1;
        if (acnl_hook(FN_BLD_RECT_PTR, hook_rect_ptr_pre, nullptr, nullptr) != 0) return -1;
    }
    char tr[8];
    g_trace = acnl_getenv("BUILDER_TRACE", tr, sizeof tr) >= 0;
    g_debug_enter = acnl_getenv("BUILDER_DEBUG_ENTER", tr, sizeof tr) >= 0;
    if ((any_links || g_trace || g_debug_enter) && acnl_hook(FN_GOTO_SCENE, hook_goto_pre, nullptr, nullptr) != 0) return -1;
    if (any_links && acnl_hook(FN_ACTOR_CREATE, hook_actor_track_pre, hook_actor_track_post, nullptr) != 0) return -1;
    if (any_hide && acnl_hook(FN_ACTOR_CREATE, hook_actor_create_pre, nullptr, nullptr) != 0) return -1;
    if (any_jmp && acnl_hook(FN_JMP_BLOCK, hook_jmp_block_pre, hook_jmp_block_post, nullptr) != 0) return -1;
    return 0;
}
