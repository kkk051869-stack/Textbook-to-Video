"""Explainable pedagogy checks for frozen TextbookEval cases.

This evaluator deliberately stops at observable teaching structure.  It does
not claim to measure whether a student learned the lesson and it does not
produce a single pedagogy score.  Frozen cases in the first pilot release do
not carry explicit learning-objective or prerequisite fields, so the
objective dimension uses the annotated core concepts as a clearly labelled
proxy and prerequisite checks remain ``not_applicable`` until a relation is
present in the input.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..runner import EvalContext
from .common import evidence_for, unavailable
from .content import (
    _case_asset,
    _load_json,
    _matches,
    _normalized_with_spans,
    _normalize,
    _paragraphs,
    _segments,
    _source_evidence,
    _term_match,
)


RULE_VERSION = "pedagogy-v0.1"
_EXAMPLE_MARKERS = ("例如", "比如", "案例", "实例", "如图", "example", "case")
_PRODUCTIVE_MARKERS = (
    "回顾",
    "总结",
    "因此",
    "应用",
    "实践",
    "例如",
    "比如",
    "recap",
    "summary",
    "application",
)
_NEGATION_MARKERS = ("不是", "并非", "而非", "不应", "不能", "避免", "错误", "区别")
_ROLE_MARKERS = {
    "definition": ("定义", "是指", "本质", "概念", "what is", "definition"),
    "problem": ("问题", "挑战", "短板", "瓶颈", "误区", "problem", "challenge"),
    "example": _EXAMPLE_MARKERS,
    "application": ("应用", "实践", "推动", "用于", "场景", "application", "practice"),
    "solution": ("路径", "方法", "解决", "需要", "加强", "提升", "补齐", "solution"),
    "recap": ("总结", "回顾", "最后", "总之", "recap", "summary"),
}


def parse_pedagogy_judge(value: Any) -> dict[str, Any]:
    """Validate an optional structured LLM judgement without hard judging.

    The first implementation does not invoke an LLM, but this small parser
    keeps a future judge fail-closed: malformed or evidence-free output is
    represented as ``uncertain`` instead of becoming a deterministic result.
    """
    if not isinstance(value, dict):
        return {
            "status": "uncertain",
            "confidence": "low",
            "evidence": [],
            "reason": "judge output is not an object",
            "uncertainty": "malformed_output",
        }
    status = value.get("status")
    confidence = value.get("confidence")
    evidence = value.get("evidence")
    allowed = {
        "covered", "partially_covered", "missing", "satisfied", "partial", "violated",
        "not_applicable", "reasonable", "questionable", "problematic",
        "directly_relevant", "partially_relevant", "weakly_relevant", "irrelevant",
        "handled", "avoided", "not_addressed", "introduced", "aligned",
        "partially_aligned", "misaligned", "uncertain",
    }
    if status not in allowed or confidence not in {"high", "medium", "low"} or not isinstance(evidence, list):
        return {
            "status": "uncertain",
            "confidence": "low",
            "evidence": evidence if isinstance(evidence, list) else [],
            "reason": "judge output is missing a valid status, confidence, or evidence array",
            "uncertainty": "missing_required_fields",
        }
    valid_evidence = [
        item for item in evidence
        if isinstance(item, dict) and item.get("slide") is not None and isinstance(item.get("text"), str)
    ]
    if not valid_evidence:
        return {
            "status": "uncertain",
            "confidence": "low",
            "evidence": [],
            "reason": "judge output has no usable slide/text evidence",
            "uncertainty": "missing_evidence",
        }
    return {
        "status": status,
        "confidence": confidence,
        "evidence": valid_evidence,
        "reason": str(value.get("reason") or ""),
        "uncertainty": value.get("uncertainty"),
    }


def _sha256(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_inputs(context: EvalContext) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Path]]:
    source_path = _case_asset(context, "source_json")
    annotation_path = _case_asset(context, "annotation")
    storyboard_path = context.artifact("storyboard")
    heldout_path = _case_asset(context, "heldout_questions")
    required = (source_path, annotation_path, storyboard_path)
    if not all(path is not None and path.is_file() for path in required):
        raise FileNotFoundError("source_json, annotation, and storyboard are required")
    source = _load_json(source_path)
    annotation = _load_json(annotation_path)
    storyboard = _load_json(storyboard_path)
    if not isinstance(source, dict) or not isinstance(annotation, dict) or not isinstance(storyboard, dict):
        raise ValueError("pedagogy inputs must be JSON objects")
    questions: list[dict[str, Any]] = []
    if heldout_path is not None and heldout_path.is_file():
        heldout = _load_json(heldout_path)
        if isinstance(heldout, dict):
            heldout = heldout.get("questions", heldout.get("heldout_questions", []))
        if isinstance(heldout, list):
            questions = [item for item in heldout if isinstance(item, dict)]
    paths = {"source": source_path, "annotation": annotation_path, "storyboard": storyboard_path}
    if heldout_path is not None:
        paths["heldout_questions"] = heldout_path
    return source, annotation, storyboard, questions, paths


def _script_text(context: EvalContext) -> str:
    path = context.artifact("script")
    return path.read_text(encoding="utf-8", errors="replace") if path and path.is_file() else ""


def _concepts(annotation: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in annotation.get("core_concepts", []) if isinstance(item, dict)]


def _concept_map(annotation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("id")): item
        for item in _concepts(annotation)
        if item.get("id") is not None
    }


def _concept_terms(concept: dict[str, Any]) -> list[str]:
    terms = concept.get("must_mention_terms", concept.get("terms", []))
    return [str(term) for term in terms if str(term).strip()]


def _full_matches(text: str, terms: list[str]) -> list[dict[str, Any]]:
    matches = [_term_match(text, term) for term in terms]
    return [item for item in matches if item["match_type"] in {"exact", "semantic_alias", "modifier_tolerant"}]


def _concept_evidence(
    concept: dict[str, Any], segments: list[tuple[str, str, dict[str, Any]]], script: str
) -> dict[str, Any]:
    terms = _concept_terms(concept)
    term_matches = [_term_match(" ".join(text for _, text, _ in segments) + " " + script, term) for term in terms]
    full = [item for item in term_matches if item["match_type"] in {"exact", "semantic_alias", "modifier_tolerant"}]
    partial = [item for item in term_matches if item["match_type"] == "partial_subphrase"]
    candidate = [
        {"slide": slide, "text": text}
        for slide, text, _ in segments
        if _matches(text, terms)
    ]
    if _matches(script, terms):
        candidate.append({"artifact": "script", "text": script})
    if not terms or not full and not partial:
        status = "missing"
    elif len(full) == len(terms):
        status = "covered"
    else:
        status = "partially_covered"
    return {
        "concept_id": str(concept.get("id") or "unknown"),
        "expected": concept.get("statement"),
        "matched_terms": [item["expected_term"] for item in full + partial],
        "term_matches": term_matches,
        "candidate_evidence": candidate,
        "status": status,
        "reason": f"matched {len(full)}/{len(terms)} required terms"
        + (f" with {len(partial)} partial term matches" if partial else ""),
    }


def _objective_specs(annotation: dict[str, Any], concepts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    explicit = annotation.get("learning_objectives") or annotation.get("objectives")
    if isinstance(explicit, list) and explicit:
        return [item for item in explicit if isinstance(item, dict)], "explicit"
    # The frozen v0.1 annotation has no objective list.  Core concepts are
    # the narrowest available proxy and are never presented as explicit goals.
    return [
        {
            "id": str(concept.get("id") or f"concept-{index}"),
            "statement": concept.get("statement"),
            "concept_ids": [str(concept.get("id"))],
            "_proxy": True,
        }
        for index, concept in enumerate(concepts, start=1)
    ], "core_concepts_proxy"


def _objective_concept_ids(item: dict[str, Any], concept_map: dict[str, dict[str, Any]]) -> list[str]:
    values: list[Any] = []
    for key in ("concept_ids", "matched_concepts", "knowledge_point_ids", "targets", "target_concepts"):
        value = item.get(key)
        if isinstance(value, list):
            values.extend(value)
        elif value is not None:
            values.append(value)
    ids = [str(value) for value in values if str(value) in concept_map]
    if ids:
        return list(dict.fromkeys(ids))
    item_id = str(item.get("id") or item.get("objective_id") or "")
    return [item_id] if item_id in concept_map else []


def _evaluate_objectives(
    annotation: dict[str, Any], concepts: list[dict[str, Any]], concept_records: dict[str, dict[str, Any]],
    segments: list[tuple[str, str, dict[str, Any]]], script: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    specs, source = _objective_specs(annotation, concepts)
    concept_map = _concept_map(annotation)
    items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for index, objective in enumerate(specs, start=1):
        objective_id = str(objective.get("objective_id") or objective.get("id") or f"objective-{index:03d}")
        ids = _objective_concept_ids(objective, concept_map)
        if not ids and objective.get("must_mention_terms"):
            terms = [str(term) for term in objective["must_mention_terms"]]
            matched = _full_matches(" ".join(text for _, text, _ in segments) + " " + script, terms)
            status = "covered" if len(matched) == len(terms) else "partially_covered" if matched else "missing"
            record = {
                "objective_id": objective_id,
                "expected": objective.get("statement"),
                "matched_concepts": [],
                "candidate_evidence": [
                    {"slide": slide, "text": text}
                    for slide, text, _ in segments
                    if _matches(text, terms)
                ],
                "status": status,
                "reason": f"matched {len(matched)}/{len(terms)} objective terms",
                "objective_source": source,
            }
        else:
            records = [concept_records[item] for item in ids if item in concept_records]
            covered = sum(item["status"] == "covered" for item in records)
            partial = sum(item["status"] == "partially_covered" for item in records)
            missing = sum(item["status"] == "missing" for item in records)
            status = "covered" if records and covered == len(records) else "partially_covered" if covered or partial else "missing"
            candidate = [evidence for item in records for evidence in item["candidate_evidence"]]
            required_example = bool(objective.get("requires_example") or objective.get("requires_application"))
            required_assessment = bool(objective.get("requires_assessment"))
            if status == "covered" and required_example and not _example_segments_for_ids(ids, segments):
                status = "partially_covered"
            record = {
                "objective_id": objective_id,
                "expected": objective.get("statement"),
                "matched_concepts": ids,
                "candidate_evidence": candidate,
                "status": status,
                "reason": (
                    f"{covered}/{len(records)} mapped concepts fully covered; "
                    f"{partial} partial; {missing} missing"
                    + ("; required example/application not found" if required_example and not _example_segments_for_ids(ids, segments) else "")
                    + ("; assessment requirement is recorded but not available" if required_assessment else "")
                ),
                "objective_source": source,
                "requirements": {
                    "example_or_application": required_example,
                    "assessment": required_assessment,
                },
            }
        items.append(record)
        if status in {"partially_covered", "missing"}:
            issues.append(
                {
                    "stage": "eval",
                    "type": "PEDAGOGY_OBJECTIVE_GAP",
                    "severity": "warning",
                    "message": f"objective {objective_id} is {status}",
                    "element_id": objective_id,
                    "evidence": record,
                }
            )
    counts = {status: sum(item["status"] == status for item in items) for status in ("covered", "partially_covered", "missing")}
    return {
        "status": "ok",
        "items": items,
        "summary": {"objective_source": source, **counts, "total": len(items)},
        "reason": "objective coverage uses explicit objectives" if source == "explicit" else "no frozen objective list; core concepts used as a labelled proxy",
    }, issues


def _relation_specs(annotation: dict[str, Any], concepts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    relations: list[Any] = []
    for key in ("prerequisite_relations", "prerequisites", "prerequisite_graph"):
        if isinstance(annotation.get(key), list):
            relations.extend(annotation[key])
    for concept in concepts:
        value = concept.get("prerequisites")
        if isinstance(value, list):
            for prerequisite in value:
                relations.append({"prerequisite": prerequisite, "dependent": concept.get("id")})
    result = []
    for item in relations:
        if isinstance(item, str):
            continue
        if not isinstance(item, dict):
            continue
        prerequisite = item.get("prerequisite") or item.get("prerequisite_concept_id") or item.get("source")
        dependent = item.get("dependent") or item.get("dependent_concept") or item.get("target") or item.get("concept_id")
        if prerequisite is not None and dependent is not None:
            result.append({"prerequisite": str(prerequisite), "dependent": str(dependent)})
    return result


def _first_occurrence(concept: dict[str, Any], segments: list[tuple[str, str, dict[str, Any]]]) -> dict[str, Any] | None:
    for key in ("first_explained_slide", "explained_at_slide"):
        if concept.get(key) is not None:
            return {"slide": concept[key], "position": None, "source": "annotation"}
    terms = _concept_terms(concept)
    for position, (slide, text, _) in enumerate(segments):
        if _matches(text, terms):
            return {"slide": int(slide) if str(slide).isdigit() else slide, "position": position, "source": "storyboard"}
    return None


def _evaluate_prerequisites(annotation: dict[str, Any], concepts: list[dict[str, Any]], segments: list[tuple[str, str, dict[str, Any]]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    relations = _relation_specs(annotation, concepts)
    if not relations:
        return {
            "status": "not_applicable",
            "items": [],
            "summary": {"status": "not_applicable", "relation_count": 0, "satisfied": 0, "partial": 0, "violated": 0},
            "reason": "frozen annotation contains no prerequisite relation",
        }, []
    cmap = _concept_map(annotation)
    items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for relation in relations:
        prerequisite = cmap.get(relation["prerequisite"])
        dependent = cmap.get(relation["dependent"])
        before = _first_occurrence(prerequisite, segments) if prerequisite else None
        after = _first_occurrence(dependent, segments) if dependent else None
        if after is None:
            status = "not_applicable"
            reason = "dependent concept is not used in the candidate"
        elif before is None:
            status = "violated"
            reason = "dependent concept appears without an observable prerequisite explanation"
        elif before.get("position") is not None and after.get("position") is not None and before["position"] <= after["position"]:
            status = "satisfied"
            reason = "prerequisite first occurs before dependent concept"
        elif before.get("slide") == after.get("slide"):
            status = "partial"
            reason = "prerequisite and dependent first occur on the same slide"
        else:
            status = "violated"
            reason = "dependent concept first occurs before prerequisite"
        record = {
            "prerequisite": relation["prerequisite"],
            "dependent_concept": relation["dependent"],
            "first_explained": before,
            "first_used": after,
            "status": status,
            "reason": reason,
        }
        items.append(record)
        if status == "violated":
            issues.append({
                "stage": "eval",
                "type": "PEDAGOGY_PREREQUISITE_GAP",
                "severity": "error",
                "message": f"prerequisite {relation['prerequisite']} precedes {relation['dependent']}: {reason}",
                "element_id": relation["dependent"],
                "evidence": record,
            })
    counts = {status: sum(item["status"] == status for item in items) for status in ("satisfied", "partial", "violated", "not_applicable")}
    return {"status": "ok", "items": items, "summary": {"relation_count": len(items), **counts}}, issues


def _role_for_segment(raw: dict[str, Any], text: str) -> list[str]:
    explicit = raw.get("teaching_role") or raw.get("role") or raw.get("phase")
    if isinstance(explicit, str) and explicit.strip():
        return [explicit.strip()]
    normalized = str(text).lower()
    return [role for role, markers in _ROLE_MARKERS.items() if any(marker.lower() in normalized for marker in markers)]


def _evaluate_ordering(concepts: list[dict[str, Any]], segments: list[tuple[str, str, dict[str, Any]]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for concept in concepts:
        terms = _concept_terms(concept)
        occurrences = []
        for index, (slide, text, raw) in enumerate(segments):
            if _matches(text, terms):
                occurrences.append({"slide": int(slide) if str(slide).isdigit() else slide, "position": index, "roles": _role_for_segment(raw, text), "text": text})
        roles = [role for occurrence in occurrences for role in occurrence["roles"]]
        inversion = False
        inversion_reason = None
        if "solution" in roles and "problem" in roles:
            first_solution = roles.index("solution")
            first_problem = roles.index("problem")
            if first_solution < first_problem:
                inversion = True
                inversion_reason = "solution appears before problem"
        if "application" in roles and "definition" in roles:
            first_application = roles.index("application")
            first_definition = roles.index("definition")
            if first_application < first_definition:
                inversion = True
                inversion_reason = "application appears before definition"
        status = "questionable" if inversion and len(occurrences) < 2 else "problematic" if inversion else "reasonable"
        record = {
            "concept_id": str(concept.get("id") or "unknown"),
            "ordering": status,
            "slides": [item["slide"] for item in occurrences],
            "roles": roles,
            "evidence": [{"slide": item["slide"], "text": item["text"], "roles": item["roles"]} for item in occurrences],
            "reason": inversion_reason or ("no deterministic teaching-order inversion detected" if occurrences else "concept has no observable candidate occurrence"),
        }
        items.append(record)
        if status in {"questionable", "problematic"}:
            issues.append({
                "stage": "eval",
                "type": "PEDAGOGY_ORDERING",
                "severity": "error" if status == "problematic" else "warning",
                "message": f"concept {record['concept_id']} ordering is {status}",
                "element_id": record["concept_id"],
                "evidence": record,
            })
    counts = {status: sum(item["ordering"] == status for item in items) for status in ("reasonable", "questionable", "problematic")}
    return {"status": "ok", "items": items, "summary": {**counts, "total": len(items), "role_metadata": "explicit_or_lexical"}}, issues


def _example_segments_for_ids(ids: list[str], segments: list[tuple[str, str, dict[str, Any]]]) -> list[dict[str, Any]]:
    # This helper is intentionally structural.  It never treats an arbitrary
    # slide as an example solely because it contains a concept term.
    records = []
    for slide, text, raw in segments:
        serialized = json.dumps(raw, ensure_ascii=False)
        element_types = [str(element.get("type", "")).lower() for element in raw.get("elements", []) if isinstance(element, dict)]
        explicit = any(key in raw for key in ("example", "examples", "application")) or any(item in {"example", "case", "application"} for item in element_types)
        lexical = any(marker.lower() in text.lower() for marker in _EXAMPLE_MARKERS)
        if explicit or lexical:
            records.append({"slide": slide, "text": text, "raw": raw, "explicit": explicit, "lexical": lexical, "ids": ids, "serialized": serialized})
    return records


def _shared_overlap(left: str, right: str) -> float:
    a = _normalize(left)
    b = _normalize(right)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    size = 4
    left_shingles = {a[i : i + size] for i in range(max(0, len(a) - size + 1))}
    right_shingles = {b[i : i + size] for i in range(max(0, len(b) - size + 1))}
    return len(left_shingles & right_shingles) / max(1, min(len(left_shingles), len(right_shingles)))


def _evaluate_examples(
    concepts: list[dict[str, Any]], segments: list[tuple[str, str, dict[str, Any]]], paragraphs: dict[str, str]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for concept in concepts:
        concept_id = str(concept.get("id") or "unknown")
        terms = _concept_terms(concept)
        source_text = " ".join(paragraphs.get(str(item), "") for item in concept.get("evidence_paragraphs", []))
        for example in _example_segments_for_ids([concept_id], segments):
            if not (_matches(example["text"], terms) or concept_id in [str(item) for item in example["raw"].get("knowledge_point_ids", [])]):
                continue
            term_overlap = len(_full_matches(example["text"], terms))
            source_overlap = _shared_overlap(example["text"], source_text)
            if term_overlap == len(terms) and source_overlap > 0:
                status = "directly_relevant"
                reason = "example shares the concept terms and source evidence"
            elif term_overlap or source_overlap > 0:
                status = "partially_relevant"
                reason = "example has partial concept or source-evidence overlap"
            else:
                status = "weakly_relevant"
                reason = "example marker found but concept/source overlap is weak"
            record = {"concept_id": concept_id, "slide": example["slide"], "example_text": example["text"], "status": status, "reason": reason, "source_evidence": _source_evidence(paragraphs, [str(item) for item in concept.get("evidence_paragraphs", [])], terms)}
            items.append(record)
            if status == "weakly_relevant":
                issues.append({"stage": "eval", "type": "PEDAGOGY_EXAMPLE_IRRELEVANT", "severity": "warning", "message": f"example on slide {example['slide']} is weakly relevant to {concept_id}", "slide": int(example["slide"]) if str(example["slide"]).isdigit() else None, "element_id": concept_id, "evidence": record})
    if not items:
        return {"status": "not_applicable", "items": [], "summary": {"status": "not_applicable", "example_count": 0}}, issues
    counts = {status: sum(item["status"] == status for item in items) for status in ("directly_relevant", "partially_relevant", "weakly_relevant", "irrelevant")}
    return {"status": "ok", "items": items, "summary": {**counts, "example_count": len(items)}}, issues


def _evaluate_misconceptions(annotation: dict[str, Any], segments: list[tuple[str, str, dict[str, Any]]], script: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    candidate = " ".join(text for _, text, _ in segments) + " " + script
    items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for misconception in annotation.get("misconceptions", []):
        if not isinstance(misconception, dict):
            continue
        wrong = str(misconception.get("wrong_claim") or "")
        why_wrong = str(misconception.get("why_wrong") or "")
        introduced = bool(wrong and _normalize(wrong) in _normalize(candidate))
        wrong_terms = [piece for piece in re.split(r"[^0-9A-Za-z\u3400-\u9fff]+", wrong) if len(piece) >= 2]
        correction = any(marker in candidate for marker in _NEGATION_MARKERS) and (
            any(_normalize(term) in _normalize(candidate) for term in wrong_terms)
            or _shared_overlap(wrong, candidate) >= 0.15
        )
        must_address = bool(misconception.get("must_address", False))
        status = "introduced" if introduced else "handled" if correction else "not_addressed"
        record = {"misconception_id": str(misconception.get("id") or "unknown"), "wrong_claim": wrong, "must_address": must_address, "status": status, "candidate_evidence": candidate if introduced or correction else None, "reference": why_wrong, "reason": "exact wrong claim found" if introduced else "explicit corrective language found" if correction else "no exact wrong claim or corrective evidence detected"}
        items.append(record)
        if status == "introduced" or (status == "not_addressed" and must_address):
            issues.append({"stage": "eval", "type": "PEDAGOGY_MISCONCEPTION", "severity": "error" if status == "introduced" else "warning", "message": f"misconception {record['misconception_id']} is {status}", "element_id": record["misconception_id"], "evidence": record})
    counts = {status: sum(item["status"] == status for item in items) for status in ("handled", "avoided", "not_addressed", "introduced")}
    return {"status": "ok", "items": items, "summary": {**counts, "misconception_count": len(items)}}, issues


def _candidate_repetition_pairs(concept: dict[str, Any], segments: list[tuple[str, str, dict[str, Any]]]) -> list[dict[str, Any]]:
    terms = _concept_terms(concept)
    occurrences = [{"slide": slide, "text": text} for slide, text, _ in segments if _matches(text, terms)]
    pairs = []
    for left, right in itertools.combinations(occurrences, 2):
        similarity = _shared_overlap(left["text"], right["text"])
        later_marked_productive = any(marker.lower() in right["text"].lower() for marker in _PRODUCTIVE_MARKERS)
        status = "productive_repetition" if similarity < 0.75 or later_marked_productive else "redundant_reteach"
        pairs.append({"concept_id": str(concept.get("id") or "unknown"), "first_slide": left["slide"], "second_slide": right["slide"], "similarity": round(similarity, 6), "status": status, "reason": "later occurrence has recap/example/application marker" if later_marked_productive else "occurrences have distinct wording or low overlap; no redundant re-teach signal" if status == "productive_repetition" else "high textual overlap without a deterministic value marker"})
    return pairs


def _evaluate_redundancy(concepts: list[dict[str, Any]], segments: list[tuple[str, str, dict[str, Any]]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    items = [pair for concept in concepts for pair in _candidate_repetition_pairs(concept, segments)]
    issues = [{"stage": "eval", "type": "PEDAGOGY_REDUNDANCY", "severity": "warning", "message": f"concept {item['concept_id']} is redundantly retaught on slides {item['first_slide']} and {item['second_slide']}", "element_id": item["concept_id"], "evidence": item} for item in items if item["status"] == "redundant_reteach"]
    if not items:
        return {"status": "not_applicable", "items": [], "summary": {"status": "not_applicable", "candidate_pair_count": 0, "productive_repetition": 0, "redundant_reteach": 0}}, issues
    return {"status": "ok", "items": items, "summary": {"candidate_pair_count": len(items), "productive_repetition": sum(item["status"] == "productive_repetition" for item in items), "redundant_reteach": sum(item["status"] == "redundant_reteach" for item in items)}}, issues


def _question_concept_ids(question: dict[str, Any], concept_map: dict[str, dict[str, Any]]) -> list[str]:
    values = question.get("targets", question.get("concept_ids", []))
    if not isinstance(values, list):
        values = [values] if values else []
    return list(dict.fromkeys(str(value) for value in values if str(value) in concept_map))


def _evaluate_assessment(
    questions: list[dict[str, Any]], annotation: dict[str, Any], concept_records: dict[str, dict[str, Any]], paragraphs: dict[str, str]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not questions:
        return {"status": "not_applicable", "items": [], "summary": {"status": "not_applicable", "question_count": 0}}, []
    cmap = _concept_map(annotation)
    items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for question in questions:
        question_id = str(question.get("id") or question.get("question_id") or "unknown")
        ids = _question_concept_ids(question, cmap)
        records = [concept_records[item] for item in ids if item in concept_records]
        answer_text = question.get("answer", "")
        scoring = str(question.get("scoring") or "")
        reference = " ".join(paragraphs.get(str(item), "") for concept in (cmap.get(cid) for cid in ids) if concept for item in concept.get("evidence_paragraphs", []))
        answer_serialized = json.dumps(answer_text, ensure_ascii=False) + " " + scoring
        answer_supported = bool(ids) and any(_shared_overlap(answer_serialized, reference) > 0 or _matches(answer_serialized, _concept_terms(cmap[cid])) for cid in ids)
        if not ids:
            status = "misaligned"
            reason = "question does not target a frozen concept"
        elif all(item["status"] == "covered" for item in records) and answer_supported:
            status = "aligned"
            reason = "question targets covered concept(s) and its reference answer matches source evidence"
        else:
            status = "partially_aligned"
            reason = "question has a concept target but candidate coverage or reference evidence is partial"
        record = {"question_id": question_id, "target_concepts": ids, "candidate_concepts": [{"concept_id": item["concept_id"], "status": item["status"], "evidence": item["candidate_evidence"]} for item in records], "source_evidence": _source_evidence(paragraphs, [str(item) for cid in ids for item in cmap[cid].get("evidence_paragraphs", [])], [term for cid in ids for term in _concept_terms(cmap[cid])]), "status": status, "reason": reason, "reference_answer_supported": answer_supported}
        items.append(record)
        if status in {"misaligned", "partially_aligned"}:
            issues.append({"stage": "eval", "type": "PEDAGOGY_ASSESSMENT_MISMATCH", "severity": "error" if status == "misaligned" else "warning", "message": f"assessment {question_id} is {status}", "question_id": question_id, "evidence": record})
    counts = {status: sum(item["status"] == status for item in items) for status in ("aligned", "partially_aligned", "misaligned")}
    return {"status": "ok", "items": items, "summary": {**counts, "question_count": len(items)}}, issues


def _write_calibration(path: Path, dimensions: dict[str, dict[str, Any]], case_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Pedagogy Calibration — {case_id}",
        "",
        f"- Rule version: `{RULE_VERSION}`",
        "- Human review status: `pending`",
        "- Labels: `correct`, `too_strict`, `too_lenient`, `false_positive`, `false_negative`, `ambiguous`",
        "- This file is a review worksheet; it is not a formal inter-rater reliability study.",
        "",
        "| Dimension | Item | Automatic status | Evidence / reason | Human label | Human notes |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for dimension, result in dimensions.items():
        items = result.get("items", [])
        if not items:
            lines.append(f"| {dimension} | — | {result.get('status', 'not_applicable')} | {result.get('reason', '')} | pending | |")
            continue
        for item in items:
            item_id = item.get("objective_id") or item.get("concept_id") or item.get("question_id") or item.get("misconception_id") or f"{item.get('first_slide', '')}-{item.get('second_slide', '')}"
            status = item.get("status") or item.get("ordering") or "unknown"
            reason = str(item.get("reason") or "").replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {dimension} | `{item_id}` | `{status}` | {reason} | pending | |")
    lines.extend(["", "## Calibration summary", "", "| Metric | Value |", "| --- | ---: |", "| total judged items | pending |", "| human confirmed | pending |", "| false positives | pending |", "| false negatives | pending |", "| ambiguous | pending |", "| precision | pending |", "| agreement rate | pending |", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def evaluate_pedagogy(context: EvalContext) -> dict[str, Any]:
    name = "pedagogy"
    source_path = _case_asset(context, "source_json")
    annotation_path = _case_asset(context, "annotation")
    storyboard_path = context.artifact("storyboard")
    if not all(path and path.is_file() for path in (source_path, annotation_path, storyboard_path)):
        return unavailable(context, name, "source_json, annotation, and storyboard are required")

    source, annotation, storyboard, questions, paths = _load_inputs(context)
    paragraphs = _paragraphs(source)
    segments = _segments(storyboard)
    script = _script_text(context)
    concepts = _concepts(annotation)
    concept_records = {str(concept.get("id")): _concept_evidence(concept, segments, script) for concept in concepts if concept.get("id") is not None}

    dimensions: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    objective, objective_issues = _evaluate_objectives(annotation, concepts, concept_records, segments, script)
    dimensions["learning_objective_coverage"] = objective
    issues.extend(objective_issues)
    prerequisite, prerequisite_issues = _evaluate_prerequisites(annotation, concepts, segments)
    dimensions["prerequisite_satisfaction"] = prerequisite
    issues.extend(prerequisite_issues)
    ordering, ordering_issues = _evaluate_ordering(concepts, segments)
    dimensions["concept_ordering"] = ordering
    issues.extend(ordering_issues)
    examples, example_issues = _evaluate_examples(concepts, segments, paragraphs)
    dimensions["example_relevance"] = examples
    issues.extend(example_issues)
    misconception, misconception_issues = _evaluate_misconceptions(annotation, segments, script)
    dimensions["misconception_handling"] = misconception
    issues.extend(misconception_issues)
    redundancy, redundancy_issues = _evaluate_redundancy(concepts, segments)
    dimensions["redundancy"] = redundancy
    issues.extend(redundancy_issues)
    assessment, assessment_issues = _evaluate_assessment(questions, annotation, concept_records, paragraphs)
    dimensions["assessment_alignment"] = assessment
    issues.extend(assessment_issues)

    calibration_path = context.output_root / "pedagogy_calibration.md"
    _write_calibration(calibration_path, dimensions, context.case.case_id)
    input_hashes = {key: _sha256(path) for key, path in paths.items()}
    provenance = {
        "rule_version": RULE_VERSION,
        "mode": "deterministic_only",
        "llm_judge_used": False,
        "input_artifact_sha256": input_hashes,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    blocking = any(item.get("severity") == "error" for item in issues)
    judged_items = sum(len(item.get("items", [])) for item in dimensions.values())
    metrics = {
        "dimension_count": len(dimensions),
        "judged_item_count": judged_items,
        "not_applicable_dimension_count": sum(item.get("status") == "not_applicable" for item in dimensions.values()),
        "objective_covered_count": objective["summary"].get("covered", 0),
        "objective_partial_count": objective["summary"].get("partially_covered", 0),
        "objective_missing_count": objective["summary"].get("missing", 0),
        "prerequisite_satisfied_count": prerequisite["summary"].get("satisfied", 0),
        "ordering_problematic_count": ordering["summary"].get("problematic", 0),
        "example_directly_relevant_count": examples["summary"].get("directly_relevant", 0),
        "misconception_introduced_count": misconception["summary"].get("introduced", 0),
        "redundant_reteach_count": redundancy["summary"].get("redundant_reteach", 0),
        "assessment_aligned_count": assessment["summary"].get("aligned", 0),
        "issue_count": len(issues),
    }
    evidence_ids = [f"{context.case.case_id}-pedagogy-annotation", f"{context.case.case_id}-pedagogy-storyboard", f"{context.case.case_id}-pedagogy-calibration"]
    evidence = [
        evidence_for(annotation_path, evidence_id=evidence_ids[0], kind="annotation"),
        evidence_for(storyboard_path, evidence_id=evidence_ids[1], kind="storyboard"),
        evidence_for(calibration_path, evidence_id=evidence_ids[2], kind="pedagogy_calibration"),
    ]
    if source_path:
        evidence.append(evidence_for(source_path, evidence_id=f"{context.case.case_id}-pedagogy-source", kind="source_json"))
        evidence_ids.append(f"{context.case.case_id}-pedagogy-source")
    if questions and paths.get("heldout_questions"):
        evidence.append(evidence_for(paths["heldout_questions"], evidence_id=f"{context.case.case_id}-pedagogy-heldout", kind="heldout_questions"))
        evidence_ids.append(f"{context.case.case_id}-pedagogy-heldout")
    return {
        "status": "failed" if blocking else "ok",
        "passed": not blocking,
        "metrics": metrics,
        "details": {
            **dimensions,
            "summary": {"dimension_count": len(dimensions), "judged_item_count": judged_items, "blocking_issue_count": sum(item.get("severity") == "error" for item in issues), "no_total_score": True},
            "provenance": provenance,
            "calibration_path": str(calibration_path),
        },
        "issues": issues,
        "evidence_ids": evidence_ids,
        "_evidence": evidence,
    }


evaluate_pedagogy.evaluator_name = "pedagogy"


__all__ = ["evaluate_pedagogy", "RULE_VERSION", "_candidate_repetition_pairs", "parse_pedagogy_judge"]
