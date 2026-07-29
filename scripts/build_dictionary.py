#!/usr/bin/env python3
"""Build browser-sized JSON shards from public Internet Archive OCR.

The program preserves article text as found in OCR. It removes only layout noise
(page numbers, repeated running headers and empty lines) and never rewrites prose.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import time
import unicodedata
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

SOURCES = [
    {
        "id": "totiuslatinitati01forc",
        "url": "https://archive.org/stream/totiuslatinitati01forc/totiuslatinitati01forc_djvu.txt",
        "page_url": "https://archive.org/details/totiuslatinitati01forc",
        "volume": "1",
    },
    {
        "id": "totiuslatinitati02forc",
        "url": "https://archive.org/stream/totiuslatinitati02forc/totiuslatinitati02forc_djvu.txt",
        "page_url": "https://archive.org/details/totiuslatinitati02forc",
        "volume": "2",
    },
]
REQUIRED = ("humanitas", "virtus", "natura", "amicitia", "amor", "res")
RUNNING_HEADER = re.compile(
    r"^(?:LEXICON\s+TOTIUS\s+LATINITATIS|TOTIUS\s+LATINITATIS\s+LEXICON|"
    r"FORCELLIN(?:I|US)|AEGIDII\s+FORCELLINI|VOL(?:UMEN)?\.?\s+[IVXLC]+)$",
    re.I,
)
PAGE_NUMBER = re.compile(r"^\s*[-—–]?\s*(?:\d{1,4}|[IVXLC]{1,8})\s*[-—–]?\s*$", re.I)
HEADWORD = re.compile(
    r"^\s*[\[({*†‡]?\s*([A-ZÆŒ][A-Za-zÆŒæœÀ-ÖØ-öø-ÿ'’\-]{1,35})"
    r"(?:\s+(?:s\.|seu|vel)\s+[A-ZÆŒ][A-Za-zÆŒæœÀ-ÖØ-öø-ÿ'’\-]+)?"
    r"\s*(?:,|\.|—|–|-)\s+.{0,150}$"
)
BAD_HEADWORDS = {
    "LEXICON", "LATINITATIS", "FORCELLINI", "FORCELLINUS", "CIC", "PLIN",
    "VIRG", "HOR", "OVID", "LIV", "TER", "TAC", "GELL", "PLAUS", "QUINTIL",
    "ITEM", "HINC", "NOTA", "VIDE", "CAPUT", "LIBER", "VOL", "IBID",
}


@dataclass
class Article:
    lemma: str
    key: str
    text: str
    source: int


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFD", value.casefold())
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    return (
        value.replace("æ", "ae").replace("œ", "oe")
        .replace("j", "i").replace("v", "u")
        .replace("’", "").replace("'", "").replace("-", "")
    )


def clean_line(line: str) -> str | None:
    line = " ".join(line.replace("\ufeff", "").replace("\u00ad", "").split())
    if not line or PAGE_NUMBER.fullmatch(line) or RUNNING_HEADER.fullmatch(line):
        return None
    if len(line) <= 5 and line.isupper() and not any(ch in line for ch in ",."):
        return None
    return line


def headword(line: str) -> str | None:
    match = HEADWORD.match(line)
    if not match:
        return None
    raw = match.group(1).strip("[](){}*†‡.,;: ").replace("’", "'")
    letters = [character for character in raw if character.isalpha()]
    uppercase_ratio = sum(character.isupper() for character in letters) / max(1, len(letters))
    if (
        raw.upper() in BAD_HEADWORDS
        or len(raw) < 2
        or not raw.replace("-", "").replace("'", "").isalpha()
        or uppercase_ratio < 0.72
    ):
        return None
    return raw


def extract_articles(text: str, source: int) -> list[Article]:
    lines = [clean_line(line) for line in text.splitlines()]
    frequency = Counter(line for line in lines if line and len(line) < 70)
    filtered = [line for line in lines if line and frequency[line] < 12]
    starts = [(i, headword(line)) for i, line in enumerate(filtered)]
    starts = [(i, lemma) for i, lemma in starts if lemma]
    articles: list[Article] = []
    for position, (start, lemma) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(filtered)
        body = "\n".join(filtered[start:end]).strip()
        key = normalize(lemma)
        if 2 <= len(key) <= 36 and len(body) >= 45:
            articles.append(Article(lemma.title(), key, body, source))
    return articles


def required_fallback(text: str, source: int, existing: set[str]) -> list[Article]:
    """Extract genuine OCR windows if a damaged heading evaded the general parser."""
    lines = [clean_line(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    found: list[Article] = []
    for wanted in REQUIRED:
        key = normalize(wanted)
        if key in existing:
            continue
        for index, line in enumerate(lines):
            first_token = re.match(r"^\s*[\[({*†‡]?\s*([A-Za-zÆŒæœÀ-ÖØ-öø-ÿ]{2,36})", line)
            if not first_token:
                continue
            observed = normalize(first_token.group(1))
            # In this OCR, capital I is occasionally emitted as lower-case l
            # (for example HUMANlTAS). This affects lookup only, never article text.
            if observed != key and observed.replace("l", "i") != key:
                continue
            end = min(index + 120, len(lines))
            for cursor in range(index + 1, end):
                if headword(lines[cursor]):
                    end = cursor
                    break
            body = "\n".join(lines[index:end]).strip()
            if len(body) >= 45:
                found.append(Article(wanted.title(), key, body, source))
                existing.add(key)
                break
    return found


def download(url: str, destination: Path, attempts: int = 4) -> str:
    if destination.exists() and destination.stat().st_size > 100_000:
        return destination.read_text(encoding="utf-8", errors="replace")
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "Forcellinus-PWA-builder/1.0"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                data = response.read()
            destination.write_bytes(data)
            return data.decode("utf-8", errors="replace")
        except Exception:
            if attempt + 1 == attempts:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("download failed")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def build(output: Path, cache: Path) -> dict:
    texts: list[str] = []
    articles: list[Article] = []
    for source_index, source in enumerate(SOURCES):
        text = download(source["url"], cache / f'{source["id"]}.txt')
        texts.append(text)
        articles.extend(extract_articles(text, source_index))

    # Prefer the longest occurrence where OCR created duplicate headings.
    unique: dict[str, Article] = {}
    for article in articles:
        if article.key not in unique or len(article.text) > len(unique[article.key].text):
            unique[article.key] = article
    for source_index, text in enumerate(texts):
        for article in required_fallback(text, source_index, set(unique)):
            unique.setdefault(article.key, article)

    articles = sorted(unique.values(), key=lambda item: item.key)
    data_dir = output / "data"
    if data_dir.exists():
        shutil.rmtree(data_dir)
    (data_dir / "index").mkdir(parents=True)
    (data_dir / "chunks").mkdir(parents=True)

    groups: dict[str, list[Article]] = defaultdict(list)
    for article in articles:
        groups[(article.key[:2] or "_").ljust(2, "_")].append(article)

    index_groups: dict[str, dict] = {}
    for bucket, items in groups.items():
        index_groups[bucket] = {}
        for chunk_number in range(0, len(items), 50):
            chunk = items[chunk_number:chunk_number + 50]
            filename = f"{bucket}-{chunk_number // 50:03d}.json"
            payload = []
            for article in chunk:
                article_id = hashlib.sha1(
                    f"{article.source}:{article.key}:{article.text[:80]}".encode("utf-8")
                ).hexdigest()[:12]
                payload.append({
                    "id": article_id,
                    "lemma": article.lemma,
                    "key": article.key,
                    "text": article.text,
                    "source": article.source,
                })
                index_groups[bucket][article.key] = {
                    "id": article_id, "lemma": article.lemma, "file": filename
                }
            write_json(data_dir / "chunks" / filename, payload)
        write_json(data_dir / "index" / f"{bucket}.json", index_groups[bucket])

    required_found = [lemma for lemma in REQUIRED if normalize(lemma) in unique]
    # "full" is deliberately conservative: never claim it for a small/partial parse.
    import_status = "full" if len(articles) >= 20_000 and len(required_found) == len(REQUIRED) else "sample"
    metadata = {
        "schema": 1,
        "import_status": import_status,
        "article_count": len(articles),
        "required_found": required_found,
        "generated_from_ocr": True,
        "notice": "Automatyczny tekst OCR; zachowano brzmienie źródła, możliwe błędy rozpoznania.",
        "sources": SOURCES,
    }
    write_json(data_dir / "meta.json", metadata)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("public"))
    parser.add_argument("--cache", type=Path, default=Path(".cache/ocr"))
    args = parser.parse_args()
    build(args.output, args.cache)


if __name__ == "__main__":
    main()
