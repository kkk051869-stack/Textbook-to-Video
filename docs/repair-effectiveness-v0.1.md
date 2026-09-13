# Repair Effectiveness v0.1

## Scope

This evaluator consumes repair lineage and before/after reports produced by
the existing evaluators. It does not run a repair agent, re-evaluate a
candidate, or mutate candidate artifacts.

The current repair execution paths are:

- animation/layout repair attempts in `src/textbook2video/animation_gen.py`;
- storyboard deterministic repair and reviewer/repair-agent loop in
  `src/textbook2video/pipeline/storyboard.py`;
- orchestration of those attempts in
  `src/textbook2video/pipeline/orchestrator.py`.

No pre-existing structured repair lineage or repair metrics run was present in
the repository or local `workspace/eval-runs` inventory. The new evaluator is
therefore an independent measurement layer. Ordinary runs include it as
`status=not_applicable` when no lineage is supplied; this is non-blocking.

## Input

Enable the evaluator with:

```text
python -m textbook2video.eval.runner --case <case_manifest.json> \
  --artifacts <candidate-artifacts> --out <eval-output> \
  --repair-lineage <repair_lineage.json>
```

The lineage is an object with a `repairs` array (a bare array is also
accepted). Each repair record carries:

| Field | Type | Required/default | Meaning |
| --- | --- | --- | --- |
| `repair_id` | string | required, unique | Stable repair attempt identity |
| `case_id` | string | optional; current case | Case being repaired |
| `round` | integer | required, >= 1 | Repair round |
| `source_issue_id` | string/null | optional | Issue selected for repair |
| `issue_type` / `issue_stage` | string | optional | Fallback issue identity fields |
| `severity` | string | optional, `warning` | Source severity |
| `before_artifact` / `after_artifact` | relative path or object | required for evaluation | Artifact provenance |
| `before_eval_report` / `after_eval_report` | relative path or inline object | required for evaluation | Reports from the same evaluator |
| `before_status` / `after_status` | string | report status fallback | Recorded status |
| `repair_action` / `repair_source` | string | optional | Action and provenance |

An artifact object may contain `path` and `sha256`. Missing artifacts,
missing reports, or SHA mismatches produce `not_evaluable` and a structured
issue; they are never counted as successful repairs.

Issue identity uses `issue_id` first. If it is absent, the stable fallback is:
`stage + type/category + slide + element_id + event_id + question_id`.
Message text is never used for matching.

## Result and metrics

Each repair has exactly one result: `success`, `partial`, `failed`,
`worsened`, or `not_evaluable`. An unnecessary repair is still represented as
`failed`, with `unnecessary_repair=true` and `unnecessary_repair_count`.

- `repair_attempt_count`: number of lineage records.
- `repair_success_count`, `repair_partial_count`, `repair_failed_count`,
  `repair_worsened_count`, `repair_not_evaluable_count`: result counts.
- `repair_success_rate` = `success_count / attempt_count`.
- `resolved_issue_count`: confirmed source issues absent from the after report.
- `persistent_issue_count`: confirmed source issues still present after repair.
- `introduced_issue_count` / `new_issue_count`: after identities absent from
  before identities, excluding the source issue family.
- `regression_repair_count`: repairs introducing one or more new issues.
- `repair_regression_rate` = `regression_repair_count / completed_repairs`,
  where not-evaluable and unnecessary attempts are excluded.
- `repairs_without_regression`: completed repairs with no introduced issue.
- `repairs_with_minor_regression` and `repairs_with_blocking_regression`:
  repair counts classified by the introduced issue severity.
- `net_issue_delta` = weighted resolved issue count minus weighted introduced
  issue count. Default weights are `info/minor/warning=1`,
  `major/error=3`, and `critical=5`; the configured weights are stored in
  evaluator provenance. Raw counts remain available.
- `average_rounds_to_pass` and `max_rounds_to_pass`: round values for repairs
  whose source issue is resolved; if no repair passes, they are null.
- `unnecessary_repair_count`: attempts with no confirmed source issue in the
  before report. This is a diagnostic, not a success.
- `unobserved_event_count`: attempts that cannot be evaluated because a
  before/after report or artifact is missing or untrusted.

Without formal human gold, detection precision and recall are omitted. The
evaluator instead reports `confirmed_detection_count`, explicit
`false_positive_count`, and `review_pending_count`. If `detection_gold` is
provided by a human-owned lineage, true/false positive and false negative
counts plus precision/recall are calculated.

## Calibration and issues

The evaluator writes `repair_calibration.md` under the evaluation output. All
human labels remain `pending`; allowed labels are `correct`, `too_strict`,
`too_lenient`, `false_positive`, `false_negative`, and `ambiguous`.

Issue types are:
`REPAIR_FAILED`, `REPAIR_PARTIAL`, `REPAIR_REGRESSION`, `REPAIR_WORSENED`,
`REPAIR_UNNECESSARY`, `REPAIR_ARTIFACT_MISSING`, and
`REPAIR_LINEAGE_INVALID`.
