"""Burmese subtitle cue splitting, visual-width two-line wrapping, ASS/SRT/Markdown export."""

from __future__ import annotations

from pathlib import Path

from recap_pipeline.domain.models import FittedSegment, RecapConfig, SubtitleCue


def _is_myanmar_combining(ch: str) -> bool:
    code = ord(ch)
    return (
        0x102B <= code <= 0x103E
        or 0x1056 <= code <= 0x1059
        or 0x1060 <= code <= 0x1064
        or 0x1067 <= code <= 0x106D
        or 0x1071 <= code <= 0x1074
        or 0x1082 <= code <= 0x108D
        or code == 0x108F
        or 0x109A <= code <= 0x109D
    )


def visual_length(text: str) -> int:
    """Count approximate visual Burmese glyph clusters (excludes combining marks & virama stack)."""
    count = 0
    prev_virama = False
    for ch in text:
        if ch == "\u1039":
            prev_virama = True
            continue
        if _is_myanmar_combining(ch):
            continue
        if prev_virama:
            prev_virama = False
            continue
        count += 1
    return count


def _find_split_index(text: str) -> int | None:
    mid = len(text) // 2
    best_idx: int | None = None
    best_score = float("inf")

    for idx, ch in enumerate(text):
        if idx < 8 or idx > len(text) - 8:
            continue
        if ch in ("၊", "။"):
            split_at = idx + 1
            if split_at < len(text) and text[split_at] == " ":
                split_at += 1
            score = abs(split_at - mid) * 0.65
        elif ch == " ":
            split_at = idx + 1
            score = float(abs(split_at - mid))
        else:
            continue

        if score < best_score:
            best_score = score
            best_idx = split_at

    return best_idx


def _wrap_two_lines(text: str, max_visual_per_line: int = 27) -> list[str]:
    cleaned = " ".join(text.split())
    if visual_length(cleaned) <= max_visual_per_line:
        return [cleaned]

    mid = len(cleaned) // 2
    space_positions = [i for i, ch in enumerate(cleaned) if ch == " "]
    if not space_positions:
        return [cleaned]

    best_pos = min(
        space_positions,
        key=lambda pos: (
            max(visual_length(cleaned[:pos]), visual_length(cleaned[pos + 1 :])) > max_visual_per_line,
            abs(pos - mid),
        ),
    )
    left = cleaned[:best_pos].strip()
    right = cleaned[best_pos + 1 :].strip()
    if not left or not right:
        return [cleaned]
    return [left, right]


def build_subtitle_cues(fitted_segments: list[FittedSegment]) -> list[SubtitleCue]:
    """Split long segments into proportional sequential cues synced to fitted audio."""
    cues: list[SubtitleCue] = []
    cue_idx = 1

    for seg in fitted_segments:
        text = seg.spec.mm.strip()
        vis_len = visual_length(text)
        span = seg.actual_end - seg.actual_start

        if vis_len > 34 and span >= 1.8:
            split_at = _find_split_index(text)
            if split_at is not None:
                part1 = text[:split_at].strip()
                part2 = text[split_at:].strip()
                if part1 and part2:
                    v1 = max(1, visual_length(part1))
                    v2 = max(1, visual_length(part2))
                    split_time = seg.actual_start + span * (v1 / (v1 + v2))
                    split_time = max(seg.actual_start + 0.8, min(seg.actual_end - 0.8, split_time))
                    cues.append(
                        SubtitleCue(
                            index=cue_idx,
                            segment_id=seg.spec.id,
                            start=seg.actual_start,
                            end=split_time - 0.02,
                            text=part1,
                        )
                    )
                    cue_idx += 1
                    cues.append(
                        SubtitleCue(
                            index=cue_idx,
                            segment_id=seg.spec.id,
                            start=split_time,
                            end=seg.actual_end,
                            text=part2,
                        )
                    )
                    cue_idx += 1
                    continue

        cues.append(
            SubtitleCue(
                index=cue_idx,
                segment_id=seg.spec.id,
                start=seg.actual_start,
                end=seg.actual_end,
                text=text,
            )
        )
        cue_idx += 1

    return cues


