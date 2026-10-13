"""Build the 'Thirty Years Away' music video scene from scratch.

    python video/prepare_audio.py "Thirty Years Away.m4a"        # once per new song render
    blender -b --factory-startup -P video/build_scene.py -- [--vertical]

Everything is anchored to Suno's timed lyrics (video/lyrics_timed.srt), so a
re-rendered song re-syncs by re-running the two commands above.
"""
import importlib
import json
import math
import random
import re
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Euler, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lib  # noqa: E402

importlib.reload(lib)
from lib import F, FPS  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
VERTICAL = "--vertical" in argv
RES = (1080, 1920) if VERTICAL else (1920, 1080)
OUT = HERE / ("thirty_years_away_vertical.blend" if VERTICAL else "thirty_years_away.blend")
if "--out" in argv:
    OUT = Path(argv[argv.index("--out") + 1])

AUD = json.loads((HERE / "audio_features.json").read_text())
AUDIO_SRC = Path((HERE / "audio_source.txt").read_text().strip())
AUDIO_DUR = AUD["duration"]
TAIL = 8.0  # silent tail after the music for the last (unsung) line + end card
DUR = AUDIO_DUR + TAIL
N = int(math.floor(DUR * FPS))
T = np.arange(N) / FPS
BPM = AUD["bpm"]
random.seed(7)
RNG = np.random.default_rng(7)

# palette (linear-ish RGB)
CYAN = (0.10, 0.80, 1.00)
MAGENTA = (1.00, 0.18, 0.75)
VIOLET = (0.45, 0.18, 1.00)
GOLD = (1.00, 0.62, 0.12)
RED = (1.00, 0.06, 0.05)
GREEN = (0.20, 1.00, 0.35)
WHITE = (1.0, 1.0, 1.0)
YELLOW = (1.0, 0.85, 0.15)
ORANGE = (1.0, 0.40, 0.08)

CZ = 3.4  # tokamak centre height
C = (0.0, 0.0, CZ)


# ==========================================================================
# timeline from Suno's timed lyrics
# ==========================================================================
def _ts(s):
    h, m, rest = s.strip().split(":")
    sec, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000


def parse_srt(path):
    out = []
    for block in re.split(r"\n\s*\n", path.read_text(encoding="utf-8").strip()):
        ls = block.strip().splitlines()
        if len(ls) >= 3 and "-->" in ls[1]:
            a, b = ls[1].split("-->")
            out.append((_ts(a), _ts(b), " ".join(ls[2:]).strip()))
    return out


KINDS = [("final chorus", "final"), ("pre-chorus", "pre"), ("chorus", "chorus"), ("verse", "verse"),
         ("intro", "intro"), ("bridge", "bridge"), ("breakdown", "breakdown"), ("outro", "outro"), ("end", "end")]
SECTIONS, LINES = [], []
_count = {}
for a, b, txt in parse_srt(HERE / "lyrics_timed.srt"):
    if txt.startswith("[") and txt.endswith("]"):
        name = txt[1:-1].strip().lower()
        kind = next((k for key, k in KINDS if name.startswith(key)), None)
        if kind is None:  # stage direction; a "bass comes back" cue splits the breakdown in two
            cur = SECTIONS[-1] if SECTIONS else None
            if cur and cur["kind"] == "breakdown" and any(l["sec"] is cur for l in LINES) and \
                    any(w in name for w in ("bass", "build")):
                kind = "breakdown"
            else:
                continue
        if kind == "end":
            continue
        _count[kind] = _count.get(kind, 0) + 1
        SECTIONS.append(dict(kind=kind, n=_count[kind], id=f"{kind}{_count[kind]}", t0=a))
    elif SECTIONS:
        if b - a < 0.05 and LINES:  # zero-length backing vocal: show with the previous line
            LINES[-1]["text"] += "\n" + txt
            LINES[-1]["merged"] = True
        else:
            LINES.append(dict(t0=a, t1=min(b, DUR), text=txt, sec=SECTIONS[-1]))
# Suno didn't sing the last line, so it plays as a caption in the silent tail.
LAST_LINE = "And I'll know by lunch."
lunch_line = next((l for l in LINES if "by lunch" in l["text"].lower()), None)
if lunch_line is None and SECTIONS:
    lunch_line = dict(text=LAST_LINE, sec=SECTIONS[-1])
    LINES.append(lunch_line)
# video/mix_ending.py splices the sung line from an earlier render onto the end of this one
_mix = HERE / "song_mix.json"
MIX = json.loads(_mix.read_text()) if _mix.exists() else None
if MIX and MIX.get("source") != AUDIO_SRC.with_suffix(".wav").name:
    MIX = None  # made for a different render of the song
if lunch_line:
    lunch_line["t0"], lunch_line["t1"] = (MIX["lunch_t0"], MIX["lunch_t1"]) if MIX else (AUDIO_DUR + 0.3, AUDIO_DUR + 3.6)
for i, s in enumerate(SECTIONS):
    s["t1"] = SECTIONS[i + 1]["t0"] if i + 1 < len(SECTIONS) else DUR
    s["lines"] = [l for l in LINES if l["sec"] is s]
SEC = {s["id"]: s for s in SECTIONS}
CHORUSES = [s for s in SECTIONS if s["kind"] in ("chorus", "final")]
# Suno gives a stacked backing vocal the same timestamp as its line; estimate where it actually starts
for l in LINES:
    dur = l["t1"] - l["t0"]
    l["split"] = l["t0"] + min(0.52 * dur, dur - 2.5) if l.get("merged") and dur > 5 else l["t1"]
print("sections:", [(s["id"], round(s["t0"], 1)) for s in SECTIONS])


def L(sub, n=1):
    """n-th lyric line containing `sub` (case-insensitive), or None."""
    hits = [l for l in LINES if sub.lower() in l["text"].lower()]
    return hits[n - 1] if len(hits) >= n else None


def first(sec_id):
    s = SEC.get(sec_id)
    return s["lines"][0] if s and s["lines"] else None


# ==========================================================================
# scene reset + render settings
# ==========================================================================
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.name = "ThirtyYearsAway"
sc.render.fps = FPS
sc.frame_start, sc.frame_end = 1, N
sc.render.resolution_x, sc.render.resolution_y = RES
sc.render.resolution_percentage = 100
sc.render.engine = "BLENDER_EEVEE"
ee = sc.eevee
ee.taa_render_samples = 24
ee.use_raytracing = True
ee.use_shadows = True
ee.shadow_pool_size = "1024"  # 1080p overflowed the default pool ("Shadow buffer full")
ee.volumetric_tile_size = "8"
ee.volumetric_samples = 48
ee.volumetric_end = 260
ee.use_volumetric_shadows = False
sc.view_settings.view_transform = "Khronos PBR Neutral"  # keeps neon colours saturated
for look in ("Medium High Contrast",):
    try:
        sc.view_settings.look = look
        break
    except Exception:
        pass
sc.render.film_transparent = False
sc.render.filter_size = 1.0  # crisper anti-aliasing

STAGE = lib.coll("Stage")
TOK = lib.coll("Tokamak")
FX = lib.coll("FX")
RIG = lib.coll("CameraRig")
HUDC = lib.coll("HUD")
ROBOT = lib.coll("Robot")

# soundtrack in the sequencer (for scrubbing in the UI; render.py muxes the audio itself)
se = sc.sequence_editor_create()
snd = HERE / "song_mix.wav" if MIX else     next((p for p in (AUDIO_SRC.with_suffix(".wav"), AUDIO_SRC.with_suffix(".mp3"), AUDIO_SRC) if p.exists()), AUDIO_SRC)
se.strips.new_sound("song", str(snd), channel=1, frame_start=1)
sc.sync_mode = "AUDIO_SYNC"


# ==========================================================================
# envelopes -> per-frame scene properties (read by shaders / drivers)
# ==========================================================================
def trap(t0, t1, fi=0.2, fo=0.2):
    return np.clip((T - t0) / max(fi, 1e-3), 0, 1) * np.clip((t1 - T) / max(fo, 1e-3), 0, 1)


def spike(t0, decay=0.25):
    return np.where(T >= t0, np.exp(-np.maximum(T - t0, 0) / decay), 0.0)


def ramp(t0, t1, v0=0.0, v1=1.0):
    return np.interp(T, [t0, t1], [v0, v1])


def follower(x, release=0.86):
    y = np.zeros_like(x)
    for i, v in enumerate(x):
        y[i] = max(v, y[i - 1] * release) if i else v
    return y


def slow_flicker(rate, p_off):
    """On/off pattern that changes at most `rate` times per second (no strobing)."""
    blocks = RNG.random(int(DUR * rate) + 2) > p_off
    return blocks[(T * rate).astype(int)].astype(float)


def aud(name):
    a = np.array(AUD[name][:N], dtype=float)
    return np.pad(a, (0, max(0, N - len(a))))


ENV = {}
ENV["aud_sub"] = follower(aud("sub") ** 1.5)
ENV["aud_high"] = follower(aud("high"), 0.8)
ENV["aud_rms"] = aud("rms")

# plasma brightness
pl = np.ones(N)
intro = SEC.get("intro1")
if intro:
    l1, l2, l3 = (intro["lines"] + [None] * 3)[:3]
    t_on = l2["t0"] if l2 else intro["t0"] + 4
    pl = np.interp(T, [0, t_on, t_on + 0.01, (l3["t0"] if l3 else t_on + 4), intro["t1"]], [0, 0, 0.25, 0.55, 1.0])
    flick = slow_flicker(4, 0.45)
    win = (T >= t_on) & (T < t_on + 1.6)
    pl = np.where(win, pl * flick, pl)
broke = L("broke again")
if broke:
    w = (T >= broke["t0"] + 0.4) & (T < broke["t0"] + 2.0)
    pl = np.where(w, 0.05 + 0.4 * slow_flicker(4, 0.6), pl)
dis = L("Disruption")
if dis:
    pl = pl * (1 - 0.95 * trap(dis["t0"] + 0.25, dis["t1"] + 1.5, 0.05, 2.0))
for s in SECTIONS:
    if s["kind"] == "breakdown":
        pl = np.where((T >= s["t0"]) & (T < s["t1"]), 0.3 if s["n"] == 1 else ramp(s["t0"], s["t1"], 0.3, 1.0), pl)
out_sec = SEC.get("outro1")
if out_sec:
    bench = L("on a bench")
    t_off = bench["t0"] if bench else out_sec["t1"]
    pl = pl * np.interp(T, [out_sec["t0"], t_off], [1, 0])
ENV["plasma"] = pl

flash = np.zeros(N)
white = np.zeros(N)
for k in range(1, 6):
    ig = L("We got ignition", k)
    if ig:
        flash += spike(ig["t0"], 0.3) * 1.0
        white += spike(ig["t0"], 0.15) * 0.55
for k in range(1, 4):
    elm = L("ELM crash", k)
    if elm:
        for j in range(int((elm["split"] - elm["t0"]) * 2)):
            flash += spike(elm["t0"] + j / 2, 0.15) * 0.3
if dis:
    flash += spike(dis["t0"], 0.3) * 1.5
    white += spike(dis["t0"], 0.12) * 0.4
ENV["flash"] = np.clip(flash, 0, 3)
ENV["white"] = np.clip(white, 0, 1)

alarm = np.zeros(N)
pre2 = SEC.get("pre2")
if pre2:
    pv_cut = next((l["split"] for l in pre2["lines"] if "pee-vee" in l["text"].lower()), pre2["t1"])
    alarm = trap(pre2["t0"], pv_cut, 0.2, 0.15)
ENV["alarm"] = alarm
ENV["alarm_pulse"] = alarm * (0.25 + 0.3 * np.sin(2 * np.pi * 2.0 * T))

v2 = SEC.get("verse2")
ENV["neutron"] = trap(v2["t0"], v2["t1"], 0.5, 0.5) if v2 else np.zeros(N)
dmg = np.zeros(N)
dpa, trit = L("dee-pee-ay"), L("tritium")
if dpa:
    end_d = SEC["chorus2"]["t0"] + 6 if "chorus2" in SEC else dpa["t0"] + 30
    dmg = np.interp(T, [dpa["t0"], trit["t0"] if trit else dpa["t1"] + 3, end_d - 6, end_d], [0, 1, 1, 0])
    dmg = np.where(T < dpa["t0"], 0, dmg)
ENV["damage"] = dmg
dv, noz = L("divertor"), L("rocket nozzle")
ENV["divertor"] = 0.08 + (trap(dv["t0"], (noz or dv)["t1"] + 0.5, 1.5, 1.0) if dv else 0)

wob = np.zeros(N)
cat = L("like a cat")
if cat:
    wob += trap(cat["t0"], cat["t1"] + 0.5, 0.4, 0.8)
if dis:
    wob += trap(dis["t0"], dis["t1"], 0.05, 0.5) * 1.5
ENV["wobble"] = wob

sign = np.zeros(N)
coil = np.full(N, 0.12)
for s in CHORUSES:
    on = trap(s["t0"], s["t1"], 0.05, 0.3)
    fl = np.where((T >= s["t0"]) & (T < s["t0"] + 0.7), slow_flicker(6, 0.5), 1.0)
    sign = np.maximum(sign, on * fl)
    coil = np.maximum(coil, on)
bd2 = SEC.get("breakdown2")
if bd2:
    coil = np.maximum(coil, ramp(bd2["t0"], bd2["t1"], 0.1, 0.6) * trap(bd2["t0"], bd2["t1"], 0.1, 0.01))
ENV["sign"] = sign
ENV["coilglow"] = coil
ENV["chase"] = T * BPM / 60 / 8

moody = np.zeros(N)
br = SEC.get("bridge1")
if br:
    moody += trap(br["t0"], br["t1"], 1.5, 0.8)
bd1 = SEC.get("breakdown1")
if bd1:
    moody += trap(bd1["t0"], bd1["t1"], 0.2, 0.01) * 0.6
if bd2:
    moody += trap(bd2["t0"], bd2["t1"], 0.01, 0.2) * ramp(bd2["t0"], bd2["t1"], 0.6, 0.0)
ENV["moody"] = np.clip(moody, 0, 1)

