import { get, post, del } from '../api.js';
import { S, openProject, closeProject, changed } from '../state.js';
import { h, mount, toast, prompt, confirmBox, field, textInput } from '../ui.js';

export const id = 'home', title = 'Project', icon = '◆', needsProject = false;

export function render(root, app) {
  const view = h('div', { class: 'pane pad', style: { maxWidth: '980px', margin: '0 auto', width: '100%' } });
  mount(root, h('div', { class: 'page-head' }, h('h2', {}, 'ACNL Builder'), h('p', {}, 'Design mods for Animal Crossing: New Leaf (recomp) and export them as .acmod')), view);

  const draw = async () => {
    const st = await get('/api/status'); app.status = st;
    const tc = st.toolchain;
    const check = (ok, label, fix) => h('div', { class: 'row' }, h('span', { class: 'chip ' + (ok ? 'ok' : 'err') }, ok ? 'ready' : 'missing'), h('span', {}, label), !ok && fix ? h('span', { class: 'dim' }, fix) : null);
    const desc = h('textarea', { rows: 3 }, S.project ? S.project.description || '' : '');
    desc.addEventListener('input', () => { S.project.description = desc.value; changed(); });
    mount(view,
      h('div', { class: 'grid2' },
        h('div', { class: 'card' }, h('h3', {}, 'Projects'),
          h('div', { class: 'list' }, st.projects.length ? st.projects.map((p) => h('div', { class: 'item' + (p.id === S.pid ? ' on' : ''), onclick: async () => { await openProject(p.id); draw(); } },
            h('b', {}, p.title), h('span', { class: 'dim' }, p.id), h('span', { class: 'sub' },
              h('button', { class: 'small ghost', onclick: async (e) => { e.stopPropagation(); const nid = await prompt('Duplicate project', 'New project id (lowercase, digits, _)', p.id + '_2'); if (nid) { try { await post('/api/projects', { id: nid, copy_of: p.id }); await openProject(nid); draw(); } catch (er) { toast(er.message, 'error'); } } } }, 'duplicate'),
              h('button', { class: 'small ghost danger', onclick: async (e) => { e.stopPropagation(); if (await confirmBox('Delete project "' + p.title + '" and its images? This cannot be undone.', 'Delete')) { await del('/api/project/' + p.id); if (S.pid === p.id) closeProject(); draw(); } } }, 'delete')))) : h('div', { class: 'empty' }, 'No project yet.')),
          h('div', { class: 'row', style: { marginTop: '10px' } }, h('button', { class: 'primary', onclick: async () => {
            const nid = await prompt('New project', 'Project id (lowercase letters, digits, _)', 'my_mod'); if (!nid) return;
            const title = await prompt('New project', 'Title', nid); if (title == null) return;
            try { await post('/api/projects', { id: nid, title }); await openProject(nid); draw(); app.go('dialogue'); } catch (er) { toast(er.message, 'error'); }
          } }, 'New project'))),
        h('div', { class: 'card' }, h('h3', {}, 'This computer'),
          h('div', { class: 'col' },
            check(!!tc.rom, 'Game dump (decrypted .3ds)', 'set ACNL_ROM or put acnl.3ds next to the repositories'),
            check(!!tc.recomp, 'Recomp checkout (modkit, SDK)', 'set ACNL_RECOMP'),
            check(!!tc.clang && !!tc.wasm_ld, 'WebAssembly toolchain (clang + wasm-ld)', 'needed to export buildings: install clang and lld'),
            h('div', { class: 'dim', style: { fontSize: '12px' } }, 'Mods go in ', h('span', { class: 'kbd' }, st.install_dir))))),
      S.project ? h('div', { class: 'card', style: { marginTop: '14px' } }, h('h3', {}, 'About this mod'),
        h('div', { class: 'grid2' },
          field('Title', textInput(S.project.title, (v) => { S.project.title = v; changed(); })),
          field('Author', textInput(S.project.author, (v) => { S.project.author = v; changed(); }))),
        h('div', { style: { marginTop: '10px' } }, field('Description', desc))) : null,
      h('div', { class: 'card', style: { marginTop: '14px' } }, h('h3', {}, 'How it works'),
        h('ol', { style: { margin: 0, paddingLeft: '20px', lineHeight: '1.8' } },
          h('li', {}, 'Pick what to change: ', h('b', {}, 'Dialogue'), ' (what anyone says), ', h('b', {}, 'Villagers'), ', ', h('b', {}, 'Textures'), ' (clothes, skins, furniture), ', h('b', {}, 'Buildings'), ' with their ', h('b', {}, 'Interiors'), ', and ', h('b', {}, 'Events'), '.'),
          h('li', {}, 'Everything autosaves in ', h('span', { class: 'kbd' }, 'projects/' + (S.pid || '<id>')), '.'),
          h('li', {}, h('b', {}, 'Export'), ' builds the .acmod from your own game dump; nothing from the game is shipped inside it unless you edited it.'))));
  };
  draw();
}
