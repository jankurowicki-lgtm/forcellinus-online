#!/usr/bin/env python3
"""Run a small, reproducible OCR comparison without changing the public corpus."""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import time
import unicodedata
import urllib.request
from dataclasses import dataclass
from pathlib import Path


USER_AGENT = (
    "Forcellinus-PWA-OCR-Pilot/1.0 "
    "(+https://github.com/jankurowicki-lgtm/forcellinus-online)"
)


@dataclass(frozen=True)
class Page:
    identifier: str
    leaf: int
    label: str


PAGES = (
    Page("totiuslatinitati01forc", 364, "cauda"),
    Page("totiuslatinitati01forc", 869, "germanus"),
    Page("totiuslatinitati01forc", 923, "humanitas"),
    Page("totiuslatinitati01forc", 1215, "otacilius"),
    Page("totiuslatinitati02forc", 372, "ratio"),
    Page("totiuslatinitati02forc", 689, "supra"),
)

EXPECTED = {
    "cauda": ("animalibus", "κέρκος", "οὐρά"),
    "germanus": ("brother", "sister", "αὐτοκασίγνητος", "frater"),
    "humanitas": ("human nature", "humanity", "ἀνθρωπότης", "φιλανθρωπία"),
    "otacilius": ("Menti aedem", "T. Otacilius", "praetor vovit"),
    "ratio": ("reason", "νοῦς", "λόγος"),
    "supra": ("above", "over", "upon", "ὑπὲρ"),
}

CONFIGS = (
    ("fast-original-psm3", "fast", False, 3),
    ("best-original-psm3", "best", False, 3),
    ("best-processed-psm3", "best", True, 3),
    ("best-processed-psm4", "best", True, 4),
)


def download(url: str, destination: Path, attempts: int = 5) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size > 10_000:
        return
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                data = response.read()
            if len(data) < 10_000:
                raise RuntimeError(f"unexpectedly small download: {len(data)} bytes")
            destination.write_bytes(data)
            return
        except Exception:
            if attempt + 1 == attempts:
                raise
            time.sleep(2**attempt)


def preprocess(source: Path, destination: Path) -> None:
    subprocess.run(
        [
            "convert",
            str(source),
            "-colorspace",
            "Gray",
            "-deskew",
            "40%",
            "-contrast-stretch",
            "1%x1%",
            "-sharpen",
            "0x1",
            str(destination),
        ],
        check=True,
    )


def run_tesseract(
    image: Path,
    output_base: Path,
    tessdata: Path,
    psm: int,
) -> None:
    output_base.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["OMP_THREAD_LIMIT"] = "2"
    subprocess.run(
        [
            "tesseract",
            str(image),
            str(output_base),
            "--tessdata-dir",
            str(tessdata),
            "-l",
            "lat+grc+eng",
            "--oem",
            "1",
            "--psm",
            str(psm),
            "txt",
            "tsv",
        ],
        check=True,
        env=environment,
    )


def fold(value: str) -> str:
    value = unicodedata.normalize("NFC", value).casefold()
    return re.sub(r"\s+", " ", value)


def confidence(tsv: Path) -> float | None:
    values: list[float] = []
    with tsv.open(encoding="utf-8", errors="replace", newline="") as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            if not row.get("text", "").strip():
                continue
            try:
                score = float(row["conf"])
            except (KeyError, ValueError):
                continue
            if score >= 0:
                values.append(score)
    return round(sum(values) / len(values), 2) if values else None


def make_report(output: Path) -> dict:
    rows = []
    for config, _, _, _ in CONFIGS:
        for page in PAGES:
            base = output / "results" / config / f"{page.identifier}-{page.leaf:04d}"
            text = base.with_suffix(".txt").read_text(encoding="utf-8", errors="replace")
            observed = fold(text)
            tokens = {
                token: fold(token) in observed
                for token in EXPECTED[page.label]
            }
            rows.append(
                {
                    "config": config,
                    "page": page.label,
                    "identifier": page.identifier,
                    "leaf": page.leaf,
                    "confidence": confidence(base.with_suffix(".tsv")),
                    "expected": tokens,
                    "passed": sum(tokens.values()),
                    "total": len(tokens),
                }
            )

    summary = {}
    for config, _, _, _ in CONFIGS:
        selected = [row for row in rows if row["config"] == config]
        summary[config] = {
            "passed": sum(row["passed"] for row in selected),
            "total": sum(row["total"] for row in selected),
            "mean_confidence": round(
                sum(row["confidence"] or 0 for row in selected) / len(selected), 2
            ),
        }

    report = {"summary": summary, "pages": rows}
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# Forcellinus OCR pilot",
        "",
        "Automated token checks are diagnostic only; the scans remain authoritative.",
        "",
        "| Configuration | Expected tokens | Mean confidence |",
        "|---|---:|---:|",
    ]
    for config, result in summary.items():
        lines.append(
            f"| `{config}` | {result['passed']}/{result['total']} | "
            f"{result['mean_confidence']:.2f} |"
        )
    lines.extend(
        [
            "",
            "| Configuration | Page | Result | Confidence |",
            "|---|---|---:|---:|",
        ]
    )
    for row in rows:
        lines.append(
            f"| `{row['config']}` | {row['page']} | "
            f"{row['passed']}/{row['total']} | {row['confidence']} |"
        )
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("ocr-pilot-output"))
    parser.add_argument("--tessdata-fast", type=Path, required=True)
    parser.add_argument("--tessdata-best", type=Path, required=True)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    for page in PAGES:
        stem = f"{page.identifier}-{page.leaf:04d}"
        original = args.output / "images" / f"{stem}.jpg"
        processed = args.output / "images" / f"{stem}-processed.png"
        download(
            f"https://archive.org/download/{page.identifier}/page/n{page.leaf}_w2500.jpg",
            original,
        )
        preprocess(original, processed)
        for config, model, use_processed, psm in CONFIGS:
            tessdata = args.tessdata_fast if model == "fast" else args.tessdata_best
            run_tesseract(
                processed if use_processed else original,
                args.output / "results" / config / stem,
                tessdata,
                psm,
            )

    report = make_report(args.output)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
