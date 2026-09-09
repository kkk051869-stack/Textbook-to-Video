"""CSS hot-fix engine — fixes common layout QA failures via Playwright JS, 0 LLM tokens.

Runs after layout QA detects failures. For each FAIL type, applies targeted CSS
fixes directly in the browser, then saves the modified HTML. Only falls back to
LLM repair for issues that cannot be fixed by CSS adjustments.

Usage:
    from textbook2video.css_hotfix import apply_css_hotfixes
    fixed_count = apply_css_hotfixes(html_path, report, browser_channel="msedge")
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

JsonDict = dict[str, Any]


def _fix_js_for_failures(failures: list[JsonDict], viewport: dict) -> str:
    """Generate a JS function that applies CSS fixes for each failure type.

    Returns a JS string that can be evaluated in the browser.
    Uses CSS selectors from QA report for reliable element targeting.
    """
    fixes = []
    for f in failures:
        ftype = f.get("type", "")
        sel = f.get("selector", "")

        if ftype == "text_clipped_vertical":
            if sel:
                # 按比例缩字号：所需缩放 ≈ clientHeight / scrollHeight（高度近似随字号线性）。
                # 不能用"溢出像素数"直接减字号——量纲不同，几十~上百 px 的溢出会把字号
                # 一把砸到 8px 下限。数据缺失时退化到 ×0.85。再留 3% 余量防边界回弹。
                scroll_h = f.get("scroll", {}).get("height", 0)
                client_h = f.get("scroll", {}).get("clientHeight", 0)
                ratio = (client_h / scroll_h) if (scroll_h and client_h and scroll_h > client_h) else 0.0
                fixes.append(
                    f"// Fix text_clipped_vertical: {sel} (scroll {scroll_h}->{client_h}, ratio {ratio:.3f})\n"
                    f"_fixBySelector({json.dumps(sel)}, el => {{ "
                    f"const cs = getComputedStyle(el); "
                    f"const fs = parseFloat(cs.fontSize); "
                    f"const r = {ratio:.4f}; "
                    f"if (fs > 0) {{ "
                    f"  const nf = r > 0 ? fs * r * 0.97 : fs * 0.85; "
                    f"  el.style.fontSize = Math.max(8, nf) + 'px'; "
                    f"  el.style.lineHeight = '1.2'; "
                    f"  el.style.overflow = 'hidden'; "
                    f"}} "
                    f"}});"
                )

        elif ftype == "text_clipped_horizontal":
            if sel:
                scroll_w = f.get("scroll", {}).get("width", 0)
                client_w = f.get("scroll", {}).get("clientWidth", 0)
                ratio = (client_w / scroll_w) if (scroll_w and client_w and scroll_w > client_w) else 0.0
                fixes.append(
                    f"// Fix text_clipped_horizontal: {sel} (scroll {scroll_w}->{client_w}, ratio {ratio:.3f})\n"
                    f"_fixBySelector({json.dumps(sel)}, el => {{ "
                    f"const cs = getComputedStyle(el); "
                    f"const fs = parseFloat(cs.fontSize); "
                    f"const r = {ratio:.4f}; "
                    f"if (fs > 0) {{ "
                    f"  const nf = r > 0 ? fs * r * 0.97 : fs * 0.85; "
                    f"  el.style.fontSize = Math.max(8, nf) + 'px'; "
                    f"  el.style.overflow = 'hidden'; "
                    f"}} "
                    f"}});"
                )

        elif ftype == "text_out_of_bottom_safe_area":
            if sel:
                fixes.append(
                    f"// Fix text_out_of_bottom_safe_area: {sel}\n"
                    f"_fixBySelector({json.dumps(sel)}, el => {{ "
                    f"el.style.marginBottom = '8px'; "
                    f"if (el.style.fontSize) {{ "
                    f"  const fs = parseFloat(el.style.fontSize); "
                    f"  if (fs > 14) el.style.fontSize = (fs * 0.9) + el.style.fontSize.replace(/\\d.*/, '').replace(String(fs), ''); "
                    f"}} "
                    f"}});"
                )

        elif ftype == "text_out_of_view":
            rect = f.get("rect", {})
            bottom = rect.get("bottom", 0)
            vh = viewport.get("height", 1080)
            if sel and bottom > vh:
                fixes.append(
                    f"// Fix text_out_of_view (bottom): {sel}\n"
                    f"_fixBySelector({json.dumps(sel)}, el => {{ "
                    f"el.style.overflow = 'visible'; "
                    f"el.style.marginBottom = '12px'; "
                    f"}});"
                )

        elif ftype == "visual_text_gap_too_small":
            visual = f.get("visual", {})
            visual_sel = visual.get("selector", "")
            gap = f.get("gap", 0)
            needed = 110 - gap
            if needed > 0 and visual_sel:
                fixes.append(
                    f"// Fix visual_text_gap_too_small: {visual_sel}, gap={gap}px, need +{needed}px\n"
                    f"_fixBySelector({json.dumps(visual_sel)}, el => {{ "
                    f"el.style.marginBottom = '{needed}px'; "
                    f"}});"
                )

        elif ftype == "content_overlap":
            first = f.get("first", {})
            second = f.get("second", {})
            ratio = f.get("overlapRatio", 0)
            second_sel = second.get("selector", "")
            if ratio > 0.15 and second_sel:
                fixes.append(
                    f"// Fix content_overlap: second={second_sel}, ratio={ratio}\n"
                    f"_fixBySelector({json.dumps(second_sel)}, el => {{ "
                    f"el.style.marginTop = '12px'; "
                    f"el.style.position = 'relative'; "
                    f"el.style.zIndex = '10'; "
                    f"}});"
                )

        elif ftype == "content_out_of_view":
            rect = f.get("rect", {})
            bottom = rect.get("bottom", 0)
            vh = viewport.get("height", 1080)
            if bottom > vh:
                fixes.append(
                    f"// Fix content_out_of_view: content extends {bottom - vh}px below viewport\n"
                    f"_fixSlideContent(slide => {{ "
                    f"const inner = slide.querySelector('[style]') || slide.children[0]; "
                    f"if (inner) {{ "
                    f"  const scale = Math.max(0.85, {vh} / {bottom}); "
                    f"  inner.style.transform = 'scale(' + scale + ')'; "
                    f"  inner.style.transformOrigin = 'top center'; "
                    f"}} "
                    f"}});"
                )

    if not fixes:
        return ""

    return """
