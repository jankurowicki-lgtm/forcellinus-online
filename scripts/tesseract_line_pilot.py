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
    return unicodedata.normalize("NFC", value).replace("ϑ", "θ").strip()


def greek_tokens(value: str) -> list[str]:
    """Return Greek runs without trusting OCR spaces or surrounding Latin."""
    tokens: list[str] = []
    current: list[str] = []
    for character in normalize(value):
        code = ord(character)
        is_greek = 0x0370 <= code <= 0x03FF or 0x1F00 <= code <= 0x1FFF
        is_mark = unicodedata.category(character) == "Mn"
        if is_greek or (is_mark and current) or (character == "-" and current):
            current.append(character)
        elif current:
            tokens.append("".join(current).strip("-"))
            current = []
    if current:
        tokens.append("".join(current).strip("-"))
    return [token for token in tokens if token]


def load_wordlist(path: Path) -> set[str]:
    words: set[str] = set()
    with path.open(encoding="utf-8") as stream:
        next(stream, None)
        for line in stream:
            word = line.strip().split("/", 1)[0]
            if word:
                words.add(normalize(word))
    return words


def choose_ensemble(rows: list[dict], wordlist: set[str]) -> list[dict]:
    """Prefer candidates whose Greek tokens are known to Morpheus/Hunspell."""
    useful = ("word-grc-only-enhanced", "line-grc-first-enhanced")
    by_sample = {
        sample.name: [row for row in rows if row["sample"] == sample.name and row["config"] in useful]
        for sample in SAMPLES
    }
    selected: dict[str, str] = {}
    for sample in SAMPLES:
        candidates = by_sample[sample.name]
        ranked = []
        for row in candidates:
            observed = normalize(row["observed"])
            tokens = greek_tokens(observed)
            valid = [token for token in tokens if token in wordlist]
            ranked.append(((len(valid), sum(map(len, valid))), observed))
        selected[sample.name] = max(ranked)[1]

    # Resolve words divided by a printed end-of-line hyphen. A prefix/suffix
    # pair is accepted only if their joined form exists in the Greek wordlist.
    for left, right in zip(SAMPLES, SAMPLES[1:]):
        for left_row in by_sample[left.name]:
            left_observed = normalize(left_row["observed"])
            left_parts = greek_tokens(left_observed)
            if not left_parts or not any(part + "-" in left_observed for part in left_parts):
                continue
            prefix = left_parts[-1]
            for right_row in by_sample[right.name]:
                right_observed = normalize(right_row["observed"])
                for suffix in greek_tokens(right_observed):
                    if prefix + suffix in wordlist:
                        selected[left.name] = left_observed
                        selected[right.name] = right_observed

    return [
        {
            "config": "lexicon-validated-ensemble",
            "sample": sample.name,
            "expected": normalize(sample.expected),
            "observed": selected[sample.name],
            "exact": normalize(sample.expected) in selected[sample.name],
        }
        for sample in SAMPLES
    ]


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

    wordlist = load_wordlist(Path(".cache/hunspell-ancient-greek/grc_GR.dic"))
    rows.extend(choose_ensemble(rows, wordlist))

    summary = {
        config: {
            "passed": sum(row["exact"] for row in rows if row["config"] == config),
            "total": len(SAMPLES),
        }
        for config in [*(item[0] for item in CONFIGS), "lexicon-validated-ensemble"]
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
