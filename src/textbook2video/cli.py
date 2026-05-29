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

    lesson_list = subparsers.add_parser("list-lessons", help="List detected lessons in a PDF")
    lesson_list.add_argument("input", help="Input textbook PDF file path")
    lesson_list.set_defaults(func=cmd_list_lessons)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
