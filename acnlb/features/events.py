"""Events: scripted conversations (Tom Nook when the player walks in; Isabelle when the player talks to her).

{"id": "welcome", "type": "enter_talk", "building": "baisodrome", "npc": "Tanukichi",
 "steps": [{"text": {"en": "...", "fr": "..."}}, ...], "goodbye": {"en": "..."}}

`enter_talk`: when the player walks into the building, the character inside says these messages in order, then
the conversation ends. It re-uses the message nodes of the character's "entering" flow (the game's script), so a
conversation can have as many boxes as that flow has message nodes (see FLOWS); each step becomes the text of
one node's message, only while inside that building.
"""
from .. import env, rom
from . import text as textmod

env.setup_path()
from modkit import msbt  # noqa: E402

FLOWS = {
    "Tanukichi": dict(talk="/Script/Talk/NPC_Tanukichi.umsbt", flow="/Script/Flow/NPC_Tanukichi_In.msbf", first=4, goodbye="001",
                      label="Tom Nook (Nook's Homes)", when="enters"),
    # Isabelle's counter conversation (the flow she runs at the town hall; its message 143 is "Well, if it isn't Mayor ...").
    # In your building it plays when the player talks to her there (needs her to stand there: Interiors > Characters).
    "Isabelle": dict(talk="/Script/Talk/NPC_Secretary.umsbt", flow="/Script/Flow/NPC_Secretary_Office.msbf", first=4, goodbye=None,
                     label="Isabelle (the town hall counter's conversation)", when="talks"),
}
END = 0xFFFF


def message_nodes(npc):
    """[(node, label)] of the entering flow, the node known to work first"""
    f = FLOWS[npc]
    flow = msbt.Flow(rom.read(f["flow"]))
    m = msbt.Msbt(msbt.umsbt_split(rom.read(f["talk"]))[0])
    by_idx = {v: k for k, v in m.labels.items()}
    nodes, seen = [], set()
    for n, i in sorted(flow.message_nodes(), key=lambda x: (x[0] != f["first"], x[0])):
        if i in by_idx and by_idx[i] not in seen and by_idx[i] != f["goodbye"]:   # one node per message
            seen.add(by_idx[i])
            nodes.append((n, by_idx[i]))
    return nodes


def compile(b):
    extra = []
    for ev in b.proj["events"]:
        if ev.get("type") != "enter_talk":
            raise ValueError("event %s: unknown type %r" % (ev.get("id"), ev.get("type")))
        bld = next((x for x in b.proj["buildings"] if x["id"] == ev["building"]), None)
        if not bld:
            raise ValueError("event %s: the building %r does not exist" % (ev["id"], ev["building"]))
        if not bld.get("interior"):
            b.warn("event %s: %s has no interior of its own, so the speech would also play in the real Nook's Homes" % (ev["id"], bld["id"]))
        npc = ev.get("npc", "Tanukichi")
        f = FLOWS[npc]
        nodes = message_nodes(npc)
        steps = [s for s in ev["steps"] if any((s.get("text") or {}).values())]
        if f["goodbye"] and any((ev.get("goodbye") or {}).values()):
            extra.append({"file": f["talk"], "label": f["goodbye"], "variant": bld["id"], "text": ev["goodbye"]})
        if not steps:
            continue
        if len(steps) > len(nodes):
            raise ValueError("event %s: at most %d messages for %s (got %d)" % (ev["id"], len(nodes), npc, len(steps)))
        variant = "b_" + bld["id"]
        flow = msbt.Flow(b.game(f["flow"], variant))
        flow.set_next(0, nodes[0][0])
        for k, step in enumerate(steps):
            node, label = nodes[k]
            extra.append({"file": f["talk"], "label": label, "variant": bld["id"], "text": step["text"]})
            flow.set_next(node, nodes[k + 1][0] if k + 1 < len(steps) else END)
        b.put(f["flow"], flow.build(), variant)
        b.note("event %s: %d message(s)" % (ev["id"], len(steps)))
    b.proj["text"] = list(b.proj["text"]) + extra
