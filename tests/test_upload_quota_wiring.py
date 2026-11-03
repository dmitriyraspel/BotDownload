"""Configuration must reach the actual Telegram delivery claim."""
import asyncio
from unittest.mock import patch

from bot.upload_coordinator import upload_one_task
from bot.upload_queue import run_upload_queue
from bot.storage import database, create_task, change_status, mark_file_ready


def _task(path):
    with database(path) as db:
        task, _ = create_task(db, user_id=8, chat_id=8, message_id=8,
                              callback_key="quota", source_url="https://youtu.be/x",
                              media_key="x", variant="MP3")
        assert change_status(db, task, "queued", "downloading")
        assert change_status(db, task, "downloading", "processing")
        assert mark_file_ready(db, task, "/staged/audio.mp3")
    return task


def test_coordinator_forwards_quota_settings(tmp_path):
    path = tmp_path / "db.sqlite"
    task = _task(path)
    received = {}

    async def fake_delivery(**kwargs):
        received.update(kwargs)
        return True

    with patch("bot.upload_coordinator.deliver_pending_file", side_effect=fake_delivery):
        assert asyncio.run(upload_one_task(
            bot=object(), db_path=path, task_id=task,
            configured_download_dir="downloads", max_bytes=123,
            max_attempts=3, second_attempt_delay_seconds=1,
            third_attempt_delay_seconds=2, daily_limit=7,
            trusted_users=(8, 9)))
    assert received["daily_limit"] == 7
    assert received["trusted_users"] == (8, 9)


def test_queue_forwards_quota_settings(tmp_path):
    path = tmp_path / "db.sqlite"
    _task(path)
    received = {}

    async def fake_upload(**kwargs):
        received.update(kwargs)
        stop.set()
        return True

    async def runner():
        with patch("bot.upload_queue.upload_one_task", side_effect=fake_upload):
            await run_upload_queue(
                stop=stop, bot=object(), db_path=path,
                configured_download_dir="downloads", max_bytes=123,
                max_attempts=3, second_attempt_delay_seconds=1,
                third_attempt_delay_seconds=2, daily_limit=7,
                trusted_users=(8, 9))
    stop = asyncio.Event()
    asyncio.run(runner())
    assert received["daily_limit"] == 7
    assert received["trusted_users"] == (8, 9)
