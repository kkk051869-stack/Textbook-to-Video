"""
智能图片提取：从 DOCX 教材中提取图片，关联章节和图注。

用法：
    python scripts/extract_docx_images.py textbook.docx --output output/images/
    python scripts/extract_docx_images.py textbook.docx --min-size 10000  # 过滤 <10KB
"""

import argparse
import json
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

# DOCX XML namespaces
NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}

CAPTION_PATTERN = re.compile(r"^图(\d+)-(\d+)\s+(.+)")
SAFE_FILENAME_RE = re.compile(r'[\\/:*?"<>|]')


def _get_style(para):
    """获取段落 style ID"""
    pPr = para.find(f"./{{{NS['w']}}}pPr")
    if pPr is None:
        return None
    pStyle = pPr.find(f"./{{{NS['w']}}}pStyle")
    if pStyle is None:
        return None
    return pStyle.get(f"{{{NS['w']}}}val")


def _get_text(para):
    """获取段落纯文本"""
    runs = para.findall(f".//{{{NS['w']}}}t")
    return "".join(r.text or "" for r in runs).strip()


def _get_blip_ids(para):
    """从段落中提取所有嵌入图片的 rId"""
    blips = para.findall(f".//{{{NS['a']}}}blip")
    ids = []
    for blip in blips:
        embed = blip.get(f"{{{NS['r']}}}embed")
        if embed:
            ids.append(embed)
    return ids



def _safe_filename(text, max_len=40):
    """将文本转为安全文件名"""
    text = SAFE_FILENAME_RE.sub("_", text)
    text = text.replace(" ", "_").strip("_")
    if len(text) > max_len:
        text = text[:max_len]
    return text


def _build_rid_map(z):
    """从 word/_rels/document.xml.rels 建立 rId -> media path 映射"""
    rels_xml = z.read("word/_rels/document.xml.rels")
    rels_root = ET.fromstring(rels_xml)
    rid_map = {}
    for rel in rels_root:
        rid = rel.get("Id")
        target = rel.get("Target")
        if target and "media" in target:
            rid_map[rid] = target
    return rid_map


