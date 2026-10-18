"""The Builder's local web server: a JSON API for the editors + the static UI (web/).

    python3 -m acnlb serve [--port 8765] [--no-browser]
"""
import base64
import io
import json
import mimetypes
import os
import re
import threading
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__, build, catalog, env, exterior, interior, models, paintx, project, rom, texfmt, vehicle
from .features import interiors as interiors_feature
from .features import text as textmod
from .features import textures as texmod

WEB = os.path.join(env.ROOT, "web")
JOBS = {}


class ApiError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


def jobs_run(fn):
    jid = uuid.uuid4().hex[:8]
    JOBS[jid] = {"state": "running"}

    def work():
        try:
            JOBS[jid] = {"state": "done", "result": fn()}
        except Exception as e:                      # reported to the UI
            traceback.print_exc()
            JOBS[jid] = {"state": "error", "error": str(e)}
    threading.Thread(target=work, daemon=True).start()
    return {"job": jid}


# ------------------------------------------------------------------ handlers (path regex -> function)

ROUTES = []


def route(method, pattern):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn))
        return fn
    return deco


def png_b64(rows):
    return base64.b64encode(texmod.to_png(rows)).decode()


@route("GET", "/api/status")
def status(req, q):
    return {"version": __version__, "toolchain": env.toolchain_status(), "projects": project.list_projects(),
            "install_dir": build.install_dir(), "langs": project.LANGS}


@route("GET", "/api/projects")
def projects(req, q):
    return project.list_projects()


@route("POST", "/api/projects")
def projects_new(req, q):
    b = req.json()
    try:
        if b.get("copy_of"):
            return project.duplicate(b["copy_of"], b["id"])
        return project.create(b["id"], b.get("title"))
    except ValueError as e:
        raise ApiError(str(e))


@route("GET", r"/api/project/([a-z][a-z0-9_]+)")
def project_get(req, q, pid):
    try:
        return project.load(pid)
    except FileNotFoundError:
        raise ApiError("no such project", 404)


@route("PUT", r"/api/project/([a-z][a-z0-9_]+)")
def project_put(req, q, pid):
    p = req.json()
    if p.get("id") != pid:
        raise ApiError("project id mismatch")
    project.save(p)
    return {"ok": True}


@route("DELETE", r"/api/project/([a-z][a-z0-9_]+)")
def project_delete(req, q, pid):
    project.delete(pid)
    return {"ok": True}


@route("GET", r"/api/project/([a-z][a-z0-9_]+)/assets")
def assets_list(req, q, pid):
    d = os.path.join(project.project_dir(pid), "assets")
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


@route("GET", r"/api/project/([a-z][a-z0-9_]+)/asset/([^/]+)")
def asset_get(req, q, pid, name):
    f = project.asset_path(pid, unquote(name))
    if not os.path.isfile(f):
        raise ApiError("no such asset", 404)
    ctype = mimetypes.guess_type(f)[0] or "application/octet-stream"
    return (ctype, open(f, "rb").read())


@route("PUT", r"/api/project/([a-z][a-z0-9_]+)/asset/([^/]+)")
def asset_put(req, q, pid, name):
    name = unquote(name)
    ext = os.path.splitext(name)[1].lower()
    data = req.body()
    if name.startswith("mdl_") and ext in models.EXTENSIONS + models.SUPPORT_EXTENSIONS:
        pass                                    # a 3D model or a file it refers to (checked when the model is read)
    elif ext == ".png":
        from PIL import Image
        try:
            Image.open(io.BytesIO(data)).verify()
        except Exception:
            raise ApiError("not a valid PNG")
    else:
        raise ApiError("assets are PNG files (3D models: glTF/GLB, OBJ, STL, PLY)")
    f = project.asset_path(pid, name)
    os.makedirs(os.path.dirname(f), exist_ok=True)
    with open(f, "wb") as fp:
        fp.write(data)
    return {"ok": True}


@route("DELETE", r"/api/project/([a-z][a-z0-9_]+)/asset/([^/]+)")
def asset_delete(req, q, pid, name):
    f = project.asset_path(pid, unquote(name))
    if os.path.isfile(f):
        os.remove(f)
    return {"ok": True}


@route("POST", r"/api/project/([a-z][a-z0-9_]+)/export")
def export(req, q, pid):
    opts = req.json()
    return jobs_run(lambda: build.export(pid, install=bool(opts.get("install"))))


@route("GET", r"/api/job/([0-9a-f]+)")
def job(req, q, jid):
    return JOBS.get(jid) or {"state": "error", "error": "unknown job"}


