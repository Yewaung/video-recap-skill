"""Media scanning, metadata probing, and pixel-ruler frame extraction."""

from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}


def _run_ffprobe(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        shell=False,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def probe_video(video_path: Path) -> dict:
    """Extract normalized video and audio stream metadata via ffprobe."""
    resolved = video_path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Video file not found: {resolved}")

    res = _run_ffprobe(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(resolved),
        ]
    )
    data = json.loads(res.stdout)
    streams = data.get("streams", [])
    fmt = data.get("format", {})

    v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if v_stream is None:
        raise RuntimeError(f"No video stream found in {resolved}")

    fps_raw = v_stream.get("avg_frame_rate") or v_stream.get("r_frame_rate") or "30/1"
    fps = float(Fraction(fps_raw)) if "/" in fps_raw and fps_raw != "0/0" else float(fps_raw)

    return {
        "path": str(resolved),
        "name": resolved.name,
        "stem": resolved.stem,
        "size_bytes": int(fmt.get("size", resolved.stat().st_size)),
        "duration": round(float(fmt.get("duration", v_stream.get("duration", 0.0))), 3),
        "width": int(v_stream["width"]),
        "height": int(v_stream["height"]),
        "fps": round(fps, 3),
        "video_codec": str(v_stream.get("codec_name", "")),
        "audio_codec": str(a_stream.get("codec_name", "")) if a_stream else None,
        "audio_sample_rate": int(a_stream["sample_rate"]) if a_stream and "sample_rate" in a_stream else None,
        "audio_channels": int(a_stream["channels"]) if a_stream and "channels" in a_stream else None,
    }


def scan_input(input_path: Path) -> list[dict]:
    """Scan a single video file or a directory of videos and probe each one."""
    resolved = input_path.resolve()
    if resolved.is_file():
        if resolved.suffix.lower() not in VIDEO_EXTENSIONS:
            raise ValueError(f"Unsupported video extension '{resolved.suffix}': {resolved}")
        return [probe_video(resolved)]

    if not resolved.is_dir():
        raise FileNotFoundError(f"Input path not found: {resolved}")

    videos = sorted(
        p for p in resolved.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
    )
    if not videos:
        raise FileNotFoundError(
            f"No video files ({', '.join(sorted(VIDEO_EXTENSIONS))}) found in {resolved}"
        )
    return [probe_video(v) for v in videos]


def extract_ruler_frames(
    video_path: Path,
    out_dir: Path,
    timestamps: list[float] | None = None,
) -> dict:
    """Render 20px ruler grid PNGs with scaled horizontal reference lines to locate captions."""
    meta = probe_video(video_path)
    duration = float(meta["duration"])
    width = int(meta["width"])
    height = int(meta["height"])

    if not timestamps:
        ratios = (0.04, 0.18, 0.38, 0.65, 0.88)
        timestamps = [
            round(min(max(0.5, duration * r), max(0.5, duration - 0.5)), 2) for r in ratios
        ]

    y_red = int(round((height * 0.68) / 20) * 20)
    y_cyan = int(round((height * 0.78) / 20) * 20)
    y_yellow = int(round((height * 0.88) / 20) * 20)

    out_dir.mkdir(parents=True, exist_ok=True)
    vf = (
        f"drawgrid=x=0:y=0:w={width}:h=20:color=lime@0.45:t=1,"
        f"drawbox=x=0:y={y_red}:w={width}:h=2:color=red@0.9:t=fill,"
        f"drawbox=x=0:y={y_cyan}:w={width}:h=2:color=cyan@0.9:t=fill,"
        f"drawbox=x=0:y={y_yellow}:w={width}:h=2:color=yellow@0.9:t=fill"
    )

    frame_paths: list[str] = []
    for ts in timestamps:
        png_path = (out_dir / f"ruler_{str(ts).replace('.', '_')}.png").resolve()
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
                "-vf",
                vf,
                str(png_path),
            ],
            shell=False,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        frame_paths.append(str(png_path))

    return {
        "video": meta,
        "grid_step_px": 20,
        "guide_lines": {
            "red_y": y_red,
            "cyan_y": y_cyan,
            "yellow_y": y_yellow,
        },
        "frames": frame_paths,
    }
