"""Deterministic content evaluators for frozen TextbookEval cases.

The first evaluation pass deliberately keeps these checks explainable.  They
compare the candidate storyboard/script with the frozen annotation and source
paragraphs; they do not produce a cross-metric score or call a model.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..runner import EvalContext
from .common import evidence_for, unavailable


_PUNCTUATION = re.compile(r"[^0-9a-zA-Z\u3400-\u9fff+]+")


def _normalize(value: Any) -> str:
    return _PUNCTUATION.sub("", str(value or "").lower())


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _case_asset(context: EvalContext, role: str) -> Path | None:
    for asset in context.case.assets():
        if asset.role == role:
            return context.case.resolve_asset(asset)
    return None


def _load_inputs(context: EvalContext) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    source_path = _case_asset(context, "source_json")
    annotation_path = _case_asset(context, "annotation")
    if source_path is None or annotation_path is None:
        raise FileNotFoundError("source_json and annotation are required for content evaluation")
    source = _load_json(source_path)
    annotation = _load_json(annotation_path)
    storyboard_path = context.artifact("storyboard")
    if storyboard_path is None or not storyboard_path.is_file():
        raise FileNotFoundError("baseline_artifacts.storyboard is required for content evaluation")
    storyboard = _load_json(storyboard_path)
    if not isinstance(source, dict) or not isinstance(annotation, dict):
        raise ValueError("source.json and annotation.json must contain objects")
    if not isinstance(storyboard, dict):
        raise ValueError("storyboard must contain an object")
    return source, annotation, storyboard


def _paragraphs(source: dict[str, Any]) -> dict[str, str]:
    return {
        str(item.get("id")): str(item.get("text") or "")
        for item in source.get("paragraphs", [])
        if isinstance(item, dict) and item.get("id")
    }


def _segment_text(segment: dict[str, Any]) -> str:
    values: list[str] = [str(segment.get("narration") or "")]
    for element in segment.get("elements", []):
        if not isinstance(element, dict):
            continue
        for key in ("text", "label", "description", "title", "content", "quote", "src"):
            value = element.get(key)
            if isinstance(value, str):
                values.append(value)
        items = element.get("items")
        if isinstance(items, list):
            values.extend(
                json.dumps(item, ensure_ascii=False) if isinstance(item, dict) else str(item)
                for item in items
            )
    return " ".join(values)


def _segments(storyboard: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    result = []
    for index, raw in enumerate(storyboard.get("segments", []), start=1):
        if isinstance(raw, dict):
            result.append((str(raw.get("id", index)), _segment_text(raw), raw))
    return result


def _matches(text: str, terms: list[str]) -> list[str]:
    normalized = _normalize(text)
    return [term for term in terms if _normalize(term) and _normalize(term) in normalized]


def _source_evidence(
    paragraphs: dict[str, str], evidence_ids: list[str], terms: list[str]
) -> list[dict[str, str]]:
    records = []
    for paragraph_id in evidence_ids:
        paragraph = paragraphs.get(str(paragraph_id), "")
        matched = _matches(paragraph, terms)
        records.append(
            {
                "paragraph_id": str(paragraph_id),
                "text": paragraph,
                "matched_terms": matched,
            }
        )
    return records


def _shared_shingles(left: str, right: str, size: int = 4) -> int:
    a = _normalize(left)
    b = _normalize(right)
    if len(a) < size or len(b) < size:
        return 0
    return len({a[i : i + size] for i in range(len(a) - size + 1)} & {b[i : i + size] for i in range(len(b) - size + 1)})


def evaluate_source_fidelity(context: EvalContext) -> dict[str, Any]:
    name = "source_fidelity"
    source_path = _case_asset(context, "source_json")
    annotation_path = _case_asset(context, "annotation")
    storyboard_path = context.artifact("storyboard")
    if not all(path and path.is_file() for path in (source_path, annotation_path, storyboard_path)):
        return unavailable(context, name, "source_json, annotation, and storyboard are required")

    source, annotation, storyboard = _load_inputs(context)
    paragraphs = _paragraphs(source)
    segments = _segments(storyboard)
    script_path = context.artifact("script")
    script_text = script_path.read_text(encoding="utf-8", errors="replace") if script_path and script_path.is_file() else ""
    all_text = " ".join(text for _, text, _ in segments) + " " + script_text
    claims = []
    issues: list[dict[str, Any]] = []
    for concept in annotation.get("core_concepts", []):
        if not isinstance(concept, dict):
            continue
        terms = [str(term) for term in concept.get("must_mention_terms", [])]
        matches = _matches(all_text, terms)
        candidate_evidence = [
            {"slide": slide_id, "text": text}
            for slide_id, text, _ in segments
            if _matches(text, terms)
        ]
        if _matches(script_text, terms):
            candidate_evidence.append({"artifact": "script", "text": script_text})
        if len(matches) == len(terms) and terms:
            judgement = "supported"
        elif matches:
            judgement = "partially_supported"
        else:
            judgement = "unsupported"
        record = {
            "claim_id": str(concept.get("id") or "unknown"),
            "generated_claim": " ".join(item[1] for item in segments if _matches(item[1], terms)),
            "source_evidence": _source_evidence(
                paragraphs, [str(item) for item in concept.get("evidence_paragraphs", [])], terms
            ),
            "paragraph_id": [str(item) for item in concept.get("evidence_paragraphs", [])],
            "judgement": judgement,
            "reason": f"matched {len(matches)}/{len(terms)} annotation terms",
            "candidate_evidence": candidate_evidence,
        }
        claims.append(record)
        if judgement == "unsupported":
            issues.append(
                {
                    "stage": "script",
                    "type": "SOURCE_CLAIM_UNSUPPORTED",
                    "severity": "error",
                    "message": f"candidate does not support annotated claim {record['claim_id']}",
                    "element_id": record["claim_id"],
                    "evidence": record,
                }
            )

    image_records = []
    for image in annotation.get("required_images", []):
        if not isinstance(image, dict):
            continue
        image_id = str(image.get("image_id") or "")
        filename = str(image.get("filename") or "")
        serialized = json.dumps(storyboard, ensure_ascii=False)
        used = bool(image_id and _normalize(image_id) in _normalize(serialized)) or bool(
            filename and _normalize(filename) in _normalize(serialized)
        )
        correct = bool(filename and _normalize(filename) in _normalize(serialized))
        near = False
        for slide_id, text, raw_segment in segments:
            segment_serialized = json.dumps(raw_segment, ensure_ascii=False)
            if image_id and _normalize(image_id) not in _normalize(segment_serialized):
                if filename and _normalize(filename) not in _normalize(segment_serialized):
                    continue
            evidence_text = " ".join(
                paragraphs.get(str(paragraph_id), "")
                for paragraph_id in image.get("evidence_paragraphs", [])
            )
            near = _shared_shingles(text, evidence_text) > 0
            if near:
                break
        image_record = {
            "image_id": image_id,
            "filename": filename,
            "used": used,
            "correct_image": correct,
            "near_knowledge_content": bool(near),
            "expected_use": image.get("expected_use"),
        }
        image_records.append(image_record)
        if not correct:
            issues.append(
                {
                    "stage": "storyboard",
                    "type": "REQUIRED_IMAGE_MISSING" if not used else "REQUIRED_IMAGE_MISMATCH",
                    "severity": "error",
                    "message": f"required image {image_id} was not matched to the candidate storyboard",
                    "element_id": image_id,
                    "evidence": image_record,
                }
            )

    source_text = " ".join(paragraphs.values())
    unsupported_additions = []
    for slide_id, text, _ in segments:
        claim = str(text or "").strip()
        if len(_normalize(claim)) < 20 or _shared_shingles(claim, source_text) > 0:
            continue
        unsupported_additions.append(
            {"slide": slide_id, "generated_claim": claim, "reason": "no source overlap detected"}
        )
    for addition in unsupported_additions:
        issues.append(
            {
                "stage": "script",
                "type": "UNSUPPORTED_ADDITION",
                "severity": "warning",
                "message": f"candidate claim on slide {addition['slide']} has no source overlap",
                "slide": int(addition["slide"]) if str(addition["slide"]).isdigit() else None,
                "evidence": addition,
            }
        )

    evidence_ids = [f"{context.case.case_id}-source", f"{context.case.case_id}-annotation"]
    return {
        "status": "failed" if any(item["severity"] == "error" for item in issues) else "ok",
        "passed": not any(item["severity"] == "error" for item in issues),
        "metrics": {
            "evidence_coverage": {
                "supported": sum(item["judgement"] == "supported" for item in claims),
                "partially_supported": sum(item["judgement"] == "partially_supported" for item in claims),
                "unsupported": sum(item["judgement"] == "unsupported" for item in claims),
                "total": len(claims),
            },
            "required_image_coverage": {
                "used": sum(item["used"] for item in image_records),
                "correct": sum(item["correct_image"] for item in image_records),
                "near_knowledge_content": sum(item["near_knowledge_content"] for item in image_records),
                "total": len(image_records),
            },
            "supported_claim_count": sum(item["judgement"] == "supported" for item in claims),
            "partial_claim_count": sum(item["judgement"] == "partially_supported" for item in claims),
            "unsupported_claim_count": sum(item["judgement"] == "unsupported" for item in claims),
            "unsupported_addition_count": len(unsupported_additions),
        },
        "details": {
            "evidence_coverage": claims,
            "required_images": image_records,
            "unsupported_additions": unsupported_additions,
        },
        "issues": issues,
        "evidence_ids": evidence_ids,
        "_evidence": [
            evidence_for(source_path, evidence_id=evidence_ids[0], kind="source_json"),
            evidence_for(annotation_path, evidence_id=evidence_ids[1], kind="annotation"),
            evidence_for(storyboard_path, evidence_id=f"{context.case.case_id}-storyboard", kind="storyboard"),
        ],
    }


evaluate_source_fidelity.evaluator_name = "source_fidelity"


def evaluate_knowledge_grounding(context: EvalContext) -> dict[str, Any]:
    name = "knowledge_grounding"
    source_path = _case_asset(context, "source_json")
    annotation_path = _case_asset(context, "annotation")
    storyboard_path = context.artifact("storyboard")
    if not all(path and path.is_file() for path in (source_path, annotation_path, storyboard_path)):
        return unavailable(context, name, "source_json, annotation, and storyboard are required")

    source, annotation, storyboard = _load_inputs(context)
    paragraphs = _paragraphs(source)
    segments = _segments(storyboard)
    script_path = context.artifact("script")
    script_text = script_path.read_text(encoding="utf-8", errors="replace") if script_path and script_path.is_file() else ""
    concepts = []
    issues: list[dict[str, Any]] = []
    for concept in annotation.get("core_concepts", []):
        if not isinstance(concept, dict):
            continue
        concept_id = str(concept.get("id") or "unknown")
        terms = [str(term) for term in concept.get("must_mention_terms", [])]
        matched = _matches(" ".join(text for _, text, _ in segments) + " " + script_text, terms)
        candidate_evidence = [
            {"slide": slide_id, "text": text}
            for slide_id, text, _ in segments
            if _matches(text, terms)
        ]
        if _matches(script_text, terms):
            candidate_evidence.append({"artifact": "script", "text": script_text})
        if not matched:
            status = "missing"
        elif len(matched) == len(terms):
            status = "covered"
        else:
            status = "partially_covered"
        record = {
            "concept_id": concept_id,
            "expected": concept.get("statement"),
            "evidence": _source_evidence(
                paragraphs, [str(item) for item in concept.get("evidence_paragraphs", [])], terms
            ),
            "candidate_evidence": candidate_evidence,
            "status": status,
            "reason": f"matched {len(matched)}/{len(terms)} required terms",
        }
        concepts.append(record)
        if status in {"missing", "incorrect"}:
            issues.append(
                {
                    "stage": "script",
                    "type": f"KNOWLEDGE_{status.upper()}",
                    "severity": "error",
                    "message": f"concept {concept_id} is {status}",
                    "element_id": concept_id,
                    "evidence": record,
                }
            )

    misconceptions = []
    candidate_text = " ".join(text for _, text, _ in segments) + " " + script_text
    for misconception in annotation.get("misconceptions", []):
        if not isinstance(misconception, dict):
            continue
        wrong_claim = str(misconception.get("wrong_claim") or "")
        introduced = bool(wrong_claim and _normalize(wrong_claim) in _normalize(candidate_text))
        record = {
            "misconception_id": misconception.get("id"),
            "wrong_claim": wrong_claim,
            "introduced": introduced,
            "candidate_evidence": candidate_text if introduced else None,
            "reason": "exact wrong claim found in candidate" if introduced else "not detected",
        }
        misconceptions.append(record)
        if introduced:
            issues.append(
                {
                    "stage": "script",
                    "type": "INTRODUCED_MISCONCEPTION",
                    "severity": "error",
                    "message": f"candidate introduces misconception {misconception.get('id')}",
                    "element_id": str(misconception.get("id") or ""),
                    "evidence": record,
                }
            )

    counts = {status: sum(item["status"] == status for item in concepts) for status in (
        "covered", "partially_covered", "missing", "incorrect"
    )}
    evidence_ids = [f"{context.case.case_id}-annotation", f"{context.case.case_id}-storyboard"]
    return {
        "status": "failed" if issues else "ok",
        "passed": not issues,
        "metrics": {
            "concept_count": len(concepts),
            "concept_coverage": counts["covered"] / len(concepts) if concepts else None,
            "covered_count": counts["covered"],
            "partially_covered_count": counts["partially_covered"],
            "missing_count": counts["missing"],
            "incorrect_count": counts["incorrect"],
            "introduced_misconception_count": sum(item["introduced"] for item in misconceptions),
        },
        "details": {
            "concepts": concepts,
            "missing_concepts": [item["concept_id"] for item in concepts if item["status"] == "missing"],
            "incorrect_concepts": [item["concept_id"] for item in concepts if item["status"] == "incorrect"],
            "introduced_misconceptions": misconceptions,
        },
        "issues": issues,
        "evidence_ids": evidence_ids,
        "_evidence": [
            evidence_for(annotation_path, evidence_id=evidence_ids[0], kind="annotation"),
            evidence_for(storyboard_path, evidence_id=evidence_ids[1], kind="storyboard"),
        ],
    }


evaluate_knowledge_grounding.evaluator_name = "knowledge_grounding"
