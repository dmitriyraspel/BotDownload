"""Regression tests for runtime upload configuration and worker resilience."""
import asyncio
from unittest.mock import patch

from bot.storage import database, create_task, change_status, mark_file_ready
from bot.upload_queue import run_upload_queue


def test_main_passes_quota_to_upload_worker():
    from bot.main import run_bot
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    settings = SimpleNamespace(token="123:TEST", data={
        "telegram": {"api_mode": "cloud", "max_upload_size_mb": {"cloud": 50}},
        "storage": {"download_dir": "data/downloads"},
        "telegram_upload_max_attempts": 3,
        "telegram_upload_second_attempt_delay_seconds": 10,
        "telegram_upload_third_attempt_delay_seconds": 30,
        "limits": {"daily_download_limit": 7},
        "trusted_users": [101, 102],
    })
    received = {}
    async def fake_queue(**kwargs):
        received.update(kwargs)
        await kwargs["stop"].wait()
    async def fake_polling(*args, **kwargs):
        return None
    with patch("bot.main.Bot") as bot_class, patch("bot.main.Dispatcher") as dispatcher_class:
        bot_class.return_value.session.close = AsyncMock()
        dispatcher_class.return_value.start_polling = fake_polling
        with patch("bot.main.run_upload_queue", side_effect=fake_queue):
            with patch("bot.main.OfflineWorkerSupervisor") as supervisor:
                supervisor.return_value.start = AsyncMock()
                supervisor.return_value.stop = AsyncMock()
                async def fake_worker_wait():
                    await asyncio.Event().wait()
                supervisor.return_value.wait = AsyncMock(side_effect=fake_worker_wait)
                asyncio.run(run_bot(settings))
                supervisor.return_value.start.assert_awaited_once()
                supervisor.return_value.stop.assert_awaited_once()
    assert received["daily_limit"] == 7
    assert received["trusted_users"] == (101, 102)


def test_worker_survives_unexpected_upload_exception(tmp_path):
    path = tmp_path / "db.sqlite"
    with database(path) as db:
        task, _ = create_task(db, user_id=1, chat_id=1, message_id=1,
                              callback_key="failure", source_url="https://youtu.be/x",
                              media_key="x", variant="MP3")
        assert change_status(db, task, "queued", "downloading")
        assert change_status(db, task, "downloading", "processing")
        assert mark_file_ready(db, task, "/staged/file.mp3")
    calls = []
    async def fail(**kwargs):
        calls.append(kwargs["task_id"])
        raise RuntimeError("unexpected")
    async def runner():
        stop = asyncio.Event()
        async def stop_soon():
            await asyncio.sleep(0.025)
            stop.set()
        stopper = asyncio.create_task(stop_soon())
        with patch("bot.upload_queue.upload_one_task", side_effect=fail):
            await run_upload_queue(
                stop=stop, bot=object(), db_path=path,
                configured_download_dir="downloads", max_bytes=50,
                max_attempts=3, second_attempt_delay_seconds=1,
                third_attempt_delay_seconds=2, idle_seconds=0.1)
        await stopper
    asyncio.run(runner())
    assert calls == [task]
