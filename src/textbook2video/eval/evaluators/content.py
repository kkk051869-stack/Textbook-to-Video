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

# These aliases are deliberately small and reviewable.  They are semantic
# evidence links, not a replacement for a general-purpose language model.
_TERM_ALIASES: dict[str, tuple[str, ...]] = {
    "行业再造": ("重塑业态",),
}

# The frozen rubric for c004 scores the four must-mention terms below, while
# its statement also contains two broader outcomes.  Keep that limitation in
# the result rather than changing the frozen annotation or penalising the
# candidate for terms that were never part of the scoring list.
_RUBRIC_COVERAGE_HINTS: dict[str, dict[str, Any]] = {
    "c004": {
        "unscored_expected_phrases": ["企业形态", "公共服务供给"],
        "reason": "annotation must_mention_terms do not score these statement phrases",
    }
}


def _normalize(value: Any) -> str:
    return _PUNCTUATION.sub("", str(value or "").lower())


def _normalized_with_spans(value: str) -> tuple[str, list[tuple[int, int]]]:
    """Return normalized text and source spans for explainable evidence."""
    normalized: list[str] = []
    spans: list[tuple[int, int]] = []
    for index, character in enumerate(str(value or "")):
        part = _normalize(character)
        for item in part:
            normalized.append(item)
            spans.append((index, index + 1))
    return "".join(normalized), spans


def _phrase_from_normalized(text: str, fragment: str) -> str:
    normalized, spans = _normalized_with_spans(text)
    start = normalized.find(fragment)
    if start < 0 or not fragment:
        return fragment
    end = start + len(fragment) - 1
    return text[spans[start][0] : spans[end][1]]


def _subsequence_with_small_gaps(haystack: str, needle: str, max_gap: int = 2) -> str | None:
    """Find a term with a short modifier inserted between its characters."""
    if len(needle) < 3:
        return None
    cursor = 0
    positions: list[int] = []
    for character in needle:
        position = haystack.find(character, cursor)
        if position < 0:
            return None
        if positions and position - positions[-1] - 1 > max_gap:
            return None
        positions.append(position)
        cursor = position + 1
    return haystack[positions[0] : positions[-1] + 1]


def _longest_common_substring(left: str, right: str) -> str:
    if not left or not right:
        return ""
    previous = [""] * (len(right) + 1)
    best = ""
    for left_character in left:
        current = [""] * (len(right) + 1)
        for index, right_character in enumerate(right, start=1):
            if left_character == right_character:
                current[index] = previous[index - 1] + left_character
                if len(current[index]) > len(best):
                    best = current[index]
        previous = current
    return best


