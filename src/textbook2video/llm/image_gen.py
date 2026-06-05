"""
AI 图片生成模块：分类 + 生成 + 批处理

流程：
1. classify_image_elements() — 一次 LLM 调用，将 image 元素分类为 figurative / abstract
2. generate_image() — 调用图片 API 生成单张图片，返回 base64
3. generate_images_for_storyboard() — 批处理入口，串联分类 + 并行生成
   - 按 segment 维度判断：一页有多个并列 image 或 image 与图表元素并列时，整页降级为 SVG

图片存储：生成的图片保存为外部文件（images/ 目录），返回相对路径而非 base64 data URI。
"""

from __future__ import annotations

import base64
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from textbook2video.llm.client import chat, chat_with_system
from textbook2video.pipeline.config import (
    IMAGE_MODEL,
    IMAGE_SIZE,
    LLM_API_KEY,
    LLM_BASE_URL,
)

# 图表类 element type — 与 image 并列出现时触发降级
# 只包含视觉图表类型，不包含文字步骤类（flow_step / activity_step 是文字内容，不是并列视觉元素）
_CHART_ELEMENT_TYPES = frozenset({
    "chart_line", "chart-bar", "comparison_panel",
})

# AI 图片风格前缀：让生成图片融入教学 slide 视觉
_IMAGE_STYLE_PREFIX = (
    "Flat vector illustration, clean lines, simple shapes, "
    "soft pastel colors, light and warm tones, "
    "suitable for an educational slide presentation. "
)

# ── 分类 prompt ──
_CLASSIFY_SYSTEM_PROMPT = """\
你是一个图片分类器。你的任务是判断教学课件中每个 image 元素应该用 AI 生成的真实图片，
还是用 SVG/CSS 绘制的简单图形。

分类标准：
- figurative: 真实人物、动物、场景、地图、建筑、卡通角色、复杂插画、照片级内容
- abstract: 简单图标、流程图、几何图案、柱状图、箭头连线、抽象符号、示意图

输出格式（严格 JSON 数组）：
[{"id": "e4", "category": "figurative"}, {"id": "e3", "category": "abstract"}]

只输出 JSON，不要任何其他文字。"""


def classify_image_elements(
    elements: list[dict],
    *,
    model: str | None = None,
) -> dict[str, str]:
    """批量分类 image 元素 -> "figurative" | "abstract"。

    Args:
        elements: [{"id": "e4", "description": "..."}, ...]
        model: LLM 模型名

    Returns:
        {"e4": "figurative", "e3": "abstract", ...}
        解析失败时所有元素默认 "abstract"。
    """
    if not elements:
        return {}

    user_content = json.dumps(
        [{"id": e["id"], "description": e["description"]} for e in elements],
        ensure_ascii=False,
    )

    try:
        raw = chat_with_system(
            user_content,
            system_prompt=_CLASSIFY_SYSTEM_PROMPT,
            model=model,
            temperature=0.1,
        )
        # 提取 JSON 数组
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            raise ValueError("未找到 JSON 数组")
        parsed = json.loads(match.group())
        result = {}
        for item in parsed:
            eid = item.get("id", "")
            cat = item.get("category", "abstract")
            if cat not in ("figurative", "abstract"):
                cat = "abstract"
            result[eid] = cat
        return result
    except Exception as exc:
        print(f"  ⚠️ 图片分类失败 ({type(exc).__name__}: {exc}), 全部默认 abstract")
        return {e["id"]: "abstract" for e in elements}


def _segment_has_parallel_images(seg: dict) -> bool:
    """判断一个 segment 是否有多个并列 image 或 image 与图表元素并列。

    降级条件（任一满足）：
    - 该页有 2 个及以上 type=image 元素。
    - 该页同时有 type=image 和图表类元素（chart_line / comparison_panel / flow_step 等）。
    """
    image_count = 0
    has_chart = False
    for elem in seg.get("elements", []):
        etype = elem.get("type", "")
        if etype == "image":
            image_count += 1
        elif etype in _CHART_ELEMENT_TYPES:
            has_chart = True
    return image_count >= 2 or (image_count >= 1 and has_chart)


