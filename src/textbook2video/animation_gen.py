"""动画生成 Pipeline

两种模式：
    generate_full(json_path)  -> Path  — 一次性生成完整 HTML（效果好，推荐）
    generate(json_path)       -> Path  — 分批生成+合并（长课程时使用）
"""

import json
import re
import time
from pathlib import Path

from textbook2video.llm.client import chat
from textbook2video.pipeline.config import DEFAULT_OUTPUT_DIR

# === 包内资源路径 ===
_PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = _PACKAGE_DIR / "templates"
PROMPTS_DIR = _PACKAGE_DIR / "llm" / "prompts"
COMPONENTS_DIR = _PACKAGE_DIR / "components"

# === 默认配置 ===
BATCH_SIZE = 4
MODEL = "ecnu-plus"
MAX_TOKENS = 16000
TEMPERATURE = 0.7

# 组件查找表: visual_type → 组件文件名
COMPONENT_REGISTRY = {
    "network": "network.html",
    "data-chart": "chart_line.html",
    "chart-line": "chart_line.html",
    "process": "flow.html",
    "comparison": "comparison.html",
}


# ============================================================
# Step 1: 解析 JSON
# ============================================================
def parse_storyboard(json_path: str | Path) -> dict:
    """读取 storyboard JSON，返回解析后的数据。

    Raises:
        FileNotFoundError: 文件不存在
        ValueError: JSON 格式错误或缺少必要字段
    """
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {json_path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "segments" not in data:
        raise ValueError("JSON 缺少 'segments' 字段")

    title = data.get("lesson_title", "教学动画")
    segments = data["segments"]
    total = data.get("metadata", {}).get("total_slides", len(segments))

    print(f"📖 课程: {title}")
    print(f"📄 共 {len(segments)} 个 segments（元数据标注 {total} 页）")

    return {"title": title, "segments": segments, "total_slides": total}


# ============================================================
# Step 2: 分批
# ============================================================
def split_batches(segments: list, batch_size: int = BATCH_SIZE) -> list:
    """将 segments 分成若干批，每批最多 batch_size 个。"""
    batches = []
    for i in range(0, len(segments), batch_size):
        batches.append(segments[i : i + batch_size])

    print(f"📦 分为 {len(batches)} 批: ", end="")
    print(", ".join(f"batch{b+1}({len(batch)}页)" for b, batch in enumerate(batches)))
    return batches


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


# ============================================================
# Step 4: 构建 scenes_description
# ============================================================
def build_scenes_description(batch: list) -> str:
    """将一批 segments 转换为 scenes_description 文本。"""
    scenes = []
    for seg in batch:
        elements_desc = []
        for elem in seg.get("elements", []):
            etype = elem.get("type", "")
            if etype == "heading":
                elements_desc.append(f"标题: {elem['text']}")
            elif etype == "subheading":
                elements_desc.append(f"副标题: {elem['text']}")
            elif etype == "text":
                elements_desc.append(f"说明文字: {elem['text']}")
            elif etype == "icon_group":
                elements_desc.append(f"图标组: {', '.join(elem['items'])}")
            elif etype == "image":
                elements_desc.append(f"插图: {elem['description']}")
            elif etype == "chart_line":
                elements_desc.append(f"折线图: {elem['description']}")
            elif etype == "comparison_panel":
                items = [f"{i['title']}({i['content']})" for i in elem["items"]]
                elements_desc.append(f"对比面板: {' vs '.join(items)}")
            elif etype == "flow_step":
                elements_desc.append(f"流程步骤: {' → '.join(elem['steps'])}")
            elif etype == "activity_step":
                elements_desc.append(f"活动步骤: {' → '.join(elem['steps'])}")
            else:
                elements_desc.append(f"{etype}: {elem}")

        anims_desc = []
        for a in seg.get("animations", []):
            anims_desc.append(f"{a['target']}: {a['effect']}")

        scene = (
            f"第{seg['id']}页（{seg['visual_type']}，音频{seg['audio_duration_sec']}秒）:\n"
            f"  内容: {'; '.join(elements_desc)}\n"
            f"  动画: {', '.join(anims_desc)}\n"
            f"  旁白: {seg['narration'][:80]}..."
        )
        scenes.append(scene)

    return "\n\n".join(scenes)


# ============================================================
# Step 5: 构建 prompt
# ============================================================
def build_batch_prompt(
    batch: list,
    prompt_template: str,
    lesson_title: str,
    lesson_description: str,
) -> str:
    """为一批 segments 构建 LLM prompt。"""
    scenes = build_scenes_description(batch)

    # 收集组件代码
    component_codes = []
    for seg in batch:
        code = load_component(seg.get("visual_type", ""))
        if code and code not in component_codes:
            component_codes.append(code)
    component_section = "\n\n".join(component_codes) if component_codes else "（无）"

    # 填充 prompt 模板
    filled = prompt_template.replace("{LESSON_TITLE}", lesson_title)
    filled = filled.replace("{LESSON_DESCRIPTION}", lesson_description)
    filled = filled.replace("{SCENES_DESCRIPTION}", scenes)
    filled = filled.replace("{COMPONENT_CODE}", component_section)

    return filled


# ============================================================
# Step 6: LLM 生成
# ============================================================
def generate_batch(prompt: str, *, model: str = MODEL) -> str:
    """调用 LLM 生成一批 slide。"""
    print(f"  🤖 正在调用 {model} 生成...")
    start = time.time()

    result = chat(
        [{"role": "user", "content": prompt}],
        model=model,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
    )

    elapsed = time.time() - start
    print(f"  ✅ 生成完成: {elapsed:.1f}s, {len(result)} 字符")
    return result


# ============================================================
# Step 7: 解析输出
# ============================================================
def extract_slides(llm_output: str) -> tuple:
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
        print("  ⚠️ 未能提取到 slide div，保存原始输出供调试")
        return text, custom_css

    print(f"  📋 提取到 {len(slides)} 个 slide")
    return "\n\n".join(slides), custom_css


def _extract_slide_divs(html: str) -> list:
    """从 HTML 中提取所有 slide div 块，使用栈匹配嵌套。"""
    slides = []
    pattern = re.compile(
        r'<div\s[^>]*class="slide[^"]*"[^>]*>',
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


# ============================================================
# Step 8: 合并
# ============================================================
def merge_html(
    all_slides: list,
    custom_css_list: list,
    shell_template: str,
    css_framework: str,
    js_controller: str,
    js_particles: str,
    durations_ms: list,
    title: str,
) -> str:
    """合并所有组件为最终 HTML。"""
    slides_html = "\n\n".join(all_slides)

    # 清理 LLM 可能输出的多余结构
    slides_html = slides_html.replace('<div class="slide-container">', '')
    slides_html = slides_html.replace("</div><!-- /slide-container -->", "")
    slides_html = slides_html.replace("</div><!-- slide-container -->", "")

    # 先移除所有 slide active（LLM 可能自己加了），再给第一个加
    slides_html = slides_html.replace('class="slide active"', 'class="slide"')
    slides_html = slides_html.replace('class="slide"', 'class="slide active"', 1)

    # 合并自定义 CSS（去重）
    seen_css = set()
    unique_css = []
    for css in custom_css_list:
        css_stripped = css.strip()
        if css_stripped and css_stripped not in seen_css:
            seen_css.add(css_stripped)
            unique_css.append(css_stripped)
    custom_css_merged = "\n\n".join(unique_css)

    # 填充 shell 模板
    result = shell_template.replace("{{LESSON_TITLE}}", title)
    result = result.replace("{{CSS_FRAMEWORK}}", css_framework)
    result = result.replace("{{CUSTOM_CSS}}", custom_css_merged)
    result = result.replace("{{SLIDES}}", slides_html)
    result = result.replace("{{JS_CONTROLLER}}", js_controller)
    result = result.replace("{{JS_PARTICLES}}", js_particles)
    result = result.replace("{{SLIDE_DURATIONS}}", str(durations_ms))

    return result


# ============================================================
# Step 9: 校验
# ============================================================
def validate_output(html: str, expected_slides: int) -> dict:
    """自动校验输出 HTML 质量。"""
    checks = {
        "slide数量": html.count('class="slide"') + html.count('class="slide active"') >= expected_slides,
        "SlideController": "SlideController" in html,
        "particleCanvas": "particleCanvas" in html,
        "SVG噪点": "feTurbulence" in html,
        "无导航按钮": "nextBtn" not in html and "prevBtn" not in html,
        "纯色背景": "#fef9f2" in html,
        ".anim系统": ".anim" in html,
        "SVG图形(≥8个svg)": html.count("<svg") >= 8,
    }

    print("\n🔍 校验结果:")
    all_pass = True
    for name, ok in checks.items():
        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"  [{status}] {name}")
        if not ok:
            all_pass = False

    slide_count = html.count('class="slide"') + html.count('class="slide active"')
    print(f"\n  总计: {slide_count} 页 slide, {len(html)} 字符")

    return {"all_pass": all_pass, "checks": checks, "slide_count": slide_count}


# ============================================================
# 公共 API: generate()
# ============================================================
def generate(
    json_path: str | Path,
    *,
    output_dir: Path | None = None,
    model: str = MODEL,
    batch_size: int = BATCH_SIZE,
) -> Path:
    """完整流水线：storyboard JSON → 单文件 HTML。

    Args:
        json_path: storyboard JSON 文件路径
        output_dir: 输出目录，默认使用 config.DEFAULT_OUTPUT_DIR
        model: LLM 模型名
        batch_size: 每批生成的 slide 数量

    Returns:
        生成的 HTML 文件路径

    Raises:
        FileNotFoundError: JSON 文件不存在
        ValueError: JSON 格式错误
    """
    print("=" * 60)
    print("🎬 分批生成+合并 Pipeline")
    print("=" * 60)

    # 1. 解析 JSON
    storyboard = parse_storyboard(json_path)
    segments = storyboard["segments"]
    title = storyboard["title"]

    # 2. 分批
    batches = split_batches(segments, batch_size)

    # 3. 加载模板
    print("\n📂 加载模板...")
    shell_template = (TEMPLATES_DIR / "shell.html").read_text(encoding="utf-8")
    css_framework = (TEMPLATES_DIR / "base.css").read_text(encoding="utf-8")
    js_controller = (TEMPLATES_DIR / "slide-controller.js").read_text(encoding="utf-8")
    js_particles = (TEMPLATES_DIR / "particle-canvas.js").read_text(encoding="utf-8")

    # 加载 prompt 模板（提取 ## Prompt 模板 下的代码块）
    prompt_raw = (PROMPTS_DIR / "slide_content.md").read_text(encoding="utf-8")
    prompt_match = re.search(
        r"## Prompt 模板\s*\n```\s*\n(.*?)```", prompt_raw, re.DOTALL
    )
    if prompt_match:
        prompt_template = prompt_match.group(1).strip()
    else:
        prompt_template = prompt_raw
    print(f"  Prompt 模板: {len(prompt_template)} 字符")

    # 构建课程描述（从第一段旁白提取）
    lesson_description = segments[0]["narration"][:100] if segments else ""

    # 4. 分批生成
    print(f"\n🚀 开始生成（{len(batches)} 批，模型: {model}）")
    all_slides = []
    all_custom_css = []

    for batch_idx, batch in enumerate(batches):
        batch_num = batch_idx + 1
        print(f"\n--- Batch {batch_num}/{len(batches)} (页面 {batch[0]['id']}-{batch[-1]['id']}) ---")

        prompt = build_batch_prompt(batch, prompt_template, title, lesson_description)
        print(f"  Prompt: {len(prompt)} 字符")

        llm_output = generate_batch(prompt, model=model)

        slides_html, custom_css = extract_slides(llm_output)
        all_slides.append(slides_html)
        if custom_css:
            all_custom_css.append(custom_css)

    # 5. 提取 durations
    durations_ms = [int(seg["audio_duration_sec"] * 1000) for seg in segments]

    # 6. 合并
    print("\n🔗 合并所有批次...")
    final_html = merge_html(
        all_slides=all_slides,
        custom_css_list=all_custom_css,
        shell_template=shell_template,
        css_framework=css_framework,
        js_controller=js_controller,
        js_particles=js_particles,
        durations_ms=durations_ms,
        title=title,
    )

    # 7. 写入输出
    out_dir = output_dir or DEFAULT_OUTPUT_DIR
    out_dir.mkdir(exist_ok=True)
    json_stem = Path(json_path).stem.replace("_storyboard", "")
    output_path = out_dir / f"{json_stem}-pipeline.html"
    output_path.write_text(final_html, encoding="utf-8")
    print(f"💾 保存到: {output_path}")
    print(f"   大小: {len(final_html)} 字符")

    # 8. 校验
    result = validate_output(final_html, storyboard["total_slides"])

    print("\n" + "=" * 60)
    if result["all_pass"]:
        print("🎉 Pipeline 执行成功！所有校验通过。")
    else:
        print("⚠️ Pipeline 执行完成，但部分校验未通过，请检查。")
    print("=" * 60)

    return output_path
