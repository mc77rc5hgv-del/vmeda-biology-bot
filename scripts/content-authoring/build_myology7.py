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

# ==================== 8. МЫШЦЫ ВЕРХНЕЙ КОНЕЧНОСТИ ====================

u1 = {
    "id": "upper_limb_girdle",
    "title": "Мышцы плечевого пояса",
    "content": (
        "<b>Классификация мышц плечевого пояса по расположению:</b>\n"
        "I — поверхностный слой: <i>m. deltoideus</i>.\n"
        "II — глубокий слой: 1) мышцы дорсальной поверхности лопатки — <i>mm. supraspinatus, infraspinatus, "
        "teres minor, teres major</i>; 2) мышцы рёберной поверхности лопатки — <i>m. subscapularis</i>.\n"
        "Все мышцы плечевого пояса — спинального происхождения (вентральные), иннервация из ветвей плечевого "
        "сплетения.\n\n"
        f"{D}\n\n"
        "<b>I. Поверхностный слой</b>\n\n"
        + mus("Дельтовидная мышца", "m. deltoideus",
              "clavicula (латеральная треть); acromion; spina scapulae", "tuberositas deltoidea humeri",
              "сгибание и вращение плеча внутрь (передние пучки); разгибание и вращение плеча наружу (задние "
              "пучки); отведение плеча (средние пучки)")
        + f"\n\n{D}\n\n"
        "<b>II. Глубокий слой</b>\n\n"
        "<i>1) Мышцы дорсальной поверхности лопатки</i>\n\n"
        + mus("Надостная мышца", "m. supraspinatus", "fossa supraspinata",
              "tuberculum majus humeri (верхняя площадка)", "отведение плеча")
        + "\n\n"
        + mus("Подостная мышца", "m. infraspinatus", "fossa infraspinata",
              "tuberculum majus humeri (средняя площадка)", "вращение плеча наружу")
        + "\n\n"
        + mus("Малая круглая мышца", "m. teres minor", "fossa infraspinata (под m. infraspinatus)",
              "tuberculum majus humeri (нижняя площадка)", "вращение плеча наружу")
        + "\n\n"
        + mus("Большая круглая мышца", "m. teres major", "facies dorsalis scapulae (у нижнего угла)",
              "crista tuberculi minoris humeri", "приведение и вращение плеча внутрь")
        + f"\n\n{D}\n\n"
        "<i>2) Мышцы рёберной поверхности лопатки</i>\n\n"
        + mus("Подлопаточная мышца", "m. subscapularis", "fossa subscapularis", "tuberculum minus humeri",
              "приведение и вращение плеча внутрь")
        + f"\n\n{D}\n\n"
        "<b>Кровоснабжение и иннервация мышц плечевого пояса:</b> артерии — <i>a. suprascapularis</i> (из <i>a. "
        "subclavia</i>), <i>a. thoracoacromialis, aa. circumflexae humeri anterior et posterior, a. circumflexa "
        "scapulae</i> (все — из <i>a. axillaris</i>). Нервы: <i>n. axillaris</i> — <i>mm. deltoideus et teres "
        "minor</i>; <i>n. suprascapularis</i> — <i>mm. supraspinatus et infraspinatus</i>; <i>n. subscapularis</i> "
        "— <i>mm. subscapularis et teres major</i>."
    ),
}

u2 = {
    "id": "upper_limb_arm",
    "title": "Мышцы плеча",
    "content": (
        "<b>Классификация мышц плеча по топографии:</b>\n"
        "I — передняя группа: <i>mm. biceps brachii, coracobrachialis, brachialis</i>.\n"
        "II — задняя группа: <i>m. triceps brachii, m. anconeus</i>.\n"
        "Все мышцы плеча — спинального происхождения (вентральные), иннервация из ветвей плечевого сплетения.\n\n"
        f"{D}\n\n"
        "<b>I. Передняя группа</b>\n\n"
        + mus("Двуглавая мышца плеча", "m. biceps brachii",
              "caput longum — tuberculum supraglenoidale scapulae; caput breve — processus coracoideus scapulae",
              "tuberositas radii",
              "сгибание плеча и предплечья; вращение предплечья наружу (условный супинатор — за счёт апоневроза "
              "Пирогова)")
        + "\n\n"
        + mus("Клювовидно-плечевая мышца", "m. coracobrachialis", "processus coracoideus scapulae",
              "humerus (средняя треть)", "сгибание плеча")
        + "\n\n"
        + mus("Плечевая мышца", "m. brachialis", "humerus (нижняя и средняя треть)", "tuberositas ulnae",
              "сгибание в локтевом суставе")
        + f"\n\n{D}\n\n"
        "<b>II. Задняя группа</b>\n\n"
        + mus("Трёхглавая мышца плеча", "m. triceps brachii",
              "caput longum — tuberculum infraglenoidale scapulae; caput laterale — задне-латеральная "
              "поверхность humerus; caput mediale — задняя поверхность humerus",
              "olecranon",
              "разгибание в локтевом суставе; длинная головка — разгибание в плечевом суставе и приведение плеча "
              "к туловищу")
        + "\n\n"
        + mus("Локтевая мышца", "m. anconeus", "epicondylus lateralis humeri", "olecranon",
              "разгибание в локтевом суставе")
        + f"\n\n{D}\n\n"
        "<b>Топография плеча и локтевой области</b>\n"
        "На плече по обе стороны от m. biceps brachii проходят медиальная и латеральная двуглавые борозды "
        "(<i>sulcus bicipitalis medialis et lateralis</i>); в медиальной проходит сосудисто-нервный пучок плеча.\n"
        "<b>Плечемышечный канал</b> (спиральный канал, канал лучевого нерва), <i>canalis humeromuscularis</i>, "
        "образован спереди плечевой костью, сзади — трёхглавой мышцей; содержимое — <i>n. radialis, a. profunda "
        "brachii</i> и соименные вены.\n"
        "<b>Локтевая ямка</b>, <i>fossa cubitalis</i>, ограничена m. brachioradialis (латерально) и m. pronator "
        "teres (медиально); дно образует m. brachialis. Медиальная и латеральная передние локтевые борозды, "
        "задние латеральная и медиальная локтевые борозды содержат анастомозы сосудистой сети локтевого сустава "
        "(<i>rete articulare cubiti</i>) и соответствующие нервы.\n\n"
        "<b>Кровоснабжение и иннервация мышц плеча:</b> артерии — <i>aa. circumflexae humeri anterior et "
        "posterior</i> (из <i>a. axillaris</i>); <i>rr. musculares a. brachialis, a. profunda brachii</i> с её "
        "ветвями. Нервы: <i>n. musculocutaneus</i> — мышцы передней группы; <i>n. radialis</i> — мышцы задней "
        "группы."
    ),
}

data["myology"]["topics"]["upper_limb_muscles"] = topic("Мышцы верхней конечности", "🖐", [u1, u2])

with open("anatomy.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

tp = data["myology"]["topics"]["upper_limb_muscles"]
print("upper_limb_muscles pages:", len(tp["material"]))
for m in tp["material"]:
    print(f"  {m['id']}: {len(m['content'])} chars")
