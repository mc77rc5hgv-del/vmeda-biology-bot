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

# ==================== 2. МЫШЦЫ СПИНЫ ====================

b1 = {
    "id": "back_superficial",
    "title": "Мышцы спины — поверхностный слой",
    "content": (
        "Границы спины: сверху — <i>linea nuchae superior</i>; снизу — <i>os coccygis et os sacrum, crista "
        "iliaca</i>; латерально — <i>linea axillaris posterior</i>.\n\n"
        "<b>Классификация по расположению и форме:</b>\n"
        "I. Поверхностные мышцы: 1) прикрепляющиеся к костям верхней конечности — трапециевидная, широчайшая спины, "
        "мышца, поднимающая лопатку, большая и малая ромбовидные; 2) прикрепляющиеся к рёбрам — задняя верхняя и "
        "задняя нижняя зубчатые.\n"
        "II. Глубокие мышцы: 1) длинные — ременные головы и шеи, мышца, выпрямляющая позвоночник, "
        "поперечно-остистая; 2) короткие — подзатылочные, межостистые, межпоперечные.\n\n"
        "<b>По происхождению:</b> трапециевидная — краниального происхождения (производная 5-й жаберной дуги); "
        "остальные поверхностные — спинального происхождения, вентральные (ромбовидные и мышца, поднимающая "
        "лопатку — трункофугальные, широчайшая — трункопетальная); все глубокие мышцы спины — спинального "
        "происхождения, дорсальные (аутохтонные).\n\n"
        f"{D}\n\n"
        "<b>1. Мышцы, прикрепляющиеся к костям верхней конечности</b>\n\n"
        + mus("Трапециевидная мышца", "m. trapezius",
              "linea nuchae superior, protuberantia occipitalis externa, lig. nuchae, processus spinosus C₇-Th₁₂, lig. supraspinale",
              "extremitas acromialis claviculae, acromion et spina scapulae",
              "поднимание лопатки (верхние пучки); опускание лопатки (нижние пучки); приближение лопатки к "
              "позвоночнику (при одновременном сокращении); при фиксированном плечевом поясе — наклон головы и шеи "
              "в свою сторону (при одностороннем сокращении), запрокидывание головы назад (при двустороннем); "
              "вращение лопатки")
        + "\n\n"
        + mus("Широчайшая мышца спины", "m. latissimus dorsi",
              "processus spinosus Th₈₋₁₂, L₁₋₅, crista sacralis mediana, labium externum cristae iliacae (задняя треть)",
              "crista tuberculi minoris humeri",
              "вращение плечевой кости внутрь; опускание поднятой руки; при фиксированных верхних конечностях — "
              "приближение к ним туловища (например, при подтягивании)")
        + "\n\n"
        + mus("Мышца, поднимающая лопатку", "m. levator scapulae",
              "processus transversus C₁₋₄", "angulus superior scapulae",
              "поднимание лопатки и приближение её к срединной плоскости; при фиксированной лопатке — наклон в "
              "свою сторону шейного отдела позвоночника")
        + "\n\n"
        + mus("Большая и малая ромбовидные мышцы", "mm. rhomboidei major et minor",
              "m. rhomboideus minor — lig. nuchae (нижняя часть), processus spinosus C₇-Th₁; m. rhomboideus major — "
              "processus spinosus Th₁₋₄",
              "margo medialis scapulae (minor — выше уровня ости; major — от уровня ости до нижнего угла)",
              "перемещение лопатки к позвоночнику",
              "нередко срастаются, образуя единую мышцу")
        + f"\n\n{D}\n\n"
        "<b>2. Мышцы, прикрепляющиеся к рёбрам</b>\n\n"
        + mus("Задняя верхняя зубчатая мышца", "m. serratus posterior superior",
              "processus spinosus C₆₋₇, Th₁₋₂", "costae₂₋₅ (латеральнее их углов)", "поднимание рёбер")
        + "\n\n"
        + mus("Задняя нижняя зубчатая мышца", "m. serratus posterior inferior",
              "processus spinosus Th₁₁₋₁₂, L₁₋₂", "costae₁₁₋₁₂ (латеральнее их углов)", "опускание рёбер")
    ),
}

