"""YouTube art for the channel: thumbnail, banner and avatar.

Flat neon-on-slate look (the "music video made with Claude" trend), built in Blender
with an orthographic camera where 1 unit = 100 px.

blender -b --factory-startup -P video/make_youtube_art.py -- [thumbnail] [banner] [avatar]
-> video/out/youtube_thumbnail.png (1280x720), youtube_banner.png (2560x1440), youtube_avatar.png (800x800)
"""
import math
import random
import sys
from pathlib import Path

import bpy

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lib  # noqa: E402

FONTS = HERE / "fonts"
SLAB = str(FONTS / "AlfaSlabOne-Regular.ttf")
POP_X = str(FONTS / "Poppins-ExtraBold.ttf")
POP_B = str(FONTS / "Poppins-Bold.ttf")
MONO = "consola.ttf"

SLATE = (0.011, 0.013, 0.017)
MAG = (1.0, 0.04, 0.5)
CYAN = (0.15, 0.85, 1.0)
WHITE = (0.93, 0.94, 0.96)
ORANGE = (0.72, 0.17, 0.08)
SHIRT = (0.02, 0.33, 0.42)
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
WHAT = set(argv) or {"thumbnail", "banner", "avatar"}


# --------------------------------------------------------------------------
# scene helpers
# --------------------------------------------------------------------------
def setup(w, h, bloom=0.5):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    lib._fonts.clear()  # fonts from the previous scene are gone after the reset
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x, sc.render.resolution_y = w, h
    sc.render.filter_size = 1.0
    sc.eevee.taa_render_samples = 32
    sc.view_settings.view_transform = "Standard"
    world = bpy.data.worlds.new("W")
    sc.world = world
    if world.node_tree is None:
        world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (*SLATE, 1)
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = w / 100
    cam.data.sensor_fit = "HORIZONTAL"
    cam.location = (0, 0, 20)
    sc.collection.objects.link(cam)
    sc.camera = cam
    ng = bpy.data.node_groups.new("Post", "CompositorNodeTree")
    ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    rl = ng.nodes.new("CompositorNodeRLayers")
    gl = ng.nodes.new("CompositorNodeGlare")
    lib._menu(gl.inputs["Type"], "Bloom", "BLOOM")
    gl.inputs["Threshold"].default_value = 0.85
    gl.inputs["Strength"].default_value = bloom
    go = ng.nodes.new("NodeGroupOutput")
    ng.links.new(rl.outputs["Image"], gl.inputs["Image"])
    ng.links.new(gl.outputs["Image"], go.inputs[0])
    sc.compositing_node_group = ng
    sc.render.use_compositing = True
    return sc, sc.collection


def flat(name, color, strength=1.0, alpha=None):
    return lib.emission_mat(name, color, strength, alpha=alpha, blended=True)


def grit(name, color, strength=1.3, specks=0.62):
    """Neon fill with dark speckles, like a worn rubber stamp."""
    m, nt, out = lib.new_mat(name, blended=True)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    nz = nt.nodes.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 22
    nz.inputs["Detail"].default_value = 12
    nt.links.new(tc.outputs["Object"], nz.inputs["Vector"])
    speck = lib.math_(nt, "GREATER_THAN", nz.outputs["Fac"], specks)
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(lib.mix_rgb(nt, speck, color, (0.03, 0.05, 0.05)), em.inputs["Color"])
    em.inputs["Strength"].default_value = strength
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    return m


def soft_disc(name, color, strength, alpha):
    """Out-of-focus bokeh disc."""
    m, nt, out = lib.new_mat(name, blended=True)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    vm = nt.nodes.new("ShaderNodeVectorMath")
    vm.operation = "DISTANCE"
    nt.links.new(tc.outputs["UV"], vm.inputs[0])
    vm.inputs[1].default_value = (0.5, 0.5, 0)
    mr = nt.nodes.new("ShaderNodeMapRange")
    nt.links.new(vm.outputs["Value"], mr.inputs[0])
    mr.inputs[1].default_value, mr.inputs[2].default_value = 0.32, 0.5
    mr.inputs[3].default_value, mr.inputs[4].default_value = alpha, 0.0
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (*color, 1)
    em.inputs["Strength"].default_value = strength
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    mx = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(mr.outputs[0], mx.inputs[0])
    nt.links.new(tr.outputs[0], mx.inputs[1])
    nt.links.new(em.outputs[0], mx.inputs[2])
    nt.links.new(mx.outputs[0], out.inputs["Surface"])
    return m


