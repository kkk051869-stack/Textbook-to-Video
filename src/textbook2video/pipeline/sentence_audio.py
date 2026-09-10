"""Sentence-level audio contracts and offline waveform helpers.

The module intentionally uses only the Python standard library.  Real TTS
backends can provide PCM/WAV bytes, while local tests can exercise the exact
same concatenation and cue logic without downloading a model.
"""

from __future__ import annotations

import hashlib
import io
import json
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class SentenceCue:
    sentence_id: str
    segment_id: int | str
    index: int
    text: str
    start_sec: float
    end_sec: float
    duration_sec: float
    audio_sha256: str | None = None


def sentence_cache_key(
    text: str,
    *,
    backend: str,
    model: str = "",
    prompt_hash: str = "",
    config: dict | None = None,
) -> str:
    """Return a stable cache key including text, model and inference config."""
    payload = {
        "text": str(text),
        "backend": backend,
        "model": model,
        "prompt_hash": prompt_hash,
        "config": config or {},
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def wav_duration(wav_bytes: bytes) -> float:
    """Read duration from WAV bytes without ffmpeg."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as reader:
        frames = reader.getnframes()
        rate = reader.getframerate()
        if rate <= 0:
            raise ValueError("WAV sample rate must be positive")
        return frames / rate


def concat_wav_bytes(waveforms: Iterable[bytes]) -> bytes:
    """Concatenate PCM WAV byte streams in memory.

    All inputs must have matching channels, sample width and sample rate.
    No per-sentence file or ffmpeg process is created.
    """
    items = list(waveforms)
    if not items:
        raise ValueError("no waveforms to concatenate")
    readers = [wave.open(io.BytesIO(item), "rb") for item in items]
    try:
        params = readers[0].getparams()
        for reader in readers[1:]:
            other = reader.getparams()
            if (other.nchannels, other.sampwidth, other.framerate) != (
                params.nchannels, params.sampwidth, params.framerate
            ):
                raise ValueError("WAV parameters do not match")
        frames = b"".join(reader.readframes(reader.getnframes()) for reader in readers)
    finally:
        for reader in readers:
            reader.close()
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(params.nchannels)
        writer.setsampwidth(params.sampwidth)
        writer.setframerate(params.framerate)
        writer.writeframes(frames)
    return output.getvalue()


def build_sentence_cues(
    segment_id: int | str,
    sentences: list[str],
    durations: list[float],
    *,
    audio_hashes: list[str | None] | None = None,
) -> list[SentenceCue]:
    """Build contiguous sentence cues from measured sentence durations."""
    if len(sentences) != len(durations):
        raise ValueError("sentences and durations must have the same length")
    if audio_hashes is not None and len(audio_hashes) != len(sentences):
        raise ValueError("audio_hashes must match sentences length")
    cursor = 0.0
    cues: list[SentenceCue] = []
    for index, (text, duration) in enumerate(zip(sentences, durations), start=1):
        if duration < 0:
            raise ValueError("sentence duration must not be negative")
        end = cursor + float(duration)
        cues.append(
            SentenceCue(
                sentence_id=f"segment-{segment_id}-sentence-{index}",
                segment_id=segment_id,
                index=index,
                text=text,
                start_sec=round(cursor, 3),
                end_sec=round(end, 3),
                duration_sec=round(float(duration), 3),
                audio_sha256=audio_hashes[index - 1] if audio_hashes else None,
            )
        )
        cursor = end
    return cues


def write_sentence_cues(path: str | Path, segments: list[dict]) -> Path:
    """Write the portable sentence cue sidecar used by subtitles and timing."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": "sentence-cues-v1", "segments": segments}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def cue_dicts(cues: Iterable[SentenceCue]) -> list[dict]:
    return [asdict(cue) for cue in cues]

