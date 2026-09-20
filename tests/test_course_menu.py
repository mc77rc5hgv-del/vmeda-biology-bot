# -*- coding: utf-8 -*-
"""Главный экран группирует предметы по курсу обучения («1️⃣ Первый курс» / «2️⃣ Второй курс»,
см. CLAUDE.md / cb_course_menu в telegram_bot.py) вместо плоского списка кнопок-предметов.
Анатомия и Гистология входят в оба курса с той же динамической (админ/подписка/техобслуживание/
промо/рефералы) подписью, что была на старом плоском главном меню — эти тесты проверяют состав
и порядок предметов в каждом курсе, что динамические подписи не потерялись при переезде, что
callback_data кнопок не изменились (гейтинг/навигация продолжают работать как раньше), и что
главное меню больше не содержит предметы напрямую, только точки входа в курсы."""
import asyncio
from _bootstrap import tb

ADMIN_ID = next(iter(tb.ADMIN_IDS))


class FakeUser:
    def __init__(self, uid):
        self.id = uid


class FakeMsg:
    def __init__(self):
        self.edits = []
    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))
        return self
    async def answer(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))
        return self


class FakeCommandMsg:
    def __init__(self, uid):
        self.from_user = FakeUser(uid)
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))
        return self


class FakeCB:
    def __init__(self, data, uid=ADMIN_ID):
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeMsg()
        self._answers = []
    async def answer(self, text=None, show_alert=False):
        self._answers.append((text, show_alert))


