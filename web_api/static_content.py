"""Адаптер статичных предметов к общему контентному контракту Mini App.

Подключаются постепенно (см. отчёт аудита Этапа 1 — у каждого статичного предмета своя,
непохожая на остальные схема, общего адаптера для всех сразу нет и не планируется). Каждый
подключённый предмет — это НЕ весь объём контента бота по этому предмету, а осознанно
ограниченный, но честный срез: то же соотношение, что и у Биохимии/Фармакологии/Латыни/
Правоведения через content.py — реальный текст, ничего не придумано, но не 1:1 копия
навигации бота (у бота, например, тема Оперативной хирургии режется на постранично пролистываемые
подтемы под лимит сообщения Telegram — у Mini App лимита сообщения нет, поэтому тема отдаётся
одной страницей).

Подключены: «Нормальная физиология» (23 темы курса + 11 рубежных контролей), «Оперативная
хирургия» (61 тема в 4 томах — БЕЗ инструментов/проекций/станций/контрольных вопросов, это
отдельная задача на будущее), «Анатомия» (107 тем в 10 модулях — только непрерывный текст
material[], БЕЗ флеш-карточек/сопоставления/мнемоник/картиночных тестов/разбора по костям/атласа/
латинских терминов/экзаменационных банков — те же "честный срез" резоны, что и у Оперативной
хирургии), «Гистология» (71 препарат в 5 диагностиках — реальный протокол описания + реальные
микрофото, БЕЗ картиночного тренажёра "Найди препарат"), «Биология» (40 билетов по 3 вопроса +
185 вопросов зачёта — БЕЗ флеш-карточек, это тот же QUESTIONS-банк в другом режиме показа у бота,
не отдельный контент), «Химия» (16 тем теории + 15 тем задач (60 задач + 15 карточек "формулы и
алгоритм") + 6 лабораторных + 11 билетов теории (22 вопроса) + 12 билетов практики — все пять
реальных банков бота) и «Физика» (186 вопросов тестовой части + 60 вопросов "на 4/5" + 13 доп.
вопросов от преподавателей (часть — с картинкой) + 9 тем задач (49 задач + 9 карточек формул) + 8
билетов с задачами (40 задач) + 30 билетов теории (60 вопросов) + 23 тестовых билета (МСQ-блок +
задачи "Часть 2", как их же и показывает бот одним сообщением — см. handlers/physics.py — а не
раздельной навигацией по вопросу) — все семь реальных банков бота, см. SUPPORTED_SUBJECT_IDS
ниже).

В отличие от Физиологии/Оперативной хирургии (полностью бесплатные разделы бота — см. CLAUDE.md),
у Анатомии и Гистологии есть собственные гейты внутри бота, а Биология, Физика и Химия гейтятся
ОБЩИМ реферальным middleware наравне друг с другом (has_subject_access) — Химия дополнительно
ужесточает это для своих БИЛЕТОВ (theory_tickets/practice_tickets) отдельной, более строгой
проверкой chemistry_tickets_access_ok (не считает ручной/временный доступ и промо-акции
достаточными — см. handlers/chemistry.py); Физика такого дополнительного ужесточения не имеет —
один и тот же has_subject_access(user_id, "physics") гейт на все семь разделов. Этот модуль сам
НИЧЕГО не проверяет (остаётся чистой функцией формы контента над tb.ANATOMY/tb.HISTOLOGY/
tb.TICKETS/tb.QUESTIONS/tb.CHEMISTRY_*/tb.PHYSICS_*, как и остальные предметы), проверка прав
живёт в web_api/routers/subjects.py (см. _anatomy_module_access_ok/_histology_access_ok/
_biology_access_ok/_chemistry_*_access/_physics_access там), у которого есть доступ к user_id."""
import os
from html import escape

from .content import ContentNotFoundError

PHYSIOLOGY_ID = "physiology"
OPERATIVE_SURGERY_ID = "operative_surgery"
ANATOMY_ID = "anatomy"
HISTOLOGY_ID = "histology"
BIOLOGY_ID = "biology"
CHEMISTRY_ID = "chemistry"
PHYSICS_ID = "physics"
SUPPORTED_SUBJECT_IDS = {
    PHYSIOLOGY_ID, OPERATIVE_SURGERY_ID, ANATOMY_ID, HISTOLOGY_ID, BIOLOGY_ID, CHEMISTRY_ID,
    PHYSICS_ID,
}
ANATOMY_SECTION_ID = "course"
HISTOLOGY_SECTION_ID = "specimens"
BIOLOGY_TICKETS_SECTION_ID = "tickets"
BIOLOGY_QUESTIONS_SECTION_ID = "questions"
CHEMISTRY_THEORY_SECTION_ID = "theory"
CHEMISTRY_TASKS_SECTION_ID = "tasks"
CHEMISTRY_LABS_SECTION_ID = "labs"
CHEMISTRY_THEORY_TICKETS_SECTION_ID = "theory_tickets"
CHEMISTRY_PRACTICE_TICKETS_SECTION_ID = "practice_tickets"
CHEMISTRY_TICKET_SECTION_IDS = {CHEMISTRY_THEORY_TICKETS_SECTION_ID, CHEMISTRY_PRACTICE_TICKETS_SECTION_ID}
PHYSICS_TEST_SECTION_ID = "test"
PHYSICS_GRADE45_SECTION_ID = "grade45"
PHYSICS_EXTRA_SECTION_ID = "extra"
PHYSICS_TASKS_SECTION_ID = "tasks"
PHYSICS_TASK_TICKETS_SECTION_ID = "task_tickets"
PHYSICS_THEORY_TICKETS_SECTION_ID = "theory_tickets"
PHYSICS_TEST_TICKETS_SECTION_ID = "test_tickets"
PHYSICS_FLAT_SECTION_IDS = {PHYSICS_TEST_SECTION_ID, PHYSICS_GRADE45_SECTION_ID, PHYSICS_EXTRA_SECTION_ID}
PHYSICS_GROUPED_SECTION_IDS = {
    PHYSICS_TASKS_SECTION_ID, PHYSICS_TASK_TICKETS_SECTION_ID,
    PHYSICS_THEORY_TICKETS_SECTION_ID, PHYSICS_TEST_TICKETS_SECTION_ID,
}

PHYSIOLOGY_PAGE_CHAR_BUDGET = 6_000


def list_subject_summaries(tb) -> list[dict]:
    summaries = []
    if tb.PHYSIOLOGY:
        summaries.append({
            "id": PHYSIOLOGY_ID,
            "title": "Нормальная физиология",
            "emoji": "🫀",
            "description": "Структурированный курс, тесты и рубежные контроли",
            "course": 2,
            "has_ai": True,
        })
    if tb.OPERATIVE_SURGERY:
        summaries.append({
            "id": OPERATIVE_SURGERY_ID,
            "title": "Оперативная хирургия",
            "emoji": "🔪",
            "description": "61 тема в 4 томах — топографическая анатомия и оперативная техника",
            "course": 2,
            "has_ai": True,
        })
    if tb.ANATOMY:
        summaries.append({
            "id": ANATOMY_ID,
            "title": "Анатомия",
            "emoji": "🦴",
            "description": "107 тем в 10 модулях — часть открыта всем, часть по подписке",
            "course": 1,
            "has_ai": True,
        })
    if tb.HISTOLOGY:
        summaries.append({
            "id": HISTOLOGY_ID,
            "title": "Гистология",
            "emoji": "🔬",
            "description": "71 препарат в 5 диагностиках — протокол описания и реальные микрофото",
            "course": 1,
            "has_ai": True,
        })
    if tb.TICKETS or tb.QUESTIONS:
        summaries.append({
            "id": BIOLOGY_ID,
            "title": "Биология",
            "emoji": "🧬",
            "description": "40 билетов и 185 вопросов зачёта",
            "course": 1,
            "has_ai": True,
        })
    if tb.CHEMISTRY_THEORY or tb.CHEMISTRY_TASKS or tb.CHEMISTRY_LABS:
        summaries.append({
            "id": CHEMISTRY_ID,
            "title": "Химия",
            "emoji": "⚗️",
            "description": "Теория, задачи, лабораторные и билеты",
            "course": 1,
            "has_ai": True,
        })
    if tb.PHYSICS_QUESTIONS or tb.PHYSICS_TASKS:
        summaries.append({
            "id": PHYSICS_ID,
            "title": "Физика",
            "emoji": "⚛️",
            "description": "Тестовая часть, задачи и билеты всех видов",
            "course": 1,
            "has_ai": True,
        })
    return summaries