def rrect(C, name, w, h, r, mat, x, y, z, parent=None, rot=0.0):
    ob = bpy.data.objects.new(name, lib.rounded_rect_mesh(name, w, h, r))
    ob.location = (x, y, z)
    ob.rotation_euler.z = math.radians(rot)
    ob.data.materials.append(mat)
    if parent:
        ob.parent = parent
    C.objects.link(ob)
    return ob


def poly(C, name, pts, mat, z, parent=None):
    me = bpy.data.meshes.new(name)
    me.from_pydata([(x, y, 0) for x, y in pts], [], [list(range(len(pts)))])
    ob = bpy.data.objects.new(name, me)
    ob.location.z = z
    me.materials.append(mat)
    if parent:
        ob.parent = parent
    C.objects.link(ob)
    return ob


def txt(C, body, size, mats, x, y, z, fontfile, align="CENTER", colors=None, parent=None, rot=0.0):
    """colors: optional list of material indices, one per character."""
    ob = lib.text(f"T_{body[:12]}", body, C, size, mats, fontfile=fontfile, align=align, loc=(x, y, z),
                  rot=(0, 0, math.radians(rot)), hud=False)
    if colors:
        for i, mi in enumerate(colors):
            ob.data.body_format[i].material_index = mi
    if parent:
        ob.parent = parent
    return ob


def bokeh(C, n, half_w, half_h, seed, z=0.05):
    rnd = random.Random(seed)
    mats = [soft_disc(f"bokeh{i}", (0.55, 0.6, 0.7), 1.0, a) for i, a in enumerate((0.05, 0.09, 0.14))]
    for i in range(n):
        s = rnd.uniform(0.25, 0.9)
        ob = lib.plane(f"bk{i}", s, s, C, loc=(rnd.uniform(-half_w, half_w), rnd.uniform(-half_h, half_h), z))
        ob.data.materials.append(rnd.choice(mats))


def tile(C, letter, size, x, y, rot, neon, z=1.0):
    """Chunky letter block: neon frame, dark face, gritty extruded letter with a brown 3D edge."""
    pv = lib.empty(f"tile_{letter}_{x:.1f}", C, loc=(x, y, z))
    pv.rotation_euler.z = math.radians(rot)
    edge = flat("tile_edge", (0.32, 0.17, 0.06))
    d = size * 0.035
    rrect(C, "edge", size, size, size * 0.17, edge, d, -d, 0.0, pv)
    rrect(C, "frame", size, size, size * 0.17, grit(f"frame_{letter}", neon, 1.0, 0.66), 0, 0, 0.01, pv)
    rrect(C, "gap", size * 0.88, size * 0.88, size * 0.12, flat("tile_dark", (0.02, 0.03, 0.035)), 0, 0, 0.02, pv)
    rrect(C, "inner", size * 0.82, size * 0.82, size * 0.1, flat("tile_line", neon, 1.0), 0, 0, 0.03, pv)
    rrect(C, "face", size * 0.78, size * 0.78, size * 0.09, flat("tile_face", (0.025, 0.035, 0.04)), 0, 0, 0.04, pv)
    txt(C, letter, size * 0.72, [edge], d * 1.1, -size * 0.04 - d * 1.1, 0.05, SLAB, parent=pv)
    txt(C, letter, size * 0.72, [grit(f"letter_{letter}", neon, 1.1, 0.6)], 0, -size * 0.04, 0.06, SLAB, parent=pv)
    return pv


def glow_line(C, name, pts, width, mat, z, taper=None):
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    sp = cu.splines.new("POLY")
    sp.points.add(len(pts) - 1)
    for i, (p_, q_) in enumerate(pts):
        sp.points[i].co = (p_, q_, 0, 1)
        sp.points[i].radius = taper[i] if taper else 1.0
    cu.bevel_depth = width / 2
    cu.bevel_resolution = 2
    cu.materials.append(mat)
    ob = bpy.data.objects.new(name, cu)
    ob.location.z = z
    C.objects.link(ob)
    return ob


