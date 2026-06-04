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


async def _generate_single(
    text: str,
    output_path: Path,
    voice: str,
    rate: str,
    *,
    retries: int = 2,
) -> Path:
    """生成单段音频，带重试与空文本兜底。

    **永不抛异常**：彻底失败时也返回 output_path（文件可能缺失/0 字节），
    交由下游 get_audio_duration 按 0 时长优雅降级——这样单段失败不会拖垮整批。
    """
    spoken = text.strip() or "（本段暂无旁白）"   # edge-tts 对空文本行为未定义，兜底
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            communicate = edge_tts.Communicate(spoken, voice=voice, rate=rate)
            await communicate.save(str(output_path))
            size = output_path.stat().st_size
            if size == 0:
                raise RuntimeError("生成音频为 0 字节")
            print(f"OK: {output_path.name} ({size:,} bytes)")
            return output_path
        except Exception as exc:  # noqa: BLE001 — 网络/TTS 各类异常都要容忍
            last_err = exc
            if attempt < retries:
                await asyncio.sleep(1.5)
    print(
        f"⚠️ {output_path.name} 配音失败（试 {retries + 1} 次）: "
        f"{type(last_err).__name__}: {last_err}；该段将无声，画面按默认时长展示"
    )
    return output_path


def generate_audio(
    segments: list[str],
    *,
    output_dir: str = "output",
    voice: str = "zh-CN-XiaoxiaoNeural",
    rate: str = "+5%",
) -> list[Path]:
    """
    批量生成讲稿音频。

    每段对应一个音频文件 sN.mp3，**按段序返回、长度恒等于输入段数**；
    个别段失败不影响其余段（失败段返回的路径可能不存在/0 字节）。

    Args:
        segments: 讲稿文本列表，每段对应一个音频文件
        output_dir: 输出目录
        voice: edge-tts 语音名称
        rate: 语速调整（如 "+5%"）

    Returns:
        生成的音频文件路径列表（与 segments 一一对应、同序）
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    async def _run_all():
        tasks = []
        for i, text in enumerate(segments):
            out_path = output_dir / f"s{i + 1}.mp3"
            tasks.append(_generate_single(text, out_path, voice, rate))
        # _generate_single 自身已吞掉异常，这里 return_exceptions 作为双保险
        return await asyncio.gather(*tasks, return_exceptions=True)

    raw = asyncio.run(_run_all())
    # 把任何漏网异常映射回对应的 sN 路径，保证返回长度 == 段数、且同序
    results: list[Path] = []
    for i, r in enumerate(raw):
        if isinstance(r, Path):
            results.append(r)
        else:
            fallback = output_dir / f"s{i + 1}.mp3"
            print(f"⚠️ 第 {i + 1} 段配音异常: {type(r).__name__}: {r}")
            results.append(fallback)
    ok = sum(1 for p in results if p.exists() and p.stat().st_size > 0)
    print(f"完成: {ok}/{len(results)} 段成功配音")
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
