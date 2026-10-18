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
#include "script_vm.h"

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
struct Link { int x, y, to, ax, ay, yaw, oyaw; };     /* oyaw: the way the player walks out through it */
struct Page {
    char variant[40];             /* RomFS variant with this room's model */
    char jmp_file[48];            /* its collision grid file */
    uint32_t jmp;                 /* guest copy of the grid */
    Link links[MAX_LINKS];
    int nlinks;
    char scene_id[32];            /* the id of the interior scene of this room (scripts name rooms by it) */
    bool has_entry;               /* where the player appears when coming in from outside (a door not on the south edge) */
    float entry_x, entry_z;
    int entry_yaw;
};
struct Building {
    char id[32];
    char model[16];               /* name the game looks the model up by */
    char variant[32];             /* RomFS variant with the building's text, on inside any of its rooms */
    char quiet[40];               /* RomFS variant with the host's arrival conversation that does not greet: on after a room change */
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
    else if (!strcmp(key, "quiet")) copy_str(b.quiet, sizeof b.quiet, val);
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
    else if (!strcmp(key, "id")) copy_str(p.scene_id, sizeof p.scene_id, val);
    else if (!strcmp(key, "jmp")) copy_str(p.jmp_file, sizeof p.jmp_file, val);
    else if (!strcmp(key, "entry")) {                             /* entry = x, z, yaw */
        int v[3] = {0, 0, 0};
        const char *q = val;
        int k = 0;
        for (; k < 3; k++) {
            char *e;
            v[k] = (int)acnl_strtol(q, &e, 0);
            if (e == q) break;
            q = e;
            while (is_space(*q)) q++;
            if (*q == ',') q++;
        }
        if (k == 3) { p.has_entry = true; p.entry_x = (float)v[0]; p.entry_z = (float)v[1]; p.entry_yaw = v[2]; }
    }
    else if (!strcmp(key, "link") && p.nlinks < MAX_LINKS) {      /* link = x, y, to page, arrival x, y, yaw[, walking-out yaw] */
        int v[7] = {0, 0, 0, 0, 0, 0, -1};
        const char *q = val;
        for (int k = 0; k < 7; k++) {
            char *e;
            v[k] = (int)acnl_strtol(q, &e, 0);
            if (e == q) break;
            q = e;
            while (is_space(*q)) q++;
            if (*q == ',') q++;
        }
        p.links[p.nlinks++] = {v[0], v[1], v[2], v[3], v[4], v[5], v[6] >= 0 ? v[6] : 32768};
    }
}

}  // namespace
#include "vehicles.h"
namespace {

/* outfits of villagers: [outfit] villager, id, model, variant (the variant holds the repainted model) */
struct Outfit { char villager[32], id[32], variant[64]; };
const int MAX_OUTFITS = 64;
Outfit g_outfit[MAX_OUTFITS];
int g_noutfits = 0;
void set_outfit_key(Outfit &o, const char *key, const char *val) {
    if (!strcmp(key, "villager")) copy_str(o.villager, sizeof o.villager, val);
    else if (!strcmp(key, "id")) copy_str(o.id, sizeof o.id, val);
    else if (!strcmp(key, "variant")) copy_str(o.variant, sizeof o.variant, val);
}

/* [characters]: characters added by the mod. spawn = <profile>, <model code>: the profile is created with the game's own model-code
   argument (as the game does when Isabelle comes out to meet the player: AcNpcSpSecretaryOut with "sza"), so it loads its own model.
   talk = <profile>, <flow>: talking to that character runs this conversation (a flow of the game, rewritten by the mod) */
struct CharDef { uint32_t profile; char code[4]; char flow[48]; };
const int MAX_CHARS = 16;
CharDef g_char[MAX_CHARS];
int g_nchars = 0;
CharDef *char_def(uint32_t profile, bool make) {
    for (int i = 0; i < g_nchars; i++) if (g_char[i].profile == profile) return &g_char[i];
    if (!make || g_nchars >= MAX_CHARS) return nullptr;
    memset(&g_char[g_nchars], 0, sizeof g_char[0]);
    g_char[g_nchars].profile = profile;
    return &g_char[g_nchars++];
}
void set_char_key(const char *key, const char *val) {
    char *e;
    uint32_t prof = (uint32_t)acnl_strtol(val, &e, 0);
    while (*e == ',' || is_space(*e)) e++;
    CharDef *c = char_def(prof, true);
    if (!c) return;
    if (!strcmp(key, "spawn")) { memset(c->code, 0, 4); for (int i = 0; i < 3 && e[i]; i++) c->code[i] = e[i]; }
    else if (!strcmp(key, "talk")) copy_str(c->flow, sizeof c->flow, e);
}

/* [probe]: log what the game does, to find what to hook (see docs/HOOKS.md). hook = <address>, <label>; actors = 1 */
struct Probe { uint32_t addr; char label[44]; int calls; };
const int MAX_PROBES = 400;
Probe g_probe[MAX_PROBES];
int g_nprobe = 0;
bool g_probe_actors = false, g_probe_spawns = false;
void set_probe_key(const char *key, const char *val) {
    if (!strcmp(key, "actors")) g_probe_actors = acnl_strtol(val, nullptr, 0) != 0;
    else if (!strcmp(key, "spawns")) g_probe_spawns = acnl_strtol(val, nullptr, 0) != 0;
    else if (!strcmp(key, "hook") && g_nprobe < MAX_PROBES) {
        char *e;
        Probe &p = g_probe[g_nprobe];
        p.addr = (uint32_t)acnl_strtol(val, &e, 0);
        while (*e == ',' || is_space(*e)) e++;
        copy_str(p.label, sizeof p.label, e);
        g_nprobe++;
    }
}

void set_trace_key(const char *key, const char *val);

/* acnlb.cfg: "[building]" starts a section, "key = value" lines, '#' comments */
void load_config() {
    static char text[32768];
    int n = acnl_read_file("acnlb.cfg", text, sizeof text - 1);
    if (n <= 0) return;
    if (n > (int)sizeof text - 1) n = sizeof text - 1;
    text[n] = 0;
    Building *cur = nullptr;
    Page *page = nullptr;
    Outfit *outfit = nullptr;
    bool inprobe = false, inchars = false, intrace = false;
    veh::Config *vcfg = nullptr;
    for (char *line = text; *line;) {
        char *end = line;
        while (*end && *end != '\n') end++;
        char *next = *end ? end + 1 : end;
        *end = 0;
        for (char *h = line; *h; h++) if (*h == '#') { *h = 0; break; }
        while (is_space(*line)) line++;
        if (*line == '[') {
            page = nullptr;
            outfit = nullptr;
            vcfg = nullptr;
            inprobe = inchars = intrace = false;
            if (!memcmp(line, "[probe]", 7)) { cur = nullptr; inprobe = true; }
            else if (!memcmp(line, "[characters]", 12)) { cur = nullptr; inchars = true; }
            else if (!memcmp(line, "[trace]", 7)) { cur = nullptr; intrace = true; }
            else if (!memcmp(line, "[outfit]", 8)) { cur = nullptr; if (g_noutfits < MAX_OUTFITS) outfit = &g_outfit[g_noutfits++]; }
            else if (!memcmp(line, "[vehicle]", 9)) {
                cur = nullptr;
                if (veh::g_nv < veh::MAX_VEHICLES) { vcfg = &veh::g_v[veh::g_nv++].c; veh::init_config(*vcfg); }
            }
            else if (!memcmp(line, "[building]", 10)) { cur = g_nb < MAX_MODS ? &g_b[g_nb++] : nullptr; if (cur) init_building(*cur); }
            else if (!memcmp(line, "[page]", 6) && cur && cur->npages < MAX_PAGES) page = &cur->pages[cur->npages++];
            else cur = nullptr;                                    /* a section this plugin does not read (e.g. [outfit]) */
        } else if (cur || outfit || inprobe || inchars || intrace || vcfg) {
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
                if (vcfg) veh::set_key(*vcfg, line, val);
                else if (intrace) set_trace_key(line, val);
                else if (inchars) set_char_key(line, val);
                else if (inprobe) set_probe_key(line, val); else if (outfit) set_outfit_key(*outfit, line, val); else if (page) set_page_key(*page, line, val); else set_key(*cur, line, val);
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
/* where the game thinks the player came from: a room reached by a link must look as if the player came in through the building's
   door from the town, or the place is not set up (seen in game: the player could not leave the room, and nobody would talk; the
   leaving test 0x5c4d4c failed). These are the values that differed between the two rooms, kept when the player walks in from the
   town and written again whenever a room is reached through a link. */
struct CameFrom { uint32_t addr; uint32_t size; };
const CameFrom CAME_FROM[] = {{0x956321, 1}, {0x94d4b4, 1}, {0x94d4a5, 1}, {0x94d43c, 4}, {0x94d440, 4}, {0x94d484, 4}};
const int N_CAME_FROM = sizeof CAME_FROM / sizeof CAME_FROM[0];
uint32_t g_came_from[N_CAME_FROM];
bool g_have_came_from = false, g_by_link = false;
int g_came_from_frames = 0;
uint32_t rd_n(uint32_t a, uint32_t n) { return n == 1 ? acnl_rd8(a) : acnl_rd32(a); }
void wr_n(uint32_t a, uint32_t n, uint32_t v) { if (n == 1) acnl_wr8(a, (uint8_t)v); else acnl_wr32(a, v); }
void came_from_keep() { for (int i = 0; i < N_CAME_FROM; i++) g_came_from[i] = rd_n(CAME_FROM[i].addr, CAME_FROM[i].size); g_have_came_from = true; }
void came_from_put() {
    if (!g_have_came_from) return;
    for (int i = 0; i < N_CAME_FROM; i++) wr_n(CAME_FROM[i].addr, CAME_FROM[i].size, g_came_from[i]);
}
Saved s_jmp;
int g_jmp_logged_page = -1;
int hook_jmp_block_pre(void *) { push(s_jmp, acnl_reg(1)); return ACNL_CONTINUE; }
void hook_jmp_block_post(void *) {
    uint32_t index = pop(s_jmp);
    if (g_cur >= 0 && g_page < g_b[g_cur].npages && g_b[g_cur].pages[g_page].jmp && index == JMP_INDOOR_BASE + (uint32_t)g_b[g_cur].room && acnl_reg(0)) {
        if (g_jmp_logged_page != g_page) {
            acnl_log("builder: room %d: the game asked for its collision grid (%08x), given the room's own (%08x)", g_page, (unsigned)acnl_reg(0), (unsigned)g_b[g_cur].pages[g_page].jmp);
            g_jmp_logged_page = g_page;
            if (g_by_link) acnl_log("builder: room %d reached by a link", g_page);
        }
        acnl_set_reg(0, g_b[g_cur].pages[g_page].jmp);
    }
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

/* ---- probes */
int hook_probe(void *user) {
    Probe &p = g_probe[(int)(intptr_t)user];
    if (p.calls++ < 30)
        acnl_log("probe: %s r0=%08x r1=%08x r2=%08x r3=%08x from=%08x", p.label, (unsigned)acnl_reg(0), (unsigned)acnl_reg(1), (unsigned)acnl_reg(2), (unsigned)acnl_reg(3), (unsigned)acnl_return_address());
    return ACNL_CONTINUE;
}
/* an actor's memory after the game has finished setting it up: comparing a genuine character with a spawned copy shows which
   fields hold its identity (model, NPC id) and its place */
void probe_dump(const char *what, uint32_t obj, uint32_t prof) {
    if (obj < 0x100000) return;
    uint32_t w[128];
    if (acnl_read(obj, w, sizeof w) != 0) return;
    for (int k = 0; k < 128; k += 16)
        acnl_log("probe: %s %u +%03x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x", what, (unsigned)prof, k * 4,
                 (unsigned)w[k], (unsigned)w[k+1], (unsigned)w[k+2], (unsigned)w[k+3], (unsigned)w[k+4], (unsigned)w[k+5], (unsigned)w[k+6], (unsigned)w[k+7],
                 (unsigned)w[k+8], (unsigned)w[k+9], (unsigned)w[k+10], (unsigned)w[k+11], (unsigned)w[k+12], (unsigned)w[k+13], (unsigned)w[k+14], (unsigned)w[k+15]);
}
Saved s_probe_spawn;
void hook_probe_spawn_post(void *) {
    uint32_t prof = pop(s_probe_spawn), obj = acnl_reg(0);
    if (prof == 454 || prof == 492 || prof == 419 || prof == 500) probe_dump("spawned", obj, prof);
}
/* the spawn function's arguments: the struct r1 points at (profile first) and the stack arguments, to learn what each field means */
int g_probe_spawn_n = 0;
int hook_probe_spawn_pre(void *) {
    uint32_t desc = acnl_reg(1), sp = acnl_reg(13);
    uint32_t prof0 = desc >= 0x100000 ? acnl_rd16(desc) : 0;
    push(s_probe_spawn, prof0);
    if (prof0 < 380 || prof0 > 560) return ACNL_CONTINUE;                 /* the characters (AcNpc*) only */
    if (acnl_reg(2) >= 0x100000 && (prof0 == 454 || prof0 == 492)) probe_dump("spawn-r2", acnl_reg(2), prof0);
    if (g_probe_spawn_n++ >= 300) return ACNL_CONTINUE;
    uint32_t w[64] = {0}, s[8] = {0};
    if (desc >= 0x100000) acnl_read(desc, w, sizeof w);
    acnl_read(sp, s, sizeof s);
    acnl_log("probe: spawn profile=%u r0=%08x r1=%08x r2=%08x r3=%08x scene=%u/%u", (unsigned)(w[0] & 0xFFFF), (unsigned)acnl_reg(0), (unsigned)desc, (unsigned)acnl_reg(2), (unsigned)acnl_reg(3),
             (unsigned)acnl_rd8(0x956320 + 2), (unsigned)acnl_rd8(0x956320 + 3));
    for (int k = 0; k < 64; k += 16)
        acnl_log("probe: spawn-desc+%02x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x", k * 4, (unsigned)w[k], (unsigned)w[k+1], (unsigned)w[k+2], (unsigned)w[k+3], (unsigned)w[k+4], (unsigned)w[k+5], (unsigned)w[k+6], (unsigned)w[k+7], (unsigned)w[k+8], (unsigned)w[k+9], (unsigned)w[k+10], (unsigned)w[k+11], (unsigned)w[k+12], (unsigned)w[k+13], (unsigned)w[k+14], (unsigned)w[k+15]);
    acnl_log("probe: spawn-stack %08x %08x %08x %08x %08x %08x %08x %08x", (unsigned)s[0], (unsigned)s[1], (unsigned)s[2], (unsigned)s[3], (unsigned)s[4], (unsigned)s[5], (unsigned)s[6], (unsigned)s[7]);
    return ACNL_CONTINUE;
}
Saved s_probe_actor;
int g_probe_actor_n = 0;
uint8_t g_probe_seen[1024];
int hook_probe_actor_pre(void *) { push(s_probe_actor, acnl_reg(0)); return ACNL_CONTINUE; }
/* the class name of a C++ object: vtable[-1] is its typeinfo, whose second word points at the mangled name */
void class_name_of(uint32_t obj, char *out, int cap) {
    out[0] = 0;
    uint32_t vt = obj >= 0x100000 ? acnl_rd32(obj) : 0;
    if (vt < 0x100000) return;
    uint32_t ti = acnl_rd32(vt - 4);
    if (ti < 0x100000) return;
    uint32_t np = acnl_rd32(ti + 4);
    if (np < 0x100000) return;
    int i = 0;
    for (; i < cap - 1; i++) { uint8_t c = acnl_rd8(np + (uint32_t)i); if (c < 32 || c > 126) break; out[i] = (char)c; }
    out[i] = 0;
}
void hook_probe_actor_post(void *) {
    uint32_t arg = pop(s_probe_actor), obj = acnl_reg(0), prof = arg & 0xFFFF;
    if (g_probe_actor_n >= 6000) return;
    if (prof < 1024 && g_probe_seen[prof] >= 3) return;          /* the first three of each profile are enough */
    if (prof < 1024) g_probe_seen[prof]++;
    g_probe_actor_n++;
    char nm[64];
    class_name_of(obj, nm, sizeof nm);
    uint32_t vt = obj >= 0x100000 ? acnl_rd32(obj) : 0;
    acnl_log("probe: actor profile=%u arg=%08x obj=%08x vtable=%08x scene=%u/%u class=%s", (unsigned)prof, (unsigned)arg, (unsigned)obj, (unsigned)vt,
             (unsigned)acnl_rd8(0x956320 + 2), (unsigned)acnl_rd8(0x956320 + 3), nm);
    if (obj >= 0x100000) {
        uint32_t w[16];
        if (acnl_read(obj, w, sizeof w) == 0)
            acnl_log("probe: actor-words %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x", (unsigned)w[0], (unsigned)w[1], (unsigned)w[2], (unsigned)w[3], (unsigned)w[4], (unsigned)w[5], (unsigned)w[6], (unsigned)w[7], (unsigned)w[8], (unsigned)w[9], (unsigned)w[10], (unsigned)w[11], (unsigned)w[12], (unsigned)w[13], (unsigned)w[14], (unsigned)w[15]);
    }
}

/* ---- tracing the player's way out: [trace] hook = <address>, <label> lines (written by the builder while this is being found out)
   log each call (arguments, caller, result) while the player stands on a link tile, a few per function and per room */
struct Trace { uint32_t addr; char label[24]; int calls; };
const int MAX_TRACES = 160;
Trace g_trace_fn[MAX_TRACES];
int g_ntrace = 0;
bool g_on_link = false;
int g_last_link = -1, g_last_link_page = -1;   /* the link tile the player last stepped on: the door walk takes them off it before the scene changes */
Saved s_trace[MAX_TRACES];
void set_trace_key(const char *key, const char *val) {
    if (strcmp(key, "hook") || g_ntrace >= MAX_TRACES) return;
    char *e;
    Trace &t = g_trace_fn[g_ntrace];
    t.addr = (uint32_t)acnl_strtol(val, &e, 0);
    while (*e == ',' || is_space(*e)) e++;
    copy_str(t.label, sizeof t.label, e);
    g_ntrace++;
}
int hook_trace_pre(void *user) {
    int i = (int)(intptr_t)user;
    Trace &t = g_trace_fn[i];
    /* labels starting with '@' are traced anywhere in the building (talking), the others while on a link tile (leaving) */
    /* '!' anywhere at any time, '@' inside a building of the mod, the others while on a link tile */
    bool on = (t.label[0] == '!' ? true : t.label[0] == '@' ? g_cur >= 0 : g_on_link) && t.calls < 12;
    push(s_trace[i], on ? 1 : 0);
    if (on) {
        t.calls++;
        acnl_log("trace: %s(%08x, %08x, %08x, %08x) from %08x", t.label, (unsigned)acnl_reg(0), (unsigned)acnl_reg(1), (unsigned)acnl_reg(2),
                 (unsigned)acnl_reg(3), (unsigned)acnl_return_address());
    }
    return ACNL_CONTINUE;
}
void hook_trace_post(void *user) {
    int i = (int)(intptr_t)user;
    if (pop(s_trace[i])) acnl_log("trace: %s -> %08x", g_trace_fn[i].label, (unsigned)acnl_reg(0));
}
void trace_reset() { for (int i = 0; i < g_ntrace; i++) g_trace_fn[i].calls = 0; }

/* the game's globals (.data and .bss) when the player first stands on a link tile of room 0, compared with the first time on one of
   another room: what differs is what the game knows differently about the player there (only while [trace] is on) */
const uint32_t GLOB_START = 0x944000, GLOB_SIZE = 0x4C000;
uint32_t g_glob = 0;           /* the copy, in guest memory (the plugin's own is too small) */
int g_glob_state = 0;          /* 0 nothing yet, 1 room 0 kept, 2 compared */
void glob_snapshot(int page) {
    if (!g_ntrace || g_glob_state == 2) return;
    if (g_glob_state == 0) {
        if (page != 0) return;
        static uint8_t chunk[0x1000];
        if (!g_glob) g_glob = acnl_alloc(GLOB_SIZE, 4);
        if (!g_glob) { g_glob_state = 2; acnl_log("trace: no memory for the globals"); return; }
        for (uint32_t o = 0; o < GLOB_SIZE; o += 0x1000) if (acnl_read(GLOB_START + o, chunk, 0x1000) == 0) acnl_write(g_glob + o, chunk, 0x1000);
        g_glob_state = 1;
        acnl_log("trace: globals kept (room 0, on a link tile)");
        return;
    }
    if (page == 0) return;
    g_glob_state = 2;
    static uint8_t now[0x1000], was[0x1000];
    int shown = 0;
    for (uint32_t o = 0; o < GLOB_SIZE && shown < 400; o += 0x1000) {
        if (acnl_read(GLOB_START + o, now, 0x1000) != 0 || acnl_read(g_glob + o, was, 0x1000) != 0) continue;
        for (uint32_t k = 0; k < 0x1000 && shown < 400; k += 4) {
            uint32_t a, b;
            memcpy(&a, was + k, 4);
            memcpy(&b, now + k, 4);
            if (a != b) { acnl_log("trace: global %08x room0 %08x room%d %08x", (unsigned)(GLOB_START + o + k), (unsigned)a, page, (unsigned)b); shown++; }
        }
    }
    acnl_log("trace: %d global words differ (shown up to 400)", shown);
}

/* ---- scripts (acnlb.script: compiled by acnlb/script/compiler.py, run by script_vm.h) ---- */
uint8_t g_script_blob[sv::MAX_CODE_BYTES + 2048];
sv::Program g_prog;
bool g_scripts = false;
int32_t g_vars[64];
uint32_t g_rng = 0x2545F491u;
struct AddReq { uint32_t profile; int tx, tz; };
const int MAX_ADDS = 4;
AddReq g_adds[MAX_ADDS];
int g_nadds = 0;
struct ScriptState { bool hide, skip, become, place, placeact; uint32_t profile; float px, pz; int yaw; int atx, atz; } g_sc;
ScriptState g_entry_override;     /* place_player() from an @on_enter handler, used when the game puts the player in the room */
bool g_has_override = false;

char g_cbuf[4][64];
int g_cb = 0;
const char *cstr(int idx) {                  /* a string of the program as a C string */
    char *o = g_cbuf[g_cb++ & 3];
    int n = 0;
    if (idx >= 0 && idx < g_prog.nstr) { n = g_prog.slen[idx]; if (n > 63) n = 63; memcpy(o, g_prog.str[idx], (size_t)n); }
    o[n] = 0;
    return o;
}
uint32_t script_rand() { g_rng ^= g_rng << 13; g_rng ^= g_rng >> 17; g_rng ^= g_rng << 5; return g_rng; }

/* the game's clock: the 3DS shared page holds ms since 1900 (local time), double buffered */
void game_clock(int32_t *y, int32_t *mo, int32_t *d, int32_t *wd, int32_t *h, int32_t *mi) {
    uint32_t sel = acnl_rd32(0x1FF81000) & 1, base = 0x1FF81020 + sel * 0x20;
    uint32_t lo = acnl_rd32(base), hi = acnl_rd32(base + 4);
    sv::civil(((uint64_t)hi << 32) | lo, y, mo, d, wd, h, mi);
}

bool script_call(void *, int id, const int32_t *a, int n, int32_t *ret, bool *has) {
    (void)n;
    *has = false;
    int32_t y, mo, d, wd, h, mi;
    switch (id) {
    case 0: case 1: case 2: case 3: case 4: case 5:
        game_clock(&y, &mo, &d, &wd, &h, &mi);
        *ret = id == 0 ? h : id == 1 ? mi : id == 2 ? wd : id == 3 ? d : id == 4 ? mo : y; *has = true; return true;
    case 6: *ret = g_cur >= 0 && !strcmp(g_b[g_cur].id, cstr(a[0])); *has = true; return true;
    case 7: *ret = g_cur >= 0 && !strcmp(g_b[g_cur].id, cstr(a[0])) && g_page < g_b[g_cur].npages && !strcmp(g_b[g_cur].pages[g_page].scene_id, cstr(a[1])); *has = true; return true;
    case 8: *ret = (int32_t)(script_rand() % 100u) < a[0]; *has = true; return true;
    case 9: *ret = a[0] > 0 ? (int32_t)(script_rand() % (uint32_t)a[0]) : 0; *has = true; return true;
    case 10: if (a[0] < 0 || a[0] >= 64) return false; *ret = g_vars[a[0]]; *has = true; return true;
    case 11: if (a[0] < 0 || a[0] >= 64) return false; g_vars[a[0]] = a[1]; return true;
    case 12: acnl_log("script: %s %d", cstr(a[0]), (int)a[1]); return true;
    case 13: case 14:
        for (int i = 0; i < g_noutfits; i++)
            if (!strcmp(g_outfit[i].villager, cstr(a[0]))) acnl_set_romfs_variant(g_outfit[i].variant, id == 13 && !strcmp(g_outfit[i].id, cstr(a[1])));
        return true;
    case 15: acnl_set_romfs_variant(cstr(a[0]), 1); return true;
    case 16: acnl_set_romfs_variant(cstr(a[0]), 0); return true;
    case 17: g_sc.hide = true; return true;
    case 18: g_sc.become = true; g_sc.profile = (uint32_t)a[0]; return true;
    case 19: g_sc.place = true; g_sc.px = a[0] * TILE + TILE / 2.0f; g_sc.pz = a[1] * TILE + TILE / 2.0f; g_sc.yaw = a[2]; return true;
    case 20: *ret = acnl_rd8((uint32_t)a[0]); *has = true; return true;
    case 21: *ret = acnl_rd16((uint32_t)a[0]); *has = true; return true;
    case 22: *ret = (int32_t)acnl_rd32((uint32_t)a[0]); *has = true; return true;
    case 23: acnl_wr8((uint32_t)a[0], (uint8_t)a[1]); return true;
    case 24: acnl_wr16((uint32_t)a[0], (uint16_t)a[1]); return true;
    case 25: acnl_wr32((uint32_t)a[0], (uint32_t)a[1]); return true;
    case 26: *ret = (int32_t)acnl_reg((uint32_t)a[0] & 15); *has = true; return true;
    case 27: acnl_set_reg((uint32_t)a[0] & 15, (uint32_t)a[1]); return true;
    case 28: g_sc.skip = true; return true;
    case 32: if (g_nadds < MAX_ADDS) g_adds[g_nadds++] = {(uint32_t)a[0] & 0xFFFF, a[1], a[2]}; return true;
    case 29: g_sc.placeact = true; g_sc.atx = a[0]; g_sc.atz = a[1]; return true;
    }
    return false;
}

void script_run(const sv::Handler &h) {
    sv::Host host{nullptr, script_call};
    int rc = sv::run(h.code, h.len, h.nlocals, host);
    if (rc) acnl_log("script: a handler stopped with error %d (1 too long, 2 stack, 3 bad code, 4 division by zero, 5 failed built-in)", rc);
}

/* run every handler of a kind that matches. building/room: the place; num: actor profile */
void script_fire(int kind, const char *building, const char *room, uint32_t num, bool from_link = false) {
    if (!g_scripts) return;
    for (int i = 0; i < g_prog.nhandlers; i++) {
        const sv::Handler &h = g_prog.h[i];
        if (h.kind != kind) continue;
        if ((kind == sv::K_ACTOR || kind == sv::K_SPAWN) && !(num >= h.num && num <= (h.s2 != 0xFFFF ? (uint32_t)h.s2 : h.num))) continue;
        if (kind == sv::K_ENTER || kind == sv::K_LEAVE || kind == sv::K_ROOM) {
            if (!building || !sv::str_is(g_prog, h.s1, building)) continue;
            if (kind == sv::K_ROOM && !(room && sv::str_is(g_prog, h.s2, room))) continue;
            if (kind == sv::K_ENTER) {
                if (h.s2 != 0xFFFF && !(room && sv::str_is(g_prog, h.s2, room))) continue;
                if (h.s2 == 0xFFFF && from_link) continue;
            }
        }
        script_run(h);
    }
}

Saved s_script_pos;
int hook_script_actor_pre(void *) {
    if (!g_scripts) return ACNL_CONTINUE;
    uint32_t arg = acnl_reg(0);
    memset(&g_sc, 0, sizeof g_sc);
    script_fire(sv::K_ACTOR, nullptr, nullptr, arg & 0xFFFF);
    if (g_sc.become) acnl_set_reg(0, (arg & ~0xFFFFu) | (g_sc.profile & 0xFFFF));
    if (g_sc.hide) { acnl_set_reg(0, 0); return ACNL_SKIP; }
    push(s_script_pos, g_sc.placeact ? (uint32_t)(0x10000 | ((g_sc.atx & 0xFF) << 8) | (g_sc.atz & 0xFF)) : 0);     /* the post hook moves the new actor */
    return ACNL_CONTINUE;
}

void put_actor(uint32_t obj, float x, float z);
void pin_add(uint32_t obj, float x, float z);
/* the last actor place_actor() moved: a spawned character gets its place set after its creation, so the spawn's post hook moves it again */
struct Placed { uint32_t obj; float x, z; } g_placed;
void hook_script_actor_post(void *) {
    uint32_t v = pop(s_script_pos), obj = acnl_reg(0);
    if (!(v & 0x10000) || obj < 0x100000) return;
    float x = ((v >> 8) & 0xFF) * (float)TILE + TILE / 2.0f, z = (v & 0xFF) * (float)TILE + TILE / 2.0f;
    put_actor(obj, x, z);
    g_placed = {obj, x, z};
    pin_add(obj, x, z);
}

int hook_script_call_pre(void *user) {
    memset(&g_sc, 0, sizeof g_sc);
    script_run(g_prog.h[(int)(intptr_t)user]);
    return g_sc.skip ? ACNL_SKIP : ACNL_CONTINUE;
}

/* ---- spawning extra actors: the game spawns actors through one function (manager, &spawn-struct, r2, r3, stack...) whose struct starts
   with the u16 profile. For an @on_spawn trigger the plugin asks the runtime to run the same call again with a copy of the struct
   holding another profile (call_again), so the extra actor is created in the same phase as the game's own: its model loads with theirs. */
const uint32_t FN_SPAWN = 0x51ef80;
/* what a spawn call carries (read from a game log):
   r1  -> the profile's record in a table of 12-byte records starting with the profile number: entry(p) = PROFILE_TABLE + 12 * p
   r3  -> a parameter block + 0x20; the block holds the character's place: x at +0x0C, y at +0x10, z at +0x14 (and an angle at +0x18)
   the stack holds copies of the profile and of r3.  An extra spawn uses the new profile's own record, a block of its own with the
   tile in it, and the stack copies changed to match. */
const uint32_t PROFILE_TABLE = 0x952FB0;
uint32_t g_param[MAX_ADDS];                 /* guest copies of the parameter block */
uint32_t g_info[MAX_ADDS];                  /* guest info + place + angle of a character spawned by model code */
const uint32_t NEW_ACTOR_POS = 0x94cfd8;    /* float *pos, u16 *angle: where the next actor is created */
uint32_t g_create_pos_saved[2];
AddReq g_adds_run[MAX_ADDS];
/* where a character stands comes from the place's table of spots (Nook's Homes: 0x958ea8, one 0x20-byte record per counter
   character, x, y, z at +4), and r3 of the spawn points 0x14 bytes past the x of the spawning character's record. A character added
   next to it takes that same record (seen in game: the added Isabelle stood on Tom Nook's spot, whatever block or position was given
   to her). So for an added character the record itself holds the chosen tile while the player is in that room; the next scene change
   puts the game's values back. The character it is added with is not shown in that room, so nobody else stands there. */
struct SpotPatch { uint32_t addr; float orig[3]; };
SpotPatch g_spot[MAX_ADDS];
int g_nspot = 0;
void restore_spots() {
    for (int i = 0; i < g_nspot; i++) acnl_write(g_spot[i].addr, g_spot[i].orig, 12);
    g_nspot = 0;
}
void patch_spot(uint32_t r3, float x, float z) {
    uint32_t a = r3 - 0x14;
    if (r3 < 0x100014 || acnl_rd32(a + 4) != 0x42000000u) return;          /* y = 32.0: it is a spot record */
    for (int i = 0; i < g_nspot; i++) if (g_spot[i].addr == a) { acnl_write(a, &x, 4); acnl_write(a + 8, &z, 4); return; }
    if (g_nspot >= MAX_ADDS) return;
    g_spot[g_nspot].addr = a;
    acnl_read(a, g_spot[g_nspot].orig, 12);
    g_nspot++;
    acnl_write(a, &x, 4);
    acnl_write(a + 8, &z, 4);
}
int hook_spawn_pre(void *) {
    g_placed.obj = 0;
    if (!g_scripts) return ACNL_CONTINUE;
    uint32_t desc = acnl_reg(1), r3 = acnl_reg(3);
    if (desc < 0x100000 || r3 < 0x100020) return ACNL_CONTINUE;
    uint32_t prof = acnl_rd16(desc);
    memset(&g_sc, 0, sizeof g_sc);
    g_nadds = 0;
    script_fire(sv::K_SPAWN, nullptr, nullptr, prof);
    for (int k = 0; k < g_nadds; k++) {
        uint32_t rec = PROFILE_TABLE + 12 * g_adds[k].profile;
        CharDef *cd = char_def(g_adds[k].profile, false);
        if (cd && cd->code[0] && acnl_rd16(rec) == g_adds[k].profile) {
            /* the game's way: info = {u8 1, u8 0, .., u32 model code at +4}; the place and the angle of a new actor are read through the
               pointers at 0x94cfd8 / 0x94cfdc (set by the game's create-with-position function, 0x57aa34), put back once it exists */
            if (!g_info[k]) g_info[k] = acnl_alloc(0x40, 4);
            if (!g_info[k]) continue;
            uint8_t info[0x20] = {0};
            info[0] = 1;
            memcpy(info + 4, cd->code, 4);
            float pos[3] = {g_adds[k].tx * (float)TILE + TILE / 2.0f, 32.0f, g_adds[k].tz * (float)TILE + TILE / 2.0f};
            uint16_t ang[4] = {0, 0, 0, 0};                         /* facing south, towards the camera */
            acnl_write(g_info[k], info, sizeof info);
            acnl_write(g_info[k] + 0x20, pos, 12);
            acnl_write(g_info[k] + 0x30, ang, 8);
            g_create_pos_saved[0] = acnl_rd32(NEW_ACTOR_POS);
            g_create_pos_saved[1] = acnl_rd32(NEW_ACTOR_POS + 4);
            acnl_wr32(NEW_ACTOR_POS, g_info[k] + 0x20);
            acnl_wr32(NEW_ACTOR_POS + 4, g_info[k] + 0x30);
            g_adds_run[k] = g_adds[k];
            acnl_log("script: spawning actor %u (model %s) next to %u (tile %d,%d)", (unsigned)g_adds[k].profile, cd->code, (unsigned)prof, g_adds[k].tx, g_adds[k].tz);
            acnl_call_again_patched(100 + (uint32_t)k, acnl_reg(0), rec, acnl_reg(2), g_info[k], prof, g_adds[k].profile, r3, g_info[k]);
            continue;
        }
        if (acnl_rd16(rec) != g_adds[k].profile) { acnl_log("script: no profile record for actor %u: not spawned", (unsigned)g_adds[k].profile); continue; }
        if (!g_param[k]) g_param[k] = acnl_alloc(0x80, 4);
        uint8_t buf[0x40];
        if (!g_param[k] || acnl_read(r3 - 0x20, buf, sizeof buf) != 0) continue;
        float x = g_adds[k].tx * (float)TILE + TILE / 2.0f, z = g_adds[k].tz * (float)TILE + TILE / 2.0f;
        memcpy(buf + 0x0C, &x, 4);
        memcpy(buf + 0x14, &z, 4);
        acnl_write(g_param[k], buf, sizeof buf);
        g_adds_run[k] = g_adds[k];
        patch_spot(r3, x, z);
        acnl_log("script: spawning actor %u next to %u (tile %d,%d)", (unsigned)g_adds[k].profile, (unsigned)prof, g_adds[k].tx, g_adds[k].tz);
        acnl_call_again_patched(100 + (uint32_t)k, acnl_reg(0), rec, acnl_reg(2), g_param[k] + 0x20, prof, g_adds[k].profile, r3, g_param[k] + 0x20);
    }
    return ACNL_CONTINUE;
}
/* the actor's place: x, y, z at +0x14 and the copy the game keeps beside it at +0x20 */
void put_actor(uint32_t obj, float x, float z) {
    const uint32_t base[2] = {0x14, 0x20};
    for (int i = 0; i < 2; i++) { acnl_write(obj + base[i], &x, 4); acnl_write(obj + base[i] + 8, &z, 4); }
}
int g_dumped_genuine = 0;
void hook_spawn_post(void *) {
    uint32_t obj = acnl_reg(0);
    if (obj >= 0x100000 && g_dumped_genuine < 2 && acnl_rd16(obj + 0xc) == 492) { g_dumped_genuine++; probe_dump("genuine", obj, 492); }
    if (g_placed.obj && obj == g_placed.obj) put_actor(obj, g_placed.x, g_placed.z);
    g_placed.obj = 0;
}
/* characters held on a tile (added ones, and the ones place_actor() moved): the game puts a character on its spot after creating it
   (a genuine Tom Nook is created at 272,0,368 and then stands at 288,32,400), so the place is written again every frame, from the
   player's update (AcPlayer method 9, which also starts the player leaving a room). Every change the game makes is logged (the first
   few), and so are the link tiles the player walks on. */
const uint32_t FN_PLAYER_UPDATE = 0x68c0ec;
const int MAX_PINS = 8;
struct Pin { uint32_t obj, vtable; float x, z; int moved; } g_pin[MAX_PINS];
uint32_t g_talker[MAX_ADDS];                 /* the characters added in this room (their conversations are the mod's) */
int g_npin = 0, g_frames = 0;
void pin_add(uint32_t obj, float x, float z) {
    for (int i = 0; i < g_npin; i++) if (g_pin[i].obj == obj) { g_pin[i].x = x; g_pin[i].z = z; return; }
    if (g_npin < MAX_PINS && obj >= 0x100000) g_pin[g_npin++] = {obj, acnl_rd32(obj), x, z, 0};
}
int g_last_tile = -1, g_tile_logs = 0;
void trace_reset();
void glob_snapshot(int page);
void pin_reset() { trace_reset(); g_on_link = false; memset(g_talker, 0, sizeof g_talker); g_npin = 0; g_last_tile = -1; g_jmp_logged_page = -1; }
void pin_tick();
/* ---- doors between rooms. An exit tile of type 0x4007 + n is door n of the scene: the player's own update looks it up in the scene's door
   table (*(0x956344 + scene * 4) + 0xc -> {36-byte entries, count}; an entry: u8 destination scene, its place at +8, angles at +0x14) and
   walks out through it. Door 0 of Nook's Homes is the front door, which the shop handles (Tom Nook sees the customer out, then the scene
   changes). Link tiles are doors 1.. of their room: the plugin adds them to the table, leading back into the same scene at the link's
   arrival tile, so moving between rooms is a plain door, as between the rooms of a house (no goodbye, no leaving the building). */
const uint32_t SCENE_DOORS = 0x956344;
const int DOOR_SIZE = 36, MAX_DOORS = 8;
uint32_t g_door_mem[MAX_PAGES];            /* per room: {entries, count} + entries */
uint32_t g_door_data = 0, g_door_orig = 0, g_door_mine = 0;
int g_door_page = -1;
void doors_restore() {
    if (g_door_data && g_door_orig && acnl_rd32(g_door_data + 0xc) == g_door_mine) acnl_wr32(g_door_data + 0xc, g_door_orig);
    g_door_data = g_door_orig = g_door_mine = 0;
    g_door_page = -1;
}
void doors_tick() {
    if (g_cur < 0 || g_page >= g_b[g_cur].npages || g_b[g_cur].scene < 0) return;
    Building &b = g_b[g_cur];
    Page &pg = b.pages[g_page];
    if (!pg.nlinks) return;
    uint32_t dd = acnl_rd32(SCENE_DOORS + (uint32_t)b.scene * 4);
    if (dd < 0x100000) return;
    uint32_t ex = acnl_rd32(dd + 0xc);
    if (g_door_page == g_page && dd == g_door_data && ex == g_door_mine) return;     /* in place */
    if (ex == g_door_mine && dd == g_door_data) ex = g_door_orig;                    /* another room of the same building */
    if (ex < 0x100000) return;
    uint32_t entries = acnl_rd32(ex), count = acnl_rd32(ex + 4);
    if (entries < 0x100000 || count == 0 || count > 16) return;
    /* the room's doors: one per different destination, numbered from 1 in the order of its link lines (as the builder numbers them) */
    Link doors[MAX_DOORS];
    int nd = 0;
    for (int l = 0; l < pg.nlinks && nd < MAX_DOORS - 1; l++) {
        const Link &k = pg.links[l];
        bool seen = false;
        for (int d = 0; d < nd; d++) if (doors[d].to == k.to && doors[d].ax == k.ax && doors[d].ay == k.ay && doors[d].yaw == k.yaw) seen = true;
        if (!seen) doors[nd++] = k;
    }
    uint32_t n = (uint32_t)nd + 1 > count ? (uint32_t)nd + 1 : count;
    if (!g_door_mem[g_page]) g_door_mem[g_page] = acnl_alloc(8 + DOOR_SIZE * MAX_DOORS * 2, 4);
    uint32_t mem = g_door_mem[g_page];
    if (!mem) return;
    uint8_t e[DOOR_SIZE];
    for (uint32_t i = 0; i < n; i++) {
        acnl_read(entries + (i < count ? i : 0) * DOOR_SIZE, e, DOOR_SIZE);
        if (i >= 1 && (int)i <= nd) {
            const Link &k = doors[i - 1];
            float pos[3] = {k.ax * TILE + TILE / 2.0f, 32.0f, k.ay * TILE + TILE / 2.0f};
            uint16_t ang[3] = {0, (uint16_t)k.oyaw, 0};
            e[0] = e[1] = e[2] = e[3] = (uint8_t)b.scene;
            e[4] = 0;
            memcpy(e + 8, pos, 12);
            memcpy(e + 0x14, ang, 6);
            /* the kind of door (+0x20): 4 is a front door from outside (walking into a shop: the shopkeeper greets, the shop music plays),
               3 a door between two rooms (the side rooms of houses, the museum...), 1 and 2 stairs; the rooms of a building use 3 */
            e[0x20] = 3;
        }
        acnl_write(mem + 8 + i * DOOR_SIZE, e, DOOR_SIZE);
    }
    acnl_wr32(mem, mem + 8);
    acnl_wr32(mem + 4, n);
    if (dd != g_door_data || g_door_orig == 0) { g_door_data = dd; g_door_orig = ex; }
    g_door_mine = mem;
    g_door_page = g_page;
    acnl_wr32(dd + 0xc, mem);
    uint8_t e0[DOOR_SIZE];
    acnl_read(entries, e0, DOOR_SIZE);
    acnl_log("builder: room %d: %d door(s) to other rooms added to the scene's %u door(s) (front door: to scene %u, kind %u)", g_page, nd, (unsigned)count, e0[0], e0[0x20]);
}
/* the door walk follows the player's facing: the game walks the player opposite to a door's angle (seen in game), so the doors of the
   room take the player's own angle + half a turn, refreshed every frame */
const uint32_t PLAYER_YAW = 0x34;          /* u16: the player's facing (0 south, 0x4000 east, 0x8000 north, 0xC000 west) */
void doors_face_player() {
    if (!g_door_mine || !g_player || acnl_rd32(g_door_data + 0xc) != g_door_mine) return;
    uint32_t n = acnl_rd32(g_door_mine + 4);
    uint16_t yaw = (uint16_t)(acnl_rd16(g_player + PLAYER_YAW) + 0x8000);
    for (uint32_t i = 1; i < n && i < (uint32_t)MAX_DOORS * 2; i++) acnl_wr16(g_door_mine + 8 + i * DOOR_SIZE + 0x16, yaw);
}
void came_from_put();
void came_from_keep();
/* the game's talk controller: *(0x95ceac) + 0x18 -> controller, its state at +0x20 (logged when it changes, while tracing) */
uint32_t g_tc_last[3] = {1, 1, 1};
int g_tc_logs = 0;
void talk_watch() {
    if (!g_ntrace || g_tc_logs >= 120) return;
    uint32_t x = acnl_rd32(0x95ceac), ctl = x >= 0x100000 ? acnl_rd32(x + 0x18) : 0, st = ctl >= 0x100000 ? acnl_rd8(ctl + 0x20) : 0xFF;
    if (x == g_tc_last[0] && ctl == g_tc_last[1] && st == g_tc_last[2]) return;
    g_tc_last[0] = x; g_tc_last[1] = ctl; g_tc_last[2] = st;
    g_tc_logs++;
    uint32_t w[16] = {0}, v[8] = {0};
    if (ctl >= 0x100000) acnl_read(ctl, w, sizeof w);
    if (x >= 0x100000) acnl_read(x, v, sizeof v);
    acnl_log("trace: talk room %d frame %d: system %08x [%08x %08x %08x %08x %08x %08x %08x %08x] controller %08x state %u [%08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x]",
             g_page, g_frames, (unsigned)x, (unsigned)v[0], (unsigned)v[1], (unsigned)v[2], (unsigned)v[3], (unsigned)v[4], (unsigned)v[5], (unsigned)v[6], (unsigned)v[7],
             (unsigned)ctl, (unsigned)st, (unsigned)w[0], (unsigned)w[1], (unsigned)w[2], (unsigned)w[3], (unsigned)w[4], (unsigned)w[5], (unsigned)w[6], (unsigned)w[7],
             (unsigned)w[8], (unsigned)w[9], (unsigned)w[10], (unsigned)w[11]);
}
uint8_t g_win_last[0x20];
int g_win_logs = 0;
void window_watch() {
    if (!g_ntrace || g_win_logs >= 200) return;
    uint8_t w[0x20];
    if (acnl_read(0x94f704, w, sizeof w) != 0 || !memcmp(w, g_win_last, sizeof w)) return;
    memcpy(g_win_last, w, sizeof w);
    g_win_logs++;
    acnl_log("trace: bells window frame %d scene %u: mode %u want %u [5]=%u [6]=%u +0x10 %08x +0x14 %08x +0x1c %08x", g_frames, (unsigned)acnl_rd8(0x956322),
             w[0], w[1], w[5], w[6], (unsigned)(w[0x10] | w[0x11] << 8 | w[0x12] << 16 | (uint32_t)w[0x13] << 24),
             (unsigned)(w[0x14] | w[0x15] << 8 | w[0x16] << 16 | (uint32_t)w[0x17] << 24), (unsigned)(w[0x1c] | w[0x1d] << 8 | w[0x1e] << 16 | (uint32_t)w[0x1f] << 24));
}
void hook_player_update_post(void *) {
    g_frames++;
    veh::tick(g_player, 0);
    window_watch();
    doors_tick();
    doors_face_player();
    talk_watch();
    if (g_came_from_frames > 0) { g_came_from_frames--; came_from_put(); }
    else if (g_cur >= 0 && !g_by_link && g_page == 0 && !g_on_link) came_from_keep();      /* walked in from the town: these are the right values */
    pin_tick();
}
void pin_tick() {
    for (int i = 0; i < g_npin; i++) {
        Pin &p = g_pin[i];
        if (acnl_rd32(p.obj) != p.vtable) continue;                         /* gone */
        float pos[3];
        if (acnl_read(p.obj + 0x14, pos, 12) != 0) continue;
        float dx = pos[0] - p.x, dz = pos[2] - p.z;
        if (dx * dx + dz * dz > 1.0f) {
            if (p.moved++ < 6) acnl_log("builder: the game moved actor %08x (profile %u) to %.0f,%.0f,%.0f (frame %d): put back on %.0f,%.0f",
                                        (unsigned)p.obj, (unsigned)acnl_rd16(p.obj + 0xc), pos[0], pos[1], pos[2], g_frames, p.x, p.z);
            put_actor(p.obj, p.x, p.z);
        }
    }
    if (g_cur >= 0 && g_player && g_page < g_b[g_cur].npages && g_b[g_cur].pages[g_page].nlinks) {
        float pos[3];
        if (acnl_read(g_player + 0x14, pos, 12) != 0) return;
        int tx = (int)(pos[0] / TILE), ty = (int)(pos[2] / TILE), t = ty * 16 + tx;
        if (t == g_last_tile || tx < 0 || ty < 0 || tx > 15 || ty > 15) return;
        g_last_tile = t;
        const Page &pg = g_b[g_cur].pages[g_page];
        g_on_link = false;
        for (int l = 0; l < pg.nlinks; l++) if (pg.links[l].x == tx && pg.links[l].y == ty) { g_on_link = true; g_last_link = l; g_last_link_page = g_page; }
        if (g_on_link) glob_snapshot(g_page);
        for (int l = 0; l < pg.nlinks; l++)
            if (pg.links[l].x == tx && pg.links[l].y == ty) {
                uint16_t attr = pg.jmp ? acnl_rd16(pg.jmp + (uint32_t)t * 10 + 8) : 0;
                if (g_tile_logs++ < 60) {
                    uint32_t st = acnl_rd8(g_player + 0x1a9);
                    uint32_t cat = st < 0xeb ? (acnl_rd8(0x841c20 + st * 10 + 5) >> 4) : 99;
                    acnl_log("builder: room %d: the player is on link tile %d,%d (collision attribute %04x), facing %04x; player state %#x (kind %u)",
                             g_page, tx, ty, attr, acnl_rd16(g_player + 0x34), st, cat);
                }
            }
    }
}
extern "C" ACNL_EXPORT("acnl_mod_call_done") void acnl_mod_call_done(uint32_t id, uint32_t result) {
    if (id < 100 || id >= 100 + MAX_ADDS) return;
    const AddReq &a = g_adds_run[id - 100];
    CharDef *cd = char_def(a.profile, false);
    if (cd && cd->code[0]) { acnl_wr32(NEW_ACTOR_POS, g_create_pos_saved[0]); acnl_wr32(NEW_ACTOR_POS + 4, g_create_pos_saved[1]); }
    if (result >= 0x100000 && acnl_rd32(result) < 0x100000) { acnl_log("script: the extra actor %u is not a real object (%08x)", (unsigned)a.profile, (unsigned)result); return; }
    if (result >= 0x100000) g_talker[(id - 100) % MAX_ADDS] = result;
    if (result < 0x100000) { acnl_log("script: the extra actor %u was not created", (unsigned)a.profile); return; }
    /* a character does not take its place from the parameter block (seen in game: the added Isabelle stood on the spot of the character
       she was spawned with, block or not), so the tile is written into the new actor once the spawn is done */
    float before[3] = {0, 0, 0};
    acnl_read(result + 0x14, before, 12);
    put_actor(result, a.tx * (float)TILE + TILE / 2.0f, a.tz * (float)TILE + TILE / 2.0f);
    pin_add(result, a.tx * (float)TILE + TILE / 2.0f, a.tz * (float)TILE + TILE / 2.0f);
    probe_dump("added", result, a.profile);
    acnl_log("script: the extra actor %u was created: object %08x, moved from %.0f,%.0f to tile %d,%d", (unsigned)a.profile, (unsigned)result,
             before[0], before[2], a.tx, a.tz);
}

void load_scripts() {
    int n = acnl_read_file("acnlb.script", g_script_blob, sizeof g_script_blob);
    if (n <= 0) return;
    if (n > (int)sizeof g_script_blob || !sv::parse(g_script_blob, n, g_prog)) { acnl_log("script: acnlb.script is damaged: scripts are off"); return; }
    g_scripts = g_prog.nhandlers > 0;
    acnl_log("script: %d trigger(s) loaded", g_prog.nhandlers);
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
/* conversations: every flow the game loads goes through script::IFlowRecept method 2 (0x5da2e0: recept r1, r2 the flow's name, which
   it keeps at r1 + 0x100 and formats into "Script/Flow/%s.msbf" in the buffer at r1 + 0x104). It is logged, and an added character (its
   talk receptor is part of the actor) gets the conversation the mod gives it: the name is replaced by that flow's (whose rewritten copy
   the mod's variant serves; the rewritten flow starts with the mod's messages from every entry). */
const uint32_t FN_FLOW_LOAD = 0x5da2e0;
char g_entry_name[48];
uint32_t g_entry_guest = 0;
void read_cstr(uint32_t a, char *out, int cap) {
    int i = 0;
    if (a >= 0x100000) for (; i < cap - 1; i++) { uint8_t ch = acnl_rd8(a + (uint32_t)i); if (!ch || ch < 32 || ch > 126) break; out[i] = (char)ch; }
    out[i] = 0;
}
Saved s_flow;
void hook_flow_load_post(void *) {
    uint32_t recept = pop(s_flow);
    char path[80];
    read_cstr(acnl_rd32(recept + 0x108), path, sizeof path);
    acnl_log("trace: conversation file %s (scene %u)", path, (unsigned)acnl_rd8(0x956322));
}
int hook_flow_load_pre(void *) {
    uint32_t recept = acnl_reg(1), r3 = acnl_reg(3);
    push(s_flow, recept);
    char name[64];
    read_cstr(acnl_reg(2), name, sizeof name);
    int who = -1;
    for (int k = 0; k < MAX_ADDS; k++)
        if (g_talker[k] && recept >= g_talker[k] && recept < g_talker[k] + 0x4000) who = k;
    acnl_log("builder: conversation %s (r3 %08x) for %08x%s, from %08x", name, (unsigned)r3, (unsigned)recept,
             who >= 0 ? " (an added character)" : "", (unsigned)acnl_return_address());
    if (who < 0) return ACNL_CONTINUE;
    CharDef *cd = char_def(acnl_rd16(g_talker[who] + 0xc), false);
    if (!cd || !cd->flow[0] || !strcmp(cd->flow, name)) return ACNL_CONTINUE;
    if (!g_entry_guest) g_entry_guest = acnl_alloc(sizeof g_entry_name, 4);
    if (!g_entry_guest) return ACNL_CONTINUE;
    acnl_write(g_entry_guest, cd->flow, strlen(cd->flow) + 1);
    acnl_set_reg(2, g_entry_guest);
    acnl_log("builder: the added character talks with %s instead", cd->flow);
    return ACNL_CONTINUE;
}
void restore_spots();
void pin_reset();
void doors_restore();
uint32_t g_entry_args[6];
bool g_has_entry_args = false;
int hook_goto_pre(void *) {
    restore_spots();                           /* a spot moved for an added character belongs to the room being left */
    pin_reset();
    uint32_t cur = acnl_rd8(SCENE_STATE + 2), want = acnl_reg(1) & 0xFF, sp = acnl_reg(13);
    if (g_nb && (cur == 0 || want == 0 || (g_cur >= 0 && cur == (uint32_t)g_b[g_cur].scene))) {      /* what a door of the game asks for */
        float pos[3] = {0, 0, 0};
        uint16_t ang[3] = {0, 0, 0};
        acnl_read(acnl_reg(2), pos, 12);
        acnl_read(acnl_reg(3), ang, 6);
        uint32_t w[6];
        acnl_read(sp, w, sizeof w);
        acnl_log("builder: scene change %u -> %u, arrival %.0f,%.0f,%.0f angle %u, stack %x %x %x %x %x %x", cur, want, pos[0], pos[1], pos[2], ang[1],
                 (unsigned)w[0], (unsigned)w[1], (unsigned)w[2], (unsigned)w[3], (unsigned)w[4], (unsigned)w[5]);
        /* the arguments of walking in from the town through the building's door: a move between rooms uses the same ones, so the place
           is set up as after a real entrance (greeting, the host seeing the player out, talking) */
        if (cur == 0 && g_cur >= 0 && want == (uint32_t)g_b[g_cur].scene) { memcpy(g_entry_args, w, sizeof w); g_has_entry_args = true; }
    }
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
    if (g_cur >= 0 && cur == 0 && g_b[g_cur].scene >= 0 && want == (uint32_t)g_b[g_cur].scene && g_b[g_cur].npages && (g_has_override || g_b[g_cur].pages[0].has_entry)) {
        /* coming in through the door: a script's place_player(), or a room whose entrance is not on the south edge */
        const Page &pg0 = g_b[g_cur].pages[0];
        float np[3] = {g_has_override ? g_entry_override.px : pg0.entry_x, 32.0f, g_has_override ? g_entry_override.pz : pg0.entry_z};
        uint16_t na[3] = {0, (uint16_t)(g_has_override ? g_entry_override.yaw : pg0.entry_yaw), 0};
        acnl_write(acnl_reg(2), np, 12);
        acnl_write(acnl_reg(3), na, 6);
        g_has_override = false;
    }
    bool linked = false;
    /* leaving a room of the building (to the town, or, after an arrival from another room, to that same scene): a link tile under the
       player (or touching them: the game may start leaving a step before the tile) takes them to the linked room instead */
    if (g_cur >= 0 && g_page < g_b[g_cur].npages && cur == (uint32_t)g_b[g_cur].scene && g_player) {
        Building &b = g_b[g_cur];
        Page &pg = b.pages[g_page];
        float pos[3];
        if (acnl_read(g_player + 0x14, pos, 12) == 0) {
            int tx = (int)(pos[0] / TILE), ty = (int)(pos[2] / TILE);
            acnl_log("builder: %s: leaving room %d (scene %u -> %u) from tile %d,%d", b.id, g_page, cur, want, tx, ty);
            int best = -1;
            float bestd = 1e9f;
            if (want == cur && g_last_link_page == g_page && g_last_link >= 0 && g_last_link < pg.nlinks) { best = g_last_link; bestd = 0; }   /* a door of ours */
            else for (int l = 0; l < pg.nlinks; l++) {
                const Link &k = pg.links[l];
                if (k.to < 0 || k.to >= b.npages) continue;
                float dx = pos[0] - (k.x * TILE + TILE / 2.0f), dz = pos[2] - (k.y * TILE + TILE / 2.0f);
                float ax = dx < 0 ? -dx : dx, az = dz < 0 ? -dz : dz, d = ax > az ? ax : az;      /* distance from the tile's middle */
                if (d < bestd) { bestd = d; best = l; }
            }
            for (int l = 0; l < pg.nlinks; l++) {
                const Link &k = pg.links[l];
                if (l != best || bestd > TILE * 0.9f) continue;
                g_last_link = g_last_link_page = -1;
                float np[3] = {k.ax * TILE + TILE / 2.0f, 32.0f, k.ay * TILE + TILE / 2.0f};
                uint16_t na[3] = {0, (uint16_t)k.yaw, 0};
                acnl_write(acnl_reg(2), np, 12);
                acnl_write(acnl_reg(3), na, 6);
                if (want != (uint32_t)b.scene) {                /* (the front door: leaving the building, turned into a room change) */
                    if (g_has_entry_args) acnl_write(sp, g_entry_args, sizeof g_entry_args);
                    else { acnl_wr32(sp, SCENE_ARRIVE_INDOOR); acnl_wr32(sp + 4, 0); }
                    acnl_set_reg(1, (uint32_t)b.scene);
                }
                select_page(b, k.to);
                g_by_link = true;
                if (b.quiet[0]) acnl_set_romfs_variant(b.quiet, 1);
                acnl_log("builder: %s: room %d -> room %d (tile %d,%d)", b.id, (int)(&pg - b.pages), k.to, tx, ty);
                linked = true;
                if (g_scripts) {
                    memset(&g_sc, 0, sizeof g_sc);
                    script_fire(sv::K_ROOM, b.id, b.pages[k.to].scene_id, 0);
                    script_fire(sv::K_ENTER, b.id, b.pages[k.to].scene_id, 0, true);
                }
                break;
            }
        }
    }
    if (!linked && g_cur >= 0 && cur == (uint32_t)g_b[g_cur].scene && want != cur) doors_restore();       /* out of the building */
    if (g_scripts && !linked && g_cur >= 0 && cur == (uint32_t)g_b[g_cur].scene && want == 0) {      /* @on_leave */
        memset(&g_sc, 0, sizeof g_sc);
        script_fire(sv::K_LEAVE, g_b[g_cur].id, g_page < g_b[g_cur].npages ? g_b[g_cur].pages[g_page].scene_id : "", 0);
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
        if (g_b[i].quiet[0]) acnl_set_romfs_variant(g_b[i].quiet, 0);        /* walking in from the town: the host greets */
        if (g_b[i].variant[0]) acnl_set_romfs_variant(g_b[i].variant, i == g_cur);
        for (int k = 0; k < g_b[i].npages; k++) acnl_set_romfs_variant(g_b[i].pages[k].variant, i == g_cur && k == 0);
    }
    g_page = 0;
    g_by_link = false;
    g_has_override = false;
    if (g_scripts && g_cur >= 0) {                  /* @on_enter */
        memset(&g_sc, 0, sizeof g_sc);
        script_fire(sv::K_ENTER, g_b[g_cur].id, g_b[g_cur].npages ? g_b[g_cur].pages[0].scene_id : "", 0);
        if (g_sc.place) { g_entry_override = g_sc; g_has_override = true; }
    }
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
    load_scripts();
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
    if ((any_links || g_trace || g_debug_enter || (g_scripts && g_nb)) && acnl_hook(FN_GOTO_SCENE, hook_goto_pre, nullptr, nullptr) != 0) return -1;
    const bool vehicles = veh::g_nv > 0;
    if ((any_links || vehicles) && acnl_hook(FN_ACTOR_CREATE, hook_actor_track_pre, hook_actor_track_post, nullptr) != 0) return -1;
    if (vehicles) {
        field::default_blocked();
        field::load_radius("fgcol.bin");
        for (int i = 0; i < veh::g_nv; i++) veh::load_assets(veh::g_v[i]);
        acnl_log("vehicles: %d vehicle(s)", veh::g_nv);
    }
    for (int i = 0; i < g_nprobe; i++)
        if (acnl_hook(g_probe[i].addr, hook_probe, nullptr, (void *)(intptr_t)i) != 0) acnl_log("probe: cannot hook %#x (%s)", (unsigned)g_probe[i].addr, g_probe[i].label);
    if (g_probe_spawns && acnl_hook(0x51ef80, hook_probe_spawn_pre, hook_probe_spawn_post, nullptr) != 0) acnl_log("probe: cannot hook the spawn function");
    if (g_probe_actors && acnl_hook(FN_ACTOR_CREATE, hook_probe_actor_pre, hook_probe_actor_post, nullptr) != 0) return -1;
    if (g_scripts) {
        bool actors = false;
        for (int i = 0; i < g_prog.nhandlers; i++) {
            const sv::Handler &h = g_prog.h[i];
            if (h.kind == sv::K_ACTOR) actors = true;
            if (h.kind == sv::K_CALL && acnl_hook(h.num, hook_script_call_pre, nullptr, (void *)(intptr_t)i) != 0)
                acnl_log("script: cannot hook %#x: it is not a function of the game, the trigger stays off", (unsigned)h.num);
        }
        if (actors && acnl_hook(FN_ACTOR_CREATE, hook_script_actor_pre, hook_script_actor_post, nullptr) != 0) return -1;
        bool spawns = false;
        for (int i = 0; i < g_prog.nhandlers; i++) if (g_prog.h[i].kind == sv::K_SPAWN) spawns = true;
        if ((spawns || actors) && acnl_hook(FN_SPAWN, hook_spawn_pre, hook_spawn_post, nullptr) != 0) { acnl_log("script: cannot hook the spawn function: @on_spawn is off"); }
    }
    /* after the scripts' hook: a script may turn a furniture request into a character before the exhibits are hidden */
    if (any_hide && acnl_hook(FN_ACTOR_CREATE, hook_actor_create_pre, nullptr, nullptr) != 0) return -1;
    if (any_jmp && acnl_hook(FN_JMP_BLOCK, hook_jmp_block_pre, hook_jmp_block_post, nullptr) != 0) return -1;
    if (g_scripts && g_ntrace && acnl_hook(FN_FLOW_LOAD, hook_flow_load_pre, hook_flow_load_post, nullptr) != 0) acnl_log("builder: cannot hook the conversation loader");
    if ((g_scripts || any_links || vehicles) && acnl_hook(FN_PLAYER_UPDATE, nullptr, hook_player_update_post, nullptr) != 0) acnl_log("builder: cannot hook the player's update");
    /* the tracing hooks last: the SDK has 128 hook slots, the mod's own come first */
    for (int i = 0; i < g_ntrace; i++)
        if (acnl_hook(g_trace_fn[i].addr, hook_trace_pre, hook_trace_post, (void *)(intptr_t)i) != 0) acnl_log("trace: cannot hook %#x", (unsigned)g_trace_fn[i].addr);
    return 0;
}
