// Geometry of interior items on the 2D plan (world units: 32 per tile, x east, z south).
export const T = 32, GRID = 16, WORLD = GRID * T;

const rot2 = (x, z, rot) => { const a = (rot || 0) * Math.PI / 180, c = Math.round(Math.cos(a) * 1e6) / 1e6, s = Math.round(Math.sin(a) * 1e6) / 1e6; return [x * c + z * s, -x * s + z * c]; };

// The entrance of a scene (mirrors acnlb/interior.py entrance_layout): the two door tiles lie in a strip along one edge,
// the exit tiles behind them. bounds = the playable area [x0, y0, x1, y1].
export const SIDES = [['south', 'South (the front, like the original)'], ['east', 'East (right)'], ['west', 'West (left)'], ['north', 'North (the back wall)']];
export function entrance(sc) {
  const side = sc.entrance || 'south';
  let p = sc.entrance_at;
  if (side === 'south' && p == null) return { side, door: sc.door || [[7, 14], [8, 14]], exit: sc.exit || [[7, 15], [8, 15]], bounds: [0, 0, GRID - 1, 13] };
  const max = side === 'south' || side === 'north' ? GRID - 2 : GRID - 4;
  p = p == null ? 7 : Math.max(0, Math.min(max, Math.round(p)));
  switch (side) {
    case 'south': return { side, door: [[p, 14], [p + 1, 14]], exit: [[p, 15], [p + 1, 15]], bounds: [0, 0, GRID - 1, 13] };
    case 'north': return { side, door: [[p, 1], [p + 1, 1]], exit: [[p, 0], [p + 1, 0]], bounds: [0, 2, GRID - 1, 13] };
    case 'east': return { side, door: [[14, p], [14, p + 1]], exit: [[15, p], [15, p + 1]], bounds: [0, 0, 13, 13] };
    default: return { side: 'west', door: [[1, p], [1, p + 1]], exit: [[0, p], [0, p + 1]], bounds: [2, 0, GRID - 1, 13] };
  }
}
export const inBounds = (b, x, y) => x >= b[0] && x <= b[2] && y >= b[1] && y <= b[3];

// axis-aligned bounding box [x0, z0, x1, z1] of an item
export function bbox(it) {
  switch (it.type) {
    case 'box': case 'flat': return [it.x0, it.z0, it.x1, it.z1];
    case 'cyl': return [it.cx - it.r, it.cz - it.r, it.cx + it.r, it.cz + it.r];
    case 'lamp': return [it.x - 12, it.z - 12, it.x + 12, it.z + 12];
    case 'extrude': { const s = it.size || 60; const rx = s / 2, rz = it.shape === 'oval' ? s / 4 : s / 2; return [it.cx - rx, it.cz - rz, it.cx + rx, it.cz + rz]; }
    case 'stand': return [it.x - 13, it.z - 13, it.x + 13, it.z + 13];
    case 'bed': return rotBox(it.x, it.z, [-28, -26, 28, 28], it.rot);
    case 'game': { const [w, d] = it.fp || [32, 32]; return rotBox(it.x, it.z, [-w / 2, -d / 2, w / 2, d / 2], it.rot); }
    case 'custom': { const [w, d] = it.fp || [32, 32], k = it.scale || 1; return rotBox(it.x, it.z, [-w * k / 2, -d * k / 2, w * k / 2, d * k / 2], it.rot); }
    case 'quad': { const xs = it.pts.map((p) => p[0]), zs = it.pts.map((p) => p[2]); return [Math.min(...xs) - 1, Math.min(...zs) - 1, Math.max(...xs) + 1, Math.max(...zs) + 1]; }
    case 'wallquad': return [Math.min(it.a[0], it.b[0]) - 2, Math.min(it.a[1], it.b[1]) - 2, Math.max(it.a[0], it.b[0]) + 2, Math.max(it.a[1], it.b[1]) + 2];
    default: return [0, 0, 8, 8];
  }
}
function rotBox(x, z, b, rot) {
  const cs = [[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]].map(([a, c]) => rot2(a, c, rot));
  return [x + Math.min(...cs.map((p) => p[0])), z + Math.min(...cs.map((p) => p[1])), x + Math.max(...cs.map((p) => p[0])), z + Math.max(...cs.map((p) => p[1]))];
}
export const center = (it) => { const b = bbox(it); return [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2]; };

