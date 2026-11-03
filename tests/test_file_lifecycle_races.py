"""Registered files must survive state changes made by a concurrent uploader."""
import asyncio
from pathlib import Path

from bot import file_lifecycle
from bot.storage import change_status, create_task, database


def test_registered_file_survives_immediate_upload_claim(tmp_path, monkeypatch):
    root = tmp_path / "downloads"
    root.mkdir()
    db_path = tmp_path / "bot.sqlite"
    with database(db_path) as db:
        task_id, _ = create_task(
            db, user_id=1, chat_id=2, message_id=3,
            callback_key="upload-race", source_url="https://youtu.be/x",
            media_key="x", variant="720p",
        )
        assert change_status(db, task_id, "queued", "downloading")

    original = file_lifecycle.mark_file_ready

    def publish_and_claim(db, task_id, ready_file):
        result = original(db, task_id, ready_file)
        if result:
            assert change_status(db, task_id, "upload_pending", "uploading")
        return result

    monkeypatch.setattr(file_lifecycle, "mark_file_ready", publish_and_claim)

    async def processor(workspace, task_id):
        (workspace / "video.mp4").write_bytes(b"video")
        return "video.mp4"

    assert asyncio.run(file_lifecycle.prepare_claimed_file_task(
        db_path=db_path, task_id=task_id,
        configured_download_dir=str(root),
        expected_bytes=1, reserve_bytes=0, processor=processor,
    ))
    with database(db_path) as db:
        status, stored_path = db.execute(
            "SELECT status,ready_file FROM tasks WHERE id=?", (task_id,)
        ).fetchone()
    assert status == "uploading"
    assert Path(stored_path).read_bytes() == b"video"


def test_registered_file_survives_immediate_cancellation(tmp_path, monkeypatch):
    root = tmp_path / "downloads"
    root.mkdir()
    db_path = tmp_path / "bot.sqlite"
    with database(db_path) as db:
        task_id, _ = create_task(
            db, user_id=1, chat_id=2, message_id=3,
            callback_key="cancel-race", source_url="https://youtu.be/x",
            media_key="x", variant="720p",
        )
        assert change_status(db, task_id, "queued", "downloading")

    original = file_lifecycle.mark_file_ready

    def publish_and_cancel(db, task_id, ready_file):
        result = original(db, task_id, ready_file)
        if result:
            assert change_status(db, task_id, "upload_pending", "cancelled")
        return result

    monkeypatch.setattr(file_lifecycle, "mark_file_ready", publish_and_cancel)

    async def processor(workspace, task_id):
        (workspace / "video.mp4").write_bytes(b"video")
        return "video.mp4"

    assert asyncio.run(file_lifecycle.prepare_claimed_file_task(
        db_path=db_path, task_id=task_id,
        configured_download_dir=str(root),
        expected_bytes=1, reserve_bytes=0, processor=processor,
    ))
    with database(db_path) as db:
        status, stored_path = db.execute(
            "SELECT status,ready_file FROM tasks WHERE id=?", (task_id,)
        ).fetchone()
    assert status == "cancelled"
    assert Path(stored_path).read_bytes() == b"video"
