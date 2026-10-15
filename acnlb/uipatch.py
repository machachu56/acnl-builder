"""Patches of the game's 2D layouts: the town-map icon sheets and the title-screen logo."""
import struct

from . import env

env.setup_path()
from modkit import darc, etc1  # noqa: E402
from modkit.paint import Canvas  # noqa: E402

MAP = "/Layout/Menu/map_village.arc"
MAP_CELL = (16, 32)              # top-left of the police station's icon in tc_mpi_A_00/01 (16 x 16 cells)
TITLE = "/Layout/Title/opng_titl.arc"
TITLE_TEX = 512


def icon_rows(shape, fill, shine, outline, size=16):
    """16 x 16 map icon (rows of RGBA), drawn at 4x and reduced"""
    c = Canvas(size * 4, size * 4, (0, 0, 0, 0))
    k = size * 4
    if shape == "heart":
        c.heart(k // 2, k // 2 + 1, k, outline)
        c.heart(k // 2, k // 2 + 1, k * 0.78, fill)
        c.circle(k * 0.33, k * 0.33, k * 0.1, shine)
    elif shape == "star":
        import math
        for sz, col in ((k * 1.05, outline), (k * 0.82, fill)):
            pts = []
            for i in range(10):
                a = -math.pi / 2 + math.pi * i / 5
                r = sz / 2 * (1 if i % 2 == 0 else 0.45)
                pts.append((k / 2 + r * math.cos(a), k / 2 + 2 + r * math.sin(a)))
            c.polygon(pts, col)
        c.circle(k * 0.42, k * 0.4, k * 0.07, shine)
    elif shape == "house":
        c.polygon([(k * 0.5, k * 0.04), (k * 0.98, k * 0.46), (k * 0.02, k * 0.46)], outline)
        c.rect((int(k * 0.12), int(k * 0.42), int(k * 0.88), int(k * 0.96)), outline)
        c.polygon([(k * 0.5, k * 0.14), (k * 0.86, k * 0.46), (k * 0.14, k * 0.46)], fill)
        c.rect((int(k * 0.2), int(k * 0.46), int(k * 0.8), int(k * 0.88)), fill)
        c.rect((int(k * 0.42), int(k * 0.6), int(k * 0.58), int(k * 0.88)), outline)
    else:
        c.circle(k / 2, k / 2, k * 0.45, outline)
        c.circle(k / 2, k / 2, k * 0.36, fill)
    return c.downscale(4).rows()


ICON_ROWS = 8                       # the sheet is made 4 cells wide and this many tall: 32 icons instead of 16


def _kind_keys(rows):
    """key frames (frame, value, slope) of the U and V tracks that map a "kind" frame to a cell of the sheet"""
    s = 1.0 / rows
    u = [(0.0, 0.0, 0.25)]
    for r in range(rows):
        u.append((4.0 * r + 3, 0.75, 0.25))
        if r < rows - 1:
            u += [(4.0 * r + 3, 0.75, -0.75), (4.0 * r + 4, 0.0, -0.75), (4.0 * r + 4, 0.0, 0.25)]
    v = []
    for r in range(rows - 1):
        v += [(4.0 * r + 3, r * s, 0.0), (4.0 * r + 3, r * s, s), (4.0 * r + 4, (r + 1) * s, s), (4.0 * r + 4, (r + 1) * s, 0.0)]
    return u, v


def expand_icon_sheet(data, rows=ICON_ROWS):
    """map_village.arc with its building-icon sheet (tc_mpi_A) taller: more cells for added buildings' icons.
    The sheet, the picture pane's texture coordinates and the animation that turns an icon's "kind" into a
    cell are changed together. Idempotent."""
    files = darc.read(data)
    w, h, fmt, _ = etc1.clim_info(files["timg/tc_mpi_A_00.bclim"])
    if h >= 16 * rows:
        return data
    new = {}
    for n in ("tc_mpi_A_00", "tc_mpi_A_01"):
        path = "timg/%s.bclim" % n
        img = [list(r) for r in etc1.clim_decode(files[path])]
        img += [[(0, 0, 0, 0)] * w for _ in range(16 * rows - len(img))]
        new[path] = clim_new(files[path], img, fmt)
    lyt = bytearray(files["blyt/map_icon_00.bclyt"])
    at = lyt.index(b"pic1")
    size = struct.unpack_from("<I", lyt, at + 4)[0]
    tc = at + size - 32                                        # four (u, v) corners: the last two have v = 1/4
    for k in (5, 7):
        struct.pack_into("<f", lyt, tc + 4 * k, 1.0 / rows)
    new["blyt/map_icon_00.bclyt"] = bytes(lyt)
    a = files["anim/map_icon_00_kind.bclan"]
    p = a.index(b"CLTS")
    u, v = _kind_keys(rows)
    chunk = b"CLTS" + struct.pack("<III", 2, 16, 16 + 12 + 12 * len(u))
    for tgt, keys in ((0, u), (1, v)):
        chunk += bytes((0, tgt, 2, 0)) + struct.pack("<II", len(keys), 12)
        for k in keys:
            chunk += struct.pack("<3f", *k)
    out = bytearray(a[:p] + chunk)
    pai = out.index(b"pai1")
    struct.pack_into("<I", out, pai + 4, len(out) - pai)
    struct.pack_into("<H", out, pai + 8, 4 * rows - 1)
    struct.pack_into("<I", out, 0x0C, len(out))
    new["anim/map_icon_00_kind.bclan"] = bytes(out)
    return darc.replace(data, new)


def frame_cell(frame):
    """top-left pixel of an icon-sheet frame (4 x 4 cells of 16 px, row by row)"""
    return (frame % 4) * 16, (frame // 4) * 16


def patch_map(data, cells, at=None):
    """cells {sheet name ('tc_mpi_A_00'/'tc_mpi_A_01'): 16x16 rows} drawn into the police station's cell (or `at`)"""
    files = darc.read(data)
    new = {}
    for name, cell in cells.items():
        path = "timg/%s.bclim" % name
        img = [list(r) for r in (etc1.clim_decode(files[path]) if path not in new else etc1.clim_decode(new[path]))]
        x0, y0 = at or MAP_CELL
        for y in range(16):
            for x in range(16):
                img[y0 + y][x0 + x] = cell[y][x]
        new[path] = etc1.clim_encode(files[path], img)
    return darc.replace(data, new)


# ---------------------------------------------------------------- title logo

def clim_new(template, img, fmt=9):
    h, w = len(img), len(img[0])
    px = etc1.encode_raw(img, fmt)
    footer = bytearray(template[-0x28:])
    struct.pack_into("<I", footer, 0x0C, len(px) + 0x28)
    struct.pack_into("<HHII", footer, 0x14 + 8, w, h, fmt, len(px))
    return px + bytes(footer)


def hide_panes(data, names=None):
    out = bytearray(data)
    off = struct.unpack_from("<H", out, 6)[0]
    first = True
    while off < len(out):
        tag = bytes(out[off:off + 4])
        size = struct.unpack_from("<I", out, off + 4)[0]
        if tag in (b"pan1", b"pic1", b"bnd1", b"wnd1", b"txt1"):
            name = bytes(out[off + 8 + 4:off + 8 + 0x14]).split(b"\0")[0].decode()
            if (names is None and not first) or (names is not None and name in names):
                out[off + 8] &= ~1
                out[off + 8 + 2] = 0
            first = False
        off += size
    return bytes(out)


def set_pane(data, name, x, y, w, h):
    out = bytearray(data)
    off = struct.unpack_from("<H", out, 6)[0]
    while off < len(out):
        tag = bytes(out[off:off + 4])
        size = struct.unpack_from("<I", out, off + 4)[0]
        if tag == b"pic1" and bytes(out[off + 12:off + 28]).split(b"\0")[0].decode() == name:
            struct.pack_into("<ff", out, off + 8 + 0x1c, x, y)
            struct.pack_into("<ff", out, off + 8 + 0x40, w, h)
            return bytes(out)
        off += size
    raise KeyError(name)


LOGO_POS = (0, 14)
LOGO_SIZE = 300


def patch_title(data, rows):
    """the title screen's logo replaced by `rows` (512 x 512 RGBA, top row first)"""
    files = darc.read(data)
    new = {"timg/my_op_base_B.bclim": clim_new(files["timg/my_op_base_B.bclim"], rows)}
    logo = files["blyt/opng_titl_logo.bclyt"]
    logo = hide_panes(logo, {"N_title", "N_title_sh", "N_leaf", "N_amiibo_00", "P_base_T_00", "P_op_base_C_00", "P_tm"})
    logo = set_pane(logo, "P_op_base_B_00", LOGO_POS[0], LOGO_POS[1], LOGO_SIZE, LOGO_SIZE)
    new["blyt/opng_titl_logo.bclyt"] = logo
    new["blyt/opng_titl_logo_s.bclyt"] = hide_panes(files["blyt/opng_titl_logo_s.bclyt"])
    return darc.replace(data, new)


def highlight_rows(rows):
    """the icon as shown when selected on the map: tinted magenta with a white outline (like the game's own)"""
    h, w = len(rows), len(rows[0])
    a = [[rows[y][x][3] if len(rows[y][x]) > 3 else 255 for x in range(w)] for y in range(h)]
    out = [[(0, 0, 0, 0)] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            near = any(0 <= y + j < h and 0 <= x + i < w and a[y + j][x + i] > 127 for j in (-1, 0, 1) for i in (-1, 0, 1))
            if a[y][x] > 127:
                r, g, b = rows[y][x][:3]
                out[y][x] = ((r + 255) // 2, g // 2, (b + 255) // 2, 255)
            elif near:
                out[y][x] = (255, 255, 255, 255)
    return out
