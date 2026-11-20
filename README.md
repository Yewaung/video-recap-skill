# video-recap-skill

Open-source **Agent Skill + Clean Architecture CLI** for turning short-form / TikTok videos into **Myanmar-dubbed, Myanmar-subtitled recap videos** with scene-synced Edge Neural TTS, HarfBuzz-shaped `libass` Burmese subtitles, frosted caption masking, timed `.srt` export, and automated audio/visual QA.

---

## How It Works (AI Agent vs. Local CLI)

| Responsibility | Handled By | API Key Needed? |
|---|---|---|
| Watch scenes, transcribe/understand dialogue, write timed Burmese script (`script.json`), inspect QA PNGs | **Your AI coding agent** (Antigravity, Gemini CLI, Claude Code, Codex) — or written manually | Agent plan/subscription only |
| Speech synthesis (`my-MM-NilarNeural` / `my-MM-ThihaNeural`), silence trim, duration sync, PCM mastering, `libass` subtitle burn-in, `.srt` & QA extraction | **Local Python + FFmpeg CLI** (`recap` / `edge-tts`) | **None (`$0.00`)** |

> **No TTS API key required.** Edge Neural TTS runs free with zero credentials. (`GEMINI_API_KEY` is only needed if you optionally opt into `gemini-tts`.)

---

## AI Compatibility & What Is Required

Pick the workflow that matches your setup:

| Tool / Mode | Skill Install Path | Native `.mp4` + Audio? | Visual QA (`.png`) | Notes to Start |
|---|---|---|---|---|
| **Antigravity** *(Recommended)* | `~/.gemini/config/skills/video-recap` | Yes (native video + audio + PNG) | Yes | Best out-of-the-box experience: watches `.mp4`, runs `ruler`/`measure`/`render`, inspects QA PNGs & `.mp3` |
| **Gemini CLI** | `~/.gemini/skills/video-recap` | Yes (native multimodal) | Yes | Full end-to-end multimodal video understanding + CLI execution |
| **Claude Code** | `~/.claude/skills/video-recap` | Text + Images only *(no raw `.mp4` stream)* | Yes (PNGs) | Works smoothly for script writing, `measure`/`render`, and PNG QA; pair with `whisper` / `faster-whisper` (or paste transcript + ruler/keyframe PNGs) so Claude can read the dialogue |
| **Codex / Cursor / Other `SKILL.md` Agents** | `~/.agents/skills/video-recap` *(or repo `.agents/skills/`)* | Depends on model | Yes (vision models) | If the active model does not accept raw `.mp4`, generate an `.srt`/transcript with Whisper + extract keyframes first |
| **Standalone CLI (No AI)** | Clone repo anywhere | Manual script | Manual | Write `input/scripts/<video>.json` from [script-template.json](references/script-template.json) and run `uv run recap wizard` |

---

## Step 1: Install Prerequisites

Install **Python `>= 3.11`**, **`uv`**, **`ffmpeg` / `ffprobe`** (compiled with `libass` + `harfbuzz`), and a **Myanmar Unicode font**:

### Windows (PowerShell)
```powershell
winget install --id astral-sh.uv -e
winget install --id Gyan.FFmpeg -e
# Myanmar Text font (mmrtext.ttf) is preinstalled on Windows 10/11
```

### macOS (Homebrew)
```sh
brew install uv ffmpeg
# Myanmar MN is preinstalled; optionally install Padauk for cleaner bold weight
```

### Ubuntu / Debian
```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
sudo apt update && sudo apt install -y ffmpeg fonts-sil-padauk fonts-noto-core
```

### Verify FFmpeg Subtitle Support
Confirm `ass` and `loudnorm` filters are available:
```sh
ffmpeg -hide_banner -filters | grep -E "ass|loudnorm|boxblur"
```

---

## Step 2A: Quick Start with an AI Agent (Claude, Gemini, Antigravity, Codex)

