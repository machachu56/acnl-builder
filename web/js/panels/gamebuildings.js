import { get } from '../api.js';
import { S, changed } from '../state.js';
import { h, mount, toast, select, field, textInput, numInput, checkbox, confirmBox } from '../ui.js';
import { Viewer, dataImage, boundsOf } from '../viewer.js';

// The game's own buildings (Buildings > "The town's buildings"): move, remove, rename, another interior; the look is
// repainted in Textures. project.game_buildings: [{slot, move: [x, y] | null, remove, interior, map_name: {lang: text}}]
const LANGS = ['en', 'es', 'fr', 'it', 'de'];
const hex = (n) => '0x' + n.toString(16);

export function render(root, app, head) {
  const P = S.project;
  P.game_buildings = P.game_buildings || [];
  const st = { sel: null, data: null };
  const left = h('div', { class: 'pane' }), mid = h('div', { class: 'pane', style: { display: 'flex', flexDirection: 'column', background: '#0f1215' } }), right = h('div', { class: 'pane' });
  mount(root, head, h('div', { class: 'split', style: { gridTemplateColumns: '260px minmax(380px,1fr) 400px' } }, left, mid, right));

  const kindOf = (slot) => st.data.kinds.find((k) => k.slot === slot);
  const inTown = (slot) => (st.data.town || []).find((b) => b.slot === slot);
  const edit = (slot) => P.game_buildings.find((g) => g.slot === slot);
  const editOrNew = (slot) => edit(slot) || (P.game_buildings.push({ slot, move: null, remove: false, interior: null, map_name: {} }), edit(slot));
  const isEdited = (slot) => { const g = edit(slot); return g && (g.remove || g.move || g.interior || Object.values(g.map_name || {}).some((v) => v)); };
  const tidy = () => { P.game_buildings = P.game_buildings.filter((g) => isEdited(g.slot)); };

  function drawLeft() {
    const item = (k, sub) => h('div', { class: 'item' + (k.slot === st.sel ? ' on' : ''), onclick: () => { st.sel = k.slot; drawLeft(); drawRight(); preview(); } },
      h('b', {}, k.label), h('span', { class: 'sub dim' }, sub), isEdited(k.slot) ? h('span', { class: 'chip ok sub' }, 'changed') : null);
    const town = (st.data.town || []).map((b) => ({ b, k: kindOf(b.slot) })).filter((x) => x.k);
    const groups = {};
    for (const k of st.data.kinds) (groups[k.group] = groups[k.group] || []).push(k);
    mount(left, h('div', { class: 'list' },
      h('div', { class: 'dim', style: { padding: '8px 12px 4px', fontSize: '11px', textTransform: 'uppercase' } }, 'In your town'),
      st.data.town ? (town.length ? town.map(({ b, k }) => item(k, 'tile ' + b.x + ', ' + b.y)) : h('div', { class: 'empty' }, 'Nothing a mod can change yet')) :
        h('div', { class: 'dim', style: { padding: '4px 12px', fontSize: '12px' } }, 'No save found (', h('span', { class: 'kbd' }, st.data.save), '): every type is listed below.'),
      Object.entries(groups).map(([g, ks]) => [h('div', { class: 'dim', style: { padding: '12px 12px 4px', fontSize: '11px', textTransform: 'uppercase' } }, g),
        ks.map((k) => item(k, inTown(k.slot) ? 'in your town' : hex(k.slot)))])));
  }

  // ---- 3D preview of the game's model
  const canvas = h('canvas', { style: { width: '100%', flex: 1, minHeight: 0 } });
  const cap = h('span', { class: 'dim' });
  let viewer = null, seq = 0;
  mount(mid, h('div', { class: 'toolbar' }, cap), canvas, h('div', { class: 'dim', style: { padding: '6px 12px', fontSize: '12px' } }, 'The game’s own model. Drag to rotate · wheel to zoom.'));
  async function preview() {
    const k = st.sel != null ? kindOf(st.sel) : null;
    if (!k) return;
    const my = ++seq;
    cap.textContent = k.model || '';
    try {
      const m = await get('/api/game-buildings/mesh?slot=' + k.slot);
      if (my !== seq) return;
      if (!viewer) { try { viewer = new Viewer(canvas, { light: [0.3, 0.8, 0.6] }); } catch (e) { viewer = null; } if (!viewer || !viewer.ok) { viewer = null; return; } }
      const imgs = {};
      for (const [n, b64] of Object.entries(m.textures)) imgs[n] = await dataImage(b64);
      const parts = m.parts.filter((p) => p.positions.length).map((p) => ({ ...p, image: p.texture ? imgs[p.texture] : blank(), flat: !p.texture }));
      viewer.setParts(parts);
      const [mn, mx] = boundsOf(parts); viewer.frame(mn, mx); viewer.yaw = 0.5; viewer.pitch = 0.45; viewer.dist *= 1.2; viewer.dirty = true;
      st.modelPath = m.model; st.texture = parts.find((p) => p.texture) ? parts.find((p) => p.texture).texture : null;
    } catch (e) { if (viewer) viewer.setParts([]); cap.textContent = (k.model || '') + ' (no preview)'; }
  }
  function blank() { const c = document.createElement('canvas'); c.width = c.height = 1; const g = c.getContext('2d'); g.fillStyle = '#ccc'; g.fillRect(0, 0, 1, 1); return c; }

  // ---- the form
  function drawRight() {
    const k = st.sel != null ? kindOf(st.sel) : null;
    if (!k) { mount(right, h('div', { class: 'empty' }, 'Pick a building on the left.')); return; }
    const g = edit(k.slot) || { slot: k.slot, move: null, remove: false, interior: null, map_name: {} };
    const here = inTown(k.slot);
    const save = () => { tidy(); changed(); drawLeft(); };
    const cards = [];
    cards.push(h('div', { class: 'card' }, h('h3', {}, k.label),
      h('div', { class: 'col' },
        h('div', { class: 'dim', style: { fontSize: '12px' } }, here ? 'In your town at tile ' + here.x + ', ' + here.y + '.' : st.data.town ? 'Not in your town (changes apply if it is built later).' : ''),
        h('div', { class: 'row' }, h('button', { onclick: repaint }, 'Repaint it in Textures…'), h('span', { class: 'dim', style: { fontSize: '11px' } }, 'its outside textures (this season)')))));

    if (k.move || k.remove) {
      const mode = g.remove ? 'remove' : g.move ? 'move' : 'keep';
      const opts = [['keep', 'Where it is'], ...(k.move ? [['move', 'Move it to a tile']] : []), ...(k.remove ? [['remove', 'Take it out of the town']] : [])];
      const body = h('div', { class: 'col' }, field('Place', select(opts, mode, (v) => {
        const e = editOrNew(k.slot);
        e.remove = v === 'remove'; e.move = v === 'move' ? (e.move || (here ? [here.x, here.y] : [56, 48])) : null;
        save(); drawRight();
      })));
      if (g.move) {
        body.append(h('div', { class: 'grid2' },
          field('Tile x', numInput(g.move[0], (v) => { editOrNew(k.slot).move[0] = Math.round(v); save(); }, { min: 16, max: 95, step: 1 })),
          field('Tile y', numInput(g.move[1], (v) => { editOrNew(k.slot).move[1] = Math.round(v); save(); }, { min: 16, max: 79, step: 1 }))),
        h('div', { class: 'dim', style: { fontSize: '11px' } }, 'x grows to the east, y to the south; the playable town is 16..95 × 16..79. Pick flat, dry ground: if another building is in the way, it stays where it is.'));
      }
      if (g.move || g.remove) body.append(h('div', { class: 'err-box', style: { fontSize: '12px' } }, 'This changes your town’s save the next time you play with the mod. Removing the mod does not put it back: keep a copy of your save.'));
      cards.push(h('div', { class: 'card' }, h('h3', {}, 'Place'), body));
    }

    if (k.interior) {
      const ints = P.interiors || [];
      cards.push(h('div', { class: 'card' }, h('h3', {}, 'Inside'), h('div', { class: 'col' },
        field('Interior', select([['', 'The game’s own'], ...ints.map((i) => [i.id, i.title || i.id])], g.interior || '', (v) => { editOrNew(k.slot).interior = v || null; save(); })),
        h('div', { class: 'dim', style: { fontSize: '11px' } }, ints.length ? 'A room designed in Interiors replaces the inside (and whoever works there).' : 'Design a room in Interiors first.'),
        k.slot >= 0x50 && k.slot <= 0x53 && g.interior ? h('div', { class: 'err-box', style: { fontSize: '12px' } }, 'Isabelle and the town hall’s services (saving, ordinances, projects) are inside the town hall: with another interior they cannot be reached.') : null)));
    }

    if (k.map_label != null) {
      const names = g.map_name || {};
      cards.push(h('div', { class: 'card' }, h('h3', {}, 'Name on the map'), h('div', { class: 'col' },
        LANGS.map((l) => field(l.toUpperCase(), textInput(names[l] || '', (v) => { const e = editOrNew(k.slot); e.map_name = e.map_name || {}; e.map_name[l] = v; save(); }, { placeholder: l === 'en' ? 'the game’s name' : 'same as English' }))),
        h('div', { class: 'dim', style: { fontSize: '11px' } }, 'Shared by every building of this type' + (k.slot === 0x4c || k.slot === 0x4d ? ' (both police stations).' : '.')))));
    }
    if (isEdited(k.slot)) cards.push(h('div', { class: 'row' }, h('div', { class: 'grow' }), h('button', { class: 'ghost danger', onclick: async () => {
      if (!await confirmBox('Undo every change to ' + k.label + '?', 'Undo')) return;
      P.game_buildings = P.game_buildings.filter((x) => x.slot !== k.slot); changed(); drawLeft(); drawRight();
    } }, 'Undo changes')));
    mount(right, h('div', { class: 'pad', style: { padding: '14px', display: 'flex', flexDirection: 'column', gap: '14px' } }, cards));
  }

  async function repaint() {
    const k = kindOf(st.sel);
    if (!st.modelPath) { toast('No model to repaint for ' + k.label, 'error'); return; }
    const folder = st.modelPath.slice(0, st.modelPath.lastIndexOf('/') + 1);
    const seasons = await get('/api/game/models?prefix=' + encodeURIComponent(folder + 'Textures/'));
    const file = seasons.find((p) => p.endsWith('/season00.bcres')) || st.modelPath;
    app.preset = { model: file, tex: st.texture };
    app.go('textures');
  }

  get('/api/game-buildings').then((d) => {
    st.data = d;
    const first = (d.town || []).find((b) => d.kinds.some((k) => k.slot === b.slot));
    st.sel = first ? first.slot : d.kinds[0].slot;
    drawLeft(); drawRight(); preview();
  }).catch((e) => { toast(e.message, 'error'); mount(left, h('div', { class: 'err-box' }, e.message)); });
}
