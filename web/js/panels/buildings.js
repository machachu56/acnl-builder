import { get, post, put, del } from '../api.js';
import { S, changed, uid } from '../state.js';
import { h, mount, toast, select, debounce, field, textInput, numInput, colorInput, checkbox, slider, modal, prompt, confirmBox, loadImage, pickFile } from '../ui.js';
import { Viewer, dataImage, boundsOf } from '../viewer.js';
import { PixelEditor } from '../pixel.js';

export const id = 'buildings', title = 'Buildings', icon = '⌂', needsProject = true;
const LANGS = ['en', 'es', 'fr', 'it', 'de'];
const COLOR_LABELS = {
  wall: 'Walls', wall_low: 'Lower walls', roof: 'Roof', roof_rim: 'Roof rim', trim: 'Trim & posts', awning_a: 'Awning stripe A', awning_b: 'Awning stripe B',
  gold: 'Door frame', door: 'Doorway', stone: 'Plinth stone', wood: 'Wood', sign_bg: 'Sign board', sign_fg: 'Sign lettering', sign_outline: 'Sign outline',
  glass: 'Window glow', curtain: 'Curtains', lamp: 'Lanterns', leaf: 'Bushes', flower: 'Flowers', pot: 'Flower pots', ornament: 'Roof ornament',
};
const COLOR_GROUPS = [['Walls', ['wall', 'wall_low', 'stone', 'wood', 'trim']], ['Roof', ['roof', 'roof_rim', 'ornament']], ['Entrance', ['awning_a', 'awning_b', 'gold', 'door', 'lamp']], ['Sign', ['sign_bg', 'sign_fg', 'sign_outline']], ['Windows & plants', ['glass', 'curtain', 'leaf', 'flower', 'pot']]];

export function newInterior(P, title) {
  const sid = uid('interior', P.interiors);
  return {
    id: sid, title: title || sid, main: 'main', materials: {
      floor_main: { type: 'floor', preset: 'carpet' }, wall_main: { type: 'wall', preset: 'plain' },
      wood: { type: 'prop', preset: 'wood', colors: { c1: '#a87a4a', c2: '#6e4a2a' }, size: [16, 16] },
      fabric: { type: 'prop', preset: 'fabric', colors: { c1: '#c8506a', c2: '#a03050' }, size: [16, 16] },
      white: { type: 'prop', preset: 'solid', colors: { c1: '#f4f0ea' }, size: [16, 16] },
      dark: { type: 'prop', preset: 'solid', colors: { c1: '#2a2226' }, size: [16, 16] },
      gold: { type: 'prop', preset: 'gradient', colors: { c1: '#ffe68c', c2: '#c8963c' }, size: [16, 16] },
    }, palettes: {}, rooms: [{ id: 'main', name: 'Main room', rect: [3, 4, 12, 13], floor: 'floor_main', wall: 'wall_main' }], items: [],
  };
}

