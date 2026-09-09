"""
TTS 配音模块：讲稿文本 → 音频文件

当前后端：edge-tts（免费，质量可接受）
规划后端：Fish Audio / CosyVoice

用法：
  from textbook2video.pipeline.narrator import generate_audio
  segments = generate_audio(["第一段讲稿", "第二段讲稿"], output_dir="output/audio/")
"""

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import edge_tts
except ImportError:  # Optional when an isolated local TTS backend is selected.
    edge_tts = None


_ABBREVIATION_PRONUNCIATIONS = {
    "CPU": "C P U",
    "GPU": "G P U",
    "NPU": "N P U",
    "AI": "A I",
}


def normalize_tts_text(text: str) -> str:
    """Make common technical abbreviations unambiguous to Chinese TTS engines.

    This transformation is deliberately applied only to the spoken narration.
    Storyboard and HTML text continue to display the original abbreviations.
    """
    normalized = str(text or "")
    for abbreviation, spoken in _ABBREVIATION_PRONUNCIATIONS.items():
        normalized = re.sub(
            rf"(?<![A-Za-z0-9]){abbreviation}(?![A-Za-z0-9])",
            spoken,
            normalized,
        )
    return normalized


def _wav_paths(output_dir: Path, count: int) -> list[Path]:
    return [output_dir / f"s{i + 1}.wav" for i in range(count)]


def _generate_cosyvoice(
    segments: list[str],
    output_dir: Path,
    rate: str,
) -> list[Path]:
    """Generate a batch with CosyVoice in its isolated Python environment."""
    outputs = _wav_paths(output_dir, len(segments))
    python = os.getenv("T2V_COSYVOICE_PYTHON", "/ai/data/tools/envs/cosyvoice3/bin/python")
    cosyvoice_root = Path(os.getenv("T2V_COSYVOICE_ROOT", "/ai/data/tools/CosyVoice"))
    runner = Path(__file__).with_name("cosyvoice_runner.py")
    env = os.environ.copy()
    matcha_root = cosyvoice_root / "third_party" / "Matcha-TTS"
    env["PYTHONPATH"] = os.pathsep.join(
        value
        for value in (str(cosyvoice_root), str(matcha_root), env.get("PYTHONPATH", ""))
        if value
    )
    request = {
        "segments": [normalize_tts_text(text).strip() or "（本段暂无旁白）" for text in segments],
        "output_dir": str(output_dir.resolve()),
        "rate": rate,
        "model_dir": os.getenv(
            "T2V_COSYVOICE_MODEL", "/ai/data/models/Fun-CosyVoice3-0.5B-2512"
        ),
        "prompt_wav": os.getenv(
            "T2V_COSYVOICE_PROMPT_WAV",
            str(cosyvoice_root / "asset" / "zero_shot_prompt.wav"),
        ),
        "prompt_text": os.getenv(
            "T2V_COSYVOICE_PROMPT_TEXT",
            "You are a helpful assistant.<|endofprompt|>希望你以后能够做的比我还好呦。",
        ),
    }
    try:
        subprocess.run(
            [python, str(runner)],
            input=json.dumps(request, ensure_ascii=False),
            text=True,
            encoding="utf-8",
            env=env,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"CosyVoice batch failed: {type(exc).__name__}: {exc}")
    ok = sum(path.exists() and path.stat().st_size > 0 for path in outputs)
    print(f"CosyVoice completed: {ok}/{len(outputs)} segment(s)")
    return outputs


def _generate_megatts3(segments: list[str], output_dir: Path) -> list[Path]:
    """Generate a batch with MegaTTS3 in its isolated Python environment."""
    outputs = _wav_paths(output_dir, len(segments))
    python = os.getenv("T2V_MEGATTS3_PYTHON", "/ai/data/tools/envs/cosyvoice3/bin/python")
    megatts3_root = Path(
        os.getenv("T2V_MEGATTS3_ROOT", "/ai/data/repos/PresentAgent/presentagent/MegaTTS3")
    )
    runner = Path(__file__).with_name("megatts3_runner.py")
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(megatts3_root), env.get("PYTHONPATH", "")) if value
    )
    bundled_tools = Path(sys.executable).parent
    env["PATH"] = os.pathsep.join(
        value
        for value in (str(Path(python).parent), str(bundled_tools), env.get("PATH", ""))
        if value
    )
    device = os.getenv("T2V_MEGATTS3_DEVICE", "").strip().lower()
    if device == "cpu":
        env["CUDA_VISIBLE_DEVICES"] = ""
    request = {
        "segments": [normalize_tts_text(text).strip() or "本段暂无旁白。" for text in segments],
        "output_dir": str(output_dir.resolve()),
        "megatts3_root": str(megatts3_root),
        "prompt_wav": os.getenv(
            "T2V_MEGATTS3_PROMPT_WAV",
            str(megatts3_root / "assets" / "Chinese_prompt.wav"),
        ),
        "prompt_latent": os.getenv("T2V_MEGATTS3_PROMPT_LATENT", ""),
        "time_step": int(os.getenv("T2V_MEGATTS3_TIME_STEP", "24")),
        "p_w": float(os.getenv("T2V_MEGATTS3_P_W", "2.0")),
        "t_w": float(os.getenv("T2V_MEGATTS3_T_W", "2.5")),
        "device": device,
    }
    try:
        subprocess.run(
            [python, str(runner)],
            input=json.dumps(request, ensure_ascii=False),
            text=True,
            encoding="utf-8",
            env=env,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"MegaTTS3 batch failed: {type(exc).__name__}: {exc}")
    ok = sum(path.exists() and path.stat().st_size > 0 for path in outputs)
    print(f"MegaTTS3 completed: {ok}/{len(outputs)} segment(s)")
    return outputs


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
    spoken = normalize_tts_text(text).strip() or "（本段暂无旁白）"
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
    backend: str | None = None,
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
        backend: edge、cosyvoice3 或 megatts3；默认读取 T2V_TTS_BACKEND

    Returns:
        生成的音频文件路径列表（与 segments 一一对应、同序）
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    selected_backend = (backend or os.getenv("T2V_TTS_BACKEND", "edge")).strip().lower()
    if selected_backend in {"cosyvoice", "cosyvoice3"}:
        return _generate_cosyvoice(segments, output_dir, rate)
    if selected_backend in {"mega", "megatts", "megatts3"}:
        return _generate_megatts3(segments, output_dir)
    if selected_backend != "edge":
        raise ValueError(f"Unsupported TTS backend: {selected_backend}")
    if edge_tts is None:
        raise RuntimeError("edge_tts is required only for the edge TTS backend")

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

    bundled_ffmpeg = Path(sys.executable).with_name("ffmpeg")
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None and bundled_ffmpeg.is_file():
        ffmpeg = str(bundled_ffmpeg)
    ffmpeg = ffmpeg or "ffmpeg"
    result = sp.run(
        [ffmpeg, "-i", str(audio_path)],
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
