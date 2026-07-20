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

u5 = {
    "id": "hand_muscles",
    "title": "Мышцы кисти",
    "content": (
        "<b>Классификация мышц кисти по топографии:</b>\n"
        "I — латеральная группа (мышцы большого пальца, тенара): <i>mm. abductor pollicis brevis, flexor "
        "pollicis brevis, opponens pollicis, adductor pollicis</i>.\n"
        "II — медиальная группа (мышцы мизинца, гипотенара): <i>mm. palmaris brevis, abductor digiti minimi, "
        "flexor digiti minimi brevis, opponens digiti minimi</i>.\n"
        "III — средняя группа: <i>mm. lumbricales</i> (четыре), <i>interossei palmares</i> (три), "
        "<i>interossei dorsales</i> (четыре).\n"
        "Все мышцы кисти — спинального происхождения (вентральные), иннервация из ветвей плечевого сплетения.\n\n"
        f"{D}\n\n"
        "<b>I. Латеральная группа</b>\n\n"
        + mus("Короткая мышца, отводящая большой палец кисти", "m. abductor pollicis brevis",
              "retinaculum flexorum et os scaphoideum", "основание проксимальной фаланги большого пальца",
              "отведение большого пальца")
        + "\n\n"
        + mus("Короткий сгибатель большого пальца кисти", "m. flexor pollicis brevis",
              "поверхностная головка — retinaculum flexorum; глубокая головка — os trapezoideum",
              "проксимальная фаланга большого пальца", "сгибание большого пальца")
        + "\n\n"
        + mus("Мышца, противопоставляющая большой палец кисти", "m. opponens pollicis", "os trapezium",
              "os metacarpale I", "противопоставление большого пальца мизинцу")
        + "\n\n"
        + mus("Мышца, приводящая большой палец кисти", "m. adductor pollicis",
              "поперечная головка — os metacarpale III; косая головка — os capitatum",
              "проксимальная фаланга большого пальца", "приведение и сгибание большого пальца")
        + f"\n\n{D}\n\n"
        "<b>II. Медиальная группа</b>\n\n"
        + mus("Короткая ладонная мышца", "m. palmaris brevis", "retinaculum flexorum",
              "кожа медиального края кисти", "образование кожных складок")
        + "\n\n"
        + mus("Мышца, отводящая мизинец", "m. abductor digiti minimi", "os pisiforme et lig. pisohamatum",
              "проксимальная фаланга мизинца", "отведение мизинца")
        + "\n\n"
        + mus("Короткий сгибатель мизинца", "m. flexor digiti minimi brevis",
              "hamulus ossis hamati et retinaculum flexorum", "проксимальная фаланга мизинца",
              "сгибание проксимальной фаланги мизинца")
        + "\n\n"
        + mus("Мышца, противопоставляющая мизинец", "m. opponens digiti minimi",
              "hamulus ossis hamati et retinaculum flexorum", "os metacarpale V (локтевой край)",
              "противопоставление мизинца большому пальцу")
        + f"\n\n{D}\n\n"
        "<b>III. Средняя группа</b>\n\n"
        + mus("Червеобразные мышцы", "mm. lumbricales", "tendines m. flexor digitorum profundus",
              "проксимальные фаланги II-V пальцев, переходя в тыльный апоневроз",
              "сгибание проксимальных, разгибание средних и дистальных фаланг II-V пальцев")
        + "\n\n"
        + mus("Ладонные межкостные мышцы", "mm. interossei palmares",
              "первая — медиальная поверхность os metacarpale II; вторая и третья — латеральная поверхность "
              "ossa metacarpalia IV и V",
              "ладонная поверхность проксимальных и тыльная поверхность средних и дистальных фаланг II, IV и V "
              "пальцев",
              "приведение II, IV и V пальцев к среднему; сгибание проксимальных и разгибание средних и "
              "дистальных фаланг")
        + "\n\n"
        + mus("Тыльные межкостные мышцы", "mm. interossei dorsales",
              "обращённые друг к другу стороны соседних пястных костей",
              "ладонная поверхность проксимальных, тыльная поверхность средних и дистальных фаланг II-IV пальцев",
              "отведение II и IV пальцев от среднего; сгибание проксимальных и разгибание средних и дистальных "
              "фаланг II-IV пальцев")
    ),
}

