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
    original = tb.DYNAMIC_COURSES
    tb.DYNAMIC_COURSES = [{
        "id": "operative_surgery",
        "course": 2,
        "title": "Оперативная хирургия",
        "emoji": "🔪",
        "description": "Кафедральный курс",
        "ai_mode": "latin",
        "sections": [{
            "id": "general",
            "title": "Общая техника",
            "lessons": [{
                "id": "lesson_one",
                "title": "Разъединение тканей",
                "content": "<b>Основной материал</b>",
                "sources": ["practice.pdf"],
            }],
        }],
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
        print("dynamic generated courses: OK")
    finally:
        tb.DYNAMIC_COURSES = original


if __name__ == "__main__":
    asyncio.run(main())
