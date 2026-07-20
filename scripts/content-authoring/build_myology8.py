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

u3 = {
    "id": "forearm_anterior",
    "title": "Мышцы предплечья — передняя группа",
    "content": (
        "<b>Классификация мышц предплечья по топографии:</b>\n"
        "I — передняя группа: 1) поверхностный слой — <i>mm. brachioradialis, pronator teres, flexor carpi "
        "radialis, palmaris longus, flexor digitorum superficialis, flexor carpi ulnaris</i>; 2) глубокий слой — "
        "<i>mm. flexor pollicis longus, flexor digitorum profundus, pronator quadratus</i>.\n"
        "II — задняя группа: 1) поверхностный слой — <i>mm. extensores carpi radiales longus et brevis, "
        "extensor digitorum, extensor digiti minimi, extensor carpi ulnaris</i>; 2) глубокий слой — <i>mm. "
        "supinator, abductor pollicis longus, extensor pollicis brevis, extensor pollicis longus, extensor "
        "indicis</i>.\n"
        "Все мышцы предплечья — спинального происхождения (вентральные), иннервация из ветвей плечевого "
        "сплетения. Большая часть сгибателей начинается в <b>типичном месте</b>: <i>epicondylus medialis "
        "humeri</i> и собственная фасция предплечья.\n\n"
        f"{D}\n\n"
        "<b>1. Поверхностный слой</b>\n\n"
        + mus("Плечелучевая мышца", "m. brachioradialis", "crista supracondylaris lateralis humeri",
              "radius (над processus styloideus)",
              "сгибание в локтевом суставе; устанавливает кисть в среднем положении между супинацией и "
              "пронацией")
        + "\n\n"
        + mus("Круглый пронатор", "m. pronator teres", "типичное + processus coronoideus ulnae",
              "radius (средняя треть)", "сгибание в локтевом суставе; пронация предплечья")
        + "\n\n"
        + mus("Лучевой сгибатель запястья", "m. flexor carpi radialis", "типичное", "basis os metacarpale II",
              "сгибание кисти; отведение кисти (вместе с mm. extensores carpi radiales longus et brevis)")
        + "\n\n"
        + mus("Длинная ладонная мышца", "m. palmaris longus", "типичное", "aponeurosis palmaris",
              "сгибание кисти; натяжение ладонного апоневроза")
        + "\n\n"
        + mus("Поверхностный сгибатель пальцев", "m. flexor digitorum superficialis",
              "типичное; lig. collaterale ulnare и проксимальная часть radius",
              "сухожилиями — к боковым поверхностям средних фаланг II-V пальцев",
              "сгибание кисти; сгибание II-V пальцев")
        + "\n\n"
        + mus("Локтевой сгибатель запястья", "m. flexor carpi ulnaris",
              "caput mediale — типичное; caput laterale — olecranon", "os pisiforme",
              "сгибание кисти; приведение кисти (вместе с m. extensor carpi ulnaris)")
        + f"\n\n{D}\n\n"
        "<b>2. Глубокий слой</b>\n\n"
        + mus("Длинный сгибатель большого пальца", "m. flexor pollicis longus",
              "radius et membrana interossea antebrachii", "основание ногтевой фаланги большого пальца",
              "сгибание кисти и большого пальца")
        + "\n\n"
        + mus("Глубокий сгибатель пальцев", "m. flexor digitorum profundus",
              "ulna et membrana interossea antebrachii (верхние две трети)",
              "основания ногтевых фаланг II-V пальцев", "сгибание кисти и II-V пальцев")
        + "\n\n"
        + mus("Квадратный пронатор", "m. pronator quadratus", "ulna (нижняя треть)", "radius (нижняя треть)",
              "пронация предплечья и кисти")
    ),
}

