from __future__ import annotations

import csv
import json
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont


EXP_ROOT = Path("/ai/data/textbook-to-video/experiments/presentagent-comparison-v1")
INVENTORY_PATH = EXP_ROOT / "metrics/statistics/formal_video_inventory_24.csv"
OUTPUT_ROOT = EXP_ROOT / "metrics/visual_artifact_checks/formal_heuristic_v1"
FRAME_ROOT = OUTPUT_ROOT / "keyframes"
CONTACT_ROOT = OUTPUT_ROOT / "contact_sheets"
FRAME_POSITIONS = [0.08, 0.20, 0.32, 0.44, 0.56, 0.68, 0.80, 0.92]


@dataclass
class ProbeInfo:
    ok: bool
    duration_sec: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    codec: str = ""
    error: str = ""


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def parse_rate(value: str | None) -> float | None:
    if not value:
        return None
    if "/" in value:
        a, b = value.split("/", 1)
        try:
            den = float(b)
            return float(a) / den if den else None
        except ValueError:
            return None
    try:
        return float(value)
    except ValueError:
        return None


def run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)


def probe_video(video_path: Path) -> ProbeInfo:
    if not video_path.exists():
        return ProbeInfo(ok=False, error="missing_file")
    ffprobe = shutil.which("ffprobe") or "/ai/data/tools/bin/ffprobe"
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration,size,bit_rate:stream=codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,nb_frames",
        "-of",
        "json",
        str(video_path),
    ]
    result = run(cmd)
    if result.returncode != 0:
        return ProbeInfo(ok=False, error=result.stderr.strip()[:500] or "ffprobe_failed")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return ProbeInfo(ok=False, error=f"probe_json_error:{exc}")

    video_stream = None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            video_stream = stream
            break
    if not video_stream:
        return ProbeInfo(ok=False, error="no_video_stream")
    duration = data.get("format", {}).get("duration")
    try:
        duration_sec = float(duration) if duration is not None else None
    except ValueError:
        duration_sec = None
    return ProbeInfo(
        ok=True,
        duration_sec=duration_sec,
        width=int(video_stream.get("width") or 0) or None,
        height=int(video_stream.get("height") or 0) or None,
        fps=parse_rate(video_stream.get("avg_frame_rate")) or parse_rate(video_stream.get("r_frame_rate")),
        codec=video_stream.get("codec_name", ""),
    )


def extract_frame(video_path: Path, output_path: Path, timestamp: float) -> bool:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg") or "/ai/data/tools/bin/ffmpeg"
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{max(timestamp, 0):.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        "-y",
        str(output_path),
    ]
    result = run(cmd)
    return result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0


def analyze_frame(frame_path: Path) -> dict[str, Any]:
    img = Image.open(frame_path).convert("RGB")
    width, height = img.size
    scale = min(1.0, 640 / max(width, height))
    if scale < 1.0:
        img_small = img.resize((int(width * scale), int(height * scale)))
    else:
        img_small = img

    arr = np.asarray(img_small, dtype=np.float32)
    gray = arr.mean(axis=2)
    mean = float(gray.mean())
    std = float(gray.std())
    near_black_pct = float((gray < 18).mean())
    near_white_pct = float((gray > 238).mean())

    gx = np.abs(np.diff(gray, axis=1))
    gy = np.abs(np.diff(gray, axis=0))
    edge_density = float(((gx > 24).mean() + (gy > 24).mean()) / 2)

    border = np.concatenate([gray[:5, :].ravel(), gray[-5:, :].ravel(), gray[:, :5].ravel(), gray[:, -5:].ravel()])
    bg = float(np.median(border))
    content_mask = np.abs(gray - bg) > 26
    content_ratio = float(content_mask.mean())
    if content_mask.any():
        ys, xs = np.where(content_mask)
        bbox_area_ratio = float(((xs.max() - xs.min() + 1) * (ys.max() - ys.min() + 1)) / gray.size)
    else:
        bbox_area_ratio = 0.0

    blank_suspect = (std < 8 and edge_density < 0.004) or near_black_pct > 0.985 or near_white_pct > 0.985
    dark_suspect = mean < 28
    bright_suspect = mean > 245
    low_detail_suspect = std < 14 and edge_density < 0.008
    dense_visual_suspect = edge_density > 0.145
    possible_crop_suspect = content_ratio > 0.72 or bbox_area_ratio > 0.95

    flags = []
    if blank_suspect:
        flags.append("blank_or_static_suspect")
    if dark_suspect:
        flags.append("too_dark_suspect")
    if bright_suspect:
        flags.append("too_bright_suspect")
    if low_detail_suspect:
        flags.append("low_detail_suspect")
    if dense_visual_suspect:
        flags.append("overdense_visual_suspect")
    if possible_crop_suspect:
        flags.append("possible_crop_or_full_canvas_content")

    return {
        "frame_width": width,
        "frame_height": height,
        "mean_brightness": round(mean, 3),
        "contrast_std": round(std, 3),
        "near_black_pct": round(near_black_pct, 5),
        "near_white_pct": round(near_white_pct, 5),
        "edge_density": round(edge_density, 5),
        "content_ratio": round(content_ratio, 5),
        "bbox_area_ratio": round(bbox_area_ratio, 5),
        "frame_flags": ";".join(flags),
    }


