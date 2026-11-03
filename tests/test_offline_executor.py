"""Offline execution and conservative recovery tests."""
import asyncio
import math
import os

import pytest

from bot.offline_executor import OfflineExecutionError, execute_offline_job
from bot.storage import change_status, create_task, database
from bot.worker_leases import offer_job
from bot.worker_recovery import reconcile_worker_leases


def _private(tmp_path):
    path = tmp_path / "private"
    path.mkdir(mode=0o700)
    return path


def test_offline_execution_produces_bounded_file(tmp_path):
    workspace = _private(tmp_path)
    output = asyncio.run(execute_offline_job(workspace))
    assert output.read_bytes() == b"offline-worker-ok"
    assert output.stat().st_mode & 0o777 == 0o600


def test_offline_execution_rejects_existing_output(tmp_path):
    workspace = _private(tmp_path)
    (workspace / "offline-result.bin").write_text("existing")
    with pytest.raises(OfflineExecutionError):
        asyncio.run(execute_offline_job(workspace))


def test_offline_execution_pre_cancelled(tmp_path):
    workspace = _private(tmp_path)
    event = asyncio.Event()
    event.set()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(execute_offline_job(workspace, cancel=event))
    assert not list(workspace.iterdir())


@pytest.mark.parametrize("timeout", [0, -1, True, float("nan"), float("inf"), 3601])
def test_offline_execution_rejects_invalid_timeout(tmp_path, timeout):
    with pytest.raises(OfflineExecutionError):
        asyncio.run(execute_offline_job(_private(tmp_path), timeout_seconds=timeout))


@pytest.mark.parametrize("size", [0, -1, True, 1024*1024+1])
def test_offline_execution_rejects_invalid_size(tmp_path, size):
    with pytest.raises(OfflineExecutionError):
        asyncio.run(execute_offline_job(_private(tmp_path), max_output_bytes=size))


def test_offline_execution_rejects_public_workspace(tmp_path):
    workspace = _private(tmp_path)
    workspace.chmod(0o755)
    with pytest.raises(OfflineExecutionError):
        asyncio.run(execute_offline_job(workspace))


def test_recovery_expires_and_fails_abandoned_task(tmp_path):
    path = tmp_path / "db.sqlite"
    with database(path) as db:
        task, _ = create_task(
            db, user_id=1, chat_id=1, message_id=1,
            callback_key="recovery-1", source_url="https://example.com/",
            media_key="m", variant="video",
        )
        assert change_status(db, task, "queued", "downloading")
        assert offer_job(db, task, ttl_seconds=60)
        db.execute(
            "UPDATE worker_job_leases SET expires_at='2000-01-01T00:00:00+00:00' WHERE task_id=?",
            (task,),
        )
        result = reconcile_worker_leases(db)
        assert result == {"expired": 1, "revoked": 0, "failed": 1}
        assert db.execute("SELECT status FROM tasks WHERE id=?", (task,)).fetchone()[0] == "failed"
        assert reconcile_worker_leases(db) == {"expired": 0, "revoked": 0, "failed": 0}
