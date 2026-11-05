"""Two-request source-role quote diagnostic; no judge, audio or recording."""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

import run_rq2_auto_binding_video as auto

ROOT = Path(__file__).resolve().parents[1]


def prepare(source, out):
    import pymupdf

    if out.exists():
        raise FileExistsError(out)
    if auto.sha(source) != "dbbb939fe2a167419b60aa8dc4326c8439b531684ecd6b7e91d150e807d4ba3e":
        raise ValueError("Source hash mismatch")
    with pymupdf.open(source) as pdf:
        raw = pdf[4].get_text()
    text = re.sub(r"\s+", " ", re.sub(r"(?<=\w)-\n(?=\w)", "", raw))
    context = (
        text.split("3.5. Residual Encoder and Decoder Network", 1)[1]
        .split("3.6. Training Strategy", 1)[0]
        .strip()
    )
    first, rest = context.split("In this paper,", 1)
    claims = [first.strip(), ("In this paper," + rest.split("Compared with", 1)[0]).strip()]
    exposure = {}
    for claim in claims:
        hits = []
        for base in (ROOT / ".local/rq1", ROOT / ".local/rq2"):
            for path in base.rglob("*.txt"):
                if "prompts" in path.parts and claim in re.sub(
                    r"\s+", " ", path.read_text(encoding="utf-8", errors="replace")
                ):
                    hits.append(str(path.relative_to(ROOT)))
        exposure[claim] = hits
    if any(exposure.values()):
        raise ValueError(f"Selected claim already occurs in saved request: {exposure}")
    candidates = [
        {
            "id": key,
            "segment_id": "residual",
            "text": label,
            "source_refs": [f"object-label-{key}"],
            "source_locator": "DVC page5 section3.5",
        }
        for key, label in (
            ("c17", "predicted frame"),
            ("c04", "residual encoder network"),
            ("c29", "original frame"),
        )
    ]
    if any(c["text"] not in context for c in candidates):
        raise ValueError("Candidate label absent from source")
    out.mkdir(parents=True)
    shutil.copy2(source, out / "source.pdf")
    auto.write(out / "source.json", {"raw_page": raw, "source_context": context})
    auto.write(
        out / "exposure_audit.json",
        {
            "saved_request_literal_search": exposure,
            "limitation": "New local target/context search; "
            "exposed document, not independent holdout.",
        },
    )
    auto.write(
        out / "tasks.json",
        [
            {
                "id": f"residual-{i}",
                "segment_id": "residual",
                "text": claim,
                "source_refs": [f"sentence-{i}"],
                "source_context": context,
            }
            for i, claim in enumerate(claims, 1)
        ],
    )
    auto.write(out / "candidates.json", candidates)
    config = {
        "models": {"method": "ecnu-plus", "temperature": 0, "timeout_sec": 120},
        "budget": {"max_transport_calls": 2, "max_total_tokens": 20000, "automatic_retries": 0},
    }
    auto.write(out / "config.json", config)
    auto.write(out / "protocol.json", config)
    for src in (
        Path(__file__),
        ROOT / "src/textbook2video/research/binding_methods.py",
        ROOT / "scripts/run_rq2_auto_binding_video.py",
        ROOT / "scripts/run_rq1_doc2present_v2.py",
    ):
        shutil.copy2(src, out / src.name)
    auto.write(
        out / "input_manifest.json", {p.name: auto.sha(p) for p in out.iterdir() if p.is_file()}
    )


def execute(out):
    auto.verify_inputs(out)
    if auto.sha(ROOT / "src/textbook2video/research/binding_methods.py") != auto.sha(
        out / "binding_methods.py"
    ):
        raise ValueError("Binding code changed after freeze")
    run = out / "run"
    if run.exists():
        raise FileExistsError("No repeat or resume")
    run.mkdir()
    results = []
    for prop in auto.read(out / "tasks.json"):
        try:
            result = auto.binding.bind_source_conditioned(
                prop,
                auto.read(out / "candidates.json"),
                threshold=0.45,
                context_model_fn=lambda prompt: auto.call(
                    out, prop["id"], "binding", prompt, 2600, "ecnu-plus"
                ),
            )
        except Exception as exc:
            result = {
                "proposition_id": prop["id"],
                "status": "INVALID_RESPONSE",
                "selected_candidate_id": None,
                "error": auto.shared.client.redact_response_text(str(exc)),
            }
            auto.write(run / f"{prop['id']}.json", result)
            ledger = auto.read(run / "calls.json") if (run / "calls.json").exists() else []
            if not ledger or any(c["status"] != "OK" for c in ledger):
                raise
            if "BUDGET" in str(exc) or "usage" in str(exc):
                raise
        results.append(result)
        auto.write(run / "results.json", results)
    auto.verify_inputs(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "execute"])
    parser.add_argument("--source-pdf", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        if args.source_pdf is None:
            parser.error("prepare requires --source-pdf")
        prepare(args.source_pdf, args.output.resolve())
    else:
        execute(args.output.resolve())
