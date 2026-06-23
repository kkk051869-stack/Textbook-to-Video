"""Storyboard preview and lightweight local editor.

The default preview is a self-contained HTML file. When editing is requested,
the CLI starts a small localhost server so the browser can save changes back
to the storyboard JSON after server-side validation.
"""

from __future__ import annotations

import html
import json
import shutil
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

__all__ = [
    "backup_path_for",
    "build_preview_html",
    "preview_path_for",
    "save_storyboard_json",
    "serve_preview",
    "write_preview",
]


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


def backup_path_for(storyboard_path: str | Path) -> Path:
    path = Path(storyboard_path)
    return path.with_suffix(path.suffix + ".bak")


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
    editable: bool = False,
    save_endpoint: str = "/api/storyboard",
    source_path: str | Path | None = None,
) -> str:
    """Build a self-contained storyboard preview page."""
    title = str(storyboard.get("lesson_title") or "Storyboard Preview")
    summary = _summary(storyboard)
    source = str(source_path or "")
    data_json = _json_script(storyboard)
    editable_json = "true" if editable else "false"
    endpoint_json = json.dumps(save_endpoint)
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
      --danger: #b42318;
      --ok: #067647;
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
    button.primary {{
      border: 0;
      border-radius: 6px;
      padding: 8px 12px;
      background: var(--accent);
      color: white;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }}
    button.secondary {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 7px 11px;
      background: white;
      color: var(--text);
      font: inherit;
      cursor: pointer;
    }}
    button:disabled {{ opacity: 0.55; cursor: not-allowed; }}
    .toolbar {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      margin-bottom: 10px;
    }}
    .status {{
      color: var(--muted);
      font-size: 12px;
    }}
    .status.ok {{ color: var(--ok); }}
    .status.err {{ color: var(--danger); }}
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
    textarea.editor {{
      width: 100%;
      min-height: 560px;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 12px;
      background: #111827;
      color: #e5e7eb;
      font: 12px/1.45 ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
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
          <div id="editorToolbar" class="toolbar" hidden>
            <button id="applySegment" class="secondary" type="button">Apply Segment</button>
            <button id="saveStoryboard" class="primary" type="button">Save Storyboard</button>
            <span id="saveStatus" class="status"></span>
          </div>
          <pre id="rawJson"></pre>
          <textarea id="segmentEditor" class="editor" spellcheck="false" hidden></textarea>
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
    const editable = {editable_json};
    const saveEndpoint = {endpoint_json};
    const segments = Array.isArray(storyboard.segments) ? storyboard.segments : [];
    let activeIndex = 0;
    let dirty = false;

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
      const rawJson = document.getElementById("rawJson");
      const editor = document.getElementById("segmentEditor");
      if (editable) {{
        rawJson.hidden = true;
        editor.hidden = false;
        editor.value = JSON.stringify(seg, null, 2);
      }} else {{
        rawJson.hidden = false;
        editor.hidden = true;
        rawJson.textContent = JSON.stringify(seg, null, 2);
      }}
      renderItems("elements", seg.elements || [], el => `
        <div class="item-head"><span>${{escapeHtml(el.id || "")}}</span><span>${{escapeHtml(el.type || "")}}</span></div>
        <div class="item-body">${{escapeHtml(textOf(el) || JSON.stringify(el))}}</div>`);
      renderItems("animations", seg.animations || [], anim => `
        <div class="item-head"><span>${{escapeHtml(anim.target || "")}}</span><span>${{escapeHtml(anim.trigger_at_sec ?? "?")}}s</span></div>
        <div class="item-body">${{escapeHtml(anim.effect || "")}}</div>`);
      renderList(document.getElementById("search").value);
    }}
    function setStatus(message, kind = "") {{
      const node = document.getElementById("saveStatus");
      node.textContent = message;
      node.className = "status" + (kind ? ` ${{kind}}` : "");
    }}
    function applySegmentEditor() {{
      const editor = document.getElementById("segmentEditor");
      try {{
        const next = JSON.parse(editor.value);
        if (!next || typeof next !== "object" || Array.isArray(next)) {{
          throw new Error("segment must be a JSON object");
        }}
        segments[activeIndex] = next;
        storyboard.segments = segments;
        dirty = true;
        setStatus("Applied locally, not saved yet.", "ok");
        render();
        return true;
      }} catch (err) {{
        setStatus(`JSON error: ${{err.message}}`, "err");
        return false;
      }}
    }}
    async function saveStoryboard() {{
      if (!applySegmentEditor()) return;
      const button = document.getElementById("saveStoryboard");
      button.disabled = true;
      setStatus("Saving...");
      try {{
        const response = await fetch(saveEndpoint, {{
          method: "POST",
          headers: {{ "content-type": "application/json" }},
          body: JSON.stringify(storyboard)
        }});
        const result = await response.json();
        if (!response.ok || !result.ok) {{
          throw new Error(result.error || "save failed");
        }}
        dirty = false;
        const notes = result.warnings && result.warnings.length
          ? ` Saved with ${{result.warnings.length}} warning(s).`
          : " Saved.";
        setStatus(`${{notes}} Backup: ${{result.backup || "none"}}`, "ok");
      }} catch (err) {{
        setStatus(`Save failed: ${{err.message}}`, "err");
      }} finally {{
        button.disabled = false;
      }}
    }}
    document.getElementById("search").addEventListener("input", event => renderList(event.target.value));
    if (editable) {{
      document.getElementById("editorToolbar").hidden = false;
      document.getElementById("segmentEditor").addEventListener("input", () => {{
        dirty = true;
        setStatus("Edited locally, not saved.");
      }});
      document.getElementById("applySegment").addEventListener("click", applySegmentEditor);
      document.getElementById("saveStoryboard").addEventListener("click", saveStoryboard);
      window.addEventListener("beforeunload", event => {{
        if (!dirty) return;
        event.preventDefault();
        event.returnValue = "";
      }});
    }}
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


