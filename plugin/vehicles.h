/* Drivable vehicles ([vehicle] sections of acnlb.cfg, written by the builder's Objects tab).

   A vehicle is a prop (runtime props.h: the car's mesh drawn into the game's 3D scene, bent onto the town's rolling log)
   parked in the town. Next to it an "A" bubble shows: A gets in (the player hops into the seat and the game stops seeing
   the controls). The circle pad steers towards where it points and gives throttle (pull back to reverse), A accelerates,
   B brakes (hard turns with B drift; at a stop B gets out), Y honks, X switches the lights (on by themselves at night).
   It collides with the town (the game's own ground heights and kinds, its trees and rocks), spins and steers its wheels,
   leans on slopes and in turns, throws dust, sounds its engine and remembers where it was parked.

   Actor coordinates are flat (x east, z south, y up; 32 units a tile); the runtime bends props onto the cylinder the town
   is drawn on (world_roll, anchored on the player's own render matrix). Model axes: x = length (front at front * x),
   y = up, z = width. */
#pragma once
#include "field.h"
#include "pmath.h"

namespace veh {

using namespace pm;

const int MAX_VEHICLES = 4, MAX_PUFFS = 20, MAX_PARTS = 64;
const float ROLL_RADIUS = 488.89f;          /* arc length per radian of the town's cylinder */
const uint32_t SCENE_STATE_ = 0x956320;     /* +2: current scene (0 = the town) */

struct Config {
    char id[32], dir[48];
    float length, width, height, wheel_r, beam_len;
    int front;                               /* -1: the model's front is at -x */
    int wheels[4], nwheels, steer[2], nsteer, head[2], tail[2], brake[2], beam, prompt;
    float seat[3];
    float max_speed, accel, turn, grip;
    int start_kind;                          /* 0: tiles x, z; 1: next to the player's house; 2: town hall; 3: station */
    float start_x, start_z, start_yaw;
    uint32_t start_rev;                      /* changes with the start: a spot saved for another start is forgotten */
};

struct Puff { int prop; float x, y, z, vx, vy, vz, age, life, size; bool on; };

struct Vehicle {
    Config c;
    int prop, mesh, dust_mesh;
    float pivots[MAX_PARTS][3];
    int snd_engine, snd_start, snd_horn, snd_door, snd_skid, snd_stop;
    int v_engine, v_skid;
    bool placed, driving, entering, exiting, started;
    int lights_mode;                         /* 0 automatic (night), 1 on, 2 off */
    float x, y, z, head;                     /* flat position, ground height, heading (0 east, +pi/2 south) */
    float vx, vz;                            /* velocity */
    float vf, vl;                            /* ... along the heading and sideways (for the sounds, the lean, the dust) */
    float steer_vis, spin, pitch, roll, bob, throttle, braking, t;
    float anim_t, start_t;
    float ax, az, ay, bx, bz, by;            /* getting in / out: from, to */
    Puff puffs[MAX_PUFFS];
    int next_puff;
    float puff_acc;
    int place_wait;
};

Vehicle g_v[MAX_VEHICLES];
int g_nv = 0;
int g_driver = -1;                           /* the vehicle being driven (or got into / out of) */
uint32_t g_last_us = 0, g_prev_buttons = 0;

/* ------------------------------------------------------------------ config */

void init_config(Config &c) {
    memset(&c, 0, sizeof c);
    c.front = -1;
    c.length = 80; c.width = 50; c.height = 30; c.wheel_r = 7; c.beam_len = 128;
    c.max_speed = 330; c.accel = 240; c.turn = 2.4f; c.grip = 10;
    c.beam = c.prompt = -1;
    for (int i = 0; i < 2; i++) c.head[i] = c.tail[i] = c.brake[i] = -1;
    c.start_kind = 1;
    c.start_x = 3;
}

int parse_ints(const char *val, int *out, int max) {
    int n = 0;
    const char *p = val;
    while (n < max) {
        char *e;
        long v = acnl_strtol(p, &e, 0);
        if (e == p) break;
        out[n++] = (int)v;
        p = e;
        while (*p == ' ' || *p == ',' || *p == '\t') p++;
    }
    return n;
}

float parse_float(const char *s, const char **end) {
    while (*s == ' ' || *s == '\t' || *s == ',') s++;
    float sign = 1;
    if (*s == '-') { sign = -1; s++; } else if (*s == '+') s++;
    float v = 0;
    const char *start = s;
    while (*s >= '0' && *s <= '9') v = v * 10 + (float)(*s++ - '0');
    if (*s == '.') {
        s++;
        float f = 0.1f;
        while (*s >= '0' && *s <= '9') { v += (float)(*s++ - '0') * f; f *= 0.1f; }
    }
    if (end) *end = s == start ? start : s;
    return v * sign;
}

int parse_floats(const char *val, float *out, int max) {
    int n = 0;
    const char *p = val;
    while (n < max) {
        while (*p == ' ' || *p == ',' || *p == '\t') p++;
        if (!*p) break;
        const char *e;
        out[n] = parse_float(p, &e);
        if (e == p) break;
        n++;
        p = e;
    }
    return n;
}

void set_key(Config &c, const char *key, const char *val) {
    float f[3];
    if (!strcmp(key, "id")) copy_str(c.id, sizeof c.id, val);
    else if (!strcmp(key, "dir")) copy_str(c.dir, sizeof c.dir, val);
    else if (!strcmp(key, "length")) c.length = parse_float(val, nullptr);
    else if (!strcmp(key, "width")) c.width = parse_float(val, nullptr);
    else if (!strcmp(key, "height")) c.height = parse_float(val, nullptr);
    else if (!strcmp(key, "front")) c.front = parse_float(val, nullptr) < 0 ? -1 : 1;
    else if (!strcmp(key, "wheel_radius")) c.wheel_r = parse_float(val, nullptr);
    else if (!strcmp(key, "wheels")) c.nwheels = parse_ints(val, c.wheels, 4);
    else if (!strcmp(key, "steer")) c.nsteer = parse_ints(val, c.steer, 2);
    else if (!strcmp(key, "head")) parse_ints(val, c.head, 2);
    else if (!strcmp(key, "tail")) parse_ints(val, c.tail, 2);
    else if (!strcmp(key, "brake")) parse_ints(val, c.brake, 2);
    else if (!strcmp(key, "beam")) c.beam = (int)acnl_strtol(val, nullptr, 0);
    else if (!strcmp(key, "prompt")) c.prompt = (int)acnl_strtol(val, nullptr, 0);
    else if (!strcmp(key, "beam_length")) c.beam_len = parse_float(val, nullptr);
    else if (!strcmp(key, "seat") && parse_floats(val, f, 3) == 3) { c.seat[0] = f[0]; c.seat[1] = f[1]; c.seat[2] = f[2]; }
    else if (!strcmp(key, "max_speed")) c.max_speed = parse_float(val, nullptr);
    else if (!strcmp(key, "accel")) c.accel = parse_float(val, nullptr);
    else if (!strcmp(key, "turn")) c.turn = parse_float(val, nullptr);
    else if (!strcmp(key, "grip")) c.grip = parse_float(val, nullptr);
    else if (!strcmp(key, "start")) {            /* start = house|town_hall|station|tiles, dx, dz */
        const char *p = val;
        c.start_kind = !memcmp(p, "house", 5) ? 1 : !memcmp(p, "town_hall", 9) ? 2 : !memcmp(p, "station", 7) ? 3 : 0;
        while (*p && *p != ',') p++;
        if (parse_floats(p, f, 2) == 2) { c.start_x = f[0]; c.start_z = f[1]; }
    } else if (!strcmp(key, "yaw")) c.start_yaw = parse_float(val, nullptr) * PI / 180.0f;
    else if (!strcmp(key, "start_rev")) c.start_rev = (uint32_t)acnl_strtol(val, nullptr, 0);
}

/* ------------------------------------------------------------------ geometry */

/* the model's rotation about y for a heading: the model's front (front * x) turned to (cos h, sin h) */
float model_angle(const Vehicle &v) { return v.c.front < 0 ? PI - v.head : -v.head; }

/* a point of the model (lx along the length, lz across) in the flat world */
void to_world(const Vehicle &v, float lx, float lz, float *wx, float *wz) {
    float s, c;
    sincos(model_angle(v), &s, &c);
    *wx = v.x + c * lx + s * lz;
    *wz = v.z - s * lx + c * lz;
}
void to_model(const Vehicle &v, float wx, float wz, float *lx, float *lz) {
    float s, c;
    sincos(model_angle(v), &s, &c);
    float dx = wx - v.x, dz = wz - v.z;
    *lx = c * dx - s * dz;
    *lz = s * dx + c * dz;
}

/* can the vehicle stand at (x, z) facing `head`? (every point of its footprint on drivable ground, within a step of
   from_h when check_step, clear of trees and rocks); out_h: the ground height in its middle */
bool fits(const Vehicle &v0, float x, float z, float head, float from_h, float *out_h, bool check_step, float *pitch_out = nullptr,
          float *roll_out = nullptr) {
    Vehicle v = v0;
    v.x = x; v.z = z; v.head = head;
    float hl = v.c.length * 0.5f - 5, hw = v.c.width * 0.5f - 5;
    static const float px[9] = {1, 1, -1, -1, 1, -1, 0, 0, 0}, pz[9] = {1, -1, 1, -1, 0, 0, 1, -1, 0};
    float hs[9];
    for (int i = 0; i < 9; i++) {
        float wx, wz;
        to_world(v, px[i] * hl, pz[i] * hw, &wx, &wz);
        uint8_t kind;
        if (!field::ground(wx, wz, &hs[i], &kind)) return false;
        if (field::g_blocked[kind]) return false;
        if (check_step && absf(hs[i] - from_h) > 13.0f) return false;     /* a wall, a cliff, a building */
        if (!field::clear_of_items(wx, wz, 2)) return false;
    }
    if (out_h) *out_h = hs[8];
    /* the slope under it: x+ end (index 4) against x- end (5), z+ side (6) against z- (7) */
    if (pitch_out) *pitch_out = atan2f(hs[4] - hs[5], 2 * hl);
    if (roll_out) *roll_out = atan2f(hs[6] - hs[7], 2 * hw);
    return true;
}

/* ------------------------------------------------------------------ the world */

bool outdoors() { return acnl_rd8(SCENE_STATE_ + 2) == 0; }

int game_hour() {
    uint32_t sel = acnl_rd32(0x1FF81000) & 1, base = 0x1FF81020 + sel * 0x20;
    uint64_t ms = ((uint64_t)acnl_rd32(base + 4) << 32) | acnl_rd32(base);
    return (int)((ms / 3600000ull) % 24ull);
}

uint32_t player_render_matrix(uint32_t player) {
    if (player < 0x100000) return 0;
    uint32_t m = acnl_rd32(player + 0x230);
    if (m >= 0x100000) m = acnl_rd32(m + 0x220);
    if (m >= 0x100000) m = acnl_rd32(m + 0x30);
    return m >= 0x100000 ? m : 0;
}

bool building_tile(uint16_t lo, uint16_t hi, int *tx, int *tz) {
    uint32_t save = acnl_rd32(0x95af74);
    if (save < 0x100000) return false;
    uint32_t blk = save + 0x4be80;
    for (int i = 0; i < 56; i++) {
        uint32_t e = blk + 8 + i * 4;
        uint16_t id = acnl_rd16(e);
        if (id >= lo && id <= hi) { *tx = acnl_rd8(e + 2); *tz = acnl_rd8(e + 3); return true; }
    }
    return false;
}

/* ------------------------------------------------------------------ setup */

void file_path(const Vehicle &v, const char *name, char *out, int cap) {
    int n = 0;
    for (const char *s = v.c.dir; *s && n < cap - 1; s++) out[n++] = *s;
    for (const char *s = name; *s && n < cap - 1; s++) out[n++] = *s;
    out[n] = 0;
}

/* the parts' pivots, from the .apm header (wheels turn about them) */
void read_pivots(Vehicle &v, const char *path) {
    static uint8_t buf[24 + 64 * 16 + MAX_PARTS * 28];
    int n = acnl_read_file(path, buf, sizeof buf);
    if (n < 24) return;
    uint32_t np, nt;
    memcpy(&np, buf + 12, 4);
    memcpy(&nt, buf + 16, 4);
    uint32_t o = 24 + nt * 16;
    for (uint32_t i = 0; i < np && i < (uint32_t)MAX_PARTS && o + 28 <= (uint32_t)n; i++, o += 28) memcpy(v.pivots[i], buf + o + 12, 12);
}

void load_assets(Vehicle &v) {
    char path[96];
    file_path(v, "car.apm", path, sizeof path);
    v.mesh = acnl_prop_mesh(path);
    v.prop = acnl_prop_new(v.mesh);
    read_pivots(v, path);
    file_path(v, "dust.apm", path, sizeof path);
    v.dust_mesh = acnl_prop_mesh(path);
    for (int i = 0; i < MAX_PUFFS; i++) { v.puffs[i].prop = acnl_prop_new(v.dust_mesh); v.puffs[i].on = false; }
    static const char *names[6] = {"engine.wav", "start.wav", "horn.wav", "door.wav", "skid.wav", "stop.wav"};
    int *ids[6] = {&v.snd_engine, &v.snd_start, &v.snd_horn, &v.snd_door, &v.snd_skid, &v.snd_stop};
    for (int i = 0; i < 6; i++) { file_path(v, names[i], path, sizeof path); *ids[i] = acnl_sound_load(path); }
    v.v_engine = v.v_skid = -1;
}

struct Saved { uint32_t magic; float x, z, head; uint32_t rev; };
const uint32_t SPOT_MAGIC = 0x48455632u;

void spot_name(const Vehicle &v, char *name, int cap) {
    copy_str(name, (uint32_t)cap - 8, "veh_");
    int n = (int)strlen(name);
    copy_str(name + n, (uint32_t)(cap - n - 5), v.c.id);
    n = (int)strlen(name);
    memcpy(name + n, ".bin", 5);
}

void save_spot(const Vehicle &v) {
    char name[48];
    spot_name(v, name, sizeof name);
    Saved s = {SPOT_MAGIC, v.x, v.z, v.head, v.c.start_rev};
    acnl_storage_write(name, &s, sizeof s);
}

bool load_spot(Vehicle &v) {
    char name[48];
    spot_name(v, name, sizeof name);
    Saved s;
    if (acnl_storage_read(name, &s, sizeof s) != (int)sizeof s || s.magic != SPOT_MAGIC || s.rev != v.c.start_rev) return false;
    v.x = s.x; v.z = s.z; v.head = s.head;
    return true;
}

/* where the vehicle stands when the town is first there: its saved spot, or its configured start moved to free ground */
void place(Vehicle &v, const float player[3]) {
    float h;
    if (load_spot(v) && fits(v, v.x, v.z, v.head, 0, &h, false)) {
        v.y = h;
        v.placed = true;
        acnl_log("vehicles: %s parked where it was left (%.0f, %.0f)", v.c.id, v.x, v.z);
        return;
    }
    int tx = 0, tz = 0;
    float bx = player[0] + 96, bz = player[2];
    bool have = false;
    if (v.c.start_kind == 1) have = building_tile(0x00, 0x03, &tx, &tz);             /* the player's house (or tent) */
    else if (v.c.start_kind == 2) have = building_tile(0x50, 0x53, &tx, &tz);
    else if (v.c.start_kind == 3) have = building_tile(0x54, 0x57, &tx, &tz);
    if (v.c.start_kind == 0) { bx = v.c.start_x * 32 + 16; bz = v.c.start_z * 32 + 16; }
    else if (have) { bx = (tx + v.c.start_x) * 32 + 16; bz = (tz + v.c.start_z) * 32 + 16; }
    v.head = v.c.start_yaw;
    for (int ring = 0; ring < 14; ring++)                 /* step outwards until it fits on flat, free ground */
        for (int dz = -ring; dz <= ring; dz++)
            for (int dx = -ring; dx <= ring; dx++) {
                if (dx > -ring && dx < ring && dz > -ring && dz < ring) continue;
                float x = bx + dx * 32, z = bz + dz * 32, h2;
                if (!fits(v, x, z, v.head, 0, &h, false) || !fits(v, x, z, v.head, h, &h2, true)) continue;
                v.x = x; v.z = z; v.y = h;
                v.placed = true;
                acnl_log("vehicles: %s parked at %.0f, %.0f (tile %d, %d)", v.c.id, x, z, (int)(x / 32), (int)(z / 32));
                save_spot(v);
                return;
            }
    acnl_log("vehicles: no free spot for %s near %.0f, %.0f yet", v.c.id, bx, bz);
}

/* ------------------------------------------------------------------ drawing */

bool lights_on(const Vehicle &v) {
    if (v.lights_mode == 1) return true;
    if (v.lights_mode == 2) return false;
    int h = game_hour();
    return (v.driving || v.entering) && (h >= 18 || h < 6);
}

void place_model(Vehicle &v, bool visible, bool near) {
    float r[12], t[12], m[12], lean[12], lp[12], lr[12], base[12];
    m_rot_y(model_angle(v), r);
    m_rot_z(v.pitch * (float)v.c.front, lp);          /* nose up for a positive pitch */
    m_rot_x(v.roll, lr);
    m_mul(lp, lr, lean);
    m_translate(v.x, v.y + v.bob, v.z, t);
    m_mul(t, r, base);
    m_mul(base, lean, m);
    acnl_prop_place(v.prop, m, visible);
    /* wheels: spin about the axle (z), the front ones steer about y, both about the wheel's centre */
    for (int i = 0; i < v.c.nwheels; i++) {
        int part = v.c.wheels[i];
        if (part < 0 || part >= MAX_PARTS) continue;
        bool steers = false;
        for (int k = 0; k < v.c.nsteer; k++) steers |= v.c.steer[k] == part;
        float spin[12], st[12], both[12], about[12];
        m_rot_z(v.spin * (v.c.front < 0 ? 1.0f : -1.0f), spin);
        m_rot_y(steers ? v.steer_vis : 0.0f, st);
        m_mul(st, spin, both);
        m_about(both, v.pivots[part][0], v.pivots[part][1], v.pivots[part][2], about);
        acnl_prop_part(v.prop, part, about);
    }
    bool lit = lights_on(v), braking = v.driving && v.braking > 0.5f && absf(v.vf) > 4;
    for (int k = 0; k < 2; k++) {
        if (v.c.head[k] >= 0) acnl_prop_show_part(v.prop, v.c.head[k], lit);
        if (v.c.tail[k] >= 0) acnl_prop_show_part(v.prop, v.c.tail[k], lit && !braking);
        if (v.c.brake[k] >= 0) acnl_prop_show_part(v.prop, v.c.brake[k], braking);
    }
    if (v.c.beam >= 0) {
        acnl_prop_show_part(v.prop, v.c.beam, lit);
        /* the beam lies on flat ground but the town curves away north and south: tilt it down to follow */
        float sh = sinf(v.head), tilt = v.c.beam_len * sh * sh / (2 * ROLL_RADIUS) + 0.01f;
        float rz[12], about[12];
        m_rot_z(tilt * (v.c.front < 0 ? 1.0f : -1.0f), rz);
        const float *p = v.c.beam < MAX_PARTS ? v.pivots[v.c.beam] : v.pivots[0];
        m_about(rz, p[0], p[1], p[2], about);
        acnl_prop_part(v.prop, v.c.beam, about);
    }
    if (v.c.prompt >= 0) {
        acnl_prop_show_part(v.prop, v.c.prompt, near && !v.driving && !v.entering && !v.exiting);
        float bobm[12];
        m_translate(0, 2.0f * sinf(v.t * 4), 0, bobm);
        acnl_prop_part(v.prop, v.c.prompt, bobm);
    }
}

/* ------------------------------------------------------------------ dust */

void puff(Vehicle &v, float lx, float lz, float amount) {
    Puff &p = v.puffs[v.next_puff];
    v.next_puff = (v.next_puff + 1) % MAX_PUFFS;
    to_world(v, lx, lz, &p.x, &p.z);
    p.y = v.y + 3;
    float j = (float)((v.next_puff * 37) % 11) / 10.0f - 0.5f;
    p.vx = -v.vx * 0.12f + j * 10;
    p.vz = -v.vz * 0.12f - j * 8;
    p.vy = 12 + amount * 10;
    p.age = 0;
    p.life = 0.6f + amount * 0.5f;
    p.size = 0.5f + amount * 0.5f;
    p.on = true;
}

void puffs_tick(Vehicle &v, float dt, bool visible) {
    static const float zero[12] = {0};
    for (int i = 0; i < MAX_PUFFS; i++) {
        Puff &p = v.puffs[i];
        if (p.on) {
            p.age += dt;
            if (p.age >= p.life) p.on = false;
        }
        if (!p.on || !visible) { acnl_prop_place(p.prop, zero, 0); continue; }
        p.x += p.vx * dt; p.y += p.vy * dt; p.z += p.vz * dt;
        float k = expf(-3 * dt);
        p.vx *= k; p.vz *= k; p.vy *= expf(-1.5f * dt);
        float a = p.age / p.life, sc = p.size * (0.6f + 1.6f * a);
        float m[12] = {sc, 0, 0, p.x, 0, sc, 0, p.y, 0, 0, sc, p.z};
        float dim = lights_on(v) ? 0.42f : 1.0f;
        float tint[4] = {dim, dim, dim * 0.97f, 0.7f * (1 - a) * (1 - a)};
        acnl_prop_tint(p.prop, tint);
        acnl_prop_place(p.prop, m, 1);
    }
}

/* ------------------------------------------------------------------ the player */

void put_player(uint32_t player, float x, float y, float z, float head) {
    if (player < 0x100000) return;
    float pos[3] = {x, y, z};
    acnl_write(player + 0x14, pos, 12);
    uint16_t yaw = (uint16_t)(int)((PI / 2 - head) / TAU * 65536.0f);     /* the game's facing: 0 south, 0x4000 east */
    acnl_wr16(player + 0x34, yaw);
    float zero = 0;
    acnl_write(player + 0x40, &zero, 4);       /* not walking */
}

void seat(const Vehicle &v, float *x, float *z) { to_world(v, v.c.seat[0], v.c.seat[2], x, z); }

/* a free spot beside the car to get out to: the driver's side, the other side, the front, the back */
bool exit_spot(const Vehicle &v, float *x, float *z) {
    float side = v.c.width * 0.5f + 16, endd = v.c.length * 0.5f + 16;
    float sz = v.c.seat[2] >= 0 ? 1.0f : -1.0f;
    const float tries[4][2] = {{v.c.seat[0], sz * side}, {v.c.seat[0], -sz * side}, {(float)v.c.front * endd, 0}, {-(float)v.c.front * endd, 0}};
    for (int i = 0; i < 4; i++) {
        float wx, wz, h;
        uint8_t kind;
        to_world(v, tries[i][0], tries[i][1], &wx, &wz);
        if (field::ground(wx, wz, &h, &kind) && !field::g_blocked[kind] && absf(h - v.y) < 10 && field::clear_of_items(wx, wz, 6)) {
            *x = wx;
            *z = wz;
            return true;
        }
    }
    return false;
}

/* a parked car is solid: the player is pushed out of its footprint */
void push_player_out(const Vehicle &v, uint32_t player, const float pp[3]) {
    float lx, lz;
    to_model(v, pp[0], pp[2], &lx, &lz);
    float hl = v.c.length * 0.5f + 6, hw = v.c.width * 0.5f + 6;
    if (absf(lx) >= hl || absf(lz) >= hw) return;
    float ox = hl - absf(lx), oz = hw - absf(lz);
    if (ox < oz) lx = lx < 0 ? -hl : hl;
    else lz = lz < 0 ? -hw : hw;
    float wx, wz;
    to_world(v, lx, lz, &wx, &wz);
    float pos[3] = {wx, pp[1], wz};
    acnl_write(player + 0x14, pos, 12);
}

/* ------------------------------------------------------------------ driving */

void sounds_tick(Vehicle &v) {
    if (v.started && v.driving) {
        float pitch = 0.72f + 1.55f * minf(absf(v.vf) / v.c.max_speed, 1.2f) + 0.12f * v.throttle;
        float vol = 0.30f + 0.22f * v.throttle;
        if (v.v_engine < 0 || !acnl_sound_playing(v.v_engine)) v.v_engine = acnl_sound_play(v.snd_engine, 0.0f, pitch, 0, 1);
        acnl_sound_set(v.v_engine, vol, pitch, 0);
        float skid = clampf((absf(v.vl) - 45) / 160.0f, 0, 0.55f) + (v.braking > 0.5f && absf(v.vf) > 80 ? 0.25f : 0.0f);
        if (skid > 0.02f) {
            if (v.v_skid < 0 || !acnl_sound_playing(v.v_skid)) v.v_skid = acnl_sound_play(v.snd_skid, 0.0f, 1.0f, 0, 1);
            acnl_sound_set(v.v_skid, skid, 0.9f + absf(v.vf) / v.c.max_speed * 0.3f, 0);
        } else if (v.v_skid >= 0) { acnl_sound_stop(v.v_skid); v.v_skid = -1; }
    } else {
        if (v.v_engine >= 0) { acnl_sound_stop(v.v_engine); v.v_engine = -1; }
        if (v.v_skid >= 0) { acnl_sound_stop(v.v_skid); v.v_skid = -1; }
    }
}

void drive(Vehicle &v, const acnl_pad &pad, uint32_t pressed, float dt) {
    float sx = pad.cx / 156.0f, sy = pad.cy / 156.0f, mag = minf(sqrtf(sx * sx + sy * sy), 1.0f);
    bool gas = (pad.buttons & ACNL_BTN_A) != 0, brake = (pad.buttons & ACNL_BTN_B) != 0;
    if (pressed & ACNL_BTN_Y) acnl_sound_play(v.snd_horn, 0.8f, 1.0f, 0, 0);
    if (pressed & ACNL_BTN_X) v.lights_mode = lights_on(v) ? 2 : 1;
    float s, c;
    sincos(v.head, &s, &c);
    /* the velocity in the car's frame */
    v.vf = v.vx * c + v.vz * s;
    v.vl = -v.vx * s + v.vz * c;
    const float MAX = v.c.max_speed, ACC = v.c.accel;
    float target = 0, turn = 0, want_steer = 0;
    bool can_move = v.started && v.start_t > 0.9f;
    v.throttle = 0;
    if (can_move && mag > 0.25f) {
        float want = atan2f(-sy, sx);                       /* stick up = north = -z */
        float diff = wrap(want - v.head);
        float agility = clampf(absf(v.vf) / 80.0f, 0.15f, 1.0f) * (1.0f - 0.3f * clampf((absf(v.vf) - 0.7f * MAX) / (0.3f * MAX), 0, 1));
        if (absf(diff) > 2.3f && v.vf < 40) {                /* pulled back: reverse, the rear turning towards the stick */
            target = -0.4f * MAX * mag;
            float rdiff = wrap(want + PI - v.head);
            turn = clampf(rdiff, -v.c.turn * agility * dt, v.c.turn * agility * dt);
            want_steer = -clampf(rdiff, -0.5f, 0.5f);
        } else {
            target = MAX * mag * (absf(diff) > 1.3f ? 0.45f : 1.0f);
            turn = clampf(diff, -v.c.turn * agility * dt, v.c.turn * agility * dt);
            want_steer = clampf(diff, -0.5f, 0.5f);
        }
        v.throttle = mag;
    } else if (can_move && gas) {
        target = MAX;
        v.throttle = 1;
    }
    if (can_move && gas && target > 0) { target = MAX; v.throttle = 1; }
    v.braking = brake ? 1.0f : 0.0f;
    /* turn: the heading changes, the velocity keeps its direction (the sideways part slides off with the grip) */
    v.head = wrap(v.head + turn);
    sincos(v.head, &s, &c);
    float vf = v.vx * c + v.vz * s, vl = -v.vx * s + v.vz * c;
    if (brake) vf = approach(vf, 0, 620 * dt);
    else if ((target > 0 && vf < target) || (target < 0 && vf > target)) vf = approach(vf, target, ACC * dt * (vf * target < 0 ? 2.2f : 1.0f));
    else vf = approach(vf, target, (target == 0 ? 150.0f : 0.6f * ACC) * dt);
    float grip = brake && absf(vf) > 90 ? 1.6f : v.c.grip;    /* B in a hard turn: the tyres let go (a drift) */
    vl *= expf(-grip * dt);
    float old_vf = v.vf, old_vl = v.vl;
    v.vf = vf; v.vl = vl;
    v.vx = c * vf - s * vl;
    v.vz = s * vf + c * vl;
    /* move, sliding along whatever is in the way */
    float nx = v.x + v.vx * dt, nz = v.z + v.vz * dt, h = v.y, pt = 0, rl = 0;
    if (fits(v, nx, nz, v.head, v.y, &h, true, &pt, &rl)) { v.x = nx; v.z = nz; }
    else if (fits(v, nx, v.z, v.head, v.y, &h, true, &pt, &rl)) { v.x = nx; v.vz *= 0.3f; }
    else if (fits(v, v.x, nz, v.head, v.y, &h, true, &pt, &rl)) { v.z = nz; v.vx *= 0.3f; }
    else {
        float speed = sqrtf(v.vx * v.vx + v.vz * v.vz);
        if (speed > 70) acnl_sound_play(v.snd_door, minf(0.9f, speed / 300.0f), 0.7f, 0, 0);     /* bonk */
        v.vx *= -0.25f;
        v.vz *= -0.25f;
        if (!fits(v, v.x, v.z, v.head, v.y, &h, true, &pt, &rl)) {
            /* the turn itself would not fit: undo it */
            v.head = wrap(v.head - turn);
            fits(v, v.x, v.z, v.head, v.y, &h, false, &pt, &rl);
        }
    }
    v.y += (h - v.y) * minf(1.0f, dt * 18);
    /* the look: wheels, steering, lean (slope + acceleration + cornering), engine shake */
    v.spin += v.vf * dt / maxf(v.c.wheel_r, 1.0f);
    if (v.spin > 1000 || v.spin < -1000) v.spin = wrap(v.spin);
    v.steer_vis = approach(v.steer_vis, want_steer, 3.5f * dt);
    float accel_long = (v.vf - old_vf) / maxf(dt, 1e-3f), accel_lat = v.vf * turn / maxf(dt, 1e-3f) + (v.vl - old_vl) / maxf(dt, 1e-3f);
    /* nose up on a rising slope and when speeding up (down when braking); leaning out of turns */
    float pitch_t = pt * (float)v.c.front + clampf(accel_long / 4000.0f, -0.05f, 0.05f);
    float roll_t = -rl + clampf(accel_lat / 6000.0f, -0.06f, 0.06f) * (float)(-v.c.front);
    v.pitch += (pitch_t - v.pitch) * minf(1.0f, dt * 8);
    v.roll += (roll_t - v.roll) * minf(1.0f, dt * 8);
    v.bob = v.started ? 0.25f * sinf(v.t * 47) * (1.0f - minf(absf(v.vf) / 120.0f, 1.0f)) : 0.0f;
    /* dust from the rear wheels: on sand and dirt, when sliding, when starting hard */
    uint8_t kind = 0;
    float gh;
    field::ground(v.x, v.z, &gh, &kind);
    bool sand = kind == 0x16 || kind == 0x80 || (kind >= 0x36 && kind <= 0x3c) || kind == 0x11;
    float amount = clampf((absf(v.vl) - 40) / 140.0f, 0, 1) + (sand ? clampf(absf(v.vf) / MAX, 0, 1) : 0) +
                   (v.throttle > 0.5f && absf(v.vf) < 0.4f * MAX && absf(v.vf) > 20 ? 0.4f : 0);
    v.puff_acc += amount * 22 * dt;
    while (v.puff_acc > 1) {
        v.puff_acc -= 1;
        float rear = -(float)v.c.front * (v.c.length * 0.5f - 8);
        puff(v, rear, ((v.next_puff & 1) ? 1.0f : -1.0f) * v.c.width * 0.35f, minf(amount, 1.0f));
    }
}

/* ------------------------------------------------------------------ every frame */

void tick(uint32_t player, uint32_t buttons_unused) {
    (void)buttons_unused;
    if (!g_nv) return;
    uint32_t now = acnl_time_us();
    float dt = g_last_us ? (float)(now - g_last_us) / 1e6f : 1.0f / 30;
    g_last_us = now;
    dt = clampf(dt, 0.001f, 0.1f);
    acnl_pad pad;
    acnl_pad_read(&pad);
    uint32_t pressed = pad.buttons & ~g_prev_buttons;
    g_prev_buttons = pad.buttons;
    bool out = outdoors() && player >= 0x100000 && field::refresh();
    uint32_t mtx = out ? player_render_matrix(player) : 0;
    if (mtx) acnl_world_roll(mtx, player + 0x14, ROLL_RADIUS);
    float pp[3] = {0, 0, 0};
    if (player >= 0x100000) acnl_read(player + 0x14, pp, 12);
    bool near_any = false;
    for (int i = 0; i < g_nv; i++) {
        Vehicle &v = g_v[i];
        v.t += dt;
        bool visible = out && mtx && v.placed;
        if (out && !v.placed && (v.place_wait-- <= 0)) { place(v, pp); v.place_wait = 90; }    /* (a long search: not every frame) */
        if (!out && g_driver == i) {                        /* the scene changed under the car (a cut-scene...): park here */
            v.driving = v.entering = v.exiting = v.started = false;
            g_driver = -1;
            acnl_pad_override(0, 0, 0);
            save_spot(v);
        }
        if (!visible) { static const float zero[12] = {0}; acnl_prop_place(v.prop, zero, 0); puffs_tick(v, dt, false); sounds_tick(v); continue; }
        float dx = pp[0] - v.x, dz = pp[2] - v.z;
        float reach = maxf(v.c.length, v.c.width) * 0.5f + 26;
        bool near = g_driver < 0 && dx * dx + dz * dz < reach * reach;
        near_any |= near;
        if (g_driver < 0) {
            push_player_out(v, player, pp);
            if (near && (pressed & ACNL_BTN_A)) {             /* get in */
                g_driver = i;
                v.entering = true;
                v.anim_t = 0;
                v.ax = pp[0]; v.az = pp[2]; v.ay = pp[1];
                v.vx = v.vz = 0;
                acnl_sound_play(v.snd_door, 0.8f, 1.0f, 0, 0);
                acnl_log("vehicles: getting into %s", v.c.id);
            }
        }
        if (g_driver == i) {
            acnl_pad_override(0xFFFFFFFFu, 1 | 2, 0);          /* the game sees no controls: the player sits still */
            float sxw, szw;
            seat(v, &sxw, &szw);
            if (v.entering) {
                v.anim_t += dt;
                float k = minf(v.anim_t / 0.35f, 1.0f);
                float hop = 14 * sinf(k * PI);
                put_player(player, v.ax + (sxw - v.ax) * k, v.ay + (v.y + v.c.seat[1] - v.ay) * k + hop, v.az + (szw - v.az) * k, v.head);
                if (k >= 1) {
                    v.entering = false;
                    v.driving = true;
                    v.started = true;
                    v.start_t = 0;
                    acnl_sound_play(v.snd_start, 0.7f, 1.0f, 0, 0);
                }
            } else if (v.exiting) {
                v.anim_t += dt;
                float k = minf(v.anim_t / 0.3f, 1.0f);
                float hop = 12 * sinf(k * PI);
                put_player(player, v.ax + (v.bx - v.ax) * k, v.y + v.c.seat[1] * (1 - k) + hop * (1 - k * 0.5f), v.az + (v.bz - v.az) * k, v.head);
                if (k >= 1) {
                    v.exiting = false;
                    g_driver = -1;
                    acnl_pad_override(0, 0, 0);
                    float yaw_out = v.head;
                    put_player(player, v.bx, v.y, v.bz, yaw_out);
                    save_spot(v);
                    acnl_log("vehicles: got out of %s at %.0f, %.0f", v.c.id, v.x, v.z);
                }
            } else if (v.driving) {
                v.start_t += dt;
                drive(v, pad, pressed, dt);
                seat(v, &sxw, &szw);
                put_player(player, sxw, v.y + v.c.seat[1], szw, v.head);
                float speed = sqrtf(v.vx * v.vx + v.vz * v.vz);
                if ((pressed & ACNL_BTN_B) && speed < 18 && v.start_t > 0.4f) {     /* get out */
                    float ex, ez;
                    if (exit_spot(v, &ex, &ez)) {
                        v.driving = false;
                        v.started = false;
                        v.exiting = true;
                        v.anim_t = 0;
                        v.ax = sxw; v.az = szw;
                        v.bx = ex; v.bz = ez;
                        v.vx = v.vz = 0;
                        acnl_sound_play(v.snd_door, 0.8f, 1.0f, 0, 0);
                        acnl_sound_play(v.snd_stop, 0.5f, 1.0f, 0, 0);
                        if (v.lights_mode == 1) v.lights_mode = 0;
                    }
                }
            }
        }
        sounds_tick(v);
        place_model(v, true, near);
        puffs_tick(v, dt, true);
    }
    /* next to a car, A is for the car (the game does not pick something up or talk at the same time) */
    if (g_driver < 0) acnl_pad_override(near_any ? ACNL_BTN_A : 0, 0, 0);
}

}  // namespace veh
