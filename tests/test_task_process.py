import asyncio
import sys

import pytest

from bot.storage import cancel_task, change_status, create_task, database
from bot.task_process import TaskWasCancelled, run_task_process


def _task(path):
    with database(path) as db:
        task_id, _ = create_task(
            db, user_id=17, chat_id=2, message_id=3,
            callback_key="process-test", source_url="https://youtu.be/abc",
            media_key="abc", variant="720p",
        )
        assert change_status(db, task_id, "queued", "downloading")
    return task_id


def test_task_process_completes(tmp_path):
    db_path = tmp_path / "bot.sqlite"
    task_id = _task(db_path)
    result = asyncio.run(run_task_process(
        [sys.executable, "-c", "pass"], cwd=tmp_path,
        db_path=db_path, task_id=task_id, timeout_seconds=5, poll_seconds=0.05,
    ))
    assert result == 0


def test_task_process_rejects_cancelled_before_launch(tmp_path):
    db_path = tmp_path / "bot.sqlite"
    task_id = _task(db_path)
    with database(db_path) as db:
        assert cancel_task(db, task_id=task_id, user_id=17)
    with pytest.raises(TaskWasCancelled):
        asyncio.run(run_task_process(
            [sys.executable, "-c", "pass"], cwd=tmp_path,
            db_path=db_path, task_id=task_id, timeout_seconds=5,
        ))


def test_task_process_stops_after_database_cancel(tmp_path):
    db_path = tmp_path / "bot.sqlite"
    task_id = _task(db_path)

    async def scenario():
        running = asyncio.create_task(run_task_process(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            cwd=tmp_path, db_path=db_path, task_id=task_id,
            timeout_seconds=20, poll_seconds=0.05,
        ))
        await asyncio.sleep(0.25)
        with database(db_path) as db:
            assert cancel_task(db, task_id=task_id, user_id=17)
        with pytest.raises(TaskWasCancelled):
            await asyncio.wait_for(running, timeout=4)

    asyncio.run(scenario())


def test_task_process_rejects_unknown_task(tmp_path):
    with pytest.raises(ValueError, match="не найдена"):
        asyncio.run(run_task_process(
            [sys.executable, "-c", "pass"], cwd=tmp_path,
            db_path=tmp_path / "bot.sqlite", task_id=99, timeout_seconds=5,
        ))


def test_task_process_repeat_cancel_is_idempotent(tmp_path):
    db_path = tmp_path / "bot.sqlite"
    task_id = _task(db_path)
    with database(db_path) as db:
        assert cancel_task(db, task_id=task_id, user_id=17)
        assert not cancel_task(db, task_id=task_id, user_id=17)
    with pytest.raises(TaskWasCancelled):
        asyncio.run(run_task_process(
            [sys.executable, "-c", "pass"], cwd=tmp_path,
            db_path=db_path, task_id=task_id, timeout_seconds=5,
        ))


def test_task_process_reports_crash_without_changing_db_status(tmp_path):
    from bot.process_runner import ProcessExecutionError
    db_path = tmp_path / "bot.sqlite"
    task_id = _task(db_path)
    with pytest.raises(ProcessExecutionError):
        asyncio.run(run_task_process(
            [sys.executable, "-c", "raise SystemExit(7)"],
            cwd=tmp_path, db_path=db_path, task_id=task_id,
            timeout_seconds=5, poll_seconds=0.05,
        ))
    with database(db_path) as db:
        assert db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == "downloading"


def test_task_process_rejects_queued_task(tmp_path):
    db_path = tmp_path / "bot.sqlite"
    task_id = _task(db_path)
    with database(db_path) as db:
        assert change_status(db, task_id, "downloading", "queued")
    with pytest.raises(ValueError, match="не находится в обработке"):
        asyncio.run(run_task_process(
            [sys.executable, "-c", "pass"], cwd=tmp_path,
            db_path=db_path, task_id=task_id, timeout_seconds=5,
        ))
