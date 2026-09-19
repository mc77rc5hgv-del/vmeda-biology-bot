"""Read-only source inventory and review extraction; never writes runtime course/state."""
import argparse
import hashlib
import json
from pathlib import Path

import pymupdf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with args.source.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    with pymupdf.open(args.source) as doc:
        pages = [{"page": i + 1, "text": page.get_text()} for i, page in enumerate(doc)]
        report = {"file": args.source.name, "sha256": digest, "pages": len(doc),
                  "text_pages": sum(len(p["text"].strip()) > 80 for p in pages)}
        (args.output / "native_text.json").write_text(json.dumps(pages, ensure_ascii=False, indent=2), encoding="utf-8")
        (args.output / "source_manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        for i in [1, 2, *range(max(0, len(doc)-4), len(doc))]:
            doc[i].get_pixmap(matrix=pymupdf.Matrix(0.7, 0.7)).save(args.output / f"page_{i+1}.png")
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
