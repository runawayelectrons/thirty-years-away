"""Channel avatar: a neon plasma ring with one runaway electron escaping.

blender -b --factory-startup -P video/make_avatar.py      -> video/out/youtube_avatar.png (800x800)
"""
import math
import sys
from pathlib import Path

import bpy

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lib  # noqa: E402

MAGENTA, VIOLET, CYAN = (1.0, 0.18, 0.75), (0.45, 0.18, 1.0), (0.1, 0.8, 1.0)

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = "BLENDER_EEVEE"
sc.render.resolution_x = sc.render.resolution_y = 800
sc.render.filter_size = 1.0
sc.eevee.taa_render_samples = 64
sc.view_settings.view_transform = "Khronos PBR Neutral"
C = sc.collection

world = bpy.data.worlds.new("W")
sc.world = world
if world.node_tree is None:
    world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.002, 0.003, 0.01, 1)

# backdrop: soft violet glow behind the ring
bd = lib.plane("Backdrop", 30, 30, C, loc=(0, 6, 0))
bd.rotation_euler = (math.radians(90), 0, 0)
m, nt, out = lib.new_mat("Backdrop")
tc = nt.nodes.new("ShaderNodeTexCoord")
vm = nt.nodes.new("ShaderNodeVectorMath")
vm.operation = "DISTANCE"
nt.links.new(tc.outputs["UV"], vm.inputs[0])
vm.inputs[1].default_value = (0.5, 0.52, 0)
mr = nt.nodes.new("ShaderNodeMapRange")
nt.links.new(vm.outputs["Value"], mr.inputs[0])
mr.inputs[1].default_value, mr.inputs[2].default_value = 0.0, 0.2
mr.inputs[3].default_value, mr.inputs[4].default_value = 0.1, 0.0
em = nt.nodes.new("ShaderNodeEmission")
em.inputs["Color"].default_value = (*VIOLET, 1)
nt.links.new(mr.outputs[0], em.inputs["Strength"])
nt.links.new(em.outputs[0], out.inputs["Surface"])
bd.data.materials.append(m)

# plasma ring: colour runs magenta -> violet -> cyan around the torus, edges glow
ring = lib.spin("Plasma", lib.d_profile(1.0, 0.3, 1.5, 0.3, 64), C, segs=192)
m, nt, out = lib.new_mat("Plasma", blended=True)
tc = nt.nodes.new("ShaderNodeTexCoord")
gr = nt.nodes.new("ShaderNodeTexGradient")
gr.gradient_type = "RADIAL"
nt.links.new(tc.outputs["Object"], gr.inputs["Vector"])
cr = nt.nodes.new("ShaderNodeValToRGB")
els = cr.color_ramp.elements
els[0].position, els[0].color = 0.0, (*MAGENTA, 1)
els[1].position, els[1].color = 1.0, (*MAGENTA, 1)
e = els.new(0.35)
e.color = (*VIOLET, 1)
e = els.new(0.68)
e.color = (*CYAN, 1)
nt.links.new(gr.outputs["Fac"], cr.inputs["Fac"])
lw = nt.nodes.new("ShaderNodeLayerWeight")
lw.inputs["Blend"].default_value = 0.5
strength = lib.math_(nt, "ADD", 0.35, lib.math_(nt, "MULTIPLY", lib.math_(nt, "POWER", lw.outputs["Facing"], 2.5), 2.6))
em = nt.nodes.new("ShaderNodeEmission")
nt.links.new(cr.outputs["Color"], em.inputs["Color"])
nt.links.new(strength, em.inputs["Strength"])
tr = nt.nodes.new("ShaderNodeBsdfTransparent")
add = nt.nodes.new("ShaderNodeAddShader")
nt.links.new(tr.outputs[0], add.inputs[0])
nt.links.new(em.outputs[0], add.inputs[1])
nt.links.new(add.outputs[0], out.inputs["Surface"])
ring.data.materials.append(m)

