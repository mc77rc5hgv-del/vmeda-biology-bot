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

n1 = {
    "id": "neck_superficial",
    "title": "Классификация мышц шеи, поверхностные мышцы",
    "content": (
        "Границы шеи: сверху — тело и ветвь нижней челюсти, основание черепа; снизу — яремная вырезка грудины и "
        "верхние поверхности ключиц; латерально — латеральный край трапециевидной мышцы.\n\n"
        "<b>Классификация по топографии:</b>\n"
        "I. Мышцы, лежащие спереди от гортани и крупных сосудов: 1) поверхностные — подкожная мышца, "
        "грудино-ключично-сосцевидная; 2) прикрепляющиеся к подъязычной кости (ниже неё — лопаточно-подъязычная, "
        "грудино-подъязычная, грудино-щитовидная, щитоподъязычная; выше неё — двубрюшная, "
        "челюстно-подъязычная, подбородочно-подъязычная, шилоподъязычная).\n"
        "II. Глубокие мышцы: 1) латеральная группа — передняя, средняя, задняя лестничные; 2) медиальная группа — "
        "длинная мышца головы, длинная мышца шеи, передняя и боковая прямые мышцы головы.\n\n"
        "<b>По происхождению:</b> краниального происхождения — <i>m. mylohyoideus</i>, переднее брюшко "
        "<i>m. digastricus</i> (1-я висцеральная дуга, иннервация из <i>n. trigeminus</i>); <i>platysma, m. "
        "stylohyoideus</i>, заднее брюшко <i>m. digastricus</i> (2-я висцеральная дуга, иннервация из <i>n. "
        "facialis</i>); <i>m. sternocleidomastoideus</i> (5-я висцеральная дуга, иннервация из <i>n. accessorius</i>). "
        "Спинального происхождения (вентральные, аутохтонные) — <i>m. geniohyoideus</i>, все мышцы ниже "
        "подъязычной кости, все глубокие мышцы шеи (иннервация из шейного сплетения).\n\n"
        f"{D}\n\n"
        "<b>1. Поверхностные мышцы</b>\n\n"
        + mus("Подкожная мышца шеи", "platysma (m. subcutaneus colli)",
              "lamina superficialis f. pectoralis propriae",
              "переходит в f. parotidea et masseterica, вплетается в мимические мышцы (m. depressor labii "
              "inferioris, m. risorius)",
              "оттягивает кожу шеи, облегчая отток крови по поверхностным венам; передними пучками тянет угол "
              "рта книзу")
        + "\n\n"
        + mus("Грудино-ключично-сосцевидная мышца", "m. sternocleidomastoideus",
              "медиальная головка — manubrium sterni; латеральная головка — extremitas sternalis claviculae",
              "processus mastoideus et linea nuchae superior",
              "наклон головы, поворот её в противоположную сторону (при одностороннем сокращении); "
              "запрокидывание головы (при двустороннем)")
    ),
}

n1b = {
    "id": "neck_hyoid_muscles",
    "title": "Мышцы, прикрепляющиеся к подъязычной кости",
    "content": (
        "<i>1) Лежащие ниже подъязычной кости (опускают os hyoideum и гортань):</i>\n\n"
        + mus("Лопаточно-подъязычная мышца", "m. omohyoideus",
              "venter inferior — lig. transversum scapulae superius et margo superior scapulae",
              "venter superior — corpus os hyoideum", "опускает подъязычную кость")
        + "\n\n"
        + mus("Грудино-подъязычная мышца", "m. sternohyoideus",
              "facies posterior manubrii sterni, extremitas sternalis claviculae и капсула art. "
              "sternoclavicularis", "corpus os hyoideum", "опускает подъязычную кость")
        + "\n\n"
        + mus("Грудино-щитовидная мышца", "m. sternothyroideus",
              "facies posterior manubrii sterni et cartilago costae I", "linea obliqua cartilago thyroidea",
              "опускает гортань")
        + "\n\n"
        + mus("Щитоподъязычная мышца", "m. thyrohyoideus",
              "linea obliqua cartilago thyroidea", "corpus os hyoideum",
              "опускает подъязычную кость (либо, при фиксированной кости, поднимает гортань)")
        + f"\n\n{D}\n\n"
        "<i>2) Лежащие выше подъязычной кости (поднимают os hyoideum, опускают нижнюю челюсть):</i>\n\n"
        + mus("Двубрюшная мышца", "m. digastricus",
              "venter posterior — incisura mastoidea ossis temporalis; venter anterior — fossa digastrica "
              "mandibulae",
              "corpus os hyoideum, посредством сухожилия, соединяющего оба брюшка",
              "опускание нижней челюсти; при фиксированной нижней челюсти — поднимание подъязычной кости")
        + "\n\n"
        + mus("Шилоподъязычная мышца", "m. stylohyoideus",
              "processus styloideus", "основание большого рога os hyoideum",
              "смещение os hyoideum вверх и назад")
        + "\n\n"
        + mus("Челюстно-подъязычная мышца", "m. mylohyoideus",
              "linea mylohyoidea mandibulae",
              "по срединной линии мышцы обеих сторон соединяются, образуя raphe mylohyoideae; задние пучки — "
              "corpus os hyoideum",
              "смещение os hyoideum вперёд и вверх; при фиксированной кости — опускание нижней челюсти")
        + "\n\n"
        + mus("Подбородочно-подъязычная мышца", "m. geniohyoideus",
              "spina mentalis", "corpus ossis hyoidei",
              "перемещение os hyoideum вперёд и вверх; опускание нижней челюсти")
    ),
}

material = data["myology"]["topics"]["neck_muscles"]["material"]
# replace old first page with the two new split pages
assert material[0]["id"] == "neck_superficial"
material[0] = n1
material.insert(1, n1b)

with open("anatomy.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

tp = data["myology"]["topics"]["neck_muscles"]
print("neck_muscles pages now:", len(tp["material"]))
for m in tp["material"]:
    print(f"  {m['id']}: {len(m['content'])} chars")