(function applyCssHotfixes() {
  const slides = document.querySelectorAll('.slide');

  function _fixBySelector(selector, fixer) {
    for (const slide of slides) {
      if (!slide.classList.contains('active')) continue;
      /* Try exact match within slide first, then fall back to global */
      let targets = slide.querySelectorAll(selector);
      if (targets.length === 0) {
        /* Selector might include class combinators that need broader scope */
        try { targets = document.querySelectorAll(selector); } catch(e) {}
      }
      targets.forEach(fixer);
    }
  }

  function _fixSlideContent(fixer) {
    for (const slide of slides) {
      if (!slide.classList.contains('active')) continue;
      fixer(slide);
    }
  }

  """ + "\n  ".join(fixes) + """
})();
"""


def apply_css_hotfixes(
    html_path: Path,
    report: JsonDict,
    *,
    browser_channel: str = "msedge",
) -> int:
    """Apply CSS hot-fixes for common QA failures. Returns number of fixes applied.

    This runs in Playwright: navigates to the HTML, applies JS CSS fixes,
    reads back the modified HTML, and writes it to disk.

    Args:
        html_path: Path to the generated HTML file.
        report: Merged layout QA report (from run_layout_qa).
        browser_channel: Playwright browser channel.

    Returns:
        Number of FAIL issues that were targeted for CSS fix.
    """
    # Collect all FAIL issues per slide
    slides_report = report.get("slides", [])
    viewport = report.get("viewport", {"width": 1920, "height": 1080})

    all_failures: list[JsonDict] = []
    for slide in slides_report:
        for issue in slide.get("issues", []):
            if issue.get("severity") == "fail":
                all_failures.append(issue)

    if not all_failures:
        return 0

    # Filter to only CSS-fixable types
    css_fixable_types = {
        "text_clipped_vertical",
        "text_clipped_horizontal",
        "text_out_of_bottom_safe_area",
        "text_out_of_view",
        "visual_text_gap_too_small",
        "content_overlap",
        "content_out_of_view",
    }
    fixable = [f for f in all_failures if f.get("type") in css_fixable_types]

    if not fixable:
        return 0

    fix_js = _fix_js_for_failures(fixable, viewport)
    if not fix_js:
        return 0

    print(f"  [css-hotfix] Attempting CSS hot-fix for {len(fixable)} issues...")

    modified_html = ""
    with sync_playwright() as pw:
        launch_kwargs: dict[str, Any] = {"headless": True}
        if browser_channel:
            launch_kwargs["channel"] = browser_channel
        browser = pw.chromium.launch(**launch_kwargs)

        # Apply fixes viewport by viewport (1920x1080 first, then 1366x768)
        for width, height in [(1920, 1080), (1366, 768)]:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(html_path.resolve().as_uri())
            page.wait_for_load_state("load")

            # Navigate to each slide and apply fixes
            total_slides = page.evaluate("document.querySelectorAll('.slide').length")
            for slide_idx in range(total_slides):
                page.evaluate(f"""
                    () => {{
                      if (window.SlideController && window.SlideController.go) {{
                        window.SlideController.go({slide_idx});
                      }} else {{
                        document.querySelectorAll('.slide').forEach((s, i) => {{
                          s.classList.toggle('active', i === {slide_idx});
                        }});
                      }}
                    }}
                """)
                page.wait_for_timeout(500)
                page.evaluate(fix_js)

            # For the primary viewport (1920x1080), save the modified HTML
            if width == 1920:
                # 序列化前复位运行时状态：css_hotfix 遍历各页时通过 SlideController 切换过
                # active，若直接 page.content() 会把 active / transition-* / .anim.show 等
                # 运行时类固化进静态 HTML（active 会停在最后一页、并残留 transition-enter），
                # 导致打开时初始页错乱、甚至遮挡其它页。这里复位为初始态：只第 1 页 active、
                # 清除切换/入场的运行时类，让 SlideController 在加载时重新驱动。
                # element.style 上的 CSS 修复不在复位范围，会被完整保留。
                page.evaluate("""() => {
                  document.querySelectorAll('.slide').forEach((s, i) => {
                    s.classList.remove('active', 'transition-enter', 'transition-exit');
                    s.style.animationName = '';
                    s.querySelectorAll('.anim.show').forEach(e => e.classList.remove('show'));
                    if (i === 0) s.classList.add('active');
                  });
                }""")
                # element.style 修复已写入 DOM，序列化即可保留
                modified_html = page.content()

            page.close()

        browser.close()

    # Write the modified HTML (from 1920x1080 viewport session)
    if modified_html:
        html_path.write_text(modified_html, encoding="utf-8")
        print(f"  [css-hotfix] Saved CSS-hotfixed HTML ({len(modified_html)} chars)")
    else:
        print(f"  [css-hotfix] No modified HTML to save")
        return 0

    return len(fixable)