const offsets = new WeakMap();      // distance an item has been moved since it was last aligned to the tile grid
export function move(it, dx, dz) {
  const f = (o, ks) => ks.forEach((k) => { o[k] = Math.round((o[k] + (k.includes('z') || k === 'z' || k === 'cz' ? dz : dx)) * 100) / 100; });
  switch (it.type) {
    case 'box': case 'flat': f(it, ['x0', 'x1', 'z0', 'z1']); break;
    case 'cyl': case 'extrude': f(it, ['cx', 'cz']); break;
    case 'lamp': case 'stand': case 'bed': case 'game': case 'custom': f(it, ['x', 'z']); break;
    case 'quad': it.pts = it.pts.map((p) => [p[0] + dx, p[1], p[2] + dz]); break;
    case 'wallquad': it.a = [it.a[0] + dx, it.a[1] + dz]; it.b = [it.b[0] + dx, it.b[1] + dz]; break;
  }
  if (it.block) {                  // the blocked tiles follow in whole tiles
    const o = offsets.get(it) || [0, 0], n = [o[0] + dx, o[1] + dz];
    const sx = Math.round(n[0] / T) - Math.round(o[0] / T), sz = Math.round(n[1] / T) - Math.round(o[1] / T);
    offsets.set(it, n);
    if (sx || sz) it.block = it.block.map(([x, y]) => [x + sx, y + sz]);
  }
}

export function blocksFor(it) {
  const [x0, z0, x1, z1] = bbox(it), out = [];
  for (let ty = Math.max(0, Math.floor(z0 / T)); ty <= Math.min(GRID - 1, Math.floor((z1 - 0.01) / T)); ty++)
    for (let tx = Math.max(0, Math.floor(x0 / T)); tx <= Math.min(GRID - 1, Math.floor((x1 - 0.01) / T)); tx++) {
      const ox = Math.min(x1, (tx + 1) * T) - Math.max(x0, tx * T), oz = Math.min(z1, (ty + 1) * T) - Math.max(z0, ty * T);
      if (ox * oz >= T * T * 0.3) out.push([tx, ty]);
    }
  return out;
}

export function hit(it, x, z) {
  const b = bbox(it), pad = ['wallquad', 'quad'].includes(it.type) ? 4 : 0;
  return x >= b[0] - pad && x <= b[2] + pad && z >= b[1] - pad && z <= b[3] + pad;
}

// which items can be rotated and by which means
export const ROTATABLE = new Set(['bed', 'game', 'custom']);
// types that are only visual (no collision)
export const VISUAL = new Set(['flat', 'quad', 'wallquad']);

// raise (positive) or lower an item by dy units: its "lift" above the floor
export function lift(it, dy) { it.lift = Math.round(((it.lift || 0) + dy) * 100) / 100; if (!it.lift) delete it.lift; }

export function rotate(it) {
  if (!ROTATABLE.has(it.type)) return false;
  const c = center(it);
  it.rot = ((it.rot || 0) + 90) % 360;
  return c;
}

let idn = 0;
export function newId(items, prefix = 'i') {
  const ids = new Set(items.map((i) => i.id));
  let n = items.length + 1 + idn++;
  while (ids.has(prefix + n)) n++;
  return prefix + n;
}

// default items by type, centred on (x, z)
export function make(type, x, z, o = {}) {
  const sn = (v) => Math.round(v / 8) * 8;
  x = sn(x); z = sn(z);
  switch (type) {
    case 'box': return { type, x0: x - 16, x1: x + 16, y0: 0, y1: 28, z0: z - 16, z1: z + 16, mat: o.mat, faces: {} };
    case 'cyl': return { type, cx: x, cz: z, r: 10, y0: 0, y1: 30, side: o.mat, top: o.mat, n: 12 };
    case 'flat': return { type, x0: x - 40, x1: x + 40, z0: z - 28, z1: z + 28, mat: o.mat, y: 0.4 };
    case 'quad': return { type, pts: [[x - 24, 40, 1], [x + 24, 40, 1], [x + 24, 72, 1], [x - 24, 72, 1]], mat: o.mat };
    case 'wallquad': return { type, a: [x - 16, z], b: [x + 16, z], h: 32, mat: o.mat, both: true };
    case 'lamp': return { type, x, z, shade: o.mat };
    case 'extrude': return { type, shape: 'circle', cx: x, cz: z, size: 56, y0: 0, y1: 12, top_y: 10, side: o.mat, top: o.mat };
    case 'bed': return { type, x, z, rot: 0, palette: o.palette };
    case 'stand': return { type, x, z, palette: o.palette };
    case 'game': return { type, path: o.path, x, z, rot: 0, scale: 1, tex_cap: 64, fp: o.fp || [32, 32] };
    case 'custom': return { type, asset: o.asset, x, z, rot: 0, scale: o.scale || 1, tex_cap: 64, fp: o.fp || [32, 32], size: o.size, up: o.up || 'y' };
  }
}
