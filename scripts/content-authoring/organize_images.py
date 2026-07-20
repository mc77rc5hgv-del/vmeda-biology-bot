# -*- coding: utf-8 -*-
import json, os, shutil

SRC = "/tmp/claude-0/-home-user-vmeda-biology-bot/d28eaeb6-ad1f-5436-88a0-95ec7597ae8d/scratchpad/pdf_pages"
DST_ROOT = "/home/user/vmeda-biology-bot/images/anatomy"

def src(pdf, page):
    return os.path.join(SRC, f"{pdf}-{page:02d}.jpg")

# ==================== ROUTING MAPS ====================
# Each entry: (topic_key, bone_id, [(pdf, page, caption), ...])

CAPTION_SOURCE = "ВМедА, кафедра нормальной анатомии — учебная презентация"

# ---- PDF01: Кости туловища (Практическое занятие №1) ----
PDF01_ROUTES = {
    "general": [(1, "Кости туловища — общий обзор"), (2, "Плоскости тела"), (3, "Плоскости тела"),
                (4, "Кость, os — общее определение"), (5, "Строение костной ткани"),
                (6, "Классификация костей туловища и конечностей"), (7, "Классификация костей по расположению")],
    "columna_vertebralis": [(8, "Позвоночный столб, columna vertebralis"), (21, "Позвоночный столб — изгибы")],
    "vertebra_general": [(9, "Свободные позвонки — сравнение"), (10, "Позвонок, vertebra — общее строение"),
                          (11, "Положение суставных отростков позвонков"), (19, "Рёберные элементы и добавочные рёбра")],
    "cervical_vertebra": [(12, "Шейные позвонки, vertebrae cervicales"), (13, "Шейные позвонки, vertebrae cervicales")],
    "atlas_axis": [(14, "Атипичные позвонки — атлант и осевой"), (15, "Атлант, atlas"), (16, "Осевой позвонок, axis")],
    "thoracic_vertebra": [(17, "Грудные позвонки, vertebrae thoracicae")],
    "lumbar_vertebra": [(18, "Поясничные позвонки, vertebrae lumbales")],
    "sacrum_coccyx": [(20, "Сросшиеся позвонки — крестец и копчик")],
    "ribs": [(22, "Грудная клетка, thorax"), (23, "Рёбра, costae — классификация"),
             (24, "Рёбра, costae — части"), (25, "Соотношение строения рёбер и позвонков"), (26, "I ребро, costa prima")],
    "sternum": [(27, "Грудина, sternum")],
}

# ---- PDF02: Затылочная, теменная, лобная, решётчатая, клиновидная кости ----
PDF02_ROUTES_SKULL_GENERAL = [(1, "Череп — общий обзор"), (2, "Классификация костей по расположению"),
                               (3, "Череп, cranium")]
PDF02_ROUTES_SKULL_WHOLE = [(4, "Мозговой череп, neurocranium"), (5, "Классификация костей черепа по строению"),
                             (6, "Крыша черепа, calvaria"), (7, "Диплоические и эмиссарные вены"),
                             (8, "Ямочки грануляций, foveolae granulares")]
PDF02_ROUTES = {
    "occipital": [(9, "Затылочная кость, os occipitale"), (10, "Затылочная кость — внутренний рельеф"),
                  (11, "Затылочная кость — foramen magnum, каналы")],
    "parietal": [(12, "Теменная кость, os parietale"), (13, "Теменная кость — борозда менингеальной артерии")],
    "frontal": [(14, "Лобная кость, os frontale")],
    "ethmoid": [(15, "Решётчатая кость, os ethmoidale"), (16, "Решётчатая кость — носовые раковины")],
    "sphenoid": [(17, "Клиновидная кость, os sphenoidale"), (18, "Клиновидная кость — нёбный/крыловидный вид"),
                 (19, "Клиновидная кость — глазничный вид"), (20, "Клиновидная кость — содержимое турецкого седла"),
                 (21, "Клиновидная кость — внутренний вид")],
}

