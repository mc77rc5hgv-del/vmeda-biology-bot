"""Optional API inside the ONLY process allowed to write the bot's stats.

Disabled by default. Does not launch another poller, change data paths, copy a database,
or cause the bot to stop if the optional listener fails.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import nullcontext

logger = logging.getLogger(__name__)


def start_optional_api():
    if os.environ.get('BOT_SYNC_MODE') != 'owner':
        return None
    try:
        if not os.environ.get('SESSION_SECRET') or not os.environ.get('BOT_SYNC_TOKEN'):
            raise RuntimeError('SESSION_SECRET and BOT_SYNC_TOKEN must be configured')
        if not os.environ.get('LEARNING_BACKEND_URL'):
            raise RuntimeError('Existing learning backend must be configured')
        live = sys.modules.get('telegram_bot')
        if live is None:
            raise RuntimeError('Synchronization owner requires the existing bot module')
        from web_api.data_safety import backup_stats
        backup_stats(live.STATS_FILE)
        live._sync_owner_running = True
        import uvicorn
        from web_api.main import app
        config = uvicorn.Config(
            app, host=os.environ.get('BOT_SYNC_HOST', '::'),
            port=int(os.environ.get('BOT_SYNC_PORT', '8081')), loop='asyncio',
            access_log=False, log_level='warning',
        )
        server = uvicorn.Server(config)
        # Telegram's main coroutine retains ownership of process signal handlers.
        server.install_signal_handlers = lambda: None
        if hasattr(server, 'capture_signals'):
            server.capture_signals = lambda: nullcontext()
    except Exception:
        if 'live' in locals() and live is not None:
            live._sync_owner_running = False
        logger.exception('Optional synchronization API could not start; polling remains active')
        return None

    async def serve():
        try:
            await server.serve()
        except (Exception, SystemExit):
            logger.exception('Optional synchronization API stopped; polling remains active')
        finally:
            live._sync_owner_running = False
    return server, asyncio.create_task(serve(), name='vmeda-owner-api')


async def stop_optional_api(handle):
    if handle is None:
        return
    server, task = handle
    server.should_exit = True
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=10)
    except asyncio.TimeoutError:
        task.cancel()
