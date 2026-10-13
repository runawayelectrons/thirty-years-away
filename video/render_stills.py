"""Render preview stills at given song times (seconds).

blender -b video/thirty_years_away.blend -P video/render_stills.py -- OUTDIR [--pct 50] [--samples 16] t1 t2 ...
"""
import sys
import time
from pathlib import Path

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
out = Path(argv.pop(0))
out.mkdir(parents=True, exist_ok=True)
sc = bpy.context.scene
sc.render.resolution_percentage = 50
sc.eevee.taa_render_samples = 16
while argv and argv[0].startswith("--"):
    flag, val = argv.pop(0), argv.pop(0)
    if flag == "--pct":
        sc.render.resolution_percentage = int(val)
    elif flag == "--samples":
        sc.eevee.taa_render_samples = int(val)
sc.render.image_settings.file_format = "JPEG"
sc.render.image_settings.quality = 88
fps = sc.render.fps
for t in argv:
    f = int(round(float(t) * fps)) + 1
    sc.frame_set(f)
    sc.render.filepath = str(out / f"t{float(t):06.1f}.jpg")
    t0 = time.time()
    bpy.ops.render.render(write_still=True)
    print(f"rendered t={t} frame={f} in {time.time() - t0:.1f}s")