fin = SEC.get("final1")
ENV["gold"] = trap(fin["t0"], fin["t1"] + 3, 0.15, 3) if fin else np.zeros(N)
dn = L("a donut")
ENV["donut"] = np.clip((T - dn["t0"]) / 0.6, 0, 1) if dn else np.zeros(N)

fade = np.interp(T, [0, 1.5], [1, 0])
fade = np.maximum(fade, np.interp(T, [DUR - 1.6, DUR - 0.2], [0, 1]))
ENV["fade"] = fade

wk = L("It works")
led = np.zeros(N)
ledg = np.zeros(N)
if wk:
    led = np.where(T >= wk["t0"] - 1.0, 1.0, 0.0)
    blink = (np.floor((T - wk["t0"]) * 4) % 2 == 0).astype(float)
    led = np.where((T >= wk["t0"]) & (T < wk["t1"] - 0.6), blink, led)
    ledg = np.where(T >= wk["t1"] - 0.6, 1.0, 0.0)
ENV["led"] = led
ENV["led_green"] = ledg

# solar aside: on the "(...compete with pee-vee)" backing vocal and on "Solar says: ..."
pv = next((l for l in LINES if "pee-vee" in l["text"].lower()), None)
solar = L("Solar says")
SOLAR_WIN = []
if pv:
    SOLAR_WIN.append((pv["split"], pv["t1"]))
if solar:
    i_s = LINES.index(solar)
    nxt = LINES[i_s + 1] if i_s + 1 < len(LINES) else None
    SOLAR_WIN.append((solar["t0"], (nxt["t0"] if nxt else solar["t1"]) + 1.2))
bat = np.zeros(N)
for a_, b_ in SOLAR_WIN:
    bat = np.maximum(bat, np.clip((T - a_) / max(b_ - a_ - 0.6, 0.5), 0, 1) * (T < b_ + 0.1))
ENV["battery"] = 0.12 + 0.88 * bat

for k, v in ENV.items():
    lib.scene_prop(sc, k, v)


def scene_var(name, alias):
    return (alias, "SCENE", sc, f'["{name}"]')


# ==========================================================================
# world
# ==========================================================================
world = bpy.data.worlds.new("World")
sc.world = world
if world.node_tree is None:
    world.use_nodes = True
wn = world.node_tree
wn.nodes.clear()
wo = wn.nodes.new("ShaderNodeOutputWorld")
bg = wn.nodes.new("ShaderNodeBackground")
bg.inputs["Color"].default_value = (0.004, 0.005, 0.014, 1)
bg.inputs["Strength"].default_value = 1.0
wn.links.new(bg.outputs[0], wo.inputs["Surface"])

# ==========================================================================
# stage: grid floor, synthwave sun, neon sign
# ==========================================================================
floor = lib.plane("Floor", 500, 500, STAGE)
m, nt, out = lib.new_mat("FloorGrid")
p = nt.nodes.new("ShaderNodeBsdfPrincipled")
p.inputs["Base Color"].default_value = (0.004, 0.004, 0.008, 1)
p.inputs["Roughness"].default_value = 0.18
p.inputs["Specular IOR Level"].default_value = 0.6
tc = nt.nodes.new("ShaderNodeTexCoord")
sx = nt.nodes.new("ShaderNodeSeparateXYZ")
nt.links.new(tc.outputs["Object"], sx.inputs[0])


def gridline(coord):
    f = lib.math_(nt, "FRACT", lib.math_(nt, "MULTIPLY", coord, 0.5))
    g = lib.math_(nt, "MULTIPLY", lib.math_(nt, "ABSOLUTE", lib.math_(nt, "SUBTRACT", f, 0.5)), 2.0)
    return lib.math_(nt, "POWER", g, 70.0)


line = lib.math_(nt, "MAXIMUM", gridline(sx.outputs[0]), gridline(sx.outputs[1]))
vl = nt.nodes.new("ShaderNodeVectorMath")
vl.operation = "LENGTH"
nt.links.new(tc.outputs["Object"], vl.inputs[0])
fadeout = nt.nodes.new("ShaderNodeMapRange")
nt.links.new(vl.outputs["Value"], fadeout.inputs[0])
fadeout.inputs[1].default_value, fadeout.inputs[2].default_value = 15, 170
fadeout.inputs[3].default_value, fadeout.inputs[4].default_value = 1, 0
col = lib.mix_rgb(nt, lib.attr(nt, "moody"), CYAN, VIOLET)
col = lib.mix_rgb(nt, lib.attr(nt, "gold"), col, GOLD)
strength = lib.math_(nt, "MULTIPLY", line, fadeout.outputs[0])
strength = lib.math_(nt, "MULTIPLY", strength,
                     lib.math_(nt, "ADD", 1.0, lib.math_(nt, "MULTIPLY", lib.attr(nt, "aud_sub"), 1.2)))
nt.links.new(col, p.inputs["Emission Color"])
nt.links.new(strength, p.inputs["Emission Strength"])
nt.links.new(p.outputs[0], out.inputs["Surface"])
floor.data.materials.append(m)

# synthwave sun on the horizon (the one fusion reactor that works)
verts = [(0, 0, 0)] + [(math.cos(2 * math.pi * i / 128), math.sin(2 * math.pi * i / 128), 0) for i in range(128)]
faces = [(0, i + 1, (i + 1) % 128 + 1) for i in range(128)]
sun = lib.mesh_obj("Sun", verts, faces, STAGE, smooth=False)
sun.location = (0, 230, 16)
sun.rotation_euler = (math.radians(90), 0, 0)
sun.scale = (50, 50, 50)
m, nt, out = lib.new_mat("Sun", blended=True)
tc = nt.nodes.new("ShaderNodeTexCoord")
sx = nt.nodes.new("ShaderNodeSeparateXYZ")
nt.links.new(tc.outputs["Object"], sx.inputs[0])
yv = sx.outputs[1]
grad = nt.nodes.new("ShaderNodeMapRange")
nt.links.new(yv, grad.inputs[0])
grad.inputs[1].default_value, grad.inputs[2].default_value = -1, 1
col = lib.mix_rgb(nt, grad.outputs[0], MAGENTA, YELLOW)
col = lib.mix_rgb(nt, lib.math_(nt, "MULTIPLY", lib.attr(nt, "moody"), 0.7), col, VIOLET)
em = nt.nodes.new("ShaderNodeEmission")
nt.links.new(col, em.inputs["Color"])
nt.links.new(lib.math_(nt, "SUBTRACT", 1.3, lib.math_(nt, "MULTIPLY", lib.attr(nt, "moody"), 0.7)),
             em.inputs["Strength"])
below = lib.math_(nt, "LESS_THAN", yv, 0.15)
fr = lib.math_(nt, "FRACT", lib.math_(nt, "ADD", lib.math_(nt, "MULTIPLY", yv, 7.0), 10.0))
thr = lib.math_(nt, "MULTIPLY", lib.math_(nt, "SUBTRACT", 0.15, yv), 0.5)
gap = lib.math_(nt, "LESS_THAN", fr, thr)
alpha = lib.math_(nt, "SUBTRACT", 1.0, lib.math_(nt, "MULTIPLY", below, gap), clamp=True)
tr = nt.nodes.new("ShaderNodeBsdfTransparent")
mx = nt.nodes.new("ShaderNodeMixShader")
nt.links.new(alpha, mx.inputs[0])
nt.links.new(tr.outputs[0], mx.inputs[1])
nt.links.new(em.outputs[0], mx.inputs[2])
nt.links.new(mx.outputs[0], out.inputs["Surface"])
sun.data.materials.append(m)
lib.no_shadow(sun)

# neon sign
m, nt, out = lib.new_mat("SignNeon")
em = nt.nodes.new("ShaderNodeEmission")
nt.links.new(lib.mix_rgb(nt, lib.attr(nt, "gold"), MAGENTA, GOLD), em.inputs["Color"])
s_ = lib.math_(nt, "MULTIPLY", lib.attr(nt, "sign"),
               lib.math_(nt, "ADD", 6.0, lib.math_(nt, "MULTIPLY", lib.attr(nt, "aud_sub"), 2.0)))
nt.links.new(lib.math_(nt, "ADD", s_, 0.05), em.inputs["Strength"])
nt.links.new(em.outputs[0], out.inputs["Surface"])
M_SIGN = m
M_SIGN_SMALL = lib.emission_mat("SignSmall", CYAN, 4.0, blended=False)
sign1 = lib.text("Sign_30", "30 YEARS AWAY", STAGE, 6.5, [M_SIGN], fontfile="impact.ttf",
                 loc=(0, 36, 10.5), rot=(math.radians(90), 0, 0), extrude=0.25, hud=False)
sign2 = lib.text("Sign_top", "FUSION ENERGY IS", STAGE, 2.2, [M_SIGN_SMALL], fontfile="bahnschrift.ttf",
                 loc=(0, 36, 14.6), rot=(math.radians(90), 0, 0), extrude=0.1, hud=False)
lib.drive(M_SIGN_SMALL.node_tree.nodes["Emission"].inputs["Strength"], "default_value", "s*5+0.05",
          [scene_var("sign", "s")])

# ==========================================================================
# tokamak
# ==========================================================================
tok = lib.empty("Tokamak", TOK, loc=C)
CUT0, CUTA = -math.pi / 4, 1.5 * math.pi  # cut-away wedge faces -Y (toward camera azimuth 0)

# --- plasma ---
plasma = lib.spin("Plasma", lib.d_profile(3.0, 0.95, 1.65, 0.35, 72), TOK, segs=144, parent=tok)
m, nt, out = lib.new_mat("Plasma", blended=True)
tc = nt.nodes.new("ShaderNodeTexCoord")
nz = nt.nodes.new("ShaderNodeTexNoise")
nz.noise_dimensions = "4D"
nz.inputs["Scale"].default_value = 0.9
nz.inputs["Detail"].default_value = 2
nz.inputs["Distortion"].default_value = 0.15
nt.links.new(tc.outputs["Object"], nz.inputs["Vector"])
lib.drive(nz.inputs["W"], "default_value", "frame/45", [])
cr = nt.nodes.new("ShaderNodeValToRGB")
els = cr.color_ramp.elements
els[0].position, els[0].color = 0.32, (*MAGENTA, 1)
els[1].position, els[1].color = 0.78, (0.85, 0.95, 1.0, 1)
e = els.new(0.5)
e.color = (*VIOLET, 1)
e = els.new(0.64)
e.color = (*CYAN, 1)
nt.links.new(nz.outputs["Fac"], cr.inputs["Fac"])
col = lib.mix_rgb(nt, lib.attr(nt, "gold"), cr.outputs["Color"], GOLD)
col = lib.mix_rgb(nt, lib.math_(nt, "MULTIPLY", lib.attr(nt, "moody"), 0.6), col, VIOLET)
em = nt.nodes.new("ShaderNodeEmission")
nt.links.new(col, em.inputs["Color"])
lw = nt.nodes.new("ShaderNodeLayerWeight")
lw.inputs["Blend"].default_value = 0.5
edge = lib.math_(nt, "ADD", 0.08, lib.math_(nt, "MULTIPLY", lib.math_(nt, "POWER", lw.outputs["Facing"], 2.4), 1.4))
contrast = lib.math_(nt, "POWER", nz.outputs["Fac"], 2.0)
st = lib.math_(nt, "ADD", 0.7, lib.math_(nt, "MULTIPLY", lib.attr(nt, "aud_sub"), 1.0))
st = lib.math_(nt, "ADD", st, lib.math_(nt, "MULTIPLY", lib.attr(nt, "aud_high"), 1.0))
st = lib.math_(nt, "MULTIPLY", lib.math_(nt, "MULTIPLY", st, lib.attr(nt, "plasma")), lib.math_(nt, "MULTIPLY", edge, lib.math_(nt, "ADD", 0.4, lib.math_(nt, "MULTIPLY", contrast, 3.0))))
st = lib.math_(nt, "ADD", st, lib.math_(nt, "MULTIPLY", lib.attr(nt, "flash"), 8.0))
nt.links.new(st, em.inputs["Strength"])
tr = nt.nodes.new("ShaderNodeBsdfTransparent")
mx = nt.nodes.new("ShaderNodeAddShader")
nt.links.new(tr.outputs[0], mx.inputs[0])
nt.links.new(em.outputs[0], mx.inputs[1])
# donut mode: pink frosting on top, dough underneath
sx = nt.nodes.new("ShaderNodeSeparateXYZ")
nt.links.new(tc.outputs["Object"], sx.inputs[0])
nz2 = nt.nodes.new("ShaderNodeTexNoise")
nz2.inputs["Scale"].default_value = 3.0
nt.links.new(tc.outputs["Object"], nz2.inputs["Vector"])
top = lib.math_(nt, "GREATER_THAN", lib.math_(nt, "ADD", sx.outputs[2], lib.math_(nt, "MULTIPLY", nz2.outputs["Fac"], 0.6)), 0.05)
fro = nt.nodes.new("ShaderNodeBsdfPrincipled")
nt.links.new(lib.mix_rgb(nt, top, (0.75, 0.42, 0.17), (1.0, 0.35, 0.62)), fro.inputs["Base Color"])
nt.links.new(lib.math_(nt, "SUBTRACT", 0.7, lib.math_(nt, "MULTIPLY", top, 0.55)), fro.inputs["Roughness"])
mx2 = nt.nodes.new("ShaderNodeMixShader")
nt.links.new(lib.attr(nt, "donut"), mx2.inputs[0])
nt.links.new(mx.outputs[0], mx2.inputs[1])
nt.links.new(fro.outputs[0], mx2.inputs[2])
nt.links.new(mx2.outputs[0], out.inputs["Surface"])
plasma.data.materials.append(m)
lib.no_shadow(plasma)

