"""动画生成 Pipeline

公共 API:
    generate(json_path)  -> Path  — storyboard JSON → 分批生成+合并 → 单文件 HTML
"""

from __future__ import annotations


import html
import json

import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, cast

from textbook2video.llm.client import chat
from textbook2video.pipeline.config import DEFAULT_OUTPUT_DIR
from textbook2video.pipeline.config import LLM_DEFAULT_MODEL
from textbook2video.pipeline.config import RECORD_BROWSER_CHANNEL
from textbook2video.themes import (
    load_theme,
    theme_to_css_vars,
    theme_to_particle_config,
    theme_prompt_section,
    theme_layout_mode,
    theme_layout_prompt_section,
)

# === 包内资源路径 ===
_PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = _PACKAGE_DIR / "templates"
PROMPTS_DIR = _PACKAGE_DIR / "llm" / "prompts"
COMPONENTS_DIR = _PACKAGE_DIR / "components"
EXAMPLES_DIR = COMPONENTS_DIR / "examples"

# === 默认配置 ===
BATCH_SIZE = 4
MODEL = LLM_DEFAULT_MODEL
MAX_TOKENS = 16000
TEMPERATURE = 0.7
# 单次 LLM 生成 / 修复超时（秒）。timeout 现已精确生效（见 llm/client.py 禁用底层重试），
# 故上限需覆盖最慢模型的正常耗时：实测 ecnu-max 生成一批 slide 约 350s，留余量到 420s；
# ecnu-plus 通常数十秒内返回，不受此上限影响（仅请求真正卡住时才等满）。可用环境变量覆盖。
GENERATE_TIMEOUT = int(os.environ.get("T2V_GENERATE_TIMEOUT", "600"))  # seconds — slide generation timeout
REPAIR_TIMEOUT = int(os.environ.get("T2V_REPAIR_TIMEOUT", "300"))      # seconds — layout repair timeout
MAX_LAYOUT_REPAIR_ATTEMPTS = 3
# slide 数量修复重试次数（1→3）。开源网关模型一次未必给对数量，
# 多给几次重试预算成本低、收益高（见 docs/fix-plan-json-to-html.md 根因 6）。
MAX_BATCH_COUNT_REPAIR_ATTEMPTS = 3
LAYOUT_QA_VIEWPORTS = ((1920, 1080), (1366, 768))
PROMPT_SOFT_CHAR_LIMIT = 100_000
PROMPT_HARD_CHAR_LIMIT = 100_000
REPAIR_PROMPT_HARD_LIMIT = 20000

# 组件查找表: visual_type → 组件文件名
COMPONENT_REGISTRY = {
    "network": "network.html",
    "data-chart": "chart_line.html",
    "chart-line": "chart_line.html",
    "process": "flow.html",
    "comparison": "comparison.html",
}
COMPONENT_GUIDANCE_OMITTED = "（已省略组件摘要；请按核心布局规则生成）"

# 转场推断规则: visual_type → 转场类型
TRANSITION_RULES: dict[str, str] = {
    "title": "zoom",
    "closing": "zoom",
    "definition": "dissolve",
    "process": "push-left",
    "comparison": "push-left",
    "data-chart": "push-left",
    "data-bar": "push-left",
    "network": "dissolve",
    "timeline": "push-left",
    "tree": "dissolve",
    "illustration": "dissolve",
    "activity": "push-left",
}

# 默认 slide 时长（Python 侧和 JS 侧 DEFAULT_SLIDE_DURATION 保持一致）
DEFAULT_SLIDE_DURATION_MS = 5000

Segment = dict
JsonDict = dict
PromptRebuilder = Callable[..., str]


def configure_console_output() -> None:
    """让 Windows 控制台安全打印 LLM/HTML 中的 Unicode 字符。"""
    stdout_reconfigure = getattr(sys.stdout, "reconfigure", None)
    if stdout_reconfigure:
        stdout_reconfigure(encoding="utf-8", errors="backslashreplace")
    stderr_reconfigure = getattr(sys.stderr, "reconfigure", None)
    if stderr_reconfigure:
        stderr_reconfigure(encoding="utf-8", errors="backslashreplace")


# ============================================================
# Step 1: 解析 JSON
# ============================================================
def parse_storyboard(json_path: str | Path) -> dict[str, Any]:
    """读取 storyboard JSON，返回解析后的数据。

    Raises:
        FileNotFoundError: 文件不存在
        ValueError: JSON 格式错误或缺少必要字段
    """
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {json_path}")

    with open(path, "r", encoding="utf-8") as f:
        data: Any = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("JSON 根节点必须是对象")

    if "segments" not in data:
        raise ValueError("JSON 缺少 'segments' 字段")

    title = data.get("lesson_title", "教学动画")
    segments = data["segments"]
    _validate_storyboard_segments(segments)

    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("metadata 必须是对象")

    total = metadata.get("total_slides", len(segments))
    if not isinstance(total, int) or isinstance(total, bool):
        raise ValueError("metadata.total_slides 必须是整数")
    if total != len(segments):
        raise ValueError(
            f"metadata.total_slides ({total}) 必须等于 segments 数量 ({len(segments)})"
        )

    print(f"📖 课程: {title}")
    print(f"📄 共 {len(segments)} 个 segments（元数据标注 {total} 页）")

    return {"title": title, "segments": segments, "total_slides": total}


def _validate_storyboard_segments(segments: object) -> None:
    """Validate the segment fields consumed by the JSON-to-HTML pipeline."""
    if not isinstance(segments, list):
        raise ValueError("segments 必须是数组")
    if not segments:
        raise ValueError("segments 不能为空")

    required = ("id", "visual_type", "narration")
    for index, seg in enumerate(segments, start=1):
        if not isinstance(seg, dict):
            raise ValueError(f"segments[{index}] 必须是对象")

        missing = [field for field in required if field not in seg]
        if missing:
            raise ValueError(f"segments[{index}] 缺少字段: {', '.join(missing)}")

        narration = str(seg.get("narration") or "").strip()
        if not narration or narration in {"讲稿内容：", "讲稿内容:", "（无内容）", "(无内容)"}:
            raise ValueError(f"segments[{index}].narration 为空或是无效占位内容")

        if "elements" in seg and not isinstance(seg["elements"], list):
            raise ValueError(f"segments[{index}].elements 必须是数组")
        if not isinstance(seg.get("elements"), list) or not seg["elements"]:
            raise ValueError(f"segments[{index}].elements 不能为空，拒绝生成空白页")
        if "animations" in seg:
            animations = seg["animations"]
            if not isinstance(animations, list):
                raise ValueError(f"segments[{index}].animations 必须是数组")
            for anim_index, animation in enumerate(animations, start=1):
                if not isinstance(animation, dict):
                    raise ValueError(
                        f"segments[{index}].animations[{anim_index}] 必须是对象"
                    )
                missing_animation = [
                    field for field in ("target", "effect") if field not in animation
                ]
                if missing_animation:
                    raise ValueError(
                        f"segments[{index}].animations[{anim_index}] 缺少字段: "
                        f"{', '.join(missing_animation)}"
                    )


def _duration_ms_for_segment(segment: dict[str, Any]) -> int:
    """Return a validated slide duration in milliseconds."""
    if "audio_duration_sec" not in segment:
        return DEFAULT_SLIDE_DURATION_MS

    duration = segment["audio_duration_sec"]
    if duration is None or isinstance(duration, bool) or not isinstance(duration, (int, float)):
        segment_id = segment.get("id", "?")
        raise ValueError(f"segment {segment_id} 的 audio_duration_sec 必须是正数")
    if duration <= 0:
        segment_id = segment.get("id", "?")
        raise ValueError(f"segment {segment_id} 的 audio_duration_sec 必须大于 0")

    return int(duration * 1000)


def _escape_css_selector_value(value: str) -> str:
    """转义用于 CSS 属性选择器的值，防止注入。"""
    # 只允许字母数字、连字符、下划线
    return re.sub(r'[^a-zA-Z0-9_\-]', '', value)


def build_slide_timelines(segments: list[Segment]) -> list[list[dict[str, Any]]]:
    """从 segments 的 animations 字段提取时间轴数据。

    每页返回一个列表，包含 {selector, at_ms} 条目。
    如果某页没有任何 trigger_at_sec，返回空列表（controller 将 fallback 到均分模式）。
    """
    timelines: list[list[dict[str, Any]]] = []
    for seg in segments:
        seg_id = seg.get("id", "?")
        entries: list[dict[str, Any]] = []
        for anim in seg.get("animations", []):
            trigger = anim.get("trigger_at_sec")
            if trigger is not None:
                try:
                    at_ms = int(float(trigger) * 1000)
                except (TypeError, ValueError):
                    print(f"  ⚠️ segment {seg_id}: trigger_at_sec 值无效: {trigger!r}，已跳过")
                    continue
                target = anim.get("target", "")
                if not target:
                    print(f"  ⚠️ segment {seg_id}: animation 缺少 target，已跳过")
                    continue
                safe_target = _escape_css_selector_value(target)
                if safe_target != target:
                    print(f"  ⚠️ segment {seg_id}: target {target!r} 包含特殊字符，已净化为 {safe_target!r}")
                entries.append({
                    "selector": f'[data-anim-id="{safe_target}"]',
                    "at_ms": at_ms,
                })
        timelines.append(entries)
    return timelines


