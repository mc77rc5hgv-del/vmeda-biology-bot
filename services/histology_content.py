"""Read-only presentation of the shared histology bank; no learning/stat writes."""

import json
from functools import lru_cache
from pathlib import Path


PHOTO_CATALOG = Path(__file__).resolve().parents[1] / "histology_exam_photo_catalog.json"


@lru_cache(maxsize=1)
def exam_photo_catalog() -> dict[str, list[dict]]:
    return json.loads(PHOTO_CATALOG.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def exam_specimens() -> dict[str, dict]:
    path = Path(__file__).resolve().parents[1] / "histology_exam_specimens.json"
    entries = json.loads(path.read_text(encoding="utf-8"))["specimens"]
    return {entry["id"]: {**entry, "number": number} for number, entry in enumerate(entries, 1)}


def exam_groups(bank: dict) -> dict:
    """Build the official list in PDF order without renumbering the diagnostics bank."""
    diagnostic_items = {
        specimen["id"]: (group_id, specimen)
        for group_id, group in bank.items()
        for specimen in group["specimens"]
    }
    groups: dict = {}
    photo_catalog = exam_photo_catalog()
    for id_, entry in exam_specimens().items():
        if id_ in diagnostic_items:
            group_id, base = diagnostic_items[id_]
        else:
            group_id, base = entry["group_id"], {}
        if group_id not in groups:
            groups[group_id] = {**bank[group_id], "specimens": []}
        note = (
            "Окраска в карточке указана по экзаменационному перечню. "
            "Отдельные учебные кадры могут отличаться по окраске и увеличению."
        ) if base else ""
        spec = {**base, "magnification": None, "metadata_note": note, **entry}
        if photos := photo_catalog.get(id_):
            images = spec.get("images", [])
            spec["image_guides"] = [
                *(image_guide(spec, index) for index in range(len(images))),
                *({"kind": "micrograph", "exam_caption": photo["caption"]} for photo in photos),
            ]
            spec["images"] = [*images, *(photo["file"] for photo in photos)]
            spec["exam_photos"] = photos
        groups[group_id]["specimens"].append(spec)
    return groups


def quiz_photos(specimen: dict) -> dict[str | None, tuple[str, str]]:
    """Keep the existing quiz photo as the default and index each new one separately."""
    photos = {}
    if legacy_photo := specimen.get("guess_image"):
        photos[None] = (legacy_photo, specimen.get("guess_image_note", ""))
    for photo in specimen.get("exam_photos", []):
        if quiz_file := photo.get("quiz_file"):
            photos[Path(quiz_file).stem] = (quiz_file, photo["caption"])
    return photos


def diagnostic_quiz_photos(specimen: dict) -> dict[str | None, tuple[str, str]]:
    """Reuse reviewed frames by specimen ID while keeping the diagnostic card's content."""
    specimen_id = specimen["id"]
    photos = quiz_photos(specimen) or quiz_photos(exam_specimens().get(specimen_id, {}))
    photos.update(quiz_photos({"exam_photos": exam_photo_catalog().get(specimen_id, [])}))
    return photos


def find_specimen(bank: dict, specimen_id: str) -> tuple[str, dict, dict] | None:
    for group_id, group in bank.items():
        for specimen in group["specimens"]:
            if specimen["id"] == specimen_id:
                return group_id, group, specimen
    return None


def exam_progress(result: dict) -> dict:
    ids = exam_specimens().keys()
    mastered = sorted(ids & result["mastered_ids"])
    mistakes = sorted(ids & result["mistake_ids"])
    return {
        **result,
        "total_specimens": len(ids),
        "mastered_specimens": len(mastered),
        "mastered_ids": mastered,
        "active_mistakes": len(mistakes),
        "mistake_ids": mistakes,
    }


def image_guide(specimen: dict, index: int) -> dict:
    guides = specimen.get("image_guides", [])
    if 0 <= index < len(guides):
        return guides[index]
    return {}


def image_caption(specimen: dict, index: int) -> str:
    guide = image_guide(specimen, index)
    parts = [specimen["title"]]
    if guide.get("kind") == "diagram":
        parts.append("Учебная схема, не микрофотография; не в масштабе.")
    if guide.get("visible"):
        parts.append("Ориентиры: " + guide["visible"])
    if guide.get("note"):
        parts.append("Пояснение: " + guide["note"])
    if guide.get("exam_caption"):
        parts.append("Подпись к экзаменационному фото:\n" + guide["exam_caption"])
    return "\n\n".join(parts)
