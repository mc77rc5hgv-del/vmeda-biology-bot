"""Additive off-volume backups with verified restore; never overwrite live data.

Only scoped BACKUP_S3_* credentials are used. No restore-to-production entry point,
no deletion/lifecycle calls, no user data or object URLs in logs.
"""
import asyncio
import hashlib
import hmac
import io
import json
import logging
import os
import sqlite3
import tarfile
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx

logger = logging.getLogger(__name__)
status = {'configured': False, 'last_verified_at': None, 'last_error': None}


def snapshot(directory, names):
    files = {}
    for name in names:
        source = Path(directory) / name
        if not source.is_file():
            raise RuntimeError('Existing backup source missing')
        if name.endswith('.sqlite3'):
            with tempfile.TemporaryDirectory(prefix='vmeda-backup-snapshot-') as scratch:
                destination = Path(scratch) / name
                with sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True, timeout=10) as old, sqlite3.connect(destination) as new:
                    old.backup(new, pages=128)
                    if new.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise RuntimeError('Backup integrity failed')
                files[name] = destination.read_bytes()
        else:
            raw = source.read_bytes()  # stats writer uses atomic replace
            data = json.loads(raw)
            if not isinstance(data.get('total_users'), list):
                raise RuntimeError('Existing user list missing')
            files[name] = raw
    manifest = {name: {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()} for name, raw in files.items()}
    files['manifest.json'] = json.dumps(manifest, sort_keys=True).encode()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
        for name, raw in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(raw), 0o600
            archive.addfile(info, io.BytesIO(raw))
    return buffer.getvalue()


def verify_restore(bundle, destination):
    destination = Path(destination)
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)  # NEVER replace an existing dir
    allowed = {'stats.json', 'billing.sqlite3', 'miniapp_learning.sqlite3', 'manifest.json'}
    with tarfile.open(fileobj=io.BytesIO(bundle), mode='r:gz') as archive:
        members = archive.getmembers()
        if any(m.name not in allowed or not m.isfile() or m.size > 512 * 1024 * 1024 for m in members):
            raise RuntimeError('Invalid backup member')
        if len({m.name for m in members}) != len(members):
            raise RuntimeError('Duplicate backup member')
        for member in members:
            with (destination / member.name).open('xb') as stream:
                os.chmod(stream.name, 0o600)
                stream.write(archive.extractfile(member).read())
    manifest = json.loads((destination / 'manifest.json').read_bytes())
    for name, expected in manifest.items():
        if name not in allowed - {'manifest.json'}:
            raise RuntimeError('Invalid manifest')
        raw = (destination / name).read_bytes()
        if len(raw) != expected['bytes'] or hashlib.sha256(raw).hexdigest() != expected['sha256']:
            raise RuntimeError('Backup checksum failed')
        if name.endswith('.sqlite3'):
            with sqlite3.connect((destination / name).resolve().as_uri() + '?mode=ro', uri=True) as db:
                if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Restored SQLite integrity failed')
        elif name == 'stats.json':
            if not isinstance(json.loads(raw).get('total_users'), list):
                raise RuntimeError('Restored user list missing')
    return manifest


