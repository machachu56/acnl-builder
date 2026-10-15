import { get, put, del, q } from '../api.js';
import { S, changed } from '../state.js';
import { h, mount, select, debounce, textInput, field, modal, prompt, confirmBox, pickFile, loadImage, toast } from '../ui.js';
import { PixelEditor } from '../pixel.js';
import { Viewer, dataImage, boundsOf } from '../viewer.js';

export const id = 'villagers', title = 'Villagers', icon = '☺', needsProject = true;
const LANGS = ['en', 'es', 'fr', 'it', 'de'];

export function render(root, app) {
  const P = S.project;
  const st = { all: [], species: '', q: '', sel: null, lang: 'en' };
  const left = h('div', { class: 'pane' }), main = h('div', { class: 'pane pad' }), side = h('div', { class: 'pane pad' });
  mount(root, h('div', { class: 'page-head' }, h('h2', {}, 'Villagers'), h('p', {}, 'Rename a villager, give them a new catch phrase and repaint them. A new character is a re-skinned existing one.')),
    h('div', { class: 'split', style: { gridTemplateColumns: '290px minmax(360px,1fr) 360px' } }, left, main, side));

  const list = h('div', { class: 'list' });
  const search = h('input', { type: 'search', placeholder: 'Search a villager…' });
  const spec = h('select', {});
  const draw = () => {
    const q = search.value.toLowerCase();
    mount(list, st.all.filter((v) => (!spec.value || v.species === spec.value) && (!q || (v.name + v.id).toLowerCase().includes(q))).slice(0, 300).map((v) => {
      const e = P.villagers.find((x) => x.id === v.id);
      const skin = P.textures.some((t) => t.file === v.model) || (e && (e.outfits || []).length);
      return h('div', { class: 'item' + (st.sel === v.id ? ' on' : ''), onclick: () => { st.sel = v.id; draw(); drawMain(); } },
        h('span', {}, (e && e.name && e.name.en) || v.name), h('span', { class: 'dim', style: { fontSize: '12px' } }, v.species),
        h('span', { class: 'sub' }, e ? h('span', { class: 'chip ok' }, 'renamed') : null, skin ? h('span', { class: 'chip warn', style: { marginLeft: '4px' } }, 'skin') : null));
    }));
  };
  search.addEventListener('input', debounce(draw, 100)); spec.addEventListener('change', draw);
  mount(left, h('div', { style: { padding: '10px', display: 'grid', gap: '6px', position: 'sticky', top: 0, background: 'var(--bg)', zIndex: 2 } }, search, spec), list);
  get('/api/game/villagers').then((v) => { st.all = v; st.sel = st.sel || (v[0] && v[0].id); const sp = [...new Set(v.map((x) => x.species))].sort(); mount(spec, h('option', { value: '' }, 'All species'), sp.map((s) => h('option', { value: s }, s))); draw(); drawMain(); });

  let viewer = null;
  const canvas = h('canvas', { style: { width: '100%', height: '300px', borderRadius: '6px' } });
  function drawMain() {
    const v = st.all.find((x) => x.id === st.sel);
    if (!v) { mount(main, h('div', { class: 'empty' }, 'Pick a villager.')); mount(side); return; }
    let e = P.villagers.find((x) => x.id === v.id);
    const ensure = () => { if (!e) { e = { id: v.id, name: {}, catchphrase: {} }; if (v.special) e.model = v.model; P.villagers.push(e); } return e; };
    const prune = () => { if (e && !Object.values(e.name || {}).some(Boolean) && !Object.values(e.catchphrase || {}).some(Boolean) && !(e.outfits || []).length) { P.villagers.splice(P.villagers.indexOf(e), 1); e = null; } };
    const tabs = h('div', { class: 'tabs', style: { marginBottom: '12px' } }, LANGS.map((l) => h('button', { class: l === st.lang ? 'on' : '', onclick: () => { st.lang = l; drawMain(); } }, l.toUpperCase())));
    mount(main,
      h('div', { class: 'row', style: { marginBottom: '8px' } }, h('h2', {}, v.name), h('span', { class: 'chip' }, v.species), h('span', { class: 'dim' }, v.id)),
      v.special ? h('div', { class: 'info-box' }, 'A special character (shopkeeper, secretary, visitor…), listed by the game’s file code: its name and lines are not editable here, but it can have outfits.') : tabs,
      v.special ? null : h('div', { class: 'grid2' },
        field('Name (' + st.lang + ')', textInput((e && e.name && e.name[st.lang]) || '', (val) => { ensure().name = e.name || {}; if (val) e.name[st.lang] = val; else delete e.name[st.lang]; prune(); changed(); draw(); }, { placeholder: v.name }), 'Shown everywhere: dialogue boxes, the town map, mail.'),
        field('Catch phrase (' + st.lang + ')', textInput((e && e.catchphrase && e.catchphrase[st.lang]) || '', (val) => { ensure().catchphrase = e.catchphrase || {}; if (val) e.catchphrase[st.lang] = val; else delete e.catchphrase[st.lang]; prune(); changed(); draw(); }, { placeholder: v.catchphrase }), 'Added at the end of what they say.')),
      v.special ? null : h('div', { class: 'info-box', style: { marginTop: '14px' } }, 'A villager’s conversation lines come from their personality, shared by every villager of that personality: change them in ', h('a', { href: '#dialogue', style: { color: 'inherit' } }, 'Dialogue'), ' (files AN_, BO_, FU_, GE_, HA_, KO_, OT_, ZK_ are the eight personalities).'),
      h('div', { class: 'row', style: { marginTop: '14px' } }, h('button', { class: 'primary', onclick: () => { app.preset = { model: v.model }; app.go('textures'); } }, 'Paint ' + v.name + '…'),
        P.textures.some((t) => t.file === v.model) ? h('span', { class: 'chip warn' }, 'has a custom skin') : null),
      outfitsCard(v, ensure, prune));
    mount(side, h('div', { class: 'panel-title' }, 'Preview'), canvas, h('p', { class: 'dim', style: { fontSize: '12px' } }, 'Bind pose, original skin. Open the texture studio to repaint it.'));
    loadModel(v);
  }
  // ---- outfits: the villager's clothes are painted on the body texture, so an outfit is another version of it
  const outfitPng = (v, o, tex) => `/api/project/${S.pid}/asset/${encodeURIComponent(o.textures[tex])}?t=${Date.now()}`;
  async function bodyTexture(v) {
    const texs = await get('/api/game/model-textures?path=' + encodeURIComponent(v.model));
    const t = texs.find((x) => x.supported && !/^e[.\d]/.test(x.name)) || texs.find((x) => x.supported);
    return t ? t.name : null;
  }
  // the texture as it is now (your plain skin edit, or the game's)
  async function currentLook(v, tex) {
    const e = P.textures.find((x) => x.file === v.model && x.name === tex);
    return loadImage(e ? `/api/project/${S.pid}/asset/${encodeURIComponent(e.png)}?t=${Date.now()}` : '/api/game/texture?' + q({ path: v.model, name: tex }));
  }
  const slug = (n) => n.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 16) || 'outfit';
  async function saveOutfitImage(v, o, tex, blobOrCanvas) {
    const name = `outfit_${v.id}_${o.id}_${tex.replace(/[^A-Za-z0-9]/g, '_')}.png`;
    const blob = blobOrCanvas instanceof Blob ? blobOrCanvas : await new Promise((r) => blobOrCanvas.toBlob(r, 'image/png'));
    await put(`/api/project/${S.pid}/asset/${encodeURIComponent(name)}`, blob);
    o.textures = { ...(o.textures || {}), [tex]: name };
  }
  async function newOutfit(v, ensure, fromFile) {
    const tex = await bodyTexture(v); if (!tex) { toast('This model has no texture that can be edited', 'error'); return; }
    let img = null;
    if (fromFile) {
      const f = await pickFile('image/png,image/*'); if (!f) return;
      img = await loadImage(URL.createObjectURL(f));
      if (img.width % 8 || img.height % 8) { toast('Width and height must be multiples of 8', 'error'); return; }
    }
    const name = await prompt(fromFile ? 'Outfit from a PNG' : 'New outfit', 'Name', 'Work clothes'); if (!name) return;
    const vv = ensure(); vv.outfits = vv.outfits || [];
    let id = slug(name); for (let n = 2; vv.outfits.some((x) => x.id === id); n++) id = slug(name) + n;
    const o = { id, name, textures: {} };
    try {
      const c = document.createElement('canvas'); const src = img || await currentLook(v, tex);
      c.width = src.width; c.height = src.height; c.getContext('2d').drawImage(src, 0, 0);
      await saveOutfitImage(v, o, tex, c);
    } catch (er) { toast('Could not create the outfit: ' + er.message, 'error'); return; }
    vv.outfits.push(o); changed(); draw(); drawMain();
    if (!fromFile) paintOutfit(v, o, tex);
  }
  async function paintOutfit(v, o, tex) {
    tex = tex || Object.keys(o.textures)[0];
    const ed = new PixelEditor({ filename: () => v.id + '_' + o.id + '_' + tex, freeSize: true, validate: (w, hh) => (w % 8 || hh % 8) ? 'Width and height must be multiples of 8' : null });
    ed.load(await loadImage(outfitPng(v, o, tex)));
    try {      // the model's UV layout over the texture, so you can see which part is which
      const m = await get('/api/game/mesh?path=' + encodeURIComponent(v.model)), seen = new Set(), edges = [];
      for (const p of m.parts) if (p.texture === tex) for (let i = 0; i + 2 < p.indices.length; i += 3) for (let k = 0; k < 3; k++) {
        const a = p.indices[i + k], b = p.indices[i + (k + 1) % 3], key = a < b ? a + ',' + b : b + ',' + a; if (seen.has(key)) continue; seen.add(key);
        const x0 = p.uvs[a * 2] * ed.w, y0 = (1 - p.uvs[a * 2 + 1]) * ed.h, x1 = p.uvs[b * 2] * ed.w, y1 = (1 - p.uvs[b * 2 + 1]) * ed.h;
        if (Math.abs(x0 - x1) < ed.w / 2 && Math.abs(y0 - y1) < ed.h / 2) edges.push([x0, y0, x1, y1]);
      }
      ed.setUV(edges);
    } catch (er) { /* no overlay */ }
    const holder = h('div', { style: { width: '760px', maxWidth: '84vw', height: '560px' } }, ed.el);
    setTimeout(() => ed.fit(), 40);
    const r = await modal('Paint · ' + o.name + ' (' + v.name + ')', holder, [{ label: 'Cancel', value: false }, { label: 'Save outfit', value: true, primary: true }]);
    if (r) { try { await saveOutfitImage(v, o, tex, await ed.toBlob()); changed(); } catch (er) { toast(er.message, 'error'); } }
    ed.destroy(); drawMain();
  }
  function outfitsCard(v, ensure, prune) {
    const e = P.villagers.find((x) => x.id === v.id), outfits = (e && e.outfits) || [];
    const row = (o) => {
      const isDef = e.default_outfit === o.id;
      return h('div', { class: 'row', style: { gap: '6px', padding: '4px 0', borderTop: '1px solid var(--line)' } },
        h('b', {}, o.name), isDef ? h('span', { class: 'chip ok' }, 'worn by default') : null, h('div', { class: 'grow' }),
        h('button', { class: 'small', onclick: () => showOutfit(v, o) }, 'Preview'),
        h('button', { class: 'small', onclick: () => paintOutfit(v, o) }, 'Paint…'),
        h('button', { class: 'small', title: 'Replace this outfit with a PNG file', onclick: async () => { const f = await pickFile('image/png,image/*'); if (!f) return; const im = await loadImage(URL.createObjectURL(f)); if (im.width % 8 || im.height % 8) { toast('Width and height must be multiples of 8', 'error'); return; } await saveOutfitImage(v, o, Object.keys(o.textures)[0], f); changed(); showOutfit(v, o); } }, 'Import PNG'),
        h('button', { class: 'small', onclick: async () => { const a = h('a', { href: outfitPng(v, o, Object.keys(o.textures)[0]), download: v.id + '_' + o.id + '.png' }); document.body.append(a); a.click(); a.remove(); } }, 'Export PNG'),
        h('button', { class: 'small', onclick: () => { if (isDef) delete e.default_outfit; else e.default_outfit = o.id; changed(); drawMain(); } }, isDef ? 'Not by default' : 'Wear by default'),
        h('button', { class: 'small ghost danger', onclick: async () => { if (!await confirmBox('Delete the outfit ' + o.name + '?', 'Delete')) return; e.outfits.splice(e.outfits.indexOf(o), 1); if (e.default_outfit === o.id) delete e.default_outfit; for (const f of Object.values(o.textures)) { try { await del(`/api/project/${S.pid}/asset/${encodeURIComponent(f)}`); } catch (er) { /* gone */ } } prune(); changed(); draw(); drawMain(); } }, '×'));
    };
    return h('div', { class: 'card', style: { marginTop: '14px' } }, h('h3', {}, 'Outfits'),
      h('div', { class: 'dim', style: { fontSize: '12px', marginBottom: '6px' } }, v.name + '’s clothes are painted on the body texture. An outfit is another version of it: paint one here or import a PNG (export one to edit it in another program). The one marked “worn by default” is what the mod ships; the others are kept for scripts that swap clothes in the game.'),
      outfits.map(row),
      h('div', { class: 'row', style: { marginTop: '8px' } }, h('button', { onclick: () => newOutfit(v, ensure, false) }, '+ New outfit (paint)'), h('button', { onclick: () => newOutfit(v, ensure, true) }, '+ From a PNG…')));
  }
  async function showOutfit(v, o) {
    if (!viewer || !viewer.partTextures) return;
    const tex = Object.keys(o.textures)[0], img = await loadImage(outfitPng(v, o, tex));
    viewer.partTextures.forEach((n, i) => { if (n === tex) viewer.setImage(i, img); });
  }
  async function loadModel(v) {
    if (!viewer) { try { viewer = new Viewer(canvas, { light: [0.3, 0.8, 0.6] }); } catch (er) { viewer = null; } }
    if (!viewer || !viewer.ok) return;
    const m = await get('/api/game/mesh?path=' + encodeURIComponent(v.model));
    if (st.sel !== v.id) return;
    const imgs = {}; for (const [n, b] of Object.entries(m.textures)) imgs[n] = await dataImage(b);
    const parts = m.parts.filter((p) => p.positions.length && p.texture).map((p) => ({ ...p, image: imgs[p.texture] }));
    viewer.setParts(parts); viewer.partTextures = parts.map((p) => p.texture); const [mn, mx] = boundsOf(parts); viewer.frame(mn, mx); viewer.yaw = 0.4; viewer.pitch = 0.15;
  }
  drawMain();
}
