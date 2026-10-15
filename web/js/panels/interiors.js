import { get, post, put, del, q } from '../api.js';
import { S, changed as saveChanged, uid } from '../state.js';
import { h, mount, toast, select, debounce, field, textInput, numInput, colorInput, checkbox, modal, prompt, confirmBox, loadImage, pickFiles } from '../ui.js';
import { Viewer, dataImage, boundsOf } from '../viewer.js';
import { PixelEditor } from '../pixel.js';
import * as plan from '../plan.js';
import { newInterior } from './buildings.js';

export const id = 'interiors', title = 'Interiors', icon = '▣', needsProject = true;
const { T, GRID, WORLD } = plan;
const SCALE = 36 / T;                                   // canvas px per world unit
const TYPE_LABEL = { box: 'Box', cyl: 'Cylinder', flat: 'Rug / floor decal', quad: 'Picture / poster', wallquad: 'Wall panel', lamp: 'Lamp', extrude: 'Tub / pedestal', bed: 'Bed', stand: 'Bedside table', game: 'Game furniture', custom: 'Custom 3D model' };
const WALL_PRESETS = ['plain', 'stripes_hearts', 'panel', 'brick', 'night', 'tiles', 'leopard', 'tufted', 'wood'];
const FLOOR_PRESETS = ['plain', 'hearts', 'marble', 'flagstone', 'checker', 'tiles', 'leopard', 'shag', 'planks', 'carpet'];
const PROP_PRESETS = ['solid', 'gradient', 'wood', 'fabric', 'stripes', 'leopard', 'shag', 'tiles', 'hearts', 'sign', 'text'];

