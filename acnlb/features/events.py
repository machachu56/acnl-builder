"""Events: conversations of the game's characters, rewritten by you.

A conversation in the game is a *message flow* (/Script/Flow/*.msbf): a graph of messages, questions and game events,
with its lines in a text file. Which flow runs, and when, is the game's decision (the counter conversation of the secretary,
Tom Nook greeting someone who walks in, a birthday...). An event of the project picks a flow and changes what it says:

  {"id": "hello", "type": "conversation", "flow": "/Script/Flow/NPC_Secretary_Office.msbf",
   "scope": "building" | "script" | "always", "building": "baisodrome",
   "mode": "sequence", "steps": [{"text": {"en": "..."}}, ...], "goodbye": {...}
   or "mode": "rewrite", "edits": [{"label": "151", "text": {"en": "..."}}]}

scope   building: only while the player is inside that building (its RomFS variant)
        script:   only while a script switches it on:  conversation_on("hello") / conversation_off("hello")
        always:   everywhere, all the time
mode    sequence: the conversation becomes these messages. A message may end with a question: the player picks one of
                  2 to 6 answers and each answer leads on to a message of its own (or ends the conversation), like the game's
                  own menus. The flow is built anew from the messages (nodes appended to the game's flow file):
                  {"id": "m1", "text": {...}, "next": "m2" | "end" (default: the message below),
                   "choices": [{"text": {"en": "Sure!"}, "next": "m3" | "end"}, ...]}
        rewrite:  the game's own messages are replaced one by one and the conversation keeps its structure: its questions,
                  answers ("Yes!") and branches stay as the game has them

The old form {"type": "enter_talk", "building", "npc", "steps", "goodbye"} still works (a sequence inside a building).
"""
import collections
import functools
import struct

from .. import env, rom
from . import text as textmod

env.setup_path()
from modkit import msbt  # noqa: E402

# conversations worth naming (the others are listed by their file name)
FLOWS = {
    "Tanukichi": dict(talk="/Script/Talk/NPC_Tanukichi.umsbt", flow="/Script/Flow/NPC_Tanukichi_In.msbf", first=4, goodbye="001",
                      label="Tom Nook (Nook's Homes)", when="enters"),
    # Isabelle's counter conversation (the flow she runs at the town hall; its message 143 is "Well, if it isn't Mayor ...").
    "Isabelle": dict(talk="/Script/Talk/NPC_Secretary.umsbt", flow="/Script/Flow/NPC_Secretary_Office.msbf", first=4, goodbye=None,
                     label="Isabelle (the town hall counter's conversation)", when="talks"),
}
END = 0xFFFF
FLOW_DIR = "/Script/Flow/"
MIN_CHOICES, MAX_CHOICES = 2, 6
MAX_ANSWER = 24                  # characters of an answer in the game's menu (the game's longest are about 22)


def talk_for(flow):
    """the text file of a flow: the same name, or the name without its last _part (NPC_Secretary_Office -> NPC_Secretary)"""
    base = flow.rsplit("/", 1)[-1][:-5]
    while base:
        p = "/Script/Talk/%s.umsbt" % base
        if rom.exists(p):
            return p
        if "_" not in base:
            return None
        base = base.rsplit("_", 1)[0]
    return None


@functools.lru_cache(maxsize=1)
def flow_list():
    """[{flow, name, talk}] of every conversation that has a text file we can read"""
    out = []
    for p in rom.glob_prefix(FLOW_DIR, ".msbf"):
        t = talk_for(p)
        if t:
            out.append({"flow": p, "name": p.rsplit("/", 1)[-1][:-5], "talk": t})
    return out


def flow_nodes(flow, talk=None, first=None, goodbye=None):
    """[{node, label, text}] the message nodes of a flow, one per message (the node known to work first), with the game's own English text"""
    talk = talk or talk_for(flow)
    f = msbt.Flow(rom.read(flow))
    m = msbt.Msbt(msbt.umsbt_split(rom.read(talk))[0])
    by_idx = {v: k for k, v in m.labels.items()}
    nodes, seen = [], set()
    for n, i in sorted(f.message_nodes(), key=lambda x: (x[0] != first, x[0])):
        if i in by_idx and by_idx[i] not in seen and by_idx[i] != goodbye:
            seen.add(by_idx[i])
            nodes.append({"node": n, "label": by_idx[i], "text": m.text(i)})
    return nodes