def _summary_by_id(tb, subject_id: str) -> dict:
    for summary in list_subject_summaries(tb):
        if summary["id"] == subject_id:
            return summary
    raise ContentNotFoundError(f"статичный предмет {subject_id!r} не найден")


def get_subject_detail(tb, subject_id: str) -> dict:
    summary = _summary_by_id(tb, subject_id)
    if subject_id == ANATOMY_ID:
        total_topics = sum(len(module.get("topics", {})) for module in tb.ANATOMY.values())
        summary["sections"] = [
            {"id": ANATOMY_SECTION_ID, "title": "Курс", "item_count": total_topics, "kind": "grouped"},
        ]
        return summary

    if subject_id == PHYSIOLOGY_ID:
        physiology = tb.PHYSIOLOGY
        summary["sections"] = [
            {
                "id": "course",
                "title": "Курс",
                "item_count": len(physiology.get("topics", [])),
                "kind": "flat",
            },
            {
                "id": "boundary-controls",
                "title": "Рубежные контроли",
                "item_count": sum(
                    len(_boundary_control_pages(control))
                    for control in physiology.get("boundary_controls", [])
                ),
                "kind": "grouped",
            },
        ]
        return summary

    if subject_id == HISTOLOGY_ID:
        total_specimens = sum(len(group.get("specimens", [])) for group in tb.HISTOLOGY.values())
        summary["sections"] = [
            {"id": HISTOLOGY_SECTION_ID, "title": "Препараты", "item_count": total_specimens, "kind": "grouped"},
        ]
        return summary

    if subject_id == BIOLOGY_ID:
        ticket_question_count = sum(len(t.get("questions", [])) for t in tb.TICKETS)
        summary["sections"] = [
            {
                "id": BIOLOGY_TICKETS_SECTION_ID,
                "title": "Билеты",
                "item_count": ticket_question_count,
                "kind": "grouped",
            },
            {
                "id": BIOLOGY_QUESTIONS_SECTION_ID,
                "title": "Вопросы",
                "item_count": len(tb.QUESTIONS),
                "kind": "flat",
            },
        ]
        return summary

    if subject_id == CHEMISTRY_ID:
        tasks_item_count = sum(
            1 + len(topic.get("tasks", [])) for topic in tb.CHEMISTRY_TASKS.values()
        )  # +1 за карточку "формулы и алгоритм" на тему -- см. _chemistry_tasks_group_items
        theory_tickets_item_count = sum(len(t.get("questions", [])) for t in tb.CHEMISTRY_THEORY_TICKETS.values())
        summary["sections"] = [
            {
                "id": CHEMISTRY_THEORY_SECTION_ID, "title": "Теория",
                "item_count": len(tb.CHEMISTRY_THEORY), "kind": "flat",
            },
            {
                "id": CHEMISTRY_TASKS_SECTION_ID, "title": "Задачи",
                "item_count": tasks_item_count, "kind": "grouped",
            },
            {
                "id": CHEMISTRY_LABS_SECTION_ID, "title": "Лабораторные",
                "item_count": len(tb.CHEMISTRY_LABS.get("labs", [])), "kind": "flat",
            },
            {
                "id": CHEMISTRY_THEORY_TICKETS_SECTION_ID, "title": "Билеты теории",
                "item_count": theory_tickets_item_count, "kind": "grouped",
            },
            {
                "id": CHEMISTRY_PRACTICE_TICKETS_SECTION_ID, "title": "Билеты практики",
                "item_count": len(tb.CHEMISTRY_PRACTICE_TICKETS), "kind": "flat",
            },
        ]
        return summary

    if subject_id == PHYSICS_ID:
        tasks_item_count = sum(
            1 + len(topic.get("tasks", [])) for topic in tb.PHYSICS_TASKS.values()
        )  # +1 за карточку формул на тему, как у Химии -- см. _physics_tasks_group_items
        task_tickets_item_count = sum(len(t.get("tasks", [])) for t in tb.PHYSICS_TASK_TICKETS.values())
        theory_tickets_item_count = sum(len(t.get("questions", [])) for t in tb.PHYSICS_THEORY_TICKETS.values())
        test_tickets_item_count = sum(
            1 + len(t.get("tasks", [])) for t in tb.PHYSICS_TEST_TICKETS.values()
        )  # +1 за МСQ-блок билета -- см. _physics_test_tickets_group_items
        summary["sections"] = [
            {
                "id": PHYSICS_TEST_SECTION_ID, "title": "Тестовая часть",
                "item_count": len(tb.PHYSICS_QUESTIONS), "kind": "flat",
            },
            {
                "id": PHYSICS_GRADE45_SECTION_ID, "title": "Вопросы на 4/5",
                "item_count": len(tb.PHYSICS_GRADE45_QUESTIONS), "kind": "flat",
            },
            {
                "id": PHYSICS_EXTRA_SECTION_ID, "title": "Доп. вопросы от преподавателей",
                "item_count": len(tb.PHYSICS_EXTRA_QUESTIONS), "kind": "flat",
            },
            {
                "id": PHYSICS_TASKS_SECTION_ID, "title": "Задачи по темам",
                "item_count": tasks_item_count, "kind": "grouped",
            },
            {
                "id": PHYSICS_TASK_TICKETS_SECTION_ID, "title": "Билеты с задачами",
                "item_count": task_tickets_item_count, "kind": "grouped",
            },
            {
                "id": PHYSICS_THEORY_TICKETS_SECTION_ID, "title": "Билеты теоретической части",
                "item_count": theory_tickets_item_count, "kind": "grouped",
            },
            {
                "id": PHYSICS_TEST_TICKETS_SECTION_ID, "title": "Тестовые билеты",
                "item_count": test_tickets_item_count, "kind": "grouped",
            },
        ]
        return summary

    # operative_surgery
    oh = tb.OPERATIVE_SURGERY
    summary["sections"] = [
        {
            "id": "volumes",
            "title": "Тома",
            "item_count": len(oh.get("topics", [])),
            "kind": "grouped",
        },
    ]
    return summary


