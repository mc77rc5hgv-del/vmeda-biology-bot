"""Public entry, admin promo persistence and restricted management; isolated storage."""
import asyncio
import os
from copy import deepcopy
from types import SimpleNamespace

from _bootstrap import tb
from handlers.admin import cb_admin_miniapp_promo_set, cb_admin_miniapp_promo, get_admin_menu


async def main():
    os.environ['MINIAPP_ACCESS_MODE'] = 'public'
    user = 98765001
    admin = next(iter(tb.ADMIN_IDS))
    tb.stats['total_users'].add(user)
    tb.stats['user_username'][str(user)] = 'synthetic_public'
    assert tb.miniapp_launch_allowed(user)
    for uid in (user, None):
        assert any(b.web_app for row in tb.get_main_menu(uid).inline_keyboard for b in row)
    menus, messages, answers = [], [], []
    async def set_menu(**kwargs):
        menus.append(kwargs)
    async def edit(_message, text, **kwargs):
        messages.append(text)
    async def answer(*args, **kwargs):
        answers.append(kwargs)
    async def message_answer(text, **kwargs):
        messages.append(text)
    tb.bot.set_chat_menu_button = set_menu
    tb.safe_edit_text = edit
    await tb.sync_miniapp_menu_button(user)
    assert menus[-1]['menu_button'].type == 'web_app'
    before = deepcopy(tb.stats)
    callback = SimpleNamespace(from_user=SimpleNamespace(id=admin), data='admin_miniapp_promo_enable',
        message=SimpleNamespace(answer=message_answer), answer=answer)
    await cb_admin_miniapp_promo_set(callback)
    assert tb.load_stats()['miniapp_public_promo']['active']
    assert any(b.callback_data == 'admin_miniapp_promo' for row in get_admin_menu().inline_keyboard for b in row)
    await cb_admin_miniapp_promo(callback)
    callback.data = 'admin_miniapp_promo_disable'
    await cb_admin_miniapp_promo_set(callback)
    saved = tb.load_stats()['miniapp_public_promo']
    assert saved['active'] is False and len(saved['history']) == 2
    assert {k:v for k,v in tb.stats.items() if k != 'miniapp_public_promo'} == before
    assert tb.miniapp_launch_allowed(user)
    callback.from_user.id = user
    callback.data = 'admin_miniapp_promo_enable'
    await cb_admin_miniapp_promo_set(callback)
    assert answers[-1]['show_alert'] and not tb.stats['miniapp_public_promo']['active']
    # Saving failed: don't claim confirmed activation to the administrator.
    callback.from_user.id = admin
    from concurrent.futures import Future
    def failed_save():
        future = Future()
        future.set_exception(OSError('synthetic disk error'))
        return future
    tb.save_stats = failed_save
    await cb_admin_miniapp_promo_set(callback)
    assert 'Не удалось подтвердить' in messages[-1]
    print('Public launcher, durable admin toggles, preservation, non-admin rejection and save failure: OK')


asyncio.run(main())
