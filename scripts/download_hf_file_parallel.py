#!/usr/bin/env python3
import argparse
import concurrent.futures
import os
import shutil
import time
from pathlib import Path

import requests


def file_size(path: Path) -> int:
    return path.stat().st_size if path.exists() else -1


def download_range(url: str, part: Path, start: int, end: int, proxies, timeout: int) -> str:
    expected = end - start + 1
    if file_size(part) == expected:
        return f"skip {start}-{end}"
    if part.exists():
        part.unlink()

    headers = {"Range": f"bytes={start}-{end}"}
    last_error = None
    for _ in range(8):
        try:
            with requests.get(
                url,
                headers=headers,
                proxies=proxies,
                stream=True,
                timeout=(30, timeout),
                allow_redirects=True,
            ) as response:
                response.raise_for_status()
                if response.status_code != 206:
                    raise RuntimeError(f"range request returned HTTP {response.status_code}")
                tmp = part.with_suffix(part.suffix + ".tmp")
                if tmp.exists():
                    tmp.unlink()
                with tmp.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            handle.write(chunk)
                if file_size(tmp) == expected:
                    tmp.replace(part)
                    return f"ok {start}-{end}"
                last_error = RuntimeError(f"expected {expected}, got {file_size(tmp)}")
                tmp.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001 - retry network failures.
            last_error = exc
            time.sleep(3)
    raise RuntimeError(f"failed {start}-{end}: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-size", required=True, type=int)
    parser.add_argument("--proxy")
    parser.add_argument("--connections", type=int, default=12)
    parser.add_argument("--chunk-size-mb", type=int, default=16)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    expected_size = args.expected_size

    if file_size(output) == expected_size:
        print(f"OK {output} ({expected_size} bytes)")
        return 0
    if file_size(output) > expected_size:
        raise RuntimeError(f"{output} is larger than expected")

    part_root = Path(str(output) + ".parts")
    part_root.mkdir(parents=True, exist_ok=True)

    current_size = max(file_size(output), 0)
    if current_size:
        seed = part_root / f"{0:010d}-{current_size - 1:010d}.part"
        if file_size(seed) != current_size:
            shutil.copyfile(output, seed)

    ranges = []
    chunk_size = args.chunk_size_mb * 1024 * 1024
    start = current_size
    while start < expected_size:
        end = min(expected_size - 1, start + chunk_size - 1)
        ranges.append((start, end, part_root / f"{start:010d}-{end:010d}.part"))
        start = end + 1

    proxies = None
    if args.proxy:
        proxies = {"http": args.proxy, "https": args.proxy}

    pending = [(s, e, p, 0) for s, e, p in ranges if file_size(p) != e - s + 1]
    print(f"seed={current_size} pending_parts={len(pending)} connections={args.connections}")

    completed = 0
    failed = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.connections) as executor:
        futures = {}
        while pending or futures:
            while pending and len(futures) < args.connections:
                start, end, part, attempts = pending.pop(0)
                future = executor.submit(download_range, args.url, part, start, end, proxies, args.timeout)
                futures[future] = (start, end, part, attempts)

            done, _ = concurrent.futures.wait(
                futures,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            for future in done:
                start, end, part, attempts = futures.pop(future)
                try:
                    print(future.result(), flush=True)
                    completed += 1
                except Exception as exc:  # noqa: BLE001 - keep long downloads alive.
                    if attempts < 10:
                        print(f"retry {start}-{end}: {exc}", flush=True)
                        pending.append((start, end, part, attempts + 1))
                    else:
                        print(f"giveup {start}-{end}: {exc}", flush=True)
                        failed.append((start, end, exc))

                if (completed + len(failed)) % 4 == 0 or (not pending and not futures):
                    total = sum(min(max(file_size(p), 0), e - s + 1) for s, e, p in ranges)
                    if current_size:
                        total += current_size
                    percent = round(total / expected_size * 100, 2)
                    print(f"progress {total}/{expected_size} bytes ({percent}%)", flush=True)

    if failed:
        raise RuntimeError(f"{len(failed)} ranges failed")

    parts = []
    if current_size:
        parts.append(part_root / f"{0:010d}-{current_size - 1:010d}.part")
    parts.extend(part for _, _, part in ranges)
    total = sum(part.stat().st_size for part in parts if part.exists())
    if total != expected_size:
        raise RuntimeError(f"part total mismatch: expected {expected_size}, got {total}")

    tmp_output = output.with_suffix(output.suffix + ".tmp")
    if tmp_output.exists():
        tmp_output.unlink()
    with tmp_output.open("wb") as out:
        for part in parts:
            with part.open("rb") as handle:
                shutil.copyfileobj(handle, out, length=1024 * 1024)
    if file_size(tmp_output) != expected_size:
        raise RuntimeError("combined file size mismatch")
    tmp_output.replace(output)
    shutil.rmtree(part_root)
    print(f"OK {output} ({expected_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
