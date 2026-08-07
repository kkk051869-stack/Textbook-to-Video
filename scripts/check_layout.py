"""Browser geometry QA for generated slide HTML.

This checker does not use image recognition. It opens a generated HTML file in
Playwright, navigates through SlideController pages, and validates computed
layout geometry: active slide position, visible content, safe-area bounds,
vertical centering, overlap, and risky inline layout styles.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright


DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_WAIT_MS = 2200


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check generated slide HTML layout geometry.")
    parser.add_argument("html", type=Path, help="Generated HTML file to inspect")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH, help="Viewport width")
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT, help="Viewport height")
    parser.add_argument("--wait-ms", type=int, default=DEFAULT_WAIT_MS, help="Wait after each slide")
    parser.add_argument("--json", type=Path, default=None, help="Optional JSON report path")
    parser.add_argument(
        "--browser-channel",
        default=None,
        help="Optional Chromium channel, e.g. msedge or chrome",
    )
    return parser.parse_args()


def read_static_risks(html_path: Path) -> list[dict[str, Any]]:
    html = html_path.read_text(encoding="utf-8")
    risks: list[dict[str, Any]] = []

    slide_tag_pattern = re.compile(r'<div\s+[^>]*class="slide(?: active)?"[^>]*>', re.I)
    for match_index, match in enumerate(slide_tag_pattern.finditer(html), start=1):
        tag = match.group(0)
        style_match = re.search(r'style="([^"]*)"', tag, re.I)
        if not style_match:
            continue
        style = style_match.group(1).lower().replace(" ", "")
        if "position:relative" in style or "position:absolute" in style or "position:fixed" in style:
            risks.append(
                {
                    "slide": match_index,
                    "severity": "warn",
                    "type": "slide_inline_position",
                    "message": "Slide tag sets inline position; framework should own slide positioning.",
                    "tag": tag[:240],
                }
            )
        if "height:100vh" in style:
            risks.append(
                {
                    "slide": match_index,
                    "severity": "warn",
                    "type": "slide_inline_100vh",
                    "message": "Slide tag sets height:100vh; framework already controls slide height.",
                    "tag": tag[:240],
                }
            )

    if "height:100vh" in html.lower().replace(" ", ""):
        risks.append(
            {
                "slide": None,
                "severity": "warn",
                "type": "child_height_100vh_present",
                "message": "HTML contains height:100vh; child elements may overflow fullscreen slides.",
            }
        )

    svg_block_pattern = re.compile(r"<svg\b[\s\S]*?</svg>", re.I)
    svg_anim_pattern = re.compile(
        r"<(g|circle|rect|path|text|line|ellipse|polygon)\b[^>]*class=\"[^\"]*\banim\b[^\"]*\"[^>]*>",
        re.I,
    )
    for svg_index, svg_match in enumerate(svg_block_pattern.finditer(html), start=1):
        svg = svg_match.group(0)
        for anim_match in svg_anim_pattern.finditer(svg):
            risks.append(
                {
                    "slide": None,
                    "severity": "fail",
                    "type": "svg_internal_anim_class",
                    "message": "SVG child elements must not use .anim; CSS transform overrides SVG transform and can stack elements.",
                    "svg": svg_index,
                    "tag": anim_match.group(0)[:240],
                }
            )

    return risks


def js_checker(wait_ms: int) -> str:
    return f"""