def generate_image(
    description: str,
    *,
    model: str = IMAGE_MODEL,
    size: str = IMAGE_SIZE,
) -> str | None:
    """调用图片 API 生成图片，返回 base64 字符串或 None。

    Args:
        description: 图片描述文本
        model: 图片模型名
        size: 图片尺寸 (e.g. "1024x1024")

    Returns:
        base64 编码的图片字符串，失败返回 None
    """
    styled_prompt = _IMAGE_STYLE_PREFIX + description

    max_retries = 2
    url = f"{LLM_BASE_URL}/images/generations"

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "prompt": styled_prompt,
                    "n": 1,
                    "size": size,
                    "response_format": "b64_json",
                },
                timeout=90,
            )
            resp.raise_for_status()
            body = resp.json()

            err = body.get("err_message")
            if err:
                raise ValueError(f"API 错误: {err}")

            data = body.get("data", [])
            if not data:
                raise ValueError("API 返回空 data")

            b64 = data[0].get("b64_json", "")
            if b64:
                return b64
            raise ValueError("API 返回空 b64_json")
        except Exception as exc:
            print(
                f"  ⚠️ 图片生成第 {attempt} 次失败: "
                f"{type(exc).__name__}: {str(exc)[:100]}"
            )
            if attempt < max_retries:
                time.sleep(2 * attempt)

    return None


def generate_images_for_storyboard(
    segments: list[dict],
    *,
    model: str | None = None,
    max_parallel: int = 4,
    image_dir: str | None = None,
) -> dict[str, str]:
    """处理所有 segments 中的 image 元素。

    流程:
    1. 按 segment 维度过滤：并列 image 过多或与图表混排的页面整页降级为 SVG
    2. 收集剩余 image 元素并分类（一次 LLM 调用）
    3. 并行生成 figurative 元素的图片（带风格约束）

    Args:
        segments: storyboard segments 列表
        model: 分类使用的 LLM 模型名
        max_parallel: 最大并行生成数
        image_dir: 图片保存目录路径，默认为当前工作目录下的 images/

    Returns:
        {"seg_id:elem_id": "/abs/path/images/ai_seg1_e2.png"} 字典（绝对路径）
    """
    from pathlib import Path

    img_dir = Path(image_dir).resolve() if image_dir else Path("images").resolve()
    img_dir.mkdir(parents=True, exist_ok=True)
    # 1. 按 segment 维度过滤并列 image
    image_elements = []  # [(seg_id, elem_id, description)]
    downgraded = 0
    for seg in segments:
        seg_id = seg.get("id", "")
        if _segment_has_parallel_images(seg):
            image_count = sum(
                1 for e in seg.get("elements", []) if e.get("type") == "image"
            )
            print(
                f"  ⬇️ segment {seg_id}: {image_count} 个并列 image，"
                f"降级为 SVG"
            )
            downgraded += 1
            continue
        for elem in seg.get("elements", []):
            if elem.get("type") == "image":
                if elem.get("src"):
                    # 有 src = storyboard 引用的教材原图，由 animation_gen.load_textbook_images
                    # 直接读原图嵌入，不走 AI 生成（避免用 AI 重画覆盖真实教材插图）。
                    continue
                elem_id = elem.get("id", "")
                desc = elem.get("description", "")
                if elem_id and desc:
                    image_elements.append((seg_id, elem_id, desc))

    if not image_elements:
        print(f"\n🖼️  未发现可生成 AI 图片的 image 元素（{downgraded} 页降级为 SVG）")
        return {}

    print(
        f"\n🖼️  发现 {len(image_elements)} 个 image 元素"
        f"（{downgraded} 页因并列降级为 SVG），开始分类..."
    )

    # 2. 分类
    classify_input = [
        {"id": elem_id, "description": desc}
        for _, elem_id, desc in image_elements
    ]
    classifications = classify_image_elements(classify_input, model=model)

    figurative = [
        (seg_id, elem_id, desc)
        for seg_id, elem_id, desc in image_elements
        if classifications.get(elem_id) == "figurative"
    ]
    abstract_count = len(image_elements) - len(figurative)
    print(
        f"  分类结果: {len(figurative)} figurative, "
        f"{abstract_count} abstract"
    )

    if not figurative:
        return {}

    # 3. 并行生成
    print(f"  开始生成 {len(figurative)} 张 AI 图片 (并行={max_parallel})...")
    results: dict[str, str] = {}

    def _gen(item: tuple[str, str, str]) -> tuple[str, str | None]:
        seg_id, elem_id, desc = item
        key = f"{seg_id}:{elem_id}"
        b64 = generate_image(desc)
        return key, b64

    with ThreadPoolExecutor(max_workers=max_parallel) as pool:
        futures = {pool.submit(_gen, item): item for item in figurative}
        for future in as_completed(futures):
            key, b64 = future.result()
            if b64:
                fname = f"ai_{key.replace(':', '_')}.png"
                (img_dir / fname).write_bytes(base64.b64decode(b64))
                results[key] = str(img_dir / fname)
                print(f"  ✅ {key} 生成成功 → {fname}")
            else:
                seg_id, elem_id, desc = futures[future]
                print(f"  ❌ {key} 生成失败，将回退到 SVG/CSS")

    print(
        f"  图片生成完成: {len(results)}/{len(figurative)} 成功"
    )
    return results


