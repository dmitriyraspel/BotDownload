import asyncio

from bot.download_storage import create_task_directory
from bot.storage import (
    change_status, create_task, database, mark_file_ready,
    recover_interrupted_tasks,
)
from bot.upload_coordinator import upload_one_task


def test_cancelled_upload_quarantines_ambiguous_delivery_after_restart(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    db_path = tmp_path / "db.sqlite"
    with database(db_path) as db:
        task_id, _ = create_task(
            db, user_id=1, chat_id=2, message_id=3,
            callback_key="shutdown-upload", source_url="https://youtu.be/x",
            media_key="x", variant="720p",
        )
        assert change_status(db, task_id, "queued", "downloading")
        assert change_status(db, task_id, "downloading", "processing")
        folder = create_task_directory(root, str(task_id))
        path = folder / "video.mp4"
        path.write_bytes(b"video")
        assert mark_file_ready(db, task_id, str(path))

    async def scenario():
        started = asyncio.Event()

        class Bot:
            async def send_video(self, **kwargs):
                started.set()
                await asyncio.Event().wait()

        worker = asyncio.create_task(upload_one_task(
            bot=Bot(), db_path=db_path, task_id=task_id,
            configured_download_dir=str(root), max_bytes=100,
            max_attempts=2, second_attempt_delay_seconds=1,
            third_attempt_delay_seconds=1,
        ))
        await asyncio.wait_for(started.wait(), timeout=2)
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())
    assert path.read_bytes() == b"video"
    with database(db_path) as db:
        assert db.execute(
            "SELECT status FROM tasks WHERE id=?", (task_id,)
        ).fetchone()[0] == "uploading"
        assert recover_interrupted_tasks(db) == 0
    with database(db_path) as db:
        assert db.execute(
            "SELECT status FROM tasks WHERE id=?", (task_id,)
        ).fetchone()[0] == "uploading"
