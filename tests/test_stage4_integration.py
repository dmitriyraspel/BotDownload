"""Final integration: durable restart and background task supervision."""
import asyncio
from unittest.mock import patch

import pytest

from bot.startup_recovery import recover_before_workers
from bot.worker_crash_recovery import reconcile_confirmed_worker_exit
from bot.storage import create_task, database, change_status
from bot.worker_leases import offer_job, transition_job


def test_restart_then_confirmed_crash_is_idempotent(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    path = tmp_path / "db.sqlite"
    with database(path) as db:
        task, _ = create_task(
            db, user_id=1, chat_id=1, message_id=1,
            callback_key="final-integration", source_url="https://youtu.be/x",
            media_key="x", variant="MP3",
        )
        assert change_status(db, task, "queued", "downloading")
        token = offer_job(db, task)
        assert token
        assert transition_job(db, task, token, "offered", "running")
    assert recover_before_workers(path, str(root)).requeued == 0
    assert recover_before_workers(path, str(root)).requeued == 0
    assert reconcile_confirmed_worker_exit(path) == 1
    assert reconcile_confirmed_worker_exit(path) == 0
    with database(path) as db:
        assert db.execute("SELECT status FROM tasks WHERE id=?", (task,)).fetchone()[0] == "failed"
        assert not transition_job(db, task, token, "running", "finished")


def test_idle_maintenance_is_repeatable(tmp_path):
    from bot.queue_maintenance import maintain_queue
    path = tmp_path / "db.sqlite"
    assert maintain_queue(path) == (0, 0)
    assert maintain_queue(path) == (0, 0)
