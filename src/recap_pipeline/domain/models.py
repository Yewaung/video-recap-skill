"""Pure domain models, presets, and timeline validators."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

VOICE_PRESETS: dict[str, str] = {
    "woman": "my-MM-NilarNeural",
    "female": "my-MM-NilarNeural",
    "man": "my-MM-ThihaNeural",
    "male": "my-MM-ThihaNeural",
}

CAPTION_MODES: tuple[str, ...] = ("frosted-mask", "clean-burn", "srt-only")
POV_MODES: tuple[str, ...] = ("first_person", "third_person")
_RATE_PATTERN = re.compile(r"^[+-]\d{1,3}%$")


class ValidationError(ValueError):
    """Raised when configuration, inputs, or script schema are invalid."""


class SyncOverflowError(RuntimeError):
    """Raised when a synthesized clip cannot fit its scene window within speed limits."""


def resolve_voice(voice: str) -> str:
    """Resolve friendly voice aliases ('woman'/'man') to Edge TTS voice IDs."""
    cleaned = voice.strip()
    if not cleaned:
        raise ValidationError("Voice cannot be empty.")
    return VOICE_PRESETS.get(cleaned.lower(), cleaned)


@dataclass(frozen=True, slots=True)
class SegmentSpec:
    """Declarative narration segment anchored to a video scene window."""

    id: int
    start: float
    end: float
    en: str
    mm: str


@dataclass(frozen=True, slots=True)
class RecapConfig:
    """Validated runtime configuration for a single video recap render."""

    input_video: Path
    output_dir: Path
    build_dir: Path
    duration: float
    width: int
    height: int
    voice: str
    rate: str
    pov: str
    caption_mode: str
    max_speed: float
    gap_sec: float
    max_borrow_sec: float
    band_y: int
    band_h: int
    segments: tuple[SegmentSpec, ...]


@dataclass(frozen=True, slots=True)
class FittedSegment:
    """Time-fitted audio segment placed on the master timeline."""

    spec: SegmentSpec
    raw_wav: Path
    fitted_wav: Path
    raw_duration: float
    fitted_duration: float
    speed: float
    actual_start: float
    actual_end: float


@dataclass(frozen=True, slots=True)
class SubtitleCue:
    """Single timed subtitle cue synced to fitted audio."""

    index: int
    segment_id: int
    start: float
    end: float
    text: str


def _infer_workspace_root(script_path: Path) -> Path:
    resolved = script_path.resolve()
    if resolved.parent.name == "scripts" and resolved.parent.parent.name == "input":
        return resolved.parent.parent.parent
    if resolved.parent.name == "scripts":
        return resolved.parent.parent
    return Path.cwd().resolve()


def load_config(
    script_path: Path,
    *,
    input_video_override: Path | None = None,
    output_dir_override: Path | None = None,
    build_dir_override: Path | None = None,
    voice_override: str | None = None,
    rate_override: str | None = None,
    caption_mode_override: str | None = None,
    band_y_override: int | None = None,
    band_h_override: int | None = None,
    probed_meta: dict | None = None,
) -> RecapConfig:
    """Load and validate recap JSON with clean workspace path defaults and CLI overrides."""
    resolved_script = script_path.resolve()
    if not resolved_script.is_file():
        raise ValidationError(f"Script JSON not found: {resolved_script}")

    raw = json.loads(resolved_script.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValidationError("Top-level recap JSON must be an object.")

    workspace = _infer_workspace_root(resolved_script)

    if input_video_override is not None:
        input_video = input_video_override.resolve()
    elif "input_video" in raw and str(raw["input_video"]).strip():
        cand = Path(str(raw["input_video"]))
        if cand.is_absolute():
            input_video = cand.resolve()
        else:
            candidates = (
                (workspace / cand).resolve(),
                (resolved_script.parent / cand).resolve(),
                (Path.cwd() / cand).resolve(),
            )
            input_video = next((p for p in candidates if p.is_file()), candidates[0])
    else:
        raise ValidationError("input_video must be provided in JSON or via --input-video.")

    stem = input_video.stem
    output_dir = (
        output_dir_override.resolve()
        if output_dir_override is not None
        else (workspace / "output" / stem).resolve()
    )
    build_dir = (
        build_dir_override.resolve()
        if build_dir_override is not None
        else (workspace / "build" / stem).resolve()
    )

    duration = float(probed_meta["duration"]) if probed_meta else float(raw.get("duration", 0.0))
    width = int(probed_meta["width"]) if probed_meta else int(raw.get("width", 0))
    height = int(probed_meta["height"]) if probed_meta else int(raw.get("height", 0))
    if duration <= 0 or width <= 0 or height <= 0:
        raise ValidationError("Video duration, width, and height must be positive.")

    voice = resolve_voice(voice_override if voice_override is not None else str(raw.get("voice", "woman")))
    rate = (rate_override if rate_override is not None else str(raw.get("rate", "+20%"))).strip()
    if not _RATE_PATTERN.match(rate):
        raise ValidationError(f"Invalid TTS rate '{rate}', expected format like '+20%'.")

    pov = str(raw.get("pov", "first_person")).strip()
    if pov not in POV_MODES:
        raise ValidationError(f"pov must be one of {POV_MODES}, got '{pov}'.")

    caption_mode = (
        caption_mode_override
        if caption_mode_override is not None
        else str(raw.get("caption_mode", "frosted-mask"))
    ).strip()
    if caption_mode not in CAPTION_MODES:
        raise ValidationError(f"caption_mode must be one of {CAPTION_MODES}, got '{caption_mode}'.")

    max_speed = float(raw.get("max_speed", 1.28))
    gap_sec = float(raw.get("gap_sec", 0.08))
    max_borrow_sec = float(raw.get("max_borrow_sec", 0.35))
    if max_speed <= 1.0 or max_speed > 2.0:
        raise ValidationError(f"max_speed must be in (1.0, 2.0], got {max_speed}.")
    if gap_sec < 0 or max_borrow_sec < 0:
        raise ValidationError("gap_sec and max_borrow_sec must be non-negative.")

    default_band_h = max(80, int(round(height * 0.146)))
    default_band_y = max(0, int(round(height * 0.688)))
    band_y = int(band_y_override if band_y_override is not None else raw.get("band_y", default_band_y))
    band_h = int(band_h_override if band_h_override is not None else raw.get("band_h", default_band_h))
    if caption_mode == "frosted-mask":
        if band_y < 0 or band_h <= 0 or band_y + band_h > height:
            raise ValidationError(
                f"Mask band [{band_y}, {band_y + band_h}] exceeds frame height {height}."
            )

    raw_segments = raw.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise ValidationError("segments must be a non-empty list.")

    parsed: list[SegmentSpec] = []
    prev_end = 0.0
    for idx, item in enumerate(raw_segments, start=1):
        if not isinstance(item, dict):
            raise ValidationError(f"Segment {idx} must be an object.")
        seg_id = int(item["id"])
        start = float(item["start"])
        end = float(item["end"])
        en = str(item.get("en", "")).strip()
        mm = str(item["mm"]).strip()

        if seg_id != idx:
            raise ValidationError(f"Expected segment id {idx}, got {seg_id}.")
        if start < 0 or start >= end or end > duration + 0.05:
            raise ValidationError(
                f"Segment {seg_id} has invalid window [{start}, {end}] for duration {duration:.2f}."
            )
        if start < prev_end - 1e-6:
            raise ValidationError(f"Segment {seg_id} start {start} overlaps previous end {prev_end}.")
        if not mm:
            raise ValidationError(f"Segment {seg_id} has empty Myanmar narration text.")
        if end - start <= gap_sec and idx < len(raw_segments):
            raise ValidationError(f"Segment {seg_id} window too narrow for gap_sec={gap_sec}.")

        parsed.append(SegmentSpec(id=seg_id, start=start, end=min(end, duration), en=en, mm=mm))
        prev_end = end

    return RecapConfig(
        input_video=input_video,
        output_dir=output_dir,
        build_dir=build_dir,
        duration=duration,
        width=width,
        height=height,
        voice=voice,
        rate=rate,
        pov=pov,
        caption_mode=caption_mode,
        max_speed=max_speed,
        gap_sec=gap_sec,
        max_borrow_sec=max_borrow_sec,
        band_y=band_y,
        band_h=band_h,
        segments=tuple(parsed),
    )


def validate_fitted_segments(fitted: list[FittedSegment], duration: float) -> None:
    """Ensure fitted timeline is strictly monotonic and has zero overlap."""
    if not fitted:
        raise ValidationError("Fitted segment list cannot be empty.")

    prev_end = 0.0
    for seg in fitted:
        if seg.actual_start < 0:
            raise ValidationError(f"Segment {seg.spec.id} starts before 0: {seg.actual_start}")
        if seg.actual_start < prev_end - 1e-4:
            raise ValidationError(
                f"Segment {seg.spec.id} overlap: start={seg.actual_start:.3f} < prev_end={prev_end:.3f}"
            )
        if seg.actual_end <= seg.actual_start:
            raise ValidationError(f"Segment {seg.spec.id} has non-positive fitted span.")
        if seg.actual_end > duration + 0.05:
            raise ValidationError(
                f"Segment {seg.spec.id} exceeds duration {duration:.3f}: {seg.actual_end:.3f}"
            )
        prev_end = seg.actual_end
