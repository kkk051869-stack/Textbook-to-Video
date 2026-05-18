"""
CLI 入口：t2v 命令

用法:
  t2v record <input.html> <output.mp4> [--duration 30]
  t2v generate <input.pdf> --output output/     (开发中)
"""

import argparse
import sys


def cmd_record(args):
    from textbook2video.pipeline.recorder import record_html_to_video

    record_html_to_video(args.input, args.output, duration=args.duration)


def cmd_generate(args):
    print("Pipeline generate 功能开发中...")
    print(f"  输入: {args.input}")
    print(f"  输出: {args.output}")
    sys.exit(1)


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
    rec.set_defaults(func=cmd_record)

    # t2v generate
    gen = subparsers.add_parser("generate", help="完整 Pipeline（开发中）")
    gen.add_argument("input", help="输入教材文件路径")
    gen.add_argument("--output", default="output/", help="输出目录")
    gen.set_defaults(func=cmd_generate)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
