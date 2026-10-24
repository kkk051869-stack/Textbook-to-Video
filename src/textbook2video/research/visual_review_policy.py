"""Separate strict approval from permission to render an explicitly unapproved draft."""

from __future__ import annotations

POLICIES = ("strict", "development")
COSMETIC_CATEGORIES = frozenset({"spacing", "color", "hierarchy", "styling"})


def review_disposition(report: dict, geometry: list, page_plan: dict | None = None) -> dict:
    """Recompute eligibility from evidence, never from a cached 'usable' flag.

    Unknown issues are blocking. Even an aesthetic issue cannot override negative
    semantic, completeness, readability, coverage, or geometry evidence.
    """
    blockers = []
    scores = report.get("scores", {})
    issues = report.get("issues")
    if report.get("verdict") not in {"ACCEPT", "REVISE"}:
        blockers.append("review_rejected_or_invalid")
    if (
        not isinstance(scores, dict)
        or set(scores) != {"accuracy", "relevance", "readability", "composition"}
        or any(type(v) is not int or not 0 <= v <= 4 for v in scores.values())
    ):
        blockers.append("invalid_scores")
    elif any(scores[name] < 3 for name in ("accuracy", "relevance", "readability")):
        blockers.append("semantic_or_readability_score")
    if not isinstance(issues, list):
        blockers.append("invalid_issues")
        issues = []
    if any(capture.get("issues") for capture in geometry):
        blockers.append("geometry_failure")
    if report.get("prior_coverage_conflicts"):
        blockers.append("prior_coverage_conflict")
    checks = report.get("checks", {})
    check_names = ("accuracy", "relevance", "completeness", "readability")
    if "checks" in report and (
        not isinstance(checks, dict)
        or any(type(checks.get(name)) is not bool for name in check_names)
        or any(checks.get(name) is False for name in check_names)
    ):
        blockers.append("negative_or_invalid_content_checks")
    plan = page_plan or {}
    replaced = plan.get("replaces_element_ids", [])
    if replaced:
        coverage = report.get("coverage", [])
        proofs = {item["element_id"]: item for item in plan.get("coverage", [])}
        expected = {
            "represented": "covered",
            "unsupported_in_source": "unsupported",
            "irrelevant_to_goal": "irrelevant",
        }
        if (
            not isinstance(coverage, list)
            or len(coverage) != len(replaced)
            or any(not isinstance(item, dict) for item in coverage)
            or {item.get("element_id") for item in coverage} != set(replaced)
            or any(
                item.get("verdict")
                != expected.get(proofs.get(item["element_id"], {}).get("decision"))
                or not item.get("reason")
                for item in coverage
            )
        ):
            blockers.append("coverage_failure")
    strict = (
        not blockers
        and report.get("verdict") == "ACCEPT"
        and not issues
        and min(scores.values()) >= 3
    )
    if strict:
        return {"strict_approved": True, "draft_usable": True, "blockers": [], "warnings": []}
    if not isinstance(checks, dict) or any(
        checks.get(name) is not True
        for name in ("accuracy", "relevance", "completeness", "readability")
    ):
        blockers.append("missing_or_negative_content_checks")
    if not issues or any(
        not isinstance(issue, dict)
        or not isinstance(issue.get("category"), str)
        or issue["category"] not in COSMETIC_CATEGORIES
        or not isinstance(issue.get("issue"), str)
        or not issue["issue"].strip()
        or not isinstance(issue.get("change"), str)
        or not issue["change"].strip()
        for issue in issues
    ):
        blockers.append("unclassified_or_noncosmetic_issue")
    return {
        "strict_approved": False,
        "draft_usable": not blockers,
        "blockers": blockers,
        "warnings": issues,
    }
