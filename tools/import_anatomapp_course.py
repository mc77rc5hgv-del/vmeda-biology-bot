import ast
import json
import re
import hashlib
from pathlib import Path
import argparse

parser = argparse.ArgumentParser(description="Import the pinned Anatomapp content snapshot, without media or user data")
parser.add_argument("source", type=Path, help="Directory containing index.html and the eight source *-data.json files")
parser.add_argument("--output", type=Path, default=Path("services/data/anatomapp_course.json"))
args = parser.parse_args()
src = args.source
html = (src / "index.html").read_text()
values = {}
for key in ["MODULES", "SECTIONS_BY_MODULE", "SUBSECTIONS"]:
    expression = re.search(r"\b" + key + r" = (.*?);", html, re.S).group(1)
    expression = re.sub(r"([,{]\s*)([A-Za-z_][A-Za-z0-9_]*):", r'\1"\2":', expression)
    expression = re.sub(r":true\b", ":True", expression)
    expression = re.sub(r":false\b", ":False", expression)
    values[key] = ast.literal_eval(expression)
files = {
    "m1": ["osteology"],
    "m2": ["syndesmology"],
    "m3": ["myology"],
    "m4": ["splanch"],
    "m6": ["cns", "pns", "sense"],
    "m5": ["angiology"],
}
gates = {
    "m1": "module1_osteology",
    "m2": "module2_syndesmology",
    "m3": "module3_myology",
    "m4": "module4_digestive",
    "m6": "module7_nervous",
    "m5": "module8_cardiovascular",
}
groups = {}
topics = {}
roots = []
hashes = {}
for module in values["MODULES"]:
    mid = module["id"]
    gid = "anatomapp_" + mid
    roots.append(gid)
    entries = []
    for filename in files[mid]:
        path = src / (filename + "-data.json")
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        for entry in json.loads(path.read_text()):
            num = len(entries) + 1
            tid = f"{gid}_{num:03d}"
            topics[tid] = {
                "id": tid,
                "number": num,
                "source_file": path.name,
                "source_num": entry["num"],
                "module_id": gid,
                "group_id": gid,
                "data": entry,
            }
            entries.append(tid)

    def make_group(group_id, title, low, high, parent=None):
        ids = [tid for tid in entries if low <= topics[tid]["number"] <= high]
        sections = [
            {"title": s["name"], "ids": [tid for tid in ids if s["from"] <= topics[tid]["number"] <= s["to"]]}
            for s in values["SECTIONS_BY_MODULE"][mid]
            if low <= s["from"] <= high
        ]
        if [tid for s in sections for tid in s["ids"]] != ids:
            raise ValueError("Source hierarchy does not cover all topics exactly once")
        return {
            "id": group_id,
            "title": title,
            "permission_key": gates[mid],
            "parent_id": parent,
            "ids": ids,
            "sections": sections,
            "subgroups": [],
        }

    groups[gid] = make_group(gid, module["title"], 1, len(entries))
    for i, sub in enumerate(values["SUBSECTIONS"].get(mid, [])):
        child = f"{gid}_{i + 1}"
        groups[child] = make_group(child, sub["name"], sub["from"], sub["to"], gid)
        groups[gid]["subgroups"].append(child)
        for tid in groups[child]["ids"]:
            topics[tid]["group_id"] = child
if len(topics) != 143:
    raise ValueError("Pinned source must contain exactly 143 topics")
out = {
    "source": {
        "repository": "mc77rc5hgv-del/Anatomapp",
        "commit": "e82ab964e01492138edb8361abe0f5fabda2b043",
        "sha256": hashes,
    },
    "roots": roots,
    "groups": groups,
    "topics": topics,
}
args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
print(len(topics), "topics", len(groups), "groups")