### 1. Install the Skill Globally
Clone the repository into your agent's skill directory and sync the isolated `uv` environment once:

```sh
# Antigravity
git clone https://github.com/Yewaung/video-recap-skill.git ~/.gemini/config/skills/video-recap
uv sync --project ~/.gemini/config/skills/video-recap

# Gemini CLI
git clone https://github.com/Yewaung/video-recap-skill.git ~/.gemini/skills/video-recap
uv sync --project ~/.gemini/skills/video-recap

# Claude Code
git clone https://github.com/Yewaung/video-recap-skill.git ~/.claude/skills/video-recap
uv sync --project ~/.claude/skills/video-recap

# Codex CLI / Workspace-agnostic
git clone https://github.com/Yewaung/video-recap-skill.git ~/.agents/skills/video-recap
uv sync --project ~/.agents/skills/video-recap
```

*(Note for Claude Code / Codex users: if the agent is triggered directly from `SKILL.md` without calling `uv run recap`, it runs `uv run --project <skill-dir> recap ...` automatically.)*

### 2. Drop Videos & Prompt Your Agent
Put your source `.mp4` video(s) into a folder (e.g., `./input/`) and ask your agent:

- **Antigravity / Gemini CLI**:
  > *"Use `video-recap` to convert `./input/my_clip.mp4` into a Myanmar recap video in `./output`."*
- **Batch folder**:
  > *"Run `video-recap` on all videos in `./input` and save Myanmar versions to `./output`."*
- **Claude Code** *(with transcript or Whisper installed)*:
  > *"Use `video-recap` on `./input/my_clip.mp4`. Transcribe the audio with Whisper and extract keyframes first, then ask me for voice and caption options before rendering to `./output`."*

### 3. Answer the 4 Interactive Prompts
On every run, [SKILL.md](SKILL.md) instructs the agent to ask you:
1. **Input & Output Folders**: Single video or folder path + destination output directory.
2. **Voice Choice**: Woman (`my-MM-NilarNeural`), Man (`my-MM-ThihaNeural`), or `gemini-tts`.
3. **Narration POV**: 1st-person TikTok (`ကျွန်မ` / `ကျွန်တော်`) or 3rd-person movie recap (`သူမ` / `သူ`).
4. **Caption Mode**:
   - `frosted-mask` — dark blurred subtitle bar over burned-in English captions + Myanmar text
   - `clean-burn` — Myanmar subtitles directly over clean video
   - `srt-only` — lossless `-c:v copy` video + Myanmar voiceover + external `.srt`

---

## Step 2B: Quick Start Standalone (CLI / Interactive Wizard)

Use this path when running directly from the terminal with or without an AI agent.

### 1. Clone & Sync
```sh
git clone https://github.com/Yewaung/video-recap-skill.git
cd video-recap-skill
uv sync
```

### 2. Add Your Video & Script
1. Place source video(s) in `input/` (for example, `input/demo.mp4`).
2. Scan metadata:
   ```sh
   uv run recap scan --input input --output build/scan.json
   ```
3. *(If using `frosted-mask`)* Extract 20px pixel-ruler PNGs to find exact `band_y` / `band_h` coordinates covering source captions:
   ```sh
   uv run recap ruler --input input/demo.mp4
   ```
4. Create `input/scripts/demo.json` based on [references/script-template.json](references/script-template.json) and character pacing rules in [references/burmese-pacing-guide.md](references/burmese-pacing-guide.md).

### 3. Dry-Run Fit, Render & Verify
```sh
# 1. Check that every Burmese line fits its scene window (<= 1.28x speed, zero overlap)
uv run recap measure --script input/scripts/demo.json --voice woman

# 2. Render MP4, synced SRT, and Markdown script into output/demo/
uv run recap render --script input/scripts/demo.json --voice woman --caption-mode frosted-mask

# 3. Verify duration drift, audio loudness, and extract 5 QA frames + 15s audio preview
uv run recap verify --video output/demo/demo_mm.mp4 --source-video input/demo.mp4
```

