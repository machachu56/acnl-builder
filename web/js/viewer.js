// A small WebGL orbit viewer for meshes with one texture each.
// parts: [{positions, normals, uvs, colors?, indices, image (data URL or <img>/<canvas>), flat?}]
export class Viewer {
  constructor(canvas, opts = {}) {
    this.c = canvas;
    this.gl = canvas.getContext('webgl', { antialias: true, alpha: false, preserveDrawingBuffer: true });
    this.parts = [];
    this.opts = Object.assign({ light: [0.35, 0.8, 0.55], bg: [0.55, 0.72, 0.9], ground: true, night: false, flipV: false }, opts);
    this.yaw = opts.yaw ?? 0.6; this.pitch = opts.pitch ?? 0.45; this.dist = 300; this.target = [0, 30, 0];
    this.ok = !!this.gl; (window.__viewers = window.__viewers || []).push(this);
    if (!this.ok) return;
    this.prog = this.makeProgram();
    this.bind();
    this.loop = this.loop.bind(this);
    this.dirty = true; requestAnimationFrame(this.loop);
  }
  makeProgram() {
    const gl = this.gl;
    const sh = (t, s) => { const o = gl.createShader(t); gl.shaderSource(o, s); gl.compileShader(o); if (!gl.getShaderParameter(o, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(o)); return o; };
    const p = gl.createProgram();
    gl.attachShader(p, sh(gl.VERTEX_SHADER, `attribute vec3 pos; attribute vec3 nrm; attribute vec2 uv; attribute vec3 col; uniform mat4 mvp; varying vec3 vn; varying vec2 vuv; varying vec3 vc;
      void main(){ vn = nrm; vuv = uv; vc = col; gl_Position = mvp * vec4(pos,1.0); }`));
    gl.attachShader(p, sh(gl.FRAGMENT_SHADER, `precision mediump float; varying vec3 vn; varying vec2 vuv; varying vec3 vc; uniform sampler2D tex; uniform vec3 light; uniform float night; uniform float flat_;
      void main(){ vec4 t = texture2D(tex, vuv); float l = max(dot(normalize(vn), normalize(light)), 0.0);
        float k = flat_ > 0.5 ? 1.0 : (night > 0.5 ? 0.3 + 0.2*l : 0.55 + 0.6*l);
        gl_FragColor = vec4(t.rgb * vc * k, 1.0); }`));
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
    return p;
  }
  bind() {
    const c = this.c; let drag = null;
    c.addEventListener('pointerdown', (e) => { drag = { x: e.clientX, y: e.clientY, b: e.button }; c.setPointerCapture(e.pointerId); });
    c.addEventListener('pointerup', () => { drag = null; });
    c.addEventListener('pointermove', (e) => {
      if (!drag) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y; drag.x = e.clientX; drag.y = e.clientY;
      if (drag.b === 2 || e.shiftKey) { const s = this.dist * 0.0015; this.target[0] -= (Math.cos(this.yaw) * dx) * s; this.target[2] -= (-Math.sin(this.yaw) * dx) * s; this.target[1] += dy * s; }
      else { this.yaw -= dx * 0.01; this.pitch = Math.max(-1.45, Math.min(1.45, this.pitch + dy * 0.01)); }
      this.dirty = true;
    });
    c.addEventListener('wheel', (e) => { e.preventDefault(); this.dist *= Math.exp(e.deltaY * 0.001); this.dirty = true; }, { passive: false });
    c.addEventListener('contextmenu', (e) => e.preventDefault());
  }
  frame(min, max) {
    const mid = min.map((v, i) => (v + max[i]) / 2), r = Math.hypot(max[0] - min[0], max[1] - min[1], max[2] - min[2]) / 2;
    this.target = mid; this.dist = Math.max(40, r * 2.6); this.dirty = true;
  }
  setParts(parts) {
    const gl = this.gl; if (!this.ok) return;
    for (const p of this.parts) { gl.deleteBuffer(p.vb); gl.deleteBuffer(p.ib); if (p.tex && !p.shared) gl.deleteTexture(p.tex); }
    this.parts = parts.map((p) => this.upload(p));
    this.dirty = true;
  }
  upload(p) {
    const gl = this.gl, n = p.positions.length / 3;
    const data = new Float32Array(n * 11);
    for (let i = 0; i < n; i++) {
      data.set(p.positions.slice(i * 3, i * 3 + 3), i * 11);
      data.set((p.normals || []).slice(i * 3, i * 3 + 3).length ? p.normals.slice(i * 3, i * 3 + 3) : [0, 1, 0], i * 11 + 3);
      data[i * 11 + 6] = p.uvs[i * 2]; data[i * 11 + 7] = this.opts.flipV ? 1 - p.uvs[i * 2 + 1] : p.uvs[i * 2 + 1];
      const c = p.colors ? p.colors.slice(i * 3, i * 3 + 3) : [1, 1, 1]; data.set(c, i * 11 + 8);
    }
    const vb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, vb); gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    const ib = gl.createBuffer(); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib);
    const idx = n > 65535 ? new Uint32Array(p.indices) : new Uint16Array(p.indices);
    if (n > 65535) gl.getExtension('OES_element_index_uint');
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, idx, gl.STATIC_DRAW);
    const out = { vb, ib, count: p.indices.length, type: n > 65535 ? gl.UNSIGNED_INT : gl.UNSIGNED_SHORT, tex: null, flat: !!p.flat, image: p.image };
    if (p.image) out.tex = this.makeTex(p.image);
    return out;
  }
  makeTex(img) {
    const gl = this.gl, t = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, t);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    const pow2 = (v) => (v & (v - 1)) === 0;
    const w = img.width, hh = img.height;
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    const wrap = pow2(w) && pow2(hh) ? gl.REPEAT : gl.CLAMP_TO_EDGE;
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, wrap); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, wrap);
    return t;
  }
  // swap the texture of part i (used for live editing)
  setImage(i, img) {
    const p = this.parts[i]; if (!p) return;
    this.gl.deleteTexture(p.tex); p.tex = this.makeTex(img); this.dirty = true;
  }
  bounds() {
    return null;
  }
  loop() {
    if (!this.c.isConnected) return;
    requestAnimationFrame(this.loop);
    if (!this.dirty) return;
    this.dirty = false; this.draw();
  }
  draw() {
    const gl = this.gl, c = this.c;
    const w = c.clientWidth, hh = c.clientHeight, dpr = Math.min(2, window.devicePixelRatio || 1);
    if (c.width !== Math.round(w * dpr) || c.height !== Math.round(hh * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(hh * dpr); }
    gl.viewport(0, 0, c.width, c.height);
    const bg = this.opts.night ? this.opts.bg.map((v) => v * 0.25) : this.opts.bg;
    gl.clearColor(bg[0], bg[1], bg[2], 1); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT); gl.enable(gl.DEPTH_TEST); gl.enable(gl.CULL_FACE);
    const cp = Math.cos(this.pitch), eye = [this.target[0] + this.dist * cp * Math.sin(this.yaw), this.target[1] + this.dist * Math.sin(this.pitch), this.target[2] + this.dist * cp * Math.cos(this.yaw)];
    const mvp = mul(persp(0.7, c.width / c.height, this.dist * 0.02, this.dist * 30), look(eye, this.target, [0, 1, 0]));
    gl.useProgram(this.prog);
    const loc = (n) => gl.getUniformLocation(this.prog, n), at = (n) => gl.getAttribLocation(this.prog, n);
    gl.uniformMatrix4fv(loc('mvp'), false, mvp); gl.uniform3fv(loc('light'), this.opts.light); gl.uniform1f(loc('night'), this.opts.night ? 1 : 0);
    for (const p of this.parts) {
      gl.bindBuffer(gl.ARRAY_BUFFER, p.vb); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, p.ib);
      for (const [name, size, off] of [['pos', 3, 0], ['nrm', 3, 3], ['uv', 2, 6], ['col', 3, 8]]) { const a = at(name); gl.enableVertexAttribArray(a); gl.vertexAttribPointer(a, size, gl.FLOAT, false, 44, off * 4); }
      gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, p.tex); gl.uniform1i(loc('tex'), 0); gl.uniform1f(loc('flat_'), p.flat ? 1 : 0);
      gl.drawElements(gl.TRIANGLES, p.count, p.type, 0);
    }
  }
  snapshot() { this.draw(); return this.c.toDataURL('image/png'); }
}

