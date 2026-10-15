import { get, put, del, q } from '../api.js';
import { S, changed } from '../state.js';
import { h, mount, toast, select, debounce, pickFile, loadImage, download, prompt, confirmBox } from '../ui.js';
import { PixelEditor } from '../pixel.js';
import { Viewer, dataImage, boundsOf } from '../viewer.js';

export const id = 'textures', title = 'Textures', icon = '▦', needsProject = true;

const CATS = [
  ['Villagers', '/Npc/Normal/Model/', ''], ['Special characters', '/Npc/Special/Model/', ''],
  ['Tops', '/Item/Model/', 'tops_'], ['Bottoms', '/Item/Model/', 'btms_'], ['Hats & caps', '/Item/Model/', 'cap_'], ['Helmets', '/Item/Model/', 'hlmt_'], ['Wigs', '/Item/Model/', 'mjk_'],
  ['Accessories', '/Item/Model/', 'acc_'], ['Socks', '/Item/Model/', 'sock_'], ['Shoes', '/Item/Model/', 'bot'], ['Furniture', '/Item/Model/', 'rmk_'], ['Interior items', '/Item/Model/', 'int_'], ['Carpets', '/Item/Model/', 'carpet_'], ['Wallpapers', '/Item/Model/', 'wall_'],
  ['Player body', '/Player/', ''], ['Buildings', '/Strc/sobj/', ''], ['Anything…', '/', ''],
];

