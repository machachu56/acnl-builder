"""Dialogue and string-table edits.

{"file": "/Script/Talk/NPC_Tanukichi.umsbt", "label": "002", "variant": null,
 "text": {"en": "...", "fr": "..."}}

A language without a text gets the English one (so a mod written in one language still reads in the others);
with no English either, the game's own line stays. `variant` makes the edit apply only inside that building.
"""
import re

from .. import env, rom

env.setup_path()
from modkit import msbt  # noqa: E402

LANGS = msbt.LANGS
MAX_LINE = 34               # characters per line of a message window
MAX_ROWS = 3

CODE = re.compile(r"\{\d+\.\d+:[0-9a-f]*\}")
CHOICES = re.compile(r"\{15\.\d+:[0-9a-f]*\}")


def plain_len(line):
    """visible length of a line: control codes take no room, player/town names count as 8 characters"""
    line = line.replace("{5.0:}", "X" * 8).replace("{5.5:}", "X" * 8)
    return len(CODE.sub("", line))


def check(text):
    """problems of a text: list of strings (empty = fine)"""
    out = []
    text = CHOICES.split(text, 1)[0]                 # the answers of a question are a menu of their own, not lines of the window
    for n, box in enumerate(text.split("{0.4:}"), 1):
        rows = box.split("\n")
        if len(rows) > MAX_ROWS:
            out.append("box %d has %d lines (max %d)" % (n, len(rows), MAX_ROWS))
        for r in rows:
            if plain_len(r) > MAX_LINE:
                out.append("box %d: line too long (%d > %d): %s" % (n, plain_len(r), MAX_LINE, CODE.sub("", r)[:40]))
    return out


def split_file(data):
    return msbt.umsbt_split(data) if data[:8] != b"MsgStdBn" else [data]


def join_file(parts, was_single):
    return parts[0] if was_single else msbt.umsbt_join(parts)


def lang_of(i, n, single):
    """language of part i of a text archive: the European dump has five (en es fr it de); any other layout is
    only known to start with English, the other parts then receive the English text"""
    if single:
        return None
    if n == len(LANGS):
        return LANGS[i]
    return "en" if i == 0 else "?"


def apply(data, edits):
    """edits [{label, text}] on one file's bytes -> new bytes; raises KeyError for an unknown label"""
    parts = split_file(data)
    single = data[:8] == b"MsgStdBn"
    out = []
    for i, part in enumerate(parts):
        lang = lang_of(i, len(parts), single)
        m = msbt.Msbt(part)
        for e in edits:
            t = e["text"]
            s = (t.get(lang) or t.get("en")) if lang else (t.get("en") or next(iter(t.values()), None))
            if not s:
                continue
            m.set_text(m.index(e["label"]), s)
        out.append(m.build())
    return join_file(out, single)


def variant_name(variant):
    """the RomFS variant of a text edit: a building's id means the variant of that building (its interior and text),
    "ev_<event>" is a conversation a script switches on (see events), nothing means everywhere"""
    if not variant:
        return None
    return variant if variant.startswith("ev_") else "b_" + variant


def compile(b):
    groups = {}
    for e in b.proj["text"]:
        if not any(e["text"].values()):
            continue
        groups.setdefault((e["file"], e.get("variant")), []).append(e)
    for (path, variant), edits in groups.items():
        for e in edits:
            for lang, s in e["text"].items():
                for msg in check(s):
                    b.warn("%s %s [%s]: %s" % (path.rsplit("/", 1)[-1], e["label"], lang, msg))
        vname = variant_name(variant)
        try:
            data = apply(b.game(path, vname), edits)
        except KeyError as ex:
            raise ValueError("%s: unknown label %s" % (path, ex))
        b.put(path, data, vname)


# ------------------------------------------------------------------ browsing the game's strings

def read_table(path):
    """{lang: [(label, index, text)]} of a game text file"""
    data = rom.read(path)
    parts = split_file(data)
    single = data[:8] == b"MsgStdBn"
    out = {}
    for i, part in enumerate(parts):
        lang = "en" if single else lang_of(i, len(parts), single)
        if lang == "?":
            continue
        m = msbt.Msbt(part)
        by_index = {v: k for k, v in m.labels.items()}
        out[lang] = [(by_index.get(k, ""), k, m.text(k)) for k in range(len(m.raw))]
    return out
