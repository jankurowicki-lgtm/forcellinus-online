#!/usr/bin/env python3
"""Compare free Kraken models on difficult Forcellinus pages."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
import unicodedata
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


USER_AGENT = (
    "Forcellinus-PWA-Kraken-Pilot/1.0 "
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


def split_columns(source: Path, destination: Path) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    image = Image.open(source)
    width, height = image.size
    # The printed area is inset from the scan edges, so equal thirds cut off
    # the ends of lines (often the Greek glosses) and leak neighbouring text.
    # These bounds follow the vertical rules visible in both 1828 volumes.
    bounds = (
        (0.045, 0.360),
        (0.350, 0.675),
        (0.665, 0.980),
    )
    crops = []
    for column, (left_ratio, right_ratio) in enumerate(bounds, start=1):
        left = round(width * left_ratio)
        right = round(width * right_ratio)
        path = destination / f"{source.stem}-column-{column}.png"
        image.crop((left, 0, right, height)).save(path)
        crops.append(path)
    return crops


def recognize(crops: list[Path], output: Path, model: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    command = ["kraken"]
    for crop in crops:
        command.extend(["-i", str(crop), str(output / f"{crop.stem}.txt")])
    command.extend(["binarize", "segment", "ocr", "-m", str(model)])
    subprocess.run(command, check=True)


def fold(value: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        unicodedata.normalize("NFC", value).casefold(),
    )


def page_text(output: Path, stem: str) -> str:
    return "\n".join(
        (output / f"{stem}-column-{column}.txt").read_text(
            encoding="utf-8",
            errors="replace",
        )
        for column in range(1, 4)
    )


def make_report(output: Path, models: dict[str, Path]) -> dict:
    rows = []
    for model_name in models:
        model_output = output / "results" / model_name
        for page in PAGES:
            stem = f"{page.identifier}-{page.leaf:04d}"
            text = page_text(model_output, stem)
            (model_output / f"{stem}-combined.txt").write_text(
                text,
                encoding="utf-8",
            )
            observed = fold(text)
            tokens = {
                token: fold(token) in observed
                for token in EXPECTED[page.label]
            }
            rows.append(
                {
                    "model": model_name,
                    "page": page.label,
                    "identifier": page.identifier,
                    "leaf": page.leaf,
                    "expected": tokens,
                    "passed": sum(tokens.values()),
                    "total": len(tokens),
                }
            )

    summary = {}
    for model_name in models:
        selected = [row for row in rows if row["model"] == model_name]
        summary[model_name] = {
            "passed": sum(row["passed"] for row in selected),
            "total": sum(row["total"] for row in selected),
        }

    report = {"summary": summary, "pages": rows}
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# Forcellinus Kraken OCR pilot",
        "",
        "Automated token checks are diagnostic only; the scans remain authoritative.",
        "",
        "| Model | Expected tokens |",
        "|---|---:|",
    ]
    for model_name, result in summary.items():
        lines.append(
            f"| `{model_name}` | {result['passed']}/{result['total']} |"
        )
    lines.extend(
        [
            "",
            "| Model | Page | Result |",
            "|---|---|---:|",
        ]
    )
    for row in rows:
        lines.append(
            f"| `{row['model']}` | {row['page']} | "
            f"{row['passed']}/{row['total']} |"
        )
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("kraken-pilot-output"))
    parser.add_argument("--model", action="append", required=True)
    args = parser.parse_args()
    models = {}
    for value in args.model:
        name, separator, raw_path = value.partition("=")
        if not separator or not name or not raw_path:
            parser.error("--model must use NAME=PATH")
        models[name] = Path(raw_path)

    crops: list[Path] = []
    args.output.mkdir(parents=True, exist_ok=True)
    for page in PAGES:
        stem = f"{page.identifier}-{page.leaf:04d}"
        image = args.output / "images" / f"{stem}.jpg"
        download(
            f"https://archive.org/download/{page.identifier}/page/n{page.leaf}_w2500.jpg",
            image,
        )
        crops.extend(split_columns(image, args.output / "columns"))

    for model_name, model in models.items():
        recognize(crops, args.output / "results" / model_name, model)

    report = make_report(args.output, models)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
