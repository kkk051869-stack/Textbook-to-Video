"""Isolated batch runner for the optional MegaTTS3 TTS backend."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path


def _log(message: str) -> None:
    print(f"[megatts3] {message}", file=sys.stderr, flush=True)


def main() -> None:
    request = json.load(sys.stdin)
    megatts3_root = Path(request["megatts3_root"])
    sys.path.insert(0, str(megatts3_root))

    from tts.infer_cli import MegaTTS3DiTInfer
    from tts.utils.audio_utils.io import save_wav

    output_dir = Path(request["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    prompt_wav = Path(request["prompt_wav"])
    prompt_latent = Path(request.get("prompt_latent") or prompt_wav.with_suffix(".npy"))
    with prompt_wav.open("rb") as file:
        prompt_audio = file.read()

    _log("initializing model")
    infer = MegaTTS3DiTInfer(
        ckpt_root=str(megatts3_root / "checkpoints"),
        device=request.get("device") or None,
    )
    _log(f"model initialized on {infer.device}")
    _log("preprocessing prompt")
    resource_context = infer.preprocess(prompt_audio, latent_file=str(prompt_latent))
    _log("prompt preprocessed")

    time_step = int(request.get("time_step", 24))
    p_w = float(request.get("p_w", 2.0))
    t_w = float(request.get("t_w", 2.5))

    for index, text in enumerate(request["segments"], start=1):
        spoken = text.strip() or "本段暂无旁白。"
        _log(f"forward sentence {index}/{len(request['segments'])}")
        wav_bytes = infer.forward(
            resource_context,
            spoken,
            time_step=time_step,
            p_w=p_w,
            t_w=t_w,
        )
        output = output_dir / f"s{index}.wav"
        save_wav(wav_bytes, str(output))
        _log(f"saved {output.name}")
        print(f"OK: {output.name} ({output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
