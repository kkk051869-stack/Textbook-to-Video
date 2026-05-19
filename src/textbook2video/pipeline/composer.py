"""
音视频合成模块：拼接音频 + 合并音视频

用法：
  from textbook2video.pipeline.composer import concat_audio, merge_audio_video
  full_audio = concat_audio(["s1.mp3", "s2.mp3"], output="full.mp3")
  merge_audio_video("video.mp4", "full.mp3", output="final.mp4")
"""

import subprocess
from pathlib import Path


def concat_audio(audio_files: list[str], *, output: str = "output/full.mp3") -> Path:
    """
    拼接多段音频为一个文件。

    Args:
        audio_files: 音频文件路径列表
        output: 输出文件路径

    Returns:
        合并后的音频文件路径
    """
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    # 生成 ffmpeg concat 列表
    concat_list = output.with_suffix(".txt")
    with open(concat_list, "w", encoding="utf-8") as f:
        for seg in audio_files:
            f.write(f"file '{Path(seg).resolve()}'\n")

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(output),
        ],
        check=True,
        capture_output=True,
    )

    concat_list.unlink(missing_ok=True)
    print(f"合并音频: {output} ({output.stat().st_size:,} bytes)")
    return output


def merge_audio_video(
    video_path: str,
    audio_path: str,
    *,
    output: str = "output/final.mp4",
) -> Path:
    """
    合并无声视频和音频轨道。

    Args:
        video_path: 视频文件路径（无音轨或将被替换）
        audio_path: 音频文件路径
        output: 输出文件路径

    Returns:
        合并后的视频文件路径
    """
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(audio_path),
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(output),
        ],
        check=True,
        capture_output=True,
    )

    print(f"最终视频: {output} ({output.stat().st_size:,} bytes)")
    return output
