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

# ==================== 7. МЫШЦЫ ГОЛОВЫ ====================

h1 = {
    "id": "head_masticatory",
    "title": "Жевательные мышцы",
    "content": (
        "Границы головы: подбородочный выступ, тело и ветвь нижней челюсти, наружный слуховой проход, "
        "сосцевидный отросток, верхняя выйная линия, наружный затылочный выступ.\n\n"
        "<b>Классификация мышц головы по функции и расположению:</b>\n"
        "I. <b>Жевательные мышцы</b>: <i>mm. masseter, temporalis, pterygoideus lateralis, pterygoideus "
        "medialis</i>.\n"
        "II. <b>Мимические мышцы</b>: 1) мышцы крыши черепа — <i>m. epicranius</i>; 2) мышцы наружного уха — "
        "<i>mm. auriculares anterior, superior, posterior</i>; 3) мышцы окружности глаза — <i>mm. orbicularis "
        "oculi, corrugator supercilii, procerus</i>; 4) мышцы носа — <i>m. nasalis</i>; 5) мышцы окружности рта — "
        "<i>mm. levator labii superioris, zygomaticus major et minor, risorius, depressor anguli oris, levator "
        "anguli oris, depressor labii inferioris, mentalis, buccinator, orbicularis oris</i>.\n\n"
        "<b>По происхождению</b> мышцы головы краниальные: жевательные — производные I висцеральной дуги "
        "(иннервация из тройничного нерва); мимические — производные II висцеральной дуги (иннервация из "
        "лицевого нерва).\n\n"
        f"{D}\n\n"
        "<b>I. Жевательные мышцы</b>\n\n"
        + mus("Жевательная мышца", "m. masseter", "arcus zygomaticus", "tuberositas masseterica mandibulae",
              "поднимание нижней челюсти")
        + "\n\n"
        + mus("Височная мышца", "m. temporalis", "planum temporale", "processus coronoideus mandibulae",
              "поднимание нижней челюсти (передние пучки); смещение нижней челюсти назад (задние пучки)")
        + "\n\n"
        + mus("Латеральная крыловидная мышца", "m. pterygoideus lateralis",
              "facies infratemporalis alae majoris et facies externa laminae lateralis processus pterygoidei "
              "ossis sphenoidalis",
              "fovea pterygoidea mandibulae",
              "смещение нижней челюсти в противоположную сторону (при одностороннем сокращении); движение "
              "нижней челюсти вперёд (при двустороннем)")
        + "\n\n"
        + mus("Медиальная крыловидная мышца", "m. pterygoideus medialis",
              "fossa pterygoidea processus pterygoidei ossis sphenoidalis", "tuberositas pterygoidea mandibulae",
              "поднимание нижней челюсти")
        + f"\n\n{D}\n\n"
        "<b>Жировое тело щеки</b>, <i>corpus adiposum buccae</i>, расположено между щечной и жевательной мышцами "
        "в фиброзном футляре; имеет 3 отростка: височный, глазничный и крылонёбный.\n\n"
        "<b>Кровоснабжение и иннервация жевательных мышц:</b> артерии — <i>aa. temporales profundae, a. "
        "masseterica, rr. pterygoidei</i> (из <i>a. maxillaris</i> из <i>a. carotis externa</i>); <i>a. transversa "
        "faciei</i> (из <i>a. temporalis superficialis</i>). Нервы — <i>n. massetericus, nn. temporales "
        "profundi, nn. pterygoidei medialis et lateralis</i> из <i>n. mandibularis</i> (ветвь тройничного нерва, "
        "V пара)."
    ),
}

