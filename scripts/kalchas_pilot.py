#!/usr/bin/env python3
"""Evaluate free polytonic-Greek OCR on exact Forcellinus word crops."""
from __future__ import annotations

import json
import time
import unicodedata
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from kalchas.ocr import load_ocr_model


USER_AGENT = (
    "Forcellinus-PWA-Kalchas-Pilot/1.0 "
    "(+https://github.com/jankurowicki-lgtm/forcellinus-online)"
)


@dataclass(frozen=True)
class Sample:
    name: str
    identifier: str
    leaf: int
    box: tuple[int, int, int, int]
    expected: str


SAMPLES = (
    Sample("cauda-kerkos", "totiuslatinitati01forc", 364, (875, 325, 1005, 395), "κέρκος,"),
    Sample("cauda-oura", "totiuslatinitati01forc", 364, (40, 375, 150, 445), "οὐρὰ,"),
    Sample(
        "germanus-kasignetos",
        "totiuslatinitati01forc",
        869,
        (190, 2915, 420, 2990),
        "κασίγνητος,",
    ),
    Sample(
        "humanitas-anthro",
        "totiuslatinitati01forc",
        923,
        (2025, 3015, 2175, 3090),
        "ἀνθρω-",
    ),
    Sample(
        "humanitas-potes",
        "totiuslatinitati01forc",
        923,
        (1180, 3060, 1340, 3135),
        "πότης,",
    ),
    Sample(
        "humanitas-philanthropia",
        "totiuslatinitati01forc",
        923,
        (1320, 3145, 1560, 3220),
        "φιλανθρωπία",
    ),
    Sample(
        "ratio-greek",
        "totiuslatinitati02forc",
        372,
        (1375, 2745, 1595, 2820),
        "νοῦς, λόγος,",
    ),
    Sample(
        "supra-hyper",
        "totiuslatinitati02forc",
        689,
        (1840, 4025, 1960, 4100),
        "ὑπὲρ,",
    ),
)


def download(identifier: str, leaf: int, destination: Path) -> None:
    if destination.exists() and destination.stat().st_size > 10_000:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://archive.org/download/{identifier}/page/n{leaf}_w2500.jpg"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                data = response.read()
            if len(data) < 10_000:
                raise RuntimeError(f"unexpectedly small download: {len(data)} bytes")
            destination.write_bytes(data)
            return
        except Exception:
            if attempt == 4:
                raise
            time.sleep(2**attempt)


def normalize(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip()


def main() -> None:
    output = Path("kalchas-pilot-output")
    images = output / "images"
    crops = output / "crops"
    crops.mkdir(parents=True, exist_ok=True)

    crop_paths = []
    for sample in SAMPLES:
        scan = images / f"{sample.identifier}-{sample.leaf:04d}.jpg"
        download(sample.identifier, sample.leaf, scan)
        crop = crops / f"{sample.name}.png"
        Image.open(scan).crop(sample.box).save(crop)
        crop_paths.append(crop)

    rows = []
    for model_name in ("Kalchas", "Polyton-DB"):
        model = load_ocr_model(model_name)
        observed = model.ocr([Image.open(path).convert("L") for path in crop_paths])
        for sample, text in zip(SAMPLES, observed):
            expected = normalize(sample.expected)
            actual = normalize(text)
            rows.append(
                {
                    "model": model_name,
                    "sample": sample.name,
                    "expected": expected,
                    "observed": actual,
                    "exact": actual == expected,
                }
            )

    summary = {
        model_name: {
            "passed": sum(row["exact"] for row in rows if row["model"] == model_name),
            "total": len(SAMPLES),
        }
        for model_name in ("Kalchas", "Polyton-DB")
    }
    report = {"summary": summary, "samples": rows}
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# Forcellinus polytonic-Greek OCR pilot",
        "",
        "| Model | Exact word crops |",
        "|---|---:|",
    ]
    for model_name, result in summary.items():
        lines.append(f"| `{model_name}` | {result['passed']}/{result['total']} |")
    lines.extend(["", "| Model | Sample | Expected | Observed | Exact |", "|---|---|---|---|---:|"])
    for row in rows:
        mark = "yes" if row["exact"] else "no"
        lines.append(
            f"| `{row['model']}` | {row['sample']} | `{row['expected']}` | "
            f"`{row['observed']}` | {mark} |"
        )
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