# ── SVG 示意图生成（无真实图片时的矢量兜底，替代纯文字占位）──

_SVG_SYSTEM_PROMPT = (
    "你是 SVG 矢量插画师。只输出一个 <svg>...</svg> 标签，"
    "不要 markdown 代码块、不要任何解释文字。"
)


def draw_svg(
    description: str,
    *,
    colors: dict[str, str] | None = None,
    model: str | None = None,
    timeout: float = 120.0,
) -> str | None:
    """让 LLM 按描述画一个简洁扁平的 SVG 示意图。失败返回 None。"""
    c = colors or {}
    primary = c.get("primary", "#5b8def")
    secondary = c.get("secondary", "#37c6e5")
    accent = c.get("accent", "#f8c808")
    line = c.get("line", "#cdd8ef")
    prompt = (
        f"根据描述画一个简洁、扁平、现代的示意图 SVG。\n"
        f'要求：viewBox="0 0 480 300"；用几何图形/线条/简单图标表达，避免文字标签；'
        f"描边和填充只用这些颜色：{primary}(主)、{secondary}(辅)、{accent}(强调)、{line}(线条/浅色)；"
        f"线宽 2-3；只输出 <svg>...</svg>。\n"
        f"【重要】背景必须完全透明：不要画任何填满画布的背景矩形/圆角矩形，"
        f"不要给 <svg> 或 <rect> 设深色/纯色 fill 当底色；让示意图直接浮在透明背景上。\n"
        f"描述：{description}"
    )
    for attempt in range(2):
        try:
            raw = chat_with_system(
                prompt, system_prompt=_SVG_SYSTEM_PROMPT,
                model=model, temperature=0.4, max_tokens=2200, timeout=timeout,
            )
            match = re.search(r"<svg.*?</svg>", raw, re.DOTALL | re.IGNORECASE)
            if match:
                svg = match.group(0)
                # 补明确 width/height：SVG 只有 viewBox 而无尺寸时，作为 <img src=data:svg>
                # 会被 max-width:100% 压成 0x0。从 viewBox 取尺寸补上，确保能正常显示。
                head = svg[: svg.find(">")]
                if "width=" not in head:
                    vb = re.search(r'viewBox="[\d.\s]*?([\d.]+)\s+([\d.]+)"', head)
                    w, h = (vb.group(1), vb.group(2)) if vb else ("480", "300")
                    svg = svg.replace("<svg", f'<svg width="{w}" height="{h}"', 1)
                return _strip_bg_rect(svg)
        except Exception as exc:  # noqa: BLE001
            if attempt == 0:
                time.sleep(2)
                continue
            print(f"  ⚠️ SVG 生成调用失败: {type(exc).__name__}: {str(exc)[:80]}")
    return None


