# Overnight Stability Phase 0 Audit

Repository: `Textbook-to-Video`
Branch: `codex/luna-stability-loop-local`
Start HEAD: `959fce69d0c8ee706ba13348c0aa436b9653571f`
Working tree at audit: clean

## Reuse points

- `src/textbook2video/pipeline/storyboard.py`
  - `run_storyboard_agent_review()` is the storyboard reviewer/repair loop.
  - `_call_review_agent()` reads a storyboard and returns review issues.
  - `_call_repair_agent()` returns a complete repaired storyboard object.
  - The current loop applies the repaired object in memory and returns it; it does not write lineage or create a candidate directory.
- `src/textbook2video/animation_gen.py`
  - `run_layout_qa()` and `failing_slide_indices()` provide deterministic layout observations.
  - `apply_css_hotfixes()` is the zero-token deterministic CSS path.
  - `repair_single_slides()` and `replace_failed_batches()` are the existing single-slide and batch LLM repair paths.
  - `generate()` writes `output_path` before QA and writes repaired HTML back to the same path, so this is the main canonical-overwrite risk to isolate.
- `src/textbook2video/eval/runner.py`
  - `EvalContext.artifact()` resolves declared and conventional artifact paths.
  - `run_case()` isolates evaluator exceptions, normalizes unified issues, writes `eval_report.json`, `run_manifest.json`, review files, and CSVs.
  - A caller can select a targeted evaluator sequence by passing `evaluators=[...]`; optional adapters append their evaluator when not already present.
- `src/textbook2video/eval/evaluators/repair_effectiveness.py`
  - `RepairEffectivenessAdapter` is the existing lineage consumer.
  - It accepts either a list or an object with `repairs`, rejects duplicate `repair_id`, verifies before/after artifact SHA-256 when declared, compares before/after reports, and keeps calibration labels pending.
  - Its effective fields are `repair_id`, case/round, source issue identity, before/after artifact references, before/after report references, and optional status/action/source metadata.
- `src/textbook2video/eval/compare.py` and `src/textbook2video/eval/evaluators/regression.py`
  - `compare_reports()` already computes gate changes, metric deltas, new issues, resolved issues, and unchanged issues without a unified score.
  - `evaluate_regression()` can consume a precomputed comparison and turn regressed gates into a blocking result.
- `contracts/`
  - Existing public contracts include unified issues, evaluator results, eval reports, and run manifests. No repair-lineage or stability contract exists yet.

## Phase 0 gap statement

The implementation should add the thinnest coordination layer around these existing functions:

1. append-only repair lineage writer with SHA-256 references and explicit attempt status;
2. candidate workspace + issue-family router + targeted evaluator selection;
3. acceptance policy that resolves the target issue, rejects new blocking regressions, enforces round/budget limits, and records accept/rollback;
4. repeated evaluation aggregation with independent run IDs, gate flips, metric mean/std, issue frequency, and worst run.

The new layer must use local deterministic repair/evaluator callables in tests. It must not invoke the optional cloud-model adapters or change frozen case files, evaluator thresholds, or canonical artifacts.
