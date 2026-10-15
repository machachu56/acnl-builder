/* The script interpreter: runs the bytecode written by acnlb/script/compiler.py (format in compiler.Program.encode).
   Portable on purpose (no SDK, no libc): the plugin includes it, and tests/vm_native compiles it natively and checks
   it against acnlb/script/vm.py, the Python twin. Keep the two in step.

   Values are 32-bit integers. Text never exists at run time: it was turned into string / variable indexes. A
   handler runs to its end (or an error) with a step budget, so a script can never hang the game. */
#ifndef ACNLB_SCRIPT_VM_H
#define ACNLB_SCRIPT_VM_H
#include <stdint.h>
#ifndef ACNL_MOD_H            /* the plugin has no libc: acnl_mod.h declares memcpy, memcmp, strlen ... */
#include <string.h>
#endif

namespace sv {

enum { OK = 0, ERR_BUDGET = 1, ERR_STACK = 2, ERR_BAD_OP = 3, ERR_DIV = 4, ERR_HOST = 5 };
const int BUDGET = 20000, STACK = 64, MAX_LOCALS = 32, MAX_STR = 256, MAX_HANDLERS = 64, MAX_CODE_BYTES = 24000;
enum Kind { K_ENTER = 1, K_LEAVE = 2, K_ACTOR = 3, K_CALL = 4, K_ROOM = 5 };

struct Host {
    void *ctx;
    /* a built-in: args in order; return false on failure; set *has_ret when a value is pushed */
    bool (*call)(void *ctx, int id, const int32_t *args, int n, int32_t *ret, bool *has_ret);
};

inline int32_t floor_div(int32_t a, int32_t b) {
    int64_t q = (int64_t)a / b, r = (int64_t)a % b;
    if (r != 0 && ((r < 0) != (b < 0))) q--;
    return (int32_t)q;
}
inline int32_t floor_mod(int32_t a, int32_t b) {
    int64_t r = (int64_t)a % b;
    if (r != 0 && ((r < 0) != (b < 0))) r += b;
    return (int32_t)r;
}
inline uint16_t rd16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
inline int32_t rd32(const uint8_t *p) { return (int32_t)((uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24)); }

inline int run(const uint8_t *code, int len, int nlocals, const Host &host) {
    int32_t st[STACK];
    int sp = 0, pc = 0;
    int32_t loc[MAX_LOCALS];
    for (int i = 0; i < MAX_LOCALS; i++) loc[i] = 0;
    if (nlocals > MAX_LOCALS) return ERR_BAD_OP;
    for (int steps = 0;; steps++) {
        if (steps > BUDGET) return ERR_BUDGET;
        if (pc >= len) return OK;
        uint8_t op = code[pc++];
        switch (op) {
        case 0x01: if (sp >= STACK || pc + 4 > len) return ERR_STACK; st[sp++] = rd32(code + pc); pc += 4; break;
        case 0x02: if (sp >= STACK || code[pc] >= MAX_LOCALS) return ERR_STACK; st[sp++] = loc[code[pc++]]; break;
        case 0x03: if (sp < 1 || code[pc] >= MAX_LOCALS) return ERR_STACK; loc[code[pc++]] = st[--sp]; break;
        case 0x06: {
            if (sp < 2) return ERR_STACK;
            int32_t b = st[--sp], a = st[--sp];
            uint8_t k = code[pc++];
            int32_t r = 0;
            switch (k) {
            case 0: r = (int32_t)((uint32_t)a + (uint32_t)b); break;
            case 1: r = (int32_t)((uint32_t)a - (uint32_t)b); break;
            case 2: r = (int32_t)((uint32_t)a * (uint32_t)b); break;
            case 3: if (b == 0) return ERR_DIV; r = floor_div(a, b); break;
            case 4: if (b == 0) return ERR_DIV; r = floor_mod(a, b); break;
            case 5: r = a == b; break;
            case 6: r = a != b; break;
            case 7: r = a < b; break;
            case 8: r = a <= b; break;
            case 9: r = a > b; break;
            case 10: r = a >= b; break;
            case 11: r = a & b; break;
            case 12: r = a | b; break;
            case 13: r = a ^ b; break;
            case 14: r = (int32_t)((uint32_t)a << (b & 31)); break;
            case 15: r = a >> (b & 31); break;
            default: return ERR_BAD_OP;
            }
            st[sp++] = r;
            break;
        }
        case 0x07: if (sp < 1) return ERR_STACK; st[sp - 1] = !st[sp - 1]; break;
        case 0x08: if (sp < 1) return ERR_STACK; st[sp - 1] = (int32_t)(0u - (uint32_t)st[sp - 1]); break;
        case 0x09: pc = rd16(code + pc); break;
        case 0x0A: { int t = rd16(code + pc); pc += 2; if (sp < 1) return ERR_STACK; if (!st[--sp]) pc = t; break; }
        case 0x0F: { int t = rd16(code + pc); pc += 2; if (sp < 1) return ERR_STACK; if (st[--sp]) pc = t; break; }
        case 0x0C: if (sp < 1) return ERR_STACK; sp--; break;
        case 0x0D: return OK;
        case 0x0E: if (sp < 1 || sp >= STACK) return ERR_STACK; st[sp] = st[sp - 1]; sp++; break;
        case 0x0B: {
            int id = code[pc], n = code[pc + 1];
            pc += 2;
            if (sp < n) return ERR_STACK;
            sp -= n;
            int32_t ret = 0;
            bool has = false;
            if (!host.call(host.ctx, id, st + sp, n, &ret, &has)) return ERR_HOST;
            if (has) { if (sp >= STACK) return ERR_STACK; st[sp++] = ret; }
            break;
        }
        default: return ERR_BAD_OP;
        }
    }
}

/* the game's clock: milliseconds since 1900-01-01 (a Monday), local time -> calendar fields */
inline void civil(uint64_t ms, int32_t *y, int32_t *mo, int32_t *d, int32_t *wd, int32_t *h, int32_t *mi) {
    uint64_t secs = ms / 1000ull, days = secs / 86400ull;
    uint32_t sod = (uint32_t)(secs % 86400ull);
    *wd = (int32_t)(days % 7ull);
    int64_t z = (int64_t)days - 25567 + 719468;    /* days since 1970 -> civil date (Howard Hinnant) */
    int64_t era = (z >= 0 ? z : z - 146096) / 146097;
    int64_t doe = z - era * 146097, yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    int64_t yy = yoe + era * 400, doy = doe - (365 * yoe + yoe / 4 - yoe / 100), mp = (5 * doy + 2) / 153;
    int64_t dd = doy - (153 * mp + 2) / 5 + 1, mm = mp < 10 ? mp + 3 : mp - 9;
    *y = (int32_t)(yy + (mm <= 2)); *mo = (int32_t)mm; *d = (int32_t)dd;
    *h = (int32_t)(sod / 3600); *mi = (int32_t)(sod / 60 % 60);
}

/* ---- a program file */
struct Handler { uint8_t kind; uint16_t s1, s2; uint32_t num; uint16_t nlocals, len; const uint8_t *code; };
struct Program {
    int nstr, nhandlers, nvars;
    const uint8_t *str[MAX_STR];
    uint8_t slen[MAX_STR];
    Handler h[MAX_HANDLERS];
    bool ok;
};

inline bool parse(const uint8_t *b, int len, Program &p) {
    p.ok = false; p.nstr = p.nhandlers = p.nvars = 0;
    if (len < 10 || memcmp(b, "ACS1", 4) != 0) return false;
    int o = 4;
    int n = rd16(b + o); o += 2;
    if (n > MAX_STR) return false;
    for (int i = 0; i < n; i++) {
        if (o >= len) return false;
        p.slen[i] = b[o]; p.str[i] = b + o + 1; o += 1 + b[o];
    }
    p.nstr = n;
    if (o + 4 > len) return false;
    p.nvars = rd16(b + o); int nh = rd16(b + o + 2); o += 4;
    if (nh > MAX_HANDLERS) return false;
    for (int i = 0; i < nh; i++) {
        if (o + 13 > len) return false;
        Handler &h = p.h[i];
        h.kind = b[o]; h.s1 = rd16(b + o + 1); h.s2 = rd16(b + o + 3); h.num = (uint32_t)rd32(b + o + 5);
        h.nlocals = rd16(b + o + 9); h.len = rd16(b + o + 11);
        o += 13;
        if (o + h.len > len) return false;
        h.code = b + o; o += h.len;
    }
    p.nhandlers = nh;
    p.ok = true;
    return true;
}

inline bool str_is(const Program &p, int idx, const char *s) {
    if (idx < 0 || idx >= p.nstr) return false;
    int n = (int)strlen(s);
    return p.slen[idx] == n && memcmp(p.str[idx], s, (size_t)n) == 0;
}

}  // namespace sv
#endif
