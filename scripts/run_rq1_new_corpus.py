"""Prepare, execute, resume, analyze, and verify a bounded RQ1 development run.

All network calls are reserved in ``calls.json`` before transport. The runner
uses the existing proposition/source/decision/acquisition/Judge artifacts and
does not call image generation, TTS, recording, or service health checks.
"""

# The runner stores verbatim source claims and frozen natural-language prompts.
# Keep those literal bytes unchanged; structural lint checks still cover this file.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import importlib.metadata
import json
import os
import platform
import random
import re
import shutil
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src")]
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

from textbook2video.llm import client  # noqa: E402
from textbook2video.pipeline.config import LLM_API_KEY, LLM_BASE_URL  # noqa: E402
from textbook2video.research.rq1_controlled_evaluation import (  # noqa: E402
    summarize_blind_proposal_comparison,
)
from textbook2video.research.rq1_preference_judge import (  # noqa: E402
    judge_rq1_blind_proposals,
)
from textbook2video.research.visual_acquisition import (  # noqa: E402
    execute_visual_acquisition,
)
from textbook2video.research.visual_decision import (  # noqa: E402
    DECISION_VERSION,
    decide_visual_support,
)
from textbook2video.research.visual_decision_baselines import (  # noqa: E402
    predict_baseline,
)

PACKAGE_ID = "rq1-noaa-orsea-crossdoc-dev-v1"
CONFIG_REL = Path("configs/research/rq1_new_corpus_dev_v1.json")
DEFAULT_PACKAGE_ROOT = ROOT / ".local/rq1/20261104-rq1-new-corpus-v1"
RUN_ID = "rq1-20261104-run01"
RUN_REL = Path("run-01")

SOURCE_DOCS = {
    "noaa-56861-forams": {
        "split": "development",
        "title": "Forams as Storytellers",
        "authors": ["Kerry Zambrano", "Will Millard", "M. Kelsey Lane"],
        "record_url": "https://repository.library.noaa.gov/view/noaa/56861",
        "archive_pdf_url": "https://repository.library.noaa.gov/view/noaa/56861/noaa_56861_DS1.pdf",
        "archive_sha256": "ac1cacd5ce8cca5e5a5b21df6c6c40750a88bb0845dc2bc982d2a2093d89229e",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "license_record": "CC0 Public Domain on NOAA Institutional Repository record",
        "local_pdf": "sources/dev-forams.pdf",
        "pdf_updated": "2024-12-13 (OSU-hosted copy)",
        "archive_pdf_updated": "2023-01-06 (NOAA archived PDF text)",
        "pages_json": "extracted/forams/pages.json",
        "images_json": "extracted/forams/images.json",
        "image_dir": "extracted/forams/images",
        "archive_quotes": [
            "Foraminifera, or forams, are microscopic, shelled protists found throughout the global oceans.",
            "Distribution of foraminifera species is dependent on water temperature and other measurable, environmental factors.",
            "By collecting and analyzing foram species annually off the Oregon coast, researchers have correlated changes in water temperature with species frequency and distribution.",
            "Additionally, the study of foraminifera can be applied to deep sea sediment cores to help us understand ancient climate.",
        ],
    },
    "noaa-60590-salmon": {
        "split": "comparison",
        "title": "Population Fluctuations in Salmon",
        "authors": ["Kristina Webster", "Ellen Pennell", "Selina Heppell"],
        "record_url": "https://repository.library.noaa.gov/view/noaa/60590",
        "archive_pdf_url": "https://repository.library.noaa.gov/view/noaa/60590/noaa_60590_DS1.pdf",
        "archive_sha256": "1abaf07b65672f2324117c0277f1d10e354cac6ef0a91ba6a6c3475ae34e56b1",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "license_record": "CC0 Public Domain on NOAA Institutional Repository record",
        "local_pdf": "sources/eval-salmon-original.pdf",
        "pdf_updated": "2022-12-22 (OSU-hosted copy)",
        "archive_pdf_updated": "2022-12-22 (NOAA archived PDF text)",
        "pages_json": "extracted/salmon/pages.json",
        "images_json": "extracted/salmon/images.json",
        "image_dir": "extracted/salmon/images",
        "archive_quotes": [
            "Scientists use line graphs to visualize changes in populations over time.",
            "Different species of salmon have different life cycles.",
            "Scientists use models to predict how impacts at different life stages impact salmon populations.",
            "Understanding the life cycles and population histories of salmon can inform management decisions.",
            "Different species of salmon have different life cycles that impact how they respond to disturbances in their ecosystems.",
            "When we see a decline in the population, we may be tempted to make a management decision to help the species rebound.",
        ],
    },
    "noaa-56860-coral": {
        "split": "comparison",
        "title": "Coral Bleaching",
        "authors": ["Andy Beddingfield", "Nick Gezon", "Nate Kirk"],
        "record_url": "https://repository.library.noaa.gov/view/noaa/56860",
        "archive_pdf_url": "https://repository.library.noaa.gov/view/noaa/56860/noaa_56860_DS1.pdf",
        "archive_sha256": "f6a44314efbc3a8480966a57dad2599d1c24d6219c3efbfcc17d976c4711531e",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "license_record": "CC0 Public Domain on NOAA Institutional Repository record",
        "local_pdf": "sources/eval-coral.pdf",
        "pdf_updated": "2023-01-05 (OSU-hosted copy)",
        "archive_pdf_updated": "2023-03-03 (NOAA archived PDF text)",
        "pages_json": "extracted/coral/pages.json",
        "images_json": "extracted/coral/images.json",
        "image_dir": "extracted/coral/images",
        "archive_quotes": [
            "Corals experiencing environmental stress can exhibit bleaching which adds more stress and can lead to increased mortality.",
            "To study coral bleaching, researchers use model organisms that have similar processes but are easier to work with.",
            "Photosynthesis and cellular respiration provide most of the energy for life processes.",
            "Symbiotic relationships between organisms can affect the physiology of organisms.",
            "The algae make food from the sun in a process called photosynthesis and ship the food to the coral so that it can eat and generate energy in a process called cellular respiration.",
            "Losing the algae is called coral bleaching as the loss of the algae reveals the beautiful white skeleton of the coral beneath.",
        ],
    },
}

CLAIM_LOCATORS = {
    "noaa-56861-forams": [
        (2, "Introduction, consecutive sentence 1", "forams-intro-s1"),
        (2, "Introduction, consecutive sentence 2", "forams-intro-s2"),
        (2, "Introduction, consecutive sentence 3", "forams-intro-s3"),
        (2, "Introduction, consecutive sentence 4", "forams-intro-s4"),
    ],
    "noaa-60590-salmon": [
        (1, "Learning Goals, bullet 1", "salmon-goal-b1"),
        (1, "Learning Goals, bullet 2", "salmon-goal-b2"),
        (1, "Learning Goals, bullet 3", "salmon-goal-b3"),
        (1, "Learning Goals, bullet 4", "salmon-goal-b4"),
        (2, "Introduction, sentence 1", "salmon-intro-s1"),
        (2, "Introduction, sentence 2", "salmon-intro-s2"),
    ],
    "noaa-56860-coral": [
        (1, "Learning Goals, bullet 2", "coral-goal-b2"),
        (1, "Learning Goals, bullet 3", "coral-goal-b3"),
        (1, "Learning Goals, bullet 4", "coral-goal-b4"),
        (1, "Learning Goals, bullet 5", "coral-goal-b5"),
        (2, "Introduction, paragraph 2, sentence 2", "coral-intro-p2-s2"),
        (2, "Introduction, paragraph 3, sentence 2", "coral-intro-p3-s2"),
    ],
}

ASSET_SPECS = [
    {
        "id": "asset-noaa-forams-ssta-2012",
        "doc_id": "noaa-56861-forams",
        "page": 2,
        "xref": 62,
        "filename": "page-02-xref-62.jpeg",
        "caption": "Fall 2012 SSTa map. Image credit: NOAA/ESRL.",
        "title": "Fall 2012 sea surface temperature anomaly map",
        "tags": ["SSTa", "map", "sea surface temperature", "temperature anomaly", "ocean"],
        "source_ids": ["noaa-56861-forams"],
    },
    {
        "id": "asset-noaa-salmon-chinook",
        "doc_id": "noaa-60590-salmon",
        "page": 1,
        "xref": 41,
        "filename": "page-01-xref-41.jpeg",
        "caption": "Chinook salmon. Image: NOAA Fisheries.",
        "title": "Chinook salmon photograph",
        "tags": ["salmon", "Chinook", "fish", "life cycle", "species"],
        "source_ids": ["noaa-60590-salmon"],
    },
    {
        "id": "asset-noaa-coral-healthy",
        "doc_id": "noaa-56860-coral",
        "page": 3,
        "xref": 113,
        "filename": "page-03-xref-113.jpeg",
        "caption": "Healthy coral reef. Photo: NOAA.",
        "title": "Healthy coral reef photograph",
        "tags": ["coral", "reef", "healthy", "marine ecosystem"],
        "source_ids": [],
    },
    {
        "id": "asset-noaa-coral-bleached",
        "doc_id": "noaa-56860-coral",
        "page": 3,
        "xref": 114,
        "filename": "page-03-xref-114.jpeg",
        "caption": "Bleached coral in Guam during a period of elevated sea surface temperatures in August 2016. Photo: NOAA.",
        "title": "Bleached coral in Guam, August 2016",
        "tags": ["coral", "bleaching", "heat stress", "elevated temperature", "Guam"],
        "source_ids": [],
    },
]

EXCLUDED_SOURCE_VISUALS = [
    {
        "id": "excluded-forams-figure-p02-xref63",
        "doc_id": "noaa-56861-forams",
        "page": 2,
        "caption": "Foraminifera. Image credit: Theresa Fritz-Endres.",
        "reason": "Third-party individual photo credit; not included in the shared candidate pool or sent as pixels because reuse rights were not separately verified.",
    },
    {
        "id": "excluded-salmon-p02-salmonsociety",
        "doc_id": "noaa-60590-salmon",
        "page": 2,
        "caption": "Screenshot from salmonsociety.com.",
        "reason": "Third-party website screenshot; not included in the shared candidate pool or sent as pixels.",
    },
    {
        "id": "excluded-salmon-p02-odfw-photo",
        "doc_id": "noaa-60590-salmon",
        "page": 2,
        "caption": "Chum salmon. Photo: ODFW.",
        "reason": "Rights not separately verified for this credited image; not included in the shared pool or sent as pixels.",
    },
    {
        "id": "excluded-coral-p01-jack-koch",
        "doc_id": "noaa-56860-coral",
        "page": 1,
        "caption": "Sea anemone with pedal lacerates. Photo: Jack Koch.",
        "reason": "Third-party individual photo credit; not included in the shared candidate pool or sent as pixels.",
    },
    {
        "id": "excluded-coral-p02-corals",
        "doc_id": "noaa-56860-coral",
        "page": 2,
        "caption": "Healthy (left) and bleached (right) coral.",
        "reason": "The individual image credit is not explicit in the page caption; not included in the shared candidate pool or sent as pixels.",
    },
    {
        "id": "excluded-coral-p02-aiptasia-n-kirk",
        "doc_id": "noaa-56860-coral",
        "page": 2,
        "caption": "Anemone grown with and without symbiotic algae. Photos: N. Kirk.",
        "reason": "Third-party individual photo credit; not included in the shared candidate pool or sent as pixels.",
    },
]

ENGLISH_KEYWORDS = frozenset(
    json.loads((ROOT / CONFIG_REL).read_text(encoding="utf-8"))["english_keyword_heuristic_lexicon"]
)
BASELINE_IDS = ("never_retrieve", "always_retrieve", "keyword_heuristic")
METHOD_CONDITIONS = (
    "direct_llm",
    "proposed",
    "no_source",
    "without_source_sufficiency",
    "without_retrieval_suitability",
    "without_uncertainty_handling",
)
SOURCE_FILES = (
    "scripts/run_rq1_new_corpus.py",
    "src/textbook2video/research/visual_decision.py",
    "src/textbook2video/research/visual_decision_baselines.py",
    "src/textbook2video/research/visual_acquisition.py",
    "src/textbook2video/research/rq1_preference_judge.py",
    "src/textbook2video/research/rq1_controlled_evaluation.py",
    str(CONFIG_REL).replace("\\", "/"),
)


