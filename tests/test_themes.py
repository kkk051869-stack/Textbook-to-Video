"""theme 动画风格相关：duration_scale CSS 变量注入 + 默认转场推断
+ Phase 2：easing 曲线、粒子密度、stagger 步长。"""

from textbook2video.animation_gen import infer_transitions
from textbook2video.themes import (
    list_themes,
    load_theme,
    theme_default_transition,
    theme_to_css_vars,
    theme_to_particle_config,
)


def test_all_themes_have_animation_block():
    """3 个内置主题都应携带 animation 配置（Phase 1）。"""
    for tid in list_themes():
        t = load_theme(tid)
        assert "animation" in t, f"{tid} 缺少 animation 块"
        assert "duration_scale" in t["animation"]
        assert "transition_style" in t["animation"]


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


def test_infer_transitions_style_overrides_all_pages():
    """传 style 参数时所有页一律用它（覆盖 visual_type 推断），这是主题统一转场签名。"""
    segs = [
        {"id": 1, "visual_type": "title"},
        {"id": 2, "visual_type": "comparison"},
        {"id": 3, "visual_type": "process"},
    ]
    assert infer_transitions(segs, style="dissolve") == ["dissolve", "dissolve", "dissolve"]


def test_infer_transitions_no_style_uses_visual_type_rules():
    """不传 style 时按 TRANSITION_RULES 推断。"""
    segs = [
        {"id": 1, "visual_type": "title"},        # → zoom
        {"id": 2, "visual_type": "unknown_xyz"},  # → default
        {"id": 3, "visual_type": "process"},      # → push-left
    ]
    out = infer_transitions(segs, default="dissolve")
    assert out == ["zoom", "dissolve", "push-left"]


def test_infer_transitions_default_falls_back_to_push_left():
    """不传 default 时默认 push-left（向后兼容）。"""
    segs = [{"id": 1, "visual_type": "unknown"}]
    assert infer_transitions(segs) == ["push-left"]


# ===== Phase 2 =====


def test_theme_to_css_vars_injects_per_theme_easing():
    """三个主题应各自注入 --ease-smooth/bounce/anticipate/arc，且至少一条值不同。"""
    css_b = theme_to_css_vars(load_theme("bright"))
    css_a = theme_to_css_vars(load_theme("dark-blue-academic"))
    for v in ("--ease-smooth", "--ease-bounce", "--ease-anticipate", "--ease-arc"):
        assert v in css_b and v in css_a, f"{v} 未注入"
    # bright 用过冲曲线，academic 用 sine 平滑——bounce 行必然不同
    bright_bounce = [ln for ln in css_b.splitlines() if "--ease-bounce" in ln][0]
    academic_bounce = [ln for ln in css_a.splitlines() if "--ease-bounce" in ln][0]
    assert bright_bounce != academic_bounce


def test_theme_to_css_vars_injects_stagger_step():
    """各主题 --stagger-step 应反映 stagger_step_ms 配置。"""
    css = theme_to_css_vars(load_theme("bright"))
    assert "--stagger-step: 80ms" in css
    css = theme_to_css_vars(load_theme("dark-blue-academic"))
    assert "--stagger-step: 130ms" in css


def test_theme_particle_density_scale_applies():
    """particle_density_scale 应缩放 effects.particle_count。"""
    bright = load_theme("bright")
    base = bright["effects"]["particle_count"]
    expected = max(0, round(base * 1.2))
    assert theme_to_particle_config(bright)["count"] == expected

    academic = load_theme("dark-blue-academic")
    base_a = academic["effects"]["particle_count"]
    expected_a = max(0, round(base_a * 0.7))
    assert theme_to_particle_config(academic)["count"] == expected_a


def test_theme_particle_density_scale_default_is_one():
    """缺 animation 块时 density_scale 默认 1.0（向后兼容）。"""
    fake = {"effects": {
        "particles": True, "particle_count": 50,
        "particle_connect_dist": 100, "particle_colors": ["#fff"],
    }}
    assert theme_to_particle_config(fake)["count"] == 50


# ===== Phase 3：关键帧主题化 + 卡片视觉强化 =====


def test_theme_keyframes_mapping_injected_as_css_vars():
    """academic 主题的 keyframes 映射应注入为一组 --kf-* CSS 变量。"""
    css = theme_to_css_vars(load_theme("dark-blue-academic"))
    assert "--kf-up: gentleSlideUp" in css
    assert "--kf-card: gentleCardIn" in css
    assert "--kf-anticipate-up: gentleSlideUp" in css


def test_theme_keyframes_3b1b_uses_manim_series():
    """3b1b-math 主题应映射到 manim 系关键帧。"""
    css = theme_to_css_vars(load_theme("3b1b-math"))
    assert "--kf-up: manimSlideUp" in css
    assert "--kf-card: manimCardIn" in css


def test_theme_without_keyframes_block_uses_defaults():
    """bright 主题（未配 keyframes）不应注入任何 --kf-* 变量，让 base.css 默认生效。"""
    css = theme_to_css_vars(load_theme("bright"))
    assert "--kf-" not in css


def test_3b1b_card_visual_distinct():
    """3b1b 主题卡片应是直角/白细边/极薄阴影（数学课本极简风）。"""
    v = load_theme("3b1b-math")["visual"]
    assert v["border_radius"] == "4px"
    assert "0.25" in v["card_border"]  # 较实在的白细边
