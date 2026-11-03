"""Sequential upload worker must not spin on a quota-blocked task."""
import asyncio
from unittest.mock import patch

from bot.storage import database, create_task, change_status, mark_file_ready
from bot.upload_queue import next_due_upload, run_upload_queue


def _ready(db):
    task, _ = create_task(db, user_id=7, chat_id=7, message_id=7,
                          callback_key="ready", source_url="https://youtu.be/x",
                          media_key="x", variant="MP3")
    assert change_status(db, task, "queued", "downloading")
    assert change_status(db, task, "downloading", "processing")
    assert mark_file_ready(db, task, "/staged/audio.mp3")
    return task


def test_due_upload_skips_ambiguous_task(tmp_path):
    path = tmp_path / "db.sqlite"
    with database(path) as db:
        task = _ready(db)
    assert next_due_upload(path) == task
    with database(path) as db:
        assert change_status(db, task, "upload_pending", "uploading")
    assert next_due_upload(path) is None


def test_due_upload_skips_unstaged_task(tmp_path):
    path = tmp_path / "db.sqlite"
    with database(path) as db:
        task, _ = create_task(db, user_id=7, chat_id=7, message_id=7,
                              callback_key="empty", source_url="https://youtu.be/x",
                              media_key="x", variant="MP3")
        assert change_status(db, task, "queued", "downloading")
        assert change_status(db, task, "downloading", "processing")
        assert change_status(db, task, "processing", "upload_pending")
    assert next_due_upload(path) is None


def test_worker_waits_when_upload_not_delivered(tmp_path):
    path = tmp_path / "db.sqlite"
    with database(path) as db:
        _ready(db)
    calls = []

    async def blocked(**kwargs):
        calls.append(kwargs["task_id"])
        return False

    async def run():
        stop = asyncio.Event()
        async def stop_after_delay():
            await asyncio.sleep(0.035)
            stop.set()
        stopper = asyncio.create_task(stop_after_delay())
        with patch("bot.upload_queue.upload_one_task", side_effect=blocked):
            await run_upload_queue(
                stop=stop, bot=object(), db_path=path,
                configured_download_dir="downloads", max_bytes=100,
                max_attempts=2, second_attempt_delay_seconds=0,
                third_attempt_delay_seconds=0, idle_seconds=0.1)
        await stopper
    asyncio.run(run())
    assert calls == [1]
