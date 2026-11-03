"""Bridge durable SQLite cancellation to an in-flight trusted subprocess.

Not wired into Telegram or the download engine. Never run untrusted network
commands without a separate network sandbox.
"""
import asyncio
from pathlib import Path
from collections.abc import Sequence

from .process_runner import run_bounded_process
from .storage import database, task_is_cancelled


class TaskWasCancelled(Exception):
    """The task was cancelled in persistent storage."""


def _cancelled(db_path: Path, task_id: int) -> bool:
    with database(db_path) as db:
        return task_is_cancelled(db, task_id)


async def run_task_process(
    argv: Sequence[str], *,
    cwd: Path,
    db_path: Path,
    task_id: int,
    timeout_seconds: float,
    poll_seconds: float = 0.2,
) -> int:
    """Stop a subprocess when its task is cancelled in SQLite.

    Only call for a previously claimed task. A missing task is an error,
    not evidence of cancellation. This function does not change task status.
    """
    if task_id <= 0 or not (0 < poll_seconds <= 60):
        raise ValueError("Некорректные параметры задачи")
    with database(db_path) as db:
        row = db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
    if row is None:
        raise ValueError("Задача не найдена")
    if row[0] == "cancelled":
        raise TaskWasCancelled("Задача отменена")
    if row[0] not in ("downloading", "processing"):
        raise ValueError("Задача не находится в обработке")

    process_task = asyncio.create_task(
        run_bounded_process(argv, cwd=cwd, timeout_seconds=timeout_seconds)
    )
    try:
        while True:
            done, _ = await asyncio.wait({process_task}, timeout=poll_seconds)
            if _cancelled(db_path, task_id):
                raise TaskWasCancelled("Задача отменена")
            if done:
                return await process_task
    finally:
        if not process_task.done():
            process_task.cancel()
        # Ensure the subprocess runner has time to reap the child.
        await asyncio.shield(asyncio.gather(process_task, return_exceptions=True))
