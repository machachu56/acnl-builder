import { get, put } from './api.js';
import { debounce } from './ui.js';

// the open project and its autosave
export const S = { pid: null, project: null, saving: false, error: null, listeners: new Set(), status: null };

export function on(fn) { S.listeners.add(fn); return () => S.listeners.delete(fn); }
export function emit() { for (const f of S.listeners) f(); }

const flush = debounce(async () => {
  if (!S.project) return;
  S.saving = true; S.error = null; emit();
  try { await put('/api/project/' + S.pid, S.project); }
  catch (e) { S.error = e.message; }
  S.saving = false; S.dirty = false; emit();
}, 700);

export function changed() { S.dirty = true; emit(); flush(); }
export const saveNow = () => flush.now();

export async function openProject(pid) {
  if (S.project && S.dirty) await saveNow();
  S.project = await get('/api/project/' + pid);
  S.pid = pid;
  try { localStorage.setItem('acnlb.project', pid); } catch (e) { /* private mode */ }
  emit();
}
export function closeProject() { S.project = null; S.pid = null; emit(); }

// ---- helpers over project lists
export function findOrAdd(list, pred, make) {
  let e = list.find(pred);
  if (!e) { e = make(); list.push(e); }
  return e;
}
export const uid = (prefix, existing) => {
  let n = 1; const ids = new Set(existing.map((x) => x.id));
  while (ids.has(prefix + n)) n++;
  return prefix + n;
};
window.S = S;
