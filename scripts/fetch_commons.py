#!/usr/bin/env python3
"""Download files from Wikimedia Commons and save them as JPEGs under images/.

Usage: python3 scripts/fetch_commons.py <spec_file.json>
spec_file.json: list of {"commons": "File name.svg", "out": "category/name.jpg", "width": 1000}
"""
import json
import os
import sys
import subprocess
from io import BytesIO
from urllib.parse import quote

from PIL import Image
import cairosvg

IMAGES_DIR = "images"
MAX_W = 1280


def fetch(commons_name: str) -> bytes:
    url = "https://commons.wikimedia.org/wiki/Special:FilePath/" + quote(commons_name)
    result = subprocess.run(
        ["curl", "-sSL", "--max-time", "30", "-A", "vmeda-biology-bot/1.0", url],
        capture_output=True,
    )
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError(f"download failed for {commons_name}: rc={result.returncode}")
    return result.stdout


def save_as_jpeg(data: bytes, out_path: str, width: int = 1100):
    if data[:5] == b"<?xml" or b"<svg" in data[:400]:
        png_bytes = cairosvg.svg2png(bytestring=data, output_width=width)
        img = Image.open(BytesIO(png_bytes))
    else:
        img = Image.open(BytesIO(data))
    if img.mode in ("RGBA", "P", "LA"):
        bg = Image.new("RGB", img.size, "white")
        img = img.convert("RGBA")
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    if img.width > MAX_W:
        ratio = MAX_W / img.width
        img = img.resize((MAX_W, int(img.height * ratio)))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path, "JPEG", quality=85, optimize=True)


def main():
    spec_path = sys.argv[1]
    with open(spec_path, encoding="utf-8") as f:
        specs = json.load(f)
    for spec in specs:
        commons_name = spec["commons"]
        out_path = os.path.join(IMAGES_DIR, spec["out"])
        width = spec.get("width", 1100)
        try:
            data = fetch(commons_name)
            save_as_jpeg(data, out_path, width)
            size = os.path.getsize(out_path)
            print(f"OK   {commons_name} -> {out_path} ({size} bytes)")
        except Exception as e:
            print(f"FAIL {commons_name}: {e}")


if __name__ == "__main__":
    main()
