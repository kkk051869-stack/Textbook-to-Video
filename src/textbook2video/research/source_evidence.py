"""Research-only source evidence sidecars for P0.

The production pipeline keeps extracted textbook text and image metadata, but
does not keep a proposition-level provenance chain.  This module builds that
chain beside (never inside) the frozen production artifacts.  Text links are
deterministic lexical candidates, not human-verified entailment labels.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

SOURCE_EVIDENCE_VERSION = "p0-source-evidence-v0.1"


def _features(text: str) -> set[str]:
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", text.lower())
    features = set(re.findall(r"[a-z]+|\d+(?:\.\d+)?", text.lower()))
    for run in re.findall(r"[\u4e00-\u9fff]+", normalized):
        if len(run) == 1:
            features.add(run)
        else:
            features.update(run[index : index + 2] for index in range(len(run) - 1))
    return {item for item in features if item}


def lexical_score(left: str, right: str) -> float:
    """Return a transparent overlap score; this is not semantic entailment."""
    left_features, right_features = _features(left), _features(right)
    if not left_features or not right_features:
        return 0.0
    denominator = min(len(left_features), len(right_features))
    return round(len(left_features & right_features) / denominator, 4)


def _source_units(raw_text: str) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    # The current PDF/DOCX extractors write one source paragraph per line.
    # Blank-line groups remain supported for manually prepared raw artifacts.
    matches = re.finditer(r"[^\n\r]+", raw_text)
    for index, match in enumerate(matches, start=1):
        text = match.group(0).strip()
        if not text:
            continue
        units.append(
            {
                "id": f"raw-unit-{index:04d}",
                "text": text,
                "source_locator": f"raw.txt:chars:{match.start()}-{match.end()}",
                "char_span": {"start": match.start(), "end": match.end()},
            }
        )
    if not units and raw_text.strip():
        units.append(
            {
                "id": "raw-unit-0001",
                "text": raw_text.strip(),
                "source_locator": f"raw.txt:chars:0-{len(raw_text)}",
                "char_span": {"start": 0, "end": len(raw_text)},
            }
        )
    return units


def _local_image_path(raw_path: Path, filename: str) -> Path | None:
    """Resolve only filenames in the production output image roots."""
    candidate = Path(filename)
    if not filename or candidate.name != filename:
        return None
    for root in (raw_path.parent / "images", raw_path.parent):
        path = root / filename
        if path.is_file():
            return path
    return None


def _teaching_asset_status(image: dict[str, Any]) -> str:
    """Classify image granularity without pretending to judge relevance."""
    asset_kind = str(image.get("asset_kind") or "")
    if asset_kind == "RENDERED_FIGURE_CROP":
        return "ELIGIBLE_COMPLETE_FIGURE_REQUIRES_VLM"
    if (
        asset_kind == "FIGURE_COMPONENT"
        or (image.get("figure_id") and image.get("caption") and not asset_kind)
    ):
        return "INELIGIBLE_ISOLATED_FIGURE_COMPONENT"
    return "ELIGIBLE_SOURCE_IMAGE_REQUIRES_VLM"


def build_source_evidence(
    raw_path: str | Path,
    available_images: list[dict[str, Any]] | None,
    *,
    output_path: str | Path,
) -> Path:
    """Persist source text units and the *local* textbook image inventory."""
    raw = Path(raw_path)
    text = raw.read_text(encoding="utf-8") if raw.is_file() else ""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    images: list[dict[str, Any]] = []
    for index, image in enumerate(available_images or [], start=1):
        if not isinstance(image, dict):
            continue
        image_id = str(image.get("id") or f"available-image-{index:03d}")
        filename = str(image.get("filename") or "")
        resolved = _local_image_path(raw, filename)
        record = {
            "id": image_id,
            "filename": filename,
            "description": str(image.get("description") or ""),
            "source_locator": str(
                image.get("source_locator") or f"production.available_images[{index - 1}]"
            ),
            "inventory_locator": f"production.available_images[{index - 1}]",
            "local_path": str(resolved) if resolved else None,
            "availability": "AVAILABLE_LOCAL" if resolved else "METADATA_ONLY_OR_MISSING",
            "teaching_asset_status": _teaching_asset_status(image),
        }
        for key in (
            "page_number",
            "figure_id",
            "caption",
            "caption_source_span",
            "nearby_text",
            "asset_kind",
            "source_component_ids",
            "caption_status",
            "sha256",
        ):
            if image.get(key) is not None:
                record[key] = image[key]
        images.append(record)
    evidence = {
        "schema_version": SOURCE_EVIDENCE_VERSION,
        "document": {
            "raw_path": str(raw),
            "sha256": digest,
            "status": "EXTRACTED_RAW_TEXT" if raw.is_file() else "RAW_TEXT_MISSING",
        },
        "source_units": _source_units(text),
        "source_images": images,
        "claim": (
            "Source links are deterministic lexical candidates until reviewed; image inventory "
            "is limited to locally extracted textbook images."
        ),
    }
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def link_propositions(
    propositions: list[dict[str, Any]], evidence: dict[str, Any]
) -> list[dict[str, Any]]:
    """Attach the top lexical source-unit candidate to each narration sentence."""
    units = [item for item in evidence.get("source_units", []) if isinstance(item, dict)]
    linked: list[dict[str, Any]] = []
    for proposition in propositions:
        item = dict(proposition)
        scored = sorted(
            (
                (lexical_score(str(item.get("text") or ""), str(unit.get("text") or "")), unit)
                for unit in units
            ),
            key=lambda pair: (-pair[0], str(pair[1].get("id") or "")),
        )
        if scored and scored[0][0] > 0:
            score, unit = scored[0]
            item["source_refs"] = [
                {
                    "source_unit_id": unit["id"],
                    "source_locator": unit["source_locator"],
                    "lexical_score": score,
                    "status": "MACHINE_CANDIDATE_NOT_GOLD",
                }
            ]
        else:
            item["source_refs"] = []
        linked.append(item)
    return linked


__all__ = ["SOURCE_EVIDENCE_VERSION", "build_source_evidence", "lexical_score", "link_propositions"]
