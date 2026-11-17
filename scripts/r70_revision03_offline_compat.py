"""Explicit offline conversion for the archived r70 revision-03 response.

This utility is intentionally not imported by the live visual-generation path.
It writes a separate evidence bundle and never edits the archived source file.
"""

import argparse
import hashlib
import json
from pathlib import Path

PLAN_VERSION = "visual-plan-v1"
CONVERTER_ID = "r70-revision03-offline-compat-v1"
EXPECTED_KEYS = {"visuals", "content_map", "parent", "reason"}


def convert_r70_revision03_response(raw_bytes: bytes, source_path: str) -> dict:
    """Convert only the archived bare revision-03 shape, retaining both forms."""
    raw_text = raw_bytes.decode("utf-8")
    try:
        legacy = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"r70 revision-03 response is not valid JSON: {exc.msg}") from exc

    if not isinstance(legacy, dict) or set(legacy) != EXPECTED_KEYS:
        raise ValueError("response does not match the archived r70 revision-03 shape")
    parent = legacy["parent"]
    reason = legacy["reason"]
    if (not isinstance(parent, str)
            or not parent.replace("\\", "/").rstrip("/").endswith("/revision-01")
            or not isinstance(reason, str) or not reason.strip()
            or not isinstance(legacy["visuals"], list)
            or not isinstance(legacy["content_map"], dict)):
        raise ValueError("response does not match the archived r70 revision-03 shape")

    converted = {
        "plan_version": PLAN_VERSION,
        "visuals": legacy["visuals"],
        "content_map": legacy["content_map"],
    }
    converted_text = json.dumps(converted, ensure_ascii=False, indent=2)
    return {
        "source_path": source_path,
        "source_response": raw_text,
        "converted_response": converted_text,
        "conversion_record": {
            "converter": CONVERTER_ID,
            "source_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "converted_sha256": hashlib.sha256(
                converted_text.encode("utf-8")
            ).hexdigest(),
            "removed_fields": ["parent", "reason"],
            "added_fields": {"plan_version": PLAN_VERSION},
            "note": "Offline protocol normalization only; semantic content was not changed.",
        },
    }


def write_conversion_bundle(input_path: Path, output_path: Path) -> dict:
    """Write a new bundle; refuse in-place conversion and overwriting evidence."""
    source = input_path.resolve(strict=True)
    target = output_path.resolve(strict=False)
    if source == target:
        raise ValueError("input and output must be different files")
    bundle = convert_r70_revision03_response(source.read_bytes(), str(source))
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(bundle, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return bundle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Archived revision-03 response")
    parser.add_argument("--output", required=True, type=Path, help="New evidence bundle path")
    args = parser.parse_args()
    bundle = write_conversion_bundle(args.input, args.output)
    record = bundle["conversion_record"]
    print(f"wrote {args.output}")
    print(f"source_sha256={record['source_sha256']}")
    print(f"converted_sha256={record['converted_sha256']}")


if __name__ == "__main__":
    main()