async () => {{
  const waitMs = {wait_ms};
  const viewport = {{ width: window.innerWidth, height: window.innerHeight }};
  const safe = {{ top: 48, right: 48, bottom: 48, left: 48 }};
  const slides = Array.from(document.querySelectorAll('.slide'));
  const total = window.SlideController && window.SlideController.total
    ? window.SlideController.total()
    : slides.length;

  function rectOf(el) {{
    const r = el.getBoundingClientRect();
    return {{
      left: Math.round(r.left),
      top: Math.round(r.top),
      right: Math.round(r.right),
      bottom: Math.round(r.bottom),
      width: Math.round(r.width),
      height: Math.round(r.height),
    }};
  }}

  function area(r) {{
    return Math.max(0, r.right - r.left) * Math.max(0, r.bottom - r.top);
  }}

  function intersectionArea(a, b) {{
    const left = Math.max(a.left, b.left);
    const right = Math.min(a.right, b.right);
    const top = Math.max(a.top, b.top);
    const bottom = Math.min(a.bottom, b.bottom);
    return Math.max(0, right - left) * Math.max(0, bottom - top);
  }}

  function selectorFor(el) {{
    if (el.id) return '#' + el.id;
    const cls = typeof el.className === 'string' && el.className.trim()
      ? '.' + el.className.trim().split(/\\s+/).slice(0, 3).join('.')
      : '';
    return el.tagName.toLowerCase() + cls;
  }}

  function directTextOf(el) {{
    return Array.from(el.childNodes)
      .filter(node => node.nodeType === Node.TEXT_NODE)
      .map(node => node.textContent || '')
      .join('')
      .trim();
  }}

  function textSummaryOf(el) {{
    return (directTextOf(el) || el.textContent || '').trim();
  }}

  function isPrimaryTextElement(el) {{
    if (el.closest('svg')) return false;
    const tag = el.tagName.toLowerCase();
    const text = textSummaryOf(el);
    if (!text) return false;
    if (['h1', 'h2', 'h3', 'p', 'li'].includes(tag)) return true;
    if (tag === 'span') return directTextOf(el).length >= 2;
    if (tag === 'div') return directTextOf(el).length >= 2;
    return false;
  }}

  function textBoxFor(el, idx) {{
    return {{
      index: idx,
      selector: selectorFor(el),
      tag: el.tagName.toLowerCase(),
      text: textSummaryOf(el).slice(0, 80),
      rect: rectOf(el),
      scroll: {{
        width: Math.round(el.scrollWidth || 0),
        height: Math.round(el.scrollHeight || 0),
        clientWidth: Math.round(el.clientWidth || 0),
        clientHeight: Math.round(el.clientHeight || 0),
      }},
    }};
  }}

  function isDecorative(el, style, rect) {{
    const tag = el.tagName.toLowerCase();
    const inline = (el.getAttribute('style') || '').toLowerCase().replace(/\\s+/g, '');
    const directText = directTextOf(el);
    const visualChildren = Array.from(el.children).filter(child => {{
      const childRect = child.getBoundingClientRect();
      const childStyle = getComputedStyle(child);
      return childStyle.display !== 'none'
        && childStyle.visibility !== 'hidden'
        && Number(childStyle.opacity || '1') > 0.01
        && childRect.width > 5
        && childRect.height > 5;
    }});
    if (el.closest('svg') && tag !== 'svg') return true;
    if (tag === 'canvas') return true;
    if (tag === 'svg' && rect.width >= viewport.width * 0.9 && rect.height >= viewport.height * 0.9) return true;
    if (!directText && rect.width >= viewport.width * 0.9 && rect.height >= viewport.height * 0.9) return true;
    if (tag !== 'svg' && !directText && visualChildren.length > 0) return true;
    if (style.position === 'absolute' && Number(style.opacity || '1') <= 0.35) return true;
    if (inline.includes('pointer-events:none')) return true;
    if (inline.includes('z-index:0') || inline.includes('z-index:1')) return true;
    return false;
  }}

  function isVisibleContent(el) {{
    const style = getComputedStyle(el);
    const rect = rectOf(el);
    if (style.display === 'none' || style.visibility === 'hidden') return false;
    if (Number(style.opacity || '1') <= 0.01) return false;
    if (rect.width <= 5 || rect.height <= 5) return false;
    if (rect.right <= 0 || rect.left >= viewport.width) return false;
    if (rect.bottom <= 0 || rect.top >= viewport.height) return false;
    if (isDecorative(el, style, rect)) return false;
    return true;
  }}

  const slideReports = [];
  for (let i = 0; i < total; i++) {{
    if (window.SlideController && window.SlideController.go) {{
      window.SlideController.go(i);
    }} else {{
      slides.forEach((slide, idx) => slide.classList.toggle('active', idx === i));
    }}
    await new Promise(resolve => setTimeout(resolve, waitMs));

    const active = document.querySelector('.slide.active') || slides[i];
    const slideRect = rectOf(active);
    const slideStyle = getComputedStyle(active);
    const issues = [];

    function add(severity, type, details) {{
      issues.push(Object.assign({{ severity, type }}, details || {{}}));
    }}

    if (Math.abs(slideRect.left) > 2 || Math.abs(slideRect.top) > 2) {{
      add('fail', 'active_slide_offscreen', {{ rect: slideRect }});
    }}
    if (!['absolute', 'fixed'].includes(slideStyle.position)) {{
      add('fail', 'active_slide_not_absolutely_positioned', {{ position: slideStyle.position }});
    }}
    if (slideStyle.visibility !== 'visible' || Number(slideStyle.opacity || '1') < 0.9) {{
      add('fail', 'active_slide_not_visible', {{
        visibility: slideStyle.visibility,
        opacity: slideStyle.opacity,
      }});
    }}

    const svgAnimChildren = Array.from(active.querySelectorAll('svg .anim'));
    for (const el of svgAnimChildren) {{
      add('fail', 'svg_internal_anim_class', {{
        selector: selectorFor(el),
        tag: el.tagName.toLowerCase(),
        className: el.getAttribute('class') || '',
        transform: el.getAttribute('transform') || '',
        rect: rectOf(el),
        message: 'SVG child elements must not use .anim; CSS transform overrides SVG transform and can stack elements.',
      }});
    }}

    const contentElements = Array.from(active.querySelectorAll('*')).filter(isVisibleContent);
    // 元素偏少降级为 warn：不该用昂贵的 LLM 修复去"补元素"，那会逼迫堆叠深层嵌套、
    // 反而增加 HTML 出错概率（见 docs/历史/分镜到网页修复历史.md 根因 2）。
    if (contentElements.length < 3) {{
      add('warn', 'too_few_visible_elements', {{ count: contentElements.length }});
    }}

    const contentBoxes = contentElements.map((el, idx) => {{
      const rect = rectOf(el);
      return {{
        index: idx,
        selector: selectorFor(el),
        tag: el.tagName.toLowerCase(),
        text: (el.textContent || '').trim().slice(0, 80),
        rect,
      }};
    }});

    const primaryTextElements = contentElements.filter(isPrimaryTextElement);
    const primaryTextBoxes = primaryTextElements.map(textBoxFor);
    const textBottomFailLine = viewport.height - 64;
    const textBottomWarnLine = viewport.height - 96;

    for (const item of primaryTextBoxes) {{
      if (item.rect.top < 0 || item.rect.bottom > viewport.height) {{
        add('fail', 'text_out_of_view', item);
      }} else if (item.rect.bottom > textBottomFailLine) {{
        add('fail', 'text_out_of_bottom_safe_area', Object.assign({{ limit: textBottomFailLine }}, item));
      }} else if (item.rect.bottom > textBottomWarnLine) {{
        add('warn', 'text_near_bottom_safe_area', Object.assign({{ limit: textBottomWarnLine }}, item));
      }}
      if (
        item.scroll.clientHeight > 0
        && item.scroll.height > item.scroll.clientHeight + 2
      ) {{
        add('fail', 'text_clipped_vertical', item);
      }}
      if (
        item.scroll.clientWidth > 0
        && item.scroll.width > item.scroll.clientWidth + 2
      ) {{
        add('fail', 'text_clipped_horizontal', item);
      }}
    }}

    const headings = contentBoxes.filter(item => ['h1', 'h2', 'h3'].includes(item.tag));
    for (const item of headings) {{
      if (item.rect.top < 0 || item.rect.bottom > viewport.height) {{
        add('fail', 'heading_out_of_view', item);
      }} else if (item.rect.top < safe.top || item.rect.bottom > viewport.height - safe.bottom) {{
        add('warn', 'heading_out_of_safe_area', item);
      }}
    }}

    if (contentBoxes.length > 0) {{
      const mainRect = {{
        left: Math.min(...contentBoxes.map(item => item.rect.left)),
        top: Math.min(...contentBoxes.map(item => item.rect.top)),
        right: Math.max(...contentBoxes.map(item => item.rect.right)),
        bottom: Math.max(...contentBoxes.map(item => item.rect.bottom)),
      }};
      mainRect.width = mainRect.right - mainRect.left;
      mainRect.height = mainRect.bottom - mainRect.top;

      if (mainRect.top < 0 || mainRect.bottom > viewport.height) {{
        add('fail', 'content_out_of_view', {{ rect: mainRect }});
      }} else if (mainRect.top < safe.top || mainRect.bottom > viewport.height - safe.bottom) {{
        add('warn', 'content_out_of_safe_area', {{ rect: mainRect }});
      }}

      const centerY = (mainRect.top + mainRect.bottom) / 2;
      const deltaY = Math.round(centerY - viewport.height / 2);
      if (Math.abs(deltaY) > viewport.height * 0.12) {{
        add('warn', 'content_center_offset_y', {{ deltaY, rect: mainRect }});
      }}
    }}

    for (const item of contentBoxes) {{
      if (['svg', 'canvas', 'img'].includes(item.tag) && item.rect.height > viewport.height * 0.65) {{
        add('warn', 'large_visual_too_tall', item);
      }}
    }}

    const largeVisuals = contentBoxes.filter(item => ['svg', 'canvas', 'img'].includes(item.tag) && item.rect.height >= viewport.height * 0.45);
    const textBlocks = contentBoxes.filter(item => ['h1', 'h2', 'h3', 'p', 'li', 'span'].includes(item.tag));
    for (const visual of largeVisuals) {{
      for (const text of textBlocks) {{
        if (text.rect.top <= visual.rect.top) continue;
        const horizontalOverlap = Math.min(visual.rect.right, text.rect.right) - Math.max(visual.rect.left, text.rect.left);
        if (horizontalOverlap <= Math.min(visual.rect.width, text.rect.width) * 0.25) continue;
        const gap = text.rect.top - visual.rect.bottom;
        if (gap >= 0 && gap < 110) {{
          add('fail', 'visual_text_gap_too_small', {{ visual, text, gap }});
        }}
      }}
    }}

    for (let a = 0; a < contentBoxes.length; a++) {{
      for (let b = a + 1; b < contentBoxes.length; b++) {{
        const first = contentBoxes[a];
        const second = contentBoxes[b];
        const firstEl = contentElements[a];
        const secondEl = contentElements[b];
        if (firstEl.contains(secondEl) || secondEl.contains(firstEl)) continue;
        const overlap = intersectionArea(first.rect, second.rect);
        if (overlap <= 0) continue;
        const ratio = overlap / Math.max(1, Math.min(area(first.rect), area(second.rect)));
        if (ratio > 0.15) {{
          const involvesHeading = ['h1', 'h2', 'h3'].includes(first.tag) || ['h1', 'h2', 'h3'].includes(second.tag);
          const smallBadge = Math.min(area(first.rect), area(second.rect)) < 12000;
          const headingBlocked = involvesHeading && ratio > 0.5;
          const severity = headingBlocked || (involvesHeading && !smallBadge) ? 'fail' : 'warn';
          add(severity, 'content_overlap', {{ first, second, overlapRatio: Number(ratio.toFixed(2)) }});
        }}
      }}
    }}

    const risky100vh = Array.from(active.querySelectorAll('[style*="100vh"]')).map(el => ({{
      selector: selectorFor(el),
      style: (el.getAttribute('style') || '').slice(0, 200),
    }}));
    for (const item of risky100vh) {{
      add('warn', 'child_height_100vh', item);
    }}

    const animHidden = Array.from(active.querySelectorAll('.anim.show')).filter(el => {{
      if (el.closest('svg')) return false;
      const style = getComputedStyle(el);
      const rect = rectOf(el);
      return Number(style.opacity || '1') <= 0.01 || rect.width <= 5 || rect.height <= 5;
    }}).map(el => ({{ selector: selectorFor(el), rect: rectOf(el), opacity: getComputedStyle(el).opacity }}));
    for (const item of animHidden) {{
      add('warn', 'anim_show_not_visible', item);
    }}

    slideReports.push({{
      index: i + 1,
      passed: !issues.some(issue => issue.severity === 'fail'),
      warnings: issues.filter(issue => issue.severity === 'warn').length,
      failures: issues.filter(issue => issue.severity === 'fail').length,
      slideRect,
      slidePosition: slideStyle.position,
      visibleContentCount: contentElements.length,
      sampleContent: contentBoxes.slice(0, 8),
      issues,
    }});
  }}

  return {{ viewport, slides: slideReports }};
}}
"""


def run_browser_check(html_path: Path, width: int, height: int, wait_ms: int, channel: str | None) -> dict[str, Any]:
    with sync_playwright() as playwright:
        launch_kwargs: dict[str, Any] = {"headless": True}
        if channel:
            launch_kwargs["channel"] = channel
        browser = playwright.chromium.launch(**launch_kwargs)
        page = browser.new_page(viewport={"width": width, "height": height})
        page.goto(html_path.resolve().as_uri())
        page.wait_for_load_state("load")
        report = page.evaluate(js_checker(wait_ms))
        browser.close()
    return report


def summarize(report: dict[str, Any], static_risks: list[dict[str, Any]], html_path: Path) -> bool:
    print(f"Layout QA: {html_path}")
    print(f"Viewport: {report['viewport']['width']}x{report['viewport']['height']}")
    passed = True

    for risk in static_risks:
        label = str(risk.get("severity", "warn")).upper()
        print(f"{label} static {risk['type']}: {risk['message']}")
        if risk.get("severity") == "fail":
            passed = False

    for slide in report["slides"]:
        status = "PASS" if slide["passed"] else "FAIL"
        if not slide["passed"]:
            passed = False
        suffix = f"visible={slide['visibleContentCount']} warnings={slide['warnings']}"
        if slide["failures"]:
            suffix += f" failures={slide['failures']}"
        print(f"{status} slide {slide['index']}: {suffix}")
        visible_issues = slide["issues"][:8]
        for issue in visible_issues:
            label = issue["severity"].upper()
            details = {k: v for k, v in issue.items() if k not in {"severity", "type"}}
            print(f"  {label} {issue['type']}: {json.dumps(details, ensure_ascii=False)}")
        omitted = len(slide["issues"]) - len(visible_issues)
        if omitted > 0:
            print(f"  ... {omitted} more issue(s) in JSON report")

    return passed


def main() -> int:
    stdout_reconfigure = getattr(sys.stdout, "reconfigure", None)
    if stdout_reconfigure:
        stdout_reconfigure(encoding="utf-8", errors="backslashreplace")
    stderr_reconfigure = getattr(sys.stderr, "reconfigure", None)
    if stderr_reconfigure:
        stderr_reconfigure(encoding="utf-8", errors="backslashreplace")

    args = parse_args()
    html_path = args.html.resolve()
    if not html_path.exists():
        print(f"File not found: {html_path}", file=sys.stderr)
        return 2

    static_risks = read_static_risks(html_path)
    report = run_browser_check(html_path, args.width, args.height, args.wait_ms, args.browser_channel)
    report["file"] = str(html_path)
    report["staticRisks"] = static_risks

    passed = summarize(report, static_risks, html_path)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON report: {args.json}")

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
