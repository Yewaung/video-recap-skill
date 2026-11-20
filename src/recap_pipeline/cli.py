"""CLI presentation layer wiring domain, application, and infrastructure."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from recap_pipeline.application.audio_engine import fit_and_assemble_audio, trim_and_measure_all
from recap_pipeline.application.subtitle_engine import write_subtitles_and_script
from recap_pipeline.domain.models import CAPTION_MODES, RecapConfig, load_config
from recap_pipeline.infrastructure.media_probe import extract_ruler_frames, probe_video, scan_input
from recap_pipeline.infrastructure.tts_adapter import synthesize_segments
from recap_pipeline.infrastructure.video_composer import (
    compose_video,
    detect_and_stage_fonts,
    verify_output,
)


def _write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _cmd_scan(args: argparse.Namespace) -> int:
    videos = scan_input(Path(args.input))
    out_path = Path(args.output).resolve()
    _write_json(out_path, {"count": len(videos), "videos": videos})
    print(f"Scanned {len(videos)} video(s). Manifest written to: {out_path}")
    return 0


def _cmd_ruler(args: argparse.Namespace) -> int:
    in_video = Path(args.input).resolve()
    stem = in_video.stem
    out_dir = Path(args.output_dir).resolve() if args.output_dir else (Path("build") / stem / "ruler").resolve()
    out_json = Path(args.output).resolve() if args.output else (out_dir / "ruler.json").resolve()
    ts_list = (
        [float(x.strip()) for x in args.timestamps.split(",") if x.strip()]
        if args.timestamps
        else None
    )
    result = extract_ruler_frames(video_path=in_video, out_dir=out_dir, timestamps=ts_list)
    _write_json(out_json, result)
    print(f"Extracted {len(result['frames'])} ruler frame(s). Metadata written to: {out_json}")
    return 0


def _load_with_probe(args: argparse.Namespace) -> RecapConfig:
    script_path = Path(args.script).resolve()
    input_override = Path(args.input_video).resolve() if args.input_video else None

    probed_meta = None
    if input_override is not None:
        probed_meta = probe_video(input_override)
    else:
        raw = json.loads(script_path.read_text(encoding="utf-8"))
        if "input_video" in raw and ("duration" not in raw or "width" not in raw or "height" not in raw):
            cand = Path(str(raw["input_video"]))
            if not cand.is_absolute():
                for base in (Path.cwd(), script_path.parent.parent.parent, script_path.parent):
                    if (base / cand).is_file():
                        cand = base / cand
                        break
            probed_meta = probe_video(cand)

    return load_config(
        script_path=script_path,
        input_video_override=input_override,
        output_dir_override=Path(args.output_dir).resolve() if getattr(args, "output_dir", None) else None,
        build_dir_override=Path(args.build_dir).resolve() if getattr(args, "build_dir", None) else None,
        voice_override=args.voice,
        rate_override=args.rate,
        caption_mode_override=getattr(args, "caption_mode", None),
        band_y_override=getattr(args, "band_y", None),
        band_h_override=getattr(args, "band_h", None),
        probed_meta=probed_meta,
    )


def _cmd_measure(args: argparse.Namespace) -> int:
    config = _load_with_probe(args)
    mp3_map = synthesize_segments(
        segments=config.segments,
        voice=config.voice,
        rate=config.rate,
        out_dir=config.build_dir / "tts_mp3",
    )
    rows = trim_and_measure_all(config=config, mp3_map=mp3_map)
    overflows = [r for r in rows if not r["would_fit"]]
    out_path = Path(args.output).resolve() if args.output else (config.build_dir / "measure.json").resolve()
    _write_json(
        out_path,
        {
            "voice": config.voice,
            "rate": config.rate,
            "duration": config.duration,
            "overflow_count": len(overflows),
            "segments": rows,
        },
    )
    print(f"Measured {len(rows)} segments ({len(overflows)} overflow). Report written to: {out_path}")
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    config = _load_with_probe(args)
    mp3_map = synthesize_segments(
        segments=config.segments,
        voice=config.voice,
        rate=config.rate,
        out_dir=config.build_dir / "tts_mp3",
    )
    fitted_segments, master_audio = fit_and_assemble_audio(config=config, mp3_map=mp3_map)
    font_name = (
        detect_and_stage_fonts(config.build_dir / "fonts")
        if config.caption_mode != "srt-only"
        else "Myanmar Text"
    )
    cues, srt_path, ass_path, script_md_path = write_subtitles_and_script(
        config=config,
        fitted_segments=fitted_segments,
        font_name=font_name,
    )
    out_video = compose_video(config=config, master_audio=master_audio, ass_path=ass_path)

    manifest = {
        "input_video": str(config.input_video),
        "output_video": str(out_video),
        "output_srt": str(srt_path),
        "output_script": str(script_md_path),
        "voice": config.voice,
        "rate": config.rate,
        "pov": config.pov,
        "caption_mode": config.caption_mode,
        "cue_count": len(cues),
        "segments": [
            {
                "id": s.spec.id,
                "scene_start": s.spec.start,
                "scene_end": s.spec.end,
                "actual_start": round(s.actual_start, 3),
                "actual_end": round(s.actual_end, 3),
                "raw_duration": round(s.raw_duration, 3),
                "fitted_duration": round(s.fitted_duration, 3),
                "speed": round(s.speed, 3),
            }
            for s in fitted_segments
        ],
    }
    out_path = Path(args.output).resolve() if args.output else (config.build_dir / "render_manifest.json").resolve()
    _write_json(out_path, manifest)
    print(f"Rendered video to: {out_video} (manifest: {out_path})")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    video_path = Path(args.video).resolve()
    raw_stem = video_path.stem[:-3] if video_path.stem.endswith("_mm") else video_path.stem
    qa_dir = Path(args.qa_dir).resolve() if args.qa_dir else (Path("build") / raw_stem / "qa").resolve()
    out_json = Path(args.output).resolve() if args.output else (Path("build") / raw_stem / "verify.json").resolve()
    src = Path(args.source_video).resolve() if args.source_video else None

    result = verify_output(video_path=video_path, qa_dir=qa_dir, source_video=src)
    _write_json(out_json, result)
    print(f"Verify {'PASSED' if result['passed_media_checks'] else 'FAILED'} -> report written to: {out_json}")
    return 0 if result["passed_media_checks"] else 1


def _cmd_wizard(_: argparse.Namespace) -> int:
    print("=== Myanmar Video Recap Wizard ===")
    in_raw = input("Input video file or folder [input]: ").strip().strip('"') or "input"
    out_root_raw = input("Output base folder [output]: ").strip().strip('"') or "output"
    in_path = Path(in_raw).resolve()
    videos = scan_input(in_path)

    print(f"Discovered {len(videos)} video(s):")
    for idx, v in enumerate(videos, start=1):
        print(f"  [{idx}] {v['name']} ({v['width']}x{v['height']}, {v['duration']}s)")

    if len(videos) > 1:
        pick_raw = input("Select video number (or 'all') [1]: ").strip().lower() or "1"
        selected = videos if pick_raw == "all" else [videos[int(pick_raw) - 1]]
    else:
        selected = videos

    voice_choice = input("Voice (woman / man) [woman]: ").strip().lower() or "woman"
    rate = input("Speech rate [+20%]: ").strip() or "+20%"
    caption_mode = input("Caption mode (frosted-mask / clean-burn / srt-only) [frosted-mask]: ").strip() or "frosted-mask"

    out_root = Path(out_root_raw).resolve()
    for v in selected:
        vid_path = Path(v["path"])
        stem = vid_path.stem
        default_script = Path("input") / "scripts" / f"{stem}.json"
        prompt_suffix = f" [{default_script}]" if default_script.is_file() else " (blank = extract ruler frames only)"
        script_raw = input(f"Script JSON for {vid_path.name}{prompt_suffix}: ").strip().strip('"')
        script_candidate = Path(script_raw) if script_raw else (default_script if default_script.is_file() else None)

        if script_candidate is None or not script_candidate.is_file():
            ruler_dir = Path("build") / stem / "ruler"
            meta = extract_ruler_frames(vid_path, ruler_dir)
            _write_json(ruler_dir / "ruler.json", meta)
            print(f"No script provided -> ruler frames saved to {ruler_dir}")
            continue

        probed = probe_video(vid_path)
        config = load_config(
            script_path=script_candidate,
            input_video_override=vid_path,
            output_dir_override=out_root / stem,
            build_dir_override=Path("build") / stem,
            voice_override=voice_choice,
            rate_override=rate,
            caption_mode_override=caption_mode,
            probed_meta=probed,
        )
        mp3_map = synthesize_segments(config.segments, config.voice, config.rate, config.build_dir / "tts_mp3")
        fitted, master = fit_and_assemble_audio(config, mp3_map)
        font_name = (
            detect_and_stage_fonts(config.build_dir / "fonts")
            if config.caption_mode != "srt-only"
            else "Myanmar Text"
        )
        _, _, ass_path, _ = write_subtitles_and_script(config, fitted, font_name=font_name)
        out_vid = compose_video(config, master, ass_path)
        ver = verify_output(out_vid, config.build_dir / "qa", source_video=vid_path)
        _write_json(config.build_dir / "verify.json", ver)
        print(f"Done: {out_vid} (checks passed={ver['passed_media_checks']})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="recap",
        description="Myanmar video recap synthesis, audio fitting, subtitling, and verification CLI.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="Scan a single video or input folder (default: ./input).")
    p_scan.add_argument("--input", default="input", help="Input video file or directory (default: input).")
    p_scan.add_argument("--output", default="build/scan.json", help="Output JSON manifest path.")
    p_scan.set_defaults(func=_cmd_scan)

    p_ruler = sub.add_parser("ruler", help="Extract 20px ruler grid frames to measure caption bounds.")
    p_ruler.add_argument("--input", required=True, help="Input video path.")
    p_ruler.add_argument("--output-dir", default=None, help="Directory for ruler PNGs.")
    p_ruler.add_argument("--output", default=None, help="Output JSON metadata path.")
    p_ruler.add_argument("--timestamps", default="", help="Optional comma-separated seconds.")
    p_ruler.set_defaults(func=_cmd_ruler)

    p_meas = sub.add_parser("measure", help="Dry-run TTS synthesis and report slot duration fit.")
    p_meas.add_argument("--script", required=True, help="Path to recap JSON script.")
    p_meas.add_argument("--output", default=None, help="Output JSON measurement report path.")
    p_meas.add_argument("--input-video", default=None, help="Override input video path.")
    p_meas.add_argument("--build-dir", default=None, help="Override build directory.")
    p_meas.add_argument("--voice", default=None, help="Voice preset (woman/man) or Edge voice ID.")
    p_meas.add_argument("--rate", default=None, help="Speech rate (e.g. +20%%).")
    p_meas.set_defaults(func=_cmd_measure)

    p_ren = sub.add_parser("render", help="Synthesize audio, build SRT/ASS, and render final MP4.")
    p_ren.add_argument("--script", required=True, help="Path to recap JSON script.")
    p_ren.add_argument("--output-dir", default=None, help="Target output folder (default: output/<stem>).")
    p_ren.add_argument("--output", default=None, help="Output render manifest JSON path.")
    p_ren.add_argument("--input-video", default=None, help="Override input video path.")
    p_ren.add_argument("--build-dir", default=None, help="Override build directory.")
    p_ren.add_argument("--voice", default=None, help="Voice preset (woman/man) or Edge voice ID.")
    p_ren.add_argument("--rate", default=None, help="Speech rate (e.g. +20%%).")
    p_ren.add_argument("--caption-mode", choices=CAPTION_MODES, default=None, help="Subtitle mask mode.")
    p_ren.add_argument("--band-y", type=int, default=None, help="Frosted mask top Y pixel.")
    p_ren.add_argument("--band-h", type=int, default=None, help="Frosted mask height in pixels.")
    p_ren.set_defaults(func=_cmd_render)

    p_ver = sub.add_parser("verify", help="Verify codecs, loudness, and extract QA PNGs + audio clip.")
    p_ver.add_argument("--video", required=True, help="Rendered MP4 path.")
    p_ver.add_argument("--qa-dir", default=None, help="Directory for QA screenshots and sample MP3.")
    p_ver.add_argument("--output", default=None, help="Output verification JSON path.")
    p_ver.add_argument("--source-video", default=None, help="Optional original MP4 for duration drift check.")
    p_ver.set_defaults(func=_cmd_verify)

    p_wiz = sub.add_parser("wizard", help="Interactive prompt-driven video recap runner.")
    p_wiz.set_defaults(func=_cmd_wizard)

    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1