h2 = {
    "id": "head_mimic_upper",
    "title": "Мимические мышцы крыши черепа, уха, глаза, носа",
    "content": (
        "<b>II. Мимические мышцы</b>\n\n"
        "<b>1. Мышцы крыши черепа</b>\n\n"
        + mus("Надчерепная мышца", "m. epicranius",
              "основная часть — затылочно-лобная мышца, <i>m. occipitofrontalis</i>: venter occipitalis — linea "
              "nuchae superior, переходящее в galea aponeurotica; venter frontalis — начинается от galea "
              "aponeurotica",
              "кожа бровей",
              "поднимание бровей (лобное брюшко)",
              "сухожильный шлем (galea aponeurotica) прочно соединён с кожей и надкостницей, поэтому при "
              "сокращении m. epicranius волосистая часть головы приходит в движение вместе с шлемом; при травмах "
              "возможно образование поднадкостничных гематом")
        + f"\n\n{D}\n\n"
        "<b>2. Мышцы наружного уха</b>\n\n"
        + mus("Передняя, верхняя и задняя ушные мышцы", "mm. auriculares anterior, superior et posterior",
              "—", "—", "развиты слабо, могут обеспечивать движения ушной раковины лишь у некоторых людей")
        + f"\n\n{D}\n\n"
        "<b>3. Мышцы окружности глаза</b>\n\n"
        + mus("Круговая мышца глаза", "m. orbicularis oculi", "—", "—",
              "3 части: глазничная (<i>pars orbitalis</i>, окаймляет вход в глазницу), вековая (<i>pars "
              "palpebralis</i>, лежит под кожей век), слёзная (<i>pars lacrimalis</i>, от заднего слёзного "
              "гребня к слёзному мешку); функция: pars lacrimalis — расширение слёзного мешка и поступление в "
              "него слёзной жидкости; pars palpebralis — смыкание век; pars orbitalis — образование складок в "
              "окружности глазницы")
        + "\n\n"
        + mus("Мышца, сморщивающая бровь", "m. corrugator supercilii", "pars nasalis ossis frontalis",
              "кожа брови", "смещение брови вниз и медиально")
        + "\n\n"
        + mus("Мышца гордецов", "m. procerus", "спинка носа", "кожа надпереносья",
              "образование кожных складок в области надпереносья")
        + f"\n\n{D}\n\n"
        "<b>4. Мышцы носа</b>\n\n"
        + mus("Носовая мышца", "m. nasalis",
              "juga alveolaria верхнего клыка и латерального резца",
              "а) поперечная часть (<i>pars transversa</i>) — соединяется с одноимённой частью противоположной "
              "стороны на спинке носа; б) крыльная часть (<i>pars alaris</i>) — кожа спинки носа",
              "поперечная часть суживает отверстие носа; крыльная часть опускает крыло носа")
    ),
}

h3 = {
    "id": "head_mimic_mouth",
    "title": "Мимические мышцы окружности рта",
    "content": (
        "<b>5. Мышцы окружности рта</b>\n\n"
        + mus("Круговая мышца рта", "m. orbicularis oris",
              "губная часть (<i>pars labialis</i>) залегает в толще губ; краевая часть (<i>pars marginalis</i>) "
              "окаймляет область рта, переходя в прилежащие мышцы", "—", "закрывание ротовой щели")
        + "\n\n"
        + mus("Мышца, поднимающая верхнюю губу", "m. levator labii superioris", "подглазничный край",
              "кожа носогубной складки", "поднимание верхней губы")
        + "\n\n"
        + mus("Большая и малая скуловые мышцы", "mm. zygomaticus major et minor", "os zygomaticum",
              "кожа угла рта и слизистая оболочка щеки", "смещение угла рта вверх и латерально")
        + "\n\n"
        + mus("Мышца смеха", "m. risorius", "f. parotidea et masseterica", "присоединяются к m. depressor "
              "anguli oris", "смещение угла рта в латеральную сторону")
        + "\n\n"
        + mus("Мышца, опускающая угол рта", "m. depressor anguli oris", "нижний край mandibulae",
              "кожа угла рта", "смещение угла рта вниз")
        + "\n\n"
        + mus("Мышца, поднимающая угол рта", "m. levator anguli oris", "fossa canina",
              "кожа и слизистая оболочка верхней губы", "смещение угла рта вверх")
        + "\n\n"
        + mus("Мышца, опускающая нижнюю губу", "m. depressor labii inferioris",
              "mandibula (под foramen mentale)", "кожа и слизистая оболочка нижней губы",
              "опускание нижней губы; смещение её в латеральную сторону")
        + "\n\n"
        + mus("Подбородочная мышца", "m. mentalis", "jugum alveolare mandibulae", "кожа подбородка",
              "поднимание кожи подбородка")
        + "\n\n"
        + mus("Щечная мышца", "m. buccinator", "crista buccinatoria mandibulae; raphe pterygomandibulare",
              "слизистая оболочка щеки, верхней и нижней губ",
              "смещение угла рта назад, прижимание щеки")
        + f"\n\n{D}\n\n"
        "<b>Отличия мимических мышц от прочих скелетных мышц:</b>\n"
        "1. Начинаются от костных точек, а заканчиваются в кожных покровах (то есть не имеют типичного "
        "прикрепления к двум костям);\n"
        "2. Располагаются преимущественно вокруг естественных отверстий (глазная щель, ротовая щель, ноздри, "
        "наружный слуховой проход);\n"
        "3. Покрыты, как правило, не собственной, а поверхностной фасцией."
    ),
}

