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
mode    sequence: the conversation becomes these messages, one after the other, then it ends
        rewrite:  the game's own messages are replaced one by one and the conversation keeps its structure: its questions,
                  answers ("Yes!") and branches stay as the game has them

The old form {"type": "enter_talk", "building", "npc", "steps", "goodbye"} still works (a sequence inside a building).
"""
import functools

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
        nodes = [(n["node"], n["label"]) for n in flow_nodes(flow_path, talk, first, goodbye)]
        steps = [s for s in ev.get("steps") or [] if any((s.get("text") or {}).values())]
        if goodbye and any((ev.get("goodbye") or {}).values()):
            extra.append({"file": talk, "label": goodbye, "variant": text_key, "text": ev["goodbye"]})
        if not steps:
            continue
        if len(steps) > len(nodes):
            raise ValueError("event %s: at most %d messages for this conversation (got %d)" % (ev["id"], len(nodes), len(steps)))
        flow = msbt.Flow(b.game(flow_path, vname))
        flow.set_next(0, nodes[0][0])
        for k, step in enumerate(steps):
            node, label = nodes[k]
            extra.append({"file": talk, "label": label, "variant": text_key, "text": step["text"]})
            flow.set_next(node, nodes[k + 1][0] if k + 1 < len(steps) else END)
        b.put(flow_path, flow.build(), vname)
        b.note("event %s: %d message(s)" % (ev["id"], len(steps)))
    b.proj["text"] = list(b.proj["text"]) + extra
