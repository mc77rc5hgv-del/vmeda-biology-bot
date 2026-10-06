"""Read-only presentation of the shared histology bank; no learning/stat writes."""


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
    return "\n\n".join(parts)
