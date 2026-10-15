// tiny DOM helpers shared by every panel
export function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on')) el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'value') el.value = v;
    else if (k === 'checked' || k === 'disabled' || k === 'selected') el[k] = !!v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  append(el, kids);
  return el;
}
function append(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k == null || k === false) continue;
    el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
}
export const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };
export const mount = (el, ...kids) => { clear(el); append(el, kids); return el; };

export function toast(msg, kind = 'info', ms = 3500) {
  const t = h('div', { class: 'toast ' + kind }, msg);
  document.getElementById('toasts').append(t);
  setTimeout(() => t.remove(), kind === 'error' ? Math.max(ms, 7000) : ms);
}

export function modal(title, body, actions) {
  return new Promise((resolve) => {
    const close = (v) => { bg.remove(); resolve(v); };
    const bg = h('div', { class: 'modal-bg', onmousedown: (e) => { if (e.target === bg) close(null); } },
      h('div', { class: 'modal', role: 'dialog' }, h('h2', {}, title), body,
        h('div', { class: 'actions' }, (actions || [{ label: 'OK', value: true, primary: true }]).map((a) =>
          h('button', { class: a.primary ? 'primary' : '', onclick: () => close(typeof a.value === 'function' ? a.value() : a.value) }, a.label)))));
    document.body.append(bg);
    const f = bg.querySelector('input,textarea,select'); if (f) f.focus();
  });
}
export async function confirmBox(msg, label = 'OK') {
  return (await modal('Please confirm', h('p', {}, msg), [{ label: 'Cancel', value: false }, { label, value: true, primary: true }])) === true;
}
export async function prompt(title, label, value = '') {
  const input = h('input', { type: 'text', value });
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') input.closest('.modal-bg').querySelector('button.primary').click(); });
  const r = await modal(title, h('label', { class: 'field' }, h('span', {}, label), input),
    [{ label: 'Cancel', value: null }, { label: 'OK', value: () => input.value, primary: true }]);
  return r;
}

export function field(label, control, hint) {
  return h('label', { class: 'field' }, h('span', {}, label), control, hint ? h('span', { class: 'dim', style: { fontSize: '11px' } }, hint) : null);
}
export function textInput(value, onchange, props = {}) {
  const i = h('input', { type: 'text', value: value ?? '', ...props });
  i.addEventListener('input', () => onchange(i.value));
  return i;
}
export function numInput(value, onchange, props = {}) {
  const i = h('input', { type: 'number', value: value ?? '', ...props });
  i.addEventListener('input', () => { if (i.value !== '') onchange(Number(i.value)); });
  return i;
}
export function select(options, value, onchange) {
  const s = h('select', {}, options.map((o) => {
    const [v, l] = Array.isArray(o) ? o : [o, o];
    return h('option', { value: v, selected: String(v) === String(value) }, l);
  }));
  s.addEventListener('change', () => onchange(s.value));
  return s;
}
export function colorInput(value, onchange) {
  const i = h('input', { type: 'color', value: /^#[0-9a-f]{6}$/i.test(value) ? value : '#808080' });
  i.addEventListener('input', () => onchange(i.value));
  return i;
}
export function checkbox(value, onchange, label) {
  const i = h('input', { type: 'checkbox', checked: !!value });
  i.addEventListener('change', () => onchange(i.checked));
  return h('label', { class: 'row', style: { gap: '6px', cursor: 'pointer' } }, i, label);
}
export function slider(value, min, max, step, onchange) {
  const out = h('span', { class: 'dim', style: { minWidth: '34px', textAlign: 'right' } }, String(value));
  const i = h('input', { type: 'range', min, max, step, value });
  i.addEventListener('input', () => { out.textContent = i.value; onchange(Number(i.value)); });
  return h('div', { class: 'row' }, i, out);
}
export function debounce(fn, ms) {
  let t; const d = (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; d.now = (...a) => { clearTimeout(t); return fn(...a); }; return d;
}
export function download(name, blob) {
  const a = h('a', { href: URL.createObjectURL(blob), download: name });
  document.body.append(a); a.click(); a.remove();
}
export function pickFile(accept) {
  return new Promise((resolve) => {
    const i = h('input', { type: 'file', accept, style: { display: 'none' } });
    i.addEventListener('change', () => resolve(i.files[0] || null));
    document.body.append(i); i.click(); setTimeout(() => i.remove(), 60000);
  });
}
export function loadImage(src) {
  return new Promise((res, rej) => { const im = new Image(); im.onload = () => res(im); im.onerror = rej; im.src = src; });
}
