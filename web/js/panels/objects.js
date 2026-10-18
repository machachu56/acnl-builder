import { get, post } from '../api.js';
import { S, changed, uid } from '../state.js';
import { h, mount, toast, select, debounce, field, textInput, numInput, checkbox, slider, modal, confirmBox } from '../ui.js';
import { Viewer, dataImage, boundsOf } from '../viewer.js';

export const id = 'objects', title = 'Objects', icon = '⛟', needsProject = true;

const MAX_VEHICLES = 4;
// handling presets: top speed (units/s, 32 = a tile), acceleration, steering (rad/s at speed), grip (how fast sliding stops)
const HANDLING = {
  relaxed: { label: 'Relaxed', max_speed: 220, accel: 160, turn: 2.0, grip: 12 },
  balanced: { label: 'Balanced', max_speed: 330, accel: 240, turn: 2.4, grip: 10 },
  sporty: { label: 'Sporty', max_speed: 430, accel: 330, turn: 2.8, grip: 9 },
  drifty: { label: 'Drifty', max_speed: 380, accel: 290, turn: 3.1, grip: 4 },
};
const CONTROLS = [['A', 'X key', 'get in · accelerate'], ['B', 'Z key', 'brake · drift in a turn · get out (stopped)'], ['Circle pad', 'arrows', 'steer towards · pull back to reverse'],
  ['Y', 'A key', 'horn · hold next to a parked car: back into the pockets'], ['X', 'S key', 'lights (on by themselves at night)']];

export function newVehicle(P, name, car = 'sports_car') {
  return { id: uid('car', P.objects), name: name || 'My car', kind: 'vehicle', enabled: true, model: { car, color: 0 },
    start: { near: 'house', dx: 3, dz: 1 }, yaw: 0, scale: 1.0, sound: 'sporty', handling: { ...strip(HANDLING.balanced) },
    appear: 'item', give: { pockets: false, mail: true } };
}
function strip(hd) { const { label, ...rest } = hd; return rest; }