Or run the interactive terminal prompt instead:
```sh
uv run recap wizard
```

---

## Project Layout & CLI Reference

```text
├── SKILL.md                             # Agent skill prompt & workflow
├── pyproject.toml                       # uv project + `recap` console entrypoint
├── references/
│   ├── script-template.json             # Scene-locked JSON schema
│   └── burmese-pacing-guide.md          # Burmese speech rate & glyph-wrap rules
├── input/                               # Place source videos here (gitignored)
│   └── scripts/<video>.json             # Matching Myanmar scripts (gitignored)
├── output/
│   └── <video>/                         # Outputs: <video>_mm.mp4, _mm.srt, _mm_script.md
├── build/                               # Ephemeral TTS/WAV/ASS/QA files (gitignored)
└── src/recap_pipeline/
    ├── domain/models.py                 # Presets, dataclasses, timeline validators
    ├── application/
    │   ├── audio_engine.py              # Silence trim, slot fit, 48kHz PCM mix, loudnorm
    │   └── subtitle_engine.py           # Burmese visual-cluster cue split & 2-line wrap
    ├── infrastructure/
    │   ├── media_probe.py               # Input folder scanner & 20px ruler extractor
    │   ├── tts_adapter.py               # Rate-limited Edge Neural TTS + SHA-256 cache
    │   └── video_composer.py            # Cross-platform font staging, FFmpeg & QA check
    └── cli.py                           # CLI entrypoint (`uv run recap`)
```

| Command | Description | Default Outputs |
|---|---|---|
| `uv run recap scan` | Scan single video or folder (`./input`) | `build/scan.json` |
| `uv run recap ruler` | Render 20px grid + guide lines for caption coordinates | `build/<stem>/ruler/*.png`, `ruler.json` |
| `uv run recap measure` | Synthesize TTS and report per-segment fit without rendering | `build/<stem>/measure.json` |
| `uv run recap render` | Fit audio, build `.srt`/`.ass`/`_script.md`, render `_mm.mp4` | `output/<stem>/<stem>_mm.*` |
| `uv run recap verify` | Check codecs, drift, loudness + extract QA frames & audio sample | `build/<stem>/verify.json`, `qa/` |
| `uv run recap wizard` | Interactive prompt flow for folders, voice, rate, and caption mode | `output/<stem>/<stem>_mm.*` |

---

## Troubleshooting

- **Subtitle text shows boxes or broken Burmese vowels (`ေ` in wrong place)**:
  Ensure FFmpeg has `libass` + HarfBuzz (`ffmpeg -filters | grep ass`), and set `MYANMAR_FONT_DIR` to a folder containing `mmrtext.ttf`, `NotoSansMyanmar-Regular.ttf`, or `Padauk-Regular.ttf`.
- **Segment overflows scene window (`would_fit: false` in `measure.json`)**:
  Trim filler particles so each Burmese segment stays under `slot_seconds * 18` Unicode characters (see [burmese-pacing-guide.md](references/burmese-pacing-guide.md)).
- **Source English captions still peek above/below the dark bar**:
  Re-run `uv run recap ruler --input <video>`, inspect the PNG grid (20px steps), and adjust `band_y` / `band_h` in your script JSON or pass `--band-y` / `--band-h` to `render`.

---

## Cost & Rights Notice

- **Direct Cost**: **`$0.00`** per video locally using Microsoft Edge Neural TTS (`edge-tts`) + local FFmpeg. For high-volume commercial automation requiring an uptime SLA, swap only `src/recap_pipeline/infrastructure/tts_adapter.py` to the official Azure Speech SDK using the same `my-MM-NilarNeural` / `my-MM-ThihaNeural` voice IDs (500k chars/month free tier, ~`$16/1M` chars paid).
- **Copyright & Originality**: Only process videos you own, license, or transform with genuine original commentary/review. Visual/audio evasion filters are intentionally excluded.

## License

[MIT](LICENSE)