h4 = {
    "id": "head_fascia_topography",
    "title": "Фасции и топография головы",
    "content": (
        "<b>Фасции головы</b>\n"
        "1. <b>Поверхностная фасция головы</b>, <i>f. capitis superficialis</i>, в виде перимизия покрывает "
        "большинство мимических мышц.\n"
        "2. <b>Собственная фасция головы</b>, <i>f. capitis propria</i>, имеет 4 части:\n"
        "1) <b>височная фасция</b>, <i>f. temporalis</i>, начинается от <i>linea temporalis superior</i> и "
        "делится на 2 пластинки: поверхностную (прикрепляется к наружной поверхности <i>arcus zygomaticus</i>) и "
        "глубокую (к внутренней поверхности дуги);\n"
        "2) <b>фасция жевательной мышцы</b>, <i>f. masseterica</i>, покрывает m. masseter;\n"
        "3) <b>фасция околоушной слюнной железы</b>, <i>f. parotidea</i>, образует капсулу для железы;\n"
        "4) <b>щёчно-глоточная фасция</b>, <i>fascia buccopharyngea</i>, покрывает наружную поверхность m. "
        "buccinator и боковую стенку глотки.\n"
        "Фасция, покрывающая крыловидные мышцы, имеет вид перимизия.\n\n"
        f"{D}\n\n"
        "<b>Топография головы</b>\n"
        "• <b>Межапоневротическое височное пространство</b>, <i>spatium interaponeuroticum temporale</i>, "
        "костно-фиброзное, между поверхностной и глубокой пластинками височной фасции и верхним краем скуловой "
        "дуги; содержимое — жировая клетчатка;\n"
        "• <b>Подапоневротическое височное пространство</b>, <i>spatium subaponeuroticum temporale</i>, "
        "костно-фиброзное, между <i>planum temporale</i> и глубокой пластинкой височной фасции; содержимое — "
        "височная мышца с сосудами и нервами, жировая клетчатка;\n"
        "• <b>Височно-крыловидный промежуток</b>, <i>interstitium temporopterygoideum</i> — межмышечный, между "
        "латеральной крыловидной и височной мышцами; содержимое — клетчатка, верхнечелюстная артерия и её ветви, "
        "притоки крыловидного венозного сплетения;\n"
        "• <b>Межкрыловидный промежуток</b>, <i>interstitium interpterygoideum</i> — межмышечный, между "
        "медиальной и латеральной крыловидными мышцами; содержимое — клетчатка, <i>a. maxillaris</i> и её ветви, "
        "ветви <i>n. mandibularis</i>, притоки крыловидного венозного сплетения.\n\n"
        "<b>Кровоснабжение и иннервация мимических мышц:</b> артерии — многочисленные ветви <i>a. carotis "
        "externa</i> (occipitalis, auricularis posterior, temporalis superficialis с её ветвями, facialis, "
        "maxillaris) и <i>a. carotis interna</i> (a. ophthalmica с ветвями supraorbitalis, supratrochlearis, "
        "palpebrales, dorsalis nasi). Нервы — <i>n. facialis</i> (VII пара) для всех мимических мышц."
    ),
}

head_muscles = topic("Мышцы головы", "🗣", [h1, h2, h3, h4])
data["myology"]["topics"]["head_muscles"] = head_muscles

with open("anatomy.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

tp = data["myology"]["topics"]["head_muscles"]
print("head_muscles pages:", len(tp["material"]))
for m in tp["material"]:
    print(f"  {m['id']}: {len(m['content'])} chars")
