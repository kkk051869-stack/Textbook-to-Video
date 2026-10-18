"""Execute the real lesson_002 Track-A smoke from a prepared run manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .gold_alignment import evaluate_reviewed_gold
from .proposition_graph import build_proposition_graph
from .run_manifest import record_input_access
from .source_evidence import build_source_evidence
from .visual_decision import decide_visual_support
from .visual_decision_baselines import BASELINE_POLICIES, predict_baseline


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_track_a_smoke(manifest_path: str | Path, *, repo_root: str | Path) -> Path:
    root = Path(repo_root).resolve()
    manifest_file = Path(manifest_path).resolve()
    manifest = _read(manifest_file)
    output = root / manifest["output_root"]
    by_label = {item["label"]: root / item["path"] for item in manifest["declared_inputs"]}
    dataset_files = {
        item["path"]: root / item["path"]
        for item in manifest["declared_inputs"]
        if item["label"].startswith("dataset.manifest.files[")
    }

    def find(suffix: str) -> Path:
        matches = [
            path
            for relative, path in dataset_files.items()
            if relative.replace("\\", "/").endswith(suffix)
        ]
        if len(matches) != 1:
            raise ValueError(f"expected exactly one declared input ending with {suffix!r}")
        return matches[0]

    raw = find("/source/lesson_002.md")
    source_json = find("/source/source.json")
    lesson_plan = find("/baseline/lesson_plan.json")
    storyboard = find("/baseline/storyboard.json")
    candidate_image = find("/source/images/fig7-6_区块链数据结构.png")
    gold = by_label["frozen_inputs.gold"]
    generation_inputs = [
        raw,
        source_json,
        lesson_plan,
        storyboard,
        candidate_image,
        by_label["frozen_inputs.candidate_universe"],
        by_label["frozen_inputs.prompts[0]"],
        by_label["frozen_inputs.prompts[1]"],
    ]
    for path in generation_inputs:
        record_input_access(
            manifest_file, path, stage="generation", repo_root=root
        )

    source_evidence = output / "generation" / "source_evidence.json"
    graph = output / "generation" / "proposition_graph.json"
    decisions = output / "generation" / "visual_decisions.json"
    summary_path = output / "track_a_smoke_summary.json"
    try:
        source = _read(source_json)
        build_source_evidence(raw, source.get("images"), output_path=source_evidence)
        build_proposition_graph(
            raw_path=raw,
            source_evidence_path=source_evidence,
            storyboard_path=storyboard,
            lesson_plan_path=lesson_plan,
            output_path=graph,
            model=manifest["model"]["model_id"],
        )
        decide_visual_support(
            proposition_graph_path=graph,
            source_evidence_path=source_evidence,
            storyboard_path=storyboard,
            output_path=decisions,
            model=manifest["model"]["model_id"],
        )
        graph_doc = _read(graph)
        evidence_doc = _read(source_evidence)
        available_source_ids = {
            str(item["id"]) for item in evidence_doc.get("source_images", [])
        }
        storyboard_doc = _read(storyboard)
        segment_source_ids = {
            str(segment.get("id") or index): [
                str(element.get("source_image_id"))
                for element in segment.get("elements", [])
                if isinstance(element, dict)
                and element.get("type") == "image"
                and str(element.get("source_image_id") or "") in available_source_ids
            ]
            for index, segment in enumerate(storyboard_doc.get("segments", []), start=1)
            if isinstance(segment, dict)
        }
        baseline_paths: dict[str, str] = {}
        for policy in BASELINE_POLICIES:
            rows = [
                predict_baseline(
                    policy=policy,
                    proposition=proposition,
                    source_image_ids=segment_source_ids.get(
                        str(proposition.get("segment_id") or ""), []
                    ),
                )
                for proposition in graph_doc.get("narration_propositions", [])
            ]
            path = output / "baselines" / f"{policy}.json"
            _write(
                path,
                {
                    "schema_version": "a-visual-decision-baselines-v0.2",
                    "policy": policy,
                    "decisions": rows,
                    "claim": "Deterministic diagnostic baseline; not human gold.",
                },
            )
            baseline_paths[policy] = path.relative_to(output).as_posix()
        record_input_access(manifest_file, gold, stage="evaluation", repo_root=root)
        evaluation = evaluate_reviewed_gold(
            gold_path=gold,
            proposition_graph_path=graph,
            visual_decisions_path=decisions,
            output_path=output / "evaluation" / "gold_alignment.json",
        )
        decision_doc = _read(decisions)
        evaluation_doc = _read(evaluation)
        outputs = [source_evidence, graph, decisions, evaluation]
        summary = {
            "schema_version": "t2v-track-a-smoke-v1",
            "status": "PASS",
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "case_id": graph_doc.get("case_id"),
            "model_requested": manifest["model"]["model_id"],
            "knowledge_proposition_count": len(graph_doc.get("knowledge_propositions", [])),
            "narration_proposition_count": len(graph_doc.get("narration_propositions", [])),
            "visual_decision_count": len(decision_doc.get("decisions", [])),
            "baseline_outputs": baseline_paths,
            "gold_alignment": {
                "status": evaluation_doc.get("status"),
                "item_count": evaluation_doc.get("item_count"),
                "aligned_count": evaluation_doc.get("aligned_count"),
                "scored_count": evaluation_doc.get("scored_count"),
                "coverage": evaluation_doc.get("coverage"),
                "underpowered_classes": evaluation_doc.get("underpowered_classes"),
            },
            "limitations": [
                (
                    "The 30-item gold is an imbalanced working reference, "
                    "not formal dual-annotator data."
                ),
                "This is a development smoke and cannot support method-superiority claims.",
            ],
            "outputs": [
                {
                    "path": path.relative_to(output).as_posix(),
                    "sha256": _sha256(path),
                }
                for path in outputs
            ],
        }
        _write(summary_path, summary)
        manifest["status"] = "COMPLETE"
        manifest["completed_at_utc"] = summary["completed_at_utc"]
        manifest["summary"] = summary_path.relative_to(output).as_posix()
        _write(manifest_file, manifest)
        return summary_path
    except Exception as exc:
        failure = {
            "status": "FAILED_PRESERVED",
            "failed_at_utc": datetime.now(UTC).isoformat(),
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
        _write(output / "failure.json", failure)
        manifest["status"] = "FAILED_PRESERVED"
        manifest["failure"] = "failure.json"
        _write(manifest_file, manifest)
        raise


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest")
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    print(run_track_a_smoke(args.manifest, repo_root=args.repo_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["run_track_a_smoke"]
