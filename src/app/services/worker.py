from __future__ import annotations

import asyncio
import contextlib


class JobWorker:
    def __init__(self, ingestion_service: object, poll_interval_seconds: float) -> None:
        self.ingestion_service = ingestion_service
        self.poll_interval_seconds = poll_interval_seconds
        self._stop_event = asyncio.Event()

    async def run(self) -> None:
        while not self._stop_event.is_set():
            processed = await self.ingestion_service.process_next_job("fastapi-worker")
            if processed:
                continue
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.poll_interval_seconds,
                )
            except asyncio.TimeoutError:
                continue

    async def stop(self) -> None:
        self._stop_event.set()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.sleep(0), timeout=0.1)