export function render(root) {
  const P = S.project;
  P.objects = P.objects || [];
  const st = { sel: P.objects[0] ? P.objects[0].id : null, kinds: null };
  const left = h('div', { class: 'pane' }), mid = h('div', { class: 'pane', style: { display: 'flex', flexDirection: 'column', background: '#0f1215' } }), right = h('div', { class: 'pane' });
  mount(root, h('div', { class: 'page-head' }, h('h2', {}, 'Objects'), h('p', {}, 'Things that stand outside in the town and that you can use. Vehicles are drivable cars made from the game’s own models.')),
    h('div', { class: 'split', style: { gridTemplateColumns: '230px minmax(380px,1fr) 400px' } }, left, mid, right));

  const obj = () => P.objects.find((o) => o.id === st.sel);
  const kinds = async () => st.kinds || (st.kinds = await get('/api/objects/kinds'));
  const carInfo = (key) => (st.kinds ? st.kinds.cars.find((c) => c.key === key) : null);

  function drawLeft() {
    mount(left, h('div', { class: 'list' }, P.objects.map((o) => h('div', { class: 'item' + (o.id === st.sel ? ' on' : ''), onclick: () => { st.sel = o.id; drawLeft(); drawRight(); preview.now(); } },
      h('b', {}, o.name || o.id), h('span', { class: 'sub dim' }, (carInfo(o.model && o.model.car) || {}).label || 'vehicle', o.enabled === false ? ' · off' : ''))),
    P.objects.length ? null : h('div', { class: 'empty' }, 'No object yet')),
    h('div', { style: { padding: '10px' } }, h('button', { class: 'primary', style: { width: '100%' }, onclick: create, disabled: P.objects.length >= MAX_VEHICLES }, 'New vehicle…'),
      P.objects.length >= MAX_VEHICLES ? h('div', { class: 'dim', style: { fontSize: '11px', marginTop: '6px' } }, 'A mod can have ' + MAX_VEHICLES + ' vehicles at most.') : null));
  }

  async function create() {
    const k = await kinds();
    const nm = h('input', { type: 'text', value: P.objects.length ? 'Car ' + (P.objects.length + 1) : 'My car' });
    const model = select(k.cars.map((c) => [c.key, c.label]), 'sports_car', () => {});
    const ok = await modal('New vehicle', h('div', { class: 'col' }, field('Name', nm), field('Model', model),
      h('div', { class: 'dim', style: { fontSize: '12px' } }, 'It is parked next to your house the first time you go out; it then stays where you leave it.')),
    [{ label: 'Cancel', value: false }, { label: 'Create', value: true, primary: true }]);
    if (!ok) return;
    const o = newVehicle(P, nm.value.trim() || 'My car', model.value);
    P.objects.push(o); st.sel = o.id; changed();
    drawLeft(); drawRight(); preview.now();
  }

  // ---- 3D preview
  const canvas = h('canvas', { style: { width: '100%', flex: 1, minHeight: 0 } });
  const info = h('span', { class: 'dim' });
  let viewer = null;
  const camBtns = h('div', { class: 'toolbar' }, ['Front', 'Side', 'Back', 'Game', 'Top'].map((n) => h('button', { class: 'small', onclick: () => cam(n) }, n)), h('div', { class: 'grow' }), info);
  mount(mid, camBtns, canvas, h('div', { class: 'dim', style: { padding: '6px 12px', fontSize: '12px' } }, 'Drag to rotate · wheel to zoom · right-drag to pan. One tile of the town is 32 units.'));
  // the model's front is at -x (front = -1): the "Front" camera looks from there
  function cam(n) { if (!viewer) return; const v = { Front: [-1.57, 0.15], Side: [0, 0.15], Back: [1.57, 0.15], Game: [-0.6, 0.62], Top: [0, 1.4] }[n]; viewer.yaw = v[0]; viewer.pitch = v[1]; viewer.dirty = true; }
  const preview = debounce(async () => {
    const o = obj(); if (!o) { if (viewer) viewer.setParts([]); info.textContent = ''; return; }
    try {
      const r = await post('/api/objects/preview', { model: { ...o.model, scale: o.scale || 1 }, project: S.pid });
      if (!viewer) {
        try { viewer = new Viewer(canvas, { light: [-0.4, 0.8, 0.5], flipV: true }); } catch (e) { viewer = null; }
        if (!viewer || !viewer.ok) { toast('WebGL is not available in this browser: no 3D preview', 'error'); viewer = null; return; }
        viewer._first = true;
      }
      const parts = [];
      for (const p of r.parts) parts.push({ ...p, image: await dataImage(p.atlas) });
      viewer.setParts(parts);
      if (viewer._first) { const [mn, mx] = boundsOf(parts); viewer.frame(mn, mx); viewer.dist *= 1.7; viewer.yaw = -0.6; viewer.pitch = 0.42; viewer._first = false; }
      const [L, H, W] = r.size;
      info.textContent = (L / 32).toFixed(1) + ' × ' + (W / 32).toFixed(1) + ' tiles · ' + r.triangles + ' triangles';
    } catch (e) { toast('Preview failed: ' + e.message, 'error'); }
  }, 120);

  // ---- the form
  async function drawRight() {
    const o = obj();
    if (!o) { mount(right, h('div', { class: 'empty' }, 'Create a vehicle to start.')); return; }
    const k = await kinds();
    o.model = o.model || { car: 'sports_car', color: 0 };
    o.start = o.start || { near: 'house', dx: 3, dz: 0 };
    o.handling = o.handling || strip(HANDLING.balanced);
    const ch = () => { changed(); drawLeft(); };
    const car = carInfo(o.model.car) || k.cars[0];
    const hd = o.handling;
    const preset = Object.entries(HANDLING).find(([, v]) => v.max_speed === hd.max_speed && v.accel === hd.accel && v.turn === hd.turn && v.grip === hd.grip);
    const tiles = (v) => (v / 32).toFixed(1) + ' tiles/s';
    const hslider = (key, label, min, max, step, hint, fmt) => {
      const out = h('span', { class: 'dim', style: { fontSize: '11px' } }, fmt ? fmt(hd[key]) : '');
      return field(label, h('div', { class: 'col', style: { gap: '2px' } }, slider(hd[key], min, max, step, (v) => { hd[key] = v; if (fmt) out.textContent = fmt(v); changed(); presetSel.value = ''; }), fmt ? out : null), hint);
    };
    const presetSel = select([['', 'Custom'], ...Object.entries(HANDLING).map(([key, v]) => [key, v.label])], preset ? preset[0] : '', (v) => {
      if (!v) return; o.handling = strip(HANDLING[v]); changed(); drawRight();
    });
    o.appear = o.appear || 'item';
    o.give = o.give || { pockets: false, mail: true };
    const itemCar = o.appear === 'item' && car.item;
    const lt = Object.assign({}, k.letter, o.letter || {});
    const setLetter = (key, v) => { o.letter = Object.assign({}, o.letter || {}, { [key]: v }); changed(); };
    const body = h('textarea', { rows: 6, style: { fontFamily: 'ui-monospace, monospace', fontSize: '12px' } }, lt.body);
    body.addEventListener('input', () => setLetter('body', body.value));
    const startHint = o.start.near === 'tiles' ? 'Tile x, z from the top-left corner of the map (a town is 112 × 96 tiles; the playable part starts at 16, 16).' : 'Tiles east (x) and south (z) of it; the car moves to the nearest free flat spot.';
    mount(right, h('div', { class: 'pad', style: { padding: '14px', display: 'flex', flexDirection: 'column', gap: '14px' } },
      h('div', { class: 'card' }, h('h3', {}, 'Vehicle'), h('div', { class: 'col' },
        field('Name', textInput(o.name, (v) => { o.name = v; ch(); })),
        h('div', { class: 'row' }, h('span', { class: 'dim' }, 'Id'), h('span', { class: 'kbd' }, o.id), h('div', { class: 'grow' }), checkbox(o.enabled !== false, (v) => { o.enabled = v; ch(); }, 'In the mod')),
        field('Model', select(k.cars.map((c) => [c.key, c.label]), o.model.car, (v) => { o.model = { car: v, color: 0 }; ch(); drawRight(); preview(); })),
        car.colors.length > 1 ? field('Colour', h('div', { class: 'row', style: { flexWrap: 'wrap', gap: '6px' } }, car.colors.map((name, i) =>
          h('button', { class: 'small' + ((o.model.color || 0) === i ? ' primary' : ''), onclick: () => { o.model.color = i; ch(); drawRight(); preview(); } }, name)))) : null,
        field('Size', slider(o.scale || 1, 0.7, 1.6, 0.05, (v) => { o.scale = v; changed(); preview(); }), 'Bigger cars are harder to park between trees.'),
        field('Engine sound', select(k.sounds, o.sound || 'sporty', (v) => { o.sound = v; changed(); })))),
      h('div', { class: 'card' }, h('h3', {}, 'How it appears'), h('div', { class: 'col' },
        field('In town', select([['item', car.item ? 'From its item: drop the ' + car.label.split(' (')[0].toLowerCase() + ' outside' : 'From its item (this model has none)'], ['parked', 'Parked in town from the start']], o.appear, (v) => { o.appear = v; ch(); drawRight(); })),
        itemCar ? h('div', { class: 'dim', style: { fontSize: '11px' } }, 'The game\u2019s own furniture item (', h('span', { class: 'kbd' }, '0x' + car.item.toString(16)), '): dropped on the ground outside, it becomes the car. Hold Y next to the parked car to put it back into the pockets.') : null,
        itemCar ? field('The first time', h('div', { class: 'col', style: { gap: '4px' } },
          checkbox(o.give.pockets, (v) => { o.give.pockets = v; changed(); drawRight(); }, 'Put the item in the pockets'),
          checkbox(o.give.mail, (v) => { o.give.mail = v; changed(); drawRight(); }, o.give.pockets ? 'Send a letter explaining it' : 'Send it by letter')),
          'Once per town. It can also be bought or found like any furniture.') : null,
        itemCar && o.give.mail ? h('div', { class: 'col' },
          field('Letter header', textInput(lt.header, (v) => setLetter('header', v), { maxlength: 32 }), 'Your name goes where \u201c ,\u201d is: \u201cTo ,\u201d reads \u201cTo Claude,\u201d'),
          field('Letter', body, 'About 27 characters a line, 6 lines show at once' + (o.give.pockets ? '' : '. The item comes attached.')),
          field('Signed', textInput(lt.footer, (v) => setLetter('footer', v), { maxlength: 32 }))) : null)),
      itemCar ? null : h('div', { class: 'card' }, h('h3', {}, 'Where it starts'), h('div', { class: 'col' },
        field('Parked', select(k.starts, o.start.near, (v) => { o.start.near = v; if (v === 'tiles') { o.start.dx = 56; o.start.dz = 48; } else { o.start.dx = 3; o.start.dz = 1; } changed(); drawRight(); })),
        h('div', { class: 'grid2' },
          field(o.start.near === 'tiles' ? 'Tile x' : 'East (tiles)', numInput(o.start.dx, (v) => { o.start.dx = v; changed(); }, { step: 1 })),
          field(o.start.near === 'tiles' ? 'Tile z' : 'South (tiles)', numInput(o.start.dz, (v) => { o.start.dz = v; changed(); }, { step: 1 }))),
        h('div', { class: 'dim', style: { fontSize: '11px' } }, startHint),
        field('Facing', select([[0, 'East'], [90, 'South'], [180, 'West'], [270, 'North']], o.yaw || 0, (v) => { o.yaw = Number(v); changed(); })),
        h('div', { class: 'dim', style: { fontSize: '11px' } }, 'After that it stays where you leave it. Changing where it starts moves it back here at the next launch.'))),
      h('div', { class: 'card' }, h('h3', {}, 'Handling'), h('div', { class: 'col' },
        field('Preset', presetSel),
        hslider('max_speed', 'Top speed', 120, 560, 10, null, tiles),
        hslider('accel', 'Acceleration', 80, 520, 10, null, (v) => (hd.max_speed / v).toFixed(1) + ' s to full speed'),
        hslider('turn', 'Steering', 1.0, 4.0, 0.1, 'How fast it turns at speed.'),
        hslider('grip', 'Grip', 2, 16, 0.5, 'Low grip slides out of turns (drifts); B in a fast turn always drifts.'))),
      h('div', { class: 'card' }, h('h3', {}, 'Controls in game'), h('table', { class: 'controls', style: { width: '100%', fontSize: '12px', borderCollapse: 'collapse' } },
        CONTROLS.map(([b, key, what]) => h('tr', {}, h('td', { style: { padding: '3px 6px 3px 0' } }, h('span', { class: 'kbd' }, b)), h('td', { class: 'dim', style: { padding: '3px 6px' } }, key), h('td', { style: { padding: '3px 0' } }, what))))),
      h('div', { class: 'row' }, h('div', { class: 'grow' }), h('button', { class: 'ghost danger', onclick: async () => {
        if (!await confirmBox('Remove ' + (o.name || o.id) + ' from the mod?', 'Remove')) return;
        P.objects.splice(P.objects.indexOf(o), 1); st.sel = P.objects[0] ? P.objects[0].id : null; changed(); drawLeft(); drawRight(); preview.now();
      } }, 'Remove vehicle'))));
  }

  kinds().then(() => { drawLeft(); drawRight(); preview.now(); }).catch((e) => toast(e.message, 'error'));
  drawLeft();
}
