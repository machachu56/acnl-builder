export async function api(method, url, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) {
    if (body instanceof Blob || body instanceof ArrayBuffer) { opt.body = body; }
    else { opt.body = JSON.stringify(body); opt.headers['Content-Type'] = 'application/json'; }
  }
  const r = await fetch(url, opt);
  const ct = r.headers.get('Content-Type') || '';
  const data = ct.includes('json') ? await r.json() : await r.blob();
  if (!r.ok) throw new Error((data && data.error) || r.statusText);
  return data;
}
export const get = (u) => api('GET', u);
export const post = (u, b) => api('POST', u, b ?? {});
export const put = (u, b) => api('PUT', u, b);
export const del = (u) => api('DELETE', u);
export const q = (obj) => Object.entries(obj).filter(([, v]) => v !== undefined && v !== '').map(([k, v]) => k + '=' + encodeURIComponent(v)).join('&');

export async function pollJob(job, onTick) {
  for (;;) {
    const j = await get('/api/job/' + job);
    if (j.state === 'done') return j.result;
    if (j.state === 'error') throw new Error(j.error);
    if (onTick) onTick();
    await new Promise((r) => setTimeout(r, 400));
  }
}
