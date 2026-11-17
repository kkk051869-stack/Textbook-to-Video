"""Build a gold-blind RQ1 holdout from the legacy pilot input packets.

The legacy formal-pilot packet contains propositions and *available* source
assets, but its annotation fields are intentionally blank.  This adapter does
not read historical annotation or prediction files.  It only creates the
current research schema needed to run the frozen visual-decision method on
unseen lessons.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_holdout(
    *,
    legacy_root: Path,
    packet_path: Path,
    output_dir: Path,
    lessons: list[str],
    per_lesson: int,
) -> dict[str, Path]:
    packet = _read(packet_path)
    items = [
        item
        for item in packet.get("items", [])
        if isinstance(item, dict)
        and str(item.get("case_id") or "") in set(lessons)
        and isinstance(item.get("annotation"), dict)
        and all(value in (None, "", []) for value in item["annotation"].values())
    ]
    if not items:
        raise ValueError("no blank annotation items found for requested lessons")

    selected: list[dict[str, Any]] = []
    for lesson in lessons:
        lesson_items = sorted(
            (item for item in items if str(item.get("case_id")) == lesson),
            key=lambda item: str(item.get("knowledge_proposition_id") or ""),
        )
        if len(lesson_items) < per_lesson:
            raise ValueError(f"{lesson} has only {len(lesson_items)} blank items")
        selected.extend(lesson_items[:per_lesson])

    inputs_root = legacy_root / "datasets" / "research_generation_v2" / "dry_run" / "20261006-3a7-pilot-a" / "inputs"
    source_units_by_id: dict[str, dict[str, Any]] = {}
    source_images_by_id: dict[str, dict[str, Any]] = {}
    image_paths: dict[str, Path] = {}
    selected_records: list[dict[str, Any]] = []
    for item in selected:
        lesson = str(item["case_id"])
        source_path = inputs_root / lesson / "source_units.json"
        source_doc = _read(source_path)
        for unit in source_doc.get("source_units", []):
            if isinstance(unit, dict) and unit.get("id"):
                source_units_by_id[str(unit["id"])] = unit
        for image in source_doc.get("source_images", []):
            if isinstance(image, dict) and image.get("id"):
                source_images_by_id[str(image["id"])] = image

        source_refs = [str(value) for value in item.get("available_source_evidence_ids", [])]
        image_ids = [str(value) for value in item.get("available_source_image_ids", [])]
        candidates: list[dict[str, Any]] = []
        for candidate in item.get("source_image_candidates", []):
            if not isinstance(candidate, dict) or not candidate.get("id"):
                continue
            candidate_id = str(candidate["id"])
            path = legacy_root / str(candidate.get("repo_relative_path") or "")
            if path.is_file():
                image_paths[candidate_id] = path
                candidates.append(
                    {
                        "candidate_id": candidate_id,
                        "path": str(path),
                        "caption": candidate.get("caption"),
                        "kind": "source_image",
                        "source_locator": source_images_by_id.get(candidate_id, {}).get("source_refs", []),
                    }
                )
        selected_records.append(
            {
                "case_id": lesson,
                "proposition_id": str(item["knowledge_proposition_id"]),
                "text": str(item["proposition_text"]),
                "source_refs": source_refs,
                "source_image_ids": image_ids,
                "candidate_count": len(candidates),
                "candidates": candidates,
            }
        )

    proposition_graph = {
        "schema_version": "rq1-unseen-holdout-proposition-graph-v0.1",
        "artifact_type": "proposition-graph",
        "holdout_status": "GOLD_BLIND",
        "narration_propositions": [
            {
                "id": record["proposition_id"],
                "segment_id": record["proposition_id"],
                "text": record["text"],
                "source_refs": record["source_refs"],
                "knowledge_proposition_ids": [record["proposition_id"]],
            }
            for record in selected_records
        ],
    }
    source_evidence = {
        "schema_version": "rq1-unseen-holdout-source-evidence-v0.1",
        "artifact_type": "source-evidence",
        "holdout_status": "GOLD_BLIND",
        "source_units": [source_units_by_id[key] for key in sorted(source_units_by_id)],
        "source_images": [
            {
                **source_images_by_id[key],
                "availability": "AVAILABLE_LOCAL",
                "asset_kind": "source_image",
            }
            for key in sorted(source_images_by_id)
            if key in image_paths
        ],
    }
    storyboard = {
        "schema_version": "rq1-unseen-holdout-storyboard-v0.1",
        "artifact_type": "storyboard",
        "holdout_status": "GOLD_BLIND",
        "segments": [
            {
                "id": record["proposition_id"],
                "narration": record["text"],
                "elements": [
                    {"type": "image", "source_image_id": image_id}
                    for image_id in record["source_image_ids"]
                    if image_id in image_paths
                ],
            }
            for record in selected_records
        ],
    }
    candidate_universe = {
        "schema_version": "rq1-unseen-holdout-candidate-universe-v0.1",
        "artifact_type": "candidate-universe",
        "holdout_status": "GOLD_BLIND",
        "candidates": [candidate for record in selected_records for candidate in record["candidates"]],
    }
    metadata = {
        "schema_version": "rq1-unseen-holdout-metadata-v0.1",
        "status": "GOLD_BLIND_DEVELOPMENT_HOLDOUT",
        "lessons": lessons,
        "per_lesson": per_lesson,
        "sample_count": len(selected_records),
        "source_packet": str(packet_path),
        "historical_annotation_read": False,
        "historical_prediction_read": False,
        "selected_items": selected_records,
        "limitations": [
            "The propositions come from the legacy blank pilot packet rather than a newly sampled textbook.",
            "This is a development holdout, not a human-gold test set.",
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "proposition_graph": output_dir / "proposition_graph.json",
        "source_evidence": output_dir / "source_evidence.json",
        "storyboard": output_dir / "storyboard.json",
        "candidate_universe": output_dir / "candidate_universe.json",
        "metadata": output_dir / "holdout_metadata.json",
    }
    for key, value in (
        ("proposition_graph", proposition_graph),
        ("source_evidence", source_evidence),
        ("storyboard", storyboard),
        ("candidate_universe", candidate_universe),
        ("metadata", metadata),
    ):
        _write(outputs[key], value)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-root", required=True, type=Path)
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--lessons", nargs="+", default=["lesson_004", "lesson_007", "lesson_011", "lesson_012"])
    parser.add_argument("--per-lesson", type=int, default=3)
    args = parser.parse_args()
    outputs = build_holdout(
        legacy_root=args.legacy_root,
        packet_path=args.packet,
        output_dir=args.output_dir,
        lessons=args.lessons,
        per_lesson=args.per_lesson,
    )
    print(json.dumps({key: str(value) for key, value in outputs.items()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
