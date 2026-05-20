"""一次性生成完整 HTML

将 storyboard JSON 送给 LLM，一次性生成完整的教学动画 HTML 页面。
LLM 自由发挥每页设计，效果最好。

公共 API:
    generate_full(json_path) -> Path  — 完整流水线：JSON → HTML
"""

import json
import re
import time
from pathlib import Path

from textbook2video.llm.client import chat
from textbook2video.pipeline.config import DEFAULT_OUTPUT_DIR

# === 包内资源路径 ===
_PACKAGE_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = _PACKAGE_DIR / "llm" / "prompts"

# === 默认配置 ===
MODEL = "ecnu-max"
MAX_TOKENS = 16000
TEMPERATURE = 0.7


def _parse_storyboard(json_path: str | Path) -> dict:
    """读取 storyboard JSON，返回解析后的数据。"""
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


def _build_scenes_description(segments: list) -> str:
    """将 segments 转换为 scenes_description 文本。"""
    scenes = []
    for seg in segments:
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

        scene = (
            f"第{seg['id']}页（{seg['visual_type']}，音频{seg['audio_duration_sec']}秒）:\n"
            f"  内容: {'; '.join(elements_desc)}\n"
            f"  旁白: {seg['narration'][:150]}..."
        )
        scenes.append(scene)

    return "\n\n".join(scenes)


def _load_prompt_template() -> str:
    """加载 animation_direct.md 中的 prompt 模板。"""
    prompt_raw = (PROMPTS_DIR / "animation_direct.md").read_text(encoding="utf-8")
    lines = prompt_raw.split("\n")
    # 找第一个 ``` 开头的行（模板开始）到最后一个 ``` 行（模板结束）
    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "```" and start_idx is None:
            start_idx = i + 1
        elif line.strip() == "```" and start_idx is not None:
            end_idx = i
    if start_idx is not None and end_idx is not None:
        return "\n".join(lines[start_idx:end_idx])
    return prompt_raw


def generate_full(
    json_path: str | Path,
    *,
    output_dir: Path | None = None,
    model: str = MODEL,
) -> Path:
    """一次性生成完整 HTML：storyboard JSON → LLM 直接输出完整页面。

    效果最好（LLM 自由发挥每页设计），但受限于单次 LLM 输出长度。
    适合 8-12 页的课程。

    Args:
        json_path: storyboard JSON 文件路径
        output_dir: 输出目录，默认使用 config.DEFAULT_OUTPUT_DIR
        model: LLM 模型名（建议 ecnu-max，输出更长）

    Returns:
        生成的 HTML 文件路径
    """
    print("=" * 60)
    print("🎬 一次性生成 Pipeline（full mode）")
    print("=" * 60)

    # 1. 解析 JSON
    storyboard = _parse_storyboard(json_path)
    segments = storyboard["segments"]
    title = storyboard["title"]

    # 2. 加载 prompt 模板
    print("\n📂 加载 prompt 模板...")
    prompt_template = _load_prompt_template()
    print(f"  Prompt 模板: {len(prompt_template)} 字符")

    # 3. 构建 scenes_description
    scenes_description = _build_scenes_description(segments)
    topic_description = segments[0]["narration"][:200] if segments else ""

    # 4. 填充 prompt
    prompt = prompt_template.replace("{topic_title}", title)
    prompt = prompt.replace("{topic_description}", topic_description)
    prompt = prompt.replace("{scenes_description}", scenes_description)
    print(f"  Prompt: {len(prompt)} 字符")

    # 5. 调用 LLM
    print(f"\n🤖 正在调用 {model} 生成完整 HTML...")
    start = time.time()

    llm_output = chat(
        [{"role": "user", "content": prompt}],
        model=model,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
    )

    elapsed = time.time() - start
    print(f"  ✅ 生成完成: {elapsed:.1f}s, {len(llm_output)} 字符")

    # 6. 清理输出
    html_text = llm_output.strip()
    if html_text.startswith("```"):
        lines = html_text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        html_text = "\n".join(lines)
    doctype_pos = html_text.find("<!DOCTYPE")
    if doctype_pos > 0:
        html_text = html_text[doctype_pos:]

    # 7. 写入输出
    out_dir = output_dir or DEFAULT_OUTPUT_DIR
    out_dir.mkdir(exist_ok=True)
    json_stem = Path(json_path).stem.replace("_storyboard", "")
    output_path = out_dir / f"{json_stem}-full.html"
    output_path.write_text(html_text, encoding="utf-8")
    print(f"💾 保存到: {output_path}")
    print(f"   大小: {len(html_text)} 字符")

    # 8. 简单校验
    slide_count = html_text.count('class="slide"') + html_text.count('class="slide active"')
    print(f"   页数: {slide_count}")
    print("\n" + "=" * 60)
    if slide_count > 0:
        print("🎉 生成完成！")
    else:
        print("⚠️ 未检测到 slide，请检查输出。")
    print("=" * 60)

    return output_path
