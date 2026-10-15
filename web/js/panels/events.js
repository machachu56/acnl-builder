import { get } from '../api.js';
import { S, changed, uid } from '../state.js';
import { h, mount, toast, select, debounce, field, checkbox, confirmBox } from '../ui.js';
import { previewBoxes, CODES } from './dialogue.js';

export const id = 'events', title = 'Events', icon = '✦', needsProject = true;
const LANGS = ['en', 'es', 'fr', 'it', 'de'];

export function render(root, app) {
  const P = S.project;
  const st = { sel: P.events[0] ? P.events[0].id : null, lang: 'en', focus: null, flows: null };
  const left = h('div', { class: 'pane' }), main = h('div', { class: 'pane pad' }), side = h('div', { class: 'pane pad' });
  mount(root, h('div', { class: 'page-head' }, h('h2', {}, 'Events'), h('p', {}, 'Scripted conversations that play when the player walks into one of your buildings.')),
    h('div', { class: 'split', style: { gridTemplateColumns: '250px minmax(420px,1fr) 340px' } }, left, main, side));
  const ev = () => P.events.find((e) => e.id === st.sel);

  function drawLeft() {
    mount(left, h('div', { class: 'list' }, P.events.map((e) => h('div', { class: 'item' + (e.id === st.sel ? ' on' : ''), onclick: () => { st.sel = e.id; drawLeft(); drawMain(); } }, h('b', {}, e.id), h('span', { class: 'sub dim' }, (e.steps || []).length + ' msg'))), P.events.length ? null : h('div', { class: 'empty' }, 'No event yet')),
      h('div', { style: { padding: '10px' } }, h('button', { class: 'primary', style: { width: '100%' }, onclick: add }, 'New conversation')));
  }
  function add() {
    if (!P.buildings.length) { toast('Create a building first: events happen inside buildings', 'error'); return; }
    const e = { id: uid('talk', P.events), type: 'enter_talk', building: P.buildings[0].id, npc: 'Tanukichi', steps: [{ text: { en: '{3.1:}Welcome!' } }], goodbye: {} };
    P.events.push(e); st.sel = e.id; changed(); drawLeft(); drawMain();
  }

  async function drawMain() {
    const e = ev();
    if (!e) { mount(main, h('div', { class: 'empty' }, 'Create a conversation, or pick one.')); mount(side); return; }
    if (!st.flows) st.flows = await get('/api/events/flows');
    const maxSteps = (st.flows[e.npc] || { nodes: [] }).nodes.length;
    const bsel = select(P.buildings.map((b) => [b.id, b.name || b.id]), e.building, (v) => { e.building = v; changed(); drawMain(); });
    const b = P.buildings.find((x) => x.id === e.building);
    const tabs = h('div', { class: 'tabs', style: { margin: '10px 0' } }, LANGS.map((l) => h('button', { class: l === st.lang ? 'on' : '', onclick: () => { st.lang = l; drawMain(); } }, l.toUpperCase())));
    const stepCard = (s, i) => {
      const ta = h('textarea', { rows: 5, placeholder: st.lang === 'en' ? 'What is said (use {0.4:} to start a new box)' : 'Left empty: the English text is used' }, (s.text || {})[st.lang] || '');
      ta.addEventListener('input', () => { s.text = s.text || {}; if (ta.value) s.text[st.lang] = ta.value; else delete s.text[st.lang]; changed(); showPreview(ta.value || (s.text || {}).en || ''); });
      ta.addEventListener('focus', () => { st.focus = ta; showPreview(ta.value || (s.text || {}).en || ''); });
      return h('div', { class: 'card' }, h('div', { class: 'row', style: { marginBottom: '6px' } }, h('span', { class: 'chip' }, 'message ' + (i + 1)), h('div', { class: 'grow' }),
        h('button', { class: 'small ghost', disabled: i === 0, onclick: () => { e.steps.splice(i - 1, 0, e.steps.splice(i, 1)[0]); changed(); drawMain(); } }, '↑'),
        h('button', { class: 'small ghost', disabled: i === e.steps.length - 1, onclick: () => { e.steps.splice(i + 1, 0, e.steps.splice(i, 1)[0]); changed(); drawMain(); } }, '↓'),
        h('button', { class: 'small ghost danger', onclick: () => { e.steps.splice(i, 1); changed(); drawMain(); } }, 'remove')), ta);
    };
    const goodbye = h('textarea', { rows: 3, placeholder: 'Optional: replaces Tom Nook’s thank-you when leaving' }, (e.goodbye || {})[st.lang] || '');
    goodbye.addEventListener('input', () => { e.goodbye = e.goodbye || {}; if (goodbye.value) e.goodbye[st.lang] = goodbye.value; else delete e.goodbye[st.lang]; changed(); showPreview(goodbye.value); });
    goodbye.addEventListener('focus', () => { st.focus = goodbye; showPreview(goodbye.value); });
    mount(main,
      h('div', { class: 'row wrap' }, h('b', {}, 'When the player enters'), (() => { bsel.style.width = '200px'; return bsel; })(), h('span', { class: 'dim' }, 'the character says:'), h('span', { class: 'chip' }, (st.flows[e.npc] || {}).label || e.npc),
        h('div', { class: 'grow' }), h('button', { class: 'small ghost danger', onclick: async () => { if (await confirmBox('Delete this conversation?', 'Delete')) { P.events.splice(P.events.indexOf(e), 1); st.sel = P.events[0] ? P.events[0].id : null; changed(); drawLeft(); drawMain(); } } }, 'Delete')),
      b && !b.interior ? h('div', { class: 'warn-box', style: { marginTop: '10px' } }, 'This building has no interior of its own: the speech would also play in the real Nook’s Homes. Give it an interior in Buildings → Inside.') : null,
      tabs,
      h('div', { class: 'toolbar', style: { gap: '4px', border: '1px solid var(--line)', borderRadius: '6px', marginBottom: '10px' } }, h('span', { class: 'dim' }, 'Insert'), CODES.map(([l, c]) => h('button', { class: 'small', title: c, onclick: () => { const t = st.focus; if (!t) { toast('Click in a message first', 'info'); return; } t.setRangeText(c, t.selectionStart, t.selectionEnd, 'end'); t.dispatchEvent(new Event('input')); t.focus(); } }, l))),
      h('div', { class: 'col' }, (e.steps || []).map(stepCard),
        e.steps.length < maxSteps ? h('button', { onclick: () => { e.steps.push({ text: { en: '' } }); changed(); drawMain(); } }, '+ Add a message (' + e.steps.length + '/' + maxSteps + ')') : h('div', { class: 'dim' }, 'This character’s script allows ' + maxSteps + ' messages.'),
        h('div', { class: 'card' }, h('h3', {}, 'Goodbye'), goodbye)));
    mount(side, h('div', { class: 'panel-title' }, 'Preview'), h('div', { class: 'dim' }, 'Click in a message to see how it looks in the game.'));
    function showPreview(t) { mount(side, h('div', { class: 'panel-title' }, 'Message window'), previewBoxes(t || ' ')); }
  }
  drawLeft(); drawMain();
}