function persp(fovy, aspect, n, f) { const t = 1 / Math.tan(fovy / 2); return [t / aspect, 0, 0, 0, 0, t, 0, 0, 0, 0, (f + n) / (n - f), -1, 0, 0, 2 * f * n / (n - f), 0]; }
function sub(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
function norm(a) { const l = Math.hypot(...a) || 1; return a.map((v) => v / l); }
function look(e, t, up) {
  const z = norm(sub(e, t)), x = norm(cross(up, z)), y = cross(z, x);
  return [x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0, -(x[0] * e[0] + x[1] * e[1] + x[2] * e[2]), -(y[0] * e[0] + y[1] * e[1] + y[2] * e[2]), -(z[0] * e[0] + z[1] * e[1] + z[2] * e[2]), 1];
}
function mul(a, b) { const o = new Array(16).fill(0); for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) for (let k = 0; k < 4; k++) o[j * 4 + i] += a[k * 4 + i] * b[j * 4 + k]; return o; }

export function dataImage(b64) {
  return new Promise((res, rej) => { const im = new Image(); im.onload = () => res(im); im.onerror = rej; im.src = 'data:image/png;base64,' + b64; });
}
export function boundsOf(parts) {
  const min = [1e9, 1e9, 1e9], max = [-1e9, -1e9, -1e9];
  for (const p of parts) for (let i = 0; i < p.positions.length; i += 3) for (let k = 0; k < 3; k++) { min[k] = Math.min(min[k], p.positions[i + k]); max[k] = Math.max(max[k], p.positions[i + k]); }
  return [min, max];
}
