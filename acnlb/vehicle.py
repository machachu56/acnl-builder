"""Drivable vehicles: the prop of a car (from a model of the game or an imported one) with its wheels as parts of their
own, lights (lens glows, a beam on the ground, tail and brake lights) and the dust its wheels throw, plus the sounds.

    build(spec, read_asset)   -> {"apm": bytes, "dust": bytes, "meta": {...}, "sounds": {name: wav bytes}}

The plugin (plugin/vehicles.h) reads the meta from acnlb.cfg ([vehicle] sections): which parts are which, the wheel
radius, the car's footprint, where the driver sits. Model axes: x = length (the front is at -x, or +x with front = 1),
y = up, z = width; 32 units = one tile.
"""
import math
import struct

from . import propmesh, sounds

# models of the game that make good cars (path, colour textures of the remake series, default front)
GAME_CARS = {
    "sports_car": {"label": "Sports car (convertible)", "model": "/Item/Model/rmk_car_spt.bcres",
                   "colors": ["/Ftr/Remake/Texture/rmk_car_spt_base_0%d.bcres" % i for i in range(1, 5)], "color_tex": "base_00",
                   "color_names": ["Red", "Blue", "Yellow", "White", "Black"], "front": -1, "seat": (8, -4, 9), "scale": 1.0},
    "classic_car": {"label": "Classic car", "model": "/Item/Model/rmk_car_com.bcres",
                    "colors": ["/Ftr/Remake/Texture/rmk_car_com_base_0%d.bcres" % i for i in range(1, 5)], "color_tex": "base_00",
                    "color_names": ["Silver", "Pink", "Sky blue", "Green", "Black"], "front": -1, "seat": (4, -3, 7), "scale": 1.0},
    "kiddie_car": {"label": "Toy car", "model": "/Item/Model/int_oth_car.bcres", "colors": [], "front": -1, "seat": (0, 0, 0), "scale": 2.0},
}


def _glow_texture(size, rgb, falloff=2.2):
    """a soft round light (alpha = brightness)"""
    rows = []
    for y in range(size):
        r = []
        for x in range(size):
            d = math.hypot((x + 0.5) / size * 2 - 1, (y + 0.5) / size * 2 - 1)
            a = max(0.0, 1.0 - d) ** falloff
            r.append((rgb[0], rgb[1], rgb[2], int(255 * a)))
        rows.append(r)
    return rows


def _beam_texture(w, h):
    """the light of the headlights on the ground: strong near the car (v = 0), fading with distance and towards the sides"""
    rows = []
    for y in range(h):
        v = (y + 0.5) / h
        r = []
        for x in range(w):
            u = abs((x + 0.5) / w * 2 - 1)
            a = (1 - v) ** 1.4 * max(0.0, 1 - u ** 2.2) * min(1.0, v * 6)
            r.append((255, 244, 214, int(200 * a)))
        rows.append(r)
    return rows


def _dust_texture(size):
    rows = []
    for y in range(size):
        r = []
        for x in range(size):
            dx, dy = (x + 0.5) / size * 2 - 1, (y + 0.5) / size * 2 - 1
            d = math.hypot(dx, dy)
            n = 0.85 + 0.15 * math.sin(x * 1.7 + y * 2.3) * math.cos(x * 0.9 - y * 1.3)     # a little texture in the puff
            a = max(0.0, 1.0 - d) ** 1.5 * n
            r.append((236, 222, 196, int(255 * min(1.0, a))))
        rows.append(r)
    return rows