def message_nodes(npc):
    """[(node, label)] of a named conversation (kept for the older API)"""
    f = FLOWS[npc]
    return [(n["node"], n["label"]) for n in flow_nodes(f["flow"], f["talk"], f["first"], f["goodbye"])]


def normalise(ev):
    """an event in the old or new form -> (flow, talk, first, goodbye label, mode)"""
    if ev.get("type") == "enter_talk":
        f = FLOWS[ev.get("npc", "Tanukichi")]
        return f["flow"], f["talk"], f["first"], f["goodbye"], "sequence"
    flow = ev.get("flow")
    named = next((v for v in FLOWS.values() if v["flow"] == flow), None)
    if named:
        return flow, named["talk"], named["first"], named["goodbye"], ev.get("mode", "sequence")
    talk = talk_for(flow) if flow else None
    if not talk:
        raise ValueError("event %s: the conversation %r is not one of the game's (or has no text file)" % (ev.get("id"), flow))
    return flow, talk, None, None, ev.get("mode", "sequence")


def compile(b):
    extra = []
    for ev in b.proj["events"]:
        if ev.get("type") not in ("enter_talk", "conversation"):
            raise ValueError("event %s: unknown type %r" % (ev.get("id"), ev.get("type")))
        flow_path, talk, first, goodbye, mode = normalise(ev)
        scope = ev.get("scope", "building")
        if scope == "building":
            bld = next((x for x in b.proj["buildings"] if x["id"] == ev.get("building")), None)
            if not bld:
                raise ValueError("event %s: the building %r does not exist" % (ev["id"], ev.get("building")))
            if not bld.get("interior"):
                b.warn("event %s: %s has no interior of its own, so the conversation would also play in the real Nook's Homes" % (ev["id"], bld["id"]))
            text_key, vname = bld["id"], "b_" + bld["id"]
        elif scope == "script":
            text_key = vname = "ev_" + ev["id"]
        elif scope == "always":
            text_key = vname = None
        else:
            raise ValueError("event %s: unknown scope %r" % (ev["id"], scope))
        if mode == "rewrite":
            for e in ev.get("edits") or []:
                if any((e.get("text") or {}).values()):
                    extra.append({"file": talk, "label": e["label"], "variant": text_key, "text": e["text"]})
            b.note("event %s: %d line(s) rewritten" % (ev["id"], len([e for e in ev.get("edits") or [] if any((e.get("text") or {}).values())])))
            continue
        steps = [st for st in ev.get("steps") or [] if st.get("action") or any((st.get("text") or {}).values())]
        if goodbye and any((ev.get("goodbye") or {}).values()):
            extra.append({"file": talk, "label": goodbye, "variant": text_key, "text": ev["goodbye"]})
        if not steps:
            continue
        slots = text_slots(flow_path, talk, first, goodbye)
        if len([st for st in steps if not st.get("action")]) > len(slots):
            raise ValueError("event %s: at most %d messages for this conversation (got %d)" % (ev["id"], len(slots), len(steps)))
        flow = FlowFile(b.game(flow_path, vname))
        for line in build_sequence(flow, ev["id"], steps, slots, extra, talk, text_key, first):
            b.warn(line)
        b.put(flow_path, flow.build(), vname)
        n_q = sum(1 for st in steps if st.get("choices"))
        b.note("event %s: %d message(s)%s" % (ev["id"], len(steps), ", %d question(s)" % n_q if n_q else ""))
    b.proj["text"] = list(b.proj["text"]) + extra


# ---------------------------------------------------------------- building a flow of your own

