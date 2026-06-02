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


def cmd_generate(args):
    """Run the PDF-to-storyboard generation steps."""
    from textbook2video.pipeline.parser import extract_lesson_info
    from textbook2video.pipeline.scriptwriter import generate_script
    from textbook2video.pipeline.storyboard import generate_storyboard

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"{'=' * 50}")
    print(f"Textbook: {args.input}")
    print(f"Lesson: {args.lesson}")
    print(f"Model: {args.model or 'ecnu-max (default)'}")
    print(f"{'=' * 50}")

    print("\n[Step 1] Extracting lesson text...")
    lesson = extract_lesson_info(args.input, args.lesson)
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
    lesson_title = f"Lesson {args.lesson}"
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
    """List lessons detected in a PDF."""
    from textbook2video.pipeline.parser import list_lessons

    lessons = list_lessons(args.input)
    print(f"\nTextbook: {args.input}")
    print(f"Detected lessons: {len(lessons)}\n")
    for lesson in lessons:
        print(
            f"  Lesson {lesson['lesson_number']:2d} "
            f"(pages {lesson['pages'][0]}-{lesson['pages'][1]}, {lesson['page_count']} pages)"
        )


def cmd_animate(args):
    """Generate HTML animation from a storyboard JSON."""
    from textbook2video.animation_gen import generate

    output_dir = Path(args.output) if args.output else None
    result = generate(
        args.input,
        output_dir=output_dir,
        model=args.model,
        batch_size=args.batch_size,
        theme_id=args.theme,
        layout_repair_attempts=args.repair,
        layout_browser_channel=args.browser,
    )
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

    gen = subparsers.add_parser("generate", help="Generate script and storyboard from a textbook PDF")
    gen.add_argument("input", help="Input textbook PDF file path")
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

    lesson_list = subparsers.add_parser("list-lessons", help="List detected lessons in a PDF")
    lesson_list.add_argument("input", help="Input textbook PDF file path")
    lesson_list.set_defaults(func=cmd_list_lessons)

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
    anim.set_defaults(func=cmd_animate)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