def infer_transitions(
    segments: list[Segment],
    default: str = "push-left",
    style: str | None = None,
) -> list[str]:
    """推断每页转场类型。

    - `style`：主题统一转场（如 academic→dissolve）。**非 None 时所有页一律用它**，
      让翻页气质成为主题最显眼的签名。
    - `style=None` 时按 visual_type 从 TRANSITION_RULES 取，未命中走 `default`。
    """
    if style is not None:
        return [style] * len(segments)
    transitions: list[str] = []
    for seg in segments:
        vtype = str(seg.get("visual_type", ""))
        transitions.append(TRANSITION_RULES.get(vtype, default))
    return transitions


def _validate_slide_count(slides: list[str], expected: int, context: str) -> None:
    """Fail fast when LLM output does not preserve the storyboard/page mapping."""
    actual = len(slides)
    if actual != expected:
        raise ValueError(f"{context} slide 数量不匹配: 期望 {expected}, 实际 {actual}")


# ============================================================
# Step 2: 分批
# ============================================================
def split_batches(segments: list[Segment], batch_size: int = BATCH_SIZE) -> list[list[Segment]]:
    """将 segments 分成若干批，每批最多 batch_size 个。"""
    batches: list[list[Segment]] = []
    for i in range(0, len(segments), batch_size):
        batches.append(segments[i : i + batch_size])

    print(f"📦 分为 {len(batches)} 批: ", end="")
    print(", ".join(f"batch{b+1}({len(batch)}页)" for b, batch in enumerate(batches)))
    return batches


def select_segments_by_pages(
    segments: list[Segment],
    pages: list[int] | None,
) -> list[Segment]:
    """Return selected 1-based pages from segments, preserving requested order."""
    if not pages:
        return segments
    total = len(segments)
    selected: list[Segment] = []
    seen: set[int] = set()
    invalid: list[int] = []
    for page in pages:
        page = int(page)
        if page in seen:
            continue
        seen.add(page)
        if page < 1 or page > total:
            invalid.append(page)
            continue
        selected.append(segments[page - 1])
    if invalid:
        raise ValueError(f"--only 页码超出范围: {invalid}，有效范围 1-{total}")
    if not selected:
        raise ValueError("--only 没有选中任何页面")
    return selected


def page_selection_suffix(pages: list[int] | None) -> str:
    """Build a compact filename suffix for selected 1-based pages."""
    if not pages:
        return ""
    ordered: list[int] = []
    seen: set[int] = set()
    for page in pages:
        page = int(page)
        if page not in seen:
            ordered.append(page)
            seen.add(page)
    if len(ordered) == 1:
        return f"-p{ordered[0]}"
    return "-p" + "_".join(str(page) for page in ordered)


# ============================================================
# Step 3: 加载组件
# ============================================================
def load_component(visual_type: str) -> str:
    """根据 visual_type 查找并返回组件 HTML 代码。简单类型返回空字符串。"""
    filename = COMPONENT_REGISTRY.get(visual_type)
    if not filename:
        return ""

    filepath = COMPONENTS_DIR / filename
    if not filepath.exists():
        print(f"  ⚠️ 组件文件不存在: {filepath}")
        return ""

    return filepath.read_text(encoding="utf-8")


def _component_summary_path(visual_type: str) -> Path | None:
    filename = COMPONENT_REGISTRY.get(visual_type)
    if not filename:
        return None
    return COMPONENTS_DIR / f"{Path(filename).stem}.summary.md"


def load_component_guidance(visual_type: str) -> str:
    """Return compact component guidance for a visual type without full HTML source."""
    summary_path = _component_summary_path(visual_type)
    if summary_path and summary_path.exists():
        return summary_path.read_text(encoding="utf-8").strip()
    return f"visual_type={visual_type}: no component summary available; use core layout rules."


def build_component_guidance(batch: list[Segment], *, max_items: int | None = None) -> str:
    """Build deduplicated component guidance for the visual types in a batch."""
    summaries = []
    seen: set[str] = set()
    for seg in batch:
        visual_type = str(seg.get("visual_type", ""))
        if visual_type in seen:
            continue
        seen.add(visual_type)
        summaries.append(load_component_guidance(visual_type))
        if max_items is not None and len(summaries) >= max_items:
            break
    return "\n\n".join(summaries) if summaries else "（无）"


def load_example_snippet(visual_type: str) -> str:
    """加载指定 visual_type 的 few-shot HTML 示例。找不到返回空。"""
    example_path = EXAMPLES_DIR / f"{visual_type}.html"
    if example_path.exists():
        return example_path.read_text(encoding="utf-8").strip()
    return ""


def build_examples_section(batch: list[Segment]) -> str:
    """为 batch 中的 visual_type 构建 few-shot 示例段落（去重，最多 2 个）。"""
    examples: list[str] = []
    seen: set[str] = set()
    for seg in batch:
        vtype = str(seg.get("visual_type", ""))
        if vtype in seen:
            continue
        seen.add(vtype)
        snippet = load_example_snippet(vtype)
        if snippet:
            examples.append(f"<!-- 参考示例（{vtype}类型） -->\n{snippet}")
        if len(examples) >= 2:
            break
    return "\n\n".join(examples) if examples else ""


def load_prompt_template(filename: str) -> str:
    """Load a prompt markdown file and extract its fenced template body when present."""
    prompt_raw = (PROMPTS_DIR / filename).read_text(encoding="utf-8")
    prompt_match = re.search(
        r"## Prompt 模板\s*\n```\s*\n(.*)\n```", prompt_raw, re.DOTALL
    )
    if prompt_match:
        return prompt_match.group(1).strip()
    return prompt_raw.strip()


def _fill_generation_prompt(
    *,
    prompt_template: str,
    lesson_title: str,
    lesson_description: str,
    scenes: str,
    component_guidance: str,
    theme_prompt: str,
    layout_prompt: str,
    examples_section: str = "",
    slide_count: int = 0,
) -> str:
    filled = prompt_template.replace("{LESSON_TITLE}", lesson_title)
    filled = filled.replace("{LESSON_DESCRIPTION}", lesson_description)
    filled = filled.replace("{SCENES_DESCRIPTION}", scenes)
    filled = filled.replace("{COMPONENT_GUIDANCE}", component_guidance)
    filled = filled.replace("{COMPONENT_CODE}", component_guidance)
    if slide_count > 0:
        filled = filled.replace("{SLIDE_COUNT}", str(slide_count))

    if examples_section:
        filled = filled + "\n\n## 参考示例（仅供风格参考，不要照抄内容）\n" + examples_section
    if theme_prompt:
        filled = filled + "\n\n" + theme_prompt
    if layout_prompt:
        filled = filled + "\n\n" + layout_prompt
    return filled


def enforce_prompt_budget(
    prompt: str,
    *,
    rebuild_with_component_guidance: PromptRebuilder | None = None,
    hard_limit: int = PROMPT_HARD_CHAR_LIMIT,
) -> str:
    """Keep prompts under the hard budget via multi-level degradation.

    Degradation levels (applied in order until under budget):
      1. Drop examples section (HTML snippets are large; LLM has template guidance)
      2. Compress component guidance to max_items=1
      3. Drop component guidance entirely
      4. Truncate scenes description (last resort)

    Logs a warning if still over budget after all levels.
    """
    if len(prompt) <= hard_limit or rebuild_with_component_guidance is None:
        return prompt

    # Level 1: drop examples (usually 1000-5000 chars of HTML snippets)
    no_examples = rebuild_with_component_guidance(drop_examples=True)
    if len(no_examples) <= hard_limit:
        print(f"  📏 prompt 预算降级: 移除示例 → {len(no_examples)} 字符")
        return no_examples

    # Level 2: drop examples + compact guidance (keep 1 component)
    compact = rebuild_with_component_guidance(max_items=1, drop_examples=True)
    if len(compact) <= hard_limit:
        print(f"  📏 prompt 预算降级: 移除示例+压缩指导 → {len(compact)} 字符")
        return compact

    # Level 3: drop examples + drop guidance entirely
    no_guide = rebuild_with_component_guidance(
        component_guidance=COMPONENT_GUIDANCE_OMITTED,
        drop_examples=True,
    )
    if len(no_guide) <= hard_limit:
        print(f"  📏 prompt 预算降级: 移除示例+指导 → {len(no_guide)} 字符")
        return no_guide

    # Level 4: truncate scenes (last resort)
    truncated = rebuild_with_component_guidance(
        component_guidance=COMPONENT_GUIDANCE_OMITTED,
        drop_examples=True,
        truncate_scenes=True,
    )
    if len(truncated) <= hard_limit:
        print(f"  📏 prompt 预算降级: 移除示例+指导+截断场景 → {len(truncated)} 字符")
        return truncated

    print(f"  ⚠️ prompt 预算无法降到 {hard_limit}（当前 {len(truncated)}），发送超限 prompt")
    return truncated