def _prompt_texture(size=48, letter="A"):
    """the "press A" bubble shown over a vehicle the player stands next to (the game's green A button look)"""
    from PIL import Image, ImageDraw, ImageFont
    k = 4
    im = Image.new("RGBA", (size * k, size * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    S = size * k
    d.ellipse((S * 0.06, S * 0.06, S * 0.94, S * 0.94), fill=(255, 255, 255, 255))
    d.ellipse((S * 0.13, S * 0.13, S * 0.87, S * 0.87), fill=(64, 178, 96, 255))
    font = None
    for f in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"):
        try:
            font = ImageFont.truetype(f, int(S * 0.55))
            break
        except OSError:
            continue
    font = font or ImageFont.load_default()
    box = d.textbbox((0, 0), letter, font=font)
    d.text(((S - (box[2] - box[0])) / 2 - box[0], (S - (box[3] - box[1])) / 2 - box[1]), letter, font=font, fill=(255, 255, 255, 255))
    im = im.resize((size, size), Image.LANCZOS)
    return [[im.getpixel((x, y)) for x in range(size)] for y in range(size)]


def _add_texture(prop, rows, wrap=0):
    prop.textures.append((len(rows[0]), len(rows), rows, wrap, wrap))
    return len(prop.textures) - 1


def _quad_part(prop, name, tex, corners, flags, pivot=None, normal=(0, 1, 0), rgba=(255, 255, 255, 255)):
    """a part made of one quad: corners in order with uv (0,0) (1,0) (1,1) (0,1)"""
    p = propmesh.Part(name, tex, flags)
    for c, uv in zip(corners, ((0, 0), (1, 0), (1, 1), (0, 1))):
        p.verts.append((tuple(c), normal, uv, rgba))
    p.tris = [0, 1, 2, 0, 2, 3]
    p.pivot = pivot
    prop.parts.append(p)
    return len(prop.parts) - 1


def _billboard(prop, name, tex, center, size, flags):
    x, y, z = center
    h = size / 2
    corners = [(x - h, y + h, z), (x + h, y + h, z), (x + h, y - h, z), (x - h, y - h, z)]
    return _quad_part(prop, name, tex, corners, flags | propmesh.BILLBOARD | propmesh.UNLIT, pivot=center, normal=(0, 0, 1))


def find_lights(prop, front):
    """where the lights go: near the front and rear ends, at bumper height, towards the sides"""
    lo, hi = prop.bounds()
    fx, rx = (lo[0], hi[0]) if front < 0 else (hi[0], lo[0])
    h = hi[1] - lo[1]
    w = max(abs(lo[2]), abs(hi[2]))
    y = lo[1] + h * 0.42
    inset = (hi[0] - lo[0]) * 0.02
    return {"head": [(fx - front * inset, y, s * w * 0.62) for s in (-1, 1)],
            "tail": [(rx + front * inset, y + h * 0.04, s * w * 0.62) for s in (-1, 1)], "front_x": fx, "rear_x": rx, "width": w}


def make_prop(spec, read_asset=None):
    """the car's prop alone (grounded and scaled, wheels not split yet) and what is known about the model"""
    if spec.get("model_file"):
        from . import models
        prop = models.prop_from_asset(spec["model_file"], read_asset)
        info = {"front": int(spec.get("front", -1)), "seat": tuple(spec.get("seat", (0, 0, 0))), "scale": 1.0}
    else:
        info = GAME_CARS.get(spec.get("car", "sports_car"), GAME_CARS["sports_car"])
        retex = {}
        ci = int(spec.get("color", 0) or 0)
        if ci > 0 and ci <= len(info["colors"]):
            from . import rom, texfmt
            from .env import setup_path
            setup_path()
            from modkit import cgfx
            d = rom.read(info["colors"][ci - 1])
            t = cgfx.textures(d)[0]
            retex[info["color_tex"]] = texfmt.decode_texture(d, t)
        prop = propmesh.from_game_model(info["model"], retexture=retex)
    scale = float(spec.get("scale", info.get("scale", 1.0)) or 1.0)
    prop.ground()
    if scale != 1.0:
        prop.scale(scale)
    return prop, info, scale


def build(spec, read_asset=None):
    """spec: {"car": key of GAME_CARS, "color": index} or {"model_file": asset name (imported), "front": -1|1}, "scale": 1.0}"""
    prop, info, scale = make_prop(spec, read_asset)
    front = info["front"]
    wheels = propmesh.split_wheels(prop, front)
    lights = find_lights(prop, front)
    lo, hi = prop.bounds()
    meta = {"length": round(hi[0] - lo[0], 1), "width": round(hi[2] - lo[2], 1), "height": round(hi[1] - lo[1], 1), "front": front,
            "wheel_radius": round(sum(w["radius"] for w in wheels) / len(wheels), 2) if wheels else 0.0,
            "wheels": [], "steer": [], "seat": [round(c * scale, 1) for c in info.get("seat", (0, 0, 0))]}
    for i, p in enumerate(prop.parts):
        if p.name.startswith("wheel_"):
            meta["wheels"].append(i)
            if p.name.startswith("wheel_f"):
                meta["steer"].append(i)
    # lights
    glow_w = _add_texture(prop, _glow_texture(32, (255, 248, 220)))
    glow_r = _add_texture(prop, _glow_texture(32, (255, 40, 30), 1.6))
    beam = _add_texture(prop, _beam_texture(32, 64))
    size = max(6.0, lights["width"] * 0.42)
    meta["head"] = [_billboard(prop, "headlight_%d" % k, glow_w, c, size, propmesh.ADDITIVE) for k, c in enumerate(lights["head"])]
    meta["tail"] = [_billboard(prop, "taillight_%d" % k, glow_r, c, size * 0.7, propmesh.ADDITIVE) for k, c in enumerate(lights["tail"])]
    meta["brake"] = [_billboard(prop, "brakelight_%d" % k, glow_r, c, size * 1.3, propmesh.ADDITIVE) for k, c in enumerate(lights["tail"])]
    fx, w = lights["front_x"], lights["width"]
    L = 128.0 * max(1.0, scale ** 0.5)
    y = 1.2
    near, far = w * 0.8, w * 2.2
    xa, xb = fx, fx + front * L
    corners = [(xa, y, -near), (xa, y, near), (xb, y, far), (xb, y, -far)]
    meta["beam"] = _quad_part(prop, "beam", beam, corners, propmesh.ADDITIVE | propmesh.UNLIT, pivot=(xa, y, 0))
    meta["beam_length"] = L
    prompt = _add_texture(prop, _prompt_texture())
    meta["prompt"] = _billboard(prop, "prompt", prompt, (0, hi[1] + 18, 0), 15, propmesh.BLENDED)
    # the dust the wheels throw (its own prop: a pool of puffs)
    dust = propmesh.Prop("dust")
    dt = _add_texture(dust, _dust_texture(32))
    _billboard(dust, "puff", dt, (0, 0, 0), 16, propmesh.BLENDED)
    return {"apm": prop.apm(), "dust": dust.apm(), "meta": meta, "sounds": sounds.vehicle_sounds(spec.get("sound", "sporty")),
            "triangles": prop.triangles()}
