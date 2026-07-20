# -*- coding: utf-8 -*-
import json

with open("anatomy.json", "r", encoding="utf-8") as f:
    data = json.load(f)

skull = data["osteology"]["topics"]["skull"]

# ==================== 1. Восстановить утерянную тему "Каналы височной кости" ====================
TEMPORAL_CANALS_CONTENT = (
"<b>Каналы височной кости</b> (продолжение темы «Височная кость — строение»):\n\n"
"• <b>Канал лицевого нерва</b> (<i>canalis nervi facialis</i>) — начинается на дне внутреннего слухового прохода, идёт латерально в толще пирамиды до расщелины канала большого каменистого нерва, где образует изгиб под углом 90° — <b>коленце</b> (<i>geniculum canalis nervi facialis</i>); далее направляется назад, огибает барабанную полость и поворачивает вертикально вниз, заканчиваясь <b>шилососцевидным отверстием</b>. От него отходят канал большого каменистого нерва и каналец барабанной струны. Содержит <b>n. facialis (VII)</b>.\n\n"
"• <b>Канал большого каменистого нерва</b> — начинается от канала лицевого нерва в области коленца, открывается на передней поверхности пирамиды расщелиной большого каменистого нерва. Содержит <b>n. petrosus major</b> (ветвь VII пары).\n\n"
"• <b>Каналец барабанной струны</b> — начинается от канала лицевого нерва чуть выше шилососцевидного отверстия, проходит через барабанную полость, заканчивается в каменисто-барабанной щели. Содержит <b>chorda tympani</b> (ветвь VII пары).\n\n"
"• <b>Барабанный каналец</b> — начинается в каменистой ямочке, проходит через барабанную полость, заканчивается расщелиной малого каменистого нерва. Содержит <b>n. tympanicus</b> (ветвь IX пары).\n\n"
"• <b>Мышечно-трубный канал</b> — соединяет барабанную полость и верхушку пирамиды; перегородкой делится на 2 части: верхнюю (полуканал мышцы, напрягающей барабанную перепонку) и нижнюю (полуканал слуховой трубы).\n\n"
"• <b>Сонный канал</b> (<i>canalis caroticus</i>) — начинается наружной апертурой на нижней поверхности пирамиды, изгибается кпереди под 90°, открывается внутренней апертурой на верхушке пирамиды. Содержит <b>a. carotis interna</b>. От стенок отходят тонкие <b>сонно-барабанные канальцы</b> (обычно два, проникают в барабанную полость).\n\n"
"• <b>Сосцевидный каналец</b> — начинается в ярёмной ямке, перекрещивает канал лицевого нерва, открывается в сосцевидно-барабанную щель. Содержит ушную ветвь <b>n. vagus</b>."
)

material = skull["material"]
if not any(m["id"] == "temporal_canals" for m in material):
    idx = next(i for i, m in enumerate(material) if m["id"] == "temporal_structure")
    material.insert(idx + 1, {
        "id": "temporal_canals",
        "title": "Височная кость — каналы",
        "content": TEMPORAL_CANALS_CONTENT,
    })
skull["material"] = material

# ==================== 2. Список костей и их материал(ы) ====================
BONES_LIST = [
    ("frontal", "Лобная кость"),
    ("parietal", "Теменная кость"),
    ("occipital", "Затылочная кость"),
    ("sphenoid", "Клиновидная кость"),
    ("ethmoid", "Решётчатая кость"),
    ("temporal", "Височная кость"),
    ("mandible", "Нижняя челюсть"),
    ("maxilla", "Верхняя челюсть"),
    ("palatine", "Нёбная кость"),
    ("lacrimal", "Слёзная кость"),
    ("nasal_bone", "Носовая кость"),
    ("inferior_concha", "Нижняя носовая раковина"),
    ("zygomatic_bone", "Скуловая кость"),
    ("vomer_bone", "Сошник"),
    ("hyoid_bone", "Подъязычная кость"),
]
BONE_MATERIAL_IDS = {bone_id: [bone_id] for bone_id, _ in BONES_LIST}
BONE_MATERIAL_IDS["temporal"] = ["temporal_structure", "temporal_canals"]

