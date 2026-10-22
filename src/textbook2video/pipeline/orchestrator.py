"""生成编排：把"解析→讲稿→storyboard→TTS"串成可复用的函数，并提供端到端 produce。

cli.py 的 generate / generate-docx 以及新增的 produce / script / storyboard 命令都复用
这里的构件，避免把同一套生成逻辑（尤其 TTS 回写 audio_duration_sec）抄好几遍。
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "Artifacts",
    "run_tts",
    "read_script_segments",
    "build_storyboard_pdf",
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
    lesson_plan_path: Path | None = None
    durations: list[float] = field(default_factory=list)
    images: list[dict] = field(default_factory=list)

    @property
    def total_sec(self) -> float:
        return float(sum(self.durations))


def _carry_measured_p0_timing(
    measured_storyboard: dict,
    planned_storyboard: dict,
) -> None:
    """Keep measured TTS timing when phase two rematerializes a P0 candidate."""
    measured_segments = measured_storyboard.get("segments")
    planned_segments = planned_storyboard.get("segments")
    if not isinstance(measured_segments, list) or not isinstance(planned_segments, list):
        raise ValueError("P0 timing carry-forward requires storyboard segment lists")

    measured_by_id = {
        str(segment.get("id", index)): segment
        for index, segment in enumerate(measured_segments, start=1)
        if isinstance(segment, dict)
    }
    planned_by_id = {
        str(segment.get("id", index)): segment
        for index, segment in enumerate(planned_segments, start=1)
        if isinstance(segment, dict)
    }
    if set(measured_by_id) != set(planned_by_id):
        raise ValueError("P0 timing carry-forward segment IDs do not match")

    for segment_id, measured in measured_by_id.items():
        planned = planned_by_id[segment_id]
        if str(measured.get("narration") or "") != str(planned.get("narration") or ""):
            raise ValueError(f"P0 timing carry-forward narration mismatch: {segment_id}")
        duration = measured.get("audio_duration_sec")
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
            raise ValueError(f"P0 timing carry-forward missing measured duration: {segment_id}")
        planned["audio_duration_sec"] = float(duration)
        for key in ("timeline", "animations"):
            value = measured.get(key)
            if isinstance(value, list):
                planned[key] = copy.deepcopy(value)


def _dual_write_research_generation_v2(
    *,
    output_dir: Path,
    stem: str,
    raw_path: Path,
    lesson_plan: dict,
    segments: list[str],
    storyboard: dict,
    storyboard_path: Path,
) -> None:
    """Emit v2 research artifacts only when explicitly enabled.

    Legacy files stay valid and remain the renderer input; the small
    namespaced additions are ignored by v1 consumers.
    """
    from textbook2video.research.proposition_schema import (
        annotate_storyboard_v2,
        build_lesson_plan_v2,
        build_script_v2,
        build_source_units_v2,
        build_storyboard_v2,
        enabled,
    )

    if not enabled():
        return
    case_id = stem.replace("_", "-")
    raw_text = raw_path.read_text(encoding="utf-8")
    plan_v2 = build_lesson_plan_v2(lesson_plan, case_id=case_id, raw_text=raw_text)
    source_v2 = build_source_units_v2(case_id=case_id, raw_text=raw_text, document_path=str(raw_path))
    script_v2 = build_script_v2(segments, case_id=case_id, lesson_plan_v2=plan_v2)
    annotate_storyboard_v2(storyboard, script_v2, plan_v2)
    for path, document in (
        (output_dir / f"{stem}_source_units_v2.json", source_v2),
        (output_dir / f"{stem}_lesson_plan_v2.json", plan_v2),
        (output_dir / f"{stem}_script_v2.json", script_v2),
        (output_dir / f"{stem}_storyboard_v2.json", build_storyboard_v2(storyboard, case_id=case_id)),
    ):
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    storyboard_path.write_text(json.dumps(storyboard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _dual_write_lesson_script_v2(*, output_dir: Path, stem: str, raw_path: Path, lesson_plan: dict, segments: list[str]) -> None:
    from textbook2video.research.proposition_schema import build_lesson_plan_v2, build_script_v2, build_source_units_v2, enabled
    if not enabled():
        return
    plan_v2 = build_lesson_plan_v2(lesson_plan, case_id=stem.replace("_", "-"), raw_text=raw_path.read_text(encoding="utf-8"))
    case_id = stem.replace("_", "-")
    script_v2 = build_script_v2(segments, case_id=case_id, lesson_plan_v2=plan_v2)
    source_v2 = build_source_units_v2(case_id=case_id, raw_text=raw_path.read_text(encoding="utf-8"), document_path=str(raw_path))
    for path, document in ((output_dir / f"{stem}_source_units_v2.json", source_v2), (output_dir / f"{stem}_lesson_plan_v2.json", plan_v2), (output_dir / f"{stem}_script_v2.json", script_v2)):
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

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
    only: list[int] | None = None,
    sentence_sync: bool | None = None,
    timing_mode: str | None = None,
    reuse_existing_audio: bool = False,
    frozen_audio_dir: str | Path | None = None,
) -> list[float]:
    """为 storyboard 生成配音并回写时长。

    only 使用 1-based 页码；传入时只重配指定页，其余页沿用已有
    audio_duration_sec。返回值始终是全量 durations 列表。
    """
    from textbook2video.pipeline.narrator import generate_audio, get_audio_duration
    from textbook2video.pipeline.subtitles import SentenceSplitter
    from textbook2video.pipeline.timing import apply_timing, timed_storyboard_path

    segments = storyboard["segments"]
    total = len(segments)
    if only:
        selected = sorted(set(int(i) for i in only))
        invalid = [i for i in selected if i < 1 or i > total]
        if invalid:
            raise ValueError(f"--only 页码超出范围: {invalid}，有效范围 1-{total}")
        selected_indexes = [i - 1 for i in selected]
    else:
        selected_indexes = list(range(total))

    narrations = [segments[i]["narration"] for i in selected_indexes]
    tts_kwargs: dict = {"output_dir": str(audio_dir)}
    if voice:
        tts_kwargs["voice"] = voice
    if rate:
        tts_kwargs["rate"] = rate

    audio_dir.mkdir(parents=True, exist_ok=True)
    if frozen_audio_dir is not None:
        if only:
            raise ValueError("frozen_audio_dir cannot be combined with only")
        source_audio_dir = Path(frozen_audio_dir)
        if not source_audio_dir.is_dir():
            raise FileNotFoundError(f"frozen audio directory does not exist: {source_audio_dir}")
        for index in range(total):
            source = next(
                (
                    source_audio_dir / f"s{index + 1}{suffix}"
                    for suffix in (".mp3", ".wav")
                    if (source_audio_dir / f"s{index + 1}{suffix}").is_file()
                    and (source_audio_dir / f"s{index + 1}{suffix}").stat().st_size > 0
                ),
                None,
            )
            if source is None:
                raise FileNotFoundError(
                    f"frozen audio is missing segment {index + 1}: {source_audio_dir}"
                )
            destination = audio_dir / source.name
            if source.resolve() != destination.resolve():
                shutil.copy2(source, destination)
        source_cues = source_audio_dir / "sentence_cues.json"
        if source_cues.is_file():
            destination_cues = audio_dir / "sentence_cues.json"
            if source_cues.resolve() != destination_cues.resolve():
                shutil.copy2(source_cues, destination_cues)
        reuse_existing_audio = True
    backend = os.getenv("T2V_TTS_BACKEND", "edge").strip().lower()
    if timing_mode is not None and sentence_sync is not None:
        raise ValueError("timing_mode and sentence_sync cannot both be specified")
    requested_mode = timing_mode or os.getenv("T2V_TIMING_MODE")
    if requested_mode is not None:
        requested_mode = requested_mode.strip().lower()
        if requested_mode == "char":
            requested_mode = "legacy"
        if requested_mode not in {"legacy", "semantic"}:
            raise ValueError("timing_mode must be one of: char, legacy, semantic")
    if requested_mode is None and sentence_sync is not None:
        requested_mode = "semantic" if sentence_sync else "legacy"
    mode = requested_mode or (
        "semantic"
        if backend in {"mega", "megatts", "megatts3"}
        and os.getenv("T2V_SENTENCE_SYNC", "1") != "0"
        else "legacy"
    )
    use_sentence_sync = mode == "semantic"
    sentence_cues = None
    if reuse_existing_audio:
        if only:
            raise ValueError("reuse_existing_audio cannot be combined with only")
        audio_files = []
        for index in range(total):
            candidates = [audio_dir / f"s{index + 1}.mp3", audio_dir / f"s{index + 1}.wav"]
            audio_file = next((path for path in candidates if path.is_file() and path.stat().st_size > 0), None)
            if audio_file is None:
                raise FileNotFoundError(f"missing reusable audio for segment {index + 1}: {candidates}")
            audio_files.append(audio_file)
    elif use_sentence_sync and not only and backend in {"edge", "sapi", "mega", "megatts", "megatts3"}:
        from textbook2video.pipeline.narrator import generate_sentence_audio

        groups = [SentenceSplitter().split(text) or [text] for text in narrations]
        segment_ids = [segments[index].get("id", index + 1) for index in selected_indexes]
        sentence_kwargs = {}
        if any(str(value) != str(index + 1) for index, value in enumerate(segment_ids)):
            sentence_kwargs["segment_ids"] = segment_ids
        if backend in {"edge", "sapi"}:
            sentence_kwargs["voice"] = voice or (
                "Microsoft Huihui Desktop" if backend == "sapi" else "zh-CN-XiaoxiaoNeural"
            )
            sentence_kwargs["rate"] = rate or "+5%"
        result = generate_sentence_audio(
            groups,
            output_dir=audio_dir,
            backend=backend,
            **sentence_kwargs,
        )
        audio_files = [Path(path) for path in result["audio_files"]]
        sentence_cues = json.loads(Path(result["sentence_cues_path"]).read_text(encoding="utf-8"))
    elif only:
        with tempfile.TemporaryDirectory(prefix=".tts_partial_", dir=audio_dir) as tmp:
            tts_kwargs["output_dir"] = tmp
            partial_files = generate_audio(narrations, **tts_kwargs)
            audio_files: list[Path] = []
            for source, seg_index in zip(partial_files, selected_indexes):
                dest = audio_dir / f"s{seg_index + 1}.mp3"
                source_path = Path(source)
                if source_path.exists():
                    source_path.replace(dest)
                audio_files.append(dest)
    else:
        audio_files = generate_audio(narrations, **tts_kwargs)

    measured: list[float] = []
    for audio_file in audio_files:
        try:
            # Keep millisecond-level source timing.  Rounding each page to a
            # tenth of a second can accumulate into visible drift over a lesson.
            measured.append(round(get_audio_duration(str(audio_file)), 3))
        except ValueError:
            measured.append(0.0)

    for seg_index, duration in zip(selected_indexes, measured):
        segments[seg_index]["audio_duration_sec"] = duration

    durations: list[float] = []
    for seg in segments:
        duration = seg.get("audio_duration_sec")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool):
            durations.append(round(float(duration), 3))
        else:
            durations.append(0.0)

    # A sentence-level backend may have produced a sidecar next to the audio
    # directory.  Keep it optional so legacy segment-level TTS remains fully
    # compatible while timing/subtitles can consume measured cues.
    sentence_cues_path = audio_dir / "sentence_cues.json"
    if (
        mode == "semantic"
        and sentence_cues is None
        and sentence_cues_path.is_file()
    ):
        try:
            sentence_cues = json.loads(sentence_cues_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"sentence_cues.json could not be read in semantic timing mode: {exc}") from exc
    if mode == "semantic" and sentence_cues is None:
        raise ValueError(
            "semantic timing requires measured sentence_cues.json; "
            "regenerate sentence-level audio or provide a matching cue sidecar"
        )
    if mode == "semantic" and isinstance(sentence_cues, dict):
        groups = {
            str(group.get("segment_id")): group
            for group in sentence_cues.get("segments", [])
            if isinstance(group, dict)
        }
        for index, segment in enumerate(segments, start=1):
            segment_id = str(segment.get("id", index))
            group = groups.get(segment_id)
            if not isinstance(group, dict):
                raise ValueError(f"sentence cues are missing segment {segment_id}")
            expected = SentenceSplitter().split(str(segment.get("narration") or ""))
            actual = [
                str(cue.get("text") or "")
                for cue in group.get("cues", [])
                if isinstance(cue, dict)
            ]
            if actual != expected:
                raise ValueError(
                    f"sentence cues do not match frozen narration for segment {segment_id}"
                )
    timed = apply_timing(storyboard, sentence_cues=sentence_cues, timing_mode=mode)
    storyboard.clear()
    storyboard.update(timed)

    with open(storyboard_path, "w", encoding="utf-8") as f:
        json.dump(storyboard, f, ensure_ascii=False, indent=2)
    timed_path = timed_storyboard_path(storyboard_path)
    timed_path.write_text(
        json.dumps(storyboard, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    from textbook2video.research.proposition_schema import (
        build_timed_storyboard_v2,
        enabled as research_v2_enabled,
    )
    if research_v2_enabled():
        research_meta = storyboard.get("metadata", {}).get("research_generation_v2", {})
        case_id = str(research_meta.get("case_id") or Path(storyboard_path).stem.removesuffix("_storyboard"))
        timed_v2 = build_timed_storyboard_v2(storyboard, case_id=case_id, timing_source=mode)
        if timed_v2["segments"]:
            Path(storyboard_path).with_name(
                Path(storyboard_path).stem.removesuffix("_storyboard") + "_timed_storyboard_v2.json"
            ).write_text(json.dumps(timed_v2, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if only:
        print(f"  仅重配页: {[i + 1 for i in selected_indexes]}")
    print(f"  音频时长: {durations}")
    print(f"  总时长: {round(sum(durations), 3)} 秒")
    print(f"  已更新 (含音频时长): {storyboard_path}")
    print(f"  timed storyboard: {timed_path}")
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
    agent_review: bool = False,
    agent_review_rounds: int = 2,
    agent_review_strict: bool = False,
) -> Artifacts:
    from textbook2video.pipeline import parser as parser_mod
    from textbook2video.pipeline.lesson_plan import generate_lesson_plan
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

    title = info.get("title") or f"Lesson {lesson}"

    print("\n[Step 2] 生成教学计划...")
    lesson_plan = generate_lesson_plan(info["text"], lesson_title=title, model=model)
    lesson_plan_path = output_dir / f"{stem}_lesson_plan.json"
    lesson_plan_path.write_text(
        json.dumps(lesson_plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  知识点 {len(lesson_plan.get('knowledge_points', []))} 个 → {lesson_plan_path}")

    print("\n[Step 3] 生成讲稿...")
    segments = generate_script(info["text"], model=model, lesson_plan=lesson_plan)
    print(f"  生成 {len(segments)} 段讲稿")
    script_path = output_dir / f"{stem}_script.txt"
    _save_script(script_path, segments, label="Segment ")

    print("\n[Step 4] 生成画面大纲...")
    storyboard = generate_storyboard(
        segments, lesson_title=title, model=model, lesson_plan=lesson_plan,
        agent_review=agent_review,
        agent_review_rounds=agent_review_rounds,
        agent_review_strict=agent_review_strict,
    )
    print(f"  生成 {len(storyboard['segments'])} 页画面")
    storyboard_path = output_dir / f"{stem}_storyboard.json"
    with open(storyboard_path, "w", encoding="utf-8") as f:
        json.dump(storyboard, f, ensure_ascii=False, indent=2)
    _dual_write_research_generation_v2(
        output_dir=output_dir, stem=stem, raw_path=raw_path, lesson_plan=lesson_plan,
        segments=segments, storyboard=storyboard, storyboard_path=storyboard_path,
    )

    arts = Artifacts(
        stem=stem, title=title, raw_path=raw_path, script_path=script_path,
        storyboard_path=storyboard_path, output_dir=output_dir,
        lesson_plan_path=lesson_plan_path,
    )
    if not skip_tts:
        print("\n[Step 5] 生成 TTS 配音...")
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
    agent_review: bool = False,
    agent_review_rounds: int = 2,
    agent_review_strict: bool = False,
) -> Artifacts:
    from textbook2video.pipeline.parser import extract_section_from_docx
    from textbook2video.pipeline.lesson_plan import generate_lesson_plan
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

    title = f"第{chapter + 1}章"

    print("\n[Step 2] 生成教学计划...")
    lesson_plan = generate_lesson_plan(
        text, lesson_title=title, available_images=images if images else None,
        model=model,
    )
    lesson_plan_path = output_dir / f"{stem}_lesson_plan.json"
    lesson_plan_path.write_text(
        json.dumps(lesson_plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  知识点 {len(lesson_plan.get('knowledge_points', []))} 个 → {lesson_plan_path}")

    print("\n[Step 3] 生成讲稿...")
    segments = generate_script(text, model=model, lesson_plan=lesson_plan)
    print(f"  生成 {len(segments)} 段讲稿")
    script_path = output_dir / f"{stem}_script.txt"
    _save_script(script_path, segments, label="第")

    print("\n[Step 4] 生成画面大纲...")
    storyboard = generate_storyboard(
        segments, lesson_title=title, model=model,
        available_images=images if images else None,
        lesson_plan=lesson_plan,
        agent_review=agent_review,
        agent_review_rounds=agent_review_rounds,
        agent_review_strict=agent_review_strict,
    )
    print(f"  生成 {len(storyboard['segments'])} 页画面")
    if images:
        storyboard.setdefault("metadata", {})["available_images"] = images
    storyboard_path = output_dir / f"{stem}_storyboard.json"
    with open(storyboard_path, "w", encoding="utf-8") as f:
        json.dump(storyboard, f, ensure_ascii=False, indent=2)
    _dual_write_research_generation_v2(
        output_dir=output_dir, stem=stem, raw_path=raw_path, lesson_plan=lesson_plan,
        segments=segments, storyboard=storyboard, storyboard_path=storyboard_path,
    )

    arts = Artifacts(
        stem=stem, title=title, raw_path=raw_path, script_path=script_path,
        storyboard_path=storyboard_path, output_dir=output_dir, images=images,
        lesson_plan_path=lesson_plan_path,
    )
    if not skip_tts:
        print("\n[Step 5] 生成 TTS 配音...")
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
    from textbook2video.pipeline.lesson_plan import generate_lesson_plan
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

    print("\n[Step 2] 生成教学计划...")
    lesson_plan = generate_lesson_plan(
        text, lesson_title=title, available_images=images if images else None,
        model=model,
    )
    lesson_plan_path = output_dir / f"{stem}_lesson_plan.json"
    lesson_plan_path.write_text(
        json.dumps(lesson_plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  知识点 {len(lesson_plan.get('knowledge_points', []))} 个 → {lesson_plan_path}")

    print("\n[Step 3] 生成讲稿...")
    segments = generate_script(text, model=model, lesson_plan=lesson_plan)
    print(f"  生成 {len(segments)} 段讲稿")
    script_path = output_dir / f"{stem}_script.txt"
    _save_script(script_path, segments, label=label)
    _dual_write_lesson_script_v2(
        output_dir=output_dir, stem=stem, raw_path=raw_path,
        lesson_plan=lesson_plan, segments=segments,
    )
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
        "lesson_plan_path": lesson_plan_path,
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


def _load_visual_briefs(briefs_arg: str | Path | None) -> list[dict]:
    """Load VLM-verified, segment-bound visual briefs for storyboard planning."""
    if not briefs_arg:
        return []
    data = json.loads(Path(briefs_arg).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        briefs = data.get("visual_briefs", [])
        return [
            item for item in briefs
            if isinstance(item, dict)
            and str(item.get("vlm_verdict") or item.get("verdict") or "").upper() == "ACCEPT"
            and str(item.get("source_image_id") or item.get("id") or "").strip()
            and str(item.get("segment_id") or item.get("segment_index") or "").strip()
            and str(item.get("visual_summary") or item.get("description") or "").strip()
            and str(item.get("proposition") or item.get("support") or "").strip()
        ]
    return []


def _discover_related_artifact(script_path: Path, stem: str, suffix: str) -> Path | None:
    """Find a frozen source artifact beside an experimental rerun.

    Research candidates commonly live in a child ``candidate_*`` directory
    while their raw text, lesson plan and image inventory remain in the
    immutable source run.  This lookup is read-only and bounded; it prevents a
    P0 run from silently losing source provenance merely because its output
    directory changed.
    """
    filename = f"{stem}_{suffix}"
    current = script_path.parent
    for _ in range(5):
        candidate = current / filename
        if candidate.is_file():
            return candidate
        # Figure-extraction runs conventionally live in ``<case>_figures``
        # while the immutable text/lesson-plan run is its sibling ``<case>``.
        # Treat that as an explicit, bounded read-only provenance relation.
        if current.name.endswith("_figures"):
            frozen_run = current.parent / current.name.removesuffix("_figures")
            candidate = frozen_run / filename
            if candidate.is_file():
                return candidate
        if current.parent == current:
            break
        current = current.parent
    return None


def build_storyboard_from_script(
    script_path: str | Path,
    *,
    output_dir: str | Path | None = None,
    title: str | None = None,
    model: str | None = None,
    images: str | Path | None = None,
    visual_briefs: str | Path | None = None,
    skip_tts: bool = True,
    voice: str | None = None,
    rate: str | None = None,
    agent_review: bool = False,
    agent_review_rounds: int = 2,
    agent_review_strict: bool = False,
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
        images = auto if auto.exists() else _discover_related_artifact(script_path, stem, "images.json")
    available = _load_available_images(images)
    briefs = _load_visual_briefs(visual_briefs)
    lesson_plan = None
    auto_plan = out_dir / f"{stem}_lesson_plan.json"
    if not auto_plan.exists():
        discovered_plan = _discover_related_artifact(script_path, stem, "lesson_plan.json")
        if discovered_plan:
            auto_plan = discovered_plan
    if auto_plan.exists():
        from textbook2video.pipeline.lesson_plan import load_lesson_plan

        lesson_plan = load_lesson_plan(auto_plan)

    print(f"\n[storyboard] 从 {len(segments)} 段讲稿生成画面大纲"
          f"（教材图 {len(available)} 张）...")
    storyboard = generate_storyboard(
        segments, lesson_title=resolved_title, model=model,
        available_images=available if available else None,
        visual_briefs=briefs if briefs else None,
        lesson_plan=lesson_plan,
        agent_review=agent_review,
        agent_review_rounds=agent_review_rounds,
        agent_review_strict=agent_review_strict,
    )
    if available:
        storyboard.setdefault("metadata", {})["available_images"] = available
    if briefs:
        storyboard.setdefault("metadata", {})["visual_briefs_path"] = str(visual_briefs)
    storyboard_path = out_dir / f"{stem}_storyboard.json"
    with open(storyboard_path, "w", encoding="utf-8") as f:
        json.dump(storyboard, f, ensure_ascii=False, indent=2)
    print(f"  生成 {len(storyboard['segments'])} 页画面 → {storyboard_path}")

    arts = Artifacts(
        stem=stem, title=resolved_title,
        raw_path=_discover_related_artifact(script_path, stem, "raw.txt") or out_dir / f"{stem}_raw.txt",
        script_path=script_path, storyboard_path=storyboard_path,
        output_dir=out_dir, images=available,
        lesson_plan_path=auto_plan if auto_plan.exists() else None,
    )
    if not skip_tts:
        print("\n[storyboard] 生成 TTS 配音...")
        arts.audio_dir = out_dir / f"{stem}_audio"
        arts.durations = run_tts(
            storyboard, storyboard_path, arts.audio_dir, voice=voice, rate=rate
        )
    return arts


def _artifacts_from_storyboard(
    storyboard_path: str | Path,
    *,
    output_dir: str | Path | None = None,
    voice: str | None = None,
    rate: str | None = None,
    skip_tts: bool = False,
    reuse_audio: bool = False,
    frozen_audio_dir: str | Path | None = None,
    timing_mode: str | None = None,
) -> Artifacts:
    """Create produce artifacts from an existing storyboard.

    ``skip_tts`` is used by the optional research adapter so it can copy and
    enhance the production storyboard before the normal TTS/timing step runs.
    The default remains the historical "regenerate TTS" behavior.
    """
    source_storyboard_path = Path(storyboard_path)
    out_dir = Path(output_dir) if output_dir else source_storyboard_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = source_storyboard_path.stem
    if stem.endswith("_storyboard"):
        stem = stem[: -len("_storyboard")]
    working_storyboard_path = out_dir / source_storyboard_path.name
    if source_storyboard_path.resolve() != working_storyboard_path.resolve():
        shutil.copy2(source_storyboard_path, working_storyboard_path)
    storyboard = json.loads(working_storyboard_path.read_text(encoding="utf-8"))
    title = storyboard.get("lesson_title") or _title_from_stem(stem)

    # Preserve source figure identity when an existing storyboard is reused.
    # Older storyboards often kept only ``src``/``description`` even though
    # the embedded image inventory already contained the original Figure id
    # and caption.  Carrying those fields onto the rendered element prevents
    # a VLM summary from being shown as a truncated, reader-facing caption.
    available_images = storyboard.get("metadata", {}).get("available_images", []) or []
    source_images_by_key: dict[str, dict] = {}
    for image in available_images:
        if not isinstance(image, dict):
            continue
        for key in (image.get("id"), image.get("filename")):
            if key:
                source_images_by_key[str(key)] = image
    for segment in storyboard.get("segments", []) or []:
        if not isinstance(segment, dict):
            continue
        for element in segment.get("elements", []) or []:
            if not isinstance(element, dict) or element.get("type") != "image":
                continue
            source = source_images_by_key.get(
                str(element.get("source_image_id") or element.get("src") or "")
            )
            if not source:
                continue
            element.setdefault("source_image_id", source.get("id"))
            if source.get("figure_id"):
                element.setdefault("figure_id", source["figure_id"])
            if source.get("caption"):
                element.setdefault("source_caption", source["caption"])
    working_storyboard_path.write_text(
        json.dumps(storyboard, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # A storyboard copy must keep the exact local images it references.  The
    # renderer resolves plain filenames beside the working storyboard, so copy
    # only those immutable assets instead of falling back to generated images.
    target_image_dir = out_dir / "images"
    referenced_images = {
        str(element.get("src") or "")
        for segment in storyboard.get("segments", [])
        if isinstance(segment, dict)
        for element in segment.get("elements", [])
        if isinstance(element, dict)
        and element.get("type") == "image"
        and Path(str(element.get("src") or "")).name == str(element.get("src") or "")
        and str(element.get("src") or "").strip()
    }
    for filename in sorted(referenced_images):
        candidate_dirs = (
            source_storyboard_path.parent / "images",
            source_storyboard_path.parent.parent / "source" / "images",
        )
        source_candidates: list[Path] = []
        seen_candidates: set[Path] = set()
        for directory in candidate_dirs:
            candidate = directory / filename
            resolved = candidate.resolve()
            if resolved in seen_candidates:
                continue
            seen_candidates.add(resolved)
            if candidate.is_file():
                source_candidates.append(candidate)
        if not source_candidates:
            raise FileNotFoundError(
                "storyboard references missing local image; searched: "
                + ", ".join(str(directory / filename) for directory in candidate_dirs)
            )
        digests = {
            hashlib.sha256(candidate.read_bytes()).hexdigest()
            for candidate in source_candidates
        }
        if len(digests) != 1:
            raise ValueError(
                "storyboard image is ambiguous because same-case copies differ: "
                + ", ".join(str(candidate) for candidate in source_candidates)
            )
        source_image = source_candidates[0]
        target_image_dir.mkdir(parents=True, exist_ok=True)
        destination = target_image_dir / filename
        if source_image.resolve() != destination.resolve():
            shutil.copy2(source_image, destination)

    audio_dir = out_dir / f"{stem}_audio"
    durations: list[float] = []
    if not skip_tts:
        print(f"\n[from-storyboard] 重新生成 TTS 配音 → {audio_dir}")
        durations = run_tts(
            storyboard,
            working_storyboard_path,
            audio_dir,
            voice=voice,
            rate=rate,
            reuse_existing_audio=reuse_audio,
            frozen_audio_dir=frozen_audio_dir,
            timing_mode=timing_mode,
        )
    # An experimental candidate may be rendered into a fresh output folder
    # while its frozen textbook evidence still lives beside (or above) the
    # source storyboard.  Keep those input artifacts attached rather than
    # silently replacing them with nonexistent paths in the candidate folder.
    raw_path = _discover_related_artifact(source_storyboard_path, stem, "raw.txt")
    lesson_plan_path = _discover_related_artifact(
        source_storyboard_path, stem, "lesson_plan.json"
    )
    script_path = _discover_related_artifact(source_storyboard_path, stem, "script.txt")
    return Artifacts(
        stem=stem,
        title=title,
        raw_path=raw_path or out_dir / f"{stem}_raw.txt",
        script_path=script_path or out_dir / f"{stem}_script.txt",
        storyboard_path=working_storyboard_path,
        output_dir=out_dir,
        audio_dir=None if skip_tts else audio_dir,
        lesson_plan_path=lesson_plan_path,
        durations=durations,
        images=available_images,
    )


# ---------------------------------------------------------------------------
# 端到端：教材 → 有声 MP4
# ---------------------------------------------------------------------------

def _prepare_default_course_visuals(
    arts: Artifacts, *, model: str | None, theme: str | None, browser: str,
    voice: str | None, rate: str | None, reuse_audio: bool,
    frozen_audio_dir: str | Path | None, timing_mode: str | None,
    source_scope: str = "provided-raw-text",
) -> None:
    """Plan page structure first; measure/rebuild its timing once afterwards."""
    from textbook2video.pipeline.config import LLM_DEFAULT_MODEL
    from textbook2video.pipeline.course_visuals import prepare_course_storyboard

    before = json.loads(arts.storyboard_path.read_text(encoding="utf-8"))
    planned_path = prepare_course_storyboard(
        arts.storyboard_path, output_dir=arts.output_dir, model=model or LLM_DEFAULT_MODEL,
        theme=theme or "bright", browser=browser, source_path=arts.raw_path,
        source_scope=source_scope,
    )
    planned = json.loads(planned_path.read_text(encoding="utf-8"))
    if (frozen_audio_dir is not None or reuse_audio) and (
        [s["narration"] for s in before["segments"]]
        != [s["narration"] for s in planned["segments"]]
    ):
        raise ValueError(
            "split pages require new measured audio; cached/frozen page audio cannot be reassigned"
        )
    arts.storyboard_path = planned_path
    arts.audio_dir = arts.output_dir / f"{arts.stem}_audio"
    arts.durations = run_tts(
        planned, arts.storyboard_path, arts.audio_dir, voice=voice, rate=rate,
        reuse_existing_audio=reuse_audio, frozen_audio_dir=frozen_audio_dir,
        timing_mode=timing_mode,
    )


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
    from_script: str | Path | None = None,
    from_storyboard: str | Path | None = None,
    from_html: str | Path | None = None,
    quality_report: bool = True,
    require_review: bool = False,
    agent_review: bool = False,
    agent_review_rounds: int = 2,
    agent_review_strict: bool = False,
    p0_research: bool = False,
    p0_plan: str | Path | None = None,
    p0_proposition_graph: str | Path | None = None,
    p0_visual_decisions: str | Path | None = None,
    p0_visual_specs: str | Path | None = None,
    p0_visual_bindings: str | Path | None = None,
    p0_auto_visuals: bool = False,
    visual_briefs: str | Path | None = None,
    reuse_audio: bool = False,
    frozen_audio_dir: str | Path | None = None,
    timing_mode: str | None = None,
    p0_retrieval_catalog: str | Path | None = None,
    p0_enable_generation: bool = True,
    p0_method_mode: str = "phase2",
    p0_vlm_review: str | Path | None = None,
) -> Path:
    """从教材一步生成有声成片 MP4：generate → animate → record → mux。

    通过 lesson（PDF）或 chapter+section（DOCX）二选一指定课节。
    录制时长按音频总时长自动确定（无需手动 --duration）。
    """
    output_dir = Path(output_dir)
    if from_html and not from_storyboard:
        raise ValueError("--from-html 需要同时提供 --from-storyboard 以确定配音和时长")
    if p0_plan and not p0_research:
        raise ValueError("p0_plan requires p0_research=True")
    if p0_visual_specs and not p0_research:
        raise ValueError("p0_visual_specs requires p0_research=True")
    if p0_visual_bindings and not p0_visual_specs:
        raise ValueError("p0_visual_bindings requires p0_visual_specs")
    if p0_visual_specs and not p0_visual_bindings:
        raise ValueError("p0_visual_specs requires p0_visual_bindings")
    if p0_visual_specs and not p0_plan:
        raise ValueError(
            "p0_visual_specs currently requires an explicit p0_plan so each new element has an auditable event target"
        )
    if p0_auto_visuals and not p0_research:
        raise ValueError("p0_auto_visuals requires p0_research=True")
    if p0_auto_visuals and (p0_visual_specs or p0_visual_bindings or p0_plan):
        raise ValueError("p0_auto_visuals cannot be combined with manual P0 visual specs, bindings, or plan")
    if p0_method_mode not in {"phase2", "legacy"}:
        raise ValueError("p0_method_mode must be 'phase2' or 'legacy'")
    if p0_research and from_html:
        raise ValueError("P0 research mode must regenerate HTML; --from-html is not supported")
    if frozen_audio_dir is not None and not from_storyboard:
        raise ValueError("frozen_audio_dir currently requires from_storyboard")

    input_suffix = Path(input_path).suffix.lower()
    is_pdf_input = input_suffix == ".pdf"
    is_docx_input = input_suffix in {".docx", ".doc"}
    needs_textbook_selection = not from_script and not from_storyboard
    if needs_textbook_selection:
        if is_pdf_input:
            if lesson is None:
                raise ValueError("PDF input requires --lesson; --chapter/--section are for DOCX only")
            if chapter is not None or section is not None:
                raise ValueError("PDF input does not accept --chapter/--section; use --lesson")
        elif is_docx_input:
            if lesson is not None:
                raise ValueError("DOCX input does not accept --lesson; use --chapter and --section")
            if chapter is None or section is None:
                raise ValueError("DOCX input requires --chapter and --section")
        else:
            raise ValueError(f"Unsupported textbook format: {input_suffix or '<none>'}")

    from textbook2video.pipeline.compose import compose_video
    from textbook2video.pipeline.quality import write_quality_report
    from textbook2video.pipeline.recorder import record_html_to_video
    from textbook2video.pipeline.subtitles import generate_srt

    # 1) 内容生成。P0 mode intentionally defers TTS: it copies the ordinary
    # storyboard first, then runs the *same* production TTS/timing path on the
    # enhanced copy.  Baseline mode retains the historical calls unchanged.
    print("=" * 56)
    print("[1/4] 生成讲稿 + 画面大纲 + 配音")
    print("=" * 56)
    default_visual_tools = not p0_research and not no_images and not from_html
    defer_tts_for_p0 = p0_research or default_visual_tools
    if from_storyboard:
        arts = _artifacts_from_storyboard(
            from_storyboard,
            output_dir=output_dir,
            voice=voice,
            rate=rate,
            skip_tts=defer_tts_for_p0,
            reuse_audio=reuse_audio,
            frozen_audio_dir=frozen_audio_dir,
            timing_mode=timing_mode,
        )
    elif from_script:
        arts = build_storyboard_from_script(
            from_script,
            output_dir=output_dir,
            title=None,
            model=model,
            skip_tts=defer_tts_for_p0,
            voice=voice,
            rate=rate,
            agent_review=agent_review,
            agent_review_rounds=agent_review_rounds,
            agent_review_strict=agent_review_strict,
            visual_briefs=visual_briefs,
        )
    elif is_pdf_input:
        arts = build_storyboard_pdf(
            input_path, lesson=lesson, output_dir=output_dir,
            model=model, skip_tts=defer_tts_for_p0, voice=voice, rate=rate,
            agent_review=agent_review,
            agent_review_rounds=agent_review_rounds,
            agent_review_strict=agent_review_strict,
        )
    elif is_docx_input:
        arts = build_storyboard_docx(
            input_path, chapter=chapter, section=section, output_dir=output_dir,
            model=model, skip_tts=defer_tts_for_p0, voice=voice, rate=rate,
            agent_review=agent_review,
            agent_review_rounds=agent_review_rounds,
            agent_review_strict=agent_review_strict,
        )

    if default_visual_tools:
        _prepare_default_course_visuals(
            arts, model=model, theme=theme, browser=browser, voice=voice, rate=rate,
            reuse_audio=reuse_audio, frozen_audio_dir=frozen_audio_dir, timing_mode=timing_mode,
            source_scope="textbook" if needs_textbook_selection else "provided-raw-text",
        )

    p0_paths = None
    if p0_research:
        from textbook2video.research.p0_integration import (
            apply_p0_event_schedule,
            prepare_p0_candidate,
        )

        p0_base_storyboard_path = arts.storyboard_path
        compiled_visual_manifest_path: Path | None = None
        compiled_visual_bindings: list[dict[str, object]] = []
        if p0_visual_specs:
            specs_path = Path(p0_visual_specs)
            bindings_path = Path(p0_visual_bindings)  # guarded above
            if not specs_path.is_file() or not bindings_path.is_file():
                raise FileNotFoundError("P0 visual specs and bindings must both exist")
            specs_payload = json.loads(specs_path.read_text(encoding="utf-8"))
            specs = specs_payload.get("visuals") if isinstance(specs_payload, dict) else specs_payload
            bindings_payload = json.loads(bindings_path.read_text(encoding="utf-8"))
            bindings = (
                bindings_payload.get("bindings")
                if isinstance(bindings_payload, dict)
                else bindings_payload
            )
            if not isinstance(specs, list) or not isinstance(bindings, list):
                raise ValueError("P0 visual specs and bindings must be JSON lists or visuals/bindings objects")
            if not bindings or not all(isinstance(item, dict) for item in bindings):
                raise ValueError("P0 visual bindings must be a non-empty list of objects")
            from textbook2video.research.visual_synthesis import compile_visuals

            compiled_visual_manifest_path = compile_visuals(
                specs,
                output_dir / f"{arts.stem}_p0_visuals",
                theme_id=theme or "bright",
            )
            compiled_visual_bindings = bindings
            print(f"  P0 compiled teaching visuals: {compiled_visual_manifest_path}")
        p0_paths = prepare_p0_candidate(
            p0_base_storyboard_path,
            output_dir=output_dir,
            # Bootstrap paths and source evidence only.  A supplied plan may
            # reference IDs from the real proposition graph, so validating it
            # against temporary sentence-derived propositions here would reject
            # a correct formal plan before the graph is loaded below.
            proposition_graph_path=p0_proposition_graph,
        )
        from textbook2video.research.proposition_graph import build_proposition_graph
        from textbook2video.research.source_evidence import build_source_evidence

        evidence_path = p0_paths.sidecar_path.with_name(
            p0_paths.sidecar_path.name.replace("_research_p0.json", "_source_evidence.json")
        )
        build_source_evidence(
            arts.raw_path,
            arts.images,
            output_path=evidence_path,
        )
        graph_path = Path(p0_proposition_graph) if p0_proposition_graph else p0_paths.sidecar_path.with_name(
            p0_paths.sidecar_path.name.replace("_research_p0.json", "_proposition_graph.json")
        )
        if not p0_proposition_graph:
            build_proposition_graph(
                raw_path=arts.raw_path,
                source_evidence_path=evidence_path,
                storyboard_path=p0_base_storyboard_path,
                lesson_plan_path=arts.lesson_plan_path,
                output_path=graph_path,
                model=model,
            )
        elif not graph_path.is_file():
            raise FileNotFoundError(f"P0 proposition graph does not exist: {graph_path}")
        from textbook2video.research.visual_acquisition import execute_visual_acquisition
        from textbook2video.research.visual_decision import decide_visual_support

        visual_decision_path = Path(p0_visual_decisions) if p0_visual_decisions else p0_paths.sidecar_path.with_name(
            p0_paths.sidecar_path.name.replace("_research_p0.json", "_visual_decisions.json")
        )
        if not p0_visual_decisions:
            decide_visual_support(
                proposition_graph_path=graph_path,
                source_evidence_path=evidence_path,
                output_path=visual_decision_path,
                model=model,
                retrieval_catalog_path=p0_retrieval_catalog,
                storyboard_path=p0_base_storyboard_path,
            )
        elif not visual_decision_path.is_file():
            raise FileNotFoundError(f"P0 visual decision file does not exist: {visual_decision_path}")
        # External/frozen decision files from the first P0 iteration are
        # upgraded once at the boundary.  Downstream code then consumes one
        # validated v2 shape rather than treating omitted audit fields as
        # implicit guarantees.
        from textbook2video.research.visual_decision import (
            normalize_visual_decision,
            validate_visual_decision_document,
        )
        graph_document = json.loads(graph_path.read_text(encoding="utf-8"))
        evidence_document = json.loads(evidence_path.read_text(encoding="utf-8"))
        propositions_by_id = {
            str(item.get("id") or ""): item
            for item in graph_document.get("narration_propositions", [])
            if isinstance(item, dict) and item.get("id")
        }
        image_ids = {
            str(item.get("id") or "")
            for item in evidence_document.get("source_images", [])
            if isinstance(item, dict) and item.get("id")
        }
        decision_document = json.loads(visual_decision_path.read_text(encoding="utf-8"))
        decision_document["schema_version"] = "p0-visual-decision-v2.0"
        normalized_decisions = []
        for raw_decision in decision_document.get("decisions", []):
            if not isinstance(raw_decision, dict):
                continue
            item = dict(raw_decision)
            if not item.get("rationale_evidence"):
                item["rationale"] = item.get("rationale") or "legacy decision upgraded at P0 boundary"
                item["rationale_evidence"] = [{
                    "kind": "legacy_decision", "id": None,
                    "quote": "legacy decision had no persisted source rationale",
                    "status": "UPGRADED_LEGACY_NOT_SOURCE_EVIDENCE",
                }]
            normalized_decisions.append(normalize_visual_decision(
                item,
                proposition=propositions_by_id.get(str(item.get("narration_proposition_id") or "")),
                available_image_ids=image_ids,
            ))
        decision_document["decisions"] = normalized_decisions
        validate_visual_decision_document(
            decision_document, proposition_ids=set(propositions_by_id), require_evidence=True
        )
        visual_decision_path.write_text(
            json.dumps(decision_document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if p0_auto_visuals:
            from textbook2video.research.auto_visual_plan import build_auto_visual_plan
            from textbook2video.research.visual_synthesis import compile_visuals

            auto_plan_path = output_dir / f"{arts.stem}_p0_auto_visual_plan.json"
            build_auto_visual_plan(
                proposition_graph_path=graph_path,
                visual_decision_path=visual_decision_path,
                output_path=auto_plan_path,
                model=model,
            )
            auto_plan = json.loads(auto_plan_path.read_text(encoding="utf-8"))
            p0_plan_path = output_dir / f"{arts.stem}_p0_auto_plan.json"
            p0_plan_path.write_text(
                json.dumps(auto_plan["plan"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            p0_plan = p0_plan_path
            compiled_visual_bindings = auto_plan["bindings"]
            compiled_visual_manifest_path = compile_visuals(
                auto_plan["visuals"], output_dir / f"{arts.stem}_p0_visuals",
                theme_id=theme or "bright",
            )
            print(f"  P0 auto visual plan: {auto_plan_path}")
        visual_acquisition_path = execute_visual_acquisition(
            decision_path=visual_decision_path,
            output_dir=output_dir / f"{arts.stem}_p0_acquisition",
            retrieval_catalog_path=p0_retrieval_catalog,
            enable_generation=p0_enable_generation and not p0_auto_visuals,
        )
        if p0_vlm_review:
            from textbook2video.research.visual_acquisition import apply_vlm_review_to_acquisition
            review_path = Path(p0_vlm_review)
            if not review_path.is_file():
                raise FileNotFoundError(f"P0 VLM review does not exist: {review_path}")
            visual_acquisition_path = apply_vlm_review_to_acquisition(
                acquisition_path=visual_acquisition_path,
                vlm_review_path=review_path,
                output_path=Path(visual_acquisition_path).with_name("visual_acquisition_reviewed.json"),
            )
        p0_paths = prepare_p0_candidate(
            arts.storyboard_path,
            output_dir=output_dir,
            proposition_graph_path=graph_path,
        )
        if p0_plan is None and p0_method_mode == "legacy":
            from textbook2video.research.p0_planner import build_local_p0_plan
            p0_plan = build_local_p0_plan(
                p0_paths,
                source_evidence_path=evidence_path,
                visual_decision_path=visual_decision_path,
                require_visual_decisions=True,
            )
            p0_paths = prepare_p0_candidate(
                p0_base_storyboard_path,
                output_dir=output_dir,
                plan_path=p0_plan,
                proposition_graph_path=graph_path,
                visual_decision_path=visual_decision_path,
                compiled_visual_manifest_path=compiled_visual_manifest_path,
                compiled_visual_bindings=compiled_visual_bindings,
            )
            print(f"  P0 legacy local plan: {p0_plan}")
        else:
            p0_paths = prepare_p0_candidate(
                p0_base_storyboard_path,
                output_dir=output_dir,
                plan_path=p0_plan,
                proposition_graph_path=graph_path,
                visual_decision_path=visual_decision_path,
                compiled_visual_manifest_path=compiled_visual_manifest_path,
                compiled_visual_bindings=compiled_visual_bindings,
            )
        candidate_sidecar = json.loads(p0_paths.sidecar_path.read_text(encoding="utf-8"))
        candidate_sidecar["visual_decision_path"] = str(visual_decision_path)
        candidate_sidecar["visual_acquisition_path"] = str(visual_acquisition_path)
        if compiled_visual_manifest_path:
            candidate_sidecar["compiled_visual_manifest_path"] = str(compiled_visual_manifest_path)
            candidate_sidecar["compiled_visual_bindings"] = compiled_visual_bindings
        p0_paths.sidecar_path.write_text(
            json.dumps(candidate_sidecar, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        arts.storyboard_path = p0_paths.candidate_storyboard_path
        arts.stem = arts.storyboard_path.stem.removesuffix("_storyboard")
        arts.audio_dir = output_dir / f"{arts.stem}_audio"
        candidate = json.loads(arts.storyboard_path.read_text(encoding="utf-8"))
        print(f"  P0 research candidate: {arts.storyboard_path}")
        arts.durations = run_tts(
            candidate, arts.storyboard_path, arts.audio_dir, voice=voice, rate=rate,
            reuse_existing_audio=reuse_audio,
            frozen_audio_dir=frozen_audio_dir,
            timing_mode="semantic",
        )
        p0_sentence_cues = None
        p0_sentence_cues_path = arts.audio_dir / "sentence_cues.json"
        if p0_sentence_cues_path.is_file():
            try:
                p0_sentence_cues = json.loads(
                    p0_sentence_cues_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"P0 sentence cues could not be read: {exc}") from exc
        if p0_sentence_cues is None:
            raise ValueError(
                "formal P0 generation requires measured sentence_cues.json; "
                "duration-weighted timing fallback is disabled"
            )
        candidate_before_plan = copy.deepcopy(candidate)
        if p0_plan is None:
            # Phase two is the default research path.  It runs only after
            # production TTS has measured sentence cues, then turns the
            # frozen candidate pool and dynamic schedule into the exact P0
            # event-plan schema consumed by the unchanged renderer.
            from textbook2video.research.candidate_pool import build_frozen_candidate_pool
            from textbook2video.research.p0_method_runner import (
                build_executable_p0_plan,
                run_p0_method_suite,
            )

            method_dir = output_dir / f"{arts.stem}_p0_phase2"
            pool_path = build_frozen_candidate_pool(
                decision_path=visual_decision_path,
                proposition_graph_path=graph_path,
                source_evidence_path=evidence_path,
                storyboard_path=p0_base_storyboard_path,
                acquisition_path=visual_acquisition_path,
                retrieval_catalog_path=p0_retrieval_catalog,
                output_path=method_dir / "candidate_pool.json",
                # A single render may legitimately have only reuse/none.
                # Four-outcome coverage is enforced separately for a formal
                # multi-document binding experiment.
                require_coverage=False,
            )
            method_outputs = run_p0_method_suite(
                candidate_pool_path=pool_path,
                output_dir=method_dir,
                selected_binding_method="source_conditioned",
                storyboard_path=arts.storyboard_path,
                proposition_graph_path=graph_path,
                sentence_cues_path=p0_sentence_cues_path,
                require_pool_coverage=False,
                # This execution path may use the persisted decision-to-source
                # bridge.  The independent comparison runner keeps it off.
                allow_decision_bridge=True,
            )
            p0_plan = build_executable_p0_plan(
                candidate_pool_path=pool_path,
                dynamic_plan_path=method_outputs["dynamic_plan"],
                visual_decision_path=visual_decision_path,
                output_path=method_dir / "executable_p0_plan.json",
            )
            # Stable top-level alias retained for existing run tooling; the
            # immutable phase-two source remains in the method directory.
            shutil.copy2(p0_plan, output_dir / f"{arts.stem}_plan.json")
            p0_paths = prepare_p0_candidate(
                p0_base_storyboard_path,
                output_dir=output_dir,
                plan_path=p0_plan,
                proposition_graph_path=graph_path,
                visual_decision_path=visual_decision_path,
                compiled_visual_manifest_path=compiled_visual_manifest_path,
                compiled_visual_bindings=compiled_visual_bindings,
            )
            arts.storyboard_path = p0_paths.candidate_storyboard_path
            candidate = json.loads(arts.storyboard_path.read_text(encoding="utf-8"))
            _carry_measured_p0_timing(candidate_before_plan, candidate)
            arts.storyboard_path.write_text(
                json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"  P0 phase-two plan: {p0_plan}")
        apply_p0_event_schedule(p0_paths, sentence_cues=p0_sentence_cues)

    if not arts.audio_dir or arts.total_sec <= 0:
        raise RuntimeError("配音未成功，无法确定录制时长 / 合成音轨")

    if require_review:
        from textbook2video.pipeline.review import ensure_review_approved

        ensure_review_approved(arts.storyboard_path)
        print(f"  人工审核: approved ({arts.storyboard_path})")

    # 2) 出画面 HTML
    print("\n" + "=" * 56)
    print("[2/4] 渲染动画 HTML")
    print("=" * 56)
    if from_html:
        html_path = Path(from_html)
        if not html_path.exists():
            raise FileNotFoundError(f"HTML 文件不存在: {html_path}")
        print(f"  复用已有 HTML: {html_path}")
    else:
        from textbook2video.animation_gen import generate as animate

        anim_kwargs: dict = dict(
            output_dir=output_dir, batch_size=batch_size, theme_id=theme,
            layout_repair_attempts=repair, layout_browser_channel=browser,
            skip_image_gen=no_images,
        )
        if p0_research or default_visual_tools:
            # Formal P0 treatment stays explicit; the default course repair
            # loop must not silently become an experimental variable.
            anim_kwargs["visual_tools_enabled"] = False
        if model:
            anim_kwargs["model"] = model
        html_path = animate(str(arts.storyboard_path), **anim_kwargs)

    from textbook2video.pipeline.artifact_integrity import write_render_manifest

    manifest_path = write_render_manifest(
        arts.storyboard_path, html_path, audio_dir=arts.audio_dir
    )
    print(f"  产物校验通过: {manifest_path}")

    # 3) 录制无声视频（录满音频总时长 + 1s 余量，保证最后一页不被切）
    print("\n" + "=" * 56)
    print("[3/4] 录制画面（无声）")
    print("=" * 56)
    rec_duration = math.ceil(arts.total_sec) + 1
    silent_mp4 = output_dir / f"{arts.stem}_silent.mp4"
    from textbook2video.research.proposition_schema import enabled as research_v2_enabled
    p0_runtime_trace_path = (
        output_dir / f"{arts.stem}_browser_runtime_trace.json"
        if p0_paths is not None or research_v2_enabled() else None
    )
    record_html_to_video(
        str(html_path), str(silent_mp4),
        duration=rec_duration, fps=fps, browser_channel=browser,
        trace_path=str(p0_runtime_trace_path) if p0_runtime_trace_path else None,
    )

    # 4) 拼接配音并合成有声成片（-shortest 按音轨裁掉视频尾部余量）
    print("\n" + "=" * 56)
    print("[4/4] 合成配音")
    print("=" * 56)
    final_mp4 = output_dir / f"{arts.stem}.mp4"
    subtitle_path = None
    if subtitles:
        subtitle_path = output_dir / f"{arts.stem}.srt"
        sentence_cues_path = arts.audio_dir / "sentence_cues.json"
        sentence_cues = None
        if sentence_cues_path.is_file():
            try:
                sentence_cues = json.loads(sentence_cues_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                sentence_cues = None
        storyboard_for_subtitles = json.loads(
            arts.storyboard_path.read_text(encoding="utf-8")
        )
        generate_srt(storyboard_for_subtitles, subtitle_path, sentence_cues=sentence_cues)
        print(f"  字幕: {subtitle_path}")
    compose_video(silent_mp4, arts.audio_dir, final_mp4, subtitle_path=subtitle_path)
    if research_v2_enabled():
        from textbook2video.research.render_evidence import write_render_evidence

        rendered_storyboard = json.loads(arts.storyboard_path.read_text(encoding="utf-8"))
        planned_events = [
            {**animation, "id": (animation.get("research_generation_v2") or {}).get("event_id")}
            for segment in rendered_storyboard.get("segments", []) if isinstance(segment, dict)
            for animation in segment.get("animations", []) if isinstance(animation, dict)
        ]
        trace_document = None
        if p0_runtime_trace_path and p0_runtime_trace_path.is_file():
            trace_document = json.loads(p0_runtime_trace_path.read_text(encoding="utf-8"))
        write_render_evidence(
            video_path=final_mp4, runtime_trace=trace_document, planned_events=planned_events,
            output_path=output_dir / f"{arts.stem}_render_evidence_v2.json",
            case_id=arts.stem.replace("_", "-"),
        )
    if p0_paths is not None:
        from textbook2video.research.p0_integration import finalize_p0_render_evidence

        finalize_p0_render_evidence(
            p0_paths,
            html_path=html_path,
            video_path=final_mp4,
            runtime_trace_path=p0_runtime_trace_path,
        )
    if not keep_intermediate:
        silent_mp4.unlink(missing_ok=True)

    if quality_report:
        report_path = output_dir / f"{arts.stem}_quality.json"
        write_quality_report(
            arts.storyboard_path,
            report_path,
            audio_dir=arts.audio_dir,
            subtitle_path=subtitle_path,
            final_video=final_mp4,
            output_dir=output_dir,
            lesson_plan_path=arts.lesson_plan_path,
        )
        print(f"  质量报告: {report_path}")

    print("\n" + "=" * 56)
    print(f"✅ 成片: {final_mp4}  （约 {round(arts.total_sec, 1)}s，含配音）")
    print("=" * 56)
    return final_mp4
