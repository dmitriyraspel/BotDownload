"""Opt-in delivery of one staged file, with durable SQLite state transitions.

The sender is injected; this module does not start Telegram polling or downloads.
Do not run multiple upload workers for the same task.
"""
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path

from .download_storage import download_root
from .ready_recovery import valid_ready_file
from .storage import (change_status, database, claim_upload_task,
                      complete_reserved_delivery)

FileSender = Callable[[int, Path], Awaitable[str]]


async def deliver_pending_file(
    *, db_path: Path, task_id: int, configured_download_dir: str,
    sender: FileSender, max_bytes: int,
    project_root: Path = Path("."),
    daily_limit: int = 3,
    trusted_users: tuple[int, ...] = (),
) -> bool:
    """Send a registered file once. False means not delivered.

    Sender(task_chat_id, validated_path) must return a Telegram file_id only
    after Telegram confirms the upload. Failed sends remain retryable.
    """
    if max_bytes <= 0:
        raise ValueError("max_bytes должен быть положительным")
    root = download_root(configured_download_dir, project_root)
    with database(db_path) as db:
        row = db.execute(
            "SELECT chat_id,ready_file FROM tasks WHERE id=? AND status='upload_pending'",
            (task_id,),
        ).fetchone()
        if row is None:
            return False
        chat_id, stored_path = row
        if not stored_path or not valid_ready_file(root, task_id, stored_path):
            change_status(db, task_id, "upload_pending", "failed")
            return False
        path = Path(stored_path)
        if path.stat().st_size > max_bytes:
            change_status(db, task_id, "upload_pending", "failed")
            return False
        utc_day = datetime.now(timezone.utc).date().isoformat()
        if not claim_upload_task(db, task_id=task_id, utc_day=utc_day,
                                 daily_limit=daily_limit,
                                 trusted_users=trusted_users):
            return False

    try:
        telegram_file_id = await sender(chat_id, path)
        if not isinstance(telegram_file_id, str) or not telegram_file_id.strip():
            raise ValueError("Отправитель не вернул Telegram file_id")
    except Exception:
        # Telegram may have accepted the message before the connection failed.
        # Keep the reservation and quarantine the ambiguous task.
        raise

    with database(db_path) as db:
        return complete_reserved_delivery(
            db, task_id=task_id, telegram_file_id=telegram_file_id,
        )
