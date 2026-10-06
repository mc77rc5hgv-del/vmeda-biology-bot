"""Admin username flows use isolated bootstrap storage and retain grant audit history."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

from _bootstrap import tb
from services.miniapp_testers import has_test_access
from handlers.admin import cb_admin_tester_prompt


class Message:
    def __init__(self, uid, text):
        self.from_user = SimpleNamespace(id=uid)
        self.text = text
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append(text)


async def main():
    admin = next(iter(tb.ADMIN_IDS))
    uid = 98765432
    tb.stats['total_users'].add(uid)
    tb.stats['usernames']['tester'] = uid
    tb.stats['user_username'][str(uid)] = 'Tester'
    menus = []
    original_menu = tb.bot.set_chat_menu_button
    async def set_menu(*, chat_id, menu_button):
        menus.append((chat_id, menu_button))
    tb.bot.set_chat_menu_button = set_menu
    original = deepcopy(tb.stats)
    tb.ADMIN_PENDING[admin] = {'action': 'grant_miniapp_tester'}
    message = Message(admin, '@TESTER')
    await tb.handle_admin_pending_action(message)
    assert has_test_access(tb, uid) and admin not in tb.ADMIN_PENDING
    assert not tb.is_admin(uid) and not tb.is_payment_admin(uid)
    assert menus[-1][0] == uid and menus[-1][1].type == 'web_app'
    assert any(button.web_app for row in tb.get_main_menu(uid).inline_keyboard for button in row)
    app_message = Message(uid, '/app')
    await tb.cmd_app(app_message)
    assert app_message.answers
    assert {k:v for k,v in tb.stats.items() if k!='miniapp_tester_access'} == {k:v for k,v in original.items() if k!='miniapp_tester_access'}
    loaded = tb.load_stats()
    assert loaded['miniapp_tester_access'][str(uid)]['active'] is True
    # A renamed user retains ID-based access; stale username cannot grant to the old owner.
    tb.stats['user_username'][str(uid)] = 'renamed'
    tb.ADMIN_PENDING[admin] = {'action': 'grant_miniapp_tester'}
    await tb.handle_admin_pending_action(Message(admin, '@tester'))
    assert admin in tb.ADMIN_PENDING
    assert len(tb.stats['miniapp_tester_access'][str(uid)]['history']) == 1
    tb.ADMIN_PENDING[admin] = {'action': 'revoke_miniapp_tester'}
    await tb.handle_admin_pending_action(Message(admin, str(uid)))
    assert not has_test_access(tb, uid)
    assert menus[-1][0] == uid and menus[-1][1].type == 'commands'
    assert all(button.web_app is None for row in tb.get_main_menu(uid).inline_keyboard for button in row)
    app_message = Message(uid, '/app')
    await tb.cmd_app(app_message)
    assert not app_message.answers
    assert len(tb.load_stats()['miniapp_tester_access'][str(uid)]['history']) == 2
    answers = []
    async def answer(*args, **kwargs):
        answers.append((args,kwargs))
    callback = SimpleNamespace(from_user=SimpleNamespace(id=uid), data='admin_tester_grant', answer=answer)
    await cb_admin_tester_prompt(callback)
    assert uid not in tb.ADMIN_PENDING and answers[0][1]['show_alert'] is True
    tb.bot.set_chat_menu_button = original_menu
    print('Tester admin grant/revoke, persistence, stale username and non-admin protection: OK')


asyncio.run(main())
