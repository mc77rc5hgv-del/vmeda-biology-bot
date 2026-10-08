"""Standalone synthetic checks; never imports telegram_bot or uses inherited data paths."""
from __future__ import annotations

import ast
import asyncio
import copy
from datetime import datetime, timedelta, timezone
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import types
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
fixture_dir = tempfile.mkdtemp(prefix='vmeda_sync_synthetic_')
os.environ['BOT_SYNC_MODE'] = 'legacy'
os.environ['STATS_DIR'] = fixture_dir
os.environ['MINIAPP_LEARNING_DB'] = str(Path(fixture_dir) / 'learning.sqlite3')
os.environ['BOT_TOKEN'] = '123456789:SyntheticOnlyNotARealBotToken'
os.environ['SESSION_SECRET'] = 'synthetic-session'
os.environ['MINIAPP_ACCESS_MODE'] = 'public'
os.environ['BOT_SYNC_TOKEN'] = 'synthetic-sync-token'
os.environ['LEARNING_BACKEND_URL'] = 'http://synthetic-learning'
saved = []
tb = types.ModuleType('telegram_bot')
tb.APP_TIMEZONE = timezone(timedelta(hours=3))
tb.local_today = lambda: datetime.now(tb.APP_TIMEZONE).date()
tb.ADMIN_IDS = {1}
tb.stats = {
    'subscriptions': {}, 'user_names': {'11': 'Историческое имя'},
    'user_username': {'11': 'preserve_me'}, 'referrals': {}, 'referral_monthly': {},
    'manual_access_granted': set(), 'temporary_access': {}, 'assistant_admins': [],
    'payment_admins': [], 'section_promos': {}, 'subscription_purchase_log': [],
    'histology_temp_access': {}, 'histology_warnings': {}, 'histology_learning': {},
    'manual_anatomy_demo_granted': [], 'referral_warnings': {'11': {'count': 3}},
}
tb.save_stats = lambda: saved.append(copy.deepcopy(tb.stats))
sys.modules['telegram_bot'] = tb
from services import access as real_access
for name in dir(real_access):
    if not name.startswith('__'): setattr(tb, name, getattr(real_access, name))
tb.stats['histology_learning']['11'] = {'attempts': 4, 'known': 2, 'wrong': 2, 'mastered': ['d1'], 'mistakes': ['d2']}
tb.HISTOLOGY = {'g': {'specimens': [{'id': 'd1'}, {'id': 'd2'}]}}
tb.dynamic_course_under_maintenance = lambda subject: subject == 'pharmacology'
tb.anatomy_maintenance_mode_enabled = lambda: False
tb.has_unlimited_ai = lambda uid: False
tb.ai_requests_left = lambda uid: 3
tb.ai_provider_available = lambda: True
tb._sync_owner_running = True

def extract(names: set[str], environment: dict, filename='handlers/histology.py'):
    nodes=[]
    for node in ast.parse((ROOT/filename).read_text()).body:
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in names:
            node.decorator_list=[];nodes.append(node)
    module=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)]+nodes,type_ignores=[])
    exec(compile(ast.fix_missing_locations(module),'isolated-histology','exec'),environment)

env={'tb':tb,'time':time,'HISTOLOGY_PUBLIC':False,'HISTOLOGY_WARNING_THRESHOLD':3}
extract({'get_histology_temp_expiry','has_histology_temp_access','histology_permanently_unlocked','histology_access_ok'},env)
tb.histology_access_ok=env['histology_access_ok']
tb.histology_permanently_unlocked=env['histology_permanently_unlocked']
anatomy_env={'tb':tb,'ANATOMY_PUBLIC':False,'ANATOMY_FREE_SECTIONS':{'module1_osteology'},'ANATOMY_MAINTENANCE_MODE':True}
extract({'anatomy_access_ok','anatomy_section_access_ok','anatomy_maintenance_mode_enabled'},anatomy_env,'handlers/anatomy.py')
tb.has_manual_anatomy_demo_access=lambda uid:False
tb.ANATOMY={'module1_osteology':{},'module7_nervous':{}}
tb.anatomy_section_access_ok=anatomy_env['anatomy_section_access_ok']
from web_api import bot_state, learning
from web_api.routers import access as api_access
checks=0

