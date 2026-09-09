"""Isolated batch runner for the optional CosyVoice TTS backend."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import torch
import torchaudio


def _prefer_cached_wetext() -> None:
    """Keep wetext from checking ModelScope on every offline cloud run."""
    cache = Path(
        os.getenv(
            "T2V_WETEXT_MODEL_DIR",
            "/ai/data/model-cache/modelscope/hub/pengzhendong/wetext",
        )
    )
    if not cache.is_dir():
        return
    import modelscope

    modelscope.snapshot_download = lambda *_args, **_kwargs: str(cache)


_prefer_cached_wetext()

from cosyvoice.cli.cosyvoice import AutoModel  # noqa: E402


def _speed(rate: str) -> float:
    value = (rate or "0%").strip()
    if value.endswith("%"):
        try:
            return max(0.5, min(2.0, 1.0 + float(value[:-1]) / 100.0))
        except ValueError:
            pass
    return 1.0


def main() -> None:
    request = json.load(sys.stdin)
    output_dir = Path(request["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    model = AutoModel(model_dir=request["model_dir"], fp16=torch.cuda.is_available())
    speed = _speed(request.get("rate", "+0%"))

    for index, text in enumerate(request["segments"], start=1):
        chunks = [
            item["tts_speech"]
            for item in model.inference_zero_shot(
                text,
                request["prompt_text"],
                request["prompt_wav"],
                stream=False,
                speed=speed,
            )
        ]
        if not chunks:
            print(f"CosyVoice returned no audio for segment {index}", file=sys.stderr)
            continue
        audio = chunks[0] if len(chunks) == 1 else torch.cat(chunks, dim=1)
        output = output_dir / f"s{index}.wav"
        torchaudio.save(str(output), audio.cpu(), model.sample_rate)
        print(f"OK: {output.name} ({output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