def get_section_detail(tb, subject_id: str, section_id: str) -> dict:
    _summary_by_id(tb, subject_id)  # бросает ContentNotFoundError на неизвестный subject_id

    if subject_id == ANATOMY_ID:
        if section_id != ANATOMY_SECTION_ID:
            raise ContentNotFoundError(f"раздел {section_id!r} не найден в анатомии")
        return {
            "id": section_id,
            "title": "Курс",
            "kind": "grouped",
            "groups": [
                {"id": module_key, "title": module["title"], "item_count": len(module.get("topics", {}))}
                for module_key, module in tb.ANATOMY.items()
            ],
        }

    if subject_id == PHYSIOLOGY_ID:
        physiology = tb.PHYSIOLOGY
        if section_id == "course":
            topics = physiology.get("topics", [])
            total = len(topics)
            return {
                "id": section_id,
                "title": "Курс",
                "kind": "flat",
                "items": [
                    {"id": topic["topic_id"], "title": topic["title"], "order": index + 1, "total": total}
                    for index, topic in enumerate(topics)
                ],
            }
        if section_id == "boundary-controls":
            return {
                "id": section_id,
                "title": "Рубежные контроли",
                "kind": "grouped",
                "groups": [
                    {
                        "id": control["control_id"],
                        "title": control["title"],
                        "item_count": len(_boundary_control_pages(control)),
                    }
                    for control in physiology.get("boundary_controls", [])
                ],
            }
        raise ContentNotFoundError(f"раздел {section_id!r} не найден в физиологии")

    if subject_id == HISTOLOGY_ID:
        if section_id != HISTOLOGY_SECTION_ID:
            raise ContentNotFoundError(f"раздел {section_id!r} не найден в гистологии")
        return {
            "id": section_id,
            "title": "Препараты",
            "kind": "grouped",
            "groups": [
                {"id": group_key, "title": group["title"], "item_count": len(group.get("specimens", []))}
                for group_key, group in tb.HISTOLOGY.items()
            ],
        }

    if subject_id == BIOLOGY_ID:
        if section_id == BIOLOGY_TICKETS_SECTION_ID:
            return {
                "id": section_id,
                "title": "Билеты",
                "kind": "grouped",
                "groups": [
                    {"id": ticket["num"], "title": ticket["title"], "item_count": len(ticket.get("questions", []))}
                    for ticket in tb.TICKETS
                ],
            }
        if section_id == BIOLOGY_QUESTIONS_SECTION_ID:
            keys = list(tb.QUESTIONS.keys())
            total = len(keys)
            return {
                "id": section_id,
                "title": "Вопросы",
                "kind": "flat",
                "items": [
                    {"id": key, "title": tb.QUESTIONS[key]["title"], "order": index + 1, "total": total}
                    for index, key in enumerate(keys)
                ],
            }
        raise ContentNotFoundError(f"раздел {section_id!r} не найден в биологии")

    if subject_id == CHEMISTRY_ID:
        if section_id == CHEMISTRY_THEORY_SECTION_ID:
            keys = list(tb.CHEMISTRY_THEORY.keys())
            total = len(keys)
            return {
                "id": section_id,
                "title": "Теория",
                "kind": "flat",
                "items": [
                    {"id": key, "title": tb.CHEMISTRY_THEORY[key]["title"], "order": index + 1, "total": total}
                    for index, key in enumerate(keys)
                ],
            }
        if section_id == CHEMISTRY_TASKS_SECTION_ID:
            return {
                "id": section_id,
                "title": "Задачи",
                "kind": "grouped",
                "groups": [
                    {"id": key, "title": topic["title"], "item_count": 1 + len(topic.get("tasks", []))}
                    for key, topic in tb.CHEMISTRY_TASKS.items()
                ],
            }
        if section_id == CHEMISTRY_LABS_SECTION_ID:
            labs = tb.CHEMISTRY_LABS.get("labs", [])
            total = len(labs)
            return {
                "id": section_id,
                "title": "Лабораторные",
                "kind": "flat",
                "items": [
                    {"id": str(lab["number"]), "title": lab["title"], "order": index + 1, "total": total}
                    for index, lab in enumerate(labs)
                ],
            }
        if section_id == CHEMISTRY_THEORY_TICKETS_SECTION_ID:
            return {
                "id": section_id,
                "title": "Билеты теории",
                "kind": "grouped",
                "groups": [
                    {"id": key, "title": ticket["title"], "item_count": len(ticket.get("questions", []))}
                    for key, ticket in tb.CHEMISTRY_THEORY_TICKETS.items()
                ],
            }
        if section_id == CHEMISTRY_PRACTICE_TICKETS_SECTION_ID:
            keys = list(tb.CHEMISTRY_PRACTICE_TICKETS.keys())
            total = len(keys)
            return {
                "id": section_id,
                "title": "Билеты практики",
                "kind": "flat",
                "items": [
                    {
                        "id": key, "title": tb.CHEMISTRY_PRACTICE_TICKETS[key]["title"],
                        "order": index + 1, "total": total,
                    }
                    for index, key in enumerate(keys)
                ],
            }
        raise ContentNotFoundError(f"раздел {section_id!r} не найден в химии")

    if subject_id == PHYSICS_ID:
        if section_id == PHYSICS_TEST_SECTION_ID:
            keys = list(tb.PHYSICS_QUESTIONS.keys())
            total = len(keys)
            return {
                "id": section_id,
                "title": "Тестовая часть",
                "kind": "flat",
                "items": [
                    {"id": key, "title": tb.PHYSICS_QUESTIONS[key]["title"], "order": index + 1, "total": total}
                    for index, key in enumerate(keys)
                ],
            }
        if section_id == PHYSICS_GRADE45_SECTION_ID:
            keys = list(tb.PHYSICS_GRADE45_QUESTIONS.keys())
            total = len(keys)
            return {
                "id": section_id,
                "title": "Вопросы на 4/5",
                "kind": "flat",
                "items": [
                    {
                        "id": key, "title": tb.PHYSICS_GRADE45_QUESTIONS[key]["title"],
                        "order": index + 1, "total": total,
                    }
                    for index, key in enumerate(keys)
                ],
            }
        if section_id == PHYSICS_EXTRA_SECTION_ID:
            keys = list(tb.PHYSICS_EXTRA_QUESTIONS.keys())
            total = len(keys)
            return {
                "id": section_id,
                "title": "Доп. вопросы от преподавателей",
                "kind": "flat",
                "items": [
                    {
                        "id": key, "title": tb.PHYSICS_EXTRA_QUESTIONS[key]["title"],
                        "order": index + 1, "total": total,
                    }
                    for index, key in enumerate(keys)
                ],
            }
        if section_id == PHYSICS_TASKS_SECTION_ID:
            return {
                "id": section_id,
                "title": "Задачи по темам",
                "kind": "grouped",
                "groups": [
                    {"id": key, "title": topic["title"], "item_count": 1 + len(topic.get("tasks", []))}
                    for key, topic in tb.PHYSICS_TASKS.items()
                ],
            }
        if section_id == PHYSICS_TASK_TICKETS_SECTION_ID:
            return {
                "id": section_id,
                "title": "Билеты с задачами",
                "kind": "grouped",
                "groups": [
                    {"id": key, "title": ticket["title"], "item_count": len(ticket.get("tasks", []))}
                    for key, ticket in tb.PHYSICS_TASK_TICKETS.items()
                ],
            }
        if section_id == PHYSICS_THEORY_TICKETS_SECTION_ID:
            return {
                "id": section_id,
                "title": "Билеты теоретической части",
                "kind": "grouped",
                "groups": [
                    {"id": key, "title": ticket["title"], "item_count": len(ticket.get("questions", []))}
                    for key, ticket in tb.PHYSICS_THEORY_TICKETS.items()
                ],
            }
        if section_id == PHYSICS_TEST_TICKETS_SECTION_ID:
            return {
                "id": section_id,
                "title": "Тестовые билеты",
                "kind": "grouped",
                "groups": [
                    {"id": key, "title": ticket["title"], "item_count": 1 + len(ticket.get("tasks", []))}
                    for key, ticket in tb.PHYSICS_TEST_TICKETS.items()
                ],
            }
        raise ContentNotFoundError(f"раздел {section_id!r} не найден в физике")

    # operative_surgery
    if section_id != "volumes":
        raise ContentNotFoundError(f"раздел {section_id!r} не найден в оперативной хирургии")
    return {
        "id": section_id,
        "title": "Тома",
        "kind": "grouped",
        "groups": [
            {"id": volume["id"], "title": volume["title"], "item_count": len(volume.get("topic_ids", []))}
            for volume in tb.OPERATIVE_SURGERY.get("volumes", [])
        ],
    }


