# -*- coding: utf-8 -*-
import asyncio

from _bootstrap import tb


class FakeUser:
    def __init__(self, user_id=777):
        self.id = user_id


class FakeMessage:
    def __init__(self):
        self.edits = []

    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs))


class FakeCallback:
    def __init__(self, data, user_id=777):
        self.data = data
        self.from_user = FakeUser(user_id)
        self.message = FakeMessage()
        self.answers = []

    async def answer(self, text=None, **kwargs):
        self.answers.append((text, kwargs))


def button_texts(markup):
    return [button.text for row in markup.inline_keyboard for button in row]


async def main():
    maintenance = {"pharmacology"}
    assert tb.DYNAMIC_COURSE_MAINTENANCE_IDS == maintenance
    menu_text = button_texts(tb.get_course_menu_keyboard(2, 777))
    assert any(text == "🧬 Биохимия" for text in menu_text)
    assert any("Фармакология — техобслуживание" in text for text in menu_text)
    admin_id = next(iter(tb.ADMIN_IDS))
    admin_menu_text = button_texts(tb.get_course_menu_keyboard(2, admin_id))
    assert any("Фармакология — админ-предпросмотр" in text for text in admin_menu_text)

    biochemistry_index = next(i for i, course in enumerate(tb.DYNAMIC_COURSES) if course["id"] == "biochemistry")
    biochemistry = FakeCallback(f"dyn_c:{biochemistry_index}")
    await tb.cb_dynamic_course(biochemistry)
    assert biochemistry.answers[-1][1].get("show_alert") is not True
    assert "Полный практикум ВМедА" in biochemistry.message.edits[-1][0]

    for course_id in maintenance:
        index = next(i for i, course in enumerate(tb.DYNAMIC_COURSES) if course["id"] == course_id)
        callback = FakeCallback(f"dyn_c:{index}")
        await tb.cb_dynamic_course(callback)
        assert callback.answers[-1][1]["show_alert"] is True
        assert "полную переработку" in callback.message.edits[-1][0]

        callback = FakeCallback(f"dyn_s:{index}:0")
        await tb.cb_dynamic_section(callback)
        assert "техобслуживание" in callback.message.edits[-1][0]

        admin_callback = FakeCallback(f"dyn_c:{index}", admin_id)
        await tb.cb_dynamic_course(admin_callback)
        assert admin_callback.answers[-1][1].get("show_alert") is not True
        assert "Админ-предпросмотр" in admin_callback.message.edits[-1][0]
        assert "VMedA AI по предмету" not in button_texts(admin_callback.message.edits[-1][1]["reply_markup"])

        admin_section = FakeCallback(f"dyn_s:{index}:0", admin_id)
        await tb.cb_dynamic_section(admin_section)
        assert admin_section.answers[-1][1].get("show_alert") is not True
        assert "Выберите тему" in admin_section.message.edits[-1][0]

        admin_ai = FakeCallback(f"dyn_ai:{index}", admin_id)
        await tb.cb_dynamic_ai(admin_ai)
        assert admin_ai.answers[-1][1]["show_alert"] is True
        assert "техобслуживание" in admin_ai.message.edits[-1][0]

    print("dynamic course maintenance gate: OK")


if __name__ == "__main__":
    asyncio.run(main())