# plasma wobble ("a cat that will escape you if it can")
wtex = bpy.data.textures.new("PlasmaWobble", "CLOUDS")
wtex.noise_scale = 1.2
wob_ctl = lib.empty("WobbleCtl", TOK, parent=tok)
lib.drive(wob_ctl, "location", "frame/50", [], index=0)
lib.drive(wob_ctl, "rotation_euler", "frame/90", [], index=2)
dm = plasma.modifiers.new("Wobble", "DISPLACE")
dm.texture = wtex
dm.texture_coords = "OBJECT"
dm.texture_coords_object = wob_ctl
dm.mid_level = 0.5
lib.drive(dm, "strength", "w*0.9", [scene_var("wobble", "w")])

# --- first wall (tiles + glowing cracks + divertor heat) ---
fw = lib.spin("FirstWall", lib.d_profile(3.0, 1.13, 1.6, 0.33, 72), TOK, segs=108, start=CUT0, angle=CUTA, parent=tok)
m, nt, out = lib.new_mat("FirstWall")
p = nt.nodes.new("ShaderNodeBsdfPrincipled")
tc = nt.nodes.new("ShaderNodeTexCoord")
bk = nt.nodes.new("ShaderNodeTexBrick")
bk.inputs["Scale"].default_value = 5.5
bk.inputs["Color1"].default_value = (0.05, 0.05, 0.055, 1)
bk.inputs["Color2"].default_value = (0.09, 0.09, 0.1, 1)
bk.inputs["Mortar"].default_value = (0.01, 0.01, 0.012, 1)
bk.inputs["Mortar Size"].default_value = 0.012
nt.links.new(tc.outputs["Object"], bk.inputs["Vector"])
nt.links.new(bk.outputs["Color"], p.inputs["Base Color"])
p.inputs["Roughness"].default_value = 0.55
p.inputs["Metallic"].default_value = 0.3
vor = nt.nodes.new("ShaderNodeTexVoronoi")
vor.feature = "DISTANCE_TO_EDGE"
vor.inputs["Scale"].default_value = 2.2
nt.links.new(tc.outputs["Object"], vor.inputs["Vector"])
crack = lib.math_(nt, "LESS_THAN", vor.outputs["Distance"], 0.025)
gate_n = nt.nodes.new("ShaderNodeTexNoise")
gate_n.inputs["Scale"].default_value = 0.8
nt.links.new(tc.outputs["Object"], gate_n.inputs["Vector"])
gate = lib.math_(nt, "GREATER_THAN", gate_n.outputs["Fac"], lib.math_(nt, "SUBTRACT", 1.05, lib.attr(nt, "damage")))
crack_e = lib.math_(nt, "MULTIPLY", lib.math_(nt, "MULTIPLY", crack, gate), lib.math_(nt, "MULTIPLY", lib.attr(nt, "damage"), 12.0))
sx = nt.nodes.new("ShaderNodeSeparateXYZ")
nt.links.new(tc.outputs["Object"], sx.inputs[0])
div_mask = nt.nodes.new("ShaderNodeMapRange")
nt.links.new(sx.outputs[2], div_mask.inputs[0])
div_mask.inputs[1].default_value, div_mask.inputs[2].default_value = -1.25, -1.75
div_e = lib.math_(nt, "MULTIPLY", div_mask.outputs[0], lib.math_(nt, "MULTIPLY", lib.attr(nt, "divertor"), 30.0))
nt.links.new(lib.math_(nt, "ADD", crack_e, div_e), p.inputs["Emission Strength"])
p.inputs["Emission Color"].default_value = (1.0, 0.42, 0.12, 1)
nt.links.new(p.outputs[0], out.inputs["Surface"])
fw.data.materials.append(m)
for poly in fw.data.polygons:  # face inward
    poly.flip()

# --- vacuum vessel (cut away) ---
vv = lib.spin("VacuumVessel", lib.d_profile(3.0, 1.26, 1.58, 0.33, 72), TOK, segs=108, start=CUT0, angle=CUTA, parent=tok)
sol = vv.modifiers.new("Thickness", "SOLIDIFY")
sol.thickness = 0.12
sol.offset = 1.0
sol.use_rim = True
m, nt, p = lib.principled("Vessel", (0.22, 0.24, 0.27), metallic=0.85, roughness=0.3)
nt.links.new(lib.mix_rgb(nt, lib.attr(nt, "donut"), (0.22, 0.24, 0.27), (0.72, 0.42, 0.18)), p.inputs["Base Color"])
nt.links.new(lib.math_(nt, "SUBTRACT", 0.85, lib.math_(nt, "MULTIPLY", lib.attr(nt, "donut"), 0.85)), p.inputs["Metallic"])
vv.data.materials.append(m)

# --- TF coils (chase lights) ---
m, nt, p = lib.principled("Coil", (0.85, 0.45, 0.22), metallic=1.0, roughness=0.32)
ph = lib.math_(nt, "SUBTRACT", lib.attr(nt, "chase"), lib.attr(nt, "phase", "OBJECT"))
wave = lib.math_(nt, "POWER", lib.math_(nt, "ADD", 0.5, lib.math_(nt, "MULTIPLY", lib.math_(nt, "COSINE", lib.math_(nt, "MULTIPLY", ph, 2 * math.pi)), 0.5)), 14.0)
glow = lib.math_(nt, "MULTIPLY", lib.math_(nt, "ADD", 0.03, wave), lib.attr(nt, "coilglow"))
glow = lib.math_(nt, "MULTIPLY", glow, lib.math_(nt, "ADD", 2.0, lib.math_(nt, "MULTIPLY", lib.attr(nt, "aud_sub"), 2.0)))
q = lib.attr(nt, "q", "OBJECT")
nt.links.new(lib.math_(nt, "ADD", glow, lib.math_(nt, "MULTIPLY", q, 10.0)), p.inputs["Emission Strength"])
ccol = lib.mix_rgb(nt, lib.attr(nt, "gold"), CYAN, GOLD)
ccol = lib.mix_rgb(nt, lib.math_(nt, "MINIMUM", q, 1.0), ccol, WHITE)
nt.links.new(ccol, p.inputs["Emission Color"])
M_COIL = m
coil_prof = lib.d_profile(3.15, 1.95, 1.45, 0.45, 64)
COILS = []
for k in range(16):
    phi = 2 * math.pi * k / 16
    deg = (math.degrees(phi) + 180) % 360 - 180
    if -135 < deg < -45:
        continue  # leave the cut-away side open
    cu = bpy.data.curves.new(f"TF{k:02d}", "CURVE")
    cu.dimensions = "3D"
    sp = cu.splines.new("POLY")
    sp.points.add(len(coil_prof) - 1)
    for pt, (R, Z) in zip(sp.points, coil_prof):
        pt.co = (R * math.cos(phi), R * math.sin(phi), Z, 1)
    sp.use_cyclic_u = True
    cu.bevel_depth = 0.17
    cu.bevel_resolution = 3
    cu.extrude = 0.08
    cu.materials.append(M_COIL)
    ob = bpy.data.objects.new(f"TF{k:02d}", cu)
    ob.parent = tok
    ob["phase"] = k / 16
    ob["q"] = 0.0
    lib.link(ob, TOK)
    COILS.append((deg, ob))

# --- central solenoid, PF coils, legs, ports ---
bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=0.85, depth=5.4, location=C)
cs = bpy.context.active_object
cs.name = "CentralSolenoid"
for c in cs.users_collection:
    c.objects.unlink(cs)
TOK.objects.link(cs)
m, nt, p = lib.principled("Solenoid", (0.08, 0.09, 0.11), metallic=0.8, roughness=0.25)
tc = nt.nodes.new("ShaderNodeTexCoord")
sx = nt.nodes.new("ShaderNodeSeparateXYZ")
nt.links.new(tc.outputs["Object"], sx.inputs[0])
band = lib.math_(nt, "POWER", lib.math_(nt, "ABSOLUTE", lib.math_(nt, "SINE", lib.math_(nt, "MULTIPLY", sx.outputs[2], 9.0))), 30.0)
nt.links.new(lib.math_(nt, "MULTIPLY", band, lib.math_(nt, "ADD", 1.0, lib.math_(nt, "MULTIPLY", lib.attr(nt, "aud_high"), 3.0))), p.inputs["Emission Strength"])
nt.links.new(lib.mix_rgb(nt, lib.attr(nt, "gold"), MAGENTA, GOLD), p.inputs["Emission Color"])
cs.data.materials.append(m)
m_pf, _, _ = lib.principled("PFCoil", (0.8, 0.42, 0.2), metallic=1.0, roughness=0.3)
for i, (R, z) in enumerate([(5.7, 1.7), (5.7, -1.7), (2.9, 3.25), (2.9, -3.25)]):
    bpy.ops.mesh.primitive_torus_add(major_radius=R, minor_radius=0.14, major_segments=128, minor_segments=12,
                                     location=(0, 0, CZ + z))
    ob = bpy.context.active_object
    ob.name = f"PF{i}"
    for c in ob.users_collection:
        c.objects.unlink(ob)
    TOK.objects.link(ob)
    ob.data.materials.append(m_pf)
    for poly in ob.data.polygons:
        poly.use_smooth = True
m_leg, _, _ = lib.principled("Legs", (0.12, 0.12, 0.13), metallic=0.6, roughness=0.5)
for k in range(8):
    phi = 2 * math.pi * (k + 0.5) / 8
    bpy.ops.mesh.primitive_cube_add(size=1, location=(3.4 * math.cos(phi), 3.4 * math.sin(phi), 0.75))
    ob = bpy.context.active_object
    ob.name = f"Leg{k}"
    ob.scale = (0.35, 0.35, 1.5)
    ob.rotation_euler = (0, 0, phi)
    for c in ob.users_collection:
        c.objects.unlink(ob)
    TOK.objects.link(ob)
    ob.data.materials.append(m_leg)

# --- neutrons: little bright pellets that ignore your steel ---
nmesh = bpy.data.meshes.new("Neutron")
bm = bmesh.new()
bmesh.ops.create_icosphere(bm, subdivisions=1, radius=1.0)
bm.to_mesh(nmesh)
bm.free()
M_NEUT = lib.emission_mat("Neutron", (0.75, 0.95, 1.0), 30.0, blended=False)
nmesh.materials.append(M_NEUT)
NEUT = lib.empty("Neutrons", FX, loc=C)
for i in range(110):
    ob = bpy.data.objects.new(f"n{i:03d}", nmesh)
    ob.parent = NEUT
    ob.scale = (0.045,) * 3
    lib.no_shadow(ob)
    lib.link(ob, FX)
    phi = random.uniform(-2.6, -0.5) if random.random() < 0.75 else random.uniform(-math.pi, math.pi)
    th = random.uniform(0, 2 * math.pi)
    R = 3.0 + 0.95 * math.cos(th)
    p0 = (R * math.cos(phi), R * math.sin(phi), 1.5 * math.sin(th))
    d = (math.cos(th) * math.cos(phi) + random.gauss(0, 0.5), math.cos(th) * math.sin(phi) + random.gauss(0, 0.5),
         math.sin(th) + random.gauss(0, 0.4))
    nrm = math.sqrt(sum(c * c for c in d)) or 1
    dist = random.uniform(5, 9)
    p1 = tuple(p0[j] + dist * d[j] / nrm for j in range(3))
    off = random.randint(0, 13)
    lib.key(ob, "location", off, p0, interp="LINEAR")
    lib.key(ob, "location", off + 14, p1, interp="LINEAR")
    for fc in lib.fcurves(ob):
        fc.modifiers.new("CYCLES")
lib.show(NEUT, [(v2["t0"], v2["t1"])] if v2 else [], pop=False)

# --- 'model of a model' cages for the bridge ---
WIRES = []
for i, (s, colr) in enumerate([(1.22, GREEN), (1.45, YELLOW), (1.7, CYAN)]):
    me = plasma.data.copy()
    me.materials.clear()
    me.materials.append(lib.emission_mat(f"Cage{i}", colr, 2.2, blended=False))
    ob = bpy.data.objects.new(f"ModelCage{i}", me)
    ob.parent = tok
    lib.link(ob, FX)
    w = ob.modifiers.new("Wire", "WIREFRAME")
    w.thickness = 0.012 * s
    lib.no_shadow(ob)
    WIRES.append((ob, s))
    lib.drive(ob, "rotation_euler", f"frame/{300 + 120 * i}*{(-1) ** i}", [], index=2)
sur, mom = L("surrogate"), L("model of a model")
if sur:
    plots_line = L("plots")
    end_t = plots_line["t0"] if plots_line else sur["t1"] + 4
    starts = [sur["t0"] + 0.3, (mom or sur)["t0"] + 0.2, (mom or sur)["t0"] + 1.6]
    for (ob, s), t0 in zip(WIRES, starts):
        lib.show(ob, [(t0, end_t)], scale=s)
else:
    for ob, s in WIRES:
        lib.show(ob, [], scale=s)

# --- donut sprinkles ---
bm = bmesh.new()
SPR_MATS = []
for i, cc in enumerate([(1, 0.9, 0.2), (0.2, 0.7, 1), (1, 1, 1), (0.3, 1, 0.4), (1, 0.3, 0.2), (0.6, 0.3, 1)]):
    mm, _, _ = lib.principled(f"Sprinkle{i}", cc, roughness=0.35)
    SPR_MATS.append(mm)
prof_a = 0.97
for i in range(700):
    th = random.uniform(0.15, math.pi - 0.15)
    phi = random.uniform(0, 2 * math.pi)
    R = 3.0 + prof_a * math.cos(th + 0.35 * math.sin(th))
    Z = 1.65 * prof_a * math.sin(th)
    res = bmesh.ops.create_cube(bm, size=1.0)
    vs = res["verts"]
    bmesh.ops.scale(bm, vec=(0.17, 0.045, 0.045), verts=vs)
    rot = Euler((random.uniform(-0.4, 0.4), random.uniform(-0.4, 0.4), random.uniform(0, math.pi)), "XYZ").to_matrix().to_4x4()
    bmesh.ops.transform(bm, matrix=rot, verts=vs)
    bmesh.ops.translate(bm, vec=Vector((R * math.cos(phi), R * math.sin(phi), Z)), verts=vs)
    mi = i % len(SPR_MATS)
    for f in {f for v in vs for f in v.link_faces}:
        f.material_index = mi
spr_me = bpy.data.meshes.new("Sprinkles")
bm.to_mesh(spr_me)
bm.free()
for mm in SPR_MATS:
    spr_me.materials.append(mm)