def get_group_detail(tb, subject_id: str, section_id: str, group_id: str) -> dict:
    _summary_by_id(tb, subject_id)

    if subject_id == ANATOMY_ID:
        if section_id != ANATOMY_SECTION_ID:
            raise ContentNotFoundError(f"в разделе {section_id!r} нет групп")
        module = tb.ANATOMY.get(group_id)
        if module is None:
            raise ContentNotFoundError(f"модуль {group_id!r} не найден в анатомии")
        topics = module.get("topics", {})
        total = len(topics)
        return {
            "id": group_id,
            "title": module["title"],
            "items": [
                {"id": topic_key, "title": topic["title"], "order": index + 1, "total": total}
                for index, (topic_key, topic) in enumerate(topics.items())
            ],
        }

    if subject_id == PHYSIOLOGY_ID:
        if section_id != "boundary-controls":
            raise ContentNotFoundError(f"в разделе {section_id!r} нет групп")
        control = _find_physiology_control(tb.PHYSIOLOGY, group_id)
        pages = _boundary_control_pages(control)
        total = len(pages)
        return {
            "id": group_id,
            "title": control["title"],
            "items": [
                {"id": page["id"], "title": page["title"], "order": index + 1, "total": total}
                for index, page in enumerate(pages)
            ],
        }

    if subject_id == HISTOLOGY_ID:
        if section_id != HISTOLOGY_SECTION_ID:
            raise ContentNotFoundError(f"в разделе {section_id!r} нет групп")
        group = tb.HISTOLOGY.get(group_id)
        if group is None:
            raise ContentNotFoundError(f"диагностика {group_id!r} не найдена в гистологии")
        specimens = group.get("specimens", [])
        total = len(specimens)
        return {
            "id": group_id,
            "title": group["title"],
            "items": [
                {"id": specimen["id"], "title": specimen["title"], "order": index + 1, "total": total}
                for index, specimen in enumerate(specimens)
            ],
        }

    if subject_id == BIOLOGY_ID:
        if section_id != BIOLOGY_TICKETS_SECTION_ID:
            raise ContentNotFoundError(f"в разделе {section_id!r} нет групп")
        ticket = _biology_find_ticket(tb.TICKETS, group_id)
        questions = ticket.get("questions", [])
        total = len(questions)
        return {
            "id": group_id,
            "title": ticket["title"],
            "items": [
                {
                    "id": _biology_ticket_item_id(group_id, question["num"]),
                    "title": question["title"],
                    "order": index + 1,
                    "total": total,
                }
                for index, question in enumerate(questions)
            ],
        }

    if subject_id == CHEMISTRY_ID:
        if section_id == CHEMISTRY_TASKS_SECTION_ID:
            topic = tb.CHEMISTRY_TASKS.get(group_id)
            if topic is None:
                raise ContentNotFoundError(f"тема {group_id!r} не найдена в задачах по химии")
            return {
                "id": group_id,
                "title": topic["title"],
                "items": _chemistry_tasks_group_items(group_id, topic),
            }
        if section_id == CHEMISTRY_THEORY_TICKETS_SECTION_ID:
            ticket = tb.CHEMISTRY_THEORY_TICKETS.get(group_id)
            if ticket is None:
                raise ContentNotFoundError(f"билет {group_id!r} не найден в билетах теории химии")
            questions = ticket.get("questions", [])
            total = len(questions)
            return {
                "id": group_id,
                "title": ticket["title"],
                "items": [
                    {
                        "id": _chemistry_ticket_question_id(group_id, index),
                        "title": question["title"],
                        "order": index + 1,
                        "total": total,
                    }
                    for index, question in enumerate(questions)
                ],
            }
        raise ContentNotFoundError(f"в разделе {section_id!r} нет групп")

    if subject_id == PHYSICS_ID:
        if section_id == PHYSICS_TASKS_SECTION_ID:
            topic = tb.PHYSICS_TASKS.get(group_id)
            if topic is None:
                raise ContentNotFoundError(f"тема {group_id!r} не найдена в задачах по физике")
            return {
                "id": group_id,
                "title": topic["title"],
                "items": _physics_tasks_group_items(group_id, topic),
            }
        if section_id == PHYSICS_TASK_TICKETS_SECTION_ID:
            ticket = tb.PHYSICS_TASK_TICKETS.get(group_id)
            if ticket is None:
                raise ContentNotFoundError(f"билет {group_id!r} не найден в билетах с задачами физики")
            tasks = ticket.get("tasks", [])
            total = len(tasks)
            return {
                "id": group_id,
                "title": ticket["title"],
                "items": [
                    {
                        "id": _physics_task_item_id(group_id, task["num"]),
                        "title": task["title"],
                        "order": index + 1,
                        "total": total,
                    }
                    for index, task in enumerate(tasks)
                ],
            }
        if section_id == PHYSICS_THEORY_TICKETS_SECTION_ID:
            ticket = tb.PHYSICS_THEORY_TICKETS.get(group_id)
            if ticket is None:
                raise ContentNotFoundError(f"билет {group_id!r} не найден в билетах теории физики")
            questions = ticket.get("questions", [])
            total = len(questions)
            return {
                "id": group_id,
                "title": ticket["title"],
                "items": [
                    {
                        "id": _physics_theory_ticket_question_id(group_id, index),
                        "title": question["title"],
                        "order": index + 1,
                        "total": total,
                    }
                    for index, question in enumerate(questions)
                ],
            }
        if section_id == PHYSICS_TEST_TICKETS_SECTION_ID:
            ticket = tb.PHYSICS_TEST_TICKETS.get(group_id)
            if ticket is None:
                raise ContentNotFoundError(f"билет {group_id!r} не найден в тестовых билетах физики")
            return {
                "id": group_id,
                "title": ticket["title"],
                "items": _physics_test_tickets_group_items(group_id, ticket),
            }
        raise ContentNotFoundError(f"в разделе {section_id!r} нет групп")

    # operative_surgery
    if section_id != "volumes":
        raise ContentNotFoundError(f"в разделе {section_id!r} нет групп")
    volume = _find_oh_volume(tb.OPERATIVE_SURGERY, group_id)
    topics = _oh_volume_topics(tb.OPERATIVE_SURGERY, volume)
    total = len(topics)
    return {
        "id": volume["id"],
        "title": volume["title"],
        "items": [
            {"id": topic["id"], "title": f"{topic['number']}. {topic['title']}", "order": index + 1, "total": total}
            for index, topic in enumerate(topics)
        ],
    }


def get_material(tb, subject_id: str, section_id: str, item_id: str) -> dict:
    _summary_by_id(tb, subject_id)

    if subject_id == ANATOMY_ID:
        return _anatomy_material(tb.ANATOMY, section_id, item_id)
    if subject_id == HISTOLOGY_ID:
        return _histology_material(tb.HISTOLOGY, section_id, item_id)
    if subject_id == BIOLOGY_ID:
        return _biology_material(tb.TICKETS, tb.QUESTIONS, section_id, item_id)
    if subject_id == CHEMISTRY_ID:
        return _chemistry_material(tb, section_id, item_id)
    if subject_id == PHYSICS_ID:
        return _physics_material(tb, section_id, item_id)
    if subject_id == PHYSIOLOGY_ID:
        return _physiology_material(tb.PHYSIOLOGY, section_id, item_id)
    return _operative_surgery_material(tb.OPERATIVE_SURGERY, section_id, item_id)


# ==================== Нормальная физиология ====================

def _physiology_material(physiology: dict, section_id: str, item_id: str) -> dict:
    if section_id == "course":
        topics = physiology.get("topics", [])
        for index, topic in enumerate(topics):
            if topic.get("topic_id") == item_id:
                return {
                    "id": item_id,
                    "title": topic["title"],
                    "content_html": _physiology_topic_html(topic),
                    "sources": [],
                    "order": index + 1,
                    "total": len(topics),
                    "group_id": None,
                    "prev_id": topics[index - 1]["topic_id"] if index > 0 else None,
                    "next_id": topics[index + 1]["topic_id"] if index + 1 < len(topics) else None,
                    "media": [],
                }
        raise ContentNotFoundError(f"тема {item_id!r} не найдена в физиологии")

    if section_id == "boundary-controls":
        for control in physiology.get("boundary_controls", []):
            pages = _boundary_control_pages(control)
            for index, page in enumerate(pages):
                if page["id"] == item_id:
                    return {
                        **page,
                        "sources": [],
                        "order": index + 1,
                        "total": len(pages),
                        "group_id": control["control_id"],
                        "prev_id": pages[index - 1]["id"] if index > 0 else None,
                        "next_id": pages[index + 1]["id"] if index + 1 < len(pages) else None,
                    }
        raise ContentNotFoundError(f"страница {item_id!r} не найдена в рубежных контролях")

    raise ContentNotFoundError(f"раздел {section_id!r} не найден в физиологии")


def _find_physiology_control(physiology: dict, control_id: str) -> dict:
    for control in physiology.get("boundary_controls", []):
        if control.get("control_id") == control_id:
            return control
    raise ContentNotFoundError(f"рубежный контроль {control_id!r} не найден")


def _physiology_topic_html(topic: dict) -> str:
    parts = []
    for section in [*topic.get("sections", []), *topic.get("deepening", [])]:
        heading = escape(str(section.get("heading", "Раздел")))
        body = str(section.get("text", "")).strip()
        if body:
            parts.extend((f"<p><strong>{heading}</strong></p>", f"<p>{body}</p>"))
    return "\n".join(parts)


def _table_text(block: dict) -> str:
    lines = [str(block.get("caption", "Таблица"))]
    lines.extend(" | ".join(str(cell) for cell in row) for row in block.get("rows", []))
    return "\n".join(lines)


