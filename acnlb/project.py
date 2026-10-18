"""Project files: a directory with project.json and assets/, edited by the UI or by hand.

project.json (format 1):
  id, title, author, description, version
  text      [{file, label, variant?, text: {lang: str}}]      dialogue and every other string table
  textures  [{file, name, png, variant?}]                    repaint a texture of any game model
  villagers [{...}]   buildings [{...}]   interiors [{...}]   events [{...}]
  scripts   [{id, name, enabled, code}]                       Python-syntax triggers (see docs/SCRIPTING.md)
  objects   [{id, name, kind, model, start, ...}]             outdoor objects drawn by the runtime: vehicles (features/objects.py)
  actors    {name: profile number}                           names for the actors scripts may mention
"""
import json
import os
import re
import shutil
import threading

from . import env

FORMAT = 1
LANGS = ["en", "es", "fr", "it", "de"]
ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


def blank(pid, title=None):
    return {"format": FORMAT, "id": pid, "title": title or pid, "author": "", "description": "", "version": "1.0",
            "text": [], "textures": [], "villagers": [], "designs": [], "buildings": [], "interiors": [], "events": [], "scripts": [], "actors": {}, "unsafe_ok": [], "objects": []}


def project_dir(pid):
    if not ID_RE.match(pid):
        raise ValueError("project id must be lowercase letters, digits and _ (2-32 chars, starting with a letter)")
    return os.path.join(env.PROJECTS, pid)


def list_projects():
    out = []
    if os.path.isdir(env.PROJECTS):
        for name in sorted(os.listdir(env.PROJECTS)):
            f = os.path.join(env.PROJECTS, name, "project.json")
            if os.path.isfile(f):
                try:
                    p = json.load(open(f, encoding="utf-8"))
                    out.append({"id": name, "title": p.get("title", name), "author": p.get("author", "")})
                except (OSError, ValueError):
                    out.append({"id": name, "title": name + " (unreadable)", "author": ""})
    return out


def load(pid):
    with open(os.path.join(project_dir(pid), "project.json"), encoding="utf-8") as f:
        p = json.load(f)
    for k, v in blank(pid).items():
        p.setdefault(k, v)
    return migrate(p)


def migrate(p):
    # room for future format changes
    p["format"] = FORMAT
    return p


_save_lock = threading.Lock()


def save(p):
    """write project.json atomically; saves can arrive together (autosave while an export saves), so one at a time"""
    d = project_dir(p["id"])
    os.makedirs(os.path.join(d, "assets"), exist_ok=True)
    with _save_lock:
        tmp = os.path.join(d, "project.json.%d.tmp" % threading.get_ident())
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(p, f, indent=1, ensure_ascii=False)
        os.replace(tmp, os.path.join(d, "project.json"))


def create(pid, title=None):
    d = project_dir(pid)
    if os.path.exists(d):
        raise ValueError("project %s already exists" % pid)
    p = blank(pid, title)
    save(p)
    return p


def duplicate(pid, new_id):
    src, dst = project_dir(pid), project_dir(new_id)
    if os.path.exists(dst):
        raise ValueError("project %s already exists" % new_id)
    shutil.copytree(src, dst)
    p = load(new_id)
    p["id"] = new_id
    save(p)
    return p


def delete(pid):
    shutil.rmtree(project_dir(pid))


def asset_path(pid, name):
    """absolute path of a project asset; the name may not leave assets/"""
    if "/" in name or "\\" in name or name.startswith("."):
        raise ValueError("bad asset name")
    return os.path.join(project_dir(pid), "assets", name)
