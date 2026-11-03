"""Lifecycle for a previously claimed task; no download or upload wiring.

The injected processor must be trusted and cancellation-aware. It must not
start detached processes or perform network access without sandboxing.
"""
import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from .storage import change_status, database, task_is_cancelled
from .task_process import TaskWasCancelled
from .task_workspace import task_workspace

Processor = Callable[[Path, int], Awaitable[None]]


async def prepare_claimed_task(
    *,
    db_path: Path,
    task_id: int,
    configured_download_dir: str,
    expected_bytes: int,
    processor: Processor,
    project_root: Path = Path("."),
    reserve_bytes: int = 512 * 1024 * 1024,
) -> bool:
    """Prepare one already-claimed task and transition to upload_pending.

    Returns False when the task was cancelled. Does not claim queue entries,
    download media, upload files, or retain the temporary workspace.
    """
    with database(db_path) as db:
        row = db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
    if row is None or row[0] != "downloading":
        raise ValueError("Задача не захвачена для загрузки")

    try:
        with task_workspace(
            configured_download_dir, str(task_id), expected_bytes,
            project_root=project_root, reserve_bytes=reserve_bytes,
        ) as workspace:
            with database(db_path) as db:
                if task_is_cancelled(db, task_id):
                    return False
            await processor(workspace, task_id)
            with database(db_path) as db:
                if task_is_cancelled(db, task_id):
                    return False
                if not change_status(db, task_id, "downloading", "processing"):
                    raise RuntimeError("Статус задачи изменился во время обработки")
                if not change_status(db, task_id, "processing", "upload_pending"):
                    raise RuntimeError("Не удалось завершить подготовку")
        return True
    except TaskWasCancelled:
        with database(db_path) as db:
            if task_is_cancelled(db, task_id):
                return False
        raise
    except BaseException:
        with database(db_path) as db:
            if not task_is_cancelled(db, task_id):
                for status in ("downloading", "processing"):
                    if change_status(db, task_id, status, "failed"):
                        break
        raise
