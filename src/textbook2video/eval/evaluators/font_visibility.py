"""Deterministic browser gate for font binding and visible CJK glyphs."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from ..runner import EvalContext
from .common import evidence_for, unavailable


DEFAULT_PROBE_TEXT = "互联网 数字化转型 中国制造 教育 数据"
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_FONT_FACE_RE = re.compile(r"@font-face\s*\{(?P<body>.*?)\}", re.IGNORECASE | re.DOTALL)
_FONT_FAMILY_RE = re.compile(r"font-family\s*:\s*([^;]+)", re.IGNORECASE)
_FONT_DEFAULT_RE = re.compile(r"--font-(?:body|heading|display|label|number)-default\s*:\s*([^;]+)", re.IGNORECASE)
_FONT_SRC_RE = re.compile(r"src\s*:\s*([^;]+)", re.IGNORECASE)
_URL_RE = re.compile(r"url\(\s*['\"]?([^'\")]+)", re.IGNORECASE)
_GENERIC_FAMILIES = {"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui"}


def _first_family(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    for candidate in value.split(","):
        family = candidate.strip().strip("'\"")
        if family and family.lower() not in _GENERIC_FAMILIES and not family.startswith("var("):
            return family
    return None


def _normalize_family(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().strip("'\"")).casefold()


def _font_faces_from_css(html: str) -> list[dict[str, Any]]:
    faces: list[dict[str, Any]] = []
    for match in _FONT_FACE_RE.finditer(html):
        body = match.group("body")
        family_match = _FONT_FAMILY_RE.search(body)
        src_match = _FONT_SRC_RE.search(body)
        family = _first_family(family_match.group(1) if family_match else None)
        sources = _URL_RE.findall(src_match.group(1)) if src_match else []
        faces.append({"family": family, "sources": sources})
    return faces


def _infer_html_family(html: str) -> str | None:
    for stack in _FONT_DEFAULT_RE.findall(html):
        family = _first_family(stack)
        if family:
            return family
    return None


def _font_setting_sources(context: EvalContext) -> list[dict[str, Any]]:
    settings: list[dict[str, Any]] = []
    raw = context.case.raw if isinstance(context.case.raw, dict) else {}
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    for container in (raw, metadata):
        for key in ("font_visibility", "fonts", "font"):
            value = container.get(key)
            if isinstance(value, dict):
                settings.append(value)
    for role in ("run_config", "candidate_manifest"):
        path = context.artifact(role)
        if path is None or not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict):
            continue
        settings.append(value)
        for key in ("font_visibility", "fonts", "font", "config", "environment"):
            nested = value.get(key)
            if isinstance(nested, dict):
                settings.append(nested)
    return settings


def _setting(settings: list[dict[str, Any]], *keys: str) -> Any:
    for item in settings:
        for key in keys:
            if key in item and item[key] not in (None, ""):
                return item[key]
    return None


def _resolve_asset_path(value: Any, *, html_path: Path, artifacts_root: Path) -> Path | None:
    if isinstance(value, dict):
        value = value.get("path") or value.get("asset")
    if not isinstance(value, str) or not value.strip():
        return None
    if value.startswith("file://"):
        parsed = urlparse(value)
        return Path(unquote(parsed.path.lstrip("/")))
    path = Path(value)
    if path.is_absolute():
        return path
    candidates = [artifacts_root / path, html_path.parent / path]
    return next((candidate.resolve() for candidate in candidates if candidate.is_file()), candidates[0].resolve())


def _font_asset_info(path: Path | None, expected_sha256: str | None = None) -> dict[str, Any]:
    info: dict[str, Any] = {
        "path": str(path) if path is not None else None,
        "exists": bool(path is not None and path.is_file()),
        "sha256": None,
        "expected_sha256": expected_sha256,
    }
    if not info["exists"]:
        return info
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    info["sha256"] = digest.hexdigest()
    info["sha256_matches"] = expected_sha256 is None or info["sha256"].casefold() == expected_sha256.casefold()
    return info


def _browser_executable(playwright: Any) -> str | None:
    for key in ("T2V_PLAYWRIGHT_EXECUTABLE", "T2V_BROWSER_EXECUTABLE"):
        configured = os.environ.get(key)
        if configured and Path(configured).is_file():
            return configured
    default = Path(playwright.chromium.executable_path)
    return str(default) if default.is_file() else None


def _browser_probe(page: Any, *, expected_family: str, probe_text: str) -> dict[str, Any]:
    return page.evaluate(
        """
        async ({expectedFamily, probeText}) => {
          const cjk = /[\\u3400-\\u4dbf\\u4e00-\\u9fff\\uf900-\\ufaff]/;
          const chars = Array.from(new Set(Array.from(probeText).filter(ch => cjk.test(ch))));
          const familyKey = (value) => String(value || '').replace(/["']/g, '').trim().toLowerCase();
          const fontStack = (value) => {
            const quoted = JSON.stringify(String(value || ''));
            return `${quoted}, sans-serif`;
          };
          const fingerprint = (ch, family) => {
            const canvas = document.createElement('canvas');
            canvas.width = 160;
            canvas.height = 160;
            const ctx = canvas.getContext('2d', { willReadFrequently: true });
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.fillStyle = '#000';
            ctx.textBaseline = 'top';
            ctx.font = `64px ${family}`;
            ctx.fillText(ch, 8, 8);
            const image = ctx.getImageData(0, 0, canvas.width, canvas.height);
            let minX = canvas.width, minY = canvas.height, maxX = -1, maxY = -1, ink = 0;
            for (let y = 0; y < canvas.height; y += 1) {
              for (let x = 0; x < canvas.width; x += 1) {
                const alpha = image.data[(y * canvas.width + x) * 4 + 3];
                if (alpha < 8) continue;
                ink += 1;
                minX = Math.min(minX, x); minY = Math.min(minY, y);
                maxX = Math.max(maxX, x); maxY = Math.max(maxY, y);
              }
            }
            if (maxX < minX) return { hash: 'empty', width: 0, height: 0, ink: 0 };
            let hash = 2166136261;
            for (let y = minY; y <= maxY; y += 1) {
              for (let x = minX; x <= maxX; x += 1) {
                const alpha = image.data[(y * canvas.width + x) * 4 + 3];
                hash ^= alpha;
                hash = Math.imul(hash, 16777619);
              }
            }
            return {
              hash: (hash >>> 0).toString(16),
              width: maxX - minX + 1,
              height: maxY - minY + 1,
              ink,
            };
          };
          await document.fonts.ready;
          const loaded = await document.fonts.load(`48px "${expectedFamily.replace(/"/g, '\\"')}"`, probeText);
          const expectedStack = fontStack(expectedFamily);
          const fallbackStack = fontStack('__T2V_NON_EXISTENT_FONT__');
          const expectedGlyphs = chars.map(ch => ({ char: ch, ...fingerprint(ch, expectedStack) }));
          const fallbackGlyphs = chars.map(ch => ({ char: ch, ...fingerprint(ch, fallbackStack) }));
          const sameAsFallback = expectedGlyphs.filter((item, index) => item.hash === fallbackGlyphs[index].hash).length;
          const expectedHashes = new Set(expectedGlyphs.map(item => item.hash));
          const visibleCount = expectedGlyphs.filter(item => item.ink > 0).length;
          const tofuSuspected = chars.length >= 3 && (
            visibleCount < Math.max(3, Math.ceil(chars.length * 0.6)) ||
            (sameAsFallback / chars.length >= 0.7 && expectedHashes.size <= Math.max(2, Math.ceil(chars.length * 0.35)))
          );
          const fontFaces = Array.from(document.fonts).map(face => ({
            family: face.family,
            status: face.status,
            weight: face.weight,
            style: face.style,
          }));
          const cssFontFaces = [];
          for (const sheet of Array.from(document.styleSheets)) {
            let rules;
            try { rules = Array.from(sheet.cssRules || []); } catch (_) { continue; }
            for (const rule of rules) {
              if (!rule.cssText || !/^@font-face/i.test(rule.cssText.trim())) continue;
              cssFontFaces.push({
                family: rule.style && rule.style.getPropertyValue('font-family') || null,
                sources: rule.style && rule.style.getPropertyValue('src') || null,
              });
            }
          }
          const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
          const nodes = [];
          let current;
          while ((current = walker.nextNode())) {
            const text = String(current.nodeValue || '');
            if (!cjk.test(text)) continue;
            const element = current.parentElement;
            if (!element) continue;
            if (['SCRIPT', 'STYLE', 'TEMPLATE', 'NOSCRIPT'].includes(element.tagName)) continue;
            const style = getComputedStyle(element);
            const charsForNode = Array.from(new Set(Array.from(text).filter(ch => cjk.test(ch)))).slice(0, 12);
            const nodeGlyphs = charsForNode.map(ch => ({ char: ch, ...fingerprint(ch, style.fontFamily) }));
            const nodeFallback = charsForNode.map(ch => fingerprint(ch, fallbackStack));
            const sameNodeFallback = nodeGlyphs.filter((item, index) => item.hash === nodeFallback[index].hash).length;
            const nodeHashes = new Set(nodeGlyphs.map(item => item.hash));
            const nodeTofu = charsForNode.length >= 3 && (
              nodeGlyphs.filter(item => item.ink > 0).length < Math.max(2, Math.ceil(charsForNode.length * 0.6)) ||
              (sameNodeFallback / charsForNode.length >= 0.7 && nodeHashes.size <= Math.max(2, Math.ceil(charsForNode.length * 0.35)))
            );
            nodes.push({
              tag: element.tagName.toLowerCase(),
              class_name: String(element.className || '').slice(0, 120),
              text: text.trim().slice(0, 160),
              font_family: style.fontFamily,
              font_size: style.fontSize,
              suspected_missing_glyph: nodeTofu,
            });
          }
          const computedFamilies = Array.from(new Set(nodes.map(item => item.font_family).filter(Boolean)));
          const matchingFaces = fontFaces.filter(face => familyKey(face.family) === familyKey(expectedFamily));
          return {
            document_fonts_status: document.fonts.status,
            font_check: document.fonts.check(`48px "${expectedFamily.replace(/"/g, '\\"')}"`, probeText),
            loaded_font_faces: loaded.length,
            font_faces: fontFaces,
            css_font_faces: cssFontFaces,
            matching_loaded_faces: matchingFaces.filter(face => face.status === 'loaded').length,
            expected_family_used: computedFamilies.some(value => familyKey(value).split(',')[0].trim() === familyKey(expectedFamily)),
            computed_font_families: computedFamilies,
            probe_text: probeText,
            probe_glyphs: expectedGlyphs,
            fallback_glyphs: fallbackGlyphs,
            same_as_fallback_count: sameAsFallback,
            visible_glyph_count: visibleCount,
            unique_glyph_fingerprint_count: expectedHashes.size,
            tofu_suspected: tofuSuspected,
            cjk_nodes: nodes,
          };
        }
        """,
        {"expectedFamily": expected_family, "probeText": probe_text},
    )


def evaluate_font_visibility(context: EvalContext) -> dict[str, Any]:
    name = "font_visibility"
    html_path = context.artifact("html")
    if html_path is None or not html_path.is_file():
        result = unavailable(context, name, "candidate HTML is missing")
        result["details"] = {"required": True}
        return result

    html = html_path.read_text(encoding="utf-8", errors="replace")
    settings = _font_setting_sources(context)
    expected_family = (
        _setting(settings, "expected_family", "expected_font_family", "font_family")
        or os.environ.get("T2V_EXPECTED_FONT_FAMILY")
        or _infer_html_family(html)
    )
    expected_family = str(expected_family or "").strip().strip("'\"")
    if not expected_family:
        result = unavailable(context, name, "expected font family is not configured or discoverable")
        result["details"] = {"required": True}
        return result

    font_asset_setting = _setting(
        settings,
        "expected_font_asset",
        "font_asset_path",
        "expected_font_path",
        "font_asset",
    ) or os.environ.get("T2V_FONT_ASSET_PATH")
    expected_sha256 = _setting(settings, "expected_font_sha256", "font_sha256") or os.environ.get(
        "T2V_FONT_ASSET_SHA256"
    )
    asset_path = _resolve_asset_path(
        font_asset_setting,
        html_path=html_path,
        artifacts_root=context.artifacts_root,
    )
    asset = _font_asset_info(asset_path, str(expected_sha256) if expected_sha256 else None)
    asset_required = font_asset_setting is not None or bool(os.environ.get("T2V_FONT_ASSET_REQUIRED"))
    font_faces = _font_faces_from_css(html)
    explicit_font_face = any(
        _normalize_family(face.get("family")) == _normalize_family(expected_family) for face in font_faces
    )
    probe_text = str(_setting(settings, "probe_text", "cjk_probe_text") or DEFAULT_PROBE_TEXT)
    evidence_id = f"{context.case.case_id}-font-visibility"
    evidence = [evidence_for(html_path, evidence_id=evidence_id, kind="candidate_html")]
    if asset_path is not None and asset_path.is_file():
        evidence.append(evidence_for(asset_path, evidence_id=f"{evidence_id}-font", kind="font_asset"))

    issues: list[dict[str, Any]] = []
    if asset_required and not asset["exists"]:
        issues.append({
            "type": "FONT_ASSET_MISSING",
            "severity": "major",
            "message": "required font asset is missing",
            "evidence_ids": [evidence_id],
        })
    if asset.get("exists") and asset.get("sha256_matches") is False:
        issues.append({
            "type": "FONT_ASSET_HASH_MISMATCH",
            "severity": "major",
            "message": "font asset SHA-256 does not match the configured digest",
            "evidence_ids": [f"{evidence_id}-font"],
        })
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        result = unavailable(context, name, "Playwright is not installed")
        result["details"] = {"required": True, "expected_family": expected_family}
        return result

    page_errors: list[str] = []
    console_errors: list[str] = []
    request_failures: list[str] = []
    try:
        with sync_playwright() as playwright:
            executable = _browser_executable(playwright)
            if not executable:
                result = unavailable(context, name, "no Chromium executable is available for Playwright")
                result["details"] = {"required": True, "expected_family": expected_family}
                return result
            browser = playwright.chromium.launch(headless=True, executable_path=executable)
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
            page.on("requestfailed", lambda request: request_failures.append(str(request.url)))
            page.goto(html_path.resolve().as_uri(), wait_until="load")
            browser_result = _browser_probe(page, expected_family=expected_family, probe_text=probe_text)
            browser_version = browser.version
            page.close()
            browser.close()
    except Exception as exc:  # browser failures are explicit gate failures, not silent unavailable results
        issues.append({
            "type": "FONT_LOAD_FAILED",
            "severity": "major",
            "message": f"browser font probe failed: {exc}",
            "evidence_ids": [evidence_id],
        })
        browser_result = {
            "document_fonts_status": "error",
            "font_faces": [],
            "css_font_faces": [],
            "computed_font_families": [],
            "cjk_nodes": [],
            "tofu_suspected": False,
        }
        browser_version = None
        executable = None

    browser_font_faces = browser_result.get("font_faces", [])
    css_font_faces = browser_result.get("css_font_faces", [])
    explicit_font_face = explicit_font_face or any(
        _normalize_family(face.get("family")) == _normalize_family(expected_family)
        for face in css_font_faces
    )
    if not explicit_font_face:
        issues.append({
            "type": "FONT_FACE_NOT_BOUND",
            "severity": "major",
            "message": f"expected family {expected_family!r} is not explicitly bound with @font-face",
            "evidence_ids": [evidence_id],
        })
    matching_loaded_faces = int(browser_result.get("matching_loaded_faces", 0))
    font_loaded = matching_loaded_faces > 0
    if explicit_font_face and not font_loaded:
        issues.append({
            "type": "FONT_LOAD_FAILED",
            "severity": "major",
            "message": f"FontFace for expected family {expected_family!r} did not reach loaded state",
            "evidence_ids": [evidence_id],
        })
    if browser_result.get("tofu_suspected"):
        issues.append({
            "type": "CJK_GLYPH_MISSING",
            "severity": "major",
            "message": "CJK probe shows repeated or missing-glyph bitmap fingerprints",
            "evidence_ids": [evidence_id],
        })
    fallback_suspected = (
        not font_loaded
        and bool(browser_result.get("expected_font_family_used"))
        and not bool(browser_result.get("tofu_suspected"))
    )
    if fallback_suspected:
        issues.append({
            "type": "FONT_FALLBACK_SUSPECTED",
            "severity": "warning",
            "message": "CJK glyphs are visible but the expected FontFace was not loaded",
            "evidence_ids": [evidence_id],
        })

    nodes = browser_result.get("cjk_nodes", [])
    suspected_nodes = [node for node in nodes if node.get("suspected_missing_glyph")]
    if suspected_nodes and not browser_result.get("tofu_suspected"):
        issues.append({
            "type": "CJK_GLYPH_MISSING",
            "severity": "major",
            "message": f"{len(suspected_nodes)} actual CJK text nodes show missing-glyph fingerprints",
            "evidence_ids": [evidence_id],
        })

    details = {
        "required": True,
        "expected_family": expected_family,
        "explicit_font_face": explicit_font_face,
        "font_face_sources": font_faces + css_font_faces,
        "font_loaded": font_loaded,
        "font_asset": asset,
        "document_fonts_status": browser_result.get("document_fonts_status"),
        "font_check": browser_result.get("font_check"),
        "loaded_font_faces": browser_result.get("loaded_font_faces", 0),
        "font_faces": browser_font_faces,
        "computed_font_families": browser_result.get("computed_font_families", []),
        "fallback_suspected": fallback_suspected,
        "cjk_probe": {
            "text": probe_text,
            "passed": not bool(browser_result.get("tofu_suspected")),
            "tofu_suspected": bool(browser_result.get("tofu_suspected")),
            "visible_glyph_count": browser_result.get("visible_glyph_count", 0),
            "same_as_fallback_count": browser_result.get("same_as_fallback_count", 0),
            "unique_glyph_fingerprint_count": browser_result.get("unique_glyph_fingerprint_count", 0),
            "glyphs": browser_result.get("probe_glyphs", []),
        },
        "actual_cjk_nodes": {
            "total": len(nodes),
            "checked": len(nodes),
            "suspected_missing_glyph": len(suspected_nodes),
            "nodes": nodes,
        },
        "browser_runtime": {
            "browser": "Playwright Chromium",
            "executable": executable,
            "version": browser_version,
            "page_errors": page_errors,
            "console_errors": console_errors,
            "request_failures": request_failures,
        },
    }
    runtime_path = context.output_root / "browser_runtime.json"
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text(json.dumps(details["browser_runtime"] | {
        "document_fonts_status": details["document_fonts_status"],
        "expected_family": expected_family,
        "font_faces": browser_font_faces,
        "cjk_probe": details["cjk_probe"],
        "actual_cjk_nodes": details["actual_cjk_nodes"],
        "tofu_suspected": bool(browser_result.get("tofu_suspected")),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    details["browser_runtime_path"] = str(runtime_path)

    blocking = [issue for issue in issues if issue["severity"] in {"major", "critical", "error"}]
    return {
        "status": "ok" if not blocking else "failed",
        "passed": not blocking,
        "metrics": {
            "font_asset_exists": bool(asset["exists"]),
            "explicit_font_face": explicit_font_face,
            "font_loaded": font_loaded,
            "cjk_text_node_count": len(nodes),
            "checked_cjk_node_count": len(nodes),
            "suspected_missing_glyph_node_count": len(suspected_nodes),
            "cjk_glyph_visibility": not bool(browser_result.get("tofu_suspected")),
            "tofu_suspected": bool(browser_result.get("tofu_suspected")),
            "fallback_suspected": fallback_suspected,
        },
        "details": details,
        "issues": issues,
        "evidence_ids": [evidence_id],
        "_evidence": evidence + [evidence_for(runtime_path, evidence_id=f"{evidence_id}-runtime", kind="browser_runtime")],
    }


evaluate_font_visibility.evaluator_name = "font_visibility"
