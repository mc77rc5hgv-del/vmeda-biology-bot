# -*- coding: utf-8 -*-
"""Anatomy section temporary technical closure (ANATOMY_MAINTENANCE_MODE): anatomy_root is
the sole entry point into the whole section (course + exam), so gating it there closes
everything reachable from the UI for non-admins while leaving admins able to keep working
in it. The flag is meant to be flipped back to False once the issue is resolved — this test
also covers that the section behaves exactly as before once it's off."""
import asyncio
from _bootstrap import tb

ADMIN_ID = next(iter(tb.ADMIN_IDS))
NON_ADMIN = 447788990

class FakeUser:
    def __init__(self, uid):
        self.id = uid

class FakeMsg:
    def __init__(self):
        self.edits = []
    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))
        return self
    async def delete(self):
        pass
    async def answer(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))
        return self

class FakeCB:
    def __init__(self, data, uid=NON_ADMIN):
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeMsg()
        self._answers = []
    async def answer(self, text=None, show_alert=False):
        self._answers.append((text, show_alert))

def kb_texts(markup):
    return [b.text for row in markup.inline_keyboard for b in row]

def kb_data(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]

async def main():
    orig_mode = tb.ANATOMY_MAINTENANCE_MODE

    # ---- 1. maintenance ON: non-admin gets the closed screen, no course/exam entry points ----
    tb.ANATOMY_MAINTENANCE_MODE = True
    cb = FakeCB("anatomy_root", uid=NON_ADMIN)
    await tb.cb_anatomy_root(cb)
    text, kb = cb.message.edits[-1]
    assert "недоступен" in text.lower() or "техническ" in text.lower()
    data = kb_data(kb)
    assert "anatomy_menu" not in data and "anatomy_exam_menu" not in data
    assert "back_to_main" in data
    print("1. maintenance ON blocks non-admin at anatomy_root: OK")

    # ---- 2. maintenance ON: admin still gets the normal course/exam split ----
    cb_admin = FakeCB("anatomy_root", uid=ADMIN_ID)
    await tb.cb_anatomy_root(cb_admin)
    text_a, kb_a = cb_admin.message.edits[-1]
    data_a = kb_data(kb_a)
    assert "anatomy_menu" in data_a and "anatomy_exam_menu" in data_a
    print("2. maintenance ON still lets admin in: OK")

    # ---- 3. main menu label reflects maintenance for non-admin, not for admin ----
    menu_non_admin = tb.get_main_menu(user_id=NON_ADMIN)
    assert any("техобслуживание" in t for t in kb_texts(menu_non_admin))
    menu_admin = tb.get_main_menu(user_id=ADMIN_ID)
    assert any("(админ)" in t for t in kb_texts(menu_admin))
    assert not any("техобслуживание" in t for t in kb_texts(menu_admin))
    print("3. main menu label: non-admin sees maintenance, admin sees normal (админ) label: OK")

    # ---- 4. maintenance OFF: behaves exactly as before for non-admin too ----
    tb.ANATOMY_MAINTENANCE_MODE = False
    cb2 = FakeCB("anatomy_root", uid=NON_ADMIN)
    await tb.cb_anatomy_root(cb2)
    text2, kb2 = cb2.message.edits[-1]
    data2 = kb_data(kb2)
    assert "anatomy_menu" in data2 and "anatomy_exam_menu" in data2
    menu_non_admin_off = tb.get_main_menu(user_id=NON_ADMIN)
    assert not any("техобслуживание" in t for t in kb_texts(menu_non_admin_off))
    print("4. maintenance OFF restores normal behavior: OK")

    tb.ANATOMY_MAINTENANCE_MODE = orig_mode
    print("\nAll anatomy maintenance-mode tests passed!")

if __name__ == "__main__":
    asyncio.run(main())