def _validate_for_save(storyboard: dict[str, Any], storyboard_path: Path) -> list[str]:
    if not isinstance(storyboard, dict):
        raise ValueError("storyboard JSON must be an object")
    if not isinstance(storyboard.get("segments"), list) or not storyboard["segments"]:
        raise ValueError("storyboard JSON must contain a non-empty segments list")

    from textbook2video.pipeline.checks import validate_storyboard

    report = validate_storyboard(storyboard, base_dir=storyboard_path.parent)
    if report.errors:
        raise ValueError("; ".join(report.errors))
    return report.warnings


def save_storyboard_json(
    storyboard_path: str | Path,
    storyboard: dict[str, Any],
    *,
    create_backup: bool = True,
) -> dict[str, Any]:
    """Validate and save storyboard JSON, preserving a first-edit backup."""
    path = Path(storyboard_path)
    warnings = _validate_for_save(storyboard, path)
    backup = backup_path_for(path)
    if create_backup and path.exists() and not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(
        json.dumps(storyboard, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "ok": True,
        "path": str(path),
        "backup": str(backup) if backup.exists() else None,
        "warnings": warnings,
    }


def serve_preview(
    storyboard_path: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = False,
) -> str:
    """Serve editable preview until interrupted. Returns the served URL."""
    path = Path(storyboard_path).resolve()
    _read_json(path)

    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _send_html(self) -> None:
            storyboard = _read_json(path)
            raw = build_preview_html(
                storyboard,
                editable=True,
                source_path=path,
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
            route = urlparse(self.path).path
            if route in ("/", "/preview"):
                self._send_html()
                return
            if route == "/api/storyboard":
                self._send_json(200, _read_json(path))
                return
            self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
            route = urlparse(self.path).path
            if route != "/api/storyboard":
                self.send_error(404)
                return
            try:
                size = int(self.headers.get("content-length", "0"))
                payload = self.rfile.read(size).decode("utf-8")
                data = json.loads(payload)
                result = save_storyboard_json(path, data)
            except Exception as exc:  # intentionally reports validation failures
                self._send_json(400, {"ok": False, "error": str(exc)})
                return
            self._send_json(200, result)

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    actual_host, actual_port = server.server_address[:2]
    url = f"http://{actual_host}:{actual_port}/"
    print(f"\nEditable preview: {url}")
    print("Press Ctrl+C to stop the preview server.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return url