spr = bpy.data.objects.new("Sprinkles", spr_me)
spr.parent = tok
lib.link(spr, FX)
lib.show(spr, [(dn["t0"] + 0.4, DUR)] if dn else [])

# ==========================================================================
# lights
# ==========================================================================
def area(name, loc, energy, color, size=6, target=C):
    ld = bpy.data.lights.new(name, "AREA")
    ld.energy = energy
    ld.color = color
    ld.size = size
    ob = bpy.data.objects.new(name, ld)
    ob.location = loc
    lib.link(ob, STAGE)
    c = ob.constraints.new("TRACK_TO")
    tgt = lib.empty(f"{name}_tgt", STAGE, loc=target, size=0.2)
    c.target = tgt
    c.track_axis = "TRACK_NEGATIVE_Z"
    c.up_axis = "UP_Y"
    return ob


key_l = area("Key", (-14, -16, 18), 4500, (0.85, 0.9, 1.0), size=10)
rim_m = area("RimMagenta", (16, 14, 9), 6000, MAGENTA, size=8)
rim_c = area("RimCyan", (-16, 14, 9), 6000, CYAN, size=8)
for ob, base in ((key_l, 4500), (rim_m, 6000), (rim_c, 6000)):
    lib.drive(ob.data, "energy", f"{base}*(1-0.6*m)", [scene_var("moody", "m")])
for k in range(4):
    phi = math.pi / 4 + k * math.pi / 2
    ld = bpy.data.lights.new(f"PlasmaGlow{k}", "POINT")
    ld.color = (0.75, 0.45, 1.0)
    ld.shadow_soft_size = 1.2
    ob = bpy.data.objects.new(ld.name, ld)
    ob.location = (3.0 * math.cos(phi), 3.0 * math.sin(phi), CZ)
    lib.link(ob, STAGE)
    lib.drive(ld, "energy", "p*(900+900*s)+f*4000",
              [("p", "SCENE", sc, '["plasma"]'), ("s", "SCENE", sc, '["aud_sub"]'),
               ("f", "SCENE", sc, '["flash"]')])
for k, x in enumerate((-8, 8)):
    ld = bpy.data.lights.new(f"Alarm{k}", "SPOT")
    ld.color = RED
    ld.spot_size = math.radians(40)
    ob = bpy.data.objects.new(ld.name, ld)
    ob.location = (x, -7, 9)
    ob.rotation_euler = (math.radians(65), 0, 0)
    lib.link(ob, STAGE)
    lib.drive(ob, "rotation_euler", f"frame*0.22+{k * math.pi}", [], index=2)
    lib.drive(ld, "energy", "a*12000", [("a", "SCENE", sc, '["alarm"]')])

# ==========================================================================
# robot workbench (outro): a thing that either works or doesn't
# ==========================================================================
RB = (90.0, 0.0, 0.0)
m_bench, _, _ = lib.principled("Bench", (0.35, 0.22, 0.12), roughness=0.6)
m_robot, _, _ = lib.principled("Robot", (0.9, 0.55, 0.1), metallic=0.3, roughness=0.35)
m_dark, _, _ = lib.principled("RobotDark", (0.05, 0.05, 0.06), metallic=0.5, roughness=0.4)


def box(name, loc, scale, mat, parent=None, coll_=ROBOT):
    """loc is local to parent when a parent is given."""
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = scale
    for c in ob.users_collection:
        c.objects.unlink(ob)
    coll_.objects.link(ob)
    ob.data.materials.append(mat)
    if parent:
        ob.parent = parent
        ob.location = loc
    return ob


box("BenchTop", (RB[0], RB[1], 1.0), (3.2, 1.5, 0.08), m_bench)
for dx in (-1.5, 1.5):
    for dy in (-0.65, 0.65):
        box("BenchLeg", (RB[0] + dx, RB[1] + dy, 0.5), (0.08, 0.08, 1.0), m_dark)
r_base = lib.empty("RobotBase", ROBOT, loc=(RB[0] - 0.3, RB[1], 1.04))
box("RBase", (0, 0, 0.08), (0.4, 0.4, 0.16), m_dark, parent=r_base)
r_sh = lib.empty("RobotShoulder", ROBOT, loc=(0, 0, 0.18), parent=r_base)
box("RArm1", (0, 0, 0.35), (0.12, 0.12, 0.7), m_robot, parent=r_sh)
r_el = lib.empty("RobotElbow", ROBOT, loc=(0, 0, 0.7), parent=r_sh)
box("RArm2", (0, 0.28, 0), (0.1, 0.56, 0.1), m_robot, parent=r_el)
box("RGrip", (0, 0.58, -0.08), (0.14, 0.06, 0.18), m_dark, parent=r_el)
fingers = [box(f"RFinger{k}", (sgn * 0.07, 0.6, -0.2), (0.025, 0.05, 0.1), m_dark, parent=r_el)
           for k, sgn in enumerate((-1, 1))]
box("Board", (RB[0] - 1.15, RB[1] + 0.25, 1.06), (0.7, 0.5, 0.03), lib.principled("PCB", (0.02, 0.25, 0.08), roughness=0.4)[0])
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.06, location=(RB[0] - 0.95, RB[1] - 0.1, 1.12))
led_ob = bpy.context.active_object
led_ob.name = "LED"
for c in led_ob.users_collection:
    c.objects.unlink(led_ob)
ROBOT.objects.link(led_ob)
m, nt, out = lib.new_mat("LED")
em = nt.nodes.new("ShaderNodeEmission")
nt.links.new(lib.mix_rgb(nt, lib.attr(nt, "led_green"), RED, GREEN), em.inputs["Color"])
nt.links.new(lib.math_(nt, "MULTIPLY", lib.attr(nt, "led"), 40.0), em.inputs["Strength"])
nt.links.new(em.outputs[0], out.inputs["Surface"])
led_ob.data.materials.append(m)

# --- the laundry test: grab a T-shirt, try to fold it, drop it ---
BASE = np.array([RB[0] - 0.3, RB[1], 1.04])
TIP = (0.6, -0.24)  # gripper tip in the elbow frame (forward, up)
BENCH_Z = 1.046


def planar_fk(sh, el):
    """(forward, up) of the gripper tip relative to the robot base, plus elbow height."""
    ey, ez = -0.7 * np.sin(sh), 0.18 + 0.7 * np.cos(sh)
    a = sh + el
    return ey + TIP[0] * np.cos(a) - TIP[1] * np.sin(a), ez + TIP[0] * np.sin(a) + TIP[1] * np.cos(a), ez


SH_G, EL_G = np.meshgrid(np.arange(-2.2, 1.2, 0.006), np.arange(-2.8, 2.8, 0.006))
F_G, U_G, E_G = planar_fk(SH_G, EL_G)


def ik(target):
    """Joint angles (yaw, shoulder, elbow) that put the gripper tip on a world-space target."""
    d = np.asarray(target, dtype=float) - BASE
    yaw = math.atan2(-d[0], d[1])
    err = (F_G - math.hypot(d[0], d[1])) ** 2 + (U_G - d[2]) ** 2 + 0.0005 * EL_G ** 2 + 10.0 * (E_G < 0.3)
    i = np.unravel_index(np.argmin(err), err.shape)
    return yaw, float(SH_G[i]), float(EL_G[i])


def tip_world(yaw, sh, el):
    f, u, _ = planar_fk(sh, el)
    return BASE + np.array([-f * math.sin(yaw), f * math.cos(yaw), u])


C0 = BASE + np.array([0.75, 0.0, BENCH_Z - BASE[2]])  # shirt collar, lying on the bench
bench_l_, works_ = L("on a bench"), L("It works")
tb = bench_l_["t0"] if bench_l_ else DUR - 12
tw0, tw1 = (works_["t0"], works_["t1"]) if works_ else (tb + 3.5, tb + 6.2)
t_grab, t_drop, fall = tb + 1.7, tw1 - 0.55, 0.38
t_lunch = lunch_line["t0"] if lunch_line else t_drop + 2
poses = [  # (time, joint angles)
    (tb, (-0.9, 0.05, 0.25)),
    (tb + 0.7, ik(C0 + [0, 0, 0.18])),
    (tb + 1.4, ik(C0 + [0, 0, 0.012])),
    (t_grab, ik(C0 + [0, 0, 0.012])),
    (tb + 2.9, ik(C0 + [-0.15, 0, 0.62])),
    (tw0 + 0.1, ik(C0 + [-0.15, 0.22, 0.6])),
    (tw0 + 0.9, ik(C0 + [-0.12, -0.25, 0.63])),
    (tw0 + 1.7, ik(C0 + [-0.1, 0.06, 0.64])),
    (t_drop, ik(C0 + [-0.12, 0.0, 0.64])),
    (t_drop + 0.6, ik(C0 + [-0.2, 0.0, 0.72])),
    (t_lunch + 0.3, ik(C0 + [-0.2, 0.0, 0.72])),
    (t_lunch + 1.6, ik(C0 + [-0.4, 0.0, 0.2])),  # slump
]
joints = np.zeros((N, 3))
for i, t in enumerate(T):
    if t < poses[0][0]:
        joints[i] = (math.sin(t * 1.3) * 0.6, math.sin(t * 1.76) * 0.3, 0.3 + math.sin(t * 2.3 + 1) * 0.3)
        continue
    k = max(j for j in range(len(poses)) if poses[j][0] <= t)
    if k == len(poses) - 1:
        joints[i] = poses[k][1]
        continue
    (ta, pa), (tb_, pb) = poses[k], poses[k + 1]
    u = (t - ta) / (tb_ - ta)
    u = u * u * (3 - 2 * u)
    joints[i] = [pa[j] + (pb[j] - pa[j]) * u for j in range(3)]
lib.bake(r_base, "rotation_euler", joints[:, 0], index=2)
lib.bake(r_sh, "rotation_euler", joints[:, 1], index=0)
lib.bake(r_el, "rotation_euler", joints[:, 2], index=0)
grip = np.clip((T - (t_grab - 0.15)) / 0.15, 0, 1) * (T < t_drop)  # 1 = closed
for k, f_ob in enumerate(fingers):
    lib.bake(f_ob, "location", (-1 if k == 0 else 1) * (0.07 - 0.045 * grip), index=0)


# T-shirt mesh: collar at the origin, body along +X
def _shirt(x, y):
    ay = abs(y)
    if not (0 <= x <= 0.55) or (x < 0.045 and ay < 0.075):
        return False
    return ay <= 0.235 or (ay <= 0.37 and 0.01 + (ay - 0.235) * 0.1 <= x <= 0.17 - (ay - 0.235) * 0.35)


xs_, ys_ = np.arange(0, 0.5601, 0.02), np.arange(-0.38, 0.3801, 0.02)
vid, verts, faces = {}, [], []
for i in range(len(xs_) - 1):
    for j in range(len(ys_) - 1):
        if not _shirt((xs_[i] + xs_[i + 1]) / 2, (ys_[j] + ys_[j + 1]) / 2):
            continue
        quad = []
        for ii, jj in ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)):
            if (ii, jj) not in vid:
                vid[(ii, jj)] = len(verts)
                verts.append((float(xs_[ii]), float(ys_[jj]), 0.0))
            quad.append(vid[(ii, jj)])
        faces.append(quad)
shirt = lib.mesh_obj("TShirt", verts, faces, ROBOT)
m_shirt, _, p_shirt = lib.principled("TShirt", (0.1, 0.62, 0.7), roughness=0.85)
shirt.data.materials.append(m_shirt)
shirt.modifiers.new("Thick", "SOLIDIFY").thickness = 0.006
shirt.modifiers.new("Smooth", "SUBSURF").levels = 1
shirt.shape_key_add(name="Basis", from_mix=False)
hang_co, keys_ = [], {}
for name in ("Hang", "Fold", "Crumple"):
    keys_[name] = shirt.shape_key_add(name=name, from_mix=False)
for i, (x, y, _) in enumerate(verts):
    hz = -(x + 0.35 * abs(y))
    hang = (0.02 * math.sin(6 * x), y * 0.85, hz)
    keys_["Hang"].data[i].co = hang
    keys_["Fold"].data[i].co = (hang[0] + 0.05, hang[1], -0.6 - hz) if hz < -0.3 else hang
    keys_["Crumple"].data[i].co = ((x - 0.27) * 0.5 + 0.03 * math.sin(17 * y + 4 * x),
                                   y * 0.55 + 0.025 * math.cos(13 * x + 9 * y),
                                   0.012 + 0.045 * (0.5 + 0.5 * math.sin(11 * x + 1) * math.cos(9 * y))
                                   + 0.03 * math.exp(-((x - 0.27) ** 2 + y ** 2) / 0.02))
keys_["Fold"].relative_key = keys_["Hang"]

loc = np.zeros((N, 3))
hang_v, fold_v, crum_v = np.zeros(N), np.zeros(N), np.zeros(N)
drop_i = min(N - 1, int(t_drop * FPS))
p_drop = tip_world(*joints[drop_i]) + [0, 0, -0.01]
for i, t in enumerate(T):
    if t < t_grab:
        loc[i] = C0
    elif t < t_drop:
        loc[i] = tip_world(*joints[i]) + [0, 0, -0.01]
        hang_v[i] = np.clip((loc[i][2] - BENCH_Z) / 0.55, 0, 1)
    else:
        dt = t - t_drop
        loc[i] = [p_drop[0] + 0.15 * min(dt, fall), p_drop[1], max(BENCH_Z, p_drop[2] - 4.9 * dt * dt)]
        w = min(1.0, dt / fall)
        hang_v[i] = (1 - w) * np.clip((p_drop[2] - BENCH_Z) / 0.55, 0, 1)
        crum_v[i] = w
fold_v = np.interp(T, [tw0 + 0.3, tw0 + 1.4, tw0 + 1.9, t_drop - 0.1, t_drop], [0, 0.8, 0.8, 0.3, 0])
fold_v = np.where(T < t_drop, fold_v, 0)
for k in range(3):
    lib.bake(shirt, "location", loc[:, k], index=k)
