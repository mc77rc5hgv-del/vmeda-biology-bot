# -*- coding: utf-8 -*-
import json

with open("anatomy.json", "r", encoding="utf-8") as f:
    data = json.load(f)

D = "━━━━━━━━━━━━━━"

# ---- Fix 1: general_myology / muscle_forms_and_auxiliary ----
material = data["myology"]["topics"]["general_myology"]["material"]
old = material[1]
assert old["id"] == "muscle_forms_and_auxiliary"
full = old["content"]
split_marker = f"{D}\n\n<b>Вспомогательный аппарат мышц</b>"
idx = full.index(split_marker)
part1 = full[:idx].rstrip()
part2 = full[idx + len(D) + 2:].lstrip()

new1 = {"id": "muscle_forms_classification", "title": "Формы и классификация мышц", "content": part1}
new2 = {"id": "muscle_auxiliary_apparatus", "title": "Вспомогательный аппарат, сила мышц", "content": part2}
material[1:2] = [new1, new2]

# ---- Fix 2: lower_limb_muscles / lower_limb_topography_supply ----
material2 = data["myology"]["topics"]["lower_limb_muscles"]["material"]
old2 = material2[7]
assert old2["id"] == "lower_limb_topography_supply"
full2 = old2["content"]
split_marker2 = f"{D}\n\n<b>Кровоснабжение и иннервация мышц нижней конечности"
idx2 = full2.index(split_marker2)
part1b = full2[:idx2].rstrip()
part2b = full2[idx2 + len(D) + 2:].lstrip()

new1b = {"id": "lower_limb_topography", "title": "Топография нижней конечности", "content": part1b}
new2b = {"id": "lower_limb_blood_nerve_supply", "title": "Кровоснабжение и иннервация мышц нижней конечности", "content": part2b}
material2[7:8] = [new1b, new2b]

with open("anatomy.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

for tk in ("general_myology",):
    tp = data["myology"]["topics"][tk]
    print(tk, len(tp["material"]), "pages")
    for m in tp["material"]:
        print(f"  {m['id']}: {len(m['content'])} chars")

tp = data["myology"]["topics"]["lower_limb_muscles"]
print("lower_limb_muscles", len(tp["material"]), "pages")
for m in tp["material"]:
    print(f"  {m['id']}: {len(m['content'])} chars")
