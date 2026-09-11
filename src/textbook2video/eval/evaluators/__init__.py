"""Built-in TextbookEval evaluators."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .animation_runtime import evaluate_animation_runtime
from .artifact_integrity import evaluate_artifact_integrity
from .hashes import evaluate_hashes
from .judge_results import (
    evaluate_text_judge,
    evaluate_videoqa_audience,
    evaluate_videoqa_reference,
    evaluate_vlm_readability,
)
from .layout import evaluate_layout
from .quality import evaluate_quality
from .regression import evaluate_regression
from .structure import evaluate_structure
from .content import evaluate_knowledge_grounding, evaluate_source_fidelity

if TYPE_CHECKING:
    from ..runner import Evaluator


def deterministic_evaluators() -> list["Evaluator"]:
    return [
        evaluate_hashes,
        evaluate_structure,
        evaluate_artifact_integrity,
        evaluate_quality,
        evaluate_layout,
        evaluate_animation_runtime,
        evaluate_source_fidelity,
        evaluate_knowledge_grounding,
        evaluate_regression,
    ]


def full_evaluators() -> list["Evaluator"]:
    return [
        *deterministic_evaluators(),
        evaluate_text_judge,
        evaluate_vlm_readability,
        evaluate_videoqa_audience,
        evaluate_videoqa_reference,
    ]


__all__ = [
    "deterministic_evaluators",
    "full_evaluators",
    "evaluate_animation_runtime",
    "evaluate_artifact_integrity",
    "evaluate_hashes",
    "evaluate_layout",
    "evaluate_text_judge",
    "evaluate_videoqa_audience",
    "evaluate_videoqa_reference",
    "evaluate_vlm_readability",
    "evaluate_quality",
    "evaluate_structure",
    "evaluate_source_fidelity",
    "evaluate_knowledge_grounding",
    "evaluate_regression",
]
