"""Offline guard tests for the opt-in crash/restart probe."""
import asyncio
from unittest.mock import patch

import pytest

from bot.media_worker_crash_smoke import descendants, run


def test_descendants_does_not_include_self():
    import os
    assert os.getpid() not in descendants(os.getpid())


def test_crash_probe_refuses_root():
    with patch("bot.media_worker_crash_smoke.os.geteuid", return_value=0):
        with pytest.raises(RuntimeError, match="unprivileged"):
            asyncio.run(run("https://www.youtube.com/watch?v=jNQXAC9IVRw"))


@pytest.mark.parametrize("wait", [0, 4, 121])
def test_crash_probe_rejects_invalid_wait(wait):
    with patch("bot.media_worker_crash_smoke.os.geteuid", return_value=1001):
        with pytest.raises(ValueError, match="wait_seconds"):
            asyncio.run(run("https://www.youtube.com/watch?v=jNQXAC9IVRw", wait))


def test_crash_probe_refuses_loopback():
    with pytest.raises(Exception):
        asyncio.run(run("http://127.0.0.1/private"))


def test_revoking_lease_twice_is_idempotent(tmp_path):
    from bot.storage import create_task, database, change_status
    from bot.worker_leases import offer_job, cancel_job
    db_path = tmp_path / "lease.sqlite"
    with database(db_path) as db:
        task_id, _ = create_task(
            db, user_id=1, chat_id=1, message_id=1,
            callback_key="crash-lease-idempotent",
            source_url="https://www.youtube.com/watch?v=jNQXAC9IVRw",
            media_key="crash", variant="video",
        )
        assert change_status(db, task_id, "queued", "downloading")
        assert offer_job(db, task_id)
    with database(db_path) as db:
        assert cancel_job(db, task_id)
    with database(db_path) as db:
        assert cancel_job(db, task_id) is False
        assert db.execute(
            "SELECT state FROM worker_job_leases WHERE task_id=?", (task_id,)
        ).fetchone() == ("cancelled",)
