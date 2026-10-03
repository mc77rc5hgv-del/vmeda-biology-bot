"""Verified, additive backups. Never restore over, truncate or remove live data."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time


def backup_stats(path: str):
    source = Path(path).resolve()
    raw = source.read_bytes()
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get('total_users'), list):
        raise RuntimeError('stats.json does not contain the existing user list')
    folder = source.parent / 'sync_backups'
    folder.mkdir(mode=0o700, exist_ok=True)
    target = folder / f'stats-{time.time_ns()}-{hashlib.sha256(raw).hexdigest()[:12]}.json'
    with target.open('xb') as stream:
        os.chmod(target, 0o600)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if target.read_bytes() != raw:
        raise RuntimeError('Stats backup verification failed')
    return str(target)


def backup_sqlite(path: str):
    source = Path(path).resolve()
    if not source.is_file():
        raise RuntimeError('Existing learning database missing')
    folder = source.parent / 'sync_backups'
    folder.mkdir(mode=0o700, exist_ok=True)
    target = folder / f'learning-{time.time_ns()}.sqlite3'
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=10) as old:
        if old.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise RuntimeError('Existing learning database failed integrity check')
        with sqlite3.connect(target) as new:
            old.backup(new)
            if new.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise RuntimeError('Learning backup verification failed')
    os.chmod(target, 0o600)
    return str(target)
