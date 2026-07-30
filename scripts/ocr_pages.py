#!/usr/bin/env python3
"""Create page-level Latin + Ancient Greek OCR shards from Internet Archive scans."""
from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SOURCES = (
    ("totiuslatinitati01forc", 1356),
    ("totiuslatinitati02forc", 1502),
)
USER_AGENT = "Forcellinus-PWA-Greek-OCR/1.0 (+https://github.com/jankurowicki-lgtm/forcellinus-online)"


def download_page(identifier: str, leaf: int, destination: Path, attempts: int = 5) -> None:
    url = f"https://archive.org/download/{identifier}/page/n{leaf}_w2500.jpg"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                data = response.read()
            if len(data) < 10_000:
                raise RuntimeError(f"unexpectedly small scan ({len(data)} bytes)")
            destination.write_bytes(data)
            return
        except Exception:
            if attempt + 1 == attempts:
                raise
            time.sleep(2**attempt)


def ocr_page(
    identifier: str,
    leaf: int,
    output_root: Path,
    tessdata: Path,
) -> str:
    destination = output_root / identifier / f"{leaf:04d}.txt"
    if destination.exists() and destination.stat().st_size > 20:
        return f"cached {identifier}/{leaf}"

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="forcellinus-ocr-") as temporary:
        image = Path(temporary) / "page.jpg"
        result_base = Path(temporary) / "page"
        download_page(identifier, leaf, image)
        environment = os.environ.copy()
        # One Tesseract process per core is faster and more predictable than
        # OpenMP oversubscription when several pages are processed together.
        environment["OMP_THREAD_LIMIT"] = "1"
        subprocess.run(
            [
                "tesseract",
                str(image),
                str(result_base),
                "--tessdata-dir",
                str(tessdata),
                "-l",
                "lat+grc+eng",
                "--psm",
                "3",
            ],
            check=True,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        text = result_base.with_suffix(".txt").read_text(encoding="utf-8", errors="replace")
    destination.write_text(text, encoding="utf-8")
    return f"done {identifier}/{leaf}: {len(text)} characters"


def selected_pages(shard: int, shard_count: int) -> list[tuple[str, int]]:
    pages: list[tuple[str, int]] = []
    global_index = 0
    for identifier, leaf_count in SOURCES:
        for leaf in range(leaf_count):
            if global_index % shard_count == shard:
                pages.append((identifier, leaf))
            global_index += 1
    return pages


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard", type=int, required=True)
    parser.add_argument("--shard-count", type=int, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--output", type=Path, default=Path(".cache/greek-ocr/pages"))
    parser.add_argument("--tessdata", type=Path, required=True)
    args = parser.parse_args()
    if not 0 <= args.shard < args.shard_count:
        parser.error("--shard must be in the range 0 <= shard < shard-count")

    pages = selected_pages(args.shard, args.shard_count)
    print(f"OCR shard {args.shard + 1}/{args.shard_count}: {len(pages)} pages")
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(ocr_page, identifier, leaf, args.output, args.tessdata): (identifier, leaf)
            for identifier, leaf in pages
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            identifier, leaf = futures[future]
            try:
                message = future.result()
            except Exception as error:
                raise RuntimeError(f"OCR failed for {identifier}/{leaf}") from error
            print(f"[{completed}/{len(pages)}] {message}", flush=True)


if __name__ == "__main__":
    main()
