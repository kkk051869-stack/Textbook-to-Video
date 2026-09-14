"""Generate approximate sentence-level SRT subtitles from storyboard JSON.

The first subtitle pass deliberately stays independent from the TTS engine:
each storyboard segment already has narration text and measured audio duration,
so we split the narration into readable chunks and distribute the segment time
by text length. This gives stable sentence-level alignment without word-boundary
support from the TTS backend.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "SubtitleCue",
    "build_subtitle_cues",
    "format_srt_timestamp",
    "generate_srt",
    "load_storyboard",
    "SentenceSplitter",
]


@dataclass(frozen=True)
class SubtitleCue:
    index: int
    start_sec: float
    end_sec: float
    text: str
    sentence_id: str | None = None
    sentence_index: int | None = None


class SentenceSplitter:
    """Stable narration sentence splitter shared by TTS and subtitle layers."""

    def split(self, text: str) -> list[str]:
        cleaned = _clean_narration(text)
        if not cleaned:
            return []
        return _regex_chunks(cleaned, _SENTENCE_END_RE)


_SENTENCE_END_RE = re.compile(r"([^。！？!?；;\n]+[。！？!?；;]?)")
_SOFT_BREAK_RE = re.compile(r"([^，,、：:]+[，,、：:]?)")
_MARKDOWN_PREFIX_RE = re.compile(r"^\s*#{1,6}\s*")


def load_storyboard(path: str | Path) -> dict[str, Any]:
    """Read a storyboard JSON file."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _clean_narration(text: Any) -> str:
    text = str(text or "")
    text = _MARKDOWN_PREFIX_RE.sub("", text.strip())
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _visible_len(text: str) -> int:
    """Approximate spoken length, ignoring whitespace and most punctuation."""
    chars = re.sub(r"[\s，,。！？!?；;：:、“”\"'‘’（）()《》<>【】\[\]#*_`~\-]", "", text)
    return max(1, len(chars))


def _regex_chunks(text: str, pattern: re.Pattern[str]) -> list[str]:
    chunks = [m.group(1).strip() for m in pattern.finditer(text) if m.group(1).strip()]
    return chunks or ([text.strip()] if text.strip() else [])


def _split_by_length(text: str, max_chars: int) -> list[str]:
    if _visible_len(text) <= max_chars:
        return [text]

    pieces: list[str] = []
    current = ""
    for char in text:
        current += char
        if _visible_len(current) >= max_chars and char not in "，,、：:":
            pieces.append(current.strip())
            current = ""
    if current.strip():
        pieces.append(current.strip())
    return pieces


def split_narration(text: str, *, max_chars: int = 28) -> list[str]:
    """Split narration into subtitle-sized sentence chunks."""
    text = _clean_narration(text)
    if not text:
        return []

    chunks: list[str] = []
    for sentence in _regex_chunks(text, _SENTENCE_END_RE):
        if _visible_len(sentence) <= max_chars:
            chunks.append(sentence)
            continue
        for phrase in _regex_chunks(sentence, _SOFT_BREAK_RE):
            chunks.extend(_split_by_length(phrase, max_chars))
    return [c for c in chunks if c.strip()]


def _duration_for_chunk(
    chunk_len: int,
    total_len: int,
    segment_duration: float,
    *,
    min_sec: float,
) -> float:
    raw = segment_duration * (chunk_len / max(1, total_len))
    return max(min_sec, raw)