def _boundary_control_pages(control: dict) -> list[dict]:
    pages: list[dict] = []
    text_parts: list[str] = []
    text_length = 0

    def flush_text() -> None:
        nonlocal text_parts, text_length
        if not text_parts:
            return
        pages.append({"content_html": f"<p>{escape(chr(10).join(text_parts))}</p>", "media": []})
        text_parts = []
        text_length = 0

    for block in control.get("blocks", []):
        block_type = block.get("type")
        if block_type == "image":
            flush_text()
            relative_path = str(block.get("path", ""))
            pages.append(
                {
                    "content_html": "<p>Учебная схема к рубежному контролю.</p>",
                    "media": [
                        {
                            "path": f"images/physiology/boundary_controls/{relative_path}",
                            "caption": "Учебная схема",
                        }
                    ],
                }
            )
            continue
        piece = str(block.get("text", "")) if block_type == "text" else _table_text(block)
        if text_parts and text_length + len(piece) + 2 > PHYSIOLOGY_PAGE_CHAR_BUDGET:
            flush_text()
        text_parts.append(piece)
        text_length += len(piece) + 2
    flush_text()

    total = len(pages)
    for index, page in enumerate(pages):
        page["id"] = f"{control['control_id']}_page_{index + 1}"
        page["title"] = f"{control['title']} — часть {index + 1} из {total}"
    return pages


# ==================== Оперативная хирургия ====================
# Подключён только раздел «Тома» (61 тема, реальный текст subtopics). instrument_groups/
# projections/practical_stations/control_questions НЕ подключены в этом заходе -- честный срез,
# не весь объём бота по этому предмету (см. docstring модуля).

def _find_oh_volume(oh: dict, volume_id: str) -> dict:
    for volume in oh.get("volumes", []):
        if volume.get("id") == volume_id:
            return volume
    raise ContentNotFoundError(f"том {volume_id!r} не найден в оперативной хирургии")


def _oh_topics_by_id(oh: dict) -> dict[str, dict]:
    return {topic["id"]: topic for topic in oh.get("topics", [])}


def _oh_volume_topics(oh: dict, volume: dict) -> list[dict]:
    """Порядок берётся из volume["topic_ids"] (собственный порядок источника), а не из фильтрации
    topics по полю volume -- volumes[].topic_ids это явный, авторский порядок тем внутри тома."""
    topics_by_id = _oh_topics_by_id(oh)
    return [topics_by_id[tid] for tid in volume.get("topic_ids", []) if tid in topics_by_id]


def _oh_topic_html(topic: dict) -> str:
    parts = []
    for subtopic in topic.get("subtopics", []):
        heading = escape(str(subtopic.get("title", "")))
        body = str(subtopic.get("text", "")).strip()
        if body:
            parts.extend((f"<p><strong>{heading}</strong></p>", f"<p>{body}</p>"))
    return "\n".join(parts)


def _operative_surgery_material(oh: dict, section_id: str, item_id: str) -> dict:
    if section_id != "volumes":
        raise ContentNotFoundError(f"раздел {section_id!r} не найден в оперативной хирургии")

    topics_by_id = _oh_topics_by_id(oh)
    topic = topics_by_id.get(item_id)
    if topic is None:
        raise ContentNotFoundError(f"тема {item_id!r} не найдена в оперативной хирургии")
    volume = _find_oh_volume(oh, topic["volume"])
    siblings = _oh_volume_topics(oh, volume)
    index = next(i for i, t in enumerate(siblings) if t["id"] == item_id)

    return {
        "id": item_id,
        "title": f"{topic['number']}. {topic['title']}",
        "content_html": _oh_topic_html(topic),
        "sources": [topic["source"]] if topic.get("source") else [],
        "order": index + 1,
        "total": len(siblings),
        "group_id": volume["id"],
        "prev_id": siblings[index - 1]["id"] if index > 0 else None,
        "next_id": siblings[index + 1]["id"] if index + 1 < len(siblings) else None,
        "media": [],
    }


# ==================== Анатомия ====================
# Подключён только раздел «Курс» (107 тем в 10 модулях, реальный текст topic["material"]).
# flashcards/matching_sets/mnemonics/picture_quiz/bones_list (разбор по костям)/bone_images/
# atlas_images/latin_terms/экзаменационные банки (ТЕСТ, практика, теория) НЕ подключены в этом
# заходе — честный срез, не весь объём бота по этому предмету (см. docstring модуля). Права
# доступа (модуль бесплатный/по подписке, тех.режим) здесь НЕ проверяются — см. docstring модуля.

ANATOMY_EMPTY_MATERIAL_NOTE = "<p>Материал по этой теме пока не добавлен.</p>"


def _anatomy_find_topic(anatomy: dict, topic_id: str) -> tuple[str, dict, dict]:
    """Возвращает (module_key, module, topic). ANATOMY — dict секций -> dict тем (не список), тема
    ищется перебором модулей — то же самое, что делает handlers/anatomy.py::get_anatomy_topic_data,
    просто с модулем в возврате (он нужен и здесь, и в web_api/routers/subjects.py для гейта)."""
    for module_key, module in anatomy.items():
        topic = module.get("topics", {}).get(topic_id)
        if topic is not None:
            return module_key, module, topic
    raise ContentNotFoundError(f"тема {topic_id!r} не найдена в анатомии")


def _anatomy_topic_html(topic: dict) -> str:
    material = topic.get("material") or []
    parts = []
    for entry in material:
        title = entry.get("title")
        body = str(entry.get("content", "")).strip()
        if not body:
            continue
        if title:
            parts.append(f"<p><strong>{escape(str(title))}</strong></p>")
        parts.append(f"<p>{body}</p>")
    return "\n".join(parts) if parts else ANATOMY_EMPTY_MATERIAL_NOTE


def _anatomy_material(anatomy: dict, section_id: str, item_id: str) -> dict:
    if section_id != ANATOMY_SECTION_ID:
        raise ContentNotFoundError(f"раздел {section_id!r} не найден в анатомии")

    module_key, module, topic = _anatomy_find_topic(anatomy, item_id)
    topics = module.get("topics", {})
    topic_keys = list(topics.keys())
    index = topic_keys.index(item_id)

    return {
        "id": item_id,
        "title": topic["title"],
        "content_html": _anatomy_topic_html(topic),
        "sources": [],
        "order": index + 1,
        "total": len(topic_keys),
        "group_id": module_key,
        "prev_id": topic_keys[index - 1] if index > 0 else None,
        "next_id": topic_keys[index + 1] if index + 1 < len(topic_keys) else None,
        "media": [],
    }


# ==================== Гистология ====================
# Подключён только раздел «Препараты» (71 препарат в 5 диагностиках, реальный протокол описания
# + реальные микрофото). Картиночный тренажёр "Найди препарат" (picture_quiz-подобный режим,
# guess_image в исходных данных) НЕ подключён в этом заходе — честный срез, не весь объём бота
# по этому предмету (см. docstring модуля). Права доступа (пробный период/подписка/рефералы в
# этом месяце/промо) здесь НЕ проверяются — см. docstring модуля.

def _histology_find_specimen(histology: dict, specimen_id: str) -> tuple[str, dict, dict]:
    for group_key, group in histology.items():
        for specimen in group.get("specimens", []):
            if specimen["id"] == specimen_id:
                return group_key, group, specimen
    raise ContentNotFoundError(f"препарат {specimen_id!r} не найден в гистологии")


def _histology_specimen_html(specimen: dict) -> str:
    parts = []
    stain = specimen.get("stain")
    if stain:
        parts.append(f"<p><strong>Окраска:</strong> {escape(str(stain))}</p>")
    magnification = specimen.get("magnification")
    if magnification:
        parts.append(f"<p><strong>Увеличение:</strong> ×{escape(str(magnification))}</p>")
    protocol = str(specimen.get("protocol", "")).strip()
    for paragraph in protocol.split("\n\n"):
        paragraph = paragraph.strip()
        if paragraph:
            parts.append(f"<p>{escape(paragraph)}</p>")
    return "\n".join(parts)


def _histology_material(histology: dict, section_id: str, item_id: str) -> dict:
    if section_id != HISTOLOGY_SECTION_ID:
        raise ContentNotFoundError(f"раздел {section_id!r} не найден в гистологии")

    group_key, group, specimen = _histology_find_specimen(histology, item_id)
    specimens = group.get("specimens", [])
    index = next(i for i, s in enumerate(specimens) if s["id"] == item_id)

    return {
        "id": item_id,
        "title": specimen["title"],
        "content_html": _histology_specimen_html(specimen),
        "sources": [],
        "order": index + 1,
        "total": len(specimens),
        "group_id": group_key,
        "prev_id": specimens[index - 1]["id"] if index > 0 else None,
        "next_id": specimens[index + 1]["id"] if index + 1 < len(specimens) else None,
        "media": [
            {"path": f"images/histology/{path}", "caption": specimen["title"]}
            for path in specimen.get("images", [])
        ],
    }


