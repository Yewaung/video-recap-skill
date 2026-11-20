"""Microsoft Edge Neural TTS adapter with monotonic rate limiting, retries, and caching."""

from __future__ import annotations

import asyncio
import hashlib
import re
import sys
import time
from pathlib import Path

import edge_tts

from recap_pipeline.domain.models import SegmentSpec, ValidationError

_RATE_PATTERN = re.compile(r"^[+-]\d{1,3}%$")


class _MonotonicRateLimiter:
    """Async pace limiter ensuring Edge TTS requests stay spaced apart via time.monotonic()."""

    def __init__(self, min_interval_sec: float = 0.35) -> None:
        self._min_interval = min_interval_sec
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()


def _cache_digest(voice: str, rate: str, text: str) -> str:
    payload = f"{voice}|{rate}|{text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12]


async def _synthesize_one(
    seg: SegmentSpec,
    voice: str,
    rate: str,
    out_dir: Path,
    semaphore: asyncio.Semaphore,
    limiter: _MonotonicRateLimiter,
    max_retries: int = 3,
) -> Path:
    digest = _cache_digest(voice, rate, seg.mm)
    mp3_path = out_dir / f"seg_{seg.id:02d}_{digest}.mp3"

    if mp3_path.is_file() and mp3_path.stat().st_size > 256:
        return mp3_path

    for old_file in out_dir.glob(f"seg_{seg.id:02d}_*.mp3"):
        old_file.unlink(missing_ok=True)

    last_exc: Exception | None = None
    async with semaphore:
        for attempt in range(max_retries):
            await limiter.acquire()
            try:
                communicate = edge_tts.Communicate(text=seg.mm, voice=voice, rate=rate)
                await communicate.save(str(mp3_path))
                if mp3_path.is_file() and mp3_path.stat().st_size > 256:
                    return mp3_path
                raise RuntimeError(f"Empty audio produced for segment {seg.id}")
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                mp3_path.unlink(missing_ok=True)
                if attempt + 1 < max_retries:
                    delay = 1.5 * (2**attempt)
                    print(
                        f"[tts retry {attempt + 1}/{max_retries - 1}] segment {seg.id}: {exc} (waiting {delay:.1f}s)",
                        file=sys.stderr,
                    )
                    await asyncio.sleep(delay)

    raise RuntimeError(
        f"TTS synthesis failed for segment {seg.id} ({voice}, {rate}) after {max_retries} attempts: {last_exc}"
    ) from last_exc


async def _synthesize_all_async(
    segments: tuple[SegmentSpec, ...],
    voice: str,
    rate: str,
    out_dir: Path,
    concurrency: int = 3,
    min_interval_sec: float = 0.35,
) -> dict[int, Path]:
    semaphore = asyncio.Semaphore(concurrency)
    limiter = _MonotonicRateLimiter(min_interval_sec=min_interval_sec)
    tasks = [
        _synthesize_one(
            seg=seg,
            voice=voice,
            rate=rate,
            out_dir=out_dir,
            semaphore=semaphore,
            limiter=limiter,
        )
        for seg in segments
    ]
    results = await asyncio.gather(*tasks)
    return {seg.id: path for seg, path in zip(segments, results, strict=True)}


def synthesize_segments(
    segments: tuple[SegmentSpec, ...],
    voice: str,
    rate: str,
    out_dir: Path,
) -> dict[int, Path]:
    """Synthesize all segments via Edge Neural TTS with rate limiting and content-hash cache."""
    if not voice.strip():
        raise ValidationError("TTS voice cannot be empty.")
    if not _RATE_PATTERN.match(rate):
        raise ValidationError(f"Invalid TTS rate '{rate}', expected format like '+20%'.")

    out_dir.mkdir(parents=True, exist_ok=True)
    return asyncio.run(_synthesize_all_async(segments, voice, rate, out_dir))
