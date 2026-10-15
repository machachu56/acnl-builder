import { get, post } from '../api.js';
import { S, changed, saveNow, uid } from '../state.js';
import { h, mount, toast, debounce, textInput, field, checkbox, modal, prompt, confirmBox, select, download } from '../ui.js';

export const id = 'scripts', title = 'Scripts', icon = '❯', needsProject = true;

const STATUS_LABEL = { ready: 'ready', 'needs-test': 'not yet seen in the game', advanced: 'advanced' };
const STATUS_CLASS = { ready: 'ok', 'needs-test': 'warn', advanced: 'err' };

export function render(root, app) {
  const P = S.project;
  P.scripts = P.scripts || []; P.actors = P.actors || {};
  const st = { sel: P.scripts[0] ? P.scripts[0].id : null, result: null, ref: null, tab: 'result' };
  const left = h('div', { class: 'pane' }), mid = h('div', { class: 'pane', style: { display: 'flex', flexDirection: 'column', padding: 0 } }), right = h('div', { class: 'pane pad' });
  mount(root, h('div', { class: 'page-head' }, h('h2', {}, 'Scripts'), h('p', {}, 'Python that reacts to the game: swap clothes, hide or replace villagers, hook any function. It is checked here, before the game ever sees it.')),
    h('div', { class: 'split', style: { gridTemplateColumns: '240px minmax(420px,1fr) 400px' } }, left, mid, right));
  const CAST = '@characters';
  st.gen = '';
  const cur = () => st.sel === CAST ? { id: CAST, name: 'Characters (made from the Interiors tab)', enabled: true, code: st.gen, generated: true } : P.scripts.find((x) => x.id === st.sel);
  async function loadGenerated() { try { await saveNow(); st.gen = (await get('/api/script/generated?project=' + S.pid)).source || ''; } catch (e) { st.gen = ''; } }

  // ---- list
  function drawLeft() {
    mount(left, h('div', { class: 'list' }, st.gen ? h('div', { class: 'item' + (st.sel === CAST ? ' on' : ''), onclick: () => { st.sel = CAST; st.result = null; drawAll(); check.now(); } }, h('span', {}, 'Characters'), h('span', { class: 'sub' }, h('span', { class: 'chip' }, 'from Interiors'))) : null, P.scripts.map((sc) => h('div', { class: 'item' + (sc.id === st.sel ? ' on' : ''), onclick: () => { st.sel = sc.id; st.result = null; drawAll(); check.now(); } },
        h('span', {}, sc.name || sc.id), h('span', { class: 'sub' }, sc.enabled === false ? h('span', { class: 'chip' }, 'off') : null)))),
      P.scripts.length || st.gen ? null : h('div', { class: 'empty' }, 'No script yet'),
      h('div', { style: { padding: '10px', display: 'grid', gap: '6px' } }, h('button', { class: 'primary', onclick: newScript }, '+ New script'),
        h('button', { onclick: showGuide }, 'How scripts work…')),
      actorsCard());
  }
  async function newScript() {
    const ex = await post('/api/script/examples', { project: S.pid });
    let choice = '';
    const sel = select([['', 'Empty script'], ...ex.map((e) => [e.id, e.title])], '', (v) => { choice = v; desc.textContent = (ex.find((e) => e.id === v) || {}).description || 'A trigger function that does nothing yet.'; });
    const name = h('input', { type: 'text', value: 'My script' });
    const desc = h('div', { class: 'dim', style: { fontSize: '12px', maxWidth: '460px', whiteSpace: 'pre-wrap', marginTop: '6px' } }, 'A trigger function that does nothing yet.');
    if (!await modal('New script', h('div', { class: 'col' }, field('Name', name), field('Start from', sel), desc), [{ label: 'Cancel', value: false }, { label: 'Create', value: true, primary: true }])) return;
    const e = ex.find((x) => x.id === choice);
    const sc = { id: uid('script', P.scripts), name: name.value || 'Script', enabled: true, code: e ? e.code : 'from acnl import *\n\n\n@on_enter("my_building")\ndef when_someone_comes_in():\n    log("hello")\n' };
    P.scripts.push(sc); st.sel = sc.id; changed(); drawAll(); check.now();
  }

  // ---- actors: names for the numbers the game uses
  function actorsCard() {
    const rows = Object.entries(P.actors);
    return h('div', { class: 'card', style: { margin: '10px' } }, h('h3', {}, 'Actors'),
      h('div', { class: 'dim', style: { fontSize: '12px', marginBottom: '6px' } }, 'A name for the profile number the game gives a villager or object, so scripts can say @on_actor("Isabelle"). The probe lists the numbers (docs/HOOKS.md).'),
      rows.map(([n, v]) => h('div', { class: 'row', style: { gap: '4px', marginBottom: '4px' } }, h('b', { style: { flex: 1 } }, n), h('span', { class: 'kbd' }, '0x' + Number(v).toString(16)),
        h('button', { class: 'small ghost danger', onclick: () => { delete P.actors[n]; changed(); drawLeft(); check(); } }, '×'))),
      h('button', { class: 'small', onclick: async () => {
        const n = await prompt('New actor', 'Name', 'Isabelle'); if (!n) return;
        const v = await prompt('Profile number', 'Number (0x… or decimal)', '0x'); const num = Number(v);
        if (!Number.isInteger(num) || num < 0 || num > 0xFFFF) { toast('A profile number is a whole number up to 0xFFFF', 'error'); return; }
        P.actors[n] = num; changed(); drawLeft(); check();
      } }, '+ Add an actor'));
  }

  // ---- editor
  const ta = h('textarea', { spellcheck: 'false', style: { flex: 1, resize: 'none', font: '13px/1.5 var(--mono, monospace)', background: 'var(--bg)', color: 'var(--text)', border: 0, padding: '8px 10px 8px 54px', outline: 'none', whiteSpace: 'pre', tabSize: 4 } });
  const gutter = h('div', { style: { position: 'absolute', left: 0, top: 0, bottom: 0, width: '46px', overflow: 'hidden', font: '13px/1.5 var(--mono, monospace)', color: 'var(--dim)', textAlign: 'right', padding: '8px 6px 8px 0', userSelect: 'none', pointerEvents: 'none', background: 'var(--panel)' } });
  const wrap = h('div', { style: { position: 'relative', flex: 1, display: 'flex', minHeight: 0 } }, gutter, ta);
  const head = h('div', { class: 'toolbar' });
  function drawGutter() {
    const lines = ta.value.split('\n').length, bad = new Map();
    for (const d of (st.result && st.result.diagnostics) || []) if (d.line && !bad.has(d.line) || (bad.get(d.line) || {}).severity !== 'error') bad.set(d.line, d);
    mount(gutter, h('div', { style: { transform: `translateY(${-ta.scrollTop}px)` } }, Array.from({ length: lines }, (_, i) => {
      const d = bad.get(i + 1);
      return h('div', { style: { color: d ? (d.severity === 'error' ? 'var(--danger)' : d.severity === 'warning' ? 'var(--warm)' : 'var(--info)') : '', fontWeight: d ? 700 : 400 } }, (d ? '● ' : '') + (i + 1));
    })));
  }
  ta.addEventListener('scroll', drawGutter);
  ta.addEventListener('input', () => { const sc = cur(); if (!sc || sc.generated) return; sc.code = ta.value; changed(); drawGutter(); check(); });
  ta.addEventListener('keydown', (e) => {
    if (e.key === 'Tab') { e.preventDefault(); const a = ta.selectionStart; ta.setRangeText('    ', a, ta.selectionEnd, 'end'); ta.dispatchEvent(new Event('input')); }
    if (e.key === 'Enter') {                       // keep the indentation (and add one after a colon)
      const a = ta.selectionStart, before = ta.value.slice(0, a), line = before.slice(before.lastIndexOf('\n') + 1), ind = line.match(/^ */)[0] + (/:\s*$/.test(line) ? '    ' : '');
      e.preventDefault(); ta.setRangeText('\n' + ind, a, ta.selectionEnd, 'end'); ta.dispatchEvent(new Event('input'));
    }
  });
  function drawMid() {
    const sc = cur();
    if (!sc) { mount(mid, h('div', { class: 'empty' }, 'Create a script, or start from an example: “+ New script”.')); return; }
    mount(head, sc.generated ? h('b', {}, sc.name) : textInput(sc.name || '', (v) => { sc.name = v; changed(); drawLeft(); }, { style: { width: '220px' }, placeholder: 'Name' }),
      sc.generated ? null : checkbox(sc.enabled !== false, (v) => { sc.enabled = v; changed(); drawLeft(); }, 'Enabled'),
      h('div', { class: 'grow' }),
      h('span', { class: 'chip ' + (!st.result ? '' : st.result.ok ? 'ok' : 'err') }, !st.result ? 'checking…' : st.result.ok ? '✓ ready to export' : st.result.diagnostics.filter((d) => d.severity === 'error').length + ' problem(s)'),
      h('button', { class: 'small', onclick: () => check.now() }, 'Check'),
      sc.generated ? null : h('button', { class: 'small danger', onclick: async () => { if (!await confirmBox('Delete the script “' + (sc.name || sc.id) + '”?', 'Delete')) return; P.scripts.splice(P.scripts.indexOf(sc), 1); st.sel = P.scripts[0] ? P.scripts[0].id : null; changed(); drawAll(); } }, 'Delete'));
    ta.value = sc.code || ''; ta.readOnly = !!sc.generated;
    mount(mid, head, sc.generated ? h('div', { class: 'info-box', style: { margin: '8px' } }, 'This script is written for you from the Characters card (Interiors tab > Add). Change the characters there; it is compiled into the mod with your other scripts.') : null, wrap);
    drawGutter();
  }

  // ---- results: problems, then what the script does through the day
  function jump(line) { const lines = ta.value.split('\n'); let o = 0; for (let i = 0; i < line - 1 && i < lines.length; i++) o += lines[i].length + 1; ta.focus(); ta.setSelectionRange(o, o + (lines[line - 1] || '').length); ta.scrollTop = Math.max(0, (line - 4) * 19.5); drawGutter(); }
  function drawRight() {
    const r = st.result;
    const tabs = h('div', { class: 'tabs' }, [['result', 'Result'], ['ref', 'Reference']].map(([k, l]) => h('button', { class: st.tab === k ? 'on' : '', onclick: () => { st.tab = k; drawRight(); } }, l)));
    if (st.tab === 'ref') { mount(right, tabs, reference()); return; }
    if (!cur()) { mount(right, tabs); return; }
    if (!r) { mount(right, tabs, h('div', { class: 'dim', style: { padding: '12px' } }, 'Checking…')); return; }
    const sev = { error: 'err-box', warning: 'warn-box', info: 'info-box' };
    mount(right, tabs, h('div', { style: { padding: '10px', display: 'grid', gap: '6px' } },
      r.diagnostics.length ? r.diagnostics.map((d) => h('div', { class: sev[d.severity] || 'info-box', style: { cursor: d.line ? 'pointer' : '', whiteSpace: 'pre-wrap' }, onclick: () => d.line && jump(d.line) },
        d.line ? h('b', {}, 'line ' + d.line + ': ') : null, d.message, d.hint ? h('div', { class: 'dim', style: { marginTop: '2px' } }, d.hint) : null))
        : h('div', { class: 'info-box' }, 'No problems found.'),
      (r.handlers || []).length ? h('h3', { style: { margin: '8px 0 0' } }, 'What it does') : null,
      (r.handlers || []).map(handlerCard),
      r.bytes ? h('div', { class: 'dim', style: { fontSize: '12px' } }, 'Compiled: ' + r.bytes + ' bytes of the 24000 the game has room for. The timeline assumes it is a Wednesday; chance() rolls vary in the game.') : null));
  }
  function handlerCard(hd) {
    const rows = hd.timeline.map((seg) => h('tr', { style: { borderTop: '1px solid var(--line)' } },
      h('td', { style: { padding: '3px 6px 3px 0', whiteSpace: 'nowrap', color: 'var(--dim)' } }, seg.start === '00:00' && seg.end === '00:00' ? 'always' : seg.start + '–' + seg.end),
      h('td', { style: { color: seg.error ? 'var(--danger)' : '' } }, seg.error ? 'error: ' + seg.error : seg.does.length ? seg.does.join('  ') : h('span', { class: 'dim' }, 'nothing'))));
    return h('div', { class: 'card' }, h('div', {}, h('b', {}, hd.name + '()'), h('div', { class: 'dim', style: { fontSize: '12px' } }, 'runs ' + hd.trigger)),
      h('table', { style: { width: '100%', marginTop: '6px', fontSize: '12px', borderCollapse: 'collapse' } }, rows));
  }
  function reference() {
    const ref = st.ref;
    if (!ref) { get('/api/script/reference').then((r) => { st.ref = r; if (st.tab === 'ref') drawRight(); }); return h('div', { class: 'dim', style: { padding: '12px' } }, 'Loading…'); }
    const sig = (n) => n.name + '(' + n.params.map((p) => p.name).join(', ') + ')';
    return h('div', { style: { padding: '10px', display: 'grid', gap: '8px' } },
      h('button', { class: 'small', onclick: async () => { const t = await (await fetch('/api/script/stub')).text(); download('acnl.py', new Blob([t], { type: 'text/x-python' })); } }, 'Download acnl.py (editor completion)'),
      h('h3', { style: { margin: '4px 0 0' } }, 'Triggers'),
      ref.triggers.map((t) => h('div', { class: 'card' }, h('code', {}, '@' + t.name + '(' + [...t.params.map((p) => p.name), ...t.options.map((p) => p.name + '=…')].join(', ') + ')'), h('div', { class: 'dim', style: { fontSize: '12px' } }, t.doc))),
      h('h3', { style: { margin: '4px 0 0' } }, 'Functions'),
      ref.natives.map((n) => h('div', { class: 'card' }, h('div', { class: 'row' }, h('code', {}, sig(n)), h('div', { class: 'grow' }), h('span', { class: 'chip ' + STATUS_CLASS[n.status] }, STATUS_LABEL[n.status])),
        h('div', { class: 'dim', style: { fontSize: '12px' } }, n.doc), n.where[0] !== 'any' ? h('div', { class: 'dim', style: { fontSize: '12px' } }, 'only in: ' + n.where.map((w) => '@on_' + w).join(', ')) : null,
        n.example ? h('pre', { style: { margin: '4px 0 0', fontSize: '12px', color: 'var(--accent)' } }, n.example) : null)));
  }
  function showGuide() {
    modal('How scripts work', h('div', { style: { maxWidth: '620px', lineHeight: 1.5 } },
      h('p', {}, 'A script is a few Python functions. Each one starts with a trigger line that says when the game should run it:'),
      h('pre', { style: { background: 'var(--bg)', padding: '8px', borderRadius: '6px' } }, '@on_enter("baisodrome")      # the player walks in\ndef welcome():\n    if time_between("22:00", "06:00"):\n        log("it is night")'),
      h('p', {}, 'Inside you can ask about the clock, the place, remembered values, and do things: dress villagers, hide or replace actors, put the player somewhere, or reach the game’s own functions and memory to build anything new.'),
      h('p', {}, 'Scripts are never run by Python: Builder checks them (names, places, outfits, game addresses), runs them through the whole day on a pretend game, and compiles them into a small program the mod’s plugin runs. If something is wrong you are told here, with the line, not in the game.'),
      h('p', {}, 'Things marked “not yet seen in the game” are implemented but nobody has watched the game do them yet: use the log and tell what happens. The full guide is docs/SCRIPTING.md.')), [{ label: 'OK', value: true, primary: true }]);
  }

  const check = debounce(async () => {
    const sc = cur(); if (!sc) { st.result = null; drawRight(); return; }
    try { await saveNow(); st.result = await post('/api/script/check', { project: S.pid, source: sc.code || '' }); }
    catch (e) { st.result = { ok: false, diagnostics: [{ line: 0, severity: 'error', message: e.message, hint: '' }], handlers: [] }; }
    drawMid_head(); drawGutter(); drawRight();
  }, 600);
  function drawMid_head() { const c = head.querySelector('.chip'); if (c && st.result) { c.className = 'chip ' + (st.result.ok ? 'ok' : 'err'); c.textContent = st.result.ok ? '✓ ready to export' : st.result.diagnostics.filter((d) => d.severity === 'error').length + ' problem(s)'; } }
  function drawAll() { drawLeft(); drawMid(); drawRight(); }
  loadGenerated().then(() => { if (!st.sel && st.gen) st.sel = CAST; drawAll(); if (cur()) check.now(); });
  drawAll(); if (cur()) check.now();
}