def _sha(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temp, path)


def _collapse(value: str) -> str:
    return " ".join(value.split())


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def _package_path(package_root: Path, relative: str | Path) -> Path:
    candidate = (package_root / relative).resolve()
    if not candidate.is_relative_to(package_root.resolve()):
        raise ValueError(f"package-relative path escapes root: {relative}")
    return candidate


@contextlib.contextmanager
def _working_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _source_metadata(package_root: Path) -> tuple[list[dict], dict[str, dict]]:
    documents: list[dict] = []
    page_texts: dict[str, dict] = {}
    import fitz

    for doc_id, spec in SOURCE_DOCS.items():
        pdf_path = _package_path(package_root, spec["local_pdf"])
        pages_path = _package_path(package_root, spec["pages_json"])
        image_index_path = _package_path(package_root, spec["images_json"])
        if not pdf_path.is_file() or not pages_path.is_file() or not image_index_path.is_file():
            raise FileNotFoundError(f"required source or extracted index missing for {doc_id}")
        extracted = json.loads(pages_path.read_text(encoding="utf-8"))
        document = fitz.open(pdf_path)
        actual_pages = [page.get_text("text") for page in document]
        if len(actual_pages) != len(extracted):
            raise ValueError(f"page count drift between PDF and extracted index: {doc_id}")
        for index, actual in enumerate(actual_pages):
            if _collapse(actual) != _collapse(str(extracted[index].get("text") or "")):
                raise ValueError(f"PDF text extraction drift at {doc_id} page {index + 1}")
        page_texts[doc_id] = {
            str(index + 1): actual_pages[index]
            for index in range(len(actual_pages))
        }
        documents.append(
            {
                "document_id": doc_id,
                "split": spec["split"],
                "title": spec["title"],
                "authors": spec["authors"],
                "record_url": spec["record_url"],
                "archive_pdf_url": spec["archive_pdf_url"],
                "archive_sha256": spec["archive_sha256"],
                "license_url": spec["license_url"],
                "license_record": spec["license_record"],
                "archive_pdf_updated": spec["archive_pdf_updated"],
                "local_pdf_path": spec["local_pdf"],
                "local_pdf_sha256": _sha(pdf_path),
                "local_pdf_size_bytes": pdf_path.stat().st_size,
                "local_pdf_updated": spec["pdf_updated"],
                "archive_binary_equal": _sha(pdf_path) == spec["archive_sha256"],
                "page_count": len(actual_pages),
                "selected_source_rule": (
                    "fixed consecutive Introduction sentences or fixed Learning Goals bullets; "
                    "selection precedes all method predictions"
                ),
            }
        )
    return documents, page_texts


def _asset_index(package_root: Path) -> dict[str, dict]:
    records: dict[str, dict] = {}
    for spec in ASSET_SPECS:
        doc = SOURCE_DOCS[spec["doc_id"]]
        index_path = _package_path(package_root, doc["images_json"])
        inventory = json.loads(index_path.read_text(encoding="utf-8"))
        found = next(
            (
                row
                for row in inventory
                if row.get("page") == spec["page"]
                and row.get("xref") == spec["xref"]
                and row.get("path", "").endswith(spec["filename"])
            ),
            None,
        )
        if not found:
            raise ValueError(f"selected image absent from frozen extraction index: {spec['id']}")
        relative = f"{doc['image_dir']}/{spec['filename']}"
        path = _package_path(package_root, relative)
        if not path.is_file() or _sha(path) != found.get("sha256"):
            raise ValueError(f"selected image hash does not match extracted index: {spec['id']}")
        records[spec["id"]] = {
            **spec,
            "path": relative.replace("\\", "/"),
            "sha256": _sha(path),
            "size_bytes": path.stat().st_size,
            "width": found.get("width"),
            "height": found.get("height"),
            "license": "CC0 Public Domain (NOAA IR record for source document)",
            "license_url": SOURCE_DOCS[spec["doc_id"]]["license_url"],
            "provenance": (
                f"{SOURCE_DOCS[spec['doc_id']]['record_url']} ; page {spec['page']} ; "
                f"credit: {spec['caption']}"
            ),
            "source_url": SOURCE_DOCS[spec["doc_id"]]["archive_pdf_url"],
            "asset_review_status": "UNREVIEWED_CANDIDATE",
        }
    return records


def _claim_records(
    page_texts: dict[str, dict], assets: dict[str, dict], documents: list[dict]
) -> list[dict]:
    records: list[dict] = []
    local_pdf_hashes = {doc["document_id"]: doc["local_pdf_sha256"] for doc in documents}
    for doc_id, spec in SOURCE_DOCS.items():
        quotes = spec["archive_quotes"]
        locators = CLAIM_LOCATORS[doc_id]
        if len(quotes) != len(locators):
            raise ValueError(f"fixed selection count mismatch for {doc_id}")
        for index, (quote, (page_number, section_locator, local_id)) in enumerate(
            zip(quotes, locators, strict=True), start=1
        ):
            local_page = page_texts[doc_id][str(page_number)]
            normalized_page = _collapse(local_page)
            normalized_quote = _collapse(quote)
            position = normalized_page.find(normalized_quote)
            if position < 0 or normalized_page.find(normalized_quote, position + 1) >= 0:
                raise ValueError(
                    f"quote must occur exactly once in local PDF page: {doc_id}, {section_locator}"
                )
            context_start = max(0, position - 220)
            context_end = min(len(normalized_page), position + len(normalized_quote) + 220)
            context = normalized_page[context_start:context_end]
            claim_id = local_id
            source_id = f"{claim_id}-source"
            page_image_ids = [
                asset_id
                for asset_id, asset in assets.items()
                if asset["doc_id"] == doc_id
                and asset["page"] == page_number
                and doc_id in asset["source_ids"]
            ]
            records.append(
                {
                    "id": claim_id,
                    "document_id": doc_id,
                    "split": spec["split"],
                    "page_number": page_number,
                    "section_locator": section_locator,
                    "original_teaching_text": quote,
                    "knowledge_claim": quote,
                    "narration_text": quote,
                    "claim_derivation": "DETERMINISTIC_VERBATIM_SOURCE_SENTENCE_OR_BULLET",
                    "pronouns_or_ellipsis_modified": False,
                    "source_refs": [source_id],
                    "source_unit_id": source_id,
                    "source_unit_text": context,
                    "exact_claim_quote": quote,
                    "local_page_normalized_char_span": {
                        "start": position,
                        "end": position + len(normalized_quote),
                        "unit": "normalized_unicode_codepoint",
                        "end_exclusive": True,
                    },
                    "source_image_ids": page_image_ids,
                    "text_match_status": "DETERMINISTIC_LITERAL_MATCH_LOCAL_PDF_AND_ARCHIVE_EXCERPT",
                    "semantic_support_status": "VERBATIM_CLAIM_PROXY_NOT_INDEPENDENT_ENTAILMENT",
                    "official_archive_text_quote": quote,
                    "archive_binary_sha256": spec["archive_sha256"],
                    "local_pdf_text_sha256": local_pdf_hashes[doc_id],
                    "status": "SOURCE_LINKED_NOT_HUMAN_REVIEWED",
                    "selection_index_within_document": index,
                }
            )
    return records


