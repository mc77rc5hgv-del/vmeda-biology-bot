import json

path = "/home/user/vmeda-biology-bot/physics_questions.json"
with open(path, encoding="utf-8") as f:
    data = json.load(f)

note = "d — символ производной (математическое обозначение «скорости изменения» или «малого приращения» величины, а не отдельная физическая переменная); например, dv/dt читается как «скорость изменения v по времени»"

target_ids = ["1","6","8","27","42","43","45","62","73","84","85","96","98","153","154","162"]

updated = 0
for k in target_ids:
    ans = data[k]["answer"]
    if "символ производной" in ans:
        continue
    assert "Обозначения:" in ans, f"no Обозначения block in {k}"
    data[k]["answer"] = ans + f"; {note}"
    updated += 1

with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("Updated", updated, "questions")