b2 = {
    "id": "back_deep_long",
    "title": "Мышцы спины — глубокий слой (длинные)",
    "content": (
        "<b>1. Длинные мышцы</b>\n\n"
        + mus("Ременная мышца головы и шеи", "m. splenius capitis et cervicis",
              "lig. nuchae на уровне C₃₋₆; processus spinosus C₇, Th₁₋₆",
              "m. splenius cervicis — processus transversus C₁₋₃; m. splenius capitis — processus mastoideus et "
              "linea nuchae superior",
              "m. splenius capitis — поворот головы в свою сторону (при одностороннем сокращении), запрокидывание "
              "головы назад (при двустороннем); m. splenius cervicis — наклон шейного отдела в свою сторону, "
              "разгибание шейного отдела (при двустороннем сокращении)")
        + f"\n\n{D}\n\n"
        + mus("Мышца, выпрямляющая позвоночник", "m. erector spinae",
              "os sacrum, processus spinosus L₁₋₅, crista iliaca, f. thoracolumbalis (общее начало для всех трёх "
              "частей); дополнительное начало — см. по частям ниже",
              "по частям ниже",
              "главная функция — разгибание позвоночника; m. iliocostalis lumborum — опускание рёбер; "
              "m. longissimus capitis — запрокидывание головы (при двустороннем сокращении), наклон головы в свою "
              "сторону (при одностороннем)")
        + "\n\nСостоит из трёх частей (тракты идут от общего начала латерально → медиально):\n"
        + "а) <b>подвздошно-рёберная мышца</b>, <i>m. iliocostalis</i> (lumborum, thoracis et cervicis) — "
        "дополнительное начало от рёбер (латеральнее углов); прикрепление — угол соответствующего ребра выше "
        "(поясничная и грудная части) либо processus transversus C₄₋₆ (шейная часть);\n"
        + "б) <b>длиннейшая мышца</b>, <i>m. longissimus</i> (thoracis, cervicis et capitis) — прикрепление: "
        "thoracis — processus transversus Th₁₋₁₂ и angulus costae₂₋₁₂; cervicis — processus transversus C₂₋₅; "
        "capitis — processus mastoideus;\n"
        + "в) <b>остистая мышца</b>, <i>m. spinalis</i> (thoracis, cervicis et capitis) — дополнительное начало от "
        "processus spinosus L₁₋₂, Th₁₁₋₁₂; прикрепление: thoracis — processus spinosus Th₂₋₈; cervicis — processus "
        "spinosus C₂₋₇; capitis — protuberantia occipitalis externa (может отсутствовать).\n"
        + f"\n{D}\n\n"
        + mus("Поперечно-остистая мышца", "m. transversospinalis",
              "processus transversus нижележащих позвонков", "processus spinosus вышележащих позвонков (по частям — см. ниже)",
              "разгибание позвоночника; поворот шеи и головы в противоположную сторону (при одностороннем "
              "сокращении); m. semispinalis capitis — наклон головы назад (при двустороннем), поворот головы в "
              "сторону (при одностороннем)")
        + "\n\nСостоит из трёх частей, различающихся размахом перекидывания через позвонки:\n"
        + "а) <b>полуостистая мышца</b>, <i>m. semispinalis</i> (thoracis, cervicis, capitis) — перебрасывается "
        "через 4-6 позвонков (у m. semispinalis capitis прикрепление — os occipitale, между верхней и нижней "
        "выйными линиями);\n"
        + "б) <b>многораздельная мышца</b>, <i>m. multifidus</i> (lumborum, thoracis et cervicis) — перекидывается "
        "через 2-4 позвонка;\n"
        + "в) <b>мышцы-вращатели</b>, <i>mm. rotatores</i> (lumborum, thoracis et cervicis) — короткие "
        "(<i>mm. rotatores breves</i>, к соседнему позвонку) и длинные (<i>mm. rotatores longi</i>, минуя 1-2 "
        "позвонка)."
    ),
}

