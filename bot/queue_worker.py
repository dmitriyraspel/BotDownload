"""Read-only queue inspection while real downloads are disabled.

This module does not claim tasks, change statuses, or execute external code.
"""
from pathlib import Path

from .storage import database


def inspect_next_queued(db_path: Path) -> int | None:
    """Return oldest queued task ID without changing the queue."""
    with database(db_path) as db:
        row = db.execute(
            "SELECT id FROM tasks WHERE status='queued' ORDER BY created_at,id LIMIT 1"
        ).fetchone()
        return row[0] if row else None


def queued_task_cancelled(db_path: Path, task_id: int) -> bool:
    """Check whether a task has been cancelled, without changing state."""
    with database(db_path) as db:
        row = db.execute(
            "SELECT status FROM tasks WHERE id=?", (task_id,)
        ).fetchone()
        return row is not None and row[0] == "cancelled"


# The active worker is deliberately opt-in. No production downloader is wired.
import asyncio
import logging

from .file_lifecycle import FileProcessor, prepare_claimed_file_task
from .storage import claim_next_task


async def process_next_queued_task(
    *, db_path: Path, configured_download_dir: str, expected_bytes: int,
    processor: FileProcessor, max_wait_minutes: int,
    project_root: Path = Path("."),
    reserve_bytes: int = 512 * 1024 * 1024,
) -> int | None:
    """Claim and prepare at most one task; return its ID, or None."""
    with database(db_path) as db:
        task_id = claim_next_task(db, max_wait_minutes=max_wait_minutes)
    if task_id is None:
        return None
    try:
        await prepare_claimed_file_task(
            db_path=db_path, task_id=task_id,
            configured_download_dir=configured_download_dir,
            expected_bytes=expected_bytes, processor=processor,
            project_root=project_root, reserve_bytes=reserve_bytes,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        logging.exception("Ошибка подготовки задачи %d", task_id)
    return task_id


async def run_queue_worker(
    *, stop: asyncio.Event, db_path: Path, configured_download_dir: str,
    expected_bytes: int, processor: FileProcessor, max_wait_minutes: int,
    idle_seconds: float = 1.0, project_root: Path = Path("."),
    reserve_bytes: int = 512 * 1024 * 1024,
) -> None:
    """Process tasks sequentially; do not spawn detached workers."""
    if idle_seconds <= 0:
        raise ValueError("idle_seconds должен быть положительным")
    while not stop.is_set():
        task_id = await process_next_queued_task(
            db_path=db_path, configured_download_dir=configured_download_dir,
            expected_bytes=expected_bytes, processor=processor,
            max_wait_minutes=max_wait_minutes, project_root=project_root,
            reserve_bytes=reserve_bytes,
        )
        if task_id is None:
            try:
                await asyncio.wait_for(stop.wait(), timeout=idle_seconds)
            except asyncio.TimeoutError:
                pass