skull["bones_list"] = [{"id": bid, "title": title} for bid, title in BONES_LIST]
skull["bone_material_ids"] = BONE_MATERIAL_IDS
skull["bone_images"] = {bid: [] for bid, _ in BONES_LIST}

# ==================== 3. Тегируем флэш-карточки по кости ====================
FLASHCARD_BONES = {
    2: "frontal", 3: "occipital", 4: "sphenoid", 5: "temporal", 6: "temporal",
    7: "temporal", 8: "temporal", 9: "temporal", 12: "mandible", 13: "maxilla",
    14: "maxilla", 18: "sphenoid", 19: "sphenoid", 20: "sphenoid", 21: "occipital",
    22: "sphenoid", 23: "sphenoid", 26: "lacrimal", 27: "maxilla", 28: "vomer_bone",
    29: "ethmoid", 30: "ethmoid", 31: "palatine", 32: "palatine", 33: "sphenoid",
    36: "parietal", 37: "sphenoid",
}
for i, fc in enumerate(skull["flashcards"]):
    fc["bone"] = FLASHCARD_BONES.get(i)

NEW_FLASHCARDS = [
    {"front": "Что такое яремный бугорок и где он расположен?", "back": "Возвышение вблизи большого затылочного отверстия, над каналом подъязычного нерва (tuberculum jugulare).", "bone": "occipital"},
    {"front": "Сколько краёв и углов у теменной кости?", "back": "4 края (сагиттальный, лобный, затылочный, чешуйчатый) и 4 угла (лобный, затылочный, клиновидный, сосцевидный).", "bone": "parietal"},
    {"front": "Какими отверстиями начинается и заканчивается канал нижней челюсти?", "back": "Начинается отверстием нижней челюсти на внутренней поверхности ветви, заканчивается подбородочным отверстием на теле.", "bone": "mandible"},
    {"front": "Чем заканчивается книзу задний слёзный гребень слёзной кости?", "back": "Слёзным крючком (hamulus lacrimalis).", "bone": "lacrimal"},
    {"front": "Из чего состоит сошник?", "back": "Пластинка сошника (lamina vomeris) и крылья сошника (alae vomeris), охватывающие клиновидный киль клиновидной кости.", "bone": "vomer_bone"},
    {"front": "С какими костями соединяется носовая кость?", "back": "С лобным отростком верхней челюсти, носовой частью лобной кости и одноимённой костью противоположной стороны.", "bone": "nasal_bone"},
    {"front": "Что пронизывает носовую кость?", "back": "Носовое отверстие (foramen nasale).", "bone": "nasal_bone"},
    {"front": "Чем нижняя носовая раковина отличается от верхней и средней?", "back": "Это самостоятельная кость (верхняя и средняя раковины — части решётчатой кости).", "bone": "inferior_concha"},
    {"front": "Какие 3 отростка есть у нижней носовой раковины?", "back": "Слёзный (кверху, к слёзной кости), верхнечелюстной (вниз, прикрывает вход в верхнечелюстную пазуху), решётчатый (к решётчатой кости).", "bone": "inferior_concha"},
    {"front": "Что образует скуловая кость вместе со скуловыми отростками лобной и височной костей?", "back": "Скуловую дугу (arcus zygomaticus).", "bone": "zygomatic_bone"},
    {"front": "Какие 2 отростка есть у скуловой кости?", "back": "Височный (к скуловому отростку височной кости) и лобный (к скуловому отростку лобной кости).", "bone": "zygomatic_bone"},
    {"front": "Где расположена подъязычная кость?", "back": "В области шеи, между верхним краем щитовидного хряща гортани и нижней челюстью.", "bone": "hyoid_bone"},
    {"front": "Из каких частей состоит подъязычная кость?", "back": "Тело и 2 пары рогов: большие рога (кзади и вверх) и малые рога (у места отхождения больших рогов).", "bone": "hyoid_bone"},
]
skull["flashcards"].extend(NEW_FLASHCARDS)

