import asyncio

import pytest

from bot.file_lifecycle import prepare_claimed_file_task
from bot.storage import cancel_task, change_status, create_task, database, get_pending_file


def setup_task(db_path):
    with database(db_path) as db:
        task_id, _ = create_task(
            db, user_id=12, chat_id=3, message_id=4,
            callback_key="file-lifecycle", source_url="https://youtu.be/x",
            media_key="x", variant="720p",
        )
        assert change_status(db, task_id, "queued", "downloading")
    return task_id


def run(db_path, task_id, root, processor):
    return asyncio.run(prepare_claimed_file_task(
        db_path=db_path, task_id=task_id,
        configured_download_dir=str(root),
        expected_bytes=1, reserve_bytes=0, processor=processor,
    ))


def test_file_lifecycle_publishes_and_retains_file(tmp_path):
    db_path, root = tmp_path / "db.sqlite", tmp_path / "downloads"
    root.mkdir()
    task_id = setup_task(db_path)

    async def processor(workspace, task_id):
        (workspace / "video.mp4").write_bytes(b"ready")
        return "video.mp4"

    assert run(db_path, task_id, root, processor)
    with database(db_path) as db:
        path = get_pending_file(db, task_id)
    assert path is not None
    assert __import__("pathlib").Path(path).read_bytes() == b"ready"
    assert len(list(root.iterdir())) == 1


def test_file_lifecycle_cancelled_removes_workspace(tmp_path):
    db_path, root = tmp_path / "db.sqlite", tmp_path / "downloads"
    root.mkdir()
    task_id = setup_task(db_path)

    async def processor(workspace, task_id):
        (workspace / "video.mp4").write_bytes(b"ready")
        with database(db_path) as db:
            assert cancel_task(db, task_id=task_id, user_id=12)
        return "video.mp4"

    assert not run(db_path, task_id, root, processor)
    with database(db_path) as db:
        assert get_pending_file(db, task_id) is None
    assert not list(root.iterdir())


def test_file_lifecycle_bad_output_fails_and_cleans(tmp_path):
    db_path, root = tmp_path / "db.sqlite", tmp_path / "downloads"
    root.mkdir()
    task_id = setup_task(db_path)

    async def processor(workspace, task_id):
        (workspace / "video.mp4").write_bytes(b"ready")
        return "../video.mp4"

    with pytest.raises(Exception):
        run(db_path, task_id, root, processor)
    with database(db_path) as db:
        assert db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == "failed"
    assert not list(root.iterdir())
