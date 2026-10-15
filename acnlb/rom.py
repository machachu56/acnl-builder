"""Read-only access to the game's RomFS (your own dump), with a small cache."""
import os
import threading

from . import env

_lock = threading.Lock()
_romfs = None
_index = None


def _open():
    global _romfs, _index
    with _lock:
        if _romfs is None:
            env.setup_path()
            from ctr import NCSD
            _romfs = NCSD(env.rom_path()).ncch(0).romfs()
            _index = {p: (o, s) for p, o, s in _romfs.walk()}
    return _romfs, _index


def listing():
    """{path: size} of every RomFS file"""
    _, idx = _open()
    return {p: s for p, (o, s) in idx.items()}


def exists(path):
    return path in _open()[1]


def read(path):
    r, idx = _open()
    if path not in idx:
        raise KeyError("not in the game's RomFS: " + path)
    with _lock:
        return r.read(*idx[path])


def glob_prefix(prefix, suffix=""):
    return sorted(p for p in _open()[1] if p.startswith(prefix) and p.endswith(suffix))
