import { get } from '../api.js';
import { S, changed } from '../state.js';
import { h, mount, select, debounce, textInput, field } from '../ui.js';
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
      const skin = P.textures.some((t) => t.file === v.model);
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
    const ensure = () => { if (!e) { e = { id: v.id, name: {}, catchphrase: {} }; P.villagers.push(e); } return e; };
    const prune = () => { if (e && !Object.values(e.name || {}).some(Boolean) && !Object.values(e.catchphrase || {}).some(Boolean)) { P.villagers.splice(P.villagers.indexOf(e), 1); e = null; } };
    const tabs = h('div', { class: 'tabs', style: { marginBottom: '12px' } }, LANGS.map((l) => h('button', { class: l === st.lang ? 'on' : '', onclick: () => { st.lang = l; drawMain(); } }, l.toUpperCase())));
    mount(main,
      h('div', { class: 'row', style: { marginBottom: '8px' } }, h('h2', {}, v.name), h('span', { class: 'chip' }, v.species), h('span', { class: 'dim' }, v.id)),
      tabs,
      h('div', { class: 'grid2' },
        field('Name (' + st.lang + ')', textInput((e && e.name && e.name[st.lang]) || '', (val) => { ensure().name = e.name || {}; if (val) e.name[st.lang] = val; else delete e.name[st.lang]; prune(); changed(); draw(); }, { placeholder: v.name }), 'Shown everywhere: dialogue boxes, the town map, mail.'),
        field('Catch phrase (' + st.lang + ')', textInput((e && e.catchphrase && e.catchphrase[st.lang]) || '', (val) => { ensure().catchphrase = e.catchphrase || {}; if (val) e.catchphrase[st.lang] = val; else delete e.catchphrase[st.lang]; prune(); changed(); draw(); }, { placeholder: v.catchphrase }), 'Added at the end of what they say.')),
      h('div', { class: 'info-box', style: { marginTop: '14px' } }, 'A villager’s conversation lines come from their personality, shared by every villager of that personality: change them in ', h('a', { href: '#dialogue', style: { color: 'inherit' } }, 'Dialogue'), ' (files AN_, BO_, FU_, GE_, HA_, KO_, OT_, ZK_ are the eight personalities).'),
      h('div', { class: 'row', style: { marginTop: '14px' } }, h('button', { class: 'primary', onclick: () => { app.preset = { model: v.model }; app.go('textures'); } }, 'Paint ' + v.name + '…'),
        P.textures.some((t) => t.file === v.model) ? h('span', { class: 'chip warn' }, 'has a custom skin') : null));
    mount(side, h('div', { class: 'panel-title' }, 'Preview'), canvas, h('p', { class: 'dim', style: { fontSize: '12px' } }, 'Bind pose, original skin. Open the texture studio to repaint it.'));
    loadModel(v);
  }
  async function loadModel(v) {
    if (!viewer) { try { viewer = new Viewer(canvas, { light: [0.3, 0.8, 0.6] }); } catch (er) { viewer = null; } }
    if (!viewer || !viewer.ok) return;
    const m = await get('/api/game/mesh?path=' + encodeURIComponent(v.model));
    if (st.sel !== v.id) return;
    const imgs = {}; for (const [n, b] of Object.entries(m.textures)) imgs[n] = await dataImage(b);
    const parts = m.parts.filter((p) => p.positions.length && p.texture).map((p) => ({ ...p, image: imgs[p.texture] }));
    viewer.setParts(parts); const [mn, mx] = boundsOf(parts); viewer.frame(mn, mx); viewer.yaw = 0.4; viewer.pitch = 0.15;
  }
  drawMain();
}