def _fmt_srt_time(seconds: float) -> str:
    ms_total = max(0, int(round(seconds * 1000)))
    hrs, rem = divmod(ms_total, 3600_000)
    mins, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{ms:03d}"


def _fmt_ass_time(seconds: float) -> str:
    cs_total = max(0, int(round(seconds * 100)))
    hrs, rem = divmod(cs_total, 3600_00)
    mins, rem = divmod(rem, 6000)
    secs, cs = divmod(rem, 100)
    return f"{hrs:d}:{mins:02d}:{secs:02d}.{cs:02d}"


def write_subtitles_and_script(
    config: RecapConfig,
    fitted_segments: list[FittedSegment],
    font_name: str = "Myanmar Text",
) -> tuple[list[SubtitleCue], Path, Path, Path]:
    """Write SRT, ASS, and Markdown script files into output_dir and build_dir."""
    cues = build_subtitle_cues(fitted_segments)
    stem = config.input_video.stem

    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.build_dir.mkdir(parents=True, exist_ok=True)

    srt_path = config.output_dir / f"{stem}_mm.srt"
    script_path = config.output_dir / f"{stem}_mm_script.md"
    ass_path = config.build_dir / "recap_mm.ass"

    srt_blocks: list[str] = []
    for cue in cues:
        lines = _wrap_two_lines(cue.text)
        srt_blocks.append(
            f"{cue.index}\n{_fmt_srt_time(cue.start)} --> {_fmt_srt_time(cue.end)}\n"
            + "\n".join(lines)
        )
    srt_path.write_text("\n\n".join(srt_blocks) + "\n", encoding="utf-8-sig")

    font_size = max(20, int(round(config.width * 0.0435)))
    margin_lr = max(20, int(round(config.width * 0.045)))
    if config.caption_mode == "frosted-mask":
        margin_v = config.height - (config.band_y + config.band_h) + max(18, int(round(config.band_h * 0.25)))
    else:
        margin_v = max(40, int(round(config.height * 0.10)))

    ass_header = f"""[Script Info]
Title: {stem}_mm Recap Subtitles
ScriptType: v4.00+
PlayResX: {config.width}
PlayResY: {config.height}
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: MyanmarRecap,{font_name},{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,1.8,0.8,2,{margin_lr},{margin_lr},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ass_events = [
        f"Dialogue: 0,{_fmt_ass_time(c.start)},{_fmt_ass_time(c.end)},MyanmarRecap,,0,0,0,,{r'\N'.join(_wrap_two_lines(c.text))}"
        for c in cues
    ]
    ass_path.write_text(ass_header + "\n".join(ass_events) + "\n", encoding="utf-8")

    md_lines = [
        f"# Myanmar Video Recap Script (`{config.input_video.name}`)",
        "",
        f"- **Voice**: `{config.voice}` (rate `{config.rate}`)",
        f"- **POV**: `{config.pov}` | **Caption Mode**: `{config.caption_mode}`",
        f"- **Duration**: `{config.duration:.2f}s` ({config.width}x{config.height})",
        f"- **Segments**: `{len(fitted_segments)}` | **Subtitle Cues**: `{len(cues)}`",
        "",
        "| # | Scene Window | Actual Audio Span | Speed | Myanmar Narration | English Reference |",
        "|---|---|---|---|---|---|",
    ]
    for seg in fitted_segments:
        md_lines.append(
            f"| {seg.spec.id} | {seg.spec.start:.2f}s - {seg.spec.end:.2f}s | "
            f"{seg.actual_start:.2f}s - {seg.actual_end:.2f}s | {seg.speed:.2f}x | "
            f"{seg.spec.mm} | {seg.spec.en} |"
        )
    script_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    return cues, srt_path, ass_path, script_path
