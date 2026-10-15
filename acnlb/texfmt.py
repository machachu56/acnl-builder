"""Texture pixels of CGFX (.bcres) models <-> RGBA rows (PICA200 formats, tiled, mip chains)."""
import struct

from . import env

env.setup_path()
from modkit import cgfx, etc1  # noqa: E402

_C = etc1.CLIM_FORMATS


def _e_l8(p): return bytes(((p[0] * 3 + p[1] * 6 + p[2]) // 10,))
def _e_a8(p): return bytes((p[3],))
def _e_rgb8(p): return bytes((p[2], p[1], p[0]))


# CGFX/PICA format -> (bits per pixel, decode, encode)
RAW = {0: _C[9], 1: (24, _C[6][1], _e_rgb8), 2: _C[7], 3: _C[5], 4: _C[8], 5: _C[3],
       7: (8, _C[0][1], _e_l8), 8: (8, _C[1][1], _e_a8)}
NAMES = cgfx.FORMATS


def supported(fmt):
    return fmt in RAW or fmt in (12, 13)


def bits(fmt):
    return {12: 4, 13: 8}.get(fmt) or RAW[fmt][0]


def level_size(w, h, fmt):
    return (max(w, 8) * max(h, 8) * bits(fmt)) // 8 if fmt not in (12, 13) else max(w, 8) * max(h, 8) * bits(fmt) // 8


def decode(data, w, h, fmt):
    """tiled pixels -> rows of (r, g, b, a), top row first"""
    if fmt in (12, 13):
        return etc1.decode(data, w, h, fmt == 13)
    return etc1.decode_raw(data, w, h, {0: 9, 1: 6, 2: 7, 3: 5, 4: 8, 5: 3, 7: 0, 8: 1}[fmt])


def decode_texture(data, t):
    """rows of RGBA for a cgfx.Texture of a file (mip level 0)"""
    if not supported(t.fmt):
        raise ValueError("texture format %s is not supported yet" % NAMES.get(t.fmt, t.fmt))
    return decode(data[t.data_off:t.data_off + t.size], t.w, t.h, t.fmt)


def _encode_level(img, fmt):
    if fmt in (12, 13):
        return etc1.encode(img, fmt == 13)
    bpp, _, enc = RAW[fmt]
    h, w = len(img), len(img[0])
    n = bpp // 8
    out = bytearray(w * h * n)
    for ty in range(0, h, 8):
        for tx in range(0, w, 8):
            base = ((ty // 8) * (w // 8) + tx // 8) * 64
            for y in range(8):
                for x in range(8):
                    o = (base + etc1._morton(x, y)) * n
                    out[o:o + n] = enc(tuple(int(c) for c in img[ty + y][tx + x]))
    return bytes(out)


def encode(img, fmt, mips=1):
    out = b""
    for _ in range(mips):
        out += _encode_level(img, fmt)
        img = etc1.downscale(img)
    return out


def pad8(img):
    """ETC1 and the tiled formats need sizes that are multiples of 8"""
    h, w = len(img), len(img[0])
    nh, nw = -(-h // 8) * 8, -(-w // 8) * 8
    if (nw, nh) == (w, h):
        return img
    return [[img[min(y, h - 1)][min(x, w - 1)] for x in range(nw)] for y in range(nh)]


def replacement(img, t):
    """cgfx.rebuild texture entry (w, h, mips, pixels) for new pixels of texture `t`. The format stays the game's own, so no
    format is given (cgfx.rebuild would then look for a GL format it only knows for ETC1)."""
    img = pad8(img)
    h, w = len(img), len(img[0])
    mips = t.mips
    while mips > 1 and (w >> (mips - 1) < 8 or h >> (mips - 1) < 8):
        mips -= 1
    if t.fmt in (12, 13):
        return (w, h, mips, encode_cached(img, t.fmt, mips))
    return (w, h, 1, encode_cached(img, t.fmt, 1))


def _key(img, *parts):
    import hashlib
    h = hashlib.sha1(repr(parts).encode())
    for row in img:
        h.update(bytes(v for p in row for v in p[:4]))
    return h.hexdigest()


def encode_cached(img, fmt, mips=1):
    """encode(), remembering the result on disk: ETC1 in pure Python takes seconds for a big texture"""
    import os
    path = os.path.join(env.CACHE, "tex", _key(img, fmt, mips) + ".bin")
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        pass
    data = encode(img, fmt, mips)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "wb") as f:
            f.write(data)
        os.replace(path + ".tmp", path)
    except OSError:
        pass
    return data
