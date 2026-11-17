"""Re-render saved specifications under the production shell, without any API call.

This is diagnostic evidence, not a new accepted model revision or video run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path

from textbook2video.research.visual_tools import dispatch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--revision", type=Path)
    inputs.add_argument(
        "--cases", type=Path, help="Explicit development fixtures, not model output"
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    if args.revision:
        request = json.loads((args.revision / "request.json").read_text(encoding="utf-8"))
        source = json.loads((args.revision / "source.json").read_text(encoding="utf-8"))
        cases = [{"id": "saved-content", "request": request, "source": source["source_text"]}]
        provenance = args.revision / "request.json"
    else:
        cases = []
        provenance = args.cases
        for case in json.loads(args.cases.read_text(encoding="utf-8")):
            cases.append(
                {
                    "id": case["id"],
                    "source": case["source"],
                    "request": {
                        "arguments": {
                            "visuals": [case["visual"]],
                            "page_plan": {
                                "support_element_ids": [],
                                "replaces_element_ids": [],
                                "coverage": [],
                                "reason": "Explicit development fixture, not model output",
                            },
                        },
                        "page_context": [],
                        "narration_text": case["source"],
                    },
                }
            )
    args.output_dir.mkdir(parents=True, exist_ok=False)
    records = []
    try:
        for case in cases:
            request = case["request"]
            for theme in ("dark-blue-academic", "bright", "3b1b-math"):
                arguments = deepcopy(request["arguments"])
                arguments.pop("parent", None)
                arguments["reason"] = "DIAGNOSTIC_RENDER_ONLY: existing content, new layout"
                folder = (
                    args.output_dir / case["id"] / theme if args.cases else args.output_dir / theme
                )
                result = dispatch(
                    "create",
                    arguments,
                    source=case["source"],
                    output_dir=folder,
                    theme=theme,
                    page_context=request.get("page_context"),
                    narration_text=request.get("narration_text"),
                )
                record = json.loads(result.read_text(encoding="utf-8"))
                records.append(
                    {
                        "case": case["id"],
                        "theme": theme,
                        "revision": str(result),
                        "geometry": record["geometry"],
                    }
                )
    finally:
        manifest = {
            "status": "DIAGNOSTIC_RENDER_ONLY_PENDING_VISUAL_REVIEW",
            "input_path": str(provenance.resolve()),
            "input_request_sha256": hashlib.sha256(provenance.read_bytes()).hexdigest(),
            "model_calls": 0,
            "human_review": "NOT_REVIEWED",
            "records": records,
        }
        with (args.output_dir / "manifest.json").open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"themes": len(records), "output": str(args.output_dir)}))


if __name__ == "__main__":
    main()
