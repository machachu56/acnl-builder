// RAW text of a conversation (Events, "My own conversation"): one language at a time, readable by people and by an AI, and read back
// into the same steps. The other languages of a step are kept when its id stays the same.
//
//   [m1]                       a message: its id, then its text (codes as {g.t:…}, {0.4:} starts a new box)
//   text…
//   > An answer -> m2          the player's answers (2 to 6), each with where it leads
//   -> m3                      where the message leads (default: the step below; "end" ends the conversation)
//   [c1] CHARGE 500 -> m4      takes 500 Bells from the player
//   [k1] IF BELLS >= 500 -> c1 ELSE -> m3     enough / not enough
//   [a1] ACTION 0/1 100 -> m2  any action of the game (subtype/event parameter)

const HEAD = /^\[([A-Za-z0-9_]+)\]\s*(.*)$/;
const TARGET = /^->\s*([A-Za-z0-9_]+)\s*$/;
const ANSWER = /^>\s*(.*?)\s*->\s*([A-Za-z0-9_]+)\s*$/;

export function toRaw(steps, lang) {
  const out = [];
  const txt = (t) => (t && (t[lang] ?? t.en)) || '';
  for (const s of steps) {
    const to = (n) => (n ? ' -> ' + n : '');
    if ('charge' in s) out.push('[' + s.id + '] CHARGE ' + s.charge + to(s.next));
    else if ('has_bells' in s) out.push('[' + s.id + '] IF BELLS >= ' + s.has_bells + ' -> ' + (s.next || 'next') + ' ELSE -> ' + (s.else || 'end'));
    else if (s.action) out.push('[' + s.id + '] ACTION ' + (s.action.sub || 0) + '/' + s.action.event + ' ' + (s.action.param || 0) + to(s.next));
    else {
      out.push('[' + s.id + ']');
      out.push(txt(s.text));
      for (const c of s.choices || []) out.push('> ' + txt(c.text).replace(/\n/g, ' ') + ' -> ' + (c.next || 'end'));
      if (s.next && !(s.choices || []).length) out.push('-> ' + s.next);
    }
    out.push('');
  }
  return out.join('\n').replace(/\n+$/, '\n');
}