sk = shirt.data.shape_keys
lib.bake(sk, 'key_blocks["Hang"].value', hang_v)
lib.bake(sk, 'key_blocks["Fold"].value', fold_v)
lib.bake(sk, 'key_blocks["Crumple"].value', crum_v)

# LED: green while it tries, red once the shirt hits the bench
led = np.where(T >= tb, 1.0, 0.0)
blink = (np.floor((T - tw0) * 4) % 2 == 0).astype(float)
led = np.where((T >= tw0) & (T < t_drop), blink, led)
lib.scene_prop(sc, "led", led)
lib.scene_prop(sc, "led_green", np.where(T < t_drop, 1.0, 0.0))
bench_l = area("BenchLight", (RB[0] - 2, RB[1] - 3, 4.5), 400, (1.0, 0.85, 0.7), size=3, target=(RB[0], RB[1], 1.1))
area("BenchRim", (RB[0] + 2.5, RB[1] + 3, 3), 300, CYAN, size=2, target=(RB[0], RB[1], 1.1))

# ==========================================================================
# solar farm aside: PV panels + batteries under the synthwave sun
# ==========================================================================
SOLARC = lib.coll("SolarFarm")
SF = (-90.0, 0.0, 0.0)
m_pv, nt, p = lib.principled("PVPanel", (0.03, 0.08, 0.24), metallic=0.4, roughness=0.12)
tc = nt.nodes.new("ShaderNodeTexCoord")
sx = nt.nodes.new("ShaderNodeSeparateXYZ")
nt.links.new(tc.outputs["Object"], sx.inputs[0])


def _cell(c, n):
    f = lib.math_(nt, "FRACT", lib.math_(nt, "MULTIPLY", lib.math_(nt, "ADD", c, 0.5), n))
    return lib.math_(nt, "LESS_THAN", lib.math_(nt, "ABSOLUTE", lib.math_(nt, "SUBTRACT", f, 0.5)), 0.45)


inside = lib.math_(nt, "MULTIPLY", _cell(sx.outputs[0], 6.0), _cell(sx.outputs[1], 10.0))
nt.links.new(lib.mix_rgb(nt, inside, (0.7, 0.72, 0.76), (0.03, 0.08, 0.24)), p.inputs["Base Color"])
m_alu, _, _ = lib.principled("Aluminium", (0.7, 0.72, 0.75), metallic=0.9, roughness=0.3)
for r in range(3):
    for c in range(-3, 4):
        x, y = SF[0] + c * 1.95, SF[1] + r * 3.0
        pv_ob = box(f"PV_{r}_{c + 3}", (x, y, 1.15), (1.8, 2.2, 0.05), m_pv, coll_=SOLARC)
        pv_ob.rotation_euler = (math.radians(-10), 0, 0)
        box(f"PVPost_{r}_{c + 3}", (x, y + 0.1, 0.55), (0.07, 0.07, 1.1), m_alu, coll_=SOLARC)
m_bat, _, _ = lib.principled("Battery", (0.82, 0.84, 0.88), roughness=0.4)
m, nt, out = lib.new_mat("BatteryCharge")
tc = nt.nodes.new("ShaderNodeTexCoord")
sx = nt.nodes.new("ShaderNodeSeparateXYZ")
nt.links.new(tc.outputs["UV"], sx.inputs[0])
lit = lib.math_(nt, "LESS_THAN", sx.outputs[0], lib.attr(nt, "battery"))
em = nt.nodes.new("ShaderNodeEmission")
nt.links.new(lib.mix_rgb(nt, lit, (0.02, 0.03, 0.03), GREEN), em.inputs["Color"])
nt.links.new(lib.math_(nt, "ADD", 0.3, lib.math_(nt, "MULTIPLY", lit, 4.0)), em.inputs["Strength"])
nt.links.new(em.outputs[0], out.inputs["Surface"])
M_CHARGE = m
M_LABEL = lib.emission_mat("BatteryLabel", (0.05, 0.06, 0.08), 1.0, blended=False)
for k, y in enumerate((0.0, 3.2)):
    bx = SF[0] + 9.5
    box(f"Battery{k}", (bx, SF[1] + y, 0.8), (2.6, 1.3, 1.6), m_bat, coll_=SOLARC)
    bar = lib.plane(f"BatteryBar{k}", 2.0, 0.32, SOLARC, loc=(bx, SF[1] + y - 0.66, 1.05))
    bar.rotation_euler = (math.radians(90), 0, 0)
    bar.data.materials.append(M_CHARGE)
    lib.text(f"BatteryLabel{k}", "BATTERY", SOLARC, 0.26, [M_LABEL], fontfile="bahnschrift.ttf",
             loc=(bx, SF[1] + y - 0.66, 1.42), rot=(math.radians(90), 0, 0), hud=False)
for nm_, loc_, en_, col_, size_ in (("SolarKey", (SF[0] - 4, SF[1] - 10, 14), 4000, (1.0, 0.86, 0.7), 14),
                                    ("SolarRim", (SF[0] + 10, SF[1] + 14, 6), 900, CYAN, 6)):
    lo = area(nm_, loc_, en_, col_, size=size_, target=(SF[0], SF[1] + 2, 1.0))
    for attr_, val_ in (("use_custom_distance", True), ("cutoff_distance", 45.0)):
        if hasattr(lo.data, attr_):
            setattr(lo.data, attr_, val_)

# ==========================================================================
# camera rig + shot list (per-frame baked)
# ==========================================================================
pivot = lib.empty("CamPivot", RIG, loc=C)
pivot.rotation_mode = "XYZ"
dolly = lib.empty("CamDolly", RIG, parent=pivot)
shake = lib.empty("CamShake", RIG, parent=dolly)
cam_data = bpy.data.cameras.new("Camera")
cam_data.clip_start = 0.02
cam_data.clip_end = 800
cam = bpy.data.objects.new("Camera", cam_data)
cam.parent = shake
cam.rotation_euler = (math.radians(90), 0, 0)
lib.link(cam, RIG)
sc.camera = cam

P = {  # shot presets: az/el in degrees (pairs = start->end), d distance, lens mm, tgt offset
    "wide": dict(az=(-30, -8), el=(11, 8), d=(24, 21), lens=30),
    "wide2": dict(az=(28, 8), el=(7, 12), d=(23, 20), lens=28),
    "wide_fast": dict(az=(-30, 0), el=(13, 10), d=(21, 19.5), lens=30),
    "med": dict(az=(-18, 6), el=(6, 6), d=(13, 11), lens=35, tgt=(0, -1.5, 0)),
    "med2": dict(az=(22, -4), el=(9, 5), d=(12, 10.5), lens=38, tgt=(0, -1.5, 0)),
    "inside": dict(az=(-25, -6), el=(3, 4), d=(7.5, 6.5), lens=24, tgt=(0, -2.4, 0)),
    "ignite": dict(az=(-8, 4), el=(3, 3), d=(7.5, 6.2), lens=24, tgt=(0, -2.4, 0)),
    "coil": dict(az=(35, 48), el=(12, 16), d=(10, 9), lens=40, tgt=(2.0, -2.2, 1.0)),
    "low": dict(az=(40, 24), el=(-5, 1), d=(13, 12), lens=22),
    "top": dict(az=(-10, 35), el=(58, 64), d=(17, 16), lens=30),
    "crane": dict(az=(0, -22), el=(4, 28), d=(15, 15), lens=30),
    "orbitA": dict(az=(70, 130), el=(16, 18), d=(24, 24), lens=30),
    "orbitB": dict(az=(130, 200), el=(18, 14), d=(24, 23), lens=30),
    "orbitC": dict(az=(200, 270), el=(14, 18), d=(23, 24), lens=30),
    "orbitD": dict(az=(270, 335), el=(18, 12), d=(24, 22), lens=30),
    "moody_high": dict(az=(-40, -10), el=(26, 22), d=(28, 26), lens=30),
    "moody_med": dict(az=(15, -5), el=(10, 8), d=(16, 14), lens=35),
    "cage": dict(az=(-30, 30), el=(20, 24), d=(20, 18), lens=28),
    "front": dict(az=(-3, 3), el=(4, 4), d=(15, 13.5), lens=35),
    "front2": dict(az=(10, 4), el=(10, 9), d=(12, 11), lens=40),
    "donut": dict(az=(-20, 20), el=(62, 58), d=(14, 13), lens=30),
    "intro_push": dict(az=(-25, -12), el=(6, 8), d=(34, 22), lens=45),
    "intro_orbit": dict(az=(-12, 12), el=(8, 10), d=(16, 13), lens=35),
    "pullback": dict(az=(-10, 10), el=(10, 22), d=(14, 42), lens=30),
    "solar": dict(az=(-22, -16), el=(15, 14), d=(13, 11.5), lens=22, tgt=(SF[0] + 1, SF[1] + 3, 1.0), abs=True),
    "solar2": dict(az=(-8, 2), el=(17, 15), d=(15, 13.5), lens=22, tgt=(SF[0] + 2.5, SF[1] + 3, 1.0), abs=True),
    "robot": dict(az=(-30, -14), el=(17, 14), d=(4.7, 4.1), lens=38, tgt=(RB[0] + 0.15, RB[1], 1.3), abs=True),
}
SHOTS = []  # (t0, t1, preset, priority)


def shot(t0, t1, preset, prio=0):
    if t0 is not None and t1 is not None and t1 > t0:
        SHOTS.append((t0, t1, P[preset], prio))


def cut_on_lines(sec, presets, per=1):
    if not sec:
        return
    ls = sec["lines"]
    cuts = [sec["t0"]] + [ls[i]["t0"] for i in range(per, len(ls), per)] + [sec["t1"]]
    cuts = sorted(set(round(c, 3) for c in cuts))
    for i in range(len(cuts) - 1):
        shot(cuts[i], cuts[i + 1], presets[i % len(presets)])


SEQ = {
    "verse": [["wide", "med", "inside", "crane"], ["inside", "med2", "low", "wide2"],
              ["orbitA", "orbitB"], ["orbitC", "orbitD"]],
    "pre": [["low", "med"], ["med", "front2"], ["low", "front"]],
    "chorus": [["wide_fast", "coil", "med", "top", "wide2", "med2"]],
    "bridge": [["moody_high", "moody_med", "cage", "cage", "front"]],
    "breakdown": [["front", "front2", "med", "med2", "low"], ["med2", "front", "wide2", "low", "front2", "wide"]],
    "final": [["wide_fast", "coil", "top", "med", "donut", "wide"]],
}
for s in SECTIONS:
    k = s["kind"]
    if k == "intro":
        l2 = s["lines"][1] if len(s["lines"]) > 1 else None
        shot(s["t0"], l2["t0"] if l2 else s["t1"], "intro_push")
        shot(l2["t0"] if l2 else s["t0"], s["t1"], "intro_orbit")
    elif k == "outro":
        shot(s["t0"], s["t1"], "pullback")
    elif k in SEQ:
        seqs = SEQ[k]
        per = 2 if k in ("verse", "bridge") else 1
        if k == "verse" and s["n"] >= 3:
            per = 4
        cut_on_lines(s, seqs[(s["n"] - 1) % len(seqs)], per)
# overrides that land on specific lyrics
for k in range(1, 6):
    ig = L("We got ignition", k)
    if ig:
        shot(ig["t0"], ig["t1"], "ignite", 2)
qn = L("quenched")
if qn:
    shot(qn["t0"], qn["t1"], "coil", 2)
if dn:
    shot(dn["t0"] - 0.05, dn["t1"], "donut", 2)
bench = L("on a bench")
if bench:
    shot(bench["t0"], DUR + 1, "robot", 3)
for i_, (a_, b_) in enumerate(SOLAR_WIN):
    shot(a_, b_, "solar" if i_ == 0 and pv else "solar2", 3)
cg = L("plots")
if cg:
    shot(cg["t0"], (SEC.get("breakdown1") or cg)["t0"] if SEC.get("breakdown1") else cg["t1"], "front", 2)


def smooth(u):
    return u * u * (3 - 2 * u)


def lerp(a, b, u):
    return a + (b - a) * u


cam_ch = {k: np.zeros(N) for k in ("px", "py", "pz", "rx", "rz", "d", "lens")}
default = P["wide"]
for i in range(N):
    t = T[i]
    best = None
    for s in SHOTS:
        if s[0] <= t < s[1] and (best is None or s[3] >= best[3]):
            best = s
    if best is None:
        t0, t1, pr = 0, DUR, default
    else:
        t0, t1, pr = best[0], best[1], best[2]
    u = smooth(min(1.0, max(0.0, (t - t0) / (t1 - t0))))
    tg = pr.get("tgt", (0, 0, 0))
    base = (0, 0, 0) if pr.get("abs") else C
    cam_ch["px"][i] = base[0] + tg[0]
    cam_ch["py"][i] = base[1] + tg[1]
    cam_ch["pz"][i] = base[2] + tg[2]
    cam_ch["rz"][i] = math.radians(lerp(*pr["az"], u))
    cam_ch["rx"][i] = -math.radians(lerp(*pr["el"], u))
    cam_ch["d"][i] = lerp(*pr["d"], u)
    cam_ch["lens"][i] = pr["lens"]
lib.bake(pivot, "location", cam_ch["px"], index=0)
lib.bake(pivot, "location", cam_ch["py"], index=1)
lib.bake(pivot, "location", cam_ch["pz"], index=2)
lib.bake(pivot, "rotation_euler", cam_ch["rx"], index=0)
lib.bake(pivot, "rotation_euler", cam_ch["rz"], index=2)
lib.bake(dolly, "location", -cam_ch["d"], index=1)
lib.bake(cam_data, "lens", cam_ch["lens"])

# camera shake: alarms, flashes, a little kick punch in choruses
# only a slow, gentle sway during the disruption (no per-beat camera punches: motion sickness)
amp = 0.3 * ENV["alarm"]
tt = T
nz_ = lambda f1, f2, ph: np.sin(tt * f1 + ph) * 0.6 + np.sin(tt * f2 + ph * 1.7) * 0.4  # noqa: E731
lib.bake(shake, "location", amp * 0.05 * nz_(5, 8, 0.3), index=0)
lib.bake(shake, "location", amp * 0.05 * nz_(6, 9, 1.1), index=2)
lib.bake(shake, "rotation_euler", amp * 0.01 * nz_(4, 7, 2.0), index=0)
lib.bake(shake, "rotation_euler", amp * 0.012 * nz_(3, 5, 3.0), index=1)

