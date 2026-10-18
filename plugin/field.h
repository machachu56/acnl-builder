/* The town as the game keeps it, for things that move by themselves (vehicles): ground height and kind per tile, the
   field items (trees, rocks...) that block the way. Found in game (EUR Welcome amiibo), see docs/VEHICLES.md:

   field object (*0x9b3a24, what 0x6a4e7c returns; r0 of 0x317184): s32 x0, y0, x1, y1 (acres), +0x20 acre records (12 bytes),
     +0x24 per acre 0xA1C bytes: 0x1C header, then 16 x 16 tiles of 5 u16: four words of three 5-bit heights (x 8 units)
     -- the tile's triangles N, E, S, W as (centre, corner, corner) -- and the attribute (low byte: kind of ground).
     Buildings are stamped into it as raised ground.
   town items: save + 0x534D8, 20 acres (the playable 5 x 4, acre-major) x 256 u32 (low 16 bits: item, 0x7FFE: none).
   item collision: /Fg/Param/Fg.bin, 16 bytes per field item, u16 at +0 = radius (written to the mod as fgcol.bin). */
#pragma once
#include "pmath.h"

namespace field {

const uint32_t FIELD_PTR = 0x9b3a24;            /* the current field (town, island...) */
const uint32_t SAVE_PTR_ = 0x95af74;
const uint32_t TOWN_ITEMS = 0x534D8;
const float TILE_ = 32.0f, ACRE = 512.0f;

uint32_t g_field = 0;
uint16_t g_item_radius[256];
bool g_have_radius = false;
/* kinds of ground nothing can drive on (out of bounds, rails, sea, river, building blocks, doors) */
uint8_t g_blocked[256];

void default_blocked() {
    static const uint8_t b[] = {0x0f, 0xaa, 0x25, 0x26, 0x27, 0x28, 0x29, 0x10, 0x1b, 0x1c, 0x1d, 0x1e, 0x1f, 0x20, 0x21, 0x22, 0x02, 0x32};
    for (uint8_t v : b) g_blocked[v] = 1;
}

/* follow the game's current field (read each frame: it changes with the scene); false when there is none */
bool refresh() {
    uint32_t f = acnl_rd32(FIELD_PTR);
    if (f == g_field) return f != 0;
    g_field = 0;
    if (f < 0x100000) return false;
    int32_t r[4];
    if (acnl_read(f, r, sizeof r) != 0) return false;
    if (r[0] < 0 || r[1] < 0 || r[2] < r[0] || r[3] < r[1] || r[2] >= 16 || r[3] >= 16 || acnl_rd32(f + 0x24) < 0x100000) return false;
    g_field = f;
    acnl_log("vehicles: town field %08x (acres %d,%d .. %d,%d)", f, r[0], r[1], r[2], r[3]);
    return true;
}

void load_radius(const char *file) {
    int n = acnl_read_file(file, g_item_radius, sizeof g_item_radius);
    g_have_radius = n > 0;
}

/* the tile record (5 u16) under a position; false outside the town */
bool tile(float x, float z, uint16_t w[5], float *u, float *v) {
    if (!g_field || x < 0 || z < 0) return false;
    int32_t r[4];
    if (acnl_read(g_field, r, sizeof r) != 0) return false;
    int ax = (int)(x / ACRE), az = (int)(z / ACRE);
    if (ax < r[0] || az < r[1] || ax > r[2] || az > r[3]) return false;
    int width = r[2] - r[0] + 1;
    uint32_t data = acnl_rd32(g_field + 0x24);
    if (data < 0x100000) return false;
    float lx = x - ax * ACRE, lz = z - az * ACRE;
    int tx = (int)(lx / TILE_), tz = (int)(lz / TILE_);
    if (tx > 15) tx = 15;
    if (tz > 15) tz = 15;
    uint32_t a = data + (uint32_t)((az - r[1]) * width + (ax - r[0])) * 0xA1C + 0x1C + (uint32_t)(tz * 16 + tx) * 10;
    if (acnl_read(a, w, 10) != 0) return false;
    *u = (lx - tx * TILE_) / TILE_;
    *v = (lz - tz * TILE_) / TILE_;
    return true;
}

/* ground height (world units) and kind at a position; false outside the town */
bool ground(float x, float z, float *h, uint8_t *kind) {
    uint16_t w[5];
    float u, v;
    if (!tile(x, z, w, &u, &v)) return false;
    *kind = (uint8_t)(w[4] & 0xFF);
    /* the triangle the point is in: N (v < u, v < 1-u), E, S, W; vertices (centre, corner a, corner b) */
    int t;
    if (v <= u && v <= 1 - u) t = 0;
    else if (u >= v && u >= 1 - v) t = 1;
    else if (v >= u && v >= 1 - u) t = 2;
    else t = 3;
    float hc = (float)(w[t] & 31), ha = (float)((w[t] >> 5) & 31), hb = (float)((w[t] >> 10) & 31);
    /* corners: NW (0,0) NE (1,0) SE (1,1) SW (0,1); triangle t joins corner t and corner t+1 (clockwise from NW) */
    static const float cx[4] = {0, 1, 1, 0}, cz[4] = {0, 0, 1, 1};
    float ax_ = cx[t], az_ = cz[t], bx = cx[(t + 1) & 3], bz = cz[(t + 1) & 3];
    /* barycentric weights of (u, v) in (C(0.5,0.5), A, B) */
    float d = (az_ - bz) * (0.5f - bx) + (bx - ax_) * (0.5f - bz);
    float wc = ((az_ - bz) * (u - bx) + (bx - ax_) * (v - bz)) / d;
    float wa = ((bz - 0.5f) * (u - bx) + (0.5f - bx) * (v - bz)) / d;
    float wb = 1 - wc - wa;
    *h = (hc * wc + ha * wa + hb * wb) * 8.0f;
    return true;
}

/* the collision radius of the field item on a tile (0: none / passable) */
float item_radius(int tx, int tz) {
    if (!g_have_radius) return 0;
    uint32_t save = acnl_rd32(SAVE_PTR_);
    if (save < 0x100000) return 0;
    int ax = tx / 16 - 1, az = tz / 16 - 1;
    if (ax < 0 || az < 0 || ax > 4 || az > 3) return 0;
    uint32_t idx = (uint32_t)((az * 5 + ax) * 256 + (tz % 16) * 16 + (tx % 16));
    uint32_t item = acnl_rd32(save + TOWN_ITEMS + idx * 4) & 0xFFFF;
    if (item >= 0xFE) return 0;
    return (float)g_item_radius[item];
}

/* is a point free of field items? (circles of their radius around their tile's centre) */
bool clear_of_items(float x, float z, float margin) {
    int tx = (int)(x / TILE_), tz = (int)(z / TILE_);
    for (int dz = -1; dz <= 1; dz++)
        for (int dx = -1; dx <= 1; dx++) {
            float r = item_radius(tx + dx, tz + dz);
            if (r <= 0) continue;
            float cx = (tx + dx) * TILE_ + TILE_ / 2, cz = (tz + dz) * TILE_ + TILE_ / 2;
            float ex = x - cx, ez = z - cz, rr = r + margin;
            if (ex * ex + ez * ez < rr * rr) return false;
        }
    return true;
}

}  // namespace field
