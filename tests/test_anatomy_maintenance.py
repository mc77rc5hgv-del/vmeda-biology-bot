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
    orig_mode = tb.anatomy_handlers.ANATOMY_MAINTENANCE_MODE

    # ---- 1. maintenance ON: non-admin gets the closed screen, no course/exam entry points ----
    tb.anatomy_handlers.ANATOMY_MAINTENANCE_MODE = True
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

    # ---- 3. course-menu (1st and 2nd course both carry Anatomy) reflects maintenance for
    # non-admin, not for admin ----
    assert "техобслуживание" in tb._anatomy_menu_label(NON_ADMIN)
    assert "(админ)" in tb._anatomy_menu_label(ADMIN_ID)
    assert "техобслуживание" not in tb._anatomy_menu_label(ADMIN_ID)
    course1_non_admin = tb.get_course_menu_keyboard(1, user_id=NON_ADMIN)
    assert any("техобслуживание" in t for t in kb_texts(course1_non_admin))
    course2_admin = tb.get_course_menu_keyboard(2, user_id=ADMIN_ID)
    assert any("(админ)" in t for t in kb_texts(course2_admin))
    print("3. course menu label: non-admin sees maintenance, admin sees normal (админ) label: OK")

    # ---- 4. maintenance OFF: behaves exactly as before for non-admin too ----
    tb.anatomy_handlers.ANATOMY_MAINTENANCE_MODE = False
    cb2 = FakeCB("anatomy_root", uid=NON_ADMIN)
    await tb.cb_anatomy_root(cb2)
    text2, kb2 = cb2.message.edits[-1]
    data2 = kb_data(kb2)
    assert "anatomy_menu" in data2 and "anatomy_exam_menu" in data2
    assert "техобслуживание" not in tb._anatomy_menu_label(NON_ADMIN)
    print("4. maintenance OFF restores normal behavior: OK")

    tb.anatomy_handlers.ANATOMY_MAINTENANCE_MODE = orig_mode

    # ---- 5. stats override takes precedence over the hardcoded constant ----
    orig_override = tb.stats.get("anatomy_maintenance_override")
    tb.anatomy_handlers.ANATOMY_MAINTENANCE_MODE = False
    tb.stats["anatomy_maintenance_override"] = True
    assert tb.anatomy_maintenance_mode_enabled() is True
    cb5 = FakeCB("anatomy_root", uid=NON_ADMIN)
    await tb.cb_anatomy_root(cb5)
    text5, _ = cb5.message.edits[-1]
    assert "техническ" in text5.lower(), "stats override must close the section even though the hardcoded flag is off"

    tb.stats["anatomy_maintenance_override"] = False
    assert tb.anatomy_maintenance_mode_enabled() is False
    tb.anatomy_handlers.ANATOMY_MAINTENANCE_MODE = True
    cb6 = FakeCB("anatomy_root", uid=NON_ADMIN)
    await tb.cb_anatomy_root(cb6)
    data6 = kb_data(cb6.message.edits[-1][1])
    assert "anatomy_menu" in data6, "stats override=False must open the section even though the hardcoded flag is on"

    tb.anatomy_handlers.ANATOMY_MAINTENANCE_MODE = orig_mode
    tb.stats["anatomy_maintenance_override"] = None
    print("5. stats override wins over the hardcoded ANATOMY_MAINTENANCE_MODE constant: OK")

    # ---- 6. admin panel one-tap toggle ----
    assert tb.anatomy_maintenance_mode_enabled() == orig_mode  # override cleared -> back to hardcoded default

    cb_toggle1 = FakeCB("admin_anatomy_maintenance_toggle", uid=ADMIN_ID)
    await tb.cb_admin_anatomy_maintenance_toggle(cb_toggle1)
    assert tb.anatomy_maintenance_mode_enabled() == (not orig_mode)
    assert cb_toggle1._answers and cb_toggle1._answers[-1][1] is True  # show_alert
    menu_text1, menu_kb1 = cb_toggle1.message.edits[-1]
    label1 = next(t for t in kb_texts(menu_kb1) if "Техрежим Анатомии" in t)
    assert ("ВКЛ" in label1) == (not orig_mode)

    cb_toggle2 = FakeCB("admin_anatomy_maintenance_toggle", uid=ADMIN_ID)
    await tb.cb_admin_anatomy_maintenance_toggle(cb_toggle2)
    assert tb.anatomy_maintenance_mode_enabled() == orig_mode  # flipped back
    _, menu_kb2 = cb_toggle2.message.edits[-1]
    label2 = next(t for t in kb_texts(menu_kb2) if "Техрежим Анатомии" in t)
    assert ("ВКЛ" in label2) == orig_mode

    cb_toggle_denied = FakeCB("admin_anatomy_maintenance_toggle", uid=NON_ADMIN)
    await tb.cb_admin_anatomy_maintenance_toggle(cb_toggle_denied)
    assert tb.anatomy_maintenance_mode_enabled() == orig_mode, "non-admin must not be able to toggle maintenance mode"
    assert not cb_toggle_denied.message.edits

    tb.stats["anatomy_maintenance_override"] = orig_override
    print("6. admin_anatomy_maintenance_toggle flips state one-tap, relabels the button, denies non-admin: OK")

    print("\nAll anatomy maintenance-mode tests passed!")

if __name__ == "__main__":
    asyncio.run(main())
