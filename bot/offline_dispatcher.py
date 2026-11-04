"""Explicit offline-only queue dispatcher for integration tests.

Not wired into Telegram polling: production user links must never generate
synthetic files. Exactly one job is dispatched at a time.
"""
import asyncio
import logging
from pathlib import Path

from .offline_queue_integration import process_one_offline_task


async def run_offline_dispatcher(
    *, stop: asyncio.Event, db_path: Path, socket_path: Path,
    configured_download_dir: str, max_wait_minutes: int = 30,
    project_root: Path = Path("."), idle_seconds: float = 0.1,
) -> None:
    """Sequentially drain an explicitly provided offline test queue."""
    if not isinstance(stop, asyncio.Event) or idle_seconds <= 0:
        raise ValueError("Некорректные параметры диспетчера")
    while not stop.is_set():
        task_id = await process_one_offline_task(
            db_path=db_path, socket_path=socket_path,
            configured_download_dir=configured_download_dir,
            max_wait_minutes=max_wait_minutes, project_root=project_root,
        )
        if task_id is not None:
            logging.info("Offline dispatcher обработал задачу %d", task_id)
            continue
        try:
            await asyncio.wait_for(stop.wait(), timeout=idle_seconds)
        except asyncio.TimeoutError:
            pass
