"""Sequential upload queue started by Telegram polling.

Upload attempts and retry deadlines live in SQLite. This worker never deletes
files and must not run alongside another uploader for the same database.
"""
import asyncio
import logging
from pathlib import Path

from .storage import database
from .upload_coordinator import upload_one_task


def next_due_upload(db_path: Path) -> int | None:
    """Read the oldest due staged task without changing its status."""
    with database(db_path) as db:
        row = db.execute(
            """SELECT id FROM tasks
            WHERE status='upload_pending'
              AND ready_file IS NOT NULL AND ready_file != ''
              AND (next_upload_at IS NULL OR julianday(next_upload_at) <= julianday('now'))
            ORDER BY created_at,id LIMIT 1"""
        ).fetchone()
        return row[0] if row else None


async def run_upload_queue(
    *, stop: asyncio.Event, bot, db_path: Path,
    configured_download_dir: str, max_bytes: int, max_attempts: int,
    second_attempt_delay_seconds: int, third_attempt_delay_seconds: int,
    idle_seconds: float = 1.0, project_root: Path = Path("."),
    daily_limit: int = 3, trusted_users: tuple[int, ...] = (),
) -> None:
    """Send one pending file at a time, waiting when no upload is due."""
    if idle_seconds <= 0:
        raise ValueError("idle_seconds должен быть положительным")
    while not stop.is_set():
        task_id = next_due_upload(db_path)
        if task_id is not None:
            try:
                delivered = await upload_one_task(
                    bot=bot, db_path=db_path, task_id=task_id,
                    configured_download_dir=configured_download_dir,
                    max_bytes=max_bytes, max_attempts=max_attempts,
                    second_attempt_delay_seconds=second_attempt_delay_seconds,
                    third_attempt_delay_seconds=third_attempt_delay_seconds,
                    project_root=project_root,
                    daily_limit=daily_limit, trusted_users=trusted_users,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.exception("Необработанная ошибка очереди отправки задачи %d", task_id)
                delivered = False
            if delivered:
                continue
            # Quota exhaustion and failed preflight leave a pending task.
            # Back off instead of spinning on the same task indefinitely.
        try:
            await asyncio.wait_for(stop.wait(), timeout=idle_seconds)
        except asyncio.TimeoutError:
            pass