def _term_match(text: str, expected: str) -> dict[str, Any]:
    """Classify one expected term with traceable candidate evidence."""
    expected_normalized = _normalize(expected)
    candidate_normalized, _ = _normalized_with_spans(text)
    if not expected_normalized:
        return {
            "expected_term": expected,
            "matched_candidate_phrase": None,
            "match_type": "none",
            "confidence": 0.0,
            "reason": "empty expected term",
        }
    if expected_normalized in candidate_normalized:
        phrase = _phrase_from_normalized(text, expected_normalized)
        return {
            "expected_term": expected,
            "matched_candidate_phrase": phrase,
            "match_type": "exact",
            "confidence": 1.0,
            "reason": "normalized expected term occurs in candidate text",
        }

    for alias in _TERM_ALIASES.get(expected, ()):
        alias_normalized = _normalize(alias)
        if alias_normalized and alias_normalized in candidate_normalized:
            return {
                "expected_term": expected,
                "matched_candidate_phrase": _phrase_from_normalized(text, alias_normalized),
                "match_type": "semantic_alias",
                "confidence": 0.8,
                "reason": f"reviewed semantic alias: {alias}",
            }

    modified = _subsequence_with_small_gaps(candidate_normalized, expected_normalized)
    if modified and modified != expected_normalized:
        return {
            "expected_term": expected,
            "matched_candidate_phrase": _phrase_from_normalized(text, modified),
            "match_type": "modifier_tolerant",
            "confidence": 0.9,
            "reason": "expected term characters occur in order with a short candidate modifier",
        }

    common = _longest_common_substring(expected_normalized, candidate_normalized)
    minimum = max(4, (len(expected_normalized) + 1) // 2)
    if len(common) >= minimum and len(common) < len(expected_normalized):
        return {
            "expected_term": expected,
            "matched_candidate_phrase": _phrase_from_normalized(text, common),
            "match_type": "partial_subphrase",
            "confidence": 0.6,
            "reason": "candidate contains a substantial traceable subphrase of the expected term",
        }
    return {
        "expected_term": expected,
        "matched_candidate_phrase": None,
        "match_type": "none",
        "confidence": 0.0,
        "reason": "no exact, alias, modifier-tolerant, or substantial subphrase match",
    }


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
    return [term for term in terms if _term_match(text, term)["match_type"] != "none"]


def _match_details(text: str, terms: list[str]) -> list[dict[str, Any]]:
    return [_term_match(text, term) for term in terms]


def _match_summary(text: str, terms: list[str]) -> tuple[list[str], list[dict[str, Any]]]:
    details = _match_details(text, terms)
    matched = [item["expected_term"] for item in details if item["match_type"] != "none"]
    return matched, details


def _source_evidence(
    paragraphs: dict[str, str], evidence_ids: list[str], terms: list[str]
) -> list[dict[str, Any]]:
    records = []
    for paragraph_id in evidence_ids:
        paragraph = paragraphs.get(str(paragraph_id), "")
        matched = _matches(paragraph, terms)
        records.append(
            {
                "paragraph_id": str(paragraph_id),
                "text": paragraph,
                "matched_terms": matched,
                "term_matches": _match_details(paragraph, terms),
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
    rubric_coverage_warnings: list[dict[str, Any]] = []
    for concept in annotation.get("core_concepts", []):
        if not isinstance(concept, dict):
            continue
        terms = [str(term) for term in concept.get("must_mention_terms", [])]
        matches, term_matches = _match_summary(all_text, terms)
        full_matches = [
            item for item in term_matches
            if item["match_type"] in {"exact", "semantic_alias", "modifier_tolerant"}
        ]
        partial_matches = [item for item in term_matches if item["match_type"] == "partial_subphrase"]
        candidate_evidence = [
            {"slide": slide_id, "text": text}
            for slide_id, text, _ in segments
            if _matches(text, terms)
        ]
        if _matches(script_text, terms):
            candidate_evidence.append({"artifact": "script", "text": script_text})
        if len(full_matches) == len(terms) and terms:
            judgement = "supported"
        elif full_matches or partial_matches:
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
            "reason": (
                f"matched {len(full_matches)}/{len(terms)} annotation terms"
                + (f" with {len(partial_matches)} partial subphrase evidence" if partial_matches else "")
            ),
            "candidate_evidence": candidate_evidence,
            "term_matches": term_matches,
        }
        hint = _RUBRIC_COVERAGE_HINTS.get(str(concept.get("id") or ""))
        if hint:
            record["rubric_coverage_warning"] = hint
            rubric_coverage_warnings.append({"claim_id": record["claim_id"], **hint})
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
            "rubric_coverage_warnings": rubric_coverage_warnings,
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
    rubric_coverage_warnings: list[dict[str, Any]] = []
    for concept in annotation.get("core_concepts", []):
        if not isinstance(concept, dict):
            continue
        concept_id = str(concept.get("id") or "unknown")
        terms = [str(term) for term in concept.get("must_mention_terms", [])]
        matched, term_matches = _match_summary(
            " ".join(text for _, text, _ in segments) + " " + script_text,
            terms,
        )
        full_matches = [
            item for item in term_matches
            if item["match_type"] in {"exact", "semantic_alias", "modifier_tolerant"}
        ]
        partial_matches = [item for item in term_matches if item["match_type"] == "partial_subphrase"]
        candidate_evidence = [
            {"slide": slide_id, "text": text}
            for slide_id, text, _ in segments
            if _matches(text, terms)
        ]
        if _matches(script_text, terms):
            candidate_evidence.append({"artifact": "script", "text": script_text})
        if not matched:
            status = "missing"
        elif len(full_matches) == len(terms):
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
            "reason": (
                f"matched {len(full_matches)}/{len(terms)} required terms"
                + (f" with {len(partial_matches)} partial subphrase evidence" if partial_matches else "")
            ),
            "term_matches": term_matches,
        }
        hint = _RUBRIC_COVERAGE_HINTS.get(concept_id)
        if hint:
            record["rubric_coverage_warning"] = hint
            rubric_coverage_warnings.append({"concept_id": concept_id, **hint})
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
            "rubric_coverage_warnings": rubric_coverage_warnings,
        },
        "issues": issues,
        "evidence_ids": evidence_ids,
        "_evidence": [
            evidence_for(annotation_path, evidence_id=evidence_ids[0], kind="annotation"),
            evidence_for(storyboard_path, evidence_id=evidence_ids[1], kind="storyboard"),
        ],
    }


evaluate_knowledge_grounding.evaluator_name = "knowledge_grounding"
