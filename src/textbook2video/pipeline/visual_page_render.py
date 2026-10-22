"""Use the production page renderer and shell for visual-tool page previews."""

from __future__ import annotations

from pathlib import Path


def course_page_html(segment: dict, images: dict[str, str], *, theme: str) -> str:
    from textbook2video.animation_gen import inject_generated_images, merge_html
    from textbook2video.template_renderer import render_slide
    from textbook2video.themes import load_theme

    template_dir = Path(__file__).resolve().parents[1] / "templates"
    selected_theme = load_theme(theme)
    rendered = render_slide(segment, 0, set(images), selected_theme.get("preferred_variants"))
    if rendered is None:
        raise ValueError("course page is not supported by the deterministic renderer")
    uris = {key: Path(path).resolve().as_uri() for key, path in images.items()}
    rendered = inject_generated_images([rendered], [segment], uris)[0]
    return merge_html(
        [rendered],
        [".anim{opacity:1!important;transform:none!important;animation:none!important}"],
        (template_dir / "base-template.html").read_text(encoding="utf-8"),
        (template_dir / "base.css").read_text(encoding="utf-8"),
        (template_dir / "slide-controller.js").read_text(encoding="utf-8"),
        "",
        [int(segment.get("audio_duration_sec", 10) * 1000)],
        "课程视觉开发预览",
        theme=selected_theme,
    )
