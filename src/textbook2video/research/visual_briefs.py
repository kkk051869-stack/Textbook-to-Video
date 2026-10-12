"""Turn VLM-reviewed image decisions into storyboard-safe visual briefs.

This module intentionally does not infer image meaning from PDF page text.
Its input is a persisted VLM decision artifact, produced from the image pixels,
and its output is the only image list the research storyboard path may use.
"""

from __future__ import annotations

from typing import Any


def build_vlm_review_context(
    image: dict[str, Any],
    *,
    segment_id: str,
    proposition: str,
) -> dict[str, Any]:
    """Build the text context that must accompany an image in a VLM review.

    The image pixels alone are insufficient for academic PDFs: a video frame
    can be a valid input example for a compression explanation, while the same
    frame is decorative for an optimisation equation.  ``caption`` is source
    evidence, not a model-generated guess.
    """
    image_id = str(image.get("id") or "").strip()
    if not image_id:
        raise ValueError("image review context requires image.id")
    if not str(segment_id).strip() or not str(proposition).strip():
        raise ValueError("image review context requires segment_id and proposition")
    return {
        "source_image_id": image_id,
        "filename": str(image.get("filename") or ""),
        "page_number": image.get("page_number"),
        "figure_id": image.get("figure_id"),
        "caption": image.get("caption"),
        "caption_source_span": image.get("caption_source_span"),
        "nearby_text": image.get("nearby_text"),
        "segment_id": str(segment_id),
        "proposition": str(proposition).strip(),
        "review_instruction": (
            "Judge this source image against the specified proposition, using the "
            "original figure caption as primary evidence. Classify its role as "
            "INPUT_EXAMPLE, EXPLANATORY_DIAGRAM, RESULT_FIGURE, DECORATIVE_ONLY, "
            "or NOT_RELEVANT; do not reject a video-frame example merely because "
            "it is not a chart or formula."
        ),
    }


def build_visual_briefs(
    decisions: list[dict[str, Any]],
    available_images: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return whitelisted, segment-bound briefs from explicit VLM ACCEPTs.

    Each decision must carry an image identifier, a target segment, an actual
    visual summary, and an explicit ``ACCEPT`` verdict.  Page-context text or
    unreviewed lexical retrieval records are rejected by construction.
    """
    known = {
        str(image.get("id")): image
        for image in available_images
        if isinstance(image, dict) and image.get("id") and image.get("filename")
        and str(image.get("teaching_asset_status") or "")
        != "INELIGIBLE_ISOLATED_FIGURE_COMPONENT"
    }
    briefs: list[dict[str, Any]] = []
    used_pairs: set[tuple[str, str]] = set()
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        if str(decision.get("verdict") or "").upper() != "ACCEPT":
            continue
        image_id = str(decision.get("source_image_id") or "")
        segment_id = str(decision.get("segment_id") or "")
        summary = str(decision.get("visual_summary") or "").strip()
        proposition = str(decision.get("proposition") or "").strip()
        if image_id not in known or not segment_id or not summary or not proposition:
            continue
        key = (segment_id, image_id)
        if key in used_pairs:
            continue
        used_pairs.add(key)
        brief = {
            "segment_id": segment_id,
            "source_image_id": image_id,
            "filename": str(known[image_id]["filename"]),
            "visual_summary": summary,
            "proposition": proposition,
            "layout_hint": str(decision.get("layout_hint") or "主视觉 + 简短解释"),
            "vlm_verdict": "ACCEPT",
            "vlm_reason": str(decision.get("reason") or ""),
        }
        for key in (
            "figure_id",
            "caption",
            "caption_source_span",
            "asset_kind",
            "teaching_asset_status",
        ):
            if known[image_id].get(key) is not None:
                brief[key] = known[image_id][key]
        role = str(decision.get("role") or "").strip()
        if role:
            brief["visual_role"] = role
        briefs.append(brief)
    return briefs


__all__ = ["build_visual_briefs", "build_vlm_review_context"]