class S3Store:
    def __init__(self, env=None, transport=None):
        env = os.environ if env is None else env
        self.endpoint = env.get('BACKUP_S3_ENDPOINT', '').rstrip('/')
        self.bucket = env.get('BACKUP_S3_BUCKET', '')
        self.region = env.get('BACKUP_S3_REGION', 'auto')
        self.access = env.get('BACKUP_S3_ACCESS_KEY_ID', '')
        self.secret = env.get('BACKUP_S3_SECRET_ACCESS_KEY', '')
        self.style = env.get('BACKUP_S3_URL_STYLE', 'path')
        self.transport = transport
        if not all((self.endpoint.startswith('https://'), self.bucket, self.access, self.secret)):
            raise ValueError('Independent backup credentials unavailable')

    def request(self, method, key, content=b''):
        parsed = urlsplit(self.endpoint)
        host = parsed.netloc if self.style == 'path' else self.bucket + '.' + parsed.netloc
        path = (parsed.path.rstrip('/') + '/' + (self.bucket + '/' if self.style == 'path' else '') + key)
        path = quote(path, safe='/~')
        now = datetime.now(timezone.utc)
        stamp, day = now.strftime('%Y%m%dT%H%M%SZ'), now.strftime('%Y%m%d')
        digest = hashlib.sha256(content).hexdigest()
        canonical_headers = f'host:{host}\nx-amz-content-sha256:{digest}\nx-amz-date:{stamp}\n'
        signed = 'host;x-amz-content-sha256;x-amz-date'
        canonical = '\n'.join([method, path, '', canonical_headers, signed, digest])
        scope = f'{day}/{self.region}/s3/aws4_request'
        string = '\n'.join(['AWS4-HMAC-SHA256', stamp, scope, hashlib.sha256(canonical.encode()).hexdigest()])
        def sign(key, text):
            return hmac.new(key, text.encode(), hashlib.sha256).digest()
        signing = sign(sign(sign(sign(('AWS4' + self.secret).encode(), day), self.region), 's3'), 'aws4_request')
        signature = hmac.new(signing, string.encode(), hashlib.sha256).hexdigest()
        headers = {'Host': host, 'x-amz-date': stamp, 'x-amz-content-sha256': digest,
                   'Authorization': f'AWS4-HMAC-SHA256 Credential={self.access}/{scope}, SignedHeaders={signed}, Signature={signature}'}
        with httpx.Client(timeout=60, transport=self.transport) as client:
            response = client.request(method, 'https://' + host + path, content=content, headers=headers)
            response.raise_for_status()
            return response.content

    def verified_upload(self, key, bundle):
        self.request('PUT', key, bundle)
        restored = self.request('GET', key)
        if hashlib.sha256(restored).digest() != hashlib.sha256(bundle).digest():
            raise RuntimeError('Offsite copy differs')
        with tempfile.TemporaryDirectory(prefix='vmeda-backup-restore-') as scratch:
            verify_restore(restored, Path(scratch) / 'isolated-restore')


async def periodic(tb=None):
    try:
        store = S3Store()
    except ValueError:
        return  # unconfigured is visible in protected operations status
    status['configured'] = True
    owner = tb is not None
    names = ['stats.json'] if owner else ['miniapp_learning.sqlite3']
    if owner and (Path(tb.STATS_DIR) / 'billing.sqlite3').is_file():
        names.append('billing.sqlite3')
    directory = tb.STATS_DIR if owner else os.environ['STATS_DIR']
    while True:
        try:
            if owner:
                from web_api.subscriptions import _persist
                from services.payments.runtime import runtime
                billing = runtime(tb)
                if billing:
                    async with billing._lock:
                        await _persist(tb)
                        bundle = await asyncio.to_thread(snapshot, directory, names)
                else:
                    await _persist(tb)
                    bundle = await asyncio.to_thread(snapshot, directory, names)
            else:
                bundle = await asyncio.to_thread(snapshot, directory, names)
            key = f'vmeda/{"owner" if owner else "learning"}/{datetime.now(timezone.utc):%Y/%m/%d}/{uuid.uuid4().hex}.tar.gz'
            await asyncio.to_thread(store.verified_upload, key, bundle)
            status.update(last_verified_at=time.time(), last_error=None)
            logger.warning('OFFSITE_BACKUP_VERIFIED role=%s restore_integrity=ok', 'owner' if owner else 'learning')
        except asyncio.CancelledError:
            raise
        except Exception:
            status['last_error'] = 'backup_failed'
            logger.error('OFFSITE_BACKUP_FAILED retry_scheduled=true')
        await asyncio.sleep(3600 if status['last_error'] is None else 60)
