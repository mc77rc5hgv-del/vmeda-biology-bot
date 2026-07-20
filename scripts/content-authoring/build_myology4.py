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

# ==================== 5. ДИАФРАГМА ====================

d1 = {
    "id": "diaphragm_structure",
    "title": "Строение диафрагмы",
    "content": (
        "<b>Диафрагма</b>, <i>diaphragma (m. phrenicus)</i>, — непарная мышца, разделяющая грудную и брюшную "
        "полости.\n\n"
        "В диафрагме выделяют:\n"
        "1. <b>Сухожильный центр</b>, <i>centrum tendineum</i>;\n"
        "2. <b>Мышечную часть</b>, <i>pars muscularis</i>.\n\n"
        "Правая часть купола диафрагмы располагается на уровне хряща V ребра, левая — на уровне хряща VI ребра. "
        "Сверху и снизу диафрагма покрыта фасциями (<i>f. endothoracica</i> и <i>f. endoabdominalis</i>) и "
        "серозными оболочками (плеврой и брюшиной).\n\n"
        "В сухожильном центре различают: <b>сердечное вдавление</b>, <i>impressio cordis</i>; <b>отверстие нижней "
        "полой вены</b>, <i>foramen venae cavae</i>.\n\n"
        f"{D}\n\n"
        "<b>Мышечная часть</b> состоит из трёх частей: поясничной, рёберной и грудинной.\n\n"
        "<b>I. Поясничная часть</b>, <i>pars lumbalis</i>, состоит из трёх ножек:\n"
        "1. <b>Медиальная ножка</b>, <i>crus mediale</i>, начинается справа от <i>corpus L₃</i>, слева — от "
        "<i>corpus L₂</i>, а также от <i>lig. longitudinale anterius</i>. На уровне Th₁₂-L₁ правая и левая ножки "
        "сходятся, образуя <b>срединную дугообразную связку</b>, <i>lig. arcuatum medianum</i>, ограничивающую "
        "<b>аортальное отверстие</b>, <i>hiatus aorticus</i> (проходят аорта и грудной лимфатический проток). Затем "
        "мышечные пучки расходятся, образуя <b>пищеводное отверстие</b>, <i>hiatus esophageus</i>, на уровне "
        "Th₁₀₋₁₁ (проходят пищевод и блуждающие нервы).\n"
        "2. <b>Промежуточная ножка</b>, <i>crus intermedium</i>, начинается от боковой поверхности <i>corpus "
        "L₂</i>. От медиальной ножки отделена щелью, через которую справа проходит большой внутренностный нерв "
        "(<i>n. splanchnicus major</i>) и <i>v. azygos</i>, слева — тот же нерв и <i>v. hemiazygos</i>. Через "
        "промежуточную ножку проходит малый внутренностный нерв, <i>n. splanchnicus minor</i>.\n"
        "3. <b>Латеральная ножка</b>, <i>crus laterale</i>, начинается от медиальной и латеральной дугообразных "
        "связок: медиальная дугообразная связка (<i>lig. arcuatum mediale</i>) перекинута над <i>m. psoas "
        "major</i>, фиксирована к телу L₁ и поперечному отростку L₂; латеральная дугообразная связка (<i>lig. "
        "arcuatum laterale</i>) перекинута над <i>m. quadratus lumborum</i>, фиксирована к поперечному отростку L₂ "
        "и costa₁₂. В щели между латеральной и промежуточной ножками проходит симпатический ствол, <i>truncus "
        "sympathicus</i>.\n\n"
        "<b>II. Рёберная часть</b>, <i>pars costalis</i>, начинается от шести нижних рёбер и заканчивается в "
        "<i>centrum tendineum</i>.\n\n"
        "<b>III. Грудинная часть</b>, <i>pars sternalis</i>, начинается от задней поверхности мечевидного "
        "отростка грудины и заканчивается в <i>centrum tendineum</i>.\n\n"
        "Между <i>pars sternalis</i> и <i>pars costalis</i> расположен <b>грудино-рёберный треугольник</b>, "
        "<i>trigonum sternocostale</i>; смежные края <i>pars lumbalis</i> и <i>pars costalis</i> ограничивают "
        "<b>пояснично-рёберный треугольник</b>, <i>trigonum lumbocostale</i>. В этих треугольниках грудная и "
        "брюшная полости разобщены только фасциями и серозными оболочками — «слабые» места диафрагмы."
    ),
}

