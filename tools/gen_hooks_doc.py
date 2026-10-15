"""Regenerate the class catalogue in docs/HOOKS.md from YOUR dump:  python3 tools/gen_hooks_doc.py
(addresses depend on the exact game version; the doc says which one was read)"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from acnlb import env, gamemap, xref  # noqa: E402

# what the NAME of each class suggests (not verified by watching the game: that is what the probe is for)
CLASSES = [
    ("Weather", [("BsWeatherRain", "rain effect"), ("BsWeatherSnow", "snow effect"), ("BsWeatherSakura", "cherry-blossom petals"), ("BsWeatherPaper", "paper/confetti")]),
    ("Clothes", [("NpcTopsChangeModel", "a villager model whose shirt changes"), ("AcNpcTopsChangeDemoDollSp", "the cut-scene doll of a villager changing their shirt"),
                 ("NpcTopsBank", "the bank of shirt textures for villagers"), ("ClothesList", "the player's clothes list")]),
    ("Faces and emotions", [("HumanFaceAnimControl", "face animation of a human model"), ("HumanResTextureAnimBank", "face texture animations"),
                            ("PlayerFaceBank", "face textures of the player"), ("EmoticonAction", "a character playing an emoticon/emotion action"), ("NpcHeadCtrl", "a villager's head/gaze control")]),
    ("Villagers and actors", [("AcNpc", "base of every villager/NPC actor"), ("AcNpcNml", "an ordinary villager"), ("AcNpcSp", "a special character"), ("AcNpcSpShop", "a shopkeeper"),
                              ("AcNpcSpResetsan", "Mr. Resetti"), ("AcNpcSpTourDesk", "the tour desk"), ("NpcModel", "a villager's 3D model"), ("BsNpcMgr", "manager of all NPCs"),
                              ("NpcAction", "NPC actions"), ("Actor", "base of all actors"), ("DemoActor", "actors in cut-scenes")]),
    ("Events", [("BsEventMgr", "event manager"), ("EventBook", "the event calendar"), ("EventSecretarySearchFunc", "looks for the secretary among the NPCs")]),
]


def main():
    gm = gamemap.load()
    x = xref.load()
    rows = ["| class | what the name suggests | vtable | slots | derived from |", "|---|---|---|---|---|"]
    for title, items in CLASSES:
        rows.append("| **%s** | | | | |" % title)
        for name, why in items:
            c = gm.classes.get(name)
            if c:
                rows.append("| `%s` | %s | `0x%x` | %d | %s |" % (name, why, c["vtable"], len(c["methods"]), ", ".join("`%s`" % b[:28] for b in c["bases"]) or "-"))
    table = "\n".join(rows)
    path = os.path.join(ROOT, "docs", "HOOKS.md")
    text = open(path, encoding="utf-8").read()
    text = re.sub(r"(<!-- classes:start -->).*?(<!-- classes:end -->)", lambda m: m.group(1) + "\n" + table + "\n" + m.group(2), text, flags=re.S)
    open(path, "w", encoding="utf-8").write(text)
    print("updated", path, "(%d classes in the map)" % len(gm.classes))


if __name__ == "__main__":
    main()
