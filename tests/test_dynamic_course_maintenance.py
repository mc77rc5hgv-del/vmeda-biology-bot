# -*- coding: utf-8 -*-
import asyncio

from _bootstrap import tb


class FakeUser:
    id = 777


class FakeMessage:
    def __init__(self):
        self.edits = []

    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs))


class FakeCallback:
    def __init__(self, data):
        self.data = data
        self.from_user = FakeUser()
        self.message = FakeMessage()
        self.answers = []

    async def answer(self, text=None, **kwargs):
        self.answers.append((text, kwargs))


def button_texts(markup):
    return [button.text for row in markup.inline_keyboard for button in row]


async def main():
    maintenance = {"biochemistry", "pharmacology"}
    assert tb.DYNAMIC_COURSE_MAINTENANCE_IDS == maintenance
    menu_text = button_texts(tb.get_course_menu_keyboard(2, 777))
    assert any("Биохимия — техобслуживание" in text for text in menu_text)
    assert any("Фармакология — техобслуживание" in text for text in menu_text)

    for course_id in maintenance:
        index = next(i for i, course in enumerate(tb.DYNAMIC_COURSES) if course["id"] == course_id)
        callback = FakeCallback(f"dyn_c:{index}")
        await tb.cb_dynamic_course(callback)
        assert callback.answers[-1][1]["show_alert"] is True
        assert "полную переработку" in callback.message.edits[-1][0]

        callback = FakeCallback(f"dyn_s:{index}:0")
        await tb.cb_dynamic_section(callback)
        assert "техобслуживание" in callback.message.edits[-1][0]

    print("dynamic course maintenance gate: OK")


if __name__ == "__main__":
    asyncio.run(main())
