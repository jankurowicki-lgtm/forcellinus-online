#!/usr/bin/env python3
"""Validate automatic three-column segmentation on difficult Forcellinus pages."""
from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import tempfile
import time
import unicodedata
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(".")
OUTPUT = ROOT / "column-ocr-pilot-output"
IMAGE_ROOT = OUTPUT / "images"
TESSDATA = ROOT / ".cache/tessdata-best"
GREEK_WORDLIST = ROOT / ".cache/hunspell-ancient-greek/grc_GR.dic"
LATIN_WORDLIST = ROOT / ".cache/verba/verba.txt"
USER_AGENT = (
    "Forcellinus-PWA-Column-OCR-Pilot/1.0 "
    "(+https://github.com/jankurowicki-lgtm/forcellinus-online)"
)


@dataclass(frozen=True)
class Case:
    name: str
    image: str
    column: int
    expected: tuple[str, ...]
    edition_expected: tuple[str, ...] = ()


CASES = (
    Case(
        "cauda",
        "totiuslatinitati01forc-0364.jpg",
        0,
        ("κέρκος", "οὐρὰ", "posterior pars pendens in animalibus"),
    ),
    Case(
        "germanus",
        "totiuslatinitati01forc-0869.jpg",
        0,
        ("αὐτο", "κασίγνητος", "a brother, sister"),
    ),
    Case(
        "humanitas",
        "totiuslatinitati01forc-0923.jpg",
        1,
        ("ἀνθρω-", "πότης", "φιλανθρωπία"),
    ),
    Case(
        "otacilius",
        "totiuslatinitati01forc-1215.jpg",
        1,
        ("T. Otacilius", "vovit"),
        ("ædem", "præ-"),
    ),
    Case(
        "ratio",
        "totiuslatinitati02forc-0372.jpg",
        1,
        ("νοῦς", "λόγος"),
    ),
    Case(
        "supra",
        "totiuslatinitati02forc-0689.jpg",
        1,
        ("ὑπὲρ",),
    ),
)


def normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text).replace("ϑ", "θ")


def greek_core(text: str) -> str:
    result: list[str] = []
    for character in normalize(text):
        code = ord(character)
        if (
            0x0370 <= code <= 0x03FF
            or 0x1F00 <= code <= 0x1FFF
            or (unicodedata.category(character) == "Mn" and result)
        ):
            result.append(character)
    return "".join(result)


def load_greek_words() -> set[str]:
    words: set[str] = set()
    with GREEK_WORDLIST.open(encoding="utf-8") as stream:
        next(stream, None)
        for line in stream:
            word = normalize(line.strip().split("/", 1)[0])
            if word:
                words.add(word)
    return words


def normalize_latin(text: str) -> str:
    return (
        text.casefold()
        .replace("æ", "ae")
        .replace("œ", "oe")
        .replace("j", "i")
        .replace("v", "u")
    )


def latin_core(text: str) -> str:
    return "".join(re.findall(r"[A-Za-zÆŒæœ]+", text))


