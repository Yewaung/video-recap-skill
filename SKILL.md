---
name: video-recap
description: >-
  Convert short-form or TikTok videos into Myanmar-dubbed, Myanmar-subtitled recap
  videos with scene-synced voiceover, frosted caption masking, SRT subtitles, and
  QA checks. Use whenever the user asks for a video recap, Myanmar dubbing/version
  of a video, batch recap folder processing, or choosing male/female Myanmar voice.
---

# Myanmar Video Recap

## Overview

End-to-end production pipeline that inspects source videos, prompts per run for input/output folders and voice/caption preferences, builds scene-locked Myanmar narration scripts, synthesizes rate-limited neural TTS, fits clips to visual cuts with zero overlap, renders `libass`-shaped Burmese subtitles, and verifies audio/visual quality.

## Dependencies

- **System tools**: `uv`, `ffmpeg`, `ffprobe` (built with `libass` + `harfbuzz`), and a Myanmar Unicode font (`Myanmar Text` on Windows, `Myanmar MN`/`Padauk` on macOS, `Noto Sans Myanmar`/`Padauk` on Linux, or set `MYANMAR_FONT_DIR`).
- **`gemini-tts` (optional)**: Use an installed `gemini-tts` skill instead of Edge TTS only when the user explicitly requests Gemini TTS and `GEMINI_API_KEY` is configured. Default to Edge Neural TTS (`edge-tts` inside this skill's `uv` project), which requires no API key.
- **References**:
  - [Script Template](references/script-template.json)
  - [Burmese Pacing & Style Guide](references/burmese-pacing-guide.md)

## Mandatory Interactive Intake (Ask Every Run)

Before scanning or rendering, ask the user for all four run settings:

1. **Input & Output Folders** — Input video file or folder path (default `./input`, single video or batch folder) and output base folder (default `./output`).
2. **Voice Selection** —
   - Woman (`woman` -> `my-MM-NilarNeural`, Edge Neural, free)
   - Man (`man` -> `my-MM-ThihaNeural`, Edge Neural, free)
   - `gemini-tts` (optional, requires `GEMINI_API_KEY`)
3. **Narration POV** —
   - 1st-person storytelling (`first_person`)
   - 3rd-person movie recap narrator (`third_person`)
4. **Caption Mode** —
   - `frosted-mask`: Blurred dark translucent band over source English captions + burned-in Myanmar subtitles
   - `clean-burn`: Burned-in Myanmar subtitles directly over clean video (no mask band)
   - `srt-only`: Lossless video copy (`-c:v copy`) + Myanmar voiceover + external `.srt` only

## Quick Start

Let `<skill-dir>` be this skill's directory (for example `~/.gemini/config/skills/video-recap`):

```sh
uv sync --project "<skill-dir>"
uv run --project "<skill-dir>" recap scan --input "<input_folder_or_file>" --output "<build>/scan.json"
```

Users can also launch the interactive terminal runner directly:

```sh
uv run --project "<skill-dir>" recap wizard
```

## Utility Scripts

All CLI commands write structured JSON reports to `--output` (keeping stdout concise).

| Subcommand | Purpose | Key Flags |
|---|---|---|
| `scan` | Discover and probe 1 video or all videos in a folder | `--input`, `--output` |
| `ruler` | Extract 20px pixel-grid PNGs to locate existing captions | `--input`, `--output-dir`, `--output`, `--timestamps` |
| `measure` | Dry-run TTS across all segments and report slot fit/overflows | `--script`, `--output`, `--input-video`, `--voice`, `--rate`, `--build-dir` |
| `render` | Synthesize audio, fit timings, build `.srt`/`.ass`/`_script.md`, render `_mm.mp4` | `--script`, `--output-dir`, `--output`, `--input-video`, `--voice`, `--rate`, `--caption-mode`, `--band-y`, `--band-h`, `--build-dir` |
| `verify` | Check codecs/duration/loudness (`volumedetect`) and extract 5 QA PNGs + audio clip | `--video`, `--qa-dir`, `--output`, `--source-video` |
| `wizard` | Interactive prompt flow for direct terminal runs | — |

## End-to-End Agent Workflow

Follow this sequence for each selected video (or loop sequentially for batch folders):

1. **Collect Run Inputs**: Ask for input folder/video, output folder, voice (`woman`/`man`), POV, and caption mode.
2. **Scan Input**: Run `scan --input <path> --output <build>/scan.json` and read the JSON manifest. If multiple videos are found, confirm whether to process all or a subset.
3. **Inspect Video & Measure Caption Bounds**:
   - Inspect the source video (`read_file`) to map scene cuts, pacing, and dialogue.
   - If `caption_mode == "frosted-mask"`, run `ruler` and inspect the ruler PNGs (`read_file`) to measure exact `band_y` and `band_h` pixels covering source captions without covering actor faces.
4. **Author Scene-Locked Script JSON**:
   - Write `<script>.json` matching [script-template.json](references/script-template.json) and character budgets in [burmese-pacing-guide.md](references/burmese-pacing-guide.md).
5. **Dry-Run Duration Fit (`measure`)**:
   - Run `measure` first and inspect `<build>/measure.json`. If any segment has `would_fit: false` or `ratio > 1.22`, tighten its Burmese phrasing before rendering.
6. **Render Final Outputs (`render`)**:
   - Run `render` targeting `<output-dir>`. Outputs `<stem>_mm.mp4`, `<stem>_mm.srt`, and `<stem>_mm_script.md`.
7. **Automated & Visual QA (`verify`)**:
   - Run `verify` and read `<build>/verify.json`.
   - Call `read_file` on **all 5 extracted QA PNG frames** and `sample_audio.mp3` to confirm:
     - Proper Myanmar HarfBuzz shaping (`ေ` before consonant, `ြ` wrap, no tofu boxes/dotted circles).
     - Complete masking of any burned-in source captions (zero bleed) and `<= 2` lines inside the band.
     - Crisp Burmese voiceover (`mean_volume_db` near `-14` to `-18 dB`, `max_volume_db <= -0.5 dB`, zero clipping).

## Rate Limiting

- Edge TTS calls are paced inside `tts_adapter.py` using `time.monotonic()` (`min_interval_sec = 0.35`, concurrency cap `3`) with exponential backoff (`1.5s`, `3.0s`) on transient errors and SHA-256 `(voice, rate, text)` caching to prevent redundant requests.

## Rights & Usage Notice

- Only process videos you own, have a license/affiliate agreement for, or are producing transformative original commentary/review over. Avoid adding visual/audio evasion filters; rely on original Burmese commentary, licensed/royalty-free audio, and clean attribution.

## Common Mistakes

- **Never use FFmpeg `drawtext` for Myanmar**: `drawtext` breaks Burmese vowel/medial reordering. Always render via `libass` (`ass` filter).
- **Never skip `ruler` inspection before `frosted-mask` rendering**: Source TikTok captions often sit higher (`~70%` height) than letterbox bars (`~90%`). Measure exact pixel coordinates first.
- **Never assume system locale encoding on Windows**: Always specify `encoding="utf-8"` (or `utf-8-sig` for `.srt`) in custom scripts handling Myanmar text.