# ============================================================
# Step 4: 构建 scenes_description
# ============================================================
def build_scenes_description(
    batch: list[Segment],
    generated_images: dict[str, str] | None = None,
) -> str:
    """将一批 segments 转换为 scenes_description 文本。"""
    scenes = []
    for seg in batch:
        elements_desc = []
        for elem in seg.get("elements", []):
            etype = elem.get("type", "")
            if etype == "heading":
                elements_desc.append(f"标题: {elem.get('text', '')}")
            elif etype == "subheading":
                elements_desc.append(f"副标题: {elem.get('text', '')}")
            elif etype == "text":
                elements_desc.append(f"说明文字: {elem.get('text', '')}")
            elif etype == "icon_group":
                elements_desc.append(f"图标组: {', '.join(elem.get('items', []))}")
            elif etype == "image":
                image_key = f"{seg.get('id', '')}:{elem.get('id', '')}"
                if (generated_images or {}).get(image_key):
                    elem_id = elem.get("id", "")
                    elements_desc.append(
                        f"已生成AI图片(id={elem_id}): "
                        f"使用标记 {{{{IMG_{elem_id}}}}} 作为占位，"
                        f"系统会自动替换为 <img> 标签。"
                        f"描述: {elem.get('description', '')}"
                    )
                else:
                    elements_desc.append(f"插图: {elem.get('description', '')}")
            elif etype == "chart_line":
                elements_desc.append(f"折线图: {elem.get('description', '')}")
            elif etype == "comparison_panel":
                items = [
                    f"{i.get('title', '')}({i.get('content', '')})"
                    for i in elem.get("items", [])
                ]
                elements_desc.append(f"对比面板: {' vs '.join(items)}")
            elif etype == "flow_step":
                elements_desc.append(f"流程步骤: {' → '.join(elem.get('steps', []))}")
            elif etype == "activity_step":
                elements_desc.append(f"活动步骤: {' → '.join(elem.get('steps', []))}")
            else:
                text = elem.get("text", elem.get("description", ""))
                elements_desc.append(f"{etype}: {text}" if text else etype)

        anims_desc = []
        for a in seg.get("animations", []):
            anims_desc.append(f"{a['target']}: {a['effect']}")

        scene = (
            f"第{seg['id']}页（{seg['visual_type']}，音频{seg.get('audio_duration_sec', '?')}秒）:\n"
            f"  内容: {'; '.join(elements_desc)}\n"
            f"  动画: {', '.join(anims_desc)}\n"
            "  非可见参考旁白（仅用于语义理解和音频时长，不得作为页面文字渲染）: "
            f"{seg['narration'][:80]}..."
        )
        scenes.append(scene)

    return "\n\n".join(scenes)


# ============================================================
# Step 5: 构建 prompt
# ============================================================
def build_batch_prompt(
    batch: list[Segment],
    prompt_template: str,
    lesson_title: str,
    lesson_description: str,
    theme_prompt: str = "",
    layout_prompt: str = "",
    generated_images: dict[str, str] | None = None,
) -> str:
    """为一批 segments 构建 LLM prompt。"""
    scenes = build_scenes_description(batch, generated_images=generated_images)
    examples = build_examples_section(batch)

    def rebuild(
        *,
        max_items: int | None = None,
        component_guidance: str | None = None,
        drop_examples: bool = False,
        truncate_scenes: bool = False,
    ) -> str:
        guidance = component_guidance
        if guidance is None:
            guidance = build_component_guidance(batch, max_items=max_items)
        actual_examples = "" if drop_examples else examples
        actual_scenes = scenes
        if truncate_scenes and len(scenes) > 600:
            actual_scenes = scenes[:600] + "\n\n...（场景描述已截断）"
        return _fill_generation_prompt(
            prompt_template=prompt_template,
            lesson_title=lesson_title,
            lesson_description=lesson_description,
            scenes=actual_scenes,
            component_guidance=guidance,
            theme_prompt=theme_prompt,
            layout_prompt=layout_prompt,
            examples_section=actual_examples,
            slide_count=len(batch),
        )

    prompt = rebuild()
    if len(prompt) > PROMPT_SOFT_CHAR_LIMIT:
        prompt = enforce_prompt_budget(prompt, rebuild_with_component_guidance=rebuild)
    return prompt


# ============================================================
# Step 6: LLM 生成
# ============================================================
def generate_batch(prompt: str, *, model: str = MODEL, max_tokens: int = MAX_TOKENS, timeout: float = GENERATE_TIMEOUT) -> str:
    """调用 LLM 生成一批 slide。带自动重试。"""
    print(f"  🤖 正在调用 {model} 生成 (max_tokens={max_tokens}, timeout={timeout}s)...")

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        start = time.time()
        try:
            result = chat(
                [{"role": "user", "content": prompt}],
                model=model,
                temperature=TEMPERATURE,
                max_tokens=max_tokens,
                timeout=timeout,
            )

            elapsed = time.time() - start
            print(f"  ✅ 生成完成: {elapsed:.1f}s, {len(result)} 字符")
            return result
        except Exception as e:
            elapsed = time.time() - start
            print(f"  ❌ 第 {attempt} 次失败 ({elapsed:.1f}s): {type(e).__name__}: {str(e)[:100]}")
            if attempt < max_retries:
                wait = 5 * attempt
                print(f"  ⏳ 等待 {wait}s 后重试...")
                time.sleep(wait)
            else:
                print(f"  💥 已达最大重试次数 ({max_retries})，放弃")
                raise
    raise RuntimeError("LLM 生成失败")


def build_slide_count_repair_prompt(
    *,
    lesson_title: str,
    lesson_description: str,
    batch: list[Segment],
    expected_count: int,
    actual_count: int,
    previous_batch_html: str,
    theme_prompt: str = "",
    layout_prompt: str = "",
) -> str:
    """Build a focused prompt that asks the model to regenerate one batch with exact count."""
    scenes = build_scenes_description(batch)
    return f"""你正在修复一批教学动画 slide 的数量错误。

任务：重新生成这一批 slide HTML，并且必须严格输出 {expected_count} 个 `<div class="slide">...</div>`。

课程标题：{lesson_title}
课程描述：{lesson_description}

数量错误：
- 期望 slide 数量：{expected_count}
- 当前实际 slide 数量：{actual_count}

必须遵守：
- 每个 segment 只能对应 1 个 slide。
- 不要合并 segment，也不要拆分 segment。
- 不要静默删除内容来凑数量；请按下方 scenes 重新生成正确的一一对应 slide。
- 只输出 slide div 和必要的 style；不要输出 markdown、DOCTYPE、html、head、body、script。
- 输出后可被正则提取为恰好 {expected_count} 个 class 包含 slide 的 div。

Scenes:
{scenes}

当前错误输出（用于参考风格与内容，数量不可信）：
{previous_batch_html}

{theme_prompt}

{layout_prompt}
""".strip()


def repair_batch_slide_count(
    *,
    slides: list[str],
    custom_css: str,
    batch: list[Segment],
    lesson_title: str,
    lesson_description: str,
    theme_prompt: str,
    layout_prompt: str,
    model: str,
    max_tokens: int,
    generate_fn: Callable[..., str] = generate_batch,
    max_attempts: int = MAX_BATCH_COUNT_REPAIR_ATTEMPTS,
    timeout: float = REPAIR_TIMEOUT,
) -> tuple[list[str], str]:
    """Try to regenerate a batch when extracted slide count does not match its segments."""
    expected_count = len(batch)
    if len(slides) == expected_count:
        return slides, custom_css

    current_slides = slides
    current_css = custom_css
    for attempt in range(1, max_attempts + 1):
        print(f"  ⚠️ batch slide 数量不匹配: 期望 {expected_count}, 实际 {len(current_slides)}，尝试数量修复 {attempt}/{max_attempts}")
        repair_prompt = build_slide_count_repair_prompt(
            lesson_title=lesson_title,
            lesson_description=lesson_description,
            batch=batch,
            expected_count=expected_count,
            actual_count=len(current_slides),
            previous_batch_html="\n\n".join(current_slides),
            theme_prompt=theme_prompt,
            layout_prompt=layout_prompt,
        )
        llm_output = generate_fn(repair_prompt, model=model, max_tokens=max_tokens, timeout=timeout)
        repaired_slides_html, repaired_css = extract_slides(llm_output)
        repaired_slides = split_slides_html(repaired_slides_html)
        if len(repaired_slides) == expected_count:
            print("  ✅ batch slide 数量修复成功")
            return repaired_slides, repaired_css or current_css

        current_slides = repaired_slides
        current_css = repaired_css or current_css

    print("  ⚠️ batch slide 数量修复未得到可接受输出，交由最终校验报错")
    return current_slides, current_css


