"""Rendered-slide visual VLM evaluator.

This evaluator deliberately sits after the deterministic rendering gates.  It
judges screenshots produced by a real browser and never treats storyboard or
HTML source as visual evidence.
"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import time
from pathlib import Path
from typing import Any, Callable

from ..runner import EvalContext

VISUAL_PROMPT_VERSION = "visual-slide-v1"
VISUAL_EVALUATOR = "visual_vlm"
VIEWPORT = {"width": 1920, "height": 1080}

DIMENSION_STATUSES: dict[str, set[str]] = {
    "visual_hierarchy": {"clear", "acceptable", "weak", "confusing", "uncertain"},
    "readability": {"good", "acceptable", "dense", "hard_to_read", "uncertain"},
    "visual_relevance": {
        "relevant",
        "partially_relevant",
        "decorative",
        "misleading",
        "uncertain",
    },
    "composition_coherence": {"coherent", "acceptable", "awkward", "fragmented", "uncertain"},
    "pedagogical_visual_value": {"strong", "acceptable", "weak", "misleading", "uncertain"},
    "image_grounding": {
        "grounded",
        "partially_grounded",
        "misgrounded",
        "not_applicable",
        "uncertain",
    },
}

DIMENSION_ISSUE_TYPES = {
    "visual_hierarchy": "VISUAL_HIERARCHY",
    "readability": "VISUAL_READABILITY",
    "visual_relevance": "VISUAL_RELEVANCE",
    "composition_coherence": "VISUAL_COMPOSITION",
    "pedagogical_visual_value": "VISUAL_PEDAGOGY",
    "image_grounding": "IMAGE_GROUNDING",
}

ALLOWED_ISSUE_TYPES = set(DIMENSION_ISSUE_TYPES.values()) | {"EVAL_UNCERTAIN"}
CONFIDENCES = {"high", "medium", "low"}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _read_json(path: Path | None) -> Any:
    if path is None or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _asset_path(context: EvalContext, role: str) -> Path | None:
    try:
        for asset in context.case.assets():
            if asset.role == role:
                path = context.case.resolve_asset(asset)
                return path if path.is_file() else None
    except (AttributeError, OSError, ValueError):
        return None
    return None


def _source_evidence(context: EvalContext, segment: dict[str, Any]) -> list[dict[str, str]]:
    annotation = _read_json(_asset_path(context, "annotation"))
    source = _read_json(_asset_path(context, "source_json"))
    paragraphs = source.get("paragraphs", []) if isinstance(source, dict) else []
    paragraph_by_id = {
        str(item.get("id")): str(item.get("text", ""))
        for item in paragraphs
        if isinstance(item, dict) and item.get("id") is not None
    }
    concept_ids = {str(value) for value in segment.get("knowledge_point_ids", [])}
    concepts = annotation.get("core_concepts", []) if isinstance(annotation, dict) else []
    evidence: list[dict[str, str]] = []
    for concept in concepts:
        if not isinstance(concept, dict) or str(concept.get("id")) not in concept_ids:
            continue
        evidence.append(
            {
                "concept_id": str(concept.get("id")),
                "statement": str(concept.get("statement", ""))[:500],
                "paragraphs": json.dumps(
                    [
                        paragraph_by_id.get(str(paragraph_id), "")[:500]
                        for paragraph_id in concept.get("evidence_paragraphs", [])
                        if paragraph_by_id.get(str(paragraph_id))
                    ],
                    ensure_ascii=False,
                ),
            }
        )
    return evidence


def _compact_element(element: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"id": element.get("id"), "type": element.get("type")}
    for key in ("text", "description", "label", "author", "src", "target", "target_image"):
        if element.get(key) not in (None, ""):
            result[key] = str(element[key])[:600]
    for key in ("title", "content"):
        if element.get(key) not in (None, ""):
            result[key] = str(element[key])[:600]
    if isinstance(element.get("items"), list):
        result["items"] = element["items"][:12]
    return result


def build_slide_context(context: EvalContext, segment: dict[str, Any], slide_number: int) -> dict[str, Any]:
    elements = segment.get("elements", [])
    return {
        "case_id": context.case.case_id,
        "lesson_id": context.case.lesson_id,
        "slide_id": str(segment.get("id", slide_number)),
        "slide_number": slide_number,
        "narration": str(segment.get("narration", ""))[:1800],
        "core_concept_ids": [str(value) for value in segment.get("knowledge_point_ids", [])],
        "visual_type": segment.get("visual_type"),
        "teaching_role": segment.get("teaching_role"),
        "elements": [
            _compact_element(item) for item in elements if isinstance(item, dict)
        ],
        "expected_images": [
            {
                "id": str(item.get("id", "")),
                "description": str(item.get("description", ""))[:500],
                "src": str(item.get("src", "")),
            }
            for item in elements
            if isinstance(item, dict) and item.get("type") == "image"
        ],
        "source_evidence": _source_evidence(context, segment),
    }


def _rubric_path() -> Path:
    return Path(__file__).resolve().parents[1] / "rubrics" / "visual" / "slide_v1.txt"


def _load_rubric() -> str:
    path = _rubric_path()
    return path.read_text(encoding="utf-8")


def _image_part(path: Path) -> dict[str, Any]:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}


def _browser_executable(playwright: Any) -> str | None:
    configured = os.environ.get("T2V_PLAYWRIGHT_EXECUTABLE") or os.environ.get(
        "T2V_BROWSER_EXECUTABLE"
    )
    if configured and Path(configured).is_file():
        return configured
    default = Path(playwright.chromium.executable_path)
    if default.is_file():
        return str(default)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        cached = sorted(
            Path(local_app_data).glob("ms-playwright/chromium-*/chrome-win/chrome.exe"),
            reverse=True,
        )
        if cached:
            return str(cached[0])
    for candidate in (
        Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", ""))
        / "Microsoft/Edge/Application/msedge.exe",
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def _prompt(rubric: str, slide_context: dict[str, Any]) -> str:
    output_shape = {
        name: {
            "status": sorted(statuses),
            "confidence": ["high", "medium", "low"],
            "reason": "short explanation grounded in the screenshot",
            "evidence": [{"region": "where", "observation": "what is visible"}],
        }
        for name, statuses in DIMENSION_STATUSES.items()
    }
    output_shape["issues"] = [
        {
            "type": sorted(ALLOWED_ISSUE_TYPES),
            "severity": ["warning", "major"],
            "summary": "short issue summary",
            "location": "visible region or slide",
            "evidence": [{"region": "where", "observation": "what is visible"}],
        }
    ]
    return (
        "You are the rendered-visual evaluator for an educational slide.\n"
        "Judge the attached Chromium screenshot, not HTML/source syntax.\n"
        "Deterministic checks already cover overflow, overlap, broken resources, tofu, "
        "browser errors, and animation errors: do not invent issues for those.\n"
        "Use the narration, concept IDs, and source evidence only as minimal context. "
        "Do not reward text merely because it appears; judge whether the visible design "
        "supports the stated teaching purpose.\n\n"
        f"RUBRIC:\n{rubric}\n\n"
        "Return one JSON object only, with exactly these six dimension objects and an "
        "optional issues array. Every non-uncertain judgement must include at least one "
        "concrete screenshot evidence item. Never use a total visual score.\n"
        f"OUTPUT SHAPE:\n{json.dumps(output_shape, ensure_ascii=False)}\n\n"
        f"SLIDE CONTEXT:\n{json.dumps(slide_context, ensure_ascii=False, sort_keys=True)}"
    )


def _uncertain_dimension(reason: str) -> dict[str, Any]:
    return {"status": "uncertain", "confidence": "low", "reason": reason, "evidence": []}


def _normalize_dimension(name: str, value: Any) -> tuple[dict[str, Any], bool]:
    if not isinstance(value, dict):
        return _uncertain_dimension("Model did not return a dimension object."), False
    status = str(value.get("status", "uncertain"))
    confidence = str(value.get("confidence", "low"))
    reason = str(value.get("reason", "")).strip()
    evidence = value.get("evidence")
    normalized_evidence = []
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, dict) and str(item.get("region", "")).strip() and str(
                item.get("observation", "")
            ).strip():
                normalized_evidence.append(
                    {
                        "region": str(item["region"])[:200],
                        "observation": str(item["observation"])[:800],
                    }
                )
    valid = status in DIMENSION_STATUSES[name] and confidence in CONFIDENCES and bool(reason)
    if status not in {"uncertain", "not_applicable"} and not normalized_evidence:
        valid = False
    if not valid:
        return _uncertain_dimension(reason or "Model response failed the visual result contract."), False
    return {
        "status": status,
        "confidence": confidence,
        "reason": reason[:1200],
        "evidence": normalized_evidence,
    }, True


def normalize_visual_response(parsed: Any) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    if not isinstance(parsed, dict):
        return {
            **{name: _uncertain_dimension("Model response was not a JSON object.") for name in DIMENSION_STATUSES},
            "issues": [],
        }, ["response_not_object"]
    result: dict[str, Any] = {}
    for name in DIMENSION_STATUSES:
        value, valid = _normalize_dimension(name, parsed.get(name))
        result[name] = value
        if not valid:
            errors.append(f"invalid_{name}")
    model_issues = parsed.get("issues", [])
    result["issues"] = []
    if isinstance(model_issues, list):
        for item in model_issues:
            if not isinstance(item, dict) or str(item.get("type")) not in ALLOWED_ISSUE_TYPES:
                continue
            result["issues"].append(
                {
                    "type": str(item["type"]),
                    "severity": "major" if item.get("severity") == "major" else "warning",
                    "summary": str(item.get("summary") or item.get("message") or item["type"])[:800],
                    "location": str(item.get("location") or "slide")[:200],
                    "evidence": item.get("evidence") if isinstance(item.get("evidence"), list) else [],
                }
            )
    return result, errors


def _automatic_issue(
    *, case_id: str, slide_number: int, dimension: str, value: dict[str, Any], evidence_ids: list[str]
) -> dict[str, Any] | None:
    status = value["status"]
    ordinary = {
        "visual_hierarchy": {"weak", "confusing"},
        "readability": {"dense", "hard_to_read"},
        "visual_relevance": {"partially_relevant", "decorative", "misleading"},
        "composition_coherence": {"awkward", "fragmented"},
        "pedagogical_visual_value": {"weak", "misleading"},
        "image_grounding": {"partially_grounded", "misgrounded"},
    }
    if status not in ordinary.get(dimension, set()):
        if status != "uncertain":
            return None
        return {
            "case_id": case_id,
            "stage": "eval",
            "evaluator": VISUAL_EVALUATOR,
            "type": "EVAL_UNCERTAIN",
            "severity": "minor",
            "message": f"{dimension} was uncertain: {value.get('reason') or 'no reason provided'}",
            "slide": slide_number,
            "evidence_ids": evidence_ids,
            "review_status": "uncertain",
        }
    serious = status in {"confusing", "hard_to_read", "misleading", "misgrounded"}
    return {
        "case_id": case_id,
        "stage": "eval",
        "evaluator": VISUAL_EVALUATOR,
        "type": DIMENSION_ISSUE_TYPES[dimension],
        "severity": "major" if serious else "minor",
        "message": f"{dimension}={status}: {value.get('reason') or 'visual issue'}",
        "slide": slide_number,
        "evidence_ids": evidence_ids,
        "review_status": "unreviewed",
        "evidence": {"dimension": dimension, "status": status, "items": value.get("evidence", [])},
    }


def _render_screenshots(html_path: Path, output_dir: Path) -> tuple[list[Path], dict[str, Any]]:
    """Render every slide in Chromium at the fixed visual-eval viewport."""
    output_dir.mkdir(parents=True, exist_ok=True)
    diagnostics: dict[str, Any] = {
        "viewport": dict(VIEWPORT),
        "page_errors": [],
        "console_errors": [],
        "failed_requests": [],
    }
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - dependency is project-required
        raise RuntimeError("Playwright is required for rendered visual evaluation") from exc

    with sync_playwright() as playwright:
        executable = _browser_executable(playwright)
        if not executable:
            raise RuntimeError("no Chromium-compatible browser executable is available")
        browser = playwright.chromium.launch(headless=True, executable_path=executable)
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=1)
        page.on("pageerror", lambda error: diagnostics["page_errors"].append(str(error)))
        page.on(
            "console",
            lambda message: diagnostics["console_errors"].append(message.text)
            if message.type == "error"
            else None,
        )
        page.on(
            "requestfailed",
            lambda request: diagnostics["failed_requests"].append(
                f"{request.url}: {request.failure or 'request failed'}"
            ),
        )
        page.goto(html_path.as_uri(), wait_until="networkidle", timeout=120_000)
        page.evaluate("document.fonts ? document.fonts.ready : Promise.resolve()")
        page.add_style_tag(
            content="""
            html.visual-vlm-static *, html.visual-vlm-static *::before,
            html.visual-vlm-static *::after { animation: none !important; transition: none !important; }
            html.visual-vlm-static .slide .anim { opacity: 1 !important; visibility: visible !important;
                transform: none !important; }
            html.visual-vlm-static .slide { transition: none !important; }
            """
        )
        slide_count = page.locator(".slide").count()
        if slide_count <= 0:
            raise RuntimeError("candidate HTML contains no .slide elements")
        screenshots: list[Path] = []
        for index in range(slide_count):
            page.evaluate(
                """
                (index) => {
                    document.documentElement.classList.add('visual-vlm-static');
                    const slides = Array.from(document.querySelectorAll('.slide'));
                    slides.forEach((slide, current) => {
                        const active = current === index;
                        slide.classList.toggle('active', active);
                        slide.style.setProperty('opacity', active ? '1' : '0', 'important');
                        slide.style.setProperty('visibility', active ? 'visible' : 'hidden', 'important');
                    });
                }
                """,
                index,
            )
            page.wait_for_timeout(50)
            path = output_dir / f"slide_{index + 1:03d}.png"
            page.screenshot(path=str(path), full_page=False)
            screenshots.append(path)
        browser.close()
    diagnostics["slide_count"] = len(screenshots)
    diagnostics["ok"] = not any(
        diagnostics[key] for key in ("page_errors", "console_errors", "failed_requests")
    )
    return screenshots, diagnostics


class VisualVLMAdapter:
    """One request per rendered slide, with fail-closed parsing and provenance."""

    def __init__(
        self,
        client: Any,
        *,
        max_retries: int = 1,
        max_tokens: int = 1400,
        render_screenshots: Callable[[Path, Path], tuple[list[Path], dict[str, Any]]] | None = None,
    ) -> None:
        self.client = client
        self.max_retries = max(0, int(max_retries))
        self.max_tokens = max_tokens
        self.render_screenshots = render_screenshots or _render_screenshots
        self.output_root: Path | None = None

    def set_output_root(self, output_root: Path) -> None:
        self.output_root = Path(output_root).resolve()

    def _raw_path(self, slide_number: int) -> Path:
        if self.output_root is None:
            raise RuntimeError("visual VLM output root was not configured")
        path = self.output_root / "rendered_visual" / "judge" / f"slide_{slide_number:03d}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _judge_slide(
        self, *, slide_context: dict[str, Any], screenshot: Path, rubric: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        prompt = _prompt(rubric, slide_context)
        prompt_sha256 = _sha256_text(prompt)
        image_sha256 = _sha256_bytes(screenshot.read_bytes())
        context_sha256 = _sha256_text(
            json.dumps(slide_context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        raw_response = ""
        parsed: Any = None
        parse_errors: list[str] = []
        started = time.monotonic()
        attempts = 0
        for attempts in range(1, self.max_retries + 2):
            try:
                parsed, raw_response = self.client.chat(
                    [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                _image_part(screenshot),
                            ],
                        }
                    ],
                    max_tokens=self.max_tokens,
                )
                break
            except Exception as exc:  # noqa: BLE001 - retry is the adapter contract
                parse_errors.append(f"attempt_{attempts}: {type(exc).__name__}: {exc}")
        latency_ms = round((time.monotonic() - started) * 1000, 3)
        if parsed is None:
            normalized, errors = normalize_visual_response(None)
            parse_errors.extend(errors)
        else:
            try:
                normalized, errors = normalize_visual_response(parsed)
                parse_errors.extend(errors)
            except Exception as exc:  # noqa: BLE001 - fail closed on model drift
                normalized, parse_errors = normalize_visual_response(None)
                parse_errors.append(f"normalization: {type(exc).__name__}: {exc}")
        raw_path = self._raw_path(int(slide_context["slide_number"]))
        raw_path.write_text(
            json.dumps(
                {
                    "schema_version": "textbookeval-visual-vlm-v0.1",
                    "case_id": slide_context["case_id"],
                    "slide_id": slide_context["slide_id"],
                    "slide_number": slide_context["slide_number"],
                    "model": getattr(self.client, "model", "unknown"),
                    "provider": "openai-compatible",
                    "model_version": getattr(self.client, "model_version", getattr(self.client, "model", "unknown")),
                    "prompt_version": VISUAL_PROMPT_VERSION,
                    "prompt_sha256": prompt_sha256,
                    "image_sha256": image_sha256,
                    "context_sha256": context_sha256,
                    "temperature": 0,
                    "latency_ms": latency_ms,
                    "attempts": attempts,
                    "retry_count": max(0, attempts - 1),
                    "errors": parse_errors,
                    "raw_response": raw_response,
                    "parsed_response": parsed,
                    "normalized_response": normalized,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return normalized, {
            "prompt_sha256": prompt_sha256,
            "image_sha256": image_sha256,
            "context_sha256": context_sha256,
            "raw_path": raw_path,
            "latency_ms": latency_ms,
            "attempts": attempts,
            "errors": parse_errors,
        }

    def evaluate_case(self, context: EvalContext) -> dict[str, Any]:
        html_path = context.artifact("html")
        storyboard_path = context.artifact("storyboard")
        if html_path is None or not html_path.is_file():
            return _unavailable(context, "candidate HTML is missing")
        if storyboard_path is None or not storyboard_path.is_file():
            return _unavailable(context, "candidate storyboard is missing")
        storyboard = _read_json(storyboard_path)
        segments = storyboard.get("segments", []) if isinstance(storyboard, dict) else []
        if not isinstance(segments, list) or not segments:
            return _unavailable(context, "candidate storyboard contains no segments")
        output_root = self.output_root or context.output_root
        screenshot_dir = output_root / "rendered_visual"
        try:
            screenshots, diagnostics = self.render_screenshots(html_path, screenshot_dir)
        except Exception as exc:  # noqa: BLE001 - unavailable is an explicit evaluator state
            return _unavailable(context, f"browser screenshot generation failed: {exc}")
        html_sha256 = _sha256_bytes(html_path.read_bytes())
        diagnostics_path = screenshot_dir / "browser_diagnostics.json"
        diagnostics_path.write_text(
            json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        diagnostics_id = f"{context.case.case_id}-visual-browser-diagnostics"
        diagnostics_evidence = {
            "evidence_id": diagnostics_id,
            "kind": "browser_runtime_diagnostics",
            "path": str(diagnostics_path.relative_to(output_root)),
        }
        if not diagnostics.get("ok", False):
            return {
                "status": "ok",
                "passed": None,
                "metrics": {"slide_count": len(screenshots), "judged_slide_count": 0, "uncertain_slide_count": len(screenshots)},
                "details": {"required": True, "browser_diagnostics": diagnostics, "slides": [], "provenance": {"provider": "openai-compatible"}},
                "issues": [
                    {
                        "case_id": context.case.case_id,
                        "stage": "eval",
                        "evaluator": VISUAL_EVALUATOR,
                        "type": "EVAL_UNCERTAIN",
                        "severity": "minor",
                        "message": "Deterministic browser diagnostics are not clean; visual VLM was not called.",
                        "evidence_ids": [diagnostics_id],
                        "review_status": "uncertain",
                    }
                ],
                "evidence_ids": [diagnostics_id],
                "_evidence": [diagnostics_evidence],
            }

        rubric = _load_rubric()
        slide_results = []
        issues: list[dict[str, Any]] = []
        evidence_ids: list[str] = [diagnostics_id]
        evidence: list[dict[str, Any]] = [diagnostics_evidence]
        prompt_hashes: list[str] = []
        context_hashes: list[str] = []
        image_hashes: dict[str, str] = {}
        total_latency = 0.0
        serious = False
        for index, screenshot in enumerate(screenshots, start=1):
            segment = segments[index - 1] if index - 1 < len(segments) and isinstance(segments[index - 1], dict) else {"id": index, "elements": []}
            slide_context = build_slide_context(context, segment, index)
            normalized, call = self._judge_slide(slide_context=slide_context, screenshot=screenshot, rubric=rubric)
            screenshot_id = f"{context.case.case_id}-visual-slide-{index:03d}"
            raw_id = f"{screenshot_id}-raw"
            evidence_ids.extend([screenshot_id, raw_id])
            evidence.extend(
                [
                    {
                        "evidence_id": screenshot_id,
                        "kind": "rendered_visual_screenshot",
                        "path": str(screenshot.relative_to(output_root)),
                        "sha256": call["image_sha256"],
                        "slide": index,
                    },
                    {
                        "evidence_id": raw_id,
                        "kind": "model_raw_output",
                        "path": str(call["raw_path"].relative_to(output_root)),
                        "sha256": _sha256_bytes(call["raw_path"].read_bytes()),
                        "slide": index,
                    },
                ]
            )
            slide_issues = []
            for dimension in DIMENSION_STATUSES:
                issue = _automatic_issue(
                    case_id=context.case.case_id,
                    slide_number=index,
                    dimension=dimension,
                    value=normalized[dimension],
                    evidence_ids=[screenshot_id, raw_id],
                )
                if issue is not None:
                    slide_issues.append(issue)
                    issues.append(issue)
                    serious = serious or issue["severity"] == "major"
            for model_issue in normalized.get("issues", []):
                issue = {
                    "case_id": context.case.case_id,
                    "stage": "eval",
                    "evaluator": VISUAL_EVALUATOR,
                    "type": model_issue["type"],
                    "severity": model_issue["severity"],
                    "message": model_issue["summary"],
                    "slide": index,
                    "evidence_ids": [screenshot_id, raw_id],
                    "review_status": "unreviewed",
                    "evidence": {"location": model_issue["location"], "items": model_issue["evidence"]},
                }
                issues.append(issue)
                slide_issues.append(issue)
                serious = serious or issue["severity"] == "major"
            slide_results.append(
                {
                    "slide_id": slide_context["slide_id"],
                    "slide_number": index,
                    "screenshot_path": str(screenshot.relative_to(output_root)),
                    "html_sha256": html_sha256,
                    "viewport": dict(VIEWPORT),
                    "render_commit": context.candidate_commit or "unknown",
                    "context": slide_context,
                    "dimensions": {name: normalized[name] for name in DIMENSION_STATUSES},
                    "issues": slide_issues,
                    "provenance": {
                        "prompt_version": VISUAL_PROMPT_VERSION,
                        "prompt_sha256": call["prompt_sha256"],
                        "image_sha256": call["image_sha256"],
                        "context_sha256": call["context_sha256"],
                        "latency_ms": call["latency_ms"],
                        "retry_count": max(0, call["attempts"] - 1),
                        "raw_path": str(call["raw_path"].relative_to(output_root)),
                        "errors": call["errors"],
                    },
                }
            )
            prompt_hashes.append(call["prompt_sha256"])
            context_hashes.append(call["context_sha256"])
            image_hashes[str(index)] = call["image_sha256"]
            total_latency += float(call["latency_ms"])

        dimension_counts = {
            dimension: {
                status: sum(item["dimensions"][dimension]["status"] == status for item in slide_results)
                for status in sorted(DIMENSION_STATUSES[dimension])
                if any(item["dimensions"][dimension]["status"] == status for item in slide_results)
            }
            for dimension in DIMENSION_STATUSES
        }
        uncertain_count = sum(
            any(item["dimensions"][dimension]["status"] == "uncertain" for dimension in DIMENSION_STATUSES)
            for item in slide_results
        )
        details = {
            "required": True,
            "model": getattr(self.client, "model", "unknown"),
            "provider": "openai-compatible",
            "model_version": getattr(self.client, "model_version", getattr(self.client, "model", "unknown")),
            "prompt_version": VISUAL_PROMPT_VERSION,
            "html": {"path": str(html_path), "sha256": html_sha256},
            "viewport": dict(VIEWPORT),
            "browser_diagnostics": diagnostics,
            "browser_diagnostics_path": str(diagnostics_path.relative_to(output_root)),
            "slides": slide_results,
            "metadata": {
                "prompt_sha256": _sha256_text(rubric),
                "slide_prompt_sha256": prompt_hashes,
                "context_sha256": context_hashes,
                "image_sha256": image_hashes,
            },
            "provenance": {
                "provider": "openai-compatible",
                "model": getattr(self.client, "model", "unknown"),
                "model_version": getattr(self.client, "model_version", getattr(self.client, "model", "unknown")),
                "prompt_version": VISUAL_PROMPT_VERSION,
                "rubric_sha256": _sha256_text(rubric),
                "temperature": 0,
                "slide_count": len(slide_results),
                "total_latency_ms": round(total_latency, 3),
                "retry_count": sum(item["provenance"]["retry_count"] for item in slide_results),
            },
        }
        return {
            "status": "failed" if serious else "ok",
            "passed": not serious,
            "metrics": {
                "slide_count": len(slide_results),
                "judged_slide_count": len(slide_results),
                "uncertain_slide_count": uncertain_count,
                "issue_count": len(issues),
                "dimension_status_counts": dimension_counts,
            },
            "details": details,
            "issues": issues,
            "evidence_ids": evidence_ids,
            "_evidence": evidence,
        }


def _unavailable(context: EvalContext, message: str) -> dict[str, Any]:
    evidence_id = f"{context.case.case_id}-{VISUAL_EVALUATOR}-missing-input"
    return {
        "status": "unavailable",
        "passed": None,
        "metrics": {},
        "details": {"required": True, "reason": message},
        "issues": [
            {
                "case_id": context.case.case_id,
                "stage": "eval",
                "evaluator": VISUAL_EVALUATOR,
                "type": "EVAL_UNCERTAIN",
                "severity": "minor",
                "message": message,
                "evidence_ids": [evidence_id],
                "review_status": "uncertain",
            }
        ],
        "evidence_ids": [evidence_id],
    }


def evaluate_visual_vlm(context: EvalContext) -> dict[str, Any]:
    adapter = context.visual_vlm
    if adapter is None:
        return _unavailable(context, "visual VLM is not configured")
    return adapter.evaluate_case(context)


evaluate_visual_vlm.evaluator_name = VISUAL_EVALUATOR