export function render(root, app) {
  const P = S.project;
  const preset = app.preset; app.preset = null;
  // undo / redo: a snapshot of the scene after each (coalesced) change
  const hist = { stack: [], at: -1, sid: null };
  const snapshot = () => { const sc = scene(); if (!sc) return; if (hist.sid !== sc.id) { hist.stack = []; hist.at = -1; hist.sid = sc.id; } const j = JSON.stringify(sc); if (hist.stack[hist.at] === j) return; hist.stack = hist.stack.slice(0, hist.at + 1); hist.stack.push(j); if (hist.stack.length > 80) hist.stack.shift(); hist.at = hist.stack.length - 1; };
  const commitSoon = debounce(snapshot, 350);
  const changed = () => { saveChanged(); commitSoon(); };
  const restore = (i) => { const sc = scene(); if (!sc || i < 0 || i >= hist.stack.length) return; commitSoon.now(); hist.at = i; const j = JSON.parse(hist.stack[i]); for (const k of Object.keys(sc)) delete sc[k]; Object.assign(sc, j); setSel([]); saveChanged(); drawAll(); preview(); };
  const undo = () => { commitSoon.now(); restore(hist.at - 1); };
  const redo = () => { restore(hist.at + 1); };
  const st = { multi: new Set(), anchor: null, sid: (preset && preset.interior) || (P.interiors[0] && P.interiors[0].id) || null, tool: 'select', sel: null, tab: 'add', placing: null, drag: null, hover: null, problems: [], used: 0, tris: 0, presets: null, flash: 0 };
  const scene = () => P.interiors.find((s) => s.id === st.sid);
  // selection: st.multi holds the selected items' ids; st.sel stays the "main" selection the inspector shows
  const setSel = (ids, room) => {
    st.multi = new Set(ids);
    st.sel = room ? { kind: 'room', id: room } : ids.length === 1 ? { kind: 'item', id: ids[0] } : ids.length ? { kind: 'items' } : null;
    if (ids.length) st.anchor = ids[ids.length - 1];
  };
  const selItems = () => { const sc = scene(); return sc ? sc.items.filter((i) => st.multi.has(i.id)) : []; };
  const toggleIn = (id) => { const ids = [...st.multi]; const k = ids.indexOf(id); if (k >= 0) ids.splice(k, 1); else ids.push(id); return ids; };

  const left = h('div', { class: 'pane', style: { display: 'flex', flexDirection: 'column' } });
  const mid = h('div', { class: 'pane pad', style: { display: 'flex', flexDirection: 'column', gap: '10px' } });
  const right = h('div', { class: 'pane', style: { display: 'flex', flexDirection: 'column' } });
  mount(root, h('div', { class: 'page-head' }, h('h2', {}, 'Interiors'), h('p', {}, 'Lay out rooms and place furniture on the 16 × 16 plan. The 3D view updates as you work.')),
    h('div', { class: 'split', style: { gridTemplateColumns: '300px 620px minmax(300px,1fr)' } }, left, mid, right));

  // ================================================================ plan canvas
  const cv = h('canvas', { width: GRID * 36, height: GRID * 36, style: { width: GRID * 36 + 'px', height: GRID * 36 + 'px', cursor: 'default', touchAction: 'none', alignSelf: 'center' } });
  const toolbar = h('div', { class: 'toolbar', style: { border: '1px solid var(--line)', borderRadius: '6px' } });
  const hint = h('div', { class: 'dim', style: { fontSize: '12px', minHeight: '32px' } });
  mount(mid, toolbar, cv, hint);

  const sceneNames = () => P.interiors.map((s) => [s.id, s.title || s.id]);
  function drawToolbar() {
    const tools = [['select', '↖ Select / move', 'V'], ['room', '▭ Draw area', 'U'], ['door', '⌷ Doorway', 'D'], ['link', '⇄ Way to another room', 'L']];
    mount(toolbar,
      P.interiors.length ? h('button', { class: 'small primary', title: 'Furniture, shapes, game furniture and your own 3D models', onclick: () => { st.tab = 'add'; drawLeft(); } }, '＋ Add item') : null,
      P.interiors.length ? (() => { const s = select(sceneNames(), st.sid, (v) => { st.sid = v; setSel([]); st.placing = null; drawAll(); preview.now(); }); s.style.width = '170px'; return s; })() : null,
      h('button', { class: 'small', title: 'A new, empty room', onclick: addScene }, '+ Room'),
      scene() ? h('button', { class: 'small', title: 'A new room joined to this one by doors both ways', onclick: addLinkedRoom }, '+ Linked room') : null,
      P.interiors.length ? h('button', { class: 'small ghost', onclick: renameScene }, 'Rename') : null,
      P.interiors.length ? h('button', { class: 'small ghost danger', onclick: delScene }, 'Delete') : null,
      h('button', { class: 'small ghost', title: 'Undo (Ctrl+Z)', onclick: undo }, '↶'), h('button', { class: 'small ghost', title: 'Redo (Ctrl+Y)', onclick: redo }, '↷'),
      h('div', { class: 'sep-v' }),
      tools.map(([id, label, key]) => h('button', { class: 'small' + (st.tool === id && !st.placing ? ' on' : ''), title: label + ' (' + key + ')', onclick: () => { st.tool = id; st.placing = null; drawToolbar(); hintText(); } }, label)),
      st.placing ? h('span', { class: 'chip warn' }, 'placing: ' + (TYPE_LABEL[st.placing.type] || st.placing.type) + ' — click the plan, Esc to stop') : null);
  }
  function hintText() {
    const t = st.placing ? 'Click on the plan to place it. Hold Shift to place several.' : { select: 'Click an item to select it; Ctrl/Shift-click adds more, or drag a box on empty floor. Drag to move the selection; arrows nudge (Alt: 1 unit, Shift: a tile), PgUp / PgDn raise and lower it, R rotates, Del deletes. A room is selected by clicking its floor and moved by its top-left tile. Click empty space with nothing selected to set the entrance.', room: 'Drag on the empty grid to add an area (a rectangle of floor; any tile outside the areas is a low partition wall).', link: 'Click a floor tile (best next to a wall) to make a door to another room: walking onto it crosses into that room, and with “Two-way” on the other room gets the door back automatically. Choose where it leads in the Links tab. Click a door tile again to remove it.', door: 'Select a room first, then click floor tiles beside it to make doorways to the main room.' }[st.tool];
    hint.textContent = t;
  }
  async function addScene() {
    const t = await prompt('New room', 'Name', 'My room'); if (!t) return;
    const sc = newInterior(P, t); P.interiors.push(sc); st.sid = sc.id; changed(); drawAll(); preview.now();
  }
  async function renameScene() { const t = await prompt('Rename interior', 'Name', scene().title); if (t) { scene().title = t; changed(); drawToolbar(); } }
  async function delScene() {
    const sc = scene(); const users = P.buildings.filter((b) => b.interior === sc.id);
    if (!await confirmBox('Delete "' + (sc.title || sc.id) + '"' + (users.length ? ' (used by ' + users.map((b) => b.name || b.id).join(', ') + ')' : '') + '?', 'Delete')) return;
    P.interiors.splice(P.interiors.indexOf(sc), 1); users.forEach((b) => { b.interior = null; }); P.interiors.forEach((o) => { o.links = (o.links || []).filter((l) => l.to !== sc.id); });
    st.sid = P.interiors[0] ? P.interiors[0].id : null; setSel([]); changed(); drawAll(); preview.now();
  }

  // ---- links: ways to other rooms of the building
  const floorMap = (sc) => ownerMap(sc);
  const solidSet = (sc) => { const o = new Set(); for (const it of sc.items) for (const b of it.block || []) o.add(b[0] + ',' + b[1]); return o; };
  const linkTiles = (sc) => { const o = new Map(); for (const l of sc.links || []) for (const t of l.tiles || []) o.set(t[0] + ',' + t[1], l); return o; };
  // free floor tiles (not an entrance, doorway, link or blocked by furniture), nearest to (cx, cy) first
  function freeTiles(sc, cx, cy, avoid) {
    const fl = floorMap(sc), sol = solidSet(sc), lk = linkTiles(sc), out = [];
    const ent = plan.entrance(sc), door = new Set([...ent.door, ...ent.exit].map((t) => t[0] + ',' + t[1]));
    for (const [k, o] of fl) { if (sol.has(k) || lk.has(k) || door.has(k) || (avoid && avoid.has(k)) || o.door) continue; const [x, y] = k.split(',').map(Number); out.push([x, y]); }
    return out.sort((a, b) => Math.hypot(a[0] - cx, a[1] - cy) - Math.hypot(b[0] - cx, b[1] - cy));
  }
  const neighbours = ([x, y]) => [[x, y + 1], [x, y - 1], [x + 1, y], [x - 1, y]];
  // where a door looks right: free floor tiles against a back or side wall first (the front is open), then any edge, then the rest; nearest to cx, cy first
  function doorSpots(sc, cx, cy) {
    const fl = floorMap(sc), all = freeTiles(sc, cx, cy), open = (t, skipSouth) => neighbours(t).some(([x, y]) => !fl.has(x + ',' + y) && !(skipSouth && y > t[1]));
    return [...all.filter((t) => open(t, true)), ...all.filter((t) => open(t, false) && !open(t, true)), ...all.filter((t) => !open(t, false))];
  }
  const FACES = [['north', 'North (towards the back wall)'], ['south', 'South (towards the front)'], ['east', 'East (right)'], ['west', 'West (left)']];
  const newLinkId = (sc) => uid('link', sc.links || []);
  const faceOf = (from, to) => { const dx = to[0] - from[0], dy = to[1] - from[1]; return Math.abs(dy) >= Math.abs(dx) ? (dy > 0 ? 'south' : 'north') : (dx > 0 ? 'east' : 'west'); };
  // a free floor tile next to t (not furniture, a door or another link)
  function freeNeighbour(sc, t, avoid) {
    const fl = floorMap(sc), sol = solidSet(sc), lk = linkTiles(sc);
    return neighbours(t).find(([x, y]) => { const k = x + ',' + y; return fl.has(k) && !fl.get(k).door && !sol.has(k) && !lk.has(k) && !(avoid && avoid.has(k)); }) || null;
  }
  // give room `dest` a door back to `a` (through tile `ta` of a): the forward link then arrives next to that door, facing away from it
  function makeWayBack(a, link, dest) {
    const ta = link.tiles[0], avoid = new Set((dest.links || []).flatMap((l) => l.tiles.map((t) => t.join(','))));
    const qa = freeNeighbour(a, ta); if (!qa) return false;
    for (const tb of doorSpots(dest, 8, 0)) {
      if (avoid.has(tb.join(','))) continue;
      const qb = freeNeighbour(dest, tb, new Set([tb.join(',')])); if (!qb) continue;
      dest.links = (dest.links || []).concat([{ id: newLinkId(dest), tiles: [tb], to: a.id, arrive: qa, face: faceOf(ta, qa) }]);
      link.arrive = qb; link.face = faceOf(tb, qb);
      return true;
    }
    return false;
  }
  const hasWayBack = (sc, dest) => dest && (dest.links || []).some((l) => l.to === sc.id);
  async function addLinkedRoom() {
    const a = scene(); if (!a) return;
    const name = await prompt('New linked room', 'Name', 'Room ' + (P.interiors.length + 1)); if (!name) return;
    const b = newInterior(P, name);
    const ta = doorSpots(a, 8, 0)[0]; if (!ta) { toast('There is no free tile in this room for the door', 'error'); return; }
    P.interiors.push(b);
    const nl = { id: newLinkId(a), tiles: [ta], to: b.id, arrive: [8, 10], face: 'south' };
    a.links = (a.links || []).concat([nl]);
    if (!makeWayBack(a, nl, b)) { toast('Could not place the door back: add it by hand in the new room', 'error'); }
    st.sid = b.id; setSel([]); st.tab = 'links'; changed(); drawAll(); preview.now();
    toast('Created ' + name + ': a door in each room leads to the other', 'ok');
  }

  // ---- drawing
  const tintOf = (sc, matName, kind) => {
    const m = sc.materials[matName]; if (!m) return '#666';
    if (m.image) return '#7d7d86';
    const pr = (st.presets && st.presets[kind] && st.presets[kind][m.preset || 'plain']) || {};
    return (m.colors && m.colors.c1) || pr.c1 || '#888';
  };
  function drawPlan() {
    const sc = scene(), g = cv.getContext('2d'); const S36 = 36;
    g.clearRect(0, 0, cv.width, cv.height); g.fillStyle = '#10151a'; g.fillRect(0, 0, cv.width, cv.height);
    if (!sc) { g.fillStyle = '#8e9aa6'; g.font = '14px system-ui'; g.fillText('Create an interior with “+ New”', 150, 280); return; }
    const owner = ownerMap(sc), ent = plan.entrance(sc);
    for (let y = 0; y < GRID; y++) for (let x = 0; x < GRID; x++) {
      const o = owner.get(x + ',' + y);
      if (o) { const room = sc.rooms.find((r) => r.id === o.room); g.fillStyle = tintOf(sc, (o.door ? (sc.rooms.find((r) => r.id === sc.main) || {}) : room || {}).floor, 'floor'); g.globalAlpha = 0.85; g.fillRect(x * S36, y * S36, S36, S36); g.globalAlpha = 1; }
      else { g.fillStyle = '#2a323a'; g.fillRect(x * S36, y * S36, S36, S36); }
      if (ent.side === 'south' ? y >= GRID - 1 : !plan.inBounds(ent.bounds, x, y) && !(o && o.door)) { g.fillStyle = 'rgba(0,0,0,.45)'; g.fillRect(x * S36, y * S36, S36, S36); }
    }
    g.strokeStyle = 'rgba(255,255,255,.07)'; g.lineWidth = 1; g.beginPath();
    for (let i = 0; i <= GRID; i++) { g.moveTo(i * S36 + .5, 0); g.lineTo(i * S36 + .5, cv.height); g.moveTo(0, i * S36 + .5); g.lineTo(cv.width, i * S36 + .5); } g.stroke();
    // doors / exit
    for (const t of ent.door) { g.fillStyle = 'rgba(107,191,122,.75)'; g.fillRect(t[0] * S36 + 2, t[1] * S36 + 2, S36 - 4, S36 - 4); }
    for (const t of ent.exit) { g.fillStyle = 'rgba(106,168,230,.55)'; g.fillRect(t[0] * S36 + 2, t[1] * S36 + 2, S36 - 4, S36 - 4); }
    label(g, 'DOOR (' + ent.side + ')', ent.door[0][0] * S36 + 4, ent.door[0][1] * S36 + 14);
    // rooms
    for (const r of sc.rooms) {
      const [x0, y0, x1, y1] = r.rect, sel = st.sel && st.sel.kind === 'room' && st.sel.id === r.id;
      g.strokeStyle = sel ? '#6bbf7a' : 'rgba(255,255,255,.35)'; g.lineWidth = sel ? 3 : 1.5; g.strokeRect(x0 * S36 + 1, y0 * S36 + 1, (x1 - x0 + 1) * S36 - 2, (y1 - y0 + 1) * S36 - 2);
      label(g, (r.name || r.id) + (r.id === sc.main ? ' ★' : ''), x0 * S36 + 4, y0 * S36 + 13, sel);
      for (const d of r.doors || []) { g.fillStyle = 'rgba(255,230,120,.5)'; g.fillRect(d[0] * S36 + 4, d[1] * S36 + 4, S36 - 8, S36 - 8); }
    }
    // solid tiles
    g.strokeStyle = 'rgba(230,106,95,.7)'; g.lineWidth = 1;
    const solid = new Set(); for (const it of sc.items) for (const b of it.block || []) solid.add(b[0] + ',' + b[1]);
    for (const k of solid) { const [x, y] = k.split(',').map(Number); g.beginPath(); for (let i = 0; i < S36; i += 8) { g.moveTo(x * S36 + i, y * S36); g.lineTo(x * S36, y * S36 + i); } g.stroke(); }
    for (const l of sc.links || []) for (const t of l.tiles || []) {
      const dest = P.interiors.find((x) => x.id === l.to), sel = st.linkSel === l.id;
      g.fillStyle = 'rgba(190,120,255,.55)'; g.fillRect(t[0] * S36 + 2, t[1] * S36 + 2, S36 - 4, S36 - 4); g.strokeStyle = sel ? '#fff' : '#c9a0ff'; g.lineWidth = sel ? 3 : 2; g.strokeRect(t[0] * S36 + 3, t[1] * S36 + 3, S36 - 6, S36 - 6);
      g.fillStyle = '#fff'; g.font = 'bold 15px system-ui'; g.fillText('⇄', t[0] * S36 + 9, t[1] * S36 + 24); label(g, '→ ' + (dest ? dest.title || dest.id : '?'), t[0] * S36 + 2, t[1] * S36 - 1, sel);
    }
    // items
    for (const it of sc.items) drawItem(g, it, st.multi.has(it.id), sc);
    // selection: a clear frame around every selected item (dark outline + bright frame + corner handles), and one around the group
    const chosen = sc.items.filter((it) => st.multi.has(it.id));
    for (const it of chosen) {
      const b = plan.bbox(it).map((v) => v * SCALE), pad = 9, minS = 34, cxm = (b[0] + b[2]) / 2, cym = (b[1] + b[3]) / 2, w = Math.max(minS, b[2] - b[0] + 2 * pad), hh = Math.max(minS, b[3] - b[1] + 2 * pad), x = cxm - w / 2, y = cym - hh / 2;
      g.fillStyle = 'rgba(255,230,80,.22)'; g.fillRect(x, y, w, hh);
      g.lineWidth = 5; g.strokeStyle = 'rgba(0,0,0,.75)'; g.strokeRect(x, y, w, hh);
      g.lineWidth = 3; g.strokeStyle = '#ffe650'; g.strokeRect(x, y, w, hh);
      for (const [cx, cy] of [[x, y], [x + w, y], [x, y + hh], [x + w, y + hh]]) { g.fillStyle = '#000'; g.fillRect(cx - 6, cy - 6, 12, 12); g.fillStyle = '#ffe650'; g.fillRect(cx - 4, cy - 4, 8, 8); }
    }
    if (chosen.length > 1) {
      const bs = chosen.map((it) => plan.bbox(it).map((v) => v * SCALE)), x0 = Math.min(...bs.map((b) => b[0])) - 9, y0 = Math.min(...bs.map((b) => b[1])) - 9, x1 = Math.max(...bs.map((b) => b[2])) + 9, y1 = Math.max(...bs.map((b) => b[3])) + 9;
      g.lineWidth = 1.5; g.strokeStyle = '#6bbf7a'; g.setLineDash([6, 4]); g.strokeRect(x0, y0, x1 - x0, y1 - y0); g.setLineDash([]);
      label(g, chosen.length + ' selected', x0 + 2, y0 - 3, true);
    }
    if (st.drag && st.drag.kind === 'marquee') { const m = st.drag, x0 = Math.min(m.start[0], m.cur[0]) * SCALE, y0 = Math.min(m.start[1], m.cur[1]) * SCALE, x1 = Math.max(m.start[0], m.cur[0]) * SCALE, y1 = Math.max(m.start[1], m.cur[1]) * SCALE; g.fillStyle = 'rgba(255,230,80,.12)'; g.fillRect(x0, y0, x1 - x0, y1 - y0); g.strokeStyle = '#ffe650'; g.setLineDash([4, 3]); g.strokeRect(x0 + .5, y0 + .5, x1 - x0, y1 - y0); g.setLineDash([]); }
    // tool previews
    if (st.drag && st.drag.kind === 'room') { const r = st.drag.rect; g.strokeStyle = '#ffe650'; g.setLineDash([5, 4]); g.strokeRect(r[0] * S36, r[1] * S36, (r[2] - r[0] + 1) * S36, (r[3] - r[1] + 1) * S36); g.setLineDash([]); }
    if (st.placing && st.hover) { const p = plan.make(st.placing.type, st.hover[0], st.hover[1], st.placing); if (p) { p.id = '_ghost'; g.globalAlpha = 0.55; drawItem(g, p, true, sc); g.globalAlpha = 1; } }
  }
  function label(g, t, x, y, strong) { g.font = '11px system-ui'; const w = g.measureText(t).width + 6; g.fillStyle = 'rgba(0,0,0,.55)'; g.fillRect(x - 3, y - 11, w, 14); g.fillStyle = strong ? '#9ae6a8' : '#dfe6ec'; g.fillText(t, x, y); }
  function drawItem(g, it, sel, sc) {
    const b = plan.bbox(it).map((v) => v * SCALE), col = sel ? '#ffe650' : 'rgba(255,255,255,.85)';
    g.lineWidth = sel ? 2.5 : 1.5; g.strokeStyle = col;
    const fillFor = (m, kind) => tintOf(sc, m, kind || 'prop');
    if (it.type === 'cyl' || it.type === 'lamp' || (it.type === 'extrude' && it.shape !== 'oval' && it.shape !== 'heart')) {
      g.fillStyle = it.type === 'lamp' ? '#f4d27a' : fillFor(it.side || it.mat, 'prop'); g.beginPath(); g.ellipse((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, (b[2] - b[0]) / 2, (b[3] - b[1]) / 2, 0, 0, 7); g.fill(); g.stroke();
    } else if (it.type === 'extrude') {
      g.fillStyle = fillFor(it.side, 'prop'); g.beginPath(); g.ellipse((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, (b[2] - b[0]) / 2, (b[3] - b[1]) / 2, 0, 0, 7); g.fill(); g.stroke();
      if (it.shape === 'heart') { g.font = '14px system-ui'; g.fillStyle = '#fff'; g.fillText('♥', (b[0] + b[2]) / 2 - 6, (b[1] + b[3]) / 2 + 5); }
    } else if (it.type === 'quad' || it.type === 'wallquad') {
      g.strokeStyle = sel ? '#ffe650' : '#9ec1ff'; g.lineWidth = sel ? 5 : 3; g.beginPath();
      if (it.type === 'wallquad') { g.moveTo(it.a[0] * SCALE, it.a[1] * SCALE); g.lineTo(it.b[0] * SCALE, it.b[1] * SCALE); } else { g.moveTo(b[0], (b[1] + b[3]) / 2); g.lineTo(b[2], (b[1] + b[3]) / 2); }
      g.stroke();
    } else if (it.type === 'flat') {
      g.fillStyle = fillFor(it.mat, 'prop'); g.globalAlpha *= 0.55; g.fillRect(b[0], b[1], b[2] - b[0], b[3] - b[1]); g.globalAlpha /= 0.55; g.setLineDash([4, 3]); g.strokeRect(b[0], b[1], b[2] - b[0], b[3] - b[1]); g.setLineDash([]);
    } else {
      g.fillStyle = it.type === 'custom' ? '#6a5acd' : it.type === 'bed' ? tintOf(sc, '', '') : fillFor(it.mat || it.palette, 'prop');
      g.fillStyle = it.type === 'bed' || it.type === 'stand' ? ((sc.palettes[it.palette] || {}).accent || '#c04060') : g.fillStyle;
      g.fillRect(b[0], b[1], b[2] - b[0], b[3] - b[1]); g.strokeRect(b[0], b[1], b[2] - b[0], b[3] - b[1]);
      if (it.type === 'game') { g.fillStyle = 'rgba(0,0,0,.5)'; g.font = '10px system-ui'; g.fillText(it.path.split('/').pop().replace('.bcres', '').replace(/^rmk_/, '').slice(0, 11), b[0] + 2, (b[1] + b[3]) / 2 + 3); }
      if (it.type === 'custom') { g.fillStyle = 'rgba(255,255,255,.85)'; g.font = '10px system-ui'; g.fillText(modelLabel(it.asset).slice(0, 11), b[0] + 2, (b[1] + b[3]) / 2 + 3); }
      if (it.type === 'bed') { const [hx, hz] = headDir(it.rot || 0); g.fillStyle = 'rgba(255,255,255,.7)'; const c = [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2]; g.beginPath(); g.arc(c[0] + hx * 12, c[1] + hz * 12, 4, 0, 7); g.fill(); }
    }
  }
  const modelLabel = (asset) => String(asset || '').replace(/^mdl_/, '').replace(/__/, ' · ').replace(/\.[a-z]+$/i, '');
  const headDir = (rot) => { const a = rot * Math.PI / 180; return [-Math.sin(a), -Math.cos(a)].map((v) => Math.round(v)); };
  function ownerMap(sc) {
    const m = new Map();
    for (const r of sc.rooms) { const [x0, y0, x1, y1] = r.rect; for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) m.set(x + ',' + y, { room: r.id }); }
    for (const r of sc.rooms) for (const d of r.doors || []) m.set(d[0] + ',' + d[1], { room: sc.main, door: true });
    for (const d of plan.entrance(sc).door) m.set(d[0] + ',' + d[1], { room: sc.main, door: true });
    return m;
  }

  // ---- mouse
  const world = (e) => { const r = cv.getBoundingClientRect(); return [(e.clientX - r.left) / r.width * WORLD, (e.clientY - r.top) / r.height * WORLD]; };
  const tileOf = (w) => [Math.max(0, Math.min(GRID - 1, Math.floor(w[0] / T))), Math.max(0, Math.min(GRID - 1, Math.floor(w[1] / T)))];
  function itemAt(sc, w) { for (let i = sc.items.length - 1; i >= 0; i--) { const it = sc.items[i]; if (plan.hit(it, w[0], w[1])) return it; } return null; }
  function roomAt(sc, t) { return sc.rooms.find((r) => t[0] >= r.rect[0] && t[0] <= r.rect[2] && t[1] >= r.rect[1] && t[1] <= r.rect[3]); }
  cv.addEventListener('pointerdown', (e) => {
    const sc = scene(); if (!sc) return; cv.setPointerCapture(e.pointerId); cv.focus && cv.focus();
    const w = world(e), t = tileOf(w);
    if (st.placing) {
      const it = plan.make(st.placing.type, w[0], w[1], st.placing); it.id = plan.newId(sc.items, st.placing.type[0]);
      it.block = plan.VISUAL.has(it.type) || st.placing.noblock ? undefined : plan.blocksFor(it); if (!it.block) delete it.block;
      sc.items.push(it); setSel([it.id]); if (!e.shiftKey) { st.placing = null; drawToolbar(); hintText(); }
      changed(); drawAll(); preview(); return;
    }
    if (st.tool === 'select') {
      const it = itemAt(sc, w), add = e.ctrlKey || e.metaKey || e.shiftKey;
      if (it) {
        if (add) { const was = st.multi.has(it.id); setSel(toggleIn(it.id)); if (was) { drawInspector(); drawLists(); drawPlan(); return; } }   // Ctrl/Shift-click toggles
        else if (!st.multi.has(it.id)) setSel([it.id]);
        st.drag = { kind: 'move', items: selItems(), start: w, total: [0, 0], snap: !e.altKey, any: false };
      } else {
        const r = roomAt(sc, t);
        const grab = r && !add && t[0] === r.rect[0] && t[1] === r.rect[1];        // the room's top-left tile (its name tag) moves the room
        if (grab) { setSel([], r.id); st.drag = { kind: 'moveRoom', r, start: t, orig: r.rect.slice(), od: (r.doors || []).map((d) => d.slice()) }; }
        else st.drag = { kind: 'marquee', start: w, cur: w, add, base: add ? new Set(st.multi) : new Set(), room: r };
      }
      drawInspector(); drawLists(); drawPlan();
    } else if (st.tool === 'room') {
      st.drag = { kind: 'room', start: t, rect: [t[0], t[1], t[0], t[1]] }; drawPlan();
    } else if (st.tool === 'link') {
      const lk = linkTiles(sc), key = t[0] + ',' + t[1], hit = lk.get(key);
      if (hit) { hit.tiles = hit.tiles.filter((q2) => q2.join(',') !== key); if (!hit.tiles.length) sc.links.splice(sc.links.indexOf(hit), 1); changed(); drawAll(); preview(); return; }
      if (!floorMap(sc).has(key) || solidSet(sc).has(key)) { toast('Links go on free floor tiles', 'info'); return; }
      const others = P.interiors.filter((x) => x.id !== sc.id);
      if (!others.length) { toast('Add another room first (“+ Room” or “+ Linked room”)', 'info'); return; }
      sc.links = sc.links || [];
      const cur = st.linkSel && sc.links.find((l) => l.id === st.linkSel);
      if (cur) cur.tiles.push(t);
      else {
        const o = others.find((x) => x.id === st.lastDest) || others[0], q2 = freeTiles(o, 8, 10)[0] || [8, 10];
        const nl = { id: newLinkId(sc), tiles: [t], to: o.id, arrive: q2, face: 'south' }; sc.links.push(nl); st.linkSel = nl.id;
        if (st.twoWay !== false && !hasWayBack(sc, o) && makeWayBack(sc, nl, o)) toast('Door to ' + (o.title || o.id) + ' made, with a door back', 'ok', 2200);
      }
      st.tab = 'links'; changed(); drawAll(); preview();
    } else if (st.tool === 'door') {
      const r = st.sel && st.sel.kind === 'room' ? sc.rooms.find((x) => x.id === st.sel.id) : null;
      if (!r) { toast('Select the room the doorway leads to first (Select tool)', 'info'); return; }
      if (r.id === sc.main) { toast('Doorways lead from the main room to other rooms: select another room', 'info'); return; }
      const k = (r.doors || []).findIndex((d) => d[0] === t[0] && d[1] === t[1]);
      r.doors = r.doors || [];
      if (k >= 0) r.doors.splice(k, 1); else { const inside = roomAt(sc, t); if (inside) { toast('A doorway is a floor tile outside the room, in the main room or between rooms', 'info'); return; } r.doors.push(t); }
      changed(); drawAll(); preview();
    }
  });
  cv.addEventListener('pointermove', (e) => {
    const sc = scene(); if (!sc) return; const w = world(e), t = tileOf(w); st.hover = w;
    const d = st.drag;
    if (d && d.kind === 'marquee') {
      d.cur = w;
      const x0 = Math.min(d.start[0], w[0]), x1 = Math.max(d.start[0], w[0]), z0 = Math.min(d.start[1], w[1]), z1 = Math.max(d.start[1], w[1]);
      if (x1 - x0 > 4 || z1 - z0 > 4) {
        const ids = new Set(d.base);
        for (const it of sc.items) { const b = plan.bbox(it); if (!(b[2] < x0 || b[0] > x1 || b[3] < z0 || b[1] > z1)) ids.add(it.id); }
        setSel([...ids]); d.dragged = true; drawLists();
      }
      drawPlan();
    } else if (d && d.kind === 'move') {
      const dx = w[0] - d.start[0], dz = w[1] - d.start[1];
      const sn = d.snap ? 8 : 1, ax = Math.round(dx / sn) * sn, az = Math.round(dz / sn) * sn;
      const mx = ax - d.total[0], mz = az - d.total[1];
      if (mx || mz) { for (const it of d.items) plan.move(it, mx, mz); d.total = [ax, az]; d.any = true; drawPlan(); drawInspector(true); }
    } else if (d && d.kind === 'room') { d.rect = [Math.min(d.start[0], t[0]), Math.min(d.start[1], t[1]), Math.max(d.start[0], t[0]), Math.max(d.start[1], t[1])]; drawPlan(); }
    else if (d && d.kind === 'moveRoom') {
      const dx = t[0] - d.start[0], dy = t[1] - d.start[1], o = d.orig;
      const bd = plan.entrance(sc).bounds, nx0 = Math.max(bd[0], Math.min(bd[2] - (o[2] - o[0]), o[0] + dx)), ny0 = Math.max(bd[1], Math.min(bd[3] + (bd[3] === 13 && plan.entrance(sc).side === 'south' ? 1 : 0) - (o[3] - o[1]), o[1] + dy));
      d.r.rect = [nx0, ny0, nx0 + o[2] - o[0], ny0 + o[3] - o[1]]; d.r.doors = d.od.map((q2) => [q2[0] + nx0 - o[0], q2[1] + ny0 - o[1]]); drawPlan();
    } else if (st.placing) drawPlan();
    else { const it = itemAt(sc, w); cv.style.cursor = it ? 'move' : 'default'; }
  });
  cv.addEventListener('pointerup', () => {
    const sc = scene(), d = st.drag; st.drag = null; if (!d || !sc) return;
    if (d.kind === 'room') {
      let [x0, y0, x1, y1] = d.rect; const bd = plan.entrance(sc).bounds;
      x0 = Math.max(x0, bd[0]); y0 = Math.max(y0, bd[1]); x1 = Math.min(x1, bd[2]); y1 = Math.min(y1, bd[3] + (bd[3] === 13 && plan.entrance(sc).side === 'south' ? 1 : 0));
      const clash = x1 < x0 || y1 < y0 || sc.rooms.some((r) => !(x1 < r.rect[0] || x0 > r.rect[2] || y1 < r.rect[1] || y0 > r.rect[3]));
      if (clash) toast(x1 < x0 || y1 < y0 ? 'That area is in the entrance strip: draw it inside the room' : 'Rooms cannot overlap', 'error');
      else {
        const rid = uid('room', sc.rooms), tag = rid.replace('room', '');
        const fm = 'floor_' + rid, wm = 'wall_' + rid;
        sc.materials[fm] = { type: 'floor', preset: 'planks' }; sc.materials[wm] = { type: 'wall', preset: 'plain' };
        sc.rooms.push({ id: rid, name: 'Room ' + tag, rect: [x0, y0, x1, y1], floor: fm, wall: wm, doors: [] }); setSel([], rid); st.tool = 'select'; changed();
      }
    } else if (d.kind === 'marquee') {
      if (!d.dragged && !d.add) setSel([], d.room ? d.room.id : null);                // a plain click on empty floor: the room, or nothing
      drawAll(); return;
    } else if (d.kind === 'move' || d.kind === 'moveRoom') { if (d.kind === 'moveRoom' || d.any) changed(); else { drawAll(); return; } }
    drawAll(); preview();
  });
  cv.addEventListener('pointerleave', () => { st.hover = null; if (st.placing) drawPlan(); });
  const onKey = (e) => {
    if (!cv.isConnected || /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
    const sc = scene(); if (!sc) return; const k = e.key;
    if (e.ctrlKey && (k === 'z' || k === 'Z') && !e.shiftKey) { e.preventDefault(); undo(); return; }
    if (e.ctrlKey && (k === 'y' || k === 'Y' || ((k === 'z' || k === 'Z') && e.shiftKey))) { e.preventDefault(); redo(); return; }
    if (k === 'Escape') { st.placing = null; setSel([]); drawAll(); return; }
    if ((e.ctrlKey || e.metaKey) && (k === 'a' || k === 'A')) { e.preventDefault(); setSel(sc.items.map((i) => i.id)); drawAll(); return; }
    const its = selItems();
    if ((e.ctrlKey || e.metaKey) && (k === 'd' || k === 'D')) { e.preventDefault(); if (its.length) duplicate(its); return; }
    if (!e.ctrlKey && !e.metaKey) { if (k === 'l') { st.tool = 'link'; drawToolbar(); hintText(); } else if (k === 'v') { st.tool = 'select'; drawToolbar(); hintText(); } else if (k === 'u') { st.tool = 'room'; drawToolbar(); hintText(); } else if (k === 'd') { st.tool = 'door'; drawToolbar(); hintText(); } }
    if (!its.length) { if ((k === 'Delete' || k === 'Backspace') && st.sel && st.sel.kind === 'room') { delRoom(); } return; }
    const step = e.shiftKey ? T : e.altKey ? 1 : 8;
    if (k === 'PageUp' || k === 'PageDown') { const dy = (k === 'PageUp' ? 1 : -1) * (e.altKey ? 1 : 4); its.forEach((it) => plan.lift(it, dy)); }
    else if (k === 'Delete' || k === 'Backspace') { sc.items = sc.items.filter((i) => !st.multi.has(i.id)); setSel([]); }
    else if (k === 'ArrowLeft') its.forEach((it) => plan.move(it, -step, 0)); else if (k === 'ArrowRight') its.forEach((it) => plan.move(it, step, 0)); else if (k === 'ArrowUp') its.forEach((it) => plan.move(it, 0, -step)); else if (k === 'ArrowDown') its.forEach((it) => plan.move(it, 0, step));
    else if (k === 'r') its.forEach((it) => { const c = plan.rotate(it); if (c) { const c2 = plan.center(it); plan.move(it, c[0] - c2[0], c[1] - c2[1]); } });
    else return;
    e.preventDefault(); changed(); drawAll(); preview();
  };
  window.addEventListener('keydown', onKey);
  function duplicate(list) {
    const sc = scene(), items = Array.isArray(list) ? list : [list], ids = [];
    for (const it of items) { const c = JSON.parse(JSON.stringify(it)); c.id = plan.newId(sc.items, it.type[0]); plan.move(c, 16, 16); sc.items.push(c); ids.push(c.id); }
    setSel(ids); changed(); drawAll(); preview();
  }
  function align(mode) {
    const its = selItems(); if (its.length < 2) return;
    const bs = its.map((it) => plan.bbox(it));
    const L = Math.min(...bs.map((b) => b[0])), R = Math.max(...bs.map((b) => b[2])), Tp = Math.min(...bs.map((b) => b[1])), B = Math.max(...bs.map((b) => b[3]));
    its.forEach((it, i) => { const b = bs[i]; let dx = 0, dz = 0;
      if (mode === 'left') dx = L - b[0]; else if (mode === 'right') dx = R - b[2]; else if (mode === 'hcenter') dx = (L + R) / 2 - (b[0] + b[2]) / 2;
      else if (mode === 'top') dz = Tp - b[1]; else if (mode === 'bottom') dz = B - b[3]; else if (mode === 'vcenter') dz = (Tp + B) / 2 - (b[1] + b[3]) / 2;
      if (dx || dz) plan.move(it, Math.round(dx), Math.round(dz)); });
    changed(); drawAll(); preview();
  }
  function delRoom() {
    const sc = scene(), r = sc.rooms.find((x) => x.id === st.sel.id); if (!r) return;
    if (r.id === sc.main) { toast('The main room cannot be deleted', 'error'); return; }
    sc.rooms.splice(sc.rooms.indexOf(r), 1); setSel([]); changed(); drawAll(); preview();
  }

  // ================================================================ left: lists
  function drawLeft() {
    const sc = scene();
    mount(left, h('div', { class: 'tabs compact' }, [['add', '＋ Add'], ['items', 'Items'], ['rooms', 'Areas'], ['links', 'Links'], ['mats', 'Materials']].map(([id, l]) => h('button', { class: st.tab === id ? 'on' : '', onclick: () => { st.tab = id; drawLeft(); } }, l))), h('div', { style: { overflow: 'auto', flex: 1 }, id: 'leftbody' }));
    drawLists();
  }
  function drawLists() {
    const sc = scene(), body = left.querySelector('#leftbody'); if (!body) return;
    if (!sc) { mount(body, h('div', { class: 'empty' }, 'No interior yet.')); return; }
    if (st.tab === 'items') {
      mount(body, h('div', { class: 'list' }, sc.items.length ? sc.items.map((it, i) => h('div', { class: 'item' + (st.multi.has(it.id) ? ' on' : ''), onclick: (e) => { listClick(e, sc, it); } },
        h('span', {}, TYPE_LABEL[it.type] || it.type), h('span', { class: 'dim', style: { fontSize: '12px' } }, it.type === 'game' ? it.path.split('/').pop().replace('.bcres', '') : it.type === 'custom' ? modelLabel(it.asset) : it.id), it.block && it.block.length ? h('span', { class: 'chip sub' }, 'solid') : null)) : h('div', { class: 'empty' }, 'Nothing placed. Use the Add tab.')));
    } else if (st.tab === 'rooms') {
      mount(body, h('div', { class: 'list' }, sc.rooms.map((r) => h('div', { class: 'item' + (st.sel && st.sel.kind === 'room' && st.sel.id === r.id ? ' on' : ''), onclick: () => { setSel([], r.id); drawInspector(); drawLists(); drawPlan(); } }, h('span', {}, (r.name || r.id) + (r.id === sc.main ? ' ★' : '')), h('span', { class: 'sub dim' }, (r.rect[2] - r.rect[0] + 1) + '×' + (r.rect[3] - r.rect[1] + 1)))),
        h('div', { class: 'dim', style: { padding: '10px 12px', fontSize: '12px' } }, 'Use the “Draw area” tool to add areas. ★ is the main area: the entrance, and where doorways lead.'), entranceCard(sc)));
    } else if (st.tab === 'mats') drawMaterials(body, sc);
    else if (st.tab === 'links') drawLinks(body, sc);
    else drawAdd(body, sc);
  }

  // list selection: click, Ctrl/Cmd-click toggles, Shift-click selects the range from the last clicked item
  function listClick(e, sc, it) {
    if (e.shiftKey && st.anchor) {
      const a = sc.items.findIndex((i) => i.id === st.anchor), b = sc.items.findIndex((i) => i.id === it.id);
      if (a >= 0 && b >= 0) { const [lo, hi] = a < b ? [a, b] : [b, a]; const ids = new Set(e.ctrlKey || e.metaKey ? st.multi : []); for (let k = lo; k <= hi; k++) ids.add(sc.items[k].id); const keep = st.anchor; setSel([...ids]); st.anchor = keep; }
    } else if (e.ctrlKey || e.metaKey) setSel(toggleIn(it.id)); else setSel([it.id]);
    drawInspector(); drawLists(); drawPlan();
  }

  // ---- the Links tab: where each way out of this room leads
  function arrivalOk(dest, a) {
    const k = a[0] + ',' + a[1]; return floorMap(dest).has(k) && !floorMap(dest).get(k).door && !solidSet(dest).has(k) && !linkTiles(dest).has(k);
  }
  function drawLinks(body, sc) {
    const others = P.interiors.filter((x) => x.id !== sc.id);
    const owners = P.buildings.filter((b) => b.interior === sc.id).map((b) => b.name || b.id);
    const cards = (sc.links || []).map((l) => {
      const dest = P.interiors.find((x) => x.id === l.to), ok = dest && arrivalOk(dest, l.arrive || [-1, -1]);
      const mini = h('canvas', { width: 14 * GRID, height: 14 * GRID, style: { width: 14 * GRID + 'px', height: 14 * GRID + 'px', cursor: 'crosshair', borderRadius: '4px', border: '1px solid var(--line)' } });
      const drawMini = () => {
        const g = mini.getContext('2d'); g.fillStyle = '#10151a'; g.fillRect(0, 0, mini.width, mini.height);
        if (dest) {
          for (const [k, o] of floorMap(dest)) { const [x, y] = k.split(',').map(Number); g.fillStyle = o.door ? '#4a5a3a' : '#7a4a52'; g.fillRect(x * 14, y * 14, 13, 13); }
          g.fillStyle = 'rgba(190,120,255,.8)'; for (const t of linkTiles(dest).keys()) { const [x, y] = t.split(',').map(Number); g.fillRect(x * 14 + 2, y * 14 + 2, 9, 9); }
          g.fillStyle = 'rgba(230,106,95,.9)'; for (const k of solidSet(dest)) { const [x, y] = k.split(',').map(Number); g.fillRect(x * 14 + 4, y * 14 + 4, 5, 5); }
        }
        const a = l.arrive || [0, 0]; g.strokeStyle = ok ? '#6bbf7a' : '#e66a5f'; g.lineWidth = 2; g.strokeRect(a[0] * 14 + 1, a[1] * 14 + 1, 12, 12);
      };
      mini.addEventListener('pointerdown', (e) => { const r = mini.getBoundingClientRect(); l.arrive = [Math.floor((e.clientX - r.left) / r.width * GRID), Math.floor((e.clientY - r.top) / r.height * GRID)]; changed(); drawLists(); });
      setTimeout(drawMini, 0);
      return h('div', { class: 'card' + (st.linkSel === l.id ? ' sel' : ''), style: { margin: '8px', padding: '10px', borderColor: st.linkSel === l.id ? '#c9a0ff' : '' } },
        h('div', { class: 'row', style: { marginBottom: '6px' } }, h('b', {}, 'Way ' + l.id), h('span', { class: 'dim' }, (l.tiles || []).length + ' tile(s): ' + (l.tiles || []).map((t) => t.join(',')).join('  ')), h('div', { class: 'grow' }),
          h('button', { class: 'small ghost danger', onclick: () => { sc.links.splice(sc.links.indexOf(l), 1); if (st.linkSel === l.id) st.linkSel = null; changed(); drawAll(); preview(); } }, 'delete')),
        field('Leads to', select(others.map((o) => [o.id, o.title || o.id]), l.to, (v) => { l.to = v; st.lastDest = v; const nd = P.interiors.find((x) => x.id === v); if (nd && !arrivalOk(nd, l.arrive || [-1, -1])) l.arrive = freeTiles(nd, 8, 10)[0] || l.arrive; changed(); drawLists(); drawPlan(); })),
        h('div', { class: 'grid2', style: { marginTop: '6px' } }, field('The player arrives facing', select(FACES, l.face || 'south', (v) => { l.face = v; changed(); })), field('Arrival tile', textInput((l.arrive || []).join(', '), (v) => { const p = v.split(/[ ,]+/).map(Number); if (p.length === 2 && p.every((n) => n >= 0 && n < GRID)) { l.arrive = p; changed(); drawMini(); } }))),
        h('div', { class: 'dim', style: { fontSize: '12px', margin: '6px 0 4px' } }, ok ? 'Click the other room’s floor to choose where the player appears (green = fine).' : 'The arrival tile must be free floor (not a door, link or furniture): click another tile.'), mini,
        dest && !hasWayBack(sc, dest) ? h('div', { class: 'row', style: { marginTop: '8px' } }, h('span', { class: 'dim', style: { fontSize: '12px' } }, 'One-way: ' + (dest.title || dest.id) + ' has no door back.'),
          h('button', { class: 'small', onclick: () => { if (makeWayBack(sc, l, dest)) { changed(); drawAll(); preview(); } else toast('No free tile for a door back', 'error'); } }, 'Add the door back')) : null,
        h('div', { class: 'row', style: { marginTop: '8px' } }, h('button', { class: 'small' + (st.linkSel === l.id ? ' on' : ''), onclick: () => { st.linkSel = l.id; st.tool = 'link'; drawToolbar(); hintText(); drawLists(); } }, 'Add tiles to this way'),
          h('button', { class: 'small', onclick: () => { const b = P.interiors.find((x) => x.id === l.to); if (b) { st.sid = b.id; setSel([]); drawAll(); preview.now(); } } }, 'Go to that room')));
    });
    mount(body, h('div', { style: { padding: '8px 12px 0' } }, checkbox(st.twoWay !== false, (v) => { st.twoWay = v; }, 'Two-way: a new door also gets its door back in the other room')),
      h('div', { class: 'dim', style: { padding: '10px 12px', fontSize: '12px' } }, owners.length ? 'This is the entrance room of ' + owners.join(', ') + '. ' : 'Rooms reachable by ways from a building’s entrance room belong to that building. ',
        'A way is a tile (or several) that takes the player to another room.'),
      cards.length ? cards : h('div', { class: 'empty' }, others.length ? 'No way out of this room yet. Use the “Way to another room” tool and click floor tiles, or “+ Linked room”.' : 'Create a second room first: “+ Room” or “+ Linked room”.'));
  }

  // ---- materials
  function matUsers(sc, name) { return sc.rooms.filter((r) => r.floor === name || r.wall === name).length + sc.items.filter((it) => [it.mat, it.side, it.top, it.shade, ...Object.values(it.faces || {})].includes(name)).length; }
  function drawMaterials(body, sc) {
    const names = Object.keys(sc.materials);
    mount(body, h('div', { class: 'list' }, names.map((n) => { const m = sc.materials[n]; return h('div', { class: 'item', onclick: () => editMaterial(n) }, h('span', { class: 'swatch', style: { background: tintOf(sc, n, m.type) } }), h('span', {}, n), h('span', { class: 'sub dim' }, m.type + (m.image ? ' · image' : ' · ' + (m.preset || 'solid')))); })),
      h('div', { style: { padding: '10px', display: 'grid', gap: '6px' } }, h('button', { onclick: newMaterial }, '+ New material…'),
        h('div', { class: 'dim', style: { fontSize: '12px' } }, 'Materials are textures for floors, walls and props. Pick a preset, or draw your own. Atlas used: ' + st.used + ' / 512 rows.'),
        atlasBar()));
  }
  const atlasBar = () => h('div', { style: { height: '8px', background: 'var(--line)', borderRadius: '4px', overflow: 'hidden' } }, h('div', { style: { height: '100%', width: Math.min(100, st.used / 5.12) + '%', background: st.used > 480 ? 'var(--danger)' : 'var(--accent)' } }));
  async function newMaterial() {
    const sc = scene();
    const nm = h('input', { type: 'text', value: 'material' + (Object.keys(sc.materials).length + 1) });
    const typ = select([['floor', 'Floor (tiles)'], ['wall', 'Wall (wallpaper + wainscot)'], ['prop', 'Prop / furniture surface']], 'prop', () => {});
    if (!await modal('New material', h('div', { class: 'col' }, field('Name', nm), field('Type', typ)), [{ label: 'Cancel', value: false }, { label: 'Create', value: true, primary: true }])) return;
    const n = nm.value.replace(/[^a-z0-9_]/gi, '_'); if (!n || sc.materials[n]) { toast('Name missing or already used', 'error'); return; }
    sc.materials[n] = typ.value === 'prop' ? { type: 'prop', preset: 'gradient', colors: { c1: '#d8c8b0', c2: '#a08868' }, size: [16, 16] } : { type: typ.value, preset: 'plain' };
    changed(); drawLists(); preview(); editMaterial(n);
  }
  async function editMaterial(n) {
    const sc = scene(), m = sc.materials[n];
    const presets = m.type === 'floor' ? FLOOR_PRESETS : m.type === 'wall' ? WALL_PRESETS : PROP_PRESETS;
    const box = h('div', { class: 'col' });
    const draw = () => {
      const keys = ['c1', 'c2', 'c3', 'c4', 'c5'];
      const defaults = (st.presets && st.presets[m.type === 'wall' ? 'wall' : 'floor'] && st.presets[m.type === 'wall' ? 'wall' : 'floor'][m.preset]) || {};
      mount(box,
        field('Look', select([['', m.game_texture ? 'Game texture (from your dump)' : m.image ? 'Custom image' : '—'], ...presets.map((p) => [p, p.replace(/_/g, ' ')])].filter((x) => x[0] || m.image || m.game_texture), (m.image || m.game_texture) ? '' : (m.preset || ''), (v) => { if (v) { m.preset = v; delete m.image; delete m.game_texture; changed(); preview(); draw(); drawLists(); } })),
        (m.image || m.game_texture) ? null : h('div', { class: 'row wrap', style: { gap: '12px' } }, keys.slice(0, m.type === 'prop' ? 3 : 5).map((k) => h('label', { class: 'row', style: { gap: '4px' } }, h('span', { class: 'dim' }, k), colorInput((m.colors || {})[k] || defaults[k] || ['#c8c8d0', '#808090', '#ffffff'][keys.indexOf(k)] || '#888888', (v) => { m.colors = Object.assign({}, m.colors, { [k]: v }); changed(); preview(); })))),
        m.type === 'prop' ? h('div', { class: 'grid2' }, field('Width (px)', numInput((m.size || [16, 16])[0], (v) => { m.size = [Math.max(8, v), (m.size || [16, 16])[1]]; changed(); preview(); })), field('Height (px)', numInput((m.size || [16, 16])[1], (v) => { m.size = [(m.size || [16, 16])[0], Math.max(8, v)]; changed(); preview(); }))) : null,
        (m.preset === 'sign' || m.preset === 'text') && !m.image ? field('Text', textInput(m.text || '', (v) => { m.text = v; changed(); preview(); })) : null,
        h('div', { class: 'row' }, h('button', { onclick: () => { close(); drawImage(n); } }, m.image ? 'Edit the image…' : 'Draw by hand…'), m.image ? h('button', { onclick: () => { delete m.image; m.preset = m.preset || 'plain'; changed(); preview(); draw(); drawLists(); } }, 'Back to a preset') : null),
        h('div', { class: 'dim', style: { fontSize: '12px' } }, 'Used ' + matUsers(sc, n) + ' time(s).'));
    };
    draw();
    let close = () => {};
    modal('Material · ' + n, box, [{ label: 'Delete', value: () => { if (matUsers(sc, n)) { toast('Still in use: change the items/rooms that use it first', 'error'); return null; } delete sc.materials[n]; changed(); drawLists(); preview(); return 'del'; } }, { label: 'Done', value: true, primary: true }]).then(() => { drawLists(); });
    close = () => document.querySelector('.modal-bg') && document.querySelector('.modal-bg').remove();
  }
  async function drawImage(n) {
    const sc = scene(), m = sc.materials[n];
    const [w, hh] = m.type === 'floor' ? [32, 32] : m.type === 'wall' ? [32, 64] : (m.size || [16, 16]);
    const ed = new PixelEditor({});
    if (m.image) ed.load(await loadImage(`/api/project/${S.pid}/asset/${encodeURIComponent(m.image)}?t=${Date.now()}`));
    else { // start from the preset's look, rendered by the server
      try { const r = await post('/api/interior/preview', { scene: { ...sc, items: [], rooms: [{ id: 'main', rect: [1, 1, 3, 3], floor: n.startsWith('floor') || m.type === 'floor' ? n : undefined, wall: m.type === 'wall' ? n : undefined }], main: 'main', materials: { [n]: m }, palettes: {} }, project: S.pid }); const im = await dataImage(r.mesh.atlas); const rg = r.regions && r.regions['m:' + n]; ed.blank(w, hh, [200, 200, 200, 255]); if (rg) { const c = document.createElement('canvas'); c.width = w; c.height = hh; c.getContext('2d').drawImage(im, rg[0], rg[1], rg[2] - rg[0], rg[3] - rg[1], 0, 0, w, hh); ed.load(c); } } catch (e) { ed.blank(w, hh, [200, 200, 200, 255]); }
    }
    const holder = h('div', { style: { width: '760px', maxWidth: '84vw', height: '520px' } }, ed.el);
    setTimeout(() => ed.fit(), 40);
    const r = await modal('Draw · ' + n + ' (' + ed.w + '×' + ed.h + ')', holder, [{ label: 'Cancel', value: false }, { label: 'Use this image', value: true, primary: true }]);
    ed.destroy();
    if (r) { const name = 'mat_' + n + '.png'; await put(`/api/project/${S.pid}/asset/${name}`, await ed.toBlob()); m.image = name; if (m.type === 'prop') m.size = [ed.w, ed.h]; changed(); preview(); drawLists(); }
  }

  // ---- adding things
  const lib = { q: '', results: [], sel: null, vw: null, models: null };
  function drawAdd(body, sc) {
    const start = (o) => { st.placing = o; st.tool = 'select'; drawToolbar(); hintText(); toast('Now click on the plan', 'info', 1500); };
    const matSel = h('select', {}, Object.keys(sc.materials).filter((n) => sc.materials[n].type === 'prop').concat(Object.keys(sc.materials).filter((n) => sc.materials[n].type !== 'prop')).map((n) => h('option', { value: n }, n)));
    const palSel = h('select', {}, Object.keys(sc.palettes).map((n) => h('option', { value: n }, n)));
    const prims = [['box', 'Box'], ['cyl', 'Cylinder'], ['flat', 'Rug / floor decal'], ['lamp', 'Lamp'], ['extrude', 'Tub / pedestal'], ['quad', 'Picture / poster'], ['wallquad', 'Wall panel']];
    const search = h('input', { type: 'search', placeholder: 'Search furniture (e.g. lov_bed, rmk_apl, int_)…', value: lib.q });
    const res = h('div', { class: 'list', style: { maxHeight: '260px', overflow: 'auto' } });
    const info = h('div', { class: 'dim', style: { fontSize: '12px' } });
    const doSearch = debounce(async () => { lib.q = search.value; lib.results = await get('/api/game/models?' + q({ prefix: '/Item/Model/', q: search.value || 'rmk_' })); mount(res, lib.results.slice(0, 120).map((p) => h('div', { class: 'item' + (lib.sel === p ? ' on' : ''), onclick: () => pickModel(p) }, p.split('/').pop().replace('.bcres', '')))); }, 150);
    async function pickModel(p) {
      lib.sel = p; info.textContent = 'Measuring…'; mount(res, lib.results.slice(0, 120).map((x) => h('div', { class: 'item' + (lib.sel === x ? ' on' : ''), onclick: () => pickModel(x) }, x.split('/').pop().replace('.bcres', ''))));
      try {
        const m = await get('/api/game/mesh?path=' + encodeURIComponent(p)); const [mn, mx] = boundsOf(m.parts);
        const fp = [Math.max(8, Math.round(mx[0] - mn[0])), Math.max(8, Math.round(mx[2] - mn[2]))];
        lib.fp = fp; info.textContent = `Footprint about ${fp[0]} × ${fp[1]} units (${(fp[0] / T).toFixed(1)} × ${(fp[1] / T).toFixed(1)} tiles). Its texture is added to the atlas.`;
        start({ type: 'game', path: p, fp });
      } catch (e) { info.textContent = 'Cannot read this model: ' + e.message; }
    }
    search.addEventListener('input', doSearch);
    // your own models: files exported from Blender, kept in the project (assets/mdl_<name>__<file>)
    const MODEL_EXT = ['.glb', '.gltf', '.obj', '.stl', '.ply'];
    const extOf = (n) => (String(n).match(/\.[^.]+$/) || [''])[0].toLowerCase();
    const cleanName = (n) => n.replace(/[^A-Za-z0-9._-]/g, '_');
    const refreshModels = async () => { try { lib.models = (await get('/api/project/' + S.pid + '/assets')).filter((n) => /^mdl_.+__.+/.test(n) && MODEL_EXT.includes(extOf(n))); } catch (e) { lib.models = []; } if (st.tab === 'add') drawLists(); };
    async function placeModel(asset) {
      try {
        const m = await post('/api/model/info', { project: S.pid, asset, up: 'y' });
        const scale = Math.round(40 / Math.max(...m.size, 1e-6) * 1e4) / 1e4;       // the biggest side is about 40 units (a bit over a tile) to start with
        m.notes.forEach((x) => toast(x, 'info', 6000));
        toast(m.triangles + ' triangles' + (m.triangles > 5000 ? ': heavy for a 3DS, consider a Decimate modifier in Blender' : ''), m.triangles > 5000 ? 'info' : 'ok', 4000);
        start({ type: 'custom', asset, scale, fp: [m.size[0], m.size[2]], size: m.size });
      } catch (e) { toast(e.message, 'error'); }
    }
    async function importModels() {
      const files = await pickFiles(MODEL_EXT.concat(['.mtl', '.bin', '.png', '.jpg', '.jpeg']).join(','));
      if (!files.length) return;
      const main = files.filter((f) => MODEL_EXT.includes(extOf(f.name))).sort((a, b) => MODEL_EXT.indexOf(extOf(a.name)) - MODEL_EXT.indexOf(extOf(b.name)))[0];
      if (!main) { toast('Choose a .glb, .gltf, .obj, .stl or .ply file (with its .mtl / .bin / textures selected too, if it has them)', 'error', 7000); return; }
      const base = main.name.replace(/\.[^.]+$/, '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'model', prefix = 'mdl_' + base + '__';
      try {
        for (const f of files) await put('/api/project/' + S.pid + '/asset/' + encodeURIComponent(prefix + cleanName(f.name)), f);
        await refreshModels(); changed();
        await placeModel(prefix + cleanName(main.name));
      } catch (e) { toast(e.message, 'error'); }
    }
    async function deleteModel(asset) {
      const used = P.interiors.filter((x) => x.items.some((i) => i.asset === asset));
      if (used.length) { toast('Still placed in ' + used.map((x) => x.title || x.id).join(', ') + ': delete those items first', 'error'); return; }
      if (!await confirmBox('Delete the model ' + modelLabel(asset) + ' and its texture files from the project?', 'Delete')) return;
      const prefix = asset.split('__')[0] + '__';
      for (const n of await get('/api/project/' + S.pid + '/assets')) if (n.startsWith(prefix)) await del('/api/project/' + S.pid + '/asset/' + encodeURIComponent(n));
      refreshModels();
    }
    if (!lib.models) refreshModels();
    const modelsCard = h('div', { class: 'card' }, h('h3', {}, 'Your 3D models'),
      h('button', { class: 'primary', onclick: importModels }, 'Import a model…'),
      h('div', { class: 'dim', style: { fontSize: '12px', margin: '6px 0' } }, 'From Blender: File → Export → glTF 2.0 (.glb, recommended: one file with its textures), Wavefront (.obj, also pick the .mtl and the images), STL or PLY (no colours). Select all the files of one model together. Importing the same name again updates the model.'),
      (lib.models || []).length ? h('div', { class: 'list' }, lib.models.map((a) => h('div', { class: 'item', title: 'Click, then click the plan to place it', onclick: () => placeModel(a) }, h('span', {}, modelLabel(a)),
        h('button', { class: 'small ghost danger sub', title: 'Remove from the project', onclick: (e) => { e.stopPropagation(); deleteModel(a); } }, '×')))) : h('div', { class: 'dim', style: { fontSize: '12px' } }, 'No model imported yet.'));
    mount(body, h('div', { style: { padding: '10px', display: 'grid', gap: '10px' } }, modelsCard,
      h('div', { class: 'card' }, h('h3', {}, 'Shapes'), h('label', { class: 'field' }, h('span', {}, 'Material'), matSel),
        h('div', { class: 'pill-row', style: { marginTop: '8px' } }, prims.map(([t, l]) => h('button', { onclick: () => { if (!matSel.value) { toast('Create a material first', 'error'); return; } start({ type: t, mat: matSel.value, noblock: false }); } }, l)))),
      h('div', { class: 'card' }, h('h3', {}, 'Beds'), Object.keys(sc.palettes).length ? h('div', { class: 'col' }, h('label', { class: 'field' }, h('span', {}, 'Palette'), palSel),
        h('div', { class: 'pill-row' }, h('button', { onclick: () => start({ type: 'bed', palette: palSel.value }) }, 'Bed'), h('button', { onclick: () => start({ type: 'stand', palette: palSel.value }) }, 'Bedside table'))) : h('div', { class: 'dim' }, 'No bed palette yet.'),
        h('button', { style: { marginTop: '8px' }, onclick: async () => { const n = await prompt('New bed palette', 'Name', 'palette' + (Object.keys(sc.palettes).length + 1)); if (!n) return; sc.palettes[n.replace(/[^a-z0-9_]/gi, '_')] = { wood: '#7a4a2a', wood_dark: '#4a2a18', accent: '#d03050', accent_light: '#ff8098', sheet: '#f4eee6', sheet_dark: '#d8d0c8' }; changed(); drawLists(); preview(); } }, '+ New palette'),
        Object.keys(sc.palettes).length ? h('details', {}, h('summary', {}, 'Edit palettes'), Object.entries(sc.palettes).map(([n, pal]) => h('div', { class: 'card', style: { marginTop: '6px' } }, h('div', { class: 'row', style: { justifyContent: 'space-between' } }, h('b', {}, n), h('button', { class: 'small ghost danger', onclick: () => { if (sc.items.some((i) => i.palette === n)) { toast('Used by a bed or bedside table', 'error'); return; } delete sc.palettes[n]; changed(); drawLists(); preview(); } }, 'delete')),
          h('div', { class: 'row wrap' }, ['wood', 'wood_dark', 'accent', 'accent_light', 'sheet', 'sheet_dark'].map((k) => h('label', { class: 'row', style: { gap: '4px' } }, h('span', { class: 'dim', style: { fontSize: '11px' } }, k.replace('_', ' ')), colorInput(pal[k] || '#888888', (v) => { pal[k] = v; changed(); preview(); }))))))) : null),
      h('div', { class: 'card' }, h('h3', {}, 'Game furniture'), search, res, info)));
    if (!lib.results.length) doSearch();
  }

  // ================================================================ inspector
  const insp = h('div', { class: 'pad', style: { padding: '12px', display: 'flex', flexDirection: 'column', gap: '10px', overflow: 'auto', flex: 1, borderTop: '1px solid var(--line)' } });
  function matPick(sc, cur, on, allowNone) {
    const names = Object.keys(sc.materials);
    const extra = ['trim', 'lip'].filter((x) => !names.includes(x));
    const palRegions = []; for (const p of Object.keys(sc.palettes)) for (const part of ['frame', 'sheet', 'head', 'stand', 'pillow']) palRegions.push('bed:' + p + ':' + part);
    const opts = [...(allowNone ? [['', '(none)']] : []), ...names, ...extra, ...palRegions];
    if (cur && !opts.some((o) => (Array.isArray(o) ? o[0] : o) === cur)) opts.push(cur);
    return select(opts, cur || '', (v) => { on(v); changed(); preview(); drawPlan(); });
  }
  function drawInspector(light) {
    const sc = scene();
    if (!sc || !st.sel) { mount(insp, h('div', { class: 'dim' }, sc ? 'Select an area or an item on the plan.' : ''), sc ? entranceCard(sc) : null); return; }
    if (st.sel.kind === 'items') return drawMultiInspector(sc);
    if (st.sel.kind === 'room') return drawRoomInspector(sc, light);
    const it = sc.items.find((i) => i.id === st.sel.id); if (!it) { mount(insp); return; }
    const n = (k, label, step = 1) => field(label, numInput(Number(it[k]).toString(), (v) => { it[k] = v; changed(); preview(); drawPlan(); }, { step }));
    const mp = (k, label, none) => field(label, matPick(sc, it[k], (v) => { if (v) it[k] = v; else delete it[k]; }, none));
    const rows = [];
    switch (it.type) {
      case 'box': rows.push(h('div', { class: 'grid2' }, n('x0', 'x from'), n('x1', 'x to'), n('z0', 'z from (back)'), n('z1', 'z to (front)'), n('y0', 'Bottom'), n('y1', 'Top')), mp('mat', 'Material (all sides)'), mp('top', 'Top face', true)); it.faces = it.faces || {}; rows[rows.length - 1] = field('Top face', matPick(sc, it.faces.top, (v) => { if (v) it.faces.top = v; else delete it.faces.top; }, true)); break;
      case 'cyl': rows.push(h('div', { class: 'grid2' }, n('cx', 'Centre x'), n('cz', 'Centre z'), n('r', 'Radius'), n('n', 'Sides'), n('y0', 'Bottom'), n('y1', 'Top')), mp('side', 'Side'), mp('top', 'Top', true)); break;
      case 'flat': rows.push(h('div', { class: 'grid2' }, n('x0', 'x from'), n('x1', 'x to'), n('z0', 'z from'), n('z1', 'z to'), n('y', 'Height', 0.1)), mp('mat', 'Material')); break;
      case 'lamp': rows.push(h('div', { class: 'grid2' }, n('x', 'x'), n('z', 'z')), mp('shade', 'Shade material')); break;
      case 'extrude': rows.push(h('div', { class: 'grid2' }, n('cx', 'Centre x'), n('cz', 'Centre z'), n('size', 'Size'), n('y1', 'Height'), n('top_y', 'Top surface height')), field('Shape', select(['circle', 'oval', 'heart'], it.shape, (v) => { it.shape = v; changed(); preview(); drawPlan(); })), mp('side', 'Side'), mp('top', 'Top')); break;
      case 'bed': case 'stand': rows.push(h('div', { class: 'grid2' }, n('x', 'x'), n('z', 'z'), it.type === 'bed' ? field('Rotation', select([[0, 'Head at back'], [90, 'Head at left'], [180, 'Head at front'], [270, 'Head at right']], it.rot || 0, (v) => { it.rot = Number(v); changed(); preview(); drawPlan(); })) : null), field('Palette', select(Object.keys(sc.palettes), it.palette, (v) => { it.palette = v; changed(); preview(); drawPlan(); }))); break;
      case 'game': rows.push(h('div', { class: 'dim', style: { fontSize: '12px' } }, it.path), h('div', { class: 'grid2' }, n('x', 'x'), n('z', 'z'), field('Rotation', select([[0, '0°'], [90, '90°'], [180, '180°'], [270, '270°']], it.rot || 0, (v) => { it.rot = Number(v); changed(); preview(); drawPlan(); })), n('scale', 'Scale', 0.05), n('tex_cap', 'Texture detail (px)')),
        h('div', { class: 'grid3' }, field('Hue shift°', numInput((it.recolor || {}).h || 0, (v) => { it.recolor = Object.assign({}, it.recolor, { h: v }); changed(); preview(); })), field('Saturation ×', numInput((it.recolor || {}).s ?? 1, (v) => { it.recolor = Object.assign({}, it.recolor, { s: v }); changed(); preview(); }, { step: 0.1 })), field('Brightness ×', numInput((it.recolor || {}).v ?? 1, (v) => { it.recolor = Object.assign({}, it.recolor, { v }); changed(); preview(); }, { step: 0.1 })))); break;
      case 'custom': rows.push(customRows(sc, it, n)); break;
      case 'quad': rows.push(h('div', { class: 'dim', style: { fontSize: '12px' } }, 'Four corners (x, y height, z), counter-clockwise seen from the front.'), ...it.pts.map((p, i) => h('div', { class: 'grid3' }, [0, 1, 2].map((k) => field('p' + (i + 1) + ' ' + 'xyz'[k], numInput(p[k], (v) => { p[k] = v; changed(); preview(); drawPlan(); }))))), mp('mat', 'Material')); break;
      case 'wallquad': rows.push(h('div', { class: 'grid2' }, field('Start x', numInput(it.a[0], (v) => { it.a[0] = v; changed(); preview(); drawPlan(); })), field('Start z', numInput(it.a[1], (v) => { it.a[1] = v; changed(); preview(); drawPlan(); })), field('End x', numInput(it.b[0], (v) => { it.b[0] = v; changed(); preview(); drawPlan(); })), field('End z', numInput(it.b[1], (v) => { it.b[1] = v; changed(); preview(); drawPlan(); })), n('h', 'Height')), mp('mat', 'Material'), checkbox(it.both, (v) => { it.both = v; changed(); preview(); }, 'Visible from both sides')); break;
    }
    const blockTxt = h('input', { type: 'text', value: (it.block || []).map((b) => b.join(',')).join('  '), placeholder: 'e.g. 3,4  4,4' });
    blockTxt.addEventListener('change', () => { it.block = blockTxt.value.split(/\s+/).filter(Boolean).map((s) => s.split(',').map(Number)).filter((b) => b.length === 2 && b.every((v) => !isNaN(v))); if (!it.block.length) delete it.block; changed(); preview(); drawPlan(); });
    const liftRow = field('Height above the floor (up / down)', h('div', { class: 'row' }, numInput(it.lift || 0, (v) => { if (v) it.lift = v; else delete it.lift; changed(); preview(); }, { step: 1, style: { flex: 1 } }),
      h('button', { class: 'small', title: 'Raise (PgUp)', onclick: () => { plan.lift(it, 2); changed(); preview(); drawInspector(); } }, '▲'),
      h('button', { class: 'small', title: 'Lower (PgDn)', onclick: () => { plan.lift(it, -2); changed(); preview(); drawInspector(); } }, '▼')), 'Lifts the whole item (a clock higher on the wall, a lamp on a table). PgUp / PgDn; Alt for 1 unit.');
    mount(insp, h('div', { class: 'row' }, h('b', {}, TYPE_LABEL[it.type] || it.type), h('span', { class: 'dim' }, it.id), h('div', { class: 'grow' }),
      h('button', { class: 'small', onclick: () => duplicate(it) }, 'Duplicate'), h('button', { class: 'small danger', onclick: () => { sc.items.splice(sc.items.indexOf(it), 1); setSel([]); changed(); drawAll(); preview(); } }, 'Delete')),
      rows, liftRow,
      plan.VISUAL.has(it.type) ? null : h('div', { class: 'card' }, h('h3', {}, 'Collision'), field('Blocked floor tiles (x,y …)', blockTxt, 'Tiles the player cannot walk onto; doorways must stay free.'),
        h('button', { class: 'small', onclick: () => { it.block = plan.blocksFor(it); if (!it.block.length) delete it.block; changed(); preview(); drawAll(); } }, 'Fit to the footprint')));
  }
  function drawMultiInspector(sc) {
    const its = selItems(), counts = {}; its.forEach((i) => { counts[TYPE_LABEL[i.type] || i.type] = (counts[TYPE_LABEL[i.type] || i.type] || 0) + 1; });
    const al = (m, label, title) => h('button', { class: 'small', title, onclick: () => align(m) }, label);
    mount(insp, h('div', { class: 'row' }, h('b', {}, its.length + ' items selected'), h('div', { class: 'grow' }),
        h('button', { class: 'small', onclick: () => duplicate(its) }, 'Duplicate'), h('button', { class: 'small danger', onclick: () => { sc.items = sc.items.filter((i) => !st.multi.has(i.id)); setSel([]); changed(); drawAll(); preview(); } }, 'Delete')),
      h('div', { class: 'dim', style: { fontSize: '12px' } }, Object.entries(counts).map(([k, n]) => n + ' × ' + k).join(', ')),
      h('div', { class: 'card' }, h('h3', {}, 'Up / down'), h('div', { class: 'pill-row' },
        h('button', { class: 'small', onclick: () => { its.forEach((i) => plan.lift(i, 4)); changed(); drawAll(); preview(); } }, '▲ Raise 4'), h('button', { class: 'small', onclick: () => { its.forEach((i) => plan.lift(i, -4)); changed(); drawAll(); preview(); } }, '▼ Lower 4'),
        h('button', { class: 'small', onclick: () => { its.forEach((i) => { delete i.lift; }); changed(); drawAll(); preview(); } }, 'Back to the floor'))),
      h('div', { class: 'card' }, h('h3', {}, 'Align'), h('div', { class: 'pill-row' }, al('left', '⇤ Left', 'Align left edges'), al('hcenter', '⇔ Centre', 'Centre horizontally'), al('right', '⇥ Right', 'Align right edges'),
        al('top', '⤒ Top', 'Align top (back) edges'), al('vcenter', '⇕ Middle', 'Centre vertically'), al('bottom', '⤓ Bottom', 'Align bottom (front) edges'))),
      h('div', { class: 'dim', style: { fontSize: '12px' } }, 'Drag any selected item to move them all; arrows nudge (Shift: a tile, Alt: 1 unit), PgUp / PgDn raise and lower, R rotates, Delete removes, Ctrl+D duplicates. Ctrl/Shift-click adds or removes one; drag on empty floor to select a box; Ctrl+A selects everything.'));
  }
  function drawRoomInspector(sc, light) {
    const r = sc.rooms.find((x) => x.id === st.sel.id); if (!r) { mount(insp); return; }
    const rect = (i, label) => field(label, numInput(r.rect[i], (v) => { r.rect[i] = Math.max(0, Math.min(GRID - 1, v)); changed(); preview(); drawPlan(); }));
    const mats = (type) => Object.keys(sc.materials).filter((n) => sc.materials[n].type === type);
    mount(insp, h('div', { class: 'row' }, h('b', {}, 'Room'), h('span', { class: 'dim' }, r.id), h('div', { class: 'grow' }), r.id !== sc.main ? h('button', { class: 'small danger', onclick: delRoom }, 'Delete') : h('span', { class: 'chip' }, 'main room')),
      field('Name', textInput(r.name || '', (v) => { r.name = v; changed(); drawPlan(); drawLists(); })),
      h('div', { class: 'grid2' }, rect(0, 'x from'), rect(2, 'x to'), rect(1, 'y from'), rect(3, 'y to')),
      field('Floor', select(mats('floor'), r.floor, (v) => { r.floor = v; changed(); preview(); drawPlan(); })), field('Walls', select(mats('wall'), r.wall, (v) => { r.wall = v; changed(); preview(); })),
      r.id !== sc.main ? signCard(r) : null,
      r.id !== sc.main ? h('div', { class: 'dim', style: { fontSize: '12px' } }, 'Doorways: ' + ((r.doors || []).map((d) => d.join(',')).join('  ') || 'none') + '. Use the Doorway tool. (To walk into a separate room instead, use “Way to another room”.)') : h('label', { class: 'dim' }, 'Doorways from the main room lead into the other rooms.'),
      r.id !== sc.main ? h('button', { class: 'small', onclick: () => { sc.main = r.id; changed(); drawAll(); preview(); } }, 'Make this the main room (entrance)') : null);
  }

  // ---- the sign over a doorway: text, colours, font and look (it shrinks / wraps to fit; one sign per group of doorway tiles)
  const SIGN_DEFAULTS = { fg: '#ffeef4', bg: '#784632', outline: '#78143c', frame: '#e6be5a' };
  function signCard(r) {
    const lc = () => { r.label_colors = r.label_colors || {}; return r.label_colors; };
    const col = (k, label) => h('label', { class: 'row', style: { gap: '4px' } }, h('span', { class: 'dim', style: { fontSize: '11px' } }, label), colorInput((r.label_colors || {})[k] || SIGN_DEFAULTS[k], (v) => { lc()[k] = v; changed(); preview(); }));
    const outlineOn = !r.label_colors || r.label_colors.outline !== '';
    const fontIn = h('input', { type: 'text', list: 'fontlist', value: r.label_font || '', placeholder: 'default (bold serif)' });
    fontIn.addEventListener('change', () => { if (fontIn.value) r.label_font = fontIn.value; else delete r.label_font; changed(); preview(); });
    return h('div', { class: 'card' }, h('h3', {}, 'Sign over the doorway'),
      field('Text', textInput(r.label || '', (v) => { if (v) r.label = v; else delete r.label; changed(); preview(); }), 'Shrinks and wraps to fit the doorway; a wider doorway gives a wider sign. Each separate doorway gets one.'),
      h('div', { class: 'row wrap', style: { gap: '12px', margin: '6px 0' } }, col('fg', 'text'), col('bg', 'background'), col('frame', 'frame'), col('outline', 'outline')),
      checkbox(outlineOn, (v) => { if (v) { if (r.label_colors) delete r.label_colors.outline; } else lc().outline = ''; changed(); preview(); drawInspector(); }, 'Outline around the letters'),
      h('div', { class: 'grid2', style: { marginTop: '6px' } },
        field('Look', select([['plate', 'Plate (framed)'], ['flat', 'Flat panel'], ['neon', 'Neon (bars top and bottom)']], r.label_style || 'plate', (v) => { r.label_style = v; changed(); preview(); })),
        field('Letter detail', select([['auto', 'Automatic'], ['normal', 'Normal (small file)'], ['high', 'High (sharper, uses more atlas)']], r.label_detail || 'auto', (v) => { r.label_detail = v; changed(); preview(); }))),
      field('Font', fontIn, 'Any installed font; start typing for the list (e.g. LiberationSerif-Italic, Montserrat-Bold).'),
      h('datalist', { id: 'fontlist' }, (st.fonts || []).map((f) => h('option', { value: f }))));
  }

  // ---- where the player comes in (the door can be on any edge)
  // the player must be able to walk from the door into the main area: stretch it to the edge the door is on
  function fitMainToDoor(sc, e) {
    const m = sc.rooms.find((r) => r.id === sc.main); if (!m) return null;
    const d = e.door, xs = d.map((t) => t[0]), ys = d.map((t) => t[1]);
    const r = m.rect.slice(), b = e.bounds;
    if (e.side === 'east') { r[2] = b[2]; r[1] = Math.min(r[1], Math.min(...ys)); r[3] = Math.max(r[3], Math.max(...ys)); }
    else if (e.side === 'west') { r[0] = b[0]; r[1] = Math.min(r[1], Math.min(...ys)); r[3] = Math.max(r[3], Math.max(...ys)); }
    else if (e.side === 'north') { r[1] = b[1]; r[0] = Math.min(r[0], Math.min(...xs)); r[2] = Math.max(r[2], Math.max(...xs)); }
    else { r[3] = Math.max(r[3], 13); r[0] = Math.min(r[0], Math.min(...xs)); r[2] = Math.max(r[2], Math.max(...xs)); }
    if (r.join() === m.rect.join()) return true;
    if (r[0] < b[0] || r[1] < b[1] || r[2] > b[2] || r[3] > b[3]) return false;
    if (sc.rooms.some((o) => o !== m && !(r[2] < o.rect[0] || r[0] > o.rect[2] || r[3] < o.rect[1] || r[1] > o.rect[3]))) return false;
    m.rect = r; return true;
  }
  function entranceCard(sc) {
    const ent = plan.entrance(sc), max = ent.side === 'south' || ent.side === 'north' ? GRID - 2 : GRID - 4;
    const at = ent.side === 'south' || ent.side === 'north' ? ent.door[0][0] : ent.door[0][1];
    const set = (side, pos) => {
      sc.entrance = side; sc.entrance_at = Math.max(0, Math.min(side === 'south' || side === 'north' ? GRID - 2 : GRID - 4, pos));
      const e2 = plan.entrance(sc); sc.door = e2.door; sc.exit = e2.exit;
      const stretched = fitMainToDoor(sc, e2);
      changed(); drawAll(); preview();
      if (stretched === false) toast('The main area could not be stretched to the door (another area is in the way): move that area', 'error');
      const bad = sc.rooms.filter((r) => side !== 'south' && (r.rect[0] < e2.bounds[0] || r.rect[1] < e2.bounds[1] || r.rect[2] > e2.bounds[2] || r.rect[3] > e2.bounds[3]));
      if (bad.length) toast('Area ' + bad.map((r) => r.name || r.id).join(', ') + ' reaches into the entrance strip: move or shrink it', 'error');
    };
    return h('div', { class: 'card', style: { margin: '8px' } }, h('h3', {}, 'Entrance (door)'),
      field('The door is on the', select(plan.SIDES, ent.side, (v) => set(v, v === ent.side ? at : 7))),
      field('Position along that edge (tile of the first door tile)', numInput(at, (v) => set(ent.side, v), { min: 0, max, step: 1 })),
      h('div', { class: 'dim', style: { fontSize: '12px', marginTop: '4px' } }, ent.side === 'south' ? 'The original: the door in the front wall, the player walks in facing north.' : 'The two rows or columns along that edge are kept free for the doorway. The player appears there facing into the room.'));
  }

  // ---- your own 3D models (Blender exports)
  function customRows(sc, it, n) {
    const sz = it.size, k = it.scale || 1;
    return h('div', { class: 'col', style: { gap: '8px' } },
      h('div', { class: 'dim', style: { fontSize: '12px' } }, modelLabel(it.asset) + (sz ? ' · ' + sz.map((v) => (v * k).toFixed(0)).join(' × ') + ' units (w × h × d), ' + ((sz[1] * k) / T).toFixed(1) + ' tiles tall' : '')),
      h('div', { class: 'grid2' }, n('x', 'x'), n('z', 'z'), n('rot', 'Rotation (degrees)', 15), n('scale', 'Scale', 0.05),
        sz ? field('Fit to height (units)', numInput(Math.round(sz[1] * k), (v) => { if (v > 0) { it.scale = v / sz[1]; changed(); preview(); drawPlan(); } }, { step: 4 })) : null, n('tex_cap', 'Texture detail (px)')),
      h('div', { class: 'grid2' }, field('Model’s up axis', select([['y', 'Y up (glTF, Blender OBJ)'], ['z', 'Z up (STL, PLY, raw Blender)']], it.up || 'y', (v) => { it.up = v; remeasure(it); })),
        h('div', { style: { alignSelf: 'end' } }, checkbox(it.flip, (v) => { it.flip = v; changed(); preview(); }, 'Flip faces (inside-out)'))));
  }
  async function remeasure(it) {
    try { const m = await post('/api/model/info', { project: S.pid, asset: it.asset, up: it.up || 'y', flip: !!it.flip }); it.size = m.size; it.fp = [m.size[0], m.size[2]]; changed(); drawAll(); preview(); }
    catch (e) { toast(e.message, 'error'); }
  }

  // ================================================================ 3D preview
  const vcanvas = h('canvas', { style: { width: '100%', height: '320px', background: '#8cb8e6' } });
  const msgs = h('div', { class: 'col', style: { padding: '8px 12px', gap: '6px' } });
  let viewer = null, firstFrame = true;
  const vbar = h('div', { class: 'toolbar' }, ['Front', 'Top', 'Left', 'Right'].map((n) => h('button', { class: 'small', onclick: () => { if (!viewer) return; const v = { Front: [0, 0.75], Top: [0, 1.5], Left: [-1.0, 0.7], Right: [1.0, 0.7] }[n]; viewer.yaw = v[0]; viewer.pitch = v[1]; viewer.dirty = true; } }, n)), h('div', { class: 'grow' }), h('span', { class: 'dim', style: { fontSize: '12px' } }, '3D'));
  mount(right, vbar, vcanvas, msgs, insp);
  let seq = 0;
  const preview = debounce(async () => {
    const sc = scene(); const my = ++seq;
    if (!sc) { if (viewer) viewer.setParts([]); mount(msgs); return; }
    let r; try { r = await post('/api/interior/preview', { scene: sc, project: S.pid }); } catch (e) { mount(msgs, h('div', { class: 'err-box' }, e.message)); return; }
    if (my !== seq) return;
    if (r.error) { mount(msgs, h('div', { class: 'err-box' }, r.error)); return; }
    st.problems = r.problems; st.used = r.atlas_used; st.tris = r.triangles; st.regions = r.regions;
    mount(msgs, r.problems.map((p) => h('div', { class: 'err-box' }, p)), (r.warnings || []).map((w) => h('div', { class: 'warn-box' }, w)), h('div', { class: 'row dim', style: { fontSize: '12px' } }, `${r.triangles} triangles · atlas ${r.atlas_used}/512 rows`, h('div', { style: { flex: 1 } }, atlasBar())));
    if (!viewer) { try { viewer = new Viewer(vcanvas, { light: [0.2, 1, 0.4], bg: [0.45, 0.62, 0.8] }); } catch (e) { console.error('viewer', e); viewer = null; } if (!viewer || !viewer.ok) return; }
    const img = await dataImage(r.mesh.atlas);
    viewer.setParts([{ ...r.mesh, image: img }]);
    if (firstFrame) { viewer.target = [256, 20, 250]; viewer.dist = 640; viewer.yaw = 0; viewer.pitch = 0.75; firstFrame = false; }
    if (st.tab === 'mats') drawLists();
  }, 450);

  function drawAll() { drawToolbar(); hintText(); drawLeft(); drawInspector(); drawPlan(); }
  get('/api/interior/presets').then((p) => { st.presets = p; drawPlan(); });
  get('/api/fonts').then((f) => { st.fonts = f; }).catch(() => {});
  drawAll(); preview.now(); snapshot();
  return () => { window.removeEventListener('keydown', onKey); };
}