# ==================== 4. Пары для сопоставления -> формат словарей с тегом bone ====================
SET_PAIR_BONES = {
    "Каналы височной кости и их содержимое": ["temporal"] * 6,
    "Отверстия черепа и нервы, которые через них проходят": ["sphenoid", "sphenoid", "sphenoid", "occipital", "occipital", "sphenoid", "temporal"],
    "Кости и их части": ["temporal", "sphenoid", "occipital", "frontal", "maxilla", "mandible"],
    "Черепные ямки и что в них расположено": [None, None, None],
    "Сообщения глазницы и куда они ведут": [None, None, None, "lacrimal", None],
}
for s in skull["matching_sets"]:
    bones = SET_PAIR_BONES.get(s["title"], [None] * len(s["pairs"]))
    new_pairs = []
    for (term, definition), bone in zip(s["pairs"], bones):
        new_pairs.append({"term": term, "definition": definition, "bone": bone})
    s["pairs"] = new_pairs

skull["matching_sets"].append({
    "title": "Мелкие кости лицевого черепа",
    "pairs": [
        {"term": "Носовая кость", "definition": "образует спинку носа, пронизана носовым отверстием", "bone": "nasal_bone"},
        {"term": "Слёзная кость", "definition": "медиальная стенка глазницы, ямка слёзного мешка", "bone": "lacrimal"},
        {"term": "Нижняя носовая раковина", "definition": "самостоятельная кость, 3 отростка (слёзный, верхнечелюстной, решётчатый)", "bone": "inferior_concha"},
        {"term": "Скуловая кость", "definition": "образует скуловую дугу вместе с височной и лобной костями", "bone": "zygomatic_bone"},
        {"term": "Сошник", "definition": "пластинка и крылья, часть перегородки носа, разделяет хоаны", "bone": "vomer_bone"},
        {"term": "Подъязычная кость", "definition": "тело и 2 пары рогов, не сочленяется напрямую с черепом", "bone": "hyoid_bone"},
    ],
})

# ==================== 5. Мнемоники: тегируем bone (None — общие, для нескольких костей) ====================
MNEMONIC_BONES = {
    "Кости мозгового черепа (6 костей)": None,
    "Черепные нервы через овальное и круглое отверстия": "sphenoid",
    "Содержимое верхней глазничной щели": "sphenoid",
    "Порядок черепных нервов в яремном отверстии": "occipital",
    "Роднички новорождённого по размеру и срокам зарастания": None,
    "Развитие костей черепа: что откуда": None,
    "Первая и вторая жаберные дуги": "temporal",
}
for mn in skull["mnemonics"]:
    mn["bone"] = MNEMONIC_BONES.get(mn["title"])

data["osteology"]["topics"]["skull"] = skull

with open("anatomy.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("material topics:", len(skull["material"]))
print("flashcards:", len(skull["flashcards"]))
print("matching sets:", len(skull["matching_sets"]), "pairs:", sum(len(s["pairs"]) for s in skull["matching_sets"]))
print("mnemonics:", len(skull["mnemonics"]))
print("bones_list:", len(skull["bones_list"]))

# coverage check per bone
from collections import Counter
fc_cov = Counter(fc["bone"] for fc in skull["flashcards"] if fc["bone"])
pair_cov = Counter(p["bone"] for s in skull["matching_sets"] for p in s["pairs"] if p["bone"])
mn_cov = Counter(mn["bone"] for mn in skull["mnemonics"] if mn["bone"])
for bid, title in BONES_LIST:
    print(f"{bid:20s} flash={fc_cov.get(bid,0):2d} pairs={pair_cov.get(bid,0):2d} mnemo={mn_cov.get(bid,0):2d}")
