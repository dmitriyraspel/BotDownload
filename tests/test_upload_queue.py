import asyncio
from types import SimpleNamespace

from bot.download_storage import create_task_directory
from bot.storage import change_status, create_task, database, mark_file_ready
from bot.upload_queue import next_due_upload, run_upload_queue


def setup_task(db_path, root, key):
    with database(db_path) as db:
        task_id, _ = create_task(
            db, user_id=3, chat_id=123, message_id=5,
            callback_key=key, source_url="https://youtu.be/x",
            media_key=key, variant="720p",
        )
        assert change_status(db, task_id, "queued", "downloading")
        assert change_status(db, task_id, "downloading", "processing")
        folder = create_task_directory(root, str(task_id))
        (folder / "video.mp4").write_bytes(b"video")
        assert mark_file_ready(db, task_id, str(folder / "video.mp4"))
    return task_id


def test_upload_queue_skips_future_retry(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    db_path = tmp_path / "db.sqlite"
    first = setup_task(db_path, root, "first")
    second = setup_task(db_path, root, "second")
    with database(db_path) as db:
        db.execute(
            "UPDATE tasks SET next_upload_at='2999-01-01T00:00:00+00:00' WHERE id=?",
            (first,),
        )
    assert next_due_upload(db_path) == second


def test_upload_queue_processes_ready_tasks_sequentially(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    db_path = tmp_path / "db.sqlite"
    first = setup_task(db_path, root, "first")
    second = setup_task(db_path, root, "second")
    stop = asyncio.Event()
    calls = []

    class Bot:
        async def send_video(self, *, chat_id, video, supports_streaming):
            calls.append(video.path)
            if len(calls) == 2:
                stop.set()
            return SimpleNamespace(video=SimpleNamespace(file_id="tg-" + str(len(calls))))

    async def run():
        await asyncio.wait_for(run_upload_queue(
            stop=stop, bot=Bot(), db_path=db_path,
            configured_download_dir=str(root), max_bytes=100,
            max_attempts=2, second_attempt_delay_seconds=0,
            third_attempt_delay_seconds=0, idle_seconds=0.01,
        ), timeout=3)

    asyncio.run(run())
    assert len(calls) == 2
    with database(db_path) as db:
        assert db.execute(
            "SELECT status FROM tasks WHERE id=?", (first,)
        ).fetchone()[0] == "completed"
        assert db.execute(
            "SELECT status FROM tasks WHERE id=?", (second,)
        ).fetchone()[0] == "completed"


def test_upload_queue_stops_without_pending_tasks(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    stop = asyncio.Event()
    stop.set()

    async def run():
        await run_upload_queue(
            stop=stop, bot=object(), db_path=tmp_path / "db.sqlite",
            configured_download_dir=str(root), max_bytes=100,
            max_attempts=2, second_attempt_delay_seconds=0,
            third_attempt_delay_seconds=0,
        )

    asyncio.run(run())
