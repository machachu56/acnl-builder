import { get, post, q } from '../api.js';
import { S, changed } from '../state.js';
import { h, mount, clear, toast, select, debounce } from '../ui.js';

export const id = 'dialogue', title = 'Dialogue', icon = '✎', needsProject = true;

const LANGS = ['en', 'es', 'fr', 'it', 'de'];
const MAX_LINE = 34, MAX_ROWS = 3;
export const CODES = [
  ['Player name', '{5.0:}'], ['Town name', '{5.5:}'], ['New box', '{0.4:}'], ['Pause', '{7.0:0a000000}'],
  ['Highlight', '{0.3:0200}…{0.3:ffff}'], ['Smile', '{3.1:}'], ['Delighted', '{3.3:}'], ['Proud', '{3.5:}'], ['Thinking', '{3.11:}'], ['Surprised', '{3.15:}'], ['Dreamy', '{3.21:}'], ['Asking', '{3.23:}'], ['Embarrassed', '{3.26:}'], ['Beaming', '{3.38:}'],
];
const EXPR = { 1: 'smile', 3: 'delighted', 5: 'proud', 11: 'thinking', 15: 'surprised', 21: 'dreamy', 23: 'asking', 26: 'embarrassed', 38: 'beaming' };
const CODE_RE = /\{(\d+)\.(\d+):([0-9a-f]*)\}/g;

function plainLen(line) {
  return line.replace(/\{5\.0:\}/g, 'XXXXXXXX').replace(/\{5\.5:\}/g, 'XXXXXXXX').replace(CODE_RE, '').length;
}

// a message window preview: one panel per text box, codes as small tags
export function previewBoxes(text) {
  const boxes = text.split('{0.4:}');
  return h('div', { class: 'col', style: { gap: '10px' } }, boxes.map((box, bi) => {
    const rows = box.split('\n');
    const over = rows.length > MAX_ROWS;
    return h('div', { style: { background: '#f4efe3', color: '#3b3226', borderRadius: '12px', padding: '10px 14px', border: '2px solid ' + (over ? 'var(--danger)' : '#cdbf9f'), fontFamily: 'var(--mono)', fontSize: '13px', lineHeight: '1.55', position: 'relative' } },
      h('div', { style: { position: 'absolute', top: '-8px', right: '10px', fontSize: '10px', background: 'var(--panel)', color: 'var(--dim)', padding: '0 6px', borderRadius: '6px' } }, 'box ' + (bi + 1)),
      rows.map((r) => {
        const tooLong = plainLen(r) > MAX_LINE;
        const parts = []; let last = 0, m, hl = false;
        CODE_RE.lastIndex = 0;
        while ((m = CODE_RE.exec(r))) {
          if (m.index > last) parts.push(span(r.slice(last, m.index), hl));
          const g = +m[1], t = +m[2];
          if (g === 5 && t === 0) parts.push(tag('PLAYER', '#2e6f4f'));
          else if (g === 5 && t === 5) parts.push(tag('TOWN', '#2e6f4f'));
          else if (g === 3) parts.push(tag(EXPR[t] || 'face ' + t, '#6b5b95', true));
          else if (g === 7 && t === 0) parts.push(tag('…', '#999', true));
          else if (g === 0 && t === 3) hl = m[3] !== 'ffff';
          else parts.push(tag(m[0], '#a05', true));
          last = m.index + m[0].length;
        }
        if (last < r.length) parts.push(span(r.slice(last), hl));
        return h('div', { style: { minHeight: '1.55em', whiteSpace: 'pre', color: tooLong ? 'var(--danger)' : '', borderRight: tooLong ? '2px solid var(--danger)' : '' } }, parts.length ? parts : ' ');
      }));
  }));
  function span(t, hl) { return h('span', { style: hl ? { color: '#c2410c', fontWeight: 700 } : {} }, t); }
  function tag(t, bg, small) { return h('span', { style: { background: bg, color: '#fff', borderRadius: '4px', padding: '0 4px', margin: '0 1px', fontSize: small ? '10px' : '11px' } }, t); }
}

