"""Splice the sung last line from an earlier Suno render onto the end of the current one.

The latest render stops before "And I'll know by lunch."; the first render sings it
(quietly, after the music drops out). This writes video/song_mix.wav plus
video/song_mix.json with where the phrase lands, which build_scene.py and render.py use.

Usage: python video/mix_ending.py ["Thirty Years Away.wav"] [clip_start clip_end]
"""
import json
import sys
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OLD = HERE.parent / (sys.argv[1] if len(sys.argv) > 1 else "Thirty Years Away.wav")
CLIP_A, CLIP_B = (float(sys.argv[2]), float(sys.argv[3])) if len(sys.argv) > 3 else (327.55, 328.88)
VOCAL_A, VOCAL_B = CLIP_A + 0.13, CLIP_B  # the phrase itself; the clip ends right after "lunch"
FADE_OUT, OVERLAP = 0.25, 0.12

src = Path((HERE / "audio_source.txt").read_text().strip())
NEW = src.with_suffix(".wav")


def load(p):
    with wave.open(str(p), "rb") as w:
        sr, ch = w.getframerate(), w.getnchannels()
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, ch).astype(np.float32)
    return sr, x


sr, new = load(NEW)
sr_o, old = load(OLD)
assert sr == sr_o and new.shape[1] == old.shape[1], "sample rate / channel mismatch"

new = new.copy()
n_f = int(FADE_OUT * sr)
new[-n_f:] *= np.linspace(1, 0, n_f)[:, None]

clip = old[int(CLIP_A * sr):int(CLIP_B * sr)].copy()
n_in, n_out = int(0.02 * sr), int(0.04 * sr)  # short fade: no jingle after the words
clip[:n_in] *= np.linspace(0, 1, n_in)[:, None]
clip[-n_out:] *= np.linspace(1, 0, n_out)[:, None]

place = len(new) / sr - OVERLAP
start = int(place * sr)
out = np.zeros((max(len(new), start + len(clip)), new.shape[1]), np.float32)
out[:len(new)] += new
out[start:start + len(clip)] += clip
out = np.clip(out, -32768, 32767).astype(np.int16)

dst = HERE / "song_mix.wav"
with wave.open(str(dst), "wb") as w:
    w.setnchannels(out.shape[1])
    w.setsampwidth(2)
    w.setframerate(sr)
    w.writeframes(out.tobytes())
with wave.open(str(HERE / "last_line_clip.wav"), "wb") as w:  # for a quick listen
    w.setnchannels(clip.shape[1])
    w.setsampwidth(2)
    w.setframerate(sr)
    w.writeframes(clip.astype(np.int16).tobytes())

meta = {"source": NEW.name, "donor": OLD.name, "clip": [CLIP_A, CLIP_B], "placed_at": round(place, 3),
        "lunch_t0": round(place + (VOCAL_A - CLIP_A), 3), "lunch_t1": round(place + (VOCAL_B - CLIP_A), 3),
        "duration": round(len(out) / sr, 3)}
(HERE / "song_mix.json").write_text(json.dumps(meta, indent=1))
print(meta)
