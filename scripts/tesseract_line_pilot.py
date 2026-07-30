#!/usr/bin/env python3
"""Compare free Tesseract models on exact Greek lines and words from Forcellinus."""
from __future__ import annotations

import json
import os
import subprocess
import time
import unicodedata
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter


USER_AGENT = (
    "Forcellinus-PWA-Tesseract-Line-Pilot/1.0 "
    "(+https://github.com/jankurowicki-lgtm/forcellinus-online)"
)


@dataclass(frozen=True)
class Sample:
    name: str
    identifier: str
    leaf: int
    line_box: tuple[int, int, int, int]
    word_box: tuple[int, int, int, int]
    expected: str


SAMPLES = (
    Sample(
        "cauda-kerkos",
        "totiuslatinitati01forc",
        364,
        (40, 345, 1010, 405),
        (875, 325, 1005, 395),
        "κέρκος,",
    ),
    Sample(
        "cauda-oura",
        "totiuslatinitati01forc",
        364,
        (40, 405, 1010, 465),
        (40, 375, 150, 445),
        "οὐρὰ,",
    ),
    Sample(
        "germanus-kasignetos",
        "totiuslatinitati01forc",
        869,
        (180, 2940, 1110, 3000),
        (190, 2915, 420, 2990),
        "κασίγνητος,",
    ),
    Sample(
        "humanitas-anthro",
        "totiuslatinitati01forc",
        923,
        (1180, 3035, 2160, 3095),
        (2025, 3015, 2175, 3090),
        "ἀνθρω-",
    ),
    Sample(
        "humanitas-potes",
        "totiuslatinitati01forc",
        923,
        (1180, 3090, 2160, 3150),
        (1180, 3060, 1340, 3135),
        "πότης,",
    ),
    Sample(
        "humanitas-philanthropia",
        "totiuslatinitati01forc",
        923,
        (1180, 3155, 2160, 3215),
        (1320, 3145, 1560, 3220),
        "φιλανθρωπία",
    ),
    Sample(
        "ratio-greek",
        "totiuslatinitati02forc",
        372,
        (1200, 2770, 2280, 2830),
        (1375, 2745, 1595, 2820),
        "νοῦς, λόγος,",
    ),
    Sample(
        "supra-hyper",
        "totiuslatinitati02forc",
        689,
        (1230, 4040, 2310, 4100),
        (1840, 4025, 1960, 4100),
        "ὑπὲρ,",
    ),
)


CONFIGS = (
    ("line-lat-first", "line", "lat+grc+eng", 7, False),
    ("line-grc-first", "line", "grc+lat+eng", 7, False),
    ("line-grc-first-enhanced", "line", "grc+lat+eng", 7, True),
    ("word-grc-only-enhanced", "word", "grc", 8, True),
    ("word-grc-first-enhanced", "word", "grc+lat+eng", 8, True),
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


def enhance(image: Image.Image) -> Image.Image:
    image = image.convert("L").resize((image.width * 2, image.height * 2))
    image = ImageEnhance.Contrast(image).enhance(1.5)
    return image.filter(ImageFilter.SHARPEN)


def recognize(image: Path, tessdata: Path, languages: str, psm: int) -> str:
    environment = os.environ.copy()
    environment["OMP_THREAD_LIMIT"] = "2"
    result = subprocess.run(
        [
            "tesseract",
            str(image),
            "stdout",
            "--tessdata-dir",
            str(tessdata),
            "-l",
            languages,
            "--oem",
            "1",
            "--psm",
            str(psm),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    return normalize(result.stdout)


def main() -> None:
    output = Path("tesseract-line-pilot-output")
    scans = output / "images"
    crops = output / "crops"
    crops.mkdir(parents=True, exist_ok=True)
    tessdata = Path(".cache/tessdata-best")

    prepared: dict[tuple[str, str, bool], Path] = {}
    for sample in SAMPLES:
        scan = scans / f"{sample.identifier}-{sample.leaf:04d}.jpg"
        download(sample.identifier, sample.leaf, scan)
        source = Image.open(scan)
        for kind, box in (("line", sample.line_box), ("word", sample.word_box)):
            crop = source.crop(box)
            for changed in (False, True):
                suffix = "-enhanced" if changed else ""
                path = crops / f"{sample.name}-{kind}{suffix}.png"
                (enhance(crop) if changed else crop).save(path)
                prepared[(sample.name, kind, changed)] = path

    rows = []
    for config, kind, languages, psm, changed in CONFIGS:
        for sample in SAMPLES:
            observed = recognize(
                prepared[(sample.name, kind, changed)],
                tessdata,
                languages,
                psm,
            )
            expected = normalize(sample.expected)
            rows.append(
                {
                    "config": config,
                    "sample": sample.name,
                    "expected": expected,
                    "observed": observed,
                    "exact": expected in observed,
                }
            )

    summary = {
        config: {
            "passed": sum(row["exact"] for row in rows if row["config"] == config),
            "total": len(SAMPLES),
        }
        for config, *_ in CONFIGS
    }
    report = {"summary": summary, "samples": rows}
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# Forcellinus segmented Tesseract pilot",
        "",
        "| Configuration | Exact Greek tokens |",
        "|---|---:|",
    ]
    for config, result in summary.items():
        lines.append(f"| `{config}` | {result['passed']}/{result['total']} |")
    lines.extend(["", "| Configuration | Sample | Expected | Observed | Exact |", "|---|---|---|---|---:|"])
    for row in rows:
        mark = "yes" if row["exact"] else "no"
        observed = row["observed"].replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| `{row['config']}` | {row['sample']} | `{row['expected']}` | "
            f"`{observed}` | {mark} |"
        )
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
