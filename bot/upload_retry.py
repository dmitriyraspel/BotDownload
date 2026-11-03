"""Persist bounded Telegram upload attempts and backoff.

An ambiguous network error can mean Telegram delivered the message. Retrying
may duplicate a delivery; no exactly-once guarantee is claimed.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .storage import database


def reserve_upload_attempt(
    db_path: Path, task_id: int, *,
    max_attempts: int,
) -> bool:
    """Atomically reserve one due upload attempt or fail exhausted tasks."""
    if max_attempts <= 0:
        raise ValueError("max_attempts должен быть положительным")
    with database(db_path) as db:
        db.execute("BEGIN IMMEDIATE") if not db.in_transaction else None
        row = db.execute(
            """SELECT upload_attempts,next_upload_at FROM tasks
            WHERE id=? AND status='upload_pending'""", (task_id,),
        ).fetchone()
        if row is None:
            return False
        attempts, next_at = row
        if attempts >= max_attempts:
            db.execute(
                "UPDATE tasks SET status='failed' WHERE id=? AND status='upload_pending'",
                (task_id,),
            )
            return False
        now = datetime.now(timezone.utc)
        if next_at and datetime.fromisoformat(next_at) > now:
            return False
        return db.execute(
            """UPDATE tasks SET upload_attempts=upload_attempts+1,
            next_upload_at=NULL WHERE id=? AND status='upload_pending'""",
            (task_id,),
        ).rowcount == 1


def schedule_upload_retry(
    db_path: Path, task_id: int, *,
    max_attempts: int, delay_seconds: int,
) -> bool:
    """Schedule retry after a failed send, or mark task permanently failed."""
    if max_attempts <= 0 or delay_seconds < 0:
        raise ValueError("Некорректные параметры повтора")
    with database(db_path) as db:
        row = db.execute(
            "SELECT upload_attempts FROM tasks WHERE id=? AND status='upload_pending'",
            (task_id,),
        ).fetchone()
        if row is None:
            return False
        if row[0] >= max_attempts:
            db.execute(
                "UPDATE tasks SET status='failed',next_upload_at=NULL WHERE id=? AND status='upload_pending'",
                (task_id,),
            )
            return False
        due = (datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)).isoformat()
        return db.execute(
            """UPDATE tasks SET next_upload_at=? WHERE id=? AND status='upload_pending'""",
            (due, task_id),
        ).rowcount == 1
