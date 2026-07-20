# -*- coding: utf-8 -*-
import json

with open("anatomy.json", "r", encoding="utf-8") as f:
    data = json.load(f)

D = "━━━━━━━━━━━━━━"

def mus(name_ru, name_lat, start, insertion, function, note=None):
    s = f"<b>{name_ru}</b>, <i>{name_lat}</i>:\n• начало: {start}\n• прикрепление: {insertion}\n• функция: {function}"
    if note:
        s += f"\n• примечание: {note}"
    return s

l3 = {
    "id": "thigh_medial_posterior",
    "title": "Мышцы бедра — медиальная и задняя группы",
    "content": (
        "<b>II. Медиальная группа мышц бедра</b>\n\n"
        + mus("Тонкая мышца", "m. gracilis", "ramus inferior ossis pubis",
              "tuberositas tibiae (вместе с сухожилиями mm. sartorius et semitendinosus образует pes anserinus "
              "superficialis)",
              "приведение бедра; сгибание голени; при согнутом коленном суставе — вращение голени внутрь")
        + "\n\n"
        + mus("Гребенчатая мышца", "m. pectineus", "pecten ossis pubis et ramus superior ossis pubis",
              "labium mediale lineae asperae femoris (верхняя часть)", "сгибание и приведение бедра")
        + "\n\n"
        + mus("Длинная приводящая мышца", "m. adductor longus", "ramus superior ossis pubis",
              "labium mediale lineae asperae femoris (средняя треть)", "приведение бедра")
        + "\n\n"
        + mus("Короткая приводящая мышца", "m. adductor brevis (расположена под предыдущей)",
              "ramus inferior ossis pubis", "labium mediale lineae asperae femoris (верхняя треть)",
              "приведение и сгибание бедра")
        + "\n\n"
        + mus("Большая приводящая мышца", "m. adductor magnus",
              "tuber ischiadicum, ramus ossis ischii и частично ramus inferior ossis pubis",
              "labium mediale lineae asperae femoris; epicondylus medialis femoris", "приведение бедра")
        + f"\n\n{D}\n\n"
        "<b>III. Задняя группа мышц бедра</b>\n\n"
        + mus("Двуглавая мышца бедра", "m. biceps femoris",
              "caput longum — tuber ischiadicum; caput breve — labium laterale lineae asperae femoris",
              "caput fibulae", "разгибание бедра; сгибание и вращение голени наружу")
        + "\n\n"
        + mus("Полусухожильная мышца", "m. semitendinosus", "tuber ischiadicum",
              "tuberositas tibiae (вместе с сухожилиями mm. sartorius et gracilis образует pes anserinus "
              "superficialis)",
              "разгибание бедра; сгибание и вращение голени внутрь")
        + "\n\n"
        + mus("Полуперепончатая мышца", "m. semimembranosus", "tuber ischiadicum",
              "tibia, образуя pes anserinus profundus", "разгибание бедра; сгибание и вращение голени внутрь")
    ),
}

l4 = {
    "id": "leg_anterior_lateral",
    "title": "Мышцы голени — передняя и латеральная группы",
    "content": (
        "<b>Классификация мышц голени по топографии:</b>\n"
        "I — передняя группа (разгибатели): <i>mm. tibialis anterior, extensor digitorum longus, extensor "
        "hallucis longus</i>.\n"
        "II — латеральная группа: <i>mm. peroneus longus, peroneus brevis</i>.\n"
        "III — задняя группа (сгибатели): поверхностный слой — <i>mm. triceps surae (gastrocnemius et soleus), "
        "plantaris</i>; глубокий слой — <i>mm. popliteus, flexor digitorum longus, tibialis posterior, flexor "
        "hallucis longus</i>.\n"
        "Все мышцы голени — спинального происхождения (вентральные), иннервация из ветвей крестцового "
        "сплетения.\n\n"
        f"{D}\n\n"
        "<b>I. Передняя группа</b>\n\n"
        + mus("Передняя большеберцовая мышца", "m. tibialis anterior",
              "facies lateralis tibiae; membrana interossea cruris; fascia cruris",
              "os cuneiforme mediale et basis ossis metatarsalis I",
              "тыльное сгибание (<i>flexio dorsalis</i>), супинация и приведение стопы",
              "вместе с m. peroneus longus образует «стремя стопы»")
        + "\n\n"
        + mus("Длинный разгибатель пальцев", "m. extensor digitorum longus",
              "condylus lateralis tibiae; caput et margo anterior fibulae; membrana interossea cruris et fascia "
              "cruris",
              "средняя и дистальная фаланги II-V пальцев",
              "разгибание II-V пальцев; поднимание латерального края стопы (пронация)",
              "пятое сухожилие с частью брюшка прикрепляется к os metatarsale V, образуя m. peroneus tertius")
        + "\n\n"
        + mus("Длинный разгибатель большого пальца стопы", "m. extensor hallucis longus",
              "fibula (нижние две трети); membrana interossea cruris",
              "основание дистальной фаланги большого пальца",
              "тыльное сгибание стопы; разгибание большого пальца")
        + f"\n\n{D}\n\n"
        "<b>II. Латеральная группа</b>\n\n"
        + mus("Длинная малоберцовая мышца", "m. peroneus longus", "fibula (верхние две трети)",
              "tuberositas ossis metatarsalis I; basis ossis metatarsalis II et os cuneiforme mediale "
              "(подошвенная поверхность)",
              "подошвенное сгибание (<i>flexio plantaris</i>), пронация и отведение стопы")
        + "\n\n"
        + mus("Короткая малоберцовая мышца", "m. peroneus brevis", "facies lateralis fibulae (нижняя часть)",
              "tuberositas ossis metatarsalis V", "подошвенное сгибание, пронация и отведение стопы")
    ),
}

tp = data["myology"]["topics"]["lower_limb_muscles"]
tp["material"].append(l3)
tp["material"].append(l4)

with open("anatomy.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("lower_limb_muscles pages now:", len(tp["material"]))
for m in tp["material"]:
    print(f"  {m['id']}: {len(m['content'])} chars")