# thin dark coils so it reads as a tokamak, not a donut
m_coil, nt, p = lib.principled("Coil", (0.06, 0.06, 0.08), metallic=0.9, roughness=0.3)
p.inputs["Emission Color"].default_value = (*CYAN, 1)
p.inputs["Emission Strength"].default_value = 0.08
prof = lib.d_profile(1.0, 0.52, 1.35, 0.4, 64)
for k in range(10):
    phi = 2 * math.pi * k / 10 + 0.13
    cu = bpy.data.curves.new(f"TF{k}", "CURVE")
    cu.dimensions = "3D"
    sp = cu.splines.new("POLY")
    sp.points.add(len(prof) - 1)
    for pt, (R, Z) in zip(sp.points, prof):
        pt.co = (R * math.cos(phi), R * math.sin(phi), Z, 1)
    sp.use_cyclic_u = True
    cu.bevel_depth = 0.02
    cu.bevel_resolution = 2
    cu.materials.append(m_coil)
    lib.link(bpy.data.objects.new(f"TF{k}", cu), C)

# the runaway electron: bright head, tapered streak spiralling out of the ring
pts = []
for i in range(40):
    u = i / 39
    a = math.radians(-70 + 95 * u)
    r = 1.15 + 1.25 * u ** 1.6
    pts.append((r * math.cos(a), r * math.sin(a), 0.05 + 1.15 * u ** 1.3, 0.15 + 0.85 * u ** 2))
cu = bpy.data.curves.new("Streak", "CURVE")
cu.dimensions = "3D"
sp = cu.splines.new("POLY")
sp.points.add(len(pts) - 1)
for pt, (x, y, z, rad) in zip(sp.points, pts):
    pt.co = (x, y, z, 1)
    pt.radius = rad
cu.bevel_depth = 0.055
cu.bevel_resolution = 3
cu.use_fill_caps = True
m, nt, out = lib.new_mat("Streak")
tc = nt.nodes.new("ShaderNodeTexCoord")  # brighter the further it has escaped
vl = nt.nodes.new("ShaderNodeVectorMath")
vl.operation = "LENGTH"
nt.links.new(tc.outputs["Object"], vl.inputs[0])
along = nt.nodes.new("ShaderNodeMapRange")
nt.links.new(vl.outputs["Value"], along.inputs[0])
along.inputs[1].default_value, along.inputs[2].default_value = 1.15, 2.7
em = nt.nodes.new("ShaderNodeEmission")
nt.links.new(lib.mix_rgb(nt, along.outputs[0], CYAN, (0.85, 1.0, 1.0)), em.inputs["Color"])
nt.links.new(lib.math_(nt, "ADD", 1.5, lib.math_(nt, "MULTIPLY", along.outputs[0], 8.0)), em.inputs["Strength"])
nt.links.new(em.outputs[0], out.inputs["Surface"])
cu.materials.append(m)
lib.link(bpy.data.objects.new("Streak", cu), C)
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.12, location=pts[-1][:3])
head = bpy.context.active_object
head.data.materials.append(lib.emission_mat("Head", (0.9, 1.0, 1.0), 40.0, blended=False))
for poly in head.data.polygons:
    poly.use_smooth = True

# camera: three-quarter view from above, ring centred, electron heading up-right
cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
cam.data.lens = 50
cam.location = (0.0, -6.1, 3.25)
c = cam.constraints.new("TRACK_TO")
tgt = lib.empty("Target", C, loc=(0.38, 0.25, 0.55))
c.target = tgt
c.track_axis = "TRACK_NEGATIVE_Z"
c.up_axis = "UP_Y"
lib.link(cam, C)
sc.camera = cam

ng = bpy.data.node_groups.new("Post", "CompositorNodeTree")
ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
rl = ng.nodes.new("CompositorNodeRLayers")
gl = ng.nodes.new("CompositorNodeGlare")
lib._menu(gl.inputs["Type"], "Bloom", "BLOOM")
gl.inputs["Threshold"].default_value = 1.0
gl.inputs["Strength"].default_value = 0.6
go = ng.nodes.new("NodeGroupOutput")
ng.links.new(rl.outputs["Image"], gl.inputs["Image"])
ng.links.new(gl.outputs["Image"], go.inputs[0])
sc.compositing_node_group = ng
sc.render.use_compositing = True

(HERE / "out").mkdir(exist_ok=True)
sc.render.image_settings.file_format = "PNG"
sc.render.filepath = str(HERE / "out" / "youtube_avatar.png")
bpy.ops.render.render(write_still=True)
print("wrote", sc.render.filepath)
