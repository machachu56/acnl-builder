"""Sounds made by the builder (synthesized, nothing taken from anywhere): a vehicle's engine loop, starter, horn, door,
skid, engine stop and the "poof" of a car appearing from its item, as 16-bit mono WAV files the runtime mixes into the game's sound (plugin: acnl_sound_*).

The engine loop holds a whole number of periods of its fundamental, so it loops without a click; the plugin raises its
pitch with the speed.
"""
import math
import random
import struct

RATE = 22050


def wav(samples, rate=RATE):
    data = struct.pack("<%dh" % len(samples), *(max(-32767, min(32767, int(s * 32767))) for s in samples))
    return b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) + \
        b"data" + struct.pack("<I", len(data)) + data


def _lowpass(xs, fc, rate=RATE):
    a = 1 - math.exp(-2 * math.pi * fc / rate)
    y, out = 0.0, []
    for x in xs:
        y += (x - y) * a
        out.append(y)
    return out


def _normalize(xs, peak=0.8):
    m = max(1e-9, max(abs(x) for x in xs))
    return [x * peak / m for x in xs]


def _loop(xs, n, fade):
    """xs holds n + fade samples: its last `fade` are crossfaded over its first ones, so sample n - 1 runs on into sample 0"""
    out = list(xs[:n])
    for i in range(fade):
        w = i / fade
        out[i] = xs[n + i] * (1 - w) + xs[i] * w
    return out


def _env(n, attack, release):
    a, r = max(1, int(attack * RATE)), max(1, int(release * RATE))
    return [min(1.0, i / a, (n - i) / r) for i in range(n)]


def engine_loop(style="sporty"):
    """a seamless engine idle: harmonics of f0 with a four-stroke beat and a little rumble"""
    f0 = 49 if style == "sporty" else 42         # 22050 / 49 = 450 samples: whole periods
    period = RATE // f0
    n = period * 24
    fade = period * 2
    rnd = random.Random(7)
    noise = _lowpass([rnd.uniform(-1, 1) for _ in range(n + fade)], 260)
    out = []
    harm = [1.0, 0.75, 0.45, 0.32, 0.18, 0.12, 0.07] if style == "sporty" else [1.0, 0.5, 0.25, 0.12]
    for i in range(n + fade):
        t = i / RATE
        ph = 2 * math.pi * f0 * t
        tone = sum(a * math.sin((k + 1) * ph + k * 0.7) for k, a in enumerate(harm))
        beat = 0.62 + 0.38 * (0.5 + 0.5 * math.cos(ph / 2)) ** 3        # firing: every other turn
        out.append(tone * beat * 0.55 + noise[i] * 1.6)
    return _normalize(_loop(out, n, fade), 0.55)          # (the noise is not periodic: crossfaded at the seam)


def starter(style="sporty"):
    """the starter cranks three times, the engine catches and revs once"""
    rnd = random.Random(3)
    out = []
    crank = int(0.62 * RATE)
    for i in range(crank):
        t = i / RATE
        whine = math.sin(2 * math.pi * (120 + 30 * math.sin(2 * math.pi * 5.2 * t)) * t) * 0.35
        chug = (0.5 + 0.5 * math.sin(2 * math.pi * 5.2 * t)) ** 4
        out.append((whine + rnd.uniform(-0.25, 0.25)) * chug)
    rev = int(0.75 * RATE)
    ph = 0.0
    for i in range(rev):
        t = i / rev
        f = 49 * (0.8 + 1.1 * math.sin(math.pi * min(1.0, t * 1.4)) ** 2 + 0.2 * t)
        ph += 2 * math.pi * f / RATE
        a = min(1.0, t * 8) * (1 - t * 0.35)
        out.append(a * (math.sin(ph) + 0.6 * math.sin(2 * ph + 0.7) + 0.35 * math.sin(3 * ph + 1.4)) * 0.55)
    out = _lowpass(out, 3000)
    return _normalize(out, 0.7)


def horn():
    """a cheerful two-note "beep beep" (a major third, soft square waves)"""
    out = []
    for beep in range(2):
        n = int(0.16 * RATE)
        env = _env(n, 0.008, 0.03)
        for i in range(n):
            t = i / RATE
            v = 0.0
            for f in (523.25, 659.25):
                for k in (1, 3, 5):                       # a rounded square wave
                    v += math.sin(2 * math.pi * f * k * t) / k
            out.append(v * env[i] * 0.3)
        if beep == 0:
            out += [0.0] * int(0.07 * RATE)
    return _normalize(_lowpass(out, 4200), 0.75)


def door():
    """getting in or out: a soft thump with a click"""
    rnd = random.Random(11)
    n = int(0.22 * RATE)
    out = []
    for i in range(n):
        t = i / RATE
        thump = math.sin(2 * math.pi * (95 - 120 * t) * t) * math.exp(-t * 26)
        click = rnd.uniform(-1, 1) * math.exp(-t * 180) * 0.6
        out.append(thump + click)
    return _normalize(_lowpass(out, 2400), 0.8)


def skid():
    """tyres sliding (a loop): a band of noise that wavers"""
    rnd = random.Random(5)
    n = int(RATE / 14) * 7                                 # whole wavers
    fade = int(0.05 * RATE)
    raw = [rnd.uniform(-1, 1) for _ in range(n + fade)]
    hi = _lowpass(raw, 3400)
    lo = _lowpass(raw, 1300)
    out = [(h - l) * (0.75 + 0.25 * math.sin(2 * math.pi * 14 * i / RATE)) for i, (h, l) in enumerate(zip(hi, lo))]
    return _normalize(_loop(out, n, fade), 0.5)


def engine_stop():
    """the engine winds down"""
    n = int(0.7 * RATE)
    out = []
    ph = 0.0
    for i in range(n):
        t = i / n
        f = 49 * (1 - 0.65 * t)
        ph += 2 * math.pi * f / RATE
        out.append((math.sin(ph) + 0.5 * math.sin(2 * ph + 0.7)) * (1 - t) ** 1.5 * 0.6)
    return _normalize(out, 0.6)


def poof():
    """a car appears (or goes back into the pockets): a soft whoosh under a rising sparkle of bells"""
    rnd = random.Random(23)
    n = int(0.9 * RATE)
    noise = _lowpass([rnd.uniform(-1, 1) for _ in range(n)], 1800)
    out = [noise[i] * math.sin(math.pi * min(1.0, i / (0.45 * RATE))) ** 2 * 0.5 for i in range(n)]
    for k, f in enumerate((1046.5, 1318.5, 1568.0, 2093.0, 2637.0)):         # C6 E6 G6 C7 E7
        start = int((0.05 + 0.09 * k) * RATE)
        for i in range(start, n):
            t = (i - start) / RATE
            out[i] += (math.sin(2 * math.pi * f * t) + 0.3 * math.sin(2 * math.pi * 2.01 * f * t)) * math.exp(-t * 7) * 0.35
    return _normalize(out, 0.7)


def vehicle_sounds(style="sporty"):
    return {"engine.wav": wav(engine_loop(style)), "start.wav": wav(starter(style)), "horn.wav": wav(horn()),
            "door.wav": wav(door()), "skid.wav": wav(skid()), "stop.wav": wav(engine_stop()), "poof.wav": wav(poof())}