def kb_data(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def kb_texts(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


def kb_buttons(markup):
    return [button for row in markup.inline_keyboard for button in row]


async def main():
    non_admin = 88_112_233

    # ---- 1. main menu no longer lists individual subjects, only the two course entry points ----
    main_menu = tb.get_main_menu(user_id=non_admin)
    main_data = kb_data(main_menu)
    for gone in ("menu_biology", "menu_physics", "menu_chemistry", "anatomy_root", "histology_menu", "oh:menu", "phys:menu"):
        assert gone not in main_data, gone
    assert "course_menu:1" in main_data and "course_menu:2" in main_data
    assert any("Первый курс" in t for t in kb_texts(main_menu))
    assert any("Второй курс" in t for t in kb_texts(main_menu))
    assert all(button.web_app is None for button in kb_buttons(main_menu))
    print("1. main menu exposes only the two course entry points, no direct subject buttons: OK")

    # ---- 1b. production Mini App entry is visible only to a full admin while API is admin_only ----
    admin_app_buttons = [button for button in kb_buttons(tb.get_main_menu(user_id=ADMIN_ID)) if button.web_app]
    assert len(admin_app_buttons) == 1
    assert admin_app_buttons[0].text == "🎓 Открыть VMEDA App"
    assert admin_app_buttons[0].web_app.url == tb.MINIAPP_URL
    assert tb.MINIAPP_URL.startswith("https://")
    print("1b. admin gets one signed Telegram Mini App launch button; ordinary users get none: OK")

    # ---- 1c. /app is a second admin-only entry point for stale /start messages ----
    admin_app_message = FakeCommandMsg(ADMIN_ID)
    await tb.cmd_app(admin_app_message)
    assert len(admin_app_message.answers) == 1
    app_markup = admin_app_message.answers[0][1]["reply_markup"]
    app_buttons = [button for button in kb_buttons(app_markup) if button.web_app]
    assert len(app_buttons) == 1 and app_buttons[0].web_app.url == tb.MINIAPP_URL

    ordinary_app_message = FakeCommandMsg(non_admin)
    await tb.cmd_app(ordinary_app_message)
    assert ordinary_app_message.answers == []
    print("1c. /app gives admins a fresh launch button and stays hidden from ordinary users: OK")

    # ---- 1d. startup configures Telegram's persistent chat-menu button per full admin ----
    class FakeBot:
        def __init__(self):
            self.command_calls = []
            self.menu_calls = []

        async def set_my_commands(self, commands, scope):
            self.command_calls.append((commands, scope))

        async def set_chat_menu_button(self, *, chat_id, menu_button):
            self.menu_calls.append((chat_id, menu_button))

    fake_bot = FakeBot()
    real_bot = tb.setup_bot_commands.__globals__["bot"]
    tb.setup_bot_commands.__globals__["bot"] = fake_bot
    try:
        await tb.setup_bot_commands()
    finally:
        tb.setup_bot_commands.__globals__["bot"] = real_bot

    assert {chat_id for chat_id, _ in fake_bot.menu_calls} == tb.ADMIN_IDS
    assert all(menu_button.web_app.url == tb.MINIAPP_URL for _, menu_button in fake_bot.menu_calls)
    admin_command_names = {
        command.command
        for commands, scope in fake_bot.command_calls
        if getattr(scope, "chat_id", None) in tb.ADMIN_IDS
        for command in commands
    }
    assert "app" in admin_command_names
    print("1d. startup pins VMEDA App beside the Telegram input for every full admin: OK")

    # ---- 2. 1st course: Физика, Химия, Биология, Анатомия, Гистология, in that order ----
    course1 = tb.get_course_menu_keyboard(1, user_id=non_admin)
    c1_data = [d for d in kb_data(course1) if d != "back_to_main"]
    assert c1_data[:5] == ["menu_physics", "menu_chemistry", "menu_biology", "anatomy_root", "histology_menu"]
    assert all(value.startswith("dyn_c:") for value in c1_data[5:])
    print("2. 1st course keeps core subjects in order and appends generated subjects: OK")

    # ---- 3. 2nd course: Анатомия, Гистология, Нормальная физиология, Оперативная хирургия ----
    course2 = tb.get_course_menu_keyboard(2, user_id=non_admin)
    c2_data = [d for d in kb_data(course2) if d != "back_to_main"]
    assert c2_data[:4] == ["anatomy_root", "histology_menu", "phys:menu", "oh:menu"]
    assert all(value.startswith("dyn_c:") for value in c2_data[4:])
    print("3. 2nd course keeps core subjects in order and appends generated subjects: OK")

    # ---- 4. Anatomy/Histology carry their dynamic label in BOTH courses, not just one ----
    course1_admin = tb.get_course_menu_keyboard(1, user_id=ADMIN_ID)
    course2_admin = tb.get_course_menu_keyboard(2, user_id=ADMIN_ID)
    assert "🔥🦴 Анатомия (админ)" in kb_texts(course1_admin)
    assert "🔥🦴 Анатомия (админ)" in kb_texts(course2_admin)
    assert "🔬 Гистология (админ)" in kb_texts(course1_admin)
    assert "🔬 Гистология (админ)" in kb_texts(course2_admin)
    print("4. Anatomy/Histology dynamic labels are consistent across both course screens: OK")

    # ---- 5. course screens are ungated navigation, correct back button, both callbacks routed ----
    assert not tb.is_gated_callback("course_menu:1")
    assert not tb.is_gated_callback("course_menu:2")
    assert "back_to_main" in kb_data(course1)

    cb1 = FakeCB("course_menu:1", uid=non_admin)
    await tb.cb_course_menu(cb1)
    text1, kb1 = cb1.message.edits[-1]
    assert "ПЕРВЫЙ КУРС" in text1
    assert kb_data(kb1) == kb_data(tb.get_course_menu_keyboard(1, non_admin))

    cb2 = FakeCB("course_menu:2", uid=non_admin)
    await tb.cb_course_menu(cb2)
    text2, kb2 = cb2.message.edits[-1]
    assert "ВТОРОЙ КУРС" in text2
    assert kb_data(kb2) == kb_data(tb.get_course_menu_keyboard(2, non_admin))
    print("5. course screens ungated, correctly routed, real back button: OK")

    print("\nALL COURSE MENU TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
