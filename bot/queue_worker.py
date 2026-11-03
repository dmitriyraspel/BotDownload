"""Single-step queue runner. Downloads remain intentionally disabled.

This module does not execute yt-dlp, FFmpeg, or make network requests.
"""
from pathlib import Path

from .storage import (
    change_status,
    claim_next_task,
    database,
    task_is_cancelled,
)


def process_next_disabled(db_path: Path, *, max_wait_minutes: int = 30) -> int | None:
    """Claim one task and fail it safely while downloads are disabled.

    This is an explicit maintenance/testing entrypoint, NOT a background
    consumer: calling it will mark a queued task as failed.
    """
    with database(db_path) as db:
        task_id = claim_next_task(db, max_wait_minutes=max_wait_minutes)
        if task_id is None:
            return None
        if not task_is_cancelled(db, task_id):
            change_status(db, task_id, "downloading", "failed")
        return task_id
