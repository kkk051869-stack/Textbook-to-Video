"""Offline-safe conversion of common LaTeX delimiters to browser MathML."""

from __future__ import annotations

import html
import re
from typing import Any

from latex2mathml.converter import convert


_MATH_RE = re.compile(
    r"(?P<display>\$\$(?P<display_dollar>.+?)\$\$|\\\[(?P<display_bracket>.+?)\\\])"
    r"|(?P<inline>\\\((?P<inline_bracket>.+?)\\\)|\$(?P<inline_dollar>[^$\n]+?)\$)",
    flags=re.DOTALL,
)
_HTML_TOKEN_RE = re.compile(r"(<[^>]+>)")


def html_with_math(value: Any) -> str:
    """Escape prose while converting supported LaTeX delimiters to MathML.

    The output contains no runtime network dependency, so Playwright recording
    sees the same equations as a browser preview. Invalid LaTeX remains
    escaped source text instead of breaking the whole slide.
    """
    text = str(value or "")
    parts: list[str] = []
    cursor = 0
    for match in _MATH_RE.finditer(text):
        parts.append(html.escape(text[cursor:match.start()]).replace("\n", "<br>"))
        is_display = bool(match.group("display"))
        expression = (
            match.group("display_dollar")
            or match.group("display_bracket")
            or match.group("inline_bracket")
            or match.group("inline_dollar")
            or ""
        ).strip()
        try:
            mathml = convert(expression, display="block" if is_display else "inline")
        except Exception:  # latex2mathml has several parser-specific errors
            parts.append(html.escape(match.group(0)))
        else:
            tag = "div" if is_display else "span"
            kind = "display" if is_display else "inline"
            parts.append(f'<{tag} class="t2v-math t2v-math-{kind}">{mathml}</{tag}>')
        cursor = match.end()
    parts.append(html.escape(text[cursor:]).replace("\n", "<br>"))
    return "".join(parts)


def replace_latex_in_html_text(html_source: str) -> str:
    """Convert LaTeX in already-generated HTML text nodes only.

    The LLM HTML fallback bypasses the deterministic element renderer.  This
    keeps its attributes, SVG and scripts untouched while normalising formula
    text before it is inserted into the final page shell.
    """
    pieces = _HTML_TOKEN_RE.split(html_source)
    output: list[str] = []
    skip_tag: str | None = None
    for piece in pieces:
        if piece.startswith("<") and piece.endswith(">"):
            tag_match = re.match(r"<\s*/?\s*([a-zA-Z0-9]+)", piece)
            tag_name = tag_match.group(1).lower() if tag_match else ""
            if tag_name in {"script", "style"}:
                skip_tag = None if piece.lstrip().startswith("</") else tag_name
            output.append(piece)
            continue
        if skip_tag or not any(marker in piece for marker in ("$", r"\(", r"\[")):
            output.append(piece)
        else:
            output.append(html_with_math(html.unescape(piece)))
    return "".join(output)


__all__ = ["html_with_math", "replace_latex_in_html_text"]
