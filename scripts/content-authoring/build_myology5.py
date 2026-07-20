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

# ==================== 6. МЫШЦЫ ШЕИ ====================

n1 = {
    "id": "neck_superficial",
    "title": "Поверхностные мышцы шеи, прикрепляющиеся к подъязычной кости",
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
        + f"\n\n{D}\n\n"
        "<b>2. Мышцы, прикрепляющиеся к подъязычной кости</b>\n\n"
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

n2 = {
    "id": "neck_deep",
    "title": "Глубокие мышцы шеи",
    "content": (
        "<b>1. Латеральная группа</b>\n\n"
        + mus("Передняя, средняя и задняя лестничные мышцы", "mm. scaleni anterior, medius et posterior",
              "processus transversus C₃₋₆",
              "tuberculum m. scaleni anterioris costae I (m. scalenus anterior); позади sulcus a. subclaviae "
              "costae I (m. scalenus medius); costa II (m. scalenus posterior)",
              "поднимание I и II рёбер; если рёбра фиксированы — наклон шейного отдела позвоночника в свою "
              "сторону; наклон позвоночника вперёд (при двустороннем сокращении)")
        + f"\n\n{D}\n\n"
        "<b>2. Медиальная группа</b>\n\n"
        + mus("Длинная мышца головы", "m. longus capitis", "processus transversus C₃₋₇",
              "pars basilaris ossis occipitalis",
              "поворот головы в сторону; наклон головы вперёд (при двустороннем сокращении)")
        + "\n\n"
        + mus("Длинная мышца шеи", "m. longus colli (расположена под предыдущей)",
              "вертикальная часть — corpus C₅₋₇, Th₁₋₃; нижняя косая часть — corpus Th₁₋₃; верхняя косая часть "
              "— processus transversus C₃₋₆",
              "вертикальная часть — corpus C₂₋₄; нижняя косая — processus transversus C₅₋₇; верхняя косая — "
              "tuberculum anterius atlantis",
              "наклоняет голову вперёд и в сторону")
        + "\n\n"
        + mus("Передняя прямая мышца головы", "m. rectus capitis anterior",
              "arcus anterior et processus transversus atlantis", "pars basilaris ossis occipitalis",
              "наклон головы вперёд")
        + "\n\n"
        + mus("Боковая прямая мышца головы", "m. rectus capitis lateralis",
              "processus transversus atlantis", "pars lateralis ossis occipitalis", "наклон головы в сторону")
    ),
}

n3 = {
    "id": "neck_regions_and_fascia",
    "title": "Области, треугольники и фасции шеи",
    "content": (
        "<b>Области и треугольники шеи</b>\n\n"
        "<b>1. Передняя область шеи</b>, <i>regio colli anterior</i>: латерально — передний край mm. "
        "sternocleidomastoidei; снизу — incisura jugularis manubrii sterni; сверху — верхняя граница шеи. В ней "
        "выделяют 4 треугольника:\n"
        "1) <b>лопаточно-подъязычный (сонный) треугольник</b>, <i>trigonum omohyoideum (caroticum)</i> — "
        "передний край m. sternocleidomastoideus; venter superior m. omohyoidei; venter posterior m. digastrici;\n"
        "2) <b>лопаточно-трахеальный треугольник</b>, <i>trigonum omotracheale</i> — срединная линия; передний "
        "край m. sternocleidomastoideus; venter superior m. omohyoidei;\n"
        "3) <b>поднижнечелюстной треугольник</b>, <i>trigonum submandibulare</i> — margo inferior mandibulae и "
        "m. digastricus;\n"
        "4) <b>треугольник Пирогова</b> — сухожилие m. digastricus, задний край m. mylohyoideus и "
        "n. hypoglossus (в нём хирургически находят язычную артерию).\n\n"
        "<b>2. Грудино-ключично-сосцевидная область</b>, <i>regio sternocleidomastoidea</i>, — соответствует "
        "контурам одноимённой мышцы; между её ножками — <i>trigonum sternocleidomastoideum</i>.\n\n"
        "<b>3. Боковая область шеи</b>, <i>regio colli lateralis</i>: спереди — задний край m. "
        "sternocleidomastoideus; сзади — латеральный край m. trapezius; снизу — верхний край ключицы. В ней 2 "
        "треугольника:\n"
        "1) <b>лопаточно-ключичный треугольник</b>, <i>trigonum omoclaviculare</i> — clavicula, venter inferior "
        "m. omohyoidei и задний край m. sternocleidomastoideus;\n"
        "2) <b>лопаточно-трапециевидный треугольник</b>, <i>trigonum omotrapezoideum</i> — край m. trapezius, "
        "задний край m. sternocleidomastoideus, venter inferior m. omohyoidei.\n\n"
        f"{D}\n\n"
        "<b>Фасции шеи</b> (нумерация по Шевкуненко, 5 фасций):\n"
        "1. <b>Поверхностная фасция шеи</b>, <i>f. cervicalis superficialis</i> (№1) — в виде перимизия покрывает "
        "подкожную мышцу.\n"
        "2. <b>Собственная фасция шеи</b>, <i>f. cervicalis propria</i>, — подподъязычная (3 пластинки: "
        "поверхностная №2 — окутывает грудино-ключично-сосцевидную мышцу; предтрахеальная №3 — лопаточно-ключичный "
        "апоневроз, «парус Рише», покрывает мышцы ниже подъязычной кости; предпозвоночная №5 — от основания черепа "
        "до III грудного позвонка, образует костно-фиброзный футляр для глубоких мышц шеи) и надподъязычная "
        "(2 пластинки: поверхностная — продолжается на голове в f. parotidea et masseterica; глубокая — покрывает "
        "нижнюю поверхность челюстно-подъязычной мышцы, продолжается в f. buccopharyngea).\n"
        "3. <b>Внутришейная фасция</b>, <i>f. endocervicalis</i> (№4) — париетальная пластинка выстилает полость "
        "шеи изнутри, образуя фиброзный футляр для сосудисто-нервного пучка; висцеральная пластинка раздельно "
        "покрывает органы шеи (глотку, пищевод, гортань, трахею, щитовидную железу).\n\n"
        "<b>Межфасциальные клетчаточные пространства шеи</b> (кратко): надгрудинное межапоневротическое "
        "(замкнутое, между фасциями №2 и №3, книзу образует слепой карман Грубера); предорганное (продолжается в "
        "переднее средостение); позадиорганное (продолжается в заднее средостение); предпозвоночное (замкнутое, "
        "содержит truncus sympathicus); боковое межапоневротическое (сообщается с подмышечной впадиной); "
        "предлестничный и межлестничный промежутки (содержат v./a. subclavia и plexus brachialis); "
        "поднижнечелюстное пространство; зачелюстная ямка (содержит околоушную железу).\n\n"
        "<b>Кровоснабжение и иннервация (кратко):</b> артерии — ветви <i>a. carotis externa</i> "
        "(<i>occipitalis, sternocleidomastoidea, facialis, lingualis, thyroidea superior</i>) и <i>a. "
        "subclavia</i> (<i>vertebralis, transversa colli, tr. thyrocervicalis, tr. costocervicalis</i>). Нервы: "
        "<i>n. mylohyoideus</i> (V пара) — m. mylohyoideus, переднее брюшко m. digastricus; <i>n. facialis</i> "
        "(VII пара) — platysma, m. stylohyoideus, заднее брюшко m. digastricus; <i>n. accessorius</i> (XI пара) — "
        "m. sternocleidomastoideus; ветви шейного сплетения — остальные мышцы шеи."
    ),
}

neck_muscles = topic("Мышцы шеи", "🦒", [n1, n2, n3])
data["myology"]["topics"]["neck_muscles"] = neck_muscles

with open("anatomy.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

tp = data["myology"]["topics"]["neck_muscles"]
print("neck_muscles pages:", len(tp["material"]))
for m in tp["material"]:
    print(f"  {m['id']}: {len(m['content'])} chars")
