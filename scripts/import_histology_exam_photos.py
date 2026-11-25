"""Validate and import a reviewed batch of exam micrographs into the shared catalog."""

import argparse
import json
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile

from PIL import Image, ImageCms, ImageOps

from services.histology_content import PHOTO_CATALOG, exam_specimens


IMAGE_ROOT = PHOTO_CATALOG.parent / "images" / "histology"
MAX_SIDE = 3000


def prepare_image(source_dir: Path, filename: str) -> tuple[str, bytes, tuple[int, int]]:
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("expected an image filename")
    relative = Path(filename)
    path = (source_dir / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(source_dir):
        raise ValueError(f"image must be inside the source folder: {filename}")

    with Image.open(path) as original:
        if original.format not in {"JPEG", "PNG", "WEBP", "TIFF"} or getattr(original, "n_frames", 1) != 1:
            raise ValueError(f"expected a single JPEG, PNG, WebP or TIFF image: {filename}")
        image = ImageOps.exif_transpose(original)
        profile = image.info.get("icc_profile")
        if profile and image.mode in {"RGB", "CMYK", "L"}:
            image = ImageCms.profileToProfile(
                image, ImageCms.ImageCmsProfile(BytesIO(profile)), ImageCms.createProfile("sRGB"),
                outputMode="RGB",
            )
        else:
            image = image.convert("RGB")
        image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        image.save(buffer, "JPEG", quality=93, subsampling=0, optimize=True)
        contents = buffer.getvalue()
        if max(image.size) > 20 * min(image.size) or len(contents) > 10_000_000:
            raise ValueError(f"image is outside Telegram photo limits: {filename}")
    return f"_exam_photos/{sha256(contents).hexdigest()}.jpg", contents, image.size


def review_batch(rows: list, source_dir: Path, catalog: dict) -> tuple[dict[str, bytes], list[str]]:
    specimens = exam_specimens()
    existing = {
        photo["file"]: (specimen_id, photo)
        for specimen_id, photos in catalog.items()
        for photo in photos
    }
    claimed = {
        name: photo["file"]
        for _, photo in existing.values()
        for name in (photo["file"], photo.get("quiz_file"))
        if name
    }
    assets = {}
    report = []
    errors = []
    for index, row in enumerate(rows, 1):
        try:
            if not isinstance(row, dict):
                raise ValueError("expected an object")
            specimen_id = row["specimen_id"]
            if not isinstance(specimen_id, str) or specimen_id not in specimens:
                raise ValueError(f"unknown exam specimen: {specimen_id!r}")
            caption = row["caption"]
            if not isinstance(caption, str) or not caption.strip():
                raise ValueError("caption must contain text")
            caption.encode("utf-8")
            quiz = row.get("quiz", False)
            if not isinstance(quiz, (bool, str)):
                raise ValueError("quiz must be true, false, or a reviewed image filename")

            filename = row["file"]
            gallery, contents, size = prepare_image(source_dir, filename)
            photo = {"file": gallery, "caption": caption}
            prepared = {gallery: contents}
            if quiz is True:
                photo["quiz_file"] = gallery
            elif isinstance(quiz, str):
                quiz_image, quiz_contents, _ = prepare_image(source_dir, quiz)
                photo["quiz_file"] = quiz_image
                prepared[quiz_image] = quiz_contents

            if gallery in existing:
                if existing[gallery] != (specimen_id, photo):
                    raise ValueError("image already has a different specimen, caption or quiz variant")
                status = "already imported"
            else:
                if any(name in claimed and claimed[name] != gallery for name in prepared):
                    raise ValueError("image is already assigned to another gallery entry")
                catalog.setdefault(specimen_id, []).append(photo)
                status = "add"

            existing[gallery] = (specimen_id, photo)
            for name, content in prepared.items():
                claimed[name] = gallery
                assets[name] = content
            specimen = specimens[specimen_id]
            mode = "gallery + quiz" if quiz else "gallery only"
            report.append(f"{status}: #{specimen['number']} {specimen['title']} | {filename} | {size[0]}×{size[1]} | {mode}")
        except (KeyError, OSError, ValueError, Image.DecompressionBombError, ImageCms.PyCMSError) as exc:
            errors.append(f"Row {index}: {exc}")
    if errors:
        raise ValueError("\n".join(errors))
    for name, contents in assets.items():
        path = IMAGE_ROOT / name
        if path.exists() and path.read_bytes() != contents:
            raise ValueError(f"existing asset differs from its content hash: {name}")
    return assets, report


def atomic_write(path: Path, data: bytes) -> None:
    with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        staging_path = Path(temporary.name)
        try:
            temporary.write(data)
            temporary.close()
            staging_path.replace(path)
        finally:
            staging_path.unlink(missing_ok=True)


def import_batch(rows: list, source_dir: Path, *, apply: bool) -> list[str]:
    if not isinstance(rows, list) or not rows:
        raise ValueError("manifest must contain a non-empty list of photos")
    source_dir = source_dir.resolve()
    if not apply:
        catalog = json.loads(PHOTO_CATALOG.read_text(encoding="utf-8"))
        return review_batch(rows, source_dir, catalog)[1]
    lock = PHOTO_CATALOG.with_suffix(".lock")
    with lock.open("xb") as handle:
        handle.write(b"Import in progress\n")
    try:
        original = PHOTO_CATALOG.read_text(encoding="utf-8")
        catalog = json.loads(original)
        assets, report = review_batch(rows, source_dir, catalog)
        for name, contents in assets.items():
            path = IMAGE_ROOT / name
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write(path, contents)
        updated = json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
        if updated != original:
            atomic_write(PHOTO_CATALOG, updated.encode("utf-8"))
        return report
    finally:
        lock.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", type=Path, help="UTF-8 JSON with a photos array")
    parser.add_argument("--apply", action="store_true", help="write the verified catalog and images")
    parser.add_argument("--list", action="store_true", help="list existing exam numbers, IDs and titles")
    args = parser.parse_args()
    if args.list:
        for specimen_id, specimen in exam_specimens().items():
            print(f"#{specimen['number']}\t{specimen_id}\t{specimen['title']}\t{specimen.get('stain', '')}")
        return
    if args.manifest is None:
        parser.error("provide a manifest or use --list")
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
        if not isinstance(manifest, dict):
            raise ValueError("expected a JSON object with a photos array")
        report = import_batch(manifest.get("photos"), args.manifest.resolve().parent, apply=args.apply)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    for line in report:
        print(line)
    print("Import complete." if args.apply else "Preview only. Files were not changed.")


if __name__ == "__main__":
    main()