def generate_batch_slides(
    *,
    prompt: str,
    batch: list[Segment],
    lesson_title: str,
    lesson_description: str,
    theme_prompt: str,
    layout_prompt: str,
    model: str,
    max_tokens: int,
    generate_fn: Callable[..., str] = generate_batch,
    timeout: float = GENERATE_TIMEOUT,
) -> tuple[list[str], str]:
    """Generate, extract, and pre-repair a batch before final slide-count validation."""
    configure_console_output()
    llm_output = generate_fn(prompt, model=model, max_tokens=max_tokens, timeout=timeout)
    slides_html, custom_css = extract_slides(llm_output)
    slides = split_slides_html(slides_html)
    return repair_batch_slide_count(
        slides=slides,
        custom_css=custom_css,
        batch=batch,
        lesson_title=lesson_title,
        lesson_description=lesson_description,
        theme_prompt=theme_prompt,
        layout_prompt=layout_prompt,
        model=model,
        max_tokens=max_tokens,
        generate_fn=generate_fn,
        timeout=timeout,
    )


# ============================================================
# Step 7: 解析输出
# ============================================================
def extract_slides(llm_output: str) -> tuple[str, str]:
    """从 LLM 输出中提取 slide HTML 和自定义 CSS。

    Returns:
        (slides_html: str, custom_css: str)
    """
    text = llm_output.strip()

    # 清理 markdown 包裹
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    # 提取 <style> 标签中的自定义 CSS（如有）
    custom_css = ""
    style_pattern = re.compile(r"<style[^>]*>(.*?)</style>", re.DOTALL)
    style_matches = style_pattern.findall(text)
    if style_matches:
        custom_css = "\n".join(style_matches).strip()

    # 提取所有 <div class="slide"...>...</div> 块
    slides = _extract_slide_divs(text)

    if not slides:
        # 兜底：尝试从完整 HTML 中提取
        doctype_pos = text.find("<!DOCTYPE")
        if doctype_pos >= 0:
            text = text[doctype_pos:]
            slides = _extract_slide_divs(text)

    if not slides:
        # 栈匹配 + 浏览器 DOM 兜底均未提取到 slide。返回空串而非原始文本：
        # 原始文本不是合法 slide，伪装成 slides_html 只会把错误延后到下游、爆在信息更少处。
        # 交由 repair_batch_slide_count 数量修复 / generate() 占位补齐统一处理（根因 6 / P5）。
        print("  ⚠️ 未能提取到 slide div（栈匹配 + 浏览器兜底均失败），返回空交由数量修复/占位处理")
        return "", custom_css

    print(f"  📋 提取到 {len(slides)} 个 slide")
    return "\n\n".join(slides), custom_css


def split_slides_html(slides_html: str) -> list[str]:
    """将一段 slide HTML 拆成逐页列表。"""
    return _extract_slide_divs(slides_html)


def inject_generated_images(
    slides: list[str],
    batch: list[Segment],
    generated_images: dict[str, str],
) -> list[str]:
    """将 {{IMG_eN}} 占位符替换为实际 <img> 标签。

    Args:
        slides: 该 batch 生成的 slide HTML 列表
        batch: 对应的 segment 列表
        generated_images: {"seg_id:elem_id": "images/fig1.png"} 字典（相对路径）

    Returns:
        替换后的 slide 列表
    """
    if not generated_images:
        return slides

    result = []
    for i, slide_html in enumerate(slides):
        if i < len(batch):
            seg = batch[i]
            seg_id = seg.get("id", "")
            for elem in seg.get("elements", []):
                if elem.get("type") != "image":
                    continue
                elem_id = elem.get("id", "")
                key = f"{seg_id}:{elem_id}"
                image_path = generated_images.get(key)
                if not image_path:
                    continue
                placeholder = "{{IMG_" + elem_id + "}}"
                if placeholder in slide_html:
                    desc = html.escape(str(elem.get("description", "")))
                    img_tag = (
                        f'<img src="{image_path}" alt="{desc}" '
                        f'style="max-width:100%;max-height:100%;object-fit:contain;'
                        f'border-radius:12px;">'
                    )
                    slide_html = slide_html.replace(placeholder, img_tag)
                else:
                    print(
                        f"  ⚠️ 未找到占位符 {placeholder} "
                        f"(slide {seg_id})，跳过图片注入"
                    )
        result.append(slide_html)
    return result


def load_textbook_images(
    segments: list[Segment], image_dir: str | Path | None
) -> dict[str, str]:
    """读取 storyboard 引用的教材原图（image 元素的 src），返回绝对路径。

    返回 {"seg_id:elem_id": "/abs/path/images/fig1-1_xxx.png"}，与 AI 生成图共用同一套
    {{IMG_eN}} 占位 / inject_generated_images 注入机制嵌入 HTML。
    image_dir 不存在、或某张图文件缺失时跳过该图并告警，不中断流程。
    """
    result: dict[str, str] = {}
    if not image_dir:
        return result
    base = Path(image_dir).resolve()
    if not base.is_dir():
        return result

    for seg in segments:
        seg_id = seg.get("id", "")
        for elem in seg.get("elements", []):
            if elem.get("type") != "image":
                continue
            src = elem.get("src", "")
            elem_id = elem.get("id", "")
            if not src or not elem_id:
                continue
            # 防路径穿越：src 来自 LLM 输出，只允许 images/ 内的纯文件名，
            # 拒绝带目录分隔符 / .. / 绝对路径的可疑值（否则可读出任意系统文件）
            if "/" in src or "\\" in src or src.startswith("..") or Path(src).is_absolute():
                print(f"  ⚠️ 跳过可疑图片路径（疑似路径穿越）: {src!r}")
                continue
            img_path = base / src
            if not img_path.is_file():
                print(f"  ⚠️ 教材原图缺失，跳过: {img_path}")
                continue
            result[f"{seg_id}:{elem_id}"] = str(img_path)
            print(f"  🖼️ 教材原图 {src} → seg{seg_id}:{elem_id}")
    return result


# 兜底解析复用项目录制/布局自检所用的浏览器 channel（默认 msedge），避免额外下载
# Playwright 自带 chromium；系统无该浏览器时 _extract_slide_divs_browser 会优雅降级返回 []。
_EXTRACT_BROWSER_CHANNEL = RECORD_BROWSER_CHANNEL


def _extract_slide_divs(html: str) -> list[str]:
    """提取所有 slide div 块。

    优先用零开销的栈匹配（快路径）；当 LLM 输出 div 开闭不平衡、导致栈匹配
    提取不到任何 slide 时，回退到浏览器 DOM 解析——与下游消费者（slide-controller、
    布局自检、录制）使用同一套容错解析器，避免"提取阶段判死、浏览器其实能正常渲染"
    的解析器宽容度错配（见 docs/fix-plan-json-to-html.md 根因 1）。
    """
    slides = _extract_slide_divs_stack(html)
    if slides:
        return slides
    # 快路径返回空，极可能是 div 不平衡。用浏览器 DOM 兜底。
    browser_slides = _extract_slide_divs_browser(html)
    if browser_slides:
        print(f"  🌐 栈匹配失败，浏览器 DOM 兜底提取到 {len(browser_slides)} 个 slide")
    return browser_slides


def _extract_slide_divs_stack(html: str) -> list[str]:
    """栈匹配快路径：要求 div 严格平衡，零依赖、零开销。"""
    # 剥离 HTML 注释，避免注释中的 <div 干扰深度计数
    html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)

    slides: list[str] = []
    pattern = re.compile(
        r'<div\s[^>]*class="[^"]*(?<![\w-])slide(?![\w-])[^"]*"[^>]*>',
        re.DOTALL,
    )

    for m in pattern.finditer(html):
        start = m.start()
        pos = m.end()
        depth = 1

        while pos < len(html) and depth > 0:
            next_open = html.find("<div", pos)
            next_close = html.find("</div>", pos)

            if next_close == -1:
                break

            if next_open != -1 and next_open < next_close:
                depth += 1
                pos = next_open + 4
            else:
                depth -= 1
                pos = next_close + 6

        if depth == 0:
            slide_html = html[start:pos]
            slides.append(slide_html)

    return slides


