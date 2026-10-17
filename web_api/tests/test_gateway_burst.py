"""Short bursts queue without increasing owner concurrency or replaying POSTs."""
import asyncio
from collections import Counter

import httpx
import pytest

from web_api.sync_transport import BotGateway


async def unexpected_fallback(scope, receive, send):
    raise AssertionError('An API request must not reach local fallback')


@pytest.mark.asyncio
async def test_hundred_request_burst_preserves_bounded_owner_and_unique_posts():
    active = peak = 0
    forwarded = []
    async def owner(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            assert request.headers['X-Vmeda-Sync-Token'] == 'synthetic-owner-secret'
            forwarded.append(request.content)
            await asyncio.sleep(.02)
            return httpx.Response(200, json={'ok': True})
        finally:
            active -= 1
    gateway = BotGateway(unexpected_fallback, 'http://owner.test', 'synthetic-owner-secret')
    async with httpx.AsyncClient(transport=httpx.MockTransport(owner)) as upstream:
        gateway._client = upstream
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway), base_url='http://gateway.test') as client:
            results = await asyncio.gather(*(client.post('/api/v1/synthetic', json={'event': n}) for n in range(100)))
    assert all(response.status_code == 200 for response in results)
    assert max(Counter(forwarded).values()) == 1 and len(forwarded) == 100
    assert peak <= 64 and gateway._active == gateway._waiting == 0
    assert gateway.rejected == 0


@pytest.mark.asyncio
async def test_queue_full_timeout_and_cancellation_never_leak_capacity():
    started, release = asyncio.Event(), asyncio.Event()
    forwarded = []
    async def owner(request):
        forwarded.append(request.content)
        started.set()
        await release.wait()
        return httpx.Response(200, json={'ok': True})
    gateway = BotGateway(unexpected_fallback, 'http://owner.test', 'synthetic-owner-secret',
                         max_active=1, max_waiting=1, queue_timeout=.05)
    async with httpx.AsyncClient(transport=httpx.MockTransport(owner)) as upstream:
        gateway._client = upstream
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway), base_url='http://gateway.test') as client:
            first = asyncio.create_task(client.post('/api/v1/synthetic', content=b'first'))
            await started.wait()
            queued = asyncio.create_task(client.post('/api/v1/synthetic', content=b'timed-out'))
            while not gateway._waiting:
                await asyncio.sleep(0)
            full = await client.post('/api/v1/synthetic', content=b'queue-full')
            assert full.status_code == 503 and full.headers['Retry-After'] == '5'
            assert (await queued).status_code == 503
            assert forwarded == [b'first'] and gateway._waiting == 0
            cancelled = asyncio.create_task(client.post('/api/v1/synthetic', content=b'cancelled'))
            while not gateway._waiting:
                await asyncio.sleep(0)
            cancelled.cancel()
            with pytest.raises(asyncio.CancelledError):
                await cancelled
            assert gateway._waiting == 0
            release.set()
            assert (await first).status_code == 200
            assert (await client.post('/api/v1/synthetic', content=b'recovered')).status_code == 200
    assert forwarded == [b'first', b'recovered']
    assert gateway._active == gateway._waiting == 0


@pytest.mark.asyncio
async def test_upstream_failure_never_replays_a_post():
    calls = []
    async def owner(request):
        calls.append(request.content)
        raise httpx.ReadError('synthetic ambiguous response')
    gateway = BotGateway(unexpected_fallback, 'http://owner.test', 'synthetic-owner-secret')
    async with httpx.AsyncClient(transport=httpx.MockTransport(owner)) as upstream:
        gateway._client = upstream
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway), base_url='http://gateway.test') as client:
            response = await client.post('/api/v1/subscriptions/sbp', content=b'synthetic-stable-checkout-key')
            assert response.status_code == 503
    assert calls == [b'synthetic-stable-checkout-key']
    assert gateway._active == gateway._waiting == 0