# ==========================================================================
# HUD
# ==========================================================================
hud = lib.HUD(cam, HUDC, *RES)
M = {
    "white": lib.emission_mat("H_white", WHITE, 1.0),
    "cyan": lib.emission_mat("H_cyan", CYAN, 1.15),
    "mag": lib.emission_mat("H_mag", MAGENTA, 1.25),
    "red": lib.emission_mat("H_red", (1.0, 0.18, 0.15), 1.25),
    "green": lib.emission_mat("H_green", GREEN, 1.1),
    "yellow": lib.emission_mat("H_yellow", YELLOW, 1.15),
    "orange": lib.emission_mat("H_orange", ORANGE, 1.2),
    "dim": lib.emission_mat("H_dim", (0.55, 0.6, 0.7), 1.0),
    "panel": lib.emission_mat("H_panel", (0.004, 0.008, 0.025), 1.0, alpha=0.86),
    "paper": lib.emission_mat("H_paper", (0.92, 0.92, 0.88), 0.9),
    "ink": lib.emission_mat("H_ink", (0.02, 0.02, 0.03), 1.0),
    "panel_solid": lib.emission_mat("H_panel_solid", (0.004, 0.008, 0.025), 1.0, alpha=0.94),
    "pill": lib.emission_mat("H_pill", (0.004, 0.008, 0.025), 1.0, alpha=0.84),
    "pill_lyric": lib.emission_mat("H_pill_lyric", (0.004, 0.008, 0.025), 1.0, alpha=0.72),
}


def overlay(name, color, alpha_expr, z, radial=None):
    """Full-screen overlay; alpha from a scene property, optionally a radial (vignette) mask."""
    m, nt, out = lib.new_mat(name, blended=True)
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (*color, 1)
    a = lib.attr(nt, alpha_expr) if isinstance(alpha_expr, str) else lib.sock(nt, alpha_expr)
    if radial:
        tc = nt.nodes.new("ShaderNodeTexCoord")
        vm = nt.nodes.new("ShaderNodeVectorMath")
        vm.operation = "DISTANCE"
        nt.links.new(tc.outputs["UV"], vm.inputs[0])
        vm.inputs[1].default_value = (0.5, 0.5, 0)
        mr = nt.nodes.new("ShaderNodeMapRange")
        nt.links.new(vm.outputs["Value"], mr.inputs[0])
        mr.inputs[1].default_value, mr.inputs[2].default_value = radial
        a = lib.math_(nt, "MULTIPLY", a, mr.outputs[0])
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    mx = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(a, mx.inputs[0])
    nt.links.new(tr.outputs[0], mx.inputs[1])
    nt.links.new(em.outputs[0], mx.inputs[2])
    nt.links.new(mx.outputs[0], out.inputs["Surface"])
    return hud.fullscreen(name, m, z)


overlay("Vignette", (0, 0, 0), 0.4, 0.0, radial=(0.45, 0.9))
overlay("AlarmEdge", (1, 0, 0), "alarm_pulse", 0.003, radial=(0.25, 0.75))
overlay("WhiteFlash", (1, 1, 1), "white", 0.005)
overlay("Fader", (0, 0, 0), "fade", 0.04)

N_OBJ = [0]


def nm(prefix):
    N_OBJ[0] += 1
    return f"{prefix}_{N_OBJ[0]:03d}"


PANEL_RECTS = []  # (u0, u1, v0, v1, t0, t1) of on-screen panels
PILLS = []  # (object, padding, material): dark rounded backings, sized once the text exists


def pill_for(ob, size_px, mat="pill"):
    PILLS.append((ob, hud.px(max(10, size_px * 0.3)), mat))


def card(body, t0, t1, size=60, mat="white", u=0.0, v=0.0, fontfile="segoeuib.ttf", align="CENTER",
         accent=None, pop=True, scale=1.0, rot=0.0, pill=None, pill_mat="pill"):
    if t0 is None or t1 is None or t1 <= t0:
        return None
    mats = [M[mat]] + ([M[accent]] if accent else [])
    ob = hud.text(nm("txt"), body, size, mats, u=u, v=v, fontfile=fontfile, align=align,
                  accent_parens=bool(accent), rot=(0, 0, math.radians(rot)))
    lib.show(ob, [(t0, t1)], scale=scale, pop=pop)
    if pill is None:  # text that already sits on a panel needs no backing of its own
        pill = mat != "ink" and not any(a <= u <= b and c <= v <= d and t0 < e and t1 > s_
                                        for a, b, c, d, s_, e in PANEL_RECTS)
    if pill:
        pill_for(ob, size, pill_mat)
    return ob


def panel(t0, t1, w, h, u, v, mat="panel", z=0.006):
    if t0 is None or t1 is None or t1 <= t0:
        return None
    ob = hud.plane(nm("panel"), w, h, M[mat], u=u, v=v, z=z, radius_px=0 if mat == "paper" else 16)
    lib.show(ob, [(t0, t1)], pop=False, in_frames=3, out_frames=3)
    du, dv = hud.px(w) / 2 / hud.HW, hud.px(h) / 2 / hud.HH
    PANEL_RECTS.append((u - du, u + du, v - dv, v + dv, t0, t1))
    return ob


def at(line, frac=0.0):
    return None if line is None else line["t0"] + frac * (line["t1"] - line["t0"])


def end(line, pad=0.0):
    return None if line is None else line["t1"] + pad


def sec_end(sec_id, fallback=None):
    s = SEC.get(sec_id)
    return s["t1"] if s else fallback


WRAP = 40 if not VERTICAL else 24
LX = 0.92  # left/right margin in u

# ---- lyrics (lower third) ----
NO_LYRICS = {"intro", "breakdown"}
for l in LINES:
    if l["sec"]["kind"] in NO_LYRICS:
        continue
    parts = l["text"].split("\n")
    body = "\n".join(lib.wrap(part, WRAP) for part in parts)
    while body.count("\n") + 1 > 3 and len(parts) > 1:  # drop stacked backing vocals that would overflow
        parts = parts[:-1]
        body = "\n".join(lib.wrap(part, WRAP) for part in parts)
    rows = body.count("\n") + 1
    size = 52 if rows <= 2 else 44
    card(body, l["t0"], l["t1"], size=size, mat="white", u=0, v=-0.8 + 0.035 * (rows - 1), accent="mag",
         pill=True, pill_mat="pill_lyric")

# ---- persistent deadpan status bar ----
v1 = SEC.get("verse1")
status_t0 = v1["t0"] if v1 else 0
status_t1 = (L("on a bench") or {"t0": DUR - 2})["t0"]
card("FUSION ETA:  T–30 YRS", status_t0, status_t1, 36, "cyan", u=-LX, v=0.9, fontfile="bahnschrift.ttf",
     align="LEFT", pop=False)
card("● LIVE  |  SHOT 401117", status_t0, status_t1, 32, "dim", u=LX, v=0.9, fontfile="bahnschrift.ttf",
     align="RIGHT", pop=False)

# ---- intro: terminal ----
if intro:
    for i, l in enumerate(intro["lines"]):
        line_txt = "SHOT #401117" if "four-oh-one" in l["text"].lower() else l["text"].upper()
        lib.show(lib.typer(nm("type"), hud, "> " + line_txt, l["t0"], 22, 46, M["green"], u=-0.8,
                           v=0.25 - 0.17 * i), [(l["t0"], intro["t1"])], pop=False)

# ---- verse 1: the year counter that never closes the gap ----
y0, y1 = L("fifty-eight"), L("come online") or L("kids were twenty-one")
if y0:
    t_a, t_b = y0["t0"], (y1 or y0)["t1"]
    t_end = SEC["pre1"]["t0"] if SEC.get("pre1") else t_b
    panel(t_a, t_end, 520, 210, u=0.62, v=0.6)
    for ob in (lib.counter(nm("cnt"), hud, "YEAR  ", "", 1958, 2026, t_a + 0.5, t_b - 0.5, 64, M["white"],
                           u=0.62, v=0.68),
               lib.counter(nm("cnt"), hud, "FUSION ETA  ", "", 1988, 2056, t_a + 0.5, t_b - 0.5, 50, M["mag"],
                           u=0.62, v=0.53)):
        lib.show(ob, [(t_a, t_end)])
    card("(ALWAYS +30)", at(y0, 0.5), t_end, 26, "dim", u=0.62, v=0.43, fontfile="bahnschrift.ttf")
if cat:
    for j in range(4):
        card("⚠ PLASMA ESCAPING", cat["t0"] + 0.45 * j, cat["t0"] + 0.45 * j + 0.3, 44, "red", u=0, v=0.3,
             fontfile="bahnschrift.ttf", pop=False)
mth, onl = L("did the math"), L("come online")
if mth:
    t1_ = end(onl or mth)
    panel(mth["t0"], t1_, 1700 if not VERTICAL else 1000, 260, u=0, v=0.15)
    bar = hud.polyline(nm("bar"), [(-0.78, 0.12), (0.62, 0.12)], M["cyan"], 6)
    bar.data.bevel_factor_end = 0.0
    lib.key(bar.data, "bevel_factor_end", F(mth["t0"]), 0.0)
    lib.key(bar.data, "bevel_factor_end", F(at(mth, 0.8)), 1.0)
    lib.show(bar, [(mth["t0"], t1_)], pop=False)
    for u_, lab, mt in ((-0.78, "CAREER START", "dim"), (-0.2, "YOU ARE HERE", "white"), (0.6, "RETIREMENT", "dim")):
        card("|", at(mth, 0.1), t1_, 50, mt, u=u_, v=0.12, fontfile="bahnschrift.ttf")
        card(lab, at(mth, 0.1), t1_, 34, mt, u=u_, v=0.24, fontfile="bahnschrift.ttf")
    card("FIRST FUSION POWER  →", at(onl or mth, 0.25), t1_, 34, "mag", u=0.9, v=0.03,
         fontfile="bahnschrift.ttf", align="RIGHT")

# ---- pre-chorus 1: up and to the right ----
up, deck = L("up and to the right"), L("turning on tonight")
if up:
    t1_ = (SEC.get("chorus1") or {"t0": end(deck or up)})["t0"] + 0.4
    cu0, cv0, cw, ch_ = 0.15, -0.35, 0.72, 0.85
    panel(up["t0"], t1_, 760 if not VERTICAL else 500, 560, u=cu0 + cw / 2, v=cv0 + ch_ / 2 + 0.02)
    ax = hud.polyline(nm("ax"), [(cu0, cv0 + ch_), (cu0, cv0), (cu0 + cw, cv0)], M["dim"], 3)
    lib.show(ax, [(up["t0"], t1_)], pop=False)
    pts = [(cu0 + cw * x, cv0 + ch_ * (0.05 + 0.9 * (math.exp(3 * x) - 1) / (math.exp(3) - 1)))
           for x in np.linspace(0, 1, 30)]
    g = hud.polyline(nm("graph"), pts, M["green"], 6)
    lib.key(g.data, "bevel_factor_end", F(up["t0"]), 0.0)
    lib.key(g.data, "bevel_factor_end", F(at(up, 0.9)), 1.0)
    lib.show(g, [(up["t0"], t1_)], pop=False)
    card("EVERY DECADE'S GRAPH", at(up, 0.1), t1_, 28, "dim", u=cu0 + 0.02, v=cv0 + ch_ - 0.03,
         fontfile="bahnschrift.ttf", align="LEFT")
    if deck:
        card("SERIES A", at(deck, 0.1), t1_, 30, "cyan", u=cu0 + cw * 0.35, v=cv0 + ch_ * 0.2,
             fontfile="bahnschrift.ttf")
        card("SERIES B", at(deck, 0.35), t1_, 30, "cyan", u=cu0 + cw * 0.62, v=cv0 + ch_ * 0.42,
             fontfile="bahnschrift.ttf")
        card("NET ELECTRICITY BY 2023 ✓", at(deck, 0.7), t1_, 30, "yellow", u=cu0 + cw * 0.55,
             v=cv0 + ch_ * 0.98, fontfile="bahnschrift.ttf")
        card("✗", at(deck, 0.8), t1_, 220, "red", u=cu0 + cw * 0.55, v=cv0 + ch_ * 0.6)
        card("(it is 2026)", at(deck, 0.88), t1_, 34, "red", u=cu0 + cw * 0.55, v=cv0 + ch_ * 0.25,
             fontfile="bahnschrift.ttf")

# ---- choruses ----
for s in CHORUSES:
    ls = s["lines"]
    if not ls:
        continue
    l0 = ls[0]
    card("30 YEARS AWAY", l0["t0"], l0["t1"], 170, "mag", u=0, v=0.42, fontfile="impact.ttf")
    card("(30 YEARS AWAY)", at(l0, 0.5), l0["t1"], 60, "cyan", u=0, v=0.18, fontfile="impact.ttf")
    for l in ls:
        tx = l["text"].lower()
        if "net gain" in tx:
            card("NET GAIN!", l["t0"], l["t1"], 160, "yellow", u=0, v=0.4, fontfile="impact.ttf", rot=-4)
            card("*if you don't count the wall plug", at(l, 0.45), l["t1"], 42, "white", u=0.05, v=0.13,
                 fontfile="segoeuib.ttf")
            card("Q_sci ~1.5     Q_wall-plug ~0.01", at(l, 0.6), l["t1"], 30, "dim", u=0.05, v=0.0,
                 fontfile="consola.ttf")
        elif "ignition" in tx:
            card("IGNITION!", l["t0"], l["t1"], 180, "orange", u=0, v=0.4, fontfile="impact.ttf")
            card("*for 0.000000001 s", at(l, 0.4), l["t1"], 46, "orange", u=0, v=0.12, fontfile="consola.ttf")
        elif "broke again" in tx:
            panel(at(l, 0.2), l["t1"], 900, 150, u=0, v=0.38)
            card("NSTX-U STATUS: BROKEN (AGAIN)", at(l, 0.25), l["t1"], 54, "red", u=0, v=0.38,
                 fontfile="bahnschrift.ttf")
        elif "quench" in tx:
            card("⚠ MAGNET QUENCH ⚠", at(l, 0.3), l["t1"], 90, "red", u=0, v=0.4, fontfile="impact.ttf")
        elif "for free" in tx:
            card("INVOICE TOTAL: $0.00", at(l, 0.35), l["t1"], 80, "green", u=0, v=0.4, fontfile="consola.ttf")
        elif "donut" in tx:
            card("STATUS: DONUT", at(l, 0.3), l["t1"], 110, "mag", u=0, v=0.45, fontfile="impact.ttf")
            card("(always late)", at(l, 0.65), l["t1"], 50, "white", u=0, v=0.25, fontfile="segoeuib.ttf")
        elif "advisor" in tx:
            card("ADVISOR: 30 YRS  →  THEIR ADVISOR: 30 YRS", at(l, 0.2), l["t1"], 40, "cyan", u=0, v=0.4,
                 fontfile="bahnschrift.ttf")
