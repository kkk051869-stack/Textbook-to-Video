"""Separate strict approval from permission to render an explicitly unapproved draft."""

from __future__ import annotations

POLICIES = ("strict", "development")
COSMETIC_CATEGORIES = frozenset({"spacing", "color", "hierarchy", "styling"})


def cosmetic_category(value) -> bool:
    """Accept the review prompt's historical literal 'cosmetic-only spacing' too."""
    if not isinstance(value, str):
        return False
    return value.removeprefix("cosmetic-only ") in COSMETIC_CATEGORIES


def review_disposition(
    report: dict, geometry: list, page_plan: dict | None = None, *, policy: str = 'strict',
) -> dict:
    """Recompute eligibility from evidence, never from a cached 'usable' flag.

    Unknown issues are blocking. Even an aesthetic issue cannot override negative
    semantic, completeness, readability, coverage, or geometry evidence.
    """
    if policy not in POLICIES:
        raise ValueError('review policy must be strict or development')
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
    if policy == 'development':
        # A quality verdict is evidence to retain, not permission to claim approval.
        # Keep malformed reports and unsafe replacement coverage blocking.
        valid_report = (
            report.get('verdict') in {'ACCEPT', 'REVISE', 'REJECT'}
            and 'invalid_scores' not in blockers
            and isinstance(report.get('issues'), list)
            and all(isinstance(issue, dict) for issue in issues)
            and ('checks' not in report or isinstance(checks, dict)
                 and all(type(checks.get(name)) is bool for name in check_names))
        )
        hard = ([] if valid_report else ['invalid_review_report'])
        if 'coverage_failure' in blockers:
            hard.append('coverage_failure')
        warnings = list(issues) + [{
            'category': 'development_quality', 'issue': reason,
            'change': 'Retained as an unapproved development draft; inspect rendered output.',
        } for reason in dict.fromkeys(blockers)]
        return {'strict_approved': False, 'draft_usable': not hard,
                'blockers': hard, 'warnings': warnings,
                'strict_blockers': list(dict.fromkeys(blockers)),
                'quality_status': 'UNAPPROVED_DEVELOPMENT_DRAFT'}
    if not isinstance(checks, dict) or any(
        checks.get(name) is not True
        for name in ("accuracy", "relevance", "completeness", "readability")
    ):
        blockers.append("missing_or_negative_content_checks")
    if not issues or any(
        not isinstance(issue, dict)
        or not cosmetic_category(issue.get("category"))
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