def ellipse_ring(C, name, rx, ry, width, mat, x, y, z, rot):
    pts = [(rx * math.cos(2 * math.pi * k / 160), ry * math.sin(2 * math.pi * k / 160)) for k in range(161)]
    ob = glow_line(C, name, pts, width, mat, z)
    ob.location.x, ob.location.y = x, y
    ob.rotation_euler.z = math.radians(rot)
    return ob


def render(sc, name):
    sc.render.image_settings.file_format = "PNG"
    sc.render.filepath = str(OUT / name)
    bpy.ops.render.render(write_still=True)
    print("wrote", sc.render.filepath)


# --------------------------------------------------------------------------
# thumbnail 1280x720
# --------------------------------------------------------------------------
if "thumbnail" in WHAT:
    sc, C = setup(1280, 720, bloom=0.55)
    bokeh(C, 14, 6.4, 3.6, seed=3)
    # the card: a data file nobody wants to update
    cx, cw, ch = -1.075, 9.85, 6.4
    rrect(C, "card_border", cw + 0.04, ch + 0.04, 0.17, flat("border", (0.35, 0.38, 0.45), 1.0, alpha=0.35), cx, 0, 0.1)
    rrect(C, "card", cw, ch, 0.15, flat("card", (0.013, 0.015, 0.02), 1.0, alpha=0.94), cx, 0, 0.11)
    m_hdr, m_hdr_dim = flat("hdr", (0.5, 0.52, 0.56)), flat("hdr_dim", (0.28, 0.3, 0.34))
    head = "fusion_eta.csv: bump ETA again  #1958"
    txt(C, head, 0.27, [m_hdr, m_hdr_dim], -5.68, 2.78, 0.2, POP_B, align="LEFT",
        colors=[0 if i < head.index("#") else 1 for i in range(len(head))])
    txt(C, "+30 yrs", 0.27, [flat("plus", CYAN, 1.1)], 3.55, 2.78, 0.2, MONO, align="RIGHT")
    m_code = flat("code", (0.075, 0.08, 0.09))
    for k in range(15):
        yr = 1958 + 5 * k
        txt(C, f'+ year: {yr}   eta: {yr + 30}   status: "soon"', 0.21, [m_code], -5.68, 2.28 - 0.31 * k, 0.15,
            MONO, align="LEFT")
    txt(C, "0 of 68 deadlines met", 0.21, [flat("foot", (0.38, 0.4, 0.44))], -5.68, -2.92, 0.2, MONO, align="LEFT")
    # the tiles
    for letter, x, rot in (("S", -4.47, -3), ("O", -2.22, 2.5), ("O", 0.03, -2), ("N", 2.28, 3.5)):
        tile(C, letter, 2.05, x, 0.85, rot, MAG)
    # the subtitle, "thirty years away" with magenta accents
    sub = "thirty years away"
    accent = {0, 7, 8, 9, 10, 11, 13}
    txt(C, sub, 1.02, [flat("sub_w", WHITE, 1.0), flat("sub_m", MAG, 1.05)], -1.15, -1.62, 1.2, POP_X,
        colors=[1 if i in accent else 0 for i in range(len(sub))])
    # mascot: an orange box robot, dropping the T-shirt it was supposed to fold
    m_or = flat("robot", ORANGE, 1.0)
    m_or_dk = flat("robot_dk", (0.33, 0.06, 0.025))
    m_ink = flat("ink", (0.04, 0.03, 0.03))
    bx, by = 4.95, -2.2
    rrect(C, "shadow", 2.3, 0.35, 0.17, flat("shadow", (0, 0, 0), 1.0, alpha=0.55), bx, -3.32, 2.0)
    for k, lx in enumerate((-0.55, -0.2, 0.2, 0.55)):
        rrect(C, f"leg{k}", 0.16, 0.6, 0.03, m_or, bx + lx, by - 0.78, 2.05)
    rrect(C, "body", 1.7, 1.15, 0.06, m_or, bx, by, 2.1)
    for k in range(6):
        rrect(C, f"stripe{k}", 1.62, 0.025, 0.01, m_or_dk, bx, by - 0.38 + 0.15 * k, 2.11)
    for ex in (-0.35, 0.35):
        rrect(C, "eye", 0.2, 0.3, 0.03, m_ink, bx + ex, by + 0.18, 2.12)
    gx, gy = bx + 0.05, by + 2.3  # gripper
    glow_line(C, "arm", [(bx + 0.35, by + 0.5), (bx + 0.9, by + 1.45), (gx, gy)], 0.16, m_or, 2.05)
    shirt = lib.empty("shirt", C, loc=(gx, gy - 0.08, 2.08))
    shirt.rotation_euler.z = math.radians(-30)
    shirt.scale = (0.8, 0.8, 1)
    tee = [(-0.18, 0), (-0.5, -0.05), (-0.85, -0.35), (-0.68, -0.6), (-0.5, -0.45), (-0.5, -1.3), (0.5, -1.3),
           (0.5, -0.45), (0.68, -0.6), (0.85, -0.35), (0.5, -0.05), (0.18, 0), (0, -0.14)]
    poly(C, "tee", tee, flat("tee", SHIRT, 1.0), 0.0, shirt)
    rrect(C, "grip", 0.46, 0.15, 0.03, m_or_dk, gx, gy, 2.1)
    m_wh = flat("whoosh", (0.45, 0.5, 0.56))
    for k, (x0, y0) in enumerate(((-1.05, -0.35), (-0.8, -0.05), (-1.3, -0.75))):
        glow_line(C, f"whoosh{k}", [(gx + x0, gy + y0), (gx + x0 + 0.08, gy + y0 + 0.4)], 0.035, m_wh, 2.0)
    render(sc, "youtube_thumbnail.png")