// entry name for a model+texture; the PNG lives in the project assets
export const assetName = (file, tex) => 'tex_' + (file + ':' + tex).replace(/[^A-Za-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(-60) + '.png';

export function render(root, app) {
  const P = S.project;
  const preset = app.preset; app.preset = null;
  const st = { cat: 0, q: '', model: null, texs: [], tex: null, loading: false, dirty: false, worn: [], wornIdx: 0 };
  const left = h('div', { class: 'pane' }), center = h('div', { class: 'pane', style: { display: 'flex', flexDirection: 'column' } }), right = h('div', { class: 'pane pad' });
  mount(root, h('div', { class: 'page-head' }, h('h2', {}, 'Texture studio'), h('p', {}, 'Repaint villagers, clothes, furniture or any game model. Edits are saved as PNGs in the project.')),
    h('div', { class: 'split', style: { gridTemplateColumns: '270px minmax(420px,1fr) 360px' } }, left, center, right));

  const editor = new PixelEditor({ onchange: () => { st.dirty = true; saveSoon(); viewerTex(); uvEdges(); }, freeSize: true, filename: () => (st.model || 'model').split('/').pop().replace('.bcres', '') + '_' + (st.tex || 'texture'),
    validate: (w, hh) => (w % 8 || hh % 8) ? 'Width and height must be multiples of 8 (the game\'s texture format)' : null });
  let viewer = null, viewerModel = null;

  // ---- model list
  const list = h('div', { class: 'list' });
  const search = h('input', { type: 'search', placeholder: 'Filter…' });
  const customPrefix = h('input', { type: 'text', value: '/', style: { display: 'none' }, placeholder: '/Item/Model/' });
  const pills = h('div', { class: 'pill-row', style: { padding: '8px 10px' } }, CATS.map(([n], i) => h('button', { class: i === st.cat ? 'on' : '', onclick: () => { st.cat = i; customPrefix.style.display = CATS[i][0] === 'Anything…' ? '' : 'none'; pills.querySelectorAll('button').forEach((b, k) => b.classList.toggle('on', k === i)); loadList(); } }, n)));
  mount(left, pills, h('div', { style: { padding: '0 10px 8px', display: 'grid', gap: '6px' } }, customPrefix, search), list);
  const edited = (file) => P.textures.filter((t) => t.file === file).length;
  const loadList = debounce(async () => {
    const [name, prefix, pre] = CATS[st.cat];
    const base = name === 'Anything…' ? customPrefix.value : prefix;
    const r = await get('/api/game/models?' + q({ prefix: base + pre, q: search.value }));
    mount(list, r.length ? r.map((p) => h('div', { class: 'item' + (p === st.model ? ' on' : ''), onclick: () => openModel(p) }, h('span', {}, p.split('/').slice(-1)[0].replace('.bcres', '')), edited(p) ? h('span', { class: 'chip ok sub' }, edited(p)) : null))
      : h('div', { class: 'empty' }, 'No model'));
  }, 120);
  search.addEventListener('input', loadList); customPrefix.addEventListener('input', loadList);
  loadList();

  async function openModel(path, texName) {
    await flush();
    st.model = path; st.tex = null;
    st.texs = await get('/api/game/model-textures?path=' + encodeURIComponent(path));
    st.worn = await get('/api/game/preview-models?path=' + encodeURIComponent(path)); st.wornIdx = 0;
    loadList(); drawCenter(); loadViewerModel(st.worn.length ? st.worn[0][1] : path, st.worn.length > 0);
    const t = texName ? st.texs.find((x) => x.name === texName) : st.texs.find((x) => x.supported);
    if (t) openTexture(t.name);
  }

  async function openTexture(name) {
    await flush();
    st.tex = name; drawRight();
    const t = st.texs.find((x) => x.name === name);
    if (!t || !t.supported) { editor.px = null; mount(editorHost, h('div', { class: 'empty' }, 'The format ' + (t ? t.fmt : '') + ' cannot be edited yet.')); return; }
    const e = P.textures.find((x) => x.file === st.model && x.name === name);
    const url = e ? `/api/project/${S.pid}/asset/${encodeURIComponent(e.png)}?t=${Date.now()}` : `/api/game/texture?${q({ path: st.model, name })}`;
    const img = await loadImage(url);
    editor.load(img); mount(editorHost, editor.el); editor.fit(); st.dirty = false; drawRight(); viewerTex(); uvEdges();
  }

  // ---- saving
  const saveSoon = debounce(() => flush(), 900);
  async function flush() {
    if (!st.dirty || !st.model || !st.tex || !editor.px) return;
    st.dirty = false;
    const name = assetName(st.model, st.tex);
    try {
      await put(`/api/project/${S.pid}/asset/${encodeURIComponent(name)}`, await editor.toBlob());
      let e = P.textures.find((x) => x.file === st.model && x.name === st.tex);
      if (!e) { e = { file: st.model, name: st.tex, png: name }; P.textures.push(e); }
      changed(); drawRight(); loadList();
    } catch (er) { toast('Could not save the texture: ' + er.message, 'error'); st.dirty = true; }
  }

  // ---- center: model + editor
  const editorHost = h('div', { style: { flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' } });
  function drawCenter() {
    if (!st.model) { mount(center, h('div', { class: 'empty' }, 'Choose a model on the left (a villager, a shirt, a chair…).')); return; }
    mount(center,
      h('div', { class: 'tabs' }, st.texs.map((t) => h('button', { class: t.name === st.tex ? 'on' : '', title: t.w + '×' + t.h + ' ' + t.fmt, onclick: () => openTexture(t.name) },
        t.name, P.textures.some((x) => x.file === st.model && x.name === t.name) ? ' ●' : '', t.supported ? '' : ' (read-only)'))),
      h('div', { class: 'toolbar' }, h('b', {}, st.model.replace(/^\//, '')),
        h('div', { class: 'grow' }),
        h('button', { class: 'small danger', onclick: revert }, 'Revert to original')),
      h('div', { class: 'toolbar' }, h('span', { class: 'dim' }, 'Recolor'),
        h('button', { class: 'small', onclick: () => editor.px && editor.hueShift(30) }, 'Hue +30°'), h('button', { class: 'small', onclick: () => editor.px && editor.hueShift(-30) }, 'Hue −30°'),
        h('button', { class: 'small', onclick: () => editor.px && editor.hueShift(0, 1.3, 1) }, 'Saturate'), h('button', { class: 'small', onclick: () => editor.px && editor.hueShift(0, 0.6, 1) }, 'Desaturate'),
        h('button', { class: 'small', onclick: () => editor.px && editor.hueShift(0, 1, 1.15) }, 'Lighter'), h('button', { class: 'small', onclick: () => editor.px && editor.hueShift(0, 1, 0.85) }, 'Darker'),
        h('div', { class: 'sep-v' }), h('button', { class: 'small', onclick: () => editor.px && editor.flip(true) }, 'Flip ⇆'), h('button', { class: 'small', onclick: () => editor.px && editor.flip(false) }, 'Flip ⇅')),
      editorHost);
    if (!editor.px) mount(editorHost, h('div', { class: 'empty' }, 'Pick a texture tab above.'));
    else mount(editorHost, editor.el);
  }
  async function revert() {
    const i = P.textures.findIndex((x) => x.file === st.model && x.name === st.tex);
    if (i < 0) { toast('Already the original', 'info'); return; }
    if (!await confirmBox('Drop your edits of ' + st.tex + ' and use the game’s texture again?', 'Revert')) return;
    const e = P.textures[i]; P.textures.splice(i, 1);
    try { await del(`/api/project/${S.pid}/asset/${encodeURIComponent(e.png)}`); } catch (er) { /* already gone */ }
    changed(); st.dirty = false; openTexture(st.tex); loadList(); drawCenter();
  }

  // ---- right: preview
  const canvas = h('canvas', { style: { width: '100%', height: '320px', borderRadius: '6px', background: '#8cb8e6' } });
  async function loadViewerModel(path, asWorn) {
    if (!viewer) { try { viewer = new Viewer(canvas, { light: [0.3, 0.8, 0.6] }); } catch (e) { viewer = null; } }
    if (!viewer || !viewer.ok) return;
    try {
      const m = await get('/api/game/mesh?path=' + encodeURIComponent(path));
      if (asWorn) { for (const p of m.parts) p.texture = st.texs[0] ? st.texs[0].name : null; m.textures = {}; }
      else if (st.model !== path) return;
      const imgs = {};
      for (const [n, b64] of Object.entries(m.textures)) imgs[n] = await dataImage(b64);
      viewerModel = m;
      const parts = m.parts.filter((p) => p.positions.length).map((p) => ({ ...p, image: p.texture ? imgs[p.texture] : null, flat: !p.texture && !asWorn }));
      viewer.setParts(parts.map((p) => ({ ...p, image: p.image || blankImg() })));
      viewer.partTextures = parts.map((p) => p.texture);
      uvEdges(); 
      const [mn, mx] = boundsOf(m.parts); viewer.frame(mn, mx); viewer.yaw = 0.5; viewer.pitch = 0.2;
      for (const e of P.textures.filter((x) => x.file === st.model)) if (e.name !== st.tex) applyTexture(e.name, await loadImage(`/api/project/${S.pid}/asset/${encodeURIComponent(e.png)}`));
      viewerTex(); uvEdges();
    } catch (e) { viewerModel = null; }
  }
  // the model's UV layout over the texture, so you can see which part is which
  function uvEdges() {
    if (!viewerModel || !st.tex || !editor.px) { editor.setUV(null); return; }
    const seen = new Set(), out = [], w = editor.w, hh = editor.h;
    for (const p of viewerModel.parts) {
      if (p.texture !== st.tex) continue;
      for (let i = 0; i + 2 < p.indices.length; i += 3) for (let k = 0; k < 3; k++) {
        const a = p.indices[i + k], b = p.indices[i + (k + 1) % 3];
        const key = a < b ? a + ',' + b : b + ',' + a; if (seen.has(key)) continue; seen.add(key);
        const x0 = p.uvs[a * 2] * w, y0 = (1 - p.uvs[a * 2 + 1]) * hh, x1 = p.uvs[b * 2] * w, y1 = (1 - p.uvs[b * 2 + 1]) * hh;
        if (Math.abs(x0 - x1) > w / 2 || Math.abs(y0 - y1) > hh / 2) continue;      // a tiling seam
        out.push([x0, y0, x1, y1]);
      }
    }
    editor.setUV(out);
  }
  const blankImg = () => { const c = document.createElement('canvas'); c.width = c.height = 2; const g = c.getContext('2d'); g.fillStyle = '#bbb'; g.fillRect(0, 0, 2, 2); return c; };
  function applyTexture(name, img) { if (!viewer || !viewer.partTextures) return; viewer.partTextures.forEach((n, i) => { if (n === name) viewer.setImage(i, img); }); }
  const viewerTex = debounce(() => { if (viewer && st.tex && editor.px) applyTexture(st.tex, editor.toCanvas()); }, 80);

  function drawRight() {
    const t = st.texs.find((x) => x.name === st.tex);
    mount(right, h('div', { class: 'panel-title' }, '3D preview'),
      st.worn.length ? h('div', { class: 'row', style: { marginBottom: '6px' } }, h('span', { class: 'dim' }, 'Worn as'), (() => { const sel = select(st.worn.map((w, i) => [i, w[0]]), st.wornIdx, (v) => { st.wornIdx = +v; loadViewerModel(st.worn[st.wornIdx][1], true); }); sel.style.flex = 1; return sel; })()) : null,
      canvas,
      h('p', { class: 'dim', style: { fontSize: '12px' } }, 'Drag to rotate, wheel to zoom, right-drag to pan. Characters show in their bind pose; textures update as you paint.'),
      t ? h('div', { class: 'card' }, h('h3', {}, 'Texture'), h('div', { class: 'dim' }, `${t.name} — ${t.w}×${t.h}, ${t.fmt}${t.mips > 1 ? ', ' + t.mips + ' mip levels' : ''}`),
        t.fmt === 'ETC1A4' ? h('p', { class: 'dim', style: { fontSize: '12px', marginBottom: 0 } }, 'The alpha channel is both transparency and (for many models) a gloss/detail map: keep it opaque unless you want a cut-out.') : null) : null,
      P.textures.length ? h('div', { class: 'card', style: { marginTop: '10px' } }, h('h3', {}, 'Edited in this project'), h('div', { class: 'list' }, P.textures.map((e) => h('div', { class: 'item', onclick: () => openModel(e.file, e.name) }, h('span', {}, e.file.split('/').pop().replace('.bcres', '') + ' · ' + e.name))))) : null);
  }
  drawCenter(); drawRight();
  if (preset && preset.model) openModel(preset.model, preset.tex);
  return () => { flush(); editor.destroy(); };
}
