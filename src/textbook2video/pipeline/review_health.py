"""Bounded image-understanding probe, before any course page is changed."""

from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path

from textbook2video.llm.client import chat_with_images, redact_response_text


class ReviewServiceUnavailable(RuntimeError):
    """Common reviewer failure: stop the batch rather than page-level fallback."""


def check_review_health(output_dir: Path, *, model: str, timeout: float = 30) -> Path:
    output_dir.mkdir(parents=True, exist_ok=False)
    image = output_dir / "probe.png"

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data)))

    # A blue square on white; independent of browser, fonts and external assets.
    rows = bytearray()
    for y in range(64):
        rows.append(0)
        for x in range(64):
            rows.extend((0, 0, 255) if 16 <= x < 48 and 16 <= y < 48 else (255, 255, 255))
    image.write_bytes(
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 64, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")
    )
    result = {"model": model, "status": "UNAVAILABLE", "scope": "synthetic-image-health-only"}
    stage = "request"
    try:
        response = chat_with_images(
            'Describe the central object. Return only JSON with English keys "shape" and "color".',
            [image], model=model, temperature=0, max_tokens=100, timeout=timeout,
            extra_body={"response_format": {"type": "json_object"}},
        )
        stage = "response_parse"
        result["response_type"] = type(response).__name__
        if not isinstance(response, str):
            raise ValueError("health response must be text")
        saved = redact_response_text(response)
        with (output_dir / "response.txt").open("x", encoding="utf-8", newline="") as stream:
            stream.write(saved)
        result.update(
            response_file="response.txt",
            response_sha256=hashlib.sha256(response.encode("utf-8")).hexdigest(),
            saved_response_sha256=hashlib.sha256(saved.encode("utf-8")).hexdigest(),
            response_redacted=saved != response,
        )
        value = json.loads(response)
        stage = "response_schema"
        if not isinstance(value, dict) or any(
            not isinstance(value.get(key), str) for key in ("shape", "color")
        ):
            raise ValueError("health response needs string shape and color")
        stage = "image_understanding"
        if value["shape"].lower() != "square" or value["color"].lower() != "blue":
            raise ValueError("image understanding probe failed")
        result["status"] = "AVAILABLE"
    except Exception as error:
        # Do not persist provider exception text: it may contain credentials/URLs.
        result["error_type"] = type(error).__name__
        result["error_stage"] = stage
        if isinstance(error, json.JSONDecodeError):
            result["parse_error"] = {
                "position": error.pos, "line": error.lineno, "column": error.colno,
                "message": error.msg,
            }
        (output_dir / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        raise ReviewServiceUnavailable(
            f"Review service health check failed ({type(error).__name__}); "
            "enhancement batch stopped. "
            f"Evidence: {output_dir / 'result.json'}"
        ) from None
    path = output_dir / "result.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return path
