import { get } from '../api.js';
import { S, changed } from '../state.js';
import { h, mount, toast, select, debounce, field, checkbox } from '../ui.js';
import { Viewer, dataImage, boundsOf } from '../viewer.js';

export const id = 'furniture', title = 'Furniture', icon = '⊓', needsProject = true;

const SHOWN = 400;          // rows drawn at once (the search narrows the 1,904 items)

export function defaults() {
  return { enabled: false, which: 'all', list: [], exclude: [], solid: true, face: 'player', pickup: 'game' };
}

// how many items the project turns into models (also the nav count)
export function count(f, total = 1904) {
  if (!f || !f.enabled) return 0;
  return f.which === 'list' ? (f.list || []).length : total - (f.exclude || []).length;
}

export function render(root) {
  const P = S.project;
  P.furniture = Object.assign(defaults(), P.furniture || {});
  const F = P.furniture;
  const st = { items: null, sel: null, q: '', show: 'all' };
  const left = h('div', { class: 'pane', style: { display: 'flex', flexDirection: 'column' } }),
    mid = h('div', { class: 'pane', style: { display: 'flex', flexDirection: 'column', background: '#0f1215' } }), right = h('div', { class: 'pane' });
  mount(root, h('div', { class: 'page-head' }, h('h2', {}, 'Furniture outside'),
    h('p', {}, 'Furniture you drop on the ground in your town shows as its real 3D model instead of a leaf. The item stays on the ground under it, so it saves with the game and you pick it up as usual.')),
  h('div', { class: 'split', style: { gridTemplateColumns: '340px minmax(360px,1fr) 360px' } }, left, mid, right));

  const inMod = (i) => (F.which === 'list' ? F.list.includes(i) : !F.exclude.includes(i));
  function setIn(i, on) {
    const key = F.which === 'list' ? 'list' : 'exclude', want = F.which === 'list' ? on : !on;
    const s = new Set(F[key]);
    if (want) s.add(i); else s.delete(i);
    F[key] = [...s].sort((a, b) => a - b);
  }
  const hex = (i) => '0x' + i.toString(16).toUpperCase();

  // ---- the items
  const search = h('input', { type: 'search', placeholder: 'Search a name, a model or an ID…', style: { flex: 1 } });
  search.addEventListener('input', debounce(() => { st.q = search.value.trim().toLowerCase(); drawList(); }, 150));
  const showSel = select([['all', 'All items'], ['in', 'In the mod'], ['out', 'Left out']], st.show, (v) => { st.show = v; drawList(); });
  const listBox = h('div', { class: 'list', style: { flex: 1, overflow: 'auto' } });
  const listFoot = h('div', { class: 'toolbar', style: { borderTop: '1px solid var(--line)', borderBottom: 0 } });
  mount(left, h('div', { class: 'toolbar' }, search, showSel), listBox, listFoot);

  function matches() {
    if (!st.items) return [];
    const q = st.q;
    return st.items.filter((e) => {
      if (st.show === 'in' && !inMod(e.id)) return false;
      if (st.show === 'out' && inMod(e.id)) return false;
      return !q || e.name.toLowerCase().includes(q) || e.model.toLowerCase().includes(q) || hex(e.id).toLowerCase().includes(q);
    });
  }
  function drawList() {
    if (!st.items) { mount(listBox, h('div', { class: 'empty' }, 'Loading the game’s furniture…')); return; }
    const m = matches();
    mount(listBox, m.slice(0, SHOWN).map((e) => {
      const box = h('input', { type: 'checkbox', checked: inMod(e.id), disabled: !F.enabled });
      box.addEventListener('click', (ev) => { ev.stopPropagation(); setIn(e.id, box.checked); changed(); drawFoot(); });
      return h('div', { class: 'item' + (e.id === st.sel ? ' on' : ''), onclick: () => { st.sel = e.id; drawList(); preview.now(); } },
        box, h('span', {}, e.name), h('span', { class: 'sub' }, hex(e.id)));
    }), m.length > SHOWN ? h('div', { class: 'empty', style: { padding: '12px' } }, (m.length - SHOWN) + ' more: search to narrow the list') : null,
    m.length ? null : h('div', { class: 'empty' }, 'No furniture matches'));
    drawFoot(m);
  }
  function drawFoot(m) {
    m = m || matches();
    const n = st.items ? count(F, st.items.length) : 0;
    mount(listFoot, h('span', { class: 'dim', style: { fontSize: '12px' } }, F.enabled ? n + ' of ' + (st.items ? st.items.length : '…') + ' in the mod' : 'Off'),
      h('div', { class: 'grow' }),
      h('button', { class: 'small', disabled: !F.enabled || !m.length, onclick: () => { m.forEach((e) => setIn(e.id, true)); changed(); drawList(); } }, 'Add shown'),
      h('button', { class: 'small', disabled: !F.enabled || !m.length, onclick: () => { m.forEach((e) => setIn(e.id, false)); changed(); drawList(); } }, 'Leave out shown'));
  }

  // ---- 3D preview
  const canvas = h('canvas', { style: { width: '100%', flex: 1, minHeight: 0 } });
  const info = h('span', { class: 'dim' });
  let viewer = null;
  mount(mid, h('div', { class: 'toolbar' }, ['Front', 'Side', 'Top'].map((n) => h('button', { class: 'small', onclick: () => cam(n) }, n)), h('div', { class: 'grow' }), info),
    canvas, h('div', { class: 'dim', style: { padding: '6px 12px', fontSize: '12px' } }, 'As it stands outside, facing the camera. One tile of the town is 32 units.'));
  // models face +z (south, towards the game's camera): "Front" looks from there
  function cam(n) { if (!viewer) return; const v = { Front: [0, 0.2], Side: [1.57, 0.2], Top: [0, 1.4] }[n]; viewer.yaw = v[0]; viewer.pitch = v[1]; viewer.dirty = true; }
  const preview = debounce(async () => {
    if (st.sel == null) { info.textContent = ''; return; }
    const want = st.sel;
    try {
      const r = await get('/api/furniture/preview?id=' + want);
      if (want !== st.sel) return;
      if (!viewer) {
        try { viewer = new Viewer(canvas, { light: [-0.3, 0.8, 0.6], flipV: true, yaw: 0.35, pitch: 0.4 }); } catch (e) { viewer = null; }
        if (!viewer || !viewer.ok) { toast('WebGL is not available in this browser: no 3D preview', 'error'); viewer = null; return; }
      }
      const parts = [];
      for (const p of r.parts) parts.push({ ...p, image: await dataImage(p.atlas) });
      viewer.setParts(parts);
      const [mn, mx] = boundsOf(parts);
      viewer.frame(mn, mx); viewer.dist *= 1.5;
      const [W, H, D] = r.size;
      info.textContent = r.name + ' · ' + (W / 32).toFixed(1) + ' × ' + (D / 32).toFixed(1) + ' tiles · ' + r.triangles + ' triangles';
    } catch (e) { toast('Preview failed: ' + e.message, 'error'); }
  }, 120);

  // ---- settings
  function drawRight() {
    const ch = () => { changed(); drawList(); drawRight(); };
    mount(right, h('div', { class: 'pad', style: { padding: '14px', display: 'flex', flexDirection: 'column', gap: '14px' } },
      h('div', { class: 'card' }, h('h3', {}, 'Furniture outside'), h('div', { class: 'col' },
        checkbox(F.enabled, (v) => { F.enabled = v; ch(); }, 'Show dropped furniture as its 3D model'),
        F.enabled ? field('Which furniture', select([['all', 'All furniture (but those left out)'], ['list', 'Only the items I tick']], F.which, (v) => { F.which = v; ch(); }),
          F.which === 'all' ? 'Every piece of furniture of the game, gyroids too. Untick an item to leave it a leaf. All of them add about 25 MB to the mod.'
            : 'Tick the items in the list; the others stay leaves. “Add shown” ticks everything the search shows (a series, a word…).') : null)),
      F.enabled ? h('div', { class: 'card' }, h('h3', {}, 'In the town'), h('div', { class: 'col' },
        checkbox(F.solid, (v) => { F.solid = v; changed(); }, 'Solid: you walk around it'),
        field('Facing', select([['player', 'Turned to face you when you drop it'], ['south', 'Always towards the camera']], F.face, (v) => { F.face = v; changed(); }),
          'Each piece remembers its facing after you save and come back.'),
        field('Picking it up', select([['game', 'The game’s Y, facing it'], ['hold', 'Hold Y beside it']], F.pickup, (v) => { F.pickup = v; changed(); }),
          'It goes back into the pockets like any item.'))) : null,
      F.enabled ? h('div', { class: 'card' }, h('h3', {}, 'Good to know'), h('div', { class: 'col dim', style: { fontSize: '12px', gap: '6px' } },
        h('div', {}, 'The cars of the Objects tab stay cars: their item is never turned into furniture here.'),
        h('div', {}, 'Furniture is drawn up to about 14 tiles away; the leaf comes back if the mod is removed.'),
        h('div', {}, 'The first export converts the models (about half a minute for all of them); later exports reuse them.'))) : null));
  }

  drawRight(); drawList();
  get('/api/furniture/items').then((r) => {
    st.items = r.items;
    if (st.sel == null && st.items.length) st.sel = (st.items.find((e) => e.model === 'rmk_oth_lavalamp') || st.items[0]).id;
    drawList(); preview.now();
  }).catch((e) => toast(e.message, 'error'));
}