class FlowFile:
    """an MSBF file whose FLW3 section can grow: nodes and branch-table entries are appended after the game's own,
    so every node index (and the FEN1 entry table, which points at entry nodes) stays valid.
    A node is 16 bytes: u8 type (1 message, 2 branch, 3 event, 4 entry), u8 subtype, then u16 fields; a message has
    next at +8, its text file's id at +10 and the message index at +12; a branch has the query at +10, the number of
    cases at +12 and the first of its targets in the branch table at +14. After the branch table come the names of the
    flows that "call another flow" events (type 3, subtype 5) jump to, by their offset in FLW3 (at +4): they move
    along when the section grows."""

    def __init__(self, data):
        assert data[:8] == b"MsgFlwBn"
        self.header = bytearray(data[:0x20])
        nsec = struct.unpack_from("<H", data, 0x0E)[0]
        pos, self.sections = 0x20, []
        for _ in range(nsec):
            magic, size = data[pos:pos + 4], struct.unpack_from("<I", data, pos + 4)[0]
            self.sections.append([magic, bytes(data[pos + 0x10:pos + 0x10 + size])])
            pos = (pos + 0x10 + size + 15) & ~15
        f = self._flw()
        n, nb = struct.unpack_from("<HH", f, 0)
        self.flw_head = bytearray(f[:0x10])
        self.nodes = [bytearray(f[0x10 + i * 16:0x20 + i * 16]) for i in range(n)]
        self.table = list(struct.unpack_from("<%dH" % nb, f, 0x10 + n * 16))
        self.names_at = 0x10 + n * 16 + nb * 2
        self.names = bytes(f[self.names_at:])

    def _flw(self):
        return next(b for m, b in self.sections if m == b"FLW3")

    def message_file_id(self):
        """the id of the text file the flow's messages come from (the most common one: a few may use another file)"""
        ids = collections.Counter(struct.unpack_from("<H", nd, 10)[0] for nd in self.nodes if nd[0] == 1)
        if not ids:
            raise ValueError("this conversation has no message to copy the text file from")
        return ids.most_common(1)[0][0]

    def entry_nodes(self):
        return [i for i, nd in enumerate(self.nodes) if nd[0] == 4]

    def set_next(self, i, nxt):
        assert self.nodes[i][0] in (1, 4), self.nodes[i][0]
        struct.pack_into("<H", self.nodes[i], 8, nxt)

    def redirect(self, old, new):
        """every way into node `old` (a node's next, a branch's case) leads to `new` instead; returns how many were changed"""
        n = 0
        for nd in self.nodes:
            if nd[0] in (1, 3, 4) and struct.unpack_from("<H", nd, 8)[0] == old:
                struct.pack_into("<H", nd, 8, new)
                n += 1
        for k, t in enumerate(self.table):
            if t == old:
                self.table[k] = new
                n += 1
        return n

    def add_message(self, file_id, index, nxt=END):
        self.nodes.append(bytearray(struct.pack("<BBHHHHHHH", 1, 0xFF, 0, 0, 0, nxt, file_id, index, 0)))
        return len(self.nodes) - 1

    def add_event(self, sub, event, param, nxt=END):
        """an action of the game (a type 3 node): subtype, event number at +10, its parameter at +4"""
        self.nodes.append(bytearray(struct.pack("<BBHHHHHHH", 3, sub, 0, param & 0xFFFF, 0, nxt, event, 0, 0)))
        return len(self.nodes) - 1

    def add_choice_branch(self, targets):
        """a branch on the answer the player picked in the menu of the message before it (the game's own query for
        an n-answer menu is 2n - 1, with the answers' targets in the branch table, first answer first)"""
        n = len(targets)
        self.nodes.append(bytearray(struct.pack("<BBHHHHHHH", 2, 6, 0, 0, 0, END, 2 * n - 1, n, len(self.table))))
        self.table += list(targets)
        return len(self.nodes) - 1

    def build(self):
        if len(self.nodes) > 0xFFF0 or len(self.table) > 0xFFF0:
            raise ValueError("the conversation is too big")
        f = bytearray(self.flw_head)
        struct.pack_into("<HH", f, 0, len(self.nodes), len(self.table))
        for nd in self.nodes:
            f += nd
        f += struct.pack("<%dH" % len(self.table), *self.table)
        moved = len(f) - self.names_at
        for i in range(len(self.nodes)):                     # the flow-name references follow the names
            nd = f[0x10 + i * 16:0x20 + i * 16]
            if nd[0] == 3 and nd[1] == 5:
                struct.pack_into("<H", f, 0x10 + i * 16 + 4, struct.unpack_from("<H", nd, 4)[0] + moved)
        f += self.names
        out = bytearray(self.header)
        for magic, body in self.sections:
            if magic == b"FLW3":
                body = bytes(f)
            out += magic + struct.pack("<I", len(body)) + bytes(8) + body
            while len(out) % 16:
                out.append(0xAB)
        struct.pack_into("<I", out, 0x12, len(out))
        return bytes(out)


def choice_code(n):
    """the control code that opens the answer menu of a message: {15.<n + 3>:} with one u16 per answer"""
    return "{15.%d:%s}" % (n + 3, "0000" * n)


@functools.lru_cache(maxsize=64)
def _labels(talk):
    m = msbt.Msbt(msbt.umsbt_split(rom.read(talk))[0])
    return sorted(m.labels, key=lambda k: m.labels[k]), dict(m.labels)


