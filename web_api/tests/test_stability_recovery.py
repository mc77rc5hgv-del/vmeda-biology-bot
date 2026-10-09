import asyncio
import json
import logging
from concurrent.futures import Future
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from services.stats_writer import StatsWriter
from web_api.sync_transport import BotGateway


def test_cancellation_race_does_not_lose_other_durability_confirmations(tmp_path):
    writer = StatsWriter(lambda: {}, str(tmp_path / 'stats.json'), logging.getLogger(__name__))
    canceled, other = Future(), Future()
    original_done = canceled.done
    first = True

    def cancel_between_check_and_confirmation():
        nonlocal first
        if first:
            first = False
            canceled.cancel()
            return False
        return original_done()

    canceled.done = cancel_between_check_and_confirmation
    writer._waiters = [(1, canceled), (1, other)]
    try:
        writer._finish(1)
        assert canceled.cancelled()
        assert other.result(timeout=.1) is None
        assert writer._waiters == []
    finally:
        writer.executor.shutdown()


@pytest.mark.asyncio
async def test_snapshot_failure_finishes_waiter_and_next_save_recovers(tmp_path):
    data = {'total_users': {123}, 'preserved_field': {'username': 'synthetic'}}
    path = tmp_path / 'stats.json'
    writer = StatsWriter(lambda: data, str(path), logging.getLogger(__name__))
    snapshot = writer._snapshot
    writer._snapshot = AsyncMock(side_effect=ValueError('synthetic snapshot failure'))
    try:
        with pytest.raises(ValueError, match='synthetic snapshot failure'):
            await asyncio.wait_for(asyncio.wrap_future(writer.save()), timeout=1)
        assert not path.exists()
        writer._snapshot = snapshot
        await asyncio.wait_for(writer.flush(), timeout=1)
        assert json.loads(path.read_text()) == {'total_users': [123], 'preserved_field': {'username': 'synthetic'}}
        assert writer._waiters == []
    finally:
        if writer._task and not writer._task.done():
            writer._task.cancel()
            await asyncio.gather(writer._task, return_exceptions=True)
        writer.executor.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize('close_error', [httpx.WriteError('synthetic close failure'), asyncio.CancelledError()])
async def test_gateway_cleanup_always_releases_capacity(close_error):
    gateway = BotGateway(AsyncMock(), 'http://owner.test', 'synthetic-secret')
    response = httpx.Response(200, content=b'complete')
    response.aclose = AsyncMock(side_effect=close_error)
    gateway._client = Mock()
    gateway._client.build_request.return_value = httpx.Request('POST', 'http://owner.test/api/v1/test')
    gateway._client.send = AsyncMock(return_value=response)
    scope = {'type': 'http', 'path': '/api/v1/test', 'method': 'POST', 'headers': [], 'query_string': b''}
    receive = AsyncMock(return_value={'type': 'http.request', 'body': b''})
    send = AsyncMock()
    if isinstance(close_error, asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await gateway(scope, receive, send)
    else:
        await gateway(scope, receive, send)
        assert gateway.failures == 1
    assert gateway._active == 0
    assert gateway._client.send.await_count == 1  # Never replay a POST after an error.
    response.aclose.side_effect = None
    await gateway(scope, receive, send)
    assert gateway._active == 0
