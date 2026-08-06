"""Extract the bot's study content from anatomapp.ru's index.html.

The site ships all 143 topics inline as `window.__ANATOM_DATA` (a ~6MB line) and installs a
fetch() shim so its own `fetch("osteology-data.json")` calls resolve from that object — which is
why those .json paths 404 when requested directly from the server.

Run after the site's content changes:
    python3 scripts/extract_content.py path/to/index.html content.json

Topic numbering must stay byte-identical to the site's, because progress keys ("<moduleId>:<num>")
are shared between the bot and the website. The site builds module m6 by concatenating three
datasets and shifting their numbers (see its componentDidMount), which SHIFTS below mirrors.
`theory` is dropped: it is the bulk of the payload and the bot links to the site for reading.
"""

import json
import re
import sys

# dataset file -> (module id, number offset applied by the site)
SHIFTS = [
    ("osteology-data.json", "m1", 0),
    ("syndesmology-data.json", "m2", 0),
    ("myology-data.json", "m3", 0),
    ("splanch-data.json", "m4", 0),
    ("angiology-data.json", "m5", 0),
    ("cns-data.json", "m6", 0),
    ("pns-data.json", "m6", 15),
    ("sense-data.json", "m6", 26),
]

KEEP = ("cards", "pairs", "tests")


def extract(html_path: str) -> dict:
    raw = None
    with open(html_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if "__ANATOM_DATA" in line:
                raw = line
                break
    if raw is None:
        raise SystemExit("window.__ANATOM_DATA not found in " + html_path)

    match = re.search(r"window\.__ANATOM_DATA\s*=\s*", raw)
    data, _ = json.JSONDecoder().raw_decode(raw, match.end())

    modules: dict[str, list] = {}
    for filename, module_id, offset in SHIFTS:
        for topic in data.get(filename, []):
            entry = {"num": topic["num"] + offset, "name": topic.get("name", "")}
            if topic.get("lat"):
                entry["lat"] = topic["lat"]
            for key in KEEP:
                if topic.get(key):
                    entry[key] = topic[key]
            modules.setdefault(module_id, []).append(entry)

    for topics in modules.values():
        topics.sort(key=lambda t: t["num"])
    return modules


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "index.html"
    dst = sys.argv[2] if len(sys.argv) > 2 else "content.json"
    result = extract(src)
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, separators=(",", ":"))
    for module_id, topics in sorted(result.items()):
        cards = sum(len(t.get("cards", [])) for t in topics)
        pairs = sum(len(t.get("pairs", [])) for t in topics)
        tests = sum(len(t.get("tests", [])) for t in topics)
        print(f"{module_id}: {len(topics):3d} topics | {cards:5d} cards | {pairs:5d} pairs | {tests:5d} tests")
