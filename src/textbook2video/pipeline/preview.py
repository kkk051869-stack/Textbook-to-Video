"""Storyboard preview HTML generation.

The preview is intentionally static for the first MVP: it produces a local
HTML file that lets a reviewer inspect pages, narration, elements, knowledge
point bindings, and timing without rerunning the pipeline.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

__all__ = ["build_preview_html", "preview_path_for", "write_preview"]


def _read_json(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("storyboard JSON must be an object")
    if not isinstance(data.get("segments"), list):
        raise ValueError("storyboard JSON must contain a segments list")
    return data


def preview_path_for(storyboard_path: str | Path) -> Path:
    path = Path(storyboard_path)
    stem = path.stem
    if stem.endswith("_storyboard"):
        stem = stem[: -len("_storyboard")]
    return path.with_name(f"{stem}_preview.html")


def _json_script(data: dict[str, Any]) -> str:
    raw = json.dumps(data, ensure_ascii=False)
    return raw.replace("</", r"<\/")


def _summary(storyboard: dict[str, Any]) -> dict[str, Any]:
    segments = storyboard.get("segments", []) or []
    duration = 0.0
    with_timing = 0
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        value = seg.get("audio_duration_sec")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            duration += float(value)
        if any(
            isinstance(anim, dict) and anim.get("trigger_at_sec") is not None
            for anim in seg.get("animations", []) or []
        ):
            with_timing += 1
    return {
        "slides": len(segments),
        "duration": round(duration, 1),
        "timed_slides": with_timing,
    }


def build_preview_html(
    storyboard: dict[str, Any],
    *,
    source_path: str | Path | None = None,
) -> str:
    """Build a self-contained storyboard preview page."""
    title = str(storyboard.get("lesson_title") or "Storyboard Preview")
    summary = _summary(storyboard)
    source = str(source_path or "")
    data_json = _json_script(storyboard)
    safe_title = html.escape(title)
    safe_source = html.escape(source)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title} - Preview</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --line: #d9dee7;
      --text: #1c2430;
      --muted: #667085;
      --accent: #1366d6;
      --accent-soft: #e8f1ff;
      --warn: #a15c00;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.5 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      height: 58px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 0 18px;
      background: var(--panel);
      border-bottom: 1px solid var(--line);
    }}
    h1 {{
      margin: 0;
      font-size: 18px;
      font-weight: 700;
      letter-spacing: 0;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .meta {{
      display: flex;
      gap: 14px;
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
    }}
    main {{
      display: grid;
      grid-template-columns: 320px minmax(0, 1fr);
      min-height: calc(100vh - 58px);
    }}
    aside {{
      border-right: 1px solid var(--line);
      background: var(--panel);
      overflow: auto;
      max-height: calc(100vh - 58px);
    }}
    .search {{
      width: calc(100% - 24px);
      margin: 12px;
      padding: 9px 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      font: inherit;
    }}
    .slide-btn {{
      display: grid;
      grid-template-columns: 34px minmax(0, 1fr);
      width: 100%;
      border: 0;
      border-top: 1px solid var(--line);
      background: transparent;
      padding: 11px 12px;
      text-align: left;
      cursor: pointer;
      color: inherit;
      font: inherit;
    }}
    .slide-btn:hover, .slide-btn.active {{ background: var(--accent-soft); }}
    .num {{
      width: 24px;
      height: 24px;
      border-radius: 50%;
      background: #eef1f5;
      color: var(--muted);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 12px;
      font-weight: 700;
    }}
    .active .num {{ background: var(--accent); color: white; }}
    .slide-title {{
      font-weight: 700;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .slide-sub {{
      margin-top: 2px;
      color: var(--muted);
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    section {{
      padding: 18px;
      overflow: auto;
      max-height: calc(100vh - 58px);
    }}
    .grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.1fr) minmax(340px, 0.9fr);
      gap: 14px;
      align-items: start;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }}
    h2, h3 {{
      margin: 0 0 10px;
      letter-spacing: 0;
    }}
    h2 {{ font-size: 20px; }}
    h3 {{ font-size: 14px; color: var(--muted); text-transform: uppercase; }}
    .facts {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 12px;
    }}
    .pill {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 4px 8px;
      color: var(--muted);
      background: #fafbfc;
      font-size: 12px;
    }}
    .narration {{
      white-space: pre-wrap;
      font-size: 15px;
    }}
    .list {{
      display: grid;
      gap: 8px;
    }}
    .item {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      background: #fbfcfe;
    }}
    .item-head {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 6px;
      font-weight: 700;
    }}
    .item-body {{
      color: var(--muted);
      white-space: pre-wrap;
      word-break: break-word;
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      background: #111827;
      color: #e5e7eb;
      padding: 12px;
      border-radius: 6px;
      max-height: 560px;
      overflow: auto;
      font-size: 12px;
    }}
    .empty {{ color: var(--muted); }}
    @media (max-width: 860px) {{
      header {{ align-items: flex-start; height: auto; padding: 12px; flex-direction: column; }}
      main {{ grid-template-columns: 1fr; }}
      aside {{ max-height: 320px; border-right: 0; border-bottom: 1px solid var(--line); }}
      section {{ max-height: none; }}
      .grid {{ grid-template-columns: 1fr; }}
      .meta {{ flex-wrap: wrap; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{safe_title}</h1>
    <div class="meta">
      <span>{summary["slides"]} slides</span>
      <span>{summary["duration"]}s audio</span>
      <span>{summary["timed_slides"]} timed</span>
      <span>{safe_source}</span>
    </div>
  </header>
  <main>
    <aside>
      <input id="search" class="search" placeholder="Filter slides">
      <div id="slideList"></div>
    </aside>
    <section>
      <div class="grid">
        <div class="panel">
          <h2 id="slideHeading"></h2>
          <div id="facts" class="facts"></div>
          <h3>Narration</h3>
          <div id="narration" class="narration"></div>
        </div>
        <div class="panel">
          <h3>Segment JSON</h3>
          <pre id="rawJson"></pre>
        </div>
        <div class="panel">
          <h3>Elements</h3>
          <div id="elements" class="list"></div>
        </div>
        <div class="panel">
          <h3>Animations</h3>
          <div id="animations" class="list"></div>
        </div>
      </div>
    </section>
  </main>
  <script>
    const storyboard = {data_json};
    const segments = Array.isArray(storyboard.segments) ? storyboard.segments : [];
    let activeIndex = 0;

    function textOf(value) {{
      if (value == null) return "";
      if (typeof value === "string" || typeof value === "number") return String(value);
      if (Array.isArray(value)) return value.map(textOf).filter(Boolean).join(" / ");
      if (typeof value === "object") {{
        return ["text", "title", "label", "caption", "description", "items", "steps", "src"]
          .map(k => textOf(value[k])).filter(Boolean).join(" / ");
      }}
      return "";
    }}
    function escapeHtml(value) {{
      return String(value ?? "").replace(/[&<>"']/g, ch => ({{
        "&": "&amp;", "<": "&lt;", ">": "&gt;", "\\"": "&quot;", "'": "&#39;"
      }}[ch]));
    }}
    function slideLabel(seg, index) {{
      const heading = (seg.elements || []).find(el => el && el.type === "heading");
      return textOf(heading) || seg.visual_type || `Slide ${{index + 1}}`;
    }}
    function renderList(filter = "") {{
      const root = document.getElementById("slideList");
      const term = filter.trim().toLowerCase();
      root.innerHTML = "";
      segments.forEach((seg, index) => {{
        const haystack = JSON.stringify(seg).toLowerCase();
        if (term && !haystack.includes(term)) return;
        const btn = document.createElement("button");
        btn.className = "slide-btn" + (index === activeIndex ? " active" : "");
        btn.innerHTML = `
          <span class="num">${{index + 1}}</span>
          <span>
            <div class="slide-title">${{escapeHtml(slideLabel(seg, index))}}</div>
            <div class="slide-sub">${{escapeHtml(seg.visual_type || "")}} · ${{escapeHtml(seg.audio_duration_sec || "?")}}s</div>
          </span>`;
        btn.addEventListener("click", () => {{ activeIndex = index; render(); }});
        root.appendChild(btn);
      }});
    }}
    function renderItems(id, items, formatter) {{
      const root = document.getElementById(id);
      root.innerHTML = "";
      if (!items || !items.length) {{
        root.innerHTML = '<div class="empty">None</div>';
        return;
      }}
      items.forEach(item => {{
        const div = document.createElement("div");
        div.className = "item";
        div.innerHTML = formatter(item);
        root.appendChild(div);
      }});
    }}
    function render() {{
      const seg = segments[activeIndex] || {{}};
      document.getElementById("slideHeading").textContent = slideLabel(seg, activeIndex);
      document.getElementById("facts").innerHTML = [
        `id: ${{seg.id ?? activeIndex + 1}}`,
        `type: ${{seg.visual_type || "unknown"}}`,
        `render: ${{seg.render_mode || "auto"}}`,
        `audio: ${{seg.audio_duration_sec || "?"}}s`,
        `kp: ${{(seg.knowledge_point_ids || []).join(", ") || "none"}}`
      ].map(x => `<span class="pill">${{escapeHtml(x)}}</span>`).join("");
      document.getElementById("narration").textContent = seg.narration || "";
      document.getElementById("rawJson").textContent = JSON.stringify(seg, null, 2);
      renderItems("elements", seg.elements || [], el => `
        <div class="item-head"><span>${{escapeHtml(el.id || "")}}</span><span>${{escapeHtml(el.type || "")}}</span></div>
        <div class="item-body">${{escapeHtml(textOf(el) || JSON.stringify(el))}}</div>`);
      renderItems("animations", seg.animations || [], anim => `
        <div class="item-head"><span>${{escapeHtml(anim.target || "")}}</span><span>${{escapeHtml(anim.trigger_at_sec ?? "?")}}s</span></div>
        <div class="item-body">${{escapeHtml(anim.effect || "")}}</div>`);
      renderList(document.getElementById("search").value);
    }}
    document.getElementById("search").addEventListener("input", event => renderList(event.target.value));
    render();
  </script>
</body>
</html>
"""


def write_preview(
    storyboard_path: str | Path,
    output_path: str | Path | None = None,
) -> Path:
    """Write a self-contained preview HTML file and return its path."""
    storyboard_path = Path(storyboard_path)
    storyboard = _read_json(storyboard_path)
    out = Path(output_path) if output_path else preview_path_for(storyboard_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        build_preview_html(storyboard, source_path=storyboard_path),
        encoding="utf-8",
    )
    return out
