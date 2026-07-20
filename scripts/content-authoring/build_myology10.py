# -*- coding: utf-8 -*-
import json

with open("anatomy.json", "r", encoding="utf-8") as f:
    data = json.load(f)

D = "━━━━━━━━━━━━━━"

def topic(title, icon, material):
    return {
        "title": title,
        "icon": icon,
        "menu_title": f"{icon} {title}",
        "material": material,
        "flashcards": [],
        "matching_sets": [],
        "mnemonics": [],
        "picture_quiz": [],
    }

def mus(name_ru, name_lat, start, insertion, function, note=None):
    s = f"<b>{name_ru}</b>, <i>{name_lat}</i>:\n• начало: {start}\n• прикрепление: {insertion}\n• функция: {function}"
    if note:
        s += f"\n• примечание: {note}"
    return s

# ==================== 9. МЫШЦЫ НИЖНЕЙ КОНЕЧНОСТИ ====================

l1 = {
    "id": "pelvis_muscles",
    "title": "Мышцы таза",
    "content": (
        "<b>Классификация мышц таза по топографии:</b>\n"
        "I — внутренние мышцы таза: <i>mm. iliopsoas, piriformis, obturatorius internus</i>.\n"
        "II — наружные мышцы таза: <i>mm. gluteus maximus, gluteus medius, gluteus minimus, quadratus femoris, "
        "gemellus superior, gemellus inferior, tensor fasciae latae, obturatorius externus</i>.\n"
        "Все мышцы таза — спинального происхождения (вентральные), иннервация из ветвей поясничного и "
        "крестцового сплетений.\n\n"
        f"{D}\n\n"
        "<b>I. Внутренние мышцы таза</b>\n\n"
        + mus("Подвздошно-поясничная мышца", "m. iliopsoas",
              "состоит из: 1) большой поясничной мышцы, <i>m. psoas major</i> — corpus et processus transversus "
              "Th₁₂-L₄; 2) малой поясничной мышцы, <i>m. psoas minor</i> (непостоянная) — corpus Th₁₂-L₁; "
              "3) подвздошной мышцы, <i>m. iliacus</i> — fossa iliaca",
              "m. iliopsoas — trochanter minor ossis femoris; m. psoas minor — eminentia iliopubica",
              "сгибание и вращение бедра наружу; при фиксированном бедре — сгибание поясничного отдела "
              "позвоночного столба")
        + "\n\n"
        + mus("Грушевидная мышца", "m. piriformis", "facies anterior ossis sacri", "trochanter major femoris",
              "вращение бедра наружу")
        + "\n\n"
        + mus("Внутренняя запирательная мышца", "m. obturatorius internus",
              "внутренняя поверхность membrana obturatoria и края for. obturatum", "fossa trochanterica",
              "вращение бедра наружу")
        + f"\n\n{D}\n\n"
        "<b>II. Наружные мышцы таза</b>\n\n"
        + mus("Большая ягодичная мышца", "m. gluteus maximus",
              "площадка позади linea glutea posterior; facies dorsalis ossis sacri et coccygis; lig. "
              "sacrotuberale et fascia thoracolumbalis",
              "tuberositas glutea ossis femoris; частично продолжается в tractus iliotibialis",
              "разгибание бедра; вращение бедра наружу; отведение бедра")
        + "\n\n"
        + mus("Средняя ягодичная мышца", "m. gluteus medius",
              "площадка между linea glutea anterior et linea glutea posterior", "trochanter major",
              "отведение бедра; вращение бедра внутрь (передние пучки); вращение бедра наружу (задние пучки)")
        + "\n\n"
        + mus("Малая ягодичная мышца", "m. gluteus minimus",
              "площадка между linea glutea anterior et linea glutea inferior", "trochanter major",
              "отведение бедра; вращение бедра внутрь (передние пучки); вращение бедра наружу (задние пучки)")
        + "\n\n"
        + mus("Напрягатель широкой фасции бедра", "m. tensor fasciae latae",
              "spina iliaca anterior superior et labium externum cristae iliacae",
              "переходит в tractus iliotibialis", "натяжение tractus iliotibialis; сгибание бедра (передние "
              "пучки)")
        + "\n\n"
        + mus("Квадратная мышца бедра", "m. quadratus femoris", "tuber ischiadicum",
              "crista trochanterica et trochanter major femoris", "вращение бедра наружу")
        + "\n\n"
        + mus("Верхняя близнецовая мышца", "m. gemellus superior", "spina ischiadica",
              "вместе с m. obturatorius internus — к fossa trochanterica", "вращение бедра наружу")
        + "\n\n"
        + mus("Нижняя близнецовая мышца", "m. gemellus inferior", "tuber ischiadicum",
              "вместе с m. obturatorius internus — к fossa trochanterica", "вращение бедра наружу")
        + "\n\n"
        + mus("Наружная запирательная мышца", "m. obturatorius externus",
              "наружная поверхность membrana obturatoria и край for. obturatum", "fossa trochanterica",
              "вращение бедра наружу")
    ),
}

l2 = {
    "id": "thigh_anterior",
    "title": "Мышцы бедра — передняя группа",
    "content": (
        "<b>Классификация мышц бедра по топографии:</b>\n"
        "I — передняя группа: <i>mm. sartorius, quadriceps femoris</i>.\n"
        "II — медиальная группа: <i>mm. gracilis, pectineus, adductor longus, adductor brevis, adductor "
        "magnus</i>.\n"
        "III — задняя группа: <i>m. biceps femoris, m. semitendinosus, m. semimembranosus</i>.\n"
        "Все мышцы бедра — спинального происхождения (вентральные), иннервация из ветвей поясничного и "
        "крестцового сплетений.\n\n"
        f"{D}\n\n"
        + mus("Портняжная мышца", "m. sartorius", "spina iliaca anterior superior",
              "tuberositas tibiae (вместе с сухожилиями mm. gracilis et semitendinosus образует pes anserinus "
              "superficialis)",
              "сгибание бедра и голени; согнутую голень вращает внутрь")
        + f"\n\n{D}\n\n"
        "<b>Четырёхглавая мышца бедра</b>, <i>m. quadriceps femoris</i>, состоит из четырёх головок:\n\n"
        "1) <b>прямая мышца бедра</b>, <i>m. rectus femoris</i> — начало: <i>spina iliaca anterior inferior</i>;\n"
        "2) <b>латеральная широкая мышца бедра</b>, <i>m. vastus lateralis</i> — начало: <i>labium laterale "
        "lineae asperae femoris</i>, основание <i>trochanter major</i>;\n"
        "3) <b>промежуточная широкая мышца бедра</b>, <i>m. vastus intermedius</i> — начало: передняя "
        "поверхность <i>femur</i>;\n"
        "4) <b>медиальная широкая мышца бедра</b>, <i>m. vastus medialis</i> — начало: <i>labium mediale lineae "
        "asperae femoris</i>.\n\n"
        "Все четыре головки соединяются и переходят в <i>lig. patellae</i>, которая фиксируется к <i>tuberositas "
        "tibiae</i>. Функция: разгибание голени; <i>m. rectus femoris</i> дополнительно сгибает бедро."
    ),
}

data["myology"]["topics"]["lower_limb_muscles"] = topic("Мышцы нижней конечности", "🦿", [l1, l2])

with open("anatomy.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

tp = data["myology"]["topics"]["lower_limb_muscles"]
print("lower_limb_muscles pages:", len(tp["material"]))
for m in tp["material"]:
    print(f"  {m['id']}: {len(m['content'])} chars")