# --------------------------------------------------------------------------
# banner 2560x1440 (everything that matters inside the 1546x423 safe area)
# --------------------------------------------------------------------------
if "banner" in WHAT:
    sc, C = setup(2560, 1440, bloom=0.6)
    bokeh(C, 26, 12.8, 7.2, seed=11)
    m_line = flat("line", MAG, 2.0)
    glow_line(C, "field", [(-12.8, -1.25), (4.6, -1.25)], 0.05, m_line, 1.0, taper=[0.3, 1.0])
    glow_line(C, "escape", [(4.6, -1.25), (6.6, -0.2)], 0.05, flat("esc", (1.0, 0.6, 0.9), 2.5), 1.0)
    rrect(C, "electron", 0.28, 0.28, 0.02, flat("e", (1, 1, 1), 12.0), 6.6, -0.2, 1.1)
    txt(C, "Runaway Electrons", 1.55, [flat("name", WHITE, 1.0)], 0, 0.55, 1.2, POP_X)
    tag = "songs that escape confinement  ·  made with Suno, animated in code by Claude"
    txt(C, tag, 0.36, [flat("tag", (0.55, 0.58, 0.64))], 0, -0.55, 1.2, POP_B)
    render(sc, "youtube_banner.png")

# --------------------------------------------------------------------------
# avatar 800x800: one confined plasma, one electron getting out
# --------------------------------------------------------------------------
if "avatar" in WHAT:
    av3d = OUT / "youtube_avatar.png"
    if av3d.exists() and not (OUT / "youtube_avatar_3d.png").exists():
        av3d.replace(OUT / "youtube_avatar_3d.png")  # keep the earlier 3D version as an alternative
    sc, C = setup(800, 800, bloom=0.9)
    bpy.data.node_groups["Post"].nodes["Glare"].inputs["Threshold"].default_value = 0.55
    sc.world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.012, 0.01, 0.014, 1)
    rx, ry, rot, cxa, cya = 2.5, 0.95, math.radians(-10), -0.35, -0.45
    ellipse_ring(C, "plasma", rx, ry, 0.08, flat("ring", MAG, 1.0), cxa, cya, 1.0, math.degrees(rot))

    def on_ring(th):
        x_, y_ = rx * math.cos(th), ry * math.sin(th)
        return (cxa + x_ * math.cos(rot) - y_ * math.sin(rot), cya + x_ * math.sin(rot) + y_ * math.cos(rot))

    th0 = math.radians(28)
    p0, p1 = on_ring(th0), on_ring(th0 + 0.01)
    tx, ty = p1[0] - p0[0], p1[1] - p0[1]
    n_ = math.hypot(tx, ty)
    end = (p0[0] + 2.1 * tx / n_ + 0.5, p0[1] + 2.1 * ty / n_ + 0.9)
    glow_line(C, "escape", [p0, ((p0[0] + end[0]) / 2 + 0.15, (p0[1] + end[1]) / 2 - 0.05), end], 0.06,
              flat("esc", (1.0, 0.3, 0.75), 1.4), 1.0, taper=[0.35, 0.7, 1.0])
    rrect(C, "electron", 0.36, 0.36, 0.03, flat("e", (1, 1, 1), 14.0), end[0], end[1], 1.1, rot=-10)
    render(sc, "youtube_avatar.png")

