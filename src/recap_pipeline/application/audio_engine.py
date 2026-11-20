"""Audio trimming, dry-run telemetry, scene-window tempo fitting, PCM assembly, and mastering."""

from __future__ import annotations

import array
import subprocess
import wave
from pathlib import Path

from recap_pipeline.domain.models import (
    FittedSegment,
    RecapConfig,
    SegmentSpec,
    SyncOverflowError,
    validate_fitted_segments,
)

SAMPLE_RATE = 48000


def _run_cmd(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        shell=False,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def probe_duration(media_path: Path) -> float:
    """Measure exact media duration in seconds via ffprobe."""
    res = _run_cmd(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media_path),
        ]
    )
    dur = float(res.stdout.strip())
    if dur <= 0:
        raise RuntimeError(f"Invalid measured duration {dur} for {media_path}")
    return dur


def _trim_to_wav(mp3_path: Path, wav_path: Path) -> float:
    """Strip leading/trailing dead silence and decode to 48kHz mono 16-bit PCM WAV."""
    silence_filter = (
        "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.04,"
        "areverse,"
        "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.04,"
        "areverse"
    )
    _run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(mp3_path),
            "-af",
            silence_filter,
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(wav_path),
        ]
    )
    dur = probe_duration(wav_path)
    if dur < 0.1:
        raise RuntimeError(f"Trimmed audio unexpectedly short ({dur:.3f}s) for {mp3_path}")
    return dur


def _render_fitted_wav(raw_wav: Path, fitted_wav: Path, speed: float) -> float:
    """Apply tempo adjustment (if needed) and symmetric 15ms boundary fades."""
    filters: list[str] = []
    if speed > 1.005:
        filters.append(f"atempo={speed:.4f}")
    filters.append("afade=t=in:st=0:d=0.015,areverse,afade=t=in:st=0:d=0.015,areverse")

    _run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(raw_wav),
            "-af",
            ",".join(filters),
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(fitted_wav),
        ]
    )
    return probe_duration(fitted_wav)


def _compute_slot(
    idx: int,
    spec: SegmentSpec,
    raw_dur: float,
    prev_end: float,
    config: RecapConfig,
    is_last: bool,
) -> tuple[float, float]:
    min_start = 0.0 if idx == 0 else prev_end + config.gap_sec
    target_start = max(spec.start, min_start)
    nominal_end = (config.duration - 0.05) if is_last else (spec.end - config.gap_sec)
    avail_no_borrow = nominal_end - target_start

    if avail_no_borrow <= 0.1:
        raise SyncOverflowError(
            f"Segment {spec.id} squeezed to {avail_no_borrow:.3f}s after previous borrow."
        )

    if raw_dur <= avail_no_borrow:
        return target_start, 1.0

    needed_speed = raw_dur / avail_no_borrow
    if needed_speed <= config.max_speed:
        return target_start, needed_speed

    min_dur_at_max = raw_dur / config.max_speed
    back_slack = max(0.0, target_start - min_start)
    back_borrow = min(back_slack, config.max_borrow_sec, min_dur_at_max - avail_no_borrow)
    actual_start = target_start - back_borrow
    avail_after_back = nominal_end - actual_start

    if min_dur_at_max <= avail_after_back:
        return actual_start, raw_dur / avail_after_back

    forward_needed = min_dur_at_max - avail_after_back
    max_forward = 0.0 if is_last else config.max_borrow_sec
    if forward_needed <= max_forward:
        return actual_start, config.max_speed

    raise SyncOverflowError(
        f"Segment {spec.id} overflows scene window: raw={raw_dur:.2f}s, "
        f"avail={avail_after_back:.2f}s (max borrow {max_forward:.2f}s), "
        f"would need speed={raw_dur / (avail_after_back + max_forward):.2f}x > {config.max_speed:.2f}x."
    )