# ==================== Биология ====================
# Подключены оба раздела: «Билеты» (40 билетов по 3 вопроса, tb.TICKETS -- список, не dict) и
# «Вопросы» (185 вопросов зачёта, tb.QUESTIONS -- dict "1".."185", уже в числовом порядке
# вставки). Флеш-карточки НЕ подключены -- это тот же QUESTIONS-банк в другом режиме показа у
# бота (переворачивающиеся карточки), не отдельный контент, так что честный срез уже покрывает
# все реальные вопросы через раздел "Вопросы".
#
# Билетный вопрос уже несёт готовый HTML (<b>...</b>, как у топиков Анатомии/ОХ) -- НЕ эскейпится.
# Вопрос из отдельного банка QUESTIONS -- обычный plain text (проверено на всех 185 записях, ни в
# одной нет HTML-тегов) -- эскейпится, как и у Гистологии.

def _biology_ticket_item_id(ticket_num: str, question_num) -> str:
    return f"{ticket_num}_{question_num}"


def _biology_find_ticket(tickets: list, ticket_num: str) -> dict:
    for ticket in tickets:
        if ticket["num"] == ticket_num:
            return ticket
    raise ContentNotFoundError(f"билет {ticket_num!r} не найден в биологии")


def _biology_find_ticket_question(tickets: list, item_id: str) -> tuple[dict, dict]:
    for ticket in tickets:
        for question in ticket.get("questions", []):
            if _biology_ticket_item_id(ticket["num"], question["num"]) == item_id:
                return ticket, question
    raise ContentNotFoundError(f"вопрос {item_id!r} не найден в билетах биологии")


def _biology_ticket_material(tickets: list, item_id: str) -> dict:
    ticket, target_question = _biology_find_ticket_question(tickets, item_id)
    questions = ticket.get("questions", [])
    index = next(i for i, q in enumerate(questions) if q["num"] == target_question["num"])

    def sibling_id(i: int) -> str:
        return _biology_ticket_item_id(ticket["num"], questions[i]["num"])

    return {
        "id": item_id,
        "title": target_question["title"],
        "content_html": target_question["answer"],
        "sources": [],
        "order": index + 1,
        "total": len(questions),
        "group_id": ticket["num"],
        "prev_id": sibling_id(index - 1) if index > 0 else None,
        "next_id": sibling_id(index + 1) if index + 1 < len(questions) else None,
        "media": [],
    }


def _biology_question_material(questions: dict, item_id: str) -> dict:
    question = questions.get(item_id)
    if question is None:
        raise ContentNotFoundError(f"вопрос {item_id!r} не найден в биологии")
    keys = list(questions.keys())
    index = keys.index(item_id)
    return {
        "id": item_id,
        "title": question["title"],
        "content_html": f"<p>{escape(str(question['answer']))}</p>",
        "sources": [],
        "order": index + 1,
        "total": len(keys),
        "group_id": None,
        "prev_id": keys[index - 1] if index > 0 else None,
        "next_id": keys[index + 1] if index + 1 < len(keys) else None,
        "media": [],
    }


def _biology_material(tickets: list, questions: dict, section_id: str, item_id: str) -> dict:
    if section_id == BIOLOGY_TICKETS_SECTION_ID:
        return _biology_ticket_material(tickets, item_id)
    if section_id == BIOLOGY_QUESTIONS_SECTION_ID:
        return _biology_question_material(questions, item_id)
    raise ContentNotFoundError(f"раздел {section_id!r} не найден в биологии")


# ==================== Химия ====================
# Подключены все пять реальных банков бота (tb.CHEMISTRY_THEORY/_TASKS/_LABS/_THEORY_TICKETS/
# _PRACTICE_TICKETS). _chemistry_material принимает весь tb (не отдельные словари, как остальные
# _*_material выше) -- единственное исключение в файле, оправданное тем, что здесь нужно РОВНО
# пять разных атрибутов сразу, а не один-два.
#
# Правило эскейпинга по полям (проверено на ВСЕХ реальных записях, см. commit message): формулы
# темы (formulas), решение задачи (solution), ответ билета теории (answer), содержимое билета
# практики (content), вывод лабораторной (summary) и текст темы теории (content у THEORY) уже
# несут готовый HTML (<b>/<i>, как у Анатомии/ОХ) -- НЕ эскейпятся. Вступление к теме задач
# (intro), условие задачи (condition) и все текстовые поля лабораторных, КРОМЕ summary, --
# обычный plain text -- эскейпятся.

def _chemistry_formulas_item_id(topic_key: str) -> str:
    return f"{topic_key}_formulas"


def _chemistry_task_item_id(topic_key: str, task_num) -> str:
    return f"{topic_key}_{task_num}"


def _chemistry_ticket_question_id(ticket_key: str, index: int) -> str:
    return f"{ticket_key}_{index}"


def _chemistry_tasks_group_items(topic_key: str, topic: dict) -> list[dict]:
    """Карточка "формулы и алгоритм" темы идёт первым пунктом группы (order=1), затем сами
    пронумерованные задачи -- реальный контент темы (intro+formulas), не выдуманный элемент
    навигации."""
    tasks = topic.get("tasks", [])
    total = 1 + len(tasks)
    items = [
        {"id": _chemistry_formulas_item_id(topic_key), "title": "📐 Формулы и алгоритм", "order": 1, "total": total},
    ]
    items.extend(
        {
            "id": _chemistry_task_item_id(topic_key, task["num"]),
            "title": task["title"],
            "order": index + 2,
            "total": total,
        }
        for index, task in enumerate(tasks)
    )
    return items


def _chemistry_theory_material(theory: dict, item_id: str) -> dict:
    topic = theory.get(item_id)
    if topic is None:
        raise ContentNotFoundError(f"тема {item_id!r} не найдена в теории химии")
    keys = list(theory.keys())
    index = keys.index(item_id)
    return {
        "id": item_id,
        "title": topic["title"],
        "content_html": topic["content"],
        "sources": [],
        "order": index + 1,
        "total": len(keys),
        "group_id": None,
        "prev_id": keys[index - 1] if index > 0 else None,
        "next_id": keys[index + 1] if index + 1 < len(keys) else None,
        "media": [],
    }


def _chemistry_formulas_html(topic: dict) -> str:
    parts = []
    intro = str(topic.get("intro", "")).strip()
    if intro:
        parts.append(f"<p>{escape(intro)}</p>")
    formulas = str(topic.get("formulas", "")).strip()
    if formulas:
        parts.append(f"<p>{formulas}</p>")
    return "\n".join(parts)


def _chemistry_task_html(task: dict) -> str:
    parts = []
    condition = str(task.get("condition", "")).strip()
    if condition:
        parts.append(f"<p><strong>Условие:</strong> {escape(condition)}</p>")
    solution = str(task.get("solution", "")).strip()
    if solution:
        parts.append(f"<p>{solution}</p>")
    return "\n".join(parts)


def _chemistry_tasks_material(tasks: dict, item_id: str) -> dict:
    for topic_key, topic in tasks.items():
        items = _chemistry_tasks_group_items(topic_key, topic)
        for index, item in enumerate(items):
            if item["id"] != item_id:
                continue
            is_formulas = index == 0
            content_html = (
                _chemistry_formulas_html(topic) if is_formulas
                else _chemistry_task_html(topic["tasks"][index - 1])
            )
            return {
                "id": item_id,
                "title": item["title"],
                "content_html": content_html,
                "sources": [],
                "order": item["order"],
                "total": item["total"],
                "group_id": topic_key,
                "prev_id": items[index - 1]["id"] if index > 0 else None,
                "next_id": items[index + 1]["id"] if index + 1 < len(items) else None,
                "media": [],
            }
    raise ContentNotFoundError(f"задача {item_id!r} не найдена в химии")


_CHEMISTRY_LAB_FIELD_LABELS = {
    "theme": "Тема",
    "condition": "Условие",
    "positive_sol": "Положительная проба",
    "negative_sol": "Отрицательная проба",
    "procedure": "Методика",
    "theory": "Теория",
    "titrant": "Титрант",
    "indicator": "Индикатор",
    "buffer": "Буферный раствор",
    "equations": "Уравнения реакций",
    "calculations": "Расчёты",
    "summary": "Вывод",
}
_CHEMISTRY_LAB_TRUSTED_HTML_FIELDS = {"summary"}  # см. проверку в commit message: только summary несёт HTML
_CHEMISTRY_EXPERIMENT_FIELD_LABELS = {
    "description": "Описание",
    "mechanism": "Механизм",
    "technique": "Техника выполнения",
    "sorbent": "Сорбент",
    "eluent": "Элюент",
    "procedure": "Ход работы",
}