# ---- PDF03: Височная кость. Кости лицевого черепа ----
PDF03_ROUTES_SKULL_GENERAL = [(1, "Височная кость и кости лицевого черепа — обзор"),
                               (16, "Классификация костей по расположению"),
                               (17, "Классификация костей черепа по строению"),
                               (18, "Альвеолярные образования челюстей")]
PDF03_ROUTES = {
    "temporal": [(2, "Височная кость, os temporale — части"), (3, "Височная кость — 3D вид"),
                 (4, "Височная кость — базальный и внутренний вид"), (5, "Распил височной кости"),
                 (6, "Височная кость — распил"), (7, "Каналы височной кости"),
                 (8, "Сонный канал, canalis caroticus"), (9, "Мышечно-трубный канал, canalis musculotubarius"),
                 (10, "Канал лицевого нерва"), (11, "Канал лицевого нерва — вид сверху"),
                 (12, "Барабанный каналец, canaliculus tympanicus"), (13, "Сосцевидный каналец, canaliculus mastoideus"),
                 (14, "Каналы височной кости — сводная схема"), (15, "Каналы, связанные с внутренним ухом")],
    "mandible": [(19, "Нижняя челюсть, mandibula"), (20, "Нижняя челюсть — вид снизу/сзади"),
                 (21, "Нижняя челюсть — канал нижней челюсти"), (22, "Возрастные изменения нижней челюсти")],
    "maxilla": [(23, "Верхняя челюсть, maxilla"), (24, "Верхняя челюсть — внутренний вид")],
    "palatine": [(25, "Нёбная кость, os palatinum")],
    "inferior_concha": [(26, "Компактные кости лицевого черепа — нижняя носовая раковина и сошник")],
    "vomer_bone": [(26, "Компактные кости лицевого черепа — нижняя носовая раковина и сошник")],
    "lacrimal": [(27, "Компактные кости лицевого черепа — слёзная и носовая кости")],
    "nasal_bone": [(27, "Компактные кости лицевого черепа — слёзная и носовая кости")],
    "zygomatic_bone": [(28, "Компактные кости лицевого черепа — скуловая кость")],
    "hyoid_bone": [(29, "Подъязычная кость, os hyoideum")],
}

# ---- PDF04: Череп в целом ----
PDF04_ROUTES_SKULL_GENERAL = [(1, "Череп в целом — обзор"), (2, "Кости черепа по развитию"),
                               (3, "Cranium — лицевой и мозговой отделы")]
PDF04_ROUTES_SKULL_WHOLE = [
    (4, "Fossa temporalis"), (5, "Fossa infratemporalis"), (6, "Fossa pterygopalatina"), (7, "Basis cranii"),
    (8, "Fossa cranii anterior"), (9, "Fossa cranii media"), (10, "Fossa cranii posterior"),
    (11, "Palatum osseum"), (12, "Cavitas nasi osseum"), (13, "Cavitas nasi osseum — латеральная стенка"),
    (14, "Cavitas nasi osseum — латеральная стенка"), (15, "Cavitas nasi osseum — сосуды и нервы"),
    (16, "Sinus paranasales"), (17, "Orbita"), (18, "Фронтальный распил черепа"),
]

# ---- PDF05: Кости верхней конечности ----
PDF05_ROUTES_UPPER_GENERAL = [(1, "Кости верхней конечности — обзор"), (2, "Классификация костей по расположению"),
                               (3, "Плоскости и термины положения"), (4, "Верхняя конечность — классификация отделов")]