def make_contact_sheet(image_paths: list[Path], labels: list[str], output_path: Path, columns: int = 4, thumb_w: int = 320) -> None:
    if not image_paths:
        return
    thumbs = []
    for path in image_paths:
        img = Image.open(path).convert("RGB")
        ratio = thumb_w / img.width
        thumb_h = int(img.height * ratio)
        thumbs.append(img.resize((thumb_w, thumb_h)))
    label_h = 28
    rows = math.ceil(len(thumbs) / columns)
    cell_h = max(img.height for img in thumbs) + label_h
    sheet = Image.new("RGB", (columns * thumb_w, rows * cell_h), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for idx, img in enumerate(thumbs):
        x = (idx % columns) * thumb_w
        y = (idx // columns) * cell_h
        draw.rectangle([x, y, x + thumb_w - 1, y + label_h - 1], fill=(31, 78, 121))
        draw.text((x + 6, y + 8), labels[idx][:60], fill="white", font=font)
        sheet.paste(img, (x, y + label_h))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, quality=92)


def summarize_video(frame_rows: list[dict[str, Any]], probe: ProbeInfo, inventory: dict[str, str]) -> tuple[str, int]:
    flags: list[str] = []
    if not Path(inventory["cloud_path"]).exists():
        flags.append("missing_file")
    if not probe.ok:
        flags.append("probe_failed")
    else:
        if (probe.width or 0) < 640 or (probe.height or 0) < 360:
            flags.append("low_resolution")
        inv_duration = float(inventory.get("duration_sec") or 0)
        if inv_duration and probe.duration_sec and abs(inv_duration - probe.duration_sec) > 3:
            flags.append("duration_mismatch")
        if probe.duration_sec and probe.duration_sec < 20:
            flags.append("very_short_video")
        size = int(inventory.get("size_bytes") or 0)
        if size < 500_000:
            flags.append("tiny_file")

    blank_count = sum("blank_or_static_suspect" in r.get("frame_flags", "") for r in frame_rows)
    low_detail_count = sum("low_detail_suspect" in r.get("frame_flags", "") for r in frame_rows)
    dark_count = sum("too_dark_suspect" in r.get("frame_flags", "") for r in frame_rows)
    bright_count = sum("too_bright_suspect" in r.get("frame_flags", "") for r in frame_rows)
    overdense_count = sum("overdense_visual_suspect" in r.get("frame_flags", "") for r in frame_rows)
    crop_count = sum("possible_crop_or_full_canvas_content" in r.get("frame_flags", "") for r in frame_rows)

    if blank_count:
        flags.append(f"blank_frames={blank_count}")
    if low_detail_count >= 3:
        flags.append(f"low_detail_frames={low_detail_count}")
    if dark_count:
        flags.append(f"dark_frames={dark_count}")
    if bright_count:
        flags.append(f"bright_frames={bright_count}")
    if overdense_count >= 3:
        flags.append(f"overdense_frames={overdense_count}")
    severity = 0
    if any(flag in flags for flag in ["missing_file", "probe_failed", "very_short_video", "tiny_file"]):
        severity = 3
    elif blank_count or dark_count or bright_count or low_detail_count >= 5:
        severity = 2
    elif flags:
        severity = 1
    return ";".join(flags) if flags else "ok", severity


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    inventory = read_csv(INVENTORY_PATH)
    video_rows: list[dict[str, Any]] = []
    frame_rows: list[dict[str, Any]] = []
    lesson_to_video_frames: dict[str, list[tuple[str, list[Path]]]] = {}

    for row in inventory:
        video_id = row["video_id"]
        lesson_id = row["lesson_id"]
        system = row["system"]
        video_path = Path(row["cloud_path"])
        probe = probe_video(video_path)
        this_frame_rows: list[dict[str, Any]] = []
        frame_paths: list[Path] = []
        duration = probe.duration_sec or float(row.get("duration_sec") or 0)

        if video_path.exists() and probe.ok and duration > 0:
            for idx, pos in enumerate(FRAME_POSITIONS, start=1):
                timestamp = max(0.1, duration * pos)
                frame_path = FRAME_ROOT / lesson_id / video_id / f"frame_{idx:02d}_{timestamp:.1f}s.jpg"
                ok = extract_frame(video_path, frame_path, timestamp)
                metrics = analyze_frame(frame_path) if ok else {}
                frame_row = {
                    "video_id": video_id,
                    "lesson_id": lesson_id,
                    "system": system,
                    "frame_index": idx,
                    "timestamp_sec": round(timestamp, 3),
                    "frame_path": str(frame_path),
                    "extract_ok": ok,
                    **metrics,
                }
                frame_rows.append(frame_row)
                this_frame_rows.append(frame_row)
                if ok:
                    frame_paths.append(frame_path)

        contact_path = CONTACT_ROOT / "by_video" / lesson_id / f"{video_id}.jpg"
        make_contact_sheet(
            frame_paths,
            [f"{video_id} {r['timestamp_sec']}s" for r in this_frame_rows if r.get("extract_ok")],
            contact_path,
        )
        lesson_to_video_frames.setdefault(lesson_id, []).append((video_id, frame_paths[:6]))

        flags, severity = summarize_video(this_frame_rows, probe, row)
        video_rows.append(
            {
                "video_id": video_id,
                "lesson_id": lesson_id,
                "system": system,
                "video_exists": video_path.exists(),
                "probe_ok": probe.ok,
                "duration_inventory_sec": row.get("duration_sec", ""),
                "duration_probe_sec": round(probe.duration_sec, 3) if probe.duration_sec else "",
                "width": probe.width or "",
                "height": probe.height or "",
                "fps": round(probe.fps, 3) if probe.fps else "",
                "codec": probe.codec,
                "size_bytes": row.get("size_bytes", ""),
                "extracted_frame_count": len(frame_paths),
                "blank_frame_count": sum("blank_or_static_suspect" in r.get("frame_flags", "") for r in this_frame_rows),
                "low_detail_frame_count": sum("low_detail_suspect" in r.get("frame_flags", "") for r in this_frame_rows),
                "dark_frame_count": sum("too_dark_suspect" in r.get("frame_flags", "") for r in this_frame_rows),
                "bright_frame_count": sum("too_bright_suspect" in r.get("frame_flags", "") for r in this_frame_rows),
                "overdense_frame_count": sum("overdense_visual_suspect" in r.get("frame_flags", "") for r in this_frame_rows),
                "crop_proxy_frame_count": sum("possible_crop_or_full_canvas_content" in r.get("frame_flags", "") for r in this_frame_rows),
                "auto_flags": flags,
                "manual_review_priority": severity,
                "contact_sheet": str(contact_path) if contact_path.exists() else "",
                "video_path": str(video_path),
            }
        )

    for lesson_id, items in lesson_to_video_frames.items():
        paths: list[Path] = []
        labels: list[str] = []
        for video_id, frames in sorted(items):
            for idx, frame in enumerate(frames, start=1):
                paths.append(frame)
                labels.append(f"{video_id} f{idx}")
        make_contact_sheet(paths, labels, CONTACT_ROOT / "by_lesson" / f"{lesson_id}.jpg", columns=6, thumb_w=260)

    write_csv(
        OUTPUT_ROOT / "artifact_quality_report.csv",
        video_rows,
        [
            "video_id",
            "lesson_id",
            "system",
            "video_exists",
            "probe_ok",
            "duration_inventory_sec",
            "duration_probe_sec",
            "width",
            "height",
            "fps",
            "codec",
            "size_bytes",
            "extracted_frame_count",
            "blank_frame_count",
            "low_detail_frame_count",
            "dark_frame_count",
            "bright_frame_count",
            "overdense_frame_count",
            "crop_proxy_frame_count",
            "auto_flags",
            "manual_review_priority",
            "contact_sheet",
            "video_path",
        ],
    )
    write_csv(
        OUTPUT_ROOT / "frame_quality_metrics.csv",
        frame_rows,
        [
            "video_id",
            "lesson_id",
            "system",
            "frame_index",
            "timestamp_sec",
            "frame_path",
            "extract_ok",
            "frame_width",
            "frame_height",
            "mean_brightness",
            "contrast_std",
            "near_black_pct",
            "near_white_pct",
            "edge_density",
            "content_ratio",
            "bbox_area_ratio",
            "frame_flags",
        ],
    )

    system_summary: list[dict[str, Any]] = []
    systems = sorted({r["system"] for r in video_rows})
    for system in systems:
        rows = [r for r in video_rows if r["system"] == system]
        system_summary.append(
            {
                "system": system,
                "video_count": len(rows),
                "probe_ok_count": sum(bool(r["probe_ok"]) for r in rows),
                "total_blank_frames": sum(int(r["blank_frame_count"]) for r in rows),
                "total_low_detail_frames": sum(int(r["low_detail_frame_count"]) for r in rows),
                "total_dark_frames": sum(int(r["dark_frame_count"]) for r in rows),
                "total_bright_frames": sum(int(r["bright_frame_count"]) for r in rows),
                "total_overdense_frames": sum(int(r["overdense_frame_count"]) for r in rows),
                "high_priority_review_count": sum(int(r["manual_review_priority"]) >= 2 for r in rows),
                "max_review_priority": max(int(r["manual_review_priority"]) for r in rows) if rows else 0,
            }
        )
    write_csv(
        OUTPUT_ROOT / "artifact_quality_summary_by_system.csv",
        system_summary,
        [
            "system",
            "video_count",
            "probe_ok_count",
            "total_blank_frames",
            "total_low_detail_frames",
            "total_dark_frames",
            "total_bright_frames",
            "total_overdense_frames",
            "high_priority_review_count",
            "max_review_priority",
        ],
    )

    markdown = [
        "# Visual Artifact Quality Check - formal_heuristic_v1",
        "",
        "This is a deterministic artifact check, not an OCR/VLM semantic review.",
        "",
        "## Scope",
        "",
        f"- Videos checked: {len(video_rows)}",
        f"- Frames extracted/analyzed: {len(frame_rows)}",
        f"- Output root: `{OUTPUT_ROOT}`",
        "",
        "## OCR status",
        "",
        "- No tesseract/easyocr/paddleocr engine was available on the cloud machine.",
        "- Garbled text cannot be finally judged from this run alone.",
        "- Contact sheets were generated for OCR/VLM/manual follow-up.",
        "",
        "## System summary",
        "",
        "| system | videos | probe ok | blank frames | low detail frames | dark frames | bright frames | overdense frames | high priority videos |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in system_summary:
        markdown.append(
            f"| {row['system']} | {row['video_count']} | {row['probe_ok_count']} | {row['total_blank_frames']} | "
            f"{row['total_low_detail_frames']} | {row['total_dark_frames']} | {row['total_bright_frames']} | "
            f"{row['total_overdense_frames']} | {row['high_priority_review_count']} |"
        )
    markdown.extend(
        [
            "",
            "## Files",
            "",
            "- `artifact_quality_report.csv`: one row per video.",
            "- `frame_quality_metrics.csv`: one row per extracted frame.",
            "- `artifact_quality_summary_by_system.csv`: aggregated automatic artifact flags.",
            "- `contact_sheets/by_video`: one contact sheet per video.",
            "- `contact_sheets/by_lesson`: side-by-side contact sheets grouped by lesson.",
        ]
    )
    (OUTPUT_ROOT / "visual_artifact_quality_check_report.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "output_root": str(OUTPUT_ROOT),
                "videos": len(video_rows),
                "frames": len(frame_rows),
                "system_summary": system_summary,
                "needs_review": [r["video_id"] for r in video_rows if int(r["manual_review_priority"]) > 0],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