def extract_images(docx_path, output_dir, min_size=5000):
    """
    从 DOCX 中智能提取图片。

    Args:
        docx_path: DOCX 文件路径
        output_dir: 输出目录
        min_size: 最小文件大小（字节），低于此值的图片被视为图标/项目符号

    Returns:
        manifest dict
    """
    docx_path = Path(docx_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(docx_path, "r") as z:
        rid_map = _build_rid_map(z)
        doc_xml = z.read("word/document.xml")
        root = ET.fromstring(doc_xml)
        paras = root.findall(f".//{{{NS['w']}}}p")

        # 建立媒体文件大小索引
        media_sizes = {}
        for name in z.namelist():
            if name.startswith("word/media/"):
                media_sizes[name] = z.getinfo(name).file_size

        # 遍历段落，跟踪章节状态
        current_chapter = ""
        current_section = ""
        images = []
        seen_paths = {}

        for i, para in enumerate(paras):
            style = _get_style(para)
            text = _get_text(para)

            if style == "2" and text:
                current_chapter = text
                current_section = ""
            elif style == "4" and text:
                current_section = text

            # 检测图片
            blip_ids = _get_blip_ids(para)
            if not blip_ids:
                continue

            for rid in blip_ids:
                if rid not in rid_map:
                    continue

                media_path = rid_map[rid]
                # 规范化路径（有的是 "media/image1.png"，有的是 "word/media/image1.png"）
                full_media_path = media_path if media_path.startswith("word/") else f"word/{media_path}"

                size = media_sizes.get(full_media_path, 0)
                if size < min_size:
                    continue

                # 查找图注：检查后续段落
                caption = ""
                caption_chapter = 0
                caption_seq = 0
                for offset in range(1, 4):
                    if i + offset >= len(paras):
                        break
                    next_text = _get_text(paras[i + offset])
                    match = CAPTION_PATTERN.match(next_text)
                    if match:
                        caption_chapter = int(match.group(1))
                        caption_seq = int(match.group(2))
                        caption = next_text
                        break
                    if next_text and not next_text.startswith("图"):
                        break

                # 没有图注的图片直接跳过
                if not caption_seq:
                    continue

                # 确定章节目录：用图注中的章号
                ch_key = caption_chapter

                # 确定图片 ID 和文件名
                img_id = f"fig{caption_chapter}-{caption_seq}"
                ext = os.path.splitext(full_media_path)[1].lower()
                title_part = CAPTION_PATTERN.match(caption)
                title_text = title_part.group(3) if title_part else caption
                safe_title = _safe_filename(title_text)
                filename = f"{img_id}_{safe_title}{ext}"

                # 章节子目录
                ch_dir = f"ch{ch_key}" if ch_key > 0 else "ch0"

                # 处理重复文件名（同一图注对应多张子图）
                rel_path = f"{ch_dir}/{filename}"
                seen_key = rel_path
                if seen_key in seen_paths:
                    seen_paths[seen_key] += 1
                    base, dot_ext = os.path.splitext(filename)
                    filename = f"{base}_{seen_paths[seen_key]}{dot_ext}"
                    rel_path = f"{ch_dir}/{filename}"
                else:
                    seen_paths[seen_key] = 1

                images.append({
                    "id": img_id,
                    "filename": rel_path,
                    "original": full_media_path,
                    "size_bytes": size,
                    "chapter": current_chapter,
                    "section": current_section,
                    "caption": caption,
                    "description": title_text,
                    "paragraph_index": i,
                })

        # 提取文件并写入
        extracted_count = 0
        for img in images:
            dest_path = output_dir / img["filename"]
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                data = z.read(img["original"])
                dest_path.write_bytes(data)
                extracted_count += 1
            except KeyError:
                print(f"  [WARN] 找不到: {img['original']}")

    # 生成 manifest
    manifest = {
        "source": str(docx_path.name),
        "min_size_filter": min_size,
        "total_extracted": extracted_count,
        "total_skipped_small": len(media_sizes) - extracted_count,
        "images": images,
    }

    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    return manifest


def main():
    parser = argparse.ArgumentParser(
        description="从 DOCX 教材中智能提取图片，关联章节和图注"
    )
    parser.add_argument("input", help="DOCX 文件路径")
    parser.add_argument("--output", "-o", default="output/images/", help="输出目录")
    parser.add_argument("--min-size", type=int, default=5000, help="最小文件大小（字节），默认 5000")
    args = parser.parse_args()

    print(f"{'=' * 60}")
    print(f"DOCX 智能图片提取")
    print(f"{'=' * 60}")
    print(f"  输入: {args.input}")
    print(f"  输出: {args.output}")
    print(f"  最小尺寸: {args.min_size:,} bytes")
    print()

    manifest = extract_images(args.input, args.output, min_size=args.min_size)

    print(f"{'=' * 60}")
    print(f"提取完成")
    print(f"{'=' * 60}")
    print(f"  有效图片: {manifest['total_extracted']} 张")
    print(f"  跳过（太小）: {manifest['total_skipped_small']} 张")
    print()

    # 按章统计
    chapter_stats = {}
    for img in manifest["images"]:
        ch = img["chapter"] or "(目录前)"
        chapter_stats.setdefault(ch, 0)
        chapter_stats[ch] += 1

    print("  按章分布:")
    for ch, count in chapter_stats.items():
        print(f"    {ch}: {count} 张")

    print()
    print(f"  Manifest: {Path(args.output) / 'manifest.json'}")

    # 显示前几张
    print()
    print("  前 10 张:")
    for img in manifest["images"][:10]:
        print(f"    {img['filename']:<50} {img['size_bytes']:>10,}B  {img['caption'][:30]}")


if __name__ == "__main__":
    main()
