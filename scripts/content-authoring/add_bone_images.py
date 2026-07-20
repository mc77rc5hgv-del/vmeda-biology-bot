# -*- coding: utf-8 -*-
import json

with open("anatomy.json", "r", encoding="utf-8") as f:
    data = json.load(f)

skull = data["osteology"]["topics"]["skull"]

PD = "Gray's Anatomy, 1918 (Henry Vandyke Carter) — общественное достояние"
ANATOMOGRAPHY = "Anatomography / BodyParts3D (DBCLS), Wikimedia Commons — CC BY-SA 2.1 Japan"
CC_BY_SA_3 = "Wikimedia Commons — CC BY-SA 3.0"
CC_BY_3 = "OpenStax College, Wikimedia Commons — CC BY 3.0"
PD_GOV = "National Cancer Institute (SEER), Wikimedia Commons — общественное достояние"
PD_SOBOTTA = "Sobotta's Atlas, 1909, Wikimedia Commons — общественное достояние"

BONE_IMAGES = {
    "frontal": [
        {"url": "https://upload.wikimedia.org/wikipedia/commons/thumb/9/9f/Frontal_bone_lateral3.png/500px-Frontal_bone_lateral3.png",
         "caption": "Лобная кость — вид сбоку (выделена на черепе)", "credit": ANATOMOGRAPHY},
    ],
    "parietal": [
        {"url": "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e5/Parietal_bone_posterior2.png/500px-Parietal_bone_posterior2.png",
         "caption": "Теменная кость — вид сзади (выделена на черепе)", "credit": ANATOMOGRAPHY},
        {"url": "https://upload.wikimedia.org/wikipedia/commons/thumb/2/21/Gray132.png/500px-Gray132.png",
         "caption": "Теменная кость — классическая схема (Gray's Anatomy)", "credit": PD},
    ],
    "occipital": [
        {"url": "https://upload.wikimedia.org/wikipedia/commons/thumb/1/19/Occipital_bone_lateral2.png/500px-Occipital_bone_lateral2.png",
         "caption": "Затылочная кость — вид сбоку (выделена на черепе)", "credit": ANATOMOGRAPHY},
        {"url": "https://upload.wikimedia.org/wikipedia/commons/thumb/8/88/Gray129.png/500px-Gray129.png",
         "caption": "Затылочная кость — классическая схема (Gray's Anatomy)", "credit": PD},
    ],
    "sphenoid": [
        {"url": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/af/Sphenoid_bone_-_lateral_view.png/500px-Sphenoid_bone_-_lateral_view.png",
         "caption": "Клиновидная кость — вид сбоку (выделена на черепе)", "credit": ANATOMOGRAPHY},
        {"url": "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d3/Gray148.png/330px-Gray148.png",
         "caption": "Клиновидная кость — классическая схема (Gray's Anatomy)", "credit": PD},
    ],
    "ethmoid": [
        {"url": "https://upload.wikimedia.org/wikipedia/commons/thumb/9/93/Gray149.png/250px-Gray149.png",
         "caption": "Решётчатая кость — классическая схема 1 (Gray's Anatomy)", "credit": PD},
        {"url": "https://upload.wikimedia.org/wikipedia/commons/thumb/f/f5/Gray150.png/250px-Gray150.png",
         "caption": "Решётчатая кость — классическая схема 2 (Gray's Anatomy)", "credit": PD},
    ],
    "temporal": [
        {"url": "https://upload.wikimedia.org/wikipedia/commons/thumb/2/20/Temporal_bone_lateral5.png/500px-Temporal_bone_lateral5.png",
         "caption": "Височная кость — вид сбоку (выделена на черепе)", "credit": ANATOMOGRAPHY},
        {"url": "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3a/Gray142.png/500px-Gray142.png",
         "caption": "Височная кость — классическая схема (Gray's Anatomy)", "credit": PD},
    ],
    "mandible": [
        {"url": "https://upload.wikimedia.org/wikipedia/commons/6/64/Gray176.png",
         "caption": "Нижняя челюсть — вид снаружи (Gray's Anatomy)", "credit": PD},
        {"url": "https://upload.wikimedia.org/wikipedia/commons/a/a3/Gray177.png",
         "caption": "Нижняя челюсть — вид изнутри (Gray's Anatomy)", "credit": PD},
    ],
    "maxilla": [
        {"url": "https://upload.wikimedia.org/wikipedia/commons/thumb/7/7f/Maxilla_anterior.png/500px-Maxilla_anterior.png",
         "caption": "Верхняя челюсть — вид спереди (выделена на черепе)", "credit": ANATOMOGRAPHY},
        {"url": "https://upload.wikimedia.org/wikipedia/commons/d/db/Gray161.png",
         "caption": "Верхняя челюсть — классическая схема (Gray's Anatomy)", "credit": PD},
    ],
    "palatine": [
        {"url": "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3e/Gray167.png/500px-Gray167.png",
         "caption": "Нёбная кость — классическая схема 1 (Gray's Anatomy)", "credit": PD},
        {"url": "https://upload.wikimedia.org/wikipedia/commons/thumb/b/b5/Gray168.png/500px-Gray168.png",
         "caption": "Нёбная кость — классическая схема 2 (Gray's Anatomy)", "credit": PD},
    ],
    "lacrimal": [
        {"url": "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c6/Lacrimal_bone_-_lateral_view6.png/500px-Lacrimal_bone_-_lateral_view6.png",
         "caption": "Слёзная кость — вид сбоку (выделена на черепе)", "credit": ANATOMOGRAPHY},
    ],
    "nasal_bone": [
        {"url": "https://upload.wikimedia.org/wikipedia/commons/thumb/7/77/Illu_facial_bones.jpg/500px-Illu_facial_bones.jpg",
         "caption": "Носовая кость в составе костей лица", "credit": PD_GOV},
        {"url": "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e9/Gray153.png/500px-Gray153.png",
         "caption": "Носовая кость — классическая схема (Gray's Anatomy)", "credit": PD},
    ],
    "inferior_concha": [
        {"url": "https://upload.wikimedia.org/wikipedia/commons/thumb/e/ef/Gray170.png/500px-Gray170.png",
         "caption": "Нижняя носовая раковина — классическая схема 1 (Gray's Anatomy)", "credit": PD},
        {"url": "https://upload.wikimedia.org/wikipedia/commons/thumb/4/42/Gray171.png/500px-Gray171.png",
         "caption": "Нижняя носовая раковина — классическая схема 2 (Gray's Anatomy)", "credit": PD},
    ],
    "zygomatic_bone": [
        {"url": "https://upload.wikimedia.org/wikipedia/commons/thumb/0/0b/Zygomatic_bone_anterior.png/500px-Zygomatic_bone_anterior.png",
         "caption": "Скуловая кость — вид спереди (выделена на черепе)", "credit": ANATOMOGRAPHY},
        {"url": "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d9/Gray165.png/500px-Gray165.png",
         "caption": "Скуловая кость — классическая схема (Gray's Anatomy)", "credit": PD},
    ],
    "vomer_bone": [
        {"url": "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d3/Vomer.jpg/500px-Vomer.jpg",
         "caption": "Сошник — фотография препарата", "credit": CC_BY_SA_3},
        {"url": "https://upload.wikimedia.org/wikipedia/commons/thumb/8/83/Gray173.png/500px-Gray173.png",
         "caption": "Сошник — классическая схема (Gray's Anatomy)", "credit": PD},
    ],
    "hyoid_bone": [
        {"url": "https://upload.wikimedia.org/wikipedia/commons/thumb/8/83/712_Hyoid_Bone.jpg/500px-712_Hyoid_Bone.jpg",
         "caption": "Подъязычная кость — вид спереди", "credit": CC_BY_3},
        {"url": "https://upload.wikimedia.org/wikipedia/commons/thumb/1/1f/Gray186.png/500px-Gray186.png",
         "caption": "Подъязычная кость — классическая схема (Gray's Anatomy)", "credit": PD},
    ],
}

missing = [b["id"] for b in skull["bones_list"] if b["id"] not in BONE_IMAGES]
assert not missing, f"missing images for: {missing}"

skull["bone_images"] = BONE_IMAGES
data["osteology"]["topics"]["skull"] = skull

with open("anatomy.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

total = sum(len(v) for v in BONE_IMAGES.values())
print("bones with images:", len(BONE_IMAGES), "/ total images:", total)
for bid, imgs in BONE_IMAGES.items():
    print(f"{bid:20s} {len(imgs)} img")