def _extract_slide_divs_browser(
    html: str, *, browser_channel: str = _EXTRACT_BROWSER_CHANNEL
) -> list[str]:
    """浏览器 DOM 兜底：把 LLM 输出加载进浏览器，取规范化后的顶层 .slide。

    浏览器按 DOM 语义自动补齐缺失的 </div>，得到与最终渲染一致的结构。只返回顶层
    slide（祖先中没有其它 .slide 的元素），避免漏闭合造成的嵌套重复。浏览器不可用
    （未安装 Playwright / 浏览器二进制）时优雅降级返回 []，不破坏快路径行为。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  ⚠️ 浏览器兜底不可用：未安装 playwright")
        return []

    wrapped = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
        f"<body>{html}</body></html>"
    )
    extract_js = (
        "() => Array.from(document.querySelectorAll('.slide'))"
        ".filter(e => !e.parentElement || !e.parentElement.closest('.slide'))"
        ".map(e => e.outerHTML)"
    )
    try:
        with sync_playwright() as pw:
            launch_kwargs: dict[str, Any] = {"headless": True}
            if browser_channel:
                launch_kwargs["channel"] = browser_channel
            browser = pw.chromium.launch(**launch_kwargs)
            try:
                page = browser.new_page()
                page.set_content(wrapped, wait_until="domcontentloaded")
                slides = page.evaluate(extract_js)
            finally:
                browser.close()
        return [s for s in slides if isinstance(s, str) and s.strip()]
    except Exception as e:
        print(f"  ⚠️ 浏览器兜底解析失败: {type(e).__name__}: {str(e)[:80]}")
        return []


# ============================================================
# Step 8: 合并
# ============================================================
def merge_html(
    all_slides: list[str],
    custom_css_list: list[str],
    shell_template: str,
    css_framework: str,
    js_controller: str,
    js_particles: str,
    durations_ms: list[int],
    title: str,
    theme: JsonDict | None = None,
    timelines: list[list[dict[str, Any]]] | None = None,
    transitions: list[str] | None = None,
) -> str:
    """合并所有组件为最终 HTML。"""
    slides_html = "\n\n".join(all_slides)

    # 清理 LLM 可能输出的多余结构
    slides_html = slides_html.replace('<div class="slide-container">', '')
    slides_html = slides_html.replace("</div><!-- /slide-container -->", "")
    slides_html = slides_html.replace("</div><!-- slide-container -->", "")

    # 先移除所有 active（LLM 可能自己加了），再给第一个 slide 加 active
    # 用正则兼容多类名情况（如 class="slide intro" 或 class="slide active hero"）
    _SLIDE_CLASS_RE = re.compile(r'(<div\s[^>]*class="[^"]*)\bactive\b\s*([^"]*\bslide\b[^"]*")')
    _ACTIVE_BEFORE_SLIDE_RE = re.compile(r'(<div\s[^>]*class="[^"]*\bslide\b[^"]*)\s*\bactive\b([^"]*")')
    _FIRST_SLIDE_RE = re.compile(r'(<div\s[^>]*class="[^"]*)\bslide\b([^"]*")')

    slides_html = _SLIDE_CLASS_RE.sub(r'\1\2', slides_html)
    slides_html = _ACTIVE_BEFORE_SLIDE_RE.sub(r'\1\2', slides_html)
    slides_html = _FIRST_SLIDE_RE.sub(r'\1slide active\2', slides_html, count=1)

    # 合并自定义 CSS（去重）
    seen_css = set()
    unique_css = []
    for css in custom_css_list:
        css_stripped = css.strip()
        if css_stripped and css_stripped not in seen_css:
            seen_css.add(css_stripped)
            unique_css.append(css_stripped)
    custom_css_merged = "\n\n".join(unique_css)

    # Theme 参数
    t = theme or {}
    bg_color = t.get("visual", {}).get("background", "#fef9f2")
    theme_css_vars = theme_to_css_vars(t) if t else ""
    particle_config = theme_to_particle_config(t) if t else {"enabled": True}
    layout_mode = theme_layout_mode(t)

    # 粒子 canvas — 只有主题启用粒子时才渲染
    particle_canvas_html = ""
    if particle_config.get("enabled", True):
        particle_canvas_html = '<canvas id="particleCanvas"></canvas>'

    # 粒子 JS — 只有主题启用粒子时才注入
    particle_js = js_particles if particle_config.get("enabled", True) else ""

    # 填充 shell 模板（兼容新旧两种模板）
    result = shell_template.replace("{{LESSON_TITLE}}", title)
    result = result.replace("{{THEME_CSS_VARS}}", theme_css_vars)
    result = result.replace("{{THEME_BG_COLOR}}", bg_color)
    result = result.replace("{{LAYOUT_MODE}}", layout_mode)
    result = result.replace("{{CSS_FRAMEWORK}}", css_framework)
    result = result.replace("{{CUSTOM_CSS}}", custom_css_merged)
    result = result.replace("{{SLIDES}}", slides_html)
    result = result.replace("{{PARTICLE_CANVAS}}", particle_canvas_html)
    result = result.replace("{{JS_CONTROLLER}}", js_controller)
    result = result.replace("{{JS_PARTICLES}}", particle_js)
    result = result.replace("{{SLIDE_DURATIONS}}", str(durations_ms))
    # 防止 JSON 内容中出现 </script> 破坏 HTML 结构
    timelines_json = json.dumps(timelines or [], ensure_ascii=False).replace("</", r"<\/")
    transitions_json = json.dumps(transitions or [], ensure_ascii=False).replace("</", r"<\/")
    result = result.replace("{{SLIDE_TIMELINES}}", timelines_json)
    result = result.replace("{{SLIDE_TRANSITIONS}}", transitions_json)

    return result


# ============================================================
# Step 9: 校验
# ============================================================
def _extract_slide_durations(html: str) -> list[int] | None:
    """Extract the slide duration array injected into the final HTML."""
    match = re.search(r"var\s+slideDurations\s*=\s*(\[[^;]*\])\s*;", html)
    if not match:
        return None

    try:
        values = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None

    if not isinstance(values, list):
        return None
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in values):
        return None
    return values


def validate_output(
    html: str,
    expected_slides: int,
    theme: dict[str, Any] | None = None,
    expected_durations_ms: list[int] | None = None,
) -> dict[str, Any]:
    """自动校验输出 HTML 质量。根据主题调整校验规则。"""
    configure_console_output()
    t = theme or {}
    effects = t.get("effects", {})
    has_particles = effects.get("particles", True)
    has_noise = effects.get("noise_overlay", True)
    bg_color = t.get("visual", {}).get("background", "#fef9f2")
    layout_mode = theme_layout_mode(t)

    html_before_scripts = html.split("<script", 1)[0]
    slide_count = len(_extract_slide_divs(html_before_scripts))
    checks = {
        "slide数量": slide_count == expected_slides,
        "SlideController": "SlideController" in html,
        "无导航按钮": "nextBtn" not in html and "prevBtn" not in html,
        f"背景色({bg_color})": bg_color in html,
        ".anim系统": ".anim" in html,
        f"data-layout={layout_mode}": f'data-layout="{layout_mode}"' in html,
    }

    # 主题相关校验（只有明亮风格才检查粒子/噪点/SVG）
    if has_particles:
        checks["particleCanvas"] = "particleCanvas" in html
    if has_noise:
        checks["SVG噪点"] = "feTurbulence" in html
    if t.get("theme_id") == "bright":
        checks["SVG图形(≥8个svg)"] = html.count("<svg") >= 8

    if expected_durations_ms is not None:
        actual_durations = _extract_slide_durations(html)
        checks["slideDurations存在"] = actual_durations is not None
        checks["slideDurations数量"] = actual_durations is not None and len(actual_durations) == expected_slides
        checks["slideDurations匹配"] = actual_durations == expected_durations_ms

    print("\n🔍 校验结果:")
    all_pass = True
    for name, ok in checks.items():
        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"  [{status}] {name}")
        if not ok:
            all_pass = False

    print(f"\n  总计: {slide_count} 页 slide, {len(html)} 字符")

    return {"all_pass": all_pass, "checks": checks, "slide_count": slide_count}


# ============================================================
# Step 10: 浏览器布局自检与回流修复
# ============================================================
def layout_report_path(output_path: Path, attempt: int) -> Path:
    suffix = "layout" if attempt == 0 else f"layout-repair{attempt}"
    return output_path.with_name(f"{output_path.stem}.{suffix}.json")


def viewport_report_path(report_path: Path, width: int, height: int, index: int) -> Path:
    if index == 0:
        return report_path
    return report_path.with_name(f"{report_path.stem}-{width}x{height}{report_path.suffix}")


def run_layout_qa(
    html_path: Path,
    report_path: Path,
    *,
    browser_channel: str = "msedge",
) -> tuple[bool, JsonDict]:
    """运行多视口 Playwright 几何自检，返回是否通过和合并后的 JSON 报告。"""
    checker = _PACKAGE_DIR.parents[1] / "scripts" / "check_layout.py"
    if not checker.exists():
        print(f"  ⚠️ 未找到布局自检脚本: {checker}")
        return True, {}

    merged_report: JsonDict = {
        "viewports": [
            {"width": width, "height": height}
            for width, height in LAYOUT_QA_VIEWPORTS
        ],
        "slides": [],
        "staticRisks": [],
        "reports": [],
    }
    passed = True

    for index, (width, height) in enumerate(LAYOUT_QA_VIEWPORTS):
        current_report_path = viewport_report_path(report_path, width, height, index)
        cmd = [
            sys.executable,
            str(checker),
            str(html_path),
            "--width",
            str(width),
            "--height",
            str(height),
            "--json",
            str(current_report_path),
        ]
        if browser_channel:
            cmd.extend(["--browser-channel", browser_channel])

        print(f"  [layout-qa] {html_path.name} @ {width}x{height}")
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.stdout:
            print(proc.stdout.strip().encode("gbk", errors="backslashreplace").decode("gbk"))
        if proc.stderr:
            print(proc.stderr.strip().encode("gbk", errors="backslashreplace").decode("gbk"))

        if current_report_path.exists():
            report = json.loads(current_report_path.read_text(encoding="utf-8"))
        else:
            report = {
                "viewport": {"width": width, "height": height},
                "slides": [],
                "staticRisks": [],
                "error": "Layout checker did not write a JSON report.",
            }

        slides = report.get("slides", [])
        if isinstance(slides, list):
            for slide in slides:
                if isinstance(slide, dict):
                    slide["viewport"] = {"width": width, "height": height}
            merged_report["slides"].extend(slides)
        if index == 0:
            merged_report["viewport"] = report.get("viewport")
            merged_report["staticRisks"] = report.get("staticRisks", [])
        merged_report["reports"].append(str(current_report_path))
        if proc.returncode != 0:
            passed = False

    return passed, merged_report

def failing_slide_indices(report: JsonDict) -> list[int]:
    """返回全局 1-based 失败页码。"""
    return sorted({int(slide["index"]) for slide in report.get("slides", []) if not slide.get("passed", True)})


def summarize_layout_failures(report: JsonDict, max_issues_per_slide: int = 5) -> str:
    """压缩布局报告，只保留 LLM 修复需要的失败信息。"""
    lines = []
    viewports = report.get("viewports") or []
    if viewports:
        label = ", ".join(f"{v.get('width')}x{v.get('height')}" for v in viewports)
        lines.append(f"Viewports: {label}")
    else:
        viewport = report.get("viewport") or {}
        if viewport:
            lines.append(f"Viewport: {viewport.get('width')}x{viewport.get('height')}")

    static_risks = report.get("staticRisks", [])
    if static_risks:
        lines.append("Static risks:")
        for risk in static_risks[:8]:
            lines.append(f"- {risk.get('type')}: {risk.get('message')}")

    for slide in report.get("slides", []):
        if slide.get("passed", True):
            continue
        slide_viewport = slide.get("viewport") or {}
        viewport_suffix = ""
        if slide_viewport:
            viewport_suffix = f" @ {slide_viewport.get('width')}x{slide_viewport.get('height')}"
        lines.append(f"Slide {slide.get('index')}{viewport_suffix} failed:")
        fail_issues = [issue for issue in slide.get("issues", []) if issue.get("severity") == "fail"]
        for issue in fail_issues[:max_issues_per_slide]:
            details = {k: v for k, v in issue.items() if k not in {"severity", "type"}}
            details_text = json.dumps(details, ensure_ascii=False)[:1000]
            lines.append(f"- {issue.get('type')}: {details_text}")

    return "\n".join(lines) if lines else "No blocking failures."

def build_layout_repair_prompt(
    *,
    lesson_title: str,
    lesson_description: str,
    batch: list[Segment],
    batch_start_index: int,
    batch_slides: list[str],
    failed_global_indices: list[int],
    qa_summary: str,
    theme_prompt: str,
    layout_prompt: str,
) -> str:
    scenes = build_scenes_description(batch)
    failed_set = set(failed_global_indices)
    failed_html_parts = []
    for local_idx, slide_html in enumerate(batch_slides, start=1):
        global_idx = batch_start_index + local_idx
        if global_idx in failed_set:
            failed_html_parts.append(f"<!-- global slide {global_idx}, batch-local {local_idx} -->\n{slide_html}")

    previous_html = "\n\n".join(batch_slides)
    failed_html = "\n\n".join(failed_html_parts)

    template = load_prompt_template("slide_repair.md")
    prompt = (
        template.replace("{SLIDE_COUNT}", str(len(batch_slides)))
        .replace("{LESSON_TITLE}", lesson_title)
        .replace("{LESSON_DESCRIPTION}", lesson_description)
        .replace("{SCENES_DESCRIPTION}", scenes)
        .replace("{QA_SUMMARY}", qa_summary)
        .replace("{FAILED_HTML}", failed_html)
        .replace("{PREVIOUS_BATCH_HTML}", previous_html)
        .replace("{THEME_PROMPT}", theme_prompt)
        .replace("{LAYOUT_PROMPT}", layout_prompt)
    )

    # Budget control: repair prompts contain full HTML, so they have a higher limit.
    # If still over, truncate PREVIOUS_BATCH_HTML (keep only failed slides' context).
    if len(prompt) > REPAIR_PROMPT_HARD_LIMIT:
        non_failed_parts = []
        for local_idx, slide_html in enumerate(batch_slides, start=1):
            global_idx = batch_start_index + local_idx
            if global_idx not in failed_set:
                non_failed_parts.append(
                    f"<!-- global slide {global_idx}, batch-local {local_idx} (non-failed, truncated) -->\n"
                    f"<div class=\"slide\" data-idx=\"{global_idx}\">...</div>"
                )
        truncated_previous = "\n\n".join(failed_html_parts + non_failed_parts)
        prompt = (
            template.replace("{SLIDE_COUNT}", str(len(batch_slides)))
            .replace("{LESSON_TITLE}", lesson_title)
            .replace("{LESSON_DESCRIPTION}", lesson_description)
            .replace("{SCENES_DESCRIPTION}", scenes)
            .replace("{QA_SUMMARY}", qa_summary)
            .replace("{FAILED_HTML}", failed_html)
            .replace("{PREVIOUS_BATCH_HTML}", truncated_previous)
            .replace("{THEME_PROMPT}", theme_prompt)
            .replace("{LAYOUT_PROMPT}", layout_prompt)
        )

    return prompt


def _build_single_slide_repair_prompt(
    *,
    lesson_title: str,
    lesson_description: str,
    scene_description: str,
    slide_html: str,
    qa_summary: str,
    theme_prompt: str,
    layout_prompt: str,
) -> str:
    """Build a minimal prompt to repair a single failed slide."""
    template = load_prompt_template("slide_single_repair.md")
    return (
        template.replace("{LESSON_TITLE}", lesson_title)
        .replace("{LESSON_DESCRIPTION}", lesson_description)
        .replace("{SCENE_DESCRIPTION}", scene_description)
        .replace("{SLIDE_HTML}", slide_html)
        .replace("{QA_SUMMARY}", qa_summary)
        .replace("{THEME_PROMPT}", theme_prompt)
        .replace("{LAYOUT_PROMPT}", layout_prompt)
    )


def repair_single_slides(
    *,
    segments: list[Segment],
    batch_slide_lists: list[list[str]],
    all_custom_css: list[str],
    report: JsonDict,
    title: str,
    lesson_description: str,
    theme_prompt: str,
    layout_prompt: str,
    model: str,
    max_tokens: int,
) -> bool:
    """Repair only the individual failed slides, one at a time. Returns True if any repaired.

    Unlike replace_failed_batches which re-sends the entire batch, this sends only
    the single failed slide HTML to the LLM — much smaller prompt, faster, cheaper.
    """
    failed_indices = failing_slide_indices(report)
    if not failed_indices:
        return False

    qa_summary = summarize_layout_failures(report)

    # Build a flat index → (batch_idx, local_idx) mapping
    slide_to_batch: dict[int, tuple[int, int]] = {}
    global_idx = 1
    for batch_idx, slide_list in enumerate(batch_slide_lists):
        for local_idx in range(len(slide_list)):
            slide_to_batch[global_idx] = (batch_idx, local_idx)
            global_idx += 1

    repaired_any = False

    for fail_idx in failed_indices:
        if fail_idx not in slide_to_batch:
            continue
        batch_idx, local_idx = slide_to_batch[fail_idx]

        # Get the segment for this slide (scene description)
        seg_global_idx = fail_idx - 1  # 0-based
        seg = segments[seg_global_idx] if seg_global_idx < len(segments) else None
        scene_desc = build_scenes_description([seg]) if seg else f"Slide {fail_idx}"

        slide_html = batch_slide_lists[batch_idx][local_idx]

        # Filter QA summary to only this slide's failures
        slide_failures = []
        for slide in report.get("slides", []):
            if slide.get("index") == fail_idx:
                for issue in slide.get("issues", []):
                    if issue.get("severity") == "fail":
                        details = {k: v for k, v in issue.items() if k not in {"severity", "type"}}
                        slide_failures.append(
                            f"- {issue.get('type')}: {json.dumps(details, ensure_ascii=False)[:500]}"
                        )
        if not slide_failures:
            continue
        single_qa = f"Slide {fail_idx} 失败:\n" + "\n".join(slide_failures[:6])

        print(f"  [single-repair] 修复 slide {fail_idx} ({len(slide_html)} chars HTML)")
        prompt = _build_single_slide_repair_prompt(
            lesson_title=title,
            lesson_description=lesson_description,
            scene_description=scene_desc,
            slide_html=slide_html,
            qa_summary=single_qa,
            theme_prompt=theme_prompt,
            layout_prompt=layout_prompt,
        )

        try:
            llm_output = generate_batch(prompt, model=model, max_tokens=max_tokens, timeout=REPAIR_TIMEOUT)
        except Exception as e:
            print(f"  ⚠️ slide {fail_idx} 修复失败: {type(e).__name__}: {str(e)[:100]}")
            continue

        repaired_html, custom_css = extract_slides(llm_output)
        repaired_slides = split_slides_html(repaired_html)

        if len(repaired_slides) != 1:
            print(f"  ⚠️ slide {fail_idx} 修复输出 {len(repaired_slides)} 个 slide（期望 1），跳过")
            continue

        batch_slide_lists[batch_idx][local_idx] = repaired_slides[0]
        if custom_css:
            all_custom_css.append(custom_css)
        repaired_any = True
        print(f"  ✅ slide {fail_idx} 修复成功")

    return repaired_any


def replace_failed_batches(
    *,
    batches: list[list[Segment]],
    batch_slide_lists: list[list[str]],
    all_custom_css: list[str],
    report: JsonDict,
    title: str,
    lesson_description: str,
    theme_prompt: str,
    layout_prompt: str,
    model: str,
    max_tokens: int,
) -> bool:
    """按失败页所在 batch 调 LLM 修复，成功替换返回 True。"""
    failed_indices = failing_slide_indices(report)
    if not failed_indices:
        return False

    batch_ranges = []
    start = 0
    for slide_list in batch_slide_lists:
        end = start + len(slide_list)
        batch_ranges.append((start + 1, end))
        start = end

    repaired_any = False
    qa_summary = summarize_layout_failures(report)

    for batch_idx, (start_index, end_index) in enumerate(batch_ranges):
        failed_in_batch = [idx for idx in failed_indices if start_index <= idx <= end_index]
        if not failed_in_batch:
            continue

        print(f"  [layout-repair] Batch {batch_idx + 1}: 全局页 {failed_in_batch}")
        repair_prompt = build_layout_repair_prompt(
            lesson_title=title,
            lesson_description=lesson_description,
            batch=batches[batch_idx],
            batch_start_index=start_index - 1,
            batch_slides=batch_slide_lists[batch_idx],
            failed_global_indices=failed_in_batch,
            qa_summary=qa_summary,
            theme_prompt=theme_prompt,
            layout_prompt=layout_prompt,
        )
        try:
            llm_output = generate_batch(repair_prompt, model=model, max_tokens=max_tokens, timeout=REPAIR_TIMEOUT)
        except Exception as e:
            print(f"  ⚠️ 布局修复 LLM 调用失败: {type(e).__name__}: {str(e)[:120]}")
            print(f"  ⚠️ 跳过该 batch 修复，保留当前输出")
            continue
        repaired_slides_html, custom_css = extract_slides(llm_output)
        repaired_slides = split_slides_html(repaired_slides_html)
        if len(repaired_slides) != len(batch_slide_lists[batch_idx]):
            print(
                f"  ⚠️ 修复输出 slide 数量不匹配: "
                f"期望 {len(batch_slide_lists[batch_idx])}, 实际 {len(repaired_slides)}，跳过该 batch"
            )
            continue

        batch_slide_lists[batch_idx] = repaired_slides
        if custom_css:
            all_custom_css.append(custom_css)
        repaired_any = True

    return repaired_any


# ============================================================
# 公共 API: generate()
# ============================================================
def generate(
    json_path: str | Path,
    *,
    output_dir: Path | None = None,
    model: str = MODEL,
    batch_size: int = BATCH_SIZE,
    max_tokens: int = MAX_TOKENS,
    theme_id: str | None = None,
    layout_repair_attempts: int = MAX_LAYOUT_REPAIR_ATTEMPTS,
    layout_browser_channel: str = "msedge",
    skip_image_gen: bool = False,
    only: list[int] | None = None,
) -> Path:
    """完整流水线：storyboard JSON → 单文件 HTML。

    Args:
        json_path: storyboard JSON 文件路径
        output_dir: 输出目录，默认使用 config.DEFAULT_OUTPUT_DIR
        model: LLM 模型名
        batch_size: 每批生成的 slide 数量
        theme_id: 主题 ID（"bright" / "3b1b-math"），None 使用默认
        skip_image_gen: 跳过 AI 图片生成，所有 image 元素使用 SVG/CSS
        only: 1-based 页码列表；传入时只生成指定页的局部 HTML

    Returns:
        生成的 HTML 文件路径

    Raises:
        FileNotFoundError: JSON 文件不存在
        ValueError: JSON 格式错误
    """
    configure_console_output()

    # 0. 加载主题
    theme = load_theme(theme_id)
    theme_prompt = theme_prompt_section(theme)
    layout_prompt = theme_layout_prompt_section(theme)
    print("=" * 60)
    print(f"🎬 分批生成+合并 Pipeline")
    print(f"🎨 主题: {theme['name']} ({theme['theme_id']})")
    print(f"📐 布局: {theme_layout_mode(theme)}")
    print("=" * 60)

    # 1. 解析 JSON
    storyboard = parse_storyboard(json_path)
    segments = select_segments_by_pages(storyboard["segments"], only)
    if only:
        selected = page_selection_suffix(only).removeprefix("-p").replace("_", ", ")
        print(f"🎯 仅生成页面: {selected}")
    title = storyboard["title"]

    # 2. 分批
    batches = split_batches(segments, batch_size)

    # 2a. 载入 storyboard 引用的教材原图（src 指向 JSON 同级 images/ 目录）
    textbook_image_dir = Path(json_path).parent / "images"
    textbook_images = load_textbook_images(segments, textbook_image_dir)
    if textbook_images:
        print(f"🖼️  载入 {len(textbook_images)} 张教材原图（来自 {textbook_image_dir}）")

    # 2b. AI 图片生成（generate_images_for_storyboard 已跳过有 src 的教材原图）
    if not skip_image_gen:
        from textbook2video.llm.image_gen import generate_images_for_storyboard
        generated_images = generate_images_for_storyboard(
            segments, model=model, image_dir=str(textbook_image_dir)
        )
    else:
        generated_images = {}

    # 教材原图与 AI 图合并：两者键互斥（src / 非 src），教材原图直接采用
    generated_images = {**generated_images, **textbook_images}

    # 2c. 为仍无图的 image 元素生成 SVG 矢量示意图（按描述 + 主题配色），替代纯文字占位
    if os.environ.get("T2V_SKIP_SVG") != "1":
        from textbook2video.llm.image_gen import generate_svgs_for_storyboard
        v = theme.get("visual", {})
        svg_colors = {
            "primary": v.get("primary", "#5b8def"),
            "secondary": v.get("secondary", "#37c6e5"),
            "accent": v.get("accent", "#f8c808"),
            "line": v.get("text_dim", "#cdd8ef"),
        }
        svg_images = generate_svgs_for_storyboard(
            segments, set(generated_images.keys()), colors=svg_colors,
            model=model, image_dir=str(textbook_image_dir)
        )
        # 真图 / AI 图优先，SVG 仅补未覆盖的
        generated_images = {**svg_images, **generated_images}

    # 3. 加载模板
    print("\n📂 加载模板...")
    base_template_path = TEMPLATES_DIR / "base-template.html"
    shell_template = base_template_path.read_text(encoding="utf-8")
    print("  Shell: base-template.html (theme-aware)")
    css_framework = (TEMPLATES_DIR / "base.css").read_text(encoding="utf-8")
    js_controller = (TEMPLATES_DIR / "slide-controller.js").read_text(encoding="utf-8")
    js_particles = (TEMPLATES_DIR / "particle-canvas.js").read_text(encoding="utf-8")

    prompt_template = load_prompt_template("slide_content_core.md")
    print(f"  Prompt 模板: {len(prompt_template)} 字符")

    # 构建课程描述（从第一段旁白提取）
    lesson_description = segments[0]["narration"][:100] if segments else ""

    # 4. 分批生成：优先用确定性模板渲染（F5），visual_type/element 不支持的 fallback 到 LLM
    use_renderer = os.environ.get("T2V_DISABLE_TEMPLATE_RENDERER") != "1"
    available_image_keys = set(generated_images.keys())
    # 主题级 variant 偏好（Phase 5）：theme.json 的 preferred_variants 字段，
    # 形如 {"icon_group": ["minimal_squares"], "heading": ["badge_title", "gradient_band"]}
    theme_pref = theme.get("preferred_variants") if theme else None
    renderer = None
    if use_renderer:
        from textbook2video.template_renderer import render_slide as renderer
    print(
        f"\n🚀 开始生成（{len(batches)} 批，模型: {model}，"
        f"模板渲染: {'开' if use_renderer else '关'}"
        f"{'，主题 variant 偏好已加载' if theme_pref else ''}）"
    )
    all_slides = []
    batch_slide_lists = []
    all_custom_css = []
    global_idx = 0

    for batch_idx, batch in enumerate(batches):
        batch_num = batch_idx + 1
        print(f"\n--- Batch {batch_num}/{len(batches)} (页面 {batch[0]['id']}-{batch[-1]['id']}) ---")

        # 4a. 逐页路由：
        #   - seg.render_mode == "llm" → 直接交 LLM 自由生成（创意页：title/closing/illustration 等）
        #   - 否则先尝试模板确定性渲染；不支持就 fallback 到 LLM
        slides: list[str | None] = [None] * len(batch)
        llm_local_idxs: list[int] = []
        forced_llm = 0
        for local_i, seg in enumerate(batch):
            mode = (seg.get("render_mode") or "template").lower()
            if mode == "llm":
                llm_local_idxs.append(local_i)
                forced_llm += 1
                continue
            rendered = (
                renderer(
                    seg, global_idx + local_i, available_image_keys,
                    theme_preferences=theme_pref,
                )
                if renderer else None
            )
            if rendered:
                slides[local_i] = rendered
            else:
                llm_local_idxs.append(local_i)
        rendered_count = len(batch) - len(llm_local_idxs)
        if rendered_count:
            print(f"  🧩 模板渲染 {rendered_count}/{len(batch)} 页")
        if forced_llm:
            print(f"  🎨 render_mode=llm 显式交 LLM 自由生成 {forced_llm} 页")

        # 4b. 对不支持的页走原有 LLM 生成
        custom_css = ""
        if llm_local_idxs:
            llm_batch = [batch[i] for i in llm_local_idxs]
            vtypes = [batch[i].get("visual_type") for i in llm_local_idxs]
            print(f"  🤖 LLM fallback 生成 {len(llm_batch)} 页（{vtypes}）")
            prompt = build_batch_prompt(
                llm_batch, prompt_template, title, lesson_description,
                theme_prompt=theme_prompt,
                layout_prompt=layout_prompt,
                generated_images=generated_images,
            )
            llm_slides, custom_css = generate_batch_slides(
                prompt=prompt,
                batch=llm_batch,
                lesson_title=title,
                lesson_description=lesson_description,
                theme_prompt=theme_prompt,
                layout_prompt=layout_prompt,
                model=model,
                max_tokens=max_tokens,
            )
            for k, local_i in enumerate(llm_local_idxs):
                slides[local_i] = llm_slides[k] if k < len(llm_slides) else None

        # 4c. 占位补齐缺失页
        for local_i in range(len(slides)):
            if slides[local_i] is None:
                page_no = global_idx + local_i + 1
                slides[local_i] = (
                    f'<div class="slide">'
                    f'<div style="display:flex;align-items:center;justify-content:center;'
                    f'height:100%;color:var(--text-dim);font-size:1.2em;">'
                    f"第{page_no}页（生成缺失）"
                    f"</div></div>"
                )

        # 4d. 统一注入教材原图 / AI 图（模板与 LLM 产出的 {{IMG_eN}} 占位都在此替换）
        filled_slides = cast("list[str]", slides)
        filled_slides = inject_generated_images(filled_slides, batch, generated_images)

        global_idx += len(batch)
        batch_slide_lists.append(filled_slides)
        all_slides.append("\n\n".join(filled_slides))
        if custom_css:
            all_custom_css.append(custom_css)

    # 5. 提取 durations（兼容缺失 audio_duration_sec 的 JSON）
    durations_ms = [_duration_ms_for_segment(seg) for seg in segments]
    # 5b. 构建时间轴和转场数据
    timelines = build_slide_timelines(segments)
    from textbook2video.themes import theme_transition_style
    transitions = infer_transitions(segments, style=theme_transition_style(theme))

    # 6. 准备输出路径
    out_dir = output_dir or DEFAULT_OUTPUT_DIR
    out_dir.mkdir(exist_ok=True)
    json_stem = Path(json_path).stem.replace("_storyboard", "")
    json_stem = f"{json_stem}{page_selection_suffix(only)}"
    theme_suffix = f"-{theme['theme_id']}" if theme_id else ""
    output_path = out_dir / f"{json_stem}-pipeline{theme_suffix}.html"

    # 6b. 收集所有图片绝对路径 → 相对路径映射，供 write_current_html 替换
    # （图片保存在 storyboard 同级 images/ 目录，HTML 可能输出到不同目录）
    html_parent = output_path.parent.resolve()
    abs_to_rel: dict[str, str] = {}
    for abs_path in generated_images.values():
        resolved = Path(abs_path).resolve()
        if resolved.is_file():
            rel = os.path.relpath(str(resolved), str(html_parent))
            rel = rel.replace("\\", "/")
            abs_to_rel[str(resolved)] = rel
            # 也存 Windows 原始路径形式（inject 阶段可能写入两种格式）
            abs_to_rel[str(resolved).replace("/", "\\")] = rel

    def write_current_html() -> str:
        current_slides = ["\n\n".join(slides) for slides in batch_slide_lists]
        html = merge_html(
            all_slides=current_slides,
            custom_css_list=all_custom_css,
            shell_template=shell_template,
            css_framework=css_framework,
            js_controller=js_controller,
            js_particles=js_particles,
            durations_ms=durations_ms,
            title=title,
            theme=theme,
            timelines=timelines,
            transitions=transitions,
        )
        # 将图片绝对路径替换为相对于 HTML 文件的相对路径
        for abs_p, rel_p in abs_to_rel.items():
            html = html.replace(abs_p, rel_p)
        output_path.write_text(html, encoding="utf-8")
        print(f"💾 保存到: {output_path}")
        print(f"   大小: {len(html)} 字符")
        return html

    # 7. 合并、写入、布局 QA，失败时回流修复
    print("\n🔗 合并所有批次...")
    final_html = write_current_html()

    for attempt in range(layout_repair_attempts + 1):
        report_path = layout_report_path(output_path, attempt)
        qa_passed, layout_report = run_layout_qa(
            output_path,
            report_path,
            browser_channel=layout_browser_channel,
        )
        if qa_passed:
            print("  ✅ 布局自检通过")
            break

        failed = failing_slide_indices(layout_report)
        print(f"  ⚠️ 布局自检失败页: {failed}")
        if attempt >= layout_repair_attempts:
            print(f"  ⚠️ 已达到布局修复上限 ({layout_repair_attempts})，保留最后一次结果")
            break

        # Phase 1: CSS hot-fix (0 token, fast)
        try:
            from textbook2video.css_hotfix import apply_css_hotfixes
            fix_count = apply_css_hotfixes(
                output_path, layout_report, browser_channel=layout_browser_channel,
            )
            if fix_count > 0:
                # Re-run QA to see if CSS fixes resolved the issues
                report_path_after = layout_report_path(output_path, attempt)
                qa_passed_after, layout_report_after = run_layout_qa(
                    output_path,
                    report_path_after,
                    browser_channel=layout_browser_channel,
                )
                if qa_passed_after:
                    print(f"  ✅ CSS 热修复解决全部问题 ({fix_count} 处修复)")
                    break
                failed_after = failing_slide_indices(layout_report_after)
                if len(failed_after) < len(failed):
                    print(f"  📐 CSS 热修复减少了失败页: {len(failed)} → {len(failed_after)}，继续 LLM 修复剩余")
                    layout_report = layout_report_after
                    failed = failed_after
        except Exception as e:
            print(f"  ⚠️ CSS 热修复异常: {type(e).__name__}: {str(e)[:80]}")

        # Phase 2: Single-slide LLM repair (cheaper than batch repair)
        try:
            repaired = repair_single_slides(
                segments=segments,
                batch_slide_lists=batch_slide_lists,
                all_custom_css=all_custom_css,
                report=layout_report,
                title=title,
                lesson_description=lesson_description,
                theme_prompt=theme_prompt,
                layout_prompt=layout_prompt,
                model=model,
                max_tokens=max_tokens,
            )
        except Exception as e:
            print(f"  ⚠️ 单 slide 修复异常: {type(e).__name__}: {str(e)[:120]}")
            repaired = False

        if not repaired:
            # Phase 3: Batch LLM repair (fallback — most expensive)
            try:
                repaired = replace_failed_batches(
                    batches=batches,
                    batch_slide_lists=batch_slide_lists,
                    all_custom_css=all_custom_css,
                    report=layout_report,
                    title=title,
                    lesson_description=lesson_description,
                    theme_prompt=theme_prompt,
                    layout_prompt=layout_prompt,
                    model=model,
                    max_tokens=max_tokens,
                )
            except Exception as e:
                print(f"  ⚠️ Batch 修复异常: {type(e).__name__}: {str(e)[:120]}")
                repaired = False
        if not repaired:
            print("  ⚠️ 没有可接受的修复输出，停止布局回流")
            break

        print(f"\n🔁 写入布局修复结果 (attempt {attempt + 1})...")
        final_html = write_current_html()

    # 8. 结构校验
    result = validate_output(
        final_html,
        storyboard["total_slides"],
        theme=theme,
        expected_durations_ms=durations_ms,
    )

    print("\n" + "=" * 60)
    if result["all_pass"]:
        print("🎉 Pipeline 执行成功！所有校验通过。")
    else:
        print("⚠️ Pipeline 执行完成，但部分校验未通过，请检查。")
    print("=" * 60)

    return output_path