# ---- game data

@route("GET", "/api/game/text-files")
def game_text_files(req, q):
    qq = (q.get("q") or [""])[0].lower()
    grp = (q.get("group") or [""])[0]
    out = [f for f in catalog.text_files() if (not grp or f["group"] == grp) and (not qq or qq in f["name"].lower())]
    return {"files": out[:400], "total": len(out), "groups": sorted({f["group"] for f in catalog.text_files()})}


@route("GET", "/api/game/text")
def game_text(req, q):
    path = (q.get("path") or [""])[0]
    if not rom.exists(path):
        raise ApiError("not in the game", 404)
    return catalog.read_text(path)


@route("GET", "/api/game/text-search")
def game_text_search(req, q):
    return catalog.search_text((q.get("q") or [""])[0])


@route("POST", "/api/text/check")
def text_check(req, q):
    b = req.json()
    return {"problems": textmod.check(b.get("text", ""))}


@route("GET", "/api/game/villagers")
def game_villagers(req, q):
    return catalog.villagers()


@route("GET", "/api/game/models")
def game_models(req, q):
    return catalog.list_models((q.get("prefix") or ["/Item/Model/"])[0], (q.get("q") or [""])[0])


@route("GET", "/api/game/model-textures")
def game_model_textures(req, q):
    return catalog.model_textures((q.get("path") or [""])[0])


@route("GET", "/api/game/texture")
def game_texture(req, q):
    path, name = (q.get("path") or [""])[0], (q.get("name") or [""])[0]
    try:
        return ("image/png", texmod.to_png(catalog.texture_rows(path, name)))
    except KeyError:
        raise ApiError("no such texture", 404)


@route("GET", "/api/game/preview-models")
def game_preview_models(req, q):
    return catalog.preview_models((q.get("path") or [""])[0])


@route("GET", "/api/game/mesh")
def game_mesh(req, q):
    return catalog.mesh_json((q.get("path") or [""])[0])


# ---- editors' previews

def mesh_payload(mesh, atlas_rows, extra=None):
    m = mesh
    out = {"positions": [c for v in m.verts for c in v["pos"]], "normals": [c for v in m.verts for c in v["normal"]],
           "uvs": [c for v in m.verts for c in v["uv"]], "colors": [c for v in m.verts for c in v["color"][:3]],
           "indices": m.tris, "atlas": png_b64(atlas_rows)}
    out.update(extra or {})
    return out


@route("GET", "/api/exterior/presets")
def ext_presets(req, q):
    return {"defaults": exterior.DEFAULT, "presets": exterior.PRESETS, "bases": exterior.BASES}


@route("POST", "/api/exterior/preview")
def ext_preview(req, q):
    b = req.json()
    pid = b.get("project")
    style = dict(b.get("style") or {})
    overlay = None
    if style.get("overlay") and pid:
        f = project.asset_path(pid, style["overlay"])
        if os.path.isfile(f):
            overlay = texmod.load_png(f)
    ext = exterior.build(style)
    rows = ext.paint_body(bool(b.get("winter")), overlay).rows()
    parts = [mesh_payload(ext.body, rows, {"name": "body"})]
    if ext.glow:
        parts.append(mesh_payload(ext.glow, ext.paint_glow().rows(), {"name": "glow"}))
    return {"parts": parts, "regions": ext.regions, "atlas_size": [len(rows[0]), len(rows)], "style": ext.s}


@route("POST", "/api/exterior/atlas")
def ext_atlas(req, q):
    """the generated body atlas as PNG (the starting point for painting over it)"""
    b = req.json()
    ext = exterior.build(b.get("style") or {})
    return ("image/png", texmod.to_png(ext.paint_body(False).rows()))


@route("GET", "/api/objects/kinds")
def objects_kinds(req, q):
    cars = [{"key": k, "label": v["label"], "colors": v.get("color_names") or ["Default"]} for k, v in vehicle.GAME_CARS.items()]
    return {"cars": cars, "starts": [["house", "Next to the player's house"], ["town_hall", "Next to the town hall"],
                                     ["station", "Next to the train station"], ["tiles", "At a tile of the town (x, z)"]],
            "sounds": [["sporty", "Sporty engine"], ["classic", "Soft old engine"]]}