qn_coil = min(COILS, key=lambda c: abs(c[0] - (-30)))[1] if COILS else None
if qn and qn_coil:
    lib.key(qn_coil, '["q"]', F(qn["t0"]) - 1, 0.0)
    lib.key(qn_coil, '["q"]', F(qn["t0"] + 0.25), 1.0)
    lib.key(qn_coil, '["q"]', F(qn["t0"] + 1.6), 0.0)

# ---- verse 2: the engineering bill ----
STAT = [("Fourteen", "14.1 MeV NEUTRONS  —  steel not consulted", "cyan"),
        ("dee-pee-ay", "FIRST WALL: 50 dpa  (cracking)", "orange"),
        ("tritium", "WORLD TRITIUM ~25 kg ~ 1 DOG", "white"),
        ("half gone", "HALF-LIFE 12.3 yr  —  backlog: ∞", "white"),
        ("divertor", "DIVERTOR: 10 MW/m²", "orange"),
        ("rocket nozzle", "= A ROCKET NOZZLE, 24/7", "red")]
if v2:
    rows = [(L(k), txt, c) for k, txt, c in STAT if L(k)]
    if rows:
        panel(rows[0][0]["t0"], v2["t1"], 900 if not VERTICAL else 1000, 80 + 62 * len(rows), u=-0.55,
              v=0.62 - 0.062 * (len(rows) - 1) * 1.0)
    for i, (l, txt, c) in enumerate(rows):
        card(txt, l["t0"] + 0.2, v2["t1"], 36, c, u=-LX + 0.04, v=0.74 - 0.12 * i, fontfile="bahnschrift.ttf",
             align="LEFT")
    hl = L("half gone")
    if hl:
        ob = lib.counter(nm("cnt"), hud, "TRITIUM LEFT ", "%", 100, 50, hl["t0"], hl["t1"], 56, M["yellow"],
                         u=0.55, v=0.5)
        lib.show(ob, [(hl["t0"], hl["t1"] + 1.0)])
        pill_for(ob, 56)

# ---- pre-chorus 2: disruption + ELMs ----
if dis:
    card("DISRUPTION!", dis["t0"], dis["t1"], 190, "white", u=0, v=0.4, fontfile="impact.ttf")
    card("runaway electrons → tile", at(dis, 0.35), dis["t1"], 46, "orange", u=0, v=0.14, fontfile="consola.ttf")
for k in (1, 2):
    elm = L("ELM crash", k)
    if elm:
        card("ELM CRASH ×50/s", elm["t0"], elm["split"], 130, "yellow", u=0, v=0.4, fontfile="impact.ttf",
             rot=3 if k == 1 else -3)
        card("take it with a smile :)", elm["t0"] + 0.45 * (elm["split"] - elm["t0"]), elm["split"], 44, "white",
             u=0, v=0.16)

# ---- verse 3: framework proliferation + paper-trail milestones ----
gr, fif = L("build a framework"), L("fifteen of those")
v3 = SEC.get("verse3")
if gr and v3:
    t_hide = (L("Quarterly") or {"t0": v3["t1"]})["t0"]
    cols, rows_ = (4, 4) if not VERTICAL else (3, 6)
    tiles = []
    for idx in range(16):
        r, c = divmod(idx, cols)
        u_ = -0.66 + c * (1.32 / (cols - 1))
        v_ = 0.66 - r * 0.22
        if idx == 0:
            t_in = at(gr, 0.5)
        elif idx < 15 and fif:
            t_in = at(fif, 0.05 + 0.6 * (idx / 15))
        else:
            t_in = at(fif or gr, 0.85)
        label = "FRAMEWORK" if idx < 15 else "FRAMEWORK #16\n(coming soon)"
        pnl = panel(t_in, t_hide, 330, 120, u=u_, v=v_, mat="panel")
        txt_ = card(label, t_in, t_hide, 30 if idx < 15 else 22, "cyan" if idx < 15 else "yellow", u=u_, v=v_,
                    fontfile="bahnschrift.ttf")
        tiles.append((u_, v_))
    logo = L("got a logo")
    if logo:
        card("LOGO ✓   WEBSITE ✓   WORKSHOP ✓", at(logo, 0.2), t_hide, 44, "green", u=0, v=-0.2,
             fontfile="bahnschrift.ttf")
    adop = L("adopted")
    if adop:
        card("ADOPTED", at(adop, 0.15), t_hide, 140, "green", u=0, v=0.3, fontfile="impact.ttf", rot=-12)
        card("USERS: 0", at(adop, 0.6), t_hide, 110, "red", u=0, v=0.0, fontfile="impact.ttf", rot=6)
    qr = L("Quarterly")
    if qr:
        chain = [("PROJECT  ●●●●  ALL GREEN", L("Quarterly")), ("PROGRAM MANAGER  ✓", L("Signed and stamped")),
                 ("OFFICE DIRECTOR  ✓", L("Program manager")), ("DC HIGHLIGHT SLIDE  ✓", L("Program manager"))]
        t_chain_end = (L("two stars") or qr)["t0"]
        for i, (lab, l) in enumerate(chain):
            if not l:
                continue
            t_in = at(l, 0.15 + (0.45 if i == 3 else 0))
            panel(t_in, t_chain_end, 760, 110, u=0, v=-0.25 + 0.24 * i)
            card(lab, t_in, t_chain_end, 40, "green", u=0, v=-0.25 + 0.24 * i, fontfile="bahnschrift.ttf")
            if i < 3:
                card("↑", t_in + 0.3, t_chain_end, 50, "dim", u=0, v=-0.13 + 0.24 * i, fontfile="segoeuib.ttf")
    stars = L("two stars")
    if stars:
        t1_ = v3["t1"]
        panel(stars["t0"], t1_, 900, 520, u=0, v=0.3)
        card("unified-fusion-framework", stars["t0"], t1_, 52, "white", u=0, v=0.6, fontfile="consola.ttf")
        card("★ 2", at(stars, 0.25), t1_, 90, "yellow", u=-0.15, v=0.4, fontfile="segoeuib.ttf")
        card("(one of them is me)", at(stars, 0.6), t1_, 34, "mag", u=0.2, v=0.4)
        card("IMPACT: TRANSFORMATIONAL ✓", at(stars, 0.75), t1_, 34, "green", u=0, v=0.24, fontfile="consola.ttf")
        card("LAST COMMIT: 2021", at(stars, 0.82), t1_, 34, "red", u=0, v=0.14, fontfile="consola.ttf")
        card("DOCS: ASPIRATIONAL", at(stars, 0.9), t1_, 34, "orange", u=0, v=0.04, fontfile="consola.ttf")

# ---- verse 4: extraction ----
fo = L("Founder wants")
v4 = SEC.get("verse4")
if fo and v4:
    obj_ = L("new objection")
    t_pp = (L("on paper") or obj_ or fo)["t0"] + 0.01
    names = ["PROPOSAL", "PROPOSAL v2", "PROPOSAL v3 (FINAL)", "PROPOSAL v4 (FINAL_final)"]
    times = [at(fo, 0.1), at(fo, 0.45), at(fo, 0.75), at(obj_, 0.3) if obj_ else at(fo, 0.9)]
    for i, (nm_, t_in) in enumerate(zip(names, times)):
        u_, v_ = -0.45 + 0.05 * i, 0.5 - 0.07 * i
        pp = panel(t_in, t_pp + 2.0, 520, 300, u=u_, v=v_, mat="paper", z=0.006 + 0.0004 * i)
        if pp:
            pp.rotation_euler.z = math.radians(random.uniform(-6, 6))
        lab_ = card(nm_, t_in, t_pp + 2.0, 40, "ink", u=u_ + 0.02 * i, v=v_ + 0.12 - 0.035 * i, fontfile="bahnschrift.ttf")
        if lab_:
            lab_.location.z += 0.0004 * i
    if obj_:
        card('"we\'ll get to equity"', at(obj_, 0.5), (L("on paper") or obj_)["t1"], 44, "yellow", u=0.42,
             v=0.55, fontfile="segoeuib.ttf")
    op = L("on paper")
    if op:
        ob = lib.counter(nm("cnt"), hud, "YOUR EQUITY: ", "%", 5, 0, at(op, 0.2), at(op, 0.85), 64, M["mag"],
                         u=0.42, v=0.3)
        lib.show(ob, [(op["t0"], op["t1"])])
        pill_for(ob, 64)
    col_ = L("collaborate through")
    if col_:
        panel(col_["t0"], col_["t1"], 1000, 230, u=0, v=0.35)
        card("COLLABORATION AGREEMENT", col_["t0"], col_["t1"], 52, "white", u=0, v=0.42, fontfile="bahnschrift.ttf")
        card("compensation: $0.00   |   timeline: forever", at(col_, 0.35), col_["t1"], 34, "red", u=0, v=0.3,
             fontfile="consola.ttf")
    tm = L("Want my time")
    if tm:
        card("THEM  →  YOUR SUPERVISOR  →  (you, eventually)", at(tm, 0.15), tm["t1"], 42, "cyan", u=0, v=0.4,
             fontfile="bahnschrift.ttf")
    fr_ = L("data that was free")
    if fr_:
        card("CO-AUTHOR REQUEST", at(fr_, 0.1), fr_["t1"], 90, "red", u=0, v=0.42, fontfile="impact.ttf", rot=-6)
        card("contribution: the data was already public", at(fr_, 0.45), fr_["t1"], 36, "white", u=0, v=0.2,
             fontfile="consola.ttf")

# ---- pre-chorus 3: opportunity / privilege ----
opp, priv = L("Opportunity!"), L("Privilege!")
if opp:
    card("OPPORTUNITY!", opp["t0"], opp["t1"], 170, "green", u=0, v=0.4, fontfile="impact.ttf", rot=-3)
    card("weekly meetings  •  pay: $0", at(opp, 0.4), opp["t1"], 44, "white", u=0, v=0.14, fontfile="bahnschrift.ttf")
if priv:
    card("PRIVILEGE!", priv["t0"], priv["t1"], 170, "yellow", u=0, v=0.4, fontfile="impact.ttf", rot=3)
    card("stipend $30K  •  rent $32K  •  hooray", at(priv, 0.35), priv["t1"], 44, "white", u=0, v=0.14,
         fontfile="bahnschrift.ttf")

# ---- bridge: 1976 chart, models of models ----
s76, fund = L("seventy-six"), L("funded us below")
if s76:
    t1_ = end(fund or s76, 0.5)
    cu0, cv0, cw, ch_ = -0.75, -0.32, 1.5, 0.95
    panel(s76["t0"], t1_, 1500 if not VERTICAL else 1000, 620, u=0, v=cv0 + ch_ / 2 + 0.03)
    lib.show(hud.polyline(nm("ax"), [(cu0, cv0 + ch_), (cu0, cv0), (cu0 + cw, cv0)], M["dim"], 3),
             [(s76["t0"], t1_)], pop=False)
    card("ERDA, 1976: FUSION FUNDING SCENARIOS", at(s76, 0.05), t1_, 30, "dim", u=cu0 + 0.02, v=cv0 + ch_ + 0.02,
         fontfile="bahnschrift.ttf", align="LEFT")
    curves = [("LOGIC I: ACCELERATED", 1.0, "green"), ("LOGIC III", 0.7, "cyan"),
              ("LOGIC V", 0.45, "yellow")]
    for i, (lab, peak, c) in enumerate(curves):
        pts = [(cu0 + cw * x, cv0 + ch_ * (0.25 + peak * 0.7 * math.sin(min(1, x * 1.6) * math.pi / 2)))
               for x in np.linspace(0, 1, 24)]
        pl_ = hud.polyline(nm("c76"), pts, M[c], 4)
        lib.key(pl_.data, "bevel_factor_end", F(at(s76, 0.1 + 0.1 * i)), 0.0)
        lib.key(pl_.data, "bevel_factor_end", F(at(s76, 0.5 + 0.1 * i)), 1.0)
        lib.show(pl_, [(s76["t0"], t1_)], pop=False)
        card(lab, at(s76, 0.55 + 0.1 * i), t1_, 24, c, u=cu0 + cw - 0.02, v=pts[-1][1] + 0.04,
             fontfile="bahnschrift.ttf", align="RIGHT")
    nv = hud.polyline(nm("never"), [(cu0, cv0 + ch_ * 0.22), (cu0 + cw, cv0 + ch_ * 0.22)], M["red"], 5)
    lib.key(nv.data, "bevel_factor_end", F(at(s76, 0.55)), 0.0)
    lib.key(nv.data, "bevel_factor_end", F(at(s76, 0.95)), 1.0)
    lib.show(nv, [(s76["t0"], t1_)], pop=False)
    card('"FUSION NEVER"', at(s76, 0.8), t1_, 30, "red", u=cu0 + cw - 0.02, v=cv0 + ch_ * 0.22 + 0.05,
         fontfile="bahnschrift.ttf", align="RIGHT")
    if fund:
        pts = [(cu0 + cw * x, cv0 + ch_ * (0.2 - 0.12 * x + 0.03 * math.sin(x * 9))) for x in np.linspace(0, 1, 24)]
        ac = hud.polyline(nm("actual"), pts, M["white"], 6)
        lib.key(ac.data, "bevel_factor_end", F(at(fund, 0.05)), 0.0)
        lib.key(ac.data, "bevel_factor_end", F(at(fund, 0.6)), 1.0)
        lib.show(ac, [(fund["t0"], t1_)], pop=False)
        card("ACTUAL FUNDING (us)", at(fund, 0.4), t1_, 30, "white", u=cu0 + cw * 0.5, v=cv0 + 0.03,
             fontfile="bahnschrift.ttf")
        card("...what took so long?", at(fund, 0.7), t1_, 40, "mag", u=0.35, v=0.5)
