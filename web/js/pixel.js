// A pixel editor on a <canvas>: pencil, eraser, fill, picker, line, rect, ellipse, selection-free filters, zoom/pan, undo.
import { h, mount, toast, pickFile, loadImage, download } from './ui.js';

export class PixelEditor {
  constructor(opts = {}) {
    this.w = 0; this.h = 0; this.px = null;          // ImageData-like RGBA Uint8ClampedArray
    this.zoom = 8; this.tool = 'pencil'; this.color = [0, 0, 0, 255]; this.size = 1; this.grid = true;
    this.undo = []; this.redo = []; this.onchange = opts.onchange || (() => {}); this.opts = opts; this.overlay = null; this.regions = null; this.uv = null; this.showUV = true;
    this.alphaLock = false; this.mirrorX = false; this.recent = [];
    this.canvas = h('canvas', { style: { imageRendering: 'pixelated', cursor: 'crosshair', touchAction: 'none' } });
    this.wrap = h('div', { class: 'canvas-wrap', style: { overflow: 'auto', maxHeight: '100%', flex: 1, minHeight: '200px' } }, this.canvas);
    this.info = h('span', { class: 'dim', style: { fontSize: '12px' } });
    this.bind();
    this.el = h('div', { class: 'col', style: { height: '100%', minHeight: 0 } }, this.toolbar(), this.wrap, h('div', { class: 'row', style: { padding: '2px 4px' } }, this.info));
  }
  toolbar() {
    const tools = [['pencil', '✎ Pencil', 'B'], ['eraser', '⌫ Eraser', 'E'], ['fill', '▧ Fill', 'G'], ['picker', '◉ Pick', 'I'], ['line', '╱ Line', 'L'], ['rect', '▭ Rect', 'R'], ['frect', '■ Box', 'F'], ['ellipse', '◯ Ellipse', 'O']];
    this.toolBtns = {};
    const bar = h('div', { class: 'toolbar' },
      tools.map(([id, label, key]) => { const b = h('button', { class: 'small' + (id === this.tool ? ' on' : ''), title: label + ' (' + key + ')', onclick: () => this.setTool(id) }, label); this.toolBtns[id] = b; return b; }),
      h('div', { class: 'sep-v' }),
      h('label', { class: 'row', style: { gap: '4px' } }, h('span', { class: 'dim' }, 'Color'), (this.colorEl = h('input', { type: 'color', value: '#000000', oninput: (e) => this.setColor(e.target.value) }))),
      h('label', { class: 'row', style: { gap: '4px' }, title: 'Alpha of the pencil' }, h('span', { class: 'dim' }, 'α'), (this.alphaEl = h('input', { type: 'range', min: 0, max: 255, value: 255, style: { width: '70px' }, oninput: (e) => { this.color[3] = +e.target.value; } }))),
      h('label', { class: 'row', style: { gap: '4px' } }, h('span', { class: 'dim' }, 'Size'), (this.sizeEl = h('input', { type: 'number', min: 1, max: 16, value: 1, style: { width: '52px' }, oninput: (e) => { this.size = Math.max(1, +e.target.value || 1); } }))),
      h('div', { class: 'sep-v' }),
      h('button', { class: 'small', onclick: () => this.undoStep(), title: 'Undo (Ctrl+Z)' }, '↶'), h('button', { class: 'small', onclick: () => this.redoStep(), title: 'Redo (Ctrl+Y)' }, '↷'),
      h('div', { class: 'sep-v' }),
      h('button', { class: 'small', title: 'Save the texture as a PNG file, to edit it in another program', onclick: () => this.exportPng() }, '⇩ Export PNG'),
      h('button', { class: 'small', title: 'Load a PNG (from Blender, GIMP, Krita…) into the editor', onclick: () => this.importPng() }, '⇧ Import PNG'),
      h('div', { class: 'sep-v' }),
      h('button', { class: 'small', onclick: () => this.setZoom(this.zoom / 2) }, '−'), (this.zoomEl = h('span', { class: 'dim', style: { minWidth: '34px', textAlign: 'center' } }, '8×')), h('button', { class: 'small', onclick: () => this.setZoom(this.zoom * 2) }, '+'),
      h('button', { class: 'small', onclick: () => this.fit() }, 'Fit'),
      (this.gridBtn = h('button', { class: 'small on', onclick: () => { this.grid = !this.grid; this.gridBtn.classList.toggle('on', this.grid); this.draw(); } }, '#')),
      (this.uvBtn = h('button', { class: 'small on', title: 'Show the model’s UV layout over the texture', style: { display: 'none' }, onclick: () => { this.showUV = !this.showUV; this.uvBtn.classList.toggle('on', this.showUV); this.draw(); } }, 'UV')),
      (this.mirBtn = h('button', { class: 'small', title: 'Mirror horizontally while drawing', onclick: () => { this.mirrorX = !this.mirrorX; this.mirBtn.classList.toggle('on', this.mirrorX); } }, '⇋')),
      (this.lockBtn = h('button', { class: 'small', title: 'Only paint where the texture is not transparent', onclick: () => { this.alphaLock = !this.alphaLock; this.lockBtn.classList.toggle('on', this.alphaLock); } }, '🔒α')));
    this.palette = h('div', { class: 'row wrap', style: { padding: '4px 10px', gap: '4px' } });
    return h('div', {}, bar, this.palette);
  }
  setUV(edges) { this.uv = edges && edges.length ? edges : null; this.uvBtn.style.display = this.uv ? '' : 'none'; this.draw(); }
  setTool(t) { this.tool = t; for (const [k, b] of Object.entries(this.toolBtns)) b.classList.toggle('on', k === t); }
  setColor(hex, alpha) {
    const n = parseInt(hex.slice(1), 16);
    this.color = [n >> 16 & 255, n >> 8 & 255, n & 255, alpha ?? this.color[3]];
    this.colorEl.value = hex; this.alphaEl.value = this.color[3];
    this.pushRecent(hex);
  }
  pushRecent(hex) {
    this.recent = [hex, ...this.recent.filter((c) => c !== hex)].slice(0, 24);
    mount(this.palette, this.recent.map((c) => h('span', { class: 'swatch', style: { background: c }, title: c, onclick: () => { this.setColor(c); } })));
  }
  // ---- image io
  load(img) {
    this.w = img.width; this.h = img.height;
    const c = document.createElement('canvas'); c.width = this.w; c.height = this.h;
    const g = c.getContext('2d', { willReadFrequently: true }); g.drawImage(img, 0, 0);
    this.px = g.getImageData(0, 0, this.w, this.h).data;
    this.undo = []; this.redo = [];
    this.canvas.width = this.w; this.canvas.height = this.h; this.fit(); this.draw();
  }
  blank(w, h2, rgba = [0, 0, 0, 0]) {
    this.w = w; this.h = h2; this.px = new Uint8ClampedArray(w * h2 * 4);
    for (let i = 0; i < w * h2; i++) this.px.set(rgba, i * 4);
    this.undo = []; this.redo = []; this.canvas.width = w; this.canvas.height = h2; this.fit(); this.draw();
  }
  toCanvas() {
    const c = document.createElement('canvas'); c.width = this.w; c.height = this.h;
    c.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(this.px), this.w, this.h), 0, 0); return c;
  }
  // export / import the current texture as a PNG file (opts.filename() names it; opts.freeSize lets the image change the size, opts.validate(w, h) may refuse it)
  async exportPng() {
    if (!this.px) { toast('Nothing to export yet', 'info'); return; }
    download(((this.opts.filename && this.opts.filename()) || 'texture').replace(/[^A-Za-z0-9._-]+/g, '_') + '.png', await this.toBlob());
  }
  async importPng() {
    if (!this.px) { toast('Open a texture first', 'info'); return; }
    const f = await pickFile('image/png,image/*'); if (!f) return;
    const url = URL.createObjectURL(f);
    try {
      const im = await loadImage(url);
      let w = this.w, hh = this.h;
      if (this.opts.freeSize) {
        const bad = this.opts.validate && this.opts.validate(im.width, im.height);
        if (bad) { toast(bad, 'error'); return; }
        w = im.width; hh = im.height;
      }
      this.snapshot();
      const c = document.createElement('canvas'); c.width = w; c.height = hh;
      const g = c.getContext('2d', { willReadFrequently: true }); g.imageSmoothingEnabled = !(im.width <= w && im.height <= hh);
      g.drawImage(im, 0, 0, w, hh);
      this.px = g.getImageData(0, 0, w, hh).data; this.w = w; this.h = hh; this.canvas.width = w; this.canvas.height = hh;
      this.fit(); this.draw(); this.onchange();
      if (im.width !== w || im.height !== hh) toast('The image was scaled from ' + im.width + '×' + im.height + ' to ' + w + '×' + hh, 'info');
    } catch (e) { toast('Could not read that image', 'error'); }
    finally { URL.revokeObjectURL(url); }
  }
  toBlob() { return new Promise((res) => this.toCanvas().toBlob(res, 'image/png')); }
  snapshot() { this.undo.push(new Uint8ClampedArray(this.px)); if (this.undo.length > 60) this.undo.shift(); this.redo = []; }
  undoStep() { if (!this.undo.length) return; this.redo.push(this.px); this.px = this.undo.pop(); this.draw(); this.onchange(); }
  redoStep() { if (!this.redo.length) return; this.undo.push(this.px); this.px = this.redo.pop(); this.draw(); this.onchange(); }
  // ---- view
  fit() { const a = this.wrap.clientWidth || 600, b = this.wrap.clientHeight || 400; let z = Math.min((a - 8) / this.w, (b - 8) / this.h); z = z >= 2 ? Math.floor(z) : Math.max(1, Math.floor(z * 2) / 2); this.setZoom(Math.min(32, z)); }
  setZoom(z) { this.zoom = Math.max(0.5, Math.min(48, z)); this.canvas.style.width = this.w * this.zoom + 'px'; this.canvas.style.height = this.h * this.zoom + 'px'; this.zoomEl.textContent = this.zoom + '×'; this.draw(); }
  draw() {
    if (!this.px) return;
    const c = this.canvas, g = c.getContext('2d');
    g.clearRect(0, 0, c.width, c.height);
    g.putImageData(new ImageData(new Uint8ClampedArray(this.px), this.w, this.h), 0, 0);
    this.drawOverlay();
  }
  drawOverlay() {
    if (!this.regions && !(this.uv && this.showUV) && !(this.grid && this.zoom >= 8)) { if (this.ov) this.ov.remove(), this.ov = null; return; }
    if (!this.ov) { this.ov = h('canvas', { style: { position: 'absolute', left: 0, top: 0, pointerEvents: 'none' } }); this.wrap.style.position = 'relative'; this.wrap.append(this.ov); }
    const o = this.ov, z = this.zoom; o.width = this.w * z; o.height = this.h * z; o.style.width = o.width + 'px'; o.style.height = o.height + 'px';
    const g = o.getContext('2d');
    if (this.grid && z >= 8) { g.strokeStyle = 'rgba(128,128,128,.28)'; g.beginPath(); for (let x = 0; x <= this.w; x++) { g.moveTo(x * z + .5, 0); g.lineTo(x * z + .5, o.height); } for (let y = 0; y <= this.h; y++) { g.moveTo(0, y * z + .5); g.lineTo(o.width, y * z + .5); } g.stroke(); }
    if (this.uv && this.showUV) {
      g.strokeStyle = 'rgba(80,220,255,.55)'; g.lineWidth = 1; g.beginPath();
      for (const [x0, y0, x1, y1] of this.uv) { g.moveTo(x0 * z, y0 * z); g.lineTo(x1 * z, y1 * z); }
      g.stroke();
    }
    if (this.regions) {
      g.font = '11px system-ui'; g.lineWidth = 1;
      for (const [name, [x0, y0, x1, y1]] of Object.entries(this.regions)) {
        g.strokeStyle = 'rgba(255,230,80,.85)'; g.strokeRect(x0 * z + .5, y0 * z + .5, (x1 - x0) * z - 1, (y1 - y0) * z - 1);
        g.fillStyle = 'rgba(0,0,0,.6)'; const tw = g.measureText(name).width + 6; g.fillRect(x0 * z + 1, y0 * z + 1, tw, 14); g.fillStyle = '#ffe650'; g.fillText(name, x0 * z + 4, y0 * z + 12);
      }
    }
  }
  // ---- drawing
  pos(e) { const r = this.canvas.getBoundingClientRect(); return [Math.floor((e.clientX - r.left) / r.width * this.w), Math.floor((e.clientY - r.top) / r.height * this.h)]; }
  put(x, y, col) {
    if (x < 0 || y < 0 || x >= this.w || y >= this.h) return;
    const i = (y * this.w + x) * 4;
    if (this.alphaLock && this.px[i + 3] === 0) return;
    this.px[i] = col[0]; this.px[i + 1] = col[1]; this.px[i + 2] = col[2]; this.px[i + 3] = col[3];
  }
  brush(x, y, col) {
    const s = this.size, o = Math.floor(s / 2);
    for (let j = 0; j < s; j++) for (let i = 0; i < s; i++) { this.put(x - o + i, y - o + j, col); if (this.mirrorX) this.put(this.w - 1 - (x - o + i), y - o + j, col); }
  }
  lineTo(x0, y0, x1, y1, fn) {
    const dx = Math.abs(x1 - x0), dy = -Math.abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1; let err = dx + dy;
    for (;;) { fn(x0, y0); if (x0 === x1 && y0 === y1) break; const e2 = 2 * err; if (e2 >= dy) { err += dy; x0 += sx; } if (e2 <= dx) { err += dx; y0 += sy; } }
  }
  fill(x, y, col) {
    if (x < 0 || y < 0 || x >= this.w || y >= this.h) return;
    const get = (a, b) => { const i = (b * this.w + a) * 4; return [this.px[i], this.px[i + 1], this.px[i + 2], this.px[i + 3]]; };
    const t = get(x, y); if (t.every((v, k) => v === col[k])) return;
    const same = (a, b) => { const i = (b * this.w + a) * 4; return this.px[i] === t[0] && this.px[i + 1] === t[1] && this.px[i + 2] === t[2] && this.px[i + 3] === t[3]; };
    const st = [[x, y]];
    while (st.length) { const [a, b] = st.pop(); if (a < 0 || b < 0 || a >= this.w || b >= this.h || !same(a, b)) continue; this.put(a, b, col); st.push([a + 1, b], [a - 1, b], [a, b + 1], [a, b - 1]); }
  }
  shape(kind, a, b, col) {
    const [x0, y0] = a, [x1, y1] = b;
    const plot = (x, y) => this.brush(x, y, col);
    if (kind === 'line') this.lineTo(x0, y0, x1, y1, plot);
    else if (kind === 'rect') { const lx = Math.min(x0, x1), hx = Math.max(x0, x1), ly = Math.min(y0, y1), hy = Math.max(y0, y1); for (let x = lx; x <= hx; x++) { plot(x, ly); plot(x, hy); } for (let y = ly; y <= hy; y++) { plot(lx, y); plot(hx, y); } }
    else if (kind === 'frect') { const lx = Math.min(x0, x1), hx = Math.max(x0, x1), ly = Math.min(y0, y1), hy = Math.max(y0, y1); for (let y = ly; y <= hy; y++) for (let x = lx; x <= hx; x++) this.put(x, y, col); }
    else if (kind === 'ellipse') {
      const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, rx = Math.abs(x1 - x0) / 2 + .5, ry = Math.abs(y1 - y0) / 2 + .5;
      for (let t = 0; t < Math.PI * 2; t += 1 / Math.max(rx, ry, 4)) plot(Math.round(cx + rx * Math.cos(t) - (rx > 0 ? 0 : 0)), Math.round(cy + ry * Math.sin(t)));
    }
  }
  bind() {
    const c = this.canvas; let down = null, start = null, last = null, backup = null;
    const colFor = (e) => (this.tool === 'eraser' || e.button === 2 && false ? [0, 0, 0, 0] : this.color);
    c.addEventListener('contextmenu', (e) => e.preventDefault());
    c.addEventListener('pointerdown', (e) => {
      if (!this.px) return; c.setPointerCapture(e.pointerId);
      const p = this.pos(e); down = e.button; start = p; last = p;
      if (this.tool === 'picker' || e.altKey || e.button === 2) { const i = (p[1] * this.w + p[0]) * 4; if (this.px[i + 3] || true) { const hx = '#' + [0, 1, 2].map((k) => this.px[i + k].toString(16).padStart(2, '0')).join(''); this.setColor(hx, this.px[i + 3]); } down = 'pick'; return; }
      this.snapshot();
      if (this.tool === 'fill') { this.fill(p[0], p[1], this.color); this.draw(); this.onchange(); down = null; return; }
      if (this.tool === 'pencil' || this.tool === 'eraser') { this.brush(p[0], p[1], colFor(e)); this.draw(); }
      else backup = new Uint8ClampedArray(this.px);
    });
    c.addEventListener('pointermove', (e) => {
      if (!this.px) return; const p = this.pos(e);
      this.info.textContent = `${p[0]}, ${p[1]}   ${this.w}×${this.h}`;
      if (down == null || down === 'pick') return;
      if (this.tool === 'pencil' || this.tool === 'eraser') { this.lineTo(last[0], last[1], p[0], p[1], (x, y) => this.brush(x, y, colFor(e))); last = p; this.draw(); }
      else if (backup) { this.px.set(backup); this.shape(this.tool, start, p, this.color); this.draw(); }
    });
    c.addEventListener('pointerup', () => { if (down != null && down !== 'pick') this.onchange(); down = null; backup = null; });
    this.wrap.addEventListener('wheel', (e) => { if (e.ctrlKey) { e.preventDefault(); this.setZoom(this.zoom * (e.deltaY < 0 ? 1.25 : 0.8)); } }, { passive: false });
    window.addEventListener('keydown', this._key = (e) => {
      if (!this.el.isConnected || /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
      const k = e.key.toLowerCase();
      if (e.ctrlKey && k === 'z') { e.preventDefault(); this.undoStep(); } else if (e.ctrlKey && (k === 'y' || (e.shiftKey && k === 'z'))) { e.preventDefault(); this.redoStep(); }
      else if (!e.ctrlKey) { const m = { b: 'pencil', e: 'eraser', g: 'fill', i: 'picker', l: 'line', r: 'rect', f: 'frect', o: 'ellipse' }[k]; if (m) this.setTool(m); }
    });
  }
  destroy() { window.removeEventListener('keydown', this._key); }
  // ---- filters
  filter(fn) { this.snapshot(); for (let i = 0; i < this.w * this.h; i++) { const o = fn(this.px[i * 4], this.px[i * 4 + 1], this.px[i * 4 + 2], this.px[i * 4 + 3]); this.px.set(o, i * 4); } this.draw(); this.onchange(); }
  hueShift(deg, sat = 1, val = 1) {
    this.filter((r, g, b, a) => {
      let [hh, s, v] = rgb2hsv(r, g, b); hh = (hh + deg / 360 + 1) % 1; s = Math.min(1, s * sat); v = Math.min(1, v * val);
      return [...hsv2rgb(hh, s, v), a];
    });
  }
  flip(horizontal) {
    this.snapshot(); const n = new Uint8ClampedArray(this.px.length);
    for (let y = 0; y < this.h; y++) for (let x = 0; x < this.w; x++) { const sx = horizontal ? this.w - 1 - x : x, sy = horizontal ? y : this.h - 1 - y; n.set(this.px.slice((sy * this.w + sx) * 4, (sy * this.w + sx) * 4 + 4), (y * this.w + x) * 4); }
    this.px = n; this.draw(); this.onchange();
  }
}
function rgb2hsv(r, g, b) { r /= 255; g /= 255; b /= 255; const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn; let hh = 0; if (d) { hh = mx === r ? ((g - b) / d + 6) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4; hh /= 6; } return [hh, mx ? d / mx : 0, mx]; }
function hsv2rgb(hh, s, v) { const i = Math.floor(hh * 6), f = hh * 6 - i, p = v * (1 - s), q = v * (1 - f * s), t = v * (1 - (1 - f) * s); const [r, g, b] = [[v, t, p], [q, v, p], [p, v, t], [p, q, v], [t, p, v], [v, p, q]][i % 6]; return [Math.round(r * 255), Math.round(g * 255), Math.round(b * 255)]; }
