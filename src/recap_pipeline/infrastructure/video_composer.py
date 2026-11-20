"""FFmpeg video composition, cross-platform Myanmar font staging, and QA verification."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from recap_pipeline.domain.models import RecapConfig
from recap_pipeline.infrastructure.media_probe import probe_video

_MEAN_VOL_RE = re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")
_MAX_VOL_RE = re.compile(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")

_FONT_FAMILY_HINTS: tuple[tuple[str, str], ...] = (
    ("mmrtext", "Myanmar Text"),
    ("notosansmyanmar", "Noto Sans Myanmar"),
    ("padauk", "Padauk"),
    ("myanmar mn", "Myanmar MN"),
    ("myanmarmn", "Myanmar MN"),
    ("myanmar sangam", "Myanmar Sangam MN"),
    ("pyidaungsu", "Pyidaungsu"),
)


def _infer_font_family(font_path: Path) -> str:
    stem_lower = font_path.stem.lower()
    for needle, family in _FONT_FAMILY_HINTS:
        if needle in stem_lower:
            return family
    return "Myanmar Text"


def _find_system_myanmar_fonts() -> list[Path]:
    env_dir = os.environ.get("MYANMAR_FONT_DIR", "").strip()
    if env_dir:
        custom = Path(env_dir).expanduser()
        if custom.is_dir():
            matches = sorted(
                p for p in custom.iterdir() if p.is_file() and p.suffix.lower() in {".ttf", ".ttc", ".otf"}
            )
            if matches:
                return matches

    win_candidates = [
        Path(r"C:\Windows\Fonts\mmrtext.ttf"),
        Path(r"C:\Windows\Fonts\mmrtextb.ttf"),
    ]
    win_found = [p for p in win_candidates if p.is_file()]
    if win_found:
        return win_found

    mac_candidates = [
        Path("/System/Library/Fonts/Supplemental/Myanmar MN.ttc"),
        Path("/System/Library/Fonts/Supplemental/Myanmar Sangam MN.ttc"),
    ]
    mac_found = [p for p in mac_candidates if p.is_file()]
    if mac_found:
        return mac_found

    search_roots = (
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        Path.home() / ".local" / "share" / "fonts",
        Path("/Library/Fonts"),
        Path.home() / "Library" / "Fonts",
    )
    for root in search_roots:
        if not root.is_dir():
            continue
        found = sorted(
            p
            for p in root.rglob("*")
            if p.is_file()
            and p.suffix.lower() in {".ttf", ".ttc", ".otf"}
            and any(k in p.stem.lower() for k in ("myanmar", "padauk", "pyidaungsu"))
        )
        if found:
            return found[:4]

    return []


def detect_and_stage_fonts(fonts_dir: Path) -> str:
    """Copy platform Myanmar Unicode fonts into build/fonts and return ASS Fontname."""
    sources = _find_system_myanmar_fonts()
    if not sources:
        raise FileNotFoundError(
            "No Myanmar Unicode font found. Install Myanmar Text (Windows), "
            "Noto Sans Myanmar / Padauk (Linux/macOS), or set MYANMAR_FONT_DIR."
        )

    fonts_dir.mkdir(parents=True, exist_ok=True)
    for src in sources:
        dst = fonts_dir / src.name
        if not dst.is_file():
            shutil.copy2(src, dst)
    return _infer_font_family(sources[0])


def compose_video(
    config: RecapConfig,
    master_audio: Path,
    ass_path: Path,
) -> Path:
    """Compose final MP4 using cross-drive-safe cwd=build_dir for libass filter paths."""
    if not config.input_video.is_file():
        raise FileNotFoundError(f"Source video not found: {config.input_video}")

    config.output_dir.mkdir(parents=True, exist_ok=True)
    output_video = (config.output_dir / f"{config.input_video.stem}_mm.mp4").resolve()

    if config.caption_mode == "srt-only":
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(config.input_video.resolve()),
                "-i",
                str(master_audio.resolve()),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "copy",
                "-movflags",
                "+faststart",
                "-shortest",
                str(output_video),
            ],
            shell=False,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return output_video

    fonts_dir = config.build_dir / "fonts"
    detect_and_stage_fonts(fonts_dir)

    rel_ass = ass_path.resolve().relative_to(config.build_dir.resolve()).as_posix()
    rel_fonts = fonts_dir.resolve().relative_to(config.build_dir.resolve()).as_posix()

    if config.caption_mode == "frosted-mask":
        w = config.width
        band_y = config.band_y
        band_h = config.band_h
        bottom_border_y = band_h - 2
        filter_complex = (
            f"[0:v]split=2[base][band_src];"
            f"[band_src]crop={w}:{band_h}:0:{band_y},boxblur=20:2,"
            f"drawbox=x=0:y=0:w={w}:h={band_h}:color=black@0.76:t=fill,"
            f"drawbox=x=0:y=0:w={w}:h=2:color=white@0.18:t=fill,"
            f"drawbox=x=0:y={bottom_border_y}:w={w}:h=2:color=white@0.18:t=fill[band];"
            f"[base][band]overlay=0:{band_y},ass={rel_ass}:fontsdir={rel_fonts}[vout]"
        )
    else:
        filter_complex = f"[0:v]ass={rel_ass}:fontsdir={rel_fonts}[vout]"

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(config.input_video.resolve()),
            "-i",
            str(master_audio.resolve()),
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            "-shortest",
            str(output_video),
        ],
        cwd=str(config.build_dir.resolve()),
        shell=False,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return output_video


def verify_output(
    video_path: Path,
    qa_dir: Path,
    source_video: Path | None = None,
) -> dict:
    """Inspect final video codecs, loudness, and extract QA screenshots + 15s audio preview."""
    meta = probe_video(video_path)
    src_meta = probe_video(source_video) if source_video and source_video.is_file() else None

    vol_res = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(video_path.resolve()),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        shell=False,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    vol_text = vol_res.stderr or ""
    mean_match = _MEAN_VOL_RE.search(vol_text)
    max_match = _MAX_VOL_RE.search(vol_text)
    mean_db = float(mean_match.group(1)) if mean_match else None
    max_db = float(max_match.group(1)) if max_match else None

    qa_dir.mkdir(parents=True, exist_ok=True)
    duration = float(meta["duration"])
    sample_timestamps = [
        round(min(max(0.5, duration * r), max(0.5, duration - 0.5)), 2)
        for r in (0.03, 0.15, 0.44, 0.63, 0.90)
    ]
    qa_frames: list[str] = []
    for ts in sample_timestamps:
        png = (qa_dir / f"qa_{str(ts).replace('.', '_')}.png").resolve()
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-ss",
                f"{ts:.2f}",
                "-i",
                str(video_path.resolve()),
                "-frames:v",
                "1",
                str(png),
            ],
            shell=False,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        qa_frames.append(str(png))

    sample_dur = min(15.0, duration)
    sample_audio = (qa_dir / "sample_audio.mp3").resolve()
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-ss",
            "0",
            "-t",
            f"{sample_dur:.2f}",
            "-i",
            str(video_path.resolve()),
            "-vn",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "2",
            str(sample_audio),
        ],
        shell=False,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    drift_sec = round(abs(duration - float(src_meta["duration"])), 3) if src_meta else None
    loudness_ok = (mean_db is not None and -22.0 <= mean_db <= -10.0) and (
        max_db is not None and max_db <= -0.5
    )
    drift_ok = True if drift_sec is None else drift_sec <= 0.25

    return {
        "video": meta,
        "duration_drift_sec": drift_sec,
        "mean_volume_db": mean_db,
        "max_volume_db": max_db,
        "qa_frames": qa_frames,
        "sample_audio": str(sample_audio),
        "passed_media_checks": bool(
            meta["audio_codec"] == "aac"
            and loudness_ok
            and drift_ok
            and all(Path(p).is_file() for p in qa_frames)
            and sample_audio.is_file()
        ),
    }
