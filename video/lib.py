"""Small helper layer over bpy for building the music video procedurally.

Everything here is scene-agnostic: materials, keyframes, per-frame baking,
camera-locked HUD text and geometry-node counters.
"""
import math
import re

import bpy
from bpy_extras import anim_utils

FPS = 30
FONT_DIR = "C:/Windows/Fonts/"
SYMBOLS = set("✓✔✗✘★☆⚠●▲▼◆■□→←↑↓≈∞")


def F(t):
    """Seconds -> frame number (frame 1 == t=0)."""
    return int(round(t * FPS)) + 1


# --------------------------------------------------------------------------
# collections / objects
# --------------------------------------------------------------------------
def coll(name, parent=None):
    c = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    p = parent or bpy.context.scene.collection
    if c.name not in [x.name for x in p.children]:
        p.children.link(c)
    return c


def link(ob, collection):
    collection.objects.link(ob)
    return ob


def empty(name, collection, loc=(0, 0, 0), parent=None, size=0.5):
    ob = bpy.data.objects.new(name, None)
    ob.empty_display_size = size
    ob.location = loc
    if parent:
        ob.parent = parent
    return link(ob, collection)


def mesh_obj(name, verts, faces, collection, smooth=True, parent=None):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
    ob = bpy.data.objects.new(name, me)
    if parent:
        ob.parent = parent
    return link(ob, collection)


def plane(name, w, h, collection, parent=None, loc=(0, 0, 0)):
    x, y = w / 2, h / 2
    ob = mesh_obj(name, [(-x, -y, 0), (x, -y, 0), (x, y, 0), (-x, y, 0)], [(0, 1, 2, 3)], collection,
                  smooth=False, parent=parent)
    ob.location = loc
    uv = ob.data.uv_layers.new(name="UVMap")
    for i, c in enumerate([(0, 0), (1, 0), (1, 1), (0, 1)]):
        uv.data[i].uv = c
    return ob


def rounded_rect_mesh(name, w, h, r, seg=6):
    """Flat rounded rectangle centred on the origin (UVs span 0..1)."""
    r = max(0.0, min(r, w / 2, h / 2))
    pts = []
    for cx, cy, a0 in ((w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90), (-w / 2 + r, -h / 2 + r, 180),
                       (w / 2 - r, -h / 2 + r, 270)):
        for k in range(seg + 1):
            a = math.radians(a0 + 90 * k / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a), 0.0))
    me = bpy.data.meshes.new(name)
    me.from_pydata(pts, [], [list(range(len(pts)))])
    me.update()
    uv = me.uv_layers.new(name="UVMap")
    for li, loop in enumerate(me.loops):
        x, y, _ = pts[loop.vertex_index]
        uv.data[li].uv = (x / w + 0.5, y / h + 0.5)
    return me


def no_shadow(ob):
    for attr in ("visible_shadow",):
        if hasattr(ob, attr):
            setattr(ob, attr, False)
    return ob


# --------------------------------------------------------------------------
# materials
# --------------------------------------------------------------------------
def new_mat(name, blended=False):
    m = bpy.data.materials.new(name)
    if m.node_tree is None:
        m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (600, 0)
    m.surface_render_method = "BLENDED" if blended else "DITHERED"
    return m, nt, out


def sock(nt, v):
    """Return a socket, or a Value node output holding constant v."""
    if isinstance(v, (int, float)):
        n = nt.nodes.new("ShaderNodeValue")
        n.outputs[0].default_value = float(v)
        return n.outputs[0]
    return v


def math_(nt, op, a, b=None, clamp=False):
    n = nt.nodes.new("ShaderNodeMath")
    n.operation = op
    n.use_clamp = clamp
    for i, v in enumerate([a, b]):
        if v is None:
            continue
        if isinstance(v, (int, float)):
            n.inputs[i].default_value = float(v)
        else:
            nt.links.new(v, n.inputs[i])
    return n.outputs[0]


def attr(nt, name, kind="VIEW_LAYER"):
    """Read a scene/view-layer (or object) custom property inside a shader."""
    n = nt.nodes.new("ShaderNodeAttribute")
    n.attribute_type = kind
    n.attribute_name = name
    return n.outputs["Fac"]


def rgb(nt, color):
    n = nt.nodes.new("ShaderNodeRGB")
    n.outputs[0].default_value = (*color[:3], 1)
    return n.outputs[0]


