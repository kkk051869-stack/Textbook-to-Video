"""
TTS 配音模块：讲稿文本 → 音频文件

当前后端：edge-tts（免费，质量可接受）
规划后端：Fish Audio / CosyVoice

用法：
  from textbook2video.pipeline.narrator import generate_audio
  segments = generate_audio(["第一段讲稿", "第二段讲稿"], output_dir="output/audio/")
"""

import asyncio
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from textbook2video.pipeline.sentence_audio import (
    build_sentence_cues,
    concat_wav_bytes,
    wav_duration,
    write_sentence_cues,
)

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


def _resolve_ffmpeg() -> str | None:
    """Resolve ffmpeg from PATH, the Python runtime, or imageio-ffmpeg."""
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    for name in ("ffmpeg", "ffmpeg.exe"):
        bundled = Path(sys.executable).with_name(name)
        if bundled.is_file():
            return str(bundled)
    try:
        import imageio_ffmpeg

        candidate = Path(imageio_ffmpeg.get_ffmpeg_exe())
        if candidate.is_file():
            return str(candidate)
    except (ImportError, RuntimeError, OSError):
        pass
    return None


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
            timeout=float(os.getenv("T2V_MEGATTS3_TIMEOUT_SEC", "1800")),
        )
    except subprocess.TimeoutExpired as exc:
        print(f"MegaTTS3 batch timed out after {exc.timeout}s")
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"MegaTTS3 batch failed: {type(exc).__name__}: {exc}")
    ok = sum(path.exists() and path.stat().st_size > 0 for path in outputs)
    print(f"MegaTTS3 completed: {ok}/{len(outputs)} segment(s)")
    return outputs


def _sapi_rate(rate: str) -> int:
    """Map the public percentage rate to System.Speech's -10..10 scale."""
    value = str(rate or "0").strip()
    match = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)%?", value)
    if not match:
        raise ValueError(f"invalid SAPI speech rate: {rate}")
    percent = float(match.group(1))
    scaled = math.copysign(math.floor(abs(percent) / 10.0 + 0.5), percent)
    return max(-10, min(10, int(scaled)))


def _generate_sapi(
    segments: list[str],
    output_dir: Path,
    voice: str,
    rate: str,
) -> list[Path]:
    """Generate local WAV files through Windows System.Speech."""
    if os.name != "nt":
        raise RuntimeError("the SAPI TTS backend is available only on Windows")
    powershell = shutil.which("powershell") or shutil.which("powershell.exe")
    if powershell is None:
        raise RuntimeError("PowerShell is required for the SAPI TTS backend")
    runner = Path(__file__).with_name("sapi_tts_runner.ps1")
    request = {
        "segments": [normalize_tts_text(text).strip() or "（本段暂无旁白）" for text in segments],
        "output_dir": str(output_dir.resolve()),
        "voice": voice,
        "rate": _sapi_rate(rate),
    }
    try:
        subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(runner),
            ],
            input=json.dumps(request, ensure_ascii=False),
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError(f"SAPI TTS batch failed: {detail}") from exc
    outputs = _wav_paths(output_dir, len(segments))
    missing = [path.name for path in outputs if not path.is_file() or path.stat().st_size == 0]
    if missing:
        raise RuntimeError(f"SAPI TTS output missing: {', '.join(missing)}")
    print(f"SAPI completed: {len(outputs)}/{len(outputs)} segment(s)")
    return outputs


