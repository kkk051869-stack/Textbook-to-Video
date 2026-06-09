"""生成编排：把"解析→讲稿→storyboard→TTS"串成可复用的函数，并提供端到端 produce。

cli.py 的 generate / generate-docx 以及新增的 produce / script / storyboard 命令都复用
这里的构件，避免把同一套生成逻辑（尤其 TTS 回写 audio_duration_sec）抄好几遍。
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "Artifacts",
    "run_tts",
    "read_script_segments",
    "build_storyboard_pdf",
    "build_storyboard_pdf_general",
    "build_storyboard_docx",
    "build_script",
    "build_storyboard_from_script",
    "produce",
]

# script.txt 段头：兼容 "Segment 1:" / "第1段：" / "第1：" 三种历史写法
_SCRIPT_HEADER = re.compile(
    r"^(?:Segment\s*\d+|第\s*\d+\s*段?)\s*[:：]\s*$", re.MULTILINE
)


@dataclass
class Artifacts:
    """一次内容生成产出的所有中间件路径与元信息。"""

    stem: str                      # 文件前缀，如 "lesson4" 或 "ch3_s0"
    title: str
    raw_path: Path
    script_path: Path
    storyboard_path: Path
    output_dir: Path
    audio_dir: Path | None = None
    durations: list[float] = field(default_factory=list)
    images: list[dict] = field(default_factory=list)

    @property
    def total_sec(self) -> float:
        return float(sum(self.durations))


# ---------------------------------------------------------------------------
# 共享子步骤
# ---------------------------------------------------------------------------

def run_tts(
    storyboard: dict,
    storyboard_path: Path,
    audio_dir: Path,
    *,
    voice: str | None = None,
    rate: str | None = None,
) -> list[float]:
    """为 storyboard 各段生成配音，把 audio_duration_sec 回写进 JSON，返回时长列表。"""
    from textbook2video.pipeline.narrator import generate_audio, get_audio_duration

    narrations = [seg["narration"] for seg in storyboard["segments"]]
    tts_kwargs: dict = {"output_dir": str(audio_dir)}
    if voice:
        tts_kwargs["voice"] = voice
    if rate:
        tts_kwargs["rate"] = rate
    audio_files = generate_audio(narrations, **tts_kwargs)

    durations: list[float] = []
    for audio_file in audio_files:
        try:
            durations.append(round(get_audio_duration(str(audio_file)), 1))
        except ValueError:
            durations.append(0.0)

    for i, seg in enumerate(storyboard["segments"]):
        seg["audio_duration_sec"] = durations[i]

    with open(storyboard_path, "w", encoding="utf-8") as f:
        json.dump(storyboard, f, ensure_ascii=False, indent=2)

    print(f"  音频时长: {durations}")
    print(f"  总时长: {round(sum(durations), 1)} 秒")
    print(f"  已更新 (含音频时长): {storyboard_path}")
    return durations


def _save_script(script_path: Path, segments: list[str], *, label: str) -> None:
    with open(script_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            f.write(f"{label}{i}{'：' if label == '第' else ':'}\n{seg}\n\n")


def read_script_segments(path: str | Path) -> list[str]:
    """从 *_script.txt 还原讲稿分段（按段头切分，兼容多种历史格式）。"""
    text = Path(path).read_text(encoding="utf-8")
    if _SCRIPT_HEADER.search(text):
        # 以段头行为分隔切开；split 后首元素是段头前的空白
        parts = _SCRIPT_HEADER.split(text)
        return [p.strip() for p in parts if p.strip()]
    # 没有可识别的段头：退化为按空行分块
    return [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]


def _title_from_stem(stem: str) -> str:
    """从文件前缀推测课程标题：ch3_s0 → 第4章；lesson4 → Lesson 4。"""
    m = re.fullmatch(r"ch(\d+)_s\d+", stem)
    if m:
        return f"第{int(m.group(1)) + 1}章"
    m = re.fullmatch(r"lesson(\d+)", stem)
    if m:
        return f"Lesson {m.group(1)}"
    return ""


# ---------------------------------------------------------------------------
# PDF 路径（lesson 页码表）
# ---------------------------------------------------------------------------

def build_storyboard_pdf(
    input_path: str,
    *,
    lesson: int,
    output_dir: str | Path,
    model: str | None = None,
    skip_tts: bool = False,
    voice: str | None = None,
    rate: str | None = None,
) -> Artifacts:
    from textbook2video.pipeline import parser as parser_mod
    from textbook2video.pipeline.scriptwriter import generate_script
    from textbook2video.pipeline.storyboard import generate_storyboard

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"lesson{lesson}"

    print("\n[Step 1] 提取课文文本...")
    info = parser_mod.extract_lesson_info(input_path, lesson)
    print(f"  页码: {info['pages'][0]}-{info['pages'][1]}，{len(info['text'])} 字符")
    raw_path = output_dir / f"{stem}_raw.txt"
    raw_path.write_text(info["text"], encoding="utf-8")

    print("\n[Step 2] 生成讲稿...")
    segments = generate_script(info["text"], model=model)
    print(f"  生成 {len(segments)} 段讲稿")
    script_path = output_dir / f"{stem}_script.txt"
    _save_script(script_path, segments, label="Segment ")

    print("\n[Step 3] 生成画面大纲...")
    title = info.get("title") or f"Lesson {lesson}"
    storyboard = generate_storyboard(segments, lesson_title=title, model=model)
    print(f"  生成 {len(storyboard['segments'])} 页画面")
    storyboard_path = output_dir / f"{stem}_storyboard.json"
    with open(storyboard_path, "w", encoding="utf-8") as f:
        json.dump(storyboard, f, ensure_ascii=False, indent=2)

    arts = Artifacts(
        stem=stem, title=title, raw_path=raw_path, script_path=script_path,
        storyboard_path=storyboard_path, output_dir=output_dir,
    )
    if not skip_tts:
        print("\n[Step 4] 生成 TTS 配音...")
        arts.audio_dir = output_dir / f"{stem}_audio"
        arts.durations = run_tts(
            storyboard, storyboard_path, arts.audio_dir, voice=voice, rate=rate
        )
    return arts


# ---------------------------------------------------------------------------
# DOCX 路径（章/节 + 教材图提取）
# ---------------------------------------------------------------------------

def build_storyboard_docx(
    input_path: str,
    *,
    chapter: int,
    section: int,
    output_dir: str | Path,
    model: str | None = None,
    skip_tts: bool = False,
    voice: str | None = None,
    rate: str | None = None,
) -> Artifacts:
    from textbook2video.pipeline.parser import extract_section_from_docx
    from textbook2video.pipeline.scriptwriter import generate_script
    from textbook2video.pipeline.storyboard import generate_storyboard

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"ch{chapter}_s{section}"

    print("\n[Step 1] 提取章节文本和图片...")
    result = extract_section_from_docx(
        input_path,
        chapter_number=chapter,
        section_number=section,
        include_images=True,
        image_output_dir=str(output_dir / "images"),
    )
    text, images = result["text"], result["images"]
    print(f"  文本 {len(text)} 字符，图片 {len(images)} 张")
    raw_path = output_dir / f"{stem}_raw.txt"
    raw_path.write_text(text, encoding="utf-8")

    print("\n[Step 2] 生成讲稿...")
    segments = generate_script(text, model=model)
    print(f"  生成 {len(segments)} 段讲稿")
    script_path = output_dir / f"{stem}_script.txt"
    _save_script(script_path, segments, label="第")

    print("\n[Step 3] 生成画面大纲...")
    title = f"第{chapter + 1}章"
    storyboard = generate_storyboard(
        segments, lesson_title=title, model=model,
        available_images=images if images else None,
    )
    print(f"  生成 {len(storyboard['segments'])} 页画面")
    if images:
        storyboard.setdefault("metadata", {})["available_images"] = images
    storyboard_path = output_dir / f"{stem}_storyboard.json"
    with open(storyboard_path, "w", encoding="utf-8") as f:
        json.dump(storyboard, f, ensure_ascii=False, indent=2)

    arts = Artifacts(
        stem=stem, title=title, raw_path=raw_path, script_path=script_path,
        storyboard_path=storyboard_path, output_dir=output_dir, images=images,
    )
    if not skip_tts:
        print("\n[Step 4] 生成 TTS 配音...")
        arts.audio_dir = output_dir / f"{stem}_audio"
        arts.durations = run_tts(
            storyboard, storyboard_path, arts.audio_dir, voice=voice, rate=rate
        )
    return arts


# ---------------------------------------------------------------------------
# 拆分步骤：只生成讲稿 / 从讲稿续跑 storyboard
# ---------------------------------------------------------------------------

def build_script(
    input_path: str,
    *,
    lesson: int | None = None,
    chapter: int | None = None,
    section: int | None = None,
    output_dir: str | Path = "output",
    model: str | None = None,
) -> dict:
    """只做"解析 + 生成讲稿"两步，产出 *_raw.txt 与 *_script.txt。

    DOCX 路径会额外提取教材图并把 available_images 写到 <stem>_images.json，
    供后续 storyboard 步骤复用（图文链路不丢）。
    返回 dict：stem/title/raw_path/script_path/segments/images。
    """
    from textbook2video.pipeline.scriptwriter import generate_script

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    images: list[dict] = []
    if chapter is not None and section is not None:
        from textbook2video.pipeline.parser import extract_section_from_docx

        stem = f"ch{chapter}_s{section}"
        title = f"第{chapter + 1}章"
        label = "第"
        print("\n[Step 1] 提取章节文本和图片...")
        result = extract_section_from_docx(
            input_path, chapter_number=chapter, section_number=section,
            include_images=True, image_output_dir=str(output_dir / "images"),
        )
        text, images = result["text"], result["images"]
        print(f"  文本 {len(text)} 字符，图片 {len(images)} 张")
    elif lesson is not None:
        from textbook2video.pipeline import parser as parser_mod

        stem = f"lesson{lesson}"
        label = "Segment "
        print("\n[Step 1] 提取课文文本...")
        info = parser_mod.extract_lesson_info(input_path, lesson)
        text = info["text"]
        title = info.get("title") or f"Lesson {lesson}"
        print(f"  {len(text)} 字符")
    else:
        raise ValueError("build_script 需要 lesson（PDF）或 chapter+section（DOCX）")

    raw_path = output_dir / f"{stem}_raw.txt"
    raw_path.write_text(text, encoding="utf-8")

    print("\n[Step 2] 生成讲稿...")
    segments = generate_script(text, model=model)
    print(f"  生成 {len(segments)} 段讲稿")
    script_path = output_dir / f"{stem}_script.txt"
    _save_script(script_path, segments, label=label)
    print(f"  已保存: {script_path}")

    if images:
        images_path = output_dir / f"{stem}_images.json"
        images_path.write_text(
            json.dumps(images, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  已保存教材图清单: {images_path}")

    return {
        "stem": stem, "title": title, "raw_path": raw_path,
        "script_path": script_path, "segments": segments, "images": images,
    }


def build_script_from_text(
    raw_text_path: str | Path,
    *,
    output_dir: str | Path | None = None,
    stem: str | None = None,
    model: str | None = None,
    label: str = "Segment ",
) -> dict:
    """Generate script segments from an existing raw text file."""
    from textbook2video.pipeline.scriptwriter import generate_script

    raw_text_path = Path(raw_text_path)
    out_dir = Path(output_dir) if output_dir else raw_text_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    resolved_stem = stem or raw_text_path.stem.removesuffix("_raw")
    text = raw_text_path.read_text(encoding="utf-8")

    target_raw = out_dir / f"{resolved_stem}_raw.txt"
    if target_raw.resolve() != raw_text_path.resolve():
        target_raw.write_text(text, encoding="utf-8")

    segments = generate_script(text, model=model)
    script_path = out_dir / f"{resolved_stem}_script.txt"
    _save_script(script_path, segments, label=label)
    return {
        "stem": resolved_stem,
        "raw_path": target_raw,
        "script_path": script_path,
        "segments": segments,
        "text": text,
    }


def _load_available_images(images_arg: str | Path | None) -> list[dict]:
    """从 --images 指向的 JSON 读取 available_images。

    支持两种 JSON：images 列表本身，或含 metadata.available_images 的 storyboard。
    """
    if not images_arg:
        return []
    data = json.loads(Path(images_arg).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("metadata", {}).get("available_images", []) or []
    return []


def build_storyboard_from_script(
    script_path: str | Path,
    *,
    output_dir: str | Path | None = None,
    title: str | None = None,
    model: str | None = None,
    images: str | Path | None = None,
    skip_tts: bool = True,
    voice: str | None = None,
    rate: str | None = None,
) -> Artifacts:
    """从已有 *_script.txt 重新生成 storyboard JSON（可选再配音）。

    用于"讲稿满意、只想重做画面大纲"而不必重跑解析+讲稿。
    教材图通过 images（images.json 或旧 storyboard.json）复用。
    """
    from textbook2video.pipeline.storyboard import generate_storyboard

    script_path = Path(script_path)
    stem = script_path.stem
    if stem.endswith("_script"):
        stem = stem[: -len("_script")]
    out_dir = Path(output_dir) if output_dir else script_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    segments = read_script_segments(script_path)
    if not segments:
        raise ValueError(f"未能从 {script_path} 解析出讲稿分段")
    resolved_title = title or _title_from_stem(stem)

    # 若未显式指定 images，尝试自动发现同级 <stem>_images.json
    if images is None:
        auto = out_dir / f"{stem}_images.json"
        if auto.exists():
            images = auto
    available = _load_available_images(images)

    print(f"\n[storyboard] 从 {len(segments)} 段讲稿生成画面大纲"
          f"（教材图 {len(available)} 张）...")
    storyboard = generate_storyboard(
        segments, lesson_title=resolved_title, model=model,
        available_images=available if available else None,
    )
    if available:
        storyboard.setdefault("metadata", {})["available_images"] = available
    storyboard_path = out_dir / f"{stem}_storyboard.json"
    with open(storyboard_path, "w", encoding="utf-8") as f:
        json.dump(storyboard, f, ensure_ascii=False, indent=2)
    print(f"  生成 {len(storyboard['segments'])} 页画面 → {storyboard_path}")

    arts = Artifacts(
        stem=stem, title=resolved_title, raw_path=out_dir / f"{stem}_raw.txt",
        script_path=script_path, storyboard_path=storyboard_path,
        output_dir=out_dir, images=available,
    )
    if not skip_tts:
        print("\n[storyboard] 生成 TTS 配音...")
        arts.audio_dir = out_dir / f"{stem}_audio"
        arts.durations = run_tts(
            storyboard, storyboard_path, arts.audio_dir, voice=voice, rate=rate
        )
    return arts


def build_storyboard_pdf_general(
    input_path: str,
    *,
    output_dir: str | Path = "output/pdf_extract",
    start_page: int = 1,
    max_pages: int | None = None,
    stem: str = "pdf_extract",
    title: str | None = None,
    profile: str | Path | None = None,
    model: str | None = None,
    skip_tts: bool = True,
    voice: str | None = None,
    rate: str | None = None,
) -> Artifacts:
    """PDF experimental route: extract page range -> script -> storyboard.

    This does not replace the legacy page-range PDF parser. It is an opt-in
    path for profile-driven PDF parsing.
    """
    from textbook2video.pipeline.pdf_layout import PdfProfile, write_pdf_extract_bundle

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_profile = PdfProfile.from_file(profile) if profile else None
    bundle = write_pdf_extract_bundle(
        input_path,
        output_dir,
        profile=pdf_profile,
        start_page=start_page,
        max_pages=max_pages,
        stem=stem,
    )
    script_info = build_script_from_text(
        bundle["raw_path"],
        output_dir=output_dir,
        stem=stem,
        model=model,
    )
    return build_storyboard_from_script(
        script_info["script_path"],
        output_dir=output_dir,
        title=title or _title_from_stem(stem),
        model=model,
        images=bundle["images_path"],
        skip_tts=skip_tts,
        voice=voice,
        rate=rate,
    )


# ---------------------------------------------------------------------------
# 端到端：教材 → 有声 MP4
# ---------------------------------------------------------------------------

def produce(
    input_path: str,
    *,
    lesson: int | None = None,
    chapter: int | None = None,
    section: int | None = None,
    output_dir: str | Path = "output",
    theme: str | None = None,
    model: str | None = None,
    no_images: bool = False,
    repair: int = 2,
    browser: str = "msedge",
    batch_size: int = 4,
    voice: str | None = None,
    rate: str | None = None,
    fps: int = 30,
    keep_intermediate: bool = False,
    subtitles: bool = True,
) -> Path:
    """从教材一步生成有声成片 MP4：generate → animate → record → mux。

    通过 lesson（PDF）或 chapter+section（DOCX）二选一指定课节。
    录制时长按音频总时长自动确定（无需手动 --duration）。
    """
    from textbook2video.animation_gen import generate as animate
    from textbook2video.pipeline.compose import compose_video
    from textbook2video.pipeline.recorder import record_html_to_video
    from textbook2video.pipeline.subtitles import generate_srt

    output_dir = Path(output_dir)

    # 1) 内容生成（必须含 TTS，produce 要靠音频驱动时长 + 合成声音）
    print("=" * 56)
    print("[1/4] 生成讲稿 + 画面大纲 + 配音")
    print("=" * 56)
    if chapter is not None and section is not None:
        arts = build_storyboard_docx(
            input_path, chapter=chapter, section=section, output_dir=output_dir,
            model=model, skip_tts=False, voice=voice, rate=rate,
        )
    elif lesson is not None:
        arts = build_storyboard_pdf(
            input_path, lesson=lesson, output_dir=output_dir,
            model=model, skip_tts=False, voice=voice, rate=rate,
        )
    else:
        raise ValueError("produce 需要 lesson（PDF）或 chapter+section（DOCX）指定课节")

    if not arts.audio_dir or arts.total_sec <= 0:
        raise RuntimeError("配音未成功，无法确定录制时长 / 合成音轨")

    # 2) 出画面 HTML
    print("\n" + "=" * 56)
    print("[2/4] 渲染动画 HTML")
    print("=" * 56)
    anim_kwargs: dict = dict(
        output_dir=output_dir, batch_size=batch_size, theme_id=theme,
        layout_repair_attempts=repair, layout_browser_channel=browser,
        skip_image_gen=no_images,
    )
    if model:
        anim_kwargs["model"] = model
    html_path = animate(str(arts.storyboard_path), **anim_kwargs)

    # 3) 录制无声视频（录满音频总时长 + 1s 余量，保证最后一页不被切）
    print("\n" + "=" * 56)
    print("[3/4] 录制画面（无声）")
    print("=" * 56)
    rec_duration = math.ceil(arts.total_sec) + 1
    silent_mp4 = output_dir / f"{arts.stem}_silent.mp4"
    record_html_to_video(
        str(html_path), str(silent_mp4),
        duration=rec_duration, fps=fps, browser_channel=browser,
    )

    # 4) 拼接配音并合成有声成片（-shortest 按音轨裁掉视频尾部余量）
    print("\n" + "=" * 56)
    print("[4/4] 合成配音")
    print("=" * 56)
    final_mp4 = output_dir / f"{arts.stem}.mp4"
    subtitle_path = None
    if subtitles:
        subtitle_path = output_dir / f"{arts.stem}.srt"
        generate_srt(str(arts.storyboard_path), subtitle_path)
        print(f"  字幕: {subtitle_path}")
    compose_video(silent_mp4, arts.audio_dir, final_mp4, subtitle_path=subtitle_path)
    if not keep_intermediate:
        silent_mp4.unlink(missing_ok=True)

    print("\n" + "=" * 56)
    print(f"✅ 成片: {final_mp4}  （约 {round(arts.total_sec, 1)}s，含配音）")
    print("=" * 56)
    return final_mp4
