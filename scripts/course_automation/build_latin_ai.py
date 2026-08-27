"""Build a private Latin-language RAG corpus from supplied VMEDA materials."""
import asyncio
import hashlib
import json
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

from pypdf import PdfReader
from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import BitmapDecoder
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = REPO_ROOT / ".course-automation" / "latin"
SOURCES = WORKSPACE / "sources"
OUTPUT = REPO_ROOT / "generated_knowledge" / "latin_ai.json"
PDFTOPPM = Path(r"C:\Users\MSI-01\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin\pdftoppm.exe")


def clean_text(value: str) -> str:
    value = value.replace("\u00ad", "").replace("\xa0", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    return re.sub(r"\n{3,}", "\n\n", value).strip()


def chunks(value: str, limit: int = 1400) -> list[str]:
    units = [x.strip() for x in re.split(r"\n{2,}|(?<=[.!?])\s+(?=[А-ЯA-Z])", value) if x.strip()]
    result, current = [], ""
    for unit in units:
        for piece in [unit[i:i + limit] for i in range(0, len(unit), limit)]:
            candidate = f"{current}\n{piece}".strip()
            if current and len(candidate) > limit:
                result.append(current)
                current = piece
            else:
                current = candidate
    if current:
        result.append(current)
    return result


async def ocr_image(path: Path) -> str:
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(path.read_bytes())
    await writer.store_async()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    texts = []
    for language_tag, label in (("ru", "Русское распознавание"), ("en", "Латинское распознавание")):
        engine = OcrEngine.try_create_from_language(Language(language_tag))
        if engine is None:
            raise RuntimeError(f"Windows OCR language is unavailable: {language_tag}")
        text = clean_text((await engine.recognize_async(bitmap)).text)
        if text:
            texts.append(f"{label}:\n{text}")
    return "\n\n".join(texts)


async def extract_pdf(path: Path) -> list[dict]:
    reader = PdfReader(path)
    page_texts = [clean_text(page.extract_text() or "") for page in reader.pages]
    if all(page_texts):
        return [{"locator": f"стр. {i}", "text": text, "method": "text"}
                for i, text in enumerate(page_texts, 1)]
    if not PDFTOPPM.is_file():
        raise FileNotFoundError(PDFTOPPM)
    records = []
    with tempfile.TemporaryDirectory(prefix="vmeda-latin-ocr-") as temp_dir:
        prefix = Path(temp_dir) / "page"
        subprocess.run([str(PDFTOPPM), "-png", "-r", "280", str(path), str(prefix)],
                       check=True, capture_output=True)  # noqa: S603
        images = sorted(Path(temp_dir).glob("page-*.png"))
        if len(images) != len(reader.pages):
            raise RuntimeError(f"Rendered {len(images)} of {len(reader.pages)} pages for {path.name}")
        for index, image in enumerate(images, 1):
            text = page_texts[index - 1] or await ocr_image(image)
            if not text:
                raise RuntimeError(f"OCR returned no text for {path.name}, page {index}")
            records.append({"locator": f"стр. {index}", "text": text, "method": "ocr_ru_en"})
    return records


async def extract_docx_images(path: Path) -> list[dict]:
    records = []
    with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory(prefix="vmeda-latin-docx-") as temp_dir:
        names = sorted(name for name in archive.namelist()
                       if name.startswith("word/media/") and Path(name).suffix.lower() in {".png", ".jpg", ".jpeg"})
        for index, name in enumerate(names, 1):
            target = Path(temp_dir) / Path(name).name
            target.write_bytes(archive.read(name))
            text = await ocr_image(target)
            if not text:
                raise RuntimeError(f"OCR returned no text for {path.name}, image {index}")
            records.append({"locator": f"изображение {index}", "text": text, "method": "ocr_ru_en"})
    return records


async def build() -> dict:
    paths = sorted(SOURCES.iterdir())
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    entries, files = [], []
    for path in paths:
        if path.name == "Словарь Л-Р (2).docx" and hashes[path.name] == hashes.get("Словарь Л-Р.docx"):
            files.append({"file": path.name, "sha256": hashes[path.name], "status": "duplicate",
                          "same_as": "Словарь Л-Р.docx"})
            continue
        units = await (extract_pdf(path) if path.suffix.lower() == ".pdf" else extract_docx_images(path))
        for unit in units:
            for part, text in enumerate(chunks(unit["text"]), 1):
                entries.append({"subject": "латинский язык",
                                "title": f"{path.stem}, {unit['locator']}, фрагмент {part}",
                                "text": text, "source": path.name, "locator": unit["locator"],
                                "method": unit["method"]})
        files.append({"file": path.name, "sha256": hashes[path.name], "status": "processed",
                      "units": len(units), "characters": sum(len(unit["text"]) for unit in units)})
    if not entries:
        raise RuntimeError("Latin AI corpus is empty")
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps({"subject": "latin", "visibility": "ai_only", "entries": entries},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {"subject": "Латинский язык", "mode": "credit_placeholder_with_ai",
                "files": files, "entries": len(entries)}
    (WORKSPACE / "source_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                                     encoding="utf-8")
    return manifest


if __name__ == "__main__":
    print(json.dumps(asyncio.run(build()), ensure_ascii=False))
