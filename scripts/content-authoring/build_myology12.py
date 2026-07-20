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

l5 = {
    "id": "leg_posterior",
    "title": "Мышцы голени — задняя группа",
    "content": (
        "<b>1. Поверхностный слой</b>\n\n"
        "<b>Трёхглавая мышца голени</b>, <i>m. triceps surae</i>, состоит из икроножной и камбаловидной мышц:\n\n"
        + mus("Икроножная мышца", "m. gastrocnemius",
              "caput mediale — epicondylus medialis femoris; caput laterale — epicondylus lateralis femoris",
              "вместе с камбаловидной мышцей образует пяточное (Ахиллово) сухожилие, прикрепляющееся к tuber "
              "calcanei",
              "сгибание голени и стопы (<i>flexio plantaris</i>); caput laterale — вращение голени наружу; "
              "caput mediale — вращение голени внутрь")
        + "\n\n"
        + mus("Камбаловидная мышца", "m. soleus", "caput fibulae; верхняя треть fibulae; linea musculi solei "
              "tibiae",
              "соединяется с икроножной мышцей, образуя пяточное сухожилие", "сгибание голени и стопы")
        + "\n\n"
        + mus("Подошвенная мышца", "m. plantaris", "epicondylus lateralis femoris",
              "вплетается в Ахиллово сухожилие", "сгибание в коленном суставе")
        + f"\n\n{D}\n\n"
        "<b>2. Глубокий слой</b>\n\n"
        + mus("Подколенная мышца", "m. popliteus", "epicondylus lateralis femoris",
              "задняя поверхность tibia выше linea m. solei", "сгибание голени; вращение голени внутрь")
        + "\n\n"
        + mus("Длинный сгибатель пальцев", "m. flexor digitorum longus", "tibia (средняя треть)",
              "дистальные фаланги II-V пальцев, прободая сухожилия короткого сгибателя пальцев",
              "flexio plantaris, супинация стопы; сгибание ногтевых фаланг II-V пальцев")
        + "\n\n"
        + mus("Задняя большеберцовая мышца", "m. tibialis posterior",
              "membrana interossea cruris, обращённые друг к другу поверхности tibia и fibula",
              "tuberositas ossis navicularis; ossa cuneiformia mediale, intermedium et laterale",
              "flexio plantaris, супинация и приведение стопы")
        + "\n\n"
        + mus("Длинный сгибатель большого пальца стопы", "m. flexor hallucis longus", "нижние две трети "
              "fibula", "phalanx distalis hallucis",
              "сгибание большого пальца; принимает участие в flexio plantaris, супинации и приведении стопы")
    ),
}

l6 = {
    "id": "foot_dorsum_medial_lateral",
    "title": "Мышцы стопы — тыл, медиальная и латеральная группы",
    "content": (
        "<b>Классификация мышц стопы по топографии:</b>\n"
        "I — мышцы тыла стопы: <i>mm. extensores digitorum longus et brevis</i> (короткий разгибатель — "
        "собственная мышца стопы).\n"
        "II — мышцы подошвы: 1) медиальная группа — <i>mm. abductor hallucis, flexor hallucis brevis, adductor "
        "hallucis</i>; 2) латеральная группа — <i>mm. abductor digiti minimi, flexor digiti minimi brevis</i>; "
        "3) средняя группа — <i>mm. flexor digitorum brevis, quadratus plantae, lumbricales, interossei "
        "plantares et dorsales</i>.\n"
        "Все мышцы стопы — спинального происхождения (вентральные), иннервация из ветвей крестцового сплетения.\n\n"
        f"{D}\n\n"
        "<b>I. Мышцы тыла стопы</b>\n\n"
        + mus("Короткий разгибатель пальцев", "m. extensor digitorum brevis",
              "calcaneus (латеральная и верхняя поверхности)",
              "основания средних и дистальных фаланг II-IV пальцев", "разгибание II-IV пальцев")
        + "\n\n"
        + mus("Короткий разгибатель большого пальца стопы", "m. extensor hallucis brevis",
              "верхняя поверхность calcaneus", "основание проксимальной фаланги большого пальца",
              "разгибание большого пальца стопы")
        + f"\n\n{D}\n\n"
        "<b>II. Мышцы подошвы — 1. Медиальная группа</b>\n\n"
        + mus("Мышца, отводящая большой палец стопы", "m. abductor hallucis",
              "tuber calcanei; tuberositas ossis navicularis et retinaculum mm. flexorum; aponeurosis plantaris",
              "основание проксимальной фаланги большого пальца", "отведение большого пальца стопы")
        + "\n\n"
        + mus("Короткий сгибатель большого пальца стопы", "m. flexor hallucis brevis",
              "os cuneiforme mediale; сухожилие m. tibialis posterior",
              "caput mediale — основание проксимальной фаланги большого пальца и медиальная сесамовидная кость; "
              "caput laterale — основание проксимальной фаланги большого пальца и латеральная сесамовидная кость",
              "сгибание проксимальной фаланги большого пальца")
        + "\n\n"
        + mus("Мышца, приводящая большой палец стопы", "m. adductor hallucis",
              "caput obliquum — lig. plantare longum, сухожилие m. peroneus longus, os cuneiforme laterale, "
              "основания ossa metatarsalia II и III; caput transversum — суставные капсулы плюснефаланговых "
              "суставов III-V",
              "латеральная сесамовидная кость; проксимальная фаланга большого пальца",
              "приведение большого пальца; сгибание его проксимальной фаланги")
        + f"\n\n{D}\n\n"
        "<b>2. Латеральная группа</b>\n\n"
        + mus("Мышца, отводящая мизинец стопы", "m. abductor digiti minimi",
              "подошвенная поверхность calcaneus; aponeurosis plantaris",
              "tuberositas ossis metatarsalis V; основание проксимальной фаланги мизинца",
              "отведение и сгибание проксимальной фаланги мизинца")
        + "\n\n"
        + mus("Короткий сгибатель мизинца стопы", "m. flexor digiti minimi brevis",
              "os metatarsale V; lig. plantare longum", "основание проксимальной фаланги мизинца",
              "сгибание проксимальной фаланги мизинца")
    ),
}

tp = data["myology"]["topics"]["lower_limb_muscles"]
tp["material"].append(l5)
tp["material"].append(l6)

with open("anatomy.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("lower_limb_muscles pages now:", len(tp["material"]))
for m in tp["material"]:
    print(f"  {m['id']}: {len(m['content'])} chars")