d2 = {
    "id": "diaphragm_openings_and_supply",
    "title": "Отверстия диафрагмы, кровоснабжение",
    "content": (
        "<b>Содержимое и топография щелей и отверстий диафрагмы</b>\n\n"
        "• <b>Отверстие нижней полой вены</b>, <i>foramen venae cavae</i> — в сухожильном центре, в области "
        "сердечного вдавления (прикрепление к грудине хряща VI ребра). Содержимое: <i>vena cava inferior</i>.\n\n"
        "• <b>Аортальное отверстие</b>, <i>hiatus aorticus</i> — между сухожильными пучками медиальных ножек "
        "(Th₁₂-L₁). Содержимое: <i>aorta, ductus thoracicus</i>.\n\n"
        "• <b>Пищеводное отверстие</b>, <i>hiatus esophageus</i> — между мышечными пучками медиальных ножек "
        "(Th₁₀-Th₁₁). Содержимое: <i>esophagus, n. vagus dexter et n. vagus sinister</i>.\n\n"
        "• <b>Щель между медиальной и промежуточной ножками</b> — сбоку от позвоночного столба (Th₁₁-Th₁₂). "
        "Содержимое: <i>n. splanchnicus major</i> (справа), <i>v. azygos</i> (справа), <i>v. hemiazygos</i> "
        "(слева).\n\n"
        "• <b>Щель между промежуточной и латеральной ножками</b> — сбоку от позвоночного столба (Th₁₁-Th₁₂). "
        "Содержимое: <i>truncus sympathicus</i>.\n\n"
        "• <b>Щель между мышечными пучками промежуточной ножки</b> — сбоку от позвоночного столба (Th₁₁-Th₁₂). "
        "Содержимое: <i>n. splanchnicus minor</i>.\n\n"
        "• <b>Грудино-рёберный треугольник</b>, <i>trigonum sternocostale</i> — сбоку от основания мечевидного "
        "отростка. Содержимое: <i>a. epigastrica superior</i> (из <i>a. thoracica interna</i>), <i>vv. "
        "epigastricae superiores</i> (в <i>v. brachiocephalica</i>).\n\n"
        f"{D}\n\n"
        "<b>Кровоснабжение и иннервация диафрагмы</b>\n"
        "Артерии: <i>a. musculophrenica, a. pericardiacophrenica</i> (из <i>a. thoracica interna</i> из <i>a. "
        "subclavia</i>); <i>aa. intercostales posteriores, aa. phrenicae superiores</i> (из грудной аорты); "
        "<i>aa. phrenicae inferiores</i> (из брюшной аорты).\n"
        "Вены: <i>v. musculophrenica, v. pericardiacophrenica</i> — в <i>v. thoracica interna</i> и далее в "
        "<i>v. brachiocephalica</i>; <i>vv. intercostales posteriores, vv. phrenicae superiores</i> — в <i>v. "
        "azygos (v. hemiazygos)</i> и далее в <i>v. cava superior</i>; <i>vv. phrenicae inferiores</i> — в "
        "<i>v. cava inferior</i>.\n"
        "Нервы: <i>n. phrenicus</i> (из шейного сплетения) — единственный двигательный и чувствительный нерв "
        "диафрагмы; при его раздражении возникает икота."
    ),
}

diaphragm_topic = topic("Диафрагма", "🫧", [d1, d2])
data["myology"]["topics"]["diaphragm"] = diaphragm_topic

with open("anatomy.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

tp = data["myology"]["topics"]["diaphragm"]
print("diaphragm pages:", len(tp["material"]))
for m in tp["material"]:
    print(f"  {m['id']}: {len(m['content'])} chars")
