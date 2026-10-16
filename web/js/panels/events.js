import { get, q } from '../api.js';
import { S, changed, uid } from '../state.js';
import { h, mount, toast, select, debounce, field, checkbox, confirmBox, textInput } from '../ui.js';
import { previewBoxes, CODES } from './dialogue.js';

export const id = 'events', title = 'Events', icon = '✦', needsProject = true;
const LANGS = ['en', 'es', 'fr', 'it', 'de'];
const SCOPES = [['building', 'only inside a building'], ['script', 'only when a script switches it on'], ['always', 'everywhere, all the time']];

export function render(root, app) {
  const P = S.project;
  const st = { sel: P.events[0] ? P.events[0].id : null, lang: 'en', focus: null, named: null, flow: {}, list: [], q: '' };
  const left = h('div', { class: 'pane' }), main = h('div', { class: 'pane pad' }), side = h('div', { class: 'pane pad' });
  mount(root, h('div', { class: 'page-head' }, h('h2', {}, 'Events'), h('p', {}, 'Change what a character says in any of the game’s conversations, for one building, for when a script says so, or everywhere.')),
    h('div', { class: 'split', style: { gridTemplateColumns: '250px minmax(420px,1fr) 340px' } }, left, main, side));
  const ev = () => P.events.find((e) => e.id === st.sel);

  function drawLeft() {
    mount(left, h('div', { class: 'list' }, P.events.map((e) => h('div', { class: 'item' + (e.id === st.sel ? ' on' : ''), onclick: () => { st.sel = e.id; drawLeft(); drawMain(); } }, h('b', {}, e.id), h('span', { class: 'sub dim' }, (e.mode === 'rewrite' ? (e.edits || []).filter((x) => Object.values(x.text || {}).some(Boolean)).length + ' line' : (e.steps || []).length + ' msg')))), P.events.length ? null : h('div', { class: 'empty' }, 'No event yet')),
      h('div', { style: { padding: '10px' } }, h('button', { class: 'primary', style: { width: '100%' }, onclick: add }, 'New conversation')));
  }
  async function named() { if (!st.named) st.named = await get('/api/events/flows'); return st.named; }
  async function add() {
    const nm = await named(), first = Object.values(nm)[0];
    const e = { id: uid('talk', P.events), type: 'conversation', flow: first.flow, scope: P.buildings.length ? 'building' : 'always', building: P.buildings[0] ? P.buildings[0].id : '', mode: 'sequence', steps: [{ text: { en: '{3.1:}Welcome!' } }], edits: [], goodbye: {} };
    P.events.push(e); st.sel = e.id; changed(); drawLeft(); drawMain();
  }
  async function flowInfo(path) { if (!st.flow[path]) st.flow[path] = await get('/api/events/flow?' + q({ flow: path })); return st.flow[path]; }

  async function drawMain() {
    const e = ev();
    if (!e) { mount(main, h('div', { class: 'empty' }, 'Create a conversation, or pick one.')); mount(side); return; }
    const nm = await named();
    if (e.type === 'enter_talk') { e.type = 'conversation'; e.flow = (nm[e.npc || 'Tanukichi'] || Object.values(nm)[0]).flow; e.scope = 'building'; e.mode = 'sequence'; changed(); }
    e.scope = e.scope || 'building'; e.mode = e.mode || 'sequence'; e.steps = e.steps || []; e.edits = e.edits || [];
    const info = await flowInfo(e.flow).catch(() => ({ nodes: [], goodbye: false }));
    const known = Object.values(nm).find((v) => v.flow === e.flow);
    const maxSteps = info.slots || info.nodes.length, maxChoices = info.max_choices || 6, maxAnswer = info.max_answer || 24;
    for (const s of e.steps) if (!s.id) { s.id = uid('m', e.steps); changed(); }
    const stepName = (id) => { const k = e.steps.findIndex((x) => x.id === id); return k < 0 ? '?' : 'message ' + (k + 1); };
    // where a message (or an answer) leads: '' = the message below it, 'end', or the id of a message
    const nextSelect = (cur, i, onPick, allowBelow) => select([...(allowBelow ? [['', i + 1 < e.steps.length ? 'Go on with the message below' : 'End the conversation']] : []), ['end', 'End the conversation'],
      ...e.steps.filter((x, k) => k !== i || !allowBelow).map((x) => [x.id, 'Go to ' + stepName(x.id)])], cur || (allowBelow ? '' : 'end'), onPick);
    const b = P.buildings.find((x) => x.id === e.building);
    const tabs = h('div', { class: 'tabs', style: { margin: '10px 0' } }, LANGS.map((l) => h('button', { class: l === st.lang ? 'on' : '', onclick: () => { st.lang = l; drawMain(); } }, l.toUpperCase())));
    const bind = (ta, get_, set_) => {
      ta.addEventListener('input', () => { set_(ta.value); changed(); showPreview(ta.value || get_(true) || ''); });
      ta.addEventListener('focus', () => { st.focus = ta; showPreview(ta.value || get_(true) || ''); });
      return ta;
    };
    const textBox = (obj, rows, ph) => bind(h('textarea', { rows, placeholder: st.lang === 'en' ? ph : 'Left empty: the English text is used' }, (obj.text || {})[st.lang] || ''),
      (en) => (en ? (obj.text || {}).en : ''), (v) => { obj.text = obj.text || {}; if (v) obj.text[st.lang] = v; else delete obj.text[st.lang]; });
    const answerRow = (s, i, c, j) => {
      const inp = h('input', { type: 'text', value: (c.text || {})[st.lang] || '', maxlength: 40, placeholder: st.lang === 'en' ? 'An answer, e.g. Sure!' : 'Left empty: the English text is used' });
      const warn = h('span', { class: 'dim', style: { fontSize: '11px', minWidth: '34px', textAlign: 'right' } });
      const count = () => { const n = inp.value.length; warn.textContent = n + '/' + maxAnswer; warn.style.color = n > maxAnswer ? 'var(--err, #d55)' : ''; };
      inp.addEventListener('input', () => { c.text = c.text || {}; if (inp.value) c.text[st.lang] = inp.value; else delete c.text[st.lang]; count(); changed(); });
      count();
      const nx = nextSelect(c.next, i, (v) => { c.next = v; changed(); }, false); nx.style.width = '190px';
      return h('div', { class: 'row', style: { gap: '6px', marginTop: '4px' } }, h('span', { class: 'dim' }, '▸'), h('div', { class: 'grow', style: { display: 'flex' } }, inp), warn, nx,
        h('button', { class: 'small ghost danger', title: 'Remove this answer', onclick: () => { s.choices.splice(j, 1); if (!s.choices.length) delete s.choices; changed(); drawMain(); } }, '✕'));
    };
    const stepCard = (s, i) => {
      const ch = s.choices || [];
      return h('div', { class: 'card' }, h('div', { class: 'row', style: { marginBottom: '6px' } }, h('span', { class: 'chip' }, 'message ' + (i + 1)), h('div', { class: 'grow' }),
        h('button', { class: 'small ghost', disabled: i === 0, onclick: () => { e.steps.splice(i - 1, 0, e.steps.splice(i, 1)[0]); changed(); drawMain(); } }, '↑'),
        h('button', { class: 'small ghost', disabled: i === e.steps.length - 1, onclick: () => { e.steps.splice(i + 1, 0, e.steps.splice(i, 1)[0]); changed(); drawMain(); } }, '↓'),
        h('button', { class: 'small ghost danger', onclick: () => { const gone = s.id; e.steps.splice(i, 1); for (const x of e.steps) { if (x.next === gone) delete x.next; for (const c of x.choices || []) if (c.next === gone) c.next = 'end'; } changed(); drawMain(); } }, 'remove')),
        textBox(s, 5, 'What is said (use {0.4:} to start a new box)'),
        ch.length ? h('div', { style: { marginTop: '8px' } }, h('div', { class: 'dim', style: { fontSize: '12px' } }, 'The player answers'), ch.map((c, j) => answerRow(s, i, c, j)),
          ch.length < 2 ? h('div', { class: 'warn-box', style: { marginTop: '6px' } }, 'A question needs at least 2 answers.') : null) : null,
        h('div', { class: 'row', style: { gap: '8px', marginTop: '8px' } },
          ch.length < maxChoices ? h('button', { class: 'small', onclick: () => { s.choices = s.choices || []; s.choices.push({ text: { en: '' }, next: 'end' }); if (s.choices.length === 1) s.choices.push({ text: { en: '' }, next: 'end' }); changed(); drawMain(); } }, ch.length ? '+ Answer' : '+ Let the player answer') : null,
          h('div', { class: 'grow' }),
          ch.length ? null : h('span', { class: 'dim', style: { fontSize: '12px' } }, 'Then'),
          ch.length ? null : (() => { const nx = nextSelect(s.next, i, (v) => { if (v) s.next = v; else delete s.next; changed(); }, true); nx.style.width = '220px'; return nx; })()));
    };
    const edit = (n) => { let x = e.edits.find((y) => y.label === n.label); if (!x) { x = { label: n.label, text: {} }; e.edits.push(x); } return x; };
    const rewriteCard = (n) => {
      const x = e.edits.find((y) => y.label === n.label) || { text: {} };
      const ta = bind(h('textarea', { rows: 4, placeholder: 'Leave empty to keep the game’s line' }, (x.text || {})[st.lang] || ''), () => n.text, (v) => { const t = edit(n); if (v) t.text[st.lang] = v; else delete t.text[st.lang]; });
      return h('div', { class: 'card' }, h('div', { class: 'row', style: { marginBottom: '4px' } }, h('span', { class: 'chip' }, 'line ' + n.label), h('span', { class: 'dim', style: { fontSize: '12px', whiteSpace: 'pre-wrap' } }, 'now: ' + n.text.replace(/\{[^}]*\}/g, '').slice(0, 110))), ta);
    };
    const goodbye = bind(h('textarea', { rows: 3, placeholder: 'Optional: replaces the closing line' }, (e.goodbye || {})[st.lang] || ''), () => '', (v) => { e.goodbye = e.goodbye || {}; if (v) e.goodbye[st.lang] = v; else delete e.goodbye[st.lang]; });
    const flowSearch = h('input', { type: 'search', placeholder: 'Search the game’s conversations (e.g. Secretary, Tanukichi, Ev_Carnival)…', value: st.q });
    const flowList = h('div', { class: 'list', style: { maxHeight: '180px', overflow: 'auto', display: st.q ? '' : 'none' } });
    const loadList = debounce(async () => { st.q = flowSearch.value; flowList.style.display = st.q ? '' : 'none'; if (!st.q) return; const r = await get('/api/events/flowlist?' + q({ q: st.q })); mount(flowList, r.slice(0, 80).map((f) => h('div', { class: 'item' + (f.flow === e.flow ? ' on' : ''), onclick: () => { e.flow = f.flow; e.steps = []; e.edits = []; e.mode = 'rewrite'; st.q = ''; changed(); drawMain(); } }, f.name, f.npc ? h('span', { class: 'chip sub' }, f.npc) : null))); }, 200);
    flowSearch.addEventListener('input', loadList); if (st.q) loadList();
    const curated = select([...Object.entries(nm).map(([k, v]) => [v.flow, v.label]), ...(known ? [] : [[e.flow, e.flow.split('/').pop().replace('.msbf', '')]])], e.flow, (v) => { e.flow = v; e.steps = []; e.edits = []; changed(); drawMain(); });
    mount(main,
      h('div', { class: 'row wrap' }, h('b', {}, 'Conversation'), (() => { curated.style.width = '320px'; return curated; })(), h('div', { class: 'grow' }),
        h('button', { class: 'small ghost danger', onclick: async () => { if (await confirmBox('Delete this conversation?', 'Delete')) { P.events.splice(P.events.indexOf(e), 1); st.sel = P.events[0] ? P.events[0].id : null; changed(); drawLeft(); drawMain(); } } }, 'Delete')),
      h('div', { style: { margin: '6px 0' } }, flowSearch, flowList),
      h('div', { class: 'grid2' }, field('Name (scripts use it)', textInput(e.id, (v) => { const n = v.toLowerCase().replace(/[^a-z0-9_]/g, '_'); if (n && !P.events.some((x) => x !== e && x.id === n)) { e.id = n; st.sel = n; changed(); drawLeft(); } })),
        field('It applies', select(SCOPES, e.scope, (v) => { e.scope = v; changed(); drawMain(); }))),
      e.scope === 'building' ? field('Building', select(P.buildings.map((x) => [x.id, x.name || x.id]), e.building, (v) => { e.building = v; changed(); drawMain(); })) : null,
      e.scope === 'building' && b && !b.interior ? h('div', { class: 'warn-box', style: { marginTop: '8px' } }, 'This building has no interior of its own: the conversation would also play in the real place. Give it an interior in Buildings → Inside.') : null,
      e.scope === 'script' ? h('div', { class: 'info-box', style: { marginTop: '8px' } }, 'Off until a script switches it on, e.g. ', h('code', {}, '@on_enter("my_building")\ndef hello():\n    conversation_on("' + e.id + '")')) : null,
      e.scope === 'always' ? h('div', { class: 'warn-box', style: { marginTop: '8px' } }, 'This changes the conversation everywhere in the game, all the time.') : null,
      h('div', { class: 'grid2', style: { marginTop: '8px' } }, field('What to change', select([['sequence', 'My own conversation (messages, questions and answers)'], ['rewrite', 'Rewrite the game’s own lines (its questions and answers stay)']], e.mode, (v) => { e.mode = v; changed(); drawMain(); }))),
      tabs,
      h('div', { class: 'toolbar', style: { gap: '4px', border: '1px solid var(--line)', borderRadius: '6px', marginBottom: '10px' } }, h('span', { class: 'dim' }, 'Insert'), CODES.map(([l, c]) => h('button', { class: 'small', title: c, onclick: () => { const t = st.focus; if (!t) { toast('Click in a message first', 'info'); return; } t.setRangeText(c, t.selectionStart, t.selectionEnd, 'end'); t.dispatchEvent(new Event('input')); t.focus(); } }, l))),
      e.mode === 'rewrite'
        ? h('div', { class: 'col' }, info.nodes.length ? info.nodes.map(rewriteCard) : h('div', { class: 'dim' }, 'No readable lines in this conversation.'))
        : h('div', { class: 'col' }, e.steps.map(stepCard),
          e.steps.length < maxSteps ? h('button', { onclick: () => { e.steps.push({ id: uid('m', e.steps), text: { en: '' } }); changed(); drawMain(); } }, '+ Add a message') : h('div', { class: 'dim' }, 'This conversation has room for ' + maxSteps + ' messages.'),
          info.goodbye ? h('div', { class: 'card' }, h('h3', {}, 'Goodbye'), goodbye) : null));
    mount(side, h('div', { class: 'panel-title' }, 'Preview'), h('div', { class: 'dim' }, 'Click in a message to see how it looks in the game.'),
      h('div', { class: 'info-box', style: { marginTop: '12px', fontSize: '12px' } }, 'The game decides when each conversation starts (talking to someone, a visit…). Give a message answers to ask the player something: each answer goes on to a message of its own, or ends the conversation.'));
    function showPreview(t) { mount(side, h('div', { class: 'panel-title' }, 'Message window'), previewBoxes(t || ' ')); }
  }
  drawLeft(); drawMain();
}