def mix_rgb(nt, fac, a, b):
    n = nt.nodes.new("ShaderNodeMix")
    n.data_type = "RGBA"
    for s, v in ((0, fac), (6, a), (7, b)):
        if isinstance(v, (int, float)):
            n.inputs[s].default_value = v
        elif isinstance(v, tuple):
            n.inputs[s].default_value = (*v[:3], 1)
        else:
            nt.links.new(v, n.inputs[s])
    return n.outputs[2]


def emission_mat(name, color, strength=1.0, alpha=None, blended=True):
    """Unlit emissive material; alpha may be a float or a scene property name."""
    m, nt, out = new_mat(name, blended=blended)
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (*color[:3], 1)
    em.inputs["Strength"].default_value = strength
    if alpha is None:
        nt.links.new(em.outputs[0], out.inputs["Surface"])
        return m
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    mx = nt.nodes.new("ShaderNodeMixShader")
    a = attr(nt, alpha) if isinstance(alpha, str) else sock(nt, alpha)
    nt.links.new(a, mx.inputs[0])
    nt.links.new(tr.outputs[0], mx.inputs[1])
    nt.links.new(em.outputs[0], mx.inputs[2])
    nt.links.new(mx.outputs[0], out.inputs["Surface"])
    return m


def principled(name, base, metallic=0.0, roughness=0.5, emission=None, em_strength=0.0):
    m, nt, out = new_mat(name)
    p = nt.nodes.new("ShaderNodeBsdfPrincipled")
    p.inputs["Base Color"].default_value = (*base[:3], 1)
    p.inputs["Metallic"].default_value = metallic
    p.inputs["Roughness"].default_value = roughness
    if emission:
        p.inputs["Emission Color"].default_value = (*emission[:3], 1)
        p.inputs["Emission Strength"].default_value = em_strength
    nt.links.new(p.outputs[0], out.inputs["Surface"])
    return m, nt, p


# --------------------------------------------------------------------------
# animation
# --------------------------------------------------------------------------
def fcurves(id_):
    ad = id_.animation_data
    if not ad or not ad.action:
        return []
    cb = anim_utils.action_get_channelbag_for_slot(ad.action, ad.action_slot)
    return cb.fcurves if cb else []


def find_fc(id_, path, index=0):
    for fc in fcurves(id_):
        if fc.data_path == path and fc.array_index == index:
            return fc
    return None


def _set_path(id_, path, value, index):
    if path.startswith('["'):
        id_[path[2:-2]] = value
        return
    owner, attr_name = (id_, path) if "." not in path else (id_.path_resolve(path.rsplit(".", 1)[0]), path.rsplit(".", 1)[1])
    if index < 0:
        setattr(owner, attr_name, value)
    else:
        getattr(owner, attr_name)[index] = value


def key(id_, path, frame, value, index=-1, interp=None):
    """Set a value and keyframe it. interp: None(=bezier) / 'LINEAR' / 'CONSTANT'."""
    _set_path(id_, path, value, index)
    id_.keyframe_insert(path, index=index, frame=frame)
    if interp:
        for fc in fcurves(id_):
            if fc.data_path == path and (index < 0 or fc.array_index == index):
                for kp in fc.keyframe_points:
                    if abs(kp.co.x - frame) < 0.01:
                        kp.interpolation = interp


def bake(id_, path, values, index=-1, start=1, interp="LINEAR"):
    """Write one key per frame from a sequence of floats."""
    _set_path(id_, path, float(values[0]), index)
    id_.keyframe_insert(path, index=index, frame=start)
    fc = find_fc(id_, path, max(index, 0))
    fc.keyframe_points.clear()
    n = len(values)
    fc.keyframe_points.add(n)
    co = []
    for i, v in enumerate(values):
        co += [start + i, float(v)]
    fc.keyframe_points.foreach_set("co", co)
    ival = {"CONSTANT": 0, "LINEAR": 1, "BEZIER": 2}[interp]
    fc.keyframe_points.foreach_set("interpolation", [ival] * n)
    fc.update()
    return fc


def scene_prop(scene, name, values):
    scene[name] = 0.0
    return bake(scene, f'["{name}"]', values)


def drive(target, path, expr, variables, index=-1):
    """variables: list of (name, id_type, id, data_path)."""
    fc = target.driver_add(path, index) if index >= 0 else target.driver_add(path)
    d = fc.driver
    d.type = "SCRIPTED"
    for vname, id_type, id_, dpath in variables:
        v = d.variables.new()
        v.name = vname
        v.type = "SINGLE_PROP"
        v.targets[0].id_type = id_type
        v.targets[0].id = id_
        v.targets[0].data_path = dpath
    d.expression = expr
    return fc


