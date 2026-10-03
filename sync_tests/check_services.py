"""Actual owner/gateway HTTP integration on synthetic volumes; never production."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlencode

import httpx

ROOT = Path(__file__).resolve().parents[1]
folder = Path(tempfile.mkdtemp(prefix='vmeda-service-sync-'))
owner_data = folder / 'owner-data'; owner_data.mkdir()
gateway_data = folder / 'gateway-data'; gateway_data.mkdir()
user_id = 8123456
bot_token = '123456789:AAIntegrationTestTokenNotReal00000000'
token = 'synthetic-internal-token'
baseline = {'total_users': [user_id], 'user_names': {str(user_id): 'Preserved name'},
            'user_username': {str(user_id): 'preserved_username'}, 'usernames': {'preserved_username': user_id},
            'histology_learning': {str(user_id): {'attempts': 4, 'known': 2, 'wrong': 2, 'mistakes': ['d1_01'], 'mastered': ['d1_02']}},
            'anatomy_exam_test_scores': {str(user_id): {'correct': 3, 'total': 5, 'attempts': 1}},
            'unknown_future_field': {'must_preserve': [1, 2, 3]}}
(owner_data/'stats.json').write_text(json.dumps(baseline))
# Deliberately inconsistent gateway stats must NEVER be consulted for entitlements.
(gateway_data/'stats.json').write_text(json.dumps({'total_users': [], 'subscriptions': {}}))
gateway_snapshot = (gateway_data/'stats.json').read_bytes()
db = gateway_data/'miniapp_learning.sqlite3'
with sqlite3.connect(db) as conn:
    conn.execute('CREATE TABLE legacy_identity(user_id INTEGER PRIMARY KEY, username TEXT)')
    conn.execute('INSERT INTO legacy_identity VALUES (?, ?)', (user_id, 'preserved_username'))


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


owner_port, gateway_port = port(), port()
owner_url, gateway_url = f'http://127.0.0.1:{owner_port}', f'http://127.0.0.1:{gateway_port}'
common = dict(os.environ, BOT_TOKEN=bot_token, SESSION_SECRET='synthetic-session-secret', BOT_SYNC_TOKEN=token,
              MINIAPP_ACCESS_MODE='public', WEB_API_ALLOWED_ORIGINS='https://synthetic-miniapp.test',
              OPENAI_API_KEY='', GEMINI_API_KEY='', XAI_API_KEY='', VMEDA_SYNTHETIC_RUN='1', AI_BUILD_EMBEDDINGS_ON_START='0')
owner_env = dict(common, BOT_SYNC_MODE='owner', STATS_DIR=str(owner_data), LEARNING_BACKEND_URL=gateway_url, MINIAPP_LEARNING_DB=str(owner_data/'unused.sqlite3'))
gateway_env = dict(common, BOT_SYNC_MODE='gateway', STATS_DIR=str(gateway_data), BOT_SYNC_URL=owner_url, MINIAPP_LEARNING_DB=str(db), SYNC_REQUIRE_EXISTING_DB='1')
processes = []; logs = []


def launch(module, number, env):
    output = (folder / (module.replace('.', '-') + f'-{len(logs)}.log')).open('w')
    logs.append(output)
    proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', module+':app', '--host', '127.0.0.1', '--port', str(number), '--log-level', 'warning'], cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT)
    processes.append(proc)
    return proc


client = httpx.Client(timeout=15, trust_env=False)


def ready(url, proc):
    for _ in range(150):
        if proc.poll() is not None:
            raise RuntimeError(f'Synthetic service exited: {proc.returncode}; logs in {folder}')
        try:
            if client.get(url+'/healthz').status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(.1)
    raise RuntimeError('Synthetic service did not become ready')


def signed_init_data():
    fields = {'user': json.dumps({'id': user_id, 'first_name': 'New name must not overwrite', 'username': 'must_not_replace'}), 'auth_date': str(int(time.time()))}
    key = hmac.new(b'WebAppData', bot_token.encode(), hashlib.sha256).digest()
    fields['hash'] = hmac.new(key, '\n'.join(f'{k}={v}' for k, v in sorted(fields.items())).encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def auth():
    response = client.post(gateway_url+'/api/v1/auth/telegram', json={'init_data': signed_init_data()})
    assert response.status_code == 200, response.text
    return {'Authorization': 'Bearer '+response.json()['session_token']}


try:
    gateway = launch('web_api.main', gateway_port, gateway_env); ready(gateway_url, gateway)
    owner = launch('sync_tests.service_fixture', owner_port, owner_env); ready(owner_url, owner)
    headers = auth()
    assert client.get(owner_url+'/api/v1/me').status_code == 403
    assert client.get(gateway_url+'/api/v1/me').status_code == 401
    response = client.get(gateway_url+'/api/v1/access/histology', headers=headers)
    assert response.json()['trial_available'] and not response.json()['can_open_subject']
    assert client.post(gateway_url+'/api/v1/access/histology/enter', headers=headers).json()['trial_started']
    assert not client.post(gateway_url+'/api/v1/access/histology/enter', headers=headers).json()['trial_started']
    internal = {'X-Vmeda-Sync-Token': token}
    assert client.get(gateway_url+'/internal/sync/status').status_code == 403
    safety = client.get(gateway_url+'/internal/sync/status', headers=internal).json()
    assert safety['backups']['learning']['verified']
    assert safety['owner']['backups']['stats']['loaded_data_preserved']
    assert safety['owner']['users'] == 1
    assert client.post(owner_url+'/internal/test/grant', headers=internal, json={'user_id': user_id, 'tier': 24}).status_code == 200
    assert client.get(gateway_url+'/api/v1/subscription', headers=headers).json()['subscription_title']
    assert client.get(gateway_url+'/api/v1/sync/state', headers=headers).json()['source'] == 'running_bot'
    practical = client.get(gateway_url+'/api/v1/histology/exam/practical?limit=1', headers=headers).json()[0]
    grade_url = gateway_url+f"/api/v1/histology/exam/specimens/{practical['id']}/grade"
    grade_body = {'known': True, 'scope': 'all', 'attempt_id': practical['attempt_id']}
    assert client.post(grade_url, headers=headers, json=grade_body).json()['attempts'] == 5
    assert client.post(grade_url, headers=headers, json=grade_body).json()['attempts'] == 5
    assert client.post(owner_url+'/internal/test/histology', headers=internal, json={'user_id': user_id, 'specimen_id': 'd1_01', 'known': True, 'event_id': 'synthetic-bot-histology'}).status_code == 200
    assert client.get(gateway_url+'/api/v1/histology/exam/stats', headers=headers).json()['attempts'] == 6
    run = client.post(gateway_url+'/api/v1/anatomy/exam/runs', headers=headers, json={'kind': 'part', 'part_id': 1, 'rating': True}).json()
    body = {'position': 0, 'selected_index': 0}
    answer_url = gateway_url+f"/api/v1/anatomy/exam/runs/{run['id']}/answer"
    first = client.post(answer_url, headers=headers, json=body)
    assert first.status_code == 200, first.text
    assert client.post(answer_url, headers=headers, json=body).status_code == 200
    assert client.get(gateway_url+'/api/v1/anatomy/exam/runs/active', headers=headers).json()['answered'] == 1
    # Short fixture bot run updates the SAME ranking; incomplete miniapp run does not.
    assert client.post(owner_url+'/internal/test/anatomy', headers=internal, json={'user_id': user_id}).status_code == 200
    rating = client.get(gateway_url+'/api/v1/anatomy/exam/ratings/part', headers=headers).json()['entries'][0]
    assert (rating['correct'], rating['total'], rating['attempts']) == (4, 6, 2)
    owner.terminate(); owner.wait(timeout=10)
    outage = client.get(gateway_url+'/api/v1/subscription', headers=headers)
    assert outage.status_code == 503 and outage.headers['cache-control'] == 'no-store'
    assert client.get(gateway_url+'/api/v1/subscription', headers={**headers, 'Origin': 'https://synthetic-miniapp.test'}).headers['access-control-allow-origin'] == 'https://synthetic-miniapp.test'
    owner = launch('sync_tests.service_fixture', owner_port, owner_env); ready(owner_url, owner)
    assert client.post(grade_url, headers=headers, json=grade_body).json()['attempts'] == 6  # signed key survives restart
    assert client.get(gateway_url+'/api/v1/anatomy/exam/runs/active', headers=headers).json()['answered'] == 1
    assert client.post(answer_url, headers=headers, json=body).status_code == 200
    persisted = json.loads((owner_data/'stats.json').read_text())
    for key in ['user_names', 'user_username', 'usernames', 'histology_learning', 'anatomy_exam_test_scores', 'unknown_future_field']:
        assert persisted[key] == baseline[key], key
    assert (gateway_data/'stats.json').read_bytes() == gateway_snapshot
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT * FROM legacy_identity').fetchall() == [(user_id, 'preserved_username')]
    assert list((gateway_data/'sync_backups').glob('learning-*.sqlite3'))
    if os.environ.get('VMEDA_BROWSER_SMOKE') == '1':
        from browser_smoke import run_browser_smoke
        print(json.dumps(run_browser_smoke(gateway_url, signed_init_data(), client, headers)))
    print(json.dumps({'real_owner_gateway_http': True, 'subscription_visible_immediately': True,
                      'histology_retry_survives_restart': True, 'anatomy_resume_and_common_rating': True,
                      'outage_fails_closed_with_cors': True, 'legacy_identity_and_stats_preserved': True,
                      'synthetic_directory': str(folder)}, ensure_ascii=False, indent=2))
finally:
    for proc in processes:
        if proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=10)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait()
    client.close()
    for output in logs: output.close()