def generate_sentence_audio(
    sentence_groups: list[list[str]],
    *,
    output_dir: str | Path,
    backend: str = "megatts3",
    segment_ids: list[int | str] | None = None,
    voice: str = "zh-CN-XiaoxiaoNeural",
    rate: str = "+5%",
) -> dict:
    """Generate sentence-addressable audio and persist measured cue boundaries.

    MegaTTS3 and SAPI emit WAV files that are concatenated losslessly in memory.  Edge
    TTS emits MP3, so sentences are generated in a temporary directory and
    joined with ffmpeg's concat demuxer.  In both cases cue boundaries come
    from measured sentence files, never from character-count estimates.
    """
    backend = backend.strip().lower()
    if backend not in {"edge", "sapi", "mega", "megatts", "megatts3"}:
        raise ValueError("sentence audio requires the edge, sapi, or MegaTTS3 backend")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if segment_ids is not None and len(segment_ids) != len(sentence_groups):
        raise ValueError("segment_ids must match sentence_groups length")
    resolved_segment_ids = segment_ids or list(range(1, len(sentence_groups) + 1))
    sentences = [sentence for group in sentence_groups for sentence in group]
    if not sentences:
        raise ValueError("sentence_groups must contain at least one sentence")
    with tempfile.TemporaryDirectory(prefix=".sentence_tts_", dir=output_dir) as temp:
        temp_dir = Path(temp)
        if backend == "edge":
            if edge_tts is None:
                raise RuntimeError("edge_tts is required for sentence-level Edge TTS")

            async def _run_edge_sentences() -> list[Path]:
                tasks = [
                    _generate_single(
                        sentence,
                        temp_dir / f"sentence-{index:04d}.mp3",
                        voice,
                        rate,
                    )
                    for index, sentence in enumerate(sentences, start=1)
                ]
                return list(await asyncio.gather(*tasks))

            generated = asyncio.run(_run_edge_sentences())
        elif backend == "sapi":
            generated = _generate_sapi(sentences, temp_dir, voice, rate)
        else:
            generated = _generate_megatts3(sentences, temp_dir)
        cursor = 0
        groups_meta = []
        for segment_index, group in enumerate(sentence_groups, start=1):
            blobs, durations, sentence_paths = [], [], []
            for _ in group:
                path = Path(generated[cursor])
                cursor += 1
                if not path.exists() or path.stat().st_size == 0:
                    raise RuntimeError(f"sentence TTS output missing: {path.name}")
                blob = path.read_bytes()
                blobs.append(blob)
                sentence_paths.append(path)
                durations.append(
                    get_audio_duration(str(path)) if backend == "edge" else wav_duration(blob)
                )
            if backend == "edge":
                segment_path = output_dir / f"s{segment_index}.mp3"
                if len(sentence_paths) == 1:
                    shutil.copy2(sentence_paths[0], segment_path)
                else:
                    ffmpeg = _resolve_ffmpeg()
                    if ffmpeg is None:
                        raise RuntimeError(
                            "ffmpeg is required to concatenate sentence-level Edge TTS audio"
                        )
                    concat_file = temp_dir / f"segment-{segment_index:04d}.txt"
                    concat_file.write_text(
                        "".join(
                            f"file '{path.resolve().as_posix().replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n"
                            for path in sentence_paths
                        ),
                        encoding="utf-8",
                    )
                    subprocess.run(
                        [
                            ffmpeg,
                            "-y",
                            "-f",
                            "concat",
                            "-safe",
                            "0",
                            "-i",
                            str(concat_file),
                            "-c",
                            "copy",
                            str(segment_path),
                        ],
                        check=True,
                        capture_output=True,
                    )
            else:
                merged = concat_wav_bytes(blobs)
                segment_path = output_dir / f"s{segment_index}.wav"
                segment_path.write_bytes(merged)
            cues = build_sentence_cues(
                resolved_segment_ids[segment_index - 1],
                group,
                durations,
                audio_hashes=[hashlib.sha256(blob).hexdigest() for blob in blobs],
            )
            groups_meta.append({
                "segment_id": resolved_segment_ids[segment_index - 1],
                "audio_path": segment_path.name,
                "duration_sec": round(sum(durations), 3),
                "cues": [cue.__dict__ for cue in cues],
            })
    sidecar = write_sentence_cues(output_dir / "sentence_cues.json", groups_meta)
    return {
        "audio_files": [
            output_dir / f"s{i}.{'mp3' if backend == 'edge' else 'wav'}"
            for i in range(1, len(sentence_groups) + 1)
        ],
        "sentence_cues_path": sidecar,
        "segments": groups_meta,
    }


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
    if selected_backend == "sapi":
        return _generate_sapi(segments, output_dir, voice, rate)
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


def _mp3_duration_without_ffmpeg(audio_path: str) -> float:
    """Measure common MPEG Layer III streams without an external binary.

    Edge TTS emits MPEG-2/2.5 Layer III MP3.  This fallback counts frame
    samples, so timing remains audio-derived when a Windows environment lacks
    ffmpeg/ffprobe.  Unsupported or malformed streams still fail loudly.
    """
    data = Path(audio_path).read_bytes()
    offset = 0
    if data[:3] == b"ID3" and len(data) >= 10:
        # ID3v2 size uses four synchsafe bytes.
        offset = 10 + sum((data[index] & 0x7F) << (7 * (9 - index)) for index in range(6, 10))
    sample_rates = {
        3: (44100, 48000, 32000),
        2: (22050, 24000, 16000),
        0: (11025, 12000, 8000),
    }
    bitrate_mpeg1_l3 = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320)
    bitrate_mpeg2_l3 = (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)
    samples = 0
    sample_rate: int | None = None
    while offset + 4 <= len(data):
        if data[offset] != 0xFF or data[offset + 1] & 0xE0 != 0xE0:
            offset += 1
            continue
        version = (data[offset + 1] >> 3) & 0x03
        layer = (data[offset + 1] >> 1) & 0x03
        bitrate_index = (data[offset + 2] >> 4) & 0x0F
        rate_index = (data[offset + 2] >> 2) & 0x03
        padding = (data[offset + 2] >> 1) & 0x01
        if version == 1 or layer != 1 or rate_index == 3 or bitrate_index in {0, 15}:
            offset += 1
            continue
        rate = sample_rates[version][rate_index]
        bitrate = (bitrate_mpeg1_l3 if version == 3 else bitrate_mpeg2_l3)[bitrate_index] * 1000
        frame_samples = 1152 if version == 3 else 576
        frame_length = ((144 if version == 3 else 72) * bitrate) // rate + padding
        if frame_length <= 4 or offset + frame_length > len(data):
            break
        samples += frame_samples
        sample_rate = rate
        offset += frame_length
    if not samples or not sample_rate:
        raise ValueError(f"无法解析 {audio_path} 的 MP3 帧时长")
    return samples / sample_rate


def get_audio_duration(audio_path: str) -> float:
    """获取音频文件时长（秒），优先 ffmpeg，缺失时解析 MP3 帧。"""
    import subprocess as sp

    ffmpeg = _resolve_ffmpeg()
    ffmpeg = ffmpeg or "ffmpeg"
    try:
        result = sp.run(
            [ffmpeg, "-i", str(audio_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        if Path(audio_path).suffix.lower() == ".mp3":
            return _mp3_duration_without_ffmpeg(audio_path)
        raise
    for line in result.stderr.split("\n"):
        if "Duration:" in line:
            time_str = line.strip().split("Duration: ")[1].split(",")[0].strip()
            h, m, s = time_str.split(":")
            return float(h) * 3600 + float(m) * 60 + float(s)
    if Path(audio_path).suffix.lower() == ".mp3":
        return _mp3_duration_without_ffmpeg(audio_path)
    raise ValueError(f"无法获取 {audio_path} 的时长")
