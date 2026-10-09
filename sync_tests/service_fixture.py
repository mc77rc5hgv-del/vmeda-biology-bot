"""Synthetic owner for integration tests. Never starts Telegram polling."""
import asyncio
import os
from pathlib import Path

if os.environ.get('BOT_TOKEN') != '123456789:AAIntegrationTestTokenNotReal00000000' or os.environ.get('VMEDA_SYNTHETIC_RUN') != '1' or not Path(os.environ.get('STATS_DIR', '')).name.startswith('owner-'):
    raise RuntimeError('This fixture may run only with explicitly isolated synthetic data')

import telegram_bot as tb
tb._sync_owner_running = True
from web_api.data_safety import backup_stats, verify_loaded_stats
verify_loaded_stats(backup_stats(tb.STATS_FILE), tb.stats)
from web_api.main import app
from pydantic import BaseModel


class Grant(BaseModel):
    user_id: int
    tier: int
    subject: str | None = None


@app.post('/internal/test/grant')
async def grant(body: Grant):
    tb.grant_subscription(body.user_id, body.tier, 'synthetic', 0, body.subject)
    await asyncio.wrap_future(tb.save_stats())
    return {'ok': True}


@app.post('/internal/test/histology')
async def histology(payload: dict):
    await asyncio.to_thread(tb.record_histology_result, payload['user_id'], payload['specimen_id'], payload['known'], payload['event_id'])
    return {'ok': True}


@app.post('/internal/test/anatomy')
async def anatomy(payload: dict):
    from web_api import learning
    await asyncio.to_thread(learning.create_anatomy_run, payload['user_id'], 'bot', 'part', True, [1], 'synthetic-bot-run')
    q = tb.ANATOMY_EXAM_TEST_PARTS[0]['questions'][0]
    await asyncio.to_thread(learning.answer_anatomy_run, payload['user_id'], 'synthetic-bot-run', 0, 1, q['correct'], True)
    return {'ok': True}


@app.post('/internal/test/tester')
async def tester(payload: dict):
    from services.miniapp_testers import set_test_access
    saved = set_test_access(tb, next(iter(tb.ADMIN_IDS)), payload['user_id'], active=payload['active'])
    await asyncio.wrap_future(saved)
    return {'ok': True}


@app.post('/internal/test/promo')
async def promo(payload: dict):
    from services.miniapp_policy import set_promo
    await asyncio.wrap_future(set_promo(tb, next(iter(tb.ADMIN_IDS)), payload['active']))
    return {'ok': True}