PDF05_ROUTES = {
    "scapula": [(5, "Лопатка, scapula")],
    "clavicle": [(6, "Ключица, clavicula")],
    "humerus": [(7, "Плечевая кость, humerus"), (11, "Плечевая кость и кости предплечья — локтевой сустав")],
    "ulna": [(8, "Локтевая кость, ulna"), (10, "Кости предплечья, ossa antebrachii"),
             (11, "Плечевая кость и кости предплечья — локтевой сустав")],
    "radius": [(9, "Лучевая кость, radius"), (10, "Кости предплечья, ossa antebrachii"),
               (11, "Плечевая кость и кости предплечья — локтевой сустав")],
    "hand_bones": [(12, "Кости кисти, ossa manus"), (13, "Ossa carpi — обзор"),
                   (14, "Ossa carpi — проксимальный ряд"), (15, "Ossa carpi — дистальный ряд"),
                   (16, "Кости пясти, ossa metacarpi"), (17, "Фаланги пальцев кисти")],
}

# ==================== ЗАГРУЗКА anatomy.json ====================
with open("/home/user/vmeda-biology-bot/anatomy.json", "r", encoding="utf-8") as f:
    data = json.load(f)

def new_topic(title, icon):
    return {
        "title": title,
        "icon": icon,
        "menu_title": f"{icon} {title}",
        "material": [],
        "flashcards": [],
        "matching_sets": [],
        "mnemonics": [],
        "picture_quiz": [],
        "bones_list": [],
        "bone_material_ids": {},
        "bone_images": {},
    }

if "trunk_bones" not in data["osteology"]["topics"]:
    data["osteology"]["topics"]["trunk_bones"] = new_topic("Кости туловища", "🦴")
if "upper_limb_bones" not in data["osteology"]["topics"]:
    data["osteology"]["topics"]["upper_limb_bones"] = new_topic("Кости верхней конечности", "💪")

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def copy_and_register(topic_key, bone_id, entries, section_key="osteology"):
    """entries: list of (pdf_tag, page, caption) tuples"""
    topic = data[section_key]["topics"][topic_key]
    if "bone_images" not in topic:
        topic["bone_images"] = {}
    if bone_id not in topic["bone_images"]:
        topic["bone_images"][bone_id] = []
    dest_dir = os.path.join(DST_ROOT, topic_key, bone_id)
    ensure_dir(dest_dir)
    for i, (pdf_tag, page, caption) in enumerate(entries):
        source_path = src(pdf_tag, page)
        if not os.path.exists(source_path):
            raise FileNotFoundError(source_path)
        filename = f"{pdf_tag}-{page:02d}.jpg"
        dest_path = os.path.join(dest_dir, filename)
        shutil.copyfile(source_path, dest_path)
        rel_path = f"{topic_key}/{bone_id}/{filename}"
        topic["bone_images"][bone_id].append({
            "path": rel_path,
            "caption": caption,
            "credit": CAPTION_SOURCE,
        })

# ---- PDF01 -> trunk_bones (new topic) ----
for bone_id, pages in PDF01_ROUTES.items():
    entries = [("pdf01", p, cap) for p, cap in pages]
    copy_and_register("trunk_bones", bone_id, entries)

# ---- PDF02 -> skull (existing topic) ----
copy_and_register("skull", "general", [("pdf02", p, cap) for p, cap in PDF02_ROUTES_SKULL_GENERAL])
copy_and_register("skull", "whole_skull", [("pdf02", p, cap) for p, cap in PDF02_ROUTES_SKULL_WHOLE])
for bone_id, pages in PDF02_ROUTES.items():
    entries = [("pdf02", p, cap) for p, cap in pages]
    copy_and_register("skull", bone_id, entries)

# ---- PDF03 -> skull (existing topic) ----
copy_and_register("skull", "general", [("pdf03", p, cap) for p, cap in PDF03_ROUTES_SKULL_GENERAL])
for bone_id, pages in PDF03_ROUTES.items():
    entries = [("pdf03", p, cap) for p, cap in pages]
    copy_and_register("skull", bone_id, entries)

