"""Single durable writer: bounded snapshots, cooperative consistent copy, atomic replace.

Every save returns its own durability barrier. Cancellation of one caller cannot cancel
another payment's barrier. A save arriving during a snapshot invalidates that copy;
no half-old/half-new payment or subscription snapshot is ever committed.
"""
import asyncio
import copy
import json
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor


class ChangedDuringCopy(Exception):
    pass


class StatsWriter:
    def __init__(self, source, path, logger):
        self.source, self.path, self.logger = source, path, logger
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='stats-writer')
        self._lock = threading.Lock()
        self._generation = 0
        self._waiters = []
        self._task = None
        self._loop = None
        self._sync_pending = None
        self._sync_running = False

    def save(self):
        barrier = Future()
        with self._lock:
            self._generation += 1
            self._waiters.append((self._generation, barrier))
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = self._loop if self._loop and self._loop.is_running() else None
        if loop:
            self._loop = loop
            loop.call_soon_threadsafe(self._start)
        else:
            # Startup/tests without a running event loop; never queue unlimited snapshots.
            data = copy.deepcopy(self.source())
            with self._lock:
                self._sync_pending = (self._generation, data)
                if not self._sync_running:
                    self._sync_running = True
                    self.executor.submit(self._sync_drain)
        return barrier

    def _start(self):
        if not self._task or self._task.done():
            self._task = asyncio.create_task(self._drain(), name='vmeda-stats-durable-writer')

    def _finish(self, generation, error=None):
        with self._lock:
            done = [f for g, f in self._waiters if g <= generation]
            self._waiters = [(g, f) for g, f in self._waiters if g > generation]
        for future in done:
            if not future.done():
                if error:
                    future.set_exception(error)
                else:
                    future.set_result(None)

    def _write(self, data):
        data['total_users'] = list(data.get('total_users', []))
        tmp = self.path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, self.path)
        directory = os.open(os.path.dirname(os.path.abspath(self.path)), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    async def _snapshot(self, generation):
        deadline = time.monotonic() + .003
        async def clone(value):
            nonlocal deadline
            if time.monotonic() >= deadline:
                await asyncio.sleep(0)
                if self._generation != generation:
                    raise ChangedDuringCopy()
                deadline = time.monotonic() + .003
            if isinstance(value, dict):
                result = {}
                for key, child in value.items():
                    result[key] = await clone(child)
                return result
            if isinstance(value, list):
                return [await clone(child) for child in value]
            if isinstance(value, set):
                return {await clone(child) for child in value}
            if isinstance(value, tuple):
                return tuple([await clone(child) for child in value])
            return value  # JSON scalar, immutable
        result = await clone(self.source())
        if generation != self._generation:
            raise ChangedDuringCopy()
        return result

    async def _drain(self):
        retries = 0
        while self._waiters:
            await asyncio.sleep(.025)  # combine bursts, payments still await fsync
            generation = self._generation
            try:
                snapshot = await self._snapshot(generation)
            except (ChangedDuringCopy, RuntimeError):
                retries += 1
                if retries < 3:
                    continue
                # Never starve payment fsync under continuous mutations. Rare bounded
                # fallback takes one consistent snapshot, rather than one per event.
                generation = self._generation
                snapshot = copy.deepcopy(self.source())
            retries = 0
            try:
                await asyncio.get_running_loop().run_in_executor(self.executor, self._write, snapshot)
            except Exception as exc:
                self.logger.error('Не удалось сохранить статистику: %s', exc)
                self._finish(generation, exc)
            else:
                self._finish(generation)

    def _sync_drain(self):
        while True:
            with self._lock:
                pending, self._sync_pending = self._sync_pending, None
                if pending is None:
                    self._sync_running = False
                    return
            generation, data = pending
            try:
                self._write(data)
            except Exception as exc:
                self.logger.error('Не удалось сохранить статистику: %s', exc)
                self._finish(generation, exc)
            else:
                self._finish(generation)

    async def flush(self):
        barrier = self.save()
        await asyncio.shield(asyncio.wrap_future(barrier))
        if self._task:
            await self._task
