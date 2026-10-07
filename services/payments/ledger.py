"""Separate owner-volume billing journal. Never opens stats.json or the learning DB."""
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


class BillingLedger:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.backup_info = self.backup() if Path(path).is_file() else None
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
            CREATE TABLE IF NOT EXISTS orders (
              id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, request_key TEXT NOT NULL,
              tier_id INTEGER NOT NULL, subject TEXT, amount_minor INTEGER NOT NULL,
              proof TEXT NOT NULL, source TEXT NOT NULL, username TEXT,
              created REAL NOT NULL, updated REAL NOT NULL, state TEXT NOT NULL,
              provider_id TEXT UNIQUE, url TEXT, reason TEXT,
              net_minor INTEGER, fee_minor INTEGER, charge_id TEXT, checked REAL DEFAULT 0,
              UNIQUE(user_id, request_key));
            CREATE INDEX IF NOT EXISTS billing_pending ON orders(state, checked);
            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY, order_id TEXT NOT NULL, at REAL NOT NULL,
              state TEXT NOT NULL, details TEXT NOT NULL);
            ''')

        os.chmod(self.path, 0o600)

    def backup(self):
        source = Path(self.path).resolve()
        folder = source.parent / 'billing_backups'
        folder.mkdir(mode=0o700, exist_ok=True)
        target = folder / f'billing-{time.time_ns()}.sqlite3'
        with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=10) as old:
            if old.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise RuntimeError('Billing integrity check failed')
            with sqlite3.connect(target) as new:
                old.backup(new)
                if new.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Billing backup integrity check failed')
                for table in ('orders', 'events'):
                    query = 'SELECT * FROM orders ORDER BY id' if table == 'orders' else 'SELECT * FROM events ORDER BY id'
                    if old.execute(query).fetchall() != new.execute(query).fetchall():
                        raise RuntimeError('Billing backup data verification failed')
                count = new.execute('SELECT count(*) FROM orders').fetchone()[0]
        os.chmod(target, 0o600)
        return {'verified': True, 'orders': count, 'path': str(target)}

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, order_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
            return dict(row) if row else None

    def by_provider(self, provider_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM orders WHERE provider_id=?', (provider_id,)).fetchone()
            return dict(row) if row else None

    def existing(self, user_id, request_key):
        with self.connect() as db:
            row = db.execute('SELECT * FROM orders WHERE user_id=? AND request_key=?', (user_id, request_key)).fetchone()
            return dict(row) if row else None

    def create(self, row):
        now = time.time()
        with self.connect() as db:
            db.execute('INSERT INTO orders(id,user_id,request_key,tier_id,subject,amount_minor,proof,source,username,created,updated,state) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       tuple(row[k] for k in ('id', 'user_id', 'request_key', 'tier_id', 'subject', 'amount_minor', 'proof', 'source', 'username')) + (now, now, 'creating'))
            db.execute('INSERT INTO events(order_id,at,state,details) VALUES(?,?,?,?)', (row['id'], now, 'creating', '{}'))
        return self.get(row['id'])

    def update(self, order_id, state, *, resolve_review=False, **values):
        if not set(values) <= {'provider_id', 'url', 'reason', 'net_minor', 'fee_minor', 'charge_id', 'checked'}:
            raise ValueError('Immutable quote cannot change')
        with self.connect() as db:
            now = time.time()
            old = db.execute('SELECT state FROM orders WHERE id=?', (order_id,)).fetchone()
            if not old:
                raise ValueError('Unknown order')
            # A callback / poll can never downgrade a durable settled receipt.
            if old['state'] in ('applied', 'resolved_keep') and state != old['state']:
                return
            if old['state'] == 'review' and state != 'review' and not (resolve_review and state in ('applied', 'resolved_keep')):
                return
            sets = ','.join(f'{key}=?' for key in values)
            db.execute('UPDATE orders SET state=?,updated=?' + (',' + sets if sets else '') + ' WHERE id=?',  # noqa: S608 - column names strictly allowlisted above
                       (state, now, *values.values(), order_id))
            if old['state'] != state:
                db.execute('INSERT INTO events(order_id,at,state,details) VALUES(?,?,?,?)',
                           (order_id, now, state, json.dumps(values, ensure_ascii=False)))

    def pending(self, limit=50):
        with self.connect() as db:
            # Keep failed/cancelled orders recoverable: delayed bank settlements are possible.
            return [dict(row) for row in db.execute('SELECT * FROM orders WHERE provider_id IS NOT NULL AND state NOT IN ("applied","review","resolved_keep") AND checked < ? - CASE WHEN created > ? - 3600 THEN 15 WHEN created > ? - 86400 THEN 300 ELSE 3600 END ORDER BY checked LIMIT ?',
                                                    (time.time(), time.time(), time.time(), limit))]

    def uncertain_creation(self, user_id):
        with self.connect() as db:
            return db.execute('SELECT 1 FROM orders WHERE user_id=? AND state IN ("creating","creation_unknown") LIMIT 1', (user_id,)).fetchone() is not None

    def record_event(self, order_id, state, details):
        with self.connect() as db:
            db.execute('INSERT INTO events(order_id,at,state,details) VALUES(?,?,?,?)',
                       (order_id, time.time(), state, json.dumps(details, ensure_ascii=False)))

    def events(self, order_id):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM events WHERE order_id=? ORDER BY id', (order_id,))]

    def recover_interrupted_creation(self):
        with self.connect() as db:
            ids = [row[0] for row in db.execute('SELECT id FROM orders WHERE state="creating"')]
        for order_id in ids:
            self.update(order_id, 'creation_unknown', reason='Создание было прервано. Требуется сверка с codeePay.')

    def history(self, user_id=None, limit=50, offset=0):
        with self.connect() as db:
            where = ' WHERE user_id=?' if user_id is not None else ''
            params = (user_id,) if user_id is not None else ()
            query = 'SELECT * FROM orders WHERE user_id=? ORDER BY created DESC LIMIT ? OFFSET ?' if where else 'SELECT * FROM orders ORDER BY created DESC LIMIT ? OFFSET ?'
            return [dict(row) for row in db.execute(query, (*params, limit, offset))]

    def summary(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute('''SELECT strftime('%Y-%m', created+10800, 'unixepoch') AS month,
                      state, count(*) AS count, sum(amount_minor) AS amount_minor,
                      sum(net_minor) AS net_minor, sum(fee_minor) AS fee_minor
                      FROM orders GROUP BY month,state ORDER BY month DESC,state''')]

    @staticmethod
    def public(row):
        return {key: row[key] for key in ('id', 'tier_id', 'subject', 'amount_minor', 'source', 'created', 'state', 'reason', 'net_minor', 'fee_minor', 'url')}
