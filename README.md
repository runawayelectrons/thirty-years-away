# Thirty Years Away

A synth-pop song about fusion energy, which has been thirty years away since 1958.
Song made with Suno; the music video is written as code by Claude Opus 5.5 and rendered in Blender.

This repo has everything needed to remix it: stems, the final mix, a karaoke and an
instrumental version, the lyrics, and the full video pipeline.

- Video: [youtube.com/@runawayelectrons](https://www.youtube.com/@runawayelectrons)
- Audio and video files: on the [Releases page](../../releases/latest) (too big for git)

## Downloads (Releases)

| File | What it is |
|---|---|
| `thirty-years-away_stems_48k-wav.zip` | 10 stems, 48 kHz / 16-bit WAV, all 336.36 s and aligned at 0:00 |
| `thirty-years-away_final-mix.wav` / `.mp3` | The released mix (what's in the video) |
| `thirty-years-away_karaoke.wav` / `.mp3` | Everything except the lead vocal (backing vocals kept) |
| `thirty-years-away_instrumental.wav` / `.mp3` | No vocals at all |
| `thirty-years-away_suno-take-b_raw.wav` | The raw Suno render the stems come from |
| `thirty-years-away_music-video_1080p.mp4` | The music video |
| `thirty-years-away_karaoke-video_1080p.mp4` | The music video with the karaoke track; the on-screen lyrics are the guide |

Stems: Lead Vocals, Backing Vocals, Drums, Bass, Guitar, Keyboard, Percussion, Synth, Other, Brass.

Things worth knowing before you remix:

- **Tempo:** about 126 BPM (measured). Beat grid in
  [`video/audio_features.json`](video/audio_features.json) (`bpm`, `beat_phase`, `beats`).
- **The stems don't null against the mix.** Suno generates each stem rather than cutting
  them out of the mix, so they're individually normalized and won't cancel the original
  exactly. Summing them at unity gain gets you close (about +2 dB hotter, so leave headroom).
  The karaoke and instrumental files are stem sums, loudness-matched and peak-limited.
- **The last line is a splice.** The Suno render used for the release stops before the
  final spoken line ("And I'll know by lunch."), so the final mix pastes 1.33 s of an
  alternate take in at 336.24 s (see [`video/mix_ending.py`](video/mix_ending.py) and
  [`video/song_mix.json`](video/song_mix.json)). That line isn't in the stems.

## Lyrics

[`lyrics/lyrics.txt`](lyrics/lyrics.txt) is the released lyric sheet, with Suno's section and
delivery tags. [`video/lyrics_timed.srt`](video/lyrics_timed.srt) is the line-by-line timing for the
release, which is also what the video syncs to.

## Rebuilding the video

Everything in the video (camera cuts, gags, captions) is anchored to the timed lyrics,
so a different render or a remix with the same vocal timing re-syncs automatically.

Needs Blender 5.2, Python 3 with numpy and Pillow, and ffmpeg on the PATH. Some captions
use Windows system fonts (Bahnschrift, Consolas, Impact, Segoe UI); the other fonts are in
[`video/fonts/`](video/fonts/).

```sh
# put the release audio in ./audio/ first
python video/prepare_audio.py audio/thirty-years-away_suno-take-b_raw.wav   # writes audio_source.txt + audio_features.json
cp audio/thirty-years-away_final-mix.wav video/song_mix.wav                 # the mix with the spliced last line
blender -b --factory-startup -P video/build_scene.py                        # -> video/thirty_years_away.blend
python video/render.py --preview                                            # 960x540; drop --preview for 1080p
```

`render.py` renders in resumable chunks with several Blender workers (set `BLENDER=` if it
isn't at the default Windows install path). The channel art comes from `make_youtube_art.py`,
`make_thumbnail.py` (`--karaoke` adds the badge) and `make_avatar_logo.py`.

## Credits

- Song: made with Suno
- Animation: Claude Opus 5.5, in Python and Blender
- Direction: Runaway Electrons
- Peer reviewed by: Reviewer 2 (please address the neutrons)

## License

The song, lyrics, stems, artwork and video are [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/):
remix them, use them, sell your remix, just credit **Runaway Electrons**. The code is MIT,
and the bundled fonts are under the SIL Open Font License. Details in [LICENSE.md](LICENSE.md).
