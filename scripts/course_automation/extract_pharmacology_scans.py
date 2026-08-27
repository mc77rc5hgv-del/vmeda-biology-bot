"""OCR scanned pharmacology PDFs and retain the visual table atlas."""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from pypdf import PdfReader
from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import BitmapDecoder
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream


def clean(value: str) -> str:
    value = value.replace("\u00ad", "").replace("\u00a0", " ")
    value = re.sub(r"[ \t]+", " ", value)
    return re.sub(r"\n{3,}", "\n\n", value).strip()


async def ocr_bytes(data: bytes) -> str:
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(data)
    await writer.store_async()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    engine = OcrEngine.try_create_from_language(Language("ru"))
    return clean((await engine.recognize_async(bitmap)).text)


async def process(source: Path, output: Path, asset_dir: Path | None = None) -> list[dict]:
    page_count = len(PdfReader(source).pages)
    records = []
    if asset_dir:
        asset_dir.mkdir(parents=True, exist_ok=True)
    pdftoppm = Path(r"C:\Users\MSI-01\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin\pdftoppm.exe")
    with tempfile.TemporaryDirectory(prefix="vmeda-pharma-ocr-") as temp_dir:
        prefix = Path(temp_dir) / "page"
        subprocess.run([str(pdftoppm), "-jpeg", "-r", "120", str(source), str(prefix)], check=True)
        images = sorted(Path(temp_dir).glob("page-*.jpg"))
        if len(images) != page_count:
            raise RuntimeError(f"Rendered {len(images)} of {page_count} pages: {source.name}")
        for index, image in enumerate(images, 1):
            text = await ocr_bytes(image.read_bytes())
            record = {"page": index, "text": text, "method": "ocr_ru"}
            if asset_dir:
                target = asset_dir / f"table_{index:03d}.jpg"
                target.write_bytes(image.read_bytes())
                record["media"] = f"generated_assets/pharmacology/{target.name}"
            records.append(record)
            if index % 25 == 0:
                print(f"{source.name}: {index}/{page_count}", flush=True)
    output.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    return records


async def main(repo: Path) -> None:
    workspace = repo / ".course-automation" / "pharmacology"
    sources = workspace / "sources"
    extracted = workspace / "extracted"
    extracted.mkdir(parents=True, exist_ok=True)
    assets = repo / "generated_assets" / "pharmacology"
    tasks = [
        ("Занятие Nº 14.pdf", None),
        ("Фарма все таблицы.pdf", assets),
        ("Фармакология практикум.pdf", None),
    ]
    for filename, asset_dir in tasks:
        output = extracted / f"{filename}.ocr.json"
        if output.exists():
            continue
        await process(sources / filename, output, asset_dir)


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]).resolve()))
