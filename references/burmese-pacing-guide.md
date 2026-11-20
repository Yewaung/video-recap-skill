# Burmese Video Recap Pacing & Style Guide

## 1. Voice Presets (Microsoft Edge Neural TTS)

| Preset | Voice ID | Style | Best For |
|---|---|---|---|
| `woman` | `my-MM-NilarNeural` | Clear, expressive female Burmese | 1st-person female narration, lifestyle/story TikToks |
| `man` | `my-MM-ThihaNeural` | Steady, authoritative male Burmese | 1st-person male narration, 3rd-person movie/documentary recaps |

Default speech rate: `+20%` (natural punchy short-form recap cadence without sounding rushed).

## 2. Character Budget & Time Fitting

At `rate="+20%"`, `my-MM-NilarNeural` and `my-MM-ThihaNeural` average **~18-20 Unicode code points per second** (including spaces and Burmese punctuation `၊`, `။`).

- **Target character budget per segment**:
  `max_unicode_chars ~= slot_seconds * 18`
- **Hard sync limit**: `max_speed <= 1.28x` (aim for `<= 1.15x` for natural tone).
- Always run `measure` before `render` so you inspect every segment's exact raw TTS duration vs. its slot window in one pass.
- When a segment reports `would_fit: false` or `ratio > 1.20`:
  - Replace formal particles (`ဖြစ်ခဲ့သလိုမျိုး`, `မည်သူမဆို`, `အလွန်အမင်း`) with concise spoken phrasing (`ဖြစ်သလို`, `ဘယ်သူမဆို`, `တော်တော်`).
  - Drop repeated pronouns when clear from context.
  - Trim filler words rather than key plot beats.

## 3. Narration POV Conventions

- **1st-person (`first_person`)**:
  - Female narrator: `ကျွန်မ` (narrative) or `ငါ` (inner dialogue)
  - Male narrator: `ကျွန်တော်` (narrative) or `ငါ` (inner dialogue)
- **3rd-person (`third_person`)**:
  - Recap narrator: `သူမ` (she), `သူ` (he), `သူတို့` (they), `ဇာတ်လိုက်` (protagonist)

## 4. Burmese Subtitle Splitting & Shaping

- Count **visual Burmese glyph clusters** (base consonants/vowels/punctuation, excluding combining signs/asat/medials and virama-stacked sub-consonants) rather than raw UTF-8 `len()`.
- Segments with `visual_length > 34` and span `>= 1.8s` split automatically into 2 proportional sequential cues at `၊`, `။`, or the space nearest midpoint.
- Wrap cues to `<= 2 lines` (`~27` visual glyphs/line max) at spaces.
- Never use FFmpeg `drawtext` for Myanmar; always render via `libass` (`ass` filter) with HarfBuzz shaping (`Myanmar Text`, `Noto Sans Myanmar`, `Padauk`, or `Myanmar MN`) so `ေ`, `ြ`, and stacked consonants shape properly.
