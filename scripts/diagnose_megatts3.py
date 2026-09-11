""" 단계-by-stage MegaTTS3 diagnostic for the GPU environment.

This script is intended for the cloud host only.  It loads one model, checks
prompt preprocessing, then generates one short sentence and writes one WAV.
It does not run the textbook pipeline or modify any repository files.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


def log(message: str) -> None:
    print(f"[diagnose-megatts3] {message}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        default=os.getenv("T2V_MEGATTS3_ROOT", "/ai/data/repos/PresentAgent/presentagent/MegaTTS3"),
    )
    parser.add_argument("--python-device", default=os.getenv("T2V_MEGATTS3_DEVICE", "cuda"))
    parser.add_argument(
        "--output", default="/ai/data/textbook-to-video/smoke/megatts3-diagnostic.wav"
    )
    parser.add_argument("--text", default="这是一个单句模型诊断测试。")
    args = parser.parse_args()

    root = Path(args.root)
    prompt_wav = root / "assets" / "Chinese_prompt.wav"
    prompt_latent = root / "assets" / "Chinese_prompt.npy"
    if not prompt_wav.exists() or not prompt_latent.exists():
        raise FileNotFoundError(f"prompt assets missing: {prompt_wav} / {prompt_latent}")

    sys.path.insert(0, str(root))
    from tts.infer_cli import MegaTTS3DiTInfer
    from tts.utils.audio_utils.io import save_wav

    started = time.monotonic()
    log(f"root={root}")
    log(f"device={args.python_device}")
    log("stage=init")
    infer = MegaTTS3DiTInfer(
        ckpt_root=str(root / "checkpoints"),
        device=args.python_device,
    )
    log(f"stage=init_done elapsed={time.monotonic() - started:.1f}s")

    log("stage=preprocess")
    prompt_audio = prompt_wav.read_bytes()
    context = infer.preprocess(prompt_audio, latent_file=str(prompt_latent))
    log(f"stage=preprocess_done keys={sorted(context)} elapsed={time.monotonic() - started:.1f}s")

    log("stage=forward")
    wav_bytes = infer.forward(context, args.text, time_step=24, p_w=2.0, t_w=2.5)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    save_wav(wav_bytes, str(output))
    result = {
        "status": "ok",
        "output": str(output),
        "bytes": output.stat().st_size,
        "elapsed_sec": round(time.monotonic() - started, 1),
    }
    log(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
