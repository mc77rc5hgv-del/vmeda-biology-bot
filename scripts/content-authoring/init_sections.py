# -*- coding: utf-8 -*-
import json

with open("anatomy.json", "r", encoding="utf-8") as f:
    data = json.load(f)

data["osteology"]["menu_title"] = "🦴 Остеология (кости)"
data["osteology"]["topics"]["skull"]["menu_title"] = "💀 Череп"
data["osteology"]["topics"]["skull"]["icon"] = "💀"

data["arthrology"] = {
    "title": "Соединения костей (Артросиндесмология)",
    "menu_title": "🔗 Соединения костей",
    "topics": {}
}

data["myology"] = {
    "title": "Мышечная система (Миология)",
    "menu_title": "💪 Мышечная система",
    "topics": {}
}

with open("anatomy.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("sections:", list(data.keys()))
