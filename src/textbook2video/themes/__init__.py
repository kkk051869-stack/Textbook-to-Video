"""
Theme loader — 加载和管理动画风格主题。

Theme = 视觉参数 + 效果开关 + 动画配置 + Prompt 提示词。
每个 theme.json 定义一套完整的视觉风格，用于：
  1. 注入 CSS 变量到 base-template.html
  2. 控制 particle-canvas.js 的行为（开关/颜色/数量）
  3. 为 LLM Prompt 提供风格约束（prompt_hints）
  4. 控制 animation_gen.py 的校验逻辑

用法:
    from textbook2video.themes import load_theme
    theme = load_theme("bright")       # 按 theme_id 加载
    theme = load_theme()               # 默认加载 bright
"""

import json
from pathlib import Path
from typing import Any

_THEMES_DIR = Path(__file__).resolve().parent

# 可用主题注册表（theme_id → 文件名）
_REGISTRY: dict[str, str] = {
    "bright": "bright.json",
    "3b1b-math": "3b1b-math.json",
    "dark-blue-academic": "dark-blue-academic.json",
}

DEFAULT_THEME = "bright"


def list_themes() -> list[str]:
    """返回所有可用的 theme_id。"""
    return list(_REGISTRY.keys())


def load_theme(theme_id: str | None = None) -> dict[str, Any]:
    """加载主题配置。

    Args:
        theme_id: 主题 ID，None 则使用默认主题

    Returns:
        主题配置字典

    Raises:
        FileNotFoundError: 主题文件不存在
        ValueError: 未知主题 ID
    """
    tid = theme_id or DEFAULT_THEME

    if tid not in _REGISTRY:
        available = ", ".join(_REGISTRY.keys())
        raise ValueError(f"未知主题 '{tid}'，可用: {available}")

    filepath = _THEMES_DIR / _REGISTRY[tid]
    if not filepath.exists():
        raise FileNotFoundError(f"主题文件不存在: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        theme = json.load(f)

    # 校验必要字段
    _validate_theme(theme, tid)
    return theme


def theme_to_css_vars(theme: dict[str, Any]) -> str:
    """将主题的 visual 参数转换为 CSS :root 变量声明。

    用于注入到 base-template.html 的 <style> 中。

    Returns:
        CSS 文本，如 ":root { --primary: #4361ee; ... }"
    """
    v = theme["visual"]
    fallback = v.get("font_family", "sans-serif")
    lines = [
        f"    --primary: {v['primary']};",
        f"    --accent: {v['accent']};",
        f"    --secondary: {v['secondary']};",
        f"    --success: {v['success']};",
        f"    --orange: {v['orange']};",
        f"    --gold: {v['gold']};",
        f"    --bg-warm: {v['background']};",
        f"    --bg-dark: {v['background_dark']};",
        f"    --text: {v['text_color']};",
        f"    --text-dim: {v['text_dim']};",
        f"    --border: {v['border']};",
        f"    --card-bg: {v.get('card_bg', 'white')};",
        f"    --card-border: {v.get('card_border', 'transparent')};",
        f"    --card-shadow: {v.get('card_shadow', '0 4px 20px rgba(0,0,0,0.06)')};",
        f"    --glow-primary: {v['glow_primary']};",
        f"    --glow-accent: {v['glow_accent']};",
        f"    --glow-secondary: {v['glow_secondary']};",
        f"    --glow-success: {v['glow_success']};",
        f"    --noise-opacity: {v.get('noise_opacity', '0.03')};",
        f"    --transition-speed: {v['transition_speed']};",
        f"    --font-body: {v.get('font_body', fallback)};",
        f"    --font-heading: {v.get('font_heading', fallback)};",
        f"    --font-display: {v.get('font_display', v.get('font_heading', fallback))};",
        f"    --font-number: {v.get('font_number', fallback)};",
        f"    --font-label: {v.get('font_label', v.get('font_body', fallback))};",
    ]
    # 动画风格（Phase 1）：duration_scale 控制所有 .anim-* 时长的倍率
    anim = theme.get("animation", {})
    lines.append(
        f"    --anim-duration-scale: {anim.get('duration_scale', 1.0)};"
    )
    return ":root {\n" + "\n".join(lines) + "\n}"


def theme_default_transition(theme: dict[str, Any]) -> str:
    """主题指定的默认转场风格（visual_type 未命中 TRANSITION_RULES 时用）。

    取值见 slide-controller.js 的 TRANSITIONS：push-left / push-right / zoom / dissolve。
    """
    return theme.get("animation", {}).get("transition_default", "push-left")


def theme_to_particle_config(theme: dict[str, Any]) -> dict[str, Any]:
    """提取粒子系统配置参数。

    Returns:
        dict with: enabled, count, connect_dist, colors
    """
    fx = theme["effects"]
    return {
        "enabled": fx["particles"],
        "count": fx["particle_count"],
        "connect_dist": fx["particle_connect_dist"],
        "colors": fx["particle_colors"],
    }


def theme_prompt_section(theme: dict[str, Any]) -> str:
    """生成注入到 LLM Prompt 中的风格约束段落。

    Returns:
        Markdown 文本，可直接拼接到 prompt 模板中
    """
    hints = theme.get("prompt_hints", [])
    if not hints:
        return ""

    lines = [f"## 当前风格约束（{theme['name']}）", ""]
    for h in hints:
        lines.append(f"- {h}")
    return "\n".join(lines)


def theme_layout_mode(theme: dict[str, Any] | None = None) -> str:
    """返回主题的布局模式。

    Returns:
        "card"（默认）或 "fullscreen"
    """
    if not theme:
        return "card"
    layout = theme.get("layout")
    if isinstance(layout, dict):
        mode = layout.get("mode", "card")
    else:
        mode = "card"
    if mode not in ("card", "fullscreen"):
        raise ValueError(
            f"layout.mode 只接受 'card' 或 'fullscreen'，收到: {mode!r}"
        )
    return mode


def theme_layout_prompt_section(theme: dict[str, Any]) -> str:
    """根据布局模式返回 LLM prompt 中的布局指导段落。

    Returns:
        Markdown 文本，可直接拼接到 prompt 中
    """
    mode = theme_layout_mode(theme)
    if mode == "fullscreen":
        return (
            "## 布局模式：全屏（fullscreen）\n"
            "\n"
            "- 不要把每页 slide 的全部内容都包在 `.content-card` 里；"
            "使用全屏 flex / grid / absolute 布局占满整个 slide。\n"
            "- `.content-card` 仅用于局部面板（如侧边信息卡片、弹窗式容器），"
            "不作为主要居中容器。\n"
            "- 标题、大图、公式等主内容直接放在 `.slide` 内，利用全宽全高空间。\n"
            "- 需要分区时用自定义 flex/grid 容器，不要依赖 `.content-card` 的"
            "白底+圆角+阴影样式。\n"
            "- 顶层内容容器必须设置 `width:100%`，需要居中时在 `.slide` 或主容器上"
            "显式设置 `align-items:center; justify-content:center; text-align:center`。\n"
            "- `.slide` 已经占满视口，不要在子容器上使用 `height:100vh`；"
            "改用 `height:100%`、`min-height:0`、`flex:1` 或 `max-height:calc(100vh - 160px)`。\n"
            "- 大型 SVG/图表区域高度控制在 `45vh` 到 `60vh`，并给标题、正文、总结区"
            "预留空间，避免元素重叠或被裁切。\n"
        )
    # card (default)
    return (
        "## 布局模式：卡片（card）\n"
        "\n"
        "- 使用 `.content-card` 作为主要居中容器，包裹每页 slide 的内容。\n"
        "- `.content-card` 提供白底、圆角、阴影、居中效果的视觉框架。\n"
    )


def _validate_theme(theme: dict[str, Any], theme_id: str) -> None:
    """校验主题配置的必要字段。"""
    required_sections = ["visual", "effects", "animation"]
    for section in required_sections:
        if section not in theme:
            raise ValueError(f"主题 '{theme_id}' 缺少 '{section}' 字段")

    v = theme["visual"]
    required_visual = ["background", "text_color", "primary", "font_family"]
    for field in required_visual:
        if field not in v:
            raise ValueError(f"主题 '{theme_id}' visual 缺少 '{field}' 字段")

    # 校验 layout.mode（如果存在）
    layout = theme.get("layout")
    if isinstance(layout, dict) and "mode" in layout:
        mode = layout["mode"]
        if mode not in ("card", "fullscreen"):
            raise ValueError(
                f"主题 '{theme_id}' layout.mode 只接受 'card' 或 'fullscreen'，"
                f"收到: {mode!r}"
            )
