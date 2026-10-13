"""Prepare a Suno render for the video build.

1. Extracts Suno's time-synced lyrics (subtitle track) -> video/lyrics_timed.srt
2. Decodes the audio and writes per-video-frame energy envelopes + tempo
   -> video/audio_features.json

Usage: python video/prepare_audio.py "Thirty Years Away.m4a" [fps]
Re-run this whenever you swap in a new render of the song.
"""
import json
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

src_path = Path(sys.argv[1])
fps = int(sys.argv[2]) if len(sys.argv) > 2 else 30
here = Path(__file__).resolve().parent

srt = here / "lyrics_timed.srt"
r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src_path), "-map", "0:s:0", str(srt)],
                   capture_output=True, text=True)
print("lyrics:", srt.name if r.returncode == 0 else f"no subtitle track in {src_path.name} (kept existing srt)")

wav_path = Path(tempfile.gettempdir()) / "fusion_song_analysis.wav"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src_path), "-vn", "-ac", "2", "-ar", "48000",
                "-c:a", "pcm_s16le", str(wav_path)], check=True)
(here / "audio_source.txt").write_text(src_path.resolve().as_posix())

with wave.open(str(wav_path), "rb") as w:
    sr = w.getframerate()
    ch = w.getnchannels()
    raw = w.readframes(w.getnframes())
x = np.frombuffer(raw, dtype=np.int16).reshape(-1, ch).astype(np.float32).mean(axis=1) / 32768.0
duration = len(x) / sr

# --- per-frame band energies (window centred on each video frame) ---
hop = sr / fps
win = 4096
n_frames = int(np.ceil(duration * fps))
freqs = np.fft.rfftfreq(win, 1 / sr)
bands = {"sub": (20, 120), "low": (120, 400), "mid": (400, 2500), "high": (2500, 12000)}
masks = {k: (freqs >= a) & (freqs < b) for k, (a, b) in bands.items()}
window = np.hanning(win).astype(np.float32)
pad = np.concatenate([np.zeros(win // 2, np.float32), x, np.zeros(win, np.float32)])
out = {k: np.zeros(n_frames, np.float32) for k in bands}
rms = np.zeros(n_frames, np.float32)
for i in range(n_frames):
    s = int(i * hop)
    seg = pad[s : s + win]
    rms[i] = np.sqrt(np.mean(seg ** 2))
    spec = np.abs(np.fft.rfft(seg * window)) ** 2
    for k, m in masks.items():
        out[k][i] = spec[m].sum()

def norm(a):
    a = np.log1p(a / (np.median(a) + 1e-9))
    lo, hi = np.percentile(a, 2), np.percentile(a, 99.5)
    return np.clip((a - lo) / (hi - lo + 1e-9), 0, 1)

feat = {k: norm(v) for k, v in out.items()}
feat["rms"] = np.clip(rms / np.percentile(rms, 99.5), 0, 1)

# --- onset strength from sub+low band (kick) ---
kick = feat["sub"] * 0.7 + feat["low"] * 0.3
onset = np.maximum(0, np.diff(kick, prepend=kick[0]))

# --- tempo + phase search on a fine time grid ---
best = None
t_frames = np.arange(n_frames) / fps
for bpm in np.arange(110.0, 140.0, 0.05):
    period = 60.0 / bpm
    for ph in np.arange(0, period, 1 / (fps * 4)):
        idx = np.round((np.arange(ph, duration, period)) * fps).astype(int)
        idx = idx[idx < n_frames]
        score = onset[idx].mean()
        if best is None or score > best[0]:
            best = (score, bpm, ph)
score, bpm, phase = best
period = 60.0 / bpm
beats = np.arange(phase, duration, period)

# kick "hits": onset peaks above an adaptive threshold
thr = np.convolve(onset, np.ones(fps) / fps, mode="same") * 2.5 + 0.03
peaks = [i for i in range(1, n_frames - 1) if onset[i] > thr[i] and onset[i] >= onset[i - 1] and onset[i] >= onset[i + 1]]

res = {
    "fps": fps,
    "duration": duration,
    "n_frames": n_frames,
    "bpm": round(float(bpm), 3),
    "beat_phase": round(float(phase), 4),
    "beats": [round(float(b), 4) for b in beats],
    "kick_frames": peaks,
    **{k: [round(float(v), 3) for v in a] for k, a in feat.items()},
}
dst = Path(__file__).with_name("audio_features.json")
dst.write_text(json.dumps(res))
print(f"duration={duration:.2f}s frames={n_frames} bpm={bpm:.3f} phase={phase:.3f}s score={score:.3f} kicks={len(peaks)}")
# energy profile per 10 s, to sanity check section boundaries
for s in range(0, int(duration), 10):
    a, b = s * fps, min(n_frames, (s + 10) * fps)
    print(f"{s:4d}s rms={feat['rms'][a:b].mean():.2f} sub={feat['sub'][a:b].mean():.2f} high={feat['high'][a:b].mean():.2f}")
