"""
讲稿生成器：教材文本 → 讲稿分段文本

用法：
  from textbook2video.pipeline.scriptwriter import generate_script
  segments = generate_script("教材文本")
"""

from textbook2video.llm.client import chat_with_system, load_prompt


def generate_script(lesson_text: str, model: str | None = None) -> list[str]:
    """
    根据教材文本生成讲稿分段。

    Args:
        lesson_text: 教材提取的课程文本
        model: 可选，指定模型名

    Returns:
        讲稿分段列表，每段对应一页动画
    """
    prompt_template = load_prompt("script.md")
    prompt = prompt_template.replace("{lesson_text}", lesson_text)

    result = chat_with_system(
        user_content=prompt,
        system_prompt="你是一位信息科技老师，将教材内容转化为生动的课堂讲稿。",
        model=model,
        temperature=0.7,
        max_tokens=4096,
    )

    return _parse_script(result)


def _parse_script(raw: str) -> list[str]:
    """
    解析 LLM 返回的讲稿文本，拆分为段落列表。

    支持两种格式：
    1. "第1段：（8-12秒）\n内容..." 格式
    2. 纯段落格式（按空行分隔）
    """
    lines = raw.strip().split("\n")

    segments = []
    current = []

    for line in lines:
        # 检测 "第N段：（x-y秒）" 或 "第N段：" 开头
        stripped = line.strip()
        if stripped and (
            "第" in stripped
            and "段" in stripped
            and "：" in stripped
        ):
            # 保存前一段
            if current:
                segments.append("\n".join(current).strip())
                current = []
            # 这一行是标题行，跳过，内容从下一行开始
            continue

        # 空行 = 段落分隔
        if stripped == "":
            if current:
                segments.append("\n".join(current).strip())
                current = []
        else:
            current.append(stripped)

    # 最后一段
    if current:
        segments.append("\n".join(current).strip())

    # 如果没解析出段落（纯文本），按空行分割
    if not segments:
        paragraphs = [p.strip() for p in raw.strip().split("\n\n") if p.strip()]
        segments = paragraphs

    # 过滤纯分隔符段落（"---"、"———"、"***" 等）
    segments = [
        s for s in segments
        if s.strip("—-\t *\n\r") and s.strip() != "---"
    ]

    return segments