im = L("integrated model")
if im:
    card("INTEGRATED MODEL: FINE ✓", at(im, 0.4), im["t1"], 64, "green", u=0, v=0.4, fontfile="bahnschrift.ttf")
ro = L("Research ops")
if ro:
    card("ITER  •  RESEARCH OPS 2034  •  D–T 2039", at(ro, 0.1), ro["t1"], 50, "cyan", u=0, v=0.4,
         fontfile="bahnschrift.ttf")
sm_ = L("Six months")
if sm_:
    ob = lib.counter(nm("cnt"), hud, "SETUP: ", " MONTHS", 0, 6, at(sm_, 0.0), at(sm_, 0.45), 54, M["white"],
                     u=-0.4, v=0.4)
    lib.show(ob, [(sm_["t0"], sm_["t1"])])
    pill_for(ob, 54)
    ob = lib.counter(nm("cnt"), hud, "IN PRINT: ", " YEARS", 0, 2, at(sm_, 0.5), at(sm_, 0.95), 54, M["yellow"],
                     u=0.4, v=0.4)
    lib.show(ob, [(at(sm_, 0.5), sm_["t1"])])
    pill_for(ob, 54)
va = L("Validated on")
if va:
    panel(va["t0"], va["t1"], 1100, 170, u=0, v=0.4)
    card("VALIDATION TARGET: 404 REACTOR NOT FOUND", at(va, 0.25), va["t1"], 42, "red", u=0, v=0.4,
         fontfile="consola.ttf")
if sur:
    card("SURROGATE(", at(sur, 0.2), (L("plots") or sur)["t0"], 40, "green", u=-0.6, v=0.5, fontfile="consola.ttf")
if mom:
    card("MODEL(", at(mom, 0.05), mom["t1"], 40, "yellow", u=-0.25, v=0.5, fontfile="consola.ttf")
    card("PLASMA(?)))", at(mom, 0.5), mom["t1"], 40, "cyan", u=0.2, v=0.5, fontfile="consola.ttf")
if cg:
    # "the plots look good": a perfect fit to a tight cluster of experiments, extrapolated a long, long way
    T0 = cg["t0"]
    t1_ = (SEC.get("breakdown1") or {"t0": cg["t1"] + 2})["t0"]
    panel(T0, t1_, 1700 if not VERTICAL else 1040, 660, u=0, v=0.2, mat="panel_solid")
    ox, oy, x1, y1 = -0.8, -0.3, 0.8, 0.72
    lib.show(hud.polyline(nm("ax"), [(ox, y1), (ox, oy), (x1, oy)], M["dim"], 3), [(T0, t1_)], pop=False)
    card("GAIN", T0, t1_, 26, "dim", u=ox + 0.02, v=y1 - 0.02, fontfile="bahnschrift.ttf", align="LEFT")
    card("MACHINE SIZE (log)  →", T0, t1_, 26, "dim", u=x1, v=oy - 0.06, fontfile="bahnschrift.ttf", align="RIGHT")
    card("//", T0, t1_, 30, "dim", u=-0.33, v=oy, fontfile="bahnschrift.ttf")  # axis break

    def fit_v(u_):
        return -0.22 + 0.6 * (u_ + 0.74)

    for i in range(8):
        x = -0.72 + 0.022 * i
        card("●", T0 + 0.04 * i, t1_, 22, "white", u=x, v=fit_v(x) + random.uniform(-0.012, 0.012), pill=False)
    lib.show(hud.polyline(nm("fit"), [(-0.75, fit_v(-0.75)), (-0.52, fit_v(-0.52))], M["green"], 5),
             [(T0 + 0.3, t1_)], pop=False)
    card("EXPERIMENTAL\nRESULTS", T0 + 0.2, t1_, 30, "cyan", u=-0.62, v=0.16, fontfile="bahnschrift.ttf")
    card("R² = 0.9999 ✓", T0 + 0.5, t1_, 40, "green", u=-0.62, v=0.34, fontfile="consola.ttf")
    # dashed extrapolation, drawn dash by dash
    xa, xb, n_d = -0.52, 0.64, 18
    for k in range(n_d):
        a_ = xa + (xb - xa) * k / n_d
        b_ = a_ + (xb - xa) / n_d * 0.6
        lib.show(hud.polyline(nm("dash"), [(a_, fit_v(a_)), (b_, fit_v(b_))], M["green"], 5),
                 [(T0 + 0.6 + 0.8 * k / n_d, t1_)], pop=False)
    card("★", T0 + 1.4, t1_, 70, "mag", u=xb + 0.02, v=fit_v(xb), pill=False)
    card("POWER PLANT SCALE", T0 + 1.4, t1_, 34, "mag", u=xb - 0.02, v=fit_v(xb) + 0.1, fontfile="bahnschrift.ttf")
    card("(0 data points)", T0 + 1.9, t1_, 28, "red", u=xb - 0.02, v=fit_v(xb) - 0.1, fontfile="bahnschrift.ttf")
    # how far the extrapolation reaches
    yd = -0.22
    for pts in ([(-0.48, yd), (0.6, yd)], [(-0.45, yd + 0.03), (-0.48, yd), (-0.45, yd - 0.03)],
                [(0.57, yd + 0.03), (0.6, yd), (0.57, yd - 0.03)]):
        lib.show(hud.polyline(nm("dist"), pts, M["yellow"], 3), [(T0 + 1.7, t1_)], pop=False)
    card("~1000× bigger  ·  zero data", T0 + 1.7, t1_, 30, "yellow", u=0.1, v=yd + 0.07, fontfile="bahnschrift.ttf")

# ---- solar aside #1: the sun is the fusion reactor that already works ----
if pv:
    a_, b_ = SOLAR_WIN[0]
    card("PV + BATTERIES: ALREADY SHIPPING ✓", a_ + 0.1, b_, 60, "green", u=0, v=0.7, fontfile="bahnschrift.ttf")
    card("▲ the fusion reactor that already works\n150 million km away · free delivery · zero tritium", a_ + 0.6, b_,
         34, "yellow", u=0.1, v=0.3, fontfile="bahnschrift.ttf")


def solar_scoreboard(l, t1):
    t0 = l["t0"]
    card("SOLAR:", t0, t1, 44, "yellow", u=0, v=0.8, fontfile="bahnschrift.ttf")
    card("we shipped while you were in review.", at(l, 0.05), t1, 54, "white", u=0, v=0.66)
    panel(t0 + 0.15, t1, 1500 if not VERTICAL else 1000, 560, u=0, v=-0.02)
    cols = (-0.72, -0.02, 0.5)
    card("SOLAR + BATTERIES", t0 + 0.25, t1, 34, "yellow", u=cols[1], v=0.36, fontfile="bahnschrift.ttf")
    card("FUSION (best case)", t0 + 0.25, t1, 34, "mag", u=cols[2], v=0.36, fontfile="bahnschrift.ttf")
    rows = [("BUILD TIME", "months", "decades"), ("AVAILABLE", "today", "2050s, maybe"),
            ("FUEL", "sunlight, free", "tritium ~ 1 dog"), ("NEUTRONS", "none", "14 MeV, lots"),
            ("COST TREND", "falling every year", "TBD")]
    for i, (lab, good, bad) in enumerate(rows):
        tt, v_ = t0 + 0.45 + 0.16 * i, 0.2 - 0.13 * i
        card(lab, tt, t1, 30, "dim", u=cols[0], v=v_, fontfile="bahnschrift.ttf", align="LEFT")
        card(good + "  ✓", tt, t1, 32, "green", u=cols[1], v=v_, fontfile="bahnschrift.ttf")
        card(bad + "  ✗", tt + 0.08, t1, 32, "red", u=cols[2], v=v_, fontfile="bahnschrift.ttf")


# ---- breakdown: speaker cards ----
for s in SECTIONS:
    if s["kind"] != "breakdown":
        continue
    for l in s["lines"]:
        txt = l["text"]
        m_ = re.match(r"^(.*?)\s+says:\s*(.*)$", txt, re.S) or re.match(r"^(note to self):\s*(.*)$", txt, re.S | re.I)
        t_in = l["t0"]
        if solar and LINES.index(l) == LINES.index(solar) + 1:  # let the solar scoreboard breathe
            t_in = min(SOLAR_WIN[-1][1], at(l, 0.45))
        if m_ and m_.group(1).strip().lower() == "solar":
            solar_scoreboard(l, SOLAR_WIN[-1][1])
        elif m_:
            who, said = m_.group(1).upper(), m_.group(2)
            panel(t_in, l["t1"], 1600 if not VERTICAL else 1000, 420, u=0, v=0.12)
            card(who + ":", t_in, l["t1"], 46, "mag", u=0, v=0.33, fontfile="bahnschrift.ttf")
            body = "\n".join(lib.wrap(part, 34 if not VERTICAL else 22) for part in said.split("\n"))
            card(body, t_in + 0.08 * (l["t1"] - l["t0"]), l["t1"], 66 if len(said) < 70 else 54, "white", u=0,
                 v=0.05, accent="yellow")
        elif "approved" in txt.lower():
            card("APPROVED", l["t0"], l["t1"] + 1.5, 230, "red", u=0, v=0.3, fontfile="impact.ttf", rot=-10)
            card("SHIP THE REACTOR", at(l, 0.45), l["t1"] + 1.5, 80, "white", u=0, v=-0.05, fontfile="impact.ttf")
        else:
            card(lib.wrap(txt, 34), l["t0"], l["t1"], 60, "white", u=0, v=0.1, accent="yellow")

# ---- outro ----
if out_sec:
    mk = L("thirty-five")
    if mk:
        ob = lib.counter(nm("cnt"), hud, "FUSION ETA: ", "", 2056, 2061, at(mk, 0.1), at(mk, 0.7), 64, M["mag"],
                         u=0, v=0.4)
        lib.show(ob, [(mk["t0"], (L("don't wait up") or mk)["t1"])])
        pill_for(ob, 64)
    if bench_l_:
        card("TASK: fold_laundry.py", tb + 0.4, t_drop + 1.0, 40, "cyan", u=-0.88, v=0.62, fontfile="consola.ttf",
             align="LEFT")
        ob = lib.counter(nm("cnt"), hud, "FOLDING... ", "%", 0, 87, tw0, t_drop, 44, M["yellow"], u=-0.88, v=0.5,
                         align="left", fontfile="consola.ttf")
        lib.show(ob, [(tw0, t_drop + 1.0)], pop=False)
        pill_for(ob, 44)
        t_end_fail = (lunch_line["t1"] + 0.6) if lunch_line else DUR
        card("TEST: FAILED ✗", t_drop + 0.35, t_end_fail, 110, "red", u=0.42, v=0.5, fontfile="impact.ttf", rot=-4)
        card("better luck next time ;)", t_drop + 0.9, t_end_fail, 46, "white", u=0.42, v=0.3)
    lu = L("by lunch")
    if lu:
        for txt_, a_, b_ in (("11:59", lu["t0"] - 0.6, at(lu, 0.55)), ("12:00  LUNCH", at(lu, 0.55), lu["t1"] + 0.8)):
            card(txt_, a_, b_, 70, "yellow", u=-0.55, v=0.45, fontfile="consola.ttf", pop=False)
        t_card = lu["t1"] + 0.6
        card("THIRTY YEARS AWAY", t_card, DUR + 1, 150, "mag", u=0, v=0.1, fontfile="impact.ttf")
        card("a song about fusion, mostly", t_card + 0.6, DUR + 1, 44, "dim", u=0, v=-0.12, fontfile="bahnschrift.ttf")

# ---- dark rounded backings behind text, sized from the evaluated text bounds ----
dg = bpy.context.evaluated_depsgraph_get()
dg.update()
for ob, pad, pm in PILLS:
    bb = ob.evaluated_get(dg).bound_box
    xs, ys = [c[0] for c in bb], [c[1] for c in bb]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    if w <= 1e-6 or h <= 1e-6:
        continue
    me = lib.rounded_rect_mesh(ob.name + "_pill", w + 2 * pad, h + 1.3 * pad, min(w, h) * 0.25 + pad * 0.6)
    pb = bpy.data.objects.new(ob.name + "_pill", me)
    pb.parent = ob
    pb.location = ((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2, -0.002)
    me.materials.append(M[pm])
    lib.link(pb, HUDC)
    lib.no_shadow(pb)
print("pills:", len(PILLS))

# ==========================================================================
# compositor: subtle bloom only
# ==========================================================================
ng = bpy.data.node_groups.new("Post", "CompositorNodeTree")
ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
rl = ng.nodes.new("CompositorNodeRLayers")
gl = ng.nodes.new("CompositorNodeGlare")
lib._menu(gl.inputs["Type"], "Bloom", "BLOOM")
gl.inputs["Threshold"].default_value = 1.4
gl.inputs["Strength"].default_value = 0.3
gl.inputs["Size"].default_value = 0.55
go = ng.nodes.new("NodeGroupOutput")
ng.links.new(rl.outputs["Image"], gl.inputs["Image"])
ng.links.new(gl.outputs["Image"], go.inputs[0])
sc.compositing_node_group = ng
sc.render.use_compositing = True

# ==========================================================================
# output defaults + save
# ==========================================================================
sc.render.image_settings.file_format = "PNG"
sc.render.filepath = str(HERE / "render" / "frame_")
sc.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT))
print(f"saved {OUT}  frames={N}  objects={len(bpy.data.objects)}")
