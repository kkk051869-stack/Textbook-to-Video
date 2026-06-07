"""CLI entry point for the ``t2v`` command."""

import argparse
import json
import sys
from pathlib import Path


def cmd_record(args):
    from textbook2video.pipeline.recorder import record_html_to_video

    record_html_to_video(
        args.input,
        args.output,
        duration=args.duration,
        fps=args.fps,
    )


def _detect_input_type(filepath: str) -> str:
    """Detect input file type by extension. Returns 'pdf' or 'docx'."""
    ext = Path(filepath).suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext in (".docx", ".doc"):
        return "docx"
    raise ValueError(f"不支持的文件格式: {ext}，仅支持 .pdf 和 .docx")


def _get_parser(filepath: str):
    """Return the appropriate parser module based on file type."""
    ftype = _detect_input_type(filepath)
    if ftype == "pdf":
        from textbook2video.pipeline import parser as mod
    else:
        from textbook2video.pipeline import docx_parser as mod
    return mod, ftype


def cmd_generate(args):
    """Run the textbook-to-storyboard generation steps (PDF or DOCX)."""
    from textbook2video.pipeline.scriptwriter import generate_script
    from textbook2video.pipeline.storyboard import generate_storyboard

    parser_mod, ftype = _get_parser(args.input)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"{'=' * 50}")
    print(f"Textbook: {args.input} ({ftype.upper()})")
    print(f"Lesson/Section: {args.lesson}")
    print(f"Model: {args.model or 'ecnu-max (default)'}")
    print(f"{'=' * 50}")

    print("\n[Step 1] Extracting lesson text...")
    lesson = parser_mod.extract_lesson_info(args.input, args.lesson)
    if ftype == "docx":
        print(f"  Section title: {lesson.get('title', 'N/A')}")
    else:
        print(f"  Pages: {lesson['pages'][0]}-{lesson['pages'][1]}")
    print(f"  Text length: {len(lesson['text'])}")

    raw_path = output_dir / f"lesson{args.lesson}_raw.txt"
    raw_path.write_text(lesson["text"], encoding="utf-8")
    print(f"  Saved: {raw_path}")

    print("\n[Step 2] Generating script...")
    script_segments = generate_script(lesson["text"], model=args.model)
    print(f"  Generated {len(script_segments)} script segment(s)")

    for i, seg in enumerate(script_segments, 1):
        print(f"  Segment {i} ({len(seg)} chars): {seg[:80]}...")

    script_path = output_dir / f"lesson{args.lesson}_script.txt"
    with open(script_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(script_segments, 1):
            f.write(f"Segment {i}:\n{seg}\n\n")
    print(f"  Saved: {script_path}")

    print("\n[Step 3] Generating storyboard...")
    lesson_title = lesson.get("title") or f"Lesson {args.lesson}"
    storyboard = generate_storyboard(
        script_segments,
        lesson_title=lesson_title,
        model=args.model,
    )
    print(f"  Generated {len(storyboard['segments'])} storyboard segment(s)")

    storyboard_path = output_dir / f"lesson{args.lesson}_storyboard.json"
    with open(storyboard_path, "w", encoding="utf-8") as f:
        json.dump(storyboard, f, ensure_ascii=False, indent=2)
    print(f"  Saved: {storyboard_path}")

    if not args.skip_tts:
        print("\n[Step 4] Generating TTS audio...")
        from textbook2video.pipeline.narrator import generate_audio, get_audio_duration

        narrations = [seg["narration"] for seg in storyboard["segments"]]
        audio_dir = output_dir / f"lesson{args.lesson}_audio"
        audio_files = generate_audio(narrations, output_dir=str(audio_dir))

        durations = []
        for audio_file in audio_files:
            try:
                duration = get_audio_duration(str(audio_file))
                durations.append(round(duration, 1))
            except ValueError:
                durations.append(0)

        for i, seg in enumerate(storyboard["segments"]):
            seg["audio_duration_sec"] = durations[i]

        print(f"  Audio durations: {durations}")
        print(f"  Total duration: {sum(durations)} seconds")

        with open(storyboard_path, "w", encoding="utf-8") as f:
            json.dump(storyboard, f, ensure_ascii=False, indent=2)
        print(f"  Updated storyboard with audio durations: {storyboard_path}")

    print(f"\n{'=' * 50}")
    print(f"Done. Output directory: {output_dir}")
    print(f"{'=' * 50}")


def cmd_generate_docx(args):
    """Run the DOCX-to-storyboard generation (text + images in one pass)."""
    from textbook2video.pipeline.parser import extract_section_from_docx
    from textbook2video.pipeline.scriptwriter import generate_script
    from textbook2video.pipeline.storyboard import generate_storyboard

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    image_dir = output_dir / "images"

    section_id = f"ch{args.chapter}_s{args.section}"

    print(f"{'=' * 50}")
    print(f"教材: {args.input}")
    print(f"章节: chapter={args.chapter}, section={args.section}")
    print(f"模型: {args.model or 'ecnu-max (默认)'}")
    print(f"{'=' * 50}")

    # Step 1: 提取文本 + 图片（一次解析）
    print("\n[Step 1] 提取章节文本和图片...")
    result = extract_section_from_docx(
        args.input,
        chapter_number=args.chapter,
        section_number=args.section,
        include_images=True,
        image_output_dir=str(image_dir),
    )
    text = result["text"]
    images = result["images"]
    print(f"  文本: {len(text)} 字符")
    print(f"  图片: {len(images)} 张")
    for img in images:
        print(f"    {img['id']}: {img['description']}")

    raw_path = output_dir / f"{section_id}_raw.txt"
    raw_path.write_text(text, encoding="utf-8")
    print(f"  已保存: {raw_path}")

    # Step 2: 生成讲稿
    print("\n[Step 2] 生成讲稿...")
    script_segments = generate_script(text, model=args.model)
    print(f"  生成 {len(script_segments)} 段讲稿")

    script_path = output_dir / f"{section_id}_script.txt"
    with open(script_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(script_segments, 1):
            f.write(f"第{i}段：\n{seg}\n\n")
    print(f"  已保存: {script_path}")

    # Step 3: 生成画面大纲（带可用图片列表）
    print("\n[Step 3] 生成画面大纲...")
    storyboard = generate_storyboard(
        script_segments,
        lesson_title=f"第{args.chapter + 1}章",
        model=args.model,
        available_images=images if images else None,
    )
    print(f"  生成 {len(storyboard['segments'])} 页画面")

    # 把图片信息写入 metadata
    if images:
        storyboard["metadata"]["available_images"] = images

    storyboard_path = output_dir / f"{section_id}_storyboard.json"
    with open(storyboard_path, "w", encoding="utf-8") as f:
        json.dump(storyboard, f, ensure_ascii=False, indent=2)
    print(f"  已保存: {storyboard_path}")

    # Step 4: TTS
    if not args.skip_tts:
        print("\n[Step 4] 生成 TTS 配音...")
        from textbook2video.pipeline.narrator import generate_audio, get_audio_duration

        narrations = [seg["narration"] for seg in storyboard["segments"]]
        audio_dir = output_dir / f"{section_id}_audio"
        audio_files = generate_audio(narrations, output_dir=str(audio_dir))

        durations = []
        for audio_file in audio_files:
            try:
                dur = get_audio_duration(str(audio_file))
                durations.append(round(dur, 1))
            except ValueError:
                durations.append(0)

        for i, seg in enumerate(storyboard["segments"]):
            seg["audio_duration_sec"] = durations[i]

        print(f"  音频时长: {durations}")
        print(f"  总时长: {sum(durations)} 秒")

        with open(storyboard_path, "w", encoding="utf-8") as f:
            json.dump(storyboard, f, ensure_ascii=False, indent=2)
        print(f"  已更新 (含音频时长): {storyboard_path}")

    print(f"\n{'=' * 50}")
    print(f"完成！输出目录: {output_dir}")
    print(f"{'=' * 50}")


def cmd_list_lessons(args):
    """List lessons/sections detected in a PDF or DOCX."""
    parser_mod, ftype = _get_parser(args.input)
    lessons = parser_mod.list_lessons(args.input)

    print(f"\nTextbook: {args.input} ({ftype.upper()})")
    print(f"Detected sections: {len(lessons)}\n")
    for lesson in lessons:
        if ftype == "docx":
            title = lesson.get("title", "")
            print(
                f"  Section {lesson['lesson_number']:2d}: {title} "
                f"({lesson['para_count']} paragraphs)"
                if "para_count" in lesson
                else f"  Section {lesson['lesson_number']:2d}: {title}"
            )
        else:
            print(
                f"  Lesson {lesson['lesson_number']:2d} "
                f"(pages {lesson['pages'][0]}-{lesson['pages'][1]}, "
                f"{lesson['page_count']} pages)"
            )


def cmd_validate(args):
    """静态校验 storyboard JSON（element 类型/必填字段/图片 src 存在性）。"""
    from textbook2video.pipeline.checks import validate_storyboard

    sb_path = Path(args.input)
    storyboard = json.loads(sb_path.read_text(encoding="utf-8"))

    # 推导同级 <stem>_script.txt 用于段数一致性比对（可被 --script 覆盖）
    if args.script:
        script_path = Path(args.script)
    else:
        stem = sb_path.stem
        if stem.endswith("_storyboard"):
            stem = stem[: -len("_storyboard")]
        script_path = sb_path.parent / f"{stem}_script.txt"

    rep = validate_storyboard(
        storyboard, base_dir=sb_path.parent, script_path=script_path
    )

    for w in rep.warnings:
        print(f"  ⚠️  {w}")
    for e in rep.errors:
        print(f"  ❌ {e}")

    if rep.ok:
        print(f"✅ 校验通过（{len(rep.warnings)} 条建议）: {sb_path}")
    else:
        print(f"\n发现 {len(rep.errors)} 个错误、{len(rep.warnings)} 条建议: {sb_path}")
        sys.exit(1)


def cmd_doctor(args):
    """预检运行环境：LLM 凭据 / ffmpeg / 浏览器 / TTS /（可选）LLM 连通。"""
    from textbook2video.pipeline.checks import run_doctor

    results = run_doctor(browser_channel=args.browser, ping=args.ping)
    print("环境自检：\n")
    failed_required = False
    for r in results:
        mark = "✅" if r.ok else ("❌" if r.required else "⚠️ ")
        tag = "" if r.required else "（可选）"
        print(f"  {mark} {r.name}{tag}: {r.detail}")
        if not r.ok and r.required:
            failed_required = True
    if failed_required:
        print("\n存在必需项未通过，先修复再跑流水线。")
        sys.exit(1)
    print("\n环境就绪。")


def cmd_batch(args):
    """批处理：对多个课节依次跑 produce，单个失败不影响其余。"""
    from textbook2video.pipeline.checks import parse_lesson_specs, parse_section_specs
    from textbook2video.pipeline.orchestrator import produce

    jobs: list[dict] = []
    if args.sections:
        for c, s in parse_section_specs(args.sections):
            jobs.append({"chapter": c, "section": s, "label": f"ch{c}_s{s}"})
    elif args.lessons:
        for n in parse_lesson_specs(args.lessons):
            jobs.append({"lesson": n, "label": f"lesson{n}"})
    else:
        sys.exit("错误：需指定 --sections（DOCX，如 '3:0,3:1'）或 --lessons（PDF，如 '1,2'）")

    print(f"批处理 {len(jobs)} 个课节...\n")
    outcomes: list[tuple[str, str]] = []
    for i, job in enumerate(jobs, 1):
        label = job.pop("label")
        print(f"\n{'#' * 56}\n# [{i}/{len(jobs)}] {label}\n{'#' * 56}")
        try:
            out = produce(
                args.input, output_dir=args.output, theme=args.theme,
                model=args.model, no_images=args.no_images, repair=args.repair,
                browser=args.browser, batch_size=args.batch_size, **job,
            )
            outcomes.append((label, f"✅ {out}"))
        except Exception as exc:  # noqa: BLE001
            outcomes.append((label, f"❌ {type(exc).__name__}: {exc}"))
            print(f"  [跳过] {label} 失败: {exc}")

    print(f"\n{'=' * 56}\n批处理结果：")
    for label, status in outcomes:
        print(f"  {label}: {status}")
    if any(s.startswith("❌") for _, s in outcomes):
        sys.exit(1)


def cmd_script(args):
    """只生成讲稿（解析 + 讲稿分段），产出 *_raw.txt 与 *_script.txt。"""
    from textbook2video.pipeline.orchestrator import build_script

    if args.chapter is None and args.lesson is None:
        sys.exit("错误：需指定 --lesson（PDF）或 --chapter + --section（DOCX）")
    if args.chapter is not None and args.section is None:
        sys.exit("错误：--chapter 必须配合 --section 一起使用")

    result = build_script(
        args.input, lesson=args.lesson, chapter=args.chapter,
        section=args.section, output_dir=args.output, model=args.model,
    )
    print(f"\nOutput: {result['script_path']}")


def cmd_storyboard(args):
    """从已有 *_script.txt 重新生成画面大纲 JSON（可选再配音）。"""
    from textbook2video.pipeline.orchestrator import build_storyboard_from_script

    arts = build_storyboard_from_script(
        args.input, output_dir=args.output, title=args.title, model=args.model,
        images=args.images, skip_tts=args.skip_tts, voice=args.voice, rate=args.rate,
    )
    print(f"\nOutput: {arts.storyboard_path}")


def cmd_narrate(args):
    """读 storyboard.json 重新生成 TTS 配音，并回写 audio_duration_sec。"""
    from textbook2video.pipeline.compose import resolve_audio_dir
    from textbook2video.pipeline.orchestrator import run_tts

    sb_path = Path(args.input)
    storyboard = json.loads(sb_path.read_text(encoding="utf-8"))
    if "segments" not in storyboard or not storyboard["segments"]:
        sys.exit("错误：JSON 中没有 segments，无法配音")

    audio_dir = Path(args.audio_dir) if args.audio_dir else resolve_audio_dir(sb_path)
    print(f"配音 → {audio_dir}（共 {len(storyboard['segments'])} 段）")
    run_tts(storyboard, sb_path, audio_dir, voice=args.voice, rate=args.rate)


def cmd_mux(args):
    """把分段 TTS 配音合成到已录制的视频上，输出有声 MP4。"""
    from textbook2video.pipeline.compose import compose_video, resolve_audio_dir

    audio_dir = resolve_audio_dir(args.audio)
    if not audio_dir.is_dir():
        sys.exit(f"错误：音频目录不存在: {audio_dir}")

    out = args.output or str(
        Path(args.video).with_name(Path(args.video).stem + "_voiced.mp4")
    )
    final = compose_video(args.video, audio_dir, out)
    print(f"\n有声成片: {final}")


def cmd_produce(args):
    """端到端：教材 → 有声成片 MP4（generate → animate → record → mux）。"""
    import os as _os

    from textbook2video.pipeline.orchestrator import produce

    if getattr(args, "free_form", False):
        _os.environ["T2V_DISABLE_TEMPLATE_RENDERER"] = "1"

    if args.chapter is None and args.lesson is None:
        sys.exit("错误：需指定 --lesson（PDF）或 --chapter + --section（DOCX）")
    if args.chapter is not None and args.section is None:
        sys.exit("错误：--chapter 必须配合 --section 一起使用")

    final = produce(
        args.input,
        lesson=args.lesson,
        chapter=args.chapter,
        section=args.section,
        output_dir=args.output,
        theme=args.theme,
        model=args.model,
        no_images=args.no_images,
        repair=args.repair,
        browser=args.browser,
        batch_size=args.batch_size,
        voice=args.voice,
        rate=args.rate,
        fps=args.fps,
        keep_intermediate=args.keep_intermediate,
    )
    print(f"\nOutput: {final}")


def cmd_animate(args):
    """Generate HTML animation from a storyboard JSON."""
    import os as _os

    from textbook2video.animation_gen import generate

    # --free-form：禁用确定性模板，全部页交 LLM 自由发挥（更灵动但更不稳，
    # 靠布局 QA + 修复兜底）。等价于设 T2V_DISABLE_TEMPLATE_RENDERER=1。
    if getattr(args, "free_form", False):
        _os.environ["T2V_DISABLE_TEMPLATE_RENDERER"] = "1"

    output_dir = Path(args.output) if args.output else None
    kwargs = dict(
        output_dir=output_dir,
        batch_size=args.batch_size,
        theme_id=args.theme,
        layout_repair_attempts=args.repair,
        layout_browser_channel=args.browser,
        skip_image_gen=getattr(args, "no_images", False),
    )
    if args.model:
        kwargs["model"] = args.model
    result = generate(args.input, **kwargs)
    print(f"\n{'=' * 50}")
    print(f"Output: {result}")
    print(f"{'=' * 50}")


def main():
    parser = argparse.ArgumentParser(
        prog="t2v",
        description="Textbook-to-Video: create narrated teaching videos from textbooks.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    rec = subparsers.add_parser("record", help="Record animation HTML to MP4")
    rec.add_argument("input", help="Input HTML file path")
    rec.add_argument("output", help="Output MP4 file path")
    rec.add_argument("--duration", type=int, default=30, help="Recording duration in seconds")
    rec.add_argument("--fps", type=int, default=30, help="Frame rate, default 30")
    rec.set_defaults(func=cmd_record)

    gen = subparsers.add_parser("generate", help="Generate script and storyboard from a PDF or DOCX")
    gen.add_argument("input", help="Input textbook file path (PDF or DOCX)")
    gen.add_argument("--lesson", "-l", type=int, required=True, help="Lesson number")
    gen.add_argument("--output", "-o", default="output/", help="Output directory, default output/")
    gen.add_argument("--model", "-m", default=None, help="LLM model name")
    gen.add_argument("--skip-tts", action="store_true", help="Skip TTS generation")
    gen.set_defaults(func=cmd_generate)

    gen_docx = subparsers.add_parser("generate-docx", help="从 DOCX 教材生成讲稿+画面大纲（含图片提取）")
    gen_docx.add_argument("input", help="DOCX 文件路径")
    gen_docx.add_argument("--chapter", "-c", type=int, required=True, help="章序号（0-based）")
    gen_docx.add_argument("--section", "-s", type=int, required=True, help="节序号（0-based，章内）")
    gen_docx.add_argument("--output", "-o", default="output/", help="输出目录")
    gen_docx.add_argument("--model", "-m", default=None, help="LLM 模型名")
    gen_docx.add_argument("--skip-tts", action="store_true", help="跳过 TTS 配音")
    gen_docx.set_defaults(func=cmd_generate_docx)

    lesson_list = subparsers.add_parser("list-lessons", help="List detected lessons/sections in a PDF or DOCX")
    lesson_list.add_argument("input", help="Input textbook file path (PDF or DOCX)")
    lesson_list.set_defaults(func=cmd_list_lessons)

    val = subparsers.add_parser(
        "validate",
        help="静态校验 storyboard JSON（element 类型/必填字段/图片 src 存在性）",
    )
    val.add_argument("input", help="storyboard JSON 路径")
    val.add_argument("--script", default=None,
                     help="讲稿 *_script.txt（用于段数一致性比对，默认找同级文件）")
    val.set_defaults(func=cmd_validate)

    doc = subparsers.add_parser(
        "doctor",
        help="预检运行环境：LLM 凭据 / ffmpeg / 浏览器 / TTS",
    )
    doc.add_argument("--browser", default="msedge", help="要探测的浏览器通道（默认 msedge）")
    doc.add_argument("--ping", action="store_true", help="额外做一次 LLM 连通测试（走网络）")
    doc.set_defaults(func=cmd_doctor)

    bat = subparsers.add_parser(
        "batch",
        help="批处理：对多个课节依次跑 produce（单个失败不影响其余）",
    )
    bat.add_argument("input", help="教材文件路径（PDF 或 DOCX）")
    bat.add_argument("--sections", default=None,
                     help="DOCX 章节列表，如 '3:0,3:1,4:0'（chapter:section）")
    bat.add_argument("--lessons", default=None, help="PDF 课号列表，如 '1,2,4'")
    bat.add_argument("--output", "-o", default="output/", help="输出目录")
    bat.add_argument("--theme", "-t", default=None, help="主题")
    bat.add_argument("--model", "-m", default=None, help="LLM 模型名（推荐 ecnu-plus）")
    bat.add_argument("--no-images", action="store_true", help="跳过 AI 配图")
    bat.add_argument("--repair", type=int, default=2, help="布局修复轮数")
    bat.add_argument("--batch-size", "-b", type=int, default=4, help="每批页数")
    bat.add_argument("--browser", default="msedge", help="录制/布局浏览器通道")
    bat.set_defaults(func=cmd_batch)

    scr = subparsers.add_parser(
        "script",
        help="只生成讲稿（解析+讲稿分段 → *_script.txt），便于先审讲稿再做画面",
    )
    scr.add_argument("input", help="教材文件路径（PDF 或 DOCX）")
    scr.add_argument("--lesson", "-l", type=int, default=None, help="课号（PDF）")
    scr.add_argument("--chapter", "-c", type=int, default=None, help="章序号（DOCX，0-based）")
    scr.add_argument("--section", "-s", type=int, default=None, help="节序号（DOCX，0-based）")
    scr.add_argument("--output", "-o", default="output/", help="输出目录")
    scr.add_argument("--model", "-m", default=None, help="LLM 模型名（推荐 ecnu-plus）")
    scr.set_defaults(func=cmd_script)

    sb = subparsers.add_parser(
        "storyboard",
        help="从已有 *_script.txt 重新生成画面大纲 JSON（讲稿满意、只想重做画面时用）",
    )
    sb.add_argument("input", help="*_script.txt 路径")
    sb.add_argument("--output", "-o", default=None, help="输出目录（默认与 script 同级）")
    sb.add_argument("--title", default=None, help="课程标题（默认按文件名推测）")
    sb.add_argument("--model", "-m", default=None, help="LLM 模型名（推荐 ecnu-plus）")
    sb.add_argument("--images", default=None,
                    help="教材图清单 JSON（images.json 或旧 storyboard.json）")
    sb.add_argument("--skip-tts", action="store_true", default=True,
                    help="不配音（默认；storyboard 步通常先不配音）")
    sb.add_argument("--tts", dest="skip_tts", action="store_false",
                    help="同时生成 TTS 配音")
    sb.add_argument("--voice", default=None, help="TTS 语音")
    sb.add_argument("--rate", default=None, help="TTS 语速")
    sb.set_defaults(func=cmd_storyboard)

    narr = subparsers.add_parser(
        "narrate",
        help="读 storyboard.json 重新生成 TTS 配音并回写 audio_duration_sec",
    )
    narr.add_argument("input", help="storyboard JSON 路径")
    narr.add_argument("--audio-dir", default=None,
                      help="音频输出目录（默认同级 <stem>_audio）")
    narr.add_argument("--voice", default=None, help="TTS 语音（默认 zh-CN-XiaoxiaoNeural）")
    narr.add_argument("--rate", default=None, help="TTS 语速（默认 +5%%）")
    narr.set_defaults(func=cmd_narrate)

    mux = subparsers.add_parser(
        "mux",
        help="把分段 TTS 配音合成到已录制视频上（输出有声 MP4）",
    )
    mux.add_argument("video", help="已录制的（无声）视频路径")
    mux.add_argument("audio", help="音频目录（含 sN.mp3）或 storyboard.json（推导同级音频目录）")
    mux.add_argument("--output", "-o", default=None,
                     help="输出路径（默认 <video>_voiced.mp4）")
    mux.set_defaults(func=cmd_mux)

    prod = subparsers.add_parser(
        "produce",
        help="端到端：教材 → 有声成片 MP4（generate→animate→record→配音合成，一步到位）",
    )
    prod.add_argument("input", help="教材文件路径（PDF 或 DOCX）")
    prod.add_argument("--lesson", "-l", type=int, default=None, help="课号（PDF，页码表）")
    prod.add_argument("--chapter", "-c", type=int, default=None, help="章序号（DOCX，0-based）")
    prod.add_argument("--section", "-s", type=int, default=None, help="节序号（DOCX，0-based）")
    prod.add_argument("--output", "-o", default="output/", help="输出目录")
    prod.add_argument("--theme", "-t", default=None,
                      help="主题: bright | dark-blue-academic | 3b1b-math")
    prod.add_argument("--model", "-m", default=None, help="LLM 模型名（推荐 ecnu-plus）")
    prod.add_argument("--no-images", action="store_true", help="跳过 AI 配图，全用 SVG/CSS")
    prod.add_argument("--repair", type=int, default=2, help="布局修复轮数（默认 2）")
    prod.add_argument("--batch-size", "-b", type=int, default=4, help="每批页数（默认 4）")
    prod.add_argument("--browser", default="msedge", help="录制/布局浏览器通道（默认 msedge）")
    prod.add_argument("--voice", default=None, help="TTS 语音（默认 zh-CN-XiaoxiaoNeural）")
    prod.add_argument("--rate", default=None, help="TTS 语速（默认 +5%%）")
    prod.add_argument("--fps", type=int, default=30, help="录制帧率（默认 30）")
    prod.add_argument("--keep-intermediate", action="store_true", help="保留无声中间视频")
    prod.add_argument("--free-form", action="store_true",
                      help="禁用确定性模板，全部页交 LLM 自由发挥（更灵动但更不稳）")
    prod.set_defaults(func=cmd_produce)

    anim = subparsers.add_parser("animate", help="Generate HTML animation from storyboard JSON")
    anim.add_argument("input", help="Storyboard JSON file path")
    anim.add_argument("--output", "-o", default=None, help="Output directory (default: output/)")
    anim.add_argument("--theme", "-t", default=None,
                      help="Theme ID: bright, 3b1b-math, dark-blue-academic")
    anim.add_argument("--model", "-m", default=None, help="LLM model name")
    anim.add_argument("--batch-size", "-b", type=int, default=4, help="Slides per batch (default: 4)")
    anim.add_argument("--repair", type=int, default=2, help="Max layout repair attempts (default: 2)")
    anim.add_argument("--browser", default="msedge",
                      help="Browser channel for layout QA (default: msedge)")
    anim.add_argument("--no-images", action="store_true",
                      help="Skip AI image generation, use SVG/CSS for all visuals")
    anim.add_argument("--free-form", action="store_true",
                      help="禁用确定性模板，全部页交 LLM 自由发挥（更灵动但更不稳）")
    anim.set_defaults(func=cmd_animate)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
