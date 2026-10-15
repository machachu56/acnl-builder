import { post, get, pollJob } from '../api.js';
import { S, saveNow } from '../state.js';
import { h, mount, toast } from '../ui.js';

export const id = 'export', title = 'Export', icon = '⬇', needsProject = true;

export function render(root, app) {
  const P = S.project;
  const body = h('div', { class: 'pane pad', style: { maxWidth: '860px', margin: '0 auto', width: '100%' } });
  mount(root, h('div', { class: 'page-head' }, h('h2', {}, 'Export'), h('p', {}, 'Build the .acmod from your project and your own game dump')), body);
  const needsPlugin = P.buildings.length || P.events.length;
  const lines = [
    ['Dialogue & text edits', P.text.length], ['Villagers', P.villagers.length], ['Texture edits', P.textures.length],
    ['Buildings', P.buildings.length], ['Interiors', P.interiors.length], ['Events', P.events.length],
  ];
  const out = h('div', {});
  const draw = (state) => mount(body,
    h('div', { class: 'card' }, h('h3', {}, P.title), h('div', { class: 'grid3' }, lines.map(([l, n]) => h('div', {}, h('div', { style: { fontSize: '22px', fontWeight: 650 } }, n), h('div', { class: 'dim' }, l)))),
      needsPlugin ? h('p', { class: 'dim', style: { marginBottom: 0 } }, 'Buildings and events need the runtime plugin (WebAssembly): it is compiled automatically on the first export.') : null),
    h('div', { class: 'row', style: { margin: '14px 0' } },
      h('button', { class: 'primary', disabled: state === 'busy', onclick: () => run(false) }, state === 'busy' ? 'Building…' : 'Build .acmod'),
      h('button', { disabled: state === 'busy', onclick: () => run(true) }, 'Build and install into the game'),
      app.status.toolchain.game ? h('button', { disabled: state === 'busy', onclick: () => run(true, true) }, 'Install and play') : null,
      h('span', { class: 'dim' }, 'Installs to ', h('span', { class: 'kbd' }, app.status.install_dir))),
    out);
  async function run(install, play) {
    draw('busy'); mount(out, h('div', { class: 'info-box' }, 'Building… this can take a little while the first time (textures are encoded and cached).'));
    try {
      await saveNow();
      const { job } = await post(`/api/project/${S.pid}/export`, { install });
      const r = await pollJob(job);
      draw('idle');
      if (play) { try { await post('/api/launch', {}); toast('Starting the game…', 'ok'); } catch (e) { toast(e.message, 'error'); } }
      mount(out, h('div', { class: 'card', style: { borderColor: 'var(--ok)' } }, h('h3', { style: { color: 'var(--ok)' } }, 'Done'),
        h('div', {}, h('span', { class: 'kbd' }, r.path)), h('div', { class: 'dim', style: { marginTop: '4px' } }, r.files + ' files · ' + (r.bytes / 1024).toFixed(0) + ' KiB'),
        r.installed ? h('div', { style: { marginTop: '8px' } }, 'Installed: ', h('span', { class: 'kbd' }, r.installed), h('div', { class: 'dim' }, 'Restart the game to load it.')) : h('div', { class: 'dim', style: { marginTop: '8px' } }, 'Copy it into the game’s mods folder (or use “Build and install”). The same file works on Windows, Linux and Android.'),
        r.warnings.length ? h('div', { style: { marginTop: '10px' } }, h('h3', {}, 'Warnings'), r.warnings.map((w) => h('div', { class: 'warn-box', style: { marginBottom: '4px' } }, w))) : null,
        r.log.length ? h('details', { style: { marginTop: '10px' } }, h('summary', {}, 'Build log'), h('pre', { style: { fontSize: '12px', color: 'var(--dim)' } }, r.log.join('\n'))) : null));
    } catch (e) { draw('idle'); mount(out, h('div', { class: 'err-box' }, h('b', {}, 'Build failed. '), h('pre', { style: { whiteSpace: 'pre-wrap', margin: '6px 0 0', font: '12px var(--mono)' } }, e.message))); }
  }
  draw('idle');
}
