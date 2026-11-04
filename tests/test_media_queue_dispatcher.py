"""Media queue IPC integration is fail-closed."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

from bot.media_queue_dispatcher import process_one_media_task, run_media_dispatcher
from bot.storage import create_task, database


def _task(path):
    with database(path) as db:
        return create_task(db, user_id=1, chat_id=1, message_id=1,
                           callback_key="media-stage2", source_url="https://youtu.be/abc",
                           media_key="abc", variant="MP3")[0]


def test_media_queue_reserves_then_fails_closed(tmp_path):
    path = tmp_path / "db.sqlite"
    task = _task(path)
    async def scenario():
        reserve = AsyncMock(return_value=True)
        revoke = AsyncMock(return_value=True)
        with patch("bot.media_queue_dispatcher.reserve_worker_job", reserve), patch("bot.media_queue_dispatcher.cancel_worker_reservation", revoke):
            assert await process_one_media_task(db_path=path, socket_path=Path("/tmp/test.sock")) == task
        reserve.assert_awaited_once()
        revoke.assert_awaited_once()
    asyncio.run(scenario())
    with database(path) as db:
        assert db.execute("SELECT status,ready_file FROM tasks WHERE id=?", (task,)).fetchone() == ("failed", None)
        assert db.execute("SELECT state FROM worker_job_leases WHERE task_id=?", (task,)).fetchone()[0] == "cancelled"


def test_rejected_reservation_never_publishes_file(tmp_path):
    path = tmp_path / "db.sqlite"
    task = _task(path)
    async def scenario():
        with patch("bot.media_queue_dispatcher.reserve_worker_job", AsyncMock(return_value=False)), patch("bot.media_queue_dispatcher.cancel_worker_reservation", AsyncMock()):
            assert await process_one_media_task(db_path=path, socket_path=Path("/tmp/test.sock")) == task
    asyncio.run(scenario())
    with database(path) as db:
        assert db.execute("SELECT status,ready_file FROM tasks WHERE id=?", (task,)).fetchone() == ("failed", None)


def test_empty_queue_and_stop(tmp_path):
    path = tmp_path / "db.sqlite"
    async def scenario():
        assert await process_one_media_task(db_path=path, socket_path=Path("/tmp/test.sock")) is None
        stop = asyncio.Event()
        stop.set()
        await run_media_dispatcher(stop=stop, db_path=path, socket_path=Path("/tmp/test.sock"))
    asyncio.run(scenario())
