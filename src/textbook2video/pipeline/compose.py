"""音画合成：把分段 TTS 音频拼接成完整音轨，再 mux 到录制好的视频上。

设计要点（与"音频先行"架构对齐）：
  - 每段讲稿对应一个音频文件 sN.mp3（见 narrator.generate_audio 命名）。
  - animate 把每段 audio_duration_sec 注入 HTML 的 slideDurations，recorder 据此
    逐页翻页并录满总时长。因此**按 segment 顺序拼接音频**得到的音轨长度 ≈ 视频长度，
    且每页画面与其旁白天然对齐——不需要逐页精确对齐，顺序拼接即可。
  - 最终 mux：视频流直接 copy（不重编码），音频转 aac。

录制产物默认无声（recorder 只转码画面），本模块补上最后这一步。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

__all__ = [
    "find_segment_audio",
    "concat_audio",
    "mux_audio_video",
    "compose_video",
]


def find_segment_audio(audio_dir: str | Path) -> list[Path]:
    """返回音频目录下按段号升序排列的 sN.* 文件列表。

    命名约定见 narrator.generate_audio：s1.mp3, s2.mp3, ...
    按 N 的数值排序（避免 s10 排到 s2 前面的字典序错误）。
    """
    audio_dir = Path(audio_dir)
    if not audio_dir.is_dir():
        raise FileNotFoundError(f"音频目录不存在: {audio_dir}")

    indexed: list[tuple[int, Path]] = []
    for f in audio_dir.iterdir():
        m = re.fullmatch(r"s(\d+)", f.stem, flags=re.IGNORECASE)
        if m and f.is_file():
            indexed.append((int(m.group(1)), f))
    indexed.sort(key=lambda t: t[0])
    return [p for _, p in indexed]


def concat_audio(audio_files: list[str | Path], out_path: str | Path) -> Path:
    """按给定顺序无缝拼接音频为单个文件（ffmpeg concat demuxer，逐段重编码为统一格式）。

    用重编码而非 -c copy：分段音频可能编码参数不一致，stream copy 拼接易出错；
    教学视频音轨重编码代价可忽略。
    """
    files = [Path(f) for f in audio_files]
    if not files:
        raise ValueError("没有可拼接的音频文件")
    missing = [str(f) for f in files if not f.exists()]
    if missing:
        raise FileNotFoundError(f"音频文件缺失: {', '.join(missing)}")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 用 concat demuxer：写一个清单文件，ffmpeg 顺序读取
    list_path = out_path.with_suffix(".concat.txt")
    lines = []
    for f in files:
        # concat 清单要求路径转义单引号
        safe = str(f.resolve()).replace("'", "'\\''")
        lines.append(f"file '{safe}'")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", str(list_path),
                "-c:a", "aac", "-b:a", "192k",
                str(out_path),
            ],
            check=True,
            capture_output=True,
        )
    finally:
        list_path.unlink(missing_ok=True)
    return out_path


def mux_audio_video(
    video_path: str | Path,
    audio_path: str | Path,
    out_path: str | Path,
) -> Path:
    """把音轨合成到视频上：视频流 copy，音频转 aac，时长取较短者对齐。"""
    video_path, audio_path, out_path = Path(video_path), Path(audio_path), Path(out_path)
    for p in (video_path, audio_path):
        if not p.exists():
            raise FileNotFoundError(f"文件不存在: {p}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-map", "0:v:0", "-map", "1:a:0",
            "-shortest",
            "-movflags", "+faststart",
            str(out_path),
        ],
        check=True,
        capture_output=True,
    )
    return out_path


def compose_video(
    video_path: str | Path,
    audio_dir: str | Path,
    out_path: str | Path,
) -> Path:
    """一步合成：从音频目录按段拼接 → mux 到视频 → 输出有声成片。

    中间拼接的整段音轨写到 out_path 同级的 .<stem>.fulltrack.m4a（合成后删除）。
    """
    out_path = Path(out_path)
    audio_files = find_segment_audio(audio_dir)
    if not audio_files:
        raise FileNotFoundError(f"音频目录中未找到 sN.mp3 分段音频: {audio_dir}")

    track_path = out_path.parent / f".{out_path.stem}.fulltrack.m4a"
    try:
        concat_audio(audio_files, track_path)
        mux_audio_video(video_path, track_path, out_path)
    finally:
        track_path.unlink(missing_ok=True)
    return out_path
