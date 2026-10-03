"""Verified, additive backups. Never restore over, truncate or remove live data."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import logging

logger = logging.getLogger(__name__)
backup_status: dict = {}


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
    backup_status['stats'] = {'verified': True, 'users': len(data['total_users']), 'sha256': hashlib.sha256(raw).hexdigest()}
    logger.warning('SYNC_STATS_BACKUP_VERIFIED users=%d', len(data['total_users']))
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
    backup_status['learning'] = {'verified': True, 'integrity': 'ok', 'bytes': target.stat().st_size}
    logger.warning('SYNC_LEARNING_BACKUP_VERIFIED integrity=ok bytes=%d', target.stat().st_size)
    return str(target)


def verify_loaded_stats(snapshot: str, current: dict):
    original = json.loads(Path(snapshot).read_text())
    if set(original['total_users']) != set(current.get('total_users', [])):
        raise RuntimeError('Loaded user list differs from the verified snapshot')
    for key, value in original.items():
        if key != 'total_users' and current.get(key) != value:
            raise RuntimeError('Loaded statistics differ from the verified snapshot')
    backup_status['stats']['loaded_data_preserved'] = True
    logger.warning('SYNC_STATS_LOADED_PRESERVED all_original_fields=true users=%d', len(original['total_users']))