def _chemistry_experiment_html(experiment: dict) -> str:
    parts = [f"<p><strong>{escape(str(experiment.get('name', 'Опыт')))}</strong></p>"]
    for field, label in _CHEMISTRY_EXPERIMENT_FIELD_LABELS.items():
        value = str(experiment.get(field, "")).strip()
        if value:
            parts.append(f"<p><strong>{label}:</strong> {escape(value)}</p>")
    return "\n".join(parts)


def _chemistry_lab_html(lab: dict) -> str:
    parts = []
    for field, label in _CHEMISTRY_LAB_FIELD_LABELS.items():
        value = lab.get(field)
        if not value:
            continue
        value = str(value).strip()
        if not value:
            continue
        body = value if field in _CHEMISTRY_LAB_TRUSTED_HTML_FIELDS else escape(value)
        parts.append(f"<p><strong>{label}:</strong></p>")
        parts.append(f"<p>{body}</p>")
    for experiment in lab.get("experiments", []):
        parts.append(_chemistry_experiment_html(experiment))
    return "\n".join(parts)


def _chemistry_labs_material(labs_data: dict, item_id: str) -> dict:
    labs = labs_data.get("labs", [])
    for index, lab in enumerate(labs):
        if str(lab["number"]) != item_id:
            continue
        return {
            "id": item_id,
            "title": lab["title"],
            "content_html": _chemistry_lab_html(lab),
            "sources": [],
            "order": index + 1,
            "total": len(labs),
            "group_id": None,
            "prev_id": str(labs[index - 1]["number"]) if index > 0 else None,
            "next_id": str(labs[index + 1]["number"]) if index + 1 < len(labs) else None,
            "media": [],
        }
    raise ContentNotFoundError(f"лабораторная {item_id!r} не найдена в химии")


def _chemistry_theory_tickets_material(theory_tickets: dict, item_id: str) -> dict:
    for ticket_key, ticket in theory_tickets.items():
        questions = ticket.get("questions", [])
        for index, question in enumerate(questions):
            if _chemistry_ticket_question_id(ticket_key, index) != item_id:
                continue
            return {
                "id": item_id,
                "title": question["title"],
                "content_html": question["answer"],
                "sources": [],
                "order": index + 1,
                "total": len(questions),
                "group_id": ticket_key,
                "prev_id": _chemistry_ticket_question_id(ticket_key, index - 1) if index > 0 else None,
                "next_id": (
                    _chemistry_ticket_question_id(ticket_key, index + 1) if index + 1 < len(questions) else None
                ),
                "media": [],
            }
    raise ContentNotFoundError(f"вопрос {item_id!r} не найден в билетах теории химии")


def _chemistry_practice_tickets_material(practice_tickets: dict, item_id: str) -> dict:
    ticket = practice_tickets.get(item_id)
    if ticket is None:
        raise ContentNotFoundError(f"билет {item_id!r} не найден в билетах практики химии")
    keys = list(practice_tickets.keys())
    index = keys.index(item_id)
    return {
        "id": item_id,
        "title": ticket["title"],
        "content_html": ticket["content"],
        "sources": [],
        "order": index + 1,
        "total": len(keys),
        "group_id": None,
        "prev_id": keys[index - 1] if index > 0 else None,
        "next_id": keys[index + 1] if index + 1 < len(keys) else None,
        "media": [],
    }


def _chemistry_material(tb, section_id: str, item_id: str) -> dict:
    if section_id == CHEMISTRY_THEORY_SECTION_ID:
        return _chemistry_theory_material(tb.CHEMISTRY_THEORY, item_id)
    if section_id == CHEMISTRY_TASKS_SECTION_ID:
        return _chemistry_tasks_material(tb.CHEMISTRY_TASKS, item_id)
    if section_id == CHEMISTRY_LABS_SECTION_ID:
        return _chemistry_labs_material(tb.CHEMISTRY_LABS, item_id)
    if section_id == CHEMISTRY_THEORY_TICKETS_SECTION_ID:
        return _chemistry_theory_tickets_material(tb.CHEMISTRY_THEORY_TICKETS, item_id)
    if section_id == CHEMISTRY_PRACTICE_TICKETS_SECTION_ID:
        return _chemistry_practice_tickets_material(tb.CHEMISTRY_PRACTICE_TICKETS, item_id)
    raise ContentNotFoundError(f"раздел {section_id!r} не найден в химии")


# ==================== Физика ====================
# Подключены все семь реальных банков бота (tb.PHYSICS_QUESTIONS/_GRADE45_QUESTIONS/
# _EXTRA_QUESTIONS/_TASKS/_TASK_TICKETS/_THEORY_TICKETS/_TEST_TICKETS). В отличие от Химии, у
# Физики нет отдельного более строгого гейта на билеты -- один has_subject_access(user_id,
# "physics") на все семь разделов (handlers/physics.py гейтит физику наравне с Биологией/Химией
# через общий реферальный middleware, без доп. ужесточения -- см. GATED_CALLBACKS_PHYSICS /
# GATED_PREFIXES_PHYSICS в services/access.py).
#
# "Тестовые билеты" (test_tickets) -- единственный раздел составной формы: каждый билет несёт И
# тестовую часть (МСQ-вопросы с вариантами и правильным ответом), И "Часть 2. Задачи" (условие +
# решение). Повторяем это ровно так, как их же одним сообщением показывает бот (cb_phys_test_ticket
# в handlers/physics.py: все МСQ-вопросы билета выводятся одним текстовым блоком с отмеченным ✅
# правильным вариантом, а не по одному вопросу с постраничной навигацией, как у "билетов теории") --
# группа билета содержит один МСQ-блок первым пунктом (order=1), затем отдельные карточки задач
# "Часть 2", если у билета вообще есть задачи (3 из 23 билетов их не имеют — см. коммит).
#
# Правило эскейпинга по полям (проверено на ВСЕХ реальных записях, см. commit message): решение
# задачи (solution) и формулы темы (formulas) уже несут готовый HTML (<b>/<u>, как у Химии) -- НЕ
# эскейпятся. Ответ вопроса зачёта/на 4-5/доп. вопроса (answer), вступление к теме задач (intro),
# условие задачи (condition), текст и варианты МСQ-вопроса (text/options) и заголовок+ответ вопроса
# билета теории (title/answer) -- обычный plain text -- эскейпятся.

def _physics_formulas_item_id(topic_key: str) -> str:
    return f"{topic_key}_formulas"


def _physics_task_item_id(scope_key: str, task_num) -> str:
    """Общий id-хелпер для задач темы (PHYSICS_TASKS), билета с задачами (PHYSICS_TASK_TICKETS) и
    задач "Часть 2" тестового билета (PHYSICS_TEST_TICKETS) -- все три коллекции задач имеют
    одинаковую форму {num, title, condition, solution} и ищутся внутри своей же группы, так что
    общий "{scope_key}_{num}" не может столкнуться между разделами."""
    return f"{scope_key}_{task_num}"


def _physics_theory_ticket_question_id(ticket_key: str, index: int) -> str:
    return f"{ticket_key}_{index}"


def _physics_test_ticket_mcq_item_id(ticket_key: str) -> str:
    return f"{ticket_key}_mcq"


def _physics_tasks_group_items(topic_key: str, topic: dict) -> list[dict]:
    """Карточка "формулы и алгоритм" темы идёт первым пунктом группы (order=1), затем сами
    пронумерованные задачи -- та же схема, что у _chemistry_tasks_group_items."""
    tasks = topic.get("tasks", [])
    total = 1 + len(tasks)
    items = [
        {"id": _physics_formulas_item_id(topic_key), "title": "📐 Формулы и алгоритм", "order": 1, "total": total},
    ]
    items.extend(
        {
            "id": _physics_task_item_id(topic_key, task["num"]),
            "title": task["title"],
            "order": index + 2,
            "total": total,
        }
        for index, task in enumerate(tasks)
    )
    return items