def text_slots(flow, talk, first=None, goodbye=None):
    """[(label, index)] of the messages of the conversation's text file that can hold your lines: the ones this
    conversation shows first (known to work), then every other line of the file (they belong to the same character)"""
    order, idx = _labels(talk)
    out, seen = [], {goodbye}
    for n in flow_nodes(flow, talk, first, goodbye):
        if n["label"] not in seen:
            seen.add(n["label"])
            out.append((n["label"], idx[n["label"]]))
    for lab in order:
        if lab not in seen:
            seen.add(lab)
            out.append((lab, idx[lab]))
    return out


def build_sequence(flow, ev_id, steps, slots, extra, talk, text_key, first=None):
    """the steps as new nodes of `flow` (the conversation's entries lead to the first); their texts go into `extra`
    (text edits of `talk`). Returns warnings."""
    warns = []
    ids = {}
    for k, st in enumerate(steps):
        sid = st.get("id") or "m%d" % (k + 1)
        if sid in ids:
            raise ValueError("event %s: two messages are called %s" % (ev_id, sid))
        ids[sid] = k
    fid = flow.message_file_id()
    first_node = len(flow.nodes)
    msg_nodes = [first_node + k for k in range(len(steps))]
    slot_of, n = {}, 0
    for k, st in enumerate(steps):
        if st.get("action"):                     # a game action: {"sub": 1, "event": 7, "param": 0}
            a = st["action"]
            flow.add_event(int(a.get("sub", 0)), int(a["event"]), int(a.get("param", 0)))
        else:
            flow.add_message(fid, slots[n][1])
            slot_of[k] = slots[n]
            n += 1

    def target(nxt, k, what):
        """a step's (or an answer's) next: "end", a message id, or nothing = the message below"""
        if nxt == "end":
            return END
        if not nxt:
            return msg_nodes[k + 1] if k + 1 < len(steps) else END
        if nxt not in ids:
            raise ValueError("event %s: %s leads to message %r, which does not exist" % (ev_id, what, nxt))
        return msg_nodes[ids[nxt]]

    for k, st in enumerate(steps):
        sid = st.get("id") or "m%d" % (k + 1)
        if st.get("action"):                     # an action goes on with the next step (or where it says)
            struct.pack_into("<H", flow.nodes[msg_nodes[k]], 8, target(st.get("next"), k, "action %s" % sid))
            continue
        text = dict(st["text"])
        choices = [c for c in st.get("choices") or [] if any((c.get("text") or {}).values())]
        if choices:
            if not MIN_CHOICES <= len(choices) <= MAX_CHOICES:
                raise ValueError("event %s, message %s: a question has %d to %d answers (has %d)" % (ev_id, sid, MIN_CHOICES, MAX_CHOICES, len(choices)))
            langs = set(text) | {l for c in choices for l in (c.get("text") or {})}
            for lang in langs:
                q = text.get(lang) or text.get("en") or ""
                answers = [(c["text"].get(lang) or c["text"].get("en") or next(iter(c["text"].values()))).replace("\n", " ") for c in choices]
                for a in answers:
                    if len(textmod.CODE.sub("", a)) > MAX_ANSWER:
                        warns.append("event %s, message %s [%s]: the answer %r is long for the game's menu (over %d characters)" % (ev_id, sid, lang, a, MAX_ANSWER))
                text[lang] = q + choice_code(len(choices)) + "".join("\n" + a for a in answers)
            br = flow.add_choice_branch([target(c.get("next") or "end", k, "an answer of %s" % sid) for c in choices])
            flow.set_next(msg_nodes[k], br)
        else:
            flow.set_next(msg_nodes[k], target(st.get("next"), k, "message %s" % sid))
        extra.append({"file": talk, "label": slot_of[k][0], "variant": text_key, "text": text})
    # the conversation starts with the first message: where the game's own first message was (its other branches stay, e.g. Tom Nook's
    # goodbye when the player leaves, which makes the player leave), or else from every entry
    if first is None or not flow.redirect(first, first_node):
        for e in flow.entry_nodes():
            flow.set_next(e, first_node)
    return warns


def quiet_flow(data, first):
    """a copy of a flow whose branch to its first message ends at once (the greeting of the host when the player arrives from another
    room of the building); its other branches (the goodbye) stay"""
    f = FlowFile(data)
    f.redirect(first, END)
    return f.build()