def trim_and_measure_all(
    config: RecapConfig,
    mp3_map: dict[int, Path],
) -> list[dict]:
    """Dry-run duration diagnostics across ALL segments without stopping at first overflow."""
    raw_wav_dir = config.build_dir / "wav_raw"
    raw_wav_dir.mkdir(parents=True, exist_ok=True)
    report: list[dict] = []
    total = len(config.segments)

    for idx, spec in enumerate(config.segments):
        raw_wav = raw_wav_dir / f"seg_{spec.id:02d}.wav"
        raw_dur = _trim_to_wav(mp3_map[spec.id], raw_wav)
        is_last = idx == total - 1
        slot_dur = (config.duration - 0.05 - spec.start) if is_last else (spec.end - spec.start - config.gap_sec)
        ratio = raw_dur / slot_dur if slot_dur > 0 else 99.0
        min_at_max = raw_dur / config.max_speed
        max_avail = slot_dur + (0.0 if is_last else config.max_borrow_sec)
        would_fit = min_at_max <= max_avail
        report.append(
            {
                "id": spec.id,
                "scene_start": spec.start,
                "scene_end": spec.end,
                "slot_sec": round(slot_dur, 3),
                "raw_sec": round(raw_dur, 3),
                "ratio": round(ratio, 3),
                "would_fit": would_fit,
                "overflow_sec": round(max(0.0, min_at_max - max_avail), 3),
                "mm_chars": len(spec.mm),
            }
        )
    return report


def fit_and_assemble_audio(
    config: RecapConfig,
    mp3_map: dict[int, Path],
) -> tuple[list[FittedSegment], Path]:
    """Trim, time-fit, assemble on sample-accurate PCM timeline, and master to AAC."""
    raw_wav_dir = config.build_dir / "wav_raw"
    fit_wav_dir = config.build_dir / "wav_fit"
    raw_wav_dir.mkdir(parents=True, exist_ok=True)
    fit_wav_dir.mkdir(parents=True, exist_ok=True)

    fitted_segments: list[FittedSegment] = []
    prev_end = 0.0
    total = len(config.segments)

    for idx, spec in enumerate(config.segments):
        raw_wav = raw_wav_dir / f"seg_{spec.id:02d}.wav"
        fit_wav = fit_wav_dir / f"seg_{spec.id:02d}.wav"

        raw_dur = _trim_to_wav(mp3_map[spec.id], raw_wav)
        actual_start, speed = _compute_slot(
            idx=idx,
            spec=spec,
            raw_dur=raw_dur,
            prev_end=prev_end,
            config=config,
            is_last=(idx == total - 1),
        )
        fitted_dur = _render_fitted_wav(raw_wav, fit_wav, speed=speed)
        actual_end = actual_start + fitted_dur

        if idx == total - 1 and actual_end > config.duration:
            adjusted_speed = min(
                config.max_speed,
                speed * (fitted_dur / max(0.2, config.duration - actual_start - 0.02)),
            )
            if adjusted_speed > speed:
                fitted_dur = _render_fitted_wav(raw_wav, fit_wav, speed=adjusted_speed)
                speed = adjusted_speed
                actual_end = actual_start + fitted_dur

        fitted_segments.append(
            FittedSegment(
                spec=spec,
                raw_wav=raw_wav,
                fitted_wav=fit_wav,
                raw_duration=raw_dur,
                fitted_duration=fitted_dur,
                speed=speed,
                actual_start=actual_start,
                actual_end=actual_end,
            )
        )
        prev_end = actual_end

    validate_fitted_segments(fitted_segments, duration=config.duration)

    total_samples = int(round(config.duration * SAMPLE_RATE))
    mix_buf = array.array("i", [0]) * total_samples

    for seg in fitted_segments:
        with wave.open(str(seg.fitted_wav), "rb") as wf:
            if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() != SAMPLE_RATE:
                raise RuntimeError(f"Unexpected WAV format in {seg.fitted_wav}")
            frames = wf.readframes(wf.getnframes())
        samples = array.array("h")
        samples.frombytes(frames)
        start_sample = int(round(seg.actual_start * SAMPLE_RATE))
        limit = min(len(samples), total_samples - start_sample)
        for j in range(limit):
            val = mix_buf[start_sample + j] + samples[j]
            if val > 32767:
                val = 32767
            elif val < -32768:
                val = -32768
            mix_buf[start_sample + j] = val

    out_pcm = array.array("h", mix_buf)
    assembled_wav = config.build_dir / "assembled_raw.wav"
    with wave.open(str(assembled_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(out_pcm.tobytes())

    master_m4a = config.build_dir / "master_mm.m4a"
    _run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(assembled_wav),
            "-af",
            "highpass=f=80,acompressor=threshold=-18dB:ratio=2.5:attack=10:release=120,loudnorm=I=-14:TP=-1.5:LRA=11",
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            "2",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(master_m4a),
        ]
    )
    return fitted_segments, master_m4a
