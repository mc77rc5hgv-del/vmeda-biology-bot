import ast
import hashlib
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from vicegram_access import SingleOwnerAccess


class AccessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'vicegram.db'
        with sqlite3.connect(self.db) as conn:
            conn.executescript('''
                CREATE TABLE users(user_id INTEGER, username TEXT);
                INSERT INTO users VALUES(111, 'vmeda_helper'), (222, 'other');
                CREATE TABLE settings(chat_id INTEGER, owner_id INTEGER);
                INSERT INTO settings VALUES(-1, 111), (-2, 222);
                CREATE TABLE business_connections(business_connection_id TEXT, owner_id INTEGER, is_enabled INTEGER);
                INSERT INTO business_connections VALUES('own', 111, 1), ('other', 222, 1), ('disabled', 111, 0);
                CREATE TABLE reminders(id INTEGER, user_id INTEGER, remind_at INTEGER, sent INTEGER);
                INSERT INTO reminders VALUES(1, 222, 1, 0), (2, 111, 2, 0);
                CREATE TABLE messages(source TEXT, deleted INTEGER, expired INTEGER, next_check_at INTEGER, chat_id INTEGER);
                INSERT INTO messages VALUES('group_bot', 0, 0, 1, -2), ('group_bot', 0, 0, 2, -1);
            ''')
        self.policy = SingleOwnerAccess(self.db)
        self.owner = NS(id=111, username='VMEDA_HELPER', is_bot=False)
        self.other = NS(id=222, username='other', is_bot=False)
        self.handler = AsyncMock(return_value='handled')

    async def dispatch(self, kind, **kw):
        event = NS(answer=AsyncMock(), **kw)
        await self.policy(self.handler, NS(event_type=kind, event=event), {})
        return event

    def test_pin_survives_restart_and_username_reassignment(self):
        self.assertTrue(self.policy.authenticate(self.owner))
        policy = SingleOwnerAccess(self.db)
        self.assertTrue(policy.authenticate(NS(id=111, username='renamed')))
        self.assertFalse(policy.authenticate(NS(id=333, username='vmeda_helper')))

    def test_unresolved_fails_closed_and_never_writes_database(self):
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        self.assertFalse(self.policy.permits(None))
        self.assertFalse(self.policy.authenticate(self.other))
        self.assertTrue(self.policy.authenticate(self.owner))
        self.policy.group_owner(-1)
        self.assertEqual(before, hashlib.sha256(self.db.read_bytes()).hexdigest())

    async def test_stale_database_username_is_not_authorization(self):
        bot = NS(get_chat=AsyncMock(return_value=NS(id=111, username='changed')))
        await self.policy.resolve_existing(bot)
        self.assertIsNone(self.policy.owner_id)
        bot.get_chat.return_value = self.owner
        await self.policy.resolve_existing(bot)
        self.assertEqual(111, self.policy.owner_id)

    async def test_private_commands_callbacks_and_payments_block_others(self):
        self.policy.authenticate(self.owner)
        for kind in ['callback_query', 'pre_checkout_query', 'inline_query', 'message']:
            with self.subTest(kind=kind):
                await self.dispatch(kind, from_user=self.other, chat=NS(type='private'), text='/start')
                self.handler.assert_not_awaited()

    async def test_private_owner_can_use_bot(self):
        await self.dispatch('message', from_user=self.owner, chat=NS(type='private'), text='/start')
        self.handler.assert_awaited_once()

    async def test_business_events_authorize_owner_not_correspondent(self):
        self.policy.authenticate(self.owner)
        for kind in ['business_message', 'edited_business_message', 'deleted_business_messages']:
            for connection, expected in [('own', True), ('other', False), ('disabled', False)]:
                with self.subTest(kind=kind, connection=connection):
                    self.handler.reset_mock()
                    await self.dispatch(kind, business_connection_id=connection, from_user=self.other)
                    self.assertEqual(expected, self.handler.await_count == 1)

    async def test_connection_owner_and_unknown_connection(self):
        await self.dispatch('business_connection', user=self.other)
        self.handler.assert_not_awaited()
        connection = NS(user=self.owner, is_enabled=True)
        register = []
        bot = NS(get_business_connection=AsyncMock(return_value=connection))
        await self.policy(self.handler, NS(event_type='business_message', event=NS(business_connection_id='new')),
                          {'bot': bot, 'vicegram_register_connection': register.append})
        self.handler.assert_awaited_once()
        self.assertEqual(register, [connection])

    async def test_groups_only_monitor_allowed_owners_groups(self):
        self.policy.authenticate(self.owner)
        for chat, actor, text, expected in [(-1, self.other, 'hello', True),
                (-1, self.other, '/restore', False), (-2, self.other, 'hello', False),
                (-2, self.owner, '/settings', False), (-1, self.owner, '/settings', True)]:
            with self.subTest(chat=chat, text=text):
                self.handler.reset_mock()
                await self.dispatch('message', chat=NS(id=chat, type='supergroup'), from_user=actor, text=text)
                self.assertEqual(expected, self.handler.await_count == 1)

    def test_background_queries_filter_before_limit(self):
        self.policy.authenticate(self.owner)
        tree = ast.parse(Path(__file__).with_name('vicegram_bot.py').read_text())
        constants = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        reminder_sql = next(s for s in constants if 'SELECT * FROM reminders WHERE sent = 0' in s)
        group_sql = next(s for s in constants if 'SELECT * FROM messages' in s and 'next_check_at <= ?' in s)
        self.assertEqual([2], [r['id'] for r in self.policy.read(reminder_sql, (100, 111, 1))])
        self.assertEqual([-1], [r['chat_id'] for r in self.policy.read(group_sql, (100, 111))])
        self.assertEqual(2, len(self.policy.read('SELECT * FROM reminders')))
        self.assertEqual(2, len(self.policy.read('SELECT * FROM messages')))

    @unittest.skipUnless(importlib.util.find_spec('aiogram'), 'aiogram installed in CI')
    async def test_real_aiogram_outer_middleware(self):
        from aiogram import Bot, Dispatcher
        from aiogram.types import Update
        bot = Bot(token='123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi')
        bot.session.make_request = AsyncMock(return_value=True)
        dp = Dispatcher()
        dp.update.outer_middleware(self.policy)
        seen = []
        async def receive(message):
            seen.append(message.from_user.id)
        dp.message.register(receive)
        for uid, username in [(222, 'other'), (111, 'vmeda_helper'), (333, 'vmeda_helper')]:
            update = Update.model_validate({'update_id': uid, 'message': {
                'message_id': uid, 'date': 1700000000,
                'chat': {'id': uid, 'type': 'private'},
                'from': {'id': uid, 'is_bot': False, 'first_name': 'Test', 'username': username},
                'text': '/start'}})
            await dp.feed_update(bot, update)
        self.assertEqual([111], seen)
        await bot.session.close()


if __name__ == '__main__':
    unittest.main()