@route("POST", "/api/objects/preview")
def objects_preview(req, q):
    """the vehicle's model for the 3D preview: one viewer part per prop part (its texture as PNG)"""
    b = req.json()
    pid = b.get("project")
    spec = dict(b.get("model") or {"car": "sports_car"})
    read = (lambda name: open(project.asset_path(pid, name), "rb").read()) if pid else None
    prop, info, scale = vehicle.make_prop(spec, read)
    pngs, parts = {}, []
    for p in prop.parts:
        if not p.tris:
            continue
        if p.tex not in pngs:
            pngs[p.tex] = png_b64(prop.textures[p.tex][2]) if 0 <= p.tex < len(prop.textures) else png_b64([[(255, 255, 255, 255)]])
        parts.append({"name": p.name, "positions": [c for v in p.verts for c in v[0]], "normals": [c for v in p.verts for c in v[1]],
                      "uvs": [c for v in p.verts for c in v[2]], "colors": [c / 255 for v in p.verts for c in v[3][:3]],
                      "indices": p.tris, "atlas": pngs[p.tex]})
    lo, hi = prop.bounds()
    return {"parts": parts, "size": [round(hi[i] - lo[i], 1) for i in range(3)], "front": info["front"], "triangles": prop.triangles()}


@route("POST", "/api/interior/preview")
def int_preview(req, q):
    b = req.json()
    proj = b.get("project")
    spec = b["scene"]
    loader = None
    if proj:
        loader = interiors_feature.asset_loader({"id": proj})
    try:
        built = interior.Builder(spec, rom.read, loader)
        built.paint()
        built.atlas = interior.Atlas(interior.ATLAS_W, interior.ATLAS_H, built.pack.regions)
        built.mesh = interior.Mesh(built.atlas)
        built.shell()
        errs = []
        for it in spec["items"]:
            try:
                built.add_item(it)
            except Exception as e:          # keep going: show every broken item
                errs.append("%s: %s" % (it.get("id", "?"), e))
        errs += built.plan.problems() + built.budget()
        built.mesh.weld()
    except interior.SceneError as e:
        return {"error": str(e)}
    plan = built.plan
    return {"mesh": mesh_payload(built.mesh, built.canvas.rows()), "problems": errs,
            "solid": sorted(plan.solid), "floor": sorted(plan.owner), "doorway": sorted(plan.doorway),
            "atlas_used": built.pack.y, "triangles": len(built.mesh.tris) // 3, "regions": built.pack.regions,
            "warnings": built.warnings, "entrance": {"side": plan.side, "door": plan.door, "exit": plan.exit, "bounds": plan.bounds}}


@route("POST", "/api/model/info")
def model_info(req, q):
    """measure an imported 3D model: size in its own units, triangles, textures"""
    b = req.json()
    loader = interiors_feature.asset_loader({"id": b["project"]})
    main = b["asset"]
    try:
        m = models.load(main, interior.asset_fetch(main, loader.bytes), b.get("up", "y"), bool(b.get("flip")))
    except models.ModelError as e:
        raise ApiError(str(e))
    mn, mx = m.bounds()
    return {"size": [mx[i] - mn[i] for i in range(3)], "triangles": m.triangles, "vertices": m.vertices,
            "materials": [{"name": x.name, "textured": x.image is not None} for x in m.materials], "notes": m.notes}


@route("GET", "/api/interior/presets")
def int_presets(req, q):
    return {"floor": interior.FLOOR_PRESETS, "wall": interior.WALL_PRESETS, "bed": interior.BED_DEFAULT}


# ---- scripts
@route("POST", "/api/script/check")
def script_check(req, q):
    """check one script (or all of them) against the saved project; the browser saves before asking"""
    from .script import check, context
    b = req.json()
    proj = project.load(b["project"])
    res = check(b.get("source") or "", context.build_ctx(proj))
    res.pop("program", None)
    return res


@route("GET", "/api/script/reference")
def script_reference(req, q):
    from .script import docs
    from .features import scripts as scfeat
    return dict(docs.reference(), spawnable=sorted(scfeat.SPAWNABLE), talk_flow=scfeat.TALK_FLOW)


@route("POST", "/api/script/examples")
def script_examples(req, q):
    from .script import docs
    b = req.json()
    return docs.examples(project.load(b["project"]) if b.get("project") else None)


@route("GET", "/api/script/generated")
def script_generated(req, q):
    """the Python made from the Characters cards of the interiors"""
    from .features import scripts
    return {"source": scripts.cast_source(project.load((q.get("project") or [""])[0]))}


@route("GET", "/api/script/stub")
def script_stub(req, q):
    from .script import docs
    return ("text/x-python", docs.stub().encode())


@route("GET", "/api/fonts")
def fonts(req, q):
    return list(paintx.list_fonts())