def show(ob, windows, scale=1.0, pop=True, in_frames=5, out_frames=4):
    """Visible only inside the given (t0, t1) windows; pop-in / shrink-out via scale."""
    s = scale if isinstance(scale, (tuple, list)) else (scale, scale, scale)
    zero = (0.0, 0.0, 0.0)
    ob.scale = zero
    ob.keyframe_insert("scale", frame=0)
    for t0, t1 in windows:
        f0, f1 = F(t0), F(t1)
        fin = min(in_frames, max(1, (f1 - f0) // 3))
        fout = min(out_frames, max(1, (f1 - f0) // 3))
        ob.scale = zero
        ob.keyframe_insert("scale", frame=f0 - 1)
        if pop and fin >= 3:
            ob.scale = tuple(c * 1.12 for c in s)
            ob.keyframe_insert("scale", frame=f0 + fin - 2)
        ob.scale = s
        ob.keyframe_insert("scale", frame=f0 + fin)
        ob.scale = s
        ob.keyframe_insert("scale", frame=f1 - fout)
        ob.scale = zero
        ob.keyframe_insert("scale", frame=f1)


# --------------------------------------------------------------------------
# text
# --------------------------------------------------------------------------
_fonts = {}


def font(file):
    """A Windows font by file name, or a path to any font file."""
    if file not in _fonts:
        path = file if ("/" in file or "\\" in file) else FONT_DIR + file
        _fonts[file] = bpy.data.fonts.load(path, check_existing=True)
    return _fonts[file]


def wrap(text, maxc):
    """Greedy word wrap; parentheticals start a new row when the line is long."""
    if len(text) > maxc:
        text = re.sub(r"\s+\(", "\n(", text)
    rows = []
    for para in text.split("\n"):
        row = ""
        for w in para.split():
            if row and len(row) + 1 + len(w) > maxc:
                rows.append(row)
                row = w
            else:
                row = f"{row} {w}" if row else w
        rows.append(row)
    return "\n".join(rows)


def text(name, body, collection, size, mats, fontfile="segoeuib.ttf", align="CENTER", valign="CENTER",
         parent=None, loc=(0, 0, 0), rot=(0, 0, 0), extrude=0.0, accent_parens=False, spacing=1.0,
         hud=True):
    cu = bpy.data.curves.new(name, "FONT")
    cu.body = body
    cu.font = font(fontfile)
    cu.font_bold = font("seguisym.ttf")  # symbol fallback, toggled per character
    cu.size = size
    cu.align_x = align
    cu.align_y = valign
    cu.space_line = spacing
    cu.extrude = extrude
    ob = bpy.data.objects.new(name, cu)
    ob.location = loc
    ob.rotation_euler = rot
    if parent:
        ob.parent = parent
    link(ob, collection)
    for m in mats:
        cu.materials.append(m)
    depth = 0
    for i, ch in enumerate(body):
        if ch == "(":
            depth += 1
        fmt = cu.body_format[i]
        if accent_parens and len(mats) > 1:
            fmt.material_index = 1 if depth > 0 else 0
        if ch in SYMBOLS:
            fmt.use_bold = True
        if ch == ")":
            depth = max(0, depth - 1)
    if hud:
        no_shadow(ob)
    return ob


# --------------------------------------------------------------------------
# camera-locked HUD
# --------------------------------------------------------------------------
class HUD:
    """A plane of overlay objects that stays glued to the camera at any focal length.

    Coordinates: u, v in [-1, 1] across the visible frame.
    """

    def __init__(self, cam, collection, res_x, res_y):
        self.c = collection
        self.root = empty("HUD_root", collection, parent=cam, size=0.05)
        self.root.location = (0, 0, -1)
        drive(self.root, "location", "-lens/35", [("lens", "CAMERA", cam.data, "lens")], index=2)
        half = 18 / 35  # sensor 36mm, AUTO fit, at depth lens/35
        if res_x >= res_y:
            self.HW, self.HH = half, half * res_y / res_x
        else:
            self.HH, self.HW = half, half * res_x / res_y
        self.short = min(res_x, res_y)
        self.landscape = res_x >= res_y

    def p(self, u, v, z=0.0):
        return (u * self.HW, v * self.HH, z)

    def px(self, n):
        """Size in 'pixels' relative to a 1080px short side."""
        return n * 2 * min(self.HW, self.HH) / 1080

    def text(self, name, body, size_px, mats, u=0, v=0, z=0.01, **kw):
        return text(name, body, self.c, self.px(size_px), mats, parent=self.root, loc=self.p(u, v, z), **kw)

    def plane(self, name, w_px, h_px, mat, u=0, v=0, z=0.0, radius_px=0):
        if radius_px:
            ob = link(bpy.data.objects.new(name, rounded_rect_mesh(name, self.px(w_px), self.px(h_px),
                                                                   self.px(radius_px))), self.c)
            ob.parent = self.root
            ob.location = self.p(u, v, z)
        else:
            ob = plane(name, self.px(w_px), self.px(h_px), self.c, parent=self.root, loc=self.p(u, v, z))
        ob.data.materials.append(mat)
        return no_shadow(ob)

    def fullscreen(self, name, mat, z):
        ob = plane(name, 2 * self.HW * 1.02, 2 * self.HH * 1.02, self.c, parent=self.root, loc=(0, 0, z))
        ob.data.materials.append(mat)
        return no_shadow(ob)

    def polyline(self, name, pts_uv, mat, width_px=4, z=0.012):
        """Polyline in HUD space; returns curve object (animate bevel_factor_end to draw it)."""
        cu = bpy.data.curves.new(name, "CURVE")
        cu.dimensions = "3D"
        sp = cu.splines.new("POLY")
        sp.points.add(len(pts_uv) - 1)
        for p, (u, v) in zip(sp.points, pts_uv):
            x, y, _ = self.p(u, v)
            p.co = (x, y, 0, 1)
        cu.bevel_depth = self.px(width_px) / 2
        cu.bevel_resolution = 1
        cu.bevel_factor_mapping_end = "SPLINE"
        cu.materials.append(mat)
        ob = bpy.data.objects.new(name, cu)
        ob.parent = self.root
        ob.location = (0, 0, z)
        link(ob, self.c)
        return no_shadow(ob)


# --------------------------------------------------------------------------
# geometry-nodes text that changes over time:
#   counter: "PREFIX <value> SUFFIX", value ramps V0 -> V1 between T0 and T1
#   typer:   String revealed one character at a time from T0 at CPS chars/s
# --------------------------------------------------------------------------
def _menu(sock_, *vals):
    for val in vals:
        try:
            sock_.default_value = val
            return
        except Exception:
            pass


def _string_group(kind, align, fontfile):
    name = f"{kind}_{align}_{fontfile.split('.')[0]}"
    ng = bpy.data.node_groups.get(name)
    if ng:
        return ng
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    ifc = ng.interface
    ifc.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    if kind == "counter":
        spec = [("Prefix", "NodeSocketString"), ("Suffix", "NodeSocketString"), ("V0", "NodeSocketFloat"),
                ("V1", "NodeSocketFloat"), ("T0", "NodeSocketFloat"), ("T1", "NodeSocketFloat")]
    else:
        spec = [("String", "NodeSocketString"), ("T0", "NodeSocketFloat"), ("CPS", "NodeSocketFloat")]
    for nm, st in spec + [("Size", "NodeSocketFloat"), ("Material", "NodeSocketMaterial")]:
        ifc.new_socket(nm, in_out="INPUT", socket_type=st)
    N, L = ng.nodes, ng.links
    gi = N.new("NodeGroupInput")
    go = N.new("NodeGroupOutput")
    st = N.new("GeometryNodeInputSceneTime")
    if kind == "counter":
        mr = N.new("ShaderNodeMapRange")
        mr.clamp = True
        L.new(st.outputs["Seconds"], mr.inputs[0])
        for i, s in enumerate(["T0", "T1", "V0", "V1"], start=1):
            L.new(gi.outputs[s], mr.inputs[i])
        fl = N.new("ShaderNodeMath")
        fl.operation = "FLOOR"
        L.new(mr.outputs[0], fl.inputs[0])
        vs = N.new("FunctionNodeValueToString")
        L.new(fl.outputs[0], vs.inputs["Value"])
        j = N.new("GeometryNodeStringJoin")
        # multi-input sockets list the newest link first
        for s in (gi.outputs["Suffix"], vs.outputs["String"], gi.outputs["Prefix"]):
            L.new(s, j.inputs["Strings"])
        string_out = j.outputs["String"]
    else:
        sub = N.new("ShaderNodeMath")
        sub.operation = "SUBTRACT"
        L.new(st.outputs["Seconds"], sub.inputs[0])
        L.new(gi.outputs["T0"], sub.inputs[1])
        mul = N.new("ShaderNodeMath")
        mul.operation = "MULTIPLY"
        mul.use_clamp = False
        L.new(sub.outputs[0], mul.inputs[0])
        L.new(gi.outputs["CPS"], mul.inputs[1])
        mx = N.new("ShaderNodeMath")
        mx.operation = "MAXIMUM"
        L.new(mul.outputs[0], mx.inputs[0])
        mx.inputs[1].default_value = 0.0
        sl = N.new("FunctionNodeSliceString")
        L.new(gi.outputs["String"], sl.inputs["String"])
        sl.inputs["Position"].default_value = 0
        L.new(mx.outputs[0], sl.inputs["Length"])
        string_out = sl.outputs["String"]
    s2c = N.new("GeometryNodeStringToCurves")
    s2c.inputs["Font"].default_value = font(fontfile)
    _menu(s2c.inputs["Align X"], align.capitalize(), align.upper())
    _menu(s2c.inputs["Align Y"], "Middle", "MIDDLE")
    L.new(string_out, s2c.inputs["String"])
    L.new(gi.outputs["Size"], s2c.inputs["Size"])
    ri = N.new("GeometryNodeRealizeInstances")
    L.new(s2c.outputs["Curve Instances"], ri.inputs["Geometry"])
    fc = N.new("GeometryNodeFillCurve")
    L.new(ri.outputs[0], fc.inputs["Curve"])
    sm = N.new("GeometryNodeSetMaterial")
    L.new(fc.outputs[0], sm.inputs["Geometry"])
    L.new(gi.outputs["Material"], sm.inputs["Material"])
    L.new(sm.outputs[0], go.inputs["Geometry"])
    return ng


def _string_obj(name, hud, ng, vals, u, v, z):
    ob = bpy.data.objects.new(name, bpy.data.meshes.new(name))
    ob.parent = hud.root
    ob.location = hud.p(u, v, z)
    link(ob, hud.c)
    mod = ob.modifiers.new("Text", "NODES")
    mod.node_group = ng
    for item in ng.interface.items_tree:
        if getattr(item, "in_out", None) == "INPUT" and item.name in vals:
            if hasattr(mod, "properties"):  # Blender 5.2+
                getattr(mod.properties.inputs, item.identifier).value = vals[item.name]
            else:
                mod[item.identifier] = vals[item.name]
    return no_shadow(ob)


def counter(name, hud, prefix, suffix, v0, v1, t0, t1, size_px, mat, u, v, z=0.012, align="center",
            fontfile="bahnschrift.ttf"):
    ng = _string_group("counter", align, fontfile)
    vals = {"Prefix": prefix, "Suffix": suffix, "V0": float(v0), "V1": float(v1), "T0": float(t0),
            "T1": float(t1), "Size": hud.px(size_px), "Material": mat}
    return _string_obj(name, hud, ng, vals, u, v, z)


def typer(name, hud, string, t0, cps, size_px, mat, u, v, z=0.012, align="left", fontfile="consola.ttf"):
    ng = _string_group("typer", align, fontfile)
    vals = {"String": string, "T0": float(t0), "CPS": float(cps), "Size": hud.px(size_px), "Material": mat}
    return _string_obj(name, hud, ng, vals, u, v, z)


# --------------------------------------------------------------------------
# geometry
# --------------------------------------------------------------------------
def d_profile(R0, a, kappa, delta, n=64):
    """Tokamak 'D' cross-section in the (R, Z) plane."""
    pts = []
    for i in range(n):
        th = 2 * math.pi * i / n
        pts.append((R0 + a * math.cos(th + delta * math.sin(th)), kappa * a * math.sin(th)))
    return pts


def spin(name, prof, collection, segs=96, start=0.0, angle=2 * math.pi, parent=None):
    full = abs(angle - 2 * math.pi) < 1e-6
    nring = segs if full else segs + 1
    n = len(prof)
    verts, faces, uvs = [], [], []
    for j in range(nring):
        ph = start + angle * j / segs
        c, s = math.cos(ph), math.sin(ph)
        for R, Z in prof:
            verts.append((R * c, R * s, Z))
    for j in range(segs):
        j2 = (j + 1) % nring if full else j + 1
        for i in range(n):
            i2 = (i + 1) % n
            faces.append((j * n + i, j2 * n + i, j2 * n + i2, j * n + i2))
            uvs.append([(j / segs, i / n), ((j + 1) / segs, i / n), ((j + 1) / segs, (i + 1) / n),
                        (j / segs, (i + 1) / n)])
    ob = mesh_obj(name, verts, faces, collection, parent=parent)
    uv = ob.data.uv_layers.new(name="UVMap")
    k = 0
    for poly, quad in zip(ob.data.polygons, uvs):
        for li, c in zip(poly.loop_indices, quad):
            uv.data[li].uv = c
            k += 1
    return ob
