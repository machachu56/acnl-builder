"""Villagers: name and catchphrase of an existing villager (the skin is a texture edit, see textures).

{"id": "ant00", "name": {"en": "Cyrano", "fr": "..."}, "catchphrase": {"en": "ah-CHOO"}}
Personality dialogue is shared by every villager of a personality: edit it in the dialogue tab.
"""
NAME = "/Script/Str/STR_NNpc_name.umsbt"
HABIT = "/Script/Str/STR_NNpc_habit.umsbt"


def compile(b):
    extra = []
    for v in b.proj["villagers"]:
        if any((v.get("name") or {}).values()):
            extra.append({"file": NAME, "label": v["id"], "text": v["name"]})
        if any((v.get("catchphrase") or {}).values()):
            extra.append({"file": HABIT, "label": v["id"], "text": v["catchphrase"]})
    b.proj["text"] = list(b.proj["text"]) + extra
