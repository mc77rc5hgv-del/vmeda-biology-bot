"""Append-only answers and durable, resumable anatomy runs on the existing learning DB."""
import json
import uuid
from contextlib import closing

from fastapi import HTTPException

from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


def _connection():
    from .learning import _connect
    conn = _connect()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS anatomy_runs (
          id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, source TEXT NOT NULL,
          kind TEXT NOT NULL, rating INTEGER NOT NULL, queue TEXT NOT NULL,
          created_at TEXT NOT NULL, finished_at TEXT);
        CREATE INDEX IF NOT EXISTS anatomy_runs_user ON anatomy_runs(user_id, created_at);
        CREATE TABLE IF NOT EXISTS anatomy_answers (
          run_id TEXT NOT NULL REFERENCES anatomy_runs(id), position INTEGER NOT NULL,
          question_num INTEGER NOT NULL, chosen TEXT NOT NULL, correct INTEGER NOT NULL,
          answered_at TEXT NOT NULL, PRIMARY KEY(run_id, position));
    ''')
    return conn


def create_anatomy_run(user_id: int, source: str, kind: str, rating: bool, queue: list[int], run_id: str | None = None):
    if source not in {'bot', 'miniapp'} or kind not in {'part', 'flash', 'mistakes'} or not queue or len(queue) > 2000:
        raise HTTPException(status_code=422, detail='Некорректная попытка')
    run_id = run_id or uuid.uuid4().hex
    with closing(_connection()) as conn, conn:
        conn.execute('INSERT INTO anatomy_runs VALUES (?, ?, ?, ?, ?, ?, ?, NULL) ON CONFLICT(id) DO NOTHING',
                     (run_id, user_id, source, kind, int(rating), json.dumps(queue), _now()))
    run = get_anatomy_run(user_id, run_id)
    if (run['source'], run['kind'], bool(run['rating']), run['queue']) != (source, kind, bool(rating), queue):
        raise HTTPException(status_code=409, detail='Попытка уже существует с другими параметрами')
    return run


def get_anatomy_run(user_id: int, run_id: str):
    with closing(_connection()) as conn:
        row = conn.execute('SELECT * FROM anatomy_runs WHERE id=? AND user_id=?', (run_id, user_id)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail='Попытка не найдена')
        answers = conn.execute('SELECT position, question_num, chosen, correct FROM anatomy_answers WHERE run_id=? ORDER BY position', (run_id,)).fetchall()
    result = dict(row)
    result['queue'] = json.loads(result['queue'])
    result['answers'] = [dict(answer) for answer in answers]
    result['correct'] = sum(answer['correct'] for answer in answers)
    result['answered'] = len(answers)
    return result


def active_anatomy_run(user_id: int, source: str = 'miniapp'):
    with closing(_connection()) as conn:
        row = conn.execute('SELECT id FROM anatomy_runs WHERE user_id=? AND source=? AND finished_at IS NULL ORDER BY rowid DESC LIMIT 1', (user_id, source)).fetchone()
    return get_anatomy_run(user_id, row['id']) if row else None


def answer_anatomy_run(user_id: int, run_id: str, position: int, question_num: int, chosen: str, correct: bool):
    with closing(_connection()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM anatomy_runs WHERE id=? AND user_id=?', (run_id, user_id)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail='Попытка не найдена')
        queue = json.loads(row['queue'])
        if not 0 <= position < len(queue) or queue[position] != question_num:
            raise HTTPException(status_code=409, detail='Вопрос не принадлежит попытке')
        old = conn.execute('SELECT chosen, correct FROM anatomy_answers WHERE run_id=? AND position=?', (run_id, position)).fetchone()
        if old:
            if old['chosen'] != chosen:
                raise HTTPException(status_code=409, detail='Ответ уже сохранён; изменить его нельзя')
            return {'correct': bool(old['correct']), 'duplicate': True}
        count = conn.execute('SELECT COUNT(*) FROM anatomy_answers WHERE run_id=?', (run_id,)).fetchone()[0]
        if row['finished_at'] or position != count:
            raise HTTPException(status_code=409, detail='Начни с текущего вопроса')
        conn.execute('INSERT INTO anatomy_answers VALUES (?, ?, ?, ?, ?, ?)', (run_id, position, question_num, chosen, int(correct), _now()))
        if count + 1 == len(queue):
            conn.execute('UPDATE anatomy_runs SET finished_at=? WHERE id=?', (_now(), run_id))
    return {'correct': bool(correct), 'duplicate': False}


def get_anatomy_mistakes(user_id: int):
    with closing(_connection()) as conn:
        rows = conn.execute('''SELECT question_num, correct FROM anatomy_answers a
          JOIN anatomy_runs r ON r.id=a.run_id WHERE r.user_id=? ORDER BY a.rowid''', (user_id,)).fetchall()
    latest = {row['question_num']: row['correct'] for row in rows}
    return [num for num, correct in latest.items() if not correct]


def get_anatomy_scores(user_id: int, kind: str):
    # user_id is required even for the shared ranking RPC: the caller must be authenticated.
    with closing(_connection()) as conn:
        rows = conn.execute('''SELECT r.user_id, r.id, COUNT(*) total, SUM(a.correct) correct
          FROM anatomy_runs r JOIN anatomy_answers a ON a.run_id=r.id
          WHERE r.finished_at IS NOT NULL AND r.kind=? AND (r.rating=1 OR r.kind='flash')
          GROUP BY r.id''', (kind,)).fetchall()
    scores = {}
    for row in rows:
        uid = str(row['user_id'])
        if kind == 'flash':
            entry = scores.setdefault(uid, {'best_correct': 0, 'best_total': 0, 'attempts': 0})
            if (row['correct']/row['total'], row['total']) > (entry['best_correct']/entry['best_total'] if entry['best_total'] else 0, entry['best_total']):
                entry.update(best_correct=row['correct'], best_total=row['total'])
        else:
            entry = scores.setdefault(uid, {'correct': 0, 'total': 0, 'attempts': 0})
            entry['correct'] += row['correct']
            entry['total'] += row['total']
        entry['attempts'] += 1
    return scores