export function render(root, app) {
  const P = S.project;
  const st = { sel: P.buildings[0] ? P.buildings[0].id : null, tab: 'look', winter: false, night: false, defaults: null, presets: null };
  const left = h('div', { class: 'pane' }), mid = h('div', { class: 'pane', style: { display: 'flex', flexDirection: 'column', background: '#0f1215' } }), right = h('div', { class: 'pane' });
  mount(root, h('div', { class: 'page-head' }, h('h2', {}, 'Buildings'), h('p', {}, 'New places on the town map: their outside look, name, map icon and position. The inside is designed in Interiors.')),
    h('div', { class: 'split', style: { gridTemplateColumns: '230px minmax(380px,1fr) 400px' } }, left, mid, right));

  const bld = () => P.buildings.find((b) => b.id === st.sel);

  function drawLeft() {
    mount(left, h('div', { class: 'list' }, P.buildings.map((b) => h('div', { class: 'item' + (b.id === st.sel ? ' on' : ''), onclick: () => { st.sel = b.id; st.tab = 'look'; drawLeft(); drawRight(); preview.now(); } }, h('b', {}, b.name || b.id), h('span', { class: 'sub dim' }, '0x' + (b.slot ?? 0x4d).toString(16)))),
      P.buildings.length ? null : h('div', { class: 'empty' }, 'No building yet')),
      h('div', { style: { padding: '10px' } }, h('button', { class: 'primary', style: { width: '100%' }, onclick: create }, 'New building…')));
  }

  async function create() {
    if (!st.defaults) { const r = await get('/api/exterior/presets'); st.defaults = r.defaults; st.presets = r.presets; st.bases = r.bases; }
    const taken = new Set(P.buildings.map((b) => b.slot ?? 0x4d));
    const bases = Object.entries(st.bases);
    const baseFor = (slotKey) => bases.find(([k]) => k === slotKey);
    const nm = h('input', { type: 'text', value: 'My building' });
    const pr = select(Object.keys(st.presets).map((k) => [k, k.replace(/_/g, ' ')]), 'cozy_cottage', () => {});
    const baseSel = select(bases.map(([k, v]) => [k, v.label]), bases[0][0], () => {});
    const spare = []; for (let i = 0x6b; i <= 0x7e; i++) if (!taken.has(i)) spare.push(i);
    const mode = select([['new', 'Add it as a new building (the police stations stay)'], ['replace', 'Replace the police station of that type']], spare.length ? 'new' : 'replace', () => {});
    const ok = await modal('New building', h('div', { class: 'col' }, h('label', { class: 'field' }, h('span', {}, 'Name'), nm), h('label', { class: 'field' }, h('span', {}, 'Starting look'), pr),
      h('label', { class: 'field' }, h('span', {}, 'Built like'), baseSel), h('label', { class: 'field' }, h('span', {}, 'How'), mode),
      h('div', { class: 'dim', style: { fontSize: '12px' } }, 'Added buildings use a spare slot (one of the game\u2019s 20 signboard IDs) and copy the footprint and door of the base. They can have their own map icon (up to 17), but the name on the map list is the base’s. Replacing also gives your own map name, but removes that police station from your town.')), [{ label: 'Cancel', value: false }, { label: 'Create', value: true, primary: true }]);
    if (!ok) return;
    const base = baseFor(baseSel.value);
    let slot = base[1].slot;
    if (mode.value === 'new') { if (!spare.length) { toast('No spare slot left', 'error'); return; } slot = spare[0]; } else if (taken.has(slot)) { toast('That police station is already replaced by another building', 'error'); return; }
    const bid = uid('b', P.buildings).replace(/^b/, 'bld');
    const style = JSON.parse(JSON.stringify(st.presets[pr.value])); style.base = base[0]; style.sign = Object.assign({}, st.defaults.sign, style.sign, { text: nm.value.slice(0, 14) });
    P.buildings.push({ id: bid, name: nm.value, slot, model: 'sobj_' + bid.slice(0, 7), dx: 4 + 6 * P.buildings.length, dy: 7, interior: null, hide_furniture: true, style, map_name: { en: nm.value }, map_icon: { shape: 'house', fill: '#f6c86c', outline: '#6e4a1e' } });
    st.sel = bid; changed(); drawLeft(); drawRight(); preview.now();
  }

  // ---- the 3D view
  const canvas = h('canvas', { style: { width: '100%', flex: 1, minHeight: 0 } });
  let viewer = null;
  const camBtns = h('div', { class: 'toolbar' },
    ['Front', 'Side', 'Game', 'Top'].map((n) => h('button', { class: 'small', onclick: () => cam(n) }, n)), h('div', { class: 'grow' }),
    checkbox(st.winter, (v) => { st.winter = v; preview.now(); }, 'Winter'), checkbox(st.night, (v) => { st.night = v; if (viewer) { viewer.opts.night = v; viewer.dirty = true; } }, 'Night'));
  mount(mid, camBtns, canvas, h('div', { class: 'dim', style: { padding: '6px 12px', fontSize: '12px' } }, 'Drag to rotate · wheel to zoom · right-drag to pan. The game looks at a building from the front, a bit above.'));
  function cam(n) { if (!viewer) return; const v = { Front: [0, 0.18], Side: [1.57, 0.18], Game: [0.35, 0.62], Top: [0, 1.4] }[n]; viewer.yaw = v[0]; viewer.pitch = v[1]; viewer.dirty = true; }
  let cached = null, regions = null, atlasSize = null;
  const preview = debounce(async () => {
    const b = bld(); if (!b) { if (viewer) viewer.setParts([]); return; }
    try {
      const r = await post('/api/exterior/preview', { style: b.style, project: S.pid, winter: st.winter });
      regions = r.regions; atlasSize = r.atlas_size; cached = r;
      if (!viewer) { try { viewer = new Viewer(canvas, { light: [0.35, 0.8, 0.55] }); } catch (e) { viewer = null; } if (!viewer || !viewer.ok) { toast('WebGL is not available in this browser: no 3D preview', 'error'); return; } const first = true; viewer.opts.night = st.night; viewer._first = first; }
      const parts = [];
      for (const p of r.parts) parts.push({ ...p, image: await dataImage(p.atlas) });
      viewer.setParts(parts);
      if (viewer._first) { const [mn, mx] = boundsOf(parts); viewer.frame(mn, mx); viewer.target[1] += 8; viewer.dist *= 1.25; viewer.yaw = 0.35; viewer.pitch = 0.4; viewer._first = false; }
    } catch (e) { toast('Preview failed: ' + e.message, 'error'); }
  }, 140);
  const styleChanged = () => { changed(); preview(); };

  // ---- the form
  const set = (obj, path, v) => { const k = path.split('.'); let o = obj; for (const a of k.slice(0, -1)) { o[a] = o[a] || {}; o = o[a]; } o[k[k.length - 1]] = v; };
  const getp = (obj, path, d) => { let o = obj; for (const a of path.split('.')) { if (o == null) return d; o = o[a]; } return o ?? d; };

  async function drawRight() {
    const b = bld();
    if (!b) { mount(right, h('div', { class: 'empty' }, 'Create a building to start.')); return; }
    if (!st.defaults) { const r = await get('/api/exterior/presets'); st.defaults = r.defaults; st.presets = r.presets; st.bases = r.bases; }
    const D = st.defaults, s = b.style = b.style || {};
    const tab = (id, label) => h('button', { class: st.tab === id ? 'on' : '', onclick: () => { st.tab = id; drawRight(); } }, label);
    const body = h('div', { class: 'pad', style: { padding: '14px', display: 'flex', flexDirection: 'column', gap: '14px' } });
    mount(right, h('div', { class: 'tabs' }, tab('look', 'Look'), tab('colors', 'Colors'), tab('paint', 'Paint'), tab('place', 'Name & place'), tab('inside', 'Inside')), body);
    const val = (path) => getp(s, path, getp(D, path));
    const sel = (path, opts) => select(opts, val(path), (v) => { set(s, path, v); styleChanged(); });
    const num = (path, min, max, step) => slider(val(path), min, max, step, (v) => { set(s, path, v); styleChanged(); });
    const chk = (path, label) => checkbox(val(path), (v) => { set(s, path, v); styleChanged(); }, label);

    if (st.tab === 'look') {
      const presetSel = select([['', 'Choose a preset…'], ...Object.keys(st.presets).map((k) => [k, k.replace(/_/g, ' ')])], '', async (v) => {
        if (!v) return;
        if (!await confirmBox('Replace the look of ' + (b.name || b.id) + ' with the "' + v.replace(/_/g, ' ') + '" preset? (Sign text and your painted overlay are kept.)', 'Apply')) { presetSel.value = ''; return; }
        const keep = { base: s.base, overlay: s.overlay, sign: s.sign }; b.style = Object.assign(JSON.parse(JSON.stringify(st.presets[v])), keep); b.style.sign = Object.assign({}, getp(st.presets[v], 'sign', {}), s.sign);
        styleChanged(); drawRight();
      });
      mount(body, field('Preset', presetSel),
        h('div', { class: 'card' }, h('h3', {}, 'Shape'), h('div', { class: 'col' },
          field('Width', num('width', 26, 44, 1)), field('Depth', num('depth', 36, 70, 1), 'The building keeps the collision box of the slot it replaces: stay near the original size.'),
          field('Wall height', num('eave', 28, 60, 1)), s.roof && s.roof.style === 'flat' ? null : field('Roof peak', num('ridge', 36, 100, 1)))),
        h('div', { class: 'card' }, h('h3', {}, 'Roof & walls'), h('div', { class: 'grid2' },
          field('Roof', sel('roof.style', [['barrel', 'Barrel'], ['gable', 'Gable'], ['flat', 'Flat']])), field('Roof covering', sel('roof.pattern', [['panels', 'Panels'], ['tiles', 'Tiles'], ['shingles', 'Shingles'], ['plain', 'Plain']])),
          field('Walls', sel('wall_pattern', [['planks', 'Planks'], ['brick', 'Brick'], ['stucco', 'Stucco'], ['stripes', 'Stripes']])), field('Roof motif', sel('roof.motif', [['heart', 'Hearts'], ['star', 'Stars'], ['none', 'None']])))),
        h('div', { class: 'card' }, h('h3', {}, 'Front'), h('div', { class: 'col' },
          h('div', { class: 'grid2' }, field('Big ornament', sel('ornament', [['heart', 'Heart'], ['star', 'Star'], ['none', 'None']])), field('Windows', sel('windows', [['round', 'Round'], ['square', 'Square'], ['none', 'None']]))),
          field('Door', sel('door', [['beads', 'Bead curtain'], ['dark', 'Dark doorway'], ['wood', 'Wooden door']])),
          h('div', { class: 'row wrap', style: { gap: '14px' } }, chk('awning', 'Awning'), chk('bushes', 'Rose bushes'), chk('lanterns', 'Lanterns')),
          field('Sign text', textInput(val('sign.text'), (v) => { set(s, 'sign.text', v); styleChanged(); }, { maxlength: 18 })),
          h('div', { class: 'grid2' }, field('Lettering size', num('sign.size', 8, 22, 1))))));
    } else if (st.tab === 'colors') {
      mount(body, COLOR_GROUPS.map(([g, keys]) => h('div', { class: 'card' }, h('h3', {}, g), h('div', { class: 'grid2' }, keys.map((k) => h('label', { class: 'row', style: { justifyContent: 'space-between' } }, h('span', {}, COLOR_LABELS[k]), colorInput(getp(s, 'colors.' + k, D.colors[k]), (v) => { set(s, 'colors.' + k, v); styleChanged(); })))))),
        h('div', { class: 'dim', style: { fontSize: '12px' } }, 'Shading, highlights and the winter snow are derived from these.'));
    } else if (st.tab === 'paint') {
      drawPaint(body, b);
    } else if (st.tab === 'place') {
      mount(body,
        h('div', { class: 'card' }, h('h3', {}, 'Name'), h('div', { class: 'col' },
          field('Display name (default)', textInput(b.name || '', (v) => { b.name = v; b.map_name = Object.assign({}, b.map_name, { en: v }); changed(); drawLeft(); })),
          h('details', {}, h('summary', {}, 'Other languages (fall back to English)'), h('div', { class: 'col', style: { marginTop: '6px' } }, LANGS.filter((l) => l !== 'en').map((l) => field(l.toUpperCase(), textInput((b.map_name || {})[l] || '', (v) => { b.map_name = Object.assign({}, b.map_name); if (v) b.map_name[l] = v; else delete b.map_name[l]; changed(); }))))),
          h('div', { class: 'dim', style: { fontSize: '12px' } }, 'The name on the town map list. An added building (not replacing the police station) keeps the base building’s name there; its icon can still be your own.'))),
        h('div', { class: 'card' }, h('h3', {}, 'Map icon'), h('div', { class: 'grid3' },
          (b.map_icon || {}).shape === 'image' ? iconCard(b) : null,
          field('Shape', select([['heart', 'Heart'], ['star', 'Star'], ['house', 'House'], ['dot', 'Dot'], ['image', 'My own image…'], ['none', 'Keep original']], (b.map_icon || {}).shape || 'none', (v) => { b.map_icon = Object.assign({}, b.map_icon, { shape: v }); changed(); drawRight(); })),
          field('Fill', colorInput((b.map_icon || {}).fill || '#f6548c', (v) => { b.map_icon = Object.assign({}, b.map_icon, { fill: v }); changed(); })),
          field('Outline', colorInput((b.map_icon || {}).outline || '#78143c', (v) => { b.map_icon = Object.assign({}, b.map_icon, { outline: v }); changed(); })))),
        h('div', { class: 'card' }, h('h3', {}, 'Position in town'), h('div', { class: 'col' },
          placementMap(b),
          h('div', { class: 'grid2' }, field('Offset from the town hall — east', numInput(b.dx ?? 4, (v) => { b.dx = v; changed(); })), field('Offset — south', numInput(b.dy ?? 7, (v) => { b.dy = v; changed(); }))),
          h('details', {}, h('summary', {}, 'Absolute position'), h('div', { class: 'grid2', style: { marginTop: '6px' } },
            field('x (tile, blank = use the offset)', numInput(b.x ?? '', (v) => { b.x = v; changed(); })), field('y', numInput(b.y ?? '', (v) => { b.y = v; changed(); })))),
          h('div', { class: 'dim', style: { fontSize: '12px' } }, 'Tiles are 1/16 of an acre. Keep a free tile in front of the door. If you build several buildings, give each its own offset.'))),
        h('div', { class: 'card' }, h('h3', {}, 'Advanced'), h('div', { class: 'col' },
          field('Model name', textInput(b.model || '', (v) => { b.model = v; changed(); }, { maxlength: 12 }), 'sobj_xxxxxxx — must be new; the files are named after it.'),
          h('div', { class: 'dim', style: { fontSize: '12px' } }, 'Takes over town slot 0x' + (b.slot ?? 0x4d).toString(16).toUpperCase() + '.'))),
        h('button', { class: 'danger', onclick: async () => { if (await confirmBox('Delete ' + (b.name || b.id) + '?', 'Delete')) { P.buildings.splice(P.buildings.indexOf(b), 1); P.text = P.text.filter((t) => t.variant !== b.id); P.events = P.events.filter((e) => e.building !== b.id); st.sel = P.buildings[0] ? P.buildings[0].id : null; changed(); drawLeft(); drawRight(); preview.now(); } } }, 'Delete this building'));
    } else if (st.tab === 'inside') {
      const opts = [['', '— none: the original police station interior —'], ...P.interiors.map((i) => [i.id, i.title || i.id])];
      mount(body, h('div', { class: 'card' }, h('h3', {}, 'Interior'), h('div', { class: 'col' },
        field('Which interior is behind the door', select(opts, b.interior || '', (v) => { b.interior = v || null; b.hide_furniture = !!v; changed(); drawRight(); })),
        h('div', { class: 'row' }, h('button', { onclick: () => { const sc = newInterior(P, (b.name || 'New') + ' interior'); P.interiors.push(sc); b.interior = sc.id; b.hide_furniture = true; changed(); app.go('interiors'); } }, 'Create a new interior'),
          b.interior ? h('button', { onclick: () => { app.preset = { interior: b.interior }; app.go('interiors'); } }, 'Edit it →') : null),
        h('div', { class: 'dim', style: { fontSize: '12px' } }, 'The room is the inside of Nook’s Homes (16 × 16 tiles), so Tom Nook is the person behind the counter. His lines can be changed in Dialogue ("Only inside this building").'))),
        h('div', { class: 'card' }, h('h3', {}, 'Behaviour'), checkbox(!!b.hide_furniture, (v) => { b.hide_furniture = v; changed(); }, 'No exhibits: Tom Nook’s shop furniture is not created inside (your own furniture is part of the room)')));
    }
  }

  // ---- a map icon from any picture: 16 x 16 pixels in the game
  function iconCard(b) {
    const img = (b.map_icon || {}).image;
    const prev = h('canvas', { width: 16, height: 16, style: { width: '64px', height: '64px', imageRendering: 'pixelated', background: '#4b7f52', borderRadius: '6px' } });
    if (img) loadImage('/api/project/' + S.pid + '/asset/' + encodeURIComponent(img) + '?t=' + Date.now()).then((im) => prev.getContext('2d').drawImage(im, 0, 0, 16, 16)).catch(() => {});
    return h('div', { class: 'row', style: { gridColumn: '1 / -1', gap: '12px' } }, prev,
      h('div', { class: 'col', style: { gap: '4px' } }, h('button', { onclick: () => iconDialog(b) }, img ? 'Change the image…' : 'Choose an image…'),
        h('span', { class: 'dim', style: { fontSize: '12px' } }, 'The game draws it 16 × 16 pixels. Any PNG/JPG works: it is made square and shrunk for you.')));
  }
  async function iconDialog(b) {
    let src = null, shown = null;
    const out = h('canvas', { width: 16, height: 16, style: { width: '160px', height: '160px', imageRendering: 'pixelated', background: 'repeating-conic-gradient(#3a4a3c 0 25%, #4b7f52 0 50%) 0 0 / 20px 20px', borderRadius: '6px' } });
    const real = h('canvas', { width: 16, height: 16, style: { imageRendering: 'pixelated', background: '#4b7f52' } });
    const mode = select([['crop', 'Crop to a square (centre)'], ['fit', 'Fit inside a square (transparent padding)'], ['stretch', 'Stretch to a square']], 'fit', () => draw());
    const bgOff = h('input', { type: 'checkbox' }); const tol = h('input', { type: 'range', min: 5, max: 120, value: 40, style: { width: '120px' } });
    const draw = () => {
      const g = out.getContext('2d', { willReadFrequently: true }); g.clearRect(0, 0, 16, 16);
      if (!src) { shown = null; return; }
      const w = src.width, hh = src.height, s = Math.min(w, hh), big = Math.max(w, hh);
      const c = document.createElement('canvas'); c.width = c.height = 64; const cg = c.getContext('2d', { willReadFrequently: true }); cg.imageSmoothingQuality = 'high';
      if (mode.value === 'crop') cg.drawImage(src, (w - s) / 2, (hh - s) / 2, s, s, 0, 0, 64, 64);
      else if (mode.value === 'fit') { const k = 64 / big; cg.drawImage(src, 0, 0, w, hh, (64 - w * k) / 2, (64 - hh * k) / 2, w * k, hh * k); }
      else cg.drawImage(src, 0, 0, 64, 64);
      if (bgOff.checked) {                       // the colour of the corners becomes transparent
        const one = document.createElement('canvas'); one.width = one.height = 1; const og = one.getContext('2d'); og.drawImage(src, 0, 0, 1, 1, 0, 0, 1, 1);
        const d = cg.getImageData(0, 0, 64, 64), px = d.data, ref = og.getImageData(0, 0, 1, 1).data;
        if (ref[3] > 0) for (let i = 0; i < px.length; i += 4) { const dist = Math.hypot(px[i] - ref[0], px[i + 1] - ref[1], px[i + 2] - ref[2]); if (px[i + 3] > 0 && dist < +tol.value) px[i + 3] = 0; }
        cg.putImageData(d, 0, 0);
      }
      g.imageSmoothingQuality = 'high'; g.drawImage(c, 0, 0, 32, 32); const c2 = document.createElement('canvas'); c2.width = c2.height = 32; c2.getContext('2d').drawImage(c, 0, 0, 32, 32);
      g.clearRect(0, 0, 16, 16); g.drawImage(c2, 0, 0, 16, 16);
      shown = true; const rg = real.getContext('2d'); rg.clearRect(0, 0, 16, 16); rg.drawImage(out, 0, 0);
    };
    bgOff.addEventListener('change', draw); tol.addEventListener('input', draw);
    const pick = async () => { const f = await pickFile('image/*'); if (!f) return; try { src = await loadImage(URL.createObjectURL(f)); draw(); } catch (e) { toast('Cannot read that image', 'error'); } };
    const body = h('div', { class: 'col' },
      h('div', { class: 'row' }, h('button', { onclick: pick }, 'Choose a picture…'), h('span', { class: 'dim' }, 'PNG, JPG, GIF, WebP…')),
      field('Make it square', mode),
      h('label', { class: 'row', style: { gap: '8px' } }, bgOff, 'Remove the background (the colour of the corner)', tol),
      h('div', { class: 'row', style: { gap: '16px' } }, out, h('div', { class: 'col' }, h('span', { class: 'dim' }, 'Actual size on the map:'), real)));
    const ok = await modal('Map icon', body, [{ label: 'Cancel', value: false }, { label: 'Use this icon', value: true, primary: true }]);
    if (!ok) return;
    if (!shown) { toast('Choose a picture first', 'error'); return; }
    const blob = await new Promise((res) => out.toBlob(res, 'image/png'));
    const name = b.id + '_icon.png';
    await put('/api/project/' + S.pid + '/asset/' + name, blob);
    b.map_icon = Object.assign({}, b.map_icon, { shape: 'image', image: name }); changed(); drawRight();
  }

  // ---- where in town: a plan around the town hall (positions are relative to it)
  const RECTS = { hall: [-3, -2, 3, 2], 0x4c: [-2, -3, 2, 2], 0x4d: [-2, -3, 2, 2] };
  function placementMap(b) {
    const W = 41, H = 27, Z = 12, cx = 20, cy = 9;              // tiles shown, px per tile, the hall's tile
    const cv = h('canvas', { width: W * Z, height: H * Z, style: { width: '100%', maxWidth: W * Z + 'px', cursor: 'crosshair', borderRadius: '6px', border: '1px solid var(--line)' } });
    const g = cv.getContext('2d');
    const rectOf = (bb) => { const r = RECTS[bb.slot ?? 0x4d] || [-2, -3, 2, 2]; const ox = bb.x != null && bb.x !== '' ? null : bb.dx ?? 4, oy = bb.dy ?? 7; return ox == null ? null : [cx + ox + r[0], cy + oy + r[1], cx + ox + r[2], cy + oy + r[3]]; };
    const draw = () => {
      g.fillStyle = '#26402c'; g.fillRect(0, 0, cv.width, cv.height);
      g.strokeStyle = 'rgba(255,255,255,.06)'; g.beginPath(); for (let x = 0; x <= W; x++) { g.moveTo(x * Z + .5, 0); g.lineTo(x * Z + .5, cv.height); } for (let y = 0; y <= H; y++) { g.moveTo(0, y * Z + .5); g.lineTo(cv.width, y * Z + .5); } g.stroke();
      const box = (r, fill, label, strong) => { g.fillStyle = fill; g.fillRect(r[0] * Z, r[1] * Z, (r[2] - r[0] + 1) * Z, (r[3] - r[1] + 1) * Z); g.strokeStyle = strong ? '#ffe650' : 'rgba(255,255,255,.5)'; g.lineWidth = strong ? 2 : 1; g.strokeRect(r[0] * Z + .5, r[1] * Z + .5, (r[2] - r[0] + 1) * Z - 1, (r[3] - r[1] + 1) * Z - 1); g.fillStyle = '#fff'; g.font = '10px system-ui'; g.fillText(label, r[0] * Z + 3, r[1] * Z + 11); };
      const hall = [cx + RECTS.hall[0], cy + RECTS.hall[1], cx + RECTS.hall[2], cy + RECTS.hall[3]];
      box(hall, '#5d6b78', 'Town hall');
      g.fillStyle = '#9ec1ff'; g.fillRect((cx - 0.5) * Z, (cy + RECTS.hall[3] + 1) * Z, Z, Z / 2);
      const rs = P.buildings.map((bb) => [bb, rectOf(bb)]);
      for (const [bb, r] of rs) { if (!r) continue; const clash = rs.some(([o, q2]) => o !== bb && q2 && !(r[2] < q2[0] || r[0] > q2[2] || r[3] < q2[1] || r[1] > q2[3])) || !(r[2] < hall[0] || r[0] > hall[2] || r[3] < hall[1] || r[1] > hall[3]); box(r, clash ? 'rgba(230,106,95,.6)' : bb === b ? 'rgba(107,191,122,.75)' : 'rgba(200,170,90,.65)', bb.name || bb.id, bb === b); g.fillStyle = '#fff'; g.fillRect(((r[0] + r[2]) / 2 + .5) * Z - 3, (r[3] + 1) * Z - 4, 6, 4); }
    };
    cv.addEventListener('pointerdown', (e) => {
      const rc = cv.getBoundingClientRect(), tx = Math.floor((e.clientX - rc.left) / rc.width * W), ty = Math.floor((e.clientY - rc.top) / rc.height * H);
      b.dx = tx - cx; b.dy = ty - cy; delete b.x; delete b.y; changed(); draw(); drawRight();
    });
    draw();
    return h('div', { class: 'col', style: { gap: '4px' } }, cv, h('div', { class: 'dim', style: { fontSize: '12px' } }, 'Click to place the building (its door, the white mark, faces south). Red: overlapping. The town hall is the centre of reference.'));
  }

  // ---- painting over the generated texture
  let editor = null;
  async function drawPaint(body, b) {
    if (editor) { editor.destroy(); editor = null; }
    const s = b.style;
    mount(body, h('div', { class: 'info-box' }, 'Paint on top of the generated texture: the yellow frames are the parts of the model (walls, roof, sign, awning…). What you draw here is layered over the procedural look. Transparent = untouched.'), h('div', { class: 'dim' }, 'Loading…'));
    if (!cached) await preview.now();
    const [aw, ah] = atlasSize || [256, 128];
    let saveTimer = null;
    editor = new PixelEditor({ onchange: () => { clearTimeout(saveTimer); saveTimer = setTimeout(save, 700); } });
    editor.regions = regions;
    if (s.overlay) { try { editor.load(await loadImage(`/api/project/${S.pid}/asset/${encodeURIComponent(s.overlay)}?t=${Date.now()}`)); } catch (e) { editor.blank(aw, ah); } } else editor.blank(aw, ah);
    const base = h('img', { src: 'data:image/png;base64,' + (cached.parts[0].atlas), style: { position: 'absolute', left: 0, top: 0, imageRendering: 'pixelated', pointerEvents: 'none' } });
    editor.wrap.style.position = 'relative'; editor.canvas.style.position = 'relative'; editor.canvas.style.zIndex = 1; editor.wrap.prepend(base);
    const sz = editor.setZoom.bind(editor);
    editor.setZoom = (z) => { sz(z); base.style.width = editor.w * editor.zoom + 'px'; base.style.height = editor.h * editor.zoom + 'px'; };
    editor.setZoom(editor.zoom);
    editor.wrap.style.height = '520px'; editor.wrap.style.flex = 'none';
    async function save() {
      const name = b.id + '_overlay.png';
      await put(`/api/project/${S.pid}/asset/${name}`, await editor.toBlob());
      b.style.overlay = name; changed(); preview();
    }
    const clearBtn = h('button', { class: 'small danger', onclick: async () => { if (!await confirmBox('Erase everything you painted on this building?', 'Erase')) return; editor.snapshot(); editor.blank(aw, ah); await save(); } }, 'Erase overlay');
    mount(body, h('div', { class: 'info-box' }, 'Paint over the generated texture. Yellow frames mark the model’s parts; transparent pixels leave the generated look untouched.'), editor.el, h('div', { class: 'row' }, clearBtn));
    setTimeout(() => editor.fit(), 30);
  }

  drawLeft(); drawRight(); preview.now();
  return () => { if (editor) editor.destroy(); };
}
