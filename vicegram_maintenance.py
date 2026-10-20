"""Explicit, one-off owner cleanup. Defaults to a read-only inventory.

Owner means the account whose correspondence is stored, NOT the sender of each
message. Unknown schemas and files are never guessed away.
"""
import gzip
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

OWNER = 8928384363
VERSION = "owner-cleanup-v1"
LOG = logging.getLogger(__name__)
GROUP = "chat_id IN (SELECT chat_id FROM settings WHERE owner_id = :owner)"
# Dependents first; settings stays available until its dependent rows are removed.
KEEP = {
    "messages": "(source = 'business' AND owner_id = :owner) OR (source = 'group_bot' AND " + GROUP + ")",
    "custom_commands": GROUP,
    "streaks": GROUP,
    "business_connections": "owner_id = :owner",
    "active_notes": "owner_id = :owner",
    "reminders": "user_id = :owner",
    "payments": "user_id = :owner",
    "referrals": "referrer_id = :owner OR referred_id = :owner",
    "settings": "owner_id = :owner",
    "users": "user_id = :owner",
}


def digest_rows(conn):
    result = {}
    for table, predicate in KEEP.items():
        digest = hashlib.sha256()
        for row in conn.execute(f'SELECT * FROM "{table}" WHERE {predicate} ORDER BY rowid', {"owner": OWNER}):
            digest.update(repr(tuple(row)).encode("utf-8"))
            digest.update(b"\n")
        result[table] = digest.hexdigest()
    return result


def validate(conn, db):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if tables != set(KEEP):
        raise RuntimeError("Unexpected cleanup schema: " + repr(sorted(tables ^ set(KEEP))))
    pin = json.loads(db.with_name("vicegram-owner-access.json").read_text())
    if pin != {"username": "vmeda_helper", "user_id": OWNER}:
        raise RuntimeError("Owner identity does not match the authorized cleanup")
    if conn.execute("SELECT count(*) FROM users WHERE user_id = ?", (OWNER,)).fetchone()[0] != 1:
        raise RuntimeError("Expected owner user record is missing")


def inventory(db, media):
    db, media = Path(db).resolve(), Path(media).resolve()
    if not db.is_file() or db.is_symlink() or media == db.parent:
        raise RuntimeError("Unsafe database or media location")
    with closing(sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)) as conn:
        validate(conn, db)
        counts = {}
        for table, predicate in KEEP.items():
            total, kept = conn.execute(f'SELECT count(*), coalesce(sum(coalesce(({predicate}), 0)), 0) FROM "{table}"', {"owner": OWNER}).fetchone()
            counts[table] = {"total": total, "keep": kept, "remove": total - kept}
        protected = set()
        for row in conn.execute("SELECT media_path FROM messages WHERE (" + KEEP["messages"] + ") AND media_path IS NOT NULL", {"owner": OWNER}):
            protected.add(Path(row[0]).resolve())
        known_foreign = set()
        for row in conn.execute("SELECT media_path FROM messages WHERE NOT coalesce((" + KEEP["messages"] + "), 0) AND media_path IS NOT NULL", {"owner": OWNER}):
            known_foreign.add(Path(row[0]).resolve())
    files = {"keep": [], "remove": [], "unknown": []}
    sizes = {key: 0 for key in files}
    if media.exists():
        for directory, dirs, names in os.walk(media, followlinks=False):
            dirs[:] = [n for n in dirs if not (Path(directory) / n).is_symlink()]
            for name in names:
                file = Path(directory) / name
                if file.is_symlink() or not file.is_file():
                    continue
                resolved = file.resolve()
                match = re.fullmatch(r"(\d+)_-?\d+_\d+", name)
                if resolved in protected or (match and int(match[1]) == OWNER):
                    category = "keep"
                elif resolved in known_foreign or (match and int(match[1]) != OWNER):
                    category = "remove"
                else:
                    category = "unknown"
                files[category].append(str(file))
                sizes[category] += file.stat().st_size
    root = []
    for file in db.parent.iterdir():
        if not file.is_symlink():
            root.append({"name": file.name, "directory": file.is_dir(), "bytes": file.stat().st_size if file.is_file() else None})
    return {"version": VERSION, "database_bytes": db.stat().st_size,
            "tables": counts, "media_counts": {k: len(v) for k, v in files.items()},
            "media_bytes": sizes, "volume_root": root}, files