def _physics_test_tickets_group_items(ticket_key: str, ticket: dict) -> list[dict]:
    """МСQ-блок билета идёт первым пунктом группы (order=1, несёт ВСЕ тестовые вопросы билета
    сразу -- см. docstring раздела выше), затем задачи "Часть 2" по отдельности, если они у билета
    вообще есть (3 из 23 билетов их не имеют)."""
    tasks = ticket.get("tasks", [])
    total = 1 + len(tasks)
    items = [
        {
            "id": _physics_test_ticket_mcq_item_id(ticket_key), "title": "📝 Тестовая часть билета",
            "order": 1, "total": total,
        },
    ]
    items.extend(
        {
            "id": _physics_task_item_id(ticket_key, task["num"]),
            "title": task["title"],
            "order": index + 2,
            "total": total,
        }
        for index, task in enumerate(tasks)
    )
    return items


def _physics_question_material(questions: dict, item_id: str) -> dict:
    question = questions.get(item_id)
    if question is None:
        raise ContentNotFoundError(f"вопрос {item_id!r} не найден в физике")
    keys = list(questions.keys())
    index = keys.index(item_id)
    return {
        "id": item_id,
        "title": question["title"],
        "content_html": f"<p>{escape(str(question['answer']))}</p>",
        "sources": [],
        "order": index + 1,
        "total": len(keys),
        "group_id": None,
        "prev_id": keys[index - 1] if index > 0 else None,
        "next_id": keys[index + 1] if index + 1 < len(keys) else None,
        "media": [],
    }


def _physics_extra_question_material(tb, item_id: str) -> dict:
    questions = tb.PHYSICS_EXTRA_QUESTIONS
    question = questions.get(item_id)
    if question is None:
        raise ContentNotFoundError(f"доп. вопрос {item_id!r} не найден в физике")
    keys = list(questions.keys())
    index = keys.index(item_id)
    image = question.get("image")
    media = [{"path": os.path.join(tb.IMAGES_DIR, image), "caption": question["title"]}] if image else []
    return {
        "id": item_id,
        "title": question["title"],
        "content_html": f"<p>{escape(str(question['answer']))}</p>",
        "sources": [],
        "order": index + 1,
        "total": len(keys),
        "group_id": None,
        "prev_id": keys[index - 1] if index > 0 else None,
        "next_id": keys[index + 1] if index + 1 < len(keys) else None,
        "media": media,
    }


def _physics_task_html(task: dict) -> str:
    parts = []
    condition = str(task.get("condition", "")).strip()
    if condition:
        parts.append(f"<p><strong>Условие:</strong> {escape(condition)}</p>")
    solution = str(task.get("solution", "")).strip()
    if solution:
        parts.append(f"<p>{solution}</p>")
    return "\n".join(parts)


def _physics_formulas_html(topic: dict) -> str:
    parts = []
    intro = str(topic.get("intro", "")).strip()
    if intro:
        parts.append(f"<p>{escape(intro)}</p>")
    formulas = str(topic.get("formulas", "")).strip()
    if formulas:
        parts.append(f"<p>{formulas}</p>")
    return "\n".join(parts)


def _physics_tasks_material(tasks: dict, item_id: str) -> dict:
    for topic_key, topic in tasks.items():
        items = _physics_tasks_group_items(topic_key, topic)
        for index, item in enumerate(items):
            if item["id"] != item_id:
                continue
            is_formulas = index == 0
            content_html = (
                _physics_formulas_html(topic) if is_formulas
                else _physics_task_html(topic["tasks"][index - 1])
            )
            return {
                "id": item_id,
                "title": item["title"],
                "content_html": content_html,
                "sources": [],
                "order": item["order"],
                "total": item["total"],
                "group_id": topic_key,
                "prev_id": items[index - 1]["id"] if index > 0 else None,
                "next_id": items[index + 1]["id"] if index + 1 < len(items) else None,
                "media": [],
            }
    raise ContentNotFoundError(f"задача {item_id!r} не найдена в физике")


def _physics_task_tickets_material(task_tickets: dict, item_id: str) -> dict:
    for ticket_key, ticket in task_tickets.items():
        tasks = ticket.get("tasks", [])
        total = len(tasks)
        for index, task in enumerate(tasks):
            if _physics_task_item_id(ticket_key, task["num"]) != item_id:
                continue
            return {
                "id": item_id,
                "title": task["title"],
                "content_html": _physics_task_html(task),
                "sources": [],
                "order": index + 1,
                "total": total,
                "group_id": ticket_key,
                "prev_id": _physics_task_item_id(ticket_key, tasks[index - 1]["num"]) if index > 0 else None,
                "next_id": (
                    _physics_task_item_id(ticket_key, tasks[index + 1]["num"]) if index + 1 < total else None
                ),
                "media": [],
            }
    raise ContentNotFoundError(f"задача {item_id!r} не найдена в билетах с задачами физики")


def _physics_theory_tickets_material(theory_tickets: dict, item_id: str) -> dict:
    for ticket_key, ticket in theory_tickets.items():
        questions = ticket.get("questions", [])
        for index, question in enumerate(questions):
            if _physics_theory_ticket_question_id(ticket_key, index) != item_id:
                continue
            return {
                "id": item_id,
                "title": question["title"],
                "content_html": f"<p>{escape(str(question['answer']))}</p>",
                "sources": [],
                "order": index + 1,
                "total": len(questions),
                "group_id": ticket_key,
                "prev_id": _physics_theory_ticket_question_id(ticket_key, index - 1) if index > 0 else None,
                "next_id": (
                    _physics_theory_ticket_question_id(ticket_key, index + 1)
                    if index + 1 < len(questions) else None
                ),
                "media": [],
            }
    raise ContentNotFoundError(f"вопрос {item_id!r} не найден в билетах теории физики")


def _physics_mcq_block_html(questions: list) -> str:
    parts = []
    for question in questions:
        parts.append(f"<p><strong>{question['num']}. {escape(str(question['text']))}</strong></p>")
        option_lines = []
        for letter, option in question.get("options", {}).items():
            marker = "✅ " if letter == question.get("correct") else ""
            option_lines.append(f"{marker}{escape(str(letter))}) {escape(str(option))}")
        parts.append("<p>" + "\n".join(option_lines) + "</p>")
    return "\n".join(parts)


def _physics_test_tickets_material(test_tickets: dict, item_id: str) -> dict:
    for ticket_key, ticket in test_tickets.items():
        items = _physics_test_tickets_group_items(ticket_key, ticket)
        for index, item in enumerate(items):
            if item["id"] != item_id:
                continue
            is_mcq_block = index == 0
            content_html = (
                _physics_mcq_block_html(ticket.get("questions", [])) if is_mcq_block
                else _physics_task_html(ticket["tasks"][index - 1])
            )
            return {
                "id": item_id,
                "title": item["title"],
                "content_html": content_html,
                "sources": [],
                "order": item["order"],
                "total": item["total"],
                "group_id": ticket_key,
                "prev_id": items[index - 1]["id"] if index > 0 else None,
                "next_id": items[index + 1]["id"] if index + 1 < len(items) else None,
                "media": [],
            }
    raise ContentNotFoundError(f"элемент {item_id!r} не найден в тестовых билетах физики")


def _physics_material(tb, section_id: str, item_id: str) -> dict:
    if section_id == PHYSICS_TEST_SECTION_ID:
        return _physics_question_material(tb.PHYSICS_QUESTIONS, item_id)
    if section_id == PHYSICS_GRADE45_SECTION_ID:
        return _physics_question_material(tb.PHYSICS_GRADE45_QUESTIONS, item_id)
    if section_id == PHYSICS_EXTRA_SECTION_ID:
        return _physics_extra_question_material(tb, item_id)
    if section_id == PHYSICS_TASKS_SECTION_ID:
        return _physics_tasks_material(tb.PHYSICS_TASKS, item_id)
    if section_id == PHYSICS_TASK_TICKETS_SECTION_ID:
        return _physics_task_tickets_material(tb.PHYSICS_TASK_TICKETS, item_id)
    if section_id == PHYSICS_THEORY_TICKETS_SECTION_ID:
        return _physics_theory_tickets_material(tb.PHYSICS_THEORY_TICKETS, item_id)
    if section_id == PHYSICS_TEST_TICKETS_SECTION_ID:
        return _physics_test_tickets_material(tb.PHYSICS_TEST_TICKETS, item_id)
    raise ContentNotFoundError(f"раздел {section_id!r} не найден в физике")