def _strip_bg_rect(svg: str) -> str:
    """移除铺满画布的背景矩形（LLM 常无视'透明背景'画一个深色底）。

    判定为背景：x/y≈0 且 width、height 都接近画布尺寸（>=88%）的 <rect>。
    """
    vb = re.search(r'viewBox="[\d.\s]+?([\d.]+)\s+([\d.]+)"', svg[: svg.find(">")])
    vw, vh = (float(vb.group(1)), float(vb.group(2))) if vb else (480.0, 300.0)

    def _num(tag: str, attr: str) -> float | None:
        m = re.search(rf'{attr}="([\d.]+)(%?)"', tag)
        if not m:
            return None
        val = float(m.group(1))
        return vw if (m.group(2) and attr == "width") else (
            vh if (m.group(2) and attr == "height") else val
        )

    def _maybe_drop(m: re.Match) -> str:
        tag = m.group(0)
        x = _num(tag, "x") or 0.0
        y = _num(tag, "y") or 0.0
        w = _num(tag, "width")
        h = _num(tag, "height")
        if w and h and x <= vw * 0.05 and y <= vh * 0.05 and w >= vw * 0.88 and h >= vh * 0.88:
            return ""  # 背景矩形 → 删除
        return tag

    return re.sub(r"<rect\b[^>]*?/>", _maybe_drop, svg, flags=re.IGNORECASE)


def generate_svgs_for_storyboard(
    segments: list[dict],
    covered_keys: set[str],
    *,
    colors: dict[str, str] | None = None,
    model: str | None = None,
    max_parallel: int = 2,
    image_dir: str | None = None,
) -> dict[str, str]:
    """为无 src、且未被教材图/AI 图覆盖的 image 元素生成 SVG 示意图。

    返回 {"seg_id:elem_id": "/abs/path/images/svg_seg1_e2.svg"}，复用 {{IMG_eN}} 注入。
    """
    from pathlib import Path

    img_dir = Path(image_dir).resolve() if image_dir else Path("images").resolve()
    img_dir.mkdir(parents=True, exist_ok=True)
    targets: list[tuple[str, str]] = []
    for seg in segments:
        seg_id = seg.get("id", "")
        for elem in seg.get("elements", []):
            if elem.get("type") != "image" or elem.get("src"):
                continue
            elem_id = elem.get("id", "")
            desc = elem.get("description", "")
            key = f"{seg_id}:{elem_id}"
            if elem_id and desc and key not in covered_keys:
                targets.append((key, desc))

    if not targets:
        return {}

    print(f"\n🎨 为 {len(targets)} 个无图 image 元素生成 SVG 矢量示意图...")

    def _gen(item: tuple[str, str]) -> tuple[str, str | None]:
        key, desc = item
        svg = draw_svg(desc, colors=colors, model=model)
        if not svg:
            return key, None
        fname = f"svg_{key.replace(':', '_')}.svg"
        (img_dir / fname).write_text(svg, encoding="utf-8")
        return key, str(img_dir / fname)

    results: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max_parallel) as pool:
        futures = {pool.submit(_gen, t): t for t in targets}
        for future in as_completed(futures):
            key, uri = future.result()
            if uri:
                results[key] = uri
                print(f"  ✅ {key} SVG 示意图生成成功")
            else:
                print(f"  ⚠️ {key} SVG 生成失败，回退文字占位")
    print(f"  SVG 示意图完成: {len(results)}/{len(targets)}")
    return results