u4 = {
    "id": "forearm_posterior",
    "title": "Мышцы предплечья — задняя группа",
    "content": (
        "Большая часть разгибателей начинается в <b>типичном месте</b>: <i>epicondylus lateralis humeri</i> и "
        "собственная фасция предплечья.\n\n"
        "<b>1. Поверхностный слой</b>\n\n"
        + mus("Длинный лучевой разгибатель запястья", "m. extensor carpi radialis longus", "типичное",
              "основание II пястной кости",
              "разгибание предплечья; разгибание кисти; отведение кисти (вместе с m. flexor carpi radialis)")
        + "\n\n"
        + mus("Короткий лучевой разгибатель запястья", "m. extensor carpi radialis brevis",
              "типичное et lig. collaterale radiale", "основание III пястной кости",
              "разгибание кисти; отведение кисти (вместе с m. flexor carpi radialis)")
        + "\n\n"
        + mus("Разгибатель пальцев", "m. extensor digitorum", "типичное",
              "средние и ногтевые фаланги II-V пальцев", "разгибание кисти и II-V пальцев",
              "сухожилия соединены межсухожильными соединениями, connexus intertendineus")
        + "\n\n"
        + mus("Разгибатель мизинца", "m. extensor digiti minimi", "типичное",
              "основание средней и ногтевой фаланг мизинца", "разгибает мизинец")
        + "\n\n"
        + mus("Локтевой разгибатель запястья", "m. extensor carpi ulnaris", "типичное",
              "основание V пястной кости",
              "разгибание кисти; приведение кисти (вместе с m. flexor carpi ulnaris)")
        + f"\n\n{D}\n\n"
        "<b>2. Глубокий слой</b>\n\n"
        + mus("Супинатор", "m. supinator",
              "epicondylus lateralis humeri, lig. collaterale radiale, lig. annulare radii et crista m. "
              "supinatorii",
              "radius (верхняя треть)", "супинация предплечья")
        + "\n\n"
        + mus("Длинная мышца, отводящая большой палец кисти", "m. abductor pollicis longus",
              "radius, ulna (нижняя треть) et membrana interossea antebrachii", "основание I пястной кости",
              "отведение кисти и большого пальца")
        + "\n\n"
        + mus("Короткий разгибатель большого пальца кисти", "m. extensor pollicis brevis",
              "radius et membrana interossea antebrachii", "проксимальная фаланга большого пальца",
              "разгибание и отведение большого пальца")
        + "\n\n"
        + mus("Длинный разгибатель большого пальца кисти", "m. extensor pollicis longus",
              "ulna (средняя треть) et membrana interossea antebrachii",
              "основание дистальной фаланги большого пальца", "разгибание большого пальца")
        + "\n\n"
        + mus("Разгибатель указательного пальца", "m. extensor indicis",
              "ulna et membrana interossea antebrachii", "проксимальная фаланга указательного пальца",
              "разгибание указательного пальца")
        + f"\n\n{D}\n\n"
        "<b>Топография предплечья</b>: лучевая борозда (латерально — <i>m. brachioradialis</i>, медиально — "
        "<i>m. flexor carpi radialis</i>; содержит <i>a. radialis</i>, вены, поверхностную ветвь <i>n. "
        "radialis</i>); срединная борозда (между <i>m. flexor carpi radialis</i> и <i>m. flexor digitorum "
        "superficialis</i>; содержит <i>n. medianus</i>); локтевая борозда (между <i>m. flexor digitorum "
        "superficialis</i> и <i>m. flexor carpi ulnaris</i>; содержит <i>a., vv. ulnares, n. ulnaris</i>); "
        "супинаторный канал (содержит глубокую ветвь <i>n. radialis</i>).\n\n"
        "<b>Кровоснабжение и иннервация мышц предплечья:</b> артерии — ветви <i>a. radialis, a. ulnaris</i> (обе "
        "из <i>a. brachialis</i>), <i>a. interossea anterior et posterior</i> (из <i>a. interossea communis</i>). "
        "Нервы: <i>n. radialis</i> — задняя группа и <i>m. brachioradialis</i>; <i>n. ulnaris</i> — <i>m. flexor "
        "carpi ulnaris</i> и медиальная часть <i>m. flexor digitorum profundus</i>; <i>n. medianus</i> — "
        "остальные мышцы передней группы."
    ),
}

tp = data["myology"]["topics"]["upper_limb_muscles"]
tp["material"].append(u3)
tp["material"].append(u4)

with open("anatomy.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("upper_limb_muscles pages now:", len(tp["material"]))
for m in tp["material"]:
    print(f"  {m['id']}: {len(m['content'])} chars")
