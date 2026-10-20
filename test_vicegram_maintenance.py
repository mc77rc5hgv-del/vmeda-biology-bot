import gzip
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vicegram_maintenance import OWNER, VERSION, inventory, cleanup


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / 'vicegram.db'
        self.media = self.root / 'media'
        self.media.mkdir()
        self.keep = self.media / f'{OWNER}_222_1'
        self.remove = self.media / '222_333_2'
        self.shared = self.media / '222_333_3'
        self.unknown = self.media / 'unknown-file'
        for file in [self.keep, self.remove, self.shared, self.unknown]:
            file.write_bytes(file.name.encode())
        self.pin = self.root / 'vicegram-owner-access.json'
        self.pin.write_text(json.dumps({'username': 'vmeda_helper', 'user_id': OWNER}))
        with sqlite3.connect(self.db) as c:
            c.executescript('''
                CREATE TABLE users(user_id INTEGER PRIMARY KEY, username TEXT);
                CREATE TABLE settings(chat_id INTEGER PRIMARY KEY, owner_id INTEGER);
                CREATE TABLE messages(source TEXT, owner_id INTEGER, chat_id INTEGER, user_id INTEGER, media_path TEXT);
                CREATE TABLE custom_commands(chat_id INTEGER, trigger TEXT);
                CREATE TABLE streaks(chat_id INTEGER, user_id INTEGER);
                CREATE TABLE business_connections(owner_id INTEGER, connection TEXT);
                CREATE TABLE active_notes(owner_id INTEGER, text TEXT);
                CREATE TABLE reminders(user_id INTEGER, text TEXT);
                CREATE TABLE payments(user_id INTEGER, amount INTEGER);
                CREATE TABLE referrals(referrer_id INTEGER, referred_id INTEGER);
            ''')
            c.executemany('INSERT INTO users VALUES (?,?)', [(OWNER, 'vmeda_helper'), (222, 'other')])
            c.executemany('INSERT INTO settings VALUES (?,?)', [(-1, OWNER), (-2, 222), (-3, None)])
            c.executemany('INSERT INTO messages VALUES (?,?,?,?,?)', [
                ('business', OWNER, 222, 222, str(self.keep)),
                ('business', OWNER, 222, 222, str(self.shared)),
                ('business', 222, 333, OWNER, str(self.remove)),
                ('business', 222, 333, OWNER, str(self.shared)),
                ('group_bot', 0, -1, 222, None),
                ('group_bot', 0, -2, OWNER, None),
                ('group_bot', 0, -3, OWNER, None)])
            for table in ['custom_commands', 'streaks']:
                c.executemany(f'INSERT INTO {table} VALUES (?,?)', [(-1, 222), (-2, OWNER), (-3, OWNER)])
            for table in ['business_connections', 'active_notes', 'reminders', 'payments']:
                c.executemany(f'INSERT INTO {table} VALUES (?,?)', [(OWNER, 123), (222, 456)])
            c.executemany('INSERT INTO referrals VALUES (?,?)', [(OWNER, 222), (222, OWNER), (333, 222)])

    def test_audit_is_read_only_and_understands_correspondence_ownership(self):
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        report, files = inventory(self.db, self.media)
        self.assertEqual(before, hashlib.sha256(self.db.read_bytes()).hexdigest())
        self.assertEqual(3, report['tables']['messages']['keep'])
        self.assertEqual(4, report['tables']['messages']['remove'])
        self.assertIn(str(self.shared), files['keep'])
        self.assertNotIn(str(self.shared), files['remove'])
        self.assertEqual([str(self.remove)], files['remove'])
        self.assertEqual([str(self.unknown)], files['unknown'])

    def test_cleanup_preserves_owner_content_and_verifies_recoverable_database_backup(self):
        report = cleanup(self.db, self.media)
        self.assertTrue(report['owner_rows_verified'])
        self.assertTrue(report['owner_media_verified'])
        self.assertTrue(self.keep.exists())
        self.assertTrue(self.shared.exists())
        self.assertTrue(self.unknown.exists())
        self.assertFalse(self.remove.exists())
        self.assertFalse(any(t['remove'] for t in report['after']['tables'].values()))
        with sqlite3.connect(self.db) as c:
            self.assertEqual([(OWNER, 'vmeda_helper')], c.execute('SELECT * FROM users').fetchall())
            self.assertEqual(3, c.execute('SELECT count(*) FROM messages').fetchone()[0])
            self.assertEqual(2, c.execute('SELECT count(*) FROM referrals').fetchone()[0])
        restored = self.root / 'restored.sqlite3'
        with gzip.open(self.root / report['backup'], 'rb') as s:
            restored.write_bytes(s.read())
        with sqlite3.connect(restored) as c:
            self.assertEqual('ok', c.execute('PRAGMA integrity_check').fetchone()[0])
            self.assertEqual(2, c.execute('SELECT count(*) FROM users').fetchone()[0])
            self.assertEqual(7, c.execute('SELECT count(*) FROM messages').fetchone()[0])
        self.assertEqual(report, cleanup(self.db, self.media))

    def test_wrong_identity_and_unknown_schema_abort_without_deletion(self):
        self.pin.write_text(json.dumps({'username': 'vmeda_helper', 'user_id': 222}))
        with self.assertRaises(RuntimeError):
            cleanup(self.db, self.media)
        self.assertTrue(self.remove.exists())
        self.pin.write_text(json.dumps({'username': 'vmeda_helper', 'user_id': OWNER}))
        with sqlite3.connect(self.db) as c:
            c.execute('CREATE TABLE unexpected_secret_data(value TEXT)')
        with self.assertRaises(RuntimeError):
            cleanup(self.db, self.media)
        self.assertTrue(self.remove.exists())

    def test_insufficient_backup_space_never_deletes(self):
        with patch('vicegram_maintenance.shutil.disk_usage') as usage:
            usage.return_value.free = 0
            with self.assertRaises(RuntimeError):
                cleanup(self.db, self.media)
        self.assertTrue(self.remove.exists())
        with sqlite3.connect(self.db) as c:
            self.assertEqual(2, c.execute('SELECT count(*) FROM users').fetchone()[0])

    def test_owner_media_link_and_path_outside_cache_are_never_removed(self):
        outside = self.root / 'outside'
        outside.write_bytes(b'outside')
        (self.media / '222_1_55').symlink_to(outside)
        with sqlite3.connect(self.db) as c:
            c.execute('INSERT INTO messages VALUES (?,?,?,?,?)', ('business', 222, 0, 0, str(outside)))
        cleanup(self.db, self.media)
        self.assertTrue(outside.exists())


if __name__ == '__main__':
    unittest.main()
