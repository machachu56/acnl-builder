import { get } from './api.js';
import { S, on, openProject, saveNow } from './state.js';
import { h, mount, toast, select } from './ui.js';
import * as home from './panels/home.js';
import * as dialogue from './panels/dialogue.js';
import * as villagers from './panels/villagers.js';
import * as textures from './panels/textures.js';
import * as buildings from './panels/buildings.js';
import * as interiors from './panels/interiors.js';
import * as objects from './panels/objects.js';
import * as events from './panels/events.js';
import * as scripts from './panels/scripts.js';
import * as exportp from './panels/export.js';

const PANELS = [home, { sep: true }, dialogue, villagers, textures, { sep: true }, buildings, interiors, objects, events, scripts, { sep: true }, exportp];
let current = null, cleanup = null;

export const app = {
  go(id) { if (location.hash === '#' + id) render(); else location.hash = '#' + id; },
  status: null,
  refresh() { render(); },
};
window.app = app;

function counts() {
  const p = S.project;
  if (!p) return {};
  return { dialogue: p.text.length, villagers: p.villagers.length, textures: p.textures.length, buildings: p.buildings.length, interiors: p.interiors.length, objects: (p.objects || []).length, events: p.events.length, scripts: (p.scripts || []).length };
}

function renderNav() {
  const c = counts();
  mount(document.getElementById('nav'), PANELS.map((p) => {
    if (p.sep) return h('div', { class: 'sep' });
    return h('button', { class: p.id === current ? 'on' : '', disabled: p.needsProject && !S.project, onclick: () => app.go(p.id) },
      h('span', {}, p.icon), p.title, c[p.id] ? h('span', { class: 'count' }, c[p.id]) : null);
  }));
}

function renderProjectBar() {
  const bar = document.getElementById('projectbar');
  if (!app.status) return;
  const opts = [['', S.project ? S.project.title : 'Open a project…'], ...app.status.projects.map((p) => [p.id, p.title])];
  const sel = select(opts, S.pid || '', async (v) => { if (v) { await openProject(v); render(); } });
  sel.style.width = '220px';
  mount(bar, h('div', { class: 'row' }, h('span', { class: 'dim' }, 'Project'), sel));
  const st = document.getElementById('savestate');
  st.textContent = S.error ? 'save failed: ' + S.error : S.saving ? 'saving…' : S.project ? (S.dirty ? 'unsaved' : 'saved') : '';
  st.style.color = S.error ? 'var(--danger)' : '';
}

function render() {
  const id = (location.hash || '#home').slice(1);
  const panel = PANELS.find((p) => p.id === id) || home;
  if (panel.needsProject && !S.project) { console.warn('no project, going home from', id); location.hash = '#home'; return; }
  if (cleanup) { try { cleanup(); } catch (e) { console.error(e); } cleanup = null; }
  current = panel.id;
  renderNav(); renderProjectBar();
  const root = h('div', { class: 'page' });
  mount(document.getElementById('main'), root);
  try { cleanup = panel.render(root, app) || null; } catch (e) { console.error(e); mount(root, h('div', { class: 'err-box', style: { margin: '20px' } }, 'This panel failed: ' + e.message)); }
}

on(() => { renderNav(); renderProjectBar(); });
let ready = false;
window.addEventListener('hashchange', () => { if (ready) render(); });
document.getElementById('btn-export').addEventListener('click', () => { if (S.project) app.go('export'); else toast('Open a project first', 'error'); });
window.addEventListener('beforeunload', () => { if (S.dirty) saveNow(); });

(async () => {
  app.status = await get('/api/status');
  const last = (() => { try { return localStorage.getItem('acnlb.project'); } catch (e) { return null; } })();
  if (last && app.status.projects.some((p) => p.id === last)) await openProject(last).catch(() => {});
  ready = true;
  render();
})();
