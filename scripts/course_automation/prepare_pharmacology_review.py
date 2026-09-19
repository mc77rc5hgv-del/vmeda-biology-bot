"""Inventory original pharmacology files and stage every practicum page for review.

Outputs are review artifacts, never live course data or user state.
"""
import argparse
import hashlib
import json
from pathlib import Path

import pymupdf
from docx import Document

REPO = Path(__file__).resolve().parents[2]


def prepare(sources: Path, extracted: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    files, seen = [], {}
    for source in sorted(sources.iterdir(), key=lambda p: p.name.casefold()):
        if source.suffix.lower() not in {".pdf", ".doc", ".docx"}:
            continue
        with source.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        item = {"file": source.name, "sha256": digest, "bytes": source.stat().st_size}
        if digest in seen:
            item.update(status="duplicate", same_as=seen[digest])
            files.append(item)
            continue
        seen[digest] = source.name
        try:
            if source.suffix.lower() == ".pdf":
                with pymupdf.open(source) as doc:
                    pages = [{"page": i + 1, "text": page.get_text(),
                              "images": len(page.get_images())} for i, page in enumerate(doc)]
                item.update(pages=len(pages), weak_text_pages=sum(len(p["text"].strip()) < 80 for p in pages))
                (output / (source.name + ".text.json")).write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
                item["status"] = "needs_ocr_review" if item["weak_text_pages"] else "text_extracted_needs_review"
            elif source.suffix.lower() == ".docx":
                doc = Document(source)
                blocks = []
                for index, block in enumerate(doc.iter_inner_content()):
                    if hasattr(block, "text"):
                        blocks.append({"block": index, "kind": "paragraph", "text": block.text})
                    else:
                        blocks.append({"block": index, "kind": "table", "rows": [[c.text for c in r.cells] for r in block.rows]})
                (output / (source.name + ".text.json")).write_text(json.dumps(blocks, ensure_ascii=False), encoding="utf-8")
                item.update(status="text_extracted_needs_review", blocks=len(blocks), images=len(doc.inline_shapes))
            else:
                item["status"] = "legacy_doc_requires_conversion"
        except Exception as exc:
            item.update(status="extraction_failed", error=str(exc))
        files.append(item)
    curriculum = json.loads((REPO / "course_sources/pharmacology/curriculum.json").read_text(encoding="utf-8"))
    practicum = next(f for f in files if f["file"] == curriculum["source"]["file"])
    if practicum["sha256"] != curriculum["source"]["sha256"]:
        raise ValueError("Practicum changed: recheck the curriculum against this edition")
    ocr = json.loads((extracted / (practicum["file"] + ".ocr.json")).read_text(encoding="utf-8"))
    page_numbers = [p["page"] for p in ocr]
    if sorted(page_numbers) != list(range(1, practicum["pages"] + 1)):
        raise ValueError("OCR page coverage is incomplete or duplicated")
    review_pages = [{"pdf_page": p["page"], "text": p["text"], "status": "needs_image_review",
                     "source_sha256": practicum["sha256"]} for p in ocr]
    (output / "practicum_review.json").write_text(json.dumps(review_pages, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {"subject": "pharmacology", "files": files,
              "source_count": len(files), "practicum_pages_staged": len(review_pages),
              "modules": len(curriculum["modules"]),
              "classes": sum(len(m["lessons"]) for m in curriculum["modules"]),
              "publication_ready": False,
              "blockers": ["Scan text and drug doses require visual review", "Map source answers to the 49 classes", "Verify assessment keys"]}
    (output / "review_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("sources", type=Path)
    parser.add_argument("extracted", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = prepare(args.sources, args.extracted, args.output)
    print(json.dumps({k: v for k, v in result.items() if k != "files"}, ensure_ascii=False))
