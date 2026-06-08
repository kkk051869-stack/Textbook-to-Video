"""theme 动画风格相关：duration_scale CSS 变量注入 + 默认转场推断。"""

from textbook2video.animation_gen import infer_transitions
from textbook2video.themes import (
    list_themes,
    load_theme,
    theme_default_transition,
    theme_to_css_vars,
)


def test_all_themes_have_animation_block():
    """3 个内置主题都应携带 animation 配置（Phase 1）。"""
    for tid in list_themes():
        t = load_theme(tid)
        assert "animation" in t, f"{tid} 缺少 animation 块"
        assert "duration_scale" in t["animation"]
        assert "transition_default" in t["animation"]


def test_theme_to_css_vars_includes_duration_scale():
    """theme_to_css_vars 应注入 --anim-duration-scale。"""
    css = theme_to_css_vars(load_theme("bright"))
    assert "--anim-duration-scale: 0.85" in css


def test_theme_default_transition_returns_per_theme():
    """每个主题各自的默认转场。"""
    assert theme_default_transition(load_theme("bright")) == "zoom"
    assert theme_default_transition(load_theme("dark-blue-academic")) == "dissolve"
    assert theme_default_transition(load_theme("3b1b-math")) == "push-left"


def test_theme_default_transition_fallback():
    """主题没 animation 块时回退到 push-left。"""
    assert theme_default_transition({}) == "push-left"


def test_infer_transitions_uses_theme_default_for_unknown_visual_type():
    """visual_type 未命中 TRANSITION_RULES 时，应用 theme 默认转场。"""
    segs = [
        {"id": 1, "visual_type": "title"},        # → zoom（TRANSITION_RULES 命中）
        {"id": 2, "visual_type": "unknown_xyz"},  # → 落到 default
        {"id": 3, "visual_type": "process"},      # → push-left（TRANSITION_RULES 命中）
    ]
    out = infer_transitions(segs, default="dissolve")
    assert out == ["zoom", "dissolve", "push-left"]


def test_infer_transitions_default_falls_back_to_push_left():
    """不传 default 时默认 push-left（向后兼容）。"""
    segs = [{"id": 1, "visual_type": "unknown"}]
    assert infer_transitions(segs) == ["push-left"]
