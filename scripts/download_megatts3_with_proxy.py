#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path

import requests


FILES = [
    (".gitattributes", 1574),
    ("README.md", 7635),
    ("aligner_lm/config.yaml", 2335),
    ("aligner_lm/model_only_last.ckpt", 218434266),
    ("config.json", 68),
    ("diffusion_transformer/config.yaml", 2301),
    ("diffusion_transformer/model_only_last.ckpt", 1836341777),
    ("duration_lm/config.yaml", 2720),
    ("duration_lm/model_only_last.ckpt", 267955084),
    ("g2p/added_tokens.json", 573857),
    ("g2p/config.json", 757),
    ("g2p/generation_config.json", 117),
    ("g2p/latest", 16),
    ("g2p/merges.txt", 1671853),
    ("g2p/model.safetensors", 1018490136),
    ("g2p/special_tokens_map.json", 616),
    ("g2p/tokenizer.json", 14796960),
    ("g2p/tokenizer_config.json", 3210300),
    ("g2p/trainer_state.json", 789603),
    ("g2p/vocab.json", 2776833),
    ("wavvae/config.yaml", 3566),
    ("wavvae/decoder.ckpt", 904541298),
]


def file_size(path: Path) -> int:
    return path.stat().st_size if path.exists() else -1


def download_small(url: str, target: Path, expected_size: int, proxy: str | None) -> None:
    if file_size(target) == expected_size:
        print(f"OK {target} ({expected_size} bytes)")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    proxies = {"http": proxy, "https": proxy} if proxy else None
    tmp = target.with_suffix(target.suffix + ".tmp")
    with requests.get(url, proxies=proxies, timeout=(30, 300), stream=True, allow_redirects=True) as response:
        response.raise_for_status()
        with tmp.open("wb") as handle:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    handle.write(chunk)
    if file_size(tmp) != expected_size:
        raise RuntimeError(f"{target} expected {expected_size}, got {file_size(tmp)}")
    tmp.replace(target)
    print(f"OK {target} ({expected_size} bytes)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="PresentAgent-MegaTTS3-checkpoints")
    parser.add_argument("--base-url", default="https://huggingface.co/ByteDance/MegaTTS3/resolve/main")
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--connections", type=int, default=4)
    parser.add_argument("--chunk-size-mb", type=int, default=8)
    parser.add_argument("--parallel-threshold-mb", type=int, default=32)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    for rel, expected_size in FILES:
        target = output_dir / rel
        if file_size(target) == expected_size:
            print(f"skip {rel}")
            continue
        url = f"{args.base_url}/{rel}"
        if expected_size >= args.parallel_threshold_mb * 1024 * 1024:
            cmd = [
                sys.executable,
                "scripts/download_hf_file_parallel.py",
                "--url",
                url,
                "--output",
                str(target),
                "--expected-size",
                str(expected_size),
                "--proxy",
                args.proxy,
                "--connections",
                str(args.connections),
                "--chunk-size-mb",
                str(args.chunk_size_mb),
                "--timeout",
                "300",
            ]
            print("parallel", rel, flush=True)
            subprocess.run(cmd, check=True)
        else:
            print("download", rel, flush=True)
            download_small(url, target, expected_size, args.proxy)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
