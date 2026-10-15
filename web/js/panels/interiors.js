import { get, post, put, q } from '../api.js';
import { S, changed as saveChanged, uid } from '../state.js';
import { h, mount, toast, select, debounce, field, textInput, numInput, colorInput, checkbox, modal, prompt, confirmBox, loadImage } from '../ui.js';
import { Viewer, dataImage, boundsOf } from '../viewer.js';
import { PixelEditor } from '../pixel.js';
import * as plan from '../plan.js';
import { newInterior } from './buildings.js';

export const id = 'interiors', title = 'Interiors', icon = '▣', needsProject = true;
const { T, GRID, WORLD } = plan;
const SCALE = 36 / T;                                   // canvas px per world unit
const TYPE_LABEL = { box: 'Box', cyl: 'Cylinder', flat: 'Rug / floor decal', quad: 'Picture / poster', wallquad: 'Wall panel', lamp: 'Lamp', extrude: 'Tub / pedestal', bed: 'Bed', stand: 'Bedside table', game: 'Game furniture' };
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
  const restore = (i) => { const sc = scene(); if (!sc || i < 0 || i >= hist.stack.length) return; commitSoon.now(); hist.at = i; const j = JSON.parse(hist.stack[i]); for (const k of Object.keys(sc)) delete sc[k]; Object.assign(sc, j); st.sel = null; saveChanged(); drawAll(); preview(); };
  const undo = () => { commitSoon.now(); restore(hist.at - 1); };
  const redo = () => { restore(hist.at + 1); };
  const st = { sid: (preset && preset.interior) || (P.interiors[0] && P.interiors[0].id) || null, tool: 'select', sel: null, tab: 'items', placing: null, drag: null, hover: null, problems: [], used: 0, tris: 0, presets: null, flash: 0 };
  const scene = () => P.interiors.find((s) => s.id === st.sid);

  const left = h('div', { class: 'pane', style: { display: 'flex', flexDirection: 'column' } });
  const mid = h('div', { class: 'pane pad', style: { display: 'flex', flexDirection: 'column', gap: '10px' } });
  const right = h('div', { class: 'pane', style: { display: 'flex', flexDirection: 'column' } });
  mount(root, h('div', { class: 'page-head' }, h('h2', {}, 'Interiors'), h('p', {}, 'Lay out rooms and place furniture on the 16 × 16 plan. The 3D view updates as you work.')),
    h('div', { class: 'split', style: { gridTemplateColumns: '270px 620px minmax(300px,1fr)' } }, left, mid, right));

  // ================================================================ plan canvas
  const cv = h('canvas', { width: GRID * 36, height: GRID * 36, style: { width: GRID * 36 + 'px', height: GRID * 36 + 'px', cursor: 'default', touchAction: 'none', alignSelf: 'center' } });
  const toolbar = h('div', { class: 'toolbar', style: { border: '1px solid var(--line)', borderRadius: '6px' } });
  const hint = h('div', { class: 'dim', style: { fontSize: '12px', minHeight: '32px' } });
  mount(mid, toolbar, cv, hint);

  const sceneNames = () => P.interiors.map((s) => [s.id, s.title || s.id]);
  function drawToolbar() {
    const tools = [['select', '↖ Select / move', 'V'], ['room', '▭ Draw room', 'U'], ['door', '⌷ Doorway', 'D']];
    mount(toolbar,
      P.interiors.length ? (() => { const s = select(sceneNames(), st.sid, (v) => { st.sid = v; st.sel = null; st.placing = null; drawAll(); preview.now(); }); s.style.width = '170px'; return s; })() : null,
      h('button', { class: 'small', onclick: addScene }, '+ New'),
      P.interiors.length ? h('button', { class: 'small ghost', onclick: renameScene }, 'Rename') : null,
      P.interiors.length ? h('button', { class: 'small ghost danger', onclick: delScene }, 'Delete') : null,
      h('button', { class: 'small ghost', title: 'Undo (Ctrl+Z)', onclick: undo }, '↶'), h('button', { class: 'small ghost', title: 'Redo (Ctrl+Y)', onclick: redo }, '↷'),
      h('div', { class: 'sep-v' }),
      tools.map(([id, label, key]) => h('button', { class: 'small' + (st.tool === id && !st.placing ? ' on' : ''), title: label + ' (' + key + ')', onclick: () => { st.tool = id; st.placing = null; drawToolbar(); hintText(); } }, label)),
      st.placing ? h('span', { class: 'chip warn' }, 'placing: ' + (TYPE_LABEL[st.placing.type] || st.placing.type) + ' — click the plan, Esc to stop') : null);
  }
  function hintText() {
    const t = st.placing ? 'Click on the plan to place it. Hold Shift to place several.' : { select: 'Click an item or room to select it; drag to move; arrows nudge, R rotates, Del deletes.', room: 'Drag on the empty grid to add a room (any tile not inside a room is a low partition wall).', door: 'Select a room first, then click floor tiles beside it to make doorways to the main room.' }[st.tool];
    hint.textContent = t;
  }
  async function addScene() {
    const t = await prompt('New interior', 'Name', 'My interior'); if (!t) return;
    const sc = newInterior(P, t); P.interiors.push(sc); st.sid = sc.id; changed(); drawAll(); preview.now();
  }
  async function renameScene() { const t = await prompt('Rename interior', 'Name', scene().title); if (t) { scene().title = t; changed(); drawToolbar(); } }
  async function delScene() {
    const sc = scene(); const users = P.buildings.filter((b) => b.interior === sc.id);
    if (!await confirmBox('Delete "' + (sc.title || sc.id) + '"' + (users.length ? ' (used by ' + users.map((b) => b.name || b.id).join(', ') + ')' : '') + '?', 'Delete')) return;
    P.interiors.splice(P.interiors.indexOf(sc), 1); users.forEach((b) => { b.interior = null; });
    st.sid = P.interiors[0] ? P.interiors[0].id : null; st.sel = null; changed(); drawAll(); preview.now();
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
    const owner = ownerMap(sc);
    for (let y = 0; y < GRID; y++) for (let x = 0; x < GRID; x++) {
      const o = owner.get(x + ',' + y);
      if (o) { const room = sc.rooms.find((r) => r.id === o.room); g.fillStyle = tintOf(sc, (o.door ? (sc.rooms.find((r) => r.id === sc.main) || {}) : room || {}).floor, 'floor'); g.globalAlpha = 0.85; g.fillRect(x * S36, y * S36, S36, S36); g.globalAlpha = 1; }
      else { g.fillStyle = '#2a323a'; g.fillRect(x * S36, y * S36, S36, S36); }
      if (y >= GRID - 1) { g.fillStyle = 'rgba(0,0,0,.45)'; g.fillRect(x * S36, y * S36, S36, S36); }
    }
    g.strokeStyle = 'rgba(255,255,255,.07)'; g.lineWidth = 1; g.beginPath();
    for (let i = 0; i <= GRID; i++) { g.moveTo(i * S36 + .5, 0); g.lineTo(i * S36 + .5, cv.height); g.moveTo(0, i * S36 + .5); g.lineTo(cv.width, i * S36 + .5); } g.stroke();
    // doors / exit
    for (const t of sc.door || []) { g.fillStyle = 'rgba(107,191,122,.75)'; g.fillRect(t[0] * S36 + 2, t[1] * S36 + 2, S36 - 4, S36 - 4); }
    for (const t of sc.exit || []) { g.fillStyle = 'rgba(106,168,230,.55)'; g.fillRect(t[0] * S36 + 2, t[1] * S36 + 2, S36 - 4, S36 - 4); }
    label(g, 'DOOR', ((sc.door || [[7, 14]])[0][0]) * S36 + 4, 14.6 * S36);
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
    // items
    for (const it of sc.items) drawItem(g, it, st.sel && st.sel.kind === 'item' && st.sel.id === it.id, sc);
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
      g.fillStyle = it.type === 'bed' ? tintOf(sc, '', '') : fillFor(it.mat || it.palette, 'prop');
      g.fillStyle = it.type === 'bed' || it.type === 'stand' ? ((sc.palettes[it.palette] || {}).accent || '#c04060') : g.fillStyle;
      g.fillRect(b[0], b[1], b[2] - b[0], b[3] - b[1]); g.strokeRect(b[0], b[1], b[2] - b[0], b[3] - b[1]);
      if (it.type === 'game') { g.fillStyle = 'rgba(0,0,0,.5)'; g.font = '10px system-ui'; g.fillText(it.path.split('/').pop().replace('.bcres', '').replace(/^rmk_/, '').slice(0, 11), b[0] + 2, (b[1] + b[3]) / 2 + 3); }
      if (it.type === 'bed') { const [hx, hz] = headDir(it.rot || 0); g.fillStyle = 'rgba(255,255,255,.7)'; const c = [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2]; g.beginPath(); g.arc(c[0] + hx * 12, c[1] + hz * 12, 4, 0, 7); g.fill(); }
    }
  }
  const headDir = (rot) => { const a = rot * Math.PI / 180; return [-Math.sin(a), -Math.cos(a)].map((v) => Math.round(v)); };
  function ownerMap(sc) {
    const m = new Map();
    for (const r of sc.rooms) { const [x0, y0, x1, y1] = r.rect; for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) m.set(x + ',' + y, { room: r.id }); }
    for (const r of sc.rooms) for (const d of r.doors || []) m.set(d[0] + ',' + d[1], { room: sc.main, door: true });
    for (const d of sc.door || []) m.set(d[0] + ',' + d[1], { room: sc.main, door: true });
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
      sc.items.push(it); st.sel = { kind: 'item', id: it.id }; if (!e.shiftKey) { st.placing = null; drawToolbar(); hintText(); }
      changed(); drawAll(); preview(); return;
    }
    if (st.tool === 'select') {
      const it = itemAt(sc, w);
      if (it) { st.sel = { kind: 'item', id: it.id }; st.drag = { kind: 'move', it, start: w, total: [0, 0], snap: !e.altKey }; }
      else { const r = roomAt(sc, t); st.sel = r ? { kind: 'room', id: r.id } : null; if (r) st.drag = { kind: 'moveRoom', r, start: t, orig: r.rect.slice(), od: (r.doors || []).map((d) => d.slice()) }; }
      drawInspector(); drawLists(); drawPlan();
    } else if (st.tool === 'room') {
      st.drag = { kind: 'room', start: t, rect: [t[0], t[1], t[0], t[1]] }; drawPlan();
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
    if (d && d.kind === 'move') {
      const dx = w[0] - d.start[0], dz = w[1] - d.start[1];
      const sn = d.snap ? 8 : 1, ax = Math.round(dx / sn) * sn, az = Math.round(dz / sn) * sn;
      const mx = ax - d.total[0], mz = az - d.total[1];
      if (mx || mz) { plan.move(d.it, mx, mz); d.total = [ax, az]; drawPlan(); drawInspector(true); }
    } else if (d && d.kind === 'room') { d.rect = [Math.min(d.start[0], t[0]), Math.min(d.start[1], t[1]), Math.max(d.start[0], t[0]), Math.max(d.start[1], t[1])]; drawPlan(); }
    else if (d && d.kind === 'moveRoom') {
      const dx = t[0] - d.start[0], dy = t[1] - d.start[1], o = d.orig;
      const nx0 = Math.max(0, Math.min(GRID - 1 - (o[2] - o[0]), o[0] + dx)), ny0 = Math.max(0, Math.min(GRID - 2 - (o[3] - o[1]), o[1] + dy));
      d.r.rect = [nx0, ny0, nx0 + o[2] - o[0], ny0 + o[3] - o[1]]; d.r.doors = d.od.map((q2) => [q2[0] + nx0 - o[0], q2[1] + ny0 - o[1]]); drawPlan();
    } else if (st.placing) drawPlan();
    else { const it = itemAt(sc, w); cv.style.cursor = it ? 'move' : 'default'; }
  });
  cv.addEventListener('pointerup', () => {
    const sc = scene(), d = st.drag; st.drag = null; if (!d || !sc) return;
    if (d.kind === 'room') {
      let [x0, y0, x1, y1] = d.rect; y1 = Math.min(y1, GRID - 2);
      const clash = sc.rooms.some((r) => !(x1 < r.rect[0] || x0 > r.rect[2] || y1 < r.rect[1] || y0 > r.rect[3]));
      if (clash) toast('Rooms cannot overlap', 'error');
      else {
        const rid = uid('room', sc.rooms), tag = rid.replace('room', '');
        const fm = 'floor_' + rid, wm = 'wall_' + rid;
        sc.materials[fm] = { type: 'floor', preset: 'planks' }; sc.materials[wm] = { type: 'wall', preset: 'plain' };
        sc.rooms.push({ id: rid, name: 'Room ' + tag, rect: [x0, y0, x1, y1], floor: fm, wall: wm, doors: [] }); st.sel = { kind: 'room', id: rid }; st.tool = 'select'; changed();
      }
    } else if (d.kind === 'move' || d.kind === 'moveRoom') changed();
    drawAll(); preview();
  });
  cv.addEventListener('pointerleave', () => { st.hover = null; if (st.placing) drawPlan(); });
  const onKey = (e) => {
    if (!cv.isConnected || /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
    const sc = scene(); if (!sc) return; const k = e.key;
    if (e.ctrlKey && (k === 'z' || k === 'Z') && !e.shiftKey) { e.preventDefault(); undo(); return; }
    if (e.ctrlKey && (k === 'y' || k === 'Y' || ((k === 'z' || k === 'Z') && e.shiftKey))) { e.preventDefault(); redo(); return; }
    if (k === 'Escape') { st.placing = null; st.sel = null; drawAll(); return; }
    if (k === 'v') { st.tool = 'select'; drawToolbar(); hintText(); } else if (k === 'u') { st.tool = 'room'; drawToolbar(); hintText(); } else if (k === 'd') { st.tool = 'door'; drawToolbar(); hintText(); }
    const it = st.sel && st.sel.kind === 'item' ? sc.items.find((i) => i.id === st.sel.id) : null;
    if (!it) { if ((k === 'Delete' || k === 'Backspace') && st.sel && st.sel.kind === 'room') { delRoom(); } return; }
    const step = e.shiftKey ? T : 8;
    if (k === 'Delete' || k === 'Backspace') { sc.items.splice(sc.items.indexOf(it), 1); st.sel = null; }
    else if (k === 'ArrowLeft') plan.move(it, -step, 0); else if (k === 'ArrowRight') plan.move(it, step, 0); else if (k === 'ArrowUp') plan.move(it, 0, -step); else if (k === 'ArrowDown') plan.move(it, 0, step);
    else if (k === 'r') { const c = plan.rotate(it); if (c) { const c2 = plan.center(it); plan.move(it, c[0] - c2[0], c[1] - c2[1]); } }
    else if (k === 'd' && e.ctrlKey) { e.preventDefault(); duplicate(it); return; } else return;
    e.preventDefault(); changed(); drawAll(); preview();
  };
  window.addEventListener('keydown', onKey);
  function duplicate(it) { const sc = scene(); const c = JSON.parse(JSON.stringify(it)); c.id = plan.newId(sc.items, it.type[0]); plan.move(c, 16, 16); sc.items.push(c); st.sel = { kind: 'item', id: c.id }; changed(); drawAll(); preview(); }
  function delRoom() {
    const sc = scene(), r = sc.rooms.find((x) => x.id === st.sel.id); if (!r) return;
    if (r.id === sc.main) { toast('The main room cannot be deleted', 'error'); return; }
    sc.rooms.splice(sc.rooms.indexOf(r), 1); st.sel = null; changed(); drawAll(); preview();
  }

  // ================================================================ left: lists
  function drawLeft() {
    const sc = scene();
    mount(left, h('div', { class: 'tabs' }, [['items', 'Items'], ['rooms', 'Rooms'], ['mats', 'Materials'], ['add', 'Add']].map(([id, l]) => h('button', { class: st.tab === id ? 'on' : '', onclick: () => { st.tab = id; drawLeft(); } }, l))), h('div', { style: { overflow: 'auto', flex: 1 }, id: 'leftbody' }));
    drawLists();
  }
  function drawLists() {
    const sc = scene(), body = left.querySelector('#leftbody'); if (!body) return;
    if (!sc) { mount(body, h('div', { class: 'empty' }, 'No interior yet.')); return; }
    if (st.tab === 'items') {
      mount(body, h('div', { class: 'list' }, sc.items.length ? sc.items.map((it, i) => h('div', { class: 'item' + (st.sel && st.sel.kind === 'item' && st.sel.id === it.id ? ' on' : ''), onclick: () => { st.sel = { kind: 'item', id: it.id }; drawInspector(); drawLists(); drawPlan(); } },
        h('span', {}, TYPE_LABEL[it.type] || it.type), h('span', { class: 'dim', style: { fontSize: '12px' } }, it.type === 'game' ? it.path.split('/').pop().replace('.bcres', '') : it.id), it.block && it.block.length ? h('span', { class: 'chip sub' }, 'solid') : null)) : h('div', { class: 'empty' }, 'Nothing placed. Use the Add tab.')));
    } else if (st.tab === 'rooms') {
      mount(body, h('div', { class: 'list' }, sc.rooms.map((r) => h('div', { class: 'item' + (st.sel && st.sel.kind === 'room' && st.sel.id === r.id ? ' on' : ''), onclick: () => { st.sel = { kind: 'room', id: r.id }; drawInspector(); drawLists(); drawPlan(); } }, h('span', {}, (r.name || r.id) + (r.id === sc.main ? ' ★' : '')), h('span', { class: 'sub dim' }, (r.rect[2] - r.rect[0] + 1) + '×' + (r.rect[3] - r.rect[1] + 1)))),
        h('div', { class: 'dim', style: { padding: '10px 12px', fontSize: '12px' } }, 'Use the “Draw room” tool to add rooms. ★ is the main room: the entrance, and where doorways lead.')));
    } else if (st.tab === 'mats') drawMaterials(body, sc);
    else drawAdd(body, sc);
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
  const lib = { q: '', results: [], sel: null, vw: null };
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
    mount(body, h('div', { style: { padding: '10px', display: 'grid', gap: '10px' } },
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
    if (!sc || !st.sel) { mount(insp, h('div', { class: 'dim' }, sc ? 'Select a room or an item on the plan.' : '')); return; }
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
      case 'quad': rows.push(h('div', { class: 'dim', style: { fontSize: '12px' } }, 'Four corners (x, y height, z), counter-clockwise seen from the front.'), ...it.pts.map((p, i) => h('div', { class: 'grid3' }, [0, 1, 2].map((k) => field('p' + (i + 1) + ' ' + 'xyz'[k], numInput(p[k], (v) => { p[k] = v; changed(); preview(); drawPlan(); }))))), mp('mat', 'Material')); break;
      case 'wallquad': rows.push(h('div', { class: 'grid2' }, field('Start x', numInput(it.a[0], (v) => { it.a[0] = v; changed(); preview(); drawPlan(); })), field('Start z', numInput(it.a[1], (v) => { it.a[1] = v; changed(); preview(); drawPlan(); })), field('End x', numInput(it.b[0], (v) => { it.b[0] = v; changed(); preview(); drawPlan(); })), field('End z', numInput(it.b[1], (v) => { it.b[1] = v; changed(); preview(); drawPlan(); })), n('h', 'Height')), mp('mat', 'Material'), checkbox(it.both, (v) => { it.both = v; changed(); preview(); }, 'Visible from both sides')); break;
    }
    const blockTxt = h('input', { type: 'text', value: (it.block || []).map((b) => b.join(',')).join('  '), placeholder: 'e.g. 3,4  4,4' });
    blockTxt.addEventListener('change', () => { it.block = blockTxt.value.split(/\s+/).filter(Boolean).map((s) => s.split(',').map(Number)).filter((b) => b.length === 2 && b.every((v) => !isNaN(v))); if (!it.block.length) delete it.block; changed(); preview(); drawPlan(); });
    mount(insp, h('div', { class: 'row' }, h('b', {}, TYPE_LABEL[it.type] || it.type), h('span', { class: 'dim' }, it.id), h('div', { class: 'grow' }),
      h('button', { class: 'small', onclick: () => duplicate(it) }, 'Duplicate'), h('button', { class: 'small danger', onclick: () => { sc.items.splice(sc.items.indexOf(it), 1); st.sel = null; changed(); drawAll(); preview(); } }, 'Delete')),
      rows,
      plan.VISUAL.has(it.type) ? null : h('div', { class: 'card' }, h('h3', {}, 'Collision'), field('Blocked floor tiles (x,y …)', blockTxt, 'Tiles the player cannot walk onto; doorways must stay free.'),
        h('button', { class: 'small', onclick: () => { it.block = plan.blocksFor(it); if (!it.block.length) delete it.block; changed(); preview(); drawAll(); } }, 'Fit to the footprint')));
  }
  function drawRoomInspector(sc, light) {
    const r = sc.rooms.find((x) => x.id === st.sel.id); if (!r) { mount(insp); return; }
    const rect = (i, label) => field(label, numInput(r.rect[i], (v) => { r.rect[i] = Math.max(0, Math.min(GRID - 1, v)); changed(); preview(); drawPlan(); }));
    const mats = (type) => Object.keys(sc.materials).filter((n) => sc.materials[n].type === type);
    mount(insp, h('div', { class: 'row' }, h('b', {}, 'Room'), h('span', { class: 'dim' }, r.id), h('div', { class: 'grow' }), r.id !== sc.main ? h('button', { class: 'small danger', onclick: delRoom }, 'Delete') : h('span', { class: 'chip' }, 'main room')),
      field('Name', textInput(r.name || '', (v) => { r.name = v; changed(); drawPlan(); drawLists(); })),
      h('div', { class: 'grid2' }, rect(0, 'x from'), rect(2, 'x to'), rect(1, 'y from'), rect(3, 'y to')),
      field('Floor', select(mats('floor'), r.floor, (v) => { r.floor = v; changed(); preview(); drawPlan(); })), field('Walls', select(mats('wall'), r.wall, (v) => { r.wall = v; changed(); preview(); })),
      r.id !== sc.main ? field('Sign over the doorway', textInput(r.label || '', (v) => { if (v) r.label = v; else delete r.label; changed(); preview(); }), 'Lettering on the lintel above this room’s doorway.') : null,
      r.id !== sc.main ? h('div', { class: 'dim', style: { fontSize: '12px' } }, 'Doorways: ' + ((r.doors || []).map((d) => d.join(',')).join('  ') || 'none') + '. Use the Doorway tool.') : h('label', { class: 'dim' }, 'Doorways from the main room lead into the other rooms.'),
      r.id !== sc.main ? h('button', { class: 'small', onclick: () => { sc.main = r.id; changed(); drawAll(); preview(); } }, 'Make this the main room (entrance)') : null);
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
    mount(msgs, r.problems.map((p) => h('div', { class: 'err-box' }, p)), h('div', { class: 'row dim', style: { fontSize: '12px' } }, `${r.triangles} triangles · atlas ${r.atlas_used}/512 rows`, h('div', { style: { flex: 1 } }, atlasBar())));
    if (!viewer) { try { viewer = new Viewer(vcanvas, { light: [0.2, 1, 0.4], bg: [0.45, 0.62, 0.8] }); } catch (e) { console.error('viewer', e); viewer = null; } if (!viewer || !viewer.ok) return; }
    const img = await dataImage(r.mesh.atlas);
    viewer.setParts([{ ...r.mesh, image: img }]);
    if (firstFrame) { viewer.target = [256, 20, 250]; viewer.dist = 640; viewer.yaw = 0; viewer.pitch = 0.75; firstFrame = false; }
    if (st.tab === 'mats') drawLists();
  }, 450);

  function drawAll() { drawToolbar(); hintText(); drawLeft(); drawInspector(); drawPlan(); }
  get('/api/interior/presets').then((p) => { st.presets = p; drawPlan(); });
  drawAll(); preview.now(); snapshot();
  return () => { window.removeEventListener('keydown', onKey); };
}
