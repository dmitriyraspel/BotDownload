import asyncio

import pytest

from bot.storage import cancel_task, change_status, create_task, database
from bot.task_lifecycle import prepare_claimed_task


def claimed(path):
    with database(path) as db:
        task_id, _ = create_task(
            db, user_id=31, chat_id=1, message_id=1,
            callback_key="lifecycle", source_url="https://youtu.be/a",
            media_key="a", variant="720p",
        )
        assert change_status(db, task_id, "queued", "downloading")
    return task_id


def status(path, task_id):
    with database(path) as db:
        return db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0]


def run(path, task_id, root, processor):
    root.mkdir(parents=True, exist_ok=True)
    return asyncio.run(prepare_claimed_task(
        db_path=path, task_id=task_id,
        configured_download_dir=str(root), expected_bytes=0,
        reserve_bytes=0, processor=processor,
    ))


def test_lifecycle_success_cleans_workspace(tmp_path):
    path, root = tmp_path / "db.sqlite", tmp_path / "downloads"
    task_id = claimed(path)

    async def processor(workspace, task_id):
        (workspace / "temporary.txt").write_text("ok")

    assert run(path, task_id, root, processor)
    assert status(path, task_id) == "upload_pending"
    assert not list(root.iterdir())


def test_lifecycle_failure_cleans_workspace(tmp_path):
    path, root = tmp_path / "db.sqlite", tmp_path / "downloads"
    task_id = claimed(path)

    async def processor(workspace, task_id):
        (workspace / "temporary.txt").write_text("ok")
        raise RuntimeError("processor crashed")

    with pytest.raises(RuntimeError, match="crashed"):
        run(path, task_id, root, processor)
    assert status(path, task_id) == "failed"
    assert not list(root.iterdir())


def test_lifecycle_cancellation_preserves_cancelled(tmp_path):
    path, root = tmp_path / "db.sqlite", tmp_path / "downloads"
    task_id = claimed(path)

    async def processor(workspace, task_id):
        (workspace / "temporary.txt").write_text("ok")
        with database(path) as db:
            assert cancel_task(db, task_id=task_id, user_id=31)

    assert not run(path, task_id, root, processor)
    assert status(path, task_id) == "cancelled"
    assert not list(root.iterdir())


def test_lifecycle_rejects_unclaimed_task(tmp_path):
    path = tmp_path / "db.sqlite"
    task_id = claimed(path)
    with database(path) as db:
        assert change_status(db, task_id, "downloading", "queued")

    async def processor(workspace, task_id):
        raise AssertionError("must not execute")

    with pytest.raises(ValueError, match="не захвачена"):
        run(path, task_id, tmp_path / "downloads", processor)
    assert status(path, task_id) == "queued"