# ------------------------------------------------------------------ http plumbing

class Handler(BaseHTTPRequestHandler):
    server_version = "ACNLBuilder/" + __version__

    def log_message(self, fmt, *args):
        pass

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def json(self):
        try:
            return json.loads(self.body() or b"{}")
        except ValueError:
            raise ApiError("bad JSON")

    def send(self, status, ctype, data):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def allowed(self, method):
        """only this machine's own pages may talk to the API (no DNS-rebinding / cross-site requests)"""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in ("127.0.0.1", "localhost", "::1"):
            return False
        origin = self.headers.get("Origin")
        if method != "GET" and origin and origin not in ("http://%s" % self.headers.get("Host"),):
            return False
        return True

    def handle_any(self, method):
        if not self.allowed(method):
            return self.send(403, "application/json", b'{"error":"forbidden"}')
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path.startswith("/api/"):
            for m, rx, fn in ROUTES:
                if m != method:
                    continue
                mt = rx.match(u.path)
                if mt:
                    try:
                        res = fn(self, q, *[unquote(g) for g in mt.groups()])
                    except ApiError as e:
                        return self.send(e.status, "application/json", json.dumps({"error": str(e)}).encode())
                    except Exception as e:
                        traceback.print_exc()
                        return self.send(500, "application/json", json.dumps({"error": "%s: %s" % (type(e).__name__, e)}).encode())
                    if isinstance(res, tuple):
                        return self.send(200, res[0], res[1])
                    return self.send(200, "application/json", json.dumps(res).encode())
            return self.send(404, "application/json", b'{"error":"no such endpoint"}')
        if method != "GET":
            return self.send(405, "text/plain", b"method not allowed")
        path = u.path.lstrip("/") or "index.html"
        f = os.path.normpath(os.path.join(WEB, path))
        if not f.startswith(WEB) or not os.path.isfile(f):
            return self.send(404, "text/plain", b"not found")
        ctype = mimetypes.guess_type(f)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self.send(200, ctype, open(f, "rb").read())

    def do_GET(self): self.handle_any("GET")
    def do_POST(self): self.handle_any("POST")
    def do_PUT(self): self.handle_any("PUT")
    def do_DELETE(self): self.handle_any("DELETE")


def serve(port=8765, open_browser=True):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = "http://127.0.0.1:%d/" % port
    print("ACNL Builder %s -- %s (Ctrl+C to stop)" % (__version__, url))
    if open_browser:
        import webbrowser
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


@route("GET", "/api/events/flows")
def event_flows(req, q):
    from .features import events as ev
    return {k: {"flow": v["flow"], "label": v["label"], "when": v.get("when"), "goodbye": bool(v["goodbye"]), "nodes": [l for n, l in ev.message_nodes(k)]} for k, v in ev.FLOWS.items()}


@route("GET", "/api/events/flowlist")
def event_flowlist(req, q):
    """every conversation of the game that can be rewritten, filtered by ?q="""
    from .features import events as ev
    t = (q.get("q") or [""])[0].lower()
    named = {v["flow"]: k for k, v in ev.FLOWS.items()}
    return [dict(x, npc=named.get(x["flow"])) for x in ev.flow_list() if t in x["name"].lower()][:200]


@route("GET", "/api/events/flow")
def event_flow(req, q):
    """the message nodes of one conversation with the game's own text"""
    from .features import events as ev
    flow = (q.get("flow") or [""])[0]
    named = next((v for v in ev.FLOWS.values() if v["flow"] == flow), None)
    talk = named["talk"] if named else ev.talk_for(flow)
    if not talk:
        raise ApiError("no text file for this conversation")
    return {"flow": flow, "talk": talk, "goodbye": bool(named and named["goodbye"]),
            "nodes": ev.flow_nodes(flow, talk, named and named["first"], named and named["goodbye"]),
            "slots": len(ev.text_slots(flow, talk, named and named["first"], named and named["goodbye"])),
            "max_choices": ev.MAX_CHOICES, "max_answer": ev.MAX_ANSWER}


@route("POST", "/api/launch")
def launch(req, q):
    """start the recompiled game in its own (visible) window"""
    import subprocess
    exe = env.game_binary()
    if not exe:
        raise ApiError("the recomp is not built (looked for %s)" % os.path.join(env.RECOMP, "build", "linux", "acnl"))
    p = subprocess.Popen([exe, env.rom_path()], cwd=os.path.dirname(exe), start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"pid": p.pid, "exe": exe}
