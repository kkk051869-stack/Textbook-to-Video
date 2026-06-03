"""
AI 图片生成模块：分类 + 生成 + 批处理

流程：
1. classify_image_elements() — 一次 LLM 调用，将 image 元素分类为 figurative / abstract
2. generate_image() — 调用图片 API 生成单张图片，返回 base64
3. generate_images_for_storyboard() — 批处理入口，串联分类 + 并行生成
   - 按 segment 维度判断：一页有多个并列 image 或 image 与图表元素并列时，整页降级为 SVG
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from textbook2video.llm.client import chat_with_system
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

    Returns:
        {"seg_id:elem_id": "data:image/png;base64,..."} 字典
    """
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
                results[key] = f"data:image/png;base64,{b64}"
                print(f"  ✅ {key} 生成成功 ({len(b64) // 1024}KB)")
            else:
                seg_id, elem_id, desc = futures[future]
                print(f"  ❌ {key} 生成失败，将回退到 SVG/CSS")

    print(
        f"  图片生成完成: {len(results)}/{len(figurative)} 成功"
    )
    return results
