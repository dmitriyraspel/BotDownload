"""End-to-end offline worker IPC and file staging tests."""
import asyncio
import os
from pathlib import Path

from bot.offline_queue_integration import process_one_offline_task
from bot.storage import create_task, database
from bot.worker_ipc import handle_connection
from bot.worker_offline import OfflineJobController
from bot.worker_reservations import JobReservations


def test_offline_queue_to_staged_file(tmp_path):
    db_path = tmp_path / "tasks.sqlite"
    root = tmp_path / "downloads"
    root.mkdir(mode=0o700)
    with database(db_path) as db:
        task, _ = create_task(
            db, user_id=1, chat_id=1, message_id=1,
            callback_key="offline-e2e", source_url="https://example.com/",
            media_key="fixture", variant="720p",
        )

    async def run():
        socket_path = tmp_path / "worker.sock"
        reservations = JobReservations()
        controller = OfflineJobController(reservations)
        server = await asyncio.start_unix_server(
            lambda r, w: handle_connection(
                r, w, allowed_uid=os.getuid(), db_path=db_path,
                reservations=reservations, offline=controller,
            ), path=str(socket_path),
        )
        try:
            assert await process_one_offline_task(
                db_path=db_path, socket_path=socket_path,
                configured_download_dir=str(root), reserve_bytes=0,
            ) == task
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(run())
    with database(db_path) as db:
        status, ready_file = db.execute(
            "SELECT status,ready_file FROM tasks WHERE id=?", (task,)
        ).fetchone()
        lease = db.execute(
            "SELECT state FROM worker_job_leases WHERE task_id=?", (task,)
        ).fetchone()[0]
    assert status == "upload_pending"
    assert lease == "finished"
    assert Path(ready_file).read_bytes() == b"offline-worker-ok"


def test_missing_worker_fails_claimed_task(tmp_path):
    db_path = tmp_path / "tasks.sqlite"
    root = tmp_path / "downloads"
    root.mkdir(mode=0o700)
    with database(db_path) as db:
        task, _ = create_task(
            db, user_id=1, chat_id=1, message_id=1,
            callback_key="offline-missing", source_url="https://example.com/",
            media_key="fixture", variant="480p",
        )
    assert asyncio.run(process_one_offline_task(
        db_path=db_path, socket_path=tmp_path / "missing.sock",
        configured_download_dir=str(root), reserve_bytes=0,
    )) == task
    with database(db_path) as db:
        assert db.execute(
            "SELECT status FROM tasks WHERE id=?", (task,)
        ).fetchone()[0] == "failed"