export function render(root, app) {
  const P = S.project;
  const st = { file: null, rows: null, lang: 'en', filter: '', group: '', fq: '', variant: '', shown: 80, focus: null, last: null };
  const listPane = h('div', { class: 'pane' });
  const mainPane = h('div', { class: 'pane', style: { display: 'flex', flexDirection: 'column' } });
  const prevPane = h('div', { class: 'pane pad' });
  mount(root,
    h('div', { class: 'page-head' }, h('h2', {}, 'Dialogue & text'), h('p', {}, 'Everything characters say, plus names and menus. Pick a file, rewrite its messages; empty languages fall back to English.')),
    h('div', { class: 'split', style: { gridTemplateColumns: '280px minmax(380px, 1fr) 340px' } }, listPane, mainPane, prevPane));

  // ---- file list
  let groups = [];
  const files = h('div', { class: 'list' });
  const search = h('input', { type: 'search', placeholder: 'Find a file (e.g. Tanukichi, STR_Map)…' });
  const grp = h('select', {});
  const text = h('input', { type: 'search', placeholder: 'Search what is said (English)…' });
  const results = h('div', { class: 'list' });
  const loadFiles = debounce(async () => {
    const r = await get('/api/game/text-files?' + q({ q: search.value, group: grp.value }));
    if (!groups.length) { groups = r.groups; mount(grp, h('option', { value: '' }, 'All groups'), groups.map((g) => h('option', { value: g }, g))); if (groups.includes('Talk')) { grp.value = 'Talk'; loadFiles(); return; } }
    mount(files, r.files.map((f) => h('div', { class: 'item' + (st.file === f.path ? ' on' : ''), onclick: () => openFile(f.path) }, h('span', {}, f.name), editedCount(f.path) ? h('span', { class: 'chip ok sub' }, editedCount(f.path)) : null)),
      r.total > r.files.length ? h('div', { class: 'dim', style: { padding: '8px 12px' } }, `${r.total - r.files.length} more — narrow the search`) : null);
  }, 150);
  const textSearch = debounce(async () => {
    if (text.value.length < 3) { mount(results); return; }
    const r = await get('/api/game/text-search?q=' + encodeURIComponent(text.value));
    mount(results, r.length ? r.map((x) => h('div', { class: 'item', style: { flexDirection: 'column', alignItems: 'flex-start', gap: '2px' }, onclick: () => openFile(x.path, x.label) },
      h('span', { class: 'dim', style: { fontSize: '11px' } }, x.path.replace('/Script/', '') + ' · ' + x.label), h('span', {}, x.text.replace(/\{[^}]*\}/g, '').replace(/\n/g, ' ').slice(0, 90)))) : h('div', { class: 'dim', style: { padding: '10px 12px' } }, 'No match'));
  }, 250);
  search.addEventListener('input', loadFiles); grp.addEventListener('change', loadFiles); text.addEventListener('input', textSearch);
  mount(listPane, h('div', { style: { padding: '10px', display: 'grid', gap: '6px', position: 'sticky', top: 0, background: 'var(--bg)', zIndex: 2 } }, search, grp, text), results, files);
  loadFiles();

  const editedCount = (path) => P.text.filter((e) => e.file === path).length;
  const entry = (label, create) => {
    const v = st.variant || null;
    let e = P.text.find((x) => x.file === st.file && x.label === label && (x.variant || null) === v);
    if (!e && create) { e = { file: st.file, label, text: {} }; if (v) e.variant = v; P.text.push(e); }
    return e;
  };

  async function openFile(path, label) {
    st.file = path; st.shown = 80; st.filter = label || '';
    mount(mainPane, h('div', { class: 'empty' }, 'Loading…'));
    try { st.rows = await get('/api/game/text?path=' + encodeURIComponent(path)); } catch (e) { toast(e.message, 'error'); return; }
    loadFiles(); drawMain();
    if (label) setTimeout(() => { const el = mainPane.querySelector('[data-label="' + label + '"]'); if (el) el.scrollIntoView({ block: 'center' }); }, 50);
  }

  // ---- messages
  function drawMain() {
    if (!st.rows) { mount(mainPane, h('div', { class: 'empty' }, 'Pick a file on the left, or search for a line.')); return; }
    const langs = LANGS.filter((l) => st.rows[l]);
    if (!langs.includes(st.lang)) st.lang = langs[0];
    const rows = st.rows[st.lang] || [];
    const en = st.rows.en || rows;
    const flt = st.filter.toLowerCase();
    const matches = rows.filter((r) => !flt || r.label.toLowerCase().includes(flt) || r.text.toLowerCase().includes(flt));
    const variants = [['', 'Everywhere'], ...P.buildings.map((b) => [b.id, 'Only inside ' + (b.name || b.id)])];
    const filter = h('input', { type: 'search', placeholder: 'Filter messages…', value: st.filter });
    filter.addEventListener('input', debounce(() => { st.filter = filter.value; st.shown = 80; drawList(); }, 120));
    const list = h('div', { class: 'col', style: { padding: '12px', gap: '12px' } });
    const drawList = () => {
      const fl = st.filter.toLowerCase();
      const ms = rows.filter((r) => !fl || r.label.toLowerCase().includes(fl) || r.text.toLowerCase().includes(fl));
      mount(list, ms.slice(0, st.shown).map((r) => messageRow(r, en)), ms.length > st.shown ? h('button', { onclick: () => { st.shown += 80; drawList(); } }, `Show more (${ms.length - st.shown} left)`) : null);
    };
    mount(mainPane,
      h('div', { class: 'tabs' }, langs.map((l) => h('button', { class: l === st.lang ? 'on' : '', onclick: () => { st.lang = l; drawMain(); } }, l.toUpperCase())),
        h('div', { class: 'grow' }),
        P.buildings.length ? h('div', { class: 'row', style: { padding: '4px 8px' } }, h('span', { class: 'dim' }, 'Applies'), (() => { const s = select(variants, st.variant, (v) => { st.variant = v; drawList(); }); s.style.width = '190px'; return s; })()) : null),
      h('div', { class: 'toolbar' }, h('b', {}, st.file.replace('/Script/', '')), h('span', { class: 'dim' }, rows.length + ' messages'), h('div', { class: 'grow' }), (() => { filter.style.width = '200px'; return filter; })()),
      h('div', { class: 'toolbar', style: { gap: '4px' } }, h('span', { class: 'dim' }, 'Insert'), CODES.map(([l, c]) => h('button', { class: 'small', title: c, onclick: () => insertCode(c) }, l))),
      h('div', { style: { overflow: 'auto', flex: 1 } }, list));
    drawList();
  }

  function insertCode(c) {
    const ta = st.last; if (!ta) { toast('Click in a message first', 'info'); return; }
    const a = ta.selectionStart, b = ta.selectionEnd;
    ta.setRangeText(c, a, b, 'end'); ta.dispatchEvent(new Event('input')); ta.focus();
  }

  function messageRow(r, en) {
    const e = entry(r.label, false);
    const lang = st.lang;
    const cur = e && e.text[lang] != null ? e.text[lang] : '';
    const enText = (en.find((x) => x.label === r.label) || {}).text;
    const ta = h('textarea', { rows: Math.max(2, Math.min(8, (cur || r.text).split('\n').length)), placeholder: 'Unchanged — type to replace this message', value: cur });
    const warn = h('div', { class: 'dim', style: { fontSize: '12px' } });
    const done = h('span', { class: 'chip ok', style: { display: e && Object.values(e.text).some(Boolean) ? '' : 'none' } }, 'edited');
    const upd = () => {
      const v = ta.value;
      const en2 = entry(r.label, v !== '');
      if (en2) { if (v) en2.text[lang] = v; else delete en2.text[lang]; if (!Object.values(en2.text).some(Boolean)) P.text.splice(P.text.indexOf(en2), 1); }
      done.style.display = P.text.some((x) => x.file === st.file && x.label === r.label && (x.variant || '') === st.variant) ? '' : 'none';
      showPreview(v || r.text, r);
      checkText(v, warn);
      changed();
    };
    ta.addEventListener('input', upd);
    ta.addEventListener('focus', () => { st.last = ta; showPreview(ta.value || r.text, r); });
    return h('div', { class: 'card', 'data-label': r.label, style: { padding: '10px' } },
      h('div', { class: 'row', style: { marginBottom: '6px' } }, h('span', { class: 'chip' }, r.label), done, h('div', { class: 'grow' }),
        h('button', { class: 'small ghost', onclick: () => { ta.value = r.text; upd(); } }, 'copy original'),
        h('button', { class: 'small ghost', onclick: () => { ta.value = ''; upd(); } }, 'revert')),
      h('div', { class: 'dim', style: { fontFamily: 'var(--mono)', fontSize: '12px', whiteSpace: 'pre-wrap', marginBottom: '6px', maxHeight: '120px', overflow: 'auto' } }, r.text || '(empty)'),
      ta, warn);
  }

  const checkText = debounce(async (v, el) => {
    if (!v) { el.textContent = ''; return; }
    const r = await post('/api/text/check', { text: v });
    el.textContent = r.problems.join(' · '); el.style.color = r.problems.length ? 'var(--warm)' : '';
  }, 250);

  function showPreview(t, r) {
    mount(prevPane, h('div', { class: 'panel-title' }, 'Message window · ' + r.label), previewBoxes(t),
      h('p', { class: 'dim', style: { fontSize: '12px', marginTop: '14px' } }, `A box holds ${MAX_ROWS} lines of about ${MAX_LINE} characters; longer texts scroll. Start a new box with {0.4:}. Player and town names are counted as 8 characters.`));
  }
  mount(prevPane, h('div', { class: 'empty' }, 'Click a message to preview it as the game shows it.'));
  drawMain();
}
