from types import SimpleNamespace

import pytest

from services.payment_notifications import buyer_label
from web_api.tests.test_sbp_billing import paid

pytest_plugins = ['web_api.tests.test_sbp_billing']


def test_username_is_shown_with_id():
    tb = SimpleNamespace(stats={'user_username': {'42': 'medical_student'}})
    assert buyer_label(tb, 42) == '42 · @medical_student'


def test_profile_link_without_username_escapes_name_and_does_not_reuse_removed_username():
    tb = SimpleNamespace(stats={'user_username': {'42': None}, 'user_names': {'42': 'Анна <Петрова> & Иван'}})
    assert buyer_label(tb, 42, 'old_username') == '42 · <a href="tg://user?id=42">Анна &lt;Петрова&gt; &amp; Иван</a>'


def test_unknown_name_and_invalid_username_have_safe_profile_link():
    tb = SimpleNamespace(stats={'user_username': {'42': '<script>'}})
    assert buyer_label(tb, 42) == '42 · <a href="tg://user?id=42">Профиль пользователя</a>'


@pytest.mark.asyncio
async def test_actual_sbp_admin_notification_contains_username_and_html_mode(service):
    row = await service.checkout(777123, 21, None, 'notification-key', 'miniapp')
    await service.settle(row, paid(row))
    notifications = [call for call in service.tb.bot.send_message.await_args_list if call.args[0] in service.tb.ADMIN_IDS and call.args[0] != 777123]
    assert notifications
    assert all('Пользователь: 777123 · @preserve_username' in call.args[1] for call in notifications)
    assert all(call.kwargs['parse_mode'] == 'HTML' for call in notifications)