def file_digest(file):
    digest = hashlib.sha256()
    with open(file, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_report(path, report):
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def cleanup(db, media):
    db, media = Path(db).resolve(), Path(media).resolve()
    marker = db.with_name(VERSION + "-complete.json")
    if marker.exists():
        return json.loads(marker.read_text())
    report, files = inventory(db, media)
    # Space for a verified SQLite backup and compression. Never delete first to
    # make room for a backup, and never put a full database snapshot in RAM.
    if shutil.disk_usage(db.parent).free < db.stat().st_size * 2 + 16 * 1024 * 1024:
        raise RuntimeError("Insufficient space for verified cleanup backup")
    plain = db.with_name(VERSION + "-backup.sqlite3")
    archive = db.with_name(VERSION + "-backup.sqlite3.gz")
    if plain.exists() or archive.exists():
        raise RuntimeError("Previous cleanup backup exists; inspect before retry")
    with closing(sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)) as source:
        with closing(sqlite3.connect(plain)) as target:
            source.backup(target)
            if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup integrity check failed")
        source_hash = file_digest(plain)
    with open(plain, "rb") as source, gzip.open(str(archive) + ".tmp", "wb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    digest = hashlib.sha256()
    with gzip.open(str(archive) + ".tmp", "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != source_hash:
        raise RuntimeError("Compressed backup verification failed")
    os.replace(str(archive) + ".tmp", archive)
    with open(archive, "rb") as stream:
        os.fsync(stream.fileno())
    plain.unlink()
    owner_media = {p: file_digest(p) for p in files["keep"]}
    with closing(sqlite3.connect(db, timeout=30)) as conn:
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("BEGIN IMMEDIATE")
        try:
            validate(conn, db)
            before = digest_rows(conn)
            for table, predicate in KEEP.items():
                conn.execute(f'DELETE FROM "{table}" WHERE NOT coalesce(({predicate}), 0)', {"owner": OWNER})
            if digest_rows(conn) != before:
                raise RuntimeError("Owner data changed during cleanup")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Database integrity check failed")
        for name, digest in owner_media.items():
            if file_digest(name) != digest:
                raise RuntimeError("Owner media verification failed")
        removed_bytes = 0
        for name in files["remove"]:
            file = Path(name)
            # Recheck containment and type immediately before unlinking.
            if file.is_symlink() or not file.resolve().is_relative_to(media):
                raise RuntimeError("Unsafe media removal path")
            if file.exists():
                removed_bytes += file.stat().st_size
                file.unlink()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
        if digest_rows(conn) != before or conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Final owner data verification failed")
    final, _ = inventory(db, media)
    if any(t["remove"] for t in final["tables"].values()):
        raise RuntimeError("Unexpected foreign records after cleanup")
    result = {"version": VERSION, "before": report, "after": final,
              "removed_media_bytes": removed_bytes, "owner_rows_verified": True,
              "owner_media_verified": True, "backup": archive.name,
              "backup_bytes": archive.stat().st_size}
    write_report(marker, result)
    return result


def run_maintenance(db, media):
    try:
        if os.getenv("VICEGRAM_OWNER_CLEANUP") == str(OWNER) + ":" + VERSION:
            report = cleanup(db, media)
            LOG.info("VICEGRAM_OWNER_CLEANUP_COMPLETE %s", json.dumps(report, ensure_ascii=False))
        else:
            report, _ = inventory(db, media)
            LOG.info("VICEGRAM_OWNER_CLEANUP_AUDIT %s", json.dumps(report, ensure_ascii=False))
    except Exception:
        # Existing bot can keep serving the owner if maintenance is unavailable.
        # No fallback that drops/reinitializes the existing database is permitted.
        LOG.exception("VICEGRAM_OWNER_CLEANUP_FAILED")