u6 = {
    "id": "upper_limb_fascia_topography",
    "title": "Фасции и топография верхней конечности",
    "content": (
        "<b>Фасции верхней конечности</b>: поверхностная (без особенностей) и собственная (окружает мышцы, "
        "разделяясь по областям).\n"
        "• <b>Дельтовидная фасция</b> — формирует фиброзный футляр для одноимённой мышцы.\n"
        "• <b>Надостная, подостная, подлопаточная фасции</b> — образуют костно-фиброзные футляры для "
        "одноимённых мышц.\n"
        "• <b>Собственная фасция плеча</b> образует медиальную и латеральную межмышечные перегородки (медиальная "
        "формирует фиброзный футляр для сосудисто-нервного пучка плеча); фиброзные футляры для m. biceps brachii "
        "и СНП плеча; костно-фиброзные футляры для m. brachialis и m. triceps brachii.\n"
        "• <b>Собственная фасция предплечья</b> образует удерживатель сгибателей (<i>retinaculum flexorum</i>) с "
        "тремя каналами запястья (canalis carpi radialis, canalis carpi, canalis carpi ulnaris) и удерживатель "
        "разгибателей (<i>retinaculum extensorum</i>) с шестью костно-фиброзными каналами для сухожилий "
        "мышц-разгибателей.\n"
        "• <b>Собственная фасция кисти</b> образует ладонный апоневроз (<i>aponeurosis palmaris</i>), фиброзные и "
        "костно-фиброзные футляры для сухожилий сгибателей/разгибателей, мышц тенара, гипотенара и межкостных "
        "мышц.\n\n"
        f"{D}\n\n"
        "<b>Топография плечевого пояса</b>\n"
        "<b>Подмышечная ямка</b>, <i>fossa axillaris</i>, ограничена складками кожи по нижним краям <i>m. "
        "pectoralis major</i> (спереди) и <i>m. latissimus dorsi</i> (сзади). <b>Подмышечная полость</b>, "
        "<i>cavitas axillaris</i>, имеет мышечные стенки (передняя — большая и малая грудные; задняя — большая "
        "круглая и подлопаточная; медиальная — передняя зубчатая; латеральная — двуглавая и клювовидно-плечевая); "
        "содержимое — <i>a. et v. axillaris, plexus brachialis</i>, лимфатические узлы.\n"
        "<b>Трёхстороннее отверстие</b>, <i>foramen trilaterum</i> (сверху — m. subscapularis и m. teres minor; "
        "снизу — m. teres major; латерально — длинная головка трицепса): содержит <i>a. circumflexa scapulae</i> "
        "с венами.\n"
        "<b>Четырёхстороннее отверстие</b>, <i>foramen quadrilaterum</i> (сверху — те же мышцы; снизу — m. teres "
        "major; медиально — длинная головка трицепса; латерально — humerus): содержит <i>a. circumflexa humeri "
        "posterior</i> с венами и <i>n. axillaris</i>.\n\n"
        "<b>Топография кисти</b> (кратко): на ладонной поверхности синовиальные влагалища мышц-сгибателей "
        "выступают над краем <i>retinaculum flexorum</i>; влагалище сухожилия длинного сгибателя большого пальца "
        "продолжается до основания ногтевой фаланги; общее влагалище сгибателей слепо заканчивается на середине "
        "ладони (в области мизинца — до ногтевой фаланги); на II-IV пальцах сухожилия поверхностного и глубокого "
        "сгибателей имеют изолированные слепые синовиальные футляры от оснований ногтевых фаланг до головок "
        "пястных костей.\n\n"
        "<b>Кровоснабжение и иннервация мышц кисти:</b> артерии — <i>a. princeps pollicis</i> (из <i>a. "
        "radialis</i>), ветви поверхностной и глубокой ладонных дуг. Нервы: <i>n. ulnaris</i> — мышцы медиальной "
        "группы, все межкостные мышцы, глубокая головка <i>m. flexor pollicis brevis</i>, <i>m. adductor "
        "pollicis</i>, <i>mm. lumbricales III-IV</i>; <i>n. medianus</i> — поверхностная головка <i>m. flexor "
        "pollicis brevis</i>, <i>mm. abductor et opponens pollicis</i>, <i>mm. lumbricales I-II</i>."
    ),
}

tp = data["myology"]["topics"]["upper_limb_muscles"]
tp["material"].append(u5)
tp["material"].append(u6)

with open("anatomy.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("upper_limb_muscles pages now:", len(tp["material"]))
for m in tp["material"]:
    print(f"  {m['id']}: {len(m['content'])} chars")
