"""Frozen, development-only RQ1 comparison on Doc2Present source papers."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

# Keep importing LiteLLM from making an unrelated remote model-cost-map request.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

legacy = importlib.import_module("run_rq1_new_corpus")
client = legacy.client
controlled_evaluation = importlib.import_module("textbook2video.research.rq1_controlled_evaluation")
summarize_canonical_rq1 = controlled_evaluation.summarize_canonical_rq1
preference_judge = importlib.import_module("textbook2video.research.rq1_preference_judge")
build_canonical_decision_judge_prompt = preference_judge.build_canonical_decision_judge_prompt
canonical_proposal_groups = preference_judge.canonical_proposal_groups
normalize_canonical_set_judgment = preference_judge.normalize_canonical_set_judgment


CONFIG_REL = Path("configs/research/rq1_new_corpus_dev_v2.json")
DOC2PRESENT_ROOT = Path("D:/Code/vibe coding/datasets/Doc2Present")
OLD_PACKAGE_ROOT = ROOT / ".local/rq1/20261104-rq1-new-corpus-v1-final"
DEFAULT_PACKAGE_ROOT = ROOT / ".local/rq1/20261104-doc2present-rq1-v2-dev/package-run04"
RUN_REL = Path("run-01")
RUN_ID = "rq1-20261104-doc2present-v2-run01"
BASELINES = ("never_retrieve", "always_retrieve", "keyword_heuristic")
MODEL_CONDITIONS = (
    "direct_llm",
    "proposed",
    "no_source",
    "without_source_sufficiency",
    "without_retrieval_suitability",
    "without_uncertainty_handling",
)
METHODS = BASELINES + MODEL_CONDITIONS
COMPARISON_IDS = tuple(
    [f"finegym-intro-feature-{index:02d}" for index in range(1, 7)]
    + [f"justask-sec31-sentence-{index:02d}" for index in range(1, 7)]
)

FINEGYM_CLAIMS = (
    "All actions are annotated with semantic labels at three levels, namely event, set, and element.",
    "Such a semantic hierarchy provides a solid foundation for both coarse- and fine-grained action understanding.",
    "All action instances of interest in each video are identified, and they are manually decomposed into sub-actions.",
    "These annotated temporal structures also provide important support to fine-grained understanding, from another aspect.",
    "All videos in the dataset are high-resolution records of high-level professional competitions.",
    "Also, careful quality control is enforced to ensure the accuracy, reliability, and consistency of the annotations.",
)
JUSTASK_CLAIMS = (
    "We tackle the task of generating video-question-answer triplets from a large-scale instructional video dataset with transcribed spoken narration [60].",
    "This is a challenging task because of transcription errors and lack of punctuation.",
    "We also wish to obtain highly diverse data.",
    "To address these issues, we propose to leverage powerful language models trained on text data.",
    "Our approach is illustrated in Figure 3 and details are given next.",
    "We first present details about the generation procedure.",
)

FIGURES = (
    {
        "document_id": "finegym",
        "id": "finegym-fig1",
        "page": 1,
        "rect": (40, 225, 570, 470),
        "marker": "Figure 1:",
        "caption": "Figure 1: An overview of the FineGym dataset. We provide coarse-to-fine annotations both temporally and semantically. There are three levels of categorical labels; the temporal dimension is also divided into actions and sub-actions.",
        "tags": "FineGym semantic hierarchy temporal action sub-action event set element taxonomy decision tree",
    },
    {
        "document_id": "finegym",
        "id": "finegym-fig2",
        "page": 4,
        "rect": (45, 15, 555, 305),
        "marker": "Figure 2:",
        "caption": "Figure 2: FineGym organizes both the semantic and temporal annotations hierarchically. The upper part shows event, set, and element labels; the lower part depicts temporal boundaries of actions and sub-action instances.",
        "tags": "FineGym hierarchy semantic temporal events sets elements action sub-action start end time",
    },
    {
        "document_id": "finegym",
        "id": "finegym-fig4",
        "page": 5,
        "rect": (45, 25, 555, 260),
        "marker": "Figure 4:",
        "caption": "Figure 4: Examples of fine-grained sub-action instances in FineGym, including subtle distinctions among gymnastics elements.",
        "tags": "FineGym sub-action examples gymnastics element categories sequence frames subtle differences",
    },
    {
        "document_id": "finegym",
        "id": "finegym-fig5",
        "page": 7,
        "rect": (45, 25, 555, 230),
        "marker": "Figure 5:",
        "caption": "Figure 5: Person detection and pose-estimation results on a vault routine, with optical-flow features shown below.",
        "tags": "FineGym vault pose estimation person detection optical flow frames motion",
    },
    {
        "document_id": "finegym",
        "id": "finegym-fig6",
        "page": 8,
        "rect": (45, 25, 555, 245),
        "marker": "Figure 6:",
        "caption": "Figure 6: Per-class performance plots for action-recognition models across FineGym element categories and frame conditions.",
        "tags": "FineGym performance chart action recognition per class model frames temporal modeling",
    },
    {
        "document_id": "justask",
        "id": "justask-fig3",
        "page": 3,
        "rect": (45, 25, 555, 300),
        "marker": "Figure 3:",
        "caption": "Figure 3: Our automatic approach for large-scale generation of video-question-answer triplets from narrated (subtitled) videos.",
        "tags": "Just Ask narrated video automatic generation sentence punctuator answer extractor question generator ASR timestamps aligned clip",
    },
    {
        "document_id": "justask",
        "id": "justask-fig4",
        "page": 4,
        "rect": (45, 10, 555, 205),
        "marker": "Figure 4:",
        "caption": "Figure 4: Examples of video-question-answer triplets generated from narrated videos in HowToVQA69M, including relevant and failure cases.",
        "tags": "Just Ask video question answer triplet example ASR generated question visual relevance errors",
    },
    {
        "document_id": "justask",
        "id": "justask-table1",
        "page": 4,
        "rect": (300, 200, 560, 300),
        "marker": "Table 1:",
        "caption": "Table 1: Manual evaluation of question-answer generation with and without punctuation compared with a rule-based method.",
        "tags": "Just Ask Table 1 punctuation generation method correct samples QA generation failure unrelated to video comparison",
    },
    {
        "document_id": "justask",
        "id": "justask-fig5",
        "page": 5,
        "rect": (55, 25, 285, 210),
        "marker": "Figure 5:",
        "caption": "Figure 5: Overview of the VideoQA training architecture.",
        "tags": "Just Ask VideoQA architecture video question transformer answer encoder training architecture",
    },
)

SOURCE_CONTEXTS = {
    "finegym-intro-feature-01": ["finegym-fig1", "finegym-fig2"],
    "finegym-intro-feature-02": ["finegym-fig1", "finegym-fig2"],
    "finegym-intro-feature-03": ["finegym-fig2", "finegym-fig4"],
    "finegym-intro-feature-04": ["finegym-fig1", "finegym-fig2"],
    "finegym-intro-feature-05": ["finegym-fig4"],
    "finegym-intro-feature-06": ["finegym-fig1"],
    "justask-sec31-sentence-01": ["justask-fig3"],
    "justask-sec31-sentence-02": ["justask-fig3"],
    "justask-sec31-sentence-03": ["justask-fig3"],
    "justask-sec31-sentence-04": ["justask-fig3"],
    "justask-sec31-sentence-05": ["justask-fig3"],
    "justask-sec31-sentence-06": ["justask-fig3"],
}
CONTEXT_LINK_NOTES = {
    "finegym-fig1": "Caption describes semantic/temporal annotations and decision-tree construction; it is context, not independent proof of annotation quality.",
    "finegym-fig2": "Caption directly depicts semantic levels and temporal boundaries described in the surrounding feature paragraph; page distance is not treated as evidence by itself.",
    "finegym-fig4": "Caption gives examples of sub-action categories; for the high-resolution/all-videos claim this is only a sample and cannot establish the universal or resolution statement.",
    "justask-fig3": "Caption and labels depict the punctuator, answer/question models, ASR timestamps, and aligned video clips described in Section 3.1.",
    "justask-fig4": "Caption shows generated triplets and relevant/failure examples; contextual examples are not a completeness claim.",
    "justask-table1": "The source sentence explicitly points to Table 1; the table compares generation conditions and recorded outcomes.",
}


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _norm_source(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).replace("\u00ad", "")
    text = re.sub(r"(?<=[A-Za-z])-[ \t]*\n[ \t]*(?=(?:and|or)\b)", "- ", text, flags=re.I)
    text = re.sub(r"(?<=[A-Za-z0-9])-\s*\n\s*(?=[A-Za-z])", "", text)
    return re.sub(r"\s+", " ", text).strip()


_ACTIVE_CONFIG: dict | None = None


def _config() -> dict:
    return _ACTIVE_CONFIG if _ACTIVE_CONFIG is not None else _read(ROOT / CONFIG_REL)


def _comparison_ids() -> tuple[str, ...]:
    return tuple(_config().get("comparison", {}).get("proposition_ids", COMPARISON_IDS))


def _activate_config(config_path: Path) -> None:
    global CONFIG_REL, DOC2PRESENT_ROOT, RUN_ID, _ACTIVE_CONFIG
    CONFIG_REL = config_path.resolve().relative_to(ROOT.resolve())
    _ACTIVE_CONFIG = _read(config_path)
    DOC2PRESENT_ROOT = ROOT / _ACTIVE_CONFIG.get("source_root", str(DOC2PRESENT_ROOT))
    RUN_ID = _ACTIVE_CONFIG["run_id"]


def _activate_package_config(package_root: Path) -> None:
    protocol_path = package_root / RUN_REL / "protocol.json"
    if protocol_path.exists():
        protocol = _read(protocol_path)
        relative = protocol.get("git", {}).get("config_relative_path")
        if relative:
            global CONFIG_REL, DOC2PRESENT_ROOT, RUN_ID, _ACTIVE_CONFIG
            CONFIG_REL = Path(relative)
            _ACTIVE_CONFIG = _read(package_root / "code_snapshot" / relative)
            DOC2PRESENT_ROOT = ROOT / _ACTIVE_CONFIG.get("source_root", str(DOC2PRESENT_ROOT))
            RUN_ID = _ACTIVE_CONFIG["run_id"]


def _package_path(package_root: Path, relative: str | Path) -> Path:
    resolved_root = package_root.resolve()
    result = (resolved_root / relative).resolve()
    if not result.is_relative_to(resolved_root):
        raise ValueError(f"package path escapes root: {relative}")
    return result


def _copy_forams_development(package_root: Path) -> list[str]:
    source_root = OLD_PACKAGE_ROOT
    dataset = package_root / "dataset"
    if not (source_root / "dataset/source_evidence/noaa-56861-forams.json").is_file():
        raise FileNotFoundError(f"reusable Forams source package is missing: {source_root}")
    copy_files = [
        source_root / "sources/dev-forams.pdf",
        source_root / "dataset/source_evidence/noaa-56861-forams.json",
        source_root / "dataset/retrieval_catalog.json",
    ]
    for old in copy_files:
        if not old.is_file():
            raise FileNotFoundError(f"required Forams development input is missing: {old}")
        relative = old.relative_to(source_root)
        target = package_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old, target)
    for source_dir in (
        source_root / "extracted/forams/images",
        source_root / "dataset/proposition_graphs",
        source_root / "dataset/cases",
        source_root / "dataset/storyboards",
    ):
        if not source_dir.exists():
            continue
        for old in source_dir.rglob("*"):
            if not old.is_file():
                continue
            if (
                source_dir.name in {"proposition_graphs", "cases", "storyboards"}
                and "forams" not in old.name
            ):
                continue
            if source_dir.name == "images" and old.suffix.lower() not in {".jpeg", ".jpg", ".png"}:
                continue
            relative = old.relative_to(source_root)
            target = package_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(old, target)
    # Keep only the Forams candidate in the protocol-development catalog.
    old_catalog = _read(dataset / "retrieval_catalog.json")
    for asset in old_catalog.get("assets", []):
        if asset.get("source_document_id") == "noaa-56861-forams":
            path = _package_path(package_root, asset["path"])
            if not path.is_file() or _sha(path) != asset.get("sha256"):
                raise ValueError(f"Forams candidate hash mismatch: {asset.get('id')}")
    _write(
        dataset / "retrieval_catalog_forams.json",
        {
            "schema_version": old_catalog.get("schema_version"),
            "summary": {
                "policy": "reused Forams development candidate only; no new retrieval pool"
            },
            "assets": [
                asset
                for asset in old_catalog.get("assets", [])
                if asset.get("source_document_id") == "noaa-56861-forams"
            ],
        },
    )
    ids = [f"forams-intro-s{index}" for index in range(1, 5)]
    for proposition_id in ids:
        for old_root, relative in (
            (source_root, Path(f"dataset/cases/{proposition_id}/input.json")),
            (source_root, Path(f"dataset/proposition_graphs/{proposition_id}.json")),
            (source_root, Path(f"dataset/storyboards/{proposition_id}.json")),
        ):
            old = old_root / relative
            if not old.is_file():
                raise FileNotFoundError(f"Forams proposition input is missing: {old}")
            target = package_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old, target)
    return [
        "dataset/source_evidence/noaa-56861-forams.json",
        "dataset/retrieval_catalog_forams.json",
        "sources/dev-forams.pdf",
        "extracted/forams/images",
    ]


def _doc_specs() -> dict[str, dict]:
    configured = {item["document_id"]: item for item in _config()["comparison"]["source_files"]}
    return {doc_id: configured[doc_id] for doc_id in _config()["comparison"]["document_ids"]}


def _extract_caption(page_text: str, marker: str, fallback: str) -> str:
    normalized = _norm_source(page_text)
    start = normalized.find(_norm_source(marker))
    if start < 0:
        raise ValueError(f"figure/table caption marker not found: {marker}")
    tail = normalized[start:]
    next_marker = re.search(r"\b(?:Figure|Table)\s+\d+:", tail[len(marker) :], flags=re.I)
    caption = tail if next_marker is None else tail[: len(marker) + next_marker.start()]
    if len(caption) < 60:
        return fallback
    return caption[:800]


def _write_comparison_document(package_root: Path, doc_id: str, spec: dict) -> list[dict]:
    import fitz

    source_pdf = DOC2PRESENT_ROOT / spec["filename"]
    if not source_pdf.is_file():
        raise FileNotFoundError(f"Doc2Present PDF is missing: {source_pdf}")
    actual_pdf_hash = _sha(source_pdf)
    if actual_pdf_hash != spec["sha256"]:
        raise ValueError(f"Doc2Present PDF hash mismatch for {doc_id}: {actual_pdf_hash}")
    raw_pdf_rel = f"dataset/raw_sources/{doc_id}.pdf"
    raw_pdf = _package_path(package_root, raw_pdf_rel)
    raw_pdf.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_pdf, raw_pdf)
    if _sha(raw_pdf) != actual_pdf_hash:
        raise ValueError(f"copied PDF hash mismatch for {doc_id}")

    document = fitz.open(raw_pdf)
    page_text = {str(index + 1): page.get_text("text") for index, page in enumerate(document)}
    extracted_rel = f"dataset/extracted/{doc_id}-page-text.json"
    _write(_package_path(package_root, extracted_rel), page_text)
    normalized_pages = {page: _norm_source(text) for page, text in page_text.items()}

    claim_texts = spec.get("claims", FINEGYM_CLAIMS if doc_id == "finegym" else JUSTASK_CLAIMS)
    claim_page = 2 if doc_id == "finegym" else 3
    if doc_id == "justask":
        # Page 3 has the six consecutive sentences selected from Section 3.1.
        claim_page = 3
    claim_page = int(spec.get("claim_page", claim_page))
    figures = spec.get("figures", FIGURES)
    source_contexts = spec.get("source_contexts", SOURCE_CONTEXTS)
    figure_records: list[dict] = []
    source_image_by_id: dict[str, dict] = {}
    for figure in (item for item in figures if item["document_id"] == doc_id):
        figure_page = int(figure["page"])
        page = document[figure_page - 1]
        crop = page.get_pixmap(
            matrix=fitz.Matrix(2, 2), clip=fitz.Rect(figure["rect"]), alpha=False
        )
        crop_rel = f"dataset/source_images/{figure['id']}.png"
        crop_path = _package_path(package_root, crop_rel)
        crop_path.parent.mkdir(parents=True, exist_ok=True)
        crop_path.write_bytes(crop.tobytes("png"))
        if figure.get("exact_caption"):
            actual_caption = _norm_source(figure["caption"])
            if normalized_pages[str(figure_page)].count(actual_caption) != 1:
                raise ValueError(f"configured exact caption must occur once: {figure['id']}")
        else:
            actual_caption = _extract_caption(
                page_text[str(figure_page)], figure["marker"], figure["caption"]
            )
        source_image = {
            "id": figure["id"],
            "filename": crop_path.name,
            "caption": actual_caption,
            "description": figure["caption"],
            "figure_id": figure["marker"].rstrip(":"),
            "source_locator": f"{spec['filename']} PDF page {figure_page}, {figure['marker'].rstrip(':')}",
            "page_number": figure_page,
            "availability": "AVAILABLE_LOCAL",
            "teaching_asset_status": "ELIGIBLE_COMPLETE_FIGURE_REQUIRES_VLM",
            "asset_kind": "SOURCE_PDF_FIGURE_OR_TABLE_CROP",
            "rights_status": spec["rights_status"],
            "license": spec.get(
                "license",
                "arXiv non-exclusive distribution license; embedded figure/table reuse rights not independently verified",
            ),
            "local_path": crop_rel,
            "sha256": _sha(crop_path),
        }
        source_image_by_id[figure["id"]] = source_image
        figure_records.append(
            {
                "id": figure["id"],
                "title": f"{doc_id} {figure['marker'].rstrip(':')}",
                "caption": actual_caption,
                "description": figure["caption"],
                "tags": figure["tags"],
                "path": crop_rel,
                "sha256": source_image["sha256"],
                "license": source_image["license"],
                "provenance": f"{spec['source_url']} ; local Doc2Present source PDF page {figure_page} ; {actual_caption}",
                "source_url": spec["source_url"],
                "source_document_id": doc_id,
                "source_page": figure_page,
                "rights_status": spec["rights_status"],
                "status": "UNREVIEWED_CANDIDATE_RIGHTS_NOT_CLEARED_FOR_REUSE",
            }
        )

    source_units = []
    propositions = []
    context_link_manifest = []
    for index, quote in enumerate(claim_texts, start=1):
        proposition_id = (
            f"finegym-intro-feature-{index:02d}"
            if doc_id == "finegym"
            else f"justask-sec31-sentence-{index:02d}"
        )
        proposition_id = (
            spec.get("proposition_ids", [])[index - 1]
            if spec.get("proposition_ids")
            else proposition_id
        )
        source_pages = [claim_page]
        page_norm = " ".join(normalized_pages[str(page_number)] for page_number in source_pages)
        occurrence_count = page_norm.count(quote)
        if occurrence_count != 1:
            raise ValueError(
                f"source quote must occur exactly once after typography normalization: {proposition_id}, count={occurrence_count}"
            )
        start = page_norm.index(quote)
        end = start + len(quote)
        source_id = f"{proposition_id}-source"
        context_start = max(0, start - 480)
        context_end = min(len(page_norm), end + 480)
        source_units.append(
            {
                "id": source_id,
                "text": page_norm[context_start:context_end],
                "page_number": claim_page,
                "page_numbers": source_pages,
                "source_locator": (
                    f"PDF p. 2, Introduction feature paragraph, fixed consecutive sentence {index}"
                    if doc_id == "finegym"
                    else f"Section 3.1, PDF p. 3, fixed consecutive sentence {index}"
                ),
                "exact_claim_quote": quote,
                "normalized_page_span": {
                    "start": start,
                    "end": end,
                    "unit": "NFKC_linebreak_hyphen_and_whitespace_normalized_source_region_codepoint",
                    "source_pages": source_pages,
                    "end_exclusive": True,
                },
                "text_match_status": "DETERMINISTIC_NORMALIZED_LITERAL_MATCH_NOT_SEMANTIC_GOLD",
            }
        )
        source_units[-1]["source_locator"] = spec.get(
            "section_locator", source_units[-1]["source_locator"]
        )
        kp_id = f"{proposition_id}-kprop"
        propositions.append(
            {
                "id": proposition_id,
                "document_id": doc_id,
                "split": "comparison",
                "page_number": claim_page,
                "source_pages": source_pages,
                "section_locator": source_units[-1]["source_locator"],
                "original_teaching_text": quote,
                "knowledge_claim": quote,
                "narration_text": quote,
                "claim_derivation": "DETERMINISTIC_NORMALIZED_VERBATIM_SOURCE_SENTENCE",
                "pronouns_or_ellipsis_modified": False,
                "source_refs": [source_id],
                "source_unit_id": source_id,
                "source_unit_text": source_units[-1]["text"],
                "exact_claim_quote": quote,
                "local_page_normalized_char_span": source_units[-1]["normalized_page_span"],
                "source_image_ids": list(source_contexts[proposition_id]),
                "text_match_status": source_units[-1]["text_match_status"],
                "semantic_support_status": "UNCERTAIN_NOT_INDEPENDENTLY_ADJUDICATED",
                "status": "SOURCE_LINKED_NOT_HUMAN_REVIEWED",
            }
        )
        context_link_manifest.append(
            {
                "proposition_id": proposition_id,
                "source_page": claim_page,
                "source_pages": source_pages,
                "selected_source_components": [
                    {
                        "source_image_id": image_id,
                        "component_page": source_image_by_id[image_id]["page_number"],
                        "caption": source_image_by_id[image_id]["caption"],
                        "relation_status": (
                            "UNCERTAIN_CONTEXT_ONLY"
                            if (proposition_id.endswith("05") and doc_id == "finegym")
                            or (proposition_id.endswith("06") and doc_id == "finegym")
                            else "CONTEXT_LINK_NOT_SUPPORT_LABEL"
                        ),
                        "basis": CONTEXT_LINK_NOTES.get(
                            image_id, "Caption/section relationship; no same-page inference."
                        ),
                    }
                    for image_id in source_contexts[proposition_id]
                ],
            }
        )
        board_id = "segment-001"
        graph = {
            "schema_version": "p0-proposition-graph-v1.0",
            "case_id": doc_id,
            "raw_sha256": actual_pdf_hash,
            "source_evidence_path": f"dataset/source_evidence/{doc_id}.json",
            "storyboard_path": f"dataset/storyboards/{proposition_id}.json",
            "knowledge_propositions": [
                {
                    "id": kp_id,
                    "knowledge_point_id": f"{doc_id}-source-section",
                    "text": quote,
                    "source_refs": [source_id],
                    "source_anchor": quote,
                    "status": "DETERMINISTIC_NORMALIZED_VERBATIM_SOURCE_DERIVATION_NOT_HUMAN_GOLD",
                }
            ],
            "narration_propositions": [
                {
                    "id": proposition_id,
                    "segment_id": board_id,
                    "text": quote,
                    "span": {
                        "start": 0,
                        "end": len(quote),
                        "unit": "unicode_codepoint",
                        "end_exclusive": True,
                    },
                    "knowledge_proposition_ids": [kp_id],
                    "source_refs": [source_id],
                    "status": "DETERMINISTIC_NORMALIZED_VERBATIM_SOURCE_DERIVATION_NOT_HUMAN_GOLD",
                }
            ],
            "claim": "Development source derivation only; source entailment and atomicity are not human-validated.",
        }
        graph_path = package_root / "dataset/proposition_graphs" / f"{proposition_id}.json"
        _write(graph_path, graph)
        claim_input = {
            **propositions[-1],
            "source_unit_id": source_id,
            "source_unit_text": source_units[-1]["text"],
            "split": "comparison",
            "selection_index_within_document": index,
        }
        _write(package_root / "dataset/cases" / proposition_id / "input.json", claim_input)
        _write(
            package_root / "dataset/storyboards" / f"{proposition_id}.json",
            {
                "segments": [
                    {
                        "id": board_id,
                        "narration": quote,
                        "source_page_number": claim_page,
                        "source_page_numbers": source_pages,
                        "elements": [
                            {"type": "image", "source_image_id": image_id}
                            for image_id in source_contexts[proposition_id]
                        ],
                    }
                ]
            },
        )

    source_evidence = {
        "schema_version": "p0-source-evidence-v0.1",
        "document": {
            "document_id": doc_id,
            "raw_path": extracted_rel,
            "raw_sha256": actual_pdf_hash,
            "pdf_path": raw_pdf_rel,
            "pdf_sha256": actual_pdf_hash,
            "archive_record_url": spec["source_url"],
            "rights_status": spec["rights_status"],
            "status": "LOCAL_DOC2PRESENT_SOURCE_COPY_HASH_VERIFIED_RIGHTS_SCOPE_UNVERIFIED",
        },
        "source_units": source_units,
        "source_images": list(source_image_by_id.values()),
        "claim": "Source units use deterministic NFKC, line-break hyphen, and whitespace normalization. Visual links are engineering context links, not semantic support labels.",
    }
    _write(package_root / "dataset/source_evidence" / f"{doc_id}.json", source_evidence)
    return figure_records + [{"_context_link_manifest": context_link_manifest}]


def _build_frozen_inputs(package_root: Path) -> dict:
    import fitz  # noqa: F401

    dataset = package_root / "dataset"
    if dataset.exists() or (package_root / "code_snapshot").exists():
        raise FileExistsError("refusing to reuse an existing partial or frozen v2 package")
    dataset.mkdir(parents=True)
    forams_inputs = _copy_forams_development(package_root) if _config().get("development") else []
    docs = _doc_specs()
    candidate_assets = []
    context_records = []
    for doc_id in _config()["comparison"]["document_ids"]:
        records = _write_comparison_document(package_root, doc_id, docs[doc_id])
        for record in records:
            if "_context_link_manifest" in record:
                context_records.extend(record["_context_link_manifest"])
            else:
                candidate_assets.append(record)
    _write(
        dataset / "retrieval_catalog.json",
        {
            "schema_version": "p0-retrieval-catalog-local-rag-v1.0",
            "summary": {
                "policy": _config().get(
                    "candidate_pool_policy",
                    "frozen nine-figure/table source-derived candidate pool from the two comparison PDFs; no open-web fetch; no image generation",
                ),
                "coverage": _config().get(
                    "candidate_pool_coverage",
                    [
                        "hierarchy and temporal structure",
                        "fine-grained action examples",
                        "narrated-video generation pipeline",
                        "question/answer examples",
                        "punctuation comparison",
                        "VideoQA architecture",
                    ],
                ),
                "known_gaps": [
                    "No broad external licensed visual corpus",
                    "rights for source-embedded figures are not independently verified",
                    "all comparison candidates are proxy-only and acquisition reuse is fail-closed",
                ],
            },
            "assets": candidate_assets,
        },
    )
    _write(
        dataset / "source_context_links.json",
        {
            "schema_version": "engineering-source-context-map-v1",
            "status": "ENGINEERING_CONTEXT_LINKS_NOT_G0_LABELS_NOT_SEMANTIC_SUPPORT_GOLD",
            "links": context_records,
        },
    )
    docs_manifest = []
    for doc_id, spec in docs.items():
        pdf = package_root / "dataset/raw_sources" / f"{doc_id}.pdf"
        docs_manifest.append(
            {
                "document_id": doc_id,
                "source_filename": spec["filename"],
                "source_url": spec["source_url"],
                "local_pdf": f"dataset/raw_sources/{doc_id}.pdf",
                "sha256": _sha(pdf),
                "rights_status": spec["rights_status"],
                "split": "comparison",
                "planned_propositions": len(spec.get("claims", [None] * 6)),
            }
        )
    _write(
        dataset / "sample_manifest.json",
        {
            "dataset_id": _config()["dataset_id"],
            "scope": _config()["scope"],
            "split_by_document": True,
            "comparison_documents": docs_manifest,
            "comparison_proposition_ids": list(_comparison_ids()),
            "development_document_id": "noaa-56861-forams"
            if _config().get("development")
            else None,
            "development_proposition_ids": [f"forams-intro-s{index}" for index in range(1, 5)]
            if _config().get("development")
            else [],
            "selection_rule": _config()["selection"]["rule"],
            "human_labels_required": False,
            "locked_test": False,
        },
    )
    _write(
        dataset / "documents.json",
        {
            "dataset_id": _config()["dataset_id"],
            "documents": docs_manifest
            + [
                {
                    "document_id": "noaa-56861-forams",
                    "split": "development_protocol_check_only",
                    "provenance": "Copied from the prior v1 package; new predictions will be generated for this v2 run.",
                }
            ]
            if _config().get("development")
            else docs_manifest,
        },
    )
    _snapshot_code(package_root)
    return {"forams_inputs": forams_inputs, "comparison_documents": docs_manifest}


def _snapshot_code(package_root: Path) -> dict[str, str]:
    snapshot = package_root / "code_snapshot"
    relatives = [
        "scripts/run_rq1_doc2present_v2.py",
        "scripts/run_rq1_new_corpus.py",
        "src/textbook2video/research/visual_decision.py",
        "src/textbook2video/research/visual_decision_baselines.py",
        "src/textbook2video/research/visual_acquisition.py",
        "src/textbook2video/research/rq1_preference_judge.py",
        "src/textbook2video/research/rq1_controlled_evaluation.py",
        "configs/research/rq1_new_corpus_dev_v2.json",
        "tests/test_rq1_canonical_judge.py",
        "tests/test_rq1_strict_acquisition_license.py",
        "tests/test_rq1_new_corpus_runner.py",
    ]
    hashes = {}
    for relative in relatives:
        source = ROOT / relative
        if not source.is_file():
            raise FileNotFoundError(f"required source snapshot file is missing: {source}")
        target = snapshot / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        hashes[relative] = _sha(target)
    status = subprocess.run(
        ["git", "status", "--short", "--branch"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    (snapshot / "git_status.txt").write_text(status, encoding="utf-8")
    diff = subprocess.run(
        ["git", "diff", "--binary", "--", *relatives],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    (snapshot / "relevant_worktree_diff.patch").write_bytes(diff)
    hashes["code_snapshot/git_status.txt"] = _sha(snapshot / "git_status.txt")
    hashes["code_snapshot/relevant_worktree_diff.patch"] = _sha(
        snapshot / "relevant_worktree_diff.patch"
    )
    return hashes


def _require_explicit_license(config: dict) -> bool:
    """Keep strict defaults; permit a recorded, document-scoped local dev use."""
    if config.get("acquisition", {}).get("require_explicit_license", True):
        return True
    use = config.get("local_research_use", {})
    expected = {d["document_id"]: d["sha256"]
                for d in config["comparison"]["source_files"]}
    if (config.get("scope") != "DEVELOPMENT_METHOD_COMPARISON_NOT_LOCKED_TEST_NOT_FORMAL_EXPERIMENT"
            or config.get("selection", {}).get("locked_test") is not False
            or use.get("purpose") != "LOCAL_RESEARCH_PAPER_TO_VIDEO"
            or use.get("source_sha256") != expected
            or not use.get("authorization_record")):
        raise ValueError("local research use requires explicit dev scope and exact document hashes")
    return False


def _protocol(package_root: Path, code_hashes: dict[str, str]) -> dict:
    config = _config()
    tasks = []
    for proposition_id in _comparison_ids():
        doc_id = next(
            (
                doc_id
                for doc_id, spec in _doc_specs().items()
                if proposition_id in spec.get("proposition_ids", [])
            ),
            "finegym" if proposition_id.startswith("finegym-") else "justask",
        )
        task = {
            "proposition_id": proposition_id,
            "document_id": doc_id,
            "split": "comparison",
            "input_path": f"dataset/cases/{proposition_id}/input.json",
            "graph_path": f"dataset/proposition_graphs/{proposition_id}.json",
            "source_evidence_path": f"dataset/source_evidence/{doc_id}.json",
            "storyboard_path": f"dataset/storyboards/{proposition_id}.json",
            "catalog_path": "dataset/retrieval_catalog.json",
            "methods": list(METHODS),
        }
        tasks.append(task)
    development_tasks = []
    for index in range(1, 5) if config.get("development") else []:
        proposition_id = f"forams-intro-s{index}"
        development_tasks.append(
            {
                "proposition_id": proposition_id,
                "document_id": "noaa-56861-forams",
                "split": "development",
                "input_path": f"dataset/cases/{proposition_id}/input.json",
                "graph_path": f"dataset/proposition_graphs/{proposition_id}.json",
                "source_evidence_path": "dataset/source_evidence/noaa-56861-forams.json",
                "storyboard_path": f"dataset/storyboards/{proposition_id}.json",
                "catalog_path": "dataset/retrieval_catalog_forams.json",
                "methods": ["direct_llm", "proposed"],
            }
        )
    inputs = {}
    for path in sorted((package_root / "dataset").rglob("*")):
        if path.is_file():
            rel = path.relative_to(package_root).as_posix()
            inputs[rel] = {"sha256": _sha(path), "size_bytes": path.stat().st_size}
    for relative in code_hashes:
        if relative.startswith("code_snapshot/"):
            path = package_root / relative
        else:
            path = package_root / "code_snapshot" / relative
            relative = f"code_snapshot/{relative}"
        inputs[relative] = {"sha256": _sha(path), "size_bytes": path.stat().st_size}
    config_copy = package_root / "code_snapshot" / CONFIG_REL
    return {
        "schema_version": "rq1-canonical-proposal-development-v2.0",
        "dataset_id": config["dataset_id"],
        "run_id": config["run_id"],
        "scope": config["scope"],
        "created_at_utc": datetime.now(UTC).isoformat(),
        "package_root_from_run": "..",
        "git": {
            "branch": subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            ).stdout.strip(),
            "head": subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            ).stdout.strip(),
            "results_include_uncommitted_code": bool(
                subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()
            ),
            "code_snapshot_hashes": code_hashes,
            "config_sha256": _sha(config_copy),
            "config_relative_path": CONFIG_REL.as_posix(),
        },
        "environment": {
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "packages": {
                name: legacy._distribution_version(name)
                for name in ("jsonschema", "litellm", "PyMuPDF", "pydantic")
            },
            "model_family_independence": "UNVERIFIED_ALIAS_ONLY",
        },
        "conditions": {
            "never_retrieve": "existing baseline; may reuse a linked source image, never performs external retrieval",
            "always_retrieve": "existing baseline; requests retrieve for every claim, subject to shared fixed pool and strict rights/hash gates",
            "keyword_heuristic": "existing deterministic policy with the exact frozen English lexicon in configs/research/rq1_new_corpus_dev_v2.json",
            "direct_llm": "existing direct decision path; cannot read Proposed output or rationale",
            "proposed": "existing staged source-conditioned decision path",
            "no_source": "existing ablation removes model-visible source text, captions, refs and source image inputs",
            "without_source_sufficiency": "existing ablation removes only the explicit source-sufficiency criterion/output",
            "without_retrieval_suitability": "existing ablation removes only the explicit retrieval-suitability criterion/output",
            "without_uncertainty_handling": "existing ablation removes only the uncertainty output requirement; safety gates remain enabled",
        },
        "models": config["models"],
        "judges": {
            **config["decision_judge"],
            "method_names_and_rationales_sent": False,
            "prompt_template": "canonical decision fields; query/generation prose and acquisition result excluded",
        },
        "assets": {
            **config["acquisition"],
            "formal_acceptance": False,
            "candidate_pool": "dataset/retrieval_catalog.json",
            "candidate_count": len(
                _read(package_root / "dataset/retrieval_catalog.json")["assets"]
            ),
            "require_explicit_license": _require_explicit_license(config),
            "local_research_use": config.get("local_research_use"),
            "candidate_rights": "Original rights metadata retained; execution use follows the recorded scoped policy.",
        },
        "selection": {
            **config["selection"],
            "comparison_claim_ids": list(_comparison_ids()),
            "visual_context_map_path": "dataset/source_context_links.json",
        },
        "budget": {
            "max_transport_calls": config["max_transport_calls"],
            "allocation": config["call_allocation"],
            "automatic_retries": 0,
            "stop_on_transport_failure": config.get("stop_on_transport_failure", False),
            "same_task_retries": "FORBIDDEN; failures and interrupted unknown results count and remain in planned denominator",
            "resume_budget_reset": False,
            "reserve_not_used_to_add_conditions": True,
        },
        "source_files": inputs,
        "tasks": tasks,
        "planned_development_tasks": development_tasks,
        "asset_review_rule": config["material_review"],
        "primary_metrics": [
            "planned-denominator output coverage, action, uncertainty/abstention, and failure",
            "canonical proposal grouping with deterministic method mapping",
            "LLM proxy acceptable/preferred membership, source sufficiency/action-fit labels, ties and order sensitivity",
            "fixed-pool acquisition outcomes separated from decision-layer preference",
            "material object ID/hash disagreement, proxy fit, source/license/hash status, formal acceptance state",
            "actual transfer count, token usage when returned, elapsed time, and provider fee when exposed",
        ],
        "claim_boundary": "Development comparison only; no human gold, truth accuracy, learning effect, formal experiment, or superiority claim.",
    }


def prepare(package_root: Path) -> Path:
    package_root = package_root.resolve()
    run_dir = package_root / RUN_REL
    if run_dir.exists() or (package_root / "protocol.json").exists():
        raise FileExistsError(f"refusing to overwrite existing v2 package/run: {package_root}")
    if package_root.exists() and any(package_root.iterdir()):
        raise FileExistsError(f"refusing to reuse a nonempty package directory: {package_root}")
    package_root.mkdir(parents=True, exist_ok=True)
    _build_frozen_inputs(package_root)
    code_hashes = _snapshot_code(package_root)
    config_copy = package_root / "code_snapshot" / CONFIG_REL
    config_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / CONFIG_REL, config_copy)
    code_hashes[CONFIG_REL.as_posix()] = _sha(config_copy)
    protocol = _protocol(package_root, code_hashes)
    run_dir.mkdir(parents=True)
    _write(run_dir / "protocol.json", protocol)
    _write(run_dir / "calls.json", [])
    _write(
        run_dir / "prepare.json",
        {
            "status": "FROZEN_INPUTS_READY_NO_MODEL_CALLS",
            "run_id": protocol["run_id"],
            "protocol_sha256": _sha(run_dir / "protocol.json"),
            "source_file_count": len(protocol["source_files"]),
            "comparison_propositions": len(protocol["tasks"]),
            "development_propositions": len(protocol["planned_development_tasks"]),
            "candidate_count": protocol["assets"]["candidate_count"],
            "model_calls": 0,
        },
    )
    _refresh_report(package_root, run_dir, protocol)
    return run_dir


def _protocol_path(run_dir: Path) -> Path:
    return run_dir / "protocol.json"


def _method_rows(run_dir: Path, task: dict) -> dict[str, dict | None]:
    return {
        method: legacy._method_row(run_dir, task["split"], method, task["proposition_id"])
        for method in task["methods"]
    }


def _source_hashes(package_root: Path, task: dict) -> dict[str, str]:
    evidence = _read(package_root / task["source_evidence_path"])
    hashes = {}
    for item in evidence.get("source_images", []):
        if not isinstance(item, dict) or not item.get("id"):
            continue
        image_path = _package_path(package_root, str(item.get("local_path") or ""))
        if not image_path.is_file():
            raise FileNotFoundError(f"linked source visual is missing: {item.get('id')}")
        actual = _sha(image_path)
        if item.get("sha256") != actual:
            raise ValueError(f"linked source visual hash mismatch: {item.get('id')}")
        hashes[str(item["id"])] = actual
    return hashes


def _source_context(package_root: Path, task: dict) -> tuple[list[dict], list[str], list[str], str]:
    claim = _read(package_root / task["input_path"])
    evidence = _read(package_root / task["source_evidence_path"])
    source_units = {str(item["id"]): item for item in evidence.get("source_units", [])}
    source_unit_ids = [str(value) for value in claim.get("source_refs", [])]
    if any(source_id not in source_units for source_id in source_unit_ids):
        raise ValueError(f"unresolved source reference for {task['proposition_id']}")
    storyboard = _read(package_root / task["storyboard_path"])
    segment = next(
        item
        for item in storyboard.get("segments", [])
        if item.get("id")
        == _read(package_root / task["graph_path"])["narration_propositions"][0]["segment_id"]
    )
    linked_ids = [
        str(element.get("source_image_id"))
        for element in segment.get("elements", [])
        if isinstance(element, dict)
        and element.get("type") == "image"
        and element.get("source_image_id")
    ]
    images = {str(item["id"]): item for item in evidence.get("source_images", []) if item.get("id")}
    if len(linked_ids) != len(set(linked_ids)) or any(
        image_id not in images for image_id in linked_ids
    ):
        raise ValueError(f"invalid explicit source visual links for {task['proposition_id']}")
    source_text = [
        {
            "id": source_id,
            "source_locator": source_units[source_id].get("source_locator"),
            "text": source_units[source_id].get("text"),
            "exact_claim_quote": source_units[source_id].get("exact_claim_quote"),
        }
        for source_id in source_unit_ids
    ]
    visual_inventory = [
        {
            key: images[image_id].get(key)
            for key in (
                "id",
                "caption",
                "description",
                "source_locator",
                "page_number",
                "availability",
                "teaching_asset_status",
                "rights_status",
                "license",
            )
        }
        for image_id in linked_ids
    ]
    context = [{"source_units": source_text, "source_visual_inventory": visual_inventory}]
    image_paths = [
        str(_package_path(package_root, images[image_id]["local_path"])) for image_id in linked_ids
    ]
    image_labels = [f"source-image-{index:02d}" for index in range(1, len(linked_ids) + 1)]
    return context, image_paths, image_labels, str(claim["knowledge_claim"])


def _call_model(
    *,
    package_root: Path,
    run_dir: Path,
    protocol: dict,
    ledger: list[dict],
    task_key: str,
    stage: str,
    model: str,
    prompt: str,
    images: list[str],
    max_tokens: int,
    system_prompt: str,
) -> tuple[str | None, dict]:
    existing = next((item for item in ledger if item.get("task_key") == task_key), None)
    if existing:
        raise ValueError(
            f"this task key has already been reserved; repeat calls are forbidden: {task_key}"
        )
    if len(ledger) >= int(protocol["budget"]["max_transport_calls"]):
        raise RuntimeError("RQ1_DOC2PRESENT_V2_TRANSPORT_BUDGET_EXHAUSTED")
    call_id = len(ledger) + 1
    prompt_rel = f"prompts/{call_id:03d}-{legacy._safe_id(task_key)}.txt"
    legacy._write_text(run_dir / prompt_rel, prompt)
    image_records = []
    for image_path in images:
        path = Path(image_path)
        image_records.append({"sha256": _sha(path), "name": path.name})
    entry = {
        "call_id": call_id,
        "task_key": task_key,
        "stage": stage,
        "model_alias": model,
        "provider": "ECNU OpenAI-compatible endpoint",
        "endpoint_host": urlparse(legacy.LLM_BASE_URL).hostname if legacy.LLM_BASE_URL else None,
        "status": "STARTED",
        "reserved_before_transport": True,
        "prompt_path": prompt_rel,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "images": image_records,
        "usage": None,
        "cost_usd": None,
        "elapsed_sec": None,
    }
    ledger.append(entry)
    _write(run_dir / "calls.json", ledger)
    usage_info: dict[str, Any] = {}
    original_completion = client.litellm.completion if client.litellm is not None else None

    def observed_completion(*args, **kwargs):
        response = original_completion(*args, **kwargs)
        usage = getattr(response, "usage", None)
        if usage is not None:
            try:
                usage_info["usage"] = usage.model_dump(exclude_none=True)
            except AttributeError:
                usage_info["usage"] = dict(usage)
        hidden = getattr(response, "_hidden_params", None)
        if isinstance(hidden, dict) and hidden.get("response_cost") is not None:
            usage_info["cost_usd"] = hidden["response_cost"]
        return response

    started = time.monotonic()
    if original_completion:
        client.litellm.completion = observed_completion
    try:
        call_kwargs = {
            "system_prompt": system_prompt,
            "model": model,
            "temperature": protocol["models"]["temperature"],
            "max_tokens": max_tokens,
            "timeout": protocol["models"]["timeout_sec"],
            "num_retries": 0,
            "max_retries": 0,
        }
        if client.litellm is not None:
            call_kwargs["caching"] = False
        if images:
            raw = client.chat_with_images(prompt, images, **call_kwargs)
        else:
            raw = client.chat_with_system(prompt, **call_kwargs)
        redacted = client.redact_response_text(str(raw))
        entry.update(status="OK", raw_response=redacted, **usage_info)
        return str(raw), entry
    except Exception as exc:
        entry.update(
            status="FAILED",
            error_type=type(exc).__name__,
            error_message=client.redact_response_text(str(exc))[:800],
            **usage_info,
        )
        return None, entry
    finally:
        entry["elapsed_sec"] = round(time.monotonic() - started, 3)
        _write(run_dir / "calls.json", ledger)
        if original_completion:
            client.litellm.completion = original_completion


def _judge_output_path(run_dir: Path, task: dict, alias: str, order: str) -> Path:
    return (
        run_dir
        / "judges"
        / (f"{legacy._safe_id(task['proposition_id'])}-{legacy._safe_id(alias)}-{order}.json")
    )


def _parse_json_response(raw: str) -> dict:
    """Parse a saved model response without repairing or inferring its contents."""
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Judge response must be a JSON object")
    return value


def _judge_one(
    *,
    package_root: Path,
    run_dir: Path,
    protocol: dict,
    task: dict,
    alias: str,
    order: str,
    ledger: list[dict],
) -> dict:
    output_path = _judge_output_path(run_dir, task, alias, order)
    if output_path.is_file():
        return _read(output_path)
    rows = _method_rows(run_dir, task)
    if any(not row or row.get("status") != "OK" for row in rows.values()):
        result = {
            "status": "SKIPPED_INCOMPLETE_METHOD_OUTPUT",
            "proposition_id": task["proposition_id"],
            "judge_alias": alias,
            "display_order": order,
            "planned": True,
            "model_calls": 0,
        }
        _write(output_path, result)
        return result

    groups = canonical_proposal_groups(rows, source_image_hashes=_source_hashes(package_root, task))
    proposal_path = (
        run_dir / "canonical_proposals" / f"{legacy._safe_id(task['proposition_id'])}.json"
    )
    proposal_record = {
        "proposition_id": task["proposition_id"],
        "document_id": task["document_id"],
        "method_to_proposal": groups["method_to_proposal"],
        "method_views": groups["method_views"],
        "material_by_method": groups["material_by_method"],
        "groups": groups["groups"],
        "prompt_fields": ["action", "decision_state", "uncertainty", "object_reference"],
        "excluded_from_decision_prompt": [
            "method_id",
            "method rationale",
            "retrieval query",
            "acceptance criteria",
            "generation prose",
            "acquisition status",
            "candidate captions for retrieved assets",
        ],
    }
    if proposal_path.exists():
        if _read(proposal_path) != proposal_record:
            raise ValueError(f"canonical proposal record drift: {task['proposition_id']}")
    else:
        _write(proposal_path, proposal_record)

    source_context, image_paths, image_labels, proposition_text = _source_context(
        package_root, task
    )
    proposals = [
        {"proposal_id": group["proposal_id"], **group["view"]} for group in groups["groups"]
    ]
    prompt = build_canonical_decision_judge_prompt(
        proposition_id=task["proposition_id"],
        proposition_text=proposition_text,
        source_context=source_context,
        proposals=proposals,
        display_order=order,
        attached_image_labels=image_labels,
    )
    canonical_hash = hashlib.sha256(
        json.dumps(
            {"source_context": source_context, "proposals": proposals},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    task_key = f"decision_judge:{task['proposition_id']}:{alias}:{order}"
    raw, entry = _call_model(
        package_root=package_root,
        run_dir=run_dir,
        protocol=protocol,
        ledger=ledger,
        task_key=task_key,
        stage="canonical_decision_layer_judge",
        model=alias,
        prompt=prompt,
        images=image_paths,
        max_tokens=protocol["models"]["judge_max_tokens"],
        system_prompt="You are a careful independent instructional-visual decision evaluator. Return JSON only.",
    )
    if raw is None:
        result = {
            "status": "FAILED_TRANSPORT",
            "proposition_id": task["proposition_id"],
            "document_id": task["document_id"],
            "judge_alias": alias,
            "display_order": order,
            "planned": True,
            "method_to_proposal": groups["method_to_proposal"],
            "canonical_view_sha256": canonical_hash,
            "model_calls": 1,
            "error_type": entry.get("error_type"),
            "error_message": entry.get("error_message"),
        }
        _write(output_path, result)
        return result
    try:
        parsed = _parse_json_response(raw)
        judgment = normalize_canonical_set_judgment(
            parsed,
            eligible_proposal_ids=[item["proposal_id"] for item in proposals],
            proposition_id=task["proposition_id"],
            judge_alias=alias,
            display_order=order,
        )
        status = "OK"
        parse_error = None
    except Exception as exc:
        judgment = None
        status = "INVALID_RESPONSE"
        parse_error = {"type": type(exc).__name__, "message": str(exc)[:800]}
    result = {
        "status": status,
        "proposition_id": task["proposition_id"],
        "document_id": task["document_id"],
        "judge_alias": alias,
        "display_order": order,
        "planned": True,
        "method_to_proposal": groups["method_to_proposal"],
        "canonical_view_sha256": canonical_hash,
        "proposal_record_path": proposal_path.relative_to(package_root).as_posix(),
        "method_names_sent": False,
        "method_rationales_sent": False,
        "model_calls": 1,
        "call_id": entry["call_id"],
        "judgment": judgment,
        "parse_error": parse_error,
    }
    _write(output_path, result)
    return result


def _asset_candidate_for_row(package_root: Path, row: dict) -> dict | None:
    acquisition = row.get("acquisition") or {}
    asset = legacy._asset_status(acquisition)
    local_path = asset.get("local_path")
    candidate_id = (
        asset.get("catalog_candidate_id")
        or asset.get("source_image_id")
        or asset.get("best_candidate_id")
        or asset.get("asset_id")
    )
    candidate = legacy._asset_by_id(package_root, str(candidate_id)) if candidate_id else None
    if local_path:
        path = _package_path(package_root, local_path)
    elif candidate and candidate.get("path"):
        path = _package_path(package_root, candidate["path"])
    else:
        return None
    if not path.is_file():
        return None
    actual_hash = _sha(path)
    expected_hash = asset.get("sha256") or (candidate or {}).get("sha256")
    if expected_hash and expected_hash != actual_hash:
        raise ValueError(f"material proxy input hash mismatch for {candidate_id}")
    if not candidate:
        candidate = {
            "id": candidate_id,
            "path": str(path.relative_to(package_root).as_posix()),
            "sha256": actual_hash,
            "caption": asset.get("caption"),
            "license": asset.get("license") or asset.get("rights_status"),
            "provenance": asset.get("source_locator"),
        }
    return {
        "candidate": candidate,
        "path": path,
        "sha256": actual_hash,
        "object_id": str(candidate_id or candidate.get("id") or "unknown"),
        "acquisition": asset,
    }


def _material_review_plan(package_root: Path, run_dir: Path, protocol: dict) -> dict:
    candidates: dict[tuple[str, str], dict] = {}
    not_materialized = []
    method_order = list(protocol["tasks"][0]["methods"])
    for task in protocol["tasks"]:
        for method in method_order:
            row = legacy._method_row(run_dir, "comparison", method, task["proposition_id"])
            if not row or row.get("status") != "OK":
                continue
            action = str((row.get("decision") or {}).get("action") or "")
            if action not in {"reuse", "retrieve", "generate"}:
                continue
            if action == "generate":
                not_materialized.append(
                    {
                        "proposition_id": task["proposition_id"],
                        "method_id": method,
                        "action": action,
                        "status": legacy._asset_status(row.get("acquisition") or {}).get("status"),
                        "reason": "Generation is disabled; this is a request, not a materialized visual.",
                    }
                )
                continue
            material = _asset_candidate_for_row(package_root, row)
            if not material:
                not_materialized.append(
                    {
                        "proposition_id": task["proposition_id"],
                        "method_id": method,
                        "action": action,
                        "status": legacy._asset_status(row.get("acquisition") or {}).get("status"),
                        "reason": "No local file with a verifiable object hash was available for proxy review.",
                    }
                )
                continue
            key = (task["proposition_id"], material["sha256"])
            item = candidates.setdefault(
                key,
                {
                    "proposition_id": task["proposition_id"],
                    "document_id": task["document_id"],
                    "object_id": material["object_id"],
                    "sha256": material["sha256"],
                    "candidate_path": material["path"].relative_to(package_root).as_posix(),
                    "candidate": material["candidate"],
                    "acquisition_status": material["acquisition"].get("status"),
                    "method_ids": [],
                },
            )
            if material["sha256"] != item["sha256"]:
                raise AssertionError("same proposition+hash dedup key changed content")
            if method not in item["method_ids"]:
                item["method_ids"].append(method)

    ordered = list(candidates.values())
    cap = int(protocol["asset_review_rule"]["maximum_calls"])
    selected, excluded = ordered[:cap], ordered[cap:]
    plan = {
        "schema_version": "rq1-material-review-selection-v1",
        "rule": protocol["asset_review_rule"]["selection_rule"],
        "selection_is_proxy_only": True,
        "maximum_calls": cap,
        "unique_material_objects_found": len(ordered),
        "selected": selected,
        "not_selected_over_cap": excluded,
        "not_materialized_or_unresolvable": not_materialized,
    }
    plan_path = run_dir / "asset_review_plan.json"
    if plan_path.exists() and _read(plan_path) != plan:
        raise ValueError("material review selection changed after it was frozen")
    if not plan_path.exists():
        _write(plan_path, plan)
    return plan


def _asset_review_prompt(package_root: Path, item: dict, task: dict) -> str:
    claim = _read(package_root / task["input_path"])
    evidence = _read(package_root / task["source_evidence_path"])
    unit = next(
        source for source in evidence["source_units"] if source["id"] in claim["source_refs"]
    )
    candidate = item["candidate"]
    payload = {
        "task": "Assess only the visual fit of this exact candidate image for the source claim; this is an LLM/VLM proxy, not formal acceptance.",
        "source_claim": claim["knowledge_claim"],
        "source_context": unit["text"],
        "source_locator": unit["source_locator"],
        "candidate": {
            "anonymous_label": "candidate-image-01",
            "caption": candidate.get("caption"),
            "source_locator": candidate.get("source_page") or candidate.get("provenance"),
        },
        "rules": [
            "Use visible pixels and source caption; topic similarity alone is insufficient.",
            "Do not infer formal source/license acceptance from visual fit.",
            "Distinguish visible evidence, semantic relation, missing relation, redundancy, and uncertainty.",
            "Return JSON only and do not guess when the image is unclear.",
        ],
        "output": {
            "fit": "MATCH|PARTIAL|MISMATCH|UNCERTAIN",
            "visible_evidence": "brief description tied to pixels",
            "claim_relation": "brief explanation tied to the exact claim",
            "redundant_or_decorative": False,
            "uncertainty": None,
        },
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)


def _review_materials(
    package_root: Path, run_dir: Path, protocol: dict, ledger: list[dict]
) -> list[dict]:
    plan = _material_review_plan(package_root, run_dir, protocol)
    results = []
    for item in plan["selected"]:
        key_id = f"{legacy._safe_id(item['proposition_id'])}-{item['sha256'][:16]}"
        output_path = run_dir / "asset_reviews" / f"{key_id}.json"
        if output_path.exists():
            results.append(_read(output_path))
            continue
        task_key = f"material_review:{item['proposition_id']}:{item['sha256']}"
        existing = next((entry for entry in ledger if entry.get("task_key") == task_key), None)
        if existing:
            result = {
                "status": "INTERRUPTED_REMOTE_RESULT_UNKNOWN",
                "proposition_id": item["proposition_id"],
                "sha256": item["sha256"],
                "method_ids": item["method_ids"],
                "model_calls": 1,
                "formal_acceptance": False,
                "retry": "FORBIDDEN_FOR_THIS_RESERVED_TASK",
            }
            _write(output_path, result)
            results.append(result)
            continue
        task = next(
            task for task in protocol["tasks"] if task["proposition_id"] == item["proposition_id"]
        )
        prompt = _asset_review_prompt(package_root, item, task)
        raw, entry = _call_model(
            package_root=package_root,
            run_dir=run_dir,
            protocol=protocol,
            ledger=ledger,
            task_key=task_key,
            stage="material_fit_proxy_review",
            model=protocol["models"]["asset_review_model"],
            prompt=prompt,
            images=[str(_package_path(package_root, item["candidate_path"]))],
            max_tokens=protocol["models"]["asset_review_max_tokens"],
            system_prompt="You are a careful visual candidate-fit evaluator. Return JSON only.",
        )
        result = {
            "proposition_id": item["proposition_id"],
            "document_id": item["document_id"],
            "method_ids": item["method_ids"],
            "object_id": item["object_id"],
            "asset_sha256": item["sha256"],
            "acquisition_status": item["acquisition_status"],
            "candidate_path": item["candidate_path"],
            "rights_status": item["candidate"].get("rights_status")
            or item["candidate"].get("license"),
            "formal_acceptance": False,
            "proxy_status": "FAILED_TRANSPORT" if raw is None else "INVALID_RESPONSE",
            "model_alias": protocol["models"]["asset_review_model"],
            "model_calls": 1,
            "call_id": entry["call_id"],
            "judgment": None,
        }
        if raw is not None:
            try:
                parsed = legacy._parse_json(raw)
                if parsed.get("fit") not in {"MATCH", "PARTIAL", "MISMATCH", "UNCERTAIN"}:
                    raise ValueError("fit is invalid")
                if not str(parsed.get("visible_evidence") or "").strip():
                    raise ValueError("visible_evidence is required")
                result.update(proxy_status="PROXY_REVIEWED", judgment=parsed)
            except Exception as exc:
                result["parse_error"] = {"type": type(exc).__name__, "message": str(exc)[:500]}
        _write(output_path, result)
        results.append(result)
    return results


def _all_prediction_rows(run_dir: Path, protocol: dict) -> list[dict]:
    rows = []
    for split, tasks, conditions in (
        ("development", protocol["planned_development_tasks"], ["direct_llm", "proposed"]),
        ("comparison", protocol["tasks"], list(METHODS)),
    ):
        for task in tasks:
            for method in conditions:
                row = legacy._method_row(run_dir, split, method, task["proposition_id"])
                if row is not None:
                    rows.append(row)
    return rows


def _all_judge_rows(run_dir: Path, protocol: dict) -> list[dict]:
    rows = []
    for task in protocol["tasks"]:
        for alias in protocol["models"]["judge_models"]:
            for order in ("forward", "reverse"):
                path = _judge_output_path(run_dir, task, alias, order)
                if path.is_file():
                    rows.append(_read(path))
    return rows


def _call_summary(ledger: list[dict], *, budget_limit: int = 160) -> dict:
    stages: dict[str, int] = {}
    statuses: dict[str, int] = {}
    prompt_tokens = completion_tokens = total_tokens = 0
    known_costs: list[float] = []
    elapsed_values = []
    usage_known = False
    for entry in ledger:
        stage = str(entry.get("stage") or "UNKNOWN")
        status = str(entry.get("status") or "UNKNOWN")
        stages[stage] = stages.get(stage, 0) + 1
        statuses[status] = statuses.get(status, 0) + 1
        usage = entry.get("usage") or {}
        if isinstance(usage, dict):
            prompt_value = usage.get("prompt_tokens", usage.get("input_tokens"))
            completion_value = usage.get("completion_tokens", usage.get("output_tokens"))
            total_value = usage.get("total_tokens")
            if prompt_value is not None or completion_value is not None:
                usage_known = True
                prompt_tokens += int(prompt_value or 0)
                completion_tokens += int(completion_value or 0)
            if total_value is not None:
                total_tokens += int(total_value)
        cost = entry.get("cost_usd")
        if isinstance(cost, (int, float)):
            known_costs.append(float(cost))
        elapsed = entry.get("elapsed_sec")
        if isinstance(elapsed, (int, float)):
            elapsed_values.append(float(elapsed))
    return {
        "actual_transport_attempts": len(ledger),
        "budget_limit": budget_limit,
        "remaining_budget": budget_limit - len(ledger),
        "stage_counts": dict(sorted(stages.items())),
        "status_counts": dict(sorted(statuses.items())),
        "prompt_tokens": prompt_tokens if usage_known else None,
        "completion_tokens": completion_tokens if usage_known else None,
        "total_tokens": total_tokens if usage_known and total_tokens else None,
        "request_elapsed_seconds_sum": round(sum(elapsed_values), 3),
        "provider_cost_usd": round(sum(known_costs), 6) if known_costs else None,
        "provider_cost_unknown_attempts": sum(entry.get("cost_usd") is None for entry in ledger),
        "automatic_retries": 0,
        "image_generation_calls": 0,
        "tts_calls": 0,
        "recording_calls": 0,
        "health_check_calls": 0,
    }


def _judge_action_sensitivity(run_dir: Path, protocol: dict, judge_rows: list[dict]) -> dict:
    """Compare Judge sets after projecting canonical proposals to action profiles."""
    indexed = {
        (row.get("proposition_id"), row.get("judge_alias"), row.get("display_order")): row
        for row in judge_rows
    }
    profiles: dict[tuple[str, str, str], dict | None] = {}
    for task in protocol["tasks"]:
        record_path = (
            run_dir / "canonical_proposals" / f"{legacy._safe_id(task['proposition_id'])}.json"
        )
        if not record_path.is_file():
            continue
        record = _read(record_path)
        views = {item["proposal_id"]: item["view"] for item in record.get("groups", [])}
        for alias in protocol["models"]["judge_models"]:
            for order in ("forward", "reverse"):
                row = indexed.get((task["proposition_id"], alias, order))
                if not row or row.get("status") != "OK":
                    profiles[(task["proposition_id"], alias, order)] = None
                    continue
                judgment = row.get("judgment") or {}

                def project(field: str) -> dict:
                    action_set = set()
                    profile_set = set()
                    for proposal_id in judgment.get(field, []):
                        view = views.get(proposal_id)
                        if not view:
                            continue
                        action = str(view.get("action") or "UNKNOWN")
                        uncertainty = view.get("uncertainty") or {}
                        action_set.add(action)
                        profile_set.add(
                            (
                                action,
                                str(view.get("decision_state") or "UNKNOWN"),
                                bool(uncertainty.get("uncertain")),
                                bool(uncertainty.get("abstain")),
                            )
                        )
                    return {
                        "actions": sorted(action_set),
                        "action_uncertainty_profiles": [list(item) for item in sorted(profile_set)],
                    }

                profiles[(task["proposition_id"], alias, order)] = {
                    "status": "ABSTAIN" if judgment.get("abstain") else "JUDGED",
                    "abstain": bool(judgment.get("abstain")),
                    "preferred": project("preferred_proposal_ids"),
                    "acceptable": project("acceptable_proposal_ids"),
                    "uncertain_actions": project("uncertain_proposal_ids"),
                }

    def compare(left: dict, right: dict) -> dict:
        return {
            "preferred_action_set_changed": left["preferred"]["actions"]
            != right["preferred"]["actions"],
            "preferred_action_profile_changed": (
                left["preferred"]["action_uncertainty_profiles"]
                != right["preferred"]["action_uncertainty_profiles"]
                or left["abstain"] != right["abstain"]
            ),
            "acceptable_action_set_changed": left["acceptable"]["actions"]
            != right["acceptable"]["actions"],
            "acceptable_action_profile_changed": (
                left["acceptable"]["action_uncertainty_profiles"]
                != right["acceptable"]["action_uncertainty_profiles"]
            ),
            "abstention_changed": left["abstain"] != right["abstain"],
        }

    order_pairs = []
    alias_pairs = []
    aliases = list(protocol["models"]["judge_models"])
    for task in protocol["tasks"]:
        proposition_id = task["proposition_id"]
        for alias in aliases:
            forward = profiles.get((proposition_id, alias, "forward"))
            reverse = profiles.get((proposition_id, alias, "reverse"))
            if forward is not None and reverse is not None:
                order_pairs.append(
                    {
                        "proposition_id": proposition_id,
                        "judge_alias": alias,
                        **compare(forward, reverse),
                    }
                )
        for order in ("forward", "reverse"):
            left = profiles.get((proposition_id, aliases[0], order)) if aliases else None
            right = profiles.get((proposition_id, aliases[1], order)) if len(aliases) > 1 else None
            if left is not None and right is not None:
                alias_pairs.append(
                    {
                        "proposition_id": proposition_id,
                        "display_order": order,
                        "judge_aliases": aliases[:2],
                        **compare(left, right),
                    }
                )

    def summarize(rows: list[dict], name: str) -> dict:
        fields = (
            "preferred_action_set_changed",
            "preferred_action_profile_changed",
            "acceptable_action_set_changed",
            "acceptable_action_profile_changed",
            "abstention_changed",
        )
        return {
            "comparison": name,
            "planned_pairs": (
                len(protocol["tasks"]) * len(aliases)
                if name == "forward_vs_reverse_within_alias"
                else len(protocol["tasks"]) * 2
            ),
            "valid_pairs": len(rows),
            **{field: sum(bool(row[field]) for row in rows) for field in fields},
            "pairs": rows,
        }

    return {
        "projection": "action plus decision_state and uncertainty profile; object identity remains separately reported",
        "alias_identity_independence": "UNDERLYING_MODEL_FAMILIES_UNVERIFIED",
        "order_pairs": summarize(order_pairs, "forward_vs_reverse_within_alias"),
        "alias_pairs": summarize(alias_pairs, "alias_1_vs_alias_2_same_display_order"),
    }


def _refresh_report(
    package_root: Path, run_dir: Path, protocol: dict, *, persist: bool = True
) -> dict:
    predictions = _all_prediction_rows(run_dir, protocol)
    judges = _all_judge_rows(run_dir, protocol)
    comparison_predictions = [row for row in predictions if row.get("split") == "comparison"]
    method_summary = summarize_canonical_rq1(
        method_ids=list(METHODS),
        proposition_ids=[task["proposition_id"] for task in protocol["tasks"]],
        predictions=comparison_predictions,
        judge_results=judges,
        judge_aliases=list(protocol["models"]["judge_models"]),
    )
    per_claim = []
    for task in protocol["tasks"]:
        methods = {}
        for method in METHODS:
            row = legacy._method_row(run_dir, "comparison", method, task["proposition_id"])
            if not row:
                methods[method] = {
                    "status": "NOT_RUN",
                    "action": "NOT_RUN",
                    "acquisition_status": "NOT_RUN",
                }
                continue
            decision = row.get("decision") or {}
            assets = (row.get("acquisition") or {}).get("assets") or []
            asset = assets[0] if assets and isinstance(assets[0], dict) else {}
            methods[method] = {
                "status": row.get("status"),
                "action": decision.get("action", "UNKNOWN"),
                "decision_state": decision.get("decision_state"),
                "uncertain": decision.get("uncertain"),
                "abstain": decision.get("abstain"),
                "acquisition_status": asset.get("status", "MISSING"),
                "object_id": asset.get("catalog_candidate_id")
                or asset.get("source_image_id")
                or asset.get("asset_id")
                or asset.get("best_candidate_id"),
                "sha256": asset.get("sha256"),
                "rights_status": asset.get("rights_status") or asset.get("license"),
            }
        per_claim.append(
            {
                "proposition_id": task["proposition_id"],
                "document_id": task["document_id"],
                "claim": _read(package_root / task["input_path"])["knowledge_claim"],
                "methods": methods,
            }
        )

    axis_counts: dict[str, dict[str, dict[str, int]]] = {
        method: {
            axis: {}
            for axis in ("visual_need", "source_sufficiency", "action_fit", "uncertainty_fit")
        }
        for method in METHODS
    }
    for row in judges:
        if row.get("status") != "OK":
            continue
        judgment = row.get("judgment") or {}
        mapping = row.get("method_to_proposal") or {}
        for method in METHODS:
            proposal_id = mapping.get(method)
            assessment = (judgment.get("assessment_by_proposal") or {}).get(proposal_id, {})
            for axis, label in assessment.items():
                counts = axis_counts[method].setdefault(axis, {})
                counts[label] = counts.get(label, 0) + 1
    for method in METHODS:
        for axis, counts in axis_counts[method].items():
            axis_counts[method][axis] = dict(sorted(counts.items()))

    asset_plan_path = run_dir / "asset_review_plan.json"
    asset_plan = _read(asset_plan_path) if asset_plan_path.is_file() else None
    asset_review_files = (
        sorted((run_dir / "asset_reviews").glob("*.json"))
        if (run_dir / "asset_reviews").exists()
        else []
    )
    asset_review_results = [_read(path) for path in asset_review_files]
    report = {
        "status": "RUN_COMPLETE"
        if (run_dir / "output_manifest.json").is_file()
        else "RUN_IN_PROGRESS_OR_PREPARED",
        "dataset_id": protocol["dataset_id"],
        "run_id": protocol["run_id"],
        "protocol_sha256": _sha(run_dir / "protocol.json"),
        "scope": protocol["scope"],
        "git": protocol["git"],
        "sample": {
            "comparison_documents": sorted({task["document_id"] for task in protocol["tasks"]}),
            "comparison_propositions_planned": len(protocol["tasks"]),
            "development_propositions_planned": len(protocol["planned_development_tasks"]),
            "candidate_pool_size": protocol["assets"]["candidate_count"],
            "selection_is_document_level": True,
            "locked_test": False,
        },
        "method_summary": method_summary,
        "per_method_decision_judge_assessment_counts": axis_counts,
        "per_claim_method_outputs": per_claim,
        "judge_result_status_counts": dict(
            sorted(
                __import__("collections").Counter(str(row.get("status")) for row in judges).items()
            )
        ),
        "judge_results_planned": len(protocol["tasks"])
        * len(protocol["models"]["judge_models"])
        * 2,
        "development_outputs": [
            {
                "proposition_id": row["proposition_id"],
                "method_id": row["method_id"],
                "status": row.get("status"),
                "action": (row.get("decision") or {}).get("action"),
                "acquisition_status": legacy._asset_status(row.get("acquisition") or {}).get(
                    "status"
                ),
            }
            for row in predictions
            if row.get("split") == "development"
        ],
        "material_review_plan": asset_plan,
        "material_review_results": asset_review_results,
        "material_proxy_formal_acceptance_count": 0,
        "calls": _call_summary(
            legacy._json_calls(run_dir), budget_limit=protocol["budget"]["max_transport_calls"]
        ),
        "rights_and_source_boundary": {
            "source_pdfs_hash_verified": True,
            "embedded_source_figure_rights_independently_verified": False,
            "strict_acquisition_license_gate": protocol["assets"]["require_explicit_license"],
            "local_research_use": protocol["assets"].get("local_research_use"),
            "formal_acceptance": False,
            "arxiv_distribution_rights_not_treated_as_reuse_license": True,
            "candidate_pool_size": protocol["assets"]["candidate_count"],
        },
        "judge_action_sensitivity": _judge_action_sensitivity(run_dir, protocol, judges),
        "claim_boundary": protocol["claim_boundary"],
        "reproduction_commands": [
            "python scripts/run_rq1_doc2present_v2.py verify --package-root <copied-package>",
            "python scripts/run_rq1_doc2present_v2.py analyze-only --package-root <copied-package> --output <new-analysis.json>",
        ],
    }
    if persist:
        _write(run_dir / "report.json", report)
        legacy._write_text(run_dir / "report.md", _render_report_markdown(report))
    return report


def _render_report_markdown(report: dict) -> str:
    lines = [
        f"# RQ1 Doc2Present v2 development run: {report['run_id']}",
        "",
        f"Status: `{report['status']}`. This is a development comparison, not a locked test or formal experiment.",
        "",
        "## Method output and Judge proxy coverage",
        "",
        f"- Method outputs: {report['method_summary']['method_output_coverage']['numerator']}/{report['method_summary']['method_output_coverage']['denominator']}.",
        f"- Judge order slots: {report['method_summary']['judge_order_slot_coverage']['numerator']}/{report['method_summary']['judge_order_slot_coverage']['denominator']}.",
        f"- Valid forward/reverse pairs: {report['method_summary']['valid_forward_reverse_pairs']}.",
        f"- Acceptable-set / preferred-set / axis-label changes across order: {report['method_summary']['acceptable_set_changed_pairs']} / {report['method_summary']['preferred_set_changed_pairs']} / {report['method_summary']['assessment_changed_pairs']}.",
        f"- Preferred action-profile changed in forward/reverse pairs: {report['judge_action_sensitivity']['order_pairs']['preferred_action_profile_changed']}/{report['judge_action_sensitivity']['order_pairs']['valid_pairs']}; between Judge aliases at the same order: {report['judge_action_sensitivity']['alias_pairs']['preferred_action_profile_changed']}/{report['judge_action_sensitivity']['alias_pairs']['valid_pairs']}.",
        "- Judge outputs are proxies and are not a gold standard.",
        "",
        "## Per-proposition actions and acquisition outcomes",
        "",
        "| Proposition | Document | " + " | ".join(METHODS) + " |",
        "|---|---|" + "|".join(["---"] * len(METHODS)) + "|",
    ]
    for item in report["per_claim_method_outputs"]:
        values = [
            f"{item['methods'][method]['action']} / {item['methods'][method]['acquisition_status']}"
            for method in METHODS
        ]
        lines.append(
            f"| {item['proposition_id']} | {item['document_id']} | " + " | ".join(values) + " |"
        )
    calls = report["calls"]
    lines.extend(
        [
            "",
            "## Materials, rights and cost",
            "",
            f"- Candidate pool: all claims share the same frozen {report['sample']['candidate_pool_size']}-asset document-derived pool.",
            f"- Material proxy reviews: {len(report['material_review_results'])}; formal ACCEPT: 0.",
            "- Acquisition follows the frozen use policy; local research authorization is not an open-license or semantic ACCEPT claim.",
            f"- Real transport attempts: {calls['actual_transport_attempts']}/{calls['budget_limit']}; tokens: {calls['total_tokens']}; provider cost: {calls['provider_cost_usd']}.",
            f"- Request elapsed time sum: {calls['request_elapsed_seconds_sum']} sec; this is not wall-clock duration.",
            "- Image generation/TTS/recording/health checks: 0/0/0/0.",
            "",
            "## Interpretation boundary",
            "",
            report["claim_boundary"],
            "",
        ]
    )
    return "\n".join(lines)


def _build_output_manifest(run_dir: Path, protocol: dict) -> dict:
    files = {}
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file() or path.name in {"output_manifest.json", "run.lock"}:
            continue
        rel = path.relative_to(run_dir).as_posix()
        files[rel] = {"sha256": _sha(path), "size_bytes": path.stat().st_size}
    return {
        "schema_version": "rq1-v2-output-manifest-v1",
        "dataset_id": protocol["dataset_id"],
        "run_id": protocol["run_id"],
        "protocol_sha256": _sha(run_dir / "protocol.json"),
        "file_count": len(files),
        "files": files,
    }


def _verify_output_manifest(run_dir: Path, protocol: dict) -> dict:
    manifest_path = run_dir / "output_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"run output manifest is missing: {manifest_path}")
    saved = _read(manifest_path)
    current = _build_output_manifest(run_dir, protocol)
    saved_for_comparison = dict(saved)
    ignored_stale_transients = []
    saved_files = dict(saved.get("files", {}))
    if "run.lock" in saved_files and not (run_dir / "run.lock").exists():
        saved_files.pop("run.lock")
        saved_for_comparison["files"] = saved_files
        saved_for_comparison["file_count"] = len(saved_files)
        ignored_stale_transients.append("run.lock was included while finalizing under the run lock")
    if saved_for_comparison != current:
        expected, actual = set(saved_for_comparison.get("files", {})), set(current.get("files", {}))
        raise ValueError(
            f"run output manifest mismatch; changed files={sorted(k for k in expected & actual if saved['files'][k] != current['files'][k])}, "
            f"missing={sorted(expected - actual)}, new={sorted(actual - expected)}"
        )
    return {
        "status": "PASS",
        "file_count": saved["file_count"],
        "protocol_sha256": saved["protocol_sha256"],
        "ignored_stale_transients": ignored_stale_transients,
    }


def _recover_saved_judges(package_root: Path) -> dict:
    """Normalize already-returned valid JSON Judge responses; never send requests."""
    package_root = package_root.resolve()
    run_dir = package_root / RUN_REL
    protocol = _read(_protocol_path(run_dir))
    if not (run_dir / "output_manifest.json").is_file():
        raise ValueError("offline Judge recovery requires a completed run manifest")
    if verify(package_root)["status"] != "PASS":
        raise ValueError("offline Judge recovery requires an intact pre-recovery run")

    recovery_dir = run_dir / "recovery"
    if recovery_dir.exists():
        saved = recovery_dir / "judge_parser_recovery.json"
        if saved.is_file():
            return _read(saved)
        raise FileExistsError(
            f"incomplete recovery directory exists; inspect before continuing: {recovery_dir}"
        )

    ledger = legacy._json_calls(run_dir)
    if len(ledger) > int(protocol["budget"]["max_transport_calls"]):
        raise ValueError("cannot recover a run whose saved call ledger exceeds its frozen budget")
    calls_by_id = {entry.get("call_id"): entry for entry in ledger}
    originals = []
    recovered = []
    schema_invalid = []
    processed = []
    for path in sorted((run_dir / "judges").glob("*.json")):
        row = _read(path)
        error = row.get("parse_error") or {}
        if not (
            row.get("status") == "INVALID_RESPONSE"
            and error.get("type") == "AttributeError"
            and "_parse_json" in str(error.get("message") or "")
        ):
            continue
        call_entry = calls_by_id.get(row.get("call_id"))
        if (
            not call_entry
            or call_entry.get("stage") != "canonical_decision_layer_judge"
            or call_entry.get("status") != "OK"
            or not isinstance(call_entry.get("raw_response"), str)
        ):
            continue
        proposal_path = package_root / str(row.get("proposal_record_path") or "")
        if not proposal_path.is_file():
            raise FileNotFoundError(f"canonical proposal record is missing for {path.name}")
        proposal_record = _read(proposal_path)
        eligible_ids = [item["proposal_id"] for item in proposal_record.get("groups", [])]
        raw = call_entry["raw_response"]
        originals.append({"path": path.relative_to(run_dir).as_posix(), "row": row})
        raw_digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        try:
            parsed = _parse_json_response(raw)
            judgment = normalize_canonical_set_judgment(
                parsed,
                eligible_proposal_ids=eligible_ids,
                proposition_id=row["proposition_id"],
                judge_alias=row["judge_alias"],
                display_order=row["display_order"],
            )
        except Exception as exc:
            validation_error = {"type": type(exc).__name__, "message": str(exc)[:800]}
            row["initial_processing_error"] = error
            row["status"] = "INVALID_RESPONSE"
            row["judgment"] = None
            row["parse_error"] = validation_error
            row["processing_recovery"] = {
                "method": "STRICT_LOCAL_JSON_PARSE_AND_FROZEN_SCHEMA_VALIDATION",
                "call_id": call_entry["call_id"],
                "raw_response_sha256": raw_digest,
                "model_request_repeated": False,
                "schema_valid": False,
            }
            _write(path, row)
            schema_invalid.append(
                {
                    "path": path.relative_to(run_dir).as_posix(),
                    "call_id": call_entry["call_id"],
                    "raw_response_sha256": raw_digest,
                    "status": "SAVED_RESPONSE_FAILED_FROZEN_SCHEMA_VALIDATION",
                    "error": validation_error,
                }
            )
            processed.append(schema_invalid[-1])
            continue
        row["initial_processing_error"] = error
        row["status"] = "OK"
        row["judgment"] = judgment
        row["parse_error"] = None
        row["processing_recovery"] = {
            "method": "STRICT_LOCAL_JSON_PARSE_OF_SAVED_CALL_LEDGER_RESPONSE",
            "call_id": call_entry["call_id"],
            "raw_response_sha256": raw_digest,
            "model_request_repeated": False,
            "schema_valid": True,
        }
        _write(path, row)
        recovered.append(
            {
                "path": path.relative_to(run_dir).as_posix(),
                "call_id": call_entry["call_id"],
                "raw_response_sha256": raw_digest,
                "status": "RECOVERED_FROM_SAVED_JSON_RESPONSE_NO_MODEL_CALL",
            }
        )
        processed.append(recovered[-1])

    if not processed:
        raise ValueError("no parser-failure Judge outputs were eligible for offline recovery")
    recovery_dir.mkdir(parents=True)
    shutil.copy2(
        run_dir / "output_manifest.json",
        recovery_dir / "pre_recovery_output_manifest.json",
    )
    _write(recovery_dir / "pre_recovery_judge_rows.json", originals)
    implementation = recovery_dir / "recover_saved_judges_implementation.py"
    shutil.copy2(Path(__file__).resolve(), implementation)
    recovery_record = {
        "status": "RECOVERED_FROM_SAVED_RAW_RESPONSES_NO_MODEL_CALLS",
        "run_id": protocol["run_id"],
        "protocol_sha256": _sha(_protocol_path(run_dir)),
        "reason": "The original runner called a nonexistent legacy JSON parser after successful transport; all recovered responses were already stored in calls.json.",
        "method": "Strict json.loads plus the frozen canonical set validator; no response repair, inference, or resend.",
        "implementation_path": implementation.relative_to(run_dir).as_posix(),
        "implementation_sha256": _sha(implementation),
        "pre_recovery_output_manifest_sha256": _sha(
            recovery_dir / "pre_recovery_output_manifest.json"
        ),
        "pre_recovery_judge_row_count": len(originals),
        "recovered_judge_row_count": len(recovered),
        "schema_invalid_judge_row_count": len(schema_invalid),
        "recovered_judges": recovered,
        "schema_invalid_judges": schema_invalid,
        "processed_judges": processed,
        "call_count_before": len(ledger),
        "call_count_after": len(legacy._json_calls(run_dir)),
        "new_model_calls": 0,
        "model_request_repeats": 0,
    }
    if recovery_record["call_count_after"] != recovery_record["call_count_before"]:
        raise AssertionError("offline parser recovery changed the transport ledger")
    _write(recovery_dir / "judge_parser_recovery.json", recovery_record)
    _append_execution_record(run_dir, mode="recover_saved_judges_offline", started=time.monotonic())
    _refresh_report(package_root, run_dir, protocol)
    _write(run_dir / "output_manifest.json", _build_output_manifest(run_dir, protocol))
    return {**recovery_record, "verification": verify(package_root)}


def _recover_saved_material_reviews(package_root: Path) -> dict:
    """Strictly parse already-saved material proxy responses without resending."""
    package_root = package_root.resolve()
    run_dir = package_root / RUN_REL
    protocol = _read(_protocol_path(run_dir))
    recovery_dir = run_dir / "recovery"
    recovery_dir.mkdir(exist_ok=True)
    recovery_path = recovery_dir / "material_review_parser_recovery.json"
    if recovery_path.exists():
        return {**_read(recovery_path), "verification": verify(package_root)}

    ledger = legacy._json_calls(run_dir)
    if len(ledger) > int(protocol["budget"]["max_transport_calls"]):
        raise ValueError("cannot recover a run whose saved call ledger exceeds its frozen budget")
    calls_by_id = {entry.get("call_id"): entry for entry in ledger}
    rows_before = []
    recovered = []
    invalid = []
    processed = []
    for path in sorted((run_dir / "asset_reviews").glob("*.json")):
        row = _read(path)
        error = row.get("parse_error") or {}
        if not (
            row.get("proxy_status") == "INVALID_RESPONSE"
            and error.get("type") == "AttributeError"
            and "_parse_json" in str(error.get("message") or "")
        ):
            continue
        call_entry = calls_by_id.get(row.get("call_id"))
        images = (call_entry or {}).get("images") or []
        if (
            not call_entry
            or call_entry.get("stage") != "material_fit_proxy_review"
            or call_entry.get("status") != "OK"
            or not isinstance(call_entry.get("raw_response"), str)
            or len(images) != 1
            or images[0].get("sha256") != row.get("asset_sha256")
        ):
            continue

        raw = call_entry["raw_response"]
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        rows_before.append({"path": path.relative_to(run_dir).as_posix(), "row": row})
        try:
            judgment = _parse_json_response(raw)
            if judgment.get("fit") not in {"MATCH", "PARTIAL", "MISMATCH", "UNCERTAIN"}:
                raise ValueError("fit must be MATCH, PARTIAL, MISMATCH, or UNCERTAIN")
            if not str(judgment.get("claim_relation") or "").strip():
                raise ValueError("claim_relation is required")
            if not str(judgment.get("visible_evidence") or "").strip():
                raise ValueError("visible_evidence is required")
            if not isinstance(judgment.get("redundant_or_decorative"), bool):
                raise ValueError("redundant_or_decorative must be boolean")
            uncertainty = judgment.get("uncertainty")
            if uncertainty is not None and not isinstance(uncertainty, str):
                raise ValueError("uncertainty must be a string or null")
        except Exception as exc:
            row["initial_processing_error"] = error
            row["parse_error"] = {"type": type(exc).__name__, "message": str(exc)[:800]}
            row["processing_recovery"] = {
                "method": "STRICT_LOCAL_JSON_PARSE_AND_MATERIAL_PROXY_FIELD_VALIDATION",
                "call_id": call_entry["call_id"],
                "raw_response_sha256": digest,
                "model_request_repeated": False,
                "schema_valid": False,
            }
            _write(path, row)
            entry = {
                "path": path.relative_to(run_dir).as_posix(),
                "call_id": call_entry["call_id"],
                "raw_response_sha256": digest,
                "status": "SAVED_RESPONSE_FAILED_MATERIAL_PROXY_VALIDATION",
                "error": row["parse_error"],
            }
            invalid.append(entry)
            processed.append(entry)
            continue

        row["initial_processing_error"] = error
        row["proxy_status"] = "PROXY_REVIEWED"
        row["judgment"] = judgment
        row["parse_error"] = None
        row["processing_recovery"] = {
            "method": "STRICT_LOCAL_JSON_PARSE_OF_SAVED_CALL_LEDGER_RESPONSE",
            "call_id": call_entry["call_id"],
            "raw_response_sha256": digest,
            "model_request_repeated": False,
            "schema_valid": True,
            "formal_acceptance": False,
        }
        _write(path, row)
        entry = {
            "path": path.relative_to(run_dir).as_posix(),
            "call_id": call_entry["call_id"],
            "raw_response_sha256": digest,
            "status": "RECOVERED_FROM_SAVED_JSON_RESPONSE_NO_MODEL_CALL",
        }
        recovered.append(entry)
        processed.append(entry)

    if not processed:
        raise ValueError(
            "no parser-failure material review outputs were eligible for offline recovery"
        )

    pre_manifest = run_dir / "output_manifest.json"
    if pre_manifest.is_file():
        shutil.copy2(pre_manifest, recovery_dir / "pre_material_review_recovery_manifest.json")
    _write(recovery_dir / "pre_material_review_rows.json", rows_before)
    implementation = recovery_dir / "recover_saved_material_reviews_implementation.py"
    shutil.copy2(Path(__file__).resolve(), implementation)
    recovery_record = {
        "status": "RECOVERED_FROM_SAVED_RAW_RESPONSES_NO_MODEL_CALLS",
        "run_id": protocol["run_id"],
        "protocol_sha256": _sha(_protocol_path(run_dir)),
        "reason": "The runner called a nonexistent legacy JSON parser after successful material-proxy transport; raw responses were already stored in calls.json.",
        "method": "Strict JSON object parsing plus required material-proxy field validation. No response repair, inference, license clearance, or formal ACCEPT promotion.",
        "implementation_path": implementation.relative_to(run_dir).as_posix(),
        "implementation_sha256": _sha(implementation),
        "pre_recovery_rows": len(rows_before),
        "recovered_rows": len(recovered),
        "invalid_saved_responses": len(invalid),
        "recovered_material_reviews": recovered,
        "invalid_material_reviews": invalid,
        "processed_material_reviews": processed,
        "call_count_before": len(ledger),
        "call_count_after": len(legacy._json_calls(run_dir)),
        "new_model_calls": 0,
        "model_request_repeats": 0,
        "formal_acceptance_count": 0,
    }
    if recovery_record["call_count_after"] != recovery_record["call_count_before"]:
        raise AssertionError("offline material-review recovery changed the transport ledger")
    _write(recovery_path, recovery_record)
    _append_execution_record(
        run_dir, mode="recover_saved_material_reviews_offline", started=time.monotonic()
    )
    _refresh_report(package_root, run_dir, protocol)
    _write(run_dir / "output_manifest.json", _build_output_manifest(run_dir, protocol))
    return {**recovery_record, "verification": verify(package_root)}


def verify(package_root: Path) -> dict:
    package_root = package_root.resolve()
    run_dir = package_root / RUN_REL
    protocol = _read(_protocol_path(run_dir))
    input_results = []
    for relative, metadata in sorted(protocol["source_files"].items()):
        path = _package_path(package_root, relative)
        if not path.is_file():
            raise FileNotFoundError(f"frozen v2 input is missing: {relative}")
        actual = _sha(path)
        if actual != metadata["sha256"]:
            raise ValueError(f"frozen v2 input hash mismatch: {relative}")
        input_results.append({"path": relative, "sha256": actual, "status": "PASS"})

    ledger = legacy._json_calls(run_dir)
    call_ids = [entry.get("call_id") for entry in ledger]
    task_keys = [entry.get("task_key") for entry in ledger]
    if call_ids != list(range(1, len(call_ids) + 1)):
        raise ValueError("call ledger IDs must be continuous and append-only")
    if len(task_keys) != len(set(task_keys)):
        raise ValueError("the call ledger contains repeated task keys")
    if len(ledger) > int(protocol["budget"]["max_transport_calls"]):
        raise ValueError("the frozen run-wide transport budget was exceeded")
    for entry in ledger:
        prompt_path = _package_path(package_root, f"run-01/{entry['prompt_path']}")
        if not prompt_path.is_file() or _sha(prompt_path) != entry.get("prompt_sha256"):
            raise ValueError(f"prompt hash mismatch for call {entry.get('call_id')}")

    source_quotes = []
    for task in protocol["tasks"]:
        claim = _read(package_root / task["input_path"])
        evidence = _read(package_root / task["source_evidence_path"])
        page_path = package_root / f"dataset/extracted/{task['document_id']}-page-text.json"
        pages = _read(page_path)
        source_pages = claim.get("source_pages") or [claim["page_number"]]
        page_text = " ".join(pages[str(page_number)] for page_number in source_pages)
        if _norm_source(claim["exact_claim_quote"]) not in _norm_source(page_text):
            raise ValueError(
                f"source quote no longer matches normalized page text: {task['proposition_id']}"
            )
        ref_ids = {str(item["id"]) for item in evidence.get("source_units", [])}
        if any(reference not in ref_ids for reference in claim.get("source_refs", [])):
            raise ValueError(f"source references missing for {task['proposition_id']}")
        _source_hashes(package_root, task)
        source_quotes.append(task["proposition_id"])
    links = _read(package_root / "dataset/source_context_links.json")
    if links.get("status") != "ENGINEERING_CONTEXT_LINKS_NOT_G0_LABELS_NOT_SEMANTIC_SUPPORT_GOLD":
        raise ValueError("engineering source context links were mislabeled")
    link_prop_ids = {item["proposition_id"] for item in links["links"]}
    if link_prop_ids != {task["proposition_id"] for task in protocol["tasks"]}:
        raise ValueError("engineering context links do not cover the frozen proposition sample")
    candidate_catalog = _read(package_root / "dataset/retrieval_catalog.json")
    candidate_ids = [item["id"] for item in candidate_catalog.get("assets", [])]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("frozen candidate IDs are not unique")
    for candidate in candidate_catalog.get("assets", []):
        path = _package_path(package_root, candidate["path"])
        if not path.is_file() or _sha(path) != candidate.get("sha256"):
            raise ValueError(f"candidate asset hash mismatch: {candidate.get('id')}")

    for prompt_file in (
        (run_dir / "prompts").glob("*.txt") if (run_dir / "prompts").exists() else []
    ):
        if "decision_judge" not in prompt_file.name:
            continue
        payload = json.loads(prompt_file.read_text(encoding="utf-8"))
        for proposal in payload.get("proposals_in_display_order", []):
            if any(
                key in proposal
                for key in (
                    "method_id",
                    "rationale",
                    "retrieval_query",
                    "acceptance_criteria",
                    "generation_prompt",
                    "acquisition_status",
                )
            ):
                raise ValueError(
                    f"decision Judge prompt contains excluded proposal fields: {prompt_file.name}"
                )

    recovery_path = run_dir / "recovery/judge_parser_recovery.json"
    if recovery_path.is_file():
        recovery = _read(recovery_path)
        implementation = _package_path(package_root, f"run-01/{recovery['implementation_path']}")
        if not implementation.is_file() or _sha(implementation) != recovery.get(
            "implementation_sha256"
        ):
            raise ValueError("offline recovery implementation hash mismatch")
        if recovery.get("new_model_calls") != 0 or recovery.get("model_request_repeats") != 0:
            raise ValueError("offline recovery record reports a model call or repeated request")
        for processed_row in recovery.get("processed_judges", []):
            judge_path = _package_path(package_root, f"run-01/{processed_row['path']}")
            judge = _read(judge_path)
            call = next(
                (item for item in ledger if item.get("call_id") == processed_row["call_id"]),
                None,
            )
            actual_response_hash = (
                hashlib.sha256(call["raw_response"].encode("utf-8")).hexdigest()
                if call and isinstance(call.get("raw_response"), str)
                else None
            )
            if (
                judge.get("status")
                != (
                    "OK"
                    if processed_row.get("status")
                    == "RECOVERED_FROM_SAVED_JSON_RESPONSE_NO_MODEL_CALL"
                    else "INVALID_RESPONSE"
                )
                or not call
                or actual_response_hash != processed_row.get("raw_response_sha256")
                or judge.get("processing_recovery", {}).get("raw_response_sha256")
                != processed_row.get("raw_response_sha256")
            ):
                raise ValueError(
                    f"processed Judge evidence does not match the saved call: {processed_row['path']}"
                )

    manifest = (
        _verify_output_manifest(run_dir, protocol)
        if (run_dir / "output_manifest.json").is_file()
        else {
            "status": "OUTPUTS_PENDING",
            "file_count": None,
        }
    )
    result = {
        "status": "PASS" if manifest["status"] in {"PASS", "OUTPUTS_PENDING"} else "FAIL",
        "dataset_id": protocol["dataset_id"],
        "run_id": protocol["run_id"],
        "protocol_sha256": _sha(_protocol_path(run_dir)),
        "input_file_count": len(input_results),
        "input_files": input_results,
        "source_quote_matches": len(source_quotes),
        "candidate_count": len(candidate_ids),
        "candidate_hashes": "PASS",
        "call_count": len(ledger),
        "call_budget": protocol["budget"]["max_transport_calls"],
        "output_manifest": manifest,
        "api_calls_during_verify": 0,
    }
    _write(package_root / "verify.json", result)
    return result


def _record_interrupted_result(
    run_dir: Path, split: str, method: str, task: dict, reason: str
) -> None:
    path = legacy._prediction_path(run_dir, split, method, task["proposition_id"])
    if path.exists():
        return
    _write(
        path,
        {
            "status": "INTERRUPTED_REMOTE_RESULT_UNKNOWN",
            "proposition_id": task["proposition_id"],
            "document_id": task["document_id"],
            "split": split,
            "method_id": method,
            "decision_model_calls": 1,
            "retry": "FORBIDDEN_FOR_THIS_RESERVED_TASK",
            "error_message": reason,
        },
    )


def _recover_started_calls(run_dir: Path, ledger: list[dict]) -> None:
    changed = False
    for entry in ledger:
        if entry.get("status") == "STARTED":
            entry["status"] = "INTERRUPTED_REMOTE_RESULT_UNKNOWN"
            entry["error_message"] = (
                "Transport result was not durably recorded; this reserved task will not be resent."
            )
            changed = True
    if changed:
        _write(run_dir / "calls.json", ledger)


def _task_key_exists(ledger: list[dict], task_key: str) -> bool:
    return any(entry.get("task_key") == task_key for entry in ledger)


def _append_execution_record(run_dir: Path, *, mode: str, started: float) -> None:
    history_path = run_dir / "execution_history.json"
    history = _read(history_path).get("invocations", []) if history_path.is_file() else []
    history.append(
        {
            "mode": mode,
            "started_at_utc": datetime.now(UTC).isoformat(),
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    )
    _write(history_path, {"invocations": history})


def _stop_after_failed_transport(protocol: dict, ledger: list[dict]) -> None:
    if protocol["budget"].get("stop_on_transport_failure") and any(
        entry.get("status") != "OK" for entry in ledger
    ):
        raise RuntimeError("STOPPED_AFTER_TRANSPORT_FAILURE_NO_RETRY")


def _run_all(package_root: Path, *, resume: bool) -> dict:
    package_root = package_root.resolve()
    run_dir = package_root / RUN_REL
    protocol = _read(_protocol_path(run_dir))
    verify(package_root)
    if (run_dir / "output_manifest.json").is_file():
        if resume:
            return _refresh_report(package_root, run_dir, protocol, persist=False)
        raise FileExistsError(
            "run already has a final output manifest; use resume only to inspect it"
        )
    if protocol["budget"]["max_transport_calls"] != _config()["max_transport_calls"]:
        raise ValueError("run-wide call budget differs from frozen config")
    if not legacy.LLM_API_KEY or not legacy.LLM_BASE_URL:
        raise RuntimeError(
            "LLM credentials or endpoint are unavailable; no model transfer was attempted"
        )
    lock = run_dir / "run.lock"
    try:
        with lock.open("x", encoding="utf-8") as stream:
            stream.write(str(os.getpid()))
    except FileExistsError as exc:
        raise RuntimeError(f"run is locked by another process or a stale lock: {lock}") from exc

    started = time.monotonic()
    try:
        ledger = legacy._json_calls(run_dir)
        _recover_started_calls(run_dir, ledger)
        ledger = legacy._json_calls(run_dir)
        keyword_terms = frozenset(_config()["english_keyword_heuristic_lexicon"])

        # Deterministic baselines and their fail-closed acquisition paths.
        for task in protocol["tasks"]:
            for method in BASELINES:
                if legacy._method_row(run_dir, "comparison", method, task["proposition_id"]):
                    continue
                legacy._make_baseline(
                    package_root=package_root,
                    run_dir=run_dir,
                    task=task,
                    method_id=method,
                    require_explicit_license=protocol["assets"]["require_explicit_license"],
                    keyword_terms=keyword_terms,
                )
        _refresh_report(package_root, run_dir, protocol)
        _stop_after_failed_transport(protocol, ledger)
        # Re-run Direct/Proposed on the reused Forams protocol-development split.
        for task in protocol["planned_development_tasks"]:
            for method in task["methods"]:
                if legacy._method_row(run_dir, "development", method, task["proposition_id"]):
                    continue
                task_key = f"decision:development:{method}:{task['proposition_id']}"
                if _task_key_exists(ledger, task_key):
                    _record_interrupted_result(
                        run_dir,
                        "development",
                        method,
                        task,
                        "Reserved request has no recoverable output; not resent.",
                    )
                    continue
                legacy._run_method_call(
                    package_root=package_root,
                    run_dir=run_dir,
                    protocol=protocol,
                    task=task,
                    condition=method,
                    split="development",
                    ledger=ledger,
                    max_tokens=protocol["models"]["method_max_tokens"],
                )
                _refresh_report(package_root, run_dir, protocol)
                _stop_after_failed_transport(protocol, ledger)
        # Direct, Proposed, and the four frozen mechanism ablations use the same inputs/pool.
        for task in protocol["tasks"]:
            for method in MODEL_CONDITIONS:
                if legacy._method_row(run_dir, "comparison", method, task["proposition_id"]):
                    continue
                task_key = f"decision:comparison:{method}:{task['proposition_id']}"
                if _task_key_exists(ledger, task_key):
                    _record_interrupted_result(
                        run_dir,
                        "comparison",
                        method,
                        task,
                        "Reserved request has no recoverable output; not resent.",
                    )
                    continue
                legacy._run_method_call(
                    package_root=package_root,
                    run_dir=run_dir,
                    protocol=protocol,
                    task=task,
                    condition=method,
                    split="comparison",
                    ledger=ledger,
                    max_tokens=protocol["models"]["method_max_tokens"],
                )
                _refresh_report(package_root, run_dir, protocol)
                _stop_after_failed_transport(protocol, ledger)
        _refresh_report(package_root, run_dir, protocol)
        _stop_after_failed_transport(protocol, ledger)
        # Two aliases × two display orders. The proposal set is canonical and tied proposals are grouped first.
        for task in protocol["tasks"]:
            for alias in protocol["models"]["judge_models"]:
                for order in ("forward", "reverse"):
                    output_path = _judge_output_path(run_dir, task, alias, order)
                    task_key = f"decision_judge:{task['proposition_id']}:{alias}:{order}"
                    if output_path.exists():
                        continue
                    if _task_key_exists(ledger, task_key):
                        _write(
                            output_path,
                            {
                                "status": "INTERRUPTED_REMOTE_RESULT_UNKNOWN",
                                "proposition_id": task["proposition_id"],
                                "judge_alias": alias,
                                "display_order": order,
                                "planned": True,
                                "model_calls": 1,
                                "retry": "FORBIDDEN_FOR_THIS_RESERVED_TASK",
                            },
                        )
                        continue
                    _judge_one(
                        package_root=package_root,
                        run_dir=run_dir,
                        protocol=protocol,
                        task=task,
                        alias=alias,
                        order=order,
                        ledger=ledger,
                    )
                    _refresh_report(package_root, run_dir, protocol)
                    _stop_after_failed_transport(protocol, ledger)
        _refresh_report(package_root, run_dir, protocol)
        _stop_after_failed_transport(protocol, ledger)
        _review_materials(package_root, run_dir, protocol, ledger)
        _refresh_report(package_root, run_dir, protocol)
        _stop_after_failed_transport(protocol, ledger)
        _append_execution_record(run_dir, mode="resume" if resume else "execute", started=started)
        if len(ledger) > protocol["budget"]["max_transport_calls"]:
            raise AssertionError("frozen run-wide model-transfer budget exceeded")
        _refresh_report(package_root, run_dir, protocol)
        _stop_after_failed_transport(protocol, ledger)
        _write(run_dir / "output_manifest.json", _build_output_manifest(run_dir, protocol))
        _refresh_report(package_root, run_dir, protocol)
        _stop_after_failed_transport(protocol, ledger)
        # report.md/json are part of the manifest; refresh the manifest once more after final status changes.
        _write(run_dir / "output_manifest.json", _build_output_manifest(run_dir, protocol))
        return _refresh_report(package_root, run_dir, protocol, persist=False)
    finally:
        if lock.exists():
            lock.unlink()


def analyze_only(run_dir: Path, output_path: Path) -> dict:
    run_dir = run_dir.resolve()
    package_root = run_dir.parent
    protocol = _read(_protocol_path(run_dir))
    verified = verify(package_root)
    if verified["status"] != "PASS" or not (run_dir / "output_manifest.json").is_file():
        raise ValueError("analyze-only requires a completed, verified, immutable run")
    before = len(legacy._json_calls(run_dir))
    report = _refresh_report(package_root, run_dir, protocol, persist=False)
    after = len(legacy._json_calls(run_dir))
    if before != after:
        raise AssertionError("analyze-only changed the model-call ledger")
    output_path = output_path.resolve()
    if output_path.exists():
        raise FileExistsError(f"analysis output already exists; choose a new path: {output_path}")
    result = {
        "status": "ANALYZED_FROM_SAVED_RUN_NO_MODEL_CALLS",
        "run_id": protocol["run_id"],
        "protocol_sha256": _sha(_protocol_path(run_dir)),
        "model_calls_before": before,
        "model_calls_after": after,
        "new_model_calls": 0,
        "report": report,
        "analysis_implementation_sha256": _sha(Path(__file__).resolve()),
    }
    _write(output_path, result)
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in (
        "prepare",
        "verify",
        "execute",
        "resume",
        "recover-saved-judges",
        "recover-saved-material-reviews",
    ):
        sub = subparsers.add_parser(command)
        sub.add_argument("--package-root", type=Path, default=DEFAULT_PACKAGE_ROOT)
        if command == "prepare":
            sub.add_argument("--config-path", type=Path)
    analyze = subparsers.add_parser("analyze-only")
    analyze.add_argument("--package-root", type=Path, default=DEFAULT_PACKAGE_ROOT)
    analyze.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        if args.config_path:
            _activate_config(args.config_path)
        print(prepare(args.package_root))
        return 0
    _activate_package_config(args.package_root)
    if args.command == "verify":
        print(json.dumps(verify(args.package_root), ensure_ascii=False, indent=2))
        return 0
    if args.command == "execute":
        result = _run_all(args.package_root, resume=False)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "resume":
        result = _run_all(args.package_root, resume=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "recover-saved-judges":
        result = _recover_saved_judges(args.package_root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "recover-saved-material-reviews":
        result = _recover_saved_material_reviews(args.package_root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    run_dir = args.package_root / RUN_REL
    print(json.dumps(analyze_only(run_dir, args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
