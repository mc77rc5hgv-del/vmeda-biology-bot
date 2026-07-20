# -*- coding: utf-8 -*-
import json

with open("anatomy.json", "r", encoding="utf-8") as f:
    data = json.load(f)

D = "━━━━━━━━━━━━━━"

l8 = {
    "id": "lower_limb_topography_supply",
    "title": "Топография нижней конечности, кровоснабжение",
    "content": (
        "<b>Топография таза:</b> <i>m. piriformis</i> делит <i>for. ischiadicum majus</i> на надгрушевидное и "
        "подгрушевидное отверстия (содержат ветви <i>a., v. et n. gluteus superior/inferior</i>, а также "
        "<i>n. ischiadicus, n. pudendus, n. cutaneus femoris posterior</i>). <b>Запирательный канал</b>, "
        "<i>canalis obturatorius</i>, содержит <i>a. obturatoria</i> с сопровождающими сосудами и <i>n. "
        "obturatorius</i>.\n\n"
        "<b>Топография бедра:</b> <b>мышечная лакуна</b>, <i>lacuna musculorum</i> (спереди/сверху — паховая "
        "связка; латерально — подвздошная кость; медиально — подвздошно-гребенчатая дуга) содержит <i>m. "
        "iliopsoas, n. femoralis, n. cutaneus femoris lateralis</i>. <b>Сосудистая лакуна</b>, <i>lacuna "
        "vasorum</i> (медиально — лакунарная связка; сзади/снизу — гребенчатая связка) содержит <i>a. et v. "
        "femoralis</i>, ветви поясничного сплетения. <b>Бедренный канал</b>, <i>canalis femoralis</i>, "
        "формируется только при бедренной грыже в медиальной части сосудистой лакуны (глубокое и поверхностное "
        "бедренные кольца). <b>Бедренный треугольник (Скарпа)</b>, <i>trigonum femorale</i> (сверху — паховая "
        "связка; латерально — портняжная мышца; медиально — длинная приводящая мышца). <b>Бедренно-подколенный "
        "канал (канал Гунтера)</b>, <i>canalis femoropopliteus</i>, — продолжение передней бедренной борозды; "
        "содержит <i>a. et v. femoralis, n. saphenus</i>.\n\n"
        "<b>Топография голени:</b> <b>подколенная ямка</b>, <i>fossa poplitea</i> (сверху/латерально — двуглавая "
        "мышца бедра; сверху/медиально — полуперепончатая мышца; снизу — обе головки икроножной мышцы). "
        "<b>Голено-подколенный канал (канал Грубера)</b>, <i>canalis cruropopliteus</i>, содержит <i>a. tibialis "
        "posterior, n. tibialis</i>. Верхний и нижний мышечно-малоберцовые каналы содержат <i>n. peroneus "
        "communis</i> с его ветвями и малоберцовые сосуды.\n\n"
        "<b>Топография стопы:</b> медиальная и латеральная подошвенные борозды содержат одноимённые сосуды "
        "(ветви <i>a. tibialis posterior</i>) и нервы (ветви <i>n. tibialis</i>).\n\n"
        f"{D}\n\n"
        "<b>Кровоснабжение и иннервация мышц нижней конечности (сводно):</b>\n\n"
        "<b>Мышцы таза:</b> артерии — <i>aa. lumbales, a. circumflexa ilium profunda, a. obturatoria, a. glutea "
        "superior, a. iliolumbalis, a. glutea inferior, a. pudenda interna</i> (из <i>a. iliaca interna/"
        "externa</i>); <i>r. ascendens, r. profundus a. circumflexae femoris medialis; r. ascendens a. "
        "circumflexae femoris lateralis</i> (из <i>a. profunda femoris</i>). Нервы — из поясничного сплетения "
        "(<i>m. iliopsoas</i>, запирательные мышцы через <i>n. obturatorius</i>) и крестцового сплетения "
        "(<i>m. piriformis, m. quadratus femoris</i>, близнецовые мышцы, обе ягодичные мышцы через <i>nn. "
        "gluteus superior/inferior</i>, <i>m. tensor fasciae latae</i>).\n\n"
        "<b>Мышцы бедра:</b> артерии — <i>a. obturatoria</i> (из <i>a. iliaca interna</i>); <i>a. circumflexa "
        "ilium superficialis, aa. pudendae externae, a. circumflexa femoris lateralis, a. circumflexa femoris "
        "medialis, aa. perforantes, a. genus descendens</i> (все — из <i>a. femoralis / a. profunda femoris</i>); "
        "<i>a. genus superior lateralis/medialis</i> (из <i>a. poplitea</i>). Нервы: <i>n. femoralis</i> — "
        "передняя группа; <i>n. obturatorius</i> — медиальная группа; <i>n. ischiadicus</i> — задняя группа.\n\n"
        "<b>Мышцы голени:</b> артерии — <i>a. genus inferior lateralis/medialis, rr. musculares, aa. surales</i> "
        "(из <i>a. poplitea</i>); ветви <i>a. tibialis anterior</i> и <i>a. tibialis posterior</i> (включая "
        "<i>a. circumflexa fibulae, a. peronea</i>). Нервы: <i>n. peroneus profundus</i> — передняя группа; "
        "<i>n. tibialis</i> — задняя группа; <i>n. peroneus superficialis</i> — латеральная группа.\n\n"
        "<b>Мышцы стопы:</b> артерии — <i>rr. malleolares</i> (из <i>a. peronea, a. tibialis anterior/"
        "posterior</i>), <i>a. tarsea lateralis, aa. metatarseae dorsales</i> (из <i>a. dorsalis pedis</i>), "
        "<i>a. plantaris medialis, a. plantaris lateralis, arcus plantaris</i>. Нервы: <i>n. peroneus "
        "profundus</i> — тыл стопы; <i>n. plantaris medialis</i> — часть медиальной группы; <i>n. plantaris "
        "lateralis</i> — латеральная группа, все межкостные мышцы и большая часть средней группы."
    ),
}

data["myology"]["topics"]["lower_limb_muscles"]["material"].append(l8)

with open("anatomy.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

tp = data["myology"]["topics"]["lower_limb_muscles"]
print("lower_limb_muscles pages now:", len(tp["material"]))
for m in tp["material"]:
    print(f"  {m['id']}: {len(m['content'])} chars")

print()
print("=== MYOLOGY SUMMARY ===")
for tk, tp in data["myology"]["topics"].items():
    print(tk, ":", len(tp["material"]), "pages, total chars:", sum(len(m["content"]) for m in tp["material"]))
