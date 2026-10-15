"""Turns a project into a mod: a staged file tree (romfs/, romfs.<variant>/, plugin, config) packed as .acmod."""
import hashlib
import os
import subprocess
import sys
import tempfile
import zipfile

from . import env, project, rom


class BuildError(Exception):
    pass


class Build:
    """Collects the mod's files. Features read the current version of a game file with .game() and
    stage a replacement with .put(), so several features can edit the same file."""

    def __init__(self, proj):
        self.proj = proj
        self.files = {}          # mod-relative path -> bytes
        self.cfg = {"buildings": [], "events": []}      # what the runtime plugin reads
        self.log = []
        self.warnings = []

    # -- files
    def put(self, path, data, variant=None):
        key = ("romfs.%s/" % variant if variant else "romfs/") + path.lstrip("/")
        self.files[key] = data

    def game(self, path, variant=None):
        """current version of a game file: staged (in the variant, then globally) or from the dump"""
        for key in ((("romfs.%s/" % variant) + path.lstrip("/"),) if variant else ()) + ("romfs/" + path.lstrip("/"),):
            if key in self.files:
                return self.files[key]
        return rom.read(path)

    def add(self, name, data):
        self.files[name] = data

    def note(self, msg):
        self.log.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)
        self.log.append("warning: " + msg)


def mod_ini(proj, b):
    lines = ["# %s -- built with ACNL Builder" % proj["title"], "enabled = true"]
    return ("\n".join(lines) + "\n").encode()


def build(proj, only=None):
    """run every feature; returns the Build (nothing is written to disk)"""
    from .features import FEATURES
    b = Build(proj)
    for name, fn in FEATURES:
        if only and name not in only:
            continue
        before = len(b.files)
        fn(b)
        if len(b.files) != before:
            b.note("%s: %d file(s) so far" % (name, len(b.files)))
    return b


def plugin_needed(b):
    return bool(b.cfg["buildings"] or b.cfg["events"] or b.cfg.get("hooks") or b.cfg.get("scripts"))


# ------------------------------------------------------------------ the runtime plugin

def build_plugin(b):
    """compile plugin/acnlb_runtime.cpp (+ the SDK) once per source hash; returns the .wasm bytes"""
    clang, wasm_ld = env.find_clang(), env.find_wasm_ld()
    if not clang or not wasm_ld:
        raise BuildError("this project needs the runtime plugin (custom buildings/events), but the WebAssembly "
                         "toolchain is missing: install clang and lld (wasm-ld), or set CLANG / WASM_LD "
                         "(found clang=%s, wasm-ld=%s)" % (clang, wasm_ld))
    src = os.path.join(env.ROOT, "plugin", "acnlb_runtime.cpp")
    sdk_c = os.path.join(env.SDK, "acnl_mod.c")
    h = hashlib.sha256()
    for f in (src, sdk_c, os.path.join(env.SDK, "acnl_mod.h")):
        h.update(open(f, "rb").read())
    os.makedirs(env.CACHE, exist_ok=True)
    out = os.path.join(env.CACHE, "runtime-%s.wasm" % h.hexdigest()[:16])
    if os.path.isfile(out):
        return open(out, "rb").read()
    envp = dict(os.environ)
    envp["PATH"] = os.path.dirname(wasm_ld) + os.pathsep + envp.get("PATH", "")
    objs = []
    with tempfile.TemporaryDirectory() as td:
        for s in (src, sdk_c):
            o = os.path.join(td, os.path.basename(s) + ".o")
            lang = ["-x", "c++", "-std=c++17", "-fno-exceptions", "-fno-rtti"] if s.endswith(".cpp") else ["-x", "c", "-std=c11"]
            cmd = [clang, "--target=wasm32", "-mcpu=mvp", "-O2", "-ffreestanding", "-fno-builtin", "-nostdlib", "-Wall",
                   *lang, "-I", env.SDK, "-c", s, "-o", o]
            r = subprocess.run(cmd, capture_output=True, text=True, env=envp)
            if r.returncode:
                raise BuildError("plugin compile failed:\n" + r.stderr)
            objs.append(o)
        tmp = out + ".tmp"
        cmd = [clang, "--target=wasm32", "-mcpu=mvp", "-nostdlib", "-Wl,--no-entry", "-Wl,--export=acnl_mod_init",
               "-Wl,--gc-sections", "-Wl,--strip-all", "-Wl,-z,stack-size=32768", "-Wl,--initial-memory=262144",
               "-o", tmp, *objs]
        r = subprocess.run(cmd, capture_output=True, text=True, env=envp)
        if r.returncode:
            raise BuildError("plugin link failed:\n" + r.stderr)
        os.replace(tmp, out)
    return open(out, "rb").read()


# ------------------------------------------------------------------ packing

def finish(b):
    """add mod.ini, the config and the plugin; returns {path: bytes}"""
    from .features.runtime import config_text
    files = dict(b.files)
    files["mod.ini"] = mod_ini(b.proj, b)
    if plugin_needed(b):
        files["acnlb.cfg"] = config_text(b).encode()
        files["%s.wasm" % b.proj["id"]] = build_plugin(b)
    if not any(k.startswith("romfs") for k in files) and not any(k.endswith(".wasm") for k in files):
        raise BuildError("the project changes nothing yet: add some text, a texture, a building...")
    return files


def write_acmod(files, out):
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    tmp = out + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            z.writestr(info, files[name], zipfile.ZIP_DEFLATED)
    os.replace(tmp, out)


def export(pid, out=None, install=False):
    """build + pack projects/<pid> -> exports/<pid>.acmod; returns a report dict"""
    proj = project.load(pid)
    b = build(proj)
    files = finish(b)
    out = out or os.path.join(env.EXPORTS, pid + ".acmod")
    write_acmod(files, out)
    rep = {"path": out, "files": len(files), "bytes": os.path.getsize(out), "log": b.log, "warnings": b.warnings}
    if install:
        dst = install_dir()
        os.makedirs(dst, exist_ok=True)
        import shutil
        shutil.copy(out, os.path.join(dst, pid + ".acmod"))
        rep["installed"] = os.path.join(dst, pid + ".acmod")
    return rep


def install_dir():
    if sys.platform == "win32":
        return os.path.join(os.environ.get("APPDATA", ""), "acnl-recomp", "mods")
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "acnl-recomp", "mods")