// -> { steps, errors }. `old` are the current steps: their other languages are kept (matched by id, answers by position)
export function fromRaw(raw, old, lang) {
  const errors = [], steps = [], byId = Object.fromEntries((old || []).map((s) => [s.id, s]));
  const lines = raw.replace(/\r/g, '').split('\n');
  let cur = null, body = [];
  const keep = (prev, key) => Object.assign({}, (prev && prev[key]) || {});
  const flush = () => {
    if (!cur || cur.kind !== 'message') return;
    while (body.length && !body[body.length - 1].trim()) body.pop();
    while (body.length && !body[0].trim()) body.shift();
    const prev = byId[cur.s.id], text = keep(prev, 'text');
    text[lang] = body.join('\n');
    cur.s.text = text;
    if (!body.join('').trim()) errors.push('[' + cur.s.id + '] has no text');
    if (cur.s.choices) {
      if (cur.s.choices.length < 2 || cur.s.choices.length > 6) errors.push('[' + cur.s.id + '] a question has 2 to 6 answers (has ' + cur.s.choices.length + ')');
      cur.s.choices.forEach((c, k) => { const pc = prev && (prev.choices || [])[k]; const t = Object.assign({}, (pc && pc.text) || {}); t[lang] = c.text; c.text = t; });
      delete cur.s.next;
    }
  };
  lines.forEach((line, n) => {
    const at = 'line ' + (n + 1) + ': ';
    const hm = HEAD.exec(line.trim());
    if (hm) {
      flush(); body = [];
      const id = hm[1], rest = hm[2].trim();
      if (steps.some((x) => x.id === id)) errors.push(at + 'the id [' + id + '] is used twice');
      let m;
      if (!rest) { cur = { kind: 'message', s: { id } }; steps.push(cur.s); return; }
      if ((m = /^CHARGE\s+(\d+)\s*(?:->\s*([A-Za-z0-9_]+))?$/i.exec(rest))) { const s = { id, charge: +m[1] }; if (m[2]) s.next = m[2]; steps.push(s); cur = { kind: 'charge', s }; return; }
      if ((m = /^IF\s+BELLS\s*>=\s*(\d+)\s*->\s*([A-Za-z0-9_]+)\s+ELSE\s*->\s*([A-Za-z0-9_]+)$/i.exec(rest))) {
        const s = { id, has_bells: +m[1], else: m[3] }; if (m[2] !== 'next') s.next = m[2]; steps.push(s); cur = { kind: 'check', s }; return;
      }
      if ((m = /^ACTION\s+(\d+)\/(\d+)\s+(\d+)\s*(?:->\s*([A-Za-z0-9_]+))?$/i.exec(rest))) { const s = { id, action: { sub: +m[1], event: +m[2], param: +m[3] } }; if (m[4]) s.next = m[4]; steps.push(s); cur = { kind: 'action', s }; return; }
      errors.push(at + 'I do not understand "' + rest + '" (CHARGE n, IF BELLS >= n -> x ELSE -> y, or ACTION a/b n)'); cur = null; return;
    }
    if (!cur) { if (line.trim()) errors.push(at + 'text before the first [id]'); return; }
    if (cur.kind !== 'message') { if (line.trim()) errors.push(at + '[' + cur.s.id + '] is not a message: text cannot follow it'); return; }
    let m;
    if ((m = ANSWER.exec(line.trim()))) { (cur.s.choices = cur.s.choices || []).push({ text: m[1], next: m[2] }); return; }
    if ((m = TARGET.exec(line.trim()))) { cur.s.next = m[1]; return; }
    if (cur.s.choices || cur.s.next) { if (line.trim()) errors.push(at + 'text after the answers / "->" of [' + cur.s.id + ']'); return; }
    body.push(line.replace(/\s+$/, ''));
  });
  flush();
  const ids = new Set(steps.map((s) => s.id));
  const check = (t, where) => { if (t && t !== 'end' && t !== 'next' && !ids.has(t)) errors.push(where + ' leads to [' + t + '], which does not exist'); };
  for (const s of steps) {
    check(s.next, '[' + s.id + ']'); check(s.else, '[' + s.id + '] ELSE');
    for (const c of s.choices || []) check(c.next, '[' + s.id + '] answer "' + c.text[lang] + '"');
    if (s.next === 'next') delete s.next;
  }
  if (!steps.length) errors.push('no steps: start a step with [m1]');
  return { steps, errors };
}

// what to give an AI along with the conversation, so it writes back the same format
export function rawGuide(reactions) {
  return `FORMAT OF THIS CONVERSATION (keep it exactly; I paste your answer back into a game editor)

[m1]
{3.32:}Welcome to my little shop,
{5.0:}!{0.4:}{3.23:}Want a lucky charm?
It's only 500 Bells.
> Yes, please! -> k1
> No, thanks. -> m4

[k1] IF BELLS >= 500 -> c1 ELSE -> m3

[c1] CHARGE 500 -> m2

[m2]
{3.3:}Thank you! Here you go!
-> end

[m3]
{3.9:}Oh... You don't have
enough Bells, hm?
-> end

[m4]
{3.1:}Come back anytime!

RULES
- A step starts with [id] on its own line (letters, digits, _). Keep the ids you were given; new steps need new ids.
- A message's text follows its [id]. A text box has at most 3 lines of at most 34 characters ({5.0:} and {5.5:} count as 8).
  {0.4:} starts a new box. Keep every {…} code exactly as written.
- "> answer -> id" lines are the player's answers: 2 to 6, at most 24 characters each, each leading to a step id or "end".
- "-> id" after a message says where it goes next (without it: the step below; "-> end" ends the conversation).
- [id] CHARGE n -> id          takes n Bells from the player.
- [id] IF BELLS >= n -> id ELSE -> id    goes on if the player has at least n Bells, else to the other step. Check before you charge.
- [id] ACTION a/b n -> id      an action of the game: keep these lines as they are.
- Codes: {5.0:} player's name, {5.5:} town's name, {0.3:0200}word{0.3:ffff} highlights a word,
  {7.0:0a000000} a short pause. {3.n:} makes the speaker react from that point on:
${reactions.map(([n, name]) => '  {3.' + n + ':} ' + name).join('\n')}
- Answer with the whole conversation in this format and nothing else.`;
}
