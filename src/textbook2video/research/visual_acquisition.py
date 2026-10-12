"""Execute explicit retrieve/generate decisions with provenance, never silently."""

from __future__ import annotations

import base64
import json
import re
import shutil
from pathlib import Path
from typing import Any

from textbook2video.llm.image_gen import generate_image
from textbook2video.research.source_evidence import lexical_score


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def execute_visual_acquisition(
    *,
    decision_path: str | Path,
    output_dir: str | Path,
    retrieval_catalog_path: str | Path | None = None,
    enable_generation: bool = False,
    min_retrieval_score: float = 0.25,
) -> Path:
    """Materialize only approved retrieval/generation requests.

    Retrieval is against an explicit local RAG catalog whose entries require a
    local file and a license/provenance string.  Generation is opt-in because
    an image API result is a candidate asset, never textbook evidence.
    """
    decisions = _read(Path(decision_path))
    catalog = _read(Path(retrieval_catalog_path)).get("assets", []) if retrieval_catalog_path else []
    output = Path(output_dir)
    image_dir = output / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    assets: list[dict[str, Any]] = []
    for index, decision in enumerate(decisions.get("decisions", []), start=1):
        if not isinstance(decision, dict):
            continue
        action = str(decision.get("action") or "")
        prop_id = str(decision.get("narration_proposition_id") or "")
        if action == "reuse":
            assets.append({"proposition_id": prop_id, "action": action, "status": "SOURCE_REUSE_REFERENCED", "source_image_id": decision.get("source_image_id")})
            continue
        if action == "none":
            assets.append({"proposition_id": prop_id, "action": action, "status": "NO_VISUAL_AUTHORIZED"})
            continue
        if action == "retrieve":
            query = str(decision.get("retrieval_query") or "")
            scored = []
            for candidate in catalog if isinstance(catalog, list) else []:
                if not isinstance(candidate, dict):
                    continue
                path = Path(str(candidate.get("path") or ""))
                license_text = str(candidate.get("license") or candidate.get("provenance") or "")
                if not path.is_file() or not license_text:
                    continue
                text = " ".join(str(candidate.get(key) or "") for key in ("caption", "description", "title", "tags"))
                score = lexical_score(query, text)
                if score > 0:
                    scored.append((score, candidate))
            scored.sort(key=lambda item: (-item[0], str(item[1].get("id") or "")))
            if not scored:
                assets.append({"proposition_id": prop_id, "action": action, "status": "RETRIEVAL_NO_ACCEPTABLE_RESULT", "query": query})
                continue
            score, selected = scored[0]
            if score < min_retrieval_score:
                assets.append({
                    "proposition_id": prop_id,
                    "action": action,
                    "status": "RETRIEVAL_BELOW_RELEVANCE_THRESHOLD",
                    "query": query,
                    "best_candidate_id": selected.get("id"),
                    "best_score": score,
                    "minimum_score": min_retrieval_score,
                })
                continue
            source = Path(str(selected["path"]))
            asset_id = re.sub(r"[^A-Za-z0-9_-]+", "-", str(selected.get("id") or f"retrieved-{index}")).strip("-")
            destination = image_dir / f"{asset_id}{source.suffix.lower() or '.png'}"
            shutil.copy2(source, destination)
            assets.append({
                "proposition_id": prop_id, "action": action, "status": "RETRIEVED_LOCAL_RAG",
                "asset_id": asset_id, "filename": destination.name, "local_path": str(destination),
                "retrieval_query": query, "retrieval_score": score,
                "license": selected.get("license"), "provenance": selected.get("provenance"),
            })
            continue
        if action == "generate":
            prompt = str(decision.get("generation_prompt") or "")
            if not enable_generation:
                assets.append({"proposition_id": prop_id, "action": action, "status": "GENERATION_REQUIRES_EXPLICIT_ENABLE", "generation_prompt": prompt})
                continue
            encoded = generate_image(prompt)
            if not encoded:
                assets.append({"proposition_id": prop_id, "action": action, "status": "GENERATION_FAILED", "generation_prompt": prompt})
                continue
            asset_id = f"generated-{index:03d}"
            destination = image_dir / f"{asset_id}.png"
            destination.write_bytes(base64.b64decode(encoded))
            assets.append({
                "proposition_id": prop_id, "action": action, "status": "GENERATED_CANDIDATE_PENDING_VLM_REVIEW",
                "asset_id": asset_id, "filename": destination.name, "local_path": str(destination), "generation_prompt": prompt,
            })
    path = output / "visual_acquisition.json"
    path.write_text(json.dumps({
        "schema_version": "p0-visual-acquisition-v1.0", "decision_path": str(decision_path),
        "retrieval_catalog_path": str(retrieval_catalog_path) if retrieval_catalog_path else None,
        "generation_enabled": enable_generation,
        "minimum_retrieval_score": min_retrieval_score,
        "assets": assets,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def build_reviewed_acquisition_briefs(
    *,
    decision_path: str | Path,
    acquisition_path: str | Path,
    vlm_review_path: str | Path,
    output_path: str | Path,
) -> Path:
    """Promote acquired assets only when a persisted VLM review accepts them.

    The review document is intentionally provider-agnostic but every entry
    must include ``asset_id``, ``verdict=ACCEPT``, a target segment and an
    explanatory summary.  This makes external retrieval/generation obey the
    same VLM gate as textbook figures before it is passed to storyboard.py.
    """
    decisions = _read(Path(decision_path))
    acquisition = _read(Path(acquisition_path))
    reviews = _read(Path(vlm_review_path)).get("decisions", [])
    decisions_by_prop = {
        str(item.get("narration_proposition_id") or ""): item
        for item in decisions.get("decisions", []) if isinstance(item, dict)
    }
    assets = {
        str(item.get("asset_id") or ""): item
        for item in acquisition.get("assets", []) if isinstance(item, dict)
        and str(item.get("status") or "") in {"RETRIEVED_LOCAL_RAG", "GENERATED_CANDIDATE_PENDING_VLM_REVIEW"}
    }
    briefs: list[dict[str, Any]] = []
    available_images: list[dict[str, Any]] = []
    image_dir = Path(output_path).parent / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    for review in reviews if isinstance(reviews, list) else []:
        if not isinstance(review, dict) or str(review.get("verdict") or "").upper() != "ACCEPT":
            continue
        asset_id = str(review.get("asset_id") or "")
        asset = assets.get(asset_id)
        proposition_id = str(review.get("narration_proposition_id") or "")
        decision = decisions_by_prop.get(proposition_id)
        if not asset or not decision:
            continue
        segment_id = str(review.get("segment_id") or "")
        summary = str(review.get("visual_summary") or "").strip()
        if not segment_id or not summary:
            continue
        local_path = Path(str(asset.get("local_path") or ""))
        if not local_path.is_file():
            continue
        destination_image = image_dir / local_path.name
        if local_path.resolve() != destination_image.resolve():
            shutil.copy2(local_path, destination_image)
        briefs.append({
            "segment_id": segment_id,
            "source_image_id": asset_id,
            "filename": local_path.name,
            "visual_summary": summary,
            "proposition": str(review.get("proposition") or decision.get("rationale") or proposition_id),
            "layout_hint": str(review.get("layout_hint") or "primary explanatory visual"),
            "visual_role": str(review.get("visual_role") or "EXPLANATORY_DIAGRAM"),
            "vlm_verdict": "ACCEPT",
            "vlm_reason": str(review.get("reason") or ""),
            "acquisition": decision.get("action"),
            "acquisition_provenance": {
                key: asset.get(key) for key in ("retrieval_query", "retrieval_score", "license", "provenance", "generation_prompt")
                if asset.get(key) is not None
            },
        })
        available_images.append({
            "id": asset_id, "filename": destination_image.name,
            "description": summary, "source_locator": "p0:reviewed-acquisition",
            "acquisition": decision.get("action"),
        })
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({
        "schema_version": "p0-reviewed-acquisition-briefs-v1.0",
        "decision_path": str(decision_path), "acquisition_path": str(acquisition_path),
        "vlm_review_path": str(vlm_review_path), "visual_briefs": briefs,
        "claim": "Only VLM ACCEPT acquired assets are included; rejected or unreviewed assets are absent.",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    destination.with_name(destination.stem + "_images.json").write_text(
        json.dumps(available_images, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return destination


def apply_vlm_review_to_acquisition(
    *,
    acquisition_path: str | Path,
    vlm_review_path: str | Path,
    output_path: str | Path,
) -> Path:
    """Persist the VLM gate on acquisition records before planning can use them.

    A review is not merely a storyboard prompt input: the accepted/rejected
    state belongs on the concrete local asset that a later executable plan may
    materialize.  Missing reviews remain ``UNREVIEWED`` and are ineligible.
    """
    acquisition = _read(Path(acquisition_path))
    reviews = _read(Path(vlm_review_path)).get("decisions", [])
    by_asset = {
        str(item.get("asset_id") or ""): item
        for item in reviews if isinstance(item, dict) and item.get("asset_id")
    }
    assets: list[dict[str, Any]] = []
    for raw in acquisition.get("assets", []):
        if not isinstance(raw, dict):
            continue
        asset = dict(raw)
        review = by_asset.get(str(asset.get("asset_id") or ""))
        if review:
            asset["vlm_verdict"] = str(review.get("verdict") or "UNREVIEWED").upper()
            asset["vlm_review_reason"] = str(review.get("reason") or "")
            asset["vlm_review_path"] = str(vlm_review_path)
            asset["description"] = review.get("visual_summary") or asset.get("description")
            asset["caption"] = review.get("caption") or asset.get("caption")
        elif asset.get("asset_id"):
            asset["vlm_verdict"] = "UNREVIEWED"
        assets.append(asset)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({
        **acquisition,
        "schema_version": "p0-visual-acquisition-v1.1-reviewed",
        "source_acquisition_path": str(acquisition_path),
        "vlm_review_path": str(vlm_review_path),
        "assets": assets,
        "claim": "Only assets with vlm_verdict=ACCEPT may be materialized by an executable P0 plan.",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destination


__all__ = [
    "apply_vlm_review_to_acquisition",
    "build_reviewed_acquisition_briefs",
    "execute_visual_acquisition",
]
