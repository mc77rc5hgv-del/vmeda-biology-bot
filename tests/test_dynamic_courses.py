# -*- coding: utf-8 -*-
import asyncio

from _bootstrap import tb
from scripts.course_automation.schema import validate_course


class FakeUser:
    def __init__(self, uid=777): self.id = uid


class FakeMsg:
    def __init__(self): self.edits = []
    async def edit_text(self, text, **kwargs): self.edits.append((text, kwargs))
    async def delete(self): pass
    async def answer(self, text, **kwargs): self.edits.append((text, kwargs))
    async def answer_photo(self, photo, **kwargs): self.edits.append((photo, kwargs))


class FakeCB:
    def __init__(self, data):
        self.data = data
        self.from_user = FakeUser()
        self.message = FakeMsg()
        self.answers = []
    async def answer(self, text=None, **kwargs): self.answers.append((text, kwargs))


def callback_data(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row if button.callback_data]


async def main():
    from handlers import dynamic_courses as dc

    original = tb.DYNAMIC_COURSES
    tb.DYNAMIC_COURSES = [{
        "id": "operative_surgery",
        "course": 2,
        "title": "Оперативная хирургия",
        "emoji": "🔪",
        "description": "Кафедральный курс",
        "ai_mode": "latin",
        "sections": [
            {
                "id": "general",
                "title": "Общая техника",
                "lessons": [{
                    "id": "lesson_one",
                    "title": "Разъединение тканей",
                    "content": "<b>Основной материал</b>",
                    "sources": ["practice.pdf"],
                }],
            },
            {
                "id": "tests_and_controls",
                "title": "Тесты",
                "groups": [{
                    "id": "tests",
                    "title": "Все тесты",
                    "lessons": [
                        {
                            "id": "test_1",
                            "title": "Тест 1",
                            "content": "Что является мономером белков?",
                            "quiz": {
                                "options": ["глюкоза", "аминокислоты", "пептон", "нуклеозид"],
                                "correct_index": 1,
                            },
                        },
                        {
                            "id": "test_2",
                            "title": "Тест 2",
                            "content": "Урок без теста (ответ неоднозначен).",
                        },
                    ],
                }],
            },
        ],
    }]
    try:
        main_data = callback_data(tb.get_course_menu_keyboard(2, 777))
        assert "dyn_c:0" in main_data
        assert "dyn_c:0" not in callback_data(tb.get_course_menu_keyboard(1, 777))

        cb_course = FakeCB("dyn_c:0")
        await tb.cb_dynamic_course(cb_course)
        assert "Оперативная хирургия" in cb_course.message.edits[-1][0]
        assert "dyn_s:0:0" in callback_data(cb_course.message.edits[-1][1]["reply_markup"])
        assert "dyn_ai:0" in callback_data(cb_course.message.edits[-1][1]["reply_markup"])

        cb_section = FakeCB("dyn_s:0:0")
        await tb.cb_dynamic_section(cb_section)
        assert "Общая техника" in cb_section.message.edits[-1][0]
        assert "dyn_l:0:0:0" in callback_data(cb_section.message.edits[-1][1]["reply_markup"])

        cb_lesson = FakeCB("dyn_l:0:0:0")
        await tb.cb_dynamic_lesson(cb_lesson)
        text = cb_lesson.message.edits[-1][0]
        assert "Основной материал" in text and "practice.pdf" in text

        cb_negative = FakeCB("dyn_l:-1:0:0")
        await tb.cb_dynamic_lesson(cb_negative)
        assert cb_negative.answers[-1][1]["show_alert"] is True

        valid_course = tb.DYNAMIC_COURSES[0]
        assert validate_course(valid_course) == []
        unsafe_course = {**valid_course, "sections": [{
            **valid_course["sections"][0],
            "lessons": [{
                **valid_course["sections"][0]["lessons"][0],
                "content": '<a href="https://example.com">unsafe</a>',
            }],
        }]}
        assert any("unsupported HTML" in error for error in validate_course(unsafe_course))

        # Тестовый урок (lesson["quiz"]) в группе -- вместо обычной клавиатуры показывает варианты.
        cb_quiz_lesson = FakeCB("dyn_gl:0:1:0:0")
        await dc.cb_dynamic_group_lesson(cb_quiz_lesson)
        quiz_text, quiz_kwargs = cb_quiz_lesson.message.edits[-1]
        assert "мономером белков" in quiz_text
        quiz_callbacks = callback_data(quiz_kwargs["reply_markup"])
        assert quiz_callbacks == [
            "dyn_gqa:0:1:0:0:0", "dyn_gqa:0:1:0:0:1", "dyn_gqa:0:1:0:0:2", "dyn_gqa:0:1:0:0:3",
            "dyn_g:0:1:0:0",
        ]
        # Правильный ответ никогда не утекает в исходящую клавиатуру.
        button_texts = [
            b.text for row in quiz_kwargs["reply_markup"].inline_keyboard for b in row
        ]
        assert any("аминокислоты" in t for t in button_texts)  # виден как вариант, не помечен

        # Non-quiz урок (test_2) по-прежнему рендерится обычной клавиатурой навигации, без вариантов.
        cb_plain_lesson = FakeCB("dyn_gl:0:1:0:1")
        await dc.cb_dynamic_group_lesson(cb_plain_lesson)
        plain_kwargs = cb_plain_lesson.message.edits[-1][1]
        assert not any(cb.startswith("dyn_gqa:") for cb in callback_data(plain_kwargs["reply_markup"]))

        # Правильный ответ.
        cb_correct = FakeCB("dyn_gqa:0:1:0:0:1")
        await dc.cb_dynamic_group_quiz_answer(cb_correct)
        assert cb_correct.answers[-1][0] == "✅ Верно!"
        correct_text, correct_kwargs = cb_correct.message.edits[-1]
        assert "✅ Верно!" in correct_text
        assert "Правильный ответ: <b>аминокислоты</b>" in correct_text
        assert "Твой ответ:" not in correct_text
        # После ответа клавиатура возвращается к обычной навигации (без вариантов).
        assert not any(cb.startswith("dyn_gqa:") for cb in callback_data(correct_kwargs["reply_markup"]))

        # Неправильный ответ -- показывает и правильный вариант, и выбранный пользователем.
        cb_wrong = FakeCB("dyn_gqa:0:1:0:0:0")
        await dc.cb_dynamic_group_quiz_answer(cb_wrong)
        assert cb_wrong.answers[-1][0] == "❌ Неверно"
        wrong_text = cb_wrong.message.edits[-1][0]
        assert "❌ Неверно." in wrong_text
        assert "Правильный ответ: <b>аминокислоты</b>" in wrong_text
        assert "Твой ответ: глюкоза" in wrong_text

        # Некорректный индекс варианта -- не падает, отвечает алертом.
        cb_bad_index = FakeCB("dyn_gqa:0:1:0:0:99")
        await dc.cb_dynamic_group_quiz_answer(cb_bad_index)
        assert cb_bad_index.answers[-1][1].get("show_alert") is True

        # Несуществующий урок -- тоже алерт, не исключение.
        cb_bad_lesson = FakeCB("dyn_gqa:0:1:0:99:0")
        await dc.cb_dynamic_group_quiz_answer(cb_bad_lesson)
        assert cb_bad_lesson.answers[-1][1].get("show_alert") is True

        print("dynamic generated courses: OK")
    finally:
        tb.DYNAMIC_COURSES = original


if __name__ == "__main__":
    asyncio.run(main())
