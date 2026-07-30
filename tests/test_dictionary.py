#!/usr/bin/env python3
import json
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "public" / "data"
REQUIRED = ("humanitas", "virtus", "natura", "amicitia", "amor", "res", "ratio")


def normalize(value):
    value = "".join(
        ch for ch in unicodedata.normalize("NFD", value.casefold())
        if unicodedata.category(ch) != "Mn"
    )
    return value.replace("æ", "ae").replace("œ", "oe").replace("j", "i").replace("v", "u")


def check(lemma):
    key = normalize(lemma)
    bucket = key[:2].ljust(2, "_")
    index = json.loads((DATA / "index" / f"{bucket}.json").read_text(encoding="utf-8"))
    ref = index.get(key)
    assert ref, f"Brak lematu {lemma} w indeksie"
    chunk = json.loads((DATA / "chunks" / ref["file"]).read_text(encoding="utf-8"))
    article = next((item for item in chunk if item["id"] == ref["id"]), None)
    assert article, f"Brak artykułu {lemma} w pliku {ref['file']}"
    assert len(article["text"]) >= 45, f"Podejrzanie krótki artykuł {lemma}"
    assert article["key"] == key
    return len(article["text"])


meta = json.loads((DATA / "meta.json").read_text(encoding="utf-8"))
assert meta["generated_from_ocr"] is True
assert meta["article_count"] > 0
for required in REQUIRED:
    print(f"OK {required}: {check(required)} znaków OCR")
if "grc" in meta.get("ocr_languages", []):
    ratio_key = normalize("ratio")
    ratio_index = json.loads((DATA / "index" / "ra.json").read_text(encoding="utf-8"))
    ratio_ref = ratio_index[ratio_key]
    ratio_chunk = json.loads(
        (DATA / "chunks" / ratio_ref["file"]).read_text(encoding="utf-8")
    )
    ratio = next(item for item in ratio_chunk if item["id"] == ratio_ref["id"])
    assert "νοῦς" in ratio["text"], "OCR hasła ratio utracił greckie νοῦς"
    assert "λόγος" in ratio["text"], "OCR hasła ratio utracił greckie λόγος"
    assert any("\u0370" <= character <= "\u03ff" for character in ratio["text"])
    print("OK greka w ratio: νοῦς, λόγος")
print(f"Import: {meta['import_status']}; artykułów: {meta['article_count']}")
sys.exit(0)
