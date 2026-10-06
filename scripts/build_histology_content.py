"""Build the shared bank from reviewed text and image guides. No runtime data access.

Run from any directory with Python's standard library; writes only histology.json.
Stable specimen IDs, order, titles and guess_image assignments are preserved.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    bank_path = ROOT / "histology.json"
    bank = json.loads(bank_path.read_text())
    text = (ROOT / "docs/histology_protocols.md").read_text()
    protocols = dict(re.findall(r"^## (d\d_\d+)\n(.*?)(?=^## |\Z)", text, re.M | re.S))
    media = json.loads((ROOT / "docs/histology_image_guides.json").read_text())
    refs = json.loads((ROOT / "docs/histology_sources.json").read_text())
    specimens = [s for g in bank.values() for s in g["specimens"]]
    require(len(specimens) == len(protocols) == len(media) == 71, "Expected all 71 specimens")
    require(set(protocols) == set(media) == {s["id"] for s in specimens}, "Mismatched specimen IDs")
    stable_before = [(s["id"], s["number"], s["title"], s.get("guess_image")) for s in specimens]
    for spec in specimens:
        sid = spec["id"]
        spec["protocol"] = protocols[sid].strip()
        spec["metadata_note"] = (
            "Окраска и увеличение относятся к исходному препарату. "
            "Отдельные кадры и схемы могут иметь другой масштаб и метод; см. пояснение к кадру."
        )
        entries = media[sid]["active"]
        require(bool(entries), f"No active images: {sid}")
        require(all((ROOT / "images/histology" / e["path"]).is_file() for e in entries),
                f"Missing image: {sid}")
        spec["images"] = [e["path"] for e in entries]
        spec["image_guides"] = [{k: e[k] for k in ("kind", "visible", "note")} for e in entries]
        spec["sources"] = [dict(title=r["title"], url=r["url"]) for r in refs
                           if r["id"] == "S01" or sid in r["specimens"]]
    require(stable_before == [(s["id"], s["number"], s["title"], s.get("guess_image")) for s in specimens],
            "Specimen IDs, titles or quiz assignments changed")
    bank_path.write_text(json.dumps(bank, ensure_ascii=False, indent=2) + "\n")
    print(f"Built {len(specimens)} protocols; {sum(len(s['images']) for s in specimens)} images/guides; stable IDs and quiz assignments preserved")


if __name__ == "__main__":
    main()