def _write_dataset(package_root: Path) -> dict:
    documents, page_texts = _source_metadata(package_root)
    assets = _asset_index(package_root)
    claims = _claim_records(page_texts, assets, documents)
    dataset_dir = package_root / "dataset"
    claims_dir = dataset_dir / "cases"
    evidence_dir = dataset_dir / "source_evidence"
    graph_dir = dataset_dir / "proposition_graphs"
    board_dir = dataset_dir / "storyboards"
    raw_dir = dataset_dir / "raw_sources"
    for directory in (claims_dir, evidence_dir, graph_dir, board_dir, raw_dir):
        directory.mkdir(parents=True, exist_ok=True)

    doc_claims = {
        doc_id: [claim for claim in claims if claim["document_id"] == doc_id]
        for doc_id in SOURCE_DOCS
    }
    source_files: dict[str, str] = {}
    for doc_id, spec in SOURCE_DOCS.items():
        page_text = "\n\n".join(
            f"[PDF page {page_number}]\n{page_texts[doc_id][str(page_number)]}"
            for page_number in range(1, len(page_texts[doc_id]) + 1)
        )
        raw_path = raw_dir / f"{doc_id}.txt"
        _write_text(raw_path, page_text)
        raw_rel = raw_path.relative_to(package_root).as_posix()
        source_files[f"raw:{doc_id}"] = raw_rel
        image_records = []
        for asset_id, asset in assets.items():
            if asset["doc_id"] != doc_id or doc_id not in asset["source_ids"]:
                continue
            image_records.append(
                {
                    "id": asset_id,
                    "filename": Path(asset["path"]).name,
                    "description": asset["caption"],
                    "caption": asset["caption"],
                    "source_locator": f"NOAA archival PDF page {asset['page']}",
                    "page_number": asset["page"],
                    "asset_kind": "COMPLETE_SOURCE_IMAGE",
                    "availability": "AVAILABLE_LOCAL",
                    "teaching_asset_status": "ELIGIBLE_SOURCE_IMAGE_REQUIRES_VLM",
                    "sha256": asset["sha256"],
                    "local_path": asset["path"],
                    "license": asset["license"],
                    "license_url": asset["license_url"],
                }
            )
        for excluded in EXCLUDED_SOURCE_VISUALS:
            if excluded["doc_id"] != doc_id:
                continue
            image_records.append(
                {
                    "id": excluded["id"],
                    "filename": None,
                    "description": excluded["caption"],
                    "caption": excluded["caption"],
                    "source_locator": f"NOAA archival PDF page {excluded['page']}",
                    "page_number": excluded["page"],
                    "availability": "METADATA_ONLY_OR_MISSING",
                    "teaching_asset_status": "INELIGIBLE_RIGHTS_UNVERIFIED",
                    "local_path": None,
                    "license": None,
                    "rights_status": excluded["reason"],
                }
            )
        evidence = {
            "schema_version": "p0-source-evidence-v0.1",
            "document": {
                "document_id": doc_id,
                "raw_path": raw_rel,
                "raw_sha256": _sha(raw_path),
                "pdf_path": spec["local_pdf"],
                "pdf_sha256": next(d["local_pdf_sha256"] for d in documents if d["document_id"] == doc_id),
                "archive_record_url": spec["record_url"],
                "archive_pdf_sha256": spec["archive_sha256"],
                "status": "EXTRACTED_TEXT_FROM_OFFICIAL_OSU_HOSTED_COPY_RECONCILED_TO_NOAA_ARCHIVE_EXCERPTS",
            },
            "source_units": [
                {
                    "id": claim["source_unit_id"],
                    "text": claim["source_unit_text"],
                    "page_number": claim["page_number"],
                    "source_locator": (
                        f"NOAA PDF p.{claim['page_number']}, {claim['section_locator']}"
                    ),
                    "exact_claim_quote": claim["exact_claim_quote"],
                    "archive_binary_sha256": spec["archive_sha256"],
                    "local_pdf_normalized_char_span": claim[
                        "local_page_normalized_char_span"
                    ],
                    "link_status": "DETERMINISTIC_LITERAL_MATCH_NOT_SEMANTIC_GOLD",
                }
                for claim in doc_claims[doc_id]
            ],
            "source_images": image_records,
            "claim": (
                "Only selected verbatim teaching text and page-linked, NOAA-credited images are "
                "included. Image status is an unreviewed candidate, not ACCEPT."
            ),
        }
        evidence_path = evidence_dir / f"{doc_id}.json"
        _write(evidence_path, evidence)
        source_files[f"source_evidence:{doc_id}"] = evidence_path.relative_to(package_root).as_posix()

    for claim in claims:
        doc_id = claim["document_id"]
        doc_claims_list = doc_claims[doc_id]
        index = doc_claims_list.index(claim) + 1
        segment_id = f"segment-{index:03d}"
        prop_id = claim["id"]
        graph = {
            "schema_version": "p0-proposition-graph-v1.0",
            "case_id": doc_id,
            "raw_sha256": next(d["local_pdf_sha256"] for d in documents if d["document_id"] == doc_id),
            "source_evidence_path": f"dataset/source_evidence/{doc_id}.json",
            "storyboard_path": f"dataset/storyboards/{doc_id}.json",
            "knowledge_propositions": [
                {
                    "id": f"{prop_id}-kprop",
                    "knowledge_point_id": f"{doc_id}-source-section",
                    "text": claim["knowledge_claim"],
                    "source_refs": claim["source_refs"],
                    "source_anchor": claim["exact_claim_quote"],
                    "status": "DETERMINISTIC_VERBATIM_SOURCE_DERIVATION_NOT_HUMAN_GOLD",
                }
            ],
            "narration_propositions": [
                {
                    "id": prop_id,
                    "segment_id": segment_id,
                    "text": claim["narration_text"],
                    "span": {
                        "start": 0,
                        "end": len(claim["narration_text"]),
                        "unit": "unicode_codepoint",
                        "end_exclusive": True,
                    },
                    "knowledge_proposition_ids": [f"{prop_id}-kprop"],
                    "source_refs": claim["source_refs"],
                    "status": "DETERMINISTIC_VERBATIM_SOURCE_DERIVATION_NOT_HUMAN_GOLD",
                }
            ],
            "claim": "A verbatim development input graph; source entailment and atomicity are not human-validated.",
        }
        graph_path = graph_dir / f"{prop_id}.json"
        _write(graph_path, graph)
        source_files[f"graph:{prop_id}"] = graph_path.relative_to(package_root).as_posix()
        storyboard = {
            "segments": [
                {
                    "id": segment_id,
                    "narration": claim["narration_text"],
                    "source_page_number": claim["page_number"],
                    "elements": [
                        {"type": "image", "source_image_id": image_id}
                        for image_id in claim["source_image_ids"]
                    ],
                }
            ]
        }
        board_path = board_dir / f"{prop_id}.json"
        _write(board_path, storyboard)
        source_files[f"storyboard:{prop_id}"] = board_path.relative_to(package_root).as_posix()
        case_dir = claims_dir / prop_id
        case_dir.mkdir(parents=True, exist_ok=True)
        _write(case_dir / "input.json", claim)
        source_files[f"claim:{prop_id}"] = (case_dir / "input.json").relative_to(package_root).as_posix()

    catalog_assets = []
    for asset in assets.values():
        catalog_assets.append(
            {
                "id": asset["id"],
                "title": asset["title"],
                "caption": asset["caption"],
                "description": asset["caption"],
                "tags": " ".join(asset["tags"]),
                "path": asset["path"],
                "sha256": asset["sha256"],
                "license": asset["license"],
                "provenance": asset["provenance"],
                "source_url": asset["source_url"],
                "source_document_id": asset["doc_id"],
                "source_page": asset["page"],
                "credit": asset["caption"],
                "status": "UNREVIEWED_CANDIDATE",
            }
        )
    catalog = {
        "schema_version": "p0-retrieval-catalog-local-rag-v1.0",
        "summary": {
            "policy": "fixed four-image local pool; no open-web fetch or image generation",
            "assets": [
                {
                    key: asset[key]
                    for key in ("id", "title", "caption", "description", "tags", "license")
                }
                for asset in catalog_assets
            ],
        },
        "assets": catalog_assets,
    }
    catalog_path = dataset_dir / "retrieval_catalog.json"
    _write(catalog_path, catalog)
    source_files["catalog"] = catalog_path.relative_to(package_root).as_posix()
    _write(dataset_dir / "documents.json", {"dataset_id": PACKAGE_ID, "documents": documents})
    source_files["archive_quote_checks"] = "dataset/archive_quote_checks.json"
    source_files["source_retrieval_attempts"] = "dataset/source_retrieval_attempts.json"
    source_files["assets"] = "dataset/assets.json"
    _write(dataset_dir / "documents.json", {"dataset_id": PACKAGE_ID, "documents": documents})
    source_files["documents"] = "dataset/documents.json"
    _write(dataset_dir / "selections.json", {"claims": claims})
    source_files["selections"] = "dataset/selections.json"
    _write(
        dataset_dir / "archive_quote_checks.json",
        {
            "source": "NOAA IR archived PDF browser text extraction",
            "check_type": "literal quote reconciliation; archived raw PDF binaries are referenced by NOAA SHA-256 and URL",
            "claims": [
                {
                    "claim_id": claim["id"],
                    "archive_pdf_url": SOURCE_DOCS[claim["document_id"]]["archive_pdf_url"],
                    "archive_pdf_sha256": claim["archive_binary_sha256"],
                    "local_pdf_sha256": claim["local_pdf_text_sha256"],
                    "exact_quote": claim["exact_claim_quote"],
                    "archive_text_match": True,
                    "local_text_match": claim["text_match_status"].startswith("DETERMINISTIC"),
                    "binary_equality_claimed": False,
                }
                for claim in claims
            ],
        },
    )
    retrieval_attempts = {
        "attempts": [
            {
                "url": "https://repository.library.noaa.gov/view/noaa/56861/noaa_56861_DS1.pdf",
                "status": "HTTP_403_FORBIDDEN",
                "used_as_local_source_bytes": False,
            },
            {
                "url": "https://repository.library.noaa.gov/view/noaa/60590/noaa_60590_DS1.pdf",
                "status": "HTTP_403_FORBIDDEN",
                "used_as_local_source_bytes": False,
            },
            {
                "url": "https://repository.library.noaa.gov/view/noaa/56860/noaa_56860_DS1.pdf",
                "status": "HTTP_403_FORBIDDEN",
                "used_as_local_source_bytes": False,
            },
            {
                "url": "https://seagrant.oregonstate.edu/sites/seagrant.oregonstate.edu/files/orsea3_-_salmon_stats_lesson.pdf",
                "status": "200_OFFICIAL_OSU_HOSTED_COPY",
                "sha256": next(d["local_pdf_sha256"] for d in documents if d["document_id"] == "noaa-60590-salmon"),
                "selected": True,
            },
        ],
        "note": "Local OSU-hosted edition hashes are recorded separately and are not claimed byte-identical to NOAA archive files.",
    }
    _write(dataset_dir / "source_retrieval_attempts.json", retrieval_attempts)
    _write(dataset_dir / "assets.json", {"assets": list(assets.values())})
    return {
        "documents": documents,
        "claims": claims,
        "assets": assets,
        "source_files": source_files,
        "catalog": catalog,
    }


def _config() -> dict:
    return _json(ROOT / CONFIG_REL)


