// Native twin test: runs handlers of a program file with the same pretend game as acnlb/script/vm.py and prints the
// trace in the same format. Usage: vm_test PROGRAM.acs HANDLER HOUR MINUTE [BUILDING ROOM]
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <string>
#include <vector>
#include "../../plugin/script_vm.h"

struct World {
    int hour = 12, minute = 0, weekday = 2, day = 1, month = 1, year = 2026;
    std::string building, room;
    uint32_t seed = 1;
    int32_t regs[16] = {0};
    std::vector<int32_t> vars = std::vector<int32_t>(64, 0);
    std::vector<uint8_t> mem = std::vector<uint8_t>(0x2000, 0);   // addresses 0x1000..0x2fff
    const sv::Program *prog;
};
static std::string S(const sv::Program &p, int i) { return std::string((const char *)p.str[i], p.slen[i]); }
static uint32_t rnd(World &w) { w.seed = (w.seed * 1103515245u + 12345u) & 0x7FFFFFFF; return w.seed >> 8; }

static bool call(void *ctx, int id, const int32_t *a, int n, int32_t *ret, bool *has) {
    World &w = *(World *)ctx;
    const sv::Program &p = *w.prog;
    *has = false;
    auto R = [&](int32_t v) { *ret = v; *has = true; return true; };
    switch (id) {
    case 0: return R(w.hour); case 1: return R(w.minute); case 2: return R(w.weekday); case 3: return R(w.day);
    case 4: return R(w.month); case 5: return R(w.year);
    case 6: return R(w.building == S(p, a[0]));
    case 7: return R(w.building == S(p, a[0]) && w.room == S(p, a[1]));
    case 8: return R((int32_t)(rnd(w) % 100) < a[0]);
    case 9: return R(a[0] > 0 ? (int32_t)(rnd(w) % (uint32_t)a[0]) : 0);
    case 10: return R(w.vars[a[0]]);
    case 11: w.vars[a[0]] = a[1]; return true;
    case 12: if (a[1]) printf("log('%s', %d)\n", S(p, a[0]).c_str(), a[1]); else printf("log('%s')\n", S(p, a[0]).c_str()); return true;
    case 13: printf("wear(%s, %s)\n", S(p, a[0]).c_str(), S(p, a[1]).c_str()); return true;
    case 14: printf("wear_default(%s)\n", S(p, a[0]).c_str()); return true;
    case 15: printf("variant_on(%s)\n", S(p, a[0]).c_str()); return true;
    case 16: printf("variant_off(%s)\n", S(p, a[0]).c_str()); return true;
    case 17: printf("hide_actor()\n"); return true;
    case 18: printf("become(0x%x)\n", (unsigned)a[0]); return true;
    case 19: printf("place_player(%d, %d, %d)\n", a[0], a[1], a[2]); return true;
    case 32: printf("add_actor(0x%x, %d, %d)\n", (unsigned)a[0], a[1], a[2]); return true;
    case 29: printf("place_actor(%d, %d)\n", a[0], a[1]); return true;
    case 20: case 21: case 22: {
        int nb = id == 20 ? 1 : id == 21 ? 2 : 4;
        if (a[0] < 0x1000 || a[0] + nb > 0x3000) return false;
        uint32_t v = 0; for (int i = 0; i < nb; i++) v |= (uint32_t)w.mem[a[0] - 0x1000 + i] << (8 * i);
        return R((int32_t)v);
    }
    case 23: case 24: case 25: {
        int nb = id == 23 ? 1 : id == 24 ? 2 : 4;
        if (a[0] < 0x1000 || a[0] + nb > 0x3000) return false;
        for (int i = 0; i < nb; i++) w.mem[a[0] - 0x1000 + i] = (uint8_t)((uint32_t)a[1] >> (8 * i));
        printf("write%d(0x%x, %d)\n", nb * 8, (unsigned)a[0], a[1]);
        return true;
    }
    case 26: return R(w.regs[a[0] & 15]);
    case 27: w.regs[a[0] & 15] = a[1]; printf("set_reg(%d, %d)\n", a[0] & 15, a[1]); return true;
    case 28: printf("skip_call()\n"); return true;
    }
    return false;
}

int main(int argc, char **argv) {
    if (argc == 3 && !strcmp(argv[1], "clock")) {      // clock MS: calendar fields of a game clock value
        int32_t y, mo, d, wd, h, mi;
        sv::civil(strtoull(argv[2], nullptr, 10), &y, &mo, &d, &wd, &h, &mi);
        printf("%d %d %d %d %d %d\n", y, mo, d, wd, h, mi);
        return 0;
    }
    if (argc < 5) return 2;
    FILE *f = fopen(argv[1], "rb");
    if (!f) return 2;
    std::vector<uint8_t> blob(1 << 16);
    int len = (int)fread(blob.data(), 1, blob.size(), f);
    fclose(f);
    static sv::Program p;
    if (!sv::parse(blob.data(), len, p)) { printf("PARSE ERROR\n"); return 3; }
    World w;
    w.prog = &p;
    int hi = atoi(argv[2]);
    w.hour = atoi(argv[3]); w.minute = atoi(argv[4]);
    if (argc > 5) w.building = argv[5];
    if (argc > 6) w.room = argv[6];
    const sv::Handler &h = p.h[hi];
    sv::Host host{&w, call};
    int rc = sv::run(h.code, h.len, h.nlocals, host);
    if (rc) printf("ERROR %d\n", rc);
    return 0;
}