# --------------------------------------------------------------------------
# thumbnail hero (2560x1440, black): a glowing tokamak plasma ring, lit like an accretion disk.
# make_thumbnail.py sets the type on top of it.
# --------------------------------------------------------------------------
if "thumbhero" in WHAT:
    sc, C = setup(2560, 1440, bloom=0.85)
    sc.eevee.taa_render_samples = 64
    sc.world.node_tree.nodes["Background"].inputs["Color"].default_value = (0, 0, 0, 1)
    HOT = (1.0, 0.03, 0.42)
    ring = lib.spin("Plasma", lib.d_profile(1.6, 0.4, 1.35, 0.3, 72), C, segs=256)
    m, nt, out = lib.new_mat("PlasmaHero", blended=True)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sx = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Object"], sx.inputs[0])
    rad = nt.nodes.new("ShaderNodeVectorMath")
    rad.operation = "LENGTH"
    nt.links.new(tc.outputs["Object"], rad.inputs[0])
    bands = lib.math_(nt, "ADD", 0.8, lib.math_(nt, "MULTIPLY", lib.math_(nt, "SINE", lib.math_(nt, "MULTIPLY", rad.outputs["Value"], 55.0)), 0.2))
    lw = nt.nodes.new("ShaderNodeLayerWeight")
    lw.inputs["Blend"].default_value = 0.5
    edge = lib.math_(nt, "ADD", 0.1, lib.math_(nt, "MULTIPLY", lib.math_(nt, "POWER", lw.outputs["Facing"], 2.6), 2.8))
    hot_side = nt.nodes.new("ShaderNodeMapRange")  # one side runs white-hot, like a beamed accretion disk
    nt.links.new(sx.outputs[0], hot_side.inputs[0])
    hot_side.inputs[1].default_value, hot_side.inputs[2].default_value = 0.4, 2.1
    hot_side.inputs[3].default_value, hot_side.inputs[4].default_value = 0.0, 1.0
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(lib.mix_rgb(nt, lib.math_(nt, "MULTIPLY", hot_side.outputs[0], 0.75), HOT, (1.0, 0.85, 0.95)), em.inputs["Color"])
    st = lib.math_(nt, "MULTIPLY", lib.math_(nt, "MULTIPLY", bands, edge),
                  lib.math_(nt, "ADD", 1.0, lib.math_(nt, "MULTIPLY", hot_side.outputs[0], 2.5)))
    nt.links.new(st, em.inputs["Strength"])
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    add = nt.nodes.new("ShaderNodeAddShader")
    nt.links.new(tr.outputs[0], add.inputs[0])
    nt.links.new(em.outputs[0], add.inputs[1])
    nt.links.new(add.outputs[0], out.inputs["Surface"])
    ring.data.materials.append(m)
    black = flat("black", (0, 0, 0), 1.0)
    black.surface_render_method = "DITHERED"
    bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=0.5, depth=2.3)
    bpy.context.active_object.data.materials.append(black)
    prof = lib.d_profile(1.65, 0.85, 1.35, 0.4, 64)
    for k in range(14):
        phi = 2 * math.pi * k / 14 + 0.11
        cu = bpy.data.curves.new(f"TF{k}", "CURVE")
        cu.dimensions = "3D"
        sp = cu.splines.new("POLY")
        sp.points.add(len(prof) - 1)
        for pt, (R, Z) in zip(sp.points, prof):
            pt.co = (R * math.cos(phi), R * math.sin(phi), Z, 1)
        sp.use_cyclic_u = True
        cu.bevel_depth = 0.026
        cu.materials.append(black)
        C.objects.link(bpy.data.objects.new(f"TF{k}", cu))
    cam = sc.camera
    cam.data.type = "PERSP"
    cam.data.lens = 50
    cam.location = (0, -12.2, 3.5)
    tgt = lib.empty("Target", C, loc=(0, 0, -1.12))
    c = cam.constraints.new("TRACK_TO")
    c.target = tgt
    c.track_axis = "TRACK_NEGATIVE_Z"
    c.up_axis = "UP_Y"
    render(sc, "thumb_hero.png")