def _source_code_snapshot(package_root: Path) -> dict[str, str]:
    snapshot_dir = package_root / "code_snapshot"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for relative in SOURCE_FILES:
        source = ROOT / relative
        if not source.is_file():
            raise FileNotFoundError(f"required implementation source missing: {relative}")
        destination = snapshot_dir / Path(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        hashes[relative] = _sha(source)
    git_status = __import__("subprocess").run(
        ["git", "status", "--short", "--branch"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    diff = __import__("subprocess").run(
        ["git", "diff", "HEAD", "--", *SOURCE_FILES],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    _write_text(snapshot_dir / "git_status.txt", git_status)
    _write_text(snapshot_dir / "relevant_worktree_diff.patch", diff)
    hashes["code_snapshot/git_status.txt"] = _sha(snapshot_dir / "git_status.txt")
    hashes["code_snapshot/relevant_worktree_diff.patch"] = _sha(
        snapshot_dir / "relevant_worktree_diff.patch"
    )
    return hashes


def _protocol(package_root: Path, data: dict, code_hashes: dict[str, str]) -> dict:
    config = _config()
    claims = data["claims"]
    comparison_claims = [claim for claim in claims if claim["split"] == "comparison"]
    methods = list(BASELINE_IDS) + list(METHOD_CONDITIONS)
    tasks = []
    for claim in comparison_claims:
        ordered_methods = methods.copy()
        random.Random(f"{RUN_ID}:{claim['id']}:opaque-labels").shuffle(ordered_methods)
        method_to_option = {
            method: f"option-{index:02d}"
            for index, method in enumerate(ordered_methods, start=1)
        }
        option_to_method = {value: key for key, value in method_to_option.items()}
        forward = list(option_to_method)
        random.Random(f"{RUN_ID}:{claim['id']}:judge-order").shuffle(forward)
        tasks.append(
            {
                "proposition_id": claim["id"],
                "document_id": claim["document_id"],
                "split": claim["split"],
                "input_path": f"dataset/cases/{claim['id']}/input.json",
                "graph_path": f"dataset/proposition_graphs/{claim['id']}.json",
                "source_evidence_path": f"dataset/source_evidence/{claim['document_id']}.json",
                "storyboard_path": f"dataset/storyboards/{claim['id']}.json",
                "catalog_path": "dataset/retrieval_catalog.json",
                "methods": methods,
                "method_to_option": method_to_option,
                "option_to_method": option_to_method,
                "judge_forward_order": forward,
                "judge_reverse_order": list(reversed(forward)),
                "asset_review_conditions": list(config["asset_review"]["condition_ids"]),
            }
        )
    input_paths = {}
    for relative in sorted(set(data["source_files"].values())):
        path = _package_path(package_root, relative)
        input_paths[relative] = {"sha256": _sha(path), "size_bytes": path.stat().st_size}
    for doc in data["documents"]:
        relative = doc["local_pdf_path"]
        path = _package_path(package_root, relative)
        input_paths[relative] = {"sha256": _sha(path), "size_bytes": path.stat().st_size}
        spec = SOURCE_DOCS[doc["document_id"]]
        for derived_index in (spec["pages_json"], spec["images_json"]):
            index_path = _package_path(package_root, derived_index)
            input_paths[derived_index] = {
                "sha256": _sha(index_path),
                "size_bytes": index_path.stat().st_size,
            }
    for asset in data["assets"].values():
        relative = asset["path"]
        path = _package_path(package_root, relative)
        input_paths[relative] = {"sha256": _sha(path), "size_bytes": path.stat().st_size}
    for relative in code_hashes:
        if relative.startswith("code_snapshot/"):
            path = _package_path(package_root, relative)
        else:
            path = _package_path(package_root, f"code_snapshot/{relative}")
            relative = f"code_snapshot/{relative}"
        input_paths[relative] = {"sha256": _sha(path), "size_bytes": path.stat().st_size}
    return {
        "schema_version": "rq1-run-protocol-using-existing-artifacts-v1",
        "dataset_id": PACKAGE_ID,
        "run_id": RUN_ID,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "scope": config["scope"],
        "package_root_from_run": "..",
        "git": {
            "branch": __import__("subprocess").run(
                ["git", "branch", "--show-current"], cwd=ROOT, check=True,
                capture_output=True, text=True, encoding="utf-8"
            ).stdout.strip(),
            "head": __import__("subprocess").run(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                capture_output=True, text=True, encoding="utf-8"
            ).stdout.strip(),
            "results_include_uncommitted_code": True,
            "code_snapshot_hashes": code_hashes,
        },
        "conditions": {
            "direct_llm": "same claim, sources, images, and frozen pool; direct action choice without staged proposed criteria",
            "proposed": "visual need, source sufficiency, retrieval suitability, source fidelity, and uncertainty are explicitly evaluated",
            "no_source": "claim remains visible; source refs/context/captions/pixels removed; frozen retrieval catalog stays the same; reuse unavailable",
            "without_source_sufficiency": "source input is retained; explicit sufficiency criterion/output removed; normalized field UNKNOWN",
            "without_retrieval_suitability": "source input is retained; explicit suitability criterion/output removed; normalized field UNKNOWN",
            "without_uncertainty_handling": "source input is retained; abstain/uncertain choice removed; safety gates remain unchanged",
            "never_retrieve": "existing baseline: reuse linked page image if one exists, else none",
            "always_retrieve": "existing baseline: retrieve for every claim from fixed local catalog",
            "keyword_heuristic": "existing deterministic baseline with a versioned English lexicon for this English corpus; source image reuse takes precedence",
        },
        "models": config["models"],
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "packages": {
                name: _distribution_version(name)
                for name in ("jsonschema", "litellm", "PyMuPDF", "pydantic")
            },
            "reproducibility_note": "Python/package versions are recorded; provider model alias versions are not independently verifiable.",
        },
        "judges": {
            "aliases": config["models"]["judge_models"],
            "known_model_series": None,
            "independence_limit": "Provider only exposes aliases here; distinct underlying model families/versions are unverified.",
            "blind_method_names": True,
            "blind_method_rationales": True,
            "method_option_mapping_not_sent_to_judge": True,
        },
        "assets": {
            "retrieval_mode": "FROZEN_LOCAL_CATALOG_ONLY",
            "min_lexical_score": config["acquisition"]["minimum_lexical_score"],
            "image_generation_calls": 0,
            "tts_calls": 0,
            "recording_calls": 0,
            "health_check_calls": 0,
            "formal_acceptance": False,
        },
        "selection": {
            "rule": config["selection"]["rule"],
            "action_balance": False,
            "proposition_text_rewritten": False,
            "split_by_document": True,
            "human_gold_required": False,
        },
        "budget": {
            "max_transport_calls": config["max_transport_calls"],
            "allocation": config["call_allocation"],
            "automatic_retries": 0,
            "format_repair_policy": "No automatic repair; an explicitly used format repair would consume one reserved transfer.",
            "interrupted_started_calls_are_not_retried": True,
            "budget_is_not_reset_on_resume": True,
        },
        "inputs": input_paths,
        "tasks": tasks,
        "planned_development_tasks": [
            {
                "proposition_id": claim["id"],
                "document_id": claim["document_id"],
                "conditions": ["direct_llm", "proposed"],
                "input_path": f"dataset/cases/{claim['id']}/input.json",
                "graph_path": f"dataset/proposition_graphs/{claim['id']}.json",
                "source_evidence_path": f"dataset/source_evidence/{claim['document_id']}.json",
                "storyboard_path": f"dataset/storyboards/{claim['id']}.json",
                "catalog_path": "dataset/retrieval_catalog.json",
            }
            for claim in claims
            if claim["split"] == "development"
        ],
        "primary_metrics": [
            "planned-denominator method/action coverage, abstention and failure",
            "double-blind-proposal Judge ranking, acceptable/rejected sets, six axes, model/order sensitivity",
            "source-reference/literal-quote/hash/candidate legality checks",
            "fixed-pool acquisition outcomes, kept separate from decision preference",
        ],
        "claim_boundary": "Development-only proxy evaluation; no human truth, learning effect, formal Gate, or superiority claim.",
    }


def _distribution_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def prepare(package_root: Path) -> Path:
    package_root = package_root.resolve()
    if not package_root.is_dir():
        raise FileNotFoundError(f"source package directory does not exist: {package_root}")
    run_dir = package_root / RUN_REL
    if (run_dir / "protocol.json").exists():
        raise FileExistsError(f"run is already prepared; do not overwrite: {run_dir}")
    if (package_root / "dataset/selections.json").exists() or (package_root / "code_snapshot").exists():
        raise FileExistsError(
            "dataset or code snapshot already exists; preserve it and prepare a new package directory"
        )
    data = _write_dataset(package_root)
    code_hashes = _source_code_snapshot(package_root)
    config_copy = package_root / "code_snapshot" / CONFIG_REL
    config_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / CONFIG_REL, config_copy)
    code_hashes[str(CONFIG_REL).replace("\\", "/")] = _sha(config_copy)
    protocol = _protocol(package_root, data, code_hashes)
    run_dir.mkdir(parents=True, exist_ok=False)
    _write(run_dir / "protocol.json", protocol)
    _write(run_dir / "calls.json", [])
    _write(run_dir / "prepare.json", {
        "status": "PREPARED_NO_MODEL_CALLS",
        "dataset_id": PACKAGE_ID,
        "run_id": RUN_ID,
        "planned_comparison_propositions": len(protocol["tasks"]),
        "planned_development_propositions": len(protocol["planned_development_tasks"]),
        "prepared_at_utc": datetime.now(UTC).isoformat(),
    })
    return run_dir


def _protocol_path(run_dir: Path) -> Path:
    path = run_dir / "protocol.json"
    if not path.is_file():
        raise FileNotFoundError(f"run protocol is missing: {path}")
    return path


def _verify_inputs(package_root: Path, protocol: dict) -> list[dict]:
    findings = []
    for relative, expected in protocol["inputs"].items():
        path = _package_path(package_root, relative)
        if not path.is_file():
            findings.append({"path": relative, "status": "MISSING"})
            continue
        actual = _sha(path)
        findings.append(
            {
                "path": relative,
                "status": "OK" if actual == expected["sha256"] else "HASH_MISMATCH",
                "expected_sha256": expected["sha256"],
                "actual_sha256": actual,
                "size_matches": path.stat().st_size == expected["size_bytes"],
            }
        )
    bad = [item for item in findings if item["status"] != "OK" or not item.get("size_matches", True)]
    if bad:
        raise ValueError(f"frozen run input verification failed: {bad[:3]}")
    return findings


def _verify_protocol_and_claims(package_root: Path, protocol: dict) -> dict:
    _verify_inputs(package_root, protocol)
    selections = _json(package_root / "dataset/selections.json")["claims"]
    issues = []
    for claim in selections:
        case = _json(package_root / f"dataset/cases/{claim['id']}/input.json")
        evidence = _json(package_root / f"dataset/source_evidence/{claim['document_id']}.json")
        refs = [item for item in evidence["source_units"] if item["id"] in case["source_refs"]]
        if len(refs) != 1:
            issues.append({"claim_id": claim["id"], "code": "SOURCE_REF_RESOLUTION_FAILED"})
            continue
        unit = refs[0]
        if _collapse(case["original_teaching_text"]) != _collapse(case["knowledge_claim"]):
            issues.append({"claim_id": claim["id"], "code": "CLAIM_TEXT_DRIFT"})
        if _collapse(case["exact_claim_quote"]) not in _collapse(unit["text"]):
            issues.append({"claim_id": claim["id"], "code": "QUOTE_NOT_IN_SOURCE_UNIT"})
        if case["pronouns_or_ellipsis_modified"] or case["claim_derivation"].startswith("LLM"):
            issues.append({"claim_id": claim["id"], "code": "UNDECLARED_TEXT_TRANSFORMATION"})
    if issues:
        raise ValueError(f"source link verification failed: {issues[:4]}")
    return {
        "source_ref_resolution": len(selections),
        "literal_source_quote_matches": len(selections),
        "changed_claim_texts": 0,
        "semantic_support": "VERBATIM_CLAIM_PROXY_NOT_INDEPENDENT_ENTAILMENT",
        "asset_count": len(_json(package_root / "dataset/retrieval_catalog.json")["assets"]),
        "asset_hashes_verified": True,
        "formal_accepts": 0,
    }


def _build_output_manifest(run_dir: Path, protocol: dict) -> dict:
    excluded = {"output_manifest.json", "verify.json", "run.lock"}
    files = []
    for path in sorted(item for item in run_dir.rglob("*") if item.is_file()):
        relative = path.relative_to(run_dir).as_posix()
        if relative in excluded or path.name in excluded:
            continue
        files.append({
            "path": relative,
            "size_bytes": path.stat().st_size,
            "sha256": _sha(path),
        })
    return {
        "schema_version": "rq1-run-output-manifest-v1",
        "dataset_id": protocol["dataset_id"],
        "run_id": protocol["run_id"],
        "protocol_sha256": _sha(run_dir / "protocol.json"),
        "files": files,
    }


def _verify_output_manifest(run_dir: Path, protocol: dict) -> dict:
    manifest_path = run_dir / "output_manifest.json"
    if not manifest_path.is_file():
        return {"status": "NOT_FINALIZED", "verified_files": 0}
    manifest = _json(manifest_path)
    if manifest.get("protocol_sha256") != _sha(run_dir / "protocol.json"):
        raise ValueError("output manifest protocol hash differs from the frozen protocol")
    expected = {item["path"]: item for item in manifest.get("files", [])}
    actual = {
        path.relative_to(run_dir).as_posix(): path
        for path in run_dir.rglob("*")
        if path.is_file() and path.name not in {"output_manifest.json", "verify.json", "run.lock"}
    }
    if set(expected) != set(actual):
        raise ValueError("run output files differ from the frozen output manifest")
    for relative, path in actual.items():
        item = expected[relative]
        if path.stat().st_size != item["size_bytes"] or _sha(path) != item["sha256"]:
            raise ValueError(f"run output hash mismatch: {relative}")
    calls = _json_calls(run_dir)
    if len(calls) > protocol["budget"]["max_transport_calls"]:
        raise ValueError("run exceeded the frozen transport-call budget")
    allowed_stages = {
        "development_method", "comparison_method", "blind_proposal_judge", "asset_proxy_review"
    }
    unexpected = sorted({item.get("stage") for item in calls} - allowed_stages)
    if unexpected:
        raise ValueError(f"run contains unplanned transport stages: {unexpected}")
    return {
        "status": "PASS",
        "verified_files": len(expected),
        "model_calls": len(calls),
    }


def verify(package_root: Path, *, run_dir: Path | None = None) -> dict:
    package_root = package_root.resolve()
    run_dir = run_dir.resolve() if run_dir else package_root / RUN_REL
    protocol = _json(_protocol_path(run_dir))
    findings = _verify_inputs(package_root, protocol)
    claims = _verify_protocol_and_claims(package_root, protocol)
    output_manifest = _verify_output_manifest(run_dir, protocol)
    result = {
        "status": "PASS",
        "dataset_id": protocol["dataset_id"],
        "run_id": protocol["run_id"],
        "verified_at_utc": datetime.now(UTC).isoformat(),
        "protocol_sha256": _sha(run_dir / "protocol.json"),
        "verified_inputs": len(findings),
        "claims": claims,
        "model_calls": len(_json_calls(run_dir)),
        "model_calls_during_verify": 0,
        "output_manifest": output_manifest,
        "findings": findings,
    }
    _write(run_dir / "verify.json", result)
    return result


def _json_calls(run_dir: Path) -> list[dict]:
    path = run_dir / "calls.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def _read_task(package_root: Path, task: dict) -> tuple[dict, dict, dict, dict]:
    claim = _json(_package_path(package_root, task["input_path"]))
    graph = _json(_package_path(package_root, task["graph_path"]))
    evidence = _json(_package_path(package_root, task["source_evidence_path"]))
    storyboard = _json(_package_path(package_root, task["storyboard_path"]))
    return claim, graph, evidence, storyboard


def _runtime_evidence(package_root: Path, evidence: dict) -> dict:
    output = copy.deepcopy(evidence)
    for item in output.get("source_images", []):
        if item.get("local_path"):
            item["local_path"] = str(_package_path(package_root, item["local_path"]))
    return output


def _runtime_catalog(package_root: Path, catalog: dict) -> dict:
    output = copy.deepcopy(catalog)
    for item in output.get("assets", []):
        item["path"] = str(_package_path(package_root, item["path"]))
    return output


def _task_paths(package_root: Path, run_dir: Path, task: dict, claim: dict, evidence: dict):
    work_dir = run_dir / "work" / claim["id"]
    work_dir.mkdir(parents=True, exist_ok=True)
    graph = _json(_package_path(package_root, task["graph_path"]))
    storyboard = _json(_package_path(package_root, task["storyboard_path"]))
    runtime_evidence = _runtime_evidence(package_root, evidence)
    runtime_catalog = _runtime_catalog(
        package_root,
        _json(_package_path(package_root, task["catalog_path"])),
    )
    graph_path = work_dir / "proposition_graph.json"
    evidence_path = work_dir / "source_evidence.json"
    storyboard_path = work_dir / "storyboard.json"
    catalog_path = work_dir / "retrieval_catalog.json"
    _write(graph_path, graph)
    _write(evidence_path, runtime_evidence)
    _write(storyboard_path, storyboard)
    _write(catalog_path, runtime_catalog)
    return graph_path, evidence_path, storyboard_path, catalog_path, runtime_evidence, runtime_catalog


def _acquire_decision(
    *,
    package_root: Path,
    run_dir: Path,
    claim: dict,
    decision: dict,
    evidence: dict,
    catalog: dict,
    method_id: str,
    catalog_rel: str = "dataset/retrieval_catalog.json",
    require_explicit_license: bool = False,
) -> dict:
    output_dir = run_dir / "acquisitions" / _safe_id(method_id) / _safe_id(claim["id"])
    output_dir.mkdir(parents=True, exist_ok=True)
    decision_doc = {
        "schema_version": DECISION_VERSION,
        "decisions": [decision],
    }
    decision_path = output_dir / "decision.json"
    _write(decision_path, decision_doc)
    evidence_rel = f"dataset/source_evidence/{claim['document_id']}.json"
    with _working_directory(package_root):
        result_path = execute_visual_acquisition(
            decision_path=decision_path,
            output_dir=output_dir,
            retrieval_catalog_path=catalog_rel,
            enable_generation=False,
            source_evidence_path=evidence_rel,
            content_addressed_assets=True,
            min_retrieval_score=0.25,
            require_explicit_license=require_explicit_license,
        )
    result = _json(result_path)
    for key in ("decision_path",):
        raw_path = result.get(key)
        if raw_path:
            result[key] = Path(raw_path).resolve().relative_to(package_root.resolve()).as_posix()
    result["retrieval_catalog_path"] = catalog_rel
    result["source_evidence_path"] = evidence_rel
    for asset in result.get("assets", []):
        raw_path = asset.get("local_path")
        if raw_path and Path(raw_path).is_file():
            asset["local_path"] = Path(raw_path).resolve().relative_to(package_root.resolve()).as_posix()
    _write(result_path, result)
    return result


def _asset_by_id(package_root: Path, asset_id: str) -> dict | None:
    catalog = _json(package_root / "dataset/retrieval_catalog.json")
    return next((item for item in catalog["assets"] if item["id"] == asset_id), None)


def _asset_status(acquisition: dict) -> dict:
    assets = acquisition.get("assets", [])
    return assets[0] if assets else {"status": "ACQUISITION_RESULT_MISSING"}


def _prediction_path(run_dir: Path, split: str, method_id: str, proposition_id: str) -> Path:
    return run_dir / "predictions" / split / _safe_id(method_id) / f"{_safe_id(proposition_id)}.json"


def _method_row(run_dir: Path, split: str, method_id: str, proposition_id: str) -> dict | None:
    path = _prediction_path(run_dir, split, method_id, proposition_id)
    return _json(path) if path.is_file() else None


def _make_baseline(
    *, package_root: Path, run_dir: Path, task: dict, method_id: str,
    require_explicit_license: bool = False,
    keyword_terms: frozenset[str] | set[str] | None = None,
) -> dict:
    claim, graph, evidence, storyboard = _read_task(package_root, task)
    proposition = graph["narration_propositions"][0]
    source_image_ids = list(claim.get("source_image_ids") or [])
    catalog = _json(_package_path(package_root, task["catalog_path"]))
    candidate_ids = [str(asset["id"]) for asset in catalog["assets"]]
    options = {"policy": method_id, "proposition": proposition, "source_image_ids": source_image_ids,
               "external_candidate_ids": candidate_ids}
    if method_id == "keyword_heuristic":
        options["keyword_terms"] = keyword_terms if keyword_terms is not None else ENGLISH_KEYWORDS
    decision = predict_baseline(**options)
    decision["narration_proposition_id"] = proposition["id"]
    try:
        acquisition = _acquire_decision(
            package_root=package_root,
            run_dir=run_dir,
            claim=claim,
            decision=decision,
            evidence=evidence,
            catalog=catalog,
            method_id=method_id,
            catalog_rel=task.get("catalog_path", "dataset/retrieval_catalog.json"),
            require_explicit_license=require_explicit_license,
        )
        acquisition_status = "OK"
        acquisition_error = None
    except Exception as exc:
        acquisition = {"assets": [{"status": "ACQUISITION_FAILED"}]}
        acquisition_status = "FAILED"
        acquisition_error = {"type": type(exc).__name__, "message": str(exc)[:500]}
    row = {
        "status": "OK",
        "proposition_id": proposition["id"],
        "document_id": claim["document_id"],
        "split": claim["split"],
        "method_id": method_id,
        "decision": decision,
        "acquisition": acquisition,
        "acquisition_stage_status": acquisition_status,
        "acquisition_error": acquisition_error,
        "decision_model_calls": 0,
        "asset_review_status": "PENDING_OR_NOT_APPLICABLE",
    }
    path = _prediction_path(run_dir, claim["split"], method_id, proposition["id"])
    _write(path, row)
    return row


def _run_method_call(
    *,
    package_root: Path,
    run_dir: Path,
    protocol: dict,
    task: dict,
    condition: str,
    split: str,
    ledger: list[dict],
    max_tokens: int,
) -> dict:
    proposition_id = task["proposition_id"]
    claim, graph, evidence, storyboard = _read_task(package_root, task)
    graph_path = task["graph_path"]
    evidence_path = task["source_evidence_path"]
    board_path = task["storyboard_path"]
    catalog_path = task["catalog_path"]
    output_path = _prediction_path(run_dir, split, condition, proposition_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    decisions_path = output_path.with_name(f"{output_path.stem}.visual_decisions.json")
    call_ids: list[int] = []
    raw_responses: list[str] = []
    active_call: dict | None = None

    def transport(base_fn):
        def call(*args, **kwargs):
            nonlocal active_call
            if len(ledger) >= protocol["budget"]["max_transport_calls"]:
                raise RuntimeError("RQ1_TRANSPORT_BUDGET_EXHAUSTED")
            prompt = str(args[0])
            call_number = len(ledger) + 1
            call_id = call_number
            task_key = f"decision:{split}:{condition}:{proposition_id}"
            if any(item.get("task_key") == task_key for item in ledger):
                raise ValueError(f"a transfer is already reserved for this task; will not repeat: {task_key}")
            prompt_rel = f"prompts/{call_id:03d}-{_safe_id(task_key)}.txt"
            _write_text(run_dir / prompt_rel, prompt)
            image_hashes = []
            if len(args) > 1 and isinstance(args[1], list):
                for raw_image in args[1]:
                    image = Path(raw_image)
                    image_hashes.append({"sha256": _sha(image), "name": image.name})
            entry = {
                "call_id": call_id,
                "task_key": task_key,
                "stage": "development_method" if split == "development" else "comparison_method",
                "condition": condition,
                "model_alias": kwargs.get("model"),
                "provider": "ECNU OpenAI-compatible endpoint",
                "endpoint_host": urlparse(LLM_BASE_URL).hostname,
                "status": "STARTED",
                "reserved_before_transport": True,
                "prompt_path": prompt_rel,
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "images": image_hashes,
                "usage": None,
                "cost_usd": None,
                "elapsed_sec": None,
            }
            ledger.append(entry)
            _write(run_dir / "calls.json", ledger)
            call_ids.append(call_id)
            active_call = entry
            started = time.monotonic()
            try:
                kwargs["temperature"] = protocol["models"]["temperature"]
                kwargs["max_tokens"] = max_tokens
                kwargs["timeout"] = protocol["models"]["timeout_sec"]
                kwargs["num_retries"] = 0
                kwargs["max_retries"] = 0
                if client.litellm is not None:
                    kwargs["caching"] = False
                raw = base_fn(*args, **kwargs)
                entry.update(status="OK", raw_response=client.redact_response_text(str(raw)))
                raw_responses.append(str(raw))
                return raw
            except Exception as exc:
                entry.update(
                    status="FAILED",
                    error_type=type(exc).__name__,
                    error_message=client.redact_response_text(str(exc))[:800],
                )
                raise
            finally:
                entry["elapsed_sec"] = round(time.monotonic() - started, 3)
                _write(run_dir / "calls.json", ledger)

        return call

    original_text = __import__("textbook2video.research.visual_decision", fromlist=["chat_with_system"]).chat_with_system
    visual_module = __import__("textbook2video.research.visual_decision", fromlist=["chat_with_images"])
    original_images = visual_module.chat_with_images
    visual_module.chat_with_system = transport(client.chat_with_system)
    visual_module.chat_with_images = transport(client.chat_with_images)
    original_completion = client.litellm.completion if client.litellm is not None else None

    def observed_completion(*args, **kwargs):
        response = original_completion(*args, **kwargs)
        if active_call is not None:
            usage = getattr(response, "usage", None)
            if usage is not None:
                try:
                    active_call["usage"] = usage.model_dump(exclude_none=True)
                except AttributeError:
                    active_call["usage"] = dict(usage)
            hidden = getattr(response, "_hidden_params", None)
            if isinstance(hidden, dict) and hidden.get("response_cost") is not None:
                active_call["cost_usd"] = hidden["response_cost"]
        return response

    if original_completion:
        client.litellm.completion = observed_completion
    try:
        with _working_directory(package_root):
            decide_visual_support(
                proposition_graph_path=graph_path,
                source_evidence_path=evidence_path,
                storyboard_path=board_path,
                retrieval_catalog_path=catalog_path,
                output_path=decisions_path,
                model=protocol["models"]["method_model"],
                research_condition=condition,
            )
        decisions_doc = _json(decisions_path)
        decision = decisions_doc["decisions"][0]
        try:
            acquisition = _acquire_decision(
                package_root=package_root,
                run_dir=run_dir,
                claim=claim,
                decision=decision,
                evidence=evidence,
                catalog=_json(_package_path(package_root, task["catalog_path"])),
                method_id=condition,
                catalog_rel=task.get("catalog_path", "dataset/retrieval_catalog.json"),
                require_explicit_license=bool(
                    protocol.get("assets", {}).get("require_explicit_license", False)
                ),
            )
            acquisition_status = "OK"
            acquisition_error = None
        except Exception as exc:
            acquisition = {"assets": [{"status": "ACQUISITION_FAILED"}]}
            acquisition_status = "FAILED"
            acquisition_error = {
                "type": type(exc).__name__,
                "message": client.redact_response_text(str(exc))[:500],
            }
        row = {
            "status": "OK",
            "proposition_id": proposition_id,
            "document_id": claim["document_id"],
            "split": split,
            "method_id": condition,
            "decision": decision,
            "acquisition": acquisition,
            "acquisition_stage_status": acquisition_status,
            "acquisition_error": acquisition_error,
            "decision_model_calls": len(call_ids),
            "call_ids": call_ids,
            "raw_response": client.redact_response_text(raw_responses[-1]) if raw_responses else None,
            "decision_artifact_path": decisions_path.resolve().relative_to(package_root.resolve()).as_posix(),
            "validation_status": "SCHEMA_AND_TARGET_CHECKED",
            "asset_review_status": "PENDING_OR_NOT_APPLICABLE",
        }
        _write(output_path, row)
        return row
    except Exception as exc:
        row = {
            "status": "FAILED",
            "proposition_id": proposition_id,
            "document_id": claim["document_id"],
            "split": split,
            "method_id": condition,
            "error_type": type(exc).__name__,
            "error_message": client.redact_response_text(str(exc))[:1000],
            "decision_model_calls": len(call_ids),
            "call_ids": call_ids,
            "raw_response": client.redact_response_text(raw_responses[-1]) if raw_responses else None,
        }
        _write(output_path, row)
        return row
    finally:
        visual_module.chat_with_system = original_text
        visual_module.chat_with_images = original_images
        if original_completion:
            client.litellm.completion = original_completion


def _candidate_record(package_root: Path, acquisition: dict) -> dict:
    outcome = _asset_status(acquisition)
    candidate = None
    if outcome.get("catalog_candidate_id"):
        candidate = _asset_by_id(package_root, str(outcome["catalog_candidate_id"]))
    elif outcome.get("source_image_id"):
        candidate = _asset_by_id(package_root, str(outcome["source_image_id"]))
    local_path = outcome.get("local_path")
    if local_path:
        resolved = _package_path(package_root, local_path)
        if not resolved.is_file() or _sha(resolved) != outcome.get("sha256"):
            raise ValueError(f"materialized asset hash mismatch: {local_path}")
    return {"outcome": outcome, "candidate": candidate, "local_path": local_path}


def _blind_option(
    *, package_root: Path, method_id: str, option_id: str, row: dict | None,
) -> dict:
    if row is None or row.get("status") != "OK":
        return {
            "option_id": option_id,
            "proposal_status": "METHOD_OUTPUT_UNAVAILABLE",
            "action": "NOT_RUN",
            "uncertainty_status": "UNAVAILABLE",
            "acquisition_result": "UNAVAILABLE",
            "visual_asset": None,
        }
    decision = row["decision"]
    acquisition = row.get("acquisition") or {}
    asset = _candidate_record(package_root, acquisition)
    candidate = asset["candidate"] or {}
    outcome = asset["outcome"]
    visual_asset = None
    if candidate:
        visual_asset = {
            "image_label": None,
            "caption": candidate.get("caption"),
            "license_status": "NOAA_CC0_RECORD; IMAGE_STILL_UNREVIEWED",
        }
    if decision.get("action") == "generate":
        visual_asset = {
            "generation_request": decision.get("generation_prompt"),
            "status": "NOT_GENERATED",
        }
    elif decision.get("action") == "retrieve" and not candidate:
        visual_asset = {
            "retrieval_query": decision.get("retrieval_query"),
            "status": outcome.get("status"),
        }
    elif decision.get("action") == "none":
        visual_asset = {"status": "NO_EXTRA_ASSET_PROPOSED"}
    return {
        "option_id": option_id,
        "proposal_status": "DECISION_AVAILABLE",
        "action": decision.get("action"),
        "decision_state": decision.get("decision_state"),
        "uncertainty_status": {
            "abstain": bool(decision.get("abstain")),
            "uncertain": bool(decision.get("uncertain")),
        },
        "retrieval_query": decision.get("retrieval_query") if decision.get("action") == "retrieve" else None,
        "acceptance_criteria": decision.get("acceptance_criteria") if decision.get("action") == "retrieve" else None,
        "generation_request": decision.get("generation_prompt") if decision.get("action") == "generate" else None,
        "acquisition_result": outcome.get("status"),
        "visual_asset": visual_asset,
    }


def _judge_images_and_labels(
    package_root: Path, run_dir: Path, options: list[dict], task: dict
) -> tuple[list[str], list[str], list[dict]]:
    path_by_hash: dict[str, Path] = {}
    labels_by_hash: dict[str, str] = {}
    source_visual_metadata: list[dict] = []
    claim = _json(_package_path(package_root, task["input_path"]))
    evidence = _json(_package_path(package_root, task["source_evidence_path"]))
    source_units = [item for item in evidence["source_units"] if item["id"] in claim["source_refs"]]
    source_pages = {item.get("page_number") for item in source_units}
    for image in evidence.get("source_images", []):
        if image.get("page_number") not in source_pages:
            continue
        source_visual_metadata.append(
            {
                "type": "source_page_visual_inventory",
                "id": image.get("id"),
                "caption": image.get("caption"),
                "source_locator": image.get("source_locator"),
                "availability": image.get("availability"),
                "teaching_asset_status": image.get("teaching_asset_status"),
                "rights_status": image.get("rights_status"),
            }
        )
        local_path = image.get("local_path")
        if local_path:
            path = _package_path(package_root, local_path)
            if path.is_file():
                digest = _sha(path)
                path_by_hash.setdefault(digest, path)
                labels_by_hash.setdefault(digest, f"source-image-{len(labels_by_hash) + 1:02d}")
    for option in options:
        ref = option.get("visual_asset")
        if not isinstance(ref, dict):
            continue
        method = task["option_to_method"][option["option_id"]]
        row = _method_row(run_dir, "comparison", method, task["proposition_id"])
        if not row or row.get("status") != "OK":
            continue
        path_value = _asset_status(row.get("acquisition") or {}).get("local_path")
        if not path_value:
            continue
        path = _package_path(package_root, path_value)
        if not path.is_file():
            continue
        digest = _sha(path)
        path_by_hash.setdefault(digest, path)
        labels_by_hash.setdefault(digest, f"candidate-image-{len(labels_by_hash) + 1:02d}")
        ref["image_label"] = labels_by_hash[digest]
    return (
        [labels_by_hash[key] for key in path_by_hash],
        [str(path) for path in path_by_hash.values()],
        source_visual_metadata,
    )


def _record_unavailable_task(run_dir: Path, split: str, method: str, task: dict, reason: str) -> dict:
    path = _prediction_path(run_dir, split, method, task["proposition_id"])
    if path.is_file():
        return _json(path)
    row = {
        "status": "INTERRUPTED_REMOTE_RESULT_UNKNOWN",
        "proposition_id": task["proposition_id"],
        "document_id": task["document_id"],
        "split": split,
        "method_id": method,
        "error_message": reason,
        "decision_model_calls": 1,
        "retry": "FORBIDDEN_FOR_THIS_RESERVED_TASK",
    }
    _write(path, row)
    return row


def _asset_review_prompt(claim: dict, source_unit: dict, candidate: dict) -> str:
    payload = {
        "task": "Evaluate the fit of the supplied existing image to the source-backed teaching claim.",
        "claim": claim["knowledge_claim"],
        "source_excerpt": source_unit["text"],
        "exact_source_quote": source_unit["exact_claim_quote"],
        "candidate_metadata": {
            "caption": candidate.get("caption"),
            "license_status": "NOAA CC0 source record; asset remains an unreviewed candidate",
            "source_locator": candidate.get("provenance"),
        },
        "requirements": [
            "Describe only visible objects/relations, not topic similarity alone.",
            "Decide whether the image explains this particular claim, is redundant, or is misleading.",
            "Do not issue formal ACCEPT/REJECT or source-gate status.",
            "Use UNCERTAIN when details are unreadable or source relation is unclear.",
            "Return JSON only.",
        ],
        "output_schema": {
            "fit": "MATCH|PARTIAL|MISMATCH|UNCERTAIN",
            "visible_evidence": "brief description of pixels",
            "claim_relation": "brief explanation tied to the exact source quote",
            "redundant_or_decorative": "boolean",
            "uncertainty": "brief reason or null",
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _run_asset_review(
    *, package_root: Path, run_dir: Path, protocol: dict, task: dict, method_id: str,
    row: dict, ledger: list[dict],
) -> dict:
    output_path = run_dir / "asset_reviews" / f"{_safe_id(method_id)}-{_safe_id(task['proposition_id'])}.json"
    if output_path.exists():
        return _json(output_path)
    claim = _json(_package_path(package_root, task["input_path"]))
    source_evidence = _json(_package_path(package_root, task["source_evidence_path"]))
    source_unit = next(item for item in source_evidence["source_units"] if item["id"] in claim["source_refs"])
    acquisition = row.get("acquisition") or {}
    asset = _candidate_record(package_root, acquisition)
    outcome = asset["outcome"]
    local_path = asset["local_path"]
    candidate = asset["candidate"]
    if not local_path or not candidate:
        result = {
            "status": "NOT_APPLICABLE_NO_MATERIALIZED_IMAGE",
            "proposition_id": task["proposition_id"],
            "method_id": method_id,
            "decision_action": row.get("decision", {}).get("action"),
            "acquisition_status": outcome.get("status"),
            "asset_review_model_calls": 0,
            "formal_acceptance": False,
        }
        _write(output_path, result)
        return result
    prompt = _asset_review_prompt(claim, source_unit, candidate)
    if len(ledger) >= protocol["budget"]["max_transport_calls"]:
        result = {
            "status": "BUDGET_NOT_AVAILABLE",
            "proposition_id": task["proposition_id"],
            "method_id": method_id,
            "asset_review_model_calls": 0,
            "formal_acceptance": False,
        }
        _write(output_path, result)
        return result
    task_key = f"asset_review:{method_id}:{task['proposition_id']}"
    if any(item.get("task_key") == task_key for item in ledger):
        result = {
            "status": "INTERRUPTED_REMOTE_RESULT_UNKNOWN",
            "proposition_id": task["proposition_id"],
            "method_id": method_id,
            "asset_review_model_calls": 1,
            "retry": "FORBIDDEN_FOR_THIS_RESERVED_TASK",
            "formal_acceptance": False,
        }
        _write(output_path, result)
        return result
    call_id = len(ledger) + 1
    prompt_rel = f"prompts/{call_id:03d}-{_safe_id(task_key)}.txt"
    _write_text(run_dir / prompt_rel, prompt)
    entry = {
        "call_id": call_id,
        "task_key": task_key,
        "stage": "asset_proxy_review",
        "condition": method_id,
        "model_alias": protocol["models"]["asset_review_model"],
        "provider": "ECNU OpenAI-compatible endpoint",
        "endpoint_host": urlparse(LLM_BASE_URL).hostname,
        "status": "STARTED",
        "reserved_before_transport": True,
        "prompt_path": prompt_rel,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "images": [{"sha256": _sha(_package_path(package_root, local_path)), "name": Path(local_path).name}],
        "usage": None,
        "cost_usd": None,
    }
    ledger.append(entry)
    _write(run_dir / "calls.json", ledger)
    usage_info = {}
    original = client.litellm.completion if client.litellm is not None else None
    if original:
        def observed(*args, **kwargs):
            response = original(*args, **kwargs)
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
        client.litellm.completion = observed
    started = time.monotonic()
    try:
        raw = client.chat_with_images(
            prompt,
            [_package_path(package_root, local_path)],
            system_prompt="You are an independent visual asset evaluator. Output only JSON.",
            model=protocol["models"]["asset_review_model"],
            temperature=0.0,
            max_tokens=protocol["models"]["asset_review_max_tokens"],
            timeout=protocol["models"]["timeout_sec"],
            num_retries=0,
            max_retries=0,
            **({"caching": False} if client.litellm is not None else {}),
        )
        entry.update(status="OK", raw_response=client.redact_response_text(str(raw)), **usage_info)
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(raw).strip(), flags=re.I)
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("asset reviewer response did not contain JSON")
        judgment = json.loads(text[start:end + 1])
        if judgment.get("fit") not in {"MATCH", "PARTIAL", "MISMATCH", "UNCERTAIN"}:
            raise ValueError("asset reviewer fit value is invalid")
        if not str(judgment.get("visible_evidence") or "").strip():
            raise ValueError("asset reviewer omitted visible pixel evidence")
        result = {
            "status": "PROXY_REVIEWED",
            "proposition_id": task["proposition_id"],
            "document_id": task["document_id"],
            "method_id": method_id,
            "decision_action": row["decision"]["action"],
            "acquisition_status": outcome.get("status"),
            "asset_id": candidate["id"],
            "asset_sha256": _sha(_package_path(package_root, local_path)),
            "model_alias": protocol["models"]["asset_review_model"],
            "judgment": judgment,
            "asset_review_model_calls": 1,
            "formal_acceptance": False,
        }
        _write(output_path, result)
        return result
    except Exception as exc:
        entry.update(
            status="FAILED",
            error_type=type(exc).__name__,
            error_message=client.redact_response_text(str(exc))[:800],
            **usage_info,
        )
        result = {
            "status": "FAILED",
            "proposition_id": task["proposition_id"],
            "method_id": method_id,
            "asset_review_model_calls": 1,
            "error_type": type(exc).__name__,
            "error_message": client.redact_response_text(str(exc))[:800],
            "formal_acceptance": False,
        }
        _write(output_path, result)
        return result
    finally:
        entry["elapsed_sec"] = round(time.monotonic() - started, 3)
        _write(run_dir / "calls.json", ledger)
        if original:
            client.litellm.completion = original


def _run_judge(
    *, package_root: Path, run_dir: Path, protocol: dict, task: dict,
    model: str, order: str, ledger: list[dict],
) -> dict:
    output_path = run_dir / "judges" / f"{_safe_id(task['proposition_id'])}-{_safe_id(model)}-{order}.json"
    if output_path.is_file():
        return _json(output_path)
    method_rows = {
        method: _method_row(run_dir, "comparison", method, task["proposition_id"])
        for method in task["methods"]
    }
    if any(not row or row.get("status") != "OK" for row in method_rows.values()):
        result = {
            "status": "SKIPPED_INCOMPLETE_METHOD_OUTPUT",
            "proposition_id": task["proposition_id"],
            "model": model,
            "order": order,
            "planned": True,
            "model_calls": 0,
        }
        _write(output_path, result)
        return result
    claim = _json(_package_path(package_root, task["input_path"]))
    evidence_doc = _json(_package_path(package_root, task["source_evidence_path"]))
    source_unit = next(item for item in evidence_doc["source_units"] if item["id"] in claim["source_refs"])
    source_evidence = [
        {key: source_unit.get(key) for key in ("id", "source_locator", "text", "exact_claim_quote")}
    ]
    options = []
    for method_id in task["methods"]:
        option_id = task["method_to_option"][method_id]
        options.append(
            _blind_option(
                package_root=package_root,
                method_id=method_id,
                option_id=option_id,
                row=method_rows[method_id],
            )
        )
    option_order = task[f"judge_{order}_order"]
    images_labels, image_paths, source_visual_metadata = _judge_images_and_labels(
        package_root, run_dir, options, task
    )
    source_evidence.extend(source_visual_metadata)
    task_key = f"judge:{model}:{order}:{task['proposition_id']}"
    if any(item.get("task_key") == task_key for item in ledger):
        result = {
            "status": "INTERRUPTED_REMOTE_RESULT_UNKNOWN",
            "proposition_id": task["proposition_id"],
            "model": model,
            "order": order,
            "model_calls": 1,
            "retry": "FORBIDDEN_FOR_THIS_RESERVED_TASK",
        }
        _write(output_path, result)
        return result
    prompt_preview = {
        "task": "Judge anonymous method proposals; no method identities or rationale fields included.",
        "proposition_id": task["proposition_id"],
        "options": [
            _blind_option(
                package_root=package_root,
                method_id=task["option_to_method"][option_id],
                option_id=option_id,
                row=method_rows[task["option_to_method"][option_id]],
            )
            for option_id in option_order
        ],
    }
    prompt_hash_seed = json.dumps(prompt_preview, ensure_ascii=False, sort_keys=True)
    call_ids = []
    prompt_holder: dict = {}
    usage_info: dict = {}
    original = client.litellm.completion if client.litellm is not None else None
    if original:
        def observed(*args, **kwargs):
            response = original(*args, **kwargs)
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
        client.litellm.completion = observed

    def make_call(base_fn, stage: str):
        def call(*args, **kwargs):
            if len(ledger) >= protocol["budget"]["max_transport_calls"]:
                raise RuntimeError("RQ1_TRANSPORT_BUDGET_EXHAUSTED")
            prompt = str(args[0])
            call_id = len(ledger) + 1
            prompt_rel = f"prompts/{call_id:03d}-{_safe_id(task_key)}.txt"
            _write_text(run_dir / prompt_rel, prompt)
            attached = []
            if len(args) > 1 and isinstance(args[1], list):
                attached = [{"sha256": _sha(Path(x)), "name": Path(x).name} for x in args[1]]
            entry = {
                "call_id": call_id,
                "task_key": task_key,
                "stage": stage,
                "model_alias": model,
                "provider": "ECNU OpenAI-compatible endpoint",
                "endpoint_host": urlparse(LLM_BASE_URL).hostname,
                "status": "STARTED",
                "reserved_before_transport": True,
                "prompt_path": prompt_rel,
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "images": attached,
                "usage": None,
                "cost_usd": None,
            }
            ledger.append(entry)
            _write(run_dir / "calls.json", ledger)
            call_ids.append(call_id)
            prompt_holder["prompt"] = prompt
            started = time.monotonic()
            try:
                kwargs["model"] = model
                kwargs["temperature"] = 0.0
                kwargs["max_tokens"] = protocol["models"]["judge_max_tokens"]
                kwargs["timeout"] = protocol["models"]["timeout_sec"]
                kwargs["num_retries"] = 0
                kwargs["max_retries"] = 0
                if client.litellm is not None:
                    kwargs["caching"] = False
                raw = base_fn(*args, **kwargs)
                entry.update(status="OK", raw_response=client.redact_response_text(str(raw)), **usage_info)
                return raw
            except Exception as exc:
                entry.update(status="FAILED", error_type=type(exc).__name__,
                             error_message=client.redact_response_text(str(exc))[:800], **usage_info)
                raise
            finally:
                entry["elapsed_sec"] = round(time.monotonic() - started, 3)
                _write(run_dir / "calls.json", ledger)
        return call

    try:
        judgment = judge_rq1_blind_proposals(
            proposition={"id": task["proposition_id"], "text": claim["knowledge_claim"], "source_refs": claim["source_refs"]},
            source_evidence=source_evidence,
            options=options,
            option_order=option_order,
            order=order,
            attached_image_labels=images_labels,
            candidate_images=image_paths,
            model=model,
            text_call=make_call(client.chat_with_system, "blind_proposal_judge"),
            image_call=make_call(client.chat_with_images, "blind_proposal_judge"),
        )
        result = {
            "status": "OK",
            "proposition_id": task["proposition_id"],
            "document_id": task["document_id"],
            "model": model,
            "order": order,
            "option_order": option_order,
            "option_to_method": task["option_to_method"],
            "method_names_sent_to_judge": False,
            "method_rationales_sent_to_judge": False,
            "judgment": judgment,
            "model_calls": len(call_ids),
            "call_ids": call_ids,
            "prompt_sha256": hashlib.sha256(prompt_holder.get("prompt", prompt_hash_seed).encode("utf-8")).hexdigest(),
        }
        _write(output_path, result)
        return result
    except Exception as exc:
        result = {
            "status": "FAILED",
            "proposition_id": task["proposition_id"],
            "document_id": task["document_id"],
            "model": model,
            "order": order,
            "option_order": option_order,
            "option_to_method": task["option_to_method"],
            "method_names_sent_to_judge": False,
            "model_calls": len(call_ids),
            "call_ids": call_ids,
            "error_type": type(exc).__name__,
            "error_message": client.redact_response_text(str(exc))[:900],
        }
        _write(output_path, result)
        return result
    finally:
        if original:
            client.litellm.completion = original
        _write(run_dir / "calls.json", ledger)


def _refresh_report(
    package_root: Path, run_dir: Path, protocol: dict, *, persist: bool = True
) -> dict:
    ledger = _json_calls(run_dir)
    comparisons = protocol["tasks"]
    methods = BASELINE_IDS + METHOD_CONDITIONS
    decision_summary = {}
    by_document = {}
    for method in methods:
        rows = [
            _method_row(run_dir, "comparison", method, task["proposition_id"])
            for task in comparisons
        ]
        rows = [row for row in rows if row]
        actions = Counter(
            row.get("decision", {}).get("action", "NO_DECISION") for row in rows
        )
        statuses = Counter(row.get("status", "UNKNOWN") for row in rows)
        decision_summary[method] = {
            "planned": len(comparisons),
            "returned": sum(row.get("status") == "OK" for row in rows),
            "failed_or_missing": len(comparisons) - sum(row.get("status") == "OK" for row in rows),
            "action_counts_in_returned_rows": dict(actions),
            "status_counts": dict(statuses),
            "abstentions": sum(bool(row.get("decision", {}).get("abstain")) for row in rows),
            "uncertain": sum(bool(row.get("decision", {}).get("uncertain")) for row in rows),
        }
    for doc_id in sorted({task["document_id"] for task in comparisons}):
        doc_tasks = [task for task in comparisons if task["document_id"] == doc_id]
        by_document[doc_id] = {
            method: {
                "planned": len(doc_tasks),
                "returned": sum(
                    bool((row := _method_row(run_dir, "comparison", method, task["proposition_id"]))
                         and row.get("status") == "OK")
                    for task in doc_tasks
                ),
                "action_counts": dict(Counter(
                    (row.get("decision") or {}).get("action", "NO_DECISION")
                    for task in doc_tasks
                    if (row := _method_row(run_dir, "comparison", method, task["proposition_id"]))
                )),
            }
            for method in methods
        }
    judge_rows = []
    for path in sorted((run_dir / "judges").glob("*.json")) if (run_dir / "judges").exists() else []:
        judge_rows.append(_json(path))
    valid_judgments = [row for row in judge_rows if row.get("status") == "OK"]
    judge_summary = summarize_blind_proposal_comparison(
        tasks=comparisons,
        judgments=valid_judgments,
        judge_models=protocol["models"]["judge_models"],
    )
    asset_reviews = []
    for path in sorted((run_dir / "asset_reviews").glob("*.json")) if (run_dir / "asset_reviews").exists() else []:
        asset_reviews.append(_json(path))
    asset_counts = Counter(row.get("status", "UNKNOWN") for row in asset_reviews)
    calls_by_stage = Counter(row.get("stage", "unknown") for row in ledger)
    call_statuses = Counter(row.get("status", "unknown") for row in ledger)
    total_tokens = Counter()
    for call in ledger:
        usage = call.get("usage") or {}
        if isinstance(usage, dict):
            for key in ("prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens"):
                value = usage.get(key)
                if isinstance(value, (int, float)):
                    total_tokens[key] += int(value)
    costs = [call["cost_usd"] for call in ledger if isinstance(call.get("cost_usd"), (int, float))]
    duration_values = [call["elapsed_sec"] for call in ledger if isinstance(call.get("elapsed_sec"), (int, float))]
    completed_calls = sum(call.get("status") in {"OK", "FAILED"} for call in ledger)
    report = {
        "dataset_id": protocol["dataset_id"],
        "run_id": protocol["run_id"],
        "protocol_sha256": _sha(run_dir / "protocol.json"),
        "code_branch": protocol["git"]["branch"],
        "code_head": protocol["git"]["head"],
        "result_contains_uncommitted_code": True,
        "updated_at_utc": datetime.now(UTC).isoformat(),
        "scope": "DEVELOPMENT_ONLY_NOT_FORMAL_EXPERIMENT",
        "input_summary": {
            "independent_documents": len({doc["document_id"] for doc in _json(package_root / "dataset/documents.json")["documents"]}),
            "planned_development_propositions": len(protocol["planned_development_tasks"]),
            "planned_comparison_propositions": len(comparisons),
            "comparison_documents": sorted({task["document_id"] for task in comparisons}),
            "all_propositions_verbatim": True,
            "source_refs_and_literal_quotes_verified": True,
            "semantic_support_boundary": "Verbatim match proxy only; no independent entailment gold.",
            "local_pdf_binary_equal_to_noaa_archive": {
                doc["document_id"]: doc["archive_binary_equal"]
                for doc in _json(package_root / "dataset/documents.json")["documents"]
            },
        },
        "development_results": {
            "planned_method_calls": sum(len(item["conditions"]) for item in protocol["planned_development_tasks"]),
            "returned": sum(
                bool((row := _method_row(run_dir, "development", condition, item["proposition_id"]))
                     and row.get("status") == "OK")
                for item in protocol["planned_development_tasks"]
                for condition in item["conditions"]
            ),
            "no_holdout_or_locked_test_claim": True,
        },
        "comparison": {
            "planned_propositions_fixed_denominator": len(comparisons),
            "by_document": by_document,
            "methods": decision_summary,
        },
        "blind_judges": judge_summary,
        "asset_proxy_reviews": {
            "planned_pairs_upper_bound": len(comparisons) * len(protocol["tasks"][0]["asset_review_conditions"]),
            "records": len(asset_reviews),
            "status_counts": dict(asset_counts),
            "formal_accepts": 0,
            "judgments": asset_reviews,
        },
        "filtered_or_unavailable": {
            "missing_method_outputs": sum(item["failed_or_missing"] for item in decision_summary.values()),
            "judge_skipped_incomplete": sum(row.get("status") == "SKIPPED_INCOMPLETE_METHOD_OUTPUT" for row in judge_rows),
            "judge_failed_or_interrupted": sum(row.get("status") not in {"OK", "SKIPPED_INCOMPLETE_METHOD_OUTPUT"} for row in judge_rows),
            "acquisition_outcomes": {
                method: dict(Counter(
                    _asset_status(row.get("acquisition") or {}).get("status", "NO_ACQUISITION")
                    for task in comparisons
                    if (row := _method_row(run_dir, "comparison", method, task["proposition_id"]))
                ))
                for method in methods
            },
        },
        "calls": {
            "transport_attempts_reserved": len(ledger),
            "hard_budget": protocol["budget"]["max_transport_calls"],
            "statuses": dict(call_statuses),
            "by_stage": dict(calls_by_stage),
            "completed_or_failed": completed_calls,
            "usage_tokens": dict(total_tokens),
            "elapsed_call_seconds_sum": round(sum(duration_values), 3) if duration_values else None,
            "cost_usd_sum": round(sum(costs), 8) if len(costs) == len(ledger) and costs else None,
            "cost_usd_known_calls": len(costs),
            "cost_is_null_when_unknown": True,
            "image_generation": 0,
            "tts": 0,
            "video_recording": 0,
            "health_check": 0,
        },
        "claims_supported": [
            "The new split contains three independent public instructional documents, including non-blockchain biology and ocean-science lessons.",
            "All selected claims are verbatim with deterministic source reference and local text/hash checks.",
            "Direct LLM, proposed decision, configured ablations, and three deterministic baselines are compared on the fixed 12-claim denominator where outputs exist.",
            "Judges provide proxy preferences and axis scores; no human truth or learning effect is established.",
        ],
        "claims_not_supported": [
            "No claim of human accuracy, semantic entailment truth, learner comprehension, or teaching effectiveness.",
            "No claim that a generated image exists; image generation was not run.",
            "No claim of formal pilot, validation, locked-test, or RQ2 completion.",
            "Distinct ECNU aliases do not prove independent model families or versions.",
        ],
    }
    if persist:
        _write(run_dir / "report.json", report)
    return report


def _recover_unknown_calls(run_dir: Path, protocol: dict, ledger: list[dict]) -> None:
    """Persist unknown interrupted transfers as unresolved rows and never resend."""
    for entry in ledger:
        if entry.get("status") != "STARTED":
            continue
        task_key = entry.get("task_key", "")
        parts = task_key.split(":")
        if parts[0] == "decision" and len(parts) == 4:
            _, split, condition, proposition_id = parts
            task = next(
                (item for item in (protocol["planned_development_tasks"] if split == "development" else protocol["tasks"])
                 if item["proposition_id"] == proposition_id),
                {"proposition_id": proposition_id, "document_id": "unknown"},
            )
            _record_unavailable_task(run_dir, split, condition, task, "The remote result was unknown after interruption; this reserved request will not be resent.")
        elif parts[0] == "judge" and len(parts) == 4:
            _, model, order, proposition_id = parts
            path = run_dir / "judges" / f"{_safe_id(proposition_id)}-{_safe_id(model)}-{order}.json"
            if not path.exists():
                _write(path, {
                    "status": "INTERRUPTED_REMOTE_RESULT_UNKNOWN",
                    "proposition_id": proposition_id,
                    "model": model,
                    "order": order,
                    "model_calls": 1,
                    "retry": "FORBIDDEN_FOR_THIS_RESERVED_TASK",
                })
        elif parts[0] == "asset_review" and len(parts) == 3:
            _, method_id, proposition_id = parts
            path = run_dir / "asset_reviews" / f"{_safe_id(method_id)}-{_safe_id(proposition_id)}.json"
            if not path.exists():
                _write(path, {
                    "status": "INTERRUPTED_REMOTE_RESULT_UNKNOWN",
                    "method_id": method_id,
                    "proposition_id": proposition_id,
                    "asset_review_model_calls": 1,
                    "formal_acceptance": False,
                    "retry": "FORBIDDEN_FOR_THIS_RESERVED_TASK",
                })
        entry["status"] = "INTERRUPTED_REMOTE_RESULT_UNKNOWN"
        entry["error_message"] = "Process interruption after pre-transport budget reservation; request outcome cannot be recovered."
    _write(run_dir / "calls.json", ledger)


def _run_all(package_root: Path, run_dir: Path, *, resume: bool) -> dict:
    package_root = package_root.resolve()
    run_dir = run_dir.resolve()
    protocol = _json(_protocol_path(run_dir))
    _verify_protocol_and_claims(package_root, protocol)
    if not LLM_API_KEY or not LLM_BASE_URL:
        raise RuntimeError("RQ1 model credentials or endpoint are unavailable; no transport was attempted")
    if protocol["budget"]["max_transport_calls"] != 160:
        raise ValueError("frozen RQ1 call budget changed; prepare a new run")
    lock = run_dir / "run.lock"
    try:
        with lock.open("x", encoding="utf-8") as stream:
            stream.write(str(os.getpid()))
    except FileExistsError as exc:
        raise RuntimeError(f"run is locked by another process or stale lock: {lock}") from exc
    try:
        ledger = _json_calls(run_dir)
        _recover_unknown_calls(run_dir, protocol, ledger)
        ledger = _json_calls(run_dir)
        # Development documents are isolated from the frozen comparison set.
        for task in protocol["planned_development_tasks"]:
            for condition in task["conditions"]:
                current = _method_row(run_dir, "development", condition, task["proposition_id"])
                task_key = f"decision:development:{condition}:{task['proposition_id']}"
                if current or any(call.get("task_key") == task_key for call in ledger):
                    continue
                try:
                    _run_method_call(
                        package_root=package_root,
                        run_dir=run_dir,
                        protocol=protocol,
                        task=task,
                        condition=condition,
                        split="development",
                        ledger=ledger,
                        max_tokens=protocol["models"]["method_max_tokens"],
                    )
                finally:
                    _refresh_report(package_root, run_dir, protocol)
        # Baselines and their local acquisitions are deterministic and offline.
        for task in protocol["tasks"]:
            for method in BASELINE_IDS:
                if _method_row(run_dir, "comparison", method, task["proposition_id"]):
                    continue
                _make_baseline(package_root=package_root, run_dir=run_dir, task=task, method_id=method)
            _refresh_report(package_root, run_dir, protocol)
        # Proposed and four real mechanism ablations, plus the direct decision model.
        for task in protocol["tasks"]:
            for condition in METHOD_CONDITIONS:
                existing = _method_row(run_dir, "comparison", condition, task["proposition_id"])
                task_key = f"decision:comparison:{condition}:{task['proposition_id']}"
                if existing or any(call.get("task_key") == task_key for call in ledger):
                    if not existing and any(call.get("task_key") == task_key for call in ledger):
                        _record_unavailable_task(
                            run_dir, "comparison", condition, task,
                            "A prior request was reserved without a recoverable completed result; not resent.",
                        )
                    continue
                try:
                    _run_method_call(
                        package_root=package_root,
                        run_dir=run_dir,
                        protocol=protocol,
                        task=task,
                        condition=condition,
                        split="comparison",
                        ledger=ledger,
                        max_tokens=protocol["models"]["method_max_tokens"],
                    )
                finally:
                    _refresh_report(package_root, run_dir, protocol)
        _refresh_report(package_root, run_dir, protocol)
        # Two aliases, forward/reverse order. Failures and missing method outputs
        # remain planned rows; incomplete samples are not silently dropped.
        for task in protocol["tasks"]:
            for model in protocol["models"]["judge_models"]:
                for order in ("forward", "reverse"):
                    task_key = f"judge:{model}:{order}:{task['proposition_id']}"
                    if any(call.get("task_key") == task_key for call in ledger):
                        path = run_dir / "judges" / f"{_safe_id(task['proposition_id'])}-{_safe_id(model)}-{order}.json"
                        if not path.exists():
                            _write(path, {
                                "status": "INTERRUPTED_REMOTE_RESULT_UNKNOWN",
                                "proposition_id": task["proposition_id"], "model": model,
                                "order": order, "model_calls": 1,
                                "retry": "FORBIDDEN_FOR_THIS_RESERVED_TASK",
                            })
                        continue
                    if (run_dir / "judges" / f"{_safe_id(task['proposition_id'])}-{_safe_id(model)}-{order}.json").exists():
                        continue
                    _run_judge(
                        package_root=package_root,
                        run_dir=run_dir,
                        protocol=protocol,
                        task=task,
                        model=model,
                        order=order,
                        ledger=ledger,
                    )
                    _refresh_report(package_root, run_dir, protocol)
        _refresh_report(package_root, run_dir, protocol)
        # Every comparison proposition is preassigned both Proposed and
        # Always-Retrieve asset outcomes. Calls are made only when a file exists.
        for task in protocol["tasks"]:
            for method in task["asset_review_conditions"]:
                row = _method_row(run_dir, "comparison", method, task["proposition_id"])
                if not row or row.get("status") != "OK":
                    status_path = run_dir / "asset_reviews" / f"{_safe_id(method)}-{_safe_id(task['proposition_id'])}.json"
                    if not status_path.exists():
                        _write(status_path, {
                            "status": "NOT_APPLICABLE_METHOD_OUTPUT_UNAVAILABLE",
                            "proposition_id": task["proposition_id"],
                            "method_id": method,
                            "asset_review_model_calls": 0,
                            "formal_acceptance": False,
                        })
                    continue
                _run_asset_review(
                    package_root=package_root,
                    run_dir=run_dir,
                    protocol=protocol,
                    task=task,
                    method_id=method,
                    row=row,
                    ledger=ledger,
                )
                _refresh_report(package_root, run_dir, protocol)
        report = _refresh_report(package_root, run_dir, protocol)
        if len(ledger) > protocol["budget"]["max_transport_calls"]:
            raise AssertionError("frozen transport budget exceeded")
        _write(run_dir / "output_manifest.json", _build_output_manifest(run_dir, protocol))
        return report
    finally:
        if lock.exists():
            lock.unlink()


def analyze_only(run_dir: Path, output_path: Path) -> dict:
    run_dir = run_dir.resolve()
    package_root = (run_dir / "..").resolve()
    protocol = _json(_protocol_path(run_dir))
    _verify_protocol_and_claims(package_root, protocol)
    saved_report = _json(run_dir / "report.json")
    if saved_report.get("protocol_sha256") != _sha(run_dir / "protocol.json"):
        raise ValueError("saved report/protocol mismatch; refusing relocation analysis")
    _verify_output_manifest(run_dir, protocol)
    report = _refresh_report(package_root, run_dir, protocol, persist=False)
    output_path = output_path.resolve()
    if output_path.exists() and output_path != run_dir / "report.json":
        raise FileExistsError(f"analysis output already exists: {output_path}")
    analysis = {
        "status": "ANALYZED_FROM_SAVED_RUN_NO_MODEL_CALLS",
        "run_id": protocol["run_id"],
        "protocol_sha256": _sha(run_dir / "protocol.json"),
        "model_calls_before": len(_json_calls(run_dir)),
        "model_calls_after": len(_json_calls(run_dir)),
        "new_model_calls": 0,
        "report": report,
        "analysis_implementation_sha256": _sha(ROOT / "scripts/run_rq1_new_corpus.py"),
    }
    _write(output_path, analysis)
    return analysis


def _show(result: dict) -> None:
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "execute", "resume", "verify"):
        item = sub.add_parser(command)
        item.add_argument("--package-root", type=Path, default=DEFAULT_PACKAGE_ROOT)
        if command in {"execute", "resume", "verify"}:
            item.add_argument("--run-dir", type=Path)
    analyze = sub.add_parser("analyze-only")
    analyze.add_argument("--run-dir", type=Path, required=True)
    analyze.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        _show({"run_dir": str(prepare(args.package_root))})
    elif args.command in {"execute", "resume"}:
        run_dir = args.run_dir or (args.package_root / RUN_REL)
        if args.command == "execute" and _json_calls(run_dir):
            raise SystemExit("run already has reserved calls; use resume to continue")
        _show(_run_all(args.package_root, run_dir, resume=args.command == "resume"))
    elif args.command == "verify":
        _show(verify(args.package_root, run_dir=args.run_dir))
    else:
        _show(analyze_only(args.run_dir, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
