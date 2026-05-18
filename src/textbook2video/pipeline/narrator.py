"""
TTS 配音模块：讲稿文本 → 音频文件

当前后端：edge-tts（免费，质量可接受）
规划后端：Fish Audio / CosyVoice

用法：
  from textbook2video.pipeline.narrator import generate_audio
  segments = generate_audio(["第一段讲稿", "第二段讲稿"], output_dir="output/audio/")
"""

import asyncio
from pathlib import Path

import edge_tts


async def _generate_single(text: str, output_path: Path, voice: str, rate: str) -> Path:
    """生成单段音频"""
    communicate = edge_tts.Communicate(text, voice=voice, rate=rate)
    await communicate.save(str(output_path))
    size = output_path.stat().st_size
    print(f"OK: {output_path.name} ({size:,} bytes)")
    return output_path


def generate_audio(
    segments: list[str],
    *,
    output_dir: str = "output",
    voice: str = "zh-CN-XiaoyiNeural",
    rate: str = "+5%",
) -> list[Path]:
    """
    批量生成讲稿音频。

    Args:
        segments: 讲稿文本列表，每段对应一个音频文件
        output_dir: 输出目录
        voice: edge-tts 语音名称
        rate: 语速调整（如 "+5%"）

    Returns:
        生成的音频文件路径列表
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    async def _run_all():
        tasks = []
        for i, text in enumerate(segments):
            out_path = output_dir / f"s{i + 1}.mp3"
            tasks.append(_generate_single(text, out_path, voice, rate))
        return await asyncio.gather(*tasks)

    results = asyncio.run(_run_all())
    print(f"全部完成: {len(results)} 段音频")
    return results


def get_audio_duration(audio_path: str) -> float:
    """获取音频文件时长（秒），需要 ffmpeg"""
    import subprocess as sp

    result = sp.run(
        ["ffmpeg", "-i", str(audio_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    for line in result.stderr.split("\n"):
        if "Duration:" in line:
            time_str = line.strip().split("Duration: ")[1].split(",")[0].strip()
            h, m, s = time_str.split(":")
            return float(h) * 3600 + float(m) * 60 + float(s)
    raise ValueError(f"无法获取 {audio_path} 的时长")
