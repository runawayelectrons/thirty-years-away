"""Render the music video in resumable chunks, then join them and mux the song.

    python video/render.py --preview          # 960x540 quick pass  -> video/out/..._preview.mp4
    python video/render.py                    # 1920x1080 final     -> video/out/....mp4
    options: --workers N (parallel Blender processes), --chunk FRAMES, --vertical

Finished chunks are kept, so an interrupted render picks up where it stopped.
Delete video/render/<tag>/ after rebuilding the scene to force a full re-render.
"""
import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
BLENDER = os.environ.get("BLENDER", r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe")

ap = argparse.ArgumentParser()
ap.add_argument("--preview", action="store_true")
ap.add_argument("--vertical", action="store_true")
ap.add_argument("--workers", type=int, default=2)
ap.add_argument("--chunk", type=int, default=300)
ap.add_argument("--samples", type=int, default=None, help="EEVEE samples (default 16 preview, 16 final)")
args = ap.parse_args()

blend = HERE / ("thirty_years_away_vertical.blend" if args.vertical else "thirty_years_away.blend")
tag = ("vertical_" if args.vertical else "") + ("preview" if args.preview else "final")
pct, samples = (50, 16) if args.preview else (100, 16)
samples = args.samples or samples
chunk_dir = HERE / "render" / tag
chunk_dir.mkdir(parents=True, exist_ok=True)
out_dir = HERE / "out"
out_dir.mkdir(exist_ok=True)

SETUP = """
import bpy, os
sc = bpy.context.scene
sc.render.resolution_percentage = int(os.environ["R_PCT"])
sc.eevee.taa_render_samples = int(os.environ["R_SAMPLES"])
im = sc.render.image_settings
if hasattr(im, "media_type"):
    im.media_type = "VIDEO"
im.file_format = "FFMPEG"
ff = sc.render.ffmpeg
ff.format = "MPEG4"
ff.codec = "H264"
ff.constant_rate_factor = "HIGH"
ff.ffmpeg_preset = "GOOD"
ff.gopsize = 30
ff.audio_codec = "NONE"
sc.render.filepath = os.environ["R_OUT"]
"""
setup_py = chunk_dir / "_setup.py"
setup_py.write_text(SETUP)

frames = subprocess.run([BLENDER, "-b", str(blend), "--python-expr",
                         "import bpy; s=bpy.context.scene; print('RANGE', s.frame_start, s.frame_end)"],
                        capture_output=True, text=True).stdout
f0, f1 = map(int, next(l for l in frames.splitlines() if l.startswith("RANGE")).split()[1:])
chunks = [(s, min(s + args.chunk - 1, f1)) for s in range(f0, f1 + 1, args.chunk)]


def final_name(s, e):
    return chunk_dir / f"chunk_{s:05d}_{e:05d}.mp4"


def render(c):
    s, e = c
    dst = final_name(s, e)
    if dst.exists() and dst.stat().st_size > 0:
        return f"skip {s}-{e}"
    tmp_prefix = chunk_dir / f"tmp_{s:05d}_"
    env = dict(os.environ, R_PCT=str(pct), R_SAMPLES=str(samples), R_OUT=str(tmp_prefix))
    r = subprocess.run([BLENDER, "-b", str(blend), "-P", str(setup_py), "-s", str(s), "-e", str(e), "-a"],
                       env=env, capture_output=True, text=True)
    made = sorted(chunk_dir.glob(f"tmp_{s:05d}_*"))
    if r.returncode != 0 or not made:
        return f"FAILED {s}-{e}\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}"
    made[-1].replace(dst)
    return f"done {s}-{e}"


print(f"{tag}: frames {f0}-{f1} in {len(chunks)} chunks, {args.workers} workers", flush=True)
with ThreadPoolExecutor(args.workers) as ex:
    for i, msg in enumerate(ex.map(render, chunks), 1):
        print(f"[{i}/{len(chunks)}] {msg}", flush=True)
        if msg.startswith("FAILED"):
            sys.exit(1)

lst = chunk_dir / "_list.txt"
lst.write_text("".join(f"file '{final_name(s, e).as_posix()}'\n" for s, e in chunks))
video_only = chunk_dir / "_video_only.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
                str(video_only)], check=True)

src = Path((HERE / "audio_source.txt").read_text().strip())
song = next((p for p in (src.with_suffix(".wav"), src) if p.exists()), src)
mix_meta = HERE / "song_mix.json"
if mix_meta.exists() and json.loads(mix_meta.read_text()).get("source") == src.with_suffix(".wav").name:
    song = HERE / "song_mix.wav"  # current render + the sung last line (see mix_ending.py)
print("audio:", song.name)
name = "Thirty Years Away - music video" + (" (vertical)" if args.vertical else "") + \
       (" (preview)" if args.preview else "") + ".mp4"
final = out_dir / name
# apad: the video runs a few seconds past the music for the unsung last line + end card
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video_only), "-i", str(song), "-map", "0:v", "-map", "1:a",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "320k", "-af", "apad", "-shortest",
                "-movflags", "+faststart", str(final)], check=True)
print("wrote", final)
