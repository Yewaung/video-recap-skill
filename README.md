# video-recap-skill

Open-source **Agent Skill + Clean Architecture CLI** for turning short-form / TikTok videos into **Myanmar-dubbed, Myanmar-subtitled recap videos** with scene-synced Edge Neural TTS, Burmese `libass` subtitle shaping, frosted caption masking, timed `.srt` export, and automated audio/visual QA.

---

## Features

- **Agent Skill ready** — Works with Antigravity, Claude Code, Codex, and Gemini CLI (`SKILL.md` + `references/`).
- **Interactive run wizard** — Prompts for `input/` and `output/` folders, `woman` (`my-MM-NilarNeural`) or `man` (`my-MM-ThihaNeural`) Burmese voice, POV, and caption mode.
- **Zero-overlap scene sync** — Trims TTS silence, checks segment durations in a dry-run (`measure`), applies bounded tempo fitting (`<= 1.28x`), and assembles sample-accurate 48 kHz PCM audio mastered to `-14 LUFS`.
- **Proper Burmese Unicode shaping** — Uses `libass` + HarfBuzz (cross-platform font detection for Windows, macOS, and Linux) and splits/wraps subtitles by visual Burmese glyph clusters rather than raw UTF-8 code points.
- **3 Caption Modes** — `frosted-mask` (blurred dark translucent band over source English captions), `clean-burn` (direct subtitles), or `srt-only` (lossless `-c:v copy` mux + `.srt`).
- **Clean Architecture** — Separated `domain/`, `application/`, `infrastructure/`, and `cli` layers under `src/recap_pipeline/`.

---

## Prerequisites

- **Python** `>= 3.11` and [`uv`](https://docs.astral.sh/uv/)
- **FFmpeg & FFprobe** built with `libass` and `libharfbuzz` (`ffmpeg -filters` includes `ass`)
- **Myanmar Unicode font**:
  - Windows: `Myanmar Text` (`mmrtext.ttf`, preinstalled)
  - macOS: `Myanmar MN` or `Padauk` / `Noto Sans Myanmar`
  - Linux: `fonts-noto-core` (`NotoSansMyanmar`) or `fonts-sil-padauk` (or set `MYANMAR_FONT_DIR`)

---

## Install as an Agent Skill

Clone directly into your agent's global skills folder:

```bash
# Antigravity
git clone https://github.com/Yewaung/video-recap-skill.git ~/.gemini/config/skills/video-recap
uv sync --project ~/.gemini/config/skills/video-recap

# Claude Code
git clone https://github.com/Yewaung/video-recap-skill.git ~/.claude/skills/video-recap

# Codex
git clone https://github.com/Yewaung/video-recap-skill.git ~/.agents/skills/video-recap

# Gemini CLI
git clone https://github.com/Yewaung/video-recap-skill.git ~/.gemini/skills/video-recap
```

Then ask your AI agent in any workspace:
> *"Use `video-recap` to make a Myanmar recap version of my video in `./input`."*

---

## Standalone CLI Usage

### 1. Setup

```bash
git clone https://github.com/Yewaung/video-recap-skill.git
cd video-recap-skill
uv sync
```

### 2. Project Layout

```text
├── SKILL.md                             # Agent skill specification
├── references/
│   ├── script-template.json             # Scene-locked narration schema
│   └── burmese-pacing-guide.md          # Burmese TTS pacing & glyph-wrap rules
├── input/                               # Place source videos here (gitignored)
│   └── scripts/<video>.json             # Matching Myanmar script JSON (gitignored)
├── output/
│   └── <video>/                         # Per-video outputs: _mm.mp4, _mm.srt, _mm_script.md
├── build/                               # Ephemeral TTS/WAV/ASS/QA artifacts (gitignored)
└── src/recap_pipeline/
    ├── domain/models.py                 # Presets, dataclasses, timeline validators
    ├── application/
    │   ├── audio_engine.py              # Silence trim, slot fitting, PCM mix, loudnorm
    │   └── subtitle_engine.py           # Visual-cluster cue split & 2-line wrap
    ├── infrastructure/
    │   ├── media_probe.py               # Single/batch folder scanner & 20px ruler frames
    │   ├── tts_adapter.py               # Rate-limited Edge Neural TTS + SHA-256 cache
    │   └── video_composer.py            # FFmpeg composition & media/loudness/QA verifier
    └── cli.py                           # `recap` CLI entrypoint
```

### 3. Commands

```bash
# Interactive wizard (defaults to ./input & ./output, asks woman/man voice)
uv run recap wizard

# Scan a single video or batch folder (defaults to ./input)
uv run recap scan --input input --output build/scan.json

# Extract 20px pixel-ruler PNGs to find exact burned-in caption coordinates
uv run recap ruler --input input/demo.mp4

# Dry-run TTS timing check across all segments before rendering
uv run recap measure --script input/scripts/demo.json --voice woman

# Render final dubbed MP4, synced SRT, and script Markdown into ./output/<stem>/
uv run recap render --script input/scripts/demo.json --voice man --caption-mode frosted-mask

# Verify duration drift, audio loudness (volumedetect), and extract QA PNGs + audio sample
uv run recap verify --video output/demo/demo_mm.mp4 --source-video input/demo.mp4
```

---

## Cost & Rights Notes

- **Voiceover cost**: Free locally via Microsoft Edge Neural TTS (`edge-tts`). For high-volume commercial automation requiring an uptime SLA, swap `infrastructure/tts_adapter.py` to official Azure Speech SDK using the same `my-MM-NilarNeural` / `my-MM-ThihaNeural` voice IDs.
- **Rights & originality**: Only process content you own, license, or transform with genuine original commentary/review. Visual/audio evasion filters are intentionally omitted.

## License

[MIT](LICENSE)
