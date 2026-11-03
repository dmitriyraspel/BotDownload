"""Stage one processed file and publish it in SQLite.

Not connected to Telegram, yt-dlp or a queue worker. The supplied processor
must be trusted and cancellation-aware; it returns a single basename.
"""
from collections.abc import Awaitable, Callable
from pathlib import Path

from .download_storage import cleanup_task_directory, download_root
from .ready_files import stage_ready_file
from .storage import change_status, database, mark_file_ready, task_is_cancelled
from .task_process import TaskWasCancelled
from .task_workspace import task_workspace

FileProcessor = Callable[[Path, int], Awaitable[str]]


async def prepare_claimed_file_task(
    *,
    db_path: Path,
    task_id: int,
    configured_download_dir: str,
    expected_bytes: int,
    processor: FileProcessor,
    project_root: Path = Path("."),
    reserve_bytes: int = 512 * 1024 * 1024,
) -> bool:
    """Return True when a ready file is durably published; False if cancelled."""
    with database(db_path) as db:
        row = db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
    if row is None or row[0] != "downloading":
        raise ValueError("Задача не захвачена для загрузки")

    staged = None
    try:
        with task_workspace(
            configured_download_dir, str(task_id), expected_bytes,
            project_root=project_root, reserve_bytes=reserve_bytes,
        ) as workspace:
            with database(db_path) as db:
                if task_is_cancelled(db, task_id):
                    return False
            filename = await processor(workspace, task_id)
            with database(db_path) as db:
                if task_is_cancelled(db, task_id):
                    return False
                if not change_status(db, task_id, "downloading", "processing"):
                    raise RuntimeError("Статус задачи изменился во время обработки")

            root = download_root(configured_download_dir, project_root)
            staged = stage_ready_file(root, workspace, filename, str(task_id))
            # The conditional UPDATE cannot overwrite a cancellation.
            with database(db_path) as db:
                if not mark_file_ready(db, task_id, str(staged)):
                    if task_is_cancelled(db, task_id):
                        return False
                    raise RuntimeError("Не удалось сохранить готовый файл")
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
    finally:
        if staged is not None:
            with database(db_path) as db:
                row = db.execute(
                    "SELECT ready_file,status FROM tasks WHERE id=?", (task_id,)
                ).fetchone()
            if row is None or row[0] != str(staged):
                root = download_root(configured_download_dir, project_root)
                cleanup_task_directory(root, staged.parent)