def _is_positive_duration(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _materialize_real_cue(
    cue: dict[str, Any], *, index: int, offset_sec: float = 0.0
) -> SubtitleCue | None:
    start = float(cue.get("start_sec", cue.get("start", 0.0)))
    end = float(cue.get("end_sec", cue.get("end", 0.0)))
    if end < start:
        return None
    return SubtitleCue(
        index=index,
        start_sec=offset_sec + start,
        end_sec=offset_sec + end,
        text=str(cue.get("text", "")),
        sentence_id=(
            str(cue.get("sentence_id") or cue.get("id"))
            if cue.get("sentence_id") or cue.get("id")
            else f"sentence_{index}"
        ),
        sentence_index=(
            int(cue["index"])
            if isinstance(cue.get("index"), (int, float))
            and not isinstance(cue.get("index"), bool)
            else index
        ),
    )


def build_subtitle_cues(
    storyboard: dict[str, Any],
    *,
    max_chars: int = 28,
    min_cue_sec: float = 0.8,
    sentence_cues: dict[str, Any] | list[dict[str, Any]] | None = None,
) -> list[SubtitleCue]:
    """Build sentence-level cues from storyboard segments.

    Timings are exact at segment boundaries and approximate within each segment.
    If a segment is short, the min cue duration is relaxed so cues still fit.
    """
    segments = storyboard.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("storyboard must contain a non-empty segments list")

    # Prefer measured sentence-level timing when a sidecar is available.  The
    # sidecar stores each segment on a local clock; SRT is global, so add the
    # preceding segment durations while preserving local clocks for timing.py.
    if isinstance(sentence_cues, dict) and isinstance(sentence_cues.get("segments"), list):
        groups_by_segment = {
            str(group.get("segment_id")): group
            for group in sentence_cues.get("segments", [])
            if isinstance(group, dict)
        }
        if groups_by_segment:
            measured: list[SubtitleCue] = []
            cursor = 0.0
            cue_index = 1
            for seg_index, segment in enumerate(segments, start=1):
                if not isinstance(segment, dict):
                    raise ValueError(f"segments[{seg_index}] must be an object")
                group = groups_by_segment.get(str(segment.get("id", seg_index)))
                group_cues = (
                    [cue for cue in group.get("cues", []) if isinstance(cue, dict)]
                    if group
                    else []
                )
                valid_group_cues: list[SubtitleCue] = []
                for cue in group_cues:
                    materialized = _materialize_real_cue(
                        cue, index=cue_index, offset_sec=cursor
                    )
                    if materialized is not None:
                        valid_group_cues.append(materialized)
                        cue_index += 1
                if valid_group_cues:
                    measured.extend(valid_group_cues)
                else:
                    # A partial sidecar should not make later segments overlap
                    # or disappear from the subtitle track.
                    approximate = build_subtitle_cues(
                        {"segments": [segment]},
                        max_chars=max_chars,
                        min_cue_sec=min_cue_sec,
                    )
                    for cue in approximate:
                        measured.append(
                            SubtitleCue(
                                index=cue_index,
                                start_sec=cursor + cue.start_sec,
                                end_sec=cursor + cue.end_sec,
                                text=cue.text,
                                sentence_id=cue.sentence_id,
                                sentence_index=cue.sentence_index,
                            )
                        )
                        cue_index += 1
                duration = segment.get("audio_duration_sec")
                if not _is_positive_duration(duration):
                    duration = group.get("duration_sec") if group else None
                if not _is_positive_duration(duration):
                    duration = max(
                        (cue.end_sec - cursor for cue in valid_group_cues),
                        default=0.0,
                    )
                cursor += float(duration)
            if measured:
                return measured

    real_cues: list[dict[str, Any]] = (
        [cue for cue in sentence_cues if isinstance(cue, dict)]
        if isinstance(sentence_cues, list)
        else []
    )
    if real_cues:
        return [
            materialized
            for index, cue in enumerate(real_cues, start=1)
            if (materialized := _materialize_real_cue(cue, index=index)) is not None
        ]

    cues: list[SubtitleCue] = []
    cursor = 0.0
    cue_index = 1

    for seg_index, seg in enumerate(segments, start=1):
        if not isinstance(seg, dict):
            raise ValueError(f"segments[{seg_index}] must be an object")

        duration = seg.get("audio_duration_sec")
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
            raise ValueError(
                f"segment {seg.get('id', seg_index)} audio_duration_sec must be positive"
            )

        chunks = split_narration(str(seg.get("narration", "")), max_chars=max_chars)
        if not chunks:
            cursor += float(duration)
            continue

        total_len = sum(_visible_len(chunk) for chunk in chunks)
        segment_start = cursor
        segment_end = segment_start + float(duration)
        local_cursor = segment_start

        relaxed_min = min(min_cue_sec, float(duration) / max(1, len(chunks)))
        allocated: list[float] = [
            _duration_for_chunk(
                _visible_len(chunk), total_len, float(duration), min_sec=relaxed_min
            )
            for chunk in chunks
        ]
        scale = float(duration) / sum(allocated)

        for i, chunk in enumerate(chunks):
            if i == len(chunks) - 1:
                end = segment_end
            else:
                end = min(segment_end, local_cursor + allocated[i] * scale)
            cues.append(
                SubtitleCue(
                    cue_index,
                    local_cursor,
                    end,
                    chunk,
                    sentence_id=f"sentence_{cue_index}",
                    sentence_index=cue_index,
                )
            )
            cue_index += 1
            local_cursor = end

        cursor = segment_end

    return cues


def format_srt_timestamp(seconds: float) -> str:
    """Format seconds as SRT timestamp: HH:MM:SS,mmm."""
    ms_total = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(ms_total, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _format_srt(cues: list[SubtitleCue]) -> str:
    blocks = []
    for cue in cues:
        blocks.append(
            "\n".join(
                [
                    str(cue.index),
                    f"{format_srt_timestamp(cue.start_sec)} --> "
                    f"{format_srt_timestamp(cue.end_sec)}",
                    cue.text,
                ]
            )
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def generate_srt(
    storyboard: dict[str, Any] | str | Path,
    out_path: str | Path,
    *,
    max_chars: int = 28,
    sentence_cues: dict[str, Any] | list[dict[str, Any]] | None = None,
) -> Path:
    """Generate an SRT file from a storyboard dict or path."""
    data = load_storyboard(storyboard) if isinstance(storyboard, (str, Path)) else storyboard
    cues = build_subtitle_cues(data, max_chars=max_chars, sentence_cues=sentence_cues)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_format_srt(cues), encoding="utf-8")
    return out
