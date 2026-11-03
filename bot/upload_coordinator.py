"""Opt-in upload coordinator; not started by Telegram polling.

Attempts are reserved durably before calling Telegram. An ambiguous timeout
may mean Telegram delivered the file, so retrying can produce duplicates.
"""
import logging
from pathlib import Path

from .file_delivery import deliver_pending_file
from .telegram_sender import send_staged_file
from .upload_retry import reserve_upload_attempt, schedule_upload_retry


async def upload_one_task(
    *, bot, db_path: Path, task_id: int, configured_download_dir: str,
    max_bytes: int, max_attempts: int,
    second_attempt_delay_seconds: int,
    third_attempt_delay_seconds: int,
    project_root: Path = Path("."),
    daily_limit: int = 3, trusted_users: tuple[int, ...] = (),
) -> bool:
    """Return True only on confirmed delivery; otherwise False.

    Ambiguous Telegram errors are logged and quarantined, never auto-retried.
    No file is removed here. The caller must not run concurrent upload
    coordinators for the same task.
    """
    if max_attempts <= 0 or second_attempt_delay_seconds < 0 or third_attempt_delay_seconds < 0:
        raise ValueError("Некорректные параметры повторной отправки")
    if not reserve_upload_attempt(db_path, task_id, max_attempts=max_attempts):
        return False

    async def sender(chat_id: int, path: Path) -> str:
        return await send_staged_file(bot, chat_id, path)

    try:
        return await deliver_pending_file(
            db_path=db_path, task_id=task_id,
            configured_download_dir=configured_download_dir,
            sender=sender, max_bytes=max_bytes,
            project_root=project_root,
            daily_limit=daily_limit, trusted_users=trusted_users,
        )
    except Exception:
        from .storage import database
        with database(db_path) as db:
            row = db.execute(
                "SELECT upload_attempts,status FROM tasks WHERE id=?", (task_id,),
            ).fetchone()
        if row is not None and row[1] == "upload_pending":
            delay = (second_attempt_delay_seconds if row[0] == 1
                     else third_attempt_delay_seconds)
            schedule_upload_retry(
                db_path, task_id, max_attempts=max_attempts,
                delay_seconds=delay,
            )
        logging.exception("Ошибка отправки задачи %d в Telegram", task_id)
        return False