# ---- PDF04 -> skull (existing topic) ----
copy_and_register("skull", "general", [("pdf04", p, cap) for p, cap in PDF04_ROUTES_SKULL_GENERAL])
copy_and_register("skull", "whole_skull", [("pdf04", p, cap) for p, cap in PDF04_ROUTES_SKULL_WHOLE])

# ---- PDF05 -> upper_limb_bones (new topic) ----
copy_and_register("upper_limb_bones", "general", [("pdf05", p, cap) for p, cap in PDF05_ROUTES_UPPER_GENERAL])
for bone_id, pages in PDF05_ROUTES.items():
    entries = [("pdf05", p, cap) for p, cap in pages]
    copy_and_register("upper_limb_bones", bone_id, entries)

# ==================== СОЗДАНИЕ bones_list ДЛЯ НОВЫХ ТЕМ ====================
TRUNK_BONES_LIST = [
    {"id": "general", "title": "Общие сведения"},
    {"id": "columna_vertebralis", "title": "Позвоночный столб"},
    {"id": "vertebra_general", "title": "Позвонок — общее строение"},
    {"id": "cervical_vertebra", "title": "Шейные позвонки"},
    {"id": "atlas_axis", "title": "Атлант и осевой позвонок"},
    {"id": "thoracic_vertebra", "title": "Грудные позвонки"},
    {"id": "lumbar_vertebra", "title": "Поясничные позвонки"},
    {"id": "sacrum_coccyx", "title": "Крестец и копчик"},
    {"id": "ribs", "title": "Рёбра и грудная клетка"},
    {"id": "sternum", "title": "Грудина"},
]
UPPER_LIMB_BONES_LIST = [
    {"id": "general", "title": "Общие сведения"},
    {"id": "scapula", "title": "Лопатка"},
    {"id": "clavicle", "title": "Ключица"},
    {"id": "humerus", "title": "Плечевая кость"},
    {"id": "ulna", "title": "Локтевая кость"},
    {"id": "radius", "title": "Лучевая кость"},
    {"id": "hand_bones", "title": "Кости кисти"},
]

data["osteology"]["topics"]["trunk_bones"]["bones_list"] = TRUNK_BONES_LIST
data["osteology"]["topics"]["trunk_bones"]["bone_material_ids"] = {b["id"]: [] for b in TRUNK_BONES_LIST}
data["osteology"]["topics"]["upper_limb_bones"]["bones_list"] = UPPER_LIMB_BONES_LIST
data["osteology"]["topics"]["upper_limb_bones"]["bone_material_ids"] = {b["id"]: [] for b in UPPER_LIMB_BONES_LIST}

# Add "general" and "whole_skull" pseudo-bones to skull's bones_list (they're not real bones,
# but reuse the existing per-bone gallery UI to host overview/whole-skull photos)
skull_bones_list = data["osteology"]["topics"]["skull"]["bones_list"]
existing_ids = {b["id"] for b in skull_bones_list}
if "general" not in existing_ids:
    skull_bones_list.insert(0, {"id": "general", "title": "Общий обзор черепа"})
if "whole_skull" not in existing_ids:
    skull_bones_list.append({"id": "whole_skull", "title": "Череп в целом (ямки, глазница, полость носа)"})
data["osteology"]["topics"]["skull"]["bone_material_ids"].setdefault("general", [])
data["osteology"]["topics"]["skull"]["bone_material_ids"].setdefault("whole_skull", [])

with open("/home/user/vmeda-biology-bot/anatomy.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

# ==================== SUMMARY ====================
total_images = 0
for topic_key in ("trunk_bones", "skull", "upper_limb_bones"):
    topic = data["osteology"]["topics"][topic_key]
    print(f"\n=== {topic_key} ===")
    for bone_id, imgs in topic.get("bone_images", {}).items():
        print(f"  {bone_id}: {len(imgs)} images")
        total_images += len(imgs)
print(f"\nTOTAL IMAGES REGISTERED: {total_images}")
