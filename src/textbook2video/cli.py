"""
CLI 入口：t2v 命令

用法:
  t2v record <input.html> <output.mp4> [--duration 30] [--fps 30]
  t2v generate <input.pdf> --lesson <课号> [--output output/] [--model 模型名]
  t2v generate <input.pdf> --lesson <课号> --skip-tts    # 只生成讲稿+大纲，不做TTS
  t2v list-lessons <input.pdf>                             # 列出可提取的课程
"""

import argparse
import json
import sys
from pathlib import Path


def cmd_record(args):
    from textbook2video.pipeline.recorder import record_html_to_video

    record_html_to_video(
        args.input, args.output,
        duration=args.duration,
        fps=args.fps,
    )


def cmd_generate(args):
    """t2v generate 端到端命令"""
    from textbook2video.pipeline.parser import extract_lesson_info
    from textbook2video.pipeline.scriptwriter import generate_script
    from textbook2video.pipeline.storyboard import generate_storyboard

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"{'='*50}")
    print(f"教材: {args.input}")
    print(f"课号: 第{args.lesson}课")
    print(f"模型: {args.model or 'ecnu-max (默认)'}")
    print(f"{'='*50}")

    # ── Step 1: PDF 提取 ──
    print("\n[Step 1] 提取教材内容...")
    lesson = extract_lesson_info(args.input, args.lesson)
    print(f"  页码范围: 第{lesson['pages'][0]}-{lesson['pages'][1]}页")
    print(f"  文本长度: {len(lesson['text'])} 字符")

    # 保存教材原文（调试用）
    raw_path = output_dir / f"lesson{args.lesson}_raw.txt"
    raw_path.write_text(lesson["text"], encoding="utf-8")
    print(f"  已保存: {raw_path}")

    # ── Step 2: 讲稿生成 ──
    print("\n[Step 2] 生成讲稿...")
    script_segments = generate_script(lesson["text"], model=args.model)
    print(f"  生成 {len(script_segments)} 段讲稿")

    for i, seg in enumerate(script_segments, 1):
        print(f"  第{i}段 ({len(seg)}字): {seg[:80]}...")

    # 保存讲稿
    script_path = output_dir / f"lesson{args.lesson}_script.txt"
    with open(script_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(script_segments, 1):
            f.write(f"第{i}段：\n{seg}\n\n")
    print(f"  已保存: {script_path}")

    # ── Step 3: 画面大纲生成 ──
    print("\n[Step 3] 生成画面大纲...")
    lesson_title = f"第{args.lesson}课"
    storyboard = generate_storyboard(
        script_segments,
        lesson_title=lesson_title,
        model=args.model,
    )
    print(f"  生成 {len(storyboard['segments'])} 个画面段")

    # 保存画面大纲 JSON
    storyboard_path = output_dir / f"lesson{args.lesson}_storyboard.json"
    with open(storyboard_path, "w", encoding="utf-8") as f:
        json.dump(storyboard, f, ensure_ascii=False, indent=2)
    print(f"  已保存: {storyboard_path}")

    # ── Step 4: TTS 配音（可选） ──
    if not args.skip_tts:
        print("\n[Step 4] 生成 TTS 配音...")
        from textbook2video.pipeline.narrator import generate_audio, get_audio_duration

        narrations = [seg["narration"] for seg in storyboard["segments"]]
        audio_dir = output_dir / f"lesson{args.lesson}_audio"
        audio_files = generate_audio(narrations, output_dir=str(audio_dir))

        # 回填音频时长到 storyboard
        durations = []
        for af in audio_files:
            try:
                dur = get_audio_duration(str(af))
                durations.append(round(dur, 1))
            except ValueError:
                durations.append(0)

        for i, seg in enumerate(storyboard["segments"]):
            seg["audio_duration_sec"] = durations[i]

        print(f"  音频时长: {durations}")
        print(f"  总时长: {sum(durations)} 秒")

        # 重新保存带时长的 JSON
        with open(storyboard_path, "w", encoding="utf-8") as f:
            json.dump(storyboard, f, ensure_ascii=False, indent=2)
        print(f"  已更新 (含音频时长): {storyboard_path}")

    print(f"\n{'='*50}")
    print(f"✅ 完成！输出目录: {output_dir}")
    print(f"{'='*50}")


def cmd_list_lessons(args):
    """列出 PDF 中可提取的课程"""
    from textbook2video.pipeline.parser import list_lessons

    lessons = list_lessons(args.input)
    print(f"\n教材: {args.input}")
    print(f"可提取课程: {len(lessons)} 课\n")
    for l in lessons:
        print(f"  第{l['lesson_number']:2d}课  (第{l['pages'][0]}-{l['pages'][1]}页, {l['page_count']}页)")


def main():
    parser = argparse.ArgumentParser(
        prog="t2v",
        description="Textbook-to-Video: 教材 → 带动画配音的教学视频",
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # t2v record
    rec = subparsers.add_parser("record", help="录制动画 HTML 为视频")
    rec.add_argument("input", help="输入 HTML 文件路径")
    rec.add_argument("output", help="输出 MP4 文件路径")
    rec.add_argument("--duration", type=int, default=30, help="录制时长（秒）")
    rec.add_argument("--fps", type=int, default=30, help="帧率（默认 30）")
    rec.set_defaults(func=cmd_record)

    # t2v generate
    gen = subparsers.add_parser("generate", help="完整 Pipeline：教材 → 讲稿 → 画面大纲 → TTS")
    gen.add_argument("input", help="输入教材 PDF 文件路径")
    gen.add_argument("--lesson", "-l", type=int, required=True, help="课号（必填）")
    gen.add_argument("--output", "-o", default="output/", help="输出目录（默认 output/）")
    gen.add_argument("--model", "-m", default=None, help="LLM 模型名（默认 ecnu-max）")
    gen.add_argument("--skip-tts", action="store_true", help="跳过 TTS 配音，只生成讲稿+大纲")
    gen.set_defaults(func=cmd_generate)

    # t2v list-lessons
    ll = subparsers.add_parser("list-lessons", help="列出教材中可提取的课程")
    ll.add_argument("input", help="输入教材 PDF 文件路径")
    ll.set_defaults(func=cmd_list_lessons)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