def load_latin_words() -> set[str]:
    return {
        normalize_latin(line.strip())
        for line in LATIN_WORDLIST.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def ligature_variants(word: str) -> set[str]:
    """Generate conservative OCR confusions for printed æ/œ ligatures."""
    lowered = word.casefold()
    variants: set[str] = set()
    for index, character in enumerate(lowered):
        if character == "e":
            variants.add(lowered[:index] + "a" + lowered[index:])
            variants.add(lowered[:index] + "o" + lowered[index:])
        elif character == "z":
            variants.add(lowered[:index] + "ae" + lowered[index + 1 :])
    return variants


def printed_ligatures(word: str) -> str:
    return word.replace("ae", "æ").replace("oe", "œ")


def correct_latin_ligature(
    observed: str,
    next_observed: str,
    confidence: float,
    wordlist: set[str],
) -> tuple[str, dict | None]:
    """Correct only unambiguous low-confidence ligatures; queue ambiguities."""
    if confidence >= 50:
        return observed, None
    core = latin_core(observed)
    if len(core) < 2:
        return observed, None
    next_core = latin_core(next_observed) if observed.rstrip().endswith("-") else ""
    observed_joined = normalize_latin(core + next_core)
    valid_candidates = {
        candidate
        for candidate in ligature_variants(core)
        if normalize_latin(candidate + next_core) in wordlist
    }
    if not valid_candidates:
        return observed, None

    review = {
        "observed": observed,
        "next": next_observed,
        "confidence": confidence,
        "candidates": sorted(printed_ligatures(item) for item in valid_candidates),
    }
    if observed_joined in wordlist or len(valid_candidates) != 1:
        review["status"] = "manual-review"
        return observed, review

    candidate = valid_candidates.pop()
    replacement = printed_ligatures(candidate)
    if observed.rstrip().endswith("-"):
        replacement += "-"
    review["status"] = "auto-corrected"
    review["replacement"] = replacement
    return replacement, review


def download_image(filename: str) -> Path:
    destination = IMAGE_ROOT / filename
    if destination.exists() and destination.stat().st_size > 10_000:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    identifier, leaf_with_suffix = filename.rsplit("-", 1)
    leaf = int(Path(leaf_with_suffix).stem)
    url = f"https://archive.org/download/{identifier}/page/n{leaf}_w2500.jpg"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                data = response.read()
            if len(data) < 10_000:
                raise RuntimeError(f"unexpectedly small scan: {len(data)} bytes")
            destination.write_bytes(data)
            return destination
        except Exception:
            if attempt == 4:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("download failed")


def detect_boundaries(image: Image.Image) -> tuple[int, int]:
    """Find the two column separators from the vertical ink projection."""
    gray = np.asarray(image.convert("L"))
    height, width = gray.shape
    body = gray[int(height * 0.05) : int(height * 0.94)]
    ink = (body < 160).mean(axis=0)
    window = max(17, round(width * 0.0065))
    if window % 2 == 0:
        window += 1
    smooth = np.convolve(ink, np.ones(window) / window, mode="same")

    boundaries: list[int] = []
    for lower, upper in ((0.25, 0.43), (0.55, 0.75)):
        start, end = int(width * lower), int(width * upper)
        valley = start + int(np.argmin(smooth[start:end]))
        # The minimum lies immediately before the printed rule (or in the
        # middle of a blank gutter). Move by half a smoothing window so the
        # crop includes every terminal glyph without importing the next column.
        boundaries.append(valley + window // 2 + 2)
    first, second = boundaries
    if not (width * 0.25 < first < width * 0.43 < width * 0.55 < second < width * 0.75):
        raise RuntimeError(f"implausible column boundaries: {boundaries} for width {width}")
    return first, second


def crop_column(image: Image.Image, index: int, boundaries: tuple[int, int]) -> Image.Image:
    width, height = image.size
    first, second = boundaries
    bounds = ((0, first), (first + 2, second), (second + 2, width))
    left, right = bounds[index]
    return image.crop((left, 0, right, height))


def recognize_greek_word(image: Image.Image) -> str:
    enlarged = image.convert("L").resize((image.width * 2, image.height * 2))
    with tempfile.NamedTemporaryFile(suffix=".png", dir=OUTPUT, delete=False) as stream:
        temporary = Path(stream.name)
    try:
        enlarged.save(temporary)
        environment = os.environ.copy()
        environment["OMP_THREAD_LIMIT"] = "1"
        result = subprocess.run(
            [
                "tesseract",
                str(temporary),
                "stdout",
                "--tessdata-dir",
                str(TESSDATA),
                "-l",
                "grc",
                "--oem",
                "1",
                "--psm",
                "8",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        return normalize(result.stdout)
    finally:
        temporary.unlink(missing_ok=True)


def ocr(
    path: Path,
    greek_wordlist: set[str],
    latin_wordlist: set[str],
) -> tuple[str, list[dict]]:
    base = OUTPUT / f"_{path.stem}"
    environment = os.environ.copy()
    environment["OMP_THREAD_LIMIT"] = "1"
    subprocess.run(
        [
            "tesseract",
            str(path),
            str(base),
            "--tessdata-dir",
            str(TESSDATA),
            "-l",
            "grc+lat+eng",
            "--oem",
            "1",
            "--psm",
            "6",
            "tsv",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    image = Image.open(path)
    lines: dict[tuple[str, ...], list[dict[str, str]]] = {}
    with base.with_suffix(".tsv").open(encoding="utf-8") as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            if row["level"] != "5" or not row["text"].strip():
                continue
            key = (row["page_num"], row["block_num"], row["par_num"], row["line_num"])
            lines.setdefault(key, []).append(row)

    rendered: list[str] = []
    review_queue: list[dict] = []
    pending_prefix = ""
    ordered_lines = list(lines.values())
    for line_index, words in enumerate(ordered_lines):
        corrected: list[str] = []
        for word_index, row in enumerate(words):
            observed = normalize(row["text"])
            if word_index + 1 < len(words):
                next_observed = words[word_index + 1]["text"]
            elif line_index + 1 < len(ordered_lines) and ordered_lines[line_index + 1]:
                next_observed = ordered_lines[line_index + 1][0]["text"]
            else:
                next_observed = ""
            observed, latin_review = correct_latin_ligature(
                observed,
                next_observed,
                float(row["conf"]),
                latin_wordlist,
            )
            if latin_review:
                latin_review.update(
                    {
                        "left": int(row["left"]),
                        "top": int(row["top"]),
                    }
                )
                review_queue.append(latin_review)
            core = greek_core(observed)
            should_retry = bool(core) or bool(pending_prefix)
            if should_retry:
                left, top, width, height = (
                    int(row["left"]),
                    int(row["top"]),
                    int(row["width"]),
                    int(row["height"]),
                )
                pad = 10
                crop = image.crop(
                    (
                        max(0, left - pad),
                        max(0, top - pad),
                        min(image.width, left + width + pad),
                        min(image.height, top + height + pad),
                    )
                )
                candidate = recognize_greek_word(crop)
                candidate_core = greek_core(candidate)
                if candidate_core in greek_wordlist or (
                    pending_prefix and pending_prefix + candidate_core in greek_wordlist
                ):
                    observed = candidate
                    core = candidate_core

            corrected.append(observed)
            if core and observed.rstrip().endswith("-"):
                pending_prefix = core
            elif pending_prefix:
                pending_prefix = ""
        rendered.append(" ".join(corrected))
    return normalize("\n".join(rendered)), review_queue


def run_case(case: Case) -> dict:
    image = Image.open(download_image(case.image))
    boundaries = detect_boundaries(image)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    crop_path = OUTPUT / f"{case.name}-column-{case.column + 1}.png"
    crop_column(image, case.column, boundaries).save(crop_path)
    text, review_queue = ocr(
        crop_path,
        load_greek_words(),
        load_latin_words(),
    )
    text_path = OUTPUT / f"{case.name}.txt"
    text_path.write_text(text, encoding="utf-8")
    checks = {expected: expected in text for expected in case.expected}
    edition_checks = {
        expected: expected in text for expected in case.edition_expected
    }
    return {
        "name": case.name,
        "image": case.image,
        "column": case.column + 1,
        "boundaries": boundaries,
        "checks": checks,
        "edition_checks": edition_checks,
        "review_queue": review_queue,
        "passed": all(checks.values()),
        "edition_exact": all(edition_checks.values()) if edition_checks else True,
    }


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    # Tesseract occasionally returns an empty TSV when several large
    # multi-language pages compete for memory on a small CI runner.
    rows = [run_case(case) for case in CASES]
    report = {
        "passed": sum(row["passed"] for row in rows),
        "total": len(rows),
        "edition_exact": all(row["edition_exact"] for row in rows),
        "quality_gate": (
            "pass"
            if all(row["passed"] and row["edition_exact"] for row in rows)
            else "blocked"
        ),
        "cases": rows,
    }
    (OUTPUT / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