# Every published and legacy tier: restrictions, expiry, explicit entitlement flags.
for tier in real_access.SUBSCRIPTION_TIERS:
    cfg=real_access.SUBSCRIPTION_TIERS[tier]
    for selected in ['biology','physics','chemistry']:
        real_access.grant_subscription(11,tier,'synthetic',0,selected)
        sub=tb.stats['subscriptions']['11']
        for expired in [False,True]:
            sub['expires']=time.time()+60 if not expired else time.time()-60
            for subject in ['biology','physics','chemistry']:
                assert api_access._subject_is_open(tb,11,subject)==tb.has_subject_access(11,subject)
                checks+=1
            assert api_access._subject_is_open(tb,11,'histology')==tb.histology_access_ok(11)
            checks+=1
            assert tb.anatomy_section_access_ok(11,'module1_osteology')
            assert tb.anatomy_section_access_ok(11,'module7_nervous')==tb.has_subscription_anatomy_access(11)
            checks+=2
tb.stats['subscriptions'].clear()
before=copy.deepcopy(tb.stats)
for subject in api_access.SUBJECT_IDS:
    api_access._subject_is_open(tb,11,subject)
assert tb.stats==before
from web_api.routers.sync import sync_state
snapshot=sync_state(11,tb)
assert snapshot['source']=='legacy_local_file'
assert not snapshot['subscription']['active']
assert snapshot['anatomy_modules']['module1_osteology']
assert not snapshot['anatomy_modules']['module7_nervous']
tb.stats['histology_temp_access']['11']=time.time()+60
tb.stats['histology_warnings']['11']={'count':3,'last_warn_at':0}
assert not tb.histology_access_ok(11)
tb.stats['histology_warnings']['11']['count']=0
assert tb.histology_access_ok(11)

# Referent month, manual access, old subscriptions and expiry are evaluated by native code.
tb.stats['referral_monthly']['11']={'month':tb.local_today().strftime('%Y-%m'),'count':2}
assert all(api_access._subject_is_open(tb,11,s) for s in ['biology','physics','chemistry','histology'])
tb.stats['referral_monthly']['11']['month']='2000-01'
assert not api_access._subject_is_open(tb,11,'biology')
tb.stats['manual_access_granted'].add(11)
assert api_access._subject_is_open(tb,11,'biology')
tb.stats['manual_access_granted'].clear()

# Owner identity must be the live object. No reload of stats.json, even before disk flush.
os.environ['BOT_SYNC_MODE']='owner'
bot_state.refresh_stats()
assert bot_state.get_bot_module() is tb
live_stats=tb.stats
bot_state.refresh_stats()
assert tb.stats is live_stats
os.environ['BOT_SYNC_MODE']='gateway'
try:bot_state.get_bot_module()
except bot_state.BotStateUnavailableError:pass
else:raise AssertionError('Gateway accepted local state')
os.environ['BOT_SYNC_MODE']='legacy'

# Preserve the existing journal and bot baseline; retries produce only one extra attempt.
learning.record_histology_attempt(11,'d1',False)  # legacy Mini App history
from services.histology_sync import summary
baseline=copy.deepcopy(tb.stats)
assert summary(tb,11)['attempts']==5
learning.record_histology_attempt(11,'d2',True,event_id='new-shared-event')
learning.record_histology_attempt(11,'d2',True,event_id='new-shared-event')
combined=summary(tb,11)
assert combined['attempts']==6 and combined['known']==3
assert combined['mistake_ids']==['d1']
assert tb.stats==baseline
assert tb.stats['user_username']['11']=='preserve_me'
assert learning.get_dashboard(11)['xp']>0

# Stale and simultaneously arriving callbacks cannot advance two questions.
callback_env={'tb':tb,'asyncio':asyncio,'os':os,'HISTOLOGY_GUESS_SESSIONS':{}}
extract({'cb_histology_guess_answer', '_learning_call'},callback_env)
def record(*args):time.sleep(0.01)
callback_env['record_histology_result']=record
async def render(*args):pass
callback_env['render_histology_guess_question']=render
callback_env['render_histology_guess_summary']=render
class Callback:
    data='histology_guess_know:synthetic-run:0'
    from_user=types.SimpleNamespace(id=11)
    async def answer(self,*args,**kwargs):await asyncio.sleep(0)