b3 = {
    "id": "back_deep_short_and_fascia",
    "title": "Короткие и подзатылочные мышцы, фасции спины",
    "content": (
        "<b>2. Короткие мышцы</b>\n\n"
        + mus("Межостистые мышцы", "mm. interspinales", "—", "—",
              "находятся между остистыми отростками смежных позвонков (cervicis, thoracis, lumborum); "
              "принимают участие в разгибании позвоночника")
        + "\n\n"
        + mus("Межпоперечные мышцы", "mm. intertransversarii", "—", "—",
              "соединяют верхушки поперечных отростков соседних позвонков; наклоны позвоночника в сторону")
        + f"\n\n{D}\n\n"
        "<b>Подзатылочные мышцы</b> (короткие мышцы, действующие на атлантозатылочный и атлантоосевой суставы)\n\n"
        + mus("Большая задняя прямая мышца головы", "m. rectus capitis posterior major",
              "processus spinosus C₂", "linea nuchae inferior (латеральная часть)",
              "поворот головы (при одностороннем сокращении); запрокидывание головы назад (при двустороннем)")
        + "\n\n"
        + mus("Малая задняя прямая мышца головы", "m. rectus capitis posterior minor",
              "tuberculum posterius atlantis", "linea nuchae inferior (медиальная часть)",
              "запрокидывание головы назад")
        + "\n\n"
        + mus("Верхняя косая мышца головы", "m. obliquus capitis superior",
              "processus transversus atlantis", "linea nuchae inferior (латеральная часть)",
              "поворот головы (при одностороннем сокращении); запрокидывание головы назад (при двустороннем)")
        + "\n\n"
        + mus("Нижняя косая мышца головы", "m. obliquus capitis inferior",
              "processus spinosus axis", "processus transversus atlantis", "поворот головы")
        + f"\n\n{D}\n\n"
        "<b>Фасции спины</b>\n"
        "1. <b>Поверхностная фасция спины</b>, <i>fascia dorsi superficialis</i> — расположена за подкожной жировой "
        "клетчаткой.\n"
        "2. <b>Собственная фасция спины</b>, <i>fascia dorsi propria</i>, состоит из двух листков:\n"
        "а) поверхностная пластинка — покрывает поверхностные мышцы, окутывая каждую и прочно с ней срастаясь;\n"
        "б) глубокая пластинка — хорошо выражена в области m. erector spinae, называется <b>грудо-поясничной "
        "фасцией</b>, <i>fascia thoracolumbalis</i>; покрывает глубокие мышцы спины двумя пластинками (задней и "
        "передней), которые соединяются вдоль латерального края m. erector spinae, замыкая для неё "
        "костно-фиброзный футляр — <b>влагалище мышцы, выпрямляющей позвоночник</b>, <i>vagina m. erector "
        "spinae</i>, расположенное в поясничной области латерально от позвоночника (3 стенки: передняя — "
        "processus transversus L₁₋₅ и глубокая пластинка; задняя — поверхностная пластинка; медиальная — processus "
        "spinosus L₁₋₅).\n\n"
        "<b>Кровоснабжение и иннервация мышц спины (кратко):</b>\n"
        "Артерии — по областям: в области головы — <i>a. occipitalis, a. auricularis posterior</i>; в области шеи "
        "— ветви <i>a. vertebralis, a. subclavia</i> (через <i>trunci costocervicalis, thyrocervicalis</i>); в "
        "грудной области — <i>aa. intercostales posteriores, a. suprascapularis, a. thoracodorsalis</i>; в "
        "поясничной — <i>aa. lumbales, iliolumbales</i>.\n"
        "Нервы: <i>n. accessorius</i> (XI пара) — <i>m. trapezius</i>; <i>n. dorsalis scapulae</i> — ромбовидные и "
        "мышца, поднимающая лопатку; <i>n. thoracodorsalis</i> — <i>m. latissimus dorsi</i>; <i>nn. "
        "intercostales</i> — зубчатые задние мышцы; <i>rr. dorsales nn. spinales</i> — все глубокие мышцы спины."
    ),
}

back_muscles = topic("Мышцы спины", "🔙", [b1, b2, b3])
data["myology"]["topics"]["back_muscles"] = back_muscles

with open("anatomy.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

tp = data["myology"]["topics"]["back_muscles"]
print("back_muscles pages:", len(tp["material"]))
for m in tp["material"]:
    print(f"  {m['id']}: {len(m['content'])} chars")
