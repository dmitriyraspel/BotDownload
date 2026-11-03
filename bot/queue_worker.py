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