async def duplicate_callbacks():
    session={'id':'synthetic-run','index':0,'know':0,'dont_know':0,'items':[('g','d1'),('g','d2')]}
    callback_env['HISTOLOGY_GUESS_SESSIONS'][11]=session
    async def synthetic_io(function,*args,**kwargs):
        await asyncio.sleep(0)
        return function(*args,**kwargs)
    with patch('asyncio.to_thread',synthetic_io):
        await asyncio.gather(callback_env['cb_histology_guess_answer'](Callback()),callback_env['cb_histology_guess_answer'](Callback()))
        await callback_env['cb_histology_guess_answer'](Callback())
    assert session['index']==1 and session['know']==1
asyncio.run(duplicate_callbacks())

# Internal RPC is authenticated and has no operations for deleting records or replacing stats.
from web_api.learning_rpc import invoke, install_remote_backend
from fastapi import HTTPException
os.environ['BOT_SYNC_MODE']='gateway'
assert invoke('get_histology_stats',{'user_id':11},'synthetic-sync-token')['result']['attempts']==2
for operation,token in [('get_state','bad-token'),('erase_database','synthetic-sync-token')]:
    try:invoke(operation,{'user_id':11},token)
    except HTTPException:pass
    else:raise AssertionError('Unsafe RPC accepted')

# ASGI proxy preserves Telegram authorization, reads live state, and fails closed.
import httpx
from web_api.sync_transport import BotGateway, OwnerGuard
from starlette.responses import JSONResponse
async def fallback(scope,receive,send):
    raise AssertionError('Public gateway fell back to local handlers')
received=[]
def upstream(request):
    received.append(request)
    assert request.headers['X-Vmeda-Sync-Token']=='synthetic-sync-token'
    assert request.headers['Authorization']=='Bearer synthetic-user-session'
    return httpx.Response(200,json={'revision':len(saved)})
real_client=httpx.AsyncClient
async def roundtrip():
    gateway=BotGateway(fallback,'http://synthetic-owner','synthetic-sync-token')
    with patch('web_api.sync_transport.httpx.AsyncClient',lambda **kw:real_client(transport=httpx.MockTransport(upstream),**kw)):
        async with real_client(transport=httpx.ASGITransport(app=gateway),base_url='http://gateway') as client:
            resp=await client.get('/api/v1/access/biology',headers={'Authorization':'Bearer synthetic-user-session'})
            assert resp.status_code==200 and resp.headers['cache-control']=='no-store'
    def unavailable(request):raise httpx.ConnectError('synthetic outage')
    await gateway._client.aclose()
    gateway._client = None  # replace the transport of the now-shared connection pool
    with patch('web_api.sync_transport.httpx.AsyncClient',lambda **kw:real_client(transport=httpx.MockTransport(unavailable),**kw)):
        async with real_client(transport=httpx.ASGITransport(app=gateway),base_url='http://gateway') as client:
            assert (await client.get('/api/v1/me')).status_code==503
    async def owner(scope,receive,send):
        await JSONResponse({'ok':True})(scope,receive,send)
    async with real_client(transport=httpx.ASGITransport(app=OwnerGuard(owner,'synthetic-sync-token')),base_url='http://owner') as client:
        assert (await client.get('/api/v1/me')).status_code==403
        assert (await client.get('/healthz',headers={'X-Vmeda-Sync-Token':'synthetic-sync-token'})).status_code==200
asyncio.run(roundtrip())

# Remote learning has no local-database fallback when the gateway is unreachable.
namespace={name:getattr(learning,name) for name in importlib.import_module('web_api.learning_rpc').OPERATIONS}
os.environ['BOT_SYNC_MODE']='owner'
install_remote_backend(namespace)
with patch('web_api.learning_rpc.rpc_client') as mock_pool:
    mock_pool.return_value.post.side_effect = httpx.ConnectError('synthetic outage')
    try:namespace['get_state'](11)
    except HTTPException as exc:assert exc.status_code==503
    else:raise AssertionError('Remote learning fell back to empty state')
os.environ['BOT_SYNC_MODE']='legacy'
from services.sync_runtime import start_optional_api
assert start_optional_api() is None

syntax_files=0
for path in ROOT.rglob('*.py'):
    ast.parse(path.read_text());syntax_files+=1
result={'tariff_decisions_checked':checks,'python_files_parsed':syntax_files,'preserved_bot_baseline':True,'duplicate_events_ignored':True,'gateway_and_owner_guards':True,'failed_connections_return_503':True,'synthetic_data_directory':fixture_dir}
(ROOT/'sync_tests/results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False,indent=2))
