"""Cancellation during a running offline IPC call revokes the reservation."""
import asyncio
from unittest.mock import patch

from bot.offline_queue_integration import process_one_offline_task
from bot.storage import create_task, database, cancel_task
from bot.worker_leases import offer_job, transition_job


def test_cancel_during_execution_revokes_ipc(tmp_path):
    db_path = tmp_path / "db.sqlite"
    with database(db_path) as db:
        task, _ = create_task(
            db, user_id=7, chat_id=7, message_id=7,
            callback_key="running", source_url="https://youtu.be/x",
            media_key="x", variant="MP3",
        )

    async def scenario():
        executing = asyncio.Event()
        released = asyncio.Event()
        revoked = []

        async def execute(*args, **kwargs):
            executing.set()
            try:
                await asyncio.Event().wait()
            finally:
                released.set()

        async def reserve(*args, **kwargs):
            return True

        async def revoke(socket, task_id, token, **kwargs):
            revoked.append(task_id)
            return True

        with patch("bot.offline_queue_integration.reserve_worker_job", side_effect=reserve), \
             patch("bot.offline_queue_integration.execute_offline_ipc", side_effect=execute), \
             patch("bot.offline_queue_integration.cancel_worker_reservation", side_effect=revoke):
            runner = asyncio.create_task(process_one_offline_task(
                db_path=db_path, socket_path=tmp_path / "worker.sock",
                configured_download_dir="downloads", project_root=tmp_path,
            ))
            await asyncio.wait_for(executing.wait(), timeout=2)
            with database(db_path) as db:
                assert cancel_task(db, task_id=task, user_id=7)
            assert await asyncio.wait_for(runner, timeout=3) == task
            assert released.is_set()
            assert task in revoked

    asyncio.run(scenario())
    with database(db_path) as db:
        assert db.execute("SELECT status FROM tasks WHERE id=?", (task,)).fetchone()[0] == "cancelled"
        assert db.execute("SELECT state FROM worker_job_leases WHERE task_id=?", (task,)).fetchone()[0] == "cancelled"
