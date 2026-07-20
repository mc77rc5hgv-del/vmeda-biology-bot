import json

path = "/home/user/vmeda-biology-bot/chemistry_tasks.json"
with open(path, encoding="utf-8") as f:
    data = json.load(f)

old = data["topics"]

# Desired order per the 3 "Контрольная работа" screenshots
order_by_title = [
    "Способы выражения концентрации",                                  # КР1.1
    "Коллигативные свойства растворов",                                # КР1.2
    "Дисперсные системы. Золи",                                        # КР1.3
    "Химическая термодинамика",                                        # КР1.4
    "Химическое равновесие",                                           # КР1.5
    "pH сильных кислот и оснований",                                   # КР2.1
    "pH слабых кислот и оснований",                                    # КР2.2
    "Гидролиз солей",                                                  # КР2.3
    "Буферные системы",                                                # КР2.4
    "Расчёты в объёмном анализе",                                      # КР2.5
    "Гетерогенные равновесия. Произведение растворимости",             # КР3.1
    "Комплексные соединения",                                          # КР3.2
    "Уравнение Нернста",                                               # КР3.3
    "Хлорактивные соединения",                                         # КР3.4
    "Гальванические элементы",                                         # КР3.5
]

title_to_topic = {t["title"]: t for t in old.values()}

assert len(title_to_topic) == len(old), "duplicate titles!"
for title in order_by_title:
    assert title in title_to_topic, f"missing title: {title}"
assert len(order_by_title) == len(old), "count mismatch"

new_topics = {}
for i, title in enumerate(order_by_title, start=1):
    new_topics[str(i)] = title_to_topic[title]

data["topics"] = new_topics

with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

for k in sorted(data["topics"].keys(), key=int):
    print(k, data["topics"][k]["title"])
