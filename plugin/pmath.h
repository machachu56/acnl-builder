/* Small float math for the plugin (no libm in a freestanding WebAssembly module). */
#pragma once

namespace pm {

const float PI = 3.14159265f, TAU = 6.28318531f;

inline float absf(float v) { return v < 0 ? -v : v; }
inline float minf(float a, float b) { return a < b ? a : b; }
inline float maxf(float a, float b) { return a > b ? a : b; }
inline float clampf(float v, float lo, float hi) { return v < lo ? lo : v > hi ? hi : v; }
inline float sqrtf(float v) { return v > 0 ? __builtin_sqrtf(v) : 0.0f; }
inline float floorf(float v) { return __builtin_floorf(v); }
inline float wrap(float a) { a -= TAU * floorf((a + PI) / TAU); return a; }      /* -pi .. pi */

inline void sincos(float a, float *s, float *c) {
    a = wrap(a);
    /* sin on [-pi/2, pi/2], folded */
    float x = a, sgn = 1;
    if (x > PI / 2) x = PI - x;
    else if (x < -PI / 2) x = -PI - x;
    float x2 = x * x;
    *s = x * (1 - x2 / 6 * (1 - x2 / 20 * (1 - x2 / 42 * (1 - x2 / 72))));
    float y = a + PI / 2;                       /* cos a = sin(a + pi/2) */
    y = wrap(y);
    if (y > PI / 2) y = PI - y;
    else if (y < -PI / 2) y = -PI - y;
    float y2 = y * y;
    *c = sgn * y * (1 - y2 / 6 * (1 - y2 / 20 * (1 - y2 / 42 * (1 - y2 / 72))));
}
inline float sinf(float a) { float s, c; sincos(a, &s, &c); return s; }
inline float cosf(float a) { float s, c; sincos(a, &s, &c); return c; }

inline float atan2f(float y, float x) {
    float ax = absf(x), ay = absf(y);
    if (ax < 1e-12f && ay < 1e-12f) return 0;
    float a = ax > ay ? ay / ax : ax / ay, s2 = a * a;
    float r = ((-0.0464964749f * s2 + 0.15931422f) * s2 - 0.327622764f) * s2 * a + a;
    if (ay > ax) r = PI / 2 - r;
    if (x < 0) r = PI - r;
    return y < 0 ? -r : r;
}

inline float expf(float x) {                    /* good to ~1e-4 relative for |x| < 20 */
    if (x < -20) return 0;
    if (x > 20) x = 20;
    int k = (int)floorf(x * 1.44269504f + 0.5f);
    float r = x - k * 0.69314718f;
    float p = 1 + r * (1 + r * (0.5f + r * (1.0f / 6 + r * (1.0f / 24 + r * (1.0f / 120)))));
    float s = 1;
    if (k > 0) for (int i = 0; i < k; i++) s *= 2;
    else for (int i = 0; i < -k; i++) s *= 0.5f;
    return p * s;
}

/* approach v towards target by at most step */
inline float approach(float v, float target, float step) {
    return v < target ? minf(target, v + step) : maxf(target, v - step);
}

/* 3x4 row-major matrices */
inline void m_identity(float m[12]) { for (int i = 0; i < 12; i++) m[i] = (i % 5 == 0) ? 1.0f : 0.0f; }
inline void m_mul(const float a[12], const float b[12], float o[12]) {
    float t[12];
    for (int r = 0; r < 3; r++)
        for (int c = 0; c < 4; c++)
            t[r * 4 + c] = a[r * 4] * b[c] + a[r * 4 + 1] * b[4 + c] + a[r * 4 + 2] * b[8 + c] + (c == 3 ? a[r * 4 + 3] : 0);
    for (int i = 0; i < 12; i++) o[i] = t[i];
}
inline void m_rot_x(float a, float m[12]) { float s, c; sincos(a, &s, &c); m_identity(m); m[5] = c; m[6] = -s; m[9] = s; m[10] = c; }
inline void m_rot_y(float a, float m[12]) { float s, c; sincos(a, &s, &c); m_identity(m); m[0] = c; m[2] = s; m[8] = -s; m[10] = c; }
inline void m_rot_z(float a, float m[12]) { float s, c; sincos(a, &s, &c); m_identity(m); m[0] = c; m[1] = -s; m[4] = s; m[5] = c; }
inline void m_translate(float x, float y, float z, float m[12]) { m_identity(m); m[3] = x; m[7] = y; m[11] = z; }
/* rotation about an axis through point p: T(p) R T(-p) */
inline void m_about(const float r[12], float px, float py, float pz, float o[12]) {
    float a[12], b[12], t[12];
    m_translate(px, py, pz, a);
    m_translate(-px, -py, -pz, b);
    m_mul(a, r, t);
    m_mul(t, b, o);
}

}  // namespace pm
