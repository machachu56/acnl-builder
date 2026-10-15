"""Where things are: the recomp checkout (modkit, SDK, mods), the game dump, the wasm toolchain.

Everything can be overridden with environment variables:
  ACNL_RECOMP   recomp checkout            (default: ../recomp next to this repository)
  ACNL_ROM      decrypted .3ds/.cci dump   (default: ../acnl.3ds)
  CLANG, WASM_LD   the WebAssembly toolchain
"""
import glob
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # acnl-builder/
PARENT = os.path.dirname(ROOT)
RECOMP = os.environ.get("ACNL_RECOMP") or os.path.join(PARENT, "recomp")
ROM = os.environ.get("ACNL_ROM") or os.path.join(PARENT, "acnl.3ds")
PROJECTS = os.environ.get("ACNLB_PROJECTS") or os.path.join(ROOT, "projects")
CACHE = os.environ.get("ACNLB_CACHE") or os.path.join(ROOT, ".cache")
EXPORTS = os.environ.get("ACNLB_EXPORTS") or os.path.join(ROOT, "exports")
SDK = os.path.join(RECOMP, "mods", "sdk")


def setup_path():
    """make recomp/tools importable (ctr, modkit)"""
    tools = os.path.join(RECOMP, "tools")
    if not os.path.isdir(tools):
        raise SystemExit("recomp checkout not found at %s (set ACNL_RECOMP)" % RECOMP)
    if tools not in sys.path:
        sys.path.insert(0, tools)


def rom_path():
    if not os.path.isfile(ROM):
        raise SystemExit("game dump not found at %s (set ACNL_ROM to your decrypted .3ds)" % ROM)
    return ROM


def find_clang():
    return os.environ.get("CLANG") or shutil.which("clang")


def find_wasm_ld():
    """wasm-ld from WASM_LD, the PATH or an Android NDK"""
    w = os.environ.get("WASM_LD")
    if w:
        return w if os.path.isfile(w) else os.path.join(w, "wasm-ld")
    p = shutil.which("wasm-ld")
    if p:
        return p
    for pat in (os.path.expanduser("~/Android/Sdk/ndk/*/toolchains/llvm/prebuilt/*/bin/wasm-ld"),
                os.environ.get("ANDROID_NDK", "/nonexistent") + "/toolchains/llvm/prebuilt/*/bin/wasm-ld"):
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[-1]
    return None


def game_binary():
    """the recomp executable (ACNL_BIN, or the build next to the sources)"""
    for c in (os.environ.get("ACNL_BIN"), os.path.join(RECOMP, "build", "linux", "acnl"), os.path.join(RECOMP, "build", "linux", "acnl.exe")):
        if c and os.path.isfile(c):
            return c
    return None


def toolchain_status():
    return {"clang": find_clang(), "wasm_ld": find_wasm_ld(), "rom": ROM if os.path.isfile(ROM) else None,
            "recomp": RECOMP if os.path.isdir(RECOMP) else None, "magick": shutil.which("magick"),
            "game": game_binary()}
